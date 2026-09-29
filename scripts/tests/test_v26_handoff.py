"""Prompt wiring and display-only handoff contracts, not live semantic guarantees."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s, semantic_policy as policy
from common import capture_clarification as gate
from capture.render_capture_brief import render_capture_brief
from test_capture_component_handoff import fixture


def checkpoint_fixture():
    _, context, _, _, _ = fixture()
    graph = context['checked_evidence_graph']
    sources = context['sources']
    terms = ['Reopen the facility 18 hours after panel installation.',
             'Keep the same facility closed until 48 hours after panel installation.']
    sources['D2'] = {'kind': 'package', 'text': ' '.join(terms)}
    for term in terms:
        graph['requirements'].append({
            'meaning': term, 'status': 'current', 'task': False, 'record_kind': 'requirement',
            'focus': [{'ref': 'D2:0', 'quote': term}], 'evidence': [{'ref': 'D2:0', 'quote': term}],
            'components': [],
        })
    anchors = [{'ref': 'D2:0', 'quote': term} for term in terms]
    question = {
        'id': 'Q1', 'route': 'formal_qa', 'kind': 'document_conflict',
        'question': 'Regarding the two closure terms: Which term governs?',
        'question_validation': 'supported', 'question_receipt_ids': ['IQ1'],
    }
    receipt = {'target_id': 'IQ1', 'signal': {'evidence': anchors},
               'check': {'verdict': 'supported'}}
    state = {
        'status': 'NEEDS_FORMAL_QA', 'research_authorized': False,
        'questions': [question], 'confirmed_answers': [],
        'understanding_audit': {
            'semantic_plan': graph, 'independent_question_checks': [receipt],
            'claim_evidence': {'passed': True, 'checks': [
                {'target_id': 'R2', 'verdict': 'supported', 'audit_dimension': 'source_fidelity',
                 'precedence_status': 'unresolved_precedence', 'conflicting_requirement_ids': ['R2', 'R3']},
            ]},
        },
    }
    evidence = {'status': 'VALIDATION_ONLY', 'capability_fit_analysis': {},
                'questions_to_ask': {'customer': ['Generic default question.']}}
    return state, {'sources': sources}, evidence


class V26PromptTests(unittest.TestCase):
    def test_future_missing_information_cases_cannot_pass_by_asking(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/semantic_classification_cases.json').read_text())['cases']
        for case in cases:
            if case['id'] in {'H02', 'S08'}:
                self.assertEqual(case['statuses'], ['READY'])
                self.assertEqual(case['relevance'], ['unknown'])

    def test_negative_boundary_reaches_comparator_and_comparison_auditor(self):
        for prompt in (c.ISOLATED_COMPONENT_PROMPT, c.COMPONENT_PROMPT,
                       s.audit_prompt([{'kind': 'comparison'}])):
            self.assertIn(policy.NEGATIVE_SCOPE_POLICY, prompt)
            self.assertIn('NEVER contradicted or unrelated', prompt)

    def test_tense_and_attribution_boundaries_are_shared(self):
        for prompt in (c.INVENTORY_PROMPT, s.audit_prompt([{'kind': 'claim'}]),
                       s.audit_prompt([{'kind': 'claim_coverage'}])):
            self.assertIn(policy.DELIVERY_TENSE_POLICY, prompt)
            self.assertIn(policy.ATTRIBUTION_EVIDENCE_POLICY, prompt)
        self.assertIn(policy.ATTRIBUTION_EVIDENCE_POLICY, c.ISOLATED_COMPONENT_PROMPT)

    def test_absence_boundary_reaches_both_question_channels_and_audit(self):
        for prompt in (c.AMBIGUITY_PROMPT, c.INVENTORY_PROMPT, c.QUESTION_AUDIT_PROMPT):
            self.assertIn(policy.MISSING_INFORMATION_POLICY, prompt)
            self.assertIn('existing reference with unclear duties', prompt)

    def test_source_fidelity_and_decomposer_remain_vendor_isolated(self):
        for prompt in (c.DECOMPOSE_PROMPT, s.audit_prompt([{'kind': 'requirement'}])):
            self.assertNotIn(policy.NEGATIVE_SCOPE_POLICY, prompt)
            self.assertNotIn(policy.ATTRIBUTION_EVIDENCE_POLICY, prompt)

    def test_correct_missing_condition_is_preserved_without_relabeling(self):
        # Supplied decisions test propagation, not whether an LLM will produce them.
        spans, context, _, _, _ = fixture()
        graph = context['checked_evidence_graph']
        claim = deepcopy(graph['claims'][0])
        claim.update(form='context', execution='negative', assertion_basis='work_denial')
        findings = deepcopy(graph['comparisons'][0]['component_findings'])
        findings['K0'].update(status='contradicted', supported_scope='')
        result = c.aggregate_components(graph['requirements'][0], claim, findings, spans)
        self.assertEqual(result['component_findings']['K1']['status'], 'missing')
        self.assertIn('K1', result['missing_components'])
        self.assertEqual(result['fit_label'], 'Unrelated')


class V26RendererTests(unittest.TestCase):
    def adapt(self, state, packet, evidence):
        from capture.checkpoint_render_adapter import apply_checkpoint_render_context
        return apply_checkpoint_render_context(evidence, state, packet)

    def test_formal_qa_and_partial_components_survive_without_authorizing_capture(self):
        state, packet, evidence = checkpoint_fixture()
        before = deepcopy((state, packet, evidence))
        adapted = self.adapt(state, packet, evidence)
        self.assertEqual((state, packet, evidence), before)
        self.assertEqual(gate.confirmed_context(state, packet), {})
        self.assertTrue(adapted['checkpoint_render_context']['display_only'])
        self.assertEqual(adapted['questions_to_ask']['customer'], [state['questions'][0]['question']])
        notes = ' '.join(adapted['capability_fit_analysis']['component_coverage_notes'])
        self.assertIn('Partial Fit', notes)
        self.assertIn('Install panels', notes)
        self.assertIn('certified lifting equipment', notes)
        self.assertIn('missing', notes)
        self.assertIn('Vendor claim: [V1:0]', notes)
        text = render_capture_brief(Path(__file__).resolve().parents[2] / 'templates/capture-brief.template.md', adapted)
        for expected in ('18 hours', '48 hours', 'unresolved_precedence', 'Which term governs?', 'Partial Fit'):
            self.assertIn(expected, text)
        self.assertNotIn('Generic default question.', text)

    def test_failed_fit_audit_does_not_suppress_independent_question(self):
        state, packet, evidence = checkpoint_fixture()
        state['status'] = 'TECHNICAL_BLOCKED'
        state['understanding_audit']['claim_evidence']['passed'] = False
        result = self.adapt(state, packet, evidence)
        self.assertEqual(len(result['checkpoint_render_context']['formal_qa_items']), 1)
        self.assertEqual(result['capability_fit_analysis']['component_coverage_notes'], [])
        self.assertNotIn('Partial Fit', str(result['checkpoint_render_context']))

    def test_pending_audit_cannot_export_positive_component_notes(self):
        state, packet, evidence = checkpoint_fixture()
        state['understanding_audit']['validation_pending'] = True
        self.assertEqual(self.adapt(state, packet, evidence)['capability_fit_analysis']['component_coverage_notes'], [])

    def test_wrong_package_quotes_are_rejected_not_silently_rendered(self):
        state, packet, evidence = checkpoint_fixture()
        packet['sources']['D2']['text'] = 'An unrelated current package.'
        result = self.adapt(state, packet, evidence)['checkpoint_render_context']
        self.assertEqual(result['formal_qa_items'], [])
        self.assertEqual(result['unresolved_precedence'], [])
        self.assertTrue(result['validation_issues'])

    def test_unsupported_question_cannot_replace_generic_text_as_a_valid_question(self):
        state, packet, evidence = checkpoint_fixture()
        state['questions'][0]['question_validation'] = 'unsupported'
        result = self.adapt(state, packet, evidence)
        self.assertEqual(result['checkpoint_render_context']['formal_qa_items'], [])
        self.assertNotIn('Generic default question.', str(result['questions_to_ask']['customer']))

    def test_same_conflict_question_dedupes_but_retains_receipts_and_broadest_context(self):
        state, packet, evidence = checkpoint_fixture()
        other = deepcopy(state['questions'][0])
        other.update(id='Q2', question='Regarding both source clauses and their entire context: Which term governs?', question_receipt_ids=['IQ2'])
        state['questions'].append(other)
        receipt = deepcopy(state['understanding_audit']['independent_question_checks'][0])
        receipt.update(target_id='IQ2')
        receipt['signal']['evidence'] = [{'ref': 'D2:0', 'quote': packet['sources']['D2']['text']}]
        state['understanding_audit']['independent_question_checks'].append(receipt)
        result = self.adapt(state, packet, evidence)['checkpoint_render_context']['formal_qa_items']
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]['question_ids']), {'Q1', 'Q2'})
        self.assertEqual(set(result[0]['receipt_ids']), {'IQ1', 'IQ2'})
        self.assertEqual(result[0]['question'], other['question'])

    def test_separate_conflicts_with_same_question_intent_stay_separate(self):
        state, packet, evidence = checkpoint_fixture()
        packet['sources']['D3'] = {'kind': 'package', 'text': 'The price cap is 40. The issued answer says 60.'}
        other = deepcopy(state['questions'][0])
        other.update(id='Q2', question='Regarding the price cap: Which term governs?', question_receipt_ids=['IQ2'])
        state['questions'].append(other)
        state['understanding_audit']['independent_question_checks'].append({
            'target_id': 'IQ2', 'signal': {'evidence': [{'ref': 'D3:0', 'quote': packet['sources']['D3']['text']}]},
            'check': {'verdict': 'supported'}})
        self.assertEqual(len(self.adapt(state, packet, evidence)['checkpoint_render_context']['formal_qa_items']), 2)

    def test_two_audited_conflicts_on_same_page_stay_separate(self):
        state, packet, evidence = checkpoint_fixture()
        terms = ['The base-year price cap is 40.', 'The issued answer sets that cap to 60.']
        packet['sources']['D2']['text'] += ' ' + ' '.join(terms)
        graph = state['understanding_audit']['semantic_plan']
        for term in terms:
            graph['requirements'].append({'status': 'current', 'focus': [{'ref': 'D2:0', 'quote': term}]})
        state['understanding_audit']['claim_evidence']['checks'].append({
            'target_id': 'R4', 'verdict': 'supported', 'audit_dimension': 'source_fidelity',
            'precedence_status': 'unresolved_precedence', 'conflicting_requirement_ids': ['R4', 'R5']})
        question = deepcopy(state['questions'][0])
        question.update(id='Q2', question='Regarding the price cap: Which term governs?', question_receipt_ids=['IQ2'])
        state['questions'].append(question)
        state['understanding_audit']['independent_question_checks'].append({
            'target_id': 'IQ2', 'signal': {'evidence': [{'ref': 'D2:0', 'quote': term} for term in terms]},
            'check': {'verdict': 'supported'}})
        view = self.adapt(state, packet, evidence)['checkpoint_render_context']
        self.assertEqual(len(view['formal_qa_items']), 2)
        self.assertEqual({tuple(row['conflicting_requirement_ids']) for row in view['formal_qa_items']},
                         {('R2', 'R3'), ('R4', 'R5')})

    def test_invalid_warrant_or_vendor_quote_cannot_be_promoted(self):
        state, packet, evidence = checkpoint_fixture()
        state['understanding_audit']['independent_question_checks'][0]['check']['verdict'] = 'unsupported'
        state['understanding_audit']['semantic_plan']['claims'][0]['evidence'][0]['quote'] = 'Invented vendor delivery.'
        view = self.adapt(state, packet, evidence)['checkpoint_render_context']
        self.assertEqual(view['formal_qa_items'], [])
        self.assertEqual(view['component_coverage_notes'], [])
        self.assertTrue(view['validation_issues'])


if __name__ == '__main__':
    unittest.main()
