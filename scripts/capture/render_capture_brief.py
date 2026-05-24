from __future__ import annotations

from pathlib import Path
from typing import Any

from common.paths import read_text


def _md_cell(value: object) -> str:
    return str(value or "N/A").replace("|", "/").replace("\n", " ").strip() or "N/A"


def _markdown_list(items: list[str], empty: str = "none found") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def _score_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "| Category | Score | Max | Rationale |\n|:---|---:|---:|:---|\n| No score breakdown generated | 0 | 0 | N/A |"
    lines = ["| Category | Score | Max | Rationale |", "|:---|---:|---:|:---|"]
    for row in rows:
        lines.append(
            "| {category} | {score} | {max_score} | {rationale} |".format(
                category=_md_cell(row.get("category")),
                score=_md_cell(row.get("score")),
                max_score=_md_cell(row.get("max")),
                rationale=_md_cell(row.get("rationale")),
            )
        )
    return "\n".join(lines)


def _evidence_ledger_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "| Source Type | Title | Date | Link | What It Proves | Confidence |\n|:---|:---|:---|:---|:---|---:|\n| N/A | No evidence sources captured | N/A | N/A | Evidence gap | 0 |"
    lines = [
        "| Source Type | Title | Date | Link | What It Proves | Confidence |",
        "|:---|:---|:---|:---|:---|---:|",
    ]
    for row in rows:
        link = row.get("link", "N/A")
        link_text = f"[link]({link})" if isinstance(link, str) and link.startswith("http") else _md_cell(link)
        lines.append(
            "| {source_type} | {title} | {date} | {link} | {proves} | {confidence} |".format(
                source_type=_md_cell(row.get("source_type")),
                title=_md_cell(row.get("title")),
                date=_md_cell(row.get("date")),
                link=link_text,
                proves=_md_cell(row.get("what_it_proves")),
                confidence=_md_cell(row.get("confidence")),
            )
        )
    return "\n".join(lines)


def _opportunity_snapshot(snapshot: dict[str, Any]) -> str:
    ordered_keys = [
        ("Opportunity", "title"),
        ("Solicitation Number", "solicitation_number"),
        ("Agency / Bureau / Program", "agency_bureau_program"),
        ("Notice Type", "notice_type"),
        ("NAICS", "naics"),
        ("PSC / Other Taxonomy", "psc"),
        ("Contract Vehicle", "contract_vehicle"),
        ("Contract Structure", "contract_structure"),
        ("Set-Aside", "set_aside"),
        ("Contract Type", "contract_type"),
        ("Evaluation Basis", "evaluation_basis"),
        ("Transition Window", "transition_window"),
        ("Due Date", "due_date"),
        ("Days Until Due", "days_until_due"),
        ("Estimated Value", "estimated_value"),
        ("Place of Performance", "place_of_performance"),
        ("Opportunity URL", "opportunity_url"),
        ("Scan Bucket", "scan_bucket"),
        ("Scan Match Score", "scan_match_score"),
        ("Scan Confidence Score", "scan_confidence_score"),
        ("Incumbent Signal", "incumbent_signal"),
    ]
    lines: list[str] = []
    for label, key in ordered_keys:
        value = snapshot.get(key, "N/A")
        if key == "opportunity_url" and isinstance(value, str) and value.startswith("http"):
            value = f"[{value}]({value})"
        lines.append(f"- {label}: {value or 'N/A'}")
    return "\n".join(lines)


def _document_inventory_block(inventory: dict[str, Any]) -> str:
    return "\n".join(
        [
            "### Found",
            _markdown_list(inventory.get("found", [])),
            "",
            "### Parsed",
            _markdown_list(inventory.get("parsed", [])),
            "",
            "### Missing",
            _markdown_list(inventory.get("missing", [])),
            "",
            "### Inaccessible",
            _markdown_list(inventory.get("inaccessible", [])),
            "",
            "### Controlled",
            _markdown_list(inventory.get("controlled", [])),
            "",
            "### Actions",
            _markdown_list(inventory.get("action_items", [])),
        ]
    )


def _customer_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Mission Problem:** {_md_cell(section.get('mission_problem'))}",
            "",
            "### Evidence-Backed Customer Priorities",
            _markdown_list(section.get("evidence_backed_priorities", [])),
            "",
            "### Likely Customer Priorities",
            _markdown_list(section.get("likely_priorities", [])),
            "",
            "### Visible Pain Points",
            _markdown_list(section.get("pain_points", [])),
            "",
            "### Repeated Language / Themes",
            _markdown_list(section.get("repeated_language", [])),
            "",
            "### Unknowns Requiring Customer Validation",
            _markdown_list(section.get("unknowns", [])),
        ]
    )


def _funding_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Funding Confidence:** {_md_cell(section.get('funding_confidence'))}",
            f"**Trend Direction:** {_md_cell(section.get('trend_direction'))}",
            "",
            "### Evidence",
            _markdown_list(section.get("evidence", [])),
            "",
            "### Risk to Timing or Award",
            _markdown_list(section.get("risk_to_timing_or_award", [])),
            "",
            "### Open Questions",
            _markdown_list(section.get("open_questions", [])),
        ]
    )


def _acquisition_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Contract Vehicle:** {_md_cell(section.get('contract_vehicle'))}",
            f"**Contract Structure:** {_md_cell(section.get('contract_structure'))}",
            f"**Set-Aside:** {_md_cell(section.get('set_aside'))}",
            f"**Contract Type:** {_md_cell(section.get('contract_type'))}",
            f"**Requirement Type:** {_md_cell(section.get('requirement_type'))}",
            f"**Evaluation Basis:** {_md_cell(section.get('evaluation_basis'))}",
            f"**Transition Window:** {_md_cell(section.get('transition_window'))}",
            "",
            "### Vehicle / Eligibility Assessment",
            _markdown_list(section.get("vehicle_assessment", [])),
            "",
            "### Shaping Signals",
            _markdown_list(section.get("shaping_signals", [])),
            "",
            "### Capture Levers",
            _markdown_list(section.get("capture_levers", [])),
            "",
            "### Vehicle / Eligibility Gaps",
            _markdown_list(section.get("vehicle_or_eligibility_gaps", [])),
            "",
            "### Price-to-Win Implications",
            _markdown_list(section.get("price_to_win_implications", [])),
        ]
    )


def _incumbent_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Incumbent:** {_md_cell(section.get('incumbent_name'))}",
            f"**Source Basis:** {_md_cell(section.get('source_basis'))}",
            f"**Contract Number / Award ID:** {_md_cell(section.get('contract_number'))}",
            f"**Awarding Agency:** {_md_cell(section.get('awarding_agency'))}",
            f"**Public Amount Signal:** {_md_cell(section.get('total_obligated_amount'))}",
            f"**Scope Summary:** {_md_cell(section.get('scope_summary'))}",
            "",
            "### Strength Signals",
            _markdown_list(section.get("strength_signals", [])),
            "",
            "### Vulnerability Signals",
            _markdown_list(section.get("vulnerability_signals", [])),
            "",
            "### Likely Reasons for Prior Selection",
            _markdown_list(section.get("prior_selection_hypotheses", [])),
            "",
            "### Known Subcontractors / Teaming Signals",
            _markdown_list(section.get("known_subcontractors", [])),
        ]
    )


def _stakeholder_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "| Stakeholder | Role | Public Contact | Procurement Relevance | Capture Question | Communication |\n|:---|:---|:---|:---|:---|:---|\n| N/A | N/A | N/A | N/A | N/A | N/A |"
    lines = [
        "| Stakeholder | Role | Public Contact | Procurement Relevance | Capture Question | Communication |",
        "|:---|:---|:---|:---|:---|:---|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {role} | {contact} | {influence} | {question} | {communication} |".format(
                name=_md_cell(row.get("name")),
                role=_md_cell(row.get("role")),
                contact=_md_cell(row.get("contact")),
                influence=_md_cell(row.get("influence")),
                question=_md_cell(row.get("capture_question")),
                communication=_md_cell(row.get("communication")),
            )
        )
    return "\n".join(lines)


def _competitive_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- No specific competitor was strong enough to profile from the current public record."
    blocks: list[str] = []
    for row in rows:
        blocks.extend(
            [
                f"### {row.get('name', 'Competitor')}",
                f"- Why likely: {row.get('why_likely', 'N/A')}",
                f"- Strengths: {row.get('strengths', 'N/A')}",
                f"- Weaknesses / uncertainty: {row.get('weaknesses', 'N/A')}",
                f"- Likely strategy: {row.get('likely_strategy', 'N/A')}",
                f"- Partner relevance: {row.get('partner_relevance', 'N/A')}",
                f"- Evidence: {row.get('evidence', 'N/A')}",
                "",
            ]
        )
    return "\n".join(blocks).strip()


def _partner_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Recommended Posture:** {_md_cell(section.get('recommended_posture'))}",
            "",
            "### Best Partner Candidates",
            _markdown_list(section.get("best_partner_candidates", [])),
            "",
            "### Partner Rationale",
            _markdown_list(section.get("partner_rationale", [])),
            "",
            "### Partner Risks",
            _markdown_list(section.get("partner_risks", [])),
            "",
            "### Partner Outreach Action Items",
            _markdown_list(section.get("partner_outreach_action_items", [])),
            "",
            "### Known Partners Provided by User",
            _markdown_list(section.get("known_partners", [])),
        ]
    )


def _fit_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Company Summary:** {_md_cell(section.get('company_summary'))}",
            f"**Recommended Prime / Team Posture:** {_md_cell(section.get('recommended_prime_team_posture'))}",
            "",
            "### Capability Matches",
            _markdown_list(section.get("capability_hits", [])),
            "",
            "### Past Performance Inventory",
            _markdown_list(section.get("past_performance_inventory", [])),
            "",
            "### Past Performance Hits",
            _markdown_list(section.get("past_performance_hits", [])),
            "",
            "### Proof Points We Can Use",
            _markdown_list(section.get("proof_points", [])),
            "",
            "### Negative Fit Signals",
            _markdown_list(section.get("negative_hits", [])),
            "",
            "### Missing Proof / Gaps",
            _markdown_list(section.get("missing_proof", [])),
            "",
            "### Qualification Gates",
            _markdown_list(section.get("qualification_gates", [])),
            "",
            "### What Would Make Us Credible",
            _markdown_list(section.get("credibility_requirements", [])),
        ]
    )


def _subtle_signals_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- No subtle capture signal was strong enough to call out from the current evidence."
    blocks: list[str] = []
    for row in rows:
        blocks.extend(
            [
                f"### {row.get('signal', 'Signal')}",
                f"- Why it matters: {row.get('why_it_matters', 'N/A')}",
                f"- Effect: {row.get('effect', 'N/A')}",
                f"- Confidence: {row.get('confidence', 'N/A')}",
                f"- Source: {row.get('source', 'N/A')}",
                "",
            ]
        )
    return "\n".join(blocks).strip()


def _win_strategy_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            "### Likely Customer Hot Buttons",
            _markdown_list(section.get("hot_buttons", [])),
            "",
            "### Proposed Win Themes",
            _markdown_list(section.get("win_themes", [])),
            "",
            "### Discriminators",
            _markdown_list(section.get("discriminators", [])),
            "",
            "### Ghosting Strategy",
            _markdown_list(section.get("ghosting_strategy", [])),
            "",
            "### Price-to-Win Considerations",
            _markdown_list(section.get("price_to_win_considerations", [])),
            "",
            "### Transition Strategy",
            _markdown_list(section.get("transition_strategy", [])),
            "",
            "### Staffing / Key Personnel Strategy",
            _markdown_list(section.get("staffing_strategy", [])),
            "",
            "### Compliance Strategy",
            _markdown_list(section.get("compliance_strategy", [])),
            "",
            "### Partner Strategy",
            _markdown_list(section.get("partner_strategy", [])),
        ]
    )


def _questions_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            "### Questions for Customer / Formal Q&A",
            _markdown_list(section.get("customer", [])),
            "",
            "### Questions for Internal Team",
            _markdown_list(section.get("internal", [])),
            "",
            "### Questions for Partners",
            _markdown_list(section.get("partners", [])),
            "",
            "### Questions Requiring Missing Documents",
            _markdown_list(section.get("missing_documents", [])),
        ]
    )


def _action_items_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- No actions generated."
    lines: list[str] = []
    for item in items:
        lines.append(
            "- [{priority}] {owner} - {action} Why: {why} Dependency: {dependency} Capture value: {value}".format(
                priority=_md_cell(item.get("priority")),
                owner=_md_cell(item.get("owner_role")),
                action=_md_cell(item.get("action")),
                why=_md_cell(item.get("why")),
                dependency=_md_cell(item.get("dependency")),
                value=_md_cell(item.get("capture_value")),
            )
        )
    return "\n".join(lines)


def _action_plan_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            "### Immediate Actions, Next 48 Hours",
            _action_items_block(section.get("immediate", [])),
            "",
            "### Near-Term Actions, Next 2 Weeks",
            _action_items_block(section.get("near_term", [])),
            "",
            "### Longer-Term Actions, 30-60 Days",
            _action_items_block(section.get("longer_term", [])),
        ]
    )


def _assumptions_block(section: dict[str, Any]) -> str:
    blocks = [
        f"**Overall Confidence:** {_md_cell(section.get('overall_confidence'))}",
    ]
    if section.get("memo_honesty_score") not in (None, ""):
        blocks.append(f"**Memo Honesty Score:** {_md_cell(section.get('memo_honesty_score'))} / 100")
    if section.get("release_warning"):
        blocks.extend(
            [
                f"**Release Warning:** {_md_cell(section.get('release_warning'))}",
                "",
                "### Why This Memo Is Still Capped",
                _markdown_list(section.get("honesty_drivers", [])),
            ]
        )
    blocks.extend(
        [
            "",
            "### Known Facts",
            _markdown_list(section.get("facts", [])),
            "",
            "### Evidence-Backed Inferences",
            _markdown_list(section.get("evidence_backed_inferences", [])),
            "",
            "### Hypotheses Requiring Validation",
            _markdown_list(section.get("hypotheses", [])),
            "",
            "### Unknowns",
            _markdown_list(section.get("unknowns", [])),
        ]
    )
    return "\n".join(blocks)


def _executive_judgment_block(section: dict[str, Any]) -> str:
    blocks = [
        section.get("executive_summary", "Judgment not generated."),
    ]
    if section.get("memo_honesty_score") not in (None, ""):
        blocks.append(f"**Memo Honesty Score:** {_md_cell(section.get('memo_honesty_score'))} / 100")
    if section.get("release_warning"):
        blocks.append(f"**Release Warning:** {_md_cell(section.get('release_warning'))}")
    blocks.extend(
        [
            "",
            "### Should We Pursue?",
            _markdown_list([f"{section.get('recommendation', 'Undetermined')} ({section.get('score_total', 0)}/100)."] + list(section.get("why", [])[:3])),
            "",
            "### What Would Make Us Credible?",
            _markdown_list(section.get("credibility_requirements", [])),
            "",
            "### Who Already Has Advantage?",
            _markdown_list(section.get("advantaged_players", [])),
            "",
            "### What Does the Customer Appear to Care About?",
            _markdown_list(section.get("customer_cares_about", [])),
            "",
            "### What Should the Capture Team Do Next?",
            _markdown_list(section.get("next_best_actions", [])),
        ]
    )
    if section.get("honesty_drivers"):
        blocks.extend(
            [
                "",
                "### Why This Memo Is Still Capped",
                _markdown_list(section.get("honesty_drivers", [])),
            ]
        )
    return "\n".join(blocks)


def _pursuit_block(section: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"**Recommendation:** {_md_cell(section.get('recommendation'))}",
            f"**Total Score:** {_md_cell(section.get('score_total'))} / 100",
            f"**Confidence:** {_md_cell(section.get('confidence'))}",
            "",
            "### Score Breakdown",
            _score_rows(section.get("score_breakdown", [])),
            "",
            "### Rationale",
            _markdown_list(section.get("rationale", [])),
            "",
            "### Conditions",
            _markdown_list(section.get("conditions", [])),
        ]
    )


def render_capture_brief(template_path: Path, evidence: dict[str, Any]) -> str:
    template = read_text(template_path)
    entry = evidence.get("entry", {})
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
        "{{EXECUTIVE_CAPTURE_JUDGMENT}}": _executive_judgment_block(evidence.get("capture_judgment", {})),
        "{{OPPORTUNITY_SNAPSHOT}}": _opportunity_snapshot(evidence.get("opportunity_snapshot", {})),
        "{{PURSUIT_RECOMMENDATION_AND_SCORE}}": _pursuit_block(evidence.get("pursuit_recommendation", {})),
        "{{EVIDENCE_LEDGER}}": _evidence_ledger_rows(evidence.get("evidence_ledger", [])),
        "{{DOCUMENT_INVENTORY}}": _document_inventory_block(evidence.get("document_inventory", {})),
        "{{CUSTOMER_AND_MISSION_ANALYSIS}}": _customer_block(evidence.get("customer_mission_analysis", {})),
        "{{FUNDING_AND_SPENDING_TREND_ANALYSIS}}": _funding_block(evidence.get("funding_trend_analysis", {})),
        "{{ACQUISITION_STRATEGY}}": _acquisition_block(evidence.get("acquisition_strategy", {})),
        "{{INCUMBENT_ANALYSIS}}": _incumbent_block(evidence.get("incumbent_analysis", {})),
        "{{CONTRACTING_OFFICE_AND_STAKEHOLDER_MAP}}": _stakeholder_rows(evidence.get("stakeholder_analysis", [])),
        "{{COMPETITIVE_LANDSCAPE}}": _competitive_block(evidence.get("competitive_analysis", [])),
        "{{PARTNER_AND_TEAMING_ANALYSIS}}": _partner_block(evidence.get("partner_analysis", {})),
        "{{FIT_ANALYSIS}}": _fit_block(evidence.get("capability_fit_analysis", {})),
        "{{SUBTLE_SIGNALS}}": _subtle_signals_block(evidence.get("subtle_signals", [])),
        "{{RECOMMENDED_WIN_STRATEGY}}": _win_strategy_block(evidence.get("win_strategy", {})),
        "{{QUESTIONS_TO_ASK}}": _questions_block(evidence.get("questions_to_ask", {})),
        "{{ACTION_PLAN}}": _action_plan_block(evidence.get("capture_action_plan", {})),
        "{{ASSUMPTIONS_UNKNOWNS_CONFIDENCE}}": _assumptions_block(evidence.get("assumptions_unknowns_confidence", {})),
    }

    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered
