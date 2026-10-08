"""Deterministic native PPT exercises and foreground-weighted diagnostics.

Private construction data must never be supplied to a blind model attempt.
Scores are diagnostics; Office, semantic and independent visual gates are separate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pptx import build
from common import read_json, sha256, walk_objects, write_json
from components import compile_component

BACKGROUND = "F7F9FC"
CANVAS = {"width": 960, "height": 540, "width_pt": 720, "height_pt": 405,
          "mapping": "uniform", "background": BACKGROUND}
EVIDENCE = {"status": "measured", "note": "Controlled native practice construction"}


def shape(oid, box, fill, geometry="rect", **extra):
    return {"id": oid, "kind": "shape", "bbox": box, "geometry": geometry,
            "style": {"fill": fill, "line": None}, "editability": "shape",
            "evidence": copy.deepcopy(EVIDENCE), **extra}


def text(oid, content, box, size=18, color="243341", **style):
    return {"id": oid, "kind": "text", "bbox": box, "text": content,
            "style": {"font": "Arial", "font_east_asia": "Microsoft YaHei",
                      "font_size_pt": size, "color": color, "margin_pt": 0, **style},
            "editability": "text", "evidence": copy.deepcopy(EVIDENCE)}


def path(oid, commands, fill=None, **style):
    return {"id": oid, "kind": "path", "commands": commands,
            "closed": commands[-1][0] == "Z", "editability": "path",
            "style": {"fill": fill, "line": None, **style},
            "evidence": copy.deepcopy(EVIDENCE)}


def gradient(colors, angle=0, radial=False, center=None):
    result = {"type": "radial" if radial else "linear",
              "stops": [{"position": i / (len(colors) - 1), "color": c}
                        for i, c in enumerate(colors)]}
    result.update({"center": center or [.5, .5]} if radial else {"angle_deg": angle})
    return result


def shadow(blur=5, dx=3, dy=5, alpha=.25):
    return {"version": "1", "shadow": {"enabled": True, "color": "243341",
            "alpha": alpha, "blur_pt": blur, "dx_pt": dx, "dy_pt": dy}}


def _case(name, title):
    return {"id": name, "objects": [text(name + "-title", title, [42, 25, 875, 46], 25, bold=True)]}, [
        {"id": "title", "bbox": [35, 20, 930, 78]}]


def _region(regions, name, x, y, w, h, margin=10):
    regions.append({"id": name, "bbox": [max(0, x-margin), max(0, y-margin),
                    min(960, x+w+margin), min(540, y+h+margin)]})


def make_cases():
    cases = []
    slide, regions = _case("basic-shapes", "01  Shapes and corner radii")
    boxes = [[55, 125, 235, 118], [365, 125, 235, 118], [675, 125, 235, 118],
             [55, 333, 235, 85], [400, 315, 145, 145], [700, 320, 190, 130]]
    specs = [("rect", "23888B", None), ("round_rect", "E98265", .05),
             ("round_rect", "6079C7", .23), ("round_rect", "D8A52C", .5),
             ("ellipse", "399878", None), ("triangle", "CB6382", None)]
    for i, (box, (geo, color, adjustment)) in enumerate(zip(boxes, specs)):
        obj = shape(f"basic-{i}", box, color, geo)
        if adjustment is not None:
            obj["adjustments"] = [adjustment]
        slide["objects"].append(obj)
        _region(regions, f"shape-{i}", *box)
    cases.append((slide, regions, "training"))

    slide, regions = _case("vector-paths", "02  Curves, polygons and holes")
    slide["objects"] += [
        path("polygon", [["M", 65, 170], ["L", 145, 112], ["L", 275, 145],
                         ["L", 265, 235], ["L", 120, 264], ["Z"]], "E98265"),
        path("leaf", [["M", 360, 257], ["C", 350, 110, 460, 102, 595, 120],
                      ["C", 593, 243, 500, 302, 360, 257], ["Z"]], "399878"),
        path("leaf-vein", [["M", 366, 253], ["C", 420, 204, 493, 157, 581, 128]],
             None, line="FFFFFF", line_width_pt=2),
        compile_component({"id": "ring", "recipe": "annular_sector", "bbox": [705, 117, 160, 160],
                           "params": {"inner_ratio": .57, "start_deg": 0, "sweep_deg": 360},
                           "style": {"fill": "6079C7", "line": None}}),
        compile_component({"id": "arrow", "recipe": "double_arrow", "bbox": [70, 353, 245, 93],
                           "params": {"head_fraction": .19, "shaft_fraction": .34},
                           "style": {"fill": "23888B", "line": None}}),
        path("s-curve", [["M", 378, 443], ["C", 385, 328, 515, 460, 577, 344]],
             None, line="CB6382", line_width_pt=4, line_cap="round", end_arrow="triangle"),
        path("notch", [["M", 685, 346], ["L", 848, 346], ["L", 890, 388],
                       ["L", 890, 460], ["L", 685, 460], ["Z"]], "D8A52C")]
    for i, box in enumerate([[55, 102, 235, 176], [343, 96, 264, 202], [699, 111, 172, 172],
                             [60, 343, 265, 113], [361, 320, 236, 145], [678, 338, 220, 130]]):
        _region(regions, f"vector-{i}", *box, margin=3)
    cases.append((slide, regions, "training"))

    slide, regions = _case("linear-gradients", "03  Native linear gradients")
    for i, (colors, angle) in enumerate([
            (["F4D36C", "E26971"], 0), (["72CFB3", "12666D"], 90),
            (["3E65C0", "9BCBE6", "F3E6AF"], 30),
            (["45558D", "D39BB6", "F5E6D0"], 135)]):
        x, y = 60 + (i % 2)*460, 118 + (i // 2)*205
        obj = shape(f"linear-{i}", [x, y, 380, 135], None,
                    adjustments=[.07], geometry="round_rect")
        obj["style"]["gradient"] = gradient(colors, angle)
        slide["objects"].append(obj)
        _region(regions, f"gradient-{i}", x, y, 380, 135)
    cases.append((slide, regions, "training"))

    slide, regions = _case("radial-gradients", "04  Radial light and transparency")
    for i, (box, colors, center) in enumerate([
            ([70, 133, 240, 240], ["D4F2EF", "177C88"], [.33, .28]),
            ([388, 158, 480, 180], ["FFF8DF", "D89432"], [.5, .5])]):
        obj = shape(f"radial-{i}", box, None, "ellipse")
        obj["style"]["gradient"] = gradient(colors, radial=True, center=center)
        slide["objects"].append(obj)
        _region(regions, f"radial-{i}", *box)
    base = shape("transparency-base", [390, 397, 478, 48], "5F78C5")
    overlay = shape("transparent", [430, 380, 180, 80], "FFFFFF", "round_rect", adjustments=[.1])
    overlay["style"]["fill_alpha"] = .35
    slide["objects"] += [base, overlay]
    _region(regions, "transparency", 378, 370, 503, 101)
    cases.append((slide, regions, "training"))

    slide, regions = _case("native-shadows", "05  Editable native shadows")
    for i, (color, parameters) in enumerate([
            ("FFFFFF", (6, 4, 7, .25)), ("EFBCD0", (0, 9, 9, .8)),
            ("B5E0CE", (10, 0, 3, .32))]):
        x, y, w, h = 60+i*305, 166, 222, 160
        obj = shape(f"shadow-{i}", [x, y, w, h], color,
                    "round_rect", adjustments=[.055])
        obj["style"]["native_format"] = shadow(*parameters)
        slide["objects"].append(obj)
        _region(regions, f"shadow-{i}", x-20, y-20, w+64, h+68, margin=2)
    slide["objects"].append(text("shadow-label", "Soft / sharp / diffuse", [280, 411, 440, 52], 23,
                                 align="center"))
    _region(regions, "shadow-label", 260, 399, 480, 72)
    cases.append((slide, regions, "training"))

    slide, regions = _case("editable-typography", "06  Editable type and mixed runs")
    slide["objects"] += [
        text("zh", "原生图形与可编辑文字", [60, 117, 824, 55], 26, bold=True),
        text("numeric", "39%   12.8 mg/L   2026", [60, 200, 820, 54], 29, color="23888B"),
        text("mixed", "", [60, 288, 750, 62], 30,
             font_east_asia="Microsoft YaHei"),
        text("body", "Quality first\nTime second", [60, 395, 425, 91], 22,
             line_spacing_pt=29),
        text("right", "ALIGN RIGHT", [524, 400, 360, 57], 21, align="right",
             color="CB6382", bold=True)]
    mixed = slide["objects"][3]
    mixed.pop("text")
    mixed["runs"] = [{"text": "H"}, {"text": "2", "baseline": "subscript", "font_size_pt": 21},
                     {"text": "O  +  x"}, {"text": "2", "baseline": "superscript", "font_size_pt": 21},
                     {"text": "   Bold", "bold": True}, {"text": " / regular"}]
    for name, box in [("cjk", [48, 106, 850, 73]), ("numbers", [48, 190, 850, 75]),
                       ("mixed", [48, 275, 850, 89]), ("body", [48, 386, 450, 111]),
                       ("right", [512, 390, 386, 78])]:
        _region(regions, name, *box, margin=2)
    cases.append((slide, regions, "training"))

    slide, regions = _case("overlap-alignment", "07  Alignment and object relationships")
    for i, (y, color, label) in enumerate([(125, "23888B", "Input"), (258, "6079C7", "Review"),
                                         (391, "CB6382", "Output")]):
        slide["objects"] += [shape(f"node-{i}", [74, y, 240, 77], color, "round_rect", adjustments=[.08]),
                             text(f"label-{i}", label, [74, y+16, 240, 47], 24, "FFFFFF", align="center")]
        if i < 2:
            slide["objects"].append(path(f"connector-{i}", [["M", 194, y+81], ["L", 194, y+124]],
                                         None, line="243341", line_width_pt=2, end_arrow="triangle"))
    slide["objects"] += [shape("overlap-a", [455, 148, 240, 240], "23888B", "ellipse"),
                         shape("overlap-b", [598, 207, 240, 240], "D8A52C", "ellipse")]
    slide["objects"][-1]["style"]["fill_alpha"] = .72
    _region(regions, "flow", 59, 112, 272, 368)
    _region(regions, "overlap", 443, 135, 409, 326)
    cases.append((slide, regions, "training"))

    for n, split in [(0, "training"), (1, "holdout"), (2, "holdout")]:
        name = "mixed-composition" if n == 0 else f"unseen-composition-{'a' if n == 1 else 'b'}"
        slide, regions = _case(name, ["08  Native process summary", "09  Material screening", "10  Sample validation"][n])
        colors = [("23888B", "6079C7", "CB6382"), ("4576B8", "3D997D", "B65B7F"),
                  ("398798", "A86A38", "6D7DAE")][n]
        labels = [["Collect", "Compare", "Confirm"], ["Sample", "Inspect", "Record"],
                  ["Prepare", "Measure", "Archive"]][n]
        amounts = [["24", "87%", "6.2"], ["37", "92%", "4.8"], ["18", "76%", "8.4"]][n]
        for i in range(3):
            x = 56 + i*307
            card = shape(f"panel-{i}", [x, 142, 238, 315], "FFFFFF", "round_rect",
                         adjustments=[.035+n*.012])
            card["style"].update({"line": "D8DFE7", "line_width_pt": .75,
                                  "native_format": shadow(4, 2, 3, .16)})
            badge = shape(f"badge-{i}", [x+71, 170+n*4, 96, 96], None, "ellipse")
            badge["style"]["gradient"] = gradient(["EAF5EF", colors[i]], radial=True,
                                                  center=[.36, .28])
            slide["objects"] += [card, badge,
                text(f"name-{i}", labels[i], [x+10, 294, 218, 44], 22, align="center", bold=True),
                text(f"value-{i}", amounts[i], [x+10, 367, 218, 62], 34, colors[i], align="center")]
            if i < 2:
                slide["objects"].append(path(f"bridge-{i}", [["M", x+246, 311], ["L", x+289, 311]],
                                             None, line="818C96", line_width_pt=2, end_arrow="triangle"))
            _region(regions, f"panel-{i}", x-8, 130, 263, 345, margin=1)
        for i in range(2):
            _region(regions, f"bridge-{i}", 298+i*307, 296, 55, 30, margin=1)
        cases.append((slide, regions, split))
    return cases


def make_holdout_cases():
    slide, regions = _case("unseen-composition-a", "09  Membrane screening")
    outer = shape("frame", [58, 133, 410, 330], "FFFFFF", "round_rect", adjustments=[.03])
    outer["style"].update(line="D8DFE7", line_width_pt=.75, native_format=shadow(4, 2, 4, .22))
    bar = shape("gradient", [91, 171, 343, 83], None, "round_rect", adjustments=[.095])
    bar["style"]["gradient"] = gradient(["CDF1E0", "308B86"], 20)
    slide["objects"] += [outer, bar,
        text("sample", "Sample A7", [91, 288, 343, 50], 25, bold=True),
        text("count", "42 samples", [91, 365, 343, 55], 28, "308B86"),
        compile_component({"id": "sector", "recipe": "annular_sector",
                           "bbox": [598, 135, 220, 220],
                           "params": {"inner_ratio": .64, "start_deg": 25, "sweep_deg": 285},
                           "style": {"fill": "BE6686", "line": None}}),
        path("transfer", [["M", 490, 295], ["C", 530, 295, 534, 242, 575, 242]],
             None, line="5669AF", line_width_pt=3, end_arrow="triangle"),
        text("review", "Review 73%", [561, 410, 305, 54], 26, "5669AF", align="center")]
    for name, box in [("frame", [45, 120, 446, 370]), ("sector", [588, 125, 240, 240]),
                       ("transfer", [481, 225, 103, 83]), ("review", [548, 400, 332, 78])]:
        _region(regions, name, *box, margin=1)
    first = (slide, regions, "holdout")
    slide, regions = _case("unseen-composition-b", "10  Native validation board")
    for i, (label, color) in enumerate([("Mix 16", "337F92"), ("Dry 28", "A85B7F")]):
        y = 135+i*168
        node = shape(f"node-{i}", [66, y, 280, 110], color, "round_rect", adjustments=[.11])
        slide["objects"] += [node, text(f"node-label-{i}", label, [80, y+33, 252, 47],
                                        25, "FFFFFF", align="center")]
        _region(regions, f"node-{i}", 56, y-10, 300, 130)
    slide["objects"] += [
        path("stem", [["M", 206, 253], ["L", 206, 293]], None, line="243341",
             line_width_pt=2.5, end_arrow="triangle"),
        path("panel", [["M", 459, 142], ["L", 816, 142], ["L", 881, 207],
                       ["L", 881, 434], ["L", 459, 434], ["Z"]], "D3E7F1"),
        shape("disc", [516, 186, 116, 116], "FFFFFF", "ellipse"),
        path("tick", [["M", 544, 244], ["L", 565, 264], ["L", 604, 219]], None,
             line="337F92", line_width_pt=5, line_cap="round", line_join="round"),
        text("ready", "READY", [656, 221, 188, 54], 27, "243341", bold=True),
        text("batch", "Batch 42 / 8.4", [494, 356, 349, 53], 25, "A85B7F", align="center")]
    for name, box in [("stem", [194, 244, 28, 58]), ("panel", [448, 132, 445, 315])]:
        _region(regions, name, *box, margin=1)
    return [first, (slide, regions, "holdout")]


def create(outdir: Path, holdout=False):
    outdir.mkdir(parents=True, exist_ok=False)
    private = outdir / "private"
    private.mkdir()
    cases = make_holdout_cases() if holdout else make_cases()
    scene = {"version": "1.0", "canvas": CANVAS,
             "slides": [c[0] for c in cases]}
    write_json(private / "references.scene.json", scene)
    build(private / "references.scene.json", private / "references.pptx")
    rubric = {"version": "native-practice/1", "canvas": CANVAS, "cases": [
        {"index": i+1, "id": slide["id"], "split": split, "regions": regions}
        for i, (slide, regions, split) in enumerate(cases)]}
    write_json(private / "rubric.json", rubric)
    write_json(outdir / "manifest.json", {"rubric_sha256": sha256(private / "rubric.json"),
               "scene_sha256": sha256(private / "references.scene.json"),
               "pptx_sha256": sha256(private / "references.pptx"),
               "scope": "Synthetic native constructions; reference Office exports still required"})
    return rubric


def _edges(a):
    a = a.astype(np.int16)
    edge = np.zeros(a.shape[:2], dtype=bool)
    edge[:, 1:] |= np.max(np.abs(a[:, 1:] - a[:, :-1]), axis=2) > 24
    edge[1:, :] |= np.max(np.abs(a[1:, :] - a[:-1, :]), axis=2) > 24
    return edge


def _dilate(mask):
    padded = np.pad(mask, 1)
    h, w = mask.shape
    return np.logical_or.reduce([padded[y:y+h, x:x+w] for y in range(3) for x in range(3)])


def region_score(a, b, background):
    if a.shape != b.shape or a.ndim != 3 or a.shape[2] != 3 or not a.size:
        raise ValueError("Matching nonempty RGB arrays required")
    af, bf = a.astype(np.float32), b.astype(np.float32)
    active = (np.max(np.abs(af-background), axis=2) > 8) | (
        np.max(np.abs(bf-background), axis=2) > 8)
    color = 1 - float(np.abs(af-bf)[active].mean())/255 if active.any() else 1.0
    ea, eb = _edges(a), _edges(b)
    if not ea.any() and not eb.any():
        edge = 1.0
    elif not ea.any() or not eb.any():
        edge = 0.0
    else:
        recall = np.count_nonzero(ea & _dilate(eb))/np.count_nonzero(ea)
        precision = np.count_nonzero(eb & _dilate(ea))/np.count_nonzero(eb)
        edge = 2*precision*recall/(precision+recall) if precision+recall else 0
    return {"score": float(.65*color+.35*edge), "foreground_color_agreement": color,
            "edge_f1_at_1px": float(edge), "foreground_pixels": int(active.sum())}


def image_score(reference: Path, candidate: Path, regions):
    with Image.open(reference) as ref, Image.open(candidate) as cand:
        a = np.asarray(ref.convert("RGB"))
        b = np.asarray(cand.convert("RGB"))
    if a.shape != b.shape:
        raise ValueError(f"Image size mismatch: {a.shape} versus {b.shape}; no automatic resize")
    background = np.array([int(BACKGROUND[i:i+2], 16) for i in (0, 2, 4)], dtype=np.float32)
    rows, covered = [], np.zeros(a.shape[:2], dtype=bool)
    for region in regions:
        x1, y1, x2, y2 = region["bbox"]
        if not (0 <= x1 < x2 <= a.shape[1] and 0 <= y1 < y2 <= a.shape[0]):
            raise ValueError("Invalid reference region")
        rows.append({"id": region["id"], **region_score(a[y1:y2, x1:x2], b[y1:y2, x1:x2], background)})
        covered[y1:y2, x1:x2] = True
    if not rows:
        raise ValueError("At least one fixed reference region required")
    outside = (~covered) & (np.max(np.abs(a.astype(np.int16)-b.astype(np.int16)), axis=2) > 24)
    return {"score": sum(r["score"] for r in rows)/len(rows), "regions": rows,
            "outside_region_difference_pixels": int(outside.sum()),
            "full_rgb_agreement_diagnostic_only": 1-float(np.abs(a.astype(float)-b).mean())/255,
            "scope": "Numerical image diagnostics only; not visual acceptance"}


def text_values(objects):
    values = []
    for obj in walk_objects(objects):
        if obj["kind"] != "text":
            continue
        if "paragraphs" in obj:
            content = "\n".join("".join(r["text"] for r in p["runs"]) for p in obj["paragraphs"])
        elif "runs" in obj:
            content = "".join(r["text"] for r in obj["runs"])
        else:
            content = obj.get("text", "")
        if content.strip():
            values.append("".join(content.split()))
    return Counter(values)


def semantic_diagnostics(expected, actual):
    want, got = text_values(expected["objects"]), text_values(actual["objects"])
    leaves = list(walk_objects(actual["objects"]))
    raster_count = sum(o["kind"] == "image" for o in leaves)
    return {"exact_text_objects": want == got, "missing_text": list((want-got).elements()),
            "unexpected_text": list((got-want).elements()), "raster_objects": raster_count,
            "native_only_scene": raster_count == 0,
            "note": "Text split/merge differences need manual review; object IDs are not scored."}


def evaluate(suite: Path, scene_path: Path, render_dir: Path, output: Path,
             pptx: Path, expected_cases=None):
    if output.exists():
        raise FileExistsError(output)
    rubric = read_json(suite / "private/rubric.json")
    expected = read_json(suite / "private/references.scene.json")
    frozen = read_json(suite / "manifest.json")
    for key, relative in [("rubric_sha256", "private/rubric.json"),
                           ("scene_sha256", "private/references.scene.json"),
                           ("pptx_sha256", "private/references.pptx")]:
        if sha256(suite / relative) != frozen[key]:
            raise ValueError("Frozen reference inputs changed")
    actual = read_json(scene_path)
    ref_receipt = read_json(suite / "reference-office/office-render.json")
    out_receipt = read_json(render_dir / "office-render.json")
    if any(r.get("status") != "passed" or r.get("renderer") != "Microsoft PowerPoint"
           for r in (ref_receipt, out_receipt)):
        raise ValueError("Actual PowerPoint reference and candidate receipts required")
    build_receipt = read_json(pptx.with_suffix(".build.json"))
    if (build_receipt.get("scene_sha256") != sha256(scene_path)
            or build_receipt.get("pptx_sha256") != sha256(pptx)
            or out_receipt.get("pptx_sha256") != sha256(pptx)
            or ref_receipt.get("pptx_sha256") != frozen["pptx_sha256"]):
        raise ValueError("Scene, PPTX and Office evidence identity mismatch")
    import zipfile
    with zipfile.ZipFile(pptx) as archive:
        embedded_media = [n for n in archive.namelist() if n.startswith("ppt/media/")]
    if expected_cases is not None and Counter(expected_cases) != Counter(
            slide["id"] for slide in actual["slides"]):
        raise ValueError("Missing, duplicated or unexpected case IDs")
    rows = []
    by_id = {s["id"]: (s, c) for s, c in zip(expected["slides"], rubric["cases"])}
    if len({s["id"] for s in actual["slides"]}) != len(actual["slides"]):
        raise ValueError("Duplicate slide IDs")
    for idx, slide in enumerate(actual["slides"], 1):
        source, case = by_id[slide["id"]]
        ref = suite / "reference-office" / f"slide-{case['index']:03}.png"
        candidate = render_dir / f"slide-{idx:03}.png"
        for image, receipt, index in [(ref, ref_receipt, case["index"]), (candidate, out_receipt, idx)]:
            entry = next(s for s in receipt["slides"] if s["index"] == index)
            if sha256(image) != entry["sha256"]:
                raise ValueError("Office image hash does not match receipt")
        semantic = semantic_diagnostics(source, slide)
        score = image_score(ref, candidate, case["regions"])
        numeric_target_met = all(region["score"] >= .95 for region in score["regions"])
        rows.append({"id": slide["id"], **score, "semantics": semantic,
                     "numeric_target_met": numeric_target_met,
                     "status": "needs_independent_review" if numeric_target_met
                     and semantic["exact_text_objects"] and semantic["native_only_scene"]
                     and score["outside_region_difference_pixels"] <= 8 else "needs_changes"})
    result = {"version": "native-practice-evaluation/1", "cases": rows,
              "mean_score": sum(r["score"] for r in rows)/len(rows),
              "target": .95, "visual_acceptance": "not_automated",
              "save_reopen_and_edit": "not_checked",
              "embedded_media_count": len(embedded_media),
              "native_package_gate": not embedded_media,
              "scene_sha256": sha256(scene_path),
              "reference_rubric_sha256": sha256(suite / "private/rubric.json")}
    write_json(output, result)
    return result


def packet(case_ids, output: Path, guidance: Path | None = None):
    if output.exists():
        raise FileExistsError(output)
    known = {slide["id"] for slide, _, _ in make_cases()}
    if not case_ids or len(set(case_ids)) != len(case_ids) or set(case_ids)-known:
        raise ValueError("Supply distinct known case IDs")
    root = Path(__file__).resolve().parents[1]
    content = (root / "references/native-scene-contract.md").read_text(encoding="utf-8")
    content += "\n\nReconstruct all attached images in order, using these slide IDs:\n"
    content += json.dumps(case_ids) + "\n"
    if guidance:
        content += "\nAdditional generic authoring guidance:\n" + guidance.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return {"case_ids": case_ids, "prompt_sha256": sha256(output),
            "private_ground_truth_supplied": False}


def extract(response: Path, output: Path):
    from benchmark import parse_model_json
    if output.exists():
        raise FileExistsError(output)
    scene = parse_model_json(response.read_text(encoding="utf-8"))
    write_json(output, scene)
    return {"scene": str(output), "raw_response_sha256": sha256(response),
            "content_modified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create")
    p.add_argument("--outdir", type=Path, required=True)
    p.add_argument("--holdout", action="store_true")
    p = sub.add_parser("evaluate")
    p.add_argument("--suite", type=Path, required=True)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--render-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--pptx", type=Path, required=True)
    p.add_argument("--expected-case", action="append")
    p = sub.add_parser("packet")
    p.add_argument("--case", action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--guidance", type=Path)
    p = sub.add_parser("extract")
    p.add_argument("--response", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.command == "create":
        result = create(a.outdir, a.holdout)
    elif a.command == "evaluate":
        result = evaluate(a.suite, a.scene, a.render_dir, a.output, a.pptx, a.expected_case)
    elif a.command == "packet":
        result = packet(a.case, a.output, a.guidance)
    else:
        result = extract(a.response, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
