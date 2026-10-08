"""Bounded native text specimens and pixel-based alignment suggestions.

Plain and explicitly selected single-color mixed runs on flat backgrounds.
No OCR, reference scene, automatic adoption or visual approval is performed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pptx import build
from common import read_json, sha256, staged_directory, write_json
from validate_scene import validate


def _refined_text(original, sample):
    obj = copy.deepcopy(original)
    st = obj["style"]
    st["font_size_pt"] += sample["delta"]
    for i, run in enumerate(obj.get("runs", [])):
        script = run.get("baseline", "normal") != "normal"
        if sample.get("font_only") and script:
            # Materialize inherited script size before changing the base font.
            run["font_size_pt"] = run.get("font_size_pt", original["style"]["font_size_pt"])
        elif "font_size_pt" in run:
            run["font_size_pt"] += sample["delta"]
        if (run.get("baseline", "normal") != "normal"
                and ("script_runs" not in sample or i in sample["script_runs"])):
            run["font_size_pt"] = run.get("font_size_pt", st["font_size_pt"])+sample.get("script_delta", 0)
        if i in sample.get("spacing_runs", []):
            run["char_spacing_pt"] = (
                run.get("char_spacing_pt", st.get("char_spacing_pt", 0))+sample["spacing_delta_pt"])
        if (run.get("font_size_pt", st["font_size_pt"]) <= 0
                or not -20 <= run.get("char_spacing_pt", st.get("char_spacing_pt", 0)) <= 100):
            raise ValueError("Refinement exceeds native font or spacing limits")
    if st["font_size_pt"] <= 0:
        raise ValueError("Refinement requires positive font size")
    return obj


def _packing_grid(canvas):
    width, height = canvas["width"], canvas["height"]
    if any(type(n) not in (int, float) or not low <= n <= 4096 or n != int(n)
           for n, low in ((width, 320), (height, 180))):
        raise ValueError("Packed specimens require integer canvas dimensions within 320..4096 by 180..4096")
    width, height = int(width), int(height)
    return width//2, height//4, round(20*width/960), round(24*height/540)


def _specimen_cell(obj, roi, cell, canvas):
    """Use integer translations so packing preserves each original pixel phase."""
    x, y, _, _ = obj["bbox"]
    cw, ch, mx, my = _packing_grid(canvas)
    dx, dy = cell % 2*cw + mx-int(x), cell // 2*ch + my-int(y)
    packed = [roi[0]+dx, roi[1]+dy, roi[2]+dx, roi[3]+dy]
    bounds = [cell % 2*cw, cell//2*ch, cell % 2*cw+cw, cell//2*ch+ch]
    if not (bounds[0] <= packed[0] < packed[2] <= bounds[2]
            and bounds[1] <= packed[1] < packed[3] <= bounds[3]):
        raise ValueError("Refined ROI extends outside its specimen cell")
    return [dx, dy], packed


def refined_plan(scene_path, request_path, outdir):
    """Pack variants into eight cells per page, retaining their subpixel phase."""
    source, request = read_json(scene_path), read_json(request_path)
    if request.get("source_sha256") != sha256(scene_path):
        raise ValueError("Stale text scene hash")
    spacing = request.get("spacing_deltas_pt")
    script = request.get("script_deltas_pt")
    font = request.get("font_deltas_pt")
    if sum(v is not None for v in (spacing, script, font)) > 1:
        raise ValueError("Select one sizing or spacing mode, not both in one plan")
    keys = ({"source_sha256", "targets"}
            | ({"spacing_deltas_pt"} if spacing is not None else set())
            | ({"script_deltas_pt"} if script is not None else set())
            | ({"font_deltas_pt"} if font is not None else set())
            | ({"shift_limit_px"} if "shift_limit_px" in request else set()))
    if set(request) != keys or validate(source, scene_path.parent):
        raise ValueError("Valid source and explicit text targets required")
    shift_limit = request.get("shift_limit_px", 0 if script is not None else 6)
    if (type(shift_limit) is not int or not 0 <= shift_limit <= 6
            or script is not None and shift_limit != 0):
        raise ValueError("Shift limit must be 0..6 pixels; scripts require zero")
    if font is not None and (
            not isinstance(font, list) or not 1 <= len(font) <= 17
            or any(type(d) not in (int, float) or not np.isfinite(d) or abs(d) > 2 for d in font)
            or len(set(font)) != len(font) or 0 not in font):
        raise ValueError("Font deltas need 1..17 distinct finite values within 2pt, including zero")
    if spacing is not None and (
            not isinstance(spacing, list) or not 1 <= len(spacing) <= 25
            or any(type(d) not in (int, float) or not np.isfinite(d) or abs(d) > 12 for d in spacing)
            or len(set(spacing)) != len(spacing) or 0 not in spacing):
        raise ValueError("Spacing deltas need 1..25 distinct finite values within 12pt, including zero")
    if script is not None and (
            not isinstance(script, list) or not 1 <= len(script) <= 25
            or any(type(d) not in (int, float) or not np.isfinite(d) or abs(d) > 8 for d in script)
            or len(set(script)) != len(script) or 0 not in script):
        raise ValueError("Script deltas need 1..25 distinct finite values within 8pt, including zero")
    if not isinstance(request["targets"], list) or not 1 <= len(request["targets"]) <= 8:
        raise ValueError("Refined plan supports 1..8 isolated text targets")
    canvas, targets, refs = source["canvas"], [], {}
    cell_width, cell_height, margin_x, margin_y = _packing_grid(canvas)
    cells_fit = True
    seen = set()
    for i, row in enumerate(request["targets"]):
        row_keys = ({"slide", "id", "reference", "roi"}
                    | ({"spacing_runs"} if spacing is not None else set())
                    | ({"script_runs"} if script is not None else set())
                    | ({"font_anchors"} if font is not None and "font_anchors" in row else set()))
        if set(row) != row_keys:
            raise ValueError("Refined targets need slide, id, reference, roi")
        if (row["slide"], row["id"]) in seen:
            raise ValueError("Duplicate refined text target")
        seen.add((row["slide"], row["id"]))
        slide = next(s for s in source["slides"] if s["id"] == row["slide"])
        obj = next(o for o in slide["objects"] if o["id"] == row["id"])
        st = obj.get("style", {})
        if (obj["kind"] != "text" or obj.get("rotation", 0) or "paragraphs" in obj
                or st.get("native_format") or st.get("text_outline") or st.get("warp")
                or not st.get("font_size_pt") or st.get("fill") or st.get("line")
                or obj["bbox"][2] > canvas["width"]
                or obj["bbox"][3] > cell_height-round(49*canvas["height"]/540)):
            raise ValueError("Refined specimens need short unrotated plain or mixed text without effects")
        runs = obj.get("runs", [])
        if any(r.get("color", st.get("color", "222222")) != st.get("color", "222222") for r in runs):
            raise ValueError("Mixed-color runs require separate measurement")
        if spacing is not None:
            indices = row["spacing_runs"]
            if (not isinstance(indices, list) or not 1 <= len(indices) <= 8
                    or any(type(n) is not int or not 0 <= n < len(runs) for n in indices)
                    or len(set(indices)) != len(indices)
                    or any(not runs[n]["text"] or runs[n]["text"].strip(" ") for n in indices)):
                raise ValueError("Spacing targets must explicitly select 1..8 distinct ASCII-space runs")
        if script is not None:
            indices = row["script_runs"]
            if (not isinstance(indices, list) or not 1 <= len(indices) <= 8
                    or any(type(n) is not int or not 0 <= n < len(runs) for n in indices)
                    or len(set(indices)) != len(indices)
                    or any(runs[n].get("baseline") not in {"subscript", "superscript"} for n in indices)):
                raise ValueError("Script targets must select 1..8 distinct native script runs")
        roi = row["roi"]
        if (len(roi) != 4 or any(type(n) is not int for n in roi)
                or not 0 <= roi[0] < roi[2] <= canvas["width"]
                or not 0 <= roi[1] < roi[3] <= canvas["height"]
                or roi[3]-roi[1] > cell_height-round(25*canvas["height"]/540)):
            raise ValueError("Refined text ROI must be a short region within the canvas")
        # Wide headings cannot share a translated half-width cell. Preserve their
        # physical coordinates and use the existing overlap-aware page packing.
        compact = (obj["bbox"][2] <= cell_width-2*margin_x
                   and roi[2]-roi[0] <= cell_width-margin_x)
        if compact:
            try:
                _specimen_cell(obj, roi, 0, canvas)
            except ValueError:
                compact = False
        cells_fit = cells_fit and compact
        anchors = row.get("font_anchors")
        if anchors is not None:
            if (not isinstance(anchors, list) or not 1 <= len(anchors) <= 4
                    or any(not isinstance(box, list) or len(box) != 4
                           or any(type(n) is not int for n in box)
                           or not roi[0] <= box[0] < box[2] <= roi[2]
                           or not roi[1] <= box[1] < box[3] <= roi[3] for box in anchors)):
                raise ValueError("Font anchors need 1..4 integer rectangles within the target ROI")
            for i, a in enumerate(anchors):
                if any(max(a[0], b[0]) < min(a[2], b[2])
                       and max(a[1], b[1]) < min(a[3], b[3]) for b in anchors[:i]):
                    raise ValueError("Font anchors must not overlap")
        ref = Path(row["reference"]).resolve()
        with Image.open(ref) as image:
            if image.size != (canvas["width"], canvas["height"]):
                raise ValueError("Reference size mismatch")
        previous = refs.get(slide["id"])
        if previous and previous["path"] != str(ref):
            raise ValueError("One reference per slide required")
        refs[slide["id"]] = {"path": str(ref), "sha256": sha256(ref)}
        targets.append({"slide": slide["id"], "id": obj["id"], "object": copy.deepcopy(obj),
                        "roi_xyxy": roi, "spacing_runs": row.get("spacing_runs", []),
                        **({"font_anchors": anchors} if anchors is not None else {}),
                        "script_runs": row.get("script_runs", []), "samples": []})
    from itertools import product
    if font is not None:
        settings = [{"delta": d, "script_delta": 0, "font_only": True} for d in font]
        phases = list(product([0, .5], repeat=2))
    elif spacing is None and script is None:
        settings = [{"delta": d, "script_delta": 0}
                    for d in [-1, -.75, -.5, -.25, 0, .25, .5, .75, 1]]
        if any(r.get("baseline", "normal") != "normal" for t in targets for r in t["object"].get("runs", [])):
            settings += [{"delta": 0, "script_delta": d} for d in [-4, -2, -1, 1, 2, 4]]
        phases = list(product([0, .5], repeat=2))
    elif spacing is not None:
        settings = [{"delta": 0, "script_delta": 0, "spacing_delta_pt": d} for d in spacing]
        phases = [(0, 0)]
    else:
        settings = [{"delta": 0, "script_delta": d} for d in script]
        phases = [(0, 0)]
    # Office rasterizes text against physical slide coordinates before export.
    # Integer export-pixel translations alone are insufficient when the export
    # scale differs from 96 dpi. Preserve original coordinates in that case.
    translated_cells = (cells_fit and abs(canvas["width_pt"]-.75*canvas["width"]) < 1e-9
                        and abs(canvas["height_pt"]-.75*canvas["height"]) < 1e-9)
    slides, sample_count, occupied = [], 0, []
    for setting in settings:
        for px, py in phases:
            for target in targets:
                if translated_cells:
                    cell = sample_count % 8
                    if cell == 0:
                        slides.append({"id": f"packed-{len(slides)}", "objects": []})
                    move, packed = _specimen_cell(target["object"], target["roi_xyxy"], cell, canvas)
                else:
                    move, packed = [0, 0], target["roi_xyxy"][:]
                    x,y,w,h = target["object"]["bbox"]
                    area = [min(packed[0],x+px), min(packed[1],y+py),
                            max(packed[2],x+w+px), max(packed[3],y+h+py)]
                    if (not slides or len(occupied) == 8 or any(
                            max(area[0],b[0]) < min(area[2],b[2])
                            and max(area[1],b[1]) < min(area[3],b[3]) for b in occupied)):
                        slides.append({"id": f"original-{len(slides)}", "objects": []})
                        occupied = []
                    occupied.append(area)
                if len(slides) > 68:
                    raise ValueError("Refinement exceeds 68 pages at this export scale; reduce targets or variants")
                sample = {**setting, "index": len(slides), "phase": [px, py],
                          "packing_move": move, "packed_roi_xyxy": packed}
                if spacing is not None:
                    sample["spacing_runs"] = target["spacing_runs"]
                if script is not None:
                    sample["script_runs"] = target["script_runs"]
                obj = _refined_text(target["object"], sample)
                obj["id"] = f"sample-{sample_count}"
                obj["bbox"][0] += move[0]+px
                obj["bbox"][1] += move[1]+py
                obj["style"]["color"] = "000000"
                for run in obj.get("runs", []):
                    run["color"] = "000000"
                slides[-1]["objects"].append(obj)
                target["samples"].append(sample)
                sample_count += 1
    specimen = {"version": "1.0", "canvas": {**canvas, "background": "FFFFFF"}, "slides": slides}
    with staged_directory(outdir) as stage:
        write_json(stage / "specimens.scene.json", specimen)
        build(stage / "specimens.scene.json", stage / "specimens.pptx")
        write_json(stage / "source.scene.json", source)
        write_json(stage / "plan.json", {"version": "native-text-fit/3", "source_path": str(scene_path.resolve()),
            "source_sha256": sha256(scene_path), "source_copy_sha256": sha256(stage / "source.scene.json"),
            "specimens_sha256": sha256(stage / "specimens.pptx"), "request_sha256": sha256(request_path),
            "references": refs, "targets": targets, "skipped": [], "shift_limit_px": shift_limit,
            "canvas": canvas, "page_exports_planned": len(slides), "status": "awaiting_office",
            "sample_count": sample_count, "samples_per_page": 8,
            "placement": "translated_96dpi_cells" if translated_cells else "original_coordinates",
            "search": "font" if font is not None else "spacing" if spacing is not None else "script" if script is not None else "size_and_phase",
            "scope": "Packed native text specimens; contents, run order and baseline kinds unchanged"})
    return {"targets": len(targets), "page_exports_planned": len(slides)}


def plan(scene_path, references, outdir, deltas=None, shift_limit=6):
    deltas = deltas if deltas is not None else [-1, -.75, -.5, -.25, 0, .25, .5, .75, 1]
    if (not isinstance(deltas, list) or not 1 <= len(deltas) <= 13
            or any(type(d) not in (int, float) or not np.isfinite(d) or abs(d) > 2 for d in deltas)
            or len(set(deltas)) != len(deltas)):
        raise ValueError("Supply 1..13 distinct finite size deltas within two points")
    if type(shift_limit) is not int or not 0 <= shift_limit <= 12:
        raise ValueError("shift_limit must be 0..12 pixels")
    source = read_json(scene_path)
    canvas = source["canvas"]
    if [canvas["width"], canvas["height"]] != [round(canvas["width"]), round(canvas["height"])]:
        raise ValueError("Integer export canvas required")
    if len(source["slides"])*len(deltas) > 128:
        raise ValueError("At most 128 specimen page exports per plan")
    slides, targets, skipped, refs = [], [], [], {}
    for si, slide in enumerate(source["slides"]):
        reference = Path(references[slide["id"]]).resolve()
        with Image.open(reference) as image:
            if list(image.size) != [canvas["width"], canvas["height"]]:
                raise ValueError("Reference must match the logical canvas exactly")
        refs[slide["id"]] = {"path": str(reference), "sha256": sha256(reference)}
        eligible = []
        for obj in slide["objects"]:
            if obj["kind"] != "text":
                continue
            if ("text" not in obj or obj.get("rotation", 0)
                    or obj.get("style", {}).get("native_format")
                    or not obj.get("style", {}).get("font_size_pt")):
                skipped.append({"slide": slide["id"], "id": obj["id"],
                                "reason": "Mixed runs, rotation or effects require separate review"})
                continue
            eligible.append(obj)
            targets.append({"slide": slide["id"], "id": obj["id"], "object": copy.deepcopy(obj)})
        for di, delta in enumerate(deltas):
            objects = copy.deepcopy(eligible)
            if not objects:
                continue
            for obj in objects:
                obj["style"]["font_size_pt"] += delta
                obj["style"]["color"] = "000000"
                for key in ("fill", "gradient", "line", "text_outline"):
                    obj["style"].pop(key, None)
            slides.append({"id": f"probe-{si}-{di}", "objects": objects})
            for target in targets:
                if target["slide"] == slide["id"]:
                    target.setdefault("samples", []).append({"index": len(slides), "delta": delta})
    if not targets or len(targets) > 64:
        raise ValueError("Plan needs 1..64 supported text targets")
    specimen = {"version": "1.0", "canvas": {**canvas, "background": "FFFFFF"}, "slides": slides}
    with staged_directory(outdir) as stage:
        write_json(stage/"specimens.scene.json", specimen)
        build(stage/"specimens.scene.json", stage/"specimens.pptx")
        write_json(stage/"source.scene.json", source)
        record = {"version": "native-text-fit/1", "source_path": str(scene_path.resolve()),
                  "source_sha256": sha256(scene_path), "source_copy_sha256": sha256(stage/"source.scene.json"),
                  "specimens_sha256": sha256(stage/"specimens.pptx"),
                  "references": refs, "targets": targets, "skipped": skipped,
                  "shift_limit_px": shift_limit, "canvas": canvas,
                  "page_exports_planned": len(slides), "status": "awaiting_office",
                  "scope": "Native size specimens only, no auto-adoption or visual approval"}
        write_json(stage/"plan.json", record)
    return {"targets": len(targets), "skipped": len(skipped), "page_exports_planned": len(slides)}


def _rgb(hex_color):
    return np.array([int(hex_color[i:i+2], 16) for i in (0, 2, 4)], dtype=np.float32)


def _reference_ink(rgb, color):
    values, counts = np.unique(rgb.reshape(-1, 3), axis=0, return_counts=True)
    background = values[counts.argmax()].astype(np.float32)
    coverage = counts.max()/rgb.shape[0]/rgb.shape[1]
    if coverage < .4:
        # Compressed screenshots seldom retain one exact background RGB value.
        # Accept only a narrow cohort around the dominant color; broad gradients
        # and textured regions still lack sufficient shared background support.
        # Exact foreground glyphs can outnumber any individual noisy background
        # color. Find the dominant coarse color cluster before the narrow check.
        quantized = rgb.reshape(-1, 3)//16
        _, inverse, cluster_counts = np.unique(quantized, axis=0, return_inverse=True, return_counts=True)
        background = np.median(rgb.reshape(-1, 3)[inverse == cluster_counts.argmax()], axis=0).astype(np.float32)
        near = np.max(np.abs(rgb.astype(np.float32)-background), axis=2) <= 8
        coverage = float(near.mean())
        if coverage >= .4:
            background = np.median(rgb[near], axis=0).astype(np.float32)
    direction = _rgb(color)-background
    norm = float(np.dot(direction, direction))
    if norm < 24**2 or coverage < .4:
        raise ValueError("Insufficient contrast or non-flat local background")
    projection = np.clip(np.einsum("ijk,k->ij", rgb.astype(float)-background, direction)/norm, 0, 1)
    # Discard background outside a colored text container, connected to ROI edges.
    mask = Image.fromarray((projection > .12).astype(np.uint8)*255).copy()
    width, height = mask.size
    border = [(x, y) for x in range(width) for y in (0, height-1)]
    border += [(x, y) for y in range(height) for x in (0, width-1)]
    for point in border:
        if mask.getpixel(point):
            ImageDraw.floodfill(mask, point, 0)
    inside = np.asarray(mask) > 0
    solid = rgb[(projection > .92) & inside]
    if len(solid) < 4:
        raise ValueError("Too few opaque glyph samples")
    foreground = np.median(solid, axis=0).astype(np.uint8)
    direction = foreground.astype(float)-background
    norm = float(np.dot(direction, direction))
    if norm < 24**2:
        raise ValueError("Insufficient measured glyph contrast")
    projection = np.clip(np.einsum("ijk,k->ij", rgb.astype(float)-background, direction)/norm, 0, 1)
    projection *= inside
    return projection.astype(np.float32), "".join(f"{int(v):02X}" for v in foreground)


def _shift(a, dx, dy):
    result = np.zeros_like(a)
    h, w = a.shape
    x1, x2 = max(0, dx), min(w, w+dx)
    y1, y2 = max(0, dy), min(h, h+dy)
    if x1 < x2 and y1 < y2:
        result[y1:y2, x1:x2] = a[y1-dy:y2-dy, x1-dx:x2-dx]
    return result


def fit_ink(reference, candidate, limit=6):
    if reference.shape != candidate.shape or not reference.size:
        raise ValueError("Equal nonempty ink arrays required")
    if type(limit) is not int or not 0 <= limit <= 12:
        raise ValueError("Bounded alignment limit required")
    if max(float(reference.sum()), float(candidate.sum())) < 4:
        raise ValueError("Insufficient glyph coverage")
    best = None
    for dy in range(-limit, limit+1):
        for dx in range(-limit, limit+1):
            moved = _shift(candidate, dx, dy)
            denominator = float(np.maximum(reference, moved).sum())
            score = 1-float(np.abs(reference-moved).sum())/max(denominator, 1e-9)
            row = {"score": score, "dx_px": dx, "dy_px": dy}
            rank = (score, -abs(dx)-abs(dy))
            if best is None or rank > best[0]:
                best = (rank, row)
    return best[1]


def evaluate(plan_dir, office_dir, output):
    if output.exists():
        raise FileExistsError(output)
    started = time.monotonic()
    plan = read_json(plan_dir/"plan.json")
    receipt = read_json(office_dir/"office-render.json")
    if (receipt.get("status") != "passed" or receipt.get("renderer") != "Microsoft PowerPoint"
            or receipt.get("probe_only") or receipt.get("pptx_sha256") != plan["specimens_sha256"]
            or sha256(plan_dir/"specimens.pptx") != plan["specimens_sha256"]
            or sha256(plan_dir/"source.scene.json") != plan["source_copy_sha256"]
            or sha256(Path(plan["source_path"])) != plan["source_sha256"]):
        raise ValueError("Current source and real Office specimen evidence required")
    rows = receipt["slides"]
    if len(rows) != plan["page_exports_planned"] or len({r["index"] for r in rows}) != len(rows):
        raise ValueError("Office specimen pages incomplete or duplicated")
    arrays = {}
    for row in rows:
        image_path = (office_dir/row["file"]).resolve()
        if not image_path.is_relative_to(office_dir.resolve()) or sha256(image_path) != row["sha256"]:
            raise ValueError("Office image identity mismatch")
        with Image.open(image_path) as im:
            if list(im.size) != [plan["canvas"]["width"], plan["canvas"]["height"]]:
                raise ValueError("Specimen export size mismatch")
            arrays[row["index"]] = np.asarray(im.convert("RGB"))
    refs = {}
    for sid, row in plan["references"].items():
        if sha256(Path(row["path"])) != row["sha256"]:
            raise ValueError("Reference changed")
        with Image.open(row["path"]) as im:
            refs[sid] = np.asarray(im.convert("RGB"))
    targets = []
    for target in plan["targets"]:
        obj = target["object"]
        x, y, w, h = obj["bbox"]
        padding = plan["shift_limit_px"]+2
        box = target.get("roi_xyxy") or [max(0, int(x)-padding), max(0, int(y)-padding),
               min(plan["canvas"]["width"], int(np.ceil(x+w))+padding),
               min(plan["canvas"]["height"], int(np.ceil(y+h))+padding)]
        x1, y1, x2, y2 = box
        try:
            if plan.get("search") == "script":
                # Tiny scripts may contain only antialiasing. Estimate their shared
                # color from the same text line before cropping the selected glyph.
                a, b = max(0, min(int(x)-padding, x1)), max(0, min(int(y)-padding, y1))
                c = min(plan["canvas"]["width"], max(int(np.ceil(x+w))+padding, x2))
                d = min(plan["canvas"]["height"], max(int(np.ceil(y+h))+padding, y2))
                context, color = _reference_ink(refs[target["slide"]][b:d, a:c],
                                                obj["style"].get("color", "222222"))
                ink = context[y1-b:y2-b, x1-a:x2-a]
            else:
                ink, color = _reference_ink(refs[target["slide"]][y1:y2, x1:x2],
                                            obj["style"].get("color", "222222"))
            candidates = []
            for sample in target["samples"]:
                a, b, c, d = sample.get("packed_roi_xyxy", target.get("packed_roi_xyxy", box))
                crop = arrays[sample["index"]][b:d, a:c]
                test_ink = 1-crop.astype(np.float32).mean(axis=2)/255
                anchors = target.get("font_anchors")
                if anchors:
                    anchor_fits = []
                    for ax, ay, bx, by in anchors:
                        local = (slice(ay-y1, by-y1), slice(ax-x1, bx-x1))
                        anchor_fits.append(fit_ink(ink[local], test_ink[local], plan["shift_limit_px"]))
                    # Independent local alignment avoids mistaking intervening
                    # script/space errors for a normal-font size error. Only
                    # the first anchor contributes the whole-object position.
                    fitted = {**anchor_fits[0], "score": min(r["score"] for r in anchor_fits),
                              "anchor_fits": anchor_fits}
                else:
                    fitted = fit_ink(ink, test_ink, plan["shift_limit_px"])
                phase = sample.get("phase", [0, 0])
                candidate = {**fitted,
                    "dx_px": fitted["dx_px"]+phase[0], "dy_px": fitted["dy_px"]+phase[1],
                    "font_size_pt": obj["style"]["font_size_pt"]+sample["delta"], "color": color,
                    "sample_index": sample["index"]}
                if "runs" in obj:
                    candidate["runs"] = _refined_text(obj, sample)["runs"]
                if "spacing_delta_pt" in sample:
                    candidate["spacing_delta_pt"] = sample["spacing_delta_pt"]
                if "script_runs" in sample:
                    candidate["script_delta_pt"] = sample["script_delta"]
                if sample.get("font_only"):
                    candidate["font_delta_pt"] = sample["delta"]
                candidates.append(candidate)
            candidates.sort(key=lambda r: (-r["score"], abs(r["font_size_pt"]-obj["style"]["font_size_pt"]),
                                           abs(r["dx_px"])+abs(r["dy_px"])))
            targets.append({"slide": target["slide"], "id": target["id"], "roi_xyxy": box,
                            "score_scope": "selected_roi_only_not_whole_line",
                            **({"font_anchors": target["font_anchors"],
                                "alignment_anchor": 0} if target.get("font_anchors") else {}),
                            "status": "suggestion_only", "best": candidates[0],
                            "alternatives": candidates[1:3]})
        except ValueError as exc:
            targets.append({"slide": target["slide"], "id": target["id"],
                            "status": "unmeasurable", "reason": str(exc)})
    report = {"version": "native-text-fit-result/1", "source_sha256": plan["source_sha256"],
              "plan_sha256": sha256(plan_dir/"plan.json"), "targets": targets,
              "tool_sha256": sha256(Path(__file__)), "specimen_version": plan["version"],
              "skipped": plan["skipped"], "elapsed_seconds": time.monotonic()-started,
              "auto_adopt": False, "visual_review": "pending",
              "scope": "Bounded glyph fit with unchanged text. Does not verify content, font identity or unseen glyphs."}
    write_json(output, report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--scene", type=Path, required=True)
    a.add_argument("--references", type=Path, required=True)
    a.add_argument("--outdir", type=Path, required=True)
    a = sub.add_parser("refine-plan", allow_abbrev=False)
    a.add_argument("--scene", type=Path, required=True)
    a.add_argument("--request", type=Path, required=True)
    a.add_argument("--outdir", type=Path, required=True)
    a = sub.add_parser("evaluate")
    a.add_argument("--plan", type=Path, required=True)
    a.add_argument("--office", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.action == "plan":
        result = plan(args.scene, read_json(args.references), args.outdir)
    elif args.action == "refine-plan":
        result = refined_plan(args.scene, args.request, args.outdir)
    else:
        result = evaluate(args.plan, args.office, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
