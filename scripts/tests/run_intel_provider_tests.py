from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from intel.mcp_http import MCPHttpClient, clean_bearer_token  # type: ignore
from intel.providers.govtribe_mcp import GovTribeMCPCommercialIntelProvider, discover_tool_families  # type: ignore
from intel.providers.sam_gov import hydrate_sam_notice, search_sam_opportunities  # type: ignore
from scan.sam_hydrate import hydrate_sam_notice as legacy_hydrate_sam_notice  # type: ignore
from scan.sam_search import search_sam_opportunities as legacy_search_sam_opportunities  # type: ignore


class FakeResponse:
    def __init__(self, body: str | dict[str, object], headers: dict[str, str] | None = None):
        self.body = json.dumps(body, ensure_ascii=True) if isinstance(body, dict) else body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self.body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeUrlopen:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.requests = []

    def __call__(self, request: object, timeout: int = 0) -> FakeResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("No fake responses remain")
        return self.responses.pop(0)


class FakeNoToolsClient:
    def list_tools(self) -> list[dict[str, object]]:
        return []

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        raise AssertionError("call_tool should not run when no compatible tool exists")


class FakeGovTribeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_tools(self) -> list[dict[str, object]]:
        return [
            {
                "name": "Search_Activity",
                "description": "Searches GovTribe activity feed events for a subject record and optionally related records.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "govtribe_type": {"type": "string"},
                        "govtribe_id": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["govtribe_type", "govtribe_id"],
                },
            },
            {
                "name": "Search_Federal_Contract_Opportunities",
                "description": "Search federal contract opportunities by solicitation number or keyword query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_mode": {"type": "string", "enum": ["keyword", "semantic"]},
                        "per_page": {"type": "number"},
                        "naics_codes": {"type": "array", "items": {"type": "string"}},
                        "solicitation_numbers": {"type": "array", "items": {"type": "string"}},
                        "fields_to_return": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "govtribe_id",
                                    "govtribe_url",
                                    "source_url",
                                    "name",
                                    "solicitation_number",
                                    "opportunity_type",
                                    "opportunity_state",
                                    "set_aside_type",
                                    "posted_date",
                                    "due_date",
                                    "award_date",
                                    "descriptions",
                                    "govtribe_ai_summary",
                                    "federal_contract_vehicle",
                                    "federal_agency",
                                    "naics_category",
                                    "psc_category",
                                    "government_files",
                                    "federal_contract_awards",
                                    "federal_contract_idvs",
                                ],
                            },
                        },
                    },
                    "required": [],
                },
            }
        ]

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        return {
            "structuredContent": {
                "records": [
                    {
                        "id": "gt-123",
                        "title": "IRS Case Management Modernization",
                        "solicitation_number": "IRS-2026-001",
                        "url": "https://govtribe.com/opportunity/gt-123",
                        "summary": "GovTribe opportunity record with incumbent and vehicle clues.",
                        "posted_date": "2026-06-01",
                        "due_date": "2026-07-15",
                        "federal_agency": {"name": "Internal Revenue Service"},
                        "naics_category": {"code": "541512", "name": "Computer Systems Design Services"},
                        "set_aside_type": "Total Small Business Set-Aside",
                        "incumbent_name": "Alpha Systems",
                        "vehicle_name": "CIO-SP3",
                        "award_amount": "$24,500,000",
                    }
                ]
            }
        }


def _header_map(request: object) -> dict[str, str]:
    return {str(key): str(value) for key, value in request.header_items()}  # type: ignore[attr-defined]


def main() -> int:
    failures: list[str] = []

    if legacy_search_sam_opportunities is not search_sam_opportunities:
        failures.append("sam_search_wrapper_identity")
    if legacy_hydrate_sam_notice is not hydrate_sam_notice:
        failures.append("sam_hydrate_wrapper_identity")

    with patch.dict(os.environ, {}, clear=True):
        result = search_sam_opportunities(naics_codes=["541512"], today=__import__("datetime").date(2026, 6, 16))
        if result.get("status") != "missing_api_key":
            failures.append("sam_missing_key_status")

    if clean_bearer_token("Bearer abc123") != "abc123":
        failures.append("bearer_prefix_strip")

    fake_http = FakeUrlopen(
        [
            FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-govtribe"},
                    },
                },
                {"Content-Type": "application/json", "Mcp-Session-Id": "session-1"},
            ),
            FakeResponse("", {"Content-Type": "application/json"}),
            FakeResponse(
                'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"Search_Federal_Contract_Opportunities","description":"Search federal contract opportunities","inputSchema":{"type":"object","properties":{"query":{"type":"string"}}}}]}}\n\n',
                {"Content-Type": "text/event-stream"},
            ),
            FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": "{\"records\":[{\"id\":\"gt-1\",\"title\":\"Demo\"}]}",
                            }
                        ]
                    },
                },
                {"Content-Type": "application/json"},
            ),
        ]
    )
    client = MCPHttpClient(url="https://govtribe.com/mcp", bearer_token="Bearer test-token", urlopen=fake_http)
    tools = client.list_tools()
    if len(tools) != 1:
        failures.append("mcp_sse_tools_list")
    call_result = client.call_tool("Search_Federal_Contract_Opportunities", {"query": "IRS-2026-001"})
    if not isinstance(call_result.get("content"), list):
        failures.append("mcp_tools_call_json")
    first_headers = _header_map(fake_http.requests[0])
    third_headers = _header_map(fake_http.requests[2])
    if first_headers.get("Authorization") != "Bearer test-token":
        failures.append("mcp_authorization_header")
    if third_headers.get("Mcp-session-id") != "session-1" and third_headers.get("Mcp-Session-Id") != "session-1":
        failures.append("mcp_session_header")
    if third_headers.get("Mcp-protocol-version") != "2025-06-18" and third_headers.get("MCP-Protocol-Version") != "2025-06-18":
        failures.append("mcp_protocol_version_header")

    discovered = discover_tool_families(tools)
    if discovered.get("opportunities", {}).get("name") != "Search_Federal_Contract_Opportunities":
        failures.append("govtribe_tool_discovery")
    broader_discovery = discover_tool_families(
        [
            {
                "name": "Search_Activity",
                "description": "Searches GovTribe activity feed events for a subject record and optionally related records.",
                "inputSchema": {"required": ["govtribe_type", "govtribe_id"]},
            },
            {
                "name": "Search_Federal_Contract_Opportunities",
                "description": "Search federal contract opportunities and returns solicitation records.",
            },
            {"name": "Search_Federal_Contract_Awards", "description": "Search federal contract awards and vendors."},
            {"name": "Search_Federal_Contract_IDVs", "description": "Search federal contract IDVs and vehicle records."},
            {"name": "Search_Federal_Contract_Vehicles", "description": "Search contract vehicles, IDIQs, GWACs, and schedules."},
            {"name": "Search_Government_Files", "description": "Search government files and procurement documents."},
        ]
    )
    if set(broader_discovery) != {"opportunities", "awards", "idvs", "vehicles", "government_files"}:
        failures.append("govtribe_broader_tool_discovery")
    if broader_discovery.get("opportunities", {}).get("name") != "Search_Federal_Contract_Opportunities":
        failures.append("govtribe_activity_not_opportunity")

    with patch.dict(os.environ, {}, clear=True):
        provider = GovTribeMCPCommercialIntelProvider({"id": "govtribe_mcp_commercial_intel"})
        configured, missing = provider.is_configured()
        if configured or missing != ["GOVTRIBE_MCP_API_KEY"]:
            failures.append("govtribe_missing_key_only")
        missing_result = provider.enrich_scan(record={"title": "Demo"}, hydrated_text="", vendor_profile={}, preferences={})
        if missing_result.get("status") != "not_configured":
            failures.append("govtribe_missing_key_status")
        missing_retrieval = provider.search_scan_opportunities(vendor_profile={}, preferences={})
        if missing_retrieval.get("status") != "not_configured":
            failures.append("govtribe_retrieval_missing_key_status")

    with patch.dict(os.environ, {"GOVTRIBE_MCP_API_KEY": "test-key"}, clear=True):
        provider = GovTribeMCPCommercialIntelProvider({"id": "govtribe_mcp_commercial_intel"}, client=FakeNoToolsClient())  # type: ignore[arg-type]
        configured, missing = provider.is_configured()
        if not configured or missing:
            failures.append("govtribe_no_openai_requirement")
        no_tool_result = provider.enrich_scan(
            record={"title": "IRS Case Management Modernization", "buyer": "IRS"},
            hydrated_text="",
            vendor_profile={},
            preferences={},
        )
        if no_tool_result.get("status") != "tool_contract_unavailable":
            failures.append("govtribe_no_tool_contract_status")
        no_tool_retrieval = provider.search_scan_opportunities(
            vendor_profile={"core_competencies": ["case management"], "naics": {"confirmed": ["541512"]}},
            preferences={},
        )
        if no_tool_retrieval.get("status") != "tool_contract_unavailable":
            failures.append("govtribe_retrieval_no_tool_contract_status")

    with patch.dict(os.environ, {"GOVTRIBE_MCP_API_KEY": "test-key"}, clear=True):
        fake_client = FakeGovTribeClient()
        provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=fake_client,  # type: ignore[arg-type]
        )
        enriched = provider.enrich_scan(
            record={
                "title": "IRS Case Management Modernization",
                "buyer": "Internal Revenue Service",
                "solicitation_number": "IRS-2026-001",
                "summary": "Modernization support.",
            },
            hydrated_text="Modernization support.",
            vendor_profile={"company": {"name": "Acme Federal"}},
            preferences={},
        )
        evidence = enriched.get("enrichment", {}).get("evidence_model", {})  # type: ignore[union-attr]
        if enriched.get("status") != "ok" or not enriched.get("matched"):
            failures.append("govtribe_enriched_status")
        if evidence.get("incumbent", {}).get("name") != "Alpha Systems":
            failures.append("govtribe_evidence_incumbent")
        if evidence.get("vehicle", {}).get("name") != "CIO-SP3":
            failures.append("govtribe_evidence_vehicle")
        first_call_args = fake_client.calls[0][1]
        if first_call_args.get("query") != "IRS-2026-001":
            failures.append("govtribe_solicitation_first")
        if first_call_args.get("solicitation_numbers") != ["IRS-2026-001"]:
            failures.append("govtribe_solicitation_filter")
        if first_call_args.get("search_mode") != "keyword":
            failures.append("govtribe_keyword_mode")
        if "fields_to_return" not in first_call_args:
            failures.append("govtribe_fields_to_return")

        calls_before_empty_retrieval = len(fake_client.calls)
        empty_retrieval = provider.search_scan_opportunities(vendor_profile={}, preferences={})
        if empty_retrieval.get("status") != "no_match":
            failures.append("govtribe_retrieval_empty_profile_no_match")
        if fake_client.calls[calls_before_empty_retrieval:]:
            failures.append("govtribe_retrieval_empty_profile_no_call")

        retrieval = provider.search_scan_opportunities(
            vendor_profile={
                "company": {"name": "Acme Federal", "summary": "Cloud modernization for civilian agencies."},
                "core_competencies": ["case management modernization", "data analytics"],
                "fit_narrative": "Prioritize case management modernization and cloud delivery.",
                "naics": {"confirmed": ["541512"], "candidates": ["541519"]},
            },
            preferences={"soft_preferences": {"positive_keywords": ["taxpayer services"], "preferred_naics": ["541611"]}},
        )
        retrieval_records = retrieval.get("records", [])
        if retrieval.get("status") != "ok" or not retrieval_records:
            failures.append("govtribe_retrieval_status")
        else:
            first_record = retrieval_records[0]
            if first_record.get("source_id") != "govtribe_mcp_commercial_intel":
                failures.append("govtribe_retrieval_source_id")
            if first_record.get("canonical_record_id") != "govtribe:gt-123":
                failures.append("govtribe_retrieval_canonical_id")
            if first_record.get("buyer") != "Internal Revenue Service":
                failures.append("govtribe_retrieval_buyer")
            if "541512" not in first_record.get("naics", []):
                failures.append("govtribe_retrieval_naics")
            evidence = first_record.get("raw_match_evidence", {})
            if evidence.get("tool_name") != "Search_Federal_Contract_Opportunities":
                failures.append("govtribe_retrieval_tool_name")
        retrieval_call_args = fake_client.calls[-1][1]
        if fake_client.calls[-1][0] != "Search_Federal_Contract_Opportunities":
            failures.append("govtribe_retrieval_typed_tool")
        if retrieval_call_args.get("search_mode") != "keyword":
            failures.append("govtribe_retrieval_keyword_first")
        if retrieval_call_args.get("naics_codes") != ["541512", "541519", "541611"]:
            failures.append("govtribe_retrieval_naics_filter")
        if "fields_to_return" not in retrieval_call_args:
            failures.append("govtribe_retrieval_fields_to_return")

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
