"""Conservative revision advice. Never changes review tasks or observations."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

if __package__:
    from .common import resolve_asset, sha256
    from .evidence_contract import logical_bounds
else:
    from common import resolve_asset, sha256
    from evidence_contract import logical_bounds

FORMAT = 'review-impact/1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def summary(report, slide_id, limit=20):
    """Small task context; the caller retains the full report as a bound file."""
    pages=[]
    for page in report['pages']:
        if page['slide_id']!=slide_id:
            continue
        changes,affected=page['changed_objects'],page['affected_object_ids']
        pages.append({**page,'changed_objects':changes[:limit],'affected_object_ids':affected[:limit],
                      'changed_object_count':len(changes),'affected_object_count':len(affected),
                      'object_details_truncated':len(changes)>limit or len(affected)>limit})
    return {k:v for k,v in report.items() if k not in {'pages','unchanged_page_ids'}} | {'pages':pages}


def _index(slide):
    rows = {}
    def walk(objects, parents=()):
        for position, obj in enumerate(objects):
            oid = obj['id']
            if oid in rows:
                raise ValueError('Ambiguous duplicate object ID: '+oid)
            rows[oid] = (obj, parents, position)
            if obj['kind'] == 'group':
                walk(obj['children'], parents+(oid,))
    walk(slide.get('objects', []))
    return rows


def _properties(obj):
    # A changed child does not imply a transform on the whole group.
    return {k: ([c['id'] for c in v] if k == 'children' else v) for k, v in obj.items()}


def _dependencies(scene, base):
    hashes, uses, unresolved = {}, {}, []
    def add(asset, sid, oid):
        uses.setdefault(asset, set()).add((sid, oid))
        if asset in hashes:
            return
        try:
            hashes[asset] = sha256(resolve_asset(base, asset))
        except (OSError, ValueError):
            hashes[asset] = None
            unresolved.append(asset)
    for slide in scene['slides']:
        sid = slide['id']
        if slide.get('reference'):
            add(slide['reference'], sid, None)
        for oid, (obj, _, _) in _index(slide).items():
            if obj.get('asset'):
                add(obj['asset'], sid, oid)
            for field in ('reference', 'drawing'):
                if obj.get('generation_decision', {}).get(field):
                    add(obj['generation_decision'][field], sid, oid)
        for unit in slide.get('element_scope', {}).get('units', []):
            if unit.get('source', {}).get('asset'):
                # Source scopes can bind several owners. Page review is safer
                # than guessing a single visible consumer from its unit name.
                add(unit['source']['asset'], sid, None)
    return hashes, uses, unresolved


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _intersects(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def _bounds(obj, canvas, measured):
    box = logical_bounds(obj)
    style = obj.get('style', {})
    if (obj.get('native_group_transform') or obj.get('native_path_frame')
            or any(k in style for k in ('native_format', 'shadow', 'glow', 'soft_edge',
                                       'warp', 'text_outline', 'effects'))):
        raise ValueError('unbounded_effect_or_native_transform')
    if obj['kind'] in {'table', 'chart'}:
        raise ValueError('compound_layout_needs_page_review')
    if obj.get('adjustments'):
        raise ValueError('preset_adjustment_extent_unverified')
    if obj['kind'] == 'text':
        row = measured.get(obj['id'])
        if (not row or row.get('status') == 'blocked' or row.get('rotation', 0)
                or obj.get('rotation', 0)):
            raise ValueError('text_layout_without_paired_office_bounds')
        values = row.get('bound_pt')
        if (not isinstance(values, list) or len(values) != 4
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in values)
                or values[2] <= 0 or values[3] <= 0):
            raise ValueError('text_bounds_unavailable')
        sx, sy = canvas['width']/canvas['width_pt'], canvas['height']/canvas['height_pt']
        x, y, w, h = values
        box = _union([box, [x*sx, y*sy, (x+w)*sx, (y+h)*sy]])
    line = style.get('line') or {}
    width = line.get('width_pt', style.get('line_width_pt', 0)) if isinstance(line, dict) else style.get('line_width_pt', 0)
    arrow_scale = 8 if style.get('begin_arrow') or style.get('end_arrow') else 1
    margin = 2 + arrow_scale*abs(width)*max(canvas['width']/canvas['width_pt'],
                               canvas['height']/canvas['height_pt'])
    box = [box[0]-margin, box[1]-margin, box[2]+margin, box[3]+margin]
    if any(not math.isfinite(n) for n in box):
        raise ValueError('invalid_geometry')
    return box


def compare(before, after, before_base, after_base, *, before_bounds=None,
            after_bounds=None, changed_assets=()):
    """Bounds, if supplied, must come from receipts bound to these scene versions."""
    old = {s['id']: s for s in before['slides']}
    new = {s['id']: s for s in after['slides']}
    if len(old) != len(before['slides']) or len(new) != len(after['slides']):
        raise ValueError('Ambiguous duplicate slide ID')
    ah, au, ax = _dependencies(before, Path(before_base))
    bh, bu, bx = _dependencies(after, Path(after_base))
    forced = set(changed_assets)
    if forced - (ah.keys() | bh.keys()):
        raise ValueError('changed_assets must name dependencies in either scene')
    assets = {p for p in ah.keys() | bh.keys() if ah.get(p) != bh.get(p)} | forced | set(ax+bx)
    global_fields = {k for k in before.keys() | after.keys()
                     if k not in {'slides', 'version', 'path_base', 'title'}
                     and before.get(k) != after.get(k)}
    pages = []
    for sid in dict.fromkeys([*old, *new]):
        a, b = old.get(sid, {}), new.get(sid, {})
        ai, bi = _index(a), _index(b)
        changed, reasons = {}, set()
        canvas = after['canvas'] if sid in new else before['canvas']
        whole = [0, 0, canvas['width'], canvas['height']]
        if global_fields:
            reasons.add('global_scene_change')
        if sid not in old or sid not in new:
            reasons.add('page_added_or_removed')
        elif list(old).index(sid) != list(new).index(sid):
            reasons.add('page_order_changed')
        if {k:v for k,v in a.items() if k != 'objects'} != {k:v for k,v in b.items() if k != 'objects'}:
            reasons.add('page_contract_or_reference_changed')
        for oid in ai.keys() | bi.keys():
            left, right = ai.get(oid), bi.get(oid)
            fields = []
            if not left or not right:
                fields = ['added' if right else 'removed']
            else:
                ap, bp = _properties(left[0]), _properties(right[0])
                fields = sorted(k for k in ap.keys() | bp.keys() if ap.get(k) != bp.get(k))
                if left[1:] != right[1:]:
                    fields.append('parent_or_draw_order')
            if fields:
                changed[oid] = fields
        page_assets = []
        for path in sorted(assets):
            consumers = au.get(path, set()) | bu.get(path, set())
            relevant = [(s, o) for s, o in consumers if s == sid]
            if relevant:
                page_assets.append(path)
            for _, oid in relevant:
                if oid is None:
                    reasons.add('shared_source_or_reference_changed')
                else:
                    changed.setdefault(oid, []).append('asset_content')
        if not changed and not reasons:
            continue
        affected = set(changed)
        # A transform/order/membership change on a group covers every descendant.
        for oid, (_, parents, _) in {**ai, **bi}.items():
            if any(p in changed for p in parents):
                affected.add(oid)
        for oid, (obj, _, _) in {**ai, **bi}.items():
            if obj['kind']=='connector':
                endpoints={obj.get(k,{}).get('object_id') for k in ('begin','end')}-{None}
                if oid in affected or endpoints & affected:
                    affected.update(endpoints | {oid})
                    reasons.add('attached_connector_reflow')
        boxes = []
        measurements = (before_bounds or {}, after_bounds or {})
        for index, rows in enumerate((ai, bi)):
            frame = before['canvas'] if index == 0 else after['canvas']
            measured = measurements[index].get(sid, {})
            for oid in affected:
                if oid not in rows:
                    continue
                obj, parents, _ = rows[oid]
                if any(rows[p][0].get('rotation', 0) or rows[p][0].get('native_group_transform') for p in parents):
                    reasons.add('group_transform_requires_page_review')
                try:
                    boxes.append(_bounds(obj, frame, measured))
                except (KeyError, ValueError, TypeError):
                    reasons.add('uncertain_changed_object_extent')
        # Neighbours may overflow their frames. Missing text/effect bounds mean
        # a local exclusion cannot be proved, so keep the entire page in scope.
        for index, rows in enumerate((ai, bi)):
            frame = before['canvas'] if index == 0 else after['canvas']
            measured = measurements[index].get(sid, {})
            for oid, (obj, parents, _) in rows.items():
                if oid in affected:
                    continue
                try:
                    box = _bounds(obj, frame, measured)
                    if any(_intersects(box, area) for area in boxes):
                        affected.add(oid)
                        affected.update(parents)
                        boxes.append(box)
                except (KeyError, ValueError, TypeError):
                    reasons.add('uncertain_neighbour_extent')
        if len(boxes) > 64:
            reasons.add('region_budget_exceeded')
        full = bool(reasons) or not boxes
        if full:
            affected.update(ai.keys() | bi.keys())
            regions = [whole]
        else:
            # One union includes the old/new placement corridor and overlaps.
            # Keep raw coordinates for off-canvas diagnostics; never clip them.
            regions = [_union(boxes)]
        relations = set()
        for slide in (a, b):
            relations.update(slide.get('review_requirements', {}).get('relationship_objects', []))
        affected.update(relations)
        for oid in list(affected):
            for rows in (ai, bi):
                if oid in rows:
                    affected.update(rows[oid][1])
        pages.append({'slide_id': sid, 'scope': 'full_page' if full else 'regions',
                      'changed_objects': [{'id': k, 'fields': sorted(set(v))} for k,v in sorted(changed.items())],
                      'affected_object_ids': sorted(affected), 'regions_xyxy': regions,
                      'changed_assets': page_assets, 'expansion_reasons': sorted(reasons),
                      'out_of_canvas': any(r[0] < 0 or r[1] < 0 or r[2] > whole[2] or r[3] > whole[3] for r in boxes),
                      'checks': ['geometry', 'occlusion', 'bounds', 'text_reflow', 'relationships'],
                      'visual_review': 'required'})
    return {'format': FORMAT, 'status': 'advisory', 'automatic_review_scheduling': False,
            'observations_written': False, 'review_reuse_policy': 'existing_exact_bindings_unchanged',
            'binding': {'before': digest([before, ah]), 'after': digest([after, bh])},
            'changed_assets': sorted(assets), 'unresolved_dependencies': sorted(set(ax+bx)),
            'pages': pages, 'affected_pages': len(pages),
            'unchanged_page_ids': [s for s in new if s not in {p['slide_id'] for p in pages}],
            'note': 'Advice only. Unlisted pages are not approved or exempt from existing checks. '
                    'Compare frozen assets, or explicitly identify same-path in-place asset changes.'}


def from_runs(project, before, after):
    """Use existing frozen-file and render bindings; altered evidence is rejected."""
    from workflow_store import under, WorkflowError
    from common import read_json
    from evidence_contract import validate_render
    values, bases, bounds, render_rows, environments = [], [], [], [], []
    for run in (before, after):
        base = under(project, run['dir']+'/scene.json').parent
        for name, value in run['frozen'].items():
            if sha256(under(base, name)) != value:
                raise WorkflowError('impact_changed', 'Frozen impact input changed')
        scene = read_json(base/'scene.json')
        values.append(scene); bases.append(base)
        measured = {}
        images = {}
        environment = None
        if run.get('render') and run.get('candidate'):
            for key in ('render', 'candidate'):
                if sha256(under(project, run[key]['file'])) != run[key]['sha256']:
                    raise WorkflowError('impact_changed', 'Impact render dependency changed')
            report, images = validate_render(under(project, run['render']['file']),
                                       under(project, run['candidate']['file']), len(scene['slides']))
            environment = report.get('office_version')
            for row in report.get('text_bounds', []):
                idx = row.get('slide')
                if type(idx) is int and 1 <= idx <= len(scene['slides']) and row.get('id'):
                    measured.setdefault(scene['slides'][idx-1]['id'], {})[row['id']] = row
        bounds.append(measured)
        render_rows.append({scene['slides'][i-1]['id']:row['sha256'] for i,row in images.items()})
        environments.append(environment)
    result = compare(*values, *bases, before_bounds=bounds[0], after_bounds=bounds[1])
    covered = {p['slide_id'] for p in result['pages']}
    environment_changed = environments[0] != environments[1]
    for slide in values[1]['slides']:
        sid = slide['id']
        pixels_changed = sid in render_rows[0] and sid in render_rows[1] and render_rows[0][sid] != render_rows[1][sid]
        if environment_changed or (pixels_changed and sid not in covered):
            prior=next((p for p in result['pages'] if p['slide_id']==sid),{})
            result['pages'] = [p for p in result['pages'] if p['slide_id'] != sid]
            c = values[1]['canvas']
            reason='office_environment_changed' if environment_changed else 'render_changed_without_scene_delta'
            result['pages'].append({'slide_id': sid, 'scope': 'full_page', 'changed_objects': prior.get('changed_objects',[]),
                'affected_object_ids': sorted(_index(slide)), 'regions_xyxy': [[0,0,c['width'],c['height']]],
                'changed_assets': prior.get('changed_assets',[]), 'expansion_reasons': sorted(set(prior.get('expansion_reasons',[])+[reason])),
                'out_of_canvas': prior.get('out_of_canvas',False), 'checks': ['geometry','occlusion','bounds','text_reflow','relationships'],
                'visual_review': 'required'})
    result['affected_pages'] = len(result['pages'])
    result['unchanged_page_ids'] = [s['id'] for s in values[1]['slides'] if s['id'] not in {p['slide_id'] for p in result['pages']}]
    result['binding'].update(before_run=before['id'], after_run=after['id'])
    for label,run in (('before',before),('after',after)):
        for key in ('candidate','render'):
            result['binding'][label+'_'+key+'_sha256']=(run.get(key) or {}).get('sha256')
    return result
