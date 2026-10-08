"""Bounded, isolated SVG conversion. The worker has no library or project writes."""
from __future__ import annotations
import base64
import json
import subprocess
import sys
from pathlib import Path


def prepare(svg, timeout=20):
    if not isinstance(svg,str) or len(svg.encode('utf-8'))>400000:
        raise ValueError('SVG 必须小于 400KB')
    try:
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve())],
            input=json.dumps({'svg':svg}),capture_output=True,text=True,encoding='utf-8',
            timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Artwork preflight timed out; read-only worker stopped; no library write started') from exc
    if result.returncode:
        raise ValueError('Artwork worker failed: '+result.stderr[-1200:])
    value=json.loads(result.stdout)
    if not value.get('supported'):
        raise ValueError(value.get('error','Unsupported artwork'))
    return value


def inspect_svg(svg):
    try:
        value=prepare(svg)
        return {'supported':True,'part_count':len(value['ir']['parts']),
                'node_count':sum(len(p['commands']) for p in value['ir']['parts']),
                'conversion':'native_paths','text_editability':'no_text_objects',
                'retained':False,'office':'not_run'}
    except ValueError as exc:
        return {'supported':False,'issues':[str(exc)],'retained':False,'office':'not_run',
                'conversion':'not_performed','guidance':'保留原始 SVG。文字转轮廓会失去文字编辑能力；渐变拆色会增加节点。'}


def worker(svg):
    from toolbox_manager.icons.geometry import compile_svg,svg_from_ir,render,scene_group
    import io
    import numpy as np
    from PIL import Image
    ir=compile_svg(svg);normalized=svg_from_ir(ir);png=render(normalized)
    original=render(svg)
    a=Image.open(io.BytesIO(original)).convert('RGBA').resize((256,256))
    b=Image.open(io.BytesIO(png)).convert('RGBA').resize((256,256))
    errors={}
    for color in ('white','black'):
        aa=Image.new('RGBA',a.size,color);aa.alpha_composite(a)
        bb=Image.new('RGBA',b.size,color);bb.alpha_composite(b)
        errors[color]=round(float(np.abs(np.array(aa,dtype=float)-np.array(bb,dtype=float)).mean()/255),6)
    return {'supported':True,'ir':ir,'normalized':normalized,'png':base64.b64encode(png).decode(),
            'scene_fragment':scene_group(ir),'structural':{'source_hash_ok':True,
            'native_path_count':len(ir['parts']),'raster_objects':0,'svg_conversion_pixel_mae':errors,
            'office':'not_run','visual_review':'pending','semantic_review':'pending','reference_pixel_mae':None}}


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    try:
        request=json.loads(sys.stdin.read(2400001))
        result=worker(request['svg'])
    except Exception as exc:result={'supported':False,'error':str(exc)}
    print(json.dumps(result,ensure_ascii=True))
