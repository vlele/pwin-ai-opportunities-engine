"""Structural guarantees and negative controls, not a promise of model infallibility."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s
from test_semantic_contract import fixture
from test_semantic_policy_alignment import conflict_fixture


class PackageReferenceTests(unittest.TestCase):
    def inventory(self):
        spans, plan = conflict_fixture()
        raw = {k: deepcopy(v) for k, v in plan.items() if k != "comparisons"}
        for r in raw["requirements"]:
            r.pop("meaning")
        raw["quoted_vendor_context"] = []
        spans["D2:0"] = {"kind": "package", "source_id": "D2", "offset": 0,
                          "text": "A cited offeror reference describes equipment support without naming tasks."}
        raw["quoted_vendor_context"].append({"meaning": "The package cites an undefined equipment-support reference.",
            "evidence": [{"ref": "D2:0", "quote": spans["D2:0"]["text"]}]})
        return spans, raw

    def test_schema_requires_explicit_package_reference_array(self):
        spans, _ = self.inventory()
        self.assertIn("quoted_vendor_context", s.inventory_schema(spans, components=True)["required"])

    def test_production_rejects_missing_context_slot(self):
        spans, raw = self.inventory()
        raw.pop("quoted_vendor_context")
        with self.assertRaises(ValueError):
            s.validate_inventory(raw, spans, components=True, require_context=True)

    def test_package_context_survives_as_its_own_audited_source_role(self):
        spans, raw = self.inventory()
        plan = s.validate_inventory(raw, spans, components=True, require_context=True)
        records = s.audit_records({**plan, "comparisons": []}, spans)
        context = next(r for r in records if r["kind"] == "package_reference")
        coverage = next(r for r in records if r["kind"] == "package_coverage")
        self.assertEqual(context["value"], raw["quoted_vendor_context"][0])
        self.assertIn(context["value"], coverage["value"]["quoted_vendor_context"])
        self.assertEqual(context["audit_dimension"], "source_fidelity")
        self.assertNotIn("V1:0", c.audit_payload([context], spans)["spans"])
        self.assertEqual(plan["claims"], s.validate_inventory({k: v for k, v in raw.items() if k != "quoted_vendor_context"}, spans, components=True)["claims"])

    def test_profile_cannot_replace_package_reference_provenance(self):
        spans, raw = self.inventory()
        raw["quoted_vendor_context"][0]["evidence"] = [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]
        with self.assertRaises(ValueError):
            s.validate_inventory(raw, spans, components=True, require_context=True)

    def test_empty_explicit_context_cannot_be_rescued_by_a_package_claim(self):
        spans, raw = self.inventory()
        plan = s.validate_inventory(raw, spans, components=True, require_context=True)
        plan["claims"][0]["evidence"] = raw["quoted_vendor_context"][0]["evidence"]
        plan["quoted_vendor_context"] = []
        coverage = next(r for r in s.audit_records({**plan, "comparisons": []}, spans)
                        if r["kind"] == "package_coverage")
        self.assertEqual(coverage["value"]["quoted_vendor_context"], [])
        checked = s.validate_audit({"checks": {coverage["id"]: {
            "verdict": "unsupported", "reason": "Package reference is absent from structured context."}}}, [coverage])
        self.assertFalse(checked["passed"])


class ComponentBindingTests(unittest.TestCase):
    def jobs(self):
        spans, requirement, claim, findings = fixture()
        pair = {"id": "C0.R0", "claim": 0, "requirement": 0, "required": requirement, "claimed": claim}
        return spans, pair, list(c.component_jobs([pair])), findings

    def response(self, job, finding):
        return {"pair_id": job["pair_id"], "component_id": job["component_id"],
                "component_kind": job["component_kind"],
                "supported_scope": "Install panels" if finding["status"] == "matched" else "", **deepcopy(finding)}

    def test_each_call_has_one_named_component_not_a_sibling_array(self):
        _, _, jobs, _ = self.jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["component_text"], "Install panels")
        self.assertEqual(jobs[1]["component_text"], "certified lifting equipment")
        for job in jobs:
            self.assertNotIn("components", job)
            self.assertNotIn("required", job)
            schema = c.component_response_schema(job)
            self.assertNotIn("component_text", schema["properties"])
            for field in ("pair_id", "component_id", "component_kind"):
                self.assertEqual(schema["properties"][field]["enum"], [job[field]])

    def test_wrong_pair_id_component_id_text_and_kind_are_rejected(self):
        spans, _, jobs, findings = self.jobs()
        for field in ("pair_id", "component_id", "component_text", "component_kind"):
            result = self.response(jobs[0], findings["K0"])
            result[field] = "wrong-target"
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.validate_component_response(result, jobs[0], spans)

    def test_schema_prevents_whole_span_quote_from_replacing_declared_claim(self):
        spans, _, jobs, findings = self.jobs()
        response = self.response(jobs[0], findings["K0"])
        jsonschema.validate(response, c.component_response_schema(jobs[0]))
        response["evidence"] = [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(response, c.component_response_schema(jobs[0]))

    def test_schema_couples_quote_with_its_own_ref(self):
        spans, _, jobs, findings = self.jobs()
        spans["V2:0"] = {"kind": "profile", "source_id": "V2", "offset": 0, "text": "Our crews also installed doors."}
        jobs[0]["claimed"]["evidence"].append({"ref": "V2:0", "quote": spans["V2:0"]["text"]})
        response = self.response(jobs[0], findings["K0"])
        response["evidence"] = [{"ref": "V2:0", "quote": "Our employees installed panels."}]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(response, c.component_response_schema(jobs[0]))

    def test_silence_on_qualification_preserves_partial_core_fit(self):
        spans, pair, jobs, findings = self.jobs()
        bound = {j["component_id"]: c.validate_component_response(self.response(j, findings[j["component_id"]]), j, spans)
                 for j in jobs}
        result = c.aggregate_components(pair["required"], pair["claimed"], bound, spans)
        self.assertEqual((result["relationship"], result["fit_label"]), ("same_task", "Partial Fit"))
        self.assertEqual(result["unknown_components"], ["K1"])

    def test_reassembly_cannot_swap_correctly_bound_findings(self):
        spans, pair, jobs, findings = self.jobs()
        bound = [c.validate_component_response(self.response(j, findings[j["component_id"]]), j, spans)
                 for j in jobs]
        with self.assertRaisesRegex(ValueError, "binding"):
            c.aggregate_components(pair["required"], pair["claimed"], {"K0": bound[1], "K1": bound[0]}, spans)

    def test_timing_silence_preserves_partial_fit_but_unrelated_work_does_not(self):
        spans, pair, jobs, findings = self.jobs()
        spans["D1:0"]["text"] += " Finish within eight hours."
        pair["required"]["components"][1] = {"kind": "timing", "text": "Finish within eight hours",
            "evidence": [{"ref": "D1:0", "quote": "Finish within eight hours"}]}
        findings["K1"] = {"status": "missing", "reason": "No duration supplied.", "evidence": []}
        result = c.aggregate_components(pair["required"], pair["claimed"], findings, spans)
        self.assertEqual((result["fit_label"], result["met_components"], result["unknown_components"]),
                         ("Partial Fit", ["K0"], ["K1"]))
        spans["V1:0"]["text"] = "Our staff deliver floral arrangements."
        pair["claimed"]["evidence"] = [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]
        findings["K0"] = {"status": "unrelated", "reason": "Floral delivery does not establish panel installation.",
                          "evidence": pair["claimed"]["evidence"]}
        result = c.aggregate_components(pair["required"], pair["claimed"], findings, spans)
        self.assertEqual((result["fit_label"], result["met_components"]), ("Unrelated", []))

    def test_unrelated_cannot_replace_silence_on_a_condition(self):
        spans, _, jobs, findings = self.jobs()
        result = self.response(jobs[1], {**findings["K1"], "status": "unrelated", "evidence": jobs[1]["claimed"]["evidence"]})
        with self.assertRaises(ValueError):
            c.validate_component_response(result, jobs[1], spans)

    def test_bound_text_does_not_excuse_a_semantically_wrong_reason(self):
        spans, pair, jobs, findings = self.jobs()
        result = self.response(jobs[0], findings["K0"])
        result["reason"] = "The certificate is absent."
        # Structural checks cannot prove natural-language entailment. The audit must still reject it.
        c.validate_component_response(result, jobs[0], spans)
        records = [{"id": "E0", "kind": "comparison", "value": result, "required": pair["required"]}]
        checked = s.validate_audit({"checks": {"E0": {"verdict": "unsupported", "reason": "Reason addresses the wrong component."}}}, records)
        self.assertFalse(checked["passed"])


class IntentProvenanceTests(unittest.TestCase):
    def signals(self):
        first = 'Schedule A says "ten days".'
        second = 'Schedule B says "thirty days".'
        text = first + " " + second
        spans = {"D1:0": {"kind": "package", "source_id": "D1", "offset": 0, "text": text}}
        signal = {"dimension": "official_conflict", "decision": "timing", "reason": "Conflicting periods need authority.",
                  "evidence": [{"ref": "D1:0", "quote": first}, {"ref": "D1:0", "quote": second}]}
        whole = {**deepcopy(signal), "evidence": [{"ref": "D1:0", "quote": text}]}
        return spans, signal, whole

    def test_split_and_whole_quotes_merge_after_independent_warrant_checks(self):
        spans, split, whole = self.signals()
        channel = c.QuestionChannel(spans)
        for origin, signal in (("independent", split), ("inventory", whole)):
            channel.add([signal], origin=origin)
            targets = channel.pending_targets()
            channel.accept_checks(s.validate_audit({"checks": {t["id"]: {"verdict": "supported", "reason": "Unresolved timing."} for t in targets}}, targets))
        rows = channel.questions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["question_receipt_ids"]), 2)
        self.assertIn(spans["D1:0"]["text"], rows[0]["question"])
        self.assertTrue(channel.retained(split))
        self.assertTrue(channel.retained(whole))

    def test_quote_boundary_punctuation_does_not_change_question_identity(self):
        spans, _, whole = self.signals()
        clipped = deepcopy(whole)
        clipped["evidence"][0]["quote"] = spans["D1:0"]["text"].rstrip(".")
        self.assertEqual(c.question_provenance_key(whole, spans), c.question_provenance_key(clipped, spans))

    def test_unicode_quote_boundaries_and_anchor_order_do_not_change_identity(self):
        spans, split, whole = self.signals()
        text = "\u201c" + spans["D1:0"]["text"] + "\u201d"
        spans["D1:0"]["text"] = text
        whole["evidence"][0]["quote"] = text
        split["evidence"].reverse()
        self.assertEqual(c.question_provenance_key(whole, spans), c.question_provenance_key(split, spans))

    def test_same_question_with_multiple_consequences_keeps_receipts_but_merges_display(self):
        spans, _, whole = self.signals()
        other = {**deepcopy(whole), "decision": "acceptance"}
        channel = c.QuestionChannel(spans)
        channel.add([whole, other], origin="test")
        self.assertEqual(len(channel.receipts()), 2)
        self.assertEqual(len(channel.questions()), 1)
        self.assertEqual(channel.questions()[0]["affected_decisions"], ["acceptance", "timing"])

    def test_distinct_missing_information_intents_do_not_merge_on_the_same_passage(self):
        spans, _, whole = self.signals()
        other = {**deepcopy(whole), "dimension": "requirement_meaning"}
        channel = c.QuestionChannel(spans)
        channel.add([whole, other], origin="test")
        self.assertEqual(len(channel.questions()), 2)

    def test_repeated_quote_locations_are_not_guessed(self):
        spans, _, whole = self.signals()
        text = spans["D1:0"]["text"]
        spans["D1:0"]["text"] = text + " " + text
        other = deepcopy(whole)
        other["evidence"][0]["quote"] = text.rstrip(".")
        self.assertNotEqual(c.question_provenance_key(whole, spans), c.question_provenance_key(other, spans))

    def test_distinct_source_passages_and_intents_do_not_merge(self):
        spans, split, whole = self.signals()
        left = {**deepcopy(split), "evidence": split["evidence"][:1]}
        right = {**deepcopy(split), "evidence": split["evidence"][1:]}
        other_intent = {**whole, "dimension": "requirement_meaning"}
        keys = [c.question_provenance_key(x, spans) for x in (left, right, whole, other_intent)]
        self.assertEqual(len(set(keys)), 4)

    def test_conflicting_warrants_do_not_become_supported_through_merge(self):
        spans, split, whole = self.signals()
        channel = c.QuestionChannel(spans)
        for signal, verdict in ((split, "unsupported"), (whole, "supported")):
            channel.add([signal], origin="test")
            targets = channel.pending_targets()
            channel.accept_checks(s.validate_audit({"checks": {t["id"]: {"verdict": verdict, "reason": "Fixture warrant."} for t in targets}}, targets))
        rows = channel.questions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question_validation"], "uncertain")
        self.assertTrue(rows[0]["warrant_conflict"])


if __name__ == "__main__":
    unittest.main()
