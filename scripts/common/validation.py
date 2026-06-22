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
GENERIC_STRATEGY_FALLBACKS = [
    "show how the team will execute the primary requirement workstreams from day one",
    "tie past performance to the visible workstreams surfaced in the attachments",
    "present a low-disruption transition story that directly answers continuity concerns",
    "a delivery story that links startup readiness, qa/qc rigor, reporting discipline, and workstream throughput in one narrative",
    "compliance, security, or audit-ready delivery appears important",
    "continuity and transition credibility matter because",
    "reporting discipline matters because",
    "quality-control discipline matters because",
    "access and handling readiness matter because",
    "package quality and review throughput matter because",
    "show that the solution is governable in a federal environment",
    "requirement throughput with documented discipline",
    "no-drama access and security compliance",
]


def contains_placeholders(text: str) -> bool:
    return bool(PLACEHOLDER_RE.search(text))


def missing_capture_sections(text: str) -> list[str]:
    return [heading for heading in CAPTURE_HEADINGS if heading not in text]


def validate_capture_brief_text(text: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = missing_capture_sections(text)
    lower = text.lower()
    evidence = evidence if isinstance(evidence, dict) else {}
    solicitation_fact_model = evidence.get("solicitation_fact_model", {}) if isinstance(evidence.get("solicitation_fact_model"), dict) else {}
    package_strength = solicitation_fact_model.get("package_strength", {}) if isinstance(solicitation_fact_model.get("package_strength"), dict) else {}
    promoted_fact_lines = solicitation_fact_model.get("promoted_fact_lines", []) if isinstance(solicitation_fact_model.get("promoted_fact_lines"), list) else []
    attachment_native_ready = bool(package_strength.get("attachment_native_ready"))
    generic_strategy_hits = [phrase for phrase in GENERIC_STRATEGY_FALLBACKS if phrase in lower]
    strong_attachment_case = attachment_native_ready or len(promoted_fact_lines) >= 4
    evidence_alignment_ok = not (strong_attachment_case and generic_strategy_hits)
    return {
        "contains_placeholders": contains_placeholders(text),
        "missing_sections": missing,
        "all_required_sections_present": not missing,
        "generic_strategy_hits": generic_strategy_hits,
        "evidence_alignment_ok": evidence_alignment_ok,
    }


def validate_digest_text(text: str) -> dict[str, Any]:
    entry_ids = re.findall(r"(?m)^###\s+([AWESN]\d+)\s+-\s+", text)
    return {
        "contains_placeholders": contains_placeholders(text),
        "stable_id_count": len(set(entry_ids)),
        "entry_ids": sorted(set(entry_ids)),
    }
