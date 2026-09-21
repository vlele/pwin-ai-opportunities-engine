"""Exact-claim contract tests. Mock verdicts test enforcement, not model accuracy."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u
from test_capture_understanding import assessment, issue, packet, task_alignment, supported_audit


def explicit(row, *, basis="reported", subject="performed_work"):
    row["claim"] = {"subject": subject, "statement": "The vendor performs consumer event photography only.",
                    "basis": basis, "refs": ["V1:0"]}
    row["comparison"] = {"required_statement": "Maintain industrial refrigeration equipment.",
                         "refs": ["D1:0"], "rationale": "The stated performed tasks do not overlap the requirement."}
    return row


class ClaimEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.spans = u.build_spans(packet())
        self.raw = assessment(self.spans)
        self.raw["uncertainties"] = [explicit(issue(self.spans, "clear", relevance="unrelated"))]

    def targets(self):
        return u.claim_targets(self.raw, self.spans)

    def audit(self):
        return supported_audit(u.audit_components(self.targets()))

    def test_classification_requires_an_explicit_claim(self):
        del self.raw["uncertainties"][0]["claim"]
        with self.assertRaisesRegex(ValueError, "claim"):
            u.render_assessment(self.raw, self.spans)

    def test_claim_and_requirement_have_distinct_original_citations(self):
        row = u.render_assessment(self.raw, self.spans)["uncertainties"][0]
        self.assertEqual(row["claim_citations"][0]["source_id"], "V1")
        self.assertEqual(row["requirement_citations"][0]["source_id"], "D1")

    def test_profile_cannot_supply_the_governments_requirement(self):
        self.raw["uncertainties"][0]["comparison"]["refs"] = ["V1:0"]
        with self.assertRaisesRegex(ValueError, "comparison"):
            u.render_assessment(self.raw, self.spans)

    def test_missing_claim_is_not_a_positive_experience_assertion(self):
        row = self.raw["uncertainties"][0]
        row.update(relevance="unknown", ambiguity="missing", verification_status="unknown", action="record_gap", question="", options=[])
        row["claim"].update(statement="", basis="not_supplied", refs=[])
        row["task_alignment"] = task_alignment("unknown")
        self.assertEqual(u.render_assessment(self.raw, self.spans)["uncertainties"][0]["relevance"], "unknown")
        row["relevance"] = "direct"
        row["task_alignment"] = task_alignment("direct")
        with self.assertRaisesRegex(ValueError, "not_supplied"):
            u.render_assessment(self.raw, self.spans)

    def test_role_preference_cannot_be_experience_credit(self):
        row = self.raw["uncertainties"][0]
        row.update(kind="vendor_role", relevance="direct")
        row["claim"]["subject"] = "role_preference"
        with self.assertRaisesRegex(ValueError, "role_preference"):
            u.render_assessment(self.raw, self.spans)

    def test_source_supported_requires_package_fact_not_reported_claim(self):
        row = self.raw["uncertainties"][0]
        row.update(verification_status="source_supported", verification_refs=["D1:0"])
        with self.assertRaisesRegex(ValueError, "basis"):
            u.render_assessment(self.raw, self.spans)

    def test_targets_freeze_claims_instead_of_allowing_reviewer_rewrites(self):
        before = copy.deepcopy(self.raw)
        targets = self.targets()
        self.assertEqual({t["target_id"] for t in targets}, {"I1", "F1"})
        self.assertEqual(targets[1]["claim"], before["uncertainties"][0]["claim"])
        self.assertEqual(self.raw, before)
        self.assertEqual(targets[1]["source_spans"]["V1:0"]["text"], self.spans["V1:0"]["text"])

    def test_target_ids_are_code_owned(self):
        self.raw["uncertainties"][0]["target_id"] = "I1"
        self.assertEqual(self.targets()[1]["target_id"], "F1")

    def test_different_claims_on_same_citations_are_not_deduped_away(self):
        from common import capture_clarification as gate
        first = self.raw["uncertainties"][0]
        first.update(action="record_gap", question="", options=[])
        second = copy.deepcopy(first)
        second["claim"]["statement"] = "The vendor does not perform equipment maintenance."
        self.raw["uncertainties"].append(second)
        rendered = u.render_assessment(self.raw, self.spans)
        self.assertEqual(len(gate.validate_assessment(rendered, packet())["open_gaps"]), 2)

    def test_checked_user_answer_can_pass_citation_boundary_without_editing_profile(self):
        from common import capture_clarification as gate
        original = copy.deepcopy(packet())
        answered = u.packet_with_answers(original, [{"question_id": "Q-1", "answer": "Our staff delivered the installation."}])
        spans = u.build_spans(answered)
        raw = assessment(spans)
        row = explicit(issue(spans, "clear", relevance="direct"))
        row["claim"].update(statement="Our staff delivered the installation.", refs=["U1:0"])
        row.update(action="record_gap", question="", options=[])
        raw["uncertainties"] = [row]
        state = gate.validate_assessment(u.render_assessment(raw, spans), answered)
        self.assertEqual(state["status"], "READY")
        self.assertEqual(original, packet())
        self.assertEqual(state["open_gaps"][0]["verification_status"], "unverified")

    def test_unverified_but_accurately_reported_claim_can_pass(self):
        result = u.validate_claim_audit(self.audit(), self.targets(), self.spans)
        self.assertTrue(result["passed"])

    def test_reference_echo_is_not_evidence_of_actual_performance(self):
        row = self.raw["uncertainties"][0]
        row.update(verification_status="source_supported", verification_refs=["D1:0"])
        row["claim"].update(basis="package_fact", refs=["D1:0"])
        # A semantic auditor says this is only an assertion, despite a valid package ID.
        audit = self.audit()
        audit["checks"]["F1.assertion"].update(verdict="unsupported", reason="A quoted reference does not establish performance.")
        result = u.validate_claim_audit(audit, self.targets(), self.spans)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][1]["claim_support"], "not_established")

    def test_legitimate_package_support_is_not_forced_to_unverified(self):
        row = self.raw["uncertainties"][0]
        row.update(verification_status="source_supported", verification_refs=["D1:0"])
        row["claim"].update(basis="package_fact", refs=["D1:0"])
        audit = self.audit()
        self.assertEqual(u.validate_claim_audit(audit, self.targets(), self.spans)["checks"][1]["claim_support"], "package_supported")
        self.assertTrue(u.validate_claim_audit(audit, self.targets(), self.spans)["passed"])

    def test_negative_semantic_verdict_is_retained_not_repaired(self):
        audit = self.audit()
        audit["checks"]["I1.interpretation"].update(verdict="unsupported", reason="A relevant-experience example was changed into mandatory eligibility.")
        result = u.validate_claim_audit(audit, self.targets(), self.spans)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["facets"]["I1.interpretation"], {**audit["checks"]["I1.interpretation"], "refs": self.targets()[0]["refs"], "evidence_scope": "entire_supplied_component_evidence_set"})

    def test_partial_or_uncertain_entailment_cannot_pass(self):
        audit = self.audit()
        audit["checks"]["F1.fit"]["verdict"] = "uncertain"
        self.assertFalse(u.validate_claim_audit(audit, self.targets(), self.spans)["passed"])

    def test_honestly_classified_conflicting_vendor_claim_is_not_positive_credit(self):
        row = self.raw["uncertainties"][0]
        row.update(relevance="unknown", ambiguity="conflicting", action="ask")
        row["task_alignment"] = task_alignment("unknown")
        audit = self.audit()
        self.assertTrue(u.validate_claim_audit(audit, self.targets(), self.spans)["passed"])
        audit["checks"]["F1.fit"].update(verdict="unsupported", reason="The finding treats conflicting reported evidence as settled.")
        self.assertFalse(u.validate_claim_audit(audit, self.targets(), self.spans)["passed"])

    def test_every_component_requires_exactly_one_verdict(self):
        for alteration in ("missing", "unknown", "legacy_array"):
            audit = self.audit()
            if alteration == "missing":
                audit["checks"].pop("F1.fit")
            elif alteration == "unknown":
                audit["checks"]["invented"] = {"verdict": "supported", "reason": "Invented."}
            else:
                audit["checks"] = list(audit["checks"].values())
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                u.validate_claim_audit(audit, self.targets(), self.spans)

    def test_auditor_cannot_add_unrelated_evidence(self):
        self.raw["interpretation"][0]["refs"] = ["D1:0", "V1:0"]
        audit = self.audit()
        audit["checks"]["I1.interpretation"]["refs"] = ["D2:0"]
        with self.assertRaisesRegex(ValueError, "cite other evidence"):
            u.validate_claim_audit(audit, self.targets(), self.spans)

    def test_user_answers_are_citable_but_remain_reported(self):
        spans = u.build_spans(packet(), [{"question_id": "Q-one", "answer": "Our own staff performed the installation."}])
        answer = next(s for s in spans.values() if s["kind"] == "user_answer")
        self.assertEqual(answer["question_id"], "Q-one")
        schema = u.source_schema(u.ASSESSMENT_SCHEMA, spans)
        self.assertNotIn("U1:0", schema["$defs"]["PackageRef"]["enum"])

    def test_failed_entailment_blocks_without_resampling_or_user_question(self):
        from common import capture_clarification as gate
        calls = []

        def model(**kwargs):
            payload = kwargs["user_payload"]
            calls.append(payload)
            if "signals" in kwargs["response_schema"]["schema"]["properties"]:
                return {"signals": []}
            if isinstance(payload.get("requirements"), dict):
                return {"requirements": {key: {"logic": "all", "components": [{"kind": "work", "text": "Maintain refrigeration",
                       "evidence": row["evidence"]}]} for key, row in payload["requirements"].items()}}
            if "targets" in payload:
                audit = supported_audit(payload["targets"])
                if "C0" in audit["checks"]:
                    audit["checks"]["C0"].update(verdict="unsupported", reason="Claim exceeds the cited performed work.")
                return audit
            if "component_job" in payload:
                job = payload["component_job"]
                return {**{k: job[k] for k in ("pair_id", "component_id", "component_text", "component_kind")},
                        "status": "matched", "reason": "Claimed match.", "supported_scope": job["component_text"],
                        "evidence": job["claimed"]["evidence"]}
            if "source_coverage" in payload:
                spans = payload["spans"]
                return {"requirements": [{"area": "scope", "status": "current", "task": True,
                                          "record_kind": "requirement", "logic": "all", "supersedes": [],
                                          "focus": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}],
                                          "components": [{"kind": "work", "text": "Maintain refrigeration", "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]}],
                                          "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]}],
                        "claims": [{"form": "performed_task", "meaning": "Unsupported performed tasks.", "attribution": "self",
                                    "execution": "affirmative_actual", "unresolved_dimensions": [],
                                    "evidence": [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]}],
                        "questions": [], "resolved_question_ids": [], "quoted_vendor_context": []}
            spans = payload["spans"]
            return {"complete": True, "facts": [{"area": "scope", "statement": "Maintain refrigeration equipment.", "refs": list(spans)}],
                    "coverage": [{"source_id": sid, "finding": "Scope or schedule reviewed.", "refs": [ref for ref, span in spans.items() if span["source_id"] == sid]}
                                 for sid in dict.fromkeys(span["source_id"] for span in spans.values())]}

        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), packet(), analyze=lambda p, a, prev: u.analyze_packet(p, a, prev, call=model))
            self.assertEqual(result["status"], "TECHNICAL_BLOCKED")
            self.assertEqual(result["understanding_audit"]["failure_kind"], "semantic_support")
            self.assertEqual(len(calls), 10)
            self.assertEqual(sum(any(t["id"] == "C0" for t in c.get("targets", [])) for c in calls), 1)
            self.assertFalse(result["questions"])
            self.assertIn("Claim exceeds", Path(result["review_path"]).read_text())
            self.assertEqual(gate.confirmed_context(result, packet()), {})

    def test_raw_extraction_is_not_repromoted_as_checked_downstream_claims(self):
        from common import capture_clarification as gate
        state = {"status": "READY", "fingerprint": "sample", "interpretation": [], "confirmed_answers": [], "open_gaps": [],
                 "understanding_audit": {"facts": [{"statement": "An unreviewed extraction"}],
                                         "coverage": [{"finding": "Unreviewed coverage prose"}],
                                         "claim_evidence": {"passed": True, "checks": [], "basis": "fixture"}}}
        context = gate.confirmed_context(state, packet())
        self.assertNotIn("facts", context["understanding_audit"])
        self.assertNotIn("coverage", context["understanding_audit"])
        self.assertTrue(context["understanding_audit"]["claim_evidence"]["passed"])

    def test_strict_schemas_validate_positive_contract_examples(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional jsonschema package is not installed")
        schemas = [(u.source_schema(u.ASSESSMENT_SCHEMA, self.spans), self.raw),
                   (u.claim_audit_schema(self.targets(), self.spans), self.audit())]
        for schema, data in schemas:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(data, schema)

    def test_live_auditor_benchmark_defaults_to_low_and_honors_override(self):
        from run_claim_evidence_benchmark import audit_request
        targets = self.targets()
        self.assertEqual(audit_request(targets, self.spans, "test-model")["reasoning_effort"], "low")
        self.assertEqual(audit_request(targets, self.spans, "test-model", "medium")["reasoning_effort"], "medium")
        self.assertNotIn("expected", str(audit_request(targets, self.spans, "test-model")["user_payload"]))


if __name__ == "__main__":
    unittest.main()
