"""Content-independent comparator wire contract and opt-in real-provider probes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as plan, semantic_policy as policy
from common.evidence_selection import EvidenceTransport, SELECTION_PROMPT


PUNCTUATION = "8 1/2\" x 11\" \n & < > 'test'"


def component_case(text=None, vendor=None, *, kind="condition", execution=False):
    text = text or ("The delivered drawing labels must contain exactly: " + PUNCTUATION)
    vendor = vendor or "We offer effective business solutions and understand our customers."
    spans = {"D1:0": {"kind": "package", "source_id": "D1", "offset": 0, "text": text},
             "V1:0": {"kind": "profile", "source_id": "V1", "offset": 0, "text": vendor}}
    job = {"pair_id": "C0.R0", "component_id": "K0", "component_text": text,
           "component_kind": kind, "comparison_kind": "operational_work",
           "component_category": "compliance_certification" if kind == "qualification" else "technical_capability",
           "applicability": "prime_contractor", "routing_reason": "This fixture assigns the condition to the contractor.",
           "component_evidence": [{"ref": "D1:0", "quote": text}],
           "claimed": {"meaning": vendor, "attribution": "self",
                       "form": "performed_task" if execution else "capability",
                       "execution": "affirmative_actual" if execution else "not_execution",
                       "assertion_basis": "delivered_work" if execution else "service_offering",
                       "evidence": [{"ref": "V1:0", "quote": vendor}], "negative_context": []}}
    transport = EvidenceTransport(c.component_response_schema(job), {"component_job": job, "spans": spans})
    return spans, job, transport


def missing_response(job):
    return {**{key: job[key] for key in ("pair_id", "component_id", "component_kind")},
            "status": "missing", "reason": "The isolated vendor claim supplies no proof of this condition.",
            "supported_scope": "", "evidence": []}


class ComponentWireTests(unittest.TestCase):
    def test_arbitrary_wording_is_payload_only_and_does_not_change_wire_schema(self):
        _, job, transport = component_case()
        _, _, plain = component_case("Use the specified drawing label.", "We offer business solutions.")
        self.assertEqual(transport.schema, plain.schema)
        self.assertNotIn("component_text", transport.schema["properties"])
        self.assertEqual(transport.payload["component_job"]["component_text"], job["component_text"])
        self.assertNotIn(PUNCTUATION, json.dumps(transport.schema, ensure_ascii=False))
        self.assertNotIn("quote", transport.schema["properties"]["evidence"]["items"]["properties"])

    def test_code_reattaches_exact_text_without_normalization(self):
        for text in (PUNCTUATION, 'Do NOT accept 12" units; use 18" units.', "Clause \\ path {x} [y]\t\r\n", "\u201cquoted\u201d \u2264 4 \u00b5m"):
            with self.subTest(text=text):
                spans, job, transport = component_case(text)
                raw = missing_response(job)
                jsonschema.validate(raw, transport.schema)
                result = c.validate_component_response(transport.resolve(raw), job, spans)
                self.assertEqual(result["component_text"], text)

    def test_wrong_identity_and_model_supplied_component_text_are_rejected(self):
        spans, job, _ = component_case()
        for field in ("pair_id", "component_id", "component_kind", "component_text"):
            raw = missing_response(job)
            raw[field] = "wrong"
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.validate_component_response(raw, job, spans)

    def test_quoted_claim_evidence_round_trips_without_schema_literals(self):
        spans, job, transport = component_case(vendor="Our employees delivered drawing labels with " + PUNCTUATION, execution=True)
        raw = {**missing_response(job), "status": "matched", "reason": "The reported labels contain the specified content.",
               "supported_scope": job["component_text"], "evidence": [{"evidence_id": "E0"}]}
        jsonschema.validate(raw, transport.schema)
        result = c.validate_component_response(transport.resolve(raw), job, spans)
        self.assertEqual(result["evidence"], job["claimed"]["evidence"])
        raw["evidence"] = [{"evidence_id": "D1:0"}]
        with self.assertRaises(ValueError):
            transport.resolve(raw)

    def test_scope_text_and_evidence_id_do_not_themselves_prove_semantics(self):
        spans, job, _ = component_case()
        finding = {**missing_response(job), "status": "matched", "supported_scope": job["component_text"],
                   "reason": "It appears in the solicitation.", "evidence": job["claimed"]["evidence"]}
        # Structural validity is deliberately NOT mislabeled semantic proof.
        result = c.validate_component_response(finding, job, spans)
        target = {"id": "comparison", "kind": "comparison", "value": result}
        audit = plan.validate_audit({"checks": {"comparison": {
            "verdict": "unsupported", "reason": "A government rule does not establish vendor compliance."}}}, [target])
        self.assertFalse(audit["passed"])

    def test_burden_of_proof_policy_is_shared_by_comparator_and_comparison_auditor(self):
        for prompt in (c.COMPONENT_PROMPT, c.ISOLATED_COMPONENT_PROMPT, plan.COMPARE_PROMPT,
                       plan.AUDIT_PROMPT, plan.audit_prompt([{"kind": "comparison"}])):
            self.assertIn(policy.BURDEN_OF_PROOF_POLICY, prompt)
        self.assertNotIn(policy.BURDEN_OF_PROOF_POLICY, policy.apply_policies("Source fidelity only", execution=False))
        for kind in ("requirement", "package_coverage", "package_reference"):
            self.assertNotIn(policy.BURDEN_OF_PROOF_POLICY, plan.audit_prompt([{"kind": kind}]))

    def test_changed_prompt_schema_and_runtime_do_not_reuse_old_checkpoint(self):
        from common.understanding_checkpoints import StageCheckpoints
        _, job, transport = component_case()
        old = deepcopy(transport.schema)
        old["properties"]["component_text"] = {"type": "string", "enum": [job["component_text"]]}
        old["required"].append("component_text")
        store = StageCheckpoints("unused", scope={}, runtime="test")
        new_key = store.key("component", c.ISOLATED_COMPONENT_PROMPT, transport.payload, transport.schema, {})
        self.assertNotEqual(new_key, store.key("component", c.ISOLATED_COMPONENT_PROMPT, transport.payload, old, {}))
        self.assertNotEqual(new_key, store.key("component", "old prompt", transport.payload, transport.schema, {}))


@unittest.skipUnless(os.getenv("PWIN_LIVE_COMPONENT_TEST") == "1", "Explicit opt-in required: real API charges")
class LiveComponentWireTests(unittest.TestCase):
    def run_case(self, name, expected, **options):
        import httpx
        from openai import OpenAI
        from common import openai_reasoning as api

        self.assertTrue(os.getenv("OPENAI_API_KEY"), "Live test requires OPENAI_API_KEY")
        folder = Path(os.environ["PWIN_LIVE_TEST_AUDIT_DIR"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (name + ".json")
        self.assertFalse(path.exists(), "Do not overwrite a live result or resample silently")
        spans, job, transport = component_case(**options)
        replies = []

        def observe(response):
            response.read()
            body = response.json()
            replies.append({"http_status": response.status_code, "model": body.get("model"),
                            "usage": body.get("usage"), "request_id": response.headers.get("x-request-id")})

        with OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.getenv("OPENAI_BASE_URL"),
                    max_retries=0, http_client=httpx.Client(event_hooks={"response": [observe]})) as client:
            # Only client construction is replaced, with a REAL instrumented client.
            # The production request serializer, retry boundary and JSON parser run.
            with patch.object(api, "_openai_client", return_value=client):
                raw = api._call_openai_json(
                    system_prompt=c.ROUTED_COMPONENT_PROMPT + "\n" + SELECTION_PROMPT,
                    user_payload=transport.payload, model="gpt-5.4-mini", reasoning_effort="medium", timeout_seconds=120,
                    response_schema={"name": "capture_understanding", "strict": True, "schema": transport.schema})
        receipt = {"model": "gpt-5.4-mini", "reasoning_effort": "medium", "job": job,
                   "schema": transport.schema, "response": raw, "http_responses": replies, "expected_status": expected}
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        self.assertEqual([r["http_status"] for r in replies], [200])
        jsonschema.validate(raw, transport.schema)
        checked = c.validate_component_response(transport.resolve(raw), job, spans)
        self.assertEqual(checked["status"], expected)
        self.assertEqual(checked["component_text"], job["component_text"])
        receipt.update(validated_decision=checked, passed=True)
        path.write_text(json.dumps(receipt, indent=2) + "\n")

    def test_severe_punctuation_with_generic_vendor_is_missing(self):
        self.run_case("punctuation-missing", "missing")

    def test_explicit_reported_delivery_with_same_punctuation_is_matched(self):
        self.run_case("punctuation-matched", "matched", execution=True,
                      vendor="Our employees delivered drawing labels containing exactly: " + PUNCTUATION)

    def test_requirement_is_not_vendor_registration_proof(self):
        self.run_case("registration-missing", "missing", kind="qualification",
                      text="The offeror must be a registered user of the designated submission portal.")


if __name__ == "__main__":
    unittest.main()
