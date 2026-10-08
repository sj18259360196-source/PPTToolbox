"""Project persistence, stage contracts and bounded helper integration."""
import json
from pathlib import Path
import shutil
import threading
import time

import pytest

from scripts import project_journal as journal
from toolbox_manager.service import Manager
from toolbox_manager import project_hub as hub
from toolbox_manager import pptagent


@pytest.fixture
def project(tmp_path):
    manager=Manager(tmp_path/'data')
    base=tmp_path/'projects';base.mkdir()
    manager.save_settings({'revision':0,'values':{'projects_directory':str(base)}})
    row=hub.create(manager,{'name':'工作项目'})
    return manager,Path(row['path']),row['id']


def check(root,event='begin',stage='intake',**extra):
    s=journal.load(root)
    body={'checkpoint_id':'check-'+str(s['phase_revision']),'run_id':s['run_id'],
          'expected_revision':s['phase_revision'],'event':event,'stage':stage,
          'result_summary':'已明确本阶段安排','next_action':'继续完成下一阶段',**extra}
    return body,journal.checkpoint(root,body)


def test_create_child_and_scan_reconstructs_index(project):
    manager,root,key=project
    child=hub.create(manager,{'name':'子项目','parent':key})
    assert Path(child['path']).parent==root
    assert manager.store.get('workbench_projects')[child['id']]['parent_id']==key
    manager.store.set('workbench_projects',{})
    assert len(hub.scan(manager)['found'])==2
    assert len(manager.store.get('workbench_projects'))==2


def test_hierarchy_path_validation_does_not_hold_database_writer(project,monkeypatch):
    import sqlite3
    manager,root,key=project
    child=hub.create(manager,{'name':'子项目','parent':key})
    original=hub.plain_path
    def validate(value):
        with sqlite3.connect(manager.store.path,timeout=0) as db:
            db.execute('BEGIN IMMEDIATE')
            db.rollback()
        return original(value)
    monkeypatch.setattr(hub,'plain_path',validate)
    hub.hierarchy(manager)
    assert manager.store.get('workbench_projects')[child['id']]['parent_id']==key


def test_scan_refreshes_hierarchy_once(project,monkeypatch):
    manager,root,key=project
    hub.create(manager,{'name':'子项目','parent':key})
    original=hub.hierarchy;calls=[]
    def refresh(manager):
        calls.append(True);return original(manager)
    monkeypatch.setattr(hub,'hierarchy',refresh)
    assert len(hub.scan(manager)['found'])==2
    assert len(calls)==1


def test_duplicate_identity_is_not_merged(project):
    manager,root,key=project
    copy=root.with_name('副本');shutil.copytree(root,copy)
    result=hub.scan(manager)
    assert result['errors'] and len(manager.store.get('workbench_projects'))==1


def test_directory_reads_registered_index_without_project_io(project,monkeypatch):
    from toolbox_manager import projects
    from toolbox_manager.workbench import Workbench
    manager,root,key=project
    def forbidden(*args,**kwargs):raise AssertionError('project file read from list')
    monkeypatch.setattr(Workbench,'entry',forbidden)
    monkeypatch.setattr(hub,'files',forbidden)
    monkeypatch.setattr(journal,'load',forbidden)
    data=projects.directory(manager)
    assert data['rows'][0]['id']==key and data['rows'][0]['work_directory']==str(root)


def test_directory_only_invalidates_on_visible_metadata(project):
    from toolbox_manager import projects
    manager,root,key=project
    before=projects.directory(manager)['revision']
    projects.mutate(manager.store,lambda rows:rows[key].update(updated_at='later',last_call_id='heartbeat'))
    assert projects.directory(manager)['revision']==before
    projects.mutate(manager.store,lambda rows:rows[key].update(archived=True))
    assert projects.directory(manager)['revision']!=before
    projects.mutate(manager.store,lambda rows:rows.pop(key))
    assert projects.directory(manager)['rows']==[]


def test_directory_read_does_not_acquire_writer_lock(project):
    import sqlite3
    from toolbox_manager.projects import directory
    manager,_,key=project
    with sqlite3.connect(manager.store.path,timeout=0) as db:
        db.execute('BEGIN IMMEDIATE')
        assert directory(manager)['rows'][0]['id']==key
        db.rollback()


def test_folder_identity_survives_missing_markdown(project):
    manager,root,key=project
    (root/'ppttool.md').unlink()
    assert hub.entry(manager,key)[1]['project_id']==journal.load(root)['project_id']
    manager.store.set('workbench_projects',{})
    assert len(hub.scan(manager)['found'])==1


def test_current_preview_uses_declared_candidate_not_newest_history(project):
    import os
    manager,root,key=project
    for name,age in [('current.pptx',10),('historical-copy.pptx',5)]:
        p=root/name;p.write_bytes(b'fixture');os.utime(p,(time.time()-age,)*2)
    hub.observe(manager,key)
    (root/'workflow').mkdir()
    (root/'workflow/state.json').write_text(json.dumps({'project_id':journal.load(root)['project_id'],
         'status':'running','run':{'candidate':{'file':'current.pptx'}}}),encoding='utf-8')
    result=hub.previews(manager,key)
    assert [d['path'] for d in result['decks']]==['current.pptx']
    assert (root/'historical-copy.pptx').exists()


def test_checkpoint_retry_and_conflicting_reuse(project):
    _,root,_=project
    body,result=check(root)
    assert journal.checkpoint(root,body)['duplicate']
    assert len(journal.load(root)['checkpoints'])==1
    with pytest.raises(ValueError,match='不同内容'):
        journal.checkpoint(root,{**body,'result_summary':'另一个结果'})


def test_concurrent_checkpoint_only_one_wins(project):
    _,root,_=project
    s=journal.load(root);results=[]
    def run(i):
        try:results.append(journal.checkpoint(root,{'checkpoint_id':str(i),'run_id':s['run_id'],
            'expected_revision':0,'event':'begin','stage':'intake','result_summary':'开始','next_action':'规划'}))
        except ValueError:results.append(None)
    threads=[threading.Thread(target=run,args=(i,)) for i in range(2)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert len([r for r in results if r])==1
    assert journal.load(root)['phase_revision']==1


def test_six_checkpoints_and_artifact_confirmation(project):
    manager,root,key=project
    journal.ensure(root,required=True)
    assert journal.requirement(root)
    check(root)
    assert journal.requirement(root) is None
    for stage,_ in journal.STAGES[1:]:check(root,'transition',stage)
    assert journal.requirement(root,True) is None
    check(root,'finish','delivery',artifact_refs=['result.pptx'])
    state=journal.load(root)
    assert len(state['checkpoints'])==6 and state['phase']['artifact_state']=='unconfirmed'
    (root/'result.pptx').write_bytes(b'test artifact existence only')
    state=hub.observe(manager,key)
    assert state['phase']['artifact_state']=='present'


def test_stage_order_and_stale_run(project):
    _,root,_=project
    check(root)
    with pytest.raises(ValueError,match='下一大阶段'):check(root,'transition','delivery')
    with pytest.raises(ValueError,match='任务或阶段版本'):check(root,run_id='wrong')


def test_replan_retains_old_branch(project):
    _,root,_=project
    check(root);check(root,'transition','plan');check(root,'transition','production')
    check(root,'replan','plan',result_summary='原素材不可用，调整路线')
    s=journal.load(root)
    assert len(s['checkpoints'])==4 and s['phase']['stage']=='plan'
    assert s['checkpoints'][-1]['from_stage']=='production'


def test_notes_preserved_and_conflict_detected(project):
    _,root,_=project
    old=journal.notes(root)
    journal.save_notes(root,'用户手写说明',old['revision'])
    check(root)
    assert journal.notes(root)['text']=='用户手写说明'
    with pytest.raises(ValueError,match='已被修改'):
        journal.save_notes(root,'覆盖说明',old['revision'])


def test_event_recovery_without_snapshot(project):
    _,root,_=project
    check(root)
    (root/'.ppttool/state.json').unlink()
    assert journal.load(root)['phase']['stage']=='intake'


def test_unsafe_artifacts_and_unknown_fields(project):
    _,root,_=project
    with pytest.raises(ValueError,match='超出'):
        check(root,artifact_refs=['../outside.pptx'])
    with pytest.raises(ValueError,match='未知'):
        check(root,finish_all=True)


def test_file_observer_does_not_loop_or_include_child(project):
    manager,root,key=project
    child=hub.create(manager,{'name':'独立子项目','parent':key})
    (Path(child['path'])/'child.pptx').write_bytes(b'child')
    (root/'deck.pptx').write_bytes(b'one')
    first=hub.observe(manager,key)
    second=hub.observe(manager,key)
    assert first['sequence']==second['sequence']
    assert [f['path'] for f in second['files']]==['deck.pptx']
    (root/'deck.pptx').write_bytes(b'new version')
    assert hub.observe(manager,key)['sequence']>second['sequence']


def test_preview_requires_exact_deck_hash(project):
    import hashlib,os
    manager,root,key=project
    p=root/'deck.pptx';p.write_bytes(b'fixture');os.utime(p,(time.time()-5,)*2)
    image=root/'slide-001.png';image.write_bytes(b'not a decoded image')
    receipt=root/'office-render.json';receipt.write_text(json.dumps({'pptx_sha256':'wrong'}))
    hub.observe(manager,key)
    assert not hub.previews(manager,key)['decks'][0]['slides']
    receipt.write_text(json.dumps({'pptx_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':'passed'}))
    assert hub.previews(manager,key)['decks'][0]['slides']==['slide-001.png']


def test_retrieval_does_not_offer_chart_for_title():
    from scripts.rebuild_assistance import search
    ids=[r['id'] for r in search('标题、蓝色One Health与双语问题',stage='production')['matches']]
    assert 'EXP-129' not in ids
    assert 'EXP-128' in [r['id'] for r in search('公式下标显示不全')['matches']]


def test_model_cannot_overwrite_newer_project_state(project,monkeypatch):
    manager,root,key=project
    check(root)
    manager.store.set('pptagent_config',{'enabled':True,'revision':1,'endpoint':'http://127.0.0.1/api','model':'fixture'})
    def request(*args):
        journal.update(root,{'label':'已被用户更新'},source='human')
        return {'summary':'old','next_hint':'old','evidence_ids':['check-0'],'recommended_ids':[]}
    monkeypatch.setattr(pptagent,'request_summary',request)
    worker=pptagent.Worker(manager);state=journal.load(root)
    worker.process(key,state['sequence'],'signature')
    assert journal.load(root)['label']=='已被用户更新'
    assert journal.load(root)['summary']=={}


def test_helper_failure_does_not_change_stage(project,monkeypatch):
    manager,root,key=project;check(root)
    manager.store.set('pptagent_config',{'enabled':True,'revision':1,'endpoint':'http://127.0.0.1/api','model':'fixture'})
    def fail(*args):raise TimeoutError('secret provider response')
    monkeypatch.setattr(pptagent,'request_summary',fail)
    s=journal.load(root);pptagent.Worker(manager).process(key,s['sequence'],'same')
    result=journal.load(root)
    assert result['phase']==s['phase'] and result['summary']['status']=='unavailable'
    assert 'secret' not in json.dumps(result['summary'])


def test_settings_rejects_remote_http_and_never_returns_key(project):
    manager,_,_=project
    with pytest.raises(ValueError,match='HTTPS'):
        pptagent.save_config(manager,{'enabled':True,'revision':0,'endpoint':'http://example.com','model':'model'})
    c=pptagent.save_config(manager,{'enabled':False,'revision':0,'endpoint':'','model':''})
    assert 'api_key' not in c and c['revision']==1


def test_offline_queue_does_not_override_target_project(project,monkeypatch):
    manager,root,key=project
    folder=root/'.ppttool/checkpoints/pending';folder.mkdir(parents=True)
    (folder/'input.json').write_text(json.dumps({'project':'outside'}))
    called=[]
    monkeypatch.setattr(hub,'checkpoint',lambda manager,body:called.append(body) or {})
    hub.Observer(manager).pending_checkpoints(key)
    assert called[0]['project']==key


def test_folder_project_start_inline_checkin_and_pause_gate(project,tmp_path):
    from PIL import Image
    manager,root,key=project
    image=tmp_path/'input.png';Image.new('RGB',(32,18),'white').save(image)
    manager.authorize_project(root,[tmp_path])
    manager.save_settings({'revision':manager.settings()['revision'],'values':{'agent_execution_enabled':True}})
    started=manager.execute_workflow('start',{'project':str(root),'in_place':True,'references':[str(image)]})
    assert started['command_status']=='completed',started
    assert started['stage_context']['checkpoint_required']
    assert started['workbench_project']==key and len(manager.store.get('workbench_projects'))==1
    gate=manager.execute_workflow('next',{'project':str(root)})
    assert gate['checkpoint_required']['required'] and 'task' not in gate
    state=journal.load(root)
    body={'checkpoint_id':'first','run_id':state['run_id'],'expected_revision':0,'event':'begin',
          'stage':'intake','result_summary':'确认输入','next_action':'制定方案'}
    result=manager.execute_workflow('next',{'project':str(root),'checkpoint':body})
    assert result['task']['kind']=='page_plan'
    assert journal.load(root)['phase_revision']==1
    check(root,'pause','intake')
    paused=manager.execute_workflow('next',{'project':str(root)})
    assert paused['checkpoint_required']['required']
    check(root,'resume','intake')
    assert manager.execute_workflow('next',{'project':str(root)})['task']['task_id']==result['task']['task_id']


def test_observer_cannot_undo_a_concurrent_checkpoint(project,monkeypatch):
    manager,root,key=project
    check(root)
    original=journal.update
    def concurrent(*args,**kw):
        check(root,'transition','plan')
        return original(*args,**kw)
    monkeypatch.setattr(journal,'update',concurrent)
    assert hub.observe(manager,key)['phase']['stage']=='plan'
    assert journal.load(root)['phase_revision']==2


def test_adoption_and_recommendation_counters_remain_separate(project):
    from scripts.usage_store import connect
    manager,root,key=project;manager.authorize_project(root,[])
    s=journal.load(root)
    body={'project':key,'checkpoint_id':'adoption','run_id':s['run_id'],'expected_revision':0,
          'event':'begin','stage':'intake','result_summary':'本次已采用公式处理方法','next_action':'核对公式下标',
          'used_experiences':['EXP-128']}
    hub.checkpoint(manager,body);hub.checkpoint(manager,body)
    with connect(manager.data/'usage') as db:
        adopted=db.execute("SELECT evidence FROM usage_events WHERE action='cited'").fetchall()
        recommended=db.execute("SELECT count(*) FROM usage_events WHERE action='retrieved'").fetchone()[0]
    assert len(adopted)==1 and recommended>=1
    assert json.loads(adopted[0]['evidence'])['level']=='agent_reported_not_validated'


def test_replan_cannot_skip_forward_and_absolute_artifacts_rejected(project):
    _,root,_=project;check(root)
    with pytest.raises(ValueError,match='不能跳过'):check(root,'replan','delivery')
    with pytest.raises(ValueError,match='相对路径'):check(root,'pause','intake',artifact_refs=[str(root/'file.pptx')])


def test_mcp_checkpoint_is_a_write_and_activity_is_read_only(project):
    from toolbox_manager.mcp import MCP
    manager,_,_=project;mcp=MCP(manager.data)
    mcp.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})
    specs=mcp.handle({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})['result']['tools']
    annotations={r['name']:r['annotations'] for r in specs}
    assert annotations['toolbox_checkpoint']['readOnlyHint'] is False
    assert annotations['toolbox_project_activity']['readOnlyHint'] is True


def test_model_rejects_invented_evidence(project,monkeypatch):
    manager,_,_=project
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'choices':[{'message':{'content':json.dumps({
            'summary':'invented','next_hint':'','evidence_ids':['missing'],'recommended_ids':[]})}}]}).encode()
    class Client:
        def open(self,*args,**kw):return Reply()
    monkeypatch.setattr(pptagent,'build_opener',lambda *args:Client())
    with pytest.raises(ValueError,match='不存在'):
        pptagent.request_summary(manager,{'model':'fixture','endpoint':'http://127.0.0.1/api'},{'evidence_ids':['known'],'recommendations':[]})


def test_real_dpapi_roundtrip_and_public_config_redaction(project):
    import os,base64
    if os.name!='nt':pytest.skip('Windows DPAPI test')
    manager,_,_=project
    public=pptagent.save_config(manager,{'enabled':False,'revision':0,'endpoint':'','model':'','api_key':'test-only-secret'})
    raw=(manager.data/'pptagent/key.dpapi').read_bytes()
    assert b'test-only-secret' not in raw and 'test-only-secret' not in json.dumps(public)
    assert pptagent._secret(base64.b64decode(raw),True)==b'test-only-secret'


def test_metadata_survives_index_rebuild(project):
    from toolbox_manager.projects import update_metadata
    manager,root,key=project
    update_metadata(manager,{'id':key,'revision':0,'label':'人工整理的名称','category':'研究','archived':True})
    manager.store.set('workbench_projects',{})
    hub.scan(manager)
    row=next(iter(manager.store.get('workbench_projects').values()))
    assert (row['label'],row['category'],row['archived'])==('人工整理的名称','研究',True)


def test_scan_does_not_initialize_unrelated_workflow(project):
    manager,root,_=project
    unrelated=root.parent/'unrelated';(unrelated/'workflow').mkdir(parents=True)
    (unrelated/'workflow/state.json').write_text('{"status":"running"}')
    result=hub.scan(manager)
    assert result['errors'] and not (unrelated/'ppttool.md').exists() and not (unrelated/'.ppttool').exists()


def test_provider_change_does_not_send_key_to_previous_endpoint(project,monkeypatch):
    manager,_,_=project
    old={'revision':0,'endpoint':'http://127.0.0.1/old','model':'fixture'}
    pptagent.save_config(manager,{'enabled':False,'revision':0,'endpoint':'http://127.0.0.1/new','model':'fixture'})
    monkeypatch.setattr(pptagent,'build_opener',lambda *args:pytest.fail('Stale request must not reach network'))
    with pytest.raises(ValueError,match='设置已变化'):
        pptagent.request_summary(manager,old,{'evidence_ids':[],'recommendations':[]})
