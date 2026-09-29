"""Sparse-page exceptions need layout evidence, never customer-specific rules."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture import fetch_notice_attachments as attachments
from common.capture_clarification import build_packet


@unittest.skipIf(attachments.fitz is None, "PyMuPDF required for PDF fixtures")
class PDFPageCoverageTests(unittest.TestCase):
    def pdf(self, decorate=None, header="SYNTHETIC-PACKAGE", count=3):
        with attachments.fitz.open() as doc:
            for index in range(count):
                page = doc.new_page(width=612, height=792)
                if header:
                    page.insert_text((40, 35), header)
                    page.insert_text((40, 765), f"Page {index + 1} of {count}")
                if index != count - 2:
                    page.insert_text((40, 200), "\n".join([
                        "The contractor shall inspect equipment and record all findings.",
                        "Test results shall identify the instrument and calibration date.",
                        "Provide monthly reports listing completed and outstanding tasks.",
                        "Retain source records and submit findings for customer review.",
                    ]))
                elif decorate:
                    decorate(page)
            return doc.tobytes()

    def coverage(self, data):
        return attachments._understanding_input(data, "synthetic.pdf", "", [])

    def test_repeated_header_and_footer_are_covered_and_retained(self):
        text, meta = self.coverage(self.pdf())
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["unreadable_pages"], [])
        row = meta["page_coverage"][1]
        self.assertEqual(row["status"], "verified_header_footer_only")
        self.assertEqual(row["page_number"], 2)
        self.assertIn("SYNTHETIC-PACKAGE", text)
        self.assertIn("Page 2 of 3", text)
        self.assertEqual(meta["pages_extracted"], 3)

    def test_page_locations_survive_packet_and_span_chunking(self):
        from common.capture_understanding import build_spans
        from common.evidence_selection import source_locations
        text, meta = self.coverage(self.pdf())
        packet = build_packet(profile={}, resolved={}, notice_text="", attachment_bundle={"attachments": [{
            "filename": "synthetic.pdf", "parser_status": "parsed_pdf", "understanding_text": text,
            "understanding_coverage": meta}]})
        locations = [loc for span in build_spans(packet).values() for loc in source_locations(span)]
        self.assertEqual({loc["page_number"] for loc in locations}, {1, 2, 3})
        self.assertEqual(sum(loc["document_char_end"] - loc["document_char_start"] for loc in locations), len(text))
        self.assertTrue(all(loc["filename"] == "synthetic.pdf" for loc in locations))

    def test_vision_offsets_keep_page_and_extraction_basis_separate(self):
        pages = [{"page_number": 1, "section_blocks": [{"text": "Table requires two inspections."}], "table_rows": []},
                 {"page_number": 3, "section_blocks": [], "table_rows": [{"text": "CLIN 2: repair; 12 months."}]}]
        text, meta = attachments._understanding_input(self.pdf(), "synthetic.pdf", "", pages)
        vision = [r for r in meta["text_regions"] if r["basis"] == "vision_extraction_unverified"]
        self.assertEqual([r["page_number"] for r in vision], [1, 3])
        self.assertIn("two inspections", text[vision[0]["start"]:vision[0]["end"]])
        self.assertIn("CLIN 2", text[vision[1]["start"]:vision[1]["end"]])
        self.assertEqual(vision[-1]["end"], len(text))

    def test_truly_blank_page_is_covered_without_dropping_its_number(self):
        text, meta = self.coverage(self.pdf(header=""))
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["page_coverage"][1]["status"], "verified_blank")
        self.assertIn("[Page 2]", text)

    def test_footer_only_page_is_covered(self):
        _, meta = self.coverage(self.pdf(lambda p: p.insert_text((40, 765), "Page 2 of 3"), header=""))
        self.assertTrue(meta["complete"])

    def test_long_repeated_header_is_not_a_reason_to_drop_text(self):
        text, meta = self.coverage(self.pdf(header="SYNTHETIC DOCUMENT FOR FIXTURE ONLY - GENERAL TERMS"))
        self.assertTrue(meta["complete"])
        self.assertIn("GENERAL TERMS", text)

    def test_short_body_requirement_is_not_blank(self):
        text, meta = self.coverage(self.pdf(lambda p: p.insert_text((40, 300), "No site access."), header=""))
        self.assertFalse(meta["complete"])
        self.assertEqual(meta["unreadable_pages"], [2])
        self.assertIn("No site access.", text)

    def test_unique_margin_note_requires_review(self):
        _, meta = self.coverage(self.pdf(lambda p: p.insert_text((40, 35), "No entry before approval."), header=""))
        self.assertFalse(meta["complete"])

    def test_one_other_header_occurrence_is_not_enough(self):
        _, meta = self.coverage(self.pdf(count=2))
        self.assertFalse(meta["complete"])

    def test_image_only_page_is_not_blank(self):
        def image(page):
            pix = attachments.fitz.Pixmap(attachments.fitz.csRGB, (0, 0, 20, 20))
            pix.clear_with(0)
            page.insert_image(attachments.fitz.Rect(40, 200, 240, 400), pixmap=pix)
        _, meta = self.coverage(self.pdf(image))
        self.assertFalse(meta["complete"])
        self.assertEqual(meta["unreadable_pages"], [2])

    def test_vector_content_is_not_blank(self):
        _, meta = self.coverage(self.pdf(lambda p: p.draw_rect(attachments.fitz.Rect(40, 200, 300, 400))))
        self.assertFalse(meta["complete"])

    def test_annotation_is_not_blank(self):
        _, meta = self.coverage(self.pdf(lambda p: p.add_text_annot((100, 200), "Deadline changed.")))
        self.assertFalse(meta["complete"])

    def test_form_widget_is_not_blank(self):
        def widget(page):
            item = attachments.fitz.Widget()
            item.field_name = "Required response"
            item.field_type = attachments.fitz.PDF_WIDGET_TYPE_TEXT
            item.rect = attachments.fitz.Rect(40, 200, 200, 250)
            page.add_widget(item)
        _, meta = self.coverage(self.pdf(widget))
        self.assertFalse(meta["complete"])

    def test_link_is_not_blank(self):
        def link(page):
            page.insert_link({"kind": attachments.fitz.LINK_URI,
                              "from": attachments.fitz.Rect(40, 200, 200, 250),
                              "uri": "https://example.invalid/attachment"})
        _, meta = self.coverage(self.pdf(link))
        self.assertFalse(meta["complete"])

    def test_internal_navigation_is_retained_not_treated_as_unreadable_content(self):
        def link(page):
            page.insert_link({"kind": attachments.fitz.LINK_GOTO,
                              "from": attachments.fitz.Rect(40, 200, 200, 250),
                              "page": 0, "to": attachments.fitz.Point(40, 200)})
        _, meta = self.coverage(self.pdf(link))
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["page_coverage"][1]["internal_navigation_targets"], [1])

    def test_internal_link_target_outside_extracted_pages_stays_blocked(self):
        def link(page):
            page.insert_link({"kind": attachments.fitz.LINK_GOTO,
                              "from": attachments.fitz.Rect(40, 200, 200, 250),
                              "page": 0, "to": attachments.fitz.Point(40, 200)})
        with attachments.fitz.open(stream=self.pdf(link), filetype="pdf") as doc:
            row = attachments._sparse_pdf_page_coverage(doc[1], [], {}, available_pages=0)
            self.assertEqual(row["status"], "unreadable")

    def test_failed_layout_inspection_stays_blocked(self):
        from unittest.mock import MagicMock
        page = MagicMock()
        page.rotation = 0
        page.get_image_info.side_effect = RuntimeError("layout unavailable")
        row = attachments._sparse_pdf_page_coverage(page, [], {})
        self.assertEqual(row["status"], "unreadable")

    def test_readable_vision_on_other_pages_does_not_clear_image_page(self):
        _, meta = attachments._understanding_input(
            self.pdf(lambda p: p.draw_rect(attachments.fitz.Rect(40, 200, 300, 400))),
            "synthetic.pdf", "", [{"page_number": 1, "section_blocks": [
                {"title": "Scope", "text": "The contractor shall inspect equipment."}]}])
        self.assertFalse(meta["complete"])

    def test_rotated_sparse_page_is_not_guessed_blank(self):
        _, meta = self.coverage(self.pdf(lambda p: p.set_rotation(90)))
        self.assertFalse(meta["complete"])

    def test_sparse_page_after_forty_is_checked(self):
        _, meta = self.coverage(self.pdf(count=44))
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["page_coverage"][42]["status"], "verified_header_footer_only")

    def test_no_layout_backend_cannot_certify_blank_pages(self):
        data = self.pdf()
        with patch.object(attachments, "fitz", None):
            _, meta = attachments._understanding_input(data, "synthetic.pdf", "", [])
        self.assertFalse(meta["complete"])

    def test_bad_pdf_stays_blocked(self):
        _, meta = self.coverage(b"not a pdf")
        self.assertFalse(meta["complete"])

    def test_full_attachment_path_and_checkpoint_clear_only_verified_blank(self):
        for decorate, expected_blocked in ((None, False), (lambda p: p.add_text_annot((100, 200), "Read this"), True)):
            with self.subTest(blocked=expected_blocked), patch.object(attachments, "_review_hard_pdf_pages", return_value={}):
                row = attachments._attachment_record_from_bytes(
                    url="", filename="synthetic.pdf", content_type="application/pdf",
                    data=self.pdf(decorate), truncated=False)
                packet = build_packet(profile={}, resolved={}, attachment_bundle={"attachments": [row]}, notice_text="")
                self.assertEqual(bool(packet["technical_issues"]), expected_blocked)

    def test_truncated_source_remains_incomplete(self):
        with patch.object(attachments, "_review_hard_pdf_pages", return_value={}):
            row = attachments._attachment_record_from_bytes(
                url="", filename="synthetic.pdf", content_type="application/pdf",
                data=self.pdf(), truncated=True)
        self.assertFalse(row["understanding_coverage"]["complete"])


if __name__ == "__main__":
    unittest.main()
