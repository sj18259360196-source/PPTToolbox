"""Governed construction drafts. No implicit adoption or writes to active candidates."""
from __future__ import annotations
import base64
import copy
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT/"scripts") not in sys.path:
    sys.path.insert(0, str(ROOT/"scripts"))
from graphics_recipe import SCHEMA, compile_recipe, digest, obj, array

S = {"type": "string", "minLength": 1}
VERSION = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
PROJECT = {"project": S}
SPECS = {
    "inspect": ("读取图形构造契约或项目草稿。", obj({**PROJECT, "version": VERSION})),
    "preview": ("计算曲线组、共享边与关联副本预览，不修改 PPT。",
                obj({**PROJECT, "version": VERSION, "recipe": SCHEMA}, ("recipe",))),
    "compile": ("编译原生图形草稿到已授权项目，保留配方与可编辑样件。",
                obj({**PROJECT, "recipe": SCHEMA}, ("project", "recipe"))),
    "regenerate": ("核对草稿及实际 PPT 修改冲突，再生成新的关联副本与共享边。",
                   obj({**PROJECT, "version": VERSION, "recipe": SCHEMA}, ("project", "version", "recipe"))),
    "fit_gradient": ("从有效采样区域拟合原生渐变，报告误差及不可识别项。",
                     obj({"image": {"type": "string", "maxLength": 8_000_000},
                          "mask": {"type": "string", "maxLength": 8_000_000},
                          "models": array({"enum": ["linear", "radial"]}, 2, 1),
                          "max_stops": {"type": "integer", "minimum": 2, "maximum": 5}},
                         ("image",))),
    "validate": ("校验图形草稿文件及当前原生对象，不自动审批视觉。",
                 obj({**PROJECT, "version": VERSION}, ("project", "version"))),
}


def decode_image(value):
    from PIL import Image
    raw = base64.b64decode(value.split(",", 1)[-1], validate=True)
    image = Image.open(io.BytesIO(raw))
    if image.width*image.height > 4_000_000:
        raise ValueError("Image exceeds four million pixels")
    image.load()
    return image


def _load(project, version):
    from .policy import plain_path
    target = plain_path(project/"assets"/"graphics"/version)
    manifest = json.loads((target/"manifest.json").read_text(encoding="utf-8"))
    required = {"compiled.json", "scene.json", "editable.pptx", "editable.build.json",
                "preview.svg", "preview.png", "native-readback.json"}
    if set(manifest.get("files", {})) != required:
        raise ValueError("Incomplete graphics manifest")
    import hashlib
    for name, expected in manifest["files"].items():
        if name == "editable.pptx":
            continue  # Native user edits are checked independently, never hidden by file hashing.
        if hashlib.sha256((target/name).read_bytes()).hexdigest() != expected:
            raise ValueError("Immutable graphics draft changed: "+name)
    result = json.loads((target/"compiled.json").read_text(encoding="utf-8"))
    identity = digest({"recipe": result["recipe"], "objects": result["objects"],
                       "parent": manifest.get("parent"), "compiler": manifest.get("compiler")})
    if manifest.get("version") != version or identity != version:
        raise ValueError("Graphics draft identity mismatch")
    from graphics_preview import readback
    expected = json.loads((target/"native-readback.json").read_text(encoding="utf-8"))
    observed = readback(target/"editable.pptx")
    conflicts = sorted(k for k in expected.keys() | observed.keys() if expected.get(k) != observed.get(k))
    return target, result, conflicts


def call(manager, op, args=None, source="mcp"):
    from jsonschema import Draft202012Validator
    from .policy import PolicyDenied, authorize, plain_path
    from graphics_preview import png, svg, readback
    from graphics_gradient import fit_gradient
    a = args or {}
    if op not in SPECS:
        raise ValueError("Unknown graphics operation")
    Draft202012Validator(SPECS[op][1]).validate(a)
    p = manager.package()
    if not p["enabled"] or not p["trusted"]:
        raise PolicyDenied("Graphics package is disabled or untrusted")
    if not manager.override(p["id"], "tool", "graphics."+op, True):
        raise PolicyDenied("Graphics tool disabled")
    if op not in {"inspect", "validate"} and source != "owner" and not manager.settings()["agent_execution_enabled"]:
        raise PolicyDenied("Agent execution is disabled")
    with manager.lock:
        from .storage import stamp
        started_at=stamp()
        status = "ok"
        try:
            project = None
            if "project" in a:
                project, _ = authorize(manager, a["project"])
            if op == "inspect":
                if "version" in a:
                    if project is None:
                        raise ValueError("Version inspection requires a project")
                    target, result, conflicts = _load(project, a["version"])
                    return {**result, "version": a["version"], "manual_conflicts": conflicts}
                return {"format": "graphics-recipe/1", "schema": copy.deepcopy(SCHEMA),
                        "example": json.loads((ROOT/"examples/graphics/capabilities.json").read_text(encoding="utf-8")),
                        "capabilities": ["curve_groups", "shared_boundaries", "gradient_fitting", "linked_instances"],
                        "limitations": ["single_region", "no_live_powerpoint_linkage", "no_automatic_visual_approval"]}
            if op == "fit_gradient":
                return fit_gradient(decode_image(a["image"]), decode_image(a["mask"]) if a.get("mask") else None,
                                    models=a.get("models", ["linear"]), max_stops=a.get("max_stops", 3))
            if op == "validate":
                target, result, conflicts = _load(project, a["version"])
                return {"version": a["version"], "manual_conflicts": conflicts,
                        "structure": "unchanged" if not conflicts else "changed",
                        "office": "not_run", "visual_review": "pending"}
            previous = None
            if op == "regenerate" or (op == "preview" and "version" in a):
                if project is None:
                    raise ValueError("Version preview requires a project")
                target, previous, conflicts = _load(project, a["version"])
                if conflicts:
                    raise ValueError("Manual PowerPoint edits detected; old draft preserved: "+", ".join(conflicts))
            result = compile_recipe(a["recipe"], previous, previous["objects"] if previous else None)
            if op == "preview":
                return {**result, "preview": "data:image/png;base64,"+base64.b64encode(png(result)).decode()}
            if not manager.override(p["id"], "tool", "pptx.build", True):
                raise PolicyDenied("PPTX build is disabled")
            import hashlib
            compiler = digest({name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                "scripts/graphics_geometry.py", "scripts/graphics_recipe.py",
                "scripts/graphics_preview.py", "scripts/build_pptx.py",
                "scripts/graphics_paint.py", "assets/graphics/office16-gradient-profile.json",
                "assets/schemas/scene.schema.json")})
            version = digest({"recipe": a["recipe"], "objects": result["objects"],
                              "parent": a.get("version"), "compiler": compiler})
            target = plain_path(project/"assets"/"graphics"/version)
            # Use the same project writer lock if initialized; standalone authorized
            # asset projects get a separate exclusive lock in the graphics directory.
            from contextlib import nullcontext
            from scripts.workflow_store import locked
            parent = plain_path(project/"assets"/"graphics")
            parent.mkdir(parents=True, exist_ok=True)
            lockfile = parent/"writer.lock"
            import os
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.close(fd)
                with locked(project) if (project/"workflow"/"state.json").is_file() else nullcontext():
                    if target.exists():
                        _, stored, conflicts = _load(project, version)
                        if conflicts:
                            raise ValueError("Existing draft was edited; refusing overwrite")
                    else:
                        target.mkdir()
                        def write(name, data):
                            (target/name).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False,
                                                               indent=2), encoding="utf-8")
                        write("compiled.json", result)
                        write("scene.json", result["scene"])
                        (target/"preview.svg").write_text(svg(result), encoding="utf-8")
                        (target/"preview.png").write_bytes(png(result))
                        from build_pptx import build
                        build(target/"scene.json", target/"editable.pptx")
                        write("native-readback.json", readback(target/"editable.pptx"))
                        import hashlib
                        write("manifest.json", {"format": "graphics-project-copy/1", "version": version,
                              "parent": a.get("version"), "compiler": compiler,
                              "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                        for f in target.iterdir() if f.is_file()}})
            finally:
                lockfile.unlink()
            return {"version": version, "directory": str(target), "pptx": str(target/"editable.pptx"),
                    "objects": result["objects"], "recipe": result["recipe"],
                    "changed": result["changed"], "dependencies": result["dependencies"],
                    "scope": "immutable_asset_draft_not_adopted", "office": "not_run",
                    "visual_review": "pending"}
        except Exception:
            status = "error"
            raise
        finally:
            manager.store.event("graphics."+op, "Graphics operation", source=source, status=status,
                                details={"project": str(project) if "project" in locals() and project else None,
                                         "version": a.get("version"), "started_at": started_at, "ended_at": stamp()})
