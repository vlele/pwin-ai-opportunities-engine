"""Regression contracts; mocked semantic choices are not live-model proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import semantic_contract as c, semantic_plan as s
from run_semantic_classification_benchmark import grade_case


def fixture():
    texts = {
        "D:0": "Install sensing modules using certified lifting equipment.",
        "V:0": "Our employees install sensing modules. We do not conduct chemical testing.",
        "X:0": "Another company conducts chemical testing.",
    }
    spans = {k: {"text": v, "kind": "package" if k == "D:0" else "profile",
                 "source_id": k.split(":")[0], "offset": 0} for k, v in texts.items()}
    anchor = lambda ref, quote: {"ref": ref, "quote": quote}
    req = {"logic": "all", "record_kind": "requirement", "components": [
        {"kind": "work", "text": "Install sensing modules", "evidence": [anchor("D:0", texts["D:0"])]},
        {"kind": "qualification", "text": "Certified lifting equipment", "evidence": [anchor("D:0", texts["D:0"])]}]}
    claim = {"form": "performed_task", "execution": "affirmative_actual", "attribution": "self",
             "meaning": "Employees install sensing modules.", "unresolved_dimensions": [],
             "evidence": [anchor("V:0", "Our employees install sensing modules.")]}
    denial = {"form": "context", "execution": "negative", "attribution": "self",
              "assertion_basis": "work_denial", "meaning": "No chemical testing.", "unresolved_dimensions": [],
              "evidence": [anchor("V:0", "We do not conduct chemical testing.")]}
    return spans, req, claim, denial


class GroundingTests(unittest.TestCase):
    def test_inventory_schema_allows_no_antecedent_for_standalone_claims(self):
        import jsonschema
        spans, _, _, _ = fixture()
        schema = s.inventory_schema(spans, components=True)
        field = schema["properties"]["claims"]["items"]["properties"]["antecedent_evidence"]
        jsonschema.Draft202012Validator(field).validate([])

    def test_linked_delivery_still_requires_an_antecedent(self):
        spans, _, old, _ = fixture()
        raw = {k: v for k, v in old.items() if k not in {"form", "execution"}}
        raw.update(assertion_basis="linked_delivery", antecedent_evidence=[])
        with self.assertRaises(ValueError):
            c.ground_claims([raw], spans)

    def test_noncommercial_conditions_cannot_be_discarded_as_not_applicable(self):
        spans, req, claim, _ = fixture()
        for kind in ("qualification", "condition", "timing", "quantity", "acceptance"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                req["components"][1]["kind"] = kind
                c.aggregate_components(req, claim, {
                    "K0": {"status": "matched", "reason": "Reported installation.", "supported_scope": "Installation", "evidence": claim["evidence"]},
                    "K1": {"status": "not_applicable", "reason": "This discards a real condition.", "supported_scope": "", "evidence": []}}, spans)

    def test_timing_component_schema_cannot_emit_not_applicable(self):
        _, req, claim, _ = fixture()
        req["components"][1]["kind"] = "timing"
        schema = c.comparison_schema([{"id": "C0.R0", "required": req, "claimed": claim}])
        allowed = schema["properties"]["pairs"]["properties"]["C0.R0"]["properties"]["components"]["properties"]["K1"]["properties"]["status"]["enum"]
        self.assertNotIn("not_applicable", allowed)

    def test_known_performer_can_have_unknown_duties_and_workshare(self):
        _, _, claim, _ = fixture()
        claim.update(form="work_reference", execution="unclear", unresolved_dimensions=["task_meaning", "workshare"])
        c.validate_claim_dimensions(claim)

    def test_real_identity_conflict_still_requires_unresolved_attribution(self):
        _, _, claim, _ = fixture()
        claim.update(form="work_reference", execution="unclear", unresolved_dimensions=["task_meaning", "performer_identity"])
        with self.assertRaises(ValueError):
            c.validate_claim_dimensions(claim)

    def test_staff_execution_basis_derives_work_without_second_form_vote(self):
        spans, _, old, _ = fixture()
        raw = {k: v for k, v in old.items() if k not in {"form", "execution"}}
        raw.update(assertion_basis="staff_execution", antecedent_evidence=[])
        result = c.ground_claims([raw], spans)[0]
        self.assertEqual((result["form"], result["execution"]), ("performed_task", "affirmative_actual"))

    def test_future_staffing_is_not_execution(self):
        spans, _, old, _ = fixture()
        spans["V:0"]["text"] = "Our employees would install the modules if selected."
        raw = {k: v for k, v in old.items() if k not in {"form", "execution"}}
        raw.update(assertion_basis="proposed_work", antecedent_evidence=[], evidence=[{"ref": "V:0", "quote": spans["V:0"]["text"]}])
        result = c.ground_claims([raw], spans)[0]
        self.assertEqual((result["form"], result["execution"]), ("capability", "prospective"))

    def test_linked_delivery_keeps_antecedent_and_execution_quotes(self):
        spans, _, old, _ = fixture()
        activity = "We survey reservoirs using optical instruments."
        delivery = "Our crew delivered these surveys."
        spans["V:0"]["text"] = activity + " " + delivery
        raw = {k: v for k, v in old.items() if k not in {"form", "execution"}}
        raw.update(assertion_basis="linked_delivery", evidence=[{"ref": "V:0", "quote": delivery}],
                   antecedent_evidence=[{"ref": "V:0", "quote": activity}])
        result = c.ground_claims([raw], spans)[0]
        self.assertEqual({a["quote"] for a in result["evidence"]}, {activity, delivery})
        self.assertEqual(result["form"], "performed_task")

    def test_antecedent_cannot_come_from_another_company_field(self):
        spans, _, old, _ = fixture()
        raw = {k: v for k, v in old.items() if k not in {"form", "execution"}}
        raw.update(assertion_basis="linked_delivery", antecedent_evidence=[{"ref": "X:0", "quote": spans["X:0"]["text"]}])
        with self.assertRaises(ValueError):
            c.ground_claims([raw], spans)

    def test_linked_negative_evidence_is_preserved_without_work_credit(self):
        spans, req, claim, denial = fixture()
        claims = c.bind_negative_context([claim, denial], spans)
        req["components"] = [{"kind": "work", "text": "Conduct chemical testing", "evidence": req["components"][0]["evidence"]}]
        finding = {"K0": {"status": "contradicted", "reason": "The same vendor explicitly denies this activity.",
                           "supported_scope": "", "evidence": denial["evidence"]}}
        edge = c.aggregate_components(req, claims[0], finding, spans)
        self.assertEqual(edge["fit_label"], "Unrelated")
        self.assertEqual(edge["matched_work"], "")
        self.assertEqual(edge["component_findings"]["K0"]["evidence_links"][0]["claim_id"], "C1")

    def test_linked_denial_cannot_prove_positive_work(self):
        spans, req, claim, denial = fixture()
        claim = c.bind_negative_context([claim, denial], spans)[0]
        finding = {"K0": {"status": "matched", "reason": "Not a valid positive proof.", "supported_scope": "Installation", "evidence": denial["evidence"]},
                   "K1": {"status": "missing", "reason": "Not supplied.", "supported_scope": "", "evidence": []}}
        with self.assertRaises(ValueError):
            c.aggregate_components(req, claim, finding, spans)

    def test_other_performer_denial_is_not_automatically_attached(self):
        spans, _, claim, denial = fixture()
        denial["attribution"] = "other"
        self.assertEqual(c.bind_negative_context([claim, denial], spans)[0]["negative_context"], [])

    def test_absent_history_can_explain_missing_without_becoming_denial(self):
        spans, req, claim, context = fixture()
        quote = "Our project descriptions have not been supplied."
        spans["V:1"] = {**spans["V:0"], "text": quote, "offset": 90}
        context.update(assertion_basis="negative_context", attribution="not_applicable",
                       meaning="No project descriptions supplied.", evidence=[{"ref": "V:1", "quote": quote}])
        claim = c.bind_negative_context([claim, context], spans)[0]
        findings = {f"K{i}": {"status": "missing", "reason": "History is not supplied.",
                     "supported_scope": "", "evidence": context["evidence"]} for i in range(2)}
        edge = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual(edge["fit_label"], "Unknown")
        self.assertEqual(edge["component_findings"]["K0"]["evidence_links"][0]["relation"], "uncertainty_context")

    def test_absent_history_cannot_establish_unrelated_or_contradicted(self):
        spans, req, claim, context = fixture()
        context.update(assertion_basis="negative_context", attribution="not_applicable")
        claim = c.bind_negative_context([claim, context], spans)[0]
        for status in ("matched", "partial", "transferable", "unrelated", "contradicted"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                c.aggregate_components(req, claim, {
                    "K0": {"status": status, "reason": "Cannot infer work from absent history.",
                           "supported_scope": "Installation" if status in {"matched", "partial", "transferable"} else "",
                           "evidence": context["evidence"]},
                    "K1": {"status": "missing", "reason": "Not supplied.", "supported_scope": "", "evidence": []}}, spans)

    def test_bound_denial_may_cross_chunks_of_the_same_source(self):
        spans, req, claim, denial = fixture()
        quote = denial["evidence"][0]["quote"]
        spans["V:1"] = {**spans["V:0"], "text": quote, "offset": 90}
        denial["evidence"] = [{"ref": "V:1", "quote": quote}]
        claim = c.bind_negative_context([claim, denial], spans)[0]
        req["components"] = req["components"][:1]
        result = c.aggregate_components(req, claim, {"K0": {
            "status": "contradicted", "reason": "Explicit same-subject denial.",
            "supported_scope": "", "evidence": denial["evidence"]}}, spans)
        self.assertEqual(result["fit_label"], "Unrelated")

    def test_missing_source_identity_does_not_join_unrelated_chunks(self):
        spans, _, claim, denial = fixture()
        for value in spans.values():
            value["source_id"] = None
        spans["X:0"]["text"] = denial["evidence"][0]["quote"]
        denial["evidence"][0]["ref"] = "X:0"
        self.assertEqual(c.bind_negative_context([claim, denial], spans)[0]["negative_context"], [])

    def test_different_source_denial_is_not_automatically_attached(self):
        spans, _, claim, denial = fixture()
        spans["X:0"]["text"] = denial["evidence"][0]["quote"]
        denial["evidence"][0]["ref"] = "X:0"
        self.assertEqual(c.bind_negative_context([claim, denial], spans)[0]["negative_context"], [])

    def test_explicit_work_denial_is_assessed_but_never_performed_work(self):
        spans, req, _, denial = fixture()
        req.update(status="current")
        pairs = s.comparison_pairs({"requirements": [req], "claims": [denial]})
        self.assertEqual(len(pairs), 1)
        self.assertEqual(denial["form"], "context")
        schema = c.comparison_schema(pairs)
        statuses = schema["properties"]["pairs"]["properties"]["C0.R0"]["properties"]["components"]["properties"]["K0"]["properties"]["status"]["enum"]
        self.assertIn("contradicted", statuses)
        self.assertNotIn("matched", statuses)

    def test_denied_required_work_is_unrelated_without_imagining_other_experience(self):
        spans, req, _, denial = fixture()
        req["components"][0]["text"] = "Conduct chemical testing"
        finding = {"K0": {"status": "contradicted", "reason": "This work is explicitly denied.", "supported_scope": "", "evidence": denial["evidence"]},
                   "K1": {"status": "missing", "reason": "No qualification evidence.", "supported_scope": "", "evidence": []}}
        result = c.aggregate_components(req, denial, finding, spans)
        self.assertEqual((result["fit_label"], result["coverage"]), ("Unrelated", "none"))
        self.assertEqual(result["met_components"], [])

    def test_denial_of_one_alternative_does_not_reject_all_other_alternatives(self):
        spans, req, _, denial = fixture()
        req.update(logic="any")
        req["components"] = [{"kind": "work", "text": term, "evidence": req["components"][0]["evidence"]}
                             for term in ("Conduct chemical testing", "Provide thermal measurements")]
        finding = {"K0": {"status": "contradicted", "reason": "Explicitly denied.", "supported_scope": "", "evidence": denial["evidence"]},
                   "K1": {"status": "missing", "reason": "Alternative not supplied.", "supported_scope": "", "evidence": []}}
        self.assertEqual(c.aggregate_components(req, denial, finding, spans)["fit_label"], "Unknown")

    def test_work_and_pricing_are_separate_assessable_components(self):
        spans, req, claim, _ = fixture()
        req["components"][1].update(kind="pricing", text="Fixed-price execution")
        finding = {"K0": {"status": "matched", "reason": "Reported installation.", "supported_scope": "Installation", "evidence": claim["evidence"]},
                   "K1": {"status": "not_applicable", "reason": "Price is not experience.", "supported_scope": "", "evidence": []}}
        self.assertEqual(c.aggregate_components(req, claim, finding, spans)["relationship"], "same_task")

    def test_claim_local_context_must_not_change_requirement_fidelity_audit(self):
        spans, req, claim, denial = fixture()
        package = c.audit_payload([{"id": "R0", "kind": "requirement", "value": req}], spans)
        self.assertEqual(set(package["spans"]), {"D:0"})
        self.assertNotIn("claims", package)

    def test_partial_work_does_not_prove_missing_qualification(self):
        spans, req, claim, _ = fixture()
        findings = {"K0": {"status": "matched", "reason": "Reported installation.", "supported_scope": "Installation", "evidence": claim["evidence"]},
                    "K1": {"status": "missing", "reason": "Certification not supplied.", "supported_scope": "", "evidence": []}}
        edge = c.aggregate_components(req, claim, findings, spans)
        self.assertEqual((edge["fit_label"], edge["met_components"], edge["missing_components"]), ("Partial Fit", ["K0"], ["K1"]))


class StrictDecisionTests(unittest.TestCase):
    def test_all_unknown_cannot_pass_an_explicit_task_expectation(self):
        case = {"statuses": ["READY"], "relevance": [], "ambiguity": [], "verification": [], "facts": [], "question_kinds": [],
                "semantic_expectations": {"tasks": [{"requirement_quote": "Installation is fixed-price.",
                    "claim_quote": "Our employees install the modules.", "relationship": "same_task"}]}}
        state = {"status": "READY", "questions": [], "open_gaps": [], "interpretation": [], "understanding_audit": {"semantic_plan": {
            "requirements": [{"meaning": "Installation is fixed-price."}],
            "claims": [{"evidence": [{"ref": "V:0", "quote": "Our employees install the modules."}]}],
            "comparisons": [{"claim": 0, "requirement": 0, "relationship": "unknown"}]}}}
        self.assertFalse(grade_case(case, state)["pass"])
        state["understanding_audit"]["semantic_plan"]["comparisons"][0]["relationship"] = "same_task"
        self.assertTrue(grade_case(case, state)["pass"])

    def test_pricing_presence_without_correct_line_allocation_fails(self):
        case = {"statuses": ["READY"], "relevance": [], "ambiguity": [], "verification": [], "facts": [], "question_kinds": [],
                "semantic_expectations": {"pricing": [{"requirement_quote": "CLIN 1", "pricing_pattern": "labor.hour"}]}}
        state = {"status": "READY", "questions": [], "open_gaps": [], "interpretation": [], "understanding_audit": {"semantic_plan": {
            "requirements": [{"meaning": "CLIN 1 installation", "status": "current", "components": [{"kind": "pricing", "text": "Fixed-price"}]},
                             {"meaning": "CLIN 2 repair", "status": "current", "components": [{"kind": "pricing", "text": "Labor-hour"}]}],
            "claims": [], "comparisons": []}}}
        self.assertFalse(grade_case(case, state)["pass"])


class NewProtocolPipelineTests(unittest.TestCase):
    def test_self_attributed_unknown_workshare_still_reaches_user_on_unrelated_audit_failure(self):
        from test_question_channel import pipeline_model
        from common import capture_understanding as u, capture_clarification as gate
        model, _, packet = pipeline_model(fail_claim=True)
        def grounded_model(**kwargs):
            value = model(**kwargs)
            if kwargs['user_payload'].get('inventory_mode') == 'vendor':
                claim = value["claims"][0]
                claim.pop("form")
                claim.pop("execution")
                claim.update(assertion_basis="unresolved_reference", antecedent_evidence=[],
                             unresolved_dimensions=["task_meaning", "workshare"])
            return value
        state = gate.validate_assessment(u.analyze_packet(packet, [], {}, call=grounded_model), packet)
        self.assertTrue(state["questions"])
        self.assertNotEqual(state["status"], "READY")
        self.assertTrue(any(q["routing_reason"] in {"task_meaning", "workshare"} for q in state["questions"]))


if __name__ == "__main__":
    unittest.main()
