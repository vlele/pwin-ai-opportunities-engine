from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


from capture import capture_decision as decision  # noqa: E402


def main() -> int:
    failures: list[str] = []

    anchors = [
        "PWS 5.1 transition plan within 21 days",
        "Evaluation basis: Best Value",
    ]
    retained = decision._retain_rows_with_current_package_evidence(
        [
            {
                "text": "Show a concrete transition approach in the first 21 days.",
                "evidence_anchor": "PWS 5.1 transition plan within 21 days",
            }
        ],
        anchors,
        max_items=3,
        min_overlap=1,
    )
    if not retained or str(retained[0].get("evidence_anchor") or "").strip() != anchors[0]:
        failures.append("retain_valid_package_anchor")

    dropped = decision._retain_rows_with_current_package_evidence(
        [
            {
                "text": "Lead with generic innovation language.",
                "evidence_anchor": "Unrelated market blog note",
            }
        ],
        anchors,
        max_items=3,
        min_overlap=1,
    )
    if dropped:
        failures.append("drop_non_package_anchor")

    print(json.dumps({"status": "OK" if not failures else "FAIL", "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
