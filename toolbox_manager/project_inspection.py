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
    state=load(project)
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
        return {'identity':identity,'task_id':task['id'],'view_strategy':strategy(project,packet),'items':items,'total':len(files),
                'next_offset':offset+limit if offset+limit<len(files) else None,
                'note':'Listing, thumbnails and truncated output do not record viewing. Submit only actually viewed files.'}
    if action!='scene':raise ValueError('Unknown action')
    if not args.get('scene') and not state.get('run'):
        raise ValueError('No frozen scene yet. Complete the current plan/object tasks, or provide an authorized scene path.')
    path=check_input(args['scene'],project,roots) if args.get('scene') else under(project,state['run']['dir']+'/scene.json')
    if path.stat().st_size>16*1024*1024:raise ValueError('Scene exceeds inspection limit')
    scene=read_json(path)
    from validate_scene import validate
    errors=validate(scene,path.parent);changes=args.get('changes',[]);updated=copy.deepcopy(scene)
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
    if changes:errors=validate(updated,path.parent)
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
                    asset=check_input(str(path.parent/obj['asset']),project,roots)
                    for roi in text_candidates(asset):
                        warnings.append({'kind':'possible_baked_text','object_id':obj['id'],'asset':str(asset),
                                         'source_pixel_roi':roi,'note':'Glyph-row heuristic; inspect visually. May also detect diagrams or texture.'})
                a=logical_bounds(obj)
                for j,text in texts:
                    b=logical_bounds(text)
                    if n>j and min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]):
                        warnings.append({'kind':'possible_text_occlusion','slide_id':slide['id'],'object_id':obj['id'],'text_id':text['id'],'roi':[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])]})
    impact=[]
    if changes and not errors:
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
            'impact':impact,
            'note':'Preflight only. Apply the explicit changes through managed patch or scene replacement. No evidence or references are invented.'}
