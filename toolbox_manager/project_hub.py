"""Folder projects, activity projection and background file observation."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import re
import threading
import time
import uuid

from scripts import project_journal as journal
from .policy import plain_path
from .storage import stamp


def entry(manager, key):
    from .workbench import Workbench
    return Workbench(manager).entry(key)


def index(manager, root, identity=None, *, refresh_hierarchy=True):
    from .projects import mutate
    root = plain_path(root)
    state_path = journal.safe(root, 'workflow/state.json')
    workflow = journal.read_json(state_path, {})
    if state_path.exists() and (not isinstance(workflow,dict) or not isinstance(workflow.get('project_id'),str)
                               or (workflow.get('format') and not workflow['format'].startswith('ppt-workflow/'))):
        raise ValueError('该目录没有可识别的 PPT 工作流身份，未写入项目记录')
    root_key = os.path.normcase(os.path.normpath(str(root)))
    old_row = next((r for r in manager.store.get('workbench_projects', {}).values()
                    if os.path.normcase(os.path.normpath(r['path'])) == root_key), {})
    portable = journal.ensure(root, workflow.get('project_id') or (identity or {}).get('project_id'), old_row.get('label'))
    # Resolve conflicting locations outside the SQLite writer transaction.
    locations = {k:(r['path'], plain_path(r['path']).exists()) for k,r in
                 manager.store.get('workbench_projects', {}).items() if r['project_id']==portable['project_id']}
    def change(rows):
        for key, row in rows.items():
            if row['project_id'] == portable['project_id']:
                old = Path(row['path'])
                if key not in locations or locations[key][0] != row['path']:
                    raise ValueError('项目登记同时更新，请重新扫描')
                if old != root and locations[key][1]:
                    raise ValueError('发现同一项目编号的两个目录，未合并记录')
                if old != root:
                    row.setdefault('path_history', []).append({'path': str(old), 'until': stamp()})
                row.update(path=str(root), label=portable['label'], updated_at=portable['updated_at'])
                return key
        key = 'folder-' + portable['project_id']
        rows[key] = {'path': str(root), 'project_id': portable['project_id'], 'label': portable['label'],
                     'category': portable.get('category','folder'), 'archived': portable.get('archived',False), 'metadata_revision': 0, 'editable': False,
                     'scope': 'folder-project', 'created_at': stamp(), 'updated_at': stamp()}
        return key
    key = mutate(manager.store, change)
    from .projects import cache_summary
    cache_summary(manager, key, workflow or {'status':'folder'})
    if refresh_hierarchy:
        hierarchy(manager)
    return key


def hierarchy(manager):
    from .projects import mutate
    # Validate paths before taking SQLite's writer lock so observation cannot
    # block an independent Agent's connection during a large folder scan.
    for _ in range(3):
        snapshot = manager.store.get('workbench_projects', {})
        identities = {key: row['path'] for key, row in snapshot.items()}
        paths = {key: plain_path(value) for key, value in identities.items()}
        parents = {}
        for key, root in paths.items():
            candidates = [(k, path) for k, path in paths.items()
                          if k != key and root != path and root.is_relative_to(path)]
            parents[key] = max(candidates, key=lambda p: len(p[1].parts))[0] if candidates else None
        def change(rows):
            if {key: row['path'] for key, row in rows.items()} != identities:
                return False
            for key, row in rows.items():
                row['parent_id'] = parents[key]
            return True
        if mutate(manager.store, change):
            return


def create(manager, body):
    name = body.get('name', '')
    if isinstance(name, str): name = name.strip()
    if not isinstance(name, str) or not name or len(name) > 100 or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.rstrip(' .') != name or name in {'.','..'} or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        raise ValueError('请使用有效的文件夹名称')
    if body.get('parent'):
        base = entry(manager, body['parent'])[0]
    else:
        configured = manager.settings().get('projects_directory')
        if not configured:
            raise ValueError('请先在设置中选择默认项目根目录')
        base = plain_path(configured)
    root = journal.safe(base, name)
    root.mkdir(exist_ok=False)
    journal.ensure(root, label=name)
    key = index(manager, root)
    manager.store.event('project.folder_created', '已创建项目文件夹', source='owner', details={'project': str(root), 'view_id': key})
    return {'id': key, 'path': str(root)}


def scan(manager):
    configured = manager.settings().get('projects_directory')
    if not configured:
        return {'found': [], 'errors': [], 'message': '未配置项目根目录'}
    base = plain_path(configured)
    found, errors = [], []
    pending = [(base, 0)]; visited = 0
    while pending and visited < 3000:
        folder, depth = pending.pop(); visited += 1
        try:
            if folder != base and ((folder/'.ppttool/state.json').is_file() or (folder/'ppttool.md').is_file() or (folder/'workflow/state.json').is_file()):
                found.append(index(manager, folder, refresh_hierarchy=False))
            if depth < 5:
                for child in folder.iterdir():
                    if child.name.startswith('.') or child.name in {'input','assets','runs','workflow','logs','delivery','node_modules','previews','trials','cache'}:
                        continue
                    if child.is_dir():
                        pending.append((plain_path(child), depth + 1))
        except (OSError, ValueError) as exc:
            errors.append({'path': str(folder), 'error': str(exc)})
    hierarchy(manager)
    return {'found': found, 'errors': errors, 'limited': bool(pending)}


def files(root, children=()):
    """Bounded metadata scan, excluding nested projects and our own records."""
    selected = []; visited = 0
    excluded = {str(p).casefold() for p in children}
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if not d.startswith('.') and d not in {'node_modules','logs','tasks','archives','__pycache__','cache'}
            and str(Path(folder)/d).casefold() not in excluded and not (Path(folder)/d).is_symlink()
            and not getattr((Path(folder)/d).stat(), 'st_file_attributes', 0) & 0x400]
        for name in names:
            visited += 1
            if visited > 8000:
                return selected, True
            path = Path(folder)/name
            if name == 'ppttool.md' or name.startswith('~$') or not (path.suffix.lower() in {'.pptx','.md','.pdf'} or name == 'office-render.json'):
                continue
            try:
                relative = path.relative_to(root).as_posix(); path = journal.safe(root, relative); st = path.stat()
                selected.append({'path': relative, 'name': name, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns})
            except (OSError, ValueError):
                continue
    return sorted(selected, key=lambda x: (-x['mtime_ns'], x['path']))[:500], False


def observe(manager, key):
    root, row, workflow = entry(manager, key)
    state = journal.ensure(root, row['project_id'], row['label'])
    # Exclusion uses registered lexical paths; files() validates any path it reads.
    children = [Path(r['path']) for k,r in manager.store.get('workbench_projects', {}).items()
                if k != key and Path(r['path']).is_relative_to(root)]
    items, limited = files(root, children)
    with manager.store.db() as db:
        events = db.execute("SELECT id,time,action,status,message,details FROM events WHERE json_extract(details,'$.project')=? AND (action LIKE 'tool.%' OR action LIKE 'activity.%' OR action LIKE 'icons.%' OR action LIKE 'graphics.%') ORDER BY id DESC LIMIT 120", (str(root),)).fetchall()
        # Revisit evidence around old unbound failures, even outside the recent window.
        extra=[]
        for issue in state.get('activity',{}).get('issues',[]):
            if issue.get('state')!='open' or issue.get('task_id') or issue.get('tool') not in {'workflow.start','workflow.submit','workflow.replace-scene'}:
                continue
            evidence=issue.get('evidence_id','').removeprefix('audit-')
            if not evidence.isdigit():continue
            eid=int(evidence)
            query="SELECT id,time,action,status,message,details FROM events WHERE json_extract(details,'$.project')=? AND action='tool.finished' AND json_extract(details,'$.tool_id') LIKE 'workflow.%' AND id"
            extra+=db.execute(query+"<? ORDER BY id DESC LIMIT 1",(str(root),eid)).fetchall()
            extra+=db.execute(query+">=? ORDER BY id ASC LIMIT 32",(str(root),eid)).fetchall()
        events=sorted({e['id']:e for e in [*events,*extra]}.values(),key=lambda e:e['id'],reverse=True)
    calls = {}
    wrapped = {}
    for e in events:
        d=json.loads(e['details'] or '{}')
        if e['action'] in {'activity.started','activity.finished'}:
            item=wrapped.setdefault(d.get('call_id'),{'tool':d.get('tool_id')})
            item[e['action'].split('.')[-1]]=e['id']
    from .execution import process_alive
    for event in reversed(events):
        detail = json.loads(event['details'] or '{}'); cid = detail.get('call_id')
        legacy = event['action'].startswith(('icons.','graphics.'))
        if legacy:
            # New wrappers already carry the lifecycle; old versions only wrote a final event.
            if any(w['tool']==event['action'] and w.get('started',event['id'])<event['id']<w.get('finished',event['id']) for w in wrapped.values()):
                continue
            cid = cid or 'legacy-'+str(event['id'])
        if not cid:
            continue
        status = detail.get('command_status') or ('failed' if event['status'] == 'error' else 'completed' if legacy else 'running')
        if event['action'] in {'tool.started','tool.authorized','tool.launched','activity.started'}:
            alive = process_alive(detail.get('worker_pid') or detail.get('owner_pid'))
            status = 'running' if alive is True else 'outcome_unknown'
            if status=='outcome_unknown' and event['action']=='activity.started':
                import re
                if re.fullmatch(r'[a-f0-9]{32}',cid):
                    receipt=journal.safe(root,'logs/tool-calls/'+cid+'/activity.json')
                    try:
                        if receipt.stat().st_size <= 16*1024*1024:
                            saved=json.loads(receipt.read_text('utf-8'))
                            if saved.get('call_id')==cid and saved.get('command_status') not in {None,'started','running'}:
                                detail={**detail,**{k:v for k,v in saved.items() if k!='result'}}
                                status=saved['command_status']
                    except (OSError,ValueError):pass

        from .project_status import safe_message
        calls[cid] = {'id': cid, 'tool': detail.get('tool_id',event['action'] if legacy else ''), 'status': status,
            'project':str(root), 'project_id':detail.get('project_id'),
            'revision_before':detail.get('revision_before'), 'revision_after':detail.get('revision_after'),
            'at': event['time'], 'task_id': detail.get('task_id'), 'task_kind': detail.get('task_kind'),
            'error_code':detail.get('error_code'), 'reason_code':detail.get('reason_code'),
            'message':safe_message(detail.get('error_message') or detail.get('error') or detail.get('reason') or ''),
            'recovery':detail.get('recovery') or {}, 'evidence_id': 'audit-'+str(event['id'])}
        calls[cid]['elapsed_seconds']=(detail.get('timings') or {}).get('through_worker_seconds')
    history = [{'at': e.get('at'), 'event': e.get('event'), 'detail': {k:v for k,v in e.get('detail',{}).items() if k in {'kind','id','reason','region_id','slide_id'}}}
               for e in workflow.get('history', [])[-25:]]
    from .agent_presence import status as connection_status
    connection = connection_status(manager)
    from .project_status import reconcile, generation_routes
    activity = {'calls': list(calls.values())[-30:],
                'generation_routes':generation_routes(workflow),
                'issues':reconcile(state.get('activity',{}).get('issues',[]),list(calls.values())),
                'history': history, 'workflow_status': workflow.get('status'),
                'connection': {'state': connection['state'], 'connected_count': connection['connected_count']},
                'task': {k:v for k,v in (workflow.get('active_task') or {}).items() if k in {'id','kind','target'}},
                'file_scan_limited': limited}
    from .issue_assessment import assess
    activity['issues']=assess({**state,'activity':activity})['issues']
    from .visual_activity import project_visuals
    try:
        activity['visual']=project_visuals(manager,root,workflow,activity['calls'])
    except Exception as exc:
        activity['visual']={'coverage':'unavailable','diagnostics':[{'message':safe_message(exc)}],
                            'diagnostic_count':1,'measurement_note':'图片统计暂不可用；未将缺失数据记为零。'}
    # Connection loss never rewrites a successful/failed tool result.
    changes={'activity': activity, 'files': items, 'notes_revision': journal.notes(root)['revision']}
    phase=state.get('phase',{})
    if phase.get('artifacts'):
        artifacts=[{'path':f['path'],'exists':journal.safe(root,f['path']).is_file()} for f in phase['artifacts']]
        changes['phase']={**phase,'artifacts':artifacts,'artifact_state':'present' if all(f['exists'] for f in artifacts) else 'unconfirmed'}
    saved = journal.update(root, changes, detail={'origin': 'tool_events_and_file_metadata'}, expected_sequence=state['sequence'])
    from .projects import cache_summary
    cache_summary(manager, key, workflow)
    return journal.load(root) if saved.get('discarded') else saved


def recommendations(manager, root, state):
    from scripts import rebuild_assistance as advice
    phase = state.get('phase', {})
    query = ' '.join([state.get('label',''), phase.get('next_action',''), phase.get('blocker') or ''])
    return advice.search(query or '制作方案', stage=phase.get('stage'), external_root=manager.data/'experience-library')['matches']


def snapshot(manager, key):
    root, row, workflow = entry(manager, key)
    observer = getattr(manager, 'project_observer', None)
    if observer:
        observer.selected = key
        observer.selected_until = time.monotonic()+10
    state = journal.load(root)
    if not state:
        return {'project': key, 'label': row['label'], 'path': str(root), 'syncing': True,
                'phase': {}, 'checkpoints': [], 'activity': {}, 'files': [], 'recommendations': [], 'sequence': 0}
    summary = state.get('summary', {})
    suggested = recommendations(manager, root, state)
    if summary.get('status') == 'ready':
        preferred = summary.get('recommended_ids', [])
        suggested.sort(key=lambda r: preferred.index(r['id']) if r['id'] in preferred else len(preferred))
    from .project_status import graph
    from .issue_assessment import assess, handoff
    from scripts.project_flow import STEP_TYPES
    from .pptagent_metrics import project_status as assistant_status
    from .flow_semantics import lifecycle, hydrate
    state={**state,'flow_lifecycle':lifecycle(manager,workflow),
           'work_graph':{**state.get('work_graph',{}),'nodes':hydrate(manager,root,state.get('work_graph',{}).get('nodes',[]))}}
    return {**state, 'project': key, 'path': str(root), 'workflow_status': workflow.get('status'),
            'assistant':assistant_status(manager,key,state),
            'display_graph':graph(state), 'step_types':STEP_TYPES,
            'issue_view':assess(state), 'assistance_packet':handoff(state),
            'notes': journal.notes(root),
            'recommendations': suggested, 'summary': summary,
            'stages': [{'id':i,'label':t} for i,t in journal.STAGES],
            'observer_error': ((observer.errors.get(key) or observer.errors.get('_observer')) if observer else None)}


def acknowledge_issue(manager, body):
    root, _, _ = entry(manager, body.get('project'))
    state = journal.load(root)
    if body.get('sequence') != state.get('sequence'):
        raise ValueError('项目记录已经变化，请刷新后重试')
    activity = state.get('activity', {})
    target = next((i for i in activity.get('issues', []) if i['id']==body.get('id')), None)
    if not target: raise ValueError('没有找到这条异常记录')
    target.update(state='acknowledged', acknowledged_at=stamp(), acknowledged_by='owner')
    saved = journal.update(root, {'activity':activity}, detail={'origin':'owner_issue_acknowledgement'}, expected_sequence=state['sequence'])
    if saved.get('discarded'): raise ValueError('项目记录已经变化，请刷新后重试')
    return saved


def checkpoint(manager, body):
    from .policy import authorize
    from scripts.experience_library import load_library
    root, row, _ = entry(manager, body.get('project'))
    authorize(manager, root)
    ensure = journal.ensure(root, row['project_id'], row['label'])
    values = {k:v for k,v in body.items() if k != 'project'}
    known = {e['id'] for e in load_library(manager.root, manager.data/'experience-library')[1]}
    if set(values.get('used_experiences', [])) - known:
        raise ValueError('实际采用记录包含未知经验编号')
    record = journal.checkpoint(root, values)
    from scripts.usage_store import record as usage_record, key as usage_key
    warnings = []
    suggested = recommendations(manager, root, journal.load(root))
    try:
        for item in suggested:
            usage_record(manager.data/'usage',usage_key('checkpoint-recommendation',str(root),values['checkpoint_id'],item['id']),
                'experience',item['id'],'retrieved',project=str(root),task='checkpoint:'+values['checkpoint_id'],
                evidence={'level':'recommended_only','stage':record['stage']})
        for identifier in values.get('used_experiences', []):
            usage_record(manager.data/'usage', usage_key('checkpoint-citation',str(root),values['checkpoint_id'],identifier),
                'experience', identifier, 'cited', project=str(root), task='checkpoint:'+values['checkpoint_id'],
                evidence={'reason': values['result_summary'], 'level':'agent_reported_not_validated'})
    except Exception:
        warnings.append('打卡已保存，经验汇总暂未更新；采用记录仍保留在项目内')
    return {**record, 'recommendations': suggested,
            'next_revision': record['revision'], 'warnings': warnings}


def stage_context(manager, project):
    from scripts.project_flow import STEP_TYPES
    from .issue_assessment import handoff
    if not any(project in {key,row['project_id'],row['path']} for key,row in manager.store.get('workbench_projects',{}).items()):
        return None
    root, row, _ = entry(manager, project)
    state = journal.ensure(root, row['project_id'], row['label'])
    visual=state.get('activity',{}).get('visual')
    visual_context=({'coverage':visual.get('coverage'),'observed_at':state.get('updated_at'),
        **{k:visual.get(k) for k in ('overview','detail','recent_required_file_bytes','repeated_next_calls','diagnostic_count','notices')},
        'measurement_note':'项目观察器的最近快照，可能晚于当前任务；字节为本地文件统计，宿主查看及供应商流量未知。'}
        if visual else {'coverage':'pending','measurement_note':'项目观察器尚未采集图片统计；未知值不能当作零。'})
    return {k:state.get(k) for k in ('project_id','run_id','phase_revision','phase','checkpoint_required')} | {
        'visual_context':visual_context,
        'assistance_packet':handoff(state),
        'stages':[{'id':i,'label':t} for i,t in journal.STAGES], 'tool':'toolbox_checkpoint',
        'step_types':STEP_TYPES,
        'recommendations':recommendations(manager,root,state),
        'instructions':'大阶段开始、切换及交付收尾必须打卡。正常流程共六次，可随 rebuild_next 或 rebuild_submit 的 checkpoint 一起提交。阶段内无需逐调用或定时汇报。遇到改道、阻塞、暂停、恢复时登记对应事件；同一请求重试保留 checkpoint_id。used_experiences 只填写实际采用的条目。工作图自动归类任务并显示建议后续；细分路径可在同一次打卡的 flow 中批量提交变化项。新增项填 id、kind、after，优先 step_types，不适用时每批增一到两个 title 自定义节点。after 多项表示汇合；links 按 from 标明 relation（dependency/sequence/decision/merge/revision/suggested/grouping）、label 条件、basis（recorded/agent/inferred/suggested）和 evidence_ids。有据才填依赖，推断或建议必须标明。task_ids 绑定任务，result 记结果，next_action 记下一步。反馈后新增修改范围、返修、复查节点及 round，保留旧路径；分支接回合成或复查，再到交付。无需新增图片、每步汇报或为更新图而重试制作。'}


def previews(manager, key):
    root, row, workflow = entry(manager, key)
    state = journal.load(root)
    files_ = state.get('files', [])
    decks = [f for f in files_ if f['path'].lower().endswith('.pptx')]
    # The UI displays one current artifact. Historical PPTs remain on disk.
    from .project_inventory import lifecycle
    life = lifecycle(root)
    preferred = [life.get('delivery')]
    delivery = workflow.get('delivery')
    if workflow.get('status')=='delivered' and isinstance(delivery,str):
        preferred += [delivery, delivery.rstrip('/\\')+'/editable.pptx']
    preferred += [workflow.get('candidate')]
    run = workflow.get('run') or {}
    candidate = run.get('candidate') or {}
    if isinstance(candidate,dict): preferred += [candidate.get('file')]
    preferred += [f.get('path') for f in state.get('phase',{}).get('artifacts',[]) if f.get('exists')]
    current = next((d for p in preferred if isinstance(p,str) for d in decks if d['path']==p.replace('\\','/')),None)
    if current is None:
        current = next((d for d in decks if not set(Path(d['path']).parts)&{'input','references','trials','tests'}),None)
    results = []
    for deck in [current] if current else []:
        item = {**deck, 'slides': [], 'state': '等待匹配预览'}
        if deck['size'] > 250*1024*1024 or time.time_ns()-deck['mtime_ns'] < 2_000_000_000:
            item['state'] = '文件正在保存或超过预览上限'; results.append(item); continue
        path = journal.safe(root, deck['path'])
        if not path.exists() or path.stat().st_mtime_ns != deck['mtime_ns']:
            item['state'] = '文件已变化，等待扫描'; results.append(item); continue
        cachekey = (str(path), deck['mtime_ns'], deck['size'])
        hashes = getattr(manager, '_preview_hashes', {})
        if cachekey not in hashes:
            with path.open('rb') as f:
                hashes[cachekey] = hashlib.file_digest(f, 'sha256').hexdigest()
            manager._preview_hashes = dict(list(hashes.items())[-100:])
        digest = hashes[cachekey]
        final_stat = path.stat()
        if final_stat.st_mtime_ns != deck['mtime_ns'] or final_stat.st_size != deck['size']:
            hashes.pop(cachekey, None)
            item['state'] = '文件正在保存，等待扫描'; results.append(item); continue
        receipts = [journal.safe(root, f['path']) for f in files_ if f['name'] == 'office-render.json']
        cache = journal.safe(root, '.ppttool/previews/'+digest+'/office-render.json')
        if cache.exists(): receipts.append(cache)
        for receipt in receipts:
            try:
                if receipt.stat().st_size > 2_000_000: continue
                data = journal.read_json(receipt, {})
                if data.get('pptx_sha256') != digest or data.get('status') != 'passed': continue
                slides = sorted(p for p in receipt.parent.iterdir() if re.fullmatch(r'slide[-_]?\d+\.(png|jpe?g|webp)', p.name, re.I))
                item['slides'] = [journal.safe(root,p.relative_to(root)).relative_to(root).as_posix() for p in slides]
                if slides: item['state'] = '已匹配当前文件'; break
            except (ValueError, OSError):
                continue
        results.append(item)
    return {'decks': results, 'current_only': True, 'limited': False}


class Observer:
    def __init__(self, manager):
        self.manager = manager; self.selected = None; self.errors = {}; self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name='ppttool-project-observer', daemon=True)
        self.cursor = 0; self.selected_until = 0; self.event_cursor = 0

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set(); self.thread.join(timeout=6)

    def run(self):
        while not self.stop_event.is_set():
            try:
                rows = self.manager.store.get('workbench_projects', {})
                keys = list(rows)
                targets = [self.selected] if self.selected in rows and time.monotonic()<self.selected_until else []
                with self.manager.store.db() as db:
                    events = db.execute("SELECT id,details FROM events WHERE id>? AND (action LIKE 'tool.%' OR action LIKE 'activity.%') ORDER BY id DESC LIMIT 100",(self.event_cursor,)).fetchall()
                if events:
                    self.event_cursor=events[0]['id']
                    active_paths={json.loads(e['details']).get('project') for e in events}
                    targets += [key for key,row in rows.items() if row['path'] in active_paths]
                if keys:
                    key=keys[self.cursor % len(keys)]; self.cursor += 1
                    # Reconcile small status records only. Never inventory every
                    # registered project's files just because the list is visible.
                    try:
                        self.pending_checkpoints(key)
                        from .projects import cache_summary
                        cache_summary(self.manager,key)
                        saved=journal.load(entry(self.manager,key)[0])
                        helper=getattr(self.manager,'pptagent_worker',None)
                        if helper and not rows[key].get('archived') and (saved.get('assistant_dispatch') or saved.get('assistant_recording',{}).get('has_more') or key==self.selected):
                            helper.offer(key,saved)
                    except (OSError,ValueError) as exc:
                        self.errors[key]=str(exc)
                for key in dict.fromkeys(targets):
                    try:
                        self.pending_checkpoints(key)
                        state = observe(self.manager, key); self.errors.pop(key, None)
                        helper = getattr(self.manager, 'pptagent_worker', None)
                        if helper: helper.offer(key, state)
                    except (OSError, ValueError) as exc:
                        self.errors[key] = str(exc)
                self.errors.pop('_observer', None)
            except Exception as exc:
                self.errors['_observer'] = type(exc).__name__ + ': ' + str(exc)[:300]
            self.stop_event.wait(2)

    def pending_checkpoints(self,key):
        root,_,_=entry(self.manager,key)
        folder=journal.safe(root,'.ppttool/checkpoints/pending')
        for path in list(folder.glob('*.json'))[:10] if folder.is_dir() else []:
            path=journal.safe(root,path.relative_to(root))
            if path.stat().st_size>20000:raise ValueError('离线打卡文件过大')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            receipt=journal.safe(root,'.ppttool/checkpoints/receipts/'+digest+'.json')
            if receipt.is_file():continue
            result=checkpoint(self.manager,{**journal.read_json(path),'project':key})
            receipt.parent.mkdir(parents=True,exist_ok=True)
            journal.atomic(receipt,result)
