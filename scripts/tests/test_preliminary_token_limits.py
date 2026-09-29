"""Token-limit continuation is not permission to publish unaudited evidence."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.tests.test_preliminary_capture import packet, provider
from scripts.tests.test_preliminary_decision_pipeline import CORE, fixture, harness
from common import openai_reasoning as api, preliminary_capture as p
from capture.preliminary_render import render


TITLE = '## Requirements not processed because of token limits in the test environment'


def completion(content='', finish='length', refusal=None):
    # Exact failure shape/usage from the saved IETSS and EBMS responses, no RFP rules.
    usage = {'prompt_tokens': 42487, 'completion_tokens': 32768,
             'completion_tokens_details': {'reasoning_tokens': 32768}}
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=content, refusal=refusal))],
        usage=SimpleNamespace(model_dump=lambda: usage))


def limited():
    return api.ModelOutputLimit(usage={'completion_tokens': 32768,
                                      'completion_tokens_details': {'reasoning_tokens': 32768}})


def two_ranges():
    value = packet()
    value['sources']['D2'] = {**value['sources']['D1'], 'source_id': 'D2',
                            'document_id': 'second-doc', 'filename': 'second.txt',
                            'text_regions': [{'start': 0, 'end': len(value['sources']['D1']['text']),
                                              'page_number': 7, 'basis': 'synthetic'}]}
    def schedule(spans, *args):
        return [({'phase': 'package_review', 'primary_refs': [ref], 'spans': {ref: span}},
                 p.review_schema({ref: span})) for ref, span in spans.items()]
    return value, schedule


class CompletionLimitTests(unittest.TestCase):
    def invoke(self, response, **options):
        client = Mock()
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        with patch.object(api, '_openai_client', return_value=client):
            return api._call_openai_json(system_prompt='test', user_payload={},
                model='test', timeout_seconds=1, **options)

    def test_empty_length_response_is_explicit_not_fake_json(self):
        with self.assertRaises(api.ModelOutputLimit) as error:
            self.invoke(completion(), raise_on_output_limit=True)
        self.assertEqual(error.exception.usage['completion_tokens'], 32768)
        self.assertEqual(error.exception.usage['reasoning_tokens'], 32768)

    def test_even_parseable_truncated_response_is_not_accepted(self):
        with self.assertRaises(api.ModelOutputLimit):
            self.invoke(completion('{"rows": []}'), raise_on_output_limit=True)

    def test_legacy_callers_fail_closed_without_new_exception(self):
        self.assertIsNone(self.invoke(completion()))

    def test_empty_stop_and_refusal_are_not_token_limit_exceptions(self):
        self.assertIsNone(self.invoke(completion(finish='stop'), raise_on_output_limit=True))
        self.assertIsNone(self.invoke(completion(refusal='Declined'), raise_on_output_limit=True))
        self.assertIsNone(self.invoke(completion(finish='content_filter'), raise_on_output_limit=True))

    def test_valid_finished_response_is_unchanged(self):
        self.assertEqual(self.invoke(completion('{"rows": []}', 'stop'), raise_on_output_limit=True), {'rows': []})

    def test_missing_choices_fail_closed(self):
        self.assertIsNone(self.invoke(SimpleNamespace(choices=[]), raise_on_output_limit=True))


class PreliminaryTokenLimitTests(unittest.TestCase):
    def test_reading_limit_skips_only_that_range_and_finishes_assessment(self):
        value, schedule = two_ranges()
        model, calls = provider(proposal='pursue_discovery')
        def call(**request):
            payload = request['user_payload']
            if payload['phase'] == 'package_review' and payload['primary_refs'] == ['D1:0']:
                raise limited()
            return model(**request)
        with patch.object(p, 'partitions', side_effect=schedule):
            result = p.assess(value, call=call)
        self.assertTrue(result['rows'])
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertFalse(result['strategic_coverage_complete'])
        self.assertEqual([m['reviewed'] for m in result['review_manifest']], [False, True])
        self.assertEqual(result['token_limit_omissions'][0]['source_refs'], ['D1:0'])
        self.assertTrue(all(a['ref'] != 'D1:0' for f in result['findings'].values() for a in f['evidence']))
        self.assertIn('assessment_audit', [v['phase'] for v in calls])

    def test_audit_limit_does_not_admit_unaudited_range_or_cache_failure(self):
        value, schedule = two_ranges()
        model, _ = provider()
        def call(**request):
            payload = request['user_payload']
            if payload['phase'] == 'package_audit' and payload['primary_refs'] == ['D2:0']:
                raise limited()
            return model(**request)
        with tempfile.TemporaryDirectory() as directory, patch.object(p, 'partitions', side_effect=schedule):
            result = p.assess(value, call=call, checkpoint_dir=Path(directory))
            cached = [json.loads(f.read_text()) for f in Path(directory).glob('*.json')]
        self.assertTrue(result['rows'])
        self.assertFalse(any(a['ref'] == 'D2:0' for f in result['findings'].values() for a in f['evidence']))
        self.assertFalse(any(c.get('stage') == 'preliminary-package-audit-2' for c in cached))
        text = render(result, value)
        self.assertIn(TITLE, text)
        self.assertIn('second.txt', text.split(TITLE)[1])
        self.assertIn('page 7', text.split(TITLE)[1])
        self.assertIn('preliminary-package-audit-2', text.split(TITLE)[1])

    def test_all_readings_limited_still_renders_honest_report_without_claims(self):
        result = p.assess(packet(), call=lambda **kw: (_ for _ in ()).throw(limited()))
        self.assertEqual(result['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['findings'], {})
        text = render(result, packet())
        self.assertIn(TITLE, text)
        self.assertIn('No independently audited core workstream', text)
        self.assertEqual(len(result['stages']), 1)

    def test_supplement_limit_preserves_original_audit_without_unchecked_extras(self):
        model, _ = provider()
        for fail_at_audit in (False, True):
            audit_calls = 0
            def call(**request):
                nonlocal audit_calls
                payload = request['user_payload']
                if payload['phase'] == 'package_review' and 'material_gaps' in payload and not fail_at_audit:
                    raise limited()
                answer = model(**request)
                if payload['phase'] == 'package_audit':
                    audit_calls += 1
                    if audit_calls == 2:
                        raise limited()
                    answer['material_checks']['staffing_quantities'] = {'status': 'incomplete', 'reason': 'Synthetic gap.'}
                return answer
            result = p.assess(packet(), call=call)
            self.assertTrue(result['rows'])
            self.assertEqual(set(result['findings']), {'F1-1', 'F1-2', 'F1-3'})
            self.assertFalse(result['strategic_coverage_complete'])
            self.assertEqual(len(result['token_limit_omissions']), 1)

    def test_reconciliation_limit_withholds_terms_but_keeps_audited_workstream(self):
        value, rows = fixture([CORE, ('Two references required.', {'topic': 'experience'}),
                               ('Access permit required.', {'topic': 'other'})])
        for phase in ('reconciliation', 'reconciliation_audit'):
            model, _ = harness(rows)
            def call(**request):
                if request['user_payload']['phase'] == phase:
                    raise limited()
                return model(**request)
            result = p.assess(value, call=call)
            self.assertTrue(result['rows'])
            self.assertEqual(set(result['findings']), {'F1-1'})
            self.assertFalse(result['reconciliation_complete'])
            self.assertTrue(result['decision_blockers'])

    def test_judgment_limit_never_publishes_unaudited_strategy(self):
        for phase in ('assessment', 'assessment_audit'):
            model, _ = provider()
            def call(**request):
                if request['user_payload']['phase'] == phase:
                    raise limited()
                return model(**request)
            result = p.assess(packet(), call=call)
            self.assertTrue(result['findings'])
            self.assertEqual(result['rows'], [])
            self.assertIn(TITLE, render(result, packet()))

    def test_generic_bad_json_or_provider_failure_is_not_reported_as_token_limit(self):
        for response in ({}, None):
            result = p.assess(packet(), call=lambda **kw: response)
            self.assertEqual(result['status'], 'TECHNICAL_BLOCKED')
            self.assertEqual(result['token_limit_omissions'], [])

    def test_citation_rejection_after_a_skipped_range_is_not_bypassed(self):
        value, schedule = two_ranges()
        model, _ = provider()
        def call(**request):
            payload = request['user_payload']
            if payload['phase'] == 'package_review' and payload['primary_refs'] == ['D1:0']:
                raise limited()
            answer = model(**request)
            if payload['phase'] == 'assessment':
                answer['rows'][0]['finding_ids'] = ['invented']
            return answer
        with patch.object(p, 'partitions', side_effect=schedule):
            result = p.assess(value, call=call)
        self.assertFalse(any(r['kind'] == 'alignment' for r in result['rows']))
        self.assertTrue(result['quarantined'])
        self.assertEqual(result['recommendation'], 'investigate_further')

    def test_report_files_are_written_when_every_reading_is_token_limited(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            evidence, brief = root / 'evidence.json', root / 'brief.md'
            artifacts = {'request_capture_evidence_path': str(evidence), 'request_capture_brief_path': str(brief)}
            outcome = p.run(root, packet(), artifacts, request_id='synthetic',
                            call=lambda **kw: (_ for _ in ()).throw(limited()))
            self.assertEqual(outcome['status'], 'PARTIAL_PRELIMINARY_ASSESSMENT')
            self.assertTrue(brief.is_file())
            self.assertIn(TITLE, brief.read_text())
            self.assertEqual(json.loads(evidence.read_text())['rows'], [])

    def test_finished_run_has_none_recorded_in_final_section(self):
        model, _ = provider()
        text = render(p.assess(packet(), call=model), packet())
        self.assertTrue(text.rstrip().endswith('None recorded.'))
        self.assertIn(TITLE, text)


if __name__ == '__main__':
    unittest.main()
