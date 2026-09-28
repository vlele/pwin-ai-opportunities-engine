"""Lossless coverage encoding: source completeness, not semantic verdicts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import audit_evidence_encoding as encoding
from common import semantic_contract as contract, semantic_plan as plan
from common.evidence_selection import EvidenceTransport


def fixture():
    text = 'Do not waive the 12-hour requirement. ' + 'Exact source text; ' * 80
    spans = {
        'D0:0': {'kind': 'package', 'source_id': 'D0', 'document_id': 'scope',
                 'source_offset': 0, 'offset': 0, 'filename': 'scope.pdf', 'text': text},
        'D1:0': {'kind': 'package', 'source_id': 'D1', 'document_id': 'amendment',
                 'source_offset': 0, 'offset': 0, 'filename': 'amendment.pdf', 'text': text},
        'D2:0': {'kind': 'package', 'source_id': 'D2', 'offset': 0,
                 'text': 'Uncited exception: only the alternate track uses 72 hours.'},
    }
    anchor = {'ref': 'D0:0', 'quote': text}
    req = {'status': 'current', 'record_kind': 'requirement', 'logic': 'all',
           'supersedes': [], 'meaning': 'Do not waive the 12-hour requirement.',
           'focus': [deepcopy(anchor)], 'evidence': [deepcopy(anchor)],
           'components': [{'kind': 'timing', 'text': '12 hours', 'evidence': [deepcopy(anchor)]}
                          for _ in range(8)]}
    rows = [{'id': 'package-coverage', 'kind': 'package_coverage',
             'value': {'requirements': [req], 'quoted_vendor_context': [
                 {'meaning': 'A package-provided reference.', 'evidence': [deepcopy(anchor)]}]}}]
    return {'targets': rows, 'spans': spans}


class CoverageEncodingTests(unittest.TestCase):
    def test_exact_round_trip_without_mutating_input(self):
        raw = fixture()
        before = deepcopy(raw)
        wire = encoding.encode(raw)
        self.assertEqual(raw, before)
        self.assertNotEqual(wire, raw)
        self.assertLess(len(json.dumps(wire)), len(json.dumps(raw)))
        self.assertEqual(encoding.decode(wire), raw)
        self.assertEqual(wire['spans'], raw['spans'])
        self.assertEqual(set(wire['spans']), {'D0:0', 'D1:0', 'D2:0'})

    def test_each_anchor_is_stored_once_and_all_occurrences_remain(self):
        raw = fixture()
        wire = encoding.encode(raw)
        self.assertEqual(len(wire['evidence_registry']), 1)
        req = wire['targets'][0]['value']['requirements'][0]
        self.assertEqual(req['focus'], req['evidence'])
        self.assertEqual(len(req['components']), 8)
        self.assertEqual(req['components'][0]['evidence'], req['focus'])
        self.assertEqual(len(encoding.decode(wire)['targets']), 1)

    def test_identical_words_at_different_sources_never_share_identity(self):
        raw = fixture()
        other = deepcopy(raw['targets'][0]['value']['requirements'][0])
        for anchor in other['focus'] + other['evidence'] + [a for p in other['components'] for a in p['evidence']]:
            anchor['ref'] = 'D1:0'
        other['status'] = 'superseded'
        raw['targets'][0]['value']['requirements'].append(other)
        wire = encoding.encode(raw)
        self.assertEqual(len(wire['evidence_registry']), 2)
        self.assertEqual(encoding.decode(wire), raw)

    def test_numbers_negations_whitespace_and_unicode_are_not_normalized(self):
        raw = fixture()
        strings = ['Do NOT waive 12 hours.\r\n', 'Do waive 12 hours.\n',
                   'Do NOT waive 72 hours.\n', '8 1/2" x 11" & < > \'quoted\' \u2014 \u00e9']
        raw['spans']['D3:0'] = {'kind': 'package', 'text': '\n'.join(strings)}
        parts = raw['targets'][0]['value']['requirements'][0]['components']
        for text in strings:
            parts.extend([{'text': text, 'evidence': [{'ref': 'D3:0', 'quote': text}]} for _ in range(4)])
        self.assertEqual(encoding.decode(encoding.encode(raw)), raw)

    def test_changed_quote_source_record_or_record_order_fails_integrity(self):
        for variant in ('quote', 'span', 'component', 'order', 'missing_source'):
            raw = fixture()
            second = deepcopy(raw['targets'][0]['value']['requirements'][0])
            second['status'] = 'superseded'
            raw['targets'][0]['value']['requirements'].append(second)
            wire = encoding.encode(raw)
            value = wire['targets'][0]['value']
            if variant == 'quote':
                next(iter(wire['evidence_registry'].values()))['quote'] = 'Altered quotation.'
            elif variant == 'span':
                wire['spans']['D0:0']['text'] = 'Altered source.'
            elif variant == 'component':
                value['requirements'][0]['components'][0]['text'] = '72 hours'
            elif variant == 'order':
                value['requirements'].reverse()
            else:
                del wire['spans']['D2:0']
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                encoding.decode(wire)

    def test_unknown_reference_and_unused_registry_entry_fail(self):
        wire = encoding.encode(fixture())
        del wire['evidence_registry'][next(iter(wire['evidence_registry']))]
        with self.assertRaises(ValueError):
            encoding.decode(wire)
        wire = encoding.encode(fixture())
        unused = {'ref': 'D2:0', 'quote': wire['spans']['D2:0']['text']}
        wire['evidence_registry']['E' + encoding._digest(unused)] = unused
        with self.assertRaisesRegex(ValueError, 'unused'):
            encoding.decode(wire)

    def test_registry_cycles_and_external_pointers_are_rejected(self):
        for pointer in ('#/evidence_registry/unknown', 'https://example.invalid/source', '#/spans/D0:0'):
            wire = encoding.encode(fixture())
            wire['targets'][0]['value']['requirements'][0]['focus'][0] = {'$ref': pointer}
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                encoding.decode(wire)
        wire = encoding.encode(fixture())
        key = next(iter(wire['evidence_registry']))
        wire['evidence_registry'][key] = {'$ref': '#/evidence_registry/' + key}
        with self.assertRaises(ValueError):
            encoding.decode(wire)

    def test_uncited_private_source_is_not_leaked_by_encoder(self):
        raw = fixture()
        raw['spans']['V0:0'] = {'kind': 'profile', 'text': 'Private profile.'}
        with self.assertRaisesRegex(ValueError, 'package-only'):
            encoding.encode(raw)

    def test_original_metadata_and_non_anchor_objects_are_untouched(self):
        raw = fixture()
        raw['spans']['D0:0']['text_regions'] = [{'start': 0, 'end': 12, 'page_number': 3, 'basis': 'native_text'}]
        raw['targets'][0]['value']['extra'] = {'ref': 'An ordinary field', 'other': 'Do not reinterpret me'}
        wire = encoding.encode(raw)
        self.assertEqual(encoding.decode(wire), raw)
        self.assertEqual(wire['spans'], raw['spans'])
        self.assertEqual(wire['targets'][0]['value']['extra'], raw['targets'][0]['value']['extra'])

    def test_digest_collision_fails_instead_of_merging_different_sources(self):
        raw = fixture()
        req = raw['targets'][0]['value']['requirements'][0]
        req['evidence'].append({'ref': 'D1:0', 'quote': raw['spans']['D1:0']['text']})
        with patch.object(encoding, '_digest', return_value='collision'), self.assertRaisesRegex(ValueError, 'collision'):
            encoding.encode(raw)

    def test_invalid_private_unknown_or_changed_anchor_fails_before_encoding(self):
        for variant in ('private', 'unknown', 'quote'):
            raw = fixture()
            if variant == 'private':
                raw['spans']['D0:0']['kind'] = 'profile'
            elif variant == 'unknown':
                del raw['spans']['D0:0']
            else:
                raw['targets'][0]['value']['requirements'][0]['focus'][0]['quote'] = 'Not in the source.'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                encoding.encode(raw)

    def test_short_or_noncoverage_requests_keep_original_representation(self):
        raw = fixture()
        raw['targets'][0]['kind'] = 'requirement'
        self.assertEqual(encoding.encode(raw), raw)
        tiny = {'targets': [{'id': 'package-coverage', 'kind': 'package_coverage',
                             'value': {'requirements': []}}], 'spans': {}}
        self.assertEqual(encoding.encode(tiny), tiny)

    def test_reserved_keys_cannot_be_smuggled_into_an_unencoded_request(self):
        raw = fixture()
        raw['evidence_registry'] = {'fake': {}}
        with self.assertRaises(ValueError):
            encoding.encode(raw)
        raw = fixture()
        raw['targets'][0]['value']['injected'] = {'$ref': '#/evidence_registry/fake'}
        with self.assertRaises(ValueError):
            encoding.encode(raw)

    def test_large_synthetic_coverage_fits_without_losing_any_source_or_component(self):
        raw = fixture()
        raw['spans']['D2:0']['text'] += 'Uncited source context. ' * 19500
        row = raw['targets'][0]['value']['requirements'][0]
        row['components'] *= 18
        self.assertGreater(len(json.dumps(raw)), 640000)
        encoded = encoding.encode(raw)
        self.assertLess(len(json.dumps(encoded)), 640000)
        self.assertEqual(encoding.decode(encoded), raw)

    def test_transport_compacts_but_does_not_change_verdict_schema_or_source_roles(self):
        raw = fixture()
        schema = plan.audit_schema(raw['targets'])
        transport = EvidenceTransport(schema, raw)
        self.assertEqual(encoding.decode(transport.payload), raw)
        self.assertEqual(transport.schema, schema)
        self.assertFalse(transport.active)
        self.assertIn('evidence_registry', transport.payload)
        self.assertEqual(transport.audit_evidence_encoding['format'], encoding.FORMAT)
        failed = plan.validate_audit({'checks': {'package-coverage': {
            'verdict': 'unsupported', 'reason': 'The uncited exception is missing.'}}}, raw['targets'])
        self.assertFalse(failed['passed'])
        self.assertEqual(failed['targets'], raw['targets'])

    def test_sizing_and_actual_transport_use_identical_encoding(self):
        from common.understanding_checkpoints import request_chars
        raw = fixture()
        wire = EvidenceTransport(plan.audit_schema(raw['targets']), contract.audit_payload(raw['targets'], raw['spans']))
        self.assertEqual(plan.audit_request_chars(raw['targets'], raw['spans']),
                         request_chars(plan.audit_prompt(raw['targets']), wire.payload, wire.schema))
        self.assertEqual(list(plan.audit_batches(raw['targets'], raw['spans'])), [raw['targets']])

    def test_truly_oversized_distinct_sources_still_hard_fail(self):
        raw = fixture()
        raw['spans']['D2:0']['text'] = 'x' * 640000
        with self.assertRaisesRegex(ValueError, 'package-coverage.*No target or evidence was truncated'):
            list(plan.audit_batches(raw['targets'], raw['spans']))

    def test_changed_representation_changes_checkpoint_key(self):
        from common.understanding_checkpoints import StageCheckpoints
        raw = fixture()
        schema = plan.audit_schema(raw['targets'])
        prompt = plan.audit_prompt(raw['targets'])
        with tempfile.TemporaryDirectory() as folder:
            store = StageCheckpoints(folder, scope={}, runtime='test')
            self.assertNotEqual(store.key('audit', prompt, raw, schema, {}),
                                store.key('audit', prompt, encoding.encode(raw), schema, {}))


class PipelineEncodingTests(unittest.TestCase):
    def provider(self):
        from tests import test_question_channel as q
        spans, inv, signal = q.fixture()
        text = 'Inspect the cooling units. ' + 'Retain the exact inspection records. ' * 25
        spans['D1:0']['text'] = text

        def extend(value):
            if isinstance(value, dict):
                if set(value) == {'ref', 'quote'} and value['ref'] == 'D1:0':
                    value['quote'] = text
                else:
                    for child in value.values():
                        extend(child)
            elif isinstance(value, list):
                for child in value:
                    extend(child)

        extend(inv)
        with patch.object(q, 'fixture', return_value=(spans, inv, signal)):
            return q.pipeline_model()

    def test_real_invoke_receipt_matches_transmitted_payload_and_preserves_audit_graph(self):
        from common import capture_understanding as u
        model, calls, packet = self.provider()
        result = u.analyze_packet(packet, [], {}, call=model)
        self.assertNotIn('pipeline_errors', result)
        payload = next(p for p in calls if p.get('audit_evidence_encoding'))
        receipt = encoding.receipt(payload)
        stage = next(s for s in result['understanding_audit']['stages'] if s.get('audit_payload_encoding'))
        self.assertEqual(stage['audit_payload_encoding'], receipt)
        self.assertTrue(receipt['round_trip_verified'])
        canonical = encoding.decode(payload)
        audited = next(t for t in result['understanding_audit']['claim_evidence']['targets']
                       if t['kind'] == 'package_coverage')
        self.assertEqual(canonical['targets'], [audited])
        self.assertEqual(set(canonical['spans']), {'D1:0'})

    def test_negative_coverage_verdict_still_blocks_and_is_not_resampled_on_restart(self):
        from common import capture_understanding as u, capture_clarification as gate
        model, _, packet = self.provider()
        checked_payloads = []

        def reject(**request):
            raw = model(**request)
            if request['user_payload'].get('audit_evidence_encoding'):
                checked_payloads.append(request['user_payload'])
                raw['checks']['package-coverage'] = {'verdict': 'unsupported', 'reason': 'Synthetic omitted scope; do not proceed.'}
            return raw

        with tempfile.TemporaryDirectory() as folder:
            result = u.analyze_packet(packet, [], {}, call=reject, checkpoint_dir=folder)
            state = gate.validate_assessment(result, packet)
            self.assertEqual(state['status'], 'TECHNICAL_BLOCKED')
            self.assertFalse(state['research_authorized'])
            self.assertEqual(len(checked_payloads), 1)
            again = u.analyze_packet(packet, [], {}, call=lambda **kw: self.fail('Do not resample rejected audit'), checkpoint_dir=folder)
            self.assertEqual(result['understanding_audit']['claim_evidence'], again['understanding_audit']['claim_evidence'])
            self.assertFalse(again['understanding_audit']['claim_evidence']['passed'])


if __name__ == '__main__':
    unittest.main()
