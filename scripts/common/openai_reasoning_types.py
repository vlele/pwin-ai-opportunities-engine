from __future__ import annotations

from typing import Any, Literal, TypedDict


FitAssessment = Literal[
    "strong_fit",
    "adjacent_fit",
    "weak_fit",
    "misleading_keyword_match",
]

CrediblePosture = Literal["prime", "team", "monitor", "suppress"]
AlignmentLevel = Literal["high", "medium", "low", "unknown"]
CompetitivePosture = Literal["favorable", "neutral", "unfavorable", "unknown"]
ConfidenceLevel = Literal["high", "medium", "low"]
RecommendedAction = Literal["shortlist", "watchlist", "suppress"]

UserSentiment = Literal["positive", "negative", "neutral", "mixed"]
PrimaryReason = Literal[
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
]


class ReasoningEvidenceSpan(TypedDict):
    source: str
    quote: str
    why_it_matters: str


class SemanticFacets(TypedDict):
    mission_domains: list[str]
    delivery_models: list[str]
    technical_motions: list[str]
    contract_postures: list[str]
    buyer_maturity_signals: list[str]
    negative_fit_facets: list[str]
    positive_fit_facets: list[str]


class ScanFitAssessmentPayload(TypedDict):
    schema_version: str
    reasoning_source: str
    model_name: str
    fit_assessment: FitAssessment
    credible_posture: CrediblePosture
    mission_alignment: AlignmentLevel
    delivery_alignment: AlignmentLevel
    customer_alignment: AlignmentLevel
    competitive_posture: CompetitivePosture
    incumbent_pressure: AlignmentLevel
    fit_confidence: ConfidenceLevel
    why_it_fits: list[str]
    why_it_does_not_fit: list[str]
    dominant_fit_factors: list[str]
    risk_flags: list[str]
    semantic_facets: SemanticFacets
    evidence_spans: list[ReasoningEvidenceSpan]
    recommended_action: RecommendedAction
    reasoning_summary: str


class FeedbackInterpretation(TypedDict):
    user_sentiment: UserSentiment
    primary_reason: PrimaryReason
    secondary_reasons: list[str]
    reason_confidence: ConfidenceLevel
    accepted_facets: list[str]
    rejected_facets: list[str]
    accepted_postures: list[str]
    rejected_postures: list[str]
    accepted_mission_domains: list[str]
    rejected_mission_domains: list[str]
    accepted_delivery_models: list[str]
    rejected_delivery_models: list[str]
    buyer_specific: bool
    naics_specific: bool
    set_aside_specific: bool
    vehicle_specific: bool
    generalizable: bool
    reasoning: list[str]
    evidence_spans: list[ReasoningEvidenceSpan]


class SemanticResolvedEntities(TypedDict):
    semantic_positive_facets: list[str]
    semantic_negative_facets: list[str]
    mission_domains: list[str]
    delivery_models: list[str]
    contract_postures: list[str]
    competitive_shapes: list[str]
    set_aside_signals: list[str]
    vehicle_signals: list[str]
    teaming_postures: list[str]


class SemanticFeedbackPayload(TypedDict):
    schema_version: str
    feedback_interpretation: FeedbackInterpretation
    resolved_entities: SemanticResolvedEntities
    reasoning_summary: str


class SemanticAggregateRow(TypedDict):
    value: str
    score: float
    event_count: int


class SemanticAppliedPreferences(TypedDict):
    prefer_mission_domains: list[str]
    avoid_mission_domains: list[str]
    prefer_delivery_models: list[str]
    avoid_delivery_models: list[str]
    prefer_contract_postures: list[str]
    avoid_contract_postures: list[str]
    prefer_semantic_facets: list[str]
    avoid_semantic_facets: list[str]
    prefer_teaming_postures: list[str]
    avoid_competitive_shapes: list[str]
    notes: list[str]


class SemanticLearningSummary(TypedDict):
    feedback_event_count: int
    threshold: float
    semantic_aggregates: dict[str, list[SemanticAggregateRow]]
    semantic_applied_preferences: SemanticAppliedPreferences


class SemanticPreferenceState(TypedDict):
    semantic_signal_scores: dict[str, dict[str, float]]
    semantic_signal_event_counts: dict[str, dict[str, int]]
    semantic_aggregates: dict[str, list[SemanticAggregateRow]]
    semantic_applied_preferences: SemanticAppliedPreferences


class OpenAIReasoningResultEnvelope(TypedDict):
    ok: bool
    model: str
    latency_ms: int
    payload: dict[str, Any]
    error: str | None
