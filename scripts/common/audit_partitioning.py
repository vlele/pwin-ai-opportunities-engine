"""Lossless source-range coverage audits with an explicit all-receipts reduce gate.

Every source span has exactly one primary owner. Whole inventory records and their
anchors travel as context; they are never summarized or trimmed to fit a budget.
All pairs of primary ranges are also checked together, including uncited text, so
splitting cannot silently hide cross-range exceptions or amendment conflicts.
"""
from copy import deepcopy
from itertools import combinations
import hashlib
import json

from common.evidence_selection import source_locations
from common.understanding_checkpoints import MAX_MODEL_INPUT_CHARS

VERSION = 'source-partitions-v2-context-closure'
PARTITION_INSTRUCTIONS = """This is a source-partitioned package coverage audit.
audit_partition.primary_refs are the complete source ranges you own in this call.
All primary source text is supplied, including text with no inventory citation.
Other supplied spans are supporting context, not additional primary ownership.
Every supplied supporting span also brings records citing that span, transitively.
This visibility is source context ONLY, never proof of equivalence or coverage.
Check actors, exceptions, numbers, status and scope; shared spans do not settle them.
The inventory contains WHOLE unchanged records relevant to these ranges; some of
their facts occur in supporting context. requirement_ids and package_reference_ids
identify their ORIGINAL inventory positions. supersedes indexes use that original
inventory, never the local array positions. Do not treat a record present elsewhere
in this payload as missing merely because it has another primary source location.
For mode=range, check every material fact in the primary text for inventory coverage.
For mode=cross_range, check the primary ranges TOGETHER for omitted or flattened
exceptions, definitions, qualifications, pricing allocations and precedence or
conflicts spanning those ranges. Do not assume two individually passing ranges are
jointly consistent. Accurate retention of both conflicting terms is not itself a
failure; dropped conflicts, unjustified precedence, or altered qualifiers are.
Do not judge omissions in source text outside the stated primary ranges. Do not
invent vendor facts. Return only the requested immutable target's verdict/reason.
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     allow_nan=False).encode()).hexdigest()


def _anchors(value):
    if isinstance(value, dict):
        if set(value) == {'ref', 'quote'}:
            yield value
        else:
            for child in value.values():
                yield from _anchors(child)
    elif isinstance(value, list):
        for child in value:
            yield from _anchors(child)


def _document(span):
    return span.get('document_id') or span.get('source_id')


def _start(span):
    return span.get('source_offset', 0) + span.get('offset', 0)


def _source_index(spans):
    result = {}
    for ref, span in spans.items():
        if span.get('kind') != 'package':
            continue
        if not isinstance(span.get('text'), str) or not span['text'] or not _document(span):
            raise ValueError('Coverage requires nonempty, identifiable package source spans.')
        result[ref] = {'ref': ref, 'document_id': _document(span), 'start': _start(span),
                       'end': _start(span) + len(span['text']), 'sha256': digest(span),
                       'locations': source_locations(span)}
    if not result:
        raise ValueError('Package coverage requires original source text.')
    return result


class _Layout:
    def __init__(self, target, spans):
        if target.get('id') != 'package-coverage' or target.get('kind') != 'package_coverage':
            raise ValueError('Only the canonical package-coverage target can be partitioned.')
        self.target = target
        self.spans = {k: v for k, v in spans.items() if v.get('kind') == 'package'}
        self.index = _source_index(self.spans)
        self.refs = sorted(self.index, key=lambda r: (self.index[r]['document_id'], self.index[r]['start'], r))
        value = target['value']
        if set(value) != {'requirements', 'quoted_vendor_context'}:
            raise ValueError('Unaccounted coverage inventory fields cannot be discarded.')
        self.requirements, self.context = value['requirements'], value['quoted_vendor_context']
        self.record_refs = {}
        for prefix, rows in (('R', self.requirements), ('P', self.context)):
            for i, row in enumerate(rows):
                refs = set()
                for anchor in _anchors(row):
                    ref, quote = anchor['ref'], anchor['quote']
                    if ref not in self.spans or not isinstance(quote, str) or not quote.strip() or quote not in self.spans[ref]['text']:
                        raise ValueError('Coverage inventory contains an invalid or non-package anchor.')
                    refs.add(ref)
                if not refs:
                    raise ValueError('A coverage inventory record has no accountable source evidence.')
                self.record_refs[f'{prefix}{i}'] = refs
        self.neighbors = {}
        for i, ref in enumerate(self.refs):
            row = self.index[ref]
            adjacent = set()
            for j in (i - 1, i + 1):
                if 0 <= j < len(self.refs):
                    other = self.index[self.refs[j]]
                    if row['document_id'] == other['document_id'] and (row['end'] == other['start'] or other['end'] == row['start']):
                        adjacent.add(self.refs[j])
            self.neighbors[ref] = adjacent

    def make(self, groups, ids, mode):
        primary = set(ref for group in groups for ref in group)
        contextual = primary | {n for ref in primary for n in self.neighbors[ref]}
        selected = {key for key, refs in self.record_refs.items() if refs & contextual}
        # An explicit supersedes edge must bring both unchanged records and their
        # evidence even if its source is in a different document/range.
        while True:
            before = set(selected)
            for key in before:
                if key.startswith('R'):
                    for i in self.requirements[int(key[1:])].get('supersedes', []):
                        if type(i) is not int or not 0 <= i < len(self.requirements):
                            raise ValueError('Coverage found a dangling precedence dependency.')
                        selected.add(f'R{i}')
            cited = {ref for key in selected for ref in self.record_refs[key]}
            # Expand neighbors only from actual citations/primary ranges, not
            # recursively from arbitrary neighbors across the entire document.
            dependencies = contextual | cited | {n for ref in cited for n in self.neighbors[ref]}
            selected.update(key for key, refs in self.record_refs.items() if refs & dependencies)
            if selected == before:
                break
        req_ids = [f'R{i}' for i in range(len(self.requirements)) if f'R{i}' in selected]
        ctx_ids = [f'P{i}' for i in range(len(self.context)) if f'P{i}' in selected]
        return {'id': 'package-coverage-' + '-'.join(ids), 'kind': 'package_coverage',
                'value': {'requirements': [deepcopy(self.requirements[int(k[1:])]) for k in req_ids],
                          'quoted_vendor_context': [deepcopy(self.context[int(k[1:])]) for k in ctx_ids]},
                'audit_partition': {'version': VERSION, 'mode': mode, 'partition_ids': ids,
                                    'primary_refs': [r for r in self.refs if r in primary],
                                    'source_refs': [r for r in self.refs if r in dependencies],
                                    'context_dependency_records': sorted(key for key in selected if not self.record_refs[key] & contextual),
                                    'requirement_ids': req_ids, 'package_reference_ids': ctx_ids}}


def _targets(layout, groups):
    targets = [layout.make([group], [f'P{i}'], 'range') for i, group in enumerate(groups)]
    targets.extend(layout.make([groups[i], groups[j]], [f'P{i}', f'P{j}'], 'cross_range')
                   for i, j in combinations(range(len(groups)), 2))
    return targets


def prepare(target, spans, *, max_chars=MAX_MODEL_INPUT_CHARS):
    """Plan every map/cross-range request before any vendor comparison is paid for."""
    from common.semantic_plan import audit_request_chars
    if type(max_chars) is not int or not 0 < max_chars <= MAX_MODEL_INPUT_CHARS:
        raise ValueError('Invalid coverage partition request budget.')
    layout = _Layout(target, spans)
    unpartitioned_size = audit_request_chars([target], spans)
    if unpartitioned_size <= max_chars:
        groups, targets = [layout.refs], [deepcopy(target)]
    else:
        groups = []
        for ref in layout.refs:
            if not groups or _document(spans[groups[-1][-1]]) != _document(spans[ref]):
                groups.append([])
            groups[-1].append(ref)
        while True:
            targets = _targets(layout, groups)
            oversized = next((t for t in targets if audit_request_chars([t], spans) > max_chars), None)
            if oversized is None:
                break
            candidates = [int(p[1:]) for p in oversized['audit_partition']['partition_ids']
                          if len(groups[int(p[1:])]) > 1]
            if not candidates:
                size = audit_request_chars([oversized], spans)
                raise ValueError(f'Indivisible coverage dependency {oversized["id"]} requires {size} characters; '
                                 f'limit is {max_chars}. No source or inventory record was truncated.')
            split = max(candidates, key=lambda i: sum(len(spans[r]['text']) for r in groups[i]))
            midpoint = len(groups[split]) // 2
            groups[split:split+1] = [groups[split][:midpoint], groups[split][midpoint:]]
    sizes = {t['id']: audit_request_chars([t], spans) for t in targets}
    manifest = []
    for i, group in enumerate(groups):
        target_id = 'package-coverage' if len(targets) == 1 and 'audit_partition' not in targets[0] else f'package-coverage-P{i}'
        manifest.append({'partition_id': f'P{i}', 'target_id': target_id,
                         'source_ranges': [deepcopy(layout.index[r]) for r in group],
                         'verdict': 'pending', 'passed': False})
    result = {'version': VERSION, 'max_chars': max_chars, 'source_sha256': digest(layout.spans),
              'inventory_sha256': digest(target), 'targets': targets, 'request_chars': sizes,
              'unpartitioned_request_chars': unpartitioned_size,
              'coverage_manifest': manifest,
              'cross_partition_checks': [{'target_id': t['id'], 'partition_ids': t['audit_partition']['partition_ids'],
                                          'verdict': 'pending', 'passed': False}
                                         for t in targets if t.get('audit_partition', {}).get('mode') == 'cross_range']}
    validate_layout(result, target, spans)
    return result


def validate_layout(prepared, target, spans):
    from common.semantic_plan import audit_request_chars
    bound = prepared.get('max_chars')
    if type(bound) is not int or not 0 < bound <= MAX_MODEL_INPUT_CHARS:
        raise ValueError('Coverage manifest cannot raise or disable the request budget.')
    layout = _Layout(target, spans)
    if prepared.get('version') != VERSION or prepared['source_sha256'] != digest(layout.spans) or prepared['inventory_sha256'] != digest(target):
        raise ValueError('Coverage manifest source/inventory identity changed.')
    groups, owned = [], []
    for i, row in enumerate(prepared['coverage_manifest']):
        if row['partition_id'] != f'P{i}':
            raise ValueError('Invalid coverage partition identity/order.')
        refs = []
        for source in row['source_ranges']:
            ref = source['ref']
            if ref not in layout.index or source != layout.index[ref]:
                raise ValueError('Coverage manifest range/hash/provenance changed.')
            refs.append(ref)
        if not refs:
            raise ValueError('Empty coverage partition.')
        groups.append(refs)
        owned.extend(refs)
    if owned != layout.refs or len(set(owned)) != len(owned):
        raise ValueError('Coverage manifest must own every source range exactly once, in order.')
    canonical = len(prepared['targets']) == 1 and 'audit_partition' not in prepared['targets'][0]
    expected = [deepcopy(target)] if canonical else _targets(layout, groups)
    if canonical and len(groups) != 1:
        raise ValueError('Canonical coverage cannot hide multiple manifest owners.')
    if prepared['targets'] != expected:
        raise ValueError('Coverage target/context or cross-partition dependency was lost or changed.')
    expected_cross = [t['id'] for t in expected if t.get('audit_partition', {}).get('mode') == 'cross_range']
    if [r['target_id'] for r in prepared['cross_partition_checks']] != expected_cross:
        raise ValueError('Missing, duplicate or unexpected cross-partition check.')
    cross = [t for t in expected if t.get('audit_partition', {}).get('mode') == 'cross_range']
    if any(row['partition_ids'] != t['audit_partition']['partition_ids']
           for row, t in zip(prepared['cross_partition_checks'], cross)):
        raise ValueError('Cross-partition receipt was linked to the wrong source ranges.')
    for i, row in enumerate(prepared['coverage_manifest']):
        if row['target_id'] != expected[i]['id']:
            raise ValueError('Coverage owner was linked to the wrong audit target.')
    sizes = {t['id']: audit_request_chars([t], spans) for t in expected}
    if sizes != prepared['request_chars'] or any(n > prepared['max_chars'] for n in sizes.values()):
        raise ValueError('Coverage request size or budget changed.')
    records = set()
    for t in expected:
        scope = t.get('audit_partition')
        records.update(scope['requirement_ids'] + scope['package_reference_ids'] if scope else layout.record_refs)
    if records != set(layout.record_refs):
        raise ValueError('Coverage partitions lost an inventory record.')


def observe(prepared, checks):
    """Only validated auditor verdicts, not a boolean model coverage assertion, count."""
    for row in prepared['coverage_manifest'] + prepared['cross_partition_checks']:
        check = checks.get(row['target_id'])
        row['verdict'] = check['verdict'] if check else 'pending'
        row['passed'] = row['verdict'] == 'supported'
        if check:
            row['reason'] = check['reason']


def reduce(prepared, target, spans, checks):
    """Return a canonical coverage verdict only after exact range/receipt accounting."""
    from common.semantic_plan import validate_audit
    validate_layout(prepared, target, spans)
    expected = {t['id'] for t in prepared['targets']}
    subset = {k: v for k, v in checks.items() if k in expected}
    audited = validate_audit({'checks': subset}, prepared['targets'])
    observe(prepared, subset)
    errors = audited['errors']
    return {'verdict': 'supported' if audited['passed'] else 'unsupported',
            'reason': ('All source ranges and required cross-range checks passed; exact coverage manifest verified.'
                       if audited['passed'] else 'Partitioned package coverage failed: ' + '; '.join(errors))}


def receipt(prepared):
    return deepcopy({k: v for k, v in prepared.items() if k != 'targets'})
