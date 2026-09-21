from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


from capture import capture_decision as decision  # noqa: E402


def _base_inputs() -> dict[str, object]:
    return {
        "customer_priorities": {"evidence_backed_priorities": [], "likely_priorities": []},
        "capability_fit": {"capability_hits": ["outage response"], "past_performance_hits": ["site reporting"]},
        "partner_analysis": {"best_partner_candidates": [], "partner_outreach_action_items": []},
        "contract_type": "Firm Fixed Price",
        "incumbent_analysis": {"strength_signals": []},
        "policy_signals": [],
        "solicitation_facts": {
            "quoted_facts": [
                "Contract type: Firm Fixed Price",
                "Evaluation basis: Best Value",
            ],
            "staffing_roles": ["Site supervisor"],
        },
        "attachment_workstreams": [
            {
                "title": "Runway outage response",
                "objective": "Inspect runway lighting circuits and restore outages within four hours.",
                "evidence_snippets": [
                    "PWS 1.3 Scope: The contractor shall inspect runway lighting circuits, isolate faults, and restore outages within four hours of notification.",
                    "PWS 1.5 General Requirements: The contractor shall maintain field communications and provide daily status reports during outages and weather events.",
                ],
            }
        ],
        "staffing_pricing_signals": {
            "staffing_notes": [],
            "pricing_notes": ["Contract posture is Firm Fixed Price."],
            "evaluation_notes": ["Evaluation basis surfaced in the solicitation package: Best Value."],
        },
        "attachment_anomalies": [],
        "solicitation_fact_model": {
            "package_strength": {"attachment_native_ready": True},
            "workstream_fact_rows": [
                {
                    "text": "Restore outages within four hours of notification.",
                    "evidence_anchor": "PWS 1.3 Scope: The contractor shall inspect runway lighting circuits, isolate faults, and restore outages within four hours of notification.",
                    "confidence": "high",
                }
            ],
            "access_fact_rows": [
                {
                    "text": "Maintain field communications and provide daily status reports during outages and weather events.",
                    "evidence_anchor": "PWS 1.5 General Requirements: The contractor shall maintain field communications and provide daily status reports during outages and weather events.",
                    "confidence": "high",
                }
            ],
        },
    }


def main() -> int:
    failures: list[str] = []

    primary_case = _base_inputs()
    primary_case["strategic_reasoning"] = {
        "reasoned_hot_button_rows": [
            {
                "category": "reporting_governance",
                "text": "Daily outage reporting cadence is a visible evaluator concern.",
                "evidence_anchor": "PWS 1.5 General Requirements: The contractor shall maintain field communications and provide daily status reports during outages and weather events.",
                "confidence": "high",
            }
        ],
        "reasoned_win_theme_rows": [
            {
                "category": "technical_execution",
                "text": "Lead with a four-hour outage restoration plan and daily reporting rhythm.",
                "evidence_anchor": "PWS 1.3 Scope: The contractor shall inspect runway lighting circuits, isolate faults, and restore outages within four hours of notification.",
                "confidence": "high",
            }
        ],
        "reasoned_pain_points": [
            "Daily outage reporting cadence is a visible evaluator concern."
        ],
        "reasoned_win_themes": [
            "Lead with a four-hour outage restoration plan and daily reporting rhythm."
        ],
        "reasoned_differentiators": [],
        "proof_requirements": [],
        "risk_implications": [],
    }
    primary_result = decision._win_strategy(
        primary_case["customer_priorities"],
        primary_case["capability_fit"],
        primary_case["partner_analysis"],
        str(primary_case["contract_type"]),
        primary_case["incumbent_analysis"],
        list(primary_case["policy_signals"]),
        primary_case["solicitation_facts"],
        list(primary_case["attachment_workstreams"]),
        primary_case["staffing_pricing_signals"],
        list(primary_case["attachment_anomalies"]),
        primary_case["strategic_reasoning"],
        primary_case["solicitation_fact_model"],
    )
    primary_hot_buttons = primary_result.get("hot_buttons", [])
    primary_win_themes = primary_result.get("win_themes", [])
    if not primary_hot_buttons or "outage" not in " ".join(primary_hot_buttons[:2]).lower():
        failures.append("primary_hot_buttons_missing_scope_signal")
    if not primary_win_themes or ("outage" not in primary_win_themes[0].lower() and "restore" not in primary_win_themes[0].lower()):
        failures.append("primary_win_themes_missing_scope_signal")
    if any("the contractor shall" in item.lower() for item in primary_hot_buttons + primary_win_themes):
        failures.append("raw_clause_survived_primary_reasoning_case")

    scope_priority_case = _base_inputs()
    scope_priority_case["strategic_reasoning"] = {
        "reasoned_hot_button_rows": [
            {
                "category": "access_readiness",
                "text": "Daily reporting and field communications are visible evaluator concerns.",
                "evidence_anchor": "PWS 1.5 General Requirements: The contractor shall maintain field communications and provide daily status reports during outages and weather events.",
                "confidence": "high",
            }
        ],
        "reasoned_win_theme_rows": [
            {
                "category": "reporting_governance",
                "text": "Show the reporting cadence and field-communications rhythm from day one.",
                "evidence_anchor": "PWS 1.5 General Requirements: The contractor shall maintain field communications and provide daily status reports during outages and weather events.",
                "confidence": "high",
            }
        ],
        "reasoned_pain_points": [
            "Daily reporting and field communications are visible evaluator concerns."
        ],
        "reasoned_win_themes": [
            "Show the reporting cadence and field-communications rhythm from day one."
        ],
        "reasoned_differentiators": [],
        "proof_requirements": [],
        "risk_implications": [],
    }
    # Ranking must choose among model-supplied rows, never invent a scope row.
    scope_priority_case["strategic_reasoning"]["reasoned_hot_button_rows"].append({
        "category": "technical_execution", "text": "Restoring runway outages within four hours is the primary delivery risk.",
        "evidence_anchor": "PWS 1.3 Scope: The contractor shall inspect runway lighting circuits, isolate faults, and restore outages within four hours of notification.", "confidence": "high",
    })
    scope_priority_case["strategic_reasoning"]["reasoned_win_theme_rows"].append({
        "category": "technical_execution", "text": "Lead with a four-hour outage restoration plan backed by field technicians.",
        "evidence_anchor": "PWS 1.3 Scope: The contractor shall inspect runway lighting circuits, isolate faults, and restore outages within four hours of notification.", "confidence": "high",
    })
    scope_priority_result = decision._win_strategy(
        scope_priority_case["customer_priorities"],
        scope_priority_case["capability_fit"],
        scope_priority_case["partner_analysis"],
        str(scope_priority_case["contract_type"]),
        scope_priority_case["incumbent_analysis"],
        list(scope_priority_case["policy_signals"]),
        scope_priority_case["solicitation_facts"],
        list(scope_priority_case["attachment_workstreams"]),
        scope_priority_case["staffing_pricing_signals"],
        list(scope_priority_case["attachment_anomalies"]),
        scope_priority_case["strategic_reasoning"],
        scope_priority_case["solicitation_fact_model"],
    )
    scope_priority_hot_buttons = scope_priority_result.get("hot_buttons", [])
    scope_priority_win_themes = scope_priority_result.get("win_themes", [])
    if not scope_priority_hot_buttons or "outage" not in scope_priority_hot_buttons[0].lower():
        failures.append("scope_hot_button_not_ranked_ahead_of_control_row")
    if not scope_priority_win_themes or ("outage" not in scope_priority_win_themes[0].lower() and "restore" not in scope_priority_win_themes[0].lower()):
        failures.append("scope_win_theme_not_ranked_ahead_of_control_row")

    fallback_case = _base_inputs()
    fallback_case["strategic_reasoning"] = {
        "reasoned_hot_button_rows": [],
        "reasoned_win_theme_rows": [],
        "reasoned_pain_points": [],
        "reasoned_win_themes": [],
        "reasoned_differentiators": [],
        "proof_requirements": [],
        "risk_implications": [],
    }
    fallback_result = decision._win_strategy(
        fallback_case["customer_priorities"],
        fallback_case["capability_fit"],
        fallback_case["partner_analysis"],
        str(fallback_case["contract_type"]),
        fallback_case["incumbent_analysis"],
        list(fallback_case["policy_signals"]),
        fallback_case["solicitation_facts"],
        list(fallback_case["attachment_workstreams"]),
        fallback_case["staffing_pricing_signals"],
        list(fallback_case["attachment_anomalies"]),
        fallback_case["strategic_reasoning"],
        fallback_case["solicitation_fact_model"],
    )
    if fallback_result.get("hot_buttons") != [decision.NO_HOT_BUTTON_EVIDENCE]:
        failures.append("missing_reasoning_hot_button_should_fallback_explicitly")
    if fallback_result.get("win_themes") != [decision.NO_WIN_THEME_EVIDENCE]:
        failures.append("missing_reasoning_win_theme_should_fallback_explicitly")

    print(
        json.dumps(
            {
                "status": "OK" if not failures else "FAIL",
                "failures": failures,
                "primary_hot_buttons": primary_hot_buttons,
                "primary_win_themes": primary_win_themes,
                "scope_priority_hot_buttons": scope_priority_hot_buttons,
                "scope_priority_win_themes": scope_priority_win_themes,
                "fallback_hot_buttons": fallback_result.get("hot_buttons", []),
                "fallback_win_themes": fallback_result.get("win_themes", []),
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
