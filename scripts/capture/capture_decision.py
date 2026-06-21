from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from common.evidence_model import evidence_model_competitor_candidates


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SIGNAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "under",
    "through",
    "support",
    "services",
    "service",
    "program",
    "system",
    "task",
    "order",
    "combined",
    "synopsis",
    "solicitation",
    "request",
    "proposal",
    "notice",
    "amendment",
    "department",
    "agency",
    "office",
    "federal",
    "national",
    "space",
    "based",
}
FIT_NOISE_TERMS = {
    "support",
    "service",
    "services",
    "solution",
    "solutions",
    "system",
    "systems",
    "technology",
    "technologies",
    "program management",
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
FIT_NARRATIVE_STOPWORDS = SIGNAL_STOPWORDS | {
    "can",
    "credibly",
    "prefer",
    "prioritize",
    "favor",
    "favour",
    "target",
    "pursue",
    "focus",
    "look",
    "work",
}
VEHICLE_ACCESS_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("GSA MAS", ("gsa mas", "multiple award schedule", "mas schedule", "federal supply schedule")),
    ("NASA SEWP", ("sewp",)),
    ("CIO-SP", ("cio-sp", "cio sp")),
    ("Alliant", ("alliant",)),
    ("OASIS", ("oasis",)),
    ("8(a) STARS", ("8(a) stars", "8a stars", "stars iii", "stars ii")),
    ("Polaris", ("polaris",)),
]
CONTRACT_STRUCTURE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("Single-award IDIQ", ("single award idiq", "single-award idiq")),
    ("IDIQ", ("indefinite-delivery-indefinite-quantity", "indefinite delivery indefinite quantity", "idiq")),
    ("SATOC", ("single award task order contract", "satoc")),
    ("Task-order contract", ("task order contract",)),
    ("BPA", ("blanket purchase agreement", "bpa")),
    ("Open market / unrestricted competition", ("full and open", "open market", "unrestricted full and open competition", "unrestricted")),
]
CONTINUITY_MARKERS = (
    "incumbent",
    "continuation",
    "continue",
    "bridge",
    "zero mission degradation",
    "avoid a lapse",
    "prevent a lapse",
    "low transition risk",
    "transitioning to a new contractor",
    "legacy",
)
SHAPING_MARKERS = (
    "sources sought",
    "request for information",
    "rfi",
    "industry day",
    "draft rfp",
    "draft solicitation",
    "questions",
    "amendment",
    "proposal instructions",
)
COMPETITIVE_BLOCK_MARKERS = (
    "not a request for competitive proposals",
    "sole source",
    "only one responsible source",
    "notice of intent to award a sole source",
)
POLICY_MARKERS = (
    "nist",
    "fedramp",
    "cui",
    "fisma",
    "508",
    "cmmc",
    "sbom",
    "zero trust",
    "publication 4812",
)
QUALIFICATION_MARKERS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("Top Secret facility clearance", ("top secret", "facility clearance"), ("top secret", "facility clearance", "fcl")),
    ("Secret facility clearance", ("secret", "facility clearance"), ("secret", "facility clearance", "fcl")),
    ("CMMC Level 2", ("cmmc level 2", "c3pao"), ("cmmc", "c3pao")),
    ("JCP certification", ("joint certification program", "jcp"), ("jcp", "joint certification program")),
]
NO_HOT_BUTTON_EVIDENCE = "Requirement-bearing scope evidence is still too thin to call customer hot buttons confidently."
NO_WIN_THEME_EVIDENCE = "Insufficient corroborated requirement evidence to recommend win themes yet."
NO_DIFFERENTIATOR_EVIDENCE = "Insufficient corroborated requirement evidence to recommend differentiators yet."
NO_REASONED_THEME_EVIDENCE = "Reasoning-based win themes remain unverified until extracted scope sections or promoted solicitation facts surface."
NO_PROOF_REQUIREMENT_EVIDENCE = "Proof requirements remain provisional until extracted scope sections or promoted solicitation facts surface."
THIN_PRIORITY_EVIDENCE = "Requirement-bearing customer priorities remain under-corroborated in this run; rely on explicit solicitation facts and validated workstreams only."
THIN_PRIORITY_LIKELY = "No additional customer-priority inference should be treated as reliable until stronger mission, budget, forecast, or attachment anchors are recovered."
THIN_PRIORITY_PAIN = "Customer pain points remain provisional because requirement-bearing mission or scope anchors are still thin."
MODERATE_PRIORITY_WARNING = "Evidence is partial in this run, so customer-priority sections were shortened to anchored points only."
THIN_PRIORITY_WARNING = "Evidence is thin in this run, so customer-priority sections were intentionally shortened and made explicit."
GENERIC_STRATEGY_TEMPLATE_PREFIXES = (
    "show how the team will execute the primary requirement workstreams from day one",
    "tie past performance to the visible workstreams surfaced in the attachments",
    "present a low-disruption transition story",
    "prove fixed-price discipline with a fully burdened on-site labor mix",
    "the customer needs a credible staffing plan for the visible labor mix and execution setting",
    "a delivery story that links startup readiness, qa/qc rigor, reporting discipline, and workstream throughput in one narrative",
    "documented readiness for access, credentialing, clearance, nda, or other surfaced handling controls",
    "credible experience supporting scoped package artifacts and customer review coordination",
)


def _clean_excerpt(value: object, max_chars: int = 4000) -> str:
    raw = str(value or "")
    text = SPACE_RE.sub(" ", TAG_RE.sub(" ", raw)).strip()
    return text[:max_chars]


def _normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_excerpt(value, max_chars=20000).lower()).strip()


def _signal_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        for token in normalized.split():
            if token in SIGNAL_STOPWORDS or token.isdigit() or len(token) < 3:
                continue
            tokens.add(token)
    return tokens


def _currency(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"${number:,.2f}"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _join_sentence_parts(parts: list[str]) -> str:
    cleaned = [str(part).strip().rstrip(".") for part in parts if str(part).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"{cleaned[0]}."
    if len(cleaned) == 2:
        return f"{cleaned[0]}, and {cleaned[1]}."
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}."


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _semantic_capture_context(opportunity: dict[str, Any], learned_semantic_preferences: dict[str, Any]) -> dict[str, Any]:
    semantic_fit = opportunity.get("semantic_fit", {}) if isinstance(opportunity.get("semantic_fit"), dict) else {}
    semantic_facets = semantic_fit.get("semantic_facets", {}) if isinstance(semantic_fit.get("semantic_facets"), dict) else {}
    if not semantic_fit and not learned_semantic_preferences:
        return {
            "summary": "",
            "support": [],
            "cautions": [],
            "historical_pattern_summary": "",
            "fit_assessment": "",
            "credible_posture": "",
            "reasoning_summary": "",
        }

    mission_domains = set(_string_list(semantic_facets.get("mission_domains", [])))
    delivery_models = set(_string_list(semantic_facets.get("delivery_models", [])))
    positive_facets = set(_string_list(semantic_facets.get("positive_fit_facets", [])))
    negative_facets = set(_string_list(semantic_facets.get("negative_fit_facets", [])))
    risk_flags = set(_string_list(semantic_fit.get("risk_flags", [])))
    fit_assessment = str(semantic_fit.get("fit_assessment", "") or "").strip()
    credible_posture = str(semantic_fit.get("credible_posture", "") or "").strip()
    reasoning_summary = str(semantic_fit.get("reasoning_summary", "") or "").strip()

    prefer_mission = mission_domains & set(_string_list(learned_semantic_preferences.get("prefer_mission_domains", [])))
    avoid_mission = mission_domains & set(_string_list(learned_semantic_preferences.get("avoid_mission_domains", [])))
    prefer_delivery = delivery_models & set(_string_list(learned_semantic_preferences.get("prefer_delivery_models", [])))
    avoid_delivery = delivery_models & set(_string_list(learned_semantic_preferences.get("avoid_delivery_models", [])))
    prefer_facets = positive_facets & set(_string_list(learned_semantic_preferences.get("prefer_semantic_facets", [])))
    avoid_facets = negative_facets & set(_string_list(learned_semantic_preferences.get("avoid_semantic_facets", [])))
    avoid_shapes = risk_flags & set(_string_list(learned_semantic_preferences.get("avoid_competitive_shapes", [])))
    prefer_teaming = set()
    if credible_posture == "team":
        prefer_teaming = {"team_not_prime"} & set(_string_list(learned_semantic_preferences.get("prefer_teaming_postures", [])))

    support = _dedupe_strings(
        [
            *([f"Historical preference supports this mission domain: {', '.join(sorted(prefer_mission)[:2])}."] if prefer_mission else []),
            *([f"Historical preference supports this delivery model: {', '.join(sorted(prefer_delivery)[:2])}."] if prefer_delivery else []),
            *([f"Historical preference supports this work pattern: {', '.join(sorted(prefer_facets)[:2])}."] if prefer_facets else []),
            *([f"Historical teaming preference is consistent with the scan semantic posture ({credible_posture})."] if prefer_teaming else []),
        ]
    )
    cautions = _dedupe_strings(
        [
            *([f"Historical caution applies to this mission domain: {', '.join(sorted(avoid_mission)[:2])}."] if avoid_mission else []),
            *([f"Historical caution applies to this delivery model: {', '.join(sorted(avoid_delivery)[:2])}."] if avoid_delivery else []),
            *([f"Historical caution applies to this work pattern: {', '.join(sorted(avoid_facets)[:2])}."] if avoid_facets else []),
            *([f"Historical caution applies to the current competitive shape: {', '.join(sorted(avoid_shapes)[:2])}."] if avoid_shapes else []),
        ]
    )

    summary_parts = []
    if reasoning_summary:
        summary_parts.append(reasoning_summary)
    if fit_assessment:
        summary_parts.append(f"Scan semantic fit assessed this as {fit_assessment.replace('_', ' ')}.")
    if credible_posture:
        summary_parts.append(f"Scan semantic posture was {credible_posture}.")
    summary = " ".join(summary_parts).strip()

    historical_pattern_summary = ""
    if cautions:
        historical_pattern_summary = cautions[0]
    elif support:
        historical_pattern_summary = support[0]
    elif summary:
        historical_pattern_summary = summary

    return {
        "summary": summary,
        "support": support,
        "cautions": cautions,
        "historical_pattern_summary": historical_pattern_summary,
        "fit_assessment": fit_assessment,
        "credible_posture": credible_posture,
        "reasoning_summary": reasoning_summary,
    }


def _stringify_item(item: object) -> str:
    if isinstance(item, dict):
        parts: list[str] = []
        for key in (
            "name",
            "title",
            "client",
            "buyer",
            "agency",
            "summary",
            "description",
            "vehicle",
            "code",
            "outcome",
        ):
            value = str(item.get(key, "") or "").strip()
            if value and value not in parts:
                parts.append(value)
        if parts:
            return " | ".join(parts)
        return _clean_excerpt(json.dumps(item, ensure_ascii=True), max_chars=220)
    return _clean_excerpt(item, max_chars=220)


def _string_list(value: object, max_items: int = 0) -> list[str]:
    values = value if isinstance(value, list) else [value]
    items = _dedupe_strings([_stringify_item(item) for item in values if _stringify_item(item)])
    return items[:max_items] if max_items else items


def _profile_company_name(profile: dict[str, Any]) -> str:
    company = profile.get("company", {}) if isinstance(profile.get("company"), dict) else {}
    return (
        str(company.get("name", "") or "").strip()
        or str(profile.get("vendor_name", "") or "").strip()
        or str(profile.get("name", "") or "").strip()
        or "Vendor"
    )


def _profile_company_summary(profile: dict[str, Any]) -> str:
    company = profile.get("company", {}) if isinstance(profile.get("company"), dict) else {}
    return _clean_excerpt(company.get("summary", "") or profile.get("fit_narrative", "") or "Company profile summary not provided.", max_chars=600)


def _profile_fit_narrative(profile: dict[str, Any]) -> str:
    value = profile.get("fit_narrative", "")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
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
        normalized = _normalize_text(cleaned)
        if normalized:
            parts.append(normalized)
    return _dedupe_strings(parts)


def _fit_narrative_guidance(profile: dict[str, Any]) -> dict[str, list[str]]:
    narrative = _profile_fit_narrative(profile)
    positive_terms: list[str] = []
    negative_terms: list[str] = []
    for clause in _split_fit_narrative_clauses(narrative):
        normalized_clause = _normalize_text(clause)
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
                parts = re.split(cue, clause, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) > 1:
                    negative_terms.extend(_split_fit_narrative_terms(parts[1]))
                break
        for cue in FIT_NARRATIVE_POSITIVE_CUES:
            if cue in normalized_clause:
                parts = re.split(cue, clause, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) > 1:
                    positive_terms.extend(_split_fit_narrative_terms(parts[1]))
                break
    return {
        "positive_terms": _dedupe_strings(positive_terms),
        "negative_terms": _dedupe_strings(negative_terms),
    }


def _profile_keywords(profile: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    keywords.extend(_string_list(profile.get("core_competencies", [])))
    other_tags = profile.get("other_taxonomy_tags", {}) if isinstance(profile.get("other_taxonomy_tags"), dict) else {}
    keywords.extend(_string_list(other_tags.get("keywords", [])))
    return _dedupe_strings(keywords)


def _profile_negative_keywords(profile: dict[str, Any]) -> list[str]:
    other_tags = profile.get("other_taxonomy_tags", {}) if isinstance(profile.get("other_taxonomy_tags"), dict) else {}
    return _string_list(other_tags.get("negative_keywords", []))


def _profile_naics(profile: dict[str, Any]) -> list[str]:
    naics = profile.get("naics", {}) if isinstance(profile.get("naics"), dict) else {}
    values: list[str] = []
    for bucket in ("confirmed", "candidates"):
        for item in naics.get(bucket, []):
            if isinstance(item, dict):
                code = item.get("code") or item.get("naics") or item.get("id")
            else:
                code = item
            text = str(code or "").strip()
            if text:
                values.append(text)
    return _dedupe_strings(values)


def _profile_past_performance(profile: dict[str, Any]) -> list[str]:
    return _string_list(profile.get("past_performance_highlights", []))


def _profile_contract_vehicles(profile: dict[str, Any]) -> list[str]:
    return _string_list(profile.get("contract_vehicles", []))


def _profile_partner_names(profile: dict[str, Any]) -> list[str]:
    partner_values: list[str] = []
    for key in ("partners", "known_partners", "preferred_partners"):
        if key in profile:
            partner_values.extend(_string_list(profile.get(key, [])))
    return _dedupe_strings(partner_values)


def _profile_prime_sub_preferences(profile: dict[str, Any]) -> list[str]:
    commercial = profile.get("commercial_constraints", {}) if isinstance(profile.get("commercial_constraints"), dict) else {}
    return _string_list(commercial.get("prime_or_sub", []))


def _profile_teaming_preferences(profile: dict[str, Any]) -> list[str]:
    commercial = profile.get("commercial_constraints", {}) if isinstance(profile.get("commercial_constraints"), dict) else {}
    return _string_list(commercial.get("teaming_preferences", []))


def _profile_set_asides(profile: dict[str, Any]) -> list[str]:
    commercial = profile.get("commercial_constraints", {}) if isinstance(profile.get("commercial_constraints"), dict) else {}
    return _string_list(commercial.get("set_aside_programs", []))


def _profile_certifications(profile: dict[str, Any]) -> list[str]:
    commercial = profile.get("commercial_constraints", {}) if isinstance(profile.get("commercial_constraints"), dict) else {}
    return _string_list(commercial.get("certifications", []))


def _profile_preferred_buyers(profile: dict[str, Any]) -> list[str]:
    buyers = profile.get("buyers", {}) if isinstance(profile.get("buyers"), dict) else {}
    values = _string_list(buyers.get("preferred", []))
    narrative = _profile_fit_narrative(profile)
    for match in re.finditer(r"buyers such as\s+(.+?)(?:[.;]|$)", narrative, flags=re.IGNORECASE):
        fragment = re.split(r"(?:avoid|treat|lower-fit|lower fit)", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        parts = re.split(r";|,(?=\s*[A-Z])", fragment)
        expanded_parts: list[str] = []
        for part in parts:
            expanded_parts.extend(
                re.split(
                    r"\band (?=(?:Department of|U\.S\.|US |Veterans Affairs|General Services Administration|NASA|National ))",
                    part,
                    flags=re.IGNORECASE,
                )
            )
        for part in expanded_parts:
            cleaned = part.strip(" .")
            if cleaned and len(cleaned) >= 4:
                values.append(cleaned)
    return _dedupe_strings(values)


def _profile_preferred_award_band(profile: dict[str, Any]) -> tuple[float | None, float | None]:
    commercial = profile.get("commercial_constraints", {}) if isinstance(profile.get("commercial_constraints"), dict) else {}
    band = commercial.get("preferred_award_band", {}) if isinstance(commercial.get("preferred_award_band"), dict) else {}
    return (_currency_to_float(band.get("min")), _currency_to_float(band.get("max")))


def _profile_place_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    geography = profile.get("geography", {}) if isinstance(profile.get("geography"), dict) else {}
    return {
        "preferred_places": _dedupe_strings(
            _string_list(geography.get("place_of_performance", []))
            + _string_list(geography.get("preferred_states", []))
        ),
        "remote_ok": bool(geography.get("remote_ok")),
    }


def _currency_to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.]+", "", str(value or ""))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _looks_like_buyer_phrase(value: str) -> bool:
    lower = value.lower().strip()
    return lower.startswith(
        (
            "department of ",
            "u.s. ",
            "us ",
            "veterans affairs",
            "general services administration",
            "national ",
            "office of ",
        )
    )


def _buyer_preference_matches(buyer: str, preferred_buyers: list[str]) -> list[str]:
    normalized_buyer = _normalize_text(buyer)
    buyer_tokens = _signal_tokens(buyer)
    matches: list[str] = []
    for preferred in preferred_buyers:
        normalized_preferred = _normalize_text(preferred)
        preferred_tokens = _signal_tokens(preferred)
        if not normalized_preferred or not preferred_tokens:
            continue
        overlap = buyer_tokens & preferred_tokens
        if (
            f" {normalized_preferred} " in f" {normalized_buyer} "
            or f" {normalized_buyer} " in f" {normalized_preferred} "
            or len(overlap) >= max(2, min(len(preferred_tokens), 3))
        ):
            matches.append(preferred)
    return _dedupe_strings(matches)


def _fuzzy_phrase_hits(text: str, phrases: list[str], max_items: int = 8) -> list[str]:
    text_tokens = _signal_tokens(text)
    hits: list[str] = []
    for phrase in phrases:
        raw = _clean_excerpt(phrase, max_chars=140)
        phrase_tokens = {
            token
            for token in _signal_tokens(raw)
            if token not in FIT_NARRATIVE_STOPWORDS and token not in FIT_NOISE_TERMS
        }
        if not phrase_tokens:
            continue
        required_overlap = 2 if len(phrase_tokens) >= 4 else 1
        if len(text_tokens & phrase_tokens) < required_overlap:
            continue
        hits.append(raw)
        if len(hits) >= max_items:
            break
    return _dedupe_strings(hits)


def _vehicle_profile_matches(visible_paths: list[str], profile_vehicles: list[str]) -> list[str]:
    matches: list[str] = []
    for visible in visible_paths:
        visible_tokens = _signal_tokens(visible)
        for vehicle in profile_vehicles:
            vehicle_tokens = _signal_tokens(vehicle)
            if not vehicle_tokens:
                continue
            overlap = visible_tokens & vehicle_tokens
            if (
                _contains_normalized_phrase(visible, vehicle)
                or _contains_normalized_phrase(vehicle, visible)
                or len(overlap) >= max(2, min(len(vehicle_tokens), 3))
            ):
                matches.append(vehicle)
    return _dedupe_strings(matches)


def _profile_fit_weighting(
    profile: dict[str, Any],
    buyer: str,
    opportunity: dict[str, Any],
    notice_text: str,
    solicitation_facts: dict[str, Any],
    vehicle_access_paths: list[str],
    set_aside_text: str,
    capability_hits: list[str],
    negative_hits: list[str],
    past_performance_hits: list[str],
) -> dict[str, Any]:
    fit_guidance = _fit_narrative_guidance(profile)
    preferred_buyers = _profile_preferred_buyers(profile)
    buyer_matches = _buyer_preference_matches(buyer, preferred_buyers)
    thematic_positive_terms = [
        term
        for term in _dedupe_strings(_profile_keywords(profile) + fit_guidance.get("positive_terms", []))
        if "buyers such as" not in term.lower() and term not in preferred_buyers and not _looks_like_buyer_phrase(term)
    ]
    positive_theme_hits = _fuzzy_phrase_hits(
        notice_text,
        thematic_positive_terms,
        max_items=6,
    )
    negative_theme_hits = _dedupe_strings(
        negative_hits
        + _fuzzy_phrase_hits(
            notice_text,
            _dedupe_strings(_profile_negative_keywords(profile) + fit_guidance.get("negative_terms", [])),
            max_items=4,
        )
    )
    vehicle_matches = _vehicle_profile_matches(vehicle_access_paths, _profile_contract_vehicles(profile))
    preferred_min, preferred_max = _profile_preferred_award_band(profile)
    estimated_value = _currency_to_float(
        solicitation_facts.get("estimated_value")
        or opportunity.get("estimated_value")
        or opportunity.get("award_amount")
        or opportunity.get("ceiling_value")
    )
    preferred_places = _profile_place_preferences(profile)
    location_text = _location_text(opportunity)
    location_matches = _fuzzy_phrase_hits(location_text, preferred_places.get("preferred_places", []), max_items=3)

    customer_alignment_adjustment = 0
    requirement_fit_adjustment = 0
    past_performance_adjustment = 0
    vehicle_access_adjustment = 0
    signals: list[str] = []
    cautions: list[str] = []

    if buyer_matches:
        customer_alignment_adjustment += 2
        signals.append(f"Buyer aligns with stated vendor target accounts: {', '.join(buyer_matches[:2])}.")
    elif preferred_buyers and buyer.strip():
        customer_alignment_adjustment -= 1
        cautions.append(f"Buyer does not align cleanly with the vendor's stated target accounts ({', '.join(preferred_buyers[:2])}).")

    if positive_theme_hits or capability_hits:
        requirement_fit_adjustment += 2 if len(_dedupe_strings(positive_theme_hits + capability_hits)) >= 3 else 1
        signals.append(
            f"Requirement language overlaps vendor-priority themes: {', '.join(_dedupe_strings(positive_theme_hits + capability_hits)[:3])}."
        )
    elif fit_guidance.get("positive_terms") or _profile_keywords(profile):
        requirement_fit_adjustment -= 1
        cautions.append("Current package does not show strong overlap with the vendor's stated priority themes.")

    if negative_theme_hits:
        requirement_fit_adjustment -= min(3, max(1, len(negative_theme_hits)))
        cautions.append(f"Lower-fit or cautionary profile themes surfaced against this package: {', '.join(negative_theme_hits[:3])}.")

    if past_performance_hits:
        past_performance_adjustment += min(2, len(past_performance_hits))
        signals.append(f"Visible scope aligns with past performance we can plausibly cite: {', '.join(past_performance_hits[:2])}.")
    elif _profile_past_performance(profile):
        past_performance_adjustment -= 1
        cautions.append("User-provided past performance inventory exists, but direct scope overlap was not obvious in the current package.")

    if vehicle_matches:
        vehicle_access_adjustment += 1
        signals.append(f"Visible vehicle path overlaps profile vehicles: {', '.join(vehicle_matches[:2])}.")
    elif vehicle_access_paths and _profile_contract_vehicles(profile):
        cautions.append("Visible vehicle path does not line up cleanly with the vehicles listed in the vendor profile.")

    if set_aside_text and set_aside_text.strip().lower() not in {"not stated", "unknown"}:
        set_aside_matches = _fuzzy_phrase_hits(set_aside_text, _profile_set_asides(profile), max_items=2)
        if set_aside_matches:
            signals.append(f"Set-aside posture aligns with profile eligibility cues: {', '.join(set_aside_matches[:2])}.")

    if estimated_value is not None and (preferred_min is not None or preferred_max is not None):
        if (preferred_min is None or estimated_value >= preferred_min) and (preferred_max is None or estimated_value <= preferred_max):
            signals.append("Estimated value falls inside the vendor's preferred award band.")
        else:
            cautions.append("Estimated value falls outside the vendor's stated preferred award band.")

    if location_matches:
        signals.append(f"Place of performance aligns with profile geography cues: {', '.join(location_matches[:2])}.")
    elif preferred_places.get("remote_ok") and "remote" in notice_text.lower():
        signals.append("Profile allows remote delivery and the package signals remote execution flexibility.")

    return {
        "customer_alignment_adjustment": customer_alignment_adjustment,
        "requirement_fit_adjustment": requirement_fit_adjustment,
        "past_performance_adjustment": past_performance_adjustment,
        "vehicle_access_adjustment": vehicle_access_adjustment,
        "signals": _dedupe_strings(signals),
        "cautions": _dedupe_strings(cautions),
        "buyer_matches": buyer_matches,
        "preferred_buyers": preferred_buyers,
        "positive_theme_hits": positive_theme_hits,
        "negative_theme_hits": negative_theme_hits,
        "vehicle_matches": vehicle_matches,
        "location_matches": location_matches,
        "award_band_fit": estimated_value is not None
        and (preferred_min is None or estimated_value >= preferred_min)
        and (preferred_max is None or estimated_value <= preferred_max),
    }


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    normalized_text = f" {_normalize_text(text)} "
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in normalized_text


def _contains_any(text: str, phrases: tuple[str, ...] | list[str]) -> bool:
    lower = text.lower()
    return any(phrase.lower() in lower for phrase in phrases)


def _contains_policy_marker(text: str) -> bool:
    return any(_contains_normalized_phrase(text, phrase) for phrase in POLICY_MARKERS)


def _phrase_hits(text: str, phrases: list[str], max_items: int = 8) -> list[str]:
    normalized_text = f" {_normalize_text(text)} "
    hits: list[str] = []
    for phrase in phrases:
        raw = _clean_excerpt(phrase, max_chars=120)
        normalized_phrase = _normalize_text(raw)
        if not normalized_phrase or normalized_phrase in FIT_NOISE_TERMS:
            continue
        if len(normalized_phrase) < 4:
            continue
        if f" {normalized_phrase} " in normalized_text:
            hits.append(raw)
            continue
        tokens = [token for token in normalized_phrase.split() if len(token) >= 4 and token not in SIGNAL_STOPWORDS]
        matched = [token for token in tokens if f" {token} " in normalized_text]
        if len(tokens) >= 2 and len(matched) >= min(2, len(tokens)):
            hits.append(raw)
    return _dedupe_strings(hits)[:max_items]


def _location_text(opportunity: dict[str, Any]) -> str:
    location = opportunity.get("location", {}) if isinstance(opportunity.get("location"), dict) else {}
    city = str(((location.get("city") or {}).get("name")) or "").strip() if isinstance(location.get("city"), dict) else ""
    state = str(((location.get("state") or {}).get("name")) or ((location.get("state") or {}).get("code")) or "").strip() if isinstance(location.get("state"), dict) else ""
    country = str(((location.get("country") or {}).get("name")) or "").strip() if isinstance(location.get("country"), dict) else ""
    parts = [part for part in (city, state, country) if part]
    return ", ".join(parts) or "Not stated in current scan record"


def _detect_contract_type(text: str) -> str:
    lower = text.lower()
    has_ffp = "firm fixed price" in lower or bool(re.search(r"\bffp\b", lower))
    has_cost = "cost plus" in lower or "cost-reimbursement" in lower or "cost reimbursement" in lower
    has_tm = "time and materials" in lower or bool(re.search(r"\bt&m\b", lower))
    has_lh = "labor hour" in lower
    if has_ffp and has_cost:
        return "Hybrid FFP / Cost Reimbursement"
    if has_ffp and has_tm:
        return "Hybrid FFP / Time and Materials"
    if "firm fixed price" in lower or re.search(r"\bffp\b", lower):
        return "Firm Fixed Price"
    if "time and materials" in lower or re.search(r"\bt&m\b", lower):
        return "Time and Materials"
    if "labor hour" in lower:
        return "Labor Hour"
    if "cost plus" in lower or "cost-reimbursement" in lower:
        return "Cost Reimbursement"
    return "Not explicit in current evidence"


def _detect_award_basis(text: str) -> str:
    lower = text.lower()
    if "lowest price technically acceptable" in lower or "lpta" in lower:
        return "LPTA"
    if "best value" in lower and "tradeoff" in lower:
        return "Best Value Tradeoff"
    if "best value" in lower:
        return "Best Value"
    if "technically acceptable" in lower:
        return "Technical Acceptability / Price"
    return "Evaluation basis not explicit in current evidence"


def _detect_transition_window(text: str) -> str:
    lower = text.lower()
    if "no transition" in lower or "no phase-in" in lower:
        return "No transition period stated in current evidence"
    patterns = (
        r"(\d{1,3})\s*-\s*day transition",
        r"(\d{1,3})\s+day transition",
        r"transition period of (\d{1,3}) days",
        r"phase[- ]in period of (\d{1,3}) days",
        r"within (\d{1,3}) days after award",
        r"(\d{1,3})\s+calendar days(?: after award)?",
    )
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return f"{match.group(1)}-day transition / mobilization signal"
    if any(marker in lower for marker in CONTINUITY_MARKERS):
        return "Transition sensitivity is visible, but the exact transition window is not explicit in current evidence"
    return "Not explicit in current evidence"


def _detect_vehicle_posture(text: str, vehicle_signals: list[str], contract_vehicles: list[str]) -> dict[str, Any]:
    lower = f"{text} {' '.join(vehicle_signals)}".lower()
    access_paths: list[str] = []
    for label, markers in VEHICLE_ACCESS_MARKERS:
        if any(marker in lower for marker in markers):
            access_paths.append(label)
    contract_structures: list[str] = []
    for label, markers in CONTRACT_STRUCTURE_MARKERS:
        if any(marker in lower for marker in markers):
            contract_structures.append(label)
    access_paths = _dedupe_strings(access_paths)
    contract_structures = _dedupe_strings(contract_structures)
    profile_hits = [
        vehicle
        for vehicle in contract_vehicles
        if _normalize_text(vehicle) and _normalize_text(vehicle) in _normalize_text(" ".join(access_paths) + " " + text)
    ]
    requires_existing_vehicle_access = bool(access_paths)
    return {
        "access_paths": access_paths,
        "contract_structures": contract_structures,
        "profile_hits": _dedupe_strings(profile_hits),
        "requires_existing_vehicle_access": requires_existing_vehicle_access,
    }


def _required_qualification_gaps(profile: dict[str, Any], text: str) -> dict[str, list[str]]:
    lower = text.lower()
    vendor_cert_tokens = _normalize_text(" ".join(_profile_certifications(profile)))
    surfaced: list[str] = []
    missing_labels: list[str] = []
    missing: list[str] = []
    for label, required_markers, vendor_markers in QUALIFICATION_MARKERS:
        if all(marker in lower for marker in required_markers):
            surfaced.append(label)
            if not any(marker in vendor_cert_tokens for marker in vendor_markers):
                missing_labels.append(label)
                missing.append(f"{label} is called out in the notice, but the vendor profile does not prove it.")
    surfaced = _dedupe_strings(surfaced)
    missing_labels = _dedupe_strings(missing_labels)
    if "Top Secret facility clearance" in surfaced:
        surfaced = [value for value in surfaced if value != "Secret facility clearance"]
        missing_labels = [value for value in missing_labels if value != "Secret facility clearance"]
        missing = [value for value in missing if not value.startswith("Secret facility clearance ")]
    return {
        "surfaced": surfaced,
        "missing_labels": missing_labels,
        "missing": _dedupe_strings(missing),
    }


def _set_aside_access(set_aside_text: str, vendor_set_asides: list[str]) -> tuple[str, bool]:
    normalized = _normalize_text(set_aside_text)
    if not normalized or normalized in {"not stated", "na", "n a", "unknown"}:
        return "Set-aside posture is not stated in the current evidence.", True
    if "no set aside" in normalized or "full and open" in normalized or "unrestricted" in normalized:
        return "No visible socioeconomic barrier in the current record.", True
    vendor_tokens = " ".join(_normalize_text(value) for value in vendor_set_asides)
    match = bool(vendor_tokens and any(token in vendor_tokens for token in normalized.split()))
    if match:
        return f"Opportunity appears set aside ({set_aside_text}); vendor profile shows matching or adjacent socioeconomic posture.", True
    return f"Opportunity appears set aside ({set_aside_text}); vendor profile does not yet prove matching eligibility.", False


def _competitive_gate(opportunity: dict[str, Any], notice_text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    screening_status = str(opportunity.get("screening_status", "") or "").lower()
    bucket = str(opportunity.get("bucket", "") or "").lower()
    if screening_status == "suppressed" or bucket == "suppressed":
        reasons.append("The scan classified this record as suppressed rather than a current bid candidate.")
    if _contains_any(notice_text, list(COMPETITIVE_BLOCK_MARKERS)):
        reasons.append("Current notice language points to a sole-source or non-competitive action rather than a clean bid opportunity.")
    return (not reasons), reasons


def _requirement_specific_insights(text: str) -> dict[str, list[str] | str]:
    lower = text.lower()
    normalized_text = f" {_normalize_text(text)} "
    priorities: list[str] = []
    pain_points: list[str] = []
    win_themes: list[str] = []
    differentiators: list[str] = []
    mission_problem = ""

    def _has_signal(phrase: str) -> bool:
        normalized_phrase = _normalize_text(phrase)
        return bool(normalized_phrase and f" {normalized_phrase} " in normalized_text)

    def _matched_signals(phrases: tuple[str, ...]) -> list[str]:
        return [phrase for phrase in phrases if _has_signal(phrase)]

    records_lifecycle_signals = (
        "records management",
        "records lifecycle",
        "records retention",
        "retention schedule",
        "file plan",
        "disposition",
        "nara",
        "erm 2.04",
        "federal records act",
        "records management and retention",
        "fermi",
    )
    records_transfer_signals = (
        "chain of custody",
        "records transfer",
        "records retrieval",
        "archive coordination",
        "archive retrieval",
        "record retirement",
        "retire records",
        "case file",
        "case files",
        "file room",
    )
    records_ingestion_signals = (
        "digitization",
        "scanning",
        "barcoding",
        "indexing",
        "metadata capture",
        "metadata",
        "paper record",
        "paper records",
    )
    lifecycle_hits = _matched_signals(records_lifecycle_signals)
    transfer_hits = _matched_signals(records_transfer_signals)
    ingestion_hits = _matched_signals(records_ingestion_signals)
    records_signal_total = len(set(lifecycle_hits + transfer_hits + ingestion_hits))
    records_category_hits = sum(bool(group) for group in (lifecycle_hits, transfer_hits, ingestion_hits))
    if records_category_hits >= 2 and records_signal_total >= 3:
        mission_problem = "The customer appears to need a records-heavy operating environment that can control ingestion, retention, retrieval, and multi-office workflows without breaking continuity."
        priorities.append("The requirement is about operational records control at scale, not generic document storage: the package repeatedly points to records lifecycle, retrieval, metadata, or high-volume file handling.")
        pain_points.append("If records classification, retrieval, or migration logic fails at operational scale, the customer risks disruption across multiple offices, users, or case workflows.")
        win_themes.append("Lead with records-operations credibility: show how the solution preserves retrieval fidelity, workflow continuity, and user access across large volumes and mixed record types.")
        differentiators.append("Proof that the team has supported records-heavy federal operations with measurable retrieval, metadata, and lifecycle-control discipline.")

    if lifecycle_hits:
        priorities.append("NARA and records-lifecycle compliance are core functional requirements, not background policy language: the PWS ties the solution to NARA ERM requirements, retention schedules, and disposition logic.")
        pain_points.append("A platform that cannot automate retention, disposition, and records-lifecycle controls will fail the mission even if the user interface is acceptable.")
        win_themes.append("Frame the bid around records-lifecycle control: retention calculation, disposition, metadata, and NARA-aligned governance have to be working features, not compliance promises.")
        differentiators.append("Demonstrated records-governance implementation aligned to NARA requirements and approved federal retention schedules.")

    if any(
        _has_signal(token)
        for token in ("fedramp", "fisma", "privacy act", "nist", "security controls", "ato", "authority to operate")
    ):
        priorities.append("Named security, privacy, or compliance controls appear to be part of the requirement baseline, not just general background language.")
        pain_points.append("The customer is buying an environment that has to survive security, privacy, and audit scrutiny, not just pass a technical demo.")
        win_themes.append("Show that the solution is governable in a federal environment: control inheritance, compliance evidence, and operating discipline should be first-class proof points.")
        differentiators.append("Audit-ready operating evidence for a federal environment, including control inheritance and measurable compliance routines.")

    if _has_signal("chain of custody") or len(transfer_hits) >= 2:
        priorities.append("Retrieval and chain-of-custody continuity matter because the package ties the work to records transfer, retirement, retrieval, or archive coordination.")
        pain_points.append("If the platform cannot preserve transfer and retrieval fidelity across archive or records-handoff workflows, the customer loses legal, investigative, or business-use confidence.")
        win_themes.append("Make retrieval continuity a headline theme: prove the solution can transfer, track, and retrieve records without losing control history or user confidence.")
        differentiators.append("Operating evidence for chain-of-custody, transfer, and retrieval workflows rather than generic repository administration.")

    if any(
        _has_signal(token)
        for token in ("current contractor", "transition-in", "transition out", "90-day transition", "successor contractor", "phase-in")
    ):
        priorities.append("Transition risk is concrete in this package: the successor has to stand up the new operating rhythm quickly while preserving continuity from the current execution approach.")
        pain_points.append("The buyer is exposed to continuity loss during phase-in or successor handoff, especially if knowledge transfer, access setup, or mobilization steps are weak.")
        win_themes.append("Tell a continuity story, not just a capability story: show how the team will stand up the replacement effort, inherit the operating context, and preserve continuity through transition.")
        differentiators.append("A transition plan that addresses successor take-over, knowledge transfer, access dependencies, and continuity checkpoints during phase-in.")

    if len(ingestion_hits) >= 2:
        priorities.append("This includes real ingestion and conversion work, not just light workflow support: the package points to scanning, indexing, or metadata discipline that affects downstream usability.")
        pain_points.append("Ingestion and conversion can break the program if validation, metadata capture, or handoff discipline are treated like commodity back-office tasks.")
        win_themes.append("Show industrialized ingestion: explain how conversion, validation, indexing, and metadata discipline will preserve usability from day one.")
        differentiators.append("Operational proof of high-volume ingestion, validation, and metadata-control discipline in a federal workflow.")

    support_admin_hits = _matched_signals(("help desk", "service desk", "user administration", "account provisioning"))
    reporting_hits = _matched_signals(("dashboard", "dashboards", "metrics dashboard", "status dashboard"))
    adoption_hits = _matched_signals(("end-user training", "user training", "train users"))
    governance_hits = _matched_signals(("program management office", "pmo", "service governance"))
    if support_admin_hits and (reporting_hits or adoption_hits or governance_hits):
        priorities.append("The customer is buying an operating service, not just software delivery: dashboards, help desk, training, user administration, and program management are explicit parts of scope.")
        pain_points.append("Adoption and day-two operations will matter because the platform has to be supportable by distributed users, not just deployed once.")
        win_themes.append("Position as an operating partner: combine platform delivery with dashboards, user support, training, and governance routines that make the system usable after go-live.")
        differentiators.append("A day-two operating model covering dashboards, help desk, training, administration, and user-adoption support.")

    if any(_has_signal(token) for token in ("independent audit", "soc 1", "ssae 16", "fiscam", "corrective action plan")):
        priorities.append("Independent auditability is a named requirement: the customer wants a solution that can withstand SOC/FISCAM-style review and produce corrective-action discipline.")
        pain_points.append("If operations are not evidenced cleanly enough for independent audit, the contractor will lose credibility even if the platform features look strong.")
        win_themes.append("Emphasize audit-ready operations: show how the team will support annual independent review, furnish evidence, and close findings without drama.")
        differentiators.append("Documented experience supporting independent audits, corrective-action plans, and evidence production for government-facing systems.")

    if any(
        _has_signal(token)
        for token in ("geographic information", "api", "foia", "searching in response to information requests")
    ):
        priorities.append("The requirement includes integration, search, or reporting use cases beyond a narrow transactional workflow.")
        pain_points.append("If the solution cannot expose data cleanly for downstream users, reporting, or information-response workflows, the customer will lose mission value after deployment.")
        win_themes.append("Show that the solution is usable as an operational data asset: integration, search, and reporting should be part of the story, not an afterthought.")
        differentiators.append("Proof of API, reporting, and information-response support tied directly to the operational workflow in scope.")

    return {
        "mission_problem": mission_problem,
        "priorities": _dedupe_strings(priorities),
        "pain_points": _dedupe_strings(pain_points),
        "win_themes": _dedupe_strings(win_themes),
        "differentiators": _dedupe_strings(differentiators),
    }


def _priority_analysis(
    notice_text: str,
    public_research: dict[str, Any],
    attachment_bundle: dict[str, Any],
    award_basis: str,
    contract_type: str,
) -> dict[str, list[str] | str]:
    lower = notice_text.lower()
    requirement_specific = _requirement_specific_insights(notice_text)
    has_specific = len(_string_list(requirement_specific.get("priorities", []), max_items=8)) >= 4
    evidence_backed: list[str] = []
    likely: list[str] = []
    unknowns: list[str] = []
    pain_points: list[str] = []
    repeated_language: list[str] = []
    external_pressure_signals = public_research.get("external_pressure_signals", [])
    if not isinstance(external_pressure_signals, list):
        external_pressure_signals = []
    pressure_lines = [
        f"{str(item.get('signal') or '').strip()}: {str(item.get('evidence') or '').strip()}"
        for item in external_pressure_signals
        if isinstance(item, dict) and str(item.get("signal") or "").strip() and str(item.get("evidence") or "").strip()
    ]
    pressure_categories = {
        str(item.get("category") or "").strip()
        for item in external_pressure_signals
        if isinstance(item, dict)
    }

    if _contains_any(lower, list(CONTINUITY_MARKERS)) and not has_specific:
        evidence_backed.append("Continuity of operations and low transition risk appear to matter, based on direct continuity language in the notice or attachments.")
        pain_points.append("The customer appears sensitive to service disruption, transition delay, or mission lapse risk.")
    if public_research.get("policy_compliance_signals"):
        evidence_backed.append("Requirement-specific compliance or control alignment appears important because the notice references named policy or control frameworks.")
    if ("report" in lower or "dashboard" in lower or "metrics" in lower) and not has_specific:
        evidence_backed.append("The customer appears to value measurable reporting and management visibility.")
        repeated_language.append("Reporting / metrics / visibility")
    if "staff" in lower or "key personnel" in lower:
        likely.append("Staffing continuity and named key personnel may influence credibility.")
        repeated_language.append("Staffing / personnel")
    if "license" in lower or "cots" in lower or "commercial off" in lower:
        likely.append("The customer may prefer a proven productized or COTS-led approach over bespoke build-from-scratch delivery.")
        repeated_language.append("Licensing / product support")
    if contract_type == "Firm Fixed Price":
        likely.append("Price discipline and scope control likely matter because the procurement language points to fixed-price execution.")
    if award_basis != "Evaluation basis not explicit in current evidence":
        evidence_backed.append(f"The solicitation language surfaced an award basis signal: {award_basis}.")
    if "oversight" in pressure_categories:
        evidence_backed.append("Public oversight pressure suggests the buyer will care about remediation speed, reporting discipline, and fewer execution surprises.")
        pain_points.append("The customer may be trying to reduce findings, rework, or management churn around this requirement area.")
    if "leadership" in pressure_categories or "public_discourse" in pressure_categories:
        evidence_backed.append("Leadership or testimony signals suggest this requirement area carries visible executive or public attention.")
    if "acquisition_forecast" in pressure_categories:
        likely.append("A forecast or buying-plan signal exists, which suggests the customer may already be shaping timing and acquisition path.")
    if public_research.get("mission_context_signals"):
        repeated_language.extend(_string_list(public_research.get("mission_context_signals", []), max_items=3))
    repeated_language.extend(pressure_lines[:3])
    evidence_backed = _dedupe_strings(_string_list(requirement_specific.get("priorities", []), max_items=8) + evidence_backed)
    pain_points = _dedupe_strings(_string_list(requirement_specific.get("pain_points", []), max_items=8) + pain_points)
    if not public_research.get("mission_context_signals"):
        unknowns.append("Mission problem is still inferred because no strong agency strategy or program document was captured.")
    if award_basis == "Evaluation basis not explicit in current evidence":
        unknowns.append("Evaluation weighting is still unknown because the current package did not expose factors or basis of award clearly.")
    if not public_research.get("leadership_priority_signals"):
        unknowns.append("Program-level customer priorities still need validation through named officials, industry day material, or formal Q&A.")

    mission_problem = (
        _clean_excerpt(public_research.get("mission_context_signals", [])[0], max_chars=320)
        if public_research.get("mission_context_signals")
        else str(requirement_specific.get("mission_problem") or "Mission problem is not corroborated beyond the solicitation text in current evidence.")
    )

    return {
        "mission_problem": mission_problem,
        "evidence_backed_priorities": _dedupe_strings(evidence_backed),
        "likely_priorities": _dedupe_strings(likely),
        "unknowns": _dedupe_strings(unknowns),
        "pain_points": _dedupe_strings(pain_points),
        "repeated_language": _dedupe_strings(repeated_language)[:5],
        "external_pressure_signals": _dedupe_strings(pressure_lines)[:6],
    }


def _priority_evidence_mode(
    customer_priorities: dict[str, Any],
    public_research: dict[str, Any],
    workstream_lines: list[str],
) -> str:
    core_context_anchor_count = int(public_research.get("core_context_anchor_count", 0) or 0)
    funding_or_buying_anchor_count = int(public_research.get("funding_or_buying_anchor_count", 0) or 0)
    workstream_count = len([item for item in workstream_lines if str(item or "").strip()])
    evidence_priority_count = len(_string_list(customer_priorities.get("evidence_backed_priorities", []), max_items=8))
    if workstream_count == 0 and core_context_anchor_count == 0 and funding_or_buying_anchor_count == 0:
        return "thin"
    if workstream_count >= 4 or (core_context_anchor_count >= 2 and workstream_count >= 2):
        return "strong"
    if workstream_count >= 2 or core_context_anchor_count >= 1 or funding_or_buying_anchor_count >= 1 or evidence_priority_count >= 2:
        return "moderate"
    return "thin"


def _apply_priority_evidence_gate(
    customer_priorities: dict[str, Any],
    public_research: dict[str, Any],
    workstream_lines: list[str],
) -> dict[str, Any]:
    updated = dict(customer_priorities or {})
    mode = _priority_evidence_mode(updated, public_research, workstream_lines)
    evidence_backed = _dedupe_strings(_string_list(updated.get("evidence_backed_priorities", []), max_items=8))
    likely = _dedupe_strings(_string_list(updated.get("likely_priorities", []), max_items=6))
    pain_points = _dedupe_strings(_string_list(updated.get("pain_points", []), max_items=8))
    strategic_pain_points = _dedupe_strings(_string_list(updated.get("strategic_pain_points", []), max_items=6))
    repeated_language = _dedupe_strings(_string_list(updated.get("repeated_language", []), max_items=5))
    external_pressure = _dedupe_strings(_string_list(updated.get("external_pressure_signals", []), max_items=6))

    if mode == "strong":
        updated["priority_rendering_mode"] = "strong"
        updated["priority_rendering_warning"] = ""
        return updated

    if mode == "moderate":
        updated["evidence_backed_priorities"] = evidence_backed[:4]
        updated["likely_priorities"] = likely[:2]
        updated["pain_points"] = pain_points[:3]
        updated["strategic_pain_points"] = strategic_pain_points[:2]
        updated["repeated_language"] = repeated_language[:3]
        updated["external_pressure_signals"] = external_pressure[:3]
        updated["priority_rendering_mode"] = "moderate"
        updated["priority_rendering_warning"] = MODERATE_PRIORITY_WARNING
        return updated

    updated["evidence_backed_priorities"] = [THIN_PRIORITY_EVIDENCE]
    updated["likely_priorities"] = [THIN_PRIORITY_LIKELY]
    updated["pain_points"] = [THIN_PRIORITY_PAIN]
    updated["strategic_pain_points"] = []
    updated["repeated_language"] = repeated_language[:1]
    updated["external_pressure_signals"] = external_pressure[:2]
    updated["priority_rendering_mode"] = "thin"
    updated["priority_rendering_warning"] = THIN_PRIORITY_WARNING
    if len([item for item in workstream_lines if str(item or "").strip()]) < 2:
        updated["strategic_reasoning_summary"] = ""
    return updated


def _solicitation_fact_lines(solicitation_facts: dict[str, Any]) -> list[str]:
    if not isinstance(solicitation_facts, dict):
        return []
    naics = str(solicitation_facts.get("naics") or "").strip()
    naics_title = str(solicitation_facts.get("naics_title") or "").strip()
    size_standard = str(solicitation_facts.get("naics_size_standard") or "").strip()
    return _dedupe_strings(
        [
            *([f"Set-aside: {solicitation_facts.get('set_aside')}"] if str(solicitation_facts.get("set_aside") or "").strip() else []),
            *([f"Vehicle: {solicitation_facts.get('contract_vehicle')}"] if str(solicitation_facts.get("contract_vehicle") or "").strip() else []),
            *([f"Contract type: {solicitation_facts.get('contract_type')}"] if str(solicitation_facts.get("contract_type") or "").strip() else []),
            *([f"NAICS {naics} - {naics_title}"] if naics else []),
            *([f"NAICS size standard: {size_standard}"] if size_standard else []),
            *([f"Due date: {solicitation_facts.get('due_date')}"] if str(solicitation_facts.get("due_date") or "").strip() else []),
            *([f"Evaluation basis: {solicitation_facts.get('evaluation_basis')}"] if str(solicitation_facts.get("evaluation_basis") or "").strip() else []),
            *([f"Funds status: {solicitation_facts.get('funds_status')}"] if str(solicitation_facts.get("funds_status") or "").strip() else []),
            *([f"Period of performance: {solicitation_facts.get('period_of_performance')}"] if str(solicitation_facts.get("period_of_performance") or "").strip() else []),
        ]
    )


def _workstream_lines(attachment_workstreams: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in attachment_workstreams or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        objective = str(item.get("objective") or "").strip()
        if title and objective:
            lines.append(f"{title}: {objective}")
        elif objective:
            lines.append(objective)
    return _dedupe_strings(lines)


def _current_package_strategy_anchors(
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
) -> dict[str, list[str]]:
    section_anchors: list[str] = []
    for item in attachment_workstreams or []:
        if not isinstance(item, dict):
            continue
        for snippet in _string_list(item.get("evidence_snippets", []), max_items=4):
            cleaned = _clean_excerpt(snippet, max_chars=260)
            if cleaned:
                section_anchors.append(cleaned)
    fact_anchors = _solicitation_fact_lines(solicitation_facts)
    return {
        "section_anchors": _dedupe_strings(section_anchors),
        "fact_anchors": _dedupe_strings(fact_anchors),
        "all_anchors": _dedupe_strings(section_anchors + fact_anchors),
    }


def _workstream_capture_implication_rows(
    attachment_workstreams: list[dict[str, Any]],
    solicitation_facts: dict[str, Any],
    staffing_pricing_signals: dict[str, Any],
    attachment_anomalies: list[dict[str, Any]],
    max_items: int = 5,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in attachment_workstreams or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        objective = _clean_excerpt(item.get("objective") or "", max_chars=260).strip()
        evidence_anchor = _string_list(item.get("evidence_snippets"), max_items=1)
        if not objective or not evidence_anchor:
            continue
        if title and objective.lower().startswith(title.lower()):
            text = objective
        elif title:
            text = f"{title}: {objective}"
        else:
            text = objective
        key = _normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append({"text": text, "evidence_anchor": evidence_anchor[0]})
        if len(rows) >= max_items:
            break
    if len(rows) < max_items:
        for fact in _solicitation_fact_lines(solicitation_facts):
            if any(marker in fact.lower() for marker in ("set-aside", "vehicle", "contract type", "evaluation basis", "period of performance", "funds status")):
                key = _normalize_text(fact)
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append({"text": fact, "evidence_anchor": fact})
                if len(rows) >= max_items:
                    break
    if len(rows) < max_items:
        for note in _string_list(staffing_pricing_signals.get("evaluation_notes"), max_items=3):
            key = _normalize_text(note)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({"text": note, "evidence_anchor": note})
            if len(rows) >= max_items:
                break
    if len(rows) < max_items:
        for anomaly in attachment_anomalies or []:
            if not isinstance(anomaly, dict):
                continue
            signal = str(anomaly.get("signal") or "").strip()
            source = str(anomaly.get("source") or "").strip()
            if not signal or not source:
                continue
            key = _normalize_text(signal)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({"text": signal, "evidence_anchor": source})
            if len(rows) >= max_items:
                break
    return rows


def _proof_artifact_recommendations(
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
    staffing_pricing_signals: dict[str, Any],
    attachment_anomalies: list[dict[str, Any]],
    strategic_reasoning: dict[str, Any],
) -> list[str]:
    workstream_text = " ".join(_workstream_lines(attachment_workstreams)).lower()
    anomaly_text = " ".join(str(item.get("signal") or "") for item in attachment_anomalies if isinstance(item, dict)).lower()
    staffing_roles = _string_list(solicitation_facts.get("staffing_roles", []), max_items=8)
    artifacts = _dedupe_strings(
        [
            *(
                [f"Staffing matrix mapped to the visible roles, coverage periods, and workstreams: {', '.join(staffing_roles)}."]
                if staffing_roles
                else []
            ),
            *(
                ["Transition and day-one-readiness annex covering access steps, onboarding dependencies, and first-30-day operating rhythm."]
                if "transition" in workstream_text or "continuity" in workstream_text or str(solicitation_facts.get("transition_window") or "").strip()
                else []
            ),
            *(
                ["Sample reporting package with PSR cadence, issue log, QA/QC loop, and corrective-action format."]
                if any(marker in workstream_text for marker in ("psr", "report", "dashboard", "qa/qc", "quality"))
                else []
            ),
            *(
                ["CLIN or pricing trace showing labor mix, option periods, and evaluated-price logic."]
                if "pricing sheet" in anomaly_text or "spreadsheet" in anomaly_text or "firm fixed price" in str(solicitation_facts.get("contract_type") or "").lower()
                else []
            ),
            *(
                ["Acceptance-threshold or AQL crosswalk tied to QC actions, reporting triggers, and remedy avoidance."]
                if "acceptance" in anomaly_text or "aql" in anomaly_text or "remedy" in anomaly_text
                else []
            ),
            *(
                ["Controlling-document matrix reconciling RFQ, PWS, amendments, and Q&A conflicts before proposal lock."]
                if "cross-document conflict" in anomaly_text or "attachment-count mismatch" in anomaly_text or "page-limit conflict" in anomaly_text
                else []
            ),
            *(
                ["Eligibility proof pack covering set-aside status, vehicle access, and contract-type execution posture."]
                if str(solicitation_facts.get("set_aside") or "").strip() or str(solicitation_facts.get("contract_vehicle") or "").strip()
                else []
            ),
            *_string_list(strategic_reasoning.get("proof_requirements", []), max_items=4),
            *_string_list(staffing_pricing_signals.get("pricing_notes", []), max_items=2),
        ]
    )
    return artifacts[:8]


def _best_strategy_anchor(text: str, anchors: list[str], min_overlap: int = 2) -> str:
    reference_tokens = _signal_tokens(text)
    if not reference_tokens:
        return ""
    ranked = sorted(
        (
            (len(reference_tokens & _signal_tokens(anchor)), len(anchor), anchor)
            for anchor in anchors
            if str(anchor or "").strip()
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    if not ranked or ranked[0][0] < min_overlap:
        return ""
    return _clean_excerpt(ranked[0][2], max_chars=240)


def _anchor_strategy_lines(
    lines: list[str],
    anchors: list[str],
    *,
    fallback: str,
    max_items: int = 6,
    min_overlap: int = 2,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in _dedupe_strings(lines):
        anchor = _best_strategy_anchor(line, anchors, min_overlap=min_overlap)
        if not anchor:
            continue
        rows.append({"text": line, "evidence_anchor": anchor})
        if len(rows) >= max_items:
            break
    if rows:
        return rows
    return [{"text": fallback, "evidence_anchor": ""}]


def _strategy_row_texts(rows: list[dict[str, str]]) -> list[str]:
    return _dedupe_strings([str(item.get("text") or "").strip() for item in rows if isinstance(item, dict)])


def _prune_generic_strategy_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    specific_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and not any(str(row.get("text") or "").strip().lower().startswith(prefix) for prefix in GENERIC_STRATEGY_TEMPLATE_PREFIXES)
    ]
    return specific_rows or rows


def _operational_constraint_lines(
    solicitation_facts: dict[str, Any],
    staffing_pricing_signals: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
) -> list[str]:
    staffing_notes = _string_list(staffing_pricing_signals.get("staffing_notes", []), max_items=6)
    pricing_notes = _string_list(staffing_pricing_signals.get("pricing_notes", []), max_items=6)
    workstream_text = " ".join(_workstream_lines(attachment_workstreams)).lower()
    constraints = _dedupe_strings(
        staffing_notes
        + pricing_notes
        + (
            ["The visible workstreams are operational rather than purely advisory, so day-one on-site execution credibility matters."]
            if "on-site" in workstream_text
            else []
        )
        + (
            [f"Timing caveat: {solicitation_facts.get('funds_status')}"]
            if str(solicitation_facts.get("funds_status") or "").strip()
            else []
        )
    )
    return constraints[:8]


def _strategic_capture_reasoning(
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
    staffing_pricing_signals: dict[str, Any],
    attachment_anomalies: list[dict[str, Any]],
    contract_type: str,
    award_basis: str,
) -> dict[str, Any]:
    workstream_lines = _workstream_lines(attachment_workstreams)
    workstream_text = " ".join(workstream_lines).lower()
    staffing_notes = _string_list(staffing_pricing_signals.get("staffing_notes", []), max_items=8)
    pricing_notes = _string_list(staffing_pricing_signals.get("pricing_notes", []), max_items=8)
    anomaly_signals = [
        str(item.get("signal") or "").strip()
        for item in attachment_anomalies or []
        if isinstance(item, dict) and str(item.get("signal") or "").strip()
    ]
    security_visible = any(
        marker in workstream_text or any(marker in note.lower() for note in staffing_notes)
        for marker in ("af form 1199", "leads", "naci", "cac", "clearance", "nda", "fouo")
    )
    acquisition_support_visible = any(marker in workstream_text for marker in ("dd 1391", "acquisition-package", "sow", "pws", "soo", "cost estimate"))
    reporting_visible = any(marker in workstream_text for marker in ("psr", "project status report", "qa/qc", "presentation materials"))
    furnishings_visible = any(marker in workstream_text for marker in ("furnishings", "dorm", "warehouse"))
    on_site_visible = any(marker in workstream_text for marker in ("on-site", "on site", "site access", "delivery continuity", "field-facing"))

    central_pain_point = (
        "The buyer is not just buying labor. It is buying a delivery team that can become operational quickly where the work happens, keep requirement workstreams moving, maintain clean documentation and QA/QC discipline, and avoid mission friction from staffing, access, or transition delays."
        if on_site_visible
        else "The buyer appears to want low-drama execution certainty more than generic staff augmentation."
    )
    reasoning_summary_parts = [
        central_pain_point,
        *(
            ["Continuity matters because this team has to be physically present or access-gated and productive quickly; a bidder that cannot stand up operations fast will lose credibility even before technical scoring differentiates."]
            if on_site_visible and security_visible
            else []
        ),
        *(
            ["The work also touches planning, package development, or review support, so the customer likely cares about boundaries, approvals, and decision-authority clarity, not just technical competence."]
            if acquisition_support_visible
            else []
        ),
        *(
            ["The repeated PSR, task-hierarchy, and QA/QC signals suggest the customer is trying to reduce rework, documentation churn, and project-control noise as much as it is buying labor hours."]
            if reporting_visible
            else []
        ),
        *(
            ["A specialized support function appears in the staffing mix and may be underweighted by otherwise-credible bidders; that creates a practical differentiator if treated as part of mission continuity rather than an afterthought."]
            if furnishings_visible
            else []
        ),
    ]
    reasoned_pain_points = _dedupe_strings(
        [
            *(
                ["Day-one site or facility execution is a likely evaluator anxiety because the labor mix is visible and the work is not purely remote or back-office."]
                if on_site_visible
                else []
            ),
            *(
                ["Access, credentialing, clearance, or information-handling friction can break continuity even if the technical narrative is strong."]
                if security_visible
                else []
            ),
            *(
                ["Package or deliverable throughput and documentation discipline likely matter because the contractor is helping move scoped artifacts through the customer's approval pipeline."]
                if acquisition_support_visible
                else []
            ),
            *(
                ["The customer likely wants fewer project-control surprises, not just more bodies, because the PWS leans hard on PSR cadence, task hierarchy, files, and deliverable review."]
                if reporting_visible
                else []
            ),
            *(
                ["A specialized support function is part of the mission load and can become a credibility gap if treated like generic admin support."]
                if furnishings_visible
                else []
            ),
        ]
    )
    reasoned_win_themes = _dedupe_strings(
        [
            *(
                ["Ready on day one where the work happens: make staffing, access, and operating-rhythm readiness the proof point, not an appendix."]
                if on_site_visible
                else []
            ),
            *(
                ["Requirement throughput with documented discipline: show how the team will move scoped deliverables through planning, review, and reporting workflows without rework."]
                if acquisition_support_visible or reporting_visible
                else []
            ),
            *(
                ["QA/QC that protects mission outcomes and rework budgets: the buyer appears to want fewer defects and less churn, not just technically acceptable support."]
                if reporting_visible
                else []
            ),
            *(
                ["No-drama access and security compliance: make site access, credentialing, clearance, and handling controls part of the core solution story."]
                if security_visible
                else []
            ),
            *(
                ["Clean boundary management while still adding value: make decision authority and sensitive-information handling visibly safe."]
                if acquisition_support_visible
                else []
            ),
            *(
                ["Treat specialized support functions as part of mission continuity, not side work."]
                if furnishings_visible
                else []
            ),
        ]
    )
    reasoned_differentiators = _dedupe_strings(
        [
            *(
                [f"Named or contingent-hired core staff for the visible labor mix: {', '.join(_string_list(solicitation_facts.get('staffing_roles', []), max_items=8))}."]
                if _string_list(solicitation_facts.get("staffing_roles", []), max_items=8)
                else []
            ),
            *(
                ["A requirement-specific transition and access plan covering credentialing dependencies, workstation or tool readiness, and the first-30-day operating rhythm."]
                if security_visible
                else []
            ),
            *(
                ["A one-page OCI and sensitive-information protocol that states what the team will and will not do when supporting acquisition-package and review activities."]
                if acquisition_support_visible
                else []
            ),
            *(
                ["A sample monthly PSR and QA/QC control loop tailored to the task hierarchy, issues, benchmarks, and corrective actions visible in the PWS."]
                if reporting_visible
                else []
            ),
            *(
                ["A role-specific continuity playbook so any specialized support function does not look like an afterthought."]
                if furnishings_visible
                else []
            ),
            *(
                ["A realistic fixed-price posture that looks executable for the surfaced labor mix and performance periods."]
                if contract_type == "Firm Fixed Price"
                else []
            ),
        ]
    )
    proof_requirements = _dedupe_strings(
        reasoned_differentiators
        + [
            *(
                ["Do not rely on generic corporate brand language; prove local execution, project-control discipline, and staffing realism."]
                if on_site_visible
                else []
            ),
            *(
                ["Because the solicitation is best value, a tighter technical story and safer execution posture may beat a cheaper but thinner staffing plan."]
                if "best value" in award_basis.lower()
                else []
            ),
        ]
    )
    pricing_posture = _dedupe_strings(
        pricing_notes
        + [
            *(
                ["This reads like a lean execution-heavy support order, not a giant program, so bloated indirect structure will be harder to hide."]
                if contract_type == "Firm Fixed Price"
                else []
            ),
            *(
                ["Optional engineer CLINs should be priced like real surge capacity, not as a recovery mechanism for an underbid base."]
                if "option year" in str(solicitation_facts.get("period_of_performance") or "").lower() or _string_list(solicitation_facts.get("staffing_roles", []), max_items=8)
                else []
            ),
        ]
    )
    risk_implications = _dedupe_strings(
        [
            *(
                ["Because the technical page limit is ambiguous, write the technical volume to the stricter interpretation unless a formal clarification exists."]
                if any("page-limit" in signal.lower() for signal in anomaly_signals)
                else []
            ),
            *(
                ["Missing Q&A, PPQ, and wage attachments increase compliance risk more than they change the core solution story."]
                if any("declared attachments" in signal.lower() for signal in anomaly_signals)
                else []
            ),
            *(
                ["The funding caveat means the team should avoid irreversible pre-award commitments even if it decides to pursue."]
                if str(solicitation_facts.get("funds_status") or "").strip()
                else []
            ),
        ]
    )
    return {
        "central_pain_point": central_pain_point,
        "reasoning_summary": " ".join(_dedupe_strings(reasoning_summary_parts)),
        "reasoned_pain_points": reasoned_pain_points,
        "reasoned_win_themes": reasoned_win_themes,
        "reasoned_differentiators": reasoned_differentiators,
        "proof_requirements": proof_requirements,
        "pricing_posture": pricing_posture,
        "risk_implications": risk_implications,
    }


def _reasoned_competitor_hypotheses(
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
) -> list[dict[str, str]]:
    naics = str(solicitation_facts.get("naics") or "").strip()
    set_aside = str(solicitation_facts.get("set_aside") or "").lower()
    vehicle = str(solicitation_facts.get("contract_vehicle") or "").lower()
    workstream_text = " ".join(_workstream_lines(attachment_workstreams)).lower()
    if naics != "541330" and "engineering" not in workstream_text:
        return []
    if "small business" not in set_aside or "oasis" not in vehicle:
        return []
    return []


def _funding_analysis(
    funding_assessment: dict[str, Any],
    award_signals: dict[str, Any],
    public_research: dict[str, Any],
    attachment_bundle: dict[str, Any],
    evidence_gaps: list[str],
) -> dict[str, Any]:
    useful_awards = bool(funding_assessment.get("useful_award_history"))
    useful_budget_docs = bool(funding_assessment.get("useful_budget_documents"))
    useful_attachment_budget = bool(funding_assessment.get("useful_attachment_budget"))
    if useful_awards and useful_budget_docs:
        confidence = "High"
    elif useful_awards or useful_budget_docs or useful_attachment_budget:
        confidence = "Medium"
    else:
        confidence = "Low"

    relevant_awards = award_signals.get("relevant_awards", []) or []
    if len(relevant_awards) >= 3:
        trend = "Recurring demand is visible in related award history, but exact growth or decline still needs tighter time-series analysis."
    elif relevant_awards:
        trend = "Some comparable spending is visible, which supports durability, but the trend line is still thin."
    else:
        trend = "Trend direction is unclear because clearly relevant award history was not surfaced."

    timing_risk: list[str] = []
    categories = Counter(
        str(item.get("category", "other"))
        for item in (attachment_bundle.get("attachments", []) or [])
        if isinstance(item, dict)
    )
    if categories.get("amendment"):
        timing_risk.append("Amendments are present, which can signal moving requirements or schedule drift.")
    if not public_research.get("budget_document_signals"):
        timing_risk.append("No official budget document was captured, so funding timing still depends heavily on award-history inference.")
    if not relevant_awards:
        timing_risk.append("Award-history evidence is thin, which limits confidence in timing and durability.")

    evidence = _dedupe_strings(
        _string_list(award_signals.get("budget_signals", []), max_items=3)
        + _string_list(public_research.get("budget_document_signals", []), max_items=2)
        + _string_list(public_research.get("acquisition_forecast_signals", []), max_items=1)
        + (
            ["Attachment package includes pricing, schedule, or amendment artifacts that can be used for direct funding validation."]
            if useful_attachment_budget
            else []
        )
    )
    if not evidence:
        timing_risk.append("No corroborated funding evidence was found in this run; timing and durability remain assumptions until validated.")
    open_questions = _dedupe_strings(
        [
            *_string_list(funding_assessment.get("gap_notes", []), max_items=2),
            *([gap for gap in evidence_gaps if "budget" in gap.lower() or "fund" in gap.lower()][:2]),
            "Is there a named budget line, forecast item, or obligated predecessor contract that directly maps to this requirement?",
        ]
    )
    return {
        "funding_confidence": confidence,
        "trend_direction": trend,
        "risk_to_timing_or_award": _dedupe_strings(timing_risk) or ["No major timing risk surfaced beyond normal procurement uncertainty."],
        "evidence": evidence,
        "open_questions": open_questions,
    }


def _requirement_type(notice_type: str, notice_text: str) -> str:
    lower = notice_text.lower()
    if "bridge" in lower:
        return "Bridge / interim continuity action"
    if "follow-on" in lower or "recompete" in lower or "continuation" in lower:
        return "Likely follow-on / recompete"
    if "single award task order contract" in lower or "satoc" in lower or "indefinite-delivery-indefinite-quantity" in lower or "indefinite delivery indefinite quantity" in lower:
        if "presolicitation" in notice_type.lower():
            return "Presolicitation for new IDIQ / SATOC procurement"
        return "New IDIQ / SATOC competitive procurement"
    if "draft rfp" in lower or "sources sought" in lower or "request for information" in lower:
        return "Requirement still being shaped"
    if "amendment" in lower:
        return "Live competitive procurement with amendments"
    if notice_type:
        return f"Public notice type: {notice_type}"
    return "Requirement type still unclear"


def _incumbent_analysis(
    notice_text: str,
    award_signals: dict[str, Any],
    attachment_validation: dict[str, Any],
    attachment_bundle: dict[str, Any],
) -> dict[str, Any]:
    validated_incumbents = _string_list(attachment_validation.get("validated_incumbents", []))
    likely_incumbents = _string_list((award_signals.get("competitive_landscape", {}) or {}).get("likely_incumbents", []))
    incumbent_name = (validated_incumbents or likely_incumbents or ["No confirmed incumbent"])[0]
    direct_validation = bool(validated_incumbents or attachment_validation.get("direct_mentions"))
    source_basis = (
        "Directly named in the notice or parsed attachment package."
        if direct_validation
        else "Inferred from related public award history; this remains a hypothesis until validated."
    )

    relevant_awards = award_signals.get("relevant_awards", []) or []
    incumbent_award = None
    for row in relevant_awards:
        if incumbent_name != "No confirmed incumbent" and _normalize_text(row.get("Recipient Name", "")) == _normalize_text(incumbent_name):
            incumbent_award = row
            break
    if incumbent_award is None and relevant_awards:
        incumbent_award = relevant_awards[0]

    strength_signals: list[str] = []
    vulnerability_signals: list[str] = []
    prior_selection_hypotheses: list[str] = []

    lower = notice_text.lower()
    if _contains_any(lower, list(CONTINUITY_MARKERS)):
        if incumbent_name == "No confirmed incumbent":
            strength_signals.append(
                "Continuity language suggests the customer is sensitive to transition risk, but the current evidence does not confirm which performer benefits most from that posture."
            )
            prior_selection_hypotheses.append(
                "If this is a true follow-on, low transition risk and legacy environment familiarity were likely meaningful selection factors."
            )
        else:
            strength_signals.append(
                "Continuity language suggests the customer is sensitive to transition risk, which can favor an incumbent or other deeply embedded performer."
            )
            prior_selection_hypotheses.append("A likely prior discriminator was low transition risk and legacy environment familiarity.")
    if incumbent_award:
        strength_signals.append(
            f"Related award history points to {incumbent_award.get('Recipient Name', 'the likely performer')} under award {incumbent_award.get('Award ID', 'N/A')} for {_currency(incumbent_award.get('Award Amount'))}."
        )
    if "actively competed" in lower or "follow-on procurement" in lower:
        vulnerability_signals.append("The notice references a follow-on or active competition, which creates an opening if the customer wants better value or cleaner transition planning.")
    if "amendment" in lower or attachment_bundle.get("attachments"):
        vulnerability_signals.append("Amendments and Q&A activity can reveal customer dissatisfaction, unresolved ambiguity, or shifting requirements that weaken pure continuity arguments.")
    if not direct_validation:
        vulnerability_signals.append("Incumbent identity is not fully proven from the solicitation package yet, which means the public record may be overstating a specific competitor's advantage.")
    if not prior_selection_hypotheses:
        prior_selection_hypotheses.append("The public record suggests agency familiarity, relevant past performance, and execution continuity were likely meaningful.")

    return {
        "incumbent_name": incumbent_name,
        "source_basis": source_basis,
        "contract_number": incumbent_award.get("Award ID", "Not confirmed") if isinstance(incumbent_award, dict) else "Not confirmed",
        "awarding_agency": (
            f"{incumbent_award.get('Awarding Agency', '')} / {incumbent_award.get('Awarding Sub Agency', '')}".strip(" /")
            if isinstance(incumbent_award, dict)
            else "Not confirmed"
        ),
        "total_obligated_amount": _currency(incumbent_award.get("Award Amount")) if isinstance(incumbent_award, dict) else "Not confirmed",
        "scope_summary": _clean_excerpt(incumbent_award.get("Description", ""), max_chars=220) if isinstance(incumbent_award, dict) else "Not confirmed",
        "strength_signals": _dedupe_strings(strength_signals),
        "vulnerability_signals": _dedupe_strings(vulnerability_signals),
        "prior_selection_hypotheses": _dedupe_strings(prior_selection_hypotheses),
        "known_subcontractors": _string_list((award_signals.get("competitive_landscape", {}) or {}).get("common_teammates", [])),
    }


def _stakeholder_analysis(
    buyer: str,
    stakeholder_contacts: list[dict[str, str]],
    opportunity: dict[str, Any],
    public_research: dict[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    active_procurement = str(opportunity.get("due_date", "") or "").strip() != ""
    contact_history_rows = public_research.get("stakeholder_contact_history", []) if isinstance(public_research.get("stakeholder_contact_history"), list) else []
    contact_history_by_key: dict[str, dict[str, Any]] = {}
    for item in contact_history_rows:
        if not isinstance(item, dict):
            continue
        name_key = _normalize_text(item.get("name", ""))
        email_key = str(item.get("email", "") or "").strip().lower()
        if name_key:
            contact_history_by_key[name_key] = item
        if email_key:
            contact_history_by_key[email_key] = item
    for contact in stakeholder_contacts:
        role = str(contact.get("role", "") or "Contact").strip()
        influence = "Contracting process / communication"
        question = "Confirm the final communication path, amendment cadence, and proposal instructions."
        history_row = contact_history_by_key.get(str(contact.get("email", "") or "").strip().lower()) or contact_history_by_key.get(
            _normalize_text(contact.get("name", ""))
        )
        history = str(history_row.get("summary") or "").strip() if isinstance(history_row, dict) else ""
        if "program" in role.lower() or "technical" in role.lower() or "project" in role.lower():
            influence = "Program scope / technical expectations"
            question = "Clarify the operational pain point, transition expectations, and performance metrics."
        elif "small business" in role.lower():
            influence = "Socioeconomic posture / outreach"
            question = "Clarify set-aside posture, small-business participation goals, and approved outreach channels."
        elif "contract" in role.lower() and history:
            influence = "Contracting process / communication and prior buying pattern"
            question = "Validate amendment cadence, submission path, and whether prior buying patterns imply a vehicle, set-aside, or continuity bias."
        contact_value = str(contact.get("email", "") or "Public contact not parsed").strip()
        if str(contact.get("phone", "") or "").strip():
            contact_value = f"{contact_value} | {str(contact.get('phone', '')).strip()}"
        rows.append(
            {
                "name": str(contact.get("name", "") or "Unnamed contact").strip(),
                "role": role,
                "contact": contact_value,
                "influence": influence,
                "capture_question": question,
                "communication": "Formal Q&A only during active solicitation." if active_procurement else "Use official industry outreach channels only.",
                "history": history or "No public contact-history signal surfaced in this run.",
            }
        )
    if rows:
        return rows

    for index, segment in enumerate([part.strip() for part in str(buyer or "").split(".") if part.strip()][:3], start=1):
        rows.append(
            {
                "name": segment,
                "role": "Buyer organization",
                "contact": "No named public contact parsed in this run",
                "influence": "Likely stakeholder chain inferred from buyer metadata",
                "capture_question": "Identify the real program owner, contracting lead, and evaluation chain.",
                "communication": "Use official procurement channels only.",
                "history": "No named public contact-history signal surfaced in this run.",
            }
        )
    return rows


def _competitive_analysis(
    award_signals: dict[str, Any],
    normalized_evidence: dict[str, Any],
    incumbent_name: str,
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    workstream_tokens = _signal_tokens(" ".join(_workstream_lines(attachment_workstreams)))
    vehicle_text = str(solicitation_facts.get("contract_vehicle") or "").strip()
    set_aside_text = str(solicitation_facts.get("set_aside") or "").strip()

    for candidate in evidence_model_competitor_candidates(normalized_evidence, max_items=8):
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        role = str(candidate.get("role") or "likely_bidder").replace("_", " ").strip()
        strengths = _string_list(candidate.get("strengths"), max_items=4)
        weaknesses = _string_list(candidate.get("weaknesses"), max_items=4)
        evidence = _string_list(candidate.get("evidence"), max_items=4)
        rows.append(
            {
                "name": name,
                "role": role,
                "why_likely": str(candidate.get("rationale") or "Cross-source evidence surfaced this company as a likely competitor.").strip(),
                "strengths": " ".join(strengths) or "Cross-source evidence suggests relevant position or predecessor knowledge.",
                "weaknesses": " ".join(weaknesses) or "Still needs direct validation against the current solicitation package.",
                "likely_strategy": (
                    "Likely to lean on continuity, predecessor context, and advantaged access."
                    if "incumbent" in role
                    else "Likely to emphasize adjacent past performance, vehicle access, or customer familiarity."
                ),
                "partner_relevance": (
                    "Potential partner only if its vehicle or customer position fills a real gap."
                    if "partner" in role
                    else "Low as a likely prime competitor."
                ),
                "evidence": " | ".join(evidence) or "Cross-source normalized competitive signal.",
            }
        )

    relevant_awards = award_signals.get("relevant_awards", []) or []
    adjacent_awards = award_signals.get("adjacent_awards", []) or []
    agency_matched = [award for award in relevant_awards if award.get("_agency_match")]
    candidate_awards = (agency_matched or relevant_awards) + [award for award in adjacent_awards if isinstance(award, dict)]
    for award in candidate_awards:
        name = str(award.get("Recipient Name", "") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        agency_match = bool(award.get("_agency_match"))
        overlap = len(workstream_tokens & _signal_tokens(award.get("Description", "")))
        role = (
            "incumbent advantaged"
            if incumbent_name and _normalize_text(name) == _normalize_text(incumbent_name)
            else "likely bidder"
            if agency_match
            else "adjacent bidder"
        )
        strengths: list[str] = []
        weaknesses: list[str] = []
        if agency_match:
            strengths.append("Public award history shows the same agency or bureau.")
        else:
            weaknesses.append("Public match appears adjacent rather than same-customer, so direct customer intimacy is not yet proven.")
        if incumbent_name and _normalize_text(name) == _normalize_text(incumbent_name):
            strengths.append("Appears to hold the strongest public incumbency signal.")
        else:
            weaknesses.append("No direct incumbency proof surfaced in the current run.")
        if overlap >= 2:
            strengths.append("Award description overlaps with current requirement workstreams.")
        if vehicle_text:
            strengths.append(f"Validate whether this firm already holds or accesses {vehicle_text}.")
        if set_aside_text and "small business" in set_aside_text.lower():
            strengths.append(f"Socioeconomic posture may matter because the package signals {set_aside_text}.")
        description = _clean_excerpt(award.get("Description", ""), max_chars=180)
        rows.append(
            {
                "name": name,
                "role": role,
                "why_likely": f"Matched award {award.get('Award ID', 'N/A')} for {_currency(award.get('Award Amount'))}; scope overlap appears in public award description.",
                "strengths": " ".join(_dedupe_strings(strengths)) or "Relevant performer in adjacent public award history.",
                "weaknesses": " ".join(_dedupe_strings(weaknesses)) or "No clear weakness surfaced in public data; validation still needed.",
                "likely_strategy": f"Likely to emphasize {'continuity and agency familiarity' if agency_match else 'adjacent domain credibility and relevant scale'}.",
                "partner_relevance": "Low as a likely prime competitor unless the firm is clearly positioned as a subcontractor on this procurement.",
                "evidence": description or "Public award description not returned.",
            }
        )
        if len(rows) >= 8:
            break
    return rows


def _subtle_signals(
    notice_text: str,
    opportunity: dict[str, Any],
    attachment_bundle: dict[str, Any],
    public_research: dict[str, Any],
    funding_confidence: str,
    vehicle_mentions: list[str],
) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    lower = notice_text.lower()
    days_until_due = opportunity.get("days_until_due")
    if _contains_any(lower, list(CONTINUITY_MARKERS)):
        signals.append(
            {
                "signal": "Continuity / legacy protection language",
                "why_it_matters": "This often signals low tolerance for transition risk and a bias toward teams that can prove stable, low-disruption delivery.",
                "effect": "Hurts teams that cannot show a concrete transition and staffing story.",
                "confidence": "High",
                "source": "SAM notice and parsed attachment text",
            }
        )
    if Counter(str(item.get("category", "other")) for item in (attachment_bundle.get("attachments", []) or [])).get("amendment"):
        signals.append(
            {
                "signal": "Active amendment pattern",
                "why_it_matters": "Amendments often mean the requirement is still moving, which can create Q&A leverage and expose weak spots in the incumbent story.",
                "effect": "Neutral to helpful.",
                "confidence": "Medium",
                "source": "Parsed amendment files in the attachment package",
            }
        )
    if isinstance(days_until_due, (int, float)) and float(days_until_due) <= 14:
        signals.append(
            {
                "signal": "Compressed response window",
                "why_it_matters": "Short timelines disproportionately help incumbents and pre-positioned teams because solutioning, teaming, and pricing have to move immediately.",
                "effect": "Hurts us.",
                "confidence": "High",
                "source": "Opportunity due date in the scan record",
            }
        )
    if vehicle_mentions:
        signals.append(
            {
                "signal": "Vehicle / ordering language",
                "why_it_matters": "Vehicle access can be the first real gate. If the vehicle is closed or teammate-only, prime posture may not be credible.",
                "effect": "Neutral until access is confirmed.",
                "confidence": "Medium",
                "source": "Notice and attachment vehicle references",
            }
        )
    if funding_confidence == "Low":
        signals.append(
            {
                "signal": "Thin public funding proof",
                "why_it_matters": "Capture can still proceed, but timing, scope durability, and price-to-win confidence remain weaker until budget or predecessor data is confirmed.",
                "effect": "Hurts us.",
                "confidence": "Medium",
                "source": "Funding and award-history enrichment results",
            }
        )
    if public_research.get("oversight_signals"):
        signals.append(
            {
                "signal": "Oversight or audit pressure in public record",
                "why_it_matters": "Oversight pressure usually sharpens customer hot buttons around controls, reporting, remediation speed, and low-drama execution.",
                "effect": "Helps us if we can prove compliance and operational discipline.",
                "confidence": "Medium",
                "source": "Public oversight and agency context sources",
            }
        )
    for item in public_research.get("external_pressure_signals", []) or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        signal = str(item.get("signal") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        why = str(item.get("why_it_matters") or "").strip()
        if not category or not signal or not evidence:
            continue
        if category not in {"leadership", "public_discourse", "acquisition_forecast"}:
            continue
        signals.append(
            {
                "signal": signal,
                "why_it_matters": why or "Requirement-bearing external pressure signal surfaced in this run.",
                "effect": "Helpful when the capture story aligns directly to this pressure.",
                "confidence": "Medium",
                "source": evidence,
            }
        )
    return signals


def _evidence_ledger(source_log: list[dict[str, Any]]) -> list[dict[str, str]]:
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(
        source_log,
        key=lambda row: (
            -int(row.get("confidence", 0) or 0),
            int(row.get("tier", 99) or 99),
            str(row.get("title", "") or ""),
        ),
    ):
        url = str(item.get("url", "") or "").strip()
        title = str(item.get("title", "") or "Untitled source").strip()
        key = f"{title.lower()}::{url.lower()}"
        if key in seen:
            continue
        seen.add(key)
        source_type = "Primary government source"
        if "usaspending" in url.lower():
            source_type = "Award history"
        elif "sam.gov" in url.lower():
            source_type = "SAM notice / attachment"
        elif "gao.gov" in url.lower() or "oig" in url.lower():
            source_type = "Oversight"
        ranked.append(
            {
                "source_type": source_type,
                "title": title,
                "date": str(item.get("published_date", "") or item.get("accessed_date", "") or "N/A"),
                "link": url or "N/A",
                "what_it_proves": _clean_excerpt(item.get("relevance", "") or "Supporting evidence", max_chars=180),
                "confidence": str(item.get("confidence", 0) or 0),
            }
        )
        if len(ranked) >= 12:
            break
    return ranked


def _document_inventory(
    attachment_bundle: dict[str, Any],
    source_log: list[dict[str, Any]],
    evidence_gaps: list[str],
) -> dict[str, list[str]]:
    attachments = attachment_bundle.get("attachments", []) or []
    found = [
        f"{item.get('filename', 'Unnamed file')} [{item.get('category', 'other')}]"
        for item in attachments
        if isinstance(item, dict)
    ]
    parsed = [
        f"{item.get('filename', 'Unnamed file')} [{item.get('category', 'other')}]"
        for item in attachments
        if isinstance(item, dict) and str(item.get("parser_status", "") or "").lower().startswith("parsed")
    ]
    inaccessible = _string_list(attachment_bundle.get("errors", []))
    missing: list[str] = []
    controlled: list[str] = []
    review_required: list[str] = []
    structured_review_needed = False
    if attachment_bundle.get("attachments_expected") and not attachments:
        missing.append("Attachment package was expected, but no files were parsed in this run.")
    for item in attachments:
        if not isinstance(item, dict):
            continue
        flags = [str(flag) for flag in (item.get("analysis_flags", []) or []) if str(flag).strip()]
        if any(flag in {"table_or_matrix_heavy", "clin_or_task_matrix_visible", "acceptance_or_aql_visible", "incentive_or_remedy_visible", "pricing_sheet_or_rate_table"} for flag in flags):
            structured_review_needed = True
        if bool(item.get("review_required")):
            review_required.append(
                f"{item.get('filename', 'Unnamed file')} [{item.get('category', 'other')}] needs OCR / structured-table review ({', '.join(flags[:4])})."
            )
    for gap in evidence_gaps:
        if "attachment" in gap.lower() or "document" in gap.lower() or "q&a" in gap.lower():
            missing.append(gap)
    for item in source_log:
        title = str(item.get("title", "") or "").lower()
        if "attachment" in title and int(item.get("confidence", 0) or 0) <= 1:
            controlled.append(str(item.get("title", "") or "Controlled source"))
    action_items = _dedupe_strings(
        [
            "Retrieve the final SOW/PWS, amendments, Q&A, and pricing attachments if any are missing or only partially parsed.",
            "Confirm whether any controlled or expired attachment links require manual download from the notice workspace.",
            *(
                ["Run OCR or manual section extraction on the table-heavy or thinly parsed files before trusting objective decomposition, CLIN logic, or pricing posture."]
                if review_required
                else []
            ),
            *(
                ["Run structured review on CLIN tables, acceptance/AQL sections, and pricing matrices before treating the capture memo as decision-grade."]
                if structured_review_needed
                else []
            ),
        ]
    )
    return {
        "found": found or ["No attachments or downloadable documents were surfaced in this run."],
        "parsed": parsed or ["No attachment parsed cleanly enough to rely on as a scope source."],
        "missing": _dedupe_strings(missing) or ["No specific missing document was proven, but the full package still needs manual completeness review."],
        "inaccessible": _dedupe_strings(inaccessible + review_required) or ["No explicit access error was logged."],
        "controlled": controlled or ["No controlled-source document was explicitly flagged in this run."],
        "action_items": action_items,
    }


def _capability_fit(
    profile: dict[str, Any],
    buyer: str,
    opportunity: dict[str, Any],
    notice_text: str,
    customer_priorities: dict[str, Any],
    solicitation_facts: dict[str, Any],
    vehicle_access_paths: list[str],
    set_aside_text: str,
    vehicle_access_ok: bool,
    vehicle_access_required: bool,
    set_aside_access_ok: bool,
    qualification_gaps: dict[str, list[str]],
) -> dict[str, Any]:
    keywords = _profile_keywords(profile)
    negative_keywords = _profile_negative_keywords(profile)
    fit_guidance = _fit_narrative_guidance(profile)
    positive_terms = [
        term
        for term in fit_guidance.get("positive_terms", [])
        if "buyers such as" not in term.lower() and not _looks_like_buyer_phrase(term)
    ]
    past_performance = _profile_past_performance(profile)
    profile_naics = _profile_naics(profile)
    opportunity_naics = [str(item).strip() for item in (opportunity.get("naics", []) or []) if str(item).strip()]
    capability_hits = _dedupe_strings(
        _phrase_hits(notice_text, keywords, max_items=8)
        + _phrase_hits(notice_text, positive_terms, max_items=4)
    )[:8]
    negative_hits = _dedupe_strings(
        _phrase_hits(notice_text, negative_keywords, max_items=5)
        + _phrase_hits(notice_text, fit_guidance.get("negative_terms", []), max_items=4)
    )[:6]
    past_performance_hits = _phrase_hits(notice_text, past_performance, max_items=4)
    naics_match = bool(set(profile_naics) & set(opportunity_naics))
    fit_weighting = _profile_fit_weighting(
        profile,
        buyer,
        opportunity,
        notice_text,
        solicitation_facts,
        vehicle_access_paths,
        set_aside_text,
        capability_hits,
        negative_hits,
        past_performance_hits,
    )

    proof_points = _dedupe_strings(
        capability_hits
        + past_performance_hits
        + fit_weighting.get("positive_theme_hits", [])
        + fit_weighting.get("signals", [])[:2]
    )

    missing_proof: list[str] = []
    if not past_performance:
        missing_proof.append("No user-provided past performance highlights were available to map against likely evaluation criteria.")
    if not naics_match and opportunity_naics:
        missing_proof.append(f"Profile NAICS do not cleanly match opportunity NAICS ({', '.join(opportunity_naics)}).")
    if vehicle_access_required and not vehicle_access_ok:
        missing_proof.append("Vehicle access is not yet proven from the vendor profile.")
    if not set_aside_access_ok:
        missing_proof.append("Socioeconomic eligibility is not yet proven for the visible set-aside posture.")
    missing_proof.extend(qualification_gaps.get("missing", []))
    missing_proof.extend(fit_weighting.get("cautions", [])[:2])
    eligibility_gaps: list[str] = []
    if vehicle_access_required and not vehicle_access_ok:
        eligibility_gaps.append("Vehicle access is not yet proven from the vendor profile.")
    if not set_aside_access_ok:
        eligibility_gaps.append("Socioeconomic eligibility is not yet proven for the visible set-aside posture.")
    eligibility_gaps.extend(qualification_gaps.get("missing", []))

    credibility_requirements: list[str] = []
    lower = notice_text.lower()
    if customer_priorities.get("evidence_backed_priorities"):
        credibility_requirements.append(
            "Map each proof point to the specific priorities surfaced in this notice, especially continuity, compliance, reporting, and best-value credibility."
        )
    surfaced_qualifications = qualification_gaps.get("surfaced", [])
    missing_qualifications = qualification_gaps.get("missing_labels", [])
    proven_qualifications = [label for label in surfaced_qualifications if label not in missing_qualifications]
    if surfaced_qualifications:
        qualification_parts: list[str] = []
        if proven_qualifications:
            qualification_parts.append(f"Lead with documented proof of {', '.join(proven_qualifications)}")
        if missing_qualifications:
            qualification_parts.append(
                f"explain how {', '.join(missing_qualifications)} will be satisfied before controlled technical documents or award access are required"
                if any(marker in lower for marker in ("distribution d", "controlled technical", "jcp"))
                else f"explain how {', '.join(missing_qualifications)} will be satisfied before award"
            )
        qualification_bullet = _join_sentence_parts(qualification_parts)
        if qualification_bullet:
            credibility_requirements.append(qualification_bullet)
    if _contains_any(lower, list(CONTINUITY_MARKERS)):
        if any(marker in lower for marker in ("high performance computing", "supercomputer", "dsrc", "dren", "sdren", "classified")):
            credibility_requirements.append(
                "Show a transition and staffing plan for cleared, low-disruption operations across classified and unclassified environments, including named mobilization steps and cutover controls."
            )
        else:
            credibility_requirements.append(
                "Show a transition plan, mobilization timeline, and low-disruption staffing approach because the notice signals transition sensitivity."
            )
    if any(marker in lower for marker in ("cmmc", "jcp", "distribution d", "controlled technical")):
        credibility_requirements.append(
            "Bring compliance evidence that matches this notice: CMMC control coverage, controlled-document handling, and any clearance-dependent delivery controls."
        )
    elif _contains_policy_marker(notice_text):
        credibility_requirements.append("Produce compliance artifacts, control mappings, or policy-ready delivery evidence.")
    if capability_hits:
        credibility_requirements.append(
            f"Anchor the solution story in the overlap already visible in the record: {', '.join(capability_hits[:3])}."
        )
    if fit_weighting.get("positive_theme_hits"):
        credibility_requirements.append(
            f"Carry the vendor-fit narrative through the bid by proving the priority themes already visible here: {', '.join(fit_weighting.get('positive_theme_hits', [])[:3])}."
        )
    elif fit_guidance.get("positive_terms") or keywords:
        credibility_requirements.append(
            "No clear positive alignment surfaced from the vendor fit narrative; prove why this requirement is adjacent to core priorities or adjust teaming posture."
        )
    if fit_weighting.get("preferred_buyers") and not fit_weighting.get("buyer_matches"):
        credibility_requirements.append(
            f"Explain buyer adjacency because the current customer does not match the profile's named target accounts ({', '.join(fit_weighting.get('preferred_buyers', [])[:2])})."
        )
    if not past_performance:
        if any(marker in lower for marker in ("high performance computing", "supercomputer", "dsrc", "dren", "sdren")):
            credibility_requirements.append(
                "Use teammate or referenceable past performance that proves secure DoD or mission-platform operations at comparable scale, ideally including HPC, networking, or 24x7 support."
            )
        elif any(marker in lower for marker in ("classified", "top secret", "secret clearance", "facility clearance")):
            credibility_requirements.append(
                "Use teammate or referenceable past performance that proves cleared delivery in classified or controlled environments, not just general cloud modernization."
            )
        else:
            credibility_requirements.append("Bring partner or subcontractor past performance if in-house proof is thin.")

    return {
        "capability_hits": capability_hits,
        "negative_hits": negative_hits,
        "fit_narrative_positive_hits": _phrase_hits(notice_text, positive_terms, max_items=4),
        "fit_narrative_negative_hits": _phrase_hits(notice_text, fit_guidance.get("negative_terms", []), max_items=4),
        "past_performance_hits": past_performance_hits,
        "naics_match": naics_match,
        "proof_points": proof_points,
        "missing_proof": _dedupe_strings(missing_proof),
        "eligibility_gaps": _dedupe_strings(eligibility_gaps),
        "credibility_requirements": _dedupe_strings(credibility_requirements),
        "past_performance_inventory": past_performance,
        "qualification_gates": qualification_gaps.get("surfaced", []),
        "missing_qualification_gates": qualification_gaps.get("missing_labels", []),
        "fit_weighting_signals": fit_weighting.get("signals", []),
        "fit_weighting_cautions": fit_weighting.get("cautions", []),
        "fit_weighting_summary": _join_sentence_parts(
            fit_weighting.get("signals", [])[:2] + fit_weighting.get("cautions", [])[:2]
        ),
        "customer_alignment_adjustment": int(fit_weighting.get("customer_alignment_adjustment", 0) or 0),
        "requirement_fit_adjustment": int(fit_weighting.get("requirement_fit_adjustment", 0) or 0),
        "past_performance_adjustment": int(fit_weighting.get("past_performance_adjustment", 0) or 0),
        "vehicle_access_adjustment": int(fit_weighting.get("vehicle_access_adjustment", 0) or 0),
    }


def _partner_analysis(
    profile: dict[str, Any],
    capability_fit: dict[str, Any],
    vehicle_access_paths: list[str],
    vehicle_access_required: bool,
    vehicle_profile_hits: list[str],
    set_aside_access_ok: bool,
    incumbent_analysis: dict[str, Any],
) -> dict[str, Any]:
    known_partners = _profile_partner_names(profile)
    prime_sub_preferences = _profile_prime_sub_preferences(profile)
    teaming_preferences = _profile_teaming_preferences(profile)
    risks: list[str] = []
    best_partner_candidates: list[str] = []
    outreach_actions: list[str] = []

    if not set_aside_access_ok:
        best_partner_candidates.append("A prime or JV partner with the required socioeconomic eligibility and a clean compliance record.")
    if vehicle_access_required and vehicle_access_paths and not vehicle_profile_hits:
        best_partner_candidates.append("A vehicle holder already positioned on the likely contract path.")
    if capability_fit.get("qualification_gates"):
        best_partner_candidates.append("A partner or prime with the required facility clearances and certifications already in place.")
    if "transition" in " ".join(capability_fit.get("credibility_requirements", [])).lower():
        best_partner_candidates.append("An incumbent-adjacent partner or staff augmentation teammate who can reduce transition risk.")
    if not capability_fit.get("past_performance_inventory"):
        best_partner_candidates.append("A partner with directly relevant past performance that can be cited without stretching credibility.")
    if not best_partner_candidates:
        best_partner_candidates.append("A narrow specialist teammate only if it adds customer intimacy, vehicle access, or compliance depth.")

    if known_partners:
        outreach_actions.append(f"Validate whether known partners ({', '.join(known_partners[:3])}) bring customer intimacy, vehicle access, or proof points that close current gaps.")
    outreach_actions.append("Build a partner screen around vehicle access, mission relevance, transition credibility, and conflict risk.")
    risks.append("Do not add a partner that only increases complexity without closing a real capture gap.")
    if incumbent_analysis.get("incumbent_name") and incumbent_analysis.get("incumbent_name") != "No confirmed incumbent":
        risks.append("Any partner with direct incumbent conflict or OCI exposure needs early legal and contracts review.")

    posture = "Prime with targeted teammates"
    if capability_fit.get("missing_qualification_gates"):
        posture = "Team, do not prime"
    elif not set_aside_access_ok or (vehicle_access_required and vehicle_access_paths and not vehicle_profile_hits):
        posture = "Team, do not prime"
    elif not capability_fit.get("past_performance_inventory") and "prime" not in " ".join(prime_sub_preferences).lower():
        posture = "Pursue only with conditions"
    elif "sub" in " ".join(prime_sub_preferences).lower() and "prime" not in " ".join(prime_sub_preferences).lower():
        posture = "Team, do not prime"
    elif teaming_preferences:
        posture = "Prime or sub depending on partner quality and vehicle access"

    return {
        "recommended_posture": posture,
        "best_partner_candidates": _dedupe_strings(best_partner_candidates),
        "partner_rationale": _dedupe_strings(
            [
                "Partner value should be judged against real gaps: vehicle access, socioeconomic eligibility, customer intimacy, and usable past performance.",
                "A credible teammate should improve win probability, not just fill a logo slide.",
            ]
        ),
        "partner_risks": _dedupe_strings(risks),
        "partner_outreach_action_items": _dedupe_strings(outreach_actions),
        "known_partners": known_partners,
    }


def _score_and_recommendation(
    opportunity: dict[str, Any],
    customer_priorities: dict[str, Any],
    capability_fit: dict[str, Any],
    funding_analysis: dict[str, Any],
    vehicle_access_required: bool,
    vehicle_access_ok: bool,
    set_aside_access_ok: bool,
    incumbent_analysis: dict[str, Any],
    partner_analysis: dict[str, Any],
    competitive_gate_open: bool,
    gate_reasons: list[str],
) -> dict[str, Any]:
    days_until_due = opportunity.get("days_until_due")
    qualification_gap_count = len(capability_fit.get("missing_qualification_gates", []))
    customer_alignment = _clamp(
        5
        + min(6, len(customer_priorities.get("evidence_backed_priorities", [])) * 2)
        + min(4, len(customer_priorities.get("likely_priorities", []))),
        0,
        15,
    )
    customer_alignment = _clamp(
        customer_alignment + int(capability_fit.get("customer_alignment_adjustment", 0) or 0),
        0,
        15,
    )
    requirement_fit = _clamp(
        4
        + min(6, len(capability_fit.get("capability_hits", [])))
        + (3 if capability_fit.get("naics_match") else 0)
        - min(4, len(capability_fit.get("negative_hits", [])) * 2),
        0,
        15,
    )
    requirement_fit = _clamp(requirement_fit - min(3, qualification_gap_count), 0, 15)
    requirement_fit = _clamp(
        requirement_fit + int(capability_fit.get("requirement_fit_adjustment", 0) or 0),
        0,
        15,
    )
    past_perf_fit = _clamp(
        2
        + (6 if len(capability_fit.get("past_performance_inventory", [])) >= 3 else 4 if capability_fit.get("past_performance_inventory") else 0)
        + min(4, len(capability_fit.get("past_performance_hits", []))),
        0,
        15,
    )
    past_perf_fit = _clamp(
        past_perf_fit + int(capability_fit.get("past_performance_adjustment", 0) or 0),
        0,
        15,
    )
    funding_confidence = {"High": 9, "Medium": 6, "Low": 3}.get(str(funding_analysis.get("funding_confidence", "Low")), 3)
    vehicle_access = 8 if vehicle_access_ok and set_aside_access_ok else 5 if vehicle_access_ok or set_aside_access_ok else 2
    vehicle_access = _clamp(
        vehicle_access + int(capability_fit.get("vehicle_access_adjustment", 0) or 0),
        0,
        10,
    )
    incumbent_vulnerability = 5
    if any("continuity" in item.lower() or "low transition" in item.lower() for item in incumbent_analysis.get("strength_signals", [])):
        incumbent_vulnerability = 3
    if any("follow-on" in item.lower() or "active competition" in item.lower() for item in incumbent_analysis.get("vulnerability_signals", [])):
        incumbent_vulnerability += 2
    if incumbent_analysis.get("incumbent_name") == "No confirmed incumbent":
        incumbent_vulnerability += 1
    incumbent_vulnerability = _clamp(incumbent_vulnerability, 0, 10)
    competitive_position = _clamp(
        round((requirement_fit / 15) * 5 + (past_perf_fit / 15) * 3 + (incumbent_vulnerability / 10) * 2),
        0,
        10,
    )
    partner_leverage = _clamp(
        4
        + min(3, len(partner_analysis.get("best_partner_candidates", [])))
        + (2 if partner_analysis.get("known_partners") else 0)
        - (2 if partner_analysis.get("recommended_posture") == "Team, do not prime" else 0),
        0,
        10,
    )
    if isinstance(days_until_due, (int, float)):
        if float(days_until_due) >= 30:
            timing = 5
        elif float(days_until_due) >= 15:
            timing = 4
        elif float(days_until_due) >= 8:
            timing = 3
        elif float(days_until_due) >= 1:
            timing = 2
        else:
            timing = 1
    else:
        timing = 2

    if vehicle_access_required and not vehicle_access_ok:
        access_rationale = "Driven by whether the opportunity appears to require a pre-existing contract vehicle and whether the profile shows access."
    elif not set_aside_access_ok:
        access_rationale = "Driven mainly by socioeconomic eligibility because no pre-existing vehicle gate is clearly visible."
    else:
        access_rationale = "No pre-existing vehicle gate or socioeconomic barrier is visible in current evidence."
    if qualification_gap_count:
        access_rationale = f"{access_rationale} Mandatory qualifications are tracked separately and still need proof."

    breakdown = [
        {
            "category": "Customer / mission alignment",
            "score": customer_alignment,
            "max": 15,
            "rationale": "Stronger when public mission and policy signals clearly line up with the requirement.",
        },
        {
            "category": "Requirement / capability fit",
            "score": requirement_fit,
            "max": 15,
            "rationale": "Driven by overlap between requirement language, company capabilities, and NAICS alignment.",
        },
        {
            "category": "Past performance fit",
            "score": past_perf_fit,
            "max": 15,
            "rationale": "Improves when user-provided past performance can be mapped directly to likely evaluation themes.",
        },
        {
            "category": "Funding confidence",
            "score": funding_confidence,
            "max": 10,
            "rationale": "Based on award-history relevance, budget documents, and attachment-derived funding clues.",
        },
        {
            "category": "Vehicle / access eligibility",
            "score": vehicle_access,
            "max": 10,
            "rationale": access_rationale,
        },
        {
            "category": "Incumbent vulnerability",
            "score": incumbent_vulnerability,
            "max": 10,
            "rationale": "Higher when the incumbent story is weak or the requirement appears open to displacement.",
        },
        {
            "category": "Competitive position",
            "score": competitive_position,
            "max": 10,
            "rationale": "Reflects whether we look credible against the most likely competitive field.",
        },
        {
            "category": "Partner leverage",
            "score": partner_leverage,
            "max": 10,
            "rationale": "Measures how realistically teaming can close the current gaps.",
        },
        {
            "category": "Proposal timing / resources",
            "score": timing,
            "max": 5,
            "rationale": "Short windows usually favor incumbents and pre-wired teams.",
        },
    ]
    total = sum(item["score"] for item in breakdown)

    if not competitive_gate_open:
        recommendation = "Monitor only"
    elif (
        partner_analysis.get("recommended_posture") == "Team, do not prime"
        and isinstance(days_until_due, (int, float))
        and float(days_until_due) <= 7
    ):
        recommendation = "Team, do not prime"
    elif vehicle_access <= 3 and partner_leverage >= 5:
        recommendation = "Team, do not prime"
    elif total >= 80:
        recommendation = "Pursue"
    elif total >= 65:
        recommendation = "Pursue only with conditions"
    elif total >= 50:
        recommendation = "Shape before pursuing"
    else:
        recommendation = "No-bid"

    rationale: list[str] = []
    rationale.extend(gate_reasons)
    if capability_fit.get("capability_hits"):
        rationale.append(f"Capability overlap surfaced in the public package: {', '.join(capability_fit.get('capability_hits', [])[:4])}.")
    if capability_fit.get("negative_hits"):
        rationale.append(f"The fit narrative or negative-keyword profile surfaced caution areas: {', '.join(capability_fit.get('negative_hits', [])[:3])}.")
    if capability_fit.get("fit_weighting_signals"):
        rationale.append(f"Vendor-fit weighting signals: {'; '.join(capability_fit.get('fit_weighting_signals', [])[:3])}.")
    if capability_fit.get("fit_weighting_cautions"):
        rationale.append(f"Vendor-fit cautions: {'; '.join(capability_fit.get('fit_weighting_cautions', [])[:3])}.")
    if capability_fit.get("missing_proof"):
        rationale.append(f"Credibility gaps remain: {'; '.join(capability_fit.get('missing_proof', [])[:3])}.")
    if funding_analysis.get("funding_confidence"):
        rationale.append(f"Funding confidence is {funding_analysis.get('funding_confidence')}.")
    if incumbent_analysis.get("strength_signals"):
        rationale.append(f"Incumbent strength signals: {'; '.join(incumbent_analysis.get('strength_signals', [])[:2])}.")

    conditions: list[str] = []
    if recommendation in {"Pursue only with conditions", "Shape before pursuing", "Team, do not prime"}:
        conditions.append("Validate access and eligibility: vehicle path if any, set-aside posture, qualification gates, and communication path.")
        conditions.append("Close proof gaps with mapped past performance, transition story, and compliance evidence.")
    if recommendation == "Team, do not prime":
        conditions.append("Find a prime or vehicle holder that meaningfully improves win probability.")
    if not competitive_gate_open:
        conditions.append("Treat this as market intelligence for the next follow-on or shaping cycle, not as a clean immediate bid.")

    confidence = "Medium"
    if total >= 75 and competitive_gate_open:
        confidence = "Medium-High"
    if not competitive_gate_open or len(gate_reasons) >= 2:
        confidence = "Medium-Low"
    if total < 50:
        confidence = "Low"

    return {
        "recommendation": recommendation,
        "score_total": total,
        "score_breakdown": breakdown,
        "rationale": _dedupe_strings(rationale),
        "conditions": _dedupe_strings(conditions),
        "confidence": confidence,
    }


def _win_strategy(
    customer_priorities: dict[str, Any],
    capability_fit: dict[str, Any],
    partner_analysis: dict[str, Any],
    contract_type: str,
    incumbent_analysis: dict[str, Any],
    policy_signals: list[str],
    solicitation_facts: dict[str, Any],
    attachment_workstreams: list[dict[str, Any]],
    staffing_pricing_signals: dict[str, Any],
    attachment_anomalies: list[dict[str, Any]],
    strategic_reasoning: dict[str, Any],
) -> dict[str, Any]:
    workstream_lines = _workstream_lines(attachment_workstreams)
    staffing_notes = _string_list(staffing_pricing_signals.get("staffing_notes", []), max_items=6)
    pricing_notes = _string_list(staffing_pricing_signals.get("pricing_notes", []), max_items=6)
    evaluation_notes = _string_list(staffing_pricing_signals.get("evaluation_notes", []), max_items=4)
    staffing_roles = _string_list(solicitation_facts.get("staffing_roles", []), max_items=8)
    attachment_text = " ".join(workstream_lines + staffing_notes + pricing_notes + evaluation_notes).lower()
    strategy_anchors = _current_package_strategy_anchors(solicitation_facts, attachment_workstreams)
    section_anchors = strategy_anchors.get("section_anchors", [])
    fact_anchors = strategy_anchors.get("fact_anchors", [])
    current_package_anchors = strategy_anchors.get("all_anchors", [])
    workstream_capture_implication_rows = _workstream_capture_implication_rows(
        attachment_workstreams,
        solicitation_facts,
        staffing_pricing_signals,
        attachment_anomalies,
        max_items=5,
    )
    proof_artifact_recommendations = _proof_artifact_recommendations(
        solicitation_facts,
        attachment_workstreams,
        staffing_pricing_signals,
        attachment_anomalies,
        strategic_reasoning,
    )
    attachment_native_ready = bool(section_anchors) and len(section_anchors) >= 2 and len(workstream_lines) >= 3
    strong_requirement_evidence = (
        len(section_anchors) >= 2
        or (len(section_anchors) >= 1 and len(fact_anchors) >= 1)
        or attachment_native_ready
    )
    requirement_specific = _requirement_specific_insights(" ".join(workstream_lines + staffing_notes + pricing_notes + evaluation_notes))
    specific_hot_buttons = _string_list(requirement_specific.get("priorities", []), max_items=8)
    specific_pain_points = _string_list(requirement_specific.get("pain_points", []), max_items=8)
    specific_win_themes = _string_list(requirement_specific.get("win_themes", []), max_items=8)
    specific_differentiators = _string_list(requirement_specific.get("differentiators", []), max_items=8)
    strong_requirement_detail = len(workstream_lines) >= 4
    enough_specific_hot_buttons = len(specific_hot_buttons) >= 5 or (strong_requirement_detail and len(specific_hot_buttons) >= 2)
    enough_specific_win_themes = len(specific_win_themes) >= 5 or (strong_requirement_detail and len(specific_win_themes) >= 2)
    enough_specific_differentiators = len(specific_differentiators) >= 5 or (strong_requirement_detail and len(specific_differentiators) >= 2)
    main_win_theme_candidates = _dedupe_strings(
        _strategy_row_texts(workstream_capture_implication_rows)
        + specific_win_themes
        + _string_list(strategic_reasoning.get("reasoned_win_themes", []), max_items=6)
        + ([] if enough_specific_win_themes else customer_priorities.get("evidence_backed_priorities", [])[:2])
    )
    security_visible = any(
        marker in attachment_text
        for marker in ("af form 1199", "leads", "naci", "cac", "clearance", "fouo", "nda")
    )
    anomaly_signals = [
        str(item.get("signal") or "").strip()
        for item in attachment_anomalies or []
        if isinstance(item, dict) and str(item.get("signal") or "").strip()
    ]
    hot_buttons = _dedupe_strings(
        _strategy_row_texts(workstream_capture_implication_rows[:2])
        + specific_hot_buttons
        + ([] if enough_specific_hot_buttons else customer_priorities.get("evidence_backed_priorities", [])[:3])
        + ([] if enough_specific_hot_buttons else customer_priorities.get("likely_priorities", [])[:2])
        + ([] if enough_specific_hot_buttons else _string_list(strategic_reasoning.get("reasoned_pain_points", []), max_items=4))
        + ([] if enough_specific_hot_buttons else specific_pain_points[:2])
        + (
            ["The customer needs a credible staffing plan for the visible labor mix and execution setting."]
            if staffing_roles and not enough_specific_hot_buttons
            else []
        )
        + (
            ["Monthly PSR reporting and management visibility matter because the PWS calls for task-hierarchy status reporting and presentation materials."]
            if ("project reporting and qa/qc control" in attachment_text or "project status report" in attachment_text) and not enough_specific_hot_buttons
            else []
        )
        + (
            ["Access, credentialing, clearance, or information-handling readiness matters because those control steps can delay day-one execution."]
            if security_visible and not enough_specific_hot_buttons
            else []
        )
    )
    evidence_backed_discriminators = _dedupe_strings(
        capability_fit.get("capability_hits", [])[:4]
        + capability_fit.get("past_performance_hits", [])[:4]
    )[:4]
    policy_story_ready = bool(policy_signals and evidence_backed_discriminators)
    win_themes = _dedupe_strings(
        [
            *specific_win_themes,
            *(
                []
                if enough_specific_win_themes
                else [
                    "Show how the team will execute the primary requirement workstreams from day one, not just provide a labor category map.",
                    "Tie past performance to the visible workstreams surfaced in the attachments: execution support, deliverable development, reporting cadence, and quality discipline.",
                ]
            ),
            *(
                ["Present a low-disruption transition story that directly answers continuity concerns."]
                if any("continuity" in item.lower() or "transition" in item.lower() for item in hot_buttons) and not enough_specific_win_themes
                else []
            ),
            *(
                ["Prove fixed-price discipline with a fully burdened on-site labor mix, realistic QA/QC effort, and disciplined reporting controls."]
                if contract_type == "Firm Fixed Price" and not enough_specific_win_themes
                else []
            ),
            *(
                ["Show how DD 1391, SOW/PWS, programming-document, and cost-estimate support will move projects through the acquisition pipeline without rework."]
                if ("dd 1391" in attachment_text or "acquisition-package" in attachment_text) and not enough_specific_win_themes
                else []
            ),
            *([] if enough_specific_win_themes else _string_list(strategic_reasoning.get("reasoned_win_themes", []), max_items=6)),
        ]
    )
    discriminators = _dedupe_strings(
        [
            *([f"Relevant proof point: {item}" for item in evidence_backed_discriminators]),
            *specific_differentiators,
            *(
                ["A delivery story that links startup readiness, QA/QC rigor, reporting discipline, and workstream throughput in one narrative."]
                if workstream_lines and not enough_specific_differentiators
                else []
            ),
            *(
                ["Documented readiness for access, credentialing, clearance, NDA, or other surfaced handling controls."]
                if security_visible and not enough_specific_differentiators
                else []
            ),
            *(
                ["Credible experience supporting scoped package artifacts and customer review coordination."]
                if ("dd 1391" in attachment_text or "acquisition-package" in attachment_text) and not enough_specific_differentiators
                else []
            ),
            *([] if enough_specific_differentiators else _string_list(strategic_reasoning.get("reasoned_differentiators", []), max_items=6)),
        ]
    )
    if not discriminators:
        discriminators = ["No requirement-specific discriminator surfaced from current evidence."]
    ghosting = _dedupe_strings(
        [
            *(
                ["Ghost the incumbent on day-one execution by offering a named on-site mobilization plan, access/onboarding checklist, and low-drama staffing ramp."]
                if incumbent_analysis.get("strength_signals")
                else []
            ),
            *(
                ["Ghost unrealistic low bidders by showing tighter scope control and fully burdened FFP pricing tied to the exact labor mix and option periods."]
                if contract_type == "Firm Fixed Price"
                else []
            ),
            *(
                ["Ghost generic IT firms by tying proof points directly to policy, control, and mission-specific outcomes."]
                if policy_story_ready
                else []
            ),
            *(
                ["Use formal Q&A to resolve document inconsistencies before competitors bake the wrong page limits, attachment set, or revision dates into their proposal assumptions."]
                if anomaly_signals
                else []
            ),
        ]
    )
    price_to_win = _dedupe_strings(
        [
            "Use predecessor award values and the visible contract type to build an initial price-to-win range.",
            *(
                ["Stress affordability, scope control, and low transition friction, but do not underprice the visible labor mix, QA/QC effort, reporting workload, or access dependencies."]
                if contract_type == "Firm Fixed Price"
                else ["Do not assume price is secondary; keep PTW analysis active until evaluation factors are confirmed."]
            ),
            *(
                ["Model PTW around the surfaced labor mix, performance periods, access overhead, and any visible vehicle fees."]
                if staffing_roles and solicitation_facts.get("period_of_performance")
                else []
            ),
            *(
                ["Treat award timing as variable because the package says funds are not presently available."]
                if str(solicitation_facts.get("funds_status") or "").strip()
                else []
            ),
            *pricing_notes[:2],
        ]
    )
    transition = _dedupe_strings(
        [
            "Build a day-one operating-readiness story with staffing, governance, risk burn-down, and customer-facing reporting from the first month.",
            *(
                ["If displacing an incumbent, show exactly how service continuity will be protected in the first 30-60 days."]
                if incumbent_analysis.get("strength_signals")
                else []
            ),
            *(
                ["Build onboarding around the surfaced access, credentialing, clearance, and information-handling steps."]
                if security_visible
                else []
            ),
        ]
    )
    staffing = _dedupe_strings(
        [
            "Prioritize key personnel who can demonstrate immediate credibility with the customer stakeholders named or implied in the package.",
            *(
                [f"Name the staffing mix explicitly: {', '.join(staffing_roles)}."]
                if staffing_roles
                else []
            ),
            "Tie resumes and staffing assumptions to the visible workstreams, especially startup readiness, QA/QC, reporting cadence, and any surfaced access constraints.",
            *staffing_notes[:2],
        ]
    )
    compliance = _dedupe_strings(
        [
            *(
                ["Build a light compliance matrix from the notice, attachments, and policy sources before solution lock."]
                if policy_story_ready
                else ["Build a light compliance matrix from the notice and attachments before solution lock."]
            ),
            *([f"Use surfaced policy artifact: {item}" for item in policy_signals[:3]] if policy_story_ready else []),
            *(
                ["Current run surfaced policy/compliance references, but not enough requirement-specific evidence to make them a win-theme anchor yet."]
                if policy_signals and not policy_story_ready
                else []
            ),
            *(
                ["Build the matrix around PWS sections, key roles, PSR deliverables, and access/security prerequisites rather than generic policy prose."]
                if workstream_lines
                else []
            ),
            *(
                ["Define OCI and inherently-governmental boundaries early because the scope mixes acquisition-package support with proprietary-information handling."]
                if any("scope-boundary planning matters" in item.lower() for item in staffing_notes)
                else []
            ),
        ]
    )
    partner = _dedupe_strings(
        partner_analysis.get("best_partner_candidates", [])[:3]
        + partner_analysis.get("partner_outreach_action_items", [])[:2]
    )
    if not strong_requirement_evidence:
        hot_button_rows = [{"text": NO_HOT_BUTTON_EVIDENCE, "evidence_anchor": ""}]
        win_theme_rows = [{"text": NO_WIN_THEME_EVIDENCE, "evidence_anchor": ""}]
        discriminator_rows = [{"text": NO_DIFFERENTIATOR_EVIDENCE, "evidence_anchor": ""}]
        reasoning_win_theme_rows = [{"text": NO_REASONED_THEME_EVIDENCE, "evidence_anchor": ""}]
        proof_requirement_rows = [{"text": NO_PROOF_REQUIREMENT_EVIDENCE, "evidence_anchor": ""}]
    else:
        hot_button_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
            hot_buttons,
            current_package_anchors,
            fallback=NO_HOT_BUTTON_EVIDENCE,
            max_items=6,
        ))
        win_theme_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
            win_themes,
            current_package_anchors,
            fallback=NO_WIN_THEME_EVIDENCE,
            max_items=3 if attachment_native_ready else 6,
            min_overlap=1 if attachment_native_ready else 2,
        ))
        if attachment_native_ready and win_theme_rows and str(win_theme_rows[0].get("text") or "").strip() == NO_WIN_THEME_EVIDENCE:
            win_theme_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
                main_win_theme_candidates,
                section_anchors or current_package_anchors,
                fallback=NO_WIN_THEME_EVIDENCE,
                max_items=3,
                min_overlap=1,
            ))
        discriminator_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
            discriminators,
            current_package_anchors,
            fallback=NO_DIFFERENTIATOR_EVIDENCE,
            max_items=6,
        ))
        reasoning_win_theme_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
            _string_list(strategic_reasoning.get("reasoned_win_themes", []), max_items=8),
            current_package_anchors,
            fallback=NO_REASONED_THEME_EVIDENCE,
            max_items=6,
        ))
        proof_requirement_rows = _prune_generic_strategy_rows(_anchor_strategy_lines(
            _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8),
            current_package_anchors,
            fallback=NO_PROOF_REQUIREMENT_EVIDENCE,
            max_items=6,
        ))
    hot_buttons = _strategy_row_texts(hot_button_rows)
    win_themes = _strategy_row_texts(win_theme_rows)
    discriminators = _strategy_row_texts(discriminator_rows)
    reasoning_based_win_themes = _strategy_row_texts(reasoning_win_theme_rows)
    reasoning_based_proof_requirements = _strategy_row_texts(proof_requirement_rows)
    return {
        "central_pain_point": str(strategic_reasoning.get("central_pain_point") or "").strip(),
        "reasoning_summary": str(strategic_reasoning.get("reasoning_summary") or "").strip(),
        "reasoning_based_pain_points": _string_list(strategic_reasoning.get("reasoned_pain_points", []), max_items=6),
        "reasoning_based_win_themes": reasoning_based_win_themes,
        "reasoning_based_differentiators": _string_list(strategic_reasoning.get("reasoned_differentiators", []), max_items=8),
        "reasoning_based_proof_requirements": reasoning_based_proof_requirements,
        "reasoning_based_risk_implications": _string_list(strategic_reasoning.get("risk_implications", []), max_items=6),
        "strategy_evidence_strength": "strong" if strong_requirement_evidence else "thin",
        "section_anchor_count": len(section_anchors),
        "fact_anchor_count": len(fact_anchors),
        "workstream_capture_implication_rows": workstream_capture_implication_rows,
        "workstream_capture_implications": _strategy_row_texts(workstream_capture_implication_rows),
        "proof_artifact_recommendations": proof_artifact_recommendations,
        "hot_button_rows": hot_button_rows,
        "win_theme_rows": win_theme_rows,
        "discriminator_rows": discriminator_rows,
        "reasoning_based_win_theme_rows": reasoning_win_theme_rows,
        "reasoning_based_proof_requirement_rows": proof_requirement_rows,
        "hot_buttons": hot_buttons or [NO_HOT_BUTTON_EVIDENCE],
        "win_themes": win_themes,
        "discriminators": discriminators,
        "ghosting_strategy": ghosting or ["Ghosting strategy still depends on validating the incumbent and evaluation factors."],
        "price_to_win_considerations": price_to_win,
        "transition_strategy": transition,
        "staffing_strategy": staffing,
        "compliance_strategy": compliance,
        "partner_strategy": partner,
    }


def _questions_to_ask(
    customer_priorities: dict[str, Any],
    capability_fit: dict[str, Any],
    partner_analysis: dict[str, Any],
    funding_analysis: dict[str, Any],
    document_inventory: dict[str, list[str]],
) -> dict[str, list[str]]:
    customer = _dedupe_strings(
        [
            "What transition window, overlap period, and government-furnished knowledge transfer will be available at award?",
            "Which performance outcomes matter most in evaluation: continuity, speed, compliance, user support, or price realism?",
            *(
                ["How is the requirement funded and is it tied to a named program, budget line, or predecessor contract?"]
                if funding_analysis.get("funding_confidence") != "High"
                else []
            ),
        ]
    )
    internal = _dedupe_strings(
        [
            "Which 2-3 past performance examples can survive a red-team challenge against this requirement?",
            "Can we prime credibly, or do vehicle, set-aside, or staffing gaps force a team-first posture?",
            *(
                ["What proof do we have that we can manage transition risk better than the likely incumbent?"]
                if capability_fit.get("credibility_requirements")
                else []
            ),
        ]
    )
    partners = _dedupe_strings(
        [
            "Which partner closes the most important gap: vehicle access, customer intimacy, or past performance?",
            "Will the partner materially improve win probability or just complicate governance and economics?",
            *partner_analysis.get("partner_outreach_action_items", [])[:1],
        ]
    )
    missing_documents = _dedupe_strings(
        [
            *document_inventory.get("missing", [])[:3],
            "Which missing attachment or controlled document would change our pursue / team / no-bid decision the fastest?",
        ]
    )
    return {
        "customer": customer,
        "internal": internal,
        "partners": partners,
        "missing_documents": missing_documents,
    }


def _action_plan(
    document_inventory: dict[str, list[str]],
    funding_analysis: dict[str, Any],
    partner_analysis: dict[str, Any],
    capability_fit: dict[str, Any],
    recommendation: str,
) -> dict[str, list[dict[str, str]]]:
    immediate = [
        {
            "owner_role": "Capture Manager",
            "action": "Retrieve and validate the full solicitation document set, especially SOW/PWS, amendments, Q&A, and pricing files.",
            "why": "Missing or partial documents are the fastest way to misjudge evaluation drivers, transition scope, and the real competitive posture.",
            "dependency": "Notice workspace access and manual download if links are controlled or expired.",
            "priority": "High",
            "capture_value": "Improves bid/no-bid confidence and clarifies customer hot buttons.",
        },
        {
            "owner_role": "Solution Lead",
            "action": "Map the requirement to 2-3 strongest proof points and flag where partner past performance is needed.",
            "why": "Credibility gaps need to be visible before the team commits to prime posture.",
            "dependency": "User past performance inventory and current requirement parse.",
            "priority": "High",
            "capture_value": "Clarifies whether the team can credibly bid or should team.",
        },
    ]
    if partner_analysis.get("recommended_posture") in {"Team, do not prime", "Prime or sub depending on partner quality and vehicle access"}:
        immediate.append(
            {
                "owner_role": "Partner Manager",
                "action": "Start targeted partner outreach around vehicle access, customer intimacy, and directly relevant past performance.",
                "why": "If partner posture is required, delay immediately reduces leverage and narrows options.",
                "dependency": "Gap list and teammate screen.",
                "priority": "High",
                "capture_value": "Can move the opportunity from marginal to credible.",
            }
        )

    near_term = [
        {
            "owner_role": "Pricing Lead",
            "action": "Build an initial price-to-win hypothesis using predecessor award values, contract type, and visible scope boundaries.",
            "why": "Capture judgment is incomplete without a rough economic reality check.",
            "dependency": "Related award history and any pricing attachment clues.",
            "priority": "Medium",
            "capture_value": "Reduces late-cycle pricing surprises and shapes solution boundaries.",
        },
        {
            "owner_role": "Capture Manager",
            "action": "Draft formal customer questions on transition, evaluation factors, vehicle path, and funding if the solicitation allows Q&A.",
            "why": "Well-aimed questions can change win probability more than generic solution polish.",
            "dependency": "Confirmed Q&A window and communication rules.",
            "priority": "Medium",
            "capture_value": "Improves requirement clarity and surfaces hidden gates.",
        },
        {
            "owner_role": "Solution Architect",
            "action": "Run a solution workshop around customer hot buttons, transition risk, compliance, and discriminators.",
            "why": "The team needs a capture story before it starts writing a proposal story.",
            "dependency": "Updated requirement parse and proof-point map.",
            "priority": "Medium",
            "capture_value": "Sharpens win themes and ghosting strategy.",
        },
    ]

    longer_term = [
        {
            "owner_role": "Capture Manager",
            "action": "Monitor amendments, forecasts, predecessor contract changes, and budget signals through award.",
            "why": "The opportunity can still shift materially after the initial capture judgment.",
            "dependency": "Monitoring cadence and source access.",
            "priority": "Medium",
            "capture_value": "Protects against stale assumptions.",
        },
        {
            "owner_role": "Proposal Manager",
            "action": "Turn validated capture themes into storyboards, compliance artifacts, and a transition narrative.",
            "why": "Decision-grade capture only pays off if the proof points convert into proposal structure.",
            "dependency": "Pursuit approval and resolved teaming posture.",
            "priority": "Medium",
            "capture_value": "Improves downstream proposal coherence and evaluator trust.",
        },
    ]

    if funding_analysis.get("funding_confidence") == "Low":
        longer_term.append(
            {
                "owner_role": "BD Lead",
                "action": "Validate program funding and durability through forecasts, budget documents, and customer-facing market activity.",
                "why": "Low funding confidence can waste scarce capture resources.",
                "dependency": "Additional primary-source research or customer signals.",
                "priority": "Medium",
                "capture_value": "Prevents chasing an unstable requirement.",
            }
        )
    if recommendation == "Monitor only":
        immediate = [
            {
                "owner_role": "Capture Manager",
                "action": "Track the follow-on procurement and predecessor contract for a cleaner competitive opening.",
                "why": "The current action does not look like a clean bid opportunity.",
                "dependency": "Regular notice and award monitoring.",
                "priority": "High",
                "capture_value": "Preserves positioning for the next real bid window.",
            }
        ]
    return {
        "immediate": immediate,
        "near_term": near_term,
        "longer_term": longer_term,
    }


def build_capture_decision_sections(
    *,
    vendor_profile: dict[str, Any],
    resolved: dict[str, Any],
    opportunity: dict[str, Any],
    explanation: dict[str, Any],
    notice_context_text: str,
    attachment_bundle: dict[str, Any],
    attachment_validation: dict[str, Any],
    public_research: dict[str, Any],
    award_signals: dict[str, Any],
    funding_assessment: dict[str, Any],
    source_log: list[dict[str, Any]],
    evidence_gaps: list[str],
    stakeholder_contacts: list[dict[str, str]],
    vehicle_signals: list[str],
    learned_semantic_preferences: dict[str, Any],
    normalized_evidence: dict[str, Any] | None = None,
    solicitation_facts: dict[str, Any] | None = None,
    attachment_workstreams: list[dict[str, Any]] | None = None,
    staffing_pricing_signals: dict[str, Any] | None = None,
    attachment_anomalies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    vendor_name = _profile_company_name(vendor_profile)
    normalized_evidence = normalized_evidence if isinstance(normalized_evidence, dict) else {}
    solicitation_facts = solicitation_facts if isinstance(solicitation_facts, dict) else {}
    attachment_workstreams = attachment_workstreams if isinstance(attachment_workstreams, list) else []
    staffing_pricing_signals = staffing_pricing_signals if isinstance(staffing_pricing_signals, dict) else {}
    attachment_anomalies = attachment_anomalies if isinstance(attachment_anomalies, list) else []
    normalized_incumbent = normalized_evidence.get("incumbent", {}) if isinstance(normalized_evidence.get("incumbent"), dict) else {}
    normalized_vehicle = normalized_evidence.get("vehicle", {}) if isinstance(normalized_evidence.get("vehicle"), dict) else {}
    normalized_contract_value = normalized_evidence.get("contract_value_or_ceiling", {}) if isinstance(normalized_evidence.get("contract_value_or_ceiling"), dict) else {}
    normalized_teaming = normalized_evidence.get("teaming_posture", {}) if isinstance(normalized_evidence.get("teaming_posture"), dict) else {}
    normalized_related = normalized_evidence.get("related_procurements", []) if isinstance(normalized_evidence.get("related_procurements"), list) else []
    normalized_conflicts = normalized_evidence.get("conflicts", []) if isinstance(normalized_evidence.get("conflicts"), list) else []
    attachment_conflicts = solicitation_facts.get("attachment_conflicts", []) if isinstance(solicitation_facts.get("attachment_conflicts"), list) else []
    normalized_questions = _string_list(normalized_evidence.get("next_questions"), max_items=6)
    notice_text = " ".join(
        [
            str(opportunity.get("title", "") or ""),
            str(opportunity.get("summary", "") or ""),
            str(explanation.get("summary", "") or ""),
            notice_context_text,
            " ".join(_solicitation_fact_lines(solicitation_facts)),
            " ".join(_workstream_lines(attachment_workstreams)),
            " ".join(_operational_constraint_lines(solicitation_facts, staffing_pricing_signals, attachment_workstreams)),
        ]
    )
    contract_type = _detect_contract_type(notice_text)
    award_basis = _detect_award_basis(notice_text)
    transition_window = _detect_transition_window(notice_text)
    contract_vehicles = _profile_contract_vehicles(vendor_profile)
    vehicle_posture = _detect_vehicle_posture(notice_text, vehicle_signals, contract_vehicles)
    vehicle_access_paths = vehicle_posture.get("access_paths", [])
    contract_structures = vehicle_posture.get("contract_structures", [])
    vehicle_profile_hits = vehicle_posture.get("profile_hits", [])
    vehicle_access_required = bool(vehicle_posture.get("requires_existing_vehicle_access"))
    policy_marker_present = _contains_policy_marker(notice_text)
    set_aside_text = str(solicitation_facts.get("set_aside") or normalized_vehicle.get("set_aside") or opportunity.get("set_aside") or "Not stated")
    contract_vehicle_text = str(solicitation_facts.get("contract_vehicle") or normalized_vehicle.get("name") or "").strip()
    if "8(a) stars" in contract_vehicle_text.lower() and ("hubzone" in _normalize_text(set_aside_text) or set_aside_text.strip().lower() in {"not stated", "unknown"}):
        set_aside_text = "8(a)"
    if str(solicitation_facts.get("contract_vehicle") or "").strip():
        vehicle_access_paths = _dedupe_strings([str(solicitation_facts.get("contract_vehicle") or "").strip()] + vehicle_access_paths)
    if str(normalized_vehicle.get("contract_type") or "").strip():
        contract_type = str(normalized_vehicle.get("contract_type") or "").strip()
    if str(solicitation_facts.get("contract_type") or "").strip():
        contract_type = str(solicitation_facts.get("contract_type") or "").strip()
    if str(solicitation_facts.get("evaluation_basis") or "").strip():
        award_basis = str(solicitation_facts.get("evaluation_basis") or "").strip()
    set_aside_statement, set_aside_access_ok = _set_aside_access(set_aside_text, _profile_set_asides(vendor_profile))
    qualification_gaps = _required_qualification_gaps(vendor_profile, notice_text)
    semantic_context = _semantic_capture_context(opportunity, learned_semantic_preferences)
    customer_priorities = _priority_analysis(notice_text, public_research, attachment_bundle, award_basis, contract_type)
    workstream_lines = _workstream_lines(attachment_workstreams)
    strategic_reasoning = _strategic_capture_reasoning(
        solicitation_facts,
        attachment_workstreams,
        staffing_pricing_signals,
        attachment_anomalies,
        contract_type,
        award_basis,
    )
    if workstream_lines:
        customer_priorities["requirement_workstreams"] = workstream_lines
        customer_priorities["evidence_backed_priorities"] = _dedupe_strings(
            customer_priorities.get("evidence_backed_priorities", [])
            + (
                ["The requirement appears centered on direct execution support rather than generic staff augmentation."]
                if any("on-site" in item.lower() or "delivery continuity" in item.lower() or "execution" in item.lower() for item in workstream_lines)
                else []
            )
            + (
                ["The customer needs package or deliverable throughput, including planning, scope, or cost artifacts called out in the attachments."]
                if any("dd 1391" in item.lower() or "acquisition-package" in item.lower() for item in workstream_lines)
                else []
            )
            + (
                ["Monthly PSR discipline and QA/QC appear to be operational hot buttons, not nice-to-have management polish."]
                if any("psr" in item.lower() or "qa/qc" in item.lower() for item in workstream_lines)
                else []
            )
        )
        customer_priorities["likely_priorities"] = _dedupe_strings(
            customer_priorities.get("likely_priorities", [])
            + (
                ["Specialized staffing continuity may matter because multiple distinct roles are explicitly visible in the labor mix."]
                if any("furnishings" in item.lower() or "staffing mix" in item.lower() for item in workstream_lines)
                else []
            )
            + (
                ["Access, credentialing, or information-handling controls are likely evaluated informally because they can break day-one execution even when technical approach looks fine."]
                if any("access, security" in item.lower() or "information-handling" in item.lower() for item in workstream_lines)
                else []
            )
        )
        if str(customer_priorities.get("mission_problem") or "").startswith("Mission problem is not corroborated"):
            customer_priorities["mission_problem"] = workstream_lines[0]
    customer_priorities["pain_points"] = _dedupe_strings(
        customer_priorities.get("pain_points", [])
        + _string_list(strategic_reasoning.get("reasoned_pain_points", []), max_items=4)
    )
    customer_priorities["strategic_pain_points"] = _string_list(strategic_reasoning.get("reasoned_pain_points", []), max_items=6)
    customer_priorities["strategic_reasoning_summary"] = str(strategic_reasoning.get("reasoning_summary") or "").strip()
    customer_priorities = _apply_priority_evidence_gate(customer_priorities, public_research, workstream_lines)
    funding_analysis = _funding_analysis(funding_assessment, award_signals, public_research, attachment_bundle, evidence_gaps)
    if str(solicitation_facts.get("funds_status") or "").strip():
        funding_analysis["risk_to_timing_or_award"] = _dedupe_strings(
            funding_analysis.get("risk_to_timing_or_award", [])
            + [f"Solicitation funding caveat: {solicitation_facts.get('funds_status')}"]
        )
    incumbent = _incumbent_analysis(notice_text, award_signals, attachment_validation, attachment_bundle)
    normalized_incumbent_name = str(normalized_incumbent.get("name") or "").strip()
    if normalized_incumbent_name and incumbent.get("incumbent_name") == "No confirmed incumbent":
        incumbent["incumbent_name"] = normalized_incumbent_name
        incumbent["source_basis"] = "Cross-source evidence synthesis across official and commercial signals; still validate against the solicitation package."
    incumbent["strength_signals"] = _dedupe_strings(
        incumbent.get("strength_signals", [])
        + _string_list(normalized_incumbent.get("evidence"), max_items=4)
    )
    incumbent["vulnerability_signals"] = _dedupe_strings(
        incumbent.get("vulnerability_signals", [])
        + [f'Source conflict to validate: {item.get("field")}.' for item in normalized_conflicts[:1] if isinstance(item, dict)]
    )
    stakeholder_analysis = _stakeholder_analysis(resolved.get("buyer", ""), stakeholder_contacts, opportunity, public_research)
    vehicle_access_ok = (not vehicle_access_required) or bool(vehicle_profile_hits)
    capability_fit = _capability_fit(
        vendor_profile,
        resolved.get("buyer", ""),
        opportunity,
        notice_text,
        customer_priorities,
        solicitation_facts,
        vehicle_access_paths,
        set_aside_text,
        vehicle_access_ok,
        vehicle_access_required,
        set_aside_access_ok,
        qualification_gaps,
    )
    if semantic_context.get("support"):
        capability_fit["proof_points"] = _dedupe_strings(
            capability_fit.get("proof_points", []) + semantic_context.get("support", [])
        )
    if semantic_context.get("cautions"):
        capability_fit["negative_hits"] = _dedupe_strings(
            capability_fit.get("negative_hits", []) + semantic_context.get("cautions", [])
        )
    if semantic_context.get("historical_pattern_summary"):
        capability_fit["credibility_requirements"] = _dedupe_strings(
            capability_fit.get("credibility_requirements", [])
            + [f"Address the learned historical-fit pattern directly: {semantic_context.get('historical_pattern_summary')}"]
        )
    capability_fit["credibility_requirements"] = _dedupe_strings(
        capability_fit.get("credibility_requirements", [])
        + _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8)
    )
    capability_fit["proof_points"] = _dedupe_strings(
        capability_fit.get("proof_points", [])
        + _string_list(strategic_reasoning.get("reasoned_differentiators", []), max_items=6)
    )
    partner_analysis = _partner_analysis(
        vendor_profile,
        capability_fit,
        vehicle_access_paths,
        vehicle_access_required,
        vehicle_profile_hits,
        set_aside_access_ok,
        incumbent,
    )
    partner_analysis["best_partner_candidates"] = _dedupe_strings(
        partner_analysis.get("best_partner_candidates", [])
        + _string_list(normalized_teaming.get("partner_signals"), max_items=4)
    )
    partner_analysis["partner_rationale"] = _dedupe_strings(
        partner_analysis.get("partner_rationale", [])
        + _string_list(normalized_teaming.get("rationale"), max_items=4)
        + (
            [f'Commercial-intel posture signal: {normalized_teaming.get("recommended_posture")}']
            if str(normalized_teaming.get("recommended_posture") or "").strip()
            else []
        )
    )
    partner_analysis["partner_risks"] = _dedupe_strings(
        partner_analysis.get("partner_risks", [])
        + _string_list(normalized_teaming.get("risks"), max_items=4)
    )
    competitive_gate_open, gate_reasons = _competitive_gate(opportunity, notice_text)
    recommendation = _score_and_recommendation(
        opportunity,
        customer_priorities,
        capability_fit,
        funding_analysis,
        vehicle_access_required,
        vehicle_access_ok,
        set_aside_access_ok,
        incumbent,
        partner_analysis,
        competitive_gate_open,
        gate_reasons,
    )
    if semantic_context.get("support"):
        recommendation["rationale"] = _dedupe_strings(
            recommendation.get("rationale", []) + semantic_context.get("support", [])[:2]
        )
    if semantic_context.get("cautions"):
        recommendation["rationale"] = _dedupe_strings(
            recommendation.get("rationale", []) + semantic_context.get("cautions", [])[:2]
        )
    document_inventory = _document_inventory(attachment_bundle, source_log, evidence_gaps)
    competitive_analysis = _competitive_analysis(
        award_signals,
        normalized_evidence,
        incumbent.get("incumbent_name", ""),
        solicitation_facts,
        attachment_workstreams,
    )
    competitive_analysis.extend(_reasoned_competitor_hypotheses(solicitation_facts, attachment_workstreams))
    deduped_competitive_analysis: list[dict[str, str]] = []
    seen_competitors: set[str] = set()
    for item in competitive_analysis:
        if not isinstance(item, dict):
            continue
        key = _normalize_text(item.get("name", ""))
        if not key or key in seen_competitors:
            continue
        seen_competitors.add(key)
        deduped_competitive_analysis.append(item)
    competitive_analysis = deduped_competitive_analysis
    if normalized_incumbent_name and all(
        _normalize_text(item.get("name", "")) != _normalize_text(normalized_incumbent_name)
        for item in competitive_analysis
        if isinstance(item, dict)
    ):
        first_related = normalized_related[0] if normalized_related and isinstance(normalized_related[0], dict) else {}
        competitive_analysis.insert(
            0,
            {
                "name": normalized_incumbent_name,
                "why_likely": str(first_related.get("relationship") or "Cross-source evidence suggests predecessor or advantaged performer posture.").strip(),
                "strengths": " ".join(_string_list(normalized_incumbent.get("evidence"), max_items=2)) or "Cross-source evidence points to a meaningful incumbent or predecessor signal.",
                "weaknesses": "Still requires direct solicitation-package validation." if incumbent.get("source_basis", "").startswith("Cross-source") else "No direct weakness surfaced beyond remaining validation gaps.",
                "likely_strategy": "Likely to emphasize continuity, predecessor knowledge, and any advantaged vehicle or customer position.",
                "partner_relevance": "Low as a likely prime competitor unless later evidence shows a subcontract-only role.",
                "evidence": str(first_related.get("title") or "").strip() or "Commercial and official-source synthesis.",
            },
        )
    subtle_signals = _subtle_signals(
        notice_text,
        opportunity,
        attachment_bundle,
        public_research,
        str(funding_analysis.get("funding_confidence", "Low")),
        vehicle_access_paths + contract_structures,
    )
    subtle_signals.extend(
        [
            item
            for item in attachment_anomalies
            if isinstance(item, dict) and str(item.get("signal") or "").strip()
        ]
    )
    deduped_subtle_signals: list[dict[str, str]] = []
    seen_subtle_signals: set[str] = set()
    for item in subtle_signals:
        if not isinstance(item, dict):
            continue
        key = _normalize_text(item.get("signal", ""))
        if not key or key in seen_subtle_signals:
            continue
        seen_subtle_signals.add(key)
        deduped_subtle_signals.append(item)
    subtle_signals = deduped_subtle_signals
    win_strategy = _win_strategy(
        customer_priorities,
        capability_fit,
        partner_analysis,
        contract_type,
        incumbent,
        _string_list(public_research.get("policy_compliance_signals", []), max_items=4) if policy_marker_present else [],
        solicitation_facts,
        attachment_workstreams,
        staffing_pricing_signals,
        attachment_anomalies,
        strategic_reasoning,
    )
    if semantic_context.get("cautions"):
        win_strategy["win_themes"] = _dedupe_strings(
            win_strategy.get("win_themes", [])
            + [f"Do not ignore the historical caution surfaced in prior feedback: {semantic_context.get('cautions', [])[0]}"]
        )
        win_strategy["ghosting_strategy"] = _dedupe_strings(
            win_strategy.get("ghosting_strategy", [])
            + ["Ghost prior disliked patterns by proving this bid is not just another commodity or continuity-heavy support play."]
        )
    questions = _questions_to_ask(customer_priorities, capability_fit, partner_analysis, funding_analysis, document_inventory)
    questions["internal"] = _dedupe_strings(questions.get("internal", []) + normalized_questions)
    action_plan = _action_plan(document_inventory, funding_analysis, partner_analysis, capability_fit, recommendation.get("recommendation", ""))
    immediate_reasoning_actions: list[dict[str, str]] = []
    near_term_reasoning_actions: list[dict[str, str]] = []
    anomaly_signals = [str(item.get("signal") or "").strip().lower() for item in attachment_anomalies if isinstance(item, dict)]
    if any("page-limit" in item for item in anomaly_signals):
        immediate_reasoning_actions.append(
            {
                "owner_role": "Proposal Manager",
                "action": "Freeze the technical-volume assumption to 10 pages unless a formal clarification says otherwise.",
                "why": "The page-limit conflict creates avoidable compliance risk and can kill an otherwise good quote.",
                "dependency": "Current amendment package and any later formal clarification.",
                "priority": "High",
                "capture_value": "Protects compliance posture and forces a sharper technical narrative.",
            }
        )
    if _string_list(solicitation_facts.get("staffing_roles", []), max_items=8):
        immediate_reasoning_actions.append(
            {
                "owner_role": "Capture Lead + Recruiting",
                "action": "Build the staffing matrix and identify named or contingent candidates for all visible core FTE roles plus optional engineer coverage.",
                "why": "The labor mix is explicit, on-site, and central to credibility.",
                "dependency": "Role qualifications, candidate availability, and any local recruiting support.",
                "priority": "High",
                "capture_value": "Turns the staffing story from generic intent into a real discriminator.",
            }
        )
    if any(
        "transition and access plan" in item.lower()
        or "credentialing" in item.lower()
        or "site access" in item.lower()
        for item in _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8)
    ):
        immediate_reasoning_actions.append(
            {
                "owner_role": "Operations Lead",
                "action": "Draft a requirement-specific transition and access annex covering credentialing dependencies, access steps, workstation or tool readiness, and the first-30-day operating rhythm.",
                "why": "Access and onboarding dependencies are likely day-one failure points if they are treated as back-office details.",
                "dependency": "Candidate pipeline, access assumptions, and local onboarding procedures.",
                "priority": "High",
                "capture_value": "Directly answers continuity and execution-risk concerns.",
            }
        )
    if any("oci" in item.lower() or "sensitive-information" in item.lower() for item in _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8)):
        immediate_reasoning_actions.append(
            {
                "owner_role": "Contracts + Legal",
                "action": "Draft an OCI and sensitive-information control statement tied to acquisition-package support and third-party review boundaries.",
                "why": "The scope mixes useful support with areas that can trigger customer anxiety around decision authority and proprietary data.",
                "dependency": "PWS task mapping and any internal firewall / review procedures.",
                "priority": "High",
                "capture_value": "Reduces customer anxiety and strengthens the safe-pair-of-hands narrative.",
            }
        )
    if any("psr" in item.lower() or "qa/qc" in item.lower() for item in _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8)):
        near_term_reasoning_actions.append(
            {
                "owner_role": "Technical Lead",
                "action": "Produce a sample monthly PSR and a concise QA/QC control summary aligned to the task hierarchy, review cycle, and corrective-action loop.",
                "why": "The requirement signals that project-control discipline and QA/QC are part of the real evaluation story.",
                "dependency": "PWS task structure and draft staffing / management approach.",
                "priority": "High",
                "capture_value": "Creates tangible proof for a core win theme instead of leaving it as narrative.",
            }
        )
    if any("ffp pricing posture" in item.lower() or "pricing posture" in item.lower() for item in _string_list(strategic_reasoning.get("proof_requirements", []), max_items=8)):
        near_term_reasoning_actions.append(
            {
                "owner_role": "Pricing Lead",
                "action": "Complete a base-versus-optional engineer pricing model that shows executable FFP staffing rather than a buy-in strategy.",
                "why": "The RFQ explicitly raises price realism and imbalance concerns, so the rate structure has to look safe and deliberate.",
                "dependency": "Labor assumptions, optional CLIN treatment, and escalation posture.",
                "priority": "High",
                "capture_value": "Improves price realism credibility and reduces evaluator concern about underbidding.",
            }
        )
    if immediate_reasoning_actions:
        seen_immediate: set[str] = set()
        merged_immediate: list[dict[str, str]] = []
        for item in immediate_reasoning_actions + list(action_plan.get("immediate", [])):
            action_text = str(item.get("action", "") if isinstance(item, dict) else "").strip().lower()
            if not action_text or action_text in seen_immediate:
                continue
            seen_immediate.add(action_text)
            merged_immediate.append(item)
        action_plan["immediate"] = merged_immediate
    if near_term_reasoning_actions:
        seen_near: set[str] = set()
        merged_near: list[dict[str, str]] = []
        for item in near_term_reasoning_actions + list(action_plan.get("near_term", [])):
            action_text = str(item.get("action", "") if isinstance(item, dict) else "").strip().lower()
            if not action_text or action_text in seen_near:
                continue
            seen_near.add(action_text)
            merged_near.append(item)
        action_plan["near_term"] = merged_near

    snapshot = {
        "title": str(opportunity.get("title", "") or resolved.get("title", "") or "N/A"),
        "solicitation_number": str(opportunity.get("solicitation_number", "") or "Not stated"),
        "agency_bureau_program": str(resolved.get("buyer", "") or "Not stated"),
        "notice_type": str(opportunity.get("notice_type", "") or "Not stated"),
        "naics": (
            f"{solicitation_facts.get('naics')} - {solicitation_facts.get('naics_title')}".strip(" -")
            if str(solicitation_facts.get("naics") or "").strip()
            else (", ".join(_string_list(opportunity.get("naics", []))) or "Not stated")
        ),
        "naics_size_standard": str(solicitation_facts.get("naics_size_standard") or "Not stated"),
        "psc": ", ".join(_string_list(opportunity.get("other_taxonomy_tags", []))) or "Not stated",
        "contract_vehicle": str(solicitation_facts.get("contract_vehicle") or normalized_vehicle.get("name") or "").strip() or (", ".join(vehicle_access_paths) if vehicle_access_paths else ("Not a pre-existing vehicle gate from current evidence" if contract_structures else "Not explicit in current evidence")),
        "contract_structure": ", ".join(contract_structures) if contract_structures else "Not explicit in current evidence",
        "set_aside": set_aside_text,
        "contract_type": contract_type,
        "evaluation_basis": award_basis,
        "award_basis": award_basis,
        "transition_window": transition_window,
        "due_date": str(solicitation_facts.get("due_date") or opportunity.get("due_date", "") or "Not stated"),
        "days_until_due": str(opportunity.get("days_until_due", "") or "Not stated"),
        "estimated_value": str(normalized_contract_value.get("amount") or "").strip() or _currency(opportunity.get("estimated_value")),
        "period_of_performance": str(solicitation_facts.get("period_of_performance") or "Not stated"),
        "funds_status": str(solicitation_facts.get("funds_status") or "Not stated"),
        "place_of_performance": _location_text(opportunity),
        "opportunity_url": str(resolved.get("url", "") or "N/A"),
        "scan_bucket": str(opportunity.get("bucket", "") or "Not stated"),
        "scan_match_score": str(opportunity.get("match_score", "") or "Not stated"),
        "scan_confidence_score": str(opportunity.get("confidence_score", "") or "Not stated"),
        "incumbent_signal": incumbent.get("incumbent_name", "No confirmed incumbent"),
    }

    acquisition_strategy = {
        "requirement_type": _requirement_type(str(opportunity.get("notice_type", "") or ""), notice_text),
        "contract_vehicle": snapshot["contract_vehicle"],
        "contract_structure": snapshot["contract_structure"],
        "set_aside": snapshot["set_aside"],
        "contract_type": contract_type,
        "vehicle_assessment": _dedupe_strings(
            [
                *([f"Likely pre-existing vehicle or access gate: {', '.join(vehicle_access_paths)}."] if vehicle_access_paths else []),
                *([f"Contract structure appears to be: {', '.join(contract_structures)}."] if contract_structures else []),
                *(
                    ["No pre-existing GWAC / Schedule access gate is visible in the current record."]
                    if not vehicle_access_paths and contract_structures
                    else []
                ),
                *(
                    ["Vehicle path is still unconfirmed from the current package."]
                    if not vehicle_access_paths and not contract_structures
                    else []
                ),
                set_aside_statement,
                *(
                    [f"Vendor profile shows matching vehicle references: {', '.join(vehicle_profile_hits)}."]
                    if vehicle_profile_hits
                    else (
                        ["Vendor profile does not yet prove access to the visible vehicle path."]
                        if vehicle_access_required and vehicle_access_paths
                        else []
                    )
                ),
                *(
                    [f"Qualification gates surfaced in the notice: {', '.join(qualification_gaps.get('surfaced', []))}."]
                    if qualification_gaps.get("surfaced")
                    else []
                ),
                *_string_list(normalized_vehicle.get("evidence"), max_items=4),
                *(
                    [f'{normalized_contract_value.get("label", "Contract value / ceiling")}: {normalized_contract_value.get("amount")}']
                    if str(normalized_contract_value.get("amount") or "").strip()
                    else []
                ),
                *_solicitation_fact_lines(solicitation_facts),
                *(
                    [f'Attachment conflict to validate: {item.get("field")} -> {", ".join((item.get("values") or [])[:2])}.']
                    for item in attachment_conflicts[:2]
                    if isinstance(item, dict)
                ),
                *(
                    [f'Source conflict to validate: {item.get("field")} -> {", ".join((item.get("values") or [])[:2])}.']
                    for item in normalized_conflicts[:2]
                    if isinstance(item, dict)
                ),
            ]
        ),
        "solicitation_facts": _solicitation_fact_lines(solicitation_facts),
        "operational_constraints": _operational_constraint_lines(solicitation_facts, staffing_pricing_signals, attachment_workstreams),
        "staffing_pricing_signals": _dedupe_strings(
            _string_list(staffing_pricing_signals.get("staffing_notes", []), max_items=6)
            + _string_list(staffing_pricing_signals.get("pricing_notes", []), max_items=6)
            + _string_list(staffing_pricing_signals.get("evaluation_notes", []), max_items=4)
        ),
        "evaluation_basis": award_basis,
        "transition_window": transition_window,
        "shaping_signals": _dedupe_strings(
            [
                *(
                    ["Requirement appears to still be moving because amendment / Q&A language is present."]
                    if _contains_any(notice_text, list(SHAPING_MARKERS))
                    else []
                ),
                *gate_reasons,
            ]
        )
        or ["No obvious shaping signal surfaced beyond the current public package."],
        "capture_levers": _dedupe_strings(
            [
                "Clarify evaluation factors, transition expectations, and any hidden vehicle gate.",
                "Use formal Q&A to probe customer priorities that are still inferred, not proven.",
                *(
                    ["Secure vehicle access or a credible prime/teaming path before committing to a prime bid."]
                    if vehicle_access_required and not vehicle_access_ok
                    else []
                ),
                *(
                    ["Validate whether clearance and certification gates are prime-only requirements or can be satisfied through a teammate or facility sponsor."]
                    if qualification_gaps.get("surfaced")
                    else []
                ),
                *normalized_questions[:2],
            ]
        ),
        "vehicle_or_eligibility_gaps": _dedupe_strings(
            capability_fit.get("eligibility_gaps", [])[:4]
        ),
        "price_to_win_implications": win_strategy.get("price_to_win_considerations", []),
    }

    customer_priority_mode = str(customer_priorities.get("priority_rendering_mode") or "strong").strip().lower()
    assumptions = {
        "facts": _dedupe_strings(
            [
                f"Notice type: {snapshot['notice_type']}.",
                f"Set-aside: {snapshot['set_aside']}.",
                f"Contract type signal: {contract_type}.",
                f"Transition window signal: {transition_window}.",
                *( [f"Funds status: {snapshot['funds_status']}."] if snapshot["funds_status"] != "Not stated" else [] ),
                f"Funding confidence assessed as {funding_analysis['funding_confidence']}.",
                f"Current recommendation: {recommendation['recommendation']} ({recommendation['score_total']}/100).",
            ]
        ),
        "evidence_backed_inferences": _dedupe_strings(
            recommendation.get("rationale", [])[:4]
            + ([] if customer_priority_mode == "thin" else customer_priorities.get("evidence_backed_priorities", [])[:3])
        ),
        "hypotheses": _dedupe_strings(
            incumbent.get("prior_selection_hypotheses", [])[:3]
            + [f"Recommended posture is {partner_analysis.get('recommended_posture', 'undetermined')} until missing proof is closed."]
            + ([semantic_context.get("historical_pattern_summary", "")] if semantic_context.get("historical_pattern_summary") else [])
        ),
        "unknowns": _dedupe_strings(
            customer_priorities.get("unknowns", [])[:3]
            + funding_analysis.get("open_questions", [])[:2]
            + document_inventory.get("missing", [])[:2]
            + ([str(customer_priorities.get("priority_rendering_warning") or "").strip()] if customer_priority_mode == "thin" and str(customer_priorities.get("priority_rendering_warning") or "").strip() else [])
        ),
        "historical_learning_context": _dedupe_strings(
            semantic_context.get("support", [])[:2]
            + semantic_context.get("cautions", [])[:2]
            + ([semantic_context.get("summary", "")] if semantic_context.get("summary") else [])
        ),
        "overall_confidence": recommendation.get("confidence", "Medium"),
    }
    if normalized_conflicts:
        assumptions["unknowns"] = _dedupe_strings(
            assumptions.get("unknowns", [])
            + [f'Source conflict remains on {item.get("field")}.' for item in normalized_conflicts[:2] if isinstance(item, dict)]
        )
    if attachment_conflicts:
        assumptions["unknowns"] = _dedupe_strings(
            assumptions.get("unknowns", [])
            + [f'Attachment conflict remains on {item.get("field")}.' for item in attachment_conflicts[:2] if isinstance(item, dict)]
        )

    executive_judgment_lines = _dedupe_strings(
        [
            f"Recommendation: {recommendation.get('recommendation', 'Undetermined')} ({recommendation.get('score_total', 0)}/100, confidence {recommendation.get('confidence', 'Medium')}).",
            *recommendation.get("rationale", [])[:3],
            *(["Historical fit context: " + semantic_context.get("historical_pattern_summary", "")] if semantic_context.get("historical_pattern_summary") else []),
            *(["Strategic read: " + str(strategic_reasoning.get("reasoning_summary") or "").strip()] if str(strategic_reasoning.get("reasoning_summary") or "").strip() else []),
        ]
    )
    if recommendation.get("conditions"):
        executive_judgment_lines.append(f"Conditions: {'; '.join(recommendation.get('conditions', [])[:3])}.")

    return {
        "vendor_name": vendor_name,
        "capture_judgment": {
            "executive_summary": " ".join(executive_judgment_lines),
            "recommendation": recommendation.get("recommendation", "Undetermined"),
            "score_total": recommendation.get("score_total", 0),
            "confidence": recommendation.get("confidence", "Medium"),
            "score_breakdown": recommendation.get("score_breakdown", []),
            "why": recommendation.get("rationale", []),
            "conditions": recommendation.get("conditions", []),
            "credibility_requirements": capability_fit.get("credibility_requirements", []),
            "advantaged_players": _dedupe_strings(
                [incumbent.get("incumbent_name", "No confirmed incumbent")]
                + [item.get("name", "") for item in competitive_analysis[:2]]
            ),
            "customer_cares_about": _dedupe_strings(
                customer_priorities.get("evidence_backed_priorities", [])[:3]
                + ([] if customer_priority_mode == "thin" else customer_priorities.get("likely_priorities", [])[:2])
            ),
            "next_best_actions": _dedupe_strings(
                [item.get("action", "") for item in action_plan.get("immediate", [])[:3]]
            ),
            "historical_fit_context": _dedupe_strings(
                semantic_context.get("support", [])[:2] + semantic_context.get("cautions", [])[:2]
            ),
            "cross_source_conflicts": normalized_conflicts,
        },
        "opportunity_snapshot": snapshot,
        "pursuit_recommendation": recommendation,
        "evidence_ledger": _evidence_ledger(source_log),
        "document_inventory": document_inventory,
        "customer_mission_analysis": customer_priorities,
        "funding_trend_analysis": funding_analysis,
        "acquisition_strategy": acquisition_strategy,
        "incumbent_analysis": incumbent,
        "stakeholder_analysis": stakeholder_analysis,
        "competitive_analysis": competitive_analysis,
        "partner_analysis": partner_analysis,
        "capability_fit_analysis": {
            "company_summary": _profile_company_summary(vendor_profile),
            "capability_hits": capability_fit.get("capability_hits", []),
            "negative_hits": capability_fit.get("negative_hits", []),
            "proof_points": capability_fit.get("proof_points", []),
            "past_performance_inventory": capability_fit.get("past_performance_inventory", []),
            "past_performance_hits": capability_fit.get("past_performance_hits", []),
            "missing_proof": capability_fit.get("missing_proof", []),
            "qualification_gates": capability_fit.get("qualification_gates", []),
            "credibility_requirements": capability_fit.get("credibility_requirements", []),
            "recommended_prime_team_posture": partner_analysis.get("recommended_posture", "Undetermined"),
            "semantic_fit_summary": semantic_context.get("summary", ""),
            "historical_preference_support": semantic_context.get("support", []),
            "historical_preference_cautions": semantic_context.get("cautions", []),
            "fit_weighting_signals": capability_fit.get("fit_weighting_signals", []),
            "fit_weighting_cautions": capability_fit.get("fit_weighting_cautions", []),
            "fit_weighting_summary": capability_fit.get("fit_weighting_summary", ""),
        },
        "subtle_signals": subtle_signals,
        "win_strategy": win_strategy,
        "questions_to_ask": questions,
        "capture_action_plan": action_plan,
        "assumptions_unknowns_confidence": assumptions,
        "normalized_evidence": normalized_evidence,
    }
