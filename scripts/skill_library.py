"""Isolated, immutable recipe versions and evidence-derived scoped lifecycle."""
import json
import os
import sqlite3
from pathlib import Path

from common import read_json, write_json, sha256
from skill_recipe import capture, compile_recipe, digest, identifier
from workflow_store import load, locked, under, now
from toolbox_manager.policy import plain_path, check_tree
from toolbox_manager.learning_identity import DEPENDENCIES, compatibility as dependency_identity

ROOT = Path(__file__).resolve().parents[1]
def compatibility():
    return dependency_identity(ROOT)


def library_root():
    value = os.environ.get("PPT_MANAGED_LEARNING_ROOT")
    if not value:
        raise ValueError("Managed learning context unavailable")
    root = plain_path(value)
    if root.is_relative_to(ROOT):
        raise ValueError("Learning data must remain outside package")
    check_tree(root)
    return root


def database(root):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root/"library.sqlite3", timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS versions (id TEXT, version TEXT, status TEXT, payload TEXT, PRIMARY KEY(id,version))")
    db.execute("CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, skill TEXT, version TEXT, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, fingerprint TEXT, response TEXT)")
    db.commit()
    return db


def version(db, sid, ver):
    identifier(sid)
    row = db.execute("SELECT status,payload FROM versions WHERE id=? AND version=?", (sid, ver)).fetchone()
    if not row:
        raise ValueError("Unknown skill version")
    data = json.loads(row[1])
    stored = library_root()/"skills"/sid/ver/"recipe.json"
    if read_json(stored) != data:
        raise ValueError("Exported skill version changed")
    if digest(data["recipe"]) != data["recipe_sha256"] or digest(data["recipe"]["parameters"]) != data["schema_sha256"]:
        raise ValueError("Recipe or schema changed")
    if data["compatibility"] != compatibility():
        raise ValueError("Skill execution dependencies changed; requires new scoped verification")
    for path, expected in data["source"].items():
        if sha256(plain_path(path)) != expected:
            raise ValueError("Source evidence changed")
    return row[0], data


def search(root, query, required_types=("text", "shape"), limit=3):
    if not (root/"library.sqlite3").exists():
        return []
    with sqlite3.connect(f"file:{(root/'library.sqlite3').as_posix()}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT id,version FROM versions WHERE status='active_scoped' ORDER BY id,version").fetchall()
        hits = []
        for sid, ver in rows:
            try:
                _, data = version(db, sid, ver)
            except (ValueError, OSError):
                continue
            if not set(required_types) <= {o["kind"] for o in data["recipe"]["objects"]}:
                continue
            words = set(query.lower().split())
            score = len(words & set((data["description"]+" "+sid).lower().split()))
            if not score:
                continue
            hits.append({"skill_id": sid, "version": ver, "description": data["description"],
                         "scope": "Tested cases only; native independent objects, no groups",
                         "required_capabilities": ["workflow.probe", "pptx.build", "office.render"],
                         "entry": "rebuild_skill_apply", "score": score})
        return sorted(hits, key=lambda r: (-r["score"], r["skill_id"]))[:limit]


def verify_current_gate(project, run):
    """Recheck evidence bytes, not only the stored historical gate verdict."""
    from verify_delivery import verify
    paths = [under(project, run[k]["file"]) for k in
             ("candidate", "audit", "render", "review", "comparison")]
    return verify(*paths, under(project, run["dir"]+"/scene.json"))


def verify_application(app):
    """Never accept caller-authored booleans; original managed gates remain authoritative."""
    project = plain_path(app["project"])
    check_tree(project)
    state = load(project)
    tf = project/"trials"/app["trial_id"]
    from local_workflow import trial
    _, tr = trial(project, app["trial_id"])
    if tr.get("task_id") != app["task_id"]:
        raise ValueError("Application task identity differs")
    if state["status"] != "delivered":
        return {"status": "not_run", "reason": "Original delivery gates not completed"}
    if not any(a.get("trial_id") == app["trial_id"] and a.get("observation", {}).get("status") == "passed"
               for a in state.get("local_adoptions", {}).values()):
        return {"status": "needs_review", "reason": "Explicit original adoption with observation missing"}
    run = state["run"]
    final_scene = under(project, run["dir"]+"/scene.json")
    scene = read_json(final_scene)
    generated = read_json(tf/tr["scene"])
    expected = {o["id"]: o for o in generated["slides"][0]["objects"]}
    actual = {o["id"]: o for o in scene["slides"][0]["objects"]}
    if any(actual.get(k) != v for k, v in expected.items()):
        return {"status": "needs_review", "reason": "Adopted objects differ from applied recipe"}
    delivery = project/"delivery"/run["id"]/"delivery.json"
    receipt = read_json(delivery)
    if (receipt.get("status") != "passed" or receipt["gate"]["status"] != "passed" or
            receipt["pptx_sha256"] != sha256(under(project, run["candidate"]["file"])) or
            receipt["gate"]["scene_sha256"] != sha256(final_scene)):
        raise ValueError("Delivery identity or original gates invalid")
    gate = verify_current_gate(project, run)
    if gate["status"] != "passed":
        return {"status": "needs_review", "reason": "Current original gate evidence no longer passes",
                "gate": gate}
    evidence = {str(final_scene): sha256(final_scene), str(delivery): sha256(delivery)}
    for accepted in state["accepted"]:
        p = under(project, accepted["file"])
        evidence[str(p)] = sha256(p)
    return {"status": "passed", "project_id": state["project_id"], "run_id": run["id"],
            "evidence": evidence, "scope": "Original delivered task gates and exact applied object identity; host observation is attributed, not independent truth"}


def collect_current(project):
    """Recoverable completion hook, isolated from the primary delivery transaction."""
    root = library_root()
    if not (root/"library.sqlite3").exists():
        return
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        for appid, raw in db.execute("SELECT id,payload FROM applications").fetchall():
            app = json.loads(raw)
            if Path(app["project"]).resolve() != project.resolve():
                continue
            try:
                app["outcome"] = verify_application(app)
            except Exception as exc:
                app["outcome"] = {"status": "outcome_unknown", "reason": type(exc).__name__}
            db.execute("UPDATE applications SET payload=? WHERE id=?", (json.dumps(app), appid))


def execute_skill(command, project, args, policy):
    policy.require("workflow."+command)
    if command == "skill_apply":
        policy.require("workflow.probe", "pptx.validate", "pptx.build", "pptx.inspect", "assets.crop")
        if args.get("office", True):
            policy.require("office.render")
    root = library_root()
    if command == "skill_search":
        if args.get("version"):
            if not (root/"library.sqlite3").exists():
                raise ValueError("Learning library is empty")
            with sqlite3.connect(f"file:{(root/'library.sqlite3').as_posix()}?mode=ro", uri=True) as db:
                status, data = version(db, args["skill_id"], args["version"])
            return {"command_status": "completed", "status": status, "skill": data}
        hits = search(root, args["query"], args.get("object_types", ["text", "shape"]))
        return {"command_status": "completed", "matches": [
            h for h in hits if set(h["required_capabilities"]) <= policy.allowed]}
    operation = str(project.resolve())+":"+command+":"+args["operation_id"]
    with database(root) as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT fingerprint,response FROM operations WHERE id=?", (operation,)).fetchone()
        if previous:
            if previous[0] != digest(args):
                raise ValueError("Operation ID reused with different content")
            if command != "skill_capture":
                version(db, args["skill_id"], args["version"])
            return json.loads(previous[1])
        if command == "skill_capture":
            with locked(project):
                state = load(project)
                src = policy.input(args["source_scene"])
                pptx = policy.input(args["source_pptx"])
                evidence = [policy.input(p) for p in args["source_evidence"]]
                scene = read_json(src)
                from local_edit import properties
                actual = properties(pptx)
                slide = scene["slides"][args["slide_index"]]
                from common import bbox_to_points
                from common import walk_objects
                from evidence_contract import logical_bounds
                selected = [o for o in walk_objects(slide["objects"]) if o["id"] in args["object_ids"]]
                for o in selected:
                    row = actual[str(args["slide_index"])+"/"+o["id"]]
                    if row["parent"]:
                        parent=actual[str(args["slide_index"])+"/"+row["parent"]]
                        if parent["parent"] or parent["rotation"] or row["rotation"]:
                            raise ValueError("Only single-level unrotated source group members supported")
                    box=o.get("bbox")
                    if o["kind"]=="path":
                        x,y,r,b=logical_bounds(o);box=[x,y,r-x,b-y]
                    if box is None or any(abs(a-b) > .011 for a, b in zip(row["bbox_pt"], bbox_to_points(box, scene["canvas"]))):
                        raise ValueError("Native source geometry does not match scene")
                    if o["kind"] == "text" and row["text"].replace("\r", "\n") != o["text"]:
                        raise ValueError("Source text differs")
                recipe = capture(slide["objects"], args["object_ids"], args["parameters"],
                                 args["bindings"], args["placement_domain"], args["layout_assumptions"])
                sid = identifier(args["skill_id"])
                data = {"skill_id": sid, "description": args["description"], "recipe": recipe,
                        "recipe_sha256": digest(recipe), "schema_sha256": digest(recipe["parameters"]),
                        "compatibility": compatibility(),
                        "source": {str(p): sha256(p) for p in [src, pptx, *evidence]},
                        "source_evidence_level": "attributed_source_only_until_new_input_validation",
                        "created_at": now(), "project_id": state["project_id"]}
                ver = digest({k: v for k, v in data.items() if k != "created_at"})[:24]
                data["version"] = ver
                db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)", (sid, ver, "candidate", json.dumps(data)))
                folder = root/"skills"/sid/ver
                folder.mkdir(parents=True, exist_ok=True)
                if not (folder/"recipe.json").exists():
                    write_json(folder/"recipe.json", data)
                    (folder/"SKILL.md").write_text("# "+sid+"\n\n"+args["description"]+
                        "\n\nUse rebuild_skill_search for the immutable parameter contract, then rebuild_skill_apply."
                        "\nCandidate until scoped validation and activation. Each new task still needs original gates."
                        "\nNo arbitrary code, native groups or universal parameter-range validation.\n", encoding="utf-8")
                result = {"skill_id": sid, "version": ver, "status": "candidate", "skill_directory": str(folder)}
        elif command == "skill_apply":
            status, data = version(db, args["skill_id"], args["version"])
            state = load(project)
            task = state.get("active_task") or {}
            if task.get("id") != args["task_id"] or state["revision"] != args["base_revision"]:
                raise ValueError("Apply requires current real task")
            if status != "active_scoped" and not (status in {"candidate", "needs_review", "verified_scoped"} and args.get("validation_task") == args["task_id"]):
                raise ValueError("Skill inactive; candidate needs explicit current validation task")
            from local_workflow import execute_local
            policy.require("workflow.probe")
            fragment = compile_recipe(data["recipe"], args["values"], args["placement"])
            result = execute_local("probe", project, {"project": str(project), "operation_id": args["operation_id"],
                "task_id": args["task_id"], "base_revision": args["base_revision"], "result": fragment,
                "office": args.get("office", True)}, policy)
            appid = digest([state["project_id"], args["task_id"], args["operation_id"]])[:32]
            app = {"project": str(project), "project_id": state["project_id"], "task_id": args["task_id"],
                   "trial_id": result["trial_id"], "values_hash": digest([args["values"], args["placement"]]),
                   "status": "not_run", "recipe_sha256": data["recipe_sha256"]}
            db.execute("INSERT INTO applications VALUES(?,?,?,?)", (appid, args["skill_id"], args["version"], json.dumps(app)))
            result["application_id"] = appid
        elif command in {"skill_validate", "skill_activate"}:
            status, data = version(db, args["skill_id"], args["version"])
            rows = db.execute("SELECT id,payload FROM applications WHERE skill=? AND version=?",
                              (args["skill_id"], args["version"])).fetchall()
            outcomes = []
            for appid, raw in rows:
                app = json.loads(raw)
                # Foreign project evidence must be independently owner-authorized as input.
                policy.input(str(Path(app["project"])/"workflow/state.json"))
                outcome = verify_application(app)
                app["outcome"] = outcome
                db.execute("UPDATE applications SET payload=? WHERE id=?", (json.dumps(app), appid))
                outcomes.append({"application_id": appid, **outcome, "values_hash": app["values_hash"]})
            good = [o for o in outcomes if o["status"] == "passed"]
            verified = (len({o["project_id"] for o in good}) >= 2 and
                        len({o["values_hash"] for o in good}) >= 3)
            if command == "skill_activate":
                if args["enabled"] and not verified:
                    raise ValueError("Three different delivered inputs in at least two projects required")
                status = "active_scoped" if args["enabled"] else "disabled"
            else:
                status = ("active_scoped" if status == "active_scoped" else "verified_scoped") if verified else "needs_review"
            db.execute("UPDATE versions SET status=? WHERE id=? AND version=?", (status, args["skill_id"], args["version"]))
            result = {"status": status, "tested_cases": outcomes, "scope": "Discrete observed cases only",
                      "unique_successful_tasks": len({(o["project_id"], o["run_id"]) for o in good})}
        else:
            raise ValueError("Unknown skill command")
        result["command_status"] = "completed"
        db.execute("INSERT INTO operations VALUES(?,?,?)", (operation, digest(args), json.dumps(result)))
        return result
