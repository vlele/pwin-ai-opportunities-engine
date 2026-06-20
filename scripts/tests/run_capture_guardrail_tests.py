from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import capture.capture_decision as capture_decision  # type: ignore
import capture.run_capture_research as capture_run  # type: ignore
from common.paths import utc_now_iso  # type: ignore


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "capture_guardrail_cases.json"


def _load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _lower_lines(values: list[str]) -> str:
    return " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())


def _contains_phrase(values: list[str], phrase: str) -> bool:
    return phrase.lower() in _lower_lines(values)


def _check_lexical_contamination(payload: dict[str, object]) -> list[str]:
    failures: list[str] = []
    files = [SCRIPT_ROOT / str(path) for path in payload.get("core_reasoning_files", [])]
    terms = [str(term).strip().lower() for term in payload.get("lexical_contamination_terms", []) if str(term).strip()]
    for file_path in files:
        text = file_path.read_text(encoding="utf-8").lower()
        for term in terms:
            if term and term in text:
                failures.append(f"contamination:{file_path.name}:{term}")
    return failures


def _evaluate_case(case: dict[str, object]) -> dict[str, object]:
    result = capture_decision._win_strategy(
        case.get("customer_priorities", {}),
        case.get("capability_fit", {}),
        case.get("partner_analysis", {}),
        str(case.get("contract_type", "") or ""),
        case.get("incumbent_analysis", {}),
        list(case.get("policy_signals", []) or []),
        case.get("solicitation_facts", {}),
        list(case.get("attachment_workstreams", []) or []),
        case.get("staffing_pricing_signals", {}),
        list(case.get("attachment_anomalies", []) or []),
        case.get("strategic_reasoning", {}),
    )
    failures: list[str] = []
    expectation = str(case.get("expectation", "") or "")
    win_theme_rows = result.get("win_theme_rows", [])
    hot_button_rows = result.get("hot_button_rows", [])
    win_themes = result.get("win_themes", [])
    hot_buttons = result.get("hot_buttons", [])

    if expectation == "anchored":
        if result.get("strategy_evidence_strength") != "strong":
            failures.append("expected_strong_evidence")
        if not isinstance(win_theme_rows, list) or not win_theme_rows:
            failures.append("missing_win_theme_rows")
        elif any(not isinstance(row, dict) or not str(row.get("evidence_anchor", "") or "").strip() for row in win_theme_rows):
            failures.append("unanchored_win_theme_row")
        if not isinstance(hot_button_rows, list) or not hot_button_rows:
            failures.append("missing_hot_button_rows")
        elif any(not isinstance(row, dict) or not str(row.get("evidence_anchor", "") or "").strip() for row in hot_button_rows):
            failures.append("unanchored_hot_button_row")
        if win_themes == [capture_decision.NO_WIN_THEME_EVIDENCE]:
            failures.append("unexpected_win_theme_fallback")
        for phrase in case.get("expected_present_phrases", []) or []:
            if not _contains_phrase(win_themes + hot_buttons, str(phrase)):
                failures.append(f"missing_phrase:{phrase}")
    elif expectation == "thin":
        if result.get("strategy_evidence_strength") != "thin":
            failures.append("expected_thin_evidence")
        if win_themes != [capture_decision.NO_WIN_THEME_EVIDENCE]:
            failures.append("missing_thin_win_theme_fallback")
        if hot_buttons != [capture_decision.NO_HOT_BUTTON_EVIDENCE]:
            failures.append("missing_thin_hot_button_fallback")
        if any(
            isinstance(row, dict) and str(row.get("evidence_anchor", "") or "").strip()
            for row in (win_theme_rows if isinstance(win_theme_rows, list) else [])
        ):
            failures.append("unexpected_anchor_on_thin_case")

    for phrase in case.get("expected_absent_phrases", []) or []:
        if _contains_phrase(win_themes + hot_buttons, str(phrase)):
            failures.append(f"unexpected_phrase:{phrase}")

    attachment_bundle = {"attachments": [{"category": "statement_of_work"}]} if case.get("attachment_workstreams") else {"attachments": []}
    warnings = capture_run._generic_strategy_language_warnings(
        {"win_strategy": result},
        case.get("solicitation_facts", {}),
        list(case.get("attachment_workstreams", []) or []),
        attachment_bundle,
    )
    if expectation == "anchored" and warnings:
        failures.append("unexpected_generic_strategy_warning")
    if expectation == "thin" and warnings:
        failures.append("thin_case_should_be_explicit_not_generic")

    return {
        "id": case.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "strategy_evidence_strength": result.get("strategy_evidence_strength"),
        "section_anchor_count": result.get("section_anchor_count"),
        "fact_anchor_count": result.get("fact_anchor_count"),
        "win_themes": win_themes,
        "hot_buttons": hot_buttons,
        "generic_strategy_warnings": warnings,
    }


def _evaluate_generic_strategy_control(control: dict[str, object]) -> dict[str, object]:
    warnings = capture_run._generic_strategy_language_warnings(
        control.get("decision_sections", {}),
        control.get("solicitation_facts", {}),
        list(control.get("attachment_workstreams", []) or []),
        control.get("attachment_bundle", {}),
    )
    failures = [] if warnings else ["generic_strategy_warning_missing"]
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "warnings": warnings,
    }


def main() -> int:
    payload = _load_fixture()
    failures = _check_lexical_contamination(payload)
    case_results = [_evaluate_case(case) for case in payload.get("cases", [])]
    control_results = [
        _evaluate_generic_strategy_control(control)
        for control in payload.get("generic_strategy_controls", [])
    ]
    failures.extend(result["id"] for result in case_results if not result["passed"])
    failures.extend(result["id"] for result in control_results if not result["passed"])
    output = {
        "status": "OK" if not failures else "FAILED",
        "generated_at": utc_now_iso(),
        "failed_checks": failures,
        "case_results": case_results,
        "control_results": control_results,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
