"""Audit labels qualify automated approval without changing evidence or decisions."""
from copy import deepcopy
import unittest

from scripts.tests.test_preliminary_capture import packet, provider
from scripts.tests.test_preliminary_decision_pipeline import CORE, fixture, harness
from common import preliminary_capture as p
from capture.preliminary_render import render


LABEL = r'Audited\*'


class PreliminaryAuditLabelTests(unittest.TestCase):
    def assessment(self, **options):
        model, _ = provider(**options)
        value = packet()
        return p.assess(value, call=model), value

    def test_legend_is_prominent_and_repeated_for_standalone_appendix(self):
        result, value = self.assessment()
        main, appendix = render(result, value).split('## Appendix:', 1)
        for section in (main.split('## Package Status')[0], appendix):
            self.assertIn(LABEL, section)
            self.assertIn('meaning or attached evidence may be incomplete', section)
            self.assertIn('not human verification', section)

    def test_supported_package_and_judgment_rows_have_literal_asterisk(self):
        result, value = self.assessment()
        text = render(result, value)
        for phrase in ('Calibrate flow meters.', 'Access authorization is required before site work.',
                       'Use a readable font.', 'Calibration is a plausible capability overlap.',
                       'Investigate the opportunity.'):
            lines = [line for line in text.splitlines() if line.startswith('- **') and phrase in line]
            self.assertTrue(lines, phrase)
            self.assertTrue(all('Audit status: ' + LABEL in line for line in lines), phrase)
        self.assertNotIn('package finding checked;', text)

    def test_rejected_interpretations_are_not_rebranded_as_audited(self):
        result, value = self.assessment(reject_strategy=True)
        text = render(result, value)
        review = text.split('## Interpretations to Verify', 1)[1].split('## Package Status', 1)[0]
        self.assertIn('Unverified interpretation', review)
        self.assertNotIn('Audit status: ' + LABEL, review)
        self.assertFalse(result['rows'])

    def test_missing_or_adverse_approval_does_not_receive_audited_badge(self):
        for check in ({}, {'verdict': 'uncertain'}, {'verdict': 'unsupported'}):
            with self.subTest(check=check):
                result, value = self.assessment()
                result['findings']['F1-1']['audit'] = check
                result['rows'][0]['audit'] = check
                text = render(result, value)
                for phrase in ('**F1-1:', '**Calibration is a plausible capability overlap.'):
                    line = next(line for line in text.splitlines() if phrase in line)
                    self.assertIn('Audit status: Unverified', line)
                    self.assertNotIn('Audit status: ' + LABEL, line)

    def test_judgment_requires_qualifier_approval_for_badge(self):
        result, value = self.assessment()
        result['rows'][0]['audit'] = {'verdict': 'supported'}
        text = render(result, value)
        line = next(line for line in text.splitlines() if '**Calibration is a plausible' in line)
        self.assertIn('Audit status: Unverified', line)

    def test_status_market_and_superseded_records_are_also_qualified(self):
        result, value = self.assessment()
        status = deepcopy(result['findings']['F1-1'])
        status.update(id='F-status', statement='This package is a draft.')
        status['decision']['topic'] = 'document_status'
        market = deepcopy(status)
        market.update(id='F-market', statement='Package names an incumbent.')
        market['decision']['topic'] = 'market'
        result['findings'].update({'F-status': status, 'F-market': market})
        old = deepcopy(status)
        old.update(id='F-old', statement='Historical deadline.')
        old['reconciliation'] = {'state': 'superseded', 'governing_ids': ['F-status'], 'reason': 'Replaced.'}
        result['superseded_findings'] = {'F-old': old}
        text = render(result, value)
        for heading, phrase in (('Package Status', 'This package is a draft.'),
                               ('Market Context', 'Package names an incumbent.'),
                               ('Superseded Terms - History Only', 'Historical deadline.')):
            section = text.split(heading, 1)[1]
            line = next(line for line in section.splitlines() if phrase in line)
            self.assertIn('Audit status: ' + LABEL, line)
        self.assertIn('(not active)', text)

    def test_earlier_source_approval_does_not_certify_failed_reconciliation(self):
        value, rows = fixture([CORE, ('Seven references.', {'topic': 'experience'}),
                              ('Access authorization before work.', {'topic': 'acquisition'})])
        model, _ = harness(rows, fail_reconciliation=True)
        result = p.assess(value, call=model)
        text = render(result, value)
        review = text.split('## Interpretations to Verify', 1)[1].split('## Package Status', 1)[0]
        self.assertIn('Unverified interpretation', review)
        self.assertIn('earlier automated source audit', review)
        self.assertIn('remains unverified', review)
        self.assertNotIn('Audit status: ' + LABEL, review)

    def test_rendering_preserves_findings_sources_and_recommendation(self):
        result, value = self.assessment(proposal='pursue_discovery')
        before, original = deepcopy(result), deepcopy(value)
        text = render(result, value)
        self.assertEqual(result, before)
        self.assertEqual(value, original)
        self.assertEqual(result['recommendation'], 'pursue_discovery')
        self.assertIn('not an unconditional bid authorization', text)
        self.assertIn('## Requirements not processed because of token limits in the test environment', text)


if __name__ == '__main__':
    unittest.main()
