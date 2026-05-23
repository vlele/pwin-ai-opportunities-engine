from __future__ import annotations

from pathlib import Path
from typing import Any

from common.paths import read_text


def _markdown_list(items: list[str], empty: str = "none found") -> str:
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def _objective_matrix_rows(objectives: list[dict[str, Any]]) -> str:
    if not objectives:
        return "| Research objective still being assembled | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
    rows: list[str] = []
    for item in objectives:
        rows.append(
            "| {objective} | {mission_driver} | {policy_driver} | {budget_signal} | {stakeholders} | {incumbents} | {key_risks} | {kpis} | {solution_implications} | {evidence_links} |".format(
                objective=item.get("objective", "N/A"),
                mission_driver=item.get("mission_driver", "N/A"),
                policy_driver=item.get("policy_driver", "N/A"),
                budget_signal=item.get("budget_signal", "N/A"),
                stakeholders=item.get("stakeholders", "N/A"),
                incumbents=item.get("incumbents", "N/A"),
                key_risks=item.get("key_risks", "N/A"),
                kpis=item.get("kpis", "N/A"),
                solution_implications=item.get("solution_implications", "N/A"),
                evidence_links=item.get("evidence_links", "N/A"),
            )
        )
    return "\n".join(rows)


def _source_rows(source_log: list[dict[str, Any]]) -> str:
    if not source_log:
        return "| 1 | No external sources were captured in this run | N/A | N/A | N/A | N/A | N/A | Evidence gap | 0 |"
    rows: list[str] = []
    for index, item in enumerate(source_log, start=1):
        rows.append(
            "| {index} | {title} | {url} | {publisher} | {pub_date} | {accessed} | {tier} | {relevance} | {confidence} |".format(
                index=index,
                title=item.get("title", "N/A"),
                url=item.get("url", "N/A"),
                publisher=item.get("publisher", "N/A"),
                pub_date=item.get("published_date", "N/A"),
                accessed=item.get("accessed_date", "N/A"),
                tier=item.get("tier", "N/A"),
                relevance=item.get("relevance", "N/A"),
                confidence=item.get("confidence", 0),
            )
        )
    return "\n".join(rows)


def _objective_evidence_blocks(objectives: list[dict[str, Any]]) -> str:
    if not objectives:
        return "- No objective-specific source extracts were captured in this run."
    blocks: list[str] = []
    for item in objectives:
        title = item.get("objective", "Objective")
        snippets = item.get("evidence_snippets") or ["No direct snippet captured yet."]
        blocks.append(f"#### {title}\n")
        blocks.extend(f"- {snippet}" for snippet in snippets)
        blocks.append("")
    return "\n".join(blocks).strip()


def render_capture_brief(template_path: Path, evidence: dict[str, Any]) -> str:
    template = read_text(template_path)
    entry = evidence.get("entry", {})
    executive = evidence.get("executive_brief", {})
    objective_summary_lines = executive.get("objective_summaries", []) or [executive.get("summary", "N/A")]
    replacements = {
        "{{VENDOR_NAME}}": evidence.get("vendor_name", "Vendor"),
        "{{REPORT_ENTRY_ID}}": entry.get("report_entry_id", "N/A") or "N/A",
        "{{DIGEST_DATE}}": entry.get("digest_date", "N/A") or "N/A",
        "{{OPPORTUNITY_ID}}": entry.get("opportunity_id", "N/A") or "N/A",
        "{{CANONICAL_RECORD_ID}}": entry.get("canonical_record_id", "N/A") or "N/A",
        "{{CANONICAL_RECORD_ID_TYPE}}": entry.get("canonical_record_id_type", "N/A") or "N/A",
        "{{NOTICE_ID_OR_NA}}": entry.get("notice_id", "N/A") or "N/A",
        "{{REQUEST_ID}}": evidence.get("request_id", "N/A"),
        "{{RESEARCH_STATUS}}": evidence.get("status", "FAILED"),
        "{{PRIMARY_SOURCE}}": entry.get("source_name", "N/A") or "N/A",
        "{{PRIMARY_SOURCE_TIER}}": str(entry.get("source_tier", "N/A")),
        "{{REQUEST_CAPTURE_BRIEF_PATH}}": evidence.get("artifacts", {}).get("request_capture_brief_path", "N/A"),
        "{{REQUEST_CAPTURE_EVIDENCE_PATH}}": evidence.get("artifacts", {}).get("request_capture_evidence_path", "N/A"),
        "{{GENERATED_AT}}": evidence.get("generated_at", "N/A"),
        "{{CURRENT_RESEARCH_LIMITS}}": _markdown_list(evidence.get("evidence_gaps", [])),
        "{{EXECUTIVE_OBJECTIVE_SUMMARIES}}": _markdown_list(objective_summary_lines),
        "{{EXECUTIVE_WHY_NOW}}": _markdown_list(
            [f"Summary: {executive.get('summary', 'N/A')}", f"Capture trigger: {executive.get('why_now', 'N/A')}"]
            + list(executive.get("why_now_signals", []) or [])
        ),
        "{{EXECUTIVE_RISKS_AND_METRICS}}": _markdown_list(
            [f"Risks and constraints: {', '.join(executive.get('risks', [])) or 'N/A'}"]
            + [f"Success metrics: {', '.join(executive.get('success_metrics', [])) or 'N/A'}"]
        ),
        "{{EXECUTIVE_INCUMBENT_POSTURE}}": _markdown_list(executive.get("incumbent_posture", [])),
        "{{EXECUTIVE_WIN_THEMES}}": _markdown_list(
            [f"Win themes: {', '.join(executive.get('win_themes', [])) or 'N/A'}"]
            + [f"Proof points: {', '.join(executive.get('proof_points', [])) or 'N/A'}"]
        ),
        "{{OBJECTIVE_MATRIX_ROWS}}": _objective_matrix_rows(evidence.get("objectives", [])),
        "{{STAKEHOLDER_MAP}}": _markdown_list(evidence.get("stakeholder_map", [])),
        "{{LEADERSHIP_PRIORITY_SIGNALS}}": _markdown_list(evidence.get("leadership_priority_signals", []), empty="currently unavailable"),
        "{{BUDGET_AND_SPENDING_SIGNALS}}": _markdown_list(evidence.get("budget_funding_signals", [])),
        "{{ACQUISITION_FORECAST_SIGNALS}}": _markdown_list(evidence.get("acquisition_forecast_signals", []), empty="currently unavailable"),
        "{{RELATED_PROCUREMENTS_AND_VEHICLES}}": _markdown_list(
            evidence.get("related_procurements", []) + evidence.get("vehicle_signals", [])
        ),
        "{{COMPETITIVE_LANDSCAPE}}": _markdown_list(
            evidence.get("competitive_landscape", {}).get("notes", [])
            + [f"Likely incumbents: {', '.join(evidence.get('competitive_landscape', {}).get('likely_incumbents', [])) or 'none found'}"]
            + [f"Frequent primes: {', '.join(evidence.get('competitive_landscape', {}).get('frequent_primes', [])) or 'none found'}"]
            + [f"Common teammates: {', '.join(evidence.get('competitive_landscape', {}).get('common_teammates', [])) or 'none found'}"]
            + [f"Emerging challengers: {', '.join(evidence.get('competitive_landscape', {}).get('emerging_challengers', [])) or 'none found'}"]
        ),
        "{{MISSION_CONTEXT_SIGNALS}}": _markdown_list(evidence.get("mission_context_signals", []), empty="currently unavailable"),
        "{{POLICY_COMPLIANCE_SIGNALS}}": _markdown_list(evidence.get("policy_compliance_signals", []), empty="currently unavailable"),
        "{{OVERSIGHT_SIGNALS}}": _markdown_list(evidence.get("oversight_signals", []), empty="currently unavailable"),
        "{{PUBLIC_DISCOURSE_AND_MARKET_SIGNALS}}": _markdown_list(evidence.get("public_discourse_signals", [])),
        "{{RECOMMENDED_NEXT_RESEARCH_MOVES}}": _markdown_list(evidence.get("recommended_next_research_moves", [])),
        "{{ACTION_ITEMS}}": _markdown_list(evidence.get("action_items_next_10_days", [])),
        "{{ASSUMPTIONS_TO_VALIDATE}}": _markdown_list(evidence.get("assumptions_to_validate", [])),
        "{{SOURCE_LOG_ROWS}}": _source_rows(evidence.get("source_log", [])),
        "{{OBJECTIVE_EVIDENCE_BLOCKS}}": _objective_evidence_blocks(evidence.get("objectives", [])),
    }

    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered
