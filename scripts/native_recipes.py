"""Finite parameterized components using registered native format capabilities."""
from __future__ import annotations
import re
from native_capabilities import card, validate_format

REFERENCES = {
    "native_folded_banner": ["shape.fill"],
    "native_overlap_regions": ["boolean.fragment"],
    "native_effect_title": ["text.fill", "text.outline", "text.shadow"],
    "native_arch_title": ["text.fill", "text.warp"],
    "native_depth_label": ["shape.three_d"],
}


def compile_native_recipe(name, oid, box, p, evidence):
    from components import boolean_component, number
    for cid in REFERENCES[name]:
        card(cid)
    x, y, w, h = box
    def base(suffix, kind):
        return {"id": oid+suffix, "kind": kind, "editability": kind if kind != "text" else "text",
                "evidence": evidence}
    def text(value, native=None):
        if not isinstance(value, str) or not 1 <= len(value) <= 80 or any(c in value for c in "\n\r\v"):
            raise ValueError("Title requires1..80 single-line characters")
        style = {"font": "Arial", "font_east_asia": "Microsoft YaHei",
                 "font_size_pt": number(p.get("font_size_pt", 28), "font_size_pt", 8, 72),
                 "color": "173E50", "align": "center", "valign": "middle", "margin_pt": 0}
        if native:
            validate_format(native, "text")
            style["native_format"] = native
        return {**base("_text", "text"), "bbox": [x+.12*w, y+.1*h, .76*w, .8*h],
                "text": value, "style": style}
    if "color_start" in p:
        for key in ("color_start", "color_end"):
            if not re.fullmatch("[0-9A-F]{6}", p[key]):
                raise ValueError("Expected uppercase RGB")
        gradient = {"mode": "linear", "angle_deg": 0, "rotate_with_shape": True,
                    "stops": [{"position": 0, "color": p["color_start"], "alpha": 1},
                              {"position": 1, "color": p["color_end"], "alpha": 1}]}
    if name in {"native_effect_title", "native_arch_title"}:
        native = {"version": "1", "text_fill": gradient}
        if name == "native_effect_title":
            native.update(text_outline={"enabled": True, "color": "173E50", "width_pt": .5},
                          text_shadow={"enabled": True, "color": "203344", "alpha": .4,
                                       "blur_pt": 3, "dx_pt": 2, "dy_pt": 3})
        else:
            if p["warp"] not in {"textArchUp", "textArchDown"}:
                raise ValueError("Only two explicitly registered warp presets")
            native["warp"] = p["warp"]
        result = text(p["text"], native)
        result["id"] = oid
        return result
    if name == "native_depth_label":
        native = {"version": "1", "three_d": {"enabled": True,
                  "depth_pt": number(p["depth_pt"], "depth_pt", 0, 36),
                  "color": "3A9981", "bevel": "circle",
                  "bevel_width_pt": number(p["bevel_pt"], "bevel_pt", 0, 12),
                  "bevel_height_pt": p["bevel_pt"], "material": p["material"],
                  "camera": "orthographicFront", "lighting": "threePt"}}
        validate_format(native, "shape")
        shape = {**base("_shape", "shape"), "geometry": "round_rect", "bbox": box,
                 "style": {"fill": "80C2B1", "line": "26765C", "native_format": native}}
        return {**base("", "group"), "children": [shape, text(p["text"])]}
    if name == "native_overlap_regions":
        result = boolean_component({"id": oid, "operation": "fragment", "operands": [
            {"geometry": "rect", "bbox": [x, y, .65*w, h]},
            {"geometry": "rect", "bbox": [x+.35*w, y+.2*h, .65*w, .8*h]}]})
        from common import walk_objects
        paths = [o for o in walk_objects([result]) if o["kind"] == "path"]
        for child, color in zip(paths, [p["color_a"], p["color_overlap"], p["color_b"]]):
            if not re.fullmatch("[0-9A-F]{6}", color):
                raise ValueError("Expected uppercase RGB")
            child["style"] = {"fill": color, "line": "FFFFFF", "line_width_pt": .8}
        return result
    if name == "native_folded_banner":
        front = {**base("_front", "shape"), "geometry": "rect",
                 "bbox": [x+.1*w, y, .8*w, .72*h],
                 "style": {"line": None, "native_format": {"version": "1", "fill": gradient}}}
        tails = []
        for suffix, points in (
            ("_left", [[x,y+.2*h],[x+.16*w,y+.2*h],[x+.16*w,y+h],[x,y+h],[x+.04*w,y+.6*h]]),
            ("_right", [[x+.84*w,y+.2*h],[x+w,y+.2*h],[x+.96*w,y+.6*h],[x+w,y+h],[x+.84*w,y+h]])):
            tails.append({**base(suffix,"path"), "closed": True,
                          "commands": [["M",*points[0]], *[["L",*v] for v in points[1:]], ["Z"]],
                          "style": {"fill": p["color_start"], "line": None}})
        label = text(p["text"])
        label["bbox"] = [x+.15*w,y+.08*h,.7*w,.55*h]
        dark = "".join(f"{round(int(p['color_start'][i:i+2],16)*.6):02X}" for i in (0,2,4))
        folds = []
        for suffix, points in (
            ("_fold_left", [[x+.1*w,y+.72*h],[x+.16*w,y+.72*h],[x+.16*w,y+h]]),
            ("_fold_right", [[x+.84*w,y+.72*h],[x+.9*w,y+.72*h],[x+.84*w,y+h]])):
            folds.append({**base(suffix,"path"), "closed": True,
                          "commands": [["M",*points[0]], *[["L",*v] for v in points[1:]], ["Z"]],
                          "style": {"fill": dark, "line": None}})
        return {**base("", "group"), "children": [*tails,*folds,front,label]}
    raise ValueError("Unregistered recipe")
