"""Frozen simple-background metrics and bounded, deterministic search."""
from __future__ import annotations

import itertools
import math
from decimal import Decimal, ROUND_HALF_UP


METRIC = {
    "version": "fixed-foreground/3", "background_distance": 32,
    "weights": {"bounds": 1.0, "projection": 1.0, "symmetric_pixels": 1.0},
    "noise_limit": 0.002, "min_delta": 0.001, "target": 0.008,
    "outside_threshold": 0, "fringe_px": 2,
    "critical_noise_limit_px": 0.5, "critical_min_improvement_px": 0.5,
}
CRITICAL_FEATURES = ("left", "top", "right", "bottom", "line_left", "line_top")
FIELDS = ("x", "y", "width", "height", "font_size_pt",
          "margin_left_pt", "margin_right_pt", "margin_top_pt", "margin_bottom_pt")


def quantize(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def validate_parameters(parameters):
    if not 1 <= len(parameters) <= 4 or len({p["object_id"] for p in parameters}) > 3:
        raise ValueError("At most three objects and four independent scalar parameters")
    keys = [(p["object_id"], p["field"]) for p in parameters]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate parameter")
    for p in parameters:
        if p["field"] not in FIELDS or p["unit"] != "pt" or p["anchor"] != "top_left":
            raise ValueError("Unsupported field, unit or anchor")
        for k in ("initial", "lower", "upper", "step", "min_step"):
            if type(p[k]) not in (int, float) or not math.isfinite(p[k]):
                raise ValueError("Finite numeric parameter required")
        if not p["lower"] <= p["initial"] <= p["upper"] or p["lower"] == p["upper"]:
            raise ValueError("Invalid range")
        if not .01 <= p["min_step"] <= p["step"]:
            raise ValueError("Step below backend precision")
        if p["field"] in ("width", "height", "font_size_pt") and p["lower"] <= 0:
            raise ValueError("Positive sizes required")
        if p["field"].startswith("margin") and p["lower"] < 0:
            raise ValueError("Negative inset")
        if "values" in p:
            vals = p["values"]
            if not vals or len(vals) > 25 or any(type(v) not in (int, float) or not math.isfinite(v)
                                               or not p["lower"] <= v <= p["upper"] for v in vals):
                raise ValueError("Invalid finite enumeration")
            if len({quantize(v) for v in vals}) != len(vals):
                raise ValueError("Duplicate quantized values")
    for oid in {p["object_id"] for p in parameters}:
        fields = {p["field"] for p in parameters if p["object_id"] == oid}
        if ({"x"} & fields and fields & {"margin_left_pt", "margin_right_pt"}) or (
                {"y"} & fields and fields & {"margin_top_pt", "margin_bottom_pt"}):
            raise ValueError("Ambiguous position/inset parameters; fix one family")


def neighbors(parameters, center, steps):
    vectors = []
    for i, p in enumerate(parameters):
        values = p.get("values", [center[i]-steps[i], center[i]+steps[i]])
        for v in values:
            v = quantize(v)
            if p["lower"] <= v <= p["upper"]:
                row = list(center); row[i] = v
                vectors.append(row)
    # A small coupled block crosses width/font wrapping discontinuities.
    for i, p in enumerate(parameters):
        for j in range(i+1, len(parameters)):
            q = parameters[j]
            if p["object_id"] == q["object_id"] and {p["field"], q["field"]} == {"width", "font_size_pt"}:
                for a, b in itertools.product((-1, 1), repeat=2):
                    row = list(center)
                    row[i], row[j] = quantize(row[i]+a*steps[i]), quantize(row[j]+b*steps[j])
                    if p["lower"] <= row[i] <= p["upper"] and q["lower"] <= row[j] <= q["upper"]:
                        vectors.append(row)
    seen = {tuple(center)}
    return [list(v) for v in dict.fromkeys(tuple(v) for v in vectors) if v not in seen]


def foreground(path, roi, background):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.int16)
    x0, y0, x1, y1 = roi
    if not 0 <= x0 < x1 <= rgb.shape[1] or not 0 <= y0 < y1 <= rgb.shape[0]:
        raise ValueError("ROI outside fixed full-page coordinates")
    area = rgb[y0:y1, x0:x1]
    mask = np.max(np.abs(area-np.array(background)), axis=2) > METRIC["background_distance"]
    ys, xs = np.nonzero(mask)
    if not len(xs) or mask.mean() > .80:
        return {"status": "unmeasurable", "reason": "Empty or non-separable foreground"}
    colors, counts = np.unique(area[mask], axis=0, return_counts=True)
    ink = colors[counts.argmax()].astype(float)-np.array(background)
    pixels = area[mask].astype(float)-np.array(background)
    alpha = np.clip(pixels @ ink/max(1, ink @ ink), 0, 1)
    residual = np.max(np.abs(pixels-alpha[:, None]*ink), axis=1)
    if np.mean(residual > 24) > .02:
        return {"status": "unmeasurable", "reason": "Multiple inks/texture outside single-foreground model"}
    # Boundary contact could hide clipping; do not silently crop it away.
    touching = bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
    runs = np.flatnonzero(np.diff(np.r_[False, mask.any(axis=1), False].astype(int)))
    return {"status": "measured", "mask": mask, "touching": touching,
            "bounds": [int(xs.min()+x0), int(ys.min()+y0), int(xs.max()+x0+1), int(ys.max()+y0+1)],
            "line_bands": [[int(runs[i]+y0), int(runs[i+1]+y0)] for i in range(0, len(runs), 2)],
            "baseline": "unknown"}


def measure(reference, candidate, roi, background):
    import numpy as np
    a, b = foreground(reference, roi, background), foreground(candidate, roi, background)
    if a["status"] != "measured" or b["status"] != "measured":
        return {"status": "unmeasurable", "reference": a.get("reason"), "candidate": b.get("reason")}
    am, bm = a.pop("mask"), b.pop("mask")
    denom = max(1, int(am.sum()))
    bounds = sum(abs(x-y) for x, y in zip(a["bounds"], b["bounds"])) / (
        2*((roi[2]-roi[0])+(roi[3]-roi[1])))
    projection = (np.abs(am.sum(0)-bm.sum(0)).sum()+np.abs(am.sum(1)-bm.sum(1)).sum())/(2*denom)
    symmetric = np.logical_xor(am, bm).sum()/denom
    scores = {"bounds": float(bounds), "projection": float(projection), "symmetric_pixels": float(symmetric)}
    return {"status": "measured", "terms": scores,
            "score": sum(scores[k]*METRIC["weights"][k] for k in scores),
            "reference": a, "candidate": b, "denominator": denom,
            "metric_version": METRIC["version"]}


def validate_critical_dimensions(dimensions, target_ids, size):
    if len(dimensions) > 4:
        raise ValueError("At most four critical dimensions")
    seen = set()
    for d in dimensions:
        key = (d["object_id"], d["feature"], d.get("line_index", 0))
        if key in seen or d["object_id"] not in target_ids:
            raise ValueError("Duplicate critical dimension or unauthorized object")
        seen.add(key)
        if d["feature"] not in CRITICAL_FEATURES:
            raise ValueError("Unsupported critical feature")
        roi = d["roi"]
        if (len(roi) != 4 or any(type(v) is not int for v in roi) or
                not 0 <= roi[0] < roi[2] <= size[0] or not 0 <= roi[1] < roi[3] <= size[1]):
            raise ValueError("Critical ROI must retain full-page coordinates")
        tol = d["tolerance_px"]
        if type(tol) not in (int, float) or not math.isfinite(tol) or not 0 <= tol <= 10:
            raise ValueError("Invalid frozen critical tolerance")
        if type(d.get("line_index", 0)) is not int or not 0 <= d.get("line_index", 0) <= 99:
            raise ValueError("Invalid visible-line index")
        source = d["source"]
        if source["level"] not in {"observed", "measured", "inferred", "unknown"} or not source["note"].strip():
            raise ValueError("Critical dimension needs source attribution")


def critical_check(reference, baseline, candidate, dimensions, background, repeat=None):
    """Reference-derived visible edges, independent of aggregate score compensation."""
    import numpy as np
    rows = []
    for d in dimensions:
        row = {"object_id": d["object_id"], "feature": d["feature"], "roi": d["roi"],
               "tolerance_px": d["tolerance_px"], "source": d["source"], "status": "needs_review"}
        rows.append(row)
        if d["source"]["level"] not in {"observed", "measured"}:
            row["reason"] = "Critical source is not reliably observed/measured"
            continue
        paths = [reference, baseline, candidate] + ([repeat] if repeat else [])
        obs = [foreground(p, d["roi"], background) for p in paths]
        if any(o["status"] != "measured" or o["touching"] for o in obs):
            row["reason"] = "Critical foreground unmeasurable or touches fixed ROI"
            continue
        feature = d["feature"]
        if feature.startswith("line_"):
            index = d.get("line_index", 0)
            counts = [len(o["line_bands"]) for o in obs]
            if len(set(counts)) != 1 or index >= counts[0]:
                row["reason"] = "Visible line correspondence is uncertain"
                continue
            values = []
            for o in obs:
                top, bottom = o["line_bands"][index]
                if feature == "line_top":
                    values.append(top)
                else:
                    part = o["mask"][top-d["roi"][1]:bottom-d["roi"][1]]
                    values.append(int(np.nonzero(part)[1].min())+d["roi"][0])
        else:
            values = [o["bounds"][CRITICAL_FEATURES.index(feature)] for o in obs]
        ref, base, current = values[:3]
        noise = abs(values[3]-base) if repeat else None
        base_error, error = abs(base-ref), abs(current-ref)
        row.update(reference_px=ref, baseline_px=base, candidate_px=current,
                   baseline_error_px=base_error, error_px=error, noise_px=noise,
                   target_met=error <= d["tolerance_px"],
                   improved=base_error-error > METRIC["critical_min_improvement_px"])
        if noise is not None and noise > METRIC["critical_noise_limit_px"]:
            row["reason"] = "Critical edge noise exceeds frozen limit"
        else:
            # A poor baseline permits gradual progress; a good one stays within tolerance.
            row["status"] = "passed" if error <= max(base_error, d["tolerance_px"]) else "rejected"
            row["reason"] = "No critical regression" if row["status"] == "passed" else "Critical edge regressed"
    status = ("needs_review" if any(r["status"] == "needs_review" for r in rows) else
              "rejected" if any(r["status"] == "rejected" for r in rows) else "passed")
    return {"status": status, "dimensions": rows, "scope": "Declared visible edges only; not visual acceptance",
            "declaration": "present" if dimensions else "none",
            "target_met": all(r.get("target_met", False) for r in rows)}


def qualification(legal, measurement, baseline, critical):
    if not legal:
        return {"status": "rejected", "reason": "Existing hard checks failed", "critical": critical}
    if critical["status"] != "passed":
        return {"status": critical["status"], "reason": "Critical dimension not passed", "critical": critical}
    if measurement["status"] != "measured":
        return {"status": "needs_review", "reason": "Unmeasurable score", "critical": critical}
    better = (not baseline["legal"] or measurement["score"] < baseline["measurement"]["score"] -
              max(METRIC["min_delta"], baseline["noise"]["score"]))
    return {"status": "eligible" if better else "no_improvement",
            "reason": "Legal improvement within declared scope" if better else "Retain baseline",
            "critical": critical}
