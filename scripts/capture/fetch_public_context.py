from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import io
import json
import re
import ssl
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from PyPDF2 import PdfReader


TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
META_ATTR_RE = re.compile(r"([A-Za-z:_-]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)
PARAGRAPH_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
LIST_ITEM_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
TIME_RE = re.compile(r"<time\b[^>]*datetime=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
JSON_DATE_RE = re.compile(r'"(?:datePublished|dateModified|datePosted|dateCreated|uploadDate)"\s*:\s*"([^"]+)"', re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9/-]{2,}")
URL_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
SEARCH_URL = "https://www.bing.com/search?format=rss&q={query}"
SEARCH_RESULT_LIMIT = 6
DEFAULT_TIMEOUT = 25
DEFAULT_MAX_BYTES = 4_000_000
SITEMAP_DOC_LIMIT = 24
SITEMAP_URL_LIMIT = 120_000
DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
OFFICIAL_HOSTS = {
    "gao.gov",
    "whitehouse.gov",
    "nist.gov",
    "cio.gov",
    "cisa.gov",
    "fedramp.gov",
    "gsa.gov",
    "section508.gov",
    "archives.gov",
    "usaspending.gov",
    "sam.gov",
    "acquisition.gov",
    "oversight.gov",
    "congress.gov",
    "house.gov",
    "senate.gov",
    "fam.state.gov",
    "usace.army.mil",
    "erdc.usace.army.mil",
    "dodig.mil",
    "dodcio.defense.gov",
    "acq.osd.mil",
}
AGENCY_DOMAIN_HINTS = {
    "internal revenue service": ["irs.gov", "home.treasury.gov"],
    "treasury, department of the": ["home.treasury.gov"],
    "department of the treasury": ["home.treasury.gov"],
    "department of defense": ["defense.gov"],
    "dept of defense": ["defense.gov"],
    "department of the army": ["army.mil"],
    "dept of the army": ["army.mil"],
    "department of the air force": ["af.mil", "airforce.com"],
    "dept of the air force": ["af.mil", "airforce.com"],
    "department of the navy": ["navy.mil", "marines.mil"],
    "us coast guard": ["uscg.mil", "dhs.gov"],
    "department of homeland security": ["dhs.gov"],
    "department of commerce": ["commerce.gov"],
    "national oceanic and atmospheric administration": ["noaa.gov", "commerce.gov"],
    "health and human services": ["hhs.gov"],
    "department of veterans affairs": ["va.gov"],
    "veterans affairs": ["va.gov"],
    "department of state": ["state.gov"],
    "bureau of international narcotics and law enforcement affairs": ["fam.state.gov", "state.gov"],
    "acquisitions - inl": ["fam.state.gov", "state.gov"],
    "department of energy": ["energy.gov"],
    "department of the interior": ["doi.gov"],
    "general services administration": ["gsa.gov"],
    "federal deposit insurance corporation": ["fdic.gov"],
    "house of representatives": ["house.gov"],
    "selective service system": ["sss.gov"],
    "small business administration": ["sba.gov"],
    "indian health service": ["ihs.gov"],
    "us army corps of engineers": ["erdc.usace.army.mil", "usace.army.mil"],
    "engineer research and development center": ["erdc.usace.army.mil", "usace.army.mil"],
}
AGENCY_OVERSIGHT_HINTS = {
    "internal revenue service": ["tigta.gov", "oversight.gov"],
    "treasury, department of the": ["tigta.gov", "oversight.gov"],
    "department of the treasury": ["tigta.gov", "oversight.gov"],
    "department of defense": ["dodig.mil", "oversight.gov"],
    "dept of defense": ["dodig.mil", "oversight.gov"],
    "department of the army": ["dodig.mil", "oversight.gov"],
    "us army corps of engineers": ["dodig.mil", "oversight.gov"],
    "engineer research and development center": ["dodig.mil", "oversight.gov"],
}
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
    "project",
    "contract",
}
LANGUAGE_PATH_PREFIXES = {"es", "zh-hans", "zh-hant", "ko", "ru", "vi", "ht"}
BOILERPLATE_MARKERS = (
    "javascript is disabled",
    "skip to main content",
    "an official website of the united states government",
    "window.datalayer",
    "gtag(",
    "woff2",
    "@font-face",
    "font-family",
    "cookies",
    "accept all cookies",
    "we use cookies",
)
GENERIC_LABEL_TOKENS = {
    "of",
    "and",
    "the",
    "department",
    "dept",
    "office",
    "bureau",
    "directorate",
    "command",
    "administration",
    "administrative",
    "acquisitions",
    "services",
    "service",
    "support",
    "internal",
    "state",
    "defense",
    "army",
    "usa",
    "us",
}
CATEGORY_URL_HINTS = {
    "mission_context": (
        "strategic-plan",
        "it-modernization",
        "digital-strategy",
        "data-strategy",
        "technology-roadmap",
        "zero-trust",
        "operating-plan",
        "modernization",
        "roadmap",
        "digital",
        "data",
    ),
    "budget_funding": ("budget", "justification", "appropriation", "performance", "capital-investments", "operating-plan"),
    "acquisition_forecast": ("acquisition", "procurement", "forecast", "industry-day", "procurement-forecast", "forecasted-business-opportunities"),
    "oversight": ("oversight", "audit", "report", "management", "inspection", "watchdog", "tax-administration"),
    "leadership": ("commissioner", "leadership", "official", "organization", "remarks", "testimony", "about-irs"),
    "policy_compliance": ("publication", "privacy", "security", "safeguards", "accessibility", "zero-trust", "508", "nist"),
    "public_discourse": ("news", "newsroom", "press", "remarks", "testimony", "speech", "featured-stories"),
}
CATEGORY_TEXT_HINTS = {
    "mission_context": (
        "strategic plan",
        "it modernization",
        "digital strategy",
        "data strategy",
        "technology roadmap",
        "zero trust",
        "modernization",
        "technology",
    ),
    "budget_funding": ("budget", "appropriation", "performance", "funding", "investment", "justification"),
    "acquisition_forecast": ("forecast", "forecasted business opportunities", "industry day", "procurement", "acquisition"),
    "oversight": ("audit", "recommendation", "finding", "oversight", "inspector general", "watchdog"),
    "leadership": ("commissioner", "chief", "official", "testimony", "remarks", "leadership"),
    "policy_compliance": ("publication", "nist", "privacy", "security", "fedramp", "zero trust", "accessibility"),
    "public_discourse": ("news", "announcement", "remarks", "testimony", "press release", "speech"),
}
MISSION_CONTEXT_MARKERS = (
    "strategic plan",
    "it modernization",
    "digital strategy",
    "data strategy",
    "technology roadmap",
    "zero trust",
    "modernization",
    "roadmap",
    "operating plan",
    "research and development",
)
BUDGET_FUNDING_MARKERS = (
    "budget",
    "justification",
    "appropriation",
    "financial report",
    "agency financial report",
    "plans, performance, budget",
    "performance budget",
)
FORECAST_MARKERS = (
    "forecast",
    "forecasted business opportunities",
    "procurement forecast",
    "industry day",
    "forecasted",
)
POLICY_DIRECT_URLS = {
    "NIST SP 800-53": ["https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final"],
    "NIST SP 800-61": ["https://csrc.nist.gov/pubs/sp/800/61/r2/final"],
    "Section 508": ["https://www.section508.gov/"],
    "FedRAMP": ["https://www.fedramp.gov/"],
}
AGENCY_DIRECT_URLS = {
    "state.gov": {
        "mission_context": [
            "https://fam.state.gov/fam/01fam/01fam0530.html",
            "https://2017-2021.state.gov/bureaus-offices/under-secretary-for-civilian-security-democracy-and-human-rights/bureau-of-international-narcotics-and-law-enforcement-affairs",
            "https://2021-2025.state.gov/justice-programs-in-action/",
        ],
        "budget_funding": [
            "https://2017-2021.state.gov/plans-performance-budget",
        ],
    },
    "fam.state.gov": {
        "mission_context": [
            "https://fam.state.gov/fam/01fam/01fam0530.html",
        ],
        "budget_funding": [
            "https://2017-2021.state.gov/plans-performance-budget",
        ],
    },
    "erdc.usace.army.mil": {
        "mission_context": [
            "https://www.erdc.usace.army.mil/About/",
        ],
        "acquisition_forecast": [
            "https://www.erdc.usace.army.mil/Business-With-Us/Small-Business/",
            "https://www.erdc.usace.army.mil/Media/Images/igphoto/2003821542/",
        ],
    },
    "usace.army.mil": {
        "mission_context": [
            "https://www.erdc.usace.army.mil/About/",
        ],
        "acquisition_forecast": [
            "https://www.erdc.usace.army.mil/Business-With-Us/Small-Business/",
            "https://www.erdc.usace.army.mil/Media/Images/igphoto/2003821542/",
        ],
    },
}
NON_REQUIREMENT_KEYWORDS = {
    "support",
    "service",
    "services",
    "program",
    "system",
    "task",
    "order",
    "contract",
    "contracting",
    "solicitation",
    "proposal",
    "offeror",
    "notice",
    "amendment",
    "questions",
    "response",
    "responses",
    "vendor",
    "federal",
    "agency",
    "office",
    "department",
}
POLICY_FALLBACK_DOMAINS = [
    "nist.gov",
    "whitehouse.gov",
    "section508.gov",
    "fedramp.gov",
    "archives.gov",
]
GENERIC_ENTITY_TOKENS = {"internal", "office", "focused"}
SITEMAP_CACHE: dict[str, list[str]] = {}
POLICY_REFERENCE_PATTERNS = [
    {
        "label": "IRS Publication 4812",
        "pattern": re.compile(r"(irs\s+publication\s+4812|publication\s+4812)", re.IGNORECASE),
        "domains": ["irs.gov"],
    },
    {
        "label": "NIST SP 800-53",
        "pattern": re.compile(r"nist(?:\s+sp)?\s*800[- ]53", re.IGNORECASE),
        "domains": ["nist.gov"],
    },
    {
        "label": "NIST SP 800-61",
        "pattern": re.compile(r"nist(?:\s+sp)?\s*800[- ]61", re.IGNORECASE),
        "domains": ["nist.gov"],
    },
    {
        "label": "FedRAMP",
        "pattern": re.compile(r"\bfedramp\b", re.IGNORECASE),
        "domains": ["fedramp.gov"],
    },
    {
        "label": "FISMA",
        "pattern": re.compile(r"\bfisma\b", re.IGNORECASE),
        "domains": ["cisa.gov", "whitehouse.gov"],
    },
    {
        "label": "Section 508",
        "pattern": re.compile(r"section\s+508|\b508\b", re.IGNORECASE),
        "domains": ["section508.gov", "gsa.gov"],
    },
    {
        "label": "CUI",
        "pattern": re.compile(r"\bcui\b", re.IGNORECASE),
        "domains": ["archives.gov"],
    },
    {
        "label": "Zero Trust",
        "pattern": re.compile(r"zero\s+trust", re.IGNORECASE),
        "domains": ["cisa.gov", "whitehouse.gov"],
    },
    {
        "label": "CMMC Level 2",
        "pattern": re.compile(r"cmmc\s+level\s+2|c3pao", re.IGNORECASE),
        "domains": ["dodcio.defense.gov", "acq.osd.mil"],
    },
    {
        "label": "Privacy",
        "pattern": re.compile(r"\bprivacy\b", re.IGNORECASE),
        "domains": ["whitehouse.gov", "gsa.gov"],
    },
]
LEADERSHIP_ROLE_QUERIES = (
    "Chief Information Officer",
    "Chief Data Officer",
    "Chief AI Officer",
    "Chief Acquisition Officer",
    "Commissioner",
    "Director",
)


def _today_local_str() -> str:
    return datetime.now().astimezone().date().isoformat()


def _normalize_text(value: object) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(str(value or "")))).strip()


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0].lstrip("www.")


def _matches_domain(host: str, domain: str) -> bool:
    normalized = domain.lower().lstrip("www.")
    return host == normalized or host.endswith(f".{normalized}")


def _is_official_url(url: str, domain_hints: list[str] | None = None) -> bool:
    host = _host(url)
    hints = [hint.lower().lstrip("www.") for hint in (domain_hints or []) if hint]
    if any(_matches_domain(host, hint) for hint in hints):
        return True
    return host.endswith(".gov") or host.endswith(".mil") or host in OFFICIAL_HOSTS


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = SPACE_RE.sub(" ", str(value or "").strip())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _signal_tokens(*values: object) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        for token in WORD_RE.findall(_normalize_text(value).lower()):
            if token in SIGNAL_STOPWORDS or token.isdigit() or len(token) < 4:
                continue
            counts[token] = counts.get(token, 0) + 1
    return [token for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _top_keywords(title: str, notice_text: str, limit: int = 8) -> list[str]:
    title_tokens = [token for token in _signal_tokens(title) if token not in NON_REQUIREMENT_KEYWORDS]
    notice_tokens = [token for token in _signal_tokens(notice_text) if token not in NON_REQUIREMENT_KEYWORDS]
    combined: list[str] = []
    seen: set[str] = set()
    for token in title_tokens + notice_tokens:
        if token in seen:
            continue
        seen.add(token)
        combined.append(token)
        if len(combined) >= limit:
            break
    return combined


def _keyword_query_clause(keywords: list[str], limit: int = 3) -> str:
    selected: list[str] = []
    for keyword in keywords:
        cleaned = _normalize_text(keyword).lower()
        if not cleaned or cleaned in NON_REQUIREMENT_KEYWORDS:
            continue
        selected.append(cleaned)
        if len(selected) >= limit:
            break
    if not selected:
        return ""
    return "(" + " OR ".join(f'"{keyword}"' for keyword in selected) + ")"


def _clean_notice_seed(notice_text: str, max_chars: int = 2400) -> str:
    return _normalize_text(notice_text)[:max_chars]


def _agency_labels(buyer: str) -> list[str]:
    chain = [segment.strip() for segment in str(buyer or "").split(".") if segment.strip()]
    if not chain:
        return []
    def specificity(segment: str) -> tuple[int, int]:
        words = [
            word.lower()
            for word in re.findall(r"[A-Za-z]{2,}", segment)
            if word.lower() not in SIGNAL_STOPWORDS and word.lower() not in GENERIC_LABEL_TOKENS
        ]
        explicit_acronyms = [
            token
            for token in re.findall(r"\b[A-Z]{2,6}\b", segment)
            if token.lower() not in {"dept", "usa"}
        ]
        return (len(set(words)) + (2 if explicit_acronyms else 0), len(words))

    ranked = sorted(
        ((specificity(segment), index, segment) for index, segment in enumerate(chain)),
        key=lambda item: (-item[0][0], -item[0][1], item[1]),
    )
    labels: list[str] = []
    for _, _, segment in ranked:
        short_tokens = [
            token
            for token in re.findall(r"\b[A-Z]{2,5}\b", segment)
            if token.lower() not in GENERIC_LABEL_TOKENS and token.lower() not in {"dept", "usa", "us", "and", "of", "the"}
        ]
        if len(short_tokens) == 1 and re.search(r"[-/()]", segment):
            labels.append(short_tokens[0])
        labels.append(segment)
    labels.extend(chain[:2])
    return _dedupe_strings(labels)[:6]


def _label_acronyms(labels: list[str], domains: list[str]) -> list[str]:
    acronyms: list[str] = []
    for label in labels:
        words = [
            word
            for word in re.findall(r"[A-Za-z]+", label)
            if word.lower() not in SIGNAL_STOPWORDS and word.lower() not in GENERIC_LABEL_TOKENS
        ]
        if len(words) >= 2:
            acronym = "".join(word[0] for word in words).lower()
            if 3 <= len(acronym) <= 5 and acronym not in {"fam", "state", "army", "defense"}:
                acronyms.append(acronym)
    for domain in domains:
        host = domain.lower().lstrip("www.")
        prefix = host.split(".", 1)[0]
        if 3 <= len(prefix) <= 5 and prefix not in {"home", "fam", "state", "army"}:
            acronyms.append(prefix)
    return _dedupe_strings(acronyms)


def infer_official_domains(buyer: str, url: str = "") -> list[str]:
    buyer_text = str(buyer or "").lower()
    domains: list[str] = []
    for needle, values in AGENCY_DOMAIN_HINTS.items():
        if needle in buyer_text:
            domains.extend(values)
    buyer_tokens = set(re.findall(r"[a-z]{2,}", buyer_text))
    if "inl" in buyer_tokens:
        domains.extend(["fam.state.gov", "state.gov"])
    if "erdc" in buyer_tokens:
        domains.extend(["erdc.usace.army.mil", "usace.army.mil"])
    if "usace" in buyer_tokens or ("corps" in buyer_tokens and "engineers" in buyer_tokens):
        domains.extend(["usace.army.mil", "erdc.usace.army.mil"])
    if not domains and url:
        host = _host(url)
        if host.endswith(".gov") or host.endswith(".mil"):
            parts = host.split(".")
            if len(parts) >= 2:
                domains.append(".".join(parts[-2:]))
            domains.append(host)
    prioritized = sorted(
        _dedupe_strings(domains),
        key=lambda domain: (
            0 if domain.startswith(("erdc.", "usace.", "fam.")) else 1,
            0 if domain.count(".") >= 2 else 1,
            domain,
        ),
    )
    return prioritized


def extract_policy_references(*texts: object) -> list[dict[str, Any]]:
    combined = " ".join(_normalize_text(text) for text in texts if text)
    refs: list[dict[str, Any]] = []
    for item in POLICY_REFERENCE_PATTERNS:
        match = item["pattern"].search(combined)
        if not match:
            continue
        refs.append(
            {
                "label": item["label"],
                "domains": list(item["domains"]),
                "match_text": match.group(0),
            }
        )
    return refs


def _coerce_iso_date(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return "N/A"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except Exception:  # pragma: no cover - defensive fallback
            return value[:10] if re.match(r"\d{4}-\d{2}-\d{2}", value) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.date().isoformat()


def _meta_pairs(html_text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for match in META_RE.findall(html_text):
        attrs = {name.lower(): html.unescape(value) for name, _, value in META_ATTR_RE.findall(match)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        value = attrs.get("content", "").strip()
        if key and value and key not in pairs:
            pairs[key] = value
    return pairs


def _strip_html_artifacts(html_text: str) -> str:
    return SCRIPT_STYLE_RE.sub(" ", COMMENT_RE.sub(" ", html_text))


def _is_homepage_url(url: str) -> bool:
    path = urlparse(url).path.strip().lower()
    return path in {"", "/"} or path == "/index.html"


def _is_primary_language_url(url: str) -> bool:
    first_segment = urlparse(url).path.strip("/").split("/", 1)[0].lower()
    return first_segment not in LANGUAGE_PATH_PREFIXES


def _looks_like_boilerplate(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if len(normalized) < 80:
        return True
    return any(marker in normalized for marker in BOILERPLATE_MARKERS)


def _extract_html_title(html_text: str) -> str:
    match = TITLE_RE.search(html_text)
    return _normalize_text(match.group(1)) if match else ""


def _extract_html_published_date(html_text: str) -> str:
    meta_pairs = _meta_pairs(html_text)
    for key in (
        "article:published_time",
        "article:modified_time",
        "date",
        "publishdate",
        "pubdate",
        "dc.date",
        "dc.date.issued",
        "last-modified",
    ):
        if meta_pairs.get(key):
            return _coerce_iso_date(meta_pairs[key])
    time_match = TIME_RE.search(html_text)
    if time_match:
        return _coerce_iso_date(time_match.group(2))
    json_match = JSON_DATE_RE.search(html_text)
    if json_match:
        return _coerce_iso_date(json_match.group(1))
    return "N/A"


def _extract_html_excerpt(html_text: str, max_chars: int) -> str:
    cleaned_html = _strip_html_artifacts(html_text)
    meta_pairs = _meta_pairs(cleaned_html)
    meta_candidates: list[str] = []
    for key in ("description", "og:description", "twitter:description"):
        if meta_pairs.get(key):
            meta_candidates.append(meta_pairs[key])
    if meta_candidates:
        primary_meta = _normalize_text(meta_candidates[0])
        if len(primary_meta) >= 80 and not _looks_like_boilerplate(primary_meta):
            return primary_meta[:max_chars]
    candidates: list[str] = list(meta_candidates[:1])
    for pattern in (PARAGRAPH_RE, LIST_ITEM_RE):
        for match in pattern.findall(cleaned_html):
            text = _normalize_text(match)
            if len(text) < 60 or _looks_like_boilerplate(text):
                continue
            candidates.append(text)
            if len(candidates) >= 12:
                break
        if len(candidates) >= 12:
            break
    if not candidates:
        fallback = _normalize_text(TAG_RE.sub(" ", cleaned_html))
        if fallback and not _looks_like_boilerplate(fallback):
            candidates.append(fallback)
    excerpt_parts: list[str] = []
    total_chars = 0
    for candidate in _dedupe_strings(candidates):
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        excerpt_parts.append(candidate[:remaining].strip())
        total_chars += len(excerpt_parts[-1]) + 1
    return " ".join(part for part in excerpt_parts if part).strip()[:max_chars]


def infer_oversight_domains(buyer: str) -> list[str]:
    buyer_text = str(buyer or "").lower()
    domains: list[str] = []
    for needle, values in AGENCY_OVERSIGHT_HINTS.items():
        if needle in buyer_text:
            domains.extend(values)
    if "oversight.gov" not in domains:
        domains.append("oversight.gov")
    return _dedupe_strings(domains)


def _hint_variants(value: str) -> list[str]:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return []
    variants = {
        normalized,
        normalized.replace(" ", "-"),
        normalized.replace(" ", ""),
        normalized.replace(" ", "/"),
    }
    return sorted(variants)


def _category_allowed_domains(
    category: str,
    agency_domains: list[str],
    buyer: str,
    policy_refs: list[dict[str, Any]],
) -> list[str]:
    if category == "oversight":
        return _dedupe_strings(infer_oversight_domains(buyer) + agency_domains)
    if category == "policy_compliance":
        policy_domains = [domain for ref in policy_refs for domain in ref.get("domains", [])]
        fallback_domains = POLICY_FALLBACK_DOMAINS if policy_refs else [domain for domain in POLICY_FALLBACK_DOMAINS if domain != "whitehouse.gov"]
        return _dedupe_strings(agency_domains + policy_domains + fallback_domains)
    return agency_domains


def _category_hints(
    category: str,
    labels: list[str],
    keywords: list[str],
    policy_refs: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    url_hints = list(CATEGORY_URL_HINTS.get(category, ()))
    text_hints = list(CATEGORY_TEXT_HINTS.get(category, ()))
    url_hints.extend(labels[:2])
    text_hints.extend(labels[:2])
    if category in {"mission_context", "budget_funding", "acquisition_forecast", "public_discourse"}:
        url_hints.extend(keywords[:4])
        text_hints.extend(keywords[:4])
    if category == "policy_compliance":
        for ref in policy_refs:
            label = str(ref.get("label", "") or "")
            match_text = str(ref.get("match_text", "") or "")
            url_hints.extend(_hint_variants(label))
            url_hints.extend(_hint_variants(match_text))
            publication_match = re.search(r"publication\s+(\d{3,5})", match_text, re.IGNORECASE)
            if publication_match:
                url_hints.append(f"p{publication_match.group(1)}")
            text_hints.append(label)
            text_hints.append(match_text)
    if category == "leadership":
        text_hints.extend(["official", "leadership", "commissioner", "chief"])
    if category == "oversight":
        text_hints.extend(["audit", "finding", "recommendation", "inspector general"])
    return _dedupe_strings(url_hints), _dedupe_strings(text_hints)


def _candidate_url_rank(url: str, allowed_domains: list[str], url_hints: list[str], keyword_tokens: list[str]) -> int:
    host = _host(url)
    score = 4 if any(_matches_domain(host, domain) for domain in allowed_domains) else 0
    path_text = f"{urlparse(url).path.lower()} {urlparse(url).query.lower()}"
    hint_hits = 0
    for hint in url_hints:
        for variant in _hint_variants(hint):
            if variant and variant in path_text:
                score += 2
                hint_hits += 1
                break
    path_tokens = set(URL_TOKEN_RE.findall(path_text))
    keyword_hits = len(path_tokens & set(keyword_tokens))
    score += min(4, keyword_hits)
    if hint_hits == 0 and keyword_hits == 0:
        return -2
    if url.lower().endswith(".pdf"):
        score += 1
    if _is_homepage_url(url):
        score -= 6
    if not _is_primary_language_url(url):
        score -= 3
    return score


def _category_marker_hit(category: str, combined: str, url: str, text_hints: list[str]) -> bool:
    marker_groups = {
        "mission_context": MISSION_CONTEXT_MARKERS,
        "budget_funding": BUDGET_FUNDING_MARKERS,
        "acquisition_forecast": FORECAST_MARKERS,
        "oversight": ("audit", "recommendation", "finding", "inspector general", "watchdog", "oversight"),
        "leadership": ("commissioner", "chief", "leadership", "officials", "organization", "biography", "remarks", "testimony"),
        "public_discourse": ("news", "press release", "remarks", "testimony", "speech", "announcement"),
    }
    marker_values = marker_groups.get(category, tuple(text_hints))
    compact_combined = combined.replace(" ", "")
    compact_url = url.lower().replace("-", "").replace("_", "")
    for marker in marker_values:
        normalized = _normalize_text(marker).lower()
        compact_marker = normalized.replace(" ", "")
        if normalized and (
            normalized in combined
            or compact_marker in compact_combined
            or normalized in url.lower()
            or compact_marker in compact_url
        ):
            return True
    return False


def _source_quality_score(
    category: str,
    url: str,
    title: str,
    excerpt: str,
    allowed_domains: list[str],
    url_hints: list[str],
    text_hints: list[str],
    label_tokens: list[str],
    keyword_tokens: list[str],
    policy_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    score = _candidate_url_rank(url, allowed_domains, url_hints, keyword_tokens)
    combined = _normalize_text(f"{title} {excerpt}").lower()
    if _looks_like_boilerplate(combined):
        score -= 6
    combined_tokens = set(_signal_tokens(combined))
    entity_overlap = len(combined_tokens & set(label_tokens))
    objective_overlap = len(combined_tokens & set(keyword_tokens))
    score += min(4, entity_overlap)
    score += min(5, objective_overlap)
    compact_combined = combined.replace(" ", "")
    marker_hit = _category_marker_hit(category, combined, url, text_hints)
    for hint in text_hints:
        normalized = _normalize_text(hint).lower()
        compact_hint = normalized.replace(" ", "")
        if normalized and (normalized in combined or compact_hint in compact_combined):
            score += 2
    requirement_sensitive_categories = {
        "mission_context",
        "budget_funding",
        "acquisition_forecast",
        "oversight",
        "leadership",
        "public_discourse",
    }
    requirement_keywords_present = bool(keyword_tokens)
    requirement_relevant = entity_overlap > 0 and (
        objective_overlap > 0 or (category == "leadership" and not requirement_keywords_present)
    )
    if category == "policy_compliance":
        policy_ref_hits = 0
        url_text = url.lower()
        for ref in policy_refs:
            for reference_text in (str(ref.get("label", "") or ""), str(ref.get("match_text", "") or "")):
                normalized = _normalize_text(reference_text).lower()
                compact_reference = normalized.replace(" ", "")
                if normalized and (
                    normalized in combined
                    or compact_reference in compact_combined
                    or normalized in url_text
                    or compact_reference in url_text.replace("-", "").replace("_", "")
                ):
                    policy_ref_hits += 1
                    break
        if policy_refs and policy_ref_hits == 0:
            return {
                "quality_score": -10,
                "entity_overlap": entity_overlap,
                "objective_overlap": objective_overlap,
                "marker_hit": marker_hit,
                "requirement_relevant": False,
            }
        else:
            score += min(6, policy_ref_hits * 3)
    if category == "acquisition_forecast":
        if not marker_hit:
            return {
                "quality_score": -10,
                "entity_overlap": entity_overlap,
                "objective_overlap": objective_overlap,
                "marker_hit": marker_hit,
                "requirement_relevant": False,
            }
    if category == "budget_funding":
        if not marker_hit:
            return {
                "quality_score": -10,
                "entity_overlap": entity_overlap,
                "objective_overlap": objective_overlap,
                "marker_hit": marker_hit,
                "requirement_relevant": False,
            }
    if category == "mission_context":
        if not marker_hit:
            score -= 8
    if category == "leadership":
        if not marker_hit:
            score -= 8
    if category != "policy_compliance" and entity_overlap == 0 and objective_overlap == 0:
        score -= 8
    if category in {"mission_context", "oversight", "public_discourse"} and (entity_overlap == 0 or objective_overlap == 0):
        return {
            "quality_score": -10,
            "entity_overlap": entity_overlap,
            "objective_overlap": objective_overlap,
            "marker_hit": marker_hit,
            "requirement_relevant": False,
        }
    if category in {"budget_funding", "acquisition_forecast"} and objective_overlap == 0:
        return {
            "quality_score": -10,
            "entity_overlap": entity_overlap,
            "objective_overlap": objective_overlap,
            "marker_hit": marker_hit,
            "requirement_relevant": False,
        }
    if category == "leadership" and entity_overlap == 0:
        return {
            "quality_score": -10,
            "entity_overlap": entity_overlap,
            "objective_overlap": objective_overlap,
            "marker_hit": marker_hit,
            "requirement_relevant": False,
        }
    if category == "leadership" and requirement_keywords_present and objective_overlap == 0:
        return {
            "quality_score": -10,
            "entity_overlap": entity_overlap,
            "objective_overlap": objective_overlap,
            "marker_hit": marker_hit,
            "requirement_relevant": False,
        }
    if category == "oversight" and entity_overlap == 0:
        return {
            "quality_score": -10,
            "entity_overlap": entity_overlap,
            "objective_overlap": objective_overlap,
            "marker_hit": marker_hit,
            "requirement_relevant": False,
        }
    if category in {"mission_context", "budget_funding", "acquisition_forecast", "leadership", "public_discourse"} and entity_overlap == 0:
        score -= 5
    if category not in requirement_sensitive_categories:
        requirement_relevant = requirement_relevant or (marker_hit and (entity_overlap > 0 or objective_overlap > 0))
    return {
        "quality_score": score,
        "entity_overlap": entity_overlap,
        "objective_overlap": objective_overlap,
        "marker_hit": marker_hit,
        "requirement_relevant": requirement_relevant,
    }


def _is_anchor_source(category: str, source: dict[str, Any]) -> bool:
    quality = int(source.get("quality_score", 0) or 0)
    if quality < 10:
        return False
    if not bool(source.get("requirement_relevant")):
        return False
    if not bool(source.get("marker_hit")):
        return False
    return True


def _sitemap_candidates_for_policy_refs(policy_refs: list[dict[str, Any]], agency_domains: list[str]) -> list[str]:
    urls: list[str] = []
    if any(_matches_domain(domain, "irs.gov") for domain in agency_domains):
        for ref in policy_refs:
            match_text = str(ref.get("match_text", "") or "")
            publication_match = re.search(r"publication\s+(\d{3,5})", match_text, re.IGNORECASE)
            if publication_match:
                number = publication_match.group(1)
                urls.append(f"https://www.irs.gov/pub/irs-pdf/p{number}.pdf")
                urls.append(f"https://www.irs.gov/pub/irs-access/p{number}_accessible.pdf")
    for ref in policy_refs:
        urls.extend(POLICY_DIRECT_URLS.get(str(ref.get("label", "") or ""), []))
    return _dedupe_strings(urls)


def _agency_category_direct_urls(category: str, allowed_domains: list[str]) -> list[str]:
    urls: list[str] = []
    for domain, categories in AGENCY_DIRECT_URLS.items():
        if not any(_matches_domain(candidate, domain) for candidate in allowed_domains):
            continue
        urls.extend(categories.get(category, []))
    return _dedupe_strings(urls)


def _parse_sitemap_locs(data: bytes) -> list[str]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    return [(loc.text or "").strip() for loc in root.findall(".//{*}loc") if (loc.text or "").strip()]


def _fetch_sitemap_urls(domain: str) -> list[str]:
    normalized_domain = domain.lower().lstrip("www.")
    if normalized_domain in SITEMAP_CACHE:
        return SITEMAP_CACHE[normalized_domain]

    candidate_docs = [f"https://{normalized_domain}/sitemap.xml"]
    try:
        robots_request = urllib.request.Request(
            f"https://{normalized_domain}/robots.txt",
            headers=DEFAULT_REQUEST_HEADERS,
        )
        with urllib.request.urlopen(robots_request, timeout=DEFAULT_TIMEOUT) as response:
            robots_text = response.read(200_000).decode("utf-8", errors="replace")
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                candidate_docs.append(urllib.parse.urljoin(f"https://{normalized_domain}/robots.txt", line.split(":", 1)[1].strip()))
    except Exception:
        pass

    urls: list[str] = []
    queued = _dedupe_strings(candidate_docs)
    seen_docs: set[str] = set()
    while queued and len(seen_docs) < SITEMAP_DOC_LIMIT and len(urls) < SITEMAP_URL_LIMIT:
        doc_url = queued.pop(0)
        if "://" not in doc_url:
            doc_url = urllib.parse.urljoin(f"https://{normalized_domain}/", doc_url)
        if doc_url in seen_docs:
            continue
        seen_docs.add(doc_url)
        request = urllib.request.Request(doc_url, headers=DEFAULT_REQUEST_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                data = response.read(DEFAULT_MAX_BYTES)
        except Exception:
            continue
        locs = _parse_sitemap_locs(data)
        if not locs:
            continue
        nested = [
            loc
            for loc in locs
            if (
                ("sitemap" in loc.lower() and loc.lower().endswith((".xml", ".xml.gz")))
                or "sitemap.xml?page=" in loc.lower()
            )
        ]
        page_urls = [loc for loc in locs if loc not in nested]
        if nested and not page_urls:
            queued.extend([loc for loc in nested if loc not in seen_docs])
            continue
        if nested and len(page_urls) < 20:
            queued.extend([loc for loc in nested if loc not in seen_docs])
        for loc in page_urls:
            if _matches_domain(_host(loc), normalized_domain):
                urls.append(loc)
        if not page_urls and nested:
            queued.extend([loc for loc in nested if loc not in seen_docs])

    deduped = _dedupe_strings(urls)
    SITEMAP_CACHE[normalized_domain] = deduped[:SITEMAP_URL_LIMIT]
    return SITEMAP_CACHE[normalized_domain]


def _query_list(*values: str) -> list[str]:
    return [value for value in values if value]


def _search_web(query: str, timeout: int = DEFAULT_TIMEOUT, limit: int = SEARCH_RESULT_LIMIT) -> dict[str, Any]:
    request = urllib.request.Request(
        SEARCH_URL.format(query=urllib.parse.quote_plus(query)),
        headers=DEFAULT_REQUEST_HEADERS,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            xml_body = response.read().decode("utf-8", errors="replace")
        root = ET.fromstring(xml_body)
    except urllib.error.HTTPError as exc:
        return {"status": "http_error", "query": query, "code": exc.code, "results": []}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"status": "error", "query": query, "detail": str(exc), "results": []}

    results: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:limit]:
        title = _normalize_text(item.findtext("title", default=""))
        link = _normalize_text(item.findtext("link", default=""))
        description = _normalize_text(item.findtext("description", default=""))
        pub_date = _normalize_text(item.findtext("pubDate", default=""))
        if not link:
            continue
        results.append(
            {
                "title": title or link,
                "url": link,
                "snippet": description,
                "published_date": pub_date or "N/A",
            }
        )
    return {"status": "ok", "query": query, "results": results}


def _header_published_date(headers: Any) -> str:
    raw_value = headers.get("Last-Modified", "") if headers else ""
    if not raw_value:
        return "N/A"
    try:
        value = parsedate_to_datetime(raw_value)
    except Exception:  # pragma: no cover - defensive fallback
        return raw_value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date().isoformat()


def _extract_pdf_text(data: bytes, max_pages: int = 6) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages[:max_pages]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def fetch_url_excerpt(url: str, timeout: int = DEFAULT_TIMEOUT, max_chars: int = 4000) -> dict[str, Any]:
    if not url:
        return {"status": "skipped", "reason": "no URL provided"}
    attempts = [
        DEFAULT_REQUEST_HEADERS,
        {**DEFAULT_REQUEST_HEADERS, "Referer": "https://www.google.com/"},
    ]
    last_http_error: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None
    for headers in attempts:
        request = urllib.request.Request(url, headers=headers)
        try:
            try:
                response_handle = urllib.request.urlopen(request, timeout=timeout)
            except Exception as exc:
                if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                    raise
                response_handle = urllib.request.urlopen(
                    request,
                    timeout=timeout,
                    context=ssl._create_unverified_context(),
                )
            with response_handle as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(DEFAULT_MAX_BYTES + 1)
                truncated = len(raw) > DEFAULT_MAX_BYTES
                if truncated:
                    raw = raw[:DEFAULT_MAX_BYTES]
                published_date = _header_published_date(response.headers)
            if url.lower().endswith(".pdf") or "pdf" in content_type.lower():
                text = _extract_pdf_text(raw)
                title = ""
                excerpt = _normalize_text(text)[:max_chars]
            else:
                text = raw.decode("utf-8", errors="replace")
                title = _extract_html_title(text)
                html_published_date = _extract_html_published_date(text)
                published_date = html_published_date if html_published_date != "N/A" else published_date
                excerpt = _extract_html_excerpt(text, max_chars=max_chars)
            excerpt = _normalize_text(excerpt)[:max_chars]
            return {
                "status": "ok",
                "url": url,
                "content_type": content_type,
                "published_date": published_date,
                "title": title,
                "text_excerpt": excerpt,
                "truncated": truncated,
            }
        except urllib.error.HTTPError as exc:
            last_http_error = {"status": "http_error", "url": url, "code": exc.code}
            if exc.code not in {401, 403, 406, 429}:
                return last_http_error
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = {"status": "error", "url": url, "detail": str(exc)}
    return last_http_error or last_error or {"status": "error", "url": url, "detail": "Unknown fetch failure"}


def _snippet_line(source: dict[str, Any], max_chars: int = 240) -> str:
    excerpt = _normalize_text(source.get("excerpt") or source.get("snippet") or "")
    excerpt = excerpt[:max_chars] if excerpt else "No excerpt captured."
    published = source.get("published_date", "N/A")
    return f"{source.get('title', 'Source')} ({published}): {excerpt}"


def _build_source_record(
    category: str,
    query: str,
    url: str,
    title: str,
    excerpt: str,
    snippet: str,
    published_date: str,
    confidence: int,
    quality_score: int,
    entity_overlap: int,
    objective_overlap: int,
    marker_hit: bool,
    requirement_relevant: bool,
) -> dict[str, Any]:
    host = _host(url)
    return {
        "category": category,
        "query": query,
        "title": title or url,
        "url": url,
        "publisher": host or "official source",
        "published_date": published_date or "N/A",
        "accessed_date": _today_local_str(),
        "tier": 1,
        "relevance": f"{category.replace('_', ' ')} source discovered for current capture research.",
        "confidence": confidence,
        "quality_score": quality_score,
        "entity_overlap": entity_overlap,
        "objective_overlap": objective_overlap,
        "marker_hit": marker_hit,
        "requirement_relevant": requirement_relevant,
        "snippet": _normalize_text(snippet),
        "excerpt": _normalize_text(excerpt),
    }


def _source_from_result(
    category: str,
    query: str,
    result: dict[str, Any],
    allowed_domains: list[str],
    url_hints: list[str],
    text_hints: list[str],
    label_tokens: list[str],
    keyword_tokens: list[str],
    policy_refs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    url = result.get("url", "")
    host = _host(url)
    if not any(_matches_domain(host, domain) for domain in allowed_domains):
        return None
    fetched = fetch_url_excerpt(url)
    if fetched.get("status") != "ok":
        excerpt = result.get("snippet", "")
        published_date = result.get("published_date", "N/A")
        confidence = 1
        title = result.get("title", url) or url
    else:
        excerpt = fetched.get("text_excerpt", "") or result.get("snippet", "")
        published_date = fetched.get("published_date", "N/A")
        if published_date == "N/A":
            published_date = result.get("published_date", "N/A")
        title = fetched.get("title", "") or result.get("title", url) or url
        confidence = 3
    quality_metrics = _source_quality_score(
        category,
        url,
        title,
        excerpt,
        allowed_domains,
        url_hints,
        text_hints,
        label_tokens,
        keyword_tokens,
        policy_refs,
    )
    if int(quality_metrics.get("quality_score", 0) or 0) < 8:
        return None
    return _build_source_record(
        category,
        query,
        url,
        title,
        excerpt,
        result.get("snippet", ""),
        published_date,
        confidence,
        int(quality_metrics.get("quality_score", 0) or 0),
        int(quality_metrics.get("entity_overlap", 0) or 0),
        int(quality_metrics.get("objective_overlap", 0) or 0),
        bool(quality_metrics.get("marker_hit")),
        bool(quality_metrics.get("requirement_relevant")),
    )


def _source_from_candidate_url(
    category: str,
    query: str,
    url: str,
    allowed_domains: list[str],
    url_hints: list[str],
    text_hints: list[str],
    label_tokens: list[str],
    keyword_tokens: list[str],
    policy_refs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not any(_matches_domain(_host(url), domain) for domain in allowed_domains):
        return None
    fetched = fetch_url_excerpt(url)
    if fetched.get("status") != "ok":
        return None
    title = fetched.get("title", "") or url
    excerpt = fetched.get("text_excerpt", "")
    quality_metrics = _source_quality_score(
        category,
        url,
        title,
        excerpt,
        allowed_domains,
        url_hints,
        text_hints,
        label_tokens,
        keyword_tokens,
        policy_refs,
    )
    threshold = 6 if query == "direct source seed" else 10
    if int(quality_metrics.get("quality_score", 0) or 0) < threshold:
        return None
    return _build_source_record(
        category,
        query,
        url,
        title,
        excerpt,
        excerpt[:240],
        fetched.get("published_date", "N/A"),
        3,
        int(quality_metrics.get("quality_score", 0) or 0),
        int(quality_metrics.get("entity_overlap", 0) or 0),
        int(quality_metrics.get("objective_overlap", 0) or 0),
        bool(quality_metrics.get("marker_hit")),
        bool(quality_metrics.get("requirement_relevant")),
    )


def _discover_sources_from_sitemaps(
    category: str,
    allowed_domains: list[str],
    url_hints: list[str],
    text_hints: list[str],
    label_tokens: list[str],
    keyword_tokens: list[str],
    policy_refs: list[dict[str, Any]],
    *,
    max_sources: int,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, str]] = []
    direct_urls = _agency_category_direct_urls(category, allowed_domains)
    if category == "policy_compliance":
        direct_urls.extend(_sitemap_candidates_for_policy_refs(policy_refs, allowed_domains))
    for domain in allowed_domains:
        for url in _fetch_sitemap_urls(domain):
            rank = _candidate_url_rank(url, allowed_domains, url_hints, keyword_tokens)
            if rank <= 0:
                continue
            candidates.append((rank, url))
    if direct_urls:
        for url in direct_urls:
            rank = _candidate_url_rank(url, allowed_domains, url_hints, keyword_tokens) + 8
            candidates.append((rank, url))

    ordered_urls = []
    seen_urls: set[str] = set()
    for url in direct_urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ordered_urls.append(url)
    for _, url in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ordered_urls.append(url)
        if len(ordered_urls) >= 18:
            break

    sources: list[dict[str, Any]] = []
    direct_url_set = set(direct_urls)
    for url in ordered_urls:
        source = _source_from_candidate_url(
            category,
            "direct source seed" if url in direct_url_set else "sitemap discovery",
            url,
            allowed_domains,
            url_hints,
            text_hints,
            label_tokens,
            keyword_tokens,
            policy_refs,
        )
        if not source:
            continue
        sources.append(source)
        if len(sources) >= max_sources:
            break
    return sources


def _discover_sources(
    category: str,
    queries: list[str],
    allowed_domains: list[str],
    labels: list[str],
    keywords: list[str],
    policy_refs: list[dict[str, Any]],
    *,
    max_sources: int = 2,
) -> tuple[list[dict[str, Any]], list[str]]:
    sources: list[dict[str, Any]] = []
    gaps: list[str] = []
    label_tokens = [
        token
        for token in _dedupe_strings(_signal_tokens(*labels) + _label_acronyms(labels, allowed_domains))
        if token not in GENERIC_ENTITY_TOKENS
    ]
    keyword_tokens = _dedupe_strings(_signal_tokens(*keywords))
    url_hints, text_hints = _category_hints(category, labels, keywords, policy_refs)
    seen_urls: set[str] = set()
    sitemap_sources = _discover_sources_from_sitemaps(
        category,
        allowed_domains,
        url_hints,
        text_hints,
        label_tokens,
        keyword_tokens,
        policy_refs,
        max_sources=max_sources,
    )
    for source in sitemap_sources:
        if source["url"] in seen_urls:
            continue
        seen_urls.add(source["url"])
        sources.append(source)
    if len(sources) >= max_sources:
        return sources, gaps

    for query in queries:
        search = _search_web(query)
        if search.get("status") != "ok":
            gaps.append(f"{category.replace('_', ' ')} search failed for query: {query}")
            continue
        found_any = False
        for result in search.get("results", []):
            source = _source_from_result(
                category,
                query,
                result,
                allowed_domains,
                url_hints,
                text_hints,
                label_tokens,
                keyword_tokens,
                policy_refs,
            )
            if not source:
                continue
            if source["url"] in seen_urls:
                continue
            seen_urls.add(source["url"])
            sources.append(source)
            found_any = True
            if len(sources) >= max_sources:
                return sources, gaps
        if found_any:
            continue
    if not sources:
        gaps.append(f"No official {category.replace('_', ' ')} sources were discovered in this run.")
    return sources, gaps


def _role_queries(
    labels: list[str],
    domains: list[str],
    contacts: list[dict[str, str]],
    requirement_clause: str = "",
) -> list[str]:
    queries: list[str] = []
    primary_label = labels[0] if labels else ""
    search_domain = domains[0] if domains else ""
    requirement_suffix = f" {requirement_clause}" if requirement_clause else ""
    for contact in contacts[:2]:
        name = contact.get("name", "").strip()
        if name and search_domain:
            queries.append(f'site:{search_domain} "{name}"{requirement_suffix}')
    for role in LEADERSHIP_ROLE_QUERIES:
        if search_domain and primary_label:
            queries.append(f'site:{search_domain} "{role}" "{primary_label}"{requirement_suffix}')
    return _dedupe_strings(queries)


def fetch_public_research(
    entry: dict[str, Any],
    notice_text: str = "",
    stakeholder_contacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    buyer = str(entry.get("buyer", "") or "")
    title = str(entry.get("title", "") or "")
    labels = _agency_labels(buyer)
    domains = infer_official_domains(buyer, str(entry.get("url", "") or ""))
    keywords = _top_keywords(title, _clean_notice_seed(notice_text))
    requirement_clause = _keyword_query_clause(keywords)
    contacts = stakeholder_contacts or []
    query_labels = _dedupe_strings(_label_acronyms(labels, domains) + labels)
    primary_label = query_labels[0] if query_labels else buyer or title
    secondary_label = query_labels[1] if len(query_labels) > 1 else primary_label
    search_domain = domains[0] if domains else ""
    secondary_domain = domains[1] if len(domains) > 1 else search_domain
    policy_refs = extract_policy_references(title, notice_text)

    mission_queries = _query_list(
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("strategic plan" OR "digital strategy" OR "IT strategic plan" OR "IT modernization" OR "AI strategy" OR "data strategy" OR "zero trust") filetype:pdf'
        if search_domain
        else "",
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("strategic plan" OR modernization OR "digital strategy" OR "technology roadmap")'
        if search_domain
        else "",
        f'site:{secondary_domain} "{secondary_label}" {requirement_clause} ("strategic plan" OR roadmap OR "IT modernization" OR "digital strategy") filetype:pdf'
        if secondary_domain and secondary_domain != search_domain
        else "",
        f'site:.gov "{primary_label}" {requirement_clause} ("strategic plan" OR "IT modernization" OR "digital strategy") filetype:pdf',
    )
    budget_queries = _query_list(
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("budget in brief" OR "congressional budget justification" OR "budget justification") filetype:pdf'
        if search_domain
        else "",
        f'site:{secondary_domain} "{secondary_label}" {requirement_clause} ("budget in brief" OR "congressional budget justification") filetype:pdf'
        if secondary_domain and secondary_domain != search_domain
        else "",
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("performance budget" OR "budget request" OR "plans performance budget")'
        if search_domain
        else "",
        f'site:.gov "{primary_label}" {requirement_clause} ("budget in brief" OR "congressional budget justification") filetype:pdf',
    )
    forecast_queries = _query_list(
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("acquisition forecast" OR "procurement forecast" OR "forecasted business opportunities" OR "industry day")'
        if search_domain
        else "",
        f'site:{secondary_domain} "{secondary_label}" {requirement_clause} ("acquisition forecast" OR "procurement forecast" OR "forecasted business opportunities" OR "industry day")'
        if secondary_domain and secondary_domain != search_domain
        else "",
        f'site:.gov "{primary_label}" {requirement_clause} ("acquisition forecast" OR "procurement forecast" OR "forecasted business opportunities" OR "industry day")',
    )
    oversight_requirement_clause = requirement_clause or '"information technology"'
    oversight_queries = _query_list(
        f'site:gao.gov "{primary_label}" {requirement_clause}',
        f'site:oversight.gov "{primary_label}" {requirement_clause}',
        f'site:gao.gov "{primary_label}" {oversight_requirement_clause}',
    )
    leadership_queries = _role_queries(labels, domains, contacts, requirement_clause=requirement_clause)
    public_discourse_queries = _query_list(
        f'site:{search_domain} "{primary_label}" {requirement_clause} ("press release" OR news OR blog OR testimony)'
        if search_domain
        else "",
        f'site:.gov "{primary_label}" {requirement_clause} ("press release" OR testimony OR hearing)',
    )

    policy_queries: list[str] = []
    for ref in policy_refs[:4]:
        for domain in ref.get("domains", []):
            policy_queries.append(f'site:{domain} "{ref["label"]}" filetype:pdf')
    if not policy_queries:
        for domain in _category_allowed_domains("policy_compliance", domains, buyer, policy_refs):
            for term in ("privacy", "security", "zero trust", "section 508", "fedramp"):
                policy_queries.append(f'site:{domain} "{primary_label}" "{term}" filetype:pdf')
    policy_queries = _dedupe_strings(policy_queries)

    mission_sources, mission_gaps = _discover_sources(
        "mission_context",
        mission_queries,
        _category_allowed_domains("mission_context", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=2,
    )
    budget_sources, budget_gaps = _discover_sources(
        "budget_funding",
        budget_queries,
        _category_allowed_domains("budget_funding", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=2,
    )
    forecast_sources, forecast_gaps = _discover_sources(
        "acquisition_forecast",
        forecast_queries,
        _category_allowed_domains("acquisition_forecast", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=1,
    )
    oversight_sources, oversight_gaps = _discover_sources(
        "oversight",
        oversight_queries,
        _category_allowed_domains("oversight", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=2,
    )
    leadership_sources, leadership_gaps = _discover_sources(
        "leadership",
        leadership_queries,
        _category_allowed_domains("leadership", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=2,
    )
    policy_sources, policy_gaps = _discover_sources(
        "policy_compliance",
        policy_queries,
        _category_allowed_domains("policy_compliance", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=3,
    )
    public_discourse_sources, discourse_gaps = _discover_sources(
        "public_discourse",
        public_discourse_queries,
        _category_allowed_domains("public_discourse", domains, buyer, policy_refs),
        labels,
        keywords,
        policy_refs,
        max_sources=2,
    )

    source_log = (
        mission_sources
        + budget_sources
        + forecast_sources
        + oversight_sources
        + leadership_sources
        + policy_sources
        + public_discourse_sources
    )
    qualified_category_count = sum(
        1
        for values in (
            mission_sources,
            budget_sources,
            forecast_sources,
            oversight_sources,
            leadership_sources,
            policy_sources,
            public_discourse_sources,
        )
        if values
    )
    category_anchor_counts = {
        "mission_context": sum(1 for source in mission_sources if _is_anchor_source("mission_context", source)),
        "budget_funding": sum(1 for source in budget_sources if _is_anchor_source("budget_funding", source)),
        "acquisition_forecast": sum(1 for source in forecast_sources if _is_anchor_source("acquisition_forecast", source)),
    }
    core_context_anchor_count = sum(1 for value in category_anchor_counts.values() if value > 0)
    funding_or_buying_anchor_count = sum(
        1 for key, value in category_anchor_counts.items() if key in {"budget_funding", "acquisition_forecast"} and value > 0
    )
    quality_score = sum(int(item.get("quality_score", 0) or 0) for item in source_log)

    return {
        "status": "ok" if source_log else "no_results",
        "domain_hints": domains,
        "policy_references": policy_refs,
        "qualified_category_count": qualified_category_count,
        "category_anchor_counts": category_anchor_counts,
        "core_context_anchor_count": core_context_anchor_count,
        "funding_or_buying_anchor_count": funding_or_buying_anchor_count,
        "quality_score": quality_score,
        "mission_context_signals": [_snippet_line(source) for source in mission_sources],
        "budget_document_signals": [_snippet_line(source) for source in budget_sources],
        "acquisition_forecast_signals": [_snippet_line(source) for source in forecast_sources],
        "oversight_signals": [_snippet_line(source) for source in oversight_sources],
        "policy_compliance_signals": [_snippet_line(source) for source in policy_sources],
        "leadership_priority_signals": [_snippet_line(source) for source in leadership_sources],
        "public_discourse_signals": [_snippet_line(source) for source in public_discourse_sources],
        "source_log": source_log,
        "evidence_gaps": _dedupe_strings(
            mission_gaps
            + budget_gaps
            + forecast_gaps
            + oversight_gaps
            + leadership_gaps
            + policy_gaps
            + discourse_gaps
        ),
    }
