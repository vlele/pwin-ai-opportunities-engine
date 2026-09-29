"""Source accounting regressions, not a claim of live model reliability."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, semantic_plan as plan
from common.evidence_selection import EvidenceTransport


def fixture(text='cybersecurity'):
    spans = {ref: {'source_id': ref.split(':')[0], 'kind': 'profile', 'offset': 0,
                   'profile_field': field, 'text': text}
             for ref, field in (('V12:0', 'core_competencies[0]'),
                                ('V31:0', 'other_taxonomy_tags.keywords[0]'))}
    batch = h._batch({}, spans, 'vendor')
    claim = {'meaning': 'A capability keyword is listed in the supplied profile.',
             'attribution': 'self', 'assertion_basis': 'context',
             'evidence': [{'ref': 'V12:0', 'quote': text}],
             'antecedent_evidence': [], 'unresolved_dimensions': []}
    raw = {'requirements': [], 'claims': [claim], 'quoted_vendor_context': [],
           'questions': [], 'resolved_question_ids': [],
           'vendor_coverage': {ref: {'claims': [0], 'reason': 'This field contributes the keyword.'}
                               for ref in spans}}
    return batch, raw


def cite_both(batch, raw):
    raw['claims'][0]['evidence'].append({'ref': 'V31:0', 'quote': batch['payload']['spans']['V31:0']['text']})
    return raw


class VendorCitationCoverageTests(unittest.TestCase):
    def test_duplicate_text_without_second_citation_is_rejected(self):
        batch, raw = fixture()
        before = deepcopy((batch, raw))
        with self.assertRaisesRegex(ValueError, 'Vendor disposition cites a different source'):
            h.validate_batch(raw, batch)
        self.assertEqual((batch, raw), before)

    def test_both_citations_preserve_each_field_in_audit_target(self):
        batch, raw = fixture()
        cite_both(batch, raw)
        before = deepcopy((batch, raw))
        mapped = h.validate_batch(raw, batch)
        target = h.handoff_targets(batch, mapped)[0]
        self.assertEqual(target['retained_records'][0]['evidence'], raw['claims'][0]['evidence'])
        self.assertEqual(target['dispositions'], raw['vendor_coverage'])
        self.assertEqual({s['profile_field'] for s in target['spans'].values()},
                         {'core_competencies[0]', 'other_taxonomy_tags.keywords[0]'})
        self.assertEqual((batch, raw), before)

    def test_selection_wire_resolves_two_citations_not_one_alias(self):
        batch, raw = fixture()
        wire = EvidenceTransport(batch['schema'], batch['payload'])
        raw['claims'][0]['evidence'] = [{'start': {'ref': ref, 'line': 1},
                                       'end': {'ref': ref, 'line': 1}}
                                      for ref in batch['payload']['spans']]
        mapped = h.validate_batch(wire.resolve(raw), batch)
        self.assertEqual(mapped['inventory']['claims'][0]['evidence'],
                         [{'ref': ref, 'quote': 'cybersecurity'} for ref in batch['payload']['spans']])

    def test_rule_transfers_to_unrelated_capability_keywords(self):
        for text in ('equipment calibration', 'translation services', 'shoreline sampling'):
            with self.subTest(text=text):
                batch, raw = fixture(text)
                with self.assertRaisesRegex(ValueError, 'different source'):
                    h.validate_batch(raw, batch)
                self.assertEqual(len(h.validate_batch(cite_both(batch, raw), batch)['inventory']['claims']), 1)

    def test_citation_in_another_claim_does_not_cover_this_claim(self):
        batch, raw = fixture()
        other = deepcopy(raw['claims'][0])
        other['evidence'][0]['ref'] = 'V31:0'
        raw['claims'].append(other)
        raw['vendor_coverage']['V31:0']['claims'] = [0, 1]
        with self.assertRaisesRegex(ValueError, 'different source'):
            h.validate_batch(raw, batch)
        raw['vendor_coverage']['V31:0']['claims'] = [1]
        self.assertEqual(len(h.validate_batch(raw, batch)['inventory']['claims']), 2)

    def test_reason_text_cannot_substitute_for_citation(self):
        batch, raw = fixture()
        raw['vendor_coverage']['V31:0']['reason'] = 'V31:0 contains cybersecurity and is identical to V12:0.'
        with self.assertRaisesRegex(ValueError, 'different source'):
            h.validate_batch(raw, batch)

    def test_nonmatching_source_is_not_retargeted_by_coverage(self):
        batch, raw = fixture()
        batch['payload']['spans']['V31:0']['text'] = 'No calibration experience was supplied.'
        with self.assertRaisesRegex(ValueError, 'different source'):
            h.validate_batch(raw, batch)

    def test_second_citation_must_quote_its_own_source(self):
        batch, raw = fixture()
        batch['payload']['spans']['V31:0']['text'] = 'No calibration experience was supplied.'
        raw['claims'][0]['evidence'].append({'ref': 'V31:0', 'quote': 'cybersecurity'})
        with self.assertRaises(ValueError):
            h.validate_batch(raw, batch)

    def test_unknown_source_or_dangling_claim_link_is_rejected(self):
        for mode in ('unknown_source', 'dangling_claim'):
            batch, raw = fixture()
            cite_both(batch, raw)
            if mode == 'unknown_source':
                raw['claims'][0]['evidence'][1]['ref'] = 'V404:0'
            else:
                raw['vendor_coverage']['V31:0']['claims'] = [8]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                h.validate_batch(raw, batch)

    def test_complete_citations_do_not_override_semantic_audit_rejection(self):
        batch, raw = fixture()
        mapped = h.validate_batch(cite_both(batch, raw), batch)
        targets = h.handoff_targets(batch, mapped)
        verdict = plan.validate_audit({'checks': {t['id']: {'verdict': 'unsupported',
            'reason': 'The citations exist but the claim misstates attribution.'} for t in targets}}, targets)
        self.assertFalse(verdict['passed'])

    def test_vendor_prompt_states_per_claim_complete_citation_rule(self):
        batch, _ = fixture()
        for prompt in (h.VENDOR_RULES, batch['prompt']):
            self.assertIn('COMPLETE VENDOR CITATIONS', prompt)
            self.assertIn('vendor_coverage[ref].claims', prompt)
            self.assertIn("that SAME claim's evidence array", prompt)
            self.assertIn('ALL covered source refs', prompt)
            self.assertIn('even when their text is identical', prompt)
        for fixture_detail in ('V12:0', 'V31:0', 'cybersecurity'):
            self.assertNotIn(fixture_detail, h.VENDOR_RULES)


if __name__ == '__main__':
    unittest.main()
