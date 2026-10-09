"""Decision/merge metadata, iteration isolation, and read-only old-history projection."""
import copy
import pytest

from scripts.project_flow import merge, STEP_TYPES
from toolbox_manager.project_status import graph, reconcile, step_kind


def test_typed_merges_revision_rounds_and_legacy_patches():
    patches=[{'id':'text','kind':'text'},{'id':'draw','kind':'native_draw'},
        {'id':'compose','kind':'compose','after':['text','draw'],
         'links':[{'from':p,'relation':'merge','label':'素材已就绪','basis':'agent'} for p in ['text','draw']]},
        {'id':'review1','kind':'visual_review','after':['compose'],'round':1},
        {'id':'feedback','kind':'feedback','after':['review1'],'result':'需修改标题'},
        {'id':'repair2','kind':'repair','after':['feedback'],'round':2,'task_ids':['task-2'],
         'links':[{'from':'feedback','relation':'revision','basis':'recorded','evidence_ids':['feedback-1']}],
         'next_action':'重新检查标题'},
        {'id':'review2','kind':'recheck','after':['repair2'],'round':2}]
    old=merge({},patches,source='agent',at='a')
    new=merge(old,[{'id':'compose','after':['draw']}],source='pptagent',at='b')
    assert new['nodes'][2]['links']==[old['nodes'][2]['links'][1]]
    assert old['nodes'][2]['after']==['text','draw']
    assert new['nodes'][-1]['round']==2
    assert len(STEP_TYPES)==33


@pytest.mark.parametrize('link',[
    {'from':'missing','relation':'merge'}, {'from':'a','relation':'approved'},
    {'from':'a','relation':'dependency','basis':'verified_by_model'},
])
def test_invalid_link_is_atomic(link):
    previous=merge({},[{'id':'a','kind':'plan'}],source='agent',at='a')
    before=copy.deepcopy(previous)
    with pytest.raises(ValueError):
        merge(previous,[{'id':'b','kind':'compose','after':['a'],'links':[link]}],source='agent',at='b')
    assert previous==before


def call(identifier,kind,status='completed'):
    return {'id':identifier,'task_id':identifier,'task_kind':kind,'tool':'workflow.submit',
            'status':status,'at':'2026-10-09T10:00:00Z','evidence_id':'e-'+identifier}


def reachable(nodes,start,target):
    visited={start}
    while True:
        added={n['id'] for n in nodes if set(n['after'])&visited}-visited
        if not added:return target in visited
        visited|=added


def test_compose_joins_review_delivery_as_explicit_suggestion_not_completion():
    state={'phase':{'stage':'production'},'activity':{'calls':[call('assemble','candidate')]}}
    before=copy.deepcopy(state);view=graph(state);nodes=view['nodes']
    compose=next(n for n in nodes if n.get('kind')=='compose')
    preview=next(n for n in nodes if n.get('kind')=='preview')
    assert reachable(nodes,compose['id'],preview['id'])
    assert reachable(nodes,preview['id'],'delivery')
    assert preview['status']=='planned' and preview['source']=='suggested'
    assert all(l['basis']=='suggested' for l in preview['links'])
    assert not view['diagnostics'] and state==before


def test_review_failures_stay_in_their_task_occurrence():
    bad=call('first','review_local','tool_failed');good=call('second','review_local')
    nodes=graph({'activity':{'calls':[bad,good],'issues':reconcile([],[bad,good])}})['nodes']
    reviews=[n for n in nodes if n.get('kind')=='detail_review']
    assert len(reviews)==2
    assert next(n for n in reviews if n['task_ids']==['first'])['status']=='failed'
    assert next(n for n in reviews if n['task_ids']==['second'])['status']=='observed'


def test_historical_task_kinds_are_not_misclassified_as_compose():
    for kind,expected in {'page_plan':'region_plan','region_objects':'native_draw',
            'source_review':'source_text','review_full':'visual_review','review_local':'detail_review',
            'editable_behavior':'edit_verify','reproducibility':'reproducibility'}.items():
        assert step_kind('workflow.submit',kind)==expected


def test_checkpoint_adjustments_are_observations_and_dont_advance_phase():
    state={'phase':{'stage':'revision','status':'running'},'checkpoints':[
        {'checkpoint_id':'change1','event':'replan','stage':'revision','result_summary':'缩小修订范围','next_action':'核对局部'},
        {'checkpoint_id':'resume1','event':'resume','stage':'revision','result_summary':'恢复项目','next_action':'读取任务'}]}
    before=copy.deepcopy(state);nodes=graph(state)['nodes']
    changes=[n for n in nodes if n.get('source')=='checkpoint']
    assert len(changes)==2 and changes[1]['links'][0]['relation']=='sequence'
    assert changes[0]['result']=='缩小修订范围' and changes[0]['next_action']=='核对局部'
    assert state==before


def test_custom_dangling_steps_are_advice_not_failed_tasks():
    state={'work_graph':merge({},[{'id':'custom','title':'特定图案校对','stage':'revision'}],source='agent',at='a')}
    view=graph(state)
    assert view['diagnostics'][0]['node_id']=='custom'
    assert view['nodes'][0]['status']=='planned'
    assert view['nodes'][0]['after']==[]


def test_many_observed_tasks_are_bounded_and_history_is_not_mutated():
    state={'activity':{'calls':[call(str(i),'review_local') for i in range(90)]}}
    before=copy.deepcopy(state);view=graph(state)
    assert len(view['nodes'])<=64
    assert len([n for n in view['nodes'] if n.get('source')=='observer'])==16
    assert '16' in view['relationship_note'] and state==before
