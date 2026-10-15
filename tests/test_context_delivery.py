"""Deterministic delivery/regression fixtures. Never claims visual or Office acceptance."""
import copy
import json
import os
from pathlib import Path
import pytest
from PIL import Image
from test_managed_rebuild import runtime, begin, invoke, response, plan, ready
from toolbox_manager.context_delivery import compact_task, text_size
from toolbox_manager.execution import cli_arguments
from toolbox_manager.project_inspection import inspect
from toolbox_manager.contracts import validate_result
from toolbox_manager.validation_errors import ContractError
from common import sha256, read_json


def test_reviewed_bootstrap_matches_packaged_documents():
    from test_managed_rebuild import ROOT
    from toolbox_manager.storage import digest
    manifest=read_json(ROOT/'assets/context-bootstrap.json')
    assert manifest['format']=='ppt-context-bootstrap/1'
    for relative,expected in manifest['sources'].items():
        # Match Manager.document's text digest, including BOM/newline normalization.
        actual=digest((ROOT/relative).read_text(encoding='utf-8-sig'))
        assert actual==expected, 'Reviewed bootstrap digest needs explicit review after bundled document changes: '+relative


def test_production_preserves_all_policy_and_skill_fields(runtime):
    m, _, _ = runtime
    full=m.context(); compact=m.context(profile='production')
    assert compact['context_profile']=='production'
    for key in full:
        if key!='startup_prompt':assert compact[key]==full[key], key
    assert 'startup_prompt' not in compact
    assert text_size(compact)['json_chars'] < text_size(full)['json_chars']
    assert compact['workflow_defaults']['return_next'] is True


@pytest.mark.parametrize('path',['SKILL.md','给模型的启动指令.txt'])
def test_custom_bootstrap_falls_back_without_dropping_owner_text(runtime,path):
    m,_,_=runtime
    doc=m.document(path)
    m.save_document(path,doc['content']+'\nOwner-specific constraint 987.',doc['revision'])
    result=m.context(profile='production')
    assert result['context_profile']=='full'
    assert 'Owner-specific constraint 987.' in result['skill']+result['startup_prompt']


def test_changed_bootstrap_fails_open(runtime,monkeypatch):
    m,_,_=runtime; original=m.document
    def changed(path,*args,**kw):
        result=original(path,*args,**kw)
        if path=='SKILL.md':result['base_sha256']='0'*64
        return result
    monkeypatch.setattr(m,'document',changed)
    assert m.context(profile='production')['context_profile']=='full'


def test_every_task_kind_and_future_constraint_survives(tmp_path):
    from toolbox_manager.contracts import result_contracts
    from test_managed_rebuild import ROOT
    kinds,_=result_contracts(ROOT)
    for kind in [*kinds,'future-task']:
        packet={'kind':kind,'task_id':'task-1','context':{'future_quality_gate':{'required':True}},
                'future_packet_extension':{'must_do':'preserve me'}}
        template={'task_id':'task-1','result':{'status':'blocked'}}
        packet_file=tmp_path/'packet.json';packet_file.write_text(json.dumps(packet))
        template_file=tmp_path/'template.json';template_file.write_text(json.dumps(template))
        task={'kind':kind,'packet':str(packet_file),'response_template':str(template_file)}
        original=copy.deepcopy(packet)
        result=compact_task(task,packet,template)
        assert result['context']==packet['context']
        assert result['packet_metadata']['future_packet_extension']==packet['future_packet_extension']
        assert result['response']==template and result['required_read_files']==[]
        assert packet==original


def test_views_pagination_does_not_return_other_page_images(runtime,monkeypatch):
    # Inject only the view list of a synthetic packet to exercise multiple pages.
    # The real workflow state and immutable task file are not edited.
    import common
    m,p,_=begin(runtime)
    t=invoke(m,'next',p)['task'];packet=read_json(Path(t['packet']))
    original=common.read_json;files=[]
    for i in range(7):
        name='view-'+str(i)+'.png';Image.new('RGB',(12,12),'white').save(p/name);files.append(name)
    packet['required_view_files']=files
    def read(path):
        return packet if Path(path).resolve()==Path(t['packet']).resolve() else original(path)
    monkeypatch.setattr(common,'read_json',read)
    before=sha256(p/'workflow/state.json')
    first=inspect(m,{'project':str(p),'action':'views','offset':0,'limit':1})
    second=inspect(m,{'project':str(p),'action':'views','offset':1,'limit':1})
    for result in [first,second]:
        assert result['total']==7
        assert len(result['items'])==len(result['view_strategy']['required'])==1
        assert result['items'][0]['path']==result['view_strategy']['required'][0]['path']
        assert result['view_strategy']['required_file_bytes']==result['items'][0]['file_bytes']
    assert first['view_strategy']['required'][0]['path']!=second['view_strategy']['required'][0]['path']
    assert before==sha256(p/'workflow/state.json')


def test_cli_json_and_compact_share_task_validation(runtime):
    m,p,_=begin(runtime)
    task=invoke(m,'next',p,response_detail='compact')['task']
    body={k:task[k] for k in ['task_id','token','base_revision']}
    body['result']=plan();body['response_detail']='compact'
    request=p/'request.json';request.write_text(json.dumps(body),encoding='utf-8')
    args=cli_arguments(m,'submit',['--project',str(p),'--request-json',str(request)])
    assert args=={'project':str(p),**body}
    accepted=m.execute('workflow.submit',['--project',str(p),'--request-json',str(request)])
    assert accepted['command_status']=='completed',accepted
    assert accepted['accepted_task'] and accepted['submission']['replay_allowed'] is False
    assert 'stdout' not in accepted and accepted['delivery_metrics']['json_utf8_bytes']>0
    assert (Path(accepted['output_directory'])/'stdout.json').is_file()
    replay=m.execute('workflow.submit',['--project',str(p),'--request-json',str(request)])
    assert replay['command_status']!='completed'


def test_structured_diagnostics_do_not_echo_private_values(runtime):
    m,p,_=begin(runtime)
    task=invoke(m,'next',p)['task']; before=sha256(p/'workflow/state.json')
    bad=plan();bad['regions'][0]['role']='PRIVATE-SECRET-ROLE'
    with pytest.raises(ContractError) as caught:validate_result('page_plan',bad,m.root)
    row=caught.value.diagnostics[0]
    assert row['path']=='/result/regions/0/role' and row['constraint']=='enum'
    assert 'content' in row['expected']
    assert 'PRIVATE-SECRET-ROLE' not in json.dumps(caught.value.diagnostics)
    identity={k:task[k] for k in ['task_id','token','base_revision']}
    result=invoke(m,'validate_response',p,**identity,result=bad)
    assert result['valid'] is False and result['errors'][0]==row
    assert before==sha256(p/'workflow/state.json')


def test_total_delivery_includes_legacy_required_reads(runtime):
    m,p,_=begin(runtime);rows=[]
    for payload in [plan(),{'objects':[{'id':'label','kind':'text','text':'FIXTURE 123','bbox':[10,10,260,40]}],
                           'source_notes':'Deterministic fixture; no visual acceptance'}]:
        full=invoke(m,'next',p)
        compact=invoke(m,'next',p,response_detail='compact')
        task=full['task']; ct=compact['task']
        legacy=copy.deepcopy(task)
        legacy.pop('context');legacy.pop('response')
        legacy['context_summary']={k:v for k,v in task['context'].items() if k in {
            'region','local_size','coordinate_contract','native_first','native_first_meaning',
            'required_edit_actions','submission_constraints','asset_policy_revision'}}
        legacy['related_tools']=[{k:v for k,v in t.items() if k in {'id','title','manuals'}} for t in task['related_tools']]
        required_chars=sum(len(Path(task[key]).read_text(encoding='utf-8')) for key in ['packet','response_template'])
        old_total=text_size(legacy)['json_chars']+required_chars
        new_total=text_size(ct)['json_chars']
        assert ct['context']==task['context'] and ct['response']==task['response']
        assert new_total<old_total
        rows.append({'kind':task['kind'],'old_compact_task_plus_required_reads_chars':old_total,
                     'new_inline_task_chars':new_total,'reduction':round(1-new_total/old_total,4),
                     'required_extra_text_reads_before':2,'required_extra_text_reads_after':0})
        if task['kind']=='region_objects':
            from test_managed_rebuild import declare
            declare(m,p,'production')
        submitted=response(m,p,payload,task)
        assert submitted['command_status']=='completed',submitted
    destination=os.environ.get('CONTEXT_EFFICIENCY_REPORT')
    if destination:
        Path(destination).write_text(json.dumps({'scope':'Synthetic task delivery accounting; excludes optional manual reads, model tokens, images and Office quality',
                                                'tasks':rows},indent=2),encoding='utf-8')


def test_handoff_has_pending_findings_and_never_embeds_token(tmp_path):
    from handoff_summary import render
    from workflow_store import brief
    (tmp_path/'review.json').write_text(json.dumps({'result':{'status':'needs_changes','note':'Wrong digit on object t7',
                                                           'observations':['t7 must read 123']}}))
    state={'project_id':'fixture','revision':7,'status':'awaiting_revision','pages':[],
           'active_task':None,'run':{'id':'run-1','dir':'runs/run-1','reviews':{'full':{'file':'review.json','sha256':'fixture'}}}}
    before=copy.deepcopy(state)
    text=render(tmp_path,state,brief(state))
    assert 'rebuild_revise' in text and 'Wrong digit on object t7' in text and 'review.json' in text
    assert state==before
    state['active_task']={'id':'task-9','kind':'review_full','target':{},'token':'PRIVATE-TOKEN','packet':'packet.json'}
    assert 'PRIVATE-TOKEN' not in render(tmp_path,state,brief(state))
    state['operation']={'kind':'render'}
    assert 'Do not replay unknown effects' in render(tmp_path,state,brief(state))


def test_discovery_is_bounded_but_server_rejects_invalid_current_result(runtime):
    from toolbox_manager.mcp import MCP
    from toolbox_manager.contracts import schemas, current_result_contract
    from jsonschema import Draft202012Validator
    m,p,_=begin(runtime)
    shim=object.__new__(MCP);shim.manager=m
    specs={name:schema for name,_,schema in shim.specs()}
    advertised=specs['rebuild_submit']
    assert text_size(advertised)['json_chars'] < text_size(schemas(m.root)['submit'])['json_chars']/2
    task=invoke(m,'next',p)['task']
    actual=inspect(m,{'project':str(p),'action':'contract'})
    assert actual['task_id']==task['task_id']
    assert actual['result_schema']==current_result_contract('page_plan',m.root)
    assert '$defs' not in actual['result_schema']
    for payload in [plan(),{'regions':[]},{'regions':'INVALID'}]:
        scoped=list(Draft202012Validator(actual['result_schema']).iter_errors(payload))
        try:validate_result('page_plan',payload,m.root); rejected=False
        except ValueError:rejected=True
        assert bool(scoped)==rejected
    bad=plan();bad['regions'][0]['role']='WRONG'
    result=response(m,p,bad,task)
    assert result['command_status']!='completed'
    assert result['error']['diagnostics']
    assert invoke(m,'next',p)['task']['task_id']==task['task_id']
