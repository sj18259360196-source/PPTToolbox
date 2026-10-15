"""Advisory boundaries and managed paths. Synthetic receipts are NOT Office proof."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))
from common import read_json, write_json, sha256
from native_practice import CANVAS
from review_impact import compare, from_runs
import text_calibration as calibration
from test_managed_rebuild import runtime, enabled
from toolbox_manager.execution import registered_context
from toolbox_manager.policy import PolicyDenied
from toolbox_manager.project_inspection import inspect
import workflow as wf


def text(oid='label', value='Sample', role='content', box=None, **style):
    return {'id':oid,'kind':'text','role':role,'bbox':box or [40,40,400,70],
            'text':value,'style':{'font':'Arial','font_size_pt':20,**style},
            'editability':'text','evidence':{'status':'synthetic','note':'Controlled fixture'}}


def shape(oid='block', box=None):
    return {'id':oid,'kind':'shape','geometry':'rect','role':'content',
            'bbox':box or [40,180,70,70],'style':{'fill':'112233'},
            'editability':'shape','evidence':{'status':'synthetic','note':'Controlled fixture'}}


def scene(objects=None, sid='page'):
    return {'version':'1.0','canvas':copy.deepcopy(CANVAS),
            'slides':[{'id':sid,'objects':objects if objects is not None else [text()]}]}


@pytest.fixture
def environment(monkeypatch):
    value={'available':True,'sha256':'e'*64,'requested':['Arial']}
    monkeypatch.setattr(calibration,'environment',lambda fonts:copy.deepcopy(value))
    return value


def synthetic_calibration(tmp, environment, objects=None):
    source=tmp/'scene.json';write_json(source,scene(objects))
    plan_dir=tmp/'plan';calibration.plan(source,plan_dir)
    plan=read_json(plan_dir/'plan.json');office=tmp/'synthetic-office';office.mkdir()
    slides=[];bounds=[]
    for t in plan['targets']:
        img=office/f"slide-{t['index']:03}.png";Image.new('RGB',(960,540),'white').save(img)
        slides.append({'index':t['index'],'file':img.name,'sha256':sha256(img),'width':960,'height':540})
        obj=t['object'];x,y,w,h=[v*.75 for v in obj['bbox']]
        run={'text':calibration._text(obj),'office_font_size_pt':obj['style']['font_size_pt'],
             'baseline_offset_fraction':0,'baseline_shift_pt':0,'font':'Arial'}
        bounds.append({'slide':t['index'],'id':t['sample_id'],'box_pt':[x,y,w,h],
            'bound_pt':[x,y,w-3,h-3],'rotation':0,
            'calibration':{'format':'office-text-calibration/1','text':calibration._text(obj),
                'auto_size':0,'errors':[],'truncated':False,'runs':[run],
                'lines':[{'index':1,'bound_pt':[x,y,w-3,h-3],'bound_height_pt':h-3,'baseline_y_pt':None}]}})
    receipt=office/'office-render.json'
    write_json(receipt,{'status':'passed','renderer':'Microsoft PowerPoint','scope':'SYNTHETIC TEST ONLY',
                       'pptx_sha256':sha256(plan_dir/'specimens.pptx'),'slides':slides,'text_bounds':bounds,'canvas_pt':[720,405]})
    report=tmp/'measurement.json';calibration.evaluate(plan_dir,office,report)
    return source,plan_dir,office,report


def test_representatives_preserve_text_and_do_not_add_per_page_measurements(tmp_path,environment):
    source=tmp_path/'source.json'
    title=text('title','Heading','header',font_size_pt=32)
    body=text('body','A longer body example',box=[40,160,700,170],wrap=True)
    mixed=text('mixed','中文 Test 2026',box=[40,380,400,70])
    data=scene([title,body,mixed]);data['slides'] += [{**copy.deepcopy(data['slides'][0]),'id':f'p{i}'} for i in range(1,12)]
    write_json(source,data);before=source.read_bytes()
    output=tmp_path/'plan';result=calibration.plan(source,output)
    saved=read_json(output/'plan.json');specimen=read_json(output/'specimens.scene.json')
    assert result['samples']==3 and result['style_siblings']==33
    assert [t['category'] for t in saved['targets']]==['title','body','mixed_language']
    assert len(specimen['slides'])==3 and source.read_bytes()==before
    assert [s['objects'][0]['style'] for s in specimen['slides']]==[o['style'] for o in (title,body,mixed)]
    assert result['visual_review']=='pending' and not result['automatic_changes']


def test_exact_reuse_skips_office_but_new_longest_representative_is_measured(tmp_path,environment):
    source,_,_,report=synthetic_calibration(tmp_path,environment)
    result=calibration.plan(source,tmp_path/'reuse',reuse=report)
    assert result['status']=='reuse_only' and result['reused']==1 and not (tmp_path/'reuse/specimens.pptx').exists()
    data=read_json(source);data['slides'][0]['objects'].append(text('different','Different text'))
    write_json(source,data)
    calibration.plan(source,tmp_path/'new-page',reuse=report)
    plan=read_json(tmp_path/'new-page/plan.json')
    assert len(plan['reused'])==1 and [t['id'] for t in plan['targets']]==['different']
    assert plan['targets'][0]['representative_for']==['body']


@pytest.mark.parametrize('change',['environment','mixed','low_confidence','geometry','canvas'])
def test_uncertain_or_changed_inputs_remeasure(tmp_path,environment,change):
    source,_,office,report=synthetic_calibration(tmp_path,environment)
    data=read_json(source)
    if change=='environment':environment['sha256']='f'*64
    elif change=='mixed':
        obj=data['slides'][0]['objects'][0];obj['runs']=[{'text':obj.pop('text')+' mix'}]
    elif change=='geometry':data['slides'][0]['objects'][0]['bbox'][2]+=5
    elif change=='canvas':data['canvas']['background']='FFFFFF'
    else:
        receipt=read_json(office/'office-render.json');receipt['text_bounds'][0]['calibration']['truncated']=True
        write_json(office/'office-render.json',receipt)
        cached=read_json(report);cached['binding']['receipt_sha256']=sha256(office/'office-render.json')
        # Even a misleading cached high-confidence row is recomputed from the receipt.
        write_json(report,cached)
    write_json(source,data)
    result=calibration.plan(source,tmp_path/'changed',reuse=report)
    assert result['samples']==1 and result['reused']==0


@pytest.mark.parametrize('file',['plan/plan.json','plan/source.scene.json','plan/specimens.pptx','synthetic-office/slide-001.png'])
def test_cache_tampering_is_rejected_before_writing(tmp_path,environment,file):
    source,_,_,report=synthetic_calibration(tmp_path,environment)
    path=tmp_path/file;path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):calibration.plan(source,tmp_path/'reused',reuse=report)
    assert not (tmp_path/'reused').exists()


def test_metrics_do_not_fabricate_baseline_or_uniform_shrink(tmp_path,environment):
    _,plan,office,_=synthetic_calibration(tmp_path,environment)
    receipt=read_json(office/'office-render.json');row=receipt['text_bounds'][0]
    row['bound_pt'][2]=900;row['calibration']['auto_size']=2
    row['calibration']['runs'][0]['baseline_offset_fraction']=.3
    write_json(office/'office-render.json',receipt)
    calibration.evaluate(plan,office,tmp_path/'overflow.json')
    data=read_json(tmp_path/'overflow.json')['targets'][0]
    assert data['confidence']=='low' and data['baseline_y_pt'] is None
    assert data['runs'][0]['effective_font_size_pt'] is None
    assert data['suggestions'][-1]['action']=='enlarge_frame_or_review_layout'
    assert not data['automatic_changes'] and data['visual_review']=='pending'


@pytest.mark.parametrize('delta',[.00003,1])
def test_physical_canvas_accepts_com_rounding_but_rejects_rescaling(tmp_path,environment,delta):
    _,plan,office,_=synthetic_calibration(tmp_path,environment)
    path=office/'office-render.json';receipt=read_json(path)
    receipt['canvas_pt'][0]+=delta;write_json(path,receipt)
    if delta<.001:
        calibration.evaluate(plan,office,tmp_path/'rounded.json')
    else:
        with pytest.raises(ValueError,match='physical canvas'):
            calibration.evaluate(plan,office,tmp_path/'bad-size.json')


def test_budget_and_grouped_objects_remain_explicitly_unmeasured(tmp_path,environment):
    data=scene([text(str(i),font_size_pt=10+i) for i in range(10)])
    data['slides'][0]['objects'].append({'id':'group','kind':'group','role':'content','editability':'group',
        'evidence':{'status':'synthetic','note':'Fixture'},'children':[text('child')]})
    path=tmp_path/'scene.json';write_json(path,data)
    result=calibration.plan(path,tmp_path/'plan',max_samples=3)
    assert result['samples']==3 and result['pending']==7 and result['deferred']==1


def test_managed_arguments_authorize_reuse_indirect_reads(runtime,tmp_path,environment):
    manager,project,_=enabled(runtime);project.mkdir(exist_ok=True)
    source,_,office,report=synthetic_calibration(project,environment)
    args=['--mode','calibration','--scene','scene.json','--reuse',str(report),'--outdir','new']
    assert registered_context(manager,'ops.text-fit-plan',args,project)==project
    data=read_json(report);data['binding']['office_dir']=str(tmp_path/'private')
    write_json(report,data)
    with pytest.raises(PolicyDenied):registered_context(manager,'ops.text-fit-plan',args,project)
    assert not (project/'new').exists()
    assert registered_context(manager,'office.render',['-Pptx','plan/specimens.pptx','-OutputDir','render','-TextCalibration'],project)==project


def test_new_mode_executes_through_real_managed_child(runtime):
    manager,project,_=enabled(runtime);project.mkdir(exist_ok=True)
    write_json(project/'scene.json',scene())
    result=manager.execute('ops.text-fit-plan',['--project',str(project),'--mode','calibration','--scene','scene.json','--outdir','plan'])
    assert result['command_status']=='completed', result
    assert read_json(project/'plan/plan.json')['version']==calibration.FORMAT


def test_group_move_covers_children_old_new_locations_and_occlusion(tmp_path):
    group={'id':'g','kind':'group','children':[shape('a'),shape('b',[120,180,60,70])]}
    data=scene([group,shape('neighbour',[200,180,80,70]),shape('far',[800,400,40,40])]);after=copy.deepcopy(data)
    for obj in after['slides'][0]['objects'][0]['children']:obj['bbox'][0]+=130
    result=compare(data,after,tmp_path,tmp_path);page=result['pages'][0]
    assert page['scope']=='regions' and {'g','a','b','neighbour'}<=set(page['affected_object_ids'])
    assert 'far' not in page['affected_object_ids']
    box=page['regions_xyxy'][0];assert box[0]<=40 and box[2]>=310
    assert not result['automatic_review_scheduling'] and not result['observations_written']


def test_font_reflow_includes_actual_overflow_and_neighbour(tmp_path):
    data=scene([text(box=[10,10,60,30]),shape('near',[90,10,25,30]),shape('far',[800,400,40,40])])
    after=copy.deepcopy(data);after['slides'][0]['objects'][0]['style']['font_size_pt']=30
    def bounds(w):return {'page':{'label':{'bound_pt':[7.5,7.5,w,22.5],'rotation':0}}}
    result=compare(data,after,tmp_path,tmp_path,before_bounds=bounds(45),after_bounds=bounds(90))
    assert result['pages'][0]['scope']=='regions'
    assert 'near' in result['pages'][0]['affected_object_ids']
    missing=compare(data,after,tmp_path,tmp_path)
    assert missing['pages'][0]['scope']=='full_page'


def test_shared_asset_byte_change_covers_every_usage_and_stays_readonly(tmp_path):
    left=tmp_path/'before';right=tmp_path/'after';left.mkdir();right.mkdir()
    (left/'asset.png').write_bytes(b'old');(right/'asset.png').write_bytes(b'new')
    image={'id':'image','kind':'image','asset':'asset.png','bbox':[10,10,20,20]}
    data=scene([image]);data['slides'].append({'id':'second','objects':[copy.deepcopy(image)]})
    original=copy.deepcopy(data);result=compare(data,data,left,right)
    assert result['affected_pages']==2 and result['changed_assets']==['asset.png']
    assert all('image' in p['affected_object_ids'] for p in result['pages'])
    assert data==original and (left/'asset.png').read_bytes()==b'old'


@pytest.mark.parametrize('change',['removed','reorder','canvas','reference','unknown','offslide','inplace_asset'])
def test_conservative_change_cases(tmp_path,change):
    data=scene([shape('one'),shape('two',[150,180,40,40])]);after=copy.deepcopy(data)
    options={}
    if change=='removed':after['slides'][0]['objects'].pop(0)
    elif change=='reorder':after['slides'][0]['objects'].reverse()
    elif change=='canvas':after['canvas']['width']=1000
    elif change=='reference':after['slides'][0]['reference']='missing.png'
    elif change=='unknown':after['slides'][0]['objects'][0]['style']['native_format']={'unknown':True}
    elif change=='offslide':after['slides'][0]['objects'][0]['bbox'][0]=-20
    else:
        (tmp_path/'asset.png').write_bytes(b'same path changed earlier')
        obj={'id':'asset','kind':'image','asset':'asset.png','bbox':[1,1,5,5]}
        data['slides'][0]['objects'].append(obj);after=copy.deepcopy(data)
        options['changed_assets']=['asset.png']
    result=compare(data,after,tmp_path,tmp_path,**options)
    assert result['affected_pages']==1
    if change in {'canvas','reference','unknown'}:assert result['pages'][0]['scope']=='full_page'
    if change=='offslide':assert result['pages'][0]['out_of_canvas']


def test_project_inspect_impact_keeps_revision_and_tasks_unchanged(runtime):
    manager,project,source=enabled(runtime);wf.start(project,[source])
    left=scene([shape()]);right=copy.deepcopy(left);right['slides'][0]['objects'][0]['bbox'][0]+=100
    write_json(project/'before.json',left);write_json(project/'after.json',right)
    state=sha256(project/'workflow/state.json')
    result=inspect(manager,{'project':str(project),'action':'impact','before_scene':'before.json','scene':'after.json'})
    assert result['affected_pages']==1 and not result['state_changed']
    assert sha256(project/'workflow/state.json')==state
    with pytest.raises(PolicyDenied):inspect(manager,{'project':str(project),'action':'impact','before_scene':str(project.parent/'private.json'),'scene':'after.json'})


def test_connector_and_slide_order_expand_advice(tmp_path):
    connector={'id':'edge','kind':'connector','points':[[0,0],[500,400]],
               'begin':{'object_id':'one','site':0},'end':{'object_id':'two','site':1}}
    data=scene([shape('one'),shape('two',[300,200,20,20]),connector]);after=copy.deepcopy(data)
    after['slides'][0]['objects'][0]['bbox'][0]+=10
    result=compare(data,after,tmp_path,tmp_path)
    assert 'attached_connector_reflow' in result['pages'][0]['expansion_reasons']
    assert {'one','two','edge'}<=set(result['pages'][0]['affected_object_ids'])
    data['slides'].append({'id':'other','objects':[shape()]});after=copy.deepcopy(data)
    after['slides'].reverse()
    assert all('page_order_changed' in p['expansion_reasons'] for p in compare(data,after,tmp_path,tmp_path)['pages'])


@pytest.mark.parametrize('broken_advice',[False,True])
def test_revision_packet_keeps_advice_and_mandatory_review(tmp_path,monkeypatch,broken_advice):
    from test_workflow import make_ready,fake_office,respond,assertion,region_payload
    from workflow_store import load
    project,task=make_ready(tmp_path,local=True)
    respond(project,{'receipt':str(fake_office(tmp_path,project))},task)
    first=wf.next_task(project)
    wf.revise(project,'slide-001','one','Fixture text change')
    task=wf.next_task(project);respond(project,region_payload('NEW LABEL',True),task)
    respond(project,assertion)
    task=wf.next_task(project);folder=tmp_path/'second';folder.mkdir()
    if broken_advice:
        from workflow_store import WorkflowError
        import review_impact
        def unavailable(*args):raise WorkflowError('impact_changed','Synthetic missing prior evidence')
        monkeypatch.setattr(review_impact,'from_runs',unavailable)
    respond(project,{'receipt':str(fake_office(folder,project))},task)
    current=wf.next_task(project);packet=read_json(current['task']['packet'])
    advice=packet['context']['revision_impact']
    assert current['task']['kind']=='review_full'
    assert not advice['automatic_review_scheduling']
    if broken_advice:
        assert advice['status']=='unavailable' and advice['scope']=='full_page'
    else:
        assert advice['status']=='advisory' and advice['pages'][0]['visual_review']=='required'
        assert advice['report'] in {row['file'] for row in packet['input_files']}
    assert read_json(current['task']['response_template'])['result']['checks']['visual_full']['status']=='blocked'
    assert not load(project)['run']['reviews']


def test_task_summary_is_bounded_without_dropping_full_report(tmp_path):
    from review_impact import summary
    before=scene([shape(str(i),[i*8,10,5,5]) for i in range(100)])
    after=copy.deepcopy(before)
    for obj in after['slides'][0]['objects']:obj['bbox'][1]+=10
    result=compare(before,after,tmp_path,tmp_path)
    short=summary(result,'page')
    assert len(short['pages'][0]['changed_objects'])==20
    assert short['pages'][0]['changed_object_count']==100
    assert short['pages'][0]['object_details_truncated']
    assert len(result['pages'][0]['changed_objects'])==100


def test_old_render_changes_without_object_diff_require_page_review(tmp_path):
    from test_workflow import make_ready,fake_office,respond
    from workflow_store import load,WorkflowError
    project,task=make_ready(tmp_path)
    respond(project,{'receipt':str(fake_office(tmp_path,project))},task)
    run=load(project)['run']
    first=copy.deepcopy(run);after=copy.deepcopy(run)
    folder=project/'test-render';folder.mkdir()
    report=read_json(project/run['render']['file']);name=report['slides'][0]['file']
    Image.new('RGB',(640,360),'black').save(folder/name)
    report['slides'][0]['sha256']=sha256(folder/name);write_json(folder/'office-render.json',report)
    after['render']={'file':'test-render/office-render.json','sha256':sha256(folder/'office-render.json')}
    result=from_runs(project,first,after)
    assert result['pages'][0]['expansion_reasons']==['render_changed_without_scene_delta']
    assert result['binding']['after_render_sha256']==after['render']['sha256']
    (folder/name).write_bytes(b'tampered')
    with pytest.raises((WorkflowError,ValueError)):from_runs(project,first,after)


def test_package_imports_work_without_scripts_on_path():
    result=subprocess.run([sys.executable,'-B','-c','import scripts.text_calibration; import scripts.review_impact'],
                          cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
