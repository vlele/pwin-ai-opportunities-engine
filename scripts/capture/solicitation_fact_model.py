from __future__ import annotations

import re
from typing import Any


SPACE_RE = re.compile(r"\s+")
GENERIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "shall",
    "will",
    "must",
    "contractor",
    "offeror",
    "proposal",
    "government",
    "service",
    "services",
    "support",
    "work",
    "task",
    "tasks",
    "requirement",
    "requirements",
    "section",
    "attachment",
    "document",
    "file",
}
ROLE_HINTS = (
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
ACCESS_MARKERS = (
    "access",
    "badge",
    "credential",
    "clearance",
    "escort",
    "background check",
    "background investigation",
    "controlled unclassified",
    "cui",
    "fouo",
    "privacy",
    "hipaa",
    "ndis",
    "non-disclosure",
    "nda",
    "visitor control",
)
DELIVERABLE_MARKERS = (
    "deliverable",
    "submission",
    "report",
    "brief",
    "status report",
    "plan",
    "schedule",
    "estimate",
    "work package",
    "package",
    "artifact",
    "drawings",
    "submittal",
    "review package",
    "matrix",
)
EVALUATION_MARKERS = (
    "evaluation",
    "best value",
    "lpta",
    "price realism",
    "technically acceptable",
    "past performance",
    "technical approach",
    "management approach",
    "evaluation factor",
    "basis for award",
)
PRICING_MARKERS = (
    "clin",
    "subclin",
    "slin",
    "price",
    "pricing",
    "rate",
    "cost",
    "fixed price",
    "ffp",
    "labor hour",
    "time and materials",
    "ceiling",
)
ACCEPTANCE_MARKERS = (
    "acceptance",
    "aql",
    "performance requirement",
    "quality assurance",
    "surveillance",
    "inspection",
    "remedy",
    "corrective action",
    "deduction",
    "incentive",
    "service summary",
)
SECTION_PRIORITY = {
    "statement_of_work": 0,
    "solicitation": 1,
    "instructions_evaluation": 2,
    "questions_answers": 3,
    "amendment": 4,
    "other": 5,
}


def _normalize_text(value: object) -> str:
    return SPACE_RE.sub(" ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()


def _clean_excerpt(value: object, *, max_chars: int = 240) -> str:
    return _normalize_text(value)[:max_chars].strip(" .;:-")


def _dedupe_strings(values: list[str], *, max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = _clean_excerpt(value, max_chars=420)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if max_items is not None and len(output) >= max_items:
            break
    return output


def _string_list(value: object, *, max_items: int = 8) -> list[str]:
    if isinstance(value, list):
        return _dedupe_strings([str(item) for item in value if str(item or "").strip()], max_items=max_items)
    if isinstance(value, tuple):
        return _dedupe_strings([str(item) for item in value if str(item or "").strip()], max_items=max_items)
    text = _clean_excerpt(value, max_chars=420)
    return [text] if text else []


def _ordered_attachments(attachment_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = attachment_bundle.get("attachments", []) if isinstance(attachment_bundle, dict) else []
    ordered = [item for item in attachments if isinstance(item, dict)]
    ordered.sort(key=lambda item: SECTION_PRIORITY.get(str(item.get("category", "other") or "other"), 9))
    return ordered


def _fact_row(field: str, text: str, evidence_anchor: str, *, source_kind: str, confidence: str = "medium") -> dict[str, str]:
    return {
        "field": field,
        "text": _clean_excerpt(text, max_chars=260),
        "evidence_anchor": _clean_excerpt(evidence_anchor, max_chars=420),
        "source_kind": source_kind,
        "confidence": confidence,
    }


def _structured_row_records(item: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = item.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _section_blocks(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("section_blocks", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _table_blocks(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("table_blocks", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        cleaned = _clean_excerpt(value, max_chars=420)
        if cleaned:
            return cleaned
    return ""


def _role_candidate(text: str) -> str:
    cleaned = _clean_excerpt(text, max_chars=120)
    if not cleaned:
        return ""
    lower = cleaned.lower()
    if any(stop in lower for stop in ("labor category", "key personnel", "fte", "hours", "total", "optional", "base year", "option year")):
        return ""
    if len(lower.split()) > 8:
        return ""
    if not any(hint in lower for hint in ROLE_HINTS):
        return ""
    if cleaned.lower() in GENERIC_STOPWORDS:
        return ""
    return cleaned


def _staffing_role_candidates(attachment_bundle: dict[str, Any], solicitation_facts: dict[str, Any]) -> list[str]:
    roles = _string_list(solicitation_facts.get("staffing_roles"), max_items=12)
    for item in _ordered_attachments(attachment_bundle)[:8]:
        for row in _structured_row_records(item, "matrix_rows") + _structured_row_records(item, "pricing_rows"):
            cells = row.get("cells", [])
            if not isinstance(cells, list):
                cells = []
            for candidate in cells[:3]:
                role = _role_candidate(str(candidate or ""))
                if role:
                    roles.append(role)
            label_role = _role_candidate(str(row.get("label") or ""))
            if label_role:
                roles.append(label_role)
        for block in _section_blocks(item):
            source_text = str(block.get("source_text") or block.get("text") or "")
            for fragment in re.split(r"[.;]\s+|\n+", source_text):
                if not re.search(r"\b(?:provide|furnish|maintain|staff|key personnel|labor categor(?:y|ies)|position)\b", fragment, re.IGNORECASE):
                    continue
                for match in re.finditer(
                    r"\b([A-Z][A-Za-z/&-]+(?:\s+[A-Z][A-Za-z/&-]+){0,4}\s+(?:"
                    + "|".join(re.escape(hint) for hint in ROLE_HINTS)
                    + r"))\b",
                    fragment,
                ):
                    role = _role_candidate(match.group(1))
                    if role:
                        roles.append(role)
    return _dedupe_strings(roles, max_items=10)


def _block_fact_rows(
    attachment_bundle: dict[str, Any],
    *,
    field: str,
    markers: tuple[str, ...],
    max_items: int = 6,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _ordered_attachments(attachment_bundle)[:8]:
        filename = str(item.get("filename") or "attachment")
        for block in _section_blocks(item):
            text = _clean_excerpt(block.get("text") or block.get("source_text") or "", max_chars=320)
            if not text:
                continue
            lower = text.lower()
            if not any(marker in lower for marker in markers):
                continue
            rows.append(
                _fact_row(
                    field,
                    text,
                    f"{filename}: {block.get('source_text') or block.get('text') or text}",
                    source_kind="section_block",
                    confidence="high",
                )
            )
            if len(rows) >= max_items:
                return rows
    return rows


def _table_fact_rows(
    attachment_bundle: dict[str, Any],
    *,
    field: str,
    keys: set[str],
    markers: tuple[str, ...],
    max_items: int = 6,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _ordered_attachments(attachment_bundle)[:8]:
        filename = str(item.get("filename") or "attachment")
        for key in keys:
            for row in _structured_row_records(item, key):
                text = _clean_excerpt(row.get("text") or "", max_chars=320)
                if not text:
                    continue
                lower = text.lower()
                if markers and not any(marker in lower for marker in markers):
                    continue
                rows.append(
                    _fact_row(
                        field,
                        text,
                        f"{filename}: {text}",
                        source_kind=key,
                        confidence="high",
                    )
                )
                if len(rows) >= max_items:
                    return rows
        for block in _table_blocks(item):
            kind = str(block.get("kind") or "").strip().lower()
            if kind not in {key.replace("_rows", "") for key in keys}:
                continue
            block_rows = _string_list(block.get("rows"), max_items=4)
            if not block_rows:
                continue
            rendered = "; ".join(block_rows[:3])
            rows.append(
                _fact_row(
                    field,
                    rendered,
                    f"{filename}: {rendered}",
                    source_kind="table_block",
                    confidence="high",
                )
            )
            if len(rows) >= max_items:
                return rows
    return rows


def _contract_fact_rows(solicitation_facts: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    mapping = (
        ("set_aside", "Set-aside"),
        ("contract_vehicle", "Vehicle"),
        ("contract_type", "Contract type"),
        ("evaluation_basis", "Evaluation basis"),
        ("due_date", "Due date"),
        ("period_of_performance", "Period of performance"),
        ("transition_window", "Transition window"),
        ("funds_status", "Funds status"),
        ("naics", "NAICS"),
        ("naics_size_standard", "NAICS size standard"),
    )
    for field, label in mapping:
        value = _clean_excerpt(solicitation_facts.get(field), max_chars=220)
        if not value:
            continue
        if field == "naics":
            title = _clean_excerpt(solicitation_facts.get("naics_title"), max_chars=120)
            text = f"{label}: {value}" + (f" - {title}" if title else "")
        else:
            text = f"{label}: {value}"
        rows.append(_fact_row(field, text, text, source_kind="solicitation_fact", confidence="medium"))
    return rows


def _conflict_rows(attachment_bundle: dict[str, Any], solicitation_facts: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for conflict in solicitation_facts.get("attachment_conflicts", []) if isinstance(solicitation_facts, dict) else []:
        if not isinstance(conflict, dict):
            continue
        field = _clean_excerpt(conflict.get("field"), max_chars=80)
        values = _string_list(conflict.get("values"), max_items=3)
        sources = _string_list(conflict.get("sources"), max_items=3)
        if not field or not values:
            continue
        rows.append(
            _fact_row(
                "conflict",
                f"Cross-document conflict on {field}: {' vs '.join(values[:2])}",
                "; ".join(sources[:3]) or "; ".join(values[:3]),
                source_kind="attachment_conflict",
                confidence="high",
            )
        )
    for item in _ordered_attachments(attachment_bundle):
        filename = str(item.get("filename") or "attachment")
        for warning in _string_list(item.get("parse_warnings"), max_items=4):
            rows.append(
                _fact_row(
                    "parse_warning",
                    f"Parse warning: {warning.replace('_', ' ')}",
                    filename,
                    source_kind="parse_warning",
                    confidence="medium",
                )
            )
    return _dedupe_fact_rows(rows, max_items=8)


def _dedupe_fact_rows(rows: list[dict[str, str]], *, max_items: int | None = None) -> list[dict[str, str]]:
    seen: set[str] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _clean_excerpt(row.get("text"), max_chars=260)
        anchor = _clean_excerpt(row.get("evidence_anchor"), max_chars=420)
        key = f"{text.lower()}::{anchor.lower()}"
        if not text or key in seen:
            continue
        seen.add(key)
        rendered = dict(row)
        rendered["text"] = text
        rendered["evidence_anchor"] = anchor
        output.append(rendered)
        if max_items is not None and len(output) >= max_items:
            break
    return output


def _package_strength(attachment_bundle: dict[str, Any], conflict_rows: list[dict[str, str]]) -> dict[str, Any]:
    attachments = _ordered_attachments(attachment_bundle)
    section_block_count = sum(len(_section_blocks(item)) for item in attachments)
    table_block_count = sum(len(_table_blocks(item)) for item in attachments)
    matrix_row_count = sum(len(_structured_row_records(item, "matrix_rows")) for item in attachments)
    pricing_row_count = sum(len(_structured_row_records(item, "pricing_rows")) for item in attachments)
    acceptance_row_count = sum(len(_structured_row_records(item, "acceptance_rows")) for item in attachments)
    review_required_count = sum(1 for item in attachments if bool(item.get("review_required")))
    attachment_native_ready = (
        section_block_count >= 2 and (matrix_row_count >= 1 or table_block_count >= 1)
    ) or section_block_count >= 6
    return {
        "attachment_count": len(attachments),
        "section_block_count": section_block_count,
        "table_block_count": table_block_count,
        "matrix_row_count": matrix_row_count,
        "pricing_row_count": pricing_row_count,
        "acceptance_row_count": acceptance_row_count,
        "review_required_count": review_required_count,
        "conflict_count": len(conflict_rows),
        "attachment_native_ready": attachment_native_ready,
    }


def build_solicitation_fact_model(
    solicitation_facts: dict[str, Any] | None,
    attachment_bundle: dict[str, Any] | None,
    *,
    attachment_workstreams: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    solicitation_facts = solicitation_facts if isinstance(solicitation_facts, dict) else {}
    attachment_bundle = attachment_bundle if isinstance(attachment_bundle, dict) else {}
    attachment_workstreams = attachment_workstreams if isinstance(attachment_workstreams, list) else []

    contract_rows = _contract_fact_rows(solicitation_facts)
    workstream_rows = _dedupe_fact_rows(
        [
            _fact_row(
                "workstream",
                str(item.get("objective") or item.get("title") or "").strip(),
                _first_nonempty(_string_list(item.get("evidence_snippets"), max_items=1)),
                source_kind="attachment_workstream",
                confidence="high",
            )
            for item in attachment_workstreams
            if isinstance(item, dict) and str(item.get("objective") or item.get("title") or "").strip()
        ],
        max_items=8,
    )
    deliverable_rows = _dedupe_fact_rows(
        _table_fact_rows(
            attachment_bundle,
            field="deliverable",
            keys={"matrix_rows"},
            markers=DELIVERABLE_MARKERS,
            max_items=6,
        )
        + _block_fact_rows(
            attachment_bundle,
            field="deliverable",
            markers=DELIVERABLE_MARKERS,
            max_items=6,
        ),
        max_items=8,
    )
    pricing_rows = _dedupe_fact_rows(
        _table_fact_rows(
            attachment_bundle,
            field="pricing",
            keys={"pricing_rows", "matrix_rows"},
            markers=PRICING_MARKERS,
            max_items=6,
        )
        + _block_fact_rows(
            attachment_bundle,
            field="pricing",
            markers=PRICING_MARKERS,
            max_items=4,
        ),
        max_items=8,
    )
    evaluation_rows = _dedupe_fact_rows(
        _block_fact_rows(
            attachment_bundle,
            field="evaluation",
            markers=EVALUATION_MARKERS,
            max_items=6,
        )
        + [
            row
            for row in contract_rows
            if str(row.get("field") or "") == "evaluation_basis"
        ],
        max_items=8,
    )
    acceptance_rows = _dedupe_fact_rows(
        _table_fact_rows(
            attachment_bundle,
            field="acceptance",
            keys={"acceptance_rows", "remedy_rows"},
            markers=ACCEPTANCE_MARKERS,
            max_items=6,
        )
        + _block_fact_rows(
            attachment_bundle,
            field="acceptance",
            markers=ACCEPTANCE_MARKERS,
            max_items=6,
        ),
        max_items=8,
    )
    access_rows = _dedupe_fact_rows(
        _block_fact_rows(
            attachment_bundle,
            field="access",
            markers=ACCESS_MARKERS,
            max_items=6,
        ),
        max_items=6,
    )
    staffing_roles = _staffing_role_candidates(attachment_bundle, solicitation_facts)
    staffing_rows = _dedupe_fact_rows(
        [
            _fact_row(
                "staffing",
                f"Visible staffing role: {role}",
                f"Visible staffing role: {role}",
                source_kind="role_extraction",
                confidence="medium",
            )
            for role in staffing_roles
        ]
        + _block_fact_rows(
            attachment_bundle,
            field="staffing",
            markers=("labor categor", "key personnel", "position", "staffing", "ftee", "fte"),
            max_items=4,
        ),
        max_items=8,
    )
    conflict_rows = _conflict_rows(attachment_bundle, solicitation_facts)
    promoted_fact_lines = _dedupe_strings(
        [row.get("text", "") for row in contract_rows + deliverable_rows + pricing_rows + evaluation_rows + acceptance_rows + access_rows + staffing_rows],
        max_items=16,
    )
    package_strength = _package_strength(attachment_bundle, conflict_rows)
    return {
        "contract_fact_rows": contract_rows,
        "workstream_fact_rows": workstream_rows,
        "deliverable_fact_rows": deliverable_rows,
        "pricing_fact_rows": pricing_rows,
        "evaluation_fact_rows": evaluation_rows,
        "acceptance_fact_rows": acceptance_rows,
        "access_fact_rows": access_rows,
        "staffing_fact_rows": staffing_rows,
        "staffing_roles": staffing_roles,
        "conflict_rows": conflict_rows,
        "promoted_fact_lines": promoted_fact_lines,
        "package_strength": package_strength,
    }
