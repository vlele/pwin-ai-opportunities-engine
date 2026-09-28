"""Small decision contract for preliminary capture, not a compliance inventory."""
from copy import deepcopy

TOPICS = ('general', 'acquisition', 'staffing', 'experience', 'offer_validity', 'pricing',
          'document_status', 'market', 'other')
STAGES = ('rfi', 'draft', 'issued', 'unknown')
FORCES = ('required', 'anticipated', 'optional', 'conditional', 'informational', 'unknown')
COVERAGE = ('acquisition_selection', 'precedence', 'document_status', 'staffing_quantities', 'experience_quantities')
MAIN_TOPICS = {'acquisition', 'staffing', 'experience', 'offer_validity', 'pricing', 'document_status'}
RECONCILE_TOPICS = {'acquisition', 'staffing', 'experience', 'offer_validity', 'pricing', 'document_status', 'other'}
ACQUISITION_DIMENSIONS = ('none', 'set_aside', 'competition_method', 'vehicle',
                          'funding', 'evaluation', 'submission', 'other')
SELECTION_DIMENSIONS = {'set_aside', 'competition_method', 'vehicle'}


def validate_decision(row, sources):
    decision = row['decision']
    cited = {a['ref'] for a in row['evidence']}
    controls = decision['selected_controls']
    if decision['selection_basis'] != 'selected_control' and controls:
        raise ValueError('Control links require selected_control basis.')
    if decision['selection_basis'] == 'selected_control' and not controls:
        raise ValueError('A selection needs an observed selected control, not a printed label.')
    for link in controls:
        if link['ref'] not in cited or link['ref'] not in sources:
            raise ValueError('Selected control must have cited current-package evidence.')
        observed = [c for c in sources[link['ref']].get('form_controls', []) if c['id'] == link['id']]
        if len(observed) != 1 or observed[0]['state'] != 'selected' or observed[0]['label'] != link['label']:
            raise ValueError('The linked option is not an observed selected control with that label.')
        quoted = ' '.join(a['quote'] for a in row['evidence'] if a['ref'] == link['ref'])
        if link['label'] not in quoted or 'state selected' not in quoted:
            raise ValueError('The selection citation must include its label and selected state.')
    dimension = decision['acquisition_dimension']
    if dimension not in ACQUISITION_DIMENSIONS:
        raise ValueError('Unknown acquisition dimension.')
    if decision['topic'] == 'acquisition':
        if dimension == 'none':
            raise ValueError('Acquisition findings must identify their decision dimension.')
        # A page-level form flag is not evidence that this exact assertion is a
        # checkbox claim. Narrative fidelity remains an independent audit duty.
        if dimension in SELECTION_DIMENSIONS and decision['selection_basis'] == 'not_applicable':
            raise ValueError('Acquisition findings need an explicit selection or narrative basis.')
    elif dimension != 'none':
        raise ValueError('Acquisition dimensions belong only to acquisition findings.')


def reconciliation_key(row):
    decision = row['decision']
    return (decision['topic'], decision['acquisition_dimension'] if decision['topic'] == 'acquisition' else 'none')


def attach_document_context(findings, sources):
    result = deepcopy(findings)
    def docs(row):
        return {sources[a['ref']].get('document_id', sources[a['ref']].get('source_id', a['ref'])) for a in row['evidence']}
    contexts = {k: row for k, row in result.items() if row['decision']['topic'] == 'document_status'}
    for row in result.values():
        ids = [k for k, context in contexts.items() if docs(context) & docs(row)]
        row['document_context_ids'] = ids
        row['effective_stages'] = sorted({row['decision']['stage'], *(contexts[k]['decision']['stage'] for k in ids)} - {'unknown'}) or ['unknown']
    return result


def apply_reconciliation(findings, relations):
    """Apply independently approved relationships. Never pick by date or filename."""
    if set(relations) != set(findings):
        raise ValueError('Reconciliation must account for every candidate exactly once.')
    for key, relation in relations.items():
        links = relation['governing_ids']
        if len(links) != len(set(links)) or key in links or any(k not in findings for k in links):
            raise ValueError(f'{key}: governing_ids must contain distinct known OTHER findings, never self-links.')
        state = relation['state']
        if state not in {'active', 'superseded', 'unresolved'}:
            raise ValueError('Unknown reconciliation state.')
        if (state == 'active' and links) or (state != 'active' and not links):
            raise ValueError(f'{key}: active requires empty governing_ids; superseded/unresolved require links.')
        for target in links:
            if reconciliation_key(findings[key]) != reconciliation_key(findings[target]):
                raise ValueError('Different decision topics or acquisition dimensions cannot conflict or supersede each other.')
            if state == 'superseded' and relations[target]['state'] != 'active':
                raise ValueError('Supersession must point to an active term; cycles/chains are not admitted.')
            if state == 'unresolved' and (relations[target]['state'] != 'unresolved' or key not in relations[target]['governing_ids']):
                raise ValueError('Unresolved terms must identify both sides.')
    active, history = {}, {}
    for key, value in findings.items():
        row = deepcopy(value)
        row['reconciliation'] = deepcopy(relations[key])
        if relations[key]['state'] == 'superseded':
            history[key] = row
        else:
            if relations[key]['state'] == 'unresolved':
                row['role'] = 'conflict'
            active[key] = row
    return active, history


def qualifier_text(row):
    decision = row.get('decision')
    if not decision:
        return ''
    stages = row.get('effective_stages', [decision['stage']])
    labels = [f"Document: {' / '.join(stages)}", f"Obligation: {decision['force']}", f"Period: {decision['period']}"]
    if decision['quantities']:
        labels.append('Quantities: ' + '; '.join(decision['quantities']))
    if row.get('reconciliation', {}).get('state') == 'unresolved':
        labels.append('Unresolved precedence')
    return '. '.join(labels) + '.'
