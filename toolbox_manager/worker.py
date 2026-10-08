"""Private stdin worker for an already-authorized managed workflow invocation."""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from toolbox_manager.policy import Policy, PolicyDenied, check_tree
from toolbox_manager.contracts import COMMANDS, validate, validate_result


def execute(envelope):
    policy = Policy(envelope)
    root = Path(envelope["package_root"]).resolve()
    # Imported older packages cannot silently fall back to unguarded functions.
    if not (root/"scripts/workflow.py").is_file():
        raise PolicyDenied("Workflow package unavailable")
    sys.path.insert(0, str(root/"scripts"))
    import workflow as wf
    if getattr(wf, "MANAGED_POLICY_VERSION", None) != 1:
        raise PolicyDenied("Active package does not support internal capability enforcement")
    from evidence_session import validation_scope
    with validation_scope() as session:
        try:
            result = dispatch(envelope, policy, root, wf)
        except Exception as exc:
            exc.validation_metrics = session.report()
            raise
        result["validation_metrics"] = session.report()
        return result


def dispatch(envelope, policy, root, wf):
    command = envelope["command"]
    a = envelope["arguments"]
    if command in COMMANDS:
        validate(command, a, root)
    elif command not in {"advance", "handoff", "preview", "review-again", "retry", "replace-candidate", "replace-scene", "asset-add", "unlock"}:
        raise PolicyDenied("Unsupported managed command")
    policy.require("workflow." + command)
    check_tree(policy.project)
    wf.set_managed_policy(policy)
    p = policy.project
    from toolbox_manager.contracts import LOCAL_COMMANDS, CALIBRATION_COMMANDS, SKILL_COMMANDS, ROUTE_COMMANDS
    if command in ROUTE_COMMANDS:
        from skill_routing import route_check, report
        return (route_check if command == "route_check" else report)(p, a, policy)
    if command in SKILL_COMMANDS:
        original_args = a
        if command == "skill_apply" and a.get("route_id"):
            from skill_routing import enforce_apply
            enforce_apply(p, a, policy)
            a = {k: v for k, v in a.items() if k != "route_id"}
        from skill_library import execute_skill
        result = execute_skill(command, p, a, policy)
        if command == "skill_apply" and original_args.get("route_id"):
            from skill_routing import bind_application
            bind_application(p, original_args, result)
        return result
    if command in CALIBRATION_COMMANDS:
        from calibration import execute_calibration
        return execute_calibration(command, p, a, policy)
    if command in LOCAL_COMMANDS:
        if command == "adopt":
            from skill_routing import enforce_adopt
            enforce_adopt(p, a, policy)
        from local_workflow import execute_local
        return execute_local(command, p, a, policy)
    if command == "start":
        refs = [policy.input(v) for v in a.get("references", [])]
        scene = policy.input(a["scene"]) if a.get("scene") else None
        if scene:
            check_tree(scene.parent)
        candidate = policy.input(a["candidate"]) if a.get("candidate") else None
        return wf.start(p, refs, scene, candidate, a.get("ratio"), a.get("mapping", "uniform"),
                        a.get("office", False), a.get("builder", "python"), a.get('in_place',False))
    if command == "submit":
        # Task-specific validation and path resolution run once under the writer lock.
        return wf.submit(p, {k: a[k] for k in ("task_id", "token", "result")},
                         expected_revision=a.get("base_revision"), return_next=a.get('return_next', False))
    if command == "validate_response":
        return wf.validate_response(p, {k: a[k] for k in ("task_id", "token", "result")},
                                    expected_revision=a.get("base_revision"))
    if command == "revision_candidate":
        return wf.revision_candidate(p, a)
    if command == "revise":
        return wf.revise(p, a["slide"], a.get("region"), a["reason"])
    if command == "advance":
        return wf.advance(p, a.get("office"))
    if command == "handoff":
        return {**wf.status(p), "handoff_file": str(p/"HANDOFF.md")}
    if command == "preview":
        if a.get("executable"):
            raise PolicyDenied("Custom executable is not accepted by managed preview")
        receipt = policy.input(a["receipt"]) if a.get("receipt") else None
        return wf.preview(p, receipt=receipt, timeout=a.get("timeout", 180))
    if command == "review-again":
        return wf.review_again(p, a["task"], a["reason"])
    if command == "retry":
        return wf.retry(p, a["reason"])
    if command == "replace-candidate":
        return wf.replace_candidate(p, policy.input(a["pptx"]), a["reason"])
    if command == "replace-scene":
        scene = policy.input(a["scene"]); check_tree(scene.parent)
        return wf.replace_scene(p, scene, a["reason"])
    if command == "asset-add":
        return wf.add_asset(p, policy.input(a["file"]), a["provenance"])
    if command == "unlock":
        from workflow_store import unlock
        return unlock(p, a["token"], a["confirmed_no_active_writer"])
    result = {"next": wf.next_task, "status": wf.status, "finish": wf.complete}[command](p)
    if command == "finish":
        try:
            from skill_library import collect_current
            collect_current(p)
        except Exception:
            result["skill_feedback"] = "pending_retry; primary workflow unchanged"
    return result


def main():
    try:
        raw = sys.stdin.read(1024*1024 + 1)
        if len(raw) > 1024*1024:
            raise ValueError("Managed request too large")
        envelope = json.loads(raw)
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(envelope)
        code = 1 if result.get("workflow_status") == "tool_failed" else 0
    except Exception as exc:
        result = {"command_status": "permission_denied" if isinstance(exc, PolicyDenied) else "invalid_arguments" if isinstance(exc, ValueError) else "failed",
                  "workflow_status": None,
                  "error": {"code": getattr(exc, "code", "invalid_operation"),
                            "message": str(exc), "hint": getattr(exc, "hint", "")}}
        if hasattr(exc, "validation_metrics"):
            result["validation_metrics"] = exc.validation_metrics
        if hasattr(exc, 'diagnostics'):
            result['error']['diagnostics']=exc.diagnostics
        code = 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
