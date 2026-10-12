"""Component method recommendations from explicit observations, not image inference."""
from __future__ import annotations

if __package__:
    from .material_routes import CONTENT_TYPES, TEXT_OWNERSHIPS, EMBEDDED_TEXT_SCHEMA
else:
    from material_routes import CONTENT_TYPES, TEXT_OWNERSHIPS, EMBEDDED_TEXT_SCHEMA

POLICY = 'layered-material/2'
INDEPENDENT_MATERIAL_TYPES = {'photograph', 'simple_icon', 'simple_illustration', 'complex_illustration',
                              'decorative_title', 'geometric_graphic', 'existing_asset',
                              'identity_asset', 'background'}


def is_embedded_child(unit):
    return (unit.get('text_ownership') == 'embedded' and unit.get('owner_id') is not None
            and unit.get('content_type') not in INDEPENDENT_MATERIAL_TYPES)


COMPONENT_FIELDS = {
    'content_type': {'enum': CONTENT_TYPES},
    'material_route': {'enum': ['native', 'preserve_source', 'reference_generate']},
    'text_ownership': {'enum': TEXT_OWNERSHIPS},
    'embedded_text': EMBEDDED_TEXT_SCHEMA,
    'layer': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
    'component_bbox': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
}


def validate_component(unit, units):
    from validation_checks import Checks
    checks=Checks()
    def fail(message,field):checks.add(message,field,'component_contract',unit['id'])
    kind = unit.get('content_type')
    need = unit['required_edit']
    ownership = unit.get('text_ownership')
    route = unit.get('material_route')
    if kind in {'page_text', 'standard_title'} and need not in {'text', 'preserve', 'unresolved'}:
        fail('element_scope: standalone page text requires text editing or explicit preservation','/required_edit')
    if ownership == 'page' and need not in {'text', 'preserve', 'unresolved'}:
        fail('element_scope: page text cannot be hidden in an image','/text_ownership')
    if ownership == 'asset_title' and kind != 'decorative_title':
        fail('element_scope: asset_title ownership requires a decorative title','/content_type')
    if (kind == 'identity_asset' or unit.get('material_requirement', {}).get('fidelity') == 'exact') and route == 'reference_generate':
        fail('element_scope: preserve original photo/identity/existing material','/material_route')
    if kind == 'simple_icon' and route != 'native' and unit.get('material_requirement', {}).get('route_constraint') != route:
        fail('element_scope: simple icons require native editing unless an explicit object exception is cited','/material_route')
    if route == 'reference_generate' and need not in {'image_replace', 'group'}:
        fail('element_scope: generation conflicts with requested editing','/material_route')
    if route == 'preserve_source' and need not in {'preserve', 'image_replace'}:
        fail('element_scope: source preservation requires preservation or image replacement editing','/required_edit')
    if route == 'preserve_source' and unit.get('input_form') == 'raster' and not unit.get('source'):
        fail('element_scope: source preservation requires exact bound source bytes','/source')
    if is_embedded_child(unit):
        parent = units.get(unit['owner_id'])
        if parent is None or need != parent['required_edit'] or need not in {'preserve', 'image_replace', 'group'}:
            fail('element_scope: embedded text must inherit its material owner requirement','/owner_id')
        if parent is not None and need == 'preserve' and unit.get('source') != parent.get('source'):
            fail('element_scope: embedded source text must share exact source pixels/crop','/source')
    for index,row in enumerate(unit.get('embedded_text', [])):
        field='/embedded_text/'+str(index)
        if ownership not in {'embedded', 'asset_title'}:
            fail('element_scope: embedded text requires material text ownership','/text_ownership')
        if row['legibility'] == 'readable' and not row['text'].strip():
            fail('element_scope: readable material text needs exact transcription',field+'/text')
        if row['legibility'] == 'unreadable' and row['text']:
            fail('element_scope: do not invent unreadable material text',field+'/text')
        if row.get('owner_unit_id') not in (None, unit['id'], unit['owner_id']):
            fail('element_scope: embedded text belongs to its current material',field+'/owner_unit_id')
    if 'component_bbox' in unit:
        import math
        b = unit['component_bbox']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in b) or min(b) < 0 or b[2] <= 0 or b[3] <= 0:
            fail('element_scope: component_bbox needs finite source-pixel xywh','/component_bbox')
    checks.finish()


def recommend(unit, production_settings=None):
    need, kind = unit['required_edit'], unit.get('content_type')
    settings = production_settings or {}
    mode = settings.get('values', settings).get('illustration_mode')
    req = unit.get('material_requirement', {})
    constraint = req.get('route_constraint', 'auto')
    if need == 'unresolved':
        method = 'resolve_requirement'
    elif need == 'preserve' or req.get('fidelity') == 'exact' or kind == 'identity_asset':
        method = 'preserve_source'
    elif need in {'text', 'geometry', 'data'}:
        method = 'native'
    elif constraint != 'auto':
        method = constraint
    elif kind == 'simple_icon':
        method = 'native'
    elif mode == 'draw_first' and (kind in {'simple_illustration', 'complex_illustration', 'decorative_title'}
                                     or (kind == 'existing_asset' and need == 'group')):
        method = 'native'
    elif mode == 'generate_first' and kind in {'simple_illustration', 'complex_illustration', 'decorative_title', 'existing_asset'}:
        qualified = req.get('source_qualification', {})
        method = ('preserve_source' if req.get('source_origin') in {'independent_asset', 'extracted_asset'}
                  and qualified.get('complete_subject') and qualified.get('page_artifacts') == 'none'
                  else 'reference_generate')
    elif kind == 'photograph' and req.get('fidelity') == 'reference':
        method = 'reference_generate'
    elif kind in {'photograph', 'existing_asset'}:
        method = 'preserve_source'
    elif kind in {'complex_illustration', 'decorative_title'}:
        method = 'reference_generate'
    elif kind in {'simple_illustration', 'geometric_graphic', 'page_text', 'standard_title'}:
        method = 'native'
    else:
        method = 'inspect_component'
    return {'unit_id': unit['id'], 'content_type': kind, 'required_edit': need,
            'recommended_route': method, 'selected_route': unit.get('material_route'),
            'text_ownership': unit.get('text_ownership'), 'layer': unit.get('layer'),
            'note': 'Recommendation from Agent-supplied classification; source pixels and visual quality are not inferred.'}


def plan_guidance(scope, production_settings=None):
    settings = production_settings or {}
    mode = settings.get('values', settings).get('illustration_mode')
    art_route = 'native' if mode == 'draw_first' else 'reference_generate'
    return {'policy': POLICY, 'components': [recommend(u, production_settings) for u in (scope or {}).get('units', [])],
            'defaults': {'page_text': 'native', 'photograph': 'preserve_source',
                         'complex_illustration': art_route, 'decorative_title': art_route,
                         'simple_icon': 'native', 'simple_illustration': (art_route if mode else 'closed_semantic_parts'), 'geometric_graphic': 'office_shapes',
                         'embedded_text': 'keep_inside_material', 'internal_editing': 'explicit_requirement'},
            'illustration_mode': mode or 'legacy',
            'batch': 'Compatible small materials may share one reference-guided transparent sheet; inspect and crop each item independently.'}


def validate_generation_scope(request, scope, region_id):
    if scope is None:
        return
    from validation_checks import Checks
    checks=Checks()
    batch = bool(request.get('items'))
    all_units = {u['id']: u for u in scope['units']}
    units = {u['id']: u for u in scope['units'] if batch or u['region_id'] == region_id}
    ids = request.get('scope_unit_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or any(i not in units for i in ids):
        checks.add('element_scope: generation requires valid component scope_unit_ids','/scope_unit_ids','generation_scope_ids')
        checks.finish(['generation_component_rules'])
    for uid in ids:
        if units[uid]['required_edit'] not in {'image_replace', 'group'}:
            checks.add('element_scope: preserved, unresolved or native-edit content cannot be regenerated',
                       '/scope_unit_ids','generation_edit_requirement',uid,'revise')
    entries = request.get('items') or [request]
    assigned = []
    for index,item in enumerate(entries):
        path='/items/'+str(index) if batch else ''
        subset = item.get('scope_unit_ids', ids if not batch else [])
        if not isinstance(subset, list) or not subset or any(not isinstance(i, str) or i not in ids for i in subset):
            checks.add('element_scope: every batch item must bind its requested components',path+'/scope_unit_ids','generation_item_binding')
            checks.not_checked.add(path+'/generation_component_rules')
            continue
        assigned.extend(subset)
        decision = item.get('generation_decision', {})
        for uid in subset:
            unit = units[uid]
            owner = unit
            visited=set()
            while True:
                if owner['id'] in visited:
                    checks.add('element_scope: cyclic material ownership',path+'/scope_unit_ids','generation_owner_cycle',uid,'revise')
                    break
                visited.add(owner['id'])
                if owner.get('material_route') in {'native', 'preserve_source'}:
                    checks.add('element_scope: generation conflicts with selected component route; revise scope first',
                               path+'/scope_unit_ids','scope_route_change',uid,'revise')
                    break
                if not is_embedded_child(owner) or owner['owner_id'] not in all_units:
                    break
                owner = all_units[owner['owner_id']]
            if unit.get('content_type') in {'identity_asset', 'page_text', 'standard_title'}:
                checks.add('element_scope: original material or page text cannot become generated artwork',
                           path+'/scope_unit_ids','generation_content_type',uid)
            req = unit.get('material_requirement', {})
            if req.get('fidelity') == 'exact' or req.get('route_constraint') in {'native', 'preserve_source'}:
                checks.add('element_scope: generation conflicts with exact fidelity or explicit material constraint',
                           path+'/scope_unit_ids','generation_fidelity',uid)
            if unit.get('content_type') == 'simple_icon' and req.get('route_constraint') != 'reference_generate':
                checks.add('element_scope: simple icon generation needs an explicit object exception',
                           path+'/scope_unit_ids','simple_icon_native',uid)
            for key in ('content_type', 'required_edit', 'text_ownership', 'embedded_text'):
                if key in decision and key in unit and decision[key] != unit[key]:
                    checks.add('element_scope: generation decision differs from component '+key,
                               path+'/generation_decision/'+key,'generation_component_match',uid)
            if unit.get('embedded_text') and decision.get('embedded_text') != unit['embedded_text']:
                checks.add('element_scope: generation must carry the material embedded text requirements',
                           path+'/generation_decision/embedded_text','generation_embedded_text',uid)
    if set(assigned) != set(ids) or len(assigned) != len(set(assigned)):
        checks.add('element_scope: generation components must map to exactly one item','/scope_unit_ids','generation_unique_assignment')
    checks.finish()


def validate_selected_routes(scope, production_settings=None):
    """Project preferences cannot weaken explicit per-object editing and fidelity."""
    settings = production_settings or {}
    mode = settings.get('values', settings).get('illustration_mode')
    if mode not in {'generate_first', 'draw_first'}:
        return  # Historical contracts retain their accepted routes.
    for unit in (scope or {}).get('units', []):
        kind = unit.get('content_type')
        route = unit.get('material_route')
        req = unit.get('material_requirement', {})
        explicit = req.get('route_constraint', 'auto')
        if kind == 'simple_icon' and explicit == 'auto':
            if route != 'native' or unit.get('required_edit') not in {'geometry', 'group'}:
                raise ValueError('production_settings: simple icon '+unit['id']+' requires native geometry or an editable group')
        if (mode == 'draw_first' and (kind in {'simple_illustration', 'complex_illustration', 'decorative_title'}
                or (kind == 'existing_asset' and unit.get('required_edit') in {'group', 'geometry'}))
                and explicit == 'auto' and unit.get('required_edit') != 'preserve'
                and req.get('fidelity') != 'exact'):
            if route != 'native' or unit.get('required_edit') not in {'geometry', 'group'}:
                raise ValueError('production_settings: draw_first material '+unit['id']+
                                 ' requires native geometry or an internally editable group; cite an explicit object exception')
