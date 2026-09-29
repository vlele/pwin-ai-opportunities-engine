"""Copy public-package failure records from a saved replay; never call a model.

Keeps original responses separate from test-only expected variants. No vendor
profile, credentials, request headers, or model-private data are exported.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.evidence_selection import EvidenceTransport
from common.preliminary_capture import review_schema


def build(root):
    result = {'description': 'Exact saved public-package contract failures; not live semantic approvals.',
              'reconciliations': {}, 'rejected_findings': []}
    for case in json.loads((root / 'cases.json').read_text()):
        audit = root / case['id'] / 'audit'
        output = json.loads((audit / 'engine-result.json').read_text())
        evidence = json.loads(Path(output['evidence_path']).read_text())
        for path in sorted(audit.glob('response-*.json')):
            receipt = json.loads(path.read_text())
            if receipt['stage'] != 'preliminary-reconciliation':
                continue
            result['reconciliations'][case['id']] = {
                'origin': f"{root.name}/{case['id']}/audit/{path.name}",
                'receipt_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'response': json.loads(receipt['content']),
                'findings': evidence['reconciliation_candidates']}
        sources = {k: v for k, v in evidence['source_registry'].items() if v['kind'] == 'package'}
        wire = EvidenceTransport(review_schema(sources), {'spans': sources})
        for item in evidence['quarantined']:
            if item['error'] not in {
                    'Acquisition findings need an explicit selection or narrative basis.',
                    'Unreviewed form selection cannot be established from printed alternatives.'}:
                continue
            decoded = wire.resolve({'rows': [item['raw']]})['rows'][0]
            refs = {a['ref'] for a in decoded['evidence']}
            result['rejected_findings'].append({'case': case['id'], 'id': item['id'],
                'original_error': item['error'], 'raw': item['raw'], 'decoded': decoded,
                'sources': {ref: sources[ref] for ref in refs}})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite a saved fixture.')
    fixture = build(args.run_root)
    args.output.write_text(json.dumps(fixture, indent=2, ensure_ascii=True) + '\n')
    print(json.dumps({'reconciliations': len(fixture['reconciliations']),
                      'rejected_findings': len(fixture['rejected_findings'])}))
