"""Regression cases for accepted effects, optional metadata and Office inputs."""
import copy
import json
import subprocess
import shutil
from pathlib import Path

import pytest
from toolbox_manager.recovery import describe_result
from toolbox_manager.project_status import incident
from scripts import project_journal as journal
from scripts.project_flow import merge, MAX_GRAPH_NODES
from test_project_chain import project, check
from test_managed_rebuild import ROOT, runtime, begin, invoke


@pytest.mark.parametrize('payload,field', [
    ([{'index':1,'height':100}], 'width'),
    ([{'index':1,'width':True,'height':100}], 'width'),
    ([{'index':1,'width':'100','height':100}], 'width'),
    ([{'index':1,'width':-1,'height':100}], 'width'),
    ([{'index':1.5,'width':100,'height':100}], 'index'),
    ([{'index':0,'width':100,'height':100}], 'index'),
    ([{'index':1,'width':100,'height':100}]*2, 'index'),
    ({'index':1,'width':100,'height':100}, '$'),
    ([None], 'index'),
])
def test_invalid_render_sizes_never_starts_office(tmp_path, payload, field):
    sizes=tmp_path/'sizes.json'; sizes.write_text(json.dumps(payload),encoding='utf-8')
    out=tmp_path/'render'
    preferred=Path('C:/Program Files/PowerShell/7/pwsh.exe')
    shell=str(preferred) if preferred.is_file() else shutil.which('pwsh.exe')
    if not shell:pytest.skip('PowerShell 7 required')
    result=subprocess.run([shell,'-NoProfile','-File',
        str(ROOT/'scripts/render_powerpoint.ps1'),'-Pptx',str(tmp_path/'missing.pptx'),
        '-OutputDir',str(out),'-SizesJson',str(sizes)],capture_output=True,timeout=30)
    receipt=json.loads((out/'office-render.json').read_text(encoding='utf-8'))
    assert result.returncode==1
    assert receipt['error_code']=='invalid_render_sizes'
    assert receipt['error_field']==field
    assert receipt['office_started'] is False
    assert receipt['validation_stage']=='pre_com'


def test_submission_envelope_alone_prohibits_replay_and_retains_stage():
    result=describe_result({'command_status':'completed',
        'submission':{'state':'accepted','task_id':'t'},
        'next_error':{'code':'office_busy','stage':'render','message':'occupied'}},dispatched=True)
    assert result['acceptance_state']=='accepted'
    assert result['submission']['replay_allowed'] is False
    assert result['failed_stage']=='render'
    call={'id':'c','status':'completed','recovery':result['recovery'],
          'failed_stage':result['failed_stage']}
    assert incident(call)['title']=='提交已保存，渲染失败'
    del call['failed_stage']
    assert incident(call)['title']=='提交已保存，后续处理失败'


def test_invalid_optional_graph_commits_phase_and_replays_same_warning(project):
    _,root,_=project
    body,receipt=check(root,flow=[{'id':'node','title':'Node','after':['missing']}])
    assert receipt['recorded'] is True
    assert receipt['graph_update']['state']=='rejected'
    state=journal.load(root); before=copy.deepcopy(state)
    replay=journal.checkpoint(root,body)
    assert replay['duplicate'] is True
    assert replay['graph_update']==receipt['graph_update']
    assert journal.load(root)==before
    with pytest.raises(ValueError,match='不同内容'):
        journal.checkpoint(root,{**body,'flow':[{'id':'node','title':'Repaired'}]})


def test_core_or_transport_error_keeps_phase_unchanged(project):
    _,root,_=project
    check(root); before=journal.load(root)
    for event,flow in [('transition',[{'id':'node','title':'Node'}]),
                       ('resume',[{}]*65)]:
        with pytest.raises(ValueError):
            check(root,event=event,stage='delivery',flow=flow)
        assert journal.load(root)==before


def test_graph_io_failure_is_not_downgraded(project,monkeypatch):
    _,root,_=project; before=journal.load(root)
    def fail(*args,**kwargs): raise OSError('disk unavailable')
    monkeypatch.setattr(journal,'_commit',fail)
    with pytest.raises(OSError,match='disk unavailable'):
        check(root,flow=[{'id':'node','after':['missing']}])
    assert journal.load(root)==before


def test_long_graph_retains_nodes_and_dependencies():
    graph=None
    for start in range(0,MAX_GRAPH_NODES,64):
        rows=[{'id':f'n{i}','title':f'Node {i}','after':[f'n{i-1}'] if i else []}
              for i in range(start,min(start+64,MAX_GRAPH_NODES))]
        graph=merge(graph,rows,source='agent',at='test')
    before=copy.deepcopy(graph)
    assert len(graph['nodes'])==MAX_GRAPH_NODES
    with pytest.raises(ValueError):merge(graph,[{'id':'overflow','title':'extra'}],source='agent',at='test')
    assert graph==before


def test_input_change_reports_original_hash_without_rewriting(runtime):
    from workflow_store import load
    manager,root,_=begin(runtime)
    state=json.loads((root/'workflow/state.json').read_text(encoding='utf-8'))
    rel,expected=next(iter(state['tracked_inputs'].items()))
    original=(root/'workflow/state.json').read_bytes()
    (root/rel).write_bytes(b'changed by external host')
    with pytest.raises(ValueError) as error:load(root)
    assert error.value.code=='input_changed'
    row=error.value.diagnostics[0]
    assert row['file']==rel and row['expected_sha256']==expected
    assert row['actual_sha256']!=expected
    assert (root/'workflow/state.json').read_bytes()==original


def test_managed_call_returns_and_persists_graph_warning(runtime):
    manager,root,_=begin(runtime)
    state=journal.load(root)
    body={'checkpoint_id':'begin-with-bad-graph','run_id':state['run_id'],
          'expected_revision':state['phase_revision'],'event':'resume','stage':'plan',
          'result_summary':'Confirm input','next_action':'Plan the page',
          'flow':[{'id':'x','kind':'nonexistent-kind'}]}
    result=invoke(manager,'next',root,checkpoint=body)
    assert result['command_status']=='completed',result
    assert result['checkpoint_receipt']['graph_update']['state']=='rejected'
    replay=invoke(manager,'next',root,checkpoint=body)
    assert replay['checkpoint_receipt']['duplicate'] is True
    assert replay['task']['id']==result['task']['id']
    assert json.loads((Path(result['output_directory'])/'call.json').read_text(encoding='utf-8'))['checkpoint_receipt']['graph_update']['state']=='rejected'


def test_mcp_graph_repair_changes_only_metadata(project):
    from toolbox_manager.mcp import MCP
    manager,root,key=project
    manager.authorize_project(root, [root])
    check(root);before=journal.load(root)
    server=MCP(manager.data,root=manager.root,home=manager.home)
    result=server.call('toolbox_update_work_graph',{'project':key,'sequence':before['sequence'],
                    'flow':[{'id':'plan','title':'Plan'}]})
    after=journal.load(root)
    assert result['scope']=='display_only'
    assert after['last_graph_update']['state']=='applied'
    assert after['phase']==before['phase'] and after['checkpoints']==before['checkpoints']
    with pytest.raises(ValueError):
        server.call('toolbox_update_work_graph',{'project':key,'sequence':before['sequence'],'flow':[{'id':'plan','title':'Changed'}]})
    assert journal.load(root)==after


def test_template_exposes_current_text_ids_without_guessing_transcription():
    import workflow
    from task_contracts import examples
    context={'text_and_tables':[{'id':'t1','kind':'text','text':'Output text'},
                               {'id':'table','kind':'table'}]}
    template=workflow._template('source_review',context)
    assert template['text_checks']==[{'object_id':'t1','source_text':''}]
    assert template['status']=='blocked' and template['viewed_files']==[]
    assert examples('source_review',context)['current_ids']['text_object_ids']==['t1']


def test_preflight_does_not_consume_task_and_records_reference_hashes(runtime):
    from test_managed_rebuild import plan
    manager,root,_=begin(runtime)
    task=invoke(manager,'next',root)['task']
    before=(root/'workflow/state.json').read_bytes()
    result=invoke(manager,'validate_response',root,task_id=task['task_id'],token=task['token'],
                  base_revision=task['base_revision'],result=plan())
    assert result['valid'] is True,result
    assert result['validation_binding']['referenced_files']
    assert result['task_consumed'] is False and result['office']=='not_run'
    assert (root/'workflow/state.json').read_bytes()==before


def test_refinement_keeps_rounds_and_marks_method_claim_unverified():
    from scripts.layered_review import record_refinement
    state={'run':{'id':'run-1','candidate':{'sha256':'a'*64}}}
    task={'id':'t1','target':{'slide_id':'s1'}}
    row={'issue_id':'edge','object_ids':['o1'],'problem':'rough edge',
         'expected_improvement':'clean edge','improved':False,'decision':'change_method','method_id':'crop'}
    record_refinement(state,task,{'refinement_issues':[row]})
    state['run']['id']='run-2';task['id']='t2'
    record_refinement(state,task,{'refinement_issues':[{**row,'method_id':'generate'}]})
    assert len(state['refinement_history'])==2
    assert state['refinement_history'][1]['previous_task_id']=='t1'
    assert state['refinement_history'][1]['method_verification']=='agent_reported_not_verified'
    assert state['refinement_history'][0]['method_id']=='crop'


def test_candidate_exists_does_not_certify_delivery(tmp_path):
    import hashlib
    from toolbox_manager.project_status import production_summary
    candidate=tmp_path/'runs/r1/candidate.pptx';candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b'candidate')
    wf={'status':'awaiting_edit_check','run':{'id':'r1','candidate':{'file':'runs/r1/candidate.pptx',
          'sha256':hashlib.sha256(b'candidate').hexdigest()}}}
    summary=production_summary(tmp_path,wf)
    assert summary['candidate']['state']=='matched' and summary['formal_delivery'] is False
    wf['status']='delivered';wf['delivery']='delivery/r1'
    d=tmp_path/wf['delivery'];d.mkdir(parents=True)
    (d/'delivery.json').write_text(json.dumps({'run_id':'r1','pptx_sha256':'a'*64}),encoding='utf-8')
    summary=production_summary(tmp_path,wf)
    assert summary['delivery']['state']=='missing' and summary['formal_delivery'] is False
