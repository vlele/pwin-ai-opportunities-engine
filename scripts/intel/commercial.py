from __future__ import annotations

from typing import Any

from intel.providers.base import (
    CommercialIntelProvider,
    coerce_string_list,
    dedupe_source_log,
    dedupe_strings,
    env_int,
)
from intel.providers.govtribe_mcp import GovTribeMCPCommercialIntelProvider
from intel.providers.govwin_iq import GovWinIQCommercialIntelProvider


COMMERCIAL_INTEL_SOURCE_IDS = frozenset(
    {
        "govtribe_mcp_commercial_intel",
        "govwin_iq_commercial_intel",
    }
)


def commercial_scan_max_records() -> int:
    return env_int("PWIN_COMMERCIAL_SCAN_MAX_RECORDS", 3)


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
    section["enabled_source_ids"] = dedupe_strings(
        [*section.get("enabled_source_ids", []), str(result.get("source_id") or "").strip()]
    )
    section["notes"] = dedupe_strings(
        section.get("notes", [])
        + (
            [f'{result.get("source_name")}: {result.get("matched_by")}'.strip(": ")]
            if result.get("matched")
            else coerce_string_list(result.get("notes"), max_items=2)
        )
    )
    section["source_log"] = dedupe_source_log(
        [*(section.get("source_log", []) or []), *(result.get("source_log", []) or [])]
    )
    record["commercial_intel_notes"] = section.get("notes", [])


def _scan_status_from_results(source_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(results)
    matched_count = sum(1 for result in results if result.get("matched"))
    error_count = sum(
        1
        for result in results
        if str(result.get("status") or "").strip() in {"error", "http_error", "invalid_output_json", "partial_error"}
    )
    statuses = {str(result.get("status") or "").strip() for result in results}
    notes = dedupe_strings(
        [f"Commercial enrichment attempted on {attempted} scan record(s)."]
        + [note for result in results for note in coerce_string_list(result.get("notes"), max_items=2)]
    )
    if not results:
        status = "skipped"
    elif statuses == {"no_match"}:
        status = "ok"
    elif "configured_no_runtime_adapter" in statuses:
        status = "configured_no_runtime_adapter"
    elif "not_configured" in statuses:
        status = "not_configured"
    elif "tool_contract_unavailable" in statuses:
        status = "tool_contract_unavailable"
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
        "notes": coerce_string_list(result.get("notes"), max_items=4),
    }


def _status_is_issue(status: str) -> bool:
    return status in {"error", "http_error", "invalid_output_json"}


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
            if _status_is_issue(str(result.get("status") or "").strip()):
                source_issues.append(
                    f'{provider.source_name}: {", ".join(coerce_string_list(result.get("notes"), max_items=2)) or result.get("status", "error")}'
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
        competitive_landscape.extend(coerce_string_list(enrichment.get("competitive_landscape"), max_items=6))
        vehicle_signals.extend(coerce_string_list(enrichment.get("vehicle_signals"), max_items=6))
        related_procurements.extend(coerce_string_list(enrichment.get("related_procurements"), max_items=6))
        next_questions.extend(coerce_string_list(enrichment.get("next_questions"), max_items=6))
        if _status_is_issue(str(result.get("status") or "").strip()):
            issues.append(
                f'{provider.source_name}: {", ".join(coerce_string_list(result.get("notes"), max_items=2)) or result.get("status", "error")}'
            )

    return {
        "matches": matches,
        "evidence_models": evidence_models,
        "source_statuses": source_statuses,
        "source_log": dedupe_source_log(source_log),
        "competitive_landscape": dedupe_strings(competitive_landscape),
        "vehicle_signals": dedupe_strings(vehicle_signals),
        "related_procurements": dedupe_strings(related_procurements),
        "next_questions": dedupe_strings(next_questions),
        "issues": dedupe_strings(issues),
    }
