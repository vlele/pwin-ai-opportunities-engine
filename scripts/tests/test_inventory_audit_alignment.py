"""Offline contract regressions; prompt wiring is not proof of live model accuracy."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s
from common import requirement_context as rc, requirement_routing as rr
from test_v28_contracts import criterion_fixture
from test_requirement_routing import fixture as routed_fixture


def criterion_case(categorized=True, status="missing"):
    spans, req, claim, finding = criterion_fixture()
    if categorized:
        req["components"][0].update(category="past_performance",
                                    applicability="prime_contractor",
                                    routing_reason="An explicitly stated experience criterion.")
    if status == "missing":
        finding.update(status="missing", reason="Specific qualifying project evidence is absent.",
                       supported_scope="", evidence=[])
    edge = c.aggregate_components(req, claim, {"K0": finding}, spans)
    plan = {"requirements": [req], "claims": [claim], "comparisons": [
        {"claim": 0, "requirement": 0, **edge}], "questions": [], "resolved_question_ids": []}
    return spans, plan


def comparison_target(plan, spans):
    return next(r for r in s.audit_records(plan, spans) if r["id"] == "E0")


class StandaloneCriterionAuditTests(unittest.TestCase):
    def test_missing_criterion_is_not_described_as_formatting(self):
        for categorized in (False, True):
            with self.subTest(categorized=categorized):
                spans, plan = criterion_case(categorized)
                before = deepcopy(plan)
                target = comparison_target(plan, spans)
                self.assertIn("standalone evaluation criterion", target["audit_question"])
                self.assertIn("each component finding", target["audit_question"])
                self.assertNotIn("only a commercial/administrative", target["audit_question"])
                self.assertEqual(target["value"]["fit_label"], "Missing Proof" if categorized else "Unknown")
                self.assertEqual(target["value"]["relationship"], "not_applicable")
                self.assertEqual(target["value"]["matched_work"], "")
                self.assertEqual(before, plan)

    def test_supported_criterion_still_receives_no_operational_credit(self):
        spans, plan = criterion_case(status="matched")
        target = comparison_target(plan, spans)
        self.assertIn("standalone evaluation criterion", target["audit_question"])
        self.assertIn("not operational task credit", target["audit_question"])
        self.assertEqual(target["value"]["fit_label"], "Supported Fit")
        self.assertEqual(target["value"]["matched_work"], "")

    def test_certification_criterion_uses_same_audit_contract(self):
        spans, inv = routed_fixture()
        req, claim = inv["requirements"][0], inv["claims"][0]
        req["components"] = [req["components"][3]]
        finding = {"status": "missing", "reason": "No certificate supplied.",
                   "supported_scope": "", "evidence": []}
        edge = c.aggregate_components(req, claim, {"K0": finding}, spans)
        inv["comparisons"] = [{"claim": 0, "requirement": 0, **edge}]
        self.assertIn("standalone evaluation criterion", comparison_target(inv, spans)["audit_question"])

    def test_operational_and_mixed_requirements_cannot_use_criterion_exception(self):
        for indexes in ([0], [0, 4]):
            spans, inv = routed_fixture()
            req = inv["requirements"][0]
            req["components"] = [req["components"][i] for i in indexes]
            inv["comparisons"] = [{"claim": 0, "requirement": 0, "relationship": "not_applicable"}]
            question = comparison_target(inv, spans)["audit_question"]
            self.assertNotIn("standalone evaluation criterion", question)
            self.assertIn("Do not ignore tasks", question)

    def test_bad_criterion_audit_still_blocks(self):
        spans, plan = criterion_case()
        target = comparison_target(plan, spans)
        for verdict in ("unsupported", "uncertain"):
            result = s.validate_audit({"checks": {"E0": {"verdict": verdict,
                "reason": "Component evidence does not establish the asserted criterion."}}}, [target])
            self.assertFalse(result["passed"])
            self.assertEqual(len(result["errors"]), 1)


class CategoryBoundaryTests(unittest.TestCase):
    def test_boundary_is_shared_by_decomposer_and_source_auditor(self):
        for prompt in (c.DECOMPOSE_PROMPT, s.audit_prompt([{"kind": "requirement"}]),
                       s.audit_prompt([{"kind": "package_coverage"}])):
            self.assertIn("SOCIOECONOMIC THRESHOLDS AND SUBMISSION MECHANICS", prompt)
            self.assertIn("participation percentages", prompt)
            self.assertIn("compliance_certification", prompt)
            self.assertIn("administrative_formatting", prompt)
            self.assertIn("Technical response times", prompt)
            self.assertIn("conditional evaluation credit", prompt)

    def test_synthetic_compliance_and_submission_have_separate_routes(self):
        parts = [
            ("Provide at least 18% eligible small-business participation.", "compliance_certification", "vendor_comparison"),
            ("Upload the participation worksheet in Volume D using the assigned filename.", "administrative_formatting", "proposal_checklist"),
            ("Restore the service within seven hours at 99.7% availability.", "technical_capability", "vendor_comparison"),
            ("Provide two relevant projects completed within four years.", "past_performance", "vendor_comparison"),
        ]
        for text, category, expected in parts:
            with self.subTest(text=text):
                part = {"text": text, "category": category, "applicability": "prime_contractor",
                        "routing_reason": "Synthetic source-assigned obligation."}
                self.assertEqual(rr.route(part), expected)

    def test_no_numeric_keyword_reclassification(self):
        part = {"text": "Availability must exceed 99.7%.", "category": "technical_capability",
                "applicability": "prime_contractor", "routing_reason": "Technical availability threshold."}
        before = deepcopy(part)
        self.assertEqual(rr.route(part), "vendor_comparison")
        self.assertEqual(part, before)


class LosslessInventoryContractTests(unittest.TestCase):
    def test_inventory_keeps_full_sources_even_when_ledger_is_incomplete(self):
        from common import capture_understanding as u
        from common.evidence_selection import EvidenceTransport
        from tests.test_question_channel import pipeline_model
        model, calls, packet = pipeline_model()
        packet["sources"]["D1"]["text"] += " Maximum term is 42 months."
        wire_calls = []

        def record(**kwargs):
            wire_calls.append(deepcopy(kwargs["user_payload"]))
            return model(**kwargs)

        result = u.analyze_packet(packet, [], {}, call=record)
        payload = next(p for p in wire_calls if "source_coverage" in p)
        expected = u.build_spans(packet, [])
        package = {k: v for k, v in expected.items() if v['kind'] == 'package'}
        wire = EvidenceTransport(rc.parent_inventory_schema(package), {"spans": package})
        self.assertEqual(payload["spans"], wire.payload["spans"])
        self.assertIn("Maximum term is 42 months.", payload["spans"]["D1:0"]["text"])
        self.assertTrue(result["understanding_audit"]["facts"])
        self.assertFalse(any("42 months" in f["statement"] for f in result["understanding_audit"]["facts"]))
        coverage_payload = next(p for p in wire_calls if any(t['kind'] == 'package_coverage' for t in p.get('targets', [])))
        self.assertIn('Maximum term is 42 months.', coverage_payload['spans']['D1:0']['text'])

    def test_material_facts_instruction_reaches_current_and_combined_inventory(self):
        for prompt in (c.INVENTORY_PROMPT, rc.parent_inventory_prompt()):
            prompt = " ".join(prompt.split())
            self.assertIn("lossless semantic mapper", prompt)
            self.assertIn("MUST NOT silently drop material facts from the ledger", prompt)
            for concept in ("quantitative ceilings", "mandatory prerequisites", "formal definitions",
                            "form identifiers", "units", "exceptions", "supporting_context"):
                self.assertTrue(concept in prompt, "Missing inventory instruction: " + concept)

    def test_lossless_does_not_license_fabrication_or_broad_citations(self):
        prompt = rc.parent_inventory_prompt()
        for phrase in ("original package sources", "Do not invent missing facts",
                       "Do not turn definitions into contractor duties", "8,000",
                       "Private profile assertions", "quoted_vendor_context"):
            self.assertIn(phrase, prompt)

    def test_repeated_or_conflicting_facts_are_not_silently_merged(self):
        prompt = rc.parent_inventory_prompt()
        self.assertIn("Merge only equivalent facts", prompt)
        self.assertIn("Keep conflicting values", prompt)
        self.assertIn("different triggers", prompt)

    def test_coverage_omission_remains_blocking(self):
        spans, plan = criterion_case()
        target = next(r for r in s.audit_records(plan, spans) if r["kind"] == "package_coverage")
        for fact in ("Maximum term is 42 months.", "Form ZX-17 is required before access.",
                     "Subscriber means the party authorized to use the licensed product."):
            with self.subTest(fact=fact):
                result = s.validate_audit({"checks": {target["id"]: {"verdict": "unsupported",
                    "reason": "Inventory omitted the material fact: " + fact}}}, [target])
                self.assertFalse(result["passed"])
                self.assertIn(fact, result["errors"][0])

    def test_runtime_rules_have_no_replay_specific_literals(self):
        for prompt in (rc.parent_inventory_prompt(), rr.DECOMPOSITION_POLICY):
            for phrase in ("IETSS", "VA Form 0752", "66 months", "36C10B25R0003"):
                self.assertNotIn(phrase, prompt)

    def test_generated_references_include_record_specific_audit_contract(self):
        from export_semantic_prompts import documents
        docs = documents()
        self.assertIn("standalone evaluation criterion", docs["AUDITOR-PROMPT.md"])
        self.assertIn("lossless semantic mapper", docs["EXTRACTOR-PROMPT.md"])
        self.assertIn("SOCIOECONOMIC THRESHOLDS AND SUBMISSION MECHANICS", docs["DECOMPOSER-PROMPT.md"])


if __name__ == "__main__":
    unittest.main()
