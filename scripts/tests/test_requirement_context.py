"""Evidence-link contracts; mocked approvals are not model-accuracy evidence."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import requirement_context as rc, semantic_contract as c, semantic_plan as s
from common import capture_understanding as u
from tests.test_question_channel import pipeline_model, fixture as old_fixture
from tests.evidence_wire_fixture import fixture_category


def fixture():
    spans = {
        "D0:0": {"kind": "package", "source_id": "D0", "offset": 0,
                  "text": "Install panels. Use certified lifting equipment. Installation is fixed-price."},
        "D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                  "text": "The installation acceptance check requires a signed equipment register."},
        "V0:0": {"kind": "profile", "source_id": "V0", "offset": 0,
                  "text": "Our staff installed panels."},
    }
    anchor = {"ref": "D0:0", "quote": spans["D0:0"]["text"]}
    parent = {"area": "scope", "task": True, "status": "current", "record_kind": "requirement",
              "supersedes": [], "evidence": [anchor], "focus": [{"ref": "D0:0", "quote": "Install panels."}]}
    inventory = {"requirements": [parent], "claims": [], "quoted_vendor_context": [],
                 "questions": [], "resolved_question_ids": []}
    inventory = s.validate_inventory(inventory, spans, components=True, defer_components=True, require_context=True)
    return spans, inventory


def ready(ctx, text="Install panels", kind="work"):
    return {"status": "complete", "logic": "all", "components": [
        {**fixture_category({"kind": kind}), "kind": kind, "text": text, "evidence_ids": [next(iter(ctx["evidence_catalog"]))]}]}


class ParentInventoryTests(unittest.TestCase):
    def test_production_parent_assembled_once_from_explicit_declarations(self):
        spans, inv = fixture()
        raw = deepcopy(inv)
        row = raw["requirements"][0]
        row.pop("meaning")
        row["supporting_context"] = [{"ref": "D0:0", "quote": "Use certified lifting equipment."}]
        row.pop("evidence")
        before = deepcopy(raw)
        checked = rc.validate_parent_inventory(raw, spans)
        self.assertEqual(checked["requirements"][0]["meaning"], "Install panels.")
        self.assertTrue(c._contained(row["focus"], checked["requirements"][0]["evidence"]))
        self.assertEqual(raw, before)
        schema = rc.parent_inventory_schema(spans)
        self.assertNotIn("evidence", schema["properties"]["requirements"]["items"]["properties"])
        self.assertIn("supporting_context", schema["properties"]["requirements"]["items"]["required"])

    def test_duplicate_legacy_parent_list_and_private_focus_are_rejected(self):
        spans, inv = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            rc.validate_parent_inventory(inv, spans)
        raw = deepcopy(inv)
        row = raw["requirements"][0]
        row.pop("meaning")
        row["supporting_context"] = row.pop("evidence")
        row["focus"] = [{"ref": "V0:0", "quote": spans["V0:0"]["text"]}]
        with self.assertRaisesRegex(ValueError, "private"):
            rc.validate_parent_inventory(raw, spans)

    def test_schema_defers_only_components_preserving_other_protections(self):
        spans, _ = fixture()
        schema = s.inventory_schema(spans, components=True, defer_components=True)
        req = schema["properties"]["requirements"]["items"]["properties"]
        self.assertNotIn("components", req)
        self.assertNotIn("logic", req)
        self.assertTrue({"focus", "evidence", "status", "record_kind", "supersedes"}.issubset(req))
        self.assertIn("quoted_vendor_context", schema["required"])
        self.assertIn("unresolved_dimensions", schema["properties"]["claims"]["items"]["required"])

    def test_inventory_cannot_pre_generate_components(self):
        spans, inv = fixture()
        raw = deepcopy(inv)
        raw["requirements"][0].pop("meaning")
        raw["requirements"][0]["components"] = []
        with self.assertRaisesRegex(ValueError, "pre-generate"):
            s.validate_inventory(raw, spans, components=True, defer_components=True)

    def test_pending_inventory_cannot_bypass_final_validation(self):
        spans, inv = fixture()
        with self.assertRaisesRegex(ValueError, "requirement shape"):
            s.validate({**inv, "comparisons": []}, spans)
        with self.assertRaisesRegex(ValueError, "cannot enter"):
            s.validate({**inv, "comparisons": []}, spans, pending_decomposition=True)

    def test_bad_parent_focus_still_rejected(self):
        spans, inv = fixture()
        raw = deepcopy(inv)
        row = raw["requirements"][0]
        row.pop("meaning")
        row["evidence"] = [{"ref": "D0:0", "quote": "Installation is fixed-price."}]
        with self.assertRaisesRegex(ValueError, "focus"):
            s.validate_inventory(raw, spans, components=True, defer_components=True)

    def test_precedence_is_retained_before_decomposition(self):
        spans, inv = fixture()
        spans["D2:0"] = {"kind": "package", "source_id": "D2", "offset": 0,
                          "text": "Amendment replaces the old 40-day term with 75 days."}
        parent = inv["requirements"][0]
        parent.pop("meaning")
        parent.update(evidence=[{"ref": "D2:0", "quote": spans["D2:0"]["text"]}],
                      focus=[{"ref": "D2:0", "quote": "old 40-day term"}], area="timing")
        rule = deepcopy(parent)
        rule.update(record_kind="precedence_rule", supersedes=[0], focus=deepcopy(parent["evidence"]))
        inv["requirements"].append(rule)
        validated = s.validate_inventory(inv, spans, components=True, defer_components=True)
        self.assertEqual([r["status"] for r in validated["requirements"]], ["superseded", "current"])

    def test_prompt_keeps_claim_and_package_reference_policies(self):
        prompt = rc.parent_inventory_prompt()
        self.assertNotIn("Decompose every requirement", prompt)
        self.assertIn(c.CLAIM_RULES, prompt)
        self.assertIn(c.GROUNDING_RULES, prompt)
        self.assertIn("PARENT INVENTORY STAGE", prompt)


class ScopedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.spans, self.inv = fixture()
        self.ctx = rc.context("R0", self.inv["requirements"][0], self.spans)

    def test_same_text_in_another_parent_is_not_the_same_choice(self):
        other = rc.context("R1", self.inv["requirements"][0], self.spans)
        row = ready(other)
        with self.assertRaisesRegex(ValueError, "parent"):
            rc.validate_decomposition({"requirements": {"R0": row}}, [self.ctx], self.spans)
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"requirements": {"R0": row}}, rc.decomposition_schema([self.ctx]))

    def test_code_attaches_exact_original_quotes_without_mutating_parent(self):
        before = deepcopy(self.ctx)
        response = {"requirements": {"R0": ready(self.ctx)}}
        out = rc.validate_decomposition(response, [self.ctx], self.spans)
        self.assertEqual(out["R0"]["components"][0]["evidence"], self.ctx["parent"]["evidence"])
        self.assertEqual(self.ctx, before)
        out["R0"]["components"][0]["evidence"][0]["quote"] = "changed"
        self.assertEqual(self.ctx, before)

    def test_multiple_adjacent_source_pieces_remain_available(self):
        parent = deepcopy(self.inv["requirements"][0])
        parent["evidence"].append({"ref": "D1:0", "quote": self.spans["D1:0"]["text"]})
        ctx = rc.context("R0", parent, self.spans)
        row = ready(ctx)
        row["components"][0]["evidence_ids"] = list(ctx["evidence_catalog"])
        out = rc.validate_decomposition({"requirements": {"R0": row}}, [ctx], self.spans)
        self.assertEqual(out["R0"]["components"][0]["evidence"], parent["evidence"])

    def test_same_fragment_does_not_admit_neighboring_paragraph(self):
        parent = deepcopy(self.inv["requirements"][0])
        parent["evidence"] = deepcopy(parent["focus"])
        ctx = rc.context("R0", parent, self.spans)
        self.assertEqual(list(ctx["evidence_catalog"].values()), parent["focus"])
        row = ready(ctx)
        row["components"][0]["evidence"] = [{"ref": "D0:0", "quote": "Installation is fixed-price."}]
        with self.assertRaisesRegex(ValueError, "never type"):
            rc.validate_decomposition({"requirements": {"R0": row}}, [ctx], self.spans)

    def test_valid_ids_do_not_satisfy_the_semantic_auditor(self):
        row = ready(self.ctx, "Installation is time-and-materials", "pricing")
        rc.validate_decomposition({"requirements": {"R0": row}}, [self.ctx], self.spans)
        checked = s.validate_audit({"checks": {"R0": {"verdict": "unsupported", "reason": "Source says fixed-price."}}},
                                  [{"id": "R0", "kind": "requirement"}])
        self.assertFalse(checked["passed"])

    def test_empty_duplicate_unknown_and_malformed_ids_fail(self):
        for ids in ([], ["invented"], [1], [next(iter(self.ctx["evidence_catalog"]))] * 2):
            row = ready(self.ctx)
            row["components"][0]["evidence_ids"] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                rc.validate_decomposition({"requirements": {"R0": row}}, [self.ctx], self.spans)

    def test_no_omitted_parent_or_smuggled_context_component(self):
        for raw in ({"requirements": {}}, {"requirements": {"R0": {
                "status": "needs_context", "reason": "Missing clause", "query": "cross-reference",
                "components": []}}}):
            with self.assertRaises(ValueError):
                rc.validate_decomposition(raw, [self.ctx], self.spans)

    def test_batching_preserves_every_parent_without_truncation(self):
        contexts = [rc.context(f"R{i}", self.inv["requirements"][0], self.spans) for i in range(13)]
        batches = list(rc.batches(contexts))
        self.assertEqual([len(b) for b in batches], [4, 4, 4, 1])
        self.assertEqual([c["id"] for b in batches for c in b], [c["id"] for c in contexts])
        with patch.object(rc, "MAX_BATCH_CHARS", 10), self.assertRaisesRegex(ValueError, "no source was truncated"):
            list(rc.batches(contexts))


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.spans, self.inv = fixture()
        self.ctx = rc.context("R0", self.inv["requirements"][0], self.spans)
        self.proposal = {"status": "proposed", "reason": "Adds the referenced acceptance check.",
                         "additions": [{"ref": "D1:0", "quote": self.spans["D1:0"]["text"]}]}

    def test_expansion_preserves_focus_status_and_precedence(self):
        approved = rc.approve_expansion(self.ctx, self.proposal, {"verdict": "supported"}, self.spans)
        self.assertNotEqual(approved["context_sha256"], self.ctx["context_sha256"])
        for key in ("focus", "meaning", "status", "supersedes", "record_kind"):
            self.assertEqual(approved["parent"][key], self.ctx["parent"][key])
        self.assertEqual(len(self.ctx["parent"]["evidence"]), 1)

    def test_rejected_or_uncertain_additions_never_attach(self):
        for verdict in ("unsupported", "uncertain"):
            before = deepcopy(self.ctx)
            with self.assertRaisesRegex(ValueError, "unapproved"):
                rc.approve_expansion(self.ctx, self.proposal, {"verdict": verdict}, self.spans)
            self.assertEqual(self.ctx, before)

    def test_profile_or_invented_or_existing_quote_not_additional_package_context(self):
        for anchor in ({"ref": "V0:0", "quote": self.spans["V0:0"]["text"]},
                       {"ref": "D1:0", "quote": "Invented certification"},
                       self.ctx["parent"]["evidence"][0]):
            bad = {**self.proposal, "additions": [anchor]}
            with self.assertRaises(ValueError):
                rc.validate_expansion(bad, self.ctx, self.spans)

    def run_flow(self, *, verdict="supported", unavailable=False, repeat=False):
        calls, receipts = [], []
        def invoke(stage, prompt, payload, schema, validate):
            calls.append((stage, deepcopy(payload)))
            if stage.startswith("context-select"):
                raw = ({"status": "unavailable", "reason": "Not in package", "additions": []}
                       if unavailable else self.proposal)
            elif stage.startswith("context-audit"):
                self.assertNotIn("V0:0", payload["spans"])
                raw = {"verdict": verdict, "reason": "Independent test verdict"}
            elif stage.endswith("expanded") and not repeat:
                ctx = rc.approve_expansion(self.ctx, self.proposal, {"verdict": "supported"}, self.spans)
                raw = {"requirements": {"R0": ready(ctx)}}
            else:
                raw = {"requirements": {"R0": {"status": "needs_context", "reason": "Need acceptance cross-reference",
                                               "query": "installation acceptance register"}}}
            return validate(raw)
        return calls, receipts, lambda: rc.decompose(self.inv, self.spans, invoke, receipts)

    def test_explicit_request_proposal_audit_then_completion(self):
        calls, receipts, run = self.run_flow()
        out = run()
        self.assertEqual(len(out["requirements"][0]["evidence"]), 2)
        self.assertEqual([stage for stage, _ in calls], ["requirement-decomposition-1", "context-select-R0",
                                                       "context-audit-R0", "requirement-decomposition-R0-expanded"])
        self.assertIn("context_expansion_accepted", [r["event"] for r in receipts])

    def test_negative_verdict_does_not_resample_or_continue(self):
        calls, receipts, run = self.run_flow(verdict="unsupported")
        with self.assertRaisesRegex(ValueError, "unapproved"):
            run()
        self.assertEqual(len(calls), 3)
        self.assertEqual(receipts[-1]["verdict"], "unsupported")

    def test_unavailable_and_repeat_requests_stop_without_erasure(self):
        for options, message in (({"unavailable": True}, "unavailable"), ({"repeat": True}, "still missing")):
            calls, receipts, run = self.run_flow(**options)
            with self.assertRaisesRegex(ValueError, message):
                run()
            self.assertEqual(self.inv["requirements"][0]["evidence"], self.ctx["parent"]["evidence"])

    def test_expansion_budget_never_truncates_requirements(self):
        calls, receipts, run = self.run_flow()
        with patch.object(rc, "MAX_CONTEXT_EXPANSIONS", 0), self.assertRaisesRegex(ValueError, "budget exhausted"):
            run()
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipts[-1]["event"], "context_requested")


class PipelineTests(unittest.TestCase):
    def test_inventory_has_no_components_and_decomposition_runs_once(self):
        provider, calls, packet = pipeline_model()
        result = u.analyze_packet(packet, [], {}, call=provider)
        self.assertNotIn("pipeline_errors", result)
        stages = result["understanding_audit"]["stages"]
        inventory = next(s for s in stages if s["stage"].startswith("semantic-inventory-package-"))
        self.assertNotIn("components", inventory["response"]["requirements"][0])
        self.assertEqual(sum(s["stage"].startswith("requirement-decomposition") for s in stages), 1)
        self.assertTrue(result["understanding_audit"]["requirement_contexts"])
        self.assertTrue(result["understanding_audit"]["claim_evidence"]["passed"])


if __name__ == "__main__":
    unittest.main()
