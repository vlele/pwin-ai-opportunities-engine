from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import scan.run_scan as scan_run  # type: ignore
from common.paths import utc_now_iso


def _evaluate_case(
    case: dict[str, Any],
    profile: dict[str, Any],
    preferences: dict[str, Any],
    fit_guidance: dict[str, Any],
    keywords: list[str],
    negative_keywords: list[str],
    today,
) -> dict[str, Any]:
    record = case.get("record", {})
    hydrated_text = case.get("hydrated_text")
    combined_text = scan_run._normalized_text(
        f"{record.get('title', '')} {record.get('summary', '')} {hydrated_text or ''}"
    )
    token_set = set(combined_text.split())
    fit_points, fit_reasons, fit_context = scan_run._fit_narrative_alignment(
        fit_guidance,
        combined_text,
        token_set,
    )
    due_date = scan_run._parse_any_date(record.get("due_date"))
    timing_band, days_until_due = scan_run._timing_band(due_date, today, preferences)
    screening_categories = scan_run._notice_categories(record, hydrated_text)
    guidance_bucket, guidance_note, matched_categories = scan_run._notice_guidance(
        preferences,
        screening_categories,
        timing_band,
    )
    preference_bucket, preference_note = scan_run._preference_filter_guidance(
        record,
        combined_text,
        token_set,
        preferences,
    )
    if preference_bucket == "suppressed":
        guidance_bucket = "suppressed"
        guidance_note = preference_note

    match_score, confidence_score, reasons, caveat, score_fit_context = scan_run._score_record(
        record,
        keywords,
        negative_keywords,
        fit_guidance,
        profile,
        preferences,
        hydrated_text,
        timing_band,
        days_until_due,
    )
    bucket = scan_run._bucket_for_record(match_score, timing_band, preferences, guidance_bucket, score_fit_context)
    urgent_hold = scan_run._urgent_bucket_hold_reason(
        bucket,
        match_score,
        timing_band,
        preferences,
        guidance_bucket,
        score_fit_context,
    )
    keyword_hits = [keyword for keyword in keywords if scan_run._keyword_matches(keyword, combined_text, token_set)]
    negative_keyword_hits = [
        keyword for keyword in negative_keywords if scan_run._keyword_matches(keyword, combined_text, token_set)
    ]
    low_signal_only = bool(fit_context.get("low_signal_positive_hits") and not fit_context.get("positive_hits") and not keyword_hits)

    checks: list[tuple[str, bool, str]] = [
        (
            "bucket",
            bucket == case.get("expected_bucket"),
            f"expected {case.get('expected_bucket')} got {bucket}",
        ),
    ]
    if "expected_timing_band" in case:
        checks.append(
            (
                "timing_band",
                timing_band == case.get("expected_timing_band"),
                f"expected {case.get('expected_timing_band')} got {timing_band}",
            )
        )
    if "expected_guidance_bucket" in case:
        checks.append(
            (
                "guidance_bucket",
                guidance_bucket == case.get("expected_guidance_bucket"),
                f"expected {case.get('expected_guidance_bucket')} got {guidance_bucket}",
            )
        )
    if "expected_low_signal_only" in case:
        checks.append(
            (
                "low_signal_only",
                low_signal_only == case.get("expected_low_signal_only"),
                f"expected {case.get('expected_low_signal_only')} got {low_signal_only}",
            )
        )

    failures = [name for name, ok, _detail in checks if not ok]
    return {
        "id": case.get("id", ""),
        "passed": not failures,
        "failed_checks": failures,
        "check_details": [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks],
        "expected_bucket": case.get("expected_bucket"),
        "actual_bucket": bucket,
        "timing_band": timing_band,
        "guidance_bucket": guidance_bucket,
        "guidance_note": guidance_note,
        "matched_categories": matched_categories,
        "match_score": match_score,
        "confidence_score": confidence_score,
        "days_until_due": days_until_due,
        "keyword_hits": keyword_hits,
        "negative_keyword_hits": negative_keyword_hits,
        "fit_points": fit_points,
        "fit_reasons": fit_reasons,
        "fit_positive_hits": fit_context.get("positive_hits", []),
        "fit_low_signal_positive_hits": fit_context.get("low_signal_positive_hits", []),
        "fit_negative_hits": fit_context.get("negative_hits", []),
        "low_signal_only": low_signal_only,
        "score_reasons": reasons,
        "urgent_hold_reason": urgent_hold,
        "caveat": caveat,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("gold_bucket_cases.json")),
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    profile = payload.get("profile", {})
    preferences = payload.get("preferences", {})
    today = datetime.strptime(payload.get("today", "2026-05-23"), "%Y-%m-%d").date()
    fit_guidance = scan_run._fit_narrative_guidance(profile)
    keywords = scan_run._vendor_keywords(profile, preferences)
    negative_keywords = scan_run._vendor_negative_keywords(profile, preferences)

    results = [
        _evaluate_case(case, profile, preferences, fit_guidance, keywords, negative_keywords, today)
        for case in payload.get("cases", [])
    ]
    failed_case_ids = [item["id"] for item in results if not item["passed"]]
    output = {
        "status": "OK" if not failed_case_ids else "FAILED",
        "generated_at": utc_now_iso(),
        "case_count": len(results),
        "passed": len(results) - len(failed_case_ids),
        "failed": len(failed_case_ids),
        "failed_case_ids": failed_case_ids,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failed_case_ids else 10


if __name__ == "__main__":
    raise SystemExit(main())
