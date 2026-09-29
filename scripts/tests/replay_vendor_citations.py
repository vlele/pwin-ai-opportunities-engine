"""Test saved vendor responses offline plus an explicitly mocked complete citation.

Only a copied test response is changed. This is not a runtime repair algorithm,
semantic approval, or permission to replace failed receipts with passing fixtures.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, capture_understanding as u
from common.evidence_selection import EvidenceTransport


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.run.resolve()):
        raise ValueError('Write offline results outside the preserved live run.')
    read = lambda p: json.loads(p.read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    files = [p for p in args.run.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    before = {str(p): sha(p) for p in files}
    saved = read(args.audit / 'checkpoint-before/model-input.json')
    packet = read(args.run / 'audit/source-packet.json')
    assert saved['packet'] == packet
    batch = h._batch({}, u.build_spans(packet, saved['user_answers']), 'vendor')
    wire = EvidenceTransport(batch['schema'], batch['payload'])
    out = {'mode': 'offline saved failure and mocked complete-citation replay',
           'api_calls': 0, 'semantic_verdict': 'not_run', 'attempts': []}
    with patch('socket.socket.connect', side_effect=AssertionError('No network in offline replay.')):
        for path in sorted(args.audit.glob('response-*.json')):
            response = read(path)
            if not response['stage'].startswith('semantic-inventory-vendor-'):
                continue
            raw = json.loads(response['content'])
            decoded = wire.resolve(raw)
            try:
                h.validate_batch(decoded, batch)
            except ValueError as error:
                original_error = str(error)
                assert original_error == 'Vendor disposition cites a different source.'
            else:
                raise AssertionError('Saved failed response unexpectedly accepted.')
            mock = deepcopy(raw)
            additions = []
            for ref, disposition in decoded['vendor_coverage'].items():
                for index in disposition['claims']:
                    claim = decoded['claims'][index]
                    if ref in {a['ref'] for a in claim['evidence']}:
                        continue
                    # Fixture admission only: this replay specifically tests duplicate
                    # one-line fields, not arbitrary evidence repair or equivalence.
                    text = batch['payload']['spans'][ref]['text']
                    assert len(text.splitlines()) == 1 and text
                    assert any(text == a['quote'] for a in claim['evidence'])
                    selection = {'start': {'ref': ref, 'line': 1}, 'end': {'ref': ref, 'line': 1}}
                    mock['claims'][index]['evidence'].append(selection)
                    additions.append({'claim_index': index, 'source_ref': ref,
                                      'profile_field': batch['payload']['spans'][ref]['profile_field'],
                                      'selection': selection, 'quote': text})
            assert additions, 'No missing duplicate citations in this fixture.'
            resolved = wire.resolve(mock)
            mapped = h.validate_batch(resolved, batch)
            targets = h.handoff_targets(batch, mapped)
            assert len(targets) == 1
            assert mock['vendor_coverage'] == raw['vendor_coverage']
            stripped = deepcopy(mock)
            for addition in additions:
                stripped['claims'][addition['claim_index']]['evidence'].remove(addition['selection'])
            assert stripped == raw, 'The mock may change citations only.'
            out['attempts'].append({'response': path.name, 'original_error': original_error,
                'original_rejected': True, 'mock_complete_citations_accepted': True,
                'citation_additions': additions, 'claims_retained': len(mapped['inventory']['claims']),
                'audit_target': targets[0]})
    assert out['attempts'], 'No saved vendor responses found.'
    out['original_files_unchanged'] = all(sha(Path(p)) == value for p, value in before.items())
    assert out['original_files_unchanged']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({**out, 'attempts': [{k: v for k, v in a.items() if k != 'audit_target'}
                                        for a in out['attempts']]}, indent=2))


if __name__ == '__main__':
    main()
