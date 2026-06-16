from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import first_non_empty, load_json, standard_procurement_paths, today_local_str, utc_now_iso, write_json


BUCKET_ORDER = ["action_now", "worth_a_look", "watchlist", "suppressed"]
BUCKET_PREFIX = {
    "action_now": "A",
    "worth_a_look": "W",
    "watchlist": "E",
    "suppressed": "S",
}


def normalize_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("records", "opportunities", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def infer_bucket(record: dict[str, Any]) -> str:
    bucket = str(record.get("bucket", "")).strip().lower()
    if bucket == "near_miss":
        return "watchlist"
    if bucket in BUCKET_ORDER:
        return bucket
    screening_status = str(record.get("screening_status", "")).lower()
    if screening_status in {"suppressed", "rejected"}:
        return "suppressed"
    match_score = int(record.get("match_score") or 0)
    if match_score >= 75:
        return "action_now"
    if match_score >= 60:
        return "worth_a_look"
    if match_score >= 45:
        return "watchlist"
    return "suppressed"


def build_entries(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[infer_bucket(record)].append(record)

    for bucket_records in grouped.values():
        bucket_records.sort(
            key=lambda item: (
                int(item.get("match_score") or 0),
                int(item.get("confidence_score") or 0),
                str(item.get("title") or ""),
            ),
            reverse=True,
        )

    entries: list[dict[str, Any]] = []
    counts = {bucket: len(grouped.get(bucket, [])) for bucket in BUCKET_ORDER}

    for bucket in BUCKET_ORDER:
        for index, record in enumerate(grouped.get(bucket, []), start=1):
            entry_id = f"{BUCKET_PREFIX[bucket]}{index}"
            canonical_id = first_non_empty(
                [
                    record.get("canonical_record_id"),
                    record.get("notice_id"),
                    record.get("opportunity_id"),
                    record.get("source_record_id"),
                ],
                "",
            )
            canonical_type = "notice_id" if record.get("notice_id") else "opportunity_id"
            entries.append(
                {
                    "entry_id": entry_id,
                    "bucket": bucket,
                    "source_id": record.get("source_id", ""),
                    "source_name": record.get("source_name", ""),
                    "source_tier": record.get("source_tier", 1),
                    "title": record.get("title", "Untitled opportunity"),
                    "url": record.get("url", ""),
                    "buyer": record.get("buyer", "N/A"),
                    "due_date": record.get("due_date", "N/A"),
                    "match_score": int(record.get("match_score") or 0),
                    "confidence_score": int(record.get("confidence_score") or 0),
                    "opportunity_id": record.get("opportunity_id", ""),
                    "canonical_record_id": canonical_id,
                    "canonical_record_id_type": record.get("canonical_record_id_type", canonical_type),
                    "notice_id": record.get("notice_id", ""),
                    "notice_type": record.get("notice_type", ""),
                    "opportunity_class": record.get("opportunity_class", ""),
                    "timing_window": record.get("timing_window", ""),
                    "days_until_due": record.get("days_until_due"),
                }
            )
    return entries, counts


def build_digest_entry_map(workspace: Path, date_str: str, generated_at: str | None = None) -> dict[str, Any]:
    paths = standard_procurement_paths(workspace, date_str)
    opportunities_raw = load_json(paths["opportunities"], default=[])
    vendor_profile = load_json(paths["vendor_profile"], default={})
    records = normalize_records(opportunities_raw)
    entries, counts = build_entries(records)
    company = vendor_profile.get("company", {}) if isinstance(vendor_profile.get("company"), dict) else {}
    vendor_name = (
        vendor_profile.get("vendor_name")
        or vendor_profile.get("name")
        or company.get("name")
        or "Vendor"
    )

    run_status = "OK"
    if not records:
        run_status = "QUARANTINED_EMPTY_SNAPSHOT"

    digest_entry_map = {
        "digest_date": date_str,
        "generated_at": generated_at or utc_now_iso(),
        "run_status": run_status,
        "vendor_name": vendor_name,
        "digest_path": str(paths["digest"]).replace("\\", "/"),
        "report_path": str(paths["report"]).replace("\\", "/"),
        "opportunities_path": str(paths["opportunities"]).replace("\\", "/"),
        "explanations_path": str(paths["explanations"]).replace("\\", "/"),
        "entries": entries,
        "counts": counts,
    }
    write_json(paths["digest_entry_map"], digest_entry_map)
    return digest_entry_map


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--date", default=today_local_str())
    args = parser.parse_args()

    digest_entry_map = build_digest_entry_map(Path(args.workspace), args.date)
    print(json.dumps(digest_entry_map, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
