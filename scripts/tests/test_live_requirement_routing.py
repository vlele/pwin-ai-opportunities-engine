"""Explicit opt-in provider checks, separate from deterministic routing tests."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import requirement_routing as rr, requirement_context as rc, semantic_contract as c


@unittest.skipUnless(os.getenv('PWIN_LIVE_ROUTING_TEST') == '1', 'Opt-in required: real API charges')
class LiveRoutingTests(unittest.TestCase):
    def run_case(self, name, statements):
        import httpx
        from openai import OpenAI
        from common import openai_reasoning as api
        output = Path(os.environ['PWIN_LIVE_TEST_AUDIT_DIR']) / (name + '.json')
        self.assertFalse(output.exists(), 'Never overwrite or silently resample a live result')
        output.parent.mkdir(parents=True, exist_ok=True)
        spans, contexts = {}, []
        for index, (text, _, _) in enumerate(statements):
            ref = f'D{index}:0'
            spans[ref] = {'kind': 'package', 'source_id': f'D{index}', 'offset': 0, 'text': text}
            anchor = [{'ref': ref, 'quote': text}]
            parent = {'status': 'current', 'record_kind': 'requirement', 'area': 'scope',
                      'task': True, 'focus': anchor, 'evidence': anchor, 'supersedes': [], 'meaning': text}
            contexts.append(rc.context(f'R{index}', parent, spans))
        replies = []
        def observe(response):
            response.read()
            data = response.json()
            replies.append({'http_status': response.status_code, 'model': data.get('model'),
                            'usage': data.get('usage'), 'request_id': response.headers.get('x-request-id')})
        prompt = c.DECOMPOSE_PROMPT + '\n' + rc.DECOMPOSITION_INTERFACE
        payload, schema = rc.decomposition_payload(contexts), rc.decomposition_schema(contexts)
        with OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url=os.getenv('OPENAI_BASE_URL'), max_retries=0,
                    http_client=httpx.Client(event_hooks={'response': [observe]})) as client:
            with patch.object(api, '_openai_client', return_value=client):
                raw = api._call_openai_json(system_prompt=prompt, user_payload=payload, model='gpt-5.4-mini',
                    reasoning_effort='medium', timeout_seconds=180,
                    response_schema={'name': 'routing_probe', 'schema': schema, 'strict': True})
        receipt = {'model': 'gpt-5.4-mini', 'reasoning_effort': 'medium', 'prompt': prompt,
                   'payload': payload, 'schema': schema, 'response': raw, 'http_responses': replies,
                   'expected': statements, 'passed': False}
        output.write_text(json.dumps(receipt, indent=2) + '\n')
        self.assertEqual([r['http_status'] for r in replies], [200])
        checked = rc.validate_decomposition(raw, contexts, spans)
        for index, (_, categories, applicability) in enumerate(statements):
            parts = checked[f'R{index}']['components']
            self.assertEqual({p['category'] for p in parts}, set(categories), f'R{index} wrong category')
            self.assertTrue(all(p['applicability'] == applicability for p in parts), f'R{index} wrong applicability')
            for part in parts:
                if part['category'] in {'administrative_formatting', 'contract_terms'}:
                    self.assertNotEqual(rr.route(part), 'vendor_comparison')
                elif applicability == 'prime_contractor':
                    self.assertEqual(rr.route(part), 'vendor_comparison')
        receipt.update(passed=True, validated=checked)
        output.write_text(json.dumps(receipt, indent=2) + '\n')

    def test_software_delivery_vs_proposal_mechanics(self):
        self.run_case('routing-software', [
            ('The contractor shall develop geospatial processing software with 99.9 percent operational availability.',
             ['technical_capability'], 'prime_contractor'),
            ('Relevant experience must include three geospatial software deployments completed within five years.',
             ['past_performance'], 'prime_contractor'),
            ('The offeror must hold current ISO 27001 certification.', ['compliance_certification'], 'prime_contractor'),
            ('Proposal pages must be 8 1/2" x 11", use 11-point font, and be uploaded as PDF to Portal Q.',
             ['administrative_formatting'], 'prime_contractor'),
            ('The contract uses time-and-materials pricing and payment terms are Net-30.', ['contract_terms'], 'prime_contractor'),
        ])

    def test_physical_installation_embedded_in_pricing(self):
        self.run_case('routing-physical', [
            ('CLIN 1: Contractor installation of water pumps is firm-fixed-price.',
             ['technical_capability', 'contract_terms'], 'prime_contractor'),
            ('The contractor shall restore pump service within four hours of an outage.', ['technical_capability'], 'prime_contractor'),
            ('Offerors must hold a current electrical contractor license; include a copy with the proposal.',
             ['compliance_certification', 'administrative_formatting'], 'prime_contractor'),
            ('The Government, not the contractor, will issue access badges.', ['contract_terms'], 'not_prime_contractor'),
        ])

    def test_analytical_performance_vs_bid_formatting(self):
        self.run_case('routing-laboratory', [
            ('The contractor shall test drinking-water samples and report detection limits within 48 hours.',
             ['technical_capability'], 'prime_contractor'),
            ('The offeror must have two completed water-testing projects in the last three years.', ['past_performance'], 'prime_contractor'),
            ('The performing laboratory must hold current ISO 17025 accreditation.', ['compliance_certification'], 'prime_contractor'),
            ('Proposal technical volumes may not exceed twenty pages and must be submitted by 15:00 UTC on 3 November.',
             ['administrative_formatting'], 'prime_contractor'),
            ('Invoices are payable Net-30 and the ordinary place of performance is the contractor laboratory.',
             ['contract_terms'], 'prime_contractor'),
        ])


if __name__ == '__main__':
    unittest.main()
