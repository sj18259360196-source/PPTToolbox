"""Optional bounded merging of adjacent cubics in closed native contours.

The input remains authoritative. Lines, contour count, ring orientation and
nesting are preserved; a failed guard returns the original commands.
"""
from __future__ import annotations
import copy
import math
import time

import numpy as np
from .graphics_geometry import check_commands, flatten, finite


class MergeBudget:
    def __init__(self, attempts=256, seconds=2):
        self.remaining = attempts
        self.deadline = time.monotonic() + seconds
        self.exhausted = False

    def take(self):
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            self.exhausted = True
            return False
        self.remaining -= 1
        return True


def _distance_bound(first, second, tolerance):
    """Sample both polylines, bound intervening distance by arc length."""
    from shapely import distance, line_interpolate_point
    maximum = 0.
    for source, target in ((first, second), (second, first)):
        count = max(2, math.ceil(source.length / (tolerance / 8)) + 1)
        if count > 4096:
            return math.inf
        samples = line_interpolate_point(source, np.linspace(0, source.length, count))
        maximum = max(maximum, float(np.max(distance(samples, target))) +
                      source.length / (count - 1) / 2)
    # Each flattened cubic uses tolerance/32; reserve twice that amount per
    # boundary for projection and endpoint deviation from its chord.
    return maximum + tolerance / 8


def _merged(span, tolerance):
    from shapely.geometry import LineString
    p0, p1 = np.array(span[0][1:]), np.array(span[1][1:3])
    p2, p3 = np.array(span[-1][3:5]), np.array(span[-1][5:7])
    first, last = p1 - p0, p3 - p2
    if min(np.linalg.norm(first), np.linalg.norm(last)) < 1e-8:
        return None
    first, last = first / np.linalg.norm(first), last / np.linalg.norm(last)
    source = LineString(flatten(span, tolerance / 32)[0])
    t = np.linspace(0, 1, max(20, min(96, int(source.length / tolerance) + 1)))
    from shapely import get_coordinates, line_interpolate_point
    points = get_coordinates(line_interpolate_point(source, t, normalized=True))
    a, b = 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t
    base = ((1 - t) ** 3 + a)[:, None] * p0 + (b + t ** 3)[:, None] * p3
    matrix = np.stack((a[:, None] * first, -b[:, None] * last), axis=-1).reshape(-1, 2)
    scales = np.linalg.lstsq(matrix, (points - base).ravel(), rcond=None)[0]
    if np.any(scales <= 0) or np.any(scales > 2 * source.length):
        return None
    command = ["C", *(p0 + scales[0] * first), *(p3 - scales[1] * last), *p3]
    result = LineString(flatten([span[0], command], tolerance / 32)[0])
    if not result.is_simple or _distance_bound(source, result, tolerance) > tolerance:
        return None
    return command


def simplify_filled(commands, tolerance, *, protected_area=0, budget=None):
    """Return a candidate plus geometry evidence, never a visual approval."""
    from shapely.geometry import LinearRing, Polygon, LineString
    check_commands(commands)
    tolerance, protected_area = finite(tolerance), finite(protected_area)
    if not .05 <= tolerance <= 2 or protected_area < 0:
        raise ValueError("Unsupported contour simplification tolerance or protected area")
    original = copy.deepcopy(commands)
    report = {"status": "unchanged", "before_commands": len(original),
              "after_commands": len(original), "boundary_error_bound": 0.,
              "visual_review": "pending"}
    if len(commands) > 96:
        return original, {**report, "reason": "command_budget"}
    rings = []
    for command in commands:
        if command[0] == "M":
            rings.append([])
        rings[-1].append(command)
    if len(rings) > 16 or any(r[-1][0] != "Z" for r in rings):
        return original, {**report, "reason": "closed_contours_required"}
    budget = budget or MergeBudget()
    try:
        polygons, boundaries, revised = [], [], []
        for ring in rings:
            points = flatten(ring, tolerance / 32)[0]
            line, polygon = LineString(points), Polygon(points)
            if not line.is_ring or not polygon.is_valid:
                return original, {**report, "reason": "invalid_source_topology"}
            polygons.append(polygon)
            boundaries.append(line)
            if polygon.area <= protected_area:
                revised.append(copy.deepcopy(ring))
                continue
            result, index = [copy.deepcopy(ring[0])], 1
            while index < len(ring):
                if ring[index][0] != "C" or budget.exhausted:
                    result.append(copy.deepcopy(ring[index]))
                    index += 1
                    continue
                end = index
                while end < len(ring) and ring[end][0] == "C":
                    end += 1
                for stop in range(end, index + 1, -1):
                    if not budget.take():
                        break
                    span = [["M", *result[-1][-2:]], *ring[index:stop]]
                    candidate = _merged(span, tolerance)
                    if candidate is not None:
                        result.append(candidate)
                        index = stop
                        break
                else:
                    result.append(copy.deepcopy(ring[index]))
                    index += 1
                    continue
                if budget.exhausted:
                    result.append(copy.deepcopy(ring[index]))
                    index += 1
            revised.append(result)
        output = [c for ring in revised for c in ring]
        if output == original:
            return original, {**report, "reason": "budget_exhausted" if budget.exhausted else "no_safe_merge"}
        changed_polygons, maximum = [], 0.
        for before, source, ring, old_ring in zip(polygons, boundaries, revised, rings):
            points = flatten(ring, tolerance / 32)[0]
            line, polygon = LineString(points), Polygon(points)
            if (not line.is_ring or not polygon.is_valid
                    or LinearRing(source.coords).is_ccw != LinearRing(line.coords).is_ccw):
                return original, {**report, "reason": "topology_guard"}
            changed_polygons.append(polygon)
            if ring != old_ring:
                maximum = max(maximum, _distance_bound(source, line, tolerance))
        for i, polygon in enumerate(polygons):
            for j in range(i):
                if (polygon.relate(polygons[j]) != changed_polygons[i].relate(changed_polygons[j])):
                    return original, {**report, "reason": "ring_relationship_guard"}
        if maximum > tolerance:
            return original, {**report, "reason": "boundary_guard"}
        return output, {**report, "status": "simplified", "after_commands": len(output),
                        "boundary_error_bound": maximum, "budget_exhausted": budget.exhausted}
    except (ValueError, np.linalg.LinAlgError) as exc:
        return original, {**report, "reason": "geometry_guard", "detail": str(exc)}
