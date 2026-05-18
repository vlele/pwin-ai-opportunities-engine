from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import load_json, read_text, standard_procurement_paths, today_local_str, write_text
from common.validation import validate_digest_text
from scan.build_digest_entry_map import build_digest_entry_map


def explanations_lookup(raw: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("items") or raw.get("explanations") or []
    else:
        items = []

    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in (item.get("opportunity_id"), item.get("canonical_record_id"), item.get("title")):
            if key:
                lookup[str(key)] = item
    return lookup


def entry_explanation(entry: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for key in (entry.get("opportunity_id"), entry.get("canonical_record_id"), entry.get("title")):
        if key and key in lookup:
            return lookup[key]
    return {}


def reasons_block(reasons: list[str], fallback: str) -> str:
    items = reasons[:4] if reasons else [fallback]
    return "\n".join(f"- {item}" for item in items)


def timing_label(entry: dict[str, Any]) -> str:
    timing_window = str(entry.get("timing_window", "") or "").strip().lower()
    days_until_due = entry.get("days_until_due")
    suffix = f" ({days_until_due} days)" if isinstance(days_until_due, int) else ""
    if timing_window == "urgent":
        return f"Urgent bid activity{suffix}"
    if timing_window == "active":
        return f"Active pursuit{suffix}"
    if timing_window == "watchlist":
        return f"Watchlist / early shaping{suffix}"
    return "N/A"


def render_entry(entry: dict[str, Any], explanation: dict[str, Any]) -> str:
    title = entry.get("title", "Untitled opportunity")
    summary = explanation.get("summary") or explanation.get("opportunity_summary") or "N/A"
    reasons = explanation.get("reasons") or explanation.get("why_it_matters") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    caveat = explanation.get("main_caveat") or explanation.get("caveat") or "N/A"
    source_label = f'{entry.get("source_name", "Unknown")} (Tier {entry.get("source_tier", "N/A")})'
    return "\n".join(
        [
            f"### {entry['entry_id']} - {title}",
            "",
            "| Field | Value |",
            "|:---|:---|",
            f"| Buyer | {entry.get('buyer', 'N/A')} |",
            f"| Due | {entry.get('due_date', 'N/A')} |",
            f"| Timing Window | {timing_label(entry)} |",
            f"| Notice Type | {entry.get('notice_type', 'N/A')} |",
            f"| Opportunity Class | {entry.get('opportunity_class', 'N/A')} |",
            f"| Source | {source_label} |",
            f"| Match Score | {entry.get('match_score', 0)} |",
            f"| Confidence | {entry.get('confidence_score', 0)} |",
            f"| Direct URL | {entry.get('url', 'N/A')} |",
            "",
            f"Opportunity summary: {summary}",
            "",
            "Why it matters:",
            reasons_block(reasons, "Evidence-backed details still being assembled."),
            "",
            f"Caveat: {caveat}",
        ]
    )


def render_section(entries: list[dict[str, Any]], lookup: dict[str, dict[str, Any]]) -> str:
    if not entries:
        return "none found"
    return "\n\n---\n\n".join(render_entry(entry, entry_explanation(entry, lookup)) for entry in entries)


def replace_many(template: str, replacements: dict[str, str]) -> str:
    result = template
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


def render_digest_and_report(
    bundle_root: Path,
    workspace: Path,
    date_str: str,
    horizon: str,
    run_notes: list[str] | None = None,
    enabled_source_summary: str | None = None,
    source_issues: list[str] | None = None,
) -> dict[str, Any]:
    paths = standard_procurement_paths(workspace, date_str)
    digest_entry_map = load_json(paths["digest_entry_map"], default=None)
    if digest_entry_map is None:
        digest_entry_map = build_digest_entry_map(workspace, date_str)

    explanations = load_json(paths["explanations"], default=[])
    lookup = explanations_lookup(explanations)
    entries = digest_entry_map.get("entries", [])
    counts = digest_entry_map.get("counts", {})
    grouped = {
        "action_now": [entry for entry in entries if entry.get("bucket") == "action_now"],
        "worth_a_look": [entry for entry in entries if entry.get("bucket") == "worth_a_look"],
        "watchlist": [entry for entry in entries if entry.get("bucket") == "watchlist"],
        "suppressed": [entry for entry in entries if entry.get("bucket") == "suppressed"],
    }

    run_status = digest_entry_map.get("run_status", "OK")
    digest_template = read_text(bundle_root / "templates" / "daily-digest.template.md")
    report_template = read_text(bundle_root / "templates" / "daily-report.template.md")

    notes_text = "\n".join(f"- {note}" for note in (run_notes or [])) or "none found"
    used_source_summary = ", ".join(
        sorted(
            {
                f'{entry.get("source_name", "Unknown")} (Tier {entry.get("source_tier", "N/A")})'
                for entry in entries
                if entry.get("source_name")
            }
        )
    )
    if used_source_summary:
        source_summary = used_source_summary
        if enabled_source_summary and enabled_source_summary != used_source_summary:
            source_summary = f"Used: {used_source_summary} | Enabled: {enabled_source_summary}"
    else:
        source_summary = (
            f"Enabled: {enabled_source_summary}; matched records: none"
            if enabled_source_summary
            else "none found"
        )

    replacements = {
        "{{VENDOR_NAME}}": digest_entry_map.get("vendor_name", "Vendor"),
        "{{DATE}}": date_str,
        "{{DISPLAY_DATE}}": date_str,
        "{{RUN_STATUS}}": run_status,
        "{{SCAN_PERIOD}}": horizon,
        "{{SOURCE_SUMMARY}}": source_summary,
        "{{SCANNED_COUNT}}": str(len(entries)),
        "{{ACTION_COUNT}}": str(counts.get("action_now", 0)),
        "{{WORTH_COUNT}}": str(counts.get("worth_a_look", 0)),
        "{{WATCHLIST_COUNT}}": str(counts.get("watchlist", 0)),
        "{{SUPPRESSED_COUNT}}": str(counts.get("suppressed", 0)),
        "{{RUN_NOTES_OR_NONE}}": notes_text,
        "{{ACTION_NOW_ENTRIES_OR_NONE}}": render_section(grouped["action_now"], lookup),
        "{{WORTH_A_LOOK_ENTRIES_OR_NONE}}": render_section(grouped["worth_a_look"], lookup),
        "{{WATCHLIST_ENTRIES_OR_NONE}}": render_section(grouped["watchlist"], lookup),
        "{{SUPPRESSED_ENTRIES_OR_NONE}}": render_section(grouped["suppressed"], lookup),
        "{{PREFERENCE_CHANGES_OR_NONE}}": "none found",
        "{{SOURCE_ISSUES_OR_NONE}}": "\n".join(f"- {item}" for item in (source_issues or [])) or "none found",
        "{{UNIQUE_COUNT}}": str(len(entries)),
        "{{QUARANTINE_COUNT}}": str(1 if run_status == "QUARANTINED_EMPTY_SNAPSHOT" else 0),
        "{{PREFERENCE_DRIFT_OR_NONE}}": "none found",
    }

    digest_text = replace_many(digest_template, replacements)
    report_text = replace_many(report_template, replacements)

    write_text(paths["digest"], digest_text)
    write_text(paths["report"], report_text)

    digest_validation = validate_digest_text(digest_text)
    return {
        "digest_path": str(paths["digest"]).replace("\\", "/"),
        "report_path": str(paths["report"]).replace("\\", "/"),
        "digest_validation": digest_validation,
        "run_status": run_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--date", default=today_local_str())
    parser.add_argument("--horizon", default="30-45")
    args = parser.parse_args()

    bundle_root = Path(__file__).resolve().parents[2]
    result = render_digest_and_report(bundle_root, Path(args.workspace), args.date, args.horizon)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
