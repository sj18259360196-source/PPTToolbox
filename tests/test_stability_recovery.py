"""Bounded recovery tests, never Office or visual acceptance."""
import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from common import read_json,write_json,sha256
from workflow_store import FORMAT,load,WorkflowError
from workflow_recovery import context
import workflow


@pytest.fixture
def fixture(tmp_path):
    p=tmp_path/"project";(p/"workflow/tasks/task-000001").mkdir(parents=True)
    (p/"workflow/results").mkdir();(p/"runs/run-0001").mkdir(parents=True)
    (p/"input").mkdir();(p/"input/ref.png").write_bytes(b"frozen-reference")
    mapping={"scale_x":1,"scale_y":1,"offset_x":0,"offset_y":0}
    slide={"id":"slide-001","reference":"input/ref.png","review_mapping":mapping,
           "objects":[{"id":"slide-001.body.text","kind":"text","text":"21","bbox":[20,20,80,40]}]}
    canvas={"width":200,"height":100,"width_pt":200,"height_pt":100,"mapping":"uniform"}
    scene={"version":"1.0","canvas":canvas,"slides":[slide]}
    plan={"regions":[{"id":"body","bbox":[0,0,200,100],"role":"content","summary":"original"}]}
    packet={"format":"ppt-task/1.2","project_id":"p","context":{"reference_size":[200,100]},
            "input_files":[{"file":"input/ref.png","sha256":sha256(p/"input/ref.png")}]}
    write_json(p/"workflow/tasks/task-000001/packet.json",packet)
    rec={"task_id":"task-000001","kind":"page_plan","target":{"slide_id":"slide-001"},
         "base_revision":1,"result":plan,"packet_sha256":sha256(p/"workflow/tasks/task-000001/packet.json")}
    write_json(p/"workflow/results/task-000001.json",rec)
    write_json(p/"runs/run-0001/scene.json",scene)
    page={"id":"slide-001","index":1,"reference":"input/ref.png","sha256":sha256(p/"input/ref.png"),
          "size":[200,100],"plan":None,"imported_slide":slide,"fragments":{},"source_review":{"status":"passed"}}
    state={"format":FORMAT,"project_id":"p","revision":8,"status":"awaiting_visual_review",
           "canvas":canvas,"pages":[page],"asset_jobs":[],
           "accepted":[{"file":"workflow/results/task-000001.json","sha256":sha256(p/"workflow/results/task-000001.json")}],
           "run":{"id":"run-0001","dir":"runs/run-0001","frozen":{"scene.json":sha256(p/"runs/run-0001/scene.json")},
                  "reviews":{"full:slide-001":{"status":"passed"}}},
           "active_task":None,"history":[]}
    write_json(p/"workflow/state.json",state)
    return p,state,page,slide


def test_context_restores_bound_authority_not_verdicts(fixture):
    p,s,page,slide=fixture
    c=context(p,s,page,slide)
    assert c["planning_state"]=="valid" and c["planning_basis"]=="task-000001"
    assert set(c)=={"plan","mapping","planning_state","planning_basis"}
    assert page["plan"] is None


@pytest.mark.parametrize("change",["geometry","canvas","mapping","reference","no_plan","invalidated","packet"])
def test_context_rejects_changed_or_missing_basis(fixture,change):
    p,s,page,slide=fixture
    if change=="geometry":slide["objects"][0]["bbox"][0]+=200
    elif change=="canvas":s["canvas"]["width"]+=1
    elif change=="mapping":slide["review_mapping"]["offset_x"]=1
    elif change=="reference":page["sha256"]="0"*64
    elif change=="no_plan":s["accepted"]=[]
    elif change=="packet":(p/"workflow/tasks/task-000001/packet.json").write_text("{}")
    else:s["history"]=[{"revision":5,"event":"region_reopened","detail":{"slide_id":"slide-001","region_id":None}}]
    with pytest.raises((WorkflowError,ValueError)):context(p,s,page,slide)


def test_regional_revise_preserves_pair_invalidates_reviews_and_restarts(fixture):
    p,s,page,slide=fixture
    before=sha256(p/"runs/run-0001/scene.json")
    r=workflow.revise(p,"slide-001","body","Explicit same-input recovery")
    after=load(p)
    assert r["revision"]==9
    assert after["run"]["reviews"]=={} and after["pages"][0]["source_review"] is None
    assert after["pages"][0]["mapping"]["scale_x"]==1
    assert sha256(p/"runs/run-0001/scene.json")==before
    assert load(p)==after


def test_failed_atomic_commit_keeps_original_state(fixture,monkeypatch):
    p,*_=fixture;before=(p/"workflow/state.json").read_bytes()
    def fail(*args,**kw):raise OSError("injected persistence failure")
    monkeypatch.setattr(workflow,"save",fail)
    with pytest.raises(OSError):workflow.revise(p,"slide-001","body","Test")
    assert (p/"workflow/state.json").read_bytes()==before
    assert not (p/"workflow/writer.lock").exists()


def test_full_revise_explicitly_requires_new_plan(fixture):
    p,*_=fixture
    workflow.revise(p,"slide-001",None,"Explicit geometry replan")
    page=load(p)["pages"][0]
    assert page["plan"] is None and page.get("imported_slide") is None
    assert page["planning_state"]=="awaiting_replanning"


def test_missing_run_recovery_does_not_guess_pair(fixture):
    p,s,*_=fixture;s["run"]=None;write_json(p/"workflow/state.json",s)
    before=(p/"workflow/state.json").read_bytes()
    with pytest.raises(WorkflowError,match="current paired run"):
        workflow.revise(p,"slide-001","body","Test")
    assert (p/"workflow/state.json").read_bytes()==before
