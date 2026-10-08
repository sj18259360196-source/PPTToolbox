"""Versioned, bounded scene/PPTX edits. No eval or arbitrary property execution.
Never edits source; primitive scene edits preserve all unrelated object records.
"""
from __future__ import annotations
import copy
import shutil
import zipfile
from pathlib import Path
from lxml import etree as ET
from common import read_json,write_json,sha256,staged_directory,walk_objects,resolve_asset
from validate_scene import validate
from inspect_pptx import NS,xml,relationships,target_part


def normalize_scene_change(change):
    """Accept only two unambiguous data aliases; never infer an operation."""
    if not isinstance(change,dict):
        raise ValueError('Each change must be an object')
    result=copy.deepcopy(change)
    alias={'set_runs':'runs','move':'delta'}.get(result.get('op'))
    if alias and alias in result:
        if 'value' in result:
            raise ValueError('Conflicting patch value and '+alias+' fields')
        result['value']=result.pop(alias)
    if set(result)-{'slide','id','op','value'}:
        raise ValueError('Change fields are slide,id,op,value; set_runs may use runs and move may use delta')
    return result


def _shift(obj,dx,dy):
    if 'bbox' in obj:obj['bbox'][0]+=dx;obj['bbox'][1]+=dy
    if 'points' in obj:obj['points']=[[x+dx,y+dy] for x,y in obj['points']]
    if 'commands' in obj:
        for c in obj['commands']:
            for i in range(1,len(c),2):c[i]+=dx;c[i+1]+=dy
    if obj['kind']=='group':
        for ch in obj['children']:_shift(ch,dx,dy)


def patch_scene(source,spec,outdir):
    if spec.get('base_sha256')!=sha256(source):raise ValueError('Stale scene hash')
    if set(spec)-{'base_sha256','allowed_ids','changes','reason'}:raise ValueError('Unknown patch fields')
    if not isinstance(spec.get('reason'),str) or not spec['reason'].strip():raise ValueError('Record a patch reason')
    changes=spec.get('changes');allowed=spec.get('allowed_ids')
    if not isinstance(changes,list) or not changes or not isinstance(allowed,list) or not allowed:raise ValueError('Nonempty allowed_ids and changes are required')
    requested_changes=copy.deepcopy(changes)
    changes=[normalize_scene_change(change) for change in changes]
    scene=read_json(source);original=copy.deepcopy(scene);index={}
    for slide in scene['slides']:
        for o in walk_objects(slide['objects']):index[(slide['id'],o['id'])]=o
    # IDs may repeat between slides. Permission entries use slide/object.
    expanded=set()
    for key in allowed:
        matches=[(k,o) for k,o in index.items() if k[0]+'/'+k[1]==key]
        if len(matches)!=1:raise ValueError('Allowed ID must be an existing slide/object: '+str(key))
        k,o=matches[0];expanded.add(k)
        if o['kind']=='group':expanded.update((k[0],ch['id']) for ch in walk_objects(o['children']))
    for ch in changes:
        if not isinstance(ch,dict) or set(ch)-{'slide','id','op','value'}:raise ValueError('Change fields are slide,id,op,value')
        key=(ch.get('slide'),ch.get('id'))
        if key not in index or key not in expanded:raise ValueError('Patch target outside permitted object set: '+str(key))
        o=index[key];op=ch['op'];v=ch.get('value')
        if op=='set_text':
            if o['kind']!='text' or not isinstance(v,str):raise ValueError('set_text requires text object/string')
            if 'runs' in o:raise ValueError('Mixed-format text needs explicit set_runs; do not silently lose formatting')
            o['text']=v
        elif op=='set_runs':
            if o['kind']!='text' or not isinstance(v,list):raise ValueError('set_runs requires a text run list')
            o.pop('text',None);o['runs']=v
        elif op=='set_style':
            if not isinstance(v,dict):raise ValueError('set_style requires a dict')
            o['style']=o.get('style',{})|v
        elif op=='set_adjustments':
            if o['kind']!='shape' or not isinstance(v,list):
                raise ValueError('set_adjustments requires a native shape and adjustment list')
            o['adjustments']=copy.deepcopy(v)
        elif op=='set_path_commands':
            if o['kind']!='path':
                raise ValueError('set_path_commands requires a native path')
            from graphics_geometry import check_commands
            check_commands(v)
            if ([c[0] for c in v] != [c[0] for c in o['commands']]):
                raise ValueError('Path edits must preserve command topology and subpaths')
            o['commands']=copy.deepcopy(v)
        elif op=='move':
            if not isinstance(v,list) or len(v)!=2 or any(type(a) not in (int,float) for a in v):raise ValueError('move requires logical dx,dy')
            _shift(o,*v)
        elif op=='replace_image':
            if o['kind']!='image' or not isinstance(v,dict) or set(v)-{'asset','bbox','provenance','source_kind'}:raise ValueError('replace_image fields: asset,bbox,provenance,source_kind')
            if not {'asset','provenance','source_kind'}<=v.keys():raise ValueError('Replacement needs asset and actual provenance')
            o.update(v)
        elif op=='table_cell':
            if o['kind']!='table' or not isinstance(v,dict) or set(v)!={'row','col','text'}:raise ValueError('table_cell needs row,col,text')
            if type(v['row'])is not int or type(v['col'])is not int or not 0<=v['row']<len(o['rows']) or not 0<=v['col']<len(o['rows'][0]) or not isinstance(v['text'],str):raise ValueError('Invalid cell edit')
            o['rows'][v['row']][v['col']]=v['text']
        elif op=='chart_data':
            if o['kind']!='chart' or not isinstance(v,dict) or set(v)-{'series','categories','data_provenance'} or not {'series','data_provenance'}<=v.keys():raise ValueError('chart_data needs series and provenance, optional categories')
            o.update(v)
        else:raise ValueError('Unsupported bounded patch op: '+str(op))
    issues=validate(scene,source.parent)
    if issues:raise ValueError('Patched scene invalid: '+'; '.join(issues[:12]))
    # Leaf-level equality plus group membership invariants protect untouched content.
    for s0,s1 in zip(original['slides'],scene['slides']):
        a=list(walk_objects(s0['objects']));b=list(walk_objects(s1['objects']))
        if [o['id'] for o in a]!=[o['id'] for o in b]:raise ValueError('Patch must not change membership/order')
        for old,new in zip(a,b):
            if (s0['id'],old['id']) not in expanded and old['kind']!='group' and old!=new:raise ValueError('Unrelated object changed')
    files=set()
    for s in scene['slides']:
        if s.get('reference'):files.add(s['reference'])
        files.update(o['asset'] for o in walk_objects(s['objects']) if o['kind']=='image')
    with staged_directory(outdir) as stage:
        for rel in files:
            src=resolve_asset(source.parent,rel);dst=stage/rel
            if rel in {'scene.json','patch-report.json'}:raise ValueError('Dependency conflicts with patch output')
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        write_json(stage/'scene.json',scene)
        report={'status':'passed','scope':'Bounded scene edit, not a visual pass. Rebuild/render and review this new version.', 'source_sha256':sha256(source),'result_sha256':sha256(stage/'scene.json'),'allowed_ids':allowed,'changes':changes,'reason':spec['reason'],'all_prior_reviews_invalidated':True,'scene':'scene.json'}
        if requested_changes!=changes:
            report['requested_changes']=requested_changes
            report['field_aliases_normalized']=True
        write_json(stage/'patch-report.json',report)
    return report


def patch_pptx(source,spec,outdir):
    """Surgical XML edits preserve all unrelated ZIP parts byte-for-byte.
Supported: one-run native text, solid native shape fill, ungrouped position.
Advanced data/mixed-format edits use scene patch + rebuild or a tested Office adapter.
"""
    if spec.get('base_sha256')!=sha256(source):raise ValueError('Stale PPTX hash')
    if set(spec)-{'base_sha256','changes','reason'} or not spec.get('changes') or not spec.get('reason'):raise ValueError('Need base_sha256, changes, reason')
    source_hash=sha256(source);modified={};applied=[]
    with zipfile.ZipFile(source) as z:
        if len(z.namelist())!=len(set(z.namelist())) or sum(i.file_size for i in z.infolist())>250*1024*1024:raise ValueError('Invalid/oversized ZIP')
        root=xml(z.read('ppt/presentation.xml'));rels=relationships(z,'ppt/presentation.xml')
        pages=[target_part('ppt/presentation.xml',rels[n.get('{'+NS['r']+'}id')]['target']) for n in root.findall('p:sldIdLst/p:sldId',NS)]
        trees={}
        for ch in spec['changes']:
            if not isinstance(ch,dict) or set(ch)!={'slide','id','op','value'}:raise ValueError('PPTX changes require slide(1-based),id,op,value')
            si=ch['slide']
            if type(si)is not int or not 1<=si<=len(pages):raise ValueError('Invalid slide index')
            part=pages[si-1];tree=trees.setdefault(part,xml(z.read(part)))
            found=tree.xpath('.//p:cNvPr[@name=$name]',namespaces=NS,name=ch['id'])
            if len(found)!=1:raise ValueError('Need exactly one stable object name: '+str(ch['id']))
            obj=found[0].getparent().getparent();v=ch['value'];op=ch['op']
            if op=='set_text':
                nodes=obj.xpath('./p:txBody/a:p/a:r/a:t',namespaces=NS)
                if obj.tag!='{'+NS['p']+'}sp' or len(nodes)!=1 or not isinstance(v,str) or any(c in v for c in '\n\r\v') or obj.xpath('./p:txBody/a:p/a:fld',namespaces=NS):raise ValueError('Surgical text edit supports one-run single-line native text only; preserve mixed formatting via scene or Office adapter')
                nodes[0].text=v
            elif op=='set_fill':
                import re
                if obj.tag!='{'+NS['p']+'}sp' or not isinstance(v,str) or not re.fullmatch('[0-9A-Fa-f]{6}',v):raise ValueError('set_fill requires native shape and hex RGB')
                sp=obj.find('p:spPr',NS)
                if sp is None:raise ValueError('Missing shape properties')
                for old in list(sp):
                    if ET.QName(old).localname in {'noFill','solidFill','gradFill','blipFill','pattFill','grpFill'}:sp.remove(old)
                fill=ET.Element('{'+NS['a']+'}solidFill');ET.SubElement(fill,'{'+NS['a']+'}srgbClr',val=v)
                idx=0
                for j,node in enumerate(sp):
                    if ET.QName(node).localname in {'xfrm','prstGeom','custGeom'}:idx=j+1
                sp.insert(idx,fill)
            elif op=='move_pt':
                import math
                if obj.xpath('ancestor::p:grpSp',namespaces=NS):raise ValueError('Group coordinates need explicit transform; use scene patch')
                if not isinstance(v,list) or len(v)!=2 or any(type(n)not in (int,float) or not math.isfinite(n) for n in v):raise ValueError('move_pt requires finite dx,dy points')
                off=obj.find('p:spPr/a:xfrm/a:off',NS)
                if off is None:raise ValueError('No native shape/picture position transform')
                for key,d in zip(['x','y'],v):off.set(key,str(int(off.get(key))+round(d*12700)))
            else:raise ValueError('Unsupported surgical PPTX operation')
            applied.append(ch)
        for part,tree in trees.items():modified[part]=ET.tostring(tree,encoding='UTF-8',xml_declaration=True,standalone=True)
        with staged_directory(outdir) as stage:
            dst=stage/'patched.pptx'
            with zipfile.ZipFile(dst,'x',compression=zipfile.ZIP_DEFLATED) as out:
                for info in z.infolist():out.writestr(copy.copy(info),modified.get(info.filename,z.read(info.filename)))
            if sha256(source)!=source_hash:raise ValueError('Source changed during patch')
            with zipfile.ZipFile(dst) as check:
                if check.testzip():raise ValueError('Patched ZIP CRC error')
                for name in z.namelist():
                    if name not in modified and z.read(name)!=check.read(name):raise ValueError('Unrelated ZIP part changed')
            report={'status':'passed','source_sha256':source_hash,'result_sha256':sha256(dst),'changed_parts':sorted(modified),'changes':applied,'reason':spec['reason'],'scope':'Bounded XML patch only. No source overwrite. Update scene expectations then import this candidate; re-render and re-review. No arbitrary unverified code executed.'}
            write_json(stage/'patch-report.json',report)
    return report
