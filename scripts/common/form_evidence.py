"""PDF choice observations, not inferences from the printed option labels."""
from copy import deepcopy
import math
import re

STATES = {'selected', 'unselected', 'uncertain'}


def page_controls(page):
    controls = []
    for widget in page.widgets() or []:
        if widget.field_type_string not in {'CheckBox', 'RadioButton'}:
            continue
        value = widget.field_value
        label = str(widget.field_label or widget.field_name or '').strip()
        on = widget.on_state() if hasattr(widget, 'on_state') else None
        state = 'uncertain'
        if value is False or str(value).lower() in {'off', 'false', '0'}:
            state = 'unselected'
        elif value is True or (on is not None and value == on):
            state = 'selected'
        controls.append({'id': f'p{page.number + 1}-w{widget.xref}', 'label': label,
                         'group': str(widget.field_name or ''), 'state': state if label else 'uncertain',
                         'raw_value': str(value), 'page_number': page.number + 1,
                         'bbox': list(widget.rect), 'page_size': [page.rect.width, page.rect.height],
                         'coordinate_space': 'pdf_points', 'basis': 'native_widget'})
    return controls


def has_flat_choices(page, text):
    # Geometry only selects pages for visual review; it never decides check state.
    if re.search(r'[\u2610\u2611\u2612]|\b(?:check|select)\s+(?:one|all that apply)\b', text, re.I):
        return True
    for drawing in page.get_drawings():
        rect = drawing.get('rect')
        if rect is not None and 3 <= rect.width <= 18 and 3 <= rect.height <= 18:
            if 0.7 <= rect.width / rect.height <= 1.4:
                return True
    return False


def normalize_vision_controls(values, page_number):
    controls = []
    for i, value in enumerate(values if isinstance(values, list) else []):
        if not isinstance(value, dict) or not isinstance(value.get('label'), str) or not value['label'].strip():
            continue
        bbox = value.get('bbox')
        valid_box = (isinstance(bbox, list) and len(bbox) == 4
                     and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) and 0 <= n <= 1 for n in bbox)
                     and bbox[0] < bbox[2] and bbox[1] < bbox[3])
        state = value.get('state', 'uncertain')
        controls.append({'id': f'p{page_number}-v{i + 1}', 'label': str(value['label']).strip(),
                         'group': str(value.get('group', '')).strip(),
                         'state': state if isinstance(state, str) and state in STATES and valid_box else 'uncertain',
                         'page_number': page_number, 'bbox': bbox if valid_box else [],
                         'coordinate_space': 'normalized_page', 'basis': 'vision_observation'})
    return controls


def merge_controls(native, vision):
    result = deepcopy(native + vision)
    def normalized_box(control):
        box = control.get('bbox')
        if not box or len(box) != 4:
            return None
        if control.get('coordinate_space') == 'normalized_page':
            return box
        size = control.get('page_size')
        if control.get('coordinate_space') == 'pdf_points' and size and min(size) > 0:
            return [box[0] / size[0], box[1] / size[1], box[2] / size[0], box[3] / size[1]]
        return None
    def same_control(left, right):
        a, b = normalized_box(left), normalized_box(right)
        if a is not None and b is not None:
            return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
        return not left.get('group') or not right.get('group') or left['group'] == right['group']
    for item in result:
        peers = [p for p in result if p['page_number'] == item['page_number']
                 and p['label'].casefold() == item['label'].casefold()
                 and same_control(p, item)]
        if len({p['state'] for p in peers} - {'uncertain'}) > 1:
            for peer in peers:
                peer['state'] = 'uncertain'
                peer['review_note'] = 'Conflicting observations; selection is unresolved.'
    return result


def packet_sources(controls, *, document_id, filename, prefix, offset):
    sources = {}
    for index, control in enumerate(controls):
        sid = f'{prefix}C{index + 1}'
        text = (f"Form observation {control['id']}: group {control.get('group', '')}; "
                f"label {control['label']}; state {control['state']}; basis {control['basis']}. "
                "This is a control-state observation, not a requirement inferred from an unselected label.")
        sources[sid] = {'kind': 'package', 'document_id': document_id, 'filename': filename,
                        'offset': offset, 'text': text, 'provenance': 'form_control_observation',
                        'form_controls': [deepcopy(control)],
                        'text_regions': [{'start': offset, 'end': offset + len(text), 'page_number': control['page_number'],
                                          'basis': control['basis'], 'bbox': control['bbox']}]}
        offset += len(text)
    return sources
