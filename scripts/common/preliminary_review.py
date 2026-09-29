"""Document uncertainty separately from findings eligible to support judgment."""
from copy import deepcopy

RELEVANCE = ('strategic', 'readiness', 'uncertain')


def capture_relevance(row):
    if row.get('capture_relevance') in RELEVANCE:
        return row['capture_relevance']
    decision = row.get('decision', {})
    decision = decision if isinstance(decision, dict) else {}
    # Compatibility for older receipts. New package audits classify relevance.
    if decision.get('topic') == 'offer_validity':
        return 'readiness'
    if row.get('role', row.get('kind')) == 'readiness_reference' and decision.get('topic') not in {'experience', 'staffing', 'acquisition'}:
        return 'readiness'
    return 'uncertain'


def review_items(result):
    """Never turn raw model citations or unsupported prose into approved evidence."""
    items = []
    registry = result['source_registry']
    known = {**result.get('reconciliation_candidates', {}), **result['findings']}
    for entry in result['quarantined']:
        row = entry.get('candidate') or entry.get('raw') or {}
        if not isinstance(row, dict):
            row = {}
        package = entry['phase'] not in {'A', 'assessment_audit', 'recommendation_review'}
        claimed = row.get('evidence', []) if package else row.get('vendor_evidence', [])
        claimed = claimed if isinstance(claimed, list) else []
        if not package:
            ids = row.get('finding_ids', [])
            for fid in ids if isinstance(ids, list) else []:
                if isinstance(fid, str) and fid in known:
                    claimed = claimed + known[fid]['evidence']
        evidence = []
        for anchor in claimed:
            if not isinstance(anchor, dict):
                continue
            ref, quote = anchor.get('ref'), anchor.get('quote')
            if not isinstance(ref, str) or not isinstance(quote, str) or not quote or ref not in registry:
                continue
            if package and registry[ref]['kind'] != 'package':
                continue
            if quote in registry[ref]['text'] and anchor not in evidence:
                evidence.append(deepcopy(anchor))
        supported = entry['phase'] == 'reconciliation_audit' and row.get('audit', {}).get('verdict') == 'supported'
        # An unaudited row cannot declare itself harmless and hide in the appendix.
        relevance = entry.get('capture_relevance', capture_relevance(row) if supported else 'uncertain')
        items.append({'id': entry['id'], 'phase': entry['phase'],
            'interpretation': row.get('statement', 'A model record could not be interpreted.'),
            'reason': entry['error'], 'interpretation_status': 'unverified',
            'source_fidelity': 'supported' if supported else 'not_established',
            'capture_relevance': relevance if relevance in RELEVANCE else 'uncertain',
            'evidence': evidence,
            'citation_note': 'Quotations are source text, not approval of the interpretation.' if evidence else
                             'No trustworthy quotation was recovered for this interpretation; see raw audit record.',
            'follow_up': 'Review the source and interpretation before relying on this point; it is not a pursuit veto.'})
    return items
