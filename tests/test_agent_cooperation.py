import copy
import json
import pytest
from pathlib import Path
from toolbox_manager.issue_assessment import assess, handoff
from toolbox_manager.pptagent_assistance import tool
from toolbox_manager.project_activity import observe_call, CALL_ID
from toolbox_manager.project_status import reconcile
from scripts import project_journal as journal
from test_pptagent_responses import project


def test_delivered_rejection_is_history_without_rewriting_failure():
    bad={'id':'bad','tool':'workflow.replace-scene','project':'p','status':'failed','state':'open',
         'revision_before':25,'revision_after':25,'at':'1','recovery':{'outcome':'rejected'}}
    good={'id':'good','tool':bad['tool'],'project':'p','status':'completed','revision_after':26,'at':'2','evidence_id':'audit-good'}
    state={'phase':{'status':'finished','artifact_state':'present'},'activity':{'calls':[good],'issues':[bad]}}
    original=copy.deepcopy(state)
    result=assess(state)
    assert not result['attention'] and result['history'][0]['state']=='open'
    assert result['history'][0]['status']=='failed' and state==original
    state['activity']['task']={'id':'new'}
    assert assess(state)['attention']
    state['activity']['task']={};good['project']='different'
    assert assess(state)['attention']


def test_empty_and_unknown_are_different_even_after_delivery():
    state={'phase':{'status':'finished','artifact_state':'present'},'activity':{'issues':[
        {'id':'empty','state':'open','status':'blocked','message':'no_results'},
        {'id':'unknown','state':'open','status':'outcome_unknown'}]}}
    result=assess(state)
    assert [r['id'] for r in result['attention']]==['unknown']
    assert result['history'][0]['impact']=='informational'
    assert handoff(state)['current_action']=='等待用户认可交付'


def test_handoff_scope_version_idempotence_and_unknown_protection(project):
    manager,root,key,cfg=project
    state=journal.load(root)
    with pytest.raises(ValueError):tool(manager,'prepare_handoff',{'project':key,'sequence':state['sequence']},None)
    with pytest.raises(ValueError):tool(manager,'prepare_handoff',{'project':key,'sequence':999},key)
    out=tool(manager,'prepare_handoff',{'project':key,'sequence':state['sequence']},key)
    latest=journal.load(root)
    repeat=tool(manager,'prepare_handoff',{'project':key,'sequence':latest['sequence']},key)
    assert out==repeat and journal.load(root)['sequence']==latest['sequence']
    assert (root/out['path']).is_file() and latest['phase']==state['phase']
    issues=[{'id':'unknown','state':'open','status':'outcome_unknown','evidence_id':'audit-u'}]
    latest=journal.update(root,{'activity':{'issues':issues}})
    with pytest.raises(ValueError):tool(manager,'record_issue_disposition',{'project':key,'sequence':latest['sequence'],'issue_id':'unknown'},key)


def test_artifact_escape_and_unregistered_checks_rejected(project):
    manager,root,key,cfg=project
    (root/'test.md').write_text('artifact',encoding='utf-8')
    assert tool(manager,'inspect_artifact',{'project':key,'path':'test.md'},key)['sha256']
    for path in ['../outside.md','secret.dpapi']:
        with pytest.raises(ValueError):tool(manager,'inspect_artifact',{'project':key,'path':path},key)
    with pytest.raises(ValueError):tool(manager,'run_registered_checks',{'project':key,'kind':'shell'},key)
    with pytest.raises(ValueError):tool(manager,'draft_tool_change',{'project':key,'sequence':journal.load(root)['sequence'],'text':'fix','evidence_id':'invented'},key)


def test_empty_call_is_not_error_and_terminal_receipt_is_saved(project):
    manager,root,key,cfg=project
    seen=[]
    def operation():
        seen.append(CALL_ID.get());return {'items':[]}
    observe_call(manager,'icons.search',{},'mcp',operation,project_scope=key)
    receipt=json.loads((root/'logs/tool-calls'/seen[0]/'activity.json').read_text('utf-8'))
    assert receipt['command_status']=='no_results' and CALL_ID.get() is None
    with manager.store.db() as db:
        row=db.execute("select status from events where action='activity.finished' order by id desc limit 1").fetchone()
    assert row[0]=='ok'


def test_preflight_reports_missing_reference_and_evidence_together(tmp_path):
    from scripts.scene_preflight import inspect,require
    path=tmp_path/'scene.json'
    path.write_text(json.dumps({'version':'1.0','canvas':{'width':100,'height':100},'slides':[
        {'id':'slide-1','reference':'missing.png','objects':[{'id':'box','kind':'shape','geometry':'rect','bbox':[0,0,20,20]}]}]}))
    report=inspect(path)
    assert report['status']=='invalid'
    assert any('evidence' in x for x in report['errors'])
    assert any('missing.png' in x for x in report['errors'])
    with pytest.raises(ValueError,match='base='):require(path)


def test_terminal_receipt_failure_does_not_replay_or_mask_operation(project,monkeypatch):
    manager,root,key,cfg=project
    atomic=journal.atomic
    count=[]
    def write(path,text):
        if str(path).endswith('activity.json') and json.loads(text)['command_status']!='started':
            raise OSError('receipt disk unavailable')
        return atomic(path,text)
    monkeypatch.setattr(journal,'atomic',write)
    def operation():count.append(1);return {'command_status':'completed'}
    assert observe_call(manager,'graphics.construct',{},'mcp',operation,project_scope=key)['command_status']=='completed'
    assert count==[1] and CALL_ID.get() is None
    def rejected():raise ValueError('original rejection')
    with pytest.raises(ValueError,match='original rejection'):
        observe_call(manager,'graphics.construct',{},'mcp',rejected,project_scope=key)


def test_observer_recovers_terminal_receipt_when_event_is_missing(project,monkeypatch):
    from toolbox_manager.project_hub import observe
    from toolbox_manager import execution
    manager,root,key,cfg=project
    cid='a'*32
    path=root/'logs/tool-calls'/cid/'activity.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'call_id':cid,'command_status':'completed'}),encoding='utf-8')
    manager.store.event('activity.started','graphics.construct',details={'project':str(root),'call_id':cid,'tool_id':'graphics.construct','owner_pid':123})
    monkeypatch.setattr(execution,'process_alive',lambda pid:False)
    observe(manager,key)
    calls=journal.load(root)['activity']['calls']
    assert next(c for c in calls if c['id']==cid)['status']=='completed'
