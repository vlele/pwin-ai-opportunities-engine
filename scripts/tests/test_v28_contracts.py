"""Routing, isolated criterion credit, transport recovery and prompt wiring."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s, openai_reasoning as api
from test_semantic_contract import fixture


def criterion_fixture(kind="context"):
    spans, req, claim, _ = fixture()
    text = "Relevant experience is completed panel installation."
    spans["D1:0"]["text"] += " " + text
    req.update(area="evaluation", task=False, meaning=text,
               evidence=[{"ref": "D1:0", "quote": text}],
               focus=[{"ref": "D1:0", "quote": text}],
               components=[{"kind": kind, "text": text,
                            "evidence": [{"ref": "D1:0", "quote": text}]}])
    claim.update(meaning="Our employees installed panels.", assertion_basis="delivered_work")
    finding = {"status": "matched", "reason": "Reported installation meets the experience criterion only.",
               "supported_scope": "Completed panel installation experience", "evidence": claim["evidence"]}
    return spans, req, claim, finding


class CriteriaRoutingTests(unittest.TestCase):
    def test_standalone_context_condition_and_qualification_are_routed(self):
        for kind in ("context", "condition", "qualification"):
            with self.subTest(kind=kind):
                _, req, claim, _ = criterion_fixture(kind)
                self.assertEqual([p["id"] for p in s.comparison_pairs({"requirements": [req], "claims": [claim]})], ["C0.R0"])

    def test_noncriteria_and_inactive_records_remain_excluded(self):
        _, req, claim, _ = criterion_fixture()
        variants = [dict(record_kind="metadata"), dict(record_kind="precedence_rule"),
                    dict(status="superseded"), dict(status="draft"), dict(area="precedence"),
                    dict(area="timing"), dict(area="scope")]
        for update in variants:
            with self.subTest(update=update):
                self.assertEqual(s.comparison_pairs({"requirements": [{**req, **update}], "claims": [claim]}), [])

    def test_qualification_claim_routes_to_standalone_qualification(self):
        _, req, claim, _ = criterion_fixture("qualification")
        claim.update(form="qualification", execution="not_execution", assertion_basis="qualification")
        self.assertEqual(len(s.comparison_pairs({"requirements": [req], "claims": [claim]})), 1)

    def test_work_and_criterion_get_distinct_pairs(self):
        _, criterion, claim, _ = criterion_fixture()
        _, work, _, _ = fixture()
        self.assertEqual([p["id"] for p in s.comparison_pairs({"requirements": [work, criterion], "claims": [claim]})], ["C0.R0", "C0.R1"])

    def test_positive_criterion_survives_isolated_schema_and_validator(self):
        spans, req, claim, finding = criterion_fixture()
        pairs = s.comparison_pairs({"requirements": [req], "claims": [claim]})
        self.assertTrue(pairs, "The criterion must reach the Comparator")
        job = next(c.component_jobs(pairs))
        self.assertEqual(job["comparison_kind"], "standalone_criterion")
        self.assertIn("matched", c.component_response_schema(job)["properties"]["status"]["enum"])
        self.assertIn("unrelated", c.component_response_schema(job)["properties"]["status"]["enum"])
        raw = {**finding, **{k: job[k] for k in ("pair_id", "component_id", "component_kind")}}
        result = c.validate_component_response(raw, job, spans)
        self.assertEqual(result["status"], "matched")

    def test_criterion_credit_does_not_become_operational_work_credit(self):
        spans, req, claim, finding = criterion_fixture()
        edge = c.aggregate_components(req, claim, {"K0": finding}, spans)
        self.assertEqual(edge["fit_label"], "Supported Fit")
        self.assertEqual(edge["met_components"], ["K0"])
        self.assertEqual(edge["relationship"], "not_applicable")
        self.assertEqual(edge["matched_work"], "")
        self.assertEqual(edge["coverage"], "not_applicable")

    def test_criterion_cannot_borrow_positive_evidence(self):
        spans, req, claim, finding = criterion_fixture()
        finding["evidence"] = [{"ref": "V1:0", "quote": "We own a warehouse."}]
        with self.assertRaisesRegex(ValueError, "claim"):
            c.aggregate_components(req, claim, {"K0": finding}, spans)

    def test_unrelated_criterion_remains_unrelated_not_unknown_work(self):
        spans, req, claim, finding = criterion_fixture()
        text = "Our employees landscaped gardens."
        spans["V1:0"]["text"] = text
        claim.update(meaning=text, evidence=[{"ref": "V1:0", "quote": text}])
        finding["evidence"] = claim["evidence"]
        finding.update(status="unrelated", supported_scope="", reason="This isolated project is different work.")
        result = c.aggregate_components(req, claim, {"K0": finding}, spans)
        self.assertEqual(result["fit_label"], "Unrelated")
        self.assertEqual(result["relationship"], "not_applicable")
        self.assertEqual(result["matched_work"], "")

    def test_pricing_and_work_context_cannot_be_reclassified_by_isolation(self):
        spans, req, claim, _ = fixture()
        req["components"] = [{"kind": "context", "text": "Administrative rule", "evidence": req["components"][0]["evidence"]},
                             req["components"][0]]
        pair = {"id": "C0.R0", "required": req, "claimed": claim}
        job = next(c.component_jobs([pair]))
        self.assertEqual(job["comparison_kind"], "operational_work")
        self.assertEqual(c.component_response_schema(job)["properties"]["status"]["enum"], ["not_applicable"])
        _, req, claim, _ = criterion_fixture()
        req["components"][0]["kind"] = "pricing"
        self.assertEqual(s.comparison_pairs({"requirements": [req], "claims": [claim]}), [])

    def test_no_criterion_credit_for_vague_or_unattributed_claims(self):
        for update in (dict(form="capability", execution="not_execution"), dict(attribution="unresolved"),
                       dict(form="work_reference", execution="not_execution"), dict(execution="negative")):
            with self.subTest(update=update):
                spans, req, claim, finding = criterion_fixture()
                claim.update(update)
                with self.assertRaises(ValueError):
                    c.aggregate_components(req, claim, {"K0": finding}, spans)

    def test_ordinary_context_still_cannot_receive_credit(self):
        spans, req, claim, finding = criterion_fixture()
        req.update(area="precedence", record_kind="precedence_rule")
        with self.assertRaisesRegex(ValueError, "context"):
            c.aggregate_components(req, claim, {"K0": finding}, spans)

    def test_full_matrix_validation_and_render_retain_criterion(self):
        from test_semantic_plan import fixture as base_fixture
        spans, plan = base_fixture()
        req = plan["requirements"][0]
        text = "Relevant experience is completed display installation."
        spans["D1:0"]["text"] += " " + text
        req.update(meaning=text, evidence=[{"ref": "D1:0", "quote": text}])
        req.update(area="evaluation", task=False, record_kind="requirement", supersedes=[], logic="all",
                   components=[{"kind": "context", "text": text, "evidence": req["evidence"]}])
        plan["requirements"] = [req]
        claim = plan["claims"][0]
        claim.update(execution="affirmative_actual")
        finding = {"status": "matched", "reason": "Supplied experience matches this criterion.",
                   "supported_scope": "Criterion only", "evidence": claim["evidence"]}
        plan["comparisons"] = [{"claim": 0, "requirement": 0, **c.aggregate_components(req, claim, {"K0": finding}, spans)}]
        validated = s.validate(plan, spans)
        rendered = s.render(validated, spans)["uncertainties"][0]
        self.assertEqual(rendered["component_assessments"][0]["met_components"], ["K0"])
        self.assertEqual(rendered["task_alignment"]["shared_work"], "")
        self.assertNotEqual(rendered["relevance"], "direct")
        plan["comparisons"] = []
        with self.assertRaisesRegex(ValueError, "incomplete"):
            s.validate(plan, spans)


@unittest.skipUnless(api.TRANSPORT_ERRORS, "OpenAI SDK is optional")
class TransportRetryTests(unittest.TestCase):
    def setUp(self):
        import httpx
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        self.connection = APIConnectionError(request=request)
        self.timeout = APITimeoutError(request=request)
        self.auth = AuthenticationError("Invalid credentials", response=httpx.Response(401, request=request), body={})
        self.quota = RateLimitError("Quota exhausted", response=httpx.Response(429, request=request), body={"code": "insufficient_quota"})

    def call(self, create):
        client = Mock()
        client.with_options.return_value = client
        client.chat.completions.create = create
        with patch.object(api, "_openai_client", return_value=client), patch.object(api.time, "sleep") as sleep:
            result = api._call_openai_json(system_prompt="test", user_payload={"input": "fixed"}, model="test-model",
                                           timeout_seconds=1, response_schema={"name": "test", "schema": {}, "strict": True})
        self.assertEqual(client.with_options.call_args.kwargs["max_retries"], 0)
        return result, sleep

    def completion(self, content='{"ok": true}'):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def test_three_transport_retries_then_success(self):
        create = Mock(side_effect=[self.connection, self.timeout, self.connection, self.completion()])
        result, sleep = self.call(create)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(create.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        delays = [c.args[0] for c in sleep.call_args_list]
        for actual, base in zip(delays, [1, 2, 4]):
            self.assertGreaterEqual(actual, base)
            self.assertLessEqual(actual, base + 0.25)
        self.assertTrue(all(call == create.call_args_list[0] for call in create.call_args_list))

    def test_exhaustion_fails_closed_after_four_attempts(self):
        for error in (self.connection, self.timeout):
            with self.subTest(error=type(error).__name__):
                create = Mock(side_effect=error)
                result, sleep = self.call(create)
                self.assertIsNone(result)
                self.assertEqual(create.call_count, 4)
                self.assertEqual(sleep.call_count, 3)

    def test_no_retry_for_auth_quota_or_programming_error(self):
        for error in (self.auth, self.quota, ValueError("invalid arguments")):
            with self.subTest(error=type(error).__name__):
                create = Mock(side_effect=error)
                result, sleep = self.call(create)
                self.assertIsNone(result)
                self.assertEqual(create.call_count, 1)
                sleep.assert_not_called()

    def test_invalid_json_is_not_a_transport_retry(self):
        create = Mock(return_value=self.completion("not json"))
        result, sleep = self.call(create)
        self.assertIsNone(result)
        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()

    def test_rejected_semantics_are_not_retried(self):
        create = Mock(return_value=self.completion('{"verdict": "unsupported"}'))
        result, sleep = self.call(create)
        self.assertEqual(result, {"verdict": "unsupported"})
        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()


class PromptContractTests(unittest.TestCase):
    def test_exported_markdown_matches_all_live_prompt_strings(self):
        from export_semantic_prompts import documents, ROOT
        for name, text in documents().items():
            self.assertEqual((ROOT / "references/semantic-prompts" / name).read_text(), text)

    def test_comparator_missing_proof_rule_is_live(self):
        for prompt in (c.COMPONENT_PROMPT, c.ISOLATED_COMPONENT_PROMPT, s.COMPARE_PROMPT):
            self.assertIn("Reserve ambiguous ONLY", prompt)

    def test_auditor_affirmative_claim_boundary_is_live(self):
        for prompt in (s.AUDIT_PROMPT, s.audit_prompt([{"kind": "comparison"}])):
            self.assertIn("An unrelated claim is unrelated", prompt)

    def test_absent_history_rule_reaches_both_detection_channels_and_audit(self):
        for prompt in (c.AMBIGUITY_PROMPT, c.INVENTORY_PROMPT, c.QUESTION_AUDIT_PROMPT):
            self.assertIn("MUST NOT generate clarification questions asking what those missing references describe", prompt)
            self.assertIn("An existing reference with unclear duties still warrants", prompt)


if __name__ == "__main__":
    unittest.main()
