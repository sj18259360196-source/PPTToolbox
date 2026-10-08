"""Masked gradient fitting with held-out samples and explicit identifiability limits."""
from __future__ import annotations

import time
import numpy as np
from graphics_geometry import ROOT  # Also locates the isolated fitting dependencies.
from graphics_paint import mix, transfer, profile


def positions(xy, width, height, model, params):
    if model == "linear":
        angle = np.deg2rad(params[0])
        # Calibrated with native Office rectangles at different aspect ratios.
        a, b = np.cos(angle), np.sin(angle)
        return np.clip((xy[:, 0]*a+xy[:, 1]*b-min(0, a)-min(0, b)) /
                       max(abs(a)+abs(b), 1e-12), 0, 1)
    cx, cy = params[:2]
    rx, ry = max(cx, 1-cx), max(cy, 1-cy)
    return np.clip(np.hypot((xy[:, 0]-cx)/rx, (xy[:, 1]-cy)/ry), 0, 1)


def predict(xy, width, height, gradient):
    model = gradient["type"]
    params = [gradient["angle_deg"]] if model == "linear" else gradient.get("center", [.5, .5])
    t = positions(np.asarray(xy), width, height, model, params)
    stops = gradient["stops"]
    colors = np.array([[int(s["color"][j:j+2], 16)/255 for j in (0, 2, 4)] for s in stops])
    return mix(t, [s["position"] for s in stops], colors)


def fit_gradient(image, mask=None, *, models=("linear",), max_stops=3,
                 max_samples=1536, max_nfev=80, timeout_seconds=20):
    from scipy.optimize import least_squares
    started = time.monotonic()
    if not set(models) <= {"linear", "radial"} or not models:
        raise ValueError("Unknown gradient model")
    if not 2 <= max_stops <= 5 or not 64 <= max_samples <= 4096 or not 5 <= max_nfev <= 200:
        raise ValueError("Gradient fit budget out of range")
    if not 1 <= timeout_seconds <= 60:
        raise ValueError("Gradient fit timeout out of range")
    rgba = np.asarray(image.convert("RGBA"))
    rgb = rgba[:, :, :3].astype(float)/255
    height, width = rgb.shape[:2]
    if width < 4 or height < 4 or width*height > 4_000_000:
        raise ValueError("Gradient image dimensions out of range")
    valid = rgba[:, :, 3] == 255
    if mask is not None:
        if mask.size != image.size:
            raise ValueError("Gradient mask must match image dimensions")
        valid &= np.asarray(mask.convert("L")) > 127
    yy, xx = np.nonzero(valid)
    if len(xx) < 64 or np.ptp(xx) < width*.25 or np.ptp(yy) < height*.25:
        raise ValueError("Insufficient two-dimensional unoccluded samples")
    # Deterministic, distributed sampling plus independent held-out samples.
    rng = np.random.default_rng(73021)
    take = rng.choice(len(xx), min(max_samples, len(xx)), replace=False)
    x, y = xx[take], yy[take]
    xy = np.column_stack(((x+.5)/width, (y+.5)/height))
    colors = rgb[y, x]
    train = np.arange(len(x)) % 4 != 0
    tx, ty = xy[train], colors[train]
    vx, vy = xy[~train], colors[~train]
    constant = np.median(ty, axis=0)
    solid_error = float(np.abs(vy-constant).mean())
    candidates = [{"model": "solid", "validation_mae": solid_error,
                   "score": solid_error, "color": "".join(f"{int(v):02X}" for v in np.rint(constant*255))}]
    timed_out = False

    def budget():
        if time.monotonic()-started > timeout_seconds:
            raise TimeoutError("Gradient optimization reached its time budget")

    def color_hex(row):
        return "".join(f"{v:02X}" for v in np.rint(np.clip(row, 0, 1)*255).astype(int))

    for model in models:
        seeds = [[a] for a in range(0, 180, 15)] if model == "linear" else [
            [.5, .5], [.25, .25], [.75, .25], [.25, .75], [.75, .75]]
        ranked = []
        for seed in seeds:
            t = transfer(positions(tx, width, height, model, seed))
            gamma = profile()["gamma"]
            coefficients = np.linalg.lstsq(np.column_stack((1-t, t)), ty**gamma, rcond=None)[0]
            endpoints = np.clip(coefficients, .0001, .9999)**(1/gamma)
            estimate = ((1-t[:, None])*endpoints[0]**gamma+t[:, None]*endpoints[1]**gamma)**(1/gamma)
            ranked.append((float(np.abs(estimate-ty).mean()), seed, endpoints))
        for count in range(2, max_stops+1):
            for _, seed, endpoints in sorted(ranked, key=lambda row: row[0])[:2]:
                size = len(seed)
                knots = np.linspace(0, 1, count)
                initial_colors = np.array([(1-t)*endpoints[0]+t*endpoints[1] for t in knots])
                # Interior stops are fitted, with sorting and minimum gap checked below.
                initial = np.r_[seed, knots[1:-1], initial_colors.ravel()]
                lower = np.r_[[-360] if model == "linear" else [.05, .05],
                              np.full(count-2, .02), np.zeros(count*3)]
                upper = np.r_[[360] if model == "linear" else [.95, .95],
                              np.full(count-2, .98), np.ones(count*3)]

                def unpack(p):
                    return np.r_[0, np.sort(p[size:size+count-2]), 1], p[size+count-2:].reshape(count, 3)

                def residual(p):
                    budget()
                    stops, rgb_stops = unpack(p)
                    t = positions(tx, width, height, model, p[:size])
                    fitted = mix(t, stops, rgb_stops)
                    return (fitted-ty).ravel()
                try:
                    result = least_squares(residual, initial, bounds=(lower, upper),
                                           loss="soft_l1", f_scale=.02, max_nfev=max_nfev)
                except TimeoutError:
                    timed_out = True
                    break
                stops, fitted_colors = unpack(result.x)
                if min(np.diff(stops)) < .005:
                    continue
                gradient = {"type": model, "stops": [
                    {"position": float(t), "color": color_hex(c), "alpha": 1}
                    for t, c in zip(stops, fitted_colors)]}
                if model == "linear":
                    gradient["angle_deg"] = float(result.x[0] % 360)
                else:
                    gradient["center"] = result.x[:2].tolist()
                error = float(np.abs(predict(vx, width, height, gradient)-vy).mean())
                candidates.append({"model": model, "gradient": gradient, "validation_mae": error,
                                   "score": error+.0005*(count-1), "nfev": result.nfev,
                                   "optimizer_converged": bool(result.success)})
            if timed_out:
                break
        if timed_out:
            break
    candidates.sort(key=lambda v: v["score"])
    chosen = candidates[0]
    style = {"fill": chosen["color"]} if chosen["model"] == "solid" else {"gradient": chosen["gradient"]}
    warnings = ["opaque_effective_color_only", "office16_empirical_profile_other_renderers_unverified"]
    if "radial" in models:
        warnings.append("radial_preview_is_an_approximation_pending_office_comparison")
    if chosen["model"] == "solid":
        warnings.append("gradient_direction_not_identifiable")
    if timed_out:
        warnings.append("fit_time_budget_exhausted")
    return {"style": style, "selected": chosen, "candidates": candidates,
            "coverage": float(valid.mean()), "training_samples": int(train.sum()),
            "validation_samples": int((~train).sum()), "warnings": warnings,
            "elapsed_seconds": time.monotonic()-started, "office": "not_run",
            "visual_review": "pending", "color_model": profile()["id"]}
