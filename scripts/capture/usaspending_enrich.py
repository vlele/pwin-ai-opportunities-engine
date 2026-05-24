from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from common.runtime import USER_AGENT


RECIPIENT_AUTOCOMPLETE_URL = "https://api.usaspending.gov/api/v2/autocomplete/recipient/"
AWARD_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
GENERIC_TERMS = {
    "rfp",
    "rfq",
    "rfi",
    "idiq",
    "bpa",
    "task",
    "order",
    "support",
    "services",
    "system",
    "program",
    "solicitation",
    "combined",
    "synopsis",
    "amendment",
    "notice",
    "next",
    "generation",
    "acquisition",
}
SOLICITATION_ID_RE = re.compile(r"(?:solicitation(?: number)?|notice id)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{5,})", re.IGNORECASE)
ACRONYM_RE = re.compile(r"\(([A-Z][A-Z0-9-]{1,14})\)")
PHRASE_WITH_ACRONYM_RE = re.compile(r"([A-Za-z][A-Za-z0-9/&' -]{4,80}?)\s*\(([A-Z][A-Z0-9-]{1,14})\)")
TITLE_PREFIX_RE = re.compile(
    r"^(?:rfp|rfq|rfi|sources sought|special notice|presolicitation|combined synopsis/solicitation)\s*[-:]\s*",
    re.IGNORECASE,
)
MAX_QUERY_LENGTH = 96


def recipient_autocomplete_payload(search_text: str) -> dict[str, Any]:
    return {"search_text": search_text}


def spending_by_award_payload(search_text: str, page: int = 1, limit: int = 5) -> dict[str, Any]:
    return {
        "filters": {
            "keywords": [search_text],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Start Date",
            "End Date",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Award Type",
            "Description",
        ],
        "page": page,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def _post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return {"status": "ok", "payload": payload, "response": json.loads(body)}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"status": "http_error", "payload": payload, "code": exc.code, "detail": detail}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"status": "error", "payload": payload, "detail": str(exc)}


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _dedupe_terms(values: list[str]) -> list[str]:
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


def _compact_query(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip(" -:"))
    return cleaned if 0 < len(cleaned) <= MAX_QUERY_LENGTH else ""


def _all_generic_tokens(value: str) -> bool:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9]+", value)]
    return bool(tokens) and all(token in GENERIC_TERMS for token in tokens)


def build_search_terms(search_text: str, title: str = "", summary: str = "", buyer: str = "") -> list[str]:
    title_text = title or search_text
    combined = f"{title_text}\n{summary or ''}"
    terms: list[str] = []

    for match in SOLICITATION_ID_RE.finditer(combined):
        candidate = match.group(1).strip()
        if not re.search(r"\d", candidate):
            continue
        compact = _compact_query(candidate)
        if compact:
            terms.append(compact)

    for match in PHRASE_WITH_ACRONYM_RE.finditer(title_text):
        phrase = TITLE_PREFIX_RE.sub("", re.sub(r"\s+", " ", match.group(1)).strip(" -:"))
        acronym = match.group(2).strip()
        if phrase and 2 <= len(phrase.split()) <= 8:
            compact_phrase = _compact_query(phrase)
            if compact_phrase:
                terms.append(compact_phrase)
            phrase_parts = phrase.split()
            if len(phrase_parts) >= 3:
                compact_tail = _compact_query(" ".join(phrase_parts[-3:]))
                if compact_tail and not _all_generic_tokens(compact_tail):
                    terms.append(compact_tail)
        if acronym.lower() not in GENERIC_TERMS:
            terms.append(acronym)

    for acronym in ACRONYM_RE.findall(title_text):
        if acronym.lower() not in GENERIC_TERMS:
            terms.append(acronym.strip())

    cleaned_title = TITLE_PREFIX_RE.sub("", title_text).strip(" -:")
    if cleaned_title and cleaned_title.lower() != title_text.lower():
        compact_title = _compact_query(cleaned_title)
        if compact_title:
            terms.append(compact_title)

    for match in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{3,}\b", title_text):
        token = match.strip()
        normalized = token.lower()
        if normalized in GENERIC_TERMS:
            continue
        if "-" in token:
            continue
        if token.isupper() or any(char.isupper() for char in token[1:]):
            terms.append(token)

    buyer_text = buyer or ""
    if "NOAA" in buyer_text and any(term.lower() == "protech" for term in terms):
        terms.append("ProTech")

    compact_search_text = _compact_query(search_text)
    if compact_search_text:
        terms.append(compact_search_text)
    return _dedupe_terms(terms)[:6]


def _merge_award_rows(searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in searches:
        if item.get("status") != "ok":
            continue
        response = item.get("response", {})
        rows = response.get("results", []) if isinstance(response, dict) else []
        query = item.get("query", "")
        for row in rows:
            award_id = str(row.get("Award ID") or row.get("generated_internal_id") or row.get("internal_id") or "")
            if not award_id:
                continue
            existing = merged.get(award_id)
            if existing is None:
                enriched = dict(row)
                enriched["_query_terms"] = [query] if query else []
                merged[award_id] = enriched
                continue
            if query and query not in existing.get("_query_terms", []):
                existing["_query_terms"] = [*existing.get("_query_terms", []), query]
    return list(merged.values())


def enrich_from_usaspending(search_text: str, title: str = "", summary: str = "", buyer: str = "") -> dict[str, Any]:
    search_terms = build_search_terms(search_text, title=title, summary=summary, buyer=buyer)
    autocomplete = _post_json(RECIPIENT_AUTOCOMPLETE_URL, recipient_autocomplete_payload(search_text))
    award_searches = []
    for query in search_terms:
        result = _post_json(AWARD_SEARCH_URL, spending_by_award_payload(query))
        award_searches.append({"query": query, **result})
    merged_results = _merge_award_rows(award_searches)
    if any(item.get("status") == "ok" for item in award_searches):
        award_status = "ok"
    elif any(item.get("status") == "http_error" for item in award_searches):
        award_status = "http_error"
    else:
        award_status = "error"
    return {
        "search_text": search_text,
        "search_terms": search_terms,
        "recipient_autocomplete": autocomplete,
        "award_searches": award_searches,
        "spending_by_award": {
            "status": award_status,
            "payload": {"queries": search_terms},
            "response": {
                "results": merged_results,
                "query_terms": search_terms,
                "query_count": len(search_terms),
                "queries_with_results": [item.get("query", "") for item in award_searches if (item.get("response") or {}).get("results")],
            },
        },
    }
