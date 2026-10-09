"""Declarative construction graph compiled to the existing editable scene objects."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from graphics_geometry import (check_commands, face_commands, flatten, interpolate,
                               offset, ribbon, transform, ROOT)


def obj(fields, required=()):
    return {"type": "object", "properties": fields, "required": list(required),
            "additionalProperties": False}


def array(items, maximum=128, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,39}$"}
N = {"type": "number", "minimum": -1_000_000, "maximum": 1_000_000}
MATRIX = array(N, 6, 6)
BOOL = {"type": "boolean"}
COMMANDS = array({"oneOf": [
    {"type": "array", "prefixItems": [{"const": op}, *[N]*n],
     "minItems": n+1, "maxItems": n+1}
    for op, n in (("M", 2), ("L", 2), ("C", 6), ("Z", 0))
]}, 512, 2)
STYLE = obj({
    "fill": {"type": ["string", "null"], "pattern": "^[0-9A-Fa-f]{6}$"},
    "line": {"type": ["string", "null"], "pattern": "^[0-9A-Fa-f]{6}$"},
    "fill_alpha": {"type": "number", "minimum": 0, "maximum": 1},
    "line_alpha": {"type": "number", "minimum": 0, "maximum": 1},
    "line_width_pt": {"type": "number", "minimum": .05, "maximum": 50},
    "line_cap": {"enum": ["round", "butt", "square"]},
    "line_join": {"enum": ["round", "bevel", "miter"]},
})
STOP = obj({"position": {"type": "number", "minimum": 0, "maximum": 1},
            "color": {"type": "string", "pattern": "^[0-9A-Fa-f]{6}$"},
            "alpha": {"type": "number", "minimum": 0, "maximum": 1}},
           ("position", "color"))
GRADIENT = obj({"type": {"enum": ["linear", "radial"]},
                "path": {"enum": ["circle", "rect", "shape"]},
                "angle_deg": {"type": "number", "minimum": 0, "exclusiveMaximum": 360},
                "center": array({"type": "number", "minimum": 0, "maximum": 1}, 2, 2),
                "stops": array(STOP, 16, 2)}, ("type", "stops"))
LINE_GRADIENT = copy.deepcopy(GRADIENT)
LINE_GRADIENT["properties"]["stops"]["maxItems"] = 5
STYLE["properties"].update(gradient=GRADIENT, line_gradient=LINE_GRADIENT)
SURFACE = obj({"id": ID,
               "width": {"type": "number", "minimum": .12, "maximum": 10000},
               "offset": N, "style": STYLE}, ("id", "width", "style"))
PATH = obj({"id": ID, "commands": COMMANDS, "closed": BOOL,
            "visible": BOOL, "style": STYLE}, ("id", "commands", "closed"))
EDGE = obj({"id": ID, "commands": COMMANDS}, ("id", "commands"))
REF = obj({"edge": ID, "reverse": BOOL}, ("edge",))
FACE = obj({"id": ID, "loops": array(array(REF, 128, 1), 8, 1), "style": STYLE},
           ("id", "loops"))
GROUP = obj({
    "id": ID, "mode": {"enum": ["affine_repeat", "interpolate", "offset", "surface_layers"]}, "source": ID,
    "layers": array(SURFACE, 16, 1),
    "target": ID, "count": {"type": "integer", "minimum": 2, "maximum": 64},
    "matrix_step": MATRIX,
    "positions": array({"type": "number", "minimum": 0, "maximum": 1}, 64, 2),
    "distances": array(N, 64, 1), "style": STYLE,
    "tolerance": {"type": "number", "minimum": .01, "maximum": 2},
    "join_style": {"enum": ["round", "bevel", "miter"]},
    "miter_limit": {"type": "number", "minimum": 1, "maximum": 20},
}, ("id", "mode", "source"))
GROUP["allOf"] = [{"if": {"properties": {"mode": {"const": mode}}},
                    "then": {"required": fields}} for mode, fields in
                   (("interpolate", ["target"]), ("affine_repeat", ["matrix_step"]), ("offset", ["distances"]),
                    ("surface_layers", ["layers"]))]
INSTANCE = obj({"id": ID, "source": ID, "matrix": MATRIX, "style_override": STYLE,
                "state": {"enum": ["linked", "locked", "detached"]},
                "stroke_scale": {"enum": ["preserve", "uniform"]}},
               ("id", "source", "matrix"))
SCHEMA = obj({
    "format": {"const": "graphics-recipe/1"}, "id": ID,
    "canvas": array({"type": "number", "exclusiveMinimum": 0, "maximum": 10000}, 2, 2),
    "points_per_unit": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
    "paths": array(PATH), "edges": array(EDGE), "faces": array(FACE),
    "material_groups": array(obj({"id": ID, "source": ID, "layers": array(obj({"id": ID, "style": STYLE}, ("id", "style")), 8, 1)}, ("id", "source", "layers")), 32),
    "curve_groups": array(GROUP, 32), "instances": array(INSTANCE, 64),
    "order": array(ID, 256, 1),
}, ("format", "id", "canvas", "order"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def leafs(objects):
    for o in objects:
        yield o
        if o["kind"] == "group":
            yield from leafs(o["children"])


def validate_recipe(recipe):
    from jsonschema import Draft202012Validator
    Draft202012Validator(SCHEMA).validate(recipe)
    digest(recipe)
    ids = [r["id"] for key in ("paths", "edges", "faces", "curve_groups", "material_groups", "instances")
           for r in recipe.get(key, [])]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate construction ID")
    if sum(len(p["commands"]) for k in ("paths", "edges") for p in recipe.get(k, [])) > 2048:
        raise ValueError("Input command budget exceeded")
    for p in recipe.get("paths", []):
        check_commands(p["commands"])
        if p["closed"] != (p["commands"][-1][0] == "Z"):
            raise ValueError("Path closed flag and final command disagree")
    for e in recipe.get("edges", []):
        check_commands(e["commands"], open_only=True)
    layers = [layer for group in [*recipe.get("curve_groups", []), *recipe.get("material_groups", [])] for layer in group.get("layers", [])]
    for group in [*recipe.get("curve_groups", []), *recipe.get("material_groups", [])]:
        names = [layer["id"] for layer in group.get("layers", [])]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate surface layer ID")
    for o in [*layers, *recipe.get("paths", []), *recipe.get("faces", []),
              *recipe.get("curve_groups", []), *recipe.get("instances", [])]:
        style = o.get("style", o.get("style_override", {}))
        for field in ("gradient", "line_gradient"):
            if field not in style:
                continue
            g = style[field]
            pos = [s["position"] for s in g["stops"]]
            if pos != sorted(set(pos)) or pos[0] != 0 or pos[-1] != 1:
                raise ValueError("Gradient stops must increase from 0 to 1")
            if g["type"] == "linear" and ("angle_deg" not in g or "center" in g or "path" in g):
                raise ValueError("Linear gradient requires angle and excludes center")
            if g["type"] == "radial" and (field == "line_gradient" or "angle_deg" in g):
                raise ValueError("Radial gradient is fill-only and excludes angle")
    return recipe


def native_path(oid, commands, closed, style):
    return {"id": oid, "kind": "path", "commands": copy.deepcopy(commands), "closed": closed,
            "style": copy.deepcopy(style), "editability": "path",
            "evidence": {"status": "inferred", "note": "graphics-recipe/1; visual review required"}}


def native_group(oid, children):
    return {"id": oid, "kind": "group", "children": children, "editability": "group",
            "evidence": {"status": "inferred", "note": "Parametric construction"}}


def merge_style(original, override):
    value = copy.deepcopy(original)
    for base, gradient in (("fill", "gradient"), ("line", "line_gradient")):
        if base in override and gradient not in override:
            value.pop(gradient, None)
        if gradient in override:
            value.pop(base+"_alpha", None)
    value.update(copy.deepcopy(override))
    return value


def affine_object(source, oid, matrix, style, stroke_scale="preserve"):
    import numpy as np
    value = copy.deepcopy(source)
    # Geometry is transformed explicitly, avoiding hidden group-coordinate scaling.
    for o in leafs([value]):
        o["id"] = oid + o["id"][len(source["id"]):]
        if o["kind"] == "group":
            continue
        o["commands"] = transform(o["commands"], matrix)
        o["style"] = merge_style(o["style"], style)
        if stroke_scale == "uniform":
            a, b, c, d = matrix[:4]
            if not np.allclose([a*a+b*b, a*c+b*d], [c*c+d*d, 0], atol=1e-8, rtol=0):
                raise ValueError("Uniform stroke scaling requires a similarity transform")
            o["style"]["line_width_pt"] = o["style"].get("line_width_pt", 1)*np.hypot(a, b)
        # Gradient space stays attached to the destination bbox by contract.
    return value


def compile_recipe(recipe, previous=None, current_objects=None):
    import numpy as np
    validate_recipe(recipe)
    old = {o["id"]: o for o in (previous or {}).get("objects", [])}
    if previous is not None:
        if current_objects is None:
            raise ValueError("Regeneration requires an observed current object snapshot")
        current = {o["id"]: o for o in current_objects}
        if len(current) != len(current_objects) or set(current) != set(old):
            raise ValueError("Current snapshot has missing, added or duplicate objects")
        conflicts = [k for k in old if digest(old[k]) != digest(current[k])]
        if conflicts:
            raise ValueError("Manual edit conflict; preserve/detach before regeneration: "+", ".join(conflicts))
    nodes = {}
    for kind in ("paths", "faces", "curve_groups", "material_groups", "instances"):
        nodes.update({r["id"]: (kind, r) for r in recipe.get(kind, [])})
    visible = {p["id"] for p in recipe.get("paths", []) if p.get("visible", True)}
    visible |= {r["id"] for k in ("faces", "curve_groups", "material_groups", "instances") for r in recipe.get(k, [])}
    if len(recipe["order"]) != len(set(recipe["order"])) or set(recipe["order"]) != visible:
        raise ValueError("Draw order must list exactly the visible top-level objects")
    edges = {e["id"]: e["commands"] for e in recipe.get("edges", [])}
    resolved, visiting, dependencies, uses, diagnostics = {}, set(), {}, {}, []

    def resolve(oid, depth=0):
        if oid in resolved:
            return resolved[oid]
        if oid in visiting or depth > 16:
            raise ValueError("Cyclic or excessively deep construction dependency")
        if oid not in nodes:
            raise ValueError("Missing source object: "+oid)
        visiting.add(oid)
        kind, spec = nodes[oid]
        dependencies[oid] = []

        def dependency(name):
            dependencies[oid].append(name)
            return resolve(name, depth+1)
        style = spec.get("style", {"fill": "26765C", "line": None})
        if kind == "paths":
            out = native_path(oid, spec["commands"], spec["closed"], style)
        elif kind == "faces":
            commands, edge_uses = face_commands(spec["loops"], edges)
            for edge, direction in edge_uses:
                uses.setdefault(edge, []).append((oid, direction))
                dependencies[oid].append(edge)
            out = native_path(oid, commands, True, style)
        elif kind == "material_groups":
            source = dependency(spec["source"])
            if source["kind"] != "path" or not source["closed"]:
                raise ValueError("Material layers require one closed source path")
            out = native_group(oid, [native_path(oid+"_"+layer["id"], source["commands"], True,
                               layer["style"]) for layer in spec["layers"]])
            diagnostics.append({"id":oid,"geometry_owner":spec["source"],
                                "geometry_sha256":digest(source["commands"]),"layer_order":"back_to_front"})
        elif kind == "instances":
            state = spec.get("state", "linked")
            source = dependency(spec["source"]) if state != "detached" else None
            if state in {"locked", "detached"}:
                if oid not in old:
                    raise ValueError("Lock/detach requires a previous generated instance")
                out = copy.deepcopy(old[oid])
                diagnostics.append({"id": oid, "state": state, "source_not_applied": True})
            else:
                out = affine_object(source, oid, spec["matrix"], spec.get("style_override", {}),
                                    spec.get("stroke_scale", "preserve"))
        else:
            source = dependency(spec["source"])
            if source["kind"] != "path":
                raise ValueError("Curve group source must be a single path")
            mode = spec["mode"]
            children = []
            base_style = merge_style(source["style"], spec.get("style", {}))
            allowed = {"id", "mode", "source", "style"} | {
                "interpolate": {"target", "count", "positions"},
                "affine_repeat": {"count", "matrix_step"},
                "offset": {"distances", "tolerance", "join_style", "miter_limit"},
                "surface_layers": {"layers", "tolerance"}}[mode]
            if spec.keys()-allowed:
                raise ValueError("Parameters not applicable to curve group mode")
            if mode == "interpolate":
                target = dependency(spec["target"])
                if target["kind"] != "path" or source["closed"] != target["closed"]:
                    raise ValueError("Interpolation endpoints must have matching path types")
                positions = spec.get("positions", list(np.linspace(0, 1, spec.get("count", 8))))
                if positions != sorted(set(positions)):
                    raise ValueError("Interpolation positions must be strictly increasing")
                paths = [interpolate(source["commands"], target["commands"], t) for t in positions]
            elif mode == "affine_repeat":
                matrix = spec["matrix_step"]
                a, b, c, d, e, f = matrix
                step = np.array([[a, c, e], [b, d, f], [0, 0, 1]], dtype=float)
                paths = []
                power = np.eye(3)
                for _ in range(spec.get("count", 8)):
                    paths.append(transform(source["commands"], [power[0, 0], power[1, 0],
                                 power[0, 1], power[1, 1], power[0, 2], power[1, 2]]))
                    power = power@step
                # Validate the requested step even when the first copy is identity.
                transform(source["commands"], matrix)
            elif mode == "surface_layers":
                if source["closed"]:
                    raise ValueError("Surface layers require an open centerline")
                paths = []
                for layer in spec["layers"]:
                    commands, report = ribbon(source["commands"], layer["width"],
                                              layer.get("offset", 0), spec.get("tolerance", .1))
                    children.append(native_path(f"{oid}_{layer['id']}", commands, True,
                                                merge_style(base_style, layer["style"])))
                    diagnostics.append({"id": oid, "layer": layer["id"], **report})
            else:
                if source["closed"]:
                    raise ValueError("Offset groups currently require open paths")
                paths = []
                for distance in spec["distances"]:
                    commands, report = offset(source["commands"], distance, spec.get("tolerance", .2),
                                              spec.get("join_style", "round"), spec.get("miter_limit", 4))
                    paths.append(commands)
                    diagnostics.append({"id": oid, "distance": distance, **report})
            for i, commands in enumerate(paths):
                from shapely import LineString
                if any(not LineString(r).is_simple for r in flatten(commands) if len(r) > 1):
                    raise ValueError("Generated curve self-intersects")
                children.append(native_path(f"{oid}_c{i:03d}", commands, source["closed"], base_style))
            out = native_group(oid, children)
        visiting.remove(oid)
        resolved[oid] = out
        return out

    objects = [resolve(oid) for oid in recipe["order"]]
    for edge, rows in uses.items():
        if len(rows) > 2 or (len(rows) == 2 and rows[0][1] == rows[1][1]):
            raise ValueError("Shared edge needs at most two oppositely oriented face uses: "+edge)
    all_objects = list(leafs(objects))
    ids = [o["id"] for o in all_objects]
    if len(ids) != len(set(ids)) or len(ids) > 1024:
        raise ValueError("Generated ID collision or object budget exceeded")
    if sum(len(o.get("commands", [])) for o in all_objects) > 8192:
        raise ValueError("Generated command budget exceeded")
    width, height = recipe["canvas"]
    scale = recipe.get("points_per_unit", 1)
    scene = {"version": "1.0", "canvas": {"width": width, "height": height,
             "width_pt": width*scale, "height_pt": height*scale, "mapping": "uniform"},
             "slides": [{"id": "graphics", "objects": objects}]}
    from validate_scene import validate
    errors = validate(scene, ROOT, check_files=False)
    if errors:
        raise ValueError("; ".join(errors[:5]))
    changed = [o["id"] for o in objects if o["id"] not in old or digest(old[o["id"]]) != digest(o)]
    return {"format": "graphics-compiled/1", "recipe": copy.deepcopy(recipe),
            "recipe_sha256": digest(recipe), "objects": objects, "scene": scene,
            "dependencies": dependencies, "shared_edges": uses, "diagnostics": diagnostics,
            "changed": changed, "removed": sorted(set(old)-visible),
            "fingerprints": {o["id"]: digest(o) for o in objects},
            "office": "not_run", "visual_review": "pending"}
