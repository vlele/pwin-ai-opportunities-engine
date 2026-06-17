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

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
