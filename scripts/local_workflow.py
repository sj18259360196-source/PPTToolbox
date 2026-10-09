"""Project-attached trials; original workflow state remains the sole authority."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

from PIL import Image
from common import read_json, write_json, sha256, resolve_asset, walk_objects
from workflow_store import locked, load, save, brief, check_packet, under, WorkflowError, now
from workflow_scene import compile_fragment, import_file
from workflow_evidence import render_local, file_record
from evidence_contract import logical_bounds
from build_pptx import build
from inspect_pptx import inspect
from compare_images import compare
from visual_regression import compare_changes
from local_edit import prepare, surgical_write, properties, semantic_nodes, part_diff, office_roundtrip, equivalent

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def bundle(scene, source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    deps = set(s["reference"] for s in scene["slides"])
    for s in scene["slides"]:
        deps.update(u['source']['asset'] for u in s.get('element_scope', {}).get('units', []) if 'source' in u)
        deps.update(o["asset"] for o in walk_objects(s["objects"]) if o["kind"] == "image")
    for relative in deps:
        path = resolve_asset(source, relative)
        dest = destination/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    write_json(destination/"scene.json", scene)
    return destination/"scene.json"


def verify_files(folder, record):
    for rel, digest in record.get("files", {}).items():
        if sha256(under(folder, rel)) != digest:
            raise WorkflowError("trial_changed", "Trial output or frozen input changed")


def trial(project, tid):
    folder = project/"trials"/tid
    record = read_json(under(folder, "record.json"))
    verify_files(folder, record)
    return folder, record


def check_base(project, state, record):
    if record["project_id"] != state["project_id"] or record["base_revision"] != state["revision"]:
        raise WorkflowError("stale_trial", "Trial project/revision no longer current")
    if record["state_sha256"] != sha256(project/"workflow/state.json"):
        raise WorkflowError("stale_trial", "Task or baseline identity changed")


def persist(folder, record):
    record["ended_at"] = now()
    record["files"] = {p.relative_to(folder).as_posix(): sha256(p)
                       for p in folder.rglob("*") if p.is_file() and p.name not in {"record.json", "intent.json"}}
    write_json(folder/"record.json", record)
    return record


def public(project, state, record, folder):
    return {**brief(state), "local_status": record["status"], "trial_id": folder.name,
            "record": str(folder/"record.json"), "kind": record["kind"],
            "must_view_files": [str(folder/x) for x in record.get("view_files", [])],
            "outputs": {k: str(folder/record[k]) for k in ("scene", "pptx", "render") if record.get(k)},
            "scope": "Local evidence only; no automatic visual approval or delivery"}


def region_scope(state, slide, rid):
    page = next((p for p in state["pages"] if p["id"] == slide), None)
    if not page or not page.get("plan"):
        raise ValueError("Patch requires an existing analyzed page/region authorization")
    region = next((r for r in page["plan"]["regions"] if r["id"] == rid), None)
    if not region:
        raise ValueError("Unknown existing region")
    return page, region


def constrain(objects, page, region):
    m = page["mapping"]
    box = region["bbox"]
    for obj in objects:
        x0, y0, x1, y1 = logical_bounds(obj)
        actual = [x0*m["scale_x"]+m["offset_x"], y0*m["scale_y"]+m["offset_y"],
                  x1*m["scale_x"]+m["offset_x"], y1*m["scale_y"]+m["offset_y"]]
        if actual[0] < box[0]-.01 or actual[1] < box[1]-.01 or actual[2] > box[2]+.01 or actual[3] > box[3]+.01:
            raise ValueError("Object geometry leaves the existing region")


def render(folder, scene, pptx, name="office"):
    result = render_local(pptx, scene, folder/name, ROOT/"scripts/render_powerpoint.ps1")
    return result


def probe(project, state, args, folder, record, policy):
    task = state.get("active_task")
    if not task or task["kind"] != "region_objects" or task["id"] != args["task_id"]:
        raise ValueError("Probe requires current region_objects task")
    check_packet(project, state, task)
    page, region = region_scope(state, task["target"]["slide_id"], task["target"]["region_id"])
    if args["result"].get("action"):
        raise ValueError("Probe needs actual objects/components, not an asset request")
    policy.require("pptx.validate", "pptx.build", "pptx.inspect", "assets.crop")
    if args["result"].get("components"):
        policy.require("ops.component")
    if args.get("office", True):
        policy.require("office.render")
    fragment = compile_fragment(page, region, args["result"], state["canvas"], project)
    constrain(fragment["objects"], page, region)
    scene = {"version": "1.0", "canvas": state["canvas"], "slides": [{
        "id": page["id"], "reference": page["reference"], "objects": fragment["objects"],
        "review_mapping": page["mapping"]}]}
    scene_path = bundle(scene, project, folder/"bundle")
    write_json(folder/"fragment.json", fragment)
    with Image.open(project/page["reference"]) as im:
        im.crop(region["bbox"]).save(folder/"reference-region.png")
    build(scene_path, folder/"sample.pptx")
    audit = inspect(folder/"sample.pptx", scene_path)
    write_json(folder/"audit.json", audit)
    if any(c["status"] == "failed" for c in audit["checks"].values()):
        raise ValueError("Probe structure does not match fragment")
    record.update(scene="bundle/scene.json", pptx="sample.pptx", fragment="fragment.json",
                  task_id=task["id"], task_packet_sha256=task["packet_sha256"],
                  slide=page["id"], region=region["id"], region_bbox=region["bbox"],
                  object_ids=[o["id"] for o in walk_objects(fragment["objects"])],
                  units="Local reference px -> original canvas mapping; full-canvas physical size retained",
                  status="awaiting_office", view_files=["reference-region.png"])
    if args.get("office", True):
        rendered = render(folder, scene_path, folder/"sample.pptx")
        if rendered["status"] == "passed":
            record.update(status="ready_to_compare", render="office/office-render.json")
    return record


def patch(project, state, args, folder, record, policy):
    policy.require("ops.patch-pptx", "pptx.validate", "pptx.build", "pptx.inspect",
                   "office.render", "office.edit-readback")
    run = state.get("run")
    if not run or not run.get("candidate") or state["status"] == "delivered":
        raise ValueError("Patch needs a current undelivered candidate")
    scope=run.get('revision_source')
    if scope and (args['slide']!=scope['slide'] or args['region']!=scope['region']):
        raise ValueError('Patch must stay within the selected revision region')
    scene_path = under(project, run["dir"]+"/scene.json")
    source = under(project, run["candidate"]["file"])
    if sha256(scene_path) != args["scene_sha256"] or sha256(source) != args["pptx_sha256"]:
        raise WorkflowError("stale_trial", "Baseline scene/PPTX hashes differ")
    page, region = region_scope(state, args["slide"], args["region"])
    scene = read_json(scene_path)
    target = next(s for s in scene["slides"] if s["id"] == args["slide"])
    prefix = page["id"]+"."+region["id"]+"."
    allowed = {o["id"] for o in walk_objects(target["objects"]) if o["id"].startswith(prefix)}
    if any(c["op"] == "native.topology" for c in args["changes"]):
        if any(c["op"] != "native.topology" for c in args["changes"]) or record.get("calibration_id"):
            raise ValueError("Topology cannot mix format/calibration operations in one trial")
        if len(args["changes"]) > 1:
            return topology_batch(scene_path,source,page,region,allowed,args,folder,record)
        return topology_patch(scene_path, source, page, region, allowed, args, folder, record)
    prs, updated, index, touched = prepare(scene_path, source, args["slide"], allowed, args["changes"],
                                         calibration=bool(record.get("calibration_id")))
    constrain([o for o in walk_objects(updated["slides"][index]["objects"]) if o["id"] in touched], page, region)
    native_edit = any(c["op"] == "native.format" for c in args["changes"])
    if native_edit:
        from native_format import effect_margin
        from common import bbox_to_points
        margins = {}
        for oid in touched:
            versions = [next(o for o in slide["objects"] if o["id"] == oid)
                        for slide in (scene["slides"][index], updated["slides"][index])]
            margins[oid] = max(effect_margin(o.get("style", {}).get("native_format", {}))
                               for o in versions)
            for target in versions:
                x, y, w, h = bbox_to_points(target["bbox"], scene["canvas"])
                m = margins[oid]
                for neighbor in scene["slides"][index]["objects"]:
                    if neighbor["id"] in touched:
                        continue
                    if "bbox" not in neighbor:
                        raise ValueError("Native effect neighbor lacks a supported bounding box")
                    nx, ny, nw, nh = bbox_to_points(neighbor["bbox"], scene["canvas"])
                    if x-m < nx+nw and nx < x+w+m and y-m < ny+nh and ny < y+h+m:
                        raise ValueError("Predeclared native effect envelope intersects a protected neighbor")
        record["effect_margins_pt"] = margins
    new_scene = bundle(updated, scene_path.parent, folder/"bundle")
    before_scene = bundle(scene, scene_path.parent, folder/"baseline")
    shutil.copyfile(source, folder/"baseline.pptx")
    raw_diff = surgical_write(source, folder/"patched-xml.pptx", prs, index)
    original_nodes, raw_nodes = semantic_nodes(source), semantic_nodes(folder/"patched-xml.pptx")
    changed_keys = {f"{index}/{oid}" for oid in touched}
    raw_outside = [k for k in original_nodes if k not in changed_keys and original_nodes[k] != raw_nodes.get(k)]
    if raw_outside:
        raise ValueError("Surgical edit modified outside objects")
    range_edit=any(c["op"]=="text.range" for c in args["changes"])
    node_edit=any(c['op']=='native.nodes' for c in args['changes'])
    native_options = {"native": True} if native_edit or range_edit or node_edit else {}
    actual = office_roundtrip(folder/"patched-xml.pptx", folder/"candidate.pptx", folder/"readback.json", **native_options)
    office_roundtrip(folder/"baseline.pptx", folder/"baseline-office.pptx", folder/"baseline-readback.json", **native_options)
    build(new_scene, folder/"rebuild.pptx")
    expected = office_roundtrip(folder/"rebuild.pptx", folder/"rebuild-office.pptx", folder/"rebuild-readback.json", **native_options)
    if node_edit:
        from native_nodes import summary
        a,b=summary(folder/'candidate.pptx'),summary(folder/'rebuild-office.pptx')
        selected={f'{index+1}/{oid}' for oid in touched}
        actual_nodes={k:v for k,v in a.items() if k in selected}
        expected_nodes={k:v for k,v in b.items() if k in selected}
        write_json(folder/'node-readback.json',{'actual':actual_nodes,'rebuild':expected_nodes,
                   'equal':actual_nodes==expected_nodes,'operation':'OOXML node/control-point edit then actual Office save/reopen',
                   'com_receipt':'readback.json','visual_review':'pending'})
        if actual_nodes!=expected_nodes:raise ValueError('Saved node coordinates differ from independent rebuild')
    if range_edit:
        from native_text_range import validate_readback
        checked=validate_readback(args["changes"],read_json(folder/"baseline-readback.json"),
                                  read_json(folder/"readback.json"),read_json(folder/"rebuild-readback.json"))
        write_json(folder/"range-readback.json",{"checks":checked,
                   "indices":"Zero-based BMP code points; half-open within paragraph; COM offset adds one",
                   "layout_scope":"Declared target object old/new bounds; other objects remain protected"})
    if native_edit:
        from native_format import read as read_native
        from local_edit import shapes_by_name
        from pptx import Presentation
        def native_values(path):
            return {f"{i}/{name}": read_native(shape)
                    for (i, name), (shape, parent) in shapes_by_name(Presentation(path)).items()
                    if i == index and name in touched}
        actual_format = native_values(folder/"candidate.pptx")
        rebuilt_format = native_values(folder/"rebuild-office.pptx")
        write_json(folder/"native-readback.json", {"actual": actual_format,
                   "independent_rebuild": rebuilt_format, "equal": actual_format == rebuilt_format})
        if actual_format != rebuilt_format:
            raise ValueError("Saved native effects differ from independent scene rebuild")
    mismatches = [k for k in actual if not equivalent(actual[k], expected.get(k))]
    if set(actual) != set(expected) or mismatches:
        write_json(folder/"consistency-failure.json", {"actual": actual, "expected": expected, "mismatches": mismatches})
        raise ValueError("Persisted candidate differs from independent updated-scene rebuild")
    before_nodes, after_nodes = semantic_nodes(folder/"baseline-office.pptx"), semantic_nodes(folder/"candidate.pptx")
    outside = [k for k in before_nodes if k not in changed_keys and before_nodes[k] != after_nodes.get(k)]
    structure = {"status": "passed" if not outside and set(before_nodes) == set(after_nodes) else "failed",
                 "outside_objects": outside, "before": before_nodes, "after": after_nodes,
                 "raw_package_diff": raw_diff, "office_package_diff": part_diff(folder/"baseline-office.pptx", folder/"candidate.pptx"),
                 "ignored_metadata": ["creationId", "modId"], "backend": "surgical_slide_OOXML",
                 "scene_rebuild_role": "Independent consistency test only"}
    write_json(folder/"structure.json", structure)
    if structure["status"] != "passed":
        raise ValueError("Office semantic outside-object regression")
    record.update(scene="bundle/scene.json", pptx="candidate.pptx", baseline_scene="baseline/scene.json",
                  baseline_pptx="baseline-office.pptx", status="ready_to_compare",
                  slide=args["slide"], slide_index=index+1, region=args["region"],
                  region_bbox=region["bbox"], object_ids=touched, changes=args["changes"],
                  base_scene_sha256=args["scene_sha256"], base_pptx_sha256=args["pptx_sha256"],
                  structural_consistency="passed", backend="surgical_slide_OOXML",
                  crop_contract="source_crop uses original asset pixels -> OOXML crop fractions; no guessed Crop* pt conversion")
    return record


def topology_batch(scene_path,source,page,region,allowed,args,folder,record):
    from native_topology import preflight
    seen=set()
    prefixes=set()
    for change in args["changes"]:
        _,_,names=preflight(scene_path,source,args["slide"],allowed,change)
        if names&seen or change["output_prefix"] in prefixes:
            raise ValueError("Batched topology requires disjoint original inputs and output prefixes")
        seen.update(names)
        prefixes.add(change["output_prefix"])
    original_scene,original_source=scene_path,source
    results=[]
    for i,change in enumerate(args["changes"]):
        step=folder/f"step-{i:02}"
        step.mkdir()
        r=topology_patch(scene_path,source,page,region,allowed,{**args,"changes":[change]},step,{})
        results.append(r)
        scene_path=step/r["scene"]
        source=step/r["pptx"]
    last=results[-1]
    record.update(last)
    record.update(scene=f"step-{len(results)-1:02}/"+last["scene"],
        pptx=f"step-{len(results)-1:02}/"+last["pptx"],
        baseline_scene="step-00/baseline/scene.json",baseline_pptx="step-00/baseline-office.pptx",
        object_ids=sorted({n for r in results for n in r["object_ids"]}),
        topology_envelopes_pt=[b for r in results for b in r["topology_envelopes_pt"]],
        changes=args["changes"],base_scene_sha256=sha256(original_scene),base_pptx_sha256=sha256(original_source),
        topology_mapping=[f"step-{i:02}/topology-readback.json" for i in range(len(results))])
    return record


def topology_patch(scene_path, source, page, region, allowed, args, folder, record):
    from native_topology import preflight, _owned_operation, output_scene, protected_check
    from native_format import effect_margin
    change=args["changes"][0]
    scene,index,touched=preflight(scene_path,source,args["slide"],allowed,change)
    prefix=page["id"]+"."+region["id"]+"."+change["output_prefix"]
    # Declare effect envelopes before Office; translate only when explicitly requested.
    old_props=properties(source)
    boxes=[]
    dx,dy=change.get("delta",[0,0])
    members={o["id"]:o for o in walk_objects(scene["slides"][index]["objects"])}
    for name in touched:
        p=old_props[f"{index}/{name}"]
        if p["type"]==6:
            continue
        margin=effect_margin(members[name].get("style",{}).get("native_format",{}))
        x,y,w,h=p["bbox_pt"]
        for ox,oy in ((0,0),(dx,dy)):
            boxes.append([x+ox-margin,y+oy-margin,x+ox+w+margin,y+oy+h+margin])
    write_json(folder/"topology-policy.json",{"envelopes_pt_xyxy":boxes,"fringe_px":2,
               "source":"Before actual edit: leaf geometry plus typed effect margin and requested translation",
               "forbidden":"No post-hoc difference-derived mask"})
    office_roundtrip(source,folder/"baseline-office.pptx",folder/"baseline-readback.json",native=True)
    _owned_operation(folder/"baseline-office.pptx",folder/"topology-office.pptx",index,change,prefix)
    actual=office_roundtrip(folder/"topology-office.pptx",folder/"candidate.pptx",folder/"readback.json",native=True)
    updated,outputs,mapping=output_scene(scene,index,folder/"baseline-office.pptx",folder/"candidate.pptx",change,touched,prefix)
    changed_after={o["id"] for top in updated["slides"][index]["objects"] if top["id"] in outputs
                   for o in walk_objects([top])}
    constrain([o for o in updated["slides"][index]["objects"] if o["id"] in outputs],page,region)
    mapping["protected_objects_unchanged"]=protected_check(folder/"baseline-office.pptx",
                                                           folder/"candidate.pptx",index,touched,changed_after)
    write_json(folder/"topology-readback.json",mapping)
    if not mapping["protected_objects_unchanged"]:
        raise ValueError("Protected content or relative stacking changed during topology")
    before_scene=bundle(scene,scene_path.parent,folder/"baseline")
    new_scene=bundle(updated,scene_path.parent,folder/"bundle")
    build(new_scene,folder/"rebuild.pptx")
    expected=office_roundtrip(folder/"rebuild.pptx",folder/"rebuild-office.pptx",folder/"rebuild-readback.json",native=True)
    # Numeric IDs change when consumed objects are reconstructed; all other properties remain checked.
    normalized=lambda rows:{k:{n:v for n,v in p.items() if n!="shape_id"} for k,p in rows.items()}
    a,b=normalized(actual),normalized(expected)
    mismatch=[k for k in a if not equivalent(a[k],b.get(k))]
    write_json(folder/"topology-consistency.json",{"mismatches":mismatch,"actual":a,"rebuilt":b})
    if a.keys()!=b.keys() or mismatch:
        raise ValueError("Topology candidate differs from independent scene reconstruction")
    from native_format import read as read_native
    from local_edit import shapes_by_name
    from pptx import Presentation
    def formats(path,names):
        return {name:read_native(shape) for (si,name),(shape,parent) in shapes_by_name(Presentation(path)).items()
                if si==index and name in names and shape.shape_type!=6}
    actual_formats=formats(folder/"candidate.pptx",changed_after)
    rebuilt_formats=formats(folder/"rebuild-office.pptx",changed_after)
    source_formats=formats(folder/"baseline-office.pptx",touched)
    retained=all(actual_formats.get(k)==v for k,v in source_formats.items()) if change["action"] not in {
        "union","combine","intersect","subtract","fragment"} else None
    write_json(folder/"topology-style.json",{"actual":actual_formats,"rebuilt":rebuilt_formats,
               "source":source_formats,"rebuild_equal":actual_formats==rebuilt_formats,"member_styles_retained":retained})
    if actual_formats!=rebuilt_formats or retained is False:
        raise ValueError("Topology dropped or changed tracked native styles")
    record.update(scene="bundle/scene.json",pptx="candidate.pptx",baseline_scene="baseline/scene.json",
        baseline_pptx="baseline-office.pptx",status="ready_to_compare",slide=args["slide"],slide_index=index+1,
        region=args["region"],region_bbox=region["bbox"],object_ids=sorted(touched|changed_after),
        changes=args["changes"],base_scene_sha256=args["scene_sha256"],base_pptx_sha256=args["pptx_sha256"],
        structural_consistency="passed",backend="PowerPoint_native_topology",
        topology_envelopes_pt=boxes,topology_mapping="topology-readback.json")
    return record


def compare_trial(project, state, args, folder, record, policy):
    policy.require("office.render", "compare.page")
    tf, tr = trial(project, args["trial_id"])
    check_base(project, state, tr)
    if tr["kind"] not in {"probe", "patch"} or tr["status"] not in {"ready_to_compare", "awaiting_office"}:
        raise ValueError("Trial is not a usable candidate")
    if tr["kind"] == "patch":
        policy.require("ops.regression")
    scene = tf/tr["scene"]
    rendered = render(folder, scene, tf/tr["pptx"])
    if rendered["status"] != "passed":
        record.update(status="awaiting_office", trial_id=args["trial_id"])
        return record
    env = read_json(folder/"office/office-render.json")
    view = []
    checks = []
    data = read_json(scene)
    for i, s in enumerate(data["slides"], 1):
        ref = resolve_asset(scene.parent, s["reference"])
        regions = [{"id": "target", "bbox": tr["region_bbox"]}] if s["id"] == tr["slide"] else []
        comp = compare(ref, folder/f"office/slide-{i:03}.png", folder/f"reference-{i:03}", regions)
        view.extend([f"reference-{i:03}/full-side-by-side.png"])
        if regions:
            view.append(f"reference-{i:03}/target-side-by-side.png")
        checks.append(comp)
    record.update(trial_id=args["trial_id"], trial_record_sha256=sha256(tf/"record.json"),
                  reference_comparisons=checks, view_files=view, status="awaiting_observation",
                  structural_consistency=tr.get("structural_consistency", "passed"),
                  outside_regression="not_applicable")
    if tr["kind"] == "patch":
        baseline = render(folder, tf/tr["baseline_scene"], tf/tr["baseline_pptx"], "baseline-office")
        if baseline["status"] != "passed":
            record["status"] = "awaiting_office"
            return record
        old_env = read_json(folder/"baseline-office/office-render.json")
        equal_env = {k: env.get(k) for k in ("renderer", "office_version")} == {k: old_env.get(k) for k in ("renderer", "office_version")}
        threshold = {"threshold": 0, "max_outside_fraction": 0, "margin": 0,
                     "rule": "Union of each edited leaf's old/new bounds plus half line width and fixed 2px antialias fringe; effects rejected"}
        if tr.get("effect_margins_pt"):
            threshold["rule"] = "Predeclared typed effects:3*blur+max(offset), bounded front-view3D; protected neighbor intersections rejected before patch"
            threshold["effect_margins_pt"] = tr["effect_margins_pt"]
        write_json(folder/"regression-policy.json", threshold)
        old, new = properties(tf/tr["baseline_pptx"]), properties(tf/tr["pptx"])
        results = []
        for i, s in enumerate(data["slides"], 1):
            with Image.open(folder/f"office/slide-{i:03}.png") as im:
                width, height = im.size
            boxes = []
            if i == tr["slide_index"] and tr.get("topology_envelopes_pt") is not None:
                sx,sy=width/data["canvas"]["width_pt"],height/data["canvas"]["height_pt"]
                for x0,y0,x1,y1 in tr["topology_envelopes_pt"]:
                    boxes.append({"id":f"topology-{len(boxes)}","bbox":[max(0,math.floor(x0*sx)-2),
                        max(0,math.floor(y0*sy)-2),min(width,math.ceil(x1*sx)+2),min(height,math.ceil(y1*sy)+2)]})
            if i == tr["slide_index"]:
                for oid in ([] if "topology_envelopes_pt" in tr else tr["object_ids"]):
                    key = f"{i-1}/{oid}"
                    if old[key]["type"] == 6:
                        continue  # Group envelope must not mask gaps between members.
                    for props in (old[key], new[key]):
                        x, y, w, h = props["bbox_pt"]
                        sx, sy = width/data["canvas"]["width_pt"], height/data["canvas"]["height_pt"]
                        mx, my = math.ceil(props.get("line_width_pt", 0)*sx/2)+2, math.ceil(props.get("line_width_pt", 0)*sy/2)+2
                        effect = tr.get("effect_margins_pt", {}).get(oid, 0)
                        mx += math.ceil(effect*sx)
                        my += math.ceil(effect*sy)
                        b = [max(0, math.floor(x*sx)-mx), max(0, math.floor(y*sy)-my),
                             min(width, math.ceil((x+w)*sx)+mx), min(height, math.ceil((y+h)*sy)+my)]
                        boxes.append({"id": f"object-{len(boxes)}", "bbox": b})
            if boxes:
                from text_regression import scope as text_scope
                measured = text_scope(old_env, env, old, new,
                    tr['object_ids'] if i == tr['slide_index'] else [], i, data['canvas'], (width,height),
                    (sha256(tf/tr['baseline_pptx']),sha256(tf/tr['pptx'])))
                boxes.extend(measured['boxes'])
                r = compare_changes(folder/f"baseline-office/slide-{i:03}.png", folder/f"office/slide-{i:03}.png",
                                    boxes, folder/f"regression-{i:03}", threshold=0, max_outside_fraction=0, margin=0,
                                    environment_before=old_env.get("office_version"), environment_after=env.get("office_version"))
                r['text_scope'] = measured
                ok = r["status"] == "no_excess_outside_change" and equal_env and measured['status']=='measured'
                view.append(f"regression-{i:03}/before-after.png")
                view.append(f"regression-{i:03}/outside-changes.png")
            else:
                ok = sha256(folder/f"baseline-office/slide-{i:03}.png") == sha256(folder/f"office/slide-{i:03}.png") and equal_env
                r = {"status": "unchanged" if ok else "changed", "slide": i}
            results.append({"passed": ok, "report": r})
        record.update(outside_regression="passed" if all(r["passed"] for r in results) else "failed",
                      regressions=results, view_files=view)
    return record


def adopt(project, state, args, folder, record, policy):
    tf, tr = trial(project, args["trial_id"])
    cf, cr = trial(project, args["comparison_id"])
    if tr.get("calibration_id"):
        from calibration import adoption_guard
        adoption_guard(project, tr, args["trial_id"], args["observation"]["viewed_files"])
    check_base(project, state, tr)
    check_base(project, state, cr)
    if cr.get("trial_id") != args["trial_id"] or cr.get("trial_record_sha256") != sha256(tf/"record.json"):
        raise ValueError("Comparison does not bind this trial")
    if cr["status"] != "awaiting_observation" or cr["structural_consistency"] != "passed" or cr["outside_regression"] not in {"passed", "not_applicable"}:
        raise ValueError("Hard validation failed or Office evidence missing")
    observed = args["observation"]
    viewed = {str(policy.input(x)) for x in observed["viewed_files"]}
    if not {str((cf/x).resolve()) for x in cr["view_files"]} <= viewed:
        raise ValueError("Observation missing mandatory full/local/regression files")
    import workflow as wf
    marker = {"fingerprint": record["fingerprint"], "trial_id": args["trial_id"],
              "comparison_id": args["comparison_id"], "observation": observed,
              "record": str(folder/"record.json")}
    if tr["kind"] == "probe":
        policy.require("workflow.submit")
        task = state.get("active_task")
        if not task or task["id"] != tr["task_id"] or task["packet_sha256"] != tr["task_packet_sha256"]:
            raise ValueError("Probe is not attached to current task")
        fragment = read_json(tf/tr["fragment"])
        wf.submit(project, {"task_id": task["id"], "token": task["token"], "result": fragment["raw"]},
                  expected_revision=state["revision"], lock_held=True,
                  adoption=(args["operation_id"], marker))
    elif tr["kind"] == "patch":
        policy.require("pptx.validate", "pptx.inspect")
        scene = read_json(tf/tr["scene"])
        if [s["id"] for s in scene["slides"]] != [p["id"] for p in state["pages"]]:
            raise ValueError("Adoption page identities differ")
        # A single atomic state write publishes the pair and invalidates all reviews.
        updated = copy.deepcopy(state)
        wf._invalidate_run(updated, "Explicit local candidate adoption")
        for page, slide in zip(updated["pages"], scene["slides"]):
            from element_scope import compiled_scope, validate_plan, validate_outputs
            old_scope = compiled_scope(page)
            if old_scope is not None:
                if slide.get('element_scope') != old_scope:
                    raise ValueError('element_scope: local adoption cannot change scope; revise the page')
                validate_plan(old_scope, project=(tf/tr['scene']).parent, compiled=True)
                validate_outputs(old_scope, slide['objects'], (tf/tr['scene']).parent)
            if sha256(resolve_asset((tf/tr["scene"]).parent, slide["reference"])) != page["sha256"]:
                raise ValueError("Adoption reference changed")
            page["imported_slide"] = slide
            page["source_review"] = None
        updated["builder"] = "external"
        updated["pending_candidate"] = file_record(project, tf/tr["pptx"])
        updated.setdefault("tracked_inputs", {})[str((tf/tr["pptx"]).relative_to(project).as_posix())] = sha256(tf/tr["pptx"])
        updated.setdefault("local_adoptions", {})[args["operation_id"]] = marker
        save(project, updated, "local_pair_adopted", {"operation_id": args["operation_id"], "trial_id": args["trial_id"]})
    else:
        raise ValueError("Not an adoptable trial")
    record.update(status="adopted", trial_id=args["trial_id"], comparison_id=args["comparison_id"],
                  revision_after=load(project)["revision"])
    return record


def execute_local(command, project, args, policy):
    policy.require("workflow."+command)
    with locked(project):
        state = load(project)
        if state.get("operation") or state.get("failure"):
            raise WorkflowError("interrupted_operation", "Resolve main workflow failure before local work")
        folder = project/"trials"/args["operation_id"]
        digest = fingerprint({"command": command, "arguments": args})
        adopted = state.get("local_adoptions", {}).get(args["operation_id"])
        if adopted:
            if adopted["fingerprint"] != digest or command != "adopt":
                raise ValueError("Operation ID reused with different content")
            return {**brief(state), "local_status": "adopted", "idempotent": True,
                    "recovery": "Atomic main state already committed; no adoption replay"}
        if folder.exists():
            intent = read_json(folder/"intent.json")
            if intent["fingerprint"] != digest:
                raise ValueError("Operation ID reused with different content")
            if not (folder/"record.json").exists():
                return {**brief(state), "command_status": "outcome_unknown",
                        "local_status": "interrupted_trial", "trial_directory": str(folder)}
            stored = read_json(folder/"record.json")
            check_base(project, state, stored)
            verify_files(folder, stored)
            return public(project, state, stored, folder)
        if command in {"probe", "patch"}:
            if args["base_revision"] != state["revision"]:
                raise WorkflowError("stale_trial", "Base revision differs")
            scope = (state.get("active_task") or {}).get("target", {}) if command == "probe" else {"slide_id": args["slide"], "region_id": args["region"]}
            trials = [read_json(p) for p in (project/"trials").glob("*/intent.json")]
            if sum(r.get("budget_scope") == scope and r.get("kind") in {"probe", "patch"} for r in trials) >= 6:
                raise WorkflowError("trial_budget", "Region candidate budget of six reached")
        else:
            scope = None
        record = {"format": "ppt-local-trial/1", "kind": command, "fingerprint": digest,
                  "started_at": now(), "call_id": getattr(policy, "call_id", None),
                  "project_id": state["project_id"], "base_revision": state["revision"],
                  "state_sha256": sha256(project/"workflow/state.json"), "budget_scope": scope,
                  "operation_id": args["operation_id"], "status": "started"}
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder/"intent.json", record)
        try:
            result = {"probe": probe, "patch": patch, "compare": compare_trial, "adopt": adopt}[command](
                project, state, args, folder, record, policy)
            persist(folder, result)
            return public(project, load(project), result, folder)
        except Exception as exc:
            write_json(folder/"failure.json", {"status": "failed", "error_type": type(exc).__name__,
                                               "code": getattr(exc, "code", None), "message": str(exc),
                                               "reason": "No replay; inspect this trial and main state"})
            raise
