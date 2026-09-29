"""Bounded capture publication tests, not claims of live semantic reliability."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import preliminary_capture as p, preliminary_decisions as d
from capture.preliminary_render import render
from scripts.tests.test_preliminary_capture import packet, provider
from scripts.tests.test_preliminary_decision_pipeline import CORE, fixture, harness
from scripts.tests.test_preliminary_decisions import finding
from common.evidence_selection import EvidenceTransport


class PreliminaryScopeTests(unittest.TestCase):
    def test_all_valid_classifications_survive_wire_transport_without_defaulting(self):
        sources = p.build_spans(packet())
        package = {k: r for k, r in sources.items() if r['kind'] == 'package'}
        schema = p.review_schema(package)
        wire = EvidenceTransport(schema, {'spans': package})
        model, _ = provider()
        raw = model(user_payload={'phase': 'package_review', 'primary_refs': list(package)})
        for topic in d.TOPICS:
            for dimension in d.ACQUISITION_DIMENSIONS:
                if (topic == 'acquisition') == (dimension != 'none'):
                    value = deepcopy(raw)
                    value['rows'][0]['decision'].update(topic=topic, acquisition_dimension=dimension, selection_basis='narrative')
                    jsonschema.validate(value, wire.schema)
                    decoded = wire.resolve(value)
                    p.shape(decoded, schema)
                    self.assertEqual(decoded['rows'][0]['decision']['acquisition_dimension'], dimension)

    def test_saved_bad_category_pairs_are_disallowed_during_generation(self):
        saved = json.loads((Path(__file__).parent / 'fixtures/preliminary_scope.json').read_text())
        schema = p.review_schema({'D': {}})['properties']['rows']['items']['properties']['decision']
        count = 0
        for case in saved['cases'].values():
            for failure in case['category_failures']:
                decision = failure['raw']['decision']
                with self.subTest(id=failure['id']), self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(decision, schema)
                count += 1
        self.assertEqual(count, 14)

    def test_saved_reconciliation_failures_only_unapprove_entries_and_dependencies(self):
        saved = json.loads((Path(__file__).parent / 'fixtures/preliminary_scope.json').read_text())
        for case in saved['cases'].values():
            before = deepcopy(case)
            active, history, withheld = d.admit_reconciliation(case['findings'], case['relations'], case['checks'])
            self.assertEqual(set(active) | set(history) | set(withheld), set(case['findings']))
            self.assertEqual(case, before)
            for key in active:
                self.assertEqual(case['checks'][key]['verdict'], 'supported')
                self.assertFalse(set(case['relations'][key]['governing_ids']) & set(withheld))
        ces = saved['cases']['ces']
        active, _, withheld = d.admit_reconciliation(ces['findings'], ces['relations'], ces['checks'])
        self.assertIn('F1-1', active)  # Independently checked package status survives.
        self.assertIn('F1-13', withheld)  # Do not auto-repair the five-reference bundle.
        ebms = saved['cases']['ebms']
        active, _, withheld = d.admit_reconciliation(ebms['findings'], ebms['relations'], ebms['checks'])
        self.assertIn('F4-1', withheld)  # Original audit accepted a false form conflict.
        self.assertTrue(any(r['decision']['acquisition_dimension'] == 'competition_method' for r in active.values()))

    def test_failed_governing_term_withholds_both_sides_but_not_other_subjects(self):
        rows = {k: finding(k, text, topic=topic) for k, text, topic in [
            ('old', '45 days.', 'offer_validity'), ('new', 'Replace 45 with 120 days.', 'offer_validity'),
            ('refs', 'Seven references.', 'experience')]}
        relations = {k: {'state': 'active', 'governing_ids': [], 'reason': 'Applicable.'} for k in rows}
        relations['old'].update(state='superseded', governing_ids=['new'])
        checks = {k: {'verdict': 'supported', 'reason': 'Checked.'} for k in rows}
        checks['new'].update(verdict='uncertain')
        active, history, withheld = d.admit_reconciliation(rows, relations, checks)
        self.assertEqual(set(active), {'refs'})
        self.assertEqual(set(withheld), {'old', 'new'})
        self.assertFalse(history)

    def test_rejected_document_context_withholds_dependent_conditions(self):
        rows = {'ctx': finding('ctx', 'Draft.', topic='document_status', stage='draft'),
                'staff': finding('staff', 'Anticipated crew.', topic='staffing', force='anticipated'),
                'other': finding('other', 'Seven references in separate document.', topic='experience')}
        rows['staff']['document_context_ids'] = ['ctx']
        relations = {k: {'state': 'active', 'governing_ids': [], 'reason': 'Applicable.'} for k in rows}
        checks = {k: {'verdict': 'supported', 'reason': 'Checked.'} for k in rows}
        checks['ctx'].update(verdict='unsupported')
        active, _, withheld = d.admit_reconciliation(rows, relations, checks)
        self.assertEqual(set(active), {'other'})
        self.assertEqual(set(withheld), {'ctx', 'staff'})

    def test_missing_relationship_audit_does_not_approve_any_term(self):
        rows = {'a': finding('a', 'A term.', topic='pricing')}
        relations = {'a': {'state': 'active', 'governing_ids': [], 'reason': 'Applicable.'}}
        active, _, withheld = d.admit_reconciliation(rows, relations, {})
        self.assertFalse(active)
        self.assertEqual(set(withheld), {'a'})

    def test_failed_condition_does_not_prevent_workstream_assessment(self):
        value, rows = fixture([CORE, ('Hold prices 40 days.', {'topic': 'offer_validity'}),
                              ('Hold prices 90 days.', {'topic': 'offer_validity'})])
        call, seen = harness(rows, fail_reconciliation=True)
        result = p.assess(value, call=call)
        self.assertTrue(any(v['phase'] == 'assessment' for v in seen))
        self.assertTrue(result['rows'])
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertFalse(result['reconciliation_complete'])
        main = render(result, value).split('## Appendix:')[0]
        self.assertNotIn('offer_validity', main)
        self.assertNotIn('Hold prices 40 days.', main)
        self.assertIn('Hold prices 40 days.', render(result, value).split('### Readiness Interpretations to Verify')[1])

    def test_one_failed_staffing_term_does_not_erase_separate_reference_requirement(self):
        value, rows = fixture([CORE, ('Four base positions.', {'topic': 'staffing'}),
                              ('Seven recent references.', {'topic': 'experience'})])
        baseline, _ = harness(rows)
        def call(**request):
            answer = baseline(**request)
            v = request['user_payload']
            if v['phase'] == 'reconciliation_audit':
                for k, r in v['findings'].items():
                    if r['decision']['topic'] == 'staffing':
                        answer['checks'][k].update(verdict='unsupported', reason='Quantity is not in the selected quote.')
            return answer
        result = p.assess(value, call=call)
        main = render(result, value).split('## Appendix:')[0]
        self.assertIn('Seven recent references.', main)
        self.assertIn('Four base positions.', main.split('## Package Status')[0])
        self.assertNotIn('Four base positions.', main.split('## Package Status')[1])
        self.assertNotIn('F1-2', result['findings'])
        self.assertTrue(result['rows'])

    def test_uncertain_form_reading_never_becomes_a_government_conflict(self):
        value, rows = fixture([CORE, ('Printed form choices are unclear.', {'topic': 'acquisition', 'role': 'conflict'})])
        rows['D2:0']['decision'].update(acquisition_dimension='set_aside', selection_basis='uncertain')
        model, _ = harness(rows)
        result = p.assess(value, call=model)
        self.assertTrue(result['rows'])
        self.assertFalse(any(r['role'] == 'conflict' for r in result['findings'].values()))
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertIn('set_aside', render(result, value).split('## Appendix:')[0])
        self.assertNotIn('Which term governs', render(result, value))

    def test_audited_routine_appendix_failure_does_not_veto_discovery(self):
        model, _ = provider(reject_reference=True, proposal='pursue_discovery')
        result = p.assess(packet(), call=model)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertFalse(result['decision_blockers'])

    def test_unknown_bad_source_remains_material_not_auto_ignored_as_appendix(self):
        model, _ = provider(bad_reference=True, proposal='pursue_discovery')
        result = p.assess(packet(), call=model)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertTrue(result['decision_blockers'])
        self.assertEqual(result['review_items'][0]['capture_relevance'], 'uncertain')

    def test_qualifier_check_cannot_be_overridden_by_supported_verdict(self):
        value, rows = fixture([CORE, ('The draft anticipates eight analysts.',
                              {'topic': 'staffing', 'stage': 'draft', 'force': 'anticipated'})])
        baseline, _ = harness(rows, reject_strengthening=True)
        def call(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'assessment_audit':
                for k, r in request['user_payload']['candidates'].items():
                    answer['checks'][k]['qualifier_fidelity'] = 'unsupported' if r['kind'] == 'decision_risk' else 'supported'
                    answer['checks'][k]['verdict'] = 'supported'
            return answer
        result = p.assess(value, call=call)
        self.assertIn('government requires eight', render(result, value).split('## Package Status')[0])
        self.assertFalse(any(r['kind'] == 'decision_risk' for r in result['rows']))
        self.assertTrue(any(q['id'] == 'A-3' for q in result['quarantined']))
        self.assertTrue(any(r['kind'] == 'alignment' for r in result['rows']))

    def test_qualifiers_are_rendered_from_approved_fact_not_a_second_paraphrase(self):
        value, rows = fixture([CORE, ('The draft anticipates eight analysts.',
                              {'topic': 'staffing', 'stage': 'draft', 'force': 'anticipated', 'quantities': ['eight analysts']})])
        baseline, _ = harness(rows)
        def call(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'assessment':
                staff = next(k for k, r in request['user_payload']['findings'].items() if r['decision']['topic'] == 'staffing')
                answer['rows'].append({**answer['rows'][1], 'kind': 'next_action', 'recommendation': 'not_applicable',
                                      'finding_ids': [staff], 'statement': 'Validate access to the anticipated team.'})
            return answer
        result = p.assess(value, call=call)
        actions = render(result, value).split('## Next Capture Actions')[1].split('## Recommendation Rationale')[0]
        self.assertIn('Document: draft', actions)
        self.assertIn('Obligation: anticipated', actions)
        self.assertIn('eight analysts', actions)

    def test_missing_qualifier_audit_cannot_reuse_an_old_supported_verdict(self):
        baseline, _ = provider()
        def call(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'assessment_audit':
                for check in answer['checks'].values():
                    del check['qualifier_fidelity']
            return answer
        result = p.assess(packet(), call=call)
        self.assertFalse(result['rows'])
        self.assertTrue(result['findings'])
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_prompt_contract_has_no_customer_specific_parsing_exception(self):
        self.assertIn('NOT two conflicting government instructions', p.REVIEW_PROMPT)
        self.assertIn('NOT a request to', p.REVIEW_PROMPT)
        self.assertIn('qualifier_fidelity', p.ASSESS_AUDIT_PROMPT)
        for customer in ('IETSS', 'EBMS', 'FMBT', 'CES', 'PSI'):
            self.assertNotIn(customer, p.REVIEW_PROMPT + p.ASSESS_PROMPT + p.ASSESS_AUDIT_PROMPT)


if __name__ == '__main__':
    unittest.main()
