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

from common.paths import bundle_root_from_script, load_json, procurement_dir, read_text, utc_now_iso, write_json, write_text
from common.source_registry import refresh_runtime_registry


USER_AGENT = "pwin-ai-opportunities-bootstrap/1.0"
MAX_FETCH_BYTES = 750_000
MAX_RELEVANT_LINKS = 4
GENERIC_SECTIONS = {
    "about",
    "contact",
    "home",
    "services",
    "solutions",
    "industries",
    "capabilities",
    "partners",
    "case studies",
    "case study",
}
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
    ("Department of Veterans Affairs", ("veteran", "va", "benefits", "vba", "vha")),
    ("Department of Defense", ("defense", "warfighter", "mission systems", "army", "navy", "air force")),
    ("Department of Homeland Security", ("border", "homeland security", "emergency management", "cisa", "fema")),
    ("General Services Administration", ("shared services", "federal modernization", "acquisition", "gsa")),
]
GENERIC_NAME_SEGMENTS = {"home", "welcome", "homepage"}


@dataclass
class PageSignals:
    url: str
    title: str = ""
    description: str = ""
    headings: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)


class _HTMLSignalsParser(HTMLParser):
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
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        lowered = tag.lower()
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
            if self._active[index]["tag"] != lowered:
                continue
            item = self._active.pop(index)
            text = _clean_text(" ".join(item["chunks"]))
            if not text:
                return
            if lowered == "title" and not self.title:
                self.title = text
            elif lowered in {"h1", "h2", "h3"}:
                _append_unique(self.headings, text)
            elif lowered in {"p", "li"} and len(text) >= 40:
                _append_unique(self.paragraphs, text)
            elif lowered == "a":
                href = item.get("href", "")
                if href:
                    self.links.append((href, text))
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


def _normalize_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("company_url is required")
    if value.startswith(("http://", "https://", "file://")):
        return value
    return f"https://{value}"


def _parse_html(url: str, html: str) -> PageSignals:
    parser = _HTMLSignalsParser()
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
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            if url.startswith(("http://", "https://")) and "html" not in content_type.lower():
                return None, f"Skipped non-HTML content at {url}"
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_FETCH_BYTES)
            return body.decode(charset, errors="ignore"), None
    except Exception as exc:  # pragma: no cover - network error surface
        return None, f"Could not fetch {url}: {exc}"


def _same_site(base_url: str, candidate_url: str) -> bool:
    base = urllib.parse.urlparse(base_url)
    candidate = urllib.parse.urlparse(candidate_url)
    if base.scheme == "file" and candidate.scheme == "file":
        return True
    if candidate.scheme not in {"http", "https"}:
        return False
    if not base.hostname or not candidate.hostname:
        return False
    return candidate.hostname == base.hostname or candidate.hostname.endswith(f".{base.hostname}")


def _rank_link(base_url: str, href: str, text: str) -> int:
    absolute = urllib.parse.urljoin(base_url, href)
    if not _same_site(base_url, absolute):
        return -1
    parsed = urllib.parse.urlparse(absolute)
    if parsed.fragment:
        return -1
    path = parsed.path.lower()
    anchor = text.lower()
    combined = f"{path} {anchor}"
    if any(token in combined for token in ("privacy", "terms", "login", "careers", "news", "press")):
        return -1
    score = 0
    for hint in RELEVANT_LINK_HINTS:
        if hint in combined:
            score += 3
    if parsed.query:
        score -= 1
    if score == 0 and anchor in GENERIC_SECTIONS:
        score = 2
    return score


def _fetch_site_signals(company_url: str) -> tuple[list[PageSignals], list[str]]:
    pages: list[PageSignals] = []
    notes: list[str] = []
    homepage_html, error = _fetch_html(company_url)
    if error:
        notes.append(error)
        return pages, notes
    if not homepage_html:
        notes.append(f"No usable HTML found at {company_url}")
        return pages, notes

    homepage = _parse_html(company_url, homepage_html)
    pages.append(homepage)

    ranked_links: list[tuple[int, str]] = []
    for href, text in homepage.links:
        score = _rank_link(company_url, href, text)
        if score < 0:
            continue
        absolute = urllib.parse.urljoin(company_url, href)
        ranked_links.append((score, absolute))
    ranked_links.sort(key=lambda item: (-item[0], item[1]))

    seen = {company_url}
    for _, link in ranked_links:
        if link in seen:
            continue
        if len(pages) >= MAX_RELEVANT_LINKS + 1:
            break
        html, child_error = _fetch_html(link)
        seen.add(link)
        if child_error:
            notes.append(child_error)
            continue
        if not html:
            continue
        pages.append(_parse_html(link, html))
    return pages, notes


def _domain_label(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        stem = Path(parsed.path).stem or "company"
        return stem.replace("-", " ").replace("_", " ").title()
    host = parsed.hostname or "company"
    parts = [part for part in host.split(".") if part and part not in {"www", "com", "net", "org", "io", "ai", "gov"}]
    label = " ".join(parts[:2]) if parts else "company"
    return label.replace("-", " ").title()


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
    return "Company profile seeded from the provided website. Review and expand this summary before relying on it as a hard fit signal."


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

    for page in pages:
        for heading in page.headings:
            cleaned = _clean_text(heading)
            lowered = cleaned.lower()
            if not cleaned or lowered in GENERIC_SECTIONS:
                continue
            if len(cleaned.split()) > 6:
                continue
            if cleaned.lower() == summary.lower():
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


def _build_fit_narrative(capabilities: list[str], buyer_candidates: list[str]) -> str:
    phrases = [item for item in capabilities[:3] if item]
    if not phrases:
        phrases = ["the company's confirmed core competencies"]
    buyer_note = f" for buyers such as {', '.join(buyer_candidates[:2])}" if buyer_candidates else ""
    return f"Prioritize opportunities involving {', '.join(phrases)}{buyer_note}. Avoid grants until the user explicitly opts in."


def _parse_naics(raw_value: str) -> list[str]:
    values: list[str] = []
    for part in re.split(r"[,;\s]+", raw_value.strip()):
        cleaned = part.strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _merge_unique(existing: list[Any], additions: list[Any]) -> list[Any]:
    result: list[Any] = list(existing)
    seen = {json.dumps(item, sort_keys=True) for item in existing}
    for item in additions:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


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


def _naics_label(item: dict[str, str]) -> str:
    code = item.get("code", "").strip()
    label = item.get("label", "").strip()
    return f"{code} - {label}".strip(" -")


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

    vendor_template_path = bundle_root / "templates" / "vendor-profile.template.json"
    vendor_profile_path = procurement / "vendor-profile.json"
    existing_vendor = load_json(vendor_profile_path, default={}) or {}
    vendor_profile = load_json(vendor_template_path, default={}) or {}
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
    if explicit_summary.strip() or (company_summary and not _clean_text(str(vendor_profile["company"].get("summary", "")))):
        vendor_profile["company"]["summary"] = company_summary
    if capabilities:
        vendor_profile["core_competencies"] = _merge_unique(vendor_profile.get("core_competencies", []), capabilities[:6])
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
        capabilities[:6],
    )
    vendor_profile.setdefault("buyers", {})
    vendor_profile["buyers"]["notes"] = _merge_unique(vendor_profile["buyers"].get("notes", []), buyers)
    vendor_profile.setdefault("notes", [])
    vendor_profile["notes"] = _merge_unique(
        vendor_profile["notes"],
        [
            "Website-derived facts remain provisional until the user confirms them.",
            *fetch_notes,
        ],
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

    preferences_template_path = bundle_root / "templates" / "preferences.template.json"
    preferences_path = procurement / "preferences.json"
    existing_preferences = load_json(preferences_path, default={}) or {}
    preferences = load_json(preferences_template_path, default={}) or {}
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
        capabilities[:6],
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

    starter_template_path = bundle_root / "templates" / "starter-brief.template.md"
    starter_profile_path = procurement / "STARTER_PROFILE.md"
    starter_profile_text = _render_starter_profile(
        read_text(starter_template_path),
        company_url=normalized_url,
        user_naics=user_naics,
        summary=explicit_summary.strip(),
        company_summary=company_summary,
        capabilities=capabilities,
        buyers=buyers,
        candidate_naics=inferred_naics,
    )
    write_text(starter_profile_path, starter_profile_text)

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
    status = "OK" if pages else "PARTIAL_BOOTSTRAP"
    return {
        "status": status,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--company-url", required=True)
    parser.add_argument("--naics", default="")
    parser.add_argument("--naics-status", choices=("confirmed", "candidate"), default="confirmed")
    parser.add_argument("--company-name", default="")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    bundle_root = bundle_root_from_script(__file__)
    workspace = Path(args.workspace)
    result = seed_workspace(
        bundle_root=bundle_root,
        workspace=workspace,
        company_url=args.company_url,
        user_naics=_parse_naics(args.naics),
        naics_status=args.naics_status,
        explicit_name=args.company_name,
        explicit_summary=args.summary,
    )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
