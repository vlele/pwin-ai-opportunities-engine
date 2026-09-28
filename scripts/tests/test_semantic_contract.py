"""Seven-gap contracts: synthetic, source-bound, no total-score targets."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c


def fixture():
    spans = {
        "D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                 "text": "Install panels using certified lifting equipment. Installation is fixed-price."},
        "V1:0": {"kind": "profile", "source_id": "V1", "offset": 0,
                 "text": "Our employees installed panels. We own a warehouse. We do not repair engines."},
    }
    anchor = lambda ref, quote: [{"ref": ref, "quote": quote}]
    req = {"components": [
        {"kind": "work", "text": "Install panels", "evidence": anchor("D1:0", "Install panels")},
        {"kind": "qualification", "text": "certified lifting equipment", "evidence": anchor("D1:0", "certified lifting equipment")},
    ], "logic": "all", "record_kind": "requirement", "supersedes": [], "status": "current"}
    claim = {"form": "performed_task", "attribution": "self", "execution": "affirmative_actual",
             "evidence": anchor("V1:0", "Our employees installed panels.")}
    findings = {"K0": {"status": "matched", "reason": "Same installation work.", "evidence": claim["evidence"]},
                "K1": {"status": "missing", "reason": "No equipment certification is supplied.", "evidence": []}}
    return spans, req, claim, findings


class SemanticContractTests(unittest.TestCase):
    def test_partial_work_component_is_direct_but_never_complete(self):
        spans, req, claim, findings = fixture()
        findings["K0"].update(status="partial", supported_scope="Installation of panels only")
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["relationship"], "same_task")
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["matched_work"], "Installation of panels only")
        self.assertEqual(result["fit_label"], "Partial Fit")
        self.assertEqual(result["met_components"], [])
        self.assertEqual(result["partial_components"], ["K0"])

    def test_partial_requires_explicit_supported_scope(self):
        spans, req, claim, findings = fixture()
        findings["K0"]["status"] = "partial"
        with self.assertRaisesRegex(ValueError, "scope"):
            c.aggregate_components(req, claim, findings, spans)

    def test_partial_alternative_does_not_satisfy_any_path(self):
        spans, req, claim, findings = fixture()
        req["logic"] = "any"
        findings["K0"].update(status="partial", supported_scope="Installation of panels only")
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["fit_label"], "Partial Fit")

    def test_met_qualification_alternative_cannot_complete_partial_work(self):
        spans, req, claim, findings = fixture()
        req["logic"] = "any"
        findings["K0"].update(status="partial", supported_scope="Installation of panels only")
        findings["K1"].update(status="matched", evidence=claim["evidence"])
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["met_components"], ["K1"])

    def test_invalid_supported_scope_is_a_validation_error(self):
        spans, req, claim, findings = fixture()
        findings["K0"].update(status="partial", supported_scope=3)
        with self.assertRaises(ValueError):
            c.aggregate_components(req, claim, findings, spans)

    def test_no_partial_experience_credit_for_general_capability(self):
        spans, req, claim, findings = fixture()
        claim.update(form="capability", execution="not_execution")
        findings["K0"].update(status="partial", supported_scope="Installation of panels only")
        with self.assertRaisesRegex(ValueError, "affirmative"):
            c.aggregate_components(req, claim, findings, spans)

    def test_question_audits_use_one_warrant_policy(self):
        from common import semantic_plan as s
        self.assertIn(c.QUESTION_AUDIT_PROMPT, s.audit_prompt([{"kind": "question"}]))

    def test_requirement_subject_is_distinct_from_amendment_context(self):
        from common import semantic_plan as s
        text = "Amendment 03 replaces the old 40-day term with 75 days after authorization."
        spans = {"D1:0": {"kind": "package", "source_id": "D1", "offset": 0, "text": text}}
        anchor = lambda quote: [{"ref": "D1:0", "quote": quote}]
        old = {"area": "timing", "status": "current", "task": False,
               "evidence": anchor(text), "focus": anchor("old 40-day term"),
               "components": [{"kind": "timing", "text": "40-day term", "evidence": anchor("old 40-day term")}],
               "logic": "all", "record_kind": "requirement", "supersedes": []}
        rule = {**deepcopy(old), "area": "precedence", "focus": anchor(text),
                "record_kind": "precedence_rule", "supersedes": [0],
                "components": [{"kind": "context", "text": text, "evidence": anchor(text)}]}
        plan = s.validate_inventory({"requirements": [old, rule], "claims": [], "questions": [],
                                    "resolved_question_ids": []}, spans, components=True)
        self.assertEqual(plan["requirements"][0]["meaning"], "old 40-day term")
        self.assertEqual(plan["requirements"][0]["status"], "superseded")
        self.assertEqual(plan["requirements"][1]["status"], "current")
        self.assertIn("Active Precedence Rule", s.render({**plan, "comparisons": []}, spans)["interpretation"][1]["text"])

    def test_focus_cannot_borrow_another_record_in_the_same_span(self):
        spans, req, _, _ = fixture()
        req.update(evidence=[{"ref": "D1:0", "quote": "Install panels"}],
                   focus=[{"ref": "D1:0", "quote": "Installation is fixed-price."}])
        with self.assertRaisesRegex(ValueError, "focus"):
            c.validate_focus(req, spans)

    def test_component_evidence_cannot_borrow_another_project_in_same_span(self):
        spans, req, claim, findings = fixture()
        spans["V1:0"]["text"] += " A different team operated certified lifting equipment."
        findings["K1"] = {"status": "matched", "reason": "Borrowed qualification.",
                          "evidence": [{"ref": "V1:0", "quote": "A different team operated certified lifting equipment."}]}
        with self.assertRaisesRegex(ValueError, "claim"):
            c.aggregate_components(req, claim, findings, spans)

    def test_requirement_components_cannot_borrow_neighboring_scope(self):
        spans, req, _, _ = fixture()
        req["evidence"] = [{"ref": "D1:0", "quote": "Installation is fixed-price."}]
        with self.assertRaisesRegex(ValueError, "requirement"):
            c.validate_components(req, spans)

    def test_inventory_and_claim_auditors_share_execution_policy(self):
        from common import semantic_plan as s
        self.assertIn(c.CLAIM_RULES, c.INVENTORY_PROMPT)
        self.assertIn(c.CLAIM_RULES, s.audit_prompt([{"kind": "claim"}]))
        self.assertIn(c.CLAIM_RULES, s.audit_prompt([{"kind": "claim_coverage"}]))
        self.assertNotIn("compare", s.audit_prompt([{"kind": "claim"}]).lower().split(c.CLAIM_RULES.lower())[0])

    def test_package_coverage_distinguishes_quoted_vendor_context(self):
        from common import semantic_plan as s
        from test_semantic_plan import fixture as old_fixture
        spans, plan = old_fixture()
        plan["requirements"][0]["components"] = []
        plan["claims"].append({"form": "work_reference", "meaning": "Quoted reference", "attribution": "unresolved",
                               "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]})
        coverage = next(t for t in s.audit_records(plan, spans) if t["kind"] == "package_coverage")
        self.assertEqual(len(coverage["value"]["quoted_vendor_context"]), 1)
        self.assertNotIn("V1:0", str(coverage["value"]["quoted_vendor_context"]))

    def test_one_met_component_is_explicit_partial_fit(self):
        spans, req, claim, findings = fixture()
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["relationship"], "same_task")
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["fit_label"], "Partial Fit")
        self.assertEqual(result["met_components"], ["K0"])
        self.assertEqual(result["missing_components"], ["K1"])

    def test_qualification_alone_cannot_be_performed_work(self):
        spans, req, claim, findings = fixture()
        findings["K0"] = {"status": "missing", "reason": "No work claimed.", "evidence": []}
        findings["K1"] = {"status": "matched", "reason": "Reported qualification only.", "evidence": claim["evidence"]}
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["fit_label"], "Partial Fit")
        self.assertEqual(result["relationship"], "unknown")

    def test_all_and_alternatives_have_different_coverage(self):
        spans, req, claim, findings = fixture()
        req["logic"] = "any"
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["fit_label"], "Supported Fit")

    def test_missing_component_assessment_cannot_disappear(self):
        spans, req, claim, findings = fixture()
        del findings["K1"]
        with self.assertRaises(ValueError):
            c.aggregate_components(req, claim, findings, spans)

    def test_unrelated_is_bounded_to_supplied_work(self):
        spans, req, claim, findings = fixture()
        findings["K0"] = {"status": "unrelated", "reason": "The supplied work is a different task.", "evidence": claim["evidence"]}
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["relationship"], "unrelated")
        self.assertEqual(result["coverage"], "none")

    def test_missing_work_stays_unknown(self):
        spans, req, claim, findings = fixture()
        findings["K0"] = {"status": "missing", "reason": "No identifiable task in this reference.", "evidence": []}
        self.assertEqual(c.aggregate_components(req, claim, findings, spans)["relationship"], "unknown")

    def test_audit_requirement_payload_cannot_see_vendor(self):
        spans, req, _, _ = fixture()
        batch = [{"id": "R0", "kind": "requirement", "value": req}]
        payload = c.audit_payload(batch, spans, [{"answer": "PRIVATE"}], [{"question": "PRIVATE"}])
        self.assertEqual(set(payload["spans"]), {"D1:0"})
        self.assertNotIn("PRIVATE", str(payload))
        self.assertNotIn("Our employees", str(payload))

    def test_pricing_record_with_work_is_still_compared(self):
        _, req, _, _ = fixture()
        req.update(area="pricing", task=False)
        self.assertTrue(c.has_work(req))
        req["components"] = [{"kind": "pricing", "text": "fixed-price", "evidence": [{"ref": "D1:0", "quote": "fixed-price"}]}]
        self.assertFalse(c.has_work(req))

    def test_metadata_negation_and_proposal_cannot_be_execution(self):
        for execution in ("negative", "asset_ownership", "date_metadata", "prospective", "not_execution"):
            _, _, claim, _ = fixture()
            claim["execution"] = execution
            with self.assertRaises(ValueError):
                c.validate_execution(claim)

    def test_positive_cannot_cite_government_requirement_as_vendor_work(self):
        spans, req, claim, findings = fixture()
        findings["K0"]["evidence"] = [{"ref": "D1:0", "quote": "Install panels"}]
        with self.assertRaises(ValueError):
            c.aggregate_components(req, claim, findings, spans)

    def test_reference_or_unresolved_performer_cannot_earn_work_credit(self):
        for changes in ({"form": "work_reference", "execution": "unclear"}, {"attribution": "unresolved"}):
            spans, req, claim, findings = fixture()
            claim.update(changes)
            with self.assertRaises(ValueError):
                c.aggregate_components(req, claim, findings, spans)

    def test_active_precedence_rule_replaces_only_its_target(self):
        rows = [{"status": "current", "record_kind": "requirement", "supersedes": []},
                {"status": "current", "record_kind": "precedence_rule", "supersedes": [0]}]
        result = c.apply_precedence(rows)
        self.assertEqual(result[0]["status"], "superseded")
        self.assertEqual(result[1]["status"], "current")
        self.assertEqual(rows[0]["status"], "current")

    def test_precedence_cycle_and_non_rule_override_rejected(self):
        for rows in ([{"status": "current", "record_kind": "precedence_rule", "supersedes": [0]}],
                     [{"status": "current", "record_kind": "requirement", "supersedes": [0]}],
                     [{"status": "current", "record_kind": "precedence_rule", "supersedes": [1]},
                      {"status": "current", "record_kind": "precedence_rule", "supersedes": [0]}]):
            with self.assertRaises(ValueError):
                c.apply_precedence(rows)

    def test_old_precedence_rule_cannot_override_new_current_rule(self):
        rows = [{"status": "current", "record_kind": "precedence_rule", "supersedes": [2]},
                {"status": "current", "record_kind": "precedence_rule", "supersedes": [0]},
                {"status": "current", "record_kind": "requirement", "supersedes": []}]
        result = c.apply_precedence(rows)
        self.assertEqual(result[0]["status"], "superseded")
        self.assertEqual(result[1]["status"], "current")
        self.assertEqual(result[2]["status"], "current")

    def test_question_survives_other_pipeline_failure_without_research(self):
        from common.capture_clarification import validate_assessment
        spans, _, _, _ = fixture()
        signal = {"dimension": "task_meaning", "reason": "Actual duties in this reference are not established.",
                  "decision": "experience", "evidence": [{"ref": "V1:0", "quote": "Our employees installed panels."}]}
        questions = c.render_questions([signal], spans)
        raw = {"pipeline_errors": ["Unrelated pricing audit failed."], "independent_questions": questions}
        packet = {"technical_issues": [], "sources": {x["source_id"]: x for x in spans.values()}}
        state = validate_assessment(raw, packet)
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(len(state["questions"]), 1)
        self.assertFalse(state.get("research_authorized", False))

    def test_questions_deduped_not_erased(self):
        spans, _, _, _ = fixture()
        signal = {"dimension": "performer_identity", "reason": "Reference performer relationship is unstated.",
                  "decision": "attribution", "evidence": [{"ref": "V1:0", "quote": "Our employees installed panels."}]}
        rows = c.render_questions([signal, deepcopy(signal)], spans)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["blocking"])
        self.assertNotIn("met", rows[0]["question"])

    def test_independent_question_survives_live_adapter_failure(self):
        from common.capture_understanding import analyze_packet
        from common.capture_clarification import validate_assessment
        spans, _, _, _ = fixture()
        sources = {s["source_id"]: s for s in spans.values()}
        sources["V1"]["text"] = "Past project: equipment support. The performer and actual duties are unspecified."
        packet = {"sources": sources, "technical_issues": []}
        def provider(**kwargs):
            payload = kwargs["user_payload"]
            if "signals" in kwargs["response_schema"]["schema"]["properties"]:
                return {"signals": [{"dimension": "task_meaning", "reason": "This existing project's duties are unresolved.",
                       "decision": "experience", "evidence": [{"ref": "V1:0", "quote": sources["V1"]["text"]}]}]}
            if "targets" in payload:
                return {"checks": {t["id"]: {"verdict": "supported", "reason": "A genuine existing reference is unclear."} for t in payload["targets"]}}
            return None
        from tests.evidence_wire_fixture import selection_provider
        raw = analyze_packet(packet, [], {}, call=selection_provider(provider))
        self.assertTrue(raw["pipeline_errors"])
        state = validate_assessment(raw, packet)
        self.assertEqual(state["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(len(state["questions"]), 1)
        self.assertFalse(state["research_authorized"])

    def test_decomposition_cannot_rewrite_original_requirement(self):
        spans, req, _, _ = fixture()
        inventory = {"requirements": [req]}
        with self.assertRaises(ValueError):
            c.apply_decomposition(inventory, {"requirements": {"R0": {"components": req["components"], "logic": "all", "status": "superseded"}}}, spans)
        result = c.apply_decomposition(inventory, {"requirements": {"R0": {"components": req["components"], "logic": "all"}}}, spans)
        self.assertEqual(result["requirements"][0]["status"], "current")

    def test_pure_price_cannot_create_experience_pair(self):
        from common import semantic_plan
        _, req, claim, _ = fixture()
        req["components"] = [{"kind": "pricing", "text": "Fixed price", "evidence": [{"ref": "D1:0", "quote": "fixed-price"}]}]
        self.assertEqual(semantic_plan.comparison_pairs({"requirements": [req], "claims": [claim]}), [])

    def test_missing_execution_cannot_use_legacy_credit_path_in_production(self):
        _, _, claim, _ = fixture()
        del claim["execution"]
        with self.assertRaises(ValueError):
            c.validate_execution(claim)

    def test_negative_or_asset_cannot_be_positive_service_offering(self):
        for execution in ("negative", "asset_ownership", "date_metadata"):
            _, _, claim, _ = fixture()
            claim.update(form="capability", execution=execution)
            with self.assertRaises(ValueError):
                c.validate_execution(claim)

    def test_routing_audit_sees_actual_independent_question_channel(self):
        spans, _, _, _ = fixture()
        targets = [{"id": "routing", "kind": "routing", "value": {"questions": []}}]
        questions = [{"question": "Which entity performed this reference?"}]
        payload = c.audit_payload(targets, spans, independent_questions=questions)
        self.assertEqual(payload["targets"][0]["value"]["independent_questions"], questions)
        self.assertNotIn("independent_questions", targets[0]["value"])

    def test_quote_whitespace_is_not_silently_changed(self):
        from common.semantic_plan import _anchors
        spans, _, _, _ = fixture()
        with self.assertRaisesRegex(ValueError, "exact"):
            _anchors([{"ref": "V1:0", "quote": "  Our employees installed panels.  "}], spans)

    def test_cited_ambiguity_is_not_a_positive_assertion(self):
        spans, req, claim, findings = fixture()
        claim.update(form="work_reference", execution="unclear", attribution="unresolved")
        findings["K0"] = {"status": "ambiguous", "reason": "The performer is unresolved.", "evidence": claim["evidence"]}
        result = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(result["relationship"], "unknown")
        self.assertEqual(result["met_components"], [])
        self.assertEqual(result["fit_label"], "Unknown")

    def test_umbrella_context_does_not_double_count_subordinate_tasks(self):
        spans, req, claim, _ = fixture()
        req["components"] = [{"kind": "context", "text": "Panel project", "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]}]
        self.assertFalse(c.has_work(req))
        req["components"][0]["kind"] = "work"
        self.assertTrue(c.has_work(req))

    def test_failed_answer_reassessment_cannot_erase_new_question(self):
        from common.capture_clarification import checkpoint
        spans, _, _, _ = fixture()
        packet = {"technical_issues": [], "sources": {s["source_id"]: s for s in spans.values()}}
        signal = {"dimension": "task_meaning", "reason": "The existing reference's actual work is unclear.",
                  "decision": "experience", "evidence": [{"ref": "V1:0", "quote": spans["V1:0"]["text"]}]}
        first = {"pipeline_errors": ["Other audit failed."], "independent_questions": c.render_questions([signal], spans)}
        signal = {**signal, "dimension": "performer_identity", "decision": "attribution"}
        second = {"pipeline_errors": ["Other audit still failed."], "independent_questions": c.render_questions([signal], spans)}
        model = Mock(side_effect=[first, second])
        with tempfile.TemporaryDirectory() as folder:
            state = checkpoint(Path(folder), packet, analyze=model)
            answered = {"fingerprint": state["fingerprint"], "answers": [{"question_id": state["questions"][0]["id"], "answer": "The work was installation."}]}
            later = checkpoint(Path(folder), packet, analyze=model, answers=answered)
        self.assertEqual(later["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(len(later["questions"]), 2)
        self.assertFalse(later["research_authorized"])

    def test_precedence_cannot_retire_its_own_quoted_instruction(self):
        quote = [{"ref": "D1:0", "quote": "An amendment replaces the old deadline."}]
        rows = [{"record_kind": "requirement", "status": "current", "supersedes": [], "evidence": quote},
                {"record_kind": "precedence_rule", "status": "current", "supersedes": [0], "evidence": quote}]
        with self.assertRaisesRegex(ValueError, "active rule"):
            c.apply_precedence(rows)

    def test_coverage_audits_inventory_not_fit_or_question_decisions(self):
        from common import semantic_plan as s
        from test_semantic_plan import fixture as old_fixture
        spans, plan = old_fixture()
        plan["requirements"][0]["components"] = []
        targets = s.audit_records(plan, spans)
        self.assertNotIn("routing", {t["kind"] for t in targets})
        coverage = next(t for t in targets if t["kind"] == "package_coverage")
        self.assertEqual(set(coverage["value"]), {"requirements", "quoted_vendor_context"})
        vendor = next(t for t in targets if t["kind"] == "claim_coverage")
        self.assertEqual(set(vendor["value"]), {"claims"})
        self.assertEqual({s["kind"] for s in c.audit_payload([coverage], spans)["spans"].values()}, {"package"})
        self.assertEqual({s["kind"] for s in c.audit_payload([vendor], spans)["spans"].values()}, {"profile"})

    def test_workshare_question_does_not_presume_shared_execution(self):
        from common.semantic_plan import question_text
        spans, _, claim, _ = fixture()
        question = question_text({"dimension": "workshare", "claims": [0], "requirements": []}, {"claims": [claim]})
        self.assertIn("if any", question)
        self.assertIn("If others", question)

    def test_qualification_only_evidence_gets_partial_fit_without_work_credit(self):
        from common import semantic_plan as s
        spans, req, claim, findings = fixture()
        spans["V1:0"]["text"] = "Our lifting equipment is certified. No installation project is supplied."
        claim.update(form="qualification", execution="not_execution", meaning="Our lifting equipment is certified.",
                     evidence=[{"ref": "V1:0", "quote": "Our lifting equipment is certified."}])
        req.update(area="scope", task=True, meaning=spans["D1:0"]["text"], evidence=[{"ref": "D1:0", "quote": spans["D1:0"]["text"]}])
        findings["K0"] = {"status": "missing", "reason": "No installation work was supplied.", "evidence": []}
        findings["K1"] = {"status": "matched", "reason": "The equipment qualification is reported.", "evidence": claim["evidence"]}
        inventory = {"requirements": [req], "claims": [claim], "questions": [], "resolved_question_ids": []}
        pairs = s.comparison_pairs(inventory)
        self.assertEqual(len(pairs), 1)
        plan = s.attach_comparisons(inventory, {"pairs": {"C0.R0": {"components": findings}}}, pairs, spans)
        self.assertEqual(plan["comparisons"][0]["fit_label"], "Partial Fit")
        self.assertEqual(plan["comparisons"][0]["relationship"], "unknown")
        rendered = s.render(plan, spans)
        qualified = next(r for r in rendered["uncertainties"] if r.get("claim_form") == "qualification")
        self.assertEqual(qualified["relevance"], "not_applicable")
        self.assertIn("Partial Fit", qualified["current_interpretation"])


if __name__ == "__main__":
    unittest.main()
