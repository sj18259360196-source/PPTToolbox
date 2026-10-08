"""Machine-readable retry guidance; never retries or releases a project lock."""
from __future__ import annotations


def describe_result(result, *, dispatched):
    accepted = result.get("accepted_task")
    status = result.get("command_status")
    error = (result.get("error") or {}).get("code")
    unknown = status == "outcome_unknown"
    if accepted:
        if not result.get("submission"):
            result["submission"] = {
                "state": "accepted", "task_id": accepted, "replay_allowed": False}
        outcome = "accepted_next_failed" if result.get("next_error") or status != "completed" else "accepted"
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
