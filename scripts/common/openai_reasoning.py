from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from typing import Any

from common.openai_reasoning_types import (
    AlignmentLevel,
    CompetitivePosture,
    ConfidenceLevel,
    CrediblePosture,
    FeedbackInterpretation,
    FitAssessment,
    ReasoningEvidenceSpan,
    RecommendedAction,
    ScanFitAssessmentPayload,
    SemanticAggregateRow,
    SemanticAppliedPreferences,
    SemanticFeedbackPayload,
    SemanticLearningSummary,
    SemanticResolvedEntities,
)

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment]


DEFAULT_REASONING_MODEL = os.getenv("PWIN_REASONING_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"
DEFAULT_REASONING_TIMEOUT_SECONDS = int(os.getenv("PWIN_REASONING_TIMEOUT_SECONDS", "30") or "30")
SCHEMA_VERSION = "1.0"
MAX_NOTICE_TEXT = 12000
MAX_VENDOR_JSON = 5000

MISSION_DOMAIN_MARKERS: dict[str, tuple[str, ...]] = {
    "digital_modernization": ("modernization", "digital transformation", "legacy", "platform modernization"),
    "data_management": ("data", "analytics", "database", "governance", "warehouse", "etl"),
    "cybersecurity": ("cyber", "security", "rmf", "zero trust", "soc", "cmmc", "insider threat"),
    "cloud_migration": ("cloud", "aws", "azure", "hosting", "migration"),
    "identity_access": ("identity", "authentication", "authorization", "iam", "icam", "access management"),
    "software_development": ("software development", "application development", "devsecops", "agile"),
    "program_management": ("program management", "pmo", "governance", "planning"),
    "biometrics": ("biometric", "fingerprint", "facial recognition", "abiss"),
    "training": ("training", "curriculum", "instructional"),
    "engineering": ("engineering", "architecture", "design"),
    "help_desk": ("help desk", "service desk", "desktop support", "end user support"),
    "tax_software_sustainment": ("tax", "irs", "software maintenance", "annual support", "license support"),
}

DELIVERY_MODEL_MARKERS: dict[str, tuple[str, ...]] = {
    "implementation": ("implement", "deployment", "rollout", "build", "develop"),
    "operations_support": ("operations", "support services", "help desk", "service desk", "operational"),
    "continuity_support": ("maintenance", "renewal", "annual support", "sustainment", "continuity"),
    "advisory": ("assessment", "advisory", "strategy", "study", "analysis"),
    "staff_augmentation": ("labor category", "fte", "staff augmentation", "surge support"),
    "program_management": ("program management", "pmo", "portfolio support"),
}

TECHNICAL_MOTION_MARKERS: dict[str, tuple[str, ...]] = {
    "migration": ("migration", "migrate"),
    "platform_modernization": ("platform modernization", "modernization"),
    "operations_maintenance": ("operations and maintenance", "maintenance", "o m"),
    "reporting": ("reporting", "dashboard", "metrics"),
    "integration": ("integration", "interface", "api"),
}

VEHICLE_MARKERS: dict[str, tuple[str, ...]] = {
    "seaport_nxg_required": ("seaport nxg",),
    "gsa_schedule": ("gsa schedule", "mas"),
    "alliant": ("alliant",),
    "cio_sp": ("cio-sp", "cio sp"),
    "oasis": ("oasis",),
    "stars": ("8(a) stars", "stars iii", "stars ii"),
}

BUYER_MATURITY_MARKERS: dict[str, tuple[str, ...]] = {
    "named_program_office": ("program office", "program manager"),
    "named_contracting_office": ("contracting office", "contract specialist", "contracting officer"),
    "evaluation_language_present": ("evaluation", "best value", "lpta", "tradeoff"),
}

LOW_INFO_RISK_FLAGS = {
    "vehicle_access_unknown",
    "incumbent_continuity_risk",
}


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _dedupe_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _has_marker(text: str, marker: str) -> bool:
    normalized_marker = _normalized_text(marker)
    if not normalized_marker:
        return False
    return f" {normalized_marker} " in f" {text} "


def _collect_marker_hits(text: str, markers: dict[str, tuple[str, ...]]) -> list[str]:
    hits: list[str] = []
    for label, options in markers.items():
        if any(_has_marker(text, option) for option in options):
            hits.append(label)
    return hits


def _first_quote_for_markers(text: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        if _has_marker(text, marker):
            return marker
    return ""


def _confidence_multiplier(value: str) -> float:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return 1.0
    if normalized == "medium":
        return 0.7
    return 0.4


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return _dedupe_strings(value)


def _coerce_alignment(value: Any) -> AlignmentLevel:
    if isinstance(value, (int, float)):
        if float(value) >= 0.75:
            return "high"
        if float(value) >= 0.4:
            return "medium"
        return "low"
    normalized = str(value or "").strip().lower()
    if "high" in normalized:
        return "high"
    if "medium" in normalized or "moderate" in normalized:
        return "medium"
    if "low" in normalized:
        return "low"
    if normalized in {"high", "medium", "low", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _coerce_competitive_posture(value: Any) -> CompetitivePosture:
    normalized = str(value or "").strip().lower()
    if "favorable" in normalized:
        return "favorable"  # type: ignore[return-value]
    if "unfavorable" in normalized:
        return "unfavorable"  # type: ignore[return-value]
    if "neutral" in normalized:
        return "neutral"  # type: ignore[return-value]
    if normalized in {"favorable", "neutral", "unfavorable", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _coerce_confidence(value: Any) -> ConfidenceLevel:
    if isinstance(value, (int, float)):
        if float(value) >= 0.75:
            return "high"
        if float(value) >= 0.4:
            return "medium"
        return "low"
    normalized = str(value or "").strip().lower()
    if "high" in normalized:
        return "high"  # type: ignore[return-value]
    if "medium" in normalized or "moderate" in normalized:
        return "medium"  # type: ignore[return-value]
    if "low" in normalized:
        return "low"  # type: ignore[return-value]
    if normalized in {"high", "medium", "low"}:
        return normalized  # type: ignore[return-value]
    return "low"


def _coerce_fit_assessment(value: Any) -> FitAssessment:
    normalized = str(value or "").strip().lower()
    if "misleading" in normalized or "false positive" in normalized:
        return "misleading_keyword_match"  # type: ignore[return-value]
    if "strong" in normalized:
        return "strong_fit"  # type: ignore[return-value]
    if "adjacent" in normalized or "partial" in normalized:
        return "adjacent_fit"  # type: ignore[return-value]
    if "weak" in normalized:
        return "weak_fit"  # type: ignore[return-value]
    if normalized in {"strong_fit", "adjacent_fit", "weak_fit", "misleading_keyword_match"}:
        return normalized  # type: ignore[return-value]
    return "weak_fit"


def _coerce_posture(value: Any) -> CrediblePosture:
    normalized = str(value or "").strip().lower()
    if "prime" in normalized:
        return "prime"  # type: ignore[return-value]
    if "team" in normalized:
        return "team"  # type: ignore[return-value]
    if "suppress" in normalized:
        return "suppress"  # type: ignore[return-value]
    if "monitor" in normalized:
        return "monitor"  # type: ignore[return-value]
    if normalized in {"prime", "team", "monitor", "suppress"}:
        return normalized  # type: ignore[return-value]
    return "monitor"


def _coerce_action(value: Any) -> RecommendedAction:
    normalized = str(value or "").strip().lower()
    if "shortlist" in normalized or "pursue" in normalized:
        return "shortlist"  # type: ignore[return-value]
    if "watchlist" in normalized or "monitor" in normalized:
        return "watchlist"  # type: ignore[return-value]
    if "suppress" in normalized or "no bid" in normalized:
        return "suppress"  # type: ignore[return-value]
    if normalized in {"shortlist", "watchlist", "suppress"}:
        return normalized  # type: ignore[return-value]
    return "watchlist"


def _coerce_primary_reason(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    allowed = {
        "wrong_buyer",
        "wrong_mission_domain",
        "wrong_delivery_model",
        "incumbent_locked_continuity",
        "commodity_support_work",
        "wrong_set_aside",
        "wrong_vehicle",
        "wrong_scale",
        "wrong_timing",
        "wrong_geography",
        "weak_differentiation",
        "unclear_why",
    }
    return normalized if normalized in allowed else "unclear_why"


def _coerce_user_sentiment(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"positive", "negative", "neutral", "mixed"}:
        return normalized
    return "neutral"


def _coerce_evidence_spans(value: Any) -> list[ReasoningEvidenceSpan]:
    rows: list[ReasoningEvidenceSpan] = []
    if not isinstance(value, list):
        return rows
    for item in value:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        quote = str(item.get("quote") or item.get("text") or "").strip()
        why_it_matters = str(item.get("why_it_matters") or "").strip()
        if not (source or quote or why_it_matters):
            continue
        rows.append(
            {
                "source": source or "model_inference",
                "quote": quote,
                "why_it_matters": why_it_matters or "Supports the semantic judgment for this opportunity.",
            }
        )
    return rows[:4]


def _empty_semantic_entities() -> SemanticResolvedEntities:
    return {
        "semantic_positive_facets": [],
        "semantic_negative_facets": [],
        "mission_domains": [],
        "delivery_models": [],
        "contract_postures": [],
        "competitive_shapes": [],
        "set_aside_signals": [],
        "vehicle_signals": [],
        "teaming_postures": [],
    }


def _empty_applied_preferences() -> SemanticAppliedPreferences:
    return {
        "prefer_mission_domains": [],
        "avoid_mission_domains": [],
        "prefer_delivery_models": [],
        "avoid_delivery_models": [],
        "prefer_contract_postures": [],
        "avoid_contract_postures": [],
        "prefer_semantic_facets": [],
        "avoid_semantic_facets": [],
        "prefer_teaming_postures": [],
        "avoid_competitive_shapes": [],
        "notes": [],
    }


def _opportunity_text(record: dict[str, Any], hydrated_text: str) -> str:
    parts = [
        record.get("title", ""),
        record.get("summary", ""),
        hydrated_text,
        record.get("buyer", ""),
        record.get("set_aside", ""),
        record.get("notice_type", ""),
        record.get("opportunity_class", ""),
    ]
    return _normalized_text(" ".join(str(part or "") for part in parts))


def _vendor_text(vendor_profile: dict[str, Any]) -> str:
    company = vendor_profile.get("company", {}) if isinstance(vendor_profile.get("company"), dict) else {}
    competencies = vendor_profile.get("core_competencies", [])
    competency_parts: list[str] = []
    for item in competencies:
        if isinstance(item, dict):
            competency_parts.extend([str(item.get("name") or ""), str(item.get("summary") or "")])
        else:
            competency_parts.append(str(item or ""))
    buyers = vendor_profile.get("buyers", {}) if isinstance(vendor_profile.get("buyers"), dict) else {}
    parts = [
        vendor_profile.get("vendor_name", ""),
        vendor_profile.get("fit_narrative", ""),
        company.get("name", ""),
        company.get("summary", ""),
        *competency_parts,
        *buyers.get("preferred", []),
    ]
    return _normalized_text(" ".join(str(part or "") for part in parts))


def _extract_semantic_entities(record: dict[str, Any], hydrated_text: str) -> tuple[SemanticResolvedEntities, list[ReasoningEvidenceSpan]]:
    text = _opportunity_text(record, hydrated_text)
    entities = _empty_semantic_entities()
    evidence: list[ReasoningEvidenceSpan] = []

    entities["mission_domains"] = _collect_marker_hits(text, MISSION_DOMAIN_MARKERS)
    entities["delivery_models"] = _collect_marker_hits(text, DELIVERY_MODEL_MARKERS)
    technical_motions = _collect_marker_hits(text, TECHNICAL_MOTION_MARKERS)
    entities["vehicle_signals"] = _collect_marker_hits(text, VEHICLE_MARKERS)
    buyer_maturity_signals = _collect_marker_hits(text, BUYER_MATURITY_MARKERS)

    if entities["delivery_models"] and any(model in entities["delivery_models"] for model in ("continuity_support", "operations_support")):
        entities["contract_postures"].append("continuity_sensitive")
    if entities["vehicle_signals"]:
        entities["contract_postures"].append("vehicle_gated")
        entities["competitive_shapes"].append("vehicle_holder_advantaged")
    if str(record.get("set_aside") or "").strip() and str(record.get("set_aside") or "").strip().lower() not in {"n/a", "none", "not stated"}:
        entities["set_aside_signals"].append(_normalized_text(record.get("set_aside", "")))
        entities["contract_postures"].append("set_aside_restricted")
    notice_type = _normalized_text(record.get("notice_type", ""))
    opportunity_class = _normalized_text(record.get("opportunity_class", ""))
    if any(marker in notice_type for marker in ("sources sought", "request for information", "presolicitation", "industry day")) or opportunity_class in {
        "request for information",
        "sources sought",
        "presolicitation",
    }:
        entities["contract_postures"].append("shaping")
    if "continuity_sensitive" in entities["contract_postures"]:
        entities["competitive_shapes"].append("incumbent_advantaged")
    if any(model in entities["delivery_models"] for model in ("staff_augmentation", "operations_support", "program_management")):
        entities["competitive_shapes"].append("commodity_competition")
    if any(model in entities["delivery_models"] for model in ("implementation", "advisory")):
        entities["competitive_shapes"].append("whitespace_possible")
        entities["semantic_positive_facets"].append("enterprise_transformation")
    if "continuity_support" in entities["delivery_models"]:
        entities["semantic_negative_facets"].append("cots_sustainment")
        entities["semantic_negative_facets"].append("commodity_support")
    if "operations_maintenance" in technical_motions:
        entities["semantic_negative_facets"].append("operations_maintenance")
    if "migration" in technical_motions or "platform_modernization" in technical_motions:
        entities["semantic_positive_facets"].append("platform_modernization")

    entities["mission_domains"] = _dedupe_strings(entities["mission_domains"])
    entities["delivery_models"] = _dedupe_strings(entities["delivery_models"])
    entities["contract_postures"] = _dedupe_strings(entities["contract_postures"])
    entities["competitive_shapes"] = _dedupe_strings(entities["competitive_shapes"])
    entities["set_aside_signals"] = _dedupe_strings(entities["set_aside_signals"])
    entities["vehicle_signals"] = _dedupe_strings(entities["vehicle_signals"])
    entities["semantic_positive_facets"] = _dedupe_strings(entities["semantic_positive_facets"])
    entities["semantic_negative_facets"] = _dedupe_strings(entities["semantic_negative_facets"])

    if "vehicle_holder_advantaged" in entities["competitive_shapes"] or "incumbent_advantaged" in entities["competitive_shapes"]:
        entities["teaming_postures"].append("team_not_prime")
    elif entities["delivery_models"] or entities["mission_domains"]:
        entities["teaming_postures"].append("prime_possible")
    else:
        entities["teaming_postures"].append("monitor_only")
    entities["teaming_postures"] = _dedupe_strings(entities["teaming_postures"])

    for label, markers in MISSION_DOMAIN_MARKERS.items():
        if label in entities["mission_domains"]:
            evidence.append(
                {
                    "source": "notice_text",
                    "quote": _first_quote_for_markers(text, markers),
                    "why_it_matters": f"Signals mission domain: {label}.",
                }
            )
    for label, markers in DELIVERY_MODEL_MARKERS.items():
        if label in entities["delivery_models"]:
            evidence.append(
                {
                    "source": "notice_text",
                    "quote": _first_quote_for_markers(text, markers),
                    "why_it_matters": f"Signals delivery model: {label}.",
                }
            )
    for signal in buyer_maturity_signals[:1]:
        evidence.append(
            {
                "source": "notice_text",
                "quote": signal.replace("_", " "),
                "why_it_matters": "Suggests the notice has enough structure to support a semantic fit read.",
            }
        )
    return entities, evidence[:4]


def _heuristic_fit_assessment(
    record: dict[str, Any],
    hydrated_text: str,
    vendor_profile: dict[str, Any],
    deterministic_fit_context: dict[str, Any],
    learned_semantic_preferences: dict[str, Any] | None,
) -> ScanFitAssessmentPayload:
    vendor_text = _vendor_text(vendor_profile)
    notice_text = _opportunity_text(record, hydrated_text)
    entities, evidence_spans = _extract_semantic_entities(record, hydrated_text)
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    reasons_for: list[str] = []
    reasons_against: list[str] = []
    applied = learned_semantic_preferences or _empty_applied_preferences()

    for domain in entities["mission_domains"]:
        if _has_marker(vendor_text, domain.replace("_", " ")):
            positive_hits.append(domain)
            reasons_for.append(f"Mission domain aligns with vendor profile: {domain.replace('_', ' ')}.")
    for model in entities["delivery_models"]:
        if _has_marker(vendor_text, model.replace("_", " ")):
            positive_hits.append(model)
            reasons_for.append(f"Delivery model aligns with vendor profile: {model.replace('_', ' ')}.")

    prefer_mission_domains = set(applied.get("prefer_mission_domains", []))
    avoid_mission_domains = set(applied.get("avoid_mission_domains", []))
    prefer_delivery_models = set(applied.get("prefer_delivery_models", []))
    avoid_delivery_models = set(applied.get("avoid_delivery_models", []))
    prefer_semantic_facets = set(applied.get("prefer_semantic_facets", []))
    avoid_semantic_facets = set(applied.get("avoid_semantic_facets", []))
    prefer_teaming_postures = set(applied.get("prefer_teaming_postures", []))
    avoid_competitive_shapes = set(applied.get("avoid_competitive_shapes", []))

    for domain in entities["mission_domains"]:
        if domain in prefer_mission_domains:
            positive_hits.append(domain)
            reasons_for.append(f"Learned preference supports this mission domain: {domain.replace('_', ' ')}.")
        if domain in avoid_mission_domains:
            negative_hits.append(domain)
            reasons_against.append(f"Learned caution against this mission domain: {domain.replace('_', ' ')}.")
    for model in entities["delivery_models"]:
        if model in prefer_delivery_models:
            positive_hits.append(model)
            reasons_for.append(f"Learned preference supports this delivery model: {model.replace('_', ' ')}.")
        if model in avoid_delivery_models:
            negative_hits.append(model)
            reasons_against.append(f"Learned caution against this delivery model: {model.replace('_', ' ')}.")
    for facet in entities["semantic_positive_facets"]:
        if facet in prefer_semantic_facets:
            positive_hits.append(facet)
            reasons_for.append(f"Learned preference supports this work pattern: {facet.replace('_', ' ')}.")
    for facet in entities["semantic_negative_facets"]:
        if facet in avoid_semantic_facets:
            negative_hits.append(facet)
            reasons_against.append(f"Learned caution against this work pattern: {facet.replace('_', ' ')}.")
    for shape in entities["competitive_shapes"]:
        if shape in avoid_competitive_shapes:
            negative_hits.append(shape)
            reasons_against.append(f"Learned caution against this competitive shape: {shape.replace('_', ' ')}.")
    for posture in entities["teaming_postures"]:
        if posture in prefer_teaming_postures:
            positive_hits.append(posture)
            reasons_for.append(f"Learned teaming posture fits this opportunity: {posture.replace('_', ' ')}.")

    if "hard_eligibility_gate" in deterministic_fit_context and deterministic_fit_context.get("hard_eligibility_gate"):
        negative_hits.append("hard_eligibility_gate")
        reasons_against.append("Notice text indicates a hard vehicle or holder gate.")

    score_delta = len(_dedupe_strings(positive_hits)) - len(_dedupe_strings(negative_hits))
    if score_delta >= 2:
        fit_assessment: FitAssessment = "strong_fit"
    elif score_delta >= 0:
        fit_assessment = "adjacent_fit"
    elif negative_hits and not positive_hits:
        fit_assessment = "misleading_keyword_match"
    else:
        fit_assessment = "weak_fit"

    if "hard_eligibility_gate" in negative_hits:
        credible_posture: CrediblePosture = "monitor"
    elif "vehicle_holder_advantaged" in entities["competitive_shapes"] or "incumbent_advantaged" in entities["competitive_shapes"]:
        credible_posture = "team"
    elif fit_assessment == "strong_fit":
        credible_posture = "prime"
    elif fit_assessment == "adjacent_fit":
        credible_posture = "team"
    elif fit_assessment == "misleading_keyword_match":
        credible_posture = "suppress"
    else:
        credible_posture = "monitor"

    mission_alignment: AlignmentLevel = "high" if entities["mission_domains"] and positive_hits else "medium" if entities["mission_domains"] else "low"
    delivery_alignment: AlignmentLevel = "high" if entities["delivery_models"] and any(model in positive_hits for model in entities["delivery_models"]) else "medium" if entities["delivery_models"] else "low"
    customer_alignment: AlignmentLevel = "high" if deterministic_fit_context.get("buyer_match_points", 0) >= 10 else "medium" if deterministic_fit_context.get("buyer_match_points", 0) > 0 else "unknown"
    competitive_posture: CompetitivePosture = (
        "unfavorable"
        if "incumbent_advantaged" in entities["competitive_shapes"] or "vehicle_holder_advantaged" in entities["competitive_shapes"]
        else "favorable"
        if "whitespace_possible" in entities["competitive_shapes"]
        else "neutral"
    )
    incumbent_pressure: AlignmentLevel = "high" if "incumbent_advantaged" in entities["competitive_shapes"] else "medium" if "continuity_sensitive" in entities["contract_postures"] else "unknown"
    fit_confidence: ConfidenceLevel = "high" if reasons_for or reasons_against else "low"
    risk_flags = []
    if "vehicle_holder_advantaged" in entities["competitive_shapes"]:
        risk_flags.append("vehicle_access_unknown")
    if "incumbent_advantaged" in entities["competitive_shapes"]:
        risk_flags.append("incumbent_continuity_risk")
    recommended_action: RecommendedAction = "shortlist" if fit_assessment == "strong_fit" else "watchlist" if fit_assessment == "adjacent_fit" else "suppress"

    semantic_facets = {
        "mission_domains": entities["mission_domains"],
        "delivery_models": entities["delivery_models"],
        "technical_motions": _collect_marker_hits(notice_text, TECHNICAL_MOTION_MARKERS),
        "contract_postures": entities["contract_postures"],
        "buyer_maturity_signals": _collect_marker_hits(notice_text, BUYER_MATURITY_MARKERS),
        "negative_fit_facets": entities["semantic_negative_facets"],
        "positive_fit_facets": entities["semantic_positive_facets"],
    }

    reasoning_summary = reasons_for[0] if reasons_for else reasons_against[0] if reasons_against else "Semantic fit layer found limited extra signal."
    return {
        "schema_version": SCHEMA_VERSION,
        "reasoning_source": "heuristic_fallback",
        "model_name": "",
        "fit_assessment": fit_assessment,
        "credible_posture": credible_posture,
        "mission_alignment": mission_alignment,
        "delivery_alignment": delivery_alignment,
        "customer_alignment": customer_alignment,
        "competitive_posture": competitive_posture,
        "incumbent_pressure": incumbent_pressure,
        "fit_confidence": fit_confidence,
        "why_it_fits": _dedupe_strings(reasons_for)[:4],
        "why_it_does_not_fit": _dedupe_strings(reasons_against)[:4],
        "dominant_fit_factors": _dedupe_strings(positive_hits + negative_hits)[:4],
        "risk_flags": _dedupe_strings(risk_flags)[:4],
        "semantic_facets": semantic_facets,
        "evidence_spans": evidence_spans,
        "recommended_action": recommended_action,
        "reasoning_summary": reasoning_summary,
    }


def _heuristic_feedback_interpretation(
    user_text: str,
    feedback_kind: str,
    reward: int,
    record: dict[str, Any],
    hydrated_text: str,
    vendor_profile: dict[str, Any],
) -> SemanticFeedbackPayload:
    lower_user_text = _normalized_text(user_text)
    entities, evidence_spans = _extract_semantic_entities(record, hydrated_text)
    user_sentiment = "positive" if reward > 0 else "negative" if reward < 0 else "neutral"
    primary_reason = "unclear_why"
    secondary_reasons: list[str] = []
    reasoning: list[str] = []

    if "wrong buyer" in lower_user_text or "bad buyer" in lower_user_text:
        primary_reason = "wrong_buyer"
    elif "wrong vehicle" in lower_user_text:
        primary_reason = "wrong_vehicle"
    elif "wrong timing" in lower_user_text:
        primary_reason = "wrong_timing"
    elif "wrong location" in lower_user_text:
        primary_reason = "wrong_geography"
    elif "bad eligibility" in lower_user_text or "wrong eligibility" in lower_user_text:
        primary_reason = "wrong_set_aside" if entities["set_aside_signals"] else "wrong_vehicle"
    elif "too small" in lower_user_text or "too large" in lower_user_text:
        primary_reason = "wrong_scale"
    elif "teaming only" in lower_user_text or "subcontract only" in lower_user_text or "sub only" in lower_user_text:
        primary_reason = "weak_differentiation"
    elif reward < 0 and "incumbent_advantaged" in entities["competitive_shapes"] and "continuity_support" in entities["delivery_models"]:
        primary_reason = "incumbent_locked_continuity"
        secondary_reasons.append("commodity_support_work")
    elif reward < 0 and ("commodity_competition" in entities["competitive_shapes"] or "operations_support" in entities["delivery_models"]):
        primary_reason = "commodity_support_work"
    elif reward < 0 and entities["mission_domains"]:
        primary_reason = "wrong_mission_domain"
    elif reward < 0 and entities["delivery_models"]:
        primary_reason = "wrong_delivery_model"

    if reward < 0 and primary_reason == "incumbent_locked_continuity":
        reasoning.append("Negative feedback appears driven by continuity-heavy support with strong incumbent advantage.")
    elif reward < 0 and primary_reason == "commodity_support_work":
        reasoning.append("Negative feedback appears driven by commodity-like support work rather than differentiated transformation scope.")
    elif reward > 0:
        reasoning.append("Positive feedback appears tied to credible mission and delivery alignment.")
    else:
        reasoning.append("Feedback meaning remains only partially explicit from the current user note.")

    accepted_facets = entities["semantic_positive_facets"] if reward > 0 else []
    rejected_facets = list(dict.fromkeys(entities["semantic_negative_facets"] + entities["delivery_models"][:2])) if reward < 0 else []
    accepted_postures = entities["teaming_postures"] if reward > 0 else []
    rejected_postures = ["prime"] if reward < 0 and "team_not_prime" in entities["teaming_postures"] else []
    accepted_mission_domains = entities["mission_domains"] if reward > 0 else []
    rejected_mission_domains = entities["mission_domains"] if reward < 0 else []
    accepted_delivery_models = entities["delivery_models"] if reward > 0 else []
    rejected_delivery_models = entities["delivery_models"] if reward < 0 else []
    buyer_specific = primary_reason == "wrong_buyer"
    vehicle_specific = primary_reason == "wrong_vehicle"
    set_aside_specific = primary_reason == "wrong_set_aside"
    naics_specific = False
    generalizable = not any((buyer_specific, vehicle_specific, set_aside_specific)) or bool(rejected_delivery_models or rejected_facets)
    reason_confidence: ConfidenceLevel = "medium" if primary_reason != "unclear_why" else "low"

    interpretation: FeedbackInterpretation = {
        "user_sentiment": user_sentiment,  # type: ignore[typeddict-item]
        "primary_reason": primary_reason,  # type: ignore[typeddict-item]
        "secondary_reasons": _dedupe_strings(secondary_reasons),
        "reason_confidence": reason_confidence,
        "accepted_facets": _dedupe_strings(accepted_facets),
        "rejected_facets": _dedupe_strings(rejected_facets),
        "accepted_postures": _dedupe_strings(accepted_postures),
        "rejected_postures": _dedupe_strings(rejected_postures),
        "accepted_mission_domains": _dedupe_strings(accepted_mission_domains),
        "rejected_mission_domains": _dedupe_strings(rejected_mission_domains),
        "accepted_delivery_models": _dedupe_strings(accepted_delivery_models),
        "rejected_delivery_models": _dedupe_strings(rejected_delivery_models),
        "buyer_specific": buyer_specific,
        "naics_specific": naics_specific,
        "set_aside_specific": set_aside_specific,
        "vehicle_specific": vehicle_specific,
        "generalizable": generalizable,
        "reasoning": reasoning[:3],
        "evidence_spans": evidence_spans[:3],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "feedback_interpretation": interpretation,
        "resolved_entities": entities,
        "reasoning_summary": reasoning[0],
    }


def _sanitize_vendor_profile(vendor_profile: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(vendor_profile, ensure_ascii=True)
    if len(text) <= MAX_VENDOR_JSON:
        return vendor_profile
    return {
        "vendor_name": vendor_profile.get("vendor_name"),
        "fit_narrative": vendor_profile.get("fit_narrative"),
        "company": vendor_profile.get("company"),
        "core_competencies": vendor_profile.get("core_competencies", [])[:10],
        "buyers": vendor_profile.get("buyers"),
        "naics": vendor_profile.get("naics"),
    }


def _openai_client(api_key: str | None = None):
    if OpenAI is None:
        return None
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        return OpenAI(api_key=key)
    except Exception:
        return None


def _call_openai_json(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    model: str | None,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    client = _openai_client()
    if client is None:
        return None
    effective_timeout = max(int(timeout_seconds or 0), DEFAULT_REASONING_TIMEOUT_SECONDS)
    try:
        message = json.dumps(user_payload, ensure_ascii=True)
        completion = client.with_options(timeout=effective_timeout).chat.completions.create(
            model=model or DEFAULT_REASONING_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        )
    except Exception:
        return None
    try:
        content = completion.choices[0].message.content or "{}"
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        return json.loads(str(content))
    except Exception:
        return None


def _coerce_scan_fit_payload(value: dict[str, Any] | None, fallback: ScanFitAssessmentPayload) -> ScanFitAssessmentPayload:
    if not isinstance(value, dict):
        return fallback
    semantic_facets_value = value.get("semantic_facets") if isinstance(value.get("semantic_facets"), dict) else {}
    semantic_facets = {
        "mission_domains": _coerce_string_list(semantic_facets_value.get("mission_domains")),
        "delivery_models": _coerce_string_list(semantic_facets_value.get("delivery_models")),
        "technical_motions": _coerce_string_list(semantic_facets_value.get("technical_motions")),
        "contract_postures": _coerce_string_list(semantic_facets_value.get("contract_postures")),
        "buyer_maturity_signals": _coerce_string_list(semantic_facets_value.get("buyer_maturity_signals")),
        "negative_fit_facets": _coerce_string_list(semantic_facets_value.get("negative_fit_facets")),
        "positive_fit_facets": _coerce_string_list(semantic_facets_value.get("positive_fit_facets")),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "reasoning_source": str(value.get("reasoning_source") or "openai_model").strip() or "openai_model",
        "model_name": str(value.get("model_name") or fallback.get("model_name") or DEFAULT_REASONING_MODEL).strip(),
        "fit_assessment": _coerce_fit_assessment(value.get("fit_assessment")),
        "credible_posture": _coerce_posture(value.get("credible_posture")),
        "mission_alignment": _coerce_alignment(value.get("mission_alignment")),
        "delivery_alignment": _coerce_alignment(value.get("delivery_alignment")),
        "customer_alignment": _coerce_alignment(value.get("customer_alignment")),
        "competitive_posture": _coerce_competitive_posture(value.get("competitive_posture")),
        "incumbent_pressure": _coerce_alignment(value.get("incumbent_pressure")),
        "fit_confidence": _coerce_confidence(value.get("fit_confidence")),
        "why_it_fits": _coerce_string_list(value.get("why_it_fits")) or fallback.get("why_it_fits", []),
        "why_it_does_not_fit": _coerce_string_list(value.get("why_it_does_not_fit")) or fallback.get("why_it_does_not_fit", []),
        "dominant_fit_factors": _coerce_string_list(value.get("dominant_fit_factors")) or fallback.get("dominant_fit_factors", []),
        "risk_flags": _coerce_string_list(value.get("risk_flags")) or fallback.get("risk_flags", []),
        "semantic_facets": semantic_facets,
        "evidence_spans": _coerce_evidence_spans(value.get("evidence_spans")) or fallback.get("evidence_spans", []),
        "recommended_action": _coerce_action(value.get("recommended_action")),
        "reasoning_summary": str(value.get("reasoning_summary") or fallback.get("reasoning_summary") or "").strip(),
    }


def _coerce_semantic_feedback_payload(value: dict[str, Any] | None, fallback: SemanticFeedbackPayload) -> SemanticFeedbackPayload:
    if not isinstance(value, dict):
        return fallback
    interpretation_value = value.get("feedback_interpretation") if isinstance(value.get("feedback_interpretation"), dict) else {}
    resolved_entities_value = value.get("resolved_entities") if isinstance(value.get("resolved_entities"), dict) else {}
    interpretation: FeedbackInterpretation = {
        "user_sentiment": _coerce_user_sentiment(interpretation_value.get("user_sentiment")),  # type: ignore[typeddict-item]
        "primary_reason": _coerce_primary_reason(interpretation_value.get("primary_reason")),  # type: ignore[typeddict-item]
        "secondary_reasons": _coerce_string_list(interpretation_value.get("secondary_reasons")),
        "reason_confidence": _coerce_confidence(interpretation_value.get("reason_confidence")),
        "accepted_facets": _coerce_string_list(interpretation_value.get("accepted_facets")),
        "rejected_facets": _coerce_string_list(interpretation_value.get("rejected_facets")),
        "accepted_postures": _coerce_string_list(interpretation_value.get("accepted_postures")),
        "rejected_postures": _coerce_string_list(interpretation_value.get("rejected_postures")),
        "accepted_mission_domains": _coerce_string_list(interpretation_value.get("accepted_mission_domains")),
        "rejected_mission_domains": _coerce_string_list(interpretation_value.get("rejected_mission_domains")),
        "accepted_delivery_models": _coerce_string_list(interpretation_value.get("accepted_delivery_models")),
        "rejected_delivery_models": _coerce_string_list(interpretation_value.get("rejected_delivery_models")),
        "buyer_specific": bool(interpretation_value.get("buyer_specific")),
        "naics_specific": bool(interpretation_value.get("naics_specific")),
        "set_aside_specific": bool(interpretation_value.get("set_aside_specific")),
        "vehicle_specific": bool(interpretation_value.get("vehicle_specific")),
        "generalizable": bool(interpretation_value.get("generalizable")),
        "reasoning": _coerce_string_list(interpretation_value.get("reasoning")) or fallback["feedback_interpretation"]["reasoning"],
        "evidence_spans": _coerce_evidence_spans(interpretation_value.get("evidence_spans")) or fallback["feedback_interpretation"]["evidence_spans"],
    }
    resolved_entities: SemanticResolvedEntities = {
        "semantic_positive_facets": _coerce_string_list(resolved_entities_value.get("semantic_positive_facets")),
        "semantic_negative_facets": _coerce_string_list(resolved_entities_value.get("semantic_negative_facets")),
        "mission_domains": _coerce_string_list(resolved_entities_value.get("mission_domains")),
        "delivery_models": _coerce_string_list(resolved_entities_value.get("delivery_models")),
        "contract_postures": _coerce_string_list(resolved_entities_value.get("contract_postures")),
        "competitive_shapes": _coerce_string_list(resolved_entities_value.get("competitive_shapes")),
        "set_aside_signals": _coerce_string_list(resolved_entities_value.get("set_aside_signals")),
        "vehicle_signals": _coerce_string_list(resolved_entities_value.get("vehicle_signals")),
        "teaming_postures": _coerce_string_list(resolved_entities_value.get("teaming_postures")),
    }
    if not any(resolved_entities.values()):
        resolved_entities = fallback["resolved_entities"]
    return {
        "schema_version": SCHEMA_VERSION,
        "feedback_interpretation": interpretation,
        "resolved_entities": resolved_entities,
        "reasoning_summary": str(value.get("reasoning_summary") or fallback.get("reasoning_summary") or "").strip(),
    }


def assess_scan_fit(
    *,
    record: dict[str, Any],
    hydrated_text: str,
    vendor_profile: dict[str, Any],
    deterministic_fit_context: dict[str, Any],
    learned_semantic_preferences: dict[str, Any] | None = None,
    model: str | None = None,
    timeout_seconds: int = 30,
) -> ScanFitAssessmentPayload | None:
    heuristic = _heuristic_fit_assessment(
        record,
        hydrated_text,
        vendor_profile,
        deterministic_fit_context,
        learned_semantic_preferences,
    )
    user_payload = {
        "record": {
            "title": record.get("title"),
            "summary": record.get("summary"),
            "buyer": record.get("buyer"),
            "notice_type": record.get("notice_type"),
            "opportunity_class": record.get("opportunity_class"),
            "set_aside": record.get("set_aside"),
            "naics": record.get("naics"),
        },
        "hydrated_text": _clip_text(hydrated_text, MAX_NOTICE_TEXT),
        "vendor_profile": _sanitize_vendor_profile(vendor_profile),
        "deterministic_fit_context": deterministic_fit_context,
        "learned_semantic_preferences": learned_semantic_preferences or _empty_applied_preferences(),
        "heuristic_seed": heuristic,
    }
    model_name = model or DEFAULT_REASONING_MODEL
    model_result = _call_openai_json(
        system_prompt=(
            "You are a federal capture analyst. Read the opportunity and vendor profile semantically. "
            "Return only compact JSON. Prefer honest downgrade over generic optimism. Preserve missing evidence as missing. "
            "Use exact enum values only: fit_assessment=strong_fit|adjacent_fit|weak_fit|misleading_keyword_match; "
            "credible_posture=prime|team|monitor|suppress; mission_alignment, delivery_alignment, customer_alignment, incumbent_pressure=high|medium|low|unknown; "
            "competitive_posture=favorable|neutral|unfavorable|unknown; fit_confidence=high|medium|low; "
            "recommended_action=shortlist|watchlist|suppress. "
            "Return why_it_fits, why_it_does_not_fit, dominant_fit_factors, risk_flags as arrays of short strings; "
            "return semantic_facets as an object with string-array fields; return evidence_spans as [{source, quote, why_it_matters}]."
        ),
        user_payload=user_payload,
        model=model_name,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(model_result, dict):
        return heuristic
    model_result.setdefault("reasoning_source", "openai_model")
    model_result.setdefault("model_name", model_name)
    return _coerce_scan_fit_payload(model_result, heuristic)


def interpret_feedback(
    *,
    user_text: str,
    feedback_kind: str,
    reward: int,
    record: dict[str, Any],
    hydrated_text: str,
    vendor_profile: dict[str, Any],
    prior_scan_fit: dict[str, Any] | None = None,
    learned_semantic_preferences: dict[str, Any] | None = None,
    model: str | None = None,
    timeout_seconds: int = 20,
) -> SemanticFeedbackPayload | None:
    heuristic = _heuristic_feedback_interpretation(
        user_text,
        feedback_kind,
        reward,
        record,
        hydrated_text,
        vendor_profile,
    )
    user_payload = {
        "user_text": user_text,
        "feedback_kind": feedback_kind,
        "reward": reward,
        "record": {
            "title": record.get("title"),
            "summary": record.get("summary"),
            "buyer": record.get("buyer"),
            "notice_type": record.get("notice_type"),
            "opportunity_class": record.get("opportunity_class"),
            "set_aside": record.get("set_aside"),
            "naics": record.get("naics"),
        },
        "hydrated_text": _clip_text(hydrated_text, MAX_NOTICE_TEXT),
        "vendor_profile": _sanitize_vendor_profile(vendor_profile),
        "prior_scan_fit": prior_scan_fit or {},
        "learned_semantic_preferences": learned_semantic_preferences or _empty_applied_preferences(),
        "heuristic_seed": heuristic,
    }
    model_result = _call_openai_json(
        system_prompt=(
            "You are a federal capture analyst interpreting user feedback on an opportunity. "
            "Infer what the user appears to like or dislike about the work itself, not just the buyer or keywords. "
            "Return only JSON. Do not invent certainty."
        ),
        user_payload=user_payload,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    return _coerce_semantic_feedback_payload(model_result, heuristic)


def _score_rows(score_map: dict[str, float], count_map: dict[str, int]) -> list[SemanticAggregateRow]:
    rows: list[SemanticAggregateRow] = []
    for value, score in score_map.items():
        rows.append(
            {
                "value": value,
                "score": round(score, 3),
                "event_count": int(count_map.get(value, 0)),
            }
        )
    rows.sort(key=lambda item: (abs(float(item["score"])), int(item["event_count"]), item["value"]), reverse=True)
    return rows


def aggregate_semantic_feedback(
    *,
    events: list[dict[str, Any]],
    decay_rate_monthly: float,
    promotion_threshold: float,
) -> SemanticLearningSummary:
    from datetime import datetime, timezone

    from feedback.learning import _decayed_reward

    now_utc = datetime.now(timezone.utc)
    semantic_dimensions = {
        "mission_domains": defaultdict(float),
        "delivery_models": defaultdict(float),
        "contract_postures": defaultdict(float),
        "competitive_shapes": defaultdict(float),
        "set_aside_signals": defaultdict(float),
        "vehicle_signals": defaultdict(float),
        "teaming_postures": defaultdict(float),
        "semantic_facets": defaultdict(float),
    }
    semantic_counts = {
        key: defaultdict(int)
        for key in semantic_dimensions
    }
    applied = _empty_applied_preferences()

    for event in events:
        semantic_feedback = event.get("semantic_feedback", {})
        if not isinstance(semantic_feedback, dict):
            continue
        interpretation = semantic_feedback.get("feedback_interpretation", {})
        resolved_entities = semantic_feedback.get("resolved_entities", {})
        if not isinstance(interpretation, dict) or not isinstance(resolved_entities, dict):
            continue
        if not interpretation.get("generalizable", False):
            continue
        weighted_reward = _decayed_reward(event, decay_rate_monthly, now_utc)
        if weighted_reward == 0:
            continue
        multiplier = _confidence_multiplier(interpretation.get("reason_confidence"))
        adjusted_reward = weighted_reward * multiplier

        for dimension in (
            "mission_domains",
            "delivery_models",
            "contract_postures",
            "competitive_shapes",
            "set_aside_signals",
            "vehicle_signals",
            "teaming_postures",
        ):
            values = resolved_entities.get(dimension, [])
            if not isinstance(values, list):
                continue
            for value in _dedupe_strings(values):
                semantic_dimensions[dimension][value] += adjusted_reward
                semantic_counts[dimension][value] += 1

        for value in _dedupe_strings(resolved_entities.get("semantic_positive_facets", [])):
            semantic_dimensions["semantic_facets"][value] += abs(adjusted_reward)
            semantic_counts["semantic_facets"][value] += 1
        for value in _dedupe_strings(resolved_entities.get("semantic_negative_facets", [])):
            semantic_dimensions["semantic_facets"][value] -= abs(adjusted_reward)
            semantic_counts["semantic_facets"][value] += 1

    for value, score in semantic_dimensions["mission_domains"].items():
        if score >= promotion_threshold:
            applied["prefer_mission_domains"].append(value)
        elif score <= -promotion_threshold:
            applied["avoid_mission_domains"].append(value)
    for value, score in semantic_dimensions["delivery_models"].items():
        if score >= promotion_threshold:
            applied["prefer_delivery_models"].append(value)
        elif score <= -promotion_threshold:
            applied["avoid_delivery_models"].append(value)
    for value, score in semantic_dimensions["contract_postures"].items():
        if score >= promotion_threshold:
            applied["prefer_contract_postures"].append(value)
        elif score <= -promotion_threshold:
            applied["avoid_contract_postures"].append(value)
    for value, score in semantic_dimensions["semantic_facets"].items():
        if score >= promotion_threshold:
            applied["prefer_semantic_facets"].append(value)
        elif score <= -promotion_threshold:
            applied["avoid_semantic_facets"].append(value)
    for value, score in semantic_dimensions["teaming_postures"].items():
        if score >= promotion_threshold:
            applied["prefer_teaming_postures"].append(value)
    for value, score in semantic_dimensions["competitive_shapes"].items():
        if score <= -promotion_threshold:
            applied["avoid_competitive_shapes"].append(value)

    if applied["avoid_delivery_models"]:
        applied["notes"].append(
            "Learned caution on delivery models: " + ", ".join(applied["avoid_delivery_models"][:4])
        )
    if applied["prefer_delivery_models"]:
        applied["notes"].append(
            "Learned preferred delivery models: " + ", ".join(applied["prefer_delivery_models"][:4])
        )
    if applied["avoid_semantic_facets"]:
        applied["notes"].append(
            "Learned caution on work patterns: " + ", ".join(applied["avoid_semantic_facets"][:4])
        )

    return {
        "feedback_event_count": len(events),
        "threshold": float(promotion_threshold),
        "semantic_aggregates": {
            dimension: _score_rows(semantic_dimensions[dimension], semantic_counts[dimension])
            for dimension in semantic_dimensions
        },
        "semantic_applied_preferences": {
            key: _dedupe_strings(values) if isinstance(values, list) else []
            for key, values in applied.items()
        },
    }
