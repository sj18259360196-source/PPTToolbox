"""Requirement-bound material qualification. Pixel diagnostics are not visual approval.

New reference workflows require this contract for declared illustrations. Historical
scopes opt in through an ordinary page revision; no saved decisions are migrated.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
from PIL import Image

if __package__:
    from .common import resolve_asset, sha256, walk_objects
else:
    from common import resolve_asset, sha256, walk_objects

POLICY = 'material-quality/1'
MATERIAL_TYPES = {'simple_icon', 'simple_illustration', 'complex_illustration', 'existing_asset',
                  'identity_asset', 'decorative_title', 'photograph'}
TEXT = {'type': 'string', 'minLength': 1}
HASH = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
STATUS = {'enum': ['passed', 'needs_changes', 'blocked']}


def record(fields, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': fields,
            'required': list(fields) if required is None else required}


SOURCE = record({'id': TEXT, 'file': TEXT, 'sha256': HASH, 'excerpt': TEXT})
CONTRACT = record({'version': {'const': 1},
                   'requirement_sources': {'type': 'array', 'minItems': 1, 'items': SOURCE}})
REQUIREMENT = record({
    'requirement_ids': {'type': 'array', 'items': TEXT, 'minItems': 1, 'uniqueItems': True},
    'source_origin': {'enum': ['page_reference', 'independent_asset', 'extracted_asset', 'native_source']},
    'independent': {'type': 'boolean'},
    'background': {'enum': ['transparent', 'source', 'opaque']},
    'route_constraint': {'enum': ['auto', 'native', 'preserve_source', 'reference_generate']},
    'preservation_basis': {'enum': ['qualified_asset', 'user_required', 'identity', 'photograph']},
    'source_qualification': record({'complete_subject': {'type': 'boolean'},
                                   'page_artifacts': {'enum': ['none', 'present', 'unknown']},
                                   'note': TEXT}),
}, ['requirement_ids', 'source_origin', 'independent', 'background', 'route_constraint'])
REQUIREMENT['properties']['fidelity'] = {'enum': ['reference', 'exact']}
REQUIREMENT['properties']['display'] = record({
    'crop': {'type': 'array', 'items': {'type': 'integer', 'minimum': 0}, 'minItems': 4, 'maxItems': 4},
    'mask': {'type': 'object', 'additionalProperties': False, 'required': ['geometry'], 'properties': {'geometry': {'enum': ['ellipse', 'round_rect', 'custom']}, 'commands': {'type': 'array', 'minItems': 2, 'items': {'type': 'array', 'minItems': 1, 'maxItems': 7, 'prefixItems': [{'enum': ['M', 'L', 'C', 'Z']}], 'items': {'type': 'number'}}}}},
    'fit': {'enum': ['contain', 'cover', 'stretch']},
}, ['fit'])

EVIDENCE = record({'file': TEXT, 'sha256': HASH,
                   'role': {'enum': ['light', 'dark', 'target', 'comparison', 'office', 'edit']}})
REVIEW = record({
    'unit_id': TEXT, 'output_sha256': HASH, 'status': STATUS, 'note': TEXT,
    'checks': record({name: {'enum': ['passed', 'needs_changes', 'blocked', 'not_applicable']}
                      for name in ['independence', 'edges', 'fidelity', 'resolution']}),
    'defects': {'type': 'array', 'items': record({
        'kind': TEXT, 'status': {'enum': ['open', 'resolved']}, 'note': TEXT})},
    'evidence': {'type': 'array', 'items': EVIDENCE, 'minItems': 1},
}, ['unit_id', 'status', 'note', 'checks', 'defects', 'evidence'])
REVIEWS = {'type': 'array', 'items': REVIEW}


def validate_schema(value, schema):
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError('material_quality: '+errors[0].message)


def material_units(scope):
    return [u for u in (scope or {}).get('units', [])
            if u.get('content_type') in MATERIAL_TYPES or 'material_requirement' in u
            or (u.get('required_edit') == 'preserve' and u.get('input_form') == 'raster')]


def sources(scope):
    return (scope or {}).get('material_contract', {}).get('requirement_sources', [])


def validate_plan(scope, project=None, *, required=False, previous=None, reference_hash=None):
    units = material_units(scope)
    contract = (scope or {}).get('material_contract')
    if contract is None:
        if (required and units) or sources(previous) or any('material_requirement' in u for u in units):
            raise ValueError('material_quality: illustrations need material_contract with original requirement sources')
        return
    validate_schema(contract, CONTRACT)
    refs = {s['id']: s for s in sources(scope)}
    if len(refs) != len(sources(scope)):
        raise ValueError('material_quality: requirement source IDs must be unique')
    for old in sources(previous):
        if refs.get(old['id']) != old:
            raise ValueError('material_quality: retain original requirement sources; append new user requirements on revision')
    for source in refs.values():
        if not source['excerpt'].strip():
            raise ValueError('material_quality: original requirement excerpt cannot be blank')
        if project is not None:
            path = resolve_asset(Path(project), source['file'])
            if path.stat().st_size > 4_000_000 or sha256(path) != source['sha256']:
                raise ValueError('material_quality: original requirement file changed or exceeds 4 MB')
            if source['excerpt'] not in path.read_text(encoding='utf-8-sig'):
                raise ValueError('material_quality: requirement excerpt must occur verbatim in the frozen source')
    for unit in units:
        req = unit.get('material_requirement')
        validate_schema(req, REQUIREMENT)
        if not set(req['requirement_ids']) <= refs.keys():
            raise ValueError('material_quality: material requirement must cite original requirement IDs')
        route = unit.get('material_route')
        if route not in {'native', 'preserve_source', 'reference_generate'}:
            raise ValueError('material_quality: material needs an explicit selected route')
        if req['route_constraint'] != 'auto' and route != req['route_constraint']:
            raise ValueError('material_quality: selected route conflicts with the cited user requirement')
        if req.get('fidelity') == 'exact' and route != 'preserve_source':
            raise ValueError('material_quality: exact source fidelity requires source preservation')
        if unit.get('content_type') == 'identity_asset' and route == 'reference_generate':
            raise ValueError('material_quality: accurate identity material cannot be regenerated')
        if 'display' in req:
            if unit.get('content_type') != 'photograph' or route != 'preserve_source' or not unit.get('source'):
                raise ValueError('material_quality: display mapping requires a source-bound preserved photograph')
            crop = req['display'].get('crop')
            if crop and (crop[2] <= 0 or crop[3] <= 0):
                raise ValueError('material_quality: display crop needs positive dimensions')
            mask = req['display'].get('mask', {})
            if mask.get('geometry') == 'custom' and not mask.get('commands'):
                raise ValueError('material_quality: custom display mask requires commands')
            if project is not None and crop:
                image_diagnostics(resolve_asset(Path(project), unit['source']['asset']), crop)
        if route != 'preserve_source':
            continue
        basis = req.get('preservation_basis')
        if basis is None:
            raise ValueError('material_quality: source preservation needs a qualification basis')
        if basis == 'photograph' and unit.get('content_type') != 'photograph':
            raise ValueError('material_quality: photograph exception requires photograph classification')
        if basis == 'identity' and unit.get('content_type') != 'identity_asset':
            raise ValueError('material_quality: identity exception requires identity_asset classification')
        if basis == 'user_required' and req['route_constraint'] != 'preserve_source':
            raise ValueError('material_quality: user-required preservation must cite an explicit preserve_source constraint')
        if basis == 'qualified_asset' or req['independent'] or req['background'] == 'transparent':
            qualified = req.get('source_qualification')
            if not qualified or not qualified['complete_subject'] or qualified['page_artifacts'] != 'none':
                raise ValueError('material_quality: independent source needs a complete subject with no page artifacts; revise route')
        source = unit.get('source', {})
        if source and reference_hash == source.get('sha256') and req['source_origin'] != 'page_reference':
            raise ValueError('material_quality: page-reference bytes cannot be declared an independent asset')
        if project is not None and source and req['background'] == 'transparent':
            diagnostic = image_diagnostics(resolve_asset(Path(project), source['asset']), source.get('crop'))
            if not diagnostic['has_transparency']:
                raise ValueError('material_quality: requested transparency is absent in the actual preserved crop; revise route')


def image_diagnostics(path, crop=None):
    with Image.open(path) as source:
        image = source.convert('RGBA')
        if crop is not None:
            x, y, w, h = crop
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > image.width or y+h > image.height:
                raise ValueError('material_quality: crop outside the material image')
            image = image.crop((x, y, x+w, y+h))
        alpha = image.getchannel('A')
        low, high = alpha.getextrema()
        return {'size': list(image.size), 'alpha_extrema': [low, high],
                'subject_bbox': alpha.getbbox(), 'has_transparency': low < 255 and high > 0,
                'scope': 'pixel_diagnostics_only; inspect edges and fidelity separately'}


def roots_for(scope, objects, unit_id, bindings=None):
    inventory = {o['id']: o for o in walk_objects(objects)}
    rows = scope.get('bindings', []) if bindings is None else bindings
    row = next((r for r in rows if r['unit_id'] == unit_id), None)
    if not row or any(oid not in inventory for oid in row['object_ids']):
        raise ValueError('material_quality: missing current material binding '+unit_id)
    return [inventory[oid] for oid in row['object_ids']]


def fingerprint(roots, project):
    value = copy.deepcopy(roots)
    for obj in walk_objects(value):
        if obj.get('kind') == 'image':
            obj['asset'] = sha256(resolve_asset(Path(project), obj['asset']))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def inventory(scope, objects, project):
    if not (scope or {}).get('material_contract'):
        return []
    rows = []
    for unit in material_units(scope):
        roots = roots_for(scope, objects, unit['id'])
        images = [o for o in walk_objects(roots) if o['kind'] == 'image']
        rows.append({'unit_id': unit['id'], 'object_ids': [o['id'] for o in roots],
                     'output_sha256': fingerprint(roots, project),
                     'requirement': unit['material_requirement'],
                     'pixel_diagnostics': [{'object_id': o['id'], **image_diagnostics(
                         resolve_asset(Path(project), o['asset']), o.get('source_crop'))} for o in images]})
    return rows


def review_template(rows):
    return [{'unit_id': r['unit_id'], 'output_sha256': r['output_sha256'],
             'status': 'blocked', 'note': '',
             'checks': {k: 'blocked' for k in ('independence', 'edges', 'fidelity', 'resolution')},
             'defects': [], 'evidence': []} for r in rows]


def validate_reviews(scope, objects, result, project, *, output_root=None,
                     region_id=None, bindings=None, stage='source'):
    if not (scope or {}).get('material_contract'):
        if result.get('material_reviews'):
            raise ValueError('material_quality: reviews require an active material contract')
        return []
    units = [u for u in material_units(scope) if region_id is None or u['region_id'] == region_id]
    covered = {o['id'] for u in units for o in walk_objects(roots_for(scope, objects, u['id'], bindings))}
    unbound = [o['id'] for o in walk_objects(objects) if o['kind'] == 'image'
               and (o.get('asset_role') in {'icon', 'logo', 'decoration'} or
                    o.get('raster_content') in {'generated_illustration', 'reference_artifact'})
               and o['id'] not in covered]
    if unbound:
        raise ValueError('material_quality: illustration output lacks material qualification '+', '.join(unbound))
    rows = result.get('material_reviews', [])
    validate_schema(rows, REVIEWS)
    by_id = {r['unit_id']: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {u['id'] for u in units}:
        raise ValueError('material_quality: review every current material exactly once')
    passing = result.get('status') == 'passed' or stage == 'region' or (
        bool(result.get('checks')) and all(c['status'] == 'passed' for c in result['checks'].values()))
    used = []
    for unit in units:
        row = by_id[unit['id']]
        roots = roots_for(scope, objects, unit['id'], bindings)
        req = unit['material_requirement']
        output_root = output_root or project
        if stage != 'region' or 'output_sha256' in row:
            if row.get('output_sha256') != fingerprint(roots, output_root):
                raise ValueError('material_quality: review must bind the current output bytes and geometry')
        images = [o for o in walk_objects(roots) if o['kind'] == 'image']
        if req['independent'] and len(roots) != 1:
            raise ValueError('material_quality: independent illustration needs one image or a complete group')
        required = {'edges', 'fidelity'}
        if req['independent']: required.add('independence')
        if images: required.add('resolution')
        if row['status'] == 'passed':
            if not row['note'].strip() or any(row['checks'][k] != 'passed' for k in required):
                raise ValueError('material_quality: passing material needs separate quality and fidelity observations')
            if any(v in {'blocked', 'needs_changes'} for v in row['checks'].values()) or any(
                    d['status'] == 'open' for d in row['defects']):
                raise ValueError('material_quality: unresolved material defect cannot be passed')
            # An opaque label may legitimately be one child of a transparent
            # native composition. Only a standalone bitmap has a measurable
            # whole-material Alpha contract here; groups need visual evidence.
            if req['background'] == 'transparent' and len(roots) == 1 and roots[0]['kind'] == 'image':
                for obj in images:
                    if not image_diagnostics(resolve_asset(Path(output_root), obj['asset']),
                                             obj.get('source_crop'))['has_transparency']:
                        raise ValueError('material_quality: actual image lacks required transparency')
            roles = {e['role'] for e in row['evidence']}
            needed = {'comparison'}
            if req['independent'] or req['background'] == 'transparent':
                needed |= {'light', 'dark', 'target'}
            if stage == 'office': needed.add('office')
            if not needed <= roles:
                raise ValueError('material_quality: attach comparison and applicable background/Office views')
        if passing and row['status'] != 'passed':
            raise ValueError('material_quality: failed material review cannot have an overall passed result')
        for evidence in row['evidence']:
            path = resolve_asset(Path(project), evidence['file'])
            if sha256(path) != evidence['sha256']:
                raise ValueError('material_quality: review evidence changed')
            with Image.open(path) as image:
                image.verify()
            used.append(evidence)
    return used


def edit_requirements(scene):
    """Complete independent-material obligations shared by preparation and gates."""
    rows = []
    for index, slide in enumerate(scene['slides'], 1):
        scope = slide.get('element_scope') or {}
        if not scope.get('material_contract'):
            continue
        for unit in material_units(scope):
            if not unit['material_requirement']['independent']:
                continue
            roots = roots_for(scope, slide['objects'], unit['id'])
            pictures = [o['id'] for o in walk_objects(roots) if o['kind'] == 'image']
            actions = ['material_move', 'material_resize', 'material_backgrounds']
            if pictures:
                actions.append('material_replace')
            rows.append({'slide': index, 'slide_id': slide['id'], 'unit_id': unit['id'],
                         'object_ids': [o['id'] for o in roots], 'picture_ids': pictures,
                         'requirement_ids': list(unit['material_requirement'].get('requirement_ids', [])),
                         'summary_actions': actions,
                         'picture_actions': ['image_move', 'image_resize', 'image_replace'] if pictures else []})
    return rows


def validate_edit_coverage(scene, result):
    """Require per-material observations; actual PPTX picture edits are checked separately."""
    if result.get('status') != 'passed':
        return
    tests = result.get('edit_tests', [])
    for requirement in edit_requirements(scene):
        ids = set(requirement['object_ids']); operations = set(requirement['summary_actions'])
        current = [t for t in tests if t['slide_id'] == requirement['slide_id'] and t['object_id'] in ids]
        if not operations <= {t['operation'] for t in current if t['status'] == 'passed' and t['scope'] == 'required'}:
            raise ValueError('material_quality: independent material needs move, resize, backgrounds and applicable replacement tests')
        if any(t['status'] != 'passed' for t in current if t['operation'] in operations):
            raise ValueError('material_quality: unresolved material edit failure cannot pass')


def validate_picture_coverage(scene, report):
    for requirement in edit_requirements(scene):
        names = set(requirement['picture_ids'])
        for operation in requirement['picture_actions']:
            if not any(r['slide'] == requirement['slide'] and r['name'] in names
                       for r in report['verified_actions'][operation]):
                raise ValueError('material_quality: attached PPTX lacks '+operation+' for '+requirement['unit_id'])
