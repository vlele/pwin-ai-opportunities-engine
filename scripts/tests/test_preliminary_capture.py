"""Preliminary-product acceptance tests. Stub verdicts are not live validation."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import preliminary_capture as p
from capture.preliminary_render import render


def packet(profile=True):
    sources = {'D1': {'kind': 'package', 'source_id': 'D1', 'document_id': 'synthetic',
        'filename': 'scope.txt', 'offset': 0,
        'text': 'Calibrate flow meters.\nSubmit bids in a readable font.\nAccess authorization is required before site work.'}}
    if profile:
        for sid, field in (('V1', 'capabilities[0]'), ('V2', 'keywords[0]')):
            sources[sid] = {'kind': 'profile', 'profile_field': field, 'text': 'Equipment calibration.'}
    return {'sources': sources, 'opportunity': {'title': 'Synthetic calibration', 'buyer': 'Example buyer'},
            'profile_present': profile, 'technical_issues': []}


def selection(ref, line=1):
    return {'start': {'ref': ref, 'line': line}, 'end': {'ref': ref, 'line': line}}


def provider(*, reject_reference=False, reject_scope=False, bad_reference=False,
             reject_strategy=False, incomplete=False, proposal='investigate_further'):
    calls = []
    def call(**request):
        v = request['user_payload']
        calls.append(deepcopy(v))
        if v['phase'] == 'package_review':
            ref = v['primary_refs'][0]
            raw = {'rows': [
                {'kind': 'workstream', 'statement': 'Calibrate flow meters.',
                 'implication': 'Measurement accuracy is central to delivery.', 'evidence': [selection(ref)]},
                {'kind': 'readiness_reference', 'statement': 'Use a readable font.',
                 'implication': 'Submission presentation.', 'evidence': [selection('invented' if bad_reference else ref, 2)]},
                {'kind': 'readiness_reference', 'statement': 'Access authorization is required before site work.',
                 'implication': 'Site mobilization depends on authorization.', 'evidence': [selection(ref, 3)]}]}
            for row in raw['rows']:
                row['decision'] = {'topic': 'general', 'stage': 'unknown', 'force': 'unknown',
                    'acquisition_dimension': 'none',
                    'period': 'not stated', 'quantities': [], 'selection_basis': 'not_applicable', 'selected_controls': []}
            return raw
        if v['phase'] == 'package_audit':
            checks = {}
            for key, row in v['candidates'].items():
                role = 'decision_condition' if 'authorization' in row['statement'] else row['kind']
                reject = reject_scope if role == 'workstream' else reject_reference and role == 'readiness_reference'
                checks[key] = {'verdict': 'unsupported' if reject else 'supported', 'role': role,
                               'capture_relevance': 'readiness' if role == 'readiness_reference' else 'strategic',
                               'reason': 'Synthetic audit verdict.'}
            return {'checks': checks, 'strategic_coverage': 'incomplete' if incomplete else 'complete',
                    'coverage_reason': 'Synthetic material-scope review.',
                    'material_checks': {k: {'status': 'not_present', 'reason': 'Not present in this synthetic range.'} for k in p.decisions.COVERAGE}}
        if v['phase'] == 'assessment':
            work = next(k for k, row in v['findings'].items() if row['role'] == 'workstream')
            vendor = next(iter(v['spans']), None)
            base = {'finding_ids': [work], 'vendor_evidence': [], 'alignment': 'not_applicable',
                    'experience': 'not_applicable', 'follow_up': 'Confirm fit with project evidence.',
                    'recommendation': 'not_applicable'}
            return {'rows': [
                {**base, 'kind': 'alignment', 'statement': 'Calibration is a plausible capability overlap.' if vendor else 'No profile was supplied.',
                 'reason': 'A keyword is not delivery history.', 'alignment': 'plausible' if vendor else 'unknown',
                 'experience': 'not_evidenced', 'vendor_evidence': [selection(vendor)] if vendor else []},
                {**base, 'kind': 'recommendation', 'statement': 'Investigate the opportunity.',
                 'reason': 'Eligibility and delivery proof need review.', 'recommendation': proposal}]}
        if v['phase'] == 'assessment_audit':
            return {'checks': {key: {'verdict': 'unsupported' if reject_strategy else 'supported',
                                     'qualifier_fidelity': 'supported',
                                     'reason': 'Synthetic judgment audit.'} for key in v['candidates']}}
        raise AssertionError(v['phase'])
    return call, calls


class PreliminaryCaptureTests(unittest.TestCase):
    def test_sparse_profile_does_not_require_claim_inventory_or_comparators(self):
        model, calls = provider()
        result = p.assess(packet(), call=model)
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertEqual([r['phase'] for r in calls], ['package_review', 'package_audit', 'assessment', 'assessment_audit'])
        alignment = next(r for r in result['rows'] if r['kind'] == 'alignment')
        self.assertEqual(alignment['experience'], 'not_evidenced')
        self.assertEqual(len(alignment['vendor_evidence']), 1)
        self.assertNotIn('vendor_coverage', json.dumps(calls))

    def test_reference_failure_does_not_remove_supported_assessment(self):
        model, _ = provider(reject_reference=True)
        result = p.assess(packet(), call=model)
        self.assertTrue(result['rows'])
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertNotIn('Use a readable font.', [r['statement'] for r in result['findings'].values()])
        self.assertTrue(result['limitations'])

    def test_bad_reference_anchor_is_quarantined_not_rewritten(self):
        model, _ = provider(bad_reference=True, proposal='pursue_discovery')
        result = p.assess(packet(), call=model)
        self.assertTrue(result['findings'])
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertTrue(result['quarantined'])
        self.assertNotIn('F1-2', result['findings'])
        self.assertEqual(result['review_items'][0]['evidence'], [])

    def test_no_supported_core_scope_yields_review_notes_without_fit(self):
        model, _ = provider(reject_scope=True)
        result = p.assess(packet(), call=model)
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertEqual(result['rows'], [])
        self.assertIn('Unverified interpretation', render(result, packet()))

    def test_missing_profile_is_unknown_not_automatic_decline(self):
        model, _ = provider(proposal='decline')
        result = p.assess(packet(profile=False), call=model)
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertTrue(result['findings'])

    def test_incomplete_material_coverage_is_visible_without_automatic_veto(self):
        model, _ = provider(incomplete=True, proposal='pursue_discovery')
        result = p.assess(packet(), call=model)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertIn('Unresolved Review Items', render(result, packet()))

    def test_auditor_promotes_decision_changing_appendix_item(self):
        model, _ = provider()
        result = p.assess(packet(), call=model)
        text = render(result, packet())
        before_appendix = text.split('## Appendix:')[0]
        self.assertIn('Access authorization is required before site work.', before_appendix)
        self.assertIn('Use a readable font.', text.split('## Appendix:')[1])
        self.assertNotIn('Use a readable font.', before_appendix)

    def test_strategy_rejection_retains_facts_without_fallback_win_themes(self):
        model, _ = provider(reject_strategy=True)
        result = p.assess(packet(), call=model)
        self.assertTrue(result['findings'])
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['recommendation'], 'investigate_further')
        text = render(result, packet())
        self.assertIn('plausible capability overlap', text.split('## Package Status')[0])
        self.assertNotIn('plausible capability overlap', text.split('## Vendor Alignment and Experience')[1].split('## Capture Priorities')[0])

    def test_provider_failure_after_review_does_not_publish_unaudited_findings(self):
        model, _ = provider()
        def stop(**request):
            return None if request['user_payload']['phase'] == 'package_audit' else model(**request)
        result = p.assess(packet(), call=stop)
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertEqual(result['findings'], {})
        self.assertFalse(result['rows'])
        self.assertEqual(len(result['review_items']), 3)

    def test_report_never_claims_external_research_or_complete_readiness(self):
        model, _ = provider()
        text = render(p.assess(packet(), call=model), packet())
        self.assertIn('not a complete compliance matrix', text)
        self.assertIn('No live market, incumbent, USAspending or GovTribe research', text)
        self.assertIn('self-reported', text)

    def test_conditional_discovery_cannot_hide_limited_coverage(self):
        model, _ = provider(proposal='pursue_discovery')
        value = packet()
        value['technical_issues'] = ['A scope-bearing page could not be read.']
        result = p.assess(value, call=model)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertIn('A scope-bearing page could not be read.', render(result, value))

    def test_preserves_inputs_and_revalidates_own_stage_receipts(self):
        value = packet()
        before = deepcopy(value)
        model, calls = provider()
        with tempfile.TemporaryDirectory() as directory:
            first = p.assess(value, call=model, checkpoint_dir=Path(directory))
            second = p.assess(value, call=lambda **kw: self.fail('Unexpected paid call'), checkpoint_dir=Path(directory))
        self.assertEqual(first['findings'], second['findings'])
        self.assertEqual(first['rows'], second['rows'])
        self.assertEqual(value, before)

    def test_private_profile_cannot_establish_package_requirement(self):
        model, _ = provider()
        def private(**request):
            raw = model(**request)
            if request['user_payload']['phase'] == 'package_review':
                raw['rows'][0]['evidence'] = [selection('V1:0')]
            return raw
        result = p.assess(packet(), call=private)
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertTrue(result['quarantined'])
        self.assertNotIn('F1-1', result['findings'])
        self.assertEqual(result['review_items'][0]['evidence'], [])
        self.assertFalse(result['rows'])

    def test_invalid_finding_identity_cannot_support_strategy(self):
        model, _ = provider()
        def bad_link(**request):
            raw = model(**request)
            if request['user_payload']['phase'] == 'assessment':
                raw['rows'][0]['finding_ids'] = ['F999-1']
            return raw
        result = p.assess(packet(), call=bad_link)
        self.assertFalse(any(r['kind'] == 'alignment' for r in result['rows']))
        self.assertTrue(result['quarantined'])

    def test_partition_primary_ranges_are_losslessly_accounted(self):
        value = packet(False)
        value['sources']['D1']['text'] = 'Calibrate flow meters. ' * 6000
        spans = p.build_spans(value)
        schedule = p.partitions(spans, 40000)
        self.assertGreater(len(schedule), 1)
        self.assertEqual([ref for payload, _ in schedule for ref in payload['primary_refs']], list(spans))
        for payload, schema in schedule:
            self.assertLessEqual(p._size(p.REVIEW_PROMPT, payload, schema), 40000)
            self.assertTrue(all(payload['spans'][ref] == spans[ref] for ref in payload['spans']))

    def test_oversized_source_unit_fails_without_paid_calls_or_truncation(self):
        spans = p.build_spans(packet(False))
        spans['D1:0']['text'] = 'X' * 700000
        before = deepcopy(spans)
        with self.assertRaises(ValueError):
            p.partitions(spans)
        self.assertEqual(spans, before)

    def test_no_cited_delivery_means_no_reported_delivery(self):
        model, _ = provider()
        def invented(**request):
            raw = model(**request)
            if request['user_payload']['phase'] == 'assessment':
                raw['rows'][0].update(experience='reported_delivery', vendor_evidence=[])
            return raw
        result = p.assess(packet(), call=invented)
        self.assertFalse(any(r['experience'] == 'reported_delivery' for r in result['rows']))
        self.assertTrue(result['quarantined'])

    def test_orchestrator_writes_fresh_artifacts_without_legacy_gate_or_research(self):
        from capture import run_capture_research as capture
        model, _ = provider()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scope.txt').write_text(packet()['sources']['D1']['text'])
            args = ['capture', '--workspace', folder, '--file', str(root / 'scope.txt'), '--depth', 'preliminary']
            with patch.object(sys, 'argv', args), patch.object(capture, 'load_local_attachments', return_value={}), \
                 patch.object(capture, 'build_packet', return_value=packet()), \
                 patch.object(capture, 'checkpoint', side_effect=AssertionError('Legacy gate called')), \
                 patch.object(capture, 'fetch_public_research', side_effect=AssertionError('Unexpected research')), \
                 patch.object(p, '_call_openai_json', side_effect=model), contextlib.redirect_stdout(io.StringIO()) as stream:
                code = capture.main()
            output = json.loads(stream.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(Path(output['brief_path']).is_file())
            self.assertTrue(Path(output['evidence_path']).is_file())
            self.assertEqual(output['assessment_type'], 'preliminary')
            self.assertIn('## Appendix: Proposal Readiness Review', Path(output['brief_path']).read_text())

    def test_legacy_resume_cannot_accidentally_reuse_failed_graph(self):
        from capture import run_capture_research as capture
        with patch.object(sys, 'argv', ['capture', '--workspace', '.', '--file', 'scope.txt',
                                      '--depth', 'preliminary', '--resume-understanding']), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            capture.main()
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
