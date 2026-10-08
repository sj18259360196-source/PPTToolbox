"""Work diagrams are durable display metadata, never production approvals."""
import json
from pathlib import Path

import pytest

from scripts import project_journal as journal
from scripts.project_flow import merge
from toolbox_manager.pptagent_runtime import tool_result
from test_project_chain import project, check


NODES=[{'id':'plan','title':'制作计划','status':'done'},
       {'id':'text','title':'文字与排版','status':'done','after':['plan']},
       {'id':'search','title':'图标素材搜索','after':['plan']},
       {'id':'draw','title':'原生绘制','after':['search']},
       {'id':'compose','title':'整页合成','after':['text','draw']}]


def test_graph_merges_changes_and_preserves_branch_history():
    first=merge(None,NODES,source='agent',at='first')
    updated=merge(first,[{'id':'search','status':'replaced'},{'id':'draw','status':'running'}],source='pptagent',at='next')
    nodes={n['id']:n for n in updated['nodes']}
    assert nodes['search']['status']=='replaced'
    assert nodes['draw']['after']==['search'] and nodes['draw']['source']=='pptagent'
    assert nodes['compose']['after']==['text','draw']
    assert first['nodes'][2]['status']=='planned'


@pytest.mark.parametrize('patches',[
    [{'id':'plan','after':['compose']}], [{'id':'missing'}], [{'id':'plan','after':['missing']}],
    [{'id':'plan','after':['plan']}], [{'id':'plan','status':'approved'}],
    [{'id':'plan','title':'   '}], [{'id':'plan','x':10}],
    [{'id':'plan','status':'done'},{'id':'plan','status':'blocked'}],
    [{'id':'too-many-'+str(i),'title':'Node'} for i in range(65)]
])
def test_invalid_graph_does_not_mutate_previous(patches):
    old=merge(None,NODES,source='agent',at='first');before=json.dumps(old)
    with pytest.raises(ValueError):merge(old,patches,source='pptagent',at='next')
    assert json.dumps(old)==before


def test_checkpoint_flow_is_atomic_and_idempotent(project):
    _,root,_=project
    body,result=check(root,flow=NODES)
    state=journal.load(root)
    assert state['work_graph']['nodes'][0]['title']=='制作计划'
    assert journal.checkpoint(root,body)['duplicate'] is True
    assert journal.load(root)['sequence']==state['sequence']
    with pytest.raises(ValueError):check(root,event='transition',stage='plan',flow=[{'id':'plan','after':['compose']}])
    assert journal.load(root)['phase_revision']==state['phase_revision']


def test_resident_graph_updates_only_selected_project_display(project):
    manager,root,key=project
    check(root)
    initial=journal.load(root)
    result=tool_result(manager,'update_work_graph',{'project':key,'sequence':initial['sequence'],'patch_json':json.dumps(NODES)},key)
    state=journal.load(root)
    assert result['scope']=='display_only'
    assert state['phase']==initial['phase'] and state['phase_revision']==initial['phase_revision']
    assert state['checkpoints']==initial['checkpoints']
    assert state['work_graph']['nodes'][0]['source']=='pptagent'
    read=tool_result(manager,'read_project',{'project':key},key)
    assert read['work_graph']==state['work_graph']
    with pytest.raises(ValueError,match='已变化'):
        tool_result(manager,'update_work_graph',{'project':key,'sequence':initial['sequence'],'patch_json':'[{"id":"plan","status":"running"}]'},key)
    with pytest.raises(ValueError,match='选择一个项目'):
        tool_result(manager,'update_work_graph',{'project':key,'sequence':state['sequence'],'patch_json':'[]'},None)
    with pytest.raises(ValueError,match='所选项目'):
        tool_result(manager,'update_work_graph',{'project':key,'sequence':state['sequence'],'patch_json':'[]'},'another-project')


def test_graph_survives_projection_rebuild(project):
    _,root,_=project
    check(root,flow=NODES)
    before=journal.load(root)
    (root/'.ppttool/state.json').unlink()
    assert journal.load(root)['work_graph']==before['work_graph']


def test_graph_contract_available_in_existing_checkpoint_routes():
    from toolbox_manager.mcp import TOOLS
    from toolbox_manager.contracts import schemas
    tool=next(t for t in TOOLS if t[0]=='toolbox_checkpoint')
    assert 'flow' in tool[2]['properties']
    contracts=schemas(Path(__file__).resolve().parents[1])
    assert 'flow' in contracts['next']['properties']['checkpoint']['properties']
    assert 'flow' in contracts['submit']['properties']['checkpoint']['properties']
