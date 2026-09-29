"""Contract tests for separate assertion, comparison and question audits."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u
from test_capture_understanding import assessment, issue, packet
from test_claim_routing import resolution


def alignment(relationship="same_task", coverage="partial"):
    return {"relationship": relationship, "coverage": coverage,
            "shared_work": "Installation and repair of the named equipment." if relationship in {"same_task", "applicable_different_task"} else "",
            "transfer_basis": "A different installation method has an explicitly applicable procedure." if relationship == "applicable_different_task" else ""}


class AuditFacetTests(unittest.TestCase):
    def setUp(self):
        self.spans = u.build_spans(packet())
        self.raw = assessment(self.spans)
        self.row = issue(self.spans, "clear", relevance="direct")
        self.row["task_alignment"] = alignment()
        self.row.update(action="record_gap", question="", options=[])
        self.raw["uncertainties"] = [self.row]

    def test_missing_summary_refs_are_unioned_without_inventing_evidence(self):
        self.row["refs"] = ["V1:0"]
        rendered = u.render_assessment(self.raw, self.spans)
        row = rendered["uncertainties"][0]
        self.assertEqual(set(row["refs"]), {"V1:0", "D1:0"})
        self.assertEqual(self.row["refs"], ["V1:0"])
        self.assertTrue(rendered["understanding_audit"]["citation_assemblies"])

    def test_unknown_subreference_is_never_repaired(self):
        self.row["comparison"]["refs"] = ["fabricated"]
        with self.assertRaisesRegex(ValueError, "Unknown source"):
            u.render_assessment(self.raw, self.spans)

    def test_requirement_reference_schema_excludes_profile_sources(self):
        schema = u.source_schema(u.ASSESSMENT_SCHEMA, self.spans)
        for branch in schema["properties"]["uncertainties"]["items"]["anyOf"]:
            refs = branch["properties"]["comparison"]["properties"]["refs"]
            self.assertEqual(refs["items"], {"$ref": "#/$defs/PackageRef"})

    def test_direct_partial_match_is_not_downgraded_for_uncovered_tasks(self):
        self.row["relevance"] = "transferable"
        result = u.render_assessment(self.raw, self.spans)
        self.assertEqual(result["uncertainties"][0]["relevance"], "direct")
        self.assertEqual(result["uncertainties"][0]["task_alignment"]["coverage"], "partial")
        self.assertEqual(self.row["relevance"], "transferable")
        self.assertTrue(result["understanding_audit"]["classification_projections"])

    def test_unknown_tasks_cannot_gain_transfer_credit(self):
        self.row["relevance"] = "transferable"
        self.row["task_alignment"] = alignment("unknown", "unknown")
        self.assertEqual(u.render_assessment(self.raw, self.spans)["uncertainties"][0]["relevance"], "unknown")

    def test_transfer_requires_a_concrete_basis(self):
        self.row["task_alignment"] = alignment("applicable_different_task", "partial")
        self.row["task_alignment"]["transfer_basis"] = ""
        with self.assertRaisesRegex(ValueError, "transfer_basis"):
            u.render_assessment(self.raw, self.spans)

    def test_audit_components_keep_question_hypotheses_out_of_assertion(self):
        self.row.update(ambiguity="ambiguous", relevance="unknown", question="What was the vendor's own role?")
        self.row["task_alignment"] = alignment("unknown", "unknown")
        self.row["clarification"] = resolution("attribution")
        targets = u.claim_targets(self.raw, self.spans)
        components = u.audit_components(targets)
        assertion = next(c for c in components if c["target_id"] == "F1" and c["facet"] == "assertion")
        question = next(c for c in components if c["target_id"] == "F1" and c["facet"] == "clarification")
        self.assertNotIn("alternatives", str(assertion))
        self.assertEqual(set(assertion["source_spans"]), {"V1:0"})
        self.assertIn("alternatives", str(question))

    def test_unanswered_but_justified_question_does_not_need_established_answer(self):
        self.row.update(ambiguity="ambiguous", relevance="unknown", question="What work did this entity actually perform?")
        self.row["task_alignment"] = alignment("unknown", "unknown")
        self.row["clarification"] = resolution("attribution")
        targets = u.claim_targets(self.raw, self.spans)
        response = {"checks": {c["id"]: {"verdict": "supported", "reason": "The cited facts justify the question, not a particular answer."}
                               for c in u.audit_components(targets)}}
        audited = u.validate_claim_audit(response, targets, self.spans)
        self.assertTrue(audited["passed"])
        self.assertEqual(audited["checks"][1]["claim_support"], "reported_only")

    def test_good_question_cannot_rescue_an_unsupported_assertion(self):
        targets = u.claim_targets(self.raw, self.spans)
        response = {"checks": {c["id"]: {"verdict": "supported", "reason": "Supported."}
                               for c in u.audit_components(targets)}}
        response["checks"]["F1.assertion"] = {"verdict": "unsupported", "reason": "An entity relationship was never asserted."}
        self.assertFalse(u.validate_claim_audit(response, targets, self.spans)["passed"])

    def test_auditor_cannot_introduce_other_source_ids_or_rewrite_targets(self):
        targets = u.claim_targets(self.raw, self.spans)
        original = copy.deepcopy(targets)
        response = {"checks": {c["id"]: {"verdict": "supported", "reason": "Supported."}
                               for c in u.audit_components(targets)}}
        response["checks"]["F1.assertion"]["refs"] = ["D2:0"]
        with self.assertRaises(ValueError):
            u.validate_claim_audit(response, targets, self.spans)
        self.assertEqual(targets, original)

    def test_unknown_fit_audits_the_unknown_classification_not_positive_ability(self):
        self.row.update(relevance="unknown")
        self.row["task_alignment"] = alignment("unknown", "unknown")
        component = next(c for c in u.audit_components(u.claim_targets(self.raw, self.spans)) if c["id"] == "F1.fit")
        self.assertIn("unknown", component["audit_question"])
        self.assertIn("classification", component["audit_question"])

    def test_settled_finding_checks_no_question_decision(self):
        component = next(c for c in u.audit_components(u.claim_targets(self.raw, self.spans)) if c["id"] == "F1.clarification")
        self.assertEqual(component["content"]["routing_decision"], "no_question")
        self.assertIn("NOT", component["audit_question"])

    def test_verification_citations_are_audited_on_their_own(self):
        self.row["claim"].update(basis="package_fact", refs=["D1:0"])
        self.row.update(verification_status="source_supported", verification_refs=["D2:0"])
        component = next(c for c in u.audit_components(u.claim_targets(self.raw, self.spans)) if c["id"] == "F1.verification")
        self.assertEqual(set(component["source_spans"]), {"D2:0"})
        response = {"checks": {c["id"]: {"verdict": "supported", "reason": "Supported."}
                               for c in u.audit_components(u.claim_targets(self.raw, self.spans))}}
        response["checks"]["F1.verification"] = {"verdict": "unsupported", "reason": "Schedule text does not establish performance."}
        self.assertFalse(u.validate_claim_audit(response, u.claim_targets(self.raw, self.spans), self.spans)["passed"])

    def test_identity_is_not_reaudited_as_performed_work(self):
        self.row["claim"]["subject"] = "identity"
        self.row.update(relevance="not_applicable")
        self.row["task_alignment"] = alignment("not_applicable", "not_applicable")
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        self.assertNotIn("F1.fit", [c["id"] for c in components])
        self.assertIn("F1.qualification", [c["id"] for c in components])

    def test_absence_scope_is_computed_from_actual_references(self):
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        requirement = next(c for c in components if c["id"] == "F1.requirement")
        self.assertEqual(requirement["evidence_coverage"]["package"], "selected_spans")
        assertion = next(c for c in components if c["id"] == "F1.assertion")
        self.assertEqual(assertion["evidence_coverage"]["profile"], "all_supplied_spans")

    def test_true_sentence_still_requires_correct_claim_subject(self):
        self.row["claim"].update(statement="The government requires equipment maintenance.", basis="package_fact", refs=["D1:0"])
        self.row.update(verification_status="source_supported", verification_refs=["D1:0"])
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        subject = next(c for c in components if c["id"] == "F1.subject")
        self.assertIn("performed_work", subject["audit_question"])
        self.assertIn("requirement", subject["audit_question"])

    def test_question_effects_do_not_inherit_unstated_tasks(self):
        self.row.update(ambiguity="ambiguous", question="Who performed the referenced work?")
        self.row["clarification"] = resolution("attribution")
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        effect = next(c for c in components if c["id"] == "F1.effect1")
        self.assertIn("ONLY", effect["audit_question"])
        self.assertEqual(set(effect["content"]), {"new_fact_if_answered", "proposed_consequence"})
        self.assertNotIn("alternatives", str(effect["content"]))

    def test_question_routing_can_see_other_already_routed_questions(self):
        other = copy.deepcopy(self.row)
        other.update(ambiguity="ambiguous", question="What tasks did your staff perform?")
        other["clarification"] = resolution("meaning")
        self.raw["uncertainties"].append(other)
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        component = next(c for c in components if c["id"] == "F1.clarification")
        self.assertEqual(component["content"]["question_plan"][0]["question"], other["question"])
        assertion = next(c for c in components if c["id"] == "F1.assertion")
        self.assertNotIn("question_plan", assertion["content"])

    def test_nonwork_without_requirement_does_not_create_an_empty_assertion(self):
        self.row["claim"]["subject"] = "role_preference"
        self.row.update(relevance="not_applicable")
        self.row["task_alignment"] = alignment("not_applicable", "not_applicable")
        self.row["comparison"].update(required_statement="", refs=[])
        components = u.audit_components(u.claim_targets(self.raw, self.spans))
        self.assertNotIn("F1.requirement", [c["id"] for c in components])
        self.assertIn("F1.qualification", [c["id"] for c in components])


if __name__ == "__main__":
    unittest.main()
