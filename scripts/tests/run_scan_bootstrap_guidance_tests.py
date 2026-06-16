from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scan.sam_search import search_sam_opportunities  # type: ignore
from scan import run_scan  # type: ignore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _template_registry() -> dict:
    return json.loads((Path(__file__).resolve().parents[2] / "templates" / "source-registry.template.json").read_text(encoding="utf-8"))


def _write_workspace(workspace: Path, *, govtribe_enabled: bool = False, govtribe_retrieval: bool = False) -> None:
    procurement = workspace / "procurement"
    procurement.mkdir(parents=True, exist_ok=True)
    _write_json(
        procurement / "vendor-profile.json",
        {
            "company": {
                "name": "Acme Federal",
                "website": "https://example.com",
                "summary": "Cloud modernization and case management delivery for civilian agencies.",
            },
            "core_competencies": ["case management modernization", "data analytics"],
            "fit_narrative": "Prioritize case management modernization and cloud delivery.",
            "naics": {"confirmed": ["541512"], "candidates": ["541519"]},
        },
    )
    registry = _template_registry()
    for source in registry.get("sources", []):
        if source.get("id") == "govtribe_mcp_commercial_intel":
            source["enabled"] = govtribe_enabled
            source.setdefault("provider_options", {})["allow_scan_retrieval_without_sam"] = govtribe_retrieval
    _write_json(procurement / "source-registry.json", registry)


def _run_scan_main(workspace: Path) -> dict:
    stdout = StringIO()
    with patch.object(
        sys,
        "argv",
        [
            "run_scan.py",
            "--workspace",
            str(workspace),
            "--horizon",
            "30-45",
            "--federal-only",
        ],
    ), redirect_stdout(stdout):
        exit_code = run_scan.main()
    assert exit_code == 0, stdout.getvalue()
    return json.loads(stdout.getvalue().strip())


class FakeGovTribeRetrievalProvider:
    called = False

    def __init__(self, source_config: dict):
        self.source_config = source_config

    def search_scan_opportunities(self, *, vendor_profile: dict, preferences: dict, limit: int = 25) -> dict:
        FakeGovTribeRetrievalProvider.called = True
        return {
            "status": "ok",
            "notes": ["GovTribe MCP tools used: Search_Federal_Contract_Opportunities"],
            "queried_naics": ["541512"],
            "tool_name": "Search_Federal_Contract_Opportunities",
            "records": [
                {
                    "source_id": "govtribe_mcp_commercial_intel",
                    "source_name": "GovTribe MCP Commercial Intelligence",
                    "source_tier": 4,
                    "opportunity_id": "govtribe:gt-123",
                    "canonical_record_id": "govtribe:gt-123",
                    "canonical_record_id_type": "govtribe_id",
                    "notice_id": "gt-123",
                    "title": "IRS Case Management Modernization",
                    "url": "https://govtribe.com/opportunity/gt-123",
                    "buyer": "Internal Revenue Service",
                    "opportunity_class": "contracts",
                    "notice_type": "solicitation",
                    "solicitation_number": "IRS-2026-001",
                    "posted_date": "2026-06-01",
                    "due_date": "2026-07-15",
                    "naics": ["541512"],
                    "set_aside": "Total Small Business Set-Aside",
                    "summary": "Modernize a taxpayer case management platform with cloud-hosted delivery and analytics.",
                    "resource_links": ["https://govtribe.com/opportunity/gt-123"],
                    "raw_match_evidence": {
                        "query": "case management modernization",
                        "queried_naics": ["541512"],
                        "search_mode": "keyword",
                        "tool_name": "Search_Federal_Contract_Opportunities",
                        "source_record_id": "gt-123",
                        "full_desc_loaded": False,
                    },
                }
            ],
        }


class FakeGovTribeNoMatchProvider:
    called = False

    def __init__(self, source_config: dict):
        self.source_config = source_config

    def search_scan_opportunities(self, *, vendor_profile: dict, preferences: dict, limit: int = 25) -> dict:
        FakeGovTribeNoMatchProvider.called = True
        return {
            "status": "no_match",
            "notes": ["No vendor-specific GovTribe scan retrieval terms or NAICS were available."],
            "queried_naics": [],
            "tool_name": "",
            "records": [],
        }


class FakeGovTribeExpiredRetrievalProvider:
    called = False

    def __init__(self, source_config: dict):
        self.source_config = source_config

    def search_scan_opportunities(self, *, vendor_profile: dict, preferences: dict, limit: int = 25) -> dict:
        FakeGovTribeExpiredRetrievalProvider.called = True
        return {
            "status": "ok",
            "notes": ["GovTribe MCP tools used: Search_Federal_Contract_Opportunities"],
            "queried_naics": ["541512"],
            "tool_name": "Search_Federal_Contract_Opportunities",
            "records": [
                {
                    "source_id": "govtribe_mcp_commercial_intel",
                    "source_name": "GovTribe MCP Commercial Intelligence",
                    "source_tier": 4,
                    "opportunity_id": "govtribe:gt-expired",
                    "canonical_record_id": "govtribe:gt-expired",
                    "canonical_record_id_type": "govtribe_id",
                    "notice_id": "gt-expired",
                    "title": "Same Day Expired Response Deadline",
                    "url": "https://govtribe.com/opportunity/gt-expired",
                    "buyer": "Internal Revenue Service",
                    "opportunity_class": "contracts",
                    "notice_type": "solicitation",
                    "solicitation_number": "IRS-2026-EXP",
                    "posted_date": "2026-06-01",
                    "due_date": "2026-06-16T14:00:00Z",
                    "naics": ["541512"],
                    "set_aside": "Total Small Business Set-Aside",
                    "summary": "Modernize case management with cloud delivery and analytics.",
                    "resource_links": ["https://govtribe.com/opportunity/gt-expired"],
                    "raw_match_evidence": {
                        "query": "case management modernization",
                        "queried_naics": ["541512"],
                        "search_mode": "keyword",
                        "tool_name": "Search_Federal_Contract_Opportunities",
                        "source_record_id": "gt-expired",
                        "full_desc_loaded": False,
                    },
                }
            ],
        }


def main() -> int:
    original_sam_api_key = os.environ.get("SAM_API_KEY")
    os.environ["SAM_API_KEY"] = "test-sam-key"
    try:
        search_result = search_sam_opportunities(naics_codes=[], today=date(2026, 6, 10))
        assert search_result["status"] == "no_naics", search_result
        assert search_result["recommended_next_step"] == "bootstrap_workspace", search_result
        assert "Bootstrap this workspace" in search_result["recommended_message"], search_result

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            procurement = workspace / "procurement"
            procurement.mkdir(parents=True, exist_ok=True)
            _write_json(
                procurement / "vendor-profile.json",
                {
                    "company": {
                        "website": "https://example.com",
                    }
                },
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_ROOT / "scan" / "run_scan.py"),
                    "--workspace",
                    str(workspace),
                    "--horizon",
                    "30-45",
                    "--federal-only",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout.strip())

            assert payload["recommended_next_step"] == "bootstrap_workspace", payload
            assert payload["bootstrap_suggested"] is True, payload
            assert payload["recommended_next_moves"], payload
            assert payload["recommended_next_moves"][0]["type"] == "bootstrap_workspace", payload
            assert "https://example.com" in payload["recommended_next_moves"][0]["command"], payload
            assert Path(payload["digest_path"]).exists(), payload

            sam_status = next(
                item
                for item in payload["source_statuses"]
                if item.get("source_id") == "sam_contract_opportunities"
            )
            assert sam_status["status"] == "no_naics", sam_status
            assert sam_status["recommended_next_step"] == "bootstrap_workspace", sam_status
            assert "https://example.com" in sam_status["recommended_command"], sam_status
    finally:
        if original_sam_api_key is None:
            os.environ.pop("SAM_API_KEY", None)
        else:
            os.environ["SAM_API_KEY"] = original_sam_api_key

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=False, govtribe_retrieval=False)
        with patch.dict(os.environ, {}, clear=True):
            payload = _run_scan_main(workspace)
        sam_status = next(item for item in payload["source_statuses"] if item.get("source_id") == "sam_contract_opportunities")
        assert sam_status["status"] == "missing_api_key", payload
        assert not any(item.get("mode") == "scan_retrieval" for item in payload["source_statuses"]), payload

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=True, govtribe_retrieval=True)
        with patch.dict(os.environ, {}, clear=True):
            payload = _run_scan_main(workspace)
        govtribe_retrieval_status = next(
            item
            for item in payload["source_statuses"]
            if item.get("source_id") == "govtribe_mcp_commercial_intel" and item.get("mode") == "scan_retrieval"
        )
        assert govtribe_retrieval_status["status"] == "not_configured", payload

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=True, govtribe_retrieval=True)
        _write_json(workspace / "procurement" / "vendor-profile.json", {"company": {}})
        FakeGovTribeNoMatchProvider.called = False
        with patch.dict(os.environ, {}, clear=True), patch.object(run_scan, "GovTribeMCPCommercialIntelProvider", FakeGovTribeNoMatchProvider):
            payload = _run_scan_main(workspace)
        assert FakeGovTribeNoMatchProvider.called is True, payload
        govtribe_retrieval_status = next(
            item
            for item in payload["source_statuses"]
            if item.get("source_id") == "govtribe_mcp_commercial_intel" and item.get("mode") == "scan_retrieval"
        )
        assert govtribe_retrieval_status["status"] == "no_match", payload
        opportunities = json.loads(Path(payload["opportunities_path"]).read_text(encoding="utf-8")).get("records", [])
        assert opportunities == [], opportunities

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=True, govtribe_retrieval=True)
        FakeGovTribeRetrievalProvider.called = False
        with patch.dict(os.environ, {}, clear=True), patch.object(run_scan, "GovTribeMCPCommercialIntelProvider", FakeGovTribeRetrievalProvider):
            payload = _run_scan_main(workspace)
        assert FakeGovTribeRetrievalProvider.called is True, payload
        govtribe_retrieval_status = next(
            item
            for item in payload["source_statuses"]
            if item.get("source_id") == "govtribe_mcp_commercial_intel" and item.get("mode") == "scan_retrieval"
        )
        assert govtribe_retrieval_status["status"] == "ok", payload
        opportunities = json.loads(Path(payload["opportunities_path"]).read_text(encoding="utf-8")).get("records", [])
        assert opportunities, payload
        assert opportunities[0]["source_id"] == "govtribe_mcp_commercial_intel", opportunities
        assert opportunities[0]["canonical_record_id"] == "govtribe:gt-123", opportunities
        assert "bucket" in opportunities[0], opportunities

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=True, govtribe_retrieval=True)
        FakeGovTribeExpiredRetrievalProvider.called = False
        with patch.dict(os.environ, {}, clear=True), patch.object(
            run_scan,
            "GovTribeMCPCommercialIntelProvider",
            FakeGovTribeExpiredRetrievalProvider,
        ), patch.object(
            run_scan,
            "_scan_now_utc",
            return_value=datetime(2026, 6, 16, 19, 39, 6, tzinfo=timezone.utc),
        ):
            payload = _run_scan_main(workspace)
        assert FakeGovTribeExpiredRetrievalProvider.called is True, payload
        govtribe_retrieval_status = next(
            item
            for item in payload["source_statuses"]
            if item.get("source_id") == "govtribe_mcp_commercial_intel" and item.get("mode") == "scan_retrieval"
        )
        assert govtribe_retrieval_status["status"] == "ok", payload
        assert govtribe_retrieval_status["record_count"] == 1, payload
        opportunities = json.loads(Path(payload["opportunities_path"]).read_text(encoding="utf-8")).get("records", [])
        assert opportunities == [], opportunities

    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_workspace(workspace, govtribe_enabled=True, govtribe_retrieval=True)
        FakeGovTribeRetrievalProvider.called = False
        sam_record = {
            "source_id": "sam_contract_opportunities",
            "source_name": "SAM.gov",
            "source_tier": 1,
            "opportunity_id": "sam-123",
            "canonical_record_id": "sam-123",
            "canonical_record_id_type": "notice_id",
            "notice_id": "sam-123",
            "title": "IRS Case Management Modernization",
            "url": "https://sam.gov/opp/sam-123/view",
            "buyer": "Internal Revenue Service",
            "opportunity_class": "contracts",
            "notice_type": "solicitation",
            "solicitation_number": "IRS-2026-001",
            "posted_date": "2026-06-01",
            "due_date": "2026-07-15",
            "naics": ["541512"],
            "set_aside": "Total Small Business Set-Aside",
            "summary": "Modernize case management with cloud delivery and analytics.",
            "resource_links": [],
            "raw_match_evidence": {"queried_naics": "541512", "full_desc_loaded": False},
        }
        with patch.dict(os.environ, {"SAM_API_KEY": "test-sam-key"}, clear=True), patch.object(
            run_scan,
            "search_sam_opportunities",
            return_value={
                "status": "ok",
                "records": [sam_record],
                "queried_naics": ["541512"],
                "errors": [],
                "notes": ["mock SAM"],
            },
        ), patch.object(
            run_scan,
            "hydrate_sam_notice",
            return_value={"status": "empty", "full_desc_loaded": False, "summary": ""},
        ), patch.object(
            run_scan,
            "GovTribeMCPCommercialIntelProvider",
            FakeGovTribeRetrievalProvider,
        ):
            payload = _run_scan_main(workspace)
        assert FakeGovTribeRetrievalProvider.called is False, payload
        assert not any(
            item.get("source_id") == "govtribe_mcp_commercial_intel" and item.get("mode") == "scan_retrieval"
            for item in payload["source_statuses"]
        ), payload
        opportunities = json.loads(Path(payload["opportunities_path"]).read_text(encoding="utf-8")).get("records", [])
        assert opportunities[0]["source_id"] == "sam_contract_opportunities", opportunities
        assert any(item.get("source_id") == "govtribe_mcp_commercial_intel" for item in payload["source_statuses"]), payload

    print("run_scan_bootstrap_guidance_tests.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
