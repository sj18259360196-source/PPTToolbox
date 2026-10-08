"""Owner completion and explicit, fingerprinted cleanup of completed projects."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import time
import uuid
import zipfile

from .policy import plain_path, PolicyDenied
from .storage import stamp, digest
from .project_inventory import inspect, lifecycle, invalidate, preview_paths

MARKER = "workflow/project-lifecycle.json"


def _save(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _overlap(a, b):
    return a.is_relative_to(b) or b.is_relative_to(a)


def _idle(manager, root):
    for row in manager.store.get("workbench_projects", {}).values():
        other = plain_path(row["path"])
        if not _overlap(root, other):
            continue
        if manager.store.unfinished_calls(str(other)):
            raise ValueError("项目存在运行中或结果未确认的调用，请先完成核对")
        if other != root and (other / "workflow/writer.lock").exists():
            raise ValueError("关联项目仍在写入，请稍后再试")
    if (root / ".ppt-toolbox-initialize.lock").exists():
        raise ValueError("项目仍在初始化")


@contextmanager
def _owner_lock(manager, key):
    from .workbench import Workbench
    from .project_context import ProjectContext
    root, row, state = Workbench(manager).entry(key)
    ProjectContext(manager, root)
    _idle(manager, root)
    lock = plain_path(root / "workflow/writer.lock")
    # Registered folder projects may not have started a production workflow.
    lock.parent.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("项目存在写入锁，请等制作完成后再操作")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "token": token,
                       "created_at": stamp(), "purpose": "owner-project-management"}, stream)
        _idle(manager, root)
        current_root, row, state = Workbench(manager).entry(key)
        if current_root != root:
            raise ValueError("项目路径已变化，请刷新后重试")
        yield root, row, state
    finally:
        if lock.exists() and json.loads(lock.read_text(encoding="utf-8")).get("token") == token:
            lock.unlink()


def _revision(body, state, record):
    if (type(body.get("revision")) is not int or body["revision"] != record["revision"]
            or type(body.get("state_revision")) is not int
            or body["state_revision"] != state.get("revision", 0)):
        raise ValueError("项目状态已变化，请刷新后重新确认")


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pptx(path):
    if path.suffix.lower() != ".pptx" or not path.is_file() or path.stat().st_size > 250 * 1024 * 1024:
        raise ValueError("请选择项目内不超过 250 MiB 的 PPTX 成品")
    with zipfile.ZipFile(path) as archive:
        if not {"[Content_Types].xml", "ppt/presentation.xml"} <= set(archive.namelist()):
            raise ValueError("所选文件不是有效的 PPTX")


def delivery_plan(manager, key):
    """Compact, read-only preparation; invoked only after an owner selects delivery."""
    from .workbench import Workbench
    root, row, state = Workbench(manager).entry(key)
    record = lifecycle(root)
    result = {"project": key, "revision": record["revision"],
              "state_revision": state.get("revision", 0), "files": [], "selected": ""}
    if record["status"] == "completed":
        return {**result, "status": "completed", "message": "已交付并完结，无需重复处理"}
    _idle(manager, root)
    if (root / "workflow/writer.lock").exists():
        raise ValueError("项目存在写入锁，请等制作完成后再交付")
    data = inspect(manager, key)
    if not data["complete"]:
        raise ValueError("项目文件未能完整读取，请打开项目核对后重试")
    # Never silently substitute an old delivery for a missing current file.
    current = state.get("delivery")
    if isinstance(current, str) and current:
        current = current.replace("\\", "/")
        if not current.lower().endswith(".pptx"):
            current = current.rstrip("/") + "/editable.pptx"
    else:
        current = ((state.get("run") or {}).get("candidate") or {}).get("file")
        current = current.replace("\\", "/") if isinstance(current, str) else None
    excluded = {"input", "inputs", "assets", "reference", "references", "tests", "test", ".tmp", "node_modules"}
    files = [{k: f[k] for k in ("path", "file_token", "size", "mtime_ns")}
             for f in data["files"] if f["path"].lower().endswith(".pptx")
             and f["size"] <= 250 * 1024 * 1024
             and (f["path"] == current or not excluded.intersection(p.lower() for p in Path(f["path"]).parts[:-1]))]
    paths = {f["path"] for f in files}
    finals = [f["path"] for f in data["deliveries"] if f["path"] in paths]
    selected = current if current in paths else ""
    if not current:
        selected = finals[0] if len(finals) == 1 else files[0]["path"] if len(files) == 1 else ""
    _, _, latest = Workbench(manager).entry(key)
    if latest.get("revision", 0) != result["state_revision"] or lifecycle(root) != record:
        raise ValueError("项目状态已变化，请重新读取交付清单")
    message = ("当前成品已选中" if selected else "当前文件已失效，请重新选择成品" if current
               else "请选择本次交付的 PPT" if files else "没有可交付的 PPTX 文件")
    return {**result, "status": "ready" if files else "unavailable", "message": message,
            "selected": selected, "files": sorted(files, key=lambda f: (f["path"] != selected, -f["mtime_ns"]))}


def _retain_preview(root, selected, files, target, source_sha):
    parts = Path(selected).parts
    if len(parts) < 3 or parts[0] not in {"runs", "delivery"}:
        return
    prefix = "/".join(parts[:2]) + "/"
    candidates = []
    for item in files:
        if item["path"].startswith(prefix) and item["name"] == "office-render.json":
            path = plain_path(root / item["path"])
            try:
                if path.stat().st_size <= 4 * 1024 * 1024:
                    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
                    if receipt.get("pptx_sha256") == source_sha:
                        candidates.append(item)
            except (OSError, ValueError, AttributeError):
                pass
    if not candidates:
        return
    folder = max(candidates, key=lambda f: f["mtime_ns"])["path"].rsplit("/", 1)[0]
    import re
    images = [f for f in files if f["path"].rsplit("/", 1)[0] == folder
              and re.fullmatch(r"slide[-_]?\d+\.(png|jpe?g|webp)", f["name"], re.I)]
    if images:
        preview = target / "preview"
        preview.mkdir()
        for image in images:
            shutil.copyfile(plain_path(root / image["path"]), preview / image["name"])
        _save(preview / "office-render.json", {"pptx_sha256": source_sha, "source": folder})


def complete(manager, body):
    if body.get("confirmed") is not True:
        raise ValueError("请确认所选 PPT 为本次成品")
    with _owner_lock(manager, body.get("project")) as (root, row, state):
        record = lifecycle(root)
        _revision(body, state, record)
        if record["status"] != "active":
            raise ValueError("项目已完结，请刷新状态")
        data = inspect(manager, body["project"])
        selected = next((f for f in data["files"] if f["path"] == body.get("path")), None)
        if not selected or selected["file_token"] != body.get("file_token"):
            raise ValueError("成品文件已变化，请重新选择")
        source = plain_path(root / selected["path"])
        _pptx(source)
        source_sha = _sha(source)
        final = next((f for f in data["deliveries"] if f["path"] == selected["path"]
                      and f["kind"] != "unconfirmed" and f["sha256"] == source_sha), None)
        if final:
            delivered = selected["path"]
        else:
            # Owner acceptance is distinct from automated production/visual validation.
            target = plain_path(root / "delivery" / ("owner-" + uuid.uuid4().hex[:12]))
            target.mkdir(parents=True, exist_ok=False)
            shutil.copyfile(source, target / "editable.pptx")
            if _sha(target / "editable.pptx") != source_sha:
                raise ValueError("成品复制校验失败，未标记完结")
            _retain_preview(root, selected["path"], data["files"], target, source_sha)
            _save(target / "delivery.json", {"status": "owner_accepted", "pptx_sha256": source_sha,
                  "completed_at": stamp(), "source": selected["path"],
                  "note": "Owner-selected delivery. Does not certify automated or visual checks."})
            delivered = (target / "editable.pptx").relative_to(root).as_posix()
        record = {**record, "status": "completed", "revision": record["revision"] + 1,
                  "completed_at": stamp(), "delivery": delivered, "delivery_sha256": source_sha,
                  "project_id": state["project_id"], "history_cleaned": False}
        _save(root / MARKER, record)
    invalidate(manager)
    manager.store.event("project.completed", "Owner marked project complete", source="browser",
                        details={"project": str(root), "delivery": delivered})
    return record


def reopen(manager, body):
    with _owner_lock(manager, body.get("project")) as (root, _, state):
        record = lifecycle(root)
        _revision(body, state, record)
        if record.get("history_cleaned") or record.get("cleanup"):
            raise ValueError("制作历史已清理，无法恢复原制作流程。可以编辑保留的 PPT，或新建制作项目")
        record.update(status="active", revision=record["revision"] + 1, reopened_at=stamp())
        _save(root / MARKER, record)
    invalidate(manager)
    return record


def _candidates(data):
    keep = preview_paths(data["files"])
    result = []
    for f in data["files"]:
        parts = Path(f["path"]).parts
        top = parts[0]
        removable = (top in {"runs", "trials", ".tmp", "cache", "__pycache__", ".pytest_cache"}
                     or (top == "logs" and len(parts) > 1 and parts[1] == "tool-calls")
                     or (top == "workflow" and len(parts) > 1
                         and parts[1] not in {"state.json", "writer.lock", "project-lifecycle.json"})
                     or (top == "delivery" and len(parts) > 2 and parts[2] == "production"))
        if removable and f["path"] not in keep:
            result.append(f)
    return result


def _plan(manager, key):
    data = inspect(manager, key)
    record, root = data["lifecycle"], Path(data["root"])
    if record["status"] != "completed":
        raise ValueError("请先交付并完结项目，再清理制作历史")
    if not data["complete"]:
        raise ValueError("部分文件无法读取或存在链接，请先处理后再清理")
    final = plain_path(root / record["delivery"])
    if not final.is_relative_to(root) or not final.is_file() or _sha(final) != record["delivery_sha256"]:
        raise ValueError("保留成品缺失或已改变，已阻止清理")
    candidates = _candidates(data)
    registry = manager.store.get("workbench_projects", {})
    for other in registry.values():
        path = plain_path(other["path"])
        if path != root and path.is_relative_to(root):
            if any((root / f["path"]).is_relative_to(path) for f in candidates):
                raise ValueError("清理范围包含其他项目")
    for path, grant in manager.store.get("project_authorizations", {}).items():
        if plain_path(path) == root:
            continue
        inputs = [plain_path(p) for p in grant.get("input_roots", [])]
        if any(any(_overlap(root / f["path"], p) for p in inputs) for f in candidates):
            raise ValueError("制作文件仍被其他项目授权为输入，已阻止清理")
    fingerprint = digest(json.dumps({"files": candidates, "state": data["state_revision"],
                                    "lifecycle": record}, sort_keys=True))
    return data, candidates, fingerprint


def preview_cleanup(manager, body):
    with _owner_lock(manager, body.get("project")):
        data, files, fingerprint = _plan(manager, body["project"])
        token = uuid.uuid4().hex
        manager.store.set("project_cleanup:" + token, {"project": body["project"],
                          "fingerprint": fingerprint, "expires": time.time() + 600, "status": "preview"})
    groups = {}
    for f in files:
        folder = f["path"].split("/")[0]
        group = groups.setdefault(folder, {"path": folder, "bytes": 0, "files": 0})
        group["bytes"] += f["size"]
        group["files"] += 1
    return {"token": token, "bytes": sum(f["size"] for f in files), "files": len(files),
            "groups": list(groups.values()), "sample": [f["path"] for f in files[:40]],
            "retained_delivery": data["lifecycle"]["delivery"],
            "preserved": ["成品 PPT 与交付记录", "参考图与素材", "成品预览", "项目状态与清理记录"],
            "expires_in": 600}


def cleanup(manager, body):
    if body.get("confirmed") is not True or not isinstance(body.get("token"), str):
        raise ValueError("请先预览并确认清理")
    token_key = "project_cleanup:" + body["token"]
    with _owner_lock(manager, body.get("project")) as (root, _, _):
        saved = manager.store.get(token_key, {})
        if saved.get("project") != body["project"] or saved.get("status") != "preview" or saved.get("expires", 0) < time.time():
            raise ValueError("清理预览已失效，请重新检查")
        data, files, fingerprint = _plan(manager, body["project"])
        if fingerprint != saved["fingerprint"]:
            raise ValueError("文件或项目状态已变化，请重新预览")
        # Mark destructive intent before the first unlink; interruption is never reported as success.
        record = data["lifecycle"]
        record.update(history_cleaned=True, revision=record["revision"] + 1,
                      cleanup={"status": "in_progress", "started_at": stamp(),
                               "planned_bytes": sum(f["size"] for f in files), "planned_files": len(files)})
        _save(root / MARKER, record)
        manager.store.set(token_key, {**saved, "status": "consumed"})
        removed, freed, error = 0, 0, None
        try:
            for f in files:
                target = plain_path(root / f["path"])
                if not target.is_relative_to(root):
                    raise PolicyDenied("清理路径越界")
                info = target.stat()
                if (info.st_size, info.st_mtime_ns, info.st_ino, info.st_nlink) != (f["size"], f["mtime_ns"], f["inode"], 1):
                    raise ValueError("文件正在变化，清理已停止")
                target.unlink()
                removed += 1
                freed += f["size"]
            # Only empty directories in the exact removed paths are eligible.
            parents = {p for f in files for p in (root / f["path"]).parents if p != root and p.is_relative_to(root)}
            for directory in sorted(parents, key=lambda p: len(p.parts), reverse=True):
                if directory in {root / "workflow", root / "delivery"}:
                    continue
                try:
                    plain_path(directory).rmdir()
                except OSError:
                    pass
        except (OSError, ValueError) as exc:
            error = str(exc)
        record["cleanup"].update(status="partial" if error else "completed", removed_files=removed,
                                 freed_bytes=freed, ended_at=stamp(), error=error)
        _save(root / MARKER, record)
    invalidate(manager)
    manager.store.event("project.history_cleaned", "Owner project cleanup finished", source="browser",
                        status="error" if error else "ok", details={"project": str(root), **record["cleanup"]})
    return record["cleanup"]
