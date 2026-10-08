"""Owner-managed intake and read-only learning visibility; never approves Office evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from .learning_identity import compatibility, digest
from .policy import plain_path, check_tree
from .storage import stamp
from .workbench import Workbench


def root(manager):
    directory = plain_path(manager.data/"learning")
    check_tree(directory)
    if not directory.is_relative_to(manager.data):
        raise ValueError("Learning library must remain in the selected management data")
    return directory


def connect(manager, write=False):
    directory = root(manager)
    if write:
        directory.mkdir(parents=True, exist_ok=True)
    path = plain_path(directory/"library.sqlite3")
    if path.exists() and path.stat().st_nlink > 1:
        raise ValueError("Linked learning database is not allowed")
    return sqlite3.connect(path if write else f"file:{path.as_posix()}?mode=ro",
                           uri=not write, timeout=5)


def initialize(manager):
    with connect(manager, True) as db:
        db.execute("CREATE TABLE IF NOT EXISTS versions (id TEXT, version TEXT, status TEXT, payload TEXT, PRIMARY KEY(id,version))")
        db.execute("CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, skill TEXT, version TEXT, payload TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, fingerprint TEXT, response TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS delivery_candidates (id TEXT PRIMARY KEY, payload TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, payload TEXT)")


def preferences(manager):
    return {"auto_collect": bool(manager.store.get("learning_preferences", {}).get("auto_collect", False))}


def record_attempt(manager, command, arguments, result):
    if command != "skill_apply" or result.get("command_status") == "completed":
        return
    if not (root(manager)/"library.sqlite3").exists():
        return
    from .storage import redact
    error = result.get("error") or {}
    value = {"id": result["call_id"], "skill_id": arguments.get("skill_id", ""),
             "version": arguments.get("version", ""), "project": arguments.get("project", ""),
             "status": result.get("command_status", "outcome_unknown"),
             "reason": error.get("message") or result.get("reason", ""),
             "evidence": "managed_call_failure", "recorded_at": stamp(),
             "usage_test": os.environ.get('PPT_USAGE_TEST') == '1'}
    initialize(manager)
    with connect(manager, True) as db:
        db.execute("INSERT OR IGNORE INTO attempts VALUES (?,?)",
                   (value["id"], json.dumps(redact(value), ensure_ascii=False)))


def record_attempt_safely(manager, command, arguments, result):
    try:
        record_attempt(manager, command, arguments, result)
    except Exception as exc:
        manager.store.event("learning.feedback_failed", type(exc).__name__, status="error",
                            details={"call_id": result.get("call_id")})


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def delivery_source(manager, key):
    project, row, state = Workbench(manager).entry(key)
    key = next(k for k,v in manager.store.get('workbench_projects',{}).items()
               if v == row)
    if state.get("status") != "delivered":
        raise ValueError("Only delivered projects can enter the learning inbox")
    run = state["run"]
    paths = {
        "scene": Workbench.path(project, run["dir"]+"/scene.json"),
        "pptx": Workbench.path(project, run["candidate"]["file"]),
        "delivery": Workbench.path(project, "delivery/"+run["id"]+"/delivery.json"),
    }
    receipt = json.loads(paths["delivery"].read_text(encoding="utf-8-sig"))
    hashes = {name: file_hash(path) for name, path in paths.items()}
    if (receipt.get("status") != "passed" or receipt.get("gate", {}).get("status") != "passed"
            or receipt.get("pptx_sha256") != hashes["pptx"]
            or receipt.get("gate", {}).get("scene_sha256") != hashes["scene"]):
        raise ValueError("Delivery evidence changed; source requires review")
    return {"id": digest([state["project_id"], run["id"]]),
            "project_key": key, "project_id": state["project_id"], "run_id": run["id"],
            "label": row["label"], "paths": {k: str(p) for k, p in paths.items()},
            "hashes": hashes, "recorded_at": stamp(), "status": "awaiting_capture"}


def collect(manager, key):
    value = delivery_source(manager, key)
    initialize(manager)
    with connect(manager, True) as db:
        previous = db.execute("SELECT payload FROM delivery_candidates WHERE id=?", (value["id"],)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if old["hashes"] != value["hashes"]:
                raise ValueError("Recorded delivery has changed; existing intake is preserved")
            return old
        db.execute("INSERT INTO delivery_candidates VALUES (?,?)", (value["id"], json.dumps(value, ensure_ascii=False)))
    manager.store.event("learning.collected", "Delivered project added to learning inbox",
                        details={"project_id": value["project_id"], "run_id": value["run_id"]})
    return value


def version_status(manager, sid, ver, lifecycle, data, current):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", sid) or not re.fullmatch(r"[a-f0-9]{24}", ver):
        raise ValueError("Invalid skill identity")
    path = plain_path(root(manager)/"skills"/sid/ver/"recipe.json")
    check_tree(path)
    if not path.is_relative_to(root(manager)):
        raise ValueError("Recipe path escapes learning library")
    if json.loads(path.read_text(encoding="utf-8-sig")) != data:
        return "needs_review", "技能文件已变化"
    if data["compatibility"] != current:
        return "incompatible", "执行依赖已更新，需重新提取和验证"
    if digest(data["recipe"]) != data["recipe_sha256"] or digest(data["recipe"]["parameters"]) != data["schema_sha256"]:
        return "needs_review", "组件参数或配方已变化"
    for name, expected in data["source"].items():
        source = plain_path(name)
        check_tree(source)
        if file_hash(source) != expected:
            return "needs_review", "来源证据已变化"
    return lifecycle, ""


def status(manager):
    directory = root(manager)
    result = {"library_directory": str(directory), "initialized": (directory/"library.sqlite3").is_file(),
              "preferences": preferences(manager), "skills": [], "applications": [], "candidates": [],
              "counts": {"active": 0, "pending": 0, "needs_review": 0}}
    if not result["initialized"]:
        return result
    current = compatibility(Path(manager.package()["path"]))
    with connect(manager) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"versions", "applications", "operations"} <= tables:
            raise ValueError("Learning database schema is incomplete")
        for sid, ver, lifecycle, raw in db.execute("SELECT id,version,status,payload FROM versions ORDER BY id,version"):
            data = json.loads(raw)
            try:
                effective, reason = version_status(manager, sid, ver, lifecycle, data, current)
            except (ValueError, OSError, KeyError) as exc:
                effective, reason = "needs_review", "技能或来源证据不可用 · "+type(exc).__name__
            result["skills"].append({"skill_id": sid, "version": ver, "stored_status": lifecycle,
                "status": effective, "reason": reason, "description": data.get("description", ""),
                "parameters": data.get("recipe", {}).get("parameters", {}),
                "placement_domain": data.get("recipe", {}).get("placement_domain"),
                "layout_assumptions": data.get("recipe", {}).get("layout_assumptions", []),
                "created_at": data.get("created_at"), "source_project_id": data.get("project_id")})
        for appid, sid, ver, raw in db.execute("SELECT id,skill,version,payload FROM applications ORDER BY rowid DESC LIMIT 200"):
            app = json.loads(raw)
            result["applications"].append({"id": appid, "skill_id": sid, "version": ver,
                "project_id": app.get("project_id"), "project": app.get("project"),
                "task_id": app.get("task_id"), "status": app.get("outcome", {}).get("status", app.get("status", "not_run")),
                "reason": app.get("outcome", {}).get("reason", ""), "evidence": "recorded_outcome"})
        if "attempts" in tables:
            failures = [json.loads(raw) for raw, in db.execute("SELECT payload FROM attempts ORDER BY rowid DESC LIMIT 200")]
            result["applications"] = failures + result["applications"]
        if "delivery_candidates" in tables:
            for raw, in db.execute("SELECT payload FROM delivery_candidates ORDER BY rowid DESC LIMIT 200"):
                candidate = json.loads(raw)
                try:
                    fresh = delivery_source(manager, candidate["project_key"])
                    if fresh["id"] != candidate["id"] or fresh["hashes"] != candidate["hashes"]:
                        candidate.update(status="needs_review", reason="项目或来源版本已变化")
                except (ValueError, OSError, KeyError):
                    candidate.update(status="needs_review", reason="来源交付已变化或不可用")
                result["candidates"].append(candidate)
    result["counts"] = {
        "active": sum(r["status"] == "active_scoped" for r in result["skills"]),
        "pending": sum(r["status"] in {"candidate", "verified_scoped"} for r in result["skills"]),
        "needs_review": sum(r["status"] in {"incompatible", "needs_review"} for r in result["skills"]),
    }
    return result


def source(manager, candidate_id):
    with connect(manager) as db:
        row = db.execute("SELECT payload FROM delivery_candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise ValueError("Unknown learning source")
    saved = json.loads(row[0])
    current = delivery_source(manager, saved["project_key"])
    if saved["id"] != current["id"] or saved["hashes"] != current["hashes"]:
        raise ValueError("Source changed; capture is not available")
    scene = json.loads(Path(current["paths"]["scene"]).read_text(encoding="utf-8-sig"))
    objects = []
    for index, slide in enumerate(scene["slides"]):
        for obj in slide["objects"]:
            if (obj.get("kind") in {"text", "shape"} and not obj.get("rotation")
                    and (obj["kind"] == "text" or obj.get("geometry") in {"rect", "round_rect", "ellipse"})):
                objects.append({"slide_index": index, "id": obj["id"], "kind": obj["kind"],
                                "text": obj.get("text", ""), "bbox": obj.get("bbox")})
    return {**current, "objects": objects, "capture_entry": "rebuild_skill_capture",
            "source_scene": current["paths"]["scene"], "source_pptx": current["paths"]["pptx"],
            "source_evidence": [current["paths"]["delivery"]]}


def call(manager, op, args):
    if not manager.package()["enabled"]:
        raise ValueError("Current package is disabled")
    expected = {"status": set(), "source": {"id"}, "configure": {"auto_collect"},
                "collect": {"project"}, "disable": {"skill_id", "version"}}
    if op not in expected or set(args) != expected[op]:
        raise ValueError("Invalid learning operation or fields")
    if op == "status":
        return status(manager)
    if op == "source":
        return source(manager, args["id"])
    with manager.lock:
        if op == "configure":
            if type(args["auto_collect"]) is not bool:
                raise ValueError("auto_collect must be boolean")
            initialize(manager)
            manager.store.set("learning_preferences", args)
            manager.store.event("learning.configured", "Learning intake preference saved", details=args)
            return status(manager)
        if op == "collect":
            return collect(manager, args["project"])
        sid, ver = args["skill_id"], args["version"]
        with connect(manager, True) as db:
            changed = db.execute("UPDATE versions SET status='disabled' WHERE id=? AND version=?", (sid, ver)).rowcount
            if not changed:
                raise ValueError("Unknown skill version")
        manager.store.event("learning.disabled", "Owner disabled learned skill", details=args)
        return {"skill_id": sid, "version": ver, "status": "disabled"}
