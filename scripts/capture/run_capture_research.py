from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import re
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.jsonl import append_jsonl
from common.paths import load_json, safe_slug, standard_procurement_paths, today_local_str, utc_now_iso, write_json, write_text
from common.validation import validate_capture_brief_text
from capture.capture_decision import build_capture_decision_sections
from capture.fetch_notice_attachments import fetch_notice_attachments, load_local_attachments
from capture.fetch_notice_context import load_notice_context
from capture.fetch_public_context import fetch_public_research, fetch_url_excerpt
from capture.render_capture_brief import render_capture_brief
from capture.resolve_entry import resolve_entry
from capture.usaspending_enrich import enrich_from_usaspending

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
CONTACT_WITH_ROLE_RE = re.compile(
    r"(?P<name>[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+),\s*"
    r"(?P<role>Contracting Officer|Contract Specialist|Program Manager|Project Officer|Point of Contact|Technical Point of Contact|Small Business Specialist|Contract Officer)"
    r"(?P<suffix>[^@]{0,80}?)\s*,?\s*(?P<email>[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)
SIGNAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "under",
    "through",
    "support",
    "services",
    "service",
    "program",
    "system",
    "task",
    "order",
    "combined",
    "synopsis",
    "solicitation",
    "request",
    "proposal",
    "notice",
    "amendment",
    "department",
    "agency",
    "office",
    "federal",
    "national",
    "space",
    "based",
}
OBJECTIVE_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
OBJECTIVE_STRUCTURED_SPLIT_RE = re.compile(
    r"(?=\b(?:CLIN\s+\d{3,4}[A-Z]?|SubCLIN\s+\d{3,4}[A-Z]?|Task\s+\d+(?:\.\d+)?|Subtask\s+\d+(?:\.\d+)?|PWS(?:\s+Section)?\s+\d+(?:\.\d+)?|Section\s+\d+(?:\.\d+)?|Performance Objective(?:\s+\d+)?|Deliverable(?:s)?|Transition(?:\s+Plan)?|Period of Performance)\b)",
    re.IGNORECASE,
)
OBJECTIVE_KEYWORDS = (
    "shall",
    "must",
    "support",
    "provide",
    "deliver",
    "maintain",
    "ensure",
    "comply",
    "transition",
    "report",
    "staff",
    "license",
    "security",
    "privacy",
    "integration",
    "training",
    "availability",
    "quality",
)
OBJECTIVE_ROW_PREFIX_RE = re.compile(
    r"^\s*(?:CLIN\s+\d{3,4}[A-Z]?|SubCLIN\s+\d{3,4}[A-Z]?|Task\s+\d+(?:\.\d+)?|Subtask\s+\d+(?:\.\d+)?|PWS(?:\s+Section)?\s+\d+(?:\.\d+)?|Section\s+\d+(?:\.\d+)?|Performance Objective(?:\s+\d+)?|Deliverable(?:s)?|Transition(?:\s+Plan)?|Period of Performance)\b",
    re.IGNORECASE,
)
OBJECTIVE_SECTION_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+){0,3}\s+[A-Z][A-Za-z0-9/\-() ,]+$")
OBJECTIVE_TOC_LINE_RE = re.compile(r"\.{5,}\s*\d+\s*$")
OBJECTIVE_TABLE_CELL_SPLIT_RE = re.compile(r"\s*(?:\||\t| {2,})\s*")
OBJECTIVE_HEADING_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s+(.+?)\s*$")
OBJECTIVE_BOILERPLATE_MARKERS = (
    "request for information",
    "responses are due",
    "questions are due",
    "proposal due",
    "offeror",
    "offerors",
    "amendment",
    "sam.gov",
    "point of contact",
    "contract specialist",
    "standard form 30",
    "questions and answers",
    "vendor question",
)
OBJECTIVE_MIN_REQUIREMENT_OVERLAP = 2
OBJECTIVE_ADMIN_TOKENS = {
    "offeror",
    "offerors",
    "proposal",
    "questions",
    "question",
    "amendment",
    "contracting",
    "notice",
}
OBJECTIVE_PREFERRED_SECTION_HINTS = (
    "scope",
    "general requirements",
    "deliverables",
    "tasks",
    "task requirements",
    "specific tasks",
    "services required",
    "performance objectives",
    "requirements",
)
OBJECTIVE_DEMOTED_SECTION_HINTS = (
    "introduction",
    "background",
    "general information",
    "purpose",
    "authority",
    "key personnel",
)
OBJECTIVE_EXTRA_ACTION_VERBS = (
    "perform",
    "operate",
    "manage",
    "execute",
    "sustain",
    "administer",
)
OBJECTIVE_DECOMPOSITION_FALLBACK = "Objective decomposition incomplete from current artifacts; validate SOW/PWS task structure manually."
NO_MISSION_DRIVER = "No corroborated mission driver found for this objective in current public research."
NO_BUDGET_SIGNAL = "No objective-specific budget signal found in current evidence."
NO_EVIDENCE_SNIPPET = "No corroborated evidence snippet found for this objective in this run."
NO_WIN_THEMES = "Insufficient corroborated evidence to recommend win themes yet."
NO_PROOF_POINTS = "Insufficient corroborated evidence to recommend proof points yet."
NO_FUNDING_CORROBORATION = "No funding corroboration found in current run; validate with award history, budget docs, or priced attachments."
INCUMBENT_UNVERIFIED = "Incumbent unverified in current evidence."
NO_OBJECTIVE_KPIS = "No objective-specific KPI signal found in current evidence."
NO_SOLUTION_IMPLICATIONS = "Do not infer solution implications until the SOW/PWS task structure is validated."


def request_id_for(entry_value: str) -> str:
    timestamp = utc_now_iso().replace("-", "").replace(":", "").replace("T", "").replace("Z", "")
    return f"req-{timestamp[:12]}-{safe_slug(entry_value, 12)}"


def build_request_paths(workspace: Path, digest_date: str, display_entry: str, canonical_id: str, request_id: str) -> dict[str, str]:
    canonical_slug = safe_slug(canonical_id or "item", 24)
    display_slug = safe_slug(display_entry or "direct", 12)
    brief_dir = workspace / "procurement" / "capture-briefs" / digest_date
    evidence_dir = workspace / "procurement" / "capture-evidence" / digest_date
    specific_brief = brief_dir / f"{display_slug}-{canonical_slug}-{request_id}.md"
    specific_evidence = evidence_dir / f"{display_slug}-{canonical_slug}-{request_id}.json"
    alias_brief = brief_dir / f"{display_slug}-{canonical_slug}.md"
    alias_evidence = evidence_dir / f"{display_slug}-{canonical_slug}.json"
    return {
        "request_log_path": (workspace / "procurement" / "capture-requests.jsonl").as_posix(),
        "digest_entry_map_path": (workspace / "procurement" / "digest-entry-map" / f"{digest_date}.json").as_posix(),
        "request_capture_brief_path": specific_brief.as_posix(),
        "request_capture_evidence_path": specific_evidence.as_posix(),
        "latest_alias_capture_brief_path": alias_brief.as_posix(),
        "latest_alias_capture_evidence_path": alias_evidence.as_posix(),
    }


def _normalize_local_file_inputs(workspace: Path, raw_paths: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw_path in raw_paths or []:
        candidate = str(raw_path or "").strip()
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            workspace_relative = workspace / path
            if workspace_relative.exists():
                path = workspace_relative
            else:
                path = (Path.cwd() / path)
        normalized.append(path.resolve().as_posix())
    return normalized


def _build_direct_local_resolution(
    *,
    local_file_paths: list[str],
    title: str,
    buyer: str,
    summary: str,
    url: str,
    notice_id: str,
    solicitation_number: str,
) -> dict[str, object]:
    first_file = Path(local_file_paths[0]) if local_file_paths else Path("local-file-bundle")
    inferred_title = title.strip() or solicitation_number.strip() or first_file.stem.replace("-", " ").replace("_", " ").strip()
    canonical_seed = notice_id.strip() or solicitation_number.strip() or inferred_title or first_file.stem or "local-file-bundle"
    return {
        "status": "resolved",
        "entry_resolution_mode": "local_files",
        "report_entry_id": "",
        "digest_date": today_local_str(),
        "opportunity_id": "",
        "canonical_record_id": canonical_seed,
        "canonical_record_id_type": "local_file_bundle",
        "notice_id": notice_id.strip(),
        "title": inferred_title,
        "buyer": buyer.strip(),
        "summary": summary.strip(),
        "solicitation_number": solicitation_number.strip(),
        "source_id": f"local-files:{safe_slug(canonical_seed, 24)}",
        "source_name": "Local files",
        "source_tier": 1,
        "url": url.strip(),
        "local_files": local_file_paths,
    }


def _build_direct_local_context(resolved: dict[str, object]) -> dict[str, object]:
    summary = str(resolved.get("summary", "") or "").strip()
    title = str(resolved.get("title", "") or "").strip()
    buyer = str(resolved.get("buyer", "") or "").strip()
    solicitation_number = str(resolved.get("solicitation_number", "") or "").strip()
    if not summary:
        file_count = len(resolved.get("local_files", []) or [])
        summary = (
            f"Direct capture assembled from {file_count} local file(s) for {title or 'this opportunity'}."
            if file_count
            else "Direct capture assembled from local files."
        )
    opportunity_record = {
        "title": title,
        "buyer": buyer,
        "summary": summary,
        "notice_id": str(resolved.get("notice_id", "") or ""),
        "solicitation_number": solicitation_number,
        "resource_links": [],
        "point_of_contact": [],
        "semantic_fit": {},
    }
    return {
        "opportunity_record": opportunity_record,
        "explanation_record": {"summary": summary},
        "report_text": "",
        "digest_text": "",
    }


def _merge_attachment_bundles(primary: dict[str, object], supplemental: dict[str, object]) -> dict[str, object]:
    merged_contacts = [
        item
        for item in [*(primary.get("point_of_contact", []) or []), *(supplemental.get("point_of_contact", []) or [])]
        if isinstance(item, dict)
    ]
    merged_attachments: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for item in [*(primary.get("attachments", []) or []), *(supplemental.get("attachments", []) or [])]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("local_path") or item.get("url") or item.get("filename") or "")
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged_attachments.append(item)
    errors = [str(item) for item in [*(primary.get("errors", []) or []), *(supplemental.get("errors", []) or [])] if str(item or "").strip()]
    status = "ok" if merged_attachments else ("error" if errors else str(primary.get("status", supplemental.get("status", "empty"))))
    return {
        "status": status,
        "record": primary.get("record") or supplemental.get("record") or {},
        "point_of_contact": merged_contacts,
        "attachments": merged_attachments,
        "attachments_expected": bool(primary.get("attachments_expected") or supplemental.get("attachments_expected")),
        "record_lookup_status": str(primary.get("record_lookup_status") or supplemental.get("record_lookup_status") or "unknown"),
        "resource_listing_status": str(primary.get("resource_listing_status") or supplemental.get("resource_listing_status") or "unknown"),
        "seeded_resource_links": bool(primary.get("seeded_resource_links") or supplemental.get("seeded_resource_links")),
        "resource_link_count": int(primary.get("resource_link_count", 0) or 0) + int(supplemental.get("resource_link_count", 0) or 0),
        "errors": errors,
    }


def _clean_excerpt(value: object, max_chars: int = 4000) -> str:
    raw = str(value or "")
    text = SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(raw))).strip()
    return text[:max_chars]


def _attachment_structured_rows(attachment_bundle: dict[str, object], max_items: int = 16) -> list[str]:
    candidate_categories = {"statement_of_work", "solicitation", "instructions_evaluation", "questions_answers", "amendment"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=candidate_categories,
        max_items=6,
    )
    rows: list[str] = []
    for item in ordered:
        values = [*(item.get("snippets", []) or []), item.get("text_excerpt", "")]
        for value in values:
            raw = str(value or "")
            if not raw.strip():
                continue
            source_lines = [line.strip() for line in raw.replace("\r", "\n").split("\n") if line.strip()]
            if not source_lines:
                continue
            index = 0
            while index < len(source_lines):
                current = _clean_excerpt(OBJECTIVE_TABLE_CELL_SPLIT_RE.sub("; ", source_lines[index]), max_chars=420).strip(" ;:-")
                if not current:
                    index += 1
                    continue
                lower_current = current.lower()
                if _is_toc_like_objective_line(current) or re.fullmatch(r"\d+", current):
                    index += 1
                    continue
                if OBJECTIVE_ROW_PREFIX_RE.match(current):
                    combined = current
                    lookahead = index + 1
                    while lookahead < len(source_lines) and len(combined) < 320:
                        next_line = _clean_excerpt(
                            OBJECTIVE_TABLE_CELL_SPLIT_RE.sub("; ", source_lines[lookahead]),
                            max_chars=240,
                        ).strip(" ;:-")
                        if not next_line or OBJECTIVE_ROW_PREFIX_RE.match(next_line):
                            break
                        if next_line.lower().startswith(("question", "answer", "note", "instruction")):
                            break
                        combined = f"{combined}; {next_line}"
                        lookahead += 1
                        if any(term in combined.lower() for term in ("shall", "must", "provide", "deliver", "maintain", "transition", "report", "staff")):
                            break
                    rows.append(combined[:360])
                    index = lookahead
                    if len(rows) >= max_items:
                        return _dedupe_strings(rows)[:max_items]
                    continue
                if OBJECTIVE_SECTION_HEADING_RE.match(current):
                    combined = current
                    lookahead = index + 1
                    while lookahead < len(source_lines) and len(combined) < 340:
                        next_line = _clean_excerpt(
                            OBJECTIVE_TABLE_CELL_SPLIT_RE.sub("; ", source_lines[lookahead]),
                            max_chars=260,
                        ).strip(" ;:-")
                        if not next_line:
                            lookahead += 1
                            continue
                        if _is_toc_like_objective_line(next_line) or re.fullmatch(r"\d+", next_line):
                            lookahead += 1
                            continue
                        if OBJECTIVE_SECTION_HEADING_RE.match(next_line) or OBJECTIVE_ROW_PREFIX_RE.match(next_line):
                            break
                        combined = f"{combined}; {next_line}"
                        lookahead += 1
                        if any(term in combined.lower() for term in ("shall", "must", "provide", "deliver", "maintain", "transition", "report", "staff", "support")):
                            rows.append(combined[:360])
                            break
                    index = lookahead
                    if len(rows) >= max_items:
                        return _dedupe_strings(rows)[:max_items]
                    continue
                if ("|" in raw or "\t" in raw or re.search(r" {2,}", source_lines[index])) and len(current) >= 60:
                    rows.append(current[:360])
                    if len(rows) >= max_items:
                        return _dedupe_strings(rows)[:max_items]
                index += 1
    return _dedupe_strings(rows)[:max_items]


def _normalize_signal_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_excerpt(value, max_chars=12000).lower()).strip()


def _attachment_text_value(item: dict[str, object], *, max_chars: int = 12000) -> str:
    return _clean_excerpt(item.get("structured_text_excerpt") or item.get("text_excerpt", ""), max_chars=max_chars)


def _is_toc_like_objective_line(text: str) -> bool:
    lower = text.lower()
    return "table of contents" in lower or OBJECTIVE_TOC_LINE_RE.search(text) is not None or text.count(".") >= 12


def _signal_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = _normalize_signal_text(value)
        for token in normalized.split():
            if token in SIGNAL_STOPWORDS or token.isdigit():
                continue
            if len(token) < 3:
                continue
            tokens.add(token)
    return tokens


def _currency(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"${number:,.2f}"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _buyer_chain(buyer: str) -> list[str]:
    return [segment.strip() for segment in str(buyer or "").split(".") if segment.strip()]


def _extract_stakeholder_contacts(*texts: object) -> list[dict[str, str]]:
    combined = " ".join(_clean_excerpt(text, max_chars=12000) for text in texts if text)
    contacts: list[dict[str, str]] = []
    seen_emails: set[str] = set()

    for match in CONTACT_WITH_ROLE_RE.finditer(combined):
        email = match.group("email").strip().lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        contacts.append(
            {
                "name": match.group("name").strip(),
                "role": SPACE_RE.sub(" ", f"{match.group('role')} {match.group('suffix')}".strip(" ,")),
                "email": email,
            }
        )

    if contacts:
        return contacts

    for email_match in EMAIL_RE.finditer(combined):
        email = email_match.group(0).strip().lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        window = combined[max(0, email_match.start() - 140) : email_match.start()]
        role_match = re.search(
            r"(Contracting Officer|Contract Specialist|Program Manager|Project Officer|Point of Contact|Technical Point of Contact|Small Business Specialist|Contract Officer)\s*$",
            window,
            re.IGNORECASE,
        )
        name_match = re.search(r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)\s*$", window)
        contacts.append(
            {
                "name": name_match.group(1).strip() if name_match else "",
                "role": role_match.group(1).strip() if role_match else "Contact",
                "email": email,
            }
        )
    return contacts


def _structured_contact_name(item: dict[str, object]) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("fullName", "name"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    first = str(item.get("firstName", "") or "").strip()
    last = str(item.get("lastName", "") or "").strip()
    return " ".join(part for part in (first, last) if part)


def _structured_contact_role(item: dict[str, object]) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("type", "title", "role"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return "Contact"


def _contacts_from_point_of_contact(records: list[dict[str, object]]) -> list[dict[str, str]]:
    contacts: list[dict[str, str]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        email = str(item.get("email") or item.get("emailAddress") or "").strip().lower()
        phone = str(item.get("phone") or item.get("phoneNumber") or "").strip()
        contact = {
            "name": _structured_contact_name(item),
            "role": _structured_contact_role(item),
            "email": email,
        }
        if phone:
            contact["phone"] = phone
        contacts.append(contact)
    return contacts


def _dedupe_contacts(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for group in groups:
        for contact in group or []:
            if not isinstance(contact, dict):
                continue
            email = str(contact.get("email", "") or "").strip().lower()
            name = str(contact.get("name", "") or "").strip().lower()
            role = str(contact.get("role", "") or "").strip().lower()
            key = email or f"{name}|{role}"
            if not key or key in seen:
                continue
            seen.add(key)
            normalized = {
                "name": str(contact.get("name", "") or "").strip(),
                "role": str(contact.get("role", "") or "Contact").strip(),
                "email": email,
            }
            phone = str(contact.get("phone", "") or "").strip()
            if phone:
                normalized["phone"] = phone
            merged.append(normalized)
    return merged


def _attachment_manifest_lines(attachment_bundle: dict[str, object]) -> list[str]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    if not isinstance(attachments, list) or not attachments:
        return []
    category_counts = Counter(
        str(item.get("category", "other"))
        for item in attachments
        if isinstance(item, dict)
    )
    summary = ", ".join(f"{count} {category.replace('_', ' ')}" for category, count in category_counts.most_common())
    lines = [f"Attachment package parsed: {len(attachments)} files ({summary})."]
    for item in attachments[:6]:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"Attachment: {item.get('filename', 'unknown')} [{item.get('category', 'other')}] ({item.get('parser_status', 'unknown')})"
        )
    return lines


def _attachment_scope_snippets(attachment_bundle: dict[str, object], max_snippets: int = 6) -> list[str]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    prioritized_categories = {"statement_of_work", "solicitation", "instructions_evaluation", "amendment"}
    snippets: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if str(item.get("category", "other")) not in prioritized_categories:
            continue
        filename = str(item.get("filename", "attachment") or "attachment")
        for snippet in item.get("snippets", []) or []:
            snippets.append(f"{filename}: {_clean_excerpt(snippet, max_chars=280)}")
    return _dedupe_strings(snippets)[:max_snippets]


def _attachment_contract_reference_lines(attachment_bundle: dict[str, object], max_refs: int = 4) -> list[str]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    references: list[str] = []
    pattern = re.compile(
        r"((?:follow[- ]on|incumbent|current contractor|current provider|existing contract|predecessor contract)[^.]{0,220})",
        re.IGNORECASE,
    )
    for item in attachments:
        if not isinstance(item, dict):
            continue
        text = _attachment_text_value(item)
        filename = str(item.get("filename", "attachment") or "attachment")
        for match in pattern.finditer(text):
            references.append(f"{filename}: {_clean_excerpt(match.group(1), max_chars=260)}")
    return _dedupe_strings(references)[:max_refs]


def _attachment_incumbent_validation(
    attachment_bundle: dict[str, object],
    likely_incumbents: list[str],
) -> dict[str, object]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    direct_mentions: list[str] = []
    validated: list[str] = []
    notes: list[str] = []
    supporting_snippets = _attachment_contract_reference_lines(attachment_bundle)
    searchable = [
        (str(item.get("filename", "attachment") or "attachment"), _normalize_signal_text(_attachment_text_value(item)))
        for item in attachments
        if isinstance(item, dict)
    ]
    for incumbent in likely_incumbents:
        normalized = _normalize_signal_text(incumbent)
        if not normalized:
            continue
        name_hit = False
        for filename, text in searchable:
            if f" {normalized} " in f" {text} ":
                direct_mentions.append(f"{filename}: mentions {incumbent}")
                name_hit = True
        if name_hit:
            validated.append(incumbent)
    if validated:
        notes.append(
            f"Attachment package directly names likely incumbent-related performers: {', '.join(validated)}."
        )
    elif supporting_snippets:
        notes.append(
            "Attachment package references a follow-on or incumbent context, but it does not directly name the current performer."
        )
    else:
        notes.append("Attachment package did not directly name an incumbent or predecessor performer.")
    return {
        "validated_incumbents": _dedupe_strings(validated),
        "direct_mentions": _dedupe_strings(direct_mentions)[:6],
        "supporting_snippets": supporting_snippets,
        "notes": notes,
    }


def _attachment_source_log(attachment_bundle: dict[str, object]) -> list[dict[str, object]]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    sources: list[dict[str, object]] = []
    for item in attachments[:6]:
        if not isinstance(item, dict):
            continue
        sources.append(
            {
                "title": item.get("filename", "Notice attachment"),
                "url": item.get("url", "N/A"),
                "publisher": "SAM.gov attachment",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"Parsed notice attachment ({item.get('category', 'other')}); parser status {item.get('parser_status', 'unknown')}",
                "confidence": 3 if item.get("text_excerpt") else 2,
            }
        )
    return sources


def _stakeholder_lines(buyer: str, contacts: list[dict[str, str]], notice_text: str) -> list[str]:
    lines = []
    chain = _buyer_chain(buyer)
    if chain:
        lines.append(f"Buyer chain: {' > '.join(chain)}")
    for contact in contacts[:6]:
        label = f"{contact.get('role', 'Contact')}: {contact.get('name') or 'Unnamed contact'}"
        if contact.get("email"):
            label += f" ({contact['email']})"
        lines.append(label)
    lowered_notice = notice_text.lower()
    if "questions must be addressed in writing" in lowered_notice or "must be requested in writing" in lowered_notice:
        lines.append("Notice instruction: vendor questions must be submitted in writing.")
    if not lines:
        lines.append("No named solicitation contacts or buyer-chain details were parsed from the current evidence.")
    return lines


def _objective_stakeholder_text(buyer: str, contacts: list[dict[str, str]]) -> str:
    contact_labels = [f"{item.get('name') or 'Unnamed contact'} ({item.get('role', 'Contact')})" for item in contacts[:3]]
    values = _dedupe_strings(contact_labels + _buyer_chain(buyer)[:2])
    return "; ".join(values) if values else buyer or "N/A"


def _ordered_attachment_items(
    attachment_bundle: dict[str, object],
    *,
    allowed_categories: set[str] | None = None,
    max_items: int = 6,
) -> list[dict[str, object]]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    priority = {
        "statement_of_work": 0,
        "solicitation": 1,
        "instructions_evaluation": 2,
        "questions_answers": 3,
        "amendment": 4,
        "other": 5,
    }
    ordered = [
        item
        for item in attachments
        if isinstance(item, dict)
        and (allowed_categories is None or str(item.get("category", "other")) in allowed_categories)
    ]
    ordered.sort(key=lambda item: priority.get(str(item.get("category", "other")), 9))
    return ordered[:max_items]


def _attachment_text_pool(attachment_bundle: dict[str, object], max_items: int = 5) -> list[str]:
    ordered = _ordered_attachment_items(attachment_bundle, max_items=max_items)
    texts: list[str] = []
    for item in ordered:
        text_excerpt = _attachment_text_value(item, max_chars=5000)
        if text_excerpt:
            texts.append(text_excerpt)
        for snippet in item.get("snippets", []) or []:
            cleaned = _clean_excerpt(snippet, max_chars=320)
            if cleaned:
                texts.append(cleaned)
    return _dedupe_strings(texts)


def _objective_heading_title(text: str) -> str:
    match = OBJECTIVE_HEADING_PREFIX_RE.match(str(text or "").strip())
    if not match:
        return str(text or "").strip().lower()
    return match.group(2).strip().lower()


def _objective_heading_kind(text: str) -> str:
    title = _objective_heading_title(text)
    if any(hint in title for hint in OBJECTIVE_PREFERRED_SECTION_HINTS):
        return "preferred"
    if any(hint in title for hint in OBJECTIVE_DEMOTED_SECTION_HINTS):
        return "demoted"
    return "neutral"


def _preferred_objective_body_blocks(
    attachment_bundle: dict[str, object],
    max_items: int = 10,
    *,
    include_filename: bool = False,
) -> list[str]:
    scope_categories = {"statement_of_work", "solicitation", "instructions_evaluation"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=scope_categories,
        max_items=6,
    )
    blocks: list[str] = []
    action_terms = set(OBJECTIVE_KEYWORDS) | set(OBJECTIVE_EXTRA_ACTION_VERBS)
    for item in ordered:
        filename = str(item.get("filename", "attachment") or "attachment")
        text = _attachment_text_value(item, max_chars=24000)
        if not text:
            continue
        lines = [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]
        index = 0
        while index < len(lines):
            heading = _clean_excerpt(lines[index], max_chars=240).strip(" ;:-")
            if not OBJECTIVE_SECTION_HEADING_RE.match(heading):
                index += 1
                continue
            heading_kind = _objective_heading_kind(heading)
            if heading_kind == "demoted":
                index += 1
                continue
            if heading_kind != "preferred" and not any(
                marker in _objective_heading_title(heading)
                for marker in ("task", "service", "support", "performance", "requirement", "deliverable")
            ):
                index += 1
                continue
            paragraph_lines: list[str] = []
            lookahead = index + 1
            while lookahead < len(lines):
                next_line = _clean_excerpt(lines[lookahead], max_chars=320).strip(" ;:-")
                if not next_line or _is_toc_like_objective_line(next_line) or re.fullmatch(r"\d+", next_line):
                    lookahead += 1
                    continue
                if OBJECTIVE_SECTION_HEADING_RE.match(next_line):
                    break
                paragraph_lines.append(next_line)
                if len(" ".join(paragraph_lines)) >= 1400:
                    break
                lookahead += 1
            if paragraph_lines:
                paragraph = SPACE_RE.sub(" ", " ".join(paragraph_lines)).strip()
                sentence_parts = [
                    part.strip(" -;:")
                    for part in re.split(r"(?<=[.!?;])\s+|(?<=\))\s+(?=[A-Z])", paragraph)
                    if part.strip()
                ]
                if not sentence_parts:
                    sentence_parts = [paragraph]
                for part in sentence_parts:
                    lower = part.lower()
                    if len(part) < 90 or len(part) > 520:
                        continue
                    if not any(term in lower for term in action_terms):
                        continue
                    snippet = f"{heading}; {part}"[:520]
                    if include_filename:
                        snippet = f"{filename}: {snippet}"[:640]
                    blocks.append(snippet)
                    if len(blocks) >= max_items:
                        return _dedupe_strings(blocks)[:max_items]
            index = lookahead if lookahead > index else index + 1
    return _dedupe_strings(blocks)[:max_items]


def _objective_scope_texts(attachment_bundle: dict[str, object], max_items: int = 6) -> list[str]:
    scope_categories = {"statement_of_work", "solicitation", "instructions_evaluation"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=scope_categories,
        max_items=max_items,
    )
    texts: list[str] = [*_preferred_objective_body_blocks(attachment_bundle, max_items=max_items)]
    for item in ordered:
        for snippet in item.get("snippets", []) or []:
            cleaned = _clean_excerpt(snippet, max_chars=320)
            if cleaned:
                texts.append(cleaned)
        text_excerpt = _attachment_text_value(item, max_chars=2200)
        if text_excerpt:
            texts.append(text_excerpt)
    return _dedupe_strings(texts)


def _attachment_objective_candidates(attachment_bundle: dict[str, object], max_items: int = 18) -> list[str]:
    candidate_categories = {"statement_of_work", "solicitation", "instructions_evaluation", "questions_answers", "amendment"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=candidate_categories,
        max_items=6,
    )
    candidates: list[str] = [
        *_preferred_objective_body_blocks(attachment_bundle, max_items=max_items),
        *_attachment_structured_rows(attachment_bundle, max_items=max_items),
    ]
    marker_keywords = (
        "clin ",
        "subclin",
        "task ",
        "subtask",
        "deliverable",
        "transition",
        "period of performance",
        "pws",
        "shall",
        "must",
        "provide",
        "deliver",
        "maintain",
        "report",
        "staff",
    )
    for item in ordered:
        values = [*(item.get("snippets", []) or []), item.get("structured_text_excerpt") or item.get("text_excerpt", "")]
        for value in values:
            cleaned = _clean_excerpt(value, max_chars=7000)
            if not cleaned:
                continue
            structured_parts = [part for part in OBJECTIVE_STRUCTURED_SPLIT_RE.split(cleaned) if part.strip()]
            if len(structured_parts) <= 1:
                structured_parts = re.split(r"(?<=;)\s+|(?<=[.!?])\s+", cleaned)
            for part in structured_parts:
                sentence = SPACE_RE.sub(" ", part).strip(" -;:")
                lower = sentence.lower()
                if len(sentence) < 60:
                    continue
                if not any(marker in lower for marker in marker_keywords):
                    continue
                candidates.append(sentence[:360])
                if len(candidates) >= max_items:
                    return _dedupe_strings(candidates)[:max_items]
    return _dedupe_strings(candidates)[:max_items]


def _objective_requirement_tokens(
    title: str,
    summary: str,
    explanation_summary: str,
    attachment_bundle: dict[str, object],
) -> set[str]:
    seed_values: list[str] = [
        *_attachment_objective_candidates(attachment_bundle, max_items=18),
        *_objective_scope_texts(attachment_bundle, max_items=6),
        title,
        summary,
        explanation_summary,
    ]
    tokens = _signal_tokens(*seed_values)
    return {token for token in tokens if token not in OBJECTIVE_ADMIN_TOKENS}


def _is_boilerplate_objective_sentence(sentence: str) -> bool:
    lower = sentence.lower().strip()
    if any(marker in lower for marker in OBJECTIVE_BOILERPLATE_MARKERS):
        return True
    if _is_toc_like_objective_line(sentence):
        return True
    heading_title = _objective_heading_title(sentence)
    if any(hint in heading_title for hint in OBJECTIVE_DEMOTED_SECTION_HINTS) and not any(
        keyword in lower for keyword in (*OBJECTIVE_KEYWORDS, *OBJECTIVE_EXTRA_ACTION_VERBS)
    ):
        return True
    if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\b", lower):
        return True
    if re.match(r"^(submit|questions|responses|offers|proposal|amendment|contact)\b", lower):
        return True
    if lower.startswith(("response:", "would you ", "if any, please", "please describe", "please provide")):
        return True
    if "row #" in lower:
        return True
    return False


def _signal_overlap_score(reference_tokens: set[str], text: str) -> int:
    return len(reference_tokens & _signal_tokens(text))


def _objective_candidate_score(sentence: str, requirement_tokens: set[str], structured_candidates: set[str]) -> tuple[int, int, int, int]:
    lower = sentence.lower()
    overlap_count = len(_signal_tokens(sentence) & requirement_tokens)
    verb_count = sum(1 for keyword in (*OBJECTIVE_KEYWORDS, *OBJECTIVE_EXTRA_ACTION_VERBS) if keyword in lower)
    structured_bonus = 3 if OBJECTIVE_ROW_PREFIX_RE.match(sentence) else 2 if sentence in structured_candidates else 0
    density_bonus = 1 if any(token in lower for token in ("clin ", "task ", "pws", "deliverable", "transition")) else 0
    section_kind = _objective_heading_kind(sentence)
    section_bonus = 3 if section_kind == "preferred" else -3 if section_kind == "demoted" else 0
    body_bonus = 1 if ";" in sentence and len(sentence.split(";", 1)[-1].split()) >= 12 else 0
    return (section_bonus + structured_bonus + density_bonus + body_bonus, overlap_count, verb_count, len(sentence))


def _matching_lines(reference_text: str, lines: list[str], max_items: int = 3, min_score: int = 1) -> list[str]:
    reference_tokens = _signal_tokens(reference_text)
    ranked = sorted(
        (
            (_signal_overlap_score(reference_tokens, line), line)
            for line in lines
            if str(line or "").strip()
        ),
        key=lambda item: (-item[0], item[1]),
    )
    selected = [line for score, line in ranked if score >= min_score][:max_items]
    return selected[:max_items]


def _decompose_objectives(
    title: str,
    summary: str,
    explanation_summary: str,
    attachment_bundle: dict[str, object],
) -> list[str]:
    candidates: list[str] = []
    structured_rows = _attachment_structured_rows(attachment_bundle, max_items=18)
    attachment_candidates = _attachment_objective_candidates(attachment_bundle, max_items=20)
    attachment_texts = _objective_scope_texts(attachment_bundle, max_items=6)
    requirement_tokens = _objective_requirement_tokens(title, summary, explanation_summary, attachment_bundle)
    attachment_seed_text = " ".join(attachment_texts)
    attachments_thin = (len(structured_rows) < 1 and len(attachment_candidates) < 2 and len(attachment_texts) < 2) or len(attachment_seed_text) < 900
    seed_values = [*structured_rows, *attachment_candidates, *attachment_texts]
    if attachments_thin:
        seed_values.extend([summary, explanation_summary])
    elif not attachment_candidates and title:
        seed_values.append(title)
    structured_candidate_set = set(_dedupe_strings(structured_rows))
    for value in seed_values:
        parts = [value] if value in attachment_candidates or value in structured_candidate_set else OBJECTIVE_SENTENCE_RE.split(_clean_excerpt(value, max_chars=8000))
        for part in parts:
            sentence = SPACE_RE.sub(" ", part).strip(" -")
            lower = sentence.lower()
            if len(sentence) < 70 or len(sentence) > 520:
                continue
            if sentence.endswith("?"):
                continue
            if _is_boilerplate_objective_sentence(sentence):
                continue
            if not any(keyword in lower for keyword in OBJECTIVE_KEYWORDS):
                continue
            overlap_count = len(_signal_tokens(sentence) & requirement_tokens)
            if overlap_count < OBJECTIVE_MIN_REQUIREMENT_OVERLAP:
                continue
            candidates.append(sentence)
    deduped = _dedupe_strings(candidates)
    deduped.sort(
        key=lambda sentence: _objective_candidate_score(sentence, requirement_tokens, structured_candidate_set),
        reverse=True,
    )
    filtered: list[str] = []
    normalized_filtered: list[str] = []
    for sentence in deduped:
        normalized = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if not normalized:
            continue
        replaced = False
        for index, existing_normalized in enumerate(normalized_filtered):
            shorter, longer = sorted((normalized, existing_normalized), key=len)
            if shorter and shorter in longer:
                if len(sentence) > len(filtered[index]):
                    filtered[index] = sentence
                    normalized_filtered[index] = normalized
                replaced = True
                break
        if not replaced:
            filtered.append(sentence)
            normalized_filtered.append(normalized)
    if filtered and any(OBJECTIVE_ROW_PREFIX_RE.match(sentence) or sentence in structured_candidate_set for sentence in filtered[:3]):
        return filtered[:3]
    if len(filtered) >= 2:
        return filtered[:4]
    return [OBJECTIVE_DECOMPOSITION_FALLBACK]


def _objective_kpis(objective_text: str) -> str:
    if objective_text == OBJECTIVE_DECOMPOSITION_FALLBACK:
        return NO_OBJECTIVE_KPIS
    lower = objective_text.lower()
    kpis: list[str] = []
    if any(term in lower for term in ("security", "privacy", "fisma", "nist", "compliance")):
        kpis.append("compliance defect rate, time-to-remediate, audit readiness")
    if any(term in lower for term in ("support", "helpdesk", "training", "staff")):
        kpis.append("response time, staffing continuity, user satisfaction")
    if any(term in lower for term in ("software", "portal", "availability", "performance", "system")):
        kpis.append("availability, cycle-time reduction, defect escape rate")
    if any(term in lower for term in ("data", "transmission", "migration", "report")):
        kpis.append("data quality score, transmission success rate, reporting timeliness")
    return "; ".join(_dedupe_strings(kpis)) or "cycle-time reduction, compliance fidelity, mission delivery outcomes"


def _objective_solution_implications(objective_text: str) -> str:
    if objective_text == OBJECTIVE_DECOMPOSITION_FALLBACK:
        return NO_SOLUTION_IMPLICATIONS
    lower = objective_text.lower()
    implications: list[str] = []
    if "cots" in lower or "commercial off" in lower:
        implications.append("Lead with mature COTS fit, proven release cadence, and low-customization deployment.")
    if any(term in lower for term in ("security", "privacy", "nist", "fisma", "publication 4812")):
        implications.append("Show inherited control coverage, rapid compliance startup, and IRS/NIST traceability.")
    if any(term in lower for term in ("integration", "migration", "carry forward", "transmission")):
        implications.append("Reduce transition risk with clean data carry-forward, migration controls, and minimal integration dependencies.")
    if any(term in lower for term in ("staff", "workforce", "personnel", "training")):
        implications.append("Present mobilization realism, cleared staffing continuity, and measurable service management.")
    if any(term in lower for term in ("firm fixed price", "ffp", "license", "option")):
        implications.append("Anchor pricing around predictable FFP delivery and annual renewal economics.")
    return " ".join(_dedupe_strings(implications)) or "Shape win themes around mission fit, compliance, and operational realism."


def _objective_key_risks(objective_text: str, evidence_gaps: list[str]) -> str:
    if objective_text == OBJECTIVE_DECOMPOSITION_FALLBACK:
        fallback_risks = [
            "Current artifacts do not support objective-level decomposition, so capture planning still depends on manual SOW/PWS review.",
        ]
        if evidence_gaps:
            fallback_risks.append(evidence_gaps[0])
        return " ".join(_dedupe_strings(fallback_risks))
    lower = objective_text.lower()
    risks: list[str] = []
    if any(term in lower for term in ("security", "privacy", "nist", "fisma")):
        risks.append("Compressed compliance timelines could expose gaps in inherited controls or documentation.")
    if any(term in lower for term in ("migration", "carry forward", "transmission", "data")):
        risks.append("Data carry-forward and transmission assumptions may hide implementation and quality risks.")
    if any(term in lower for term in ("staff", "workforce", "personnel", "background")):
        risks.append("Key-personnel screening and workforce reporting requirements could slow mobilization.")
    if evidence_gaps:
        risks.append(evidence_gaps[0])
    return " ".join(_dedupe_strings(risks)) or "Partial evidence until attachments, policy context, and award history tell a consistent story."


def _objective_driver(reference_text: str, signals: list[str], fallback: str) -> str:
    matches = _matching_lines(reference_text, signals, max_items=1)
    return matches[0] if matches else fallback


def _attachment_objective_evidence_snippets(
    objective_text: str,
    attachment_bundle: dict[str, object],
    max_items: int = 4,
    min_score: int = 2,
) -> list[str]:
    if objective_text == OBJECTIVE_DECOMPOSITION_FALLBACK:
        return []
    candidate_lines = _dedupe_strings(
        [
            *_preferred_objective_body_blocks(attachment_bundle, max_items=18, include_filename=True),
            *_attachment_scope_snippets(attachment_bundle, max_snippets=12),
            *(
                f"Attachment body: {line}"
                for line in _attachment_structured_rows(attachment_bundle, max_items=12)
            ),
        ]
    )
    matches = _matching_lines(objective_text, candidate_lines, max_items=max_items, min_score=min_score)
    return matches[:max_items]


def _objective_evidence_snippets(
    objective_text: str,
    attachment_evidence_snippets: list[str],
    public_research: dict[str, object],
    related_procurements: list[str],
    max_items: int = 6,
) -> list[str]:
    lines: list[str] = []
    lines.extend(attachment_evidence_snippets)
    for key in (
        "mission_context_signals",
        "policy_compliance_signals",
        "budget_document_signals",
        "acquisition_forecast_signals",
        "oversight_signals",
        "leadership_priority_signals",
        "public_discourse_signals",
    ):
        lines.extend(public_research.get(key, []) or [])
    lines.extend(related_procurements[:3])
    matches = _matching_lines(objective_text, _dedupe_strings(lines), max_items=max_items)
    return matches if matches else [NO_EVIDENCE_SNIPPET]


def _objective_evidence_links(primary_url: str, source_log: list[dict[str, object]], objective_text: str) -> str:
    lines = [primary_url] if primary_url else []
    reference_tokens = _signal_tokens(objective_text)
    ranked = sorted(
        (
            (_signal_overlap_score(reference_tokens, f"{item.get('title', '')} {item.get('relevance', '')} {item.get('url', '')}"), str(item.get("url", "") or ""))
            for item in source_log
            if isinstance(item, dict) and str(item.get("url", "") or "")
        ),
        key=lambda item: (-item[0], item[1]),
    )
    for score, url in ranked:
        if score <= 0:
            continue
        if url in lines:
            continue
        lines.append(url)
        if len(lines) >= 4:
            break
    return " | ".join(lines) if lines else "N/A"


def _award_row_text(row: dict[str, object]) -> str:
    return " ".join(
        [
            str(row.get("Description", "") or ""),
            str(row.get("Awarding Agency", "") or ""),
            str(row.get("Awarding Sub Agency", "") or ""),
            str(row.get("Recipient Name", "") or ""),
        ]
    )


def _award_row_relevance(row: dict[str, object], reference_tokens: set[str], buyer_tokens: set[str]) -> int:
    description_text = _normalize_signal_text(row.get("Description", ""))
    agency_text = _normalize_signal_text(f"{row.get('Awarding Agency', '')} {row.get('Awarding Sub Agency', '')}")
    recipient_text = _normalize_signal_text(row.get("Recipient Name", ""))
    score = 0

    for term in row.get("_query_terms", []) or []:
        normalized_term = _normalize_signal_text(term)
        if not normalized_term:
            continue
        if f" {normalized_term} " in f" {description_text} ":
            score += 3 if len(normalized_term.split()) > 1 else 2
        elif f" {normalized_term} " in f" {agency_text} ":
            score += 2
        elif f" {normalized_term} " in f" {recipient_text} ":
            score -= 1

    description_tokens = set(description_text.split())
    score += min(3, len(reference_tokens & description_tokens))
    if buyer_tokens & set(agency_text.split()):
        score += 2
    if buyer_tokens & description_tokens:
        score += 1
    return score


def _relevant_award_rows(
    usaspending_result: dict[str, object],
    title: str,
    summary: str,
    buyer: str,
) -> list[dict[str, object]]:
    response = ((usaspending_result.get("spending_by_award") or {}).get("response") or {}) if isinstance(usaspending_result, dict) else {}
    rows = response.get("results", []) if isinstance(response, dict) else []
    reference_tokens = _signal_tokens(title, summary)
    buyer_tokens = _signal_tokens(buyer)
    selected: list[dict[str, object]] = []
    for row in rows:
        relevance = _award_row_relevance(row, reference_tokens, buyer_tokens)
        description_tokens = _signal_tokens(row.get("Description", ""))
        overlap_count = len(reference_tokens & description_tokens)
        agency_match = bool(buyer_tokens & _signal_tokens(f"{row.get('Awarding Agency', '')} {row.get('Awarding Sub Agency', '')}"))
        if relevance < 3:
            continue
        if not agency_match and overlap_count < 2:
            continue
        enriched = dict(row)
        enriched["_relevance_score"] = relevance
        enriched["_agency_match"] = agency_match
        enriched["_overlap_count"] = overlap_count
        selected.append(enriched)
    selected.sort(
        key=lambda item: (
            0 if item.get("_agency_match") else 1,
            -int(item.get("_relevance_score", 0) or 0),
            -(_safe_float(item.get("Award Amount")) or 0.0),
        )
    )
    return selected


def _agency_anchor_award_rows(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    agency_rows = [row for row in rows if row.get("_agency_match")]
    adjacent_rows = [row for row in rows if not row.get("_agency_match")]
    return agency_rows, adjacent_rows


def _award_history_signals(
    usaspending_result: dict[str, object],
    title: str,
    summary: str,
    buyer: str,
) -> dict[str, object]:
    response = ((usaspending_result.get("spending_by_award") or {}).get("response") or {}) if isinstance(usaspending_result, dict) else {}
    queries = list(response.get("query_terms", []) or usaspending_result.get("search_terms", []) or [])
    weak_query_only = bool(queries) and all(bool(re.fullmatch(r"[A-Z0-9-]{2,5}", str(query or ""))) for query in queries)
    candidate_rows = _relevant_award_rows(usaspending_result, title, summary, buyer)
    agency_rows, adjacent_rows = _agency_anchor_award_rows(candidate_rows)
    strong_agency_rows = [
        row
        for row in agency_rows
        if int(row.get("_overlap_count", 0) or 0) >= 2 or int(row.get("_relevance_score", 0) or 0) >= 6
    ]
    relevant_rows = strong_agency_rows
    budget_usable_for_capture = bool(relevant_rows) and not weak_query_only
    amount_rows = strong_agency_rows
    all_amounts = [amount for amount in (_safe_float(row.get("Award Amount")) for row in amount_rows) if amount is not None]
    likely_rows = strong_agency_rows
    likely_incumbents = _dedupe_strings([str(row.get("Recipient Name", "") or "") for row in likely_rows])[:4]
    competitive_rows = strong_agency_rows
    frequent_primes = [
        name
        for name, _ in Counter(str(row.get("Recipient Name", "") or "") for row in competitive_rows if row.get("Recipient Name")).most_common(5)
    ]
    emerging_challengers = _dedupe_strings(
        [
            str(row.get("Recipient Name", "") or "")
            for row in adjacent_rows
            if str(row.get("Recipient Name", "") or "")
        ]
    )[:4]

    budget_signals: list[str] = []
    related_procurements: list[str] = []
    source_log: list[dict[str, object]] = []
    notes: list[str] = []
    evidence_gaps: list[str] = []

    if agency_rows and not strong_agency_rows:
        notes.append(
            "Agency-matched USAspending rows were excluded because they only matched weak or generic requirement terms."
        )
    if weak_query_only and relevant_rows:
        notes.append(
            "USAspending rows were not accepted as funding proof because the surviving queries were acronym-only rather than requirement-specific."
        )
        evidence_gaps.append(
            "USAspending surfaced acronym-level award matches only, so funding evidence remains uncorroborated in this run."
        )

    if relevant_rows:
        queries_with_results = _dedupe_strings([term for row in relevant_rows for term in row.get("_query_terms", []) or []])
        if budget_usable_for_capture:
            budget_signals.append(
                f"USAspending surfaced {len(relevant_rows)} relevant related awards across query terms: {', '.join(queries_with_results or queries)}."
            )
            if all_amounts:
                budget_signals.append(
                    f"Visible related award values range from {_currency(min(all_amounts))} to {_currency(max(all_amounts))}, totaling {_currency(sum(all_amounts))} across the matched records."
                )
            top_row = max(
                amount_rows,
                key=lambda item: (_safe_float(item.get("Award Amount")) or 0.0, int(item.get("_relevance_score", 0) or 0)),
            )
            budget_signals.append(
                f"Top related award: {top_row.get('Award ID', 'N/A')} to {top_row.get('Recipient Name', 'Unknown')} for {_currency(top_row.get('Award Amount'))}."
            )
        if agency_rows:
            matched_agencies = _dedupe_strings(
                [
                    " / ".join(
                        [
                            str(row.get("Awarding Agency", "") or "").strip(),
                            str(row.get("Awarding Sub Agency", "") or "").strip(),
                        ]
                    ).strip(" /")
                    for row in agency_rows
                ]
            )
            notes.append(
                f"Agency-matched award history appears under {', '.join(matched_agencies[:3])}."
            )
        if adjacent_rows:
            notes.append(
                "Additional cross-agency matches indicate adjacent market performers, but they are not direct proof of incumbency on this solicitation."
            )
        for row in agency_rows[:4]:
            related_procurements.append(
                f"Award {row.get('Award ID', 'N/A')}: {row.get('Recipient Name', 'Unknown')} | {_currency(row.get('Award Amount'))} | {row.get('Awarding Sub Agency', row.get('Awarding Agency', 'Unknown'))} | {_clean_excerpt(row.get('Description', ''), max_chars=180)}"
            )
        source_log.append(
            {
                "title": "USAspending award history search",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "publisher": "USAspending.gov",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"{len(relevant_rows)} relevant awards across queries: {', '.join(queries_with_results or queries)}",
                "confidence": 3,
            }
        )
    else:
        budget_signals.append(
            f"USAspending returned no clearly relevant same-agency award-history matches across query terms: {', '.join(queries) if queries else 'none'}."
        )
        if adjacent_rows:
            notes.append(
                f"{len(adjacent_rows)} adjacent cross-agency USAspending matches were excluded from funding and incumbency proof because they do not share the customer chain."
            )
        else:
            notes.append("No clearly relevant prior award history was surfaced from the current USAspending query set.")
        evidence_gaps.append("USAspending did not surface clearly relevant same-agency prior awards, so incumbent and funding signals still need manual validation.")
        source_log.append(
            {
                "title": "USAspending award history search",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "publisher": "USAspending.gov",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"No clearly relevant same-agency awards across queries: {', '.join(queries) if queries else 'none'}",
                "confidence": 1,
            }
        )

    return {
        "queries": queries,
        "relevant_awards": relevant_rows,
        "adjacent_awards": adjacent_rows[:6],
        "budget_signals": budget_signals,
        "related_procurements": related_procurements,
        "competitive_landscape": {
            "likely_incumbents": likely_incumbents,
            "frequent_primes": frequent_primes,
            "common_teammates": [],
            "emerging_challengers": emerging_challengers,
            "notes": notes or ["Competitive posture remains thin because no related award history was parsed."],
        },
        "budget_usable_for_capture": budget_usable_for_capture,
        "objective_budget_signal": budget_signals[0] if budget_usable_for_capture and budget_signals else "Award-history signal unavailable.",
        "objective_incumbents": ", ".join(likely_incumbents) if likely_incumbents else "No clearly relevant prior award recipients surfaced from USAspending.",
        "evidence_gaps": evidence_gaps,
        "source_log": source_log,
    }


def _funding_assessment(
    award_signals: dict[str, object],
    public_research: dict[str, object],
    attachment_budget_signals: list[str],
) -> dict[str, object]:
    useful_award_history = bool(award_signals.get("budget_usable_for_capture"))
    budget_anchor_count = int(((public_research.get("category_anchor_counts") or {}).get("budget_funding", 0)) or 0)
    useful_budget_documents = budget_anchor_count > 0
    useful_attachment_budget = bool(attachment_budget_signals)
    useful_evidence_found = useful_award_history or useful_budget_documents or useful_attachment_budget
    notes: list[str] = []
    gap_notes: list[str] = []
    if useful_award_history:
        notes.append("USAspending surfaced relevant award-history rows.")
    if useful_budget_documents:
        notes.append("Official budget or appropriation documents were discovered.")
    if useful_attachment_budget:
        notes.append("SAM attachments exposed pricing, schedule, or amendment budget clues.")
    if not useful_evidence_found:
        gap_notes.append("Funding was checked, but no substantive funding evidence was found beyond query status.")
    return {
        "checked": True,
        "useful_evidence_found": useful_evidence_found,
        "useful_award_history": useful_award_history,
        "useful_budget_documents": useful_budget_documents,
        "useful_attachment_budget": useful_attachment_budget,
        "notes": notes,
        "gap_notes": gap_notes,
    }


def _public_research_assessment(public_research: dict[str, object]) -> dict[str, object]:
    category_anchor_counts = public_research.get("category_anchor_counts", {})
    if not isinstance(category_anchor_counts, dict):
        category_anchor_counts = {}
    mission_anchor_count = int(category_anchor_counts.get("mission_context", 0) or 0)
    budget_anchor_count = int(category_anchor_counts.get("budget_funding", 0) or 0)
    forecast_anchor_count = int(category_anchor_counts.get("acquisition_forecast", 0) or 0)
    oversight_anchor_count = int(category_anchor_counts.get("oversight", 0) or 0)
    leadership_anchor_count = int(category_anchor_counts.get("leadership", 0) or 0)
    public_discourse_anchor_count = int(category_anchor_counts.get("public_discourse", 0) or 0)
    requirement_relevant_ratio = float(public_research.get("requirement_relevant_ratio", 0.0) or 0.0)
    core_requirement_anchor_count = mission_anchor_count + budget_anchor_count + forecast_anchor_count
    return {
        "mission_anchor_count": mission_anchor_count,
        "budget_anchor_count": budget_anchor_count,
        "forecast_anchor_count": forecast_anchor_count,
        "oversight_anchor_count": oversight_anchor_count,
        "leadership_anchor_count": leadership_anchor_count,
        "public_discourse_anchor_count": public_discourse_anchor_count,
        "core_requirement_anchor_count": core_requirement_anchor_count,
        "funding_or_buying_anchor_count": int(public_research.get("funding_or_buying_anchor_count", 0) or 0),
        "requirement_relevant_ratio": requirement_relevant_ratio,
        "requirement_bearing_core_anchor_present": core_requirement_anchor_count > 0,
    }


def _is_fallback_objective_row(row: dict[str, object]) -> bool:
    objective_text = str(row.get("objective", "") or "").strip()
    if objective_text == OBJECTIVE_DECOMPOSITION_FALLBACK:
        return True
    if bool(row.get("attachment_native_corroborated")):
        return False
    evidence_snippets = row.get("evidence_snippets", [])
    if not isinstance(evidence_snippets, list):
        evidence_snippets = []
    has_real_snippet = any(str(snippet or "").strip() and str(snippet or "").strip() != NO_EVIDENCE_SNIPPET for snippet in evidence_snippets)
    if not has_real_snippet:
        return True
    mission_driver = str(row.get("mission_driver", "") or "").strip()
    budget_signal = str(row.get("budget_signal", "") or "").strip()
    if mission_driver == NO_MISSION_DRIVER:
        return True
    if budget_signal == NO_BUDGET_SIGNAL or budget_signal.startswith(NO_FUNDING_CORROBORATION.split(";")[0]):
        return True
    return False


def _is_corroborated_objective_row(row: dict[str, object]) -> bool:
    if bool(row.get("attachment_native_corroborated")):
        return True
    if _is_fallback_objective_row(row):
        return False
    evidence_snippets = row.get("evidence_snippets", [])
    if not isinstance(evidence_snippets, list):
        return False
    return any(str(snippet or "").strip() and str(snippet or "").strip() != NO_EVIDENCE_SNIPPET for snippet in evidence_snippets)


def _memo_honesty_assessment(
    public_research: dict[str, object],
    objective_row_count: int,
    fallback_objective_rows: int,
    real_funding_signal_count: int,
    attachments_expected: bool,
    parsed_attachment_count: int,
) -> dict[str, object]:
    score = 100
    concerns: list[str] = []
    requirement_relevant_ratio = float(public_research.get("requirement_relevant_ratio", 0.0) or 0.0)
    core_context_anchor_count = int(public_research.get("core_context_anchor_count", 0) or 0)

    if objective_row_count and fallback_objective_rows:
        if fallback_objective_rows >= objective_row_count:
            score -= 35
            concerns.append("All objective rows still depend on fallback decomposition rather than validated task structure.")
        else:
            score -= 20
            concerns.append("Some objective rows still depend on fallback decomposition rather than validated task structure.")
    if requirement_relevant_ratio < 0.5:
        score -= 25 if requirement_relevant_ratio < 0.25 else 15
        concerns.append(
            f"Public-source relevance is still weak ({requirement_relevant_ratio:.2f} requirement-bearing ratio across admitted public sources)."
        )
    if real_funding_signal_count == 0:
        score -= 20
        concerns.append("No real funding signal was corroborated in this run.")
    if core_context_anchor_count == 0:
        score -= 10
        concerns.append("No requirement-bearing mission, budget, or forecast anchor source survived admission.")
    if attachments_expected and parsed_attachment_count == 0:
        score -= 15
        concerns.append("Expected attachments were not parsed, which leaves scope interpretation under-supported.")

    score = max(0, score)
    confidence_band = "High" if score >= 80 else "Medium" if score >= 60 else "Low"
    release_warning = (
        "Release warning: this memo is informative but not yet decision-grade until fallback objectives, public-source relevance, and funding corroboration improve."
        if concerns
        else ""
    )
    return {
        "score": score,
        "confidence_band": confidence_band,
        "requirement_relevant_ratio": requirement_relevant_ratio,
        "release_warning": release_warning,
        "drivers": concerns,
    }


def _has_substantive_public_excerpt(public_context: dict[str, object]) -> bool:
    if public_context.get("status") != "ok":
        return False
    excerpt = _clean_excerpt(public_context.get("text_excerpt", ""))
    if len(excerpt) < 250:
        return False
    normalized = excerpt.lower()
    weak_markers = (
        "javascript is disabled",
        "skip to main content",
        "sign in",
        "an official website",
        "@font face",
        "font family",
        "woff2",
        "html line height",
        "sam acquisition 360 html",
    )
    return not any(marker in normalized for marker in weak_markers)


def _best_notice_excerpt(
    public_context: dict[str, object],
    opportunity: dict[str, object],
    explanation: dict[str, object],
) -> tuple[str, bool]:
    public_excerpt = _clean_excerpt(public_context.get("text_excerpt", ""))
    if _has_substantive_public_excerpt(public_context):
        return public_excerpt, True
    for candidate in (opportunity.get("summary", ""), explanation.get("summary", "")):
        cleaned = _clean_excerpt(candidate)
        if len(cleaned) >= 180:
            return cleaned, True
    return public_excerpt, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--entry")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--title", default="")
    parser.add_argument("--buyer", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--notice-id", default="")
    parser.add_argument("--solicitation-number", default="")
    parser.add_argument("--depth", default="full_360")
    args = parser.parse_args()
    if not args.entry and not args.file:
        parser.error("Provide --entry for tracked capture or at least one --file for direct local-file capture.")

    workspace = Path(args.workspace)
    bundle_root = Path(__file__).resolve().parents[2]
    vendor_profile = load_json(workspace / "procurement" / "vendor-profile.json", default={})
    preferences = load_json(workspace / "procurement" / "preferences.json", default={})
    learning = preferences.get("learning", {}) if isinstance(preferences.get("learning"), dict) else {}
    learned_semantic_preferences = (
        learning.get("semantic_applied_preferences", {})
        if isinstance(learning.get("semantic_applied_preferences"), dict)
        else {}
    )
    local_file_paths = _normalize_local_file_inputs(workspace, args.file)
    capture_mode = "tracked"
    if args.entry:
        resolved = resolve_entry(workspace, args.entry)
        if local_file_paths:
            resolved = dict(resolved)
            resolved["entry_resolution_mode"] = "entry_plus_local_files"
            resolved["local_files"] = local_file_paths
            capture_mode = "tracked_plus_local_files"
    else:
        resolved = _build_direct_local_resolution(
            local_file_paths=local_file_paths,
            title=args.title,
            buyer=args.buyer,
            summary=args.summary,
            url=args.url,
            notice_id=args.notice_id,
            solicitation_number=args.solicitation_number,
        )
        capture_mode = "direct_local_files"
    digest_date = resolved.get("digest_date") or today_local_str()
    display_entry = resolved.get("report_entry_id") or "direct"
    entry_value = args.entry or str(resolved.get("title") or resolved.get("solicitation_number") or resolved.get("canonical_record_id") or "direct")
    canonical_id = resolved.get("canonical_record_id") or resolved.get("notice_id") or entry_value
    request_id = request_id_for(display_entry or str(canonical_id))
    artifacts = build_request_paths(workspace, digest_date, display_entry, canonical_id, request_id)

    request_log_event = {
        "request_id": request_id,
        "timestamp": utc_now_iso(),
        "entry": entry_value,
        "entry_resolution_mode": resolved.get("entry_resolution_mode", "unresolved"),
        "capture_mode": capture_mode,
        "request_depth": "full_360_capture_brief",
        "status": "logged",
        "resolved": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
            "solicitation_number": resolved.get("solicitation_number", ""),
            "title": resolved.get("title", ""),
            "buyer": resolved.get("buyer", ""),
            "source_id": resolved.get("source_id", ""),
            "source_name": resolved.get("source_name", ""),
            "source_tier": resolved.get("source_tier", 1),
            "url": resolved.get("url", ""),
        },
        "artifacts": artifacts,
        "local_files": local_file_paths,
        "notes": ["Fresh request-specific artifacts must be created for this request."],
    }
    append_jsonl(Path(artifacts["request_log_path"]), request_log_event)

    local_context = load_notice_context(workspace, resolved) if args.entry else _build_direct_local_context(resolved)
    explanation = local_context.get("explanation_record", {})
    opportunity = local_context.get("opportunity_record", {})
    public_context = fetch_url_excerpt(resolved.get("url", ""))
    notice_excerpt, substantive_notice_excerpt = _best_notice_excerpt(public_context, opportunity, explanation)
    snapshot_resource_links = opportunity.get("resource_links", []) if isinstance(opportunity.get("resource_links"), list) else []
    snapshot_point_of_contact = opportunity.get("point_of_contact", []) if isinstance(opportunity.get("point_of_contact"), list) else []
    tracked_attachment_bundle = (
        fetch_notice_attachments(
            resolved.get("notice_id", "") or opportunity.get("notice_id", "") or canonical_id,
            solicitation_number=str(opportunity.get("solicitation_number", "") or resolved.get("solicitation_number", "") or ""),
            resource_links=snapshot_resource_links,
            point_of_contact=snapshot_point_of_contact,
        )
        if args.entry
        else {
            "status": "skipped",
            "record": {},
            "point_of_contact": [],
            "attachments": [],
            "attachments_expected": False,
            "record_lookup_status": "skipped",
            "resource_listing_status": "skipped",
            "seeded_resource_links": False,
            "resource_link_count": 0,
            "errors": [],
        }
    )
    local_attachment_bundle = load_local_attachments(local_file_paths) if local_file_paths else {
        "status": "skipped",
        "record": {},
        "point_of_contact": [],
        "attachments": [],
        "attachments_expected": False,
        "record_lookup_status": "skipped",
        "resource_listing_status": "skipped",
        "seeded_resource_links": False,
        "resource_link_count": 0,
        "errors": [],
    }
    attachment_bundle = _merge_attachment_bundles(tracked_attachment_bundle, local_attachment_bundle)
    attachment_scope_snippets = _attachment_scope_snippets(attachment_bundle)
    attachment_text_pool = _attachment_text_pool(attachment_bundle, max_items=6)
    attachment_context_text = " ".join(attachment_scope_snippets)
    notice_context_text = _clean_excerpt(
        f"{opportunity.get('summary', '')} {notice_excerpt} {attachment_context_text} {' '.join(attachment_text_pool)}",
        max_chars=16000,
    )
    stakeholder_contacts = _dedupe_contacts(
        _contacts_from_point_of_contact(attachment_bundle.get("point_of_contact", [])),
        _extract_stakeholder_contacts(
            opportunity.get("summary", ""),
            notice_excerpt,
            " ".join(
                _attachment_text_value(item)
                for item in (attachment_bundle.get("attachments", []) or [])[:3]
                if isinstance(item, dict)
            ),
        ),
    )
    stakeholder_map = _stakeholder_lines(resolved.get("buyer", ""), stakeholder_contacts, notice_context_text)
    stakeholder_map.extend(_attachment_manifest_lines(attachment_bundle))
    public_research = fetch_public_research(
        {
            "buyer": resolved.get("buyer", ""),
            "title": resolved.get("title", ""),
            "url": resolved.get("url", ""),
        },
        notice_context_text,
        stakeholder_contacts,
    )
    usaspending_result = enrich_from_usaspending(
        resolved.get("title") or canonical_id,
        title=resolved.get("title", ""),
        summary=notice_context_text,
        buyer=resolved.get("buyer", ""),
    )
    award_signals = _award_history_signals(
        usaspending_result,
        resolved.get("title", ""),
        notice_context_text,
        resolved.get("buyer", ""),
    )
    attachment_validation = _attachment_incumbent_validation(
        attachment_bundle,
        award_signals.get("competitive_landscape", {}).get("likely_incumbents", []),
    )
    executive_summary = _clean_excerpt(
        explanation.get("summary") or opportunity.get("summary") or "Fresh structured capture brief generated from current request context."
    )
    decomposed_objectives = _decompose_objectives(
        resolved.get("title", ""),
        opportunity.get("summary", ""),
        explanation.get("summary", ""),
        attachment_bundle,
    )
    public_sources = []
    if public_context.get("status") == "ok":
        public_sources.append(
            {
                "title": f"Official page for {resolved.get('title', 'opportunity')}",
                "url": resolved.get("url", ""),
                "publisher": resolved.get("source_name", "Official source"),
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": resolved.get("source_tier", 1),
                "relevance": "Primary public notice context",
                "confidence": 3,
            }
        )

    usaspending_status = usaspending_result.get("spending_by_award", {}).get("status", "error")
    public_excerpt_substantive = _has_substantive_public_excerpt(public_context)
    if usaspending_status in {"ok", "http_error", "error"}:
        public_sources.append(
            {
                "title": "USAspending spending by award search",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "publisher": "USAspending.gov",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"Contract award enrichment status: {usaspending_status}; queries: {', '.join(usaspending_result.get('search_terms', [])) or 'none'}",
                "confidence": 2 if usaspending_status == "ok" else 1,
            }
        )
    public_sources.extend(award_signals.get("source_log", []))
    public_sources.extend(_attachment_source_log(attachment_bundle))
    public_sources.extend(public_research.get("source_log", []))

    status = "PARTIAL_CAPTURE_RESEARCH"
    attachment_categories = Counter(
        str(item.get("category", "other"))
        for item in (attachment_bundle.get("attachments", []) or [])
        if isinstance(item, dict)
    )
    attachment_budget_signals: list[str] = []
    if attachment_categories.get("pricing") or attachment_categories.get("schedule"):
        attachment_budget_signals.append(
            f"Attachment package includes {attachment_categories.get('pricing', 0)} pricing file(s) and {attachment_categories.get('schedule', 0)} schedule file(s) for direct CLIN and timeline validation."
        )
    if attachment_categories.get("amendment"):
        attachment_budget_signals.append(
            f"Attachment package includes {attachment_categories.get('amendment', 0)} amendment file(s), which can validate scope changes and final instructions."
        )
    attachment_scope_or_notice_snippets = attachment_scope_snippets or [notice_excerpt[:300] or "No substantive notice excerpt captured in this run."]
    attachment_text_blob = " ".join(attachment_text_pool).lower()
    vehicle_signals = []
    if "gsa mas" in attachment_text_blob or "multiple award schedule" in attachment_text_blob or "federal supply schedule" in attachment_text_blob:
        vehicle_signals.append("Attachment text references a GSA or schedule-style acquisition path that should be validated against the solicitation package.")
    if "indefinite-delivery-indefinite-quantity" in attachment_text_blob or "indefinite delivery indefinite quantity" in attachment_text_blob or "idiq" in attachment_text_blob:
        vehicle_signals.append("Attachment text references an IDIQ-style contract structure that should be validated against the solicitation package.")
    if "single award task order contract" in attachment_text_blob or "satoc" in attachment_text_blob:
        vehicle_signals.append("Attachment text references a SATOC / task-order contract structure that should be validated against the solicitation package.")
    if not vehicle_signals:
        vehicle_signals.append("Likely vehicle path remains unconfirmed from the current public package; validate open-market versus existing-vehicle assumptions.")
    attachment_competitive_notes = _dedupe_strings(
        attachment_validation.get("notes", [])
        + attachment_validation.get("direct_mentions", [])
        + attachment_validation.get("supporting_snippets", [])
    )
    funding_assessment = _funding_assessment(
        award_signals,
        public_research,
        attachment_budget_signals,
    )
    funding_gap_line = (
        f'No funding corroboration found for "{resolved.get("title") or "this requirement"}" in current run; '
        "validate with award history, budget docs, or priced attachments."
    )
    budget_funding_signals = [
        *(award_signals.get("budget_signals", []) if award_signals.get("budget_usable_for_capture") else []),
        *public_research.get("budget_document_signals", []),
        *attachment_budget_signals,
    ]
    if not budget_funding_signals:
        budget_funding_signals = [funding_gap_line]
    related_procurements = award_signals.get("related_procurements", []) + attachment_validation.get("supporting_snippets", [])
    evidence_gaps = _dedupe_strings(
        [
            *(
                []
                if attachment_scope_snippets
                else ["Fresh solicitation objectives still need deeper parsing from official attachment documents."]
            ),
            *(
                []
                if attachment_bundle.get("attachments")
                else ["No attachment package was parsed in this run, so scope validation still leans on notice text."]
            ),
            *(
                []
                if attachment_validation.get("validated_incumbents") or attachment_validation.get("supporting_snippets")
                else ["Attachment package did not directly validate the incumbent story, so award-history inference still needs manual confirmation."]
            ),
            *(
                []
                if award_signals.get("budget_usable_for_capture") or not award_signals.get("relevant_awards")
                else ["USAspending returned acronym-only or weak-overlap award matches, so those rows were not used as funding evidence."]
            ),
            *award_signals.get("evidence_gaps", []),
            *public_research.get("evidence_gaps", []),
        ]
    )
    executive_risks = _dedupe_strings(
        [
            "Fresh public evidence may still be incomplete if key agency strategy or oversight sources were not discoverable this run.",
            "Incumbent and funding signals should still be checked against the full solicitation package, Q&A, and any archived predecessor awards.",
            *evidence_gaps[:2],
        ]
    )
    executive_success_metrics = _dedupe_strings(
        [
            "Validated scope understanding",
            "Incumbent posture clarity",
            "Actionable next capture moves",
            *(_matching_lines("success metrics", public_research.get("mission_context_signals", []), max_items=1) if public_research.get("mission_context_signals") else []),
        ]
    )
    incumbent_list = (
        attachment_validation.get("validated_incumbents", [])
        or award_signals.get("competitive_landscape", {}).get("likely_incumbents", [])
    )
    scope_corroborated = bool(attachment_scope_snippets)
    mission_corroborated = bool(public_research.get("mission_context_signals"))
    policy_corroborated = bool(public_research.get("policy_compliance_signals"))
    award_corroborated = bool(award_signals.get("relevant_awards"))
    executive_win_themes = _dedupe_strings(
        [
            *(
                ["Evidence-backed federal mission fit"]
                if scope_corroborated and (mission_corroborated or award_corroborated)
                else []
            ),
            *(
                ["Clear compliance and delivery readiness"]
                if scope_corroborated and policy_corroborated
                else []
            ),
            *(
                ["Proven COTS capability with rapid IRS/NIST control alignment."]
                if scope_corroborated and policy_corroborated and ("cots" in attachment_text_blob or "commercial off" in attachment_text_blob)
                else []
            ),
            *(
                ["Predictable fixed-price delivery with disciplined staffing and reporting controls."]
                if scope_corroborated and award_corroborated and ("firm fixed price" in attachment_text_blob or "ffp" in attachment_text_blob)
                else []
            ),
        ]
    )
    if not executive_win_themes:
        executive_win_themes = [NO_WIN_THEMES]
    executive_proof_points = _dedupe_strings(
        [
            *(
                ["Recent relevant delivery examples"]
                if award_corroborated
                else []
            ),
            *(
                ["Federal program alignment"]
                if scope_corroborated and mission_corroborated
                else []
            ),
            *(
                ["Documented security/privacy readiness tied to Publication 4812 and NIST requirements."]
                if scope_corroborated and policy_corroborated
                else []
            ),
            *(
                ["Demonstrated staffing continuity and post-award mobilization discipline."]
                if scope_corroborated and award_corroborated and ("staff" in attachment_text_blob or "workforce" in attachment_text_blob)
                else []
            ),
        ]
    )
    if not executive_proof_points:
        executive_proof_points = [NO_PROOF_POINTS]
    objective_rows: list[dict[str, object]] = []
    for objective_text in decomposed_objectives:
        attachment_native_evidence = _attachment_objective_evidence_snippets(
            objective_text,
            attachment_bundle,
            max_items=4,
        )
        evidence_snippets = _objective_evidence_snippets(
            objective_text,
            attachment_native_evidence or attachment_scope_or_notice_snippets,
            public_research,
            related_procurements,
        )
        objective_rows.append(
            {
                "objective": objective_text,
                "mission_driver": _objective_driver(
                    objective_text,
                    public_research.get("mission_context_signals", []),
                    NO_MISSION_DRIVER,
                ),
                "policy_driver": _objective_driver(
                    objective_text,
                    public_research.get("policy_compliance_signals", []),
                    "No corroborated policy or compliance driver found for this objective in current evidence.",
                ),
                "budget_signal": _objective_driver(
                    objective_text,
                    budget_funding_signals,
                    award_signals.get("objective_budget_signal") or NO_BUDGET_SIGNAL,
                ),
                "stakeholders": _objective_stakeholder_text(resolved.get("buyer", ""), stakeholder_contacts),
                "incumbents": ", ".join(incumbent_list) if incumbent_list else INCUMBENT_UNVERIFIED,
                "key_risks": _objective_key_risks(objective_text, evidence_gaps),
                "kpis": _objective_kpis(objective_text),
                "solution_implications": _objective_solution_implications(objective_text),
                "evidence_links": _objective_evidence_links(resolved.get("url", ""), public_sources, objective_text),
                "attachment_native_corroborated": bool(attachment_native_evidence),
                "attachment_native_evidence_snippets": attachment_native_evidence,
                "evidence_snippets": evidence_snippets,
            }
        )
    corroborated_objective_rows = sum(1 for row in objective_rows if _is_corroborated_objective_row(row))
    fallback_objective_rows = sum(1 for row in objective_rows if _is_fallback_objective_row(row))
    attachment_native_corroborated_rows = sum(1 for row in objective_rows if bool(row.get("attachment_native_corroborated")))
    real_funding_signal_count = sum(
        1 for signal in budget_funding_signals if not str(signal or "").startswith("No funding corroboration found")
    )
    public_research_assessment = _public_research_assessment(public_research)
    memo_honesty = _memo_honesty_assessment(
        public_research,
        len(objective_rows),
        fallback_objective_rows,
        real_funding_signal_count,
        bool(attachment_bundle.get("attachments_expected")),
        len(attachment_bundle.get("attachments", []) or []),
    )
    decision_sections = build_capture_decision_sections(
        vendor_profile=vendor_profile,
        resolved=resolved,
        opportunity=opportunity,
        explanation=explanation,
        notice_context_text=notice_context_text,
        attachment_bundle=attachment_bundle,
        attachment_validation=attachment_validation,
        public_research=public_research,
        award_signals=award_signals,
        funding_assessment=funding_assessment,
        source_log=public_sources,
        evidence_gaps=evidence_gaps,
        stakeholder_contacts=stakeholder_contacts,
        vehicle_signals=vehicle_signals,
        learned_semantic_preferences=learned_semantic_preferences,
    )
    decision_sections.setdefault("capture_judgment", {}).update(
        {
            "memo_honesty_score": memo_honesty.get("score", 0),
            "memo_honesty_confidence": memo_honesty.get("confidence_band", "Low"),
            "release_warning": memo_honesty.get("release_warning", ""),
            "honesty_drivers": memo_honesty.get("drivers", []),
        }
    )
    decision_sections.setdefault("assumptions_unknowns_confidence", {}).update(
        {
            "memo_honesty_score": memo_honesty.get("score", 0),
            "release_warning": memo_honesty.get("release_warning", ""),
            "honesty_drivers": memo_honesty.get("drivers", []),
        }
    )
    evidence = {
        "request_id": request_id,
        "generated_at": utc_now_iso(),
        "status": status,
        "vendor_name": decision_sections.get("vendor_name", "Vendor"),
        "entry": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
            "solicitation_number": resolved.get("solicitation_number", ""),
            "title": resolved.get("title", ""),
            "buyer": resolved.get("buyer", ""),
            "source_id": resolved.get("source_id", ""),
            "source_name": resolved.get("source_name", ""),
            "source_tier": resolved.get("source_tier", 1),
            "url": resolved.get("url", ""),
        },
        "artifacts": {
            "request_log_path": artifacts["request_log_path"],
            "request_capture_brief_path": artifacts["request_capture_brief_path"],
            "request_capture_evidence_path": artifacts["request_capture_evidence_path"],
        },
        "executive_brief": {
            "summary": executive_summary,
            "objective_summaries": decomposed_objectives,
            "why_now": "This opportunity is now in capture because it matched the latest workspace shortlist or direct identifier lookup.",
            "why_now_signals": _dedupe_strings(
                public_research.get("mission_context_signals", [])[:2]
                + public_research.get("budget_document_signals", [])[:1]
                + public_research.get("policy_compliance_signals", [])[:1]
            ),
            "risks": executive_risks,
            "success_metrics": executive_success_metrics,
            "incumbent_posture": _dedupe_strings(
                [
                    f"Likely incumbents or related performers: {', '.join(incumbent_list)}" if incumbent_list else "No confirmed incumbent named in current request artifacts.",
                    *award_signals.get("competitive_landscape", {}).get("notes", [])[:2],
                ]
            ),
            "win_themes": executive_win_themes,
            "proof_points": executive_proof_points,
        },
        "objectives": objective_rows,
        "stakeholder_map": stakeholder_map,
        "stakeholder_contacts": stakeholder_contacts,
        "leadership_priority_signals": public_research.get("leadership_priority_signals", []),
        "mission_context_signals": public_research.get("mission_context_signals", []),
        "policy_compliance_signals": public_research.get("policy_compliance_signals", []),
        "oversight_signals": public_research.get("oversight_signals", []),
        "acquisition_forecast_signals": public_research.get("acquisition_forecast_signals", []),
        "budget_funding_signals": budget_funding_signals,
        "funding_assessment": funding_assessment,
        "related_procurements": related_procurements,
        "vehicle_signals": vehicle_signals,
        "competitive_landscape": {
            **award_signals.get("competitive_landscape", {}),
            "likely_incumbents": (
                incumbent_list
                or award_signals.get("competitive_landscape", {}).get("likely_incumbents", [])
            ),
            "notes": _dedupe_strings(
                award_signals.get("competitive_landscape", {}).get("notes", [])
                + attachment_competitive_notes
            ),
        },
        "award_history_signals": {
            "queries": award_signals.get("queries", []),
            "relevant_awards": award_signals.get("relevant_awards", []),
        },
        "attachment_signals": {
            "status": attachment_bundle.get("status", "unknown"),
            "attachments_expected": bool(attachment_bundle.get("attachments_expected")),
            "record_lookup_status": attachment_bundle.get("record_lookup_status", "unknown"),
            "resource_listing_status": attachment_bundle.get("resource_listing_status", "unknown"),
            "seeded_resource_links": bool(attachment_bundle.get("seeded_resource_links")),
            "resource_link_count": attachment_bundle.get("resource_link_count", 0),
            "parsed_attachments": attachment_bundle.get("attachments", []),
            "errors": attachment_bundle.get("errors", []),
            "scope_snippets": attachment_scope_snippets,
            "incumbent_validation": attachment_validation,
        },
        "public_discourse_signals": public_research.get("public_discourse_signals", []),
        "public_research_assessment": public_research_assessment,
        "recommended_next_research_moves": _dedupe_strings(
            [
                *(
                    ["Pull agency strategy, policy, and oversight documents linked to the mission area."]
                    if not public_research.get("mission_context_signals") or not public_research.get("oversight_signals")
                    else []
                ),
                *(
                    ["Validate the final attachment set, especially SOW, instructions, Q&A, and amendments, against the award-history hypothesis."]
                    if attachment_bundle.get("attachments")
                    else ["Recover or re-fetch the attachment package to validate scope, evaluation, and amendment details."]
                ),
                *(
                    ["Confirm whether the extracted contracting contacts map to the true program owner and evaluation team."]
                    if not public_research.get("leadership_priority_signals")
                    else ["Align capture messaging to the leadership priorities and named officials surfaced in public sources."]
                ),
                *(
                    ["Pull budget justification and acquisition forecast materials to tighten funding and timing assumptions."]
                    if not public_research.get("budget_document_signals") or not public_research.get("acquisition_forecast_signals")
                    else []
                ),
            ]
        ),
        "action_items_next_10_days": _dedupe_strings(
            [
                "Confirm mission driver and program owner from official sources.",
                "Pressure-test the incumbent hypothesis against attachments, amendments, and archived awards.",
                "Translate findings into win themes and proof points for capture planning.",
                *(
                    ["Map proposal themes directly to the named policy/compliance artifacts surfaced in this run."]
                    if public_research.get("policy_compliance_signals")
                    else []
                ),
            ]
        ),
        "assumptions_to_validate": [
            "The visible buyer signal correctly identifies the mission owner.",
            "The public award-history matches are materially related to this requirement rather than adjacent market activity.",
            *(
                []
                if public_research.get("budget_document_signals")
                else ["No official budget document was captured in this run, so budget reality is still inferred rather than fully corroborated."]
            ),
        ],
        "evidence_gaps": evidence_gaps,
        "semantic_preference_signals": {
            "scan_semantic_fit": opportunity.get("semantic_fit", {}) if isinstance(opportunity.get("semantic_fit"), dict) else {},
            "learned_semantic_preferences": learned_semantic_preferences,
        },
        "source_log": public_sources,
        "memo_honesty_assessment": memo_honesty,
        "validation": {
            "all_required_sections_present": False,
            "contains_placeholders": False,
            "generated_from_current_request": True,
            "public_excerpt_substantive": public_excerpt_substantive,
            "notice_excerpt_substantive": substantive_notice_excerpt,
            "attachment_package_parsed": bool(attachment_bundle.get("attachments")),
            "attachments_expected": bool(attachment_bundle.get("attachments_expected")),
            "usaspending_search_status": usaspending_status,
            "objective_validation_summary": {
                "objective_row_count": len(objective_rows),
                "corroborated_objective_rows": corroborated_objective_rows,
                "fallback_objective_rows": fallback_objective_rows,
                "attachment_native_corroborated_rows": attachment_native_corroborated_rows,
                "real_funding_signal_count": real_funding_signal_count,
            },
            "public_research_assessment": public_research_assessment,
            "memo_honesty": memo_honesty,
            "stub_stage_exited_before_response": True,
            "menu_only_fallback_used": False,
        },
    }
    evidence.update(decision_sections)

    brief_text = render_capture_brief(bundle_root / "templates" / "capture-brief.template.md", evidence)
    brief_validation = validate_capture_brief_text(brief_text)
    evidence["validation"]["all_required_sections_present"] = brief_validation["all_required_sections_present"]
    coverage_categories = int(public_research.get("qualified_category_count", 0) or 0)
    public_research_quality_score = int(public_research.get("quality_score", 0) or 0)
    core_context_anchor_count = int(public_research.get("core_context_anchor_count", 0) or 0)
    funding_or_buying_anchor_count = int(public_research.get("funding_or_buying_anchor_count", 0) or 0)
    strong_public_sources = sum(
        1 for item in (public_research.get("source_log", []) or []) if int(item.get("quality_score", 0) or 0) >= 12
    )
    same_agency_award_history = bool(award_signals.get("relevant_awards"))
    attachment_lookup_clean = (
        attachment_bundle.get("status") in {"ok", "empty"}
        and not (attachment_bundle.get("errors", []) or [])
    )
    attachment_completion_ready = bool(attachment_bundle.get("attachments")) or (
        not attachment_bundle.get("attachments_expected")
        and attachment_lookup_clean
    )
    if (
        resolved.get("status") == "resolved"
        and substantive_notice_excerpt
        and usaspending_status == "ok"
        and attachment_completion_ready
        and brief_validation["all_required_sections_present"]
        and len(public_sources) >= 8
        and coverage_categories >= 4
        and strong_public_sources >= 5
        and core_context_anchor_count >= 1
        and (same_agency_award_history or funding_or_buying_anchor_count >= 1)
        and public_research_quality_score >= 90
    ):
        status = "360_DEEP_RESEARCH_COMPLETE"
    evidence["status"] = status
    brief_text = render_capture_brief(bundle_root / "templates" / "capture-brief.template.md", evidence)

    write_text(Path(artifacts["request_capture_brief_path"]), brief_text)
    write_json(Path(artifacts["request_capture_evidence_path"]), evidence)
    write_text(Path(artifacts["latest_alias_capture_brief_path"]), brief_text)
    write_json(Path(artifacts["latest_alias_capture_evidence_path"]), evidence)

    final_log_event = dict(request_log_event)
    final_log_event["status"] = status
    final_log_event["notes"] = [
        "Fresh request-specific brief and evidence were generated for this request.",
        f"Public notice fetch status: {public_context.get('status', 'unknown')}",
        f"Public notice excerpt substantive: {'yes' if public_excerpt_substantive else 'no'}",
        f"Expanded public research status: {public_research.get('status', 'unknown')} ({len(public_research.get('source_log', []) or [])} sources)",
        f"USAspending enrichment status: {usaspending_status}",
        f"Attachment parsing status: {attachment_bundle.get('status', 'unknown')} ({len(attachment_bundle.get('attachments', []) or [])} files parsed)",
    ]
    append_jsonl(Path(artifacts["request_log_path"]), final_log_event)

    result = {
        "status": status,
        "request_id": request_id,
        "brief_path": artifacts["request_capture_brief_path"],
        "evidence_path": artifacts["request_capture_evidence_path"],
        "capture_mode": capture_mode,
        "browser_attempted": False,
        "browser_succeeded": False,
        "usaspending_attempted": True,
        "usaspending_succeeded": usaspending_status == "ok",
        "attachments_attempted": bool(snapshot_resource_links or resolved.get("notice_id") or local_file_paths),
        "attachments_expected": bool(attachment_bundle.get("attachments_expected")),
        "attachments_succeeded": bool(attachment_bundle.get("attachments")),
        "expanded_public_research_attempted": True,
        "expanded_public_research_succeeded": bool(public_research.get("source_log")),
        "stable_id": resolved.get("report_entry_id", ""),
        "canonical_record_id": canonical_id,
        "recommended_next_moves": evidence["recommended_next_research_moves"],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if status == "360_DEEP_RESEARCH_COMPLETE" else 10


if __name__ == "__main__":
    raise SystemExit(main())
