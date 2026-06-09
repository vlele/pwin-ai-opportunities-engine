from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.commercial_intel import COMMERCIAL_INTEL_SOURCE_IDS, enrich_capture_context, enrich_scan_records  # type: ignore
from common.evidence_model import evidence_model_scan_notes, merge_evidence_models, normalize_provider_evidence_model  # type: ignore


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    enabled_sources = [
        {
            "id": "govtribe_mcp_commercial_intel",
            "name": "GovTribe MCP Commercial Intelligence",
            "enabled": True,
        },
        {
            "id": "govwin_iq_commercial_intel",
            "name": "GovWin IQ Commercial Intelligence",
            "enabled": True,
        },
    ]
    records = [
        {
            "title": "IRS Case Management Modernization",
            "buyer": "Internal Revenue Service",
            "summary": "Modernize a taxpayer case management platform with cloud-hosted delivery.",
            "match_score": 82,
            "confidence_score": 67,
            "bucket": "action_now",
        }
    ]
    vendor_profile = {
        "company": {
            "name": "Acme Federal",
            "summary": "Cloud modernization and analytics delivery for civilian buyers.",
        },
        "core_competencies": ["cloud modernization", "data analytics"],
        "naics": {"confirmed": ["541512"]},
    }

    failures: list[str] = []

    if COMMERCIAL_INTEL_SOURCE_IDS != {
        "govtribe_mcp_commercial_intel",
        "govwin_iq_commercial_intel",
    }:
        failures.append("commercial_source_ids")

    with patch.dict(os.environ, {}, clear=True):
        scan_result = enrich_scan_records(
            enabled_sources=enabled_sources,
            records=records,
            vendor_profile=vendor_profile,
            preferences={},
        )
        scan_status_by_id = {item["source_id"]: item for item in scan_result.get("source_statuses", [])}
        if scan_status_by_id.get("govtribe_mcp_commercial_intel", {}).get("status") != "not_configured":
            failures.append("govtribe_missing_env_status")
        if scan_status_by_id.get("govwin_iq_commercial_intel", {}).get("status") != "not_configured":
            failures.append("govwin_missing_env_status")
        if records[0].get("commercial_intel"):
            failures.append("scan_should_not_attach_without_configuration")

    normalized_fixture = _load_fixture("govtribe-normalized-evidence.json")
    normalized_model = normalize_provider_evidence_model(
        normalized_fixture,
        source_id="govtribe_mcp_commercial_intel",
        source_name="GovTribe MCP Commercial Intelligence",
        source_url="https://govtribe.com/mcp",
        external_record_id="fixture-001",
    )
    if normalized_model.get("incumbent", {}).get("name") != "Alpha Systems":
        failures.append("normalized_incumbent_name")
    if normalized_model.get("vehicle", {}).get("name") != "CIO-SP3":
        failures.append("normalized_vehicle_name")
    if normalized_model.get("contract_value_or_ceiling", {}).get("amount") != "$24,500,000":
        failures.append("normalized_contract_value")
    if normalized_model.get("teaming_posture", {}).get("recommended_posture") != "Team, do not prime":
        failures.append("normalized_teaming_posture")

    conflict_fixture = _load_fixture("cross-source-conflict.json")
    merged_model = merge_evidence_models(conflict_fixture.get("models", []))
    if merged_model.get("vehicle", {}).get("set_aside") != "Total Small Business Set-Aside":
        failures.append("merge_prefers_sam_set_aside")
    if merged_model.get("incumbent", {}).get("name") != "Alpha Systems":
        failures.append("merge_preserves_incumbent_signal")
    if len(merged_model.get("related_procurements", [])) != 1:
        failures.append("merge_dedupes_related_procurements")
    if not any(item.get("field") == "vehicle.set_aside" for item in merged_model.get("conflicts", [])):
        failures.append("merge_emits_set_aside_conflict")
    scan_notes = evidence_model_scan_notes(merged_model, max_items=4)
    if not any("Acquisition signal" in note for note in scan_notes):
        failures.append("scan_notes_include_acquisition_signal")

    with patch.dict(
        os.environ,
        {
            "GOVWIN_CLIENT_ID": "client-id",
            "GOVWIN_CLIENT_SECRET": "client-secret",
            "GOVWIN_USERNAME": "username",
            "GOVWIN_PASSWORD": "password",
        },
        clear=True,
    ):
        capture_result = enrich_capture_context(
            enabled_sources=enabled_sources,
            resolved={
                "title": "IRS Case Management Modernization",
                "buyer": "Internal Revenue Service",
                "url": "https://sam.gov/example",
                "solicitation_number": "IRS-2026-001",
            },
            notice_context_text="Requirement supports case management modernization and operational reporting.",
            attachment_bundle={"attachments": []},
            vendor_profile=vendor_profile,
            preferences={},
        )
        capture_status_by_id = {item["source_id"]: item for item in capture_result.get("source_statuses", [])}
        if capture_status_by_id.get("govtribe_mcp_commercial_intel", {}).get("status") != "not_configured":
            failures.append("capture_govtribe_missing_env_status")
        if capture_status_by_id.get("govwin_iq_commercial_intel", {}).get("status") != "configured_no_runtime_adapter":
            failures.append("capture_govwin_phase1_status")
        if not any(
            "Phase 1 validates the credential contract" in note
            for match in capture_result.get("matches", [])
            for note in match.get("notes", [])
        ):
            failures.append("capture_govwin_phase1_note")
        if len(capture_result.get("evidence_models", [])) != 2:
            failures.append("capture_returns_shape_stable_evidence_models")

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
