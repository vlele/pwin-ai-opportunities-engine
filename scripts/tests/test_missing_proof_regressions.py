"""Historical responses are immutable negative controls, not semantic heuristics."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_contract as c, semantic_plan as s, semantic_policy as policy
from common import requirement_routing as routing
from tests.test_requirement_routing import fixture

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/missing_proof_regressions.json').read_text())


class MissingProofRegressions(unittest.TestCase):
    def test_all_five_verbatim_bad_reasons_cannot_authorize_unrelated(self):
        spans, inv = fixture()
        job = next(c.component_jobs(s.comparison_pairs(inv)))
        self.assertEqual(len(FIXTURE['cases']), 5)
        for case in FIXTURE['cases']:
            with self.subTest(stage=case['stage']):
                # Reuse the saved explanation as opaque text; no keyword-based label repair.
                raw = {k: job[k] for k in ('pair_id', 'component_id', 'component_kind')}
                raw.update(status=case['status'], reason=case['reason'], supported_scope='', evidence=[])
                before = deepcopy(raw)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(raw, c.component_response_schema(job))
                with self.assertRaises(ValueError):
                    c.validate_component_response(raw, job, spans)
                self.assertEqual(raw, before)

    def test_strict_boundary_is_centralized_and_wired_to_both_live_prompts(self):
        _, inv = fixture()
        prompt = s.audit_prompt([{'kind': 'comparison', 'required': inv['requirements'][0]}])
        boundary = policy.CATEGORIZED_MISSING_PROOF_POLICY
        self.assertIn(boundary, c.ROUTED_COMPONENT_PROMPT)
        self.assertIn(boundary, prompt)
        self.assertIn(policy.CATEGORIZED_AUDIT_LABEL_POLICY, prompt)
        self.assertNotIn('Concrete different performed work remains unrelated', prompt)

    def test_fixture_never_becomes_production_keyword_rules(self):
        _, inv = fixture()
        prompt = s.audit_prompt([{'kind': 'comparison', 'required': inv['requirements'][0]}])
        for case in FIXTURE['cases']:
            self.assertNotIn(case['reason'], c.ROUTED_COMPONENT_PROMPT)
            self.assertNotIn(case['reason'], prompt)
        for kind in ('requirement', 'package_coverage', 'claim_coverage'):
            self.assertNotIn(policy.CATEGORIZED_AUDIT_LABEL_POLICY, s.audit_prompt([{'kind': kind}]))

    def test_negative_audit_is_binding_and_not_normalized_to_pass(self):
        target = {'id': 'E0', 'kind': 'comparison'}
        raw = {'checks': {'E0': {'verdict': 'unsupported',
              'reason': 'No supplied proof warrants missing, not unrelated.'}}}
        before = deepcopy(raw)
        checked = s.validate_audit(raw, [target])
        self.assertFalse(checked['passed'])
        self.assertEqual(raw, before)
        self.assertEqual(checked['checks'][0]['verdict'], 'unsupported')

    def test_nonprime_context_remains_unrelated_not_missing(self):
        _, inv = fixture()
        part = inv['requirements'][0]['components'][-1]
        self.assertEqual(routing.route(part), 'unrelated')
        self.assertNotIn('K6', routing.assessed_components(inv['requirements'][0]))


if __name__ == '__main__':
    unittest.main()
