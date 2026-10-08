"""Finite declarative native-fragment capture and compilation; never executes data."""
import copy
import hashlib
import json
import math
import re

PATHS = {"text", "style.color", "style.fill", "style.font_size_pt"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def number(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Finite number required")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", value):
        raise ValueError("Invalid local identifier")
    return value


def value_check(spec, value):
    if spec["type"] == "number":
        if not spec["minimum"] <= number(value) <= spec["maximum"]:
            raise ValueError("Parameter outside proposed domain")
    elif spec["type"] == "color":
        if not isinstance(value, str) or not re.fullmatch("[0-9A-Fa-f]{6}", value):
            raise ValueError("Expected RGB hex color")
    elif spec["type"] == "text":
        if not isinstance(value, str) or not 1 <= len(value) <= spec["max_length"]:
            raise ValueError("Text outside declared length")
        if any(ord(c) < 32 and c != "\n" for c in value):
            raise ValueError("Control characters are not text")
    else:
        raise ValueError("Unsupported parameter type")


def expression(expr, parameters, supplied=None):
    """A constant or one typed parameter with optional affine coefficients."""
    if not isinstance(expr, dict):
        if isinstance(expr, str):
            return expr
        return number(expr)
    if set(expr) - {"param", "scale", "offset"} or "param" not in expr:
        raise ValueError("Only parameter references and affine transforms allowed")
    name = expr["param"]
    if name not in parameters:
        raise ValueError("Unknown parameter reference")
    spec = parameters[name]
    val = (supplied or {}).get(name, spec["example"])
    if "scale" in expr or "offset" in expr:
        if spec["type"] != "number":
            raise ValueError("Affine expression requires numeric parameter")
        val = number(val)*number(expr.get("scale", 1))+number(expr.get("offset", 0))
        number(val)
    return val


def compile_recipe(recipe, values, placement):
    if set(values) != set(recipe["parameters"]):
        raise ValueError("All and only declared parameters must be supplied")
    for name, spec in recipe["parameters"].items():
        value_check(spec, values[name])
    if len(placement) != 4:
        raise ValueError("Placement requires x/y/width/height")
    x, y, width, height = [number(v) for v in placement]
    if min(width, height) <= 0:
        raise ValueError("Positive placement required")
    if not (recipe["placement_domain"][0] <= width <= recipe["placement_domain"][1] and
            recipe["placement_domain"][2] <= height <= recipe["placement_domain"][3]):
        raise ValueError("Placement outside proposed domain")
    objects = copy.deepcopy(recipe["objects"])
    by_id = {o["id"]: o for o in objects}
    for binding in recipe["bindings"]:
        oid, path = binding["object"], binding["field"]
        value = expression(binding["value"], recipe["parameters"], values)
        obj = by_id[oid]
        if path == "text":
            if not isinstance(value, str):
                raise ValueError("Text binding must produce text")
            obj["text"] = value
        elif path.startswith("style."):
            field = path.split(".")[1]
            if field == "font_size_pt":
                if not 6 <= number(value) <= 96:
                    raise ValueError("Font outside supported range")
            elif not isinstance(value, str) or not re.fullmatch("[0-9A-Fa-f]{6}", value):
                raise ValueError("Invalid color binding")
            obj.setdefault("style", {})[field] = value
    for obj in objects:
        if obj["kind"]=="path":
            if recipe["format"]!="native-recipe/2":
                raise ValueError("Paths require recipe version2")
            obj["commands"]=[[cmd[0],*[value*([width,height][i%2])+([x,y][i%2])
                                      for i,value in enumerate(cmd[1:])]] for cmd in obj["commands"]]
            continue
        a, b, w, h = obj["bbox"]
        obj["bbox"] = [x+a*width, y+b*height, w*width, h*height]
        if min(w, h) <= 0:
            raise ValueError("Empty native object")
    return {"objects": objects, "source_notes": "Declarative learned fragment; layout assumptions require current-task review"}


def capture(objects, object_ids, parameters, bindings, domain, assumptions):
    if not 3 <= len(object_ids) <= 12 or len(set(object_ids)) != len(object_ids):
        raise ValueError("Select three to twelve distinct native objects")
    def leaves(rows):
        for o in rows:
            if o["kind"]=="group":yield from leaves(o["children"])
            else:yield o
    selected = [copy.deepcopy(o) for o in leaves(objects) if o["id"] in object_ids]
    if len(selected) != len(object_ids):
        raise ValueError("Source object missing")
    for o in selected:
        if o["kind"] not in {"text", "shape","path"} or o.get("rotation", 0) or o.get("rotation_deg",0) or "runs" in o or "paragraphs" in o:
            raise ValueError("Only unrotated native text/simple shapes supported")
        if o["kind"] == "shape" and o.get("geometry") not in {"rect", "round_rect", "ellipse"}:
            raise ValueError("Unsupported shape geometry")
        if o["kind"]=="path":
            cs=o["commands"]
            if not o.get("closed") or len(cs)>64 or cs[0][0]!="M" or cs[-1]!=["Z"] or any(
                    c[0] not in {"M","L","Z"} or len(c)!=(1 if c[0]=="Z" else 3) for c in cs):
                raise ValueError("Recipe2 supports bounded closed straight paths only")
            if "native_path_frame" in o:raise ValueError("Office-derived paths need separate scoped recipe coverage")
        if o.get("style",{}).get("native_format"):
            from native_capabilities import validate_format
            validate_format(o["style"]["native_format"],o["kind"])
    if not 1 <= len(parameters) <= 20 or len(bindings) > 40:
        raise ValueError("Bounded parameter set required")
    for name, spec in parameters.items():
        identifier(name)
        allowed = {"type", "example", "minimum", "maximum"} if spec.get("type") == "number" else (
            {"type", "example", "max_length"} if spec.get("type") == "text" else {"type", "example"})
        if set(spec) != allowed:
            raise ValueError("Parameter schema has unknown or missing fields")
        if spec["type"] == "number":
            if number(spec["minimum"]) > number(spec["maximum"]):
                raise ValueError("Invalid numeric domain")
        if spec["type"] == "text" and (type(spec["max_length"]) is not int or not 1 <= spec["max_length"] <= 500):
            raise ValueError("Invalid text length")
        value_check(spec, spec["example"])
    if len(domain) != 4 or any(number(v) <= 0 for v in domain) or domain[0] > domain[1] or domain[2] > domain[3]:
        raise ValueError("Invalid placement domain")
    mapping = {o["id"]: "part-"+str(i+1) for i, o in enumerate(selected)}
    def bounds(o):
        if o["kind"]!="path":return o["bbox"]
        pts=[c[1:] for c in o["commands"] if len(c)==3]
        x=min(p[0] for p in pts);y=min(p[1] for p in pts)
        return [x,y,max(p[0] for p in pts)-x,max(p[1] for p in pts)-y]
    boxes=[bounds(o) for o in selected]
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    w = max(b[0]+b[2] for b in boxes)-x
    h = max(b[1]+b[3] for b in boxes)-y
    if w <= 0 or h <= 0:
        raise ValueError("Invalid source geometry")
    for o in selected:
        o["id"] = mapping[o["id"]]
        if o["kind"]=="path":
            o["commands"]=[[c[0],(number(c[1])-x)/w,(number(c[2])-y)/h] if len(c)==3 else c
                           for c in o["commands"]]
        else:
            a, b, ow, oh = o["bbox"]
            o["bbox"] = [(a-x)/w, (b-y)/h, ow/w, oh/h]
        o.pop("evidence", None)
        o.pop("editability", None)
    seen = set()
    for b in bindings:
        if set(b) != {"object", "field", "value"} or b["object"] not in mapping.values() or b["field"] not in PATHS:
            raise ValueError("Binding outside native whitelist")
        key = (b["object"], b["field"])
        if key in seen:
            raise ValueError("Duplicate binding")
        seen.add(key)
        target = next(o for o in selected if o["id"] == b["object"])
        if b["field"] in {"text", "style.font_size_pt", "style.color"} and target["kind"] != "text":
            raise ValueError("Text field on non-text object")
        if b["field"] == "style.fill" and (target["kind"] not in {"shape","path"} or
                target.get("style",{}).get("native_format",{}).get("fill")):
            raise ValueError("Fill binding on non-shape object")
        expression(b["value"], parameters)
    for o in selected:
        if o["kind"] == "text" and (o["id"], "text") not in seen:
            raise ValueError("Every source text must be bound to current-task content")
        if o["kind"] == "text":
            o["text"] = "EXAMPLE"
    advanced=any(o["kind"]=="path" or o.get("style",{}).get("native_format") for o in selected)
    recipe = {"format": "native-recipe/2" if advanced else "native-recipe/1", "objects": selected, "source_mapping": mapping,
              "source_frame": [x, y, w, h], "parameters": parameters, "bindings": bindings,
              "placement_domain": domain, "layout_assumptions": assumptions,
              "geometry": "normalized source frame; fonts/insets/line widths remain pt",
              "edit_depth": "independent native objects; source grouping is not retained"}
    compile_recipe(recipe, {k: v["example"] for k, v in parameters.items()}, [0, 0, domain[0], domain[2]])
    return recipe
