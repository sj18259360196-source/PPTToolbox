"""Typed DrawingML formatting shared by incremental edits and scene rebuilds."""
from __future__ import annotations
import math
from lxml import etree
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from native_capabilities import validate_format


def el(tag, **attrs):
    node = OxmlElement("a:"+tag)
    for key, value in attrs.items():
        node.set(key, str(value))
    return node


def remove(parent, names):
    for child in list(parent):
        if child.tag in {qn("a:"+n) for n in names}:
            parent.remove(child)


def fill(parent, spec):
    remove(parent, ["noFill", "solidFill", "gradFill", "pattFill", "blipFill", "grpFill"])
    mode = spec["mode"]
    if mode == "none":
        node = el("noFill")
    elif mode == "solid":
        node = el("solidFill")
        rgb = el("srgbClr", val=spec["color"])
        rgb.append(el("alpha", val=round(spec["alpha"]*100000)))
        node.append(rgb)
    else:
        node = el("gradFill", rotWithShape=int(spec["rotate_with_shape"]))
        stops = el("gsLst")
        for s in spec["stops"]:
            gs = el("gs", pos=round(s["position"]*100000))
            rgb = el("srgbClr", val=s["color"])
            rgb.append(el("alpha", val=round(s["alpha"]*100000)))
            gs.append(rgb)
            stops.append(gs)
        node.append(stops)
        node.append(el("lin", ang=round(spec["angle_deg"]*60000), scaled=1))
    # spPr and character properties have different prescribed child sequences.
    predecessors = {"xfrm", "prstGeom", "custGeom"} if etree.QName(parent).localname == "spPr" else {"ln"}
    index = 0
    for i, child in enumerate(parent):
        if etree.QName(child).localname in predecessors:
            index = i+1
    parent.insert(index, node)


def shadow(parent, spec):
    if parent.find(qn("a:effectDag")) is not None:
        raise ValueError("Unknown effectDag cannot be merged safely")
    effects = parent.find(qn("a:effectLst"))
    if effects is None:
        effects = el("effectLst")
        parent.insert_element_before(effects, "a:scene3d", "a:sp3d", "a:latin", "a:ea",
                                     "a:cs", "a:sym", "a:hlinkClick", "a:extLst")
    remove(effects, ["outerShdw"])
    if spec["enabled"]:
        dx, dy = spec["dx_pt"], spec["dy_pt"]
        sh = el("outerShdw", blurRad=round(spec["blur_pt"]*12700),
                dist=round(math.hypot(dx, dy)*12700),
                dir=round((math.degrees(math.atan2(dy, dx)) % 360)*60000),
                algn="ctr", rotWithShape=0)
        rgb = el("srgbClr", val=spec["color"])
        rgb.append(el("alpha", val=round(spec["alpha"]*100000)))
        sh.append(rgb)
        effects.append(sh)


def apply(shape, value):
    validate_format(value)
    sp = shape._element.spPr
    if "fill" in value:
        fill(sp, value["fill"])
    if "shadow" in value:
        shadow(sp, value["shadow"])
    if "three_d" in value:
        spec = value["three_d"]
        remove(sp, ["scene3d", "sp3d"])
        if spec["enabled"]:
            scene = el("scene3d")
            scene.append(el("camera", prst=spec["camera"]))
            scene.append(el("lightRig", rig=spec["lighting"], dir="t"))
            solid = el("sp3d", extrusionH=round(spec["depth_pt"]*12700),
                       prstMaterial=spec["material"])
            for side in ("bevelT", "bevelB"):
                solid.append(el(side, w=round(spec["bevel_width_pt"]*12700),
                                h=round(spec["bevel_height_pt"]*12700), prst=spec["bevel"]))
            color = el("extrusionClr")
            color.append(el("srgbClr", val=spec["color"]))
            solid.append(color)
            sp.insert_element_before(scene, "a:extLst")
            sp.insert_element_before(solid, "a:extLst")
    if set(value) & {"text_fill", "text_outline", "text_shadow", "warp"}:
        tf = shape.text_frame
        if "warp" in value:
            bp = tf._txBody.bodyPr
            remove(bp, ["prstTxWarp"])
            node = el("prstTxWarp", prst=value["warp"])
            node.append(el("avLst"))
            bp.insert_element_before(node, "a:noAutofit", "a:normAutofit", "a:spAutoFit",
                                     "a:scene3d", "a:sp3d", "a:flatTx", "a:extLst")
        for p in tf.paragraphs:
            for r in p.runs:
                rp = r._r.get_or_add_rPr()
                if "text_fill" in value:
                    fill(rp, value["text_fill"])
                if "text_shadow" in value:
                    shadow(rp, value["text_shadow"])
                if "text_outline" in value:
                    remove(rp, ["ln"])
                    spec = value["text_outline"]
                    ln = el("ln", w=round(spec.get("width_pt", 0)*12700))
                    if spec["enabled"]:
                        sf = el("solidFill")
                        sf.append(el("srgbClr", val=spec["color"]))
                        ln.append(sf)
                    else:
                        ln.append(el("noFill"))
                    rp.insert(0, ln)


def read(shape):
    """Read persisted native nodes; never return the requested scene values."""
    paths = ("./p:spPr/a:gradFill", "./p:spPr/a:ln/a:gradFill", "./p:spPr/a:solidFill", "./p:spPr/a:noFill",
             "./p:spPr/a:effectLst", "./p:spPr/a:scene3d",
             "./p:spPr/a:sp3d", "./p:txBody/a:bodyPr/a:prstTxWarp",
             "./p:txBody/a:p/a:r/a:rPr/a:gradFill", "./p:txBody/a:p/a:r/a:rPr/a:ln",
             "./p:txBody/a:p/a:r/a:rPr/a:solidFill", "./p:txBody/a:p/a:r/a:rPr/a:noFill",
             "./p:txBody/a:p/a:r/a:rPr/a:effectLst")
    def unpack(node):
        return {"tag": etree.QName(node).localname, "attributes": dict(node.attrib),
                "children": [unpack(c) for c in node]}
    return {path: [unpack(n) for n in shape._element.xpath(path)] for path in paths}


def effect_margin(value):
    """Predeclared conservative extent in pt; not inferred from difference pixels."""
    margin = 2.0
    for field in ("shadow", "text_shadow"):
        sh = value.get(field, {})
        if sh.get("enabled"):
            margin += 3*sh["blur_pt"] + max(abs(sh["dx_pt"]), abs(sh["dy_pt"]))
    td = value.get("three_d", {})
    if td.get("enabled"):
        # Oblique camera projection cannot be bounded by depth alone.
        if td["camera"] != "orthographicFront":
            raise ValueError("Oblique 3D camera is build-only; local scope needs reliable projection")
        margin += td["depth_pt"]+td["bevel_width_pt"]+td["bevel_height_pt"]
    return margin
