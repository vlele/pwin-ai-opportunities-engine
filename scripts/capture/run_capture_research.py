from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import html
import json
import re
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.jsonl import append_jsonl
from common.commercial_intel import enrich_capture_context
from common.evidence_model import (
    build_capture_official_evidence_model,
    evidence_model_competitive_notes,
    evidence_model_next_questions,
    evidence_model_related_procurement_lines,
    evidence_model_vehicle_signals,
    merge_evidence_models,
)
from common.paths import load_json, safe_slug, standard_procurement_paths, today_local_str, utc_now_iso, write_json, write_text
from common.source_registry import get_enabled_sources
from common.validation import validate_capture_brief_text
from capture.capture_decision import build_capture_decision_sections
from capture.evaluator_anxiety import build_evaluator_anxiety_model
from capture.fetch_notice_attachments import fetch_notice_attachments, load_local_attachments
from capture.fetch_notice_context import load_notice_context
from capture.fetch_public_context import fetch_public_research, fetch_url_excerpt
from capture.render_capture_brief import render_capture_brief
from capture.resolve_entry import resolve_entry
from capture.solicitation_fact_model import build_solicitation_fact_model
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
WORKSTREAM_BULLET_RE = re.compile(r"^\s*[\u2022\u25cf\u00b7\uf0a7\-*]+\s*(.+?)\s*$")
WORKSTREAM_PAGE_RE = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.IGNORECASE)
OBJECTIVE_WRAPPER_SECTION_TITLES = {
    "performance work statement",
    "statement of work",
    "statement of objective",
    "statement of objectives",
    "description/specifications/work statement",
    "description specifications work statement",
}
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
OBJECTIVE_FORMATTING_MARKERS = (
    "tracking, kerning, and leading",
    "text size shall be no less than arial",
    "shall not exceed ten pages",
    "limited to no more than 15 pages",
    "page limits",
    "both sides of a sheet",
    "proposal paragraphs shall correspond",
    "amounts/prices shall be rounded",
    "electronic media to the poc",
    "offeror's quote must show",
    "resume shall",
    "margin",
    "font",
    "type size",
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
    "scope of work",
    "general requirements",
    "deliverables",
    "tasks",
    "task requirements",
    "specific tasks",
    "services required",
    "performance objectives",
    "quality control",
    "performance requirements",
    "acceptance criteria",
    "requirements",
)
WORKSTREAM_SECTION_HINTS = (
    "scope",
    "scope of work",
    "description of services",
    "general requirements",
    "specific tasks",
    "task requirements",
    "services required",
    "performance objectives",
    "deliverables",
    "quality control",
    "quality assurance",
    "acceptance criteria",
    "performance requirements",
    "staffing",
    "reporting",
    "management reviews",
    "transition-in",
    "transition in",
    "transition out",
)
WORKSTREAM_SECTION_SKIP_HINTS = (
    "table of contents",
    "general information",
    "acronyms",
    "definitions and acronyms",
    "government-furnished property",
    "related documents",
)
GENERIC_WORKSTREAM_TITLE_HINTS = (
    "specific tasks",
    "specific tasks and deliverables",
    "deliverables",
    "general requirements",
    "requirements",
    "scope of work",
    "description of services",
    "contractor support",
    "include, at a minimum",
    "performance work statement",
)
WORKSTREAM_SERVICE_LIST_ANCHORS = (
    "shall include but are not limited to",
    "services support shall include",
    "services shall include",
    "tasks include",
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
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
ATTACHMENT_FACT_CATEGORY_PRIORITY = {
    "solicitation": 0,
    "amendment": 1,
    "instructions_evaluation": 2,
    "statement_of_work": 3,
    "questions_answers": 4,
    "other": 5,
}
ATTACHMENT_FACT_SCOPE_PRIORITY = {
    "statement_of_work": 0,
    "solicitation": 1,
    "amendment": 2,
    "instructions_evaluation": 3,
    "questions_answers": 4,
    "other": 5,
}
GENERIC_STRATEGY_CUES = (
    "credible staffing plan",
    "day-one",
    "day one",
    "build a light compliance matrix",
    "price-to-win",
    "ghost",
    "staffing plan",
    "operating-readiness story",
    "proof point",
    "transition story",
    "continuity and transition credibility matter because",
    "reporting discipline matters because",
    "quality-control discipline matters because",
    "access and handling readiness matter because",
    "package quality and review throughput matter because",
    "show that the solution is governable in a federal environment",
    "requirement throughput with documented discipline",
    "no-drama access and security compliance",
)
GENERIC_STRATEGY_FIELDS = (
    ("hot button", "hot_buttons"),
    ("win theme", "win_themes"),
    ("discriminator", "discriminators"),
)


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


def _preferred_usaspending_search_text(resolved: dict[str, object], canonical_id: str) -> str:
    candidates = [
        str(resolved.get("notice_id", "") or "").strip(),
        str(resolved.get("solicitation_number", "") or "").strip(),
        str(canonical_id or "").strip(),
        str(resolved.get("title", "") or "").strip(),
    ]
    for candidate in candidates:
        if candidate and any(char.isdigit() for char in candidate):
            return candidate
    return next((candidate for candidate in candidates if candidate), "direct-local-capture")


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


def _normalize_inline_heading_body(text: str) -> str:
    cleaned = _clean_excerpt(text, max_chars=1600).strip()
    if not cleaned:
        return ""
    return re.sub(
        r"^(\d+(?:\.\d+){0,3}\s+(?:Scope|General Requirements|Deliverables?|Tasks?|Specific Tasks?|Performance Objectives?|Requirements?|Quality Control|Performance Requirements))\s+(?=(?:The contractor|Contractor|Provide|Maintain|Deliver|Perform|Support|Report|Inspect|Review|Manage)\b)",
        r"\1; ",
        cleaned,
        flags=re.IGNORECASE,
    )


def _compact_requirement_text(
    value: object,
    *,
    max_chars: int = 360,
    max_fragments: int = 3,
    require_action: bool = False,
) -> str:
    raw = _normalize_inline_heading_body(value)
    if not raw:
        return ""
    root_heading_stripped = re.sub(
        r"^(?:performance work statement|statement of work|statement of objectives?|description/specifications/work statement)\s*[:;.-]?\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    candidate_parts = re.split(r"(?<=[.;])\s+|(?<=\))\s+(?=[A-Z])|\n+", root_heading_stripped)
    ranked: list[tuple[int, str]] = []
    for part in candidate_parts:
        sentence = _clean_excerpt(part, max_chars=900).strip(" -;:")
        if len(sentence) < 24:
            continue
        if _is_toc_like_objective_line(sentence) or _is_boilerplate_objective_sentence(sentence):
            continue
        if OBJECTIVE_SECTION_HEADING_RE.match(sentence) and len(sentence.split()) <= 8:
            continue
        lower = sentence.lower()
        score = 0
        if OBJECTIVE_ROW_PREFIX_RE.match(sentence):
            score += 6
        if any(keyword in lower for keyword in (*OBJECTIVE_KEYWORDS, *OBJECTIVE_EXTRA_ACTION_VERBS)):
            score += 4
        if any(marker in lower for marker in ("scope", "requirement", "deliverable", "transition", "quality", "acceptance", "aql", "prs", "staff", "report")):
            score += 2
        if any(marker in lower for marker in ("mission", "purpose", "background")) and not any(
            keyword in lower for keyword in (*OBJECTIVE_KEYWORDS, *OBJECTIVE_EXTRA_ACTION_VERBS)
        ):
            score -= 3
        if require_action and not any(keyword in lower for keyword in (*OBJECTIVE_KEYWORDS, *OBJECTIVE_EXTRA_ACTION_VERBS)):
            continue
        if score <= 0 and require_action:
            continue
        ranked.append((score, sentence))
    if not ranked:
        fallback = root_heading_stripped[:max_chars].strip(" ;:-")
        return fallback
    selected: list[str] = []
    normalized_selected: list[str] = []
    for _, sentence in sorted(ranked, key=lambda item: (-item[0], len(item[1]), item[1])):
        normalized = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
        if not normalized:
            continue
        replaced = False
        for index, existing in enumerate(normalized_selected):
            shorter, longer = sorted((normalized, existing), key=len)
            if shorter and shorter in longer:
                if len(sentence) < len(selected[index]):
                    selected[index] = sentence
                    normalized_selected[index] = normalized
                replaced = True
                break
        if replaced:
            continue
        selected.append(sentence)
        normalized_selected.append(normalized)
        if len("; ".join(selected)) >= max_chars or len(selected) >= max_fragments:
            break
    return "; ".join(selected)[:max_chars].strip(" ;:-")


def _attachment_structured_rows(attachment_bundle: dict[str, object], max_items: int = 16) -> list[str]:
    candidate_categories = {"statement_of_work", "solicitation", "instructions_evaluation", "questions_answers", "amendment"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=candidate_categories,
        max_items=6,
    )
    rows: list[str] = []
    for item in ordered:
        for row in item.get("structured_rows", []) or []:
            cleaned_row = _compact_requirement_text(row, max_chars=320, max_fragments=2, require_action=True).strip(" ;:-")
            if cleaned_row and not _is_boilerplate_objective_sentence(cleaned_row):
                rows.append(cleaned_row)
                if len(rows) >= max_items:
                    return _dedupe_strings(rows)[:max_items]
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
                if _is_boilerplate_objective_sentence(current):
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
                        if _is_boilerplate_objective_sentence(next_line):
                            lookahead += 1
                            continue
                        if next_line.lower().startswith(("question", "answer", "note", "instruction")):
                            break
                        combined = f"{combined}; {next_line}"
                        lookahead += 1
                        if any(term in combined.lower() for term in ("shall", "must", "provide", "deliver", "maintain", "transition", "report", "staff")):
                            break
                    compact_combined = _compact_requirement_text(combined, max_chars=320, max_fragments=2, require_action=True)
                    if compact_combined:
                        rows.append(compact_combined)
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
                        if _is_boilerplate_objective_sentence(next_line):
                            lookahead += 1
                            continue
                        if OBJECTIVE_SECTION_HEADING_RE.match(next_line) or OBJECTIVE_ROW_PREFIX_RE.match(next_line):
                            break
                        combined = f"{combined}; {next_line}"
                        lookahead += 1
                        if any(term in combined.lower() for term in ("shall", "must", "provide", "deliver", "maintain", "transition", "report", "staff", "support")):
                            compact_combined = _compact_requirement_text(combined, max_chars=320, max_fragments=2, require_action=True)
                            if compact_combined:
                                rows.append(compact_combined)
                            break
                    index = lookahead
                    if len(rows) >= max_items:
                        return _dedupe_strings(rows)[:max_items]
                    continue
                if ("|" in raw or "\t" in raw or re.search(r" {2,}", source_lines[index])) and len(current) >= 60:
                    compact_current = _compact_requirement_text(current, max_chars=320, max_fragments=2, require_action=False)
                    if compact_current:
                        rows.append(compact_current)
                    if len(rows) >= max_items:
                        return _dedupe_strings(rows)[:max_items]
                index += 1
    return _dedupe_strings(rows)[:max_items]


def _normalize_signal_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_excerpt(value, max_chars=12000).lower()).strip()


def _attachment_text_value(item: dict[str, object], *, max_chars: int = 12000) -> str:
    return _clean_excerpt(item.get("structured_text_excerpt") or item.get("text_excerpt", ""), max_chars=max_chars)


def _attachment_section_blocks(
    attachment_bundle: dict[str, object],
    *,
    allowed_categories: set[str] | None = None,
    max_items: int = 12,
    include_filename: bool = False,
) -> list[dict[str, str]]:
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=allowed_categories,
        max_items=6,
    )
    blocks: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in ordered:
        filename = str(item.get("filename", "attachment") or "attachment")
        category = str(item.get("category", "other") or "other")
        raw_blocks = [block for block in (item.get("section_blocks", []) or []) if isinstance(block, dict)]
        specific_child_present = any(
            str(block.get("title", "") or "").strip().lower() not in OBJECTIVE_WRAPPER_SECTION_TITLES
            and bool(str(block.get("title", "") or "").strip())
            for block in raw_blocks
        )
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            title = _clean_excerpt(block.get("title", ""), max_chars=220).strip(" ;:-")
            if specific_child_present and title.lower() in OBJECTIVE_WRAPPER_SECTION_TITLES:
                continue
            source_text = _clean_excerpt(block.get("source_text", "") or block.get("text", ""), max_chars=1800).strip()
            text = _compact_requirement_text(source_text or block.get("text", ""), max_chars=420, max_fragments=3, require_action=False).strip()
            if not text or not source_text:
                continue
            key = _normalize_signal_text(f"{filename} {title} {source_text}")
            if not key or key in seen:
                continue
            seen.add(key)
            rendered = text if not include_filename else f"{filename}: {text}"
            blocks.append(
                {
                    "filename": filename,
                    "category": category,
                    "title": title or _objective_heading_title(text),
                    "text": rendered,
                    "source_text": source_text,
                }
            )
            if len(blocks) >= max_items:
                return blocks[:max_items]
    return blocks[:max_items]


def _workstream_heading_title(line: str) -> str:
    cleaned = _clean_excerpt(line, max_chars=240).strip()
    match = OBJECTIVE_HEADING_PREFIX_RE.match(cleaned)
    title = match.group(2) if match else cleaned
    return re.sub(r"\s+", " ", title).strip(" .:-")


def _is_workstream_heading(line: str) -> bool:
    cleaned = _clean_excerpt(line, max_chars=240).strip()
    if not cleaned or _is_toc_like_objective_line(cleaned) or WORKSTREAM_PAGE_RE.match(cleaned):
        return False
    return cleaned.lower() == "vision statement" or OBJECTIVE_SECTION_HEADING_RE.match(cleaned) is not None


def _workstream_line_text(line: str) -> tuple[str, bool]:
    cleaned = _clean_excerpt(line, max_chars=260).strip()
    match = WORKSTREAM_BULLET_RE.match(cleaned)
    if match:
        return match.group(1).strip(" .;:-"), True
    return cleaned.strip(" .;:-"), False


def _workstream_summary(title: str, content_lines: list[str]) -> str:
    summary_lines: list[str] = []
    service_items: list[str] = []
    in_service_list = False
    for raw_line in content_lines:
        cleaned, is_bullet = _workstream_line_text(raw_line)
        if not cleaned or WORKSTREAM_PAGE_RE.match(cleaned) or _is_toc_like_objective_line(cleaned):
            continue
        lower = cleaned.lower()
        if any(anchor in lower for anchor in WORKSTREAM_SERVICE_LIST_ANCHORS):
            in_service_list = True
            continue
        if in_service_list and is_bullet:
            service_items.append(cleaned)
            continue
        if in_service_list and service_items and len(cleaned.split()) > 10:
            in_service_list = False
        if _is_boilerplate_objective_sentence(cleaned):
            continue
        summary_lines.append(cleaned)
    prefix = _compact_requirement_text(" ".join(summary_lines[:5]).strip(), max_chars=420, max_fragments=3, require_action=False)
    if service_items:
        service_clause = ", ".join(_dedupe_strings(service_items)[:10])
        if prefix:
            return _clean_excerpt(f"{prefix} Key service areas include {service_clause}.", max_chars=900)
        return _clean_excerpt(f"{title}: Key service areas include {service_clause}.", max_chars=900)
    return prefix


def _workstream_display_title(title: str, summary: str) -> str:
    cleaned_title = _clean_excerpt(title, max_chars=180).strip(" .;:-")
    lower_title = cleaned_title.lower()
    generic_title = (
        not cleaned_title
        or any(hint in lower_title for hint in GENERIC_WORKSTREAM_TITLE_HINTS)
        or cleaned_title == cleaned_title.upper()
        or len(cleaned_title.split()) > 8
    )
    if not generic_title:
        return cleaned_title
    normalized_summary = _clean_excerpt(summary, max_chars=240).strip(" .;:-")
    match = re.search(
        r"(?:the contractor shall|contractor shall|shall)\s+(.+?)(?:[.;]|$)",
        normalized_summary,
        re.IGNORECASE,
    )
    candidate = match.group(1).strip(" .;:-") if match else normalized_summary.split(";", 1)[0].strip(" .;:-")
    candidate = re.sub(
        r"^(?:provide|perform|maintain|deliver|support|manage|review|prepare|execute|coordinate)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = _clean_excerpt(candidate, max_chars=96).strip(" .;:-")
    if not candidate:
        return cleaned_title or "Requirement workstream"
    return candidate[0].upper() + candidate[1:]


def _workstream_priority(title: str, objective: str) -> int:
    lower = f"{title} {objective}".lower()
    score = 0
    weighted_terms = (
        ("transition", 110),
        ("traceability", 106),
        ("iv&v", 104),
        ("test", 102),
        ("quality control", 100),
        ("quality assurance", 98),
        ("acceptance", 96),
        ("clearance", 94),
        ("zero trust", 92),
        ("ficam", 90),
        ("trm", 90),
        ("engineering", 88),
        ("deliverable", 86),
        ("review", 84),
        ("report", 82),
        ("staffing", 80),
        ("clin", 78),
        ("price", 76),
    )
    for token, weight in weighted_terms:
        if token in lower:
            score = max(score, weight)
    if any(token in lower for token in ("security", "compliance", "transition", "technical", "quality", "testing")):
        score += 15
    if re.search(r"\b\d{1,3}\b", lower) or re.search(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b", title):
        score += 6
    if re.search(r"\b(?:shall|must|provide|deliver|support|conduct|execute|review|coordinate|submit|develop|maintain)\b", lower):
        score += 8
    return score


def _section_backed_workstreams(attachment_bundle: dict[str, object], max_items: int = 8) -> list[dict[str, object]]:
    block_workstreams: list[dict[str, object]] = []
    seen_block_keys: set[str] = set()
    for block in _attachment_section_blocks(
        attachment_bundle,
        allowed_categories={"statement_of_work", "solicitation", "instructions_evaluation", "amendment"},
        max_items=18,
        include_filename=True,
    ):
        title = str(block.get("title", "") or "").strip()
        text = str(block.get("source_text", "") or block.get("text", "") or "").strip()
        combined_lower = f"{title} {text}".lower()
        if not text or any(hint in combined_lower for hint in WORKSTREAM_SECTION_SKIP_HINTS):
            continue
        if not any(hint in combined_lower for hint in WORKSTREAM_SECTION_HINTS) and not any(
            anchor in combined_lower for anchor in WORKSTREAM_SERVICE_LIST_ANCHORS
        ):
            continue
        summary = _compact_requirement_text(text, max_chars=420, max_fragments=3, require_action=False)
        key = _normalize_signal_text(f"{title} {summary}")
        if not key or key in seen_block_keys:
            continue
        seen_block_keys.add(key)
        block_workstreams.append(
            {
                "title": _workstream_display_title(title, summary),
                "objective": summary,
                "evidence_snippets": [str(block.get("text", "") or "").strip()],
                "_priority": _workstream_priority(title, summary),
            }
        )
    if block_workstreams:
        block_workstreams.sort(key=lambda item: int(item.get("_priority", 0)), reverse=True)
        trimmed: list[dict[str, object]] = []
        for item in block_workstreams[:max_items]:
            item.pop("_priority", None)
            trimmed.append(item)
        return trimmed

    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories={"statement_of_work", "solicitation", "instructions_evaluation", "amendment"},
        max_items=6,
    )
    workstreams: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for item in ordered:
        filename = str(item.get("filename", "attachment") or "attachment")
        raw_text = str(item.get("structured_text_excerpt") or item.get("text_excerpt") or "")
        if not raw_text.strip():
            continue
        lines = [line.strip() for line in raw_text.replace("\r", "\n").split("\n") if line.strip()]
        index = 0
        while index < len(lines):
            current = lines[index]
            if not _is_workstream_heading(current):
                index += 1
                continue
            title = _workstream_heading_title(current)
            lower_title = title.lower()
            index += 1
            section_lines: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if _is_workstream_heading(candidate):
                    break
                if not WORKSTREAM_PAGE_RE.match(candidate):
                    section_lines.append(candidate)
                index += 1
            if not section_lines or any(hint in lower_title for hint in WORKSTREAM_SECTION_SKIP_HINTS):
                continue
            summary = _workstream_summary(title, section_lines)
            combined_lower = f"{lower_title} {summary.lower()}".strip()
            if not summary:
                continue
            if not any(hint in combined_lower for hint in WORKSTREAM_SECTION_HINTS) and not any(
                anchor in combined_lower for anchor in WORKSTREAM_SERVICE_LIST_ANCHORS
            ):
                continue
            key = _normalize_signal_text(f"{title} {summary}")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            workstreams.append(
                {
                    "title": _workstream_display_title(title, summary),
                    "objective": summary,
                    "evidence_snippets": [f"{filename}: {title}: {summary}"],
                    "_priority": _workstream_priority(title, summary),
                }
            )
    workstreams.sort(key=lambda item: int(item.get("_priority", 0)), reverse=True)
    trimmed: list[dict[str, object]] = []
    for item in workstreams[:max_items]:
        item.pop("_priority", None)
        trimmed.append(item)
    return trimmed


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
    for block in _attachment_section_blocks(
        attachment_bundle,
        allowed_categories=prioritized_categories,
        max_items=max_snippets * 2,
        include_filename=True,
    ):
        text = str(block.get("text", "") or "").strip()
        if text:
            snippets.append(_clean_excerpt(text, max_chars=320))
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
    for block in _attachment_section_blocks(attachment_bundle, max_items=max_items * 2):
        source_text = _clean_excerpt(block.get("source_text", "") or "", max_chars=900)
        if source_text:
            texts.append(source_text)
    for item in ordered:
        text_excerpt = _attachment_text_value(item, max_chars=5000)
        if text_excerpt:
            texts.append(text_excerpt)
        for snippet in item.get("snippets", []) or []:
            cleaned = _clean_excerpt(snippet, max_chars=320)
            if cleaned:
                texts.append(cleaned)
    return _dedupe_strings(texts)


def _dense_attachment_text(
    attachment_bundle: dict[str, object],
    *,
    allowed_categories: set[str] | None = None,
    max_items: int = 6,
    max_chars_per_attachment: int = 24000,
) -> str:
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=allowed_categories,
        max_items=max_items,
    )
    values: list[str] = []
    for item in ordered:
        text = _attachment_text_value(item, max_chars=max_chars_per_attachment)
        if text:
            values.append(text)
    dense = SPACE_RE.sub(" ", " ".join(values)).strip()
    repairs = (
        (r"Firm-\s*Fixe\s*d\s+Price", "Firm-Fixed Price"),
        (r"Set\s*-\s*Aside", "Set-Aside"),
        (r"Per\s*forman\s*ce", "Performance"),
        (r"Ad\s*dendum", "Addendum"),
        (r"Wo\s*rk", "Work"),
        (r"Oasis\s*\+\s*SB", "OASIS+ SB"),
    )
    for pattern, replacement in repairs:
        dense = re.sub(pattern, replacement, dense, flags=re.IGNORECASE)
    return dense


def _fact_window_from_lines(lines: list[str], label_patterns: tuple[str, ...], *, max_follow_lines: int = 2) -> str:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in label_patterns]
    for index, line in enumerate(lines):
        cleaned = _repair_pdf_spacing(_clean_excerpt(line, max_chars=260))
        if not cleaned:
            continue
        for pattern in compiled:
            match = pattern.search(cleaned)
            if not match:
                continue
            values: list[str] = []
            if match.lastindex:
                values.extend(
                    str(match.group(group_index) or "").strip(" .;:-")
                    for group_index in range(1, match.lastindex + 1)
                    if str(match.group(group_index) or "").strip(" .;:-")
                )
            if not values and ":" in cleaned:
                tail = cleaned.split(":", 1)[1].strip(" .;:-")
                if tail:
                    values.append(tail)
            if not values:
                for next_line in lines[index + 1 : index + 1 + max_follow_lines]:
                    candidate = _repair_pdf_spacing(_clean_excerpt(next_line, max_chars=220)).strip(" .;:-")
                    if not candidate or SECTION_HEADING_RE.match(candidate):
                        break
                    values.append(candidate)
                    if len(" ".join(values)) >= 180:
                        break
            return _clean_excerpt(" ".join(value for value in values if value), max_chars=220).strip(" .;:-")
    return ""


def _looks_like_fact_value(field: str, value: str) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if field == "due_date":
        return bool(re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", cleaned, re.IGNORECASE))
    if field == "period_of_performance":
        return bool(re.search(r"\b(?:period of performance|base year|option year|month|months|day|days|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{1,2}/\d{1,2}/\d{2,4})\b", cleaned, re.IGNORECASE))
    if field == "transition_window":
        return bool(re.search(r"\b\d{1,3}\s*[- ]?day\b", cleaned, re.IGNORECASE))
    if field == "set_aside":
        return len(lower.split()) <= 12 and any(token in lower for token in ("small business", "sdvosb", "hubzone", "wosb", "8(a)", "full and open", "unrestricted", "set aside"))
    if field == "contract_vehicle":
        return len(lower.split()) <= 12 and any(token in lower for token in ("gwac", "schedule", "idiq", "stars", "sewp", "oasis", "alliant", "cio-sp", "polaris"))
    return True


SET_ASIDE_CLAUSE_NOISE = (
    "notice of hubzone set-aside",
    "notice of price evaluation preference for hubzone",
    "notice of total small business set-aside",
    "notice of partial small business set-aside",
    "notice of service-disabled veteran-owned small business set-aside",
    "notice of set-aside of orders",
    "notice of set-aside for",
    "post award small business program representation",
    "utilization of small business concerns",
    "limitations on subcontracting",
    "small business subcontracting plan",
)
EXPLICIT_VEHICLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b8\(a\)\s+stars\s+iii\b|\b8a\s+stars\s+iii\b", "8(a) STARS III GWAC"),
    (r"\b8\(a\)\s+stars\s+ii\b|\b8a\s+stars\s+ii\b", "8(a) STARS II GWAC"),
    (r"\bnasa\s+sewp\b|\bsewp\b", "NASA SEWP"),
    (r"\bcio-sp\b|\bcio sp\b", "CIO-SP"),
    (r"\boasis\b", "OASIS"),
    (r"\balliant\b", "Alliant"),
    (r"\bpolaris\b", "Polaris"),
)
EXPLICIT_SET_ASIDE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b100%\s+small\s+business\b", "100% Small Business"),
    (r"\b8\(a\)\s+program\b|\bcompetitive/8\(a\)\b", "8(a)"),
    (r"\bservice[- ]disabled veteran[- ]owned small business\b|\bsdvosb\b", "SDVOSB"),
    (r"\bhubzone\b", "HUBZone"),
    (r"\bwosb\b", "WOSB"),
    (r"\bfull\s+and\s+open\b|\bunrestricted\b", "Full and Open"),
)


def _is_set_aside_clause_noise(line: str) -> bool:
    lower = SPACE_RE.sub(" ", str(line or "").lower()).strip()
    if not lower:
        return False
    if re.search(r"\b(?:far|hudar)?\s*52\.219-\d+\b", lower):
        return True
    return any(marker in lower for marker in SET_ASIDE_CLAUSE_NOISE)


def _clean_set_aside_candidate(value: str) -> str:
    cleaned = _repair_pdf_spacing(_clean_excerpt(value, max_chars=120)).strip(" .;:-")
    lower = cleaned.lower()
    if not cleaned or _is_set_aside_clause_noise(cleaned):
        return ""
    cleaned = re.sub(
        r"\s+(?:other information|the government intends|this announcement constitutes|offerors?\s+must).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" .;:-")
    if "8(a) stars" in lower or "8a stars" in lower or "8(a) program" in lower or "competitive/8(a)" in lower:
        return "8(a)"
    return cleaned


def _explicit_acquisition_posture(lines: list[str]) -> dict[str, str]:
    posture: dict[str, str] = {}
    for raw_line in lines:
        line = _repair_pdf_spacing(_clean_excerpt(raw_line, max_chars=260)).strip()
        if not line:
            continue
        lower = line.lower()
        if not posture.get("contract_vehicle"):
            for pattern, label in EXPLICIT_VEHICLE_PATTERNS:
                if not re.search(pattern, lower, re.IGNORECASE):
                    continue
                if any(marker in lower for marker in ("acquisition strategy", "contract holder", "gwac", "schedule", "ebuy", "task order", "competitive/")):
                    posture["contract_vehicle"] = label
                    break
        if not posture.get("set_aside"):
            set_aside_match = re.search(r"type\s+of\s+set[- ]aside[:\s]+(.+)$", line, re.IGNORECASE)
            if set_aside_match:
                candidate = _clean_set_aside_candidate(set_aside_match.group(1))
                if candidate:
                    posture["set_aside"] = candidate
                    continue
            if _is_set_aside_clause_noise(line):
                continue
            if posture.get("contract_vehicle") == "8(a) STARS III GWAC" and any(marker in lower for marker in ("8(a)", "8a", "competitive/", "contract holder")):
                posture["set_aside"] = "8(a)"
                continue
            for pattern, label in EXPLICIT_SET_ASIDE_PATTERNS:
                if re.search(pattern, lower, re.IGNORECASE):
                    posture["set_aside"] = label
                    break
        if posture.get("contract_vehicle") and posture.get("set_aside"):
            break
    return posture


def _attachment_fact_candidates(raw_text: str) -> dict[str, str]:
    text = _repair_pdf_spacing(str(raw_text or ""))
    dense = SPACE_RE.sub(" ", text).strip()
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]
    facts: dict[str, str] = {}
    if not dense:
        return facts
    explicit_posture = _explicit_acquisition_posture(lines)
    if explicit_posture.get("set_aside"):
        facts["set_aside"] = explicit_posture["set_aside"]
    if explicit_posture.get("contract_vehicle"):
        facts["contract_vehicle"] = explicit_posture["contract_vehicle"]

    facts["due_date"] = _fact_window_from_lines(
        lines,
        (
            r"deadline\s+for\s+receipt\s+of\s+offers\s*:?\s*(.+)?",
            r"(?:quotes?|offers?|proposals?|responses?)\s+(?:are\s+)?due\s*:?\s*(.+)?",
            r"offer\s+due\s+date(?:/local\s*time)?\s*:?\s*(.+)?",
            r"closing\s+date\s*:?\s*(.+)?",
        ),
        max_follow_lines=2,
    )

    if re.search(r"\blowest\s+price\s+technically\s+acceptable\b|\bLPTA\b", dense, re.IGNORECASE):
        facts["evaluation_basis"] = "LPTA"
    else:
        evaluation_match = re.search(
            r"best\s+value(?:\s+to\s+the\s+government)?(?:,\s*considering\s+factors\s+to\s+include\s+([^\n.]{8,160}))?",
            dense,
            re.IGNORECASE,
        )
        if evaluation_match:
            factors = _clean_excerpt(evaluation_match.group(1) or "", max_chars=120).strip(" ,.;:")
            facts["evaluation_basis"] = f"Best Value ({factors})" if factors else "Best Value"

    contract_type_patterns = (
        (r"\bfirm[- ]fixed\s+price\b|\bFFP\b", "Firm Fixed Price"),
        (r"\btime\s+and\s+materials\b|\bT&M\b", "Time and Materials"),
        (r"\blabor[- ]hour\b", "Labor Hour"),
        (r"\bcost[- ]plus[- ]fixed[- ]fee\b|\bCPFF\b", "Cost Plus Fixed Fee"),
        (r"\bcost[- ]reimbursement\b", "Cost Reimbursement"),
    )
    for pattern, label in contract_type_patterns:
        if re.search(pattern, dense, re.IGNORECASE):
            facts["contract_type"] = label
            break

    if not facts.get("set_aside"):
        for line in lines:
            candidate = _clean_set_aside_candidate(line)
            if not candidate:
                continue
            for pattern, label in EXPLICIT_SET_ASIDE_PATTERNS:
                if re.search(pattern, candidate, re.IGNORECASE):
                    facts["set_aside"] = label
                    break
            if facts.get("set_aside"):
                break

    facts["period_of_performance"] = _fact_window_from_lines(
        lines,
        (
            r"period\s+of\s+performance\s*:?\s*(.+)?",
            r"base\s+period\s*:?\s*(.+)?",
            r"base\s+year\s*:?\s*(.+)?",
        ),
        max_follow_lines=3,
    )
    if not facts["period_of_performance"]:
        pop_patterns = (
            r"Base\s+Year:\s*([^\n]{6,90})\s+Option\s+Year\s+One:\s*([^\n]{6,90})\s+Option\s+Year\s+Two:\s*([^\n]{6,90})",
        )
        for pattern in pop_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            facts["period_of_performance"] = _clean_excerpt(
                f"Base year {match.group(1)}; Option Year 1 {match.group(2)}; Option Year 2 {match.group(3)}",
                max_chars=220,
            )
            break

    transition_patterns = (
        r"(\d{1,3})[- ]day\s+transition(?:-in)?",
        r"transition(?:-in)?\s+period\s+of\s+(\d{1,3})\s+days",
        r"phase[- ]in\s+period\s+of\s+(\d{1,3})\s+days",
    )
    for pattern in transition_patterns:
        match = re.search(pattern, dense, re.IGNORECASE)
        if match:
            facts["transition_window"] = f"{match.group(1)}-day transition"
            break

    if re.search(r"Funds\s+are\s+not\s+presently\s+available", dense, re.IGNORECASE):
        funds_match = re.search(
            r"(Funds\s+are\s+not\s+presently\s+available[^.]{0,220}\.)",
            dense,
            re.IGNORECASE,
        )
        facts["funds_status"] = _clean_excerpt((funds_match.group(1) if funds_match else "Funds are not presently available"), max_chars=220)
    for field in ("due_date", "period_of_performance", "transition_window", "set_aside", "contract_vehicle"):
        value = str(facts.get(field, "") or "").strip()
        if value and not _looks_like_fact_value(field, value):
            facts.pop(field, None)
    return facts


def _preferred_attachment_fact(
    rows: list[dict[str, object]],
    field: str,
) -> str:
    field_priority = {
        "due_date": {
            "amendment": 0,
            "solicitation": 1,
            "instructions_evaluation": 2,
            "statement_of_work": 3,
            "questions_answers": 4,
            "other": 5,
        },
        "set_aside": {
            "solicitation": 0,
            "amendment": 1,
            "instructions_evaluation": 2,
            "statement_of_work": 3,
            "questions_answers": 4,
            "other": 5,
        },
        "contract_vehicle": {
            "solicitation": 0,
            "amendment": 1,
            "instructions_evaluation": 2,
            "statement_of_work": 3,
            "questions_answers": 4,
            "other": 5,
        },
        "contract_type": ATTACHMENT_FACT_CATEGORY_PRIORITY,
        "evaluation_basis": {
            "instructions_evaluation": 0,
            "solicitation": 1,
            "amendment": 2,
            "statement_of_work": 3,
            "questions_answers": 4,
            "other": 5,
        },
        "period_of_performance": ATTACHMENT_FACT_SCOPE_PRIORITY,
        "transition_window": ATTACHMENT_FACT_SCOPE_PRIORITY,
        "funds_status": {
            "solicitation": 0,
            "amendment": 1,
            "statement_of_work": 2,
            "instructions_evaluation": 3,
            "questions_answers": 4,
            "other": 5,
        },
    }
    priority = field_priority.get(field, ATTACHMENT_FACT_CATEGORY_PRIORITY)
    candidates = [
        row
        for row in rows
        if isinstance(row, dict) and str(((row.get("facts") or {}).get(field) if isinstance(row.get("facts"), dict) else "") or "").strip()
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda row: priority.get(str(row.get("category", "other") or "other"), 9))
    return str(((candidates[0].get("facts") or {}).get(field) if isinstance(candidates[0].get("facts"), dict) else "") or "").strip()


STAFFING_ROLE_HINTS = (
    "manager",
    "engineer",
    "architect",
    "specialist",
    "analyst",
    "technician",
    "inspector",
    "administrator",
    "coordinator",
    "planner",
    "designer",
    "scientist",
    "officer",
    "lead",
    "director",
    "supervisor",
    "operator",
    "estimator",
    "scheduler",
    "drafter",
)


def _staffing_role_candidate(text: str) -> str:
    cleaned = _repair_pdf_spacing(_clean_excerpt(text, max_chars=120)).strip(" .;:-")
    lower = cleaned.lower()
    if not cleaned or len(lower.split()) > 8:
        return ""
    if any(marker in lower for marker in ("labor category", "key personnel", "base year", "option year", "hours", "optional", "total")):
        return ""
    if not any(hint in lower for hint in STAFFING_ROLE_HINTS):
        return ""
    return cleaned


def _attachment_staffing_roles(attachment_bundle: dict[str, object], max_items: int = 10) -> list[str]:
    roles: list[str] = []
    for item in _ordered_attachment_items(attachment_bundle, max_items=8):
        for row in (item.get("matrix_rows", []) or []):
            if not isinstance(row, dict):
                continue
            cells = row.get("cells", [])
            if not isinstance(cells, list):
                cells = []
            for candidate in cells[:3]:
                role = _staffing_role_candidate(str(candidate or ""))
                if role:
                    roles.append(role)
            label_role = _staffing_role_candidate(str(row.get("label") or ""))
            if label_role:
                roles.append(label_role)
        for block in (item.get("section_blocks", []) or []):
            if not isinstance(block, dict):
                continue
            source_text = str(block.get("source_text") or block.get("text") or "")
            for fragment in re.split(r"[.;]\s+|\n+", source_text):
                if not re.search(r"\b(?:provide|furnish|staff|position|key personnel|labor categor(?:y|ies))\b", fragment, re.IGNORECASE):
                    continue
                for match in re.finditer(
                    r"\b([A-Z][A-Za-z/&-]+(?:\s+[A-Z][A-Za-z/&-]+){0,4}\s+(?:"
                    + "|".join(re.escape(hint) for hint in STAFFING_ROLE_HINTS)
                    + r"))\b",
                    fragment,
                ):
                    role = _staffing_role_candidate(match.group(1))
                    if role:
                        roles.append(role)
    return _dedupe_strings(roles)[:max_items]


def _attachment_fact_matrix(attachment_bundle: dict[str, object]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for item in _ordered_attachment_items(
        attachment_bundle,
        allowed_categories={"statement_of_work", "solicitation", "instructions_evaluation", "questions_answers", "amendment"},
        max_items=10,
    ):
        raw_text = str(item.get("structured_text_excerpt") or item.get("text_excerpt") or "")
        if not raw_text.strip():
            continue
        facts = _attachment_fact_candidates(raw_text)
        if not facts:
            continue
        rows.append(
            {
                "filename": str(item.get("filename", "attachment") or "attachment"),
                "category": str(item.get("category", "other") or "other"),
                "facts": facts,
            }
        )

    conflicts: list[dict[str, object]] = []
    for field in ("due_date", "set_aside", "contract_vehicle", "contract_type", "evaluation_basis", "period_of_performance", "transition_window", "funds_status"):
        values: dict[str, dict[str, object]] = {}
        for row in rows:
            facts = row.get("facts", {})
            if not isinstance(facts, dict):
                continue
            value = str(facts.get(field, "") or "").strip()
            normalized = _normalize_signal_text(value)
            if not normalized:
                continue
            entry = values.setdefault(normalized, {"value": value, "sources": []})
            entry["sources"].append(f"{row.get('filename', 'attachment')} [{row.get('category', 'other')}]")
        if len(values) > 1:
            conflicts.append(
                {
                    "field": field.replace("_", " "),
                    "values": [str(entry.get("value", "") or "").strip() for entry in values.values()],
                    "sources": [source for entry in values.values() for source in (entry.get("sources", []) or [])],
                }
            )
    return {"rows": rows, "conflicts": conflicts}


def _attachment_parse_guardrails(attachment_bundle: dict[str, object]) -> dict[str, object]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    poor_parse_files: list[str] = []
    matrix_files: list[str] = []
    acceptance_files: list[str] = []
    pricing_files: list[str] = []
    review_required_files: list[str] = []
    pws_present = False
    parsed_scope_documents = 0

    for item in attachments:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename", "attachment") or "attachment")
        category = str(item.get("category", "other") or "other")
        parser_status = str(item.get("parser_status", "") or "")
        flags = {str(flag) for flag in (item.get("analysis_flags", []) or []) if str(flag).strip()}
        section_blocks = item.get("section_blocks", []) if isinstance(item.get("section_blocks"), list) else []
        if category == "statement_of_work":
            pws_present = True
        if (
            category in {"statement_of_work", "solicitation", "amendment"}
            and parser_status.startswith("parsed")
            and (int(item.get("text_char_count", 0) or 0) >= 1200 or bool(section_blocks))
        ):
            parsed_scope_documents += 1
        if bool(item.get("review_required")):
            review_required_files.append(filename)
        if flags & {"parse_failed_or_unsupported", "ocr_or_image_heavy_pdf", "thin_text_extraction", "scope_document_underparsed"}:
            poor_parse_files.append(filename)
        if flags & {"table_or_matrix_heavy", "clin_or_task_matrix_visible"}:
            matrix_files.append(filename)
        if flags & {"acceptance_or_aql_visible", "incentive_or_remedy_visible"}:
            acceptance_files.append(filename)
        if "pricing_sheet_or_rate_table" in flags:
            pricing_files.append(filename)

    warnings: list[str] = []
    if pws_present and parsed_scope_documents == 0:
        warnings.append("A PWS exists in the package, but no scope attachment parsed with enough usable text to trust the downstream objective or win-theme output.")
    if poor_parse_files:
        warnings.append(f"Some attachments parsed thinly or not at all and need OCR/manual review: {', '.join(_dedupe_strings(poor_parse_files)[:4])}.")
    if matrix_files:
        warnings.append(f"CLIN, task-matrix, or table-heavy sections were detected and may require structured extraction: {', '.join(_dedupe_strings(matrix_files)[:4])}.")
    if acceptance_files:
        warnings.append(f"Acceptance / AQL / incentive-remedy content was detected and should be reviewed explicitly: {', '.join(_dedupe_strings(acceptance_files)[:4])}.")
    if pricing_files:
        warnings.append(f"Pricing sheet or spreadsheet content was detected and should be validated separately from narrative extraction: {', '.join(_dedupe_strings(pricing_files)[:4])}.")
    return {
        "pws_present": pws_present,
        "parsed_scope_documents": parsed_scope_documents,
        "poor_parse_files": _dedupe_strings(poor_parse_files),
        "matrix_files": _dedupe_strings(matrix_files),
        "acceptance_files": _dedupe_strings(acceptance_files),
        "pricing_files": _dedupe_strings(pricing_files),
        "review_required_files": _dedupe_strings(review_required_files),
        "warnings": _dedupe_strings(warnings),
    }


def _repair_pdf_spacing(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", text)
    text = re.sub(r"\b(\d{3})\s+(\d)\b", r"\1\2", text)
    text = re.sub(r"Per\s*forman\s*ce", "Performance", text, flags=re.IGNORECASE)
    text = re.sub(r"Ad\s*dendum", "Addendum", text, flags=re.IGNORECASE)
    text = re.sub(r"Wo\s*rk", "Work", text, flags=re.IGNORECASE)
    text = re.sub(r"a\s+nd", "and", text, flags=re.IGNORECASE)
    text = re.sub(r"Attachmen\s+t", "Attachment", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _attachment_context_matches(
    attachment_bundle: dict[str, object],
    patterns: list[str],
    *,
    allowed_categories: set[str] | None = None,
    max_items: int = 4,
    line_radius: int = 2,
) -> list[str]:
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=allowed_categories,
        max_items=6,
    )
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    snippets: list[str] = []
    for item in ordered:
        filename = str(item.get("filename", "attachment") or "attachment")
        raw_text = str(item.get("structured_text_excerpt") or item.get("text_excerpt") or "")
        if not raw_text.strip():
            continue
        lines = [_clean_excerpt(line, max_chars=260) for line in raw_text.replace("\r", "\n").split("\n") if line.strip()]
        for index, line in enumerate(lines):
            if _is_toc_like_objective_line(line):
                continue
            if not any(pattern.search(line) for pattern in compiled):
                continue
            chunk: list[str] = []
            for candidate in lines[max(0, index - line_radius): min(len(lines), index + line_radius + 1)]:
                if _is_toc_like_objective_line(candidate):
                    continue
                chunk.append(candidate)
            snippet = SPACE_RE.sub(" ", " ".join(chunk)).strip()
            if len(snippet) < 50:
                continue
            snippets.append(f"{filename}: {snippet[:420]}")
            if len(snippets) >= max_items:
                return _dedupe_strings(snippets)[:max_items]
    return _dedupe_strings(snippets)[:max_items]


def _extract_solicitation_facts(
    attachment_bundle: dict[str, object],
    resolved: dict[str, object],
) -> dict[str, object]:
    dense = _dense_attachment_text(attachment_bundle, max_items=6)
    statement_dense = _dense_attachment_text(
        attachment_bundle,
        allowed_categories={"statement_of_work", "solicitation", "amendment", "instructions_evaluation"},
        max_items=6,
    )
    facts: dict[str, object] = {
        "notice_id": str(resolved.get("notice_id", "") or "").strip(),
        "solicitation_number": str(resolved.get("solicitation_number", "") or "").strip(),
        "issue_date": "",
        "naics": "",
        "naics_title": "",
        "naics_size_standard": "",
        "set_aside": "",
        "contract_vehicle": "",
        "contract_type": "",
        "evaluation_basis": "",
        "due_date": "",
        "funds_status": "",
        "period_of_performance": "",
        "transition_window": "",
        "base_period": "",
        "option_periods": [],
        "staffing_roles": [],
        "attachment_fact_rows": [],
        "attachment_conflicts": [],
        "quoted_facts": [],
    }
    if not dense:
        return facts
    fact_matrix = _attachment_fact_matrix(attachment_bundle)
    fact_rows = fact_matrix.get("rows", []) if isinstance(fact_matrix, dict) else []
    attachment_conflicts = fact_matrix.get("conflicts", []) if isinstance(fact_matrix, dict) else []
    if not isinstance(fact_rows, list):
        fact_rows = []
    if not isinstance(attachment_conflicts, list):
        attachment_conflicts = []

    naics_match = re.search(
        r"NAICS:\s*(\d{6})\s*[–-]?\s*(.+?)\s+SB\s+Size\s+Standard:",
        dense,
        re.IGNORECASE,
    )
    if naics_match:
        facts["naics"] = naics_match.group(1).strip()
        facts["naics_title"] = _repair_pdf_spacing(_clean_excerpt(naics_match.group(2), max_chars=80))
    size_match = re.search(r"(?:SB\s+)?Size\s+Standard:\s*\$?\s*([0-9,]+(?:\.\d+)?)", dense, re.IGNORECASE)
    if size_match:
        facts["naics_size_standard"] = f"${size_match.group(1).strip()}"
    set_aside_match = re.search(
        r"Type\s+of\s+Set[- ]Aside:\s*(.+?)\s+(?:OTHER INFORMATION|The Government intends|This announcement constitutes)",
        dense,
        re.IGNORECASE,
    )
    if set_aside_match:
        facts["set_aside"] = _repair_pdf_spacing(_clean_excerpt(set_aside_match.group(1), max_chars=90))
    vehicle_match = re.search(
        r"(?:place|issue)\s+a\s+(Firm[- ]Fixed\s+Price\s*\(FFP\)|FFP)\s+order\s+under\s+the\s+(.+?)\s+program",
        dense,
        re.IGNORECASE,
    )
    if vehicle_match:
        facts["contract_type"] = "Firm Fixed Price"
        facts["contract_vehicle"] = _repair_pdf_spacing(_clean_excerpt(vehicle_match.group(2), max_chars=60))
    else:
        explicit_vehicle_match = re.search(
            r"(?:utilizing|under)\s+the\s+(?:Federal Acquisition Regulation\s*\(FAR\)\s*\d+,\s*)?(.+?)(?:Governmentwide Acquisition Contract|\bGWAC\b|contract holder)",
            dense,
            re.IGNORECASE,
        )
        if explicit_vehicle_match:
            vehicle_value = _repair_pdf_spacing(_clean_excerpt(explicit_vehicle_match.group(1), max_chars=80)).strip(" ,.;:")
            if vehicle_value:
                vehicle_lower = vehicle_value.lower()
                if "stars iii" in vehicle_lower or "8(a) stars iii" in vehicle_lower:
                    facts["contract_vehicle"] = "8(a) STARS III GWAC"
                else:
                    facts["contract_vehicle"] = vehicle_value
    if not facts.get("contract_type") and re.search(r"\bFFP\b|Firm[- ]Fixed\s+Price", dense, re.IGNORECASE):
        facts["contract_type"] = "Firm Fixed Price"
    issue_date_match = re.search(r"\bDATE:\s*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})", dense, re.IGNORECASE)
    if issue_date_match:
        facts["issue_date"] = _repair_pdf_spacing(_clean_excerpt(issue_date_match.group(1), max_chars=40))
    due_date_match = re.search(
        r"Deadline\s+for\s+receipt\s+of\s+offers:\s*(?:NLT\s*)?(.+?)\s+All\s+quotes\s+shall\s+be\s+emailed",
        dense,
        re.IGNORECASE,
    )
    if due_date_match:
        facts["due_date"] = _repair_pdf_spacing(_clean_excerpt(due_date_match.group(1), max_chars=90))
    evaluation_match = re.search(
        r"based\s+solely\s+on\s+the\s+best\s+value\s+to\s+the\s+Government,\s+considering\s+factors\s+to\s+include\s+(.+?)(?:\.|Offerors must)",
        dense,
        re.IGNORECASE,
    )
    if evaluation_match:
        factors = _repair_pdf_spacing(_clean_excerpt(evaluation_match.group(1), max_chars=90).rstrip(","))
        facts["evaluation_basis"] = f"Best Value ({factors})"
    elif re.search(r"\bprice,\s*technical,\s*and\s+past\s+performance\b", dense, re.IGNORECASE):
        facts["evaluation_basis"] = "Best Value (price, technical, and past performance)"
    elif re.search(r"\bbest\s+value\b", dense, re.IGNORECASE):
        facts["evaluation_basis"] = "Best Value"
    funds_match = re.search(
        r"Funds\s+are\s+not\s+presently\s+available.+?(?:until\s+funds\s+are\s+available\.)",
        dense,
        re.IGNORECASE,
    )
    if funds_match:
        facts["funds_status"] = _repair_pdf_spacing(_clean_excerpt(funds_match.group(0), max_chars=180))
    pop_match = re.search(
        r"Base\s+Year:\s*(.+?)\s+Option\s+Year\s+One:\s*(.+?)\s+Option\s+Year\s+Two:\s*(.+?)\s+This\s+performance\s+period",
        dense,
        re.IGNORECASE,
    )
    if pop_match:
        base_period = _repair_pdf_spacing(_clean_excerpt(pop_match.group(1), max_chars=60))
        option_one = _repair_pdf_spacing(_clean_excerpt(pop_match.group(2), max_chars=60))
        option_two = _repair_pdf_spacing(_clean_excerpt(pop_match.group(3), max_chars=60))
        facts["base_period"] = base_period
        facts["option_periods"] = [option_one, option_two]
        facts["period_of_performance"] = (
            f"Base year {base_period}; Option Year 1 {option_one}; Option Year 2 {option_two}"
        )
    elif re.search(r"one\s+base\s+year\s+of\s+12\s+months\s+and\s+two\s*\(2\)\s+option\s+years", statement_dense, re.IGNORECASE):
        facts["period_of_performance"] = "One 12-month base year plus two 12-month option years."

    if str(facts.get("contract_vehicle") or "").strip() and not _looks_like_fact_value("contract_vehicle", str(facts.get("contract_vehicle") or "")):
        facts["contract_vehicle"] = ""
    if not facts["due_date"]:
        facts["due_date"] = _preferred_attachment_fact(fact_rows, "due_date")
    if not facts["set_aside"]:
        facts["set_aside"] = _preferred_attachment_fact(fact_rows, "set_aside")
    if not facts["contract_vehicle"]:
        facts["contract_vehicle"] = _preferred_attachment_fact(fact_rows, "contract_vehicle")
    if str(facts.get("contract_vehicle") or "").strip() and not _looks_like_fact_value("contract_vehicle", str(facts.get("contract_vehicle") or "")):
        facts["contract_vehicle"] = ""
    if not facts["contract_type"]:
        facts["contract_type"] = _preferred_attachment_fact(fact_rows, "contract_type")
    if not facts["evaluation_basis"]:
        facts["evaluation_basis"] = _preferred_attachment_fact(fact_rows, "evaluation_basis")
    if not facts["period_of_performance"]:
        facts["period_of_performance"] = _preferred_attachment_fact(fact_rows, "period_of_performance")
    facts["transition_window"] = _preferred_attachment_fact(fact_rows, "transition_window")
    if not facts["funds_status"]:
        facts["funds_status"] = _preferred_attachment_fact(fact_rows, "funds_status")

    facts["staffing_roles"] = _attachment_staffing_roles(attachment_bundle)
    facts["attachment_fact_rows"] = fact_rows
    facts["attachment_conflicts"] = attachment_conflicts
    facts["quoted_facts"] = _dedupe_strings(
        [
            *([f"Issue date: {facts['issue_date']}"] if facts["issue_date"] else []),
            *([f"NAICS {facts['naics']} - {facts['naics_title']}"] if facts["naics"] else []),
            *([f"Size standard: {facts['naics_size_standard']}"] if facts["naics_size_standard"] else []),
            *([f"Set-aside: {facts['set_aside']}"] if facts["set_aside"] else []),
            *([f"Vehicle: {facts['contract_vehicle']}"] if facts["contract_vehicle"] else []),
            *([f"Contract type: {facts['contract_type']}"] if facts["contract_type"] else []),
            *([f"Due date: {facts['due_date']}"] if facts["due_date"] else []),
            *([f"Evaluation basis: {facts['evaluation_basis']}"] if facts["evaluation_basis"] else []),
            *([f"Funds status: {facts['funds_status']}"] if facts["funds_status"] else []),
            *([f"Period of performance: {facts['period_of_performance']}"] if facts["period_of_performance"] else []),
            *([f"Transition window: {facts['transition_window']}"] if facts["transition_window"] else []),
        ]
    )
    return facts


def _parse_named_date(value: str) -> datetime | None:
    cleaned = SPACE_RE.sub(" ", str(value or "").replace("–", "-")).strip(" .,;")
    if not cleaned:
        return None
    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})(?:,\s*([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?))?",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None
    date_part = match.group(1).strip()
    parsed: datetime | None = None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(date_part, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    time_part = (match.group(2) or "").strip()
    if not time_part:
        return parsed
    normalized_time = time_part.lower().replace(".", "").upper()
    try:
        parsed_time = datetime.strptime(normalized_time, "%I:%M %p")
    except ValueError:
        return parsed
    return parsed.replace(hour=parsed_time.hour, minute=parsed_time.minute)


def _parse_period_window(value: str) -> tuple[datetime | None, datetime | None]:
    cleaned = SPACE_RE.sub(" ", str(value or "").replace("–", "-")).strip(" .,;")
    if not cleaned:
        return None, None
    match = re.search(
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return _parse_named_date(match.group(1)), _parse_named_date(match.group(2))


def _timeline_display(dt: datetime, *, include_time: bool = False) -> str:
    date_text = dt.strftime("%d %b %Y")
    if not include_time or (dt.hour == 0 and dt.minute == 0):
        return date_text
    hour = dt.strftime("%I").lstrip("0") or "0"
    return f"{date_text}, {hour}{dt.strftime(':%M %p')}"


def _build_procurement_timeline(
    solicitation_facts: dict[str, object],
    generated_at: str,
) -> dict[str, object]:
    milestones: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add_milestone(
        label: str,
        dt: datetime | None,
        *,
        kind: str,
        detail: str = "",
        display_date: str = "",
    ) -> None:
        if dt is None:
            return
        date_iso = dt.isoformat(timespec="minutes")
        key = (label, date_iso)
        if key in seen:
            return
        seen.add(key)
        milestones.append(
            {
                "label": label,
                "date_iso": date_iso,
                "display_date": display_date or _timeline_display(dt, include_time=(dt.hour != 0 or dt.minute != 0)),
                "kind": kind,
                "detail": detail,
            }
        )

    capture_run_dt: datetime | None = None
    if generated_at:
        try:
            capture_run_dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=None,
            )
        except ValueError:
            capture_run_dt = None
    add_milestone("Capture run generated", capture_run_dt, kind="capture", detail="Current memo artifact created.")

    issue_date_text = str(solicitation_facts.get("issue_date", "") or "").strip()
    issue_date_dt = _parse_named_date(issue_date_text)
    add_milestone("Solicitation issued", issue_date_dt, kind="issue", detail="Issue date extracted from parsed attachment text.", display_date=issue_date_text)

    due_date_text = str(solicitation_facts.get("due_date", "") or "").strip()
    due_date_dt = _parse_named_date(due_date_text)
    add_milestone("Proposal due", due_date_dt, kind="due", detail="Current offer submission deadline.", display_date=due_date_text)

    base_period = str(solicitation_facts.get("base_period", "") or "").strip()
    base_start, base_end = _parse_period_window(base_period)
    add_milestone("Base year starts", base_start, kind="base_start", detail="Start of the base performance period.", display_date=_timeline_display(base_start) if base_start else "")
    add_milestone("Base year ends", base_end, kind="base_end", detail="End of the base performance period.", display_date=_timeline_display(base_end) if base_end else "")

    option_periods = solicitation_facts.get("option_periods", [])
    if not isinstance(option_periods, list):
        option_periods = []
    for index, option_period in enumerate(option_periods, start=1):
        option_start, option_end = _parse_period_window(str(option_period or ""))
        add_milestone(
            f"Option Year {index} starts",
            option_start,
            kind="option_start",
            detail=f"Start of Option Year {index}.",
            display_date=_timeline_display(option_start) if option_start else "",
        )
        add_milestone(
            f"Option Year {index} ends",
            option_end,
            kind="option_end",
            detail=f"End of Option Year {index}.",
            display_date=_timeline_display(option_end) if option_end else "",
        )

    milestones.sort(key=lambda item: str(item.get("date_iso", "")))
    notes: list[str] = []
    if solicitation_facts.get("funds_status"):
        notes.append(str(solicitation_facts.get("funds_status")))
    if not issue_date_dt:
        notes.append("Solicitation issue date was not parsed from current artifacts.")
    if due_date_text and not due_date_dt:
        notes.append("A due-date string was detected, but it could not be normalized into a chartable date.")

    return {
        "milestones": milestones,
        "notes": _dedupe_strings(notes),
        "chart_ready": len(milestones) >= 2,
    }


def _extract_attachment_workstreams(attachment_bundle: dict[str, object]) -> list[dict[str, object]]:
    scope_categories = {"statement_of_work", "solicitation", "amendment", "instructions_evaluation"}
    section_workstreams = _section_backed_workstreams(attachment_bundle, max_items=10)
    if section_workstreams:
        return section_workstreams
    workstreams: list[dict[str, object]] = []
    candidates = [
        {
            "title": "On-site execution and delivery continuity",
            "patterns": [
                r"engineering design support",
                r"project management",
                r"on-site.+technical and administrative services",
                r"\bon[- ]site\b",
                r"day[- ]to[- ]day support",
            ],
            "objective": "Provide the on-site or field-facing execution support described in the package, including day-to-day coordination, delivery continuity, and direct support to the primary requirement workstream.",
        },
        {
            "title": "Acquisition-package and planning deliverables",
            "patterns": [
                r"DD\s*1391",
                r"Statement of Objectives",
                r"Statements? of Work",
                r"Performance Work Statements?",
                r"acquisition packages",
                r"cost estimates",
                r"programming documents",
            ],
            "objective": "Develop and maintain the planning, scope, and package artifacts needed to move the requirement through customer review and execution without avoidable rework.",
        },
        {
            "title": "Project controls, reporting, and quality management",
            "patterns": [
                r"Project Status Report",
                r"\bPSR\b",
                r"Presentation Materials",
                r"QA/QC",
                r"quality assurance",
                r"quality control",
            ],
            "objective": "Maintain disciplined reporting, review, and QA/QC controls so customer status, issues, and corrective actions stay visible throughout execution.",
        },
        {
            "title": "Visible staffing mix and coverage plan",
            "patterns": [
                r"labor categor(?:y|ies)",
                r"staffing plan",
                r"key personnel",
                r"engineering technicians",
                r"engineers?\s*/\s*architects?",
                r"Construction Manager",
                r"on-site personnel",
            ],
            "objective": "Staff the visible labor mix credibly across the surfaced roles, coverage periods, and on-site or customer-facing execution expectations.",
        },
        {
            "title": "Access, security, and information-handling controls",
            "patterns": [
                r"site access",
                r"visitor control",
                r"CONFIDENTIAL clearance",
                r"credential",
                r"badg",
                r"background (?:check|investigation)",
                r"NDA",
                r"FOUO",
                r"escort visitors",
            ],
            "objective": "Meet the surfaced access, credentialing, clearance, and information-handling controls early enough that execution does not stall during mobilization.",
        },
    ]
    for candidate in candidates:
        evidence_snippets = _attachment_context_matches(
            attachment_bundle,
            candidate["patterns"],
            allowed_categories=scope_categories,
            max_items=3,
            line_radius=2,
        )
        if not evidence_snippets:
            continue
        workstreams.append(
            {
                "title": candidate["title"],
                "objective": candidate["objective"],
                "evidence_snippets": evidence_snippets,
            }
        )
    return workstreams


def _extract_staffing_pricing_signals(
    attachment_bundle: dict[str, object],
    solicitation_facts: dict[str, object],
    attachment_workstreams: list[dict[str, object]],
) -> dict[str, list[str]]:
    guardrails = _attachment_parse_guardrails(attachment_bundle)
    staffing_notes = _dedupe_strings(
        [
            *(
                [f"Visible staffing mix: {', '.join(solicitation_facts.get('staffing_roles', []))}."]
                if solicitation_facts.get("staffing_roles")
                else []
            ),
            *(
                ["On-site execution appears mandatory for the visible labor mix, not a remote-support construct."]
                if any("on-site" in " ".join(item.get("evidence_snippets", [])).lower() for item in attachment_workstreams)
                else []
            ),
            *(
                ["Access or onboarding appears non-trivial because the package includes multiple credentialing, clearance, or entry-control steps that could slow startup."]
                if _attachment_context_matches(
                    attachment_bundle,
                    [r"site access", r"visitor control", r"credential", r"badg", r"background (?:check|investigation)", r"CONFIDENTIAL clearance", r"escort visitors"],
                    max_items=1,
                )
                else []
            ),
            *(
                ["Scope-boundary planning matters because the work includes acquisition-package support while the PWS also requires NDA and proprietary-information handling."]
                if _attachment_context_matches(attachment_bundle, [r"DD\s*1391", r"proprietary", r"Non-Disclosure Agreement|NDA"], max_items=1)
                else []
            ),
            *(
                [f"Scope attachments need manual OCR or table review before staffing assumptions are treated as complete: {', '.join(guardrails.get('poor_parse_files', [])[:3])}."]
                if guardrails.get("poor_parse_files")
                else []
            ),
        ]
    )
    pricing_notes = _dedupe_strings(
        [
            *(
                [f"Contract posture is {solicitation_facts.get('contract_type')} under {solicitation_facts.get('contract_vehicle')}."]
                if solicitation_facts.get("contract_type") and solicitation_facts.get("contract_vehicle")
                else []
            ),
            *(
                ["Price has to carry the visible labor mix and execution posture across the surfaced performance periods; do not assume the staffing plan can be thinned without affecting delivery credibility."]
                if solicitation_facts.get("staffing_roles") and solicitation_facts.get("period_of_performance")
                else []
            ),
            *(
                ["The instructions addendum references price realism and unbalanced pricing, so low-drama FFP pricing matters more than a thin rate card."]
                if _attachment_context_matches(attachment_bundle, [r"price realism", r"unbalanced pricing"], allowed_categories={"instructions_evaluation"}, max_items=1)
                else []
            ),
            *(
                [f"Pricing sheet or spreadsheet content is present and should be validated directly for CLIN math, labor-rate posture, and total-evaluated-price logic: {', '.join(guardrails.get('pricing_files', [])[:3])}."]
                if guardrails.get("pricing_files")
                else []
            ),
        ]
    )
    evaluation_notes = _dedupe_strings(
        [
            *(
                [f"Evaluation basis surfaced in the solicitation package: {solicitation_facts.get('evaluation_basis')}."]
                if solicitation_facts.get("evaluation_basis")
                else []
            ),
            *(
                ["The package expects the technical narrative to map back to PWS sections and key roles."]
                if _attachment_context_matches(attachment_bundle, [r"Proposal paragraphs shall correspond to the pertinent Performance Work Statement", r"key roles defined in the PWS"], allowed_categories={"instructions_evaluation"}, max_items=1)
                else []
            ),
            *(
                [f"Acceptance / AQL / incentive-remedy tables are visible and should be reflected explicitly in the solution and risk story: {', '.join(guardrails.get('acceptance_files', [])[:3])}."]
                if guardrails.get("acceptance_files")
                else []
            ),
        ]
    )
    return {
        "staffing_notes": staffing_notes,
        "pricing_notes": pricing_notes,
        "evaluation_notes": evaluation_notes,
    }


def _extract_attachment_anomalies(
    attachment_bundle: dict[str, object],
    solicitation_facts: dict[str, object],
) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    guardrails = _attachment_parse_guardrails(attachment_bundle)
    dense = _dense_attachment_text(attachment_bundle, max_items=6)
    declaration_lines: list[str] = []
    for item in _ordered_attachment_items(attachment_bundle, allowed_categories={"amendment", "solicitation"}, max_items=4):
        raw_text = str(item.get("structured_text_excerpt") or item.get("text_excerpt") or "")
        if not raw_text.strip():
            continue
        declaration_lines.extend([line.strip() for line in raw_text.replace("\r", "\n").split("\n") if line.strip()])
    declared_attachments: list[tuple[str, str]] = []
    declared_count_match = None
    for line in declaration_lines:
        if declared_count_match is None:
            declared_count_match = re.search(r"Attachments\s*\((\d+)\)", line, re.IGNORECASE)
        match = re.match(r"Attachment\s+(\d+)\s*[-–]\s*(.+)$", _repair_pdf_spacing(line), re.IGNORECASE)
        if not match:
            continue
        declared_attachments.append((match.group(1).strip(), _repair_pdf_spacing(match.group(2)).rstrip(".")))
    provided_text = " ".join(
        [
            str(item.get("filename", "") or "")
            for item in (attachment_bundle.get("attachments", []) or [])
            if isinstance(item, dict)
        ]
    ).lower()
    if declared_count_match and declared_attachments:
        declared_total = int(declared_count_match.group(1))
        actual_total = len({number for number, _ in declared_attachments})
        if declared_total != actual_total:
            anomalies.append(
                {
                    "signal": "Attachment-count mismatch in the solicitation package",
                    "why_it_matters": f"The amendment says Attachments ({declared_total}) but the package enumerates {actual_total} attachment slots, which can hide missing required files.",
                    "effect": "Hurts us until the final attachment set is reconciled.",
                    "confidence": "High",
                    "source": "Parsed amendment attachment list",
                }
            )
    missing_declared = [
        f"Attachment {number} - {title}"
        for number, title in declared_attachments
        if _normalize_signal_text(title)
        and _normalize_signal_text(title) not in _normalize_signal_text(provided_text)
        and not (
            "performance work statement" in _normalize_signal_text(title)
            and "performance_work_statement" in provided_text
        )
    ]
    if missing_declared:
        anomalies.append(
            {
                "signal": "Declared attachments are missing from the local capture package",
                "why_it_matters": f"The current local run does not include all declared attachment artifacts: {', '.join(missing_declared[:4])}.",
                "effect": "Hurts us because evaluation, wage, PPQ, or Q&A detail may be missing.",
                "confidence": "High",
                "source": "Declared attachment inventory versus provided local files",
            }
        )
    if guardrails.get("poor_parse_files"):
        anomalies.append(
            {
                "signal": "Attachment parsing is thin for one or more scope-critical files",
                "why_it_matters": f"Some attachments parsed poorly enough that objective extraction and win-theme reasoning can drift: {', '.join(guardrails.get('poor_parse_files', [])[:4])}.",
                "effect": "Hurts us until OCR or manual review closes the gap.",
                "confidence": "High",
                "source": "Attachment parse-health analysis",
            }
        )
    if guardrails.get("matrix_files"):
        anomalies.append(
            {
                "signal": "CLIN or matrix-heavy sections require structured review",
                "why_it_matters": f"Table-heavy sections were detected in {', '.join(guardrails.get('matrix_files', [])[:4])}, so task structure, CLIN logic, or performance matrices may be under-extracted from plain text alone.",
                "effect": "Neutral if handled early; hurts us if ignored.",
                "confidence": "High",
                "source": "Attachment parse-health analysis",
            }
        )
    if guardrails.get("acceptance_files"):
        anomalies.append(
            {
                "signal": "Acceptance, AQL, or incentive-remedy content detected",
                "why_it_matters": f"The package contains acceptance or remedy logic in {', '.join(guardrails.get('acceptance_files', [])[:4])}; that can change staffing, quality, reporting, and downside-risk posture.",
                "effect": "Hurts us if the response ignores performance thresholds or remedies.",
                "confidence": "High",
                "source": "Attachment parse-health analysis",
            }
        )
    if guardrails.get("pricing_files"):
        anomalies.append(
            {
                "signal": "Pricing sheet or spreadsheet requires direct validation",
                "why_it_matters": f"Pricing-heavy attachments were detected in {', '.join(guardrails.get('pricing_files', [])[:4])}, so CLIN math, labor-rate posture, and evaluated-price assumptions should not rely on narrative extraction alone.",
                "effect": "Neutral to helpful if validated; hurts us if ignored.",
                "confidence": "High",
                "source": "Attachment parse-health analysis",
            }
        )
    for conflict in solicitation_facts.get("attachment_conflicts", []) if isinstance(solicitation_facts, dict) else []:
        if not isinstance(conflict, dict):
            continue
        field = str(conflict.get("field", "solicitation fact") or "solicitation fact").strip()
        values = [str(value or "").strip() for value in (conflict.get("values", []) or []) if str(value or "").strip()]
        sources = [str(value or "").strip() for value in (conflict.get("sources", []) or []) if str(value or "").strip()]
        if len(values) < 2:
            continue
        anomalies.append(
            {
                "signal": f"Cross-document conflict on {field}",
                "why_it_matters": f"Different attachments disagree on {field}: {', '.join(values[:3])}.",
                "effect": "Hurts us until the controlling document is confirmed.",
                "confidence": "High",
                "source": "; ".join(sources[:4]) or "Parsed attachment fact matrix",
            }
        )
    if re.search(r"technical quote volume shall not exceed ten pages", dense, re.IGNORECASE) and re.search(
        r"Factor 2\s*-\s*Technical.+?Limited to no more than 15 pages",
        dense,
        re.IGNORECASE,
    ):
        anomalies.append(
            {
                "signal": "Technical page-limit conflict",
                "why_it_matters": "One instruction says the technical quote volume shall not exceed ten pages, while another technical section says it is limited to 15 pages.",
                "effect": "Hurts us until the CO clarifies the controlling page limit.",
                "confidence": "High",
                "source": "Parsed instructions to offerors addendum",
            }
        )
    for match in re.finditer(r"DATE:\s*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})", dense, re.IGNORECASE):
        candidate = match.group(1).strip()
        try:
            datetime.strptime(candidate, "%d %b %Y")
        except ValueError:
            try:
                datetime.strptime(candidate, "%d %B %Y")
            except ValueError:
                anomalies.append(
                    {
                        "signal": f"Invalid solicitation date surfaced: {candidate}",
                        "why_it_matters": "Impossible or mistyped dates create document-control uncertainty and should be resolved before the proposal team relies on revision ordering.",
                        "effect": "Neutral operationally, but it is a capture integrity flag.",
                        "confidence": "High",
                        "source": "Parsed solicitation/PWS header text",
                    }
                )
                break
    if solicitation_facts.get("funds_status"):
        anomalies.append(
            {
                "signal": "Funds not presently available notice",
                "why_it_matters": "The package explicitly says funds are not presently available, which increases award-timing and option-exercise uncertainty even if the requirement remains valid.",
                "effect": "Hurts us on timing confidence.",
                "confidence": "High",
                "source": "Parsed solicitation funding notice",
            }
        )
    return anomalies


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
    blocks: list[str] = []
    action_terms = set(OBJECTIVE_KEYWORDS) | set(OBJECTIVE_EXTRA_ACTION_VERBS)
    for block in _attachment_section_blocks(
        attachment_bundle,
        allowed_categories={"statement_of_work", "solicitation", "amendment", "instructions_evaluation"},
        max_items=max_items * 3,
        include_filename=include_filename,
    ):
        heading = str(block.get("title", "") or "").strip()
        source_text = str(block.get("source_text", "") or block.get("text", "") or "").strip()
        if not source_text:
            continue
        heading_kind = _objective_heading_kind(heading or source_text)
        if heading_kind == "demoted":
            continue
        if heading_kind != "preferred" and not any(
            marker in _objective_heading_title(heading or source_text)
            for marker in ("task", "service", "support", "performance", "requirement", "deliverable", "objective", "scope")
        ):
            continue
        sentence_parts = [
            part.strip(" -;:")
            for part in re.split(r"(?<=[.!?;])\s+|(?<=\))\s+(?=[A-Z])", source_text)
            if part.strip()
        ]
        if not sentence_parts:
            sentence_parts = [source_text]
        for part in sentence_parts:
            compact_part = _compact_requirement_text(part, max_chars=360, max_fragments=2, require_action=True)
            lower = compact_part.lower()
            if len(compact_part) < 70 or len(compact_part) > 360:
                continue
            if _is_boilerplate_objective_sentence(compact_part):
                continue
            if not any(term in lower for term in action_terms):
                continue
            snippet = f"{heading}; {compact_part}" if heading and heading.lower() not in compact_part.lower() else compact_part
            if include_filename:
                snippet = f"{block.get('filename', 'attachment')}: {snippet}"
            blocks.append(snippet[:640])
            if len(blocks) >= max_items:
                return _dedupe_strings(blocks)[:max_items]

    scope_categories = {"statement_of_work", "solicitation", "amendment"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=scope_categories,
        max_items=6,
    )
    if not ordered:
        ordered = _ordered_attachment_items(
            attachment_bundle,
            allowed_categories={"instructions_evaluation"},
            max_items=4,
        )
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
                    compact_part = _compact_requirement_text(part, max_chars=360, max_fragments=2, require_action=True)
                    lower = compact_part.lower()
                    if len(compact_part) < 70 or len(compact_part) > 360:
                        continue
                    if _is_boilerplate_objective_sentence(compact_part):
                        continue
                    if not any(term in lower for term in action_terms):
                        continue
                    snippet = f"{heading}; {compact_part}"[:420]
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
    texts: list[str] = [
        *[
            _compact_requirement_text(str(item.get("source_text", "") or "").strip(), max_chars=420, max_fragments=3, require_action=False)
            for item in _attachment_section_blocks(attachment_bundle, allowed_categories=scope_categories, max_items=max_items * 2)
        ],
        *_preferred_objective_body_blocks(attachment_bundle, max_items=max_items),
    ]
    for item in ordered:
        for snippet in item.get("snippets", []) or []:
            cleaned = _compact_requirement_text(snippet, max_chars=320, max_fragments=2, require_action=False)
            if cleaned:
                texts.append(cleaned)
        text_excerpt = _attachment_text_value(item, max_chars=2200)
        if text_excerpt:
            texts.append(_compact_requirement_text(text_excerpt, max_chars=420, max_fragments=3, require_action=False))
    return _dedupe_strings(texts)


def _attachment_objective_candidates(attachment_bundle: dict[str, object], max_items: int = 18) -> list[str]:
    candidate_categories = {"statement_of_work", "solicitation", "amendment", "questions_answers"}
    ordered = _ordered_attachment_items(
        attachment_bundle,
        allowed_categories=candidate_categories,
        max_items=6,
    )
    candidates: list[str] = [
        *[
            _compact_requirement_text(str(item.get("source_text", "") or "").strip(), max_chars=420, max_fragments=3, require_action=False)
            for item in _attachment_section_blocks(attachment_bundle, allowed_categories=candidate_categories, max_items=max_items)
        ],
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
                if _is_boilerplate_objective_sentence(sentence):
                    continue
                if not any(marker in lower for marker in marker_keywords):
                    continue
                compact_sentence = _compact_requirement_text(sentence, max_chars=320, max_fragments=2, require_action=False)
                if compact_sentence:
                    candidates.append(compact_sentence)
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
    if any(marker in lower for marker in OBJECTIVE_FORMATTING_MARKERS):
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
    if any(token in lower for token in ("arial", "font", "page limit", "margins", "tracking", "kerning", "leading")):
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
            sentence = _compact_requirement_text(part, max_chars=360, max_fragments=2, require_action=True)
            lower = sentence.lower()
            if len(sentence) < 70 or len(sentence) > 360:
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
            *[
                str(item.get("text", "") or "").strip()
                for item in _attachment_section_blocks(attachment_bundle, max_items=18, include_filename=True)
            ],
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
    strong_adjacent_rows = [
        row
        for row in adjacent_rows
        if int(row.get("_overlap_count", 0) or 0) >= 3 and int(row.get("_relevance_score", 0) or 0) >= 7
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
    adjacent_competitors = _dedupe_strings(
        [
            str(row.get("Recipient Name", "") or "")
            for row in strong_adjacent_rows
            if str(row.get("Recipient Name", "") or "")
        ]
    )[:5]
    emerging_challengers = _dedupe_strings(
        [
            str(row.get("Recipient Name", "") or "")
            for row in strong_adjacent_rows
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
            if strong_adjacent_rows and adjacent_competitors:
                notes.append(
                    f"Adjacent scope-overlap performers from public award history include: {', '.join(adjacent_competitors[:4])}."
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
            if strong_adjacent_rows and adjacent_competitors:
                notes.append(
                    f"Adjacent scope-overlap performers still worth pressure-testing as competitors: {', '.join(adjacent_competitors[:4])}."
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
        "adjacent_awards": strong_adjacent_rows[:6],
        "budget_signals": budget_signals,
        "related_procurements": related_procurements,
        "competitive_landscape": {
            "likely_incumbents": likely_incumbents,
            "frequent_primes": frequent_primes,
            "common_teammates": [],
            "adjacent_competitors": adjacent_competitors,
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
        "external_pressure_signal_count": len(public_research.get("external_pressure_signals", []) or []),
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
    attachment_review_required_count: int,
    pws_present: bool,
    workstream_count: int,
    incumbent_evidence_thin: bool,
    generic_strategy_warning_count: int,
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
    if attachment_review_required_count:
        score -= 10 if attachment_review_required_count == 1 else 15
        concerns.append("One or more attachments still need OCR, table recovery, or manual validation before the memo is decision-grade.")
    if pws_present and workstream_count == 0:
        score -= 20
        concerns.append("A PWS exists, but no requirement workstreams survived extraction.")
    if incumbent_evidence_thin:
        score -= 10
        concerns.append("Incumbent evidence remains thin across attachments, award history, and merged provider signals.")
    if generic_strategy_warning_count:
        score -= 15
        concerns.append("The memo still contains generic strategy language despite a parsed PWS/workstream package.")

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


def _capture_usefulness_assessment(
    public_research_assessment: dict[str, object],
    objective_validation_summary: dict[str, int],
    attachment_parse_guardrails: dict[str, object],
) -> dict[str, object]:
    corroborated_objective_rows = int(objective_validation_summary.get("corroborated_objective_rows", 0) or 0)
    fallback_objective_rows = int(objective_validation_summary.get("fallback_objective_rows", 0) or 0)
    real_funding_signal_count = int(objective_validation_summary.get("real_funding_signal_count", 0) or 0)
    attachment_workstream_count = int(objective_validation_summary.get("attachment_workstream_count", 0) or 0)
    requirement_anchor_ready = bool(public_research_assessment.get("requirement_bearing_core_anchor_present"))
    review_required_count = len(attachment_parse_guardrails.get("review_required_files", []) or [])
    drivers: list[str] = []
    score = 100

    if not requirement_anchor_ready:
        score -= 35
        drivers.append("No requirement-bearing mission, budget, or forecast anchor survived public-source admission.")
    if corroborated_objective_rows == 0:
        score -= 25
        drivers.append("No corroborated objective row survived this run.")
    elif fallback_objective_rows >= corroborated_objective_rows:
        score -= 15
        drivers.append("Fallback objectives still outnumber corroborated objective rows.")
    if real_funding_signal_count == 0:
        score -= 15
        drivers.append("No real funding signal was captured; funding remains a gap, not supporting evidence.")
    if attachment_workstream_count == 0 and bool(attachment_parse_guardrails.get("pws_present")):
        score -= 20
        drivers.append("A PWS is present, but no requirement workstreams were promoted into the memo.")
    if review_required_count:
        score -= 10
        drivers.append("One or more scope-bearing files still need OCR, table recovery, or manual review.")

    score = max(0, score)
    useful = requirement_anchor_ready and corroborated_objective_rows > 0 and real_funding_signal_count > 0
    release_warning = (
        "Usefulness warning: the memo can guide follow-up research, but it is not yet decision-grade because anchor evidence, objective corroboration, or funding proof is still thin."
        if not useful
        else ""
    )
    return {
        "useful": useful,
        "score": score,
        "release_warning": release_warning,
        "drivers": drivers,
        "requirement_anchor_ready": requirement_anchor_ready,
        "corroborated_objective_rows": corroborated_objective_rows,
        "fallback_objective_rows": fallback_objective_rows,
        "real_funding_signal_count": real_funding_signal_count,
    }


def _generic_strategy_language_warnings(
    decision_sections: dict[str, object],
    solicitation_facts: dict[str, object],
    attachment_workstreams: list[dict[str, object]],
    attachment_bundle: dict[str, object],
) -> list[str]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    pws_present = any(
        isinstance(item, dict) and str(item.get("category", "other") or "other") == "statement_of_work"
        for item in attachments
    )
    if not pws_present or not attachment_workstreams:
        return []
    requirement_tokens = _signal_tokens(
        " ".join(
            _dedupe_strings(
                [
                    *(
                        f"{str(item.get('title', '') or '').strip()} {str(item.get('objective', '') or '').strip()}"
                        for item in attachment_workstreams
                        if isinstance(item, dict)
                    ),
                    *[str(item) for item in (solicitation_facts.get("quoted_facts", []) or []) if str(item or "").strip()],
                ]
            )
        )
    )
    strategy = decision_sections.get("win_strategy", {}) or decision_sections.get("recommended_win_strategy", {})
    if not isinstance(strategy, dict):
        return []
    generic_hits: list[str] = []
    for label, key in GENERIC_STRATEGY_FIELDS:
        row_key = {
            "hot_buttons": "hot_button_rows",
            "win_themes": "win_theme_rows",
            "discriminators": "discriminator_rows",
        }.get(key, "")
        row_values = strategy.get(row_key, []) if row_key else []
        if isinstance(row_values, list) and row_values and isinstance(row_values[0], dict):
            for row in row_values:
                if not isinstance(row, dict):
                    continue
                line = str(row.get("text") or "").strip()
                anchor = str(row.get("evidence_anchor") or "").strip()
                lower = line.lower()
                overlap = len(_signal_tokens(line) & requirement_tokens)
                if line and not anchor and not lower.startswith("insufficient"):
                    generic_hits.append(f"{label}: {line}")
                    continue
                if line and any(cue in lower for cue in GENERIC_STRATEGY_CUES):
                    generic_hits.append(f"{label}: {line}")
                    continue
                if line and overlap < 2 and any(term in lower for term in ("execution", "readiness", "discipline", "proof point", "transition")):
                    generic_hits.append(f"{label}: {line}")
            continue
        values = strategy.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            line = str(value or "").strip()
            if not line:
                continue
            overlap = len(_signal_tokens(line) & requirement_tokens)
            lower = line.lower()
            if overlap < 2 and any(cue in lower for cue in GENERIC_STRATEGY_CUES):
                generic_hits.append(f"{label}: {line}")
    if not generic_hits:
        return []
    return [
        "PWS-backed memo still contains generic strategy language with weak requirement overlap: "
        + "; ".join(generic_hits[:3])
    ]


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
    stakeholder_map.extend(
        [
            f"Public contact history: {item.get('name', 'Contact')} - {item.get('summary', '')}"
            for item in (public_research.get("stakeholder_contact_history", []) or [])[:3]
            if isinstance(item, dict) and str(item.get("summary", "") or "").strip()
        ]
    )
    usaspending_search_text = _preferred_usaspending_search_text(resolved, str(canonical_id or ""))
    usaspending_result = enrich_from_usaspending(
        usaspending_search_text,
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
    solicitation_facts = _extract_solicitation_facts(attachment_bundle, resolved)
    attachment_workstreams = _extract_attachment_workstreams(attachment_bundle)
    staffing_pricing_signals = _extract_staffing_pricing_signals(
        attachment_bundle,
        solicitation_facts,
        attachment_workstreams,
    )
    attachment_anomalies = _extract_attachment_anomalies(attachment_bundle, solicitation_facts)
    solicitation_fact_model = build_solicitation_fact_model(
        solicitation_facts,
        attachment_bundle,
        attachment_workstreams=attachment_workstreams,
    )
    evaluator_anxiety_model = build_evaluator_anxiety_model(
        solicitation_fact_model,
        solicitation_facts=solicitation_facts,
        attachment_anomalies=attachment_anomalies,
        contract_type=str(solicitation_facts.get("contract_type") or ""),
        award_basis=str(solicitation_facts.get("evaluation_basis") or ""),
    )
    attachment_parse_guardrails = _attachment_parse_guardrails(attachment_bundle)
    executive_summary = _clean_excerpt(
        explanation.get("summary") or opportunity.get("summary") or "Fresh structured capture brief generated from current request context."
    )
    workstream_objectives = [str(item.get("objective") or "").strip() for item in attachment_workstreams if str(item.get("objective") or "").strip()]
    decomposed_objectives = workstream_objectives or _decompose_objectives(
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
    registry = load_json(workspace / "procurement" / "source-registry.json", default={})
    commercial_intel = enrich_capture_context(
        enabled_sources=get_enabled_sources(registry),
        resolved=resolved,
        notice_context_text=notice_context_text,
        attachment_bundle=attachment_bundle,
        vendor_profile=vendor_profile,
        preferences=preferences,
    )
    public_sources.extend(award_signals.get("source_log", []))
    public_sources.extend(_attachment_source_log(attachment_bundle))
    public_sources.extend(public_research.get("source_log", []))
    public_sources.extend(commercial_intel.get("source_log", []))

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
    if solicitation_facts.get("set_aside") and not opportunity.get("set_aside"):
        opportunity["set_aside"] = solicitation_facts.get("set_aside")
    attachment_scope_or_notice_snippets = attachment_scope_snippets or [notice_excerpt[:300] or "No substantive notice excerpt captured in this run."]
    attachment_text_blob = " ".join(attachment_text_pool).lower()
    vehicle_signals = []
    if solicitation_facts.get("contract_vehicle"):
        vehicle_signals.append(f"Attachment text names the vehicle path as {solicitation_facts.get('contract_vehicle')}.")
    if solicitation_facts.get("set_aside"):
        vehicle_signals.append(f"Attachment text states the set-aside as {solicitation_facts.get('set_aside')}.")
    if solicitation_facts.get("contract_type"):
        vehicle_signals.append(f"Attachment text indicates the contract type is {solicitation_facts.get('contract_type')}.")
    if "gsa mas" in attachment_text_blob or "multiple award schedule" in attachment_text_blob or "federal supply schedule" in attachment_text_blob:
        vehicle_signals.append("Attachment text references a GSA or schedule-style acquisition path that should be validated against the solicitation package.")
    if "indefinite-delivery-indefinite-quantity" in attachment_text_blob or "indefinite delivery indefinite quantity" in attachment_text_blob or "idiq" in attachment_text_blob:
        vehicle_signals.append("Attachment text references an IDIQ-style contract structure that should be validated against the solicitation package.")
    if "single award task order contract" in attachment_text_blob or "satoc" in attachment_text_blob:
        vehicle_signals.append("Attachment text references a SATOC / task-order contract structure that should be validated against the solicitation package.")
    if not vehicle_signals:
        vehicle_signals.append("Likely vehicle path remains unconfirmed from the current public package; validate open-market versus existing-vehicle assumptions.")
    official_capture_evidence = build_capture_official_evidence_model(
        resolved=resolved,
        opportunity=opportunity,
        award_signals=award_signals,
        attachment_validation=attachment_validation,
        attachment_bundle=attachment_bundle,
        vehicle_signals=vehicle_signals,
        notice_context_text=notice_context_text,
    )
    cross_source_evidence = merge_evidence_models(
        [official_capture_evidence, *(commercial_intel.get("evidence_models", []) or [])]
    )
    merged_incumbent_name = str(
        ((cross_source_evidence.get("incumbent") or {}).get("name") if isinstance(cross_source_evidence, dict) else "")
        or ""
    ).strip()
    incumbent_evidence_thin = (
        not merged_incumbent_name
        and not attachment_validation.get("validated_incumbents")
        and not award_signals.get("relevant_awards")
    )
    vehicle_signals = _dedupe_strings(
        vehicle_signals
        + evidence_model_vehicle_signals(cross_source_evidence, max_items=6)
        + commercial_intel.get("vehicle_signals", [])
    )
    attachment_competitive_notes = _dedupe_strings(
        attachment_validation.get("notes", [])
        + attachment_validation.get("direct_mentions", [])
        + attachment_validation.get("supporting_snippets", [])
        + evidence_model_competitive_notes(cross_source_evidence, max_items=6)
        + commercial_intel.get("competitive_landscape", [])
    )
    funding_assessment = _funding_assessment(
        award_signals,
        public_research,
        attachment_budget_signals,
    )
    public_research_assessment = _public_research_assessment(public_research)
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
    related_procurements = (
        award_signals.get("related_procurements", [])
        + attachment_validation.get("supporting_snippets", [])
        + evidence_model_related_procurement_lines(cross_source_evidence, max_items=6)
        + commercial_intel.get("related_procurements", [])
    )
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
            *(
                []
                if public_research_assessment.get("requirement_bearing_core_anchor_present")
                else ["Public-web research ran, but no requirement-bearing mission, budget, or forecast anchors survived quality filters in this run."]
            ),
            *(
                []
                if funding_assessment.get("useful_evidence_found")
                else ["Funding evidence remains thin across USAspending, public budget sources, and attachment clues in this run."]
            ),
            *(
                []
                if not incumbent_evidence_thin
                else ["Incumbent evidence remains thin across attachments, award history, and merged provider signals."]
            ),
            *attachment_parse_guardrails.get("warnings", []),
            *award_signals.get("evidence_gaps", []),
            *public_research.get("evidence_gaps", []),
            *(cross_source_evidence.get("evidence_gaps", []) if isinstance(cross_source_evidence, dict) else []),
            *([item.get("signal", "") for item in attachment_anomalies if isinstance(item, dict)]),
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
        ([merged_incumbent_name] if merged_incumbent_name else [])
        or
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
                [str(item.get("objective") or "").strip() for item in attachment_workstreams[:2] if str(item.get("objective") or "").strip()]
                if scope_corroborated
                else []
            ),
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
    workstream_evidence_map = {
        str(item.get("objective") or "").strip(): list(item.get("evidence_snippets", []) or [])
        for item in attachment_workstreams
        if isinstance(item, dict)
    }
    for objective_text in decomposed_objectives:
        attachment_native_evidence = workstream_evidence_map.get(objective_text) or _attachment_objective_evidence_snippets(
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
    objective_validation_summary = {
        "objective_row_count": len(objective_rows),
        "corroborated_objective_rows": corroborated_objective_rows,
        "fallback_objective_rows": fallback_objective_rows,
        "attachment_native_corroborated_rows": attachment_native_corroborated_rows,
        "real_funding_signal_count": real_funding_signal_count,
        "attachment_workstream_count": len(attachment_workstreams),
        "attachment_anomaly_count": len(attachment_anomalies),
        "attachment_review_required_count": len(attachment_parse_guardrails.get("review_required_files", []) or []),
        "attachment_conflict_count": len(solicitation_facts.get("attachment_conflicts", []) or []),
    }
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
        normalized_evidence=cross_source_evidence,
        solicitation_facts=solicitation_facts,
        solicitation_fact_model=solicitation_fact_model,
        attachment_workstreams=attachment_workstreams,
        staffing_pricing_signals=staffing_pricing_signals,
        attachment_anomalies=attachment_anomalies,
        evaluator_anxiety_model=evaluator_anxiety_model,
    )
    generic_strategy_warnings = _generic_strategy_language_warnings(
        decision_sections,
        solicitation_facts,
        attachment_workstreams,
        attachment_bundle,
    )
    if generic_strategy_warnings:
        decision_sections.setdefault("assumptions_unknowns_confidence", {}).update(
            {
                "unknowns": _dedupe_strings(
                    list(decision_sections.get("assumptions_unknowns_confidence", {}).get("unknowns", []) or [])
                    + generic_strategy_warnings
                )
            }
        )
        decision_sections.setdefault("capture_judgment", {}).update(
            {
                "next_best_actions": _dedupe_strings(
                    list(decision_sections.get("capture_judgment", {}).get("next_best_actions", []) or [])
                    + ["Tighten the win-theme section so PWS-backed hot buttons and discriminators are requirement-specific, not generic capture boilerplate."]
                )
            }
        )
    memo_honesty = _memo_honesty_assessment(
        public_research,
        len(objective_rows),
        fallback_objective_rows,
        real_funding_signal_count,
        bool(attachment_bundle.get("attachments_expected")),
        len(attachment_bundle.get("attachments", []) or []),
        len(attachment_parse_guardrails.get("review_required_files", []) or []),
        bool(attachment_parse_guardrails.get("pws_present")),
        len(attachment_workstreams),
        incumbent_evidence_thin,
        len(generic_strategy_warnings),
    )
    capture_usefulness = _capture_usefulness_assessment(
        public_research_assessment,
        {**objective_validation_summary, "generic_strategy_warning_count": len(generic_strategy_warnings)},
        attachment_parse_guardrails,
    )
    combined_release_warnings = _dedupe_strings(
        [
            str(memo_honesty.get("release_warning") or "").strip(),
            str(capture_usefulness.get("release_warning") or "").strip(),
        ]
    )
    combined_source_statuses = _dedupe_strings(
        [
            json.dumps(item, sort_keys=True)
            for item in (
                list(public_research.get("source_statuses", []) or [])
                + list(commercial_intel.get("source_statuses", []) or [])
            )
            if isinstance(item, dict)
        ]
    )
    rendered_source_statuses = [json.loads(item) for item in combined_source_statuses]
    decision_sections.setdefault("capture_judgment", {}).update(
        {
            "memo_honesty_score": memo_honesty.get("score", 0),
            "memo_honesty_confidence": memo_honesty.get("confidence_band", "Low"),
            "release_warning": " ".join(combined_release_warnings).strip(),
            "honesty_drivers": _dedupe_strings(
                list(memo_honesty.get("drivers", []) or [])
                + list(capture_usefulness.get("drivers", []) or [])
            ),
        }
    )
    decision_sections.setdefault("assumptions_unknowns_confidence", {}).update(
        {
            "memo_honesty_score": memo_honesty.get("score", 0),
            "release_warning": " ".join(combined_release_warnings).strip(),
            "honesty_drivers": _dedupe_strings(
                list(memo_honesty.get("drivers", []) or [])
                + list(capture_usefulness.get("drivers", []) or [])
            ),
        }
    )
    capture_generated_at = utc_now_iso()
    procurement_timeline = _build_procurement_timeline(solicitation_facts, capture_generated_at)
    evidence = {
        "request_id": request_id,
        "generated_at": capture_generated_at,
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
        "procurement_timeline": procurement_timeline,
        "objectives": objective_rows,
        "stakeholder_map": stakeholder_map,
        "stakeholder_contacts": stakeholder_contacts,
        "stakeholder_contact_history": public_research.get("stakeholder_contact_history", []),
        "leadership_priority_signals": public_research.get("leadership_priority_signals", []),
        "mission_context_signals": public_research.get("mission_context_signals", []),
        "policy_compliance_signals": public_research.get("policy_compliance_signals", []),
        "oversight_signals": public_research.get("oversight_signals", []),
        "acquisition_forecast_signals": public_research.get("acquisition_forecast_signals", []),
        "external_pressure_signals": public_research.get("external_pressure_signals", []),
        "budget_funding_signals": budget_funding_signals,
        "funding_assessment": funding_assessment,
        "related_procurements": related_procurements,
        "vehicle_signals": vehicle_signals,
        "solicitation_facts": solicitation_facts,
        "solicitation_fact_model": solicitation_fact_model,
        "attachment_workstreams": attachment_workstreams,
        "attachment_anomalies": attachment_anomalies,
        "staffing_pricing_signals": staffing_pricing_signals,
        "evaluator_anxiety_model": evaluator_anxiety_model,
        "cross_source_evidence": cross_source_evidence,
        "commercial_intel": {
            "public_source_statuses": public_research.get("source_statuses", []),
            "source_statuses": commercial_intel.get("source_statuses", []),
            "matches": commercial_intel.get("matches", []),
            "evidence_models": commercial_intel.get("evidence_models", []),
            "related_procurements": commercial_intel.get("related_procurements", []),
            "vehicle_signals": commercial_intel.get("vehicle_signals", []),
            "competitive_landscape": commercial_intel.get("competitive_landscape", []),
            "next_questions": commercial_intel.get("next_questions", []),
        },
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
            "parse_guardrails": attachment_parse_guardrails,
            "errors": attachment_bundle.get("errors", []),
            "scope_snippets": attachment_scope_snippets,
            "incumbent_validation": attachment_validation,
            "solicitation_facts": solicitation_facts,
            "solicitation_fact_model": solicitation_fact_model,
            "workstreams": attachment_workstreams,
            "anomalies": attachment_anomalies,
            "evaluator_anxiety_model": evaluator_anxiety_model,
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
                *evidence_model_next_questions(cross_source_evidence, max_items=6),
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
        "source_statuses": rendered_source_statuses,
        "memo_honesty_assessment": memo_honesty,
        "capture_usefulness_assessment": capture_usefulness,
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
                **objective_validation_summary,
                "generic_strategy_warning_count": len(generic_strategy_warnings),
            },
            "public_research_assessment": public_research_assessment,
            "attachment_parse_guardrails": attachment_parse_guardrails,
            "memo_honesty": memo_honesty,
            "capture_usefulness": capture_usefulness,
            "stub_stage_exited_before_response": True,
            "menu_only_fallback_used": False,
        },
    }
    evidence.update(decision_sections)

    brief_text = render_capture_brief(bundle_root / "templates" / "capture-brief.template.md", evidence)
    brief_validation = validate_capture_brief_text(brief_text, evidence)
    evidence["validation"]["all_required_sections_present"] = brief_validation["all_required_sections_present"]
    evidence["validation"]["evidence_alignment_ok"] = brief_validation.get("evidence_alignment_ok", True)
    evidence["validation"]["generic_strategy_hits"] = brief_validation.get("generic_strategy_hits", [])
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
        and brief_validation.get("evidence_alignment_ok", True)
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
