"""Prompt wiring and immutable guardrails, not a claim of live model accuracy."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u, evidence_selection as es
from common import requirement_context as rc
from tests.test_evidence_selection import schema, selection
from tests.test_requirement_context import fixture
from tests.test_question_channel import pipeline_model


def parent_fixture():
    spans, raw = fixture()
    for row in raw["requirements"]:
        row.pop("meaning")
        row["supporting_context"] = row.pop("evidence")
    return spans, raw


class InventoryPromptTests(unittest.TestCase):
    def test_base_inventory_states_numeric_limit_and_preserves_material_context(self):
        prompt = rc.parent_inventory_prompt()
        self.assertIn("8,000 characters", prompt)
        self.assertIn("separate bounded selections", prompt)
        self.assertIn("not a page-count limit", prompt)
        self.assertIn("exceptions, negations or required conditions", prompt)

    def test_source_role_rule_uses_metadata_and_actual_array_names(self):
        prompt = rc.parent_inventory_prompt()
        self.assertIn('kind="package"', prompt)
        self.assertIn("not an ID prefix", prompt)
        self.assertIn("Private profile assertions belong in claims", prompt)
        self.assertIn("quoted_vendor_context must also cite package sources", prompt)

    def test_base_transport_and_both_repairs_expose_the_limit(self):
        for prompt in (es.SELECTION_PROMPT, es.REPAIR_PROMPT,
                       getattr(u, "CONTRACT_CORRECTION_PROMPT", "")):
            with self.subTest(prompt=prompt[:50]):
                self.assertIn("8,000 characters", prompt)
        self.assertEqual(es.MAX_SELECTION_CHARS, 8000)

    def test_general_repair_preserves_arrays_and_remaps_only_same_subject(self):
        prompt = getattr(u, "CONTRACT_CORRECTION_PROMPT", "")
        for instruction in ("Retain all previously valid claims", "Do not clear arrays",
                            "zero-based", "same retained subject", "supersedes",
                            "quoted_vendor_context", "one allowed contract correction"):
            self.assertIn(instruction, prompt)

    def test_prompt_exports_include_actual_correction_and_selection_instructions(self):
        from tests.export_semantic_prompts import documents
        text = documents()["EXTRACTOR-PROMPT.md"]
        for prompt in (es.SELECTION_PROMPT, es.REPAIR_PROMPT,
                       getattr(u, "CONTRACT_CORRECTION_PROMPT", "MISSING CORRECTION PROMPT")):
            self.assertIn(prompt.strip(), text)


class ExistingInvariantTests(unittest.TestCase):
    def test_exact_limit_succeeds_one_more_character_fails(self):
        for length in (8000, 8001):
            spans = {"D1:0": {"kind": "package", "source_id": "D1", "offset": 0,
                              "text": "x" * length}}
            transport = es.EvidenceTransport(schema(), {"spans": spans})
            if length == 8000:
                result = transport.resolve({"evidence": [selection(line=1)]})
                self.assertEqual(len(result["evidence"][0]["quote"]), length)
            else:
                with self.assertRaisesRegex(ValueError, "bounded selection budget"):
                    transport.resolve({"evidence": [selection(line=1)]})

    def test_separate_selections_preserve_long_scope_and_qualification(self):
        texts = ["Install equipment. " + "x" * 6900,
                 "Do not waive the licensed-staff requirement. " + "y" * 6900]
        spans = {ref: {"kind": "package", "source_id": ref.split(":")[0],
                       "offset": 0, "source_offset": offset, "document_id": "synthetic-scope",
                       "text": text}
                 for ref, text, offset in (("D1:0", texts[0], 0),
                                          ("D2:0", texts[1], len(texts[0])))}
        transport = es.EvidenceTransport(schema(), {"spans": spans})
        last = len(transport.payload["spans"]["D2:0"]["text"].splitlines())
        first_last = len(transport.payload["spans"]["D1:0"]["text"].splitlines())
        with self.assertRaisesRegex(ValueError, "bounded selection budget"):
            transport.resolve({"evidence": [selection(line=1, end="D2:0", last=last)]})
        result = transport.resolve({"evidence": [selection(line=1, last=first_last),
                                                  selection("D2:0", 1, last=last)]})
        self.assertEqual("".join(a["quote"] for a in result["evidence"]), "".join(texts))

    def test_private_focus_and_supporting_context_cannot_establish_requirements(self):
        for field in ("focus", "supporting_context"):
            spans, raw = parent_fixture()
            spans["D-private:0"] = spans.pop("V0:0")
            raw["requirements"][0][field] = [{"ref": "D-private:0", "quote": spans["D-private:0"]["text"]}]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "private"):
                rc.validate_parent_inventory(raw, spans)

    def test_package_role_is_not_inferred_from_prefix(self):
        spans, raw = parent_fixture()
        spans["V-official:0"] = spans.pop("D0:0")
        for field in ("focus", "supporting_context"):
            for anchor in raw["requirements"][0][field]:
                anchor["ref"] = "V-official:0"
        checked = rc.validate_parent_inventory(raw, spans)
        self.assertEqual(checked["requirements"][0]["focus"][0]["ref"], "V-official:0")

    def test_dangling_question_index_still_fails(self):
        spans, raw = parent_fixture()
        raw["questions"] = [{"dimension": "official_conflict", "claims": [],
                             "requirements": [0, 1], "reason": "Conflicting terms.",
                             "decision": "timing"}]
        with self.assertRaisesRegex(ValueError, "Unknown record index"):
            rc.validate_parent_inventory(raw, spans)

    def test_dangling_supersedes_index_still_fails(self):
        spans, raw = parent_fixture()
        raw["requirements"][0]["supersedes"] = [1]
        with self.assertRaises(ValueError):
            rc.validate_parent_inventory(raw, spans)

    def test_citation_only_merge_cannot_drop_valid_claims(self):
        model, _, packet = pipeline_model()
        expected = []
        observed = []
        good = None

        def provider(**request):
            nonlocal good
            payload = request["user_payload"]
            if "repair_targets" in payload:
                observed.append(payload)
                return {"repairs": {"T0": [good]}}
            response = model(**request)
            if payload.get('inventory_mode') == 'vendor':
                expected.append(deepcopy(response))
                good = deepcopy(response['claims'][0]['evidence'][0])
                response['claims'][0]['evidence'][0]['start']['line'] = 999
            return response

        result = u.analyze_packet(packet, [], {}, call=provider)
        self.assertNotIn("pipeline_errors", result)
        self.assertEqual(len(observed), 1)
        plan = result["understanding_audit"]["semantic_plan"]
        self.assertEqual(len(plan["claims"]), len(expected[0]["claims"]))
        self.assertTrue(plan["claims"])
        self.assertEqual(plan["claims"][0]["meaning"], expected[0]["claims"][0]["meaning"])


class GeneralCorrectionWiringTests(unittest.TestCase):
    def test_runtime_correction_receives_preservation_policy_and_previous_response(self):
        model, _, packet = pipeline_model()
        calls = []

        def provider(**request):
            payload = request["user_payload"]
            if payload.get('inventory_mode') == 'package':
                calls.append(deepcopy(payload))
                if len(calls) == 1:
                    return {}
            return model(**request)

        result = u.analyze_packet(packet, [], {}, call=provider)
        self.assertNotIn("pipeline_errors", result)
        self.assertEqual(len(calls), 2)
        correction = calls[1]["contract_correction"]
        self.assertEqual(correction["previous_response"], {})
        self.assertTrue(correction["error"])
        self.assertIn("Retain all previously valid claims", correction["instruction"])
        self.assertEqual(correction["instruction"], u.CONTRACT_CORRECTION_PROMPT)

    def test_invalid_correction_does_not_get_a_third_attempt(self):
        model, _, packet = pipeline_model()
        calls = []

        def provider(**request):
            if "source_coverage" in request["user_payload"]:
                calls.append(request)
                return {}
            return model(**request)

        result = u.analyze_packet(packet, [], {}, call=provider)
        self.assertEqual(len(calls), 2)
        self.assertIn("contract invalid after one correction", result["pipeline_errors"][0])


if __name__ == "__main__":
    unittest.main()
