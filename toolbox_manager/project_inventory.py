"""Read-only file inventory and asynchronous disk accounting for the owner UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from .policy import plain_path
from .storage import stamp, digest

MAX_ENTRIES = 250000
GROUPS = {
    "deliverables": "成品与交付附件", "inputs": "参考图与素材",
    "history": "制作历史", "records": "工作流与日志",
    "cache": "临时文件与缓存", "other": "其他文件",
}


def file_group(relative):
    parts = Path(relative).parts
    top = parts[0].lower()
    if top == "delivery":
        return "history" if len(parts) > 2 and parts[2] == "production" else "deliverables"
    if top in {"input", "assets"}:
        return "inputs"
    if top in {"runs", "trials"}:
        return "history"
    if top in {"workflow", "logs", ".ppttool", "ppttool.md"}:
        return "records"
    if top in {".tmp", "cache", "__pycache__", ".pytest_cache"}:
        return "cache"
    return "other"


def walk(root, exclusions=()):
    """Never follow links; any omission is surfaced rather than counted as zero."""
    root = plain_path(root)
    excluded = {os.path.normcase(str(plain_path(p))) for p in exclusions}
    files, errors, directories = [], [], []
    pending, visited = [root], 0
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_ENTRIES:
                        return files, directories, errors + ["扫描达到文件数量上限"]
                    if os.path.normcase(entry.path) in excluded:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    relative = Path(entry.path).relative_to(root).as_posix()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                        errors.append(relative + " 是链接，未扫描")
                    elif stat.S_ISDIR(info.st_mode):
                        directories.append(relative)
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        # Windows DirEntry.stat omits link count/inode; obtain the real file identity.
                        info = os.stat(entry.path, follow_symlinks=False)
                        if info.st_nlink != 1:
                            errors.append(relative + " 是硬链接，未扫描")
                            continue
                        files.append({"path": relative, "name": entry.name, "size": info.st_size,
                                      "mtime_ns": info.st_mtime_ns, "inode": info.st_ino,
                                      "file_token": digest(f"{relative}\0{info.st_size}\0{info.st_mtime_ns}\0{info.st_ino}"),
                                      "group": file_group(relative)})
        except OSError as exc:
            errors.append(str(folder) + " " + str(exc))
    return sorted(files, key=lambda f: f["path"]), directories, errors


def lifecycle(root):
    path = plain_path(Path(root) / "workflow/project-lifecycle.json")
    if not path.exists():
        return {"status": "active", "revision": 0, "history_cleaned": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("status") not in {"active", "completed"}:
        raise ValueError("项目完结记录损坏，请先恢复记录")
    return data


def deliveries(root, files):
    """Only the main PPT of a receipt is a delivery, never nested test copies."""
    result = []
    by_path = {f["path"]: f for f in files}
    for relative, item in by_path.items():
        parts = Path(relative).parts
        if (item["name"].lower().endswith(".pptx")
                and (len(parts) == 1 or (len(parts) == 2 and parts[0] in {"delivery", "output", "outputs", "final"}))):
            result.append({**item, "version": Path(relative).stem, "kind": "unconfirmed",
                           "sha256": None, "delivered_at": None})
            continue
        if len(parts) != 3 or parts[0] != "delivery" or parts[2] != "editable.pptx":
            continue
        receipt_path = plain_path(root / parts[0] / parts[1] / "delivery.json")
        receipt = {}
        try:
            if receipt_path.stat().st_size <= 4 * 1024 * 1024:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
        if not isinstance(receipt, dict):
            receipt = {}
        kind = ("verified" if receipt.get("status") == "passed" else
                "owner" if receipt.get("status") == "owner_accepted" else "unconfirmed")
        result.append({**item, "version": parts[1], "kind": kind,
                       "sha256": receipt.get("pptx_sha256"),
                       "delivered_at": receipt.get("completed_at")})
    return sorted(result, key=lambda f: (-f["mtime_ns"], f["path"]))


def preview_paths(files):
    groups = {}
    for f in files:
        parts = Path(f["path"]).parts
        if (len(parts) >= 4 and parts[0] == "delivery"
                and re.fullmatch(r"slide[-_]?\d+\.(png|jpe?g|webp)", f["name"], re.I)
                and re.match(r"(office|render|preview)", parts[-2], re.I)):
            groups.setdefault(parts[1], []).append(f)
    keep = set()
    for rows in groups.values():
        newest = max(rows, key=lambda f: f["mtime_ns"])["path"].rsplit("/", 1)[0]
        keep.update(f["path"] for f in rows if f["path"].rsplit("/", 1)[0] == newest)
    return keep


def inspect(manager, key):
    from .workbench import Workbench
    root, row, state = Workbench(manager).entry(key)
    registry = manager.store.get("workbench_projects", {})
    children = [plain_path(r["path"]) for k, r in registry.items() if k != key
                and plain_path(r["path"]).is_relative_to(root) and plain_path(r["path"]) != root]
    files, directories, errors = walk(root, children)
    groups = [{"id": group, "label": label,
               "bytes": sum(f["size"] for f in files if f["group"] == group),
               "files": sum(f["group"] == group for f in files),
               "paths": sorted({("/".join(Path(f["path"]).parts[:3])
                                 if f["path"].startswith("delivery/") and f["group"] == "history"
                                 else Path(f["path"]).parts[0] if len(Path(f["path"]).parts) > 1 else ".")
                                for f in files if f["group"] == group})}
              for group, label in GROUPS.items()]
    return {"project": key, "root": str(root), "label": row["label"],
            "workflow_status": state["status"], "state_revision": state.get("revision", 0),
            "lifecycle": lifecycle(root), "bytes": sum(f["size"] for f in files),
            "file_count": len(files), "groups": groups, "files": files,
            "directories": directories, "deliveries": deliveries(root, files),
            "excluded_children": len(children), "errors": errors[:20],
            "complete": not errors, "scanned_at": stamp()}


def open_global(manager, body):
    allowed = {"cache", "webview", "icon-library", "application-updates", "runs"}
    if body.get("id") not in allowed:
        raise ValueError("存储目录无效")
    path = plain_path(manager.data / body["id"])
    if not path.is_relative_to(manager.data) or not path.is_dir():
        raise ValueError("存储目录不存在")
    if os.name != "nt":
        raise ValueError("本地打开需要 Windows 桌面")
    os.startfile(str(path))
    return {"status": "requested", "path": str(path)}


def public_inventory(value):
    return {k: v for k, v in value.items() if k not in {"files", "directories"}}


def invalidate(manager):
    with manager.lock:
        manager._storage_expired = True
        manager._gallery_cache = {}


def overview(manager, refresh=False):
    """One worker per manager. UI polling never synchronously walks project trees."""
    with manager.lock:
        cache = getattr(manager, "_storage_overview", {"projects": {}, "global": [], "status": "scanning"})
        due = refresh or getattr(manager, "_storage_expired", False) or time.monotonic() - getattr(manager, "_storage_at", 0) > 60
        if due and not getattr(manager, "_storage_scanning", False):
            manager._storage_scanning = True
            manager._storage_expired = False
            threading.Thread(target=_scan_overview, args=(manager,), daemon=True).start()
        return {**cache, "status": "scanning" if getattr(manager, "_storage_scanning", False) else cache["status"]}


def _scan_overview(manager):
    try:
        registry = manager.store.get("workbench_projects", {})
        projects, global_rows = {}, []
        roots = {}
        for key, row in registry.items():
            try:
                root = plain_path(row["path"])
                # Duplicate registry entries must not inflate the aggregate.
                if str(root).casefold() in roots:
                    projects[key] = {**projects[roots[str(root).casefold()]], "project": key, "duplicate": True}
                    continue
                projects[key] = public_inventory(inspect(manager, key))
                roots[str(root).casefold()] = key
            except (OSError, ValueError) as exc:
                projects[key] = {"project": key, "complete": False, "error": str(exc)}
        for folder, label in (("cache", "工具缓存"), ("webview", "界面缓存"),
                              ("icon-library", "图标库"), ("application-updates", "升级备份"),
                              ("runs", "全局调用记录")):
            path = plain_path(manager.data / folder)
            files, _, errors = walk(path) if path.exists() else ([], [], [])
            global_rows.append({"id": folder, "label": label, "path": str(path),
                                "bytes": sum(f["size"] for f in files), "complete": not errors})
        value = {"projects": projects, "global": global_rows, "status": "ready",
                 "bytes": sum(p.get("bytes", 0) for p in projects.values() if not p.get("duplicate")),
                 "complete": all(p.get("complete") for p in projects.values()),
                 "scanned_at": stamp()}
    except Exception as exc:
        value = {"projects": {}, "global": [], "status": "error", "error": str(exc)}
    with manager.lock:
        manager._storage_overview = value
        manager._storage_at = time.monotonic()
        manager._storage_scanning = False
