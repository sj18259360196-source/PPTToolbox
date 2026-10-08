"""Reference-attributed compatibility checks attached to existing regional tasks."""
import copy
import json
import sqlite3
from pathlib import Path

from common import read_json, write_json, sha256
from workflow_store import load, locked, under, now, check_packet
from skill_recipe import compile_recipe, digest
from skill_library import library_root, version, search, verify_application


def context(project, args):
    state = load(project)
    task = state.get("active_task") or {}
    if task.get("id") != args["task_id"] or state["revision"] != args["base_revision"]:
        raise ValueError("Route requires current task and revision")
    if task["kind"] != "region_objects":
        raise ValueError("Route requires region_objects task")
    check_packet(project, state, task)
    packet = read_json(under(project, task["packet"]))
    page_id = packet["target"]["slide_id"]
    region_id = packet["target"]["region_id"]
    page = next(p for p in state["pages"] if p["id"] == page_id)
    region = next(r for r in page["plan"]["regions"] if r["id"] == region_id)
    if sha256(under(project, page["reference"])) != args["reference_sha256"]:
        raise ValueError("Reference identity differs")
    return state, task, page, region


def assess(data, status, args, allowed, tested_hashes=()):
    """Caller observations remain attributed; unknown never becomes a visual pass."""
    result = {"executable": False, "evidence_scope": "unknown", "reference_fit": "needs_review",
              "route": "needs_review", "reasons": [], "visual_status": "not_assessed",
              "covered": [], "uncovered": []}
    if status != "active_scoped" or not {"workflow.skill_apply", "workflow.probe", "pptx.build",
                                       "office.render"} <= set(allowed):
        result.update(reference_fit="incompatible", route="native_rebuild")
        result["reasons"].append("Skill lifecycle or execution capability unavailable")
        return result
    try:
        fragment = compile_recipe(data["recipe"], args["values"], args["placement"])
    except (ValueError, TypeError, KeyError) as exc:
        result.update(evidence_scope="outside_declared", reference_fit="incompatible", route="native_rebuild")
        result["reasons"].append("Parameter contract: "+str(exc))
        return result
    result["executable"] = True
    result["evidence_scope"] = ("tested_case" if digest([args["values"], args["placement"]]) in tested_hashes
                                else "within_declared_but_untested")
    requirements = args["requirements"]
    targets = requirements["objects"]
    mapping = requirements["bindings"]
    ids = [r["id"] for r in targets]
    if len(ids) != len(set(ids)) or len(mapping.values()) != len(set(mapping.values())):
        raise ValueError("Duplicate target ownership")
    generated = {o["id"]: o for o in fragment["objects"]}
    if set(mapping) != set(generated) or set(mapping.values()) != set(ids):
        result.update(reference_fit="incompatible", route="native_rebuild")
        result["uncovered"] = sorted(set(ids)-set(mapping.values()))
        result["reasons"].append("Object coverage differs; split explicit regions, do not omit or duplicate objects")
        return result
    if requirements["source"]["level"] == "unknown" or not requirements["complete"]:
        result["reasons"].append("Reference coverage or observation is unknown")
        return result
    mismatch, unknown = [], []
    by_id = {o["id"]: o for o in targets}
    for oid, actual in generated.items():
        req = by_id[mapping[oid]]
        if req["kind"] == "unknown" or req["bbox"] is None or req["style"] is None:
            unknown.append(req["id"])
            continue
        if actual["kind"] != req["kind"]:
            mismatch.append(req["id"]+": native type")
        if actual["kind"] == "text":
            if req["text"] is None:
                unknown.append(req["id"])
            elif actual.get("text") != req["text"]:
                mismatch.append(req["id"]+": original text")
            required_style = {"font", "font_size_pt", "color", "bold"}
            if not required_style <= req["style"].keys():
                unknown.append(req["id"]+": text physical style incomplete")
        elif req.get("geometry") != actual.get("geometry"):
            mismatch.append(req["id"]+": geometry")
        if any(abs(a-b) > .5 for a, b in zip(actual["bbox"], req["bbox"])):
            mismatch.append(req["id"]+": relative layout in local pixels")
        for field, expected in req["style"].items():
            value = actual.get("style", {}).get(field)
            equal = (abs(value-expected) <= .1 if type(value) in (float, int) and
                     type(expected) in (float, int) else value == expected)
            if not equal:
                mismatch.append(req["id"]+": style."+field)
        if req["editability"] != ("text" if actual["kind"] == "text" else "shape"):
            mismatch.append(req["id"]+": edit depth")
    if mismatch:
        result.update(reference_fit="incompatible", route="native_rebuild", reasons=mismatch)
    elif unknown:
        result["reasons"] = ["Unknown requirement: "+x for x in unknown]
    else:
        result.update(reference_fit="eligible_for_probe", route="skill_reuse", covered=ids,
                      reasons=["Attributed reference requirements match supported objects; current visual review still required"])
    return result


def placement_fits(placement, region_box):
    x, y, w, h = placement
    left, top, right, bottom = region_box
    return x >= 0 and y >= 0 and x+w <= right-left and y+h <= bottom-top


def route_check(project, args, policy):
    policy.require("workflow.route_check", "workflow.skill_search")
    with locked(project):
        state, task, page, region = context(project, args)
        root = library_root()
        with sqlite3.connect(f"file:{(root/'library.sqlite3').as_posix()}?mode=ro", uri=True) as db:
            try:
                status, data = version(db, args["skill_id"], args["version"])
                tested = []
                for raw, in db.execute("SELECT payload FROM applications WHERE skill=? AND version=?",
                                        (args["skill_id"], args["version"])):
                    app = json.loads(raw)
                    policy.input(str(Path(app["project"])/"workflow/state.json"))
                    if verify_application(app)["status"] == "passed":
                        tested.append(app["values_hash"])
                decision = assess(data, status, args, policy.allowed, tested)
            except ValueError as exc:
                decision = {"executable": False, "evidence_scope": "unknown",
                            "reference_fit": "incompatible", "route": "native_rebuild",
                            "reasons": [str(exc)], "visual_status": "not_assessed",
                            "covered": [], "uncovered": []}
        # Geometry must fit the current local crop, not merely the source template.
        if not placement_fits(args["placement"], region["bbox"]):
            decision.update(reference_fit="incompatible", route="native_rebuild",
                            reasons=["Placement exceeds current reference region"])
        record = {"format": "regional-route/1", "project_id": state["project_id"],
                  "arguments": copy.deepcopy(args), "decision": decision,
                  "reference_mapping": page["mapping"], "region": region,
                  "state_sha256": sha256(project/"workflow/state.json")}
        rid = digest(record)[:32]
        dest = project/"routes"/(rid+".json")
        if not dest.exists():
            write_json(dest, {**record, "created_at": now()})
        return {"command_status": "completed", "route_id": rid, **decision,
                "record": str(dest), "source": args["requirements"]["source"]}


def enforce_apply(project, args, policy):
    rid = args.get("route_id")
    if not rid:
        return
    record = read_json(under(project, "routes/"+rid+".json"))
    original = record["arguments"]
    context(project, original)
    if sha256(project/"workflow/state.json") != record["state_sha256"]:
        raise ValueError("Route state changed")
    for key in ("project", "task_id", "base_revision", "skill_id", "version", "values", "placement"):
        if args[key] != original[key]:
            raise ValueError("Route input differs: "+key)
    refreshed = route_check(project, original, policy)
    if refreshed["route_id"] != rid or refreshed["reference_fit"] != "eligible_for_probe":
        raise ValueError("Route no longer eligible")


def bind_application(project, args, result):
    if args.get("route_id") and result.get("trial_id"):
        write_json(project/"routes"/"applications"/(result["trial_id"]+".json"),
                   {"route_id": args["route_id"], "arguments": args,
                    "application_id": result["application_id"]})


def enforce_adopt(project, args, policy):
    path = under(project, "routes/applications/"+args["trial_id"]+".json", must_exist=False)
    if path.exists():
        binding = read_json(path)
        enforce_apply(project, binding["arguments"], policy)


def report(project, args, policy):
    policy.require("workflow.route_report")
    state = load(project)
    records = []
    for path in sorted((project/"routes").glob("*.json")):
        record = read_json(path)
        if record["project_id"] != state["project_id"]:
            raise ValueError("Foreign route record")
        records.append({"route_id": path.stem, "task_id": record["arguments"]["task_id"],
                        "decision": record["decision"]})
    applications = []
    root = library_root()
    if (root/"library.sqlite3").exists():
        with sqlite3.connect(f"file:{(root/'library.sqlite3').as_posix()}?mode=ro", uri=True) as db:
            for aid, sid, ver, raw in db.execute("SELECT id,skill,version,payload FROM applications"):
                app = json.loads(raw)
                if Path(app["project"]).resolve() != project.resolve():
                    continue
                try:
                    version(db, sid, ver)
                    outcome = verify_application(app)
                except Exception as exc:
                    outcome = {"status": "needs_review", "reason": type(exc).__name__}
                applications.append({"use_id": aid, "skill_id": sid, "version": ver,
                    "task_id": app["task_id"], "trial_id": app["trial_id"], "outcome": outcome,
                    "classification": ("retained_recipe" if outcome["status"] == "passed" else
                        "modified_or_abandoned" if outcome.get("reason") == "Adopted objects differ from applied recipe"
                        else "pending_or_unverified")})
    region_tasks = set()
    for accepted in state.get("accepted", []):
        path = under(project, accepted["file"])
        if sha256(path) != accepted["sha256"]:
            raise ValueError("Accepted task evidence changed")
        value = read_json(path)
        if value.get("kind") == "region_objects":
            region_tasks.add(value["task_id"])
    return {"command_status": "completed", "routes": records, "applications": applications,
            "counts": {"projects": 1, "pages": len(state["pages"]),
                       "region_tasks": len(region_tasks),
                       "checked_region_tasks": len({r["task_id"] for r in records}),
                       "uses": len(applications),
                       "successful_uses": sum(a["outcome"]["status"] == "passed" for a in applications)}}
