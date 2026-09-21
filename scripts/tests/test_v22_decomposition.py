"""Core-work separation and context-neutral roll-up; no business score targets."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, capture_fit as fit
from test_semantic_contract import fixture
from run_decomposer_core_work_probe import grade_fixture


class ProbeGraderTests(unittest.TestCase):
    def test_core_work_buried_in_timing_or_quotes_cannot_pass(self):
        expected = {"work_patterns": ["calibrat"], "forbidden_work_patterns": [], "required_condition_kinds": ["timing"]}
        parts = [{"kind": "timing", "text": "six hours after calibration", "evidence": []}]
        self.assertTrue(grade_fixture(expected, parts))
        parts.insert(0, {"kind": "work", "text": "Release instruments", "evidence": [{"quote": "after calibration"}]})
        self.assertTrue(grade_fixture(expected, parts))

    def test_adding_a_correct_task_cannot_hide_an_invented_third_party_task(self):
        expected = {"work_patterns": ["install.*light"], "forbidden_work_patterns": ["excavat"], "required_condition_kinds": []}
        parts = [{"kind": "work", "text": "Install lighting"}, {"kind": "work", "text": "Perform excavation"}]
        self.assertTrue(grade_fixture(expected, parts))

    def test_pure_context_control_rejects_any_generated_work(self):
        expected = {"work_patterns": [], "forbidden_work_patterns": ["."], "required_condition_kinds": []}
        self.assertFalse(grade_fixture(expected, [{"kind": "context", "text": "Await acceptance"}]))
        self.assertTrue(grade_fixture(expected, [{"kind": "work", "text": "Perform acceptance"}]))


class CoreWorkDecompositionTests(unittest.TestCase):
    def test_explicit_rule_is_part_of_effective_decomposer_prompt_once(self):
        self.assertEqual(c.DECOMPOSE_PROMPT.count(c.CORE_WORK_DECOMPOSITION_RULE), 1)
        self.assertIn("NEVER bury the core work", c.CORE_WORK_DECOMPOSITION_RULE)

    def test_decomposition_orders_work_before_conditions_without_inventing_parts(self):
        spans, requirement, _, _ = fixture()
        raw_parts = list(reversed(deepcopy(requirement["components"])))
        inventory = {"requirements": [deepcopy(requirement)]}
        result = c.apply_decomposition(inventory, {"requirements": {"R0": {
            "components": raw_parts, "logic": "all"}}}, spans)
        self.assertEqual(result["requirements"][0]["components"], requirement["components"])
        self.assertEqual(raw_parts[0]["kind"], "qualification")
        self.assertEqual(inventory["requirements"][0], requirement)

    def test_context_only_decomposition_does_not_invent_work(self):
        spans, requirement, _, _ = fixture()
        spans["D2:0"] = {"kind": "package", "source_id": "D2", "offset": 0,
                         "text": "No controlling document is established."}
        context = {"kind": "context", "text": "No controlling document is established.",
                   "evidence": [{"ref": "D2:0", "quote": "No controlling document is established."}]}
        # Structural ordering must not manufacture missing semantic information.
        result = c.apply_decomposition({"requirements": [requirement]}, {"requirements": {
            "R0": {"logic": "all", "components": [context]}}}, spans)
        self.assertEqual(result["requirements"][0]["components"], [context])


class ContextNeutralRollupTests(unittest.TestCase):
    def add_context(self, req, findings, count=1, kind="context"):
        req, findings = deepcopy(req), deepcopy(findings)
        for _ in range(count):
            key = f"K{len(req['components'])}"
            req["components"].append({"kind": kind, "text": "An administrative term remains a package fact.",
                                      "evidence": []})
            findings[key] = {"status": "not_applicable", "reason": "Not vendor performance.",
                             "supported_scope": "", "evidence": []}
        return req, findings

    def assert_same_credit(self, req, claim, findings, spans):
        before = c.aggregate_components(req, claim, findings, spans)
        for count in (1, 5, 25):
            changed, assessments = self.add_context(req, findings, count)
            after = c.aggregate_components(changed, claim, assessments, spans)
            for field in ("relationship", "coverage", "fit_label", "met_components", "missing_components", "unknown_components"):
                self.assertEqual(after[field], before[field], (field, count))
            self.assertEqual(fit._component_credit(after, changed), fit._component_credit(before, req))

    def test_partial_core_work_and_unknown_condition_are_not_diluted_by_context(self):
        spans, req, claim, findings = fixture()
        self.assert_same_credit(req, claim, findings, spans)
        self.assertEqual(c.aggregate_components(req, claim, findings, spans)["fit_label"], "Partial Fit")

    def test_complete_work_is_not_diluted_by_context(self):
        spans, req, claim, findings = fixture()
        req["components"] = req["components"][:1]
        findings = {"K0": findings["K0"]}
        self.assert_same_credit(req, claim, findings, spans)
        self.assertEqual(c.aggregate_components(req, claim, findings, spans)["fit_label"], "Supported Fit")

    def test_unknown_work_cannot_gain_credit_from_context(self):
        spans, req, claim, findings = fixture()
        findings["K0"] = {"status": "missing", "reason": "No performed work is identified.", "evidence": []}
        self.assert_same_credit(req, claim, findings, spans)
        self.assertEqual(c.aggregate_components(req, claim, findings, spans)["fit_label"], "Unknown")

    def test_unrelated_work_does_not_become_unknown_or_partial_with_context(self):
        spans, req, claim, findings = fixture()
        findings["K0"]["status"] = "unrelated"
        self.assert_same_credit(req, claim, findings, spans)
        self.assertEqual(c.aggregate_components(req, claim, findings, spans)["fit_label"], "Unrelated")

    def test_not_applicable_cannot_satisfy_an_alternative(self):
        spans, req, claim, findings = fixture()
        req["logic"] = "any"
        findings["K0"] = {"status": "missing", "reason": "No performed work is identified.", "evidence": []}
        self.assert_same_credit(req, claim, findings, spans)

    def test_pure_context_has_no_positive_credit(self):
        spans, req, claim, _ = fixture()
        req["components"] = []
        req, findings = self.add_context(req, {})
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual((result["fit_label"], result["met_components"], result["missing_components"]), ("Unknown", [], []))
        self.assertEqual(fit._component_credit(result, req), 0)

    def test_pricing_is_also_neutral_not_experience_credit(self):
        spans, req, claim, findings = fixture()
        before = c.aggregate_components(req, claim, findings, spans)
        changed, assessments = self.add_context(req, findings, kind="pricing")
        after = c.aggregate_components(changed, claim, assessments, spans)
        self.assertEqual(after["fit_label"], before["fit_label"])
        self.assertEqual(fit._component_credit(after, changed), fit._component_credit(before, req))

    def test_context_marked_missing_is_a_contract_error_not_a_score_penalty(self):
        spans, req, claim, findings = fixture()
        req, findings = self.add_context(req, findings)
        findings["K2"]["status"] = "missing"
        with self.assertRaisesRegex(ValueError, "Commercial/context"):
            c.aggregate_components(req, claim, findings, spans)

    def test_real_work_or_condition_cannot_be_discarded_as_not_applicable(self):
        spans, req, claim, findings = fixture()
        for key in ("K0", "K1"):
            invalid = deepcopy(findings)
            invalid[key] = {"status": "not_applicable", "reason": "Attempt to drop required scope.", "evidence": []}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "assessable"):
                c.aggregate_components(req, claim, invalid, spans)


if __name__ == "__main__":
    unittest.main()
