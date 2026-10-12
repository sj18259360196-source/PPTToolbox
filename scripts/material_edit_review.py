"""Verify picture changes in attached PPTX copies. Structural evidence only."""
from __future__ import annotations
import hashlib
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
                parent = picture.getparent()
                while parent is not None:
                    if parent.tag == '{'+NS['p']+'}grpSp':
                        points = [_transform(parent, point, True) for point in points]
                        position = _transform(parent, position, True)
                    parent = parent.getparent()
                a, b, c, center = points
                size = [math.dist(a, b)/12700, math.dist(a, c)/12700]
                result[key] = {'slide': index, 'slide_id': slide.get('id'), 'name': name,
                    'ooxml_id': identity.get('id'), 'center_pt': [v/12700 for v in center],
                    'position_pt': [v/12700 for v in position],
                    'size_pt': size, 'embedded_image_sha256': hashlib.sha256(package.read(image_part)).hexdigest(),
                    'image_part': image_part}
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
