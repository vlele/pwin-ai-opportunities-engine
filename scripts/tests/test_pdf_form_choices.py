"""Synthetic PDF controls, never solicitation-specific page/label whitelists."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture import fetch_notice_attachments as f
from common import form_evidence as forms
from common.capture_clarification import build_packet
from common.capture_understanding import build_spans
from common.evidence_selection import EvidenceTransport, _lines
from common import preliminary_capture as p


@unittest.skipIf(f.fitz is None, 'PyMuPDF is required')
class FormChoiceTests(unittest.TestCase):
    def test_native_checkbox_states_have_page_and_bbox_provenance(self):
        with f.fitz.open() as pdf:
            page = pdf.new_page()
            for n, (label, selected) in enumerate([('Open competition', True), ('Restricted competition', False)]):
                w = f.fitz.Widget()
                w.field_name = label
                w.field_label = label
                w.field_type = f.fitz.PDF_WIDGET_TYPE_CHECKBOX
                w.rect = f.fitz.Rect(20, 20 + 30 * n, 32, 32 + 30 * n)
                w.field_value = selected
                page.add_widget(w)
            data = pdf.tobytes()
        records = f._pdf_page_records(data)
        controls = records[0]['form_controls']
        self.assertEqual([c['state'] for c in controls], ['selected', 'unselected'])
        self.assertTrue(all(c['page_number'] == 1 and len(c['bbox']) == 4 for c in controls))
        self.assertTrue(all(c['basis'] == 'native_widget' for c in controls))

    def test_flat_vector_boxes_trigger_review_ahead_of_generic_tables(self):
        with f.fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((45, 28), 'Open competition')
            page.draw_rect(f.fitz.Rect(20, 18, 30, 28))
            page.draw_line((20, 18), (30, 28))
            page.draw_rect(f.fitz.Rect(20, 48, 30, 58))
            data = pdf.tobytes()
        records = f._pdf_page_records(data)
        self.assertIn('choice_controls', records[0]['flags'])
        self.assertEqual(records[0]['form_controls'], [])
        table = {'page_number': 2, 'flags': ['table_layout', 'requirement_matrix_markers'], 'marker_hits': 4}
        self.assertEqual(f._select_hard_page_candidates([table, records[0]], max_pages=1)[0]['page_number'], 1)

    def test_uncertain_vision_state_is_not_coerced_to_selected(self):
        raw = [{'label': 'A', 'state': 'maybe', 'bbox': [0.1, 0.1, 0.2, 0.2], 'group': 'Choice'}]
        controls = forms.normalize_vision_controls(raw, 2)
        self.assertEqual(controls[0]['state'], 'uncertain')
        self.assertEqual(controls[0]['basis'], 'vision_observation')

    def test_malformed_vision_types_cannot_crash_or_become_a_selected_control(self):
        for state in (None, True, [], {'selected': True}):
            with self.subTest(state=state):
                controls = forms.normalize_vision_controls([{'label': 'A', 'state': state, 'bbox': [0, 0, 0.2, 0.2]}], 1)
                self.assertEqual(controls[0]['state'], 'uncertain')
        self.assertEqual(forms.normalize_vision_controls([{'label': {'text': 'A'}, 'state': 'selected', 'bbox': [0, 0, 1, 1]}], 1), [])

    def test_native_and_vision_disagreement_stays_uncertain(self):
        native = [{'id': 'p1-w1', 'label': 'A', 'state': 'selected', 'page_number': 1, 'bbox': [10, 10, 20, 20], 'basis': 'native_widget'}]
        vision = [{'id': 'p1-v1', 'label': 'A', 'state': 'unselected', 'page_number': 1, 'bbox': [0.1, 0.1, 0.2, 0.2], 'basis': 'vision_observation'}]
        controls = forms.merge_controls(native, vision)
        self.assertTrue(all(c['state'] == 'uncertain' for c in controls))

    def test_geometric_identity_handles_different_native_and_visual_group_names(self):
        native = [{'id': 'w1', 'label': 'Yes', 'group': 'Widget42', 'state': 'selected', 'page_number': 1,
                   'bbox': [10, 10, 20, 20], 'page_size': [100, 100], 'coordinate_space': 'pdf_points', 'basis': 'native_widget'}]
        vision = [{'id': 'v1', 'label': 'Yes', 'group': 'Eligibility', 'state': 'unselected', 'page_number': 1,
                   'bbox': [0.1, 0.1, 0.2, 0.2], 'coordinate_space': 'normalized_page', 'basis': 'vision_observation'}]
        self.assertTrue(all(c['state'] == 'uncertain' for c in forms.merge_controls(native, vision)))
        vision[0]['bbox'] = [0.1, 0.6, 0.2, 0.7]
        self.assertEqual([c['state'] for c in forms.merge_controls(native, vision)], ['selected', 'unselected'])

    def test_choice_pages_outside_vision_budget_are_recorded_not_assumed(self):
        records = [{'page_number': n, 'flags': ['choice_controls'], 'form_controls': [], 'text': 'Choices'} for n in (1, 2, 3)]
        with patch.object(f, '_pdf_page_records', return_value=records), \
             patch.object(f, '_select_hard_page_candidates', return_value=records[:1]), \
             patch.object(f, '_openai_client', return_value=None):
            result = f._review_hard_pdf_pages(filename='form.pdf', category='solicitation', data=b'ignored')
        self.assertEqual(result['unresolved_choice_pages'], [1, 2, 3])

    def test_form_observations_do_not_overlap_native_evidence_offsets(self):
        text = 'Inspect equipment. Open competition / Restricted competition.'
        controls = [{'id': 'p1-v1', 'label': 'Open competition', 'group': 'Acquisition', 'state': 'selected',
                     'page_number': 1, 'bbox': [0.1, 0.1, 0.2, 0.2], 'basis': 'vision_observation'}]
        packet = build_packet(profile={}, resolved={}, notice_text='', attachment_bundle={'attachments': [{
            'filename': 'synthetic.pdf', 'parser_status': 'parsed_pdf', 'understanding_text': text,
            'understanding_coverage': {'complete': True, 'text_regions': [{'start': 0, 'end': len(text), 'page_number': 1}]},
            'form_controls': controls}]})
        spans = build_spans(packet)
        control_ref = next(k for k, s in spans.items() if s.get('form_controls'))
        control_source = spans[control_ref]
        self.assertEqual(control_source['source_offset'], len(text))
        self.assertTrue(spans['D1:0']['choice_review_required'])
        wire = EvidenceTransport(p.obj({'evidence': p.anchors(spans)}), {'spans': spans})
        raw = {'evidence': [{'start': {'ref': control_ref, 'line': 1}, 'end': {'ref': control_ref, 'line': len(_lines(control_source['text']))}}]}
        resolved = wire.resolve(raw)['evidence']
        self.assertIn('state selected', resolved[0]['quote'])
        native = {'evidence': [{'start': {'ref': 'D1:0', 'line': 1}, 'end': {'ref': 'D1:0', 'line': len(_lines(text))}}]}
        self.assertEqual(wire.resolve(native)['evidence'][0]['quote'], text)

    def test_choice_control_page_after_forty_is_still_discovered(self):
        with f.fitz.open() as pdf:
            for _ in range(44):
                page = pdf.new_page()
                page.insert_text((40, 100), 'Ordinary document text, no decision controls.')
            page.draw_rect(f.fitz.Rect(20, 18, 30, 28))
            data = pdf.tobytes()
        records = f._pdf_page_records(data)
        self.assertEqual(len(records), 44)
        self.assertEqual(f._select_hard_page_candidates(records, max_pages=1)[0]['page_number'], 44)

    def test_vision_controls_missing_bbox_remain_uncertain(self):
        for bbox in (None, [], [0, 0, 1, float('nan')], [-1, 0, 1, 1], [1, 0, 0, 1]):
            with self.subTest(bbox=bbox):
                controls = forms.normalize_vision_controls([{'label': 'Choice', 'state': 'selected', 'bbox': bbox}], 1)
                self.assertEqual(controls[0]['state'], 'uncertain')

    def test_controls_are_reviewed_even_if_filename_category_is_other(self):
        records = [{'page_number': 1, 'flags': ['choice_controls'], 'form_controls': [], 'text': 'Choices'}]
        with patch.object(f, '_pdf_page_records', return_value=records), \
             patch.object(f, '_openai_client', return_value=None):
            result = f._review_hard_pdf_pages(filename='response.pdf', category='questions_answers', data=b'ignored')
        self.assertEqual(result['candidates'][0]['page_number'], 1)
        self.assertEqual(result['unresolved_choice_pages'], [1])

    def test_form_logic_change_invalidates_attachment_cache_identity(self):
        import tempfile
        from common.capture_clarification import local_input_fingerprint
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.txt'
            path.write_text('Synthetic scope')
            original = local_input_fingerprint([str(path)])
            read = Path.read_bytes
            def altered(self):
                value = read(self)
                return value + b'\n# changed observation logic\n' if self.name == 'form_evidence.py' else value
            with patch.object(Path, 'read_bytes', altered):
                changed = local_input_fingerprint([str(path)])
        self.assertNotEqual(original, changed)


if __name__ == '__main__':
    unittest.main()
