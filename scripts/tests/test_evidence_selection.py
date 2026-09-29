"""Evidence transport must recover text, not repair an LLM's invented quotation."""
import copy
import unittest

from common.evidence_selection import EvidenceTransport, source_locations
from common.semantic_plan import _anchors, validate_audit


def schema():
    return {"type": "object", "properties": {"evidence": {"type": "array", "items": {
        "type": "object", "properties": {"ref": {"type": "string", "enum": ["D1:0", "D2:0"]},
        "quote": {"type": "string"}}, "required": ["ref", "quote"], "additionalProperties": False}}},
        "required": ["evidence"], "additionalProperties": False}


def spans():
    left = "[Page 1]\nThe period is 12 months from date of award.\nCreate a Test "
    right = "Analysis Summary.\nDo not waive the licensed-staff requirement.\n[Page 2]\nOther work."
    regions = [{"start": 0, "end": len(left) + right.index("[Page 2]"), "page_number": 1, "basis": "native_text"},
               {"start": len(left) + right.index("[Page 2]"), "end": len(left + right), "page_number": 2, "basis": "native_text"}]
    return {"D1:0": {"text": left, "kind": "package", "source_id": "D1", "document_id": "doc-a",
                      "filename": "scope.pdf", "source_offset": 0, "offset": 0, "text_regions": regions},
            "D2:0": {"text": right, "kind": "package", "source_id": "D2", "document_id": "doc-a",
                      "filename": "scope.pdf", "source_offset": len(left), "offset": 0, "text_regions": regions}}


def selection(start="D1:0", line=2, end=None, last=None):
    return {"start": {"ref": start, "line": line},
            "end": {"ref": end or start, "line": line if last is None else last}}


class EvidenceSelectionTests(unittest.TestCase):
    def transport(self, registry=None, spec=None):
        return EvidenceTransport(spec or schema(), {"spans": registry or spans()})

    def test_model_selects_lines_not_quotes(self):
        t = self.transport()
        self.assertNotIn("quote", t.schema["properties"]["evidence"]["items"]["properties"])
        self.assertIn("L2| The period is 12 months", t.payload["spans"]["D1:0"]["text"])
        result = t.resolve({"evidence": [selection()]})
        self.assertEqual(result["evidence"], [{"ref": "D1:0", "quote": "The period is 12 months from date of award.\n"}])
        _anchors(result["evidence"], spans(), package=True)

    def test_adjacent_fragments_across_source_chunks(self):
        t = self.transport()
        result = t.resolve({"evidence": [selection(line=3, end="D2:0", last=1)]})
        self.assertEqual("".join(a["quote"] for a in result["evidence"]), "Create a Test Analysis Summary.\n")
        self.assertEqual(len(t.receipts[0]["locations"]), 2)
        self.assertEqual(t.receipts[0]["locations"][1]["document_char_start"], len(spans()["D1:0"]["text"]))
        self.assertTrue(all(x["page_number"] == 1 for x in t.receipts[0]["locations"]))

    def test_page_boundary_retained(self):
        t = self.transport()
        t.resolve({"evidence": [selection("D2:0", 2, last=4)]})
        self.assertEqual({x["page_number"] for x in t.receipts[0]["locations"]}, {1, 2})

    def test_whitespace_is_retrieved_without_normalizing_source(self):
        s = spans()
        s["D1:0"]["text"] = "Term:\t12 months\r\nfrom date of award."
        t = self.transport(s)
        quote = t.resolve({"evidence": [selection(line=1, last=2)]})["evidence"][0]["quote"]
        self.assertEqual(quote, s["D1:0"]["text"])

    def test_number_negation_qualification_or_extra_quote_cannot_be_rewritten(self):
        for changed in ("2 months", "Do waive", "unlicensed staff", "unrelated activity"):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.transport().resolve({"evidence": [{**selection(), "quote": changed}]})

    def test_legacy_model_generated_quotation_is_not_accepted(self):
        with self.assertRaises(ValueError):
            self.transport().resolve({"evidence": [{"ref": "D1:0", "quote": "The period is 12 months"}]})

    def test_bad_bounds_ids_and_reverse_ranges_fail(self):
        for sel in (selection(line=0), selection(line=100), selection(line=True), selection("bogus"),
                    selection(line=3, last=1), selection("D2:0", 1, "D1:0", 3)):
            with self.subTest(sel=sel), self.assertRaises(ValueError):
                self.transport().resolve({"evidence": [sel]})

    def test_gaps_overlaps_cross_document_and_cross_role_fail(self):
        for key, value in (("document_id", "other-doc"), ("source_offset", 999), ("source_offset", 0),
                           ("kind", "profile")):
            s = spans()
            s["D2:0"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.transport(s).resolve({"evidence": [selection(line=3, end="D2:0", last=1)]})

    def test_absent_document_identity_does_not_guess_by_filename(self):
        s = spans()
        for row in s.values():
            row.pop("document_id")
        with self.assertRaises(ValueError):
            self.transport(s).resolve({"evidence": [selection(line=3, end="D2:0", last=1)]})

    def test_repeated_text_preserves_selected_location(self):
        s = spans()
        s["D1:0"]["text"] = "Same text.\nSame text.\n"
        t = self.transport(s)
        t.resolve({"evidence": [selection(line=2)]})
        self.assertEqual(t.receipts[0]["locations"][0]["document_char_start"], 11)

    def test_source_and_payload_not_mutated(self):
        s = spans()
        before = copy.deepcopy(s)
        self.transport(s).resolve({"evidence": [selection()]})
        self.assertEqual(before, s)

    def test_component_selection_is_only_from_declared_claim_anchors(self):
        s = schema()
        allowed = {"ref": "D1:0", "quote": "The period is 12 months"}
        s["properties"]["evidence"]["items"] = {"anyOf": [{"type": "object", "properties": {
            "ref": {"type": "string", "enum": [allowed["ref"]]},
            "quote": {"type": "string", "enum": [allowed["quote"]]}}}]}
        t = self.transport(spec=s)
        self.assertEqual(t.resolve({"evidence": [{"evidence_id": "E0"}]})["evidence"], [allowed])
        with self.assertRaises(ValueError):
            t.resolve({"evidence": [selection("D2:0", 2)]})
        with self.assertRaises(ValueError):
            t.resolve({"evidence": [{"evidence_id": "E1"}]})

    def test_valid_source_location_does_not_override_negative_semantic_audit(self):
        t = self.transport()
        t.resolve({"evidence": [selection()]})
        for reason in ("Changed 12 months to 2", "Dropped negation", "Dropped qualification", "Unrelated cited work"):
            verdict = validate_audit({"checks": {"R0": {"verdict": "unsupported", "reason": reason}}},
                                     [{"id": "R0", "kind": "requirement"}])
            self.assertFalse(verdict["passed"])

    def test_document_and_page_offsets_are_explicit(self):
        s = spans()
        loc = source_locations(s["D2:0"], 0, 17)[0]
        self.assertEqual(loc["document_id"], "doc-a")
        self.assertEqual(loc["filename"], "scope.pdf")
        self.assertEqual(loc["page_number"], 1)
        self.assertEqual(loc["page_char_start"], len(s["D1:0"]["text"]))
        self.assertEqual(loc["coordinate_system"], "extracted_text_unicode_codepoints")

    def test_provider_schema_rejects_source_id_in_place_of_span_id(self):
        import jsonschema
        t = self.transport()
        jsonschema.validate({"evidence": [selection()]}, t.schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"evidence": [selection("D1")]}, t.schema)
        choices = t.schema["$defs"]["evidence_endpoint"]["anyOf"]
        self.assertEqual({ref for c in choices for ref in c["properties"]["ref"]["enum"]},
                         {"D1:0", "D2:0"})

    def test_provider_schema_binds_each_endpoint_to_its_fragment_bounds(self):
        import jsonschema
        t = self.transport()
        jsonschema.validate({"evidence": [selection("D2:0", 4)]}, t.schema)
        # Line 4 exists in the second fragment, not the first. A global max
        # would pass this invalid citation, as did the old unbounded integers.
        for value in (selection(line=4), selection(last=4), selection(line=0),
                      selection(last=0), selection(line=True), selection(line=1.5)):
            with self.subTest(value=value), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({"evidence": [value]}, t.schema)

    def test_empty_fragment_cannot_be_selected(self):
        import jsonschema
        s = spans()
        s["D1:0"]["text"] = ""
        t = self.transport(s)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"evidence": [selection(line=1)]}, t.schema)
        for span in s.values():
            span["text"] = ""
        with self.assertRaisesRegex(ValueError, "No selectable"):
            self.transport(s)

    def test_equal_bounds_share_definition_without_losing_references(self):
        s = spans()
        s["D2:0"]["text"] = s["D1:0"]["text"]
        choices = self.transport(s).schema["$defs"]["evidence_endpoint"]["anyOf"]
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0]["properties"]["line"]["maximum"], 3)
        self.assertEqual(choices[0]["properties"]["ref"]["enum"], ["D1:0", "D2:0"])

    def test_repair_uses_the_same_bounded_endpoint_schema(self):
        import jsonschema
        t = self.transport()
        repair = t.selection_repair({"evidence": [selection(line=999)]})
        jsonschema.validate({"repairs": {"T0": [selection()]}}, repair.schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"repairs": {"T0": [selection(last=4)]}}, repair.schema)

    def test_old_unbounded_wire_is_not_silently_reinterpreted(self):
        with self.assertRaises(ValueError):
            self.transport().resolve({"evidence": [{"start_ref": "D1:0", "start_line": 1,
                                                    "end_ref": "D1:0", "end_line": 2}]})

    def test_a_second_sentence_is_selectable_without_including_the_first(self):
        s = spans()
        s["D1:0"]["text"] = "Our staff install displays. Our staff repair radios."
        t = self.transport(s)
        self.assertEqual(t.resolve({"evidence": [selection(line=2)]})["evidence"][0]["quote"],
                         "Our staff repair radios.")

    def test_excessively_broad_source_range_is_rejected(self):
        s = spans()
        s["D1:0"]["text"] = "a" * 8001
        with self.assertRaises(ValueError):
            self.transport(s).resolve({"evidence": [selection(line=1)]})

    def test_requirement_text_does_not_split_a_number_at_a_fragment_boundary(self):
        from common.evidence_selection import evidence_text
        s = spans()
        s["D1:0"]["text"] = "Provide service for 1"
        s["D2:0"]["text"] = "2 months."
        s["D2:0"]["source_offset"] = len(s["D1:0"]["text"])
        anchors = [{"ref": ref, "quote": value["text"]} for ref, value in s.items()]
        self.assertEqual(evidence_text(anchors, s), "Provide service for 12 months.")
        s["D2:0"]["document_id"] = "another-document"
        self.assertEqual(evidence_text(anchors, s), "Provide service for 1 2 months.")

    def test_targeted_correction_preserves_good_selections_and_source(self):
        t = self.transport()
        raw = {"evidence": [selection(), selection(line=900), selection("D2:0", 2)]}
        original = copy.deepcopy(raw)
        repair = t.selection_repair(raw)
        self.assertEqual(len(repair.targets), 1)
        self.assertEqual(repair.payload["spans"], t.payload["spans"])
        merged = repair.merge({"repairs": {"T0": [selection(line=3, end="D2:0", last=1)]}})
        self.assertEqual(merged["evidence"][0], raw["evidence"][0])
        self.assertEqual(merged["evidence"][2], raw["evidence"][2])
        self.assertEqual(raw, original)
        self.assertIn("Test Analysis", "".join(a["quote"] for a in t.resolve(merged)["evidence"]))

    def test_repairs_cannot_erase_evidence_or_rewrite_other_fields(self):
        t = self.transport()
        repair = t.selection_repair({"evidence": [selection(line=900)]})
        for response in ({"repairs": {}}, {"repairs": {"T0": []}},
                         {"repairs": {"T0": [selection()], "T1": [selection()]}},
                         {"repairs": {"T0": [selection()]}, "meaning": "New unsupported fact"}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                repair.merge(response)
        with self.assertRaises(ValueError):
            t.resolve(repair.merge({"repairs": {"T0": [selection("unknown")]}}))

    def test_multiple_repairs_preserve_indices_when_a_range_is_split(self):
        t = self.transport()
        raw = {"evidence": [selection(line=999)] + [selection()] * 10 + [selection(line=998)]}
        repair = t.selection_repair(raw)
        result = repair.merge({"repairs": {"T0": [selection(), selection("D2:0", 2)],
                                            "T1": [selection(line=3, end="D2:0", last=1)]}})
        self.assertEqual(result["evidence"][2:12], raw["evidence"][1:11])
        self.assertEqual(len(t.resolve(result)["evidence"]), 14)

    def test_valid_evidence_never_generates_a_repair(self):
        self.assertIsNone(self.transport().selection_repair({"evidence": [selection()]}))


if __name__ == "__main__":
    unittest.main()
