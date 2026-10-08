"""Versioned source obligations. Structural checks do not perform visual inference."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import jsonschema
if __package__:
    from .common import resolve_asset, sha256, walk_objects
else:
    from common import resolve_asset, sha256, walk_objects


def record(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1}
ID = {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$'}
HASH = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
BINDING = record({'unit_id': ID, 'object_ids': {'type': 'array', 'items': TEXT,
                                              'minItems': 1, 'uniqueItems': True}})
BINDINGS = {'type': 'array', 'items': BINDING, 'minItems': 1}
UNIT = record({
    'id': ID, 'region_id': ID, 'owner_id': {'type': ['string', 'null']},
    'semantic_role': {'enum': ['page_content', 'reference_artifact', 'decoration', 'unknown']},
    'input_form': {'enum': ['native', 'raster', 'mixed', 'unknown']},
    'requirement': TEXT, 'evidence': TEXT, 'counterevidence': TEXT,
    'required_edit': {'enum': ['preserve', 'text', 'geometry', 'data', 'group', 'image_replace', 'unresolved']},
    'source': record({'asset': TEXT, 'sha256': HASH,
                      'crop': {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 4, 'maxItems': 4}},
                     ['asset', 'sha256']),
    'native_sha256': HASH,
}, ['id', 'region_id', 'owner_id', 'semantic_role', 'input_form', 'requirement',
    'evidence', 'counterevidence', 'required_edit'])
SCOPE = record({'version': {'const': 1}, 'revision': {'type': 'integer', 'minimum': 1},
                'task_requirement': TEXT, 'units': {'type': 'array', 'items': UNIT, 'minItems': 1}})
COMPILED_SCOPE = copy.deepcopy(SCOPE)
COMPILED_SCOPE['properties']['bindings'] = BINDINGS
COMPILED_SCOPE['required'].append('bindings')
REVIEW = record({'revision': {'type': 'integer', 'minimum': 1},
                 'units': {'type': 'array', 'minItems': 1, 'items': record({
                     'unit_id': ID, 'status': {'enum': ['passed', 'needs_changes', 'blocked']},
                     'note': TEXT})}})


def checked(value, schema):
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ValueError('element_scope: ' + errors[0].message)


def validate_plan(scope, region_ids=None, project=None, compiled=False):
    checked(scope, COMPILED_SCOPE if compiled else SCOPE)
    units = {u['id']: u for u in scope['units']}
    if len(units) != len(scope['units']):
        raise ValueError('element_scope: duplicate unit IDs')
    if region_ids is not None and {u['region_id'] for u in units.values()} != set(region_ids):
        raise ValueError('element_scope: every region needs source units; unknown regions forbidden')
    for unit in units.values():
        chain = {unit['id']}
        owner = unit['owner_id']
        while owner is not None:
            if owner not in units or owner in chain:
                raise ValueError('element_scope: missing owner or ownership cycle')
            chain.add(owner)
            if units[owner]['required_edit'] == 'preserve' and unit['required_edit'] != 'preserve':
                raise ValueError('element_scope: child edit conflicts with preserved owner; split the scope')
            owner = units[owner]['owner_id']
        source = unit.get('source')
        if source and project is not None:
            path = resolve_asset(Path(project), source['asset'])
            if sha256(path) != source['sha256']:
                raise ValueError('element_scope: source asset changed for ' + unit['id'])
            from PIL import Image
            with Image.open(path) as im:
                crop = source.get('crop', [0, 0, *im.size])
                if not (0 <= crop[0] and 0 <= crop[1] and crop[2] > 0 and crop[3] > 0
                        and crop[0] + crop[2] <= im.width and crop[1] + crop[3] <= im.height):
                    raise ValueError('element_scope: source crop outside image')
        if unit['required_edit'] == 'preserve':
            if unit['input_form'] == 'raster' and (not source or 'native_sha256' in unit):
                raise ValueError('element_scope: raster preservation needs a bound source')
            if unit['input_form'] == 'native' and ('native_sha256' not in unit or source):
                raise ValueError('element_scope: native preservation needs a native snapshot digest')
            if unit['input_form'] not in {'raster', 'native'}:
                raise ValueError('element_scope: split mixed preservation into native/raster source units')
    return scope


def native_digest(objects):
    """Logical scene snapshot; IDs/evidence may change during regional import."""
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in {'id', 'evidence', 'notes'}}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    return hashlib.sha256(json.dumps(scrub(objects), sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_outputs(scope, objects, project=None, *, region_id=None, bindings=None,
                     check_native=True):
    """Bind every output leaf once, including unresolved source obligations."""
    units = [u for u in scope['units'] if region_id is None or u['region_id'] == region_id]
    rows = scope.get('bindings') if bindings is None else bindings
    checked(rows, BINDINGS)
    expected = {u['id'] for u in units}
    if len(rows) != len(expected) or {r['unit_id'] for r in rows} != expected:
        raise ValueError('element_scope: bindings must cover every source unit exactly once')
    inventory = {o['id']: o for o in walk_objects(objects)}
    assigned = {}
    preserved_images = set()
    by_unit = {r['unit_id']: r['object_ids'] for r in rows}
    all_units = {u['id']: u for u in scope['units']}
    def ancestor(parent, child):
        seen = set()
        while child in all_units and child not in seen:
            seen.add(child)
            child = all_units[child]['owner_id']
            if child == parent: return True
        return False
    for unit in units:
        ids = by_unit[unit['id']]
        if any(oid not in inventory for oid in ids):
            raise ValueError('element_scope: binding names a missing output')
        roots = [inventory[oid] for oid in ids]
        leaves = [o for o in walk_objects(roots) if o['kind'] != 'group']
        leaf_ids = [o['id'] for o in leaves]
        if not leaves or len(leaf_ids) != len(set(leaf_ids)):
            raise ValueError('element_scope: overlapping ownership in output bindings')
        for oid in leaf_ids:
            for other in assigned.get(oid, []):
                if not (ancestor(other, unit['id']) or ancestor(unit['id'], other)):
                    raise ValueError('element_scope: overlapping ownership in output bindings')
                # Only a genuine group may serve as an ancestor binding. Two
                # semantic units cannot both claim the same standalone text.
                parent = other if ancestor(other, unit['id']) else unit['id']
                if not any(inventory[x]['kind'] == 'group' and oid in {o['id'] for o in walk_objects([inventory[x]])}
                           for x in by_unit[parent]):
                    raise ValueError('element_scope: overlapping ancestor must bind a containing group')
            assigned.setdefault(oid, []).append(unit['id'])
        need = unit['required_edit']
        kinds = {o['kind'] for o in leaves}
        supported = {'text': {'text', 'table', 'chart'}, 'geometry': {'shape', 'path', 'line', 'connector'},
                     'data': {'chart', 'table'}, 'image_replace': {'image'}}
        if need in supported and not kinds.intersection(supported[need]):
            raise ValueError('element_scope: required edit capability missing for ' + unit['id'])
        if need in {'text', 'geometry', 'data'} and 'image' in kinds:
            raise ValueError('element_scope: editable source unit cannot hide content in an image; split independent artwork into its own unit')
        if need == 'group' and not any(o['kind'] == 'group' for o in roots):
            raise ValueError('element_scope: editable group required')
        if need == 'preserve' and unit['input_form'] == 'native' and check_native:
            if 'image' in kinds or native_digest(roots) != unit['native_sha256']:
                raise ValueError('element_scope: preserved native source changed or rasterized')
        if need == 'preserve' and unit['input_form'] == 'raster':
            if len(leaves) != 1 or kinds != {'image'}:
                raise ValueError('element_scope: preserved raster must remain one source image')
            image = leaves[0]
            source = unit['source']
            if image.get('source_kind') not in {'user', 'crop'}:
                raise ValueError('element_scope: preserved source cannot be regenerated or substituted')
            if image.get('source_crop') != source.get('crop'):
                raise ValueError('element_scope: preserved source crop changed')
            if image.get('mask') or image.get('fit') != 'stretch':
                raise ValueError('element_scope: preserved source requires unmasked stretch mapping')
            if project is not None and sha256(resolve_asset(Path(project), image['asset'])) != source['sha256']:
                raise ValueError('element_scope: preserved image bytes differ from source')
            preserved_images.add(image['id'])
    if set(assigned) != {o['id'] for o in inventory.values() if o['kind'] != 'group'}:
        raise ValueError('element_scope: output has unassigned source ownership')
    return preserved_images


def compiled_scope(page):
    if page.get('imported_slide') is not None:
        return page['imported_slide'].get('element_scope')
    scope = (page.get('plan') or {}).get('element_scope')
    if scope is None:
        return None
    result = copy.deepcopy(scope)
    result['bindings'] = []
    for region in page['plan']['regions']:
        prefix = page['id'] + '.' + region['id'] + '.'
        fragment = page['fragments'].get(region['id'], {})
        for row in fragment.get('raw', {}).get('scope_bindings', []):
            result['bindings'].append({'unit_id': row['unit_id'],
                                       'object_ids': [prefix + oid for oid in row['object_ids']]})
    return result


def validate_review(scope, result, objects, project):
    if scope is None:
        if 'scope_review' in result:
            raise ValueError('element_scope: review supplied without an active scope')
        return
    validate_plan(scope, project=project, compiled=True)
    validate_outputs(scope, objects, project)
    review = result.get('scope_review')
    checked(review, REVIEW)
    ids = {u['id'] for u in scope['units']}
    if review['revision'] != scope['revision'] or len(review['units']) != len(ids) or {u['unit_id'] for u in review['units']} != ids:
        raise ValueError('element_scope: review must cover the current revision and every unit')
    if result['status'] == 'passed':
        if any(u['required_edit'] == 'unresolved' for u in scope['units']) or any(u['status'] != 'passed' for u in review['units']):
            raise ValueError('element_scope: unresolved obligations cannot pass source review')
        text_ids = {o['id'] for o in walk_objects(objects) if o['kind'] == 'text'}
        checked_ids = {r['object_id'] for r in result.get('text_checks', [])}
        if not text_ids <= checked_ids:
            raise ValueError('element_scope: source transcription checks required for every native text object')
