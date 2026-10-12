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
if __package__:
    from .component_strategy import COMPONENT_FIELDS
else:
    from component_strategy import COMPONENT_FIELDS
UNIT['properties'].update(copy.deepcopy(COMPONENT_FIELDS))
if __package__:
    from .material_quality import CONTRACT, REQUIREMENT
else:
    from material_quality import CONTRACT, REQUIREMENT
UNIT['properties']['material_requirement'] = copy.deepcopy(REQUIREMENT)
SCOPE = record({'version': {'const': 1}, 'revision': {'type': 'integer', 'minimum': 1},
                'task_requirement': TEXT, 'units': {'type': 'array', 'items': UNIT, 'minItems': 1}})
SCOPE['properties']['material_contract'] = copy.deepcopy(CONTRACT)
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
        from validation_checks import Checks
        checks=Checks()
        for error in errors:
            checks.add('element_scope: '+error.message,
                       ('/'+('/'.join(str(x).replace('~','~0').replace('/','~1') for x in error.absolute_path))) if error.absolute_path else '',
                       'element_schema')
        checks.finish()


def validate_plan(scope, region_ids=None, project=None, compiled=False):
    checked(scope, COMPILED_SCOPE if compiled else SCOPE)
    if __package__:
        from .material_quality import validate_plan as validate_material_plan
    else:
        from material_quality import validate_plan as validate_material_plan
    validate_material_plan(scope, project)
    units = {u['id']: u for u in scope['units']}
    if len(units) != len(scope['units']):
        raise ValueError('element_scope: duplicate unit IDs')
    if region_ids is not None and {u['region_id'] for u in units.values()} != set(region_ids):
        raise ValueError('element_scope: every region needs source units; unknown regions forbidden')
    def check_unit(unit):
        if __package__:
            from .component_strategy import validate_component
        else:
            from component_strategy import validate_component
        validate_component(unit, units)
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
    from validation_checks import Checks
    checks = Checks()
    for index, unit in enumerate(scope['units']):
        checks.run(lambda unit=unit: check_unit(unit), '/units/'+str(index),
                   'component_scope', unit['id'])
    checks.finish()
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
    if __package__:
        from .component_strategy import INDEPENDENT_MATERIAL_TYPES, is_embedded_child
    else:
        from component_strategy import INDEPENDENT_MATERIAL_TYPES, is_embedded_child
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
    def check_output(unit):
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
                child = unit['id'] if parent == other else other
                embedded = (is_embedded_child(all_units[child])
                            and inventory[oid]['kind'] == 'image'
                            and by_unit[parent] == by_unit[child] == [oid]
                            and all_units[parent]['required_edit'] == all_units[child]['required_edit'])
                if not embedded and not any(inventory[x]['kind'] == 'group' and oid in {o['id'] for o in walk_objects([inventory[x]])}
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
        if (need == 'preserve' or unit.get('material_route') == 'preserve_source') and unit.get('input_form') == 'raster':
            if len(leaves) != 1 or kinds != {'image'}:
                raise ValueError('element_scope: preserved raster must remain one source image')
            image = leaves[0]
            source = unit['source']
            if image.get('source_kind') not in {'user', 'crop'}:
                raise ValueError('element_scope: preserved source cannot be regenerated or substituted')
            display = unit.get('material_requirement', {}).get('display')
            if display is not None and unit.get('content_type') != 'photograph':
                raise ValueError('element_scope: only declared photographs support display mapping')
            expected_crop = display.get('crop', source.get('crop')) if display else source.get('crop')
            if image.get('source_crop') != expected_crop:
                raise ValueError('element_scope: preserved source crop changed')
            if display is not None:
                if image.get('mask') != display.get('mask') or image.get('fit') != display['fit']:
                    raise ValueError('element_scope: preserved photograph differs from declared display mapping')
            elif image.get('mask') or image.get('fit') != 'stretch':
                raise ValueError('element_scope: preserved source requires unmasked stretch mapping')
            if project is not None and sha256(resolve_asset(Path(project), image['asset'])) != source['sha256']:
                raise ValueError('element_scope: preserved image bytes differ from source')
            preserved_images.add(image['id'])
    from validation_checks import Checks
    checks = Checks()
    for index, unit in enumerate(units):
        binding_index = next(i for i, row in enumerate(rows) if row['unit_id'] == unit['id'])
        checks.run(lambda unit=unit: check_output(unit), '/'+str(binding_index),
                   'output_binding', unit['id'])
    checks.finish(['ownership_coverage', 'generated_output_consistency'])
    if set(assigned) != {o['id'] for o in inventory.values() if o['kind'] != 'group'}:
        raise ValueError('element_scope: output has unassigned source ownership')
    # Source obligations remain authoritative after generation. An output cannot
    # remove its declared text by substituting a weaker legacy decision.
    component_fields = {'content_type', 'material_route', 'text_ownership', 'embedded_text'}
    def owner_depth(unit):
        depth = 0
        owner = unit['owner_id']
        while owner in all_units:
            depth += 1
            owner = all_units[owner]['owner_id']
        return depth
    def check_image(oid, unit_ids):
        image = inventory[oid]
        if image['kind'] != 'image':
            return
        governing_ids = set(unit_ids)
        for uid in unit_ids:
            source_unit = all_units[uid]
            while is_embedded_child(source_unit) and source_unit['owner_id'] in all_units:
                governing_ids.add(source_unit['owner_id'])
                source_unit = all_units[source_unit['owner_id']]
        # A separately declared material inside a structural group owns its
        # image route. Container editing remains checked above on the group.
        independent = {uid for uid in governing_ids
                       if all_units[uid].get('content_type') in INDEPENDENT_MATERIAL_TYPES}
        governing_ids = {uid for uid in governing_ids
                         if not any(uid != child and ancestor(uid, child) for child in independent)}
        for uid in governing_ids:
            route = all_units[uid].get('material_route')
            if route == 'native':
                raise ValueError('element_scope: image output conflicts with selected component route')
            if route == 'reference_generate' and image.get('source_kind') != 'generated':
                raise ValueError('element_scope: reference-generated component requires generated image source')
        if image.get('source_kind') != 'generated':
            return
        declared = sorted((all_units[uid] for uid in governing_ids
                           if component_fields.intersection(all_units[uid])), key=owner_depth)
        if not declared:
            return  # Legacy scopes have no new component declarations.
        decision = image.get('generation_decision') or {}
        allowed_owners = governing_ids | {all_units[uid]['owner_id'] for uid in governing_ids}
        expected_text = []
        text_declared = False
        material_ownership = next((u['text_ownership'] for u in declared
                                  if u.get('text_ownership') and not is_embedded_child(u)), None)
        for unit in declared:
            if unit.get('material_route') in {'native', 'preserve_source'}:
                raise ValueError('element_scope: generated output conflicts with selected component route')
            requirement = unit.get('material_requirement', {})
            if requirement.get('fidelity') == 'exact' or requirement.get('route_constraint') in {'native', 'preserve_source'}:
                raise ValueError('element_scope: generated output conflicts with exact source fidelity or explicit material constraint')
            if unit.get('content_type') == 'simple_icon' and requirement.get('route_constraint') != 'reference_generate':
                raise ValueError('element_scope: simple icons require native output unless an explicit exception is cited')
            for key in ('content_type', 'required_edit', 'text_ownership'):
                if key not in unit:
                    continue
                expected_value = unit[key]
                if key == 'text_ownership' and is_embedded_child(unit):
                    expected_value = material_ownership or 'embedded'
                if decision.get(key) != expected_value:
                    raise ValueError('element_scope: generated output differs from component ' + key)
            if 'embedded_text' in unit:
                text_declared = True
                local_rows = [{'text': r['text'], 'legibility': r['legibility']}
                              for r in unit['embedded_text']]
                # Parent and child may repeat the same obligation. Preserve any
                # deliberate repeated labels within one unit's own declaration.
                for index, row in enumerate(local_rows):
                    if local_rows[:index+1].count(row) > expected_text.count(row):
                        expected_text.append(row)
        if text_declared:
            actual_text = [{'text': r['text'], 'legibility': r['legibility']}
                           for r in decision.get('embedded_text', [])]
            if actual_text != expected_text:
                raise ValueError('element_scope: generated output lost or changed component embedded text')
            if any(r.get('owner_unit_id') not in allowed_owners | {None}
                   for r in decision.get('embedded_text', [])):
                raise ValueError('element_scope: generated output text names an unrelated component owner')
    for oid, unit_ids in assigned.items():
        binding_index = next(i for i, row in enumerate(rows) if row['unit_id'] in unit_ids)
        checks.run(lambda oid=oid, ids=unit_ids: check_image(oid, ids), '/'+str(binding_index),
                   'generated_output_consistency', oid)
    checks.finish()
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
    from validation_checks import Checks
    checks = Checks()
    if scope is None:
        if 'scope_review' in result:
            raise ValueError('element_scope: review supplied without an active scope')
        return
    checks.run(lambda: validate_plan(scope, project=project, compiled=True),
               '/scope_review', 'current_scope')
    if not checks.errors:
        checks.run(lambda: validate_outputs(scope, objects, project),
                   '/scope_review', 'current_outputs')
    review = result.get('scope_review')
    before = len(checks.errors)
    checks.run(lambda: checked(review, REVIEW), '/scope_review', 'review_schema')
    if len(checks.errors) == before:
        ids = {u['id'] for u in scope['units']}
        if review['revision'] != scope['revision']:
            checks.add('element_scope: review must cover the current revision and every unit',
                       '/scope_review/revision', 'scope_revision')
        actual = [u['unit_id'] for u in review['units']]
        if len(actual) != len(ids) or set(actual) != ids:
            checks.add('element_scope: review must cover the current revision and every unit',
                       '/scope_review/units', 'scope_coverage')
        if result['status'] == 'passed' and (any(u['required_edit'] == 'unresolved' for u in scope['units'])
                                            or any(u['status'] != 'passed' for u in review['units'])):
            checks.add('element_scope: unresolved obligations cannot pass source review',
                       '/scope_review/units', 'unresolved_obligations')
    if result['status'] == 'passed':
        text_ids = {o['id'] for o in walk_objects(objects) if o['kind'] == 'text'}
        checked_ids = {r['object_id'] for r in result.get('text_checks', [])}
        for oid in sorted(text_ids - checked_ids):
            checks.add('element_scope: source transcription checks required for every native text object',
                       '/text_checks', 'source_transcription_required', oid)
    checks.finish()
