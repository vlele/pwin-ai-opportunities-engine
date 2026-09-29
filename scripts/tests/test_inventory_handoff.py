"""Structural handoff regressions; mocked auditors do not prove model accuracy."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, semantic_plan as s
from common import audit_partitioning as partitions, requirement_routing as routing


def fixture():
    texts = ["The maximum term including options is 42 months.",
             "Form ZX-17 is required before staff may access the facility.",
             "Subscriber means the organization authorized to use the product."]
    spans = {f"D{i}:0": {"source_id": f"D{i}", "kind": "package", "offset": 0,
             "source_offset": i * 1000, "document_id": "synthetic", "text": text}
             for i, text in enumerate(texts)}
    spans["V0:0"] = {"source_id": "V0", "kind": "profile", "offset": 0,
                      "text": "We offer general technology solutions. No project history was supplied."}
    facts = [{"area": "scope", "statement": text, "refs": [f"D{i}:0"]}
             for i, text in enumerate(texts)]
    return facts, spans


def response(batch):
    rows = []
    for fid, fact in batch["payload"]["fact_ledger"].items():
        anchors = [{"ref": r, "quote": batch["payload"]["spans"][r]["text"]} for r in fact["refs"]]
        rows.append({"area": fact["area"], "task": False, "status": "current",
                     "record_kind": "metadata", "supersedes": [], "focus": anchors,
                     "supporting_context": [], "originating_fact_ids": [fid]})
    return {"requirements": rows, "claims": [], "quoted_vendor_context": [],
            "questions": [], "resolved_question_ids": []}


class LedgerHandoffTests(unittest.TestCase):
    def test_exact_duplicate_records_merge_without_losing_fact_ownership(self):
        facts, spans = fixture()
        facts = [facts[0], deepcopy(facts[0])]
        batches = [b for b in h.prepare(facts, spans, max_facts=1) if b['mode'] == 'package']
        inv, receipt = h.merge([(b, h.validate_batch(response(b), b)) for b in batches], spans)
        self.assertEqual(len(inv['requirements']), 1)
        self.assertEqual(set(receipt['fact_coverage']), {'F0', 'F1'})
        self.assertEqual(receipt['fact_coverage']['F0'], receipt['fact_coverage']['F1'])

    def test_unrelated_families_keep_thresholds_denials_and_definitions(self):
        for text in ('Deliver food at or below 4 C; do not use ambient storage.',
                     'Calibrate meters before release; release is not calibration.',
                     'Complete shoreline sampling within 11 days after vessel access.',
                     'Subscriber means the named organization, not its supplier.',
                     'Provide a restoration plan 6 days after emergency activation.'):
            facts, spans = fixture()
            spans['D0:0']['text'] = text
            facts = [{'area': 'scope', 'statement': text, 'refs': ['D0:0']}]
            b = next(b for b in h.prepare(facts, spans) if b['mode'] == 'package')
            mapped = h.validate_batch(response(b), b)
            t = h.handoff_targets(b, mapped)[0]
            with self.subTest(text=text):
                self.assertEqual(t['fact']['statement'], text)
                self.assertEqual(t['retained_records'][0]['meaning'], text)

    def test_fragment_cannot_bypass_final_nonempty_requirement_gate(self):
        with self.assertRaises(ValueError):
            s.validate({}, {}, fragment=True)
        with self.assertRaises(ValueError):
            h.merge([], {})

    def test_every_fact_is_explicitly_addressable_and_bounded(self):
        facts, spans = fixture()
        limit = max(h._batch({"F0": facts[0]}, spans, "package")["request_chars"],
                    h._batch({}, spans, "vendor")["request_chars"]) + 3000
        batches = h.prepare(facts, spans, max_chars=limit)
        ids = [fid for b in batches if b["mode"] == "package" for fid in b["payload"]["fact_ledger"]]
        self.assertEqual(ids, ["F0", "F1", "F2"])
        self.assertTrue(all(b["request_chars"] <= limit for b in batches))
        for b in batches:
            self.assertEqual({v["kind"] for v in b["payload"]["spans"].values()},
                             {"package"} if b["mode"] == "package" else {"profile"})

    def test_dropped_unknown_empty_or_dangling_fact_mapping_fails(self):
        facts, spans = fixture()
        batch = next(b for b in h.prepare(facts, spans) if b["mode"] == "package")
        for mode in ("drop", "unknown", "empty", "dangling", "unknown_source"):
            raw = response(batch)
            if mode == "drop":
                raw["requirements"].pop(0)
            elif mode == "unknown":
                raw["requirements"][0]["originating_fact_ids"] = ["made-up"]
            elif mode == "empty":
                raw["requirements"][0]["originating_fact_ids"] = []
            elif mode == "dangling":
                raw["fact_coverage"] = {"F0": [{"array": "requirements", "index": 99}]}
            else:
                raw["requirements"][0]["focus"][0]["ref"] = "not-a-source"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                h.validate_batch(raw, batch)

    def test_ledger_is_not_silently_rewritten_or_private(self):
        facts, spans = fixture()
        for mode in ("private", "unknown", "empty"):
            changed = deepcopy(facts)
            changed[0]["refs"] = ["V0:0"] if mode == "private" else ["missing"] if mode == "unknown" else []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                h.prepare(changed, spans)

    def test_structural_mapping_does_not_prove_semantic_retention(self):
        facts, spans = fixture()
        b = next(b for b in h.prepare(facts, spans) if b["mode"] == "package")
        raw = response(b)
        mapped = h.validate_batch(raw, b)
        targets = h.handoff_targets(b, mapped)
        self.assertEqual(len(targets), 3)
        self.assertEqual(targets[0]["fact"], facts[0])
        self.assertIn("retained_records", targets[0])
        rejected = s.validate_audit({"checks": {t["id"]: {"verdict": "unsupported",
            "reason": "Citation exists but the ceiling was lost."} for t in targets}}, targets)
        self.assertFalse(rejected["passed"])

    def test_reduction_preserves_ids_questions_and_precedence(self):
        facts, spans = fixture()
        batches = h.prepare(facts, spans, max_facts=1)
        results = []
        for b in batches:
            if b["mode"] != "package":
                continue
            raw = response(b)
            raw["questions"] = [{"dimension": "requirement_meaning", "requirements": [0],
                "claims": [], "reason": "The stated term needs interpretation.", "decision": "scope"}]
            results.append((b, h.validate_batch(raw, b)))
        inv, receipt = h.merge(results, spans)
        self.assertEqual([q["requirements"] for q in inv["questions"]], [[0], [1], [2]])
        self.assertEqual(set(receipt["fact_coverage"]), {"F0", "F1", "F2"})
        self.assertEqual(receipt["fact_coverage"]["F2"][0]["index"], 2)

    def test_budget_cannot_be_raised_and_indivisible_fact_cannot_be_cut(self):
        facts, spans = fixture()
        with self.assertRaises(ValueError):
            h.prepare(facts, spans, max_chars=640001)
        with self.assertRaises(ValueError):
            list(h.audit_batches([], max_chars=640001))
        spans["D0:0"]["text"] += "x" * 640001
        before = deepcopy((facts, spans))
        with self.assertRaisesRegex(ValueError, "Indivisible"):
            h.prepare(facts, spans)
        self.assertEqual((facts, spans), before)

    def test_vendor_batch_requires_explicit_per_source_dispositions(self):
        facts, spans = fixture()
        b = next(b for b in h.prepare(facts, spans) if b["mode"] == "vendor")
        raw = {"requirements": [], "claims": [], "quoted_vendor_context": [], "questions": [],
               "resolved_question_ids": [], "vendor_coverage": {}}
        with self.assertRaisesRegex(ValueError, "coverage"):
            h.validate_batch(raw, b)
        raw["vendor_coverage"] = {"V0:0": {"claims": [], "reason": "No supplied assertions."}}
        checked = h.validate_batch(raw, b)
        target = h.handoff_targets(b, checked)[0]
        self.assertEqual(target["spans"]["V0:0"]["text"], spans["V0:0"]["text"])
        self.assertEqual(target["retained_records"], [])
        self.assertIn("generic", h.HANDOFF_AUDIT_PROMPT)


class VisibilityTests(unittest.TestCase):
    def test_visible_supporting_sources_have_all_directly_citing_records(self):
        from test_audit_partitioning import fixture as source_fixture
        target, spans = source_fixture(4)
        target['value']['requirements'][0]['evidence'].extend(
            deepcopy(target['value']['requirements'][2]['evidence']))
        target['value']['requirements'][2]['evidence'].extend(
            deepcopy(target['value']['requirements'][3]['evidence']))
        layout = partitions._Layout(target, spans)
        t = layout.make([['D0:0']], ['P0'], 'range')
        visible = set(t['audit_partition']['source_refs'])
        for rid, refs in layout.record_refs.items():
            if refs & visible:
                self.assertIn(rid, t['audit_partition']['requirement_ids'])

    def test_supporting_source_brings_other_records_citing_it(self):
        text = "The supplier must retain eligibility registration at both submission and award under the assigned classification."
        spans = {f"D{i}:0": {"source_id": f"D{i}", "document_id": "book", "kind": "package",
                  "source_offset": i * 1000, "offset": 0, "text": text if i != 1 else "Unrelated intervening scope."}
                 for i in range(3)}
        anchor = {"ref": "D2:0", "quote": text}
        record = {"focus": [anchor], "evidence": [anchor], "supersedes": []}
        first = {"focus": [{"ref": "D0:0", "quote": text}],
                 "evidence": [{"ref": "D0:0", "quote": text}, anchor], "supersedes": []}
        target = {"id": "package-coverage", "kind": "package_coverage",
                  "value": {"requirements": [first, record], "quoted_vendor_context": []}}
        check = partitions._Layout(target, spans).make([["D0:0"]], ["P0"], "range")
        self.assertEqual(check["audit_partition"]["requirement_ids"], ["R0", "R1"])
        self.assertEqual(check["value"]["requirements"], [first, record])
        self.assertIn("D2:0", check["audit_partition"]["source_refs"])

    def test_post_award_boundary_is_shared_not_a_keyword_override(self):
        from common import semantic_contract as c
        for prompt in (c.DECOMPOSE_PROMPT, s.audit_prompt([{"kind": "requirement"}])):
            self.assertIn("POST-AWARD DELIVERABLES", prompt)
            self.assertIn("not administrative_formatting", prompt)
        part = {"category": "technical_capability", "applicability": "prime_contractor",
                "routing_reason": "Performance deadline.", "text": "Issue the outage report within two days after restoration."}
        self.assertEqual(routing.route(part), "vendor_comparison")


class PipelineGateTests(unittest.TestCase):
    def test_handoff_rejection_prevents_decomposition_and_comparison(self):
        from common import capture_understanding as u
        from test_question_channel import pipeline_model
        model, calls, packet = pipeline_model(independent=False)
        real = s.validate_audit
        def reject(raw, targets):
            if any(t['kind'] == 'ledger_handoff' for t in targets):
                raw = {'checks': {t['id']: {'verdict': 'unsupported',
                    'reason': 'Mapped ID exists but the source prerequisite was omitted.'} for t in targets}}
            return real(raw, targets)
        with patch.object(s, 'validate_audit', side_effect=reject):
            result = u.analyze_packet(packet, [], {}, call=model)
        self.assertIn('Inventory handoff audit failed', result['pipeline_errors'][0])
        self.assertEqual(result['understanding_audit']['failure_kind'], 'semantic_support')
        self.assertFalse(any('component_job' in p or p.get('parent_scoped_decomposition') for p in calls))
        self.assertTrue(result['independent_questions'])
        self.assertEqual(result['independent_questions'][0]['question_validation'], 'supported')

    def test_claim_retention_failure_blocks_before_comparison(self):
        from common import capture_understanding as u
        from test_question_channel import pipeline_model
        model, calls, packet = pipeline_model()
        real = s.validate_audit
        def reject(raw, targets):
            if any(t['kind'] == 'vendor_handoff' for t in targets):
                raw = {'checks': {t['id']: {'verdict': 'unsupported',
                    'reason': 'Generic capability was erased.'} for t in targets}}
            return real(raw, targets)
        with patch.object(s, 'validate_audit', side_effect=reject):
            result = u.analyze_packet(packet, [], {}, call=model)
        self.assertIn('Generic capability was erased', result['pipeline_errors'][0])
        self.assertFalse(any('component_job' in p for p in calls))


if __name__ == "__main__":
    unittest.main()
