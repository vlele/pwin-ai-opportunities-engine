from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.jsonl import append_jsonl
from common.paths import load_json, today_local_str, utc_now_iso, write_json


ENTRY_RE = re.compile(r"\b([AWNS]\d+)\b", re.IGNORECASE)


def latest_digest_entry_map(workspace: Path) -> tuple[dict, Path | None]:
    maps_dir = workspace / "procurement" / "digest-entry-map"
    if not maps_dir.exists():
        return {}, None
    maps = sorted(path for path in maps_dir.glob("*.json") if path.is_file())
    if not maps:
        return {}, None
    latest = maps[-1]
    return load_json(latest, default={}), latest


def detect_feedback_kind(text: str) -> tuple[str, int]:
    lower = text.lower()
    if "never show" in lower or "hide " in lower:
        return "hard_exclude", -3
    if "pursue" in lower:
        return "pursue", 2
    if "more like" in lower:
        return "more_like_this", 1
    if "less like" in lower:
        return "less_like_this", -1
    if "dislike" in lower:
        return "dislike", -1
    if "watch" in lower:
        return "watch", 0
    return "like", 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    user_text = args.text.strip()
    entry_match = ENTRY_RE.search(user_text)
    entry_id = entry_match.group(1).upper() if entry_match else ""
    feedback_kind, reward = detect_feedback_kind(user_text)
    digest_map, digest_map_path = latest_digest_entry_map(workspace)
    resolved_record = {}
    report_bucket = ""

    for entry in digest_map.get("entries", []):
        if entry.get("entry_id") == entry_id:
            resolved_record = entry
            report_bucket = entry.get("bucket", "")
            break

    digest_date = digest_map.get("digest_date", today_local_str())
    event = {
        "timestamp": utc_now_iso(),
        "digest_date": digest_date,
        "digest_path": digest_map.get("digest_path", ""),
        "resolved_from_latest_digest": bool(resolved_record),
        "report_entry_id": entry_id,
        "report_bucket": report_bucket,
        "user_id": "",
        "user_utterance": user_text,
        "feedback": feedback_kind,
        "reward": reward,
        "free_text": user_text,
        "reason_codes": [],
        "resolved_record": resolved_record,
        "resolved_entities": {
            "matched_keywords": [],
            "matched_buyers": [resolved_record.get("buyer")] if resolved_record.get("buyer") else [],
            "matched_naics": [],
            "matched_opportunity_classes": [resolved_record.get("opportunity_class")] if resolved_record.get("opportunity_class") else [],
            "matched_award_size_band": [],
            "matched_location_preferences": [],
            "matched_teaming_or_vehicle_signals": [],
        },
        "effect": {
            "hard_filters_added": ["grants"] if "never show grants" in user_text.lower() else [],
            "hard_filters_removed": [],
            "soft_preferences_upweighted": [resolved_record.get("buyer")] if reward > 0 and resolved_record.get("buyer") else [],
            "soft_preferences_downweighted": [resolved_record.get("buyer")] if reward < 0 and resolved_record.get("buyer") else [],
            "memory_updates": [],
            "preference_file_updates": [],
            "notes": [f"Resolved using {digest_map_path.as_posix()}" if digest_map_path else "No digest-entry-map found"],
        },
    }

    feedback_path = workspace / "procurement" / "feedback-events.jsonl"
    append_jsonl(feedback_path, event)

    preferences_path = workspace / "procurement" / "preferences.json"
    preferences = load_json(preferences_path, default={})
    preferences.setdefault("learning", {})
    preferences["last_updated"] = utc_now_iso()
    preferences["learning"]["last_learning_update"] = utc_now_iso()
    write_json(preferences_path, preferences)

    result = {
        "status": "OK",
        "feedback_path": feedback_path.as_posix(),
        "preferences_path": preferences_path.as_posix(),
        "feedback": feedback_kind,
        "report_entry_id": entry_id,
        "resolved": bool(resolved_record),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

