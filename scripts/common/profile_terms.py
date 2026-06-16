from __future__ import annotations

import re
from typing import Any, Iterable


LOW_SIGNAL_PROFILE_TERMS = frozenset(
    {
        "about",
        "about us",
        "blog",
        "capabilities",
        "careers",
        "case studies",
        "case study",
        "clients",
        "contact",
        "contact us",
        "customers",
        "digital services",
        "events",
        "home",
        "homepage",
        "industries",
        "insights",
        "leadership",
        "logistics",
        "news",
        "our capabilities",
        "our services",
        "our solutions",
        "our team",
        "partners",
        "privacy policy",
        "resources",
        "service",
        "services",
        "sitemap",
        "solutions",
        "team",
        "terms of use",
        "what we do",
        "who we are",
    }
)


def normalize_profile_term(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def is_low_signal_profile_term(value: Any) -> bool:
    return normalize_profile_term(value) in LOW_SIGNAL_PROFILE_TERMS


def filter_low_signal_profile_terms(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or is_low_signal_profile_term(text):
            continue
        key = normalize_profile_term(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
