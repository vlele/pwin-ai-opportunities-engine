from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


from capture import fetch_notice_attachments as attachments  # noqa: E402


def main() -> int:
    failures: list[str] = []

    candidates = attachments._select_hard_page_candidates(
        [
            {"page_number": 1, "flags": ["toc_like"], "marker_hits": 3},
            {"page_number": 2, "flags": ["table_layout", "requirement_matrix_markers"], "marker_hits": 3},
            {"page_number": 3, "flags": ["thin_text"], "marker_hits": 1},
        ],
        max_pages=2,
    )
    if [int(item.get("page_number", 0) or 0) for item in candidates] != [2, 3]:
        failures.append("hard_page_candidate_ranking")

    base_structures = attachments._extract_text_structures(
        "1.3 Scope\nThe contractor shall maintain status reporting discipline.\n"
    )
    merged = attachments._merge_hard_page_structures(
        base_structures,
        [
            {
                "page_number": 4,
                "section_blocks": [
                    {
                        "title": "1.5 General Requirements",
                        "text": "1.5 General Requirements; The contractor shall submit a transition plan within 21 days.",
                        "source_text": "Page 4: 1.5 General Requirements; The contractor shall submit a transition plan within 21 days.",
                    }
                ],
                "table_rows": [
                    {
                        "line_index": 4001,
                        "page_number": 4,
                        "kind": "pricing",
                        "label": "CLIN 0001",
                        "text": "Page 4; CLIN 0001; Base services; 12 months; FFP",
                        "cells": ["CLIN 0001", "Base services", "12 months", "FFP"],
                    }
                ],
                "parse_warnings": ["vision_promoted_pricing_table"],
            }
        ],
    )
    if not any("Page 4:" in str(item.get("source_text", "")) for item in merged.get("section_blocks", []) if isinstance(item, dict)):
        failures.append("vision_section_block_merge")
    if not any("Page 4;" in str(item) for item in merged.get("structured_rows", []) if isinstance(item, str)):
        failures.append("vision_structured_row_merge")
    if not merged.get("pricing_rows"):
        failures.append("vision_pricing_rows_merge")
    if "vision_promoted_pricing_table" not in (merged.get("parse_warnings", []) or []):
        failures.append("vision_parse_warning_merge")

    print(json.dumps({"status": "OK" if not failures else "FAIL", "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
