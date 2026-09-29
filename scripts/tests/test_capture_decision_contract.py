"""Behavioral regressions: no customer names, score targets, or network calls."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture import capture_decision as decision
from capture import run_capture_research as capture
from common import openai_reasoning as reasoning
from tests.run_capture_reasoning_primary_tests import _base_inputs


def score(fit):
    return decision._score_and_recommendation(
        {}, {"evidence_backed_priorities": ["p1", "p2", "p3"], "likely_priorities": ["p4"]},
        fit, {"funding_confidence": "Low"}, True, False, False,
        {}, {"best_partner_candidates": ["Find a vehicle holder", "Find a prime", "Find staff"]}, True, [],
    )


def component(result, name):
    return next(row["score"] for row in result["score_breakdown"] if row["category"] == name)


def strategy(model):
    case = _base_inputs()
    return decision._win_strategy(
        case["customer_priorities"], case["capability_fit"], case["partner_analysis"],
        case["contract_type"], case["incumbent_analysis"], case["policy_signals"],
        case["solicitation_facts"], case["attachment_workstreams"], case["staffing_pricing_signals"],
        case["attachment_anomalies"], model, case["solicitation_fact_model"],
    )


class DecisionContractTests(unittest.TestCase):
    def test_compaction_cannot_invent_transition_deadline(self):
        source = "Outgoing transition plan contractor shall provide the transition plan after written termination notice."
        result = decision._repair_requirement_phrase(source)
        self.assertIn("after written termination notice", result)
        self.assertNotIn("option period", result)

    def test_compaction_cannot_invent_recipient_roles(self):
        result = decision._repair_requirement_phrase("Throughout the performance of this contract shall be provided via electronic submission to the laboratory director.")
        self.assertIn("laboratory director", result)
        self.assertNotIn("PM, COR, and CO", result)

    def test_compaction_preserves_calendar_due_date(self):
        result = decision._repair_requirement_phrase("Inspection Report Due: 30 July 2030")
        self.assertNotIn("within 30 July", result)
        self.assertIn("30 July 2030", result)

    def test_unrelated_inventory_has_no_performance_credit(self):
        result = score({"past_performance_inventory": ["bakery logos", "wedding photography", "restaurant ads"]})
        self.assertEqual(component(result, "Past performance fit"), 0)

    def test_adding_unrelated_inventory_cannot_raise_performance_score(self):
        empty = component(score({}), "Past performance fit")
        many = component(score({"past_performance_inventory": ["commercial menu design"] * 12}), "Past performance fit")
        self.assertEqual(empty, many)

    def test_no_fit_is_not_rescued_by_generic_partners(self):
        result = score({"vendor_fit_assessment": {"status": "no_fit", "summary": "No relevant workshare", "capability_score": 0, "past_performance_score": 0}})
        self.assertEqual(result["recommendation"], "No-bid")

    def test_missing_information_is_not_asserted_as_no_fit_or_team(self):
        result = score({"vendor_fit_assessment": {"status": "unknown", "summary": "Profile not supplied", "capability_score": 0, "past_performance_score": 0}})
        self.assertEqual(result["recommendation"], "Monitor only")

    def test_no_fit_partner_signals_are_context_not_recommendations(self):
        result = decision._enforce_partner_fit_boundary({"recommended_posture": "Team, do not prime",
            "best_partner_candidates": ["Synthetic vehicle holder"], "partner_rationale": ["Join their team"],
            "partner_outreach_action_items": ["Contact them now"], "partner_risks": ["Conflict possible"]},
            {"status": "no_fit"})
        self.assertEqual(result["recommended_posture"], "No-bid")
        self.assertEqual(result["best_partner_candidates"], [])
        self.assertNotIn("Join their team", result["partner_rationale"])
        self.assertEqual(result["unqualified_market_signals"]["candidates"], ["Synthetic vehicle holder"])

    def test_intentional_empty_model_lists_are_preserved(self):
        fallback = reasoning._coerce_capture_reasoning_payload({}, {})
        fallback["reasoned_differentiators"] = ["Unsupported stock advantage"]
        fallback["reasoned_win_themes"] = ["Generic approach"]
        fallback["reasoned_differentiator_rows"] = [{"text": "Unsupported stock advantage", "evidence_anchor": "Clause"}]
        result = reasoning._coerce_capture_reasoning_payload({"reasoned_differentiators": [], "reasoned_win_themes": [], "reasoned_differentiator_rows": []}, fallback)
        self.assertEqual(result["reasoned_differentiators"], [])
        self.assertEqual(result["reasoned_win_themes"], [])
        self.assertEqual(result["reasoned_differentiator_rows"], [])

    def test_missing_model_does_not_create_company_advantages(self):
        result = reasoning._coerce_capture_reasoning_payload(None, {"reasoned_differentiators": ["Stock proof"]})
        self.assertFalse(result.get("reasoned_differentiators"))

    def test_renderer_preserves_empty_differentiators(self):
        result = strategy({"reasoned_differentiator_rows": [], "reasoned_differentiators": [], "reasoned_win_theme_rows": [], "reasoned_win_themes": []})
        self.assertEqual(result["discriminators"], [decision.NO_DIFFERENTIATOR_EVIDENCE])

    def test_mixed_contract_structure_survives_extraction(self):
        facts = capture._attachment_fact_candidates("This task order includes Firm Fixed Price (FFP), Labor Hour (LH), and Time and Materials (T&M) line items.")
        text = facts.get("contract_type", "").lower()
        for label in ("fixed price", "labor hour", "time and materials"):
            self.assertIn(label, text)

    def test_ffp_only_is_not_mixed_by_generic_clause(self):
        facts = capture._attachment_fact_candidates("This order is Firm Fixed Price (FFP). FAR clauses for time and materials contracts apply when applicable.")
        self.assertEqual(facts.get("contract_type"), "Firm Fixed Price")

    def test_missing_contract_structure_is_unknown(self):
        self.assertFalse(capture._attachment_fact_candidates("The contractor will maintain pumps.").get("contract_type"))


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        from common.capture_fit import build_fit_catalog, validate_fit_assessment
        self.validate = validate_fit_assessment
        self.profile = {"core_competencies": ["pump maintenance"], "past_performance_highlights": ["Maintained 40 pumps as prime for three years."]}
        self.catalog = build_fit_catalog(self.profile, [{"title": "Pump maintenance", "objective": "Maintain pumps and restore failed pumps within four hours.", "evidence_snippets": ["PWS section 5: Maintain pumps and restore failed pumps within four hours."]}])
        self.req = next(iter(self.catalog["requirements"]))
        self.project = next(k for k, v in self.catalog["vendor_evidence"].items() if v["kind"] == "past_performance")
        self.payload = {"status": "fit", "summary": "Relevant delivery", "requirement_assessments": [{"requirement_id": self.req, "match": "direct", "vendor_evidence_ids": [self.project], "reason": "Performed the same maintenance work"}], "past_performance_assessments": [{"project_id": self.project, "relevance": "direct", "requirement_ids": [self.req], "reason": "Pump maintenance at operational scale"}], "critical_gaps": []}

    def test_relevant_performance_beats_unrelated(self):
        relevant = self.validate(self.payload, self.catalog)
        unrelated = copy.deepcopy(self.payload)
        unrelated["status"] = "no_fit"
        unrelated["requirement_assessments"][0].update(match="none", vendor_evidence_ids=[])
        unrelated["past_performance_assessments"][0].update(relevance="unrelated", requirement_ids=[])
        rejected = self.validate(unrelated, self.catalog)
        self.assertGreater(relevant["past_performance_score"], rejected["past_performance_score"])
        self.assertEqual(rejected["past_performance_score"], 0)

    def test_invented_reference_cannot_earn_credit(self):
        self.payload["requirement_assessments"][0]["vendor_evidence_ids"] = ["NOT_IN_PROFILE"]
        self.payload["past_performance_assessments"][0]["project_id"] = "NOT_IN_PROFILE"
        result = self.validate(self.payload, self.catalog)
        self.assertEqual(result["past_performance_score"], 0)
        self.assertEqual(result["status"], "unknown")

    def test_positive_project_cannot_coexist_with_no_fit_for_same_requirement(self):
        self.payload["status"] = "no_fit"
        self.payload["requirement_assessments"][0].update(match="none", vendor_evidence_ids=[])
        result = self.validate(self.payload, self.catalog)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["past_performance_score"], 0)
        self.assertTrue(result["validation_issues"])

    def test_theme_requires_proof_for_every_requirement_it_claims(self):
        from common.capture_fit import validate_company_strategy_rows
        fit = self.validate(self.payload, self.catalog)
        fit["catalog"]["requirements"]["R2"] = {"text": "Inspect aircraft", "anchors": ["Inspect aircraft"]}
        fit["catalog"]["vendor_evidence"]["C2"] = {"kind": "capability", "text": "Aircraft inspections"}
        fit["requirement_assessments"].append({"requirement_id": "R2", "match": "direct", "vendor_evidence_ids": ["C2"]})
        row = {"text": "Our pump project proves both tasks", "requirement_ids": [self.req, "R2"], "vendor_evidence_ids": [self.project]}
        self.assertFalse(validate_company_strategy_rows([row], fit))

    def test_removed_proof_invalidates_its_theme(self):
        from common.capture_fit import validate_company_strategy_rows
        fit = self.validate(self.payload, self.catalog)
        row = {"text": "Use our pump-maintenance delivery to reduce outage risk.", "requirement_ids": [self.req], "vendor_evidence_ids": [self.project]}
        self.assertTrue(validate_company_strategy_rows([row], fit))
        del fit["catalog"]["vendor_evidence"][self.project]
        self.assertFalse(validate_company_strategy_rows([row], fit))

    def test_empty_profile_cannot_be_judged_no_fit(self):
        from common.capture_fit import build_fit_catalog
        empty = build_fit_catalog({}, [{"objective": "Maintain pumps", "evidence_snippets": ["Maintain pumps"]}])
        result = self.validate({"status": "no_fit", "summary": "No vendor information"}, empty)
        self.assertEqual(result["status"], "unknown")

    def test_checked_unknown_or_unrelated_project_cannot_be_repromoted(self):
        from common.capture_fit import build_fit_catalog
        for relevance in ("unknown", "unrelated"):
            context = {"understanding_audit": {"claim_evidence": {"passed": True}},
                       "sources": {"V1": {"kind": "profile", "profile_field": "past_performance_highlights[0]"}},
                       "open_gaps": [{"claim_id": "C0", "claim": {"subject": "performed_work"},
                                      "relevance": relevance, "claim_citations": [{"source_id": "V1"}]}]}
            catalog = build_fit_catalog(self.profile, [{"objective": "Maintain pumps", "evidence_snippets": ["Maintain pumps"]}],
                                        clarification_context=context)
            result = self.validate(self.payload, catalog)
            self.assertEqual(result["past_performance_score"], 0)
            self.assertEqual(result["status"], "unknown")
            self.assertNotEqual(result["summary"], "Relevant delivery")
            self.assertTrue(result["validation_issues"])

    def test_clear_reported_task_can_still_supply_provisional_credit(self):
        from common.capture_fit import build_fit_catalog
        context = {"understanding_audit": {"claim_evidence": {"passed": True}},
                   "sources": {"V1": {"kind": "profile", "profile_field": "past_performance_highlights[0]"}},
                   "open_gaps": [{"claim_id": "C0", "claim": {"subject": "performed_work"}, "relevance": "direct",
                                  "attribution": "self", "claim_citations": [{"source_id": "V1"}]}]}
        catalog = build_fit_catalog(self.profile, [{"objective": "Maintain pumps", "evidence_snippets": ["Maintain pumps"]}], clarification_context=context)
        self.assertGreater(self.validate(self.payload, catalog)["past_performance_score"], 0)

    def test_answer_credit_is_scoped_to_the_original_profile_field(self):
        from common.capture_fit import build_fit_catalog
        context = {"understanding_audit": {"claim_evidence": {"passed": True}},
                   "sources": {"V1": {"kind": "profile", "profile_field": "past_performance_highlights[0]"},
                               "U1": {"kind": "user_answer", "question_id": "Q-one"}},
                   "answers": [{"question_id": "Q-one", "kind": "vendor_experience", "answer": "Our staff maintained the pumps.",
                                "citations": [{"source_id": "V1"}]}],
                   "open_gaps": [{"claim_id": "C0", "claim": {"subject": "performed_work"}, "relevance": "direct",
                                  "attribution": "self", "claim_citations": [{"source_id": "U1"}]}]}
        profile = copy.deepcopy(self.profile)
        profile["past_performance_highlights"].append("An unrelated unresolved reference")
        catalog = build_fit_catalog(profile, [{"objective": "Maintain pumps", "evidence_snippets": ["Maintain pumps"]}], clarification_context=context)
        self.assertTrue(catalog["vendor_evidence"]["PP1"]["understanding_credit"]["allowed"])
        self.assertFalse(catalog["vendor_evidence"]["PP2"]["understanding_credit"]["allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
