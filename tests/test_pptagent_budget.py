import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest

from toolbox_manager.storage import Store
from toolbox_manager import pptagent as agent, pptagent_budget as budget, pptagent_metrics as metrics
from scripts import project_journal as journal
from test_project_chain import project, check


@pytest.fixture
def manager(tmp_path):
    return SimpleNamespace(store=Store(tmp_path/'data'), data=tmp_path/'data', lock=threading.RLock())


def test_windows_failures_and_restart_cannot_reset_quota(manager, monkeypatch):
    manager.store.set('pptagent_config', {'hourly_request_limit': 2, 'daily_request_limit': 3})
    clock=[100000.0]
    monkeypatch.setattr(budget.time,'time',lambda:clock[0])
    calls=[]
    def fail(*args): calls.append(1); raise TimeoutError('not persisted')
    monkeypatch.setattr(agent,'_request_json',fail)
    for _ in range(2):
        with pytest.raises(TimeoutError): agent.request_json(manager,{}, {})
    with pytest.raises(budget.RateLimited): agent.request_json(manager,{}, {})
    assert len(calls)==2
    assert metrics.snapshot(manager)['requests']==2
    restarted=SimpleNamespace(store=Store(manager.data),data=manager.data,lock=threading.RLock())
    assert budget.snapshot(restarted)['blocked']
    clock[0]+=3600
    with pytest.raises(TimeoutError): agent.request_json(restarted,{}, {})
    clock[0]+=3600
    with pytest.raises(budget.RateLimited): agent.request_json(restarted,{}, {})
    assert budget.snapshot(restarted)['last_24_hours']==3
    clock[0]=186400
    assert not budget.snapshot(restarted)['blocked']


def test_atomic_admission_across_managers(manager):
    manager.store.set('pptagent_config', {'hourly_request_limit': 3, 'daily_request_limit': 3})
    other=SimpleNamespace(store=Store(manager.data))
    def reserve(i):
        try: budget.reserve_request(manager if i%2 else other, now=100000); return True
        except budget.RateLimited:return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(20)))==3
    assert budget.snapshot(other, now=100000)['last_hour']==3


def test_stable_signature_ignores_observer_noise_but_tracks_business():
    cfg={'revision':1}
    state={'phase':{'stage':'production','at':'a'}, 'files':[{'path':'deck.pptx','mtime_ns':1,'size':10}],
           'activity':{'visual':{'count':1},'calls':[{'tool':'workflow.next','status':'completed','task_id':'t',
                  'at':'a','evidence_id':'audit-1','elapsed_seconds':3}], 'issues':[]}}
    original=agent.summary_signature(cfg,state)
    changed=copy.deepcopy(state);changed['sequence']=2;changed['phase']['at']='b'
    changed['files'][0].update(mtime_ns=999,size=999)
    changed['activity']['calls'][0].update(at='b',evidence_id='audit-2',elapsed_seconds=55)
    changed['activity']['visual']['count']=1000
    changed['activity']['calls'].append(copy.deepcopy(changed['activity']['calls'][0]))
    assert agent.summary_signature(cfg,changed)==original
    for change in ('stage','file','error'):
        value=copy.deepcopy(state)
        if change=='stage':value['phase']['stage']='revision'
        if change=='file':value['files'].append({'path':'new.pptx'})
        if change=='error':value['activity']['calls'][0]['status']='failed'
        assert agent.summary_signature(cfg,value)!=original


def enabled(project):
    m,root,key=project;check(root)
    m.store.set('pptagent_config',{'enabled':True,'revision':1,'endpoint':'http://127.0.0.1/api','model':'fixture'})
    return m,root,key


def test_discarded_summary_remembers_attempt_across_restart(project,monkeypatch):
    m,root,key=enabled(project);state=journal.load(root);cfg=agent.config(m)
    signature=agent.summary_signature(cfg,state)
    calls=[]
    def request(*args):
        calls.append(1);journal.update(root,{'label':'changed'},source='human')
        return {'summary':'old','next_hint':'old','evidence_ids':['check-0'],'recommended_ids':[]}
    monkeypatch.setattr(agent,'request_summary',request)
    agent.Worker(m).process(key,state['sequence'],signature)
    assert journal.load(root)['summary']=={}
    assert budget.snapshot(m,key)['summary_outcome']=='discarded'
    assert budget.summary_gate(m,key,signature)['reason']=='already_attempted'
    restarted=agent.Worker(m);restarted.offer(key,journal.load(root))
    assert restarted.pending[key][2]>agent.time.monotonic()+55
    latest=journal.load(root)
    restarted.process(key,latest['sequence'],agent.summary_signature(cfg,latest))
    assert calls==[1]


def test_observer_update_during_api_saves_summary_without_new_request(project,monkeypatch):
    m,root,key=enabled(project);state=journal.load(root);signature=agent.summary_signature(agent.config(m),state)
    def request(*args):
        journal.update(root,{'files':state.get('files',[])},source='observer')
        return {'summary':'valid','next_hint':'next','evidence_ids':['check-0'],'recommended_ids':[]}
    monkeypatch.setattr(agent,'request_summary',request)
    worker=agent.Worker(m);worker.process(key,state['sequence'],signature)
    assert journal.load(root)['summary']['summary']=='valid'
    agent.Worker(m).offer(key,journal.load(root))
    assert budget.summary_gate(m,key,signature)['reason']=='already_attempted'


def test_pending_same_signature_refreshes_sequence_without_starvation(project,monkeypatch):
    m,root,key=enabled(project);worker=agent.Worker(m);state=journal.load(root)
    worker.offer(key,state);due=worker.pending[key][2]
    changed={**state,'sequence':state['sequence']+1}
    worker.offer(key,changed)
    assert worker.pending[key][0]==changed['sequence']
    assert worker.pending[key][2]==due


def test_old_offer_cannot_remove_new_pending_summary(project):
    m,root,key=enabled(project);state=journal.load(root);cfg=agent.config(m)
    signature=agent.summary_signature(cfg,state)
    budget.summary_gate(m,key,signature,reserve=True)
    worker=agent.Worker(m)
    changed=copy.deepcopy(state);changed['label']='new'
    worker.offer(key,changed)
    worker.offer(key,state)
    assert worker.pending[key][1]==agent.summary_signature(cfg,changed)


def test_same_signature_failure_no_automatic_retry(project,monkeypatch):
    m,root,key=enabled(project);state=journal.load(root);signature=agent.summary_signature(agent.config(m),state)
    calls=[]
    def fail(*args):calls.append(1);raise TimeoutError('private')
    monkeypatch.setattr(agent,'request_summary',fail)
    agent.Worker(m).process(key,state['sequence'],signature)
    latest=journal.load(root)
    agent.Worker(m).process(key,latest['sequence'],signature)
    assert calls==[1] and latest['summary']['status']=='unavailable'
    assert 'private' not in str(m.store.get(budget.KEY))


def test_settings_defaults_validation_preservation_and_budget_visibility(project):
    m,root,key=project
    cfg=agent.config(m)
    assert all(cfg[k]==v for k,v in budget.DEFAULTS.items())
    body={'enabled':False,'revision':cfg['revision'],'endpoint':'','model':'','daily_request_limit':1}
    cfg=agent.save_config(m,body)
    budget.reserve_request(m)
    cfg=agent.save_config(m,{'enabled':False,'revision':cfg['revision'],'endpoint':'','model':''})
    assert cfg['daily_request_limit']==1 and budget.snapshot(m)['blocked']
    with pytest.raises(ValueError):
        agent.save_config(m,{'enabled':False,'revision':cfg['revision'],'endpoint':'','model':'','summary_interval_seconds':0})
    m.store.set('pptagent_config',{**cfg,'enabled':True,'endpoint':'https://example.invalid','model':'fixture'})
    status=metrics.project_status(m,key,journal.load(root))
    assert status['status']=='rate_limited' and status['metrics']['budget']['blocked']


def test_summary_gate_atomic_and_cooldown_does_not_block_other_project(manager):
    assert budget.summary_gate(manager,'a','one',reserve=True,now=100)['allowed']
    assert not budget.summary_gate(manager,'a','two',reserve=True,now=159)['allowed']
    assert budget.summary_gate(manager,'b','one',reserve=True,now=159)['allowed']
    assert budget.summary_gate(manager,'a','two',reserve=True,now=160)['allowed']


def test_budget_race_defers_without_forgetting_latest_sequence(project,monkeypatch):
    m,root,key=enabled(project);state=journal.load(root)
    clock=[100000.0];monkeypatch.setattr(budget.time,'time',lambda:clock[0])
    signature=agent.summary_signature(agent.config(m),state)
    def blocked(*args):raise budget.RateLimited('request_budget',clock[0]+3600)
    monkeypatch.setattr(agent,'request_summary',blocked)
    worker=agent.Worker(m);worker.process(key,state['sequence'],signature)
    assert key not in worker.seen and key in worker.pending
    latest=journal.load(root);worker.offer(key,latest)
    assert worker.pending[key][0]==latest['sequence']
    assert budget.snapshot(m,key)['summary_outcome']=='rate_limited'
    assert budget.summary_gate(m,key,signature,now=clock[0]+3600)['allowed']
