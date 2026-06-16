from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import (  # type: ignore
    bundle_root_from_script,
    load_json,
    procurement_dir,
    read_text,
    utc_now_iso,
    write_json,
    write_text,
)
from common.profile_terms import is_low_signal_profile_term, normalize_profile_term  # type: ignore
from common.source_registry import refresh_runtime_registry  # type: ignore
from intel.providers.govtribe_mcp import GovTribeMCPCommercialIntelProvider, SOURCE_ID as GOVTRIBE_SOURCE_ID  # type: ignore


USER_AGENT = "pwin-ai-opportunities-bootstrap/1.0"
MAX_FETCH_BYTES = 750_000
MAX_RELEVANT_LINKS = 4
RELEVANT_LINK_HINTS = (
    "about",
    "solution",
    "service",
    "capabilit",
    "industry",
    "partner",
    "contract",
    "vehicle",
    "case",
    "experience",
    "customer",
    "team",
)
CAPABILITY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("data analytics", ("data analytics", "analytics", "business intelligence", "reporting")),
    ("artificial intelligence", ("artificial intelligence", "machine learning", "generative ai", "ai solutions")),
    ("cloud modernization", ("cloud", "aws", "azure", "cloud modernization", "cloud migration")),
    ("cybersecurity", ("cybersecurity", "cyber security", "zero trust", "security operations")),
    ("software development", ("software development", "application development", "custom software", "product engineering")),
    ("systems integration", ("systems integration", "integration", "enterprise architecture", "solution architecture")),
    ("program management", ("program management", "pmo", "portfolio management")),
    ("digital transformation", ("digital transformation", "modernization", "process improvement")),
    ("health IT", ("health it", "healthcare technology", "clinical systems", "public health")),
    ("training and change management", ("training", "change management", "adoption", "workforce enablement")),
]
NAICS_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("541511", "Custom Computer Programming Services", ("software development", "application development", "custom software", "agile delivery")),
    ("541512", "Computer Systems Design Services", ("systems integration", "solution architecture", "enterprise architecture", "systems design")),
    ("541519", "Other Computer Related Services", ("cybersecurity", "cloud modernization", "devsecops", "managed services")),
    ("541611", "Administrative Management and General Management Consulting Services", ("program management", "operating model", "management consulting", "process improvement")),
    ("541690", "Other Scientific and Technical Consulting Services", ("technical consulting", "advisory services", "subject matter expertise")),
    ("541715", "Research and Development in the Physical, Engineering, and Life Sciences", ("research and development", "r&d", "prototype", "innovation")),
    ("541330", "Engineering Services", ("engineering", "systems engineering", "design engineering")),
    ("611430", "Professional and Management Development Training", ("training and change management", "workforce enablement", "instructional design")),
]
BUYER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Department of Health and Human Services", ("health", "public health", "medicaid", "medicare", "clinical")),
    ("Department of Veterans Affairs", ("veteran", "veterans", "va", "benefits", "vba", "vha")),
    ("Department of Defense", ("defense", "warfighter", "mission systems", "army", "navy", "air force")),
    ("Department of Homeland Security", ("border", "homeland security", "emergency management", "cisa", "fema")),
    ("General Services Administration", ("shared services", "federal modernization", "acquisition", "gsa")),
]
GENERIC_NAME_SEGMENTS = {"home", "welcome", "homepage"}
GOVTRIBE_BOOTSTRAP_PROVENANCE = "govtribe_subscription_derived"
GOVTRIBE_BOOLEAN_TEXT_VALUES = {"true", "false", "yes", "no"}
GOVTRIBE_GENERIC_METADATA_VALUES = {
    "business or organization",
    "for profit organization",
    "limited liability company",
    "partnership or limited liability partnership",
}
NAICS_LABEL_BY_CODE = {
    "519290": "Web Search Portals and All Other Information Services",
    "541512": "Computer Systems Design Services",
}
NAICS_CODE_BY_LABEL = {normalize_profile_term(label): code for code, label in NAICS_LABEL_BY_CODE.items()}


@dataclass
class PageSignals:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)


class _SignalsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignore_depth = 0
        self._active: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        if lowered in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if lowered == "meta":
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                content = _clean_text(attr_map.get("content", ""))
                if content and not self.description:
                    self.description = content
            return
        if lowered in {"title", "h1", "h2", "h3", "p", "li", "a"}:
            self._active.append({"tag": lowered, "href": attr_map.get("href", ""), "chunks": []})

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth:
            return
        for index in range(len(self._active) - 1, -1, -1):
            item = self._active[index]
            if item["tag"] != lowered:
                continue
            self._active.pop(index)
            text = _clean_text(" ".join(item["chunks"]))
            if not text:
                return
            if lowered == "title" and not self.title:
                self.title = text
            elif lowered in {"h1", "h2", "h3"}:
                _append_unique(self.headings, text)
            elif lowered in {"p", "li"} and len(text) >= 40:
                _append_unique(self.paragraphs, text)
            elif lowered == "a" and item.get("href"):
                self.links.append((item["href"], text))
            return

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        text = _clean_text(data)
        if not text:
            return
        for item in self._active:
            item["chunks"].append(text)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_bootstrap_signal(value: Any) -> str:
    return _clean_text(str(value or ""))


def _is_govtribe_generic_signal(value: Any) -> bool:
    normalized = normalize_profile_term(str(value or ""))
    return normalized in GOVTRIBE_BOOLEAN_TEXT_VALUES or normalized in GOVTRIBE_GENERIC_METADATA_VALUES


def _clean_govtribe_values(values: list[Any], *, allow_generic_metadata: bool = False) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _clean_bootstrap_signal(value)
        if not text:
            continue
        if normalize_profile_term(text) in GOVTRIBE_BOOLEAN_TEXT_VALUES:
            continue
        if not allow_generic_metadata and normalize_profile_term(text) in GOVTRIBE_GENERIC_METADATA_VALUES:
            continue
        cleaned.append(text)
    return _merge_unique([], cleaned)


def _normalize_url(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("company_url is required")
    if value.startswith(("http://", "https://", "file://")):
        return value
    return f"https://{value}"


def _is_govtribe_vendor_url(raw_value: str) -> bool:
    return bool(re.search(r"https?://(?:www\.)?govtribe\.com/vendors/[^/\s]+", str(raw_value or ""), re.I))


def _parse_html(url: str, html: str) -> PageSignals:
    parser = _SignalsParser()
    parser.feed(html)
    return PageSignals(
        url=url,
        title=parser.title,
        description=parser.description,
        headings=parser.headings,
        paragraphs=parser.paragraphs,
        links=parser.links,
    )


def _fetch_html(url: str) -> tuple[str | None, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read(MAX_FETCH_BYTES).decode("utf-8", errors="ignore")
    except Exception as exc:
        return None, f"Could not fetch {url}: {exc}"
    if not _clean_text(html):
        return None, f"Fetched {url} but received empty content"
    return html, None


def _absolutize_link(base_url: str, href: str) -> str | None:
    raw = href.strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urllib.parse.urljoin(base_url, raw)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {"http", "https", "file"}:
        return None
    cleaned = parsed._replace(fragment="").geturl()
    return cleaned


def _same_site(url_a: str, url_b: str) -> bool:
    parsed_a = urllib.parse.urlparse(url_a)
    parsed_b = urllib.parse.urlparse(url_b)
    if parsed_a.scheme == "file" and parsed_b.scheme == "file":
        return True
    return parsed_a.netloc.lower() == parsed_b.netloc.lower()


def _link_score(url: str, text: str) -> int:
    haystack = f"{url.lower()} {text.lower()}"
    score = 0
    for hint in RELEVANT_LINK_HINTS:
        if hint in haystack:
            score += 1
    return score


def _fetch_site_signals(root_url: str) -> tuple[list[PageSignals], list[str]]:
    root_html, root_error = _fetch_html(root_url)
    if root_error or root_html is None:
        return [], [root_error or "Unable to fetch company site"]

    pages = [_parse_html(root_url, root_html)]
    notes: list[str] = []
    candidates: list[tuple[int, str]] = []
    seen = {root_url}

    for href, text in pages[0].links:
        absolute = _absolutize_link(root_url, href)
        if not absolute or absolute in seen or not _same_site(root_url, absolute):
            continue
        score = _link_score(absolute, text)
        if score <= 0:
            continue
        seen.add(absolute)
        candidates.append((score, absolute))

    for _, url in sorted(candidates, key=lambda item: (-item[0], item[1]))[:MAX_RELEVANT_LINKS]:
        html, error = _fetch_html(url)
        if error or html is None:
            notes.append(error or f"Could not fetch {url}")
            continue
        pages.append(_parse_html(url, html))

    return pages, notes


def _domain_label(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path))
        if path.stem and path.stem.lower() not in {"index", "home"}:
            return path.stem.replace("-", " ").replace("_", " ").title()
        if path.parent.name:
            return path.parent.name.replace("-", " ").replace("_", " ").title()
        return "Company"
    netloc = parsed.netloc.split("@")[-1].split(":")[0]
    label = netloc.split(".")[0] if netloc else "company"
    return label.replace("-", " ").replace("_", " ").title()


def _infer_company_name(company_url: str, pages: list[PageSignals], explicit_name: str) -> str:
    if explicit_name.strip():
        return explicit_name.strip()
    title = pages[0].title if pages else ""
    if title:
        segments = [segment.strip() for segment in re.split(r"\s+[|\-:]\s+|[|:]", title) if segment.strip()]
        for segment in segments:
            lowered = segment.lower()
            if lowered in GENERIC_NAME_SEGMENTS:
                continue
            if len(segment.split()) <= 8:
                return segment
    return _domain_label(company_url)


def _best_summary(pages: list[PageSignals], explicit_summary: str) -> str:
    if explicit_summary.strip():
        return explicit_summary.strip()
    for page in pages:
        if 60 <= len(page.description) <= 320:
            return page.description
    for page in pages:
        for paragraph in page.paragraphs:
            if 70 <= len(paragraph) <= 360:
                return paragraph
    if pages and pages[0].title:
        return pages[0].title
    return "Company profile seeded from the provided website. Review and confirm the inferred fit before scanning."


def _site_corpus(pages: list[PageSignals]) -> str:
    parts: list[str] = []
    for page in pages:
        parts.extend([page.title, page.description])
        parts.extend(page.headings[:8])
        parts.extend(page.paragraphs[:10])
    return _clean_text(" ".join(part for part in parts if part))


def _infer_capabilities(pages: list[PageSignals], summary: str) -> list[str]:
    corpus = _site_corpus(pages).lower()
    capabilities: list[str] = []
    for label, patterns in CAPABILITY_RULES:
        if any(pattern in corpus for pattern in patterns):
            capabilities.append(label)
    if len(capabilities) >= 4:
        return capabilities[:6]

    summary_key = normalize_profile_term(summary)
    for page in pages:
        for heading in page.headings:
            cleaned = _clean_text(heading)
            lowered = cleaned.lower()
            if not cleaned or is_low_signal_profile_term(cleaned):
                continue
            if len(cleaned.split()) > 6 or normalize_profile_term(cleaned) == summary_key:
                continue
            _append_unique(capabilities, lowered)
            if len(capabilities) >= 6:
                return capabilities
    return capabilities[:6]


def _infer_candidate_buyers(pages: list[PageSignals], summary: str) -> list[str]:
    corpus = f"{summary} {_site_corpus(pages)}".lower()
    buyers: list[str] = []
    for buyer, patterns in BUYER_RULES:
        if any(pattern in corpus for pattern in patterns):
            buyers.append(buyer)
    return buyers[:4]


def _infer_naics(summary: str, capabilities: list[str], user_naics: list[str]) -> list[dict[str, str]]:
    corpus = _clean_text(" ".join([summary, *capabilities])).lower()
    inferred: list[dict[str, str]] = []
    for code, label, patterns in NAICS_RULES:
        if code in user_naics:
            continue
        if any(pattern in corpus for pattern in patterns):
            inferred.append({"code": code, "label": label})
    return inferred[:4]


def _build_fit_narrative(capabilities: list[str], buyers: list[str]) -> str:
    phrases = capabilities[:3] or ["the company's confirmed core competencies"]
    buyer_note = f" for buyers such as {', '.join(buyers[:2])}" if buyers else ""
    return f"Prioritize opportunities involving {', '.join(phrases)}{buyer_note}. Avoid grants until the user explicitly opts in."


def _parse_naics(raw_value: str) -> list[str]:
    values: list[str] = []
    for part in re.split(r"[,;\s]+", raw_value.strip()):
        cleaned = part.strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _merge_unique(existing: list[Any], additions: list[Any]) -> list[Any]:
    result = list(existing)
    seen = {json.dumps(item, sort_keys=True) for item in existing}
    for item in additions:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _source_config(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources", []):
        if source.get("id") == source_id:
            return source if isinstance(source, dict) else {}
    return {"id": source_id}


def _enable_govtribe_source(registry_path: Path, registry: dict[str, Any], now: str) -> None:
    changed = False
    for source in registry.get("sources", []):
        if not isinstance(source, dict) or source.get("id") != GOVTRIBE_SOURCE_ID:
            continue
        source["enabled"] = True
        notes = source.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)] if str(notes or "").strip() else []
        source["notes"] = _merge_unique(
            notes,
            [f"Enabled by GovTribe vendor bootstrap on {now[:10]}."],
        )
        changed = True
    if changed:
        write_json(registry_path, registry)


def _six_digit_codes(values: list[str]) -> list[str]:
    codes: list[str] = []
    for value in values:
        for match in re.findall(r"\b\d{6}\b", str(value or "")):
            if match not in codes:
                codes.append(match)
    return codes


def _naics_items(values: list[Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            code = _clean_text(str(value.get("code") or ""))
            label = _clean_text(str(value.get("label") or value.get("name") or "")) or NAICS_LABEL_BY_CODE.get(code, "")
            if code or label:
                item = {"code": code, "label": label}
                if item not in items:
                    items.append(item)
            continue
        text = str(value or "").strip()
        if not text:
            continue
        match = re.search(r"\b\d{6}\b", text)
        code = match.group(0) if match else NAICS_CODE_BY_LABEL.get(normalize_profile_term(text), "")
        label = text if match and text != code else NAICS_LABEL_BY_CODE.get(code, "")
        if not code and not label:
            label = text
        item = {"code": code, "label": label}
        if item not in items:
            items.append(item)
    return items


def _govtribe_naics_items(vendor_record: dict[str, Any], candidate_codes: list[str]) -> list[dict[str, str]]:
    items = _naics_items([*vendor_record.get("naics_items", []), *vendor_record.get("naics", [])])
    known_codes = {item["code"] for item in items if item.get("code")}
    for code in candidate_codes:
        clean_code = _clean_text(str(code or ""))
        if not clean_code or clean_code in known_codes:
            continue
        item = {"code": clean_code, "label": NAICS_LABEL_BY_CODE.get(clean_code, "")}
        items.append(item)
        known_codes.add(clean_code)
    return items


def _govtribe_provenance(field: str, value: Any, vendor_record: dict[str, Any], now: str) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "source": GOVTRIBE_SOURCE_ID,
        "source_url": vendor_record.get("source_url", ""),
        "external_record_id": vendor_record.get("external_record_id", ""),
        "provenance": GOVTRIBE_BOOTSTRAP_PROVENANCE,
        "captured_at": now,
    }


def _append_govtribe_provenance(
    facts: list[Any],
    *,
    field: str,
    value: Any,
    vendor_record: dict[str, Any],
    now: str,
) -> list[Any]:
    if value in (None, "", [], {}):
        return facts
    return _merge_unique(facts, [_govtribe_provenance(field, value, vendor_record, now)])


def _govtribe_capabilities(vendor_record: dict[str, Any]) -> list[str]:
    corpus = _clean_text(
        " ".join(
            [
                str(vendor_record.get("summary") or ""),
                " ".join(str(item or "") for item in vendor_record.get("award_signals", [])),
                " ".join(str(item or "") for item in vendor_record.get("keywords", [])),
            ]
        )
    ).lower()
    capabilities: list[str] = []
    for label, patterns in CAPABILITY_RULES:
        if any(pattern in corpus for pattern in patterns):
            capabilities.append(label)
    if capabilities:
        return capabilities[:6]
    fallback_terms = [
        item
        for item in vendor_record.get("keywords", [])
        if not re.fullmatch(r"\d{6}", str(item or "").strip())
        and not _is_govtribe_generic_signal(item)
        and not is_low_signal_profile_term(str(item))
    ]
    return _clean_govtribe_values(fallback_terms)[:6]


def _govtribe_fit_narrative(vendor_record: dict[str, Any]) -> str:
    capabilities = _govtribe_capabilities(vendor_record)[:3]
    buyers = _clean_govtribe_values(vendor_record.get("buyers", []))[:2]
    vehicles = _clean_govtribe_values(vendor_record.get("contract_vehicles", []))[:2]
    parts = capabilities or ["GovTribe-reported NAICS, certifications, and award signals"]
    buyer_note = f" for buyers such as {', '.join(buyers)}" if buyers else ""
    vehicle_note = f" through vehicles such as {', '.join(vehicles)}" if vehicles else ""
    return f"Prioritize opportunities involving {', '.join(parts)}{buyer_note}{vehicle_note}. Avoid grants until the user explicitly opts in."


def _naics_label(item: dict[str, str]) -> str:
    code = item.get("code", "").strip()
    label = item.get("label", "").strip()
    if code and label:
        return f"{code} - {label}"
    return code or label or "Needs confirmation"


def _render_starter_profile(
    template_text: str,
    *,
    company_url: str,
    user_naics: list[str],
    summary: str,
    company_summary: str,
    capabilities: list[str],
    buyers: list[str],
    candidate_naics: list[dict[str, str]],
) -> str:
    replacements = {
        "{{DATE}}": utc_now_iso()[:10],
        "{{COMPANY_URL}}": company_url,
        "{{USER_NAICS}}": ", ".join(user_naics) if user_naics else "None provided",
        "{{SUMMARY}}": summary or "Not provided",
        "{{COMPANY_SUMMARY}}": company_summary or "Needs confirmation",
        "{{COMPETENCY_1}}": capabilities[0] if len(capabilities) > 0 else "Needs confirmation",
        "{{COMPETENCY_2}}": capabilities[1] if len(capabilities) > 1 else "Needs confirmation",
        "{{BUYER_1}}": buyers[0] if len(buyers) > 0 else "Needs confirmation",
        "{{BUYER_2}}": buyers[1] if len(buyers) > 1 else "Needs confirmation",
        "{{NAICS_1}}": _naics_label(candidate_naics[0]) if len(candidate_naics) > 0 else "Needs confirmation",
        "{{NAICS_2}}": _naics_label(candidate_naics[1]) if len(candidate_naics) > 1 else "Needs confirmation",
        "{{EXCLUSION_1}}": "Grants are excluded by default until the user opts in.",
        "{{EXCLUSION_2}}": "Website-derived facts remain provisional until the user confirms them.",
        "{{QUESTION_1}}": "Which 2 to 3 capabilities above are truly core to the company?",
        "{{QUESTION_2}}": "Which agencies, buyers, or work types should never show up?",
        "{{QUESTION_3}}": "Are these candidate NAICS codes correct, or should any be confirmed or rejected?",
    }
    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def seed_workspace(
    *,
    bundle_root: Path,
    workspace: Path,
    company_url: str,
    user_naics: list[str],
    naics_status: str,
    explicit_name: str,
    explicit_summary: str,
) -> dict[str, Any]:
    normalized_url = _normalize_url(company_url)
    now = utc_now_iso()
    procurement = procurement_dir(workspace)
    pages, fetch_notes = _fetch_site_signals(normalized_url)
    company_name = _infer_company_name(normalized_url, pages, explicit_name)
    company_summary = _best_summary(pages, explicit_summary)
    capabilities = _infer_capabilities(pages, company_summary)
    buyers = _infer_candidate_buyers(pages, company_summary)
    inferred_naics = _infer_naics(company_summary, capabilities, user_naics)

    vendor_profile_path = procurement / "vendor-profile.json"
    vendor_profile = load_json(bundle_root / "templates" / "vendor-profile.template.json", default={}) or {}
    existing_vendor = load_json(vendor_profile_path, default={}) or {}
    if isinstance(existing_vendor, dict):
        vendor_profile.update(existing_vendor)
    vendor_profile["last_updated"] = now
    vendor_profile.setdefault("bootstrap", {})
    vendor_profile["bootstrap"]["method"] = "company_url_bootstrap_script_v1"
    vendor_profile["bootstrap"]["inputs"] = {
        "company_url": normalized_url,
        "user_supplied_naics": user_naics,
        "plain_language_summary": explicit_summary.strip(),
        "other_inputs": [],
    }
    vendor_profile["bootstrap"]["bootstrapped_on"] = now
    vendor_profile["bootstrap"]["status"] = "needs_user_confirmation"
    vendor_profile.setdefault("company", {})
    if explicit_name.strip() or not _clean_text(str(vendor_profile["company"].get("name", ""))):
        vendor_profile["company"]["name"] = company_name
    vendor_profile["company"]["website"] = normalized_url
    if explicit_summary.strip() or not _clean_text(str(vendor_profile["company"].get("summary", ""))):
        vendor_profile["company"]["summary"] = company_summary
    vendor_profile["core_competencies"] = _merge_unique(vendor_profile.get("core_competencies", []), capabilities)
    if not _clean_text(str(vendor_profile.get("fit_narrative", ""))):
        vendor_profile["fit_narrative"] = _build_fit_narrative(capabilities, buyers)
    vendor_profile.setdefault("naics", {})
    confirmed_values = user_naics if naics_status == "confirmed" else []
    candidate_values = user_naics if naics_status != "confirmed" else []
    vendor_profile["naics"]["confirmed"] = _merge_unique(vendor_profile["naics"].get("confirmed", []), confirmed_values)
    vendor_profile["naics"]["candidates"] = _merge_unique(
        vendor_profile["naics"].get("candidates", []),
        candidate_values + [item["code"] for item in inferred_naics],
    )
    vendor_profile.setdefault("other_taxonomy_tags", {})
    vendor_profile["other_taxonomy_tags"]["keywords"] = _merge_unique(
        vendor_profile["other_taxonomy_tags"].get("keywords", []),
        capabilities,
    )
    vendor_profile.setdefault("buyers", {})
    vendor_profile["buyers"]["notes"] = _merge_unique(vendor_profile["buyers"].get("notes", []), buyers)
    vendor_profile["notes"] = _merge_unique(
        vendor_profile.get("notes", []),
        ["Website-derived facts remain provisional until the user confirms them.", *fetch_notes],
    )
    vendor_profile.setdefault("provenance", {})
    vendor_profile["provenance"]["facts"] = _merge_unique(
        vendor_profile["provenance"].get("facts", []),
        [
            {
                "field": "company.website",
                "value": normalized_url,
                "source": normalized_url,
                "provenance": "user_confirmed",
                "captured_at": now,
            },
            {
                "field": "company.summary",
                "value": company_summary,
                "source": normalized_url,
                "provenance": "website_inferred" if pages else "manual_override",
                "captured_at": now,
            },
        ],
    )
    write_json(vendor_profile_path, vendor_profile)

    preferences_path = procurement / "preferences.json"
    preferences = load_json(bundle_root / "templates" / "preferences.template.json", default={}) or {}
    existing_preferences = load_json(preferences_path, default={}) or {}
    if isinstance(existing_preferences, dict):
        preferences.update(existing_preferences)
    preferences["last_updated"] = now
    preferences.setdefault("hard_filters", {})
    preferences["hard_filters"]["exclude_opportunity_classes"] = _merge_unique(
        preferences["hard_filters"].get("exclude_opportunity_classes", []),
        ["grants"],
    )
    preferences.setdefault("soft_preferences", {})
    preferences["soft_preferences"]["positive_keywords"] = _merge_unique(
        preferences["soft_preferences"].get("positive_keywords", []),
        capabilities,
    )
    preferences["soft_preferences"]["preferred_opportunity_classes"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_opportunity_classes", []),
        ["contracts", "subcontracts", "forecasts"],
    )
    preferences["soft_preferences"]["preferred_naics"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_naics", []),
        confirmed_values,
    )
    preferences.setdefault("provenance", {})
    preferences["provenance"]["seed_type"] = "company_url_bootstrap_script_v1"
    preferences["provenance"]["notes"] = _merge_unique(
        preferences["provenance"].get("notes", []),
        [
            f"Seeded from {normalized_url}",
            "Grants excluded by default until the user confirms interest.",
        ],
    )
    write_json(preferences_path, preferences)

    source_registry_path, _, _, _ = refresh_runtime_registry(bundle_root, workspace)

    starter_profile_path = procurement / "STARTER_PROFILE.md"
    starter_profile = _render_starter_profile(
        read_text(bundle_root / "templates" / "starter-brief.template.md"),
        company_url=normalized_url,
        user_naics=user_naics,
        summary=explicit_summary.strip(),
        company_summary=company_summary,
        capabilities=capabilities,
        buyers=buyers,
        candidate_naics=inferred_naics,
    )
    write_text(starter_profile_path, starter_profile)

    memory_path = workspace / "MEMORY.md"
    memory_snapshot = "\n".join(
        [
            f"## Bootstrap snapshot - {now[:10]}",
            "",
            f"- Company: {company_name}",
            f"- Website: {normalized_url}",
            f"- Seed method: company_url_bootstrap_script_v1",
            f"- Candidate competencies: {', '.join(capabilities[:4]) if capabilities else 'Needs confirmation'}",
            f"- Candidate buyers: {', '.join(buyers[:3]) if buyers else 'Needs confirmation'}",
            f"- Candidate NAICS: {', '.join(item['code'] for item in inferred_naics) if inferred_naics else 'Needs confirmation'}",
            "- Website-derived facts remain provisional until the user confirms them.",
            "",
            "Next confirmations:",
            "1. Confirm the 2 to 3 strongest capabilities.",
            "2. Confirm or reject the candidate NAICS.",
            "3. Name buyers, work types, or opportunity classes that should never show up.",
        ]
    ).strip()
    existing_memory = read_text(memory_path).rstrip()
    memory_text = memory_snapshot if not existing_memory else f"{existing_memory}\n\n{memory_snapshot}"
    write_text(memory_path, memory_text)

    recommended_next_moves = [
        f"Review {starter_profile_path.as_posix()} and confirm the inferred capabilities.",
        "Confirm or adjust NAICS before relying on them as hard filters.",
        "Run the 30-45 day federal scan after the starter profile looks right.",
    ]
    return {
        "status": "OK" if pages else "PARTIAL_BOOTSTRAP",
        "company_name": company_name,
        "company_url": normalized_url,
        "vendor_profile_path": vendor_profile_path.as_posix(),
        "preferences_path": preferences_path.as_posix(),
        "source_registry_path": source_registry_path.as_posix(),
        "starter_profile_path": starter_profile_path.as_posix(),
        "memory_path": memory_path.as_posix(),
        "candidate_naics": inferred_naics,
        "fetch_notes": fetch_notes,
        "recommended_next_moves": recommended_next_moves,
    }


def seed_workspace_from_govtribe(
    *,
    bundle_root: Path,
    workspace: Path,
    govtribe_lookup: str,
    company_url: str = "",
    user_naics: list[str],
    naics_status: str,
    explicit_name: str,
    explicit_summary: str,
    provider: Any | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    procurement = procurement_dir(workspace)
    source_registry_path, registry, _, _ = refresh_runtime_registry(bundle_root, workspace)
    source_config = _source_config(registry, GOVTRIBE_SOURCE_ID)
    resolver = provider or GovTribeMCPCommercialIntelProvider(source_config)
    lookup_result = resolver.resolve_vendor_profile(lookup=govtribe_lookup)
    lookup_status = str(lookup_result.get("status") or "error").strip()

    if not lookup_result.get("matched"):
        mapped_status = {
            "not_configured": "GOVTRIBE_NOT_CONFIGURED",
            "no_match": "GOVTRIBE_NO_MATCH",
            "tool_contract_unavailable": "GOVTRIBE_TOOL_CONTRACT_UNAVAILABLE",
        }.get(lookup_status, "GOVTRIBE_ERROR")
        fallback_url = company_url.strip()
        if fallback_url and not _is_govtribe_vendor_url(fallback_url):
            fallback = seed_workspace(
                bundle_root=bundle_root,
                workspace=workspace,
                company_url=fallback_url,
                user_naics=user_naics,
                naics_status=naics_status,
                explicit_name=explicit_name,
                explicit_summary=explicit_summary,
            )
            fallback["bootstrap_source"] = "website"
            fallback["fallback_source"] = "website"
            fallback["govtribe_status"] = mapped_status
            fallback["govtribe_notes"] = lookup_result.get("notes", [])
            return fallback
        return {
            "status": mapped_status,
            "bootstrap_source": "govtribe",
            "govtribe_status": mapped_status,
            "govtribe_notes": lookup_result.get("notes", []),
            "vendor_lookup": govtribe_lookup,
            "source_registry_path": source_registry_path.as_posix(),
            "recommended_next_moves": [
                "Export GOVTRIBE_MCP_API_KEY or provide a company website URL for website bootstrap fallback."
                if mapped_status == "GOVTRIBE_NOT_CONFIGURED"
                else "Provide a more specific vendor name, UEI, or company website URL."
            ],
        }

    vendor_record = lookup_result.get("vendor_record", {})
    if not isinstance(vendor_record, dict):
        vendor_record = {}
    _enable_govtribe_source(source_registry_path, registry, now)

    vendor_name = explicit_name.strip() or str(vendor_record.get("name") or "Vendor").strip()
    company_summary = explicit_summary.strip() or str(vendor_record.get("summary") or "").strip()
    if not company_summary:
        company_summary = "Vendor profile seeded from GovTribe subscription-derived fields. Review and confirm before scanning."
    govtribe_url = str(vendor_record.get("source_url") or vendor_record.get("govtribe_url") or govtribe_lookup).strip()
    display_source_url = govtribe_url or govtribe_lookup
    display_naics_items = _govtribe_naics_items(vendor_record, _six_digit_codes([str(item) for item in vendor_record.get("naics", [])]))
    vendor_naics = _merge_unique([], [item["code"] for item in display_naics_items if item.get("code")])
    confirmed_values = user_naics if naics_status == "confirmed" else []
    candidate_values = user_naics if naics_status != "confirmed" else []
    candidate_naics = _merge_unique(candidate_values, vendor_naics)
    capabilities = _govtribe_capabilities(vendor_record)
    buyers = _clean_govtribe_values(vendor_record.get("buyers", []))
    certifications = _clean_govtribe_values(vendor_record.get("certifications", []), allow_generic_metadata=True)
    set_aside_programs = _clean_govtribe_values(
        [item for item in certifications if "certified" in normalize_profile_term(item) or "small disadvantaged" in normalize_profile_term(item)]
    )
    contract_vehicles = _clean_govtribe_values(vendor_record.get("contract_vehicles", []))
    award_signals = _clean_govtribe_values(vendor_record.get("award_signals", []))
    keywords = [
        item
        for item in _clean_govtribe_values([*vendor_record.get("keywords", []), *capabilities])
        if not re.fullmatch(r"\d{6}", item)
    ]

    vendor_profile_path = procurement / "vendor-profile.json"
    vendor_profile = load_json(bundle_root / "templates" / "vendor-profile.template.json", default={}) or {}
    existing_vendor = load_json(vendor_profile_path, default={}) or {}
    if isinstance(existing_vendor, dict):
        vendor_profile.update(existing_vendor)
    vendor_profile["last_updated"] = now
    vendor_profile.setdefault("bootstrap", {})
    vendor_profile["bootstrap"]["method"] = "govtribe_vendor_bootstrap_script_v1"
    vendor_profile["bootstrap"]["inputs"] = {
        "company_url": company_url.strip(),
        "govtribe_vendor_lookup": govtribe_lookup,
        "user_supplied_naics": user_naics,
        "plain_language_summary": explicit_summary.strip(),
        "other_inputs": [],
    }
    vendor_profile["bootstrap"]["bootstrapped_on"] = now
    vendor_profile["bootstrap"]["status"] = "needs_user_confirmation"
    vendor_profile.setdefault("company", {})
    vendor_profile["company"]["name"] = vendor_name
    if company_url.strip() and not _is_govtribe_vendor_url(company_url):
        vendor_profile["company"]["website"] = _normalize_url(company_url)
    vendor_profile["company"]["summary"] = company_summary
    if vendor_record.get("uei"):
        vendor_profile["company"]["uei"] = vendor_record.get("uei")
    if vendor_record.get("location"):
        vendor_profile["company"]["headquarters"] = vendor_record.get("location")
    if govtribe_url:
        vendor_profile["company"]["govtribe_url"] = govtribe_url
    vendor_profile["core_competencies"] = _merge_unique(vendor_profile.get("core_competencies", []), capabilities)
    if not _clean_text(str(vendor_profile.get("fit_narrative", ""))):
        vendor_profile["fit_narrative"] = _govtribe_fit_narrative(vendor_record)
    vendor_profile.setdefault("naics", {})
    vendor_profile["naics"]["confirmed"] = _merge_unique(vendor_profile["naics"].get("confirmed", []), confirmed_values)
    vendor_profile["naics"]["candidates"] = _merge_unique(vendor_profile["naics"].get("candidates", []), candidate_naics)
    vendor_profile.setdefault("other_taxonomy_tags", {})
    vendor_profile["other_taxonomy_tags"]["keywords"] = _merge_unique(
        vendor_profile["other_taxonomy_tags"].get("keywords", []),
        [*keywords, *capabilities],
    )
    vendor_profile.setdefault("buyers", {})
    vendor_profile["buyers"]["notes"] = _merge_unique(vendor_profile["buyers"].get("notes", []), [*buyers, *award_signals])
    vendor_profile["past_performance_highlights"] = _merge_unique(
        vendor_profile.get("past_performance_highlights", []),
        award_signals,
    )
    vendor_profile.setdefault("commercial_constraints", {})
    vendor_profile["commercial_constraints"]["certifications"] = _merge_unique(
        vendor_profile["commercial_constraints"].get("certifications", []),
        certifications,
    )
    vendor_profile["commercial_constraints"]["set_aside_programs"] = _merge_unique(
        vendor_profile["commercial_constraints"].get("set_aside_programs", []),
        set_aside_programs,
    )
    vendor_profile["contract_vehicles"] = _merge_unique(vendor_profile.get("contract_vehicles", []), contract_vehicles)
    vendor_profile["notes"] = _merge_unique(
        vendor_profile.get("notes", []),
        [
            "GovTribe subscription-derived facts remain provisional until the user confirms them.",
            "GovTribe-derived facts are separate from website-derived facts.",
        ],
    )
    vendor_profile.setdefault("provenance", {})
    facts = vendor_profile["provenance"].get("facts", [])
    for field, value in (
        ("company.name", vendor_name),
        ("company.uei", vendor_record.get("uei")),
        ("company.summary", company_summary),
        ("company.headquarters", vendor_record.get("location")),
        ("company.govtribe_url", govtribe_url),
        ("naics.candidates", candidate_naics),
        ("commercial_constraints.certifications", certifications),
        ("contract_vehicles", contract_vehicles),
        ("buyers.notes", buyers),
        ("past_performance_highlights", award_signals),
    ):
        facts = _append_govtribe_provenance(facts, field=field, value=value, vendor_record=vendor_record, now=now)
    vendor_profile["provenance"]["facts"] = facts
    write_json(vendor_profile_path, vendor_profile)

    preferences_path = procurement / "preferences.json"
    preferences = load_json(bundle_root / "templates" / "preferences.template.json", default={}) or {}
    existing_preferences = load_json(preferences_path, default={}) or {}
    if isinstance(existing_preferences, dict):
        preferences.update(existing_preferences)
    preferences["last_updated"] = now
    preferences.setdefault("hard_filters", {})
    preferences["hard_filters"]["exclude_opportunity_classes"] = _merge_unique(
        preferences["hard_filters"].get("exclude_opportunity_classes", []),
        ["grants"],
    )
    preferences.setdefault("soft_preferences", {})
    preferences["soft_preferences"]["positive_keywords"] = _merge_unique(
        preferences["soft_preferences"].get("positive_keywords", []),
        keywords,
    )
    preferences["soft_preferences"]["preferred_opportunity_classes"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_opportunity_classes", []),
        ["contracts", "subcontracts", "forecasts"],
    )
    preferences["soft_preferences"]["preferred_naics"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_naics", []),
        [*confirmed_values, *candidate_naics],
    )
    preferences["soft_preferences"]["preferred_buyers"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_buyers", []),
        buyers,
    )
    preferences["soft_preferences"]["preferred_contract_vehicles"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_contract_vehicles", []),
        contract_vehicles,
    )
    preferences.setdefault("provenance", {})
    preferences["provenance"]["seed_type"] = "govtribe_vendor_bootstrap_script_v1"
    preferences["provenance"]["notes"] = _merge_unique(
        preferences["provenance"].get("notes", []),
        [
            f"Seeded from GovTribe vendor lookup: {govtribe_lookup}",
            "GovTribe subscription-derived facts remain provisional until user confirmation.",
            "Grants excluded by default until the user confirms interest.",
        ],
    )
    write_json(preferences_path, preferences)

    starter_profile_path = procurement / "STARTER_PROFILE.md"
    starter_profile = _render_starter_profile(
        read_text(bundle_root / "templates" / "starter-brief.template.md"),
        company_url=display_source_url,
        user_naics=[*confirmed_values, *candidate_naics],
        summary=explicit_summary.strip(),
        company_summary=company_summary,
        capabilities=capabilities,
        buyers=buyers,
        candidate_naics=_govtribe_naics_items(vendor_record, candidate_naics),
    )
    starter_profile += (
        "\n\nGovTribe source note: GovTribe subscription-derived facts are provisional commercial intelligence. "
        "Confirm them before treating them as user-confirmed or website-derived facts.\n"
    )
    write_text(starter_profile_path, starter_profile)

    memory_path = workspace / "MEMORY.md"
    memory_snapshot = "\n".join(
        [
            f"## Bootstrap snapshot - {now[:10]}",
            "",
            f"- Company: {vendor_name}",
            f"- GovTribe vendor: {govtribe_url or govtribe_lookup}",
            f"- UEI: {vendor_record.get('uei') or 'Not returned'}",
            "- Seed method: govtribe_vendor_bootstrap_script_v1",
            f"- Candidate competencies: {', '.join(capabilities[:4]) if capabilities else 'Needs confirmation'}",
            f"- Candidate buyers: {', '.join(buyers[:3]) if buyers else 'Needs confirmation'}",
            f"- Candidate NAICS: {', '.join(candidate_naics) if candidate_naics else 'Needs confirmation'}",
            "- GovTribe subscription-derived facts remain provisional and separate from website-derived facts.",
            "",
            "Next confirmations:",
            "1. Confirm the strongest capabilities and NAICS.",
            "2. Confirm GovTribe-reported certifications, vehicles, and buyer signals.",
            "3. Name buyers, work types, or opportunity classes that should never show up.",
        ]
    ).strip()
    existing_memory = read_text(memory_path).rstrip()
    memory_text = memory_snapshot if not existing_memory else f"{existing_memory}\n\n{memory_snapshot}"
    write_text(memory_path, memory_text)

    recommended_next_moves = [
        f"Review {starter_profile_path.as_posix()} and confirm the GovTribe-derived profile facts.",
        "Confirm or adjust NAICS before relying on them as hard filters.",
        "Run the 30-45 day federal scan after the starter profile looks right.",
    ]
    return {
        "status": "OK",
        "bootstrap_source": "govtribe",
        "govtribe_status": "ok",
        "company_name": vendor_name,
        "vendor_lookup": govtribe_lookup,
        "govtribe_url": govtribe_url,
        "vendor_profile_path": vendor_profile_path.as_posix(),
        "preferences_path": preferences_path.as_posix(),
        "source_registry_path": source_registry_path.as_posix(),
        "starter_profile_path": starter_profile_path.as_posix(),
        "memory_path": memory_path.as_posix(),
        "candidate_naics": _naics_items([*vendor_record.get("naics", []), *candidate_naics]),
        "govtribe_notes": lookup_result.get("notes", []),
        "recommended_next_moves": recommended_next_moves,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--company-url", default="")
    parser.add_argument("--vendor-lookup", default="")
    parser.add_argument("--naics", default="")
    parser.add_argument("--naics-status", choices=("confirmed", "candidate"), default="confirmed")
    parser.add_argument("--company-name", default="")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    bundle_root = bundle_root_from_script(__file__)
    user_naics = _parse_naics(args.naics)
    vendor_lookup = args.vendor_lookup.strip()
    if not vendor_lookup and args.company_url.strip() and _is_govtribe_vendor_url(args.company_url):
        vendor_lookup = args.company_url.strip()
    if vendor_lookup:
        result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=Path(args.workspace),
            govtribe_lookup=vendor_lookup,
            company_url=args.company_url,
            user_naics=user_naics,
            naics_status=args.naics_status,
            explicit_name=args.company_name,
            explicit_summary=args.summary,
        )
    else:
        if not args.company_url.strip():
            parser.error("--company-url is required unless --vendor-lookup is provided")
        result = seed_workspace(
            bundle_root=bundle_root,
            workspace=Path(args.workspace),
            company_url=args.company_url,
            user_naics=user_naics,
            naics_status=args.naics_status,
            explicit_name=args.company_name,
            explicit_summary=args.summary,
        )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
