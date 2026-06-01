from __future__ import annotations

import io
import json
import mimetypes
import os
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
    from docx import Document
except ImportError:  # pragma: no cover - optional dependency
    Document = None
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
PREFERRED_SECTION_STARTS = (
    ("1.3 Scope", ("1.4", "1.5", "2.0")),
    ("1.5 General Requirements", ("2.0",)),
    ("2.0 Period of Performance", ("3.0", "4.0", "5.0")),
    ("5.0 Deliverables", ("6.0",)),
)


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def _preferred_pdf_section_excerpt(text: str, max_chars: int = 12000) -> str:
    lines = [line.strip() for line in _normalize_preserve_lines(text, max_chars=30000).splitlines() if line.strip()]
    if not lines:
        return ""
    sections: list[str] = []
    lowered_lines = [line.lower() for line in lines]
    for start_label, stop_prefixes in PREFERRED_SECTION_STARTS:
        start_lower = start_label.lower()
        try:
            start_index = next(index for index, line in enumerate(lowered_lines) if line.startswith(start_lower))
        except StopIteration:
            continue
        captured: list[str] = [lines[start_index]]
        for line in lines[start_index + 1:]:
            lower = line.lower()
            if _is_toc_like_line(line):
                continue
            if any(lower.startswith(prefix.lower()) for prefix in stop_prefixes):
                break
            if SECTION_HEADING_RE.match(line) and not any(token in lower for token in ("shall", "must", "provide", "deliver", "maintain", "report", "support")):
                break
            captured.append(line)
            if len(" ".join(captured)) >= 1800:
                break
        block = "\n".join(captured).strip()
        if len(block) >= 80:
            sections.append(block)
    return "\n\n".join(sections)[:max_chars]


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
    lowered = filename.lower()
    if (
        "sow" in lowered
        or "statement of work" in lowered
        or "performance work statement" in lowered
        or "draft pws" in lowered
        or "pws" in lowered
        or "soo" in lowered
        or "statement of objectives" in lowered
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
    if lowered.endswith(".pdf") and ("rfp" in lowered or "solicitation" in lowered):
        return "solicitation"
    return "other"


def _extract_pdf_text(data: bytes, max_pages: int = 18) -> str:
    if PdfReader is None:
        raise RuntimeError("PyPDF2 unavailable")
    reader = PdfReader(io.BytesIO(data))
    page_texts: list[str] = []
    for page in reader.pages[:max_pages]:
        page_texts.append(page.extract_text() or "")
    filtered_pages = [page for page in page_texts if not _page_is_toc_like(page)]
    combined = "\n".join(filtered_pages or page_texts)
    preferred = _preferred_pdf_section_excerpt(combined, max_chars=12000)
    if preferred:
        return f"{preferred}\n\n{combined}"
    return combined


def _extract_docx_text(data: bytes) -> str:
    if Document is None:
        raise RuntimeError("python-docx unavailable")
    document = Document(io.BytesIO(data))
    values = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(values)


def _extract_xlsx_text(data: bytes, max_strings: int = 120) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        sheet_names: list[str] = []
        shared_strings: list[str] = []
        if "xl/workbook.xml" in names:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet_names = [node.attrib.get("name", "") for node in workbook.findall(".//main:sheets/main:sheet", ns)]
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
    max_bytes: int = 8_000_000,
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
    structured_excerpt = _normalize_preserve_lines(text, max_chars=24000)
    record = {
        "url": url,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "truncated": truncated,
        "category": _attachment_category(filename),
        "parser_status": parser_status,
        "text_excerpt": structured_excerpt[:12000],
        "structured_text_excerpt": structured_excerpt,
        "snippets": _attachment_snippets(text),
    }
    if local_path:
        record["local_path"] = local_path
    return record


def load_local_attachments(
    file_paths: list[str] | None,
    *,
    max_attachments: int = 20,
    max_bytes: int = 8_000_000,
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
