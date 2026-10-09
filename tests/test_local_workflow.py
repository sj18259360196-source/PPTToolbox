"""Phase-02 deterministic fixtures, never host visual acceptance."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from test_managed_rebuild import ROOT, runtime, begin, invoke, response
from common import read_json, write_json, sha256
from toolbox_manager.contracts import validate
from workflow_store import locked, WorkflowError
from local_edit import prepare, surgical_write, properties, equivalent
from build_pptx import build


def active(runtime):
    m, p, ref = begin(runtime)
    r = response(m, p, {"regions": [
        {"id": "card", "bbox": [100, 70, 420, 280], "role": "content", "summary": "FIXTURE", "local_review": True},
        {"id": "other", "bbox": [440, 70, 630, 280], "role": "content", "summary": "FIXTURE", "local_review": True}]})
    assert r["command_status"] == "completed", r
    task = invoke(m, "next", p)["task"]
    return m, p, task


def probe_args(task, op="trial1"):
    return {"operation_id": op, "task_id": task["task_id"], "base_revision": task["base_revision"],
            "office": False, "result": {"objects": [
                {"id": "label", "kind": "text", "text": "DETERMINISTIC FIXTURE", "bbox": [10, 10, 200, 35]}],
                "source_notes": "TRANSPORT FIXTURE; not image understanding"}}


def test_probe_nonzero_origin_no_task_consumption_and_idempotence(runtime):
    m, p, task = active(runtime)
    before = sha256(p/"workflow/state.json")
    result = invoke(m, "probe", p, **probe_args(task))
    assert result["command_status"] == "completed", result
    assert result["local_status"] == "awaiting_office"
    assert sha256(p/"workflow/state.json") == before
    scene = read_json(Path(result["outputs"]["scene"]))
    mapping = read_json(p/"workflow/state.json")["pages"][0]["mapping"]
    assert scene["slides"][0]["objects"][0]["bbox"][0] == pytest.approx(110/mapping["scale_x"])
    assert Path(result["outputs"]["pptx"]).is_file()
    assert invoke(m, "probe", p, **probe_args(task))["trial_id"] == "trial1"
    assert len(list((p/"trials").iterdir())) == 1
    assert sha256(p/"workflow/state.json") == before
    changed = probe_args(task); changed["result"]["objects"][0]["text"] = "OTHER"
    assert invoke(m, "probe", p, **changed)["command_status"] == "invalid_arguments"


@pytest.mark.parametrize("mutation", ["unknown", "bool", "path", "style", "unsupported"])
def test_local_schemas_reject(mutation):
    a = {"project": "p", "operation_id": "a", "base_revision": 1, "scene_sha256": "a"*64,
         "pptx_sha256": "b"*64, "slide": "s", "region": "r", "reason": "test",
         "changes": [{"op": "text.set", "id": "x", "text": "t"}]}
    if mutation == "unknown": a["shell"] = "bad"
    if mutation == "bool": a["base_revision"] = True
    if mutation == "path": a["operation_id"] = "../elsewhere"
    if mutation == "style": a["changes"] = [{"op": "text.style", "id": "x", "style": {"rotation": 90}}]
    if mutation == "unsupported": a["changes"][0]["op"] = "eval"
    with pytest.raises(ValueError): validate("patch", a, ROOT)


@pytest.mark.parametrize("cap", ["workflow.probe", "pptx.build", "office.render"])
def test_probe_dependencies(runtime, cap):
    m, p, task = active(runtime)
    m.toggle("tool", cap, False)
    a = probe_args(task); a["office"] = True
    before = sha256(p/"workflow/state.json")
    r = invoke(m, "probe", p, **a)
    assert r["command_status"] == "permission_denied", r
    assert not list((p/"trials").glob("*/sample.pptx"))
    assert sha256(p/"workflow/state.json") == before


def test_probe_budget_stale_lock_and_interrupted(runtime):
    m, p, task = active(runtime)
    with locked(p):
        assert invoke(m, "probe", p, **probe_args(task))["error"]["code"] == "writer_busy"
    for i in range(6):
        assert invoke(m, "probe", p, **probe_args(task, f"t{i}"))["command_status"] == "completed"
    assert invoke(m, "probe", p, **probe_args(task, "t6"))["error"]["code"] == "trial_budget"
    a = probe_args(task, "stale"); a["base_revision"] -= 1
    assert invoke(m, "probe", p, **a)["error"]["code"] == "stale_trial"
    f = p/"trials"/"interrupted"; f.mkdir()
    from local_workflow import fingerprint
    a = {"project": str(p), **probe_args(task, "interrupted")}
    write_json(f/"intent.json", {"fingerprint": fingerprint({"command": "probe", "arguments": a})})
    assert invoke(m, "probe", p, **probe_args(task, "interrupted"))["command_status"] == "outcome_unknown"


def scene_fixture(tmp_path):
    Image.new("RGB", (640, 360), "white").save(tmp_path/"ref.png")
    Image.new("RGB", (120, 80), "red").save(tmp_path/"asset.png")
    scene = {"version": "1.0", "canvas": {"width": 640, "height": 360, "width_pt": 960, "height_pt": 540, "mapping": "uniform"},
             "slides": [{"id": "page", "reference": "ref.png", "objects": [
                 {"id": "text", "kind": "text", "text": "ORIGINAL", "bbox": [20, 20, 220, 40]},
                 {"id": "box", "kind": "shape", "geometry": "rect", "bbox": [20, 90, 80, 60],
                  "style": {"fill": "FFFFFF"}},
                 {"id": "group", "kind": "group", "children": [
                     {"id": "child1", "kind": "shape", "geometry": "rect", "bbox": [200, 90, 60, 40]},
                     {"id": "child2", "kind": "text", "text": "GROUP", "bbox": [270, 90, 120, 40]}]},
                 {"id": "picture", "kind": "image", "asset": "asset.png", "fit": "stretch", "bbox": [400, 180, 160, 100],
                  "asset_role": "decoration", "source_kind": "crop"}
             ]}]}
    from workflow_scene import EDIT
    from common import walk_objects
    for o in walk_objects(scene["slides"][0]["objects"]):
        o["editability"] = EDIT[o["kind"]]
        o["evidence"] = {"status": "inferred", "note": "Known-answer deterministic operation fixture"}
    write_json(tmp_path/"scene.json", scene)
    build(tmp_path/"scene.json", tmp_path/"base.pptx")
    return tmp_path/"scene.json", tmp_path/"base.pptx"


OPERATIONS = [
    {"op": "text.set", "id": "text", "text": "EDITED"},
    {"op": "text.style", "id": "text", "style": {"font_size_pt": 15, "color": "123456", "align": "right", "margin_left_pt": 4}},
    {"op": "geometry.set", "id": "box", "bbox": [30, 90, 100, 50]},
    {"op": "fill.set", "id": "box", "color": "12AB34"},
    {"op": "group.translate", "id": "group", "delta": [10, 12]},
    {"op": "picture.crop", "id": "picture", "source_crop": [10, 10, 90, 60]},
]


@pytest.mark.parametrize("change", OPERATIONS, ids=[c["op"] for c in OPERATIONS])
def test_six_surgical_operations_preserve_scene_and_package(tmp_path, change):
    scene, base = scene_fixture(tmp_path)
    before = sha256(base)
    prs, updated, index, touched = prepare(scene, base, "page", {change["id"]}, [change])
    d = surgical_write(base, tmp_path/"patched.pptx", prs, index)
    assert d["changed"] == ["ppt/slides/slide1.xml"]
    assert sha256(base) == before
    write_json(tmp_path/"new.json", updated)
    build(tmp_path/"new.json", tmp_path/"rebuilt.pptx")
    a, b = properties(tmp_path/"patched.pptx"), properties(tmp_path/"rebuilt.pptx")
    assert equivalent(a, b), (a, b)
    old = properties(base)
    assert all(old[k] == a[k] for k in old if k.split("/", 1)[1] not in touched)


@pytest.mark.parametrize("change", [
    {"op": "text.set", "id": "text", "text": "x\ny"},
    {"op": "geometry.set", "id": "group", "bbox": [1, 2, 30, 40]},
    {"op": "picture.crop", "id": "picture", "source_crop": [0, 0, 999, 999]},
    {"op": "fill.set", "id": "text", "color": "112233"},
])
def test_unsupported_subtypes_before_output(tmp_path, change):
    scene, base = scene_fixture(tmp_path)
    before = sha256(base)
    with pytest.raises(ValueError):
        prepare(scene, base, "page", {change["id"]}, [change])
    assert sha256(base) == before
    assert not (tmp_path/"patched.pptx").exists()


def test_shared_office_queue_timeout_and_conflict(tmp_path):
    from runtime_env import office_guard, OfficeBusy
    path = tmp_path/"office.lock"
    with office_guard(path):
        with pytest.raises(OfficeBusy, match="writer"):
            with office_guard(path): pass
    assert not path.exists()
    with pytest.raises(subprocess.TimeoutExpired):
        with office_guard(path):
            raise subprocess.TimeoutExpired("fixture", 1)
    assert path.exists()


def test_true_stdio_probe_and_restart(runtime):
    m, p, task = active(runtime)
    from phase01_driver import call
    evidence = p.parent/"transport"
    r = call(m.data, "rebuild_probe", {"project": str(p), **probe_args(task)}, evidence)
    assert r["command_status"] == "completed", r
    repeat = call(m.data, "rebuild_probe", {"project": str(p), **probe_args(task)}, evidence)
    assert repeat["trial_id"] == r["trial_id"]
    assert len(list((evidence/"rpc").glob("*.json"))) == 2
    m.toggle("tool", "office.render", False)
    denied = call(m.data, "rebuild_compare", {"project": str(p), "operation_id": "cmp", "trial_id": "trial1"}, evidence)
    assert denied["command_status"] == "permission_denied", denied


def test_managed_cli_probe_same_service(runtime):
    m, p, task = active(runtime)
    request = p/"probe-request.json"; write_json(request, probe_args(task))
    r = m.execute("workflow.probe", ["--project", str(p), "--request", str(request)])
    assert r["command_status"] == "completed", r
    assert invoke(m, "probe", p, **probe_args(task))["trial_id"] == r["trial_id"]


def synthetic_comparison(p, result, operation="fixture-compare"):
    """Fault-injection fixture, explicitly not Office/visual validation."""
    from local_workflow import persist
    folder = p/"trials"/operation; folder.mkdir()
    marker = folder/"FIXTURE-NOT-VISUAL.txt"; marker.write_text("synthetic", encoding="utf-8")
    record = read_json(Path(result["record"]))
    record.update(kind="compare", status="awaiting_observation", trial_id=result["trial_id"],
                  trial_record_sha256=sha256(Path(result["record"])),
                  structural_consistency="passed", outside_regression="not_applicable",
                  view_files=[marker.name])
    persist(folder, record)
    return {"operation_id": "adopt1", "trial_id": result["trial_id"], "comparison_id": operation,
            "observation": {"status": "needs_changes", "note": "FAULT INJECTION FIXTURE; no visual acceptance",
                            "reviewer": "fixture", "viewed_files": [str(marker)]}}


@pytest.mark.parametrize("crash", ["before", "after", "none"])
def test_adoption_atomic_recovery(runtime, monkeypatch, crash):
    m, p, task = active(runtime)
    r = invoke(m, "probe", p, **probe_args(task))
    assert r["command_status"] == "completed", r
    a = {"project": str(p), **synthetic_comparison(p, r)}
    from local_workflow import execute_local
    from toolbox_manager.policy import check_input
    import workflow as wf
    class FixturePolicy:
        def require(self, *caps): pass
        def input(self, value): return check_input(value, p, [])
    monkeypatch.setattr(wf, "_managed_policy", None)
    original = wf.save
    before = sha256(p/"workflow/state.json")
    def fail(*args, **kwargs):
        if crash == "after": original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC power-loss boundary")
    if crash != "none":
        monkeypatch.setattr(wf, "save", fail)
        with pytest.raises(RuntimeError):
            execute_local("adopt", p, a, FixturePolicy())
        monkeypatch.setattr(wf, "save", original)
    else:
        assert execute_local("adopt", p, a, FixturePolicy())["local_status"] == "adopted"
    retry = execute_local("adopt", p, a, FixturePolicy())
    state = read_json(p/"workflow/state.json")
    if crash == "before":
        assert sha256(p/"workflow/state.json") == before
        assert retry["command_status"] == "outcome_unknown"
    else:
        assert retry["idempotent"]
        assert state["revision"] == task["base_revision"]+1
        assert state["active_task"] is None
        assert len(state["pages"][0]["fragments"]) == 1
        assert invoke(m, "submit", p, task_id=task["task_id"], token=task["token"],
                      base_revision=task["base_revision"], result=probe_args(task)["result"])["command_status"] != "completed"


def test_stale_trial_and_mutated_output(runtime):
    m, p, task = active(runtime)
    r = invoke(m, "probe", p, **probe_args(task))
    pptx = Path(r["outputs"]["pptx"]); pptx.write_bytes(pptx.read_bytes()+b"tampered")
    assert invoke(m, "probe", p, **probe_args(task))["error"]["code"] == "trial_changed"
    assert invoke(m, "probe", p, **probe_args(task, "clean"))["command_status"] == "completed"
    assert response(m, p, probe_args(task)["result"], task)["command_status"] == "completed"
    assert invoke(m, "compare", p, operation_id="cmp", trial_id="clean")["error"]["code"] == "stale_trial"


def test_rich_text_and_out_of_scope_rejected(tmp_path):
    scene, base = scene_fixture(tmp_path)
    with pytest.raises(ValueError, match="authorized"):
        prepare(scene, base, "page", {"box"}, [OPERATIONS[0]])
    s = read_json(scene); s["slides"][0]["objects"][0]["runs"] = [{"text": "rich"}]
    write_json(scene, s)
    with pytest.raises(ValueError, match="rich"):
        prepare(scene, base, "page", {"text"}, [OPERATIONS[0]])


@pytest.mark.parametrize("crash", ["before", "after"])
def test_paired_adoption_atomic_crash(runtime, monkeypatch, crash):
    """Synthetic recorded trial tests state transaction, not Office authenticity."""
    from test_managed_rebuild import ready
    from local_workflow import bundle, persist, execute_local
    import local_workflow as lw
    from toolbox_manager.policy import check_input
    m, p, _ = ready(runtime)
    invoke(m, "next", p)
    state = read_json(p/"workflow/state.json")
    folder = p/"trials"/"pair-fixture"; folder.mkdir(parents=True)
    original_scene = p/state["run"]["dir"]/"scene.json"
    data = read_json(original_scene)
    data["slides"][0]["objects"][0]["text"] = "PAIRED EDIT FIXTURE"
    scene = bundle(data, original_scene.parent, folder/"bundle")
    build(scene, folder/"candidate.pptx")
    record = {"kind": "patch", "status": "ready_to_compare", "project_id": state["project_id"],
              "base_revision": state["revision"], "state_sha256": sha256(p/"workflow/state.json"),
              "scene": "bundle/scene.json", "pptx": "candidate.pptx"}
    persist(folder, record)
    a = {"project": str(p), **synthetic_comparison(p, {"trial_id": folder.name, "record": str(folder/"record.json")})}
    class FixturePolicy:
        def require(self, *caps): pass
        def input(self, value): return check_input(value, p, [])
    before = sha256(p/"workflow/state.json")
    original = lw.save
    def fail(*args, **kwargs):
        if crash == "after": original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC pair commit power-loss")
    monkeypatch.setattr(lw, "save", fail)
    with pytest.raises(RuntimeError):
        execute_local("adopt", p, a, FixturePolicy())
    monkeypatch.setattr(lw, "save", original)
    retry = execute_local("adopt", p, a, FixturePolicy())
    current = read_json(p/"workflow/state.json")
    if crash == "before":
        assert sha256(p/"workflow/state.json") == before
        assert retry["command_status"] == "outcome_unknown"
    else:
        assert retry["idempotent"]
        assert current["revision"] == state["revision"]+1
        assert current["pages"][0]["imported_slide"]["objects"][0]["text"] == "PAIRED EDIT FIXTURE"
        assert current["pending_candidate"]["sha256"] == sha256(folder/"candidate.pptx")
        assert current["active_task"] is None and current["run"] is None
        assert current["pages"][0]["source_review"] is None


def test_shared_image_bytes_not_replaced(tmp_path):
    scene, _ = scene_fixture(tmp_path)
    data = read_json(scene)
    twin = copy.deepcopy(data["slides"][0]["objects"][-1])
    twin.update(id="twin", bbox=[200, 210, 120, 75])
    data["slides"][0]["objects"].append(twin); write_json(scene, data)
    build(scene, tmp_path/"shared.pptx")
    prs, updated, index, _ = prepare(scene, tmp_path/"shared.pptx", "page", {"picture"}, [OPERATIONS[-1]])
    surgical_write(tmp_path/"shared.pptx", tmp_path/"patched.pptx", prs, index)
    before, after = properties(tmp_path/"shared.pptx"), properties(tmp_path/"patched.pptx")
    assert before["0/twin"] == after["0/twin"]
    assert after["0/picture"]["media_sha256"] == before["0/picture"]["media_sha256"] == after["0/twin"]["media_sha256"]


def test_patch_permission_and_public_redaction(runtime):
    from test_managed_rebuild import ready
    from toolbox_manager.execution import arguments_summary
    m, p, _ = ready(runtime)
    invoke(m, "next", p)
    s = read_json(p/"workflow/state.json")
    a = {"operation_id": "denied", "base_revision": s["revision"], "scene_sha256": sha256(p/s["run"]["dir"]/"scene.json"),
         "pptx_sha256": s["run"]["candidate"]["sha256"], "slide": s["pages"][0]["id"], "region": "body",
         "changes": [{"op": "text.set", "id": s["pages"][0]["id"]+".body.label", "text": "SECRET CONTENT"}],
         "reason": "PRIVATE REASON"}
    m.toggle("tool", "office.render", False)
    before = sha256(p/"workflow/state.json")
    r = invoke(m, "patch", p, **a)
    assert r["command_status"] == "permission_denied"
    assert not list((p/"trials").glob("*/patched-xml.pptx"))
    assert sha256(p/"workflow/state.json") == before
    summary = json.dumps(arguments_summary(a))
    assert "SECRET CONTENT" not in summary and "PRIVATE REASON" not in summary


def test_cross_project_trial_and_outside_failure_block_adopt(runtime):
    m, p, task = active(runtime)
    r = invoke(m, "probe", p, **probe_args(task))
    a = synthetic_comparison(p, r)
    cf = p/"trials"/a["comparison_id"]/"record.json"
    cr = read_json(cf); cr["outside_regression"] = "failed"; write_json(cf, cr)
    before = sha256(p/"workflow/state.json")
    assert invoke(m, "adopt", p, **a)["command_status"] == "invalid_arguments"
    assert sha256(p/"workflow/state.json") == before
    rf = Path(r["record"]); tr = read_json(rf); tr["project_id"] = "foreign-project"; write_json(rf, tr)
    assert invoke(m, "compare", p, operation_id="cross-project", trial_id=r["trial_id"])["error"]["code"] == "stale_trial"
