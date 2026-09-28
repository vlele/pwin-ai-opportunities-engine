"""Offline partition/receipt invariants, not pretend model-semantic acceptance."""
from copy import deepcopy
from itertools import combinations
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import audit_partitioning as a, semantic_plan as s, semantic_contract as c
from common.evidence_selection import EvidenceTransport
from common.audit_evidence_encoding import decode


def fixture(count=12, *, contiguous=False):
    spans, reqs = {}, []
    offset = 0
    for i in range(count):
        text = f'Perform task {i}; preserve 12 hours, not 72 hours. ' + ('Original source. ' * 45)
        ref = f'D{i}:0'
        spans[ref] = {'source_id': f'D{i}', 'kind': 'package', 'document_id': 'solicitation',
                      'filename': 'synthetic.pdf', 'offset': 0, 'source_offset': offset, 'text': text}
        offset += len(text) + (0 if contiguous else 100)
        anchor = {'ref': ref, 'quote': text[:text.index('Original')]}
        reqs.append({'area': 'scope', 'status': 'current', 'task': True, 'supersedes': [],
                     'logic': 'all', 'focus': [anchor], 'evidence': [anchor], 'meaning': f'Task {i}',
                     'components': [{'kind': 'work', 'text': f'Task {i}', 'evidence': [anchor]}]})
    spans['V0:0'] = {'source_id': 'V0', 'kind': 'profile', 'text': 'Private assertion; never a public requirement.'}
    target = {'id': 'package-coverage', 'kind': 'package_coverage',
              'value': {'requirements': reqs, 'quoted_vendor_context': []}}
    return target, spans


def supported(plan):
    return {t['id']: {'verdict': 'supported', 'reason': 'Mock receipt for structural test only.'} for t in plan['targets']}


class PartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target, cls.spans = fixture()
        # Keep a fixed synthetic payload allowance as shared policy text evolves.
        # This is a test-only small budget; production remains capped at 640,000.
        cls.limit = len(s.audit_prompt([{'kind': 'package_coverage', 'audit_partition': {}}])) + 14000
        cls.plan = a.prepare(cls.target, cls.spans, max_chars=cls.limit)

    def test_small_package_keeps_canonical_audit(self):
        target, spans = fixture(1)
        got = a.prepare(target, spans)
        self.assertEqual(got['targets'], [target])
        self.assertEqual(len(got['coverage_manifest']), 1)
        self.assertEqual(got['cross_partition_checks'], [])
        self.assertEqual(a.reduce(got, target, spans, supported(got))['verdict'], 'supported')

    def test_large_package_every_source_and_full_inventory_record_survives(self):
        self.assertGreater(self.plan['unpartitioned_request_chars'], self.limit)
        self.assertGreater(len(self.plan['coverage_manifest']), 1)
        owned = [r['ref'] for m in self.plan['coverage_manifest'] for r in m['source_ranges']]
        self.assertEqual(len(owned), len(set(owned)))
        self.assertEqual(set(owned), set(self.spans) - {'V0:0'})
        records = {}
        for t in self.plan['targets']:
            payload = c.audit_payload([t], self.spans)
            wire = EvidenceTransport(s.audit_schema([t]), payload)
            self.assertEqual(decode(wire.payload), payload)
            self.assertTrue(all(v['kind'] == 'package' for v in payload['spans'].values()))
            self.assertEqual(s.audit_request_chars([t], self.spans), self.plan['request_chars'][t['id']])
            self.assertLessEqual(self.plan['request_chars'][t['id']], self.limit)
            for key, row in zip(t['audit_partition']['requirement_ids'], t['value']['requirements']):
                self.assertEqual(row, self.target['value']['requirements'][int(key[1:])])
                records[key] = row
        self.assertEqual(len(records), 12)

    def test_all_pairs_of_source_ranges_are_checked_together(self):
        parts = self.plan['coverage_manifest']
        expected = {tuple(pair) for pair in combinations([p['partition_id'] for p in parts], 2)}
        self.assertEqual({tuple(r['partition_ids']) for r in self.plan['cross_partition_checks']}, expected)
        for left, right in combinations(self.spans.keys() - {'V0:0'}, 2):
            self.assertTrue(any({left, right}.issubset(t['audit_partition']['primary_refs']) for t in self.plan['targets']))

    def test_missing_duplicate_reordered_or_changed_range_fails(self):
        for variant in ('missing', 'duplicate', 'order', 'offset', 'hash'):
            got = deepcopy(self.plan)
            rows = got['coverage_manifest'][0]['source_ranges']
            if variant == 'missing':
                rows.pop()
            elif variant == 'duplicate':
                rows.append(deepcopy(rows[0]))
            elif variant == 'order':
                got['coverage_manifest'].reverse()
            elif variant == 'offset':
                rows[0]['start'] += 1
            else:
                rows[0]['sha256'] = 'forged'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                a.reduce(got, self.target, self.spans, supported(got))

    def test_missing_cross_receipt_is_not_a_pass(self):
        got = deepcopy(self.plan)
        checks = supported(got)
        del checks[got['cross_partition_checks'][0]['target_id']]
        with self.assertRaisesRegex(ValueError, 'every immutable target'):
            a.reduce(got, self.target, self.spans, checks)

    def test_negative_or_uncertain_partition_cannot_pass_reduce(self):
        for verdict in ('unsupported', 'uncertain'):
            got = deepcopy(self.plan)
            checks = supported(got)
            checks[got['targets'][0]['id']] = {'verdict': verdict, 'reason': 'Uncited exception omitted.'}
            result = a.reduce(got, self.target, self.spans, checks)
            self.assertEqual(result['verdict'], 'unsupported')
            self.assertFalse(got['coverage_manifest'][0]['passed'])

    def test_cross_range_rejection_blocks_even_when_every_map_passes(self):
        got = deepcopy(self.plan)
        checks = supported(got)
        checks[got['cross_partition_checks'][0]['target_id']] = {'verdict': 'unsupported', 'reason': 'Amendment exception flattened.'}
        self.assertEqual(a.reduce(got, self.target, self.spans, checks)['verdict'], 'unsupported')
        self.assertTrue(all(r['passed'] for r in got['coverage_manifest']))
        self.assertFalse(all(r['passed'] for r in got['cross_partition_checks']))

    def test_all_receipts_required_even_if_manifest_is_prechecked(self):
        got = deepcopy(self.plan)
        for row in got['coverage_manifest']:
            row.update(verdict='supported', passed=True)
        with self.assertRaises(ValueError):
            a.reduce(got, self.target, self.spans, {})

    def test_changed_source_inventory_or_removed_component_invalidates_plan(self):
        changed = deepcopy(self.spans)
        changed['D0:0']['text'] = changed['D0:0']['text'].replace('not 72', '72')
        with self.assertRaises(ValueError):
            a.reduce(deepcopy(self.plan), self.target, changed, supported(self.plan))
        target = deepcopy(self.target)
        target['value']['requirements'][0]['components'] = []
        with self.assertRaisesRegex(ValueError, 'identity'):
            a.reduce(deepcopy(self.plan), target, self.spans, supported(self.plan))
        got = deepcopy(self.plan)
        got['targets'][0]['value']['requirements'][0]['components'] = []
        with self.assertRaises(ValueError):
            a.reduce(got, self.target, self.spans, supported(got))

    def test_uncited_source_and_context_only_package_are_not_dropped(self):
        target, spans = fixture(30)
        target['value']['requirements'] = []
        got = a.prepare(target, spans, max_chars=len(s.audit_prompt([{'kind': 'package_coverage', 'audit_partition': {}}])) + 4000)
        self.assertEqual(sum(len(m['source_ranges']) for m in got['coverage_manifest']), 30)
        self.assertTrue(all(not t['value']['requirements'] for t in got['targets']))

    def test_precedence_dependencies_retain_both_records_and_source_documents(self):
        target, spans = fixture(12)
        spans['D11:0']['document_id'] = 'amendment'
        target['value']['requirements'][11]['supersedes'] = [0]
        got = a.prepare(target, spans, max_chars=self.limit)
        maps = [t for t in got['targets'] if t['audit_partition']['mode'] == 'range']
        owner = next(t for t in maps if 'D11:0' in t['audit_partition']['primary_refs'])
        self.assertIn('R0', owner['audit_partition']['requirement_ids'])
        self.assertIn('D0:0', c.audit_payload([owner], spans)['spans'])

    def test_private_unknown_anchor_and_unaccounted_inventory_field_fail(self):
        for variant in ('private', 'unknown', 'field'):
            target, spans = fixture(1)
            if variant == 'field':
                target['value']['unexpected'] = 'Must not discard this.'
            else:
                target['value']['requirements'][0]['focus'][0]['ref'] = 'V0:0' if variant == 'private' else 'nope'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                a.prepare(target, spans)

    def test_no_silent_truncation_of_indivisible_dependency(self):
        target, spans = fixture(1)
        spans['D0:0']['text'] += 'x' * 640001
        before = deepcopy((target, spans))
        with self.assertRaisesRegex(ValueError, 'Indivisible.*No source'):
            a.prepare(target, spans)
        self.assertEqual((target, spans), before)

    def test_prompt_scope_and_batching_are_explicit_without_changing_semantic_rules(self):
        batches = list(s.audit_batches(self.plan['targets'], self.spans, max_chars=self.limit))
        self.assertTrue(all(len(b) == 1 for b in batches))
        base = s.audit_prompt([{'kind': 'package_coverage'}])
        for t in self.plan['targets']:
            self.assertTrue(s.audit_prompt([t]).startswith(base))
            self.assertIn(a.PARTITION_INSTRUCTIONS, s.audit_prompt([t]))

    def test_impossible_preflight_makes_zero_comparator_calls(self):
        from tests.test_requirement_routing import IntegrationTests
        with patch.object(a, 'prepare', side_effect=ValueError('Indivisible coverage dependency')):
            result, state, calls, _ = IntegrationTests().run_fixture()
        self.assertEqual(calls, [])
        self.assertEqual(state['status'], 'TECHNICAL_BLOCKED')
        self.assertFalse(state['research_authorized'])
        self.assertFalse(any(s['stage'].startswith('component-') for s in result['understanding_audit']['stages']))

    def test_manifest_persists_on_completed_pipeline(self):
        from tests.test_requirement_routing import IntegrationTests
        result, state, _, _ = IntegrationTests().run_fixture()
        self.assertEqual(state['status'], 'READY')
        manifest = result['understanding_audit']['coverage_manifest']
        self.assertTrue(manifest)
        self.assertTrue(all(r['passed'] for r in manifest))

    def test_all_153_pages_including_uncited_pages_are_accounted(self):
        target = {'id': 'package-coverage', 'kind': 'package_coverage',
                  'value': {'requirements': [], 'quoted_vendor_context': []}}
        spans = {}
        for page in range(1, 154):
            text = f'Page {page}. Original unabridged text.'
            offset = (page - 1) * 100
            spans[f'D{page}:0'] = {'kind': 'package', 'source_id': f'D{page}', 'document_id': 'book',
                                  'source_offset': offset, 'offset': 0, 'text': text,
                                  'text_regions': [{'start': offset, 'end': offset + len(text),
                                                    'page_number': page, 'basis': 'native_text'}]}
        got = a.prepare(target, spans, max_chars=30000)
        self.assertGreater(len(got['coverage_manifest']), 1)
        pages = [loc['page_number'] for m in got['coverage_manifest'] for r in m['source_ranges'] for loc in r['locations']]
        self.assertEqual(pages, list(range(1, 154)))
        self.assertEqual(a.reduce(got, target, spans, supported(got))['verdict'], 'supported')

    def test_three_document_precedence_chain_is_not_reduced_to_disconnected_pairs(self):
        target, spans = fixture(3)
        for i in range(3):
            spans[f'D{i}:0']['document_id'] = f'edition-{i}'
        target['value']['requirements'][2]['supersedes'] = [1]
        target['value']['requirements'][1]['supersedes'] = [0]
        layout = a._Layout(target, spans)
        check = layout.make([['D2:0']], ['P0'], 'range')
        self.assertEqual(check['audit_partition']['requirement_ids'], ['R0', 'R1', 'R2'])
        self.assertEqual(set(c.audit_payload([check], spans)['spans']), {'D0:0', 'D1:0', 'D2:0'})

    def test_cross_fragment_context_keeps_numbers_and_negation(self):
        target, spans = fixture(2, contiguous=True)
        layout = a._Layout(target, spans)
        check = layout.make([['D0:0']], ['P0'], 'range')
        self.assertIn('D1:0', check['audit_partition']['source_refs'])
        payload = c.audit_payload([check], spans)
        self.assertEqual(payload['spans']['D0:0']['text'], spans['D0:0']['text'])
        self.assertIn('12 hours, not 72 hours', payload['spans']['D0:0']['text'])

    def test_dense_neighbor_dependencies_block_instead_of_dropping_records(self):
        target, spans = fixture(12, contiguous=True)
        with self.assertRaisesRegex(ValueError, 'Indivisible coverage dependency'):
            a.prepare(target, spans, max_chars=self.limit)

    def test_budget_and_cross_partition_labels_cannot_be_tampered(self):
        for variant in ('budget', 'pair', 'drop_pair'):
            got = deepcopy(self.plan)
            if variant == 'budget':
                got['max_chars'] = 640001
            elif variant == 'pair':
                got['cross_partition_checks'][0]['partition_ids'] = ['P99', 'P100']
            else:
                got['cross_partition_checks'].pop()
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                a.reduce(got, self.target, self.spans, supported(got))

    def test_partitioned_pipeline_reduces_and_rejects_without_renderer_bypass(self):
        from tests.test_requirement_routing import IntegrationTests
        real_size, real_validate = s.audit_request_chars, s.validate_audit

        def force_branch(rows, *args, **kwargs):
            size = real_size(rows, *args, **kwargs)
            if len(rows) == 1 and rows[0].get('id') == 'package-coverage' and 'audit_partition' not in rows[0]:
                return 640001  # Exercise partition path with the small synthetic integration packet.
            return size

        for reject in (False, True):
            def validate(raw, records):
                if reject and any(r.get('audit_partition', {}).get('mode') == 'cross_range' for r in records):
                    raw = deepcopy(raw)
                    raw['checks'][records[0]['id']] = {'verdict': 'unsupported', 'reason': 'Synthetic cross-document exception omitted.'}
                return real_validate(raw, records)
            with patch.object(s, 'audit_request_chars', side_effect=force_branch), patch.object(s, 'validate_audit', side_effect=validate):
                result, state, calls, _ = IntegrationTests().run_fixture()
            audit = result['understanding_audit']
            self.assertTrue(audit['source_audit_preflight']['completed_before_comparison'])
            comparison_indexes = [i for i, stage in enumerate(audit['stages']) if stage['stage'].startswith('component-')]
            if reject:
                self.assertEqual(comparison_indexes, [])
            else:
                self.assertTrue(comparison_indexes)
                self.assertLessEqual(audit['source_audit_preflight']['after_stage_count'], comparison_indexes[0])
            self.assertTrue(audit['coverage_partition_audit']['cross_partition_checks'])
            self.assertEqual(state['status'], 'TECHNICAL_BLOCKED' if reject else 'READY')
            self.assertEqual(state['research_authorized'], not reject)
            self.assertEqual(audit['claim_evidence']['passed'], not reject)
            self.assertEqual(bool(calls), not reject)

    def test_package_reference_is_distinct_and_provenance_is_not_merged_with_profile(self):
        target, spans = fixture(12)
        quote = spans['D0:0']['text'][:40]
        spans['V0:0']['text'] = quote
        target['value']['quoted_vendor_context'] = [{'meaning': 'Quoted reference, not a duty.',
                                                    'evidence': [{'ref': 'D0:0', 'quote': quote}]}]
        got = a.prepare(target, spans, max_chars=self.limit + 5000)
        contexts = [t['value']['quoted_vendor_context'] for t in got['targets']]
        self.assertTrue(any(rows == target['value']['quoted_vendor_context'] for rows in contexts))
        for t in got['targets']:
            self.assertNotIn('V0:0', c.audit_payload([t], spans)['spans'])


if __name__ == '__main__':
    unittest.main()
