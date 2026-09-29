"""Offline contract audit by default; --live explicitly spends model API credits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from common.capture_clarification import analyze_understanding, build_packet, validate_assessment
from common.paths import utc_now_iso, write_json, write_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"created_at": utc_now_iso(), "live": args.live, "files": {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [ROOT / "scripts/common/capture_clarification.py", ROOT / "scripts/tests/test_capture_clarification.py",
                     ROOT / "scripts/tests/fixtures/capture_clarification_cases.json"]}}
    write_json(output / "manifest.json", manifest)
    if not args.live:
        results = []
        commands = [
            [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_capture_clarification.py", "-v"],
            [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_capture_decision_contract.py", "-v"],
            *[[sys.executable, f"scripts/tests/{name}.py"] for name in (
                "run_capture_reasoning_primary_tests", "run_openai_reasoning_tests", "run_capture_fact_model_tests",
                "run_capture_guardrail_tests", "run_capture_parser_tests", "run_capture_anchor_guardrail_tests",
                "run_capture_phrase_compaction_tests", "run_capture_hard_page_tests", "run_skill_contract_tests")],
        ]
        env = {key: value for key, value in os.environ.items() if key not in {
            "OPENAI_API_KEY", "SAM_API_KEY", "GOVTRIBE_MCP_API_KEY", "GOVWIN_API_KEY"}}
        for index, command in enumerate(commands, 1):
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            write_text(output / f"suite-{index:02}.log", result.stdout + result.stderr)
            results.append({"command": command, "exit_code": result.returncode})
        passed = all(row["exit_code"] == 0 for row in results)
        write_json(output / "results.json", {"status": "PASS" if passed else "FAIL", "live_model_tested": False, "suites": results})
        print(json.dumps({"status": "PASS" if passed else "FAIL", "suite_count": len(results), "output": str(output), "live_model_tested": False}))
        return 0 if passed else 1
    cases = json.loads((ROOT / "scripts/tests/fixtures/capture_clarification_cases.json").read_text())
    cases += [
        {"id": "defined_acronym_control", "documents": ["RMA means return merchandise authorization. Implement merchandise returns tracking."],
         "profile": {"core_competencies": ["Merchandise returns tracking"], "past_performance_highlights": ["Built merchandise returns tracking as prime in the preceding year."]}, "expected_status": "READY"},
        {"id": "explicit_poor_fit_control", "documents": ["Maintain industrial refrigeration machinery and repair failed compressors."],
         "profile": {"core_competencies": ["Consumer portrait photography only; no industrial machinery work"], "past_performance_highlights": ["Wedding portraits and restaurant menu photography."]}, "expected_status": "READY"},
        {"id": "missing_profile_control", "documents": ["Offerors must document their own delivery of calibration services and identify the performing legal entity."],
         "profile": {}, "expected_status": "NEEDS_CLARIFICATION"},
    ]
    results = []
    for case in cases:
        for repeat in range(1, args.repeats + 1):
            label = f"{case['id']}-{repeat}"
            packet = build_packet(profile=case["profile"], resolved={"title": "Synthetic procurement"}, notice_text="",
                                  attachment_bundle={"attachments_expected": True, "attachments": [
                                      {"filename": f"document-{i}.txt", "parser_status": "parsed_text", "structured_text_excerpt": text}
                                      for i, text in enumerate(case["documents"], 1)]})
            # Expected outcomes are deliberately excluded from the model request.
            raw = analyze_understanding(packet, [], {})
            assessed = validate_assessment(raw, packet)
            allowed = {case["expected_status"]}
            if case.get("kind") == "requirement_meaning":
                allowed.add("NEEDS_FORMAL_QA")
            passed = assessed["status"] in allowed
            row = {"case": case["id"], "repeat": repeat, "status": assessed["status"], "pass": passed,
                   "model_response_received": raw is not None, "questions": assessed["questions"]}
            write_json(output / (label + ".json"), {"packet": packet, "raw_model_response": raw, "validated": assessed, "acceptance": row})
            results.append(row)
            if raw is None:
                # Do not repeatedly spend/retry against an unavailable provider.
                write_json(output / "results.json", {"status": "BLOCKED", "runs": results, "reason": "Model unavailable; remaining samples not run."})
                print(json.dumps({"status": "BLOCKED", "output": str(output)}))
                return 2
    stability = {case["id"]: len({r["status"] for r in results if r["case"] == case["id"]}) == 1 for case in cases}
    passed = all(row["pass"] for row in results) and all(stability.values())
    write_json(output / "results.json", {"status": "PASS" if passed else "FAIL", "runs": results, "routing_stability": stability,
                                         "manual_review_required": "Assess question usefulness and semantic correctness; citation existence alone is insufficient."})
    print(json.dumps({"status": "PASS" if passed else "FAIL", "run_count": len(results), "output": str(output)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
