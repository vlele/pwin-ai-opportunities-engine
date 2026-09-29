"""Checked component decisions must survive the final capture handoff."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as contract, capture_clarification as gate, capture_fit as fit
from capture import render_capture_brief as renderer
from capture import capture_decision as decision


def fixture(qualified=False):
    spans = {
        "D1:0": {"source_id": "D1", "kind": "package", "offset": 0,
                 "text": "Install panels using certified lifting equipment. Repair engines."},
        "V1:0": {"source_id": "V1", "kind": "profile", "offset": 0,
                 "profile_field": "past_performance_highlights[0]",
                 "text": "Our employees installed panels using lifting equipment."},
    }
    anchor = lambda ref, quote: [{"ref": ref, "quote": quote}]
    requirement = {"area": "scope", "status": "current", "record_kind": "requirement", "task": True,
                   "logic": "all", "supersedes": [], "meaning": "Install panels using certified lifting equipment.",
                   "evidence": anchor("D1:0", "Install panels using certified lifting equipment."),
                   "focus": anchor("D1:0", "Install panels using certified lifting equipment."),
                   "components": [
                       {"kind": "work", "text": "Install panels", "evidence": anchor("D1:0", "Install panels")},
                       {"kind": "qualification", "text": "certified lifting equipment", "evidence": anchor("D1:0", "certified lifting equipment")},
                   ]}
    other = {**deepcopy(requirement), "meaning": "Repair engines.", "focus": anchor("D1:0", "Repair engines."),
             "evidence": anchor("D1:0", "Repair engines."), "components": [
                 {"kind": "work", "text": "Repair engines", "evidence": anchor("D1:0", "Repair engines")}]}
    claim = {"form": "performed_task", "execution": "affirmative_actual", "attribution": "self", "unresolved_dimensions": [],
             "meaning": "Our employees installed panels.", "evidence": anchor("V1:0", spans["V1:0"]["text"])}
    if qualified:
        spans["V1:0"]["text"] = "Our employees installed panels using certified lifting equipment."
        claim["evidence"] = anchor("V1:0", spans["V1:0"]["text"])
    findings = {"K0": {"status": "matched", "reason": "Reported panel installation.", "supported_scope": "Install panels", "evidence": claim["evidence"]},
                "K1": {"status": "matched" if qualified else "missing", "reason": "Equipment qualification is supplied." if qualified else "Certification is not supplied.",
                       "supported_scope": "certified lifting equipment" if qualified else "", "evidence": claim["evidence"] if qualified else []}}
    edges = [{"claim": 0, "requirement": 0, **contract.aggregate_components(requirement, claim, findings, spans)},
             {"claim": 0, "requirement": 1, **contract.aggregate_components(other, claim, {
                 "K0": {"status": "unrelated", "reason": "Installation is not engine repair.", "supported_scope": "", "evidence": claim["evidence"]}}, spans)}]
    graph = {"requirements": [requirement, other], "claims": [claim], "comparisons": edges}
    context = {"understanding_audit": {"claim_evidence": {"passed": True}}, "checked_evidence_graph": graph,
               "sources": {s["source_id"]: s for s in spans.values()}, "answers": [], "open_gaps": []}
    profile = {"core_competencies": [], "past_performance_highlights": [spans["V1:0"]["text"]]}
    catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
    proposed = {"status": "adjacent", "summary": "All qualifications proven.", "critical_gaps": [],
                "requirement_assessments": [
                    {"requirement_id": "R0", "match": "direct", "vendor_evidence_ids": ["PP1"], "reason": "Complete match."},
                    {"requirement_id": "R1", "match": "none", "vendor_evidence_ids": [], "reason": "Different work."},
                ], "past_performance_assessments": [
                    {"project_id": "PP1", "relevance": "direct", "requirement_ids": ["R0"], "reason": "Full proof."}]}
    return spans, context, profile, catalog, proposed


class CaptureComponentHandoffTests(unittest.TestCase):
    def test_legacy_model_cannot_supply_its_own_numeric_credit(self):
        profile = {"past_performance_highlights": ["Installed panels."]}
        catalog = fit.build_fit_catalog(profile, [{"objective": "Install panels", "evidence_snippets": ["Install panels"]}])
        proposed = {"status": "adjacent", "summary": "Transferable work", "requirement_assessments": [
            {"requirement_id": "R1", "match": "transferable", "vendor_evidence_ids": ["PP1"], "reason": "Transfer basis."}],
            "past_performance_assessments": [{"project_id": "PP1", "relevance": "transferable", "requirement_ids": ["R1"], "reason": "Transfer basis."}]}
        before = fit.validate_fit_assessment(proposed, catalog)
        proposed["requirement_assessments"][0]["credit_fraction"] = 100
        proposed["past_performance_assessments"][0]["coverage_by_requirement"] = {"R1": {"credit_fraction": 100}}
        after = fit.validate_fit_assessment(proposed, catalog)
        self.assertEqual(before["capability_score"], after["capability_score"])
        self.assertEqual(before["past_performance_score"], after["past_performance_score"])

    def test_component_ranking_proxy_cannot_round_partial_up_to_full(self):
        self.assertGreater(fit._component_score(.01), 0)
        self.assertLess(fit._component_score(.999), fit._component_score(1.0))
        self.assertEqual(fit._component_score(0), 0)

    def test_invalid_checked_graph_does_not_fall_back_to_raw_workstreams(self):
        _, context, profile, _, _ = fixture()
        context["checked_evidence_graph"]["requirements"][0]["focus"][0]["quote"] = "Invented scope"
        catalog = fit.build_fit_catalog(profile, [{"objective": "Install panels", "evidence_snippets": ["Install panels"]}], clarification_context=context)
        self.assertTrue(catalog["validation_issues"])
        self.assertEqual(fit.validate_fit_assessment({}, catalog)["status"], "unknown")

    def test_qualification_only_component_is_visible_without_work_credit(self):
        _, context, profile, _, _ = fixture()
        graph = context["checked_evidence_graph"]
        graph["claims"][0].update(form="qualification", execution="not_execution")
        graph["claims"][0]["evidence"] = [{"ref": "V1:0", "quote": "Our lifting equipment is certified."}]
        context["sources"]["V1"].update(profile_field="core_competencies[0]", text="Our lifting equipment is certified.")
        graph["comparisons"] = [graph["comparisons"][0]]
        findings = graph["comparisons"][0]["component_findings"]
        findings["K0"].update(status="missing", supported_scope="", evidence=[])
        findings["K1"].update(status="matched", supported_scope="Certified equipment", evidence=graph["claims"][0]["evidence"])
        profile = {"core_competencies": ["Our lifting equipment is certified."], "past_performance_highlights": []}
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        result = fit.validate_fit_assessment({}, catalog)
        self.assertEqual(result["past_performance_score"], 0)
        self.assertIn("Partial Fit", " ".join(result["component_coverage_notes"]))
        self.assertEqual(result["requirement_assessments"][0]["fit_label"], "Partial Fit")

    def test_confirmed_context_exports_only_checked_assertion_graph(self):
        spans, context, _, _, _ = fixture()
        plan = {**context["checked_evidence_graph"], "questions": [{"reason": "Unchecked candidate"}], "resolved_question_ids": []}
        state = {"status": "READY", "fingerprint": "test", "interpretation": [], "confirmed_answers": [], "open_gaps": [],
                 "understanding_audit": {"claim_evidence": {"passed": True}, "semantic_plan": plan}}
        result = gate.confirmed_context(state, {"sources": context["sources"]})
        self.assertEqual(result["checked_evidence_graph"], context["checked_evidence_graph"])
        self.assertNotIn("questions", result["checked_evidence_graph"])
        state["understanding_audit"]["claim_evidence"]["passed"] = False
        self.assertNotIn("checked_evidence_graph", gate.confirmed_context(state, {"sources": context["sources"]}))

    def test_catalog_uses_checked_requirement_ids_not_reconstructed_workstreams(self):
        _, context, profile, catalog, _ = fixture()
        self.assertEqual(set(catalog["requirements"]), {"R0", "R1"})
        new = fit.build_fit_catalog(profile, [{"objective": "Invented older duty", "evidence_snippets": ["Old raw phrase"]}], clarification_context=context)
        self.assertEqual(new["requirements"], catalog["requirements"])

    def test_blank_profile_entries_cannot_shift_credit_onto_another_project(self):
        _, context, profile, _, _ = fixture()
        context["sources"]["V1"]["profile_field"] = "past_performance_highlights[1]"
        profile["past_performance_highlights"] = ["", profile["past_performance_highlights"][0], "Unrelated portrait photography."]
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        self.assertEqual(catalog["vendor_evidence"]["PP2"]["profile_field"], "past_performance_highlights[1]")
        self.assertIn("installed panels", catalog["vendor_evidence"]["PP2"]["text"])
        self.assertTrue(catalog["vendor_evidence"]["PP2"]["understanding_credit"]["allowed"])
        self.assertFalse(catalog["vendor_evidence"]["PP3"]["understanding_credit"]["allowed"])

    def test_partial_fit_retains_missing_qualification_and_limited_credit(self):
        _, _, _, catalog, proposal = fixture()
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertEqual(result["status"], "adjacent")
        self.assertFalse(result["validation_issues"])
        partial = result["past_performance_assessments"][0]["coverage_by_requirement"]["R0"]
        self.assertEqual(partial["coverage"], "partial")
        self.assertEqual(partial["met_components"], ["K0"])
        self.assertEqual(partial["missing_components"], ["K1"])
        _, _, _, complete_catalog, complete_proposal = fixture(qualified=True)
        full = fit.validate_fit_assessment(complete_proposal, complete_catalog)
        self.assertGreater(result["past_performance_score"], 0)
        self.assertLess(result["past_performance_score"], full["past_performance_score"])
        self.assertNotIn("All qualifications proven", result["summary"])

    def test_model_cannot_reassign_checked_project_to_unrelated_requirement(self):
        _, _, _, catalog, proposal = fixture()
        proposal["past_performance_assessments"][0]["requirement_ids"] = ["R0", "R1"]
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertEqual(result["past_performance_assessments"][0]["requirement_ids"], ["R0"])
        self.assertTrue(result["checked_decision_overrides"])

    def test_requirement_match_cannot_borrow_project_credit_from_another_task(self):
        _, _, _, catalog, proposal = fixture()
        proposal["requirement_assessments"][1].update(match="direct", vendor_evidence_ids=["PP1"])
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertTrue(result["checked_decision_overrides"])
        self.assertEqual(result["requirement_assessments"][1]["match"], "none")
        self.assertEqual(result["status"], "adjacent")
        self.assertGreater(result["past_performance_score"], 0)

    def test_later_model_cannot_turn_known_partial_into_whole_unknown(self):
        _, _, _, catalog, proposal = fixture()
        proposal.update(status="unknown", requirement_assessments=[], past_performance_assessments=[])
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertEqual(result["status"], "adjacent")
        self.assertEqual(result["requirement_assessments"][0]["coverage"], "partial")
        self.assertEqual(result["past_performance_assessments"][0]["relevance"], "direct")

    def test_malformed_later_proposals_cannot_erase_checked_decisions(self):
        _, _, _, catalog, proposal = fixture()
        for malformed in (42, [{"project_id": ["bad-id"]}], [{"project_id": "PP1"}, {"project_id": "PP1"}]):
            with self.subTest(malformed=malformed):
                proposal["past_performance_assessments"] = malformed
                result = fit.validate_fit_assessment(proposal, catalog)
                self.assertEqual(result["status"], "adjacent")
                self.assertTrue(result["checked_decision_overrides"])

    def test_partial_gap_appears_in_rendered_fit_not_only_json(self):
        _, _, _, catalog, proposal = fixture()
        result = fit.validate_fit_assessment(proposal, catalog)
        promoted = fit.apply_validated_fit({}, result)
        text = renderer._fit_block(promoted)
        self.assertIn("Partial Fit", text)
        self.assertIn("certified lifting equipment", text)
        self.assertIn("not established", text.lower())
        self.assertNotIn("All qualifications proven", text)

    def test_unmatched_requirement_remains_an_explicit_gap_in_qualified_variant(self):
        _, _, _, catalog, proposal = fixture(qualified=True)
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertTrue(any("R1" in gap and "Repair engines" in gap for gap in result["critical_gaps"]))
        promoted = fit.apply_validated_fit({}, result)
        self.assertTrue(any("Repair engines" in gap for gap in promoted["missing_proof"]))

    def test_absent_project_evidence_does_not_make_required_tasks_disappear(self):
        _, context, _, _, _ = fixture()
        catalog = fit.build_fit_catalog({}, [], clarification_context=context)
        result = fit.validate_fit_assessment({}, catalog)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(any("Install panels" in gap for gap in result["critical_gaps"]))
        self.assertTrue(any("Repair engines" in gap for gap in result["critical_gaps"]))

    def test_decision_section_assembly_preserves_component_notes(self):
        _, _, profile, catalog, proposal = fixture()
        assessed = fit.validate_fit_assessment(proposal, catalog)
        sections = decision.build_capture_decision_sections(
            vendor_profile=profile, resolved={}, opportunity={}, explanation={}, notice_context_text="Install panels.",
            attachment_bundle={}, attachment_validation={}, public_research={}, award_signals={},
            funding_assessment={"funding_confidence": "Low"}, source_log=[], evidence_gaps=[],
            stakeholder_contacts=[], vehicle_signals=[], learned_semantic_preferences={},
            evaluator_anxiety_model={"vendor_fit_assessment": assessed, "reasoning_source": "synthetic_checked_fixture"})
        section = sections["capability_fit_analysis"]
        self.assertEqual(section["component_coverage_notes"], assessed["component_coverage_notes"])
        self.assertIn("Partial Fit", renderer._fit_block(section))

    def test_superseded_work_is_not_in_final_fit_catalog(self):
        _, context, profile, _, _ = fixture()
        context["checked_evidence_graph"]["requirements"][1]["status"] = "superseded"
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        self.assertNotIn("R1", catalog["requirements"])

    def test_ninth_checked_requirement_is_not_silently_dropped(self):
        _, context, profile, _, _ = fixture()
        graph = context["checked_evidence_graph"]
        graph["requirements"] = [deepcopy(graph["requirements"][0]) for _ in range(9)]
        graph["comparisons"] = []
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        self.assertEqual(len(catalog["requirements"]), 9)

    def test_same_profile_field_cannot_turn_unrelated_claim_into_work_credit(self):
        _, context, profile, _, proposal = fixture()
        graph = context["checked_evidence_graph"]
        graph["comparisons"][0].update(relationship="unrelated", coverage="none", matched_work="")
        graph["comparisons"][0]["component_findings"]["K0"].update(status="unrelated", supported_scope="")
        graph["comparisons"][0].update(met_components=[], partial_components=[], missing_components=["K0", "K1"], fit_label="Unrelated")
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        proposal["status"] = "no_fit"
        proposal["requirement_assessments"][0].update(match="none", vendor_evidence_ids=[])
        result = fit.validate_fit_assessment(proposal, catalog)
        self.assertEqual(result["past_performance_assessments"][0]["relevance"], "unrelated")
        self.assertEqual(result["past_performance_score"], 0)


class ReviewedPrecedenceHandoffTests(unittest.TestCase):
    def test_research_focus_uses_current_subject_not_full_span_with_old_terms(self):
        _, context, _, _, _ = fixture()
        graph = context["checked_evidence_graph"]
        graph["requirements"][1]["status"] = "superseded"
        context["interpretation"] = [{"text": "[current] Install panels.", "citations": [
            {"source_id": "D1", "quote": "Install panels using certified lifting equipment. Repair engines."}]}]
        text = gate.reviewed_package_quotes(context)
        self.assertIn("Install panels", text)
        self.assertNotIn("Repair engines", text)

    def test_active_precedence_rule_is_preserved_but_not_a_new_work_item(self):
        _, context, profile, _, _ = fixture()
        rule = deepcopy(context["checked_evidence_graph"]["requirements"][0])
        rule.update(record_kind="precedence_rule", area="precedence", supersedes=[1])
        context["checked_evidence_graph"]["requirements"].append(rule)
        catalog = fit.build_fit_catalog(profile, [], clarification_context=context)
        self.assertNotIn("R2", catalog["requirements"])
        self.assertEqual(len(catalog["active_precedence_rules"]), 1)


if __name__ == "__main__":
    unittest.main()
