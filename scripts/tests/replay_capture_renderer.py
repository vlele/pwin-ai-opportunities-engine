"""Replay saved checkpoints through the current renderer, without any model calls.

Outputs are diagnostic memos. Non-READY checkpoints remain unauthorized. This does
not regrade semantic decisions or substitute for a live full-capture evaluation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.capture_clarification import confirmed_context
from common.capture_fit import build_fit_catalog, validate_fit_assessment
from common.contract_structure import extract_contract_structure
from capture.capture_decision import build_capture_decision_sections
from capture.checkpoint_render_adapter import apply_checkpoint_render_context
from capture.render_capture_brief import render_capture_brief


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def replay(baseline, output):
    root = Path(__file__).resolve().parents[2]
    output.mkdir(parents=True, exist_ok=False)
    cases = {case['id']: case for case in read(baseline / 'cases.json')}
    results = []
    for label in ('phase1-known', 'phase2-heldout'):
        for job in read(baseline / label / 'plan.json')['jobs']:
            name = f"{job['case']}-r{job['repeat']}"
            run = baseline / label / name
            state, packet = read(run / 'state.json'), read(run / 'packet.json')
            unchanged = deepcopy((state, packet))
            case = cases[job['case']]
            context = deepcopy(confirmed_context(state, packet))
            profile = {'company': {'name': 'Synthetic vendor ' + job['case']},
                       'past_performance_highlights': [case['profile']] if case['profile'] else []}
            aliases = []
            for key, source in context.get('sources', {}).items():
                if source.get('kind') == 'profile' and source.get('profile_field') == 'reported_experience':
                    source['profile_field'] = 'past_performance_highlights[0]'
                    aliases.append({'source_id': key, 'before': 'reported_experience', 'after': source['profile_field']})
            assessed = validate_fit_assessment(None, build_fit_catalog(profile, [], clarification_context=context))
            docs = [{'source': key, 'text': source['text']} for key, source in packet['sources'].items()
                    if source['kind'] == 'package']
            sections = build_capture_decision_sections(
                vendor_profile=profile, resolved={'title': 'Synthetic validation ' + job['case']},
                opportunity={'title': 'Synthetic validation ' + job['case']}, explanation={},
                notice_context_text='\n'.join(d['text'] for d in docs), attachment_bundle={},
                attachment_validation={}, public_research={}, award_signals={},
                funding_assessment={'funding_confidence': 'Low'}, source_log=[],
                evidence_gaps=['Validation-only fixture replay; no market research performed.'],
                stakeholder_contacts=[], vehicle_signals=[], learned_semantic_preferences={},
                solicitation_facts={'contract_structure': extract_contract_structure(docs)},
                evaluator_anxiety_model={'vendor_fit_assessment': assessed,
                                         'reasoning_source': 'checked_component_graph_renderer_probe'})
            evidence = {**sections, 'status': 'VALIDATION_ONLY; checkpoint=' + state['status'],
                        'entry': {'canonical_record_id': name, 'source_name': 'Synthetic fixture'},
                        'request_id': output.name + '-' + name, 'understanding_checkpoint': context}
            evidence = apply_checkpoint_render_context(evidence, state, packet)
            memo = render_capture_brief(root / 'templates/capture-brief.template.md', evidence)
            view = evidence['checkpoint_render_context']
            formal_ids = {qid for item in view['formal_qa_items'] for qid in item['question_ids']}
            expected_ids = {q['id'] for q in state.get('questions', []) if q.get('route') == 'formal_qa'
                            and q.get('question_validation') in {'supported', 'uncertain'}}
            checks = {
                'no_template_placeholders': '{{' not in memo,
                'sources_and_checkpoint_unchanged': unchanged == (state, packet),
                'readiness_gate_unchanged': state['status'] == 'READY' or confirmed_context(state, packet) == {},
                'all_validated_formal_questions_retained': formal_ids == expected_ids,
                'formal_questions_rendered': all(row['question'] in memo for row in view['formal_qa_items']),
                'component_notes_rendered': all(note in memo for note in view['component_coverage_notes']),
                'conflicting_terms_rendered': all(cite['quote'] in memo for group in view['unresolved_precedence']
                                                for term in group['terms'] for cite in term['citations']),
                'conflict_flag_rendered': not view['unresolved_precedence'] or 'unresolved_precedence' in memo,
                'no_adapter_validation_issues': not view['validation_issues'],
            }
            (output / (name + '.md')).write_text(memo)
            save(output / (name + '.evidence.json'), evidence)
            save(output / (name + '.adapter.json'), {
                'profile_field_aliases': aliases, 'source_text_or_decision_changes': False,
                'expected_labels_supplied': False, 'production_gate_allows_memo': state['status'] == 'READY',
                'note': 'Diagnostic display projection; not a full production capture.'})
            results.append({'case': job['case'], 'repeat': job['repeat'], 'status': state['status'],
                            'checks': checks, 'formal_questions': len(formal_ids),
                            'displayed_formal_items': len(view['formal_qa_items']),
                            'conflict_groups': len(view['unresolved_precedence']),
                            'component_notes': len(view['component_coverage_notes']), 'memo': str(output / (name + '.md'))})
    save(output / 'results.json', results)
    summary = {'runs': len(results), 'passing_handoff_checks': sum(all(r['checks'].values()) for r in results),
               'failed': [r for r in results if not all(r['checks'].values())],
               'live_model_calls': 0, 'semantic_regrading': False, 'production_capture_validation': False}
    save(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.baseline, args.output)
    raise SystemExit(0 if not result['failed'] else 1)
