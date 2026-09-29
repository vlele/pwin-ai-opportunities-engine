"""Preserve supported pricing structures and their source statements."""
from __future__ import annotations

import re

TYPE_PATTERNS = (
    (r"\bfirm[- ]fixed\s+price\b|\bFFP\b", "Firm Fixed Price"),
    (r"\blabor[- ]hour\b|\bLH\b", "Labor Hour"),
    (r"\btime\s*(?:and|&)\s*materials\b|\bT\s*&\s*M\b", "Time and Materials"),
    (r"\bcost[- ]plus[- ]fixed[- ]fee\b|\bCPFF\b", "Cost Plus Fixed Fee"),
    (r"\bcost[- ]reimbursement\b", "Cost Reimbursement"),
)


def extract_contract_structure(documents: list[dict]) -> dict:
    rows = []
    for document in documents:
        # Keep source page labels when present; do not treat clause definitions as order facts.
        page = None
        for fragment in re.split(r"(?<=[.!?])\s+|\n", str(document.get("text") or "")):
            page_match = re.search(r"\bPage\s+(\d+)\s*:", fragment, re.I)
            if page_match:
                page = int(page_match.group(1))
            found = [label for pattern, label in TYPE_PATTERNS if re.search(pattern, fragment, re.I)]
            if not found:
                continue
            if re.search(r"\bFAR\b|\bclause\b|when applicable|if applicable|may be used|definition", fragment, re.I):
                continue
            explicit = re.search(r"(?:this|the|a|an)\s+(?:task\s+)?(?:order|contract)|contract\s+type|type\s+of\s+contract|line\s+items|\bCLINs?\b|\bLINs\b|\btriad\b|\bFFP\s+order\b|firm.fixed.price\s+contract", fragment, re.I)
            if explicit:
                rows.append({"types": found, "source": document.get("source", "current package"), "page": page, "quote": fragment.strip(), "scope": "line_item" if re.search(r"\bCLIN|line\s+item|\bLINs", fragment, re.I) else "order"})
    types = [label for _, label in TYPE_PATTERNS if any(label in row["types"] for row in rows)]
    declarations = {tuple(row["types"]) for row in rows if row["scope"] == "order"}
    conflict = len(declarations) > 1 and not any(set(types) <= set(d) for d in declarations)
    label = " / ".join(types)
    if len(types) > 1:
        label = ("Unresolved contract-type conflict: " if conflict else "Mixed: ") + label
    return {"types": types, "label": label, "status": "conflict" if conflict else "mixed" if len(types) > 1 else "single" if types else "unknown", "evidence": rows}
