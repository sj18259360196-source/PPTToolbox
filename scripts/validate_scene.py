"""Validate the Agent-authored scene. This does NOT analyze a reference image."""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
from common import read_json, resolve_asset, walk_objects, bbox_to_points

KINDS = {"text", "shape", "line", "connector", "path", "image", "table", "chart", "group"}
ADJUSTMENT_COUNTS = {"rect":0, "round_rect":1, "ellipse":0, "triangle":1,
                     "diamond":0, "chevron":1, "right_arrow":2,
                     "left_right_arrow":2, "star5":3, "arc":2}

def validate(scene: dict, base: Path, check_files: bool = True) -> list[str]:
    import jsonschema
    schema = read_json(Path(__file__).resolve().parents[1] / "assets/schemas/scene.schema.json")
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in
              jsonschema.Draft202012Validator(schema).iter_errors(scene)]
    if errors:
        if any("adjustments" in str(error) for error in errors):
            errors.append("Scene adjustments use normalized values from 0 to 1, not raw "
                          "OOXML integers (for example 0.06, not 6000). "
                          "For round_rect, adjustment = corner radius / shorter bbox side; "
                          "0.5 makes a capsule. The current scene contract excludes "
                          "preset adjustments outside 0..1; use a documented native path.")
        return errors
    c = scene["canvas"]
    try:
        bbox_to_points([0, 0, c["width"], c["height"]], c)
    except ValueError as exc:
        errors.append(str(exc))
    def check_finite(v, path="$", depth=0):
        if depth > 32:
            errors.append(f"{path}: nesting exceeds 32"); return
        if isinstance(v, float) and not math.isfinite(v):
            errors.append(f"{path}: number must be finite")
        elif isinstance(v, dict):
            for k, x in v.items(): check_finite(x, path + "/" + k, depth + 1)
        elif isinstance(v, list):
            for i, x in enumerate(v): check_finite(x, path + f"/{i}", depth + 1)
    check_finite(scene)
    slide_ids = set()
    for slide in scene["slides"]:
        sid = slide["id"]
        if sid in slide_ids: errors.append(f"Duplicate slide ID: {sid}")
        slide_ids.add(sid)
        flat = list(walk_objects(slide["objects"]))
        names = [o["id"] for o in flat]
        if len(names) != len(set(names)): errors.append(f"{sid}: duplicate object ID")
        by_id = {o["id"]: o for o in flat}
        preserved_images = set()
        if 'element_scope' in slide:
            from element_scope import validate_plan, validate_outputs
            try:
                validate_plan(slide['element_scope'], project=base if check_files else None, compiled=True)
                preserved_images = validate_outputs(slide['element_scope'], slide['objects'], base if check_files else None)
            except (ValueError, OSError) as exc:
                errors.append(f'{sid}: {exc}')
        top_ids = {o["id"] for o in slide["objects"]}
        from evidence_contract import required_review
        try: required_review(slide)
        except ValueError as exc: errors.append(f"{sid}: {exc}")
        if not flat: errors.append(f"{sid}: no objects; image analysis has not been completed")
        for o in flat:
            oid, kind = o["id"], o["kind"]
            common_keys = {"id","kind","role","editability","evidence","notes","rotation","allow_offslide"}
            fields = {
                "text":{"bbox","text","runs","paragraphs","style"}, "shape":{"bbox","geometry","adjustments","style"},
                "line":{"points","style"}, "connector":{"points","style","connector_type","begin","end"},
                "path":{"commands","closed","style","native_path_frame"}, "image":{"bbox","asset","fit","mask","source_crop","asset_role","source_kind","provenance","raster_content","raster_reason","generation_decision"},
                "table":{"bbox","rows","column_widths","row_heights","merges","cell_styles","header_fill","style"},
                "chart":{"bbox","chart_type","categories","series","data_provenance","legend","legend_position","axes","chart_title","plot_area","style"}, "group":{"children"}}
            extra = set(o) - common_keys - fields[kind]
            if extra: errors.append(f"{oid}: fields not supported for {kind}: {sorted(extra)}")
            text_styles = {"font","font_east_asia","font_size_pt","bold","italic","color","align","valign","wrap","margin_pt","line_spacing_pt","margin_left_pt","margin_right_pt","margin_top_pt","margin_bottom_pt","space_before_pt","space_after_pt","char_spacing_pt","warp"}
            text_styles.add("text_outline")
            arrow_sizes={side+'_arrow_'+axis for side in ('begin','end') for axis in ('width','length')}
            geometry_styles = {"fill","fill_alpha","line","line_width_pt","dash","gradient","begin_arrow","end_arrow","line_cap","line_join","line_alpha","miter_limit"}|arrow_sizes
            allowed_styles = {"text":text_styles|geometry_styles,"shape":geometry_styles,"path":geometry_styles,
                "line":{"line","line_width_pt","dash","begin_arrow","end_arrow","line_cap","line_join","line_alpha","miter_limit"}|arrow_sizes,
                "connector":{"line","line_width_pt","dash","begin_arrow","end_arrow","line_cap","line_join","line_alpha","miter_limit"}|arrow_sizes,
                "table":text_styles|{"fill","line","line_width_pt"}, "chart":{"font","font_size_pt"}, "image":set(),"group":set()}
            for native_kind in ("shape", "text"):
                allowed_styles[native_kind].add("native_format")
            if "native_format" in o.get("style", {}):
                from native_capabilities import validate_format
                try:
                    validate_format(o["style"]["native_format"], kind)
                    if "runs" in o or "paragraphs" in o or o.get("rotation", 0):
                        raise ValueError("Native effects currently exclude mixed runs and rotated objects")
                except ValueError as exc:
                    errors.append(f"{oid}: {exc}")
            unused=set(o.get("style",{}))-allowed_styles[kind]
            if kind in {"path","shape","line","connector"}:
                unused.discard("line_gradient")
            if unused: errors.append(f"{oid}: styles not implemented for {kind}: {sorted(unused)}")
            line_grad=o.get("style",{}).get("line_gradient")
            if line_grad:
                positions=[s["position"] for s in line_grad["stops"]]
                if line_grad.get("type","linear")!="linear" or "center" in line_grad or "path" in line_grad:
                    errors.append(f"{oid}: line gradients support only spatial linear gradients")
                if positions!=sorted(set(positions)) or positions[0]!=0 or positions[-1]!=1 or len(positions)>5:
                    errors.append(f"{oid}: line gradient requires 2..5 ordered stops from 0 to 1")
            grad=o.get("style",{}).get("gradient")
            if grad:
                positions=[s["position"] for s in grad['stops']]
                if positions != sorted(set(positions)) or positions[0] != 0 or positions[-1] != 1:
                    errors.append(f"{oid}: fill gradient requires unique ordered stops from 0 to 1")
            if grad and grad.get("type","linear")=="linear" and "center" in grad:
                errors.append(f"{oid}: center is only meaningful for a radial gradient")
            if grad and grad.get("type","linear")=="linear" and "path" in grad:
                errors.append(f"{oid}: path is only meaningful for a radial gradient")
            expected_edit={"text":"text","shape":"shape","line":"shape","connector":"shape","path":"path","image":"image_replace","table":"table","chart":"data_chart","group":"group"}
            if o["editability"]!=expected_edit[kind]: errors.append(f"{oid}: editability does not match kind")
            if kind=="group" and not o.get("children"): errors.append(f"{oid}: empty group")
            if kind in {'table','chart'} and oid not in top_ids: errors.append(f"{oid}: bundled builder supports table/chart at slide root only; grouped data objects require a separate tested adapter")
            if kind=="chart" and "chart_type" not in o: errors.append(f"{oid}: chart_type required")
            if kind=="image":
                for required in ("asset_role","source_kind"):
                    if required not in o: errors.append(f"{oid}: {required} required")
                if 'raster_content' in o:
                    from material_routes import generated_illustration
                    exception=False
                    try:exception=generated_illustration(o,base if check_files else None) or oid in preserved_images
                    except (ValueError,OSError) as exc:errors.append(f"{oid}: {exc}")
                    if o.get('asset_role') in {'icon','logo'} and not exception:
                        errors.append(f"{oid}: icons/logos require native paths or shapes, not raster substitution")
                    if len(o.get('raster_reason','').strip()) < 12:
                        errors.append(f"{oid}: explain the actual photographic/texture detail requiring raster storage")
                    if o.get('raster_content') == 'reference_artifact' and oid not in preserved_images:
                        errors.append(f'{oid}: reference_artifact requires a source-bound preservation decision')
            if kind in {"text", "shape", "image", "table", "chart"} and "bbox" not in o:
                errors.append(f"{sid}/{oid}: bbox required")
            if "bbox" in o:
                x,y,w,h = o["bbox"]
                if w <= 0 or h <= 0: errors.append(f"{sid}/{oid}: nonpositive box")
                if not o.get("allow_offslide", False) and (x < -1e-5 or y < -1e-5 or x+w > c["width"]+1e-5 or y+h > c["height"]+1e-5):
                    errors.append(f"{sid}/{oid}: bbox outside logical canvas; fix or explicitly document allow_offslide")
            if kind == "text":
                if not any(k in o for k in ("text","runs","paragraphs")): errors.append(f"{oid}: missing text/runs/paragraphs")
                if sum(k in o for k in ("text","runs","paragraphs"))>1: errors.append(f"{oid}: specify text OR runs OR paragraphs")
            if kind == "shape" and "geometry" not in o: errors.append(f"{oid}: missing geometry")
            if kind == "shape" and "adjustments" in o and "geometry" in o:
                count = ADJUSTMENT_COUNTS[o["geometry"]]
                if len(o["adjustments"]) > count:
                    errors.append(f"{oid}: {o['geometry']} supports at most {count} "
                                  "adjustments; excess values would fail during build")
                if o["geometry"] == "round_rect" and o["adjustments"] and o["adjustments"][0] > .5:
                    errors.append(f"{oid}: round_rect adjustment must be 0..0.5 "
                                  "(corner radius divided by shorter side)")
            if kind == "image":
                if "source_crop" in o:
                    cx,cy,cw,ch=o["source_crop"]
                    if cx<0 or cy<0 or cw<=0 or ch<=0:
                        errors.append(f"{oid}: source_crop requires nonnegative origin and positive size")
                    if o.get("fit")!="stretch":
                        errors.append(f"{oid}: source_crop requires explicit fit=stretch; bbox sets crop display size")
                if "asset" not in o: errors.append(f"{oid}: missing asset")
                elif check_files:
                    try:
                        p=resolve_asset(base,o["asset"])
                        if p.suffix.lower() in {".svg", ".emf", ".wmf"}:
                            errors.append(f"{oid}: bundled builder accepts raster images only; use documented Office adapter for SVG/vector insertion")
                        elif "source_crop" in o:
                            from PIL import Image
                            with Image.open(p) as im: iw,ih=im.size
                            if cx+cw>iw or cy+ch>ih:
                                errors.append(f"{oid}: source_crop exceeds source raster dimensions {iw}x{ih}")
                    except (ValueError, FileNotFoundError) as exc: errors.append(f"{oid}: {exc}")
                if o.get("asset_role") == "reference_fullpage": errors.append(f"{oid}: full reference image forbidden in deliverable")
                if o.get("source_kind") in {"generated","external"} and not o.get("provenance"):
                    errors.append(f"{oid}: generated/external asset needs provenance")
            if kind in {"line","connector"} and "points" not in o: errors.append(f"{oid}: needs two endpoint points")
            if kind == "connector":
                if oid not in top_ids: errors.append(f"{oid}: bundled builder requires connectors at slide root")
                for endpoint in ("begin","end"):
                    if endpoint not in o: continue
                    target = o[endpoint]["object_id"]
                    if target not in by_id: errors.append(f"{oid}: unknown {endpoint} target {target}")
                    elif target not in top_ids or by_id[target]["kind"] not in {"text","shape"}:
                        errors.append(f"{oid}: bundled auto-attachment supports root text/shape targets only")
            if kind == "path":
                if not o.get("commands") or o["commands"][0][0] != "M": errors.append(f"{oid}: path must start with M")
                for command in o.get("commands",[]):
                    n={"M":3,"L":3,"C":7,"Z":1}.get(command[0])
                    if n is None or len(command)!=n: errors.append(f"{oid}: invalid path command {command}")
                    elif any(not isinstance(v,(int,float)) or isinstance(v,bool) for v in command[1:]): errors.append(f"{oid}: path coordinates must be numeric")
                if o.get("closed") and o.get("commands",[])[-1][0] != "Z": errors.append(f"{oid}: closed path must end with Z")
            if kind == "table":
                rows=o.get("rows",[])
                if not rows or not rows[0]: errors.append(f"{oid}: empty table")
                elif any(len(r)!=len(rows[0]) for r in rows): errors.append(f"{oid}: inconsistent column counts")
                widths=o.get("column_widths")
                if widths and rows and len(widths)!=len(rows[0]): errors.append(f"{oid}: column_widths count mismatch")
                if widths and abs(sum(widths)-o["bbox"][2])>1e-5: errors.append(f"{oid}: column widths must sum to bbox width")
            if kind == "chart":
                if not o.get("series"): errors.append(f"{oid}: empty series")
                if o.get("chart_type") == "xy":
                    for s in o.get("series",[]):
                        if not s.get("points"): errors.append(f"{oid}: xy series missing points")
                else:
                    if not o.get("categories"): errors.append(f"{oid}: missing categories")
                    for s in o.get("series",[]):
                        if len(s.get("values",[]))!=len(o.get("categories",[])): errors.append(f"{oid}: data/category count mismatch")
                if not o.get("data_provenance"): errors.append(f"{oid}: data provenance required")
    from native_extensions import validate_extensions
    errors.extend(validate_extensions(scene))
    return errors

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("scene",type=Path)
    a=ap.parse_args()
    try:
        issues=validate(read_json(a.scene),a.scene.resolve().parent)
    except Exception as exc:
        print(f"Validation failed: {exc}",file=sys.stderr); return 2
    print(json.dumps({"status":"failed" if issues else "passed","findings":issues},ensure_ascii=False,indent=2))
    return 1 if issues else 0
if __name__=="__main__": raise SystemExit(main())
