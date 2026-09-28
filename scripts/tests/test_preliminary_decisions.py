"""Decision-fidelity regressions. Mock model verdicts are not live semantic proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import preliminary_decisions as d


def decision(**kw):
    return dict(topic='general', stage='unknown', force='informational', period='not stated',
                acquisition_dimension='none',
                quantities=[], selection_basis='not_applicable', selected_controls=[], **kw)


def finding(key, text, *, topic='general', stage='issued', force='required', period='base', quantities=None):
    return {'id': key, 'role': 'decision_condition', 'kind': 'decision_condition',
            'statement': text, 'implication': 'Check the supplied evidence.',
            'evidence': [{'ref': 'D1:0', 'quote': text}],
            'decision': {'topic': topic, 'stage': stage, 'force': force, 'period': period,
                         'acquisition_dimension': 'other' if topic == 'acquisition' else 'none',
                         'quantities': quantities or [], 'selection_basis': 'not_applicable', 'selected_controls': []}}


class DecisionContracts(unittest.TestCase):
    def test_printed_option_label_without_selection_basis_is_not_admitted(self):
        sources = {'D1:0': {'kind': 'package', 'text': 'Open competition / Restricted competition',
                           'choice_review_required': True}}
        row = finding('F1', sources['D1:0']['text'], topic='acquisition')
        row['decision']['acquisition_dimension'] = 'competition_method'
        with self.assertRaisesRegex(ValueError, 'selection'):
            d.validate_decision(row, sources)

    def test_selected_control_must_be_cited_and_cannot_be_an_unchecked_sibling(self):
        sources = {'D1:0': {'kind': 'package', 'text': 'Open competition; state selected',
                           'form_controls': [{'id': 'p1-c1', 'label': 'Open competition', 'state': 'selected'},
                                             {'id': 'p1-c2', 'label': 'Restricted competition', 'state': 'unselected'}]}}
        row = finding('F1', sources['D1:0']['text'], topic='acquisition')
        row['decision'].update(selection_basis='selected_control', selected_controls=[{'ref': 'D1:0', 'id': 'p1-c1', 'label': 'Open competition'}])
        d.validate_decision(row, sources)
        row['decision']['selected_controls'][0].update(id='p1-c2', label='Restricted competition')
        with self.assertRaisesRegex(ValueError, 'selected'):
            d.validate_decision(row, sources)
        row['decision']['selected_controls'][0].update(ref='D9:0', id='p1-c1')
        with self.assertRaises(ValueError):
            d.validate_decision(row, sources)

    def test_supersession_retains_history_but_only_governing_term_reaches_assessment(self):
        rows = {'old': finding('old', 'Hold prices for 45 days.', topic='offer_validity'),
                'new': finding('new', 'The acceptance period is replaced by 120 days.', topic='offer_validity')}
        relations = {'old': {'state': 'superseded', 'governing_ids': ['new'], 'reason': 'Explicit replacement.'},
                     'new': {'state': 'active', 'governing_ids': [], 'reason': 'The replacement term.'}}
        before = deepcopy(rows)
        active, history = d.apply_reconciliation(rows, relations)
        self.assertEqual(list(active), ['new'])
        self.assertEqual(history['old']['reconciliation']['governing_ids'], ['new'])
        self.assertEqual(rows, before)

    def test_invalid_cycles_and_cross_topic_replacements_fail(self):
        rows = {'a': finding('a', 'A', topic='offer_validity'), 'b': finding('b', 'B', topic='offer_validity')}
        relations = {k: {'state': 'superseded', 'governing_ids': [v], 'reason': 'Replacement.'} for k, v in [('a', 'b'), ('b', 'a')]}
        with self.assertRaises(ValueError):
            d.apply_reconciliation(rows, relations)
        relations['b'] = {'state': 'active', 'governing_ids': [], 'reason': 'Active.'}
        rows['b']['decision']['topic'] = 'staffing'
        with self.assertRaises(ValueError):
            d.apply_reconciliation(rows, relations)

    def test_unresolved_conflicts_retain_both_sides_without_latest_file_wins(self):
        rows = {k: finding(k, text, topic='offer_validity') for k, text in [('a', '45 days'), ('b', '120 days')]}
        relations = {k: {'state': 'unresolved', 'governing_ids': [v], 'reason': 'No precedence in supplied text.'} for k, v in [('a', 'b'), ('b', 'a')]}
        active, history = d.apply_reconciliation(rows, relations)
        self.assertEqual(set(active), {'a', 'b'})
        self.assertFalse(history)
        self.assertTrue(all(r['role'] == 'conflict' for r in active.values()))

    def test_draft_context_is_propagated_without_turning_anticipation_into_mandate(self):
        sources = {'D1:0': {'document_id': 'doc-a'}, 'D2:0': {'document_id': 'doc-a'}, 'D3:0': {'document_id': 'doc-b'}}
        rows = {'ctx': finding('ctx', 'Draft scope.', topic='document_status', stage='draft', force='informational'),
                'staff': finding('staff', 'The buyer anticipates eight analysts.', topic='staffing', stage='unknown', force='anticipated', quantities=['eight analysts']),
                'other': finding('other', 'A separate issued requirement.', stage='issued')}
        rows['staff']['evidence'][0]['ref'] = 'D2:0'
        rows['other']['evidence'][0]['ref'] = 'D3:0'
        tagged = d.attach_document_context(rows, sources)
        self.assertEqual(tagged['staff']['document_context_ids'], ['ctx'])
        self.assertIn('draft', tagged['staff']['effective_stages'])
        self.assertEqual(tagged['staff']['decision']['force'], 'anticipated')
        self.assertNotIn('draft', tagged['other']['effective_stages'])

    def test_quantities_are_present_in_main_display_without_combining_options(self):
        base = finding('base', 'Engineering support.', topic='staffing', quantities=['four positions', '1 FTE each'])
        option = finding('option', 'Additional support.', topic='staffing', force='optional', period='option year', quantities=['two positions'])
        refs = finding('refs', 'Relevant performance references.', topic='experience', quantities=['seven references'])
        self.assertIn('four positions', d.qualifier_text(base))
        self.assertIn('optional', d.qualifier_text(option))
        self.assertIn('option year', d.qualifier_text(option))
        self.assertIn('seven references', d.qualifier_text(refs))


if __name__ == '__main__':
    unittest.main()
