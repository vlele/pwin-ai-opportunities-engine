from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


def _reasoning_default_for_env(env: dict[str, str]) -> str:
    sys.modules.pop("common.openai_reasoning", None)
    with patch.dict(os.environ, env, clear=True):
        module = importlib.import_module("common.openai_reasoning")
    sys.modules.pop("common.openai_reasoning", None)
    return str(module.DEFAULT_REASONING_MODEL)


def _row_values(rows: list[dict]) -> set[str]:
    return {str(row.get("value") or "") for row in rows}


def main() -> int:
    failures: list[str] = []

    if _reasoning_default_for_env({}) != "gpt-5.4-mini":
        failures.append("default_reasoning_model")

    if _reasoning_default_for_env({"OPENAI_MODEL": "openai-env-model"}) != "openai-env-model":
        failures.append("openai_model_override")

    if (
        _reasoning_default_for_env(
            {
                "OPENAI_MODEL": "openai-env-model",
                "PWIN_REASONING_MODEL": "pwin-reasoning-env-model",
            }
        )
        != "pwin-reasoning-env-model"
    ):
        failures.append("pwin_reasoning_model_override")

    reasoning = importlib.import_module("common.openai_reasoning")

    heuristic_zero_delta = reasoning._heuristic_fit_assessment(
        record={
            "title": "General support services",
            "summary": "Provide routine support coordination for administrative users.",
            "buyer": "Department of Agriculture",
            "notice_type": "Solicitation",
            "opportunity_class": "IT Services",
            "set_aside": "Total Small Business Set-Aside",
            "naics": [],
        },
        hydrated_text="Provide routine support coordination for administrative users.",
        vendor_profile={
            "fit_narrative": "Prioritize modernization, cloud engineering, and data platform work. Avoid hardware procurement."
        },
        deterministic_fit_context={},
        learned_semantic_preferences=None,
    )
    if heuristic_zero_delta.get("fit_assessment") != "weak_fit":
        failures.append("heuristic_zero_delta_not_weak_fit")

    broad_model_result = {
        "feedback_interpretation": {
            "user_sentiment": "negative",
            "primary_reason": "wrong_work",
            "secondary_reasons": [],
            "reason_confidence": "medium",
            "accepted_facets": [],
            "rejected_facets": ["commodity_support"],
            "accepted_postures": [],
            "rejected_postures": ["prime_possible"],
            "accepted_mission_domains": [],
            "rejected_mission_domains": ["data_management"],
            "accepted_delivery_models": [],
            "rejected_delivery_models": ["implementation"],
            "buyer_specific": False,
            "naics_specific": False,
            "set_aside_specific": False,
            "vehicle_specific": False,
            "generalizable": True,
            "reasoning": ["Model tried to generalize from the full opportunity context."],
            "evidence_spans": [],
        },
        "resolved_entities": {
            "semantic_positive_facets": [],
            "semantic_negative_facets": ["commodity_support"],
            "mission_domains": ["data_management"],
            "delivery_models": ["implementation"],
            "contract_postures": ["set_aside_restricted"],
            "competitive_shapes": [],
            "set_aside_signals": ["no set aside used"],
            "vehicle_signals": [],
            "teaming_postures": ["prime_possible"],
        },
        "reasoning_summary": "Model tried to generalize from the full opportunity context.",
    }
    record = {
        "title": "Data platform equipment refresh",
        "summary": "Data management support with reseller hardware and equipment buys.",
        "set_aside": "no set aside used",
        "notice_type": "Sources Sought",
        "opportunity_class": "Sources Sought",
    }
    with patch.object(reasoning, "_call_openai_json", return_value=broad_model_result):
        feedback_payload = reasoning.interpret_feedback(
            user_text="dislike E6 because reseller hardware and equipment buys are not a target fit",
            feedback_kind="dislike",
            reward=-1,
            record=record,
            hydrated_text="",
            vendor_profile={},
        )
    interpretation = feedback_payload["feedback_interpretation"]
    if interpretation.get("rejected_facets") != ["reseller_hardware_equipment_buy"]:
        failures.append("reseller_feedback_explicit_facet")
    if interpretation.get("rejected_mission_domains"):
        failures.append("reseller_feedback_no_mission_reject")
    if interpretation.get("rejected_delivery_models"):
        failures.append("reseller_feedback_no_delivery_reject")
    if interpretation.get("rejected_postures"):
        failures.append("reseller_feedback_no_posture_reject")

    aggregate = reasoning.aggregate_semantic_feedback(
        events=[
            {
                "reward": -1,
                "user_utterance": "dislike E6 because reseller hardware and equipment buys are not a target fit",
                "semantic_feedback": broad_model_result,
            }
        ],
        decay_rate_monthly=0.0,
        promotion_threshold=0.5,
    )
    semantic_aggregates = aggregate.get("semantic_aggregates", {})
    semantic_preferences = aggregate.get("semantic_applied_preferences", {})
    if "reseller_hardware_equipment_buy" not in _row_values(semantic_aggregates.get("semantic_facets", [])):
        failures.append("reseller_aggregate_facet")
    if semantic_aggregates.get("mission_domains"):
        failures.append("reseller_aggregate_no_mission")
    if semantic_aggregates.get("contract_postures"):
        failures.append("reseller_aggregate_no_contract_posture")
    if semantic_aggregates.get("set_aside_signals"):
        failures.append("reseller_aggregate_no_set_aside")
    if semantic_aggregates.get("teaming_postures"):
        failures.append("reseller_aggregate_no_teaming")
    if semantic_preferences.get("avoid_semantic_facets") != ["reseller_hardware_equipment_buy"]:
        failures.append("reseller_preference_only_explicit_facet")
    if semantic_preferences.get("avoid_mission_domains"):
        failures.append("reseller_preference_no_mission")

    mission_aggregate = reasoning.aggregate_semantic_feedback(
        events=[
            {
                "reward": -1,
                "user_utterance": "dislike E6 because data management is not a target fit",
                "semantic_feedback": broad_model_result,
            }
        ],
        decay_rate_monthly=0.0,
        promotion_threshold=0.5,
    )
    mission_preferences = mission_aggregate.get("semantic_applied_preferences", {})
    if mission_preferences.get("avoid_mission_domains") != ["data_management"]:
        failures.append("explicit_mission_domain_reject")

    with patch.object(reasoning, "_call_openai_json", return_value=None):
        capture_fallback = reasoning.assess_capture_strategy(
            vendor_profile={
                "vendor_name": "Example Vendor",
                "fit_narrative": "Focus on transformation, testing, and delivery discipline.",
            },
            resolved={
                "title": "Independent testing support",
                "buyer": "Department of Veterans Affairs",
                "solicitation_number": "ABC123",
            },
            solicitation_facts={
                "contract_type": "Firm Fixed Price",
                "evaluation_basis": "Best Value",
                "quoted_facts": ["The contractor shall deliver test reports and transition plans."],
            },
            solicitation_fact_model={
                "workstream_fact_rows": [
                    {
                        "category": "testing_traceability",
                        "text": "Independent testing, traceability, and reporting are explicit workstreams.",
                        "evidence_anchor": "PWS 5.2 testing services",
                        "confidence": "high",
                    }
                ]
            },
            attachment_workstreams=[
                {
                    "title": "Testing support",
                    "objective": "The contractor shall execute testing and deliver weekly reports.",
                    "evidence_snippets": ["PWS 5.2.1: execute testing and submit weekly reports."],
                }
            ],
            evaluator_anxiety_model={
                "central_pain_point": "Testing throughput and review quality look operationally important.",
                "reasoning_summary": "The package reads like real execution support with visible testing outputs.",
                "reasoned_pain_points": ["Testing throughput and review quality look operationally important."],
                "reasoned_win_themes": ["Show how the team executes visible testing workstreams from day one."],
                "reasoned_differentiators": ["Bring proof of IV&V delivery in similar federal environments."],
                "proof_requirements": ["Provide a sample testing report and transition plan."],
                "pricing_posture": ["Price must cover the visible testing cadence and reporting load."],
                "risk_implications": ["Funding and incumbent posture still need official validation."],
                "evaluator_anxiety_rows": [
                    {
                        "category": "testing_traceability",
                        "text": "Testing throughput and review quality look operationally important.",
                        "evidence_anchor": "PWS 5.2.1",
                        "confidence": "high",
                    }
                ],
                "reasoned_pain_point_rows": [],
                "reasoned_win_theme_rows": [],
                "reasoned_differentiator_rows": [],
                "proof_requirement_rows": [],
            },
            public_research={"requirement_relevant_ratio": 0.0},
            normalized_evidence={},
        )
    if capture_fallback.get("reasoning_source") != "unavailable":
        failures.append("capture_strategy_fallback_source")
    if capture_fallback.get("reasoned_win_themes"):
        failures.append("capture_strategy_fallback_win_themes")
    if capture_fallback.get("evaluator_anxiety_rows"):
        failures.append("capture_strategy_fallback_rows")
    if capture_fallback.get("vendor_fit_assessment", {}).get("status") != "unknown":
        failures.append("capture_strategy_missing_model_must_leave_fit_unknown")

    capture_model_result = {
        "reasoning_source": "openai_model",
        "model_name": "capture-reasoning-test-model",
        "central_pain_point": "The buyer appears worried about transition and test-control breakdowns.",
        "reasoning_summary": "Transition sequencing and quality-control visibility dominate the requirement.",
        "reasoned_pain_points": [
            "Transition sequencing and startup discipline appear central to evaluator confidence."
        ],
        "reasoned_win_themes": [
            "Show exactly how transition and testing cadence will operate in the first 30 days."
        ],
        "reasoned_differentiators": [
            "Bring artifacts that prove low-drama transition and traceable test reporting."
        ],
        "proof_requirements": [
            "Provide a transition annex and sample quality-control report."
        ],
        "pricing_posture": [
            "Do not underprice transition overhead or reporting cadence."
        ],
        "risk_implications": [
            "Funding remains thin and should stay a stated gap."
        ],
        "evaluator_anxiety_rows": [
            {
                "category": "transition",
                "text": "Transition sequencing looks operationally critical.",
                "evidence_anchor": "PWS transition section",
                "confidence": "high",
            }
        ],
        "reasoned_pain_point_rows": [
            {
                "category": "transition",
                "text": "Transition sequencing looks operationally critical.",
                "evidence_anchor": "PWS transition section",
                "confidence": "high",
            }
        ],
        "reasoned_win_theme_rows": [
            {
                "category": "transition",
                "text": "Lead with a named transition operating rhythm.",
                "evidence_anchor": "PWS transition section",
                "confidence": "high",
            }
        ],
        "reasoned_differentiator_rows": [
            {
                "category": "quality_acceptance",
                "text": "Show an artifact-backed quality-control loop.",
                "evidence_anchor": "QCP requirement",
                "confidence": "medium",
            }
        ],
        "proof_requirement_rows": [
            {
                "category": "transition",
                "text": "Provide a transition annex.",
                "evidence_anchor": "PWS transition section",
                "confidence": "high",
            }
        ],
    }
    with patch.object(reasoning, "_call_openai_json", return_value=capture_model_result):
        capture_reasoned = reasoning.assess_capture_strategy(
            vendor_profile={},
            resolved={"title": "Independent testing support", "buyer": "VA"},
            solicitation_facts={},
            solicitation_fact_model={},
            attachment_workstreams=[],
            evaluator_anxiety_model={},
            public_research={},
            normalized_evidence={},
        )
    if capture_reasoned.get("reasoning_source") != "openai_model":
        failures.append("capture_strategy_model_source")
    if capture_reasoned.get("model_name") != "capture-reasoning-test-model":
        failures.append("capture_strategy_model_name")
    if capture_reasoned.get("reasoned_win_themes") != ["Show exactly how transition and testing cadence will operate in the first 30 days."]:
        failures.append("capture_strategy_model_win_themes")
    if not capture_reasoned.get("proof_requirement_rows"):
        failures.append("capture_strategy_model_rows")

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
