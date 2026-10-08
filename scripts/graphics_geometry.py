"""Bounded editable cubic geometry; topology predicates use GEOS, not heuristics."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _vendor in ("icons", "graphics"):
    _path = str(ROOT / "toolbox_manager" / "vendor" / _vendor)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected finite numeric coordinate")
    if abs(value) > 1_000_000:
        raise ValueError("Coordinate exceeds geometry budget")
    return float(value)


def check_commands(commands, *, open_only=False):
    if not isinstance(commands, list) or not 2 <= len(commands) <= 512:
        raise ValueError("Path requires 2..512 commands")
    moves = 0
    closed = False
    for i, c in enumerate(commands):
        if not isinstance(c, list) or not c or c[0] not in {"M", "L", "C", "Z"}:
            raise ValueError("Only explicit M/L/C/Z commands are supported")
        if len(c) != {"M": 3, "L": 3, "C": 7, "Z": 1}[c[0]]:
            raise ValueError("Invalid path command arity")
        for v in c[1:]:
            finite(v)
        if i == 0 and c[0] != "M":
            raise ValueError("Path must begin with M")
        if c[0] == "M":
            moves += 1
            closed = False
        elif closed:
            raise ValueError("Closed subpath requires a new M")
        elif c[0] == "Z":
            closed = True
    if open_only and (moves != 1 or any(c[0] == "Z" for c in commands)):
        raise ValueError("Expected one open continuous edge")
    return commands


def as_path(commands):
    import svgelements as se
    check_commands(commands)
    return se.Path(" ".join(" ".join(str(v) for v in row) for row in commands))


def path_commands(path):
    import svgelements as se
    out = []
    for s in path:
        if isinstance(s, se.Move):
            out.append(["M", s.end.x, s.end.y])
        elif isinstance(s, se.Line):
            out.append(["L", s.end.x, s.end.y])
        elif isinstance(s, se.CubicBezier):
            out.append(["C", s.control1.x, s.control1.y, s.control2.x, s.control2.y, s.end.x, s.end.y])
        elif isinstance(s, se.Close):
            out.append(["Z"])
        else:
            raise ValueError("Unexpected curve type")
    return check_commands(out)


def transform(commands, matrix):
    import svgelements as se
    if len(matrix) != 6:
        raise ValueError("Affine matrix requires six coefficients")
    a, b, c, d, e, f = map(finite, matrix)
    det = a*d-b*c
    if abs(det) < 1e-10:
        raise ValueError("Singular affine transform")
    return path_commands(abs(as_path(commands) * se.Matrix(a, b, c, d, e, f)))


def reverse_edge(commands):
    check_commands(commands, open_only=True)
    p = as_path(commands)
    p.reverse()
    return path_commands(p)


def flatten(commands, tolerance=.05):
    import numpy as np
    """De Casteljau subdivision, with control-polygon deviation and a hard budget."""
    check_commands(commands)
    tol = finite(tolerance)
    if not .0001 <= tol <= 5:
        raise ValueError("Flatten tolerance out of range")
    rings, points = [], []

    def cubic(p, depth=0):
        if sum(map(len, rings)) + len(points) > 16384:
            raise ValueError("Sampling budget exceeded")
        chord = p[3]-p[0]
        length = np.linalg.norm(chord)
        if length < 1e-12:
            flat = np.max(np.linalg.norm(p-p[0], axis=1)) <= tol
        else:
            # The polygon-length test catches collinear loops/backtracking.
            cross = chord[0]*(p[1:3, 1]-p[0, 1])-chord[1]*(p[1:3, 0]-p[0, 0])
            flat = (max(abs(cross))/length <= tol and
                    sum(np.linalg.norm(np.diff(p, axis=0), axis=1))-length <= tol)
        if flat:
            points.append(p[3].tolist())
            return
        if depth >= 20:
            raise ValueError("Cubic cannot meet subdivision tolerance")
        q = (p[:-1]+p[1:])/2
        r = (q[:-1]+q[1:])/2
        mid = (r[0]+r[1])/2
        cubic(np.array([p[0], q[0], r[0], mid]), depth+1)
        cubic(np.array([mid, r[1], q[2], p[3]]), depth+1)

    for c in commands:
        if c[0] == "M":
            if points:
                rings.append(points)
            points = [c[1:]]
        elif c[0] == "L":
            points.append(c[1:])
        elif c[0] == "C":
            cubic(np.array([points[-1], c[1:3], c[3:5], c[5:7]], dtype=float))
        elif c[0] == "Z":
            if points[-1] != points[0]:
                points.append(points[0])
    if points:
        rings.append(points)
    return rings


def interpolate(first, last, t):
    check_commands(first)
    check_commands(last)
    if len(first) != len(last) or any(a[0] != b[0] for a, b in zip(first, last)):
        raise ValueError("Interpolation requires matching segment topology and landmark order")
    return [[a[0], *[(1-t)*x+t*y for x, y in zip(a[1:], b[1:])]]
            for a, b in zip(first, last)]


def fit_polyline(points, tolerance, max_segments=128):
    import numpy as np
    """Fit piecewise cubics with fixed endpoints; verify both directions afterwards."""
    from scipy.optimize import lsq_linear
    p = np.asarray(points, dtype=float)
    if len(p) < 2:
        raise ValueError("Cannot fit empty offset")
    p = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-10]]
    if len(p) < 2:
        raise ValueError("Degenerate offset")
    result = [["M", *p[0]]]

    def fit(q, depth=0):
        if len(result) >= max_segments:
            raise ValueError("Editable offset segment budget exceeded")
        if len(q) == 2:
            result.append(["L", *q[-1]])
            return
        steps = np.diff(q, axis=0)
        unit = steps / np.linalg.norm(steps, axis=1)[:, None]
        corners = np.flatnonzero(np.sum(unit[:-1]*unit[1:], axis=1) < math.cos(math.radians(25)))
        if len(corners):
            split = int(corners[0])+1
            fit(q[:split+1], depth+1)
            fit(q[split:], depth+1)
            return
        lengths = np.r_[0, np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))]
        t = lengths/lengths[-1]
        u = 1-t
        basis = np.column_stack((3*u*u*t, 3*u*t*t))
        rhs = q-u[:, None]**3*q[0]-t[:, None]**3*q[-1]
        span = max(float(np.ptp(q, axis=0).max()), tolerance)
        lo, hi = q.min(axis=0)-span, q.max(axis=0)+span
        controls = np.column_stack([lsq_linear(basis, rhs[:, j], bounds=(lo[j], hi[j])).x
                                    for j in range(2)])
        predicted = basis@controls + u[:, None]**3*q[0]+t[:, None]**3*q[-1]
        errors = np.linalg.norm(predicted-q, axis=1)
        split = int(errors.argmax())
        if errors[split] <= tolerance/3:
            result.append(["C", *controls[0], *controls[1], *q[-1]])
            return
        if depth >= 16:
            raise ValueError("Offset fit recursion budget exceeded")
        split = max(1, min(len(q)-2, split))
        fit(q[:split+1], depth+1)
        fit(q[split:], depth+1)
    fit(p)
    return result


def offset(commands, distance, tolerance=.2, join_style="round", miter_limit=4):
    import numpy as np
    from shapely import LineString
    check_commands(commands, open_only=True)
    distance, tolerance = finite(distance), finite(tolerance)
    if not .01 <= tolerance <= 2 or join_style not in {"round", "bevel", "miter"}:
        raise ValueError("Unsupported offset tolerance or join")
    source = LineString(flatten(commands, tolerance/8)[0])
    if source.length < tolerance or not source.is_simple:
        raise ValueError("Offset needs a nondegenerate simple source")
    target = source.offset_curve(distance, quad_segs=32,
                                 join_style={"round": 1, "miter": 2, "bevel": 3}[join_style],
                                 mitre_limit=finite(miter_limit))
    if target.is_empty or target.geom_type != "LineString" or not target.is_simple:
        raise ValueError("Offset splits, collapses or self-intersects")
    points = list(target.coords)
    # GEOS versions can reverse negative offsets. Match the source-start normal.
    tangent = np.array(source.coords[1])-source.coords[0]
    normal = np.array([-tangent[1], tangent[0]])/np.linalg.norm(tangent)
    expected = np.array(source.coords[0])+distance*normal
    if np.linalg.norm(np.array(points[-1])-expected) < np.linalg.norm(np.array(points[0])-expected):
        points.reverse()
    candidate = fit_polyline(points, tolerance)
    fitted = LineString(flatten(candidate, tolerance/8)[0])
    error = float(target.hausdorff_distance(fitted))
    if not fitted.is_simple or error > tolerance:
        raise ValueError("Offset failed independent topology/distance verification")
    return candidate, {"hausdorff_error": error, "tolerance": tolerance,
                       "segments": len(candidate)-1, "metric": "sampled_bidirectional"}


def face_commands(loops, edges):
    import numpy as np
    from shapely import Polygon
    commands, sampled, uses = [], [], []
    for refs in loops:
        ring = []
        for ref in refs:
            if ref["edge"] not in edges:
                raise ValueError("Unknown shared edge: "+ref["edge"])
            edge = edges[ref["edge"]]
            part = reverse_edge(edge) if ref.get("reverse", False) else edge
            if ring and not np.allclose(ring[-1][-2:], part[0][1:], atol=1e-8, rtol=0):
                raise ValueError("Shared face has a gap between edges")
            ring.extend(part if not ring else part[1:])
            uses.append((ref["edge"], ref.get("reverse", False)))
        if not ring or not np.allclose(ring[-1][-2:], ring[0][1:], atol=1e-8, rtol=0):
            raise ValueError("Shared face is not closed")
        commands.append(ring+[["Z"]])
        sampled.append(flatten(ring+[["Z"]])[0])
    polygon = Polygon(sampled[0], sampled[1:])
    if not polygon.is_valid or polygon.area < 1e-8:
        raise ValueError("Shared face self-intersects or has invalid holes")
    # Reverse cubic segments, never polygonize output, to preserve editable holes.
    from shapely import LinearRing
    out = []
    for i, ring in enumerate(commands):
        want_ccw = i == 0
        if bool(LinearRing(sampled[i]).is_ccw) != want_ccw:
            ring = reverse_edge(ring[:-1])+[["Z"]]
            start = sum(len(v) for v in loops[:i])
            uses[start:start+len(loops[i])] = [(edge, not rev) for edge, rev in uses[start:start+len(loops[i])]]
        out.extend(ring)
    return out, uses
