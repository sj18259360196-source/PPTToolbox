# Graphics Construction

The `graphics.*` tools compile `graphics-recipe/1` into the existing native
scene primitives. Discover the full schema and sample with `graphics.inspect`.
The manager UI has a dedicated graphics workspace. CLI execution uses
`manager.py execute --tool graphics.compile -- --json request.json`; the request includes
an authorized `project` and a `recipe`. MCP exposes the same operations.

## Capabilities

For semantic object/material decomposition and managed invocation, read
[Native illustration](native-illustration.md). The `surface_layers` curve-group
mode creates named closed surfaces from one open centerline. Inspect exposes a
seven-layer tube example. Authored fill gradients accept up to 16 stops; stroke
gradients and automatic fitting retain their existing five-stop limits.

- Curve groups support same-topology cubic interpolation, affine repetition,
  and bounded open-path offsets. Offset fitting retains editable cubic segments.
  Invalid, split, collapsed, or self-intersecting offsets are rejected.
- Shared faces reference named edges with orientation. Editing one edge updates
  both faces. Closed loops, holes, manifold use and winding are validated.
- Gradient fitting uses an optional binary sampling mask, robust optimization,
  and held-out pixels. It compares solid, linear and optional radial models
  with two to five stops. Results include errors and identifiability warnings.
- Linked instances apply affine transforms and style overrides. Locked and
  detached copies retain the previous persisted geometry. First compile must
  use linked copies. Detached copies may outlive their original source.

## Operations

`graphics.preview` accepts `recipe` and, for locked/detached state, `project`
and `version`. It produces an SVG-rendered PNG without changing a PPT.
`graphics.compile` writes an immutable draft under
`project/assets/graphics/<version>/`.
`graphics.regenerate` requires the previous `version`; it checks file integrity
and actual PPT object signatures before creating a successor draft.
`graphics.validate` reports structural changes, not visual acceptance.
`graphics.fit_gradient` accepts base64 image data, optional mask, `models`
and `max_stops`. Use a bounded crop, particularly over MCP's message-size limit.

For measured fill correction, keep the crop in the target shape's gradient frame.
Native custom paths use the bounds of all command coordinates, including control
points, unless `native_path_frame` supplies the frame. Cropping to only the visible
portion changes the gradient coordinate system. Mask out text, strokes, occlusion
and other objects; keep separate spatial regions out of the fit and compare those
regions in the actual Office export before adopting a suggestion. A mask and low
fit error do not establish correct object attribution.

The fitter estimates opaque effective colors, not the original opacity or layer
composition. A solid fill can be the best supported result; do not force a gradient
when the direction is unidentifiable. Retain the original candidate, compare the
whole page and affected objects, and test native fill edits on a copy.

Each draft includes the recipe, ordinary scene objects, native editable PPTX,
preview, integrity manifest and native readback. Submit returned `objects`
through the existing region-object workflow when appropriate; drafts are never
automatically adopted into a project's active candidate.

## Boundaries

Relations live in the recipe and manager, not as live PowerPoint constraints.
Instance gradients use the destination bounding box with the stored angle;
affine transforms move geometry but do not rotate that gradient angle.
Editing the exported PPT does not update the recipe. Regeneration refuses
observed native changes instead of silently overwriting them.
Colors fitted from a composited reference are effective opaque colors; the
original foreground color and opacity cannot be uniquely recovered.
Fit an image crop matching the target's visible geometry bounding box. Keep
masked pixels in that same coordinate system. Native linear fitting uses an
empirical Office 16 Windows transfer profile with gamma 2.2, calibrated on a
black-to-white ramp and checked separately on colored geometry and other
aspect ratios. Other Office versions/renderers and alpha interpolation require
separate comparison. The profile is stored under `assets/graphics`.
Radial fitting and SVG previews are approximations pending Office comparison.
Gradient strokes support linear gradients only.
Geometry fitting is bounded and can reject difficult inputs rather than
produce arbitrary polylines. No automatic visual approval is issued.

## Path-fit joint constraints

The bounded path fitter preserves exact coincident coordinates across the
supplied selected paths. A coincident point on an unchanged context path anchors
the selected path at that point. Straight horizontal/vertical line constraints
propagate through these shared coordinates. The report includes `joint_constraints`
with the number of anchored and shared scalar classes.

These rules do not discover semantic connections, repair existing gaps, snap
nearby points, or account for context omitted from the request. A better pixel
score can still follow the wrong neighboring contour. Inspect junctions and
feature identity in a fresh actual Office export before adopting a suggestion.

The fitter retains the lowest-error candidate that also passes its geometry
guards. A lower-error self-intersecting candidate cannot replace a valid one.
`rejected_geometry_candidates` records rejected attempts that would otherwise
replace the current best. This is not a count of all invalid solver evaluations,
nor a visual acceptance score.

## Choosing a contour representation

Inspect the feature before fitting its coordinates. A variable-width mark,
such as a crescent-shaped closed eye, may require a filled closed outline.
Moving the control points of an equal-width stroke cannot express every such
silhouette, even when a small-ROI pixel score looks favorable.

For an explicitly separated small semantic part, `icons_trace_fragment` can
produce native filled contours from an opaque black/white mask. Preserve the
mask, its source placement, feature identity and threshold decision. Inspect
the source, SVG preview and actual Office crop independently. Thresholding
discards soft edge/color information; tracing may create many nodes for a tiny
part. Verify node editing and review complexity before treating it as a usable
replacement. Never substitute a whole-slide trace or silently change nearby
objects to improve the score.

For `smoothing="curves"`, optional `simplify_error_px` accepts `0` (default,
disabled) or `0.05..0.5` in the original mask's pixels. It merges adjacent
cubics while retaining straight edges, contour count, orientation and ring
relationships. Contours of at most four mask pixels in area are protected.
The combined draft is limited to 96 commands and 16 rings for simplification;
the merge search has 256 attempts and a two-second deadline, with bounded
sampling. Unsupported or rejected geometry stays unchanged.

Inspect the returned `simplification` record. Its error bound measures change
from the unsimplified traced draft, not fidelity to the original colored image.
The point-to-polyline check samples both directions and includes margins for
the sample spacing and cubic flattening. This does not replace a fresh actual
Office render or node-edit verification.

## Shape construction case

For irregular polygons, radial repetition, alpha overlaps, compound holes and
reference overlays, read [Shape construction case](shape-construction-case.md).
It links EXP-181 through EXP-190 to the actual case evidence, distinguishes
drawn Boolean-like silhouettes from executed Boolean operations, and provides
two generic recipes. These additions are source guidance; check the currently
installed schema before invocation. Example compilation is not Office approval.

## Dependencies

Install `requirements-graphics.txt` into the application's Python environment,
or vendor SciPy into `toolbox_manager/vendor/graphics` alongside the existing
icon dependencies. NumPy must satisfy SciPy's own dependency requirements.
Run `tests/test_graphics_construction.py` and the existing manager, native and
workflow suites before packaging. Preserve the normal installation identity
defined in `manager_docs/INSTALLATION_CONTRACT.md`.
# 参数构建与操作读回

圆角多边形、布尔学习试制、显式掩膜轮廓比较、独立原生属性读回和受限节点修改见 [异形工具](shape-tools.md)。这些入口复用 graphics 配方与 rebuild_patch/compare/adopt，保持现有权限及审查。
