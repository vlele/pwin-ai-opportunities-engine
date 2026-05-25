from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


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
    "privacy",
    "security",
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


def _contains_any(text: str, phrases: tuple[str, ...] | list[str]) -> bool:
    lower = text.lower()
    return any(phrase.lower() in lower for phrase in phrases)


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


def _priority_analysis(
    notice_text: str,
    public_research: dict[str, Any],
    attachment_bundle: dict[str, Any],
    award_basis: str,
    contract_type: str,
) -> dict[str, list[str] | str]:
    lower = notice_text.lower()
    evidence_backed: list[str] = []
    likely: list[str] = []
    unknowns: list[str] = []
    pain_points: list[str] = []
    repeated_language: list[str] = []

    if _contains_any(lower, list(CONTINUITY_MARKERS)):
        evidence_backed.append("Continuity of operations and low transition risk appear to matter, based on direct continuity language in the notice or attachments.")
        pain_points.append("The customer appears sensitive to service disruption, transition delay, or mission lapse risk.")
    if _contains_any(lower, list(POLICY_MARKERS)) or public_research.get("policy_compliance_signals"):
        evidence_backed.append("Compliance, security, or audit-ready delivery appears important because policy or control language surfaced in the public package.")
    if "report" in lower or "dashboard" in lower or "metrics" in lower:
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
    if public_research.get("mission_context_signals"):
        repeated_language.extend(_string_list(public_research.get("mission_context_signals", []), max_items=3))
    if not public_research.get("mission_context_signals"):
        unknowns.append("Mission problem is still inferred because no strong agency strategy or program document was captured.")
    if award_basis == "Evaluation basis not explicit in current evidence":
        unknowns.append("Evaluation weighting is still unknown because the current package did not expose factors or basis of award clearly.")
    if not public_research.get("leadership_priority_signals"):
        unknowns.append("Program-level customer priorities still need validation through named officials, industry day material, or formal Q&A.")

    mission_problem = (
        _clean_excerpt(public_research.get("mission_context_signals", [])[0], max_chars=320)
        if public_research.get("mission_context_signals")
        else "Mission problem is not corroborated beyond the solicitation text in current evidence."
    )

    return {
        "mission_problem": mission_problem,
        "evidence_backed_priorities": _dedupe_strings(evidence_backed),
        "likely_priorities": _dedupe_strings(likely),
        "unknowns": _dedupe_strings(unknowns),
        "pain_points": _dedupe_strings(pain_points),
        "repeated_language": _dedupe_strings(repeated_language)[:5],
    }


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
        strength_signals.append("Continuity language suggests the customer is sensitive to transition risk, which usually helps an incumbent or deeply embedded performer.")
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
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    active_procurement = str(opportunity.get("due_date", "") or "").strip() != ""
    for contact in stakeholder_contacts:
        role = str(contact.get("role", "") or "Contact").strip()
        influence = "Contracting process / communication"
        question = "Confirm the final communication path, amendment cadence, and proposal instructions."
        if "program" in role.lower() or "technical" in role.lower() or "project" in role.lower():
            influence = "Program scope / technical expectations"
            question = "Clarify the operational pain point, transition expectations, and performance metrics."
        elif "small business" in role.lower():
            influence = "Socioeconomic posture / outreach"
            question = "Clarify set-aside posture, small-business participation goals, and approved outreach channels."
        rows.append(
            {
                "name": str(contact.get("name", "") or "Unnamed contact").strip(),
                "role": role,
                "contact": str(contact.get("email", "") or "Public contact not parsed").strip(),
                "influence": influence,
                "capture_question": question,
                "communication": "Formal Q&A only during active solicitation." if active_procurement else "Use official industry outreach channels only.",
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
            }
        )
    return rows


def _competitive_analysis(
    award_signals: dict[str, Any],
    incumbent_name: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    relevant_awards = award_signals.get("relevant_awards", []) or []
    agency_matched = [award for award in relevant_awards if award.get("_agency_match")]
    candidate_awards = agency_matched or relevant_awards
    for award in candidate_awards:
        name = str(award.get("Recipient Name", "") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        agency_match = bool(award.get("_agency_match"))
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
        description = _clean_excerpt(award.get("Description", ""), max_chars=180)
        rows.append(
            {
                "name": name,
                "why_likely": f"Matched award {award.get('Award ID', 'N/A')} for {_currency(award.get('Award Amount'))}; scope overlap appears in public award description.",
                "strengths": " ".join(_dedupe_strings(strengths)) or "Relevant performer in adjacent public award history.",
                "weaknesses": " ".join(_dedupe_strings(weaknesses)) or "No clear weakness surfaced in public data; validation still needed.",
                "likely_strategy": f"Likely to emphasize {'continuity and agency familiarity' if agency_match else 'adjacent domain credibility and relevant scale'}." ,
                "partner_relevance": "Low as a likely prime competitor unless the firm is clearly positioned as a subcontractor on this procurement.",
                "evidence": description or "Public award description not returned.",
            }
        )
        if len(rows) >= 5:
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
                "why_it_matters": "This often indicates incumbent advantage, short tolerance for transition risk, and a bias toward proven delivery rather than innovation theater.",
                "effect": "Hurts us unless we can neutralize transition risk.",
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
    if attachment_bundle.get("attachments_expected") and not attachments:
        missing.append("Attachment package was expected, but no files were parsed in this run.")
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
        ]
    )
    return {
        "found": found or ["No attachments or downloadable documents were surfaced in this run."],
        "parsed": parsed or ["No attachment parsed cleanly enough to rely on as a scope source."],
        "missing": _dedupe_strings(missing) or ["No specific missing document was proven, but the full package still needs manual completeness review."],
        "inaccessible": inaccessible or ["No explicit access error was logged."],
        "controlled": controlled or ["No controlled-source document was explicitly flagged in this run."],
        "action_items": action_items,
    }


def _capability_fit(
    profile: dict[str, Any],
    opportunity: dict[str, Any],
    notice_text: str,
    customer_priorities: dict[str, Any],
    vehicle_access_ok: bool,
    vehicle_access_required: bool,
    set_aside_access_ok: bool,
    qualification_gaps: dict[str, list[str]],
) -> dict[str, Any]:
    keywords = _profile_keywords(profile)
    negative_keywords = _profile_negative_keywords(profile)
    fit_guidance = _fit_narrative_guidance(profile)
    past_performance = _profile_past_performance(profile)
    profile_naics = _profile_naics(profile)
    opportunity_naics = [str(item).strip() for item in (opportunity.get("naics", []) or []) if str(item).strip()]
    capability_hits = _dedupe_strings(
        _phrase_hits(notice_text, keywords, max_items=8)
        + _phrase_hits(notice_text, fit_guidance.get("positive_terms", []), max_items=4)
    )[:8]
    negative_hits = _dedupe_strings(
        _phrase_hits(notice_text, negative_keywords, max_items=5)
        + _phrase_hits(notice_text, fit_guidance.get("negative_terms", []), max_items=4)
    )[:6]
    past_performance_hits = _phrase_hits(notice_text, past_performance, max_items=4)
    naics_match = bool(set(profile_naics) & set(opportunity_naics))

    proof_points = _dedupe_strings(capability_hits + past_performance_hits)
    if not proof_points and keywords:
        proof_points.extend(keywords[:3])

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

    credibility_requirements: list[str] = []
    if customer_priorities.get("evidence_backed_priorities"):
        credibility_requirements.append("Map past performance and proof points directly to the evidence-backed customer priorities.")
    if _contains_any(notice_text.lower(), list(CONTINUITY_MARKERS)):
        credibility_requirements.append("Show a transition plan, mobilization timeline, and low-disruption staffing approach strong enough to counter continuity bias.")
    if customer_priorities.get("likely_priorities"):
        credibility_requirements.append("Back claims with specific delivery examples, not generic capability statements.")
    if _contains_any(notice_text.lower(), list(POLICY_MARKERS)):
        credibility_requirements.append("Produce compliance artifacts, control mappings, or policy-ready delivery evidence.")
    if not past_performance:
        credibility_requirements.append("Bring partner or subcontractor past performance if in-house proof is thin.")
    if qualification_gaps.get("surfaced"):
        credibility_requirements.append(f"Close hard qualification gaps: {', '.join(qualification_gaps.get('surfaced', []))}.")

    return {
        "capability_hits": capability_hits,
        "negative_hits": negative_hits,
        "fit_narrative_positive_hits": _phrase_hits(notice_text, fit_guidance.get("positive_terms", []), max_items=4),
        "fit_narrative_negative_hits": _phrase_hits(notice_text, fit_guidance.get("negative_terms", []), max_items=4),
        "past_performance_hits": past_performance_hits,
        "naics_match": naics_match,
        "proof_points": proof_points,
        "missing_proof": _dedupe_strings(missing_proof),
        "credibility_requirements": _dedupe_strings(credibility_requirements),
        "past_performance_inventory": past_performance,
        "qualification_gates": qualification_gaps.get("surfaced", []),
        "missing_qualification_gates": qualification_gaps.get("missing_labels", []),
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
    customer_alignment = _clamp(
        5
        + min(6, len(customer_priorities.get("evidence_backed_priorities", [])) * 2)
        + min(4, len(customer_priorities.get("likely_priorities", []))),
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
    past_perf_fit = _clamp(
        2
        + (6 if len(capability_fit.get("past_performance_inventory", [])) >= 3 else 4 if capability_fit.get("past_performance_inventory") else 0)
        + min(4, len(capability_fit.get("past_performance_hits", []))),
        0,
        15,
    )
    funding_confidence = {"High": 9, "Medium": 6, "Low": 3}.get(str(funding_analysis.get("funding_confidence", "Low")), 3)
    qualification_gap_count = len(capability_fit.get("missing_qualification_gates", []))
    vehicle_access = 8 if vehicle_access_ok and set_aside_access_ok else 5 if vehicle_access_ok or set_aside_access_ok else 2
    if qualification_gap_count:
        vehicle_access = max(1, vehicle_access - min(6, qualification_gap_count * 2))
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

    if qualification_gap_count:
        access_rationale = "Driven by hard qualification gates surfaced in the notice, such as clearances or required certifications, plus any set-aside or vehicle access issues."
    elif vehicle_access_required:
        access_rationale = "Driven by whether the opportunity appears to require a pre-existing contract vehicle and whether the profile shows access."
    elif not set_aside_access_ok:
        access_rationale = "Driven mainly by socioeconomic eligibility because no pre-existing vehicle gate is clearly visible."
    else:
        access_rationale = "No pre-existing vehicle gate or socioeconomic barrier is visible in current evidence, so this score stays stronger unless other access blockers surface."

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
) -> dict[str, list[str]]:
    hot_buttons = _dedupe_strings(
        customer_priorities.get("evidence_backed_priorities", [])[:3]
        + customer_priorities.get("likely_priorities", [])[:2]
    )
    win_themes = _dedupe_strings(
        [
            "De-risk the mission outcome, not just the labor category map.",
            "Show evidence-backed past performance tied to the customer's visible pain points.",
            *(
                ["Present a low-disruption transition story that directly answers continuity concerns."]
                if any("continuity" in item.lower() or "transition" in item.lower() for item in hot_buttons)
                else []
            ),
            *(
                ["Prove fixed-price discipline with scope control, staffing realism, and management reporting."]
                if contract_type == "Firm Fixed Price"
                else []
            ),
        ]
    )
    discriminators = _dedupe_strings(
        [
            *([f"Relevant proof point: {item}" for item in capability_fit.get("proof_points", [])[:4]]),
            "A capture story that links mission outcomes, transition credibility, and compliance readiness in one narrative.",
        ]
    )
    ghosting = _dedupe_strings(
        [
            *(
                ["Ghost the incumbent on transition risk by offering a named mobilization plan, knowledge-transfer cadence, and low-drama staffing ramp."]
                if incumbent_analysis.get("strength_signals")
                else []
            ),
            *(
                ["Ghost labor-heavy competitors by showing tighter scope control and lower management overhead under fixed-price delivery."]
                if contract_type == "Firm Fixed Price"
                else []
            ),
            *(
                ["Ghost generic IT firms by tying proof points directly to policy, control, and mission-specific outcomes."]
                if policy_signals
                else []
            ),
        ]
    )
    price_to_win = _dedupe_strings(
        [
            "Use predecessor award values and visible contract type to build an initial price-to-win range.",
            *(
                ["Stress affordability, scope control, and low transition friction in any early pricing posture."]
                if contract_type == "Firm Fixed Price"
                else ["Do not assume price is secondary; keep PTW analysis active until evaluation factors are confirmed."]
            ),
        ]
    )
    transition = _dedupe_strings(
        [
            "Build a day-1 readiness story with staffing, knowledge transfer, governance, and risk burn-down.",
            *(
                ["If displacing an incumbent, show exactly how service continuity will be protected in the first 30-60 days."]
                if incumbent_analysis.get("strength_signals")
                else []
            ),
        ]
    )
    staffing = _dedupe_strings(
        [
            "Prioritize key personnel or SMEs who can demonstrate customer-facing credibility immediately.",
            "Tie resumes and staffing assumptions to the visible customer pain points and control environment.",
        ]
    )
    compliance = _dedupe_strings(
        [
            "Build a light compliance matrix from the notice, attachments, and policy sources before solution lock.",
            *([f"Use surfaced policy artifact: {item}" for item in policy_signals[:3]]),
        ]
    )
    partner = _dedupe_strings(
        partner_analysis.get("best_partner_candidates", [])[:3]
        + partner_analysis.get("partner_outreach_action_items", [])[:2]
    )
    return {
        "hot_buttons": hot_buttons or ["Customer hot buttons remain partly inferred pending full solicitation and Q&A review."],
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
            "why": "Missing or partial documents are the fastest way to misjudge evaluation drivers, transition scope, and incumbent advantage.",
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
) -> dict[str, Any]:
    vendor_name = _profile_company_name(vendor_profile)
    notice_text = " ".join(
        [
            str(opportunity.get("title", "") or ""),
            str(opportunity.get("summary", "") or ""),
            str(explanation.get("summary", "") or ""),
            notice_context_text,
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
    set_aside_text = str(opportunity.get("set_aside", "") or "Not stated")
    set_aside_statement, set_aside_access_ok = _set_aside_access(set_aside_text, _profile_set_asides(vendor_profile))
    qualification_gaps = _required_qualification_gaps(vendor_profile, notice_text)
    semantic_context = _semantic_capture_context(opportunity, learned_semantic_preferences)
    customer_priorities = _priority_analysis(notice_text, public_research, attachment_bundle, award_basis, contract_type)
    funding_analysis = _funding_analysis(funding_assessment, award_signals, public_research, attachment_bundle, evidence_gaps)
    incumbent = _incumbent_analysis(notice_text, award_signals, attachment_validation, attachment_bundle)
    stakeholder_analysis = _stakeholder_analysis(resolved.get("buyer", ""), stakeholder_contacts, opportunity)
    vehicle_access_ok = (not vehicle_access_required) or bool(vehicle_profile_hits)
    capability_fit = _capability_fit(
        vendor_profile,
        opportunity,
        notice_text,
        customer_priorities,
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
    partner_analysis = _partner_analysis(
        vendor_profile,
        capability_fit,
        vehicle_access_paths,
        vehicle_access_required,
        vehicle_profile_hits,
        set_aside_access_ok,
        incumbent,
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
    competitive_analysis = _competitive_analysis(award_signals, incumbent.get("incumbent_name", ""))
    subtle_signals = _subtle_signals(
        notice_text,
        opportunity,
        attachment_bundle,
        public_research,
        str(funding_analysis.get("funding_confidence", "Low")),
        vehicle_access_paths + contract_structures,
    )
    win_strategy = _win_strategy(
        customer_priorities,
        capability_fit,
        partner_analysis,
        contract_type,
        incumbent,
        _string_list(public_research.get("policy_compliance_signals", []), max_items=4),
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
    action_plan = _action_plan(document_inventory, funding_analysis, partner_analysis, capability_fit, recommendation.get("recommendation", ""))

    snapshot = {
        "title": str(opportunity.get("title", "") or resolved.get("title", "") or "N/A"),
        "solicitation_number": str(opportunity.get("solicitation_number", "") or "Not stated"),
        "agency_bureau_program": str(resolved.get("buyer", "") or "Not stated"),
        "notice_type": str(opportunity.get("notice_type", "") or "Not stated"),
        "naics": ", ".join(_string_list(opportunity.get("naics", []))) or "Not stated",
        "psc": ", ".join(_string_list(opportunity.get("other_taxonomy_tags", []))) or "Not stated",
        "contract_vehicle": ", ".join(vehicle_access_paths) if vehicle_access_paths else ("Not a pre-existing vehicle gate from current evidence" if contract_structures else "Not explicit in current evidence"),
        "contract_structure": ", ".join(contract_structures) if contract_structures else "Not explicit in current evidence",
        "set_aside": set_aside_text,
        "contract_type": contract_type,
        "evaluation_basis": award_basis,
        "award_basis": award_basis,
        "transition_window": transition_window,
        "due_date": str(opportunity.get("due_date", "") or "Not stated"),
        "days_until_due": str(opportunity.get("days_until_due", "") or "Not stated"),
        "estimated_value": _currency(opportunity.get("estimated_value")),
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
            ]
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
            ]
        ),
        "vehicle_or_eligibility_gaps": _dedupe_strings(
            capability_fit.get("missing_proof", [])[:4]
            + ([] if set_aside_access_ok else [set_aside_statement])
        ),
        "price_to_win_implications": win_strategy.get("price_to_win_considerations", []),
    }

    assumptions = {
        "facts": _dedupe_strings(
            [
                f"Notice type: {snapshot['notice_type']}.",
                f"Set-aside: {snapshot['set_aside']}.",
                f"Contract type signal: {contract_type}.",
                f"Transition window signal: {transition_window}.",
                f"Funding confidence assessed as {funding_analysis['funding_confidence']}.",
                f"Current recommendation: {recommendation['recommendation']} ({recommendation['score_total']}/100).",
            ]
        ),
        "evidence_backed_inferences": _dedupe_strings(
            recommendation.get("rationale", [])[:4]
            + customer_priorities.get("evidence_backed_priorities", [])[:3]
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
        ),
        "historical_learning_context": _dedupe_strings(
            semantic_context.get("support", [])[:2]
            + semantic_context.get("cautions", [])[:2]
            + ([semantic_context.get("summary", "")] if semantic_context.get("summary") else [])
        ),
        "overall_confidence": recommendation.get("confidence", "Medium"),
    }

    executive_judgment_lines = _dedupe_strings(
        [
            f"Recommendation: {recommendation.get('recommendation', 'Undetermined')} ({recommendation.get('score_total', 0)}/100, confidence {recommendation.get('confidence', 'Medium')}).",
            *recommendation.get("rationale", [])[:3],
            *(["Historical fit context: " + semantic_context.get("historical_pattern_summary", "")] if semantic_context.get("historical_pattern_summary") else []),
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
                + customer_priorities.get("likely_priorities", [])[:2]
            ),
            "next_best_actions": _dedupe_strings(
                [item.get("action", "") for item in action_plan.get("immediate", [])[:3]]
            ),
            "historical_fit_context": _dedupe_strings(
                semantic_context.get("support", [])[:2] + semantic_context.get("cautions", [])[:2]
            ),
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
            "credibility_requirements": capability_fit.get("credibility_requirements", []),
            "recommended_prime_team_posture": partner_analysis.get("recommended_posture", "Undetermined"),
            "semantic_fit_summary": semantic_context.get("summary", ""),
            "historical_preference_support": semantic_context.get("support", []),
            "historical_preference_cautions": semantic_context.get("cautions", []),
        },
        "subtle_signals": subtle_signals,
        "win_strategy": win_strategy,
        "questions_to_ask": questions,
        "capture_action_plan": action_plan,
        "assumptions_unknowns_confidence": assumptions,
    }
