"""Portable project records and explicit major-stage declarations.

Immutable event files are authoritative; state.json and the managed Markdown
section are projections. No model output can create a checkpoint.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import time
import uuid

STAGES = [('intake', '接单与确认'), ('plan', '确定方案'), ('production', '制作 PPT'),
          ('revision', '整理与修订'), ('delivery', '交付')]
BEGIN = '<!-- ppttool:managed:start -->'
END = '<!-- ppttool:managed:end -->'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def safe(root, relative):
    root = Path(root).absolute()
    path = root / relative
    if not path.absolute().is_relative_to(root) or '..' in path.parts:
        raise ValueError('记录路径超出项目目录')
    for item in [root, *root.parents, path, *path.parents]:
        if item.is_symlink() or (item.exists() and getattr(item.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('项目记录不跟随目录链接')
    if path.is_file() and path.stat().st_nlink > 1:
        raise ValueError('项目记录不能使用硬链接')
    return path


def read_json(path, default=None):
    return json.loads(path.read_text('utf-8-sig')) if path.is_file() else copy.deepcopy(default)


def atomic(path, value):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            f.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def locked(root):
    directory = safe(root, '.ppttool')
    directory.mkdir(exist_ok=True)
    path = safe(root, '.ppttool/record.lock')
    with path.open('a+b') as f:
        if not path.stat().st_size:
            f.write(b'0'); f.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                f.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError('项目记录正在更新，请使用同一打卡编号重试')
                time.sleep(.03)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def load(root):
    state = read_json(safe(root, '.ppttool/state.json'), {})
    events = safe(root, '.ppttool/events')
    for file in sorted(events.glob('*.json')) if events.is_dir() else []:
        # Fixed-width sequences permit skipping old records without reading them.
        seq = int(file.name.split('-', 1)[0])
        if seq <= state.get('sequence', 0):
            continue
        event = read_json(safe(root, file.relative_to(root)), {})
        if seq != state.get('sequence', 0) + 1:
            raise ValueError('项目记录存在缺失序号，请保留文件并核对')
        state.update(event['changes'])
        state['sequence'] = seq
    return state


def manifest(root):
    path = safe(root, 'ppttool.md')
    if not path.is_file():
        return None
    if path.stat().st_size > 2_000_000:
        raise ValueError('ppttool.md 超过读取上限')
    raw = path.read_text('utf-8-sig')
    match = re.search(r'<!-- ppttool:identity (\{[^\n]+\}) -->', raw)
    if not match:
        raise ValueError('已有 ppttool.md 未包含工具箱身份，原文件已保留')
    identity = json.loads(match[1])
    if identity.get('format') != 'ppttool-project/1' or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', identity.get('project_id', '')):
        raise ValueError('ppttool.md 项目身份无效')
    return identity


def markdown(root, state):
    path = safe(root, 'ppttool.md')
    original = path.read_text('utf-8-sig') if path.exists() else ''
    if original and (original.count(BEGIN) != 1 or original.count(END) != 1):
        raise ValueError('ppttool.md 自动记录区标记有变动，原文已保留')
    identity = {'format': 'ppttool-project/1', 'project_id': state['project_id']}
    phase = state.get('phase', {})
    title = dict(STAGES).get(phase.get('stage'), '尚未打卡')
    block = '\n'.join([BEGIN, '<!-- ppttool:identity ' + json.dumps(identity) + ' -->',
        '## 软件记录', '', f"项目名称 {state['label']}", f"更新于 {state['updated_at']}",
        f"当前阶段 {title} · {phase.get('status', '待开始')}",
        f"下一步 {phase.get('next_action') or '等待制作 Agent 登记'}",
        f"最近结果 {phase.get('result_summary') or '尚无阶段结果'}",
        f"当前阻碍 {phase.get('blocker') or '未记录'}", '', END])
    text = (original[:original.index(BEGIN)] + block + original[original.index(END)+len(END):]
            if original else '# 项目记录\n\n' + block + '\n\n## 项目说明\n\n在这里记录需求与备注，软件更新时保留本区内容。\n')
    if original and text != original:
        # A human edit arriving while the projection was prepared is never replaced.
        if path.read_text('utf-8-sig') != original:
            raise ValueError('项目说明同时被修改，下次同步会重新合并')
    if text != original:
        atomic(path, text)


def _commit(root, old, changes, event_type, source, detail, event_id=None):
    sequence = old.get('sequence', 0) + 1
    changes = {**changes, 'updated_at': now()}
    if 'work_graph' in changes:
        changes['graph_revision'] = old.get('graph_revision', 0) + 1
        if not detail.get('history_id'):
            history_id=f"{changes['graph_revision']:010d}-{uuid.uuid4().hex[:16]}"
            folder=safe(root,'.ppttool/graph-history');folder.mkdir(exist_ok=True)
            atomic(safe(root,'.ppttool/graph-history/'+history_id+'.json'),
                   {'id':history_id,'at':changes['updated_at'],'before':old.get('work_graph',{}),
                    'after':changes['work_graph'],'summary':event_type,'warnings':[]})
            detail={**detail,'history_id':history_id}
    event = {'id': event_id or uuid.uuid4().hex, 'sequence': sequence, 'at': changes['updated_at'],
             'type': event_type, 'source': source, 'detail': detail, 'changes': changes}
    folder = safe(root, '.ppttool/events'); folder.mkdir(exist_ok=True)
    atomic(safe(root, f'.ppttool/events/{sequence:010d}-{uuid.uuid4().hex}.json'), event)
    state = {**old, **changes, 'sequence': sequence, 'manifest_warning': None}
    atomic(safe(root, '.ppttool/state.json'), state)
    try:
        markdown(root, state)
    except (OSError, ValueError) as exc:
        # Durable checkpoint success must not become a retryable production error.
        state = {**state, 'manifest_warning': str(exc)}
        atomic(safe(root, '.ppttool/state.json'), state)
    return state


def ensure(root, project_id=None, label=None, required=False):
    root = Path(root)
    with locked(root):
        state = load(root)
        if state:
            if project_id and state['project_id'] != project_id:
                raise ValueError('项目记录身份与当前工作流不一致')
            if required and not state.get('checkpoint_required'):
                return _commit(root, state, {'checkpoint_required': True}, 'checkpoint.policy', 'software', {})
            return state
        identity = manifest(root)
        identifier = project_id or (identity or {}).get('project_id') or uuid.uuid4().hex
        if identity and identifier != identity['project_id']:
            raise ValueError('目录中的项目编号存在冲突')
        return _commit(root, {}, {'format': 'ppttool-state/1', 'project_id': identifier,
            'label': label or root.name, 'checkpoint_required': required,
            'run_id': uuid.uuid4().hex, 'phase_revision': 0, 'phase': {},
            'checkpoints': [], 'activity': {}, 'files': [], 'summary': {}},
            'project.created', 'software', {'legacy_workflow': not required})


def update(root, changes, kind='project.observed', source='software', detail=None, expected_sequence=None):
    root = Path(root)
    with locked(root):
        state = load(root)
        if not state:
            raise ValueError('项目记录尚未初始化')
        if expected_sequence is not None and state.get('sequence') != expected_sequence:
            return {'discarded': True, 'reason': 'newer_project_state'}
        if all(state.get(k) == v for k, v in changes.items()):
            if state.get('manifest_warning') or not safe(root,'ppttool.md').exists():
                try:
                    markdown(root,state)
                    state['manifest_warning']=None
                    atomic(safe(root,'.ppttool/state.json'),state)
                except (ValueError,OSError): pass
            return state
        return _commit(root, state, changes, kind, source, detail or {})


def checkpoint(root, body):
    root = Path(root)
    allowed = {'checkpoint_id', 'run_id', 'expected_revision', 'event', 'stage', 'result_summary',
               'artifact_refs', 'next_action', 'blocker', 'used_experiences', 'declared_at', 'flow'}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError('存在未知打卡字段')
    for name in ['checkpoint_id', 'run_id', 'event', 'result_summary']:
        if not isinstance(body.get(name), str) or not body[name].strip() or len(body[name]) > (1500 if name == 'result_summary' else 128):
            raise ValueError('打卡缺少有效字段 ' + name)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', body['checkpoint_id']):
        raise ValueError('打卡编号仅支持字母、数字、下划线和连字符')
    if type(body.get('expected_revision')) is not int:
        raise ValueError('请提供当前阶段版本 expected_revision')
    for name in ['next_action', 'blocker', 'declared_at']:
        if body.get(name) is not None and (not isinstance(body[name], str) or len(body[name]) > 1500):
            raise ValueError('无效打卡字段 ' + name)
    refs = body.get('artifact_refs', [])
    if not isinstance(refs, list) or len(refs) > 30 or any(not isinstance(x, str) or len(x) > 500 for x in refs):
        raise ValueError('artifact_refs 应为最多 30 个项目内相对路径')
    if any(not p or Path(p).is_absolute() for p in refs):
        raise ValueError('artifact_refs 必须使用项目内相对路径')
    artifacts = [{'path': p, 'exists': safe(root, p).is_file()} for p in refs]
    used = body.get('used_experiences', [])
    if not isinstance(used, list) or len(used) > 20 or any(not isinstance(x, str) or not re.fullmatch(r'EXP-\d+', x) for x in used):
        raise ValueError('used_experiences 应为实际采用的经验编号')
    event = body['event']; stage = body.get('stage'); ids = [x[0] for x in STAGES]
    if event not in {'begin', 'transition', 'finish', 'replan', 'blocked', 'pause', 'resume'}:
        raise ValueError('未知打卡事件')
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with locked(root):
        state = load(root)
        previous = next((c for c in state.get('checkpoints', []) if c['checkpoint_id'] == body['checkpoint_id']), None)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise ValueError('同一打卡编号不能提交不同内容')
            return {**previous, 'duplicate': True}
        if body['run_id'] != state.get('run_id') or body['expected_revision'] != state.get('phase_revision'):
            raise ValueError('任务或阶段版本已变化，请先读取项目状态')
        phase = state.get('phase', {}); current = phase.get('stage')
        if event == 'begin' and (current or stage != 'intake'):
            raise ValueError('首次打卡必须从接单与确认开始')
        if event != 'begin' and not current:
            raise ValueError('请先登记接单与确认阶段开始')
        if event == 'transition' and (stage not in ids or ids.index(stage) != ids.index(current) + 1):
            raise ValueError('阶段切换应进入下一大阶段；调整原方案请用 replan')
        if event == 'replan' and stage not in ids:
            raise ValueError('调整方案需要指定有效大阶段')
        if event == 'replan' and ids.index(stage) > ids.index(current):
            raise ValueError('调整方案不能跳过尚未完成的大阶段')
        if phase.get('status') == 'finished' and event != 'replan':
            raise ValueError('本次阶段已经收尾，重新工作请登记 replan')
        if event == 'finish' and (current != 'delivery' or not artifacts):
            raise ValueError('最终收尾需要进入交付阶段并关联交付文件')
        if event in {'begin', 'transition', 'replan', 'resume'} and not body.get('next_action', '').strip():
            raise ValueError('请登记下一步安排 next_action')
        if event == 'blocked' and not body.get('blocker', '').strip():
            raise ValueError('阻塞打卡需要说明 blocker')
        revision = state['phase_revision'] + 1
        record = {**body, 'fingerprint': fingerprint, 'received_at': now(), 'revision': revision,
                  'from_stage': current, 'stage': stage if event in {'begin', 'transition', 'replan'} else current,
                  'artifacts': artifacts, 'used_experiences': used}
        status = {'blocked': 'blocked', 'pause': 'paused', 'finish': 'finished'}.get(event, 'declared_started')
        phase = {'stage': record['stage'], 'status': status, 'result_summary': body['result_summary'],
                 'next_action': body.get('next_action', ''), 'blocker': body.get('blocker'),
                 'artifacts': artifacts, 'artifact_state': 'present' if artifacts and all(a['exists'] for a in artifacts) else 'unconfirmed'}
        changes = {'phase': phase, 'phase_revision': revision, 'checkpoints': state['checkpoints'] + [record]}
        if 'flow' in body:
            if __package__:
                from .project_flow import merge
            else:
                from project_flow import merge
            changes['work_graph'] = merge(state.get('work_graph'), body['flow'], source='agent', at=record['received_at'])
        _commit(root, state, changes, 'checkpoint.' + event, 'agent', record, body['checkpoint_id'])
        return {**record, 'recorded': True, 'tool_execution': 'separate_observation', 'summary': 'queued'}


def update_graph(root, patches, expected_sequence, source='pptagent'):
    if __package__:
        from .project_flow import merge
    else:
        from project_flow import merge
    root = Path(root)
    with locked(root):
        state = load(root)
        if not state or type(expected_sequence) is not int or state.get('sequence') != expected_sequence:
            raise ValueError('项目记录已变化，请重新读取后更新工作图')
        graph = merge(state.get('work_graph'), patches, source=source, at=now())
        return _commit(root, state, {'work_graph': graph}, 'project.work_graph', source,
                       {'updated_nodes': [p['id'] for p in patches]})


def requirement(root, finishing=False):
    state = load(Path(root))
    if not state.get('checkpoint_required'):
        return None
    phase = state.get('phase', {})
    if not phase or phase.get('status') in {'blocked','paused'} or (finishing and phase.get('stage') != 'delivery'):
        return {'required': True, 'tool': 'toolbox_checkpoint', 'run_id': state['run_id'],
                'expected_revision': state['phase_revision'], 'current_stage': phase.get('stage'),
                'stages': [{'id': i, 'label': t} for i, t in STAGES],
                'message': '先登记大阶段开始或切换；阶段内无需定时汇报，交付后登记 finish。'}
    return None


def notes(root):
    path = safe(root, 'ppttool.md')
    raw = path.read_text('utf-8-sig') if path.is_file() else ''
    value = raw.split(END, 1)[1] if END in raw else ''
    return {'text': value.strip(), 'revision': hashlib.sha256(value.encode()).hexdigest()}


def save_notes(root, text, revision):
    if not isinstance(text,str) or len(text)>20000 or BEGIN in text or END in text:
        raise ValueError('项目说明超过限制或包含保留标记')
    with locked(root):
        old=notes(root)
        if old['revision']!=revision:raise ValueError('项目说明已被修改，请重新读取后合并')
        path=safe(root,'ppttool.md');raw=path.read_text('utf-8-sig')
        if raw.count(END)!=1:raise ValueError('项目说明的记录区标记不完整')
        atomic(path,raw.split(END,1)[0]+END+'\n\n'+text.strip()+'\n')
        state=load(root)
        _commit(root,state,{'notes_updated_at':now()},'project.notes','human',{})
        return notes(root)
