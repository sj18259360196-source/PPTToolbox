"""Dependency-free graphics schema and canonical input hashing."""
import copy
import hashlib
import json
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


