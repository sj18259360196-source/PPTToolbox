"""v1.1.1 evidence contracts. File identity/declared coverage, NOT visual truth.
No Office execution, image generation, or automatic semantic acceptance here.
"""
from __future__ import annotations

import math
import re
from pathlib import Path, PureWindowsPath
from typing import Any
from PIL import Image
from common import read_json, resolve_asset, sha256, walk_objects
from evidence_session import image_metadata, measured, scoped

EVIDENCE_VERSION = '1.1.1'
IMAGE_KINDS = ('side_by_side', 'overlay', 'absolute_difference')
RESERVED_IDS = {'full', 'comparison', 'deck-comparison', 'readme'}


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def digest_ok(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def safe_file(root: Path, relative: str) -> Path:
    """Evidence links are portable relative POSIX paths confined to their root."""
    if not nonempty(relative) or '\\' in relative or ':' in relative:
        raise ValueError(f'Invalid evidence-relative path: {relative!r}')
    if Path(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
        raise ValueError(f'Absolute evidence path: {relative!r}')
    return resolve_asset(root, relative)


def image_size(path: Path, png_only: bool = False) -> list[int]:
    return image_metadata(path, png_only=png_only)[0]


def checked_file(root: Path, relative: str, expected: str, image: bool = False,
                 dimensions: list | None = None) -> Path:
    if not digest_ok(expected):
        raise ValueError(f'Missing/invalid SHA256 for {relative!r}')
    path = safe_file(root, relative)
    if image:
        size, _ = image_metadata(path, png_only=True, expected=expected)
        if dimensions is not None:
            dimensions.extend(size)
    elif sha256(path) != expected:
        raise ValueError(f'File hash mismatch: {relative}')
    return path


def indexed_rows(rows: Any, count: int, label: str, exact: bool = True) -> dict[int, dict]:
    if not isinstance(rows, list):
        raise ValueError(f'{label}: expected a list')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'{label}: expected object rows')
        idx = row.get('index')
        if type(idx) is not int or not 1 <= idx <= count:
            raise ValueError(f'{label}: invalid slide index {idx!r}')
        if idx in result:
            raise ValueError(f'{label}: duplicate slide index {idx}')
        result[idx] = row
    if exact and set(result) != set(range(1, count + 1)):
        raise ValueError(f'{label}: does not cover the slide set exactly')
    return result


def reference_snapshot(scene_path: Path) -> tuple[dict, list[dict], str | None]:
    """Re-read all original references; optionally enforce init_project's manifest."""
    scene = read_json(scene_path)
    slides = scene.get('slides')
    if not isinstance(slides, list) or not slides:
        raise ValueError('A nonempty slide list is required')
    seen = set()
    refs = []
    for idx, slide in enumerate(slides, 1):
        sid = slide.get('id')
        if not nonempty(sid) or sid in seen:
            raise ValueError(f'Invalid or duplicate slide ID: {sid!r}')
        seen.add(sid)
        ref = safe_file(scene_path.parent, slide.get('reference'))
        size, identity = image_metadata(ref)
        refs.append({'index': idx, 'slide_id': sid, 'path': slide['reference'],
                     'size': size, 'sha256': identity})
    manifest = scene_path.parent / 'input/references.json'
    manifest_hash = None
    if manifest.exists():
        rows = read_json(manifest)
        converted = []
        if not isinstance(rows, list):
            raise ValueError('input/references.json must be a list')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid reference manifest row')
            converted.append({**row, 'index': row.get('slide')})
        mapped = indexed_rows(converted, len(slides), 'Reference manifest')
        for ref in refs:
            old = mapped[ref['index']]
            for key in ('path', 'size', 'sha256'):
                if old.get(key) != ref[key]:
                    raise ValueError(f'Reference manifest mismatch slide {ref["index"]}: {key}')
        manifest_hash = sha256(manifest)
    return scene, refs, manifest_hash


def validate_render(receipt_path: Path, pptx: Path, count: int) -> tuple[dict, dict[int, dict]]:
    receipt = read_json(receipt_path)
    if receipt.get('format') == 'ppt-preview-render/1' or receipt.get('accepted_for_office_gate') is False:
        raise ValueError('Preview evidence cannot be used as Microsoft PowerPoint validation')
    if receipt.get('renderer') != 'Microsoft PowerPoint' or receipt.get('probe_only', False):
        raise ValueError('Not an actual Microsoft PowerPoint page-render receipt')
    if receipt.get('status') != 'passed':
        raise ValueError('PowerPoint rendering has not passed')
    if receipt.get('pptx_sha256') != sha256(pptx):
        raise ValueError('Office receipt is for a different PPTX')
    rows = indexed_rows(receipt.get('slides'), count, 'Office receipt')
    filenames = set()
    for idx, row in rows.items():
        size = []
        path = checked_file(receipt_path.parent, row.get('file'), row.get('sha256'),
                            image=True, dimensions=size)
        key = path.as_posix().casefold()
        if key in filenames:
            raise ValueError('Two Office pages refer to the same PNG file')
        filenames.add(key)
        if type(row.get('width')) is not int or type(row.get('height')) is not int:
            raise ValueError(f'Office receipt lacks integer image dimensions: slide {idx}')
        if [row['width'], row['height']] != size:
            raise ValueError(f'Office image dimensions mismatch: slide {idx}')
    return receipt, rows


def normalize_regions(regions: Any, size: list[int] | tuple[int, int]) -> list[dict]:
    if regions is None:
        return []
    if not isinstance(regions, list):
        raise ValueError('Regions must be a list')
    used = set()
    result = []
    for region in regions:
        if not isinstance(region, dict) or set(region) - {'id', 'bbox', 'object_ids', 'note'}:
            raise ValueError('Region keys: id, bbox, object_ids, note only')
        name = region.get('id')
        if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
            raise ValueError('Region IDs must be safe ASCII filenames, 1..80 characters')
        if name.casefold() in RESERVED_IDS or name.casefold() in used:
            raise ValueError(f'Reserved or duplicate region ID: {name}')
        used.add(name.casefold())
        box = region.get('bbox')
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
            raise ValueError('Region bbox must be integer xyxy [left,top,right,bottom]')
        l, t, r, b = box
        if not (0 <= l < r <= size[0] and 0 <= t < b <= size[1]):
            raise ValueError(f'Invalid crop {name}: {box}')
        ids = region.get('object_ids', [])
        if not isinstance(ids, list) or any(not nonempty(v) for v in ids) or len(ids) != len(set(ids)):
            raise ValueError(f'Invalid/duplicate object_ids in region {name}')
        if 'note' in region and not isinstance(region['note'], str):
            raise ValueError('Region note must be a string')
        result.append({'id': name, 'bbox': box, 'object_ids': ids, 'note': region.get('note', '')})
    return result


def regions_by_index(spec: Any, count: int) -> dict[int, list]:
    if spec is None:
        return {}
    if isinstance(spec, list):
        if count != 1:
            raise ValueError('List regions format is single-slide only; use {slides:[...]} for decks')
        return {1: spec}
    if not isinstance(spec, dict) or set(spec) != {'slides'}:
        raise ValueError('Regions spec must be a list or {slides:[...]}')
    rows = indexed_rows(spec['slides'], count, 'Regions spec', exact=False)
    for row in rows.values():
        if set(row) != {'index', 'regions'}:
            raise ValueError('Regions slide keys must be index and regions')
    return {idx: row['regions'] for idx, row in rows.items()}


def required_review(slide: dict) -> dict:
    """Structural triggers are additive. They do not discover omitted source objects."""
    objects = list(walk_objects(slide.get('objects', [])))
    names = [o['id'] for o in objects]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate object IDs in review input')
    local, relationships = set(), set()
    for obj in objects:
        kind = obj['kind']
        style = obj.get('style', {})
        directional = any(style.get(k) not in (None, 'none') for k in ('begin_arrow', 'end_arrow'))
        is_relation = kind == 'connector' or directional or obj.get('geometry') in {'right_arrow', 'left_right_arrow', 'chevron'}
        if is_relation:
            relationships.add(obj['id'])
        if (is_relation or kind in {'path', 'table', 'chart'}
                or kind == 'shape' and obj.get('geometry') not in {'rect', 'round_rect', 'ellipse'}
                or kind == 'image' and (obj.get('source_kind') == 'generated' or obj.get('asset_role') in {'icon', 'logo'})):
            local.add(obj['id'])
    explicit = slide.get('review_requirements', {})
    if not isinstance(explicit, dict) or set(explicit) - {'local_objects', 'relationship_objects'}:
        raise ValueError('Invalid review_requirements')
    for field, target in [('local_objects', local), ('relationship_objects', relationships)]:
        values = explicit.get(field, [])
        if not isinstance(values, list) or any(not nonempty(v) for v in values) or len(values) != len(set(values)):
            raise ValueError(f'Invalid {field}')
        if set(values) - set(names):
            raise ValueError(f'{field}: unknown object IDs {sorted(set(values) - set(names))}')
        target.update(values)
    local.update(relationships)
    return {'local_objects': sorted(local), 'relationship_objects': sorted(relationships)}


def logical_bounds(obj: dict) -> list[float]:
    """Conservative declared bounds, including Bezier controls, not visible glyph bounds."""
    if obj['kind'] == 'group':
        boxes = [logical_bounds(c) for c in obj['children']]
        box = [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)]
    elif 'bbox' in obj:
        x, y, w, h = obj['bbox']
        box = [x, y, x + w, y + h]
    else:
        points = obj.get('points')
        if points is None:
            points = [cmd[i:i + 2] for cmd in obj.get('commands', []) for i in range(1, len(cmd), 2)]
        if not points:
            raise ValueError(f'No geometry for required review object: {obj["id"]}')
        box = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    angle = math.radians(obj.get('rotation', 0))
    if angle:
        l, t, r, b = box; cx, cy = (l + r) / 2, (t + b) / 2
        pts = [(cx + (x - cx) * math.cos(angle) - (y - cy) * math.sin(angle),
                cy + (x - cx) * math.sin(angle) + (y - cy) * math.cos(angle)) for x, y in [(l, t), (r, t), (r, b), (l, b)]]
        box = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    return box


def review_mapping(scene: dict, slide: dict, size: list[int]) -> dict:
    transform = slide.get('review_mapping')
    if transform is not None:
        keys = {'scale_x', 'scale_y', 'offset_x', 'offset_y'}
        if not isinstance(transform, dict) or set(transform) != keys:
            raise ValueError('review_mapping needs scale_x, scale_y, offset_x, offset_y')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in transform.values()):
            raise ValueError('review_mapping values must be finite numbers')
        if transform['scale_x'] <= 0 or transform['scale_y'] <= 0:
            raise ValueError('review_mapping scales must be positive')
        return transform
    canvas = scene.get('canvas', {})
    w, h = canvas.get('width'), canvas.get('height')
    if not w or not h:
        raise ValueError('Canvas required for local object coverage')
    if abs(size[0] * h / w - size[1]) > 1.01:
        raise ValueError('Reference/canvas aspect ratios differ: declare review_mapping for crop/letterbox, do not guess')
    return {'scale_x': size[0] / w, 'scale_y': size[1] / h, 'offset_x': 0, 'offset_y': 0}


def validate_local_coverage(scene: dict, slide: dict, size: list[int], regions: list[dict]) -> dict:
    requirements = required_review(slide)
    by_id = {o['id']: o for o in walk_objects(slide.get('objects', []))}
    assigned = {oid for r in regions for oid in r['object_ids']}
    if assigned - set(by_id):
        raise ValueError(f'Local regions name unknown object IDs: {sorted(assigned - set(by_id))}')
    missing = set(requirements['local_objects']) - assigned
    if missing:
        raise ValueError(f'Missing mandatory local comparisons for objects: {sorted(missing)}; add regions with object_ids')
    if not assigned:
        return requirements
    m = review_mapping(scene, slide, size)
    for region in regions:
        l, t, r, b = region['bbox']
        for oid in region['object_ids']:
            box = logical_bounds(by_id[oid])
            a, c = box[0] * m['scale_x'] + m['offset_x'], box[2] * m['scale_x'] + m['offset_x']
            d, e = box[1] * m['scale_y'] + m['offset_y'], box[3] * m['scale_y'] + m['offset_y']
            # Visible intersection only; no claim that a group/glyph actually renders exactly here.
            a, d, c, e = max(0, a), max(0, d), min(size[0], c), min(size[1], e)
            if a > c or d > e or not (l <= a + 2 and t <= d + 2 and r >= c - 2 and b >= e - 2):
                raise ValueError(f'Local crop {region["id"]} does not cover declared bounds of {oid}')
    return requirements


@scoped
@measured("comparison_validation")
def validate_comparisons(comparison_path: Path, scene_path: Path, pptx: Path, render_path: Path) -> dict:
    """Follow every link down to actual files, including full AND local evidence."""
    scene, refs, manifest_hash = reference_snapshot(scene_path)
    _, rendered = validate_render(render_path, pptx, len(refs))
    expected = {'evidence_version': EVIDENCE_VERSION, 'status': 'passed',
                'pptx_sha256': sha256(pptx), 'scene_sha256': sha256(scene_path),
                'render_receipt_sha256': sha256(render_path),
                'reference_manifest_sha256': manifest_hash, 'references': refs}
    return validate_comparison_chain(comparison_path, scene, refs, rendered, expected)


def validate_comparison_chain(comparison_path, scene, refs, rendered, expected):
    """Shared file/region checks. Caller must validate its renderer and binding.
    The Office gate continues to use validate_comparisons above, never this helper.
    """
    comp = read_json(comparison_path)
    for key, value in expected.items():
        if key not in comp or comp[key] != value:
            raise ValueError(f'Comparison binding mismatch: {key}. Regenerate v1.1.1 evidence; do not edit hashes.')
    pages = indexed_rows(comp.get('slides'), len(refs), 'Comparison receipt')
    full_paths, local_paths, relation_paths = {}, {}, {}
    required_by_page = {}
    used_files = set()
    for ref, slide in zip(refs, scene['slides']):
        idx = ref['index']; page = pages[idx]
        for key, val in [('slide_id', slide['id']), ('reference_sha256', ref['sha256']),
                         ('render_sha256', rendered[idx]['sha256'])]:
            if page.get(key) != val:
                raise ValueError(f'Slide {idx} comparison mismatch: {key}')
        regions = normalize_regions(page.get('local_regions'), ref['size'])
        required = validate_local_coverage(scene, slide, ref['size'], regions)
        if page.get('required_review') != required:
            raise ValueError(f'Slide {idx}: required review list differs from scene')
        required_by_page[idx] = required
        cp = checked_file(comparison_path.parent, page.get('comparison_json'), page.get('comparison_json_sha256'))
        detail = read_json(cp)
        for key, val in [('evidence_version', EVIDENCE_VERSION), ('status', 'passed'),
                         ('reference_sha256', ref['sha256']), ('render_sha256', rendered[idx]['sha256']),
                         ('reference_size', ref['size']),
                         ('render_original_size', [rendered[idx]['width'], rendered[idx]['height']])]:
            if detail.get(key) != val:
                raise ValueError(f'Slide {idx} page comparison mismatch: {key}')
        resized = ref['size'] != [rendered[idx]['width'], rendered[idx]['height']]
        if type(detail.get('resized_render')) is not bool or detail['resized_render'] != resized or page.get('resized_render') != resized:
            raise ValueError(f'Slide {idx}: inconsistent resize declaration')
        expected_regions = [{'id': 'full', 'bbox': [0, 0, *ref['size']], 'object_ids': []}] + regions
        rows = detail.get('regions')
        if not isinstance(rows, list) or len(rows) != len(expected_regions):
            raise ValueError(f'Slide {idx}: missing/extra full or local evidence')
        for wanted, row in zip(expected_regions, rows):
            name = wanted['id']; box = wanted['bbox']
            if row.get('region') != name or row.get('bbox') != box or row.get('object_ids') != wanted['object_ids']:
                raise ValueError(f'Slide {idx}: region identity/coverage mismatch: {name}')
            scale = row.get('display_scale')
            if type(scale) is not int or not 1 <= scale <= 8 or name == 'full' and scale != 1:
                raise ValueError(f'Invalid display scale: {name}')
            size = [box[2] - box[0], box[3] - box[1]]
            if row.get('pixel_size') != size:
                raise ValueError(f'Region dimensions mismatch: {name}')
            w, h = size[0] * scale, size[1] * scale
            for key in IMAGE_KINDS:
                actual_size = []
                image = checked_file(cp.parent, row.get(key), row.get(key + '_sha256'),
                                     image=True, dimensions=actual_size)
                file_key = image.as_posix().casefold()
                if file_key in used_files:
                    raise ValueError('Comparison evidence reuses the same file for multiple outputs')
                used_files.add(file_key)
                required_size = [w * 2 + max(10, round(w * .012)), h + max(34, round(h * .045))] if key == 'side_by_side' else [w, h]
                if actual_size != required_size or row.get(key + '_size') != actual_size:
                    raise ValueError(f'Invalid {key} image dimensions for {name}')
                if key == 'side_by_side':
                    if name == 'full':
                        linked = checked_file(comparison_path.parent, page.get('full_side_by_side'), page.get('full_side_by_side_sha256'), image=True)
                        if linked != image or page['full_side_by_side_sha256'] != row['side_by_side_sha256']:
                            raise ValueError('Full image link differs from per-page comparison')
                        full_paths[idx] = image
                    else:
                        local_paths[(idx, name)] = {'file': image, 'object_ids': wanted['object_ids']}
                        for oid in wanted['object_ids']:
                            relation_paths.setdefault((idx, oid), set()).add(image)
    return {'receipt': comp, 'full_paths': full_paths, 'local_paths': local_paths,
            'relation_paths': relation_paths, 'required_by_page': required_by_page}
