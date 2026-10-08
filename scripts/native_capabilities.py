"""Versioned native-operation manifest; no Office activation during discovery."""
from __future__ import annotations

import copy
import re


def obj(fields, required=()):
    return {"type": "object", "properties": fields, "required": list(required),
            "additionalProperties": False}


def number(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


COLOR = {"type": "string", "pattern": "^[0-9A-F]{6}$"}
RUN_STYLE=obj({"font":{"type":"string","minLength":1,"maxLength":100},
               "font_east_asia":{"type":"string","minLength":1,"maxLength":100},
               "font_size_pt":number(6,96),"bold":{"type":"boolean"},
               "color":COLOR,"char_spacing_pt":number(-5,20)})
PARA_STYLE=obj({"align":{"enum":["left","center","right"]},
                "space_before_pt":number(0,120),"space_after_pt":number(0,120),
                "line_spacing_pt":number(6,160)})
RUN_STYLE["minProperties"]=1
PARA_STYLE["minProperties"]=1
_range_fields={"op":{"const":"text.range"},"id":{"type":"string","minLength":1},
               "text_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},
               "index_unit":{"const":"unicode_codepoint_bmp"},"paragraph":{"type":"integer","minimum":0},
               "start":{"type":"integer","minimum":0},"end":{"type":"integer","minimum":1},
               "expected_fragment":{"type":"string","minLength":1}}
TEXT_RANGE={"oneOf":[obj({**_range_fields,"scope":{"const":scope},"style":style},
                         (*_range_fields,"scope","style"))
                     for scope,style in (("run",RUN_STYLE),("paragraph",PARA_STYLE))]}
STOP = obj({"position": number(0, 1), "color": COLOR, "alpha": number(0, 1)},
           ("position", "color", "alpha"))
FILL = {"oneOf": [
    obj({"mode": {"const": "none"}}, ("mode",)),
    obj({"mode": {"const": "solid"}, "color": COLOR, "alpha": number(0, 1)},
        ("mode", "color", "alpha")),
    obj({"mode": {"const": "linear"}, "angle_deg": number(0, 359.999),
         "rotate_with_shape": {"type": "boolean"},
         "stops": {"type": "array", "items": STOP, "minItems": 2, "maxItems": 5}},
        ("mode", "angle_deg", "rotate_with_shape", "stops"))
]}
SHADOW = {"oneOf": [
    obj({"enabled": {"const": False}}, ("enabled",)),
    obj({"enabled": {"const": True}, "color": COLOR, "alpha": number(0, 1),
         "blur_pt": number(0, 24), "dx_pt": number(-24, 24), "dy_pt": number(-24, 24)},
        ("enabled", "color", "alpha", "blur_pt", "dx_pt", "dy_pt"))
]}
OUTLINE = {"oneOf": [
    obj({"enabled": {"const": False}}, ("enabled",)),
    obj({"enabled": {"const": True}, "color": COLOR, "width_pt": number(.1, 8)},
        ("enabled", "color", "width_pt"))
]}
WARP = {"enum": ["textNoShape", "textArchUp", "textArchDown"]}
THREE_D = {"oneOf": [
    obj({"enabled": {"const": False}}, ("enabled",)),
    obj({"enabled": {"const": True}, "depth_pt": number(0, 36), "color": COLOR,
         "bevel": {"enum": ["circle", "relaxedInset"]},
         "bevel_width_pt": number(0, 12), "bevel_height_pt": number(0, 12),
         "material": {"enum": ["matte", "plastic", "metal"]},
         "camera": {"enum": ["orthographicFront", "isometricTopUp"]},
         "lighting": {"enum": ["threePt", "balanced"]}},
        ("enabled", "depth_pt", "color", "bevel", "bevel_width_pt",
         "bevel_height_pt", "material", "camera", "lighting"))
]}
FIELDS = {"fill": FILL, "shadow": SHADOW, "text_fill": FILL, "text_shadow": SHADOW,
          "text_outline": OUTLINE, "warp": WARP, "three_d": THREE_D}
FORMAT = obj({"version": {"const": "1"}, **FIELDS}, ("version",))
FORMAT["minProperties"] = 2
TOPOLOGY = obj({
    "op": {"const": "native.topology"},
    "action": {"enum": ["group", "ungroup", "move_group", "union", "combine", "intersect", "subtract", "fragment"]},
    "inputs": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 180},
               "minItems": 1, "maxItems": 8, "uniqueItems": True},
    "primary": {"type": "string", "minLength": 1, "maxLength": 180},
    "style_source": {"type": "string", "minLength": 1, "maxLength": 180},
    "output_prefix": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_-]{0,47}$"},
    "empty": {"enum": ["reject", "allow"]},
    "delta": {"type": "array", "items": number(-1000, 1000), "minItems": 2, "maxItems": 2},
}, ("op", "action", "inputs", "primary", "style_source", "output_prefix", "empty"))
LEARN = "https://learn.microsoft.com/en-us/office/vba/api/"
SPECS = [
    ("shape.fill", "多色渐变与填充", "Linear gradient and fill", "A", "fill",
     ["三色渐变", "半透明色标", "渐变方向", "五色", "两色", "透明填充", "已有阴影时改填充"], ["shape"],
     "powerpoint.fillformat.gradientstops"),
    ("shape.shadow", "原生外阴影", "Native outer shadow", "A", "shadow",
     ["柔和投影", "悬浮卡片", "外阴影", "投影", "阴影"], ["shape"],
     "powerpoint.shadowformat"),
    ("text.fill", "文字自身渐变", "Text glyph fill", "B", "text_fill",
     ["文字本身渐变", "不是文本框底色", "渐变标题", "文字渐变"], ["text"], "office.font2.fill"),
    ("text.outline", "文字描边", "Text outline", "B", "text_outline",
     ["文字有阴影和描边", "描边", "空心字", "轮廓"], ["text"], "office.font2.line"),
    ("text.shadow", "文字投影", "Text shadow", "B", "text_shadow",
     ["文字有阴影和描边", "字的阴影", "文字投影"], ["text"], "office.font2.shadow"),
    ("text.warp", "可改字艺术字变形", "Editable text warp", "B", "warp",
     ["可改字的弧形标题", "艺术字变形", "弧形", "拱形"], ["text"], "powerpoint.textframe2.warpformat"),
    ("shape.three_d", "原生形状三维格式", "Native shape 3D", "C", "three_d",
     ["图形有厚度", "倒角", "材质", "光照", "立体标签"], ["shape"], "powerpoint.threedformat"),
]
MAP = [
    ("page.theme", "页面与主题", ["页面", "主题"], "powerpoint.presentation"),
    ("shape.path", "基础形状与自由路径", ["自由路径", "形状"], "powerpoint.shapes.buildfreeform"),
    ("shape.line", "线条", ["线条", "线宽"], "powerpoint.lineformat"),
    ("shape.other_effects", "发光柔化映像", ["发光", "柔化", "映像"], "powerpoint.glowformat"),
    ("shape.layout", "位置对齐分布层级", ["对齐", "分布", "层级"], "powerpoint.shaperange.align"),
    ("group.create", "原生分组", ["组合后整体移动", "分组", "组合", "保持子对象", "合成一组"], "powerpoint.shaperange.group"),
    ("group.ungroup", "取消组合", ["取消组合", "拆分"], "powerpoint.shape.ungroup"),
    ("boolean.union", "布尔合并", ["Union", "合并轮廓"], "powerpoint.shaperange.mergeshapes"),
    ("boolean.combine", "布尔组合", ["Combine", "组合", "异或", "挖空重叠"], "powerpoint.shaperange.mergeshapes"),
    ("boolean.intersect", "布尔相交", ["只保留重叠部分", "只留重叠区域", "保留交集", "相交", "Intersect"], "powerpoint.shaperange.mergeshapes"),
    ("boolean.subtract", "布尔剪除", ["从A中挖掉B", "剪除", "Subtract"], "powerpoint.shaperange.mergeshapes"),
    ("boolean.fragment", "交叠分区", ["按交叠区域拆成可单独改色的块", "按交叠拆成独立块", "拆分", "Fragment"], "powerpoint.shaperange.mergeshapes"),
    ("text.layout", "普通文字段落", ["只改一段文字", "段后间距", "字距", "行距", "内边距", "AutoSize", "WordWrap"], "powerpoint.textframe2"),
    ("font.mixed", "字体与混排", ["局部字重", "只改选中字", "字体", "混排", "样张"], "office.font2"),
    ("picture.crop", "图片裁切蒙版", ["图片", "裁切", "蒙版"], "powerpoint.pictureformat"),
    ("vector.convert", "SVG矢量转换", ["SVG", "矢量转换", "拆分"], "powerpoint.shapes"),
    ("table.native", "原生表格", ["表格", "单元格"], "powerpoint.table"),
    ("chart.native", "原生图表", ["图表", "数据"], "powerpoint.chart"),
    ("connector.native", "连接线", ["连接线", "关系"], "powerpoint.connectorformat"),
    ("animation.media", "动画切换媒体", ["动画", "切换", "媒体"], "powerpoint.timeline"),
]


def entries():
    result = []
    for cid, title, english, batch, field, aliases, kinds, source in SPECS:
        result.append({
            "capability_id": cid, "version": "1", "title": title, "english": english,
            "batch": batch, "field": field, "aliases": aliases, "objects": kinds,
            "parameters": copy.deepcopy(FIELDS[field]), "official_entry": LEARN+source,
            "entry": "rebuild_patch", "operation": "native.format",
            "implementation": "bounded_ooxml", "callable": True,
            "coverage": {k: "implemented_not_office_verified" for k in
                         ("create", "modify", "readback", "clear", "reopen", "scene_rebuild")},
            "recipe": "not_validated", "office": "not_run", "validation": "code_only",
            "exclusions": ["groups", "rotated objects", "rich text", "unknown effects",
                           "neighbor-overlapping effect envelopes"],
            "units": "pt; angles in degrees; alpha=opacity in0..1, transparency=1-alpha",
            "side_effects": "new trial copy; saved/reopened Office readback; original untouched",
            "order": "validate complete request, resolve stable names, patch copy, save/reopen, compare, observe, adopt",
            "return": "same stable names and object count; paired scene/PPTX; no automatic visual pass",
            "clear": "Explicit none/disabled/textNoShape; omitted fields preserve current values.",
            "readback": "trial/readback.json actual reopened COM; native-readback.json actual DrawingML and independent rebuilt copy",
            "common_errors": ["alpha is opacity, not transparency", "shape effects do not imply glyph effects",
                              "unknown or mixed effects are rejected rather than deleted"],
            "minimal_example": {"op": "native.format", "id": "slide-001.body.target",
                                "format": {"version": "1", field: example(field)}},
        })
    for cid, title, aliases, source in MAP:
        result.append({"capability_id": cid, "version": "1", "title": title, "aliases": aliases,
                       "official_entry": LEARN+source, "callable": False,
                       "implementation": "existing_helpers_or_unimplemented",
                       "coverage": {k: "unknown" for k in
                                    ("create", "modify", "readback", "clear", "reopen", "scene_rebuild")},
                       "recipe": "not_validated", "office": "not_run",
                       "validation": "discovery_only",
                       "distinction": "Group preserves children; Fragment creates geometric pieces; neither is vector/text conversion."})
        if cid.startswith("boolean.") or cid in {"group.create","group.ungroup"}:
            action=cid.split(".")[-1] if cid.startswith("boolean.") else ("group" if cid=="group.create" else "ungroup")
            names=["slide-001.body.a","slide-001.body.b"] if action!="ungroup" else ["slide-001.body.existing-group"]
            result[-1].update(callable=True,implementation="bounded_Office_topology",entry="rebuild_patch",
                operation="native.topology",parameters=copy.deepcopy(TOPOLOGY),validation="code_only",
                coverage={k:"implemented_not_office_verified" for k in ("create","modify","readback","reopen","scene_rebuild")},
                exclusions=["rotated/scaled/nested groups","interleaved unselected z-order","animation/connectors",
                            "text Boolean operands","non-solid Boolean styles"],
                side_effects="Consumes/reparents authorized inputs; actual count/IDs read after Office operation; no automatic adoption",
                units="delta in PowerPoint pt; stored path coordinates in existing scene units",
                empty="Default reject; explicit allow needed to publish zero-geometry consumption",
                minimal_example={"op":"native.topology","action":action,"inputs":names,"primary":names[0],
                                 "style_source":names[0],"output_prefix":"derived","empty":"reject"})
        if cid in {"text.layout","font.mixed"}:
            import hashlib
            result[-1].update(callable=True,implementation="bounded_text_range",entry="rebuild_patch",
                operation="text.range",parameters=copy.deepcopy(TEXT_RANGE),validation="code_only",
                exclusions=["non-BMP characters","fields","soft breaks","empty selections","advanced glyph effects",
                            "text replacement","nested or rotated text"],
                units="Zero-based BMP Unicode code points; paragraph-local half-open range; pt spacing",
                side_effects="Selected native styles only; reflow may affect target box; neighbor protection remains",
                minimal_example={"op":"text.range","id":"slide-001.body.target",
                    "text_sha256":hashlib.sha256(b"Alpha").hexdigest(),"index_unit":"unicode_codepoint_bmp",
                    "paragraph":0,"start":0,"end":5,"expected_fragment":"Alpha",
                    "scope":"run","style":{"bold":True}})
    for name, title, aliases in [
        ("native_folded_banner", "折角渐变条幅", ["两端折回去的横幅", "折角条幅"]),
        ("native_overlap_regions", "可分别改色的交叠分区图", ["交叠分区图", "分块改色"]),
        ("native_effect_title", "可改字的渐变描边投影标题", ["渐变描边投影标题"]),
        ("native_arch_title", "可改字的弧形标题", ["弧形标题配方"]),
        ("native_depth_label", "可调厚度倒角材质的立体标签", ["立体标签配方"])]:
        result.append({"capability_id": "recipe."+name, "version": "1", "title": title,
                       "aliases": aliases, "callable": True, "entry": "rebuild_probe",
                       "operation": "components", "recipe": name,
                       "validation": "code_only", "office": "not_run",
                       "implementation": "existing_component_compiler",
                       "minimal_example": {"id": "sample", "recipe": name, "bbox": [20, 20, 600, 180]},
                       "exclusions": ["not an activated learned skill", "no arbitrary nested script",
                                      "grouped components are creation-only here"]})
    return result


def example(field):
    gradient = {"mode": "linear", "angle_deg": 0, "rotate_with_shape": True,
                "stops": [{"position": 0, "color": "26765C", "alpha": 1},
                          {"position": 1, "color": "A9DCD3", "alpha": .7}]}
    if field in {"fill", "text_fill"}:
        return gradient
    if field in {"shadow", "text_shadow"}:
        return {"enabled": True, "color": "203344", "alpha": .4, "blur_pt": 4, "dx_pt": 3, "dy_pt": 5}
    if field == "text_outline":
        return {"enabled": True, "color": "173E50", "width_pt": .5}
    if field == "warp":
        return "textArchUp"
    return {"enabled": True, "depth_pt": 12, "color": "26765C", "bevel": "circle",
            "bevel_width_pt": 3, "bevel_height_pt": 3, "material": "matte",
            "camera": "orthographicFront", "lighting": "threePt"}


def search(query, limit=5):
    q = query.casefold().strip()
    if not q:
        return []
    scored = []
    for row in entries():
        terms = [row["capability_id"], row["title"], *row["aliases"]]
        score = sum(4+len(t) for t in terms if t.casefold() in q)
        score += sum(1 for t in terms if q in t.casefold())
        if score:
            scored.append((score, row))
    scored.sort(key=lambda v: (-v[0], v[1]["capability_id"]))
    return [dict(r, score=s) for s, r in scored[:limit]]


def card(cid):
    row = next((r for r in entries() if r["capability_id"] == cid), None)
    if not row:
        raise ValueError("Unknown capability_id")
    return row


def validate_format(value, kind=None):
    from jsonschema import Draft202012Validator
    Draft202012Validator(FORMAT).validate(value)
    if kind and kind not in {"text", "shape"}:
        raise ValueError("Native format requires independent text or shape")
    if kind == "shape" and set(value) & {"text_fill", "text_outline", "text_shadow", "warp"}:
        raise ValueError("Glyph effects require text, not shape fill")
    if kind == "text" and set(value) & {"three_d", "shadow", "fill"}:
        raise ValueError("Text uses explicit glyph effects; shape effects not allowed here")
    for field in ("fill", "text_fill"):
        f = value.get(field, {})
        if f.get("mode") == "linear":
            positions = [s["position"] for s in f["stops"]]
            if positions != sorted(set(positions)) or positions[0] != 0 or positions[-1] != 1:
                raise ValueError("Stops must be strictly ordered with endpoints0 and1")
