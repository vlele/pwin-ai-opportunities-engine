"""A passing unit suite or isolated auditor cannot approve a release."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_release_readiness import REQUIRED_OFFLINE, evaluate, model_binding_errors


def inputs():
    def runs(prefix, count):
        grades = [{"case": f"{prefix}{i:02d}", "repeat": j, "status": "READY", "pass": True, "errors": []}
                  for i in range(1, count + 1) for j in range(1, 4)]
        return {"scorecard_version": 4, "expected_runs": len(grades), "grades": grades}
    return {"known": runs("K", 8), "heldout": runs("U", 12),
            "audit": {"runs": 57, "passes": 57, "false_accepts": 0, "false_rejects": 0, "technical_failures": 0},
            "offline": [{"suite": suite, "exit_code": 0} for suite in REQUIRED_OFFLINE],
            "review": {"critical_findings": [], "all_samples_reviewed": True, "long_package_integration_passed": True,
                       "downstream_credit_boundary_passed": True, "repository_review_passed": True},
            "integrity_errors": []}


class ReleaseTests(unittest.TestCase):
    def test_different_model_or_effort_cannot_be_combined_into_one_release(self):
        plan = {"model_settings": {"model": "test-snapshot", "reasoning_effort": "low"}}
        audit = {"model": "test-snapshot", "effort": "low"}
        self.assertEqual(model_binding_errors(plan, plan, audit), [])
        self.assertTrue(model_binding_errors(plan, {"model_settings": {"model": "other", "reasoning_effort": "low"}}, audit))
        self.assertTrue(model_binding_errors(plan, plan, {**audit, "effort": "high"}))
        self.assertTrue(model_binding_errors({}, {}, {}))

    def test_all_evidence_required(self):
        self.assertTrue(evaluate(**inputs())["ready"])
        for key in ("heldout", "audit", "offline", "review"):
            value = inputs()
            value[key] = None
            self.assertFalse(evaluate(**value)["ready"])

    def test_isolated_auditor_success_cannot_hide_semantic_failure(self):
        value = inputs()
        value["known"]["grades"][0].update(pass_=False)
        value["known"]["grades"][0]["pass"] = False
        value["known"]["grades"][0]["errors"] = ["wrong_fit"]
        self.assertFalse(evaluate(**value)["ready"])

    def test_duplicate_best_runs_cannot_replace_missing_repeats(self):
        value = inputs()
        value["known"]["grades"][-1] = deepcopy(value["known"]["grades"][0])
        self.assertFalse(evaluate(**value)["ready"])

    def test_technical_blocks_do_not_count_as_success(self):
        value = inputs()
        for r in value["known"]["grades"][:2]:
            r["status"] = "TECHNICAL_BLOCKED"
            r["pass"] = False
            r["errors"] = ["technical_block"]
        self.assertFalse(evaluate(**value)["ready"])

    def test_critical_review_or_hash_mismatch_cannot_be_waived(self):
        value = inputs()
        value["review"]["critical_findings"] = ["Unsupported task claim"]
        self.assertFalse(evaluate(**value)["ready"])
        value = inputs()
        value["integrity_errors"] = ["Runtime changed after testing"]
        self.assertFalse(evaluate(**value)["ready"])


if __name__ == "__main__":
    unittest.main()
