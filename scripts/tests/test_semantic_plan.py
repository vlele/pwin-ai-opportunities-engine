"""Source/decision contracts, independent of provider behavior."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_plan as s


def fixture():
    spans = {
        "D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                 "text": "Install displays. Repair displays. Supply replacement parts."},
        "V1:0": {"kind": "profile", "source_id": "V1", "offset": 0,
                 "text": "Our staff installed displays. We provide equipment services."},
    }
    reqs = [{"area": "scope", "meaning": q, "status": "current", "task": True,
             "evidence": [{"ref": "D1:0", "quote": q}]} for q in
            ("Install displays.", "Repair displays.", "Supply replacement parts.")]
    plan = {"requirements": reqs,
            "claims": [{"form": "performed_task", "meaning": "Our staff installed displays.",
                        "attribution": "self", "evidence": [{"ref": "V1:0", "quote": "Our staff installed displays."}]}],
            "comparisons": [{"claim": 0, "requirement": i, "relationship": "same_task" if i == 0 else "unknown",
                             "reason": "Same installation task." if i == 0 else "No claim about this additional task.",
                             "transfer_basis": "", "matched_work": "Install displays" if i == 0 else "",
                             "coverage": "complete" if i == 0 else "unknown"} for i in range(3)],
            "questions": [], "resolved_question_ids": []}
    return spans, plan


class SemanticPlanTests(unittest.TestCase):
    def test_audit_batches_do_not_mix_different_propositions(self):
        spans, plan = fixture()
        records = s.audit_records(plan, spans)
        batches = list(s.audit_batches(records))
        self.assertEqual([r["id"] for b in batches for r in b], [r["id"] for r in records])
        for batch in batches:
            self.assertEqual(len({r["kind"] for r in batch}), 1)
            self.assertLessEqual(len(batch), s.MAX_AUDIT_BATCH)
            self.assertIn(batch[0]["kind"], s.audit_prompt(batch))

    def test_audit_does_not_silently_drop_a_late_negative_batch(self):
        spans, plan = fixture()
        records = s.audit_records(plan, spans)
        checks = {r["id"]: {s.audit_verdict_key(r): "supported", "reason": "Record is faithful."} for r in records}
        checks["coverage"] = {"verdict": "unsupported", "reason": "A material clause was omitted."}
        self.assertFalse(s.validate_audit({"checks": checks}, records)["passed"])
        with self.assertRaises(ValueError):
            s.audit_prompt([records[0], records[-1]])

    def test_partial_same_work_is_direct_not_transferable(self):
        spans, plan = fixture()
        result = s.render(s.validate(plan, spans), spans)
        row = result["uncertainties"][0]
        self.assertEqual(row["relevance"], "direct")
        self.assertEqual(row["task_alignment"]["coverage"], "partial")
        self.assertFalse(row["blocking"])
        self.assertEqual(row["verification_status"], "unverified")

    def test_citations_are_assembled_from_both_sides_not_reinvented(self):
        spans, plan = fixture()
        row = s.render(s.validate(plan, spans), spans)["uncertainties"][0]
        self.assertEqual(set(row["refs"]), {"D1:0", "V1:0"})
        for c in row["citations"]:
            self.assertIn(c["quote"], spans[c["span_id"]]["text"])

    def test_false_quote_or_wrong_source_role_fails(self):
        for mutation in ("quote", "ref"):
            spans, plan = fixture()
            plan["requirements"][0]["evidence"][0][mutation] = "Invented text" if mutation == "quote" else "V1:0"
            with self.assertRaises(ValueError):
                s.validate(plan, spans)

    def test_unknown_claim_id_and_duplicate_comparison_fail(self):
        spans, plan = fixture()
        bad = deepcopy(plan)
        bad["comparisons"][0]["claim"] = 99
        with self.assertRaises(ValueError):
            s.validate(bad, spans)
        bad = deepcopy(plan)
        bad["comparisons"].append(deepcopy(bad["comparisons"][0]))
        with self.assertRaises(ValueError):
            s.validate(bad, spans)

    def test_no_coverage_truncation(self):
        spans, plan = fixture()
        plan["comparisons"].pop()
        with self.assertRaisesRegex(ValueError, "matrix"):
            s.validate(plan, spans)

    def test_reference_or_capability_cannot_get_experience_credit(self):
        spans, plan = fixture()
        for form in ("work_reference", "capability", "identity", "preference"):
            bad = deepcopy(plan)
            bad["claims"][0]["form"] = form
            with self.assertRaises(ValueError):
                s.validate(bad, spans)

    def test_unresolved_attribution_cannot_get_experience_credit(self):
        spans, plan = fixture()
        plan["claims"][0]["attribution"] = "unresolved"
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_ambiguous_reference_routes_without_assuming_its_meaning(self):
        spans, plan = fixture()
        plan["claims"][0].update(form="work_reference", meaning="The profile names a reference; actual tasks are unclear.", attribution="unresolved")
        for edge in plan["comparisons"]:
            edge.update(relationship="unknown", reason="Reference meaning is unresolved.", matched_work="", coverage="unknown")
        plan["questions"] = [{"dimension": "task_meaning", "claims": [0], "requirements": [0],
                              "reason": "The current reference does not identify actual tasks.", "decision": "experience"}]
        rendered = s.render(s.validate(plan, spans), spans)
        row = rendered["uncertainties"][0]
        self.assertEqual(row["claim"]["subject"], "work_reference")
        self.assertEqual(row["relevance"], "unknown")
        self.assertTrue(any(r["blocking"] for r in rendered["uncertainties"]))
        self.assertNotIn("diagnostic", " ".join(r["question"] for r in rendered["uncertainties"]))
        self.assertEqual(row["claim"]["statement"], plan["claims"][0]["meaning"])

    def test_ambiguous_reference_cannot_be_silently_dropped(self):
        spans, plan = fixture()
        plan["claims"][0].update(form="work_reference", attribution="unresolved")
        for e in plan["comparisons"]:
            e.update(relationship="unknown", matched_work="", coverage="unknown")
        with self.assertRaisesRegex(ValueError, "question"):
            s.validate(plan, spans)

    def test_generic_capability_is_unknown_without_rescue_question(self):
        spans, plan = fixture()
        plan["claims"][0].update(form="capability", attribution="self")
        for e in plan["comparisons"]:
            e.update(relationship="unknown", matched_work="", coverage="unknown")
        rendered = s.render(s.validate(plan, spans), spans)
        self.assertEqual(rendered["uncertainties"][0]["relevance"], "unknown")
        self.assertFalse(any(r["blocking"] for r in rendered["uncertainties"]))

    def test_absent_history_is_not_inability(self):
        spans, plan = fixture()
        del spans["V1:0"]
        plan.update(claims=[], comparisons=[])
        row = s.render(s.validate(plan, spans), spans)["uncertainties"][0]
        self.assertEqual(row["claim"]["basis"], "not_supplied")
        self.assertEqual(row["relevance"], "unknown")
        self.assertEqual(row["verification_status"], "unknown")
        self.assertFalse(row["blocking"])

    def test_identity_question_cannot_claim_tasks_or_unlock_task_credit(self):
        spans, plan = fixture()
        spans["V1:0"]["text"] = "Offeror Sample East. Reference performer Sample Holdings."
        plan["claims"] = [{"form": "identity", "meaning": spans["V1:0"]["text"], "attribution": "unresolved",
                           "evidence": [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]}]
        plan["comparisons"] = []
        plan["questions"] = [{"dimension": "performer_identity", "claims": [0], "requirements": [0],
                              "reason": "The entities' relationship is not specified.", "decision": "attribution"}]
        rendered = s.render(s.validate(plan, spans), spans)
        questions = [r for r in rendered["uncertainties"] if r["blocking"]]
        self.assertEqual(len(questions), 1)
        self.assertIn("legal entity", questions[0]["question"])
        self.assertFalse(any(r["relevance"] in {"direct", "transferable"} for r in rendered["uncertainties"]))
        self.assertNotIn("installed", questions[0]["question"])

    def test_official_conflict_needs_two_current_package_records(self):
        spans, plan = fixture()
        plan["questions"] = [{"dimension": "official_conflict", "claims": [], "requirements": [0],
                              "reason": "Contradictory terms.", "decision": "timing"}]
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_superseded_terms_cannot_supply_fit(self):
        spans, plan = fixture()
        plan["requirements"][0]["status"] = "superseded"
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_different_task_transfer_requires_concrete_basis(self):
        spans, plan = fixture()
        plan["comparisons"][0]["relationship"] = "applicable_different_task"
        with self.assertRaises(ValueError):
            s.validate(plan, spans)

    def test_no_credit_branches_are_constrained_before_generation(self):
        spans, plan = fixture()
        plan["claims"][0]["form"] = "capability"
        pairs = s.comparison_pairs(plan)
        branches = s.comparison_schema(pairs)["properties"]["pairs"]["properties"]["C0.R0"]["anyOf"]
        self.assertEqual({b["properties"]["relationship"]["enum"][0] for b in branches}, {"unknown", "unrelated", "not_applicable"})
        for branch in branches:
            self.assertEqual(branch["properties"]["matched_work"]["enum"], [""])
        plan["claims"][0].update(form="performed_task", attribution="unresolved")
        branches = s.comparison_schema(s.comparison_pairs(plan))["properties"]["pairs"]["properties"]["C0.R0"]["anyOf"]
        self.assertEqual({b["properties"]["relationship"]["enum"][0] for b in branches}, {"unknown", "not_applicable"})

    def test_negative_audit_is_not_silently_rewritten(self):
        spans, plan = fixture()
        records = s.audit_records(s.validate(plan, spans), spans)
        verdicts = {r["id"]: {s.audit_verdict_key(r): "supported", "reason": "Fixture"} for r in records}
        verdicts["C0"]["verdict"] = "unsupported"
        result = s.validate_audit({"checks": verdicts}, records)
        self.assertFalse(result["passed"])
        self.assertIn("C0", result["errors"][0])

    def test_auditor_cannot_omit_or_rewrite_target(self):
        spans, plan = fixture()
        records = s.audit_records(s.validate(plan, spans), spans)
        with self.assertRaises(ValueError):
            s.validate_audit({"checks": {}}, records)
        verdicts = {r["id"]: {s.audit_verdict_key(r): "supported", "reason": "Fixture", "fixed_text": "changed"} for r in records}
        with self.assertRaises(ValueError):
            s.validate_audit({"checks": verdicts}, records)

    def test_plan_has_no_second_free_floating_fit_summary(self):
        schema = s.schema({"D1:0": {"kind": "package"}, "V1:0": {"kind": "profile"}})
        self.assertNotIn("interpretation", schema["properties"])
        self.assertNotIn("current_interpretation", str(schema))

    def test_code_owns_matrix_identifiers(self):
        spans, plan = fixture()
        inventory = {k: v for k, v in plan.items() if k != "comparisons"}
        s.validate(inventory, spans, inventory_only=True)
        pairs = s.comparison_pairs(inventory)
        self.assertEqual([p["id"] for p in pairs], ["C0.R0", "C0.R1", "C0.R2"])
        raw = {"pairs": {p["id"]: {k: v for k, v in e.items() if k not in {"claim", "requirement"}}
                         for p, e in zip(pairs, plan["comparisons"])}}
        self.assertEqual(s.attach_comparisons(inventory, raw, pairs, spans), plan)
        raw["pairs"]["C99.R0"] = raw["pairs"].pop("C0.R0")
        with self.assertRaises(ValueError):
            s.attach_comparisons(inventory, raw, pairs, spans)

    def test_compound_requirement_cannot_hide_unmatched_conditions(self):
        spans, plan = fixture()
        plan["requirements"] = plan["requirements"][:1]
        plan["comparisons"] = plan["comparisons"][:1]
        plan["comparisons"][0]["coverage"] = "partial"
        row = s.render(s.validate(plan, spans), spans)["uncertainties"][0]
        self.assertEqual(row["relevance"], "direct")
        self.assertEqual(row["task_alignment"]["coverage"], "partial")

    def test_unknown_audit_targets_the_withheld_decision(self):
        spans, plan = fixture()
        record = next(r for r in s.audit_records(plan, spans) if r["id"] == "E1")
        self.assertIn("withholding", record["audit_question"])

    def test_government_terms_cannot_be_strengthened_by_paraphrase(self):
        spans, plan = fixture()
        inventory = {k: v for k, v in plan.items() if k != "comparisons"}
        for r in inventory["requirements"]:
            del r["meaning"]
        result = s.validate_inventory(inventory, spans)
        self.assertEqual(result["requirements"][0]["meaning"], "Install displays.")
        inventory["requirements"][0]["meaning"] = "Only a certified installer is eligible."
        with self.assertRaisesRegex(ValueError, "code-owned"):
            s.validate_inventory(inventory, spans)

    def test_nonwork_metadata_is_never_compared_as_experience(self):
        spans, plan = fixture()
        for form in ("recency", "scale", "resource", "context", "preference"):
            value = deepcopy(plan)
            value["claims"].append({**deepcopy(value["claims"][0]), "form": form})
            s.validate(value, spans)
            self.assertEqual(len(s.comparison_pairs(value)), 3)
            row = s.render(value, spans)["uncertainties"][1]
            self.assertEqual(row["relevance"], "not_applicable")

    def test_good_question_survives_bad_judgment_but_cannot_authorize_research(self):
        from common import capture_clarification as gate
        spans, plan = fixture()
        plan["questions"] = [{"dimension": "performer_identity", "claims": [0], "requirements": [0],
                              "reason": "The performing entity requires clarification.", "decision": "attribution"}]
        audit = {"checks": [{"target_id": "Q0", "verdict": "supported", "reason": "Question is anchored."},
                            {"target_id": "C0", "verdict": "unsupported", "reason": "Rejected assertion."}],
                 "passed": False, "errors": ["C0: Rejected assertion."]}
        rendered = s.render_supported_questions(plan, spans, audit)
        self.assertEqual([r["record_type"] for r in rendered["uncertainties"]], ["question"])
        self.assertTrue(rendered["understanding_audit"]["validation_pending"])
        self.assertFalse(gate.confirmed_context({"status": "READY", **rendered}, {}))
        packet = {"sources": {s["source_id"]: s for s in spans.values()}, "technical_issues": []}
        state = gate.validate_assessment(rendered, packet)
        self.assertEqual(state["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(state["open_gaps"], [])
        rendered["uncertainties"] = []
        self.assertEqual(gate.validate_assessment(rendered, packet)["status"], "TECHNICAL_BLOCKED")

    def test_unsupported_question_is_never_released(self):
        spans, plan = fixture()
        plan["questions"] = [{"dimension": "task_meaning", "claims": [0], "requirements": [0],
                              "reason": "Unsupported question.", "decision": "experience"}]
        self.assertIsNone(s.render_supported_questions(plan, spans, {"passed": False, "checks": [], "errors": ["Rejected question"]}))

    def test_large_comparison_matrix_is_batched_without_dropping_pairs(self):
        pairs = [{"id": str(i)} for i in range(203)]
        batches = list(s.comparison_batches(pairs))
        self.assertTrue(all(len(b) <= s.MAX_COMPARISON_BATCH for b in batches))
        self.assertEqual([p for b in batches for p in b], pairs)
        with self.assertRaises(ValueError):
            s.validate_comparison_batch({"pairs": {}}, batches[-1])

    def test_separate_routing_audit_checks_original_context(self):
        spans, plan = fixture()
        record = next(r for r in s.audit_records(plan, spans) if r["id"] == "routing")
        self.assertIn("original source", record["audit_question"])

    def test_a_pricing_hint_cannot_hide_line_item_work(self):
        spans, plan = fixture()
        plan["requirements"][0].update(area="pricing", task=False)
        self.assertEqual(len(s.comparison_pairs(plan)), 3)
        row = s.render(s.validate(plan, spans), spans)["uncertainties"][0]
        self.assertEqual(row["relevance"], "direct")


if __name__ == "__main__":
    unittest.main()
