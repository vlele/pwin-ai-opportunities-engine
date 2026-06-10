from __future__ import annotations

import argparse
import json
from datetime import date, datetime
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.openai_reasoning import assess_scan_fit
from common.evidence_model import (
    build_scan_official_evidence_model,
    evidence_model_scan_notes,
    merge_evidence_models,
)
from common.paths import load_json, today_local_str, utc_now_iso, write_json
from common.runtime import NOT_IMPLEMENTED_IN_BUNDLE_STATUS
from common.commercial_intel import COMMERCIAL_INTEL_SOURCE_IDS, enrich_scan_records
from common.source_registry import (
    enabled_sources_summary,
    filter_sources_for_policy,
    get_enabled_sources,
    refresh_runtime_registry,
    sources_summary,
)
from scan.build_digest_entry_map import build_digest_entry_map
from scan.render_digest import render_digest_and_report
from scan.sam_hydrate import hydrate_sam_notice
from scan.sam_search import search_sam_opportunities
from scan.usaspending_enrich import post_award_search


NON_ACTIONABLE_NOTICE_CATEGORIES = {
    "award_notice",
    "contract_award",
    "justification_and_approval",
    "j_and_a_posting",
    "fair_opportunity_exception",
    "sole_source_notice",
    "notice_of_intent_to_sole_source",
    "informational_update",
    "update_only_notice",
    "sources_sought_only",
    "rfi_only",
    "industry_day_only",
    "vendor_library_notice",
    "draft_solicitation",
    "cancelled_notice",
}

ALWAYS_SUPPRESSED_NOTICE_CATEGORIES = {
    "award_notice",
    "contract_award",
    "justification_and_approval",
    "j_and_a_posting",
    "fair_opportunity_exception",
    "notice_of_intent_notice",
    "sole_source_notice",
    "notice_of_intent_to_sole_source",
    "vendor_library_notice",
    "cancelled_notice",
}

WATCHLIST_ELIGIBLE_NOTICE_CATEGORIES = {
    "draft_solicitation",
    "presolicitation_notice",
    "sources_sought_only",
    "rfi_only",
    "industry_day_only",
}

INFORMATIONAL_NOTICE_CATEGORIES = {
    "informational_update",
    "update_only_notice",
}

NOTICE_CATEGORY_LABELS = {
    "award_notice": "award notice",
    "contract_award": "contract award",
    "justification_and_approval": "justification and approval posting",
    "j_and_a_posting": "J&A posting",
    "fair_opportunity_exception": "fair opportunity exception",
    "notice_of_intent_notice": "notice of intent",
    "sole_source_notice": "sole-source notice",
    "notice_of_intent_to_sole_source": "intent-to-sole-source notice",
    "informational_update": "informational update",
    "update_only_notice": "update-only notice",
    "sources_sought_only": "sources sought notice",
    "rfi_only": "request for information",
    "industry_day_only": "industry day notice",
    "vendor_library_notice": "vendor library notice",
    "draft_solicitation": "draft solicitation",
    "presolicitation_notice": "presolicitation notice",
    "cancelled_notice": "cancelled notice",
}

FIT_NARRATIVE_POSITIVE_CUES = (
    "prioritize",
    "prefer",
    "focus on",
    "target",
    "pursue",
    "favor",
    "favour",
    "look for",
)

FIT_NARRATIVE_NEGATIVE_CUES = (
    "avoid",
    "deprioritize",
    "steer away from",
    "exclude",
    "not fit for",
    "do not pursue",
    "do not target",
)

FIT_NARRATIVE_FILLER_PREFIXES = (
    "and ",
    "or ",
    "where ",
    "opportunities where ",
    "work where ",
)

FIT_NARRATIVE_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "can",
    "credibly",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "our",
    "over",
    "services",
    "the",
    "their",
    "to",
    "where",
    "with",
    "work",
}

GENERIC_LOW_SIGNAL_FIT_TERMS = {
    "support",
    "services",
    "service",
    "solution",
    "solutions",
    "system",
    "systems",
}

SEMANTIC_REASONING_MAX_RECORDS_PER_RUN = 12
SEMANTIC_REASONING_MIN_SCORE = 55


def parse_horizon(raw: str) -> tuple[int, int]:
    cleaned = raw.lower().replace("days", "").replace("day", "").replace("to", "-").replace(" ", "")
    if "-" in cleaned:
        left, right = cleaned.split("-", 1)
        return int(left), int(right)
    value = int(cleaned)
    return 0, value


def ensure_preferences(bundle_root: Path, workspace: Path, horizon: str) -> Path:
    procurement = workspace / "procurement"
    preferences_path = procurement / "preferences.json"
    template_path = bundle_root / "templates" / "preferences.template.json"
    preferences = load_json(preferences_path, default=load_json(template_path, default={}))
    min_days, max_days = parse_horizon(horizon)
    retrieval_max_days = max(120, max_days)
    preferences.setdefault("time_horizon", {})
    preferences["time_horizon"]["mode"] = "timing_window_model_v2"
    preferences["time_horizon"]["requested_min_days_from_today"] = min_days
    preferences["time_horizon"]["requested_max_days_from_today"] = max_days
    preferences["time_horizon"]["min_days_from_today"] = 0
    preferences["time_horizon"]["max_days_from_today"] = retrieval_max_days
    preferences["time_horizon"]["retrieval_min_days_from_today"] = 0
    preferences["time_horizon"]["retrieval_max_days_from_today"] = retrieval_max_days
    preferences["time_horizon"]["urgent_window_max_days"] = 14
    preferences["time_horizon"]["active_window_min_days"] = 15
    preferences["time_horizon"]["active_window_max_days"] = 45
    preferences["time_horizon"]["watchlist_window_min_days"] = 46
    preferences["time_horizon"]["watchlist_window_max_days"] = retrieval_max_days
    preferences["time_horizon"]["last_override_source"] = "scan command"
    preferences["time_horizon"]["strict_due_date_filter_before_bucketing"] = False
    preferences["time_horizon"]["allow_missing_due_date_on_shortlist"] = False
    preferences.setdefault("screening", {})
    preferences["screening"]["allow_watchlist_for_non_actionable_notices"] = True
    preferences.setdefault("confidence_thresholds", {})
    preferences["confidence_thresholds"]["watchlist_min"] = int(
        preferences["confidence_thresholds"].get("watchlist_min", preferences["confidence_thresholds"].get("near_miss_min", 45)) or 45
    )
    preferences.setdefault("delivery", {})
    preferences["delivery"]["max_watchlist"] = int(preferences["delivery"].get("max_watchlist", preferences["delivery"].get("max_near_misses", 3)) or 3)
    write_json(preferences_path, preferences)
    return preferences_path


def ensure_today_artifacts(workspace: Path, date_str: str) -> tuple[Path, Path]:
    procurement = workspace / "procurement"
    opportunities_path = procurement / "opportunities" / f"{date_str}.json"
    explanations_path = procurement / "explanations" / f"{date_str}.json"
    if not opportunities_path.exists():
        write_json(opportunities_path, [])
    if not explanations_path.exists():
        write_json(explanations_path, [])
    return opportunities_path, explanations_path


def _today_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _parse_any_date(value: Any) -> date | None:
    if value in (None, "", "N/A"):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _vendor_name(profile: dict[str, Any]) -> str:
    company = profile.get("company", {}) if isinstance(profile.get("company"), dict) else {}
    return profile.get("vendor_name") or profile.get("name") or company.get("name") or "Vendor"


def _unique_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _applied_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
    learning = preferences.get("learning", {}) if isinstance(preferences.get("learning"), dict) else {}
    applied = learning.get("applied_preferences", {})
    return applied if isinstance(applied, dict) else {}


def _semantic_applied_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
    learning = preferences.get("learning", {}) if isinstance(preferences.get("learning"), dict) else {}
    applied = learning.get("semantic_applied_preferences", {})
    return applied if isinstance(applied, dict) else {}


def _merged_preference_values(preferences: dict[str, Any], section: str, key: str) -> list[str]:
    values: list[Any] = []
    base_section = preferences.get(section, {}) if isinstance(preferences.get(section), dict) else {}
    if isinstance(base_section.get(key), list):
        values.extend(base_section.get(key, []))
    applied_section = _applied_preferences(preferences).get(section, {})
    if isinstance(applied_section, dict) and isinstance(applied_section.get(key), list):
        values.extend(applied_section.get(key, []))
    return _unique_strings(values)


def _learning_signal_scores(preferences: dict[str, Any], dimension: str) -> dict[str, float]:
    learning = preferences.get("learning", {}) if isinstance(preferences.get("learning"), dict) else {}
    signal_scores = learning.get("signal_scores", {})
    if not isinstance(signal_scores, dict):
        return {}
    values = signal_scores.get(dimension, {})
    if not isinstance(values, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in values.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _should_run_semantic_reasoning(
    *,
    match_score: int,
    bucket_override: str | None,
    timing_band: str,
    fit_context: dict[str, Any],
    hydrated_text: str | None,
) -> bool:
    if bucket_override == "suppressed":
        return False
    if match_score < SEMANTIC_REASONING_MIN_SCORE:
        return False
    if timing_band not in {"urgent", "active", "watchlist"}:
        return False
    if not (hydrated_text or fit_context.get("fit_narrative_positive_hits") or fit_context.get("keyword_hit_count", 0) >= 2):
        return False
    return True


def _semantic_feedback_adjustment(semantic_fit: dict[str, Any] | None, preferences: dict[str, Any]) -> tuple[int, list[str]]:
    if not isinstance(semantic_fit, dict):
        return 0, []

    points = 0
    reasons: list[str] = []
    applied = _semantic_applied_preferences(preferences)

    fit_assessment = str(semantic_fit.get("fit_assessment", "")).strip().lower()
    posture = str(semantic_fit.get("credible_posture", "")).strip().lower()
    reasoning_summary = str(semantic_fit.get("reasoning_summary", "") or "").strip()
    semantic_facets = semantic_fit.get("semantic_facets", {}) if isinstance(semantic_fit.get("semantic_facets"), dict) else {}

    if fit_assessment == "strong_fit":
        points += 4
    elif fit_assessment == "adjacent_fit":
        points += 1
    elif fit_assessment == "weak_fit":
        points -= 3
    elif fit_assessment == "misleading_keyword_match":
        points -= 6

    if posture == "prime":
        points += 2
    elif posture == "team":
        points += 0
    elif posture == "monitor":
        points -= 1
    elif posture == "suppress":
        points -= 4

    mission_domains = set(str(item).strip() for item in semantic_facets.get("mission_domains", []) if str(item).strip())
    delivery_models = set(str(item).strip() for item in semantic_facets.get("delivery_models", []) if str(item).strip())
    positive_facets = set(str(item).strip() for item in semantic_facets.get("positive_fit_facets", []) if str(item).strip())
    negative_facets = set(str(item).strip() for item in semantic_facets.get("negative_fit_facets", []) if str(item).strip())
    competitive_shapes = set(str(item).strip() for item in semantic_fit.get("risk_flags", []) if str(item).strip())

    mission_prefer = mission_domains & set(applied.get("prefer_mission_domains", []))
    mission_avoid = mission_domains & set(applied.get("avoid_mission_domains", []))
    delivery_prefer = delivery_models & set(applied.get("prefer_delivery_models", []))
    delivery_avoid = delivery_models & set(applied.get("avoid_delivery_models", []))
    facet_prefer = positive_facets & set(applied.get("prefer_semantic_facets", []))
    facet_avoid = negative_facets & set(applied.get("avoid_semantic_facets", []))
    competitive_avoid = competitive_shapes & {"vehicle_access_unknown", "incumbent_continuity_risk"} & set(applied.get("avoid_competitive_shapes", []))

    if mission_prefer:
        points += 3
        reasons.append(f"Learned mission-domain preference supports this fit: {', '.join(sorted(mission_prefer)[:2])}.")
    if mission_avoid:
        points -= 4
        reasons.append(f"Learned mission-domain caution applies here: {', '.join(sorted(mission_avoid)[:2])}.")
    if delivery_prefer:
        points += 3
        reasons.append(f"Learned delivery-model preference supports this fit: {', '.join(sorted(delivery_prefer)[:2])}.")
    if delivery_avoid:
        points -= 5
        reasons.append(f"Learned delivery-model caution applies here: {', '.join(sorted(delivery_avoid)[:2])}.")
    if facet_prefer:
        points += 2
        reasons.append(f"Learned work-pattern preference supports this fit: {', '.join(sorted(facet_prefer)[:2])}.")
    if facet_avoid:
        points -= 5
        reasons.append(f"Learned work-pattern caution applies here: {', '.join(sorted(facet_avoid)[:2])}.")
    if competitive_avoid:
        points -= 2
        reasons.append(f"Learned competitive caution applies here: {', '.join(sorted(competitive_avoid)[:2])}.")

    if reasoning_summary:
        if points >= 2:
            reasons.insert(0, f"Semantic fit check: {reasoning_summary}")
        elif points <= -2:
            reasons.insert(0, f"Semantic fit caution: {reasoning_summary}")

    return max(-10, min(10, points)), reasons[:3]


def _semantic_audit_record(
    *,
    semantic_fit: dict[str, Any] | None,
    score_before: int,
    score_after: int,
    bucket_before: str,
    bucket_after: str,
    guidance_bucket: str | None,
    reasoning_attempted: bool,
) -> dict[str, Any]:
    fit = semantic_fit if isinstance(semantic_fit, dict) else {}
    fit_assessment = str(fit.get("fit_assessment", "") or "").strip()
    posture = str(fit.get("credible_posture", "") or "").strip()
    reasoning_source = str(fit.get("reasoning_source", "") or "").strip()
    model_name = str(fit.get("model_name", "") or "").strip()
    score_delta = int(score_after) - int(score_before)
    return {
        "reasoning_attempted": reasoning_attempted,
        "reasoning_source": reasoning_source or ("not_run" if not reasoning_attempted else "heuristic_fallback"),
        "model_name": model_name,
        "score_before_semantic": score_before,
        "score_after_semantic": score_after,
        "score_delta": score_delta,
        "bucket_before_semantic": bucket_before,
        "bucket_after_semantic": bucket_after,
        "guidance_bucket": guidance_bucket or "",
        "fit_assessment": fit_assessment,
        "credible_posture": posture,
        "ranking_or_posture_changed": bool(score_delta or bucket_before != bucket_after or posture),
        "semantic_reasons_for": fit.get("why_it_fits", []) if isinstance(fit.get("why_it_fits"), list) else [],
        "semantic_reasons_against": fit.get("why_it_does_not_fit", []) if isinstance(fit.get("why_it_does_not_fit"), list) else [],
        "reasoning_summary": str(fit.get("reasoning_summary", "") or "").strip(),
    }


def _vendor_keywords(profile: dict[str, Any], preferences: dict[str, Any] | None = None) -> list[str]:
    keywords: list[str] = []
    for item in profile.get("core_competencies", []):
        if isinstance(item, dict):
            value = item.get("name") or item.get("summary")
        else:
            value = item
        if isinstance(value, str) and value.strip():
            keywords.append(value.strip().lower())
    other_tags = profile.get("other_taxonomy_tags", {}) if isinstance(profile.get("other_taxonomy_tags"), dict) else {}
    for item in other_tags.get("keywords", []):
        if isinstance(item, str) and item.strip():
            keywords.append(item.strip().lower())
    if preferences:
        for item in _merged_preference_values(preferences, "soft_preferences", "positive_keywords"):
            keywords.append(item.strip().lower())
    return sorted(dict.fromkeys(keywords))


def _vendor_negative_keywords(profile: dict[str, Any], preferences: dict[str, Any] | None = None) -> list[str]:
    keywords: list[str] = []
    other_tags = profile.get("other_taxonomy_tags", {}) if isinstance(profile.get("other_taxonomy_tags"), dict) else {}
    for item in other_tags.get("negative_keywords", []):
        if isinstance(item, str) and item.strip():
            keywords.append(item.strip().lower())
    if preferences:
        for item in _merged_preference_values(preferences, "soft_preferences", "negative_keywords"):
            keywords.append(item.strip().lower())
    return sorted(dict.fromkeys(keywords))


def _vendor_naics_by_bucket(profile: dict[str, Any], bucket: str) -> list[str]:
    naics = profile.get("naics", {}) if isinstance(profile.get("naics"), dict) else {}
    values: list[str] = []
    for item in naics.get(bucket, []):
        if isinstance(item, dict):
            code = item.get("code") or item.get("naics") or item.get("id")
        else:
            code = item
        code_text = str(code).strip() if code is not None else ""
        if code_text:
            values.append(code_text)
    return values


def _vendor_naics(profile: dict[str, Any], preferences: dict[str, Any] | None = None) -> list[str]:
    values: list[str] = []
    for bucket in ("confirmed", "candidates"):
        values.extend(_vendor_naics_by_bucket(profile, bucket))
    if preferences:
        values.extend(_merged_preference_values(preferences, "soft_preferences", "preferred_naics"))
    deduped = []
    for code in values:
        if code not in deduped:
            deduped.append(code)
    excluded = set(_merged_preference_values(preferences or {}, "hard_filters", "exclude_naics"))
    return [code for code in deduped if code not in excluded][:5]


def _vendor_fit_narrative(profile: dict[str, Any]) -> str:
    value = profile.get("fit_narrative", "")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " ".join(parts)
    return ""


def _split_fit_narrative_clauses(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"[.!?\n;]+", text) if segment.strip()]


def _split_fit_narrative_terms(text: str) -> list[str]:
    parts: list[str] = []
    for segment in re.split(r"[,\n;]+", text):
        cleaned = segment.strip()
        for prefix in FIT_NARRATIVE_FILLER_PREFIXES:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
        cleaned = _normalized_text(cleaned)
        if not cleaned:
            continue
        parts.append(cleaned)
    deduped: list[str] = []
    for part in parts:
        if part and part not in deduped:
            deduped.append(part)
    return deduped


def _fit_narrative_guidance(profile: dict[str, Any]) -> dict[str, Any]:
    narrative = _vendor_fit_narrative(profile)
    if not narrative:
        return {
            "enabled": False,
            "narrative": "",
            "positive_terms": [],
            "negative_terms": [],
        }

    positive_terms: list[str] = []
    negative_terms: list[str] = []
    for clause in _split_fit_narrative_clauses(narrative):
        normalized_clause = _normalized_text(clause)
        if not normalized_clause:
            continue

        contrast_match = re.search(
            r"(?:prefer|prioritize|focus on|target|pursue|favor|favour|look for)\s+(.+?)\s+(?:over|rather than|instead of)\s+(.+)",
            clause,
            flags=re.IGNORECASE,
        )
        if contrast_match:
            positive_terms.extend(_split_fit_narrative_terms(contrast_match.group(1)))
            negative_terms.extend(_split_fit_narrative_terms(contrast_match.group(2)))
            continue

        for cue in FIT_NARRATIVE_NEGATIVE_CUES:
            if cue in normalized_clause:
                negative_terms.extend(_split_fit_narrative_terms(re.split(cue, clause, maxsplit=1, flags=re.IGNORECASE)[1]))
                break

        for cue in FIT_NARRATIVE_POSITIVE_CUES:
            if cue in normalized_clause:
                positive_terms.extend(_split_fit_narrative_terms(re.split(cue, clause, maxsplit=1, flags=re.IGNORECASE)[1]))
                break

    return {
        "enabled": True,
        "narrative": narrative,
        "positive_terms": sorted(dict.fromkeys(term for term in positive_terms if term)),
        "negative_terms": sorted(dict.fromkeys(term for term in negative_terms if term)),
    }


def _fit_term_tokens(term: str) -> list[str]:
    tokens: list[str] = []
    for token in _normalized_text(term).split():
        if len(token) <= 2 or token in FIT_NARRATIVE_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _is_low_signal_fit_term(term: str) -> bool:
    tokens = _fit_term_tokens(term)
    return len(tokens) == 1 and tokens[0] in GENERIC_LOW_SIGNAL_FIT_TERMS


def _token_forms(token: str) -> set[str]:
    forms = {token}
    if token.endswith("ies") and len(token) > 3:
        forms.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        forms.add(token[:-2])
    if token.endswith("s") and len(token) > 3:
        forms.add(token[:-1])
    return {form for form in forms if form}


def _fit_term_matches(term: str, normalized_text: str, token_set: set[str]) -> bool:
    normalized_term = _normalized_text(term)
    if not normalized_term:
        return False
    if f" {normalized_term} " in f" {normalized_text} ":
        return True

    tokens = _fit_term_tokens(normalized_term)
    if not tokens:
        return False
    if len(tokens) == 1:
        return bool(_token_forms(tokens[0]) & token_set)
    if len(tokens) > 5:
        return False

    matched = 0
    for token in tokens:
        if _token_forms(token) & token_set:
            matched += 1
    if len(tokens) <= 3:
        return matched == len(tokens)
    return matched >= len(tokens) - 1


def _fit_narrative_alignment(
    fit_guidance: dict[str, Any],
    normalized_text: str,
    token_set: set[str],
) -> tuple[int, list[str], dict[str, Any]]:
    if not fit_guidance.get("enabled"):
        return 0, [], {"positive_hits": [], "negative_hits": []}

    positive_terms = [str(term) for term in fit_guidance.get("positive_terms", []) if str(term).strip()]
    negative_terms = [str(term) for term in fit_guidance.get("negative_terms", []) if str(term).strip()]
    positive_hits = [term for term in positive_terms if _fit_term_matches(term, normalized_text, token_set)]
    negative_hits = [term for term in negative_terms if _fit_term_matches(term, normalized_text, token_set)]
    strong_positive_hits = [term for term in positive_hits if not _is_low_signal_fit_term(term)]
    low_signal_positive_hits = [term for term in positive_hits if _is_low_signal_fit_term(term)]

    points = 0
    reasons: list[str] = []
    if strong_positive_hits:
        weighted_points = 0
        for term in strong_positive_hits:
            weighted_points += 4 if len(_fit_term_tokens(term)) > 1 else 2
        points += min(12, weighted_points)
        reasons.append(f"Fit narrative alignment: {', '.join(strong_positive_hits[:3])}.")
    elif low_signal_positive_hits:
        reasons.append(f"Low-signal fit alignment only: {', '.join(low_signal_positive_hits[:3])}.")
    else:
        points -= 10
        reasons.append("Fit narrative did not surface a clear positive alignment.")

    if negative_hits:
        points -= min(18, 6 * len(negative_hits))
        reasons.append(f"Fit narrative caution: {', '.join(negative_hits[:3])}.")

    return points, reasons, {
        "positive_hits": strong_positive_hits,
        "low_signal_positive_hits": low_signal_positive_hits,
        "negative_hits": negative_hits,
    }


def _timing_settings(preferences: dict[str, Any]) -> dict[str, Any]:
    time_horizon = preferences.get("time_horizon", {}) if isinstance(preferences.get("time_horizon"), dict) else {}
    retrieval_max = int(time_horizon.get("retrieval_max_days_from_today", time_horizon.get("max_days_from_today", 120)) or 120)
    urgent_max = int(time_horizon.get("urgent_window_max_days", 14) or 14)
    active_max = int(time_horizon.get("active_window_max_days", 45) or 45)
    watchlist_max = int(time_horizon.get("watchlist_window_max_days", retrieval_max) or retrieval_max)
    return {
        "retrieval_min": int(time_horizon.get("retrieval_min_days_from_today", 0) or 0),
        "retrieval_max": max(retrieval_max, watchlist_max),
        "urgent_max": urgent_max,
        "active_max": max(active_max, urgent_max),
        "watchlist_max": max(watchlist_max, active_max),
        "allow_missing": bool(time_horizon.get("allow_missing_due_date_on_shortlist", False)),
        "only_open": bool(time_horizon.get("only_open_opportunities", True)),
    }


def _timing_band(due_date: date | None, today: date, preferences: dict[str, Any]) -> tuple[str, int | None]:
    if due_date is None:
        return "missing", None

    timing = _timing_settings(preferences)
    delta = (due_date - today).days
    if timing["only_open"] and delta < 0:
        return "expired", delta
    if delta < timing["retrieval_min"] or delta > timing["retrieval_max"]:
        return "out_of_window", delta
    if delta <= timing["urgent_max"]:
        return "urgent", delta
    if delta <= timing["active_max"]:
        return "active", delta
    return "watchlist", delta


def _timing_adjustment(timing_band: str) -> int:
    return {
        "urgent": 15,
        "active": 10,
        "watchlist": 5,
    }.get(timing_band, 0)


def _timing_reason(timing_band: str, days_until_due: int | None) -> str:
    if days_until_due is None:
        return ""
    if timing_band == "urgent":
        return f"Timing signal: due in {days_until_due} days (urgent bid window)."
    if timing_band == "active":
        return f"Timing signal: due in {days_until_due} days (active pursuit window)."
    if timing_band == "watchlist":
        return f"Timing signal: due in {days_until_due} days (watchlist / early shaping window)."
    return ""


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _keyword_matches(keyword: str, normalized_text: str, token_set: set[str]) -> bool:
    normalized_keyword = _normalized_text(keyword)
    if not normalized_keyword:
        return False
    pieces = normalized_keyword.split()
    if len(pieces) == 1:
        return pieces[0] in token_set
    return f" {normalized_keyword} " in f" {normalized_text} "


def _buyer_signal_score(record: dict[str, Any], preferences: dict[str, Any]) -> tuple[float, list[str]]:
    buyer_text = _normalized_text(record.get("buyer", ""))
    scores = _learning_signal_scores(preferences, "buyers")
    hits: list[str] = []
    total = 0.0
    for buyer, score in scores.items():
        normalized_buyer = _normalized_text(buyer)
        if normalized_buyer and normalized_buyer in buyer_text:
            hits.append(buyer)
            total += score
    return total, hits


def _keyword_signal_hits(normalized_text: str, token_set: set[str], preferences: dict[str, Any]) -> tuple[list[str], list[str]]:
    scores = _learning_signal_scores(preferences, "keywords")
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    for keyword, score in scores.items():
        if not _keyword_matches(keyword, normalized_text, token_set):
            continue
        if score > 0 and keyword not in positive_hits:
            positive_hits.append(keyword)
        if score < 0 and keyword not in negative_hits:
            negative_hits.append(keyword)
    return positive_hits, negative_hits


def _naics_signal_score(record: dict[str, Any], preferences: dict[str, Any]) -> tuple[float, list[str]]:
    record_codes = _record_naics_codes(record)
    scores = _learning_signal_scores(preferences, "naics")
    hits: list[str] = []
    total = 0.0
    for code in record_codes:
        if code in scores:
            hits.append(code)
            total += scores[code]
    return total, hits


def _opportunity_class_signal_score(record: dict[str, Any], preferences: dict[str, Any]) -> tuple[float, list[str]]:
    opportunity_class = str(record.get("opportunity_class", "") or "").strip()
    if not opportunity_class:
        return 0.0, []
    scores = _learning_signal_scores(preferences, "opportunity_classes")
    total = 0.0
    hits: list[str] = []
    normalized_class = _normalized_text(opportunity_class)
    for value, score in scores.items():
        if _normalized_text(value) == normalized_class:
            hits.append(value)
            total += score
    return total, hits


def _feedback_signal_adjustment(
    record: dict[str, Any],
    normalized_text: str,
    token_set: set[str],
    preferences: dict[str, Any],
) -> tuple[int, list[str]]:
    points = 0
    reasons: list[str] = []

    buyer_score, buyer_hits = _buyer_signal_score(record, preferences)
    if buyer_score > 0:
        points += min(6, int(round(buyer_score * 2)))
        reasons.append(f"Learned buyer preference from feedback: {', '.join(buyer_hits[:2])}.")
    elif buyer_score < 0:
        points -= min(6, int(round(abs(buyer_score) * 2)))
        reasons.append(f"Learned buyer caution from feedback: {', '.join(buyer_hits[:2])}.")

    positive_keyword_hits, negative_keyword_hits = _keyword_signal_hits(normalized_text, token_set, preferences)
    positive_keyword_score = sum(_learning_signal_scores(preferences, "keywords").get(keyword, 0.0) for keyword in positive_keyword_hits)
    negative_keyword_score = sum(abs(_learning_signal_scores(preferences, "keywords").get(keyword, 0.0)) for keyword in negative_keyword_hits)
    if positive_keyword_score > 0:
        points += min(6, int(round(positive_keyword_score * 2)))
        reasons.append(f"Learned keyword preference from feedback: {', '.join(positive_keyword_hits[:3])}.")
    if negative_keyword_score > 0:
        points -= min(6, int(round(negative_keyword_score * 2)))
        reasons.append(f"Learned keyword caution from feedback: {', '.join(negative_keyword_hits[:3])}.")

    naics_score, naics_hits = _naics_signal_score(record, preferences)
    if naics_score > 0:
        points += min(4, int(round(naics_score * 2)))
        reasons.append(f"Learned NAICS preference from feedback: {', '.join(naics_hits[:3])}.")
    elif naics_score < 0:
        points -= min(4, int(round(abs(naics_score) * 2)))
        reasons.append(f"Learned NAICS caution from feedback: {', '.join(naics_hits[:3])}.")

    opportunity_class_score, opportunity_class_hits = _opportunity_class_signal_score(record, preferences)
    if opportunity_class_score > 0:
        points += min(4, int(round(opportunity_class_score * 2)))
        reasons.append(f"Learned opportunity-class preference from feedback: {', '.join(opportunity_class_hits[:2])}.")
    elif opportunity_class_score < 0:
        points -= min(4, int(round(abs(opportunity_class_score) * 2)))
        reasons.append(f"Learned opportunity-class caution from feedback: {', '.join(opportunity_class_hits[:2])}.")

    return points, reasons


def _preference_filter_guidance(
    record: dict[str, Any],
    normalized_text: str,
    token_set: set[str],
    preferences: dict[str, Any],
) -> tuple[str | None, str | None]:
    buyer_text = _normalized_text(record.get("buyer", ""))
    for buyer in _merged_preference_values(preferences, "hard_filters", "exclude_buyers"):
        normalized_buyer = _normalized_text(buyer)
        if normalized_buyer and normalized_buyer in buyer_text:
            return "suppressed", f"Suppressed by learned buyer filter: {buyer}."

    excluded_naics = set(_merged_preference_values(preferences, "hard_filters", "exclude_naics"))
    matching_naics = sorted(_record_naics_codes(record) & excluded_naics)
    if matching_naics:
        return "suppressed", f"Suppressed by learned NAICS filter: {', '.join(matching_naics[:3])}."

    opportunity_class = str(record.get("opportunity_class", "") or "").strip()
    normalized_opportunity_class = _normalized_text(opportunity_class)
    for excluded_class in _merged_preference_values(preferences, "hard_filters", "exclude_opportunity_classes"):
        if _normalized_text(excluded_class) == normalized_opportunity_class and normalized_opportunity_class:
            return "suppressed", f"Suppressed by learned opportunity-class filter: {excluded_class}."

    for keyword in _merged_preference_values(preferences, "hard_filters", "exclude_keywords"):
        if _keyword_matches(keyword, normalized_text, token_set):
            return "suppressed", f"Suppressed by learned keyword filter: {keyword}."

    return None, None


def _preferred_buyer_match_strength(preferred_buyer: str, buyer_text: str) -> tuple[int, str] | None:
    normalized_preference = _normalized_text(preferred_buyer)
    if not normalized_preference:
        return None

    direct_aliases = {
        "defense agencies": ("dept of defense", "department of defense", "army", "navy", "air force", "space force", "defense"),
        "federal civilian agencies": ("department", "agency", "administration", "bureau"),
        "state local it modernization buyers": ("state", "county", "city", "municipal"),
    }
    alias_points = {
        "defense agencies": 6,
        "federal civilian agencies": 3,
        "state local it modernization buyers": 5,
    }
    aliases = direct_aliases.get(normalized_preference)
    if aliases:
        if any(alias in buyer_text for alias in aliases):
            return alias_points.get(normalized_preference, 5), f"Preferred buyer segment match: {preferred_buyer}."
        return None
    if normalized_preference in buyer_text:
        return 10, f"Preferred buyer alignment: {preferred_buyer}."
    return None


def _record_naics_codes(record: dict[str, Any]) -> set[str]:
    values = record.get("naics", [])
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _naics_match_strength(record: dict[str, Any], profile: dict[str, Any]) -> tuple[int, str | None, str]:
    record_codes = _record_naics_codes(record)
    if not record_codes:
        return 0, None, "none"
    confirmed_codes = set(_vendor_naics_by_bucket(profile, "confirmed"))
    candidate_codes = set(_vendor_naics_by_bucket(profile, "candidates"))
    if record_codes & confirmed_codes:
        return 20, "Confirmed NAICS match from the vendor profile.", "confirmed"
    if record_codes & candidate_codes:
        return 12, "Candidate NAICS match from the vendor profile.", "candidate"
    return 8, "Related NAICS signal present, but it is not yet confirmed against the vendor profile.", "related"


def _is_actionable_notice_type(record: dict[str, Any]) -> bool:
    notice_type = _normalized_text(record.get("notice_type", ""))
    if not notice_type:
        return False
    if any(marker in notice_type for marker in ("presolicitation", "special notice", "sources sought", "request for information", "industry day")):
        return False
    notice_tokens = set(notice_type.split())
    if "solicitation" in notice_tokens:
        return True
    return any(phrase in notice_type for phrase in ("request for proposal", "request for quotation", "invitation for bid"))


def _has_strong_action_now_signal(fit_context: dict[str, Any]) -> bool:
    return bool(
        fit_context.get("multiword_keyword_hits")
        or int(fit_context.get("keyword_hit_count", 0) or 0) >= 2
        or fit_context.get("naics_quality") == "confirmed"
        or int(fit_context.get("buyer_match_points", 0) or 0) >= 10
        or fit_context.get("fit_narrative_positive_hits")
        or fit_context.get("learned_feedback_positive")
    )


def _notice_categories(record: dict[str, Any], hydrated_text: str | None) -> set[str]:
    title_text = _normalized_text(record.get("title", ""))
    summary_text = _normalized_text(hydrated_text or record.get("summary", ""))
    notice_type = _normalized_text(record.get("notice_type", ""))
    combined = " ".join(part for part in (title_text, summary_text, notice_type) if part)
    categories: set[str] = set()

    if "award notice" in combined:
        categories.add("award_notice")
    if "justification" in notice_type or "limited source justification" in combined:
        categories.add("justification_and_approval")
    if "contract award" in combined:
        categories.add("contract_award")
    if "justification and approval" in combined or " j a " in f" {combined} ":
        categories.update({"justification_and_approval", "j_and_a_posting"})
    if "fair opportunity exception" in combined:
        categories.add("fair_opportunity_exception")
    if "sole source" in combined:
        categories.add("sole_source_notice")
    if "notice of intent" in combined:
        categories.add("notice_of_intent_notice")
    if "intent to sole source" in combined or "notice of intent to sole source" in combined:
        categories.add("notice_of_intent_to_sole_source")
    if "sources sought" in combined:
        categories.add("sources_sought_only")
    if "request for information" in combined or re.search(r"(?<![a-z0-9])rfi(?![a-z0-9])", combined):
        categories.add("rfi_only")
    if "industry day" in combined:
        categories.add("industry_day_only")
    if "vendor library" in combined:
        categories.add("vendor_library_notice")
    if "presolicitation" in combined or "pre solicitation" in combined:
        categories.add("presolicitation_notice")
    if "draft solicitation" in combined or title_text.startswith("draft ") or " this is a draft " in f" {combined} ":
        categories.add("draft_solicitation")
    if "cancelled" in combined or "canceled" in combined:
        categories.add("cancelled_notice")
    if (
        "update to" in combined
        or "please continue to monitor" in combined
        or "no definitive date" in combined
        or "has been delayed" in combined
    ):
        categories.add("informational_update")
    if "update to" in title_text or title_text.startswith("update "):
        categories.add("update_only_notice")

    return categories


def _category_detail(categories: list[str]) -> str:
    labels = [NOTICE_CATEGORY_LABELS.get(category, category.replace("_", " ")) for category in categories[:3]]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _notice_guidance(preferences: dict[str, Any], categories: set[str], timing_band: str) -> tuple[str | None, str | None, list[str]]:
    screening = preferences.get("screening", {}) if isinstance(preferences.get("screening"), dict) else {}
    allow_watchlist = bool(screening.get("allow_watchlist_for_non_actionable_notices", True))
    reject_categories = {
        str(item).strip()
        for item in screening.get("reject_notice_categories_from_shortlist", [])
        if str(item).strip()
    }
    hard_suppressed = sorted(categories & ALWAYS_SUPPRESSED_NOTICE_CATEGORIES)
    if hard_suppressed:
        return "suppressed", f"Suppressed by notice type: {_category_detail(hard_suppressed)}.", hard_suppressed

    early_signal = sorted(categories & WATCHLIST_ELIGIBLE_NOTICE_CATEGORIES)
    informational = sorted(categories & INFORMATIONAL_NOTICE_CATEGORIES)
    if early_signal and allow_watchlist:
        watchlist_categories = early_signal + [category for category in informational if category not in early_signal]
        return "watchlist", f"Watchlist: early-shaping notice ({_category_detail(watchlist_categories)}).", watchlist_categories

    explicit_rejects = sorted((categories & reject_categories) - set(early_signal))
    if explicit_rejects:
        return "suppressed", f"Suppressed by preferences: notice appears non-actionable ({_category_detail(explicit_rejects)}).", explicit_rejects

    if informational:
        if allow_watchlist and timing_band == "watchlist":
            return "watchlist", f"Watchlist: informational update in shaping window ({_category_detail(informational)}).", informational
        return "suppressed", f"Suppressed by preferences: notice appears non-actionable ({_category_detail(informational)}).", informational

    return None, None, []


def _bucket_for_record(
    match_score: int,
    timing_band: str,
    preferences: dict[str, Any],
    bucket_override: str | None,
    fit_context: dict[str, Any],
) -> str:
    thresholds = preferences.get("confidence_thresholds", {}) if isinstance(preferences.get("confidence_thresholds"), dict) else {}
    action_now_min = int(thresholds.get("action_now_min", 75) or 75)
    worth_a_look_min = int(thresholds.get("worth_a_look_min", 60) or 60)
    watchlist_min = int(thresholds.get("watchlist_min", thresholds.get("near_miss_min", 45)) or 45)
    if bucket_override == "suppressed" or match_score < watchlist_min:
        return "suppressed"
    if bucket_override == "watchlist":
        return "watchlist"
    if timing_band == "urgent":
        if (
            match_score >= action_now_min
            and fit_context.get("is_actionable_notice_type")
            and not fit_context.get("hard_eligibility_gate")
            and _has_strong_action_now_signal(fit_context)
        ):
            return "action_now"
        return "worth_a_look" if match_score >= worth_a_look_min else "watchlist"
    if timing_band == "active":
        return "worth_a_look" if match_score >= worth_a_look_min else "watchlist"
    if timing_band == "watchlist":
        return "watchlist"
    return "suppressed"


def _urgent_bucket_hold_reason(
    bucket: str,
    match_score: int,
    timing_band: str,
    preferences: dict[str, Any],
    bucket_override: str | None,
    fit_context: dict[str, Any],
) -> str:
    if bucket != "worth_a_look" or timing_band != "urgent" or bucket_override:
        return ""
    thresholds = preferences.get("confidence_thresholds", {}) if isinstance(preferences.get("confidence_thresholds"), dict) else {}
    action_now_min = int(thresholds.get("action_now_min", 75) or 75)
    if fit_context.get("hard_eligibility_gate"):
        return "Urgent timing, but gating language keeps this out of Action Now."
    if not fit_context.get("is_actionable_notice_type"):
        return "Urgent timing, but the notice type is still shaping or informational rather than a live bid."
    if not _has_strong_action_now_signal(fit_context):
        return "Urgent timing, but fit evidence is still broad; keep this in Worth a Look until scope alignment is clearer."
    if match_score < action_now_min:
        return f"Urgent timing, but the fit score is still below the Action Now bar of {action_now_min}."
    return ""


def _has_hard_eligibility_gate(record: dict[str, Any], hydrated_text: str | None) -> bool:
    combined = _normalized_text(
        f"{record.get('title', '')} {record.get('summary', '')} {hydrated_text or ''}"
    )
    gate_markers = (
        "must be registered as",
        "must hold",
        "holders only",
        "only contract holders",
        "only available to",
        "eligibility for award",
    )
    vehicle_markers = (
        "contract holder",
        "contract vehicle",
        "gwac",
        "idiq",
        "bpa",
        "schedule holder",
        "blanket purchase agreement",
    )
    return any(marker in combined for marker in gate_markers) and any(marker in combined for marker in vehicle_markers)


def _score_record(
    record: dict[str, Any],
    keywords: list[str],
    negative_keywords: list[str],
    fit_guidance: dict[str, Any],
    profile: dict[str, Any],
    preferences: dict[str, Any],
    hydrated_text: str | None,
    timing_band: str,
    days_until_due: int | None,
) -> tuple[int, int, list[str], str, dict[str, Any]]:
    title_text = f"{record.get('title', '')} {record.get('summary', '')} {hydrated_text or ''}"
    normalized_text = _normalized_text(title_text)
    token_set = set(normalized_text.split())
    reasons: list[str] = []
    match_score = 35
    confidence = 50

    naics_points, naics_reason, naics_quality = _naics_match_strength(record, profile)
    match_score += naics_points
    if naics_reason:
        reasons.append(naics_reason)
    preferred_naics = set(_merged_preference_values(preferences, "soft_preferences", "preferred_naics"))
    preferred_naics_hits = sorted(_record_naics_codes(record) & preferred_naics)
    if preferred_naics_hits:
        match_score += min(8, 4 * len(preferred_naics_hits))
        reasons.append(f"Learned preferred NAICS overlap: {', '.join(preferred_naics_hits[:3])}.")

    keyword_hits = [keyword for keyword in keywords if _keyword_matches(keyword, normalized_text, token_set)]
    if keyword_hits:
        match_score += min(25, 5 * len(keyword_hits))
        reasons.append(f"Capability/keyword overlap: {', '.join(keyword_hits[:4])}.")

    negative_keyword_hits = [keyword for keyword in negative_keywords if _keyword_matches(keyword, normalized_text, token_set)]
    if negative_keyword_hits:
        match_score -= min(15, 5 * len(negative_keyword_hits))
        reasons.append(f"Negative keyword overlap: {', '.join(negative_keyword_hits[:4])}.")

    fit_narrative_points, fit_narrative_reasons, fit_narrative_context = _fit_narrative_alignment(
        fit_guidance,
        normalized_text,
        token_set,
    )
    match_score += fit_narrative_points
    reasons.extend(fit_narrative_reasons)

    buyers = profile.get("buyers", {}) if isinstance(profile.get("buyers"), dict) else {}
    preferred_buyers = []
    for item in buyers.get("preferred", []):
        if isinstance(item, str) and item.strip():
            preferred_buyers.append(item.strip().lower())
    for item in _merged_preference_values(preferences, "soft_preferences", "preferred_buyers"):
        preferred_buyers.append(item.strip().lower())
    preferred_buyers = sorted(dict.fromkeys(preferred_buyers))
    buyer_text = _normalized_text(record.get("buyer", ""))
    buyer_match_points = 0
    buyer_match_reason = ""
    for item in preferred_buyers:
        match = _preferred_buyer_match_strength(item, buyer_text)
        if match and match[0] > buyer_match_points:
            buyer_match_points, buyer_match_reason = match
    if buyer_match_points:
        match_score += buyer_match_points
        reasons.append(buyer_match_reason)

    preferred_opportunity_classes = {
        _normalized_text(item)
        for item in _merged_preference_values(preferences, "soft_preferences", "preferred_opportunity_classes")
    }
    normalized_opportunity_class = _normalized_text(record.get("opportunity_class", ""))
    if normalized_opportunity_class and normalized_opportunity_class in preferred_opportunity_classes:
        match_score += 6
        reasons.append(f"Learned preferred opportunity class: {record.get('opportunity_class', 'N/A')}.")

    timing_reason = _timing_reason(timing_band, days_until_due)
    match_score += _timing_adjustment(timing_band)
    if timing_reason:
        reasons.append(timing_reason)

    feedback_points, feedback_reasons = _feedback_signal_adjustment(record, normalized_text, token_set, preferences)
    match_score += feedback_points
    reasons.extend(feedback_reasons)

    hard_eligibility_gate = _has_hard_eligibility_gate(record, hydrated_text)
    if hard_eligibility_gate:
        match_score -= 15
        caveat = "Notice text includes a hard vehicle or holder eligibility gate; confirm you can bid before treating this as active pipeline."
        reasons.append("Hard eligibility gate detected in notice text.")
    else:
        caveat = "Review full notice attachments and confirm scope fit."

    due_date = _parse_any_date(record.get("due_date"))
    if due_date is None:
        confidence -= 10
        caveat = "Missing usable due date in source response."
    else:
        confidence += 10

    if hydrated_text:
        confidence += 20
        reasons.append("Full SAM notice description loaded for this result.")
    elif record.get("summary") and record.get("summary") != "N/A":
        confidence += 5
        reasons.append("Partial SAM summary text available from Pass 1.")
    else:
        confidence -= 10

    fit_context = {
        "keyword_hit_count": len(keyword_hits),
        "multiword_keyword_hits": sum(1 for keyword in keyword_hits if " " in _normalized_text(keyword)),
        "naics_quality": naics_quality,
        "buyer_match_points": buyer_match_points,
        "is_actionable_notice_type": _is_actionable_notice_type(record),
        "hard_eligibility_gate": hard_eligibility_gate,
        "fit_narrative_positive_hits": fit_narrative_context.get("positive_hits", []),
        "fit_narrative_negative_hits": fit_narrative_context.get("negative_hits", []),
        "learned_feedback_positive": feedback_points > 0,
    }
    return max(0, min(match_score, 100)), max(0, min(confidence, 100)), reasons[:4], caveat, fit_context


def _normalize_explanations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in records:
        items.append(
            {
                "opportunity_id": record.get("opportunity_id", ""),
                "canonical_record_id": record.get("canonical_record_id", ""),
                "title": record.get("title", ""),
                "summary": record.get("summary", "N/A"),
                "reasons": record.get("explanation_reasons", []),
                "main_caveat": record.get("main_caveat", "N/A"),
                "commercial_intel_notes": record.get("commercial_intel_notes", []),
                "cross_source_evidence_notes": record.get("cross_source_evidence_notes", []),
                "cross_source_evidence": record.get("cross_source_evidence", {}),
            }
        )
    return items


def _dedupe_scan_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _apply_cross_source_scan_evidence(records: list[dict[str, Any]]) -> None:
    for record in records:
        commercial_section = record.get("commercial_intel") if isinstance(record.get("commercial_intel"), dict) else {}
        provider_models = [
            model
            for model in (commercial_section.get("evidence_models", []) or [])
            if isinstance(model, dict)
        ]
        merged = merge_evidence_models([build_scan_official_evidence_model(record), *provider_models])
        record["cross_source_evidence"] = merged
        evidence_notes = evidence_model_scan_notes(merged, max_items=3)
        record["cross_source_evidence_notes"] = evidence_notes
        if evidence_notes:
            record["explanation_reasons"] = _dedupe_scan_strings(
                list(record.get("explanation_reasons", []) or []) + evidence_notes
            )[:4]
        conflicts = merged.get("conflicts", []) or []
        if conflicts:
            first_conflict = conflicts[0]
            conflict_caveat = (
                f'Source conflict remains on {first_conflict.get("field", "cross-source evidence")}: '
                f'{", ".join((first_conflict.get("values") or [])[:2])}.'
            )
            current_caveat = str(record.get("main_caveat") or "").strip()
            record["main_caveat"] = _dedupe_scan_strings([current_caveat, conflict_caveat])[0] if current_caveat else conflict_caveat


def _search_text_for_enrichment(profile: dict[str, Any]) -> str:
    vendor_name = _vendor_name(profile)
    if vendor_name and vendor_name != "Vendor":
        return vendor_name
    keywords = _vendor_keywords(profile)
    return keywords[0] if keywords else ""


def _company_website(profile: dict[str, Any]) -> str:
    company = profile.get("company", {}) if isinstance(profile.get("company"), dict) else {}
    website = company.get("website") or profile.get("company_url") or profile.get("website") or ""
    return str(website).strip()


def _bootstrap_recommended_next_moves(bundle_root: Path, workspace: Path, vendor_profile: dict[str, Any]) -> list[dict[str, Any]]:
    bootstrap_script = (bundle_root / "scripts" / "bootstrap" / "bootstrap_workspace.py").as_posix()
    workspace_path = workspace.as_posix()
    website = _company_website(vendor_profile)
    company_url = website or "<company-url>"
    bootstrap_command = (
        f'python3 "{bootstrap_script}" --workspace "{workspace_path}" --company-url "{company_url}"'
    )
    bootstrap_message = (
        f"Bootstrap this workspace from {website} before you rerun the scan."
        if website
        else "Bootstrap this workspace from the company website before you rerun the scan."
    )
    return [
        {
            "type": "bootstrap_workspace",
            "message": bootstrap_message,
            "command": bootstrap_command,
        },
        {
            "type": "confirm_bootstrap_outputs",
            "message": "Review procurement/STARTER_PROFILE.md, confirm the candidate NAICS, and then rerun the scan.",
        },
    ]


def _write_scan_outputs(
    opportunities_path: Path,
    explanations_path: Path,
    records: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
) -> None:
    write_json(
        opportunities_path,
        {
            "generated_at": utc_now_iso(),
            "records": records,
            "source_statuses": source_statuses,
        },
    )
    write_json(
        explanations_path,
        {
            "generated_at": utc_now_iso(),
            "items": _normalize_explanations(records),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--horizon", default="30-45")
    parser.add_argument("--federal-only", action="store_true")
    args = parser.parse_args()

    bundle_root = Path(__file__).resolve().parents[2]
    workspace = Path(args.workspace)
    date_str = today_local_str()
    today = _today_date(date_str)

    registry_path, registry, refreshed, refresh_reasons = refresh_runtime_registry(bundle_root, workspace)
    preferences_path = ensure_preferences(bundle_root, workspace, args.horizon)
    opportunities_path, explanations_path = ensure_today_artifacts(workspace, date_str)
    preferences = load_json(preferences_path, default={})
    timing = _timing_settings(preferences)
    vendor_profile = load_json(workspace / "procurement" / "vendor-profile.json", default={})
    vendor_name = _vendor_name(vendor_profile)
    keywords = _vendor_keywords(vendor_profile, preferences)
    negative_keywords = _vendor_negative_keywords(vendor_profile, preferences)
    fit_guidance = _fit_narrative_guidance(vendor_profile)
    naics_codes = _vendor_naics(vendor_profile, preferences)

    source_issues: list[str] = []
    source_statuses: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    recommended_next_moves: list[dict[str, Any]] = []

    configured_enabled_sources = get_enabled_sources(registry)
    enabled_sources = filter_sources_for_policy(configured_enabled_sources, federal_only=args.federal_only)
    enabled_ids = {source.get("id") for source in enabled_sources}
    excluded_sources = [
        source for source in configured_enabled_sources if source.get("id") not in enabled_ids
    ]

    if excluded_sources:
        for source in excluded_sources:
            source_statuses.append(
                {
                    "source_id": source.get("id"),
                    "status": "excluded_by_federal_only_policy",
                    "record_count": 0,
                    "notes": ["Source is outside the federal-only v1 release scope."],
                }
            )

    if "sam_contract_opportunities" in enabled_ids:
        sam_result = search_sam_opportunities(naics_codes=naics_codes, today=today)
        sam_source_status = {
            "source_id": "sam_contract_opportunities",
            "status": sam_result.get("status", "unknown"),
            "notes": sam_result.get("notes", []),
            "queried_naics": sam_result.get("queried_naics", []),
            "error_count": len(sam_result.get("errors", [])),
            "record_count": len(sam_result.get("records", [])),
        }
        if sam_result.get("recommended_next_step") == "bootstrap_workspace":
            recommended_next_moves = _bootstrap_recommended_next_moves(bundle_root, workspace, vendor_profile)
            sam_source_status["recommended_next_step"] = "bootstrap_workspace"
            sam_source_status["recommended_message"] = sam_result.get("recommended_message", "")
            sam_source_status["recommended_next_moves"] = recommended_next_moves
            if recommended_next_moves and recommended_next_moves[0].get("command"):
                sam_source_status["recommended_command"] = recommended_next_moves[0]["command"]
            guidance_note = str(sam_result.get("recommended_message", "")).strip()
            if guidance_note:
                source_issues.append(guidance_note)
        source_statuses.append(sam_source_status)
        source_issues.extend(sam_result.get("errors", []))

        candidate_records = []
        semantic_reasoning_remaining = SEMANTIC_REASONING_MAX_RECORDS_PER_RUN
        for record in sam_result.get("records", []):
            due_date = _parse_any_date(record.get("due_date"))
            timing_band, days_until_due = _timing_band(due_date, today, preferences)
            if timing_band in {"expired", "out_of_window"}:
                continue
            if timing_band == "missing" and not timing["allow_missing"]:
                continue

            hydrated = hydrate_sam_notice(str(record.get("notice_id", "")))
            hydrated_text = hydrated.get("summary") if hydrated.get("full_desc_loaded") else ""
            if hydrated.get("status") not in {"ok", "empty", "missing_notice_id"}:
                detail = hydrated.get("detail") or hydrated.get("code")
                source_issues.append(f"SAM Pass 2 for {record.get('notice_id', '')}: {hydrated.get('status')} ({detail})")
            if hydrated_text:
                record["summary"] = hydrated_text
                record.setdefault("raw_match_evidence", {})
                record["raw_match_evidence"]["full_desc_loaded"] = True

            normalized_scan_text = _normalized_text(f"{record.get('title', '')} {record.get('summary', '')} {hydrated_text or ''}")
            scan_token_set = set(normalized_scan_text.split())
            preference_bucket, preference_note = _preference_filter_guidance(record, normalized_scan_text, scan_token_set, preferences)
            match_score, confidence_score, reasons, caveat, fit_context = _score_record(
                record,
                keywords,
                negative_keywords,
                fit_guidance,
                vendor_profile,
                preferences,
                hydrated_text,
                timing_band,
                days_until_due,
            )
            notice_categories = _notice_categories(record, hydrated_text)
            guidance_bucket, guidance_note, guidance_categories = _notice_guidance(preferences, notice_categories, timing_band)
            if preference_bucket == "suppressed":
                guidance_bucket = "suppressed"
                guidance_note = preference_note
            semantic_score_before = match_score
            semantic_bucket_before = _bucket_for_record(match_score, timing_band, preferences, guidance_bucket, fit_context)
            semantic_reasoning_attempted = False
            if (
                semantic_reasoning_remaining > 0
                and _should_run_semantic_reasoning(
                    match_score=match_score,
                    bucket_override=guidance_bucket,
                    timing_band=timing_band,
                    fit_context=fit_context,
                    hydrated_text=hydrated_text,
                )
            ):
                semantic_reasoning_attempted = True
                semantic_fit = assess_scan_fit(
                    record=record,
                    hydrated_text=hydrated_text or str(record.get("summary", "") or ""),
                    vendor_profile=vendor_profile,
                    deterministic_fit_context=fit_context,
                    learned_semantic_preferences=_semantic_applied_preferences(preferences),
                )
                semantic_reasoning_remaining -= 1
                semantic_points, semantic_reasons = _semantic_feedback_adjustment(semantic_fit, preferences)
                match_score = max(0, min(match_score + semantic_points, 100))
                if semantic_reasons:
                    reasons = [*semantic_reasons, *reasons][:4]
                fit_context["semantic_fit"] = semantic_fit or {}
                fit_context["semantic_fit_assessment"] = (
                    str((semantic_fit or {}).get("fit_assessment", "")).strip()
                    if isinstance(semantic_fit, dict)
                    else ""
                )
            else:
                semantic_fit = None
            record["match_score"] = match_score
            record["confidence_score"] = confidence_score
            record["semantic_fit"] = semantic_fit or {}
            record["bucket"] = _bucket_for_record(match_score, timing_band, preferences, guidance_bucket, fit_context)
            record["semantic_audit"] = _semantic_audit_record(
                semantic_fit=semantic_fit,
                score_before=semantic_score_before,
                score_after=match_score,
                bucket_before=semantic_bucket_before,
                bucket_after=record["bucket"],
                guidance_bucket=guidance_bucket,
                reasoning_attempted=semantic_reasoning_attempted,
            )
            fit_context["semantic_audit"] = record["semantic_audit"]
            record["timing_window"] = timing_band
            if days_until_due is not None:
                record["days_until_due"] = days_until_due
            if notice_categories:
                record["screening_categories"] = sorted(notice_categories)
            hold_reason = _urgent_bucket_hold_reason(
                record["bucket"],
                match_score,
                timing_band,
                preferences,
                guidance_bucket,
                fit_context,
            )
            if guidance_note:
                record["screening_status"] = guidance_bucket or record["bucket"]
                record["explanation_reasons"] = [guidance_note, *reasons][:4]
                record["main_caveat"] = guidance_note if guidance_bucket == "suppressed" else caveat
                if guidance_categories:
                    record["suppression_categories"] = guidance_categories
            else:
                record["explanation_reasons"] = ([hold_reason, *reasons] if hold_reason else reasons)[:4]
                record["main_caveat"] = hold_reason or caveat
            candidate_records.append(record)

        records.extend(candidate_records)
    else:
        source_issues.append("SAM.gov Contract Opportunities is disabled in the runtime source registry.")

    if "usaspending_award_history" in enabled_ids:
        enrichment_term = _search_text_for_enrichment(vendor_profile)
        if enrichment_term:
            usaspending_result = post_award_search(enrichment_term, limit=5)
            source_statuses.append(
                {
                    "source_id": "usaspending_award_history",
                    "status": usaspending_result.get("status", "unknown"),
                    "record_count": len(((usaspending_result.get("response") or {}).get("results") or []))
                    if isinstance(usaspending_result.get("response"), dict)
                    else 0,
                }
            )
            if usaspending_result.get("status") != "ok":
                detail = usaspending_result.get("detail") or usaspending_result.get("code") or "unknown issue"
                source_issues.append(f"USAspending enrichment: {usaspending_result.get('status')} ({detail})")
        else:
            source_statuses.append(
                {
                    "source_id": "usaspending_award_history",
                    "status": "skipped",
                    "record_count": 0,
                    "notes": ["No vendor name or keyword available for enrichment query."],
                }
            )

    commercial_enrichment = enrich_scan_records(
        enabled_sources=enabled_sources,
        records=records,
        vendor_profile=vendor_profile,
        preferences=preferences,
    )
    source_statuses.extend(commercial_enrichment.get("source_statuses", []))
    source_issues.extend(commercial_enrichment.get("source_issues", []))
    _apply_cross_source_scan_evidence(records)

    for source in enabled_sources:
        source_id = source.get("id")
        if source_id not in {
            "sam_contract_opportunities",
            "usaspending_award_history",
            *COMMERCIAL_INTEL_SOURCE_IDS,
        }:
            source_statuses.append(
                {
                    "source_id": source_id,
                    "status": NOT_IMPLEMENTED_IN_BUNDLE_STATUS,
                    "record_count": 0,
                }
            )

    _write_scan_outputs(opportunities_path, explanations_path, records, source_statuses)
    digest_entry_map = build_digest_entry_map(workspace, date_str)
    configured_enabled_summary = enabled_sources_summary(registry)
    enabled_summary = sources_summary(enabled_sources)
    scan_period_label = (
        f"0-{timing['retrieval_max']} days retrieved | "
        f"0-14 action now | 15-45 worth a look | 46-{timing['watchlist_max']} watchlist / early shaping"
    )
    render_result = render_digest_and_report(
        bundle_root,
        workspace,
        date_str,
        scan_period_label,
        run_notes=[
            f"Runtime source registry path: {registry_path.as_posix()}",
            f"Runtime source registry refreshed: {'yes' if refreshed else 'no'}",
            f"Configured enabled sources: {configured_enabled_summary}",
            f"Active sources used this run: {enabled_summary}",
            f"Federal-only mode: {'yes' if args.federal_only else 'no'}",
            f"Vendor name: {vendor_name}",
            f"Vendor NAICS used for SAM search: {', '.join(naics_codes) if naics_codes else 'none'}",
            f"Fit narrative active: {'yes' if fit_guidance.get('enabled') else 'no'}",
            f"Timing model: 0-14 action now, 15-45 worth a look, 46-{timing['watchlist_max']} watchlist / early shaping",
            f"Opportunities snapshot path: {opportunities_path.as_posix()}",
            f"Explanations snapshot path: {explanations_path.as_posix()}",
            f"Refresh reasons: {', '.join(refresh_reasons) if refresh_reasons else 'none'}",
            *(
                [f"Recommended next move: {recommended_next_moves[0]['message']}"]
                if recommended_next_moves
                else []
            ),
            *(
                [f"Bootstrap command: {recommended_next_moves[0]['command']}"]
                if recommended_next_moves and recommended_next_moves[0].get("command")
                else []
            ),
        ],
        enabled_source_summary=enabled_summary,
        source_issues=source_issues,
    )

    result = {
        "status": render_result["run_status"],
        "date": date_str,
        "horizon": args.horizon,
        "federal_only": args.federal_only,
        "recommended_next_step": recommended_next_moves[0]["type"] if recommended_next_moves else "",
        "bootstrap_suggested": bool(recommended_next_moves),
        "recommended_next_moves": recommended_next_moves,
        "preferences_path": preferences_path.as_posix(),
        "registry_path": registry_path.as_posix(),
        "opportunities_path": opportunities_path.as_posix(),
        "explanations_path": explanations_path.as_posix(),
        "digest_entry_map_path": (workspace / "procurement" / "digest-entry-map" / f"{date_str}.json").as_posix(),
        "digest_path": render_result["digest_path"],
        "report_path": render_result["report_path"],
        "digest_validation": render_result["digest_validation"],
        "stable_entry_count": len(digest_entry_map.get("entries", [])),
        "source_statuses": source_statuses,
        "source_issue_count": len(source_issues),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
