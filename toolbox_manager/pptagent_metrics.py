"""Durable API usage and observed assistant effects; never estimates missing tokens."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import time
import uuid
from scripts import project_journal as journal

KEY = 'pptagent_metrics_v1'
CONTEXT = ContextVar('pptagent_request_context', default={})
COUNTERS = ('requests','succeeded','failed','interrupted','reported','unknown',
            'input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens',
            'summaries_saved','evidence_reviewed','recommendations_selected',
            'tools_completed','notes_saved','graphs_updated','requests_handled',
            'input_reported','output_reported','cached_reported','reasoning_reported')

def empty():
    return {key:0 for key in COUNTERS}

@contextmanager
def scope(**values):
    token=CONTEXT.set(values)
    try: yield
    finally: CONTEXT.reset(token)

def _edit(manager, action):
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM kv WHERE key=?',(KEY,)).fetchone()
        state=json.loads(row[0]) if row else {'since':journal.now(),'total':empty(),'projects':{},'tasks':{},'recent':[],'effects':[]}
        result=action(state)
        db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,json.dumps(state,ensure_ascii=False)))
    return result

def _buckets(state, context):
    buckets=[state['total']]
    for field,identifier in [('projects',context.get('project')),('tasks',context.get('task'))]:
        if identifier: buckets.append(state[field].setdefault(identifier,empty()))
    return buckets

def start(manager, cfg):
    identifier=uuid.uuid4().hex;context=dict(CONTEXT.get())
    row={'id':identifier,**context,'kind':context.get('kind','api'),'model':cfg.get('model',''),
         'started_at':journal.now(),'status':'running','usage':None}
    def action(state):
        for bucket in _buckets(state,context): bucket['requests']+=1
        state['recent'].insert(0,row)
        # Never evict a request whose result has not been counted yet.
        done=[r for r in state['recent'] if r['status']!='running'][:100]
        state['recent']=[r for r in state['recent'] if r['status']=='running']+done
        while len(state['tasks'])>50: state['tasks'].pop(next(iter(state['tasks'])))
    _edit(manager,action)
    return identifier,time.monotonic()

def usage(response):
    raw=response.get('usage') if isinstance(response,dict) else None
    if not isinstance(raw,dict): return None
    def count(value): return value if type(value) is int and value>=0 else None
    incoming=count(raw.get('input_tokens',raw.get('prompt_tokens')))
    outgoing=count(raw.get('output_tokens',raw.get('completion_tokens')))
    total=count(raw.get('total_tokens'))
    if total is None and incoming is not None and outgoing is not None: total=incoming+outgoing
    if total is None: return None
    input_details=raw.get('input_tokens_details',raw.get('prompt_tokens_details')) or {}
    output_details=raw.get('output_tokens_details',raw.get('completion_tokens_details')) or {}
    return {'input_tokens':incoming,'output_tokens':outgoing,'total_tokens':total,
            'cached_tokens':count(input_details.get('cached_tokens')) if isinstance(input_details,dict) else None,
            'reasoning_tokens':count(output_details.get('reasoning_tokens')) if isinstance(output_details,dict) else None}

def finish(manager, ticket, response=None, error=None):
    identifier,started=ticket;values=usage(response)
    status='failed' if error or (isinstance(response,dict) and response.get('status') in {'failed','incomplete','cancelled'}) else 'succeeded'
    def action(state):
        row=next((r for r in state['recent'] if r['id']==identifier),None)
        if not row or row['status']!='running': return
        row.update(status=status,finished_at=journal.now(),duration_ms=round((time.monotonic()-started)*1000),usage=values)
        # Persist only the exception class, never response bodies, URLs or credentials.
        if error: row['error_type']=type(error).__name__
        for bucket in _buckets(state,row):
            bucket[status]+=1;bucket['reported' if values else 'unknown']+=1
            for key,value in (values or {}).items():
                if value is not None:
                    bucket[key]+=value
                    if key!='total_tokens':
                        reported=key.replace('_tokens','_reported')
                        bucket[reported]=bucket.get(reported,0)+1
    _edit(manager,action)

def effect(manager, project, kind, count=1):
    if kind not in COUNTERS[11:18] or type(count) is not int or count<0: raise ValueError('Invalid assistant effect')
    def action(state):
        for bucket in _buckets(state,{'project':project}): bucket[kind]+=count
        state['effects'].insert(0,{'project':project,'kind':kind,'count':count,'at':journal.now()})
        del state['effects'][60:]
    _edit(manager,action)

def recover(manager):
    if not manager.store.get(KEY): return
    def action(state):
        for row in state['recent']:
            if row['status']=='running':
                row.update(status='interrupted',finished_at=journal.now())
                for bucket in _buckets(state,row): bucket['interrupted']+=1;bucket['unknown']+=1
    _edit(manager,action)

def snapshot(manager, project=None):
    state=manager.store.get(KEY,{})
    result={**empty(),**(state.get('projects',{}).get(project,{}) if project else state.get('total',{}))}
    result.update(since=state.get('since'),active=max(0,result['requests']-result['succeeded']-result['failed']-result['interrupted']),
                  recent=[r for r in state.get('recent',[]) if not project or r.get('project')==project][:12],
                  effects=[r for r in state.get('effects',[]) if not project or r.get('project')==project][:8])
    if not project: result['task_usage']=state.get('tasks',{})
    from .pptagent_budget import snapshot as budget_snapshot
    result['budget']=budget_snapshot(manager,project)
    return result

def project_status(manager, key, state):
    from .pptagent import config
    from .pptagent_runtime import tasks
    cfg=config(manager);metrics=snapshot(manager,key);worker=getattr(manager,'pptagent_worker',None)
    pending=False;processing=False
    if worker:
        with worker.lock:
            pending=key in worker.pending
            processing=key in getattr(worker,'processing',set())
        recorder=getattr(worker,'recorder',None)
        if recorder:
            with recorder.lock:pending=pending or key in recorder.queue
    dispatch=state.get('assistant_dispatch',{})
    processing=processing or dispatch.get('status')=='working' and dispatch.get('lease_until',0)>time.time()
    scoped=[r for r in tasks(manager) if r.get('project')==key]
    task=next((r for r in scoped if r['status'] in {'queued','running'}),None)
    summary=state.get('summary',{})
    status='disabled' if not cfg['enabled'] else 'unconfigured' if not cfg['endpoint'] or not cfg['model'] else 'working' if processing or metrics['active'] or (task and task['status']=='running') else 'queued' if pending or task else 'unavailable' if summary.get('status')=='unavailable' else 'ready' if summary.get('status')=='ready' else 'waiting'
    if status not in {'disabled','unconfigured','working'} and dispatch.get('status') in {'error','attention'}:
        status='unavailable'
    budget=metrics['budget']
    if status not in {'disabled','unconfigured','working'} and (budget['blocked'] or (pending and budget['summary_retry_at'])):
        status='rate_limited'
    last=scoped[0] if scoped else None
    if status in {'ready','waiting'} and last and last['status'] in {'failed','interrupted'} and last.get('updated_at','')>summary.get('at',''):
        status='task_failed'
    return {'status':status,'metrics':metrics,'summary_at':summary.get('at'),
            'evidence_count':len(summary.get('evidence_ids',[])),
            'recommendation_count':len(summary.get('recommended_ids',[])),
            'task':{'id':task['id'],'prompt':task['prompt'],'steps':len(task.get('steps',[]))} if task else None,
            'last_task_result':last.get('result','') if status=='task_failed' else None}
