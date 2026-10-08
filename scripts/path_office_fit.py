"""Bounded real-Office path phase/width specimens after an advisory SVG fit."""
from __future__ import annotations

import argparse
import copy
from itertools import product
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pptx import build
from common import read_json, sha256, staged_directory, write_json
from native_practice import region_score
from patch_ops import _shift
from path_fit import _supported
from validate_scene import validate


def plan(scene_path, request_path, outdir):
    scene, request = read_json(scene_path), read_json(request_path)
    if request.get("source_sha256") != sha256(scene_path):
        raise ValueError("Stale scene hash")
    if validate(scene, scene_path.parent):
        raise ValueError("Invalid source scene")
    targets = copy.deepcopy(request.get("targets"))
    if not isinstance(targets, list) or not 1 <= len(targets) <= 16:
        raise ValueError("Supply 1..16 explicit regions")
    canvas = scene["canvas"]
    refs, selected = {}, {}
    seen = set()
    for target in targets:
        if (set(target) != {"slide", "ids", "context_ids", "reference", "roi"}
                or target["context_ids"]):
            raise ValueError("Office probes require isolated path groups without fixed context")
        sid = target["slide"]
        slide = next(s for s in scene["slides"] if s["id"] == sid)
        ids = target["ids"]
        if not isinstance(ids, list) or not ids or len(ids) > 4 or len(set(ids)) != len(ids):
            raise ValueError("Select 1..4 distinct paths per region")
        for ident in ids:
            if (sid, ident) in seen:
                raise ValueError("Each object may belong to only one measured region")
            seen.add((sid, ident))
            obj = next(o for o in slide["objects"] if o["id"] == ident)
            _supported(obj)
            selected.setdefault(sid, []).append(copy.deepcopy(obj))
        roi = target["roi"]
        if (len(roi) != 4 or any(type(v) is not int for v in roi)
                or not 0 <= roi[0] < roi[2] <= canvas["width"]
                or not 0 <= roi[1] < roi[3] <= canvas["height"]
                or max(roi[2]-roi[0], roi[3]-roi[1]) > 512):
            raise ValueError("Invalid image ROI")
        path = Path(target["reference"]).resolve()
        with Image.open(path) as image:
            if list(image.size) != [canvas["width"], canvas["height"]]:
                raise ValueError("Reference must match logical canvas")
        if sid in refs and refs[sid]["path"] != str(path):
            raise ValueError("One reference per slide required")
        refs[sid] = {"path": str(path), "sha256": sha256(path)}
    if len(selected)*12 > 48:
        raise ValueError("Office path fit is limited to 48 specimen pages")
    slides = []
    for si, (sid, objects) in enumerate(selected.items()):
        for dx, dy, width_delta in product([0, .5], [0, .5], [-.15, 0, .15]):
            copies = copy.deepcopy(objects)
            for obj in copies:
                _shift(obj, dx, dy)
                if obj["style"].get("line"):
                    obj["style"]["line_width_pt"] = max(.25, obj["style"].get("line_width_pt", 1)+width_delta)
            slides.append({"id": f"probe-{si}-{len(slides)}", "objects": copies})
            for target in targets:
                if target["slide"] == sid:
                    target.setdefault("samples", []).append({
                        "index": len(slides), "dx": dx, "dy": dy, "width_delta_pt": width_delta})
    specimen = {"version": "1.0", "canvas": canvas, "slides": slides}
    with staged_directory(outdir) as stage:
        write_json(stage / "source.scene.json", scene)
        write_json(stage / "specimens.scene.json", specimen)
        build(stage / "specimens.scene.json", stage / "specimens.pptx")
        record = {"version": "native-path-office-fit/1",
                  "source_path": str(scene_path.resolve()), "source_sha256": sha256(scene_path),
                  "source_copy_sha256": sha256(stage / "source.scene.json"),
                  "request_sha256": sha256(request_path),
                  "specimens_sha256": sha256(stage / "specimens.pptx"),
                  "references": refs, "targets": targets, "canvas": canvas,
                  "page_exports_planned": len(slides), "shift_limit_px": 2,
                  "scope": "Actual Office specimens required; no automatic adoption"}
        write_json(stage / "plan.json", record)
    return {"targets": len(targets), "page_exports_planned": len(slides)}


def translated_crop(rgb, roi, dx, dy, background):
    x1, y1, x2, y2 = roi
    result = np.empty((y2-y1, x2-x1, 3), dtype=np.uint8)
    result[:] = background
    sx1, sy1 = max(0, x1-dx), max(0, y1-dy)
    sx2, sy2 = min(rgb.shape[1], x2-dx), min(rgb.shape[0], y2-dy)
    if sx1 < sx2 and sy1 < sy2:
        tx, ty = sx1+dx-x1, sy1+dy-y1
        result[ty:ty+sy2-sy1, tx:tx+sx2-sx1] = rgb[sy1:sy2, sx1:sx2]
    return result


def evaluate(plan_dir, office_dir, output):
    if output.exists():
        raise FileExistsError(output)
    started = time.monotonic()
    record = read_json(plan_dir / "plan.json")
    receipt = read_json(office_dir / "office-render.json")
    if (receipt.get("renderer") != "Microsoft PowerPoint" or receipt.get("status") != "passed"
            or receipt.get("probe_only") or receipt.get("pptx_sha256") != record["specimens_sha256"]
            or sha256(plan_dir / "specimens.pptx") != record["specimens_sha256"]
            or sha256(plan_dir / "source.scene.json") != record["source_copy_sha256"]
            or sha256(Path(record["source_path"])) != record["source_sha256"]):
        raise ValueError("Current source and real Office specimen identity required")
    rows = receipt["slides"]
    if len(rows) != record["page_exports_planned"] or {r["index"] for r in rows} != set(range(1, len(rows)+1)):
        raise ValueError("Office specimen pages incomplete or duplicated")
    arrays, refs = {}, {}
    for row in rows:
        path = (office_dir / row["file"]).resolve()
        if not path.is_relative_to(office_dir.resolve()) or sha256(path) != row["sha256"]:
            raise ValueError("Office image identity mismatch")
        with Image.open(path) as image:
            if list(image.size) != [record["canvas"]["width"], record["canvas"]["height"]]:
                raise ValueError("Office canvas mismatch")
            arrays[row["index"]] = np.asarray(image.convert("RGB"))
    for sid, ref in record["references"].items():
        if sha256(Path(ref["path"])) != ref["sha256"]:
            raise ValueError("Reference changed")
        with Image.open(ref["path"]) as image:
            refs[sid] = np.asarray(image.convert("RGB"))
    source = read_json(plan_dir / "source.scene.json")
    background = np.array([int(record["canvas"].get("background", "FFFFFF")[i:i+2], 16)
                           for i in (0, 2, 4)], dtype=np.uint8)
    results = []
    for target in record["targets"]:
        x1, y1, x2, y2 = target["roi"]
        reference = refs[target["slide"]][y1:y2, x1:x2]
        candidates = []
        for sample in target["samples"]:
            for dx, dy in product(range(-2, 3), repeat=2):
                crop = translated_crop(arrays[sample["index"]], target["roi"], dx, dy, background)
                score = region_score(reference, crop, background)
                candidates.append({**sample, "dx": sample["dx"]+dx, "dy": sample["dy"]+dy, **score})
        candidates.sort(key=lambda row: (-row["score"], abs(row["dx"])+abs(row["dy"]),
                                         abs(row["width_delta_pt"])))
        best = candidates[0]
        objects = next(s["objects"] for s in source["slides"] if s["id"] == target["slide"])
        widths = {o["id"]: max(.25, o["style"].get("line_width_pt", 1)+best["width_delta_pt"])
                  for o in objects if o["id"] in target["ids"] and o["style"].get("line")}
        results.append({"slide": target["slide"], "ids": target["ids"], "roi": target["roi"],
                        "status": "suggestion_only", "best": best, "line_widths_pt": widths,
                        "alternatives": candidates[1:3]})
    result = {"version": "native-path-office-result/1", "source_sha256": record["source_sha256"],
              "plan_sha256": sha256(plan_dir / "plan.json"),
              "office_receipt_sha256": sha256(office_dir / "office-render.json"),
              "tool_sha256": sha256(Path(__file__)), "targets": results,
              "elapsed_seconds": time.monotonic()-started, "auto_adopt": False,
              "scope": "Measured native translation/width suggestions. Rebuild, rerender and review final patch."}
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", allow_abbrev=False)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--outdir", type=Path, required=True)
    p = sub.add_parser("evaluate", allow_abbrev=False)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--office", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = plan(args.scene, args.request, args.outdir)
    else:
        result = evaluate(args.plan, args.office, args.output)
    print(json.dumps(result, indent=2))
