"""Read-only project projection. Browser identifiers never accept filesystem paths."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .policy import plain_path, PolicyDenied
from .storage import digest, redact, stamp


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path):
    return digest(path.read_bytes())


def pptx_properties(path):
    from pptx import Presentation
    result = {}
    for index, slide in enumerate(Presentation(str(path)).slides):
        def walk(shapes, parent=None):
            for shape in shapes:
                row = {"shape_id": shape.shape_id, "type": int(shape.shape_type), "parent": parent,
                       "bbox_pt": [v / 12700 for v in (shape.left, shape.top, shape.width, shape.height)]}
                if shape.has_text_frame:
                    row["text"] = shape.text
                    row["runs"] = [{"text": r.text, "font_size_pt": r.font.size.pt if r.font.size else None,
                                    "font": r.font.name} for p in shape.text_frame.paragraphs for r in p.runs]
                result[f"{index}/{shape.name}"] = row
                if int(shape.shape_type) == 6:
                    walk(shape.shapes, shape.name)
        walk(slide.shapes)
    return result


class Workbench:
    def __init__(self, manager):
        self.manager = manager
        self.assets = {}
        self.cache = {}
        self.lock = threading.RLock()

    def entry(self, key):
        if not isinstance(key,str) or not key:
            raise ValueError('请指定项目编号或已登记的项目路径')
        projects = self.manager.store.get("workbench_projects", {})
        row = projects.get(key)
        if row is None:
            matches = [r for r in projects.values() if r.get('project_id') == key or
                       (Path(key).is_absolute() and plain_path(r['path']) == plain_path(key))]
            if len(matches) > 1:
                raise PolicyDenied("Ambiguous project identity; use its workbench key")
            row = matches[0] if matches else None
        if not row:
            raise PolicyDenied("Project is not registered for this workbench")
        root = plain_path(row["path"])
        path = self.path(root, "workflow/state.json")
        if not path.exists() and row.get('scope') == 'folder-project':
            from scripts.project_journal import load, manifest
            identity = load(root) or manifest(root)
            if not identity or identity['project_id'] != row['project_id']:
                raise ValueError('项目文件夹身份已变化')
            return root, row, {'project_id': row['project_id'], 'status': 'folder', 'revision': 0, 'history': []}
        stat = path.stat()
        identity = (str(path), stat.st_mtime_ns, stat.st_size)
        cache = getattr(self.manager, '_project_state_cache', {})
        state = cache.get(identity)
        if state is None:
            state = read(path)
            after = path.stat()
            if (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, stat.st_size):
                raise ValueError('项目文件正在更新，请稍后读取')
            # Workflow states may be tens of MB; retain only two recent projects.
            cache = {k:v for k,v in cache.items() if k[0]!=str(path)}
            self.manager._project_state_cache = {**dict(list(cache.items())[-1:]), identity:state}
        if state["project_id"] != row["project_id"]:
            raise ValueError("Project identity changed")
        return root, row, state

    @staticmethod
    def path(root, relative):
        p = plain_path(root / relative)
        if not p.is_relative_to(root) or (p.exists() and p.stat().st_nlink > 1):
            raise PolicyDenied("Artifact is outside the authorized project")
        return p

    def cached(self, p, reader=read):
        stat = p.stat()
        identity = (str(p), stat.st_mtime_ns, stat.st_size, reader.__name__)
        with self.lock:
            if identity not in self.cache:
                self.cache = {k: v for k, v in self.cache.items()
                              if k[0] != str(p) or (k[1], k[2]) == (stat.st_mtime_ns, stat.st_size)}
                self.cache[identity] = reader(p)
            return self.cache[identity]

    def image(self, key, root, relative, expected=None):
        p = self.path(root, relative)
        if not p.is_file():
            return {"status": "missing", "name": relative}
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise PolicyDenied("Only PNG and JPEG render artifacts may be displayed")
        sha = self.cached(p, file_hash)
        if expected and sha != expected:
            raise ValueError("Render artifact changed")
        from PIL import Image
        with Image.open(p) as im:
            size = list(im.size)
        aid = digest(key + relative + sha)
        self.assets[aid] = (key, relative, sha)
        return {"status": "available", "id": aid, "name": relative, "sha256": sha,
                "size": size, "modified_ns": p.stat().st_mtime_ns}

    def artifact(self, key, aid):
        root, _, _ = self.entry(key)
        record = self.assets.get(aid)
        if not record or record[0] != key:
            raise PolicyDenied("Unknown or cross-project artifact")
        p = self.path(root, record[1])
        raw = p.read_bytes()
        if digest(raw) != record[2]:
            raise ValueError("Artifact changed; refresh snapshot")
        return raw

    def projects(self, *, summary=False):
        result = []
        for key in self.manager.store.get("workbench_projects", {}):
            try:
                root, row, state = self.entry(key)
                if state['status'] == 'folder':
                    from .project_inventory import lifecycle
                    result.append({**row, 'id':key, 'status':'folder', 'readonly':True, 'gallery':{'items':[]},
                                   'work_directory':row['path'], 'delivery_directory':None, 'lifecycle':lifecycle(Path(row['path']))})
                    continue
                from .project_inventory import lifecycle
                life = lifecycle(Path(row['path']))
                if summary:
                    previews = {'versions': [], 'deferred': True, 'search_text': ''}
                    delivery = life.get('delivery') or state.get('delivery')
                    delivery_directory = str(self.path(root, delivery)) if delivery else None
                    if life.get('delivery'):
                        delivery_directory = str(Path(delivery_directory).parent)
                else:
                    from .project_context import ProjectContext
                    from .project_gallery import gallery
                    context = ProjectContext(self.manager, row['path']).snapshot()
                    previews = gallery(self.manager, key)
                    delivery_directory = str(Path(row['path']) / Path(life['delivery']).parent) if life.get('delivery') else context['current_delivery']
                result.append({"id": key, "label": row["label"], "project_id": state["project_id"],
                               "status": state["status"], "readonly": not row.get("editable", False),
                               "category": row.get("category", "historical"),
                               "archived": row.get("archived", False),
                               "metadata_revision": row.get("metadata_revision", 0),
                               "parent_id": row.get("parent_id"), "lifecycle": life,
                               "updated_at": row.get("updated_at"),
                               "gallery":previews,"work_directory":row['path'],
                               "delivery_directory":delivery_directory})
            except (ValueError, OSError) as e:
                result.append({"id": key, "label": key, "error": str(e), "readonly": True})
        return result

    def preferences(self):
        return self.manager.store.get("workbench_preferences", {})

    def save_preferences(self, body):
        if not isinstance(body, dict) or set(body) != {"project"}:
            raise ValueError("Only the selected project can be saved")
        key = body["project"]
        if not isinstance(key, str) or (key and key not in self.manager.store.get("workbench_projects", {})):
            raise ValueError("Selected project is not registered")
        value = {"project": key}
        self.manager.store.set("workbench_preferences", value)
        return value

    def request(self, key, request_id):
        self.entry(key)
        request_id = self.manager.store.get("workbench_alias:"+request_id, request_id)
        result = self.manager.store.get("workbench_request:" + request_id)
        if not result or result["project"] != key:
            raise ValueError("Unknown request")
        public = {k: v for k, v in result.items() if k not in {"payload", "view_files"}}
        root, _, state = self.entry(key)
        public["images"] = [self.image(key, root, im["name"], im["sha256"]) for im in public.get("images", [])]
        if public["status"] == "ready" and result.get("payload", {}).get("identity", {}).get("revision") != state["revision"]:
            public["status"] = "stale_candidate"
        if public["status"] == "running" and request_id not in getattr(self, "running", set()):
            public["status"] = "outcome_unknown"
        return public

    def write(self, body):
        with self.lock:
            return self._write(body)

    def _write(self, body):
        required = {"project", "request_id", "action", "identity"}
        if not isinstance(body, dict) or not required <= body.keys():
            raise ValueError("Missing request identity")
        if body.keys() - required - {"slide", "region", "changes", "reason", "candidate_request", "observation"}:
            raise ValueError("Unknown write field")
        key, rid = body["project"], body["request_id"]
        if not isinstance(rid, str) or not re.fullmatch(r"[a-f0-9]{32}", rid):
            raise ValueError("Invalid persistent request id")
        root, row, state = self.entry(key)
        if row.get("editable") is not True or row.get("scope") != "phase-06-test":
            raise PolicyDenied("Historical project is read-only")
        from .policy import authorize
        authorize(self.manager, root)
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False)
        request_hash = digest(encoded)
        alias = self.manager.store.get("workbench_alias:"+rid)
        if alias:
            original = self.manager.store.get("workbench_request:"+alias)
            same = {k: v for k, v in original["payload"].items() if k != "request_id"}
            if same != {k: v for k, v in body.items() if k != "request_id"}:
                raise ValueError("Request id reused with different payload")
            return self.request(key, alias)
        previous = self.manager.store.get("workbench_request:" + rid)
        if previous:
            if previous["payload_hash"] != request_hash:
                raise ValueError("Request id reused with different payload")
            return self.request(key, rid)
        content = {k: v for k, v in body.items() if k != "request_id"}
        with self.manager.store.db() as db:
            prior = [json.loads(r[0]) for r in db.execute("SELECT value FROM kv WHERE key LIKE 'workbench_request:%'")]
        prior.sort(key=lambda r: (r.get("status") in {"ready", "adopted"}, r.get("started_at", "")), reverse=True)
        for existing in prior:
            same = {k: v for k, v in existing.get("payload", {}).items() if k != "request_id"}
            if same == content:
                self.manager.store.set("workbench_alias:"+rid, existing["request_id"])
                return self.request(key, existing["request_id"])
        current = self.snapshot(key)
        identity = {k: current[k] for k in ("project_id", "revision", "state_sha256", "scene_sha256", "pptx_sha256", "run")}
        if body["identity"] != identity:
            raise ValueError("Draft conflict: baseline changed; reload and confirm a new diff")
        if not state.get("active_task"):
            raise ValueError("No active task; use existing managed workflow to recover")
        action = body["action"]
        reserve, candidate_count = 0, 0
        if action == "generate":
            from .contracts import validate
            args = {"project": str(root), "operation_id": "ui-"+rid[:28],
                    "base_revision": current["revision"], "scene_sha256": current["scene_sha256"],
                    "pptx_sha256": current["pptx_sha256"],
                    **{k: body[k] for k in ("slide", "region", "changes", "reason")}}
            validate("patch", args, self.manager.root)
            page = next((p for p in current["pages"] if p["id"] == args["slide"]), None)
            if not page:
                raise ValueError("Unknown page")
            seen = set()
            for change in args["changes"]:
                if change["id"] in seen:
                    raise ValueError("One operation per object per candidate; stage a different object")
                seen.add(change["id"])
                target = next((o for o in page["objects"] if o["id"] == change["id"]), None)
                if not target or target["scene"]["kind"] not in {"text", "shape"} or target["parent"]:
                    raise ValueError("Only independent native text and ordinary shapes are editable")
                if target["scene"].get("runs") or target["scene"].get("paragraphs"):
                    raise ValueError("Rich text is not supported by this form")
                if change["op"] in {"text.set", "text.style"} and (
                        len((target["pptx"] or {}).get("runs", [])) != 1
                        or any(c in change.get("text", "") for c in "\r\n\v")):
                    raise ValueError("Only single-run single-paragraph text is supported")
                if change["op"] not in {"text.set", "text.style", "fill.set", "geometry.set"}:
                    raise ValueError("Unsupported UI operation")
                if change["op"] == "text.style" and set(change["style"]) - {"font_size_pt", "color"}:
                    raise ValueError("Unsupported UI style")
            reserve, candidate_count = 2*len(current["pages"]), 1
        elif action == "adopt":
            previous = self.manager.store.get("workbench_request:" + body.get("candidate_request", ""))
            if not previous or previous["project"] != key or previous["status"] != "ready":
                raise ValueError("No eligible completed comparison")
            if previous["payload"]["identity"] != identity:
                raise ValueError("Comparison baseline is stale")
            obs = body.get("observation", {})
            if set(obs) != {"note", "reviewer", "confirmed"} or obs["confirmed"] is not True or not obs["note"].strip():
                raise ValueError("Explicit observation required")
            if obs["reviewer"] not in {"browser-user", "test-agent"}:
                raise ValueError("Observer provenance required")
            args = {"project": str(root), "operation_id": "ua-"+rid[:28],
                    "trial_id": previous["trial_id"], "comparison_id": previous["comparison_id"],
                    "observation": {"status": "passed", "note": obs["note"], "reviewer": obs["reviewer"],
                                    "viewed_files": previous["view_files"]}}
        else:
            raise ValueError("Unsupported workbench action")
        record = {"project": key, "request_id": rid, "payload_hash": request_hash, "payload": body,
                  "status": "running", "started_at": stamp(), "action": action}
        with self.manager.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM kv WHERE key=?", ("workbench_request:"+rid,)).fetchone():
                raise ValueError("Request is already registered; query original id")
            budget = json.loads(db.execute("SELECT value FROM kv WHERE key='workbench_budget'").fetchone()[0])
            if budget["candidates"] + candidate_count > budget["max_candidates"] or (
                    budget["reserved_exports"] + reserve > budget["max_exports"] - budget["final_reserve"]):
                raise ValueError("Phase06 budget exhausted; final reserve protected")
            pending = db.execute("SELECT value FROM kv WHERE key LIKE 'workbench_request:%'").fetchall()
            if any(json.loads(r[0])["status"] in {"running", "outcome_unknown"} for r in pending):
                raise ValueError("An unresolved request exists; inspect it before another write")
            budget["candidates"] += candidate_count
            budget["reserved_exports"] += reserve
            db.execute("UPDATE kv SET value=? WHERE key='workbench_budget'", (json.dumps(budget),))
            db.execute("INSERT INTO kv VALUES(?,?)", ("workbench_request:"+rid, json.dumps(record)))
        with self.lock:
            if not hasattr(self, "running"):
                self.running = set()
            self.running.add(rid)
        threading.Thread(target=self._execute, args=(root, record, args), daemon=True).start()
        return self.request(key, rid)

    def _execute(self, root, record, args):
        rid = record["request_id"]
        try:
            result = self.manager.execute_workflow("patch" if record["action"] == "generate" else "adopt",
                                                   args, source="ui", rpc_id=rid)
            record["call_id"] = result.get("call_id")
            record["result"] = {k: result.get(k) for k in ("command_status", "local_status", "workflow_status", "error")}
            if result.get("command_status") != "completed":
                record["status"] = result.get("command_status", "outcome_unknown")
            elif record["action"] == "adopt":
                record["status"] = "adopted"
            else:
                record["trial_id"] = args["operation_id"]
                cid = "uc-"+rid[:28]
                compared = self.manager.execute_workflow("compare", {"project": str(root), "operation_id": cid,
                                                        "trial_id": args["operation_id"]}, source="ui", rpc_id=rid)
                record["comparison_id"] = cid
                record["compare_call_id"] = compared.get("call_id")
                record["result"] = {k: compared.get(k) for k in ("command_status", "local_status", "error")}
                record["view_files"] = compared.get("must_view_files", [])
                if compared.get("command_status") == "completed":
                    cr = read(self.path(root, f"trials/{cid}/record.json"))
                    record["status"] = "ready" if cr.get("outside_regression") == "passed" else "needs_review"
                    record["checks"] = {k: cr.get(k) for k in ("structural_consistency", "outside_regression", "status")}
                    record["images"] = [self.image(record["project"], root, str(Path(f).relative_to(root)))
                                        for f in record["view_files"] if Path(f).suffix == ".png"]
                else:
                    record["status"] = compared.get("command_status", "outcome_unknown")
        except Exception as e:
            record["status"] = "outcome_unknown"
            record["error"] = type(e).__name__ + ": " + str(e)
        finally:
            record["ended_at"] = stamp()
            self.manager.store.set("workbench_request:"+rid, record)
            self.running.discard(rid)

    def snapshot(self, key, run_id=None):
        root, row, state = self.entry(key)
        from .project_inventory import lifecycle
        if lifecycle(root).get("history_cleaned"):
            raise ValueError("该项目已完结并清理制作历史。请在项目页打开保留的成品")
        state_bytes = self.path(root, "workflow/state.json").read_bytes()
        if json.loads(state_bytes.decode("utf-8-sig")) != state:
            raise ValueError("Snapshot changed before read; refresh")
        state_sha = digest(state_bytes)
        current = state.get("run") or {}
        current_id = Path(current.get("dir", "")).name
        runs = sorted(set(row.get("runs", []) + ([current_id] if current_id else [])))
        run_id = run_id or current_id
        if not run_id:
            payload = {"project": key, "project_id": state["project_id"], "revision": state["revision"],
                       "state_sha256": state_sha, "run": "", "runs": runs, "historical": False,
                       "status": state["status"], "task": {k: v for k, v in (state.get("active_task") or {}).items()
                                                          if k in {"id", "kind"}},
                       "readonly": True, "scene_sha256": None, "pptx_sha256": None, "canvas": state["canvas"],
                       "pages": [{"id": p["id"], "index": p["index"], "objects": [],
                                  "regions": (p.get("plan") or {}).get("regions", []),
                                  "planning_state": p.get("planning_state","valid" if p.get("plan") else "unplanned"),
                                  "images": {"reference": self.image(key, root, p["reference"], p.get("sha256")),
                                             "candidate": {"status": "missing"}}} for p in state["pages"]],
                       "events": [], "trials": [], "checks": {}, "history": redact(state.get("history", [])[-60:]),
                       "adoptions": {}, "budget": self.manager.store.get("workbench_budget")}
            payload["cursor"] = digest(json.dumps(payload, sort_keys=True))
            payload["read_at"] = stamp()
            return payload
        if run_id not in runs or not re.fullmatch(r"run-\d{4}", run_id):
            raise ValueError("Run is not registered")
        scene_file = self.path(root, f"runs/{run_id}/scene.json")
        scene_bytes = scene_file.read_bytes()
        scene = json.loads(scene_bytes.decode("utf-8-sig"))
        scene_sha = digest(scene_bytes)
        recorded_run = current if run_id == current_id else next(
            (r for r in state.get("old_runs", []) if r.get("id") == run_id), {})
        frozen_file = self.path(root, f"runs/{run_id}/frozen-inputs.json")
        frozen = recorded_run.get("frozen") or (self.cached(frozen_file) if frozen_file.exists() else {})
        if frozen.get("scene.json") and frozen["scene.json"] != scene_sha:
            raise ValueError("Frozen scene changed")
        pptx_rel = recorded_run.get("candidate", {}).get("file")
        if not pptx_rel:
            candidates = sorted(self.path(root, f"runs/{run_id}").glob("candidate-*/candidate.pptx"))
            pptx_rel = candidates[-1].relative_to(root).as_posix() if candidates else None
        pptx = self.path(root, pptx_rel) if pptx_rel else None
        pptx_sha = self.cached(pptx, file_hash) if pptx and pptx.exists() else None
        expected_pptx = recorded_run.get("candidate", {}).get("sha256")
        if expected_pptx and pptx_sha != expected_pptx:
            raise ValueError("Frozen candidate changed")
        actual = {}
        if pptx and pptx.exists():
            actual = self.cached(pptx, pptx_properties)
        pages = []
        directories = row.get("directories", {}).get(run_id, {})
        for index, slide in enumerate(scene["slides"], 1):
            page = next((p for p in state["pages"] if p["id"] == slide["id"]), {})
            reference = page.get("reference", slide["reference"])
            images = {"reference": self.image(key, root, reference, frozen.get(reference) or page.get("sha256"))}
            receipt_path = self.path(root, directories.get("candidate", f"gate-office-{run_id}")+"/office-render.json")
            if recorded_run.get("render"):
                receipt_path = self.path(root, recorded_run["render"]["file"])
                expected_receipt = recorded_run["render"].get("sha256")
                if expected_receipt and (not receipt_path.exists()
                        or self.cached(receipt_path, file_hash) != expected_receipt):
                    raise ValueError("Frozen render receipt changed")
            if not receipt_path.exists():
                receipt_path = self.path(root, f"runs/{run_id}/office/office-render.json")
            receipt = self.cached(receipt_path) if receipt_path.exists() else {}
            rendered = next((s for s in receipt.get("slides", []) if s.get("index") == index), None)
            if rendered and receipt.get("pptx_sha256") == pptx_sha:
                relative = (receipt_path.parent / rendered["file"]).relative_to(root).as_posix()
                images["candidate"] = self.image(key, root, relative, rendered.get("sha256"))
            else:
                images["candidate"] = {"status": "missing", "reason": "No matching Office receipt"}
            for comp_path in sorted(self.path(root, f"runs/{run_id}").glob("comparisons-*/deck-comparison.json"), reverse=True):
                comp_path = self.path(root, comp_path.relative_to(root))
                comp = self.cached(comp_path)
                if comp.get("pptx_sha256") != pptx_sha or comp.get("scene_sha256") != scene_sha:
                    continue
                cs = next((v for v in comp.get("slides", []) if v.get("index") == index), None)
                if not cs:
                    continue
                comparison_path = self.path(root, (comp_path.parent/cs["comparison_json"]).relative_to(root))
                if self.cached(comparison_path, file_hash) != cs["comparison_json_sha256"]:
                    raise ValueError("Comparison record changed")
                details = self.cached(comparison_path)
                if (details.get("reference_sha256") != images["reference"].get("sha256")
                        or details.get("render_sha256") != images["candidate"].get("sha256")):
                    continue
                full = next((v for v in details.get("regions", []) if v["region"] == "full"), None)
                if full:
                    images["reference_difference"] = self.image(key, root, str(
                        (comparison_path.parent/full["absolute_difference"]).relative_to(root)),
                        full["absolute_difference_sha256"])
                break
            for label, directory in (("edit", f"edit-{run_id}"),
                                     ("edit_baseline", f"edit-baseline-{run_id}"),
                                     ("rebuild", f"rebuild-{run_id}/office")):
                directory = directories.get(label, directory)
                image_rel = f"{directory}/slide-{index:03}.png"
                images[label] = {"status": "missing", "reason": "No version-bound receipt"}
                if label == "edit":
                    receipt_file = self.path(root, directory+"/edit-readback.json")
                    supplemental = self.cached(receipt_file) if receipt_file.exists() else {}
                    render = next((v for v in supplemental.get("renders", []) if v["file"] == f"slide-{index:03}.png"), None)
                    if supplemental.get("source_sha256") == pptx_sha and render:
                        images[label] = self.image(key, root, image_rel, render["sha256"])
                else:
                    receipt_file = self.path(root, directory+"/office-render.json")
                    supplemental = self.cached(receipt_file) if receipt_file.exists() else {}
                    render = next((v for v in supplemental.get("slides", []) if v.get("index") == index), None)
                    expected_pptx = pptx_sha
                    if label == "rebuild":
                        diff_file = self.path(root, str(Path(directory).parent/"diff.json"))
                        diff = self.cached(diff_file) if diff_file.exists() else {}
                        inputs = diff.get("inputs", {})
                        expected_pptx = inputs.get("right_pptx", {}).get("sha256") if inputs.get("left_pptx", {}).get("sha256") == pptx_sha else None
                    if expected_pptx and supplemental.get("pptx_sha256") == expected_pptx and render:
                        images[label] = self.image(key, root, image_rel, render["sha256"])
            preceding = [r for r in runs if r < run_id]
            if preceding:
                previous = preceding[-1]
                old_receipt_path = self.path(root, row.get("directories", {}).get(previous, {}).get(
                    "candidate", f"gate-office-{previous}")+"/office-render.json")
                if old_receipt_path.exists():
                    old_receipt = self.cached(old_receipt_path)
                    old_slide = next((s for s in old_receipt.get("slides", []) if s.get("index") == index), None)
                    old_candidates = list(self.path(root, f"runs/{previous}").glob("candidate-*/candidate.pptx"))
                    if old_slide and any(self.cached(self.path(root, f.relative_to(root)), file_hash)
                                         == old_receipt.get("pptx_sha256") for f in old_candidates):
                        images["design_baseline"] = self.image(key, root, str(
                            (old_receipt_path.parent/old_slide["file"]).relative_to(root)), old_slide["sha256"])
            objects = []

            def walk(items, parent=None):
                for obj in items:
                    oid = obj["id"]
                    objects.append({"id": oid, "parent": parent, "scene": obj,
                                    "pptx": actual.get(f"{index-1}/{oid}"),
                                    "office": [v for v in receipt.get("text_bounds", [])
                                               if v.get("id") == oid and v.get("slide") == index],
                                    "source": {"scene": f"runs/{run_id}/scene.json", "pptx": pptx_rel,
                                               "office": str(receipt_path.relative_to(root)) if receipt else None}})
                    walk(obj.get("children", []), oid)
            walk(slide["objects"])
            pages.append({"id": slide["id"], "index": index, "objects": objects, "images": images,
                          "regions": (page.get("plan") or {}).get("regions", []),
                          "planning_state": page.get("planning_state","valid" if page.get("plan") else "recovery_blocked")})
        trials = []
        trials_root = self.path(root, "trials")
        for f in sorted(trials_root.glob("*/record.json")) if trials_root.exists() else []:
            tr = self.cached(self.path(root, f.relative_to(root)))
            summary = {k: tr.get(k) for k in ("operation_id", "kind", "status", "base_revision",
                                             "ended_at", "changes", "trial_id", "outside_regression", "call_id",
                                             "slide", "slide_index", "object_ids", "reason")}
            if tr.get("kind") == "patch":
                readbacks = []
                for name in ("baseline-readback.json", "readback.json"):
                    rb = self.path(root, (f.parent/name).relative_to(root))
                    if rb.exists() and self.cached(rb, file_hash) == tr.get("files", {}).get(name):
                        readbacks.append(self.cached(rb))
                if len(readbacks) == 2:
                    summary["office_changes"] = [{
                        "id": oid, "source": "Persisted PowerPoint baseline/readback; not scene expectation",
                        "before": next((v for v in readbacks[0].get("objects", [])
                                        if v.get("name") == oid and v.get("slide") == tr.get("slide_index")), None),
                        "after": next((v for v in readbacks[1].get("objects", [])
                                       if v.get("name") == oid and v.get("slide") == tr.get("slide_index")), None),
                    } for oid in tr.get("object_ids", [])]
            trials.append(summary)
        events = []
        seen_calls = set()
        for e in self.manager.store.logs(limit=200):
            if e.get("details", {}).get("project") == str(root):
                d = e["details"]
                cid = d.get("call_id", str(e["id"]))
                if cid in seen_calls:
                    continue
                seen_calls.add(cid)
                events.append({**{k: e[k] for k in ("id", "time", "source", "action", "status", "message")},
                               "call_id": cid, **{k: d.get(k) for k in
                                                 ("tool_id", "task_id", "run_id", "command_status", "revision_before", "revision_after")}})
        checks = {}
        for label, record in row.get("records", {}).items():
            p = plain_path(record["path"])
            if file_hash(p) != record["sha256"]:
                raise ValueError("Registered evidence changed")
            checks[label] = {"source": str(p), "sha256": record["sha256"], "data": redact(self.cached(p)),
                             "scope": "historical evidence; not a new verification"}
        applications = checks.get("skill_route", {}).get("data", {}).get("applications", [])
        for application in applications:
            tid = application.get("trial_id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
                continue
            trpath = self.path(root, f"trials/{tid}/record.json")
            if not trpath.exists():
                continue
            tr = self.cached(trpath)
            if tr.get("project_id") != state["project_id"]:
                continue
            for page in pages:
                for obj in page["objects"]:
                    if obj["id"] in tr.get("object_ids", []):
                        obj["skill"] = {k: application.get(k) for k in ("skill_id", "version", "use_id", "classification")}
                        obj["skill"]["scope"] = "Historical recorded use; not a new execution verification"
                        obj["skill"]["recorded_project_uses"] = len({
                            a.get("use_id") for a in applications
                            if a.get("use_id") and a.get("skill_id") == application.get("skill_id")
                            and a.get("version") == application.get("version")})
                        recipe = checks.get("skill_version", {}).get("data", {})
                        if recipe.get("version") == application.get("version") and recipe.get("skill_id") == application.get("skill_id"):
                            lifecycle = checks.get("skill_lifecycle", {}).get("data", {}).get("reactivated", {})
                            obj["skill"]["historical_activation"] = lifecycle.get("status")
                            obj["skill"]["tested_cases"] = [{k: c.get(k) for k in ("project_id", "run_id", "status", "values_hash")}
                                                           for c in lifecycle.get("tested_cases", [])]
                            obj["skill"]["edit_depth"] = recipe.get("recipe", {}).get("edit_depth")
                            obj["skill"]["layout_assumptions"] = recipe.get("recipe", {}).get("layout_assumptions")
                            obj["skill"]["task_route"] = next((r.get("decision") for r in
                                checks.get("skill_route", {}).get("data", {}).get("routes", [])
                                if r.get("task_id") == application.get("task_id")), None)
        for label, relative in (("rebuild", f"rebuild-{run_id}/diff.json"),):
            p = self.path(root, relative)
            if p.exists():
                checks[label] = redact(self.cached(p))
        if digest(self.path(root, "workflow/state.json").read_bytes()) != state_sha:
            raise ValueError("Snapshot changed during read; refresh")
        if file_hash(scene_file) != scene_sha or (pptx and file_hash(pptx) != pptx_sha):
            raise ValueError("Scene/PPTX changed during read; refresh")
        payload = {"project": key, "project_id": state["project_id"], "revision": state["revision"],
                   "state_sha256": state_sha, "run": run_id, "runs": runs, "historical": run_id != current_id,
                   "status": state["status"], "task": {k: v for k, v in (state.get("active_task") or {}).items()
                                                      if k in {"id", "kind", "slide", "region"}},
                   "readonly": not row.get("editable", False) or run_id != current_id or not state.get("active_task"),
                   "scene_sha256": scene_sha, "pptx_sha256": pptx_sha, "canvas": scene["canvas"],
                   "pages": pages, "events": events, "trials": trials, "checks": checks,
                   "history": redact(state.get("history", [])[-60:]),
                   "adoptions": redact(state.get("local_adoptions", {})),
                   "budget": self.manager.store.get("workbench_budget") if row.get("editable") else None}
        payload["cursor"] = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        payload["read_at"] = stamp()
        return payload
