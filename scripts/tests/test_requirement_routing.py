"""Routing and scoring contracts; synthetic judgments are not live accuracy claims."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import requirement_routing as rr, requirement_context as rc
from common import semantic_contract as c, semantic_plan as s, capture_understanding as u
from common import capture_clarification as gate
from common.capture_fit import _component_credit
from capture.render_capture_brief import render_capture_brief
from capture.checkpoint_render_adapter import apply_checkpoint_render_context
from tests.evidence_wire_fixture import selection_provider


def fixture():
    statements = [
        ('work', 'technical_capability', 'prime_contractor', 'Install the sensor array.'),
        ('condition', 'administrative_formatting', 'prime_contractor', 'Use 8 1/2" x 11" pages and submit the proposal via Portal Q.'),
        ('pricing', 'contract_terms', 'prime_contractor', 'Installation is firm-fixed-price; maintenance is time-and-materials. Payment is Net-30.'),
        ('qualification', 'compliance_certification', 'prime_contractor', 'The offeror must hold ISO 9001 certification.'),
        ('condition', 'past_performance', 'prime_contractor', 'Relevant experience requires three sensor-array projects in five years.'),
        ('timing', 'technical_capability', 'prime_contractor', 'Restore sensor service within four hours.'),
        ('context', 'contract_terms', 'not_prime_contractor', 'The Government will issue access badges.'),
    ]
    spans, components = {}, []
    for i, (kind, category, applicability, text) in enumerate(statements):
        ref = f'D{i}:0'
        spans[ref] = {'kind': 'package', 'source_id': f'D{i}', 'offset': 0, 'text': text}
        components.append({'kind': kind, 'category': category, 'applicability': applicability,
                           'routing_reason': 'The quoted source assigns this obligation or actor explicitly.',
                           'text': text, 'evidence': [{'ref': ref, 'quote': text}]})
    spans['V0:0'] = {'kind': 'profile', 'source_id': 'V0', 'offset': 0,
                     'text': 'Our employees installed the sensor array.'}
    anchors = [a for p in components for a in p['evidence']]
    req = {'area': 'scope', 'status': 'current', 'record_kind': 'requirement', 'task': True,
           'logic': 'all', 'supersedes': [], 'focus': anchors, 'evidence': anchors, 'components': components}
    claim = {'meaning': spans['V0:0']['text'], 'assertion_basis': 'staff_execution',
             'attribution': 'self', 'unresolved_dimensions': [], 'antecedent_evidence': [],
             'evidence': [{'ref': 'V0:0', 'quote': spans['V0:0']['text']}]}
    raw = {'requirements': [req], 'claims': [claim], 'quoted_vendor_context': [],
           'questions': [], 'resolved_question_ids': []}
    return spans, s.validate_inventory(raw, spans, components=True)


def findings(requirement, claim):
    return {key: {'status': 'matched' if key == 'K0' else 'missing',
                  'reason': 'Reported installation establishes this task.' if key == 'K0' else 'No specific proof supplied.',
                  'supported_scope': 'Install the sensor array.' if key == 'K0' else '',
                  'evidence': deepcopy(claim['evidence']) if key == 'K0' else []}
            for key in rr.assessed_components(requirement)}


class CategorizationTests(unittest.TestCase):
    def test_strict_schema_requires_category_applicability_and_reason(self):
        spans, inv = fixture()
        ctx = rc.context('R0', inv['requirements'][0], spans)
        p = inv['requirements'][0]['components'][0]
        part = {k: deepcopy(v) for k, v in p.items() if k != 'evidence'}
        part['evidence_ids'] = [next(iter(ctx['evidence_catalog']))]
        raw = {'requirements': {'R0': {'status': 'complete', 'logic': 'all', 'components': [part]}}}
        jsonschema.validate(raw, rc.decomposition_schema([ctx]))
        for field in rr.FIELDS:
            bad = deepcopy(raw)
            del bad['requirements']['R0']['components'][0][field]
            with self.subTest(field=field), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, rc.decomposition_schema([ctx]))
            with self.assertRaises(ValueError):
                rc.validate_decomposition(bad, [ctx], spans)
        bad = deepcopy(raw)
        bad['requirements']['R0']['components'][0]['category'] = 'miscellaneous'
        with self.assertRaises(ValueError):
            rc.validate_decomposition(bad, [ctx], spans)

    def test_mixed_missing_labels_cannot_silently_use_legacy_routing(self):
        _, inv = fixture()
        for key in rr.FIELDS:
            del inv['requirements'][0]['components'][1][key]
        with self.assertRaises(ValueError):
            s.comparison_pairs(inv)

    def test_every_component_has_exactly_one_route(self):
        _, inv = fixture()
        rows = rr.ledger(inv['requirements'])
        self.assertEqual(len(rows), 7)
        self.assertEqual(len({(r['requirement_id'], r['component_id']) for r in rows}), 7)
        self.assertEqual([r['route'] for r in rows], ['vendor_comparison', 'proposal_checklist',
            'contract_terms_checklist', 'vendor_comparison', 'vendor_comparison', 'vendor_comparison', 'unrelated'])

    def test_filter_preserves_component_ids_and_excludes_both_bypass_categories(self):
        _, inv = fixture()
        jobs = list(c.component_jobs(s.comparison_pairs(inv)))
        self.assertEqual([j['component_id'] for j in jobs], ['K0', 'K3', 'K4', 'K5'])
        self.assertTrue(all(j['component_category'] in rr.FIT_CATEGORIES for j in jobs))
        self.assertEqual(len(inv['requirements'][0]['components']), 7)

    def test_admin_only_and_terms_only_make_zero_pairs_and_calls(self):
        _, inv = fixture()
        inv['requirements'][0]['components'] = inv['requirements'][0]['components'][1:3]
        self.assertEqual(s.comparison_pairs(inv), [])
        self.assertEqual(list(c.component_jobs(s.comparison_pairs(inv))), [])

    def test_standalone_experience_and_certification_still_compared(self):
        for index in (3, 4):
            _, inv = fixture()
            inv['requirements'][0]['components'] = [inv['requirements'][0]['components'][index]]
            self.assertTrue(c.is_standalone_criterion(inv['requirements'][0]))
            self.assertEqual(len(s.comparison_pairs(inv)), 1)
            self.assertEqual(len(list(c.component_jobs(s.comparison_pairs(inv)))), 1)

    def test_explicit_technical_conditions_do_not_require_a_work_sibling_to_be_compared(self):
        _, inv = fixture()
        inv['requirements'][0]['components'] = [inv['requirements'][0]['components'][5]]
        self.assertEqual(len(list(c.component_jobs(s.comparison_pairs(inv)))), 1)

    def test_unknown_applicability_is_a_question_not_unrelated_or_compliance(self):
        _, inv = fixture()
        part = inv['requirements'][0]['components'][3]
        part.update(applicability='unclear', routing_reason='The package does not identify which certification track applies.')
        self.assertEqual(rr.route(part), 'applicability_review')
        out = rr.add_applicability_questions(inv)
        self.assertEqual(out['questions'][0]['dimension'], 'requirement_meaning')
        self.assertEqual(out['questions'][0]['claims'], [])
        self.assertEqual(rr.add_applicability_questions(out), out)
        self.assertNotIn('K3', [j['component_id'] for j in c.component_jobs(s.comparison_pairs(out))])

    def test_inactive_terms_never_become_current_checklist_items(self):
        spans, inv = fixture()
        inv['requirements'][0]['status'] = 'superseded'
        self.assertEqual(s.comparison_pairs(inv), [])
        lists = rr.checklists(inv['requirements'], spans)
        self.assertEqual(lists['proposal_formatting_submission_checklist'], [])
        self.assertEqual(lists['contract_terms_checklist'], [])
        self.assertTrue(all(r['route'] == 'inactive_context' for r in lists['requirement_applicability_notes']))

    def test_nonprime_duty_with_work_verb_is_not_a_vendor_job(self):
        _, inv = fixture()
        inv['requirements'][0]['components'][0]['applicability'] = 'not_prime_contractor'
        self.assertNotIn('K0', [j['component_id'] for j in c.component_jobs(s.comparison_pairs(inv))])


class FitBoundaryTests(unittest.TestCase):
    def test_missing_not_unrelated_is_enforced_in_schema_and_validator(self):
        spans, inv = fixture()
        job = next(c.component_jobs(s.comparison_pairs(inv)))
        props = c.component_response_schema(job)['properties']
        self.assertNotIn('unrelated', props['status']['enum'])
        self.assertNotIn('not_applicable', props['status']['enum'])
        raw = {k: job[k] for k in ('pair_id', 'component_id', 'component_kind')}
        raw.update(status='unrelated', reason='The vendor did not say.', supported_scope='', evidence=job['claimed']['evidence'])
        with self.assertRaises(ValueError):
            c.validate_component_response(raw, job, spans)
        raw['status'] = 'missing'
        self.assertEqual(c.validate_component_response(raw, job, spans)['status'], 'missing')

    def test_direct_job_cannot_bypass_smart_filter(self):
        _, inv = fixture()
        job = next(c.component_jobs(s.comparison_pairs(inv)))
        for category in ('administrative_formatting', 'contract_terms'):
            job['component_category'] = category
            with self.assertRaises(ValueError):
                c.component_response_schema(job)

    def test_partial_fit_counts_only_assessable_components(self):
        spans, inv = fixture()
        req, claim = inv['requirements'][0], inv['claims'][0]
        edge = c.aggregate_components(req, claim, findings(req, claim), spans)
        self.assertEqual(edge['fit_label'], 'Partial Fit')
        self.assertEqual(edge['met_components'], ['K0'])
        self.assertEqual(edge['missing_components'], ['K3', 'K4', 'K5'])
        self.assertEqual(_component_credit(edge, req), .25)

    def test_bypass_neither_awards_credit_nor_dilutes_a_proven_task(self):
        spans, inv = fixture()
        req, claim = inv['requirements'][0], inv['claims'][0]
        req['components'] = req['components'][:3]
        edge = c.aggregate_components(req, claim, findings(req, claim), spans)
        self.assertEqual(edge['fit_label'], 'Supported Fit')
        self.assertEqual(edge['component_findings'].keys(), {'K0'})
        self.assertEqual(_component_credit(edge, req), 1)
        self.assertTrue(all(r['compliance_status'] == 'not_assessed' for r in rr.ledger([req])))

    def test_missing_assessable_findings_and_injected_bypass_findings_are_rejected(self):
        spans, inv = fixture()
        req, claim = inv['requirements'][0], inv['claims'][0]
        for bad in ({}, {**findings(req, claim), 'K1': {'status': 'matched'}}):
            with self.assertRaises(ValueError):
                c.aggregate_components(req, claim, bad, spans)

    def test_explicit_denial_remains_contradicted_not_unrelated(self):
        spans, inv = fixture()
        req, claim = inv['requirements'][0], inv['claims'][0]
        claim.update(form='context', execution='negative', assertion_basis='work_denial')
        req['components'] = req['components'][:1]
        got = findings(req, claim)
        got['K0'].update(status='contradicted', supported_scope='', reason='Explicit denial of this exact task.')
        edge = c.aggregate_components(req, claim, got, spans)
        self.assertEqual(edge['fit_label'], 'Contradicted')
        self.assertNotEqual(edge['relationship'], 'unrelated')

    def test_auditor_rejection_of_category_remains_binding(self):
        spans, inv = fixture()
        target = {'id': 'R0', 'kind': 'requirement', 'value': inv['requirements'][0]}
        prompt = s.audit_prompt([target])
        self.assertIn('Reject disguised scope', prompt)
        audited = s.validate_audit({'checks': {'R0': {'verdict': 'unsupported',
            'reason': 'A technical recovery time was hidden as a contract term.'}}}, [target])
        self.assertFalse(audited['passed'])

    def test_current_comparator_and_auditor_share_one_boundary_not_legacy_conflicts(self):
        _, inv = fixture()
        prompt = s.audit_prompt([{'kind': 'comparison', 'required': inv['requirements'][0]}])
        for p in (c.ROUTED_COMPONENT_PROMPT, prompt):
            self.assertIn(rr.COMPARISON_POLICY, p)
            self.assertNotIn('Concrete different performed work remains unrelated', p)
            self.assertNotIn('Explicit different work with no concrete overlap is\nunrelated', p)

    def test_source_fidelity_auditor_does_not_receive_vendor_comparison_instructions(self):
        for kind in ('requirement', 'package_coverage'):
            prompt = s.audit_prompt([{'kind': kind}])
            self.assertIn(rr.ROUTING_FIDELITY_POLICY, prompt)
            self.assertNotIn(rr.COMPARISON_POLICY, prompt)
            self.assertNotIn('Audit every reported finding against its own component and the isolated vendor claim', prompt)


class ChecklistTests(unittest.TestCase):
    def test_source_anchors_and_contract_allocations_survive_routing(self):
        spans, inv = fixture()
        before = deepcopy(inv)
        out = rr.checklists(inv['requirements'], spans)
        proposal = out['proposal_formatting_submission_checklist'][0]
        self.assertEqual(proposal['evidence'], inv['requirements'][0]['components'][1]['evidence'])
        self.assertEqual(proposal['citations'][0]['ref'], 'D1:0')
        self.assertIn('firm-fixed-price', out['contract_terms_checklist'][0]['text'])
        self.assertIn('time-and-materials', out['contract_terms_checklist'][0]['text'])
        self.assertEqual(inv, before)

    def test_invalid_or_private_checklist_citations_rejected(self):
        spans, inv = fixture()
        part = inv['requirements'][0]['components'][1]
        for anchor in ({'ref': 'V0:0', 'quote': spans['V0:0']['text']}, {'ref': 'D1:0', 'quote': 'Invented limit'}):
            part['evidence'] = [anchor]
            with self.assertRaises(ValueError):
                rr.checklists(inv['requirements'], spans)

    def test_production_renderer_appends_unchecked_items_from_checkpoint(self):
        spans, inv = fixture()
        context = rr.checklists(inv['requirements'], spans)
        template = Path(__file__).resolve().parents[2] / 'templates/capture-brief.template.md'
        text = render_capture_brief(template, {'understanding_checkpoint': context})
        self.assertIn('## Proposal Formatting & Submission Checklist', text)
        self.assertIn('- [ ] **R0/K1**', text)
        self.assertIn('8 1/2" x 11"', text)
        self.assertIn('[D1:0]', text)
        self.assertIn('Contract Terms Review Checklist', text)
        self.assertIn('Requirement Applicability Notes', text)
        self.assertNotIn('[x]', text)
        self.assertNotIn('Portal Q', text.split('## Proposal Formatting & Submission Checklist')[0])

    def test_fixture_adapter_keeps_filtered_ids_without_component_lookup_errors(self):
        spans, inv = fixture()
        req, claim = inv['requirements'][0], inv['claims'][0]
        pairs = s.comparison_pairs(inv)
        graph = s.attach_comparisons(inv, {'pairs': {pairs[0]['id']: {'components': findings(req, claim)}}}, pairs, spans)
        packet = {'sources': {row['source_id']: row for row in spans.values()}, 'technical_issues': []}
        state = {'status': 'READY', 'questions': [], 'confirmed_answers': [], 'understanding_audit': {
            'semantic_plan': graph, 'claim_evidence': {'passed': True, 'checks': []}}}
        out = apply_checkpoint_render_context({}, state, packet)
        self.assertEqual(out['checkpoint_render_context']['validation_issues'], [])
        notes = out['capability_fit_analysis']['component_coverage_notes']
        self.assertIn('K3', notes[0])
        self.assertNotIn('K1 Use', notes[0])
        self.assertEqual(len(out['proposal_formatting_submission_checklist']), 1)


class IntegrationTests(unittest.TestCase):
    def run_fixture(self, *, all_admin=False, unclear=False, reject_category=False):
        spans, inv = fixture()
        if all_admin:
            inv['requirements'][0]['components'] = inv['requirements'][0]['components'][1:3]
        if unclear:
            inv['requirements'][0]['components'][0].update(applicability='unclear', routing_reason='Which track applies is unspecified.')
        raw_inventory = deepcopy(inv)
        for r in raw_inventory['requirements']:
            r.pop('meaning')
        for claim in raw_inventory['claims']:
            for key in ('form', 'execution', 'negative_context'):
                claim.pop(key, None)
        calls = []
        def provider(**kwargs):
            payload = kwargs['user_payload']
            if 'signals' in kwargs['response_schema']['schema']['properties']:
                return {'signals': []}
            if 'source_coverage' in payload:
                return deepcopy(raw_inventory)
            if isinstance(payload.get('requirements'), dict):
                return {'requirements': {'R0': {'logic': 'all', 'components': deepcopy(raw_inventory['requirements'][0]['components'])}}}
            if 'component_job' in payload:
                job = payload['component_job']
                calls.append(job)
                return {**{k: job[k] for k in ('pair_id', 'component_id', 'component_kind')},
                        'status': 'missing', 'reason': 'Mocked no-proof finding for routing test.', 'supported_scope': '', 'evidence': []}
            if 'targets' in payload:
                return {'checks': {t['id']: {s.audit_verdict_key(t): 'unsupported' if reject_category and t['id'] == 'R0' else 'supported',
                                           'reason': 'Synthetic audit verdict; not a real semantic evaluation.'}
                                   for t in payload['targets']}}
            return {'complete': True, 'facts': [{'area': 'scope', 'statement': v['text'], 'refs': [k]}
                                               for k, v in payload['spans'].items()],
                    'coverage': [{'source_id': v['source_id'], 'finding': 'Retained in synthetic fixture', 'refs': [k]}
                                 for k, v in payload['spans'].items()]}
        packet = {'sources': {r['source_id']: r for r in spans.values()}, 'technical_issues': []}
        result = u.analyze_packet(packet, [], {}, call=selection_provider(provider))
        return result, gate.validate_assessment(result, packet), calls, packet

    def test_real_orchestrator_calls_only_four_fit_components_and_preserves_all_seven(self):
        result, state, calls, packet = self.run_fixture()
        self.assertNotIn('pipeline_errors', result)
        self.assertEqual([j['component_id'] for j in calls], ['K0', 'K3', 'K4', 'K5'])
        self.assertEqual(len(result['understanding_audit']['component_routing']), 7)
        self.assertEqual(state['status'], 'READY')
        state.update(fingerprint='fixture', confirmed_answers=[])
        context = gate.confirmed_context(state, packet)
        self.assertEqual(len(context['proposal_formatting_submission_checklist']), 1)
        self.assertEqual(len(context['contract_terms_checklist']), 1)

    def test_admin_only_pipeline_makes_zero_comparison_calls(self):
        result, state, calls, _ = self.run_fixture(all_admin=True)
        self.assertNotIn('pipeline_errors', result)
        self.assertEqual(calls, [])
        self.assertEqual(result['understanding_audit']['semantic_plan']['comparisons'], [])
        self.assertEqual(state['status'], 'READY')

    def test_unclear_applicability_cannot_authorize_research(self):
        result, state, calls, _ = self.run_fixture(unclear=True)
        self.assertNotIn('pipeline_errors', result)
        self.assertEqual(state['status'], 'NEEDS_FORMAL_QA')
        self.assertFalse(state['research_authorized'])
        self.assertEqual(len(state['questions']), 1)
        self.assertNotIn('K0', [j['component_id'] for j in calls])

    def test_bad_category_audit_still_blocks_capture(self):
        result, state, _, _ = self.run_fixture(reject_category=True)
        self.assertEqual(state['status'], 'TECHNICAL_BLOCKED')
        self.assertFalse(state['research_authorized'])


if __name__ == '__main__':
    unittest.main()
