from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

from common.evidence_model import (
    evidence_model_competitive_notes,
    evidence_model_next_questions,
    evidence_model_related_procurement_lines,
    evidence_model_vehicle_signals,
    normalize_provider_evidence_model,
)
from common.paths import today_local_str, utc_now_iso
from common.profile_terms import filter_low_signal_profile_terms
from intel.mcp_http import DEFAULT_GOVTRIBE_MCP_URL, MCPHTTPError, MCPHttpClient, MCPResponseError, clean_bearer_token
from intel.providers.base import (
    clip_text,
    coerce_string_list,
    dedupe_strings,
    default_result,
    env_int,
    source_log_entry,
)


SOURCE_ID = "govtribe_mcp_commercial_intel"
SOURCE_NAME = "GovTribe MCP Commercial Intelligence"
ERROR_TEXT_MARKERS = (
    "operator is invalid",
    "selected federal agency ids operator is invalid",
    "selected federal contract opportunity ids operator is invalid",
)
ERROR_STATUS_VALUES = {"error", "failed", "failure"}
BOOLEAN_TEXT_VALUES = {"true", "false", "yes", "no"}
GENERIC_VENDOR_METADATA_VALUES = {
    "business or organization",
    "for profit organization",
    "limited liability company",
    "partnership or limited liability partnership",
}
NAICS_LABEL_TO_CODE = {
    "web search portals and all other information services": "519290",
}
NAICS_CODE_TO_LABEL = {
    "519290": "Web Search Portals and All Other Information Services",
}

FAMILY_TOOL_GUIDE: dict[str, dict[str, Any]] = {
    "vendors": {
        "preferred_names": ("Search_Vendors",),
        "required_terms": ("vendor",),
        "fields_to_return": (
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
            "parent_or_child",
            "parent",
            "naics_category",
            "federal_contract_awards",
            "federal_contract_idvs",
            "federal_contract_sub_awards",
            "awarded_federal_contract_vehicle",
        ),
    },
    "opportunities": {
        "preferred_names": ("Search_Federal_Contract_Opportunities",),
        "required_terms": ("federal", "contract", "opportunit"),
        "fields_to_return": (
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
        ),
    },
    "awards": {
        "preferred_names": ("Search_Federal_Contract_Awards",),
        "required_terms": ("federal", "contract", "award"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_url",
            "name",
            "contract_number",
            "award_date",
            "ultimate_completion_date",
            "ceiling_value",
            "dollars_obligated",
            "base_and_exercised_options_value",
            "set_aside_type",
            "descriptions",
            "govtribe_ai_summary",
            "awardee",
            "federal_contract_vehicle",
            "federal_contract_idv",
            "contracting_federal_agency",
            "funding_federal_agency",
            "originating_federal_contract_opportunity",
        ),
    },
    "idvs": {
        "preferred_names": ("Search_Federal_Contract_IDVs",),
        "required_terms": ("federal", "contract", "idv"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_url",
            "name",
            "contract_number",
            "award_date",
            "last_date_to_order",
            "ceiling_value",
            "dollars_obligated",
            "base_and_exercised_options_value",
            "set_aside",
            "description",
            "govtribe_ai_summary",
            "awardee",
            "federal_contract_vehicle",
            "contracting_federal_agency",
            "funding_federal_agency",
            "originating_federal_contract_opportunity",
            "task_orders",
        ),
    },
    "vehicles": {
        "preferred_names": ("Search_Federal_Contract_Vehicles", "Find_Federal_Contract_Vehicles"),
        "required_terms": ("federal", "contract", "vehicle"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_url",
            "name",
            "award_date",
            "last_date_to_order",
            "shared_ceiling",
            "set_aside_type",
            "descriptions",
            "govtribe_ai_summary",
            "federal_agency",
            "federal_contract_awards",
            "originating_federal_contract_opportunity",
        ),
    },
    "government_files": {
        "preferred_names": ("Search_Government_Files",),
        "required_terms": ("government", "file"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_url",
            "download_url",
            "name",
            "file_format",
            "extension",
            "file_source",
            "size",
            "posted_date",
            "content_snippet",
            "govtribe_ai_summary",
            "parent_record",
        ),
    },
    "service_contract_inventory": {
        "preferred_names": ("Search_Service_Contract_Inventory",),
        "required_terms": ("service", "contract", "inventory"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_type",
            "fiscal_year",
            "coverage_scope",
            "role",
            "contract_number",
            "piid",
            "idv_piid",
            "description",
            "place_of_performance",
            "date_signed",
            "base_effective_date",
            "accepted_at",
            "hours_invoiced",
            "ftes",
            "total_dollar_amount_invoiced",
            "total_contractor_hours_invoiced",
            "total_ftes",
            "total_dollars_obligated",
            "total_base_and_all_options_value",
            "subcontractor_count",
            "sub_hours_share",
            "derived_hourly_rate",
            "additional_reporting",
            "inherently_governmental_functions",
            "source_url",
            "source_filename",
            "source_publication_title",
            "source_publication_fiscal_year",
            "source_locator",
            "vendor",
            "federal_contract_award",
            "federal_contract_idv",
            "psc_category",
            "naics_category",
            "contracting_federal_agency",
            "funding_federal_agency",
        ),
    },
    "fcv_subcategories": {
        "preferred_names": ("Search_FCV_Subcategories",),
        "required_terms": ("vehicle", "subcategor"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_type",
            "name",
            "short_name",
            "alternate_name",
            "description",
            "descriptions",
            "shared_ceiling",
            "updated_at",
            "federal_contract_vehicle",
            "awardees",
            "federal_contract_idvs",
            "funding_federal_agencies",
        ),
    },
    "sub_awards": {
        "preferred_names": ("Search_Federal_Contract_Sub_Awards",),
        "required_terms": ("federal", "contract", "sub", "award"),
        "fields_to_return": (
            "govtribe_id",
            "govtribe_type",
            "name",
            "award_date",
            "description",
            "updated_at",
            "sub_contractor",
            "prime_contractor",
            "contracting_federal_agency",
            "funding_federal_agency",
        ),
    },
}

QUERY_COMPATIBLE_REQUIRED_FIELDS = {
    "query",
    "search_mode",
    "page",
    "per_page",
    "limit",
    "size",
    "page_size",
    "max_results",
    "fields_to_return",
    "aggregations",
    "naics",
    "naics_code",
    "naics_codes",
    "ncode",
    "ncodes",
    "solicitation_numbers",
    "piids",
    "govtribe_ids",
    "uei_values",
    "vendor_ids",
    "vendor_ids_operator",
    "awardee_vendor_ids",
    "awardee_vendor_ids_operator",
}

VENDOR_AWARD_AGGREGATIONS = (
    "top_contracting_federal_agencies_by_dollars_obligated",
    "top_funding_federal_agencies_by_dollars_obligated",
    "top_federal_contract_vehicles_by_dollars_obligated",
    "top_naics_codes_by_dollars_obligated",
    "top_locations_by_dollars_obligated",
    "top_set_aside_types_by_dollars_obligated",
    "top_contract_types_by_dollars_obligated",
    "top_pricing_types_by_dollars_obligated",
    "dollars_obligated_stats",
    "ceiling_value_stats",
    "base_and_exercised_options_value_stats",
)

VENDOR_SCI_AGGREGATIONS = (
    "hours_invoiced_stats",
    "ftes_stats",
    "total_dollar_amount_invoiced_stats",
    "total_contractor_hours_invoiced_stats",
    "total_ftes_stats",
    "total_dollars_obligated_stats",
    "total_base_and_all_options_value_stats",
    "subcontractor_count_stats",
    "sub_hours_share_stats",
    "derived_hourly_rate_stats",
    "top_fiscal_years_by_doc_count",
    "top_coverage_scopes_by_doc_count",
    "top_roles_by_doc_count",
    "top_additional_reporting_by_doc_count",
    "top_psc_categories_by_doc_count",
    "top_naics_categories_by_doc_count",
    "top_contracting_agencies_by_doc_count",
    "top_funding_agencies_by_doc_count",
    "top_place_of_performance_states_by_doc_count",
    "top_place_of_performance_countries_by_doc_count",
    "top_contract_numbers_by_doc_count",
)

VENDOR_SUB_AWARD_AGGREGATIONS = (
    "top_awardees_by_doc_count",
    "top_funding_federal_agencies_by_doc_count",
    "top_contracting_federal_agencies_by_doc_count",
)


def govtribe_mcp_url() -> str:
    return str(os.getenv("GOVTRIBE_MCP_URL") or DEFAULT_GOVTRIBE_MCP_URL).strip()


def govtribe_timeout_seconds() -> int:
    return env_int("GOVTRIBE_MCP_TIMEOUT_SECONDS", 90)


def govtribe_authorization_token() -> str:
    return clean_bearer_token(str(os.getenv("GOVTRIBE_MCP_API_KEY") or ""))


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower()).strip()


def _clean_signal_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_boolean_or_generic_metadata(value: Any) -> bool:
    normalized = _normalize_key(value)
    return normalized in BOOLEAN_TEXT_VALUES or normalized in GENERIC_VENDOR_METADATA_VALUES


def _signal_values(values: list[Any], *, allow_generic_metadata: bool = False) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _clean_signal_text(value)
        if not text:
            continue
        if _normalize_key(text) in BOOLEAN_TEXT_VALUES:
            continue
        if not allow_generic_metadata and _normalize_key(text) in GENERIC_VENDOR_METADATA_VALUES:
            continue
        cleaned.append(text)
    return dedupe_strings(cleaned)


def _is_govtribe_vendor_url(value: str) -> bool:
    return bool(re.search(r"https?://(?:www\.)?govtribe\.com/vendors/[^/\s]+", str(value or ""), re.I))


def _lookup_url_slug(value: str) -> str:
    match = re.search(r"https?://(?:www\.)?govtribe\.com/vendors/([^/?#\s]+)", str(value or ""), re.I)
    return match.group(1).strip() if match else ""


def _human_vendor_query_from_slug(slug: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", slug or "").strip()
    if not cleaned:
        return ""
    parts = cleaned.split()
    if parts and re.fullmatch(r"[a-z0-9]{4,8}", parts[-1], re.I) and any(char.isdigit() for char in parts[-1]):
        parts = parts[:-1]
    return " ".join(parts).strip()


def _vendor_lookup_queries(lookup: str) -> list[str]:
    raw = str(lookup or "").strip()
    slug = _lookup_url_slug(raw)
    if not slug:
        return [raw] if raw else []
    full_slug_query = slug.replace("-", " ").replace("_", " ").strip()
    return dedupe_strings([_human_vendor_query_from_slug(slug), full_slug_query])


def _is_likely_uei(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return len(cleaned) == 12 and cleaned.isalnum()


def _clean_uei(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or tool.get("title") or "").strip()


def _normalize_tool_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _schema_text(tool: dict[str, Any]) -> str:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    try:
        return json.dumps(schema, ensure_ascii=True, sort_keys=True)
    except Exception:
        return str(schema or "")


def _tool_text(tool: dict[str, Any]) -> str:
    return " ".join(
        [
            str(tool.get("name") or ""),
            str(tool.get("title") or ""),
            str(tool.get("description") or ""),
        ]
    ).lower()


def _tool_score(tool: dict[str, Any], family: str) -> int:
    guide = FAMILY_TOOL_GUIDE.get(family, {})
    if not _tool_accepts_query_pattern(tool):
        return 0
    normalized_name = _normalize_tool_name(_tool_name(tool))
    preferred_names = [_normalize_tool_name(item) for item in guide.get("preferred_names", ())]
    if normalized_name in preferred_names:
        return 100 - preferred_names.index(normalized_name)
    if family == "vendors":
        return 0

    text = _tool_text(tool)
    required_terms = tuple(str(item).lower() for item in guide.get("required_terms", ()))
    if required_terms and not all(term in text for term in required_terms):
        return 0
    score = 10 + sum(3 for term in required_terms if term in text)
    if family == "opportunities" and any(term in text for term in ("grant", "state and local", "vehicle opportunity")):
        score -= 8
    if family == "awards" and any(term in text for term in ("grant", "sub award", "sub-award")):
        score -= 8
    if family == "government_files" and any(term in text for term in ("user file", "vector store")):
        score -= 8
    return score


def _select_tool(tools: list[dict[str, Any]], family: str) -> dict[str, Any] | None:
    scored = sorted(((_tool_score(tool, family), tool) for tool in tools), key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    return scored[0][1]


def discover_tool_families(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for family in FAMILY_TOOL_GUIDE:
        tool = _select_tool(tools, family)
        if tool:
            families[family] = tool
    return families


def _schema_properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _schema_required(tool: dict[str, Any]) -> list[str]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    return [str(item) for item in required] if isinstance(required, list) else []


def _tool_accepts_query_pattern(tool: dict[str, Any]) -> bool:
    required = {_normalize_tool_name(item) for item in _schema_required(tool)}
    return required.issubset(QUERY_COMPATIBLE_REQUIRED_FIELDS)


def _is_string_prop(spec: Any) -> bool:
    if not isinstance(spec, dict):
        return True
    prop_type = spec.get("type")
    if isinstance(prop_type, list):
        return "string" in prop_type
    return prop_type in (None, "string")


def _is_integer_prop(spec: Any) -> bool:
    if not isinstance(spec, dict):
        return False
    prop_type = spec.get("type")
    if isinstance(prop_type, list):
        return "integer" in prop_type or "number" in prop_type
    return prop_type in {"integer", "number"}


def _is_array_prop(spec: Any) -> bool:
    if not isinstance(spec, dict):
        return False
    prop_type = spec.get("type")
    if isinstance(prop_type, list):
        return "array" in prop_type
    return prop_type == "array"


def _is_object_prop(spec: Any) -> bool:
    if not isinstance(spec, dict):
        return False
    prop_type = spec.get("type")
    if isinstance(prop_type, list):
        return "object" in prop_type
    return prop_type == "object"


def _enum_values(spec: Any) -> list[str]:
    if not isinstance(spec, dict):
        return []
    values = spec.get("enum")
    if not isinstance(values, list):
        items = spec.get("items")
        values = items.get("enum") if isinstance(items, dict) else []
    return [str(value) for value in values] if isinstance(values, list) else []


def _tool_family(tool: dict[str, Any]) -> str:
    normalized_name = _normalize_tool_name(_tool_name(tool))
    for family, guide in FAMILY_TOOL_GUIDE.items():
        preferred_names = {_normalize_tool_name(item) for item in guide.get("preferred_names", ())}
        if normalized_name in preferred_names:
            return family
    return ""


def _fields_for_tool(tool: dict[str, Any]) -> list[str]:
    guide = FAMILY_TOOL_GUIDE.get(_tool_family(tool), {})
    requested = [str(item) for item in guide.get("fields_to_return", ())]
    spec = _schema_properties(tool).get("fields_to_return")
    allowed = set(_enum_values(spec))
    if allowed:
        return [field for field in requested if field in allowed]
    return requested


def _vendor_lookup_query(lookup: str) -> str:
    queries = _vendor_lookup_queries(lookup)
    return queries[0] if queries else str(lookup or "").strip()


def _vendor_tool_arguments(tool: dict[str, Any], *, lookup: str, limit: int = 5, query: str = "") -> dict[str, Any]:
    properties = _schema_properties(tool)
    query = query or _vendor_lookup_query(lookup)
    cleaned_uei = _clean_uei(lookup)
    is_uei = _is_likely_uei(lookup)
    if not properties:
        args: dict[str, Any] = {"query": query, "per_page": limit, "search_mode": "keyword"}
        if is_uei:
            args["uei_values"] = [cleaned_uei]
        return args

    args = {}
    string_fallbacks: list[str] = []
    for name, spec in properties.items():
        key = _normalize_key(name)
        if _is_integer_prop(spec) and key in {"limit", "size", "page size", "per page", "max results"}:
            args[name] = limit
            continue
        if _is_integer_prop(spec) and key == "page":
            args[name] = 1
            continue
        if _is_array_prop(spec):
            if key == "fields to return":
                fields = _fields_for_tool(tool)
                if fields:
                    args[name] = fields
            elif key in {"uei values", "ueis", "uei"} and is_uei:
                args[name] = [cleaned_uei]
            continue
        if _is_object_prop(spec):
            continue
        if not _is_string_prop(spec):
            continue
        if key.endswith(" operator"):
            continue
        string_fallbacks.append(name)
        if key in {"query", "q", "search", "search query", "keyword", "keywords", "term", "terms"}:
            args[name] = query
        elif key == "search mode":
            allowed_modes = set(_enum_values(spec))
            if not allowed_modes or "keyword" in allowed_modes:
                args[name] = "keyword"

    if not any(str(value).strip() == query for value in args.values() if isinstance(value, str)):
        query_key = next((name for name in string_fallbacks if name in _schema_required(tool)), None) or (
            string_fallbacks[0] if string_fallbacks else ""
        )
        if query_key and query_key not in args:
            args[query_key] = query
    return args


def _search_mode_for_query(query: str, mode: str = "keyword") -> str:
    clean_mode = str(mode or "keyword").strip().lower()
    if clean_mode not in {"keyword", "semantic"}:
        clean_mode = "keyword"
    if clean_mode == "semantic":
        return "semantic"
    return "keyword"


def _tool_arguments(
    tool: dict[str, Any],
    *,
    query: str,
    naics_codes: list[str] | None = None,
    solicitation_number: str = "",
    title: str = "",
    buyer: str = "",
    limit: int = 3,
    search_mode: str = "keyword",
    due_date_from: str = "",
    due_date_to: str = "",
    opportunity_states: list[str] | None = None,
    sort: dict[str, str] | None = None,
) -> dict[str, Any]:
    properties = _schema_properties(tool)
    if not properties:
        return {"query": query, "limit": limit, "search_mode": _search_mode_for_query(query, search_mode)}

    args: dict[str, Any] = {}
    string_fallbacks: list[str] = []
    for name, spec in properties.items():
        key = _normalize_key(name)
        if _is_object_prop(spec):
            if key == "due date range" and (due_date_from or due_date_to):
                args[name] = {
                    "from": due_date_from or None,
                    "to": due_date_to or None,
                }
            elif key == "sort" and sort:
                args[name] = sort
            continue
        if _is_integer_prop(spec) and key in {"limit", "size", "page size", "per page", "max results"}:
            args[name] = limit
            continue
        if _is_array_prop(spec):
            if key == "fields to return":
                fields = _fields_for_tool(tool)
                if fields:
                    args[name] = fields
            elif key == "solicitation numbers" and solicitation_number:
                args[name] = [solicitation_number]
            elif key in {"naics", "naics codes", "naics code", "ncode", "ncodes"} and naics_codes:
                args[name] = naics_codes
            elif key in {"opportunity states", "opportunity state"} and opportunity_states:
                args[name] = opportunity_states
            continue
        if not _is_string_prop(spec):
            continue
        if key.endswith(" operator"):
            continue
        string_fallbacks.append(name)
        if key in {"query", "q", "search", "search query", "keyword", "keywords", "term", "terms"}:
            args[name] = query
        elif key == "search mode":
            mode = _search_mode_for_query(query, search_mode)
            allowed_modes = set(_enum_values(spec))
            if not allowed_modes or mode in allowed_modes:
                args[name] = mode
        elif "solicitation" in key and solicitation_number:
            args[name] = solicitation_number
        elif "notice" in key and solicitation_number:
            args[name] = solicitation_number
        elif "title" in key and title:
            args[name] = title
        elif ("agency" in key or "buyer" in key or "customer" in key) and buyer:
            args[name] = buyer
        elif key in {"naics", "naics code", "naics codes", "ncode", "ncodes"} and naics_codes:
            args[name] = " ".join(naics_codes)

    if not any(str(value).strip() == query for value in args.values() if isinstance(value, str)):
        query_key = next((name for name in string_fallbacks if name in _schema_required(tool)), None) or (
            string_fallbacks[0] if string_fallbacks else ""
        )
        if query_key and query_key not in args:
            args[query_key] = query
    return args


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
        "fit_narrative": clip_text(vendor_profile.get("fit_narrative"), max_chars=1000),
        "company_summary": clip_text(
            (vendor_profile.get("company") or {}).get("summary")
            if isinstance(vendor_profile.get("company"), dict)
            else "",
            max_chars=1200,
        ),
        "core_competencies": coerce_string_list(vendor_profile.get("core_competencies"), max_items=8),
        "confirmed_naics": coerce_string_list((naics or {}).get("confirmed"), max_items=8),
        "candidate_naics": coerce_string_list((naics or {}).get("candidates") or (naics or {}).get("candidate"), max_items=8),
        "excluded_opportunity_classes": coerce_string_list(hard_filters.get("exclude_opportunity_classes"), max_items=8),
    }


def _preference_values(preferences: dict[str, Any] | None, section: str, key: str) -> list[str]:
    values: list[Any] = []
    if not isinstance(preferences, dict):
        return []
    base_section = preferences.get(section, {}) if isinstance(preferences.get(section), dict) else {}
    if isinstance(base_section.get(key), list):
        values.extend(base_section.get(key, []))
    learning = preferences.get("learning", {}) if isinstance(preferences.get("learning"), dict) else {}
    applied = learning.get("applied_preferences", {}) if isinstance(learning.get("applied_preferences"), dict) else {}
    applied_section = applied.get(section, {}) if isinstance(applied.get(section), dict) else {}
    if isinstance(applied_section.get(key), list):
        values.extend(applied_section.get(key, []))
    return coerce_string_list(values, max_items=12)


def _vendor_retrieval_naics(vendor_profile: dict[str, Any], preferences: dict[str, Any]) -> list[str]:
    vendor = _vendor_brief(vendor_profile, preferences)
    values = [
        *coerce_string_list(vendor.get("confirmed_naics"), max_items=12),
        *coerce_string_list(vendor.get("candidate_naics"), max_items=12),
        *_preference_values(preferences, "soft_preferences", "preferred_naics"),
    ]
    excluded = set(_preference_values(preferences, "hard_filters", "exclude_naics"))
    return [item for item in dedupe_strings(values) if item not in excluded][:8]


def _profile_terms(vendor_profile: dict[str, Any], preferences: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    discrete_terms: list[str] = []
    company = vendor_profile.get("company") if isinstance(vendor_profile.get("company"), dict) else {}
    terms.extend(coerce_string_list(company.get("summary"), max_items=1))
    for item in vendor_profile.get("core_competencies", []):
        if isinstance(item, dict):
            discrete_terms.extend(coerce_string_list([item.get("name"), item.get("summary")], max_items=2))
        else:
            discrete_terms.extend(coerce_string_list(item, max_items=1))
    discrete_terms.extend(
        coerce_string_list((vendor_profile.get("other_taxonomy_tags") or {}).get("keywords"), max_items=10)
        if isinstance(vendor_profile.get("other_taxonomy_tags"), dict)
        else []
    )
    discrete_terms.extend(_preference_values(preferences, "soft_preferences", "positive_keywords"))
    terms.extend(filter_low_signal_profile_terms(discrete_terms))
    fit_narrative = str(vendor_profile.get("fit_narrative") or "").strip()
    if fit_narrative:
        terms.append(clip_text(fit_narrative, max_chars=500))
    return dedupe_strings([clip_text(term, max_chars=120) for term in terms if term])[:12]


def _scan_retrieval_queries(vendor_profile: dict[str, Any], preferences: dict[str, Any]) -> list[tuple[str, str]]:
    terms = _profile_terms(vendor_profile, preferences)
    vendor_name = _vendor_name(vendor_profile)
    if terms:
        keyword_terms = [f'"{term}"' if " " in term and len(term) <= 80 else term for term in terms[:6]]
        semantic_query = " ".join([vendor_name, *terms[:8]]).strip()
        return [
            (" | ".join(keyword_terms), "keyword"),
            (semantic_query, "semantic"),
        ]
    return [(vendor_name, "keyword")] if vendor_name != "Vendor" else []


def _scan_retrieval_due_date_range(preferences: dict[str, Any]) -> tuple[str, str]:
    time_horizon = preferences.get("time_horizon", {}) if isinstance(preferences.get("time_horizon"), dict) else {}
    try:
        min_days = max(int(time_horizon.get("retrieval_min_days_from_today", 0) or 0), 0)
    except (TypeError, ValueError):
        min_days = 0
    try:
        max_days = max(int(time_horizon.get("retrieval_max_days_from_today", 120) or 120), min_days)
    except (TypeError, ValueError):
        max_days = 120
    today = date.fromisoformat(today_local_str())
    return (
        (today + timedelta(days=min_days)).isoformat(),
        (today + timedelta(days=max_days)).isoformat(),
    )


def _scan_retrieval_sort(search_mode: str) -> dict[str, str]:
    if str(search_mode or "").strip().lower() == "semantic":
        return {"key": "_score", "direction": "desc"}
    return {"key": "dueDate", "direction": "asc"}


def _scan_record_brief(record: dict[str, Any], hydrated_text: str) -> dict[str, Any]:
    return {
        "title": str(record.get("title") or "").strip(),
        "buyer": str(record.get("buyer") or "").strip(),
        "notice_id": str(record.get("notice_id") or "").strip(),
        "solicitation_number": str(record.get("solicitation_number") or "").strip(),
        "naics": str(record.get("naics") or "").strip(),
        "set_aside": str(record.get("set_aside") or "").strip(),
        "url": str(record.get("url") or "").strip(),
        "summary": clip_text(record.get("summary"), max_chars=2000),
        "hydrated_text": clip_text(hydrated_text, max_chars=5000),
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
                "summary": clip_text(item.get("summary") or item.get("text"), max_chars=300),
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
        "notice_context_text": clip_text(notice_context_text, max_chars=10000),
        "attachments": _attachment_manifest(attachment_bundle),
    }


def _json_from_text(text: str) -> Any:
    candidate = str(text or "").strip()
    if not candidate:
        return None
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _known_tool_error_text(text: Any) -> bool:
    value = str(text or "").strip().lower()
    return bool(value) and any(marker in value for marker in ERROR_TEXT_MARKERS)


def _compact_error_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("message", "detail", "details", "error_description", "text", "summary"):
            text = _compact_error_text(value.get(key))
            if text:
                return text
        if "error" in value:
            return _compact_error_text(value.get("error"))
        try:
            return clip_text(json.dumps(value, ensure_ascii=True, sort_keys=True), max_chars=300)
        except Exception:
            return clip_text(value, max_chars=300)
    if isinstance(value, list):
        return "; ".join(filter(None, (_compact_error_text(item) for item in value[:3])))
    return clip_text(value, max_chars=300)


def _record_identity_keys(value: dict[str, Any]) -> bool:
    strong_keys = {
        "govtribe_id",
        "govtribe_url",
        "external_record_id",
        "solicitation_number",
        "solicitationNumber",
        "notice_id",
        "noticeId",
        "contract_number",
        "contract_id",
        "award_id",
        "awardId",
        "piid",
        "download_url",
        "source_url",
    }
    return bool(strong_keys.intersection(value.keys()))


def _record_container_keys(value: dict[str, Any]) -> bool:
    container_keys = {"records", "results", "data", "items", "opportunities", "awards", "vehicles", "files", "documents"}
    return any(isinstance(value.get(key), (list, dict)) for key in container_keys)


def _payload_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("message", "detail", "details", "error", "errors", "text", "summary", "title", "name"):
            if key in value:
                parts.append(_payload_text(value.get(key)))
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, list):
        return " ".join(_payload_text(item) for item in value[:6]).strip()
    return str(value or "").strip()


def _tool_error_note(value: Any) -> str:
    if isinstance(value, str):
        return f"GovTribe MCP tool error: {clip_text(value, max_chars=300)}" if _known_tool_error_text(value) else ""
    if not isinstance(value, dict):
        return ""

    is_error = value.get("isError")
    if is_error is True or str(is_error).strip().lower() == "true":
        message = _compact_error_text(value) or "tool returned an error payload"
        return f"GovTribe MCP tool error: {message}"

    error_value = value.get("error")
    if error_value:
        message = _compact_error_text(error_value) or _compact_error_text(value)
        return f"GovTribe MCP tool error: {message}"

    errors_value = value.get("errors")
    if errors_value:
        message = _compact_error_text(errors_value) or _compact_error_text(value)
        return f"GovTribe MCP tool error: {message}"

    status = str(value.get("status") or "").strip().lower()
    if status in ERROR_STATUS_VALUES and _compact_error_text(value):
        return f"GovTribe MCP tool error: {_compact_error_text(value)}"

    payload_text = _payload_text(value)
    if _known_tool_error_text(payload_text) and not _record_identity_keys(value):
        return f"GovTribe MCP tool error: {clip_text(payload_text, max_chars=300)}"

    return ""


def _is_error_only_value(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if not isinstance(value, dict):
        return False
    if _record_container_keys(value):
        return False
    if _record_identity_keys(value):
        return False
    return bool(_tool_error_note(value))


def _extract_tool_values(tool_result: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("structuredContent", "structured_content", "value"):
        if key in tool_result:
            values.append(tool_result.get(key))
    content = tool_result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if "structuredContent" in item:
                values.append(item.get("structuredContent"))
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parsed = _json_from_text(text)
                values.append(parsed if parsed is not None else text.strip())
    return values


def _flatten_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        records: list[dict[str, Any]] = []
        for item in value:
            records.extend(_flatten_records(item))
        return records
    if not isinstance(value, dict):
        return []
    records: list[dict[str, Any]] = []
    for key in ("records", "results", "data", "items", "opportunities", "awards", "vehicles", "files", "documents"):
        nested = value.get(key)
        if isinstance(nested, (list, dict)):
            records.extend(_flatten_records(nested))
    if records:
        return records
    useful_keys = {
        "govtribe_id",
        "govtribe_url",
        "id",
        "title",
        "name",
        "summary",
        "description",
        "descriptions",
        "govtribe_ai_summary",
        "content_snippet",
        "solicitation_number",
        "solicitationNumber",
        "notice_id",
        "url",
        "contract_number",
        "award_id",
        "vehicle",
        "vendor",
        "recipient",
    }
    if useful_keys.intersection(value.keys()):
        return [value]
    return []


def _tool_result_records_and_errors(tool_result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for value in _extract_tool_values(tool_result):
        error_note = _tool_error_note(value)
        if error_note:
            errors.append(error_note)
        if _is_error_only_value(value):
            continue
        records.extend(_flatten_records(value))
    return records, dedupe_strings(errors)


def _first_text(record: Any, *keys: str) -> str:
    if not isinstance(record, dict):
        return str(record or "").strip()
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            nested = _first_text(value, "name", "title", "value", "amount", "id")
            if nested:
                return nested
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = _first_text(item, "name", "title", "value", "amount", "id")
                    if nested:
                        return nested
                else:
                    text = str(item or "").strip()
                    if text:
                        return text
        else:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _record_url(record: dict[str, Any], default_url: str) -> str:
    return _first_text(record, "govtribe_url", "url", "u_r_l", "link", "uiLink", "permalink", "source_url", "download_url") or default_url


def _record_identifier(record: dict[str, Any]) -> str:
    return _first_text(
        record,
        "govtribe_id",
        "external_record_id",
        "id",
        "uuid",
        "notice_id",
        "noticeId",
        "solicitation_number",
        "solicitationNumber",
        "award_id",
        "awardId",
        "contract_id",
        "contract_number",
        "piid",
        "gov_tribe_i_d",
    )


def _record_uei(record: dict[str, Any]) -> str:
    return _first_text(record, "uei", "uei_value", "ueiValue", "sam_uei", "unique_entity_id").upper()


def _record_title(record: dict[str, Any]) -> str:
    return _first_text(record, "title", "name", "solicitationTitle", "description", "summary") or "GovTribe record"


def _record_value(record: dict[str, Any]) -> str:
    return _first_text(
        record,
        "contract_value",
        "contractValue",
        "ceiling_value",
        "shared_ceiling",
        "dollars_obligated",
        "base_and_exercised_options_value",
        "award_amount",
        "awardAmount",
        "estimated_value",
        "estimatedValue",
        "ceiling",
        "value",
        "amount",
    )


def _query_for_opportunity(opportunity: dict[str, Any]) -> str:
    parts = [
        str(opportunity.get("solicitation_number") or "").strip(),
        str(opportunity.get("title") or "").strip(),
        str(opportunity.get("buyer") or "").strip(),
    ]
    return " ".join(part for part in parts if part).strip()


def _call_search(
    client: MCPHttpClient,
    *,
    tool: dict[str, Any],
    query: str,
    naics_codes: list[str] | None = None,
    solicitation_number: str = "",
    title: str = "",
    buyer: str = "",
    limit: int = 3,
    search_mode: str = "keyword",
    due_date_from: str = "",
    due_date_to: str = "",
    opportunity_states: list[str] | None = None,
    sort: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    args = _tool_arguments(
        tool,
        query=query,
        naics_codes=naics_codes,
        solicitation_number=solicitation_number,
        title=title,
        buyer=buyer,
        limit=limit,
        search_mode=search_mode,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
        opportunity_states=opportunity_states,
        sort=sort,
    )
    result = client.call_tool(_tool_name(tool), args)
    records, errors = _tool_result_records_and_errors(result)
    return records, _tool_name(tool), errors


def _records_to_result(
    *,
    source_config: dict[str, Any],
    status: str,
    matched_by: str,
    records_by_family: list[tuple[str, dict[str, Any]]],
    notes: list[str],
    default_url: str,
) -> dict[str, Any]:
    source_id = str(source_config.get("id") or SOURCE_ID).strip()
    source_name = str(source_config.get("name") or SOURCE_NAME).strip()
    if not records_by_family:
        return default_result(source_id, source_name, status, notes=notes)

    first_family, first_record = records_by_family[0]
    source_url = _record_url(first_record, default_url)
    external_record_id = _record_identifier(first_record)
    summary = _first_text(
        first_record,
        "summary",
        "govtribe_ai_summary",
        "description",
        "descriptions",
        "content_snippet",
        "abstract",
        "title",
        "name",
    )
    incumbent_name = ""
    vehicle_name = ""
    set_aside = ""
    value = ""

    for _, record in records_by_family:
        incumbent_name = incumbent_name or _first_text(
            record,
            "incumbent",
            "incumbent_name",
            "vendor",
            "vendor_name",
            "awardee",
            "recipient",
            "recipient_name",
            "contractor",
        )
        vehicle_name = vehicle_name or _first_text(
            record,
            "vehicle",
            "vehicle_name",
            "contract_vehicle",
            "contractVehicle",
            "federal_contract_vehicle",
            "federal_contract_idv",
        )
        set_aside = set_aside or _first_text(record, "set_aside", "setAside", "set_aside_type", "typeOfSetAsideDescription")
        value = value or _record_value(record)

    related_procurements = []
    for family, record in records_by_family[:8]:
        related_procurements.append(
            {
                "title": _record_title(record),
                "identifier": _record_identifier(record),
                "relationship": f"GovTribe {family.replace('_', ' ')} signal",
                "contract_value": _record_value(record),
                "confidence": "medium",
                "url": _record_url(record, default_url),
                "notes": coerce_string_list(record.get("notes"), max_items=2),
            }
        )

    evidence_gaps = []
    if not incumbent_name:
        evidence_gaps.append("GovTribe did not return a clear incumbent name in the normalized fields.")
    if not vehicle_name:
        evidence_gaps.append("GovTribe did not return a clear contract vehicle name in the normalized fields.")
    if not value:
        evidence_gaps.append("GovTribe did not return a clear value or ceiling in the normalized fields.")

    raw_evidence = {
        "summary": summary,
        "incumbent": {
            "name": incumbent_name,
            "status": "possible" if incumbent_name else "unknown",
            "confidence": "medium" if incumbent_name else "unknown",
            "evidence": [matched_by] if incumbent_name else [],
        },
        "vehicle": {
            "name": vehicle_name,
            "set_aside": set_aside,
            "confidence": "medium" if vehicle_name or set_aside else "unknown",
            "evidence": [matched_by] if vehicle_name or set_aside else [],
        },
        "recompete_clues": coerce_string_list(
            [
                _first_text(record, "recompete", "recompete_clue", "procurement_stage", "status")
                for _, record in records_by_family
            ],
            max_items=6,
        ),
        "related_procurements": related_procurements,
        "contract_value_or_ceiling": {
            "amount": value,
            "label": "GovTribe reported value or ceiling" if value else "",
            "confidence": "medium" if value else "unknown",
            "evidence": [matched_by] if value else [],
        },
        "teaming_posture": {
            "recommended_posture": "",
            "confidence": "unknown",
            "rationale": coerce_string_list(
                [
                    f"Validate posture against GovTribe incumbent signal: {incumbent_name}" if incumbent_name else "",
                    f"Validate set-aside and vehicle fit: {set_aside or vehicle_name}" if set_aside or vehicle_name else "",
                ],
                max_items=4,
            ),
            "partner_signals": [],
            "risks": [],
        },
        "next_questions": coerce_string_list(
            [
                "Confirm incumbent and recompete timing against official solicitation attachments.",
                "Validate vehicle path and set-aside posture before capture gate.",
                "Confirm any GovTribe related procurements against official award records.",
            ],
            max_items=6,
        ),
        "evidence_gaps": evidence_gaps,
    }

    evidence_model = normalize_provider_evidence_model(
        raw_evidence,
        source_id=source_id,
        source_name=source_name,
        source_url=source_url,
        external_record_id=external_record_id,
    )
    competitive_landscape = evidence_model_competitive_notes(evidence_model, max_items=6)
    vehicle_signals = evidence_model_vehicle_signals(evidence_model, max_items=6)
    related_lines = evidence_model_related_procurement_lines(evidence_model, max_items=6)
    next_questions = evidence_model_next_questions(evidence_model, max_items=6)
    source_log = [
        source_log_entry(
            title=_record_title(record),
            url=_record_url(record, default_url),
            publisher="GovTribe",
            relevance=f"GovTribe {family.replace('_', ' ')} enrichment",
            confidence=2,
        )
        for family, record in records_by_family[:4]
    ]

    return {
        "source_id": source_id,
        "source_name": source_name,
        "status": status,
        "matched": True,
        "matched_by": matched_by,
        "confidence": "medium",
        "external_record_id": external_record_id,
        "source_url": source_url,
        "notes": dedupe_strings(notes),
        "source_log": source_log,
        "enrichment": {
            "summary": summary or f"GovTribe returned {len(records_by_family)} related record(s).",
            "competitive_landscape": competitive_landscape,
            "vehicle_signals": vehicle_signals,
            "related_procurements": related_lines,
            "next_questions": next_questions,
            "evidence_model": evidence_model,
        },
        "tool_family": first_family,
    }


def _naics_item_from_text(value: Any) -> dict[str, str] | None:
    text = _clean_signal_text(value)
    if not text or _is_boolean_or_generic_metadata(text):
        return None
    match = re.search(r"\b\d{6}\b", text)
    if match:
        code = match.group(0)
        label = _clean_signal_text(re.sub(rf"\b{code}\b\s*[-:–—]?\s*", "", text))
        if label == code:
            label = ""
        return {"code": code, "label": label or NAICS_CODE_TO_LABEL.get(code, "")}
    mapped_code = NAICS_LABEL_TO_CODE.get(_normalize_key(text))
    if mapped_code:
        return {"code": mapped_code, "label": text}
    return {"code": "", "label": text}


def _record_naics_items(record: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    def append_item(item: dict[str, str] | None) -> None:
        if not item:
            return
        key = json.dumps(item, ensure_ascii=True, sort_keys=True)
        if key not in {json.dumps(existing, ensure_ascii=True, sort_keys=True) for existing in items}:
            items.append(item)

    def first_item(values: list[str]) -> dict[str, str] | None:
        for raw_value in values:
            item = _naics_item_from_text(raw_value)
            if item:
                return item
        return None

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            code_values: list[str] = []
            label_values: list[str] = []
            for key in ("code", "naics", "n_a_i_c_s", "naics_code", "naicsCode", "id", "value"):
                if key in value:
                    direct = value.get(key)
                    if isinstance(direct, (dict, list)):
                        collect(direct)
                    else:
                        text = _clean_signal_text(direct)
                        if re.search(r"\b\d{6}\b", text):
                            code_values.append(text)
                        elif text:
                            label_values.append(text)
            for key in ("name", "title", "label", "description"):
                if key in value:
                    direct = value.get(key)
                    if isinstance(direct, (dict, list)):
                        collect(direct)
                    else:
                        text = _clean_signal_text(direct)
                        if text:
                            label_values.append(text)
            if code_values or label_values:
                code_item = first_item(code_values)
                label_item = first_item(label_values)
                label = label_item.get("label", "") if label_item else ""
                if code_item and code_item.get("code"):
                    append_item({"code": code_item["code"], "label": label or code_item.get("label", "")})
                else:
                    for label_value in label_values:
                        append_item(_naics_item_from_text(label_value))
                return
            for nested in value.values():
                collect(nested)
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        append_item(_naics_item_from_text(value))

    for key in ("naics", "n_a_i_c_s", "naics_code", "naics_codes", "naicsCode", "naicsCategory", "naics_category"):
        if key in record:
            collect(record.get(key))
    return items


def _record_naics_codes(record: dict[str, Any]) -> list[str]:
    return dedupe_strings([item["code"] for item in _record_naics_items(record) if item.get("code")])


def _record_resource_links(record: dict[str, Any], source_url: str) -> list[Any]:
    links: list[Any] = []
    for key in ("resource_links", "resourceLinks", "government_files", "files", "attachments"):
        value = record.get(key)
        if isinstance(value, list):
            links.extend(value[:8])
        elif value:
            links.append(value)
    for key in ("source_url", "govtribe_url", "url", "download_url"):
        value = str(record.get(key) or "").strip()
        if value:
            links.append(value)
    if source_url:
        links.append(source_url)

    deduped: list[Any] = []
    seen: set[str] = set()
    for item in links:
        key = json.dumps(item, ensure_ascii=True, sort_keys=True) if isinstance(item, dict) else str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:10]


def _normalize_scan_opportunity(
    *,
    record: dict[str, Any],
    source_config: dict[str, Any],
    query: str,
    queried_naics: list[str],
    search_mode: str,
    tool_name: str,
    default_url: str,
) -> dict[str, Any]:
    source_id = str(source_config.get("id") or SOURCE_ID).strip()
    source_name = str(source_config.get("name") or SOURCE_NAME).strip()
    source_record_id = _record_identifier(record)
    source_url = _record_url(record, default_url)
    title = _record_title(record)
    canonical_source_value = source_record_id or source_url or title
    canonical_id = f"govtribe:{canonical_source_value}" if canonical_source_value else "govtribe:unknown"
    notice_id = _first_text(record, "notice_id", "noticeId", "sam_notice_id", "samNoticeId") or source_record_id or canonical_id
    summary = _first_text(
        record,
        "summary",
        "govtribe_ai_summary",
        "description",
        "descriptions",
        "content_snippet",
        "abstract",
    )
    return {
        "source_id": source_id,
        "source_name": source_name,
        "source_tier": int(source_config.get("trust_tier", 4) or 4),
        "opportunity_id": canonical_id,
        "canonical_record_id": canonical_id,
        "canonical_record_id_type": "govtribe_id" if source_record_id else "govtribe_derived_id",
        "notice_id": notice_id,
        "title": title,
        "url": source_url,
        "buyer": _first_text(
            record,
            "buyer",
            "agency",
            "federal_agency",
            "contracting_federal_agency",
            "funding_federal_agency",
            "department",
            "organizationName",
        )
        or "N/A",
        "opportunity_class": "contracts",
        "notice_type": _first_text(record, "notice_type", "noticeType", "opportunity_type", "opportunity_state", "type"),
        "solicitation_number": _first_text(record, "solicitation_number", "solicitationNumber", "solicitation", "number"),
        "posted_date": _first_text(record, "posted_date", "postedDate", "published_date", "publication_date"),
        "due_date": _first_text(record, "due_date", "dueDate", "response_deadline", "responseDeadLine", "responseDeadline") or "N/A",
        "location": _first_text(record, "location", "placeOfPerformance", "place_of_performance"),
        "naics": _record_naics_codes(record) or queried_naics,
        "other_taxonomy_tags": [],
        "set_aside": _first_text(record, "set_aside", "setAside", "set_aside_type", "typeOfSetAsideDescription"),
        "estimated_value": _record_value(record) or None,
        "summary": summary or "N/A",
        "point_of_contact": record.get("pointOfContact", []) if isinstance(record.get("pointOfContact"), list) else [],
        "resource_links": _record_resource_links(record, source_url),
        "retrieval_timestamp": utc_now_iso(),
        "raw_match_evidence": {
            "query": query,
            "queried_naics": queried_naics,
            "search_mode": search_mode,
            "tool_name": tool_name,
            "source_record_id": source_record_id,
            "full_desc_loaded": False,
        },
    }


def _collect_text_values(value: Any, *, keys: tuple[str, ...] = ("name", "title", "code", "value", "contract_number")) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                values.extend(_collect_text_values(value.get(key), keys=keys))
        if not values:
            for nested in value.values():
                values.extend(_collect_text_values(nested, keys=keys))
    elif isinstance(value, list):
        for item in value:
            values.extend(_collect_text_values(item, keys=keys))
    else:
        text = str(value or "").strip()
        if text:
            values.append(text)
    return dedupe_strings(values)


def _vendor_record_location(record: dict[str, Any]) -> str:
    value = record.get("location") or record.get("address")
    if isinstance(value, dict):
        parts = [
            _first_text(value, "city"),
            _first_text(value, "state", "state_code"),
            _first_text(value, "country", "country_code"),
        ]
        text = ", ".join(part for part in parts if part)
        if text:
            return text
    return _first_text(record, "location", "address")


def _vendor_parent_record(record: dict[str, Any]) -> dict[str, str]:
    parent = record.get("parent")
    if not isinstance(parent, dict):
        return {}
    parent_record = {
        "name": _first_text(parent, "name", "vendor_name", "recipient_name", "awardee"),
        "uei": _record_uei(parent),
        "govtribe_id": _record_identifier(parent),
        "govtribe_url": _record_url(parent, ""),
    }
    return {key: value for key, value in parent_record.items() if value}


def _vendor_record_buyers(record: dict[str, Any]) -> list[str]:
    buyers: list[str] = []
    for key in ("federal_contract_awards", "federal_contract_idvs", "awarded_federal_contract_vehicle"):
        values = record.get(key)
        if not isinstance(values, list):
            values = [values] if values else []
        for item in values:
            if not isinstance(item, dict):
                continue
            buyers.extend(
                _collect_text_values(
                    [
                        item.get("contracting_federal_agency"),
                        item.get("funding_federal_agency"),
                        item.get("federal_agency"),
                        item.get("agency"),
                    ],
                    keys=("name", "title", "value"),
                )
            )
    return _signal_values(buyers)[:8]


def _vendor_record_vehicles(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("awarded_federal_contract_vehicle", "federal_contract_idvs"):
        raw_items = record.get(key)
        if not isinstance(raw_items, list):
            raw_items = [raw_items] if raw_items else []
        current_items = [item for item in raw_items if not isinstance(item, dict) or _vehicle_access_is_current(item)]
        values.extend(_vehicle_names_from_values(current_items))
    return _signal_values(values)[:8]


def _vendor_record_expired_vehicles(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("awarded_federal_contract_vehicle", "federal_contract_idvs"):
        raw_items = record.get(key)
        if not isinstance(raw_items, list):
            raw_items = [raw_items] if raw_items else []
        values.extend(_expired_vehicle_names_from_values(raw_items))
    return _signal_values(values)[:8]


def _vendor_record_award_signals(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("federal_contract_awards", "federal_contract_idvs"):
        items = record.get(key)
        if not isinstance(items, list):
            items = [items] if items else []
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            title = _record_title(item)
            identifier = _record_identifier(item)
            agency = _first_text(item, "contracting_federal_agency", "funding_federal_agency", "federal_agency")
            parts = [part for part in (title, identifier, agency) if part and part != "GovTribe record"]
            if parts:
                values.append(" - ".join(parts[:3]))
    return _signal_values(values)[:6]


def _vendor_filter_values(vendor_record: dict[str, Any]) -> list[str]:
    return dedupe_strings(
        [
            str(vendor_record.get("uei") or "").strip(),
            str(vendor_record.get("govtribe_id") or "").strip(),
            str(vendor_record.get("external_record_id") or "").strip(),
        ]
    )[:3]


def _vendor_query_text(vendor_record: dict[str, Any]) -> str:
    values = [str(vendor_record.get("name") or "").strip(), str(vendor_record.get("uei") or "").strip()]
    return " ".join(value for value in values if value).strip()


def _set_vendor_filter_args(args: dict[str, Any], tool: dict[str, Any], vendor_record: dict[str, Any]) -> bool:
    values = _vendor_filter_values(vendor_record)
    if not values:
        return False
    properties = _schema_properties(tool)
    preferred_keys = ("vendor ids", "awardee vendor ids", "awardee ids")
    for wanted_key in preferred_keys:
        for name, spec in properties.items():
            if _normalize_key(name) == wanted_key and _is_array_prop(spec):
                args[name] = values
                return True
    return False


def _set_common_search_controls(args: dict[str, Any], tool: dict[str, Any], *, limit: int, per_page: int | None = None) -> None:
    properties = _schema_properties(tool)
    for name, spec in properties.items():
        key = _normalize_key(name)
        if _is_integer_prop(spec) and key in {"limit", "size", "page size", "per page", "max results"}:
            args[name] = per_page if per_page is not None and key == "per page" else limit
        elif _is_integer_prop(spec) and key == "page":
            args[name] = 1
        elif _is_string_prop(spec) and key == "search mode":
            allowed_modes = set(_enum_values(spec))
            if not allowed_modes or "keyword" in allowed_modes:
                args[name] = "keyword"


def _args_have_vendor_or_query_filter(args: dict[str, Any]) -> bool:
    for name, value in args.items():
        key = _normalize_key(name)
        if key in {"vendor ids", "awardee vendor ids", "awardee ids", "uei values", "govtribe ids"}:
            if isinstance(value, list) and value:
                return True
            if str(value or "").strip():
                return True
        if key in {"query", "q", "search", "search query"} and str(value or "").strip():
            return True
    return False


def _vendor_award_aggregation_selection(tool: dict[str, Any]) -> tuple[list[str], list[str]]:
    aggregation_spec = _schema_properties(tool).get("aggregations")
    if not _is_array_prop(aggregation_spec):
        return [], []
    allowed = set(_enum_values(aggregation_spec))
    selected = [item for item in VENDOR_AWARD_AGGREGATIONS if not allowed or item in allowed]
    skipped = [item for item in VENDOR_AWARD_AGGREGATIONS if allowed and item not in allowed]
    return selected, skipped


def _vendor_sci_aggregation_selection(tool: dict[str, Any]) -> tuple[list[str], list[str]]:
    aggregation_spec = _schema_properties(tool).get("aggregations")
    if not _is_array_prop(aggregation_spec):
        return [], []
    allowed = set(_enum_values(aggregation_spec))
    selected = [item for item in VENDOR_SCI_AGGREGATIONS if not allowed or item in allowed]
    skipped = [item for item in VENDOR_SCI_AGGREGATIONS if allowed and item not in allowed]
    return selected, skipped


def _vendor_sub_award_aggregation_selection(tool: dict[str, Any]) -> tuple[list[str], list[str]]:
    aggregation_spec = _schema_properties(tool).get("aggregations")
    if not _is_array_prop(aggregation_spec):
        return [], []
    allowed = set(_enum_values(aggregation_spec))
    selected = [item for item in VENDOR_SUB_AWARD_AGGREGATIONS if not allowed or item in allowed]
    skipped = [item for item in VENDOR_SUB_AWARD_AGGREGATIONS if allowed and item not in allowed]
    return selected, skipped


def _vendor_award_aggregation_arguments(tool: dict[str, Any], vendor_record: dict[str, Any]) -> dict[str, Any]:
    properties = _schema_properties(tool)
    args: dict[str, Any] = {}
    has_vendor_filter = _set_vendor_filter_args(args, tool, vendor_record)
    aggregations, _skipped = _vendor_award_aggregation_selection(tool)
    if aggregations:
        args["aggregations"] = aggregations
    _set_common_search_controls(args, tool, limit=0, per_page=0)
    if not has_vendor_filter:
        query = _vendor_query_text(vendor_record)
        for name, spec in properties.items():
            if _normalize_key(name) in {"query", "q", "search", "search query"} and _is_string_prop(spec) and query:
                args[name] = query
                break
    return args if args.get("aggregations") and _args_have_vendor_or_query_filter(args) else {}


def _vendor_sci_aggregation_arguments(tool: dict[str, Any], vendor_record: dict[str, Any]) -> dict[str, Any]:
    properties = _schema_properties(tool)
    args: dict[str, Any] = {}
    has_vendor_filter = _set_vendor_filter_args(args, tool, vendor_record)
    aggregations, _skipped = _vendor_sci_aggregation_selection(tool)
    if aggregations:
        args["aggregations"] = aggregations
    _set_common_search_controls(args, tool, limit=0, per_page=0)
    if not has_vendor_filter:
        query = _vendor_query_text(vendor_record)
        for name, spec in properties.items():
            if _normalize_key(name) in {"query", "q", "search", "search query"} and _is_string_prop(spec) and query:
                args[name] = query
                break
    return args if args.get("aggregations") and _args_have_vendor_or_query_filter(args) else {}


def _vendor_sub_award_search_arguments(tool: dict[str, Any], vendor_record: dict[str, Any], *, limit: int = 10) -> dict[str, Any]:
    properties = _schema_properties(tool)
    args: dict[str, Any] = {}
    has_vendor_filter = _set_vendor_filter_args(args, tool, vendor_record)
    aggregations, _skipped = _vendor_sub_award_aggregation_selection(tool)
    if aggregations:
        args["aggregations"] = aggregations
    fields_spec = properties.get("fields_to_return")
    if _is_array_prop(fields_spec):
        fields = _fields_for_tool(tool)
        if fields:
            args["fields_to_return"] = fields
    _set_common_search_controls(args, tool, limit=limit)
    if not has_vendor_filter:
        query = _vendor_query_text(vendor_record)
        for name, spec in properties.items():
            if _normalize_key(name) in {"query", "q", "search", "search query"} and _is_string_prop(spec) and query:
                args[name] = query
                break
    return args if _args_have_vendor_or_query_filter(args) else {}


def _vendor_vehicle_search_arguments(tool: dict[str, Any], vendor_record: dict[str, Any], *, limit: int = 15) -> dict[str, Any]:
    properties = _schema_properties(tool)
    args: dict[str, Any] = {}
    has_vendor_filter = _set_vendor_filter_args(args, tool, vendor_record)
    fields_spec = properties.get("fields_to_return")
    if _is_array_prop(fields_spec):
        fields = _fields_for_tool(tool)
        if fields:
            args["fields_to_return"] = fields
    _set_common_search_controls(args, tool, limit=limit)
    if not has_vendor_filter:
        query = _vendor_query_text(vendor_record)
        for name, spec in properties.items():
            if _normalize_key(name) in {"query", "q", "search", "search query"} and _is_string_prop(spec) and query:
                args[name] = query
                break
    return args if _args_have_vendor_or_query_filter(args) else {}


def _vendor_fcv_subcategory_search_arguments(tool: dict[str, Any], vendor_record: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
    properties = _schema_properties(tool)
    args: dict[str, Any] = {}
    has_vendor_filter = _set_vendor_filter_args(args, tool, vendor_record)
    fields_spec = properties.get("fields_to_return")
    if _is_array_prop(fields_spec):
        fields = _fields_for_tool(tool)
        if fields:
            args["fields_to_return"] = fields
    _set_common_search_controls(args, tool, limit=limit)
    if not has_vendor_filter:
        query = _vendor_query_text(vendor_record)
        for name, spec in properties.items():
            if _normalize_key(name) in {"query", "q", "search", "search query"} and _is_string_prop(spec) and query:
                args[name] = query
                break
    return args if _args_have_vendor_or_query_filter(args) else {}


def _aggregation_maps(value: Any) -> list[dict[str, Any]]:
    maps: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            maps.extend(_aggregation_maps(item))
        return maps
    if not isinstance(value, dict):
        return maps
    aggregations = value.get("aggregations")
    if isinstance(aggregations, dict):
        maps.append(aggregations)
    for nested in value.values():
        if isinstance(nested, (dict, list)):
            maps.extend(_aggregation_maps(nested))
    return maps


def _tool_result_aggregation_maps(tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    maps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in _extract_tool_values(tool_result):
        for item in _aggregation_maps(value):
            key = json.dumps(item, ensure_ascii=True, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            maps.append(item)
    return maps


def _bucket_key(bucket: Any) -> dict[str, Any]:
    if isinstance(bucket, dict):
        key = bucket.get("key")
        if isinstance(key, dict):
            return key
        if key not in (None, ""):
            return {"name": key}
    return bucket if isinstance(bucket, dict) else {}


def _bucket_name(bucket: Any) -> str:
    key = _bucket_key(bucket)
    return _first_text(key, "name", "title", "value", "key") or _first_text(bucket, "name", "title", "value", "key")


def _number_value(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("value", "amount", "sum", "avg", "min", "max", "count"):
            parsed = _number_value(value.get(key))
            if parsed is not None:
                return parsed
        return None
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _bucket_doc_count(bucket: Any) -> int | None:
    if not isinstance(bucket, dict):
        return None
    parsed = _number_value(bucket.get("doc_count"))
    return int(parsed) if parsed is not None else None


def _bucket_sum_value(bucket: Any) -> int | float | None:
    if not isinstance(bucket, dict):
        return None
    return _number_value(bucket.get("sum_value"))


def _compact_bucket_item(bucket: Any, *, name: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {}
    display_name = name if name is not None else _bucket_name(bucket)
    if display_name:
        item["name"] = display_name
    doc_count = _bucket_doc_count(bucket)
    if doc_count is not None:
        item["doc_count"] = doc_count
    dollars_obligated = _bucket_sum_value(bucket)
    if dollars_obligated is not None:
        item["dollars_obligated"] = dollars_obligated
    key = _bucket_key(bucket)
    govtribe_id = _first_text(key, "govtribe_id", "gov_tribe_i_d", "id")
    if govtribe_id:
        item["govtribe_id"] = govtribe_id
    url = _first_text(key, "govtribe_url", "url", "u_r_l", "link", "permalink")
    if url:
        item["govtribe_url"] = url
    return item


def _aggregation_buckets(aggregation_maps: list[dict[str, Any]], name: str) -> list[Any]:
    buckets: list[Any] = []
    for aggregation_map in aggregation_maps:
        aggregation = aggregation_map.get(name)
        if not isinstance(aggregation, dict):
            continue
        raw_buckets = aggregation.get("buckets")
        if isinstance(raw_buckets, list):
            buckets.extend(raw_buckets)
    return buckets


def _aggregation_named_items(aggregation_maps: list[dict[str, Any]], name: str, *, max_items: int = 10) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in _aggregation_buckets(aggregation_maps, name):
        item = _compact_bucket_item(bucket)
        display_name = str(item.get("name") or "").strip()
        if not display_name or display_name in seen:
            continue
        seen.add(display_name)
        items.append(item)
    return items[:max_items]


def _location_state_code(location: Any) -> str:
    key = _bucket_key(location)
    direct = _first_text(key, "state", "state_code", "stateCode")
    if direct:
        cleaned = re.sub(r"[^A-Za-z]", "", direct).upper()
        return cleaned if len(cleaned) == 2 else ""
    text = _bucket_name(location)
    match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*,?\s*(?:USA|United States)?\s*$", text)
    return match.group(1) if match else ""


def _aggregation_location_items(aggregation_maps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in _aggregation_buckets(aggregation_maps, "top_locations_by_dollars_obligated"):
        item = _compact_bucket_item(bucket)
        location_name = str(item.get("name") or "").strip()
        if not location_name or location_name in seen:
            continue
        state = _location_state_code(bucket)
        if state:
            item["state"] = state
        seen.add(location_name)
        items.append(item)
    return items[:10]


def _aggregation_naics_items(aggregation_maps: list[dict[str, Any]], aggregation_name: str = "top_naics_codes_by_dollars_obligated") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in _aggregation_buckets(aggregation_maps, aggregation_name):
        key = _bucket_key(bucket)
        naics_items = _record_naics_items(key)
        if not naics_items:
            naics_items = [item for item in [_naics_item_from_text(_bucket_name(bucket))] if item]
        for naics_item in naics_items:
            code = str(naics_item.get("code") or "").strip()
            label = str(naics_item.get("label") or "").strip()
            if not code and not label:
                continue
            identity = code or label
            if identity in seen:
                continue
            seen.add(identity)
            item = _compact_bucket_item(bucket, name=label or code)
            item["code"] = code
            item["label"] = label
            items.append(item)
            break
    return items[:10]


def _category_code_item_from_bucket(bucket: Any, *, code_keys: tuple[str, ...]) -> dict[str, Any]:
    key = _bucket_key(bucket)
    name = _bucket_name(bucket)
    code = _first_text(key, *code_keys)
    if not code:
        match = re.search(r"\b([A-Z]\d{3}|[A-Z]{1,2}\d{2,4}|\d{4,6})\b", name)
        if match:
            code = match.group(1)
    label = name
    if code and label:
        label = re.sub(rf"^\s*{re.escape(code)}\s*[-:–—]?\s*", "", label).strip()
    item = _compact_bucket_item(bucket, name=label or code)
    if code:
        item["code"] = code
    if label:
        item["label"] = label
    return item


def _aggregation_category_items(
    aggregation_maps: list[dict[str, Any]],
    aggregation_name: str,
    *,
    code_keys: tuple[str, ...],
    max_items: int = 10,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in _aggregation_buckets(aggregation_maps, aggregation_name):
        item = _category_code_item_from_bucket(bucket, code_keys=code_keys)
        identity = str(item.get("code") or item.get("name") or item.get("label") or "").strip()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        items.append(item)
    return items[:max_items]


def _aggregation_stats(
    aggregation_maps: list[dict[str, Any]],
    stat_names: dict[str, str],
) -> dict[str, dict[str, int | float]]:
    output: dict[str, dict[str, int | float]] = {}
    for aggregation_map in aggregation_maps:
        for raw_name, normalized_name in stat_names.items():
            stats = aggregation_map.get(raw_name)
            if not isinstance(stats, dict):
                continue
            normalized_stats: dict[str, int | float] = {}
            for key in ("count", "min", "max", "avg", "sum"):
                parsed = _number_value(stats.get(key))
                if parsed is not None:
                    normalized_stats[key] = parsed
            if normalized_stats:
                output[normalized_name] = normalized_stats
    return output


def _aggregation_value_stats(aggregation_maps: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    return _aggregation_stats(
        aggregation_maps,
        {
            "dollars_obligated_stats": "dollars_obligated",
            "ceiling_value_stats": "ceiling_value",
            "base_and_exercised_options_value_stats": "base_and_exercised_options_value",
        },
    )


def _vendor_award_profile_from_aggregations(aggregation_maps: list[dict[str, Any]]) -> dict[str, Any]:
    profile: dict[str, Any] = {}
    top_naics = _aggregation_naics_items(aggregation_maps)
    top_locations = _aggregation_location_items(aggregation_maps)
    top_set_asides = _aggregation_named_items(aggregation_maps, "top_set_aside_types_by_dollars_obligated")
    top_contract_types = _aggregation_named_items(aggregation_maps, "top_contract_types_by_dollars_obligated")
    top_pricing_types = _aggregation_named_items(aggregation_maps, "top_pricing_types_by_dollars_obligated")
    top_buyers = _aggregation_named_items(aggregation_maps, "top_contracting_federal_agencies_by_dollars_obligated")
    top_funding_buyers = _aggregation_named_items(aggregation_maps, "top_funding_federal_agencies_by_dollars_obligated")
    top_vehicles = _aggregation_named_items(aggregation_maps, "top_federal_contract_vehicles_by_dollars_obligated")
    value_stats = _aggregation_value_stats(aggregation_maps)
    for key, value in (
        ("top_naics", top_naics),
        ("top_locations", top_locations),
        ("top_set_asides", top_set_asides),
        ("top_contract_types", top_contract_types),
        ("top_pricing_types", top_pricing_types),
        ("top_contracting_buyers", top_buyers),
        ("top_funding_buyers", top_funding_buyers),
        ("top_contract_vehicles", top_vehicles),
        ("value_stats", value_stats),
    ):
        if value:
            profile[key] = value
    return profile


def _sci_value_stats(aggregation_maps: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    return _aggregation_stats(
        aggregation_maps,
        {
            "hours_invoiced_stats": "hours_invoiced",
            "ftes_stats": "ftes",
            "total_dollar_amount_invoiced_stats": "total_dollar_amount_invoiced",
            "total_contractor_hours_invoiced_stats": "total_contractor_hours_invoiced",
            "total_ftes_stats": "total_ftes",
            "total_dollars_obligated_stats": "total_dollars_obligated",
            "total_base_and_all_options_value_stats": "total_base_and_all_options_value",
            "subcontractor_count_stats": "subcontractor_count",
            "sub_hours_share_stats": "sub_hours_share",
            "derived_hourly_rate_stats": "derived_hourly_rate",
        },
    )


def _sci_profile_from_aggregations(aggregation_maps: list[dict[str, Any]]) -> dict[str, Any]:
    profile: dict[str, Any] = {}
    top_naics = _aggregation_naics_items(aggregation_maps, "top_naics_categories_by_doc_count")
    top_psc = _aggregation_category_items(
        aggregation_maps,
        "top_psc_categories_by_doc_count",
        code_keys=("psc", "psc_code", "p_s_c", "code", "id", "value"),
    )
    for key, value in (
        ("value_stats", _sci_value_stats(aggregation_maps)),
        ("top_fiscal_years", _aggregation_named_items(aggregation_maps, "top_fiscal_years_by_doc_count")),
        ("top_coverage_scopes", _aggregation_named_items(aggregation_maps, "top_coverage_scopes_by_doc_count")),
        ("top_roles", _aggregation_named_items(aggregation_maps, "top_roles_by_doc_count")),
        ("top_additional_reporting", _aggregation_named_items(aggregation_maps, "top_additional_reporting_by_doc_count")),
        ("top_contracting_buyers", _aggregation_named_items(aggregation_maps, "top_contracting_agencies_by_doc_count")),
        ("top_funding_buyers", _aggregation_named_items(aggregation_maps, "top_funding_agencies_by_doc_count")),
        ("top_states", _aggregation_named_items(aggregation_maps, "top_place_of_performance_states_by_doc_count")),
        ("top_countries", _aggregation_named_items(aggregation_maps, "top_place_of_performance_countries_by_doc_count")),
        ("top_contract_numbers", _aggregation_named_items(aggregation_maps, "top_contract_numbers_by_doc_count")),
        ("top_naics", top_naics),
        ("top_psc", top_psc),
    ):
        if value:
            profile[key] = value
    return profile


def _profile_codes(profile: dict[str, Any], key: str, *, max_items: int = 10) -> list[str]:
    values: list[str] = []
    items = profile.get(key)
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            values.append(str(item.get("code") or "").strip())
    return dedupe_strings([value for value in values if value])[:max_items]


def _normalized_prime_or_sub(values: list[str]) -> list[str]:
    roles: list[str] = []
    for value in values:
        normalized = _normalize_key(value)
        if normalized == "prime" or "prime" in normalized:
            roles.append("prime")
        if normalized == "sub" or "subcontract" in normalized:
            roles.append("subcontractor")
    return dedupe_strings(roles)


def _party_name(value: Any) -> str:
    return _first_text(value, "name", "vendor_name", "recipient_name", "awardee", "title", "value")


def _vendor_matches_party(vendor_record: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    vendor_names = [
        str(vendor_record.get("name") or ""),
        str(vendor_record.get("dba") or ""),
    ]
    vendor_ids = [
        str(vendor_record.get("uei") or ""),
        str(vendor_record.get("govtribe_id") or ""),
        str(vendor_record.get("external_record_id") or ""),
    ]
    party_names = [
        _party_name(value),
        _first_text(value, "dba", "doing_business_as"),
    ]
    party_ids = [
        _first_text(value, "uei", "uei_value", "ueiValue"),
        _first_text(value, "govtribe_id", "gov_tribe_i_d", "id"),
    ]
    normalized_vendor_ids = {_normalize_identifier(item) for item in vendor_ids if item}
    normalized_party_ids = {_normalize_identifier(item) for item in party_ids if item}
    if normalized_vendor_ids.intersection(normalized_party_ids):
        return True
    normalized_vendor_names = {_normalize_match_text(item) for item in vendor_names if item}
    normalized_party_names = {_normalize_match_text(item) for item in party_names if item}
    return bool(normalized_vendor_names.intersection(normalized_party_names))


def _sub_award_profile_from_records(
    records: list[dict[str, Any]],
    aggregation_maps: list[dict[str, Any]],
    vendor_record: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    profile: dict[str, Any] = {}
    prime_names: list[str] = []
    sub_names: list[str] = []
    buyers: list[str] = []
    signals: list[str] = []
    roles: list[str] = []
    for record in records[:12]:
        prime = record.get("prime_contractor")
        sub = record.get("sub_contractor")
        prime_name = _party_name(prime)
        sub_name = _party_name(sub)
        if prime_name:
            prime_names.append(prime_name)
        if sub_name:
            sub_names.append(sub_name)
        buyers.extend(
            _collect_text_values(
                [
                    record.get("contracting_federal_agency"),
                    record.get("funding_federal_agency"),
                ],
                keys=("name", "title", "value"),
            )
        )
        title = _record_title(record)
        award_date = _first_text(record, "award_date", "awardDate")
        parts = [part for part in (title if title != "GovTribe record" else "", prime_name, sub_name, award_date) if part]
        if parts:
            signals.append(" - ".join(parts[:4]))
        if _vendor_matches_party(vendor_record, sub):
            roles.append("subcontractor")
        if _vendor_matches_party(vendor_record, prime):
            roles.append("prime")
    top_awardees = _aggregation_named_items(aggregation_maps, "top_awardees_by_doc_count")
    top_contracting = _aggregation_named_items(aggregation_maps, "top_contracting_federal_agencies_by_doc_count")
    top_funding = _aggregation_named_items(aggregation_maps, "top_funding_federal_agencies_by_doc_count")
    for key, value in (
        ("top_prime_contractors", [{"name": item} for item in _signal_values(prime_names)]),
        ("top_subcontractors", [{"name": item} for item in _signal_values(sub_names)]),
        ("top_awardees", top_awardees),
        ("top_contracting_buyers", top_contracting),
        ("top_funding_buyers", top_funding),
        ("sub_award_signals", _signal_values(signals)),
    ):
        if value:
            profile[key] = value
    profile_buyers = _signal_values([*buyers, *_award_profile_names(profile, "top_contracting_buyers"), *_award_profile_names(profile, "top_funding_buyers")])
    return profile, _signal_values(profile_buyers)[:10], dedupe_strings(roles)


def _award_profile_names(profile: dict[str, Any], key: str, *, max_items: int = 10) -> list[str]:
    values: list[str] = []
    items = profile.get(key)
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            values.append(str(item.get("name") or item.get("label") or "").strip())
        else:
            values.append(str(item or "").strip())
    return _signal_values(values)[:max_items]


def _award_profile_naics_codes(profile: dict[str, Any], *, max_items: int = 10) -> list[str]:
    values: list[str] = []
    items = profile.get("top_naics")
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            values.append(str(item.get("code") or "").strip())
    return dedupe_strings([value for value in values if value])[:max_items]


def _award_profile_naics_items(profile: dict[str, Any], *, max_items: int = 10) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    raw_items = profile.get("top_naics")
    if not isinstance(raw_items, list):
        return []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        code = str(raw_item.get("code") or "").strip()
        label = str(raw_item.get("label") or raw_item.get("name") or "").strip()
        if code or label:
            item = {"code": code, "label": label}
            if item not in items:
                items.append(item)
    return items[:max_items]


def _fcv_subcategory_item(record: dict[str, Any]) -> dict[str, Any]:
    vehicle = record.get("federal_contract_vehicle")
    vehicle_name = _party_name(vehicle) if isinstance(vehicle, dict) else _first_text(record, "federal_contract_vehicle")
    name = _first_text(record, "name", "short_name", "alternate_name", "title")
    short_name = _first_text(record, "short_name", "shortName")
    alternate_name = _first_text(record, "alternate_name", "alternateName")
    display = short_name or name or alternate_name
    if vehicle_name and display and _normalize_identifier(vehicle_name) not in _normalize_identifier(display):
        display = f"{vehicle_name}: {display}"
    item: dict[str, Any] = {}
    for key, value in (
        ("name", name),
        ("short_name", short_name),
        ("alternate_name", alternate_name),
        ("display_name", display),
        ("vehicle", vehicle_name),
        ("govtribe_id", _record_identifier(record)),
        ("govtribe_url", _record_url(record, "")),
    ):
        if value:
            item[key] = value
    shared_ceiling = _number_value(record.get("shared_ceiling"))
    if shared_ceiling is not None:
        item["shared_ceiling"] = shared_ceiling
    return item


def _fcv_subcategory_profile_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    subcategories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        item = _fcv_subcategory_item(record)
        identity = str(item.get("govtribe_id") or item.get("display_name") or item.get("name") or "").strip()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        subcategories.append(item)
    return {"subcategories": subcategories[:15]} if subcategories else {}


def _fcv_subcategory_names(profile: dict[str, Any], *, max_items: int = 15) -> list[str]:
    values: list[str] = []
    items = profile.get("subcategories")
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            values.append(str(item.get("display_name") or item.get("name") or item.get("short_name") or "").strip())
    return _signal_values(values)[:max_items]


def _vehicle_url(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    key = _bucket_key(value)
    return _first_text(value, "govtribe_url", "url", "u_r_l", "link", "permalink") or _first_text(
        key,
        "govtribe_url",
        "url",
        "u_r_l",
        "link",
        "permalink",
    )


def _vehicle_alias_from_url(value: Any) -> str:
    url = _vehicle_url(value)
    slug_match = re.search(r"/([^/?#]+)(?:[?#].*)?$", url)
    if not slug_match:
        return ""
    tokens = [token for token in re.split(r"[^a-z0-9]+", slug_match.group(1).lower()) if token]
    if not tokens:
        return ""
    suffix_candidates: list[list[str]] = []
    last = tokens[-1]
    previous = tokens[-2] if len(tokens) > 1 else ""
    if len(last) <= 2 or any(char.isdigit() for char in last):
        if previous:
            suffix_candidates.append([previous, last])
        if len(tokens) > 2:
            suffix_candidates.append(tokens[-3:])
    elif len(last) <= 4:
        if previous and len(previous) <= 6:
            suffix_candidates.append([previous, last])
        suffix_candidates.append([last])
    elif len(last) <= 6:
        suffix_candidates.append([last])
    for candidate in suffix_candidates:
        alias = " ".join(token.upper() for token in candidate).strip()
        if len(_normalize_identifier(alias)) >= 3:
            return alias
    return ""


def _vehicle_display_name(value: Any) -> str:
    name = _bucket_name(value) if isinstance(value, dict) else _clean_signal_text(value)
    if not name:
        return ""
    alias = _vehicle_alias_from_url(value)
    if alias and _normalize_identifier(alias) not in _normalize_identifier(name):
        return f"{name} ({alias})"
    return name


def _aggregation_bucket_names(aggregation_maps: list[dict[str, Any]], names: tuple[str, ...], *, max_items: int = 10) -> list[str]:
    values: list[str] = []
    for aggregation_map in aggregation_maps:
        for name in names:
            aggregation = aggregation_map.get(name)
            if not isinstance(aggregation, dict):
                continue
            buckets = aggregation.get("buckets")
            if not isinstance(buckets, list):
                continue
            for bucket in buckets:
                values.append(_bucket_name(bucket))
    return _signal_values(values)[:max_items]


def _vendor_aggregation_buyers(aggregation_maps: list[dict[str, Any]]) -> list[str]:
    return _aggregation_bucket_names(
        aggregation_maps,
        (
            "top_contracting_federal_agencies_by_dollars_obligated",
            "top_funding_federal_agencies_by_dollars_obligated",
        ),
        max_items=10,
    )


def _vendor_aggregation_vehicles(aggregation_maps: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for aggregation_map in aggregation_maps:
        aggregation = aggregation_map.get("top_federal_contract_vehicles_by_dollars_obligated")
        if not isinstance(aggregation, dict):
            continue
        buckets = aggregation.get("buckets")
        if not isinstance(buckets, list):
            continue
        for bucket in buckets:
            if _vehicle_access_is_current(bucket):
                values.append(_vehicle_display_name(bucket))
    return _signal_values(values)[:12]


def _vendor_aggregation_expired_vehicles(aggregation_maps: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for aggregation_map in aggregation_maps:
        aggregation = aggregation_map.get("top_federal_contract_vehicles_by_dollars_obligated")
        if not isinstance(aggregation, dict):
            continue
        buckets = aggregation.get("buckets")
        if not isinstance(buckets, list):
            continue
        values.extend(_expired_vehicle_names_from_values(buckets))
    return _signal_values(values)[:12]


def _vehicle_names_from_values(values: list[Any]) -> list[str]:
    names: list[str] = []
    for value in values:
        if isinstance(value, dict):
            if _vehicle_access_is_current(value):
                names.append(_vehicle_display_name(value))
        else:
            names.extend(_collect_text_values(value, keys=("name", "title", "contract_number", "vehicle")))
    return _signal_values(names)


def _expired_vehicle_names_from_values(values: list[Any]) -> list[str]:
    names: list[str] = []
    for value in values:
        if isinstance(value, dict) and not _vehicle_access_is_current(value):
            names.append(_vehicle_display_name(value))
    return _signal_values(names)


def _vehicle_names_from_records(records: list[dict[str, Any]]) -> list[str]:
    return _vehicle_names_from_values(records)[:15]


def _expired_vehicle_names_from_records(records: list[dict[str, Any]]) -> list[str]:
    return _expired_vehicle_names_from_values(records)[:15]


def _vehicle_last_date_to_order(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    key = _bucket_key(value)
    return _first_text(value, "last_date_to_order", "lastDateToOrder", "last_order_date", "ordering_period_end") or _first_text(
        key,
        "last_date_to_order",
        "lastDateToOrder",
        "last_order_date",
        "ordering_period_end",
    )


def _parse_vehicle_date(value: Any) -> date | None:
    text = _clean_signal_text(value)
    if not text:
        return None
    iso_date = text.split("T", 1)[0]
    try:
        return date.fromisoformat(iso_date)
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _vehicle_access_is_current(value: Any) -> bool:
    parsed = _parse_vehicle_date(_vehicle_last_date_to_order(value))
    if parsed is None:
        return True
    return parsed >= date.fromisoformat(today_local_str())


def _enrich_vendor_record_from_awards_and_vehicles(
    *,
    client: MCPHttpClient,
    families: dict[str, dict[str, Any]],
    vendor_record: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    enriched = dict(vendor_record)
    tool_names: list[str] = []
    notes: list[str] = []
    errors: list[str] = []

    award_tool = families.get("awards")
    if award_tool:
        args = _vendor_award_aggregation_arguments(award_tool, vendor_record)
        if args:
            tool_name = _tool_name(award_tool)
            try:
                _selected_aggregations, skipped_aggregations = _vendor_award_aggregation_selection(award_tool)
                if skipped_aggregations:
                    notes.append(
                        "GovTribe award aggregations unavailable in tool schema: "
                        + ", ".join(skipped_aggregations)
                    )
                result = client.call_tool(tool_name, args)
                aggregation_maps = _tool_result_aggregation_maps(result)
                award_profile = _vendor_award_profile_from_aggregations(aggregation_maps)
                buyers = _vendor_aggregation_buyers(aggregation_maps)
                vehicles = _vendor_aggregation_vehicles(aggregation_maps)
                expired_vehicles = _vendor_aggregation_expired_vehicles(aggregation_maps)
                award_naics_items = _award_profile_naics_items(award_profile)
                award_naics = _award_profile_naics_codes(award_profile)
                locations = _award_profile_names(award_profile, "top_locations")
                states = dedupe_strings(
                    [
                        str(item.get("state") or "").strip()
                        for item in award_profile.get("top_locations", [])
                        if isinstance(item, dict) and str(item.get("state") or "").strip()
                    ]
                )
                set_asides = _award_profile_names(award_profile, "top_set_asides")
                contract_types = _award_profile_names(award_profile, "top_contract_types")
                pricing_types = _award_profile_names(award_profile, "top_pricing_types")
                if award_profile:
                    enriched["govtribe_award_profile"] = award_profile
                    enriched["prime_or_sub"] = _signal_values(
                        [*coerce_string_list(enriched.get("prime_or_sub"), max_items=10), "prime"]
                    )[:4]
                if award_naics_items:
                    existing_items = [item for item in enriched.get("naics_items", []) if isinstance(item, dict)]
                    enriched["naics_items"] = [*existing_items]
                    seen_items = {json.dumps(item, ensure_ascii=True, sort_keys=True) for item in existing_items}
                    for item in award_naics_items:
                        key = json.dumps(item, ensure_ascii=True, sort_keys=True)
                        if key in seen_items:
                            continue
                        seen_items.add(key)
                        enriched["naics_items"].append(item)
                    enriched["naics_items"] = enriched["naics_items"][:12]
                if award_naics:
                    enriched["naics"] = dedupe_strings(
                        [*coerce_string_list(enriched.get("naics"), max_items=20), *award_naics]
                    )[:12]
                if buyers:
                    enriched["buyers"] = _signal_values([*coerce_string_list(enriched.get("buyers"), max_items=20), *buyers])[:12]
                if vehicles:
                    enriched["contract_vehicles"] = _signal_values(
                        [*coerce_string_list(enriched.get("contract_vehicles"), max_items=20), *vehicles]
                    )[:15]
                if expired_vehicles:
                    enriched["expired_contract_vehicles"] = _signal_values(
                        [*coerce_string_list(enriched.get("expired_contract_vehicles"), max_items=20), *expired_vehicles]
                    )[:15]
                if locations:
                    enriched["places_of_performance"] = _signal_values(
                        [*coerce_string_list(enriched.get("places_of_performance"), max_items=20), *locations]
                    )[:12]
                if states:
                    enriched["preferred_states"] = dedupe_strings(
                        [*coerce_string_list(enriched.get("preferred_states"), max_items=20), *states]
                    )[:12]
                if set_asides:
                    enriched["set_asides"] = _signal_values(
                        [*coerce_string_list(enriched.get("set_asides"), max_items=20), *set_asides]
                    )[:12]
                if contract_types:
                    enriched["contract_types"] = _signal_values(
                        [*coerce_string_list(enriched.get("contract_types"), max_items=20), *contract_types]
                    )[:12]
                if pricing_types:
                    enriched["pricing_types"] = _signal_values(
                        [*coerce_string_list(enriched.get("pricing_types"), max_items=20), *pricing_types]
                    )[:12]
                records, call_errors = _tool_result_records_and_errors(result)
                if records:
                    enriched["award_signals"] = _signal_values(
                        [*coerce_string_list(enriched.get("award_signals"), max_items=20), *_vendor_record_award_signals({"federal_contract_awards": records})]
                    )[:10]
                errors.extend(f"{tool_name}: {error}" for error in call_errors)
                tool_names.append(tool_name)
                notes.append(f"GovTribe MCP award aggregations used: {tool_name}")
            except (MCPResponseError, MCPHTTPError) as exc:
                errors.append(f"{tool_name}: {exc}")

    sci_tool = families.get("service_contract_inventory")
    if sci_tool:
        args = _vendor_sci_aggregation_arguments(sci_tool, vendor_record)
        if args:
            tool_name = _tool_name(sci_tool)
            try:
                _selected_aggregations, skipped_aggregations = _vendor_sci_aggregation_selection(sci_tool)
                if skipped_aggregations:
                    notes.append(
                        "GovTribe Service Contract Inventory aggregations unavailable in tool schema: "
                        + ", ".join(skipped_aggregations)
                    )
                result = client.call_tool(tool_name, args)
                aggregation_maps = _tool_result_aggregation_maps(result)
                sci_profile = _sci_profile_from_aggregations(aggregation_maps)
                roles = _award_profile_names(sci_profile, "top_roles")
                prime_or_sub = _normalized_prime_or_sub(roles)
                buyers = _signal_values(
                    [
                        *_award_profile_names(sci_profile, "top_contracting_buyers"),
                        *_award_profile_names(sci_profile, "top_funding_buyers"),
                    ]
                )
                states = _award_profile_names(sci_profile, "top_states")
                sci_naics_items = _award_profile_naics_items(sci_profile)
                sci_naics = _award_profile_naics_codes(sci_profile)
                psc_codes = _profile_codes(sci_profile, "top_psc")
                if sci_profile:
                    enriched["govtribe_service_contract_inventory_profile"] = sci_profile
                if roles:
                    enriched["service_contract_roles"] = _signal_values(
                        [*coerce_string_list(enriched.get("service_contract_roles"), max_items=20), *roles]
                    )[:12]
                if prime_or_sub:
                    enriched["prime_or_sub"] = _signal_values(
                        [*coerce_string_list(enriched.get("prime_or_sub"), max_items=10), *prime_or_sub]
                    )[:4]
                if buyers:
                    enriched["buyers"] = _signal_values([*coerce_string_list(enriched.get("buyers"), max_items=20), *buyers])[:12]
                if states:
                    enriched["preferred_states"] = dedupe_strings(
                        [*coerce_string_list(enriched.get("preferred_states"), max_items=20), *states]
                    )[:12]
                if sci_naics_items:
                    existing_items = [item for item in enriched.get("naics_items", []) if isinstance(item, dict)]
                    enriched["naics_items"] = [*existing_items]
                    seen_items = {json.dumps(item, ensure_ascii=True, sort_keys=True) for item in existing_items}
                    for item in sci_naics_items:
                        key = json.dumps(item, ensure_ascii=True, sort_keys=True)
                        if key in seen_items:
                            continue
                        seen_items.add(key)
                        enriched["naics_items"].append(item)
                    enriched["naics_items"] = enriched["naics_items"][:12]
                if sci_naics:
                    enriched["naics"] = dedupe_strings(
                        [*coerce_string_list(enriched.get("naics"), max_items=20), *sci_naics]
                    )[:12]
                if psc_codes:
                    enriched["psc_codes"] = dedupe_strings(
                        [*coerce_string_list(enriched.get("psc_codes"), max_items=20), *psc_codes]
                    )[:12]
                records, call_errors = _tool_result_records_and_errors(result)
                errors.extend(f"{tool_name}: {error}" for error in call_errors)
                if records:
                    enriched["service_contract_inventory_signals"] = _signal_values(
                        [
                            *coerce_string_list(enriched.get("service_contract_inventory_signals"), max_items=20),
                            *[_record_title(record) for record in records[:8]],
                        ]
                    )[:10]
                tool_names.append(tool_name)
                notes.append(f"GovTribe Service Contract Inventory aggregations used: {tool_name}")
            except (MCPResponseError, MCPHTTPError) as exc:
                errors.append(f"{tool_name}: {exc}")

    vehicle_tool = families.get("vehicles")
    if vehicle_tool:
        args = _vendor_vehicle_search_arguments(vehicle_tool, vendor_record)
        if args:
            tool_name = _tool_name(vehicle_tool)
            try:
                result = client.call_tool(tool_name, args)
                records, call_errors = _tool_result_records_and_errors(result)
                vehicle_names = _vehicle_names_from_records(records)
                expired_vehicle_names = _expired_vehicle_names_from_records(records)
                if vehicle_names:
                    enriched["contract_vehicles"] = _signal_values(
                        [*coerce_string_list(enriched.get("contract_vehicles"), max_items=20), *vehicle_names]
                    )[:15]
                if expired_vehicle_names:
                    enriched["expired_contract_vehicles"] = _signal_values(
                        [*coerce_string_list(enriched.get("expired_contract_vehicles"), max_items=20), *expired_vehicle_names]
                    )[:15]
                errors.extend(f"{tool_name}: {error}" for error in call_errors)
                tool_names.append(tool_name)
                notes.append(f"GovTribe MCP vehicle search used: {tool_name}")
            except (MCPResponseError, MCPHTTPError) as exc:
                errors.append(f"{tool_name}: {exc}")

    subcategory_tool = families.get("fcv_subcategories")
    if subcategory_tool:
        args = _vendor_fcv_subcategory_search_arguments(subcategory_tool, vendor_record)
        if args:
            tool_name = _tool_name(subcategory_tool)
            try:
                result = client.call_tool(tool_name, args)
                records, call_errors = _tool_result_records_and_errors(result)
                subcategory_profile = _fcv_subcategory_profile_from_records(records)
                subcategory_names = _fcv_subcategory_names(subcategory_profile)
                if subcategory_profile:
                    enriched["govtribe_vehicle_subcategory_profile"] = subcategory_profile
                if subcategory_names:
                    enriched["contract_vehicle_subcategories"] = _signal_values(
                        [*coerce_string_list(enriched.get("contract_vehicle_subcategories"), max_items=20), *subcategory_names]
                    )[:15]
                errors.extend(f"{tool_name}: {error}" for error in call_errors)
                tool_names.append(tool_name)
                notes.append(f"GovTribe vehicle subcategory search used: {tool_name}")
            except (MCPResponseError, MCPHTTPError) as exc:
                errors.append(f"{tool_name}: {exc}")

    sub_award_tool = families.get("sub_awards")
    if sub_award_tool:
        args = _vendor_sub_award_search_arguments(sub_award_tool, vendor_record)
        if args:
            tool_name = _tool_name(sub_award_tool)
            try:
                _selected_aggregations, skipped_aggregations = _vendor_sub_award_aggregation_selection(sub_award_tool)
                if skipped_aggregations:
                    notes.append(
                        "GovTribe sub-award aggregations unavailable in tool schema: "
                        + ", ".join(skipped_aggregations)
                    )
                result = client.call_tool(tool_name, args)
                records, call_errors = _tool_result_records_and_errors(result)
                aggregation_maps = _tool_result_aggregation_maps(result)
                sub_award_profile, buyers, roles = _sub_award_profile_from_records(records, aggregation_maps, vendor_record)
                if sub_award_profile:
                    enriched["govtribe_sub_award_profile"] = sub_award_profile
                if buyers:
                    enriched["buyers"] = _signal_values([*coerce_string_list(enriched.get("buyers"), max_items=20), *buyers])[:12]
                if roles:
                    enriched["prime_or_sub"] = _signal_values(
                        [*coerce_string_list(enriched.get("prime_or_sub"), max_items=10), *roles]
                    )[:4]
                prime_partners = _award_profile_names(sub_award_profile, "top_prime_contractors")
                if "subcontractor" in roles and prime_partners:
                    enriched["teaming_preferences"] = _signal_values(
                        [
                            *coerce_string_list(enriched.get("teaming_preferences"), max_items=20),
                            *[f"Historical sub-award prime: {name}" for name in prime_partners],
                        ]
                    )[:12]
                sub_award_signals = coerce_string_list(sub_award_profile.get("sub_award_signals"), max_items=10)
                if sub_award_signals:
                    enriched["award_signals"] = _signal_values(
                        [*coerce_string_list(enriched.get("award_signals"), max_items=20), *sub_award_signals]
                    )[:10]
                errors.extend(f"{tool_name}: {error}" for error in call_errors)
                tool_names.append(tool_name)
                notes.append(f"GovTribe sub-award search used: {tool_name}")
            except (MCPResponseError, MCPHTTPError) as exc:
                errors.append(f"{tool_name}: {exc}")

    return enriched, dedupe_strings([*notes, *errors]), dedupe_strings(tool_names)


def _normalize_vendor_record(record: dict[str, Any], *, source_config: dict[str, Any], default_url: str) -> dict[str, Any]:
    source_url = _record_url(record, default_url)
    name = _first_text(record, "name", "vendor_name", "recipient_name", "awardee") or "Vendor"
    dba = _first_text(record, "dba", "doing_business_as")
    summary = _first_text(record, "govtribe_ai_summary", "summary", "description")
    naics_items = _record_naics_items(record)
    naics_codes = [item["code"] for item in naics_items if item.get("code")]
    certifications = _signal_values(
        [
            *_collect_text_values(record.get("sba_certifications"), keys=("name", "title", "value")),
            *_collect_text_values(record.get("business_types"), keys=("name", "title", "value")),
        ],
        allow_generic_metadata=True,
    )[:10]
    vehicles = _vendor_record_vehicles(record)
    expired_vehicles = _vendor_record_expired_vehicles(record)
    buyers = _vendor_record_buyers(record)
    award_signals = _vendor_record_award_signals(record)
    keywords = _signal_values([*naics_codes, *vehicles, *buyers])[:12]
    prime_or_sub = ["subcontractor"] if record.get("federal_contract_sub_awards") else []
    parent_or_child = _first_text(record, "parent_or_child", "parentOrChild")
    parent_vendor = _vendor_parent_record(record)
    vendor_hierarchy = {
        key: value
        for key, value in {
            "parent_or_child": parent_or_child,
            "parent": parent_vendor,
        }.items()
        if value
    }
    return {
        "source_id": str(source_config.get("id") or SOURCE_ID).strip(),
        "source_name": str(source_config.get("name") or SOURCE_NAME).strip(),
        "external_record_id": _record_identifier(record),
        "source_url": source_url,
        "govtribe_id": _record_identifier(record),
        "govtribe_url": source_url,
        "name": name,
        "dba": dba,
        "uei": _record_uei(record),
        "summary": summary,
        "location": _vendor_record_location(record),
        "naics": naics_codes,
        "naics_items": naics_items,
        "certifications": certifications,
        "contract_vehicles": vehicles,
        "expired_contract_vehicles": expired_vehicles,
        "buyers": buyers,
        "award_signals": award_signals,
        "keywords": keywords,
        "prime_or_sub": prime_or_sub,
        "parent_or_child": parent_or_child,
        "parent_vendor": parent_vendor,
        "vendor_hierarchy": vendor_hierarchy,
        "raw_record": record,
    }


def _select_vendor_record(records: list[dict[str, Any]], lookup: str) -> dict[str, Any] | None:
    if not records:
        return None
    cleaned_uei = _clean_uei(lookup)
    if _is_likely_uei(lookup):
        for record in records:
            if _clean_uei(_record_uei(record)) == cleaned_uei:
                return record
    slug = _lookup_url_slug(lookup)
    if slug:
        normalized_slug = _normalize_identifier(slug)
        for record in records:
            url = _record_url(record, "")
            identifier = _record_identifier(record)
            if normalized_slug and (normalized_slug in _normalize_identifier(url) or normalized_slug == _normalize_identifier(identifier)):
                return record
    lookup_name = _normalize_match_text(_vendor_lookup_query(lookup))
    for record in records:
        for value in (_first_text(record, "name"), _first_text(record, "dba")):
            if lookup_name and _normalize_match_text(value) == lookup_name:
                return record
    return records[0]


class GovTribeMCPCommercialIntelProvider:
    source_id = SOURCE_ID
    source_name = SOURCE_NAME

    def __init__(self, source_config: dict[str, Any], client: MCPHttpClient | None = None):
        self.source_config = source_config
        self.client = client

    def is_configured(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if not govtribe_authorization_token():
            missing.append("GOVTRIBE_MCP_API_KEY")
        return not missing, missing

    def _client(self) -> MCPHttpClient:
        if self.client is not None:
            return self.client
        return MCPHttpClient(
            url=govtribe_mcp_url(),
            bearer_token=govtribe_authorization_token(),
            timeout_seconds=govtribe_timeout_seconds(),
        )

    def _tool_families(self, client: MCPHttpClient) -> dict[str, dict[str, Any]]:
        tools = client.list_tools()
        return discover_tool_families(tools)

    def resolve_vendor_profile(self, *, lookup: str, limit: int = 5) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "status": "not_configured",
                "matched": False,
                "lookup": lookup,
                "vendor_record": {},
                "notes": [f"Missing env vars: {', '.join(missing)}"],
                "tool_name": "",
            }

        client = self._client()
        default_url = str(self.source_config.get("homepage") or govtribe_mcp_url()).strip()
        try:
            families = self._tool_families(client)
            tool = families.get("vendors")
            if not tool:
                return {
                    "source_id": self.source_id,
                    "source_name": self.source_name,
                    "status": "tool_contract_unavailable",
                    "matched": False,
                    "lookup": lookup,
                    "vendor_record": {},
                    "notes": ["GovTribe MCP did not expose a compatible vendor search tool."],
                    "tool_name": "",
                }
            selected = None
            records: list[dict[str, Any]] = []
            extraction_errors: list[str] = []
            for query in _vendor_lookup_queries(lookup) or [str(lookup or "").strip()]:
                args = _vendor_tool_arguments(tool, lookup=lookup, limit=limit, query=query)
                result = client.call_tool(_tool_name(tool), args)
                records, errors = _tool_result_records_and_errors(result)
                extraction_errors.extend(errors)
                selected = _select_vendor_record(records, lookup)
                if selected:
                    break
        except MCPResponseError as exc:
            status = "tool_contract_unavailable" if exc.code == -32602 else "error"
            return {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "status": status,
                "matched": False,
                "lookup": lookup,
                "vendor_record": {},
                "notes": [str(exc)],
                "tool_name": "",
            }
        except MCPHTTPError as exc:
            return {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "status": "error",
                "matched": False,
                "lookup": lookup,
                "vendor_record": {},
                "notes": [str(exc)],
                "tool_name": "",
            }
        except Exception as exc:
            return {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "status": "error",
                "matched": False,
                "lookup": lookup,
                "vendor_record": {},
                "notes": [str(exc)],
                "tool_name": "",
            }

        if not selected:
            return {
                "source_id": self.source_id,
                "source_name": self.source_name,
                "status": "no_match",
                "matched": False,
                "lookup": lookup,
                "vendor_record": {},
                "notes": dedupe_strings(extraction_errors) or ["GovTribe vendor search returned no matching records."],
                "tool_name": _tool_name(tool),
            }
        normalized = _normalize_vendor_record(selected, source_config=self.source_config, default_url=default_url)
        enrichment_notes: list[str] = []
        enrichment_tool_names: list[str] = []
        try:
            normalized, enrichment_notes, enrichment_tool_names = _enrich_vendor_record_from_awards_and_vehicles(
                client=client,
                families=families,
                vendor_record=normalized,
            )
        except Exception as exc:
            enrichment_notes = [f"GovTribe vendor award/vehicle enrichment skipped: {exc}"]
        return {
            "source_id": normalized["source_id"],
            "source_name": normalized["source_name"],
            "status": "ok",
            "matched": True,
            "lookup": lookup,
            "matched_by": "GovTribe vendor search",
            "external_record_id": normalized.get("external_record_id", ""),
            "source_url": normalized.get("source_url", ""),
            "vendor_record": normalized,
            "notes": dedupe_strings([f"GovTribe MCP tools used: {_tool_name(tool)}", *enrichment_notes]),
            "tool_name": ", ".join(dedupe_strings([_tool_name(tool), *enrichment_tool_names])),
        }

    def search_scan_opportunities(
        self,
        *,
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any],
        limit: int = 25,
    ) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return {
                "status": "not_configured",
                "records": [],
                "notes": [f"Missing env vars: {', '.join(missing)}"],
                "queried_naics": [],
                "tool_name": "",
            }

        client = self._client()
        default_url = str(self.source_config.get("homepage") or govtribe_mcp_url()).strip()
        queried_naics = _vendor_retrieval_naics(vendor_profile, preferences)
        queries = _scan_retrieval_queries(vendor_profile, preferences)
        due_date_from, due_date_to = _scan_retrieval_due_date_range(preferences)
        if not queries and not queried_naics:
            return {
                "status": "no_match",
                "records": [],
                "notes": ["No vendor-specific GovTribe scan retrieval terms or NAICS were available."],
                "queried_naics": [],
                "tool_name": "",
            }
        if not queries:
            queries = [(" ".join(queried_naics), "keyword")]
        try:
            families = self._tool_families(client)
            tool = families.get("opportunities")
            if not tool:
                return {
                    "status": "tool_contract_unavailable",
                    "records": [],
                    "notes": ["GovTribe MCP did not expose a compatible federal opportunities search tool."],
                    "queried_naics": queried_naics,
                    "tool_name": "",
                }

            normalized: dict[str, dict[str, Any]] = {}
            tool_names: list[str] = []
            extraction_errors: list[str] = []
            semantic_expansion_attempted = False
            for query, search_mode in queries:
                normalized_search_mode = _search_mode_for_query(query, search_mode)
                if normalized_search_mode == "semantic":
                    semantic_expansion_attempted = True
                found, tool_name, call_errors = _call_search(
                    client,
                    tool=tool,
                    query=query,
                    naics_codes=queried_naics,
                    limit=limit,
                    search_mode=normalized_search_mode,
                    due_date_from=due_date_from,
                    due_date_to=due_date_to,
                    opportunity_states=["Posted", "Updated"],
                    sort=_scan_retrieval_sort(normalized_search_mode),
                )
                tool_names.append(tool_name)
                extraction_errors.extend(f"{tool_name}: {error}" for error in call_errors)
                for item in found:
                    record = _normalize_scan_opportunity(
                        record=item,
                        source_config=self.source_config,
                        query=query,
                        queried_naics=queried_naics,
                        search_mode=normalized_search_mode,
                        tool_name=tool_name,
                        default_url=default_url,
                    )
                    key = str(record.get("canonical_record_id") or record.get("url") or record.get("title") or "").strip()
                    if key:
                        normalized[key] = record
                if normalized:
                    break
                if call_errors:
                    break
        except MCPResponseError as exc:
            status = "tool_contract_unavailable" if exc.code == -32602 else "error"
            return {
                "status": status,
                "records": [],
                "notes": [str(exc)],
                "queried_naics": queried_naics,
                "tool_name": "",
            }
        except MCPHTTPError as exc:
            return {
                "status": "error",
                "records": [],
                "notes": [str(exc)],
                "queried_naics": queried_naics,
                "tool_name": "",
            }
        except Exception as exc:
            return {
                "status": "error",
                "records": [],
                "notes": [str(exc)],
                "queried_naics": queried_naics,
                "tool_name": "",
            }

        records = list(normalized.values())
        if not records and extraction_errors:
            return {
                "status": "error",
                "records": [],
                "notes": dedupe_strings(extraction_errors),
                "queried_naics": queried_naics,
                "tool_name": ", ".join(dedupe_strings(tool_names)),
            }
        notes = [
            *([f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}"] if tool_names else []),
            f"GovTribe scan due-date filter: {due_date_from} to {due_date_to}.",
            *extraction_errors,
        ]
        if semantic_expansion_attempted:
            notes.append(
                "GovTribe semantic expansion ran after keyword/structured-filter retrieval returned no records, "
                "with active-state and due-date filters retained."
            )
        return {
            "status": "partial_error" if records and extraction_errors else ("ok" if records else "no_match"),
            "records": records,
            "notes": dedupe_strings(notes),
            "queried_naics": queried_naics,
            "tool_name": ", ".join(dedupe_strings(tool_names)),
        }

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
            return default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )

        opportunity = _scan_record_brief(record, hydrated_text)
        query = _query_for_opportunity(opportunity)
        if not query:
            return default_result(self.source_id, self.source_name, "no_match", notes=["No GovTribe search terms were available."])

        client = self._client()
        default_url = str(self.source_config.get("homepage") or govtribe_mcp_url()).strip()
        try:
            families = self._tool_families(client)
            tool = families.get("opportunities")
            if not tool:
                return default_result(
                    self.source_id,
                    self.source_name,
                    "tool_contract_unavailable",
                    notes=["GovTribe MCP did not expose a compatible federal opportunities search tool."],
                )

            records: list[dict[str, Any]] = []
            tool_names: list[str] = []
            extraction_errors: list[str] = []
            solicitation_number = str(opportunity.get("solicitation_number") or "").strip()
            if solicitation_number:
                found, tool_name, call_errors = _call_search(
                    client,
                    tool=tool,
                    query=solicitation_number,
                    solicitation_number=solicitation_number,
                    title=str(opportunity.get("title") or ""),
                    buyer=str(opportunity.get("buyer") or ""),
                )
                records.extend(found)
                tool_names.append(tool_name)
                extraction_errors.extend(f"{tool_name}: {error}" for error in call_errors)
            if not records:
                found, tool_name, call_errors = _call_search(
                    client,
                    tool=tool,
                    query=query,
                    solicitation_number=solicitation_number,
                    title=str(opportunity.get("title") or ""),
                    buyer=str(opportunity.get("buyer") or ""),
                )
                records.extend(found)
                tool_names.append(tool_name)
                extraction_errors.extend(f"{tool_name}: {error}" for error in call_errors)
        except MCPResponseError as exc:
            status = "tool_contract_unavailable" if exc.code == -32602 else "error"
            return default_result(self.source_id, self.source_name, status, notes=[str(exc)])
        except MCPHTTPError as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])
        except Exception as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])

        if not records and extraction_errors:
            return default_result(
                self.source_id,
                self.source_name,
                "error",
                notes=dedupe_strings(extraction_errors),
            )

        if not records:
            return default_result(
                self.source_id,
                self.source_name,
                "no_match",
                notes=["GovTribe MCP opportunity search returned no matching records."],
            )

        return _records_to_result(
            source_config=self.source_config,
            status="partial_error" if extraction_errors else "ok",
            matched_by="GovTribe opportunity search by solicitation number or title/buyer query",
            records_by_family=[("opportunities", item) for item in records],
            notes=[f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}", *extraction_errors],
            default_url=default_url,
        )

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
            return default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )

        opportunity = _capture_context_brief(resolved, notice_context_text, attachment_bundle)
        vendor = _vendor_brief(vendor_profile, preferences)
        query = _query_for_opportunity(opportunity)
        if vendor.get("vendor_name"):
            query = f"{query} {vendor.get('vendor_name')}".strip()
        if not query:
            return default_result(self.source_id, self.source_name, "no_match", notes=["No GovTribe capture search terms were available."])

        client = self._client()
        default_url = str(self.source_config.get("homepage") or govtribe_mcp_url()).strip()
        records_by_family: list[tuple[str, dict[str, Any]]] = []
        tool_names: list[str] = []
        errors: list[str] = []
        try:
            families = self._tool_families(client)
            selected = {
                family: tool
                for family, tool in families.items()
                if family in {"opportunities", "awards", "idvs", "vehicles", "government_files"}
            }
            if not selected:
                return default_result(
                    self.source_id,
                    self.source_name,
                    "tool_contract_unavailable",
                    notes=["GovTribe MCP did not expose compatible opportunity, award, IDV, vehicle, or government-file search tools."],
                )

            solicitation_number = str(opportunity.get("solicitation_number") or "").strip()
            for family, tool in selected.items():
                family_query = solicitation_number if family == "opportunities" and solicitation_number else query
                try:
                    found, tool_name, call_errors = _call_search(
                        client,
                        tool=tool,
                        query=family_query,
                        solicitation_number=solicitation_number,
                        title=str(opportunity.get("title") or ""),
                        buyer=str(opportunity.get("buyer") or ""),
                    )
                    records_by_family.extend((family, item) for item in found)
                    tool_names.append(tool_name)
                    errors.extend(f"{tool_name}: {error}" for error in call_errors)
                except MCPResponseError as exc:
                    if exc.code == -32602:
                        errors.append(f"{_tool_name(tool)} schema incompatible")
                    else:
                        errors.append(f"{_tool_name(tool)}: {exc}")
                except MCPHTTPError as exc:
                    errors.append(f"{_tool_name(tool)}: {exc}")
        except MCPHTTPError as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])
        except MCPResponseError as exc:
            status = "tool_contract_unavailable" if exc.code == -32602 else "error"
            return default_result(self.source_id, self.source_name, status, notes=[str(exc)])
        except Exception as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])

        if not records_by_family:
            status = (
                "tool_contract_unavailable"
                if errors and all("schema incompatible" in error for error in errors)
                else ("error" if errors else "no_match")
            )
            return default_result(
                self.source_id,
                self.source_name,
                status,
                notes=errors or ["GovTribe MCP capture enrichment returned no matching records."],
            )

        return _records_to_result(
            source_config=self.source_config,
            status="partial_error" if errors else "ok",
            matched_by="GovTribe MCP capture enrichment across available opportunity, award, IDV, vehicle, and government-file tools",
            records_by_family=records_by_family,
            notes=[f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}", *errors],
            default_url=default_url,
        )
