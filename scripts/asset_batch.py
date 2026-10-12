"""One host sheet, separately replaceable crops, and explicit per-item decisions.

Accepted is a crop-selection decision. It never certifies visual fidelity or Office.
No provider calls or project state mutations occur in these helpers.
"""
from __future__ import annotations

import copy
import math
import os
import shutil
from pathlib import Path

from PIL import Image

if __package__:
    from .common import read_json, sha256, staged_directory, write_json
    from .material_routes import DECISION_SCHEMA
else:
    from common import read_json, sha256, staged_directory, write_json
    from material_routes import DECISION_SCHEMA

BATCH_ITEM_SCHEMA = {'type': 'object', 'properties': {
    'id': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$'},
    'purpose': {'type': 'string', 'minLength': 1}, 'generation_decision': DECISION_SCHEMA,
    'target_bbox_xywh': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
    'min_subject_pixels': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}, 'minItems': 2, 'maxItems': 2},
    'scope_unit_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'uniqueItems': True},
}, 'required': ['id', 'purpose', 'generation_decision'], 'additionalProperties': False}
BATCH_RESULT_ITEM_SCHEMA = {'type': 'object', 'properties': {
    'id': {'type': 'string'},
    'crop': {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 4, 'maxItems': 4},
    'status': {'enum': ['accepted', 'retry']}, 'note': {'type': 'string', 'minLength': 1},
    'viewed_files': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
}, 'required': ['id', 'crop', 'status', 'note', 'viewed_files'], 'additionalProperties': False}


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise ValueError('Asset batch fields are missing or unknown')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be a nonempty string')


def validate_batch_request(request, project=None):
    """Validate item identity and generation constraints; permit a one-item retry."""
    if __package__:
        from .material_routes import validate_decision
    else:
        from material_routes import validate_decision
    import re
    if request.get('multi_icon_sheet') is not True or request.get('transparent') is not True:
        raise ValueError('Asset batch requires multi_icon_sheet and transparent true')
    items = request.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        raise ValueError('Asset batch requires 1..8 items (one item is valid for retry)')
    seen = set()
    for item in items:
        _keys(item, ('id', 'purpose', 'generation_decision'),
              ('target_bbox_xywh', 'min_subject_pixels', 'scope_unit_ids'))
        if not isinstance(item['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}', item['id']):
            raise ValueError('asset batch item id requires 1..40 ASCII letters, digits, - or _')
        if item['id'] in seen:
            raise ValueError('Duplicate asset batch item id')
        seen.add(item['id'])
        _text(item['purpose'], 'Item purpose')
        validate_decision(item['generation_decision'], project)
        if 'target_bbox_xywh' in item:
            box = item['target_bbox_xywh']
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                    or box[2] <= 0 or box[3] <= 0):
                raise ValueError('target_bbox_xywh requires finite positive dimensions')
        if 'min_subject_pixels' in item:
            pixels = item['min_subject_pixels']
            if not isinstance(pixels, list) or len(pixels) != 2 or any(type(v) is not int or v <= 0 for v in pixels):
                raise ValueError('min_subject_pixels requires positive integer width,height')
        if 'scope_unit_ids' in item:
            units = item['scope_unit_ids']
            if not isinstance(units, list) or not units or any(not isinstance(v, str) or not v for v in units) or len(units) != len(set(units)):
                raise ValueError('scope_unit_ids requires unique nonempty unit IDs')
    return copy.deepcopy(request)


def validate_batch_result(project, job, result):
    """Inspect bytes and actual crop coordinates without writing any files."""
    request = validate_batch_request(job['request'], project)
    _keys(result, ('file', 'tool_used', 'provenance', 'sheet_sha256', 'items'), ('model_reported',))
    for field in ('file', 'tool_used', 'provenance'):
        _text(result[field], field)
    if result.get('model_reported') is not None and not isinstance(result['model_reported'], str):
        raise ValueError('model_reported must be a string or null')
    source = Path(result['file']).resolve()
    source_hash = sha256(source)
    if result['sheet_sha256'] != source_hash:
        raise ValueError('Sheet hash changed; old crop coordinates cannot be reused')
    expected = {item['id']: item for item in request['items']}
    rows = result['items']
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError('Every pending asset batch item needs a decision')
    manifest = {'format': 'ppt-asset-batch-ingestion/1', 'job_id': job['id'],
                'producer_claim': {field: result.get(field) for field in ('tool_used', 'model_reported', 'provenance')},
                'decision_scope': 'crop_selection_only', 'visual_review_status': 'not_run', 'items': []}
    seen = set()
    accepted_boxes = []
    with Image.open(source) as original:
        original.load()
        if original.format != 'PNG':
            raise ValueError('Asset batch requires actual PNG bytes')
        if 'A' not in original.getbands() and 'transparency' not in original.info:
            raise ValueError('Sheet needs a real transparency channel')
        rgba = original.convert('RGBA')
        alpha_range = rgba.getchannel('A').getextrema()
        if alpha_range[0] == 255 or alpha_range[1] == 0:
            raise ValueError('Sheet needs visible content and real transparency')
        manifest['sheet'] = {'file': 'sheet.png', 'sha256': source_hash,
                             'size': list(rgba.size), 'alpha_range': list(alpha_range)}
        for row in rows:
            _keys(row, ('id', 'crop', 'status', 'note', 'viewed_files'))
            if row['id'] not in expected or row['id'] in seen:
                raise ValueError('Unknown or duplicate asset batch item id')
            seen.add(row['id'])
            if row['status'] not in ('accepted', 'retry'):
                raise ValueError('Item status must be accepted or retry')
            _text(row['note'], 'Item decision note')
            viewed = row['viewed_files']
            if not isinstance(viewed, list) or not viewed or any(not isinstance(v, str) or not Path(v).is_file() for v in viewed):
                raise ValueError('Each crop decision needs existing viewed_files')
            if source not in [Path(v).resolve() for v in viewed]:
                raise ValueError('Each crop decision must identify the actual sheet as viewed')
            if any(Path(v).resolve() != source and not Path(v).resolve().is_relative_to(Path(project).resolve()) for v in viewed):
                raise ValueError('viewed_files must belong to this project or identify the actual sheet')
            crop = row['crop']
            if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop):
                raise ValueError('Actual crop must be integer [x,y,width,height]')
            x, y, width, height = crop
            if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > rgba.width or y + height > rgba.height:
                raise ValueError('Actual crop lies outside the sheet')
            item = {**copy.deepcopy(row), 'source_sheet_sha256': source_hash,
                    'visual_review_status': 'not_run',
                    'generation_decision': copy.deepcopy(expected[row['id']]['generation_decision'])}
            from_reference = Path(project) / expected[row['id']]['generation_decision']['reference']
            item['reference'] = {'file': expected[row['id']]['generation_decision']['reference'],
                                 'sha256': sha256(from_reference)}
            for field in ('target_bbox_xywh', 'scope_unit_ids'):
                if field in expected[row['id']]:
                    item[field] = copy.deepcopy(expected[row['id']][field])
            cropped = rgba.crop((x, y, x + width, y + height))
            alpha = cropped.getchannel('A')
            subject = alpha.point(lambda value: 255 if value >= 32 else 0).getbbox()
            if row['status'] == 'accepted':
                if subject is None or alpha.getextrema()[0] == 255:
                    raise ValueError('Accepted crop needs a visible subject and real transparency')
                for left, top, right, bottom in accepted_boxes:
                    if max(x, left) < min(x + width, right) and max(y, top) < min(y + height, bottom):
                        raise ValueError('Accepted item crops overlap; separate independent sheet subjects')
                accepted_boxes.append((x, y, x + width, y + height))
                l, t, r, b = subject
                item['subject_bbox_xywh'] = [l, t, r - l, b - t]
                item['subject_alpha_threshold'] = 32
                item['subject_pixels'] = [r - l, b - t]
                minimum = expected[row['id']].get('min_subject_pixels')
                if minimum is not None and (r - l < minimum[0] or b - t < minimum[1]):
                    raise ValueError('Accepted crop subject does not meet min_subject_pixels')
                item['min_subject_pixels'] = minimum
                item['asset'] = 'assets/' + row['id'] + '.png'
                item['source_crop'] = list(crop)
                all_visible = alpha.getbbox()
                item['subject_touches_crop_edge'] = all_visible[0] == 0 or all_visible[1] == 0 or all_visible[2] == width or all_visible[3] == height
            manifest['items'].append(item)
    return manifest


def ingest_batch_result(project, job, result, dest):
    """Publish once, or verify an identical interrupted publication without writes."""
    manifest = validate_batch_result(project, job, result)
    source = Path(result['file']).resolve()
    dest = Path(dest).absolute()
    if dest.exists() or dest.is_symlink():
        return _recover_published_batch(project, dest, manifest)
    with staged_directory(dest) as stage:
        shutil.copyfile(source, stage / 'sheet.png')
        if sha256(stage / 'sheet.png') != manifest['sheet']['sha256']:
            raise ValueError('Sheet changed during ingestion')
        with Image.open(stage / 'sheet.png') as original:
            rgba = original.convert('RGBA')
            for item in manifest['items']:
                if item['status'] != 'accepted':
                    continue
                x, y, w, h = item['crop']
                asset = stage / item['asset']
                asset.parent.mkdir(exist_ok=True)
                rgba.crop((x, y, x + w, y + h)).save(asset)
                item['asset_sha256'] = sha256(asset)
        write_json(stage / 'batch-manifest.json', manifest)
    return manifest


def _recover_published_batch(project, dest, expected):
    """Trust only exact bytes and the current revalidated manifest, not existence."""
    root = Path(project).resolve()
    if not dest.resolve().is_relative_to(root) or not dest.is_dir():
        raise ValueError('Existing batch destination is not a project directory')
    # Reject symlinks/junctions on the directory and every artifact before reads.
    def regular_path(path):
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('Existing batch path leaves the project')
        current = path
        while current != root:
            info = os.stat(current, follow_symlinks=False)
            if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Existing batch paths cannot be symlinks or junctions')
            if current.parent == current:
                raise ValueError('Existing batch path has an invalid root')
            current = current.parent
    regular_path(dest)
    manifest_path = dest / 'batch-manifest.json'
    regular_path(manifest_path)
    saved = read_json(manifest_path)
    if not isinstance(saved, dict):
        raise ValueError('Existing batch manifest is invalid')
    structural = copy.deepcopy(saved)
    for item in structural.get('items', []):
        if not isinstance(item, dict):
            raise ValueError('Existing batch manifest item is invalid')
        item.pop('asset_sha256', None)
    if structural != expected:
        raise ValueError('Existing batch manifest differs from this task/result')
    sheet = dest / 'sheet.png'
    regular_path(sheet)
    if sha256(sheet) != expected['sheet']['sha256']:
        raise ValueError('Existing batch sheet hash changed')
    required_files = {'sheet.png', 'batch-manifest.json'}
    with Image.open(sheet) as original:
        rgba = original.convert('RGBA')
        for item in saved['items']:
            if item['status'] != 'accepted':
                continue
            asset = dest / item['asset']
            regular_path(asset)
            required_files.add(item['asset'])
            if sha256(asset) != item.get('asset_sha256'):
                raise ValueError('Existing batch crop hash changed')
            x, y, width, height = item['crop']
            with Image.open(asset) as crop:
                if (crop.format != 'PNG' or crop.size != (width, height)
                        or crop.convert('RGBA').tobytes() != rgba.crop((x, y, x + width, y + height)).tobytes()):
                    raise ValueError('Existing batch crop pixels differ from the sheet')
    actual_files = set()
    for file in dest.rglob('*'):
        regular_path(file)
        if file.is_file():
            actual_files.add(file.relative_to(dest).as_posix())
    if actual_files != required_files:
        raise ValueError('Existing batch contains unexpected or missing artifacts')
    return saved
