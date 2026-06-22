from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import capture.capture_decision as capture_decision  # type: ignore
import capture.fetch_public_context as fetch_public  # type: ignore
import capture.render_capture_brief as capture_render  # type: ignore
import capture.run_capture_research as capture_run  # type: ignore
import capture.usaspending_enrich as usaspending_enrich  # type: ignore
import common.evidence_model as evidence_model  # type: ignore
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
    proof_artifacts = result.get("proof_artifact_recommendations", [])

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
        expected_artifact_phrase = str(case.get("expected_artifact_phrase", "") or "").strip()
        if expected_artifact_phrase and not _contains_phrase(proof_artifacts if isinstance(proof_artifacts, list) else [], expected_artifact_phrase):
            failures.append(f"missing_artifact_phrase:{expected_artifact_phrase}")
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
        "proof_artifacts": proof_artifacts,
        "generic_strategy_warnings": warnings,
    }


def _evaluate_objective_compaction_control(control: dict[str, object]) -> dict[str, object]:
    attachment_bundle = control.get("attachment_bundle", {})
    normalized_bundle = attachment_bundle if isinstance(attachment_bundle, dict) else {}
    objectives = capture_run._decompose_objectives(
        str(control.get("title", "") or ""),
        str(control.get("summary", "") or ""),
        str(control.get("explanation_summary", "") or ""),
        normalized_bundle,
    )
    workstreams = capture_run._extract_attachment_workstreams(normalized_bundle)
    rendered_lines = [
        str(item.get("objective", "") or "").strip()
        for item in workstreams
        if isinstance(item, dict) and str(item.get("objective", "") or "").strip()
    ] + [str(item or "").strip() for item in objectives if str(item or "").strip()]
    failures: list[str] = []
    max_objective_chars = int(control.get("max_objective_chars", 0) or 0)
    if max_objective_chars and any(len(line) > max_objective_chars for line in rendered_lines):
        failures.append("objective_not_compacted")
    combined = _lower_lines(rendered_lines)
    for phrase in control.get("expected_objective_phrases", []) or []:
        if str(phrase).lower() not in combined:
            failures.append(f"missing_objective_phrase:{phrase}")
    for phrase in control.get("forbidden_objective_phrases", []) or []:
        if str(phrase).lower() in combined:
            failures.append(f"unexpected_objective_phrase:{phrase}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "workstreams": workstreams,
        "objectives": objectives,
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


def _evaluate_usefulness_control(control: dict[str, object]) -> dict[str, object]:
    result = capture_run._capture_usefulness_assessment(
        control.get("public_research_assessment", {}),
        control.get("objective_validation_summary", {}),
        control.get("attachment_parse_guardrails", {}),
    )
    expected_useful = bool(control.get("expected_useful"))
    failures: list[str] = []
    if bool(result.get("useful")) != expected_useful:
        failures.append("unexpected_usefulness")
    if not expected_useful and not str(result.get("release_warning") or "").strip():
        failures.append("missing_usefulness_warning")
    if expected_useful and str(result.get("release_warning") or "").strip():
        failures.append("unexpected_usefulness_warning")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "result": result,
    }


def _evaluate_vendor_fit_control(control: dict[str, object]) -> dict[str, object]:
    result = capture_decision._capability_fit(
        control.get("profile", {}),
        str(control.get("buyer", "") or ""),
        control.get("opportunity", {}),
        str(control.get("notice_text", "") or ""),
        control.get("customer_priorities", {}),
        control.get("solicitation_facts", {}),
        list(control.get("vehicle_access_paths", []) or []),
        str(control.get("set_aside_text", "") or ""),
        bool(control.get("vehicle_access_ok", False)),
        bool(control.get("vehicle_access_required", False)),
        bool(control.get("set_aside_access_ok", True)),
        control.get("qualification_gaps", {}),
    )
    failures: list[str] = []
    adjustment_total = sum(
        int(result.get(key, 0) or 0)
        for key in (
            "customer_alignment_adjustment",
            "requirement_fit_adjustment",
            "past_performance_adjustment",
            "vehicle_access_adjustment",
        )
    )
    expected_direction = str(control.get("expected_adjustment_direction", "") or "").strip()
    if expected_direction == "positive" and adjustment_total <= 0:
        failures.append("expected_positive_adjustment")
    if expected_direction == "negative" and adjustment_total >= 0:
        failures.append("expected_negative_adjustment")
    for phrase in control.get("expected_signal_phrases", []) or []:
        if not _contains_phrase(result.get("fit_weighting_signals", []), str(phrase)):
            failures.append(f"missing_signal_phrase:{phrase}")
    for phrase in control.get("expected_caution_phrases", []) or []:
        if not _contains_phrase(result.get("fit_weighting_cautions", []), str(phrase)):
            failures.append(f"missing_caution_phrase:{phrase}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "adjustment_total": adjustment_total,
        "signals": result.get("fit_weighting_signals", []),
        "cautions": result.get("fit_weighting_cautions", []),
    }


def _evaluate_stakeholder_control(control: dict[str, object]) -> dict[str, object]:
    rows = capture_decision._stakeholder_analysis(
        str(control.get("buyer", "") or ""),
        list(control.get("stakeholder_contacts", []) or []),
        control.get("opportunity", {}),
        control.get("public_research", {}),
    )
    rendered = capture_render._stakeholder_rows(rows)
    failures: list[str] = []
    expected_history_phrase = str(control.get("expected_history_phrase", "") or "").strip()
    if expected_history_phrase and expected_history_phrase.lower() not in rendered.lower():
        failures.append("missing_history_phrase")
    if "Public History / Signals" not in rendered:
        failures.append("missing_history_column")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "rows": rows,
    }


def _evaluate_public_research_control(control: dict[str, object]) -> dict[str, object]:
    buyer = str(control.get("buyer", "") or "")
    title = str(control.get("title", "") or "")
    notice_text = str(control.get("notice_text", "") or "")
    labels = fetch_public._agency_labels(buyer)
    domains = fetch_public._category_allowed_domains(
        "mission_context",
        list(control.get("domains", []) or []),
        buyer,
        [],
    )
    label_tokens = [
        token
        for token in fetch_public._dedupe_strings(fetch_public._signal_tokens(*labels) + fetch_public._label_acronyms(labels, domains))
        if token not in fetch_public.GENERIC_ENTITY_TOKENS
    ]
    keywords = fetch_public._top_keywords(title, notice_text)
    priority_keywords = fetch_public._top_keywords(title, notice_text, limit=5)
    _, mission_text_hints = fetch_public._category_hints("mission_context", labels, keywords, [])
    _, discourse_text_hints = fetch_public._category_hints("public_discourse", labels, keywords, [])
    failures: list[str] = []

    for expected in control.get("expected_labels", []) or []:
        if str(expected) not in labels:
            failures.append(f"missing_label:{expected}")
    for excluded_domain in control.get("excluded_domains", []) or []:
        if str(excluded_domain) in domains:
            failures.append(f"excluded_domain_present:{excluded_domain}")
    for excluded_keyword in control.get("excluded_priority_keywords", []) or []:
        if str(excluded_keyword) in priority_keywords:
            failures.append(f"excluded_priority_keyword_present:{excluded_keyword}")
    for expected_keyword in control.get("expected_priority_keywords", []) or []:
        if str(expected_keyword) not in priority_keywords:
            failures.append(f"missing_priority_keyword:{expected_keyword}")

    career_url = str(control.get("career_url", "") or "")
    career_title = str(control.get("career_title", "") or "")
    career_excerpt = str(control.get("career_excerpt", "") or "")
    discourse_metrics = fetch_public._source_quality_score(
        "public_discourse",
        career_url,
        career_title,
        career_excerpt,
        domains,
        [],
        discourse_text_hints,
        label_tokens,
        priority_keywords,
        keywords,
        [],
    )
    mission_metrics = fetch_public._source_quality_score(
        "mission_context",
        career_url,
        career_title,
        career_excerpt,
        domains,
        [],
        mission_text_hints,
        label_tokens,
        priority_keywords,
        keywords,
        [],
    )
    if int(discourse_metrics.get("quality_score", 0) or 0) >= 0:
        failures.append("career_page_not_rejected_for_public_discourse")
    if int(mission_metrics.get("quality_score", 0) or 0) >= 0:
        failures.append("career_page_not_rejected_for_mission_context")

    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "labels": labels,
        "domains": domains,
        "discourse_metrics": discourse_metrics,
        "mission_metrics": mission_metrics,
        "priority_keywords": priority_keywords,
    }


def _evaluate_competitive_control(control: dict[str, object]) -> dict[str, object]:
    model = evidence_model.build_capture_official_evidence_model(
        resolved=control.get("resolved", {}),
        opportunity=control.get("opportunity", {}),
        award_signals=control.get("award_signals", {}),
        attachment_validation=control.get("attachment_validation", {}),
        attachment_bundle=control.get("attachment_bundle", {}),
        vehicle_signals=list(control.get("vehicle_signals", []) or []),
        notice_context_text=str(control.get("notice_context_text", "") or ""),
    )
    candidates = evidence_model.evidence_model_competitor_candidates(model, max_items=8)
    names = [str(item.get("name", "") or "").strip() for item in candidates if isinstance(item, dict)]
    failures: list[str] = []
    for expected_name in control.get("expected_names", []) or []:
        if str(expected_name) not in names:
            failures.append(f"missing_competitor:{expected_name}")
    for unexpected_name in control.get("unexpected_names", []) or []:
        if str(unexpected_name) in names:
            failures.append(f"unexpected_competitor:{unexpected_name}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "competitors": candidates,
    }


def _evaluate_agency_catalog_control(control: dict[str, object]) -> dict[str, object]:
    runtime_path = SCRIPT_ROOT / str(control.get("runtime_file", "") or "")
    catalog_path = SCRIPT_ROOT / str(control.get("catalog_file", "") or "")
    runtime_text = runtime_path.read_text(encoding="utf-8").lower()
    catalog_text = catalog_path.read_text(encoding="utf-8").lower()
    failures: list[str] = []
    for text in control.get("forbidden_runtime_literals", []) or []:
        needle = str(text or "").strip().lower()
        if needle and needle in runtime_text:
            failures.append(f"runtime_contains:{text}")
    for text in control.get("required_catalog_literals", []) or []:
        needle = str(text or "").strip().lower()
        if needle and needle not in catalog_text:
            failures.append(f"catalog_missing:{text}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
    }


def _evaluate_priority_rendering_control(control: dict[str, object]) -> dict[str, object]:
    result = capture_decision._apply_priority_evidence_gate(
        control.get("customer_priorities", {}),
        control.get("public_research", {}),
        list(control.get("workstream_lines", []) or []),
    )
    failures: list[str] = []
    expected_mode = str(control.get("expected_mode", "") or "").strip()
    if expected_mode and str(result.get("priority_rendering_mode", "") or "").strip() != expected_mode:
        failures.append("unexpected_priority_mode")
    warning_contains = str(control.get("warning_contains", "") or "").strip().lower()
    if warning_contains and warning_contains not in str(result.get("priority_rendering_warning", "") or "").lower():
        failures.append("missing_priority_warning")
    combined_lines = _lower_lines(
        list(result.get("evidence_backed_priorities", []) or [])
        + list(result.get("likely_priorities", []) or [])
        + list(result.get("pain_points", []) or [])
    )
    for phrase in control.get("expected_present_phrases", []) or []:
        if str(phrase).lower() not in combined_lines:
            failures.append(f"missing_phrase:{phrase}")
    for phrase in control.get("expected_absent_phrases", []) or []:
        if str(phrase).lower() in combined_lines:
            failures.append(f"unexpected_phrase:{phrase}")
    if int(control.get("max_evidence_backed_count", 0) or 0):
        if len(list(result.get("evidence_backed_priorities", []) or [])) > int(control.get("max_evidence_backed_count", 0) or 0):
            failures.append("evidence_backed_not_trimmed")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "result": result,
    }


def _evaluate_requirement_specific_control(control: dict[str, object]) -> dict[str, object]:
    result = capture_decision._requirement_specific_insights(str(control.get("text", "") or ""))
    combined = _lower_lines(
        [str(result.get("mission_problem", "") or "")]
        + list(result.get("priorities", []))
        + list(result.get("pain_points", []))
        + list(result.get("win_themes", []))
        + list(result.get("differentiators", []))
    )
    failures: list[str] = []
    for phrase in control.get("expected_present_phrases", []) or []:
        if str(phrase).lower() not in combined:
            failures.append(f"missing_phrase:{phrase}")
    for phrase in control.get("expected_absent_phrases", []) or []:
        if str(phrase).lower() in combined:
            failures.append(f"unexpected_phrase:{phrase}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "result": result,
    }


def _evaluate_usaspending_control(control: dict[str, object]) -> dict[str, object]:
    search_terms = usaspending_enrich.build_search_terms(
        str(control.get("search_text", "") or ""),
        title=str(control.get("title", "") or ""),
        summary=str(control.get("summary", "") or ""),
        buyer=str(control.get("buyer", "") or ""),
    )
    failures: list[str] = []
    for expected_term in control.get("expected_terms", []) or []:
        if str(expected_term) not in search_terms:
            failures.append(f"missing_term:{expected_term}")
    for excluded_term in control.get("excluded_terms", []) or []:
        if str(excluded_term) in search_terms:
            failures.append(f"unexpected_term:{excluded_term}")
    return {
        "id": control.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "search_terms": search_terms,
    }


def main() -> int:
    payload = _load_fixture()
    failures = _check_lexical_contamination(payload)
    case_results = [_evaluate_case(case) for case in payload.get("cases", [])]
    objective_compaction_results = [
        _evaluate_objective_compaction_control(control)
        for control in payload.get("objective_compaction_controls", [])
    ]
    control_results = [
        _evaluate_generic_strategy_control(control)
        for control in payload.get("generic_strategy_controls", [])
    ]
    usefulness_results = [
        _evaluate_usefulness_control(control)
        for control in payload.get("usefulness_controls", [])
    ]
    vendor_fit_results = [
        _evaluate_vendor_fit_control(control)
        for control in payload.get("vendor_fit_controls", [])
    ]
    stakeholder_results = [
        _evaluate_stakeholder_control(control)
        for control in payload.get("stakeholder_controls", [])
    ]
    public_research_results = [
        _evaluate_public_research_control(control)
        for control in payload.get("public_research_controls", [])
    ]
    competitive_results = [
        _evaluate_competitive_control(control)
        for control in payload.get("competitive_controls", [])
    ]
    agency_catalog_results = [
        _evaluate_agency_catalog_control(control)
        for control in payload.get("agency_catalog_controls", [])
    ]
    priority_rendering_results = [
        _evaluate_priority_rendering_control(control)
        for control in payload.get("priority_rendering_controls", [])
    ]
    requirement_specific_results = [
        _evaluate_requirement_specific_control(control)
        for control in payload.get("requirement_specific_controls", [])
    ]
    usaspending_results = [
        _evaluate_usaspending_control(control)
        for control in payload.get("usaspending_controls", [])
    ]
    failures.extend(result["id"] for result in case_results if not result["passed"])
    failures.extend(result["id"] for result in objective_compaction_results if not result["passed"])
    failures.extend(result["id"] for result in control_results if not result["passed"])
    failures.extend(result["id"] for result in usefulness_results if not result["passed"])
    failures.extend(result["id"] for result in vendor_fit_results if not result["passed"])
    failures.extend(result["id"] for result in stakeholder_results if not result["passed"])
    failures.extend(result["id"] for result in public_research_results if not result["passed"])
    failures.extend(result["id"] for result in competitive_results if not result["passed"])
    failures.extend(result["id"] for result in agency_catalog_results if not result["passed"])
    failures.extend(result["id"] for result in priority_rendering_results if not result["passed"])
    failures.extend(result["id"] for result in requirement_specific_results if not result["passed"])
    failures.extend(result["id"] for result in usaspending_results if not result["passed"])
    output = {
        "status": "OK" if not failures else "FAILED",
        "generated_at": utc_now_iso(),
        "failed_checks": failures,
        "case_results": case_results,
        "objective_compaction_results": objective_compaction_results,
        "control_results": control_results,
        "usefulness_results": usefulness_results,
        "vendor_fit_results": vendor_fit_results,
        "stakeholder_results": stakeholder_results,
        "public_research_results": public_research_results,
        "competitive_results": competitive_results,
        "agency_catalog_results": agency_catalog_results,
        "priority_rendering_results": priority_rendering_results,
        "requirement_specific_results": requirement_specific_results,
        "usaspending_results": usaspending_results,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
