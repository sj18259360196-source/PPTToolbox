"""Synthetic owner lifecycle fixtures, not Office or visual acceptance."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import zipfile

import pytest

from toolbox_manager.service import Manager
from toolbox_manager.project_inventory import inspect, lifecycle, overview, walk
from toolbox_manager.project_lifecycle import complete, reopen, preview_cleanup, cleanup
from toolbox_manager.project_files import listing, read
from toolbox_manager.projects import update_metadata
from toolbox_manager.workbench import Workbench
from toolbox_manager.policy import authorize


@pytest.fixture
def sample(tmp_path):
    m = Manager(tmp_path / "data")
    root = tmp_path / "project"
    (root / "workflow").mkdir(parents=True)
    (root / "workflow/state.json").write_text(json.dumps({
        "project_id": "sample", "revision": 5, "status": "awaiting_visual_review",
        "history": [], "pages": [], "canvas": {"width": 640, "height": 360}
    }), encoding="utf-8")
    for path in ("runs/run-0001/candidate.pptx", "runs/run-0001/old.pptx"):
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(f, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/presentation.xml", "<presentation/>")
    for path in ("input/reference.png", "assets/material.svg", "workflow/results/task.json",
                 "logs/tool-calls/1/stdout.json", "trials/old/record.json", ".tmp/scratch.txt"):
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"fixture")
    m.store.set("workbench_projects", {"sample": {
        "path": str(root), "project_id": "sample", "label": "Test project",
        "metadata_revision": 0, "category": "agent", "archived": False}})
    return m, root


def finish(m, file="runs/run-0001/candidate.pptx"):
    data = inspect(m, "sample")
    selected = next(f for f in data["files"] if f["path"] == file)
    return complete(m, {"project": "sample", "revision": data["lifecycle"]["revision"],
                        "state_revision": data["state_revision"], "path": file,
                        "file_token": selected["file_token"], "confirmed": True})


def clear(m):
    plan = preview_cleanup(m, {"project": "sample"})
    result = cleanup(m, {"project": "sample", "token": plan["token"], "confirmed": True})
    return plan, result


def test_complete_preserves_workflow_and_copies_owner_delivery(sample):
    m, root = sample
    before = (root / "workflow/state.json").read_bytes()
    record = finish(m)
    assert record["status"] == "completed" and not record["history_cleaned"]
    assert (root / record["delivery"]).read_bytes() == (root / "runs/run-0001/candidate.pptx").read_bytes()
    receipt = json.loads((root / record["delivery"]).with_name("delivery.json").read_text())
    assert receipt["status"] == "owner_accepted"
    assert before == (root / "workflow/state.json").read_bytes()
    assert inspect(m, "sample")["deliveries"][0]["kind"] == "owner"
    with pytest.raises(ValueError, match="完结"):
        authorize(m, root)
    assert not (root / "workflow/writer.lock").exists()


def test_reopen_before_cleanup_only(sample):
    m, root = sample
    record = finish(m)
    reopened = reopen(m, {"project": "sample", "revision": record["revision"], "state_revision": 5})
    assert reopened["status"] == "active"
    finish(m)
    clear(m)
    record = lifecycle(root)
    with pytest.raises(ValueError, match="无法恢复"):
        reopen(m, {"project": "sample", "revision": record["revision"], "state_revision": 5})


def test_cleanup_reclaims_history_but_preserves_assets_and_delivery(sample):
    m, root = sample
    record = finish(m)
    keep = {p: (root / p).read_bytes() for p in ["input/reference.png", "assets/material.svg",
                                               "workflow/state.json", record["delivery"]]}
    plan, result = clear(m)
    assert result["status"] == "completed"
    assert result["freed_bytes"] == plan["bytes"] > 0
    assert result["removed_files"] == plan["files"]
    assert not (root / "runs").exists()
    assert not (root / "workflow/results").exists()
    assert all((root / p).read_bytes() == raw for p, raw in keep.items())
    assert Workbench(m).projects()[0]["lifecycle"]["history_cleaned"]
    assert listing(m, "sample", group="delivery")["total"] == 1
    with pytest.raises(ValueError, match="清理"):
        Workbench(m).snapshot("sample")
    with pytest.raises(ValueError, match="失效"):
        cleanup(m, {"project": "sample", "token": plan["token"], "confirmed": True})


def test_cleanup_requires_completion_confirmation_and_fresh_plan(sample):
    m, root = sample
    with pytest.raises(ValueError, match="完结"):
        preview_cleanup(m, {"project": "sample"})
    finish(m)
    plan = preview_cleanup(m, {"project": "sample"})
    with pytest.raises(ValueError, match="确认"):
        cleanup(m, {"project": "sample", "token": plan["token"]})
    (root / ".tmp/scratch.txt").write_bytes(b"modified")
    with pytest.raises(ValueError, match="变化"):
        cleanup(m, {"project": "sample", "token": plan["token"], "confirmed": True})
    assert (root / "runs/run-0001/candidate.pptx").exists()


def test_final_missing_or_modified_blocks_cleanup(sample):
    m, root = sample
    record = finish(m)
    (root / record["delivery"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="成品"):
        preview_cleanup(m, {"project": "sample"})


def test_writer_and_pending_calls_block_completion(sample):
    m, root = sample
    lock = root / "workflow/writer.lock"
    lock.write_text('{"token":"other"}')
    with pytest.raises(ValueError, match="写入锁"):
        finish(m)
    assert json.loads(lock.read_text())["token"] == "other"
    lock.unlink()
    m.store.event("tool.authorized", "fixture", details={"project": str(root), "call_id": "active"})
    with pytest.raises(ValueError, match="调用"):
        finish(m)


def test_old_file_identity_and_stale_state_are_rejected(sample):
    m, root = sample
    data = inspect(m, "sample")
    f = next(f for f in data["files"] if f["name"] == "candidate.pptx")
    body = dict(project="sample", revision=0, state_revision=4, path=f["path"], file_token=f["file_token"], confirmed=True)
    with pytest.raises(ValueError, match="状态"):
        complete(m, body)
    with pytest.raises(ValueError, match="文件"):
        complete(m, {**body, "state_revision": 5, "file_token": "stale"})


def test_partial_deletion_is_durable_and_retryable(sample, monkeypatch):
    m, root = sample
    finish(m)
    original = Path.unlink
    def deny(path, *args, **kwargs):
        if path == root / "runs/run-0001/old.pptx":
            raise PermissionError("fixture locked file")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", deny)
        _, result = clear(m)
    assert result["status"] == "partial" and result["removed_files"] > 0
    assert lifecycle(root)["history_cleaned"]
    assert lifecycle(root)["cleanup"]["status"] == "partial"
    _, result = clear(m)
    assert result["status"] == "completed"


def test_delivery_page_unaffected_by_many_assets_and_download_not_page_limited(sample):
    m, root = sample
    for index in range(510):
        (root / "assets" / f"{index:04}.txt").write_text("x")
    record = finish(m)
    assert listing(m, "sample", group="delivery", limit=1)["files"][0]["path"] == record["delivery"]
    first = listing(m, "sample", group="assets")
    second = listing(m, "sample", group="assets", offset=100)
    assert first["total"] == 511 and first["next_offset"] == 100
    assert not {f["path"] for f in first["files"]} & {f["path"] for f in second["files"]}
    assert read(m, "sample", "assets/0509.txt").read_text() == "x"
    with pytest.raises(ValueError):
        read(m, "sample", "../outside.txt")


def test_nested_projects_excluded_from_parent_accounting(sample):
    m, root = sample
    child = root / "runs/child"
    (child / "workflow").mkdir(parents=True)
    (child / "workflow/state.json").write_text('{"project_id":"child","revision":1,"status":"draft"}')
    (child / "precious.txt").write_bytes(b"precious")
    registry = m.store.get("workbench_projects")
    registry["child"] = {"path": str(child), "project_id": "child", "label": "Child"}
    m.store.set("workbench_projects", registry)
    data = inspect(m, "sample")
    assert data["excluded_children"] == 1
    assert all(not f["path"].startswith("runs/child/") for f in data["files"])
    finish(m)
    clear(m)
    assert (child / "precious.txt").read_bytes() == b"precious"


def test_external_input_dependency_blocks_cleanup(sample, tmp_path):
    m, root = sample
    finish(m)
    m.store.set("project_authorizations", {str(tmp_path / "another"): {
        "write": True, "input_roots": [str(root / "runs")]}})
    with pytest.raises(ValueError, match="输入"):
        preview_cleanup(m, {"project": "sample"})


def test_hardlinks_make_scan_incomplete_and_block_cleanup(sample):
    m, root = sample
    finish(m)
    os.link(root / "input/reference.png", root / ".tmp/linked.png")
    assert not inspect(m, "sample")["complete"]
    with pytest.raises(ValueError, match="链接"):
        preview_cleanup(m, {"project": "sample"})


def test_only_main_delivery_and_render_preview_survive(sample):
    m, root = sample
    d = root / "delivery/run-0001"
    (d / "production/office-001").mkdir(parents=True)
    (d / "production/office-001/slide-001.png").write_bytes(b"preview")
    (d / "production/test.pptx").write_bytes(b"test")
    raw = (root / "runs/run-0001/candidate.pptx").read_bytes()
    (d / "editable.pptx").write_bytes(raw)
    (d / "delivery.json").write_text(json.dumps({"status": "passed", "pptx_sha256": hashlib.sha256(raw).hexdigest()}))
    record = finish(m, "delivery/run-0001/editable.pptx")
    assert record["delivery"] == "delivery/run-0001/editable.pptx"
    assert len(inspect(m, "sample")["deliveries"]) == 1
    clear(m)
    assert (d / "production/office-001/slide-001.png").exists()
    assert not (d / "production/test.pptx").exists()


def test_owner_delivery_retains_matching_preview_and_context(sample):
    from toolbox_manager.project_context import ProjectContext
    m, root = sample
    candidate = root / "runs/run-0001/candidate.pptx"
    office = candidate.parent / "office-001"
    office.mkdir()
    (office / "slide-001.png").write_bytes(b"preview")
    (office / "office-render.json").write_text(json.dumps({
        "pptx_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}))
    record = finish(m)
    image = (root / record["delivery"]).parent / "preview/slide-001.png"
    assert image.read_bytes() == b"preview"
    clear(m)
    assert image.exists()
    context = ProjectContext(m, root).snapshot()
    assert context["current_pptx"] == str(root / record["delivery"])
    assert context["current_scene"] is None


def test_group_cycle_and_stale_metadata(sample):
    m, root = sample
    child = root / "child"
    (child / "workflow").mkdir(parents=True)
    (child / "workflow/state.json").write_text('{"project_id":"child","revision":1,"status":"draft"}')
    registry = m.store.get("workbench_projects")
    registry["child"] = {"path": str(child), "project_id": "child", "label": "Child"}
    m.store.set("workbench_projects", registry)
    body = dict(id="child", revision=0, label="Child", category="agent", archived=False, parent_id="sample")
    update_metadata(m, body)
    with pytest.raises(ValueError, match="changed"):
        update_metadata(m, body)
    with pytest.raises(ValueError, match="真实文件夹"):
        update_metadata(m, dict(id="sample", revision=0, label="Sample", category="agent", archived=False, parent_id="child"))


def test_background_accounting_eventually_ready(sample):
    m, _ = sample
    overview(m)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = overview(m)
        if result["status"] != "scanning":
            break
        time.sleep(.02)
    assert result["status"] == "ready"
    assert result["bytes"] == result["projects"]["sample"]["bytes"]


def test_legacy_ppt_is_unconfirmed_and_not_a_test_copy(sample):
    m, root = sample
    (root / "Legacy.pptx").write_bytes((root / "runs/run-0001/candidate.pptx").read_bytes())
    entries = inspect(m, "sample")["deliveries"]
    assert len(entries) == 1 and entries[0]["kind"] == "unconfirmed"
    assert entries[0]["path"] == "Legacy.pptx"


def test_direct_workflow_write_and_load_are_blocked_after_completion(sample):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from workflow_store import locked, load
    m, root = sample
    finish(m)
    with pytest.raises(ValueError, match="completed"):
        with locked(root):
            pytest.fail("Completed projects must not acquire a workflow write session")
    assert not (root / "workflow/writer.lock").exists()
    clear(m)
    with pytest.raises(ValueError, match="cleared"):
        load(root)


def test_expired_cleanup_preview_cannot_delete(sample):
    m, root = sample
    finish(m)
    plan = preview_cleanup(m, {"project": "sample"})
    key = "project_cleanup:" + plan["token"]
    m.store.set(key, {**m.store.get(key), "expires": 0})
    with pytest.raises(ValueError, match="失效"):
        cleanup(m, {"project": "sample", "token": plan["token"], "confirmed": True})
    assert (root / "runs").is_dir()


def test_owner_routes_require_auth_and_are_not_get_writes(sample):
    from toolbox_manager.server import LocalServer
    m, _ = sample
    server = LocalServer(m.data, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(route, body=None, auth=True):
        req = urllib.request.Request(server.origin + "/api/" + route,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + server.token} if auth else {})})
        return opener.open(req, timeout=10)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            request("project.cleanup", {"project": "sample"}, auth=False)
        assert error.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as error:
            request("project.complete?project=sample")
        assert error.value.code == 404
        assert json.load(request("project.inventory?project=sample"))["result"]["file_count"] > 0
        assert json.load(request("project.files?project=sample&group=delivery"))["result"]["total"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
