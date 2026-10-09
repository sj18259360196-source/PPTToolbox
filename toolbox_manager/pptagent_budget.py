"""Persistent, atomic admission control for the toolbox's own API assistant."""
import json
import time

KEY = 'pptagent_budget_v1'
DEFAULTS = {'hourly_request_limit': 60, 'daily_request_limit': 200, 'summary_interval_seconds': 60}


class RateLimited(ValueError):
    def __init__(self, reason, retry_at):
        self.reason, self.retry_at = reason, retry_at
        super().__init__('PPTAgent 调用已限流，本地记录和 PPT 制作继续运行。请查看用量面板中的恢复时间。')


def limits(manager):
    cfg = manager.store.get('pptagent_config', {})
    return {k: cfg.get(k, v) for k, v in DEFAULTS.items()}


def _edit(manager, action):
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM kv WHERE key=?', (KEY,)).fetchone()
        state = json.loads(row[0]) if row else {'attempts': [], 'projects': {}}
        result = action(state)
        db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (KEY, json.dumps(state)))
    return result


def _usage(state, cfg, now):
    # Rolling windows avoid a burst at a calendar boundary; failed attempts count.
    day = sorted(t for t in state.get('attempts', []) if t > now - 86400)
    hour = [t for t in day if t > now - 3600]
    waits = []
    if len(day) >= cfg['daily_request_limit']:
        waits.append(day[-cfg['daily_request_limit']] + 86400)
    if len(hour) >= cfg['hourly_request_limit']:
        waits.append(hour[-cfg['hourly_request_limit']] + 3600)
    return day, {'last_hour': len(hour), 'last_24_hours': len(day), **cfg,
                 'blocked': bool(waits), 'retry_at': max(waits) if waits else None}


def snapshot(manager, project=None, now=None):
    now = time.time() if now is None else now
    state = manager.store.get(KEY, {})
    _, result = _usage(state, limits(manager), now)
    row = state.get('projects', {}).get(project, {}) if project else {}
    until = row.get('attempted_at', 0) + result['summary_interval_seconds']
    result['summary_retry_at'] = until if row and until > now else None
    result['summary_outcome'] = row.get('outcome')
    return result


def reserve_request(manager, now=None):
    now = time.time() if now is None else now
    cfg = limits(manager)
    def admit(state):
        day, view = _usage(state, cfg, now)
        if view['blocked']:
            return view
        state['attempts'] = day + [now]
    rejected = _edit(manager, admit)
    if rejected:
        raise RateLimited('request_budget', rejected['retry_at'])


def summary_gate(manager, project, signature, *, reserve=False, now=None):
    now = time.time() if now is None else now
    cfg = limits(manager)
    def gate(state):
        row = state.get('projects', {}).get(project, {})
        if row.get('signature') == signature:
            return {'allowed': False, 'reason': 'already_attempted', 'retry_at': None}
        _, usage = _usage(state, cfg, now)
        until = row.get('attempted_at', 0) + cfg['summary_interval_seconds'] if row else 0
        retry_at = max(until, usage['retry_at'] or 0)
        if retry_at > now:
            return {'allowed': False, 'reason': 'cooldown_or_budget', 'retry_at': retry_at}
        if reserve:
            state.setdefault('projects', {})[project] = {
                'signature': signature, 'attempted_at': now, 'outcome': 'attempted'}
        return {'allowed': True, 'retry_at': None}
    return _edit(manager, gate) if reserve else gate(manager.store.get(KEY, {}))


def summary_outcome(manager, project, signature, outcome):
    def update(state):
        row = state.get('projects', {}).get(project, {})
        if row.get('signature') == signature:
            row['outcome'] = outcome
            if outcome == 'rate_limited':
                row['signature'] = None  # No network attempt; eligible when the window opens.
    _edit(manager, update)
