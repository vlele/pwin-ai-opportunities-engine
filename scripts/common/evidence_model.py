from __future__ import annotations

import re
from typing import Any


SOURCE_PRIORITY = {
    "attachment_package": 110,
    "sam_contract_opportunities": 100,
    "usaspending_award_history": 80,
    "govtribe_mcp_commercial_intel": 60,
    "govwin_iq_commercial_intel": 60,
}


def _priority(source_id: str) -> int:
    return int(SOURCE_PRIORITY.get(str(source_id or "").strip(), 10))


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


def _coerce_string_list(value: Any, *, max_items: int = 8) -> list[str]:
    items: list[str] = []
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
    elif isinstance(value, str) and value.strip():
        items.append(value.strip())
    return _dedupe_strings(items)[:max_items]


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _normalize_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if text in {"high", "medium", "low", "unknown"}:
        return text
    try:
        numeric = float(text)
    except Exception:
        return "unknown"
    if numeric >= 0.85:
        return "high"
    if numeric >= 0.60:
        return "medium"
    if numeric > 0:
        return "low"
    return "unknown"


def _confidence_rank(value: Any) -> int:
    return {"unknown": 0, "low": 1, "medium": 2, "high": 3}.get(_normalize_confidence(value), 0)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _combine_source_label(source_name: str, source_id: str) -> str:
    return source_name or source_id or "Unknown source"


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        amount = str(value.get("amount") or value.get("value") or value.get("ceiling") or "").strip()
        identifier = str(value.get("number") or value.get("identifier") or value.get("id") or "").strip()
        if amount and identifier:
            return f"{amount} ({identifier})"
        if amount:
            return amount
        for candidate in value.values():
            text = str(candidate or "").strip()
            if text and text != "{}":
                return text
        return ""
    return str(value or "").strip()


def empty_evidence_model(*, source_id: str = "", source_name: str = "") -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": source_name,
        "summary": "",
        "incumbent": {
            "name": "",
            "status": "unknown",
            "confidence": "unknown",
            "source_id": source_id,
            "source_name": source_name,
            "source_url": "",
            "external_record_id": "",
            "evidence": [],
            "notes": [],
        },
        "vehicle": {
            "name": "",
            "contract_type": "",
            "set_aside": "",
            "confidence": "unknown",
            "source_id": source_id,
            "source_name": source_name,
            "source_url": "",
            "external_record_id": "",
            "evidence": [],
        },
        "recompete_clues": [],
        "related_procurements": [],
        "contract_value_or_ceiling": {
            "amount": "",
            "label": "",
            "confidence": "unknown",
            "source_id": source_id,
            "source_name": source_name,
            "source_url": "",
            "external_record_id": "",
            "evidence": [],
        },
        "teaming_posture": {
            "recommended_posture": "",
            "confidence": "unknown",
            "source_id": source_id,
            "source_name": source_name,
            "rationale": [],
            "partner_signals": [],
            "risks": [],
        },
        "next_questions": [],
        "evidence_gaps": [],
        "conflicts": [],
    }


def _signal_entry(raw: Any, *, source_id: str, source_name: str, fallback_label: str = "Signal") -> dict[str, Any] | None:
    if isinstance(raw, dict):
        signal = str(raw.get("signal") or raw.get("name") or raw.get("title") or "").strip()
        why = str(raw.get("why_it_matters") or raw.get("notes") or "").strip()
        if not signal and not why:
            return None
        return {
            "signal": signal or fallback_label,
            "why_it_matters": why,
            "confidence": _normalize_confidence(raw.get("confidence")),
            "source_id": str(raw.get("source_id") or source_id).strip() or source_id,
            "source_name": str(raw.get("source_name") or raw.get("source") or source_name).strip() or source_name,
        }
    text = str(raw or "").strip()
    if not text:
        return None
    return {
        "signal": text,
        "why_it_matters": "",
        "confidence": "unknown",
        "source_id": source_id,
        "source_name": source_name,
    }


def _related_procurement_entry(raw: Any, *, source_id: str, source_name: str, default_url: str = "") -> dict[str, Any] | None:
    if isinstance(raw, dict):
        title = str(raw.get("title") or raw.get("name") or raw.get("summary") or "").strip()
        identifier = str(raw.get("identifier") or raw.get("id") or raw.get("notice_id") or raw.get("award_id") or "").strip()
        relationship = str(raw.get("relationship") or raw.get("type") or "Related procurement signal").strip()
        contract_value = str(raw.get("contract_value") or raw.get("value") or raw.get("ceiling") or "").strip()
        url = str(raw.get("url") or default_url).strip()
        notes = _coerce_string_list(raw.get("notes"), max_items=4)
        if not title and not identifier and not notes:
            return None
        return {
            "title": title or identifier or "Related procurement",
            "identifier": identifier,
            "relationship": relationship,
            "contract_value": contract_value,
            "confidence": _normalize_confidence(raw.get("confidence")),
            "source_id": str(raw.get("source_id") or source_id).strip() or source_id,
            "source_name": str(raw.get("source_name") or raw.get("source") or source_name).strip() or source_name,
            "url": url,
            "notes": notes,
        }
    text = str(raw or "").strip()
    if not text:
        return None
    return {
        "title": text,
        "identifier": "",
        "relationship": "Related procurement signal",
        "contract_value": "",
        "confidence": "unknown",
        "source_id": source_id,
        "source_name": source_name,
        "url": default_url,
        "notes": [],
    }


def normalize_provider_evidence_model(
    raw: Any,
    *,
    source_id: str,
    source_name: str,
    source_url: str = "",
    external_record_id: str = "",
) -> dict[str, Any]:
    model = empty_evidence_model(source_id=source_id, source_name=source_name)
    data = _as_dict(raw)
    model["summary"] = str(data.get("summary") or "").strip()

    incumbent = _as_dict(data.get("incumbent"))
    incumbent_name = str(incumbent.get("name") or incumbent.get("incumbent_name") or "").strip()
    model["incumbent"].update(
        {
            "name": incumbent_name,
            "status": str(incumbent.get("status") or ("likely" if incumbent_name else "unknown")).strip() or "unknown",
            "confidence": _normalize_confidence(incumbent.get("confidence")),
            "source_url": str(incumbent.get("source_url") or source_url).strip(),
            "external_record_id": str(incumbent.get("external_record_id") or external_record_id).strip(),
            "evidence": _coerce_string_list(incumbent.get("evidence") or incumbent.get("notes"), max_items=6),
            "notes": _coerce_string_list(incumbent.get("notes"), max_items=6),
        }
    )

    vehicle = _as_dict(data.get("vehicle"))
    model["vehicle"].update(
        {
            "name": str(vehicle.get("name") or vehicle.get("vehicle_name") or "").strip(),
            "contract_type": str(vehicle.get("contract_type") or "").strip(),
            "set_aside": str(vehicle.get("set_aside") or "").strip(),
            "confidence": _normalize_confidence(vehicle.get("confidence")),
            "source_url": str(vehicle.get("source_url") or source_url).strip(),
            "external_record_id": str(vehicle.get("external_record_id") or external_record_id).strip(),
            "evidence": _coerce_string_list(vehicle.get("evidence") or vehicle.get("notes"), max_items=6),
        }
    )

    contract_value = _as_dict(data.get("contract_value_or_ceiling"))
    model["contract_value_or_ceiling"].update(
        {
            "amount": str(contract_value.get("amount") or contract_value.get("value") or contract_value.get("ceiling") or "").strip(),
            "label": str(contract_value.get("label") or contract_value.get("basis") or "Contract value / ceiling").strip(),
            "confidence": _normalize_confidence(contract_value.get("confidence")),
            "source_url": str(contract_value.get("source_url") or source_url).strip(),
            "external_record_id": str(contract_value.get("external_record_id") or external_record_id).strip(),
            "evidence": _coerce_string_list(contract_value.get("evidence") or contract_value.get("notes"), max_items=6),
        }
    )

    teaming = _as_dict(data.get("teaming_posture"))
    model["teaming_posture"].update(
        {
            "recommended_posture": str(teaming.get("recommended_posture") or teaming.get("recommendation") or teaming.get("posture") or "").strip(),
            "confidence": _normalize_confidence(teaming.get("confidence")),
            "rationale": _coerce_string_list(teaming.get("rationale"), max_items=6),
            "partner_signals": _coerce_string_list(teaming.get("partner_signals"), max_items=6),
            "risks": _coerce_string_list(teaming.get("risks"), max_items=6),
        }
    )

    model["recompete_clues"] = [
        item
        for item in (
            _signal_entry(raw_item, source_id=source_id, source_name=source_name, fallback_label="Recompete clue")
            for raw_item in (data.get("recompete_clues") or [])
        )
        if item
    ]
    model["related_procurements"] = [
        item
        for item in (
            _related_procurement_entry(raw_item, source_id=source_id, source_name=source_name, default_url=source_url)
            for raw_item in (data.get("related_procurements") or [])
        )
        if item
    ]
    model["next_questions"] = _coerce_string_list(data.get("next_questions"), max_items=8)
    model["evidence_gaps"] = _coerce_string_list(data.get("evidence_gaps"), max_items=8)

    if not model["summary"]:
        fallback_summary = _coerce_string_list(data.get("competitive_landscape"), max_items=1)
        if fallback_summary:
            model["summary"] = fallback_summary[0]
    if not model["vehicle"]["evidence"]:
        model["vehicle"]["evidence"] = _coerce_string_list(data.get("vehicle_signals"), max_items=6)
    if not model["related_procurements"]:
        model["related_procurements"] = [
            item
            for item in (
                _related_procurement_entry(raw_item, source_id=source_id, source_name=source_name, default_url=source_url)
                for raw_item in _coerce_string_list(data.get("related_procurements"), max_items=6)
            )
            if item
        ]
    if not model["teaming_posture"]["rationale"]:
        model["teaming_posture"]["rationale"] = _coerce_string_list(data.get("competitive_landscape"), max_items=4)
    if not model["next_questions"]:
        model["next_questions"] = _coerce_string_list(data.get("questions"), max_items=8)
    return model


def _contract_type_from_text(text: str) -> str:
    lower = str(text or "").lower()
    if "firm fixed price" in lower or "ffp" in lower:
        return "Firm-fixed-price"
    if "time and materials" in lower or "t&m" in lower:
        return "Time-and-materials"
    if "labor hour" in lower:
        return "Labor-hour"
    if "cost plus" in lower or "cost-plus" in lower:
        return "Cost-reimbursement"
    return ""


def _vehicle_name_from_text(text: str) -> str:
    lower = str(text or "").lower()
    if "gsa mas" in lower or "multiple award schedule" in lower or "federal supply schedule" in lower:
        return "GSA Multiple Award Schedule"
    if "oasis" in lower:
        return "OASIS"
    if "sewp" in lower:
        return "SEWP"
    if "8(a) stars" in lower:
        return "8(a) STARS"
    if "idiq" in lower or "indefinite delivery indefinite quantity" in lower or "indefinite-delivery-indefinite-quantity" in lower:
        return "IDIQ"
    if "bpa" in lower or "blanket purchase agreement" in lower:
        return "BPA"
    if "task order" in lower:
        return "Task order vehicle"
    return ""


def _recompete_clues_from_text(text: str, *, source_id: str, source_name: str) -> list[dict[str, Any]]:
    lower = str(text or "").lower()
    clues: list[dict[str, Any]] = []
    markers = [
        ("bridge", "Bridge language suggests continuity pressure or a delayed recompete."),
        ("follow-on", "Follow-on language suggests a predecessor contract and likely incumbent position."),
        ("recompete", "Recompete language suggests an existing performer and prior contract history."),
        ("incumbent", "Direct incumbent language suggests continuity risk is part of the buying posture."),
        ("continuity", "Continuity language suggests low tolerance for transition disruption."),
        ("option", "Option or extension language can signal predecessor contract timing."),
    ]
    for marker, why in markers:
        if marker in lower:
            clues.append(
                {
                    "signal": marker,
                    "why_it_matters": why,
                    "confidence": "medium",
                    "source_id": source_id,
                    "source_name": source_name,
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in clues:
        key = _normalize_key(item.get("signal"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_scan_official_evidence_model(record: dict[str, Any]) -> dict[str, Any]:
    text = " ".join([str(record.get("title") or ""), str(record.get("summary") or "")])
    model = empty_evidence_model(
        source_id="sam_contract_opportunities",
        source_name="SAM.gov Contract Opportunities",
    )
    set_aside = str(record.get("set_aside") or "").strip()
    vehicle_name = _vehicle_name_from_text(text)
    contract_type = _contract_type_from_text(text)
    model["summary"] = str(record.get("summary") or "").strip()
    model["vehicle"].update(
        {
            "name": vehicle_name,
            "contract_type": contract_type,
            "set_aside": set_aside,
            "confidence": "high" if set_aside or vehicle_name or contract_type else "unknown",
            "evidence": _dedupe_strings(
                [
                    *([f"SAM record set-aside: {set_aside}."] if set_aside else []),
                    *([f"SAM notice text suggests vehicle path: {vehicle_name}."] if vehicle_name else []),
                    *([f"SAM notice text suggests contract type: {contract_type}."] if contract_type else []),
                ]
            ),
        }
    )
    estimated_value = _value_text(record.get("estimated_value"))
    if estimated_value:
        model["contract_value_or_ceiling"].update(
            {
                "amount": estimated_value,
                "label": "Estimated value",
                "confidence": "medium",
                "evidence": [f"SAM record estimated value: {estimated_value}."],
            }
        )
    model["recompete_clues"] = _recompete_clues_from_text(
        text,
        source_id="sam_contract_opportunities",
        source_name="SAM.gov Contract Opportunities",
    )
    model["next_questions"] = _dedupe_strings(
        [
            *(
                ["Validate the final vehicle path and whether this is open market or tied to an existing ordering vehicle."]
                if not vehicle_name
                else []
            ),
            *(
                ["Confirm the set-aside posture and whether it limits prime eligibility."]
                if not set_aside or set_aside.lower() in {"n/a", "none", "not stated"}
                else []
            ),
        ]
    )
    return model


def build_capture_official_evidence_model(
    *,
    resolved: dict[str, Any],
    opportunity: dict[str, Any],
    award_signals: dict[str, Any],
    attachment_validation: dict[str, Any],
    attachment_bundle: dict[str, Any],
    vehicle_signals: list[str],
    notice_context_text: str = "",
) -> dict[str, Any]:
    text = " ".join(
        [
            str(resolved.get("title") or ""),
            str(opportunity.get("summary") or ""),
            str(notice_context_text or ""),
            " ".join(vehicle_signals),
        ]
    )
    model = empty_evidence_model(
        source_id="sam_contract_opportunities",
        source_name="Official solicitation package",
    )
    model["summary"] = str(opportunity.get("summary") or "").strip()

    validated_incumbents = _coerce_string_list(attachment_validation.get("validated_incumbents"), max_items=4)
    likely_incumbents = _coerce_string_list(
        ((award_signals.get("competitive_landscape") or {}).get("likely_incumbents") or []),
        max_items=4,
    )
    incumbent_name = (validated_incumbents or likely_incumbents or [""])[0]
    incumbent_evidence = _dedupe_strings(
        _coerce_string_list(attachment_validation.get("direct_mentions"), max_items=3)
        + _coerce_string_list(attachment_validation.get("supporting_snippets"), max_items=3)
        + (
            [
                f"USAspending likely incumbent signal: {', '.join(likely_incumbents[:3])}."
            ]
            if likely_incumbents
            else []
        )
    )
    model["incumbent"].update(
        {
            "name": incumbent_name,
            "status": "confirmed" if validated_incumbents else ("likely" if likely_incumbents else "unknown"),
            "confidence": "high" if validated_incumbents else ("medium" if likely_incumbents else "unknown"),
            "evidence": incumbent_evidence,
            "notes": _coerce_string_list((award_signals.get("competitive_landscape") or {}).get("notes"), max_items=4),
        }
    )

    set_aside = str(opportunity.get("set_aside") or "").strip()
    vehicle_name = _vehicle_name_from_text(text)
    contract_type = _contract_type_from_text(text)
    model["vehicle"].update(
        {
            "name": vehicle_name,
            "contract_type": contract_type,
            "set_aside": set_aside,
            "confidence": "high" if vehicle_signals or set_aside or contract_type else "unknown",
            "evidence": _dedupe_strings(vehicle_signals),
        }
    )

    contract_value = _value_text(opportunity.get("estimated_value"))
    if contract_value:
        model["contract_value_or_ceiling"].update(
            {
                "amount": contract_value,
                "label": "Estimated value",
                "confidence": "medium",
                "evidence": [f"Opportunity record estimated value: {contract_value}."],
            }
        )

    model["recompete_clues"] = _recompete_clues_from_text(
        text,
        source_id="sam_contract_opportunities",
        source_name="Official solicitation package",
    )
    if likely_incumbents:
        model["recompete_clues"].append(
            {
                "signal": "same-agency award history",
                "why_it_matters": "USAspending surfaced same-agency related awards that may indicate predecessor contract history.",
                "confidence": "medium",
                "source_id": "usaspending_award_history",
                "source_name": "USAspending.gov Award History",
            }
        )

    related_procurements: list[dict[str, Any]] = []
    for row in (award_signals.get("relevant_awards") or [])[:4]:
        if not isinstance(row, dict):
            continue
        related_procurements.append(
            {
                "title": str(row.get("Description") or row.get("Award ID") or "Related award").strip(),
                "identifier": str(row.get("Award ID") or "").strip(),
                "relationship": "Same-agency related award history",
                "contract_value": str(row.get("Award Amount") or "").strip(),
                "confidence": "medium",
                "source_id": "usaspending_award_history",
                "source_name": "USAspending.gov Award History",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "notes": _coerce_string_list(row.get("_query_terms"), max_items=3),
            }
        )
    model["related_procurements"] = related_procurements

    attachment_expected = bool(attachment_bundle.get("attachments_expected"))
    attachments_present = bool(attachment_bundle.get("attachments"))
    model["next_questions"] = _dedupe_strings(
        [
            *(
                ["Validate the predecessor contract number, POP, and incumbent from the solicitation attachments or archived award notice."]
                if not incumbent_name
                else []
            ),
            *(
                ["Recover the official attachment package before treating vehicle or evaluation posture as settled."]
                if attachment_expected and not attachments_present
                else []
            ),
            *(
                ["Confirm the contract type and pricing basis directly from the solicitation package."]
                if not contract_type
                else []
            ),
        ]
    )
    model["evidence_gaps"] = _dedupe_strings(
        [
            *(
                ["Official attachments were expected but not available in this run."]
                if attachment_expected and not attachments_present
                else []
            ),
            *(
                ["No explicit incumbent was confirmed from the official solicitation package."]
                if not validated_incumbents
                else []
            ),
        ]
    )
    return model


def _merge_signal_lists(models: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in models:
        for item in model.get(field_name, []) or []:
            if not isinstance(item, dict):
                continue
            key = _normalize_key(item.get("signal") or item.get("title") or item.get("identifier"))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _merge_related_procurements(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for model in models:
        for item in model.get("related_procurements", []) or []:
            if not isinstance(item, dict):
                continue
            key = _normalize_key(item.get("identifier") or item.get("title"))
            if not key:
                continue
            current = merged.get(key)
            if current is None:
                merged[key] = dict(item)
                merged[key]["notes"] = _coerce_string_list(item.get("notes"), max_items=6)
                continue
            for field in ("title", "identifier", "relationship", "contract_value", "url"):
                if not current.get(field) and item.get(field):
                    current[field] = item.get(field)
            if _confidence_rank(item.get("confidence")) > _confidence_rank(current.get("confidence")):
                current["confidence"] = item.get("confidence")
            current["notes"] = _dedupe_strings(_coerce_string_list(current.get("notes"), max_items=6) + _coerce_string_list(item.get("notes"), max_items=6))
            sources = _dedupe_strings(
                _coerce_string_list(current.get("source_name"), max_items=2)
                + _coerce_string_list(item.get("source_name"), max_items=2)
            )
            if len(sources) > 1:
                current["source_name"] = ", ".join(sources[:3])
    return list(merged.values())


def _field_candidates(models: list[dict[str, Any]], section: str, field: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for model in models:
        section_value = _as_dict(model.get(section))
        value = str(section_value.get(field) or "").strip()
        if not value:
            continue
        candidates.append(
            {
                "value": value,
                "confidence": section_value.get("confidence"),
                "source_id": str(section_value.get("source_id") or model.get("source_id") or "").strip(),
                "source_name": str(section_value.get("source_name") or model.get("source_name") or "").strip(),
                "evidence_count": len(_coerce_string_list(section_value.get("evidence"), max_items=8)),
            }
        )
    return candidates


def _resolve_text_field(models: list[dict[str, Any]], section: str, field: str, conflicts: list[dict[str, Any]]) -> str:
    candidates = _field_candidates(models, section, field)
    if not candidates:
        return ""
    chosen = max(
        candidates,
        key=lambda item: (
            _priority(item.get("source_id", "")),
            _confidence_rank(item.get("confidence")),
            int(item.get("evidence_count", 0) or 0),
        ),
    )
    distinct = { _normalize_key(item.get("value")): item for item in candidates if item.get("value") }
    if len(distinct) > 1:
        conflicts.append(
            {
                "field": f"{section}.{field}",
                "values": [str(item.get("value") or "").strip() for item in distinct.values()],
                "sources": [_combine_source_label(str(item.get("source_name") or ""), str(item.get("source_id") or "")) for item in distinct.values()],
                "resolution": f'Using "{chosen.get("value")}" from {_combine_source_label(str(chosen.get("source_name") or ""), str(chosen.get("source_id") or ""))}.',
            }
        )
    return str(chosen.get("value") or "").strip()


def merge_evidence_models(models: list[dict[str, Any]]) -> dict[str, Any]:
    usable_models = [model for model in models if isinstance(model, dict) and (model.get("source_id") or model.get("source_name"))]
    if not usable_models:
        return empty_evidence_model()

    merged = empty_evidence_model(
        source_id="merged_cross_source_evidence",
        source_name="Merged cross-source evidence",
    )
    conflicts: list[dict[str, Any]] = []
    merged["summary"] = next((str(model.get("summary") or "").strip() for model in usable_models if str(model.get("summary") or "").strip()), "")
    merged["incumbent"]["name"] = _resolve_text_field(usable_models, "incumbent", "name", conflicts)
    merged["incumbent"]["status"] = _resolve_text_field(usable_models, "incumbent", "status", conflicts) or ("likely" if merged["incumbent"]["name"] else "unknown")
    merged["incumbent"]["confidence"] = max(
        [_normalize_confidence((_as_dict(model.get("incumbent"))).get("confidence")) for model in usable_models],
        key=_confidence_rank,
        default="unknown",
    )
    merged["incumbent"]["evidence"] = _dedupe_strings(
        [
            evidence
            for model in usable_models
            for evidence in _coerce_string_list((_as_dict(model.get("incumbent"))).get("evidence"), max_items=6)
        ]
    )
    merged["incumbent"]["notes"] = _dedupe_strings(
        [
            note
            for model in usable_models
            for note in _coerce_string_list((_as_dict(model.get("incumbent"))).get("notes"), max_items=6)
        ]
    )

    merged["vehicle"]["name"] = _resolve_text_field(usable_models, "vehicle", "name", conflicts)
    merged["vehicle"]["contract_type"] = _resolve_text_field(usable_models, "vehicle", "contract_type", conflicts)
    merged["vehicle"]["set_aside"] = _resolve_text_field(usable_models, "vehicle", "set_aside", conflicts)
    merged["vehicle"]["confidence"] = max(
        [_normalize_confidence((_as_dict(model.get("vehicle"))).get("confidence")) for model in usable_models],
        key=_confidence_rank,
        default="unknown",
    )
    merged["vehicle"]["evidence"] = _dedupe_strings(
        [
            evidence
            for model in usable_models
            for evidence in _coerce_string_list((_as_dict(model.get("vehicle"))).get("evidence"), max_items=6)
        ]
    )

    merged["contract_value_or_ceiling"]["amount"] = _resolve_text_field(usable_models, "contract_value_or_ceiling", "amount", conflicts)
    merged["contract_value_or_ceiling"]["label"] = _resolve_text_field(usable_models, "contract_value_or_ceiling", "label", conflicts) or "Contract value / ceiling"
    merged["contract_value_or_ceiling"]["confidence"] = max(
        [_normalize_confidence((_as_dict(model.get("contract_value_or_ceiling"))).get("confidence")) for model in usable_models],
        key=_confidence_rank,
        default="unknown",
    )
    merged["contract_value_or_ceiling"]["evidence"] = _dedupe_strings(
        [
            evidence
            for model in usable_models
            for evidence in _coerce_string_list((_as_dict(model.get("contract_value_or_ceiling"))).get("evidence"), max_items=6)
        ]
    )

    merged["teaming_posture"]["recommended_posture"] = _resolve_text_field(usable_models, "teaming_posture", "recommended_posture", conflicts)
    merged["teaming_posture"]["confidence"] = max(
        [_normalize_confidence((_as_dict(model.get("teaming_posture"))).get("confidence")) for model in usable_models],
        key=_confidence_rank,
        default="unknown",
    )
    merged["teaming_posture"]["rationale"] = _dedupe_strings(
        [
            item
            for model in usable_models
            for item in _coerce_string_list((_as_dict(model.get("teaming_posture"))).get("rationale"), max_items=6)
        ]
    )
    merged["teaming_posture"]["partner_signals"] = _dedupe_strings(
        [
            item
            for model in usable_models
            for item in _coerce_string_list((_as_dict(model.get("teaming_posture"))).get("partner_signals"), max_items=6)
        ]
    )
    merged["teaming_posture"]["risks"] = _dedupe_strings(
        [
            item
            for model in usable_models
            for item in _coerce_string_list((_as_dict(model.get("teaming_posture"))).get("risks"), max_items=6)
        ]
    )

    merged["recompete_clues"] = _merge_signal_lists(usable_models, "recompete_clues")
    merged["related_procurements"] = _merge_related_procurements(usable_models)
    merged["next_questions"] = _dedupe_strings(
        [
            question
            for model in usable_models
            for question in _coerce_string_list(model.get("next_questions"), max_items=8)
        ]
    )
    merged["evidence_gaps"] = _dedupe_strings(
        [
            gap
            for model in usable_models
            for gap in _coerce_string_list(model.get("evidence_gaps"), max_items=8)
        ]
    )
    merged["conflicts"] = conflicts
    merged["source_names"] = _dedupe_strings([str(model.get("source_name") or model.get("source_id") or "").strip() for model in usable_models])
    merged["source_ids"] = _dedupe_strings([str(model.get("source_id") or "").strip() for model in usable_models])
    return merged


def evidence_model_scan_notes(model: dict[str, Any], *, max_items: int = 3) -> list[str]:
    notes: list[str] = []
    incumbent = _as_dict(model.get("incumbent"))
    vehicle = _as_dict(model.get("vehicle"))
    contract_value = _as_dict(model.get("contract_value_or_ceiling"))
    conflicts = model.get("conflicts", []) or []
    if str(incumbent.get("name") or "").strip():
        notes.append(f'Cross-source incumbent signal: {incumbent.get("name")} ({incumbent.get("status", "unknown")}).')
    vehicle_bits = _dedupe_strings(
        [
            *([f'set-aside {vehicle.get("set_aside")}'] if str(vehicle.get("set_aside") or "").strip() else []),
            *([f'vehicle {vehicle.get("name")}'] if str(vehicle.get("name") or "").strip() else []),
            *([f'contract type {vehicle.get("contract_type")}'] if str(vehicle.get("contract_type") or "").strip() else []),
        ]
    )
    if vehicle_bits:
        notes.append(f"Acquisition signal: {', '.join(vehicle_bits)}.")
    if str(contract_value.get("amount") or "").strip():
        notes.append(f'{contract_value.get("label", "Contract value / ceiling")}: {contract_value.get("amount")}.')
    if conflicts:
        first_conflict = conflicts[0]
        notes.append(f'Source conflict to validate: {first_conflict.get("field")} -> {", ".join(first_conflict.get("values", [])[:2])}.')
    return notes[:max_items]


def evidence_model_competitive_notes(model: dict[str, Any], *, max_items: int = 6) -> list[str]:
    notes: list[str] = []
    incumbent = _as_dict(model.get("incumbent"))
    if str(incumbent.get("name") or "").strip():
        notes.append(f'Normalized incumbent signal: {incumbent.get("name")} ({incumbent.get("status", "unknown")}).')
    notes.extend(_coerce_string_list(incumbent.get("evidence"), max_items=3))
    for signal in model.get("recompete_clues", []) or []:
        if not isinstance(signal, dict):
            continue
        text = str(signal.get("signal") or "").strip()
        why = str(signal.get("why_it_matters") or "").strip()
        if text and why:
            notes.append(f"{text}: {why}")
        elif text:
            notes.append(text)
    notes.extend(_coerce_string_list((_as_dict(model.get("teaming_posture"))).get("rationale"), max_items=3))
    return _dedupe_strings(notes)[:max_items]


def evidence_model_vehicle_signals(model: dict[str, Any], *, max_items: int = 6) -> list[str]:
    vehicle = _as_dict(model.get("vehicle"))
    signals: list[str] = []
    if str(vehicle.get("set_aside") or "").strip():
        signals.append(f'Set-aside posture: {vehicle.get("set_aside")}.')
    if str(vehicle.get("name") or "").strip():
        signals.append(f'Likely vehicle signal: {vehicle.get("name")}.')
    if str(vehicle.get("contract_type") or "").strip():
        signals.append(f'Likely contract type: {vehicle.get("contract_type")}.')
    signals.extend(_coerce_string_list(vehicle.get("evidence"), max_items=4))
    return _dedupe_strings(signals)[:max_items]


def evidence_model_related_procurement_lines(model: dict[str, Any], *, max_items: int = 6) -> list[str]:
    lines: list[str] = []
    for item in (model.get("related_procurements", []) or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        label_parts = [
            str(item.get("identifier") or "").strip(),
            str(item.get("contract_value") or "").strip(),
            str(item.get("relationship") or "").strip(),
        ]
        detail = " | ".join(part for part in label_parts if part)
        title = str(item.get("title") or "Related procurement").strip()
        line = f"{title}{': ' + detail if detail else ''}"
        lines.append(line)
    return _dedupe_strings(lines)[:max_items]


def evidence_model_next_questions(model: dict[str, Any], *, max_items: int = 8) -> list[str]:
    return _coerce_string_list(model.get("next_questions"), max_items=max_items)
