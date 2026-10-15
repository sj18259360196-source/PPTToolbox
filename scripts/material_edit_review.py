"""Verify picture changes in attached PPTX copies. Structural evidence only."""
from __future__ import annotations
import hashlib
import io
import posixpath
from lxml import etree as ET
import math
from pathlib import Path
from zipfile import ZipFile
from inspect_pptx import NS, xml, relationships, target_part
from common import sha256

TOLERANCE_PT = .05


def _transform(node, point, group=False):
    tag = 'p:grpSpPr/a:xfrm' if group else 'p:spPr/a:xfrm'
    transform = node.find(tag, NS)
    if transform is None:
        raise ValueError('Picture/group transform is missing')
    off, ext = transform.find('a:off', NS), transform.find('a:ext', NS)
    if off is None or ext is None:
        raise ValueError('Picture/group geometry is incomplete')
    x, y = float(off.get('x')), float(off.get('y'))
    w, h = float(ext.get('cx')), float(ext.get('cy'))
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError('Picture/group geometry must be positive')
    if group:
        child_off, child_ext = transform.find('a:chOff', NS), transform.find('a:chExt', NS)
        if child_off is None or child_ext is None:
            raise ValueError('Group child transform is incomplete')
        cw, ch = float(child_ext.get('cx')), float(child_ext.get('cy'))
        ox, oy = float(child_off.get('x')), float(child_off.get('y'))
        if not all(math.isfinite(v) for v in (cw, ch, ox, oy)) or cw <= 0 or ch <= 0:
            raise ValueError('Group child geometry must be positive')
        px = x+(point[0]-ox)*w/cw
        py = y+(point[1]-oy)*h/ch
    else:
        px, py = x+point[0]*w, y+point[1]*h
    cx, cy = x+w/2, y+h/2
    dx, dy = px-cx, py-cy
    if transform.get('flipH') in {'1', 'true'}: dx = -dx
    if transform.get('flipV') in {'1', 'true'}: dy = -dy
    rotation = float(transform.get('rot', '0'))
    if not math.isfinite(rotation):
        raise ValueError('Picture/group rotation must be finite')
    angle = math.radians(rotation/60000)
    return (cx+dx*math.cos(angle)-dy*math.sin(angle),
            cy+dx*math.sin(angle)+dy*math.cos(angle))


def image_signature(data):
    """Decoded pixels verify content even if Office changes image container bytes."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 16_000_000:
            raise ValueError('Decoded replacement exceeds 16 million pixels')
        image.load()
        rgba=image.convert('RGBA')
        return {'size':list(rgba.size), 'rgba_sha256':hashlib.sha256(rgba.tobytes()).hexdigest(),
                'has_transparent_pixels':rgba.getextrema()[3][0]<255}


def image_signature_optional(data):
    # Historical structural validation also accepts vector/large media. Do not
    # silently certify decoded alpha when those media cannot be inspected here.
    try:
        return image_signature(data)
    except (ValueError, OSError):
        return {'decode_status':'unavailable', 'encoded_sha256':hashlib.sha256(data).hexdigest()}


def _pictures(path):
    result = {}
    with ZipFile(path) as package:
        if len(package.namelist()) != len(set(package.namelist())):
            raise ValueError('Duplicate PPTX package members')
        presentation = xml(package.read('ppt/presentation.xml'))
        rels = relationships(package, 'ppt/presentation.xml')
        for index, slide in enumerate(presentation.findall('p:sldIdLst/p:sldId', NS), 1):
            part = target_part('ppt/presentation.xml', rels[slide.get('{'+NS['r']+'}id')]['target'])
            tree, picture_rels = xml(package.read(part)), relationships(package, part)
            for picture in tree.findall('.//p:pic', NS):
                identity = picture.find('p:nvPicPr/p:cNvPr', NS)
                name = identity.get('name', '') if identity is not None else ''
                if not name:
                    raise ValueError('Picture requires a stable object name')
                key = (slide.get('id'), name)
                if key in result:
                    raise ValueError('Ambiguous picture name on slide: '+name)
                blip = picture.find('p:blipFill/a:blip', NS)
                embed = blip.get('{'+NS['r']+'}embed') if blip is not None else None
                rel = picture_rels.get(embed)
                if not rel or rel['external'] or not rel['type'].endswith('/image'):
                    raise ValueError('Picture must contain an embedded image: '+name)
                image_part = target_part(part, rel['target'])
                points = [_transform(picture, p) for p in ((0, 0), (1, 0), (0, 1), (.5, .5))]
                off = picture.find('p:spPr/a:xfrm/a:off', NS)
                position = (float(off.get('x')), float(off.get('y')))
                ancestors=[]
                parent = picture.getparent()
                while parent is not None:
                    if parent.tag == '{'+NS['p']+'}grpSp':
                        group_id=parent.find('p:nvGrpSpPr/p:cNvPr',NS)
                        ancestors.append({'id':group_id.get('id'), 'name':group_id.get('name')})
                        points = [_transform(parent, point, True) for point in points]
                        position = _transform(parent, position, True)
                    parent = parent.getparent()
                a, b, c, center = points
                size = [math.dist(a, b)/12700, math.dist(a, c)/12700]
                result[key] = {'slide': index, 'slide_id': slide.get('id'), 'name': name,
                    'ooxml_id': identity.get('id'), 'center_pt': [v/12700 for v in center],
                    'position_pt': [v/12700 for v in position],
                    'size_pt': size, 'embedded_image_sha256': hashlib.sha256(package.read(image_part)).hexdigest(),
                    'image_part': image_part, 'group_ancestors':ancestors,
                    'z_order':list(picture.getparent()).index(picture),
                    'crop':{edge:float((picture.find('p:blipFill/a:srcRect',NS).get(edge,'0') if picture.find('p:blipFill/a:srcRect',NS) is not None else '0'))/100000 for edge in ['l','t','r','b']},
                    'rotation':float(picture.find('p:spPr/a:xfrm',NS).get('rot','0'))/60000,
                    'flip':{key:picture.find('p:spPr/a:xfrm',NS).get(key,'0') for key in ['flipH','flipV']},
                    'effects':ET.tostring(picture.find('p:blipFill/a:blip',NS)).decode('utf-8'),
                    'pixel_signature':image_signature_optional(package.read(image_part))}
    return result


def validate_image_edits(current: Path, copies: list[Path]):
    """Require move, resize and changed embedded bytes on named source pictures.

    Independent copies may prove different actions. Native text edits, crop-only
    edits, removed objects, or declarations cannot supply picture-edit evidence.
    Group transforms are applied to picture centers and edge lengths. Masks and
    crops stay in the package; their visual appearance is outside this check.
    """
    current = Path(current).resolve()
    if not isinstance(copies, list) or not copies:
        raise ValueError('Attach edited PPTX copies proving image_move, image_resize and image_replace')
    source_hash = sha256(current)
    original = _pictures(current)
    if not original:
        raise ValueError('Source candidate has no named embedded pictures')
    actions = {'image_move': [], 'image_resize': [], 'image_replace': []}
    reports = []
    for value in copies:
        path = Path(value).resolve()
        if path == current:
            raise ValueError('Edited evidence must be a separate PPTX copy')
        copy_hash = sha256(path)
        pictures = _pictures(path)
        for key in original.keys() & pictures.keys():
            old, new = original[key], pictures[key]
            evidence = {'file': str(path), 'sha256': copy_hash, 'slide': old['slide'],
                        'slide_id': old['slide_id'], 'name': old['name'], 'before': old, 'after': new}
            if any(abs(a-b)>TOLERANCE_PT for a,b in zip(old['position_pt'], new['position_pt'])):
                actions['image_move'].append(evidence)
            if any(abs(a-b)>TOLERANCE_PT for a,b in zip(old['size_pt'], new['size_pt'])):
                actions['image_resize'].append(evidence)
            if old['embedded_image_sha256'] != new['embedded_image_sha256']:
                actions['image_replace'].append(evidence)
        if sha256(path) != copy_hash:
            raise ValueError('Edited evidence changed during inspection')
        reports.append({'file': str(path), 'sha256': copy_hash, 'retained_named_pictures': len(original.keys() & pictures.keys())})
    if sha256(current) != source_hash:
        raise ValueError('Original candidate changed during inspection')
    missing = [kind for kind, records in actions.items() if not records]
    if missing:
        raise ValueError('Attached PPTX copies lack actual picture changes: '+', '.join(missing))
    return {'format': 'image-edit-structure/1', 'source_sha256': source_hash,
            'verified_actions': actions, 'copies': reports, 'tolerance_pt': TOLERANCE_PT,
            'scope': 'PPTX_structural_changes_only', 'office_ui_verification': 'not_run',
            'visual_review': 'required', 'save_reopen_verification': 'not_run'}


def picture_snapshot(path, slide, name):
    rows=[r for r in _pictures(path).values() if r['slide']==slide and r['name']==name]
    if len(rows)!=1:raise ValueError('Picture name must resolve uniquely')
    return rows[0]


def geometry_value(row):
    return dict(zip(['left','top','width','height','rotation'],row['position_pt']+row['size_pt']+[row['rotation']]))


def _picture_edit_groups(picture):
    """Shared read-only parent constraints for preparation and package execution."""
    groups=[];parent=picture.getparent()
    while parent is not None:
        if parent.tag=='{'+NS['p']+'}grpSp':groups.append(parent)
        parent=parent.getparent()
    if len(groups)>1:raise ValueError('Nested picture groups are unsupported')
    for group in groups:
        t=group.find('p:grpSpPr/a:xfrm',NS)
        if t is None or float(t.get('rot','0')) or any(t.get(k) in {'1','true'} for k in ['flipH','flipV']):
            raise ValueError('Rotated/flipped picture groups are unsupported')
        # Reject missing, nonfinite or nonpositive group dimensions before writing.
        _transform(group,(0,0),True)
    return groups


def picture_edit_geometry(picture):
    """Read slide-point geometry from an already-loaded picture, without reopening media."""
    if picture.tag!='{'+NS['p']+'}pic':raise ValueError('Embedded picture node required')
    groups=_picture_edit_groups(picture)
    points=[_transform(picture,p) for p in ((0,0),(1,0),(0,1))]
    off=picture.find('p:spPr/a:xfrm/a:off',NS)
    position=(float(off.get('x')),float(off.get('y')))
    for group in groups:
        points=[_transform(group,point,True) for point in points]
        position=_transform(group,position,True)
    a,b,c=points
    return {'left':position[0]/12700,'top':position[1]/12700,
            'width':math.dist(a,b)/12700,'height':math.dist(a,c)/12700,
            'rotation':float(picture.find('p:spPr/a:xfrm',NS).get('rot','0'))/60000}


def edit_picture_package(source, destination, operations):
    """Preflight all package edits, then write one new file; never delete a shape.

    Slide coordinates are points. Single unrotated/unflipped groups are mapped
    through chOff/chExt. Nested/rotated/flipped groups are rejected before writing.
    Replacement adds a private image relationship to retain shared-image neighbors.
    """
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or destination.exists():raise ValueError('Package edit needs a new independent destination')
    with ZipFile(source) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate package members')
        if sum(i.file_size for i in z.infolist())>256*1024*1024:raise ValueError('Package exceeds 256 MiB edit limit')
        members={n:z.read(n) for n in z.namelist()}
        presentation=xml(members['ppt/presentation.xml']);rels=relationships(z,'ppt/presentation.xml')
        slides=[target_part('ppt/presentation.xml',rels[n.get('{'+NS['r']+'}id')]['target']) for n in presentation.findall('p:sldIdLst/p:sldId',NS)]
    trees={};checks=[]
    for index,op in enumerate(operations):
        part=slides[op['slide']-1] if op['slide']<=len(slides) else None
        if not part:raise ValueError('Slide index exceeds deck')
        tree=trees.setdefault(part,xml(members[part]))
        matches=tree.xpath('.//p:cNvPr[@name=$name]',namespaces=NS,name=op['name'])
        if len(matches)!=1 or matches[0].getparent().getparent().tag!='{'+NS['p']+'}pic':
            raise ValueError('Exact name must resolve to one embedded picture')
        picture=matches[0].getparent().getparent();groups=_picture_edit_groups(picture)
        before=picture_snapshot(source,op['slide'],op['name'])
        if op['op']=='picture.transform':
            prior=geometry_value(before)
            if any(abs(prior[k]-op['expected'][k])>.05 for k in prior):raise ValueError('Stale picture geometry expectation')
            if all(abs(prior[k]-op['value'][k])<=.05 for k in prior):raise ValueError('Picture transform must change geometry')
            v=op['value'];x,y,w,h=[v[k]*12700 for k in ['left','top','width','height']]
            if groups:
                t=groups[0].find('p:grpSpPr/a:xfrm',NS)
                off,ext,co,ce=[t.find('a:'+k,NS) for k in ['off','ext','chOff','chExt']]
                sx=float(ce.get('cx'))/float(ext.get('cx'));sy=float(ce.get('cy'))/float(ext.get('cy'))
                if not math.isclose(sx,sy,rel_tol=1e-9) and (prior['rotation'] or v['rotation']):
                    raise ValueError('Rotated pictures in nonuniform scaled groups require a separate supported edit')
                x=(x-float(off.get('x')))*sx+float(co.get('x'));y=(y-float(off.get('y')))*sy+float(co.get('y'));w*=sx;h*=sy
            t=picture.find('p:spPr/a:xfrm',NS);off=t.find('a:off',NS);ext=t.find('a:ext',NS)
            for key,val in [('x',x),('y',y)]:off.set(key,str(round(val)))
            for key,val in [('cx',w),('cy',h)]:ext.set(key,str(round(val)))
            t.set('rot',str(round(v['rotation']*60000)))
        else:
            if before['embedded_image_sha256']!=op['expected_sha256']:raise ValueError('Stale expected picture image hash')
            relative=Path(op['image'])
            if relative.is_absolute() or relative.drive or '..' in relative.parts:raise ValueError('Replacement image must be source-directory relative')
            image=source.parent/relative
            if any(p.is_symlink() or (p.exists() and getattr(p.stat(), 'st_file_attributes', 0) & 0x400)
                   for p in [image,*image.parents]):raise ValueError('Replacement symlink/junction forbidden')
            image=image.resolve()
            if not image.is_relative_to(source.parent) or not image.is_file():raise ValueError('Replacement image leaves source directory or is missing')
            data=image.read_bytes()
            if hashlib.sha256(data).hexdigest()!=op['image_sha256']:raise ValueError('Replacement image hash mismatch')
            signature=image_signature(data)
            if signature==before['pixel_signature']:raise ValueError('Replacement must change decoded picture pixels')
            from PIL import Image
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.format not in {'PNG','JPEG'}:raise ValueError('Replacement currently supports PNG/JPEG only')
                extension='png' if decoded.format=='PNG' else 'jpeg';mime='image/png' if extension=='png' else 'image/jpeg'
            media='ppt/media/r6-'+op['image_sha256']+'.'+extension
            members[media]=data
            rp=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
            rt=xml(members[rp]);rid='rIdPictureEdit'+str(index)
            while any(n.get('Id')==rid for n in rt):rid+='x'
            ET.SubElement(rt,'{'+NS['rel']+'}Relationship',Id=rid,Type=NS['r']+'/image',Target=posixpath.relpath(media,posixpath.dirname(part)))
            members[rp]=ET.tostring(rt,xml_declaration=True,encoding='UTF-8',standalone=True)
            blip=picture.find('p:blipFill/a:blip',NS)
            if blip is None or blip.get('{'+NS['r']+'}embed') is None:raise ValueError('Embedded picture required')
            if len(blip):raise ValueError('Picture with extended blip effects requires separate replacement support')
            blip.set('{'+NS['r']+'}embed',rid)
            if op['crop_policy']=='reset':
                crop=picture.find('p:blipFill/a:srcRect',NS)
                if crop is not None:picture.find('p:blipFill',NS).remove(crop)
            ct=xml(members['[Content_Types].xml']);ns='http://schemas.openxmlformats.org/package/2006/content-types'
            if not any(n.get('Extension')==extension for n in ct):ET.SubElement(ct,'{'+ns+'}Default',Extension=extension,ContentType=mime)
            members['[Content_Types].xml']=ET.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
        checks.append({'operation':op,'before':before,'method':'package_transform' if op['op']=='picture.transform' else 'package_relationship_replacement',
                       'identity_policy':'same OOXML shape node and id; no deletion/recreation'})
    for part,tree in trees.items():members[part]=ET.tostring(tree,xml_declaration=True,encoding='UTF-8',standalone=True)
    from zipfile import ZIP_DEFLATED
    with ZipFile(destination,'w',ZIP_DEFLATED) as z:
        for name,data in members.items():z.writestr(name,data)
    return checks


def _native_neighbors(path):
    """Leaf native text/shape content and slide geometry, independent of Office serialization."""
    result={}
    with ZipFile(path) as z:
        presentation=xml(z.read('ppt/presentation.xml'));rels=relationships(z,'ppt/presentation.xml')
        for i,slide in enumerate(presentation.findall('p:sldIdLst/p:sldId',NS),1):
            part=target_part('ppt/presentation.xml',rels[slide.get('{'+NS['r']+'}id')]['target']);tree=xml(z.read(part))
            for shape in tree.findall('.//p:sp',NS):
                identity=shape.find('p:nvSpPr/p:cNvPr',NS);t=shape.find('p:spPr/a:xfrm',NS)
                if identity is None or t is None:continue
                points=[_transform(shape,p) for p in [(0,0),(1,0),(0,1)]];parents=[];parent=shape.getparent()
                while parent is not None:
                    if parent.tag=='{'+NS['p']+'}grpSp':
                        points=[_transform(parent,p,True) for p in points]
                        identity2=parent.find('p:nvGrpSpPr/p:cNvPr',NS);parents.append(identity2.get('id'))
                    parent=parent.getparent()
                a,b,c=points
                key=(i,identity.get('name'))
                if key in result:raise ValueError('Ambiguous native neighbor name')
                result[key]={'id':identity.get('id'),'parents':parents,'order':list(shape.getparent()).index(shape),
                    'text':shape.xpath('.//a:t/text()',namespaces=NS),'rotation':t.get('rot','0'),
                    'geometry':[a[0]/12700,a[1]/12700,math.dist(a,b)/12700,math.dist(a,c)/12700]}
    return result


def verify_picture_package_edits(source, edited, package_checks, other_operations=(), *, office_saved=False):
    original=_pictures(source);current=_pictures(edited);checks=[]
    edited_names={(c['operation']['slide'],c['operation']['name']) for c in package_checks}
    shape_set_same=set(original)==set(current)
    neighbor_checks=[]
    for key,old in original.items():
        new=current.get(key)
        if new is None:continue
        if (old['slide'],old['name']) in edited_names:continue
        invariant=all(old[k]==new[k] for k in ['ooxml_id','group_ancestors','z_order','crop','rotation','flip','pixel_signature'])
        invariant &= all(abs(a-b)<=TOLERANCE_PT for k in ['position_pt','size_pt'] for a,b in zip(old[k],new[k]))
        neighbor_checks.append({'name':old['name'],'kind':'picture','unchanged':invariant})
    old_native=_native_neighbors(source);new_native=_native_neighbors(edited)
    native_set_same=set(old_native)==set(new_native)
    changed_native={(op['slide'],op['name']) for op in other_operations if op['op'] in {'text.set','shape.fill','table.cell'}}
    for key,old in old_native.items():
        if key in changed_native:continue
        new=new_native.get(key)
        same=new is not None and all(old[k]==new[k] for k in ['id','parents','order','text','rotation'])
        same &= new is not None and all(abs(a-b)<=TOLERANCE_PT for a,b in zip(old['geometry'],new['geometry']))
        neighbor_checks.append({'name':key[1],'kind':'native_shape','unchanged':same})
    for check in package_checks:
        op=check['operation'];before=check['before'];actual=picture_snapshot(edited,op['slide'],op['name'])
        identity=all(before[k]==actual[k] for k in ['ooxml_id','group_ancestors','z_order','flip'])
        transform=next((r['operation'] for r in package_checks if r['operation']['op']=='picture.transform' and (r['operation']['slide'],r['operation']['name'])==(op['slide'],op['name'])),None)
        desired_geometry=transform['value'] if transform else geometry_value(before)
        geometry_ok=all(abs(geometry_value(actual)[k]-desired_geometry[k])<=TOLERANCE_PT for k in desired_geometry)
        replacement=next((r['operation'] for r in package_checks if r['operation']['op']=='picture.replace' and (r['operation']['slide'],r['operation']['name'])==(op['slide'],op['name'])),None)
        desired_crop=before['crop'] if not replacement or replacement['crop_policy']=='preserve' else dict.fromkeys(['l','t','r','b'],0.)
        crop_ok=all(abs(actual['crop'][k]-desired_crop[k])<=.0001 for k in desired_crop)
        signature=image_signature((Path(source).parent/replacement['image']).read_bytes()) if replacement else before['pixel_signature']
        pixels_ok=signature==actual['pixel_signature']
        matches=identity and geometry_ok and crop_ok and pixels_ok and shape_set_same and native_set_same and all(r['unchanged'] for r in neighbor_checks)
        checks.append({**check,'kind':'picture','expected':desired_geometry if op['op']=='picture.transform' else signature,
            'actual':actual,'matches':matches,'identity_matches':identity,'geometry_matches':geometry_ok,
            'crop_matches':crop_ok,'decoded_pixels_match':pixels_ok,'save_reopen_verification':'Office_saved_package_readback' if office_saved else 'not_run',
            'visual_review':'required','gui_verification':'not_run'})
    return {'checks':checks,'preservation':{'picture_set_unchanged':shape_set_same,'native_shape_set_unchanged':native_set_same,
        'neighbor_checks':neighbor_checks,'transparent_pixels_verified_in_decoded_media':all('rgba_sha256' in c['actual']['pixel_signature'] for c in checks),
        'scope':'package identity/geometry/crop/media readback; effects and appearance need actual render inspection'}}
