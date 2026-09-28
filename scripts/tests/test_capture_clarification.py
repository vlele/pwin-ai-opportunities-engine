"""Synthetic contract tests written before the clarification implementation.

Fixture model responses test validation and routing, not live semantic accuracy.
"""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_clarification as gate

CASES = json.loads((Path(__file__).parent / "fixtures/capture_clarification_cases.json").read_text())


def packet(case):
    return gate.build_packet(
        profile=case["profile"], resolved={"title": "Synthetic procurement"},
        attachment_bundle={"attachments_expected": True, "attachments": [
            {"filename": f"document-{i}.txt", "parser_status": "parsed_text", "structured_text_excerpt": text}
            for i, text in enumerate(case["documents"], 1)
        ]}, notice_text="",
    )


def response(case, value):
    citations = [{"source_id": sid, "quote": row["text"]} for sid, row in value["sources"].items() if row["kind"] == "package"]
    return {"interpretation": [{"text": case["interpretation"], "citations": citations}],
            "uncertainties": [{"kind": case["kind"], "blocking": True, "current_interpretation": case["interpretation"],
                "question": case["question"], "decision_impact": case["impact"], "options": case["options"], "citations": citations}],
            "resolved_question_ids": []}


def ready(value, resolved_ids=None):
    sid = next(s for s, v in value["sources"].items() if v["kind"] == "package")
    return {"interpretation": [{"text": "Read the stated scope without assuming vendor proof.", "citations": [{"source_id": sid, "quote": value["sources"][sid]["text"]}]}],
            "uncertainties": [], "resolved_question_ids": resolved_ids or []}


class ClarificationContractTests(unittest.TestCase):
    def test_ten_synthetic_ambiguities(self):
        self.assertEqual(len(CASES), 10)
        for case in CASES:
            with self.subTest(case=case["id"]):
                value = packet(case)
                result = gate.validate_assessment(response(case, value), value)
                self.assertEqual(result["status"], case["expected_status"])
                self.assertEqual(len(result["questions"]), 1)
                self.assertTrue(result["questions"][0]["decision_impact"])

    def test_invented_quote_is_technical_failure_not_user_question(self):
        value = packet(CASES[0])
        raw = response(CASES[0], value)
        raw["uncertainties"][0]["citations"][0]["quote"] = "Words not present in the package"
        result = gate.validate_assessment(raw, value)
        self.assertEqual(result["status"], "TECHNICAL_BLOCKED")
        self.assertEqual(result["questions"], [])

    def test_parser_and_model_problems_are_not_business_questions(self):
        value = packet(CASES[0])
        for kind in ("parser_failure", "model_contradiction", "api_unavailable"):
            raw = response(CASES[0], value)
            raw["uncertainties"][0]["kind"] = kind
            self.assertEqual(gate.validate_assessment(raw, value)["status"], "TECHNICAL_BLOCKED")

    def test_clear_and_explicitly_unrelated_cases_do_not_require_signoff(self):
        for text in ("RMA means return merchandise authorization. Implement returns processing.",
                     "Maintain industrial chillers; consumer portrait photography is not comparable work."):
            value = packet({"documents": [text], "profile": {"core_competencies": ["Portrait photography"]}})
            self.assertEqual(gate.validate_assessment(ready(value), value)["status"], "READY")

    def test_thin_parse_blocks_before_model(self):
        value = gate.build_packet(profile={}, resolved={}, attachment_bundle={"attachments_expected": True, "attachments": []}, notice_text="")
        model = Mock()
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=model)
        self.assertEqual(result["status"], "TECHNICAL_BLOCKED")
        model.assert_not_called()

    def test_checkpoint_is_durable_and_does_not_repeat_the_model_call(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            first = gate.checkpoint(Path(folder), value, analyze=model)
            again = gate.checkpoint(Path(folder), value, analyze=model)
            self.assertEqual(first["fingerprint"], again["fingerprint"])
            self.assertTrue(Path(first["review_path"]).exists())
            self.assertTrue(Path(first["answers_template_path"]).exists())
        self.assertEqual(model.call_count, 1)

    def test_unknown_answer_stays_unknown_and_is_not_asked_again(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=model)
            qid = result["questions"][0]["id"]
            answers = {"fingerprint": result["fingerprint"], "answers": [{"question_id": qid, "answer": "unknown"}]}
            resumed = gate.checkpoint(Path(folder), value, answers=answers, analyze=model)
            self.assertEqual(resumed["status"], "NEEDS_CLARIFICATION")
            self.assertEqual(resumed["questions_to_ask"], [])
            self.assertEqual(resumed["confirmed_answers"], [])
        self.assertEqual(model.call_count, 1)

    def test_answer_requires_reassessment_and_preserves_original_profile(self):
        case = copy.deepcopy(CASES[1])
        before = copy.deepcopy(case["profile"])
        value = packet(case)
        model = Mock(return_value=response(case, value))
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=model)
            qid = result["questions"][0]["id"]
            model.return_value = ready(value, [qid])
            answer = {"fingerprint": result["fingerprint"], "answers": [{"question_id": qid, "answer": "Infrastructure only; no records or retention work."}]}
            resumed = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(resumed["status"], "READY")
            self.assertEqual(resumed["confirmed_answers"][0]["provenance"], "user_reported_not_independently_verified")
            self.assertEqual(resumed["confirmed_answers"][0]["scope"], "current_capture")
            gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(case["profile"], before)

    def test_changed_package_or_profile_rejects_stale_answers(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=model)
            changed = copy.deepcopy(value)
            changed["sources"]["D1"]["text"] += " Scope changed."
            answer = {"fingerprint": result["fingerprint"], "answers": []}
            stale = gate.checkpoint(Path(folder), changed, answers=answer, analyze=model)
            self.assertEqual(stale["status"], "TECHNICAL_BLOCKED")
            self.assertIn("stale", " ".join(stale["technical_issues"]).lower())
        self.assertEqual(model.call_count, 1)

    def test_user_cannot_resolve_official_conflict_by_assertion(self):
        case = CASES[8]
        value = packet(case)
        model = Mock(return_value=response(case, value))
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=model)
            qid = result["questions"][0]["id"]
            model.return_value = ready(value, [qid])
            answer = {"fingerprint": result["fingerprint"], "answers": [{"question_id": qid, "answer": "Assume remote; we prefer that."}]}
            resumed = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(resumed["status"], "NEEDS_FORMAL_QA")
        self.assertEqual(model.call_count, 1)

    def test_no_api_response_is_not_silently_approved(self):
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), packet(CASES[1]), analyze=Mock(return_value=None))
        self.assertEqual(result["status"], "TECHNICAL_BLOCKED")
        self.assertFalse(result["questions"])

    def test_retry_cannot_override_unknown_or_official_conflict(self):
        for case, text in ((CASES[1], "unknown"), (CASES[8], "Use remote work anyway")):
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as folder:
                value = packet(case)
                model = Mock(return_value=response(case, value))
                initial = gate.checkpoint(Path(folder), value, analyze=model)
                answer = {"fingerprint": initial["fingerprint"], "answers": [{"question_id": initial["questions"][0]["id"], "answer": text}]}
                model.return_value = ready(value)
                result = gate.checkpoint(Path(folder), value, answers=answer, analyze=model, retry=True)
                self.assertEqual(result["status"], case["expected_status"])
                self.assertEqual(model.call_count, 1)

    def test_api_failure_after_answer_keeps_question_for_retry(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            initial = gate.checkpoint(Path(folder), value, analyze=model)
            qid = initial["questions"][0]["id"]
            answer = {"fingerprint": initial["fingerprint"], "answers": [{"question_id": qid, "answer": "Infrastructure only."}]}
            model.return_value = None
            failed = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(failed["status"], "TECHNICAL_BLOCKED")
            self.assertEqual(failed["questions"][0]["id"], qid)
            model.return_value = ready(value, [qid])
            result = gate.checkpoint(Path(folder), value, analyze=model, retry=True)
            self.assertEqual(result["status"], "READY")
            self.assertEqual(len(result["confirmed_answers"]), 1)

    def test_questions_are_batched_and_deduped(self):
        value = packet(CASES[1])
        raw = response(CASES[1], value)
        row = raw["uncertainties"][0]
        raw["uncertainties"] = [{**row, "question": f"Material question {i}?"} for i in range(5)] + [row, row]
        with tempfile.TemporaryDirectory() as folder:
            result = gate.checkpoint(Path(folder), value, analyze=Mock(return_value=raw))
        self.assertEqual(len(result["questions"]), 6)
        self.assertEqual(len(result["questions_to_ask"]), 3)

    def test_packet_reads_full_coarse_text_not_just_selected_scope_snippets(self):
        text = "Beginning of package. " + "Body content. " * 1500 + "Final glossary: RMA means returns processing."
        value = packet({"documents": [text], "profile": {}})
        joined = "".join(s["text"] for s in value["sources"].values() if s["kind"] == "package")
        self.assertEqual(joined, text)
        self.assertIn("Final glossary", joined)

    def test_context_overflow_does_not_silently_truncate(self):
        value = packet({"documents": ["x" * (gate.MAX_PACKET_CHARS + 1)], "profile": {}})
        self.assertTrue(value["technical_issues"])

    def test_byte_change_invalidates_cached_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            doc = root / "scope.txt"
            doc.write_text("Maintain pumps.")
            first = gate.local_input_fingerprint([str(doc)])
            model = Mock(return_value={"attachments": []})
            gate.local_attachment_cache(root, first, model)
            gate.local_attachment_cache(root, first, model)
            self.assertEqual(model.call_count, 1)
            doc.write_text("Maintain pumps and control panels.")
            second = gate.local_input_fingerprint([str(doc)])
            self.assertNotEqual(first, second)
            gate.local_attachment_cache(root, second, model)
            self.assertEqual(model.call_count, 2)

    def test_profile_change_also_invalidates_answers(self):
        original = packet(CASES[1])
        modified = copy.deepcopy(CASES[1])
        modified["profile"]["company_name"] = "Another fictional entity"
        with tempfile.TemporaryDirectory() as folder:
            model = Mock(return_value=response(CASES[1], original))
            initial = gate.checkpoint(Path(folder), original, analyze=model)
            stale = gate.checkpoint(Path(folder), packet(modified), answers={"fingerprint": initial["fingerprint"], "answers": []}, analyze=model)
            self.assertEqual(stale["status"], "TECHNICAL_BLOCKED")
            self.assertEqual(model.call_count, 1)

    def test_invalid_answer_file_does_not_replace_valid_checkpoint(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            initial = gate.checkpoint(Path(folder), value, analyze=model)
            invalid = gate.checkpoint(Path(folder), value, answers={"fingerprint": "wrong", "answers": []}, analyze=model)
            self.assertNotEqual(initial["state_path"], invalid["state_path"])
            self.assertEqual(json.loads(Path(initial["state_path"]).read_text())["status"], "NEEDS_CLARIFICATION")
            self.assertEqual(json.loads(Path(invalid["state_path"]).read_text())["status"], "TECHNICAL_BLOCKED")

    def test_dropping_question_without_resolution_cannot_approve_capture(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            first = gate.checkpoint(Path(folder), value, analyze=model)
            model.return_value = ready(value)
            answer = {"fingerprint": first["fingerprint"], "answers": [{"question_id": first["questions"][0]["id"], "answer": "Infrastructure only."}]}
            result = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(result["status"], "NEEDS_CLARIFICATION")

    def test_prompt_contract_and_answers_reach_actual_model_adapter(self):
        from common import openai_reasoning
        from common import capture_understanding as understanding
        value = packet(CASES[1])
        answers = [{"question_id": "Q-test", "answer": "Infrastructure only."}]
        from test_capture_understanding import supported_audit
        def response(**kwargs):
            payload = kwargs["user_payload"]
            if "signals" in kwargs["response_schema"]["schema"]["properties"]:
                return {"signals": []}
            if isinstance(payload.get("requirements"), dict):
                return {"requirements": {key: {"logic": "all", "components": [{"kind": "work", "text": "Migrate case records",
                       "evidence": row["evidence"]}]} for key, row in payload["requirements"].items()}}
            if "targets" in payload:
                return supported_audit(payload["targets"])
            if "component_job" in payload:
                job = payload["component_job"]
                return {**{k: job[k] for k in ("pair_id", "component_id", "component_kind")},
                        "status": "missing", "reason": "No records-task history established.", "supported_scope": "", "evidence": []}
            spans = payload["spans"]
            refs = list(spans)
            if "source_coverage" not in payload:
                return {"complete": True, "facts": [{"area": "scope", "statement": "Current supplied scope.", "refs": refs}],
                        "coverage": [{"source_id": sid, "finding": "Current material reviewed.",
                                      "refs": [key for key, span in spans.items() if span["source_id"] == sid]}
                                     for sid in dict.fromkeys(span["source_id"] for span in spans.values())]}
            return {"requirements": [{"area": "scope", "status": "current", "task": True,
                                      "record_kind": "requirement", "logic": "all", "supersedes": [],
                                      "focus": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}],
                                      "components": [{"kind": "work", "text": "Migrate case records", "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]}],
                                      "evidence": [{"ref": "D1:0", "quote": spans["D1:0"]["text"]}]}] if 'D1:0' in spans else [],
                    "claims": [{"form": "performed_task", "meaning": "Infrastructure only.", "attribution": "self",
                                "execution": "affirmative_actual", "unresolved_dimensions": [],
                                "evidence": [{"ref": "U1:0", "quote": "Infrastructure only."}]}] if 'U1:0' in spans else [],
                    "questions": [], "resolved_question_ids": ["Q-test"] if 'U1:0' in spans else [], "quoted_vendor_context": []}
        from tests.evidence_wire_fixture import selection_provider
        with patch.object(openai_reasoning, "_call_openai_json", side_effect=selection_provider(response)) as call:
            result = gate.analyze_understanding(value, answers, {"questions": [{"id": "Q-test"}]})
        self.assertNotIn("pipeline_errors", result)
        self.assertEqual(call.call_args_list[0].kwargs["user_payload"]["user_answers"], answers)
        vendor = next(c.kwargs['user_payload'] for c in call.call_args_list if c.kwargs['user_payload'].get('inventory_mode') == 'vendor')
        self.assertIn('Q-test', vendor['previous_question_ids'])
        self.assertIn('U1:0', vendor['spans'])
        requirement_audit = next(c.kwargs['user_payload'] for c in call.call_args_list
            if any(t['kind'] == 'requirement' for t in c.kwargs['user_payload'].get('targets', [])))
        self.assertNotIn("user_answers", requirement_audit)
        self.assertTrue(all(s["kind"] == "package" for s in requirement_audit["spans"].values()))
        self.assertIn("U1:0", call.call_args.kwargs["user_payload"]["spans"])
        self.assertTrue(result["understanding_audit"]["claim_evidence"]["passed"])
        self.assertTrue(call.call_args.kwargs["response_schema"]["strict"])

    def test_editing_confirmed_answer_reopens_and_reassesses_it(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            first = gate.checkpoint(Path(folder), value, analyze=model)
            qid = first["questions"][0]["id"]
            answer = {"fingerprint": first["fingerprint"], "answers": [{"question_id": qid, "answer": "Records migration."}]}
            model.return_value = ready(value, [qid])
            self.assertEqual(gate.checkpoint(Path(folder), value, answers=answer, analyze=model)["status"], "READY")
            answer["answers"][0]["answer"] = "Correction: infrastructure only."
            result = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(result["status"], "READY")
            self.assertEqual(model.call_count, 3)
            self.assertEqual(result["confirmed_answers"][0]["answer"], "Correction: infrastructure only.")

    def test_missing_answers_file_is_an_explicit_technical_error(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Mock()
            result = gate.checkpoint(Path(folder), packet(CASES[1]), answers={"invalid_answers_file": True}, analyze=model)
        self.assertEqual(result["status"], "TECHNICAL_BLOCKED")
        self.assertIn("file is missing", result["technical_issues"][0])
        model.assert_not_called()

    def test_withdrawing_a_confirmed_answer_revokes_ready_status(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            first = gate.checkpoint(Path(folder), value, analyze=model)
            qid = first["questions"][0]["id"]
            answer = {"fingerprint": first["fingerprint"], "answers": [{"question_id": qid, "answer": "Records migration."}]}
            model.return_value = ready(value, [qid])
            gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            answer["answers"][0]["answer"] = "unknown"
            result = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
            self.assertEqual(result["confirmed_answers"], [])
            self.assertEqual(model.call_count, 2)

    def test_research_focus_excludes_private_profile_and_answers(self):
        context = {"sources": {"D1": {"kind": "package"}, "V1": {"kind": "profile"}},
                   "interpretation": [{"text": "Model interpretation with private information.", "citations": [
                       {"source_id": "D1", "quote": "Maintain pumps at three sites."},
                       {"source_id": "V1", "quote": "Private internal customer reference."}]}],
                   "answers": [{"answer": "Private internal project detail."}]}
        self.assertEqual(gate.reviewed_package_quotes(context), "Maintain pumps at three sites.")

    def test_explicit_unknown_status_does_not_depend_on_natural_language_wording(self):
        value = packet(CASES[1])
        model = Mock(return_value=response(CASES[1], value))
        with tempfile.TemporaryDirectory() as folder:
            first = gate.checkpoint(Path(folder), value, analyze=model)
            answer = {"fingerprint": first["fingerprint"], "answers": [{"question_id": first["questions"][0]["id"],
                      "answer_status": "unknown", "answer": "We have not located the project records."}]}
            result = gate.checkpoint(Path(folder), value, answers=answer, analyze=model)
            self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
            self.assertEqual(result["questions_to_ask"], [])
            self.assertEqual(model.call_count, 1)

    def test_confirmed_answer_attaches_only_to_the_referenced_project(self):
        from common.capture_fit import build_fit_catalog
        profile = {"past_performance_highlights": ["Enterprise migration", "Pump maintenance"]}
        context = {"sources": {"V1": {"profile_field": "past_performance_highlights[0]"}}, "answers": [
            {"question_id": "Q-example", "kind": "vendor_experience", "answer": "Infrastructure only, not records.", "citations": [{"source_id": "V1"}]}]}
        catalog = build_fit_catalog(profile, [], clarification_context=context)
        self.assertIn("Infrastructure only", catalog["vendor_evidence"]["PP1"]["text"])
        self.assertNotIn("clarifications", catalog["vendor_evidence"]["PP2"])
        self.assertEqual(profile["past_performance_highlights"][0], "Enterprise migration")


class OrchestratorContractTests(unittest.TestCase):
    def run_main(self, case, *, approved=False, preflight=False, repeat=False):
        from capture import run_capture_research as capture
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "procurement").mkdir()
            (root / "procurement/vendor-profile.json").write_text(json.dumps(case["profile"]))
            doc = root / "package.txt"
            doc.write_text(case["documents"][0])
            bundle = {"status": "ok", "attachments_expected": True, "attachments": [
                {"filename": doc.name, "parser_status": "parsed_text", "structured_text_excerpt": case["documents"][0]}]}
            argv = ["capture", "--workspace", folder, "--file", str(doc), "--title", "Synthetic scope", "--url", "https://example.invalid/notice"]
            if preflight:
                argv.append("--preflight-only")
            def model(value, answers, previous, **kwargs):
                return ready(value) if approved else response(case, value)
            with patch.object(sys, "argv", argv), patch.object(capture, "load_local_attachments", return_value=bundle) as parser, \
                 patch.object(gate, "analyze_understanding", side_effect=model), \
                 patch.object(capture, "fetch_url_excerpt", return_value={"status": "empty"}) as notice, \
                 patch.object(capture, "fetch_public_research", return_value={"status": "empty"}) as public, \
                 patch.object(capture, "enrich_from_usaspending", return_value={}) as spending, \
                 patch.object(capture, "enrich_capture_context", return_value={}) as commercial, \
                 patch.object(capture, "assess_capture_strategy", return_value={}) as strategy:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = capture.main()
                    if repeat:
                        capture.main()
                result = json.loads(output.getvalue().splitlines()[-1])
                if not approved or preflight:
                    for mocked in (notice, public, spending, commercial, strategy):
                        mocked.assert_not_called()
                    self.assertFalse(list(root.glob("procurement/capture-briefs/**/*.md")))
                else:
                    public.assert_called_once()
                    spending.assert_called_once()
                    commercial.assert_called_once()
                    strategy.assert_called_once()
                    self.assertIn("fingerprint", strategy.call_args.kwargs["clarification_context"])
                    self.assertTrue(Path(result["brief_path"]).exists())
                self.assertEqual(parser.call_count, 1)
                return code, result

    def test_pending_stops_all_research_and_reuses_parsed_inputs(self):
        code, result = self.run_main(CASES[1], repeat=True)
        self.assertEqual(code, 20)
        self.assertEqual(result["status"], "NEEDS_CLARIFICATION")

    def test_ready_preflight_still_does_not_research(self):
        code, result = self.run_main(CASES[1], approved=True, preflight=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "READY")

    def test_ready_reaches_normal_capture_rendering(self):
        code, result = self.run_main(CASES[1], approved=True)
        self.assertEqual(code, 10)
        self.assertEqual(result["status"], "PARTIAL_CAPTURE_RESEARCH")

    def test_tracked_capture_can_fetch_primary_package_but_cannot_enrich_before_gate(self):
        from capture import run_capture_research as capture
        case = CASES[1]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "procurement").mkdir()
            (root / "procurement/vendor-profile.json").write_text(json.dumps(case["profile"]))
            bundle = {"status": "ok", "attachments_expected": True, "attachments": [
                {"filename": "PWS.txt", "parser_status": "parsed_text", "structured_text_excerpt": case["documents"][0]}]}
            resolved = {"status": "resolved", "report_entry_id": "A1", "canonical_record_id": "synthetic", "title": "Synthetic scope", "url": "https://example.invalid/notice"}
            with patch.object(sys, "argv", ["capture", "--workspace", folder, "--entry", "A1"]), \
                 patch.object(capture, "resolve_entry", return_value=resolved), \
                 patch.object(capture, "load_notice_context", return_value={"opportunity_record": {}, "explanation_record": {}}), \
                 patch.object(capture, "fetch_notice_attachments", return_value=bundle) as attachments, \
                 patch.object(capture, "fetch_url_excerpt", return_value={"status": "empty"}) as notice, \
                 patch.object(gate, "analyze_understanding", side_effect=lambda value, answers, previous, **kwargs: response(case, value)), \
                 patch.object(capture, "fetch_public_research") as public, \
                 patch.object(capture, "enrich_from_usaspending") as spending, \
                 patch.object(capture, "enrich_capture_context") as commercial, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(capture.main(), 20)
                attachments.assert_called_once()
                notice.assert_called_once()
                for mock in (public, spending, commercial):
                    mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
