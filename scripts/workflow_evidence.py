"""Reuse the v1.1.1 evidence gate; prepare per-task review without auto-approval."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from runtime_env import powershell_path
from common import read_json, write_json, sha256, staged_directory
from evidence_contract import validate_render, validate_comparisons, required_review, safe_file
from verify_delivery import REQUIRED, verify
from workflow_store import under, WorkflowError


def file_record(root, path):return {'file':Path(path).relative_to(root).as_posix(),'sha256':sha256(path)}


def import_render(receipt, pptx, destination, count):
    receipt=receipt.resolve();report,rows=validate_render(receipt,pptx,count)
    report=copy.deepcopy(report)
    with staged_directory(destination) as stage:
        new=[]
        for index in range(1,count+1):
            row=rows[index];src=safe_file(receipt.parent,row['file']);name=f'slide-{index:03}.png'
            shutil.copyfile(src,stage/name);new.append({**row,'file':name})
        report['slides']=new
        report['import_note']='Imported receipt and actual PNGs checked for identity; no independent attestation of remote execution.'
        write_json(stage/'office-render.json',report)
        validate_render(stage/'office-render.json',pptx,count)
    return destination/'office-render.json'


def render_local(pptx, scene, destination, script):
    from runtime_env import office_guard
    from calibration_exports import track, project_for
    with office_guard(), track(project_for(pptx), destination, len(read_json(scene)["slides"])):
        return _render_local(pptx, scene, destination, script)


def _render_local(pptx, scene, destination, script):
    shell=powershell_path()
    if os.name!='nt' or not shell:return {'status':'awaiting_office','reason':'Windows PowerShell + desktop PowerPoint needed; attach an actual render receipt from an authorized Windows host, or run here on Windows.'}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'PowerPoint.Application\CLSID'):pass
    except OSError:
        return {'status':'awaiting_office','reason':'Desktop PowerPoint COM registration is unavailable; no export attempted.'}
    data=read_json(scene);sizes=[]
    from PIL import Image
    for idx,s in enumerate(data['slides'],1):
        with Image.open(safe_file(scene.parent,s['reference'])) as im:w,h=im.size
        sizes.append({'index':idx,'width':w,'height':h})
    size_path=destination.parent/(destination.name+'-sizes.json');write_json(size_path,sizes)
    argv=[shell,'-NoProfile','-File',str(script),'-Pptx',str(pptx.resolve()),'-OutputDir',str(destination.resolve()),'-SizesJson',str(size_path.resolve())]
    try:p=subprocess.run(argv,timeout=240,capture_output=True,text=True,encoding='utf-8',errors='replace',shell=False)
    except subprocess.TimeoutExpired:
        raise WorkflowError('office_timeout','Office launcher timed out; inspect the task-owned presentation before retry. No PowerPoint process was terminated.')
    (destination.parent/(destination.name+'-command.log')).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
    if p.returncode:raise WorkflowError('office_failed','Office command failed; see the run log and receipt. Do not rebuild the page to fix an environment problem.')
    validate_render(destination/'office-render.json',pptx,len(sizes))
    return {'status':'passed','receipt':destination/'office-render.json'}


def comparison_views(project, run):
    base=under(project,run['dir']+'/scene.json').parent
    validated=validate_comparisons(under(project,run['comparison']['file']),base/'scene.json',
                                  under(project,run['candidate']['file']),under(project,run['render']['file']))
    return validated


def _revision_binding(state, page, region, raw):
    value = {'canvas': state['canvas'], 'slide_id': page['id'],
             'reference': page['sha256'], 'size': page['size'],
             'mapping': page['mapping'], 'region': region, 'raw': raw}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def capture_revision_feedback(project, state, page, region, reason):
    """Capture only the current paired run, never guess from an older run."""
    from workflow_scene import assemble
    result = {'revision_reason': reason, 'status': 'unavailable',
              'unavailable_reason': 'No current Office render paired with this fragment.'}
    fragment = page.get('fragments', {}).get(region['id'])
    run = state.get('run')
    if not fragment or not run or not all(run.get(k) for k in ('candidate', 'render', 'comparison')):
        return result
    # freeze_scene preserves the assembled object dictionaries and asset paths.
    # Equality also binds sibling objects, ordering, canvas and reference mapping.
    if assemble(state) != read_json(under(project, run['dir']+'/scene.json')):
        result['unavailable_reason'] = 'Current objects differ from the rendered scene.'
        return result
    result.update(status='recorded', binding=_revision_binding(state, page, region, fragment['raw']),
                  run=copy.deepcopy(run))
    result.pop('unavailable_reason')
    return result


def revision_feedback(project, state, page, region, folder, include):
    """Historical advice only; no old review status becomes a current assertion."""
    saved = page.get('revision_feedback', {}).get(region['id'])
    if not saved:
        return None
    result = {'revision_reason': saved['revision_reason'], 'status': 'unavailable',
              'scope': 'Historical attempt only. The crop includes the old page context. '
                       'Compare against the source; render and review the new candidate independently.'}
    if saved['status'] != 'recorded':
        result['unavailable_reason'] = saved['unavailable_reason']
        return result
    if saved['binding'] != _revision_binding(
            state, page, region, page.get('previous_fragments', {}).get(region['id'])):
        result['unavailable_reason'] = 'Previous fragment or region identity changed.'
        return result
    run = saved['run']
    try:
        dependencies = []
        base = under(project, run['dir']+'/scene.json').parent
        for relative, expected in run['frozen'].items():
            path = under(base, relative)
            if sha256(path) != expected:
                raise ValueError('Historical frozen input changed: '+relative)
            dependencies.append(path)
        for key in ('candidate', 'audit', 'render', 'comparison'):
            record = run.get(key)
            if not record:
                raise ValueError('Historical run lacks '+key)
            path = under(project, record['file'])
            if sha256(path) != record['sha256']:
                raise ValueError('Historical '+key+' changed.')
            dependencies.append(path)
        views = comparison_views(project, run)
        receipt = under(project, run['render']['file'])
        scene = read_json(base/'scene.json')
        report, rows = validate_render(receipt, under(project, run['candidate']['file']),
                                      len(scene['slides']))
        row = rows[page['index']]
        if [row['width'], row['height']] != page['size']:
            raise ValueError('Historical render size differs from source coordinates.')
        image = safe_file(receipt.parent, row['file'])
        dependencies.append(image)
        from common import walk_objects
        prefix = page['id']+'.'+region['id']+'.'
        ids = {o['id'] for o in walk_objects(scene['slides'][page['index']-1]['objects'])
               if o['id'].startswith(prefix)}
        keys = {'full:'+page['id']}
        keys.update(f'local:{index}:{rid}' for (index, rid), view in views['local_paths'].items()
                    if index == page['index'] and ids.intersection(view['object_ids']))
        observations = []
        for key in sorted(keys):
            record = run.get('reviews', {}).get(key)
            if not record:
                continue
            path = under(project, record['file'])
            if sha256(path) != record['sha256']:
                raise ValueError('Historical review changed.')
            review = read_json(path)
            if review['target']['slide_id'] != page['id']:
                raise ValueError('Historical review belongs to another slide.')
            dependencies.append(path)
            observations.append({'key': key, 'record': record['file'], 'result': review['result']})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['unavailable_reason'] = str(exc)
        return result
    # Write/attach only after the complete evidence chain has validated.
    from PIL import Image
    output = folder/'previous-office-crop.png'
    with Image.open(image) as im:
        im.crop(region['bbox']).save(output)
    for path in dependencies:
        include(path)
    result.update(status='available', run_id=run['id'], crop=include(output, True),
                  crop_bbox=region['bbox'], observations=observations,
                  render_receipt=run['render']['file'],
                  execution_attestation=report.get('import_note', 'Receipt identity validated; execution not independently attested.'))
    return result


def text_geometry_hints(report, slide_index, object_ids=None, limit=20):
    """Bounded advice from recorded Office measurements, never a review verdict."""
    result = {
        'status': 'unavailable', 'findings': [], 'finding_count': 0,
        'measured_objects': 0, 'deferred_objects': 0, 'scan_complete': True,
        'tolerance_pt': .5, 'visual_review': 'required',
        'scope': 'Unrotated root text bounds only. Overlapping bounds need visual inspection; '
                 'grouped text, table cells, glyph shapes and decorative effects are not assessed.',
    }
    if report.get('status') != 'passed' or report.get('renderer') != 'Microsoft PowerPoint':
        return result
    rows = report.get('text_bounds')
    if not isinstance(rows, list):
        return result
    selected = set(object_ids) if object_ids is not None else None
    measured, findings = [], []

    def box(value):
        if (not isinstance(value, list) or len(value) != 4 or
                any(type(n) not in (int, float) or not math.isfinite(n) for n in value)):
            return None
        x, y, w, h = value
        return [x, y, x+w, y+h] if w > 0 and h > 0 else None

    for row in rows:
        if not isinstance(row, dict) or row.get('slide') != slide_index:
            continue
        oid = row.get('id')
        if not isinstance(oid, str) or not oid:
            result['deferred_objects'] += 1
            continue
        if selected is not None and oid not in selected:
            continue
        frame, bounds = box(row.get('box_pt')), box(row.get('bound_pt'))
        rotation = row.get('rotation')
        if (frame is None or bounds is None or
                type(rotation) not in (int, float) or not math.isfinite(rotation) or
                abs(rotation) > .01 or row.get('status') == 'blocked'):
            result['deferred_objects'] += 1
            continue
        if len(measured) >= 1000:
            result['scan_complete'] = False
            break
        measured.append((oid, bounds))
        sides = {
            'left': frame[0]-bounds[0], 'top': frame[1]-bounds[1],
            'right': bounds[2]-frame[2], 'bottom': bounds[3]-frame[3],
        }
        overflow = {side: round(value, 3) for side, value in sides.items() if value > .5}
        if overflow:
            findings.append({'kind': 'text_outside_frame', 'object_id': oid,
                             'overflow_pt': overflow, 'frame_pt': row['box_pt'],
                             'text_bounds_pt': row['bound_pt']})
    # A horizontal sweep avoids comparing distant columns; cap pathological pages.
    measured.sort(key=lambda item: item[1][0])
    pairs = 0
    stop = False
    for index, (oid, a) in enumerate(measured):
        for other_id, b in measured[index+1:]:
            if b[0] >= a[2]-.5:
                break
            pairs += 1
            if pairs > 20000:
                result['scan_complete'] = False
                stop = True
                break
            roi = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
            if oid != other_id and roi[2]-roi[0] > .5 and roi[3]-roi[1] > .5:
                findings.append({'kind': 'possible_text_overlap',
                                 'object_ids': [oid, other_id],
                                 'intersection_pt': [round(value, 3) for value in roi]})
        if stop:
            break
    # Surface collisions before isolated frame overruns when the output is bounded.
    findings.sort(key=lambda item: item['kind'] != 'possible_text_overlap')
    result.update(status='advisory' if measured else 'unavailable',
                  measured_objects=len(measured), findings=findings[:limit],
                  finding_count=len(findings), truncated=len(findings) > limit)
    return result


def build_review(project, state):
    """Turn explicitly submitted assertions into phase-1 format. Hashes are filled by code.
    This authenticates files, NOT the truth of an Agent's assertions.
    """
    from review_reuse import verify as verify_reuse
    verify_reuse(project,state)
    run=state['run'];base=under(project,run['dir']+'/scene.json').parent
    comp=comparison_views(project,run);scene=read_json(base/'scene.json');count=len(scene['slides'])
    review={'pptx_sha256':run['candidate']['sha256'],'scene_sha256':sha256(base/'scene.json'),
            'comparison_sha256':run['comparison']['sha256'],'reviewer':'',
            'checks':{k:{'status':'not_run','note':'','slides':[],'evidence':[]} for k in REQUIRED},
            'limitations':['Review assertions supplied by the host Agent. File integrity cannot prove honest or correct visual interpretation.'],
            'user_acceptance':'not_run'}
    notes={k:[] for k in REQUIRED}; statuses={k:[] for k in REQUIRED};reviewers=[]
    def evidence(check,path):
        rec=file_record(base,path)
        if rec not in review['checks'][check]['evidence']:review['checks'][check]['evidence'].append(rec)
    def add(check,value,indices,record,extra=()):
        statuses[check].append(value['status']);notes[check].append(value['note'])
        review['checks'][check]['slides']=sorted(set(review['checks'][check]['slides'])|set(indices))
        evidence(check,record)
        for p in extra:evidence(check,p)
    records=run.get('reviews',{})
    # Source check is a separate origin-to-transcript assertion; it is NOT inferred from OOXML.
    for page in state['pages']:
        ref=page.get('source_review')
        if not ref:continue
        origin=under(project,ref['file']);record=read_json(origin)
        target=base/'review-evidence'/origin.name;target.parent.mkdir(exist_ok=True)
        if not target.exists():shutil.copyfile(origin,target)
        result=record['result'];reviewers.append(result['reviewer'])
        add('content_source',result,[page['index']],target)
    review['checks']['visual_local']['regions']=[];review['checks']['relationships']['objects']=[]
    for key,ref in records.items():
        origin=under(project,ref['file']);record=read_json(origin);r=record['result'];kind=record['kind'];target_info=record['target']
        target=base/'review-evidence'/origin.name
        if not target.exists():shutil.copyfile(origin,target)
        reviewers.append(r['reviewer'])
        if kind=='review_full':
            idx=target_info['index'];p=comp['full_paths'][idx]
            for check in ['visual_full','raster_scope','text_geometry']:add(check,r['checks'][check],[idx],target,[p])
        elif kind=='review_local':
            idx=target_info['index'];rid=target_info['region_id'];view=comp['local_paths'][(idx,rid)]
            add('visual_local',r,[idx],target,[view['file']])
            review['checks']['visual_local']['regions'].append({'index':idx,'id':rid,'object_ids':view['object_ids'],'note':r['note']})
            if r.get('relationships'):
                add('relationships',r,[idx],target,[view['file']])
                for row in r['relationships']:
                    # A relation can appear in more than one ROI; preserve one object record.
                    if not any(x['index']==idx and x['object_id']==row['object_id'] for x in review['checks']['relationships']['objects']):
                        review['checks']['relationships']['objects'].append({'index':idx,**row})
        elif kind in {'editable_behavior','reproducibility'}:
            files=[under(project,x['file']) for x in record.get('attachments',[])]
            add(kind,r,list(range(1,count+1)),target,files)
    required_rel=any(required_review(s)['relationship_objects'] for s in scene['slides'])
    for name in REQUIRED:
        c=review['checks'][name]
        if name=='visual_local' and not comp['local_paths'] or name=='relationships' and not required_rel:
            c.update(status='not_applicable',note='No applicable declared objects/regions; derived by code, not an Agent waiver.')
        elif statuses[name]:
            c['status']='failed' if any(x in {'needs_changes','failed'} for x in statuses[name]) else 'blocked' if any(x=='blocked' for x in statuses[name]) else 'passed'
            c['note']='\n'.join(notes[name])
    review['reviewer']='; '.join(sorted(set(reviewers)))
    return review


def final_gate(project,state,output):
    run=state['run'];base=under(project,run['dir']+'/scene.json').parent
    review=build_review(project,state);write_json(output/'review.json',review)
    # Gate file paths are relative to the run root. Keep the review at the run root too.
    # Use a versioned name: no already-bound review is overwritten.
    run_review=base/(output.name+'-review.json');write_json(run_review,review)
    result=verify(under(project,run['candidate']['file']),under(project,run['audit']['file']),
                  under(project,run['render']['file']),run_review,under(project,run['comparison']['file']),base/'scene.json')
    write_json(output/'gate.json',result)
    return result,run_review,output/'gate.json'
