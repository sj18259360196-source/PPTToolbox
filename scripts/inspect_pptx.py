"""Read-only OOXML audit. Checks package, expected objects/text, and simple chart caches.
Not a complete ECMA schema validator, font renderer, or visual/semantic judge.
"""
from __future__ import annotations
import argparse, hashlib, io, math, posixpath, re, sys, zipfile
from pathlib import Path
from lxml import etree as ET
from common import normalize_text, read_json, sha256, walk_objects, write_json
NS={"p":"http://schemas.openxmlformats.org/presentationml/2006/main",
    "a":"http://schemas.openxmlformats.org/drawingml/2006/main",
    "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel":"http://schemas.openxmlformats.org/package/2006/relationships",
    "c":"http://schemas.openxmlformats.org/drawingml/2006/chart",
    "s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PARSER=ET.XMLParser(resolve_entities=False,no_network=True,load_dtd=False)

def xml(data):
    root=ET.fromstring(data,parser=PARSER)
    if root.getroottree().docinfo.doctype:raise ValueError('DOCTYPE is not accepted')
    return root

def target_part(source, target):
    from urllib.parse import unquote
    target=unquote(target.split('#',1)[0])
    value=posixpath.normpath(posixpath.join(posixpath.dirname(source),target)) if not target.startswith('/') else target[1:]
    if value.startswith('../'):raise ValueError('Relationship leaves package root')
    return value

def relationships(z,source):
    rp=posixpath.join(posixpath.dirname(source),'_rels',posixpath.basename(source)+'.rels') if source else '_rels/.rels'
    if rp not in z.namelist():return {}
    return {r.get('Id'):{'target':r.get('Target'),'external':r.get('TargetMode')=='External','type':r.get('Type','')} for r in xml(z.read(rp))}

def text_body(node):
    pars=node.xpath('./a:p',namespaces=NS)
    def paragraph_text(paragraph):
        parts=[]
        for child in paragraph:
            if child.tag == '{'+NS['a']+'}br': parts.append('\n')
            else: parts.extend(child.xpath('.//a:t/text()',namespaces=NS))
        return ''.join(parts)
    return '\n'.join(paragraph_text(p) for p in pars)

def geometry(node):
    x=node.find('p:spPr/a:xfrm',NS)
    if x is None:x=node.find('p:xfrm',NS)
    if x is None:x=node.find('p:grpSpPr/a:xfrm',NS)
    if x is None:return None
    off=x.find('a:off',NS);ext=x.find('a:ext',NS)
    if off is None or ext is None:return None
    return [int(off.get('x'))/12700,int(off.get('y'))/12700,int(ext.get('cx'))/12700,int(ext.get('cy'))/12700,float(x.get('rot','0'))/60000]

def flatten(tree,group_path=''):
    for node in tree:
        kind=ET.QName(node).localname
        if kind not in {'sp','pic','cxnSp','graphicFrame','grpSp'}:continue
        nv=node.xpath('./*/p:cNvPr',namespaces=NS)
        name=nv[0].get('name','') if nv else '';ident=nv[0].get('id','') if nv else ''
        body=node.find('p:txBody',NS)
        text=text_body(body) if body is not None else ''
        table=node.find('a:graphic/a:graphicData/a:tbl',NS) if kind=='graphicFrame' else None
        chart=node.find('a:graphic/a:graphicData/c:chart',NS) if kind=='graphicFrame' else None
        rows=[]
        if table is not None:
            rows=[[text_body(cell.find('a:txBody',NS)) for cell in row.findall('a:tc',NS)] for row in table.findall('a:tr',NS)]
        item={'name':name,'ooxml_id':ident,'xml_type':kind,'group':group_path,'text':normalize_text(text),
              'geometry_pt':geometry(node),'table_rows':rows,'chart_rid':chart.get('{'+NS['r']+'}id') if chart is not None else None}
        yield item
        if kind=='grpSp':yield from flatten(node,(group_path+'/' if group_path else '')+name)

def col_index(s):
    n=0
    for c in s:n=n*26+ord(c)-64
    return n

def col_name(n):
    s=''
    while n:n,r=divmod(n-1,26);s=chr(65+r)+s
    return s

def workbook_cells(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        wb=xml(z.read('xl/workbook.xml'));rels=relationships(z,'xl/workbook.xml');strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(si.xpath('.//s:t/text()',namespaces=NS)) for si in xml(z.read('xl/sharedStrings.xml'))]
        sheets={}
        for sheet in wb.findall('s:sheets/s:sheet',NS):
            rid=sheet.get('{'+NS['r']+'}id');path=target_part('xl/workbook.xml',rels[rid]['target']);cells={}
            for cell in xml(z.read(path)).findall('.//s:sheetData/s:row/s:c',NS):
                if cell.find('s:f',NS) is not None:cells[cell.get('r')]={'formula':True};continue
                v=cell.findtext('s:v',default='',namespaces=NS);typ=cell.get('t','n')
                if typ=='s':value=strings[int(v)]
                elif typ=='inlineStr':value=''.join(cell.xpath('.//s:t/text()',namespaces=NS))
                else:value=v
                cells[cell.get('r')]=value
            sheets[sheet.get('name')]=cells
        return sheets

def cache_check(z,chart_path):
    root=xml(z.read(chart_path));ext=root.find('c:externalData',NS)
    if ext is None:return {'status':'blocked','part':chart_path,'reason':'No embedded workbook relationship'}
    rels=relationships(z,chart_path);rid=ext.get('{'+NS['r']+'}id');rel=rels.get(rid)
    if not rel or rel['external']:return {'status':'blocked','part':chart_path,'reason':'External or missing workbook'}
    try:sheets=workbook_cells(z.read(target_part(chart_path,rel['target'])))
    except Exception as exc:return {'status':'blocked','part':chart_path,'reason':str(exc)}
    findings=[];unsupported=[];checked=0
    for ref in root.xpath('.//c:numRef|.//c:strRef',namespaces=NS):
        f=ref.findtext('c:f',namespaces=NS) or ''
        match=re.fullmatch(r"(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?",f)
        if not match:unsupported.append(f);continue
        sh=(match[1] or match[2]).replace("''", "'");c1,r1=col_index(match[3]),int(match[4]);c2,r2=col_index(match[5] or match[3]),int(match[6] or match[4])
        if sh not in sheets or (c1!=c2 and r1!=r2):unsupported.append(f);continue
        values=[sheets[sh].get(f'{col_name(c)}{r}','') for r in range(r1,r2+1) for c in range(c1,c2+1)]
        cache=ref.find('c:numCache',NS)
        numeric=cache is not None
        if cache is None:cache=ref.find('c:strCache',NS)
        if cache is None:unsupported.append(f);continue
        points={int(p.get('idx')):p.findtext('c:v',default='',namespaces=NS) for p in cache.findall('c:pt',NS)}
        for i,expected in enumerate(values):
            if isinstance(expected,dict):unsupported.append(f+' formula cell');continue
            actual=points.get(i,'')
            checked+=1
            if numeric and actual!='' and expected!='':
                try:equal=math.isclose(float(actual),float(expected),rel_tol=1e-12,abs_tol=1e-12)
                except ValueError:equal=False
            else:equal=actual==expected
            if not equal:findings.append({'reference':f,'index':i,'cache':actual,'workbook':expected})
        pc=cache.find('c:ptCount',NS)
        if pc is not None and int(pc.get('val'))!=len(values):findings.append({'reference':f,'reason':'ptCount/range length differs'})
    status='failed' if findings else ('blocked' if unsupported or not checked else 'passed')
    return {'status':status,'part':chart_path,'checked_values':checked,'findings':findings,'unsupported':unsupported,
            'scope':'Basic single-row/single-column references. Numeric tolerance 1e-12; not data truth or formula recalculation.'}

def inspect(pptx:Path,scene_path:Path|None=None):
    report={'pptx_sha256':sha256(pptx),'checks':{},'slides':[],'scope':'Transitional OOXML, package relations and local objects; not full schema/visual validation'}
    errors=[];external=[]
    with zipfile.ZipFile(pptx) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):errors.append('Duplicate ZIP members')
        if sum(i.file_size for i in z.infolist())>250*1024*1024:raise ValueError('Uncompressed package exceeds 250 MB audit limit')
        bad=z.testzip()
        if bad:errors.append('CRC error: '+bad)
        for req in ['[Content_Types].xml','_rels/.rels','ppt/presentation.xml']:
            if req not in names:errors.append('Missing: '+req)
        for name in names:
            if name.endswith(('.xml','.rels')):
                try:r=xml(z.read(name))
                except Exception as exc:errors.append(f'{name}: {exc}');continue
                if name.endswith('.rels'):
                    source='' if name=='_rels/.rels' else posixpath.join(posixpath.dirname(posixpath.dirname(name)),posixpath.basename(name)[:-5])
                    for rel in r:
                        if rel.get('TargetMode')=='External':external.append({'source':source,'target':rel.get('Target')});continue
                        try:target=target_part(source,rel.get('Target',''))
                        except ValueError as exc:errors.append(str(exc));continue
                        if target not in names:errors.append(f'{name}: missing target {target}')
        report['checks']['package']={'status':'failed' if errors else 'passed','findings':errors,'external_relationships':external,'scope':'ZIP CRC, XML syntax, internal relationship targets only'}
        if errors:return report
        presentation=xml(z.read('ppt/presentation.xml'))
        if ET.QName(presentation).namespace!=NS['p']:raise ValueError('Strict OOXML not supported by this audit')
        size=presentation.find('p:sldSz',NS);width,height=int(size.get('cx'))/12700,int(size.get('cy'))/12700
        report['canvas_pt']=[width,height]
        prels=relationships(z,'ppt/presentation.xml');slide_paths=[]
        for item in presentation.findall('p:sldIdLst/p:sldId',NS):slide_paths.append(target_part('ppt/presentation.xml',prels[item.get('{'+NS['r']+'}id')]['target']))
        geom_warnings=[];deferred_geom=[];image_candidates=[]
        for si,path in enumerate(slide_paths,1):
            root=xml(z.read(path));items=list(flatten(root.find('p:cSld/p:spTree',NS)));seen=set()
            for obj in items:
                if obj['name'] in seen:errors.append(f'slide {si}: duplicate object name {obj["name"]}')
                seen.add(obj['name']);g=obj['geometry_pt']
                if g:
                    if obj['group'] or g[4]%360:
                        deferred_geom.append({'slide':si,'id':obj['name'],'reason':'Grouped or rotated geometry needs Office/visual check'})
                    elif g[0]<-.5 or g[1]<-.5 or g[0]+g[2]>width+.5 or g[1]+g[3]>height+.5:
                        geom_warnings.append({'slide':si,'id':obj['name'],'bbox_pt':g})
                    if obj['xml_type']=='pic' and not obj['group'] and g[2]*g[3]>=width*height*.8:
                        image_candidates.append({'slide':si,'id':obj['name'],'reason':'Large image. Inspect actual media purpose/content; a clean photograph background may be legitimate.'})
            leaves=[o for o in items if o['xml_type']!='grpSp']
            report['slides'].append({'index':si,'part':path,'objects':items,'leaf_objects':len(leaves),'nonempty_text_objects':sum(bool(o['text']) for o in leaves),'tables':sum(bool(o['table_rows']) for o in leaves),'charts':sum(bool(o['chart_rid']) for o in leaves),'pictures':sum(o['xml_type']=='pic' for o in leaves)})
        report['checks']['package']['findings']=errors
        report['checks']['package']['status']='failed' if errors else 'passed'
        report['checks']['geometry']={'status':'blocked' if geom_warnings or deferred_geom else 'passed','findings':geom_warnings,'deferred':deferred_geom,'scope':'Unrotated root object boxes with 0.5 pt tolerance; no glyph/effect overlap check'}
        report['checks']['raster_review']={'status':'not_run','candidates':image_candidates,'reason':'Agent must inspect media roles and text-covered areas. Hash/size checks cannot exclude re-encoded or tiled page screenshots.'}
        charts=[cache_check(z,p) for p in names if re.fullmatch(r'ppt/charts/chart\d+\.xml',p)]
        report['checks']['chart_cache']={'status':('not_applicable' if not charts else 'failed' if any(c['status']=='failed' for c in charts) else 'blocked' if any(c['status']=='blocked' for c in charts) else 'passed'),'charts':charts}
    if scene_path:
        scene=read_json(scene_path);report['scene_sha256']=sha256(scene_path);issues=[]
        if len(scene['slides'])!=len(report['slides']):issues.append('Slide count mismatch')
        for sd,actual in zip(scene['slides'],report['slides']):
            amap={o['name']:o for o in actual['objects']}
            for exp in walk_objects(sd['objects']):
                obj=amap.get(exp['id'])
                if obj is None:issues.append(f'{sd["id"]}/{exp["id"]}: missing object');continue
                kind=exp['kind']
                expected_xml={'text':'sp','shape':'sp','line':'cxnSp','connector':'cxnSp','path':'sp','image':'pic','table':'graphicFrame','chart':'graphicFrame','group':'grpSp'}[kind]
                if obj['xml_type']!=expected_xml:issues.append(f'{exp["id"]}: object type differs')
                if kind=='text':
                    expected=normalize_text("\n".join("".join(r["text"] for r in p["runs"]) for p in exp["paragraphs"])
                                            if "paragraphs" in exp else exp.get('text',''.join(r['text'] for r in exp.get('runs',[]))))
                    if expected!=obj['text']:issues.append(f'{exp["id"]}: text mismatch')
                if kind=='table' and [[normalize_text(t) for t in r] for r in exp['rows']]!=obj['table_rows']:issues.append(f'{exp["id"]}: table mismatch')
                if kind=='chart' and not obj['chart_rid']:issues.append(f'{exp["id"]}: missing native chart')
            extra=set(amap)-{o['id'] for o in walk_objects(sd['objects'])}
            if extra:issues.append(f'{sd["id"]}: unexpected objects {sorted(extra)}')
        report['checks']['native_content']={'status':'failed' if issues else 'passed','findings':issues,'scope':'PPT matches Agent-authored scene; source transcription accuracy and editable behavior are NOT proven'}
    else:report['checks']['native_content']={'status':'not_run','reason':'No scene supplied'}
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('pptx',type=Path);ap.add_argument('--scene',type=Path);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    try:r=inspect(a.pptx,a.scene);write_json(a.out,r);return 1 if any(c['status']=='failed' for c in r['checks'].values()) else 0
    except Exception as exc:print(f'Audit failed: {exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
