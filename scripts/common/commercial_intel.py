from __future__ import annotations

import os
from typing import Any, Protocol

from common.evidence_model import (
    empty_evidence_model,
    evidence_model_competitive_notes,
    evidence_model_next_questions,
    evidence_model_related_procurement_lines,
    evidence_model_vehicle_signals,
    normalize_provider_evidence_model,
)
from common.openai_mcp import call_openai_mcp_json
from common.paths import today_local_str


COMMERCIAL_INTEL_SOURCE_IDS = frozenset(
    {
        "govtribe_mcp_commercial_intel",
        "govwin_iq_commercial_intel",
    }
)


def _env_int(name: str, default: int) -> int:
    try:
        return max(int(os.getenv(name, str(default)) or str(default)), 0)
    except Exception:
        return default


def commercial_scan_max_records() -> int:
    return _env_int("PWIN_COMMERCIAL_SCAN_MAX_RECORDS", 3)


def _govtribe_mcp_url() -> str:
    return str(os.getenv("GOVTRIBE_MCP_URL") or "https://govtribe.com/mcp").strip()


def _govtribe_timeout_seconds() -> int:
    return _env_int("GOVTRIBE_MCP_TIMEOUT_SECONDS", 90)


def _govwin_timeout_seconds() -> int:
    return _env_int("GOVWIN_TIMEOUT_SECONDS", 30)


def _govtribe_authorization_token() -> str:
    token = str(os.getenv("GOVTRIBE_MCP_API_KEY") or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _dedupe_strings(items: list[str]) -> list[str]:
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


def _coerce_string_list(value: Any, *, max_items: int = 6) -> list[str]:
    items: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
    elif isinstance(value, str) and value.strip():
        items.append(value.strip())
    return _dedupe_strings(items)[:max_items]


def _clip_text(text: Any, *, max_chars: int) -> str:
    value = str(text or "").strip()
    return value[:max_chars]


def _vendor_name(vendor_profile: dict[str, Any]) -> str:
    company = vendor_profile.get("company")
    if isinstance(company, dict):
        company_name = str(company.get("name") or "").strip()
        if company_name:
            return company_name
    top_level = str(vendor_profile.get("vendor_name") or "").strip()
    return top_level or "Vendor"


def _vendor_brief(vendor_profile: dict[str, Any], preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    naics = vendor_profile.get("naics") if isinstance(vendor_profile.get("naics"), dict) else {}
    hard_filters = preferences.get("hard_filters", {}) if isinstance(preferences, dict) else {}
    return {
        "vendor_name": _vendor_name(vendor_profile),
        "fit_narrative": _clip_text(vendor_profile.get("fit_narrative"), max_chars=1000),
        "company_summary": _clip_text(
            (vendor_profile.get("company") or {}).get("summary")
            if isinstance(vendor_profile.get("company"), dict)
            else "",
            max_chars=1200,
        ),
        "core_competencies": _coerce_string_list(vendor_profile.get("core_competencies"), max_items=8),
        "confirmed_naics": _coerce_string_list((naics or {}).get("confirmed"), max_items=8),
        "candidate_naics": _coerce_string_list((naics or {}).get("candidate"), max_items=8),
        "excluded_opportunity_classes": _coerce_string_list(hard_filters.get("exclude_opportunity_classes"), max_items=8),
    }


def _scan_record_brief(record: dict[str, Any], hydrated_text: str) -> dict[str, Any]:
    return {
        "title": str(record.get("title") or "").strip(),
        "buyer": str(record.get("buyer") or "").strip(),
        "notice_id": str(record.get("notice_id") or "").strip(),
        "solicitation_number": str(record.get("solicitation_number") or "").strip(),
        "naics": str(record.get("naics") or "").strip(),
        "set_aside": str(record.get("set_aside") or "").strip(),
        "url": str(record.get("url") or "").strip(),
        "summary": _clip_text(record.get("summary"), max_chars=2000),
        "hydrated_text": _clip_text(hydrated_text, max_chars=5000),
        "match_score": int(record.get("match_score", 0) or 0),
        "confidence_score": int(record.get("confidence_score", 0) or 0),
        "bucket": str(record.get("bucket") or "").strip(),
    }


def _attachment_manifest(attachment_bundle: dict[str, Any]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for item in (attachment_bundle.get("attachments", []) or [])[:6]:
        if not isinstance(item, dict):
            continue
        manifest.append(
            {
                "category": str(item.get("category") or "").strip(),
                "file_name": str(item.get("file_name") or "").strip(),
                "summary": _clip_text(item.get("summary") or item.get("text"), max_chars=300),
            }
        )
    return manifest


def _capture_context_brief(
    resolved: dict[str, Any],
    notice_context_text: str,
    attachment_bundle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": str(resolved.get("title") or "").strip(),
        "buyer": str(resolved.get("buyer") or "").strip(),
        "solicitation_number": str(resolved.get("solicitation_number") or "").strip(),
        "notice_id": str(resolved.get("notice_id") or "").strip(),
        "url": str(resolved.get("url") or "").strip(),
        "notice_context_text": _clip_text(notice_context_text, max_chars=10000),
        "attachments": _attachment_manifest(attachment_bundle),
    }


def _source_log_entry(
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


def _dedupe_source_log(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _normalize_source_log(source_name: str, value: Any, default_url: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, list):
        for raw_item in value[:4]:
            if not isinstance(raw_item, dict):
                continue
            items.append(
                _source_log_entry(
                    title=str(raw_item.get("title") or raw_item.get("name") or source_name).strip(),
                    url=str(raw_item.get("url") or default_url).strip(),
                    publisher=str(raw_item.get("publisher") or source_name).strip(),
                    relevance=str(raw_item.get("relevance") or raw_item.get("summary") or "Commercial intelligence enrichment").strip(),
                    confidence=int(raw_item.get("confidence", 2) or 2),
                    tier=int(raw_item.get("tier", 4) or 4),
                )
            )
    return _dedupe_source_log(items)


def _default_result(source_id: str, source_name: str, status: str, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": source_name,
        "status": status,
        "matched": False,
        "matched_by": "",
        "confidence": "unknown",
        "external_record_id": "",
        "source_url": "",
        "notes": _dedupe_strings(notes or []),
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


def _govtribe_prompt(mode: str) -> str:
    return (
        "You are a federal capture analyst using the GovTribe MCP server as a read-only commercial-intelligence source. "
        "Use the GovTribe MCP tools before answering. For exact identifiers, solicitation numbers, notice IDs, vendor names, "
        "and exact titles, prefer keyword search. For adjacent procurements, incumbent discovery, or conceptually similar work, "
        "use semantic search. Keep agencies, vendors, dates, categories, and structured constraints in tool arguments instead of "
        "field:value query text. Return only compact JSON with fields matched, matched_by, confidence, external_record_id, "
        "source_url, notes, source_log, and enrichment. The enrichment object must include summary, evidence_model, "
        "competitive_landscape, vehicle_signals, related_procurements, and next_questions. The evidence_model object must include "
        "incumbent, vehicle, recompete_clues, related_procurements, contract_value_or_ceiling, teaming_posture, next_questions, "
        "and evidence_gaps. "
        + mode
    )


def _normalize_govtribe_result(source_config: dict[str, Any], lookup_result: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source_config.get("id") or "govtribe_mcp_commercial_intel").strip()
    source_name = str(source_config.get("name") or "GovTribe MCP Commercial Intelligence").strip()
    default_url = str(source_config.get("homepage") or _govtribe_mcp_url()).strip()
    lookup_status = str(lookup_result.get("status") or "error").strip()

    if lookup_status != "ok":
        message = str(lookup_result.get("error") or lookup_status).strip()
        notes = [message] if message else []
        return _default_result(source_id, source_name, lookup_status, notes=notes)

    parsed = lookup_result.get("parsed")
    if not isinstance(parsed, dict):
        return _default_result(source_id, source_name, "invalid_output_json", notes=["GovTribe returned no parseable JSON payload."])

    tool_used = bool(lookup_result.get("mcp_activity"))
    source_url = str(parsed.get("source_url") or "").strip()
    source_log = _normalize_source_log(source_name, parsed.get("source_log"), source_url or default_url)
    matched = bool(parsed.get("matched"))
    matched_by = str(parsed.get("matched_by") or "").strip()
    enrichment_value = parsed.get("enrichment") if isinstance(parsed.get("enrichment"), dict) else {}
    summary = str(
        enrichment_value.get("summary")
        if isinstance(enrichment_value, dict)
        else parsed.get("summary") or ""
    ).strip()

    if not source_log and (source_url or matched or summary):
        source_log = [
            _source_log_entry(
                title=source_name,
                url=source_url or default_url,
                publisher="GovTribe",
                relevance=matched_by or summary or "Commercial intelligence enrichment",
                confidence=2 if matched else 1,
            )
        ]

    evidence_model = normalize_provider_evidence_model(
        enrichment_value.get("evidence_model") or enrichment_value.get("normalized_evidence") or enrichment_value,
        source_id=source_id,
        source_name=source_name,
        source_url=source_url or default_url,
        external_record_id=str(parsed.get("external_record_id") or "").strip(),
    )
    if not summary:
        summary = str(evidence_model.get("summary") or "").strip()
    competitive_landscape = _dedupe_strings(
        evidence_model_competitive_notes(evidence_model, max_items=6)
        + _coerce_string_list(enrichment_value.get("competitive_landscape"), max_items=6)
    )[:6]
    vehicle_signals = _dedupe_strings(
        evidence_model_vehicle_signals(evidence_model, max_items=6)
        + _coerce_string_list(enrichment_value.get("vehicle_signals"), max_items=6)
    )[:6]
    related_procurements = _dedupe_strings(
        evidence_model_related_procurement_lines(evidence_model, max_items=6)
        + _coerce_string_list(enrichment_value.get("related_procurements"), max_items=6)
    )[:6]
    next_questions = _dedupe_strings(
        evidence_model_next_questions(evidence_model, max_items=6)
        + _coerce_string_list(enrichment_value.get("next_questions"), max_items=6)
    )[:6]
    notes = _dedupe_strings(
        _coerce_string_list(parsed.get("notes"), max_items=6)
        + ([matched_by] if matched_by else [])
        + ([] if tool_used else ["GovTribe response did not report MCP tool activity."])
    )
    status = "ok" if tool_used else "tool_not_used"
    if tool_used and not matched:
        status = "no_match"

    result = {
        "source_id": source_id,
        "source_name": source_name,
        "status": status,
        "matched": matched,
        "matched_by": matched_by,
        "confidence": str(parsed.get("confidence") or "unknown").strip() or "unknown",
        "external_record_id": str(parsed.get("external_record_id") or "").strip(),
        "source_url": source_url,
        "notes": notes,
        "source_log": source_log,
        "enrichment": {
            "summary": summary,
            "competitive_landscape": competitive_landscape,
            "vehicle_signals": vehicle_signals,
            "related_procurements": related_procurements,
            "next_questions": next_questions,
            "evidence_model": evidence_model,
        },
    }
    response_id = str(lookup_result.get("response_id") or "").strip()
    if response_id:
        result["response_id"] = response_id
    return result


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


class GovTribeMCPCommercialIntelProvider:
    source_id = "govtribe_mcp_commercial_intel"
    source_name = "GovTribe MCP Commercial Intelligence"

    def __init__(self, source_config: dict[str, Any]):
        self.source_config = source_config

    def is_configured(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if not str(os.getenv("OPENAI_API_KEY") or "").strip():
            missing.append("OPENAI_API_KEY")
        if not _govtribe_authorization_token():
            missing.append("GOVTRIBE_MCP_API_KEY")
        return not missing, missing

    def enrich_scan(
        self,
        *,
        record: dict[str, Any],
        hydrated_text: str,
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return _default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )

        lookup_result = call_openai_mcp_json(
            developer_prompt=_govtribe_prompt(
                "If GovTribe has no useful corroboration, set matched to false, keep lists short, and do not invent IDs or URLs."
            ),
            user_payload={
                "mode": "scan_enrichment",
                "vendor": _vendor_brief(vendor_profile, preferences),
                "opportunity": _scan_record_brief(record, hydrated_text),
            },
            server_label="govtribe",
            server_url=_govtribe_mcp_url(),
            authorization_token=_govtribe_authorization_token(),
            timeout_seconds=_govtribe_timeout_seconds(),
        )
        return _normalize_govtribe_result(self.source_config, lookup_result)

    def enrich_capture(
        self,
        *,
        resolved: dict[str, Any],
        notice_context_text: str,
        attachment_bundle: dict[str, Any],
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return _default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )

        lookup_result = call_openai_mcp_json(
            developer_prompt=_govtribe_prompt(
                "Focus on incumbent clues, vehicle path, set-aside posture, related procurements, recompete clues, contract value or ceiling if visible, "
                "recommended teaming posture, and the next research questions that the capture team should validate."
            ),
            user_payload={
                "mode": "capture_enrichment",
                "vendor": _vendor_brief(vendor_profile, preferences),
                "opportunity": _capture_context_brief(resolved, notice_context_text, attachment_bundle),
            },
            server_label="govtribe",
            server_url=_govtribe_mcp_url(),
            authorization_token=_govtribe_authorization_token(),
            timeout_seconds=_govtribe_timeout_seconds(),
        )
        return _normalize_govtribe_result(self.source_config, lookup_result)


class GovWinIQCommercialIntelProvider:
    source_id = "govwin_iq_commercial_intel"
    source_name = "GovWin IQ Commercial Intelligence"

    def __init__(self, source_config: dict[str, Any]):
        self.source_config = source_config

    def is_configured(self) -> tuple[bool, list[str]]:
        required = [
            "GOVWIN_CLIENT_ID",
            "GOVWIN_CLIENT_SECRET",
            "GOVWIN_USERNAME",
            "GOVWIN_PASSWORD",
        ]
        missing = [name for name in required if not str(os.getenv(name) or "").strip()]
        return not missing, missing

    def _phase1_result(self) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return _default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )
        return _default_result(
            self.source_id,
            self.source_name,
            "configured_no_runtime_adapter",
            notes=[
                "GovWin Phase 1 validates the credential contract and source-registry entry only.",
                f"GovWin timeout setting available: {_govwin_timeout_seconds()} seconds.",
            ],
        )

    def enrich_scan(
        self,
        *,
        record: dict[str, Any],
        hydrated_text: str,
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        return self._phase1_result()

    def enrich_capture(
        self,
        *,
        resolved: dict[str, Any],
        notice_context_text: str,
        attachment_bundle: dict[str, Any],
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._phase1_result()


def _provider_for_source(source: dict[str, Any]) -> CommercialIntelProvider | None:
    source_id = str(source.get("id") or "").strip()
    if source_id == "govtribe_mcp_commercial_intel":
        return GovTribeMCPCommercialIntelProvider(source)
    if source_id == "govwin_iq_commercial_intel":
        return GovWinIQCommercialIntelProvider(source)
    return None


def _configured_commercial_sources(enabled_sources: list[dict[str, Any]]) -> list[CommercialIntelProvider]:
    providers: list[CommercialIntelProvider] = []
    for source in enabled_sources:
        if source.get("id") not in COMMERCIAL_INTEL_SOURCE_IDS:
            continue
        provider = _provider_for_source(source)
        if provider is not None:
            providers.append(provider)
    return providers


def _eligible_scan_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [
        record
        for record in records
        if str(record.get("bucket") or "").strip().lower() not in {"suppressed"}
    ]
    return sorted(
        eligible,
        key=lambda item: (
            int(item.get("match_score", 0) or 0),
            int(item.get("confidence_score", 0) or 0),
        ),
        reverse=True,
    )


def _attach_scan_result(record: dict[str, Any], result: dict[str, Any]) -> None:
    section = record.setdefault("commercial_intel", {})
    matches = section.setdefault("matches", [])
    matches.append(result)
    evidence_models = section.setdefault("evidence_models", [])
    enrichment = result.get("enrichment") if isinstance(result.get("enrichment"), dict) else {}
    if isinstance(enrichment.get("evidence_model"), dict):
        evidence_models.append(enrichment.get("evidence_model"))
    section["enabled_source_ids"] = _dedupe_strings(
        [*section.get("enabled_source_ids", []), str(result.get("source_id") or "").strip()]
    )
    section["notes"] = _dedupe_strings(
        section.get("notes", [])
        + (
            [f'{result.get("source_name")}: {result.get("matched_by")}'.strip(": ")]
            if result.get("matched")
            else _coerce_string_list(result.get("notes"), max_items=2)
        )
    )
    section["source_log"] = _dedupe_source_log(
        [*(section.get("source_log", []) or []), *(result.get("source_log", []) or [])]
    )
    record["commercial_intel_notes"] = section.get("notes", [])


def _scan_status_from_results(source_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(results)
    matched_count = sum(1 for result in results if result.get("matched"))
    error_count = sum(
        1
        for result in results
        if str(result.get("status") or "").strip() in {"error", "http_error", "invalid_output_json", "tool_not_used"}
    )
    statuses = {str(result.get("status") or "").strip() for result in results}
    notes = _dedupe_strings(
        [f"Commercial enrichment attempted on {attempted} scan record(s)."]
        + [note for result in results for note in _coerce_string_list(result.get("notes"), max_items=2)]
    )
    if not results:
        status = "skipped"
    elif statuses == {"no_match"}:
        status = "ok"
    elif "configured_no_runtime_adapter" in statuses:
        status = "configured_no_runtime_adapter"
    elif "not_configured" in statuses:
        status = "not_configured"
    elif error_count and matched_count:
        status = "partial_error"
    elif error_count:
        status = "error"
    else:
        status = "ok"
    return {
        "source_id": source_id,
        "status": status,
        "record_count": matched_count,
        "attempted_record_count": attempted,
        "error_count": error_count,
        "notes": notes,
    }


def _capture_status_from_result(result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "unknown").strip()
    return {
        "source_id": str(result.get("source_id") or "").strip(),
        "status": status,
        "record_count": 1 if result.get("matched") else 0,
        "notes": _coerce_string_list(result.get("notes"), max_items=4),
    }


def enrich_scan_records(
    *,
    enabled_sources: list[dict[str, Any]],
    records: list[dict[str, Any]],
    vendor_profile: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, Any]:
    providers = _configured_commercial_sources(enabled_sources)
    if not providers:
        return {
            "source_statuses": [],
            "source_issues": [],
        }

    ranked_records = _eligible_scan_records(records)
    ranked_records = ranked_records[: commercial_scan_max_records()]
    source_statuses: list[dict[str, Any]] = []
    source_issues: list[str] = []

    for provider in providers:
        if isinstance(provider, GovWinIQCommercialIntelProvider):
            result = provider.enrich_scan(
                record={},
                hydrated_text="",
                vendor_profile=vendor_profile,
                preferences=preferences,
            )
            source_statuses.append(_capture_status_from_result(result))
            continue

        configured, missing = provider.is_configured()
        if not configured:
            source_statuses.append(
                {
                    "source_id": provider.source_id,
                    "status": "not_configured",
                    "record_count": 0,
                    "attempted_record_count": 0,
                    "error_count": 0,
                    "notes": [f"Missing env vars: {', '.join(missing)}"],
                }
            )
            continue

        if not ranked_records:
            source_statuses.append(
                {
                    "source_id": provider.source_id,
                    "status": "skipped",
                    "record_count": 0,
                    "attempted_record_count": 0,
                    "error_count": 0,
                    "notes": ["No eligible scan records were available for commercial enrichment."],
                }
            )
            continue

        provider_results: list[dict[str, Any]] = []
        for record in ranked_records:
            result = provider.enrich_scan(
                record=record,
                hydrated_text=str(record.get("summary") or ""),
                vendor_profile=vendor_profile,
                preferences=preferences,
            )
            provider_results.append(result)
            _attach_scan_result(record, result)
            if str(result.get("status") or "").strip() in {"error", "http_error", "invalid_output_json"}:
                source_issues.append(
                    f'{provider.source_name}: {", ".join(_coerce_string_list(result.get("notes"), max_items=2)) or result.get("status", "error")}'
                )

        source_statuses.append(_scan_status_from_results(provider.source_id, provider_results))

    return {
        "source_statuses": source_statuses,
        "source_issues": source_issues,
    }


def enrich_capture_context(
    *,
    enabled_sources: list[dict[str, Any]],
    resolved: dict[str, Any],
    notice_context_text: str,
    attachment_bundle: dict[str, Any],
    vendor_profile: dict[str, Any],
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    providers = _configured_commercial_sources(enabled_sources)
    if not providers:
        return {
            "matches": [],
            "evidence_models": [],
            "source_statuses": [],
            "source_log": [],
            "competitive_landscape": [],
            "vehicle_signals": [],
            "related_procurements": [],
            "next_questions": [],
            "issues": [],
        }

    matches: list[dict[str, Any]] = []
    evidence_models: list[dict[str, Any]] = []
    source_statuses: list[dict[str, Any]] = []
    source_log: list[dict[str, Any]] = []
    competitive_landscape: list[str] = []
    vehicle_signals: list[str] = []
    related_procurements: list[str] = []
    next_questions: list[str] = []
    issues: list[str] = []

    for provider in providers:
        result = provider.enrich_capture(
            resolved=resolved,
            notice_context_text=notice_context_text,
            attachment_bundle=attachment_bundle,
            vendor_profile=vendor_profile,
            preferences=preferences,
        )
        matches.append(result)
        enrichment = result.get("enrichment") if isinstance(result.get("enrichment"), dict) else {}
        if isinstance(enrichment.get("evidence_model"), dict):
            evidence_models.append(enrichment.get("evidence_model"))
        source_statuses.append(_capture_status_from_result(result))
        source_log.extend(result.get("source_log", []) or [])
        competitive_landscape.extend(_coerce_string_list(enrichment.get("competitive_landscape"), max_items=6))
        vehicle_signals.extend(_coerce_string_list(enrichment.get("vehicle_signals"), max_items=6))
        related_procurements.extend(_coerce_string_list(enrichment.get("related_procurements"), max_items=6))
        next_questions.extend(_coerce_string_list(enrichment.get("next_questions"), max_items=6))
        if str(result.get("status") or "").strip() in {"error", "http_error", "invalid_output_json"}:
            issues.append(
                f'{provider.source_name}: {", ".join(_coerce_string_list(result.get("notes"), max_items=2)) or result.get("status", "error")}'
            )

    return {
        "matches": matches,
        "evidence_models": evidence_models,
        "source_statuses": source_statuses,
        "source_log": _dedupe_source_log(source_log),
        "competitive_landscape": _dedupe_strings(competitive_landscape),
        "vehicle_signals": _dedupe_strings(vehicle_signals),
        "related_procurements": _dedupe_strings(related_procurements),
        "next_questions": _dedupe_strings(next_questions),
        "issues": _dedupe_strings(issues),
    }
