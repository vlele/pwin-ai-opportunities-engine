"""Render checked findings and a separately labeled, non-scoring review log."""
from common.evidence_selection import source_locations
from common.preliminary_decisions import MAIN_TOPICS, qualifier_text
from common.preliminary_review import capture_relevance


AUDITED_LABEL = r'Audited\*'
AUDIT_LEGEND = (
    r'\* Audited\* means an automated model audit approved the item; its meaning or attached evidence may be incomplete. '
    'This is not human verification, proof of vendor capability, or proposal-readiness certification. '
    'Verify decision-changing interpretations against the original sources. Known failed or uncertain interpretations remain Unverified.'
)


def _audit_label(row, *, judgment=False):
    check = (row or {}).get('audit') or {}
    if check.get('verdict') == 'supported' and (not judgment or check.get('qualifier_fidelity') == 'supported'):
        return AUDITED_LABEL
    return 'Unverified (no complete automated approval recorded)'


def _audit_note(row, *, judgment=False):
    return 'Audit status: ' + _audit_label(row, judgment=judgment) + '.'


def _text(value):
    # Model/source Markdown must not inject headings or links into the template.
    return ' '.join(str(value).replace('[', '(').replace(']', ')').replace('<', '(').replace('>', ')').split())


def _token_limit_section(result):
    lines = ['', '## Requirements not processed because of token limits in the test environment', '']
    omissions = result.get('token_limit_omissions', [])
    if not omissions:
        return lines + ['None recorded.']
    lines += ['The stages and source ranges below were not fully processed because model generation reached a token limit. '
              'These are processing gaps, not rejected requirements or evidence of vendor inability. '
              'The exact omitted requirements are unknown; no requirement has been guessed from an unread range. '
              'An unfinished audit, reconciliation or judgment does not mean the source was never read. '
                  f'Earlier findings marked {AUDITED_LABEL} may remain in the report. Limits were not raised and token-exhausted generations were not automatically retried. Transport retries, if any, are recorded separately in the audit trail.', '']
    for item in omissions:
        usage = ', '.join(f'{name}: {value}' for name, value in item['usage'].items()) or 'Usage unavailable'
        lines += [f"### {_text(item['stage'])}", '', f"{_text(item['reason'])} {_text(usage)}.", '']
        groups = {}
        for ref in item['source_refs']:
            span = result['source_registry'][ref]
            for location in source_locations(span):
                key = (location['document_id'], location['filename'], location['page_number'])
                groups.setdefault(key, []).append((location['document_char_start'], location['document_char_end'], ref))
        for (_, filename, page), ranges in groups.items():
            refs = ', '.join(dict.fromkeys(ref for _, _, ref in ranges))
            merged = []
            for start, end, _ in sorted(ranges):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            offsets = ', '.join(f'{start}-{end}' for start, end in merged)
            where = f'page {page}; ' if page is not None else 'page not available; '
            lines += [f"- **{_text(filename or 'Package source')}**: {where}extracted-text character ranges {offsets} (end exclusive); source refs `{_text(refs)}`."]
        if item.get('finding_ids'):
            lines += ['- Affected finding/candidate IDs (not an approval): ' + _text(', '.join(item['finding_ids'])) + '.']
        if not groups:
            lines += ['- Source location unavailable; this stage must be reviewed before relying on its conclusions.']
        lines += ['']
    return lines


def render(result, packet):
    if result['status'] == 'TECHNICAL_BLOCKED':
        raise ValueError('No supported core scope; no preliminary memo to render.')
    findings = result['findings']
    notes = result.get('review_items', [])
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

    def documented(items):
        output = []
        for item in items:
            support = (f'An earlier automated source audit approved the source assertion only ({AUDITED_LABEL}); governing status or a later interpretation remains unverified.'
                       if item['source_fidelity'] == 'supported' else 'The interpretation has not been established by the evidence.')
            output += [f"- **Unverified interpretation ({_text(item['id'])}):** {_text(item['interpretation'])}",
                       f"  Review note: {_text(item['reason'])} {support}",
                       f"  {_text(item['citation_note'])}{cite(item['evidence'])}",
                       f"  Follow-up: {_text(item['follow_up'])}"]
        return output

    opportunity = packet.get('opportunity', {})
    labels = {'pursue_discovery': 'Pursue discovery, not an unconditional bid authorization',
              'investigate_further': 'Investigate further before committing proposal resources',
              'decline': 'Decline based on the supplied evidence'}
    recommendation = next((r for r in result['rows'] if r['kind'] == 'recommendation'
                           and r['recommendation'] == result['recommendation']), None)
    lines = ['# Preliminary Capture Assessment', '', f"**Opportunity:** {_text(opportunity.get('title', 'Local solicitation'))}",
             f"**Buyer:** {_text(opportunity.get('buyer', 'Not identified'))}",
             f"**Status:** {result['status']}", f"**Recommendation:** {labels[result['recommendation']]}",
             f"**Recommendation audit:** {_audit_label(recommendation, judgment=True)}", '',
             'This is an early capture assessment of the supplied package and self-reported vendor profile, not a proposal compliance certification. Current procurement status has not been verified.', '',
             AUDIT_LEGEND, '']
    if result.get('token_limit_omissions'):
        lines += ['**Limited source processing:** Token limits left some processing unfinished. '
                  'This assessment uses only admitted evidence; unreviewed material may change the recommendation. '
                  'See "Requirements not processed because of token limits in the test environment" at the end.', '']
    if result.get('decision_blockers'):
        lines += ['## Unresolved Review Items', '',
                  'These are research caveats, not automatic pursuit vetoes. Unverified interpretations are not established requirements, government conflicts, or evidence of vendor inability.', '']
        seen = set()
        for item in result['decision_blockers']:
            if any(n['id'] == item['id'] and n['capture_relevance'] == 'readiness' for n in notes):
                continue
            key = (item['scope'], item['reason'])
            if key not in seen:
                lines += [f"- **{_text(item['scope'])}:** {_text(item['reason'])}"]
                seen.add(key)
    strategic_notes = [r for r in notes if r['capture_relevance'] != 'readiness']
    if strategic_notes:
        lines += ['', '## Interpretations to Verify', '',
                  'The following model interpretations are documented, not adopted. They do not support fit scores, eligibility conclusions or win claims. Quoted source text is provided for review; a valid citation alone does not validate the interpretation.', '']
        lines += documented(strategic_notes)
    lines += ['', '## Package Status', '']
    status_rows = [r for r in findings.values() if r.get('decision', {}).get('topic') == 'document_status']
    for row in status_rows:
        lines += [f"- {_text(row['statement'])} {_text(qualifier_text(row))} {_audit_note(row)}{cite(row['evidence'])}"]
    if not status_rows:
        lines += ['No explicit package-stage finding was admitted; do not infer an issued requirement from this assessment.']
    lines += ['', '## Scope and Customer Priorities', '']
    for key, row in findings.items():
        if row['role'] == 'workstream' and capture_relevance(row) != 'readiness':
            lines += [f"- **{key}: {_text(row['statement'])}** {_text(row['implication'])} {_text(qualifier_text(row))} {_audit_note(row)}{cite(row['evidence'])}"]
    if not any(row['role'] == 'workstream' and capture_relevance(row) != 'readiness' for row in findings.values()):
        lines += ['No independently audited core workstream is available. No vendor-fit or capture-strategy conclusion can be established from this run.']
    lines += ['', '## Capture Considerations', '', 'These conditions inform capture diligence; they are not automatic reasons to decline.', '']
    conditions = [r for r in findings.values() if capture_relevance(r) != 'readiness'
                  and (r['role'] in {'decision_condition', 'conflict'} or r.get('decision', {}).get('topic') in MAIN_TOPICS)]
    for row in conditions:
        lines += [f"- **{row['id']}: {_text(row['statement'])}** Capture implication: {_text(row['implication'])} {_text(qualifier_text(row))} {_audit_note(row)}{cite(row['evidence'])}"]
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
            lines += [f"- **{_text(row['statement'])}** {_text(row['reason'])} {_audit_note(row, judgment=True)}{cite(evidence)}"]
            for fid in row['finding_ids']:
                # These qualifiers come from admitted findings, not a new LLM paraphrase.
                lines += [f"  Package basis {fid}: {_text(qualifier_text(findings[fid]))}"]
            if kind == 'alignment':
                lines += [f"  Alignment: {row['alignment']}; delivery experience: {row['experience']}. These are supplied-evidence findings, not independent verification."]
            lines += [f"  Next evidence/action: {_text(row['follow_up'])}"]
        if not rows:
            lines += ['No sufficiently supported finding was admitted for this section.']
        if kind == 'formal_qa':
            seen = set()
            for key, finding in findings.items():
                relation = finding.get('reconciliation', {})
                if relation.get('state') != 'unresolved' or capture_relevance(finding) == 'readiness':
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
            lines += [f"- {_text(row['statement'])} {_audit_note(row)}{cite(row['evidence'])}"]
    lines += ['', '## Coverage and Limitations', '']
    lines += [f"- Package partitions reviewed: {sum(m['reviewed'] for m in result['review_manifest'])}/{len(result['review_manifest'])}.",
              f"- Strategic coverage complete according to this scoped review: {result['strategic_coverage_complete']}. This is not exhaustive requirement coverage.",
              '- The vendor profile is self-reported; absent proof does not establish inability.']
    lines += [f'- Routine readiness questions and documented interpretations do not automatically downgrade a discovery recommendation marked {AUDITED_LABEL}.',
              '- Detailed processing and interpretation notes follow in the appendix.']
    lines += ['', '## Appendix: Proposal Readiness Review - Preliminary Reference for Capture Managers', '',
              'This is not a complete compliance matrix. Items below are source-grounded reference findings, not verified vendor compliance or a submission-ready checklist. Appendix coverage is non-exhaustive; decision-changing items also appear in the main assessment. Routine appendix omissions do not veto an otherwise supported preliminary assessment.', '',
              AUDIT_LEGEND, '']
    for row in findings.values():
        if row['role'] in {'readiness_reference', 'decision_condition', 'conflict', 'context'} or capture_relevance(row) == 'readiness':
            lines += [f"- **{row['id']}: {_text(row['statement'])}** {_text(row['implication'])} {_text(qualifier_text(row))} {_audit_note(row)} Vendor satisfaction/action remains unverified.{cite(row['evidence'])}"]
    if result.get('superseded_findings'):
        lines += ['', '### Superseded Terms - History Only', '']
        for row in result['superseded_findings'].values():
            relation = row['reconciliation']
            lines += [f"- **{row['id']} (not active):** {_text(row['statement'])} Replaced by {_text(', '.join(relation['governing_ids']))}. {_text(relation['reason'])} {_audit_note(row)}{cite(row['evidence'])}"]
    readiness_notes = [r for r in notes if r['capture_relevance'] == 'readiness']
    if readiness_notes:
        lines += ['', '### Readiness Interpretations to Verify', '',
                  'Unverified preparation items are retained for reference, not used as capability-fit penalties or pursuit gates.', '']
        lines += documented(readiness_notes)
    lines += ['', '### Processing and Review Notes', '']
    lines += ['- ' + _text(s) for s in dict.fromkeys(result['limitations'])]
    lines += ['', '### Evidence References', ''] + citations
    lines += _token_limit_section(result)
    return '\n'.join(lines) + '\n'
