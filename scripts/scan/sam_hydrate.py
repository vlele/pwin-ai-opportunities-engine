from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from common.runtime import USER_AGENT

NOTICE_DESC_URL = "https://api.sam.gov/prod/opportunities/v1/noticedesc"


def hydrate_sam_notice(notice_id: str, timeout: int = 20) -> dict[str, Any]:
    api_key = os.getenv("SAM_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "missing_api_key",
            "notice_id": notice_id,
            "full_desc_loaded": False,
            "summary": "",
        }

    if not notice_id:
        return {
            "status": "missing_notice_id",
            "notice_id": notice_id,
            "full_desc_loaded": False,
            "summary": "",
        }

    query = urllib.parse.urlencode({"noticeid": notice_id, "api_key": api_key})
    request = urllib.request.Request(
        f"{NOTICE_DESC_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "http_error",
            "notice_id": notice_id,
            "code": exc.code,
            "detail": detail[:500],
            "full_desc_loaded": False,
            "summary": "",
        }
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {
            "status": "error",
            "notice_id": notice_id,
            "detail": str(exc),
            "full_desc_loaded": False,
            "summary": "",
        }

    text = ""
    if isinstance(payload, dict):
        for key in ("description", "noticeDesc", "noticeDescription", "summary", "body"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            nested = payload.get("data")
            if isinstance(nested, dict):
                for key in ("description", "noticeDesc", "noticeDescription", "summary", "body"):
                    value = nested.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break

    return {
        "status": "ok" if text else "empty",
        "notice_id": notice_id,
        "payload": payload,
        "full_desc_loaded": bool(text),
        "summary": text,
    }
