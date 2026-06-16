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
from intel.providers.govtribe_mcp import (  # type: ignore
    GovTribeMCPCommercialIntelProvider,
    _scan_retrieval_queries,
    discover_tool_families,
)
from intel.providers.sam_gov import hydrate_sam_notice, search_sam_opportunities  # type: ignore
from scan.sam_hydrate import hydrate_sam_notice as legacy_hydrate_sam_notice  # type: ignore
from scan.sam_search import search_sam_opportunities as legacy_search_sam_opportunities  # type: ignore


GOVTRIBE_OPERATOR_ERROR = (
    "The selected federal agency ids operator is invalid. "
    "The selected federal contract opportunity ids operator is invalid."
)


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
                        "due_date_range": {
                            "type": "object",
                            "properties": {
                                "from": {"type": ["string", "null"]},
                                "to": {"type": ["string", "null"]},
                            },
                        },
                        "opportunity_states": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["Posted", "Awarded", "Cancelled", "Updated"]},
                        },
                        "sort": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "enum": ["postedDate", "dueDate", "awardDate", "_score"]},
                                "direction": {"type": "string", "enum": ["asc", "desc"]},
                            },
                        },
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

    def records(self) -> list[dict[str, object]]:
        return [
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

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        return {"structuredContent": {"records": self.records()}}


class FakeGovTribeVendorClient:
    def __init__(self, records: list[dict[str, object]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._records = records if records is not None else [
            {
                "govtribe_id": "vendor-123",
                "govtribe_url": "https://govtribe.com/vendors/halvik-corp-5grr4",
                "uei": "ABC123DEF456",
                "name": "Halvik, LLC",
                "govtribe_ai_summary": "Halvik provides federal IT modernization and cybersecurity services.",
                "location": {"city": "Vienna", "state": "VA", "country": "USA"},
                "sba_certifications": ["SBA Certified 8A Program Participant"],
                "business_types": ["Service Disabled Veteran Owned Business", "For Profit Organization"],
                "naics_category": [
                    {"name": "Web Search Portals and All Other Information Services"},
                    {"code": "541512", "name": "Computer Systems Design Services"},
                ],
                "awarded_federal_contract_vehicle": [
                    {"name": "GSA MAS", "value": True, "last_date_to_order": "2120-06-01"},
                    {"name": "Expired Vendor Vehicle", "last_date_to_order": "2020-01-01"},
                ],
                "federal_contract_awards": [
                    {
                        "name": "VA Modernization Support",
                        "contract_number": "VA-1",
                        "contracting_federal_agency": {"name": "Department of Veterans Affairs"},
                    }
                ],
                "federal_contract_idvs": [
                    {
                        "name": "IT Services IDIQ",
                        "contract_number": "IDIQ-1",
                        "contracting_federal_agency": {"name": "Department of Homeland Security"},
                    }
                ],
            }
        ]

    def list_tools(self) -> list[dict[str, object]]:
        return [
            {
                "name": "Search_Vendors",
                "description": "Searches GovTribe vendor records and returns vendor profiles.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_mode": {"type": "string", "enum": ["keyword", "semantic"]},
                        "per_page": {"type": "number"},
                        "page": {"type": "number"},
                        "uei_values": {"type": "array", "items": {"type": "string"}},
                        "govtribe_ids": {"type": "array", "items": {"type": "string"}},
                        "fields_to_return": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "govtribe_id",
                                    "govtribe_type",
                                    "govtribe_url",
                                    "uei",
                                    "name",
                                    "dba",
                                    "division",
                                    "govtribe_ai_summary",
                                    "location",
                                    "address",
                                    "sba_certifications",
                                    "business_types",
                                    "naics_category",
                                    "federal_contract_awards",
                                    "federal_contract_idvs",
                                    "awarded_federal_contract_vehicle",
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
        return {"structuredContent": {"records": self._records}}


class FakeGovTribeVendorIntelClient(FakeGovTribeVendorClient):
    def list_tools(self) -> list[dict[str, object]]:
        return [
            *super().list_tools(),
            {
                "name": "Search_Federal_Contract_Awards",
                "description": "Searches GovTribe federal contract awards and returns award records with funding details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_mode": {"type": "string", "enum": ["keyword", "semantic"]},
                        "per_page": {"type": "number"},
                        "page": {"type": "number"},
                        "vendor_ids": {"type": "array", "items": {"type": "string"}},
                        "aggregations": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "top_contracting_federal_agencies_by_dollars_obligated",
                                    "top_funding_federal_agencies_by_dollars_obligated",
                                    "top_federal_contract_vehicles_by_dollars_obligated",
                                ],
                            },
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "Search_Federal_Contract_Vehicles",
                "description": "Search federal contract vehicles, IDIQs, GWACs, and schedules.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_mode": {"type": "string", "enum": ["keyword", "semantic"]},
                        "per_page": {"type": "number"},
                        "page": {"type": "number"},
                        "vendor_ids": {"type": "array", "items": {"type": "string"}},
                        "fields_to_return": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "govtribe_id",
                                    "govtribe_url",
                                    "name",
                                    "contract_type",
                                    "last_date_to_order",
                                    "federal_agency",
                                    "federal_contract_awards",
                                ],
                            },
                        },
                    },
                    "required": [],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        if name == "Search_Federal_Contract_Awards":
            return {
                "structuredContent": {
                    "total": 224,
                    "aggregations": {
                        "top_contracting_federal_agencies_by_dollars_obligated": {
                            "buckets": [
                                {
                                    "key": {
                                        "name": "Department of Commerce US Patent and Trademark Office",
                                        "u_r_l": "https://govtribe.com/agency/federal-agency/uspto",
                                    },
                                    "doc_count": 21,
                                    "sum_value": {"value": 158696956.75},
                                }
                            ]
                        },
                        "top_funding_federal_agencies_by_dollars_obligated": {
                            "buckets": [
                                {
                                    "key": {
                                        "name": "National Aeronautics and Space Administration",
                                        "u_r_l": "https://govtribe.com/agency/federal-agency/nasa",
                                    },
                                    "doc_count": 1,
                                    "sum_value": {"value": 114250000},
                                }
                            ]
                        },
                        "top_federal_contract_vehicles_by_dollars_obligated": {
                            "buckets": [
                                {
                                    "key": {
                                        "gov_tribe_i_d": "GWAC-OLD",
                                        "name": "Expired Legacy GWAC",
                                        "last_date_to_order": "Jan 1, 2020",
                                        "u_r_l": "https://govtribe.com/award/federal-vehicle/expired-legacy-gwac",
                                    },
                                    "doc_count": 80,
                                    "sum_value": {"value": 265948759.67},
                                },
                                {
                                    "key": {
                                        "gov_tribe_i_d": "FSS-MAS",
                                        "name": "Multiple Award Schedule",
                                        "last_date_to_order": "Jun 1, 2120",
                                        "u_r_l": "https://govtribe.com/award/federal-vehicle/multiple-award-schedule-mas",
                                    },
                                    "doc_count": 50,
                                    "sum_value": {"value": 165948759.67},
                                }
                            ]
                        },
                    },
                }
            }
        if name == "Search_Federal_Contract_Vehicles":
            return {
                "structuredContent": {
                    "data": [
                        {
                            "govtribe_id": "GWAC-STARS-II",
                            "govtribe_url": "https://govtribe.com/award/federal-vehicle/8a-streamlined-technology-acquisition-resources-for-services-8a-stars-ii",
                            "name": "8a Streamlined Technology Acquisition Resources for Services",
                            "contract_type": "Master GWAC",
                            "last_date_to_order": "2021-08-30T04:00:00Z",
                        },
                        {
                            "govtribe_id": "GWAC-8ASTARS3",
                            "govtribe_url": "https://govtribe.com/award/federal-vehicle/8a-stars-iii-stars-iii",
                            "name": "8(a) STARS III",
                            "contract_type": "Master GWAC",
                            "last_date_to_order": "2120-07-02T04:00:00Z",
                        }
                    ]
                }
            }
        return {"structuredContent": {"records": self._records}}


class FakeGovTribeVendorRetryClient(FakeGovTribeVendorClient):
    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        args = arguments or {}
        self.calls.append((name, args))
        if args.get("query") == "halvik corp":
            return {"structuredContent": {"records": []}}
        return {"structuredContent": {"records": self._records}}


class FakeGovTribeSemanticFallbackClient(FakeGovTribeClient):
    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        args = arguments or {}
        self.calls.append((name, args))
        if args.get("search_mode") == "keyword":
            return {"structuredContent": {"records": []}}
        return {"structuredContent": {"records": self.records()}}


class FakeGovTribeStructuredErrorClient(FakeGovTribeClient):
    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        return {
            "structuredContent": {
                "isError": True,
                "message": GOVTRIBE_OPERATOR_ERROR,
                "summary": GOVTRIBE_OPERATOR_ERROR,
            }
        }


class FakeGovTribeTextErrorClient(FakeGovTribeClient):
    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        return {"content": [{"type": "text", "text": GOVTRIBE_OPERATOR_ERROR}]}


class FakeGovTribeMixedCaptureClient(FakeGovTribeClient):
    def list_tools(self) -> list[dict[str, object]]:
        return [
            {"name": "Search_Federal_Contract_Opportunities", "description": "Search federal contract opportunities."},
            {"name": "Search_Federal_Contract_Awards", "description": "Search federal contract awards and vendors."},
            {"name": "Search_Federal_Contract_IDVs", "description": "Search federal contract IDVs and vehicle records."},
            {"name": "Search_Federal_Contract_Vehicles", "description": "Search contract vehicles, IDIQs, GWACs, and schedules."},
            {"name": "Search_Government_Files", "description": "Search government files and procurement documents."},
        ]

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, arguments or {}))
        if name == "Search_Federal_Contract_Opportunities":
            return {"structuredContent": {"records": self.records()}}
        return {
            "structuredContent": {
                "isError": True,
                "message": GOVTRIBE_OPERATOR_ERROR,
                "summary": GOVTRIBE_OPERATOR_ERROR,
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
    vendor_discovery = discover_tool_families(
        [
            {
                "name": "Search_Vendors",
                "description": "Searches GovTribe vendor records and returns vendor profiles.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []},
            }
        ]
    )
    if vendor_discovery.get("vendors", {}).get("name") != "Search_Vendors":
        failures.append("govtribe_vendor_tool_discovery")

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
        missing_vendor = provider.resolve_vendor_profile(lookup="Halvik, LLC")
        if missing_vendor.get("status") != "not_configured":
            failures.append("govtribe_vendor_missing_key_status")

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
        no_tool_vendor = provider.resolve_vendor_profile(lookup="Halvik, LLC")
        if no_tool_vendor.get("status") != "tool_contract_unavailable":
            failures.append("govtribe_vendor_no_tool_contract_status")

    with patch.dict(os.environ, {"GOVTRIBE_MCP_API_KEY": "test-key"}, clear=True):
        vendor_client = FakeGovTribeVendorClient()
        provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=vendor_client,  # type: ignore[arg-type]
        )
        vendor_result = provider.resolve_vendor_profile(lookup="ABC123DEF456")
        if vendor_result.get("status") != "ok" or not vendor_result.get("matched"):
            failures.append("govtribe_vendor_uei_status")
        vendor_record = vendor_result.get("vendor_record", {})
        if not isinstance(vendor_record, dict) or vendor_record.get("uei") != "ABC123DEF456":
            failures.append("govtribe_vendor_uei_normalized")
        if isinstance(vendor_record, dict) and "541512" not in vendor_record.get("naics", []):
            failures.append("govtribe_vendor_naics_normalized")
        if isinstance(vendor_record, dict) and "519290" not in vendor_record.get("naics", []):
            failures.append("govtribe_vendor_label_only_naics_mapped")
        naics_items = vendor_record.get("naics_items", []) if isinstance(vendor_record, dict) else []
        if not any(item.get("code") == "519290" and item.get("label") == "Web Search Portals and All Other Information Services" for item in naics_items if isinstance(item, dict)):
            failures.append("govtribe_vendor_naics_items_normalized")
        if isinstance(vendor_record, dict) and "SBA Certified 8A Program Participant" not in vendor_record.get("certifications", []):
            failures.append("govtribe_vendor_certifications_normalized")
        if isinstance(vendor_record, dict) and "GSA MAS" not in vendor_record.get("contract_vehicles", []):
            failures.append("govtribe_vendor_vehicle_normalized")
        if isinstance(vendor_record, dict) and "Expired Vendor Vehicle" in vendor_record.get("contract_vehicles", []):
            failures.append("govtribe_vendor_filters_expired_lookup_vehicle")
        vendor_payload = json.dumps(vendor_record)
        if "True" in vendor_payload or "For Profit Organization" in vendor_record.get("keywords", []):
            failures.append("govtribe_vendor_filters_generic_matching_values")
        uei_args = vendor_client.calls[-1][1]
        if vendor_client.calls[-1][0] != "Search_Vendors":
            failures.append("govtribe_vendor_typed_tool")
        if uei_args.get("uei_values") != ["ABC123DEF456"]:
            failures.append("govtribe_vendor_uei_filter")
        if uei_args.get("search_mode") != "keyword":
            failures.append("govtribe_vendor_keyword_mode")
        if uei_args.get("per_page") != 5:
            failures.append("govtribe_vendor_per_page")
        fields = uei_args.get("fields_to_return", [])
        if not isinstance(fields, list) or "uei" not in fields or "federal_contract_awards" not in fields:
            failures.append("govtribe_vendor_fields_to_return")

        name_result = provider.resolve_vendor_profile(lookup="Halvik, LLC")
        if name_result.get("status") != "ok":
            failures.append("govtribe_vendor_name_status")
        name_args = vendor_client.calls[-1][1]
        if name_args.get("query") != "Halvik, LLC":
            failures.append("govtribe_vendor_name_query")

        url_result = provider.resolve_vendor_profile(lookup="https://govtribe.com/vendors/halvik-corp-5grr4")
        if url_result.get("status") != "ok":
            failures.append("govtribe_vendor_url_status")
        url_args = vendor_client.calls[-1][1]
        if url_args.get("query") != "halvik corp":
            failures.append("govtribe_vendor_url_query")
        if "govtribe_ids" in url_args:
            failures.append("govtribe_vendor_url_no_slug_id_filter")

        retry_client = FakeGovTribeVendorRetryClient()
        retry_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=retry_client,  # type: ignore[arg-type]
        )
        retry_result = retry_provider.resolve_vendor_profile(lookup="https://govtribe.com/vendors/halvik-corp-5grr4")
        if retry_result.get("status") != "ok":
            failures.append("govtribe_vendor_url_retry_status")
        retry_queries = [call[1].get("query") for call in retry_client.calls]
        if retry_queries != ["halvik corp", "halvik corp 5grr4"]:
            failures.append("govtribe_vendor_url_retry_queries")

        no_match_provider = GovTribeMCPCommercialIntelProvider(
            {"id": "govtribe_mcp_commercial_intel"},
            client=FakeGovTribeVendorClient(records=[]),  # type: ignore[arg-type]
        )
        no_match_vendor = no_match_provider.resolve_vendor_profile(lookup="Missing Vendor")
        if no_match_vendor.get("status") != "no_match":
            failures.append("govtribe_vendor_no_match_status")

        intel_client = FakeGovTribeVendorIntelClient()
        intel_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=intel_client,  # type: ignore[arg-type]
        )
        intel_result = intel_provider.resolve_vendor_profile(lookup="ABC123DEF456")
        intel_record = intel_result.get("vendor_record", {})
        if intel_result.get("status") != "ok" or not isinstance(intel_record, dict):
            failures.append("govtribe_vendor_intel_status")
        else:
            intel_buyers = intel_record.get("buyers", [])
            if "Department of Commerce US Patent and Trademark Office" not in intel_buyers:
                failures.append("govtribe_vendor_award_aggregation_contracting_buyer")
            if "National Aeronautics and Space Administration" not in intel_buyers:
                failures.append("govtribe_vendor_award_aggregation_funding_buyer")
            intel_vehicles = intel_record.get("contract_vehicles", [])
            if "Multiple Award Schedule (MAS)" not in intel_vehicles:
                failures.append("govtribe_vendor_award_aggregation_vehicle")
            if "8(a) STARS III" not in intel_vehicles:
                failures.append("govtribe_vendor_vehicle_search")
            if "Expired Legacy GWAC" in intel_vehicles:
                failures.append("govtribe_vendor_award_aggregation_filters_expired_vehicle")
            if "8a Streamlined Technology Acquisition Resources for Services" in intel_vehicles:
                failures.append("govtribe_vendor_vehicle_search_filters_expired_vehicle")
            expired_intel_vehicles = intel_record.get("expired_contract_vehicles", [])
            if not any("Expired Legacy GWAC" in item for item in expired_intel_vehicles):
                failures.append("govtribe_vendor_tracks_expired_aggregation_vehicle")
            if not any("8a Streamlined Technology Acquisition Resources for Services" in item for item in expired_intel_vehicles):
                failures.append("govtribe_vendor_tracks_expired_search_vehicle")
            if "Department of Commerce US Patent and Trademark Office" in intel_record.get("keywords", []):
                failures.append("govtribe_vendor_intel_buyers_not_keywords")
        intel_call_args = {name: args for name, args in intel_client.calls}
        award_args = intel_call_args.get("Search_Federal_Contract_Awards", {})
        vehicle_args = intel_call_args.get("Search_Federal_Contract_Vehicles", {})
        if award_args.get("vendor_ids") != ["ABC123DEF456", "vendor-123"]:
            failures.append("govtribe_vendor_award_aggregation_vendor_filter")
        if award_args.get("per_page") != 0:
            failures.append("govtribe_vendor_award_aggregation_per_page_zero")
        if "top_contracting_federal_agencies_by_dollars_obligated" not in award_args.get("aggregations", []):
            failures.append("govtribe_vendor_award_aggregation_requested_buyers")
        if vehicle_args.get("vendor_ids") != ["ABC123DEF456", "vendor-123"]:
            failures.append("govtribe_vendor_vehicle_vendor_filter")
        if vehicle_args.get("per_page") != 15:
            failures.append("govtribe_vendor_vehicle_per_page")

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

        polluted_queries = _scan_retrieval_queries(
            {
                "company": {"name": "Halvik, LLC", "summary": "Federal IT services contractor."},
                "core_competencies": ["about us", "cybersecurity"],
                "other_taxonomy_tags": {"keywords": ["logistics"]},
                "fit_narrative": "Prioritize cybersecurity.",
            },
            {"soft_preferences": {"positive_keywords": ["digital services", "cloud modernization"]}},
        )
        polluted_query_text = " ".join(query for query, _mode in polluted_queries).lower()
        if "cybersecurity" not in polluted_query_text or "cloud modernization" not in polluted_query_text:
            failures.append("govtribe_retrieval_scrub_keeps_real_terms")
        for low_signal_term in ("about us", "logistics", "digital services"):
            if low_signal_term in polluted_query_text:
                failures.append(f"govtribe_retrieval_scrub_{low_signal_term.replace(' ', '_')}")

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
        due_date_range = retrieval_call_args.get("due_date_range")
        if not isinstance(due_date_range, dict) or not due_date_range.get("from") or not due_date_range.get("to"):
            failures.append("govtribe_retrieval_due_date_range")
        if retrieval_call_args.get("opportunity_states") != ["Posted", "Updated"]:
            failures.append("govtribe_retrieval_opportunity_states")
        if retrieval_call_args.get("sort") != {"key": "dueDate", "direction": "asc"}:
            failures.append("govtribe_retrieval_due_date_sort")
        if retrieval_call_args.get("naics_codes") != ["541512", "541519", "541611"]:
            failures.append("govtribe_retrieval_naics_filter")
        if "fields_to_return" not in retrieval_call_args:
            failures.append("govtribe_retrieval_fields_to_return")

        semantic_client = FakeGovTribeSemanticFallbackClient()
        semantic_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=semantic_client,  # type: ignore[arg-type]
        )
        semantic_retrieval = semantic_provider.search_scan_opportunities(
            vendor_profile={
                "company": {"name": "Acme Federal", "summary": "Cloud modernization for civilian agencies."},
                "core_competencies": ["case management modernization", "data analytics"],
                "fit_narrative": "Prioritize case management modernization and cloud delivery.",
                "naics": {"confirmed": ["541512"], "candidates": ["541519"]},
            },
            preferences={"soft_preferences": {"positive_keywords": ["taxpayer services"], "preferred_naics": ["541611"]}},
        )
        if semantic_retrieval.get("status") != "ok" or not semantic_retrieval.get("records"):
            failures.append("govtribe_semantic_retrieval_status")
        if len(semantic_client.calls) != 2:
            failures.append("govtribe_semantic_retrieval_two_pass")
        keyword_args = semantic_client.calls[0][1] if semantic_client.calls else {}
        semantic_args = semantic_client.calls[1][1] if len(semantic_client.calls) > 1 else {}
        if keyword_args.get("search_mode") != "keyword":
            failures.append("govtribe_semantic_retrieval_keyword_first")
        if keyword_args.get("sort") != {"key": "dueDate", "direction": "asc"}:
            failures.append("govtribe_semantic_retrieval_keyword_due_date_sort")
        if semantic_args.get("search_mode") != "semantic":
            failures.append("govtribe_semantic_retrieval_mode")
        if semantic_args.get("sort") != {"key": "_score", "direction": "desc"}:
            failures.append("govtribe_semantic_retrieval_score_sort")
        if semantic_args.get("due_date_range") != keyword_args.get("due_date_range"):
            failures.append("govtribe_semantic_retrieval_due_date_preserved")
        if semantic_args.get("opportunity_states") != keyword_args.get("opportunity_states"):
            failures.append("govtribe_semantic_retrieval_states_preserved")
        if semantic_args.get("naics_codes") != keyword_args.get("naics_codes"):
            failures.append("govtribe_semantic_retrieval_naics_preserved")
        semantic_records = semantic_retrieval.get("records", [])
        if semantic_records and semantic_records[0].get("raw_match_evidence", {}).get("search_mode") != "semantic":
            failures.append("govtribe_semantic_retrieval_evidence_mode")
        semantic_notes = semantic_retrieval.get("notes", [])
        if not any("semantic expansion ran after keyword" in str(note) for note in semantic_notes):
            failures.append("govtribe_semantic_retrieval_note")

        structured_error_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=FakeGovTribeStructuredErrorClient(),  # type: ignore[arg-type]
        )
        structured_error = structured_error_provider.enrich_scan(
            record={
                "title": "Halvik Federal IT Services",
                "buyer": "Department of Homeland Security",
                "solicitation_number": "HALVIK-2026-001",
                "summary": "IT services support.",
            },
            hydrated_text="IT services support.",
            vendor_profile={"company": {"name": "Halvik"}},
            preferences={},
        )
        structured_enrichment = structured_error.get("enrichment", {})
        if structured_error.get("status") != "error" or structured_error.get("matched"):
            failures.append("govtribe_structured_tool_error_status")
        if structured_enrichment.get("summary"):
            failures.append("govtribe_structured_tool_error_summary")
        if structured_enrichment.get("related_procurements"):
            failures.append("govtribe_structured_tool_error_related_procurements")
        if structured_error.get("source_log"):
            failures.append("govtribe_structured_tool_error_source_log")
        if not any("operator is invalid" in str(note) for note in structured_error.get("notes", [])):
            failures.append("govtribe_structured_tool_error_note")

        text_error_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=FakeGovTribeTextErrorClient(),  # type: ignore[arg-type]
        )
        text_error_retrieval = text_error_provider.search_scan_opportunities(
            vendor_profile={
                "company": {"name": "Halvik", "summary": "Federal IT services contractor."},
                "core_competencies": ["cybersecurity"],
                "naics": {"confirmed": ["541512"]},
            },
            preferences={},
        )
        if text_error_retrieval.get("status") != "error":
            failures.append("govtribe_text_tool_error_retrieval_status")
        if text_error_retrieval.get("records"):
            failures.append("govtribe_text_tool_error_retrieval_records")
        if not any("operator is invalid" in str(note) for note in text_error_retrieval.get("notes", [])):
            failures.append("govtribe_text_tool_error_retrieval_note")

        mixed_capture_provider = GovTribeMCPCommercialIntelProvider(
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "homepage": "https://govtribe.com/mcp",
            },
            client=FakeGovTribeMixedCaptureClient(),  # type: ignore[arg-type]
        )
        mixed_capture = mixed_capture_provider.enrich_capture(
            resolved={
                "title": "IRS Case Management Modernization",
                "buyer": "Internal Revenue Service",
                "url": "https://sam.gov/example",
                "solicitation_number": "IRS-2026-001",
            },
            notice_context_text="Requirement supports case management modernization and operational reporting.",
            attachment_bundle={"attachments": []},
            vendor_profile={"company": {"name": "Acme Federal"}},
            preferences={},
        )
        mixed_enrichment = mixed_capture.get("enrichment", {})
        mixed_related = " ".join(str(item) for item in mixed_enrichment.get("related_procurements", []))
        if mixed_capture.get("status") != "partial_error" or not mixed_capture.get("matched"):
            failures.append("govtribe_mixed_capture_partial_error_status")
        if "IRS Case Management Modernization" not in mixed_related:
            failures.append("govtribe_mixed_capture_keeps_valid_related_procurement")
        if "operator is invalid" in str(mixed_enrichment.get("summary")) or "operator is invalid" in mixed_related:
            failures.append("govtribe_mixed_capture_error_not_evidence")
        if not any("operator is invalid" in str(note) for note in mixed_capture.get("notes", [])):
            failures.append("govtribe_mixed_capture_error_note")

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
