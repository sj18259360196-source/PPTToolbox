"""Managed text-fit path checks. Synthetic receipts do not certify Office."""
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from common import write_json
from native_practice import CANVAS, make_cases
from toolbox_manager.execution import registered_context
from toolbox_manager.policy import PolicyDenied
from toolbox_manager.service import Manager


@pytest.fixture
def context(tmp_path):
    manager = Manager(tmp_path / "data", root=ROOT, home=tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    manager.authorize_project(project, [])
    write_json(project / "scene.json", {"version": "1.0", "canvas": CANVAS,
                                       "slides": [make_cases()[0][0]]})
    Image.new("RGB", (960, 540), "white").save(project / "ref.png")
    write_json(project / "references.json", {"basic-shapes": str(project / "ref.png")})
    write_json(project / "plan/plan.json", {"source_path": str(project / "scene.json"),
               "references": {"basic-shapes": {"path": str(project / "ref.png")}}})
    write_json(project / "plan/source.scene.json", {})
    (project / "plan/specimens.pptx").write_bytes(b"policy fixture only")
    write_json(project / "office/office-render.json", {"slides": [{"file": "slide-001.png"}]})
    (project / "office/slide-001.png").write_bytes(b"policy fixture only")
    return manager, project


def arguments(tid, output):
    if tid == "ops.text-fit-plan":
        return ["--scene", "scene.json", "--references", "references.json", "--outdir", str(output)]
    return ["--plan", "plan", "--office", "office", "--output", str(output)]


@pytest.mark.parametrize("inline", [False, True])
def test_evaluation_output_cannot_escape_project(context, tmp_path, inline):
    manager, project = context
    target = tmp_path / "outside.json"
    args = arguments("ops.text-fit-evaluate", target)
    if inline:
        args = args[:-2] + ["--output=" + str(target)]
    with pytest.raises(PolicyDenied, match="Output must stay"):
        registered_context(manager, "ops.text-fit-evaluate", args, project)
    assert not target.exists()


@pytest.mark.parametrize("tid", ["ops.text-fit-plan", "ops.text-fit-evaluate", "ops.path-office-evaluate"])
def test_supported_paths_keep_project_binding(context, tid):
    manager, project = context
    assert registered_context(manager, tid, arguments(tid, "new-result"), project) == project


@pytest.mark.parametrize("tid", ["ops.text-fit-plan", "ops.text-fit-evaluate", "ops.path-office-evaluate"])
@pytest.mark.parametrize("output", ["input/result.json", "."])
def test_immutable_output_locations_rejected(context, tid, output):
    manager, project = context
    with pytest.raises(PolicyDenied, match="Immutable"):
        registered_context(manager, tid, arguments(tid, output), project)


@pytest.mark.parametrize("field", ["source_path", "reference", "office_image", "references_map"])
def test_indirect_inputs_cannot_escape_project(context, tmp_path, field):
    manager, project = context
    outside = tmp_path / "outside"
    outside.write_bytes(b"private fixture")
    tid = "ops.text-fit-evaluate"
    if field == "references_map":
        tid = "ops.text-fit-plan"
        write_json(project / "references.json", {"basic-shapes": str(outside)})
    elif field == "office_image":
        write_json(project / "office/office-render.json", {"slides": [{"file": str(outside)}]})
    else:
        plan = json.loads((project / "plan/plan.json").read_text(encoding="utf-8"))
        if field == "source_path":
            plan["source_path"] = str(outside)
        else:
            plan["references"]["basic-shapes"]["path"] = str(outside)
        write_json(project / "plan/plan.json", plan)
    with pytest.raises(PolicyDenied, match="outside"):
        registered_context(manager, tid, arguments(tid, "new-result"), project)


@pytest.mark.parametrize("tid", ["ops.text-fit-plan", "ops.text-fit-evaluate", "ops.path-office-evaluate"])
def test_unknown_or_abbreviated_flags_rejected(context, tid):
    manager, project = context
    for extra in (["--unexpected", "value"], ["--out", "elsewhere"]):
        with pytest.raises(ValueError, match="text-fit arguments"):
            registered_context(manager, tid, arguments(tid, "new-result") + extra, project)


def test_authorized_external_reference_is_allowed(context, tmp_path):
    manager, project = context
    inputs = tmp_path / "approved-inputs"
    inputs.mkdir()
    (inputs / "ref.png").write_bytes(b"policy fixture only")
    manager.authorize_project(project, [inputs])
    write_json(project / "references.json", {"basic-shapes": str(inputs / "ref.png")})
    assert registered_context(manager, "ops.text-fit-plan",
                              arguments("ops.text-fit-plan", "new-result"), project) == project


def test_registered_plan_executes_in_isolated_manager(context):
    manager, project = context
    manager.save_settings({"revision": 0, "values": {"agent_execution_enabled": True}})
    result = manager.execute("ops.text-fit-plan",
        ["--project", str(project), *arguments("ops.text-fit-plan", "generated-plan")])
    assert result["command_status"] == "completed", result
    assert (project / "generated-plan/specimens.pptx").is_file()
    assert (project / "generated-plan/plan.json").is_file()
