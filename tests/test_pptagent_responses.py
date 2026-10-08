"""Local Responses protocol fixtures and real policy/journal boundaries. No live API."""
import json
import threading
from pathlib import Path

import pytest

from scripts import project_journal as journal
from toolbox_manager import pptagent as agent, pptagent_runtime as runtime, project_hub as hub, requests
from toolbox_manager.service import Manager


@pytest.fixture
def project(tmp_path):
    manager = Manager(tmp_path/'data')
    base = tmp_path/'projects'; base.mkdir()
    manager.save_settings({'revision':0,'values':{'projects_directory':str(base)}})
    row = hub.create(manager, {'name':'管理测试'})
    cfg = agent.save_config(manager, {'revision':0,'enabled':True,'protocol':'responses',
                                     'endpoint':'http://127.0.0.1/v1/responses','model':'fixture'})
    return manager, Path(row['path']), row['id'], cfg


def call(name, args, identifier='call-1'):
    return {'type':'function_call','name':name,'arguments':json.dumps(args),'call_id':identifier}


def response(*items, text=None):
    return {'status':'completed','output':list(items)+([] if text is None else [
        {'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}])}


def task(project, prompt='查看项目并保存管理安排', scope=True):
    manager,root,key,cfg=project
    return runtime.submit(manager, {'id':'owner-task','revision':cfg['revision'],'prompt':prompt,'project':key if scope else None})


def run(project, row):
    runtime.run_task(project[0], row, threading.Event())
    return runtime.tasks(project[0])[0]


def test_responses_summary_has_structured_output_and_no_temperature(project,monkeypatch):
    manager,_,_,cfg=project
    payload={'evidence_ids':['actual-1'],'recommendations':[]}
    result={'summary':'工具已返回','next_hint':'继续制作','evidence_ids':['actual-1'],'recommended_ids':[]}
    def provider(m,c,body,**kw):
        assert body['store'] is False and body['text']['format']['strict'] is True
        assert 'temperature' not in body and 'messages' not in body
        return response(text=json.dumps(result))
    monkeypatch.setattr(agent,'request_json',provider)
    assert agent.request_summary(manager,cfg,payload)==result


def test_full_tool_loop_preserves_reasoning_and_saves_only_note(project,monkeypatch):
    manager,root,key,cfg=project; before=journal.load(root); notes_before=journal.notes(root); sent=[]
    def provider(m,c,body,**kw):
        sent.append(body)
        assert body['store'] is False and 'reasoning.encrypted_content' in body['include']
        assert all(t['strict'] and not t['parameters']['additionalProperties'] for t in body['tools'])
        if len(sent)==1:
            return response({'type':'reasoning','id':'reason-1','encrypted_content':'opaque'},call('read_project',{'project':key}))
        if len(sent)==2:
            result=json.loads(body['input'][-1]['output'])
            assert body['input'][-1]['call_id']=='call-1'
            assert any(x.get('encrypted_content')=='opaque' for x in body['input'])
            return response(call('record_project_note',{'project':key,'sequence':result['sequence'],'text':'下次整理交付文件'},'call-2'))
        return response(text='管理备注已保存')
    monkeypatch.setattr(agent,'request_json',provider)
    result=run(project,task(project))
    assert result['status']=='completed' and len(result['steps'])==2
    after=journal.load(root)
    assert after['management_note']['text']=='下次整理交付文件'
    assert after['phase']==before['phase'] and after['checkpoints']==before['checkpoints']
    assert journal.notes(root)==notes_before


def test_probe_runs_tool_roundtrip_without_project_data(project,monkeypatch):
    manager,root,key,cfg=project; sent=[]
    def provider(m,c,body,**kw):
        sent.append(body)
        assert str(root) not in json.dumps(body) and key not in json.dumps(body)
        if len(sent)==1:
            assert body['tool_choice']['name']=='connection_probe'
            nonce=body['input'][0]['content'].split('nonce 为 ')[1].split('；')[0]
            return response(call('connection_probe',{'nonce':nonce}))
        assert json.loads(body['input'][-1]['output'])['ok'] is True
        return response(text='连接正常')
    monkeypatch.setattr(agent,'request_json',provider)
    row=runtime.submit(manager,{'id':'probe','revision':cfg['revision']},probe=True)
    assert run(project,row)['status']=='completed'
    assert agent.config(manager)['connection']['tools_verified'] is True


def test_probe_does_not_accept_plain_chat_as_success(project,monkeypatch):
    monkeypatch.setattr(agent,'request_json',lambda *a,**kw:response(text='连接正常'))
    m,_,_,cfg=project
    result=run(project,runtime.submit(m,{'id':'probe','revision':cfg['revision']},probe=True))
    assert result['status']=='failed' and agent.config(m)['connection']['status']=='unavailable'


@pytest.mark.parametrize('event',['cancel','disable'])
def test_cancel_or_config_change_stops_next_side_effect(project,monkeypatch,event):
    manager,root,key,cfg=project; row=task(project)
    def provider(*args,**kw):
        if event=='cancel':runtime.cancel(manager,{'id':row['id']})
        else:agent.save_config(manager,{k:cfg[k] for k in ('revision','endpoint','model','protocol')}|{'enabled':False})
        return response(call('record_project_note',{'project':key,'sequence':journal.load(root)['sequence'],'text':'不能写入'}))
    monkeypatch.setattr(agent,'request_json',provider)
    assert run(project,row)['status'] in {'cancelled','interrupted'}
    assert 'management_note' not in journal.load(root)


def test_tools_reject_shell_cross_project_and_stale_notes(project):
    manager,root,key,_=project
    with pytest.raises(ValueError):runtime.tool_result(manager,'shell',{'command':'anything'},key)
    child=hub.create(manager,{'name':'其他项目'})
    with pytest.raises(ValueError):runtime.tool_result(manager,'read_project',{'project':child['id']},key)
    with pytest.raises(ValueError):runtime.tool_result(manager,'record_project_note',{'project':key,'sequence':0,'text':'old'},key)
    with pytest.raises(ValueError):runtime.tool_result(manager,'record_project_note',{'project':key,'sequence':journal.load(root)['sequence'],'text':'x'},None)
    assert 'management_note' not in journal.load(root)


def test_tasks_are_idempotent_and_restart_does_not_replay(project):
    m,_,_,_=project; first=task(project)
    assert task(project)==first and len(runtime.tasks(m))==1
    with pytest.raises(ValueError):task(project,prompt='不同任务')
    runtime.change_task(m,first['id'],status='running',steps=[{'tool':'x','status':'completed'}])
    runtime.recover(m)
    assert runtime.tasks(m)[0]['status']=='interrupted'
    assert runtime.tasks(m)[0]['steps'][0]['status']=='completed'


def test_saved_policy_applies_only_when_owner_enabled_it(project):
    m,root,key,_=project
    row=requests.record_start(m,{'project':str(root)})
    assert row['status']=='awaiting_authorization'
    result=requests.apply_saved_policy(m,row['id'],row['revision'])
    assert result['status']=='awaiting_authorization' and not m.store.get('project_authorizations',{})
    settings=m.settings()
    m.save_settings({'revision':settings['revision'],'values':{'auto_approve_project_requests':True}})
    result=requests.apply_saved_policy(m,row['id'],row['revision'])
    assert result['status']=='approved' and m.store.get('project_authorizations')[str(root)]['write']
    assert m.settings()['agent_execution_enabled'] is False
    assert journal.load(root)['phase']=={}


def test_policy_keeps_owner_rejection_and_stale_request(project):
    m,root,key,_=project
    row=requests.record_start(m,{'project':str(root)})
    rejected=requests.decide(m,{'id':row['id'],'revision':row['revision'],'decision':'reject'})
    with pytest.raises(ValueError):requests.apply_saved_policy(m,row['id'],row['revision'])
    assert requests.apply_saved_policy(m,row['id'],rejected['revision'])['status']=='rejected'
    assert not m.store.get('project_authorizations',{})


def test_invalid_calls_are_recorded_without_executing(project,monkeypatch):
    count=0
    def provider(*args,**kw):
        nonlocal count;count+=1
        return response(call('shell',{'command':'do not execute'})) if count==1 else response(text='未知工具未执行')
    monkeypatch.setattr(agent,'request_json',provider)
    result=run(project,task(project))
    assert result['steps'][0]['status']=='failed' and '未完成' in result['result']


def test_duplicate_call_id_stops_without_repeating_effect(project,monkeypatch):
    m,root,key,_=project
    def provider(*args,**kw):
        return response(call('record_project_note',{'project':key,'sequence':journal.load(root)['sequence'],'text':'只写一次'}))
    monkeypatch.setattr(agent,'request_json',provider)
    before=journal.load(root)['sequence'];result=run(project,task(project))
    assert result['status']=='failed' and journal.load(root)['sequence']==before+1


def test_provider_failure_does_not_leak_response_or_change_stage(project,monkeypatch):
    m,root,key,_=project
    def fail(*a,**kw):raise RuntimeError('secret-provider-body-sk-sensitive')
    monkeypatch.setattr(agent,'request_json',fail)
    result=run(project,task(project))
    assert result['status']=='failed' and 'sensitive' not in json.dumps(result)
    assert journal.load(root)['phase']=={}


def test_summary_rejects_incomplete_responses(project,monkeypatch):
    m,_,_,cfg=project
    monkeypatch.setattr(agent,'request_json',lambda *a,**kw:{'status':'incomplete','output':[]})
    with pytest.raises(ValueError):agent.request_summary(m,cfg,{'evidence_ids':[],'recommendations':[]})
