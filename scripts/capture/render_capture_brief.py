from __future__ import annotations

from datetime import datetime
import html
from pathlib import Path
from typing import Any

from common.paths import read_text


def _md_cell(value: object) -> str:
    return str(value or "N/A").replace("|", "/").replace("\n", " ").strip() or "N/A"


def _markdown_list(items: list[str], empty: str = "none found") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def _strategy_row_list(rows: list[dict[str, Any]] | list[str], empty: str) -> str:
    if not rows:
        return f"- {empty}"
    if rows and isinstance(rows[0], dict):
        lines: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            anchor = str(row.get("evidence_anchor") or "").strip()
            if not text:
                continue
            lines.append(f"- {text}" + (f" Anchor: {anchor}" if anchor else ""))
        return "\n".join(lines) if lines else f"- {empty}"
    return _markdown_list([str(item) for item in rows if str(item).strip()], empty=empty)


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
        ("NAICS Size Standard", "naics_size_standard"),
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
        ("Period of Performance", "period_of_performance"),
        ("Funds Status", "funds_status"),
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


def _timeline_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _timeline_numeric(value: object) -> float:
    dt = _timeline_datetime(value)
    if dt is None:
        return 0.0
    return dt.toordinal() + ((dt.hour * 60) + dt.minute) / 1440.0


def _timeline_color(kind: str) -> str:
    palette = {
        "capture": "#475569",
        "issue": "#2563eb",
        "amendment": "#7c3aed",
        "due": "#c2410c",
        "award": "#b45309",
        "base_start": "#0f766e",
        "base_end": "#0369a1",
        "option_start": "#0f766e",
        "option_end": "#0369a1",
    }
    return palette.get(kind, "#334155")


def _timeline_svg(milestones: list[dict[str, Any]]) -> str:
    dated = [item for item in milestones if _timeline_datetime(item.get("date_iso"))]
    if len(dated) < 2:
        return ""
    ordered = sorted(dated, key=lambda item: (_timeline_numeric(item.get("date_iso")), str(item.get("label", ""))))
    width = 980
    height = 250
    left = 72
    right = 44
    axis_y = 132
    usable_width = width - left - right
    numbers = [_timeline_numeric(item.get("date_iso")) for item in ordered]
    min_value = min(numbers)
    max_value = max(numbers)
    lanes = [74, 192]
    label_offsets = [-18, 26]

    def milestone_x(index: int, numeric: float) -> float:
        if max_value <= min_value:
            if len(ordered) == 1:
                return left + usable_width / 2
            return left + (usable_width * index / max(1, len(ordered) - 1))
        return left + ((numeric - min_value) / (max_value - min_value)) * usable_width

    points: list[tuple[dict[str, Any], float, float, int]] = []
    last_x: float | None = None
    lane_cursor = 0
    for index, item in enumerate(ordered):
        x = milestone_x(index, numbers[index])
        if last_x is not None and abs(x - last_x) < 72:
            lane_cursor = 1 - lane_cursor
        else:
            lane_cursor = index % 2
        last_x = x
        points.append((item, x, lanes[lane_cursor], lane_cursor))

    start_label = html.escape(str(ordered[0].get("display_date") or ordered[0].get("date_iso") or "Start"))
    end_label = html.escape(str(ordered[-1].get("display_date") or ordered[-1].get("date_iso") or "End"))
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Procurement timeline">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#f8fafc" stroke="#dbe4ee"/>',
        f'<text x="{left}" y="34" font-family="Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" fill="#102a43">Procurement Timeline</text>',
        f'<text x="{left}" y="56" font-family="Segoe UI, Arial, sans-serif" font-size="12" fill="#52606d">Deterministic SVG rendered from extracted solicitation milestones.</text>',
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" stroke="#94a3b8" stroke-width="4" stroke-linecap="round"/>',
        f'<text x="{left}" y="{axis_y + 28}" text-anchor="start" font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#64748b">{start_label}</text>',
        f'<text x="{width - right}" y="{axis_y + 28}" text-anchor="end" font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#64748b">{end_label}</text>',
    ]
    for item, x, y, lane_index in points:
        label = html.escape(str(item.get("label") or "Milestone"))
        display_date = html.escape(str(item.get("display_date") or item.get("date_iso") or "Date unavailable"))
        detail = html.escape(str(item.get("detail") or ""))
        color = _timeline_color(str(item.get("kind") or ""))
        anchor = "start" if x < left + usable_width * 0.2 else "end" if x > left + usable_width * 0.8 else "middle"
        label_x = x if anchor == "middle" else x + 8 if anchor == "start" else x - 8
        text_y = y + label_offsets[lane_index]
        svg_parts.extend(
            [
                f'<line x1="{x:.1f}" y1="{axis_y}" x2="{x:.1f}" y2="{y}" stroke="{color}" stroke-width="2.5"/>',
                f'<circle cx="{x:.1f}" cy="{y}" r="8" fill="{color}" stroke="#ffffff" stroke-width="2"/>',
                f'<text x="{label_x:.1f}" y="{text_y}" text-anchor="{anchor}" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="700" fill="#0f172a">{label}</text>',
                f'<text x="{label_x:.1f}" y="{text_y + 16}" text-anchor="{anchor}" font-family="Segoe UI, Arial, sans-serif" font-size="11" fill="#475569">{display_date}</text>',
            ]
        )
        if detail:
            svg_parts.append(
                f'<text x="{label_x:.1f}" y="{text_y + 31}" text-anchor="{anchor}" font-family="Segoe UI, Arial, sans-serif" font-size="10" fill="#64748b">{detail}</text>'
            )
    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _procurement_timeline_block(section: dict[str, Any]) -> str:
    milestones = section.get("milestones", [])
    if not isinstance(milestones, list) or not milestones:
        return "- No procurement timeline milestones were extracted from current evidence."
    milestone_lines = []
    for item in milestones:
        if not isinstance(item, dict):
            continue
        label = _md_cell(item.get("label"))
        display_date = _md_cell(item.get("display_date"))
        detail = str(item.get("detail") or "").strip()
        milestone_lines.append(f"{label}: {display_date}" + (f" - {detail}" if detail else ""))
    blocks = [
        _markdown_list(milestone_lines, empty="No procurement timeline milestones were extracted from current evidence."),
    ]
    svg = _timeline_svg([item for item in milestones if isinstance(item, dict)])
    if svg:
        blocks.extend(["", svg])
    notes = section.get("notes", [])
    if isinstance(notes, list) and notes:
        blocks.extend(["", "#### Timeline Notes", _markdown_list([str(note) for note in notes if str(note).strip()])])
    return "\n".join(blocks)


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
    blocks = [
        f"**Mission Problem:** {_md_cell(section.get('mission_problem'))}",
    ]
    if section.get("priority_rendering_warning"):
        blocks.extend(
            [
                "",
                f"**Priority Evidence Note:** {_md_cell(section.get('priority_rendering_warning'))}",
            ]
        )
    if section.get("strategic_reasoning_summary"):
        blocks.extend(
            [
                "",
                f"**Strategic Capture Read:** {_md_cell(section.get('strategic_reasoning_summary'))}",
            ]
        )
    blocks.extend(
        [
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
            "### Reasoned Pain Points",
            _markdown_list(section.get("strategic_pain_points", [])),
            "",
            "### External Pressure Signals",
            _markdown_list(section.get("external_pressure_signals", [])),
            "",
            "### Requirement Workstreams",
            _markdown_list(section.get("requirement_workstreams", [])),
            "",
            "### Repeated Language / Themes",
            _markdown_list(section.get("repeated_language", [])),
            "",
            "### Unknowns Requiring Customer Validation",
            _markdown_list(section.get("unknowns", [])),
        ]
    )
    return "\n".join(blocks)


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
            "### Solicitation Fact Checks",
            _markdown_list(section.get("solicitation_facts", [])),
            "",
            "### Operational / Security Constraints",
            _markdown_list(section.get("operational_constraints", [])),
            "",
            "### Staffing / Pricing Signals",
            _markdown_list(section.get("staffing_pricing_signals", [])),
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
        return "| Stakeholder | Role | Public Contact | Public History / Signals | Procurement Relevance | Capture Question | Communication |\n|:---|:---|:---|:---|:---|:---|:---|\n| N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
    lines = [
        "| Stakeholder | Role | Public Contact | Public History / Signals | Procurement Relevance | Capture Question | Communication |",
        "|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {role} | {contact} | {history} | {influence} | {question} | {communication} |".format(
                name=_md_cell(row.get("name")),
                role=_md_cell(row.get("role")),
                contact=_md_cell(row.get("contact")),
                history=_md_cell(row.get("history")),
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
        role = str(row.get("role") or "").strip()
        blocks.extend(
            [
                f"### {row.get('name', 'Competitor')}" + (f" ({role})" if role else ""),
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
            f"**Semantic Fit Summary:** {_md_cell(section.get('semantic_fit_summary'))}",
            f"**Vendor Fit Weighting Summary:** {_md_cell(section.get('fit_weighting_summary'))}",
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
            "### Historical Preference Support",
            _markdown_list(section.get("historical_preference_support", [])),
            "",
            "### Historical Preference Cautions",
            _markdown_list(section.get("historical_preference_cautions", [])),
            "",
            "### Vendor Fit Weighting Signals",
            _markdown_list(section.get("fit_weighting_signals", [])),
            "",
            "### Vendor Fit Weighting Cautions",
            _markdown_list(section.get("fit_weighting_cautions", [])),
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
    blocks = []
    if section.get("central_pain_point"):
        blocks.extend(
            [
                f"**Central Pain Point:** {_md_cell(section.get('central_pain_point'))}",
            ]
        )
    if section.get("reasoning_summary"):
        blocks.extend(
            [
                f"**Reasoning Summary:** {_md_cell(section.get('reasoning_summary'))}",
                "",
            ]
        )
    blocks.extend(
        [
            "### Likely Customer Hot Buttons",
            _strategy_row_list(section.get("hot_button_rows", []) or section.get("hot_buttons", []), "No validated hot buttons surfaced from the current package."),
            "",
            "### Proposed Win Themes",
            _strategy_row_list(section.get("win_theme_rows", []) or section.get("win_themes", []), "Insufficient corroborated evidence to recommend win themes yet."),
            "",
            "### Discriminators",
            _strategy_row_list(section.get("discriminator_rows", []) or section.get("discriminators", []), "Insufficient corroborated evidence to recommend differentiators yet."),
            "",
            "### Workstream Capture Implications",
            _strategy_row_list(
                section.get("workstream_capture_implication_rows", []) or section.get("workstream_capture_implications", []),
                "No workstream-specific capture implication survived validation in this run.",
            ),
            "",
            "### Reasoning-Based Win Themes and Differentiators",
            _strategy_row_list(
                section.get("reasoning_based_win_theme_rows", []) or section.get("reasoning_based_win_themes", []),
                "Reasoning-based win themes remain unverified until extracted scope sections or promoted solicitation facts surface.",
            ),
            "",
            "### Reasoning-Based Proof Required",
            _strategy_row_list(
                section.get("reasoning_based_proof_requirement_rows", []) or section.get("reasoning_based_proof_requirements", []),
                "Proof requirements remain provisional until extracted scope sections or promoted solicitation facts surface.",
            ),
            "",
            "### Reasoning-Based Risk Implications",
            _markdown_list(section.get("reasoning_based_risk_implications", [])),
            "",
            "### Proof Artifacts to Build",
            _markdown_list(section.get("proof_artifact_recommendations", [])),
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
    return "\n".join(blocks)


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
          "### Historical Learning Context",
          _markdown_list(section.get("historical_learning_context", [])),
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
          "### What Past Feedback Suggests",
          _markdown_list(section.get("historical_fit_context", [])),
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
        "{{PROCUREMENT_TIMELINE}}": _procurement_timeline_block(evidence.get("procurement_timeline", {})),
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
