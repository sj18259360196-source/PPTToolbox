"""Image-guided, bounded native path suggestions, never automatic adoption.

Only explicit top-level solid M/L/C/Z paths are measured. The original command
topology and coincident nodes remain intact. Real Office verification is required.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json, sha256, staged_directory, write_json
from graphics_geometry import check_commands
from graphics_preview import svg
from validate_scene import validate


def _supported(obj):
    if (obj.get("kind") != "path" or obj.get("rotation", 0)
            or obj.get("native_path_frame")):
        raise ValueError("Only unrotated top-level native paths are supported")
    check_commands(obj["commands"])
    st = obj.get("style", {})
    allowed = {"fill", "line", "line_width_pt", "fill_alpha", "line_alpha",
               "line_cap", "line_join", "miter_limit", "begin_arrow", "end_arrow",
               "begin_arrow_width", "begin_arrow_length", "end_arrow_width", "end_arrow_length"}
    if set(st)-allowed or st.get("fill_alpha", 1) != 1 or st.get("line_alpha", 1) != 1:
        raise ValueError("Effects, gradients, transparency and dashed paths require separate measurement")
    if any(st.get(k, "none") not in {"none", "triangle"} for k in ("begin_arrow", "end_arrow")):
        raise ValueError("Only triangle endpoint arrows have a measured preview profile")
    if obj.get("closed") and any(st.get(k, "none") != "none"
                                  for k in ("begin_arrow", "end_arrow")):
        raise ValueError("Closed paths with arrows are not supported")
    if not st.get("fill") and not st.get("line"):
        raise ValueError("Invisible paths cannot be measured")


def render(objects, canvas, roi):
    """Raster preview in image coordinates, with no resizing of the reference."""
    import resvg_py
    from lxml import etree as ET
    x1, y1, x2, y2 = roi
    scale = canvas["width_pt"]/canvas["width"]
    root = ET.fromstring(svg({"recipe": {"canvas": [canvas["width"], canvas["height"]],
                                            "points_per_unit": scale}, "objects": objects}).encode())
    root.set("viewBox", f"{x1} {y1} {x2-x1} {y2-y1}")
    root.set("width", str(x2-x1))
    root.set("height", str(y2-y1))
    payload = resvg_py.svg_to_bytes(svg_string=ET.tostring(root, encoding="unicode"),
                                   skip_system_fonts=True)
    with Image.open(io.BytesIO(payload)) as image:
        background = Image.new("RGBA", image.size, "#"+canvas.get("background", "FFFFFF"))
        background.alpha_composite(image.convert("RGBA"))
        return np.asarray(background.convert("RGB"))


def _check_geometry_preserved(before, after):
    """Keep simple paths simple and keep the winding of closed subpaths."""
    from graphics_geometry import flatten
    from shapely.geometry import LineString
    a, b = flatten(before["commands"], .1), flatten(after["commands"], .1)
    for original, changed in zip(a, b):
        old, new = LineString(original), LineString(changed)
        if old.is_simple and not new.is_simple:
            raise ValueError("Fit introduced a self-intersection; keep the previous candidate")
        if before.get("closed"):
            first, second = np.asarray(original), np.asarray(changed)
            area = lambda points: float(np.sum(points[:-1, 0]*points[1:, 1]-points[1:, 0]*points[:-1, 1]))
            if area(first)*area(second) <= 0:
                raise ValueError("Fit changed a subpath winding or collapsed its area")


class _BudgetReached(Exception):
    pass


def _coordinate_parameters(objects, selected):
    """Tie coincident points and straight axes; anchor classes touching context."""
    parent, points, values, anchored = {}, {}, {}, set()

    def find(ref):
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    def union(first, second):
        a, b = find(first), find(second)
        if a != b:
            parent[b] = a

    context_points = {
        tuple(cmd[vi:vi+2])
        for obj in objects if obj["id"] not in selected
        for cmd in obj["commands"] for vi in range(1, len(cmd), 2)
    }
    for oi, obj in enumerate(objects):
        if obj["id"] not in selected:
            continue
        for ci, cmd in enumerate(obj["commands"]):
            for vi in range(1, len(cmd), 2):
                point = tuple(cmd[vi:vi+2])
                refs = [(oi, ci, vi), (oi, ci, vi+1)]
                for ref, value in zip(refs, point):
                    parent[ref] = ref
                    values[ref] = value
                    if point in context_points:
                        anchored.add(ref)
                if point in points:
                    for ref, other in zip(refs, points[point]):
                        union(ref, other)
                else:
                    points[point] = refs
        if [c[0] for c in obj["commands"]] == ["M", "L"]:
            for axis in (0, 1):
                if obj["commands"][0][axis+1] == obj["commands"][1][axis+1]:
                    union((oi, 0, axis+1), (oi, 1, axis+1))
                    break
    groups = {}
    for ref in parent:
        groups.setdefault(find(ref), []).append(ref)
    fixed = {find(ref) for ref in anchored}
    free = [refs for root, refs in groups.items() if root not in fixed]
    return free, [values[refs[0]] for refs in free], {
        "coincident_points_preserved": True,
        "unchanged_context_anchors_preserved": True,
        "anchored_scalar_classes": len(fixed),
        "shared_object_scalar_classes": sum(len({r[0] for r in refs}) > 1
                                             for refs in groups.values()),
        "scope": "Exact initial point coincidences among supplied paths only; "
                 "nearby points, omitted context and semantic connections are not inferred.",
    }


def fit_region(objects, ids, canvas, roi, reference, *, coordinate_limit=12,
               width_limit_pt=1.5, max_evaluations=1200, max_seconds=90,
               search_arrow_sizes=False):
    """Fit one isolated ROI. Uses raster pixels and the current candidate only."""
    from scipy.ndimage import gaussian_filter
    from scipy.optimize import least_squares
    from native_practice import region_score
    started = time.monotonic()
    if (type(coordinate_limit) not in (int, float) or not math.isfinite(coordinate_limit)
            or not .25 <= coordinate_limit <= 24
            or type(width_limit_pt) not in (int, float) or not math.isfinite(width_limit_pt)
            or not 0 <= width_limit_pt <= 3
            or type(max_evaluations) is not int or not 20 <= max_evaluations <= 4000
            or type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
            or not 1 <= max_seconds <= 180 or type(search_arrow_sizes) is not bool):
        raise ValueError("Invalid bounded fit budget")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids)
            or len(objects) > 8 or len({o["id"] for o in objects}) != len(objects)
            or set(ids)-{o["id"] for o in objects}):
        raise ValueError("Select 1..4 distinct paths and at most 8 explicit context paths")
    for obj in objects:
        _supported(obj)
    if (len(roi) != 4 or any(type(v) is not int for v in roi)
            or not 0 <= roi[0] < roi[2] <= canvas["width"]
            or not 0 <= roi[1] < roi[3] <= canvas["height"]
            or max(roi[2]-roi[0], roi[3]-roi[1]) > 512):
        raise ValueError("ROI must be integer image coordinates, at most 512 pixels per edge")
    if not math.isclose(canvas["width_pt"]/canvas["width"],
                        canvas["height_pt"]/canvas["height"], rel_tol=1e-8):
        raise ValueError("Uniform pixel-to-point mapping is required")
    if reference.shape != (roi[3]-roi[1], roi[2]-roi[0], 3):
        raise ValueError("Reference crop and ROI dimensions must match")
    initial = copy.deepcopy(objects)
    selected = set(ids)
    parameters, values, joint_constraints = _coordinate_parameters(objects, selected)
    limits = [coordinate_limit] * len(parameters)
    steps = [.35] * len(parameters)
    width_parameters = {}
    for oi, obj in enumerate(objects):
        if obj["id"] not in selected:
            continue
        if obj["style"].get("line") and width_limit_pt:
            width_parameters[oi] = len(parameters)
            parameters.append([(oi, "width", "line_width_pt")])
            values.append(obj["style"].get("line_width_pt", 1))
            limits.append(width_limit_pt)
            steps.append(.2)
    if not parameters or len(parameters) > 64:
        raise ValueError("Fit supports 1..64 editable scalar parameters")
    x0 = np.array(values, dtype=float)
    lo, hi = x0-np.array(limits), x0+np.array(limits)
    for i, refs in enumerate(parameters):
        if refs[0][1] == "width":
            lo[i], hi[i] = max(.25, lo[i]), min(12, hi[i])
    if np.any(lo > x0) or np.any(hi < x0):
        raise ValueError("Initial line width outside the supported range")
    background = np.array([int(canvas.get("background", "FFFFFF")[i:i+2], 16)
                           for i in (0, 2, 4)], dtype=float)
    active = np.max(np.abs(reference.astype(float)-background), axis=2) > 24
    matching = np.zeros(reference.shape[:2], dtype=bool)
    for obj in objects:
        for key in ("fill", "line"):
            color = obj["style"].get(key)
            if not color:
                continue
            direction = np.array([int(color[i:i+2], 16) for i in (0, 2, 4)])-background
            squared = float(direction @ direction)
            if squared:
                coverage = np.clip((reference-background) @ direction/squared, 0, 1)
                expected = background+coverage[..., None]*direction
                matching |= np.max(np.abs(reference-expected), axis=2) <= 24
    if np.count_nonzero(active) < 8:
        raise ValueError("Too little reference foreground to measure")
    if np.count_nonzero(active & ~matching) > max(4, np.count_nonzero(active)*.02):
        raise ValueError("Reference ROI contains unmodeled colors; isolate the target or include context")
    reference_float = reference.astype(float)/255
    # A finite pixel-scale Jacobian avoids zero derivatives on quantized PNGs.
    stride = 2 if reference.shape[0]*reference.shape[1] > 12000 else 1
    target = gaussian_filter(reference_float, (.65, .65, 0))[::stride, ::stride].ravel()
    evaluations = 0
    rejected_geometry_candidates = 0
    best = None
    size_overrides = {}
    history = []

    def candidate(x):
        result = copy.deepcopy(initial)
        for value, refs in zip(x, parameters):
            for oi, ci, vi in refs:
                if ci == "width":
                    result[oi]["style"][vi] = float(value)
                else:
                    result[oi]["commands"][ci][vi] = float(value)
        for oi, overrides in size_overrides.items():
            result[oi]["style"].update(overrides)
        return result

    def residual(x):
        nonlocal evaluations, best, rejected_geometry_candidates
        if evaluations >= max_evaluations or time.monotonic()-started >= max_seconds:
            raise _BudgetReached()
        objects_now = candidate(x)
        rgb = render(objects_now, canvas, roi)
        evaluations += 1
        data = gaussian_filter(rgb.astype(float)/255, (.65, .65, 0))[::stride, ::stride].ravel()-target
        cost = float(data @ data)
        if best is None or cost < best["cost"]:
            try:
                for before, after in zip(initial, objects_now):
                    if before["id"] in selected:
                        _check_geometry_preserved(before, after)
            except ValueError:
                rejected_geometry_candidates += 1
            else:
                best = {"cost": cost, "x": x.copy(), "objects": objects_now, "rgb": rgb}
        return np.r_[data, .001*(x-x0)/np.array(limits)]

    def jacobian(x):
        center = residual(x)
        columns = []
        for i, step in enumerate(steps):
            moved = x.copy()
            direction = step if x[i]+step <= hi[i] else -step
            if x[i]+direction < lo[i]:
                direction = (hi[i]-lo[i])/2
            moved[i] += direction
            columns.append((residual(moved)-center)/direction)
        return np.column_stack(columns)

    initial_rgb = render(objects, canvas, roi)
    termination = "solver_finished"
    try:
        residual(x0)
        opt = least_squares(residual, x0, jac=jacobian, bounds=(lo, hi),
                            max_nfev=30, ftol=2e-5, xtol=2e-5, gtol=1e-5,
                            tr_solver="lsmr", x_scale="jac")
        history.append({"stage": "geometry", "status": int(opt.status), "nfev": opt.nfev})
        if search_arrow_sizes and any(obj["id"] in selected and any(
                obj["style"].get(key) == "triangle" for key in ("begin_arrow", "end_arrow"))
                for obj in initial):
            from itertools import product
            start = best["x"].copy()
            for oi, obj in enumerate(initial):
                if obj["id"] not in selected:
                    continue
                for endpoint in ("begin_arrow", "end_arrow"):
                    if obj["style"].get(endpoint) != "triangle":
                        continue
                    current = copy.deepcopy(size_overrides)
                    for width, length in product(["sm", "med", "lg"], repeat=2):
                        size_overrides = copy.deepcopy(current)
                        size_overrides.setdefault(oi, {}).update(
                            {endpoint+"_width": width, endpoint+"_length": length})
                        pi = width_parameters.get(oi)
                        widths = (np.unique(np.r_[start[pi], np.linspace(lo[pi], hi[pi], 9),
                                  np.arange(math.ceil(lo[pi]*4), math.floor(hi[pi]*4)+1)/4])
                                  if pi is not None else [None])
                        for stroke_width in widths:
                            trial = start.copy()
                            if pi is not None:
                                trial[pi] = stroke_width
                            residual(trial)
                    size_overrides = {j: {k: v for k, v in o["style"].items()
                                          if k.endswith(("_arrow_width", "_arrow_length"))}
                                      for j, o in enumerate(best["objects"])}
                    start = best["x"].copy()
            opt = least_squares(residual, best["x"], jac=jacobian, bounds=(lo, hi),
                                max_nfev=12, ftol=2e-5, xtol=2e-5, gtol=1e-5,
                                tr_solver="lsmr", x_scale="jac")
            history.append({"stage": "arrow_refinement", "status": int(opt.status), "nfev": opt.nfev})
    except _BudgetReached:
        termination = "bounded_budget_reached"
    if best is None:
        raise ValueError("Budget expired before an initial measurement")
    suggestions = []
    for before, after in zip(initial, best["objects"]):
        if before["id"] in selected:
            _check_geometry_preserved(before, after)
            suggestions.append({"id": after["id"], "commands": after["commands"],
                                "style": {k: v for k, v in after["style"].items()
                                          if before["style"].get(k) != v}})
    return {"status": "suggestion_only", "initial_preview": region_score(reference, initial_rgb, background),
            "fitted_preview": region_score(reference, best["rgb"], background),
            "suggestions": suggestions, "evaluations": evaluations, "termination": termination,
            "elapsed_seconds": time.monotonic()-started, "solver": history,
            "parameter_count": len(parameters), "topology_preserved": True,
            "rejected_geometry_candidates": rejected_geometry_candidates,
            "joint_constraints": joint_constraints,
            "auto_adopt": False, "visual_acceptance": "not_checked",
            "scope": "SVG advisory fit; render the proposed native scene with real PowerPoint"}


def fit(scene_path, request_path, outdir):
    scene_path, request_path, outdir = map(Path, (scene_path, request_path, outdir))
    scene, request = read_json(scene_path), read_json(request_path)
    source_hash, request_hash = sha256(scene_path), sha256(request_path)
    if request.get("source_sha256") != source_hash:
        raise ValueError("Stale scene hash")
    if set(request)-{"source_sha256", "targets", "limits"}:
        raise ValueError("Unknown path fit request fields")
    issues = validate(scene, scene_path.parent)
    if issues:
        raise ValueError("Source scene invalid: "+"; ".join(issues[:5]))
    targets = request.get("targets", [])
    if not isinstance(targets, list) or not 1 <= len(targets) <= 16:
        raise ValueError("Supply 1..16 measured regions")
    limits = request.get("limits", {})
    if set(limits)-{"coordinate_limit", "width_limit_pt", "max_evaluations", "max_seconds",
                   "search_arrow_sizes"}:
        raise ValueError("Unknown fit limits")
    if (not isinstance(limits.get("max_seconds", 90), (int, float))
            or len(targets)*limits.get("max_seconds", 90) > 720):
        raise ValueError("Aggregate fit time budget must be at most 720 seconds")
    results = []
    for row in targets:
        if set(row) != {"slide", "ids", "context_ids", "reference", "roi"}:
            raise ValueError("Each region needs slide, ids, context_ids, reference and roi")
        slide = next(s for s in scene["slides"] if s["id"] == row["slide"])
        keys = row["ids"]+row["context_ids"]
        if len(keys) != len(set(keys)):
            raise ValueError("Target and context IDs must be distinct")
        objects = [o for o in slide["objects"] if o["id"] in keys]
        if set(keys) != {o["id"] for o in objects}:
            raise ValueError("All measured objects must be explicit top-level paths")
        path = Path(row["reference"]).resolve()
        reference_hash = sha256(path)
        with Image.open(path) as image:
            if list(image.size) != [scene["canvas"]["width"], scene["canvas"]["height"]]:
                raise ValueError("Full reference image must match the scene canvas")
            crop = np.asarray(image.convert("RGB").crop(row["roi"]))
        result = fit_region(objects, row["ids"], scene["canvas"], row["roi"], crop, **limits)
        if sha256(path) != reference_hash:
            raise ValueError("Reference changed while fitting")
        results.append({**row, "reference_sha256": reference_hash, **result})
    if sha256(scene_path) != source_hash or sha256(request_path) != request_hash:
        raise ValueError("Source or request changed while fitting")
    report = {"version": "native-path-fit/1", "source_sha256": source_hash,
              "request_sha256": request_hash, "limits": limits, "targets": results,
              "tool_sha256": {name: sha256(Path(__file__).parent/name)
                              for name in ("path_fit.py", "graphics_preview.py", "graphics_geometry.py")},
              "scope": "Bounded native suggestions, no automatic adoption or visual approval"}
    with staged_directory(outdir) as stage:
        write_json(stage/"suggestions.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    result = fit(args.scene, args.request, args.outdir)
    print(json.dumps({"targets": len(result["targets"]), "outdir": str(args.outdir)}, indent=2))
