"""Provenance is not entailment; mock verdicts test gates, not model accuracy."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, semantic_plan as plan
from common.evidence_selection import EvidenceTransport
from test_inventory_handoff import response


def package(texts, statement, refs=None):
    offset, spans = 0, {}
    for i, text in enumerate(texts):
        ref = f'D{i}:0'
        spans[ref] = {'source_id': f'D{i}', 'document_id': 'synthetic-package',
                      'kind': 'package', 'source_offset': offset, 'offset': 0, 'text': text}
        offset += len(text)
    fact = {'area': 'scope', 'statement': statement, 'refs': refs or list(spans)}
    return h._batch({'F0': fact}, spans, 'package')


def select(batch, ref, quote=None):
    raw = response(batch)
    raw['requirements'][0]['focus'] = [{'ref': ref, 'quote': quote or batch['payload']['spans'][ref]['text']}]
    return raw


class ProvenanceContractTests(unittest.TestCase):
    def test_definition_can_select_sufficient_citation_without_discarding_lineage(self):
        batch = package(['CWP means Coastal Work Plan.\n', 'Invoices are due monthly.\n'],
                        'CWP means Coastal Work Plan.')
        raw = select(batch, 'D0:0')
        original = deepcopy((batch, raw))
        mapped = h.validate_batch(raw, batch)
        lineage = mapped['fact_provenance']['F0']
        self.assertEqual(lineage['ledger_refs'], ['D0:0', 'D1:0'])
        self.assertEqual(lineage['selected_refs'], ['D0:0'])
        self.assertEqual(lineage['unselected_ledger_refs'], ['D1:0'])
        target = h.handoff_targets(batch, mapped)[0]
        self.assertEqual(set(target['spans']), {'D0:0', 'D1:0'})
        self.assertEqual(target['provenance'], lineage)
        self.assertEqual(target['retained_records'][0]['evidence'], raw['requirements'][0]['focus'])
        self.assertEqual((batch, raw), original)

    def test_alternative_package_citation_requires_audit_not_matching_id(self):
        batch = package(['Period is three years.\n', 'Years of service: three.\n'],
                        'Period is three years.', ['D0:0'])
        # A second fact legitimately makes the alternative passage available.
        spans = {**batch['payload']['spans'], 'D1:0': {'source_id': 'D1',
            'document_id': 'synthetic-package', 'kind': 'package', 'offset': 0,
            'source_offset': 24, 'text': 'Years of service: three.\n'}}
        facts = {**batch['payload']['fact_ledger'], 'F1': {
            'area': 'scope', 'statement': 'Years of service: three.', 'refs': ['D1:0']}}
        batch = h._batch(facts, spans, 'package')
        raw = response(batch)
        raw['requirements'].pop(0)
        raw['requirements'][0]['originating_fact_ids'] = ['F0', 'F1']
        mapped = h.validate_batch(raw, batch)
        self.assertEqual(mapped['fact_provenance']['F0']['additional_selected_refs'], ['D1:0'])
        targets = h.handoff_targets(batch, mapped)
        self.assertIn('D0:0', targets[0]['spans'])
        self.assertEqual(targets[0]['fact'], facts['F0'])

    def test_provenance_cannot_be_supplied_by_model(self):
        batch = package(['The term is 42 months.'], 'The term is 42 months.')
        raw = response(batch)
        raw['fact_provenance'] = {'F0': {'ledger_refs': []}}
        with self.assertRaises(ValueError):
            h.validate_batch(raw, batch)

    def test_bad_quotation_and_wrong_source_role_still_fail(self):
        batch = package(['Subscriber means the purchaser only.'], 'Subscriber means the purchaser only.')
        for mode in ('changed', 'unknown', 'private'):
            b = deepcopy(batch)
            raw = response(b)
            if mode == 'changed':
                raw['requirements'][0]['focus'][0]['quote'] = 'Subscriber includes all suppliers.'
            elif mode == 'unknown':
                raw['requirements'][0]['focus'][0]['ref'] = 'D99:0'
            else:
                b['payload']['spans']['D0:0']['kind'] = 'profile'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                h.validate_batch(raw, b)

    def test_unknown_identity_error_identifies_fact_and_record(self):
        batch = package(['Deliver the report.'], 'Deliver the report.')
        raw = response(batch)
        raw['requirements'][0]['originating_fact_ids'] = ['F8']
        with self.assertRaises(ValueError) as error:
            h.validate_batch(raw, batch)
        self.assertIn('F8', str(error.exception))
        self.assertIn('requirements[0]', str(error.exception))

    def test_missing_fact_error_identifies_exact_id(self):
        batch = package(['Deliver the report.'], 'Deliver the report.')
        raw = response(batch)
        raw['requirements'].clear()
        with self.assertRaises(ValueError) as error:
            h.validate_batch(raw, batch)
        self.assertIn('F0', str(error.exception))

    def test_interning_keeps_each_facts_source_lineage(self):
        batch = package(['CWP means Coastal Work Plan.\n', 'Invoices are due monthly.'],
                        'CWP means Coastal Work Plan.')
        batch['payload']['fact_ledger']['F1'] = deepcopy(batch['payload']['fact_ledger']['F0'])
        raw = response(batch)
        for record in raw['requirements']:
            record['focus'] = [{'ref': 'D0:0', 'quote': batch['payload']['spans']['D0:0']['text']}]
        mapped = h.validate_batch(raw, batch)
        inventory, receipt = h.merge([(batch, mapped)], batch['payload']['spans'])
        self.assertEqual(len(inventory['requirements']), 1)
        self.assertEqual(set(receipt['fact_provenance']), {'F0', 'F1'})
        self.assertEqual(receipt['fact_provenance']['F0']['ledger_refs'], ['D0:0', 'D1:0'])
        self.assertEqual(receipt['fact_coverage']['F0'], receipt['fact_coverage']['F1'])


class SemanticGateTests(unittest.TestCase):
    def test_supported_definition_completes_handoff_without_extra_evidence(self):
        batch = package(['CWP means Coastal Work Plan.\n', 'Invoices are due monthly.'],
                        'CWP means Coastal Work Plan.')
        raw = select(batch, 'D0:0')
        def invoke(stage, prompt, payload, schema, validator):
            if stage.startswith('semantic-inventory-package-'):
                return validator(raw)
            self.assertIn('D1:0', payload['targets'][0]['spans'])
            return validator({'checks': {t['id']: {'verdict': 'supported',
                'reason': 'The selected definition retains the complete meaning.'} for t in payload['targets']}})
        receipts = []
        inventory = h.build(list(batch['payload']['fact_ledger'].values()), batch['payload']['spans'], invoke, receipts)
        self.assertTrue(receipts[-1]['passed'])
        self.assertEqual(inventory['requirements'][0]['evidence'], raw['requirements'][0]['focus'])
        merged = next(r for r in receipts if r['event'] == 'inventory_merged')
        self.assertEqual(merged['fact_provenance']['F0']['ledger_refs'], ['D0:0', 'D1:0'])

    def check_rejection(self, batch, raw, reason, verdict='unsupported'):
        def invoke(stage, prompt, payload, schema, validator):
            if stage.startswith('semantic-inventory-package-'):
                return validator(raw)
            self.assertTrue(stage.startswith('inventory-handoff-audit-'))
            target = payload['targets'][0]
            self.assertEqual(target['fact'], batch['payload']['fact_ledger']['F0'])
            self.assertEqual(target['retained_records'][0]['evidence'], raw['requirements'][0]['focus'])
            self.assertEqual(set(target['spans']), set(batch['payload']['spans']))
            return validator({'checks': {t['id']: {'verdict': verdict, 'reason': reason}
                                         for t in payload['targets']}})
        receipts = []
        with self.assertRaisesRegex(ValueError, 'Inventory handoff audit failed'):
            h.build(list(batch['payload']['fact_ledger'].values()), batch['payload']['spans'], invoke, receipts)
        self.assertEqual(receipts[-1]['event'], 'handoff_audited')
        self.assertFalse(receipts[-1]['passed'])

    def test_cropped_obligation_reaches_auditor_without_synthetic_evidence(self):
        batch = package(['The supplier shall provide exactly two li',
                         'censed surveyors during every field shift.'],
                        'The supplier shall provide exactly two licensed surveyors during every field shift.')
        raw = select(batch, 'D1:0')
        self.check_rejection(batch, raw, 'Selected passage omits the actor, two-person constraint and part of licensed.')

    def test_definitions_have_no_blanket_exemption(self):
        for suffix in ('only; subcontractors are excluded.', 'unless written permission is issued.',
                       'not an affiliate or reseller.'):
            text = 'Subscriber means the named purchaser ' + suffix
            batch = package([text], text)
            raw = select(batch, 'D0:0', 'Subscriber means the named purchaser')
            with self.subTest(suffix=suffix):
                self.check_rejection(batch, raw, 'Material definition limiter was omitted.')

    def test_same_ref_and_fact_id_never_override_uncertain_audit(self):
        batch = package(['Provide up to seven samples, not eight.'], 'Provide up to seven samples, not eight.')
        self.check_rejection(batch, select(batch, 'D0:0', 'Provide up to seven samples'),
                             'The selected proposition is incomplete.', verdict='uncertain')

    def test_unrelated_source_mapping_cannot_pass_on_lineage_alone(self):
        batch = package(['Provide three calibrated probes.\n', 'Invoices are due monthly.\n'],
                        'Provide three calibrated probes.')
        self.check_rejection(batch, select(batch, 'D1:0'), 'The selected passage is unrelated to the fact.')

    def test_adjacent_selection_retains_constraint_verbatim(self):
        batch = package(['Provide exactly two li', 'censed surveyors.'],
                        'Provide exactly two licensed surveyors.')
        wire = EvidenceTransport(batch['schema'], batch['payload'])
        raw = response(batch)
        raw['requirements'][0]['focus'] = [{'start': {'ref': 'D0:0', 'line': 1},
                                            'end': {'ref': 'D1:0', 'line': 1}}]
        decoded = wire.resolve(raw)
        mapped = h.validate_batch(decoded, batch)
        self.assertEqual(mapped['inventory']['requirements'][0]['meaning'],
                         'Provide exactly two licensed surveyors.')

    def test_prompt_boundaries_are_not_record_kind_exemptions(self):
        for phrase in ('quantitative constraints', 'exclusivity', 'adjacent fragments'):
            self.assertIn(phrase, h.PACKAGE_RULES)
        for phrase in ('provenance', 'selected evidence', 'definitions', 'No record kind is exempt'):
            self.assertIn(phrase, h.HANDOFF_AUDIT_PROMPT)
        self.assertIn('full-time', h.HANDOFF_AUDIT_PROMPT)


if __name__ == '__main__':
    unittest.main()
