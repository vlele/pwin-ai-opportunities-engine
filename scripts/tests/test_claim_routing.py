"""Claim facts and clarification hypotheses have separate contracts.

These tests check enforcement with supplied model outputs, not model accuracy.
No procurement-family keywords are used by the implementation.
"""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u
from common import capture_clarification as gate
from test_capture_understanding import assessment, issue, packet, task_alignment, supported_audit
try:
    import jsonschema
except ImportError:
    jsonschema = None


def resolution(basis="meaning", *, refs=None):
    return {"basis": basis, "unresolved": "Which tasks the reported reference actually covered.",
            "refs": refs or ["V1:0", "D1:0"],
            "alternatives": [
                {"answer": "Own staff performed the required task", "decision_effect": "Reported task overlap can be credited, still unverified."},
                {"answer": "Only transport or administrative assistance", "decision_effect": "No direct performance of the required task is established."},
            ]}


class ClaimRoutingTests(unittest.TestCase):
    def setUp(self):
        self.packet = packet()
        self.spans = u.build_spans(self.packet)
        self.raw = assessment(self.spans)
        self.row = issue(self.spans, "missing")
        self.row.update(action="record_gap", question="What tasks did your staff perform on this reference?")
        self.row["clarification"] = resolution()
        self.raw["uncertainties"] = [self.row]

    def render(self):
        return u.render_assessment(self.raw, self.spans)

    def test_meaning_question_is_not_silenced_by_missing_label_or_gap_action(self):
        result = self.render()["uncertainties"][0]
        self.assertTrue(result["blocking"])
        self.assertEqual(result["action"], "ask")
        self.assertEqual(result["options"], [a["answer"] for a in self.row["clarification"]["alternatives"]])
        self.assertEqual(result["routing_reason"], "meaning")
        self.assertEqual(gate.validate_assessment(self.render(), self.packet)["status"], "NEEDS_CLARIFICATION")

    def test_material_meaning_without_question_cannot_be_ready(self):
        self.row.update(question="", options=[])
        with self.assertRaisesRegex(ValueError, "question"):
            self.render()

    def test_uncertainty_without_explicit_resolution_basis_is_invalid(self):
        del self.row["clarification"]
        with self.assertRaisesRegex(ValueError, "clarification"):
            self.render()

    def test_alternatives_need_distinct_decision_effects(self):
        alternatives = self.row["clarification"]["alternatives"]
        alternatives[1]["decision_effect"] = alternatives[0]["decision_effect"]
        with self.assertRaisesRegex(ValueError, "decision effects"):
            self.render()

    def test_missing_information_cannot_be_asserted_even_in_question(self):
        self.row["claim"].update(basis="not_supplied", statement="The vendor performed the required work.", refs=[])
        self.row.update(verification_status="unknown")
        with self.assertRaisesRegex(ValueError, "not_supplied"):
            self.render()

    @unittest.skipIf(jsonschema is None, "Optional jsonschema package is not installed")
    def test_unsupplied_claim_schema_prevents_positive_statement_before_generation(self):
        self.row["claim"].update(basis="not_supplied", statement="", refs=[])
        self.row.update(verification_status="unknown")
        schema = u.source_schema(u.ASSESSMENT_SCHEMA, self.spans)
        jsonschema.validate(self.raw, schema)
        self.row["claim"]["statement"] = "The vendor did the work."
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.raw, schema)

    def test_extraction_prompt_does_not_inherit_vendor_classification_contract(self):
        self.assertFalse(u.EXTRACT_PROMPT.startswith(u.BASE_PROMPT))
        self.assertNotIn("Always include at least one performed_work finding", u.EXTRACT_PROMPT)

    @unittest.skipIf(jsonschema is None, "Optional jsonschema package is not installed")
    def test_generation_schema_prevents_gap_hypotheses_and_no_claim_on_reported_work(self):
        self.row.update(ambiguity="clear", action="record_gap", question="", options=[])
        self.row["clarification"] = {"basis": "settled", "unresolved": "", "refs": [], "alternatives": []}
        schema = u.source_schema(u.ASSESSMENT_SCHEMA, self.spans)
        jsonschema.validate(self.raw, schema)
        for field, invalid in (("basis", "no_claim"), ("unresolved", "An actual question"),
                               ("refs", ["V1:0"]), ("alternatives", resolution()["alternatives"])):
            raw = copy.deepcopy(self.raw)
            raw["uncertainties"][0]["clarification"][field] = invalid
            with self.subTest(field=field), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(raw, schema)

    def test_entity_question_is_not_an_assertion_of_common_ownership(self):
        self.packet["sources"]["V1"]["text"] = "The profile names Sample East LLC. Its reference lists Sample Holdings LLC as performer; their relationship and actual tasks are not supplied."
        self.spans = u.build_spans(self.packet)
        identity = copy.deepcopy(self.row)
        identity.update(kind="company_identity", ambiguity="ambiguous", relevance="unknown",
                        question="Which entity performed the reference and what was the offeror's own role?")
        identity["task_alignment"] = task_alignment("not_applicable")
        identity["claim"].update(subject="identity", statement=self.spans["V1:0"]["text"])
        identity["clarification"] = resolution("attribution")
        identity["clarification"].update(unresolved="Whether the named offeror performed any of the referenced work.")
        identity["clarification"]["alternatives"] = [
            {"answer": "The named offeror performed the work", "decision_effect": "Its reported tasks can be assessed for experience credit."},
            {"answer": "Another entity performed it without an attributable offeror role", "decision_effect": "No offeror experience can be credited from this reference."},
        ]
        missing_work = copy.deepcopy(self.row)
        missing_work["claim"].update(statement="", basis="not_supplied", refs=[])
        missing_work.update(verification_status="unknown", question="", options=[], ambiguity="missing")
        missing_work["clarification"] = {"basis": "no_claim", "unresolved": "", "refs": [], "alternatives": []}
        self.raw["uncertainties"] = [identity, missing_work]
        rendered = self.render()
        targets = u.claim_targets(self.raw, self.spans)
        self.assertTrue(u.validate_claim_audit(supported_audit(u.audit_components(targets)), targets, self.spans)["passed"])
        state = gate.validate_assessment(rendered, self.packet)
        self.assertEqual(state["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["open_gaps"][0]["relevance"], "unknown")

    def test_entity_question_does_not_replace_work_classification(self):
        self.row.update(kind="company_identity")
        self.row["claim"]["subject"] = "identity"
        self.row["task_alignment"] = task_alignment("not_applicable")
        with self.assertRaisesRegex(ValueError, "performed_work"):
            self.render()

    def test_clarification_evidence_must_be_in_the_audited_target(self):
        self.row["refs"] = ["D1:0", "V1:0"]
        self.row["clarification"]["refs"].append("D2:0")
        self.assertIn("D2:0", self.render()["uncertainties"][0]["refs"])
        self.assertIn("D2:0", u.claim_targets(self.raw, self.spans)[1]["source_spans"])

    def test_question_does_not_exempt_unsupported_claim_from_audit(self):
        self.row["clarification"] = resolution("attribution")
        targets = u.claim_targets(self.raw, self.spans)
        audit = supported_audit(u.audit_components(targets))
        audit["checks"]["F1.assertion"].update(verdict="unsupported", reason="Entity equivalence was never asserted in the source.")
        self.assertFalse(u.validate_claim_audit(audit, targets, self.spans)["passed"])

    def test_audit_trail_labels_alternatives_as_conditional_not_claimed_work(self):
        with tempfile.TemporaryDirectory() as folder:
            state = gate.checkpoint(Path(folder), self.packet, analyze=lambda *args: self.render())
            review = Path(state["review_path"]).read_text()
            self.assertIn("Question basis: meaning", review)
            self.assertIn("conditional effects (not established facts)", review)
            self.assertIn(self.row["clarification"]["alternatives"][0]["decision_effect"], review)

    def test_absent_experience_is_a_gap_not_a_rescue_question(self):
        self.row["claim"].update(statement="", basis="not_supplied", refs=[])
        self.row.update(verification_status="unknown", question="", options=[])
        self.row["clarification"] = {"basis": "no_claim", "unresolved": "", "refs": [], "alternatives": []}
        self.assertFalse(self.render()["uncertainties"][0]["blocking"])

    def test_verification_only_and_extra_detail_remain_gaps(self):
        for basis in ("verification_only", "additional_detail"):
            with self.subTest(basis=basis):
                self.row.update(ambiguity="clear", relevance="direct", action="record_gap", question="", options=[])
                self.row["clarification"] = {"basis": basis, "unresolved": "Independent proof or extra coverage is not supplied.",
                                             "refs": ["V1:0"], "alternatives": []}
                self.assertFalse(self.render()["uncertainties"][0]["blocking"])

    def test_material_ambiguity_cannot_hide_in_additional_detail(self):
        self.row.update(ambiguity="ambiguous", action="record_gap", question="", options=[])
        self.row["clarification"] = {"basis": "additional_detail", "unresolved": "Uncertain claimed role.", "refs": ["V1:0"], "alternatives": []}
        with self.assertRaisesRegex(ValueError, "clarification"):
            self.render()


if __name__ == "__main__":
    unittest.main()
