"""Rebuild audit requests from saved live responses; never call a provider.

Pass --run-dir with audit/source-packet.json and response-*.json. Private fixtures
remain outside the repository. This checks lossless representation and request
budgets, not the semantic truth of the saved model decisions.
"""
import argparse
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u, semantic_plan as plan, semantic_contract as contract
from common import audit_evidence_encoding as encoding
from common.evidence_selection import EvidenceTransport
from common.understanding_checkpoints import request_chars, MAX_MODEL_INPUT_CHARS


def run(run_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=False)
    read = lambda path: json.loads(path.read_text())
    packet = read(run_dir / 'audit/source-packet.json')
    saved, used = {}, {}
    for path in sorted((run_dir / 'audit').glob('response-*.json')):
        row = read(path)
        saved.setdefault(row['stage'], []).append(json.loads(row['content']))
    original_batcher = plan.audit_batches
    report = {'mode': 'offline saved-response replay; no provider or checkpoint writes',
              'source_run': str(run_dir), 'measurements': [], 'all_batches_fit': False}

    def response(**request):
        frame = inspect.currentframe()
        try:
            while frame and not (frame.f_code.co_name == 'invoke' and 'stage' in frame.f_locals):
                frame = frame.f_back
            if frame is None:
                raise RuntimeError('No saved stage identity; provider fallback is forbidden.')
            stage = frame.f_locals['stage']
        finally:
            del frame
        index = used.get(stage, 0)
        if stage not in saved or index >= len(saved[stage]):
            raise RuntimeError('No saved response for ' + stage + '; provider fallback is forbidden.')
        used[stage] = index + 1
        return deepcopy(saved[stage][index])

    def inspect_batches(records, spans, answers=None, previous_questions=None, independent_questions=None, **kwargs):
        before = deepcopy((records, spans))
        for target in records:
            if target['kind'] != 'package_coverage':
                continue
            payload = contract.audit_payload([target], spans, answers, previous_questions, independent_questions)
            schema = plan.audit_schema([target])
            prompt = plan.audit_prompt([target])
            with patch.object(encoding, 'encode', side_effect=deepcopy):
                legacy = EvidenceTransport(schema, payload)
            wire = EvidenceTransport(schema, payload)
            assert not wire.active and not legacy.active
            restored = encoding.decode(wire.payload)
            assert restored == legacy.payload
            assert wire.payload['spans'] == legacy.payload['spans']
            assert wire.schema == legacy.schema
            report['measurements'].append({
                'target_id': target['id'], 'before_chars': request_chars(prompt, legacy.payload, legacy.schema),
                'after_chars': request_chars(prompt, wire.payload, wire.schema),
                'max_chars': MAX_MODEL_INPUT_CHARS, 'receipt': wire.audit_evidence_encoding,
                'exact_round_trip': True, 'all_source_spans_retained': True,
                'unchanged_prompt_and_response_schema': True,
                'requirements': len(target['value']['requirements']),
                'components': sum(len(r.get('components', [])) for r in target['value']['requirements'])})
            (output_dir / 'package-coverage-wire.json').write_text(json.dumps(wire.payload, indent=2) + '\n')
        batches = list(original_batcher(records, spans, answers, previous_questions, independent_questions, **kwargs))
        report['batches'] = []
        for batch in batches:
            size = plan.audit_request_chars(batch, spans, answers, previous_questions, independent_questions)
            report['batches'].append({'kind': batch[0]['kind'], 'target_ids': [r['id'] for r in batch], 'chars': size})
            assert size <= MAX_MODEL_INPUT_CHARS
        assert (records, spans) == before
        assert [r for batch in batches for r in batch] == records
        report['all_batches_fit'] = True
        report['all_targets_retained_in_order'] = True
        raise ValueError('Offline audit request inspection complete; semantic auditor deliberately not invoked.')

    with patch.object(plan, 'audit_batches', side_effect=inspect_batches):
        result = u.analyze_packet(packet, [], {}, call=response)
    report['saved_responses_consumed'] = sum(used.values())
    report['terminal_note'] = result.get('pipeline_errors', [])
    (output_dir / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report['all_batches_fit'] and bool(report['measurements'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.run_dir, args.output_dir) else 1)
