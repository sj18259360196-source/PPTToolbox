"""Project-attached bounded calibration, using the existing managed edit chain."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from PIL import Image
from common import read_json, write_json, sha256, bbox_to_points, walk_objects, resolve_asset
from workflow_store import locked, load, brief, under, WorkflowError, now
from local_workflow import (fingerprint, bundle, region_scope, constrain, patch,
                            compare_trial, persist, render, check_base, verify_files)
from local_edit import properties, office_roundtrip, equivalent, prepare
from build_pptx import build
from calibration_math import (METRIC, FIELDS, validate_parameters, neighbors, measure, quantize,
                              validate_critical_dimensions, critical_check, qualification)
from calibration_exports import pre_reserved

ROOT = Path(__file__).resolve().parents[1]
CAPS = ("workflow.patch", "workflow.compare", "ops.patch-pptx", "pptx.validate",
        "pptx.build", "pptx.inspect", "office.render", "office.edit-readback", "compare.page", "ops.regression")
TERMINAL = {"target_met", "improved_pending_review", "no_improvement", "budget_exhausted",
            "no_feasible_candidate", "unmeasurable", "incomparable", "stale_base", "outcome_unknown"}


def code():
    from toolbox_manager.execution import code_version
    return code_version(ROOT)["code_sha256"]


def registered_fonts(names):
    from text_ops import list_local_fonts
    inventory = list_local_fonts()
    registered = [r.get("registered_name", r.get("family", "")).casefold() for r in inventory["fonts"]]
    names = {name if isinstance(name, str) else "" for name in names}
    missing = [name for name in names if not name or not any(name.casefold() in v for v in registered)]
    return {"requested": sorted(names), "missing_or_unresolved": sorted(missing),
            "registered_names_sha256": fingerprint(sorted(registered)),
            "glyph_resolution": "unknown"}


def save(folder, record):
    write_json(folder/"calibration.json", record)


def output(project, state, folder, record):
    numeric = sorted((r for r in record.get("trials", []) if r.get("legal")),
                     key=lambda r: (r["measurement"]["score"], r["distance"]))
    ranked = [r for r in numeric if r.get("qualification", {}).get("status") == "eligible"][:3]
    stale = state["revision"] != record["base_revision"] or sha256(project/"workflow/state.json") != record["state_sha256"]
    comparable = record["metric"] == METRIC and record["code_sha256"] == code()
    best = record.get("best") if comparable and not stale and ranked else None
    return {**brief(state), "calibration_id": folder.name, "stop_reason": "stale_base" if stale else record["stop_reason"],
            "calibration_record": str(folder/"calibration.json"), "budget": read_json(ledger_path(project, record)),
            "best": best, "recommendable_best": best, "historical_best": record.get("best"),
            "numerical_best": numeric[0]["trial_id"] if numeric else None, "numeric_ranking": numeric[:3],
            "recommendation_status": ("needs_review" if stale or not comparable else
                                      "eligible_pending_visual_review" if best else "retain_baseline_or_review"),
            "alternatives": ranked if comparable and not stale else [], "baseline": record.get("baseline"),
            "visual_status": "not_run", "auto_adopt": False,
            "final_verification": record.get("final_verification", "not_run"),
            "ambiguous_parameters": sum(abs(r["measurement"]["score"]-record.get("best_score", 0))
                                        <= METRIC["min_delta"] for r in ranked) > 1}


def ledger_path(project, record):
    return project/"calibrations"/("episode-"+record["episode"]+".json")


def reserve(project, folder, record, attempts=0, exports=0):
    path = ledger_path(project, record)
    budget = read_json(path)
    if budget["attempts"]+attempts > 24 or budget["exports_reserved"]+exports > 40:
        record["stop_reason"] = "budget_exhausted"
        save(folder, record)
        return False
    budget["attempts"] += attempts
    budget["exports_reserved"] += exports
    write_json(path, budget)
    record["budget"] = budget
    save(folder, record)
    return True


def check(project, state, folder, record):
    check_base(project, state, record)
    verify_files(folder, record)
    if code() != record["code_sha256"] or record["metric"] != METRIC:
        raise WorkflowError("incomparable", "Production or frozen metric changed; retain prior evidence")
    frozen = read_json(folder/"frozen-plan.json")
    if any(record[k] != v for k, v in frozen.items()):
        raise WorkflowError("incomparable", "Frozen plan fields changed")
    if registered_fonts(record["fonts"]["requested"]) != record["fonts"]:
        raise WorkflowError("incomparable", "Registered font environment changed")
    run = state["run"]
    if sha256(under(project, run["dir"]+"/scene.json")) != record["base_scene_sha256"] or (
            sha256(under(project, run["candidate"]["file"])) != record["base_pptx_sha256"]):
        raise WorkflowError("stale_base", "Current scene/PPTX differs")


def plan(project, state, args, policy):
    folder = project/"calibrations"/args["operation_id"]
    digest = fingerprint(args)
    if folder.exists():
        record = read_json(folder/"calibration.json")
        if record["fingerprint"] != digest:
            raise ValueError("Plan ID reused with different content")
        check(project, state, folder, record)
        return output(project, state, folder, record)
    if args["base_revision"] != state["revision"] or args["task_id"] != (state.get("active_task") or {}).get("id"):
        raise WorkflowError("stale_base", "Plan requires current task and revision")
    run = state.get("run")
    if not run or not run.get("candidate") or state["status"] == "delivered":
        raise ValueError("Current undelivered candidate required")
    scene_path = under(project, run["dir"]+"/scene.json")
    pptx = under(project, run["candidate"]["file"])
    if sha256(scene_path) != args["scene_sha256"] or sha256(pptx) != args["pptx_sha256"]:
        raise WorkflowError("stale_base", "Plan pair hashes differ")
    scene = read_json(scene_path)
    if len(scene["slides"]) != 1:
        raise ValueError("First calibration kernel supports single-page projects only")
    page, region = region_scope(state, args["slide"], args["region"])
    target = next(s for s in scene["slides"] if s["id"] == args["slide"])
    objs = {o["id"]: o for o in target["objects"]}
    params = args["parameters"]
    validate_parameters(params)
    actual = properties(pptx)
    prefix = args["slide"]+"."+args["region"]+"."
    for p in params:
        oid, field = p["object_id"], p["field"]
        if not oid.startswith(prefix) or oid not in objs or objs[oid]["kind"] not in {"text", "shape"}:
            raise ValueError("Object outside native top-level region authorization")
        obj, row = objs[oid], actual["0/"+oid]
        if row["rotation"] or row["parent"] or "runs" in obj:
            raise ValueError("Rotated/grouped/rich text not supported")
        if field in FIELDS[:4]:
            value = row["bbox_pt"][FIELDS.index(field)]
        elif obj["kind"] != "text":
            raise ValueError("Text parameter on non-text object")
        elif field == "font_size_pt":
            values = {r["size_pt"] for par in row["paragraphs"] for r in par["runs"]}
            if len(values) != 1 or None in values:
                raise ValueError("Uniform explicit font size required")
            value = next(iter(values))
        else:
            value = row["margins_pt"][("left", "right", "top", "bottom").index(field.split("_")[1])]
        if abs(value-p["initial"]) > .011:
            raise ValueError("Initial parameter differs from persisted actual property")
    ref = resolve_asset(scene_path.parent, target["reference"])
    names = {r["font"] for p in params for par in actual["0/"+p["object_id"]].get("paragraphs", [])
             for r in par["runs"] if r.get("text")}
    fonts = registered_fonts(names)
    if fonts["missing_or_unresolved"]:
        raise ValueError("Requested font missing or unresolved; no substitution accepted")
    with Image.open(ref) as im:
        w, h = im.size
    roi = args["roi"]
    if not 0 <= roi[0] < roi[2] <= w or not 0 <= roi[1] < roi[3] <= h:
        raise ValueError("ROI must retain full-page coordinates")
    dimensions = args.get("critical_dimensions", [])
    validate_critical_dimensions(dimensions, {p["object_id"] for p in params}, (w, h))
    # A region has one cumulative repair budget even if callers rename/replan.
    episode = fingerprint([state["project_id"], args["slide"], args["region"]])[:24]
    record = {"format": "ppt-calibration/1", "plan_version": 2, "fingerprint": digest, "project_id": state["project_id"],
              "base_revision": state["revision"], "state_sha256": sha256(project/"workflow/state.json"),
              "task_id": args["task_id"], "base_scene_sha256": sha256(scene_path),
              "base_pptx_sha256": sha256(pptx), "code_sha256": code(), "metric": copy.deepcopy(METRIC),
              "reference_sha256": sha256(ref), "parameters": params, "roi": roi,
              "critical_dimensions": dimensions,
              "background": args["background"], "target_source": args["target_source"],
              "allowed_line_counts": args["allowed_line_counts"], "slide": args["slide"], "region": args["region"],
              "episode": episode, "stop_reason": "running", "started_at": now(), "fonts": fonts,
              "center": [quantize(p["initial"]) for p in params], "steps": [p["step"] for p in params],
              "queue": [], "evaluated": [], "trials": [], "requests": {}, "best": None,
              "mapping": {"px_to_pt_x": scene["canvas"]["width_pt"]/w,
                          "px_to_pt_y": scene["canvas"]["height_pt"]/h, "roi_origin": roi[:2]},
              "font_environment": "Per-glyph font resolution unverified; same-host results only"}
    # Validate the exact backend's supported subtype without saving or opening Office.
    prepare(scene_path, pptx, args["slide"], {p["object_id"] for p in params},
            changes(record, record["center"], scene), calibration=True)
    folder.mkdir(parents=True)
    bundle(scene, scene_path.parent, folder/"frozen")
    import shutil
    shutil.copyfile(pptx, folder/"base.pptx")
    write_json(folder/"frozen-plan.json", {k: record[k] for k in (
        "fingerprint", "parameters", "roi", "background", "metric", "allowed_line_counts",
        "base_scene_sha256", "base_pptx_sha256", "project_id", "base_revision", "task_id",
        "code_sha256", "episode", "target_source", "mapping", "slide", "region", "fonts", "critical_dimensions")})
    record["files"] = {p.relative_to(folder).as_posix(): sha256(p) for p in folder.rglob("*") if p.is_file()}
    lp = ledger_path(project, record)
    if not lp.exists():
        write_json(lp, {"attempts": 0, "exports_reserved": 0, "exports_completed": 0,
                        "limits": {"attempts": 24, "exports": 40, "per_step": 4}})
    record["budget"] = read_json(lp)
    save(folder, record)
    return output(project, state, folder, record)


def exported(project, folder, record, count):
    lp = ledger_path(project, record)
    budget = read_json(lp)
    budget["exports_completed"] += count
    write_json(lp, budget)
    record["budget"] = budget
    save(folder, record)


def changes(record, vector, scene):
    by_id = {}
    objs = {o["id"]: o for o in scene["slides"][0]["objects"]}
    canvas = scene["canvas"]
    for p, value in zip(record["parameters"], vector):
        oid, field = p["object_id"], p["field"]
        row = by_id.setdefault(oid, {})
        if field in FIELDS[:4]:
            bbox = row.setdefault("bbox", list(objs[oid]["bbox"]))
            i = FIELDS.index(field)
            ratio = canvas["width"]/canvas["width_pt"] if i % 2 == 0 else canvas["height"]/canvas["height_pt"]
            bbox[i] = value*ratio
        else:
            row.setdefault("style", {})[field] = value
    ops = []
    for oid, row in by_id.items():
        if "bbox" in row:
            ops.append({"op": "geometry.set", "id": oid, "bbox": row["bbox"]})
        if "style" in row:
            ops.append({"op": "text.style", "id": oid, "style": row["style"]})
    return ops


def hard_checks(record, vector, trial_dir, measurement):
    old = properties(trial_dir/"baseline-office.pptx")
    new = properties(trial_dir/"candidate.pptx")
    failures = []
    if old.keys() != new.keys():
        return {"status": "failed", "failures": ["object_identity"], "font_resolution": "unknown",
                "typographic_baseline": "unknown", "office_text_bounds": []}
    permitted = {}
    for p, v in zip(record["parameters"], vector):
        permitted.setdefault("0/"+p["object_id"], set()).add(p["field"])
        row = new["0/"+p["object_id"]]
        f = p["field"]
        actual = (row["bbox_pt"][FIELDS.index(f)] if f in FIELDS[:4] else
                  row["paragraphs"][0]["runs"][0]["size_pt"] if f == "font_size_pt" else
                  row["margins_pt"][("left", "right", "top", "bottom").index(f.split("_")[1])])
        if actual is None or abs(actual-v) > .011 or not p["lower"] <= actual <= p["upper"]:
            failures.append("actual_parameter_range")
    if old.keys() != new.keys():
        failures.append("object_identity")
    def intersection(a, b):
        x, y, w, h = a; xx, yy, ww, hh = b
        return max(0, min(x+w, xx+ww)-max(x, xx))*max(0, min(y+h, yy+hh)-max(y, yy))
    def contains(a, b):
        return (a[0] <= b[0]+.01 and a[1] <= b[1]+.01 and
                a[0]+a[2] >= b[0]+b[2]-.01 and a[1]+a[3] >= b[1]+b[3]-.01)
    order = {key: i for i, key in enumerate(old)}
    for key in permitted:
        for other in old.keys()-permitted.keys():
            a, b = old[key]["bbox_pt"], old[other]["bbox_pt"]
            aa, bb = new[key]["bbox_pt"], new[other]["bbox_pt"]
            containing_background = (
                order[other] < order[key] and contains(b, a) and contains(bb, aa) or
                order[key] < order[other] and contains(a, b) and contains(aa, bb))
            if not containing_background and intersection(aa, bb) > intersection(a, b)+.01:
                failures.append("new_overlap:"+other)
    for key in old.keys() & new.keys():
        a, b = copy.deepcopy(old[key]), copy.deepcopy(new[key])
        for field in permitted.get(key, ()):
            if field in FIELDS[:4]:
                b["bbox_pt"][FIELDS.index(field)] = a["bbox_pt"][FIELDS.index(field)]
            elif field.startswith("margin"):
                i = ("left", "right", "top", "bottom").index(field.split("_")[1])
                b["margins_pt"][i] = a["margins_pt"][i]
            elif field == "font_size_pt":
                for pa, pb in zip(a["paragraphs"], b["paragraphs"]):
                    for ra, rb in zip(pa["runs"], pb["runs"]):
                        rb["size_pt"] = ra["size_pt"]
        if not equivalent(a, b):
            failures.append("frozen_property:"+key)
    office = read_json(trial_dir/"readback.json")
    base_office = read_json(trial_dir/"baseline-readback.json")
    baselines = {r["name"]: r for r in base_office["objects"]}
    for row in office["objects"]:
        if "0/"+row["name"] not in permitted or not row.get("text"):
            continue
        before = baselines[row["name"]]
        if any(row[k] != before[k] for k in ("text", "autosize", "wordwrap", "anchor", "font_name")):
            failures.append("frozen_office_text_mode")
        x, y, w, h = row["bbox_pt"]
        tx, ty, tw, th = row["text_bounds_pt"]
        if tx < x-.1 or ty < y-.1 or tx+tw > x+w+.1 or ty+th > y+h+.1:
            failures.append("text_overflow")
    if measurement["status"] != "measured":
        failures.append("unmeasurable")
    else:
        candidate = measurement["candidate"]
        if candidate["touching"]:
            failures.append("roi_edge_contact")
        if record["allowed_line_counts"] and len(candidate["line_bands"]) not in record["allowed_line_counts"]:
            failures.append("line_count")
    return {"status": "passed" if not failures else "failed", "failures": sorted(set(failures)),
            "font_resolution": "unknown", "typographic_baseline": "unknown",
            "office_text_bounds": office["objects"]}


def initialize(project, state, folder, record, policy):
    if record["target_source"]["level"] == "unknown":
        record["stop_reason"] = "unmeasurable"
        save(folder, record)
        return
    if not reserve(project, folder, record, exports=2):
        return
    scene = folder/"frozen/scene.json"
    office_roundtrip(folder/"base.pptx", folder/"baseline-reopened.pptx", folder/"baseline-readback.json")
    for i in (1, 2):
        result = render(folder, scene, folder/"base.pptx", f"noise-{i}")
        if result["status"] != "passed":
            record["stop_reason"] = "unmeasurable"
            save(folder, record)
            return
        exported(project, folder, record, 1)
    data = read_json(scene)
    ref = resolve_asset(scene.parent, data["slides"][0]["reference"])
    a, b = folder/"noise-1/slide-001.png", folder/"noise-2/slide-001.png"
    noise = measure(a, b, record["roi"], record["background"])
    baseline = measure(ref, a, record["roi"], record["background"])
    record["baseline"] = {"measurement": baseline, "noise": noise, "render": str(a),
                          "reference": str(ref), "vector": record["center"]}
    baseline_failures = []
    target_ids = {p["object_id"] for p in record["parameters"]}
    for row in read_json(folder/"baseline-readback.json")["objects"]:
        if row["name"] not in target_ids or not row.get("text"):
            continue
        x, y, w, h = row["bbox_pt"]
        tx, ty, tw, th = row["text_bounds_pt"]
        if tx < x-.1 or ty < y-.1 or tx+tw > x+w+.1 or ty+th > y+h+.1:
            baseline_failures.append("text_overflow")
    if baseline["status"] == "measured":
        if baseline["candidate"]["touching"]:
            baseline_failures.append("roi_edge_contact")
        if record["allowed_line_counts"] and len(baseline["candidate"]["line_bands"]) not in record["allowed_line_counts"]:
            baseline_failures.append("line_count")
    record["baseline"]["hard_failures"] = baseline_failures
    record["baseline"]["legal"] = not baseline_failures and baseline["status"] == "measured"
    critical = critical_check(ref, a, a, record["critical_dimensions"], record["background"], repeat=b)
    record["baseline"]["critical"] = critical
    views = folder/"roi-views"
    views.mkdir()
    for name, path in (("reference", ref), ("baseline", a)):
        with Image.open(path) as im:
            im.crop(record["roi"]).save(views/(name+".png"))
    record["environment"] = {k: read_json(folder/"noise-1/office-render.json").get(k)
                             for k in ("renderer", "office_version")}
    second_env = read_json(folder/"noise-2/office-render.json")
    if any(second_env.get(k) != v for k, v in record["environment"].items()):
        record["stop_reason"] = "incomparable"
    elif noise["status"] != "measured" or baseline["status"] != "measured" or critical["status"] != "passed":
        record["stop_reason"] = "unmeasurable"
    elif noise["score"] > METRIC["noise_limit"]:
        record["stop_reason"] = "incomparable"
    else:
        record["best_score"] = baseline["score"] if not baseline_failures else 1.e100
        record["evaluated"] = [record["center"]]
        record["queue"] = neighbors(record["parameters"], record["center"], record["steps"])
        if not baseline_failures and baseline["score"] <= METRIC["target"] and critical["target_met"]:
            record["stop_reason"] = "target_met"
    save(folder, record)


def next_vector(record):
    while True:
        while record["queue"]:
            v = record["queue"].pop(0)
            if v not in record["evaluated"]:
                return v
        steps = [max(p["min_step"], s/2) for p, s in zip(record["parameters"], record["steps"])]
        if steps == record["steps"]:
            return None
        record["steps"] = steps
        record["queue"] = neighbors(record["parameters"], record["center"], steps)


def run_trial(project, state, folder, record, vector, policy):
    if not reserve(project, folder, record, attempts=1, exports=2):
        return
    index = record["budget"]["attempts"]
    tid = f"cal-{record['episode'][:12]}-{index}"
    tf = project/"trials"/tid
    cf = project/"trials"/(tid+"-compare")
    tf.mkdir(parents=True); cf.mkdir()
    base = {"format": "ppt-local-trial/1", "kind": "patch", "calibration_id": folder.name,
            "project_id": state["project_id"], "base_revision": state["revision"],
            "state_sha256": record["state_sha256"], "started_at": now(),
            "operation_id": tid, "fingerprint": fingerprint([folder.name, vector]),
            "call_id": getattr(policy, "call_id", None)}
    write_json(tf/"intent.json", base)
    cr = {**base, "kind": "compare", "operation_id": cf.name}
    write_json(cf/"intent.json", cr)
    row = {"trial_id": tid, "comparison_id": cf.name, "vector": vector, "legal": False,
           "status": "running", "distance": sum(abs(a-b) for a, b in zip(vector, record["baseline"]["vector"]))}
    record["trials"].append(row)
    record["evaluated"].append(vector)
    save(folder, record)
    args = {"scene_sha256": record["base_scene_sha256"], "pptx_sha256": record["base_pptx_sha256"],
            "slide": record["slide"], "region": record["region"],
            "changes": changes(record, vector, read_json(folder/"frozen/scene.json"))}
    try:
        persist(tf, patch(project, state, args, tf, base, policy))
        persist(cf, compare_trial(project, state, {"trial_id": tid}, cf, cr, policy))
        exported(project, folder, record, 2)
        env = read_json(cf/"office/office-render.json")
        if any(env.get(k) != v for k, v in record["environment"].items()):
            record["stop_reason"] = "incomparable"
            return
        with Image.open(folder/"noise-1/slide-001.png") as im:
            initial_pixels = im.convert("RGB").tobytes()
        with Image.open(cf/"baseline-office/slide-001.png") as im:
            if im.convert("RGB").tobytes() != initial_pixels:
                record["stop_reason"] = "incomparable"
                row.update(status="incomparable", reason="Repeated frozen baseline pixels changed")
                return
        m = measure(record["baseline"]["reference"], cf/"office/slide-001.png",
                    record["roi"], record["background"])
        hard = hard_checks(record, vector, tf, m)
        row.update(status="completed", measurement=m, hard_checks=hard,
                   legal=hard["status"] == "passed" and cr["outside_regression"] == "passed",
                   record=str(tf/"record.json"), comparison=str(cf/"record.json"),
                   must_view_files=[str(cf/x) for x in cr["view_files"]])
        critical = critical_check(record["baseline"]["reference"], record["baseline"]["render"],
                                  cf/"office/slide-001.png", record["critical_dimensions"], record["background"])
        row["qualification"] = qualification(row["legal"], m, record["baseline"], critical)
        with Image.open(cf/"office/slide-001.png") as im:
            im.crop(record["roi"]).save(cf/"calibration-roi.png")
        row["must_view_files"].append(str(cf/"calibration-roi.png"))
        persist(cf, cr)
        if row["qualification"]["status"] == "eligible" and m["score"] < record["best_score"]-max(METRIC["min_delta"], record["baseline"]["noise"]["score"]):
            record.update(best=tid, best_score=m["score"], center=vector)
            record["queue"] = neighbors(record["parameters"], vector, record["steps"])
            if m["score"] <= METRIC["target"] and critical["target_met"]:
                record["stop_reason"] = "target_met"
    except WorkflowError:
        row.update(status="outcome_unknown")
        record["stop_reason"] = "outcome_unknown"
        save(folder, record)
        raise
    except ValueError as exc:
        row.update(status="rejected", reason=str(exc))
        # Reservations are never refunded after a possibly partial export.
    except Exception:
        row.update(status="outcome_unknown")
        record["stop_reason"] = "outcome_unknown"
        save(folder, record)
        raise
    finally:
        save(folder, record)


def finalize(project, state, folder, record, policy):
    tid = record.get("best")
    if not tid or record.get("final_verification") == "passed":
        return
    if not reserve(project, folder, record, exports=2):
        return
    tf = project/"trials"/tid
    verify_files(tf, read_json(tf/"record.json"))
    dest = folder/"final"
    dest.mkdir()
    actual = office_roundtrip(tf/"candidate.pptx", dest/"reopened.pptx", dest/"reopened.json")
    build(tf/"bundle/scene.json", dest/"rebuilt.pptx")
    rebuilt = office_roundtrip(dest/"rebuilt.pptx", dest/"rebuilt-office.pptx", dest/"rebuilt.json")
    if not equivalent(actual, rebuilt):
        record["final_verification"] = "failed"
        save(folder, record)
        return
    for name, pptx in (("reopened", "reopened.pptx"), ("rebuilt", "rebuilt-office.pptx")):
        r = render(dest, tf/"bundle/scene.json", dest/pptx, name+"-render")
        if r["status"] != "passed":
            record["final_verification"] = "unmeasurable"
            save(folder, record)
            return
        exported(project, folder, record, 1)
    candidate = project/"trials"/(tid+"-compare")/"office/slide-001.png"
    with Image.open(candidate) as im:
        pixels = im.convert("RGB").tobytes()
    valid = True
    for name in ("reopened", "rebuilt"):
        with Image.open(dest/(name+"-render")/"slide-001.png") as im:
            valid &= im.convert("RGB").tobytes() == pixels
    record["final_verification"] = "passed" if valid else "failed"
    record["final_files"] = {p.relative_to(folder).as_posix(): sha256(p) for p in dest.rglob("*") if p.is_file()}
    save(folder, record)


def adoption_guard(project, trial, tid, viewed):
    folder = project/"calibrations"/trial["calibration_id"]
    record = read_json(folder/"calibration.json")
    check(project, load(project), folder, record)
    if record.get("best") != tid or record.get("final_verification") != "passed":
        raise ValueError("Calibration candidate lacks independent final verification")
    verify_files(folder, {"files": record["final_files"]})
    required = {str((folder/"final"/(name+"-render")/"slide-001.png").resolve())
                for name in ("reopened", "rebuilt")}
    required.update([str(Path(record["baseline"]["reference"]).resolve()),
                     str(Path(record["baseline"]["render"]).resolve())])
    required.update(str((folder/"roi-views"/name).resolve()) for name in ("reference.png", "baseline.png"))
    required.add(str((project/"trials"/(tid+"-compare")/"calibration-roi.png").resolve()))
    if not required <= {str(Path(v).resolve()) for v in viewed}:
        raise ValueError("Calibration observation must include reference, baseline and final independent renders")
    row = next(r for r in record["trials"] if r["trial_id"] == tid)
    if not row["legal"] or row.get("qualification", {}).get("status") != "eligible":
        raise ValueError("Calibration hard constraints failed")


def execute_calibration(command, project, args, policy):
    policy.require("workflow."+command)
    with locked(project):
        state = load(project)
        if command == "calibrate_plan":
            return plan(project, state, args, policy)
        folder = project/"calibrations"/args["calibration_id"]
        record = read_json(folder/"calibration.json")
        if command == "calibrate_report":
            return output(project, state, folder, record)
        check(project, state, folder, record)
        if state.get("failure") or state.get("operation"):
            raise WorkflowError("interrupted_operation", "Resolve primary workflow first")
        request = args["request_id"]
        digest = fingerprint(args)
        if request in record["requests"]:
            r = record["requests"][request]
            if r["fingerprint"] != digest:
                raise ValueError("Request ID reused")
            if r["status"] == "running":
                return {**output(project, state, folder, record), "command_status": "outcome_unknown"}
            return r["response"]
        if any(r["status"] == "running" for r in record["requests"].values()):
            return {**output(project, state, folder, record), "command_status": "outcome_unknown"}
        record["requests"][request] = {"fingerprint": digest, "status": "running"}
        if args.get("cancel", False):
            record["stop_reason"] = "user_stopped"
            response = output(project, state, folder, record)
            record["requests"][request].update(status="completed", response=response)
            save(folder, record)
            return response
        policy.require(*CAPS)
        save(folder, record)
        before = record["budget"]["exports_reserved"]
        reservation_context = pre_reserved()
        reservation_context.__enter__()
        try:
            if "baseline" not in record and record["stop_reason"] == "running":
                if read_json(ledger_path(project, record))["exports_reserved"]+6 > 40:
                    record["stop_reason"] = "budget_exhausted"
                    save(folder, record)
                else:
                    initialize(project, state, folder, record, policy)
            elif record["stop_reason"] == "running":
                for _ in range(2):
                    if read_json(ledger_path(project, record))["exports_reserved"] > 32:
                        record["stop_reason"] = "budget_exhausted"
                        break
                    vector = next_vector(record)
                    if vector is None:
                        record["stop_reason"] = ("improved_pending_review" if record["best"] else
                                                 "no_improvement" if record["baseline"]["legal"] else "no_feasible_candidate")
                        break
                    run_trial(project, state, folder, record, vector, policy)
                    if record["stop_reason"] != "running":
                        break
            if record["stop_reason"] in TERMINAL and record["stop_reason"] not in {"outcome_unknown", "incomparable"}:
                if record["budget"]["exports_reserved"]-before <= 2:
                    finalize(project, state, folder, record, policy)
            response = output(project, state, folder, record)
            record["requests"][request].update(status="completed", response=response)
            save(folder, record)
            return response
        except Exception:
            record["stop_reason"] = "outcome_unknown"
            save(folder, record)
            raise
        finally:
            reservation_context.__exit__(None, None, None)
