"""Managed project evidence adapters. No source overwrites or adoption."""
from __future__ import annotations
import json
from pathlib import Path
import uuid
from contextlib import nullcontext
from common import sha256,write_json,read_json,walk_objects

def read_properties(project,args):
    from toolbox_manager.policy import plain_path
    from local_edit import office_roundtrip,shapes_by_name
    from native_nodes import summary
    from pptx import Presentation
    from workflow_store import locked
    src=plain_path(project/args['pptx'])
    if not src.is_relative_to(project) or src.suffix.lower()!='.pptx' or not src.is_file():
        raise ValueError('Readback input must be a PPTX inside the authorized project')
    if sha256(src)!=args['pptx_sha256']:raise ValueError('Stale candidate hash')
    targets={(v['slide']-1,v['id']) for v in args['targets']}
    if len(targets)!=len(args['targets']):raise ValueError('Duplicate readback target')
    native=shapes_by_name(Presentation(src))
    if not targets<=native.keys():raise ValueError('Readback target missing or ambiguous')
    with locked(project) if (project/'workflow/state.json').is_file() else nullcontext():
        if sha256(src)!=args['pptx_sha256']:raise ValueError('Stale candidate hash after acquiring project lock')
        dest=plain_path(project/'assets/native-readback'/uuid.uuid4().hex)
        dest.mkdir(parents=True,exist_ok=False)
        before=sha256(src)
        office_roundtrip(src,dest/'saved-copy.pptx',dest/'office-readback.json',native=True)
        receipt=read_json(dest/'office-readback.json')
        selected=[r for r in receipt['objects'] if (r['slide']-1,r['name']) in targets]
        for row in selected:
            row['children']=[r['name'] for r in receipt['objects'] if r['slide']==row['slide'] and r['parent']==row['name']]
        if len(selected)!=len(targets):raise ValueError('Actual Office target identity differs')
        keep={f'{si+1}/{name}' for si,name in targets}
        geometry={k:v for k,v in summary(dest/'saved-copy.pptx').items() if k in keep}
        report={'format':'native-properties/1','status':'recorded','source_sha256':before,
                'source_unchanged':sha256(src)==before,'office_version':receipt['office_version'],
                'objects':selected,'native_geometry':geometry,'directory':str(dest),
                'pptx':str(dest/'saved-copy.pptx'),'visual_review':'not_assessed',
                'edit_test':'not_performed','unsupported':'Each property records unknown or not_applicable independently'}
        write_json(dest/'properties.json',report)
        if not report['source_unchanged']:raise ValueError('Source changed during readback')
        return report

def boolean_trials(project,args):
    from workflow_store import load,under
    from local_workflow import region_scope
    from native_topology import preflight
    if args.get('primary',args['inputs'][0])!=args['inputs'][0]:
        raise ValueError('primary must be the first ordered input')
    state=load(project);run=state.get('run')
    if state['status']=='delivered' or not run or not run.get('candidate'):
        raise ValueError('Boolean trials require current undelivered candidate; use governed revision first')
    page,region=region_scope(state,args['slide'],args['region'])
    scene_path=under(project,run['dir']+'/scene.json');source=under(project,run['candidate']['file'])
    scene=read_json(scene_path)
    target=next(s for s in scene['slides'] if s['id']==args['slide'])
    prefix=args['slide']+'.'+args['region']+'.'
    allowed={o['id'] for o in walk_objects(target['objects']) if o['id'].startswith(prefix)}
    requests=[]
    for action in args.get('actions',['union','combine','intersect','subtract','fragment']):
        change={'op':'native.topology','action':action,'inputs':args['inputs'],
                'primary':args['inputs'][0],'style_source':args['inputs'][0],
                'output_prefix':args['prefix']+'-'+action,'empty':'reject'}
        preflight(scene_path,source,args['slide'],allowed,change)
        requests.append({'tool':'rebuild_patch','arguments':{
            'project':str(project),'operation_id':args['prefix']+'-'+action,
            'base_revision':state['revision'],'scene_sha256':sha256(scene_path),'pptx_sha256':sha256(source),
            'slide':args['slide'],'region':args['region'],'changes':[change],'reason':args['reason']}})
    return {'format':'boolean-trials-plan/1','requests':requests,'executed':False,
            'context_id':'Fill from current toolbox_project_bind for every rebuild call',
            'review_route':'Execute independent patches from this baseline; compare each; adopt at most the chosen result',
            'budget':'Existing project trial budget applies; no automatic increase',
            'scope':'All operations keep original operands in baseline; no operation modifies the source'}
