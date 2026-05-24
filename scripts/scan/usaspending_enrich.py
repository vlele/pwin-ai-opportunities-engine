from __future__ import annotations

from typing import Any

from common.usaspending import AWARD_SEARCH_URL, build_spending_by_award_payload, post_json


def post_award_search(search_text: str, page: int = 1, limit: int = 10, timeout: int = 20) -> dict[str, Any]:
    payload = build_spending_by_award_payload(search_text, page=page, limit=limit)
    return post_json(AWARD_SEARCH_URL, payload, timeout=timeout)
