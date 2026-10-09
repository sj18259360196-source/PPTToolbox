"""Read-only visual workload projection. Does not observe host image/API traffic."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import threading
import time
from collections import Counter
from pathlib import Path
from scripts.project_journal import safe

LIMIT = 5000
LOCAL_KINDS = {'region_objects', 'asset_material', 'review_local', 'preview_local'}


def scope(kind):
    return 'detail' if kind in LOCAL_KINDS else 'overview'


class VisualIndex:
    """Cache compact metadata only; never keep decoded pixels or task tokens."""
    def __init__(self):
        self.cache = {}
        self.lock = threading.RLock()
        self.reads = 0
        self.projections = {}

    def read(self, root, relative, expected=None):
        path = safe(root, relative)
        stat = path.stat()
        if stat.st_size > 32 * 1024 * 1024:
            raise ValueError('视觉记录过大，未读取')
        key = str(path)
        identity = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        cached = self.cache.get(key)
        if cached and cached[0] == identity:
            if expected and cached[2] != expected:raise ValueError('视觉记录哈希不一致')
            return cached[1]
        raw = path.read_bytes(); self.reads += 1
        digest=hashlib.sha256(raw).hexdigest()
        if expected and digest != expected:
            raise ValueError('视觉记录哈希不一致')
        data = json.loads(raw.decode('utf-8-sig'))
        # Project packets can contain long prose, examples and credentials. Keep only evidence metadata.
        result = data.get('result') or {}
        value = {k:data.get(k) for k in ('task_id','kind','target','required_view_files','input_files','packet_sha256')}
        value['viewed_files'] = result.get('viewed_files', [])
        self.cache[key] = (identity, value, digest)
        if len(self.cache) > LIMIT * 3:
            self.cache.pop(next(iter(self.cache)))
        return value

    def project(self, root, workflow, calls):
        with self.lock:
            root=Path(root);cached=self.projections.get(str(root))
            active=workflow.get('active_task') or {}
            current_paths=[active['packet']] if active.get('packet') else []
            if cached and cached[2].get('active',{}):
                current_paths.extend(f['path'] for f in cached[2]['active']['files'])
            fingerprints=[]
            for relative in current_paths:
                try:
                    stat=safe(root,relative).stat()
                    fingerprints.append((relative,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size))
                except (OSError,ValueError):fingerprints.append((relative,'unavailable'))
            identity=(workflow.get('revision'),active.get('id'),active.get('packet_sha256'),
                      len(workflow.get('history',[])),len(workflow.get('accepted',[])),
                      json.dumps(calls,sort_keys=True),fingerprints)
            if cached and cached[0]==identity and time.monotonic()-cached[1]<30:
                return copy.deepcopy(cached[2])
            result=self._project(root,workflow,calls)
            # Recompute fingerprints once the first scan has discovered current views.
            fingerprints=[]
            for relative in ([active['packet']] if active.get('packet') else [])+[f['path'] for f in (result.get('active') or {}).get('files',[])]:
                try:
                    stat=safe(root,relative).stat();fingerprints.append((relative,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size))
                except (OSError,ValueError):fingerprints.append((relative,'unavailable'))
            identity=(*identity[:-1],fingerprints)
            self.projections[str(root)]=(identity,time.monotonic(),copy.deepcopy(result))
            if len(self.projections)>32:self.projections.pop(next(iter(self.projections)))
            return result

    def _project(self, root, workflow, calls):
        counters = {name:{'required':0,'submitted':0,'file_bytes':0,'unknown_bytes':0} for name in ('overview','detail')}
        errors = []; seen = {}; recent = []; tasks = {}; submitted_tasks = set()
        def problem(task, path, exc):
            errors.append({'task_id':task,'path':path,'message':str(exc)[:240]})
        issued = dict.fromkeys(e.get('detail',{}).get('id') for e in workflow.get('history',[])
                               if e.get('event') == 'task_issued')
        active = workflow.get('active_task') or {}
        if active.get('id'):issued.setdefault(active['id'], None)
        task_ids = [i for i in issued if isinstance(i,str)]
        limited = len(task_ids) > LIMIT
        # Oldest-first counters include each issued task once; next retries do not add images.
        for tid in task_ids[:LIMIT]:
            rel = 'workflow/tasks/'+tid+'/packet.json'
            try:
                packet = self.read(root,rel,active.get('packet_sha256') if tid==active.get('id') else None)
                if packet['task_id'] != tid:raise ValueError('任务身份不一致')
                images = packet['required_view_files'] or []
                if not isinstance(images,list) or len(images)>1000:raise ValueError('必看图片清单无效')
                role = scope(packet['kind']); entries = []
                hashes = {v['file']:v['sha256'] for v in packet['input_files'] or []}
                for relative in dict.fromkeys(images):
                    count = counters[role];count['required'] += 1
                    size = None;digest = hashes.get(relative)
                    try:
                        path = safe(root,relative); stat = path.stat();size=stat.st_size
                        if not digest:raise ValueError('图片缺少任务绑定哈希')
                        if tid == active.get('id'):
                            # Recheck the current view when its metadata changes, without decoding old images.
                            identity=(stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,digest)
                            key='image:'+str(path)
                            if self.cache.get(key) != identity:
                                if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                                    raise ValueError('当前必看图片已改变，请先核对文件')
                                self.cache[key]=identity
                        count['file_bytes'] += size
                    except (OSError,ValueError) as exc:
                        count['unknown_bytes'] += 1;problem(tid,relative,exc)
                    if digest:seen.setdefault(digest,{'count':0,'bytes':size})['count'] += 1
                    entries.append({'path':relative,'sha256':digest,'file_bytes':size})
                tasks[tid]={'task_id':tid,'kind':packet['kind'],'scope':role,'target':packet['target'],
                            'files':entries,'required':len(entries),'file_bytes':sum(i['file_bytes'] or 0 for i in entries)}
                if entries:recent.append(tasks[tid])
            except (OSError,ValueError,KeyError,TypeError) as exc:problem(tid,rel,exc)
        records = {r['file']:r for r in workflow.get('accepted',[]) if isinstance(r,dict) and r.get('file')}
        limited=limited or len(records)>LIMIT*2
        for relative,ref in list(records.items())[:LIMIT*2]:
            try:
                record=self.read(root,relative,ref.get('sha256'))
                tid=record['task_id']
                if tid not in tasks:continue
                if record.get('packet_sha256'):
                    self.read(root,'workflow/tasks/'+tid+'/packet.json',record['packet_sha256'])
                viewed=record['viewed_files']
                if not isinstance(viewed,list):raise ValueError('观察记录的图片清单无效')
                if viewed:
                    counters[scope(record['kind'])]['submitted'] += len(set(viewed))
                    submitted_tasks.add(tid)
            except (OSError,ValueError,KeyError,TypeError) as exc:problem(None,relative,exc)
        repeats = Counter(c.get('task_id') for c in calls if c.get('tool')=='workflow.next'
                          and c.get('status') in {'completed','succeeded','passed','ok'} and c.get('task_id'))
        retry_count=sum(max(0,v-1) for v in repeats.values())
        durations=[c['elapsed_seconds'] for c in calls if isinstance(c.get('elapsed_seconds'),(int,float))
                   and math.isfinite(c['elapsed_seconds']) and c['elapsed_seconds']>=0]
        recent_bytes=sum(t['file_bytes'] for t in recent[-24:])
        notices=[]
        if retry_count>=3:notices.append('最近调用中多次领取同一任务，先处理当前任务；提交后优先使用 return_next。')
        if recent_bytes>=20*1024*1024:
            notices.append('最近 24 个看图任务的必看文件累计超过 20 MiB。保存当前发现，按实际上下文选择短对话续作。此数值是工具箱提醒条件，不是供应商上限。')
        return {'format':'ppt-visual-activity/1','coverage':'partial' if errors or limited else 'available',
                'overview':counters['overview'],'detail':counters['detail'],
                'unique_images':len(seen),'repeat_image_requirements':sum(max(0,x['count']-1) for x in seen.values()),
                'required_file_bytes':sum(c['file_bytes'] for c in counters.values()),'recent_required_file_bytes':recent_bytes,
                'issued_tasks':len(tasks),'repeated_next_calls':retry_count,'recent_call_count':len(calls),
                'tool_elapsed_seconds':round(sum(durations),3),'timed_calls':len(durations),
                'retained_source_reviews':sum(bool(p.get('source_review_reuse')) and (p.get('source_review') or {}).get('status')=='passed' for p in workflow.get('pages',[])),
                'retained_visual_reviews':len(((workflow.get('run') or {}).get('reused_observations') or {}).get('records',{})),
                'active':tasks.get(active.get('id')),'recent_tasks':[{**t,'observation_submitted':t['task_id'] in submitted_tasks} for t in recent[-8:]],
                'diagnostics':errors[:12],'diagnostic_count':len(errors),'limited':limited,'notices':notices,
                'host_image_reads':None,'provider_request_bytes':None,'provider_latency_seconds':None,
                'measurement_note':'要求查看按已发出的任务去重计数，已提交观察来自 Agent 回执。文件字节为本地累计值，宿主实际查看、上传量和供应商延迟未知。工具耗时仅覆盖最近调用。'}


def project_visuals(manager, root, workflow, calls):
    if not hasattr(manager,'_visual_index'):manager._visual_index=VisualIndex()
    return manager._visual_index.project(root,workflow,calls)
