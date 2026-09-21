"""H04 contracts. Mocked verdicts prove routing, not live-model agreement."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s


def conflict_fixture():
    first = "Issued paving scope: reopen the runway 12 hours after concrete placement."
    second = "Issued acceptance schedule: keep the same runway closed until 72 hours after concrete placement."
    document = first + " " + second + " Both apply to the same work; no order of precedence is supplied."
    profile = "We perform runway paving using concrete. We can plan either schedule once the official conflict is resolved."
    spans = {"D1:0": {"text": document, "kind": "package", "source_id": "D1", "offset": 0},
             "V1:0": {"text": profile, "kind": "profile", "source_id": "V1", "offset": 0}}
    requirements = [{"area": "timing", "status": "current", "task": False,
        "record_kind": "requirement", "logic": "all", "supersedes": [],
        "evidence": [{"ref": "D1:0", "quote": document}],
        "focus": [{"ref": "D1:0", "quote": text}],
        "components": [{"kind": "timing", "text": text, "evidence": [{"ref": "D1:0", "quote": text}]}]}
        for text in (first, second)]
    claims = [{"meaning": "The vendor reports performing runway paving using concrete.",
        "assertion_basis": "staff_execution", "antecedent_evidence": [],
        "attribution": "self", "unresolved_dimensions": [],
        "evidence": [{"ref": "V1:0", "quote": "We perform runway paving using concrete."}]},
        {"meaning": "The vendor offers to plan a schedule after the official conflict is resolved.",
         "assertion_basis": "proposed_work", "antecedent_evidence": [],
         "attribution": "self", "unresolved_dimensions": [],
         "evidence": [{"ref": "V1:0", "quote": "We can plan either schedule once the official conflict is resolved."}]}]
    question = {"dimension": "official_conflict", "requirements": [0, 1], "claims": [],
                "reason": "The package supplies incompatible closure durations without precedence.", "decision": "timing"}
    inventory = s.validate_inventory({"requirements": requirements, "claims": claims,
        "questions": [question], "resolved_question_ids": []}, spans, components=True)
    return spans, s.validate({**inventory, "comparisons": []}, spans)


class SharedPolicyTests(unittest.TestCase):
    def test_vendor_models_receive_identical_execution_rule(self):
        from common.semantic_policy import EXECUTION_RULE
        from common import capture_understanding as u, capture_clarification as g, claim_audit
        prompts = [c.INVENTORY_PROMPT, c.COMPONENT_PROMPT, c.AMBIGUITY_PROMPT, c.QUESTION_AUDIT_PROMPT,
                   s.PROMPT, s.COMPARE_PROMPT, s.AUDIT_PROMPT, u.BASE_PROMPT, u.ASSESS_PROMPT,
                   u.REVIEW_PROMPT, g.SYSTEM_PROMPT, claim_audit.PROMPT]
        prompts.extend(s.audit_prompt([{"kind": kind}]) for kind in
                       ("claim", "claim_coverage", "comparison", "question", "routing", "coverage"))
        for prompt in prompts:
            with self.subTest(prompt=prompt[:70]):
                self.assertIn(EXECUTION_RULE, prompt)
                self.assertNotIn("Do not upgrade this general service description in an audit.", prompt)
                self.assertNotIn("First-person wording and present tense alone do NOT establish", prompt)

    def test_precedence_rule_is_shared_by_package_extractor_and_auditor(self):
        from common.semantic_policy import PRECEDENCE_RULE
        from common import capture_understanding as u
        for prompt in (u.EXTRACT_PROMPT, c.INVENTORY_PROMPT,
                       s.audit_prompt([{"kind": "requirement"}]), s.audit_prompt([{"kind": "package_coverage"}])):
            self.assertIn(PRECEDENCE_RULE, prompt)

    def test_decomposer_records_conflicts_without_audit_verdict_instructions(self):
        from common.semantic_policy import PRECEDENCE_POLICY, PRECEDENCE_RULE, EXECUTION_RULE
        self.assertNotIn(PRECEDENCE_RULE, c.DECOMPOSE_PROMPT)
        self.assertNotIn(PRECEDENCE_POLICY, c.DECOMPOSE_PROMPT)
        self.assertNotIn(EXECUTION_RULE, c.DECOMPOSE_PROMPT)
        for instruction in ("approve the extraction", "pass the audit", "fidelity_verdict"):
            self.assertNotIn(instruction, c.DECOMPOSE_PROMPT)
        self.assertIn("Keep conflicting terms separate", c.DECOMPOSE_PROMPT)
        self.assertIn("unresolved_precedence", c.DECOMPOSE_PROMPT)
        self.assertIn("source facts, status, focus and precedence links remain immutable", c.DECOMPOSE_PROMPT)

    def test_source_fidelity_auditors_retain_complete_precedence_policy_once(self):
        from common.semantic_policy import PRECEDENCE_POLICY
        for kind in ("requirement", "package_coverage", "package_reference"):
            with self.subTest(kind=kind):
                prompt = s.audit_prompt([{"kind": kind}])
                self.assertEqual(prompt.count(PRECEDENCE_POLICY), 1)

    def test_rule_is_not_duplicated_by_prompt_composition(self):
        from common.semantic_policy import apply_policies, EXECUTION_RULE, PRECEDENCE_RULE
        once = apply_policies("Classify these sources.")
        self.assertEqual(apply_policies(once), once)
        self.assertEqual(once.count(EXECUTION_RULE), 1)
        self.assertEqual(once.count(PRECEDENCE_RULE), 1)

    def test_staff_execution_has_work_credit_but_is_still_unverified(self):
        spans, plan = conflict_fixture()
        claim = plan["claims"][0]
        self.assertEqual((claim["form"], claim["execution"]), ("performed_task", "affirmative_actual"))
        row = next(r for r in s.render(plan, spans)["uncertainties"] if r.get("claim_id") == "C0")
        self.assertEqual(row["verification_status"], "unverified")
        self.assertEqual(row["task_alignment"]["shared_work"], "")

    def test_future_offer_and_negation_do_not_become_execution(self):
        spans, plan = conflict_fixture()
        for basis, expected in (("proposed_work", "prospective"), ("work_denial", "negative"),
                                ("service_offering", "not_execution")):
            with self.subTest(basis=basis):
                raw = {k: v for k, v in plan["claims"][0].items() if k not in {"form", "execution"}}
                raw["assertion_basis"] = basis
                claim = c.ground_claims([raw], spans)[0]
                self.assertEqual(claim["execution"], expected)
                self.assertNotEqual(claim["form"], "performed_task")


class FidelityAndPrecedenceTests(unittest.TestCase):
    def targets(self):
        spans, plan = conflict_fixture()
        return spans, plan, [r for r in s.audit_records(plan, spans) if r["kind"] == "requirement"]

    def test_recorded_conflict_is_explicit_and_current_is_not_resolved(self):
        _, _, records = self.targets()
        for record in records:
            self.assertEqual(record["audit_dimension"], "source_fidelity")
            self.assertEqual(record["precedence_status"], "unresolved_precedence")
            self.assertEqual(record["conflicting_requirement_ids"], ["R0", "R1"])
            self.assertEqual(record["value"]["status"], "current")

    def test_schema_asks_for_fidelity_not_a_governing_rule_decision(self):
        _, _, records = self.targets()
        shape = s.audit_schema(records)["properties"]["checks"]["properties"]["R0"]
        self.assertIn("fidelity_verdict", shape["required"])
        self.assertNotIn("verdict", shape["properties"])
        self.assertNotIn("governing_requirement", shape["properties"])

    def test_accurate_unresolved_records_pass_fidelity_and_remain_unresolved(self):
        _, _, records = self.targets()
        raw = {"checks": {r["id"]: {"fidelity_verdict": "supported", "reason": "Both terms are faithfully retained."}
                          for r in records}}
        checked = s.validate_audit(raw, records)
        self.assertTrue(checked["passed"])
        self.assertTrue(all(r["precedence_status"] == "unresolved_precedence" for r in checked["checks"]))
        self.assertEqual(s.validate_audit({"checks": s.audit_responses(checked["checks"])}, records), checked)

    def test_conflict_does_not_excuse_inaccurate_or_uncertain_transcription(self):
        _, _, records = self.targets()
        for verdict in ("unsupported", "uncertain"):
            raw = {"checks": {r["id"]: {"fidelity_verdict": verdict, "reason": "The extracted amount is not supported."}
                              for r in records}}
            self.assertFalse(s.validate_audit(raw, records)["passed"])

    def test_old_overloaded_verdict_is_rejected_for_fidelity_targets(self):
        _, _, records = self.targets()
        raw = {"checks": {r["id"]: {"verdict": "supported", "reason": "Ambiguous audit scope."} for r in records}}
        with self.assertRaises(ValueError):
            s.validate_audit(raw, records)

    def test_conflict_flag_cannot_silently_retire_a_clause(self):
        spans, plan, _ = self.targets()
        plan["requirements"][0]["status"] = "superseded"
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_bad_quotation_is_not_excused_by_conflicting_sources(self):
        spans, plan, _ = self.targets()
        plan["requirements"][0]["focus"][0]["quote"] = "An invented 99-hour deadline."
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_requirement_audit_never_receives_vendor_sources(self):
        spans, _, records = self.targets()
        self.assertEqual(set(c.audit_payload(records, spans)["spans"]), {"D1:0"})

    def test_render_preserves_both_terms_and_formal_qa(self):
        spans, plan, _ = self.targets()
        result = s.render(plan, spans)
        self.assertTrue(all(r["precedence_status"] == "unresolved_precedence" for r in result["interpretation"]))
        self.assertTrue(all("Unresolved precedence" in r["text"] for r in result["interpretation"]))
        self.assertIn("12 hours", result["interpretation"][0]["text"])
        self.assertIn("72 hours", result["interpretation"][1]["text"])
        question = next(r for r in result["uncertainties"] if r["record_type"] == "question")
        self.assertEqual(question["owner"], "official")
        self.assertTrue(question["blocking"])


class PipelinePolicyTests(unittest.TestCase):
    def run_conflict(self, *, reject_requirement=False):
        from common import capture_understanding as u, capture_clarification as gate
        spans, plan = conflict_fixture()
        inventory = deepcopy({k: v for k, v in plan.items() if k != "comparisons"})
        inventory["quoted_vendor_context"] = []
        for requirement in inventory["requirements"]:
            requirement.pop("meaning")
        for claim in inventory["claims"]:
            claim.pop("form")
            claim.pop("execution")
        packet = {"sources": {r["source_id"]: r for r in spans.values()}, "technical_issues": []}
        calls = []

        def model(**kwargs):
            payload = kwargs["user_payload"]
            calls.append(payload)
            if "signals" in kwargs["response_schema"]["schema"]["properties"]:
                # Inventory-only discovery must also reach the independent channel.
                return {"signals": []}
            if "source_coverage" in payload:
                return deepcopy(inventory)
            if "targets" in payload:
                return {"checks": {t["id"]: {
                    s.audit_verdict_key(t): "unsupported" if reject_requirement and t["id"] == "R0" else "supported",
                    "reason": "Mocked fidelity verdict, not a live semantic judgment.",
                } for t in payload["targets"]}}
            if isinstance(payload.get("requirements"), dict):
                return {"requirements": {f"R{i}": {"logic": r["logic"], "components": r["components"]}
                                         for i, r in enumerate(inventory["requirements"])}}
            if "pairs" in payload:
                self.fail("Timing-only records cannot manufacture matched work.")
            return {"complete": True,
                    "facts": [{"area": "timing", "statement": spans["D1:0"]["text"], "refs": ["D1:0"]}],
                    "coverage": [{"source_id": "D1", "finding": "Both conflicting terms retained.", "refs": ["D1:0"]}]}

        raw = u.analyze_packet(packet, [], {}, call=model)
        return raw, gate.validate_assessment(raw, packet), calls

    def test_approved_fidelity_is_not_permission_to_proceed(self):
        raw, state, calls = self.run_conflict()
        self.assertNotIn("pipeline_errors", raw)
        self.assertTrue(raw["understanding_audit"]["claim_evidence"]["passed"])
        self.assertEqual(state["status"], "NEEDS_FORMAL_QA")
        self.assertFalse(state["research_authorized"])
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["route"], "formal_qa")
        self.assertEqual(state["questions"][0]["question_validation"], "supported")
        self.assertEqual(len(state["interpretation"]), 2)
        self.assertTrue(all(r["precedence_status"] == "unresolved_precedence" for r in state["interpretation"]))
        claim = raw["understanding_audit"]["semantic_plan"]["claims"][0]
        self.assertEqual(claim["assertion_basis"], "staff_execution")
        proposed = raw["understanding_audit"]["semantic_plan"]["claims"][1]
        self.assertEqual((proposed["form"], proposed["execution"]), ("capability", "prospective"))
        audits = [p for p in calls if any(t["kind"] == "requirement" for t in p.get("targets", []))]
        self.assertEqual(len(audits), 1)
        self.assertEqual(set(audits[0]["spans"]), {"D1:0"})

    def test_unrelated_fidelity_failure_does_not_erase_formal_qa(self):
        raw, state, calls = self.run_conflict(reject_requirement=True)
        self.assertFalse(raw["understanding_audit"]["claim_evidence"]["passed"])
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertFalse(state["research_authorized"])
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["route"], "formal_qa")
        self.assertEqual(sum(any(t["id"] == "R0" for t in p.get("targets", [])) for p in calls), 1)


if __name__ == "__main__":
    unittest.main()
