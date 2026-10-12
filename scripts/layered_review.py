"""Versioned review coverage and advisory image resolution. No visual verdicts."""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image
from common import sha256, resolve_asset

POLICY = 'layered-review/2'


def _known_policy(policy):
    if policy not in (None, 'legacy-side/1', POLICY):
        raise ValueError('Unsupported review policy: '+str(policy))


def review_policy(run):
    policy = run.get('review_policy')
    _known_policy(policy)
    return policy or 'legacy-side/1'


def required_views(comp, index, region_id=None, policy=None):
    _known_policy(policy)
    if region_id is not None:
        return bundle_view_files(comp['local_paths'][(index, region_id)], policy)
    if policy != POLICY:
        return [comp['full_paths'][index]]
    views = comp['full_view_paths'][index]
    return [views['side_by_side'], views['overlay']]


def bundle_view_files(row, policy=None):
    _known_policy(policy)
    if policy != POLICY:
        return [row['file']]
    return [row['views']['side_by_side'], row['views']['overlay']]


local_required_views = bundle_view_files


def view_signature(comp, index, region_id=None, policy=None):
    """Role-ordered bytes bind observations even when run output paths differ."""
    return tuple(sha256(path) for path in required_views(comp, index, region_id, policy))


def effective_resolution(node, base, canvas):
    """Compute actual source pixels per placed unit, preserving fit/crop behavior.

    Alpha bounds identify visible pixels only; they cannot identify semantic parts.
    Logical units and PowerPoint points remain distinct from screen/export pixels.
    """
    if node.get('kind') != 'image':
        raise ValueError('effective_resolution requires an image object')
    box = node.get('bbox')
    if (not isinstance(box, list) or len(box) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
            box[2] <= 0 or box[3] <= 0):
        raise ValueError('Image bbox must be finite positive xywh')
    path = resolve_asset(Path(base), node['asset'])
    with Image.open(path) as original:
        rgba = original.convert('RGBA')
        iw, ih = rgba.size
        crop = node.get('source_crop', [0, 0, iw, ih])
        if (not isinstance(crop, list) or len(crop) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in crop)):
            raise ValueError('Invalid source crop')
        cx, cy, cw, ch = crop
        if cx < 0 or cy < 0 or cw <= 0 or ch <= 0 or cx+cw > iw or cy+ch > ih:
            raise ValueError('Source crop exceeds image')
        fit = node.get('fit', 'contain')
        if fit not in {'contain', 'cover', 'stretch'}:
            raise ValueError('Invalid image fit')
        w, h = box[2:]
        if 'source_crop' in node or fit == 'stretch':
            sx, sy = w/cw, h/ch
        elif fit == 'contain':
            sx = sy = min(w/iw, h/ih)
        else:
            sx = sy = max(w/iw, h/ih)
            cw, ch = w/sx, h/sy
            cx, cy = (iw-cw)/2, (ih-ch)/2
        alpha = rgba.getchannel('A')
        bounds = alpha.getbbox()
    visible = None
    if bounds:
        l, t = max(cx, bounds[0]), max(cy, bounds[1])
        r, b = min(cx+cw, bounds[2]), min(cy+ch, bounds[3])
        if r > l and b > t:
            visible = [l, t, r-l, b-t]
    if any(type(canvas.get(k)) not in (int, float) or not math.isfinite(canvas[k]) or canvas[k] <= 0
           for k in ('width_pt', 'width', 'height_pt', 'height')):
        raise ValueError('Canvas dimensions must be positive')
    px, py = canvas['width_pt']/canvas['width'], canvas['height_pt']/canvas['height']
    if not all(math.isfinite(v) and v > 0 for v in (px, py)):
        raise ValueError('Canvas dimensions must be positive')
    return {'object_id': node['id'], 'asset_sha256': sha256(path),
            'source_pixels': [iw, ih], 'visible_crop_xywh': [cx, cy, cw, ch],
            'subject_pixels_xywh': visible,
            'placed_subject_size': [visible[2]*sx, visible[3]*sy] if visible else [0, 0],
            'pixels_per_logical_unit': [1/sx, 1/sy],
            'effective_ppi': [72/(sx*px), 72/(sy*py)],
            'scope': 'source_pixel_density_and_alpha_bounds_only',
            'visual_review': 'required', 'automatic_acceptance': False,
            'limitations': 'No recovered detail estimate. Alpha bounds include shadows and glow; masks and group transforms require final rendered inspection.'}
