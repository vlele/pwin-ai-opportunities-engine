"""Replay saved public-package admission, without any provider calls or new prose.

This tests publication mechanics against old model outputs. It is not an updated
capture or proof that new prompts produce better model judgments.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.preliminary_decisions import admit_reconciliation


def replay():
    fixture = json.loads((Path(__file__).parent / 'fixtures/preliminary_scope.json').read_text())
    result = {'mode': 'offline_saved_response_admission', 'api_calls': 0,
              'new_capture_generated': False, 'cases': {}}
    for name, case in fixture['cases'].items():
        active, history, withheld = admit_reconciliation(case['findings'], case['relations'], case['checks'])
        assert set(active) | set(history) | set(withheld) == set(case['findings'])
        result['cases'][name] = {
            'origin': case['origin'], 'source_evidence_sha256': case['evidence_sha256'],
            'candidates': len(case['findings']), 'retained_active_ids': list(active),
            'retained_history_ids': list(history), 'withheld': withheld,
            'meaning': 'Admission mechanics only; preserved verdicts are not a new semantic audit.',
        }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite an offline result.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = replay()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {'retained': len(r['retained_active_ids']), 'withheld': len(r['withheld'])}
                      for name, r in result['cases'].items()}))
