"""Contract tests first; synthetic evidence, not live model accuracy claims."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as understanding


def packet():
    return {"sources": {
        "D1": {"kind": "package", "text": "Maintain industrial refrigeration equipment. Acceptance requires temperature logs.", "filename": "scope.txt"},
        "D2": {"kind": "package", "text": "Delivery is due ten business days after approval.", "filename": "schedule.txt"},
        "V1": {"kind": "profile", "text": "Only consumer event photography; no equipment maintenance.", "profile_field": "core_competencies[0]"},
    }, "technical_issues": []}


def assessment(spans):
    refs = list(spans)
    return {"interpretation": [{"text": "The supplied company does unrelated work.", "refs": [refs[0], refs[-1]]}],
            "uncertainties": [issue(spans, "clear", relevance="unrelated")], "resolved_question_ids": [],
            "coverage": [{"area": area, "finding": "Reviewed supplied material.", "refs": [refs[0]]} for area in understanding.AREAS]}


def issue(spans, ambiguity="ambiguous", owner="user", relevance="unknown", verification="unverified"):
    basis = "official_conflict" if owner == "official" and ambiguity == "conflicting" else "meaning" if ambiguity in {"ambiguous", "conflicting"} else "additional_detail" if ambiguity == "missing" else "settled"
    clarification = {"basis": basis, "unresolved": "The actual performed role is unspecified." if basis != "settled" else "",
                     "refs": [key for key, span in spans.items() if owner != "official" or span["kind"] == "package"] if basis != "settled" else [],
                     "alternatives": [{"answer": "Own staff performed the work", "decision_effect": "Assess that reported work for overlap."},
                                      {"answer": "Another performer did the work", "decision_effect": "Do not attribute that work to this vendor."}] if basis in understanding.QUESTION_BASES else []}
    return {"claim": {"subject": "performed_work", "statement": "" if verification == "unknown" else "The vendor reports consumer photography.",
                      "basis": {"unknown": "not_supplied", "source_supported": "package_fact", "unverified": "reported"}[verification],
                      "refs": [] if verification == "unknown" else ["D1:0"] if verification == "source_supported" else ["V1:0"]},
            "comparison": {"required_statement": "Maintain industrial refrigeration equipment.", "refs": ["D1:0"],
                           "rationale": "Actual performed tasks must be compared with the required work."},
            "task_alignment": task_alignment(relevance),
            "clarification": clarification,
            "kind": "vendor_experience", "relevance": relevance,
            "ambiguity": ambiguity, "verification_status": verification, "owner": owner,
            "current_interpretation": "The actual performing role is unclear.",
            "question": "Which tasks did this entity perform?", "decision_impact": "Changes attribution of experience.",
            "affected_decisions": ["past_performance"], "options": ["Provide the actual workshare", "Unknown"],
            "refs": list(spans), "verification_refs": [], "action": "ask"}


def task_alignment(relevance):
    """Explicit fixture labels; these helpers never classify production evidence."""
    return {"relationship": {"direct": "same_task", "transferable": "applicable_different_task"}.get(relevance, relevance),
            "coverage": {"direct": "partial", "transferable": "partial", "unrelated": "none",
                         "unknown": "unknown", "not_applicable": "not_applicable"}[relevance],
            "shared_work": "A concrete task overlap supplied by this contract test." if relevance in {"direct", "transferable"} else "",
            "transfer_basis": "An explicitly applicable different procedure." if relevance == "transferable" else ""}


def supported_audit(components):
    from common.semantic_plan import audit_verdict_key
    return {"checks": {c["id"]: {audit_verdict_key(c): "supported", "reason": "Qualified component supported by the fixture."}
                       for c in components}}


class UnderstandingTests(unittest.TestCase):
    def test_span_registry_preserves_text_and_profile_field_meaning(self):
        value = packet()
        value["sources"]["D1"]["text"] *= 500
        spans = understanding.build_spans(value)
        for sid, source in value["sources"].items():
            self.assertEqual("".join(s["text"] for s in spans.values() if s["source_id"] == sid), source["text"])
        self.assertEqual(next(s for s in spans.values() if s["source_id"] == "V1")["profile_field"], "core_competencies[0]")

    def test_quotes_are_retrieved_not_generated(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        result = understanding.render_assessment(raw, spans)
        for citation in result["interpretation"][0]["citations"]:
            self.assertIn(citation["quote"], packet()["sources"][citation["source_id"]]["text"])

    def test_unknown_source_is_rejected_not_fuzzily_repaired(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["interpretation"][0]["refs"] = ["invented"]
        with self.assertRaises(ValueError):
            understanding.render_assessment(raw, spans)

    def test_clear_claims_do_not_become_rescue_or_verification_questions(self):
        spans = understanding.build_spans(packet())
        for relevance in ("direct", "transferable", "unrelated"):
            raw = assessment(spans)
            raw["uncertainties"] = [issue(spans, "clear", relevance=relevance)]
            result = understanding.render_assessment(raw, spans)
            self.assertFalse(any(q["blocking"] for q in result["uncertainties"]))
            self.assertEqual(result["understanding_audit"]["suppressed_questions"][0]["relevance"], relevance)
            self.assertEqual(result["uncertainties"][0]["question"], "")
            self.assertEqual(result["uncertainties"][0]["action"], "record_gap")

    def test_ambiguous_material_claim_asks_specific_question(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["uncertainties"] = [issue(spans)]
        self.assertTrue(understanding.render_assessment(raw, spans)["uncertainties"][0]["blocking"])

    def test_a_qualified_finding_does_not_need_a_question_or_answer_choices(self):
        from common import capture_clarification as gate
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        finding = issue(spans, "clear", relevance="unrelated")
        finding.update(action="record_gap", question="", options=[])
        raw["uncertainties"] = [finding]
        rendered = understanding.render_assessment(raw, spans)
        result = gate.validate_assessment(rendered, packet())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["open_gaps"]), 1)
        self.assertFalse(result["questions"])
        self.assertEqual(result["open_gaps"][0]["relevance"], "unrelated")
        self.assertEqual(result["open_gaps"][0]["ambiguity"], "clear")
        self.assertEqual(result["open_gaps"][0]["verification_status"], "unverified")

    def test_verification_never_silences_material_ambiguity(self):
        spans = understanding.build_spans(packet())
        for verification in ("unverified", "source_supported", "unknown"):
            raw = assessment(spans)
            row = issue(spans, verification=verification)
            row.update(action="record_gap", verification_refs=["D1:0"] if verification == "source_supported" else [])
            raw["uncertainties"] = [row]
            result = understanding.render_assessment(raw, spans)["uncertainties"][0]
            self.assertTrue(result["blocking"])
            self.assertEqual(result["action"], "ask")

    def test_unknown_is_not_unrelated_and_can_remain_a_qualified_gap(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        row = issue(spans, "missing", verification="unknown")
        row.update(action="record_gap", question="", options=[])
        raw["uncertainties"] = [row]
        result = understanding.render_assessment(raw, spans)["uncertainties"][0]
        self.assertFalse(result["blocking"])
        self.assertEqual(result["relevance"], "unknown")

    def test_irrelevant_does_not_silence_a_material_interpretation_conflict(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["uncertainties"] = [issue(spans, relevance="unrelated")]
        self.assertTrue(understanding.render_assessment(raw, spans)["uncertainties"][0]["blocking"])

    def test_nonmaterial_ambiguity_does_not_create_question(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        row = issue(spans)
        row["affected_decisions"] = []
        raw["uncertainties"] = [row]
        self.assertFalse(understanding.render_assessment(raw, spans)["uncertainties"][0]["blocking"])

    def test_profile_alone_cannot_count_as_verification(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        row = issue(spans, "clear", relevance="direct", verification="source_supported")
        row["verification_refs"] = ["V1:0"]
        raw["uncertainties"] = [row]
        with self.assertRaisesRegex(ValueError, "verification_refs"):
            understanding.render_assessment(raw, spans)

    def test_missing_axis_is_not_silently_inferred_from_old_fact_state(self):
        spans = understanding.build_spans(packet())
        for key in ("relevance", "ambiguity", "verification_status"):
            raw = assessment(spans)
            row = issue(spans)
            del row[key]
            row["fact_state"] = "unverified"
            raw["uncertainties"] = [row]
            with self.assertRaisesRegex(ValueError, key):
                understanding.render_assessment(raw, spans)

    def test_config_defaults_to_high_and_preserves_explicit_override(self):
        with patch.dict("os.environ", {}, clear=True):
            config = understanding.model_settings()
            self.assertEqual(config["reasoning_effort"], "high")
        with patch.dict("os.environ", {"PWIN_UNDERSTANDING_MODEL": "test-model", "PWIN_UNDERSTANDING_REASONING_EFFORT": "medium"}):
            config = understanding.model_settings()
            self.assertEqual(config, {"model": "test-model", "reasoning_effort": "medium"})

    def test_strict_schema_limits_references_before_generation(self):
        spans = understanding.build_spans(packet())
        schema = understanding.source_schema(understanding.ASSESSMENT_SCHEMA, spans)
        self.assertEqual(schema["$defs"]["SpanRef"]["enum"], list(spans))
        self.assertNotIn("V1:0", schema["$defs"]["PackageRef"]["enum"])
        refs = schema["properties"]["interpretation"]["items"]["properties"]["refs"]
        self.assertEqual(refs["minItems"], 1)
        self.assertEqual(refs["items"], {"$ref": "#/$defs/SpanRef"})
        coverage = schema["properties"]["coverage"]["items"]["properties"]["refs"]
        self.assertEqual(coverage["minItems"], 0)
        branches = schema["properties"]["uncertainties"]["items"]["anyOf"]
        for branch in branches:
            props = branch["properties"]
            if props["verification_status"]["enum"] == ["source_supported"]:
                self.assertEqual(props["verification_refs"]["minItems"], 1)
                self.assertEqual(props["verification_refs"]["items"], {"$ref": "#/$defs/PackageRef"})
            else:
                self.assertEqual(props["verification_refs"]["maxItems"], 0)
        self.assertNotIn("$defs", understanding.ASSESSMENT_SCHEMA)

    def test_checkpoint_cache_is_model_and_effort_scoped_and_axes_visible(self):
        from common import capture_clarification as gate
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["uncertainties"] = [issue(spans, "clear", relevance="unrelated")]
        calls = []
        def analyze(*args):
            calls.append(args)
            return understanding.render_assessment(raw, spans)
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict("os.environ", {"PWIN_UNDERSTANDING_MODEL": "test-model", "PWIN_UNDERSTANDING_REASONING_EFFORT": "none"}):
                first = gate.checkpoint(Path(folder), packet(), analyze=analyze)
                cached = gate.checkpoint(Path(folder), packet(), analyze=analyze)
                self.assertEqual(len(calls), 1)
                self.assertEqual(first["fingerprint"], cached["fingerprint"])
            with patch.dict("os.environ", {"PWIN_UNDERSTANDING_MODEL": "test-model", "PWIN_UNDERSTANDING_REASONING_EFFORT": "medium"}):
                second = gate.checkpoint(Path(folder), packet(), analyze=analyze)
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(first["fingerprint"], second["fingerprint"])
            review = Path(second["review_path"]).read_text()
            for label in ("Relevance: unrelated", "Ambiguity: clear", "Verification: unverified"):
                self.assertIn(label, review)

    def test_effort_reaches_transport_only_when_explicitly_supplied(self):
        from common import openai_reasoning as reasoning
        client = MagicMock()
        create = client.with_options.return_value.chat.completions.create
        create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
        with patch.object(reasoning, "_openai_client", return_value=client):
            for effort in (None, "medium"):
                result = reasoning._call_openai_json(system_prompt="test", user_payload={}, model="test-model",
                                                      timeout_seconds=120, reasoning_effort=effort)
                self.assertTrue(result["ok"])
                if effort is None:
                    self.assertNotIn("reasoning_effort", create.call_args.kwargs)
                else:
                    self.assertEqual(create.call_args.kwargs["reasoning_effort"], "medium")

    def test_official_conflict_cannot_be_downgraded_to_open_gap(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        question = issue(spans, "conflicting", "official")
        question.update(kind="document_conflict", action="record_gap", refs=[key for key, span in spans.items() if span["kind"] == "package"])
        question.update(verification_status="source_supported", verification_refs=["D1:0"])
        question["claim"].update(subject="official_conflict", basis="package_fact", refs=["D1:0"])
        question["task_alignment"] = task_alignment("not_applicable")
        raw["uncertainties"] = [question, issue(spans, "clear", relevance="unrelated")]
        rendered = understanding.render_assessment(raw, spans)["uncertainties"][0]
        self.assertTrue(rendered["blocking"])
        self.assertEqual(rendered["kind"], "document_conflict")

    def test_profile_claim_is_not_an_official_document_conflict(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["uncertainties"] = [issue(spans, "conflicting", "official")]
        with self.assertRaises(ValueError):
            understanding.render_assessment(raw, spans)

    def test_missing_material_area_cannot_be_ready(self):
        spans = understanding.build_spans(packet())
        raw = assessment(spans)
        raw["coverage"].pop()
        with self.assertRaises(ValueError):
            understanding.render_assessment(raw, spans)

    def test_failed_chunk_prevents_final_assessment(self):
        calls = []
        def unavailable(**kwargs):
            calls.append(kwargs)
            return None
        result = understanding.analyze_packet(packet(), [], {}, call=unavailable)
        self.assertTrue(result["pipeline_errors"])
        self.assertEqual(len(calls), 1)

    def test_invalid_extraction_has_only_one_correction_attempt(self):
        calls = []
        def malformed(**kwargs):
            calls.append(kwargs)
            return {"facts": [], "coverage": []}
        result = understanding.analyze_packet(packet(), [], {}, call=malformed)
        self.assertTrue(result["pipeline_errors"])
        self.assertEqual(len(calls), 2)

    def test_profile_preferences_remain_labeled_not_a_proposed_team(self):
        value = packet()
        value["sources"]["V2"] = {"kind": "profile", "text": "subcontractor", "profile_field": "commercial_constraints.prime_or_sub[1]"}
        spans = understanding.build_spans(value)
        self.assertTrue(any(s.get("profile_field") == "commercial_constraints.prime_or_sub[1]" for s in spans.values()))


if __name__ == "__main__":
    unittest.main()
