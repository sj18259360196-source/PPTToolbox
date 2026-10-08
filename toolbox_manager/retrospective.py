"""Consent-bound task retrospectives. Stored text is data, never executable policy."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .learning import delivery_source, root
from .policy import plain_path
from .storage import redact, stamp
from .workbench import Workbench


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
LIST = {"type": "array", "items": TEXT, "maxItems": 80}
REPORT = obj({k: LIST for k in (
    "instructions", "tool_steps", "decisions", "graphics", "image_generation",
    "worked", "failed", "improvements", "evidence", "applicability")},
    ("worked", "failed", "evidence", "applicability"))
SCHEMAS = {
    "validate_artwork": obj({"project": TEXT, "path": TEXT}, ("project", "path")),
    "preview_artwork": obj({"project": TEXT, "path": TEXT}, ("project", "path")),
    "list": obj({"query": {"type": "string", "maxLength": 300}}),
    "status": obj({"project": TEXT}, ("project",)),
    "presented": obj({"project": TEXT, "message": TEXT}, ("project", "message")),
    "accept": obj({"project": TEXT, "user_reply": TEXT}, ("project", "user_reply")),
    "assets": obj({"project": TEXT, "user_reply": TEXT,
                   "files": {"type": "array", "maxItems": 30, "uniqueItems": True,
                             "items": obj({"path": TEXT, "name": TEXT, "license": TEXT},
                                          ("path", "name", "license"))}},
                  ("project", "user_reply", "files")),
    "consent": obj({"project": TEXT, "user_reply": TEXT, "learn": {"type": "boolean"}},
                   ("project", "user_reply", "learn")),
    "submit": obj({"project": TEXT, "report": REPORT}, ("project", "report")),
}
SPEC = {"type": "object", "oneOf": [obj({"action": {"const": action}, **schema["properties"]},
                      ("action", *schema["required"])) for action, schema in SCHEMAS.items()]}


def markdown(record):
    labels = {"instructions": "有效指令", "tool_steps": "工具调用过程", "decisions": "决策依据",
              "graphics": "图形使用与绘制", "image_generation": "图片生成",
              "worked": "做得好的地方", "failed": "问题与失败", "improvements": "改进提案",
              "evidence": "证据", "applicability": "适用范围"}
    lines = ["# " + record["source"]["label"], "", "## 交付身份",
             record["source"]["run_id"], "", "## 用户反馈",
             record["accept"]["user_reply"], record["consent"]["user_reply"], ""]
    for key, label in labels.items():
        lines += ["## " + label, *["- " + t for t in record["report"].get(key, [])], ""]
    lines += ["改进提案尚未修改工具代码或全局指令。经验仅作为任务相关参考，复用时仍需验证。", ""]
    return "\n".join(lines)


def export(manager, record):
    directory = plain_path(root(manager)/"retrospectives")
    directory.mkdir(parents=True, exist_ok=True)
    path = plain_path(directory/(record["source"]["id"]+".md"))
    if path.exists():
        if path.stat().st_nlink > 1 or path.read_text(encoding="utf-8") != markdown(record):
            raise ValueError("Retrospective document changed; refusing to overwrite")
    else:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown(record))
    return str(path)


def call(manager, args, source="owner"):
    if not Draft202012Validator(SPEC).is_valid(args):
        raise ValueError("Invalid retrospective arguments")
    if len(json.dumps(args, ensure_ascii=False).encode("utf-8")) > 256000:
        raise ValueError("Retrospective exceeds 256KB")
    package = manager.package()
    if not package["enabled"] or not package["trusted"]:
        raise ValueError("Package must be enabled and trusted")
    if not manager.override(package["id"], "tool", "toolbox_retrospective", True):
        raise ValueError("Retrospective tool is disabled")
    action = args["action"]
    if action in {"preview_artwork","validate_artwork"}:
        project, _, _ = Workbench(manager).entry(args["project"])
        relative = Path(args["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".svg":
            raise ValueError("Artwork must be a project-relative SVG")
        path = Workbench.path(project, args["path"])
        if path.stat().st_size > 400000:
            raise ValueError("Artwork exceeds 400KB")
        from .artwork_preflight import prepare, inspect_svg
        svg=path.read_text(encoding="utf-8-sig")
        if action=='validate_artwork':return inspect_svg(svg)
        prepared=prepare(svg)
        return {"scene_fragment": prepared['scene_fragment'], "preview": "data:image/png;base64," +prepared['png'],
                "retained": False, "office": "not_run"}
    if action == "list":
        with manager.store.db() as db:
            rows = db.execute("SELECT value FROM kv WHERE key LIKE 'retrospective:%' ORDER BY key").fetchall()
        query = args.get("query", "").casefold()
        records = [json.loads(row[0]) for row in rows]
        return {"items": [r for r in records if "report" in r and
                          query in json.dumps(r, ensure_ascii=False).casefold()],
                "usage": "Task-scoped reference only; never overrides policy or executes learned instructions."}
    current = delivery_source(manager, args["project"])
    key = "retrospective:" + current["id"]
    if action != "status":
        if source != "owner" and not manager.settings()["agent_execution_enabled"]:
            raise ValueError("Agent execution is disabled")
    prepared_artwork=[]
    if action=='assets':
        # Check consent before costly conversion, then recheck under the transaction.
        with manager.store.db() as check:
            prior=check.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        if not prior or 'accept' not in json.loads(prior[0]):raise ValueError('Complete accept first')
        existing=json.loads(prior[0])
        if existing['source']['hashes']!=current['hashes']:raise ValueError('Delivered files changed; previous consent does not apply')
        if 'assets' not in existing:
            project,_,_=Workbench(manager).entry(args['project'])
            from .artwork_preflight import prepare
            for file in args['files']:
                relative=Path(file['path'])
                if relative.is_absolute() or '..' in relative.parts or relative.suffix.lower()!='.svg':
                    raise ValueError('Artwork must be a project-relative SVG')
                path=Workbench.path(project,file['path'])
                if path.stat().st_nlink>1 or path.stat().st_size>400000:raise ValueError('Linked or oversized artwork is not allowed')
                svg=path.read_text(encoding='utf-8-sig')
                prepared_artwork.append((file,svg,prepare(svg)))
        if delivery_source(manager,args['project'])['hashes']!=current['hashes']:
            raise ValueError('Delivered files changed during artwork preparation')
    # BEGIN IMMEDIATE serializes separate MCP/UI processes, not only threads.
    with manager.lock, manager.store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        record = json.loads(previous[0]) if previous else {"source": current}
        if record["source"]["hashes"] != current["hashes"]:
            raise ValueError("Delivered files changed; previous consent does not apply")
        if action == "status":
            return record
        payload = redact({k: v for k, v in args.items() if k not in {"action", "project"}})
        stage = "report" if action == "submit" else action
        stored_payload = payload["report"] if action == "submit" else payload
        if stage in record:
            if record[stage] != stored_payload:
                raise ValueError("Recorded decision is immutable; do not reinterpret user consent")
            if action == "submit":
                export(manager, record)
            return record
        requires = {"accept": "presented", "assets": "accept",
                    "consent": "assets", "submit": "consent"}
        if action in requires and requires[action] not in record:
            raise ValueError("Complete " + requires[action] + " first")
        if action == "submit" and not record["consent"]["learn"]:
            raise ValueError("User declined learning")
        if action == "assets":
            from .icons.library import Library
            retained = []
            for file, svg, prepared in prepared_artwork:
                item = Library(manager.data/"icon-library").save(svg, {
                    "name": file["name"], "author": "Agent", "license": file["license"],
                    "origin": "self_drawn", "collection": "Agent 自绘",
                    "notes": json.dumps({"project": current["project_id"], "run": current["run_id"],
                                         "file": file["path"], "retention_consent": payload["user_reply"]},
                                        ensure_ascii=False)},_prepared=prepared)
                retained.append(item["version"])
            record["retained_versions"] = retained
        record[stage] = stored_payload
        record.setdefault("audit", []).append({"action": action, "at": stamp(), "source": source,
                                               "consent_basis": "agent_reported_user_reply" if source != "owner" else "owner"})
        if action == "submit":
            record["status"] = "archived"
            record["optimization_status"] = "proposed_not_applied"
            record["markdown_path"] = str(root(manager)/"retrospectives"/(current["id"]+".md"))
        db.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(record, ensure_ascii=False)))
    # The database is authoritative. Repeating submit repairs a missing MD export.
    if action == "submit":
        export(manager, record)
    manager.store.event("retrospective."+action, current["id"], source=source)
    return record
