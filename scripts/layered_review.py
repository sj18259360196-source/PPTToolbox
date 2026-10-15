"""Versioned review coverage and advisory image resolution. No visual verdicts."""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image
if __package__:
    from .common import sha256, resolve_asset
else:
    from common import sha256, resolve_asset

POLICY = 'layered-review/2'
ADAPTIVE_POLICY = 'layered-review/3'


def _known_policy(policy):
    if policy not in (None, 'legacy-side/1', POLICY, ADAPTIVE_POLICY):
        raise ValueError('Unsupported review policy: '+str(policy))


def review_policy(run):
    policy = run.get('review_policy')
    _known_policy(policy)
    return policy or 'legacy-side/1'


def required_views(comp, index, region_id=None, policy=None, overlay_required=False):
    _known_policy(policy)
    if region_id is not None:
        return bundle_view_files(comp['local_paths'][(index, region_id)], policy, overlay_required)
    if policy not in (POLICY, ADAPTIVE_POLICY):
        return [comp['full_paths'][index]]
    views = comp['full_view_paths'][index]
    return [views['side_by_side'], views['overlay']] if policy == POLICY or overlay_required else [views['side_by_side']]


def bundle_view_files(row, policy=None, overlay_required=False):
    _known_policy(policy)
    if policy not in (POLICY, ADAPTIVE_POLICY):
        return [row['file']]
    return [row['views']['side_by_side'], row['views']['overlay']] if policy == POLICY or overlay_required else [row['views']['side_by_side']]


local_required_views = bundle_view_files


def view_signature(comp, index, region_id=None, policy=None, overlay_required=False):
    """Role-ordered bytes bind observations even when run output paths differ."""
    return tuple(sha256(path) for path in required_views(comp, index, region_id, policy, overlay_required))


def overlay_check(state, page, run, region_id=None, preview=False, object_ids=()):
    """Versioned per-page baseline; previews never complete the Office baseline."""
    policy = review_policy(run)
    settings = (page.get('review_settings') or page.get('production_settings') or state.get('production_settings') or {}).get('values') or {}
    mode = settings.get('overlay_checking', 'standard')
    if policy == POLICY:
        reason = 'legacy_frequent'
    elif policy != ADAPTIVE_POLICY:
        reason = None
    elif mode == 'frequent':
        reason = 'frequent_setting'
    elif region_id:
        region = next((r for r in (page.get('plan') or {}).get('regions', []) if r['id'] == region_id), {})
        reason = region.get('overlay_reason') if region.get('overlay_review') else None
        reason = page.get('overlay_requests', {}).get(region_id, reason)
        # Review crops use generated roi IDs, while plans and revise use source-region IDs.
        for source in (page.get('plan') or {}).get('regions', []):
            prefix = page['id']+'.'+source['id']+'.'
            if any(oid.startswith(prefix) for oid in object_ids):
                if source.get('overlay_review'):reason=source['overlay_reason']
                reason=page.get('overlay_requests',{}).get(source['id'],reason)
    else:
        reason = page.get('overlay_requests', {}).get('full')
        if not reason and not page.get('overlay_baseline'):
            reason = 'first_full_page_alignment'
    key = f'local:{page["index"]}:{region_id}' if region_id else f'full:{page["id"]}'
    result = {'required': bool(reason), 'reason': reason, 'mode': mode, 'index': page['index'],
              'scope': 'local' if region_id else 'full', 'preview_only': preview,
              'purpose': 'Check placement, scale and large deviations. Confirm defects in side-by-side views; texture differences alone do not require revision.'}
    # Bind the actual requirement used by this run for observation reuse.
    checks = run.setdefault('preview_overlay_checks' if preview else 'overlay_checks', {})
    previous = checks.get(key,{})
    if previous.get('used'):result['used']=True
    checks[key] = result
    return result


def requires_overlay(run, index, region_id=None):
    if review_policy(run) == POLICY:
        return True
    key = f'local:{index}:{region_id}' if region_id else None
    checks = run.get('overlay_checks', {})
    if key:
        row=checks.get(key,{})
        return row.get('required', False) or row.get('used',False)
    return any(k.startswith('full:') and row.get('index') == index and (row.get('required') or row.get('used')) for k, row in checks.items())


def layout_snapshot(scene, index):
    from evidence_contract import logical_bounds
    slide = scene['slides'][index-1]
    return {'canvas': scene['canvas'], 'objects': {o['id']: logical_bounds(o) for o in slide['objects']}}


def layout_changed(before, after):
    if before['canvas'] != after['canvas']:
        return True
    objects = before['objects']; current = after['objects']
    if not objects:
        return False
    width, height = after['canvas']['width'], after['canvas']['height']
    moved = [key for key, box in objects.items() if key in current and
             any(abs(a-b) > .05 * extent for a,b,extent in zip(box,current[key],(width,height,width,height)))]
    # A majority of root objects moving by >5% indicates a broad layout change.
    return bool(moved) and len(moved) * 2 >= len(objects)


def prepare_checks(state, run, scene, comp):
    for page in state['pages']:
        baseline = page.get('overlay_baseline')
        if baseline and layout_changed(baseline['layout'], layout_snapshot(scene, page['index'])):
            page.setdefault('overlay_requests', {})['full'] = 'major_layout_change'
        overlay_check(state, page, run)
        for (index, rid), row in comp['local_paths'].items():
            if index == page['index']:
                overlay_check(state, page, run, rid, object_ids=row['object_ids'])


def accept_observation(project, state, page, task, context, result, receipt):
    """Bind optional overlays actually used, including batched local observations."""
    run = state['run']; key=task['target']['key']
    check=context.get('overlay_check',{})
    comp=__import__('workflow_evidence').comparison_views(project,run)
    index=task['target']['index'];rid=task['target'].get('region_id')
    overlay=comp['local_paths'][(index,rid)]['views']['overlay'] if rid else comp['full_view_paths'][index]['overlay']
    viewed={str((Path(project)/name).resolve()) for name in result.get('viewed_files',[])}
    used=str(Path(overlay).resolve()) in viewed
    run.setdefault('overlay_checks',{}).setdefault(key,dict(check)).update(used=used)
    passed=all(c['status']=='passed' for c in result['checks'].values()) if task['kind']=='review_full' else result['status']=='passed'
    if not check.get('required') or not passed:return
    if not rid:
        from common import read_json
        page['overlay_baseline']={'record':receipt,'layout':layout_snapshot(read_json(Path(project)/run['dir']/'scene.json'),index)}
    requests=page.get('overlay_requests',{})
    requests.pop(rid or 'full',None)
    if rid:
        # Clear a transient source-region request only after every matching crop passes.
        ids=context.get('object_ids',[])
        for source in list(requests):
            if source=='full':continue
            prefix=page['id']+'.'+source+'.'
            crops=[crop for (i,crop),row in comp['local_paths'].items() if i==index and any(oid.startswith(prefix) for oid in row['object_ids'])]
            if any(oid.startswith(prefix) for oid in ids):
                from common import read_json
                def crop_passed(crop):
                    ref=run['reviews'].get(f'local:{index}:{crop}')
                    return ref and read_json(Path(project)/ref['file'])['result']['status']=='passed'
                if all(crop==rid or crop_passed(crop) for crop in crops):requests.pop(source,None)


REFINEMENT_SCHEMA = {'type': 'array', 'maxItems': 50, 'items': {
    'type': 'object', 'additionalProperties': False,
    'required': ['issue_id','object_ids','problem','expected_improvement','improved','decision'],
    'properties': {'issue_id': {'type':'string','minLength':1,'maxLength':100},
                   'object_ids': {'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','minLength':1}},
                   'problem': {'type':'string','minLength':1}, 'expected_improvement': {'type':'string','minLength':1},
                   'improved': {'type':'boolean'},
                   'decision': {'enum':['continue','change_method','accept_difference','unresolved']},
                   'method_id':{'type':'string','minLength':1,'maxLength':100},
                   'method_evidence':{'type':'array','maxItems':12,'uniqueItems':True,
                                      'items':{'type':'string','minLength':1,'maxLength':500}}}}}


def validate_refinement(state, task, result, context):
    import jsonschema
    rows = result.get('refinement_issues', [])
    errors=list(jsonschema.Draft202012Validator(REFINEMENT_SCHEMA).iter_errors(rows))
    if errors:raise ValueError('Invalid refinement_issues: '+errors[0].message)
    changes = result.get('status') == 'needs_changes' or any(c.get('status') == 'needs_changes' for c in result.get('checks', {}).values())
    if context.get('review_policy') == ADAPTIVE_POLICY and changes and not rows:
        raise ValueError('needs_changes requires refinement_issues identifying objects, defects and expected improvement')
    seen = set()
    sid = task['target']['slide_id']
    ledger = state.get('refinement_issues', {}).get(sid, {})
    allowed = set(context.get('review_object_ids', context.get('object_ids', [])))
    for row in rows:
        if any(not row[field].strip() for field in ('issue_id','problem','expected_improvement')):
            raise ValueError('Refinement issue, defect and expected improvement must be concrete nonempty text')
        if row['issue_id'] in seen:
            raise ValueError('Duplicate refinement issue_id')
        seen.add(row['issue_id'])
        if allowed and set(row['object_ids']) - allowed:
            raise ValueError('Refinement objects must belong to the reviewed scope')
        previous = ledger.get(row['issue_id'], {})
        count = 0 if row['improved'] or not previous else previous.get('no_improvement_rounds', 0) + int(previous.get('run_id') != (state.get('run') or {}).get('id'))
        if count >= 2 and row['decision'] == 'continue':
            raise ValueError('Two rounds without improvement: choose change_method, accept_difference or unresolved')
        passed = result.get('status') == 'passed' or bool(result.get('checks')) and all(c['status']=='passed' for c in result['checks'].values())
        if passed and (row['decision']=='unresolved' or not row['improved'] and row['decision'] != 'accept_difference'):
            raise ValueError('An unresolved issue cannot pass review; record improvement or an accepted difference')
    return rows


def record_refinement(state, task, result):
    sid = task['target']['slide_id']
    for row in result.get('refinement_issues', []):
        ledger = state.setdefault('refinement_issues', {}).setdefault(sid, {})
        old = ledger.get(row['issue_id'], {})
        run_id=(state.get('run') or {}).get('id')
        record = {**row, 'slide_id':sid, 'task_id':task['id'], 'run_id':run_id,
                  'candidate_sha256':((state.get('run') or {}).get('candidate') or {}).get('sha256'),
                  'previous_task_id':old.get('task_id'), 'method_verification':'agent_reported_not_verified'}
        state.setdefault('refinement_history', []).append(record)
        ledger[row['issue_id']] = {**row, 'no_improvement_rounds': 0 if row['improved'] or not old else old.get('no_improvement_rounds',0)+int(old.get('run_id')!=run_id),
                                 'task_id':task['id'], 'run_id':run_id}


def effective_resolution(node, base, canvas):
    """Compute actual source pixels per placed unit, preserving fit/crop behavior.

    Alpha bounds identify visible pixels only; they cannot identify semantic parts.
    Logical units and PowerPoint points remain distinct from screen/export pixels.
    """
    if node.get('kind') != 'image':
        raise ValueError('effective_resolution requires an image object')
    box = node.get('bbox')
    if (not isinstance(box, list) or len(box) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
            box[2] <= 0 or box[3] <= 0):
        raise ValueError('Image bbox must be finite positive xywh')
    path = resolve_asset(Path(base), node['asset'])
    with Image.open(path) as original:
        rgba = original.convert('RGBA')
        iw, ih = rgba.size
        crop = node.get('source_crop', [0, 0, iw, ih])
        if (not isinstance(crop, list) or len(crop) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in crop)):
            raise ValueError('Invalid source crop')
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0 or cx+cw > iw or cy+ch > ih:
            raise ValueError('Source crop exceeds image')
        fit = node.get('fit', 'contain')
        if fit not in {'contain', 'cover', 'stretch'}:
            raise ValueError('Invalid image fit')
        w, h = box[2:]
        if 'source_crop' in node or fit == 'stretch':
            sx, sy = w/cw, h/ch
        elif fit == 'contain':
            sx = sy = min(w/iw, h/ih)
        else:
            sx = sy = max(w/iw, h/ih)
            cw, ch = w/sx, h/sy
            cx, cy = (iw-cw)/2, (ih-ch)/2
        alpha = rgba.getchannel('A')
        bounds = alpha.getbbox()
    visible = None
    if bounds:
        l, t = max(cx, bounds[0]), max(cy, bounds[1])
        r, b = min(cx+cw, bounds[2]), min(cy+ch, bounds[3])
        if r > l and b > t:
            visible = [l, t, r-l, b-t]
    if any(type(canvas.get(k)) not in (int, float) or not math.isfinite(canvas[k]) or canvas[k] <= 0
           for k in ('width_pt', 'width', 'height_pt', 'height')):
        raise ValueError('Canvas dimensions must be positive')
    px, py = canvas['width_pt']/canvas['width'], canvas['height_pt']/canvas['height']
    if not all(math.isfinite(v) and v > 0 for v in (px, py)):
        raise ValueError('Canvas dimensions must be positive')
    return {'object_id': node['id'], 'asset_sha256': sha256(path),
            'source_pixels': [iw, ih], 'visible_crop_xywh': [cx, cy, cw, ch],
            'subject_pixels_xywh': visible,
            'placed_subject_size': [visible[2]*sx, visible[3]*sy] if visible else [0, 0],
            'pixels_per_logical_unit': [1/sx, 1/sy],
            'effective_ppi': [72/(sx*px), 72/(sy*py)],
            'scope': 'source_pixel_density_and_alpha_bounds_only',
            'visual_review': 'required', 'automatic_acceptance': False,
            'limitations': 'No recovered detail estimate. Alpha bounds include shadows and glow; masks and group transforms require final rendered inspection.'}
