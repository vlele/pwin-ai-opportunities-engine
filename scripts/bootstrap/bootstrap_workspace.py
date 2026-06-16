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


def _vehicle_summary_match_terms(vehicles: list[str]) -> list[str]:
    terms: list[str] = []
    for vehicle in vehicles:
        text = _clean_bootstrap_signal(vehicle)
        if not text:
            continue
        terms.append(text)
        base_name = re.sub(r"\s*\([^)]*\)", "", text).strip()
        if base_name:
            terms.append(base_name)
        terms.extend(match.strip() for match in re.findall(r"\(([^)]+)\)", text) if match.strip())
    return _merge_unique([], terms)


def _contains_vehicle_term(text: str, terms: list[str]) -> bool:
    normalized_text = normalize_profile_term(text)
    for term in terms:
        normalized_term = normalize_profile_term(term)
        if normalized_term and normalized_term in normalized_text:
            return True
    return False


def _scrub_expired_vehicle_summary_claims(summary: str, expired_vehicles: list[str]) -> str:
    terms = _vehicle_summary_match_terms(expired_vehicles)
    if not terms:
        return summary
    kept: list[str] = []
    for paragraph in re.split(r"\n+", summary):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        has_vehicle_context = re.search(r"\b(contract vehicles?|vehicles?|idvs?|idiqs?|gwacs?|schedules?)\b", paragraph, re.I)
        if has_vehicle_context and _contains_vehicle_term(paragraph, terms):
            continue
        kept.append(paragraph)
    if kept:
        return "\n".join(kept)
    return "Vendor profile seeded from GovTribe subscription-derived fields. Current contract vehicle candidates are listed separately below."


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


def _govtribe_award_profile(vendor_record: dict[str, Any]) -> dict[str, Any]:
    value = vendor_record.get("govtribe_award_profile")
    return value if isinstance(value, dict) else {}


def _govtribe_sci_profile(vendor_record: dict[str, Any]) -> dict[str, Any]:
    value = vendor_record.get("govtribe_service_contract_inventory_profile")
    return value if isinstance(value, dict) else {}


def _govtribe_vehicle_subcategory_profile(vendor_record: dict[str, Any]) -> dict[str, Any]:
    value = vendor_record.get("govtribe_vehicle_subcategory_profile")
    return value if isinstance(value, dict) else {}


def _govtribe_sub_award_profile(vendor_record: dict[str, Any]) -> dict[str, Any]:
    value = vendor_record.get("govtribe_sub_award_profile")
    return value if isinstance(value, dict) else {}


def _govtribe_parent_vendor(vendor_record: dict[str, Any]) -> dict[str, str]:
    parent = vendor_record.get("parent_vendor")
    if not isinstance(parent, dict):
        hierarchy = vendor_record.get("vendor_hierarchy")
        parent = hierarchy.get("parent") if isinstance(hierarchy, dict) else {}
    if not isinstance(parent, dict):
        return {}
    output = {
        "name": _clean_text(str(parent.get("name") or "")),
        "uei": _clean_text(str(parent.get("uei") or "")),
        "govtribe_id": _clean_text(str(parent.get("govtribe_id") or "")),
        "govtribe_url": _clean_text(str(parent.get("govtribe_url") or "")),
    }
    return {key: value for key, value in output.items() if value}


def _govtribe_vendor_hierarchy(vendor_record: dict[str, Any]) -> dict[str, Any]:
    parent = _govtribe_parent_vendor(vendor_record)
    relationship = _clean_text(str(vendor_record.get("parent_or_child") or ""))
    if not relationship:
        hierarchy = vendor_record.get("vendor_hierarchy")
        if isinstance(hierarchy, dict):
            relationship = _clean_text(str(hierarchy.get("parent_or_child") or ""))
    output: dict[str, Any] = {}
    if relationship:
        output["parent_or_child"] = relationship
    if parent:
        output["parent"] = parent
    return output


def _govtribe_hierarchy_confirmation_prompt(vendor_name: str, vendor_record: dict[str, Any]) -> str:
    parent = _govtribe_parent_vendor(vendor_record)
    if not parent:
        return ""
    relationship = normalize_profile_term(str(vendor_record.get("parent_or_child") or ""))
    if relationship and relationship != "child":
        return ""
    parent_name = parent.get("name") or "the parent vendor"
    parent_uei = f" ({parent.get('uei')})" if parent.get("uei") else ""
    return (
        f"GovTribe resolved {vendor_name} as a child entity of {parent_name}{parent_uei}. "
        f"Confirm whether this workspace should stay on {vendor_name} or move up the vendor chain to {parent_name} before scanning."
    )


def _govtribe_profile_naics_codes(profile: dict[str, Any], *, max_items: int = 5) -> list[str]:
    values: list[str] = []
    for item in profile.get("top_naics", []):
        if isinstance(item, dict):
            code = _clean_text(str(item.get("code") or ""))
            if code:
                values.append(code)
    return _merge_unique([], values)[:max_items]


def _govtribe_award_naics_codes(vendor_record: dict[str, Any], *, max_items: int = 5) -> list[str]:
    return _govtribe_profile_naics_codes(_govtribe_award_profile(vendor_record), max_items=max_items)


def _govtribe_set_aside_programs(values: list[Any]) -> list[str]:
    programs = _clean_govtribe_values(values)
    return [item for item in programs if normalize_profile_term(item) != "no set aside used"]


def _format_money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if amount >= divisor:
            return f"{sign}${amount / divisor:.1f}{suffix}"
    return f"{sign}${amount:,.0f}"


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}"


def _govtribe_value_stats_note(vendor_record: dict[str, Any]) -> str:
    value_stats = _govtribe_award_profile(vendor_record).get("value_stats")
    if not isinstance(value_stats, dict):
        return "Needs confirmation"
    obligated = value_stats.get("dollars_obligated")
    if isinstance(obligated, dict):
        count = obligated.get("count")
        avg = _format_money(obligated.get("avg"))
        max_value = _format_money(obligated.get("max"))
        total = _format_money(obligated.get("sum"))
        parts = []
        if count not in (None, ""):
            parts.append(f"{count} award records")
        if avg:
            parts.append(f"average obligated {avg}")
        if max_value:
            parts.append(f"max obligated {max_value}")
        if total:
            parts.append(f"total obligated {total}")
        if parts:
            return "GovTribe award-history signal: " + ", ".join(parts) + "."
    ceiling = value_stats.get("ceiling_value")
    if isinstance(ceiling, dict):
        max_ceiling = _format_money(ceiling.get("max"))
        if max_ceiling:
            return f"GovTribe award-history signal: max reported ceiling {max_ceiling}."
    return "Needs confirmation"


def _govtribe_sci_pricing_note(vendor_record: dict[str, Any]) -> str:
    value_stats = _govtribe_sci_profile(vendor_record).get("value_stats")
    if not isinstance(value_stats, dict):
        return "Needs confirmation"
    parts: list[str] = []
    derived_rate = value_stats.get("derived_hourly_rate")
    if isinstance(derived_rate, dict):
        avg_rate = _format_money(derived_rate.get("avg"))
        min_rate = _format_money(derived_rate.get("min"))
        max_rate = _format_money(derived_rate.get("max"))
        count = derived_rate.get("count")
        if avg_rate:
            rate_note = f"average derived hourly rate {avg_rate}"
            bounds = [value for value in (min_rate, max_rate) if value]
            if len(bounds) == 2:
                rate_note += f" ({bounds[0]} to {bounds[1]})"
            parts.append(rate_note)
        if count not in (None, ""):
            parts.append(f"{count} SCI records")
    invoiced = value_stats.get("total_dollar_amount_invoiced")
    if isinstance(invoiced, dict):
        total = _format_money(invoiced.get("sum"))
        if total:
            parts.append(f"total invoiced {total}")
    hours = value_stats.get("hours_invoiced") or value_stats.get("total_contractor_hours_invoiced")
    if isinstance(hours, dict):
        total_hours = _format_number(hours.get("sum"))
        if total_hours:
            parts.append(f"{total_hours} invoiced hours")
    ftes = value_stats.get("ftes") or value_stats.get("total_ftes")
    if isinstance(ftes, dict):
        total_ftes = _format_number(ftes.get("sum"))
        if total_ftes:
            parts.append(f"{total_ftes} FTEs")
    if not parts:
        return "Needs confirmation"
    return "GovTribe Service Contract Inventory signal: " + ", ".join(parts) + "."


def _naics_label(item: dict[str, str]) -> str:
    code = item.get("code", "").strip()
    label = item.get("label", "").strip()
    if code and label:
        return f"{code} - {label}"
    return code or label or "Needs confirmation"


def _render_starter_profile(
    template_text: str,
    *,
    source_value: str,
    source_label: str = "Company URL",
    user_naics: list[str],
    summary: str,
    company_summary: str,
    capabilities: list[str],
    buyers: list[str],
    candidate_naics: list[dict[str, str]],
    contract_vehicles: list[str] | None = None,
    places_of_performance: list[str] | None = None,
    preferred_states: list[str] | None = None,
    set_aside_programs: list[str] | None = None,
    contract_types: list[str] | None = None,
    pricing_types: list[str] | None = None,
    vehicle_subcategories: list[str] | None = None,
    teaming_preferences: list[str] | None = None,
    award_value_note: str = "Needs confirmation",
    sci_pricing_note: str = "Needs confirmation",
    hierarchy_confirmation: str = "",
    provisional_fact_note: str = "Website-derived facts remain provisional until the user confirms them.",
) -> str:
    vehicle_values = contract_vehicles or []
    location_values = places_of_performance or []
    state_values = preferred_states or []
    set_aside_values = set_aside_programs or []
    contract_type_values = contract_types or []
    pricing_type_values = pricing_types or []
    vehicle_subcategory_values = vehicle_subcategories or []
    teaming_values = teaming_preferences or []
    replacements = {
        "{{DATE}}": utc_now_iso()[:10],
        "{{SOURCE_LABEL}}": source_label,
        "{{SOURCE_VALUE}}": source_value,
        "{{USER_NAICS}}": ", ".join(user_naics) if user_naics else "None provided",
        "{{SUMMARY}}": summary or "Not provided",
        "{{COMPANY_SUMMARY}}": company_summary or "Needs confirmation",
        "{{COMPETENCY_1}}": capabilities[0] if len(capabilities) > 0 else "Needs confirmation",
        "{{COMPETENCY_2}}": capabilities[1] if len(capabilities) > 1 else "Needs confirmation",
        "{{BUYER_1}}": buyers[0] if len(buyers) > 0 else "Needs confirmation",
        "{{BUYER_2}}": buyers[1] if len(buyers) > 1 else "Needs confirmation",
        "{{VEHICLE_1}}": vehicle_values[0] if len(vehicle_values) > 0 else "Needs confirmation",
        "{{VEHICLE_2}}": vehicle_values[1] if len(vehicle_values) > 1 else "Needs confirmation",
        "{{NAICS_1}}": _naics_label(candidate_naics[0]) if len(candidate_naics) > 0 else "Needs confirmation",
        "{{NAICS_2}}": _naics_label(candidate_naics[1]) if len(candidate_naics) > 1 else "Needs confirmation",
        "{{LOCATION_1}}": location_values[0] if len(location_values) > 0 else "Needs confirmation",
        "{{LOCATION_2}}": location_values[1] if len(location_values) > 1 else "Needs confirmation",
        "{{STATE_1}}": state_values[0] if len(state_values) > 0 else "Needs confirmation",
        "{{STATE_2}}": state_values[1] if len(state_values) > 1 else "Needs confirmation",
        "{{SET_ASIDE_1}}": set_aside_values[0] if len(set_aside_values) > 0 else "Needs confirmation",
        "{{SET_ASIDE_2}}": set_aside_values[1] if len(set_aside_values) > 1 else "Needs confirmation",
        "{{CONTRACT_TYPE_1}}": contract_type_values[0] if len(contract_type_values) > 0 else "Needs confirmation",
        "{{CONTRACT_TYPE_2}}": contract_type_values[1] if len(contract_type_values) > 1 else "Needs confirmation",
        "{{PRICING_TYPE_1}}": pricing_type_values[0] if len(pricing_type_values) > 0 else "Needs confirmation",
        "{{PRICING_TYPE_2}}": pricing_type_values[1] if len(pricing_type_values) > 1 else "Needs confirmation",
        "{{VEHICLE_SUBCATEGORY_1}}": vehicle_subcategory_values[0] if len(vehicle_subcategory_values) > 0 else "Needs confirmation",
        "{{VEHICLE_SUBCATEGORY_2}}": vehicle_subcategory_values[1] if len(vehicle_subcategory_values) > 1 else "Needs confirmation",
        "{{TEAMING_1}}": teaming_values[0] if len(teaming_values) > 0 else "Needs confirmation",
        "{{TEAMING_2}}": teaming_values[1] if len(teaming_values) > 1 else "Needs confirmation",
        "{{AWARD_VALUE_SIGNAL}}": award_value_note or "Needs confirmation",
        "{{SCI_PRICING_SIGNAL}}": sci_pricing_note or "Needs confirmation",
        "{{HIERARCHY_CONFIRMATION}}": hierarchy_confirmation or "No GovTribe parent hierarchy signal detected.",
        "{{EXCLUSION_1}}": "Grants are excluded by default until the user opts in.",
        "{{EXCLUSION_2}}": provisional_fact_note,
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
        source_value=normalized_url,
        user_naics=user_naics,
        summary=explicit_summary.strip(),
        company_summary=company_summary,
        capabilities=capabilities,
        buyers=buyers,
        contract_vehicles=[],
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
    explicit_summary_text = explicit_summary.strip()
    company_summary = explicit_summary_text or str(vendor_record.get("summary") or "").strip()
    if not company_summary:
        company_summary = "Vendor profile seeded from GovTribe subscription-derived fields. Review and confirm before scanning."
    govtribe_url = str(vendor_record.get("source_url") or vendor_record.get("govtribe_url") or govtribe_lookup).strip()
    display_source_url = govtribe_url or govtribe_lookup
    parent_vendor = _govtribe_parent_vendor(vendor_record)
    vendor_hierarchy = _govtribe_vendor_hierarchy(vendor_record)
    hierarchy_confirmation = _govtribe_hierarchy_confirmation_prompt(vendor_name, vendor_record)
    display_naics_items = _govtribe_naics_items(vendor_record, _six_digit_codes([str(item) for item in vendor_record.get("naics", [])]))
    award_profile = _govtribe_award_profile(vendor_record)
    sci_profile = _govtribe_sci_profile(vendor_record)
    vehicle_subcategory_profile = _govtribe_vehicle_subcategory_profile(vendor_record)
    sub_award_profile = _govtribe_sub_award_profile(vendor_record)
    award_naics = _govtribe_award_naics_codes(vendor_record, max_items=5)
    sci_naics = _govtribe_profile_naics_codes(sci_profile, max_items=5)
    vendor_naics = _merge_unique(award_naics, sci_naics)[:5] or _merge_unique([], [item["code"] for item in display_naics_items if item.get("code")])[:5]
    confirmed_values = user_naics if naics_status == "confirmed" else []
    candidate_values = user_naics if naics_status != "confirmed" else []
    candidate_naics = _merge_unique(candidate_values, vendor_naics)
    capabilities = _govtribe_capabilities(vendor_record)
    buyers = _clean_govtribe_values(vendor_record.get("buyers", []))
    certifications = _clean_govtribe_values(vendor_record.get("certifications", []))
    certification_set_asides = _clean_govtribe_values(
        [item for item in certifications if "certified" in normalize_profile_term(item) or "small disadvantaged" in normalize_profile_term(item)]
    )
    places_of_performance = _clean_govtribe_values(vendor_record.get("places_of_performance", []))
    preferred_states = _clean_govtribe_values(vendor_record.get("preferred_states", []))
    set_asides = _clean_govtribe_values(vendor_record.get("set_asides", []))
    set_aside_programs = _merge_unique(certification_set_asides, _govtribe_set_aside_programs(set_asides))
    contract_types = _clean_govtribe_values(vendor_record.get("contract_types", []))
    pricing_types = _clean_govtribe_values(vendor_record.get("pricing_types", []))
    prime_or_sub = _clean_govtribe_values(vendor_record.get("prime_or_sub", []))
    psc_codes = _clean_govtribe_values(vendor_record.get("psc_codes", []))
    contract_vehicle_subcategories = _clean_govtribe_values(vendor_record.get("contract_vehicle_subcategories", []))
    teaming_preferences = _clean_govtribe_values(vendor_record.get("teaming_preferences", []), allow_generic_metadata=True)
    award_value_note = _govtribe_value_stats_note(vendor_record)
    sci_pricing_note = _govtribe_sci_pricing_note(vendor_record)
    contract_vehicles = _clean_govtribe_values(vendor_record.get("contract_vehicles", []))
    expired_contract_vehicles = _clean_govtribe_values(vendor_record.get("expired_contract_vehicles", []))
    if not explicit_summary_text:
        company_summary = _scrub_expired_vehicle_summary_claims(company_summary, expired_contract_vehicles)
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
    if parent_vendor:
        vendor_profile["company"]["parent"] = parent_vendor
    if vendor_hierarchy:
        vendor_profile["govtribe_vendor_hierarchy"] = vendor_hierarchy
    vendor_profile["core_competencies"] = _merge_unique(vendor_profile.get("core_competencies", []), capabilities)
    if not _clean_text(str(vendor_profile.get("fit_narrative", ""))):
        vendor_profile["fit_narrative"] = _govtribe_fit_narrative(vendor_record)
    vendor_profile.setdefault("naics", {})
    vendor_profile["naics"]["confirmed"] = _merge_unique(vendor_profile["naics"].get("confirmed", []), confirmed_values)
    vendor_profile["naics"]["candidates"] = _merge_unique(vendor_profile["naics"].get("candidates", []), candidate_naics)
    if award_profile:
        vendor_profile["govtribe_award_profile"] = award_profile
    if sci_profile:
        vendor_profile["govtribe_service_contract_inventory_profile"] = sci_profile
    if vehicle_subcategory_profile:
        vendor_profile["govtribe_vehicle_subcategory_profile"] = vehicle_subcategory_profile
    if sub_award_profile:
        vendor_profile["govtribe_sub_award_profile"] = sub_award_profile
    vendor_profile.setdefault("other_taxonomy_tags", {})
    vendor_profile["other_taxonomy_tags"]["keywords"] = _merge_unique(
        vendor_profile["other_taxonomy_tags"].get("keywords", []),
        [*keywords, *capabilities],
    )
    vendor_profile["other_taxonomy_tags"]["psc"] = _merge_unique(
        vendor_profile["other_taxonomy_tags"].get("psc", []),
        psc_codes,
    )
    vendor_profile.setdefault("buyers", {})
    vendor_profile["buyers"]["notes"] = _merge_unique(vendor_profile["buyers"].get("notes", []), [*buyers, *award_signals])
    vendor_profile["past_performance_highlights"] = _merge_unique(
        vendor_profile.get("past_performance_highlights", []),
        award_signals,
    )
    vendor_profile.setdefault("geography", {})
    vendor_profile["geography"]["place_of_performance"] = _merge_unique(
        vendor_profile["geography"].get("place_of_performance", []),
        places_of_performance,
    )
    vendor_profile["geography"]["preferred_states"] = _merge_unique(
        vendor_profile["geography"].get("preferred_states", []),
        preferred_states,
    )
    vendor_profile["geography"].setdefault("excluded_states", [])
    vendor_profile["geography"].setdefault("remote_ok", True)
    vendor_profile.setdefault("commercial_constraints", {})
    existing_certifications = _clean_govtribe_values(vendor_profile["commercial_constraints"].get("certifications", []))
    vendor_profile["commercial_constraints"]["certifications"] = _merge_unique(
        existing_certifications,
        certifications,
    )
    vendor_profile["commercial_constraints"]["set_aside_programs"] = _merge_unique(
        vendor_profile["commercial_constraints"].get("set_aside_programs", []),
        set_aside_programs,
    )
    vendor_profile["commercial_constraints"]["prime_or_sub"] = _merge_unique(
        vendor_profile["commercial_constraints"].get("prime_or_sub", []),
        prime_or_sub,
    )
    vendor_profile["commercial_constraints"]["teaming_preferences"] = _merge_unique(
        vendor_profile["commercial_constraints"].get("teaming_preferences", []),
        teaming_preferences,
    )
    vendor_profile["contract_vehicles"] = _merge_unique(vendor_profile.get("contract_vehicles", []), contract_vehicles)
    vendor_profile["contract_vehicle_subcategories"] = _merge_unique(
        vendor_profile.get("contract_vehicle_subcategories", []),
        contract_vehicle_subcategories,
    )
    vendor_profile["notes"] = _merge_unique(
        vendor_profile.get("notes", []),
        [
            item
            for item in (
                "GovTribe subscription-derived facts remain provisional until the user confirms them.",
                "GovTribe-derived facts are separate from website-derived facts.",
                hierarchy_confirmation,
            )
            if item
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
        ("company.parent", parent_vendor),
        ("govtribe_vendor_hierarchy", vendor_hierarchy),
        ("naics.candidates", candidate_naics),
        ("govtribe_award_profile", award_profile),
        ("govtribe_service_contract_inventory_profile", sci_profile),
        ("govtribe_vehicle_subcategory_profile", vehicle_subcategory_profile),
        ("govtribe_sub_award_profile", sub_award_profile),
        ("other_taxonomy_tags.psc", psc_codes),
        ("geography.place_of_performance", places_of_performance),
        ("geography.preferred_states", preferred_states),
        ("commercial_constraints.certifications", certifications),
        ("commercial_constraints.set_aside_programs", set_aside_programs),
        ("commercial_constraints.prime_or_sub", prime_or_sub),
        ("commercial_constraints.teaming_preferences", teaming_preferences),
        ("contract_vehicles", contract_vehicles),
        ("contract_vehicle_subcategories", contract_vehicle_subcategories),
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
    preferences["soft_preferences"]["preferred_states"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_states", []),
        preferred_states,
    )
    preferences["soft_preferences"]["preferred_set_asides"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_set_asides", []),
        set_aside_programs,
    )
    preferences["soft_preferences"]["preferred_contract_types"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_contract_types", []),
        contract_types,
    )
    preferences["soft_preferences"]["preferred_pricing_types"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_pricing_types", []),
        pricing_types,
    )
    preferences["soft_preferences"]["preferred_psc"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_psc", []),
        psc_codes,
    )
    preferences["soft_preferences"]["preferred_buyers"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_buyers", []),
        buyers,
    )
    preferences["soft_preferences"]["preferred_contract_vehicles"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_contract_vehicles", []),
        contract_vehicles,
    )
    preferences["soft_preferences"]["preferred_contract_vehicle_subcategories"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_contract_vehicle_subcategories", []),
        contract_vehicle_subcategories,
    )
    preferences["soft_preferences"]["preferred_teaming_partners"] = _merge_unique(
        preferences["soft_preferences"].get("preferred_teaming_partners", []),
        teaming_preferences,
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
        source_label="GovTribe vendor",
        source_value=display_source_url,
        user_naics=user_naics,
        summary=explicit_summary.strip(),
        company_summary=company_summary,
        capabilities=capabilities,
        buyers=buyers,
        contract_vehicles=contract_vehicles,
        places_of_performance=places_of_performance,
        preferred_states=preferred_states,
        set_aside_programs=set_aside_programs,
        contract_types=contract_types,
        pricing_types=pricing_types,
        vehicle_subcategories=contract_vehicle_subcategories,
        teaming_preferences=teaming_preferences,
        award_value_note=award_value_note,
        sci_pricing_note=sci_pricing_note,
        hierarchy_confirmation=hierarchy_confirmation,
        candidate_naics=_govtribe_naics_items(vendor_record, candidate_naics),
        provisional_fact_note="GovTribe-derived facts remain provisional until the user confirms them.",
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
            f"- Vendor hierarchy check: {hierarchy_confirmation or 'No GovTribe parent hierarchy signal detected.'}",
            f"- Candidate vehicle subcategories: {', '.join(contract_vehicle_subcategories[:3]) if contract_vehicle_subcategories else 'Needs confirmation'}",
            f"- Service contract pricing signal: {sci_pricing_note}",
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
        hierarchy_confirmation,
        f"Review {starter_profile_path.as_posix()} and confirm the GovTribe-derived profile facts.",
        "Confirm or adjust NAICS before relying on them as hard filters.",
        "Run the 30-45 day federal scan after the starter profile looks right.",
    ]
    recommended_next_moves = [item for item in recommended_next_moves if item]
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
