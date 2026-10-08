"""Start intents approved by owner decisions or an explicitly saved owner policy."""
from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path

from .policy import PolicyDenied, plain_path, check_input, check_tree
from .storage import digest, stamp

MAX_REQUESTS = 1000


@contextlib.contextmanager
def database(manager):
    # Grants, frozen requests and owner decisions share one atomic writer lock.
    with manager.store.db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, binding TEXT UNIQUE, body TEXT)")
        db.execute("BEGIN IMMEDIATE")
        yield db


def binding(row):
    return digest(json.dumps([os.path.normcase(row["path"]),
                             sorted(os.path.normcase(p) for p in row["input_roots"])],
                            ensure_ascii=True))


def checked(record):
    key, frozen, body = record
    row = json.loads(body)
    if row["id"] != key or binding(row) != frozen:
        raise ValueError("Request fields changed; approval refused")
    return row


def save(db, row):
    db.execute("UPDATE requests SET body=? WHERE id=?", (json.dumps(row), row["id"]))


def list_requests(manager):
    # Reading the inbox must not compete with Agent execution for the writer lock.
    with manager.store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='requests'").fetchone():
            return []
        return [checked(r) for r in db.execute("SELECT id,binding,body FROM requests ORDER BY rowid DESC")]


def paths(manager, arguments):
    values = [arguments["project"], *arguments.get("references", [])]
    values += [arguments[k] for k in ("scene", "candidate") if k in arguments]
    if len(values) > 128 or any(len(v) > 8000 or any(ord(c) < 32 for c in v) for v in values):
        raise ValueError("Invalid or excessive start paths")
    if any(not Path(v).is_absolute() for v in values):raise ValueError('Start paths must be absolute')
    resolved = [plain_path(v) for v in values]
    from .project_context import ProjectContext
    project = ProjectContext(manager,resolved[0]).root
    protected = [plain_path(manager.root),plain_path(manager.package()["path"]), plain_path(manager.data)]
    if any(project.is_relative_to(p) or p.is_relative_to(project) for p in protected):
        raise PolicyDenied("Project must be separate from code and manager data")
    if project.exists() and not project.is_dir():
        raise ValueError("Project path must be a directory")
    if any(p.is_relative_to(root) for p in resolved[1:] for root in protected):
        raise PolicyDenied("Inputs must be separate from code and manager data")
    roots = sorted({os.path.normcase(str(p.parent)) for p in resolved[1:]
                    if not p.is_relative_to(project)})
    return str(project), roots


def record_start(manager, arguments):
    project, roots = paths(manager, arguments)
    row = {"id": "request-" + uuid.uuid4().hex, "label": Path(project).name,
           "path": project, "input_roots": roots, "status": "awaiting_authorization",
           "revision": 0, "reason": "Owner project authorization is required; execution is a separate setting",
           "updated_at": stamp()}
    key = binding(row)
    with database(manager) as db:
        records = [checked(r) for r in db.execute("SELECT id,binding,body FROM requests")]
        for old in records:
            if os.path.normcase(old["path"]) == os.path.normcase(project) and (old["status"] == "rejected" or old.get("archived")):
                return old
        previous = next((old for old in records if binding(old) == key), None)
        if previous and previous["status"] == "started":
            return previous
        if previous is None and len(records) >= MAX_REQUESTS:
            raise PolicyDenied("Project request capacity reached; owner maintenance required")
        grant_record = db.execute("SELECT value FROM kv WHERE key='project_authorizations'").fetchone()
        grants = json.loads(grant_record[0]) if grant_record else {}
        grant = next((v for k, v in grants.items() if os.path.normcase(k) == os.path.normcase(project)), None)
        covered = False
        if isinstance(grant, dict) and grant.get("write") is True:
            granted_roots = [plain_path(p) for p in grant.get("input_roots", [])]
            covered = all(any(Path(p).is_relative_to(r) for r in granted_roots) for p in roots)
        if covered:
            row.update(status="approved", reason="Existing owner grant covers these paths; execution remains separately controlled")
        else:
            # Read the preference under the same writer lock as requests and grants.
            setting_record = db.execute("SELECT value FROM kv WHERE key='settings'").fetchone()
            settings = json.loads(setting_record[0]) if setting_record else {}
            if (settings.get("auto_approve_project_requests") is True
                    and (grant is None or isinstance(grant, dict) and grant.get("write") is True)):
                project_path = Path(project)
                input_paths = [*arguments.get("references", [])]
                input_paths += [arguments[k] for k in ("scene", "candidate") if k in arguments]
                for value in input_paths:
                    check_input(value, project_path, [Path(p) for p in roots])
                check_tree(project_path)
                merged_roots = {os.path.normcase(str(plain_path(p))): str(plain_path(p))
                                for p in [*(grant or {}).get("input_roots", []), *roots]}
                manager.authorize_project(project, list(merged_roots.values()), connection=db,
                                          approval_mode="automatic", settings_revision=settings.get("revision"))
                covered = True
                row.update(status="approved", approval_mode="automatic",
                           approval_settings_revision=settings.get("revision"),
                           reason="Automatically approved by saved project request setting; execution remains separately controlled")
        if Path(project).exists():
            row["reason"] += "; target already exists: resume its workflow if initialized, otherwise initialize only unoccupied project folders"
        if previous:
            if covered and (previous["status"] == "awaiting_authorization" or row.get("approval_mode") == "automatic"):
                previous.update(status="approved", reason=row["reason"],
                                revision=previous["revision"] + 1, updated_at=stamp())
                if row.get("approval_mode") == "automatic":
                    previous.update(approval_mode="automatic", approval_settings_revision=row["approval_settings_revision"])
                save(db, previous)
            return previous
        db.execute("INSERT INTO requests VALUES(?,?,?)", (row["id"], key, json.dumps(row)))
    return row


def decide(manager, body):
    if (not isinstance(body, dict) or set(body) != {"id", "revision", "decision"}
            or not isinstance(body["id"], str) or type(body["revision"]) is not int
            or body["decision"] not in ("approve", "reject")):
        raise ValueError("Expected id, integer revision and approve/reject decision only")
    with database(manager) as db:
        record = db.execute("SELECT id,binding,body FROM requests WHERE id=?", (body["id"],)).fetchone()
        if record is None:
            raise ValueError("Unknown project request")
        row = checked(record)
        if row["revision"] != body["revision"] or row["status"] != "awaiting_authorization" or row.get("archived"):
            raise ValueError("Request changed; refresh before deciding")
        if any(r["status"] == "rejected" and os.path.normcase(r["path"]) == os.path.normcase(row["path"])
               for r in (checked(r) for r in db.execute("SELECT id,binding,body FROM requests"))):
            raise PolicyDenied("Owner already rejected this project")
        if body["decision"] == "approve":
            project = plain_path(row["path"])
            roots = [plain_path(p) for p in row["input_roots"]]
            if project.exists() and not project.is_dir():
                raise ValueError("Project path must be a directory")
            if any(not p.is_dir() for p in roots):
                raise ValueError("Input roots must exist before approval")
            manager.authorize_project(row["path"], row["input_roots"], connection=db)
            row.update(status="approved", reason="Owner approved project paths; execution remains separately controlled")
        else:
            row.update(status="rejected", reason="Owner rejected project authorization; do not retry or broaden roots")
        row.update(revision=row["revision"] + 1, updated_at=stamp())
        save(db, row)
        return row


def started(manager, request_id, project_id):
    with database(manager) as db:
        row = checked(db.execute("SELECT id,binding,body FROM requests WHERE id=?", (request_id,)).fetchone())
        if row["status"] == "rejected":
            raise PolicyDenied("Owner rejected project authorization")
        row.update(status="started", project_id=project_id, revision=row["revision"] + 1,
                   reason="Managed start completed", updated_at=stamp())
        save(db, row)
    return row


def archive_request(manager, body):
    """Owner-only archive of an unregistered intent; never create or delete its folder."""
    if (not isinstance(body, dict) or set(body) != {"id", "revision", "archived"}
            or not isinstance(body["id"], str) or type(body["revision"]) is not int
            or type(body["archived"]) is not bool):
        raise ValueError("请提供申请编号、版本与归档状态")
    with database(manager) as db:
        record = db.execute("SELECT id,binding,body FROM requests WHERE id=?", (body["id"],)).fetchone()
        if record is None:
            raise ValueError("申请不存在，请刷新项目列表")
        row = checked(record)
        if row["revision"] != body["revision"]:
            raise ValueError("申请已变化，请刷新后重试")
        stored = db.execute("SELECT value FROM kv WHERE key='workbench_projects'").fetchone()
        projects = json.loads(stored[0]) if stored else {}
        path_key = lambda p: os.path.normcase(os.path.normpath(p))
        if any((row.get("project_id") and row["project_id"] in {key, project.get("project_id")})
               or path_key(project["path"]) == path_key(row["path"])
               for key, project in projects.items()):
            raise ValueError("申请已登记为项目，请刷新后从项目入口操作")
        if body["archived"]:
            root = Path(row["path"])
            if manager.store.unfinished_calls(row["path"]) or (root / 'workflow/writer.lock').exists() or (root / '.ppt-toolbox-initialize.lock').exists():
                raise ValueError("项目正在启动或仍有未确认的调用，请稍后再归档")
        if bool(row.get("archived")) == body["archived"]:
            return row
        row.update(archived=body["archived"], revision=row["revision"]+1, updated_at=stamp())
        save(db, row)
    manager.store.event("project.request_archived", "Project request archive updated", source="browser",
                        details={"request_id": row["id"], "archived": row["archived"], "revision": row["revision"]})
    return row


def apply_saved_policy(manager, request_id, revision):
    """An assistant can apply an existing owner policy, never create one."""
    if not isinstance(request_id, str) or type(revision) is not int:
        raise ValueError('申请编号或版本无效')
    with database(manager) as db:
        record = db.execute('SELECT id,binding,body FROM requests WHERE id=?', (request_id,)).fetchone()
        if record is None:
            raise ValueError('申请不存在')
        row = checked(record)
        if row['revision'] != revision:
            raise ValueError('申请已变化，请重新读取')
        if row.get('archived'):
            return {'id': row['id'], 'status': row['status'], 'archived': True, 'changed': False,
                    'message': '申请已归档，需要用户先恢复'}
        if row['status'] != 'awaiting_authorization':
            return {'id': row['id'], 'status': row['status'], 'changed': False}
        siblings = [checked(r) for r in db.execute('SELECT id,binding,body FROM requests')]
        if any(r['status'] == 'rejected' and os.path.normcase(r['path']) == os.path.normcase(row['path']) for r in siblings):
            raise PolicyDenied('用户已拒绝此项目')
        record = db.execute("SELECT value FROM kv WHERE key='project_authorizations'").fetchone()
        grants = json.loads(record[0]) if record else {}
        grant = next((v for k,v in grants.items() if os.path.normcase(k) == os.path.normcase(row['path'])), None)
        if grant is not None and (not isinstance(grant, dict) or grant.get('write') is not True):
            raise PolicyDenied('项目写入授权已关闭')
        project = plain_path(row['path']); roots = [plain_path(p) for p in row['input_roots']]
        protected = [plain_path(manager.root), plain_path(manager.package()['path']), plain_path(manager.data)]
        if any(project.is_relative_to(p) or p.is_relative_to(project) for p in protected):
            raise PolicyDenied('项目不能位于程序或管理数据目录')
        if project.exists() and not project.is_dir():
            raise ValueError('项目路径不是文件夹')
        if any(not p.is_dir() or any(p.is_relative_to(d) or d.is_relative_to(p) for d in protected) for p in roots):
            raise PolicyDenied('输入目录不存在或包含受保护目录')
        check_tree(project)
        granted = [plain_path(p) for p in (grant or {}).get('input_roots', [])]
        covered = grant is not None and all(any(p.is_relative_to(g) for g in granted) for p in roots)
        setting = db.execute("SELECT value FROM kv WHERE key='settings'").fetchone()
        settings = json.loads(setting[0]) if setting else {}
        if not covered and settings.get('auto_approve_project_requests') is not True:
            return {'id': row['id'], 'status': 'awaiting_authorization', 'changed': False,
                    'message': '超出现有授权，自动审批未开启，等待用户决定'}
        if not covered:
            merged = {os.path.normcase(str(p)): str(p) for p in [*granted, *roots]}
            manager.authorize_project(project, list(merged.values()), connection=db,
                                      approval_mode='automatic', settings_revision=settings.get('revision'))
        row.update(status='approved', revision=row['revision']+1, updated_at=stamp(),
                   approval_mode='existing_grant' if covered else 'automatic',
                   approval_settings_revision=settings.get('revision'),
                   reason='Applied existing owner authorization policy; execution remains separately controlled')
        save(db, row)
        return {'id': row['id'], 'status': row['status'], 'revision': row['revision'], 'changed': True,
                'message': '已按用户授权规则批准，制作任务尚未执行'}


def next_action(row):
    if row.get("archived"):
        return "owner_restore_archived_request"
    if row["status"] != "rejected" and Path(row["path"]).is_dir():
        return "inspect_existing_project"
    return {"awaiting_authorization": "owner_review_project_request",
            "approved": "owner_check_execution_settings_then_retry_start",
            "rejected": "stop_owner_rejected_request", "started": "inspect_existing_project"}[row["status"]]
