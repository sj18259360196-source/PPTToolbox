"""Usage accounting. A read, citation, application and delivery are distinct facts."""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.usage_store import connect, insert, key, now, record
from .storage import redact

KINDS = {'experience', 'tool', 'icon', 'skill'}
ACTIONS = {'retrieved', 'viewed', 'source_viewed', 'cited', 'call', 'extracted', 'placed', 'applied', 'delivered'}
MAINTENANCE = {'workflow.status', 'experience.audit', 'toolbox_context', 'toolbox_status', 'toolbox_logs',
               'icons.stats', 'icons.providers'}


def test_record(details):
    if details.get('usage_test'): return True
    path = str(details.get('project', '')).replace('\\', '/').casefold()
    return bool(set(path.split('/')) & {'.tmp', 'checks', 'pytest', 'fixtures'})


def duration(details):
    try:
        return max(0, (datetime.fromisoformat(details['ended_at'])-datetime.fromisoformat(details['started_at'])).total_seconds())
    except (KeyError, TypeError, ValueError): return None


def sync(manager):
    """Project old/new audit rows once, with one key per underlying call."""
    with connect(manager.data/'usage') as db:
        db.execute('BEGIN IMMEDIATE')
        cursor = db.execute("SELECT value FROM meta WHERE key='audit_cursor'").fetchone()
        cursor = int(cursor[0]) if cursor else 0
        since = db.execute("SELECT value FROM meta WHERE key='enabled_since'").fetchone()[0]
        with sqlite3.connect(manager.store.path.as_uri()+'?mode=ro', uri=True) as audit:
            audit.row_factory = sqlite3.Row
            rows = audit.execute('SELECT * FROM events WHERE id>? ORDER BY id', (cursor,)).fetchall()
        for row in rows:
            d = json.loads(row['details'] or '{}')
            action, tid = row['action'], d.get('tool_id', '')
            common = dict(at=row['time'], source=row['source'], project=d.get('project', ''),
                          task=d.get('task_id', ''), is_test=test_record(d), historical=row['time'] < since,
                          evidence={'audit_id': row['id'], 'call_id': d.get('call_id'),
                                    'classification': 'explicit_test' if d.get('usage_test') else 'path_hint' if test_record(d) else 'unclassified_legacy' if row['time'] < since else 'normal'})
            if action == 'tool.finished' and tid not in MAINTENANCE and not d.get('usage_maintenance'):
                outcome = d.get('command_status', 'unknown')
                status = ('success' if outcome == 'completed' else 'failed' if outcome == 'tool_failed' else
                          'unknown' if outcome == 'outcome_unknown' else 'waiting' if outcome == 'action_required' else 'blocked')
                insert(db, 'call:'+str(d.get('call_id') or row['id']), 'tool', tid, 'rejected' if status=='blocked' else 'call',
                       status=status, duration=duration(d), **common)
                if d.get('usage_application_id') and status=='success':
                    db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',('application:'+d['usage_application_id'],json.dumps({'at':row['time'],'is_test':common['is_test']})))
            if action.startswith('icons.') and action not in {'icons.stats', 'icons.providers'}:
                insert(db, 'icon-tool:'+str(row['id']), 'tool', action, 'call',
                       status='success' if row['status']=='ok' else 'failed', duration=duration(d), **common)
                # UI views are tracked at explicit clicks; automated GETs do not count.
                metric = {'icons.inspect':'viewed', 'icons.fragment':'extracted', 'icons.place':'placed'}.get(action)
                if metric and d.get('version') and row['status']=='ok' and not (action=='icons.inspect' and row['source']=='owner'):
                    insert(db, 'icon:'+str(row['id']), 'icon', d['version'], metric, **common)
            if action.startswith('graphics.'):
                insert(db, 'graphics-tool:'+str(row['id']), 'tool', action, 'call',
                       status='success' if row['status']=='ok' else 'failed', duration=duration(d), **common)
            if action == 'mcp.read' and row['message']=='toolbox_describe' and d.get('target_id'):
                insert(db, 'describe:'+str(row['id']), 'tool', d['target_id'], 'viewed', **common)
        if rows:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('audit_cursor', str(rows[-1]['id'])))
        # Successful recipe applications have stable application IDs. Outcome may be refined later.
        learning = manager.data/'learning/library.sqlite3'
        if learning.is_file():
            with sqlite3.connect(learning.as_uri()+'?mode=ro', uri=True) as lib:
                if lib.execute("SELECT 1 FROM sqlite_master WHERE name='applications'").fetchone():
                    for appid, sid, ver, raw in lib.execute('SELECT id,skill,version,payload FROM applications'):
                        app = json.loads(raw)
                        applied=db.execute('SELECT value FROM meta WHERE key=?',('application:'+appid,)).fetchone()
                        applied=json.loads(applied[0]) if applied else {}
                        insert(db, 'skill:'+appid, 'skill', sid, 'applied', version=ver,
                               project=app.get('project',''), task=app.get('task_id',''),
                               is_test=applied.get('is_test',test_record(app)), historical=not bool(applied),
                               at=applied.get('at') or since,
                               evidence={'application_id':appid, 'time_unknown':not bool(applied), 'scope':'recipe compiled into a trial'})
                        if applied:
                            # A reader may see the application before its worker completion audit.
                            db.execute("UPDATE usage_events SET at=?,is_test=?,historical=0,evidence=json_set(evidence,'$.time_unknown',json('false')) WHERE event_key=? AND json_extract(evidence,'$.time_unknown')=1",
                                       (applied['at'],int(applied['is_test']),'skill:'+appid))
                        outcome = app.get('outcome', {})
                        if outcome.get('status') == 'passed':
                            insert(db, 'skill-delivery:'+appid, 'skill', sid, 'delivered', version=ver,
                                   project=app.get('project',''), task=app.get('task_id',''),
                                   at=now() if applied else since,
                                   is_test=applied.get('is_test',test_record(app)), historical=not bool(applied),
                                   evidence={'application_id':appid,'time_unknown':not bool(applied), 'time_basis':'outcome_observed','outcome':outcome})
                            if applied:
                                db.execute("UPDATE usage_events SET at=?,is_test=?,historical=0,evidence=json_set(evidence,'$.time_unknown',json('false')) WHERE event_key=? AND json_extract(evidence,'$.time_unknown')=1",
                                           (now(),int(applied['is_test']),'skill-delivery:'+appid))
                if lib.execute("SELECT 1 FROM sqlite_master WHERE name='attempts'").fetchone():
                    for appid, raw in lib.execute('SELECT id,payload FROM attempts'):
                        app=json.loads(raw)
                        insert(db,'skill-attempt:'+appid,'skill',app.get('skill_id',''),'attempted',
                               status=app.get('status','unknown'), at=app.get('recorded_at') or since,
                               project=app.get('project',''),version=app.get('version',''),
                               is_test=test_record(app),historical=not bool(app.get('recorded_at')),evidence={'reason':app.get('reason',''),'time_unknown':not bool(app.get('recorded_at'))})
        collect_deliveries(manager,db)


def collect_deliveries(manager,db):
    """Only identify an icon in a hash-checked final scene, never from extraction alone."""
    from .workbench import Workbench
    from .learning import delivery_source
    projects=manager.store.get('workbench_projects',{})
    for project_key in projects:
        try:
            project,_,state=Workbench(manager).entry(project_key)
            if state.get('status')!='delivered':continue
            run=state['run']
            scene=Workbench.path(project,run['dir']+'/scene.json')
            pptx=Workbench.path(project,run['candidate']['file'])
            receipt=Workbench.path(project,'delivery/'+run['id']+'/delivery.json')
            cache_key='delivery:'+str(project)
            fingerprint=key(run['id'],*[(p.stat().st_mtime_ns,p.stat().st_size) for p in (scene,pptx,receipt)])
            previous=db.execute('SELECT value FROM meta WHERE key=?',(cache_key,)).fetchone()
            if previous and previous[0]==fingerprint:continue
            source=delivery_source(manager,project_key)
            def walk(objects):
                for obj in objects:
                    yield obj
                    yield from walk(obj.get('children',[]))
            versions=set()
            for slide in json.loads(scene.read_text('utf-8'))['slides']:
                for obj in walk(slide.get('objects',[])):
                    versions.update(re.findall(r'PPTToolbox icon ([a-f0-9]{64})',obj.get('evidence',{}).get('note','')))
            for version in versions:
                from .icons.library import Library
                Library(manager.data/'icon-library').row(version)
                insert(db,key('icon-delivery',str(project),run['id'],version),'icon',version,'delivered',
                       project=str(project),is_test=test_record({'project':str(project)}),
                       evidence={'run_id':run['id'],'scene_sha256':source['hashes']['scene'],
                                 'scope':'version attribution preserved in hash-checked delivered scene'})
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(cache_key,fingerprint))
        except (OSError,ValueError,KeyError,TypeError):
            # Unavailable or changed projects cannot create a delivery count.
            continue


def query(manager, args):
    sync(manager)
    days = str(args.get('days', 'all'))
    if days not in {'7', '30', 'all'}: raise ValueError('Unsupported time range')
    kind = args.get('kind', '')
    if kind and kind not in KINDS: raise ValueError('Unknown usage kind')
    entity = args.get('id', '')
    include = args.get('include_tests') in (True, 'true', '1')
    cutoff = '' if days=='all' else (datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat()
    clauses, params = ['at>=?'], [cutoff]
    for field, value in [('kind', kind), ('entity', entity)]:
        if value: clauses.append(field+'=?'); params.append(value)
    if not include: clauses.append('is_test=0')
    # Undated legacy applications are only in all-time totals, never assigned to today.
    if days != 'all': clauses.append("COALESCE(json_extract(evidence,'$.time_unknown'),0)=0")
    where = ' AND '.join(clauses)
    with connect(manager.data/'usage') as db:
        rows = db.execute("SELECT kind,entity,action,status,COUNT(*) AS count,MAX(CASE WHEN COALESCE(json_extract(evidence,'$.time_unknown'),0)=0 THEN at END) AS last_used,SUM(duration) AS total_seconds,COUNT(duration) AS timed FROM usage_events WHERE "+where+' GROUP BY kind,entity,action,status',params).fetchall()
        items = {}
        for r in rows:
            item = items.setdefault((r['kind'],r['entity']), {'kind':r['kind'],'id':r['entity'],'counts':{},'outcomes':{},'last_used':''})
            item['counts'][r['action']] = item['counts'].get(r['action'],0)+r['count']
            if r['action'] in {'call','rejected'}: item['outcomes'][r['status']] = r['count']
            if r['timed'] and r['action']=='call':
                item['_seconds']=item.get('_seconds',0)+r['total_seconds'];item['_timed']=item.get('_timed',0)+r['timed']
                item['avg_seconds']=item['_seconds']/item['_timed']
            item['last_used'] = max(item['last_used'],r['last_used'] or '')
        since = db.execute("SELECT value FROM meta WHERE key='enabled_since'").fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM usage_events WHERE '+where,params).fetchone()[0]
        offset = int(args.get('offset',0))
        if not 0 <= offset <= 10000000:raise ValueError('Invalid detail offset')
        details = [dict(r) for r in db.execute('SELECT * FROM usage_events WHERE '+where+' ORDER BY at DESC,event_key DESC LIMIT 100 OFFSET ?',[*params,offset])]
        for row in details:row['evidence']=json.loads(row['evidence'])
        titles = {}
        if not kind or kind=='experience':
            from scripts.experience_library import load_library
            _, entries, _ = load_library(manager.root,manager.data/'experience-library')
            titles.update({('experience',e['id']):e['title'] for e in entries})
        if not kind or kind=='tool':titles.update({('tool',t['id']):t['title'] for t in manager.catalog()})
        icon_db=manager.data/'icon-library/icons.sqlite3'
        if (not kind or kind=='icon') and icon_db.is_file():
            with sqlite3.connect(icon_db.as_uri()+'?mode=ro',uri=True) as icons:
                for k in items:
                    if k[0]!='icon':continue
                    row=icons.execute('SELECT metadata FROM icons WHERE version=?',(k[1],)).fetchone()
                    if row:titles[k]=json.loads(row[0]).get('name','')
        for k,item in items.items():
            item['title']=titles.get(k,'')
            item.pop('_seconds',None);item.pop('_timed',None)
        return {'items':sorted(items.values(),key=lambda r:r['last_used'],reverse=True), 'events':details, 'total_events':total,
                'next_offset':offset+100 if offset+100<total else None,'enabled_since':since,
                'storage_path':str(manager.data/'usage/usage.sqlite3'),
                'history_note':'工具历史按已有日志回填，经验查看从启用计数后记录。阶段打卡的推荐与实际采用分别计数，相同打卡重试去重。旧日志未标记的测试可能包含在历史累计中。'}


def record_ui(manager, args):
    if 'ids' in args:
        if set(args)-{'event_id','kind','ids','action'} or args.get('kind')!='experience' or args.get('action')!='retrieved':
            raise ValueError('Only experience retrieval supports batches')
        ids=args['ids'];event_id=args.get('event_id','')
        if not isinstance(ids,list) or len(ids)>200 or any(not isinstance(i,str) for i in ids):raise ValueError('Invalid IDs')
        if not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',event_id):raise ValueError('Invalid event ID')
        from scripts.experience_library import load_library
        _,rows,_=load_library(manager.root,manager.data/'experience-library')
        if set(ids)-{r['id'] for r in rows}:raise ValueError('Unknown experience ID')
        with connect(manager.data/'usage') as db:
            count=sum(insert(db,key('ui',event_id,'experience',i,'retrieved'),'experience',i,'retrieved',source='owner') for i in set(ids))
        return {'recorded':count}
    if set(args)-{'event_id','kind','id','action','source_id'}:raise ValueError('Unknown usage fields')
    kind, entity, action = args.get('kind'), args.get('id'), args.get('action')
    if kind not in KINDS or action not in {'viewed','source_viewed','retrieved'}:raise ValueError('Invalid usage event')
    event_id = args.get('event_id','')
    if not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',event_id):raise ValueError('Invalid event ID')
    if not isinstance(entity,str) or not 1<=len(entity)<=200:raise ValueError('Invalid entity')
    if kind=='experience':
        from scripts.experience_library import show
        entry=show(entity,manager.root,manager.data/'experience-library')
        if action=='source_viewed' and args.get('source_id') not in {s['source_id'] for s in entry['sources']}:
            raise ValueError('Source is not linked to this experience')
    elif kind=='tool':manager.tool(entity)
    elif kind=='icon':
        from .icons.library import Library
        Library(manager.data/'icon-library').row(entity)
    else:
        from .learning import status
        if entity not in {s['skill_id'] for s in status(manager)['skills']}:raise ValueError('Unknown skill')
    inserted=record(manager.data/'usage',key('ui',event_id,kind,entity,action),kind,entity,action,
                    source='owner',evidence={'source_id':args.get('source_id')})
    return {'recorded':bool(inserted)}


def cite(manager,args):
    if set(args)-{'id','project','task_id','reason','object_ids'}:raise ValueError('Unknown citation fields')
    from .policy import authorize
    from scripts.experience_library import show
    if not isinstance(args.get('project'),str):raise ValueError('Project is required')
    project,_=authorize(manager,args.get('project'))
    entry=show(args.get('id'),manager.root,manager.data/'experience-library')
    task=args.get('task_id','');reason=args.get('reason','');objects=args.get('object_ids',[])
    if not re.fullmatch(r'task-\d+',task):raise ValueError('Invalid task ID')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=2000:raise ValueError('Explain the concrete use')
    if not isinstance(objects,list) or len(objects)>100 or any(not isinstance(o,str) or len(o)>200 for o in objects):raise ValueError('Invalid object IDs')
    taskfile=project/'workflow/tasks'/task/'packet.json'
    if not taskfile.resolve().is_relative_to(project.resolve()) or not taskfile.is_file():raise ValueError('Task does not exist in this project')
    if json.loads(taskfile.read_text('utf-8'))['task_id']!=task:raise ValueError('Task identity mismatch')
    inserted=record(manager.data/'usage',key('citation',str(project),task,entry['id']), 'experience',entry['id'],'cited',
                    source='agent',project=str(project),task=task,
                    evidence=redact({'reason':reason,'object_ids':objects,'level':'agent_reported_not_validated'}))
    return {'recorded':bool(inserted),'scope':'记录任务引用，不证明方法有效或已通过验收'}


def call(manager,action,args):
    if action in {'summary','detail'}:return query(manager,args)
    if action=='record':return record_ui(manager,args)
    if action=='cite':return cite(manager,args)
    raise ValueError('Unknown usage operation')
