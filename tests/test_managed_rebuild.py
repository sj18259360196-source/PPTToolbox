"""Phase-01 tests. Transport fixtures are not host visual/Office acceptance."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/"scripts"))
from toolbox_manager.service import Manager
from toolbox_manager.contracts import schemas, validate
from toolbox_manager.execution import execute, inspect_pending, snapshot
from toolbox_manager.policy import PolicyDenied
from toolbox_manager.mcp import MCP
from common import read_json, write_json, sha256
from workflow_store import locked


@pytest.fixture
def runtime(tmp_path):
    manager = Manager(tmp_path/"manager", root=ROOT, home=tmp_path/"home")
    inputs = tmp_path/"inputs"; inputs.mkdir()
    image = inputs/"中文 reference.png"; Image.new("RGB", (640, 360), "white").save(image)
    project = tmp_path/"中文 project"
    manager.authorize_project(project, [inputs])
    return manager, project, image


def enabled(runtime):
    m, p, image = runtime
    m.save_settings({"revision": m.settings()["revision"], "values": {"agent_execution_enabled": True}})
    return m, p, image


def invoke(m, command, p, **args):
    return m.execute_workflow(command, {"project": str(p), **args})


def begin(runtime, office=False):
    m, p, image = enabled(runtime)
    r = invoke(m, "start", p, references=[str(image)], office=office)
    assert r["command_status"] == "completed", r
    declare(m,p,'plan')
    return m, p, image


def declare(m,p,target):
    """Explicit synthetic stage declarations used by legacy transport fixtures."""
    from scripts import project_journal as journal
    from toolbox_manager.project_hub import checkpoint
    ids=[i for i,_ in journal.STAGES]
    while True:
        state=journal.load(p);current=state['phase'].get('stage')
        if current==target:return
        following=ids[ids.index(current)+1] if current else 'intake'
        checkpoint(m,{'project':str(p),'checkpoint_id':'fixture-stage-'+str(state['phase_revision']),
            'run_id':state['run_id'],'expected_revision':state['phase_revision'],
            'event':'transition' if current else 'begin','stage':following,
            'result_summary':'Synthetic transport fixture setup; no visual acceptance',
            'next_action':'Exercise the next controlled test operation'})


def response(m, p, payload, task=None):
    task = task or invoke(m, "next", p)["task"]
    return invoke(m, "submit", p, task_id=task["task_id"], token=task["token"],
                  base_revision=task["base_revision"], result=payload)


def plan():
    return {"regions": [{"id": "body", "bbox": [0, 0, 640, 360], "role": "content",
                         "summary": "TRANSPORT FIXTURE", "local_review": True}]}


def ready(runtime, office=False):
    m, p, image = begin(runtime, office)
    assert response(m, p, plan())["command_status"] == "completed"
    declare(m,p,'production')
    assert response(m, p, {"objects": [{"id": "label", "kind": "text", "text": "FIXTURE",
                                      "bbox": [10, 10, 260, 40]}],
                            "source_notes": "TRANSPORT FIXTURE ONLY"})["command_status"] == "completed"
    t = invoke(m, "next", p)["task"]
    assert response(m, p, {"status": "passed", "note": "SYNTHETIC ASSERTION; no visual acceptance",
                          "reviewer": "fixture", "viewed_files": t["must_view_files"]}, t)["command_status"] == "completed"
    return m, p, image


@pytest.mark.parametrize("values", [
    {"references": "x"}, {"references": [2]}, {"references": []}, {"references": ["x"], "office": "true"},
    {"references": ["x"], "extra": True}, {"references": ["x"], "scene": "y"},
])
def test_schema_invalid_start(values):
    with pytest.raises(ValueError):
        validate("start", {"project": "p", **values}, ROOT)


@pytest.mark.parametrize("result", [
    {"regions": "bad"},
    {"regions": [{"id": "r", "bbox": [0, 0, True, 10], "role": "content", "summary": "x"}]},
    {"regions": [{"id": "r", "bbox": [0, 0, 10, 10], "role": "content", "summary": "x", "unknown": 4}]},
    {"objects": [{"id": "x", "kind": "text", "text": "x", "bbox": [0, 0, float("nan"), 10]}], "source_notes": "x"},
    {"objects": [], "source_notes": "x", "components": [{"id": "r", "recipe": "segmented_ring", "bbox": [0, 0, 10, 10], "params": {"segments": "4"}}]},
])
def test_schema_invalid_nested(result):
    with pytest.raises(ValueError):
        validate("submit", {"project": "p", "task_id": "t", "token": "s", "result": result}, ROOT)


def test_default_off_and_no_auto_authorization(runtime):
    m, p, image = runtime
    r = invoke(m, "start", p, references=[str(image)])
    assert r["command_status"] == "permission_denied" and not p.exists()
    enabled(runtime)
    assert invoke(m, "start", p.parent/"unapproved", references=[str(image)])["command_status"] == "permission_denied"
    assert m.settings()["agent_execution_enabled"] is True


@pytest.mark.parametrize("kind", ["package", "untrusted", "tool"])
def test_permission_switches(runtime, kind):
    m, p, image = enabled(runtime)
    if kind == "package": m.toggle("package", "", False)
    elif kind == "tool": m.toggle("tool", "workflow.start", False)
    else:
        with m.store.db() as c: c.execute("UPDATE packages SET trusted=0 WHERE id='builtin'")
    assert invoke(m, "start", p, references=[str(image)])["command_status"] == "permission_denied"
    assert not p.exists()


def test_paths_and_source_protection(runtime, tmp_path):
    m, p, image = enabled(runtime)
    before = sha256(image)
    outside = tmp_path/"outside.png"; Image.new("RGB", (20, 20)).save(outside)
    assert invoke(m, "start", p, references=[str(outside)])["command_status"] == "permission_denied"
    assert not p.exists()
    assert invoke(m, "start", p, references=[str(image)])["command_status"] == "completed"
    assert invoke(m, "start", p, references=[str(image)])["command_status"] == "invalid_arguments"
    assert sha256(image) == before
    with pytest.raises(PolicyDenied): m.authorize_project(ROOT/"bad-project", [])


def test_junction_path_escape(runtime, tmp_path):
    m, p, image = begin(runtime)
    outside = tmp_path/"outside"; outside.mkdir()
    link = p/"escaped"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt": pytest.skip("Symlink creation unavailable")
        run = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if run.returncode: pytest.skip("No symlink or junction capability")
    try:
        assert invoke(m, "next", p)["command_status"] == "permission_denied"
        assert not list(outside.iterdir())
    finally:
        if link.is_symlink(): link.unlink()
        else: os.rmdir(link)  # Only this test's exact junction, never its target.


def test_repeated_next_stale_and_duplicate_submit(runtime):
    m, p, _ = begin(runtime)
    first = invoke(m, "next", p)
    second = invoke(m, "next", p)
    assert first["task"] == second["task"] and first["revision"] == second["revision"]
    t = first["task"]
    bad = invoke(m, "submit", p, task_id=t["task_id"], token="stale", result=plan())
    assert bad["error"]["code"] == "stale_task"
    bad = invoke(m, "submit", p, task_id=t["task_id"], token=t["token"], base_revision=0, result=plan())
    assert bad["error"]["code"] == "stale_task"
    assert response(m, p, plan(), t)["command_status"] == "completed"
    repeat = response(m, p, plan(), t)
    assert repeat["error"]["code"] == "no_active_task"
    assert len(read_json(p/"workflow/state.json")["accepted"]) == 1


def test_input_hash_and_packet_hash(runtime):
    m, p, _ = begin(runtime)
    t = invoke(m, "next", p)["task"]
    path = Path(t["must_view_files"][0])
    path.write_bytes(b"changed")
    assert invoke(m, "next", p)["error"]["code"] == "input_changed"


def test_writer_lock_kept(runtime):
    m, p, _ = begin(runtime)
    with locked(p):
        before = (p/"workflow/writer.lock").read_bytes()
        assert invoke(m, "next", p)["error"]["code"] == "writer_busy"
        assert (p/"workflow/writer.lock").read_bytes() == before


@pytest.mark.parametrize("capability", ["pptx.build", "pptx.inspect", "office.render", "compare.deck", "delivery.verify"])
def test_internal_permissions_before_side_effect(runtime, capability):
    m, p, _ = ready(runtime, office=True)
    m.toggle("tool", capability, False)
    if capability in {"compare.deck", "delivery.verify"}:
        # Explicit permission-unit fixture. No synthetic receipts are promoted
        # to Office evidence; exercise the guard at the exact side-effect site.
        import workflow as wf
        from toolbox_manager.policy import Policy
        from unittest.mock import patch
        class Deny:
            allowed = set()
            def require(self, *names):
                if capability in names: raise PolicyDenied("disabled " + capability)
        wf.set_managed_policy(Deny())
        try:
            from workflow_store import load
            # Build once using the normal managed entry with Office switched off.
            s = read_json(p/"workflow/state.json"); s["office_requested"] = False; write_json(p/"workflow/state.json", s)
            invoke(m, "next", p)
            s = load(p); s["active_task"] = None
            s["run"]["render"] = {"file": "unused-fixture"}
            if capability == "delivery.verify": s["run"]["comparison"] = {"file": "unused-fixture"}
            with patch.object(wf, "_review_queue", return_value=[]), patch.object(wf, "compare_deck") as compare, patch.object(wf, "final_gate") as gate:
                with pytest.raises(PolicyDenied): wf._progress(p, s)
                compare.assert_not_called(); gate.assert_not_called()
        finally: wf.set_managed_policy(None)
    else:
        result = invoke(m, "next", p)
        assert result["command_status"] == "permission_denied", result
        state = read_json(p/"workflow/state.json")
        assert not state.get("operation") and not state.get("failure")
        if capability == "office.render":
            assert state["run"]["candidate"]
            assert not list((p/"runs").rglob("*office*"))
        else:
            assert not list((p/"runs").rglob("candidate.pptx"))


def test_assets_crop_disable(runtime):
    m, p, _ = begin(runtime)
    response(m, p, plan())
    m.toggle("tool", "assets.crop", False)
    r = invoke(m, "next", p)
    assert r["command_status"] == "permission_denied"
    assert not list((p/"workflow/tasks").rglob("reference-crop.png"))


def test_legacy_advance_and_finish_obey_office_disable(runtime):
    m, p, _ = ready(runtime, office=True)
    declare(m,p,'delivery')
    m.toggle("tool", "office.render", False)
    for tool in ("workflow.advance", "workflow.finish"):
        result = m.execute(tool, ["--project", str(p)])
        assert result["command_status"] == "permission_denied", result
    assert not list((p/"runs").rglob("*office*"))


def test_nonobject_arguments_and_capability_injection(runtime):
    m, p, _ = enabled(runtime)
    for args in ([], None, "bad", {"project": str(p), "allowed": ["office.render"]}):
        r = m.execute_workflow("next", args)
        assert r["command_status"] == "invalid_arguments"


def test_worker_context_cannot_be_forged_by_tool_arguments(runtime):
    from toolbox_manager.policy import Policy
    with pytest.raises(PolicyDenied):
        Policy({"allowed": ["office.render"]})


def test_unknown_packet_mutation_rejected(runtime):
    m, p, _ = begin(runtime)
    task = invoke(m, "next", p)["task"]
    Path(task["packet"]).write_text("{}", encoding="utf-8")
    assert response(m, p, plan(), task)["error"]["code"] == "packet_changed"


def test_stale_response_after_revise(runtime):
    m, p, _ = begin(runtime)
    task = invoke(m, "next", p)["task"]
    invoke(m, "revise", p, slide="slide-001", reason="Explicit re-analysis")
    assert response(m, p, plan(), task)["error"]["code"] == "no_active_task"


def test_managed_office_output_cannot_escape(runtime, tmp_path):
    m, p, _ = begin(runtime)
    source = p/"source.pptx"; source.write_bytes(b"Not Office content; policy must reject before execution")
    with pytest.raises(PolicyDenied):
        m.execute("office.render", ["-Pptx", str(source), "-OutputDir", str(tmp_path/"escaped-render")])
    assert not (tmp_path/"escaped-render").exists()


def test_registered_positional_build_inspect_paths(runtime, tmp_path):
    from toolbox_manager.execution import registered_context
    m, p, _ = begin(runtime)
    scene = p/"scene.json"; scene.write_text("{}", encoding="utf-8")
    pptx = p/"candidate.pptx"; pptx.write_bytes(b"policy fixture only")
    for tool, args in (
        ("pptx.build", [str(scene), str(p/"rebuilt.pptx")]),
        ("pptx.inspect", [str(pptx), "--out", str(p/"audit.json")]),
        ("pptx.rebuild-diff", ["--left", str(pptx), "--right", str(pptx), "--out", str(p/"diff.json")]),
    ):
        assert registered_context(m, tool, args) == p
    for tool, args in (
        ("pptx.build", [str(scene), str(tmp_path/"escape.pptx")]),
        ("pptx.build", [str(scene), str(scene), "--overwrite"]),
        ("pptx.inspect", [str(pptx), "--out="+str(tmp_path/"escape.json")]),
    ):
        with pytest.raises(PolicyDenied):
            registered_context(m, tool, args)
    with pytest.raises(ValueError):
        registered_context(m, "pptx.build", [str(scene), "--out", str(p/"wrong.pptx")])


def test_registered_office_parameter_variants_do_not_escape(runtime, tmp_path):
    from toolbox_manager.execution import registered_context
    m, p, _ = begin(runtime)
    pptx = p/"source.pptx"; pptx.write_bytes(b"policy fixture only")
    ops = p/"ops.json"; ops.write_text("[]", encoding="utf-8")
    for tool, args in (
        ("office.render", ["-pptx", str(pptx), "-outputdir:"+str(tmp_path/"escape")]),
        ("office.edit-readback", ["run", "--pptx="+str(pptx), "--operations="+str(ops),
                                 "--outdir="+str(tmp_path/"escape")]),
    ):
        with pytest.raises(PolicyDenied):
            registered_context(m, tool, args)
    with pytest.raises(ValueError):
        registered_context(m, "office.render", ["-Pptx", str(pptx), "-O", str(p/"render")])


def test_revise_and_finish_gate(runtime):
    m, p, _ = begin(runtime)
    t = invoke(m, "next", p)["task"]
    response(m, p, plan(), t)
    r = invoke(m, "revise", p, slide="slide-001", region="body", reason="Explicit test region")
    assert r["command_status"] == "completed"
    declare(m,p,'delivery')
    assert invoke(m, "finish", p)["delivery_created"] is False
    assert not list((p/"delivery").iterdir())


def test_log_redaction_and_cli_mcp_parity(runtime):
    m, p, _ = begin(runtime)
    t = invoke(m, "next", p)["task"]
    payload = {"regions": [{"id": "r", "bbox": [0, 0, 640, 360], "role": "content", "summary": "PRIVATE USER PROSE 991"}]}
    response_path = p/"response.json"
    write_json(response_path, {"task_id": t["task_id"], "token": t["token"], "result": payload})
    result = m.execute("workflow.submit", ["--project", str(p), "--response", str(response_path)])
    assert result["command_status"] == "completed"
    cli = m.execute("workflow.status", ["--project", str(p)])
    mcp = invoke(m, "status", p)
    assert cli["workflow_status"] == mcp["workflow_status"] and cli["revision"] == mcp["revision"]
    logs = json.dumps(m.store.logs(limit=1000))
    assert t["token"] not in logs and "PRIVATE USER PROSE 991" not in logs
    finish = next(e for e in m.store.logs() if e["action"] == "tool.finished")
    for key in ("call_id", "source", "tool_id", "project_id", "task_id", "code", "revision_before",
                "revision_after", "started_at", "ended_at", "command_status", "workflow_status", "parameters", "output_directory"):
        assert key in finish["details"]
    assert {e["source"] for e in m.store.logs()} >= {"mcp", "cli"}


def test_timeout_restart_observation_no_replay(runtime):
    m, p, image = enabled(runtime)
    r = execute(m, "start", {"project": str(p), "references": [str(image)]}, source="mcp", timeout=0.001)
    assert r["command_status"] == "outcome_unknown"
    # Wait only for our worker. No rerun of the timed-out start.
    import time
    from toolbox_manager.execution import process_alive
    deadline = time.monotonic() + 20
    while process_alive(r["worker_pid"]) and time.monotonic() < deadline: time.sleep(.1)
    assert not process_alive(r["worker_pid"])
    reopened = Manager(m.data, root=ROOT)
    result = invoke(reopened, "status", p)
    assert result["command_status"] == "completed" and result["pending_calls"]
    assert result["revision"] == 1
    assert invoke(reopened, "next", p)["task"]["task_id"] == "task-000001"
    logs = reopened.store.logs(limit=1000)
    assert not any(e["action"] == "tool.finished" and e["details"].get("call_id") == r["call_id"] for e in logs)


def rpc_process(m, requests):
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
    r = subprocess.run([sys.executable, str(ROOT/"manager.py"), "--data-dir", str(m.data), "mcp"],
                       input=payload, text=True, encoding="utf-8", capture_output=True, timeout=40)
    assert r.returncode == 0, r.stderr
    rows = [json.loads(line) for line in r.stdout.splitlines()]
    (m.data/"transport-last.json").write_text(json.dumps({"requests": requests, "responses": rows, "stderr": r.stderr},
                                                       ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def rpc(method, rid=1, **params):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


def test_real_stdio_process_restart_and_errors(runtime):
    m, p, image = enabled(runtime)
    rows = rpc_process(m, [
        rpc("initialize", protocolVersion="2025-06-18"),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        rpc("tools/list", 2),
        rpc("tools/call", 3, name="rebuild_start", arguments={"project": str(p), "references": [str(image)]}),
        rpc("tools/call", 4, name="rebuild_next", arguments={"project": str(p)}),
        rpc("tools/call", 5, name="rebuild_next", arguments={"project": str(p), "shell": "no"}),
    ])
    tools = rows[1]["result"]["tools"]
    from toolbox_manager.contracts import COMMANDS
    from toolbox_manager.mcp import TOOLS
    from toolbox_manager.icons.contracts import SPECS as ICON_SPECS
    from toolbox_manager.graphics import SPECS as GRAPHICS_SPECS
    assert len(tools) == len(TOOLS)+1+len(COMMANDS)+len(ICON_SPECS)+len(GRAPHICS_SPECS)  # retrospective adapter
    assert any(t['name']=='toolbox_usage' for t in tools)
    assert next(t for t in tools if t["name"] == "rebuild_next")["annotations"]["readOnlyHint"] is False
    assert rows[-1]["result"]["isError"] is True
    gate = rows[-2]["result"]["structuredContent"]
    assert gate['checkpoint_required']['required'] and 'task' not in gate
    state=rows[2]['result']['structuredContent']['stage_context']
    checkpoint={'checkpoint_id':'stdio-begin','run_id':state['run_id'],'expected_revision':0,
        'event':'begin','stage':'intake','result_summary':'stdio fixture','next_action':'Issue first task'}
    first=rpc_process(m,[rpc('initialize'),rpc('tools/call',2,name='rebuild_next',arguments={'project':str(p),'checkpoint':checkpoint})])
    task=first[-1]['result']['structuredContent']['task']
    assert task["context"] and task["input_files"] and task["response"]
    declare(m,p,'delivery')
    restarted = rpc_process(m, [
        rpc("initialize"), rpc("tools/call", 2, name="rebuild_next", arguments={"project": str(p)}),
        rpc("tools/call", 3, name="rebuild_submit", arguments={"project": str(p), "task_id": task["task_id"],
            "token": task["token"], "base_revision": task["base_revision"], "result": plan()}),
        rpc("tools/call", 4, name="rebuild_status", arguments={"project": str(p)}),
        rpc("tools/call", 5, name="rebuild_revise", arguments={"project": str(p), "slide": "slide-001", "region": "body", "reason": "transport test"}),
        rpc("tools/call", 6, name="rebuild_finish", arguments={"project": str(p)}),
    ])
    assert restarted[1]["result"]["structuredContent"]["task"]["token"] == task["token"]
    assert restarted[2]["result"]["structuredContent"]["accepted_task"] == task["task_id"]
    assert restarted[-1]["result"]["structuredContent"]["delivery_created"] is False
