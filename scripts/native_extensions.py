"""Testable extensions for text, native picture masks, tables and chart layouts.
No Office success is asserted here. Caller must render and review in target Office.
"""
from __future__ import annotations
import math
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Pt
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_MARKER_STYLE, XL_LEGEND_POSITION
from common import walk_objects


def element(tag,**attrs):
    e=OxmlElement(tag)
    for k,v in attrs.items():e.set(k,str(v))
    return e


def validate_extensions(scene):
    errors=[]
    for slide in scene['slides']:
        for o in walk_objects(slide['objects']):
            oid=o['id'];kind=o['kind']
            if 'native_path_frame' in o and kind!='path':
                errors.append(f'{oid}: native_path_frame is restricted to actual paths')
            if 'paragraphs' in o:
                if kind!='text' or 'text' in o or 'runs' in o or o.get('style',{}).get('native_format'):
                    errors.append(f'{oid}: explicit paragraphs require exclusive plain text representation')
                if any(any(c in r['text'] for c in '\n\r\v') for p in o['paragraphs'] for r in p['runs']):
                    errors.append(f'{oid}: paragraph runs cannot contain embedded paragraph/soft breaks')
            if kind=='image' and 'mask' in o:
                m=o['mask']
                if o.get('fit','contain')=='contain':errors.append(f'{oid}: native masks require cover/stretch, not contain')
                if m['geometry']=='custom':
                    cs=m.get('commands',[])
                    if not cs or cs[0][0]!='M' or cs[-1][0]!='Z':errors.append(f'{oid}: custom picture mask must be closed')
                    for cmd in cs:
                        if len(cmd)!={'M':3,'L':3,'C':7,'Z':1}[cmd[0]] or any(v<0 or v>1 for v in cmd[1:]):errors.append(f'{oid}: mask commands use normalized 0..1 coordinates')
                elif 'commands' in m:errors.append(f'{oid}: preset mask cannot also define commands')
            if kind=='table':
                rows=o.get('rows',[]);nr=len(rows);nc=len(rows[0]) if rows else 0
                heights=o.get('row_heights')
                if heights and (len(heights)!=nr or abs(sum(heights)-o['bbox'][3])>1e-5):errors.append(f'{oid}: row heights must match row count and sum to bbox height')
                occupied=set()
                for r0,c0,r1,c1 in o.get('merges',[]):
                    if not 0<=r0<=r1<nr or not 0<=c0<=c1<nc or (r0==r1 and c0==c1):errors.append(f'{oid}: invalid merge range');continue
                    cells={(r,c) for r in range(r0,r1+1) for c in range(c0,c1+1)}
                    if cells & occupied:errors.append(f'{oid}: overlapping merges')
                    occupied |= cells
                    if any(rows[r][c] for r,c in cells-{(r0,c0)}):errors.append(f'{oid}: spanned cells must be empty; no silent text loss during merge')
                seen=set();textstyles={'font','font_east_asia','font_size_pt','bold','italic','color','align','valign','wrap','margin_pt','line_spacing_pt','margin_left_pt','margin_right_pt','margin_top_pt','margin_bottom_pt','space_before_pt','space_after_pt','char_spacing_pt','fill','line','line_width_pt'}
                for c in o.get('cell_styles',[]):
                    key=(c['row'],c['col'])
                    if not 0<=key[0]<nr or not 0<=key[1]<nc or key in seen:errors.append(f'{oid}: invalid/duplicate cell style coordinate')
                    if set(c['style'])-textstyles:errors.append(f'{oid}: cell style contains unsupported properties')
                    seen.add(key)
            if kind=='chart':
                for axis,st in o.get('axes',{}).items():
                    if 'minimum' in st and 'maximum' in st and st['minimum']>=st['maximum']:errors.append(f'{oid}: axis minimum must be below maximum')
                    if axis=='x' and o['chart_type']!='xy' and any(k in st for k in ('minimum','maximum','major_unit','minor_unit')):errors.append(f'{oid}: categorical X axis has no numeric scale; use xy chart for numeric X')
                if 'plot_area' in o:
                    x,y,w,h=o['plot_area']
                    if w<=0 or h<=0 or x+w>1 or y+h>1:errors.append(f'{oid}: plot_area is normalized xywh within 0..1')
                if o['chart_type']=='column' and any(any(k in s for k in ('marker','marker_size_pt','smooth')) for s in o['series']):errors.append(f'{oid}: markers/smooth unsupported for columns')
    return errors


def apply_picture_mask(pic,mask):
    sp=pic._element.spPr;old=sp.find(qn('a:prstGeom'));idx=list(sp).index(old) if old is not None else 1
    if old is not None:sp.remove(old)
    if mask['geometry']!='custom':
        geom=element('a:prstGeom',prst={'ellipse':'ellipse','round_rect':'roundRect'}[mask['geometry']]);geom.append(element('a:avLst'))
    else:
        geom=element('a:custGeom')
        for tag in ['avLst','gdLst','ahLst','cxnLst']:geom.append(element('a:'+tag))
        geom.append(element('a:rect',l='0',t='0',r='r',b='b'));lst=element('a:pathLst');path=element('a:path',w=100000,h=100000)
        for cmd in mask['commands']:
            node=element('a:'+{'M':'moveTo','L':'lnTo','C':'cubicBezTo','Z':'close'}[cmd[0]])
            for i in range(1,len(cmd),2):node.append(element('a:pt',x=round(cmd[i]*100000),y=round(cmd[i+1]*100000)))
            path.append(node)
        lst.append(path);geom.append(lst)
    sp.insert(idx,geom)


def table_extensions(shape,obj,canvas,set_text):
    table=shape.table;st=obj.get('style',{});overrides={(c['row'],c['col']):c['style'] for c in obj.get('cell_styles',[])}
    for r0,c0,r1,c1 in obj.get('merges',[]):table.cell(r0,c0).merge(table.cell(r1,c1))
    for ri,row in enumerate(obj['rows']):
        if 'row_heights' in obj:table.rows[ri].height=Pt(obj['row_heights'][ri]*canvas['height_pt']/canvas['height'])
        for ci,text in enumerate(row):
            cell=table.cell(ri,ci)
            if cell.is_spanned:continue
            cs=st|overrides.get((ri,ci),{})
            # PowerPoint table cells use tcPr margins, not text-frame bodyPr
            # insets. Preserve legacy defaults unless a side is explicit.
            for side in ('left','right','top','bottom'):
                key='margin_'+side+'_pt'
                if key in cs:setattr(cell,'margin_'+side,Pt(cs[key]))
            set_text(cell.text_frame,{'text':text,'style':cs|{'margin_pt':cs.get('margin_pt',3)}})
            if 'fill' in overrides.get((ri,ci),{}) and cs['fill'] is not None:cell.fill.solid();cell.fill.fore_color.rgb=RGBColor.from_string(cs['fill'])
            # Keep native per-cell borders. No independent overlay grid lines.
            if 'line' in cs or 'line_width_pt' in cs:
                tcp=cell._tc.get_or_add_tcPr()
                for tag in ('lnL','lnR','lnT','lnB'):
                    old=tcp.find(qn('a:'+tag))
                    if old is not None:tcp.remove(old)
                    ln=element('a:'+tag,w=int(Pt(cs.get('line_width_pt',.6))))
                    if cs.get('line') is None:ln.append(element('a:noFill'))
                    else:
                        sf=element('a:solidFill');sf.append(element('a:srgbClr',val=cs['line']));ln.append(sf)
                    tcp.insert_element_before(ln,'a:cell3D','a:noFill','a:solidFill','a:gradFill','a:blipFill','a:pattFill','a:grpFill','a:headers','a:extLst')


def chart_extensions(chart,obj):
    if obj.get('chart_title'):
        chart.has_title=True;chart.chart_title.text_frame.text=obj['chart_title']
    if chart.has_legend and 'legend_position' in obj:chart.legend.position={'bottom':XL_LEGEND_POSITION.BOTTOM,'top':XL_LEGEND_POSITION.TOP,'left':XL_LEGEND_POSITION.LEFT,'right':XL_LEGEND_POSITION.RIGHT}[obj['legend_position']]
    for key,st in obj.get('axes',{}).items():
        axis=chart.category_axis if key=='x' else chart.value_axis
        for prop,attr in [('minimum','minimum_scale'),('maximum','maximum_scale'),('major_unit','major_unit'),('minor_unit','minor_unit')]:
            if prop in st:setattr(axis,attr,st[prop])
        if 'title' in st:
            axis.has_title=bool(st['title'])
            if st['title']:axis.axis_title.text_frame.text=st['title']
        if 'visible' in st:axis.visible=st['visible']
        if 'gridlines' in st:axis.has_major_gridlines=st['gridlines']
        if 'number_format' in st:axis.tick_labels.number_format=st['number_format'];axis.tick_labels.number_format_is_linked=False
        if 'font_size_pt' in st:axis.tick_labels.font.size=Pt(st['font_size_pt'])
    markers={'none':XL_MARKER_STYLE.NONE,'circle':XL_MARKER_STYLE.CIRCLE,'square':XL_MARKER_STYLE.SQUARE,'triangle':XL_MARKER_STYLE.TRIANGLE,'diamond':XL_MARKER_STYLE.DIAMOND,'star':XL_MARKER_STYLE.STAR,'plus':XL_MARKER_STYLE.PLUS}
    for spec,ser in zip(obj['series'],chart.series):
        if 'line_width_pt' in spec:ser.format.line.width=Pt(spec['line_width_pt'])
        if 'marker' in spec:ser.marker.style=markers[spec['marker']]
        if 'marker_size_pt' in spec:ser.marker.size=spec['marker_size_pt']
        if 'smooth' in spec:ser.smooth=spec['smooth']
    if 'plot_area' in obj:
        pa=chart._chartSpace.find('.//'+qn('c:plotArea'));old=pa.find(qn('c:layout'))
        if old is not None:pa.remove(old)
        layout=element('c:layout');ml=element('c:manualLayout');ml.append(element('c:layoutTarget',val='inner'))
        for prop in ['xMode','yMode','wMode','hMode']:ml.append(element('c:'+prop,val='factor'))
        for prop,val in zip(['x','y','w','h'],obj['plot_area']):ml.append(element('c:'+prop,val=val))
        layout.append(ml);pa.insert(0,layout)
