"""Recover regional authority only from bound immutable workflow evidence."""
import copy
from common import read_json, sha256, walk_objects
from workflow_store import under, WorkflowError
from workflow_scene import valid_plan
from evidence_contract import review_mapping, logical_bounds


def geometry(slide):
    fields=("kind","bbox","points","commands","rotation","begin","end")
    return {o["id"]:{k:o[k] for k in fields if k in o} for o in walk_objects(slide["objects"])}


def _basis(project, state, page, slide):
    """Validate immutable planning evidence and the reference coordinate system."""
    plans=[]
    for ref in state.get("accepted",[]):
        path=under(project,ref["file"])
        if sha256(path)!=ref["sha256"]:raise WorkflowError("record_changed","Recovery record changed")
        rec=read_json(path)
        if rec["kind"]=="page_plan" and rec["target"]["slide_id"]==page["id"]:
            plans.append(rec)
    if not plans:raise WorkflowError("replanning_required","No accepted regional authority for this imported page")
    rec=plans[-1]
    if any(h["revision"]>rec["base_revision"] and h["event"]=="region_reopened"
           and h.get("detail",{}).get("slide_id")==page["id"]
           and not h.get("detail",{}).get("region_id") for h in state.get("history",[])):
        raise WorkflowError("replanning_required","A later explicit full-page revision invalidated the old plan")
    packet=under(project,f'workflow/tasks/{rec["task_id"]}/packet.json')
    if sha256(packet)!=rec["packet_sha256"]:raise WorkflowError("packet_changed","Original planning packet changed")
    original=read_json(packet)
    if original.get("format")!="ppt-task/1.2":
        raise WorkflowError("replanning_required","Unsupported planning packet version")
    if original["project_id"]!=state["project_id"] or original["context"]["reference_size"]!=page["size"]:
        raise WorkflowError("replanning_required","Planning input identity differs")
    if not any(i["sha256"]==page["sha256"] and i["file"]==page["reference"] for i in original["input_files"]):
        raise WorkflowError("replanning_required","Planning reference identity differs")
    plan=valid_plan(rec["result"],page["size"])
    # The original generated run anchors coordinate meaning and object geometry.
    baseline=None
    for run in state.get("old_runs",[])+([state["run"]] if state.get("run") else []):
        if not run.get("frozen",{}).get("scene.json"):continue
        path=under(project,run["dir"]+"/scene.json")
        if sha256(path)!=run["frozen"]["scene.json"]:
            raise WorkflowError("run_input_changed","Recovery scene changed")
        scene=read_json(path)
        found=next((s for s in scene["slides"] if s["id"]==page["id"]),None)
        if found is not None:
            baseline=(scene,found);break
    if baseline is None or baseline[0]["canvas"]!=state["canvas"]:
        raise WorkflowError("replanning_required","Original canvas cannot justify the retained plan")
    mapping=review_mapping(baseline[0],baseline[1],page["size"])
    if mapping!=review_mapping({"canvas":state["canvas"]},slide,page["size"]):
        raise WorkflowError("replanning_required","Reference mapping changed")
    return rec,plan,baseline[1],mapping


def review_context(project, state, page, slide):
    """Retain semantic review grouping only; never restore editing authority or verdicts."""
    rec,plan,_,mapping=_basis(project,state,page,slide)
    regions=copy.deepcopy(plan["regions"])
    for region in regions:region["object_ids"]=[]
    # Stable regional namespaces also admit newly added objects. Unbound IDs
    # remain uncovered here and receive their own ROI in auto_regions.
    for obj in walk_objects(slide["objects"]):
        matches=[r for r in regions if obj["id"].startswith(page["id"]+"."+r["id"]+".")]
        if matches:max(matches,key=lambda r:len(r["id"]))["object_ids"].append(obj["id"])
    return {"review_plan":{"regions":regions,"mapping":copy.deepcopy(mapping),
                           "basis":rec["task_id"],"notes":plan.get("notes","")}}


def context(project, state, page, slide):
    """No task results, tokens or pass verdicts are restored."""
    rec,plan,baseline,mapping=_basis(project,state,page,slide)
    if set(geometry(baseline)) != set(geometry(slide)):
        raise WorkflowError("replanning_required","Original geometry cannot justify the retained plan")
    for obj in slide["objects"]:
        region=next((r for r in plan["regions"] if obj["id"].startswith(page["id"]+"."+r["id"]+".")),None)
        if region is None:raise WorkflowError("replanning_required","Object has no original regional provenance")
        x0,y0,x1,y1=logical_bounds(obj);m=mapping;b=region["bbox"]
        xy=(x0*m["scale_x"]+m["offset_x"],y0*m["scale_y"]+m["offset_y"],
            x1*m["scale_x"]+m["offset_x"],y1*m["scale_y"]+m["offset_y"])
        if xy[0]<b[0]-.01 or xy[1]<b[1]-.01 or xy[2]>b[2]+.01 or xy[3]>b[3]+.01:
            raise WorkflowError("replanning_required","Geometry leaves the original authorized region")
    return {"plan":copy.deepcopy(plan),"mapping":copy.deepcopy(mapping),
            "planning_state":"valid","planning_basis":rec["task_id"]}
