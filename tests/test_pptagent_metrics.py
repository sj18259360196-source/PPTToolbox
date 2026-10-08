import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from toolbox_manager.storage import Store
from toolbox_manager import pptagent_metrics as metrics, pptagent

@pytest.fixture
def manager(tmp_path):
    return SimpleNamespace(store=Store(tmp_path/'data'),data=tmp_path/'data',lock=threading.RLock())

def response():
    return {'status':'completed','usage':{'input_tokens':100,'output_tokens':30,'total_tokens':130,
             'input_tokens_details':{'cached_tokens':40},'output_tokens_details':{'reasoning_tokens':10}}}

def test_usage_maps_both_protocols_without_double_counting():
    assert metrics.usage(response())=={'input_tokens':100,'output_tokens':30,'total_tokens':130,'cached_tokens':40,'reasoning_tokens':10}
    assert metrics.usage({'usage':{'prompt_tokens':8,'completion_tokens':2}})['total_tokens']==10
    assert metrics.usage({}) is None
    assert metrics.usage({'usage':{'input_tokens':True,'output_tokens':-1}}) is None

def test_requests_attribute_project_task_and_unknown_failures(manager,monkeypatch):
    monkeypatch.setattr(pptagent,'_request_json',lambda *a:response())
    with metrics.scope(project='p1',task='t1',kind='task'):
        pptagent.request_json(manager,{'model':'fixture'}, {})
    def fail(*a):raise TimeoutError('private-provider-secret')
    monkeypatch.setattr(pptagent,'_request_json',fail)
    with metrics.scope(project='p2',kind='summary'),pytest.raises(TimeoutError):
        pptagent.request_json(manager,{'model':'fixture'}, {})
    total=metrics.snapshot(manager)
    assert (total['requests'],total['succeeded'],total['failed'],total['unknown'],total['reported'])==(2,1,1,1,1)
    assert total['total_tokens']==130 and total['cached_tokens']==40
    assert metrics.snapshot(manager,'p1')['total_tokens']==130
    assert metrics.snapshot(manager,'p2')['total_tokens']==0
    assert total['task_usage']['t1']['total_tokens']==130
    assert 'private-provider-secret' not in str(manager.store.get(metrics.KEY))

def test_idempotent_finish_and_partial_failure_retains_reported_usage(manager):
    ticket=metrics.start(manager,{})
    value=response();value['status']='incomplete'
    metrics.finish(manager,ticket,value);metrics.finish(manager,ticket,value)
    result=metrics.snapshot(manager)
    assert result['failed']==1 and result['total_tokens']==130 and result['reported']==1

def test_totals_survive_history_retention_and_concurrent_updates(manager):
    def request(_):
        with metrics.scope(project='p'):
            metrics.finish(manager,metrics.start(manager,{}),response())
    with ThreadPoolExecutor(max_workers=5) as executor:list(executor.map(request,range(110)))
    result=metrics.snapshot(manager,'p')
    assert result['requests']==result['succeeded']==110
    assert result['total_tokens']==14300 and result['active']==0
    assert len(result['recent'])==12

def test_recover_marks_unknown_once_and_effects_are_project_scoped(manager):
    with metrics.scope(project='p'):metrics.start(manager,{})
    assert metrics.snapshot(manager,'p')['active']==1
    metrics.recover(manager);metrics.recover(manager)
    result=metrics.snapshot(manager,'p')
    assert result['interrupted']==result['unknown']==1 and result['active']==0
    metrics.effect(manager,'p','summaries_saved')
    metrics.effect(manager,'p','evidence_reviewed',5)
    assert metrics.snapshot(manager,'p')['summaries_saved']==1
    assert metrics.snapshot(manager,'p')['evidence_reviewed']==5
    assert metrics.snapshot(manager,'other')['summaries_saved']==0

def test_project_assistance_reports_queue_work_result_and_failure(manager):
    manager.store.set('pptagent_config',{'enabled':True,'endpoint':'https://example.invalid/responses','model':'test'})
    manager.pptagent_worker=SimpleNamespace(lock=threading.Lock(),pending={},processing=set())
    state={'summary':{'status':'ready','at':'2026-10-08T00:00:00Z','evidence_ids':['one','two']}}
    assert metrics.project_status(manager,'p',state)['status']=='ready'
    manager.pptagent_worker.pending['p']=(1,'signature',0)
    assert metrics.project_status(manager,'p',state)['status']=='queued'
    manager.pptagent_worker.processing.add('p')
    assert metrics.project_status(manager,'p',state)['status']=='working'
    manager.pptagent_worker.pending.clear();manager.pptagent_worker.processing.clear()
    manager.store.set('pptagent_tasks',[{'id':'t','project':'p','status':'failed','updated_at':'2026-10-08T01:00:00Z','result':'failed'}])
    assert metrics.project_status(manager,'p',state)['status']=='task_failed'

def test_usage_http_endpoint_requires_session_and_returns_durable_totals(manager):
    import json
    from http.server import ThreadingHTTPServer
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from toolbox_manager.server import Handler
    metrics.finish(manager,metrics.start(manager,{}),response())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.manager=manager;server.token='fixture';server.origin=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url=server.origin+'/api/pptagent.metrics'
        with pytest.raises(HTTPError) as denied:urlopen(url)
        assert denied.value.code==401
        with urlopen(Request(url,headers={'Authorization':'Bearer fixture'})) as result:
            data=json.load(result)
        assert data['ok'] and data['result']['total_tokens']==130
    finally:server.shutdown();server.server_close();thread.join()
