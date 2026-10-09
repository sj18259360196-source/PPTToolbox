"""Structured adapters for the existing workflow and regional result contracts."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from scripts.common import TASK_REVIEW_STATUSES

CALIBRATION_COMMANDS = ("calibrate_plan", "calibrate_step", "calibrate_report")
SKILL_COMMANDS = ("skill_capture", "skill_search", "skill_apply", "skill_validate", "skill_activate")
ROUTE_COMMANDS = ("route_check", "route_report")
LOCAL_COMMANDS = ("probe", "patch", "compare", "adopt", *CALIBRATION_COMMANDS, *SKILL_COMMANDS, *ROUTE_COMMANDS)
REQUEST_COMMANDS = ("validate_response", "revision_candidate")
COMMANDS = ("start", "next", "submit", "status", "revise", "finish", *REQUEST_COMMANDS, *LOCAL_COMMANDS)
STRING = {"type": "string", "minLength": 1}
TEXT = {"type": "string"}
BOOL = {"type": "boolean"}
NUMBER = {"type": "number"}


def obj(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def array(items, **kw):
    return {"type": "array", "items": items, **kw}


def result_contracts(root):
    from scripts.element_scope import SCOPE, BINDINGS, REVIEW
    # Reuse native object/style definitions. Regional compilation supplies only
    # editability/evidence; do not relax the remaining scene contract.
    scene = json.loads((Path(root)/"assets/schemas/scene.schema.json").read_text(encoding="utf-8"))
    defs = copy.deepcopy(scene["$defs"])
    defs["object"]["required"] = ["id", "kind"]
    props = defs["object"]["properties"]
    tree = ast.parse((Path(root)/"scripts/components.py").read_text(encoding="utf-8"))
    catalog = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CATALOG" for t in n.targets))
    components = []
    for name, row in catalog.items():
        params = {}
        for key, value in row["params"].items():
            params[key] = (BOOL if type(value) is bool else NUMBER if isinstance(value, (int, float))
                           else array(TEXT) if isinstance(value, list)
                           else {"type": ["string", "null"]} if value is None else TEXT)
        components.append(obj({
            "id": STRING, "recipe": {"const": name},
            "bbox": array(NUMBER, minItems=4, maxItems=4), "params": obj(params),
            "style": props["style"], "text_style": props["style"],
            "role": props["role"], "evidence": props["evidence"],
        }, ("id", "recipe", "bbox")))
    status = {"enum": list(TASK_REVIEW_STATUSES)}
    assertion = {"status": status, "note": STRING, "reviewer": STRING, "viewed_files": array(STRING)}
    base = list(assertion)
    contracts = {
        "page_plan": obj({
            "regions": array(obj({
                "id": STRING, "bbox": array({"type": "integer"}, minItems=4, maxItems=4),
                "role": {"enum": ["background", "header", "content", "diagram", "chart", "table", "photo", "decoration", "footer"]},
                "summary": STRING, "local_review": BOOL,
            }, ("id", "bbox", "role", "summary")), minItems=1),
            "notes": TEXT, "uncertainties": array(STRING), "element_scope": SCOPE,
        }, ("regions",)),
        "region_objects": {"oneOf": [
            obj({
                "objects": array({"$ref": "#/$defs/object"}),
                "source_notes": STRING, "relationship_ids": array(STRING),
                "scope_bindings": BINDINGS,
                "uncertainties": array(STRING), "draw_order": array(STRING),
                "components": array({"oneOf": components}),
                "asset_decisions": array(obj({
                    "target_id": STRING, "route": {"enum": ["native", "crop", "user_asset", "external", "generated"]},
                    "generation_considered": BOOL, "reason": STRING, "remaining_risk": STRING,
                }, ("target_id", "route", "generation_considered", "reason", "remaining_risk"))),
            }, ("objects", "source_notes")),
            obj({
                "action": {"const": "revise_objects"},
                "base_fragment_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "reason": STRING,
                "objects": array({"$ref": "#/$defs/object"}),
                "components": array({"oneOf": components}),
            }, ("action", "base_fragment_sha256", "reason")),
            obj({"action": {"const": "request_asset"}, "request": obj({
                "id": STRING, "purpose": STRING, "prompt": STRING,
                "transparent": BOOL, "allowed_approximation": {"const": True},
                "scope_unit_ids": array(STRING, minItems=1, uniqueItems=True),
            }, ("id", "purpose", "prompt", "transparent", "allowed_approximation"))}, ("action", "request")),
            obj({"action": {"const": "request_assets"}, "requests": array(obj({
                "id": STRING, "purpose": STRING, "prompt": STRING,
                "transparent": BOOL, "allowed_approximation": {"const": True},
                "scope_unit_ids": array(STRING, minItems=1, uniqueItems=True),
            }, ("id", "purpose", "prompt", "transparent", "allowed_approximation")), minItems=1, maxItems=8)}, ("action", "requests")),
        ]},
        "source_review": obj({
            **assertion,
            "scope_review": REVIEW,
            "text_checks": array(obj({"object_id": STRING, "source_text": TEXT},
                                     ("object_id", "source_text")), minItems=1),
        }, base),
        "asset_material": obj({"file": STRING, "tool_used": STRING, "provenance": STRING,
                               "model_reported": {"type": ["string", "null"]}}, ("file", "tool_used", "provenance")),
        "candidate": obj({"file": STRING}, ("file",)),
        "office_render": obj({"receipt": STRING}, ("receipt",)),
        "review_full": obj({
            "reviewer": STRING, "viewed_files": array(STRING),
            "checks": obj({k: obj({"status": status, "note": STRING}, ("status", "note"))
                           for k in ("visual_full", "raster_scope", "text_geometry")},
                          ("visual_full", "raster_scope", "text_geometry")),
            # The existing workflow deliberately leaves finding content to the reviewer.
            "findings": array({}),
        }, ("reviewer", "viewed_files", "checks")),
        "review_local": obj({**assertion, "relationships": array(obj({
            "object_id": STRING, "note": STRING}, ("object_id", "note"))), "findings": array({})}, base),
        "editable_behavior": obj({**assertion, "files": array(STRING), "actions": array(obj({
            "kind": STRING, "note": STRING, "object_id": STRING, "slide_id": STRING,
        }, ("kind", "note")))}, base + ["actions"]),
    }
    contracts["reproducibility"] = contracts["editable_behavior"]
    contracts["preview_full"] = copy.deepcopy(contracts["review_full"])
    contracts["preview_local"] = contracts["review_local"]
    contracts["review_full"]["properties"]["additional_reviews"] = array(
        obj({"region_id": STRING, "result": contracts["review_local"]}, ("region_id", "result")),
        minItems=1, maxItems=6)
    return contracts, defs


def schemas(root):
    results, defs = result_contracts(root)
    project = {"project": STRING}
    start = obj({**project, "references": array(STRING, minItems=1), "scene": STRING,
                 "candidate": STRING, "ratio": STRING, "mapping": {"enum": ["uniform", "explicit_stretch"]},
                 "office": BOOL, "builder": {"enum": ["python", "external"]}, "in_place":BOOL}, ("project",))
    start["oneOf"] = [{"required": ["references"], "not": {"required": ["scene"]}},
                      {"required": ["scene"], "not": {"required": ["references"]}}]
    submit = obj({**project, "task_id": STRING, "token": STRING,
                  "base_revision": {"type": "integer", "minimum": 0},
                  "result": {"anyOf": list(results.values())}}, ("project", "task_id", "token", "result"))
    submit["$defs"] = defs
    submit['properties']['return_next'] = BOOL
    submit['properties']['result_file'] = STRING
    submit['properties']['result_sha256'] = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    submit['required'].remove('result')
    submit['oneOf'] = [
        {'required': ['result'], 'not': {'anyOf': [{'required': ['result_file']}, {'required': ['result_sha256']}]}},
        {'required': ['result_file', 'result_sha256'], 'not': {'required': ['result']}},
    ]
    preflight = copy.deepcopy(submit)
    preflight['properties']['result'] = {'type': 'object'}
    contracts = {
        "start": start, "next": obj(project, ("project",)), "status": obj(project, ("project",)),
        "finish": obj(project, ("project",)), "submit": submit,
        "validate_response": preflight,
        "revision_candidate": obj({**project, "run_id": STRING, "slide": STRING, "region": STRING,
            "base_revision": {"type": "integer", "minimum": 0}, "reason": STRING},
            ("project", "run_id", "slide", "region", "base_revision", "reason")),
        "revise": obj({**project, "slide": STRING, "region": STRING, "reason": STRING},
                      ("project", "slide", "reason")),
    }
    for name in ('start','next','status','submit'):
        contracts[name]['properties']['response_detail']={'enum':['full','compact']}
    from scripts.project_flow import PATCH_SCHEMA as FLOW_SCHEMA
    checkpoint = obj({'checkpoint_id':STRING, 'run_id':STRING,
        'expected_revision':{'type':'integer','minimum':0},
        'event':{'enum':['begin','transition','finish','replan','blocked','pause','resume']},
        'stage':{'enum':['intake','plan','production','revision','delivery']},
        'result_summary':STRING,'next_action':TEXT,'artifact_refs':array(STRING,maxItems=30),
        'blocker':{'type':['string','null']},'used_experiences':array(STRING,maxItems=20),'flow':FLOW_SCHEMA},
        ('checkpoint_id','run_id','expected_revision','event','result_summary'))
    for name in ('next','submit'):
        contracts[name]['properties']['checkpoint'] = checkpoint
    opid = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$"}
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    color = {"type": "string", "pattern": "^[0-9A-F]{6}$"}
    style = obj({"font_size_pt": {"type": "number", "exclusiveMinimum": 0}, "color": color,
                 "align": {"enum": ["left", "center", "right"]},
                 **{"margin_"+s+"_pt": {"type": "number", "minimum": 0}
                    for s in ("left", "right", "top", "bottom")}})
    style["minProperties"] = 1
    ops = []
    for name, field, spec in (
        ("text.set", "text", TEXT), ("text.style", "style", style),
        ("geometry.set", "bbox", array(NUMBER, minItems=4, maxItems=4)),
        ("fill.set", "color", color),
        ("group.translate", "delta", array(NUMBER, minItems=2, maxItems=2)),
        ("picture.crop", "source_crop", array(NUMBER, minItems=4, maxItems=4)),
    ):
        ops.append(obj({"op": {"const": name}, "id": STRING, field: spec}, ("op", "id", field)))
    from scripts.native_capabilities import FORMAT
    ops.append(obj({"op": {"const": "native.format"}, "id": STRING,
                    "format": FORMAT, "text": TEXT}, ("op", "id", "format")))
    from scripts.native_capabilities import TOPOLOGY
    ops.append(TOPOLOGY)
    from scripts.native_capabilities import TEXT_RANGE
    ops.append(TEXT_RANGE)
    from scripts.native_nodes import NODES
    ops.append(NODES)
    common = {**project, "operation_id": opid}
    probe = obj({**common, "task_id": STRING, "base_revision": {"type": "integer", "minimum": 0},
                 "result": results["region_objects"], "office": BOOL},
                ("project", "operation_id", "task_id", "base_revision", "result"))
    probe["$defs"] = defs
    contracts.update({
        "probe": probe,
        "patch": obj({**common, "base_revision": {"type": "integer", "minimum": 0},
                      "scene_sha256": sha, "pptx_sha256": sha, "slide": STRING, "region": STRING,
                      "changes": array({"oneOf": ops}, minItems=1, maxItems=30), "reason": STRING},
                     ("project", "operation_id", "base_revision", "scene_sha256", "pptx_sha256",
                      "slide", "region", "changes", "reason")),
        "compare": obj({**common, "trial_id": opid}, ("project", "operation_id", "trial_id")),
        "adopt": obj({**common, "trial_id": opid, "comparison_id": opid,
                      "observation": obj({"status": {"enum": ["passed", "needs_changes"]},
                                          "note": STRING, "reviewer": STRING,
                                          "viewed_files": array(STRING, minItems=1)},
                                         ("status", "note", "reviewer", "viewed_files"))},
                     ("project", "operation_id", "trial_id", "comparison_id", "observation")),
    })
    from scripts.calibration_math import FIELDS, CRITICAL_FEATURES
    parameter = obj({
        "object_id": STRING, "field": {"enum": list(FIELDS)}, "unit": {"const": "pt"},
        "anchor": {"const": "top_left"}, "initial": NUMBER, "lower": NUMBER, "upper": NUMBER,
        "step": {"type": "number", "minimum": .01}, "min_step": {"type": "number", "minimum": .01},
        "values": array(NUMBER, minItems=1, maxItems=25),
    }, ("object_id", "field", "unit", "anchor", "initial", "lower", "upper", "step", "min_step"))
    contracts.update({
        "calibrate_plan": obj({
            **common, "task_id": STRING, "base_revision": {"type": "integer", "minimum": 0},
            "scene_sha256": sha, "pptx_sha256": sha, "slide": STRING, "region": STRING,
            "parameters": array(parameter, minItems=1, maxItems=4),
            "roi": array({"type": "integer", "minimum": 0}, minItems=4, maxItems=4),
            "background": array({"type": "integer", "minimum": 0, "maximum": 255}, minItems=3, maxItems=3),
            "target_source": obj({"level": {"enum": ["observed", "measured", "inferred", "unknown"]},
                                  "note": STRING}, ("level", "note")),
            "allowed_line_counts": array({"type": "integer", "minimum": 1}, maxItems=10),
            "critical_dimensions": array(obj({
                "object_id": STRING, "feature": {"enum": list(CRITICAL_FEATURES)},
                "roi": array({"type": "integer", "minimum": 0}, minItems=4, maxItems=4),
                "line_index": {"type": "integer", "minimum": 0, "maximum": 99},
                "tolerance_px": {"type": "number", "minimum": 0, "maximum": 10},
                "source": obj({"level": {"enum": ["observed", "measured", "inferred", "unknown"]},
                               "note": STRING}, ("level", "note")),
            }, ("object_id", "feature", "roi", "tolerance_px", "source")), maxItems=4),
        }, ("project", "operation_id", "task_id", "base_revision", "scene_sha256", "pptx_sha256",
            "slide", "region", "parameters", "roi", "background", "target_source", "allowed_line_counts")),
        "calibrate_step": obj({**project, "calibration_id": opid, "request_id": opid, "cancel": BOOL},
                              ("project", "calibration_id", "request_id")),
        "calibrate_report": obj({**project, "calibration_id": opid}, ("project", "calibration_id")),
    })
    skill = {"skill_id": opid, "version": sha | {"minLength": 24, "maxLength": 24, "pattern": "^[a-f0-9]{24}$"}}
    loose = {"type": "object"}
    contracts.update({
        "skill_capture": obj({**common, "skill_id": opid, "description": STRING,
            "source_scene": STRING, "source_pptx": STRING, "source_evidence": array(STRING, minItems=1, maxItems=12),
            "slide_index": {"type": "integer", "minimum": 0}, "object_ids": array(STRING, minItems=3, maxItems=12),
            "parameters": loose, "bindings": array(loose, maxItems=40),
            "placement_domain": array(NUMBER, minItems=4, maxItems=4),
            "layout_assumptions": array(obj({"status": {"enum": ["proposed", "inferred"]}, "note": STRING},
                                            ("status", "note")), maxItems=12)},
            ("project", "operation_id", "skill_id", "description", "source_scene", "source_pptx", "source_evidence",
             "slide_index", "object_ids", "parameters", "bindings", "placement_domain", "layout_assumptions")),
        "skill_search": obj({**project, "query": STRING, **skill,
            "object_types": array({"enum": ["text", "shape"]}, minItems=1)}, ("project", "query")),
        "skill_apply": obj({**common, **skill, "task_id": STRING, "base_revision": {"type": "integer", "minimum": 0},
            "validation_task": STRING, "route_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            "values": loose, "placement": array(NUMBER, minItems=4, maxItems=4), "office": BOOL},
            ("project", "operation_id", "skill_id", "version", "task_id", "base_revision", "values", "placement")),
        "skill_validate": obj({**common, **skill}, ("project", "operation_id", "skill_id", "version")),
        "skill_activate": obj({**common, **skill, "enabled": BOOL}, ("project", "operation_id", "skill_id", "version", "enabled")),
    })
    target = obj({"id": STRING, "role": STRING,
        "kind": {"enum": ["text", "shape", "image", "group", "unknown"]},
        "text": {"type": ["string", "null"]}, "geometry": {"type": ["string", "null"]},
        "bbox": {"anyOf": [array(NUMBER, minItems=4, maxItems=4), {"type": "null"}]},
        "style": {"type": ["object", "null"]},
        "editability": {"enum": ["text", "shape", "image_replace", "group", "unknown"]}},
        ("id", "role", "kind", "text", "geometry", "bbox", "style", "editability"))
    requirements = obj({"source": obj({"level": {"enum": ["observed", "inferred", "unknown"]},
        "note": STRING, "observer": STRING}, ("level", "note", "observer")), "complete": BOOL,
        "objects": array(target, minItems=1, maxItems=30),
        "bindings": {"type": "object", "additionalProperties": STRING}},
        ("source", "complete", "objects", "bindings"))
    contracts.update({
        "route_check": obj({**project, **skill, "task_id": STRING,
            "base_revision": {"type": "integer", "minimum": 0}, "reference_sha256": sha,
            "values": loose, "placement": array(NUMBER, minItems=4, maxItems=4),
            "requirements": requirements},
            ("project", "skill_id", "version", "task_id", "base_revision", "reference_sha256",
             "values", "placement", "requirements")),
        "route_report": obj(project, ("project",)),
    })
    return contracts


def validation_hint(errors):
    """Select a useful nested failure without echoing submitted values or tokens."""
    from jsonschema.exceptions import best_match
    error = best_match(errors)
    path = "/".join(map(str, error.absolute_path)) or "/"
    hint = "at " + path + "; constraint=" + str(error.validator)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [name for name in error.validator_value if name not in error.instance]
        hint += "; missing=" + ",".join(missing[:6])
    elif error.validator == "enum":
        hint += "; allowed=" + json.dumps(error.validator_value, ensure_ascii=False)[:240]
    elif error.validator == "type":
        hint += "; expected_type=" + str(error.validator_value)
    elif error.validator == "additionalProperties":
        hint += "; remove unsupported fields using the current response template"
    return hint


def validate(command, arguments, root):
    from jsonschema import Draft202012Validator
    # JSON permits neither NaN nor Infinity; reject even when called without RPC.
    json.dumps(arguments, allow_nan=False)
    errors = list(Draft202012Validator(schemas(root)[command]).iter_errors(arguments))
    if errors:
        # Do not echo the instance: errors can contain private text or task tokens.
        raise ValueError("Invalid arguments " + validation_hint(errors))


def validate_result(kind, result, root):
    from jsonschema import Draft202012Validator
    results, defs = result_contracts(root)
    spec = {**results[kind], "$defs": defs}
    errors = list(Draft202012Validator(spec).iter_errors(result))
    if errors:
        raise ValueError("Result does not match current task contract: " + kind + "; " + validation_hint(errors))
