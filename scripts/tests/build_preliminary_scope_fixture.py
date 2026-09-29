"""Export only public-package records from a saved run, without model calls."""
import argparse
import hashlib
import json
from pathlib import Path


def build(root):
    cases = {}
    for name in ('ebms', 'fbmt', 'ces'):
        audit = root / name / 'audit'
        output = json.loads((audit / 'engine-result.json').read_text())
        evidence_path = Path(output['evidence_path'])
        evidence = json.loads(evidence_path.read_text())
        cases[name] = {
            'origin': f'{root.name}/{name}',
            'evidence_sha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            'findings': evidence['reconciliation_candidates'],
            'relations': evidence['reconciliation_response']['relations'],
            'checks': evidence['reconciliation_audit']['checks'],
            'category_failures': [q for q in evidence['quarantined']
                                  if q['error'] == 'Acquisition dimensions belong only to acquisition findings.'],
        }
    return {'description': 'Unmodified public-package records; saved approvals are not ground truth.', 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite a saved fixture.')
    args.output.write_text(json.dumps(build(args.run_root), indent=2, ensure_ascii=True) + '\n')
