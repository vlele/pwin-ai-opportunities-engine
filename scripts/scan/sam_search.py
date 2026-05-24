from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

from common.paths import utc_now_iso
from common.runtime import USER_AGENT

SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"


def _format_mmddyyyy(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(cleaned[: len(fmt)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _response_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("opportunitiesData", "records", "data", "opportunities"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return ""


def _normalize_money(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return value


def _normalize_record(record: dict[str, Any], queried_naics: str) -> dict[str, Any]:
    title = _record_value(record, "title", "solicitationTitle")
    notice_id = str(_record_value(record, "noticeId", "notice_id", "id", "solicitationNumber", "solicitation_number"))
    url = _record_value(record, "uiLink", "link", "url")
    if notice_id and not url:
        url = f"https://sam.gov/opp/{notice_id}/view"
    return {
        "source_id": "sam_contract_opportunities",
        "source_name": "SAM.gov",
        "source_tier": 1,
        "opportunity_id": notice_id,
        "canonical_record_id": notice_id,
        "canonical_record_id_type": "notice_id",
        "notice_id": notice_id,
        "title": title or "Untitled opportunity",
        "url": url,
        "buyer": _record_value(record, "fullParentPathName", "organizationType", "departmentIndAgency", "organizationName") or "N/A",
        "opportunity_class": "contracts",
        "notice_type": _record_value(record, "type", "noticeType", "notice_type"),
        "solicitation_number": _record_value(record, "solicitationNumber", "solicitation_number"),
        "posted_date": _record_value(record, "postedDate", "posted_date"),
        "due_date": _record_value(record, "responseDeadLine", "archiveDate", "responseDeadline", "due_date") or "N/A",
        "location": _record_value(record, "placeOfPerformance", "place_of_performance", "officeAddress"),
        "naics": [queried_naics] if queried_naics else [],
        "other_taxonomy_tags": [],
        "set_aside": _record_value(record, "typeOfSetAsideDescription", "typeOfSetAside", "setAside"),
        "estimated_value": _normalize_money(_record_value(record, "award", "estimatedValue", "estimated_value")),
        "summary": _record_value(record, "description", "additionalInfoLink", "summary") or "N/A",
        "point_of_contact": record.get("pointOfContact", []) if isinstance(record.get("pointOfContact"), list) else [],
        "resource_links": record.get("resourceLinks", []) if isinstance(record.get("resourceLinks"), list) else [],
        "retrieval_timestamp": utc_now_iso(),
        "raw_match_evidence": {
            "queried_naics": queried_naics,
            "full_desc_loaded": False,
        },
    }


def search_sam_opportunities(
    *,
    naics_codes: list[str],
    today: date,
    lookback_days: int = 120,
    limit_per_naics: int = 25,
    timeout: int = 30,
) -> dict[str, Any]:
    api_key = os.getenv("SAM_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "missing_api_key",
            "notes": ["SAM_API_KEY is not set in the runtime environment."],
            "records": [],
            "queried_naics": [],
            "errors": [],
        }

    if not naics_codes:
        return {
            "status": "no_naics",
            "notes": ["Vendor profile does not contain confirmed or candidate NAICS codes."],
            "records": [],
            "queried_naics": [],
            "errors": [],
        }

    posted_from = _format_mmddyyyy(today - timedelta(days=lookback_days))
    posted_to = _format_mmddyyyy(today)
    deduped: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    queried: list[str] = []

    for naics in naics_codes:
        clean_naics = str(naics).strip()
        if not clean_naics:
            continue
        queried.append(clean_naics)
        query = urllib.parse.urlencode(
            {
                "ncode": clean_naics,
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "status": "active",
                "limit": limit_per_naics,
                "api_key": api_key,
            }
        )
        request = urllib.request.Request(
            f"{SEARCH_URL}?{query}",
            headers={"User-Agent": USER_AGENT},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"SAM search HTTP {exc.code} for NAICS {clean_naics}: {detail[:240]}")
            continue
        except Exception as exc:  # pragma: no cover - defensive fallback
            errors.append(f"SAM search error for NAICS {clean_naics}: {exc}")
            continue

        for record in _response_records(payload):
            normalized = _normalize_record(record, clean_naics)
            key = normalized["canonical_record_id"] or normalized["url"] or normalized["title"]
            if key:
                deduped[str(key)] = normalized

    status = "ok" if deduped else ("error" if errors else "empty")
    return {
        "status": status,
        "records": list(deduped.values()),
        "queried_naics": queried,
        "errors": errors,
        "notes": [
            f"Posted-date search window: {posted_from} to {posted_to}",
            "Results are retrieved first and then classified locally into timing windows.",
        ],
    }
