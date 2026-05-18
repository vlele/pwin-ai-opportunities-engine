from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

from PyPDF2 import PdfReader
from docx import Document


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


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
    if "sow" in lowered or "statement of work" in lowered or "pws" in lowered:
        return "statement_of_work"
    if "rftop" in lowered or "evaluation" in lowered or "instruction" in lowered:
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


def _extract_pdf_text(data: bytes, max_pages: int = 8) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages[:max_pages]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _extract_docx_text(data: bytes) -> str:
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


def _attachment_snippets(text: str, max_snippets: int = 4) -> list[str]:
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
    request = urllib.request.Request(url, headers={"User-Agent": "pwin-ai-opportunities-v15.2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        filename = filename_hint or _filename_from_headers(url, response.headers)
        content_type = content_type_hint or response.headers.get("Content-Type", "application/octet-stream")
    text, parser_status = _extract_attachment_text(filename, content_type, data)
    return {
        "url": url,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "truncated": truncated,
        "category": _attachment_category(filename),
        "parser_status": parser_status,
        "text_excerpt": _normalize_text(text)[:6000],
        "snippets": _attachment_snippets(text),
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
        headers={"User-Agent": "pwin-ai-opportunities-v15.2"},
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
        headers={"User-Agent": "pwin-ai-opportunities-v15.2"},
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
    download_targets = [
        {"url": link.strip(), "filename": "", "content_type": ""}
        for link in (resource_links or [])
        if isinstance(link, str) and link.strip()
    ]
    contacts = [item for item in (point_of_contact or []) if isinstance(item, dict)]
    record: dict[str, Any] = {}
    status = "ok"
    errors: list[str] = []

    if not download_targets:
        public_record_result = _fetch_public_notice_record(notice_id, solicitation_number)
        record = public_record_result.get("record", {})
        status = public_record_result.get("status", "error")
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
        download_targets = public_resources_result.get("resources", []) if isinstance(public_resources_result.get("resources"), list) else []
        if not download_targets and public_resources_result.get("detail"):
            errors.append(public_resources_result.get("detail"))

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
        "resource_link_count": len(download_targets),
        "errors": errors,
    }
