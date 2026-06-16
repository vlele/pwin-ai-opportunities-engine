from __future__ import annotations

from typing import Any, Protocol

from common.evidence_model import empty_evidence_model
from common.paths import today_local_str


PROVIDER_STATUSES = frozenset(
    {
        "not_configured",
        "tool_contract_unavailable",
        "no_match",
        "ok",
        "partial_error",
        "error",
    }
)


class CommercialIntelProvider(Protocol):
    source_id: str
    source_name: str

    def is_configured(self) -> tuple[bool, list[str]]:
        ...

    def enrich_scan(
        self,
        *,
        record: dict[str, Any],
        hydrated_text: str,
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def enrich_capture(
        self,
        *,
        resolved: dict[str, Any],
        notice_context_text: str,
        attachment_bundle: dict[str, Any],
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


def env_int(name: str, default: int) -> int:
    import os

    try:
        return max(int(os.getenv(name, str(default)) or str(default)), 0)
    except Exception:
        return default


def dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def coerce_string_list(value: Any, *, max_items: int = 6) -> list[str]:
    items: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
    elif isinstance(value, str) and value.strip():
        items.append(value.strip())
    return dedupe_strings(items)[:max_items]


def clip_text(text: Any, *, max_chars: int) -> str:
    value = str(text or "").strip()
    return value[:max_chars]


def source_log_entry(
    *,
    title: str,
    url: str,
    publisher: str,
    relevance: str,
    confidence: int,
    tier: int = 4,
) -> dict[str, Any]:
    return {
        "title": title or publisher,
        "url": url,
        "publisher": publisher,
        "published_date": "N/A",
        "accessed_date": today_local_str(),
        "tier": tier,
        "relevance": relevance or "Commercial intelligence enrichment",
        "confidence": max(1, min(int(confidence or 1), 3)),
    }


def dedupe_source_log(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (
            str(item.get("title") or "").strip().lower(),
            str(item.get("url") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def default_result(source_id: str, source_name: str, status: str, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": source_name,
        "status": status,
        "matched": False,
        "matched_by": "",
        "confidence": "unknown",
        "external_record_id": "",
        "source_url": "",
        "notes": dedupe_strings(notes or []),
        "source_log": [],
        "enrichment": {
            "summary": "",
            "competitive_landscape": [],
            "vehicle_signals": [],
            "related_procurements": [],
            "next_questions": [],
            "evidence_model": empty_evidence_model(source_id=source_id, source_name=source_name),
        },
    }
