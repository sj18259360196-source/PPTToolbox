"""Bounded, read-only project diagnostics. Findings never approve or alter a scene."""
import copy
import json
import sys
from pathlib import Path
from .policy import authorize, check_input, PolicyDenied
from .project_context import ProjectContext


def inspect(manager, args):
    package=manager.package()
    if not package.get('enabled') or not package.get('trusted') or not manager.override(package['id'],'tool','toolbox_project_inspect',True):
        raise PolicyDenied('Project inspection is disabled')
    project,roots=authorize(manager,args['project'])
    sys.path.insert(0,str(Path(package['path'])/'scripts'))
    from common import read_json,sha256,walk_objects
    from workflow_store import load,under,check_packet
    identity=ProjectContext(manager,project).snapshot()
    action=args.get('action','identity');offset=args.get('offset',0);limit=args.get('limit',6)
    if not 0<=offset or not 1<=limit<=20:raise ValueError('Invalid pagination')
    if action=='identity':return identity
    if action=='response':
        import re
        cid=args.get('call_id')
        if not isinstance(cid,str) or not re.fullmatch(r'[0-9a-f]{32}',cid):
            raise ValueError('Expected a managed 32-character hexadecimal call_id')
        context=ProjectContext(manager,project)
        call=context.path('logs/tool-calls/'+cid+'/call.json')
        if not call.is_file():return {'available':False,'reason':'call_receipt_unavailable','call_id':cid}
        if call.stat().st_size>16*1024*1024:raise ValueError('Call receipt exceeds inspection limit')
        receipt=read_json(call)
        if receipt.get('call_id')!=cid or Path(receipt.get('project','')).resolve()!=project:
            raise ValueError('Call receipt project/call identity differs')
        ref=receipt.get('response_detail')
        if not ref:return {'available':False,'reason':'legacy_call_has_no_full_response','call_id':cid}
        if receipt.get('project_id')!=identity.get('project_id'):
            raise ValueError('Call receipt belongs to a different project identity')
        path=context.path('logs/tool-calls/'+cid+'/response-full.json')
        if not path.is_file():return {'available':False,'reason':'full_response_unavailable','call_id':cid}
        if ref.get('format')!='ppt-response-detail/1' or ref.get('file')!='response-full.json':
            raise ValueError('Unsupported full response reference')
        from .context_delivery import DETAIL_BYTES
        if path.stat().st_size>DETAIL_BYTES:raise ValueError('Full response exceeds inspection limit')
        if sha256(path)!=ref.get('sha256'):raise ValueError('Full response hash changed')
        payload=read_json(path)
        if (payload.get('format')!=ref['format'] or payload.get('call_id')!=cid
                or payload.get('project')!=str(project) or payload.get('project_id')!=identity.get('project_id')):
            raise ValueError('Full response identity differs')
        return {'available':True,'format':ref['format'],'sha256':ref['sha256'],'call_id':cid,
                'result':payload['result'],'scope':'Historical complete facts for this call; no automatic resubmission.'}
    if action=='layout':
        from scripts.project_layout import audit
        from scripts.artifact_registry import preflight
        return {'identity':identity, **audit(project), 'delivery_preflight':preflight(project), 'state_changed':False}
    if action=='calls':
        from .call_metrics import summarize
        return {'identity':identity, **summarize(project)}
    state=load(project)
    if action=='submission':
        from .submission import prepare
        return {'identity':identity, **prepare(project)}
    if action=='impact':
        from scripts.review_impact import compare, from_runs
        if args.get('scene') or args.get('before_scene'):
            if not args.get('scene') or not args.get('before_scene'):
                raise ValueError('Provide both before_scene and scene, or neither for the latest frozen runs')
            from scripts.scene_paths import load as load_scene
            paths=[check_input(args[k],project,roots) for k in ('before_scene','scene')]
            if any(p.stat().st_size>16*1024*1024 for p in paths):
                raise ValueError('Scene exceeds inspection limit')
            pairs=[load_scene(p,project) for p in paths]
            # Resolve every indirect input through the same project permission boundary.
            from scripts.scene_paths import prepare
            for p in paths:
                for row in prepare(read_json(p),p.parent,project)[2]:
                    check_input(row['resolved'],project,roots)
            result=compare(pairs[0][0],pairs[1][0],pairs[0][1],pairs[1][1],
                           changed_assets=args.get('changed_assets',[]))
            result['binding'].update(before_scene_sha256=sha256(paths[0]),scene_sha256=sha256(paths[1]))
        else:
            if args.get('changed_assets'):
                raise ValueError('changed_assets requires an explicit scene pair')
            if not state.get('run') or not state.get('old_runs'):
                raise ValueError('Two frozen runs are required, or provide before_scene and scene')
            result=from_runs(project,state['old_runs'][-1],state['run'])
        pages=result.pop('pages')
        return {'identity':identity,**result,'pages':pages[offset:offset+limit],
                'base_revision':state['revision'],'state_changed':False,
                'next_offset':offset+limit if offset+limit<len(pages) else None}
    if action=='edits':
        from scripts.edit_summary import summarize
        summary=summarize(project,state)
        tests=summary.pop('tests');limitations=summary.pop('limitations')
        return {'identity':identity,**summary,'tests':tests[offset:offset+limit],
                'limitations':limitations[:limit],
                'test_count':len(tests),'limitation_count':len(limitations),
                'limitations_truncated':len(limitations)>limit,
                'next_offset':offset+limit if offset+limit<len(tests) else None}
    if action=='contract':
        task=state.get('active_task')
        if not task:return {'identity':identity,'task':None,'next_action':'Read status; no current task contract'}
        check_packet(project,state,task)
        from .contracts import current_result_contract
        return {'identity':identity,'task_id':task['id'],'kind':task['kind'],'base_revision':task['base_revision'],
                'result_schema':current_result_contract(task['kind'],manager.root),
                'scope':'Current result fields only. No task consumption, visual approval or permission changes.'}
    if action=='views':
        task=state.get('active_task')
        if not task:return {'identity':identity,'items':[],'total':0,'next_offset':None}
        check_packet(project,state,task);packet=read_json(under(project,task['packet']))
        files=packet['required_view_files'];items=[]
        from PIL import Image
        for relative in files[offset:offset+limit]:
            path=under(project,relative)
            with Image.open(path) as im:size=list(im.size)
            items.append({'path':str(path),'sha256':sha256(path),'size':size,'file_bytes':path.stat().st_size,'observation':'not_recorded',
                          'detail_view_needed':max(size)>2048,
                          'view_hint':'Inspect native-size detail crops if the viewer downsizes this image.' if max(size)>2048 else None})
        from view_strategy import strategy
        return {'identity':identity,'task_id':task['id'],'view_strategy':strategy(project,packet,offset=offset,limit=limit),'items':items,'total':len(files),
                'next_offset':offset+limit if offset+limit<len(files) else None,
                'note':'Listing, thumbnails and truncated output do not record viewing. Submit only actually viewed files.'}
    if action!='scene':raise ValueError('Unknown action')
    if not args.get('scene') and not state.get('run'):
        raise ValueError('No frozen scene yet. Complete the current plan/object tasks, or provide an authorized scene path.')
    path=check_input(args['scene'],project,roots) if args.get('scene') else under(project,state['run']['dir']+'/scene.json')
    if path.stat().st_size>16*1024*1024:raise ValueError('Scene exceeds inspection limit')
    from scripts.scene_preflight import inspect as preview_scene
    from scripts.scene_paths import prepare
    path_preview=preview_scene(path,project)
    if path_preview['status']=='invalid':
        return {'identity':identity,'valid':False,'errors':path_preview['errors'][:50],
                'error_count':len(path_preview['errors']),'path_preview':path_preview,
                'scene_sha256':sha256(path),'state_changed':False,'office':'not_run',
                'not_checked':['proposed_changes','crop_scan','impact'],
                'note':'Correct the scene contract and paths before previewing object changes.'}
    scene,scene_base,_=prepare(read_json(path),path.parent,project)
    from validate_scene import validate
    errors=validate(scene,scene_base,project_root=scene_base);changes=args.get('changes',[]);updated=copy.deepcopy(scene)
    objects=[o for s in updated.get('slides',[]) for o in walk_objects(s.get('objects',[]))]
    by_id={}
    for obj in objects:by_id.setdefault(obj['id'],[]).append(obj)
    for change in changes:
        matches=by_id.get(change['object_id'],[])
        if len(matches)!=1:raise ValueError('Expected one complete object ID: '+change['object_id'])
        fields=change['set']
        if any(k not in {'bbox','text','style','rotation','points','commands'} for k in fields):
            raise ValueError('Only explicit geometry, text and style changes are supported')
        matches[0].update(copy.deepcopy(fields))
    if changes:errors=validate(updated,scene_base,project_root=scene_base)
    warnings=[];image_index=0
    if not errors:
        from evidence_contract import logical_bounds
        for slide in updated['slides']:
            objs=list(walk_objects(slide['objects']))
            ids={o['id'] for o in objs}
            for oid in slide.get('review_requirements',{}).get('local_objects',[]):
                if oid not in ids:errors.append(slide['id']+': dangling local_objects reference '+oid)
            texts=[(n,o) for n,o in enumerate(objs) if o['kind']=='text']
            for n,obj in enumerate(objs):
                if obj['kind']!='image':
                    if obj['kind'] in {'shape','path'} and obj.get('style',{}).get('fill') not in (None,'none','transparent'):
                        a=logical_bounds(obj)
                        for j,text in texts:
                            b=logical_bounds(text)
                            if n>j and min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]):
                                warnings.append({'kind':'possible_text_occlusion','slide_id':slide['id'],
                                    'object_id':obj['id'],'text_id':text['id'],
                                    'roi':[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])]})
                    continue
                image_index+=1
                warnings.append({'kind':'crop_text_check','slide_id':slide['id'],'object_id':obj['id'],
                                 'note':'Inspect the source crop and final render for baked-in text, page numbers and edge remnants. OCR not performed.'})
                if args.get('scan_crops') and offset<=image_index-1<offset+limit:
                    from .raster_preflight import text_candidates
                    asset=check_input(str(scene_base/obj['asset']),project,roots)
                    for roi in text_candidates(asset):
                        warnings.append({'kind':'possible_baked_text','object_id':obj['id'],'asset':str(asset),
                                         'source_pixel_roi':roi,'note':'Glyph-row heuristic; inspect visually. May also detect diagrams or texture.'})
                a=logical_bounds(obj)
                for j,text in texts:
                    b=logical_bounds(text)
                    if n>j and min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]):
                        warnings.append({'kind':'possible_text_occlusion','slide_id':slide['id'],'object_id':obj['id'],'text_id':text['id'],'roi':[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])]})
    impact=[]
    review_impact=None
    if changes and not errors:
        from scripts.review_impact import compare as compare_impact
        review_impact=compare_impact(scene,updated,scene_base,scene_base)
        from workflow_recovery import context as regional_context
        from workflow_store import WorkflowError
        changed_ids={c['object_id'] for c in changes}
        pages={p['id']:p for p in state['pages']}
        for old,new in zip(scene['slides'],updated['slides']):
            ids=changed_ids & {o['id'] for o in walk_objects(new['objects'])}
            if not ids or old==new:continue
            page=pages.get(new['id'])
            row={'slide_id':new['id'],'changed_object_ids':sorted(ids),
                 'visual_review':'requires_new_observation','regional_context':'unavailable',
                 'next_action':'explicit_page_replanning',
                 'unaffected_pages':'Only verified identical scene, assets and render may reuse recorded observations.'}
            if page is not None:
                try:
                    recovered=regional_context(project,state,page,new)
                    row.update(regional_context='verified',planning_basis=recovered['planning_basis'],
                               next_action='check_current_patch_contract',
                               candidate_regions=[r['id'] for r in recovered['plan']['regions']
                                    if any(oid.startswith(new['id']+'.'+r['id']+'.') for oid in ids)])
                except WorkflowError as exc:
                    row['reason']=str(exc)
                    row['recovery']={'tool':'rebuild_revise','slide':new['id'],
                                     'note':'Explicit page-level replanning keeps old versions; do not edit workflow state.'}
            impact.append(row)
    return {'identity':identity,'valid':not errors,'errors':errors[:50],'error_count':len(errors),
            'warnings':warnings[offset:offset+limit],'warning_count':len(warnings),
            'crop_findings':[w for w in warnings if w['kind']=='possible_baked_text'],
            'crop_scan':{'offset':offset,'limit':limit,'images':image_index,'next_offset':offset+limit if offset+limit<image_index else None} if args.get('scan_crops') else None,
            'next_offset':offset+limit if offset+limit<len(warnings) else None,
            'changes':changes,'scene_sha256':sha256(path),'state_changed':False,'office':'not_run',
            'path_preview':path_preview,
            'impact':impact,
            'review_impact':review_impact,
            'note':'Preflight only. Apply the explicit changes through managed patch or scene replacement. No evidence or references are invented.'}
