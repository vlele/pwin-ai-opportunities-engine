"""Replay saved pre-audit model responses; prove scheduling without calling an API.

Stops before the independent auditor. Synthetic reducer verdicts below test the
gate's wiring only; they are not a semantic pass and never generate a capture memo.
"""
import argparse
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u, semantic_plan as s, semantic_contract as c
from common import audit_partitioning as a
from common.audit_evidence_encoding import decode
from common.evidence_selection import EvidenceTransport
from common.understanding_checkpoints import request_chars


def run(source, output):
    output.mkdir(parents=True, exist_ok=False)
    read = lambda path: json.loads(path.read_text())
    packet = read(source / 'audit/source-packet.json')
    saved, used = {}, {}
    for path in sorted((source / 'audit').glob('response-*.json')):
        row = read(path)
        saved.setdefault(row['stage'], []).append(json.loads(row['content']))
    report = {'source_run': str(source), 'mode': 'offline saved-response replay',
              'api_calls': 0, 'semantic_audit_run': False, 'memo_generated': False,
              'phases': [], 'negative_controls': {}}
    original_prepare, original_batches = a.prepare, s.audit_batches
    captured = {}

    def provider(**request):
        frame = inspect.currentframe()
        try:
            while frame and not (frame.f_code.co_name == 'invoke' and 'stage' in frame.f_locals):
                frame = frame.f_back
            if frame is None:
                raise RuntimeError('Missing saved stage identity; live fallback forbidden.')
            stage = frame.f_locals['stage']
        finally:
            del frame
        index = used.get(stage, 0)
        if stage.startswith('claim-evidence-') or stage not in saved or index >= len(saved[stage]):
            raise RuntimeError('No permitted saved response for ' + stage)
        used[stage] = index + 1
        return deepcopy(saved[stage][index])

    def prepare(target, spans, **kwargs):
        result = original_prepare(target, spans, **kwargs)
        captured.update(prepared=deepcopy(result), target=deepcopy(target), spans=deepcopy(spans))
        return result

    def batcher(records, spans, answers=None, previous_questions=None, independent_questions=None, **kwargs):
        batches = list(original_batches(records, spans, answers, previous_questions, independent_questions, **kwargs))
        before = deepcopy((records, spans))
        phase = {'name': 'before_comparison' if not report['phases'] else 'comparison_results',
                 'saved_comparator_responses_consumed': sum(n for k, n in used.items() if k.startswith('component-')),
                 'batches': []}
        for i, batch in enumerate(batches):
            payload = c.audit_payload(batch, spans, answers, previous_questions, independent_questions)
            wire = EvidenceTransport(s.audit_schema(batch), payload)
            assert not wire.active
            canonical = deepcopy(payload)
            for span in canonical['spans'].values():
                span.pop('text_regions', None)
            assert decode(wire.payload) == canonical
            n = request_chars(s.audit_prompt(batch), wire.payload, wire.schema)
            assert n <= 640000
            assert n == s.audit_request_chars(batch, spans, answers, previous_questions, independent_questions)
            phase['batches'].append({'kind': batch[0]['kind'], 'target_ids': [t['id'] for t in batch], 'request_chars': n,
                                    'source_spans': len(payload['spans']), 'round_trip_exact': True})
        assert (records, spans) == before
        report['phases'].append(phase)
        if len(report['phases']) == 1:
            assert phase['saved_comparator_responses_consumed'] == 0
            return iter(batches)
        raise ValueError('Offline partition replay complete; independent model auditor deliberately not invoked.')

    with patch.object(a, 'prepare', side_effect=prepare), patch.object(s, 'audit_batches', side_effect=batcher):
        result = u.analyze_packet(packet, [], {}, call=provider)
    report['terminal_note'] = result.get('pipeline_errors', [])
    if captured:
        p, target, spans = captured['prepared'], captured['target'], captured['spans']
        checks = {t['id']: {'verdict': 'supported', 'reason': 'Synthetic receipt for gate verification only.'} for t in p['targets']}
        report['synthetic_reduce_passed'] = a.reduce(deepcopy(p), target, spans, checks)['verdict'] == 'supported'
        for label, mutate in (
            ('missing_range', lambda q, ck: q['coverage_manifest'][0]['source_ranges'].pop()),
            ('missing_receipt', lambda q, ck: ck.pop(q['targets'][0]['id'])),
            ('changed_source_digest', lambda q, ck: q.update(source_sha256='tampered')),
        ):
            changed, verdicts = deepcopy(p), deepcopy(checks)
            mutate(changed, verdicts)
            try:
                a.reduce(changed, target, spans, verdicts)
                report['negative_controls'][label] = False
            except ValueError:
                report['negative_controls'][label] = True
        if p['cross_partition_checks']:
            rejected = deepcopy(checks)
            rejected[p['cross_partition_checks'][0]['target_id']] = {'verdict': 'unsupported', 'reason': 'Synthetic cross-range conflict omission.'}
            report['negative_controls']['rejected_cross_range'] = a.reduce(deepcopy(p), target, spans, rejected)['verdict'] == 'unsupported'
        report.update(unpartitioned_request_chars=p['unpartitioned_request_chars'],
                      partitions=len(p['coverage_manifest']), cross_range_checks=len(p['cross_partition_checks']),
                      package_records=len(target['value']['requirements']),
                      components=sum(len(r.get('components', [])) for r in target['value']['requirements']),
                      owned_source_spans=sum(len(m['source_ranges']) for m in p['coverage_manifest']),
                      pages=sorted({loc['page_number'] for m in p['coverage_manifest'] for r in m['source_ranges']
                                    for loc in r['locations'] if loc.get('page_number') is not None}),
                      maximum_coverage_request_chars=max(p['request_chars'].values()))
        (output / 'coverage-manifest.json').write_text(json.dumps(a.receipt(p), indent=2) + '\n')
    report['saved_responses_consumed'] = sum(used.values())
    report['passed'] = len(report['phases']) == 2 and bool(captured) and all(report['negative_controls'].values()) and report.get('synthetic_reduce_passed', False)
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('phases', 'pages')}, indent=2))
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.run_dir, args.output_dir) else 1)
