"""Exact serialized budgets, including evidence, prompts, schemas and escaping."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_plan as s, semantic_contract as c
from common.evidence_selection import EvidenceTransport, SELECTION_PROMPT
from common.understanding_checkpoints import check_request_budget


def size(batch, spans, answers=None, previous_questions=None, independent_questions=None):
    payload = c.audit_payload(batch, spans, answers, previous_questions, independent_questions)
    wire = EvidenceTransport(s.audit_schema(batch), payload)
    prompt = s.audit_prompt(batch) + ('\n' + SELECTION_PROMPT if wire.active else '')
    return check_request_budget(prompt, wire.payload, wire.schema, 10**9)


def record(i, text='Source-backed claim.', kind='claim'):
    return {'id': f'T{i}', 'kind': kind, 'value': {'meaning': text}}


class AuditSizingTests(unittest.TestCase):
    def test_empty_has_no_request(self):
        self.assertEqual(list(s.audit_batches([], {})), [])

    def test_not_a_record_count_batcher(self):
        rows = [record(i) for i in range(30)]
        self.assertEqual(list(s.audit_batches(rows, {})), [rows])

    def test_full_payload_not_just_records_controls_split(self):
        spans = {'V0': {'kind': 'profile', 'text': 's' * 380000}}
        rows = [record(i, 'r' * 90000) for i in range(3)]
        before = deepcopy((rows, spans))
        self.assertGreater(size(rows, spans), 640000)
        batches = list(s.audit_batches(rows, spans))
        self.assertEqual([len(b) for b in batches], [2, 1])
        self.assertEqual([r for b in batches for r in b], rows)
        self.assertEqual((rows, spans), before)
        self.assertTrue(all(size(b, spans) <= 640000 for b in batches))

    def test_exact_boundary_allowed_one_less_splits(self):
        rows = [record(0), record(1)]
        bound = size(rows, {})
        self.assertEqual(list(s.audit_batches(rows, {}, max_chars=bound)), [rows])
        self.assertEqual(list(s.audit_batches(rows, {}, max_chars=bound - 1)), [[rows[0]], [rows[1]]])

    def test_singleton_overflow_has_id_size_and_no_truncation(self):
        rows = [record(0, 'x' * 640001)]
        before = deepcopy(rows)
        required = size(rows, {})
        with self.assertRaisesRegex(ValueError, rf'T0.*{required}.*640000'):
            list(s.audit_batches(rows, {}))
        self.assertEqual(rows, before)

    def test_context_only_overflow_still_blocks_small_target(self):
        spans = {'V0': {'kind': 'profile', 'text': 'x' * 640000}}
        with self.assertRaisesRegex(ValueError, 'T0'):
            list(s.audit_batches([record(0)], spans))

    def test_json_escaping_counts_not_raw_character_length(self):
        rows = [record(i, ('\u201cquoted\u201d\\\n' * 20)) for i in range(2)]
        bound = size(rows, {}) - 1
        self.assertEqual(len(list(s.audit_batches(rows, {}, max_chars=bound))), 2)
        self.assertGreater(size(rows, {}), sum(len(r['value']['meaning']) for r in rows))

    def test_all_context_channels_are_budgeted(self):
        rows = [record(0), record(1)]
        context = {'answers': [{'answer': 'a' * 1000}], 'previous_questions': [{'question': 'q' * 500}]}
        bound = size(rows, {}, **context) - 1
        batches = list(s.audit_batches(rows, {}, max_chars=bound, **context))
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(size(b, {}, **context) <= bound for b in batches))
        coverage = [record(2, kind='coverage')]
        iq = [{'question': 'i' * 1000}]
        bound = size(coverage, {}, independent_questions=iq) - 1
        with self.assertRaisesRegex(ValueError, 'T2'):
            list(s.audit_batches(coverage, {}, max_chars=bound, independent_questions=iq))

    def test_kinds_remain_isolated_and_sources_keep_their_roles(self):
        rows = [record(0, kind='requirement'), record(1), record(2, kind='requirement')]
        spans = {'D0': {'kind': 'package', 'text': 'Official source'},
                 'V0': {'kind': 'profile', 'text': 'Private source'}}
        batches = list(s.audit_batches(rows, spans))
        self.assertEqual([len(b) for b in batches], [1, 1, 1])
        for batch in batches:
            payload = c.audit_payload(batch, spans)
            if batch[0]['kind'] == 'requirement':
                self.assertEqual(set(payload['spans']), {'D0'})
            else:
                self.assertEqual(set(payload['spans']), set(spans))

    def test_bad_limit_duplicate_id_or_unknown_kind_fail(self):
        for limit in (0, -1, True, 3.5, 640001):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                list(s.audit_batches([record(0)], {}, max_chars=limit))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            list(s.audit_batches([record(0), record(0)], {}))
        with self.assertRaises(ValueError):
            list(s.audit_batches([record(0, kind='invented')], {}))

    def test_orchestrator_uses_same_budget_and_payload_for_every_audit_request(self):
        from tests.test_requirement_routing import IntegrationTests
        with patch.object(s, 'audit_batches', wraps=s.audit_batches) as batching:
            result, state, _, _ = IntegrationTests().run_fixture()
        self.assertEqual(state['status'], 'READY')
        self.assertEqual(batching.call_count, 2)
        batches = []
        sizes = []
        for args, kwargs in batching.call_args_list:
            self.assertEqual(kwargs['max_chars'], 640000)
            current = list(s.audit_batches(*args, **kwargs))
            batches.extend(current)
            sizes.extend(size(b, *args[1:]) for b in current)
        self.assertTrue(all(r['kind'] != 'comparison' for r in batching.call_args_list[0].args[0]))
        self.assertTrue(all(r['kind'] == 'comparison' for r in batching.call_args_list[1].args[0]))
        stages = [r for r in result['understanding_audit']['stages'] if r['stage'].startswith('claim-evidence-')]
        self.assertEqual(len(stages), len(batches))
        for stage, required_size in zip(stages, sizes):
            self.assertEqual(stage['request_chars'], required_size)

    def test_oversized_target_stops_before_any_independent_audit_spend(self):
        from tests.test_requirement_routing import IntegrationTests
        with patch.object(s, 'audit_batches', side_effect=ValueError('Audit target T0 exceeds 640000 characters')):
            result, state, _, _ = IntegrationTests().run_fixture()
        self.assertEqual(state['status'], 'TECHNICAL_BLOCKED')
        self.assertFalse(state['research_authorized'])
        self.assertFalse(any(r['stage'].startswith('claim-evidence-') for r in result['understanding_audit']['stages']))


if __name__ == '__main__':
    unittest.main()
