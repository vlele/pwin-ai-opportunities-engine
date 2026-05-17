from __future__ import annotations

from pathlib import Path
from typing import Any

from common.paths import latest_dated_file, load_json, standard_procurement_paths


def _load_latest_digest_maps(workspace: Path) -> list[dict[str, Any]]:
    maps_dir = workspace / "procurement" / "digest-entry-map"
    if not maps_dir.exists():
        return []
    maps = []
    for path in sorted(maps_dir.glob("*.json"), reverse=True):
        data = load_json(path, default={})
        if isinstance(data, dict):
            maps.append(data)
    return maps


def resolve_entry(workspace: Path, entry: str) -> dict[str, Any]:
    entry = entry.strip()
    upper_entry = entry.upper()
    if upper_entry and upper_entry[0] in {"A", "W", "E", "N", "S"} and upper_entry[1:].isdigit():
        for digest_map in _load_latest_digest_maps(workspace):
            for item in digest_map.get("entries", []):
                if item.get("entry_id") == upper_entry:
                    return {
                        "status": "resolved",
                        "entry_resolution_mode": "digest_entry",
                        "report_entry_id": upper_entry,
                        "digest_date": digest_map.get("digest_date", ""),
                        **item,
                    }

    opportunities_dir = workspace / "procurement" / "opportunities"
    if opportunities_dir.exists():
        for path in sorted(opportunities_dir.glob("*.json"), reverse=True):
            data = load_json(path, default=[])
            records = data if isinstance(data, list) else data.get("records", [])
            for record in records:
                candidates = {
                    str(record.get("canonical_record_id", "")),
                    str(record.get("notice_id", "")),
                    str(record.get("opportunity_id", "")),
                    str(record.get("url", "")),
                }
                if entry in candidates:
                    return {
                        "status": "resolved",
                        "entry_resolution_mode": "direct_identifier",
                        "report_entry_id": "",
                        "digest_date": path.stem,
                        "title": record.get("title", ""),
                        "buyer": record.get("buyer", ""),
                        "source_id": record.get("source_id", ""),
                        "source_name": record.get("source_name", ""),
                        "source_tier": record.get("source_tier", 1),
                        "url": record.get("url", ""),
                        "opportunity_id": record.get("opportunity_id", ""),
                        "canonical_record_id": record.get("canonical_record_id") or record.get("notice_id") or record.get("opportunity_id", ""),
                        "canonical_record_id_type": record.get("canonical_record_id_type", "notice_id" if record.get("notice_id") else "opportunity_id"),
                        "notice_id": record.get("notice_id", ""),
                        "opportunity_class": record.get("opportunity_class", ""),
                        "bucket": record.get("bucket", ""),
                    }

    return {
        "status": "unresolved",
        "entry_resolution_mode": "unresolved",
        "report_entry_id": upper_entry if upper_entry != entry else "",
        "digest_date": "",
        "canonical_record_id": entry,
    }
