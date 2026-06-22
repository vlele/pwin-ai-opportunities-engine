from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from capture import fetch_notice_attachments as attachments  # noqa: E402


def _assert_case(case: dict[str, object]) -> dict[str, object]:
    name = str(case.get("name") or "unnamed")
    text = str(case.get("text") or "")
    expect = case.get("expect", {}) if isinstance(case.get("expect"), dict) else {}
    structures = attachments._extract_text_structures(text)
    failures: list[str] = []

    if len(structures.get("section_blocks", []) or []) < int(expect.get("min_section_blocks", 0) or 0):
        failures.append("section_blocks")
    if len(structures.get("matrix_rows", []) or []) < int(expect.get("min_matrix_rows", 0) or 0):
        failures.append("matrix_rows")
    if len(structures.get("pricing_rows", []) or []) < int(expect.get("min_pricing_rows", 0) or 0):
        failures.append("pricing_rows")
    if len(structures.get("acceptance_rows", []) or []) < int(expect.get("min_acceptance_rows", 0) or 0):
        failures.append("acceptance_rows")
    if len(structures.get("table_blocks", []) or []) < int(expect.get("min_table_blocks", 0) or 0):
        failures.append("table_blocks")
    if len(structures.get("section_graph", []) or []) < int(expect.get("min_section_graph_nodes", 0) or 0):
        failures.append("section_graph")
    if len(structures.get("parse_warnings", []) or []) > int(expect.get("max_parse_warnings", 999) or 999):
        failures.append("parse_warnings")

    return {
        "name": name,
        "status": "ok" if not failures else "failed",
        "failures": failures,
        "summary": {
            "section_blocks": len(structures.get("section_blocks", []) or []),
            "matrix_rows": len(structures.get("matrix_rows", []) or []),
            "pricing_rows": len(structures.get("pricing_rows", []) or []),
            "acceptance_rows": len(structures.get("acceptance_rows", []) or []),
            "table_blocks": len(structures.get("table_blocks", []) or []),
            "section_graph_nodes": len(structures.get("section_graph", []) or []),
            "parse_warnings": structures.get("parse_warnings", []),
        },
    }


def main() -> int:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "capture_parser_cases.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    results = [_assert_case(case) for case in payload.get("cases", [])]
    failures = [result for result in results if result["status"] != "ok"]
    print(
        json.dumps(
            {
                "status": "OK" if not failures else "FAIL",
                "results": results,
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
