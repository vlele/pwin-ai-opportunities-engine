from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from common.runtime import USER_AGENT


MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_GOVTRIBE_MCP_URL = "https://govtribe.com/mcp"


class MCPHTTPError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class MCPResponseError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


def clean_bearer_token(value: str) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _header_value(headers: Any, name: str) -> str:
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value:
            return str(value).strip()
        lower = name.lower()
        for key in getattr(headers, "keys", lambda: [])():
            if str(key).lower() == lower:
                return str(headers.get(key) or "").strip()
    return ""


def _json_rpc_request(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return payload


def _json_rpc_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return payload


def _parse_sse_messages(raw_text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        data = "\n".join(data_lines).strip()
        data_lines.clear()
        if not data or data == "[DONE]":
            return
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            messages.append(parsed)

    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return messages


def _parse_response_body(raw_text: str, content_type: str) -> list[dict[str, Any]]:
    if "text/event-stream" in content_type.lower():
        return _parse_sse_messages(raw_text)
    if not raw_text.strip():
        return []
    parsed = json.loads(raw_text)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


@dataclass
class MCPHttpClient:
    url: str = DEFAULT_GOVTRIBE_MCP_URL
    bearer_token: str = ""
    timeout_seconds: int = 90
    urlopen: Callable[..., Any] = urllib.request.urlopen
    user_agent: str = USER_AGENT

    def __post_init__(self) -> None:
        self.url = str(self.url or DEFAULT_GOVTRIBE_MCP_URL).strip()
        self.bearer_token = clean_bearer_token(self.bearer_token)
        self.timeout_seconds = max(int(self.timeout_seconds or 0), 5)
        self.session_id = ""
        self.protocol_version = MCP_PROTOCOL_VERSION
        self._next_id = 1
        self._initialized = False

    def _headers(self, *, is_notification: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self.protocol_version or MCP_PROTOCOL_VERSION,
            "User-Agent": self.user_agent,
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if is_notification:
            headers["Accept"] = "application/json, text/event-stream"
        return headers

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _post(self, payload: dict[str, Any], *, expected_id: int | None = None) -> dict[str, Any] | None:
        is_notification = "id" not in payload
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers=self._headers(is_notification=is_notification),
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
                content_type = _header_value(response.headers, "Content-Type")
                session_id = _header_value(response.headers, "Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPHTTPError(
                f"MCP HTTP {exc.code}",
                status_code=exc.code,
                detail=detail[:1200],
            ) from exc
        except Exception as exc:
            raise MCPHTTPError(f"MCP request failed: {exc}") from exc

        messages = _parse_response_body(raw_text, content_type)
        if is_notification:
            return None

        selected: dict[str, Any] | None = None
        for message in messages:
            if expected_id is None or message.get("id") == expected_id:
                selected = message
                break
        if selected is None and messages:
            selected = messages[-1]
        if selected is None:
            raise MCPResponseError("MCP response did not include a JSON-RPC message.")

        error = selected.get("error")
        if isinstance(error, dict):
            raise MCPResponseError(
                str(error.get("message") or "MCP JSON-RPC error"),
                code=error.get("code") if isinstance(error.get("code"), int) else None,
                data=error.get("data"),
            )
        result = selected.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def initialize(self) -> dict[str, Any]:
        request_id = self._request_id()
        result = self._post(
            _json_rpc_request(
                request_id,
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "pwin-ai-opportunities",
                        "title": "pWin AI Opportunities",
                        "version": "1.0.0",
                    },
                },
            ),
            expected_id=request_id,
        )
        if isinstance(result, dict):
            protocol_version = str(result.get("protocolVersion") or "").strip()
            if protocol_version:
                self.protocol_version = protocol_version
        return result or {}

    def initialized(self) -> None:
        self._post(_json_rpc_notification("notifications/initialized"))
        self._initialized = True

    def connect(self) -> dict[str, Any]:
        result = self.initialize()
        self.initialized()
        return result

    def ensure_initialized(self) -> None:
        if not self._initialized:
            self.connect()

    def list_tools(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        request_id = self._request_id()
        result = self._post(_json_rpc_request(request_id, "tools/list", {}), expected_id=request_id)
        tools = result.get("tools") if isinstance(result, dict) else []
        return [item for item in tools if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_initialized()
        request_id = self._request_id()
        result = self._post(
            _json_rpc_request(
                request_id,
                "tools/call",
                {
                    "name": name,
                    "arguments": arguments or {},
                },
            ),
            expected_id=request_id,
        )
        return result or {}
