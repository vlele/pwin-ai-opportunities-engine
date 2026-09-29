"""Lossless, request-local quotation interning for package completeness audits.

Only exact ref/quote objects are interned. Source spans, interpretations, record
order and verdict contracts are untouched. JSON pointers refer to this request's
registry, not external retrieval or inferred equivalent passages.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json

FORMAT = 'coverage-evidence-json-pointer-v1'
ENCODING_KEY = 'audit_evidence_encoding'
REGISTRY_KEY = 'evidence_registry'
PREFIX = '#/evidence_registry/'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _anchor(value):
    return isinstance(value, dict) and set(value) == {'ref', 'quote'}


def _validate_anchor(anchor, spans):
    ref, quote = anchor['ref'], anchor['quote']
    if not isinstance(ref, str) or ref not in spans:
        raise ValueError('Coverage registry contains an unknown source reference.')
    span = spans[ref]
    if not isinstance(span, dict) or span.get('kind') != 'package':
        raise ValueError('Private evidence cannot enter a package coverage registry.')
    if (not isinstance(quote, str) or not quote.strip() or not isinstance(span.get('text'), str)
            or quote not in span['text']):
        raise ValueError('Coverage registry quotation is not exact original source text.')


def encode(payload):
    """Return a smaller self-contained wire payload, or the unchanged representation."""
    targets = payload.get('targets', [])
    if not targets or any(row.get('kind') != 'package_coverage' for row in targets):
        return deepcopy(payload)
    if ENCODING_KEY in payload or REGISTRY_KEY in payload:
        raise ValueError('Reserved coverage encoding keys already exist in the payload.')
    spans = payload.get('spans', {})
    if not isinstance(spans, dict) or any(not isinstance(s, dict) or s.get('kind') != 'package' for s in spans.values()):
        raise ValueError('Package coverage encoding requires package-only source spans.')
    anchors, counts = {}, Counter()

    def collect(value):
        if _anchor(value):
            _validate_anchor(value, spans)
            key = 'E' + _digest(value)
            if key in anchors and anchors[key] != value:
                raise ValueError('Coverage evidence digest collision.')
            anchors[key] = deepcopy(value)
            counts[key] += 1
        elif isinstance(value, dict):
            if '$ref' in value:
                raise ValueError('Unencoded audit target cannot contain registry pointers.')
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(targets)
    # Very short or unique anchors are cheaper left inline. Final sizing below
    # includes the registry and integrity envelope, not just saved quote bytes.
    registry = {key: anchor for key, anchor in anchors.items() if counts[key] > 1 and
                (counts[key] - 1) * len(json.dumps(anchor)) >
                counts[key] * len(json.dumps({'$ref': PREFIX + key})) + len(json.dumps(key)) + 4}
    if not registry:
        return deepcopy(payload)

    def replace(value):
        if _anchor(value):
            key = 'E' + _digest(value)
            return {'$ref': PREFIX + key} if key in registry else deepcopy(value)
        if isinstance(value, dict):
            return {key: replace(child) for key, child in value.items()}
        if isinstance(value, list):
            return [replace(child) for child in value]
        return deepcopy(value)

    result = deepcopy(payload)
    result['targets'] = replace(targets)
    result[REGISTRY_KEY] = registry
    result[ENCODING_KEY] = {'format': FORMAT, 'canonical_payload_sha256': _digest(payload)}
    if decode(result) != payload:
        raise ValueError('Coverage encoding did not round-trip exactly.')
    if len(json.dumps(result)) >= len(json.dumps(payload)):
        return deepcopy(payload)
    return result


def decode(payload):
    """Verify the registry and restore the original payload for receipts and tests."""
    if ENCODING_KEY not in payload and REGISTRY_KEY not in payload:
        return deepcopy(payload)
    info, registry = payload.get(ENCODING_KEY), payload.get(REGISTRY_KEY)
    if (not isinstance(info, dict) or set(info) != {'format', 'canonical_payload_sha256'}
            or info['format'] != FORMAT or not isinstance(registry, dict) or not registry):
        raise ValueError('Malformed coverage encoding envelope.')
    spans = payload.get('spans', {})
    for key, anchor in registry.items():
        if not _anchor(anchor) or key != 'E' + _digest(anchor):
            raise ValueError('Coverage registry evidence identity changed.')
        _validate_anchor(anchor, spans)
    used = set()

    def expand(value):
        if isinstance(value, dict):
            if '$ref' in value:
                pointer = value['$ref']
                if set(value) != {'$ref'} or not isinstance(pointer, str) or not pointer.startswith(PREFIX):
                    raise ValueError('Invalid coverage evidence pointer.')
                key = pointer[len(PREFIX):]
                if key not in registry:
                    raise ValueError('Dangling coverage evidence pointer.')
                used.add(key)
                return deepcopy(registry[key])
            return {key: expand(child) for key, child in value.items()}
        if isinstance(value, list):
            return [expand(child) for child in value]
        return deepcopy(value)

    result = {key: deepcopy(value) for key, value in payload.items()
              if key not in {ENCODING_KEY, REGISTRY_KEY}}
    result['targets'] = expand(result.get('targets', []))
    if used != set(registry):
        raise ValueError('Coverage registry contains unused entries.')
    if _digest(result) != info['canonical_payload_sha256']:
        raise ValueError('Coverage payload integrity check failed.')
    return result


def receipt(payload):
    if ENCODING_KEY not in payload:
        return {}
    original = decode(payload)
    return {**payload[ENCODING_KEY], 'registry_entries': len(payload[REGISTRY_KEY]),
            'source_spans': len(payload.get('spans', {})),
            'original_payload_chars': len(json.dumps(original)),
            'encoded_payload_chars': len(json.dumps(payload)), 'round_trip_verified': True}
