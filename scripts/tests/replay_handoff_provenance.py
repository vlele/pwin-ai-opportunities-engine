"""Reconstruct saved mapping attempts offline; no new semantic verdicts or API calls."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, requirement_context as context
from common.evidence_selection import EvidenceTransport
from inline_fact_fixture import inline_saved_mapping


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--record-invalid', action='store_true',
                        help='Record structural failures without repairing them or claiming they pass.')
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    audit = args.run / 'audit'
    state_path = Path(read(audit / 'outcome-summary.json')['checkpoint_state_path'])
    spans = read(state_path)['understanding_audit']['span_registry']
    original_files = [state_path, audit / 'engine-result.json', args.run / 'REPORT.md']
    original_files += list(audit.glob('request-*.json')) + list(audit.glob('response-*.json'))
    before = {str(p): sha(p) for p in original_files}
    output = {'mode': 'offline structural replay; semantic approval not established',
              'api_calls': 0, 'attempts': []}
    previous = {}
    for path in sorted(audit.glob('request-*.json')):
        request = read(path)
        if not request['stage'].startswith('semantic-inventory-package-'):
            continue
        response_path = path.with_name(path.name.replace('request-', 'response-'))
        if not response_path.exists():
            continue
        payload = json.loads(request['request']['messages'][1]['content'])
        batch = h._batch(payload['fact_ledger'], spans, 'package')
        raw = json.loads(read(response_path)['content'])
        wire = EvidenceTransport(batch['schema'], batch['payload'])
        if set(raw) == {'repairs'}:
            repair = wire.selection_repair(previous[request['stage']])
            assert repair is not None, 'No saved invalid selections for this repair.'
            raw = repair.merge(raw)
        previous[request['stage']] = deepcopy(raw)
        migrated = 'fact_coverage' in raw
        try:
            fixture = inline_saved_mapping(raw)
            decoded = wire.resolve(fixture)
            original = deepcopy(decoded)
            mapped = h.validate_batch(decoded, batch)
            assert decoded == original
        except ValueError as error:
            if not args.record_invalid:
                raise
            output['attempts'].append({'request': path.name, 'stage': request['stage'],
                'structural_mapping_admissible': False, 'error': str(error),
                'legacy_fixture_translation_requested': migrated,
                'semantic_verdict': 'not_run'})
            continue
        canonical = deepcopy(decoded)
        for key in ('requirements', 'quoted_vendor_context'):
            for row in canonical[key]:
                row.pop('originating_fact_ids')
        assert mapped['inventory'] == context.validate_parent_inventory(canonical, batch['payload']['spans'], fragment=True)
        targets = h.handoff_targets(batch, mapped)
        for target in targets:
            fid = target['id'].removeprefix('handoff-')
            assert target['fact'] == payload['fact_ledger'][fid]
            assert set(target['fact']['refs']).issubset(target['spans'])
            for record in target['retained_records']:
                for anchor in record['evidence']:
                    assert anchor['quote'] in target['spans'][anchor['ref']]['text']
        schedule = list(h.audit_batches(targets))
        output['attempts'].append({'request': path.name, 'stage': request['stage'],
            'structural_mapping_admissible': True, 'fact_count': len(targets),
            'legacy_fixture_translation_requested': migrated,
            'semantic_verdict': 'not_run', 'selected_records_unchanged': True,
            'fact_provenance': mapped['fact_provenance'],
            'handoff_audit_requests': len(schedule), 'handoff_audit_request_chars': [
                h._size(h.HANDOFF_AUDIT_PROMPT, {'targets': b}, h.plan.audit_schema(b)) for b in schedule],
            'targets': targets})
    assert output['attempts'], 'No saved mapping attempts found.'
    output['original_files_unchanged'] = all(sha(Path(p)) == value for p, value in before.items())
    assert output['original_files_unchanged']
    output['original_engine_status'] = read(audit / 'engine-result.json')['status']
    output['structurally_admissible_attempts'] = sum(a['structural_mapping_admissible'] for a in output['attempts'])
    output['rejected_attempts'] = len(output['attempts']) - output['structurally_admissible_attempts']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({**{k: v for k, v in output.items() if k != 'attempts'}, 'attempts': [
        {k: v for k, v in attempt.items() if k not in ('targets', 'fact_provenance')} for attempt in output['attempts']]}, indent=2))


if __name__ == '__main__':
    main()
