"""Preserve and label uncertainty; never convert it into approved evidence."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.tests.test_preliminary_capture import packet, provider, selection
from scripts.tests.test_preliminary_decision_pipeline import CORE, fixture, harness
from common import preliminary_capture as p, preliminary_decisions as d
from capture.preliminary_render import render


def saved(name):
    return json.loads((Path(__file__).parent / 'fixtures/preliminary_review_policy.json').read_text())['cases'][name]


class PreliminaryReviewPolicyTests(unittest.TestCase):
    def test_saved_ebms_validity_not_suppressed_by_unrelated_audit_failures(self):
        case = saved('ebms')
        before = deepcopy(case)
        active, _, pending = d.admit_reconciliation(case['findings'], case['relations'], case['checks'])
        self.assertIn('F4-9', active)
        self.assertIn('180 calendar days', active['F4-9']['statement'])
        self.assertIn('F1S-1', pending)  # Actual unsupported alternate-PM assertion stays unapproved.
        self.assertEqual(case, before)

    def test_saved_ietss_no_audit_is_not_approval(self):
        case = saved('ietss')
        self.assertFalse(case['checks'])
        active, history, pending = d.admit_reconciliation(case['findings'], case['relations'], {})
        self.assertFalse(active or history)
        self.assertEqual(set(pending), set(case['findings']))

    def test_saved_bad_links_do_not_poison_independently_supported_oci_and_pricing(self):
        case = saved('ietss')
        # A controlled follow-on audit, NOT an invented receipt for the live run.
        checks = {k: {'verdict': 'supported', 'reason': 'Synthetic independent approval.'} for k in case['findings']}
        active, _, pending = d.admit_reconciliation(case['findings'], case['relations'], checks)
        self.assertIn('F4-5', active)
        self.assertIn('F4-1', active)
        self.assertIn('F4-6', pending)
        self.assertIn('F5-8', pending)

    def test_invalid_relation_is_documented_and_other_terms_reach_assessment(self):
        value, rows = fixture([CORE, ('Seven references.', {'topic': 'experience'}),
                              ('Access authorization before work.', {'topic': 'acquisition'})])
        def bad(findings, relations):
            key = next(k for k, r in findings.items() if r['decision']['topic'] == 'experience')
            relations[key]['governing_ids'] = ['nonexistent']
        model, observed = harness(rows, relation_fn=bad)
        result = p.assess(value, call=model)
        self.assertTrue(any(v['phase'] == 'reconciliation_audit' for v in observed))
        self.assertTrue(any(r['statement'] == 'Access authorization before work.' for r in result['findings'].values()))
        self.assertTrue(result['rows'])
        note = next(r for r in result['review_items'] if r['id'] == 'F1-2')
        self.assertEqual(note['source_fidelity'], 'supported')
        self.assertEqual(note['interpretation_status'], 'unverified')
        self.assertIn('Seven references.', render(result, value))
        self.assertNotIn('F1-2', next(v for v in observed if v['phase'] == 'assessment')['findings'])

    def test_routine_price_validity_is_appendix_only_and_not_a_pursuit_veto(self):
        value, rows = fixture([CORE, ('Hold prices for 120 days.', {'topic': 'offer_validity'}),
                              ('Hold prices for 45 days.', {'topic': 'offer_validity'})])
        model, observed = harness(rows, fail_reconciliation=True)
        result = p.assess(value, call=model)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        text = render(result, value)
        main, appendix = text.split('## Appendix:', 1)
        self.assertNotIn('Hold prices for', main)
        self.assertIn('Hold prices for 120 days.', appendix)
        self.assertIn('Unverified interpretation', appendix)
        self.assertTrue(result['rows'])
        self.assertNotIn('45 days', json.dumps(next(v for v in observed if v['phase'] == 'assessment')['findings']))

    def test_unsupported_strategy_is_visible_only_as_an_unverified_interpretation(self):
        model, _ = provider(reject_strategy=True)
        result = p.assess(packet(), call=model)
        self.assertFalse(result['rows'])
        self.assertIn('Calibration is a plausible capability overlap.', render(result, packet()))
        self.assertIn('Unverified interpretation', render(result, packet()))
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_bad_citation_is_documented_without_fabricated_source_quote(self):
        model, _ = provider(bad_reference=True)
        result = p.assess(packet(), call=model)
        note = next(r for r in result['review_items'] if r['id'] == 'F1-2')
        self.assertEqual(note['evidence'], [])
        self.assertEqual(note['source_fidelity'], 'not_established')
        self.assertIn('Use a readable font.', render(result, packet()))
        self.assertNotIn('invented`:', render(result, packet()))

    def test_rejected_core_yields_documented_review_not_fake_fit(self):
        model, _ = provider(reject_scope=True)
        result = p.assess(packet(), call=model)
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertFalse(result['rows'])
        self.assertIn('Unverified interpretation', render(result, packet()))
        self.assertIn('No independently audited core workstream', render(result, packet()))

    def test_changed_number_remains_unapproved_but_visible(self):
        value, rows = fixture([CORE, ('The draft anticipates eight analysts.',
                              {'topic': 'staffing', 'stage': 'draft', 'force': 'anticipated'})])
        model, _ = harness(rows, reject_strengthening=True)
        result = p.assess(value, call=model)
        self.assertFalse(any(r['kind'] == 'decision_risk' for r in result['rows']))
        note = next(r for r in result['review_items'] if r['id'] == 'A-3')
        self.assertIn('government requires eight', note['interpretation'])
        self.assertEqual(note['source_fidelity'], 'not_established')
        self.assertIn('Unverified interpretation', render(result, value))

    def test_one_malformed_relationship_check_does_not_discard_other_checks(self):
        value, rows = fixture([CORE, ('Seven references.', {'topic': 'experience'}),
                              ('Access approval before work.', {'topic': 'acquisition'})])
        baseline, _ = harness(rows)
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'reconciliation_audit':
                del answer['checks']['F1-2']['verdict']
            return answer
        result = p.assess(value, call=model)
        self.assertIn('F1-3', result['findings'])
        self.assertNotIn('F1-2', result['findings'])
        self.assertEqual([r['id'] for r in result['review_items']], ['F1-2'])

    def test_one_malformed_source_check_does_not_discard_audited_work(self):
        baseline, _ = provider()
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'package_audit':
                del answer['checks']['F1-2']['reason']
            return answer
        result = p.assess(packet(), call=model)
        self.assertIn('F1-1', result['findings'])
        self.assertIn('F1-3', result['findings'])
        self.assertNotIn('F1-2', result['findings'])
        self.assertEqual([r['id'] for r in result['review_items']], ['F1-2'])
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertTrue(result['rows'])

    def test_one_malformed_judgment_check_does_not_discard_audited_alignment(self):
        baseline, _ = provider()
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'assessment_audit':
                del answer['checks']['A-2']['qualifier_fidelity']
            return answer
        result = p.assess(packet(), call=model)
        self.assertEqual([r['id'] for r in result['rows']], ['A-1'])
        self.assertEqual([r['id'] for r in result['review_items']], ['A-2'])
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_incomplete_audit_metadata_does_not_certify_coverage_or_erase_valid_checks(self):
        baseline, _ = provider()
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'package_audit':
                del answer['coverage_reason']
            return answer
        result = p.assess(packet(), call=model)
        self.assertEqual(len(result['findings']), 3)
        self.assertTrue(result['rows'])
        self.assertFalse(result['strategic_coverage_complete'])

    def test_checked_audit_never_changes_a_valid_adverse_verdict(self):
        schema = p.audit_schema({'F1': {}, 'F2': {}})
        raw = {'checks': {'F1': {'verdict': 'unsupported', 'reason': 'Selected text does not support this claim.'},
                          'F2': {'verdict': 'supported', 'reason': 'Faithful interpretation.'}}}
        before = deepcopy(raw)
        checked = p.checked_audit(raw, schema)
        self.assertEqual(checked, raw)
        self.assertEqual(raw, before)

    def test_unverified_finding_cannot_be_used_as_alignment_evidence(self):
        value, rows = fixture([CORE, ('Seven references.', {'topic': 'experience'}),
                              ('Access approval before work.', {'topic': 'acquisition'})])
        baseline, _ = harness(rows, fail_reconciliation=True)
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'assessment':
                answer['rows'][0]['finding_ids'] = ['F1-2']
            return answer
        result = p.assess(value, call=model)
        self.assertFalse(any(r['kind'] == 'alignment' for r in result['rows']))
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertIn('A-1', [r['id'] for r in result['review_items']])

    def test_supplement_audit_failure_preserves_original_approval_and_documents_extra(self):
        value, rows = fixture([CORE, ('Seven references.', {'topic': 'experience'})])
        baseline, calls = harness(rows, omit_topic='experience')
        attempts = []
        def model(**request):
            v = request['user_payload']
            attempts.append(v['phase'])
            if v['phase'] == 'package_audit' and any('S-' in k for k in v['candidates']):
                return None
            return baseline(**request)
        result = p.assess(value, call=model)
        self.assertIn('F1-1', result['findings'])
        self.assertNotIn('F1S-1', result['findings'])
        self.assertIn('F1S-1', [r['id'] for r in result['review_items']])
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertTrue(result['rows'])
        self.assertEqual(attempts.count('package_audit'), 2)
        self.assertFalse(result['token_limit_omissions'])

    def test_source_audit_failure_is_documented_without_approval_or_retry(self):
        baseline, _ = provider()
        attempts = []
        def model(**request):
            phase = request['user_payload']['phase']
            attempts.append(phase)
            return None if phase == 'package_audit' else baseline(**request)
        result = p.assess(packet(), call=model)
        self.assertFalse(result['findings'] or result['rows'])
        self.assertEqual(len(result['review_items']), 3)
        self.assertEqual(attempts, ['package_review', 'package_audit'])
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertFalse(result['token_limit_omissions'])

    def test_routine_conflict_is_retained_in_appendix_not_formal_capture_qa(self):
        value, rows = fixture([CORE, ('Hold prices 45 days.', {'topic': 'offer_validity'}),
                              ('Hold prices 120 days.', {'topic': 'offer_validity'})])
        def unresolved(findings, relations):
            for key in findings:
                relations[key].update(state='unresolved', governing_ids=[k for k in findings if k != key])
        model, calls = harness(rows, relation_fn=unresolved)
        result = p.assess(value, call=model)
        self.assertFalse(result['decision_blockers'])
        main, appendix = render(result, value).split('## Appendix:', 1)
        self.assertNotIn('Hold prices', main)
        self.assertIn('Hold prices 45 days.', appendix)
        self.assertIn('Hold prices 120 days.', appendix)
        self.assertIn('Unresolved precedence', appendix)
        self.assertEqual(result['recommendation'], 'pursue_discovery')

    def test_malformed_candidate_decision_is_documented_without_renderer_crash(self):
        baseline, _ = provider()
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'package_review':
                answer['rows'][1]['decision'] = None
            return answer
        result = p.assess(packet(), call=model)
        self.assertNotIn('F1-2', result['findings'])
        self.assertIn('Use a readable font.', render(result, packet()))

    def test_readiness_cannot_masquerade_as_a_core_workstream(self):
        baseline, calls = provider()
        def model(**request):
            answer = baseline(**request)
            if request['user_payload']['phase'] == 'package_audit':
                answer['checks']['F1-1']['capture_relevance'] = 'readiness'
            return answer
        result = p.assess(packet(), call=model)
        self.assertFalse(result['rows'])
        self.assertFalse(any(v['phase'] == 'assessment' for v in calls))

    def test_no_readable_package_still_fails_without_model_call(self):
        value = packet()
        value['sources'] = {k: v for k, v in value['sources'].items() if v['kind'] != 'package'}
        result = p.assess(value, call=lambda **kw: self.fail('Unexpected model call'))
        self.assertEqual(result['status'], 'TECHNICAL_BLOCKED')
        self.assertFalse(result['findings'] or result['rows'] or result['review_items'])


if __name__ == '__main__':
    unittest.main()
