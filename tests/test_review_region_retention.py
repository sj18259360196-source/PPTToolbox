"""Semantic review retention and task guidance; no visual/Office certification."""
import copy
import shutil
from types import SimpleNamespace

import pytest
from test_workflow import ref, respond, region_payload, assertion
from test_stability_recovery import fixture
from common import read_json, write_json, sha256
from evidence_contract import required_review, validate_local_coverage
from workflow_store import load, WorkflowError
from workflow_recovery import context, review_context
from workflow_scene import auto_regions
import workflow as wf


def regional_project(tmp_path):
    project=tmp_path/'project'
    wf.start(project,[ref(tmp_path)])
    respond(project,{'regions':[
        {'id':'one','bbox':[0,0,320,360],'role':'content','summary':'First region','local_review':True},
        {'id':'two','bbox':[320,0,640,360],'role':'content','summary':'Second region','local_review':True},
    ],'notes':'Inspect the main component first; use a similar font.'})
    respond(project,region_payload('ONE',True))
    respond(project,region_payload('TWO',True))
    respond(project,assertion)
    assert wf.next_task(project)['task']['kind']=='office_render'
    return project


@pytest.mark.parametrize('change',['geometry','text'])
def test_replace_and_rebuild_keep_semantic_regions_and_new_evidence(tmp_path,change):
    project=regional_project(tmp_path);before=load(project)
    original=project/before['run']['dir']
    old_hashes={p:sha256(p) for p in original.rglob('*') if p.is_file()}
    old_packets={p:sha256(p) for p in (project/'workflow/tasks').rglob('packet.json')}
    replacement=tmp_path/'replacement';shutil.copytree(original,replacement)
    path=replacement/'scene.json';scene=read_json(path)
    obj=scene['slides'][0]['objects'][0]
    if change=='geometry':obj['bbox'][0]+=100
    else:obj['text']='NEW TEXT'
    write_json(path,scene)
    wf.replace_scene(project,path,'Scoped synthetic revision')
    state=load(project);page=state['pages'][0]
    assert len(page['review_plan']['regions'])==2
    assert page['source_review'] is None and state['run'] is None
    assert (page['plan'] is None)==(change=='geometry')
    assert 'production_notes' in read_json(wf.next_task(project)['task']['packet'])['context']
    respond(project,assertion)
    assert wf.next_task(project)['task']['kind']=='office_render'
    state=load(project);run=project/state['run']['dir']
    regions=read_json(run/'regions.json')['slides'][0]['regions']
    assert len(regions)==2
    covered={oid for r in regions for oid in r['object_ids']}
    assert covered==set(required_review(scene['slides'][0])['local_objects'])
    if change=='geometry':assert regions[0]['bbox'][2]>320
    assert state['run']['reviews']=={}
    assert all(sha256(p)==digest for p,digest in {**old_hashes,**old_packets}.items())


def test_new_and_unbound_objects_remain_covered_without_write_authority(tmp_path):
    project=regional_project(tmp_path);state=load(project);page=state['pages'][0]
    scene=read_json(project/state['run']['dir']/'scene.json');slide=scene['slides'][0]
    for oid in ['slide-001.one.added','unbound.added']:
        obj=copy.deepcopy(slide['objects'][0]);obj['id']=oid;obj['bbox']=[30,100,50,30]
        slide['objects'].append(obj);slide['review_requirements']['local_objects'].append(oid)
    page={**page,**review_context(project,state,page,slide),'plan':None,'imported_slide':slide,'fragments':{}}
    regions=auto_regions(scene,[page])['slides'][0]['regions']
    assert len(regions)==3
    assert 'slide-001.one.added' in regions[0]['object_ids']
    assert regions[-1]['object_ids']==['unbound.added']
    validate_local_coverage(scene,slide,page['size'],regions)
    with pytest.raises(WorkflowError,match='geometry'):context(project,state,page,slide)


@pytest.mark.parametrize('change',['canvas','mapping','reference','no_plan','invalidated','packet','record','run'])
def test_review_retention_rejects_invalid_basis(fixture,change):
    p,s,page,slide=fixture
    if change=='canvas':s['canvas']['width']+=1
    elif change=='mapping':slide['review_mapping']['offset_x']=1
    elif change=='reference':page['sha256']='0'*64
    elif change=='no_plan':s['accepted']=[]
    elif change=='invalidated':s['history']=[{'revision':5,'event':'region_reopened','detail':{'slide_id':'slide-001','region_id':None}}]
    else:
        paths={'packet':'workflow/tasks/task-000001/packet.json','record':'workflow/results/task-000001.json','run':'runs/run-0001/scene.json'}
        (p/paths[change]).write_text('{}',encoding='utf-8')
    with pytest.raises((WorkflowError,ValueError)):review_context(p,s,page,slide)


def test_full_replan_drops_retained_review_regions(fixture):
    p,s,page,slide=fixture
    page.update(review_context(p,s,page,slide));write_json(p/'workflow/state.json',s)
    wf.revise(p,page['id'],None,'Explicit full replan')
    assert 'review_plan' not in load(p)['pages'][0]


def test_guidance_and_plan_notes_reach_tasks_without_experience_permission(tmp_path,monkeypatch):
    policy=SimpleNamespace(allowed=set(),require=lambda *names:None,result_paths=lambda result,kind:dict(result))
    monkeypatch.setattr(wf,'_managed_policy',policy)
    project=tmp_path/'project';wf.start(project,[ref(tmp_path)])
    task=wf.next_task(project);packet=read_json(task['task']['packet'])
    assert task['task']['kind']=='page_plan'
    assert 'production_guidance' in packet['context'] and 'assistance' not in packet['context']
    notes='Prioritize component contours; similar available font.'
    respond(project,{'regions':[{'id':'one','bbox':[0,0,640,360],'role':'content','summary':'Simple content'}],'notes':notes},task)
    task=wf.next_task(project);packet=read_json(task['task']['packet'])
    assert task['task']['kind']=='region_objects'
    assert packet['context']['production_notes']==notes
    assert 'native_first' in packet['context']['production_guidance']
    assert read_json(task['task']['response_template'])['result']['objects']==[]


def test_legacy_imported_valid_plan_without_fragments_keeps_groups(tmp_path):
    project=regional_project(tmp_path);state=load(project);page=state['pages'][0]
    scene=read_json(project/state['run']['dir']/'scene.json')
    page.update(imported_slide=scene['slides'][0],fragments={})
    regions=auto_regions(scene,[page])['slides'][0]['regions']
    assert len(regions)==2 and all(len(r['object_ids'])==2 for r in regions)


def test_key_regions_cover_text_even_when_import_omits_explicit_requirements(tmp_path):
    project=regional_project(tmp_path);state=load(project);page=state['pages'][0]
    scene=read_json(project/state['run']['dir']/'scene.json');slide=scene['slides'][0]
    slide.pop('review_requirements')
    page.update(review_context(project,state,page,slide));page.update(imported_slide=slide,fragments={})
    regions=auto_regions(scene,[page])['slides'][0]['regions']
    assert len(regions)==2
    assert {oid for r in regions for oid in r['object_ids']}=={o['id'] for o in slide['objects']}
