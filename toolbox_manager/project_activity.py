"""Attribute icon/graphics calls to explicit projects without granting permission."""
from __future__ import annotations
import os
import subprocess
import uuid

from .project_status import safe_message


def observe_call(manager, tool, args, source, invoke, project_scope=None):
    args = args if isinstance(args,dict) else {}
    scope = args.get('project') or args.get('project_key') or project_scope
    if not scope:
        return invoke()
    from .project_hub import entry
    try:
        root, _, workflow = entry(manager, scope)
    except (ValueError, OSError, KeyError, TypeError):
        # Attribution must not replace the tool's own project validation.
        return invoke()
    task = workflow.get('active_task') or {}
    record = {'project':str(root), 'tool_id':tool, 'call_id':uuid.uuid4().hex,
              'owner_pid':os.getpid(), 'task_id':task.get('id'), 'task_kind':task.get('kind')}

    def event(action, status):
        try:
            manager.store.event('activity.'+action, tool, source=source, status=status, details=record)
        except Exception:
            observer = getattr(manager, 'project_observer', None)
            if observer:
                observer.errors[str(scope)] = '调用记录暂时无法保存，请核对日志与产物。'

    event('started', 'ok')
    try:
        result = invoke()
        status = result.get('command_status','completed') if isinstance(result,dict) else 'completed'
        if isinstance(result,dict) and result.get('failed',0): status='failed'
        if tool=='icons.search' and isinstance(result,dict) and result.get('items')==[]: status='no_results'
        record.update(command_status=status)
        event('finished', 'ok' if status=='completed' else 'error')
        return result
    except Exception as exc:
        from .policy import PolicyDenied
        status = 'permission_denied' if isinstance(exc,PolicyDenied) else 'invalid_arguments' if isinstance(exc,ValueError) else 'failed'
        if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)): status='outcome_unknown'
        record.update(command_status=status, error_code=getattr(exc,'code',status), error_message=safe_message(exc))
        event('finished', 'error')
        raise
