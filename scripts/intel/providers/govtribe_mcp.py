from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from typing import Any

from common.paths import today_local_str, utc_now_iso
from common.evidence_model import (
    evidence_model_competitive_notes,
    evidence_model_next_questions,
    evidence_model_related_procurement_lines,
    evidence_model_vehicle_signals,
    normalize_provider_evidence_model,
)
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

FAMILY_TOOL_GUIDE: dict[str, dict[str, Any]] = {
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
        "preferred_names": ("Search_Federal_Contract_Vehicles",),
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
    "naics",
    "naics_code",
    "naics_codes",
    "ncode",
    "ncodes",
    "solicitation_numbers",
    "piids",
    "govtribe_ids",
}


def govtribe_mcp_url() -> str:
    return str(os.getenv("GOVTRIBE_MCP_URL") or DEFAULT_GOVTRIBE_MCP_URL).strip()


def govtribe_timeout_seconds() -> int:
    return env_int("GOVTRIBE_MCP_TIMEOUT_SECONDS", 90)


def govtribe_authorization_token() -> str:
    return clean_bearer_token(str(os.getenv("GOVTRIBE_MCP_API_KEY") or ""))


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


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
    company = vendor_profile.get("company") if isinstance(vendor_profile.get("company"), dict) else {}
    terms.extend(coerce_string_list(company.get("summary"), max_items=1))
    for item in vendor_profile.get("core_competencies", []):
        if isinstance(item, dict):
            terms.extend(coerce_string_list([item.get("name"), item.get("summary")], max_items=2))
        else:
            terms.extend(coerce_string_list(item, max_items=1))
    terms.extend(coerce_string_list((vendor_profile.get("other_taxonomy_tags") or {}).get("keywords"), max_items=10) if isinstance(vendor_profile.get("other_taxonomy_tags"), dict) else [])
    terms.extend(_preference_values(preferences, "soft_preferences", "positive_keywords"))
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
                values.append(parsed if parsed is not None else {"summary": text.strip()})
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


def _tool_result_records(tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in _extract_tool_values(tool_result):
        records.extend(_flatten_records(value))
    return records


def _first_text(record: dict[str, Any], *keys: str) -> str:
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
    return _first_text(record, "govtribe_url", "url", "link", "uiLink", "permalink", "source_url", "download_url") or default_url


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
    )


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
) -> tuple[list[dict[str, Any]], str]:
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
    return _tool_result_records(result), _tool_name(tool)


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


def _record_naics_codes(record: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("code", "naics", "naics_code", "id", "value", "name"):
                if key in value:
                    collect(value.get(key))
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        text = str(value or "").strip()
        if not text:
            return
        matches = re.findall(r"\b\d{6}\b", text)
        values.extend(matches or [text])

    for key in ("naics", "naics_code", "naics_codes", "naicsCategory", "naics_category"):
        if key in record:
            collect(record.get(key))
    return dedupe_strings(values)


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
            for query, search_mode in queries:
                found, tool_name = _call_search(
                    client,
                    tool=tool,
                    query=query,
                    naics_codes=queried_naics,
                    limit=limit,
                    search_mode=search_mode,
                    due_date_from=due_date_from,
                    due_date_to=due_date_to,
                    opportunity_states=["Posted", "Updated"],
                    sort={"key": "dueDate", "direction": "asc"},
                )
                tool_names.append(tool_name)
                for item in found:
                    record = _normalize_scan_opportunity(
                        record=item,
                        source_config=self.source_config,
                        query=query,
                        queried_naics=queried_naics,
                        search_mode=search_mode,
                        tool_name=tool_name,
                        default_url=default_url,
                    )
                    key = str(record.get("canonical_record_id") or record.get("url") or record.get("title") or "").strip()
                    if key:
                        normalized[key] = record
                if normalized:
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
        return {
            "status": "ok" if records else "no_match",
            "records": records,
            "notes": dedupe_strings(
                [
                    *([f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}"] if tool_names else []),
                    f"GovTribe scan due-date filter: {due_date_from} to {due_date_to}.",
                ]
            ),
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
            solicitation_number = str(opportunity.get("solicitation_number") or "").strip()
            if solicitation_number:
                found, tool_name = _call_search(
                    client,
                    tool=tool,
                    query=solicitation_number,
                    solicitation_number=solicitation_number,
                    title=str(opportunity.get("title") or ""),
                    buyer=str(opportunity.get("buyer") or ""),
                )
                records.extend(found)
                tool_names.append(tool_name)
            if not records:
                found, tool_name = _call_search(
                    client,
                    tool=tool,
                    query=query,
                    solicitation_number=solicitation_number,
                    title=str(opportunity.get("title") or ""),
                    buyer=str(opportunity.get("buyer") or ""),
                )
                records.extend(found)
                tool_names.append(tool_name)
        except MCPResponseError as exc:
            status = "tool_contract_unavailable" if exc.code == -32602 else "error"
            return default_result(self.source_id, self.source_name, status, notes=[str(exc)])
        except MCPHTTPError as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])
        except Exception as exc:
            return default_result(self.source_id, self.source_name, "error", notes=[str(exc)])

        if not records:
            return default_result(
                self.source_id,
                self.source_name,
                "no_match",
                notes=["GovTribe MCP opportunity search returned no matching records."],
            )

        return _records_to_result(
            source_config=self.source_config,
            status="ok",
            matched_by="GovTribe opportunity search by solicitation number or title/buyer query",
            records_by_family=[("opportunities", item) for item in records],
            notes=[f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}"],
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
                    found, tool_name = _call_search(
                        client,
                        tool=tool,
                        query=family_query,
                        solicitation_number=solicitation_number,
                        title=str(opportunity.get("title") or ""),
                        buyer=str(opportunity.get("buyer") or ""),
                    )
                    records_by_family.extend((family, item) for item in found)
                    tool_names.append(tool_name)
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
            status = "tool_contract_unavailable" if errors else "no_match"
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
