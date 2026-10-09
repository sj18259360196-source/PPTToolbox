"""Bounded selection experiments and method routing, independent of case assets."""
import copy
import hashlib
import io
import json
import math
from pathlib import Path


def choose(o):
    """Observations come from the production agent; this does not inspect images."""
    old_unknown = any(o.get(k) is None for k in ('limited_palette', 'semantic_layers')) or o.get('boundary') == 'unknown'
    excluded = o.get('boundary') in ('texture', 'faceted') or o.get('semantic_layers') is False or not o.get('layer_editing_required', True)
    methods = ['native-pen-node', 'selection-to-path']
    reasons = []
    if excluded:
        decision, recommendation = 'not_applicable', 'other-representation'
        reasons.append('Observed representation is outside layered curve reconstruction')
    elif old_unknown:
        decision, recommendation = 'needs_local_probe', 'local-probe'
        reasons.append('Resolve unknown palette, semantic ownership or boundary before fitting')
    else:
        decision, recommendation = 'applicable', 'agent-choice'
    risky = [k for k in ('thin_branches', 'many_holes', 'mixed_boundary_colors') if o.get(k) is True]
    if not excluded and not old_unknown:
        if risky or o.get('limited_palette') is False:
            recommendation = 'native-pen-node'
            reasons.append('Coverage assumptions need a representative topology probe: ' + ', '.join(risky or ['continuous palette']))
        elif o.get('gradients_or_fringes') is True:
            recommendation = 'per-part-hybrid'
            reasons.append('Select geometry and color/gradient restoration separately')
        elif o.get('separable_regions') is True and o.get('shared_edges_known') is True:
            recommendation = 'selection-to-path'
            reasons.append('Observed filled regions and shared boundaries support a selection candidate')
        else:
            reasons.append('Both methods retained; inspect a representative region before choosing')
    if o.get('ranking_reversal') is True and not excluded:
        recommendation = 'local-probe'
        reasons.append('Sampling-policy ranking reversal requires local review; no scalar winner')
    if o.get('topology_changed') is True and not excluded:
        recommendation = 'native-pen-node'
        reasons.append('Reject the changed-topology selection candidate and revise or switch method')
    unknown = [k for k in ('gradients_or_fringes', 'thin_branches', 'many_holes', 'mixed_boundary_colors', 'separable_regions', 'shared_edges_known') if o.get(k) is None]
    return dict(case_id='limited-palette-layered-curves-v1', decision=decision,
        recommendation=recommendation, retained_methods=methods, chosen_by='production_agent_per_part',
        observations=o, reasons=reasons, missing_observations=unknown,
        basis='agent_supplied_observations_not_machine_vision', manual='references/layered-illustration.md',
        next_action='Record object or part, route and observed reason in page_plan.notes; freeze source-only evaluation, make a candidate, then review topology, color and actual Office edits.',
        guards=['No automatic adoption', 'User editability and generation restrictions prevail',
                'Topology loss blocks candidate adoption', 'Smoothness or fewer nodes is not fidelity',
                'Measure selection, tracing, fitting and Office separately'], visual_review='not_assessed')


def _read(project, name, sha):
    from illustration_workflow import read_input
    return read_input(project, name, sha)


def _image(project, name, sha, binary=False):
    import numpy as np
    from PIL import Image
    with Image.open(io.BytesIO(_read(project, name, sha))) as im:
        if im.width * im.height > 4_000_000:
            raise ValueError('Image exceeds four million pixels')
        im.load()
        a = np.asarray(im.convert('L' if binary else 'RGB'))
    if binary:
        if not np.isin(a, [0, 255]).all():
            raise ValueError('Explicit masks must be binary 0/255')
        return a == 255
    return a.astype(float)


def _scale(a, scale, mode):
    import numpy as np
    from scipy.ndimage import map_coordinates
    h, w = a.shape
    if h * w * scale * scale > 4_000_000:
        raise ValueError('Evaluation grid exceeds four million pixels')
    yy, xx = np.mgrid[:h * scale, :w * scale]
    return map_coordinates(a.astype(float), [(yy + .5) / scale - .5, (xx + .5) / scale - .5],
                           order=0 if mode == 'nearest' else 1, mode='nearest', prefilter=False)


def _predicate(rgb, rules, scale=1, sampling='bilinear'):
    import numpy as np
    out = np.ones((rgb.shape[0]*scale, rgb.shape[1]*scale), dtype=bool)
    for rule in rules:
        if not any(rule['weights']):raise ValueError('Channel weights cannot all be zero')
        field = np.sum(rgb * np.asarray(rule['weights']), axis=2)
        field = _scale(field, scale, sampling)
        if 'min' in rule:
            out &= field > rule['min']
        if 'max' in rule:
            out &= field < rule['max']
        if 'min' not in rule and 'max' not in rule:
            raise ValueError('Each channel rule needs min or max')
        if 'min' in rule and 'max' in rule and rule['min'] >= rule['max']:
            raise ValueError('Invalid channel rule range')
    return out


def _topology(mask):
    import numpy as np
    from scipy.ndimage import label, binary_fill_holes
    _, n = label(mask)
    _, h = label(binary_fill_holes(mask) & ~mask)
    return dict(components=int(n), holes=int(h), foreground_pixels=int(np.sum(mask)),
                connectivity='foreground_4_background_4')


def _file(folder, project, name, data):
    from PIL import Image
    p = folder / name
    if isinstance(data, dict):
        p.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    else:
        Image.fromarray(data).save(p)
    return dict(path=p.relative_to(project).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def selections(project, a, folder):
    import numpy as np
    from scipy.ndimage import gaussian_filter, distance_transform_edt, label
    rgb = _image(project, a['reference'], a['reference_sha256'])
    method = a['method']; scale = a.get('scale', 1); rules = a['rules']
    if rgb.shape[0]*rgb.shape[1]*scale*scale>4_000_000:raise ValueError('Selection grid exceeds budget')
    if method=='coverage' and any(k not in a for k in ('foreground_rules','background_rules','coverage_weights')):raise ValueError('Coverage requires explicit core rules and weights')
    baseline = _predicate(rgb, rules, scale, 'nearest')
    extra = {}; warnings = []
    if method == 'color':
        mask = _predicate(rgb, rules, scale, a.get('sampling', 'nearest'))
    elif method == 'edge_assisted':
        sigma = a.get('sigma', .6); amount = a.get('amount', .35)
        enhanced = np.clip(rgb + amount*(rgb-gaussian_filter(rgb, (sigma,sigma,0))), 0, 255)
        mask = _predicate(enhanced, rules, scale, a.get('sampling','nearest'))
        warnings.append('Enhanced image is assistance only; compare geometry to unchanged source')
    elif method == 'coverage':
        core = _predicate(rgb, a['foreground_rules']); background = _predicate(rgb, a['background_rules'])
        if not core.any() or not background.any() or (core & background).any():
            raise ValueError('Coverage requires nonempty disjoint foreground and background cores')
        q = np.sum(rgb*np.asarray(a['coverage_weights']), axis=2)
        _, fi = distance_transform_edt(~core, return_indices=True)
        _, bi = distance_transform_edt(~background, return_indices=True)
        f, b = q[tuple(fi)], q[tuple(bi)]; den = f-b
        valid = np.abs(den) >= a.get('minimum_contrast', 10)
        alpha = np.zeros(q.shape); alpha[valid] = np.clip((q[valid]-b[valid])/den[valid],0,1)
        mask = (_scale(alpha,scale,'bilinear') > a.get('coverage_threshold',.5)) & (_scale(valid,scale,'nearest')>.5)
        if a.get('clip_rules'):
            mask &= _predicate(rgb, a['clip_rules'],scale,'bilinear')
        extra['coverage'] = _file(folder,project,'coverage.png',np.rint(alpha*255).astype('uint8'))
        warnings.append('Local two-color scalar mixture is a hypothesis; gradients, light fringes and third colors may invalidate it')
    else:
        raise ValueError('Unknown selection method')
    if not mask.any():
        raise ValueError('Selection is empty')
    if a.get('support_mask'):
        support = _image(project,a['support_mask'],a['support_sha256'],True)
        if support.shape != rgb.shape[:2]:raise ValueError('Support mask must match source frame')
        support = _scale(support,scale,'nearest')>.5
        mask &= support; baseline &= support
    if a.get('seeds'):
        labels, _ = label(mask); selected=set()
        for x,y in a['seeds']:
            if not (0<=x<rgb.shape[1] and 0<=y<rgb.shape[0]):raise ValueError('Seed outside source frame')
            value=int(labels[int(y*scale),int(x*scale)])
            if value==0:raise ValueError('Seed does not hit the selected foreground')
            selected.add(value)
        mask = np.isin(labels,list(selected))
        # Compare the same semantic selection, not the entire unseeded mask.
        labs,_=label(baseline);ids={int(labs[int(y*scale),int(x*scale)]) for x,y in a['seeds']};ids.discard(0)
        baseline=np.isin(labs,list(ids))
    if not mask.any():raise ValueError('Scoped selection is empty')
    observed=_topology(mask); base=_topology(baseline)
    expected=a.get('expected_topology')
    changed=any(observed[k] != base[k] for k in ('components','holes'))
    mismatch=expected is not None and any(observed[k] != expected[k] for k in ('components','holes'))
    return dict(method=method,mask=_file(folder,project,'selection.png',(mask*255).astype('uint8')),
        trace_mask=_file(folder,project,'trace-black-foreground.png',((~mask)*255).astype('uint8')),
        source_size=[rgb.shape[1],rgb.shape[0]],scale=scale,coordinate_units='source_pixels',
        topology=observed,color_baseline_topology=base,topology_changed=changed,
        adoption_blocked=bool(changed or mismatch),expected_topology_mismatch=bool(mismatch),
        warnings=warnings,extra=extra,parameters=a,
        next_action='Check source semantics and topology before icons_trace_fragment; use source-sized box, keep the unfit trace, then fit_paths. Never auto-adopt.')


def freeze(project, a, folder):
    import numpy as np
    rgb=_image(project,a['reference'],a['reference_sha256'])
    scale=a.get('scale',1); masks=[]
    if len({p['name'] for p in a['policies']})!=len(a['policies']):raise ValueError('Duplicate policy name')
    for i,p in enumerate(a['policies']):
        if p['sampling']=='nearest_binary':
            mask=_scale(_predicate(rgb,p['rules']),scale,'nearest')>.5
        else:
            mask=_predicate(rgb,p['rules'],scale,'bilinear')
        if not mask.any():raise ValueError('Frozen policy has empty foreground')
        masks.append(dict(name=p['name'],sampling=p['sampling'],rules=p['rules'],
                          file=_file(folder,project,f'reference-{i}.png',(mask*255).astype('uint8')),
                          topology=_topology(mask)))
    # This operation accepts no candidate and never overwrites a prior contract.
    return dict(format='illustration-evaluation/1',reference=a['reference'],reference_sha256=a['reference_sha256'],
        source_size=[rgb.shape[1],rgb.shape[0]],scale=scale,policies=masks,
        frame='fixed_pixel_centers_no_alignment',scope='source_only_evaluation_contract',
        limitation='Thresholds encode caller assumptions, not unique original vector truth; freeze before candidate choice')


def evaluate(project,a,folder):
    import numpy as np
    from scipy.ndimage import binary_erosion,distance_transform_edt
    contract=json.loads(_read(project,a['contract_file'],a['contract_sha256']).decode('utf-8'))
    if contract.get('format')!='illustration-evaluation/1':raise ValueError('Unknown evaluation contract')
    _read(project,contract['reference'],contract['reference_sha256'])
    scale=contract['scale'];shape=(contract['source_size'][1]*scale,contract['source_size'][0]*scale)
    if shape[0]*shape[1]*len(a['stages'])*len(contract['policies'])>32_000_000:raise ValueError('Stage evaluation exceeds pixel-operation budget')
    def measure(left,right):
        if not left.any() or not right.any():raise ValueError('Cannot measure empty mask')
        le=left&~binary_erosion(left,border_value=0);re=right&~binary_erosion(right,border_value=0)
        ds=np.r_[distance_transform_edt(~re)[le],distance_transform_edt(~le)[re]]/scale
        return dict(iou_pct=float(100*(left&right).sum()/(left|right).sum()),
                    p95_source_px=float(np.percentile(ds,95)),max_source_px=float(ds.max()))
    masks={};rows=[]
    for stage in a['stages']:
        if stage['id'] in masks:raise ValueError('Duplicate stage ID')
        m=_image(project,stage['mask'],stage['sha256'],True)
        if m.shape!=shape:raise ValueError('Stage mask does not match frozen frame')
        masks[stage['id']]=m
        for policy in contract['policies']:
            r=_image(project,policy['file']['path'],policy['file']['sha256'],True)
            if r.shape!=shape:raise ValueError('Frozen reference frame changed')
            rows.append(dict(stage=stage['id'],policy=policy['name'],topology=_topology(m),
                             topology_changed=any(_topology(m)[k]!=policy['topology'][k] for k in ('holes','components')),
                             **measure(r,m)))
    pairs=[]
    for pair in a.get('pairs',[]):
        if pair['from'] not in masks or pair['to'] not in masks:raise ValueError('Unknown stage in pair')
        pairs.append(dict(**pair,**measure(masks[pair['from']],masks[pair['to']]),
                          interpretation='direct_pair_measurement_not_subtraction_or_causal_attribution'))
    rankings={p['name']:sorted(masks,key=lambda s:next(r['iou_pct'] for r in rows if r['policy']==p['name'] and r['stage']==s),reverse=True) for p in contract['policies']}
    reversal=len({tuple(v) for v in rankings.values()})>1
    return dict(contract_file=a['contract_file'],contract_sha256=a['contract_sha256'],rows=rows,pairs=pairs,
        iou_rankings=rankings,ranking_reversal=reversal,automatic_winner=None,
        next_action='Keep both routes and inspect original-pixel regions, color and topology' if reversal else 'Inspect geometry, color, topology and Office edits; scalar ranking alone does not adopt a candidate')


def share(project,a,folder):
    from pen_path_fit import validate_fragment,leaves,contours,nesting,signed_area
    import numpy as np
    value=json.loads(_read(project,a['input_file'],a['input_sha256']).decode('utf-8-sig'))
    fragment=copy.deepcopy(value.get('scene_fragment',value));validate_fragment(fragment)
    paths={p['id']:p for p in leaves(fragment) if p['kind']=='path'}
    original=copy.deepcopy(paths);reports=[];targets=set()
    def rings(cs):
        result=[];cur=[]
        for cmd in cs:
            if cmd[0]=='M':
                if cur:raise ValueError('Shared rings require closed paths')
                cur=[cmd]
            elif cmd[0]=='Z':
                if not cur:raise ValueError('Malformed closed ring')
                cur.append(cmd);result.append(cur);cur=[]
            else:cur.append(cmd)
        if cur:raise ValueError('Shared rings require closed paths')
        return result
    def reverse(cs):
        start=cs[0][1:];cur=start;segments=[]
        for c in cs[1:-1]:segments.append((cur,c));cur=c[-2:]
        if cur!=start:segments.append((cur,['L',*start]))
        out=[['M',*start]]
        for old,c in reversed(segments):
            out.append(['L',*old] if c[0]=='L' else ['C',*c[3:5],*c[1:3],*old])
        return out+[['Z']]
    for rel in a['relations']:
        source,target=rel['source'],rel['target']
        if source not in original or target not in paths or source==target:raise ValueError('Unknown or identical shared-ring paths')
        key=(target,rel['target_ring'])
        if key in targets:raise ValueError('Duplicate shared-ring target')
        targets.add(key)
        sr=rings(original[source]['commands']);tr=rings(paths[target]['commands'])
        if rel['source_ring']>=len(sr) or rel['target_ring']>=len(tr):raise ValueError('Ring index outside path')
        before=contours(paths[target]['commands']);nest_before=nesting(before)
        if nest_before is None:raise ValueError('Invalid original topology')
        shared=copy.deepcopy(sr[rel['source_ring']]);old=tr[rel['target_ring']]
        if rel.get('reverse',False):shared=reverse(shared)
        from scipy.spatial import cKDTree
        p=contours(old)[0][0];q=contours(shared)[0][0]
        distance=float(max(cKDTree(p).query(q)[0].max(),cKDTree(q).query(p)[0].max()))
        if distance>a['max_displacement']:raise ValueError('Shared ring exceeds sampled displacement budget')
        if signed_area(p)*signed_area(q)<=0:raise ValueError('Shared ring would change target winding; specify correct reverse')
        tr[rel['target_ring']]=shared;commands=[c for ring in tr for c in ring]
        after=contours(commands)
        if nesting(after)!=nest_before:raise ValueError('Shared ring would change nesting or intersect another ring')
        paths[target]['commands']=commands
        reports.append(dict(**rel,max_sampled_displacement=distance,topology_preserved=True))
    validate_fragment(fragment)
    return dict(scene_fragment=fragment,relations=reports,coordinate_units=a['coordinate_units'],
        scope='whole_closed_ring_reuse_same_coordinate_frame',
        limits=['Partial shared arcs use graphics recipe edges/faces; not inferred here',
                'Re-measure final geometry; earlier fit reports do not cover shared-ring edits',
                'Sampled validation is not a continuous proof; cross-object semantics require visual review'])


def execute(project,op,a):
    import uuid
    from project_journal import safe
    operations={'selection_masks':selections,'freeze_evaluation':freeze,'evaluate_stages':evaluate,'share_rings':share}
    if op not in operations:raise ValueError('Unknown illustration method operation')
    folder=safe(project,'runs/illustration-methods/'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=False)
    result=operations[op](project,a,folder)
    item=_file(folder,project,'result.json',result)
    return dict(result_file=item['path'],result_sha256=item['sha256'],status='candidate_only',
                office='not_run',visual_review='not_assessed')
