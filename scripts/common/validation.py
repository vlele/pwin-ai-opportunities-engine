from __future__ import annotations

import re
from typing import Any


PLACEHOLDER_RE = re.compile(r"{{[^{}]+}}")
CAPTURE_HEADINGS = [
    "## 1. Executive Capture Judgment",
    "## 2. Opportunity Snapshot",
    "## 3. Pursuit Recommendation and Score",
    "## 4. Evidence Ledger",
    "## 5. Document Inventory and Missing Items",
    "## 6. Customer and Mission Analysis",
    "## 7. Funding and Spending Trend Analysis",
    "## 8. Acquisition Strategy",
    "## 9. Incumbent Analysis",
    "## 10. Contracting Office and Stakeholder Map",
    "## 11. Competitive Landscape",
    "## 12. Partner and Teaming Analysis",
    "## 13. Fit Against Our Capabilities and Past Performance",
    "## 14. Subtle Signals and Capture Implications",
    "## 15. Recommended Win Strategy",
    "## 16. Questions to Ask",
    "## 17. Action Plan",
    "## 18. Assumptions, Unknowns, and Confidence",
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
