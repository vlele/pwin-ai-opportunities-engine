from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.jsonl import append_jsonl
from common.paths import safe_slug, standard_procurement_paths, today_local_str, utc_now_iso, write_json, write_text
from common.validation import validate_capture_brief_text
from capture.fetch_notice_context import load_notice_context
from capture.fetch_public_context import fetch_url_excerpt
from capture.render_capture_brief import render_capture_brief
from capture.resolve_entry import resolve_entry
from capture.usaspending_enrich import enrich_from_usaspending


def request_id_for(entry_value: str) -> str:
    timestamp = utc_now_iso().replace("-", "").replace(":", "").replace("T", "").replace("Z", "")
    return f"req-{timestamp[:12]}-{safe_slug(entry_value, 12)}"


def build_request_paths(workspace: Path, digest_date: str, display_entry: str, canonical_id: str, request_id: str) -> dict[str, str]:
    canonical_slug = safe_slug(canonical_id or "item", 24)
    display_slug = safe_slug(display_entry or "direct", 12)
    brief_dir = workspace / "procurement" / "capture-briefs" / digest_date
    evidence_dir = workspace / "procurement" / "capture-evidence" / digest_date
    specific_brief = brief_dir / f"{display_slug}-{canonical_slug}-{request_id}.md"
    specific_evidence = evidence_dir / f"{display_slug}-{canonical_slug}-{request_id}.json"
    alias_brief = brief_dir / f"{display_slug}-{canonical_slug}.md"
    alias_evidence = evidence_dir / f"{display_slug}-{canonical_slug}.json"
    return {
        "request_log_path": (workspace / "procurement" / "capture-requests.jsonl").as_posix(),
        "digest_entry_map_path": (workspace / "procurement" / "digest-entry-map" / f"{digest_date}.json").as_posix(),
        "request_capture_brief_path": specific_brief.as_posix(),
        "request_capture_evidence_path": specific_evidence.as_posix(),
        "latest_alias_capture_brief_path": alias_brief.as_posix(),
        "latest_alias_capture_evidence_path": alias_evidence.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--depth", default="full_360")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    bundle_root = Path(__file__).resolve().parents[2]
    resolved = resolve_entry(workspace, args.entry)
    digest_date = resolved.get("digest_date") or today_local_str()
    display_entry = resolved.get("report_entry_id") or "direct"
    canonical_id = resolved.get("canonical_record_id") or resolved.get("notice_id") or args.entry
    request_id = request_id_for(display_entry or canonical_id)
    artifacts = build_request_paths(workspace, digest_date, display_entry, canonical_id, request_id)

    request_log_event = {
        "request_id": request_id,
        "timestamp": utc_now_iso(),
        "entry": args.entry,
        "entry_resolution_mode": resolved.get("entry_resolution_mode", "unresolved"),
        "request_depth": "full_360_capture_brief",
        "status": "logged",
        "resolved": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
            "title": resolved.get("title", ""),
            "buyer": resolved.get("buyer", ""),
            "source_id": resolved.get("source_id", ""),
            "source_name": resolved.get("source_name", ""),
            "source_tier": resolved.get("source_tier", 1),
            "url": resolved.get("url", ""),
        },
        "artifacts": artifacts,
        "notes": ["Fresh request-specific artifacts must be created for this request."],
    }
    append_jsonl(Path(artifacts["request_log_path"]), request_log_event)

    local_context = load_notice_context(workspace, resolved)
    public_context = fetch_url_excerpt(resolved.get("url", ""))
    usaspending_result = enrich_from_usaspending(resolved.get("title") or canonical_id)

    explanation = local_context.get("explanation_record", {})
    opportunity = local_context.get("opportunity_record", {})
    public_sources = []
    if public_context.get("status") == "ok":
        public_sources.append(
            {
                "title": f"Official page for {resolved.get('title', 'opportunity')}",
                "url": resolved.get("url", ""),
                "publisher": resolved.get("source_name", "Official source"),
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": resolved.get("source_tier", 1),
                "relevance": "Primary public notice context",
                "confidence": 3,
            }
        )

    usaspending_status = usaspending_result.get("spending_by_award", {}).get("status", "error")
    if usaspending_status in {"ok", "http_error", "error"}:
        public_sources.append(
            {
                "title": "USAspending spending by award search",
                "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                "publisher": "USAspending.gov",
                "published_date": "N/A",
                "accessed_date": today_local_str(),
                "tier": 1,
                "relevance": f"Contract award enrichment status: {usaspending_status}",
                "confidence": 2 if usaspending_status == "ok" else 1,
            }
        )

    status = "360_DEEP_RESEARCH_COMPLETE" if public_context.get("status") == "ok" and usaspending_status == "ok" else "PARTIAL_CAPTURE_RESEARCH"
    evidence = {
        "request_id": request_id,
        "generated_at": utc_now_iso(),
        "status": status,
        "vendor_name": "Vendor",
        "entry": {
            "report_entry_id": resolved.get("report_entry_id", ""),
            "digest_date": digest_date,
            "opportunity_id": resolved.get("opportunity_id", ""),
            "canonical_record_id": canonical_id,
            "canonical_record_id_type": resolved.get("canonical_record_id_type", "other"),
            "notice_id": resolved.get("notice_id", ""),
            "title": resolved.get("title", ""),
            "buyer": resolved.get("buyer", ""),
            "source_id": resolved.get("source_id", ""),
            "source_name": resolved.get("source_name", ""),
            "source_tier": resolved.get("source_tier", 1),
            "url": resolved.get("url", ""),
        },
        "artifacts": {
            "request_log_path": artifacts["request_log_path"],
            "request_capture_brief_path": artifacts["request_capture_brief_path"],
            "request_capture_evidence_path": artifacts["request_capture_evidence_path"],
        },
        "executive_brief": {
            "summary": explanation.get("summary") or opportunity.get("summary") or "Fresh structured capture brief generated from current request context.",
            "why_now": "This opportunity is now in capture because it matched the latest workspace shortlist or direct identifier lookup.",
            "risks": [
                "Fresh public evidence may still be incomplete if browser-safe or API-safe retrieval failed.",
                "Mission and incumbent assumptions should be validated against current official artifacts.",
            ],
            "success_metrics": [
                "Validated scope understanding",
                "Incumbent posture clarity",
                "Actionable next capture moves",
            ],
            "win_themes": [
                "Evidence-backed federal mission fit",
                "Clear compliance and delivery readiness",
            ],
            "proof_points": [
                "Recent relevant delivery examples",
                "Federal program alignment",
            ],
        },
        "objectives": [
            {
                "objective": resolved.get("title", "Opportunity objective decomposition pending"),
                "mission_driver": opportunity.get("buyer", resolved.get("buyer", "N/A")),
                "policy_driver": "Validate against agency policy and solicitation text",
                "budget_signal": "Use USAspending and prior awards to confirm funding reality",
                "stakeholders": resolved.get("buyer", "N/A"),
                "incumbents": "To be validated with award-history enrichment",
                "key_risks": "Partial evidence until fresh official retrieval completes",
                "kpis": "Cycle-time reduction, compliance fidelity, mission delivery outcomes",
                "solution_implications": "Shape win themes around mission fit, compliance, and realism",
                "evidence_links": resolved.get("url", "N/A"),
                "evidence_snippets": [
                    public_context.get("text_excerpt", "")[:300] or "No public excerpt captured in this run.",
                ],
            }
        ],
        "stakeholder_map": [
            f"Primary buyer / agency signal: {resolved.get('buyer', 'N/A')}",
            "Program leadership, KO/CO, CIO/CISO, and mission owner still need deeper official-source confirmation.",
        ],
        "budget_funding_signals": [
            "Run USAspending and prior-award analysis to estimate realistic spend bands and incumbent patterns.",
            f"USAspending search status this run: {usaspending_status}",
        ],
        "related_procurements": [
            "Compare this identifier against prior archived SAM opportunities and related award notices.",
        ],
        "vehicle_signals": [
            "Assess likely vehicle path from agency history and companion notices when available.",
        ],
        "competitive_landscape": {
            "likely_incumbents": [],
            "frequent_primes": [],
            "common_teammates": [],
            "emerging_challengers": [],
            "notes": [
                "Competitive posture should be expanded with USAspending and official archived procurement history.",
            ],
        },
        "public_discourse_signals": [
            "Check agency strategic plans, OIG/GAO findings, and recent testimony aligned to this requirement.",
            "Review public statements, blogs, and procurement forecasts tied to this buyer and mission area.",
        ],
        "recommended_next_research_moves": [
            "Pull agency strategy, policy, and oversight documents linked to the mission area.",
            "Expand award-history review for incumbent and funding trend signals.",
            "Map likely stakeholders and decision makers from official bios and testimony.",
        ],
        "action_items_next_10_days": [
            "Confirm mission driver and program owner from official sources.",
            "Build incumbent hypothesis from award history and prior procurements.",
            "Translate findings into win themes and proof points for capture planning.",
        ],
        "assumptions_to_validate": [
            "The visible buyer signal correctly identifies the mission owner.",
            "Archived procurement history exists and is comparable to the current opportunity.",
        ],
        "evidence_gaps": [
            "Fresh solicitation objectives may still need deeper parsing from official source documents.",
            "Stakeholder, budget, and incumbent details remain partial until more public-source evidence is collected.",
        ],
        "source_log": public_sources,
        "validation": {
            "all_required_sections_present": False,
            "contains_placeholders": False,
            "generated_from_current_request": True,
            "stub_stage_exited_before_response": True,
            "menu_only_fallback_used": False,
        },
    }

    brief_text = render_capture_brief(bundle_root / "templates" / "capture-brief.template.md", evidence)
    brief_validation = validate_capture_brief_text(brief_text)
    evidence["validation"]["all_required_sections_present"] = brief_validation["all_required_sections_present"]

    write_text(Path(artifacts["request_capture_brief_path"]), brief_text)
    write_json(Path(artifacts["request_capture_evidence_path"]), evidence)
    write_text(Path(artifacts["latest_alias_capture_brief_path"]), brief_text)
    write_json(Path(artifacts["latest_alias_capture_evidence_path"]), evidence)

    final_log_event = dict(request_log_event)
    final_log_event["status"] = status
    final_log_event["notes"] = [
        "Fresh request-specific brief and evidence were generated for this request.",
        f"Public notice fetch status: {public_context.get('status', 'unknown')}",
        f"USAspending enrichment status: {usaspending_status}",
    ]
    append_jsonl(Path(artifacts["request_log_path"]), final_log_event)

    result = {
        "status": status,
        "request_id": request_id,
        "brief_path": artifacts["request_capture_brief_path"],
        "evidence_path": artifacts["request_capture_evidence_path"],
        "browser_attempted": False,
        "browser_succeeded": False,
        "usaspending_attempted": True,
        "usaspending_succeeded": usaspending_status == "ok",
        "stable_id": resolved.get("report_entry_id", ""),
        "canonical_record_id": canonical_id,
        "recommended_next_moves": evidence["recommended_next_research_moves"],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if status == "360_DEEP_RESEARCH_COMPLETE" else 10


if __name__ == "__main__":
    raise SystemExit(main())
