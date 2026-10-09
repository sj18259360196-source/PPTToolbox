"""Evidence batches and atomic assistant graph records, independent of production."""
from __future__ import annotations
import copy, hashlib, json, re, time
from pathlib import Path
from scripts import project_journal as journal
from scripts.project_flow import merge, NODE_SCHEMA, STEP_TYPES
from .storage import redact

EVENTS = "(action LIKE 'tool.%' OR action LIKE 'activity.%' OR action LIKE 'graphics.%' OR action LIKE 'icons.%')"
FIELDS = {
 'read_production_status':{'project':'string'},
 'read_project_activity':{'project':'string','cursor':'integer','limit':'integer'},
 'describe_project_tools':{'project':'string','query':'string'},
 'read_work_graph':{'project':'string'},
 'prepare_project_batch':{'project':'string'},
 'preview_work_graph_update':{'project':'string','batch_id':'string','update_json':'string'},
 'commit_project_update':{'project':'string','batch_id':'string','update_json':'string'},
 'read_work_graph_history':{'project':'string','before':'integer'},
 'restore_work_graph':{'project':'string','history_id':'string','graph_revision':'integer'},
}
DESCRIPTIONS = {
 'read_production_status':'读取所选项目当前任务、版本、调用与观测边界，不询问制作 Agent。',
 'read_project_activity':'按项目连续分页读取调用事件。cursor 从 0 开始，limit 为 1 至 160；按 next_cursor 续接。',
 'describe_project_tools':'查询制作工具用途与参数合同，返回现有启用状态，不授予权限。',
 'read_work_graph':'读取当前工作图、独立图版本、节点合同和后台整理状态。',
 'prepare_project_batch':'一次准备已有图、当前进度和连续新增事件。返回 batch_id 及结构化更新合同。',
 'preview_work_graph_update':'只预检批次更新。update_json 包含 summary、note、patches；补丁限于批次中可编辑节点，执行状态由证据确定。',
 'commit_project_update':'一次提交预检后的图、摘要、备注和游标。使用 prepare_project_batch 的 batch_id；重复提交幂等。',
 'read_work_graph_history':'分页读取图版本与变更摘要，before=0 表示最近版本，不修改记录。',
 'restore_work_graph':'恢复历史展示图为新版本，graph_revision 须匹配；不回退调用游标、制作工作流或 PPT。',
}

def digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def entry(manager,key):
 from .project_hub import entry as resolve
 root,row,workflow=resolve(manager,key)
 state=journal.load(root)
 if not state:raise ValueError('项目记录尚未初始化')
 return root,row,workflow,state

def marker(workflow,state):
 return digest({'revision':workflow.get('revision'),'status':workflow.get('status'),
                'task':(workflow.get('active_task') or {}).get('id'),
                'phase_revision':state.get('phase_revision'), 'run_id':state.get('run_id'),
                'observed_calls':[(c.get('id'),c.get('status'),c.get('recovery')) for c in state.get('activity',{}).get('calls',[])]})

def activity(manager,key,cursor=0,limit=160):
 root,_,_,_=entry(manager,key)
 if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=160:raise ValueError('调用游标或分页大小无效')
 with manager.store.db() as db:
  rows=db.execute("SELECT id,time,action,status,details FROM events WHERE id>? AND json_extract(details,'$.project')=? AND "+EVENTS+" ORDER BY id LIMIT ?",(cursor,str(root),limit+1)).fetchall()
 result=[];size=0
 allowed=('call_id','tool_id','task_id','task_kind','command_status','revision_before','revision_after','error_code','error_message','reason_code','recovery')
 for row in rows[:limit]:
  details=json.loads(row['details'] or '{}')
  if row['action'].endswith(('.started','.launched','.authorized')):
   from .execution import process_alive
   details['command_status']='running' if process_alive(details.get('worker_pid') or details.get('owner_pid')) is True else 'outcome_unknown'
   cid=details.get('call_id','')
   if re.fullmatch('[a-f0-9]{32}',cid):
    try:
     receipt=journal.safe(root,'logs/tool-calls/'+cid+'/activity.json')
     saved=journal.read_json(receipt) if receipt.stat().st_size<=16*1024*1024 else {}
     if saved.get('call_id')==cid and saved.get('command_status') not in {None,'started','running'}:
      details.update({k:v for k,v in saved.items() if k in allowed})
    except (OSError,ValueError):pass
  detail={k:details[k] for k in allowed if k in details}
  # Arbitrary provider bodies and prompts never enter the model batch.
  detail={k:(v[:500] if isinstance(v,str) else v) for k,v in detail.items()}
  if isinstance(detail.get('recovery'),dict):detail['recovery']={k:v for k,v in detail['recovery'].items() if k in {'outcome','next_action','reason'}}
  item=redact({'event_id':row['id'],'evidence_id':'audit-'+str(row['id']),'at':row['time'],
               'action':row['action'],'status':row['status'],'detail':detail})
  length=len(json.dumps(item,ensure_ascii=False))
  if result and size+length>55000:break
  result.append(item);size+=length
 return {'events':result,'cursor':cursor,'next_cursor':result[-1]['event_id'] if result else cursor,
         'has_more':len(rows)>len(result),'scope':'project_audit_only','text_characters':size}

def production(manager,key):
 root,_,workflow,state=entry(manager,key)
 task=workflow.get('active_task') or {}
 from .flow_semantics import lifecycle
 return {'project':key,'workflow_revision':workflow.get('revision'),'workflow_status':workflow.get('status'),'lifecycle':lifecycle(manager,workflow),
         'task':{k:task[k] for k in ('id','kind','target','status') if k in task},
         'phase':state.get('phase',{}),'observed_at':state.get('updated_at'),
         'recent_calls':state.get('activity',{}).get('calls',[])[-12:],
         'connection':state.get('activity',{}).get('connection',{}),
         'limitations':'只观察本工具箱记录。MCP 连接状态可能来自多个会话，不代表本项目正在制作；外部编辑和模型内部活动未知。'}

def pending(manager,key):
 root,_,workflow,state=entry(manager,key)
 saved=state.get('assistant_recording',{})
 with manager.store.db() as db:
  latest=db.execute("SELECT MAX(id) FROM events WHERE json_extract(details,'$.project')=? AND "+EVENTS,(str(root),)).fetchone()[0] or 0
 return latest>saved.get('cursor',0) or marker(workflow,state)!=saved.get('marker') and bool(state.get('checkpoints') or workflow or state.get('activity',{}).get('calls'))

def event_nodes(events):
 from .project_status import step_kind,call_state
 kinds={t['id']:t for t in STEP_TYPES};nodes={}
 for e in events:
  d=e['detail'];tool=d.get('tool_id') or e['action']
  kind=step_kind(tool,d.get('task_kind')) or 'recovery'
  task=d.get('task_id');call=d.get('call_id') or 'event-'+str(e['event_id'])
  # Terminal wrappers and their inner events share one call identity.
  identity=str(call)
  nid='auto-'+hashlib.sha256(identity.encode()).hexdigest()[:20]
  status=d.get('command_status')
  if not status:
   status='running' if e['action'].endswith(('.started','.launched','.authorized')) else 'failed' if e['status']=='error' else 'completed' if e['status'] in {'ok','success','completed'} else 'outcome_unknown'
  normalized=call_state({**d,'status':status})
  normalized='observed' if normalized in {'done','empty'} else normalized
  if normalized not in {'observed','running','blocked','failed','outcome_unknown'}:normalized='blocked'
  old=nodes.get(nid,{})
  evidence=list(dict.fromkeys(old.get('evidence_ids',[])+[e['evidence_id']]))[-12:]
  nodes[nid]={'id':nid,'kind':old.get('kind',kind),'title':old.get('title',kinds[kind]['title']),'stage':old.get('stage',kinds[kind]['stage']),
   'status':normalized,'after':[],'task_ids':[task] if task else old.get('task_ids',[]),'evidence_ids':evidence,
   'tools':list(dict.fromkeys(old.get('tools',[])+[tool]))[-12:],'result':'调用记录已更新；执行完成不等于视觉验收通过','detail':str(d.get('error_message') or d.get('reason_code') or tool)[:1500],
   'event_id':e['event_id'],'at':e['at'],'first_at':old.get('first_at',e['at']),
   'workflow_revision':old.get('workflow_revision') if old.get('workflow_revision') is not None else d.get('revision_before')}
  for field in ('started_at','finished_at'):
   if field in old:nodes[nid][field]=old[field]
  if e['action'].endswith(('.started','.launched')):nodes[nid].setdefault('started_at',e['at'])
  if e['action'].endswith(('.finished','.reconciled')):nodes[nid]['finished_at']=e['at']
 return list(nodes.values())

def prepare(manager,key):
 root,_,workflow,state=entry(manager,key)
 saved=state.get('assistant_recording',{});page=activity(manager,key,saved.get('cursor',0),32)
 observations=event_nodes(page['events']);by_id={n['id']:n for n in observations}
 existing={n['id']:n for n in state.get('work_graph',{}).get('nodes',[])}
 # Observer facts include durable terminal receipts and dead-worker uncertainty.
 for c in state.get('activity',{}).get('calls',[]):
  nid='auto-'+hashlib.sha256(str(c['id']).encode()).hexdigest()[:20]
  if nid not in by_id and nid not in existing:continue
  e={'event_id':0,'evidence_id':c['evidence_id'],'at':c['at'],'action':c['tool'],'status':'ok',
     'detail':{'call_id':c['id'],'tool_id':c['tool'],'command_status':c['status'],
               'task_id':c.get('task_id'),'task_kind':c.get('task_kind'),'recovery':c.get('recovery',{})}}
  n=event_nodes([e])[0]
  if nid in by_id and c['evidence_id'] not in by_id[nid]['evidence_ids']:
   # A newer audit fact belongs to a later batch. Receipt/dead-worker changes
   # keep their originating audit identity and may update this batch safely.
   continue
  if nid not in by_id and n['status']==existing[nid].get('status'):continue
  prior=by_id.get(nid,existing.get(nid,{}));n.update(kind=prior['kind'],stage=prior['stage'])
  n['evidence_ids']=list(dict.fromkeys(prior.get('evidence_ids',[])+n['evidence_ids']))[-12:]
  by_id[nid]=n
 from .flow_semantics import lifecycle, assign
 life=lifecycle(manager,workflow)
 assign(list(by_id.values()),life)
 payload={'project':key,'project_id':state['project_id'],'cursor':page['cursor'],'next_cursor':page['next_cursor'],
  'has_more':page['has_more'],'marker':marker(workflow,state),'graph_revision':state.get('graph_revision',0),
  'graph':state.get('work_graph',{}),'progress':production(manager,key),'lifecycle':life,'observations':list(by_id.values()),
  'events':page['events'],'checkpoints':[{k:c.get(k) for k in ('checkpoint_id','event','stage','result_summary','next_action','received_at')} for c in state.get('checkpoints',[])[-12:]]}
 identifier=digest(payload)
 path=journal.safe(root,'.ppttool/assistant-batches/'+identifier[:24]+'.json');path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():journal.atomic(path,payload)
 return {'batch_id':identifier,**payload,'update_contract':{'summary':'中文摘要，最多 1500 字','note':'管理记录，最多 1500 字','patches':'NODE_SCHEMA 数组，可为空。只编辑 observations 或已有助手节点。不要修改 status、task_ids、tools、evidence_ids。'},'node_schema':NODE_SCHEMA}

def batch(root,identifier):
 if not re.fullmatch('[a-f0-9]{64}',identifier):raise ValueError('批次编号无效')
 p=journal.safe(root,'.ppttool/assistant-batches/'+identifier[:24]+'.json')
 if not p.is_file() or p.stat().st_size>2_000_000:raise ValueError('批次不存在或过大')
 value=journal.read_json(p)
 if digest(value)!=identifier:raise ValueError('批次内容校验失败')
 return value

def proposal(state,b,update):
 if not isinstance(update,dict) or set(update)!={'summary','note','patches'}:raise ValueError('更新需要 summary、note、patches')
 for field in ('summary','note'):
  if not isinstance(update[field],str) or len(update[field])>1500:raise ValueError('摘要或备注过长')
 patches=update['patches']
 if not isinstance(patches,list) or len(patches)>64:raise ValueError('节点补丁数量无效')
 if state.get('graph_revision',0)!=b['graph_revision']:raise ValueError('工作图已变化，请准备新批次')
 if state.get('assistant_recording',{}).get('cursor',0)!=b['cursor']:raise ValueError('调用游标已变化，请准备新批次')
 existing=copy.deepcopy(state.get('work_graph',{}));nodes={n['id']:n for n in existing.get('nodes',[])}
 observed={n['id']:n for n in b['observations']};editable={k for k,n in nodes.items() if n.get('source')=='pptagent'}|set(observed)
 warnings=[]
 def order(n):
  ids=[int(e[6:]) for e in n.get('evidence_ids',[]) if re.fullmatch('audit-[0-9]+',e)]
  return min(ids) if ids else None
 def backwards(parent,target,relation):
  first,last=order(nodes.get(parent,{})),order(nodes.get(target,{}))
  return relation in {'sequence','revision','decision'} and first is not None and last is not None and first>last
 # Software supplies statuses and associations; the model supplies explanations.
 for nid,n in observed.items():
  previous=nodes.get(nid,{})
  nodes[nid]={**previous,**{k:v for k,v in n.items() if k not in {'after','event_id','at'}},
              'after':previous.get('after',[]),'source':'pptagent','updated_at':n['at']}
  for field in ('title','kind','stage'):
   if field in previous:nodes[nid][field]=previous[field]
  for field in ('evidence_ids','task_ids','tools'):
   nodes[nid][field]=list(dict.fromkeys(previous.get(field,[])+n.get(field,[])))[-12:]
  for field in ('first_at','started_at','workflow_revision'):
   if previous.get(field) is not None:nodes[nid][field]=previous[field]
 for nid,n in nodes.items():
  if n.get('source')!='pptagent' or not nid.startswith('auto-'):continue
  bad={l['from'] for l in n.get('links',[]) if backwards(l['from'],nid,l.get('relation'))}
  if bad:
   n['after']=[p for p in n.get('after',[]) if p not in bad]
   n['links']=[l for l in n.get('links',[]) if l['from'] not in bad]
   warnings.append('已移除与实际调用顺序相反的助手连线，旧图保留在历史中')
 new_ids=set(observed)
 archived=[]
 while len(nodes)>64:
  removable=next((k for k,n in nodes.items() if k not in new_ids and n.get('source')=='pptagent' and n.get('status') in {'done','observed','skipped','replaced','failed','blocked','paused'}),None)
  if removable is None:raise ValueError('当前图容纳不下本批记录，请减少批次或整理已有节点')
  archived.append(nodes.pop(removable))
 for n in nodes.values():
  n['after']=[p for p in n.get('after',[]) if p in nodes]
  if 'links' in n:n['links']=[l for l in n['links'] if l['from'] in n['after']]
 sanitized=[]
 for p in patches:
  if not isinstance(p,dict) or p.get('id') not in editable or p['id'] not in nodes:raise ValueError('只能修改本批观测或已有助手节点')
  from jsonschema import Draft202012Validator
  if not Draft202012Validator(NODE_SCHEMA).is_valid(p):raise ValueError('工作图字段无效')
  protected={'status','task_ids','evidence_ids','tools','kind','stage','round','group_id','group_label','ownership','exit_reason'}
  if any(k in p and p[k]!=nodes[p['id']].get(k) for k in protected):raise ValueError('执行状态和证据关联由实际调用决定')
  q=copy.deepcopy(p)
  if 'links' in q and 'after' not in q:
   q['after']=[link.get('from') for link in q['links'] if isinstance(link,dict)]
  for link in q.get('links',[]):
   if link.get('basis') in {'recorded','agent'} or 'basis' not in link:
    link['basis']='inferred';warnings.append('模型补充关系标记为推断')
   allowed=set(nodes[q['id']].get('evidence_ids',[]))|set(nodes.get(link.get('from'),{}).get('evidence_ids',[]))
   if set(link.get('evidence_ids',[]))-allowed:raise ValueError('连线引用了不属于两端节点的证据')
  if 'after' in q and 'links' not in q:
   q['links']=[{'from':p,'relation':'sequence','basis':'inferred','label':'助手整理的先后关系'} for p in q['after']]
  if any(backwards(l.get('from'),q['id'],l.get('relation')) for l in q.get('links',[])):
   raise ValueError('先后连线与实际调用顺序相反')
  sanitized.append(q)
 graph={'format':'ppttool-work-graph/1','nodes':list(nodes.values())}
 if sanitized:graph=merge(graph,sanitized,source='pptagent',at=journal.now())
 elif nodes:
  # Validate the complete graph without replacing evidence-derived properties.
  merge(graph,[{'id':n['id']} for n in graph['nodes']],source='pptagent',at=journal.now())
 from .flow_semantics import assign, connect_recorded
 assign(graph['nodes'],b.get('lifecycle'))
 connect_recorded(graph['nodes'])
 if graph['nodes']:merge(graph,[{'id':n['id']} for n in graph['nodes']],source='pptagent',at=journal.now())
 return {'graph':graph,'summary':redact(update['summary']),'note':redact(update['note']),
         'warnings':list(dict.fromkeys(warnings)),'archived_nodes':archived}

def commit(manager,key,identifier,update,preview=False,review_notes=None):
 root,_,_,_=entry(manager,key);b=batch(root,identifier)
 with journal.locked(root):
  state=journal.load(root)
  if b['project_id']!=state['project_id'] or b['project']!=key:raise ValueError('批次不属于当前项目')
  old=state.get('assistant_recording',{})
  if old.get('batch_id')==identifier:return {'saved':True,'already_applied':True,'graph_revision':state.get('graph_revision',0)}
  value=proposal(state,b,update)
  value['warnings']+=review_notes or []
  if preview:return {'valid':True,'graph':value['graph'],'warnings':value['warnings'],'archived_count':len(value['archived_nodes'])}
  history=journal.safe(root,'.ppttool/graph-history');history.mkdir(parents=True,exist_ok=True)
  history_id=f"{state.get('graph_revision',0)+1:010d}-{identifier[:16]}"
  record={'id':history_id,'at':journal.now(),'before':state.get('work_graph',{}),'after':value['graph'],
   'batch_id':identifier,'from_cursor':b['cursor'],'to_cursor':b['next_cursor'],'summary':value['summary'],
   'archived_nodes':value['archived_nodes'],'warnings':value['warnings']}
  journal.atomic(journal.safe(root,'.ppttool/graph-history/'+history_id+'.json'),record)
  changes={'work_graph':value['graph'],'summary':{'status':'ready','summary':value['summary'],'next_hint':'',
   'evidence_ids':[e['evidence_id'] for e in b['events']],'recommended_ids':[],'at':record['at']},
   'management_note':{'text':value['note'],'at':record['at']},
   'assistant_recording':{'cursor':b['next_cursor'],'marker':b['marker'],'batch_id':identifier,'history_id':history_id,
    'last_update':record['at'],'event_count':len(b['events']),'has_more':b['has_more'],'status':'ready',
    'total_events':old.get('total_events',0)+len(b['events']),'warnings':value['warnings']}}
  saved=journal._commit(root,state,changes,'assistant.batch','pptagent',{'history_id':history_id,'batch_id':identifier})
  return {'saved':True,'graph_revision':saved.get('graph_revision',0),'history_id':history_id,'cursor':b['next_cursor'],'warnings':value['warnings']}

def filter_suggestions(manager,key,b,update):
 """Keep authoritative facts even if optional model suggestions are invalid.

 Public commit remains strict. The automatic worker quarantines rejected
 suggestions explicitly and persists the rejection list in committed history.
 """
 state=entry(manager,key)[3]
 proposal(state,b,{**update,'patches':[]})
 if not isinstance(update['patches'],list) or len(update['patches'])>64:raise ValueError('节点补丁数量无效')
 accepted=[];rejected=[]
 for p in update['patches']:
  try:proposal(state,b,{**update,'patches':accepted+[p]})
  except ValueError as exc:
   # The response is already saved with this batch; don't feed it into a
   # repair request or guess an alternate ID.
   rejected.append({'id':str(p.get('id',''))[:64] if isinstance(p,dict) else '', 'reason':str(exc)[:160]})
  else:accepted.append(p)
 return {**update,'patches':accepted},rejected

def history(manager,key,before=0):
 root,_,workflow,state=entry(manager,key)
 # Only expose histories committed by the authoritative event journal.
 committed={}
 for p in sorted(journal.safe(root,'.ppttool/events').glob('*.json'),reverse=True):
  event=journal.read_json(p,{})
  identifier=event.get('detail',{}).get('history_id')
  if identifier and (not before or event['sequence']<before):committed[identifier]=event['sequence']
  if len(committed)>=20:break
 rows=[]
 for identifier,sequence in committed.items():
  p=journal.safe(root,'.ppttool/graph-history/'+identifier+'.json')
  if p.is_file():
   value=journal.read_json(p)
   rows.append({k:value.get(k) for k in ('id','at','summary','from_cursor','to_cursor','warnings')}|{'sequence':sequence})
 return {'graph_revision':state.get('graph_revision',0),'versions':rows,'next_before':rows[-1]['sequence'] if rows else None}

def restore(manager,key,identifier,revision,source='owner'):
 if not re.fullmatch(r'\d{10}-[a-f0-9]{16}',identifier):raise ValueError('历史编号无效')
 root,_,_,_=entry(manager,key)
 with journal.locked(root):
  state=journal.load(root)
  if state.get('graph_revision',0)!=revision:raise ValueError('工作图版本已变化')
  known=any(journal.read_json(p,{}).get('detail',{}).get('history_id')==identifier for p in journal.safe(root,'.ppttool/events').glob('*.json'))
  if not known:raise ValueError('没有已提交的历史记录')
  row=journal.read_json(journal.safe(root,'.ppttool/graph-history/'+identifier+'.json'))
  restore_id=f"{revision+1:010d}-"+digest({'id':identifier,'revision':revision})[:16]
  record={'id':restore_id,'at':journal.now(),'before':state.get('work_graph',{}),'after':row['after'],
          'summary':'恢复历史工作图 '+identifier,'warnings':[]}
  journal.atomic(journal.safe(root,'.ppttool/graph-history/'+restore_id+'.json'),record)
  saved=journal._commit(root,state,{'work_graph':row['after']},'assistant.graph_restore',source,{'history_id':restore_id})
  return {'saved':True,'graph_revision':saved.get('graph_revision',0),'production_unchanged':True}

def tool(manager,name,args,scope):
 key=args['project']
 if not scope or scope!=key:raise ValueError('只允许当前选定项目')
 root,_,_,state=entry(manager,key)
 if name=='read_production_status':return production(manager,key)
 if name=='read_project_activity':return activity(manager,key,args['cursor'],args['limit'])
 if name=='read_work_graph':
  from .flow_semantics import lifecycle, project
  from scripts.project_flow import diagnostics
  life=lifecycle(manager,workflow);nodes=project(state.get('work_graph',{}).get('nodes',[]),life)
  return {'graph':state.get('work_graph',{}),'display_nodes':nodes,'lifecycle':life,'diagnostics':diagnostics(nodes),
          'graph_revision':state.get('graph_revision',0),'recording':state.get('assistant_recording',{}),'node_schema':NODE_SCHEMA}
 if name=='prepare_project_batch':return prepare(manager,key)
 if name in {'preview_work_graph_update','commit_project_update'}:
  return commit(manager,key,args['batch_id'],json.loads(args['update_json']),preview=name.startswith('preview'))
 if name=='read_work_graph_history':return history(manager,key,args['before'])
 if name=='restore_work_graph':return restore(manager,key,args['history_id'],args['graph_revision'],source='pptagent')
 if name=='describe_project_tools':
  rows=manager.catalog()
  query=args['query'].casefold()
  matched=[r for r in rows if query in json.dumps(r,ensure_ascii=False).casefold()][:12]
  from .graphics import SPECS as graphics
  from .icons.contracts import SPECS as icons
  for r in matched:
   prefix,_,op=r['id'].partition('.')
   specs=graphics if prefix=='graphics' else icons if prefix=='icons' else {}
   if op in specs:r['input_schema']=specs[op][1]
  return {'tools':matched,'execution_enabled':manager.settings().get('agent_execution_enabled',False),
          'scope':'工具启用不等于项目执行授权；以受管执行预检为准。'}
 raise ValueError('未知记录工具')
