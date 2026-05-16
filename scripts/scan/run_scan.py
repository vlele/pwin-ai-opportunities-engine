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

from common.paths import load_json, today_local_str, utc_now_iso, write_json
from common.source_registry import enabled_sources_summary, refresh_runtime_registry
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

NOTICE_CATEGORY_LABELS = {
    "award_notice": "award notice",
    "contract_award": "contract award",
    "justification_and_approval": "justification and approval posting",
    "j_and_a_posting": "J&A posting",
    "fair_opportunity_exception": "fair opportunity exception",
    "sole_source_notice": "sole-source notice",
    "notice_of_intent_to_sole_source": "intent-to-sole-source notice",
    "informational_update": "informational update",
    "update_only_notice": "update-only notice",
    "sources_sought_only": "sources sought notice",
    "rfi_only": "request for information",
    "industry_day_only": "industry day notice",
    "vendor_library_notice": "vendor library notice",
    "draft_solicitation": "draft solicitation",
    "cancelled_notice": "cancelled notice",
}


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
    preferences.setdefault("time_horizon", {})
    preferences["time_horizon"]["min_days_from_today"] = min_days
    preferences["time_horizon"]["max_days_from_today"] = max_days
    preferences["time_horizon"]["last_override_source"] = "scan command"
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


def _vendor_keywords(profile: dict[str, Any]) -> list[str]:
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
    return sorted(dict.fromkeys(keywords))


def _vendor_naics(profile: dict[str, Any]) -> list[str]:
    naics = profile.get("naics", {}) if isinstance(profile.get("naics"), dict) else {}
    values: list[str] = []
    for bucket in ("confirmed", "candidates"):
        for item in naics.get(bucket, []):
            if isinstance(item, dict):
                code = item.get("code") or item.get("naics") or item.get("id")
            else:
                code = item
            code_text = str(code).strip() if code is not None else ""
            if code_text:
                values.append(code_text)
    deduped = []
    for code in values:
        if code not in deduped:
            deduped.append(code)
    return deduped[:5]


def _in_horizon(due_date: date | None, today: date, min_days: int, max_days: int) -> bool:
    if due_date is None:
        return False
    delta = (due_date - today).days
    return min_days <= delta <= max_days


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


def _preferred_buyer_matches(preferred_buyer: str, buyer_text: str) -> bool:
    normalized_preference = _normalized_text(preferred_buyer)
    if not normalized_preference:
        return False

    direct_aliases = {
        "defense agencies": ("dept of defense", "department of defense", "army", "navy", "air force", "space force", "defense"),
        "federal civilian agencies": ("department", "agency", "administration", "bureau"),
        "state local it modernization buyers": ("state", "county", "city", "municipal"),
    }
    aliases = direct_aliases.get(normalized_preference)
    if aliases:
        return any(alias in buyer_text for alias in aliases)
    return normalized_preference in buyer_text


def _notice_categories(record: dict[str, Any], hydrated_text: str | None) -> set[str]:
    title_text = _normalized_text(record.get("title", ""))
    summary_text = _normalized_text(hydrated_text or record.get("summary", ""))
    notice_type = _normalized_text(record.get("notice_type", ""))
    combined = " ".join(part for part in (title_text, summary_text, notice_type) if part)
    categories: set[str] = set()

    if "award notice" in combined:
        categories.add("award_notice")
    if "contract award" in combined:
        categories.add("contract_award")
    if "justification and approval" in combined or " j a " in f" {combined} ":
        categories.update({"justification_and_approval", "j_and_a_posting"})
    if "fair opportunity exception" in combined:
        categories.add("fair_opportunity_exception")
    if "sole source" in combined:
        categories.add("sole_source_notice")
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


def _suppression_details(preferences: dict[str, Any], categories: set[str]) -> tuple[str | None, list[str]]:
    screening = preferences.get("screening", {}) if isinstance(preferences.get("screening"), dict) else {}
    hard_filters = preferences.get("hard_filters", {}) if isinstance(preferences.get("hard_filters"), dict) else {}
    reject_categories = {
        str(item).strip()
        for item in screening.get("reject_notice_categories_from_shortlist", [])
        if str(item).strip()
    }
    matching_rejects = sorted(categories & reject_categories)
    suppressed_categories: list[str] = []
    if matching_rejects:
        suppressed_categories.extend(matching_rejects)
    if hard_filters.get("exclude_non_actionable_notices", False):
        for category in sorted(categories):
            if category in NON_ACTIONABLE_NOTICE_CATEGORIES and category not in suppressed_categories:
                suppressed_categories.append(category)

    if not suppressed_categories:
        return None, []

    labels = [NOTICE_CATEGORY_LABELS.get(category, category.replace("_", " ")) for category in suppressed_categories[:3]]
    if len(labels) == 1:
        detail = labels[0]
    elif len(labels) == 2:
        detail = f"{labels[0]} and {labels[1]}"
    else:
        detail = f"{', '.join(labels[:-1])}, and {labels[-1]}"
    return f"Suppressed by preferences: notice appears non-actionable ({detail}).", suppressed_categories


def _bucket_for_score(match_score: int, preferences: dict[str, Any]) -> str:
    thresholds = preferences.get("confidence_thresholds", {}) if isinstance(preferences.get("confidence_thresholds"), dict) else {}
    action_now_min = int(thresholds.get("action_now_min", 75) or 75)
    worth_a_look_min = int(thresholds.get("worth_a_look_min", 60) or 60)
    near_miss_min = int(thresholds.get("near_miss_min", 45) or 45)
    if match_score >= action_now_min:
        return "action_now"
    if match_score >= worth_a_look_min:
        return "worth_a_look"
    if match_score >= near_miss_min:
        return "near_miss"
    return "suppressed"


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


def _score_record(record: dict[str, Any], keywords: list[str], profile: dict[str, Any], hydrated_text: str | None) -> tuple[int, int, list[str], str]:
    title_text = f"{record.get('title', '')} {record.get('summary', '')} {hydrated_text or ''}"
    normalized_text = _normalized_text(title_text)
    token_set = set(normalized_text.split())
    reasons: list[str] = []
    match_score = 35
    confidence = 50

    if record.get("naics"):
        match_score += 20
        reasons.append("Confirmed/candidate NAICS match from the vendor profile.")

    keyword_hits = [keyword for keyword in keywords if _keyword_matches(keyword, normalized_text, token_set)]
    if keyword_hits:
        match_score += min(25, 5 * len(keyword_hits))
        reasons.append(f"Capability/keyword overlap: {', '.join(keyword_hits[:4])}.")

    buyers = profile.get("buyers", {}) if isinstance(profile.get("buyers"), dict) else {}
    preferred_buyers = []
    for item in buyers.get("preferred", []):
        if isinstance(item, str) and item.strip():
            preferred_buyers.append(item.strip().lower())
    buyer_text = _normalized_text(record.get("buyer", ""))
    if preferred_buyers and any(_preferred_buyer_matches(item, buyer_text) for item in preferred_buyers):
        match_score += 10
        reasons.append("Preferred buyer/agency alignment from the vendor profile.")

    if hydrated_text:
        confidence += 20
        reasons.append("Full SAM notice description loaded for this result.")
    elif record.get("summary") and record.get("summary") != "N/A":
        confidence += 5
        reasons.append("Partial SAM summary text available from Pass 1.")
    else:
        confidence -= 10

    if _has_hard_eligibility_gate(record, hydrated_text):
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
        reasons.append("Usable due date is inside the requested horizon.")

    return max(0, min(match_score, 100)), max(0, min(confidence, 100)), reasons[:4], caveat


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
            }
        )
    return items


def _search_text_for_enrichment(profile: dict[str, Any]) -> str:
    vendor_name = _vendor_name(profile)
    if vendor_name and vendor_name != "Vendor":
        return vendor_name
    keywords = _vendor_keywords(profile)
    return keywords[0] if keywords else ""


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
    min_days, max_days = parse_horizon(args.horizon)

    registry_path, registry, refreshed, refresh_reasons = refresh_runtime_registry(bundle_root, workspace)
    preferences_path = ensure_preferences(bundle_root, workspace, args.horizon)
    opportunities_path, explanations_path = ensure_today_artifacts(workspace, date_str)
    preferences = load_json(preferences_path, default={})
    vendor_profile = load_json(workspace / "procurement" / "vendor-profile.json", default={})
    vendor_name = _vendor_name(vendor_profile)
    keywords = _vendor_keywords(vendor_profile)
    naics_codes = _vendor_naics(vendor_profile)

    source_issues: list[str] = []
    source_statuses: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    enabled_sources = [source for source in registry.get("sources", []) if source.get("enabled", source.get("default_enabled", False))]
    enabled_ids = {source.get("id") for source in enabled_sources}

    if "sam_contract_opportunities" in enabled_ids:
        sam_result = search_sam_opportunities(naics_codes=naics_codes, today=today)
        source_statuses.append(
            {
                "source_id": "sam_contract_opportunities",
                "status": sam_result.get("status", "unknown"),
                "notes": sam_result.get("notes", []),
                "queried_naics": sam_result.get("queried_naics", []),
                "error_count": len(sam_result.get("errors", [])),
                "record_count": len(sam_result.get("records", [])),
            }
        )
        source_issues.extend(sam_result.get("errors", []))

        candidate_records = []
        for record in sam_result.get("records", []):
            due_date = _parse_any_date(record.get("due_date"))
            if not _in_horizon(due_date, today, min_days, max_days):
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

            match_score, confidence_score, reasons, caveat = _score_record(record, keywords, vendor_profile, hydrated_text)
            notice_categories = _notice_categories(record, hydrated_text)
            suppression_note, suppressed_categories = _suppression_details(preferences, notice_categories)
            record["match_score"] = match_score
            record["confidence_score"] = confidence_score
            record["bucket"] = "suppressed" if suppression_note else _bucket_for_score(match_score, preferences)
            if notice_categories:
                record["screening_categories"] = sorted(notice_categories)
            if suppression_note:
                record["screening_status"] = "suppressed"
                record["explanation_reasons"] = [suppression_note, *reasons][:4]
                record["main_caveat"] = suppression_note
                if suppressed_categories:
                    record["suppression_categories"] = suppressed_categories
            else:
                record["explanation_reasons"] = reasons
                record["main_caveat"] = caveat
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

    for source in enabled_sources:
        source_id = source.get("id")
        if source_id not in {"sam_contract_opportunities", "usaspending_award_history"}:
            source_statuses.append(
                {
                    "source_id": source_id,
                    "status": "not_implemented_in_v15_2",
                    "record_count": 0,
                }
            )

    _write_scan_outputs(opportunities_path, explanations_path, records, source_statuses)
    digest_entry_map = build_digest_entry_map(workspace, date_str)
    enabled_summary = enabled_sources_summary(registry)
    render_result = render_digest_and_report(
        bundle_root,
        workspace,
        date_str,
        args.horizon,
        run_notes=[
            f"Runtime source registry path: {registry_path.as_posix()}",
            f"Runtime source registry refreshed: {'yes' if refreshed else 'no'}",
            f"Enabled sources: {enabled_summary}",
            f"Federal-only mode: {'yes' if args.federal_only else 'no'}",
            f"Vendor name: {vendor_name}",
            f"Vendor NAICS used for SAM search: {', '.join(naics_codes) if naics_codes else 'none'}",
            f"Opportunities snapshot path: {opportunities_path.as_posix()}",
            f"Explanations snapshot path: {explanations_path.as_posix()}",
            f"Refresh reasons: {', '.join(refresh_reasons) if refresh_reasons else 'none'}",
        ],
        enabled_source_summary=enabled_summary,
        source_issues=source_issues,
    )

    result = {
        "status": render_result["run_status"],
        "date": date_str,
        "horizon": args.horizon,
        "federal_only": args.federal_only,
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
