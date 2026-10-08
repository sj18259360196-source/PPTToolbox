"""Project view metadata, separate from workflow state and execution grants."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .storage import digest, stamp


def mutate(store, operation):
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        old = connection.execute("SELECT value FROM kv WHERE key='workbench_projects'").fetchone()
        rows = json.loads(old[0]) if old else {}
        result = operation(rows)
        encoded = json.dumps(rows, ensure_ascii=False)
        if not old or encoded != old[0]:
            connection.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               ("workbench_projects", encoded))
    return result


def directory(manager):
    """Registered text index only. Never open a project or start an inventory scan."""
    from .requests import list_requests
    rows = []
    for key, row in manager.store.get('workbench_projects', {}).items():
        cached = row.get('directory', {})
        rows.append({**{k: row.get(k) for k in ('project_id','label','path','category','archived',
                     'parent_id','updated_at')}, 'id':key, 'metadata_revision':row.get('metadata_revision',0),
                     'work_directory':row['path'], 'status':cached.get('status','registered'),
                     'lifecycle':cached.get('lifecycle',{}), 'has_delivery':cached.get('has_delivery',False),
                     'current_file':cached.get('current_file'), 'readonly':not row.get('editable',False)})
    requests = list_requests(manager)
    # Tool heartbeats and observation timestamps do not invalidate the directory.
    order = _list_order({r['id']: r for r in rows}, requests, manager.store.get('project_list_order', {}))
    revision = digest(json.dumps({'rows':[{k:v for k,v in r.items() if k!='updated_at'} for r in rows],
                                  'requests':requests, 'order':order}, sort_keys=True, ensure_ascii=False))
    return {'rows':rows, 'requests':requests, 'revision':revision, 'order':order}


def _list_order(projects, requests, saved):
    """One text-only order spanning projects and unregistered start intents."""
    path_key = lambda p: os.path.normcase(os.path.normpath(p))
    identities = set(projects) | {r.get('project_id') for r in projects.values()}
    paths = {path_key(r['path']) for r in projects.values()}
    entries = list(projects)
    for request in requests:
        linked = request['project_id'] in identities if request.get('project_id') else path_key(request['path']) in paths
        if not linked:
            entries.append('request:' + request['id'])
    ids = [key for key in saved.get('ids', []) if key in entries]
    known = set(ids)
    ids.extend(key for key in entries if key not in known)
    return {'revision': saved.get('revision', 0), 'ids': ids}


def reorder(manager, body):
    if (not isinstance(body, dict) or set(body) != {'revision','id','relative_id','placement'}
            or type(body['revision']) is not int or body['placement'] not in {'before','after'}
            or not isinstance(body['id'], str) or not isinstance(body['relative_id'], str)):
        raise ValueError('排序参数无效')
    from .requests import database, checked
    with database(manager) as db:
        read = lambda key: db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        record = read('workbench_projects'); projects = json.loads(record[0]) if record else {}
        record = read('project_list_order'); saved = json.loads(record[0]) if record else {}
        requests = [checked(r) for r in db.execute('SELECT id,binding,body FROM requests')]
        order = _list_order(projects, requests, saved)
        if order['revision'] != body['revision']:
            raise ValueError('项目顺序已变化，请刷新后重试')
        moving, relative = body['id'], body['relative_id']
        if moving == relative or moving not in order['ids'] or relative not in order['ids']:
            raise ValueError('项目列表已变化，请刷新后重试')
        parent = lambda key: projects.get(key, {}).get('parent_id') if projects.get(key, {}).get('parent_id') in projects else None
        if parent(moving) != parent(relative):
            raise ValueError('只能调整同级项目的顺序')
        ids = [key for key in order['ids'] if key != moving]
        ids.insert(ids.index(relative) + (body['placement'] == 'after'), moving)
        result = {'revision': order['revision']+1, 'ids': ids}
        db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   ('project_list_order', json.dumps(result)))
    return result


def cache_summary(manager, key, workflow=None):
    from .workbench import Workbench
    from .project_inventory import lifecycle
    if workflow is None:
        root, row, workflow = Workbench(manager).entry(key)
    else:
        row = manager.store.get('workbench_projects', {})[key]
        root = Path(row['path'])
    life = lifecycle(root)
    current = life.get('delivery')
    delivery = workflow.get('delivery')
    if not current and isinstance(delivery,str):
        current = delivery if delivery.lower().endswith('.pptx') else delivery.rstrip('/\\')+'/editable.pptx'
    value = {'status':workflow.get('status','folder'), 'lifecycle':life,
             'has_delivery':bool(current), 'current_file':current}
    def change(rows):
        if key in rows and rows[key]['path']==row['path']:
            rows[key]['directory'] = value
    mutate(manager.store, change)


def register(manager, project, call_id, source):
    """Called only after an authorized, completed workflow operation."""
    root = Path(project).resolve()
    state = json.loads((root / "workflow/state.json").read_text(encoding="utf-8-sig"))
    project_id = state["project_id"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("Missing project identity")

    def update(rows):
        for key, row in rows.items():
            if os.path.normcase(os.path.normpath(row["path"])) == os.path.normcase(str(root)):
                if row["project_id"] != project_id:
                    raise ValueError("Registered path now has a different project identity")
                row.update(last_call_id=call_id, updated_at=stamp())
                return key
        for key,row in rows.items():
            if row['project_id']==project_id and not Path(row['path']).exists():
                row.setdefault('path_history',[]).append({'path':row['path'],'until':stamp()})
                row.update(path=str(root),last_call_id=call_id,updated_at=stamp())
                return key
        key = "agent-" + digest(str(root).casefold() + "\0" + project_id)[:24]
        if key in rows:
            raise ValueError("Project registry key collision")
        rows[key] = dict(path=str(root), project_id=project_id, label=root.name,
                         category="agent", archived=False, metadata_revision=0,
                         editable=False, scope="managed-agent-view", origin=source,
                         created_at=stamp(), updated_at=stamp(), last_call_id=call_id)
        return key

    key = mutate(manager.store, update)
    cache_summary(manager, key, state)
    from scripts.project_journal import ensure
    ensure(root, project_id, root.name)
    manager.store.event("project.registered", "Managed project view refreshed",
                        source=source, details={"project": str(root), "project_id": project_id,
                                                "view_id": key, "call_id": call_id})
    return key


def update_metadata(manager, payload):
    required = {"id", "revision", "label", "category", "archived"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {"parent_id"}:
        raise ValueError("Expected id, revision, label, category and archived")
    for key, limit in (("label", 120), ("category", 48)):
        value = payload[key]
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid " + key)
    if type(payload["archived"]) is not bool or type(payload["revision"]) is not int:
        raise ValueError("Invalid metadata types")
    from .workbench import Workbench
    Workbench(manager).entry(payload["id"])

    def update(rows):
        row = rows[payload["id"]]
        if row.get("metadata_revision", 0) != payload["revision"]:
            raise ValueError("Project metadata changed; refresh before saving")
        if "parent_id" in payload:
            parent = payload["parent_id"]
            if parent is not None and (not isinstance(parent, str) or parent not in rows):
                raise ValueError("上级项目不存在")
            if parent and not Path(row['path']).resolve().is_relative_to(Path(rows[parent]['path']).resolve()):
                raise ValueError('项目层级由真实文件夹决定，请在上级项目内新建子项目')
            seen = {payload["id"]}
            current = parent
            while current:
                if current in seen:
                    raise ValueError("项目分组不能互相包含")
                seen.add(current)
                current = rows.get(current, {}).get("parent_id")
            row["parent_id"] = parent
        row.update(label=payload["label"].strip(), category=payload["category"].strip(),
                   archived=payload["archived"], metadata_revision=payload["revision"] + 1)
        return {"id": payload["id"], "revision": row["metadata_revision"]}

    result = mutate(manager.store, update)
    from scripts.project_journal import ensure, update as update_record
    root, row, _ = Workbench(manager).entry(payload['id'])
    ensure(root, row['project_id'], row['label'])
    update_record(root, {'label': row['label'], 'category': row['category'], 'archived': row['archived']},
                  kind='project.metadata', source='human')
    from .project_inventory import invalidate
    invalidate(manager)
    manager.store.event("project.metadata", "Project classification updated", source="browser",
                        details={**result, "archived": payload["archived"]})
    return result
