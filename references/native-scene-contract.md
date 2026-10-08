# Compact Native Scene Contract

Return one JSON object only. It will be validated and built by PPTToolbox.
This is a drawing contract, not a fidelity claim or a source of reference answers.
Do not use tools, browse files, consult other attempts, or add explanations.
Use only the attached images and the canvas metadata supplied by the task.

```json
{
  "version": "1.0",
  "canvas": {
    "width": 960, "height": 540, "width_pt": 720, "height_pt": 405,
    "mapping": "uniform", "background": "F7F9FC"
  },
  "slides": [
    {"id": "supplied-case-id", "objects": []}
  ]
}
```

Object order is back to front. Coordinates and bounding boxes use image pixels.
Font sizes, stroke widths, margins, spacing and shadow dimensions use points.
Every object needs a unique per-slide ASCII `id`, `kind`, `editability` and
`evidence: {"status":"inferred","note":"Reconstructed from the attached image"}`.
Use only documented fields. Do not include source images or hidden backup images.

- Shape: `kind:"shape"`, `editability:"shape"`, `bbox:[x,y,width,height]`,
  `geometry` from `rect`, `round_rect`, `ellipse`, `triangle`, `diamond`,
  `chevron`, `right_arrow`, `left_right_arrow`, `star5`, `arc`.
  Optional `adjustments` uses normalized numbers from 0 to 1, not OOXML integers.
  For `round_rect`, use one value `radius / min(width,height)`, at most 0.5.
  For example a 6-pixel radius in a 100-pixel-high box is `[0.06]`, not `[6000]`.
  A capsule uses `[0.5]`. Do not leave the default radius for a measured small corner.
- Path: `kind:"path"`, `editability:"path"`, `commands` containing
  `["M",x,y]`, `["L",x,y]`, `["C",c1x,c1y,c2x,c2y,x,y]`, `["Z"]`.
  `closed:true` requires a final `["Z"]`. Curves and holes stay native.
- Text: `kind:"text"`, `editability:"text"`, `bbox:[x,y,width,height]`.
  Set `text` OR `runs`, never both. Runs are objects with `text` plus optional
  `font_size_pt`, `bold`, `italic`, `color`, `font`, `font_east_asia`,
  `char_spacing_pt`, `baseline:"normal"|"subscript"|"superscript"`. Newlines are `\n`.
  Use a cohesive text object for a line that needs whole-line editing.
  Set script font sizes explicitly from the image; setting `baseline` alone does
  not estimate the intended script size. Do not infer italic solely from a formula.
  Keep adjustable blank groups in separate runs; tracking is in points.
- Group: `kind:"group"`, `editability:"group"`, `children:[objects...]`.
  Children use the same global slide coordinates; no group bbox or style.
- Optional object `rotation` is clockwise degrees. Native effects below cannot
  be combined with rotation, mixed runs, groups or paths in this version.

Shape and path `style` fields:

```json
{
  "fill": "23888B", "line": null, "line_width_pt": 1,
  "fill_alpha": 1, "line_alpha": 1,
  "line_cap": "round", "line_join": "round"
}
```

Colors are six-digit RGB without `#`. Null fill/line means no fill/line.
For an ordinary dashed stroke, set `style.dash:"dash"` on one line or open
path instead of enumerating every short segment. Use `dash:"solid"` or omit it
for a solid stroke. Preset dash spacing is not an exact measured-length claim.
If precise dash/gap lengths are required in a tool-enabled workflow, compile
the `dashed_line` component with measured `dash_length` and `gap_length` in
logical pixels; retain its generated native path. Component specs are not
scene objects and must be compiled before scene validation/build.
Line cap values are `butt`, `round`, `square`; OOXML's `flat` is spelled `butt` here.
An open path normally has `fill:null`. Endpoint arrows use
`begin_arrow` or `end_arrow` with `triangle`, `stealth`, `diamond`, `oval` or `none`;
optional endpoint sizes are `begin_arrow_width`, `begin_arrow_length`,
`end_arrow_width`, `end_arrow_length`, each `sm`, `med` or `lg`.
No invisible covering patches for holes.

A native fill gradient uses `style.gradient`:

```json
{
  "type": "linear",
  "angle_deg": 0,
  "stops": [
    {"position": 0, "color": "FFFFFF", "alpha": 1},
    {"position": 1, "color": "23888B", "alpha": 1}
  ]
}
```

Radial gradients use `type:"radial"` and `center:[0.5,0.5]` instead of angle.
Stops must be uniquely ordered, starting at 0 and ending at 1.
Transparency is 0 through 1. A gradient overrides solid fill.

Native shape shadows use `style.native_format`:

```json
{
  "version": "1",
  "shadow": {
    "enabled": true, "color": "243341", "alpha": 0.25,
    "blur_pt": 5, "dx_pt": 3, "dy_pt": 5
  }
}
```

Blur is 0 through 24 points; offsets are -24 through 24 points.
Use a real native shadow, not repeated translucent silhouettes.

Text style accepts `font`, `font_east_asia`, `font_size_pt`, `bold`, `italic`,
`color`, `align:"left"|"center"|"right"`, `valign:"top"|"middle"|"bottom"`,
`wrap`, `margin_pt`, `char_spacing_pt`, `line_spacing_pt`, `space_before_pt`, `space_after_pt`.
Arial and Microsoft YaHei are available. Default margins are zero and text is
not automatically resized. Keep text independently editable.
All source text, numbers, punctuation, object relationships and visual effects
must be preserved. Similar words or decorative substitutes are not equivalent.
Check visually similar Latin and Greek characters separately. Keep uncertain
transcription unresolved for review instead of treating geometric fit as proof.
