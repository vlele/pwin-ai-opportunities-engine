from __future__ import annotations

import re
from typing import Any


PLACEHOLDER_RE = re.compile(r"{{[^{}]+}}")
CAPTURE_HEADINGS = [
    "## Current Research Limits",
    "## Executive Brief",
    "## Objective Matrix",
    "## Stakeholder and People Map",
    "## Budget, Funding, and Spending Signals",
    "## Related Procurements and Vehicle Signals",
    "## Competitive Landscape",
    "## Public Discourse and Market Signals",
    "## Recommended Next Research Moves",
    "## Action Items (Next 10 Days)",
    "## Assumptions to Validate",
    "## Evidence Annex",
]


def contains_placeholders(text: str) -> bool:
    return bool(PLACEHOLDER_RE.search(text))


def missing_capture_sections(text: str) -> list[str]:
    return [heading for heading in CAPTURE_HEADINGS if heading not in text]


def validate_capture_brief_text(text: str) -> dict[str, Any]:
    missing = missing_capture_sections(text)
    return {
        "contains_placeholders": contains_placeholders(text),
        "missing_sections": missing,
        "all_required_sections_present": not missing,
    }


def validate_digest_text(text: str) -> dict[str, Any]:
    entry_ids = re.findall(r"(?m)^###\s+([AWESN]\d+)\s+-\s+", text)
    return {
        "contains_placeholders": contains_placeholders(text),
        "stable_id_count": len(set(entry_ids)),
        "entry_ids": sorted(set(entry_ids)),
    }
