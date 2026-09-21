"""Input coverage must be explicit before semantic clarification can succeed."""
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture import fetch_notice_attachments as attachments
from common import capture_clarification as gate


class CoverageTests(unittest.TestCase):
    def test_long_text_tail_reaches_understanding_without_reordering(self):
        text = "Mechanical installation requirements and inspection records.\n" * 3000 + "Final acceptance requires calibrated temperature logs."
        with patch.object(attachments, "_review_hard_pdf_pages", return_value={}):
            row = attachments._attachment_record_from_bytes(url="", filename="scope.txt", content_type="text/plain",
                                                            data=text.encode(), truncated=False)
        self.assertTrue(row["understanding_text"].endswith("Final acceptance requires calibrated temperature logs."))
        self.assertTrue(row["understanding_coverage"]["complete"])
        value = gate.build_packet(profile={}, resolved={}, attachment_bundle={"attachments": [row]}, notice_text="")
        joined = "".join(s["text"] for s in value["sources"].values())
        self.assertEqual(joined, row["understanding_text"])

    def test_attachment_count_limit_is_not_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index in range(2):
                path = Path(folder) / f"scope-{index}.txt"
                path.write_text("Material scope and acceptance requirement. " * 10)
                paths.append(str(path))
            bundle = attachments.load_local_attachments(paths, max_attachments=1)
        self.assertTrue(bundle["errors"])
        self.assertTrue(gate.build_packet(profile={}, resolved={}, attachment_bundle=bundle, notice_text="")["technical_issues"])

    def test_pdf_pages_after_forty_remain_in_checkpoint_text(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is required for the generated PDF fixture")
        with fitz.open() as doc:
            for index in range(43):
                page = doc.new_page()
                page.insert_text((30, 50), f"Scope page {index + 1}: Inspect refrigeration equipment and retain temperature logs.")
            data = doc.tobytes()
        with patch.object(attachments, "_review_hard_pdf_pages", return_value={}):
            row = attachments._attachment_record_from_bytes(url="", filename="scope.pdf", content_type="application/pdf", data=data, truncated=False)
        self.assertIn("Scope page 43", row["understanding_text"])
        self.assertEqual(row["understanding_coverage"]["pages_extracted"], 43)

    def test_known_incomplete_coverage_is_not_rescued_by_good_excerpt(self):
        row = {"filename": "scope.pdf", "parser_status": "parsed_pdf", "structured_text_excerpt": "Readable requirement text.",
               "understanding_coverage": {"complete": False}}
        value = gate.build_packet(profile={}, resolved={}, attachment_bundle={"attachments": [row]}, notice_text="")
        self.assertTrue(value["technical_issues"])


if __name__ == "__main__":
    unittest.main()
