"""Durable recording boundaries with an isolated provider and project store."""
import json,threading,time
import pytest
from scripts import project_journal as journal
from toolbox_manager import assistant_recording as rec, assistant_scheduler as sched, pptagent as agent
from test_pptagent_responses import project,response

def emit(p,n=1,**extra):
 m,root,key,_=p
 for i in range(n):m.store.event('tool.finished','fixture',details={'project':str(root),'call_id':f'call-{i}',
  'tool_id':'graphics.construct','command_status':'completed',**extra})

def update(**kw):return {'summary':'已整理调用','note':'继续正常制作','patches':[],**kw}

def clear_due(root):
 s=journal.load(root);d=s.get('assistant_dispatch',{})
 journal.update(root,{'assistant_dispatch':{**d,'attempted_at':0,'retry_at':0,'lease_until':0}})

def test_pagination_and_project_scope(project):
 m,root,key,_=project;emit(project,181)
 m.store.event('tool.finished','other',details={'project':str(root/'other')})
 first=rec.activity(m,key,0,160);last=rec.activity(m,key,first['next_cursor'],160)
 assert len(first['events'])==160 and first['has_more'] and len(last['events'])==21 and not last['has_more']
 assert not set(e['event_id'] for e in first['events'])&set(e['event_id'] for e in last['events'])

def test_atomic_idempotent_and_production_keeps_advancing(project):
 m,root,key,_=project;emit(project,2);b=rec.prepare(m,key)
 journal.update(root,{'files':[{'path':'new.pptx'}]});emit(project,1,call_id='late')
 assert rec.commit(m,key,b['batch_id'],update(),preview=True)['valid']
 before=journal.load(root)['sequence'];saved=rec.commit(m,key,b['batch_id'],update())
 s=journal.load(root)
 assert s['sequence']==before+1 and s['summary']['summary']=='已整理调用' and s['management_note']['text']=='继续正常制作'
 assert s['assistant_recording']['cursor']==b['next_cursor'] and s['files']==[{'path':'new.pptx'}]
 assert rec.pending(m,key) and rec.commit(m,key,b['batch_id'],update())['already_applied']
 assert journal.load(root)['sequence']==s['sequence']
 assert len(rec.history(m,key)['versions'])==1 and saved['graph_revision']==1

def test_graph_change_rejects_stale_batch(project):
 m,root,key,_=project;emit(project);b=rec.prepare(m,key)
 journal.update(root,{'work_graph':{'nodes':[]}})
 with pytest.raises(ValueError,match='工作图已变化'):rec.commit(m,key,b['batch_id'],update())
 assert 'assistant_recording' not in journal.load(root)
 assert len(rec.history(m,key)['versions'])==1

@pytest.mark.parametrize('field,value',[('status','done'),('evidence_ids',['fake']),('tools',['fake']),('task_ids',['fake'])])
def test_model_cannot_rewrite_evidence(project,field,value):
 m,root,key,_=project;emit(project,command_status='outcome_unknown');b=rec.prepare(m,key)
 with pytest.raises(ValueError,match='实际调用'):rec.commit(m,key,b['batch_id'],update(patches=[{'id':b['observations'][0]['id'],field:value}]))
 assert 'work_graph' not in journal.load(root)

def test_stable_call_late_finish_and_recovery(project):
 m,root,key,_=project;emit(project,command_status='started');b=rec.prepare(m,key)
 nid=b['observations'][0]['id'];rec.commit(m,key,b['batch_id'],update(patches=[{'id':nid,'title':'渐变构建'}]))
 emit(project,command_status='completed',task_kind='region_objects',recovery={'outcome':'accepted_next_failed'})
 b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 nodes=journal.load(root)['work_graph']['nodes']
 assert len(nodes)==1 and nodes[0]['id']==nid and nodes[0]['title']=='渐变构建' and nodes[0]['status']=='failed'
 assert len(nodes[0]['evidence_ids'])==2

def test_restore_new_version_does_not_rewind_cursor(project):
 m,root,key,_=project;emit(project);b=rec.prepare(m,key);a=rec.commit(m,key,b['batch_id'],update())
 emit(project,call_id='second');b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 before=journal.load(root);rec.restore(m,key,a['history_id'],before['graph_revision'])
 after=journal.load(root)
 assert after['assistant_recording']==before['assistant_recording'] and after['phase']==before['phase']
 assert len(after['work_graph']['nodes'])==1 and after['graph_revision']==3
 with pytest.raises(ValueError):rec.restore(m,key,a['history_id'],1)

def test_edges_inferred_and_cycles_rejected(project):
 m,root,key,_=project;emit(project,2);b=rec.prepare(m,key);a,z=[n['id'] for n in b['observations']]
 good=update(patches=[{'id':z,'after':[a],'links':[{'from':a,'relation':'dependency','basis':'recorded'}]}])
 result=rec.commit(m,key,b['batch_id'],good,preview=True)
 assert result['graph']['nodes'][1]['links'][0]['basis']=='inferred'
 bad=update(patches=good['patches']+[{'id':a,'after':[z]}])
 with pytest.raises(ValueError,match='循环|顺序'):rec.commit(m,key,b['batch_id'],bad)

def test_capacity_archives_terminal_nodes(project):
 m,root,key,_=project;emit(project,64);b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 emit(project,call_id='new');b=rec.prepare(m,key);r=rec.commit(m,key,b['batch_id'],update())
 s=journal.load(root);history=journal.read_json(root/'.ppttool/graph-history'/f"{r['history_id']}.json")
 assert len(s['work_graph']['nodes'])==64 and len(history['archived_nodes'])==1

def test_scheduler_single_request_and_self_updates_no_work(project,monkeypatch):
 m,root,key,_=project;emit(project,3);sent=[]
 def provider(*a,**kw):
  sent.append(a[2]);return response(text=json.dumps({'summary':'集中整理','note':'已补图','patch_json':'[]'}))
 monkeypatch.setattr(agent,'request_json',provider);r=sched.Recorder(m,threading.Event());r.process(key)
 assert len(sent)==1 and len(journal.load(root)['work_graph']['nodes'])==3 and not rec.pending(m,key)
 r.process(key);assert len(sent)==1
 emit(project,call_id='fourth');count=len(list((root/'.ppttool/assistant-batches').glob('*.json')))
 r.process(key);assert len(sent)==1 and len(list((root/'.ppttool/assistant-batches').glob('*.json')))==count
 clear_due(root);sched.Recorder(m,threading.Event()).process(key);assert len(sent)==2

def test_three_failures_stop_and_explicit_retry(project,monkeypatch):
 m,root,key,_=project;emit(project);calls=[]
 def provider(*a,**kw):calls.append(1);raise TimeoutError()
 monkeypatch.setattr(agent,'request_json',provider);r=sched.Recorder(m,threading.Event())
 for _ in range(3):clear_due(root);r.process(key)
 s=journal.load(root);assert s['assistant_dispatch']['status']=='attention' and 'assistant_recording' not in s
 clear_due(root);r.process(key);assert len(calls)==3
 sched.retry(m,key);r.process(key);assert len(calls)==4

def test_disable_during_provider_discards_update(project,monkeypatch):
 m,root,key,cfg=project;emit(project)
 def provider(*a,**kw):
  agent.save_config(m,{k:cfg[k] for k in ('revision','endpoint','model','protocol')}|{'enabled':False})
  return response(text=json.dumps({'summary':'不能写','note':'','patch_json':'[]'}))
 monkeypatch.setattr(agent,'request_json',provider);sched.Recorder(m,threading.Event()).process(key)
 assert 'work_graph' not in journal.load(root)

def test_lease_prevents_second_recorder(project,monkeypatch):
 m,root,key,_=project;emit(project)
 journal.update(root,{'assistant_dispatch':{'status':'working','lease_until':time.time()+90}})
 monkeypatch.setattr(agent,'request_json',lambda *a,**k:pytest.fail('duplicate network request'))
 sched.Recorder(m,threading.Event()).process(key)
 assert not (root/'.ppttool/assistant-batches').exists()

def test_bad_event_status_not_completed(project):
 m,root,key,_=project
 m.store.event('tool.finished','unknown',status='mystery',details={'project':str(root),'call_id':'x'})
 assert rec.prepare(m,key)['observations'][0]['status']=='outcome_unknown'

def test_scope_and_batch_integrity(project):
 m,root,key,_=project;emit(project);b=rec.prepare(m,key)
 with pytest.raises(ValueError):rec.tool(m,'read_work_graph',{'project':key},'other')
 path=root/'.ppttool/assistant-batches'/f"{b['batch_id'][:24]}.json";path.write_text('{}')
 with pytest.raises(ValueError,match='校验'):rec.commit(m,key,b['batch_id'],update())

def test_dead_worker_receipt_and_no_false_success(project):
 m,root,key,_=project;cid='a'*32
 m.store.event('activity.started','started',details={'project':str(root),'call_id':cid,'tool_id':'graphics.construct','command_status':'started'})
 assert rec.prepare(m,key)['observations'][0]['status']=='outcome_unknown'
 folder=root/'logs/tool-calls'/cid;folder.mkdir(parents=True)
 journal.atomic(folder/'activity.json',{'call_id':cid,'command_status':'completed'})
 assert rec.prepare(m,key)['observations'][0]['status']=='observed'

def test_observer_terminal_change_without_new_audit(project):
 m,root,key,_=project;emit(project,command_status='running');b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 journal.update(root,{'activity':{'calls':[{'id':'call-0','tool':'graphics.construct','status':'outcome_unknown','evidence_id':b['events'][0]['evidence_id'],'at':journal.now()}]}})
 assert rec.pending(m,key)
 b=rec.prepare(m,key);assert not b['events'] and b['observations'][0]['status']=='outcome_unknown'
 rec.commit(m,key,b['batch_id'],update());assert not rec.pending(m,key)

def test_provider_array_and_links_only_normalize_without_extra_request(project,monkeypatch):
 m,root,key,_=project;emit(project,2);b=rec.prepare(m,key);a,z=[n['id'] for n in b['observations']];calls=[]
 def provider(*args,**kwargs):
  calls.append(1)
  return response(text=json.dumps({'summary':'两条调用','note':'关系为推断','patch_json':[{'id':z,'links':[{'from':a,'relation':'sequence','basis':'inferred'}]}]}))
 monkeypatch.setattr(agent,'request_json',provider);sched.Recorder(m,threading.Event()).process(key)
 s=journal.load(root);assert calls==[1] and s['assistant_dispatch']['status']=='ready'
 assert s['work_graph']['nodes'][1]['after']==[a]

def test_bad_suggestions_quarantined_and_forward_edges_saved(project,monkeypatch):
 m,root,key,_=project;emit(project,2);b=rec.prepare(m,key);a,z=[n['id'] for n in b['observations']]
 patches=[{'id':'made-up','title':'不存在'}, {'id':a,'after':[z]}, {'id':a,'status':'done'}, {'id':z,'after':[a]}]
 monkeypatch.setattr(agent,'request_json',lambda *a,**kw:response(text=json.dumps({'summary':'已整理','note':'','patch_json':patches})))
 sched.Recorder(m,threading.Event()).process(key);s=journal.load(root)
 assert s['assistant_dispatch']['status']=='ready' and len(s['assistant_dispatch']['rejected_suggestions'])==3
 assert len(s['work_graph']['nodes'])==2 and s['work_graph']['nodes'][1]['after']==[a]
 assert len(rec.history(m,key)['versions'][0]['warnings'])==3 and not rec.pending(m,key)

def test_old_assistant_reverse_edges_removed_with_history(project):
 m,root,key,_=project;emit(project,2);b=rec.prepare(m,key);rec.commit(m,key,b['batch_id'],update())
 g=journal.load(root)['work_graph'];a,z=[n['id'] for n in g['nodes']]
 g['nodes'][0].update(after=[z],links=[{'from':z,'relation':'sequence','basis':'inferred'}]);journal.update(root,{'work_graph':g})
 b=rec.prepare(m,key);result=rec.commit(m,key,b['batch_id'],update())
 assert result['warnings'] and journal.load(root)['work_graph']['nodes'][0]['after']==[]

def test_archived_project_not_queued_or_processed(project,monkeypatch):
 m,root,key,_=project;emit(project);rows=m.store.get('workbench_projects');rows[key]['archived']=True;m.store.set('workbench_projects',rows)
 monkeypatch.setattr(agent,'request_json',lambda *a,**kw:pytest.fail('archived project request'))
 r=sched.Recorder(m,threading.Event());r.offer(key);r.process(key);assert not r.queue
