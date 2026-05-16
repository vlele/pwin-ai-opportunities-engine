from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


RECIPIENT_AUTOCOMPLETE_URL = "https://api.usaspending.gov/api/v2/autocomplete/recipient/"
AWARD_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


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
        headers={"Content-Type": "application/json", "User-Agent": "pwin-ai-opportunities-v15"},
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


def enrich_from_usaspending(search_text: str) -> dict[str, Any]:
    autocomplete = _post_json(RECIPIENT_AUTOCOMPLETE_URL, recipient_autocomplete_payload(search_text))
    award_search = _post_json(AWARD_SEARCH_URL, spending_by_award_payload(search_text))
    return {
        "search_text": search_text,
        "recipient_autocomplete": autocomplete,
        "spending_by_award": award_search,
    }
