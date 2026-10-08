"""Shared CLI/MCP workflow dispatcher with durable, content-minimal audit events."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .contracts import COMMANDS, validate
from .policy import PolicyDenied, authorize, check_input
from .storage import stamp, digest
from scripts.runtime_env import child_environment
from .project_context import ProjectContext


def snapshot(project):
    path = project/"workflow/state.json"
    try:
        raw = path.read_bytes()
        s = json.loads(raw)
        return {"project_id": s["project_id"], "revision": s["revision"],
                "task_id": (s.get("active_task") or {}).get("id"),
                "task_kind": (s.get("active_task") or {}).get("kind"),
                "workflow_status": "interrupted_operation" if s.get("operation") else s.get("status"),
                "state_sha256": digest(raw), "writer_lock": (project/"workflow/writer.lock").exists()}
    except (OSError, ValueError, KeyError):
        return {"project_id": None, "revision": None, "task_id": None,
                "workflow_status": None, "state_sha256": None, "writer_lock": None}


def code_version(root):
    root = Path(root).resolve()
    head = None
    # Installed packages have no checkout. Avoid launching Git for every call;
    # never let a metadata subprocess inherit the live MCP input pipe.
    if any((folder / ".git").exists() for folder in (root, *root.parents)):
        try:
            result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=5, shell=False)
            head = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    files = {}
    for sub in (root, root/"scripts", root/"toolbox_manager", root/"assets/schemas", root/"toolbox"):
        for path in sub.glob("*"):
            if path.is_file() and path.suffix in {".py", ".ps1", ".psm1", ".json"} and path.name != "MANIFEST.json":
                files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return {"head": head, "code_sha256": digest(json.dumps(files, sort_keys=True)),
            "file_hashes": files, "head_note": None if head else "No Git HEAD available in active package"}


def arguments_summary(arguments):
    # No task token, user text, result content, argv, image data, or reason prose.
    return {"fields": sorted(arguments), "result_fields": sorted(arguments.get("result", {})),
            "task_id": arguments.get("task_id"), "base_revision": arguments.get("base_revision"),
            "operation_id": arguments.get("operation_id"), "trial_id": arguments.get("trial_id"),
            "comparison_id": arguments.get("comparison_id"), "change_count": len(arguments.get("changes", [])),
            "reference_count": len(arguments.get("references", []))}


def registered_context(manager, tid, args, explicit_project=None):
    """Associate the remaining managed CLI with an explicitly authorized project."""
    input_flags = {"--pptx", "-pptx", "--scene", "--operations", "-sizesjson",
                   "--left", "--right", "--left-render", "--right-render",
                   "--reference", "--candidate", "--regions"}
    output_flags = {"--outdir", "-outputdir", "--out"}
    input_paths, output_paths = [], []
    text_fit_options = None
    path_fit_options = None
    if tid in {"ops.text-fit-plan", "ops.text-fit-evaluate",
               "ops.path-office-plan", "ops.path-office-evaluate",
               "ops.text-refine-plan"} and "--help" not in args:
        parser = argparse.ArgumentParser(add_help=False, exit_on_error=False, allow_abbrev=False)
        fields = ("scene", "references", "outdir") if tid.endswith("-plan") else ("plan", "office", "output")
        if tid in {"ops.path-office-plan", "ops.text-refine-plan"}:
            fields = ("scene", "request", "outdir")
        for field in fields:
            parser.add_argument("--" + field, required=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                text_fit_options = vars(parser.parse_args(args))
            except (SystemExit, argparse.ArgumentError):
                raise ValueError("Invalid registered text-fit arguments") from None
        if tid.endswith("-plan"):
            input_paths.extend(text_fit_options[k] for k in fields[:-1])
            output_paths.append(text_fit_options["outdir"])
        else:
            input_paths.extend(str(Path(text_fit_options["plan"])/name)
                               for name in ("plan.json", "source.scene.json", "specimens.pptx"))
            input_paths.append(str(Path(text_fit_options["office"])/"office-render.json"))
            output_paths.append(text_fit_options["output"])
    elif tid == "ops.path-fit" and "--help" not in args:
        parser = argparse.ArgumentParser(add_help=False, exit_on_error=False, allow_abbrev=False)
        for field in ("scene", "request", "outdir"):
            parser.add_argument("--" + field, required=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                path_fit_options = vars(parser.parse_args(args))
            except (SystemExit, argparse.ArgumentError):
                raise ValueError("Invalid registered path-fit arguments") from None
        input_paths.extend(path_fit_options[k] for k in ("scene", "request"))
        output_paths.append(path_fit_options["outdir"])
    elif tid.startswith('assets.') and '--help' not in args:
        if not args or args[0].startswith('-'):raise ValueError('Asset tool requires a source path')
        input_paths.append(args[0])
        if tid!='assets.audit':
            if len(args)<2 or args[1].startswith('-'):raise ValueError('Asset tool requires an output path')
            output_paths.append(args[1])
    elif tid=='pptx.validate' and '--help' not in args:
        if not args:raise ValueError('Scene path is required')
        input_paths.append(args[0])
    elif tid in {"pptx.build", "pptx.inspect", "office.edit-readback"} and "--help" not in args:
        parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
        if tid == "pptx.build":
            parser.add_argument("scene")
            parser.add_argument("output")
            parser.add_argument("--overwrite", action="store_true")
        elif tid == "pptx.inspect":
            parser.add_argument("pptx")
            parser.add_argument("--scene")
            parser.add_argument("--out", required=True)
        else:
            sub = parser.add_subparsers(dest="command", required=True)
            sub.add_parser("describe")
            for command in ("validate", "run"):
                child = sub.add_parser(command)
                child.add_argument("--operations", required=True)
                if command == "run":
                    child.add_argument("--pptx", required=True)
                    child.add_argument("--outdir", required=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                parsed = vars(parser.parse_args(args))
            except (SystemExit, argparse.ArgumentError):
                raise ValueError("Invalid registered build/inspect/edit arguments") from None
        input_paths.extend(parsed[k] for k in ("scene", "pptx", "operations") if parsed.get(k))
        output_paths.extend(parsed[k] for k in ("output", "out", "outdir") if parsed.get(k))
    elif tid == "office.render" and "--help" not in args:
        # PowerShell accepts case-insensitive and colon-attached parameters.
        # Do not accept abbreviations/common parameters with extra side effects.
        i = 0
        while i < len(args):
            flag, sep, inline = args[i].partition(":")
            flag = flag.lower()
            if flag == "-probeonly" and not sep:
                i += 1
                continue
            if flag not in {"-pptx", "-outputdir", "-sizesjson", "-width", "-height"}:
                raise ValueError("Use full documented PowerPoint parameter names")
            if not sep and i + 1 >= len(args):
                raise ValueError("Missing PowerPoint parameter value")
            value = inline if sep else args[i+1]
            if flag in input_flags:
                input_paths.append(value)
            if flag in output_flags:
                output_paths.append(value)
            i += 1 if sep else 2
    else:
        for i, value in enumerate(args):
            flag, sep, inline = value.partition("=")
            path = inline if sep else args[i+1] if i+1 < len(args) else None
            if path and flag in input_flags:
                input_paths.append(path)
            if path and flag in output_flags:
                output_paths.append(path)
    context=ProjectContext(manager,explicit_project) if explicit_project is not None else None
    def absolute(value):
        if Path(value).is_absolute():return Path(value)
        if context is not None:return context.path(value)
        raise PolicyDenied('Relative tool paths require an explicit --project context')
    candidates = [absolute(p).resolve() for p in input_paths]
    known = manager.store.get("project_authorizations", {})
    outputs=[absolute(p).resolve() for p in output_paths]
    projects = [Path(p) for p in known if any(c.is_relative_to(Path(p)) for c in candidates+outputs)]
    project = context.root if context else max(projects, key=lambda p: len(str(p))) if projects else None
    if tid in {"office.render", "office.edit-readback", "pptx.build", "pptx.inspect"} and "--help" not in args:
        # Legacy non-project tools remain CLI-only, with their original contract.
        # Actual Office and build actions require the same explicit project grant.
        if tid == "office.edit-readback" and args[:1] in (["describe"], ["validate"]):
            return None
        if project is None:
            raise PolicyDenied("No authorized project matches the managed Office/build input")
    project_tool=tid.startswith(('assets.','pptx.','compare.','delivery.','legacy.','office.','preview.','regions.','ops.')) and tid not in {'ops.fonts','ops.components','ops.describe'}
    if project_tool and project is None and '--help' not in args:
        raise PolicyDenied('Project tool requires --project <absolute path> before its arguments')
    if project is not None:
        project, roots = authorize(manager, project)
        context=ProjectContext(manager,project)
        from .policy import plain_path
        for path in input_paths:
            check_input(absolute(path), project, roots)
        for path in output_paths:
            output = plain_path(absolute(path))
            if not output.is_relative_to(project):
                raise PolicyDenied("Output must stay inside the authorized project")
            protected_assets=output.is_relative_to(project/'assets') and (output.exists() or tid in {'office.render','office.edit-readback','pptx.build','pptx.inspect'})
            if output in candidates or output == project or output.is_relative_to(project/"input") or protected_assets:
                raise PolicyDenied("Immutable inputs are not output targets")
        if text_fit_options:
            # Manifests carry indirect reads; validate them before spawning the tool.
            if tid.endswith("-plan"):
                if tid in {"ops.path-office-plan", "ops.text-refine-plan"}:
                    request = json.loads(absolute(text_fit_options["request"]).read_text(encoding="utf-8-sig"))
                    if (not isinstance(request, dict) or not isinstance(request.get("targets"), list)
                            or not 1 <= len(request["targets"]) <= 16
                            or any(not isinstance(row, dict) for row in request["targets"])):
                        raise ValueError("Invalid path-office input manifest")
                    indirect = [row.get("reference") for row in request["targets"]]
                else:
                    references = json.loads(absolute(text_fit_options["references"]).read_text(encoding="utf-8-sig"))
                    if not isinstance(references, dict):
                        raise ValueError("Text-fit reference map must be an object")
                    indirect = list(references.values())
            else:
                plan = json.loads((absolute(text_fit_options["plan"])/"plan.json").read_text(encoding="utf-8-sig"))
                receipt = json.loads((absolute(text_fit_options["office"])/"office-render.json").read_text(encoding="utf-8-sig"))
                if (not isinstance(plan, dict) or not isinstance(plan.get("references"), dict)
                        or not isinstance(receipt, dict) or not isinstance(receipt.get("slides"), list)
                        or any(not isinstance(r, dict) for r in plan["references"].values())
                        or any(not isinstance(r, dict) or not isinstance(r.get("file"), str)
                               for r in receipt["slides"])):
                    raise ValueError("Invalid text-fit plan or Office input manifest")
                indirect = [plan.get("source_path")]
                indirect.extend(row.get("path") for row in plan["references"].values())
                indirect.extend(str(Path(text_fit_options["office"])/row["file"])
                                for row in receipt["slides"])
            if any(not isinstance(path, str) or not path for path in indirect):
                raise ValueError("Text-fit referenced paths must be nonempty strings")
            for path in indirect:
                check_input(absolute(path), project, roots)
        if path_fit_options:
            request = json.loads(absolute(path_fit_options["request"]).read_text(encoding="utf-8-sig"))
            if (not isinstance(request, dict) or not isinstance(request.get("targets"), list)
                    or not 1 <= len(request["targets"]) <= 16
                    or any(not isinstance(row, dict) or not isinstance(row.get("reference"), str)
                           or not row["reference"] for row in request["targets"])):
                raise ValueError("Invalid path-fit input manifest")
            for row in request["targets"]:
                check_input(absolute(row["reference"]), project, roots)
    return project


def cli_arguments(manager, command, args):
    if not isinstance(args, list) or len(args) > 200 or any(
            not isinstance(a, str) or "\0" in a or len(a) > 8000 for a in args):
        raise ValueError("Invalid workflow CLI arguments")
    if command == "start":
        # This parser runs before permission(); never import selected package code.
        parser = argparse.ArgumentParser(add_help=False, exit_on_error=False, allow_abbrev=False)
        parser.add_argument("--project", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--references", nargs="+")
        group.add_argument("--scene")
        parser.add_argument("--candidate")
        parser.add_argument("--ratio")
        parser.add_argument("--mapping", choices=["uniform", "explicit_stretch"], default="uniform")
        parser.add_argument("--office", action="store_true")
        parser.add_argument("--in-place", action="store_true")
        parser.add_argument("--builder", choices=["python", "external"], default="python")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return {k: v for k, v in vars(parser.parse_args(args)).items() if v is not None}
            except (SystemExit, argparse.ArgumentError):
                raise ValueError("Invalid workflow CLI arguments") from None
    from .contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
    if command in (*LOCAL_COMMANDS, *REQUEST_COMMANDS):
        parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
        parser.add_argument("--project", required=True)
        parser.add_argument("--request", required=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                options = parser.parse_args(args)
            except (SystemExit, argparse.ArgumentError):
                raise ValueError("Local workflow CLI requires --project and --request") from None
        project, roots = authorize(manager, options.project)
        payload = json.loads(check_input(options.request, project, roots).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or "project" in payload:
            raise ValueError("Request JSON omits project; supplied by managed CLI")
        return {"project": str(project), **payload}
    root = Path(manager.package()["path"])
    spec = importlib.util.spec_from_file_location("_managed_toolbox_parser", root/"toolbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # argparse must never print onto an MCP protocol stream.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            a = vars(module.parser().parse_args([command, *args]))
        except SystemExit:
            raise ValueError("Invalid workflow CLI arguments") from None
    a.pop("command")
    a = {k: str(v) if isinstance(v, Path) else [str(p) for p in v] if isinstance(v, list) else v
         for k, v in a.items() if v is not None}
    if command == "submit":
        project, roots = authorize(manager, a["project"])
        response = check_input(a.pop("response"), project, roots)
        payload = json.loads(response.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or set(payload) != {"task_id", "token", "result"}:
            raise ValueError("Response requires task_id, token and result only")
        a.update(payload)
    return a


def permission(manager, tid):
    p = manager.package()
    s = manager.settings()
    r = manager.tool(tid)
    if not s["agent_execution_enabled"]:
        raise PolicyDenied("Managed execution is disabled; only the owner may enable it")
    if not p["trusted"] or not p["enabled"] or not r["enabled"]:
        raise PolicyDenied("Package/tool is disabled or package is untrusted")
    return p, s, r


def enrich_task(manager, result, project, response_detail='full'):
    from .material_policy import effective
    result['material_policy'] = effective(manager, project)
    task = result.get("task")
    if not task:
        return result
    packet = json.loads(Path(task["packet"]).read_text(encoding="utf-8"))
    template = json.loads(Path(task["response_template"]).read_text(encoding="utf-8"))
    task.update(task_id=packet["task_id"], token=packet["token"], base_revision=packet["base_revision"],
                input_files=packet["input_files"], context=packet["context"], response=template)
    result["submit_tool"] = "rebuild_submit"
    result["validation_tool"] = "rebuild_validate_response"
    result["next_tool"] = "rebuild_next"
    for key in ("submit_argv", "next_argv", "preview_alternative_argv"):
        if key in result:
            tool = {"submit_argv": "workflow.submit", "next_argv": "workflow.next",
                    "preview_alternative_argv": "workflow.preview"}[key]
            old = result[key]
            result[key] = manager.tool(tool)["managed_argv_prefix"] + old[3:]
    for command in result.get("tool_commands", []):
        old = command["argv"]
        command["argv"] = manager.tool(command["tool_id"])["managed_argv_prefix"] + old[6:]
    task["related_tools"] = [manager.tool(t) for t in task["suggested_tools"]
                             if t in {r["id"] for r in manager.catalog()}]
    if response_detail == 'compact':
        task['response_detail']='compact'
        task['required_read_files']=[{'file':str(path), 'sha256':digest(path.read_bytes())}
            for path in (Path(task['packet']),Path(task['response_template']))]
        task['context_summary']={k:v for k,v in task['context'].items() if k in {
            'region','local_size','coordinate_contract','native_first','required_edit_actions',
            'submission_constraints','asset_policy_revision'}}
        task['related_tools']=[{k:v for k,v in row.items() if k in {'id','title','manuals'}} for row in task['related_tools']]
        task.pop('context',None);task.pop('response',None)
        task['read_instruction']='Read the hashed packet and response template before authoring. Full task constraints and source evidence remain in those files.'
    return result


def process_alive(pid):
    if not pid:
        return None
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None if kernel.GetLastError() == 5 else False
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                return None
            return code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def inspect_pending(manager, project, exclude=None):
    rows = manager.store.unfinished_calls(str(project))
    pending = []
    for row in rows:
        if row["call_id"] == exclude:
            continue
        alive = process_alive(row.get("worker_pid") or row.get("owner_pid"))
        observed = snapshot(project)
        item = {"call_id": row["call_id"], "process_alive": alive, "observed": observed,
                "command_status": "outcome_unknown", "output_directory": row["output_directory"],
                "reason": "Inspect actual workflow and task-owned Office output before any explicit recovery"}
        pending.append(item)
        manager.store.event("tool.unresolved", "Interrupted managed call observed", status="waiting",
                            source="recovery", details=item)
        # A later clean status observation closes the audit pairing, not the old
        # operation as a success. Retry/unlock still require explicit CLI actions.
        if alive is False and not observed["writer_lock"] and observed["workflow_status"] != "interrupted_operation":
            manager.store.event("tool.reconciled", "Observed state; original outcome remains unconfirmed",
                                status="waiting", source="recovery", details=item)
    return pending


def execute(manager, command, arguments, source="cli", rpc_id=None, timeout=None):
    import time
    began=time.perf_counter(); timings={}
    call_id = uuid.uuid4().hex
    tid = "workflow." + command
    project = None
    before = {}
    request = None
    result = None
    record = {"call_id": call_id, "tool_id": tid, "source": source,
              "rpc_request_id": rpc_id, "started_at": stamp(), "ended_at": None,
              "owner_pid": os.getpid(), "worker_pid": None,
              "project": None, "project_id": None, "task_id": None, "revision_before": None,
              "revision_after": None, "workflow_status": None, "command_status": "started",
              "parameters": {}, "code": None, "output_directory": None,
              "null_note": "Unavailable before authorization/start; no identity or result is fabricated"}
    manager.store.event("tool.started", "Managed workflow call started", source=source, details=record)
    try:
        if command == "start":
            from .requests import record_start, next_action
            root = Path(manager.package()["path"])
            if source == "cli":
                arguments = cli_arguments(manager, command, arguments)
            validate(command, arguments, root)
            request = record_start(manager, arguments)
            record.update(project=request["path"], request_id=request["id"],
                          parameters=arguments_summary(arguments))
            manager.store.event("project.requested", "Validated proposed project paths", source=source, details=record)
            if request.get("archived"):
                raise PolicyDenied("项目申请已归档，需要用户在项目列表恢复后再启动")
            if request["status"] == "rejected":
                raise PolicyDenied(request["reason"])
        p, settings, tool = permission(manager, tid)
        if request and request["status"] == "awaiting_authorization":
            raise PolicyDenied("Project not authorized for the proposed input roots; owner review is required")
        root = Path(p["path"])
        if source == "cli" and command != "start":
            arguments = cli_arguments(manager, command, arguments)
        if command in COMMANDS:
            validate(command, arguments, root)
        mark=time.perf_counter()
        project, inputs = authorize(manager, arguments["project"])
        timings['authorize_seconds']=time.perf_counter()-mark
        context=ProjectContext(manager,project)
        arguments={**arguments,'project':str(context.root)}
        checkpoint_payload = arguments.pop('checkpoint', None)
        if checkpoint_payload is not None:
            from .project_hub import checkpoint
            checkpoint(manager, {**checkpoint_payload, 'project':str(project)})
        if command in {'submit','validate_response'} and arguments.get('result',{}).get('action') in {'request_asset','request_assets'}:
            from .material_policy import effective
            if not effective(manager,project)['values']['host_generation_allowed']:
                raise PolicyDenied('Host generation is disabled by the current material policy')
        before = snapshot(project)
        output_dir = context.path('logs/tool-calls/'+call_id) if command!='start' else manager.data/'cache'/'starting-projects'/call_id
        output_dir.mkdir(parents=True, exist_ok=False)
        mark=time.perf_counter()
        version = code_version(root)
        timings['code_identity_seconds']=time.perf_counter()-mark
        (output_dir/"code-version.json").write_text(json.dumps(version, indent=2), encoding="utf-8")
        record.update(project=str(project), project_id=before["project_id"],
                      task_id=arguments.get("task_id") or before["task_id"],
                      task_kind=before.get('task_kind'),
                      revision_before=before["revision"], parameters=arguments_summary(arguments),
                      code={k: v for k, v in version.items() if k != "file_hashes"},
                      output_directory=str(output_dir))
        manager.store.event("tool.authorized", "Managed paths and capabilities checked", source=source, details=record)
        mark=time.perf_counter()
        pending = inspect_pending(manager, project, exclude=call_id)
        timings['pending_check_seconds']=time.perf_counter()-mark
        explicit_unlock = command == "unlock" and all(x["process_alive"] is False for x in pending)
        if pending and command != "status" and not explicit_unlock:
            result = {"command_status": "outcome_unknown", "workflow_status": before["workflow_status"],
                      "pending_calls": pending, "returncode": 3}
        else:
            env = child_environment(settings["powershell_path"])
            env["PPT_MANAGED_CALL_ID"] = call_id
            env["PPT_MANAGED_OFFICE_LOCK"] = str(manager.data/"office-writer.lock")
            env["PPT_USAGE_ROOT"] = str(manager.data / "usage")
            env["PPT_USAGE_PROJECT"] = str(project)
            env["PPT_USAGE_TASK"] = str(before.get("task_id") or "")
            env["PPT_EXPERIENCE_ROOT"] = str(manager.data / "experience-library")
            env["PPT_MANAGED_LEARNING_ROOT"] = str(manager.data/"learning")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            envelope = {"format": "ppt-managed-call/1", "call_id": call_id, "parent_pid": os.getpid(),
                        "package_root": str(root), "project": str(project),
                        "input_roots": [str(r) for r in inputs],
                        "allowed": [r["id"] for r in manager.catalog() if r["enabled"]],
                        "command": command, "arguments": arguments}
            argv = [settings["python_path"] or sys.executable, str(manager.root/"toolbox_manager/worker.py")]
            with (output_dir/"stdout.json").open("w", encoding="utf-8") as out, (output_dir/"stderr.log").open("w", encoding="utf-8") as err:
                mark=time.perf_counter()
                child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                         text=True, encoding="utf-8", shell=False, env=env, cwd=root)
                record["worker_pid"] = child.pid
                manager.store.event("tool.launched", "Managed worker launched", source=source, details=record)
                try:
                    child.communicate(json.dumps(envelope, ensure_ascii=False, allow_nan=False),
                                      timeout=timeout if timeout is not None else min(tool.get("timeout_seconds", 300), 900))
                except subprocess.TimeoutExpired:
                    # Deliberately do not kill the worker or PowerPoint. Durable
                    # audit plus workflow lock blocks blind replay across restarts.
                    result = {"command_status": "outcome_unknown", "workflow_status": snapshot(project)["workflow_status"],
                              "returncode": 3, "reason": "Worker timeout; inspect status before retry", "worker_pid": child.pid}
                    manager.store.event("tool.timeout", "Worker remains owned; no automatic retry or process kill",
                                        source=source, status="waiting", details={**record, **result})
                    from .recovery import describe_result
                    return describe_result({**result, "call_id": call_id, "tool_id": tid,
                        "output_directory": str(output_dir)}, dispatched=True)
            timings['worker_seconds']=time.perf_counter()-mark
            raw = (output_dir/"stdout.json").read_text(encoding="utf-8")
            try:
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
            except ValueError:
                result = {"command_status": "outcome_unknown", "workflow_status": snapshot(project)["workflow_status"],
                          "error": {"code": "worker_protocol_error", "message": "See controlled stderr/output; no payload copied into audit"}}
            result["returncode"] = child.returncode
            if result.get("workflow_status") is None:
                result["workflow_status"] = snapshot(project)["workflow_status"]
            if result.get("workflow_status") == "tool_failed" and result.get("command_status") == "completed":
                result["command_status"] = "failed"
            if (result.get("failure") or {}).get("code") == "office_timeout":
                result["command_status"] = "outcome_unknown"
            if result.get("command_status") == "completed":
                try:
                    if arguments.get('response_detail')=='compact':
                        result = enrich_task(manager, result, project, 'compact')
                    else:
                        result = enrich_task(manager, result, project)
                except Exception as exc:
                    result["task_display_warning"] = str(exc)[:1200]
                    result["next_error"] = {"code":"task_display_failed",
                                            "message":"Read current status; do not replay the completed call."}
            if pending:
                result["pending_calls"] = pending
        after = snapshot(project)
        if command=='start' and after.get('project_id'):
            # A new project's start cannot create its log folder before initialization.
            # The worker has exited; move only this call's closed files into the project.
            import shutil
            target=context.path('logs/tool-calls/'+call_id)
            try:
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():raise ValueError('Call log destination already exists')
                shutil.move(str(output_dir),str(target))
                output_dir=target
                record['output_directory']=str(target)
            except (OSError,ValueError) as exc:
                result['log_warning']='Project initialized; start log remains in toolbox cache: '+str(exc)
        from .recovery import describe_result
        describe_result(result, dispatched=record["worker_pid"] is not None)
        from .project_status import safe_message
        record.update(revision_after=after["revision"], workflow_status=result.get("workflow_status"),
                      project_id=after["project_id"], task_id=record["task_id"] or after["task_id"],
                      command_status=result["command_status"], ended_at=stamp(),
                      state_sha256=after["state_sha256"], returncode=result["returncode"],
                      error_code=(result.get("error") or {}).get("code"),
                      error_message=safe_message(
                          (result.get('next_error') or result.get('error') or result.get('failure') or {}).get('message','')),
                      reason_code=(result.get("failure") or {}).get("code") or result.get("workflow_status"),
                      recovery=result["recovery"])
        if command=='skill_apply' and result.get('application_id'):
            record['usage_application_id']=result['application_id']
        timings['through_worker_seconds']=time.perf_counter()-began
        record['timings']=timings
        result['timings']=timings
        manager.store.event("tool.finished", "Managed workflow call ended", source=source,
                            status="ok" if result["command_status"] == "completed" else "error", details=record)
        (output_dir/'call.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        if result["command_status"] == "completed" and after.get("project_id"):
            result['project_context']=context.snapshot()
            if request:
                from .requests import started
                try:
                    result["authorization_request"] = started(manager, request["id"], after["project_id"])
                except Exception as exc:
                    # Completion already happened; metadata failures cannot invite replay.
                    result["authorization_request"] = request
                    result["authorization_request_warning"] = str(exc)
            try:
                from .projects import register
                result["workbench_project"] = register(manager, project, call_id, source)
                from scripts import project_journal
                if command == 'start':
                    project_journal.ensure(project, after['project_id'], project.name,
                        required=manager.settings()['major_stage_checkpoints'])
                from .project_hub import stage_context
                result['stage_context'] = stage_context(manager,str(project))
            except Exception as exc:
                # The worker has already completed. A view failure must not invite replay.
                result["workbench_warning"] = str(exc)
                manager.store.event("project.registration_failed", str(exc), source=source,
                                    status="error", details={"call_id": call_id})
            if command == "finish" and after.get("workflow_status") == "delivered" and result.get("workbench_project"):
                result["post_delivery"] = {
                    "tool": "toolbox_retrospective", "project": result["workbench_project"],
                    "next": "Send final PPT first. Wait for user acceptance; then ask artwork retention; then ask learning and good/bad feedback. Never assume consent."}
        # Controlled output may include task tokens; public SQLite events never do.
        result.update(call_id=call_id, tool_id=tid, output_directory=str(output_dir))
        from .recovery import describe_result
        describe_result(result, dispatched=record["worker_pid"] is not None)
        from .learning import record_attempt_safely
        record_attempt_safely(manager, command, arguments, result)
        result["stdout"] = json.dumps({k: v for k, v in result.items() if k not in {"stdout", "stderr"}}, ensure_ascii=False)
        result["stderr"] = (output_dir/"stderr.log").read_text(encoding="utf-8") if (output_dir/"stderr.log").exists() else ""
        return result
    except Exception as exc:
        status = "permission_denied" if isinstance(exc, PolicyDenied) else "invalid_arguments" if isinstance(exc, (ValueError, argparse.ArgumentError)) else "failed"
        if not record.get('project') and isinstance(arguments,dict):
            requested = arguments.get('project')
            rows = manager.store.get('workbench_projects',{})
            registered = next((r for k,r in rows.items() if requested in (k,r.get('path'))), None)
            if registered: record['project'] = registered['path']
        after = snapshot(project) if project else {}
        previous_result = result if isinstance(result, dict) else {}
        result = {"call_id": call_id, "tool_id": tid, "command_status": status,
                "workflow_status": after.get("workflow_status"), "returncode": 2,
                "error": {"code": getattr(exc, "code", status), "message": str(exc)}}
        if previous_result.get("accepted_task"):
            result.update(accepted_task=previous_result["accepted_task"],
                          submission=previous_result.get("submission"),
                          next_error={"code":"post_accept_failure","message":str(exc)[:1200]})
        elif previous_result.get("command_status") == "completed":
            result.update(previous_result, reporting_warning=str(exc)[:1200])
        elif record["worker_pid"] is not None and not previous_result:
            result["command_status"] = "outcome_unknown"
        from .recovery import describe_result
        describe_result(result, dispatched=record["worker_pid"] is not None)
        record.update(command_status=result["command_status"], ended_at=stamp(),
                      revision_after=after.get("revision"), workflow_status=after.get("workflow_status"),
                      error_type=type(exc).__name__, recovery=result["recovery"])
        from .project_status import safe_message
        record.update(error_code=getattr(exc,'code',status), error_message=safe_message(exc))
        try:
            manager.store.event("tool.finished", "Managed workflow call reporting ended", source=source,
                                status="ok" if result["command_status"] == "completed" else "error",
                                details=record)
            if record.get("output_directory"):
                result["output_directory"] = record["output_directory"]
                (Path(record["output_directory"])/"call.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as audit_exc:
            result["audit_warning"] = str(audit_exc)[:1200]
        if request:
            result.update(authorization_request=request, next_action=next_action(request), reason=str(exc))
        from .learning import record_attempt_safely
        record_attempt_safely(manager, command, arguments, result)
        return result
