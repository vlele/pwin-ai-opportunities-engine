"""Replay saved relationship receipts, never generate or invent new audit verdicts."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.preliminary_decisions import admit_reconciliation
from common.preliminary_review import review_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = Path(__file__).parent / 'fixtures/preliminary_review_policy.json'
    saved = json.loads(fixture.read_text())
    before = deepcopy(saved)
    output = {'mode': 'offline_saved_responses', 'api_calls': 0,
              'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'cases': {}}
    lines = ['# Documented Uncertainty: Offline Saved-Response Replay', '',
             'No new model call, capture recommendation or live semantic approval was generated.',
             'Saved audit verdicts were replayed unchanged. They are not ground truth.', '',
             '| Case | Relationship candidates | Accepted active | History | Documented unverified |',
             '| --- | ---: | ---: | ---: | ---: |']
    for name, case in saved['cases'].items():
        active, history, pending = admit_reconciliation(case['findings'], case['relations'], case['checks'])
        state = {'source_registry': case['source_registry'], 'findings': active,
                 'reconciliation_candidates': case['findings'],
                 'quarantined': [{'id': key, 'phase': 'reconciliation_audit', 'error': reason,
                                 'raw': case['findings'][key]} for key, reason in pending.items()]}
        output['cases'][name] = {'origin': case['origin'], 'source_evidence_sha256': case['evidence_sha256'],
            'candidate_count': len(case['findings']), 'saved_audit_check_count': len(case['checks']),
            'active_findings': active, 'history': history, 'unverified_reasons': pending,
            'review_items': review_items(state)}
        lines.append(f'| {name.upper()} | {len(case["findings"])} | {len(active)} | {len(history)} | {len(pending)} |')
    ebms = output['cases']['ebms']
    assert 'F4-9' in ebms['active_findings']
    assert 'F1S-1' in ebms['unverified_reasons']
    assert not output['cases']['ietss']['active_findings']
    assert saved == before
    lines += ['', '## EBMS Example', '',
              'F4-9 survives because its own saved independent relationship verdict is supported. '
              'Unrelated failures no longer suppress every record with the same topic label.', '',
              '> ' + ebms['active_findings']['F4-9']['statement'].replace('\n', ' '), '',
              'F1S-1 remains unverified for its own recorded audit failure. No quotation was repaired.', '',
              '## IETSS Limitation', '',
              'The saved run stopped before the relationship audit. It contains zero such checks. '
              'This replay therefore approves zero governing interpretations and documents all candidates '
              'for review. It does not claim to have fixed the model responses or manufactured an audit.', '',
              'Separate synthetic tests check that malformed links do not poison independently approved '
              'targets. That is a code-isolation test, not a live IETSS result.', '',
              '## Release Boundary', '',
              'Offline tests establish routing, failure isolation, citation filtering and report labeling. '
              'Live classification and judgment quality remain unverified for this change. '
              'No merge or push was performed by this replay.', '']
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'saved-admission.json').write_text(json.dumps(output, indent=2) + '\n')
    (args.output / 'REPORT.md').write_text('\n'.join(lines))
    print(json.dumps({'output': str(args.output), 'api_calls': 0,
                      'cases': {k: {'active': len(v['active_findings']), 'unverified': len(v['review_items'])}
                                for k, v in output['cases'].items()}}))


if __name__ == '__main__':
    main()
