"""Display audited checkpoint findings without granting research authorization.

This adapter is also used by fixture replays. It never changes the checkpoint,
recalculates fit, accepts a failed graph, or changes the production READY gate.
"""
from copy import deepcopy
import re

from common.capture_understanding import build_spans
from common import requirement_routing as routing


def _normalized(text):
    return ' '.join(re.findall(r'\w+', str(text).casefold()))


def _citations(anchors, spans, *, package=False):
    if not anchors:
        raise ValueError('No current-source evidence was supplied.')
    result = []
    for anchor in anchors:
        ref, quote = anchor.get('ref'), anchor.get('quote')
        span = spans.get(ref, {})
        if not quote or quote not in span.get('text', '') or (package and span.get('kind') != 'package'):
            raise ValueError('Checkpoint citation is not in the current package/source span.')
        row = {'ref': ref, 'quote': quote, 'source_id': span['source_id']}
        if row not in result:
            result.append(row)
    return result


def _quote_text(citations):
    return '; '.join(f'[{c["ref"]}] "{c["quote"]}"' for c in citations)


def _component_notes(graph, spans, issues):
    notes = []
    for edge in graph.get('comparisons', []):
        try:
            ri, ci = edge['requirement'], edge['claim']
            if not isinstance(ri, int) or not isinstance(ci, int) or ri < 0 or ci < 0:
                raise ValueError('Invalid checkpoint comparison index.')
            requirement, claim = graph['requirements'][ri], graph['claims'][ci]
            if requirement.get('status') != 'current':
                continue
            vendor_cites = _citations(claim['evidence'], spans)
            package_cites = _citations(requirement['evidence'], spans, package=True)
            parts = []
            for index, component in enumerate(requirement['components']):
                if routing.categorized(requirement) and routing.route(component, requirement['status']) != 'vendor_comparison':
                    continue
                finding = edge['component_findings'][f'K{index}']
                _citations(component['evidence'], spans, package=True)
                if finding.get('evidence'):
                    _citations(finding['evidence'], spans)
                parts.append(f'K{index} {component["text"]}: {finding["status"]}')
            notes.append(f'R{ri}/C{ci}: {edge["fit_label"]}. ' + '; '.join(parts)
                         + '. Assessment of supplied claim; not independent verification. Requirement: ' + _quote_text(package_cites)
                         + '. Vendor claim: ' + _quote_text(vendor_cites))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            issues.append('Component display withheld: ' + str(error))
    return notes


def _conflicts(graph, checks, spans, issues):
    result, seen = [], set()
    for check in checks:
        if (check.get('verdict') != 'supported' or check.get('audit_dimension') != 'source_fidelity'
                or check.get('precedence_status') != 'unresolved_precedence'):
            continue
        ids = tuple(sorted(set(check.get('conflicting_requirement_ids', []))))
        if len(ids) < 2 or ids in seen:
            continue
        seen.add(ids)
        try:
            terms = []
            for rid in ids:
                if not re.fullmatch(r'R\d+', rid):
                    raise ValueError('Invalid conflict requirement ID.')
                record = graph['requirements'][int(rid[1:])]
                if record.get('status') != 'current':
                    raise ValueError('Unresolved conflict contains an inactive requirement.')
                terms.append({'requirement_id': rid, 'citations': _citations(
                    record.get('focus') or record['evidence'], spans, package=True)})
            result.append({'flag': 'unresolved_precedence', 'requirement_ids': list(ids), 'terms': terms})
        except (KeyError, IndexError, TypeError, ValueError) as error:
            issues.append('Conflict display withheld: ' + str(error))
    return result


def _formal_questions(state, audit, conflicts, spans, issues):
    receipts = {r['target_id']: r for r in audit.get('independent_question_checks', [])}
    groups = {}
    for question in state.get('questions', []):
        if question.get('route') != 'formal_qa':
            continue
        if question.get('question_validation') not in {'supported', 'uncertain'}:
            issues.append('Formal question has no accepted independent warrant: ' + str(question.get('id')))
            continue
        try:
            receipt_ids = question.get('question_receipt_ids') or [question.get('question_receipt_id')]
            selected = [receipts[rid] for rid in receipt_ids]
            if not selected or any(r.get('check', {}).get('verdict') not in {'supported', 'uncertain'} for r in selected):
                raise ValueError('Formal question warrant was not accepted.')
            anchors = [a for r in selected for a in r['signal']['evidence']]
            cites = _citations(anchors, spans, package=True)
            matched = [group for group in conflicts if all(
                any(a['ref'] == b['ref'] and _normalized(a['quote']) in _normalized(b['quote'])
                    for b in cites) for term in group['terms'] for a in term['citations'])]
            # Only a single audited conflict identity permits merging different
            # quotation boundaries. Sharing a page or a generic question is not enough.
            identity = tuple(matched[0]['requirement_ids']) if len(matched) == 1 else None
            text = question['question']
            intent = text.rsplit(': ', 1)[-1] if text.startswith('Regarding ') else text
            key = (_normalized(intent), identity) if identity else ('question', question['id'])
            row = {'question': text, 'question_ids': [question['id']], 'receipt_ids': list(receipt_ids),
                   'citations': cites, 'conflicting_requirement_ids': list(identity or []),
                   'unresolved_precedence': question.get('kind') == 'document_conflict'}
            if key in groups:
                previous = groups[key]
                if max(len(c['quote']) for c in cites) > max(len(c['quote']) for c in previous['citations']):
                    previous['question'] = text
                for field in ('question_ids', 'receipt_ids', 'citations'):
                    previous[field].extend(value for value in row[field] if value not in previous[field])
                previous['unresolved_precedence'] |= row['unresolved_precedence']
            else:
                groups[key] = row
        except (KeyError, TypeError, ValueError) as error:
            issues.append('Formal question display withheld: ' + str(error))
    return list(groups.values())


def build_checkpoint_render_context(state, packet):
    """Project display data; do not turn non-READY findings into confirmed_context."""
    issues = []
    audit = state.get('understanding_audit', {})
    checked = audit.get('claim_evidence', {})
    spans = build_spans(packet, state.get('confirmed_answers', []))
    graph = audit.get('semantic_plan') if checked.get('passed') is True and not audit.get('validation_pending') else None
    graph = graph if isinstance(graph, dict) else {}
    conflicts = _conflicts(graph, checked.get('checks', []), spans, issues) if graph else []
    return {
        'status': state.get('status'), 'display_only': True,
        'formal_qa_items': _formal_questions(state, audit, conflicts, spans, issues),
        'unresolved_precedence': conflicts,
        'component_coverage_notes': _component_notes(graph, spans, issues) if graph else [],
        **(routing.checklists(graph['requirements'], spans) if graph else {}),
        'validation_issues': issues,
    }


def apply_checkpoint_render_context(evidence, state, packet):
    """Map validated display keys onto the existing Markdown renderer sections."""
    result = deepcopy(evidence)
    context = build_checkpoint_render_context(state, packet)
    result['checkpoint_render_context'] = context
    for key in ('proposal_formatting_submission_checklist', 'contract_terms_checklist', 'requirement_applicability_notes'):
        result[key] = context.get(key, [])
    result.setdefault('capability_fit_analysis', {})['component_coverage_notes'] = context['component_coverage_notes']
    questions = result.setdefault('questions_to_ask', {})
    formal = context['formal_qa_items']
    if formal:
        questions['customer'] = [row['question'] for row in formal]
    elif state.get('status') == 'NEEDS_FORMAL_QA':
        questions['customer'] = ['Formal Q&A is pending, but no current-source validated question is available for display.']
    questions['unresolved_precedence'] = [
        'unresolved_precedence (' + ', '.join(row['requirement_ids']) + '): '
        + ' | '.join(term['requirement_id'] + ': ' + _quote_text(term['citations']) for term in row['terms'])
        for row in context['unresolved_precedence']]
    questions['formal_qa_evidence'] = [
        ('unresolved_precedence: ' if row['unresolved_precedence'] else '') + _quote_text(row['citations'])
        for row in formal]
    if state.get('status') != 'READY':
        judgment = result.setdefault('capture_judgment', {})
        warning = 'Checkpoint ' + str(state.get('status')) + ': display-only findings; capture/research authorization is unchanged.'
        judgment['release_warning'] = ' '.join(filter(None, [judgment.get('release_warning'), warning]))
    return result
