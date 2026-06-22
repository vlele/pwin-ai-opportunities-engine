from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from capture.evaluator_anxiety import build_evaluator_anxiety_model  # noqa: E402
from capture.solicitation_fact_model import build_solicitation_fact_model  # noqa: E402
from common.validation import validate_capture_brief_text  # noqa: E402


def _assert_case(case: dict[str, object]) -> dict[str, object]:
    name = str(case.get("name") or "unnamed")
    solicitation_facts = case.get("solicitation_facts", {}) if isinstance(case.get("solicitation_facts"), dict) else {}
    attachment_bundle = case.get("attachment_bundle", {}) if isinstance(case.get("attachment_bundle"), dict) else {}
    attachment_workstreams = case.get("attachment_workstreams", []) if isinstance(case.get("attachment_workstreams"), list) else []

    fact_model = build_solicitation_fact_model(
        solicitation_facts,
        attachment_bundle,
        attachment_workstreams=attachment_workstreams,
    )
    evaluator = build_evaluator_anxiety_model(
        fact_model,
        solicitation_facts=solicitation_facts,
        contract_type=str(solicitation_facts.get("contract_type") or ""),
        award_basis=str(solicitation_facts.get("evaluation_basis") or ""),
    )
    failures: list[str] = []
    if len(fact_model.get("promoted_fact_lines", []) or []) < 5:
        failures.append("promoted_fact_lines")
    if len(fact_model.get("staffing_roles", []) or []) < 2:
        failures.append("staffing_roles")
    if not fact_model.get("package_strength", {}).get("attachment_native_ready"):
        failures.append("attachment_native_ready")
    if len(evaluator.get("evaluator_anxiety_rows", []) or []) < 3:
        failures.append("evaluator_anxiety_rows")
    if len(evaluator.get("reasoned_win_theme_rows", []) or []) < 2:
        failures.append("reasoned_win_theme_rows")
    validation = validate_capture_brief_text(
        """
## 1. Executive Capture Judgment
## 2. Opportunity Snapshot
## 3. Pursuit Recommendation and Score
## 4. Evidence Ledger
## 5. Document Inventory and Missing Items
## 6. Customer and Mission Analysis
## 7. Funding and Spending Trend Analysis
## 8. Acquisition Strategy
## 9. Incumbent Analysis
## 10. Contracting Office and Stakeholder Map
## 11. Competitive Landscape
## 12. Partner and Teaming Analysis
## 13. Fit Against Our Capabilities and Past Performance
## 14. Subtle Signals and Capture Implications
## 15. Recommended Win Strategy
Show how the team will execute the primary requirement workstreams from day one, not just provide a labor category map.
## 16. Questions to Ask
## 17. Action Plan
## 18. Assumptions, Unknowns, and Confidence
""",
        {"solicitation_fact_model": fact_model},
    )
    if validation.get("evidence_alignment_ok", True):
        failures.append("validation_evidence_alignment")
    return {
        "name": name,
        "status": "ok" if not failures else "failed",
        "failures": failures,
        "summary": {
            "promoted_fact_lines": len(fact_model.get("promoted_fact_lines", []) or []),
            "staffing_roles": fact_model.get("staffing_roles", []),
            "attachment_native_ready": fact_model.get("package_strength", {}).get("attachment_native_ready"),
            "evaluator_anxiety_rows": len(evaluator.get("evaluator_anxiety_rows", []) or []),
        },
    }


def _assert_contamination_guard(deny_payload: dict[str, object]) -> dict[str, object]:
    failures: list[str] = []
    root = SCRIPT_ROOT / "capture"
    for filename, phrases in deny_payload.items():
        path = root / str(filename)
        if not path.exists():
            failures.append(f"missing::{filename}")
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in phrases if isinstance(phrases, list) else []:
            if str(phrase or "") and str(phrase) in text:
                failures.append(f"{filename}::{phrase}")
    return {
        "name": "contamination_guard",
        "status": "ok" if not failures else "failed",
        "failures": failures,
    }


def main() -> int:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "capture_fact_cases.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    results = [_assert_case(case) for case in payload.get("cases", [])]
    results.append(_assert_contamination_guard(payload.get("contamination_denylists", {})))
    failures = [result for result in results if result["status"] != "ok"]
    print(json.dumps({"status": "OK" if not failures else "FAIL", "results": results}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
