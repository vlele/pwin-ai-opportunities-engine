from __future__ import annotations

import json
import os
import re
from typing import Any

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
            _schema_text(tool),
        ]
    ).lower()


def _tool_score(tool: dict[str, Any], family: str) -> int:
    text = _tool_text(tool)
    score = 0
    if family == "opportunities":
        if "opportunit" not in text:
            return 0
        score += 12
        for term in ("federal", "contract", "solicitation", "notice"):
            if term in text:
                score += 3
        for term in ("award", "vehicle", "file", "document"):
            if term in text:
                score -= 3
    elif family == "awards":
        if "award" not in text:
            return 0
        score += 10
        for term in ("federal", "contract", "recipient", "vendor"):
            if term in text:
                score += 2
        if "opportunit" in text:
            score -= 2
    elif family == "vehicles":
        if "vehicle" not in text:
            return 0
        score += 10
        for term in ("contract", "idiq", "gwac", "schedule"):
            if term in text:
                score += 2
    elif family == "government_files":
        if "file" not in text and "document" not in text:
            return 0
        score += 10
        for term in ("government", "attachment", "procurement", "solicitation"):
            if term in text:
                score += 2
    return score


def _select_tool(tools: list[dict[str, Any]], family: str) -> dict[str, Any] | None:
    scored = sorted(((_tool_score(tool, family), tool) for tool in tools), key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    return scored[0][1]


def discover_tool_families(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for family in ("opportunities", "awards", "vehicles", "government_files"):
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


def _tool_arguments(
    tool: dict[str, Any],
    *,
    query: str,
    solicitation_number: str = "",
    title: str = "",
    buyer: str = "",
    limit: int = 3,
) -> dict[str, Any]:
    properties = _schema_properties(tool)
    if not properties:
        return {"query": query, "limit": limit}

    args: dict[str, Any] = {}
    string_fallbacks: list[str] = []
    for name, spec in properties.items():
        key = _normalize_key(name)
        if _is_integer_prop(spec) and key in {"limit", "size", "page size", "per page", "max results"}:
            args[name] = limit
            continue
        if not _is_string_prop(spec):
            continue
        string_fallbacks.append(name)
        if key in {"query", "q", "search", "search query", "keyword", "keywords", "term", "terms"}:
            args[name] = query
        elif "solicitation" in key and solicitation_number:
            args[name] = solicitation_number
        elif "notice" in key and solicitation_number:
            args[name] = solicitation_number
        elif "title" in key and title:
            args[name] = title
        elif ("agency" in key or "buyer" in key or "customer" in key) and buyer:
            args[name] = buyer

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
        "candidate_naics": coerce_string_list((naics or {}).get("candidate"), max_items=8),
        "excluded_opportunity_classes": coerce_string_list(hard_filters.get("exclude_opportunity_classes"), max_items=8),
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
        "id",
        "title",
        "name",
        "summary",
        "description",
        "solicitation_number",
        "solicitationNumber",
        "notice_id",
        "url",
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
    return _first_text(record, "url", "link", "uiLink", "permalink", "source_url") or default_url


def _record_identifier(record: dict[str, Any]) -> str:
    return _first_text(
        record,
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
        "piid",
    )


def _record_title(record: dict[str, Any]) -> str:
    return _first_text(record, "title", "name", "solicitationTitle", "description", "summary") or "GovTribe record"


def _record_value(record: dict[str, Any]) -> str:
    return _first_text(
        record,
        "contract_value",
        "contractValue",
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
    solicitation_number: str = "",
    title: str = "",
    buyer: str = "",
) -> tuple[list[dict[str, Any]], str]:
    args = _tool_arguments(
        tool,
        query=query,
        solicitation_number=solicitation_number,
        title=title,
        buyer=buyer,
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
    summary = _first_text(first_record, "summary", "description", "abstract", "title", "name")
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
        vehicle_name = vehicle_name or _first_text(record, "vehicle", "vehicle_name", "contract_vehicle", "contractVehicle")
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
            selected = {family: tool for family, tool in families.items() if family in {"opportunities", "awards", "vehicles", "government_files"}}
            if not selected:
                return default_result(
                    self.source_id,
                    self.source_name,
                    "tool_contract_unavailable",
                    notes=["GovTribe MCP did not expose compatible opportunity, award, vehicle, or government-file search tools."],
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
            matched_by="GovTribe MCP capture enrichment across available opportunity, award, vehicle, and government-file tools",
            records_by_family=records_by_family,
            notes=[f"GovTribe MCP tools used: {', '.join(dedupe_strings(tool_names))}", *errors],
            default_url=default_url,
        )
