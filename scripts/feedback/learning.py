from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.jsonl import read_jsonl
from common.paths import load_json, utc_now_iso, write_json


DIMENSION_FIELDS = {
    "buyers": "matched_buyers",
    "keywords": "matched_keywords",
    "naics": "matched_naics",
    "opportunity_classes": "matched_opportunity_classes",
}
PROMOTION_EPSILON = 0.05

HARD_FILTER_KEYS = (
    "exclude_keywords",
    "exclude_buyers",
    "exclude_states",
    "exclude_opportunity_classes",
    "exclude_set_asides",
    "exclude_naics",
    "exclude_contract_types",
)

SOFT_PREFERENCE_KEYS = (
    "positive_keywords",
    "negative_keywords",
    "preferred_buyers",
    "preferred_states",
    "preferred_set_asides",
    "preferred_opportunity_classes",
    "preferred_naics",
    "preferred_contract_types",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, "", "N/A"):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _decayed_reward(event: dict[str, Any], decay_rate_monthly: float, now_utc: datetime) -> float:
    reward = float(event.get("reward") or 0)
    timestamp = _parse_timestamp(event.get("timestamp"))
    if timestamp is None:
        return reward
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now_utc - timestamp.astimezone(timezone.utc)).total_seconds() / 86400.0)
    age_months = age_days / 30.0
    if decay_rate_monthly <= 0:
        return reward
    decay_factor = max(0.0, (1.0 - decay_rate_monthly) ** age_months)
    return reward * decay_factor


def _unique_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _safe_learning_block(preferences: dict[str, Any]) -> dict[str, Any]:
    learning = preferences.setdefault("learning", {})
    learning.setdefault("policy", "reinforcement_learning_style_explicit_feedback")
    learning.setdefault("soft_promotion_threshold", 3)
    learning.setdefault("decay_rate_monthly", 0.05)
    learning.setdefault("reward_values", {})
    learning.setdefault("notes", [])
    return learning


def _score_rows(score_map: dict[str, float], count_map: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for value, score in score_map.items():
        rows.append(
            {
                "value": value,
                "score": round(score, 3),
                "event_count": count_map.get(value, 0),
            }
        )
    rows.sort(key=lambda item: (abs(float(item.get("score") or 0)), int(item.get("event_count") or 0), item.get("value", "")), reverse=True)
    return rows


def recompute_learning_preferences(workspace: Path) -> dict[str, Any]:
    procurement = workspace / "procurement"
    preferences_path = procurement / "preferences.json"
    feedback_path = procurement / "feedback-events.jsonl"

    preferences = load_json(preferences_path, default={})
    learning = _safe_learning_block(preferences)
    decay_rate = float(learning.get("decay_rate_monthly", 0.05) or 0.05)
    threshold = max(1.0, float(learning.get("soft_promotion_threshold", 3) or 3))
    now_utc = datetime.now(timezone.utc)
    events = read_jsonl(feedback_path)

    score_maps: dict[str, dict[str, float]] = {
        "buyers": defaultdict(float),
        "keywords": defaultdict(float),
        "naics": defaultdict(float),
        "opportunity_classes": defaultdict(float),
        "reason_codes": defaultdict(float),
    }
    count_maps: dict[str, dict[str, int]] = {
        "buyers": defaultdict(int),
        "keywords": defaultdict(int),
        "naics": defaultdict(int),
        "opportunity_classes": defaultdict(int),
        "reason_codes": defaultdict(int),
    }

    explicit_class_excludes: list[str] = []
    for event in events:
        weighted_reward = _decayed_reward(event, decay_rate, now_utc)
        resolved_entities = event.get("resolved_entities", {}) if isinstance(event.get("resolved_entities"), dict) else {}

        for dimension, field_name in DIMENSION_FIELDS.items():
            values = resolved_entities.get(field_name, [])
            if not isinstance(values, list):
                continue
            for value in _unique_strings(values):
                score_maps[dimension][value] += weighted_reward
                count_maps[dimension][value] += 1

        reason_codes = event.get("reason_codes", [])
        if isinstance(reason_codes, list):
            for code in _unique_strings(reason_codes):
                score_maps["reason_codes"][code] += weighted_reward
                count_maps["reason_codes"][code] += 1

        effect = event.get("effect", {}) if isinstance(event.get("effect"), dict) else {}
        hard_filters_added = effect.get("hard_filters_added", [])
        if isinstance(hard_filters_added, list):
            for item in _unique_strings(hard_filters_added):
                if item == "grants":
                    explicit_class_excludes.append(item)

    applied_hard_filters = {
        key: []
        for key in HARD_FILTER_KEYS
    }
    applied_soft_preferences = {
        key: []
        for key in SOFT_PREFERENCE_KEYS
    }

    for buyer, score in score_maps["buyers"].items():
        if score >= threshold - PROMOTION_EPSILON:
            applied_soft_preferences["preferred_buyers"].append(buyer)
        elif score <= -threshold + PROMOTION_EPSILON:
            applied_hard_filters["exclude_buyers"].append(buyer)

    for keyword, score in score_maps["keywords"].items():
        if score >= threshold - PROMOTION_EPSILON:
            applied_soft_preferences["positive_keywords"].append(keyword)
        elif score <= -threshold + PROMOTION_EPSILON:
            applied_soft_preferences["negative_keywords"].append(keyword)
            applied_hard_filters["exclude_keywords"].append(keyword)

    for naics_code, score in score_maps["naics"].items():
        if score >= threshold - PROMOTION_EPSILON:
            applied_soft_preferences["preferred_naics"].append(naics_code)
        elif score <= -threshold + PROMOTION_EPSILON:
            applied_hard_filters["exclude_naics"].append(naics_code)

    for opportunity_class, score in score_maps["opportunity_classes"].items():
        if score >= threshold - PROMOTION_EPSILON:
            applied_soft_preferences["preferred_opportunity_classes"].append(opportunity_class)
        elif score <= -threshold + PROMOTION_EPSILON:
            applied_hard_filters["exclude_opportunity_classes"].append(opportunity_class)

    for item in explicit_class_excludes:
        if item not in applied_hard_filters["exclude_opportunity_classes"]:
            applied_hard_filters["exclude_opportunity_classes"].append(item)

    applied_hard_filters = {key: _unique_strings(value) for key, value in applied_hard_filters.items()}
    applied_soft_preferences = {key: _unique_strings(value) for key, value in applied_soft_preferences.items()}

    notes: list[str] = []
    if applied_soft_preferences["preferred_buyers"]:
        notes.append(f"Preferred buyers learned from feedback: {', '.join(applied_soft_preferences['preferred_buyers'][:3])}")
    if applied_soft_preferences["positive_keywords"]:
        notes.append(f"Positive keywords learned from feedback: {', '.join(applied_soft_preferences['positive_keywords'][:4])}")
    if applied_soft_preferences["preferred_naics"]:
        notes.append(f"Preferred NAICS learned from feedback: {', '.join(applied_soft_preferences['preferred_naics'][:4])}")
    if applied_soft_preferences["preferred_opportunity_classes"]:
        notes.append(
            "Preferred opportunity classes learned from feedback: "
            + ", ".join(applied_soft_preferences["preferred_opportunity_classes"][:4])
        )
    if applied_hard_filters["exclude_buyers"]:
        notes.append(f"Buyer exclusions learned from feedback: {', '.join(applied_hard_filters['exclude_buyers'][:3])}")
    if applied_soft_preferences["negative_keywords"]:
        notes.append(f"Negative keywords learned from feedback: {', '.join(applied_soft_preferences['negative_keywords'][:4])}")
    if applied_hard_filters["exclude_opportunity_classes"]:
        notes.append(
            "Opportunity-class exclusions learned from feedback: "
            + ", ".join(applied_hard_filters["exclude_opportunity_classes"][:4])
        )
    if not notes and events:
        notes.append("Feedback ledger updated; no repeated signals have crossed the promotion threshold yet.")
    if not events:
        notes.append("No feedback events logged yet.")

    learning["signal_scores"] = {
        dimension: {value: round(score, 3) for value, score in values.items()}
        for dimension, values in score_maps.items()
    }
    learning["signal_event_counts"] = {
        dimension: dict(values)
        for dimension, values in count_maps.items()
    }
    learning["aggregates"] = {
        dimension: _score_rows(score_maps[dimension], count_maps[dimension])
        for dimension in score_maps
    }
    learning["applied_preferences"] = {
        "generated_at": utc_now_iso(),
        "hard_filters": applied_hard_filters,
        "soft_preferences": applied_soft_preferences,
        "notes": notes,
    }
    learning["last_learning_update"] = utc_now_iso()

    write_json(preferences_path, preferences)
    return {
        "feedback_event_count": len(events),
        "threshold": threshold,
        "applied_preferences": learning["applied_preferences"],
    }
