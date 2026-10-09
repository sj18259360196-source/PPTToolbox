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
from graphics_recipe import SCHEMA, compile_recipe, digest, obj, array, STYLE, COMMANDS, ID

S = {"type": "string", "minLength": 1}
VERSION = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
PROJECT = {"project": S}
ANALYSIS_INPUT = obj({"objects": array({"type": "object"}, 10000, 1),
                      "cubic_warning": {"type": "integer", "minimum": 1, "maximum": 100000},
                      "subpath_warning": {"type": "integer", "minimum": 1, "maximum": 100000}}, ("objects",))
MATERIAL_INPUT = obj({"preset": {"enum": ["droplet", "rotated_end"]},
                      "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,19}$"},
                      "box": {"type": "array", "prefixItems": [
                          {"type": "number", "minimum": 0, "maximum": 10000},
                          {"type": "number", "minimum": 0, "maximum": 10000},
                          {"type": "number", "minimum": .12, "maximum": 10000},
                          {"type": "number", "minimum": .12, "maximum": 10000}], "minItems": 4, "maxItems": 4},
                      "canvas": array({"type": "number", "exclusiveMinimum": 0, "maximum": 10000}, 2, 2),
                      "rotation": {"type": "number", "minimum": -360, "maximum": 360},
                      "points_per_unit": {"type": "number", "exclusiveMinimum": 0, "maximum": 10}},
                     ("preset", "id", "box", "canvas"))
SOURCES_INPUT = obj({**PROJECT, "dependencies": array(obj({
    "path": S, "role": {"enum": ["generator", "recipe", "schema", "helper", "reference"]},
    "sha256": VERSION}, ("path", "role")), 64, 1)}, ("project", "dependencies"))
POINT=array({'type':'number','minimum':0,'maximum':10000},2,2)
CONSTRUCT_BASE={'id':ID,'canvas':POINT,'points_per_unit':{'type':'number','exclusiveMinimum':0,'maximum':10},'style':STYLE}
CONSTRUCT_INPUT={'type':'object','oneOf':[
    obj({**CONSTRUCT_BASE,'mode':{'const':'rounded_polygon'},'points':array(POINT,64,3),
         'corner_inset':{'type':'number','minimum':0,'maximum':1000}},('id','canvas','style','mode','points','corner_inset')),
    obj({**CONSTRUCT_BASE,'mode':{'const':'radial_repeat'},'commands':COMMANDS,'center':POINT,
         'count':{'type':'integer','minimum':2,'maximum':64},'step_deg':{'type':'number','exclusiveMinimum':0,'maximum':360}},
        ('id','canvas','style','mode','commands','center','count'))]}
IMAGE={'type':'string','minLength':1,'maxLength':8_000_000}
CONTOUR_INPUT=obj({**PROJECT,**{k:IMAGE for k in ['reference','candidate','reference_mask','candidate_mask','exclude_mask']}},
                  ('reference','candidate','reference_mask','candidate_mask'))
READBACK_INPUT=obj({**PROJECT,'pptx':S,'pptx_sha256':VERSION,
    'targets':array(obj({'slide':{'type':'integer','minimum':1},'id':S},('slide','id')),50,1)},
    ('project','pptx','pptx_sha256','targets'))
BOOLEAN_INPUT=obj({**PROJECT,'slide':S,'region':S,'inputs':array(S,8,2),'primary':S,
    'prefix':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]{0,23}$'},'reason':S,
    'actions':{'type':'array','uniqueItems':True,'minItems':1,'maxItems':5,
               'items':{'enum':['union','combine','intersect','subtract','fragment']}}},
    ('project','slide','region','inputs','prefix','reason'))
SPECS = {
    "illustration_guide":("少色分层插画直接调用指南。无需经验检索，返回钢笔/选区两路线、当前 schema、受管调用参数与复查条件；只读。", obj({**PROJECT, "route":{"enum":["overview","pen","selection"]}})),
    'construct':('构建有界圆角多边形或放射实例，输出现有配方。',CONSTRUCT_INPUT),
    'compare_contours':('依据显式二值掩膜测量轮廓偏差并返回叠图，不判定视觉通过。',CONTOUR_INPUT),
    'read_properties':('在独立副本保存重开，读取原生填充、分组与节点，源文件不变。',READBACK_INPUT),
    'boolean_trials':('预检有序操作数，生成复用 rebuild_patch 的独立布尔试制请求。',BOOLEAN_INPUT),
    "analyze": ("检查原生插画的路径复杂度、透明叠层与预览边界。", ANALYSIS_INPUT),
    "material_recipe": ("生成可编辑水珠或旋转端面的参数化配方。", MATERIAL_INPUT),
    "audit_sources": ("核对项目内列明的绘图依赖、哈希及临时目录风险。", SOURCES_INPUT),
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


from illustration_contracts import SPECS as ILLUSTRATION_SPECS
SPECS.update(ILLUSTRATION_SPECS)
from gradient_contracts import SPECS as GRADIENT_SPECS, LAYERED, TIME
SPECS.update(GRADIENT_SPECS)
READBACK_INPUT['properties']['timeout_seconds']=TIME
SPECS['fit_gradient'][1]['properties']['layered_linear']=LAYERED


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
    from illustration_tools import analyze, material_recipe, audit_sources
    a = args or {}
    if op not in SPECS:
        raise ValueError("Unknown graphics operation")
    Draft202012Validator(SPECS[op][1]).validate(a)
    p = manager.package()
    if not p["enabled"] or not p["trusted"]:
        raise PolicyDenied("Graphics package is disabled or untrusted")
    if not manager.override(p["id"], "tool", "graphics."+op, True):
        raise PolicyDenied("Graphics tool disabled")
    if op not in {"illustration_guide", "inspect", "validate", "analyze", "audit_sources",'compare_contours','boolean_trials'} and source != "owner" and not manager.settings()["agent_execution_enabled"]:
        raise PolicyDenied("Agent execution is disabled")
    from contextlib import nullcontext
    with nullcontext():
        from .storage import stamp
        started_at=stamp()
        import uuid
        from .project_activity import CALL_ID
        call_id=CALL_ID.get() or uuid.uuid4().hex
        manager.store.event('graphics.started','Graphics operation started',source=source,status='running',
                            details={'call_id':call_id,'operation':op,'tool_id':'graphics.'+op,'command_status':'running','project':a.get('project'),'started_at':started_at})
        status = "ok"
        try:
            project = None
            if "project" in a:
                project, _ = authorize(manager, a["project"])
            if op == 'illustration_guide':
                from .illustration_guide import guide
                return guide(manager,a)
            if op in {'scene_preflight','select_versions','probe_gradient'}:
                import gradient_capabilities
                if op=='probe_gradient':
                    for required in ['pptx.build','office.edit-readback']:
                        if not manager.override(p['id'],'tool',required,True): raise PolicyDenied(required+' disabled')
                    a={**a,'_office_lock':str(manager.data/'office-writer.lock')}
                return getattr(gradient_capabilities,{'scene_preflight':'preflight','select_versions':'select_versions','probe_gradient':'probe'}[op])(project,a)
            if op=='gradient_roundtrip':
                if not manager.override(p['id'],'tool','office.edit-readback',True): raise PolicyDenied('office.edit-readback disabled')
                from gradient_jobs import run_job
                return run_job(project,op,{**a,'_office_lock':str(manager.data/'office-writer.lock')})
            if op in ILLUSTRATION_SPECS:
                from illustration_workflow import run
                return run(project,op,a)
            if op=='construct':
                from shape_construction import construct
                return construct(a)
            if op=='compare_contours':
                import subprocess
                payload=json.dumps(a,ensure_ascii=False,allow_nan=False).encode('utf-8')
                if len(payload)>32*1024*1024:raise ValueError('Contour request exceeds budget')
                try:
                    result=subprocess.run([sys.executable,'-B','-I',str(ROOT/'scripts/contour_worker.py')],
                        input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except subprocess.TimeoutExpired:
                    raise ValueError('Contour measurement timed out; no PPT or project candidate was modified')
                if result.returncode:raise ValueError('Contour worker failed: '+result.stderr.decode('utf-8',errors='replace')[-1200:])
                return json.loads(result.stdout.decode('utf-8'))
            if op=='read_properties':
                for required in ['office.edit-readback','pptx.inspect']:
                    if not manager.override(p['id'],'tool',required,True):raise PolicyDenied(required+' disabled')
                from gradient_jobs import run_job
                return run_job(project,'read_properties',{**a,'_office_lock':str(manager.data/'office-writer.lock')})
            if op=='boolean_trials':
                if not manager.override(p['id'],'tool','workflow.patch',True):raise PolicyDenied('workflow.patch disabled')
                from shape_evidence import boolean_trials
                return boolean_trials(project,a)
            if op == "analyze":
                return analyze(a["objects"], cubic_warning=a.get("cubic_warning", 128),
                               subpath_warning=a.get("subpath_warning", 32))
            if op == "material_recipe":
                return material_recipe(a["preset"], a["id"], a["box"], a["canvas"],
                                       rotation=a.get("rotation", 0), points_per_unit=a.get("points_per_unit", 1))
            if op == "audit_sources":
                return audit_sources(project, a["dependencies"])
            if op == "inspect":
                from native_nodes import NODES
                if "version" in a:
                    if project is None:
                        raise ValueError("Version inspection requires a project")
                    target, result, conflicts = _load(project, a["version"])
                    return {**result, "version": a["version"], "manual_conflicts": conflicts}
                return {"format": "graphics-recipe/1", "schema": copy.deepcopy(SCHEMA),
                        "example": json.loads((ROOT/"examples/graphics/capabilities.json").read_text(encoding="utf-8")),
                        "capabilities": ["curve_groups", "shared_boundaries", "gradient_fitting", "linked_instances",
                                         "surface_layers", "material_groups", "layered_linear_fit", "gradient_probe", "gradient_roundtrip", "scene_preflight", "version_selection", "bounded_target_readback", "authored_gradients_up_to_16_stops",
                                         "illustration_analysis", "material_recipes", "source_dependency_audit",
                                         'shape_construction','contour_comparison','native_property_readback','boolean_trial_planning','bounded_node_edits'],
                        "material_presets": ["droplet", "rotated_end"],
                        'node_edit_schema':copy.deepcopy(NODES),
                        'node_edit_entry':'rebuild_patch',
                        "illustration_example": json.loads((ROOT/"examples/graphics/native-tube.json").read_text(encoding="utf-8")),
                        "illustration_guide": "references/native-illustration.md",
                        "limitations": ["single_region", "no_live_powerpoint_linkage", "no_automatic_visual_approval"]}
            if op == "fit_gradient":
                if 'layered_linear' in a:
                    if 'models' in a or 'max_stops' in a: raise ValueError('Single and layered model controls cannot be mixed')
                    from gradient_layered import fit
                    return fit(decode_image(a['image']),decode_image(a['mask']) if a.get('mask') else None,a['layered_linear'])
                from graphics_gradient import fit_gradient
                return fit_gradient(decode_image(a["image"]), decode_image(a["mask"]) if a.get("mask") else None,
                                    models=a.get("models", ["linear"]), max_stops=a.get("max_stops", 3))
            if op == "validate":
                target, result, conflicts = _load(project, a["version"])
                return {"version": a["version"], "manual_conflicts": conflicts,
                        "structure": "unchanged" if not conflicts else "changed",
                        "office": "not_run", "visual_review": "pending"}
            from graphics_preview import png, svg, readback
            previous = None
            if op == "regenerate" or (op == "preview" and "version" in a):
                if project is None:
                    raise ValueError("Version preview requires a project")
                target, previous, conflicts = _load(project, a["version"])
                if conflicts:
                    raise ValueError("Manual PowerPoint edits detected; old draft preserved: "+", ".join(conflicts))
            result = compile_recipe(a["recipe"], previous, previous["objects"] if previous else None)
            result["illustration_analysis"] = analyze(result["objects"])
            if op == "preview":
                return {**result, "preview": "data:image/png;base64,"+base64.b64encode(png(result)).decode()}
            if not manager.override(p["id"], "tool", "pptx.build", True):
                raise PolicyDenied("PPTX build is disabled")
            import hashlib
            compiler = digest({name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                "scripts/graphics_geometry.py", "scripts/graphics_recipe.py", "scripts/illustration_tools.py",
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
                    "illustration_analysis": result["illustration_analysis"],
                    "scope": "immutable_asset_draft_not_adopted", "office": "not_run",
                    "visual_review": "pending"}
        except Exception:
            status = "error"
            raise
        finally:
            manager.store.event("graphics."+op, "Graphics operation", source=source, status=status,
                                details={"project": str(project) if "project" in locals() and project else None,
                                         "call_id":call_id,"tool_id":"graphics."+op,"command_status":"completed" if status=="ok" else "failed","version": a.get("version"), "started_at": started_at, "ended_at": stamp()})
