import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_semantic_classification_benchmark import FIXTURE, grade_case


class SemanticScorecardTests(unittest.TestCase):
    def setUp(self):
        self.case = json.loads(FIXTURE.read_text())["cases"][0]
        self.state = {"status": "READY", "questions": [], "open_gaps": [
            {"kind": "vendor_experience", "relevance": "unrelated", "ambiguity": "clear", "verification_status": "unverified"}],
            "interpretation": [], "understanding_audit": {}}

    def test_ready_does_not_equal_semantic_pass(self):
        self.state["open_gaps"][0]["relevance"] = "direct"
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_empty_findings_do_not_get_credit(self):
        self.state["open_gaps"] = []
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_technical_block_is_not_a_semantic_success(self):
        self.state["status"] = "TECHNICAL_BLOCKED"
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_label_pass_still_requires_semantic_review(self):
        result = grade_case(self.case, self.state)
        self.assertTrue(result["pass"])
        self.assertTrue(result["manual_review_required"])

    def test_expected_question_is_checked_not_only_status(self):
        case = copy.deepcopy(self.case)
        case.update(statuses=["NEEDS_CLARIFICATION"], question_kinds=["vendor_role"])
        self.state["status"] = "NEEDS_CLARIFICATION"
        self.assertFalse(grade_case(case, self.state)["pass"])

    def test_missing_pricing_fact_is_a_failure(self):
        self.case["facts"] = ["labor.hour"]
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_unrelated_role_or_missing_recency_does_not_inherit_work_labels(self):
        self.state["open_gaps"].extend([
            {"kind": "vendor_role", "claim": {"subject": "role_preference"}, "relevance": "not_applicable", "ambiguity": "clear", "verification_status": "unverified"},
            {"kind": "vendor_recency", "claim": {"subject": "recency"}, "relevance": "unknown", "ambiguity": "missing", "verification_status": "unknown"}])
        self.assertTrue(grade_case(self.case, self.state)["pass"])

    def test_secondary_preference_cannot_replace_performed_work_classification(self):
        self.state["open_gaps"] = [{"kind": "vendor_role", "claim": {"subject": "role_preference"}, "relevance": "not_applicable", "ambiguity": "clear", "verification_status": "unverified"}]
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_absent_coverage_does_not_erase_a_known_work_classification(self):
        self.state["open_gaps"].append({"claim": {"subject": "performed_work", "basis": "not_supplied"},
                                        "relevance": "unknown", "ambiguity": "missing", "verification_status": "unknown"})
        self.assertTrue(grade_case(self.case, self.state)["pass"])
        self.state["open_gaps"][-1]["relevance"] = "direct"
        self.assertFalse(grade_case(self.case, self.state)["pass"])

    def test_a_separate_question_cannot_stand_in_for_a_work_classification(self):
        self.state["open_gaps"] = []
        self.state["questions"] = [{"record_type": "question", "kind": "vendor_experience", "relevance": "unrelated"}]
        self.assertFalse(grade_case(self.case, self.state)["pass"])


if __name__ == "__main__":
    unittest.main()
