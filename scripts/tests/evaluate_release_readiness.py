"""Fail-closed release evidence aggregation. This tool never commits or pushes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

REQUIRED_OFFLINE = {"unittest", "run_bootstrap_tests", "run_capture_anchor_guardrail_tests", "run_capture_fact_model_tests",
                    "run_capture_guardrail_tests", "run_capture_hard_page_tests", "run_capture_parser_tests",
                    "run_capture_phrase_compaction_tests", "run_capture_reasoning_primary_tests", "run_commercial_intel_tests",
                    "run_gold_bucket_tests", "run_intel_provider_tests", "run_openai_reasoning_tests", "run_render_digest_tests",
                    "run_scan_bootstrap_guidance_tests", "run_skill_contract_tests", "run_source_policy_tests", "diff-check"}


def model_binding_errors(known_plan, heldout_plan, audit_plan):
    expected = known_plan.get("model_settings", {})
    audit_settings = {"model": audit_plan.get("model"), "reasoning_effort": audit_plan.get("effort")}
    if not expected.get("model") or not expected.get("reasoning_effort") or expected != heldout_plan.get("model_settings") or expected != audit_settings:
        return ["Known, held-out and auditor results must use the same explicit model and effort"]
    return []

def evaluate(*, known, heldout, audit, offline, review, integrity_errors):
    errors = list(integrity_errors)
    for label, value, expected_cases in (("known", known, 8), ("heldout", heldout, 12)):
        if not isinstance(value, dict) or value.get("scorecard_version") != 4:
            errors.append(f"Missing/version-mismatched {label} scorecard")
            continue
        rows = value.get("grades", [])
        keys = {(r.get("case"), r.get("repeat")) for r in rows}
        cases = Counter(r.get("case") for r in rows)
        if len(rows) != expected_cases * 3 or len(keys) != len(rows) or len(cases) != expected_cases or set(cases.values()) != {3}:
            errors.append(f"{label}: incomplete/duplicate three-repeat corpus")
        if any(r.get("repeat") not in {1, 2, 3} for r in rows):
            errors.append(f"{label}: invalid repeat IDs")
        usable = sum(r.get("status") in {"READY", "NEEDS_CLARIFICATION", "NEEDS_FORMAL_QA"} for r in rows)
        if not rows or usable / len(rows) < .95:
            errors.append(f"{label}: usable checkpoints below 95 percent")
        if any(not r.get("pass") and r.get("errors") != ["technical_block"] for r in rows):
            errors.append(f"{label}: semantic/routing/retention failures")
    if not isinstance(audit, dict) or audit.get("runs", 0) < 57 or audit.get("passes") != audit.get("runs") or any(audit.get(k, 1) for k in ("false_accepts", "false_rejects", "technical_failures")):
        errors.append("Auditor negative/positive controls incomplete or failed")
    if not isinstance(offline, list) or not REQUIRED_OFFLINE.issubset({r.get("suite") for r in offline}) or any(r.get("exit_code") != 0 for r in offline):
        errors.append("Offline suites incomplete or failed")
    required = ("all_samples_reviewed", "long_package_integration_passed", "downstream_credit_boundary_passed", "repository_review_passed")
    if not isinstance(review, dict) or review.get("critical_findings") != [] or any(review.get(k) is not True for k in required):
        errors.append("Manual semantic/integration/repository review incomplete or has critical findings")
    return {"ready": not errors, "verdict": "READY_FOR_REVIEWED_COMMIT" if not errors else "NO_GO", "errors": errors,
            "scope": "Understanding/clarification contract and tested integration; not universal capture accuracy."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--known", default="mini-low-known")
    p.add_argument("--heldout", default="mini-low-heldout")
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--offline", type=Path, required=True)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    paths = {"known": args.candidate / args.known / "grades.json", "heldout": args.candidate / args.heldout / "grades.json",
             "audit": args.audit / "summary.json", "offline": args.offline / "results.json", "review": args.review}
    values, hashes, integrity = {}, {}, []
    for key, path in paths.items():
        try:
            content = path.read_bytes()
            values[key] = json.loads(content)
            hashes[key] = hashlib.sha256(content).hexdigest()
        except (OSError, ValueError):
            values[key] = None
    from run_semantic_classification_benchmark import verify_frozen, ROOT, digest
    try:
        verify_frozen(args.candidate)
        frozen_files = {p.relative_to(args.candidate / "runtime-scripts") for p in (args.candidate / "runtime-scripts").rglob("*.py")}
        current_files = {p.relative_to(ROOT / "scripts") for p in (ROOT / "scripts").rglob("*.py")}
        if frozen_files != current_files:
            integrity.append("Python file inventory differs from the tested candidate")
        for file in (args.candidate / "runtime-scripts").rglob("*.py"):
            current = ROOT / "scripts" / file.relative_to(args.candidate / "runtime-scripts")
            if not current.exists() or digest(file) != digest(current):
                integrity.append("Runtime differs from candidate: " + str(current.relative_to(ROOT)))
        known_plan = json.loads((args.candidate / args.known / "plan.json").read_text())
        heldout_plan = json.loads((args.candidate / args.heldout / "plan.json").read_text())
        audit_plan = json.loads((args.audit / "plan.json").read_text())
        integrity.extend(model_binding_errors(known_plan, heldout_plan, audit_plan))
        if audit_plan.get("implementation_sha256") != digest(ROOT / "scripts/common/semantic_plan.py"):
            integrity.append("Auditor results were produced by a different implementation")
        if audit_plan.get("fixture_sha256") != digest(args.audit / "fixtures.json"):
            integrity.append("Auditor fixture changed after execution")
        offline_hashes = json.loads((args.offline / "runtime-hashes.json").read_text())
        current_hashes = {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts").rglob("*.py")}
        if offline_hashes != current_hashes:
            integrity.append("Offline results do not match the current runtime")
    except (ValueError, OSError) as error:
        integrity.append("Frozen input/runtime verification failed: " + str(error))
    review = values["review"]
    if not isinstance(review, dict) or review.get("artifact_hashes") != {k: v for k, v in hashes.items() if k != "review"}:
        integrity.append("Review is not bound to these exact result artifacts")
    report = {**evaluate(**values, integrity_errors=integrity), "artifact_hashes": hashes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
