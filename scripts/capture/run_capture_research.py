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
from common.paths import safe_slug, standard_procurement_paths, today_local_str, utc_now_iso, write_json, write_text
from common.validation import validate_capture_brief_text
from capture.fetch_notice_attachments import fetch_notice_attachments
from capture.fetch_notice_context import load_notice_context
from capture.fetch_public_context import fetch_url_excerpt
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


def _clean_excerpt(value: object, max_chars: int = 4000) -> str:
    raw = str(value or "")
    text = SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(raw))).strip()
    return text[:max_chars]


def _normalize_signal_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_excerpt(value, max_chars=12000).lower()).strip()


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
        text = str(item.get("text_excerpt", "") or "")
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
        (str(item.get("filename", "attachment") or "attachment"), _normalize_signal_text(item.get("text_excerpt", "")))
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


def _award_history_signals(
    usaspending_result: dict[str, object],
    title: str,
    summary: str,
    buyer: str,
) -> dict[str, object]:
    response = ((usaspending_result.get("spending_by_award") or {}).get("response") or {}) if isinstance(usaspending_result, dict) else {}
    queries = list(response.get("query_terms", []) or usaspending_result.get("search_terms", []) or [])
    relevant_rows = _relevant_award_rows(usaspending_result, title, summary, buyer)
    agency_rows = [row for row in relevant_rows if row.get("_agency_match")]
    amount_rows = agency_rows or relevant_rows
    all_amounts = [amount for amount in (_safe_float(row.get("Award Amount")) for row in amount_rows) if amount is not None]
    likely_rows = agency_rows or relevant_rows
    likely_incumbents = _dedupe_strings([str(row.get("Recipient Name", "") or "") for row in likely_rows])[:4]
    frequent_primes = [name for name, _ in Counter(str(row.get("Recipient Name", "") or "") for row in relevant_rows if row.get("Recipient Name")).most_common(5)]
    emerging_challengers = _dedupe_strings(
        [
            str(row.get("Recipient Name", "") or "")
            for row in relevant_rows
            if not row.get("_agency_match") and str(row.get("Recipient Name", "") or "")
        ]
    )[:4]

    budget_signals: list[str] = []
    related_procurements: list[str] = []
    source_log: list[dict[str, object]] = []
    notes: list[str] = []
    evidence_gaps: list[str] = []

    if relevant_rows:
        queries_with_results = _dedupe_strings([term for row in relevant_rows for term in row.get("_query_terms", []) or []])
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
        if len(relevant_rows) > len(agency_rows):
            notes.append(
                "Additional cross-agency matches indicate adjacent market performers, but they are not direct proof of incumbency on this solicitation."
            )
        for row in relevant_rows[:4]:
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
            f"USAspending returned no clearly relevant award-history matches across query terms: {', '.join(queries) if queries else 'none'}."
        )
        notes.append("No clearly relevant prior award history was surfaced from the current USAspending query set.")
        evidence_gaps.append("USAspending did not surface clearly relevant prior awards, so incumbent and funding signals still need manual validation.")
        source_log.append(
            {
                "title": "USAspending award history search",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "publisher": "USAspending.gov",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"No clearly relevant awards across queries: {', '.join(queries) if queries else 'none'}",
                "confidence": 1,
            }
        )

    return {
        "queries": queries,
        "relevant_awards": relevant_rows,
        "budget_signals": budget_signals,
        "related_procurements": related_procurements,
        "competitive_landscape": {
            "likely_incumbents": likely_incumbents,
            "frequent_primes": frequent_primes,
            "common_teammates": [],
            "emerging_challengers": emerging_challengers,
            "notes": notes or ["Competitive posture remains thin because no related award history was parsed."],
        },
        "objective_budget_signal": budget_signals[0] if budget_signals else "Award-history signal unavailable.",
        "objective_incumbents": ", ".join(likely_incumbents) if likely_incumbents else "No clearly relevant prior award recipients surfaced from USAspending.",
        "evidence_gaps": evidence_gaps,
        "source_log": source_log,
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
    parser.add_argument("--entry", required=True)
    parser.add_argument("--depth", default="full_360")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    bundle_root = Path(__file__).resolve().parents[2]
    resolved = resolve_entry(workspace, args.entry)
    digest_date = resolved.get("digest_date") or today_local_str()
    display_entry = resolved.get("report_entry_id") or "direct"
    canonical_id = resolved.get("canonical_record_id") or resolved.get("notice_id") or args.entry
    request_id = request_id_for(display_entry or canonical_id)
    artifacts = build_request_paths(workspace, digest_date, display_entry, canonical_id, request_id)

    request_log_event = {
        "request_id": request_id,
        "timestamp": utc_now_iso(),
        "entry": args.entry,
        "entry_resolution_mode": resolved.get("entry_resolution_mode", "unresolved"),
        "request_depth": "full_360_capture_brief",
        "status": "logged",
        "resolved": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
            "title": resolved.get("title", ""),
            "buyer": resolved.get("buyer", ""),
            "source_id": resolved.get("source_id", ""),
            "source_name": resolved.get("source_name", ""),
            "source_tier": resolved.get("source_tier", 1),
            "url": resolved.get("url", ""),
        },
        "artifacts": artifacts,
        "notes": ["Fresh request-specific artifacts must be created for this request."],
    }
    append_jsonl(Path(artifacts["request_log_path"]), request_log_event)

    local_context = load_notice_context(workspace, resolved)
    explanation = local_context.get("explanation_record", {})
    opportunity = local_context.get("opportunity_record", {})
    public_context = fetch_url_excerpt(resolved.get("url", ""))
    notice_excerpt, substantive_notice_excerpt = _best_notice_excerpt(public_context, opportunity, explanation)
    snapshot_resource_links = opportunity.get("resource_links", []) if isinstance(opportunity.get("resource_links"), list) else []
    snapshot_point_of_contact = opportunity.get("point_of_contact", []) if isinstance(opportunity.get("point_of_contact"), list) else []
    attachment_bundle = fetch_notice_attachments(
        resolved.get("notice_id", "") or opportunity.get("notice_id", "") or canonical_id,
        solicitation_number=str(opportunity.get("solicitation_number", "") or ""),
        resource_links=snapshot_resource_links,
        point_of_contact=snapshot_point_of_contact,
    )
    attachment_scope_snippets = _attachment_scope_snippets(attachment_bundle)
    attachment_context_text = " ".join(attachment_scope_snippets)
    notice_context_text = _clean_excerpt(
        f"{opportunity.get('summary', '')} {notice_excerpt} {attachment_context_text}",
        max_chars=12000,
    )
    stakeholder_contacts = _dedupe_contacts(
        _contacts_from_point_of_contact(attachment_bundle.get("point_of_contact", [])),
        _extract_stakeholder_contacts(
            opportunity.get("summary", ""),
            notice_excerpt,
            " ".join(
                str(item.get("text_excerpt", "") or "")
                for item in (attachment_bundle.get("attachments", []) or [])[:3]
                if isinstance(item, dict)
            ),
        ),
    )
    stakeholder_map = _stakeholder_lines(resolved.get("buyer", ""), stakeholder_contacts, notice_context_text)
    stakeholder_map.extend(_attachment_manifest_lines(attachment_bundle))
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

    status = "PARTIAL_CAPTURE_RESEARCH"
    objective_budget_signal = award_signals.get("objective_budget_signal") or "Use USAspending and prior awards to confirm funding reality"
    objective_incumbents = (
        ", ".join(attachment_validation.get("validated_incumbents", []))
        if attachment_validation.get("validated_incumbents")
        else award_signals.get("objective_incumbents") or "To be validated with award-history enrichment"
    )
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
    attachment_competitive_notes = _dedupe_strings(
        attachment_validation.get("notes", [])
        + attachment_validation.get("direct_mentions", [])
        + attachment_validation.get("supporting_snippets", [])
    )
    evidence = {
        "request_id": request_id,
        "generated_at": utc_now_iso(),
        "status": status,
        "vendor_name": "Vendor",
        "entry": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
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
            "why_now": "This opportunity is now in capture because it matched the latest workspace shortlist or direct identifier lookup.",
            "risks": [
                "Fresh public evidence may still be incomplete if browser-safe or API-safe retrieval failed.",
                "Incumbent and funding signals should still be checked against the full solicitation package, Q&A, and any archived predecessor awards.",
            ],
            "success_metrics": [
                "Validated scope understanding",
                "Incumbent posture clarity",
                "Actionable next capture moves",
            ],
            "win_themes": [
                "Evidence-backed federal mission fit",
                "Clear compliance and delivery readiness",
            ],
            "proof_points": [
                "Recent relevant delivery examples",
                "Federal program alignment",
            ],
        },
        "objectives": [
            {
                "objective": resolved.get("title", "Opportunity objective decomposition pending"),
                "mission_driver": opportunity.get("buyer", resolved.get("buyer", "N/A")),
                "policy_driver": "Validate against agency policy and solicitation text",
                "budget_signal": objective_budget_signal,
                "stakeholders": _objective_stakeholder_text(resolved.get("buyer", ""), stakeholder_contacts),
                "incumbents": objective_incumbents,
                "key_risks": "Partial evidence until attachment package, amendments, and award history tell a consistent story",
                "kpis": "Cycle-time reduction, compliance fidelity, mission delivery outcomes",
                "solution_implications": "Shape win themes around mission fit, compliance, and realism",
                "evidence_links": resolved.get("url", "N/A"),
                "evidence_snippets": attachment_scope_or_notice_snippets,
            }
        ],
        "stakeholder_map": stakeholder_map,
        "stakeholder_contacts": stakeholder_contacts,
        "budget_funding_signals": [
            *award_signals.get("budget_signals", []),
            *attachment_budget_signals,
            f"USAspending search status this run: {usaspending_status}",
        ],
        "related_procurements": award_signals.get("related_procurements", []) + attachment_validation.get("supporting_snippets", []),
        "vehicle_signals": [
            "Assess likely vehicle path from agency history and companion notices when available.",
        ],
        "competitive_landscape": {
            **award_signals.get("competitive_landscape", {}),
            "likely_incumbents": (
                attachment_validation.get("validated_incumbents", [])
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
            "resource_link_count": attachment_bundle.get("resource_link_count", 0),
            "parsed_attachments": attachment_bundle.get("attachments", []),
            "errors": attachment_bundle.get("errors", []),
            "scope_snippets": attachment_scope_snippets,
            "incumbent_validation": attachment_validation,
        },
        "public_discourse_signals": [
            "Check agency strategic plans, OIG/GAO findings, and recent testimony aligned to this requirement.",
            "Review public statements, blogs, and procurement forecasts tied to this buyer and mission area.",
        ],
        "recommended_next_research_moves": [
            "Pull agency strategy, policy, and oversight documents linked to the mission area.",
            "Validate the final attachment set, especially SOW, instructions, Q&A, and amendments, against the award-history hypothesis.",
            "Confirm whether the extracted contracting contacts map to the true program owner and evaluation team.",
        ],
        "action_items_next_10_days": [
            "Confirm mission driver and program owner from official sources.",
            "Pressure-test the incumbent hypothesis against attachments, amendments, and archived awards.",
            "Translate findings into win themes and proof points for capture planning.",
        ],
        "assumptions_to_validate": [
            "The visible buyer signal correctly identifies the mission owner.",
            "The public award-history matches are materially related to this requirement rather than adjacent market activity.",
        ],
        "evidence_gaps": _dedupe_strings(
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
                *award_signals.get("evidence_gaps", []),
            ]
        ),
        "source_log": public_sources,
        "validation": {
            "all_required_sections_present": False,
            "contains_placeholders": False,
            "generated_from_current_request": True,
            "public_excerpt_substantive": public_excerpt_substantive,
            "notice_excerpt_substantive": substantive_notice_excerpt,
            "attachment_package_parsed": bool(attachment_bundle.get("attachments")),
            "stub_stage_exited_before_response": True,
            "menu_only_fallback_used": False,
        },
    }

    brief_text = render_capture_brief(bundle_root / "templates" / "capture-brief.template.md", evidence)
    brief_validation = validate_capture_brief_text(brief_text)
    evidence["validation"]["all_required_sections_present"] = brief_validation["all_required_sections_present"]
    if (
        resolved.get("status") == "resolved"
        and substantive_notice_excerpt
        and usaspending_status == "ok"
        and (attachment_bundle.get("attachments") or not attachment_bundle.get("resource_link_count"))
        and brief_validation["all_required_sections_present"]
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
        f"USAspending enrichment status: {usaspending_status}",
        f"Attachment parsing status: {attachment_bundle.get('status', 'unknown')} ({len(attachment_bundle.get('attachments', []) or [])} files parsed)",
    ]
    append_jsonl(Path(artifacts["request_log_path"]), final_log_event)

    result = {
        "status": status,
        "request_id": request_id,
        "brief_path": artifacts["request_capture_brief_path"],
        "evidence_path": artifacts["request_capture_evidence_path"],
        "browser_attempted": False,
        "browser_succeeded": False,
        "usaspending_attempted": True,
        "usaspending_succeeded": usaspending_status == "ok",
        "attachments_attempted": bool(snapshot_resource_links or resolved.get("notice_id")),
        "attachments_succeeded": bool(attachment_bundle.get("attachments")),
        "stable_id": resolved.get("report_entry_id", ""),
        "canonical_record_id": canonical_id,
        "recommended_next_moves": evidence["recommended_next_research_moves"],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if status == "360_DEEP_RESEARCH_COMPLETE" else 10


if __name__ == "__main__":
    raise SystemExit(main())
