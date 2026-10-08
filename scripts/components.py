"""Parameterised native components. Pure geometry; no LLM, rasterisation, or Office calls.
The returned primitives are accepted by the existing scene builder and review chain.
All geometry is in the caller's logical units (regional tasks use local reference px).
"""
from __future__ import annotations
import copy
import math
import re

CATALOG = {
    'dashed_line': {'title':'按段长与间隔制作虚线', 'params':{'dash_length':4,'gap_length':2,'axis':'horizontal'}, 'editability':'path', 'note':'Lengths use bbox logical units. Horizontal/vertical centerline, clipped final dash, at most 512 dashes. One native open path; not an attached connector or a live repeat constraint.'},
    'rounded_rect': {'title':'按半径制作圆角矩形', 'params':{'radius':8}, 'editability':'shape', 'note':'Radius uses the same logical/local-px units as bbox. Native round_rect with an explicit normalized adjustment; no raster or covering patches.'},
    'native_folded_banner': {'title':'折角渐变条幅', 'params':{'text':'Banner','color_start':'26765C','color_end':'A9DCD3'}, 'editability':'group', 'note':'Native folded paths and independent text; synthetic recipe, Office validation recorded separately.'},
    'native_overlap_regions': {'title':'可分别改色的交叠分区图', 'params':{'color_a':'26765C','color_b':'3A99AA','color_overlap':'B8DBD1'}, 'editability':'group', 'note':'Existing polygon Fragment backend; independent editable pieces, not dynamic Boolean recomputation.'},
    'native_effect_title': {'title':'可改字的渐变描边投影标题', 'params':{'text':'Native title','color_start':'26765C','color_end':'A9DCD3','font_size_pt':32}, 'editability':'text', 'note':'Whole single-run glyph effects; no arbitrary rich-text claim.'},
    'native_arch_title': {'title':'可改字的弧形标题', 'params':{'text':'Editable arch','color_start':'26765C','color_end':'A9DCD3','font_size_pt':32,'warp':'textArchUp'}, 'editability':'text', 'note':'Only textArchUp/textArchDown presets; actual geometry and text edits require Office review.'},
    'native_depth_label': {'title':'可调厚度倒角材质的立体标签', 'params':{'text':'Native label','depth_pt':12,'bevel_pt':3,'material':'matte'}, 'editability':'group', 'note':'Front-camera shape3D plus independent flat editable text; no text3D claim.'},
    'flat_semicircle': {'title':'平底半圆', 'params':{}, 'editability':'path', 'note':'Top is a half ellipse; bottom is a straight native path, never a capsule.'},
    'annular_sector': {'title':'环形扇区', 'params':{'inner_ratio':0.66,'start_deg':0,'sweep_deg':90}, 'editability':'path','note':'Positive angles are clockwise in slide coordinates; hole is an actual reverse path.'},
    'segmented_ring': {'title':'独立分区环带', 'params':{'inner_ratio':0.66,'segments':4,'gap_deg':3,'start_deg':0,'colors':['BEDDEB','8DBDD8','6FA1C5','A9D3E8']}, 'editability':'group','note':'Each sector is editable; geometry is not a stack of opaque circles.'},
    'notched_card': {'title':'切角卡片', 'params':{'cut_ratio':0.18}, 'editability':'path','note':'Native polygon with upper-right corner cut; no opaque covering patch.'},
    'double_arrow': {'title':'双向宽箭头', 'params':{'head_fraction':0.20,'shaft_fraction':0.32}, 'editability':'path','note':'Both arrowheads are explicit contour points; endpoints do not auto-follow nodes.'},
    'feedback_curve': {'title':'U形反馈曲线', 'params':{'bidirectional':False}, 'editability':'path','note':'Explicit cubic controls and endpoint styles; no automatic reroute.'},
    'icon_node': {'title':'图标与独立文字节点', 'params':{'label':'','value':'','description':'','icon_asset':None,'icon_provenance':None,'icon_source':'user'}, 'editability':'group','note':'Label/value/description remain independent text; icon may be an explicitly replaceable image.'},
    'photo_window': {'title':'原生异形图片窗口', 'params':{'asset':None,'provenance':None,'source_kind':'user','mask':'ellipse','cut_ratio':0.18}, 'editability':'image_replace','note':'Native p:pic with custom geometry and crop; no pre-flattening of neighbouring text.'}
}


def number(v, label, low=None, high=None, positive=False):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
        raise ValueError(f'{label}: finite number required')
    if positive and v<=0 or low is not None and v<low or high is not None and v>high:
        raise ValueError(f'{label}: out of allowed range')
    return float(v)


def _base(oid, kind, role, evidence):
    return {'id':oid,'kind':kind,'role':role,'editability':{'path':'path','group':'group','shape':'shape','text':'text','image':'image_replace'}[kind], 'evidence':copy.deepcopy(evidence)}


def _arc(cx,cy,rx,ry,start,sweep):
    """Return one move and cubic arc segments, each spanning at most 90 degrees."""
    parts=max(1,int(math.ceil(abs(sweep)/90)))
    a=math.radians(start);step=math.radians(sweep/parts)
    result=[['M',cx+rx*math.cos(a),cy+ry*math.sin(a)]]
    for _ in range(parts):
        b=a+step;k=4/3*math.tan(step/4)
        result.append(['C',cx+rx*(math.cos(a)-k*math.sin(a)),cy+ry*(math.sin(a)+k*math.cos(a)),
                       cx+rx*(math.cos(b)+k*math.sin(b)),cy+ry*(math.sin(b)-k*math.cos(b)),
                       cx+rx*math.cos(b),cy+ry*math.sin(b)])
        a=b
    return result


def sector(x,y,w,h,inner,start,sweep):
    outer=_arc(x+w/2,y+h/2,w/2,h/2,start,sweep)
    inside=_arc(x+w/2,y+h/2,w/2*inner,h/2*inner,start+sweep,-sweep)
    if math.isclose(abs(sweep),360):return outer+[['Z']]+inside+[['Z']]
    inside[0][0]='L'
    return outer+inside+[['Z']]


def compile_component(spec):
    """Produce a primitive object. Reject unknown params rather than ignore intent."""
    if not isinstance(spec,dict):raise ValueError('Component spec must be an object')
    required={'id','recipe','bbox'};allowed=required|{'params','style','role','evidence','text_style'}
    if required-spec.keys() or spec.keys()-allowed:raise ValueError('Component fields: id, recipe, bbox; optional params/style/role/evidence/text_style')
    oid=spec['id'];name=spec['recipe']
    if not isinstance(oid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,23}',oid):raise ValueError('Component ID must be 1..24 ASCII letters/digits/_/-')
    if name not in CATALOG:raise ValueError('Unknown component recipe: '+str(name))
    b=spec['bbox']
    if not isinstance(b,list) or len(b)!=4:raise ValueError('bbox must be logical/local-px xywh')
    x,y,w,h=[number(v,'bbox') for v in b];number(w,'width',positive=True);number(h,'height',positive=True)
    defaults=CATALOG[name]['params'];given=spec.get('params',{})
    if not isinstance(given,dict) or given.keys()-defaults.keys():raise ValueError('Unknown component parameters for '+name)
    p=copy.deepcopy(defaults)|copy.deepcopy(given)
    role=spec.get('role','diagram');evidence=spec.get('evidence',{'status':'inferred','note':'Parameterised '+name+'; check against reference'})
    st=copy.deepcopy(spec.get('style',{'fill':'2A7099','line':None}))
    def path(i,cmds,closed=True,style=None):return _base(i,'path',role,evidence)|{'commands':cmds,'closed':closed,'style':copy.deepcopy(st if style is None else style)}
    def group(children):return _base(oid,'group',role,evidence)|{'children':children}
    if name=='dashed_line':
        dash=number(p['dash_length'],'dash_length',positive=True)
        gap=number(p['gap_length'],'gap_length',positive=True)
        axis=p['axis']
        if axis not in ('horizontal','vertical'):raise ValueError('axis must be horizontal or vertical')
        length=w if axis=='horizontal' else h
        period=dash+gap
        ratio=length/period
        if not math.isfinite(period) or not math.isfinite(ratio) or ratio>512:
            raise ValueError('dashed_line requires at most 512 dashes')
        count=math.ceil(ratio)
        style=copy.deepcopy(spec.get('style',{'line':'2A7099','line_width_pt':1}))
        allowed_line={'fill','line','line_width_pt','line_alpha','line_cap','line_join','miter_limit'}
        if not isinstance(style,dict) or set(style)-allowed_line or style.get('fill') is not None:
            raise ValueError('dashed_line accepts only unfilled solid-stroke styles')
        if style.get('line') is None:raise ValueError('dashed_line requires a visible stroke color')
        number(style.get('line_width_pt',1),'line_width_pt',positive=True)
        style['fill']=None
        commands=[]
        for i in range(count):
            start=i*period;end=min(start+dash,length)
            if end<=start:continue
            a,b=([x+start,y+h/2],[x+end,y+h/2]) if axis=='horizontal' else ([x+w/2,y+start],[x+w/2,y+end])
            commands.extend([['M',*a],['L',*b]])
        return path(oid,commands,False,style)
    if name=='rounded_rect':
        radius=number(p['radius'],'radius',0,min(w,h)/2)
        return _base(oid,'shape',role,evidence)|{'bbox':[x,y,w,h],
            'geometry':'round_rect','adjustments':[radius/min(w,h)],'style':st}
    if name.startswith('native_'):
        from native_recipes import compile_native_recipe
        return compile_native_recipe(name, oid, [x,y,w,h], p, evidence)
    if name=='flat_semicircle':
        k=0.5522847498307936;rx=w/2
        return path(oid,[['M',x,y+h],['C',x,y+h-k*h,x+rx-k*rx,y,x+rx,y],['C',x+rx+k*rx,y,x+w,y+h-k*h,x+w,y+h],['L',x,y+h],['Z']])
    if name in {'annular_sector','segmented_ring'}:
        inner=number(p['inner_ratio'],'inner_ratio',.02,.98);start=number(p['start_deg'],'start_deg')
        if name=='annular_sector':
            sweep=number(p['sweep_deg'],'sweep_deg',.1,360)
            return path(oid,sector(x,y,w,h,inner,start,sweep))
        n=p['segments'];gap=number(p['gap_deg'],'gap_deg',0)
        if isinstance(n,bool) or not isinstance(n,int) or not 2<=n<=24:raise ValueError('segments must be integer 2..24')
        if gap>=360/n:raise ValueError('gap_deg leaves no sector')
        colors=p['colors']
        if not isinstance(colors,list) or not colors or any(not isinstance(c,str) or not re.fullmatch('[0-9A-Fa-f]{6}',c) for c in colors):raise ValueError('colors must be hex RGB strings')
        children=[]
        for i in range(n):
            style={k:v for k,v in st.items() if k not in {'fill','gradient'}}|{'fill':colors[i%len(colors)]}
            children.append(path(oid+f'_seg{i+1}',sector(x,y,w,h,inner,start+i*360/n+gap/2,360/n-gap),style=style))
        return group(children)
    if name=='notched_card':
        cut=number(p['cut_ratio'],'cut_ratio',.01,.45)*min(w,h)
        return path(oid,[['M',x,y],['L',x+w-cut,y],['L',x+w,y+cut],['L',x+w,y+h],['L',x,y+h],['Z']])
    if name=='double_arrow':
        head=number(p['head_fraction'],'head_fraction',.02,.45)*w
        half=number(p['shaft_fraction'],'shaft_fraction',.02,.95)*h/2;cy=y+h/2
        pts=[(x,cy),(x+head,y),(x+head,cy-half),(x+w-head,cy-half),(x+w-head,y),(x+w,cy),(x+w-head,y+h),(x+w-head,cy+half),(x+head,cy+half),(x+head,y+h)]
        return path(oid,[[('M' if i==0 else 'L'),*v] for i,v in enumerate(pts)]+[['Z']])
    if name=='feedback_curve':
        if not isinstance(p['bidirectional'],bool):raise ValueError('bidirectional must be boolean')
        style={k:v for k,v in st.items() if k in {'line','line_width_pt','dash'}}
        style['line']=style.get('line') or '2A7099';style.setdefault('line_width_pt',2)
        style['end_arrow']='triangle'
        if p['bidirectional']:style['begin_arrow']='triangle'
        return path(oid,[['M',x+.1*w,y+.1*h],['L',x+.1*w,y+.65*h],['C',x+.1*w,y+.9*h,x+.3*w,y+.9*h,x+.4*w,y+.9*h],['L',x+.6*w,y+.9*h],['C',x+.8*w,y+.9*h,x+.9*w,y+.9*h,x+.9*w,y+.65*h],['L',x+.9*w,y+.1*h]],False,style)
    if name=='icon_node':
        for key in ('label','value','description'):
            if not isinstance(p[key],str):raise ValueError(key+' must be exact source text')
        circle=_base(oid+'_base','shape',role,evidence)|{'geometry':'ellipse','bbox':[x,y,w,h],'style':st}
        children=[circle]
        txstyle={'font':'Arial','font_east_asia':'Microsoft YaHei','font_size_pt':14,'align':'center','color':'FFFFFF','valign':'middle'}|copy.deepcopy(spec.get('text_style',{}))
        if p['icon_asset']:
            children.append(_base(oid+'_icon','image',role,evidence)|{'bbox':[x+.33*w,y+.08*h,.34*w,.28*h],'asset':p['icon_asset'],'fit':'contain','asset_role':'icon','source_kind':p['icon_source'],'provenance':p['icon_provenance'] or 'User-supplied component icon; verify source'})
        for key,yy,hh in [('label',.38,.2),('value',.59,.2),('description',.8,.15)]:
            if p[key]:
                fs=txstyle|({'bold':True} if key=='value' else {})
                if key=='description':fs=fs|{'font_size_pt':txstyle['font_size_pt']*.72}
                children.append(_base(oid+'_'+key,'text',role,evidence)|{'bbox':[x+.07*w,y+yy*h,.86*w,hh*h],'text':p[key],'style':fs})
        return group(children)
    if name=='photo_window':
        if not isinstance(p['asset'],str) or not p['asset']:raise ValueError('photo_window needs a project-relative asset')
        if p['mask'] not in {'ellipse','round_rect','notched_card'}:raise ValueError('mask must be ellipse, round_rect or notched_card')
        mask={'geometry':p['mask']}
        if p['mask']=='notched_card':
            cut=number(p['cut_ratio'],'cut_ratio',.01,.45)
            mask={'geometry':'custom','commands':[['M',0,0],['L',1-cut,0],['L',1,cut],['L',1,1],['L',0,1],['Z']]}
        return _base(oid,'image',spec.get('role','photo'),evidence)|{'bbox':[x,y,w,h],'asset':p['asset'],'fit':'cover','mask':mask,'asset_role':'photo','source_kind':p['source_kind'],'provenance':p['provenance'] or 'User supplied photo; mask/crop only'}
    raise AssertionError(name)


def boolean_component(spec):
    """Optional polygon boolean engine; creates a real compound path with holes.
Ellipses are explicitly polygon-approximated, not claimed as exact original curves.
"""
    try:
        from shapely.geometry import Polygon, box
        from shapely.geometry.polygon import orient
    except ImportError as exc:
        raise RuntimeError('Optional Shapely not installed; use the existing Office Merge-PptShapes entry, or install approved optional dependency') from exc
    if not isinstance(spec,dict) or set(spec)-{'id','operation','operands','style','role','evidence','ellipse_samples'}:raise ValueError('Invalid boolean spec fields')
    oid=spec.get('id','boolean')
    if not isinstance(oid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,23}',oid):raise ValueError('Invalid boolean ID')
    operation=spec.get('operation');ops={'union','subtract','intersect','combine','fragment'}
    if operation not in ops:raise ValueError('operation must be one of '+str(sorted(ops)))
    operands=spec.get('operands',[])
    if not isinstance(operands,list) or not 2<=len(operands)<=16:raise ValueError('Need 2..16 operands in explicit primary-first order')
    n=spec.get('ellipse_samples',128)
    if isinstance(n,bool) or not isinstance(n,int) or not 24<=n<=512:raise ValueError('ellipse_samples: 24..512 integer')
    shapes=[]
    for o in operands:
        if not isinstance(o,dict) or set(o)-{'geometry','bbox','points'}:raise ValueError('Invalid operand')
        kind=o.get('geometry')
        if kind in {'rect','ellipse'}:
            b=o.get('bbox',[])
            if len(b)!=4:raise ValueError('operand bbox must be xywh')
            x,y,w,h=[number(v,'operand bbox') for v in b];number(w,'operand width',positive=True);number(h,'operand height',positive=True)
            g=box(x,y,x+w,y+h) if kind=='rect' else Polygon([(x+w/2+w/2*math.cos(i*2*math.pi/n),y+h/2+h/2*math.sin(i*2*math.pi/n)) for i in range(n)])
        elif kind=='polygon':
            pts=o.get('points',[])
            if len(pts)<3 or len(pts)>1024:raise ValueError('polygon needs 3..1024 points')
            g=Polygon([[number(a,'x'),number(b,'y')] for a,b in pts])
        else:raise ValueError('Operand geometry: rect/ellipse/polygon')
        if not g.is_valid or g.is_empty or g.area<=0:raise ValueError('Invalid/self-intersecting or empty operand')
        shapes.append(g)
    if operation=='fragment':
        pieces=[shapes[0]]
        for g in shapes[1:]:
            union=pieces[0]
            for piece in pieces[1:]:union=union.union(piece)
            nextpieces=[g.difference(union)]
            for piece in pieces:nextpieces.extend([piece.difference(g),piece.intersection(g)])
            pieces=[p for p in nextpieces if not p.is_empty and p.area>1e-9]
        result=pieces
    else:
        g=shapes[0]
        method={'union':'union','subtract':'difference','intersect':'intersection','combine':'symmetric_difference'}[operation]
        for other in shapes[1:]:g=getattr(g,method)(other)
        result=[g]
    polygons=[]
    def collect(g):
        if g.is_empty or g.area<=1e-9:return
        if g.geom_type=='Polygon':polygons.append(orient(g,sign=1))
        elif hasattr(g,'geoms'):
            for child in g.geoms:collect(child)
    for g in result:collect(g)
    if not polygons:raise ValueError('Boolean result is empty; no shape was created')
    polygons.sort(key=lambda g:(g.bounds,-g.area))
    ev=spec.get('evidence',{'status':'inferred','note':f'Polygon boolean {operation}; ellipse sampled at {n} points, inspect contour'})
    out=[]
    for i,p in enumerate(polygons):
        cmds=[]
        for ring in [p.exterior,*p.interiors]:
            pts=list(ring.coords)[:-1];cmds.extend([[('M' if j==0 else 'L'),*xy] for j,xy in enumerate(pts)]);cmds.append(['Z'])
        out.append(_base(oid if len(polygons)==1 else oid+f'_p{i+1}','path',spec.get('role','diagram'),ev)|{'commands':cmds,'closed':True,'style':copy.deepcopy(spec.get('style',{'fill':'2A7099','line':None}))})
    return out[0] if len(out)==1 else _base(oid,'group',spec.get('role','diagram'),ev)|{'children':out}
