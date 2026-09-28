"""Render only admitted preliminary findings, with a non-certifying appendix."""
from common.evidence_selection import source_locations
from common.preliminary_decisions import MAIN_TOPICS, qualifier_text


def _text(value):
    # Model/source Markdown must not inject headings or links into the template.
    return ' '.join(str(value).replace('[', '(').replace(']', ')').replace('<', '(').replace('>', ')').split())


def render(result, packet):
    if result['status'] == 'TECHNICAL_BLOCKED':
        raise ValueError('No supported core scope; no preliminary memo to render.')
    findings = result['findings']
    refs, citations = {}, []
    def cite(anchors):
        ids = []
        for a in anchors:
            key = (a['ref'], a['quote'])
            if key not in refs:
                refs[key] = len(refs) + 1
                span = result['source_registry'][a['ref']]
                start = span['text'].find(a['quote'])
                locations = source_locations(span, start, start + len(a['quote']))
                pages = sorted({x['page_number'] for x in locations if x.get('page_number')})
                label = span.get('filename') or span.get('profile_field') or a['ref']
                detail = 'pages ' + ', '.join(map(str, pages)) if pages else 'source text offsets'
                citations.append(f"- [S{refs[key]}] {_text(label)}; {detail}; ref `{a['ref']}`: {_text(a['quote'])}")
            ids.append(f'S{refs[key]}')
        return ' [' + ', '.join(dict.fromkeys(ids)) + ']' if ids else ''

    opportunity = packet.get('opportunity', {})
    labels = {'pursue_discovery': 'Pursue discovery, not an unconditional bid authorization',
              'investigate_further': 'Investigate further before committing proposal resources',
              'decline': 'Decline based on the supplied evidence'}
    lines = ['# Preliminary Capture Assessment', '', f"**Opportunity:** {_text(opportunity.get('title', 'Local solicitation'))}",
             f"**Buyer:** {_text(opportunity.get('buyer', 'Not identified'))}",
             f"**Status:** {result['status']}", f"**Recommendation:** {labels[result['recommendation']]}", '',
             'This is an early capture assessment of the supplied package and self-reported vendor profile, not a proposal compliance certification. Current procurement status has not been verified.', '',
             '## Package Status', '']
    status_rows = [r for r in findings.values() if r.get('decision', {}).get('topic') == 'document_status']
    for row in status_rows:
        lines += [f"- {_text(row['statement'])} {_text(qualifier_text(row))}{cite(row['evidence'])}"]
    if not status_rows:
        lines += ['No explicit package-stage finding was admitted; do not infer an issued requirement from this assessment.']
    lines += ['', '## Scope and Customer Priorities', '']
    for key, row in findings.items():
        if row['role'] == 'workstream':
            lines += [f"- **{key}: {_text(row['statement'])}** {_text(row['implication'])} {_text(qualifier_text(row))}{cite(row['evidence'])}"]
    lines += ['', '## Decision-Changing Conditions', '']
    conditions = [r for r in findings.values() if r['role'] in {'decision_condition', 'conflict'}
                  or r.get('decision', {}).get('topic') in MAIN_TOPICS]
    for row in conditions:
        lines += [f"- **{row['id']}: {_text(row['statement'])}** Capture implication: {_text(row['implication'])} {_text(qualifier_text(row))}{cite(row['evidence'])}"]
    if not conditions:
        lines += ['No decision-changing condition was admitted in this review. This is not assurance that none exists.']
    headings = [('alignment', 'Vendor Alignment and Experience'), ('capture_priority', 'Capture Priorities'),
                ('decision_risk', 'Risks to Resolve'), ('win_hypothesis', 'Requirement-Based Win Hypotheses'),
                ('teaming', 'Teaming Posture'), ('formal_qa', 'Formal Q&A Candidates'),
                ('next_action', 'Next Capture Actions'), ('recommendation', 'Recommendation Rationale')]
    for kind, heading in headings:
        lines += ['', '## ' + heading, '']
        rows = [r for r in result['rows'] if r['kind'] == kind]
        for row in rows:
            evidence = [a for fid in row['finding_ids'] for a in findings[fid]['evidence']] + row['vendor_evidence']
            lines += [f"- **{_text(row['statement'])}** {_text(row['reason'])}{cite(evidence)}"]
            if kind == 'alignment':
                lines += [f"  Alignment: {row['alignment']}; delivery experience: {row['experience']}. These are supplied-evidence findings, not independent verification."]
            lines += [f"  Next evidence/action: {_text(row['follow_up'])}"]
        if not rows:
            lines += ['No sufficiently supported finding was admitted for this section.']
        if kind == 'formal_qa':
            seen = set()
            for key, finding in findings.items():
                relation = finding.get('reconciliation', {})
                if relation.get('state') != 'unresolved':
                    continue
                members = frozenset([key, *relation['governing_ids']])
                if members in seen or any(members <= set(r['finding_ids']) for r in rows):
                    continue
                seen.add(members)
                terms = '; '.join(findings[k]['statement'] for k in sorted(members))
                evidence = [a for k in sorted(members) for a in findings[k]['evidence']]
                lines += [f"- **Unresolved precedence:** Which term governs: {_text(terms)}? No precedence was established from the supplied evidence.{cite(evidence)}"]
    lines += ['', '## Market Context', '',
              'No live market, incumbent, USAspending or GovTribe research was performed in this local preliminary assessment. Package-native statements below, if any, are not independent verification of current market conditions.']
    for row in findings.values():
        if row.get('decision', {}).get('topic') == 'market':
            lines += [f"- {_text(row['statement'])}{cite(row['evidence'])}"]
    lines += ['', '## Coverage and Limitations', '']
    lines += [f"- Package partitions reviewed: {sum(m['reviewed'] for m in result['review_manifest'])}/{len(result['review_manifest'])}.",
              f"- Strategic coverage complete according to this scoped review: {result['strategic_coverage_complete']}. This is not exhaustive requirement coverage.",
              '- The vendor profile is self-reported; absent proof does not establish inability.']
    lines += ['- ' + _text(s) for s in dict.fromkeys(result['limitations'])]
    lines += ['', '## Appendix: Proposal Readiness Review - Reference for Capture Managers', '',
              'This is not a complete compliance matrix. Items below are source-grounded reference findings, not verified vendor compliance or a submission-ready checklist. Appendix coverage is non-exhaustive; decision-changing items also appear in the main assessment.', '']
    for row in findings.values():
        if row['role'] in {'readiness_reference', 'decision_condition', 'conflict', 'context'}:
            lines += [f"- **{row['id']}: {_text(row['statement'])}** {_text(row['implication'])} {_text(qualifier_text(row))} Review status: package finding checked; vendor satisfaction/action remains unverified.{cite(row['evidence'])}"]
    if result.get('superseded_findings'):
        lines += ['', '### Superseded Terms - History Only', '']
        for row in result['superseded_findings'].values():
            relation = row['reconciliation']
            lines += [f"- **{row['id']} (not active):** {_text(row['statement'])} Replaced by {_text(', '.join(relation['governing_ids']))}. {_text(relation['reason'])}{cite(row['evidence'])}"]
    lines += ['', '### Evidence References', ''] + citations
    return '\n'.join(lines) + '\n'
