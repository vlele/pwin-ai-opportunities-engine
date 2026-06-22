from __future__ import annotations

from typing import Any


def _clean(value: object, *, max_chars: int = 280) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:max_chars].strip(" .;:-")


def _dedupe_strings(values: list[str], *, max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = _clean(value, max_chars=420)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if max_items is not None and len(output) >= max_items:
            break
    return output


def _string_list(value: object, *, max_items: int = 8) -> list[str]:
    if isinstance(value, list):
        return _dedupe_strings([str(item) for item in value if str(item or "").strip()], max_items=max_items)
    if isinstance(value, tuple):
        return _dedupe_strings([str(item) for item in value if str(item or "").strip()], max_items=max_items)
    text = _clean(value, max_chars=420)
    return [text] if text else []


def _first_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            return row
    return None


def _row(category: str, text: str, anchor: str, *, confidence: str = "high") -> dict[str, str]:
    return {
        "category": category,
        "text": _clean(text, max_chars=260),
        "evidence_anchor": _clean(anchor, max_chars=420),
        "confidence": confidence,
    }


def _fact_rows(model: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = model.get(key, []) if isinstance(model, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def build_evaluator_anxiety_model(
    solicitation_fact_model: dict[str, Any] | None,
    *,
    solicitation_facts: dict[str, Any] | None = None,
    attachment_anomalies: list[dict[str, Any]] | None = None,
    contract_type: str = "",
    award_basis: str = "",
) -> dict[str, Any]:
    solicitation_fact_model = solicitation_fact_model if isinstance(solicitation_fact_model, dict) else {}
    solicitation_facts = solicitation_facts if isinstance(solicitation_facts, dict) else {}
    attachment_anomalies = attachment_anomalies if isinstance(attachment_anomalies, list) else []

    workstream_rows = _fact_rows(solicitation_fact_model, "workstream_fact_rows")
    deliverable_rows = _fact_rows(solicitation_fact_model, "deliverable_fact_rows")
    pricing_rows = _fact_rows(solicitation_fact_model, "pricing_fact_rows")
    evaluation_rows = _fact_rows(solicitation_fact_model, "evaluation_fact_rows")
    acceptance_rows = _fact_rows(solicitation_fact_model, "acceptance_fact_rows")
    access_rows = _fact_rows(solicitation_fact_model, "access_fact_rows")
    staffing_rows = _fact_rows(solicitation_fact_model, "staffing_fact_rows")
    conflict_rows = _fact_rows(solicitation_fact_model, "conflict_rows")

    anxiety_rows: list[dict[str, str]] = []
    win_theme_rows: list[dict[str, str]] = []
    proof_requirement_rows: list[dict[str, str]] = []
    differentiator_rows: list[dict[str, str]] = []
    pain_point_rows: list[dict[str, str]] = []
    risk_implications: list[str] = []
    pricing_posture: list[str] = []

    if row := _first_row(staffing_rows):
        pain_point_rows.append(
            _row(
                "staffing_execution",
                "Visible roles and staffing structure make execution credibility part of the evaluation story, not just an appendix.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "staffing_execution",
                "Name the delivery team and show coverage for the visible labor mix instead of relying on generic surge language.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        proof_requirement_rows.append(
            _row(
                "staffing_execution",
                "Build a staffing matrix tied to the visible roles, shifts, CLINs, or task structure in the package.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(access_rows):
        anxiety_rows.append(
            _row(
                "access_readiness",
                "Access, onboarding, or information-handling steps can break day-one execution if they are treated as back-office details.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "access_readiness",
                "Make startup readiness explicit for access, credentialing, and controlled-information handling.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        differentiator_rows.append(
            _row(
                "access_readiness",
                "Documented startup controls for access, credentialing, and information handling can separate a safe execution story from a generic one.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(deliverable_rows):
        anxiety_rows.append(
            _row(
                "deliverable_throughput",
                "The package appears to care about deliverable throughput and review quality, not just labor availability.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "deliverable_throughput",
                "Show how scoped deliverables, submissions, or review packages move through approval without rework.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        proof_requirement_rows.append(
            _row(
                "deliverable_throughput",
                "Produce one proof artifact that mirrors the package's visible deliverable structure, cadence, or review path.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(acceptance_rows):
        anxiety_rows.append(
            _row(
                "acceptance_quality",
                "Acceptance, surveillance, or remedy terms mean quality escapes are likely to be visible and costly.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "acceptance_quality",
                "Tie the execution approach to the stated acceptance, surveillance, or corrective-action structure.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        differentiator_rows.append(
            _row(
                "acceptance_quality",
                "A proposal that translates acceptance and remedy structure into an operating control loop will look lower-risk.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(pricing_rows):
        anxiety_rows.append(
            _row(
                "pricing_realism",
                "Visible CLIN, pricing, or rate structure raises evaluator concern about math, scope coverage, and buy-in risk.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "pricing_realism",
                "Make the pricing posture look executable against the visible CLIN, coverage, and reporting demands.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        proof_requirement_rows.append(
            _row(
                "pricing_realism",
                "Validate CLIN math, assumptions, and optionality directly from the extracted pricing structure before final pricing locks.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        pricing_posture.append("The attachment package exposes pricing or CLIN structure, so PTW needs to align to visible package math rather than generic rate assumptions.")

    if row := _first_row(evaluation_rows):
        anxiety_rows.append(
            _row(
                "evaluation_basis",
                "The package names evaluation structure directly enough that generic proposal prose will be easy to penalize.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        win_theme_rows.append(
            _row(
                "evaluation_basis",
                "Map proof directly to the named evaluation basis and visible factors instead of relying on broad corporate claims.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(workstream_rows):
        pain_point_rows.append(
            _row(
                "workstream_execution",
                "The scope reads like real execution workstreams with visible outputs, dependencies, or review gates.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )
        differentiator_rows.append(
            _row(
                "workstream_execution",
                "A proposal that shows how the team executes the surfaced workstreams from day one will read more credibly than a labor-only story.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
            )
        )

    if row := _first_row(conflict_rows):
        risk_implications.append(
            "Cross-document conflicts or parse warnings remain in the package, so proposal assumptions should be locked to the most recent explicit source and flagged for formal clarification."
        )
        proof_requirement_rows.append(
            _row(
                "document_conflict",
                "Build a short assumptions register for any attachment conflict, parse warning, or contradictory instruction that could distort pricing or compliance.",
                str(row.get("evidence_anchor") or row.get("text") or ""),
                confidence="medium",
            )
        )

    if str(solicitation_facts.get("funds_status") or "").strip():
        risk_implications.append("Funding caveats in the package should be treated as timing risk, not positive funding evidence.")
    if contract_type:
        pricing_posture.append(f"Visible contract type signal: {contract_type}.")
    if award_basis:
        pricing_posture.append(f"Visible evaluation basis signal: {award_basis}.")
    for item in attachment_anomalies:
        if not isinstance(item, dict):
            continue
        signal = _clean(item.get("signal"), max_chars=220)
        if not signal:
            continue
        risk_implications.append(signal)

    summary_lines = _dedupe_strings(
        [row.get("text", "") for row in anxiety_rows[:2] + pain_point_rows[:2]]
        + pricing_posture[:1]
        + risk_implications[:1],
        max_items=4,
    )
    reasoning_summary = (
        " ".join(summary_lines)
        if summary_lines
        else "Attachment-native evidence is too thin to infer evaluator anxieties beyond the extracted solicitation facts."
    )
    central_pain_point = (
        summary_lines[0]
        if summary_lines
        else "Current package evidence is too thin to infer a single dominant evaluator anxiety."
    )

    return {
        "central_pain_point": central_pain_point,
        "reasoning_summary": reasoning_summary,
        "evaluator_anxiety_rows": anxiety_rows,
        "reasoned_pain_point_rows": pain_point_rows,
        "reasoned_win_theme_rows": win_theme_rows,
        "reasoned_differentiator_rows": differentiator_rows,
        "proof_requirement_rows": proof_requirement_rows,
        "reasoned_pain_points": _dedupe_strings([row.get("text", "") for row in anxiety_rows + pain_point_rows], max_items=8),
        "reasoned_win_themes": _dedupe_strings([row.get("text", "") for row in win_theme_rows], max_items=8),
        "reasoned_differentiators": _dedupe_strings([row.get("text", "") for row in differentiator_rows], max_items=8),
        "proof_requirements": _dedupe_strings([row.get("text", "") for row in proof_requirement_rows], max_items=8),
        "pricing_posture": _dedupe_strings(pricing_posture, max_items=6),
        "risk_implications": _dedupe_strings(risk_implications, max_items=6),
    }
