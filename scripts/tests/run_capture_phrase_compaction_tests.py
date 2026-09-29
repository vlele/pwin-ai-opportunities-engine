from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


from capture import capture_decision as decision  # noqa: E402


def main() -> int:
    failures: list[str] = []

    report_focus = decision._repair_requirement_phrase(
        "Deliverables; throughout the performance of this contract shall be provided via electronic submission to: VA Program Manager (PM), Contracting Officer's Representative (COR), and Contracting Officer (CO)"
    )
    report_text = decision._render_win_theme_text("reporting_governance", report_focus)
    if "who owns provide" in report_text.lower():
        failures.append("reporting_governance_literal_phrase")

    transition_focus = decision._repair_requirement_phrase(
        "5001AB Transition-Out Plan IAW PWS Paragraph 5.6 Due/Frequency: 30 days after optional task if exercised"
    )
    transition_text = decision._render_win_theme_text("transition", transition_focus)
    if "can transition-out plan iaw" in transition_text.lower():
        failures.append("transition_literal_phrase")
    if "deliver the transition-out plan" not in transition_text.lower():
        failures.append("transition_plan_not_compacted")

    duplicate_focus = decision._compact_strategy_focus_clauses(
        "support EHRM-IO Integrated Testing & OIT and execute required testing and testing-related activities; execute the following tasks in support of EHRM-IO Integrated Testing & OIT"
    )
    if duplicate_focus.count(";") > 1:
        failures.append("duplicate_clause_not_compacted")

    reporting_focus = decision._compact_strategy_focus_clauses(
        "maintain field communications and provide daily status reports during outages and weather events; Maintain daily operational reporting and weather-event coordination for site continuity"
    )
    if ";" in reporting_focus:
        failures.append("reporting_clause_echo_not_compacted")

    discrepancy_focus = decision._compact_strategy_focus_clauses(
        "submit weekly discrepancy reports, corrective-action status, and inventory accuracy metrics; Provide discrepancy reporting and corrective-action tracking for delayed or compromised shipments"
    )
    discrepancy_text = decision._render_win_theme_text("quality_acceptance", discrepancy_focus)
    if ";" in discrepancy_focus:
        failures.append("discrepancy_clause_echo_not_compacted")
    if "for submit " in discrepancy_text.lower():
        failures.append("quality_acceptance_action_rendering")

    returned_focus = decision._compact_strategy_focus_clauses(
        "Maintain quality-review checkpoints and corrective-action tracking for returned or incomplete appeal packages"
    )
    returned_text = decision._render_win_theme_text("quality_acceptance", returned_focus)
    if "executes maintain" in returned_text.lower():
        failures.append("returned_package_literal_phrase")

    print(
        json.dumps(
            {
                "status": "OK" if not failures else "FAIL",
                "failures": failures,
                "report_text": report_text,
                "transition_text": transition_text,
                "duplicate_focus": duplicate_focus,
                "reporting_focus": reporting_focus,
                "discrepancy_focus": discrepancy_focus,
                "discrepancy_text": discrepancy_text,
                "returned_text": returned_text,
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
