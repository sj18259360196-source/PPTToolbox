"""Durable single-writer state and immutable task inputs; no daemon/background jobs."""
from __future__ import annotations
import contextlib
import copy
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from common import read_json, write_json, sha256
from evidence_session import measured

FORMAT='ppt-workflow/1.2'

def now():return datetime.now(timezone.utc).isoformat()

class WorkflowError(ValueError):
    def __init__(self, code, message, hint=''):
        super().__init__(message);self.code=code;self.hint=hint


def under(root:Path, rel:str, must_exist=True):
    if not isinstance(rel,str) or not rel or '\\' in rel or ':' in rel or Path(rel).is_absolute():
        raise WorkflowError('unsafe_path',f'Invalid project-relative path: {rel!r}')
    p=(root/rel).resolve()
    if not p.is_relative_to(root.resolve()):raise WorkflowError('unsafe_path',f'Path leaves project: {rel}')
    if must_exist and not p.is_file():raise WorkflowError('missing_file',f'Missing project file: {rel}')
    return p

@contextlib.contextmanager
def locked(root:Path):
    folder=root/'workflow'
    if not folder.is_dir() or not (folder/'state.json').is_file():raise WorkflowError('not_initialized','No managed workflow; use start in a new project')
    path=folder/'writer.lock';token=uuid.uuid4().hex
    value={'pid':os.getpid(),'host':socket.gethostname(),'token':token,'created_at':now()}
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise WorkflowError('writer_busy','Project has an active or interrupted writer lock. No automatic lock deletion.',
                            'Read workflow/writer.lock. After confirming no active writer, use unlock with its token.')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as h:json.dump(value,h)
        marker=root/'workflow/project-lifecycle.json'
        if marker.exists() and read_json(marker).get('status')=='completed':
            raise WorkflowError('project_completed','Project is completed. Reopen from project management before writing; cleaned history cannot be resumed.')
        yield
    finally:
        try:
            if read_json(path).get('token')==token:path.unlink()
        except (FileNotFoundError,ValueError):pass


def unlock(root:Path, token:str, confirmed:bool):
    if not confirmed:raise WorkflowError('confirmation_required','Confirm no active writer before releasing a stale lock')
    p=root/'workflow/writer.lock'
    if not p.is_file():return {'command_status':'completed','note':'No lock exists'}
    lock=read_json(p)
    if lock.get('token')!=token:raise WorkflowError('lock_token_mismatch','Lock identity changed; read it again')
    # Explicit local recovery only. No process termination or age-based assumptions.
    p.unlink();return {'command_status':'completed','released_token':token,'scope':'Caller confirmed no active writer; no process killed'}


@measured("state_validation")
def load(root:Path):
    marker=root/'workflow/project-lifecycle.json'
    if marker.exists() and read_json(marker).get('history_cleaned'):
        raise WorkflowError('history_cleaned','Production history was explicitly cleared after completion. Open the retained delivery or create a new project.')
    s=read_json(root/'workflow/state.json')
    if s.get('format')!=FORMAT:raise WorkflowError('unsupported_state','Workflow format differs; do not edit its version field')
    for rel,h in s.get('tracked_inputs',{}).items():
        if sha256(under(root,rel))!=h:raise WorkflowError('input_changed',f'Immutable input changed: {rel}','Restore the original, or start a new explicit input revision/project.')
    for record in s.get('accepted',[]):
        if sha256(under(root,record['file']))!=record['sha256']:raise WorkflowError('record_changed','Accepted task record changed: '+record['file'])
    run=s.get('run')
    if run:
        base=under(root,run['dir']+'/scene.json').parent
        for rel,h in run['frozen'].items():
            if sha256(under(base,rel))!=h:raise WorkflowError('run_input_changed','Frozen run input changed: '+rel)
        for key in ['candidate','audit','render','comparison','review','gate']:
            if run.get(key):
                if sha256(under(root,run[key]['file']))!=run[key]['sha256']:
                    raise WorkflowError('artifact_changed',f'Current {key} changed outside the controller','Use a new candidate/revision, not a manual overwrite.')
        if run.get('preview'):
            for key in ['render','comparison']:
                rec=run['preview'][key]
                if sha256(under(root,rec['file']))!=rec['sha256']:
                    raise WorkflowError('artifact_changed','Current preview '+key+' changed outside the controller')
    from source_review_reuse import verify
    verify(root,s)
    return s


@measured("state_write")
def save(root:Path, state:dict, event:str, detail=None):
    s=state;s['revision']+=1;s['updated_at']=now()
    s.setdefault('history',[]).append({'revision':s['revision'],'event':event,'detail':detail or {},'at':s['updated_at']})
    # The state contains its journal in the same atomic commit. Handoff is derived/cache only.
    write_json(root/'workflow/state.json',s)
    summary=brief(s)
    lines=['# 当前制作状态', '', '本文件是便于交接的摘要；workflow/state.json 为权威状态。', '',
           f'- 项目 {s["project_id"]}',f'- 修订 {s["revision"]}',f'- 工作流 {summary["workflow_status"]}',
           f'- 完整页数 {summary["pages_ready"]}/{summary["pages_total"]}',
           f'- 当前任务 {s.get("active_task",{}).get("id") if s.get("active_task") else "无"}', '',
           '接手后从 Skill 的 toolbox.py 执行 status 和 next，不从旧聊天重建状态。',
           '按当前任务 view_strategy 取图。重复领取同一任务无需反复看同图；上下文丢失后补看必要图片。',
           '整页理解布局，原始像素局部用于制作和找错；保存发现与修改范围后可换短对话接续。',
           '等待看图/素材/Office均不是构建失败；不修改状态文件，不批量填通过。']
    try:(root/'HANDOFF.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    except OSError:pass  # State already committed; a missing convenience summary is not lost state.


def page_ready(p):
    return p.get('imported_slide') is not None or (p.get('plan') and all(r['id'] in p['fragments'] for r in p['plan']['regions']))


def brief(s):
    status=s.get('status','awaiting_analysis')
    if s.get('operation'):status='interrupted_operation'
    elif s.get('failure'):status='tool_failed'
    return {'command_status':'completed','workflow_status':status,'project_id':s['project_id'],
            'revision':s['revision'],'pages_total':len(s['pages']),
            'pages_ready':sum(bool(page_ready(p)) for p in s['pages']),
            'active_task':s.get('active_task',{}).get('id') if s.get('active_task') else None,
            'run_id':(s.get('run') or {}).get('id'),'preview_status':((s.get('run') or {}).get('preview') or {}).get('status','not_run'),'office_validation':'recorded' if (s.get('run') or {}).get('render') else 'not_run','failure':s.get('failure'),
            'next_hint':'next returns one bounded task; advance performs deterministic ready steps. Waiting is exit 0.'}


def check_packet(root, s, task):
    if task['base_revision']!=s['revision']:raise WorkflowError('stale_task','Task was issued for an older revision; call next again')
    for row in task['inputs']:
        if sha256(under(root,row['file']))!=row['sha256']:raise WorkflowError('stale_task','Task input changed: '+row['file'])
    if sha256(under(root,task['packet']))!=task['packet_sha256']:raise WorkflowError('packet_changed','Task packet has been altered; do not edit instructions or tokens')
