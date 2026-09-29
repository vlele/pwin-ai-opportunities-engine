"""Export public-package reconciliation receipts only. No paid requests."""
import argparse
import hashlib
import json
from pathlib import Path


def build(root):
    cases = {}
    for name in ('ietss', 'ebms'):
        audit = root / name / 'audit'
        output = json.loads((audit / 'engine-result.json').read_text())
        path = Path(output['evidence_path'])
        saved = json.loads(path.read_text())
        findings = saved['reconciliation_candidates']
        refs = {a['ref'] for r in findings.values() for a in r['evidence']}
        cases[name] = {
            'origin': f'{root.name}/{name}',
            'evidence_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'findings': findings,
            'relations': saved['reconciliation_response']['relations'],
            'checks': saved.get('reconciliation_audit', {}).get('checks', {}),
            'source_registry': {k: saved['source_registry'][k] for k in refs},
        }
        assert all(s['kind'] == 'package' for s in cases[name]['source_registry'].values())
    return {'description': 'Unmodified saved public-package data; audit receipts are not ground truth.', 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite the saved fixture.')
    args.output.write_text(json.dumps(build(args.run_root), indent=2, ensure_ascii=True) + '\n')
