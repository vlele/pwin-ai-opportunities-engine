"""Storage/request separation and restart integrity, without live model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u, capture_clarification as gate, understanding_checkpoints as cp
from tests.test_question_channel import pipeline_model


class ReceiptTests(unittest.TestCase):
    def test_identity_invalidates_every_material_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store = cp.StageCheckpoints(folder, scope={"profile": "one"}, runtime="runtime-one")
            args = ["extract-1", "prompt", {"spans": "source"}, {"type": "object"}, {"model": "one", "reasoning_effort": "medium"}]
            key = store.key(*args)
            for index, replacement in enumerate(["extract-2", "new prompt", {"spans": "changed"}, {"type": "array"}, {"model": "two"}]):
                changed = deepcopy(args)
                changed[index] = replacement
                self.assertNotEqual(key, store.key(*changed))
            for scope, runtime in (({"profile": "two"}, "runtime-one"), ({"profile": "one"}, "runtime-two")):
                self.assertNotEqual(key, cp.StageCheckpoints(folder, scope=scope, runtime=runtime).key(*args))

    def test_corrupt_checkpoint_is_not_a_cache_miss(self):
        with tempfile.TemporaryDirectory() as folder:
            store = cp.StageCheckpoints(folder, scope={}, runtime="test")
            store.save("key", {"supported": False}, stage="audit")
            self.assertFalse(store.load("key")["response"]["supported"])
            path = Path(folder) / "key.json"
            row = json.loads(path.read_text())
            row["response"]["supported"] = True
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "integrity"):
                store.load("key")
            path.write_text("not JSON")
            with self.assertRaisesRegex(ValueError, "Unreadable"):
                store.load("key")

    def test_request_budget_includes_prompt_and_schema(self):
        with self.assertRaisesRegex(ValueError, "No silent truncation"):
            cp.check_request_budget("p" * 500, {}, {}, 400)
        with self.assertRaises(ValueError):
            cp.check_request_budget("p", {}, {"description": "s" * 500}, 400)
        size = cp.check_request_budget("p", {"text": "value"}, {}, 1000)
        self.assertEqual(size, cp.check_request_budget("p", {"text": "value"}, {}, size))
        with self.assertRaises(ValueError):
            cp.check_request_budget("p", {"text": "value"}, {}, size - 1)

    def test_concurrent_verdict_cannot_replace_existing_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            store = cp.StageCheckpoints(folder, scope={}, runtime="test")
            store.save("key", {"supported": False}, stage="audit")
            store.save("key", {"supported": False}, stage="audit")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                store.save("key", {"supported": True}, stage="audit")
            self.assertFalse(store.load("key")["response"]["supported"])
            self.assertFalse(list(Path(folder).glob(".pending-*")))

    def test_unwritable_storage_is_a_diagnostic_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            store = cp.StageCheckpoints(folder, scope={}, runtime="test")
            with patch.object(Path, "mkdir", side_effect=OSError("disk unavailable")):
                with self.assertRaisesRegex(ValueError, "Cannot persist"):
                    store.save("key", {}, stage="audit")

    def test_storage_limit_is_separate_and_empty_still_fails(self):
        facts = [{"statement": "scope" * 40000}]
        result = cp.validate_ledger(facts, [])
        self.assertGreater(result["storage_bytes"], 160000)
        self.assertFalse(result["used_as_model_input"])
        with self.assertRaisesRegex(ValueError, "empty"):
            cp.validate_ledger([], [])
        with patch.object(cp, "MAX_LEDGER_STORAGE_BYTES", 100), self.assertRaisesRegex(ValueError, "storage safety"):
            cp.validate_ledger(facts, [])


class PipelineRestartTests(unittest.TestCase):
    def test_warm_resume_requires_cached_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            with self.assertRaisesRegex(ValueError, "intact attachment cache"):
                gate.local_attachment_cache(workspace, "inputs", lambda: self.fail("Paid extraction"), require_cached=True)
            saved = gate.local_attachment_cache(workspace, "inputs", lambda: {"attachments": [{"text": "original"}]})
            self.assertEqual(gate.local_attachment_cache(workspace, "inputs", lambda: self.fail("Paid extraction"), require_cached=True), saved)
            with self.assertRaisesRegex(ValueError, "cannot refresh"):
                gate.local_attachment_cache(workspace, "inputs", lambda: None, retry=True, require_cached=True)

    def test_warm_resume_refuses_new_scope_without_calling_model(self):
        _, _, packet = pipeline_model()
        with tempfile.TemporaryDirectory() as folder, patch.object(gate, "analyze_understanding") as provider:
            result = gate.resume_checkpoint(Path(folder), packet)
            self.assertEqual(result['status'], 'TECHNICAL_BLOCKED')
            provider.assert_not_called()

    def test_large_valid_ledger_proceeds_and_preserves_every_fact(self):
        model, _, packet = pipeline_model()

        def large(**kwargs):
            response = model(**kwargs)
            if "facts" in response:
                response["facts"] = [deepcopy(response["facts"][0]) for _ in range(2200)]
            return response

        result = u.analyze_packet(packet, [], {}, call=large)
        self.assertNotIn("pipeline_errors", result)
        audit = result["understanding_audit"]
        self.assertEqual(len(audit["facts"]), 2200)
        self.assertGreater(audit["ledger_storage"]["storage_bytes"], 160000)
        self.assertTrue(audit["claim_evidence"]["passed"])

    def test_empty_and_incomplete_extraction_still_block(self):
        for change in ({"facts": []}, {"complete": False}):
            model, _, packet = pipeline_model()

            def invalid(**kwargs):
                response = model(**kwargs)
                if "facts" in response:
                    response.update(change)
                return response

            result = u.analyze_packet(packet, [], {}, call=invalid)
            self.assertTrue(result["pipeline_errors"])
            self.assertFalse(any(s["stage"] == "semantic-inventory" for s in result["understanding_audit"]["stages"]))

    def test_resume_matches_uninterrupted_and_revalidates_receipts(self):
        model, _, packet = pipeline_model()
        full = u.analyze_packet(packet, [], {}, call=model)
        with tempfile.TemporaryDirectory() as folder:
            def interrupted(**kwargs):
                if "source_coverage" in kwargs["user_payload"]:
                    return None
                return model(**kwargs)

            first = u.analyze_packet(packet, [], {}, call=interrupted, checkpoint_dir=folder)
            self.assertTrue(first["pipeline_errors"])
            self.assertTrue(first["understanding_audit"]["facts"])
            self.assertTrue(first["understanding_audit"]["source_coverage"])
            paid = []

            def resumed(**kwargs):
                paid.append(kwargs)
                return model(**kwargs)

            second = u.analyze_packet(packet, [], {}, call=resumed, checkpoint_dir=folder)
            self.assertEqual(full["interpretation"], second["interpretation"])
            self.assertEqual(full["uncertainties"], second["uncertainties"])
            self.assertEqual(full["independent_questions"], second["independent_questions"])
            self.assertEqual(full["understanding_audit"]["facts"], second["understanding_audit"]["facts"])
            self.assertIn("source_coverage", paid[0]["user_payload"])
            self.assertEqual(sum(s["execution"] == "checkpoint_revalidated" for s in second["understanding_audit"]["stages"]), 3)
            with patch.object(u, "_validate_extraction", side_effect=ValueError("Evidence is invalid under current validator")):
                rejected = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Must not silently resample"), checkpoint_dir=folder)
            self.assertIn("checkpoint validation", rejected["pipeline_errors"][0])

    def test_negative_audit_is_not_resampled_on_restart(self):
        model, _, packet = pipeline_model(fail_claim=True)
        with tempfile.TemporaryDirectory() as folder:
            first = u.analyze_packet(packet, [], {}, call=model, checkpoint_dir=folder)
            self.assertTrue(first["pipeline_errors"])
            again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("No retry until audit passes"), checkpoint_dir=folder)
            self.assertEqual(first["pipeline_errors"], again["pipeline_errors"])
            self.assertEqual(first["understanding_audit"]["claim_evidence"], again["understanding_audit"]["claim_evidence"])

    def test_valid_correction_is_reused_without_retrying_bad_first_response(self):
        model, _, packet = pipeline_model()
        corrected = False

        def initial(**kwargs):
            nonlocal corrected
            if "source_coverage" in kwargs["user_payload"] and not corrected:
                corrected = True
                return {}
            return model(**kwargs)

        with tempfile.TemporaryDirectory() as folder:
            result = u.analyze_packet(packet, [], {}, call=initial, checkpoint_dir=folder)
            self.assertNotIn("pipeline_errors", result)
            self.assertTrue(corrected)
            again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Validated correction was lost"), checkpoint_dir=folder)
            self.assertEqual(result["interpretation"], again["interpretation"])

    def test_production_retry_resumes_original_inputs_despite_retained_questions(self):
        model, _, packet = pipeline_model()
        previous_inputs = []

        def blocked(packet, answers, previous, **kwargs):
            previous_inputs.append(deepcopy(previous))

            def provider(**request):
                if "source_coverage" in request["user_payload"]:
                    return None
                return model(**request)

            return u.analyze_packet(packet, answers, previous, call=provider, **kwargs)

        def resumed(packet, answers, previous, **kwargs):
            previous_inputs.append(deepcopy(previous))
            return u.analyze_packet(packet, answers, previous, call=model, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(gate, "analyze_understanding", side_effect=blocked):
                first = gate.checkpoint(Path(folder), packet)
            self.assertEqual(first["status"], "TECHNICAL_BLOCKED")
            self.assertTrue(first["questions"])
            with patch.object(gate, "analyze_understanding", side_effect=resumed) as run:
                second = gate.resume_checkpoint(Path(folder), packet)
            run.assert_called_once()
            self.assertEqual(previous_inputs, [{}, {}])
            self.assertEqual(second["status"], "NEEDS_CLARIFICATION")
            self.assertTrue(second["understanding_audit"]["claim_evidence"]["passed"])
            self.assertEqual(sum(s["execution"] == "checkpoint_revalidated" for s in second["understanding_audit"]["stages"]), 3)

    def test_actual_oversized_request_blocks_before_provider(self):
        _, _, packet = pipeline_model()
        with patch.object(u, "MAX_MODEL_INPUT_CHARS", 100):
            result = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Oversized request sent"))
        self.assertIn("No silent truncation", result["pipeline_errors"][0])

    def test_targeted_selection_correction_keeps_full_graph_and_is_resumable(self):
        model, _, packet = pipeline_model()
        good_selection = None
        corrections = []

        def provider(**kwargs):
            nonlocal good_selection
            payload = kwargs["user_payload"]
            if "repair_targets" in payload:
                corrections.append(payload)
                return {"repairs": {"T0": [good_selection]}}
            response = model(**kwargs)
            if payload.get('inventory_mode') == 'package':
                good_selection = deepcopy(response["requirements"][0]["focus"][0])
                response["requirements"][0]["focus"][0]["start"]["line"] = 999
            return response

        with tempfile.TemporaryDirectory() as folder:
            result = u.analyze_packet(packet, [], {}, call=provider, checkpoint_dir=folder)
            self.assertNotIn("pipeline_errors", result)
            self.assertEqual(len(corrections), 1)
            self.assertNotIn("previous_response", corrections[0])
            self.assertEqual(set(corrections[0]["spans"]), {k for k, v in u.build_spans(packet).items() if v['kind'] == 'package'})
            again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail("Do not repeat repaired inventory"), checkpoint_dir=folder)
            self.assertEqual(result["interpretation"], again["interpretation"])
            self.assertEqual(result["uncertainties"], again["uncertainties"])


if __name__ == "__main__":
    unittest.main()
