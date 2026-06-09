from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_OPENAI_RESPONSES_URL = (
    (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/responses"
)
DEFAULT_COMMERCIAL_INTEL_MODEL = os.getenv("PWIN_COMMERCIAL_INTEL_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5-mini"


def _response_input_message(role: str, text: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [
            {
                "type": "input_text",
                "text": text,
            }
        ],
    }


def _strip_json_fence(text: str) -> str:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    return candidate


def _extract_output_text(payload: dict[str, Any]) -> str:
    top_level = payload.get("output_text")
    if isinstance(top_level, str) and top_level.strip():
        return top_level.strip()

    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            content_type = str(content.get("type") or "").strip().lower()
            if content_type in {"output_text", "text"}:
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _extract_mcp_activity(payload: dict[str, Any]) -> list[str]:
    activity: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if "mcp" in item_type.lower():
            activity.append(item_type)
    return activity


def call_openai_mcp_json(
    *,
    developer_prompt: str,
    user_payload: dict[str, Any],
    server_label: str,
    server_url: str,
    authorization_token: str,
    model: str | None = None,
    timeout_seconds: int = 30,
    require_approval: str = "never",
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "status": "missing_openai_api_key",
            "parsed": None,
            "output_text": "",
            "mcp_activity": [],
        }

    request_body = {
        "model": model or DEFAULT_COMMERCIAL_INTEL_MODEL,
        "input": [
            _response_input_message("developer", developer_prompt),
            _response_input_message("user", json.dumps(user_payload, ensure_ascii=True)),
        ],
        "tools": [
            {
                "type": "mcp",
                "server_label": server_label,
                "server_url": server_url,
                "authorization": authorization_token,
                "require_approval": require_approval,
            }
        ],
    }

    request = urllib.request.Request(
        DEFAULT_OPENAI_RESPONSES_URL,
        data=json.dumps(request_body, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=max(int(timeout_seconds or 0), 5)) as response:
            raw_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "http_error",
            "http_status": exc.code,
            "error": detail[:1200],
            "parsed": None,
            "output_text": "",
            "mcp_activity": [],
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "parsed": None,
            "output_text": "",
            "mcp_activity": [],
        }

    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        return {
            "status": "invalid_response_json",
            "error": str(exc),
            "parsed": None,
            "output_text": "",
            "mcp_activity": [],
        }

    output_text = _strip_json_fence(_extract_output_text(payload))
    parsed: dict[str, Any] | None = None
    if output_text:
        try:
            maybe_json = json.loads(output_text)
            if isinstance(maybe_json, dict):
                parsed = maybe_json
        except Exception:
            parsed = None

    status = "ok" if isinstance(parsed, dict) else "invalid_output_json"
    return {
        "status": status,
        "parsed": parsed,
        "output_text": output_text,
        "mcp_activity": _extract_mcp_activity(payload),
        "response_id": str(payload.get("id") or "").strip(),
    }
