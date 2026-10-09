"""Evidence-based ownership, branches, and repeat delivery cycles."""
import copy
import json
import pytest
from scripts.project_flow import merge, diagnostics
from toolbox_manager.flow_semantics import assign, connect_recorded, lifecycle, project, hydrate
from toolbox_manager import assistant_recording as rec
from test_pptagent_responses import project as fixture_project


def node(name, event=1, task='task-a', **extra):
    return {'id':name,'source':'pptagent','status':'observed','title':name,'kind':'native_draw','stage':'production',
            'task_ids':[task] if task else [],'evidence_ids':['audit-'+str(event)],'after':[],
            'first_at':'2026-10-09T10:00:00Z', **extra}


def test_owned_calls_connected_as_record_sequence_without_dependency():
    rows=assign([node('a'),node('b',2)])
    connect_recorded(rows)
    assert rows[1]['after']==['a'] and rows[1]['links'][0]['relation']=='sequence'
    assert rows[1]['links'][0]['basis']=='recorded'
    assert rows[0]['group_id']==rows[1]['group_id'] and '第 1 轮' in rows[1]['group_label']
    assert '依赖' in rows[1]['links'][0]['label']


@pytest.mark.parametrize('status',['running','outcome_unknown'])
def test_unknown_or_running_does_not_imply_serial_execution(status):
    rows=assign([node('a',status=status),node('b',2)])
    connect_recorded(rows)
    assert rows[1]['after']==[] and rows[0]['group_id']==rows[1]['group_id']


def test_overlapping_calls_are_not_forced_into_serial_dependency():
    rows=assign([node('a',started_at='2026-10-09T10:00:00Z',finished_at='2026-10-09T10:02:00Z'),
                 node('b',2,started_at='2026-10-09T10:01:00Z')])
    assert connect_recorded(rows)[1]['after']==[]


def test_explicit_parallel_fork_and_join_survive_automatic_connection():
    nodes=[node('start'),node('left',2,after=['start'],links=[{'from':'start','relation':'fork','basis':'agent'}]),
           node('right',3,after=['start'],links=[{'from':'start','relation':'fork','basis':'agent'}]),
           node('join',4,after=['left','right'],join_policy='all',links=[{'from':p,'relation':'merge','basis':'agent'} for p in ['left','right']])]
    expected=copy.deepcopy(nodes)
    connect_recorded(assign(nodes))
    assert [n['after'] for n in nodes]==[n['after'] for n in expected]
    assert merge({'nodes':nodes},[{'id':'join'}],source='agent',at='now')['nodes'][-1]['join_policy']=='all'


def test_grouping_is_membership_and_never_execution_order():
    rows=project([node('parent'),node('child',2,after=['parent'],links=[{'from':'parent','relation':'grouping','basis':'recorded'}])])
    assert rows[1]['membership_ids']==['parent']
    # Software can record actual audit order, but cannot call the group a dependency.
    assert all(l['relation']!='dependency' for n in rows for l in n.get('links',[]))


def test_missing_round_evidence_is_visible_not_guessed_from_edit_time():
    n=node('old');n.pop('first_at');n['updated_at']='2026-10-09T13:00:00Z'
    life={'items':[{'event':'region_reopened','at':'2026-10-09T12:00:00Z','round':2,'revision':4}]}
    assign([n],life)
    assert 'round' not in n and '轮次待确认' in n['group_label']


def test_round_changes_from_revision_evidence_and_task_ids_can_repeat():
    life={'items':[{'event':'region_reopened','at':'2026-10-09T12:00:00Z','round':2,'revision':4}]}
    rows=assign([node('v1'),node('v2',2,first_at='2026-10-09T12:01:00Z')],life)
    assert [n['round'] for n in rows]==[1,2]
    connect_recorded(rows)
    assert rows[1]['after']==[] and rows[0]['group_id']!=rows[1]['group_id']


def test_two_deliveries_feedback_revision_chain_is_acyclic_and_version_scoped():
    life={'items':[{'id':'life-v1','event':'delivery_created','round':1,'revision':3,'at':'2026-10-09T11:00:00Z','version':'run-1','evidence_id':'workflow-3','presented':True,'accepted':True},
                   {'id':'life-repair','event':'region_reopened','round':2,'revision':4,'at':'2026-10-09T12:00:00Z','input_version':'run-1','evidence_id':'workflow-4'},
                   {'id':'life-v2','event':'delivery_created','round':2,'revision':6,'at':'2026-10-09T13:00:00Z','version':'run-2','evidence_id':'workflow-6'}]}
    original=[node('draw-v1'),node('draw-v2',2,first_at='2026-10-09T12:01:00Z')];before=copy.deepcopy(original)
    rows=project(original,life);by_id={n['id']:n for n in rows}
    assert original==before
    assert by_id['life-repair']['after']==['life-v1-feedback']
    assert by_id['draw-v2']['after']==['life-repair']
    assert by_id['life-v1-feedback']['status']=='done'
    assert by_id['life-v2-feedback']['status']=='planned'
    assert by_id['life-v2-feedback']['version']=='run-2'
    assert merge({'nodes':rows},[{'id':'life-v2'}],source='agent',at='now')


def test_result_text_does_not_hide_missing_exit():
    rows=project([node('a',result='工具调用已完成')])
    assert rows[0]['exit_reason']=='relation_pending' and diagnostics(rows)


def test_existing_cross_round_edge_does_not_make_feedback_projection_cyclic():
    life={'items':[{'id':'life-d','event':'delivery_created','round':1,'revision':3,'at':'2026-10-09T11:00:00Z','version':'r1','evidence_id':'workflow-3'},
                   {'id':'life-r','event':'region_reopened','round':2,'revision':4,'at':'2026-10-09T12:00:00Z','evidence_id':'workflow-4'}]}
    rows=project([node('old',after=['new']),node('new',2,first_at='2026-10-09T12:01:00Z')],life)
    assert next(n for n in rows if n['id']=='new').get('relation_issue')
    assert merge({'nodes':rows},[{'id':'life-r'}],source='agent',at='now')


def test_join_policy_requires_multiple_explicit_merge_branches():
    with pytest.raises(ValueError,match='汇合条件'):
        merge({'nodes':[node('a'),node('b',2,after=['a'])]},[{'id':'b','join_policy':'all'}],source='agent',at='now')


def test_lifecycle_never_uses_other_projects_consent(fixture_project):
    m,root,key,_=fixture_project
    wf={'project_id':'project-a','status':'delivered','run':{'id':'run-2'},'history':[
        {'revision':3,'event':'delivery_created','at':'2026-10-09T11:00:00Z','detail':{'dir':'delivery/run-1'}},
        {'revision':4,'event':'region_reopened','at':'2026-10-09T12:00:00Z','detail':{}},
        {'revision':5,'event':'revision_candidate_created','at':'2026-10-09T12:30:00Z','detail':{}},
        {'revision':6,'event':'delivery_created','at':'2026-10-09T13:00:00Z','detail':{'dir':'delivery/run-2'}}]}
    m.store.set('retrospective:a',{'source':{'project_id':'project-a','run_id':'run-1'},'presented':{},'accept':{},'audit':[]})
    m.store.set('retrospective:b',{'source':{'project_id':'project-b','run_id':'run-2'},'presented':{},'accept':{}})
    life=lifecycle(m,wf)
    assert life['round']==2 and len(life['items'])==3
    assert life['items'][0]['accepted'] and 'accepted' not in life['items'][-1]


def test_hydrate_reads_only_scoped_audit_and_does_not_change_saved_nodes(fixture_project):
    m,root,key,_=fixture_project
    m.store.event('tool.finished','fixture',details={'project':str(root),'revision_before':7})
    m.store.event('tool.finished','other',details={'project':str(root/'other'),'revision_before':99})
    with m.store.db() as db:rows=db.execute('SELECT id FROM events ORDER BY id DESC LIMIT 2').fetchall()
    other,current=[r['id'] for r in rows]
    ns=[node('a',current),node('b',other)]
    for n in ns:n.pop('first_at')
    found=hydrate(m,root,ns)
    assert found[0]['workflow_revision']==7 and 'workflow_revision' not in found[1]
    assert 'first_at' not in ns[0]


def test_batch_ownership_and_model_cannot_claim_user_acceptance(fixture_project):
    m,root,key,_=fixture_project
    m.store.event('tool.finished','fixture',details={'project':str(root),'call_id':'one','task_id':'task-a','tool_id':'graphics.construct','command_status':'completed'})
    b=rec.prepare(m,key)
    assert b['observations'][0]['group_label'] and 'lifecycle' in b
    with pytest.raises(ValueError,match='实际调用'):
        rec.commit(m,key,b['batch_id'],{'summary':'记录','note':'记录','patches':[{'id':b['observations'][0]['id'],'exit_reason':'accepted'}]})
