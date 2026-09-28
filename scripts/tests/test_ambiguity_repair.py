"""Bounded category repair controls; mocks test contracts, not model accuracy."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ambiguity_repair as ar, semantic_contract as c, semantic_plan as s
from common import capture_understanding as u, understanding_checkpoints as cp
from common.evidence_selection import EvidenceTransport
from common.semantic_policy import OFFICIAL_CONFLICT_POLICY
from tests.test_question_channel import pipeline_model


def selection(first, last=None):
    return {"start": {"ref": first, "line": 1}, "end": {"ref": last or first, "line": 1}}


def fixture():
    spans = {"D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                       "text": "Deliver within 30 days. Certification is required."},
             "D2:0": {"kind": "package", "source_id": "D2", "offset": 0,
                       "text": "Deliver within 90 days. Neither clause has stated precedence."},
             "V1:0": {"kind": "profile", "source_id": "V1", "offset": 0,
                       "text": "Certification details were not supplied."},
             "V2:0": {"kind": "profile", "source_id": "V2", "offset": 0,
                       "text": "Our existing inspection reference lists support without specific duties."}}
    raw = {"signals": [
        {"dimension": "official_conflict", "decision": "eligibility", "reason": "Certification information is absent.",
         "evidence": [selection("D1:0"), selection("V1:0", "V2:0")]},
        {"dimension": "task_meaning", "decision": "experience", "reason": "Existing duties are unclear.",
         "evidence": [selection("V2:0")]},
    ]}
    transport = EvidenceTransport(c.ambiguity_schema(spans), {"spans": spans})
    repair = ar.build_repair(transport, raw, "Evidence range crosses documents, fields, or source roles.")
    response = {"repairs": {"T0": [selection("V1:0")]},
                "category_reviews": {"S0": {"disposition": "missing_gap", "reason": "No credential claim exists to clarify."}}}
    return spans, raw, transport, repair, response


class BoundedSignalRepairTests(unittest.TestCase):
    def test_policy_is_wired_into_detection_inventory_warrant_and_schema(self):
        for prompt in (c.AMBIGUITY_PROMPT, c.INVENTORY_PROMPT, c.QUESTION_AUDIT_PROMPT,
                       s.INVENTORY_PROMPT, ar.REPAIR_CATEGORY_PROMPT, ar.REPAIR_AUDIT_PROMPT):
            self.assertIn(OFFICIAL_CONFLICT_POLICY, prompt)
        spans, *_ = fixture()
        self.assertEqual(c.ambiguity_schema(spans)["properties"]["signals"]["items"]["properties"]["dimension"]["description"],
                         OFFICIAL_CONFLICT_POLICY)

    def test_source_error_and_role_rule_reach_category_repair(self):
        _, _, _, repair, _ = fixture()
        self.assertIn("crosses documents", repair.payload["validation_error"])
        self.assertEqual(set(repair.payload["category_reviews"]), {"S0"})
        self.assertIn("A private assertion cannot establish", repair.payload["category_reviews"]["S0"]["source_role_rule"])

    def test_missing_gap_keeps_audit_and_unrelated_genuine_question(self):
        spans, raw, transport, repair, response = fixture()
        before = deepcopy(raw)
        merged = repair.merge(response)
        self.assertEqual(merged, {"signals": [raw["signals"][1]]})
        self.assertEqual(raw, before)
        c.validate_signals(transport.resolve(merged), spans)
        _, _, targets = repair.audit_request()
        self.assertEqual(targets[0]["original_signal"]["dimension"], "official_conflict")
        self.assertIsNone(targets[0]["corrected_signal"])
        self.assertEqual(targets[0]["disposition"], "missing_gap")
        self.assertTrue(targets[0]["original_signal"]["evidence"])

    def test_private_only_conflict_error_can_be_reviewed_without_range_repair(self):
        spans, raw, transport, _, _ = fixture()
        raw["signals"][0]["evidence"] = [selection("V1:0")]
        error = "A private assertion cannot establish a government requirement."
        repair = ar.build_repair(transport, raw, error)
        self.assertEqual(repair.payload["validation_error"], error)
        response = {"repairs": {}, "category_reviews": {"S0": {"disposition": "missing_gap", "reason": "Missing proof only."}}}
        c.validate_signals(transport.resolve(repair.merge(response)), spans)

    def test_retaining_official_category_with_private_evidence_still_fails(self):
        spans, _, transport, repair, response = fixture()
        response["category_reviews"]["S0"] = {"disposition": "retain", "dimension": "official_conflict", "reason": "Still unknown."}
        with self.assertRaisesRegex(ValueError, "private assertion"):
            c.validate_signals(transport.resolve(repair.merge(response)), spans)

    def test_genuine_vendor_ambiguity_can_use_existing_dimension(self):
        spans, raw, transport, _, _ = fixture()
        raw["signals"][0]["evidence"] = [selection("V2:0")]
        repair = ar.build_repair(transport, raw, "A private assertion cannot establish a government requirement.")
        response = {"repairs": {}, "category_reviews": {"S0": {
            "disposition": "retain", "dimension": "task_meaning", "reason": "Existing reference duties are unclear."}}}
        result = c.validate_signals(transport.resolve(repair.merge(response)), spans)
        self.assertEqual(result[0]["dimension"], "task_meaning")
        self.assertEqual(result[0]["decision"], raw["signals"][0]["decision"])

    def test_real_government_conflict_retains_both_sides(self):
        spans, raw, transport, _, _ = fixture()
        raw["signals"][0].update(decision="timing", reason="30 and 90 days conflict.",
                                 evidence=[selection("D1:0"), selection("D2:0")])
        repair = ar.build_repair(transport, raw, "Review source role after range correction elsewhere.")
        response = {"repairs": {}, "category_reviews": {"S0": {
            "disposition": "retain", "dimension": "official_conflict", "reason": "30 and 90 days conflict without precedence."}}}
        result = c.validate_signals(transport.resolve(repair.merge(response)), spans)
        self.assertEqual({a["ref"] for a in result[0]["evidence"]}, {"D1:0", "D2:0"})

    def test_edit_cannot_add_category_or_rewrite_decision_or_facts(self):
        for change in ({"dimension": "vendor_ambiguity"}, {"decision": "scope"}, {"evidence": []}, {"matched_work": "certified"}):
            _, _, _, repair, response = fixture()
            response["category_reviews"]["S0"] = {"disposition": "retain", "dimension": "certificate_scope", "reason": "Source-based reason", **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                repair.merge(response)

    def test_missing_or_extra_review_ids_and_erased_selections_rejected(self):
        for name in ("missing", "extra", "erased"):
            _, _, _, repair, response = fixture()
            if name == "missing":
                response["category_reviews"] = {}
            elif name == "extra":
                response["category_reviews"]["S1"] = deepcopy(response["category_reviews"]["S0"])
            else:
                response["repairs"]["T0"] = []
            with self.subTest(name=name), self.assertRaises(ValueError):
                repair.merge(response)

    def test_receipt_reconstruction_preserves_negative_verdict_and_detects_changed_wire(self):
        for verdict in ("supported", "unsupported", "uncertain"):
            _, _, transport, repair, response = fixture()
            raw = repair.merge(response)
            _, _, targets = repair.audit_request()
            checked = s.validate_audit({"checks": {"S0": {"verdict": verdict, "reason": "Test verdict."}}}, targets)
            receipt = repair.receipt(checked)
            self.assertEqual(ar.restore_receipt(transport, raw, receipt)["passed"], verdict == "supported")
            with self.assertRaisesRegex(ValueError, "reproduce"):
                ar.restore_receipt(transport, {"signals": []}, receipt)

    def test_audit_metadata_has_integrity_and_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            store = cp.StageCheckpoints(folder, scope={}, runtime="test")
            store.save("key", {}, stage="test", audit_metadata={"verdict": "unsupported"})
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                store.save("key", {}, stage="test", audit_metadata={"verdict": "supported"})
            path = Path(folder) / "key.json"
            row = json.loads(path.read_text())
            row["audit_metadata"]["verdict"] = "supported"
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "integrity"):
                store.load("key")


class PipelineRepairTests(unittest.TestCase):
    def provider(self, verdict):
        base, _, packet = pipeline_model()
        packet["sources"]["V2"] = {"kind": "profile", "source_id": "V2", "offset": 0,
                                     "text": "Qualification details were not provided."}
        calls = []
        def model(**request):
            payload, schema = request["user_payload"], request["response_schema"]["schema"]
            calls.append(payload)
            if "category_reviews" in payload:
                reference = selection("V1:0")
                reference["end"]["line"] = 2
                return {"repairs": {"T0": [reference]}, "category_reviews": {
                    "S0": {"disposition": "retain", "dimension": "task_meaning", "reason": "Existing reference duties are unclear."},
                    "S1": {"disposition": "missing_gap", "reason": "No qualification information exists to clarify."}}}
            if payload.get("targets", [{}])[0].get("kind") == "ambiguity_repair":
                return {"checks": {t["id"]: {"verdict": verdict, "reason": "Synthetic audit verdict."} for t in payload["targets"]}}
            if "signals" in schema["properties"]:
                return {"signals": [
                    {"dimension": "task_meaning", "reason": "Unclear duties.", "decision": "experience",
                     "evidence": [selection("V1:0", "V2:0")]},
                    {"dimension": "official_conflict", "reason": "Qualification is missing.", "decision": "eligibility",
                     "evidence": [selection("V2:0")]},
                ]}
            return base(**request)
        return model, packet, calls

    def test_repaired_pipeline_and_restart_preserve_receipt(self):
        model, packet, calls = self.provider("supported")
        with tempfile.TemporaryDirectory() as folder:
            first = u.analyze_packet(packet, [], {}, call=model, checkpoint_dir=folder)
            self.assertNotIn("pipeline_errors", first)
            self.assertEqual(sum("category_reviews" in p for p in calls), 1)
            receipt = next(s["bounded_signal_repair"] for s in first["understanding_audit"]["stages"] if "bounded_signal_repair" in s)
            again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Must reuse audited receipts"), checkpoint_dir=folder)
            self.assertNotIn("pipeline_errors", again)
            resumed = next(s["bounded_signal_repair"] for s in again["understanding_audit"]["stages"] if "bounded_signal_repair" in s)
            self.assertEqual(receipt, resumed)
            self.assertEqual(first["independent_questions"], again["independent_questions"])
            self.assertEqual(len(first["independent_questions"]), 1)

    def test_negative_or_uncertain_repair_audit_blocks_without_retry_even_after_restart(self):
        for verdict in ("unsupported", "uncertain"):
            model, packet, calls = self.provider(verdict)
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as folder:
                first = u.analyze_packet(packet, [], {}, call=model, checkpoint_dir=folder)
                self.assertIn("repair rejected", first["pipeline_errors"][0])
                self.assertEqual(len(calls), 3)
                self.assertFalse(any(s["stage"].startswith("extract-") for s in first["understanding_audit"]["stages"]))
                again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Negative audit must not resample"), checkpoint_dir=folder)
                self.assertEqual(first["pipeline_errors"], again["pipeline_errors"])


if __name__ == "__main__":
    unittest.main()
