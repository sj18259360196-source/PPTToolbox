"""Restricted SVG -> normalized editable paths. Reject unsupported rendering."""
from __future__ import annotations
import copy, io, math, re
from lxml import etree as ET
from PIL import Image
import svgelements as se
import resvg_py

NS = 'http://www.w3.org/2000/svg'
TAGS = {'svg','g','path','rect','circle','ellipse','line','polyline','polygon','title','desc'}
ATTRS = {'id','viewBox','width','height','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','d','points',
         'fill','stroke','stroke-width','fill-rule','stroke-linecap','stroke-linejoin','stroke-miterlimit',
         'fill-opacity','stroke-opacity','opacity','transform','version','color','preserveAspectRatio',
         'display','visibility','class','role','aria-hidden','aria-label','focusable'}

def sanitize(svg):
    if not isinstance(svg,str) or len(svg.encode()) > 400000:
        raise ValueError('SVG 必须小于 400KB')
    if re.search(r'<!DOCTYPE|<!ENTITY|<\?',svg,re.I):
        # Ordinary XML declaration is safe, external processing instructions are not.
        svg = re.sub(r'^\s*<\?xml\s[^?]*\?>','',svg)
        if re.search(r'<!DOCTYPE|<!ENTITY|<\?',svg,re.I): raise ValueError('不支持 SVG 外部实体或处理指令')
    root=ET.fromstring(svg.encode(),ET.XMLParser(resolve_entities=False,no_network=True))
    if ET.QName(root).localname!='svg': raise ValueError('需要 SVG 根元素')
    nodes=list(root.iter())
    if len(nodes)>1200: raise ValueError('SVG 元素超过 1200 个，请先简化')
    for e in nodes:
        if not isinstance(e.tag,str):
            if e.getparent() is not None:e.getparent().remove(e)
            continue
        tag=ET.QName(e).localname
        if tag in {'metadata','namedview','defs'}:
            if e.getparent() is not None:e.getparent().remove(e)
            continue
        if any(ET.QName(a).localname in {'metadata','namedview','defs'} for a in e.iterancestors()):continue
        if tag not in TAGS: raise ValueError('暂不支持 SVG 元素 '+tag)
        styles=e.attrib.pop('style','')
        for declaration in styles.split(';'):
            if not declaration.strip():continue
            key,sep,value=declaration.partition(':')
            if not sep:raise ValueError('无效 SVG 样式')
            e.set(key.strip(),value.strip())
        for key,value in list(e.attrib.items()):
            q=ET.QName(key)
            if q.namespace:
                if q.localname=='label':e.set('id',value)
                del e.attrib[key];continue
            if key in {'clip-rule','enable-background'}:
                # No clipping or filters are accepted, so these have no effect.
                del e.attrib[key];continue
            if key in {'stroke-dasharray','clip-path','filter','mask'} and value.strip()=='none':
                # Explicitly disabled effects have the same rendering as absence.
                del e.attrib[key];continue
            if key not in ATTRS:raise ValueError('暂不支持 SVG 属性 '+key)
            if re.search(r'url\s*\(|javascript:|!important',value,re.I):raise ValueError('不支持 SVG 外部资源或绘制引用')
        if tag in {'g','svg'} and float(e.get('opacity','1')) != 1:
            raise ValueError('请将分组透明度展开到部件后导入')
        if e.get('fill-rule','nonzero') not in {'nonzero','evenodd'}:raise ValueError('无效填充规则')
        if e.get('display') not in {None,'none','inline'}:raise ValueError('不支持此 display')
        if e.get('visibility') not in {None,'visible','hidden'}:raise ValueError('不支持此 visibility')
        for key in ('class','role','aria-hidden','aria-label','focusable'):e.attrib.pop(key,None)
    vb=root.get('viewBox')
    if vb:
        dims=[float(v) for v in re.split(r'[ ,]+',vb.strip())]
        if len(dims)!=4:raise ValueError('无效 viewBox')
    else:
        dims=[0,0,float(root.get('width','24')),float(root.get('height','24'))]
    if not all(math.isfinite(n) and abs(n)<=100000 for n in dims) or min(dims[2:])<=0:
        raise ValueError('无效 SVG 尺寸')
    # One coordinate space independent of physical units in downloaded SVGs.
    root.set('viewBox',' '.join(map(str,dims)))
    root.set('width',str(dims[2]));root.set('height',str(dims[3]))
    root.set('color',root.get('color','#222222'))
    return ET.tostring(root,encoding='unicode'),dims

def _paint(color,opacity):
    if color is None or color.value is None:return None,1.0
    return f'{color.red:02X}{color.green:02X}{color.blue:02X}',color.alpha/255*float(opacity)

def _evenodd(path):
    """Orient nested simple contours for DrawingML nonzero fill; preserve curves."""
    subs=[se.Path(s) for s in path.as_subpaths()]
    if len(subs)<2:return path
    from shapely.geometry import Polygon
    polygons=[]
    for sub in subs:
        pts=[]
        for seg in sub:
            if isinstance(seg,se.Move):continue
            steps=24 if isinstance(seg,(se.CubicBezier,se.QuadraticBezier)) else 1
            pts.extend([(seg.point(i/steps).x,seg.point(i/steps).y) for i in range(steps+1)])
        poly=Polygon(pts)
        if not poly.is_valid:raise ValueError('交叠或自交的奇偶填充需要先整理轮廓')
        polygons.append(poly)
    for i,sub in enumerate(subs):
        depth=sum(j!=i and p.contains(polygons[i]) for j,p in enumerate(polygons))
        if bool(polygons[i].exterior.is_ccw) != (depth%2==0):sub.reverse()
    result=se.Path()
    for sub in subs:result+=sub
    return result

def compile_svg(svg):
    clean,dims=sanitize(svg)
    parsed=se.SVG.parse(io.StringIO(clean),reify=True)
    parts=[]
    for element in parsed.elements():
        if not isinstance(element,se.Shape):continue
        if element.values.get('visibility')=='hidden' or element.values.get('display')=='none':continue
        p=se.Path(element);p.reify();p.approximate_arcs_with_cubics()
        if not len(p):continue
        fill,fa=_paint(p.fill,p.values.get('fill-opacity',1))
        stroke,sa=_paint(p.stroke,p.values.get('stroke-opacity',1))
        opacity=float(p.values.get('opacity',1));fa*=opacity;sa*=opacity
        if fill is None and stroke is None:continue
        bounds=p.bbox()
        if bounds and (bounds[0]<-0.5 or bounds[1]<-0.5 or bounds[2]>dims[2]+0.5 or bounds[3]>dims[3]+0.5):
            raise ValueError('路径超出 viewBox，原生转换不能隐式裁切，请先整理画布')
        if fill is not None and p.values.get('fill-rule')=='evenodd':p=_evenodd(p)
        commands=[]
        for seg in p:
            if isinstance(seg,se.Move):commands.append(['M',seg.end.x,seg.end.y])
            elif isinstance(seg,se.Close):commands.append(['Z'])
            elif isinstance(seg,se.Line):commands.append(['L',seg.end.x,seg.end.y])
            elif isinstance(seg,se.CubicBezier):commands.append(['C',seg.control1.x,seg.control1.y,seg.control2.x,seg.control2.y,seg.end.x,seg.end.y])
            elif isinstance(seg,se.QuadraticBezier):
                c1=seg.start+2/3*(seg.control-seg.start);c2=seg.end+2/3*(seg.control-seg.end)
                commands.append(['C',c1.x,c1.y,c2.x,c2.y,seg.end.x,seg.end.y])
            else:raise ValueError('未转换的路径指令 '+type(seg).__name__)
        if len(commands)>4000:raise ValueError('单个部件节点过多，请简化后重试')
        if not all(math.isfinite(v) and abs(v)<1e7 for c in commands for v in c[1:]):raise ValueError('无效路径坐标')
        if fill is not None and commands[-1][0]!='Z':
            # SVG implicitly closes fill but not stroke. Preserve these separately.
            if stroke is not None:raise ValueError('同时填充和描边的开放路径请显式闭合或拆分')
            commands.append(['Z'])
        cap=p.values.get('stroke-linecap','butt');join=p.values.get('stroke-linejoin','miter')
        if cap not in {'butt','round','square'} or join not in {'miter','round','bevel'}:raise ValueError('不支持此描边样式')
        parts.append({'name':str(element.values.get('id') or f'part-{len(parts)+1}'), 'commands':commands,
            'fill':fill,'fill_alpha':fa,'line':stroke,'line_alpha':sa,'stroke_width':float(p.stroke_width or 0),
            'line_cap':cap,'line_join':join,'miter_limit':float(p.values.get('stroke-miterlimit',4))})
    if not parts:raise ValueError('SVG 中没有可见可编辑部件')
    if sum(len(p['commands']) for p in parts)>12000:raise ValueError('图标节点总数超过 12000')
    return {'format':'editable-icon/1','width':dims[2],'height':dims[3],'parts':parts,'source_svg':clean}

def svg_from_ir(ir,color=None,stroke_width=None):
    root=ET.Element('svg',nsmap={None:NS},viewBox=f"0 0 {ir['width']} {ir['height']}")
    for p in ir['parts']:
        values={'id':p['name'],'d':' '.join(c[0]+' '+' '.join(f'{n:.7g}' for n in c[1:]) for c in p['commands']),
            'fill':'#'+(color or p['fill']) if p['fill'] else 'none',
            'stroke':'#'+(color or p['line']) if p['line'] else 'none',
            'fill-opacity':str(p['fill_alpha']),'stroke-opacity':str(p['line_alpha']),
            'stroke-width':str(stroke_width if stroke_width is not None else p['stroke_width']),
            'stroke-linecap':p['line_cap'],'stroke-linejoin':p['line_join'],'stroke-miterlimit':str(p['miter_limit'])}
        ET.SubElement(root,'path',**values)
    return ET.tostring(root,encoding='unicode')

def render(svg,size=256):
    clean,dims=sanitize(svg)
    # resvg 0.2's simultaneous width/height leaves non-square images top-left.
    # Render at native aspect and explicitly center in a transparent square.
    kw={'width':size} if dims[2]>=dims[3] else {'height':size}
    # Accepted SVGs contain paths only; scanning installed fonts is unnecessary.
    raw=resvg_py.svg_to_bytes(svg_string=clean,skip_system_fonts=True,**kw)
    im=Image.open(io.BytesIO(raw)).convert('RGBA');im.thumbnail((size,size))
    canvas=Image.new('RGBA',(size,size),(0,0,0,0));canvas.alpha_composite(im,((size-im.width)//2,(size-im.height)//2))
    out=io.BytesIO();canvas.save(out,format='PNG');return out.getvalue()

def scene_group(ir,box=(0,0,240,240),prefix='icon',color=None,stroke_width=None,points_per_unit=1):
    if color is not None and not re.fullmatch('[0-9a-fA-F]{6}',color):raise ValueError('颜色需要 6 位十六进制')
    if stroke_width is not None and not 0<float(stroke_width)<=100:raise ValueError('线宽必须在 0 到 100 之间')
    x,y,w,h=map(float,box);scale=min(w/ir['width'],h/ir['height'])
    if not all(math.isfinite(v) for v in (x,y,w,h)) or min(w,h)<=0:raise ValueError('需要有效放置范围')
    x+=(w-ir['width']*scale)/2;y+=(h-ir['height']*scale)/2
    evidence={'status':'inferred','note':'Versioned SVG conversion; visual review required for this placement'}
    children=[]
    for index,p in enumerate(ir['parts']):
        commands=[[c[0],*[round(v*scale+(x if i%2==0 else y),7) for i,v in enumerate(c[1:])]] for c in p['commands']]
        style={k:p[k] for k in ('fill','fill_alpha','line','line_alpha','line_cap','line_join','miter_limit')}
        if color:
            for k in ('fill','line'):
                if style[k]:style[k]=color
        style['line_width_pt']=(float(stroke_width) if stroke_width is not None else p['stroke_width'])*scale*points_per_unit
        part_name=re.sub(r'[^\w-]','_',p['name'])[:30]
        children.append({'id':f'{prefix}.{index+1:03d}.{part_name}', 'role':p['name'],'kind':'path','editability':'path',
                         'evidence':evidence,'commands':commands,'closed':p['fill'] is not None,'style':style})
    return {'id':prefix,'kind':'group','editability':'group','evidence':evidence,'children':children}

def fingerprint(png):
    """Appearance descriptor, not a semantic embedding or an acceptance score."""
    im=Image.open(io.BytesIO(png)).convert('RGBA');im.thumbnail((30,30))
    bg=Image.new('RGBA',(32,32),'white');bg.alpha_composite(im,((32-im.width)//2,(32-im.height)//2))
    return [round(1-value/255.0,4) for value in bg.convert('L').tobytes()]


def _protect_small_mask_components(mask, sampled):
    """Keep <=4-pixel islands/holes opaque while smoothing larger boundaries."""
    width,height=mask.size; data=mask.convert('L').tobytes()
    seen=bytearray(len(data)); protected=0
    for start in range(len(data)):
        if seen[start]:continue
        value=data[start]; stack=[start]; seen[start]=1; small=[]; count=0
        while stack:
            index=stack.pop();count+=1
            if count<=4:small.append(index)
            x=index%width;y=index//width
            neighbours=[]
            if x:neighbours.append(index-1)
            if x+1<width:neighbours.append(index+1)
            if y:neighbours.append(index-width)
            if y+1<height:neighbours.append(index+width)
            for neighbour in neighbours:
                if not seen[neighbour] and data[neighbour]==value:
                    seen[neighbour]=1;stack.append(neighbour)
        if count<=4:
            protected+=1
            for index in small:
                x=index%width;y=index//width
                sampled.paste(value,(x*3,y*3,x*3+3,y*3+3))
    return protected


def trace_mask_fragment(png, box, prefix, color, semantic_name, smoothing='none',
                        simplify_error_px=0):
    """Trace an explicitly segmented small mask, never a full-color reference."""
    import hashlib
    import vtracer
    if smoothing not in {'none','curves'}:
        raise ValueError('Unknown contour smoothing mode')
    if (type(simplify_error_px) not in (int, float) or not math.isfinite(simplify_error_px)
            or simplify_error_px != 0 and not .05 <= simplify_error_px <= .5):
        raise ValueError('simplify_error_px must be 0 or 0.05..0.5 mask pixels')
    if simplify_error_px and smoothing != 'curves':
        raise ValueError('Contour simplification requires curves smoothing')
    mask = Image.open(io.BytesIO(png))
    if max(mask.size) > 512 or min(mask.size) < 2:
        raise ValueError('轮廓蒙版尺寸须在 2 到 512 像素之间')
    mask = mask.convert('RGBA')
    pixels = list(mask.get_flattened_data() if hasattr(mask, 'get_flattened_data') else mask.getdata())
    if set(pixels) != {(0, 0, 0, 255), (255, 255, 255, 255)}:
        raise ValueError('先分离一个语义部件，提供不透明黑白二值蒙版；黑色为轮廓，白色为背景与孔洞')
    # Keep one-pixel islands and holes during spline fitting. Placement still
    # uses the original aspect ratio; this adds no invented reference detail.
    if smoothing == 'curves':
        sampled = mask.convert('L').resize((mask.width*3, mask.height*3), Image.Resampling.BILINEAR)
        sampled = sampled.point(lambda value: 0 if value < 128 else 255)
        protected = _protect_small_mask_components(mask, sampled)
        sampled = sampled.convert('RGBA')
    else:
        protected = 0
        sampled = mask.resize((mask.width*3, mask.height*3), Image.Resampling.NEAREST)
    values = list(sampled.get_flattened_data() if hasattr(sampled, 'get_flattened_data') else sampled.getdata())
    svg = vtracer.convert_pixels_to_svg(values, sampled.size, colormode='binary',
        hierarchical='cutout', mode='spline', filter_speckle=1,
        corner_threshold=60 if smoothing=='curves' else 30,
        length_threshold=2 if smoothing=='curves' else 1, max_iterations=10,
        splice_threshold=45 if smoothing=='curves' else 20, path_precision=3)
    ir = compile_svg(svg)
    simplification = {'status': 'disabled'}
    if simplify_error_px:
        from scripts.graphics_simplify import simplify_filled
        combined = [command for part in ir['parts'] for command in part['commands']]
        if len(combined) > 96:
            simplification = {'status': 'unchanged', 'reason': 'command_budget'}
        else:
            revised, simplification = simplify_filled(
                combined, simplify_error_px*3, protected_area=4*9)
            if simplification['status'] == 'simplified':
                rings = []
                for command in revised:
                    if command[0] == 'M':
                        rings.append([])
                    rings[-1].append(command)
                offset = 0
                for part in ir['parts']:
                    count = sum(c[0] == 'M' for c in part['commands'])
                    part['commands'] = [c for ring in rings[offset:offset+count] for c in ring]
                    offset += count
            simplification['boundary_error_bound_mask_px'] = simplification.pop('boundary_error_bound')/3
        simplification['requested_error_mask_px'] = simplify_error_px
        simplification['scope'] = 'Relative to the traced draft, not to the source image; actual Office review required.'
    fragment = scene_group(ir, box, prefix, color)
    fragment['role'] = semantic_name
    fragment['evidence']['note'] = 'Explicit semantic binary mask; native contour draft. Actual Office visual review required.'
    return {'scene_fragment': fragment, 'normalized_mask_sha256': hashlib.sha256(png).hexdigest(),
        'mask_size': list(mask.size), 'parts': len(ir['parts']),
        'commands': sum(len(p['commands']) for p in ir['parts']),
        'sampling': '3x bilinear thresholded spline' if smoothing=='curves' else '3x nearest-neighbor binary spline',
        'smoothing': smoothing, 'visual_review': 'pending',
        'simplification': simplification,
        'protected_small_components': protected,
        'warnings': ['曲线模式会圆化边缘；检查狭窄部件、孔洞和尖角，勿用于文字或像素图。'] if smoothing=='curves' else [],
        'scope': '仅返回当前项目可用的原生轮廓草稿，不写入全局素材库。须核对语义、孔洞、细部和实际 Office 渲染。'}
