"""Offline pipeline/renderer transfer tests with explicit, controlled model outputs."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import preliminary_capture as p
from capture.preliminary_render import render
from scripts.tests.test_preliminary_capture import provider, selection


def row(text, ref, *, topic='general', force='required', stage='issued', period='base', quantities=(), role='decision_condition'):
    return {'kind': role, 'statement': text, 'implication': 'Confirm this condition when planning pursuit.',
            'evidence': [selection(ref)], 'decision': {'topic': topic, 'stage': stage, 'force': force,
            'acquisition_dimension': 'other' if topic == 'acquisition' else 'none',
            'period': period, 'quantities': list(quantities), 'selection_basis': 'not_applicable', 'selected_controls': []}}


def fixture(descriptions):
    sources = {}
    rows = {}
    offsets = {}
    for index, (text, options) in enumerate(descriptions, 1):
        sid = f'D{index}'
        document = options.get('document', 'synthetic-doc')
        sources[sid] = {'kind': 'package', 'source_id': sid, 'document_id': document,
                        'filename': options.get('filename', 'synthetic.txt'), 'offset': offsets.get(document, 0), 'text': text}
        offsets[document] = offsets.get(document, 0) + len(text)
        rows[f'{sid}:0'] = row(text, f'{sid}:0', **{k: v for k, v in options.items() if k not in {'document', 'filename'}})
    sources['V1'] = {'kind': 'profile', 'text': 'We calibrate flow meters.', 'profile_field': 'capabilities'}
    return {'sources': sources, 'opportunity': {'title': 'Synthetic decision test'}, 'profile_present': True, 'technical_issues': []}, rows


def harness(rows, *, relation_fn=None, fail_reconciliation=False, omit_topic=None, reject_strengthening=False):
    baseline, calls = provider(proposal='pursue_discovery')
    observed = []
    def call(**request):
        payload = request['user_payload']
        observed.append(deepcopy(payload))
        phase = payload['phase']
        if phase == 'package_review':
            supplemental = 'material_gaps' in payload
            selected = [r for ref, r in rows.items() if ref in payload['primary_refs']
                        and (r['decision']['topic'] == omit_topic if supplemental else r['decision']['topic'] != omit_topic)]
            return {'rows': deepcopy(selected)}
        if phase == 'package_audit':
            value = baseline(**request)
            for key, candidate in payload['candidates'].items():
                value['checks'][key]['role'] = candidate['kind']
            for dimension in p.decisions.COVERAGE:
                value['material_checks'][dimension] = {'status': 'covered', 'reason': 'Controlled source comparison.'}
            if omit_topic and not any(r['decision']['topic'] == omit_topic for r in payload['candidates'].values()):
                value['material_checks']['experience_quantities'] = {'status': 'incomplete', 'reason': 'A mandatory reference count was omitted.'}
            return value
        if phase == 'reconciliation':
            relations = {k: {'state': 'active', 'governing_ids': [], 'reason': 'Independent applicable term.'} for k in payload['findings']}
            if relation_fn:
                relation_fn(payload['findings'], relations)
            return {'relations': relations}
        if phase == 'reconciliation_audit':
            return {'checks': {k: {'verdict': 'unsupported' if fail_reconciliation else 'supported',
                                   'reason': 'Controlled independent relationship review.'} for k in payload['findings']}}
        if phase == 'assessment':
            answer = baseline(**request)
            if reject_strengthening:
                staff = next(k for k, r in payload['findings'].items() if r['decision']['topic'] == 'staffing')
                answer['rows'].append({**answer['rows'][1], 'kind': 'decision_risk', 'recommendation': 'not_applicable',
                                     'finding_ids': [staff], 'statement': 'The government requires eight analysts.'})
            return answer
        if phase == 'assessment_audit':
            answer = baseline(**request)
            if reject_strengthening:
                for key, r in payload['candidates'].items():
                    if r['kind'] == 'decision_risk':
                        answer['checks'][key] = {'verdict': 'unsupported', 'reason': 'Anticipated staffing was strengthened into a mandate.'}
            return answer
        raise AssertionError(phase)
    return call, observed


CORE = ('Calibrate flow meters.', {'role': 'workstream'})


class PipelineDecisions(unittest.TestCase):
    def test_explicit_replacement_across_partitions_reaches_synthesis_and_history(self):
        packet, rows = fixture([CORE, ('Hold prices for 45 days.', {'topic': 'offer_validity'}),
                                ('The 45-day acceptance period is replaced by 120 days.', {'topic': 'offer_validity'})])
        def relations(findings, output):
            old = next(k for k, r in findings.items() if r['statement'].startswith('Hold'))
            new = next(k for k in findings if k != old)
            output[old] = {'state': 'superseded', 'governing_ids': [new], 'reason': 'Explicit replacement of the same acceptance period.'}
        call, observed = harness(rows, relation_fn=relations)
        def separate(spans, max_chars):
            return [({'phase': 'package_review', 'primary_refs': [ref], 'spans': {ref: span}}, p.review_schema({ref: span})) for ref, span in spans.items()]
        with patch.object(p, 'partitions', side_effect=separate):
            result = p.assess(packet, call=call)
        self.assertTrue(result['reconciliation_complete'])
        reconciliation = next(v for v in observed if v['phase'] == 'reconciliation')
        self.assertNotIn('spans', reconciliation)
        self.assertTrue(all(v['evidence'] for v in reconciliation['findings'].values()))
        synthesis = next(r for r in observed if r['phase'] == 'assessment')
        self.assertNotIn('Hold prices for 45 days.', [r['statement'] for r in synthesis['findings'].values()])
        self.assertEqual(len(result['superseded_findings']), 1)
        text = render(result, packet)
        self.assertIn('120 days', text.split('## Appendix:')[0])
        self.assertNotIn('Hold prices for 45 days.', text.split('## Appendix:')[0])
        self.assertIn('Hold prices for 45 days.', text.split('### Superseded Terms')[1])

    def test_independent_reconciliation_failure_never_leaks_unreconciled_terms(self):
        packet, rows = fixture([CORE, ('Term A: 45 days.', {'topic': 'offer_validity'}), ('Term B: 120 days.', {'topic': 'offer_validity'})])
        call, observed = harness(rows, fail_reconciliation=True)
        result = p.assess(packet, call=call)
        self.assertFalse(result['reconciliation_complete'])
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertFalse(any(v['phase'] == 'assessment' for v in observed))
        self.assertNotIn('Term A:', render(result, packet))
        self.assertNotIn('Term B:', render(result, packet))
        self.assertTrue(result['quarantined'])

    def test_provider_failure_at_reconciliation_preserves_candidates_but_not_active_terms(self):
        packet, rows = fixture([CORE, ('Term A: 45 days.', {'topic': 'offer_validity'}), ('Term B: 120 days.', {'topic': 'offer_validity'})])
        model, observed = harness(rows)
        def call(**request):
            return None if request['user_payload']['phase'] == 'reconciliation' else model(**request)
        result = p.assess(packet, call=call)
        self.assertEqual(len(result['reconciliation_candidates']), 2)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['recommendation'], 'investigate_further')
        self.assertFalse(result['reconciliation_complete'])

    def test_conflicting_terms_without_precedence_produce_one_fallback_formal_question(self):
        packet, rows = fixture([CORE, ('Hold prices for 45 days.', {'topic': 'offer_validity', 'filename': 'z-latest.txt'}),
                                ('Hold prices for 120 days.', {'topic': 'offer_validity', 'filename': 'a-old.txt'})])
        def unresolved(findings, output):
            for key in findings:
                output[key] = {'state': 'unresolved', 'governing_ids': [k for k in findings if k != key], 'reason': 'No order of precedence.'}
        call, _ = harness(rows, relation_fn=unresolved)
        result = p.assess(packet, call=call)
        self.assertEqual(result['recommendation'], 'investigate_further')
        text = render(result, packet)
        qa = text.split('## Formal Q&A Candidates')[1].split('## Next Capture Actions')[0]
        self.assertEqual(qa.count('Which term governs'), 1)
        self.assertIn('45 days', qa)
        self.assertIn('120 days', qa)

    def test_draft_status_and_anticipated_quantities_survive_to_main_and_auditor(self):
        packet, rows = fixture([CORE, ('Draft scope, issued for market research only.', {'topic': 'document_status', 'stage': 'draft', 'force': 'informational', 'role': 'context'}),
                                ('The buyer anticipates eight analysts.', {'topic': 'staffing', 'stage': 'unknown', 'force': 'anticipated', 'quantities': ['eight analysts']})])
        call, observed = harness(rows, reject_strengthening=True)
        result = p.assess(packet, call=call)
        text = render(result, packet).split('## Appendix:')[0]
        self.assertIn('Draft scope', text)
        self.assertIn('Obligation: anticipated', text)
        self.assertNotIn('government requires eight', text)
        audit = next(v for v in observed if v['phase'] == 'assessment_audit')
        staff = next(r for r in audit['findings'].values() if r['decision']['topic'] == 'staffing')
        self.assertIn('draft', staff['effective_stages'])
        self.assertTrue(staff['document_context_ids'])

    def test_required_reference_count_is_recovered_once_and_promoted_from_appendix(self):
        for count in (3, 7, 11):
            with self.subTest(count=count):
                packet, rows = fixture([CORE, (f'Provide {count} recent references.', {'topic': 'experience', 'quantities': [f'{count} references'], 'role': 'readiness_reference'})])
                call, observed = harness(rows, omit_topic='experience')
                result = p.assess(packet, call=call)
                self.assertEqual(len([v for v in observed if v['phase'] == 'package_review']), 2)
                self.assertEqual(len([v for v in observed if v['phase'] == 'package_audit']), 2)
                self.assertTrue(result['strategic_coverage_complete'])
                self.assertIn(f'{count} references', render(result, packet).split('## Appendix:')[0])

    def test_base_and_optional_counts_are_not_summed_or_hidden(self):
        packet, rows = fixture([CORE, ('Four base positions, one FTE each.', {'topic': 'staffing', 'quantities': ['four positions', 'one FTE each']}),
                                ('Two optional positions in the next period.', {'topic': 'staffing', 'period': 'option', 'force': 'optional', 'quantities': ['two positions']})])
        call, _ = harness(rows)
        text = render(p.assess(packet, call=call), packet).split('## Appendix:')[0]
        self.assertIn('four positions', text)
        self.assertIn('two positions', text)
        self.assertIn('Obligation: optional', text)
        self.assertNotIn('six positions', text)

    def test_material_supplement_is_bounded_even_when_gap_persists(self):
        packet, rows = fixture([CORE])
        call, observed = harness(rows, omit_topic='experience')
        result = p.assess(packet, call=call)
        self.assertEqual(len([v for v in observed if v['phase'] == 'package_review']), 2)
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_package_native_market_fact_is_not_denied_by_stock_disclaimer(self):
        packet, rows = fixture([CORE, ('The package identifies Example Supplier as incumbent.', {'topic': 'market', 'role': 'context', 'force': 'informational'})])
        call, _ = harness(rows)
        text = render(p.assess(packet, call=call), packet)
        self.assertIn('Example Supplier', text.split('## Market Context')[1].split('## Coverage')[0])
        self.assertNotIn('incumbent identity and funding are not established', text)


if __name__ == '__main__':
    unittest.main()
