from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from collections import Counter
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None

try:
    from docx import Document
except ImportError:  # pragma: no cover - optional dependency
    Document = None
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None
from common.runtime import USER_AGENT


SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"
PUBLIC_RESOURCES_URL = "https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources"
PUBLIC_RESOURCE_DOWNLOAD_URL = "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{resource_id}/download"
CATEGORY_PRIORITY = {
    "statement_of_work": 0,
    "solicitation": 1,
    "instructions_evaluation": 2,
    "questions_answers": 3,
    "amendment": 4,
    "schedule": 5,
    "pricing": 6,
    "subcontracting": 7,
    "other": 8,
}
ATTACHMENT_VISION_ALLOWED_CATEGORIES = {
    "statement_of_work",
    "solicitation",
    "instructions_evaluation",
    "amendment",
    "pricing",
}
ATTACHMENT_VISION_MAX_PAGES = max(1, int(os.getenv("PWIN_ATTACHMENT_VISION_MAX_PAGES", "4") or "4"))
ATTACHMENT_VISION_TIMEOUT_SECONDS = max(30, int(os.getenv("PWIN_ATTACHMENT_VISION_TIMEOUT_SECONDS", "90") or "90"))
DEFAULT_ATTACHMENT_VISION_MODEL = (
    os.getenv("PWIN_ATTACHMENT_VISION_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-4.1-mini"
)
SNIPPET_KEYWORDS = (
    "scope",
    "objective",
    "requirements",
    "deliver",
    "deliverables",
    "evaluation",
    "period of performance",
    "transition",
    "incumbent",
    "current contractor",
)
STRUCTURED_LINE_MARKERS = (
    "clin ",
    "subclin",
    "task ",
    "subtask",
    "pws",
    "performance work statement",
    "statement of objectives",
    "statement of work",
    "deliverable",
    "transition",
    "period of performance",
    "shall",
    "must",
    "provide",
    "maintain",
    "report",
    "staff",
)
TOC_LINE_RE = re.compile(r"\.{5,}\s*\d+\s*$")
SECTION_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+){0,3}\s+[A-Z][A-Za-z0-9/\-() ,]+$")
PREFERRED_SECTION_HINTS: tuple[tuple[str, int], ...] = (
    ("statement of work", 6),
    ("performance work statement", 6),
    ("description/specifications/work statement", 6),
    ("description specifications work statement", 6),
    ("statement of objectives", 5),
    ("statement of objective", 5),
    ("scope", 5),
    ("general requirements", 5),
    ("requirements", 4),
    ("specific tasks", 5),
    ("tasks", 4),
    ("deliverables", 5),
    ("period of performance", 4),
    ("background", 3),
    ("purpose", 3),
    ("evaluation factors", 3),
    ("instructions to offerors", 3),
    ("instructions to offeror", 3),
)
ATTACHMENT_TABLE_ROW_RE = re.compile(
    r"^\s*(?:CLIN|SubCLIN|Task|Subtask|AQL|PRS|Performance Objective|Deliverable|Transition|SLIN)\b",
    re.IGNORECASE,
)
TABLE_CELL_SPLIT_RE = re.compile(r"\s*(?:\||\t| {2,})\s*")
ATTACHMENT_MATRIX_MARKERS = (
    "clin",
    "subclin",
    "task",
    "subtask",
    "matrix",
    "deliverable",
    "aql",
    "prs",
    "acceptable quality level",
    "performance requirement",
)
ATTACHMENT_ACCEPTANCE_MARKERS = (
    "acceptance criteria",
    "acceptable quality level",
    "aql",
    "inspection",
    "surveillance method",
    "performance threshold",
    "quality level",
)
ATTACHMENT_INCENTIVE_MARKERS = (
    "incentive",
    "disincentive",
    "remedy",
    "deduction",
    "service credit",
    "liquidated damages",
)
ATTACHMENT_PRICING_MARKERS = (
    "unit price",
    "extended price",
    "total evaluated price",
    "price schedule",
    "rate card",
    "hourly rate",
    "fully burdened",
    "labor rate",
    "cost proposal",
    "price proposal",
    "contract line item",
)
HARD_PAGE_PRIORITY_MARKERS = (
    *ATTACHMENT_PRICING_MARKERS,
    *ATTACHMENT_ACCEPTANCE_MARKERS,
    *ATTACHMENT_INCENTIVE_MARKERS,
    "contract line item",
    "subclin",
    "slin",
    "task order",
    "performance objective",
    "traceability matrix",
)
SECTION_BLOCK_HINTS = (
    "statement of objectives",
    "statement of objective",
    "statement of work",
    "performance work statement",
    "description/specifications/work statement",
    "description specifications work statement",
    "scope",
    "general requirements",
    "requirements",
    "deliverables",
    "specific tasks",
    "tasks",
    "task order",
    "period of performance",
    "background",
    "purpose",
    "evaluation factors",
    "instructions to offerors",
    "instructions to offeror",
)
SECTION_BLOCK_SKIP_HINTS = (
    "table of contents",
    "clauses incorporated by reference",
    "representations and certifications",
)
SECTION_HEADING_HINT_RE = re.compile(
    r"^\s*(?:section\s+[a-z0-9]+(?:\s*[-–]\s*)?|\d+(?:\.\d+){0,3}\s+)[a-z].{2,140}$",
    re.IGNORECASE,
)
ACTION_VERB_HINTS = (
    "shall",
    "must",
    "provide",
    "deliver",
    "maintain",
    "support",
    "perform",
    "report",
    "transition",
)
ROOT_SCOPE_HEADINGS = (
    "statement of work",
    "performance work statement",
    "description/specifications/work statement",
    "description specifications work statement",
    "statement of objectives",
    "statement of objective",
)
COMPACT_SECTION_PREFERRED_MARKERS = (
    "shall",
    "must",
    "provide",
    "deliver",
    "maintain",
    "perform",
    "support",
    "report",
    "transition",
    "inspect",
    "review",
    "manage",
    "task",
    "deliverable",
    "clin",
    "subclin",
    "scope",
    "requirement",
    "acceptance",
    "quality",
    "aql",
    "prs",
)
INLINE_HEADING_BODY_RE = re.compile(
    r"^(\d+(?:\.\d+){0,3}\s+(?:Scope|General Requirements|Deliverables?|Tasks?|Specific Tasks?|Performance Objectives?|Requirements?))\s+(?=(?:The contractor|Contractor|Provide|Maintain|Deliver|Perform|Support|Report|Inspect|Review|Manage)\b)",
    re.IGNORECASE,
)


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = _normalize_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _normalize_preserve_lines(value: object, max_chars: int = 8000) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)[:max_chars]


def _is_toc_like_line(line: str) -> bool:
    lowered = line.lower()
    return "table of contents" in lowered or TOC_LINE_RE.search(line) is not None or line.count(".") >= 12


def _page_is_toc_like(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    toc_like = sum(1 for line in lines if _is_toc_like_line(line))
    return any("table of contents" in line.lower() for line in lines) or (toc_like >= 4 and toc_like >= max(2, len(lines) // 3))


def _section_hint_weight(line: str) -> int:
    lowered = line.lower()
    if any(skip in lowered for skip in SECTION_BLOCK_SKIP_HINTS):
        return 0
    return max((weight for hint, weight in PREFERRED_SECTION_HINTS if hint in lowered), default=0)


def _normalized_attachment_name(filename: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(filename or "").lower()).strip()


def _preferred_pdf_section_excerpt(text: str, max_chars: int = 12000) -> str:
    lines = [line.strip() for line in _normalize_preserve_lines(text, max_chars=30000).splitlines() if line.strip()]
    if not lines:
        return ""
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if (SECTION_HEADING_RE.match(line) or SECTION_HEADING_HINT_RE.match(line)) and not _is_toc_like_line(line)
    ]
    if not heading_indexes:
        return ""
    sections: list[tuple[int, int, str]] = []
    for position, start_index in enumerate(heading_indexes):
        heading = lines[start_index]
        hint_weight = _section_hint_weight(heading)
        if hint_weight <= 0:
            continue
        next_heading_index = heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(lines)
        captured: list[str] = [heading]
        action_hits = 0
        structured_hits = 0
        for line in lines[start_index + 1:next_heading_index]:
            lower = line.lower()
            if _is_toc_like_line(line):
                continue
            captured.append(line)
            if any(token in lower for token in ACTION_VERB_HINTS):
                action_hits += 1
            if any(token in lower for token in STRUCTURED_LINE_MARKERS):
                structured_hits += 1
            if len(" ".join(captured)) >= 2200:
                break
        block = "\n".join(captured).strip()
        if len(block) < 80:
            continue
        score = (hint_weight * 10) + min(action_hits, 8) + min(structured_hits, 8)
        sections.append((score, start_index, block))
    if not sections:
        return ""
    selected: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for _, _, block in sorted(sections, key=lambda item: (-item[0], item[1])):
        key = _normalize_text(block[:240])
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(block)
        total_chars += len(block) + 2
        if len(selected) >= 6 or total_chars >= max_chars:
            break
    return "\n\n".join(selected)[:max_chars]


def _filename_from_headers(url: str, headers: Any) -> str:
    disposition = headers.get("Content-Disposition", "") if headers else ""
    match = re.search(r"filename\*?=(?:UTF-8''|)([^;]+)", disposition, re.IGNORECASE)
    if match:
        filename = urllib.parse.unquote_plus(match.group(1).strip().strip('"'))
        if filename:
            return filename
    path_name = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    return urllib.parse.unquote_plus(path_name or "attachment.bin")


def _attachment_category(filename: str) -> str:
    lowered = _normalized_attachment_name(filename)
    if (
        " sow " in f" {lowered} "
        or "statement of work" in lowered
        or "performance work statement" in lowered
        or "draft pws" in lowered
        or " pws " in f" {lowered} "
        or "soo" in lowered
        or "statement of objectives" in lowered
        or "statement of objective" in lowered
    ):
        return "statement_of_work"
    if "rftop" in lowered or "evaluation" in lowered or "instruction" in lowered or "section l" in lowered or "section m" in lowered:
        return "instructions_evaluation"
    if "question" in lowered or "q&a" in lowered or "qanda" in lowered:
        return "questions_answers"
    if "amendment" in lowered:
        return "amendment"
    if "schedule" in lowered:
        return "schedule"
    if "price" in lowered or "pricing" in lowered or "cost" in lowered:
        return "pricing"
    if "subcontract" in lowered:
        return "subcontracting"
    if ("rfp" in lowered or "rfq" in lowered or "solicitation" in lowered or "soliciation" in lowered):
        return "solicitation"
    return "other"


def _refine_attachment_category(initial_category: str, filename: str, text: str) -> str:
    lower = f"{_normalized_attachment_name(filename)} {_normalize_text(text[:5000]).lower()}".strip()
    if not lower:
        return initial_category
    if any(token in lower for token in ("statement of work", "performance work statement", "statement of objectives", "statement of objective", " draft pws ", " section c - description/specifications/work statement ")):
        return "statement_of_work"
    if any(token in lower for token in ("section l", "section m", "evaluation factors for award", "instructions to offerors", "instruction to offerors", "best value", "past performance questionnaire")):
        return "instructions_evaluation"
    if any(token in lower for token in ("question matrix", "questions and answers", "question responses", "projnet question responses", "q and a", "offeror questions")):
        return "questions_answers"
    if any(token in lower for token in ("amendment of solicitation", "amendment ", "sf30", "modification of contract")):
        return "amendment"
    if initial_category == "other" and any(token in lower for token in ("solicitation/award", "request for quotation", "request for proposal", "combined synopsis", "combined synopsis/solicitation")):
        return "solicitation"
    return initial_category


def _extract_pdf_text_pypdf2(data: bytes, max_pages: int = 40) -> str:
    if PdfReader is None:
        raise RuntimeError("PyPDF2 unavailable")
    reader = PdfReader(io.BytesIO(data))
    page_texts: list[str] = []
    for page in reader.pages[:max_pages]:
        page_texts.append(page.extract_text() or "")
    filtered_pages = [page for page in page_texts if not _page_is_toc_like(page)]
    return "\n".join(filtered_pages or page_texts)


def _extract_pdf_text_fitz(data: bytes, max_pages: int = 40) -> str:
    if fitz is None:
        raise RuntimeError("fitz unavailable")
    document = fitz.open(stream=data, filetype="pdf")
    page_texts: list[str] = []
    for page_index in range(min(len(document), max_pages)):
        page = document.load_page(page_index)
        page_texts.append(page.get_text("text") or "")
    filtered_pages = [page for page in page_texts if not _page_is_toc_like(page)]
    return "\n".join(filtered_pages or page_texts)


def _pdf_text_quality_score(text: str) -> tuple[int, int, int]:
    cleaned = _normalize_preserve_lines(text, max_chars=60000)
    lines = [line for line in cleaned.splitlines() if line.strip()]
    heading_count = sum(1 for line in lines if SECTION_HEADING_RE.match(line) or SECTION_HEADING_HINT_RE.match(line))
    action_count = sum(1 for line in lines if any(term in line.lower() for term in ACTION_VERB_HINTS))
    return (len(cleaned), heading_count, action_count)


def _extract_pdf_text(data: bytes, max_pages: int = 40) -> str:
    candidates: list[str] = []
    errors: list[Exception] = []
    for extractor in (_extract_pdf_text_pypdf2, _extract_pdf_text_fitz):
        try:
            extracted = extractor(data, max_pages=max_pages)
        except Exception as exc:  # pragma: no cover - defensive fallback
            errors.append(exc)
            continue
        if extracted.strip():
            candidates.append(extracted)
    if not candidates:
        if errors:
            raise errors[0]
        raise RuntimeError("No PDF extractor available")
    combined = max(candidates, key=_pdf_text_quality_score)
    preferred = _preferred_pdf_section_excerpt(combined, max_chars=12000)
    if preferred:
        return f"{preferred}\n\n{combined}"
    return combined


def _openai_client(api_key: str | None = None):
    if OpenAI is None:
        return None
    key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        return OpenAI(api_key=key)
    except Exception:
        return None


def _image_data_url(image_bytes: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _call_openai_vision_json(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    image_bytes: bytes,
    model: str | None = None,
    timeout_seconds: int = ATTACHMENT_VISION_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    client = _openai_client()
    if client is None:
        return None
    try:
        completion = client.with_options(timeout=timeout_seconds).chat.completions.create(
            model=model or DEFAULT_ATTACHMENT_VISION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(user_payload, ensure_ascii=True)},
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_bytes)}},
                    ],
                },
            ],
        )
    except Exception:
        return None
    try:
        content = completion.choices[0].message.content or "{}"
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        payload = json.loads(str(content))
        if isinstance(payload, dict):
            payload["_model_name"] = str(model or DEFAULT_ATTACHMENT_VISION_MODEL)
            return payload
    except Exception:
        return None
    return None


def _pdf_page_records(data: bytes, max_pages: int = 500) -> list[dict[str, Any]]:
    from common.form_evidence import page_controls, has_flat_choices
    if fitz is None:
        return []
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return []
    page_records: list[dict[str, Any]] = []
    for page_index in range(min(len(document), max_pages)):
        page = document.load_page(page_index)
        text = page.get_text("text") or ""
        lines = [line.strip() for line in _normalize_preserve_lines(text, max_chars=12000).splitlines() if line.strip()]
        lower_lines = [line.lower() for line in lines]
        table_like_line_count = sum(
            1
            for line in lines
            if len(line) >= 20 and ("|" in line or "\t" in line or re.search(r" {2,}", line) or ATTACHMENT_TABLE_ROW_RE.match(line))
        )
        marker_hits = sum(1 for line in lower_lines if any(marker in line for marker in HARD_PAGE_PRIORITY_MARKERS))
        char_count = len(_normalize_text(text))
        image_count = len(page.get_images(full=True))
        flags: list[str] = []
        controls = page_controls(page)
        if has_flat_choices(page, text):
            flags.append("choice_controls")
        if _page_is_toc_like(text):
            flags.append("toc_like")
        if image_count and char_count < 220:
            flags.append("image_text_sparse")
        if char_count < 140:
            flags.append("thin_text")
        if table_like_line_count >= 3:
            flags.append("table_layout")
        if marker_hits >= 2:
            flags.append("requirement_matrix_markers")
        page_records.append(
            {
                "page_number": page_index + 1,
                "text": text,
                "char_count": char_count,
                "image_count": image_count,
                "table_like_line_count": table_like_line_count,
                "marker_hits": marker_hits,
                "flags": flags,
                "form_controls": controls,
            }
        )
    document.close()
    return page_records


def _select_hard_page_candidates(page_records: list[dict[str, Any]], max_pages: int = ATTACHMENT_VISION_MAX_PAGES) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for record in page_records:
        flags = {str(flag) for flag in (record.get("flags", []) or []) if str(flag).strip()}
        if "toc_like" in flags and "choice_controls" not in flags:
            continue
        score = 0
        if "choice_controls" in flags:
            score += 20
        if "image_text_sparse" in flags:
            score += 6
        if "thin_text" in flags:
            score += 4
        if "table_layout" in flags:
            score += 5
        if "requirement_matrix_markers" in flags:
            score += 5
        score += min(int(record.get("marker_hits", 0) or 0), 4)
        if score <= 0:
            continue
        ranked.append((score, int(record.get("page_number", 0) or 0), record))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [dict(record, hard_page_score=score) for score, _, record in ranked[:max_pages]]


def _render_pdf_page_png(data: bytes, page_number: int, *, zoom: float = 1.8) -> bytes | None:
    if fitz is None:
        return None
    try:
        document = fitz.open(stream=data, filetype="pdf")
        page = document.load_page(max(0, page_number - 1))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pixmap.tobytes("png")
    except Exception:
        return None
    return None


def _normalize_vision_row(value: dict[str, Any], *, page_number: int, row_index: int) -> dict[str, Any] | None:
    text = _normalize_text(value.get("text") or "")
    if not text:
        return None
    cells = [_normalize_text(cell) for cell in (value.get("cells", []) or []) if _normalize_text(cell)]
    kind = str(value.get("kind") or "").strip().lower() or _table_row_kind(text)
    label = _normalize_text(value.get("label") or (cells[0] if cells else text[:80]))
    return {
        "line_index": page_number * 1000 + row_index,
        "page_number": page_number,
        "kind": kind,
        "label": label[:120],
        "text": _normalize_text(f"Page {page_number}; {text}")[:420],
        "cells": cells[:10],
        "source_kind": "vision_page",
    }


def _normalize_vision_section_block(value: dict[str, Any], *, page_number: int) -> dict[str, str] | None:
    title = _heading_title(_normalize_text(value.get("title") or ""))[:180]
    body = _normalize_text(value.get("text") or value.get("source_text") or "")
    if not body:
        return None
    source_text = _normalize_text(value.get("source_text") or body)
    section_text = _normalize_text(f"{title}; {body}" if title and title.lower() not in body.lower() else body)[:1200]
    return {
        "title": title or f"Page {page_number} requirement block",
        "text": section_text,
        "source_text": _normalize_text(f"Page {page_number}: {source_text}")[:2200],
        "page_number": str(page_number),
        "source_kind": "vision_page",
    }


def _vision_page_review(
    *,
    filename: str,
    category: str,
    page_number: int,
    page_text: str,
    image_bytes: bytes,
) -> dict[str, Any] | None:
    system_prompt = (
        "You are extracting requirement-bearing solicitation content from a single page image. "
        "Return JSON only. Keep wording close to the page. Ignore headers, footers, page numbers, and table-of-contents text. "
        "Do not invent content. Prefer scope, task, CLIN, pricing, staffing, acceptance, remedy, transition, and evaluation details. "
        "For section_blocks, return short requirement-bearing blocks with title, text, and source_text. "
        "For table_rows, preserve visible row meaning with kind, label, text, and cells. "
        "Valid kinds are clin, task, pricing, acceptance, remedy, matrix, or table."
        " Read visible checkboxes/radio buttons separately from their printed labels. "
        "Return form_controls with group, exact option label, state selected/unselected/uncertain, "
        "and bbox [left, top, right, bottom] normalized to 0..1 on the page. "
        "A nearby label is not a selected option. If a mark is illegible, use uncertain; never guess. "
        "Preserve unchecked alternatives too. Do not infer a set-aside from unselected form labels. "
        "Preserve CLIN quantities, units, base/option distinctions and fee rows separately; "
        "do not add repeated option-year positions to the base staffing count."
    )
    user_payload = {
        "filename": filename,
        "category": category,
        "page_number": page_number,
        "native_text_excerpt": _normalize_preserve_lines(page_text, max_chars=3000),
        "required_output": {
            "section_blocks": [{"title": "string", "text": "string", "source_text": "string"}],
            "table_rows": [{"kind": "string", "label": "string", "text": "string", "cells": ["string"]}],
            "parse_warnings": ["string"],
            "form_controls": [{"group": "string", "label": "string", "state": "selected|unselected|uncertain", "bbox": [0, 0, 1, 1]}],
        },
    }
    payload = _call_openai_vision_json(
        system_prompt=system_prompt,
        user_payload=user_payload,
        image_bytes=image_bytes,
    )
    if not isinstance(payload, dict):
        return None
    page_sections = [
        block
        for block in (
            _normalize_vision_section_block(item, page_number=page_number)
            for item in (payload.get("section_blocks", []) or [])
            if isinstance(item, dict)
        )
        if block is not None
    ]
    page_rows = [
        row
        for row in (
            _normalize_vision_row(item, page_number=page_number, row_index=index)
            for index, item in enumerate((payload.get("table_rows", []) or []), start=1)
            if isinstance(item, dict)
        )
        if row is not None
    ]
    warnings = _dedupe_strings(
        [_normalize_text(item) for item in (payload.get("parse_warnings", []) or []) if _normalize_text(item)]
    )[:6]
    from common.form_evidence import normalize_vision_controls
    return {
        "page_number": page_number,
        "model_name": str(payload.get("_model_name") or DEFAULT_ATTACHMENT_VISION_MODEL),
        "section_blocks": page_sections[:6],
        "table_rows": page_rows[:12],
        "parse_warnings": warnings,
        "form_controls": normalize_vision_controls(payload.get("form_controls", []), page_number),
    }


def _render_vision_text_excerpt(pages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for page in pages:
        page_number = int(page.get("page_number", 0) or 0)
        for block in (page.get("section_blocks", []) or []):
            if not isinstance(block, dict):
                continue
            source_text = _normalize_text(block.get("source_text") or block.get("text") or "")
            if source_text:
                lines.append(source_text if source_text.lower().startswith(f"page {page_number}:") else f"Page {page_number}: {source_text}")
        for row in (page.get("table_rows", []) or []):
            if not isinstance(row, dict):
                continue
            text = _normalize_text(row.get("text") or "")
            if text:
                lines.append(text)
    return _normalize_preserve_lines("\n".join(lines), max_chars=20000)


def _merge_hard_page_structures(
    structures: dict[str, Any],
    vision_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = {
        "headings": list(structures.get("headings", []) or []),
        "section_blocks": list(structures.get("section_blocks", []) or []),
        "structured_rows": list(structures.get("structured_rows", []) or []),
        "table_blocks": list(structures.get("table_blocks", []) or []),
        "matrix_rows": list(structures.get("matrix_rows", []) or []),
        "pricing_rows": list(structures.get("pricing_rows", []) or []),
        "acceptance_rows": list(structures.get("acceptance_rows", []) or []),
        "remedy_rows": list(structures.get("remedy_rows", []) or []),
        "section_graph": list(structures.get("section_graph", []) or []),
        "parse_warnings": list(structures.get("parse_warnings", []) or []),
    }
    seen_sections = {
        _normalize_text(f"{item.get('title', '')} {item.get('source_text', '')}")
        for item in merged["section_blocks"]
        if isinstance(item, dict)
    }
    seen_rows = {_normalize_text(item) for item in merged["structured_rows"] if isinstance(item, str)}
    additional_row_records: list[dict[str, Any]] = []
    for page in vision_pages:
        for block in (page.get("section_blocks", []) or []):
            if not isinstance(block, dict):
                continue
            title = _normalize_text(block.get("title") or "")
            if title:
                merged["headings"].append(title)
            key = _normalize_text(f"{block.get('title', '')} {block.get('source_text', '')}")
            if key and key not in seen_sections:
                seen_sections.add(key)
                merged["section_blocks"].append(block)
        for row in (page.get("table_rows", []) or []):
            if not isinstance(row, dict):
                continue
            row_text = _normalize_text(row.get("text") or "")
            if row_text and row_text not in seen_rows:
                seen_rows.add(row_text)
                merged["structured_rows"].append(row_text[:420])
                additional_row_records.append(row)
                kind = str(row.get("kind", "table") or "table")
                if kind in {"clin", "task", "matrix"}:
                    merged["matrix_rows"].append(row)
                if kind == "pricing":
                    merged["pricing_rows"].append(row)
                if kind == "acceptance":
                    merged["acceptance_rows"].append(row)
                if kind == "remedy":
                    merged["remedy_rows"].append(row)
        merged["parse_warnings"].extend(page.get("parse_warnings", []) or [])
    if additional_row_records:
        merged["table_blocks"].extend(_table_blocks(additional_row_records, max_blocks=8))
    merged["headings"] = _dedupe_strings(merged["headings"])[:24]
    merged["section_blocks"].sort(key=lambda item: _section_block_priority(item.get("title", ""), item.get("text", "")), reverse=True)
    merged["section_blocks"] = merged["section_blocks"][:12]
    merged["structured_rows"] = _dedupe_strings(merged["structured_rows"])[:36]
    merged["table_blocks"] = merged["table_blocks"][:8]
    merged["matrix_rows"] = merged["matrix_rows"][:36]
    merged["pricing_rows"] = merged["pricing_rows"][:36]
    merged["acceptance_rows"] = merged["acceptance_rows"][:36]
    merged["remedy_rows"] = merged["remedy_rows"][:36]
    merged["parse_warnings"] = _dedupe_strings(merged["parse_warnings"])[:12]
    return merged


def _review_hard_pdf_pages(
    *,
    filename: str,
    category: str,
    data: bytes,
) -> dict[str, Any]:
    if not filename.lower().endswith(".pdf"):
        return {"status": "skipped_not_pdf", "candidates": [], "pages": []}
    if fitz is None:
        return {"status": "skipped_missing_fitz", "candidates": [], "pages": []}
    page_records = _pdf_page_records(data)
    native_controls = [c for record in page_records for c in record.get("form_controls", [])]
    choice_pages = [record["page_number"] for record in page_records if "choice_controls" in record.get("flags", [])]
    eligible_pages = page_records if category in ATTACHMENT_VISION_ALLOWED_CATEGORIES else [
        record for record in page_records if "choice_controls" in record.get("flags", [])]
    candidates = _select_hard_page_candidates(eligible_pages)
    if not candidates:
        return {"status": "no_hard_pages", "candidates": [], "pages": [], "form_controls": native_controls, "unresolved_choice_pages": []}
    if _openai_client() is None:
        return {"status": "skipped_no_openai_client", "candidates": candidates, "pages": [],
                "form_controls": native_controls, "unresolved_choice_pages": choice_pages}
    reviewed_pages: list[dict[str, Any]] = []
    model_name = ""
    for candidate in candidates:
        image_bytes = _render_pdf_page_png(data, int(candidate.get("page_number", 0) or 0))
        if not image_bytes:
            continue
        page_review = _vision_page_review(
            filename=filename,
            category=category,
            page_number=int(candidate.get("page_number", 0) or 0),
            page_text=str(candidate.get("text", "") or ""),
            image_bytes=image_bytes,
        )
        if not isinstance(page_review, dict):
            continue
        model_name = str(page_review.get("model_name") or model_name)
        reviewed_pages.append(page_review)
    from common.form_evidence import merge_controls
    controls = merge_controls(native_controls, [c for page in reviewed_pages for c in page.get("form_controls", [])])
    observed_pages = {c["page_number"] for c in controls if c["basis"] == "vision_observation"}
    uncertain_pages = {c["page_number"] for c in controls if c["state"] == "uncertain"}
    return {
        "status": "ok" if reviewed_pages else "error",
        "model_name": model_name or DEFAULT_ATTACHMENT_VISION_MODEL,
        "candidates": candidates,
        "pages": reviewed_pages,
        "form_controls": controls,
        "unresolved_choice_pages": sorted((set(choice_pages) - observed_pages) | uncertain_pages),
    }


def _extract_docx_text(data: bytes) -> str:
    if Document is None:
        raise RuntimeError("python-docx unavailable")
    document = Document(io.BytesIO(data))
    values = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [_normalize_text(cell.text) for cell in row.cells if _normalize_text(cell.text)]
            if not cells:
                continue
            values.append(" | ".join(cells))
    return "\n".join(values)


def _extract_xlsx_text(data: bytes, max_strings: int = 120) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        sheet_names: list[str] = []
        shared_strings: list[str] = []
        workbook_rels: dict[str, str] = {}
        if "xl/workbook.xml" in names:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet_names = [node.attrib.get("name", "") for node in workbook.findall(".//main:sheets/main:sheet", ns)]
            rel_ns = {"rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
            if "xl/_rels/workbook.xml.rels" in names:
                rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                workbook_rels = {
                    node.attrib.get("Id", ""): node.attrib.get("Target", "")
                    for node in rel_root.findall(".//rel:Relationship", rel_ns)
                }
        if "xl/sharedStrings.xml" in names:
            strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for node in strings_root.iter():
                if node.tag.endswith("}t") and node.text:
                    shared_strings.append(node.text.strip())
        lines = []
        if sheet_names:
            lines.append(f"Workbook sheets: {', '.join(sheet_names[:8])}")
        if shared_strings:
            sample = [value for value in shared_strings if value][:max_strings]
            lines.append("Shared strings: " + " | ".join(sample[:40]))
        if "xl/workbook.xml" in names:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            ns = {
                "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            }
            sheet_nodes = workbook.findall(".//main:sheets/main:sheet", ns)
            for sheet_node in sheet_nodes[:4]:
                sheet_name = sheet_node.attrib.get("name", "") or "Sheet"
                rel_id = sheet_node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = workbook_rels.get(rel_id, "")
                if not target:
                    continue
                sheet_path = f"xl/{target.lstrip('./')}"
                if sheet_path not in names:
                    continue
                root = ET.fromstring(archive.read(sheet_path))
                row_texts: list[str] = []
                for row in root.findall(".//main:sheetData/main:row", ns)[:20]:
                    values: list[str] = []
                    for cell in row.findall("main:c", ns):
                        raw_value = ""
                        cell_type = cell.attrib.get("t", "")
                        if cell_type == "inlineStr":
                            raw_value = "".join(node.text or "" for node in cell.findall(".//main:t", ns)).strip()
                        else:
                            value_node = cell.find("main:v", ns)
                            raw_value = (value_node.text or "").strip() if value_node is not None else ""
                            if raw_value and cell_type == "s":
                                try:
                                    raw_value = shared_strings[int(raw_value)]
                                except (ValueError, IndexError):
                                    pass
                        cleaned = _normalize_text(raw_value)
                        if cleaned:
                            values.append(cleaned)
                    if values:
                        row_texts.append(" | ".join(values[:10]))
                    if len(row_texts) >= 6:
                        break
                if row_texts:
                    lines.append(f"{sheet_name}: " + " || ".join(row_texts[:4]))
        return "\n".join(lines)


def _extract_plain_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_attachment_text(filename: str, content_type: str, data: bytes) -> tuple[str, str]:
    lowered = filename.lower()
    if lowered.endswith(".pdf") and PdfReader is None:
        return "", "dependency_missing:PyPDF2"
    if lowered.endswith(".docx") and Document is None:
        return "", "dependency_missing:python-docx"
    try:
        if lowered.endswith(".pdf"):
            return _extract_pdf_text(data), "parsed_pdf"
        if lowered.endswith(".docx"):
            return _extract_docx_text(data), "parsed_docx"
        if lowered.endswith(".xlsx"):
            return _extract_xlsx_text(data), "parsed_xlsx"
        if lowered.endswith((".txt", ".csv", ".json", ".xml", ".md")):
            return _extract_plain_text(data), "parsed_text"
        if "text" in content_type:
            return _extract_plain_text(data), "parsed_text"
    except Exception as exc:  # pragma: no cover - defensive fallback
        return "", f"parse_error:{exc.__class__.__name__}"
    return "", "unsupported"


def _pdf_page_count(data: bytes) -> int:
    if PdfReader is None:
        if fitz is None:
            return 0
    try:
        if PdfReader is not None:
            return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        pass
    if fitz is None:
        return 0
    try:
        return len(fitz.open(stream=data, filetype="pdf"))
    except Exception:  # pragma: no cover - defensive fallback
        return 0


def _is_structure_heading(line: str) -> bool:
    cleaned = _normalize_text(line)
    if not cleaned or _is_toc_like_line(cleaned):
        return False
    lower = cleaned.lower()
    if any(hint == lower or lower.startswith(f"{hint} ") for hint in SECTION_BLOCK_HINTS):
        return True
    if SECTION_HEADING_RE.match(cleaned) or SECTION_HEADING_HINT_RE.match(cleaned):
        return True
    return False


def _heading_title(line: str) -> str:
    cleaned = _normalize_text(line)
    match = re.match(r"^(?:section\s+[a-z0-9]+(?:\s*[-–]\s*)?|\d+(?:\.\d+){0,3}\s+)?(.+)$", cleaned, re.IGNORECASE)
    title = match.group(1) if match else cleaned
    return title.strip(" .:-")


def _split_heading_and_inline_body(line: str) -> tuple[str, str]:
    cleaned = _normalize_text(line)
    if not cleaned:
        return "", ""
    cleaned = INLINE_HEADING_BODY_RE.sub(r"\1; ", cleaned)
    lower = cleaned.lower()
    for hint in sorted(SECTION_BLOCK_HINTS, key=len, reverse=True):
        if lower == hint:
            return cleaned, ""
        for separator in (":", ";", " - ", ". "):
            prefix = f"{hint}{separator}"
            if lower.startswith(prefix):
                title = cleaned[: len(hint)]
                inline_body = cleaned[len(prefix):].strip(" ;:-")
                return title, inline_body
        if lower.startswith(f"{hint} "):
            remainder = cleaned[len(hint):].strip(" ;:-")
            if remainder and any(marker in remainder.lower() for marker in ACTION_VERB_HINTS):
                return cleaned[: len(hint)], remainder
    return _heading_title(cleaned), ""


def _section_block_priority(title: str, body: str) -> int:
    lower = f"{title} {body}".lower()
    score = 0
    for hint in SECTION_BLOCK_HINTS:
        if hint in lower:
            score += 4
    for verb in ACTION_VERB_HINTS:
        if verb in lower:
            score += 1
    if any(marker in lower for marker in ("clin", "task", "deliverable", "transition", "period of performance", "base period", "option year")):
        score += 3
    return score


def _table_row_kind(text: str) -> str:
    lower = str(text or "").lower()
    if lower.startswith(("clin ", "subclin", "slin")):
        return "clin"
    if lower.startswith(("task ", "subtask", "performance objective")):
        return "task"
    if any(marker in lower for marker in ATTACHMENT_PRICING_MARKERS):
        return "pricing"
    if any(marker in lower for marker in ATTACHMENT_ACCEPTANCE_MARKERS):
        return "acceptance"
    if any(marker in lower for marker in ATTACHMENT_INCENTIVE_MARKERS):
        return "remedy"
    if any(marker in lower for marker in ATTACHMENT_MATRIX_MARKERS):
        return "matrix"
    return "table"


def _matrix_row_record(raw_line: str, line_index: int) -> dict[str, Any] | None:
    normalized_row = _normalize_text(raw_line)
    normalized_row = TABLE_CELL_SPLIT_RE.sub("; ", normalized_row).strip(" ;:-")
    if len(normalized_row) < 24:
        return None
    cells = [cell.strip(" ;:-") for cell in TABLE_CELL_SPLIT_RE.split(_normalize_text(raw_line)) if cell.strip(" ;:-")]
    return {
        "line_index": line_index,
        "kind": _table_row_kind(normalized_row),
        "label": cells[0] if cells else normalized_row[:80],
        "text": normalized_row[:420],
        "cells": cells[:10],
    }


def _table_blocks(row_records: list[dict[str, Any]], max_blocks: int = 8) -> list[dict[str, Any]]:
    if not row_records:
        return []
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in sorted(row_records, key=lambda item: int(item.get("line_index", 0) or 0)):
        kind = str(row.get("kind", "table") or "table")
        line_index = int(row.get("line_index", 0) or 0)
        if (
            current is None
            or kind != str(current.get("kind", "table") or "table")
            or line_index - int(current.get("last_line_index", line_index) or line_index) > 2
        ):
            current = {
                "kind": kind,
                "title": f"{kind.replace('_', ' ').title()} table",
                "rows": [],
                "last_line_index": line_index,
            }
            blocks.append(current)
        current["rows"].append(str(row.get("text", "") or "").strip())
        current["last_line_index"] = line_index
    rendered: list[dict[str, Any]] = []
    for block in blocks[:max_blocks]:
        rows = [row for row in (block.get("rows", []) or []) if str(row or "").strip()]
        if not rows:
            continue
        rendered.append(
            {
                "kind": str(block.get("kind", "table") or "table"),
                "title": str(block.get("title", "Table") or "Table"),
                "row_count": len(rows),
                "rows": rows[:10],
            }
        )
    return rendered


def _section_graph(raw_lines: list[str], max_nodes: int = 24) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for raw_line in raw_lines:
        if not _is_structure_heading(raw_line):
            continue
        title, _ = _split_heading_and_inline_body(raw_line)
        cleaned_title = _heading_title(title).strip()
        if not cleaned_title:
            continue
        number_match = re.match(r"^\s*(\d+(?:\.\d+){0,3})\b", str(raw_line or "").strip())
        level = number_match.group(1).count(".") + 1 if number_match else 1
        while stack and int(stack[-1].get("level", 1) or 1) >= level:
            stack.pop()
        parent_title = str(stack[-1].get("title", "") or "").strip() if stack else ""
        node = {
            "title": cleaned_title[:180],
            "level": level,
            "parent_title": parent_title,
        }
        nodes.append(node)
        stack.append(node)
        if len(nodes) >= max_nodes:
            break
    return nodes


def _structure_parse_warnings(text: str, row_records: list[dict[str, Any]], section_blocks: list[dict[str, str]]) -> list[str]:
    lower = str(text or "").lower()
    warnings: list[str] = []
    has_pricing_markers = any(marker in lower for marker in ATTACHMENT_PRICING_MARKERS)
    has_acceptance_markers = any(marker in lower for marker in ATTACHMENT_ACCEPTANCE_MARKERS)
    has_remedy_markers = any(marker in lower for marker in ATTACHMENT_INCENTIVE_MARKERS)
    has_clin_markers = any(marker in lower for marker in ("clin ", "subclin", "slin"))
    kinds = Counter(str(row.get("kind", "") or "") for row in row_records)
    if has_pricing_markers and kinds.get("pricing", 0) == 0:
        warnings.append("pricing_markers_without_structured_rows")
    if has_acceptance_markers and kinds.get("acceptance", 0) == 0:
        warnings.append("acceptance_markers_without_structured_rows")
    if has_remedy_markers and kinds.get("remedy", 0) == 0:
        warnings.append("remedy_markers_without_structured_rows")
    if has_clin_markers and kinds.get("clin", 0) == 0:
        warnings.append("clin_markers_without_structured_rows")
    if any("scope" in str(block.get("title", "") or "").lower() for block in section_blocks) and not any(
        "shall" in str(block.get("source_text", "") or "").lower() for block in section_blocks
    ):
        warnings.append("scope_sections_without_action_sentences")
    return _dedupe_strings(warnings)


def _compact_section_body(body_lines: list[str], max_chars: int = 680) -> str:
    candidates: list[tuple[int, str]] = []
    for raw_line in body_lines:
        cleaned = _normalize_text(raw_line)
        if not cleaned or _is_toc_like_line(cleaned):
            continue
        lower = cleaned.lower()
        if lower in ROOT_SCOPE_HEADINGS:
            continue
        if ATTACHMENT_TABLE_ROW_RE.match(cleaned):
            normalized_row = re.sub(r"\s*(?:\||\t| {2,})\s*", "; ", cleaned).strip(" ;:-")
            candidates.append((8, normalized_row))
            continue
        for part in re.split(r"(?<=[.;])\s+|(?<=\))\s+(?=[A-Z])", cleaned):
            sentence = _normalize_text(part).strip(" ;:-")
            if len(sentence) < 24:
                continue
            lower_sentence = sentence.lower()
            score = 0
            if any(marker in lower_sentence for marker in COMPACT_SECTION_PREFERRED_MARKERS):
                score += 4
            if any(marker in lower_sentence for marker in ATTACHMENT_MATRIX_MARKERS):
                score += 2
            if any(marker in lower_sentence for marker in ATTACHMENT_ACCEPTANCE_MARKERS):
                score += 2
            if any(marker in lower_sentence for marker in ATTACHMENT_PRICING_MARKERS):
                score += 2
            if any(marker in lower_sentence for marker in ("mission", "purpose", "background")) and not any(
                verb in lower_sentence for verb in ACTION_VERB_HINTS
            ):
                score -= 3
            if score <= 0:
                continue
            candidates.append((score, sentence))

    if not candidates:
        fallback = _normalize_text(" ".join(body_lines))
        return fallback[:max_chars]

    selected: list[str] = []
    seen: set[str] = set()
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]), item[1])):
        key = sentence.lower()
        if key in seen:
            continue
        if any(key in existing.lower() or existing.lower() in key for existing in selected):
            continue
        seen.add(key)
        selected.append(sentence)
        if len("; ".join(selected)) >= max_chars or len(selected) >= 3:
            break
    return "; ".join(selected)[:max_chars]


def _extract_text_structures(text: str, *, max_sections: int = 12, max_rows: int = 36) -> dict[str, Any]:
    raw_lines = [line.strip() for line in str(text or "").replace("\r", "\n").split("\n") if line.strip()]
    headings: list[str] = []
    section_blocks: list[dict[str, str]] = []
    structured_rows: list[str] = []
    structured_row_records: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    seen_rows: set[str] = set()

    for line_index, raw_line in enumerate(raw_lines):
        if (
            ATTACHMENT_TABLE_ROW_RE.match(raw_line)
            or "|" in raw_line
            or "\t" in raw_line
            or re.search(r" {2,}", raw_line)
        ):
            row_record = _matrix_row_record(raw_line, line_index)
            if row_record is not None:
                normalized_row = str(row_record.get("text", "") or "")
                row_key = normalized_row.lower()
                if row_key not in seen_rows:
                    seen_rows.add(row_key)
                    structured_rows.append(normalized_row[:420])
                    structured_row_records.append(row_record)

    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if not _is_structure_heading(line):
            index += 1
            continue
        title, inline_body = _split_heading_and_inline_body(line)
        lower_title = title.lower()
        headings.append(title)
        if any(skip in lower_title for skip in SECTION_BLOCK_SKIP_HINTS):
            index += 1
            continue
        body_lines: list[str] = [inline_body] if inline_body else []
        lookahead = index + 1
        while lookahead < len(raw_lines):
            candidate = raw_lines[lookahead]
            if _is_structure_heading(candidate):
                break
            if not _is_toc_like_line(candidate):
                body_lines.append(candidate)
            if len(" ".join(body_lines)) >= 2200:
                break
            lookahead += 1
        body = _normalize_text(" ".join(body_lines))
        compact_body = _compact_section_body(body_lines)
        if lower_title in ROOT_SCOPE_HEADINGS and not compact_body:
            index = lookahead if lookahead > index else index + 1
            continue
        if body and _section_block_priority(title, body) >= 4:
            section_text = _normalize_text(f"{title}; {compact_body or body}")[:1200]
            key = section_text.lower()
            if key not in seen_sections:
                seen_sections.add(key)
                section_blocks.append(
                    {
                        "title": title[:180],
                        "text": section_text,
                        "source_text": _normalize_text(f"{title}; {body}")[:2200],
                    }
                )
        index = lookahead if lookahead > index else index + 1

    section_blocks.sort(key=lambda item: _section_block_priority(item.get("title", ""), item.get("text", "")), reverse=True)
    table_blocks = _table_blocks(structured_row_records)
    matrix_rows = [row for row in structured_row_records if str(row.get("kind", "") or "") in {"clin", "task", "matrix"}]
    pricing_rows = [row for row in structured_row_records if str(row.get("kind", "") or "") == "pricing"]
    acceptance_rows = [row for row in structured_row_records if str(row.get("kind", "") or "") == "acceptance"]
    remedy_rows = [row for row in structured_row_records if str(row.get("kind", "") or "") == "remedy"]
    parse_warnings = _structure_parse_warnings(text, structured_row_records, section_blocks)
    return {
        "headings": _dedupe_strings(headings)[:24],
        "section_blocks": section_blocks[:max_sections],
        "structured_rows": structured_rows[:max_rows],
        "table_blocks": table_blocks,
        "matrix_rows": matrix_rows[:max_rows],
        "pricing_rows": pricing_rows[:max_rows],
        "acceptance_rows": acceptance_rows[:max_rows],
        "remedy_rows": remedy_rows[:max_rows],
        "section_graph": _section_graph(raw_lines),
        "parse_warnings": parse_warnings,
    }


def _attachment_analysis(
    *,
    filename: str,
    content_type: str,
    category: str,
    parser_status: str,
    text: str,
    data: bytes,
) -> dict[str, Any]:
    lines = [line.strip() for line in _normalize_preserve_lines(text, max_chars=40000).splitlines() if line.strip()]
    lower_lines = [line.lower() for line in lines]
    joined_lower = "\n".join(lower_lines)
    char_count = len(text.strip())
    line_count = len(lines)
    page_count = _pdf_page_count(data) if filename.lower().endswith(".pdf") else 0
    table_like_line_count = sum(
        1
        for line in lines
        if len(line) >= 20 and ("|" in line or "\t" in line or re.search(r" {2,}", line) or ATTACHMENT_TABLE_ROW_RE.match(line))
    )
    matrix_marker_count = sum(1 for line in lower_lines if any(marker in line for marker in ATTACHMENT_MATRIX_MARKERS))
    acceptance_marker_count = sum(1 for line in lower_lines if any(marker in line for marker in ATTACHMENT_ACCEPTANCE_MARKERS))
    incentive_marker_count = sum(1 for line in lower_lines if any(marker in line for marker in ATTACHMENT_INCENTIVE_MARKERS))
    pricing_marker_count = sum(1 for line in lower_lines if any(marker in line for marker in ATTACHMENT_PRICING_MARKERS))
    flags: list[str] = []

    if parser_status.startswith(("parse_error", "dependency_missing")) or parser_status == "unsupported":
        flags.append("parse_failed_or_unsupported")
    if filename.lower().endswith(".pdf"):
        if page_count >= 4 and char_count < max(900, page_count * 180):
            flags.append("ocr_or_image_heavy_pdf")
        elif len(data) >= 600_000 and char_count < 1200:
            flags.append("ocr_or_image_heavy_pdf")
    if parser_status.startswith("parsed") and char_count < 400:
        flags.append("thin_text_extraction")
    if table_like_line_count >= 5 or matrix_marker_count >= 4:
        flags.append("table_or_matrix_heavy")
    if sum(1 for line in lines if ATTACHMENT_TABLE_ROW_RE.match(line)) >= 3:
        flags.append("clin_or_task_matrix_visible")
    if acceptance_marker_count >= 2:
        flags.append("acceptance_or_aql_visible")
    if incentive_marker_count >= 2:
        flags.append("incentive_or_remedy_visible")
    if category == "pricing" or filename.lower().endswith(".xlsx") or (pricing_marker_count >= 3 and table_like_line_count >= 2):
        flags.append("pricing_sheet_or_rate_table")
    if category in {"statement_of_work", "solicitation"} and "statement of work" in joined_lower and char_count < 900:
        flags.append("scope_document_underparsed")

    review_required = any(
        flag in flags
        for flag in (
            "parse_failed_or_unsupported",
            "ocr_or_image_heavy_pdf",
            "thin_text_extraction",
            "scope_document_underparsed",
        )
    )
    return {
        "text_char_count": char_count,
        "line_count": line_count,
        "page_count": page_count,
        "table_like_line_count": table_like_line_count,
        "matrix_marker_count": matrix_marker_count,
        "acceptance_marker_count": acceptance_marker_count,
        "incentive_marker_count": incentive_marker_count,
        "pricing_marker_count": pricing_marker_count,
        "analysis_flags": flags,
        "review_required": review_required,
    }


def _attachment_snippets(text: str, max_snippets: int = 6) -> list[str]:
    structured_lines = _normalize_preserve_lines(text, max_chars=12000).splitlines()
    ranked_structured: list[str] = []
    for line in structured_lines:
        lower = line.lower()
        if len(line) < 40:
            continue
        if _is_toc_like_line(line):
            continue
        if any(marker in lower for marker in STRUCTURED_LINE_MARKERS):
            ranked_structured.append(line[:360])
    if ranked_structured:
        return ranked_structured[:max_snippets]

    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    ranked: list[str] = []
    for part in parts:
        snippet = part.strip()
        if len(snippet) < 60:
            continue
        if any(keyword in snippet.lower() for keyword in SNIPPET_KEYWORDS):
            ranked.append(snippet[:320])
    if ranked:
        return ranked[:max_snippets]
    return [part.strip()[:320] for part in parts if part.strip()][:max_snippets]


def _download_attachment(
    url: str,
    *,
    filename_hint: str = "",
    content_type_hint: str = "",
    timeout: int = 45,
    max_bytes: int = 25_000_000,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        filename = filename_hint or _filename_from_headers(url, response.headers)
        content_type = content_type_hint or response.headers.get("Content-Type", "application/octet-stream")
    return _attachment_record_from_bytes(
        url=url,
        filename=filename,
        content_type=content_type,
        data=data,
        truncated=truncated,
    )


def _pdf_text_regions(page) -> list[tuple[str, str]]:
    """Label native text by geometry, without removing any source text."""
    regions = []
    bounds = page.rect
    for block in page.get_text("blocks"):
        if block[6] != 0 or not str(block[4]).strip():
            continue
        text = re.sub(r"\s+", " ", block[4]).strip()
        rect = fitz.Rect(block[:4])
        if not bounds.contains(rect):
            region = "outside_page"
        elif rect.y1 <= bounds.y0 + bounds.height * 0.10:
            region = "header"
        elif rect.y0 >= bounds.y1 - bounds.height * 0.10:
            region = "footer"
        else:
            region = "body"
        regions.append((region, text))
    return regions


def _sparse_pdf_page_coverage(page, regions, margin_counts, available_pages=0) -> dict:
    """Clear only proven empty/header-only pages; uncertain content stays blocked."""
    result = {"status": "unreadable", "reason": "Sparse native text requires review."}
    try:
        # Layout cannot certify images, vector content, forms or annotations as empty.
        if (page.rotation or page.get_image_info() or page.get_drawings()
                or page.get_xobjects() or next(page.annots(), None)
                or next(page.widgets(), None)):
            result["reason"] = "Sparse page has graphics, annotations, forms or rotated layout."
            return result
        links = page.get_links()
        if any(link.get("kind") != fitz.LINK_GOTO
               or not isinstance(link.get("page"), int)
               or not 0 <= link["page"] < available_pages for link in links):
            result["reason"] = "Sparse page references external or unavailable content."
            return result
        navigation = {"internal_navigation_targets": sorted({link["page"] + 1 for link in links})}
        if not regions:
            return {"status": "verified_blank", "reason": "No native text or visual objects; internal navigation retained.", **navigation}
        for region, text in regions:
            if region not in {"header", "footer"}:
                result["reason"] = "Sparse page contains body or out-of-bounds text."
                return result
            page_number = region == "footer" and re.fullmatch(
                r"(?:page\s+)?\d+(?:\s*(?:of|/)\s*\d+)?", text, re.IGNORECASE)
            # Require the same margin text on two OTHER pages, not a guessed ID.
            if not page_number and margin_counts[(region, text)] < 3:
                result["reason"] = "Margin text is not a page number or independently repeated header/footer."
                return result
        return {"status": "verified_header_footer_only",
                "reason": "Only page numbering or margin text repeated on at least two other pages; no visual objects; internal navigation retained.",
                "retained_margin_text": [text for _, text in regions], **navigation}
    except Exception as error:
        result["reason"] = f"Sparse-page layout check failed: {type(error).__name__}"
        return result


def _understanding_input(data: bytes, filename: str, extracted: str, vision_pages: list) -> tuple[str, dict]:
    """Keep checkpoint input independent of the renderer's bounded excerpts."""
    limit = 1000000
    metadata = {"complete": True, "basis": "native_text", "pages_total": None, "pages_extracted": None,
                "unreadable_pages": [], "page_coverage": [], "limitations": []}
    text = extracted
    native_regions = []
    if filename.lower().endswith(".pdf"):
        page_limit = 500
        try:
            if fitz is not None:
                with fitz.open(stream=data, filetype="pdf") as doc:
                    metadata["pages_total"] = len(doc)
                    pages = [doc.load_page(i).get_text("text") for i in range(min(len(doc), page_limit))]
                    regions = [_pdf_text_regions(doc.load_page(i)) for i in range(len(pages))]
                    margin_counts = Counter(item for rows in regions for item in set(rows)
                                            if item[0] in {"header", "footer"})
                    for index, page_text in enumerate(pages):
                        row = {"status": "native_text", "reason": "Native text extracted; not proof of table/image fidelity."}
                        if len(page_text.strip()) < 40:
                            row = _sparse_pdf_page_coverage(doc.load_page(index), regions[index], margin_counts, len(pages))
                        metadata["page_coverage"].append({"page_number": index + 1, **row})
            elif PdfReader is not None:
                doc = PdfReader(io.BytesIO(data))
                metadata["pages_total"] = len(doc.pages)
                pages = [page.extract_text() or "" for page in doc.pages[:page_limit]]
                metadata["page_coverage"] = [
                    {"page_number": i, "status": "unreadable" if len(page.strip()) < 40 else "native_text",
                     "reason": "Native text only; sparse pages need a layout-capable backend."}
                    for i, page in enumerate(pages, 1)]
            else:
                raise RuntimeError("No PDF text extractor is available")
            metadata["pages_extracted"] = len(pages)
            metadata["unreadable_pages"] = [row["page_number"] for row in metadata["page_coverage"]
                                             if row["status"] == "unreadable"]
            metadata["complete"] = bool(pages) and len(pages) == metadata["pages_total"] and not metadata["unreadable_pages"]
            text = "\n\n".join(f"[Page {i}]\n{page}" for i, page in enumerate(pages, 1))
            cursor = 0
            for i, page in enumerate(pages, 1):
                piece = _normalize_preserve_lines(f"[Page {i}]\n{page}", max_chars=len(page) + 40)
                native_regions.append({"start": cursor, "end": cursor + len(piece) + 1,
                                       "page_number": i, "basis": "native_text"})
                cursor += len(piece) + 1
            metadata["limitations"].append("Native text coverage is not proof of image/table fidelity; sparse pages require review.")
        except Exception as error:
            metadata["complete"] = False
            metadata["limitations"].append(f"Full PDF coverage failed: {type(error).__name__}")
    elif filename.lower().endswith(".xlsx"):
        metadata["complete"] = False
        metadata["limitations"].append("Current workbook extractor samples sheets/rows; full workbook understanding is not established.")
    native_length = len(_normalize_preserve_lines(text, max_chars=max(len(text), 1)))
    vision_text = _render_vision_text_excerpt(vision_pages)
    if vision_text:
        text += "\n\n[Vision extracted hard-page evidence]\n" + vision_text
        # Partial vision recovery is not evidence that every sparse page was read.
    full = _normalize_preserve_lines(text, max_chars=max(len(text), 1))
    # Offsets describe the exact normalized extraction, not PDF byte/glyph offsets.
    regions = [dict(r, end=min(r["end"], native_length)) for r in native_regions]
    if vision_text:
        marker = "[Vision extracted hard-page evidence]\n"
        vision_start = native_length + (1 if native_length else 0) + len(marker)
        cursor = vision_start
        regions.append({"start": native_length, "end": vision_start, "page_number": None,
                        "basis": "generated_vision_separator"})
        for page in vision_pages:
            piece = _render_vision_text_excerpt([page])
            if not piece or cursor >= len(full):
                continue
            end = min(cursor + len(piece) + 1, len(full))
            regions.append({"start": cursor, "end": end, "page_number": page.get("page_number"),
                            "basis": "vision_extraction_unverified"})
            cursor = end
    metadata["text_regions"] = regions
    metadata.update(characters_extracted=len(full), characters_retained=min(len(full), limit))
    if len(full) > limit:
        metadata["complete"] = False
        metadata["limitations"].append("Checkpoint text resource limit exceeded.")
    return full[:limit], metadata


def _attachment_record_from_bytes(
    *,
    url: str,
    filename: str,
    content_type: str,
    data: bytes,
    truncated: bool,
    local_path: str = "",
) -> dict[str, Any]:
    text, parser_status = _extract_attachment_text(filename, content_type, data)
    structured_excerpt = _normalize_preserve_lines(text, max_chars=120000)
    category = _refine_attachment_category(_attachment_category(filename), filename, structured_excerpt)
    analysis = _attachment_analysis(
        filename=filename,
        content_type=content_type,
        category=category,
        parser_status=parser_status,
        text=structured_excerpt,
        data=data,
    )
    vision_review = _review_hard_pdf_pages(
        filename=filename,
        category=category,
        data=data,
    )
    structures = _extract_text_structures(structured_excerpt)
    vision_pages = vision_review.get("pages", []) if isinstance(vision_review, dict) else []
    if isinstance(vision_pages, list) and vision_pages:
        structures = _merge_hard_page_structures(structures, vision_pages)
        vision_excerpt = _render_vision_text_excerpt(vision_pages)
        if vision_excerpt:
            structured_excerpt = _normalize_preserve_lines(
                "\n\n".join([structured_excerpt, "[Vision extracted hard-page evidence]", vision_excerpt]),
                max_chars=160000,
            )
    understanding_text, understanding_coverage = _understanding_input(data, filename, text, vision_pages)
    if truncated:
        understanding_coverage["complete"] = False
        understanding_coverage["limitations"].append("Source bytes were truncated.")
    record = {
        "url": url,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "truncated": truncated,
        "parser_status": parser_status,
        "text_excerpt": structured_excerpt[:18000],
        "structured_text_excerpt": structured_excerpt,
        "understanding_text": understanding_text,
        "understanding_coverage": understanding_coverage,
        "category": category,
        **analysis,
    }
    if (
        isinstance(vision_review, dict)
        and vision_review.get("status") == "ok"
        and (vision_review.get("pages") or [])
    ):
        record["analysis_flags"] = _dedupe_strings(
            [
                *(record.get("analysis_flags", []) or []),
                "hard_page_review_applied",
            ]
        )
        native_review_required = bool(record.get("review_required"))
        recovered_structure = bool(structures.get("section_blocks") or structures.get("structured_rows"))
        if native_review_required and recovered_structure:
            record["review_required"] = False
    record["hard_page_candidates"] = vision_review.get("candidates", []) if isinstance(vision_review, dict) else []
    record["form_controls"] = vision_review.get("form_controls", []) if isinstance(vision_review, dict) else []
    record["unresolved_choice_pages"] = vision_review.get("unresolved_choice_pages", []) if isinstance(vision_review, dict) else []
    record["vision_review_status"] = vision_review.get("status", "skipped") if isinstance(vision_review, dict) else "skipped"
    record["vision_model"] = vision_review.get("model_name", "") if isinstance(vision_review, dict) else ""
    record["vision_pages"] = vision_pages if isinstance(vision_pages, list) else []
    record["headings"] = structures.get("headings", [])
    record["section_blocks"] = structures.get("section_blocks", [])
    record["structured_rows"] = structures.get("structured_rows", [])
    record["table_blocks"] = structures.get("table_blocks", [])
    record["matrix_rows"] = structures.get("matrix_rows", [])
    record["pricing_rows"] = structures.get("pricing_rows", [])
    record["acceptance_rows"] = structures.get("acceptance_rows", [])
    record["remedy_rows"] = structures.get("remedy_rows", [])
    record["section_graph"] = structures.get("section_graph", [])
    record["parse_warnings"] = structures.get("parse_warnings", [])
    record["snippets"] = _attachment_snippets(
        "\n".join(
            [
                *(block.get("text", "") for block in record["section_blocks"] if isinstance(block, dict)),
                structured_excerpt,
            ]
        )
    )
    if local_path:
        record["local_path"] = local_path
    return record


def load_local_attachments(
    file_paths: list[str] | None,
    *,
    max_attachments: int = 20,
    max_bytes: int = 25_000_000,
) -> dict[str, Any]:
    attachments: list[dict[str, Any]] = []
    errors: list[str] = []
    normalized_paths: list[Path] = []
    for raw_path in file_paths or []:
        candidate = str(raw_path or "").strip()
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if not path.exists():
            errors.append(f"{path.as_posix()}: file_not_found")
            continue
        if not path.is_file():
            errors.append(f"{path.as_posix()}: not_a_file")
            continue
        normalized_paths.append(path)

    if len(normalized_paths) > max_attachments:
        errors.append(f"attachment_limit_exceeded: {len(normalized_paths) - max_attachments} files were not read")
    for path in normalized_paths[:max_attachments]:
        try:
            data = path.read_bytes()
            truncated = len(data) > max_bytes
            if truncated:
                data = data[:max_bytes]
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            attachments.append(
                _attachment_record_from_bytes(
                    url=path.resolve().as_uri(),
                    filename=path.name,
                    content_type=content_type,
                    data=data,
                    truncated=truncated,
                    local_path=path.resolve().as_posix(),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            errors.append(f"{path.as_posix()}: {exc}")

    attachments.sort(key=lambda item: (CATEGORY_PRIORITY.get(item.get("category", "other"), 99), item.get("filename", "")))
    status = "ok" if attachments else ("error" if errors else "empty")
    return {
        "status": status,
        "record": {},
        "point_of_contact": [],
        "attachments": attachments,
        "attachments_expected": bool(normalized_paths),
        "record_lookup_status": "local_files",
        "resource_listing_status": "local_files",
        "seeded_resource_links": False,
        "resource_link_count": len(normalized_paths),
        "errors": errors,
    }


def _record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return ""


def _fetch_public_notice_record(notice_id: str, solicitation_number: str = "", timeout: int = 30) -> dict[str, Any]:
    api_key = os.getenv("SAM_API_KEY", "").strip()
    if not api_key:
        return {"status": "missing_api_key", "record": {}}
    params = {"api_key": api_key}
    if notice_id:
        params["noticeid"] = notice_id
    elif solicitation_number:
        params["solnum"] = solicitation_number
    else:
        return {"status": "missing_identifier", "record": {}}
    request = urllib.request.Request(
        f"{SEARCH_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"status": "http_error", "detail": detail[:500], "record": {}}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"status": "error", "detail": str(exc), "record": {}}

    rows = payload.get("opportunitiesData", [])
    if not isinstance(rows, list) or not rows:
        return {"status": "empty", "record": {}}
    return {"status": "ok", "record": rows[0]}


def _fetch_public_resource_links(notice_id: str, timeout: int = 30) -> dict[str, Any]:
    if not notice_id:
        return {"status": "missing_identifier", "resources": []}
    request = urllib.request.Request(
        PUBLIC_RESOURCES_URL.format(notice_id=urllib.parse.quote(notice_id)),
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"status": "http_error", "detail": detail[:500], "resources": []}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"status": "error", "detail": str(exc), "resources": []}

    embedded = payload.get("_embedded", {}) if isinstance(payload, dict) else {}
    attachment_groups = embedded.get("opportunityAttachmentList", []) if isinstance(embedded, dict) else []
    resources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for group in attachment_groups if isinstance(attachment_groups, list) else []:
        attachments = group.get("attachments", []) if isinstance(group, dict) else []
        for item in attachments if isinstance(attachments, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resourceId", "") or "").strip()
            if not resource_id:
                continue
            url = PUBLIC_RESOURCE_DOWNLOAD_URL.format(resource_id=urllib.parse.quote(resource_id))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            resources.append(
                {
                    "url": url,
                    "filename": str(item.get("name", "") or "").strip(),
                    "content_type": str(item.get("mimeType", "") or "").strip(),
                    "category": _attachment_category(str(item.get("name", "") or "")),
                    "posted_date": str(item.get("postedDate", "") or "").strip(),
                }
            )
    return {"status": "ok" if resources else "empty", "resources": resources}


def fetch_notice_attachments(
    notice_id: str,
    solicitation_number: str = "",
    resource_links: list[str] | None = None,
    point_of_contact: list[dict[str, Any]] | None = None,
    *,
    max_attachments: int = 20,
) -> dict[str, Any]:
    seeded_resource_links = bool(download_targets := [
        {"url": link.strip(), "filename": "", "content_type": ""}
        for link in (resource_links or [])
        if isinstance(link, str) and link.strip()
    ])
    contacts = [item for item in (point_of_contact or []) if isinstance(item, dict)]
    record: dict[str, Any] = {}
    status = "ok"
    errors: list[str] = []
    record_lookup_status = "skipped"
    resource_listing_status = "skipped"

    if not download_targets:
        public_record_result = _fetch_public_notice_record(notice_id, solicitation_number)
        record = public_record_result.get("record", {})
        status = public_record_result.get("status", "error")
        record_lookup_status = status
        if status == "ok" and isinstance(record, dict):
            contacts = record.get("pointOfContact", []) if isinstance(record.get("pointOfContact"), list) else contacts
            download_targets = [
                {"url": link.strip(), "filename": "", "content_type": ""}
                for link in (record.get("resourceLinks") or [])
                if isinstance(link, str) and link.strip()
            ]
        else:
            errors.append(public_record_result.get("detail", "No public notice record was returned."))

    if not download_targets:
        public_resources_result = _fetch_public_resource_links(notice_id)
        status = public_resources_result.get("status", status)
        resource_listing_status = status
        download_targets = public_resources_result.get("resources", []) if isinstance(public_resources_result.get("resources"), list) else []
        if not download_targets and public_resources_result.get("detail"):
            errors.append(public_resources_result.get("detail"))

    attachments_expected = bool(download_targets)
    attachments: list[dict[str, Any]] = []
    for target in download_targets[:max_attachments]:
        if not isinstance(target, dict):
            continue
        try:
            attachments.append(
                _download_attachment(
                    str(target.get("url", "") or ""),
                    filename_hint=str(target.get("filename", "") or ""),
                    content_type_hint=str(target.get("content_type", "") or ""),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            errors.append(f"{target.get('url', 'unknown')}: {exc}")

    attachments.sort(key=lambda item: (CATEGORY_PRIORITY.get(item.get("category", "other"), 99), item.get("filename", "")))
    return {
        "status": "ok" if attachments else ("error" if errors else status),
        "record": record,
        "point_of_contact": contacts,
        "attachments": attachments,
        "attachments_expected": attachments_expected,
        "record_lookup_status": record_lookup_status,
        "resource_listing_status": resource_listing_status,
        "seeded_resource_links": seeded_resource_links,
        "resource_link_count": len(download_targets),
        "errors": errors,
    }
