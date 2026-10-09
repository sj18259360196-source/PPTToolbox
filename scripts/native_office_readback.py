"""Explicit read-only COM members. Missing properties stay unknown."""


def measured(reader):
    try:
        return {"status": "read", "value": reader()}
    except Exception as exc:
        return {"status": "unknown", "error_type": type(exc).__name__}


def transparency(value):
    value=float(value)
    if not 0<=value<=1:raise ValueError('Mixed or unavailable Office transparency')
    return value


def read_fill(fill):
    result = {"type": measured(lambda: int(fill.Type))}
    result["transparency"] = measured(lambda: transparency(fill.Transparency))
    result['alpha']=measured(lambda:1-transparency(fill.Transparency))
    if result['type'].get('value')==1:
        result['rgb_bgr_integer']=measured(lambda:int(fill.ForeColor.RGB))
    if result["type"].get("value") == 3:
        result["stops"] = measured(lambda: [
            {"position": float(fill.GradientStops.Item(i).Position),
             "transparency": transparency(fill.GradientStops.Item(i).Transparency),
             "alpha": 1-transparency(fill.GradientStops.Item(i).Transparency),
             "rgb_bgr_integer": int(fill.GradientStops.Item(i).Color.RGB)}
            for i in range(1, int(fill.GradientStops.Count)+1)])
        result["angle_deg"] = measured(lambda: float(fill.GradientAngle))
    return result


def read_shadow(shadow):
    return {"visible": measured(lambda: int(shadow.Visible)),
            "blur_pt": measured(lambda: float(shadow.Blur)),
            "dx_pt": measured(lambda: float(shadow.OffsetX)),
            "dy_pt": measured(lambda: float(shadow.OffsetY)),
            "transparency": measured(lambda: transparency(shadow.Transparency))}


def read_shape(shape):
    result = {"fill": measured(lambda: read_fill(shape.Fill)),
              "shadow": measured(lambda: read_shadow(shape.Shadow)),
              "three_d": measured(lambda: {
                  "visible": int(shape.ThreeD.Visible), "depth_pt": float(shape.ThreeD.Depth),
                  "material_id": int(shape.ThreeD.PresetMaterial),
                  "bevel_top_id": int(shape.ThreeD.BevelTopType),
                  "bevel_bottom_id": int(shape.ThreeD.BevelBottomType),
                  "bevel_top_depth_pt": float(shape.ThreeD.BevelTopDepth),
                  "bevel_top_inset_pt": float(shape.ThreeD.BevelTopInset),
                  "rotation_x_deg": float(shape.ThreeD.RotationX),
                  "rotation_y_deg": float(shape.ThreeD.RotationY),
                  "rotation_z_deg": float(shape.ThreeD.RotationZ)})}
    if shape.HasTextFrame and str(shape.TextFrame.TextRange.Text):
        tf = shape.TextFrame2
        from native_text_range import read_com
        result.update(text_fill=measured(lambda: read_fill(tf.TextRange.Font.Fill)),
                      text_shadow=measured(lambda: read_shadow(tf.TextRange.Font.Shadow)),
                      text_outline=measured(lambda: {
                          "visible": int(tf.TextRange.Font.Line.Visible),
                          "width_pt": float(tf.TextRange.Font.Line.Weight)}),
                      warp_id=measured(lambda: int(tf.WarpFormat)),
                      path_id=measured(lambda: int(tf.PathFormat)),
                      character_ranges=measured(lambda: read_com(tf)),
                      actual_font_resolution="unknown_per_glyph")
    if int(shape.Type)==5:
        def nodes():
            count=int(shape.Nodes.Count)
            if count>512:raise ValueError('Node readback budget exceeded')
            return [{'index':i,'points_pt':[[float(v) for v in row] for row in shape.Nodes.Item(i).Points],
                     'segment_type':measured(lambda i=i:int(shape.Nodes.Item(i).SegmentType)),
                     'editing_type':measured(lambda i=i:int(shape.Nodes.Item(i).EditingType))}
                    for i in range(1,count+1)]
        result['nodes']=measured(nodes)
    else:
        result['nodes']={'status':'not_applicable','reason':'not a freeform shape'}
    return result
