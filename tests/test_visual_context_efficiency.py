"""Visual-context contracts using synthetic images, not visual approval."""
import copy
import shutil
from pathlib import Path

import pytest
from PIL import Image
from test_workflow import make_ready, ref, respond, region_payload, assertion, fake_office, complete_review_tasks
from common import read_json, write_json, sha256
from workflow_store import load, WorkflowError
import workflow as wf


def replacement(tmp_path, project):
    state = load(project)
    out = tmp_path/'replacement'
    shutil.copytree(project/state['run']['dir'], out)
    return out/'scene.json'


def test_identical_source_is_retained_and_office_still_required(tmp_path):
    project, _ = make_ready(tmp_path, local=True)
    old = copy.deepcopy(load(project)['pages'][0]['source_review'])
    wf.replace_scene(project, replacement(tmp_path, project), 'Identical fixture')
    assert load(project)['pages'][0]['source_review'] == old
    task = wf.next_task(project)
    assert task['task']['kind'] == 'office_render'
    assert task['retained_source_reviews']['slide_ids'] == ['slide-001']


@pytest.mark.parametrize('field', ['text', 'geometry', 'style', 'connector', 'canvas'])
def test_changed_content_requires_source_review(tmp_path, field):
    project, _ = make_ready(tmp_path, local=True)
    path = replacement(tmp_path, project)
    scene = read_json(path)
    objects = scene['slides'][0]['objects']
    if field == 'text': objects[0]['text'] = 'CHANGED 123'
    if field == 'geometry': objects[0]['bbox'][0] += 1
    if field == 'style': objects[0]['style']['color'] = 'FF0000'
    if field == 'connector': objects[1]['points'][1][0] -= 5
    if field == 'canvas':
        scene['canvas']['width'] *= 2
        scene['canvas']['height'] *= 2
    write_json(path, scene)
    wf.replace_scene(project, path, 'Changed fixture')
    assert load(project)['pages'][0]['source_review'] is None
    assert wf.next_task(project)['task']['kind'] == 'source_review'


def test_legacy_observation_is_readable_but_not_reused(tmp_path, monkeypatch):
    import source_review_reuse
    real_binding = source_review_reuse.binding
    monkeypatch.setattr(source_review_reuse, 'binding', lambda *args: None)
    project, _ = make_ready(tmp_path)
    monkeypatch.setattr(source_review_reuse, 'binding', real_binding)
    wf.replace_scene(project, replacement(tmp_path, project), 'Legacy fixture')
    assert wf.next_task(project)['task']['kind'] == 'source_review'


@pytest.mark.parametrize('target', ['record', 'packet'])
def test_source_provenance_cannot_be_rewritten(tmp_path, target):
    project, _ = make_ready(tmp_path)
    state = load(project)
    record_path = project/state['pages'][0]['source_review']['file']
    record = read_json(record_path)
    path = record_path if target == 'record' else project/'workflow/tasks'/record['task_id']/'packet.json'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(WorkflowError): load(project)


def test_large_planning_overview_keeps_original_coordinates_and_detail(tmp_path):
    project = tmp_path/'project'
    wf.start(project, [ref(tmp_path, size=(3200, 1800))])
    task = wf.next_task(project)
    packet = read_json(task['task']['packet'])
    assert packet['context']['reference_size'] == [3200, 1800]
    assert packet['context']['overview_size'] == [1600, 900]
    path = Path(task['task']['must_view_files'][0])
    assert Image.open(path).size == (1600, 900)
    before = (project/'workflow/state.json').read_bytes()
    assert wf.next_task(project)['task'] == task['task']
    assert (project/'workflow/state.json').read_bytes() == before
    respond(project, {'regions':[{'id':'one','bbox':[0,0,3200,1800],'role':'content','summary':'Fixture'}]})
    local = wf.next_task(project)
    assert local['task']['view_strategy']['scope'] == 'local'
    assert Image.open(local['task']['must_view_files'][0]).size == (3200, 1800)
    respond(project, region_payload())
    review = wf.next_task(project)
    assert Image.open(review['task']['must_view_files'][0]).size == (3200, 1800)
    assert review['task']['view_strategy']['required_file_bytes'] == sum(Path(p).stat().st_size for p in review['task']['must_view_files'])


def test_default_comparison_keeps_original_pixels_without_duplicate_crops(tmp_path):
    from compare_images import compare, _labelled_side
    import numpy as np
    image = Image.fromarray(np.random.default_rng(7).integers(0,256,(36,64,3),dtype=np.uint8))
    path = tmp_path/'source.png'; image.save(path)
    out = tmp_path/'comparison'
    result = compare(path,path,out,[{'id':'roi','bbox':[4,5,24,25]}])
    assert len(list(out.glob('*.png'))) == 6
    row = result['regions'][1]
    assert row['display_scale'] == 1 and row['overlay_size'] == [20,20]
    with Image.open(out/row['overlay']) as actual:
        assert actual.tobytes() == image.crop((4,5,24,25)).tobytes()
    with Image.open(out/row['side_by_side']) as actual:
        assert actual.tobytes() == _labelled_side(image.crop((4,5,24,25)),image.crop((4,5,24,25))).tobytes()
    explicit = compare(path,path,tmp_path/'legacy',[{'id':'roi','bbox':[4,5,24,25]}],region_scale=2,include_source_crops=True)
    assert len(list((tmp_path/'legacy').glob('*.png'))) == 10
    assert explicit['regions'][1]['overlay_size'] == [40,40]


def test_only_changed_page_requires_new_source_observation(tmp_path):
    project=tmp_path/'project'
    wf.start(project,[ref(tmp_path,name='a.png'),ref(tmp_path,name='b.png')])
    for _ in range(2):
        respond(project,{'regions':[{'id':'one','bbox':[0,0,640,360],'role':'content','summary':'Fixture'}]})
    for _ in range(2):respond(project,region_payload())
    for _ in range(2):respond(project,assertion)
    assert wf.next_task(project)['task']['kind']=='office_render'
    path=replacement(tmp_path,project);scene=read_json(path)
    scene['slides'][0]['objects'][0]['text']='NEW';write_json(path,scene)
    wf.replace_scene(project,path,'One changed page')
    state=load(project)
    assert state['pages'][0]['source_review'] is None
    assert state['pages'][1]['source_review_reuse']
    assert wf.next_task(project)['task']['target']['slide_id']=='slide-001'
    respond(project,assertion)
    assert wf.next_task(project)['task']['kind']=='office_render'


@pytest.mark.parametrize('change',['text','occlusion','relationship'])
def test_local_reuse_keeps_only_unaffected_coverage(tmp_path,change):
    project,_=make_ready(tmp_path,two_regions=True)
    # Explicitly require both regions in this fixture.
    state=load(project)
    for region in state['pages'][0]['plan']['regions']:region['local_review']=True
    # Establish a fresh source observation after the fixture's coverage change.
    state['pages'][0]['source_review']=None
    state['run']=None;state['active_task']=None
    write_json(project/'workflow/state.json',state)
    respond(project,assertion)
    task=wf.next_task(project)
    respond(project,{'receipt':str(fake_office(tmp_path,project))},task)
    complete_review_tasks(project)
    path=replacement(tmp_path,project);scene=read_json(path)
    first=scene['slides'][0]['objects'][0]
    if change=='text':first['text']='NEW'
    if change=='occlusion':first['bbox'][0]=340
    if change=='relationship':
        connection=copy.deepcopy(first)
        connection.pop('text',None);connection.pop('bbox',None)
        connection.update(id='new-connection',kind='line',editability='shape',points=[[10,100],[600,100]],style={'line':'000000'})
        scene['slides'][0]['objects'].append(connection)
        scene['slides'][0]['review_requirements']['relationship_objects'].append('new-connection')
    write_json(path,scene);wf.replace_scene(project,path,'Scoped change')
    respond(project,assertion);task=wf.next_task(project)
    second=tmp_path/'second';second.mkdir()
    respond(project,{'receipt':str(fake_office(second,project))},task)
    current=wf.next_task(project)
    assert current['task']['kind']=='review_full'
    keys=set(load(project)['run']['reviews'])
    assert 'full:1' not in keys and 'local:1:roi-001' not in keys
    if change=='text':assert 'local:1:roi-002' in keys
    else:assert 'local:1:roi-002' not in keys


def test_asset_bytes_and_explicit_revision_invalidate_source(tmp_path):
    from source_review_reuse import binding
    project,_=make_ready(tmp_path)
    state=load(project);page=copy.deepcopy(state['pages'][0])
    page['fragments']['one']['objects'].append({'id':'photo','kind':'image','asset':'asset.png','bbox':[0,100,30,30]})
    Image.new('RGB',(30,30),'red').save(project/'asset.png')
    before=binding(project,state,page)
    Image.new('RGB',(30,30),'blue').save(project/'asset.png')
    assert binding(project,state,page)!=before
    wf.revise(project,'slide-001','one','Explicit redo')
    assert load(project)['pages'][0]['source_review'] is None


@pytest.mark.parametrize('status',['needs_changes','blocked'])
def test_nonpassing_observation_never_reused(tmp_path,status):
    from source_review_reuse import retain
    project,_=make_ready(tmp_path)
    state=load(project);old=copy.deepcopy(state['pages'][0]);new=copy.deepcopy(old)
    old['source_review']['status']=status;new['source_review']=None
    assert retain(project,state,old,new,state['canvas']) is False
    assert new['source_review'] is None
