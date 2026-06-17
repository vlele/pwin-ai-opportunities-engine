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
from common.openai_reasoning import interpret_feedback
from common.paths import load_json, standard_procurement_paths, today_local_str, utc_now_iso, write_json
from capture.resolve_entry import resolve_entry
from feedback.learning import recompute_learning_preferences
from scan.run_scan import _fit_narrative_guidance, _keyword_matches, _normalized_text, _vendor_keywords


ENTRY_RE = re.compile(r"\b([AWESN]\d+)\b", re.IGNORECASE)
REASON_CODE_PATTERNS = (
    ("right_buyer", ("right buyer", "good buyer")),
    ("wrong_buyer", ("wrong buyer", "bad buyer")),
    ("right_work", ("right work", "good fit")),
    ("wrong_work", ("wrong work", "poor fit", "not a target fit")),
    ("too_small", ("too small",)),
    ("too_large", ("too large",)),
    ("wrong_location", ("wrong location",)),
    ("wrong_vehicle", ("wrong vehicle",)),
    ("wrong_timing", ("wrong timing",)),
    ("teaming_only", ("teaming only",)),
    ("subcontract_only", ("subcontract only", "sub only")),
    ("bad_eligibility", ("bad eligibility", "wrong eligibility")),
    ("unclear_evidence", ("unclear evidence",)),
)


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


def extract_reason_codes(text: str) -> list[str]:
    lower = text.lower()
    codes: list[str] = []
    for code, patterns in REASON_CODE_PATTERNS:
        if any(pattern in lower for pattern in patterns) and code not in codes:
            codes.append(code)
    return codes


def _normalize_record_list(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("records", "opportunities", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _load_full_record(workspace: Path, resolved: dict) -> dict:
    digest_date = str(resolved.get("digest_date") or "").strip()
    if not digest_date:
        return {}
    opportunities_path = standard_procurement_paths(workspace, digest_date)["opportunities"]
    records = _normalize_record_list(load_json(opportunities_path, default=[]))
    for record in records:
        candidates = {
            str(record.get("canonical_record_id", "")),
            str(record.get("notice_id", "")),
            str(record.get("opportunity_id", "")),
            str(record.get("title", "")),
            str(record.get("url", "")),
        }
        resolved_candidates = {
            str(resolved.get("canonical_record_id", "")),
            str(resolved.get("notice_id", "")),
            str(resolved.get("opportunity_id", "")),
            str(resolved.get("title", "")),
            str(resolved.get("url", "")),
        }
        if candidates & resolved_candidates:
            return record
    return {}


def _matched_keywords(record: dict, vendor_profile: dict) -> list[str]:
    text = _normalized_text(f"{record.get('title', '')} {record.get('summary', '')}")
    token_set = set(text.split())
    fit_guidance = _fit_narrative_guidance(vendor_profile)
    candidate_keywords = _vendor_keywords(vendor_profile)
    candidate_keywords.extend(str(item) for item in fit_guidance.get("positive_terms", []))
    candidate_keywords.extend(str(item) for item in fit_guidance.get("negative_terms", []))
    matched = []
    for keyword in candidate_keywords:
        if keyword and _keyword_matches(keyword, text, token_set) and keyword not in matched:
            matched.append(keyword)
    return matched


def _resolved_record_payload(full_record: dict, resolved: dict) -> dict:
    source = full_record or resolved
    return {
        "opportunity_id": source.get("opportunity_id", ""),
        "source_id": source.get("source_id", ""),
        "source_name": source.get("source_name", ""),
        "source_tier": source.get("source_tier", 1),
        "title": source.get("title", ""),
        "url": source.get("url", ""),
        "buyer": source.get("buyer", ""),
        "opportunity_class": source.get("opportunity_class", ""),
        "notice_type": source.get("notice_type", ""),
        "posted_date": source.get("posted_date", ""),
        "due_date": source.get("due_date", ""),
        "naics": source.get("naics", []) if isinstance(source.get("naics"), list) else [],
        "set_aside": source.get("set_aside", ""),
        "match_score": int(source.get("match_score") or 0),
        "confidence_score": int(source.get("confidence_score") or 0),
        "screening_status": source.get("screening_status", source.get("bucket", "")),
        "bucket": source.get("bucket", ""),
    }


def _feedback_hydrated_text(full_record: dict, resolved: dict) -> str:
    return str(
        full_record.get("solicitation_text")
        or full_record.get("notice_text")
        or full_record.get("summary")
        or resolved.get("summary")
        or ""
    ).strip()


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
    reason_codes = extract_reason_codes(user_text)
    digest_map, digest_map_path = latest_digest_entry_map(workspace)
    resolved = resolve_entry(workspace, entry_id or user_text)
    full_record = _load_full_record(workspace, resolved)
    resolved_record = _resolved_record_payload(full_record, resolved)
    is_resolved = resolved.get("status") == "resolved"
    display_entry_id = entry_id or (str(resolved.get("report_entry_id", "") or "").strip() if is_resolved else "")
    report_bucket = str(resolved.get("bucket", "") or "")
    digest_date = resolved.get("digest_date") or digest_map.get("digest_date", today_local_str())
    vendor_profile = load_json(workspace / "procurement" / "vendor-profile.json", default={})
    hydrated_text = _feedback_hydrated_text(full_record, resolved)
    prior_scan_fit = full_record.get("semantic_fit", {}) if isinstance(full_record.get("semantic_fit"), dict) else {}
    learning_block = load_json(workspace / "procurement" / "preferences.json", default={}).get("learning", {})
    learned_semantic_preferences = (
        learning_block.get("semantic_applied_preferences", {})
        if isinstance(learning_block, dict) and isinstance(learning_block.get("semantic_applied_preferences"), dict)
        else {}
    )
    matched_naics = []
    if isinstance(resolved_record.get("naics"), list):
        matched_naics = [str(item).strip() for item in resolved_record.get("naics", []) if str(item).strip()]
    opportunity_class = str(resolved_record.get("opportunity_class", "") or "").strip()
    matched_keywords = _matched_keywords(full_record, vendor_profile) if full_record else []
    semantic_feedback = interpret_feedback(
        user_text=user_text,
        feedback_kind=feedback_kind,
        reward=reward,
        record=full_record or resolved_record,
        hydrated_text=hydrated_text,
        vendor_profile=vendor_profile,
        prior_scan_fit=prior_scan_fit,
        learned_semantic_preferences=learned_semantic_preferences,
    )
    semantic_entities = (
        semantic_feedback.get("resolved_entities", {})
        if isinstance(semantic_feedback, dict) and isinstance(semantic_feedback.get("resolved_entities"), dict)
        else {}
    )
    event = {
        "timestamp": utc_now_iso(),
        "digest_date": digest_date,
        "digest_path": digest_map.get("digest_path", ""),
        "resolved_from_latest_digest": is_resolved,
        "report_entry_id": display_entry_id,
        "report_bucket": report_bucket,
        "user_id": "",
        "user_utterance": user_text,
        "feedback": feedback_kind,
        "reward": reward,
        "free_text": user_text,
        "reason_codes": reason_codes,
        "resolved_record": resolved_record,
        "resolved_entities": {
            "matched_keywords": matched_keywords,
            "matched_buyers": [resolved_record.get("buyer")] if resolved_record.get("buyer") else [],
            "matched_naics": matched_naics,
            "matched_opportunity_classes": [opportunity_class] if opportunity_class else [],
            "matched_award_size_band": [],
            "matched_location_preferences": [],
            "matched_teaming_or_vehicle_signals": [],
            "semantic_positive_facets": semantic_entities.get("semantic_positive_facets", []),
            "semantic_negative_facets": semantic_entities.get("semantic_negative_facets", []),
            "mission_domains": semantic_entities.get("mission_domains", []),
            "delivery_models": semantic_entities.get("delivery_models", []),
            "contract_postures": semantic_entities.get("contract_postures", []),
            "competitive_shapes": semantic_entities.get("competitive_shapes", []),
            "set_aside_signals": semantic_entities.get("set_aside_signals", []),
            "vehicle_signals": semantic_entities.get("vehicle_signals", []),
            "teaming_postures": semantic_entities.get("teaming_postures", []),
        },
        "semantic_feedback": semantic_feedback or {},
        "effect": {
            "hard_filters_added": ["grants"] if "never show grants" in user_text.lower() else [],
            "hard_filters_removed": [],
            "soft_preferences_upweighted": [resolved_record.get("buyer")] if reward > 0 and resolved_record.get("buyer") else [],
            "soft_preferences_downweighted": [resolved_record.get("buyer")] if reward < 0 and resolved_record.get("buyer") else [],
            "memory_updates": [],
            "preference_file_updates": [],
            "notes": [
                f"Resolved using {digest_map_path.as_posix()}" if digest_map_path else "No digest-entry-map found",
                f"Entry resolution mode: {resolved.get('entry_resolution_mode', 'unknown')}",
            ],
        },
    }

    feedback_path = workspace / "procurement" / "feedback-events.jsonl"
    append_jsonl(feedback_path, event)
    learning_summary = recompute_learning_preferences(workspace)

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
        "report_entry_id": display_entry_id,
        "resolved": is_resolved,
        "reason_codes": reason_codes,
        "learning_summary": learning_summary,
        "semantic_feedback_summary": (
            semantic_feedback.get("reasoning_summary", "")
            if isinstance(semantic_feedback, dict)
            else ""
        ),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
