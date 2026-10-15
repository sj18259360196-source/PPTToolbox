"""Machine-readable retry guidance; never retries or releases a project lock."""
from __future__ import annotations


def independent_outcomes(result, *, command, arguments, dispatched, before, after, checkpoint):
    """Report independent observed effects; revision changes do not certify acceptance."""
    if command == 'submit':
        submission = dict(result.get('submission') or {})
        accepted = bool(result.get('accepted_task')) or submission.get('state') == 'accepted'
        unknown = result.get('command_status') == 'outcome_unknown'
        submission.update(state='accepted' if accepted else 'unknown' if unknown else 'not_accepted',
            accepted=True if accepted else None if unknown else False, dispatched=dispatched,
            task_id=submission.get('task_id') or result.get('accepted_task') or arguments.get('task_id'),
            workflow_revision_before=before.get('revision'), workflow_revision_after=after.get('revision'))
        result['submission'] = submission
    result['checkpoint_receipt'] = checkpoint or {'state':'not_requested', 'recorded':False,
        'duplicate':False, 'checkpoint_id':None, 'stage_revision_before':None, 'stage_revision_after':None}
    return result


def describe_result(result, *, dispatched):
    submission = result.get('submission') or {}
    accepted = result.get("accepted_task") or (submission.get('task_id') if submission.get('state') == 'accepted' else None)
    is_accepted = bool(accepted) or submission.get('state') == 'accepted'
    status = result.get("command_status")
    error = (result.get("error") or {}).get("code")
    unknown = status == "outcome_unknown"
    causes = [result.get(name) for name in ('next_error', 'failure', 'error')]
    causes = [c for c in causes if isinstance(c, dict) and c]
    cause = causes[0] if causes else {}
    failed_stage = next((c['stage'] for c in causes if isinstance(c.get('stage'), str) and c['stage']), None)
    from .project_status import safe_message
    result['failure_reason'] = {'code': cause.get('code'), 'stage': failed_stage,
                                'message': safe_message(cause.get('message'))}
    result['failed_stage'] = failed_stage
    result['acceptance_state'] = 'accepted' if is_accepted else 'unknown' if unknown else 'not_accepted'
    if is_accepted:
        if not result.get("submission"):
            result["submission"] = {
                "state": "accepted", "task_id": accepted, "replay_allowed": False}
        result['submission']['replay_allowed'] = False
        outcome = "accepted_next_failed" if result.get("next_error") or result.get('failure') or status != "completed" else "accepted"
        action = "inspect_status" if outcome == "accepted_next_failed" else "continue_returned_task"
        retry = "never_replay_accepted_submission"
    elif unknown:
        outcome, action, retry = "outcome_unknown", "inspect_status", "do_not_replay"
    elif not dispatched:
        outcome, retry = "not_dispatched", "correct_or_wait_then_issue_new_request"
        action = "owner_permission" if status == "permission_denied" else "correct_arguments"
    elif status == "completed":
        outcome, action, retry = "completed", "follow_current_workflow", "do_not_repeat_completed_write"
    else:
        outcome, action, retry = "rejected", "inspect_status", "inspect_before_retry"
        if error == "invalid_submission":
            action, retry = "correct_current_result", "same_task_only_if_still_current"
        elif error in {"stale_task", "no_active_task", "packet_changed"}:
            action, retry = "refresh_current_task", "do_not_replay_old_task"
        elif error in {"writer_busy", "interrupted_operation"}:
            action, retry = "inspect_writer", "never_unlock_by_age_or_retry_automatically"
    result["recovery"] = {
        "outcome": outcome, "dispatch": "dispatched" if dispatched else "not_dispatched",
        "next_action": action, "retry_policy": retry,
        "status_tool": "rebuild_status",
    }
    result['retry_scope'] = 'inspect_failed_stage' if outcome == 'accepted_next_failed' else action
    checkpoint = result.get('checkpoint_receipt') or {}
    result['recovery']['submission_retry_scope'] = (
        'do_not_resubmit' if is_accepted else 'inspect_status_and_receipt' if unknown else
        'correct_current_task_result' if dispatched else 'correct_or_wait_then_submit')
    result['recovery']['checkpoint_retry_scope'] = (
        'do_not_repeat_recorded_checkpoint' if checkpoint.get('recorded') else
        'correct_checkpoint_then_retry' if checkpoint.get('state') == 'failed' else
        'inspect_checkpoint_receipt' if checkpoint.get('state') == 'unknown' else
        'checkpoint_not_attempted' if checkpoint.get('state') == 'not_attempted' else
        'not_requested')
    blockers = result.get('pending_calls') or []
    result['blocking_call_id'] = blockers[0].get('call_id') if blockers and isinstance(blockers[0], dict) else None
    return result


def connection_diagnostics(manager, binding, *, initialized, client, active_call=None):
    import json
    import os
    import socket
    from .execution import process_alive
    from .project_context import can_read, ProjectContext

    result = {
        "current_connection": "initialized" if initialized else "not_initialized",
        "client": {k: str(client.get(k, ""))[:120] for k in ("name", "version")},
        "bridge_pid": os.environ.get("PPT_TOOLBOX_BRIDGE_PID"),
        "backend_generation": os.environ.get("PPT_TOOLBOX_BACKEND_GENERATION"),
        "execution_enabled": manager.settings()["agent_execution_enabled"],
        "project_binding": "bound" if binding else "not_bound",
        "active_call": active_call["tool"] if active_call else None,
        "pending_calls": [], "writer": {"state":"not_checked"},
        "scope": "This MCP connection only; configuration and other clients are not verified.",
    }
    if not binding:
        result["next_action"] = "bind_project"
        return result
    project = ProjectContext(manager, binding["project_root"]).root
    if not can_read(manager, project):
        result["next_action"] = "owner_project_authorization"
        return result
    for row in manager.store.unfinished_calls(str(project))[:10]:
        result["pending_calls"].append({
            "call_id":row["call_id"],
            "process_alive":process_alive(row.get("worker_pid") or row.get("owner_pid")),
            "outcome":"unknown", "next_action":"inspect_status_and_receipt_do_not_replay"})
    lock = project / "workflow/writer.lock"
    try:
        raw = json.loads(lock.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or type(raw.get("pid")) is not int or raw["pid"] <= 0:
            raise ValueError("Invalid writer lock identity")
        alive = process_alive(raw.get("pid")) if raw.get("host") == socket.gethostname() else None
        result["writer"] = {
            "state":"running" if alive is True else "orphaned" if alive is False else "unverified",
            "pid":raw.get("pid"), "process_alive":alive,
            "next_action":"wait" if alive is True else "inspect_receipts_before_explicit_unlock"}
    except FileNotFoundError:
        result["writer"] = {"state":"clear"}
    except (OSError, ValueError, TypeError):
        result["writer"] = {"state":"unverified","next_action":"inspect_lock_file"}
    result["next_action"] = ("inspect_status_and_receipt_do_not_replay" if result["pending_calls"]
                             else result["writer"].get("next_action","continue_current_task"))
    return result
