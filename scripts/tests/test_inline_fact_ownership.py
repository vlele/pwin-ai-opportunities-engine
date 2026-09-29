"""Model selects fact identities; code, never the model, counts record positions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h
from common.evidence_selection import EvidenceTransport
from inline_fact_fixture import inline_saved_mapping


def fixture(count=3):
    spans, facts, rows = {}, {}, []
    for i in range(count):
        ref, fid = f'D{i}:0', f'F{i}'
        text = f'Deliver sample set {i + 1} within five days of collection.\n'
        spans[ref] = {'source_id': f'D{i}', 'document_id': 'synthetic',
                      'offset': 0, 'source_offset': i * 1000, 'kind': 'package', 'text': text}
        facts[fid] = {'area': 'scope', 'statement': text.strip(), 'refs': [ref]}
        rows.append({'area': 'scope', 'task': True, 'status': 'current',
                     'record_kind': 'requirement', 'supersedes': [],
                     'focus': [{'ref': ref, 'quote': text}], 'supporting_context': [],
                     'originating_fact_ids': [fid]})
    batch = h._batch(facts, spans, 'package')
    raw = {'requirements': rows, 'claims': [], 'quoted_vendor_context': [],
           'questions': [], 'resolved_question_ids': []}
    return batch, raw


class InlineFactOwnershipTests(unittest.TestCase):
    def test_wire_uses_inline_fact_enum_not_separate_positional_mapping(self):
        batch, _ = fixture()
        schema = EvidenceTransport(batch['schema'], batch['payload']).schema
        self.assertNotIn('fact_coverage', schema['properties'])
        for key in ('requirements', 'quoted_vendor_context'):
            row = schema['properties'][key]['items']
            self.assertIn('originating_fact_ids', row['required'])
            field = row['properties']['originating_fact_ids']
            self.assertEqual(field['minItems'], 1)
            self.assertEqual(set(field['items']['enum']), {'F0', 'F1', 'F2'})

    def test_thirty_rows_need_no_model_generated_thirty_first_pointer(self):
        batch, raw = fixture(30)
        before = deepcopy((batch, raw))
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_coverage']['F29'], [{'array': 'requirements', 'index': 29}])
        self.assertEqual(len(mapped['fact_coverage']), 30)
        self.assertEqual((batch, raw), before)

    def test_reordering_rows_rebuilds_links_from_identity(self):
        batch, raw = fixture()
        raw['requirements'].reverse()
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_coverage']['F0'], [{'array': 'requirements', 'index': 2}])
        self.assertEqual(h.handoff_targets(batch, mapped)[0]['retained_records'][0]['meaning'],
                         batch['payload']['spans']['D0:0']['text'])

    def test_one_fact_can_produce_multiple_records_without_duplicate_id_error(self):
        batch, raw = fixture(1)
        raw['requirements'].append(deepcopy(raw['requirements'][0]))
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_coverage']['F0'], [
            {'array': 'requirements', 'index': 0}, {'array': 'requirements', 'index': 1}])
        inventory, receipt = h.merge([(batch, mapped)], batch['payload']['spans'])
        self.assertEqual(len(inventory['requirements']), 1)
        self.assertEqual(receipt['fact_coverage']['F0'], [{'array': 'requirements', 'index': 0}])

    def test_many_facts_can_share_a_record_without_erasing_either_lineage(self):
        batch, raw = fixture(2)
        raw['requirements'][0]['originating_fact_ids'] = ['F0', 'F1']
        raw['requirements'][0]['supporting_context'] = raw['requirements'][1]['focus']
        raw['requirements'].pop()
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_coverage']['F0'], mapped['fact_coverage']['F1'])
        self.assertEqual(mapped['fact_provenance']['F1']['ledger_refs'], ['D1:0'])
        self.assertEqual(len(h.handoff_targets(batch, mapped)), 2)

    def test_package_reference_retains_its_role_and_inline_ownership(self):
        batch, raw = fixture(1)
        row = raw['requirements'].pop()
        raw['quoted_vendor_context'] = [{'meaning': batch['payload']['spans']['D0:0']['text'],
            'evidence': row['focus'], 'originating_fact_ids': ['F0']}]
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_coverage']['F0'], [{'array': 'quoted_vendor_context', 'index': 0}])
        self.assertEqual(mapped['inventory']['claims'], [])
        self.assertEqual(mapped['inventory']['requirements'], [])
        self.assertEqual(h.handoff_targets(batch, mapped)[0]['fact'], batch['payload']['fact_ledger']['F0'])

    def test_zero_based_question_and_precedence_validation_is_not_relaxed(self):
        for kind in ('question', 'supersedes'):
            batch, raw = fixture(2)
            if kind == 'question':
                raw['questions'] = [{'dimension': 'requirement_meaning', 'requirements': [2],
                    'claims': [], 'reason': 'Conflicting source terms.', 'decision': 'scope'}]
            else:
                raw['requirements'][1]['record_kind'] = 'precedence_rule'
                raw['requirements'][1]['supersedes'] = [2]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                h.validate_batch(raw, batch)

    def test_introducing_an_unowned_record_cannot_sneak_past_full_fact_coverage(self):
        batch, raw = fixture(1)
        unowned = deepcopy(raw['requirements'][0])
        unowned.pop('originating_fact_ids')
        raw['requirements'].append(unowned)
        with self.assertRaisesRegex(ValueError, r'requirements\[1\]'):
            h.validate_batch(raw, batch)

    def test_missing_unknown_duplicate_empty_and_malformed_ownership_fail(self):
        for ids in ([], ['invented'], ['F0', 'F0'], 'F0', [False], [None]):
            batch, raw = fixture(1)
            raw['requirements'][0]['originating_fact_ids'] = ids
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                h.validate_batch(raw, batch)
        batch, raw = fixture(1)
        raw['requirements'][0].pop('originating_fact_ids')
        with self.assertRaises(ValueError):
            h.validate_batch(raw, batch)

    def test_omitted_fact_is_still_rejected(self):
        batch, raw = fixture(2)
        raw['requirements'].pop()
        with self.assertRaisesRegex(ValueError, 'F1'):
            h.validate_batch(raw, batch)

    def test_legacy_map_is_rejected_not_clamped_or_accepted_as_override(self):
        batch, raw = fixture(30)
        raw['fact_coverage'] = {'F29': [{'array': 'requirements', 'index': 30}]}
        with self.assertRaises(ValueError):
            h.validate_batch(raw, batch)

    def test_source_role_and_quote_checks_stay_strict(self):
        for mode in ('private', 'invented_quote'):
            batch, raw = fixture(1)
            if mode == 'private':
                batch['payload']['spans']['D0:0']['kind'] = 'profile'
            else:
                raw['requirements'][0]['focus'][0]['quote'] = 'No deadline applies.'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                h.validate_batch(raw, batch)

    def test_complete_fact_id_mapping_cannot_bypass_semantic_rejection(self):
        batch, raw = fixture(1)
        raw['requirements'][0]['focus'][0]['quote'] = 'Deliver sample set 1'
        stages = []
        def invoke(stage, prompt, payload, schema, validator):
            stages.append(stage)
            if stage.startswith('semantic-inventory-'):
                return validator(raw)
            self.assertIn('within five days', payload['targets'][0]['spans']['D0:0']['text'])
            self.assertEqual(payload['targets'][0]['retained_records'][0]['meaning'], 'Deliver sample set 1')
            return validator({'checks': {t['id']: {'verdict': 'unsupported',
                'reason': 'The selected record lost the deadline and its collection trigger.'}
                for t in payload['targets']}})
        with self.assertRaisesRegex(ValueError, 'Inventory handoff audit failed'):
            h.build(list(batch['payload']['fact_ledger'].values()), batch['payload']['spans'], invoke, [])
        self.assertTrue(any(s.startswith('inventory-handoff-audit') for s in stages))


class HistoricalFixtureTests(unittest.TestCase):
    def legacy(self):
        batch, raw = fixture(2)
        raw['fact_coverage'] = {row.pop('originating_fact_ids')[0]: [
            {'array': 'requirements', 'index': i}] for i, row in enumerate(raw['requirements'])}
        return batch, raw

    def test_explicit_valid_saved_links_can_be_translated_without_mutation(self):
        batch, raw = self.legacy()
        before = deepcopy(raw)
        translated = inline_saved_mapping(raw)
        self.assertEqual(h.validate_batch(translated, batch)['fact_coverage'], raw['fact_coverage'])
        self.assertEqual(raw, before)

    def test_saved_dangling_index_is_not_guessed(self):
        _, raw = self.legacy()
        raw['fact_coverage']['F1'][0]['index'] = 2
        with self.assertRaisesRegex(ValueError, 'Unknown record index'):
            inline_saved_mapping(raw)

    def test_unowned_or_competing_saved_ownership_fails(self):
        for kind in ('unowned', 'competing', 'duplicate', 'negative', 'bool'):
            _, raw = self.legacy()
            if kind == 'unowned':
                raw['fact_coverage'].pop('F1')
            elif kind == 'competing':
                raw['requirements'][0]['originating_fact_ids'] = ['F1']
            elif kind == 'duplicate':
                raw['fact_coverage']['F0'] *= 2
            else:
                raw['fact_coverage']['F0'][0]['index'] = -1 if kind == 'negative' else True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                inline_saved_mapping(raw)


if __name__ == '__main__':
    unittest.main()
