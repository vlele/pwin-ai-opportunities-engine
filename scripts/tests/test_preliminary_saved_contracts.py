"""Saved live wire regressions, plus synthetic transfer and negative controls.

An expected schema variant is not a new model response or semantic audit pass.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import preliminary_capture as p
from common import preliminary_decisions as d
from common.evidence_selection import EvidenceTransport
from scripts.tests.test_preliminary_decisions import finding
from scripts.tests.test_preliminary_capture import provider
from scripts.tests.evidence_wire_fixture import selection_provider
from capture.preliminary_render import render

FIXTURE = Path(__file__).parent / 'fixtures/preliminary_saved_contracts.json'


def typed(row, dimension='other'):
    value = deepcopy(row)
    value['decision']['acquisition_dimension'] = dimension if value['decision']['topic'] == 'acquisition' else 'none'
    return value


class SavedContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = json.loads(FIXTURE.read_text())

    def test_all_three_original_self_link_responses_fail_the_provider_schema(self):
        for case, record in self.saved['reconciliations'].items():
            with self.subTest(case=case):
                rows = {k: typed(v) for k, v in record['findings'].items()}
                schema = p.reconciliation_schema(rows)
                wire = EvidenceTransport(schema, {'findings': rows})
                jsonschema.Draft202012Validator.check_schema(wire.schema)
                self.assertFalse(wire.active)
                with self.assertRaises(ValueError):
                    p.shape(record['response'], wire.schema)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(record['response'], wire.schema)
                with self.assertRaises(ValueError):
                    d.apply_reconciliation(rows, record['response']['relations'])

    def test_expected_empty_links_fix_identity_without_rewriting_source(self):
        for case, record in self.saved['reconciliations'].items():
            with self.subTest(case=case):
                rows = {k: typed(v) for k, v in record['findings'].items()}
                before = deepcopy(rows)
                expected = deepcopy(record['response'])
                for relation in expected['relations'].values():
                    if relation['state'] == 'active':
                        relation['governing_ids'] = []
                p.shape(expected, p.reconciliation_schema(rows))
                jsonschema.validate(expected, p.reconciliation_schema(rows))
                active, history = d.apply_reconciliation(rows, expected['relations'])
                self.assertEqual(set(active) | set(history), set(rows))
                self.assertEqual(rows, before)
                self.assertTrue(all(active[k]['statement'] == rows[k]['statement'] for k in active))
                # EBMS's unreviewed semantic conflict is deliberately NOT repaired here.
                self.assertEqual({k for k, r in expected['relations'].items() if r['state'] == 'unresolved'},
                                 {k for k, r in record['response']['relations'].items() if r['state'] == 'unresolved'})

    def test_seven_saved_narratives_are_not_checkbox_assertions(self):
        self.assertEqual(len(self.saved['rejected_findings']), 7)
        for item in self.saved['rejected_findings']:
            with self.subTest(case=item['case'], id=item['id']):
                row = typed(item['decoded'])
                before = deepcopy(row)
                d.validate_decision(row, item['sources'])
                self.assertEqual(row, before)
                self.assertTrue(all(a['quote'] in item['sources'][a['ref']]['text'] for a in row['evidence']))

    def test_active_and_linked_schema_branches_are_disjoint(self):
        rows = {k: typed(finding(k, k, topic='offer_validity')) for k in ('a', 'b')}
        schema = p.reconciliation_schema(rows)
        valid = {'relations': {k: {'state': 'active', 'governing_ids': [], 'reason': 'Independent.'} for k in rows}}
        p.shape(valid, schema)
        for state, links in [('active', ['b']), ('superseded', []), ('unresolved', []),
                             ('active', ['a']), ('unresolved', ['unknown'])]:
            with self.subTest(state=state, links=links):
                bad = deepcopy(valid)
                bad['relations']['a'].update(state=state, governing_ids=links)
                with self.assertRaises(ValueError):
                    p.shape(bad, schema)

    def test_different_acquisition_attributes_cannot_be_a_conflict_or_replacement(self):
        rows = {'a': typed(finding('a', 'No set-aside restriction.', topic='acquisition'), 'set_aside'),
                'b': typed(finding('b', 'Only one supplier is invited.', topic='acquisition'), 'competition_method')}
        active = {k: {'state': 'active', 'governing_ids': [], 'reason': 'Independent attribute.'} for k in rows}
        p.shape({'relations': active}, p.reconciliation_schema(rows))
        self.assertEqual(len(d.apply_reconciliation(rows, active)[0]), 2)
        for state in ('unresolved', 'superseded'):
            bad = deepcopy(active)
            bad['a'].update(state=state, governing_ids=['b'])
            if state == 'unresolved':
                bad['b'].update(state=state, governing_ids=['a'])
            with self.subTest(state=state), self.assertRaises(ValueError):
                p.shape({'relations': bad}, p.reconciliation_schema(rows))
            with self.assertRaises(ValueError):
                d.apply_reconciliation(rows, bad)

    def test_same_attribute_conflict_and_explicit_replacement_still_work(self):
        rows = {k: typed(finding(k, text, topic='acquisition'), 'vehicle')
                for k, text in [('a', 'Use vehicle Alpha.'), ('b', 'Use vehicle Beta.') ]}
        relations = {k: {'state': 'unresolved', 'governing_ids': [other], 'reason': 'No precedence supplied.'}
                     for k, other in [('a', 'b'), ('b', 'a')]}
        p.shape({'relations': relations}, p.reconciliation_schema(rows))
        self.assertEqual(len(d.apply_reconciliation(rows, relations)[0]), 2)
        relations['a'].update(state='superseded', reason='Explicit applicable replacement in b.')
        relations['b'].update(state='active', governing_ids=[])
        p.shape({'relations': relations}, p.reconciliation_schema(rows))
        self.assertEqual(set(d.apply_reconciliation(rows, relations)[1]), {'a'})

    def test_form_page_does_not_disqualify_independent_narrative(self):
        for topic, dimension in [('acquisition', 'funding'), ('acquisition', 'set_aside'), ('general', 'none')]:
            sources = {'D1:0': {'kind': 'package', 'text': 'Award depends on funding.\nThis action is unrestricted.\n[ ] Other option',
                                'choice_review_required': True}}
            text = 'This action is unrestricted.' if dimension == 'set_aside' else 'Award depends on funding.'
            row = typed(finding('F1', text, topic=topic), dimension)
            row['decision']['selection_basis'] = 'narrative'
            with self.subTest(topic=topic, dimension=dimension):
                d.validate_decision(row, sources)

    def test_actual_selected_control_checks_cannot_be_bypassed(self):
        row = typed(finding('F1', 'Open; state selected', topic='acquisition'), 'set_aside')
        row['decision'].update(selection_basis='selected_control', selected_controls=[{'ref': 'D1:0', 'id': 'c1', 'label': 'Open'}])
        source = {'D1:0': {'kind': 'package', 'text': 'Open; state selected', 'choice_review_required': True,
                           'form_controls': [{'id': 'c1', 'label': 'Open', 'state': 'selected'}]}}
        d.validate_decision(row, source)
        for state in ('unselected', 'uncertain'):
            bad = deepcopy(source)
            bad['D1:0']['form_controls'][0]['state'] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                d.validate_decision(row, bad)
        for basis in ('narrative', 'not_applicable'):
            bad = deepcopy(row)
            bad['decision']['selection_basis'] = basis
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                d.validate_decision(bad, source)

    def test_reconciliation_contract_is_shared_by_model_and_auditor(self):
        self.assertIn('active MUST use governing_ids: []', p.RECONCILE_PROMPT)
        self.assertIn('active MUST use governing_ids: []', p.RECONCILE_AUDIT_PROMPT)
        for prompt in (p.REVIEW_PROMPT, p.PACKAGE_AUDIT_PROMPT, p.RECONCILE_PROMPT, p.RECONCILE_AUDIT_PROMPT):
            self.assertIn('set-aside status', prompt)
            self.assertIn('competition method', prompt)
        self.assertIn('printed alternatives', p.PACKAGE_AUDIT_PROMPT)

    def test_saved_narratives_reach_audit_and_render_only_if_supported(self):
        for item in self.saved['rejected_findings']:
            for supported in (True, False):
                with self.subTest(case=item['case'], id=item['id'], supported=supported):
                    row = typed(item['decoded'])
                    # Synthetic neutral core keeps this a controlled handoff test,
                    # not a reconstructed full solicitation or vendor-fit result.
                    core = typed(finding('core', 'Calibrate flow meters.'))
                    core['kind'] = 'workstream'
                    core['evidence'] = [{'ref': 'TEST:0', 'quote': core['statement']}]
                    sources = deepcopy(item['sources'])
                    sources['TEST:0'] = {'kind': 'package', 'source_id': 'TEST', 'document_id': 'synthetic',
                                         'text': core['statement'], 'offset': 0}
                    baseline, calls = provider()
                    def model(**request):
                        payload = request['user_payload']
                        if payload['phase'] == 'package_review':
                            allowed = ('kind', 'statement', 'implication', 'evidence', 'decision')
                            return {'rows': [{k: r[k] for k in allowed} for r in (core, row)]}
                        answer = baseline(**request)
                        if payload['phase'] == 'package_audit':
                            answer['checks']['F1-2']['verdict'] = 'supported' if supported else 'unsupported'
                        return answer
                    packet = {'profile_present': False, 'technical_issues': [], 'opportunity': {}}
                    with patch.object(p, 'build_spans', return_value=sources):
                        result = p.assess(packet, call=selection_provider(model))
                    self.assertTrue(any(c['phase'] == 'package_audit' for c in calls))
                    self.assertEqual('F1-2' in result['findings'], supported)
                    self.assertEqual(row['statement'] in render(result, packet), supported)
                    self.assertTrue(any(c['phase'] == 'assessment' for c in calls), result['limitations'])

    def test_printed_alternatives_mislabelled_narrative_are_rejected_by_audit(self):
        from scripts.tests.test_preliminary_decision_pipeline import fixture, harness, CORE
        packet, rows = fixture([CORE, ('Open / Restricted', {'topic': 'acquisition'})])
        packet['sources']['D2']['choice_review_required'] = True
        row = rows['D2:0']
        row['statement'] = 'Open is selected.'
        row['decision'].update(acquisition_dimension='competition_method', selection_basis='narrative')
        stub, seen = harness(rows)
        def rejecting(**request):
            answer = stub(**request)
            if request['user_payload']['phase'] == 'package_audit':
                for key, r in request['user_payload']['candidates'].items():
                    if r['decision']['topic'] == 'acquisition':
                        answer['checks'][key].update(verdict='unsupported', reason='Printed alternatives do not select a method.')
            return answer
        result = p.assess(packet, call=rejecting)
        self.assertFalse(any(r['statement'] == 'Open is selected.' for r in result['findings'].values()))
        self.assertNotIn('Open is selected.', render(result, packet))
        self.assertTrue(result['quarantined'])
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_missing_unknown_or_misplaced_dimension_is_not_silently_defaulted(self):
        row = typed(finding('F1', 'An acquisition condition.', topic='acquisition'))
        sources = {'D1:0': {'kind': 'package', 'text': row['statement']}}
        for dimension in ('none', 'invented'):
            bad = deepcopy(row)
            bad['decision']['acquisition_dimension'] = dimension
            with self.subTest(dimension=dimension), self.assertRaises(ValueError):
                d.validate_decision(bad, sources)
        del row['decision']['acquisition_dimension']
        with self.assertRaises(KeyError):
            d.validate_decision(row, sources)

    def test_absent_profile_reaches_assessment_without_evidence_or_fabricated_fit(self):
        from scripts.tests.test_preliminary_capture import packet
        model, calls = provider(proposal='pursue_discovery')
        result = p.assess(packet(profile=False), call=model)
        self.assertTrue(any(c['phase'] == 'assessment' for c in calls))
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertTrue(result['rows'])
        self.assertFalse(any(r['vendor_evidence'] for r in result['rows']))
        self.assertFalse(any(r['kind'] == 'formal_qa' for r in result['rows']))
        alignment = next(r for r in result['rows'] if r['kind'] == 'alignment')
        self.assertEqual(alignment['alignment'], 'unknown')
        wire = EvidenceTransport(p.assessment_schema({'F1': {}}, {}), {'spans': {}})
        self.assertFalse(wire.active)
        with self.assertRaises(ValueError):
            p.shape([{'ref': 'invented', 'quote': 'not supplied'}], p.anchors({}))

    def test_mechanically_valid_supersession_still_needs_independent_audit(self):
        from scripts.tests.test_preliminary_decision_pipeline import fixture, harness, CORE
        packet, rows = fixture([CORE, ('Hold prices for 40 days.', {'topic': 'offer_validity'}),
                                ('Hold prices for 90 days.', {'topic': 'offer_validity'})])
        def replace(findings, relations):
            first, second = list(findings)
            relations[first].update(state='superseded', governing_ids=[second], reason='Unsupported precedence claim.')
        call, _ = harness(rows, relation_fn=replace, fail_reconciliation=True)
        result = p.assess(packet, call=call)
        self.assertFalse(result['reconciliation_complete'])
        self.assertFalse(result['rows'])
        self.assertTrue(result['reconciliation_response'])
        self.assertEqual(result['reconciliation_candidates'].keys(), result['reconciliation_audit']['checks'].keys())

    def test_self_link_failure_remains_visible_and_cannot_reach_assessment(self):
        from scripts.tests.test_preliminary_decision_pipeline import fixture, harness, CORE
        packet, rows = fixture([CORE, ('40 days.', {'topic': 'offer_validity'}), ('90 days.', {'topic': 'offer_validity'})])
        def corrupt(findings, relations):
            for key in relations:
                relations[key]['governing_ids'] = [key]
        call, seen = harness(rows, relation_fn=corrupt)
        result = p.assess(packet, call=call)
        self.assertFalse(result['reconciliation_complete'])
        self.assertFalse(any(r['phase'] in {'assessment', 'reconciliation_audit'} for r in seen))
        self.assertTrue(all(k in r['governing_ids'] for k, r in result['reconciliation_response']['relations'].items()))


if __name__ == '__main__':
    unittest.main()
