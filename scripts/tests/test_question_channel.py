"""Clarification ownership tests; mocked judgments are not semantic accuracy proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s
from common import capture_understanding as u, capture_clarification as gate


def fixture():
    spans = {
        "D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                 "text": "Inspect the cooling units."},
        "V1:0": {"kind": "profile", "source_id": "V1", "offset": 0,
                 "text": "Our prior cooling-unit project involved support; the duties are unspecified."},
    }
    quote = lambda ref: [{"ref": ref, "quote": spans[ref]["text"]}]
    requirement = {"area": "scope", "task": True, "status": "current",
                   "record_kind": "requirement", "logic": "all", "supersedes": [],
                   "focus": quote("D1:0"), "evidence": quote("D1:0"),
                   "components": [{"kind": "work", "text": "Inspect cooling units", "evidence": quote("D1:0")}]}
    claim = {"form": "work_reference", "execution": "unclear", "attribution": "self",
             "meaning": "An existing support reference with unspecified duties.",
             "unresolved_dimensions": ["task_meaning"], "evidence": quote("V1:0")}
    inventory = {"requirements": [requirement], "claims": [claim], "questions": [], "resolved_question_ids": []}
    signal = {"dimension": "task_meaning", "reason": "Existing reference duties are unclear.",
              "decision": "experience", "evidence": quote("V1:0")}
    return spans, inventory, signal


class QuestionRoutingContractTests(unittest.TestCase):
    def test_self_attributed_vague_reference_does_not_force_identity(self):
        spans, inventory, _ = fixture()
        checked = s.validate_inventory(inventory, spans, components=True)
        self.assertEqual([q["dimension"] for q in checked["questions"]], ["task_meaning"])

    def test_workshare_uncertainty_does_not_force_identity_or_duplicate_task_question(self):
        spans, inventory, _ = fixture()
        inventory["claims"][0].update(attribution="unresolved", unresolved_dimensions=["task_meaning", "workshare"])
        checked = s.validate_inventory(inventory, spans, components=True)
        self.assertEqual([q["dimension"] for q in checked["questions"]], ["workshare"])

    def test_identity_question_alone_does_not_answer_task_meaning(self):
        spans, inventory, _ = fixture()
        inventory["claims"][0].update(attribution="unresolved", unresolved_dimensions=["task_meaning", "performer_identity"])
        checked = s.validate_inventory(inventory, spans, components=True)
        self.assertEqual({q["dimension"] for q in checked["questions"]}, {"task_meaning", "performer_identity"})

    def test_production_inventory_cannot_guess_missing_ambiguity_dimension(self):
        spans, inventory, _ = fixture()
        del inventory["claims"][0]["unresolved_dimensions"]
        with self.assertRaisesRegex(ValueError, "dimension"):
            s.validate_inventory(inventory, spans, components=True)

    def test_unresolved_attribution_requires_identity_or_workshare_not_just_task_meaning(self):
        spans, inventory, _ = fixture()
        inventory["claims"][0]["attribution"] = "unresolved"
        with self.assertRaisesRegex(ValueError, "attribution"):
            s.validate_inventory(inventory, spans, components=True)

    def test_new_schema_requires_explicit_dimensions(self):
        spans, _, _ = fixture()
        claim_schema = s.inventory_schema(spans, components=True)["properties"]["claims"]["items"]
        self.assertIn("unresolved_dimensions", claim_schema["required"])

    def test_clear_service_offering_has_no_rescue_question(self):
        spans, inventory, _ = fixture()
        inventory["claims"][0].update(form="capability", execution="not_execution", unresolved_dimensions=[])
        checked = s.validate_inventory(inventory, spans, components=True)
        self.assertEqual(checked["questions"], [])

    def test_duplicate_or_unknown_dimensions_are_not_accepted(self):
        spans, inventory, _ = fixture()
        for dims in (["task_meaning", "task_meaning"], ["more_favorable_projects"]):
            with self.subTest(dims=dims), self.assertRaises(ValueError):
                inventory["claims"][0]["unresolved_dimensions"] = dims
                s.validate_inventory(inventory, spans, components=True)

    def test_modern_claim_auditor_cannot_reaudit_question_warrant(self):
        spans, inventory, _ = fixture()
        inventory = s.validate_inventory(inventory, spans, components=True)
        targets = s.audit_records({**inventory, "comparisons": []}, spans)
        self.assertFalse(any(t["kind"] in {"question", "routing"} for t in targets))
        self.assertTrue(any(t["kind"] == "claim" for t in targets))


class QuestionChannelTests(unittest.TestCase):
    def test_repeated_candidate_is_judged_once_and_receipt_preserves_both_origins(self):
        spans, _, signal = fixture()
        channel = c.QuestionChannel(spans)
        channel.add([signal], origin="independent")
        first = channel.pending_targets()
        checks = s.validate_audit({"checks": {first[0]["id"]: {"verdict": "supported", "reason": "Existing ambiguous duties."}}}, first)
        channel.accept_checks(checks)
        channel.add([deepcopy(signal)], origin="inventory")
        self.assertEqual(channel.pending_targets(), [])
        self.assertEqual(len(channel.questions()), 1)
        self.assertEqual(set(channel.receipts()[0]["origins"]), {"independent", "inventory"})
        self.assertEqual(channel.questions()[0]["question_validation"], "supported")

    def test_rejected_question_cannot_be_reintroduced_by_later_inventory(self):
        spans, _, signal = fixture()
        channel = c.QuestionChannel(spans)
        channel.add([signal], origin="independent")
        targets = channel.pending_targets()
        channel.accept_checks(s.validate_audit({"checks": {targets[0]["id"]: {"verdict": "unsupported", "reason": "Already answered."}}}, targets))
        channel.add([signal], origin="inventory")
        self.assertEqual(channel.questions(), [])
        self.assertEqual(channel.pending_targets(), [])

    def test_different_dimensions_and_distinct_references_are_not_collapsed(self):
        spans, _, signal = fixture()
        spans["V1:0"]["text"] += " A separate reference has unclear equipment duties."
        second = {**signal, "dimension": "workshare"}
        third = {**signal, "evidence": [{"ref": "V1:0", "quote": "A separate reference has unclear equipment duties."}]}
        channel = c.QuestionChannel(spans)
        channel.add([signal, second, third], origin="independent")
        self.assertEqual(len(channel.pending_targets()), 3)

    def test_unchecked_question_survives_provider_failure_but_is_labeled_pending(self):
        spans, _, signal = fixture()
        channel = c.QuestionChannel(spans)
        channel.add([signal], origin="independent")
        self.assertEqual(channel.questions()[0]["question_validation"], "pending")

    def test_uncertain_warrant_remains_visible_instead_of_becoming_a_gap(self):
        spans, _, signal = fixture()
        channel = c.QuestionChannel(spans)
        channel.add([signal], origin="independent")
        targets = channel.pending_targets()
        channel.accept_checks(s.validate_audit({"checks": {targets[0]["id"]: {"verdict": "uncertain", "reason": "Meaning remains unresolved."}}}, targets))
        self.assertEqual(channel.questions()[0]["question_validation"], "uncertain")
        self.assertTrue(channel.retained(signal))

    def test_candidate_evidence_cannot_be_invented(self):
        spans, _, signal = fixture()
        signal["evidence"][0]["quote"] = "A nonexistent project"
        with self.assertRaises(ValueError):
            c.QuestionChannel(spans).add([signal], origin="inventory")

    def test_receipts_cannot_be_overwritten_or_attached_to_another_question(self):
        spans, _, signal = fixture()
        channel = c.QuestionChannel(spans)
        channel.add([signal], origin="independent")
        targets = channel.pending_targets()
        verdicts = s.validate_audit({"checks": {targets[0]["id"]: {"verdict": "supported", "reason": "Unclear duties."}}}, targets)
        channel.accept_checks(verdicts)
        with self.assertRaises(ValueError):
            channel.accept_checks(verdicts)
        bad = deepcopy(verdicts)
        bad["checks"][0]["target_id"] = "not-this-question"
        with self.assertRaises(ValueError):
            channel.accept_checks(bad)


def pipeline_model(*, reject_required=False, fail_claim=False, fail_after_inventory=False, independent=True):
    spans, inventory, signal = fixture()
    calls = []

    def model(**kwargs):
        payload = kwargs["user_payload"]
        calls.append(payload)
        if "signals" in kwargs["response_schema"]["schema"]["properties"]:
            return {"signals": [signal] if independent else []}
        if "source_coverage" in payload:
            result = deepcopy(inventory)
            result["quoted_vendor_context"] = []
            # This spurious proposal is not an asserted claim ambiguity.
            result["questions"] = [{"dimension": "performer_identity", "claims": [0], "requirements": [],
                                    "reason": "Request legal proof.", "decision": "attribution"}]
            return result
        if "targets" in payload:
            result = {}
            for target in payload["targets"]:
                bad = (target["kind"] == "question" and (target["value"]["dimension"] == "performer_identity" or reject_required))
                bad = bad or (fail_claim and target["id"] == "C0")
                result[target["id"]] = {s.audit_verdict_key(target): "unsupported" if bad else "supported",
                                        "reason": "Not warranted by this source." if bad else "Supported by current evidence."}
            return {"checks": result}
        if isinstance(payload.get("requirements"), dict):
            if fail_after_inventory:
                return None
            return {"requirements": {key: {"logic": "all", "components": inventory["requirements"][0]["components"]}
                                     for key in payload["requirements"]}}
        if "component_job" in payload:
            job = payload["component_job"]
            return {**{k: job[k] for k in ("pair_id", "component_id", "component_text", "component_kind")},
                    "status": "ambiguous", "reason": "Existing duties are unclear.", "supported_scope": "",
                    "evidence": job["claimed"]["evidence"]}
        return {"complete": True, "facts": [{"area": "scope", "statement": "Inspect cooling units.", "refs": ["D1:0"]}],
                "coverage": [{"source_id": "D1", "finding": "Scope reviewed.", "refs": ["D1:0"]}]}

    packet = {"technical_issues": [], "sources": {r["source_id"]: r for r in spans.values()}}
    return model, calls, packet


class QuestionPipelineTests(unittest.TestCase):
    def test_inventory_only_question_is_validated_before_delivery(self):
        model, calls, packet = pipeline_model(independent=False)
        state = gate.validate_assessment(u.analyze_packet(packet, [], {}, call=model), packet)
        self.assertEqual(state["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["question_validation"], "supported")
        self.assertEqual(sum(t["kind"] == "question" for p in calls for t in p.get("targets", [])), 2)

    def test_rejected_extra_question_does_not_erase_checked_classifications(self):
        model, calls, packet = pipeline_model()
        raw = u.analyze_packet(packet, [], {}, call=model)
        state = gate.validate_assessment(raw, packet)
        self.assertEqual(state["status"], "NEEDS_CLARIFICATION")
        self.assertTrue(state["understanding_audit"]["claim_evidence"]["passed"])
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["routing_reason"], "task_meaning")
        self.assertTrue(any(row.get("claim_id") == "C0" for row in state["open_gaps"]))
        question_targets = [t for p in calls for t in p.get("targets", []) if t["kind"] == "question"]
        self.assertEqual(len(question_targets), 2)
        self.assertEqual(len({t["id"] for t in question_targets}), 2)
        self.assertFalse(state["research_authorized"])

    def test_unrelated_claim_failure_cannot_hide_valid_question(self):
        model, _, packet = pipeline_model(fail_claim=True)
        raw = u.analyze_packet(packet, [], {}, call=model)
        state = gate.validate_assessment(raw, packet)
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["question_validation"], "supported")
        self.assertFalse(state["research_authorized"])

    def test_rejected_all_questions_cannot_clear_an_unresolved_claim(self):
        model, _, packet = pipeline_model(reject_required=True)
        raw = u.analyze_packet(packet, [], {}, call=model)
        state = gate.validate_assessment(raw, packet)
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertFalse(state["research_authorized"])
        self.assertFalse(state["questions"])
        self.assertIn("unresolved", " ".join(state["technical_issues"]).lower())

    def test_validated_question_survives_later_provider_failure(self):
        model, _, packet = pipeline_model(fail_after_inventory=True)
        state = gate.validate_assessment(u.analyze_packet(packet, [], {}, call=model), packet)
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(len(state["questions"]), 1)
        self.assertEqual(state["questions"][0]["question_validation"], "supported")


if __name__ == "__main__":
    unittest.main()
