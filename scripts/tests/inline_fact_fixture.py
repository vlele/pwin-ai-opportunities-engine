"""Offline fixture migration only, never a runtime repair or receipt rekeying."""
from copy import deepcopy


def inline_saved_mapping(raw):
    """Translate explicit valid old links; never infer or clamp a missing record."""
    result = deepcopy(raw)
    if 'fact_coverage' not in result:
        return result
    mapping = result.pop('fact_coverage')
    if not isinstance(mapping, dict):
        raise ValueError('Saved mapping must be an object.')
    arrays = ('requirements', 'quoted_vendor_context')
    for key in arrays:
        if not isinstance(result.get(key), list):
            raise ValueError('Saved record array is missing.')
        for row in result[key]:
            if not isinstance(row, dict) or 'originating_fact_ids' in row:
                raise ValueError('Saved row is malformed or has competing ownership declarations.')
            row['originating_fact_ids'] = []
    for fid, links in mapping.items():
        if not isinstance(fid, str) or not isinstance(links, list) or not links:
            raise ValueError('Saved fact ownership is empty or malformed.')
        seen = set()
        for link in links:
            if (not isinstance(link, dict) or set(link) != {'array', 'index'}
                    or link['array'] not in arrays or type(link['index']) is not int):
                raise ValueError(f'{fid}: malformed saved link.')
            key, index = link['array'], link['index']
            if not 0 <= index < len(result[key]):
                raise ValueError(f'{fid} -> {key}[{index}]: Unknown record index; no fixture repair inferred.')
            if (key, index) in seen:
                raise ValueError(f'{fid}: duplicate saved link.')
            seen.add((key, index))
            result[key][index]['originating_fact_ids'].append(fid)
    if any(not row['originating_fact_ids'] for key in arrays for row in result[key]):
        raise ValueError('Saved mapping has unowned records; no fixture ownership inferred.')
    return result
