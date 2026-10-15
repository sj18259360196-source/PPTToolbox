"""Read-only, candidate-bound preparation. Never supplies execution or visual verdicts."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

if __package__:
    from .common import read_json, sha256, walk_objects
    from .edit_runner import inventory, suggested_operations
    from .material_quality import edit_requirements
    from .material_edit_review import picture_edit_geometry
    from .office_edit import validate_operations
else:
    from common import read_json, sha256, walk_objects
    from edit_runner import inventory, suggested_operations
    from material_quality import edit_requirements
    from material_edit_review import picture_edit_geometry
    from office_edit import validate_operations


FORMAT = 'ppt-edit-preparation/1'
ACTION_KINDS = {'text': 'text', 'shape': 'shape', 'table': 'table', 'chart': 'chart',
                'image_move': 'image', 'image_resize': 'image', 'image_replace': 'image'}
OP_ACTIONS = {'text.set': ['text'], 'shape.fill': ['shape'], 'table.cell': ['table'],
              'picture.transform': ['image_move', 'image_resize']}


def _transform(row, canvas):
    """Conservative copy-only proposal using the executor's slide coordinate mapping."""
    shape = row['shape']
    try:
        geometry = picture_edit_geometry(shape._element)
    except (ValueError, TypeError, AttributeError) as exc:
        return None, 'unsupported_picture_geometry: '+str(exc)
    if any(not math.isfinite(v) for v in geometry.values()) or geometry['rotation']:
        return None, 'rotated_or_invalid_picture_requires_explicit_operation'
    width, height = geometry['width']*.95, geometry['height']*.95
    if width <= 0 or height <= 0 or width > canvas[0] or height > canvas[1]:
        return None, 'picture_dimensions_need_explicit_operation'
    left = min(max(geometry['left']+5, 0), canvas[0]-width)
    top = min(max(geometry['top'], 0), canvas[1]-height)
    if abs(left-geometry['left']) <= .05:
        top = min(max(geometry['top']+5, 0), canvas[1]-height)
    if (max(abs(left-geometry['left']), abs(top-geometry['top'])) <= .05
            or min(geometry['width']-width, geometry['height']-height) <= .05):
        return None, 'picture_change_below_readback_tolerance'
    return {'op': 'picture.transform', 'slide': row['slide'], 'name': row['name'],
            'units': 'slide_points', 'aspect_ratio': 'preserve', 'expected': geometry,
            'value': {**geometry, 'left': left, 'top': top, 'width': width, 'height': height}}, None


def build(scene_path, candidate_path, required_actions, *, project_id=None, run_id=None):
    """Prepare all obligations, plus bounded operation batches; perform no writes."""
    scene_path, candidate_path = Path(scene_path).resolve(), Path(candidate_path).resolve()
    scene_hash, candidate_hash = sha256(scene_path), sha256(candidate_path)
    scene = read_json(scene_path)
    deck, rows = inventory(candidate_path)
    if len(scene['slides']) != len(deck.slides):
        raise ValueError('Edit preparation scene/candidate slide count differs')
    actual = {}
    # Include groups in identity checks even though the generic sample runner omits them.
    def collect(shapes, slide):
        for shape in shapes:
            actual.setdefault((slide, shape.name), []).append(shape)
            if shape.shape_type == 6:
                collect(shape.shapes, slide)
    for index, slide in enumerate(deck.slides, 1):
        collect(slide.shapes, index)
    targets, by_key = [], {}
    for index, slide in enumerate(scene['slides'], 1):
        for obj in walk_objects(slide['objects']):
            key = (index, obj['id'])
            if key in by_key:
                raise ValueError('Duplicate scene edit target: '+obj['id'])
            matches = actual.get(key, [])
            kind = obj['kind']; shape = matches[0] if len(matches) == 1 else None
            compatible = shape is not None and (
                (kind == 'image' and shape.shape_type == 13)
                or (kind == 'group' and shape.shape_type == 6)
                or (kind == 'text' and shape.has_text_frame)
                or (kind == 'table' and shape.has_table)
                or (kind == 'chart' and shape.has_chart)
                or (kind in ('line', 'connector') and shape.shape_type == 9)
                or (kind == 'path' and shape.shape_type == 5)
                or (kind == 'shape' and shape.shape_type in (1, 5, 9)))
            target = {'slide': index, 'slide_id': slide['id'], 'name': obj['id'], 'kind': kind,
                      'binding_status': 'matched' if compatible else 'blocked'}
            if not compatible:
                target['reason'] = 'candidate_target_missing_ambiguous_or_wrong_kind'
            targets.append(target); by_key[key] = target
    required_actions = list(dict.fromkeys(required_actions))
    action_choices = [{'action': action,
                       'candidates': [t for t in targets if t['kind'] == ACTION_KINDS.get(action)],
                       'status': 'not_run'} for action in required_actions]
    materials = edit_requirements(scene)
    needed_pictures = {(r['slide'], name) for r in materials for name in r['picture_ids']}
    valid_rows = [r for r in rows if by_key.get((r['slide'], r['name']), {}).get('binding_status') == 'matched']
    operations = []
    try:
        samples = suggested_operations(valid_rows)
    except ValueError:
        samples = []
    # Generic image requirements are sampled; independent materials need every unit.
    # Do not expand every non-material image into a new mandatory test.
    if not needed_pictures and any(a.startswith('image_') for a in required_actions):
        picture_sample = next((op for op in samples if op['op'] == 'picture.transform'), None)
        if picture_sample is None:
            picture_sample = next((r for r in valid_rows if r['shape'].shape_type == 13), None)
        if picture_sample:
            needed_pictures.add((picture_sample['slide'], picture_sample['name']))
    # Keep generic text/shape/table sampling semantics; material coverage is explicit below.
    for op in samples:
        if op['op'] != 'picture.transform' and set(OP_ACTIONS.get(op['op'], [])) & set(required_actions):
            operations.append(op)
    pictures = []
    canvas = [float(deck.slide_width)/12700, float(deck.slide_height)/12700]
    row_index = {(r['slide'], r['name']): r for r in valid_rows}
    for key in sorted(needed_pictures):
        row = row_index.get(key)
        item = {'slide': key[0], 'name': key[1], 'execution_status': 'not_run', 'visual_status': 'not_run'}
        if row is None:
            item.update(transform_status='blocked', reason='candidate_target_missing_ambiguous_or_wrong_kind',
                        replacement_status='blocked')
        else:
            item['transform_target_scope'] = 'picture_child' if row['grouped'] else 'picture'
            item['whole_material_group_tested'] = False
            operation, reason = _transform(row, canvas)
            item['transform_status'] = 'operation_prepared' if operation else 'needs_explicit_operation'
            if operation:
                operations.append(operation)
            if reason:
                item['reason'] = reason
            item['replacement_status'] = 'needs_replacement_asset'
            item['replacement_draft'] = {'op': 'picture.replace', 'slide': key[0], 'name': key[1],
                'image': '', 'image_sha256': '', 'expected_sha256': hashlib.sha256(row['shape'].image.blob).hexdigest(),
                'crop_policy': '', 'fit_policy': ''}
            item['replacement_inputs'] = ['source-directory-relative PNG/JPEG with different decoded pixels',
                                          'image_sha256', 'explicit crop_policy preserve/reset and fit_policy stretch']
        pictures.append(item)
    for material in materials:
        material['status'] = 'not_run'
        material['background_views'] = [{'role': role, 'status': 'blocked', 'files': []}
                                        for role in ('light', 'dark', 'target')]
        material['observation_drafts'] = [
            {'slide_id': material['slide_id'], 'object_id': material['object_ids'][0] if len(material['object_ids']) == 1 else '',
             'operation': action, 'scope': 'required', 'status': 'blocked', 'finding': '',
             'required_adjustment': '', 'evidence_files': []} for action in material['summary_actions']]
    batches = []
    for offset in range(0, len(operations), 100):
        ops = validate_operations(copy.deepcopy(operations[offset:offset+100]))
        batches.append({'id': f'batch-{len(batches)+1:03}', 'operations': ops, 'execution_status': 'not_run'})
    if sha256(scene_path) != scene_hash or sha256(candidate_path) != candidate_hash:
        raise ValueError('Edit preparation input changed during reading')
    return {'format': FORMAT, 'status': 'needs_execution_and_observations',
            'binding': {'project_id': project_id, 'run_id': run_id,
                        'scene': {'file': str(scene_path), 'sha256': scene_hash},
                        'candidate': {'file': str(candidate_path), 'sha256': candidate_hash}},
            'targets': targets, 'target_count': len(targets), 'targets_truncated': False,
            'required_actions': action_choices, 'materials': materials, 'pictures': pictures,
            'operation_batches': batches, 'prepared_operation_count': len(operations),
            'all_objects_tested': False, 'execution_status': 'not_run', 'visual_status': 'not_run',
            'instructions': [
                'Prepared operations are suggestions for separate candidate copies. Preflight before execution; inspect actual renders.',
                'Batches cover prepared operations only. Complete every current required action and material obligation, including pending replacements and backgrounds.',
                'Background variants and incompatible edits need separate copies. Do not overwrite one test condition with another before checking it.',
                'Grouped material observations belong to its root IDs; editing one child does not prove whole-group movement or resizing.',
                'Charts, unsupported groups, replacement choices and text layout need explicit work. No old failures or observations are cleared by this preparation.']}
