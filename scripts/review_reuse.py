"""Reuse bound observations for unchanged pages or unchanged local coverage."""
import copy
import hashlib
import json
from zipfile import ZipFile
from common import read_json, sha256, resolve_asset, walk_objects
from workflow_store import under, WorkflowError


def signature(project, run, *, local=False):
    base=under(project,run['dir']+'/scene.json').parent
    for name,digest in run['frozen'].items():
        if sha256(under(base,name))!=digest:raise WorkflowError('reuse_changed','Prior frozen input changed')
    for name in ('candidate','render','comparison'):
        rec=run[name]
        if sha256(under(project,rec['file']))!=rec['sha256']:raise WorkflowError('reuse_changed','Review dependency changed')
    scene=read_json(base/'scene.json')
    with ZipFile(under(project,run['candidate']['file'])) as z:
        # Include themes, masters, layouts, embedded assets and presentation settings.
        shared={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                if not n.startswith(('ppt/slides/','docProps/'))}
    global_data={k:v for k,v in scene.items() if k!='slides'}
    region_pages=read_json(base/'regions.json')['slides'] if local else []
    values={}
    for i,slide in enumerate(scene['slides'],1):
        data=copy.deepcopy(slide)
        if data.get('reference'):data['reference']=sha256(resolve_asset(base,data['reference']))
        for obj in walk_objects(data['objects']):
            if obj.get('asset'):obj['asset']=sha256(resolve_asset(base,obj['asset']))
        if not local:
            values[i]=hashlib.sha256(json.dumps([global_data,shared,data],sort_keys=True).encode()).hexdigest()
            continue
        from evidence_contract import logical_bounds, review_mapping, required_review
        from PIL import Image
        with Image.open(resolve_asset(base,slide['reference'])) as image:size=list(image.size)
        mapping=review_mapping(scene,slide,size)
        relations=set(required_review(slide)['relationship_objects'])
        regions=next((p['regions'] for p in region_pages if p['index']==i),[])
        for region in regions:
            box=region['bbox'];selected=[]
            for position,obj in enumerate(walk_objects(data['objects'])):
                bounds=logical_bounds(obj)
                bounds=[bounds[0]*mapping['scale_x']+mapping['offset_x'],bounds[1]*mapping['scale_y']+mapping['offset_y'],
                        bounds[2]*mapping['scale_x']+mapping['offset_x'],bounds[3]*mapping['scale_y']+mapping['offset_y']]
                intersects=bounds[0]<=box[2] and bounds[2]>=box[0] and bounds[1]<=box[3] and bounds[3]>=box[1]
                if intersects or obj['id'] in relations or obj['id'] in region['object_ids']:
                    selected.append([position,obj])
            scoped={k:v for k,v in data.items() if k!='objects'}
            values[(i,region['id'])]=hashlib.sha256(json.dumps(
                [global_data,shared,scoped,region,selected],sort_keys=True).encode()).hexdigest()
    return values


def eligible(project, old, new):
    from workflow_evidence import comparison_views
    a=signature(project,old);b=signature(project,new)
    av=comparison_views(project,old);bv=comparison_views(project,new)
    unchanged={i for i in a if a[i]==b.get(i) and sha256(av['full_paths'][i])==sha256(bv['full_paths'][i])}
    for i in list(unchanged):
        left={k:v for k,v in av['local_paths'].items() if k[0]==i}
        right={k:v for k,v in bv['local_paths'].items() if k[0]==i}
        if set(left)!=set(right) or any(left[k]['object_ids']!=right[k]['object_ids'] or
                sha256(left[k]['file'])!=sha256(right[k]['file']) for k in left):unchanged.remove(i)
    al=signature(project,old,local=True);bl=signature(project,new,local=True)
    unchanged_locals={key for key,value in al.items() if value==bl.get(key)
                      and key in av['local_paths'] and key in bv['local_paths']
                      and sha256(av['local_paths'][key]['file'])==sha256(bv['local_paths'][key]['file'])}
    result={}
    for key,ref in old.get('reviews',{}).items():
        path=under(project,ref['file'])
        if sha256(path)!=ref['sha256']:raise WorkflowError('reuse_changed','Observation changed')
        record=read_json(path);r=record['result']
        if record['kind'] not in ('review_full','review_local'):continue
        target=record['target']
        if target['index'] not in unchanged and not (record['kind']=='review_local' and
                (target['index'],target['region_id']) in unchanged_locals):continue
        passed=all(c['status']=='passed' for c in r['checks'].values()) if record['kind']=='review_full' else r['status']=='passed'
        packet=under(project,'workflow/tasks/'+record['task_id']+'/packet.json')
        if sha256(packet)!=record['packet_sha256']:raise WorkflowError('reuse_changed','Observation packet changed')
        p=read_json(packet)
        for item in p['input_files']:
            if sha256(under(project,item['file']))!=item['sha256']:raise WorkflowError('reuse_changed','Observed input changed')
        if passed:result[key]=copy.deepcopy(ref)
    return result


def restore(project,state):
    run=state['run']
    if not state.get('old_runs'):return
    records={};sources={};seen=set(run.get('reviews',{}))
    for old in reversed(state['old_runs']):
        if not old.get('reviews') or not all(old.get(k) for k in ('comparison','render','candidate')):continue
        refs={k:v for k,v in eligible(project,old,run).items() if k not in seen}
        # A newer negative observation cannot be replaced by an older positive one.
        seen.update(old['reviews'])
        if refs:records.update(refs);sources[old['id']]=list(refs)
    if records:
        run['reviews'].update(records)
        run['reused_observations']={'source_run':next(iter(sources)),'sources':sources,'records':records,
            'scope':'Unchanged pages or local coverage with identical dependencies and Office views. Changed pages still require full-page review; no new visual verdicts.'}


def verify(project,state):
    run=state['run'];reuse=run.get('reused_observations')
    if not reuse:return
    for source,keys in reuse.get('sources',{reuse['source_run']:list(reuse['records'])}).items():
        old=next((r for r in state.get('old_runs',[]) if r['id']==source),None)
        if old is None:raise WorkflowError('reuse_changed','Source run missing')
        refs=eligible(project,old,run)
        if any(refs.get(k)!=reuse['records'][k] or run['reviews'].get(k)!=reuse['records'][k] for k in keys):
            raise WorkflowError('reuse_changed','Observation dependencies changed; new review required')
