"""Phase-2 scene assembly. Geometry conversion is deterministic; vision is NOT.
Regional inputs use local reference pixels. Existing full scenes keep their geometry.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from PIL import Image
from common import read_json, write_json, sha256, resolve_asset, walk_objects
from validate_scene import validate
from evidence_contract import (image_size, logical_bounds, required_review, review_mapping,
                               normalize_regions, validate_local_coverage)

EDIT = {'text':'text','shape':'shape','line':'shape','connector':'shape','path':'path',
        'image':'image_replace','table':'table','chart':'data_chart','group':'group'}
ROLES = {'background','header','content','diagram','chart','table','photo','decoration','footer'}


def native_image_issues(objects, preserved_images=()):
    from material_routes import generated_illustration
    issues = []
    for obj in walk_objects(objects):
        if obj.get('kind') != 'image':
            continue
        if obj['id'] in preserved_images:
            continue
        try:
            if generated_illustration(obj):continue
        except ValueError as exc:
            issues.append(obj['id']+': '+str(exc))
        if obj.get('asset_role') in {'icon','logo'}:
            issues.append(obj['id'] + ': icons/logos require native paths or shapes')
        if obj.get('raster_content') not in {'photograph','texture','continuous_tone_artwork'} or len(obj.get('raster_reason','').strip()) < 12:
            issues.append(obj['id'] + ': raster requires explicit raster_content and source-specific raster_reason; reconstruct vector-like artwork as native geometry')
    return issues


def identifier(value, label='id'):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}',value):
        raise ValueError(f'{label}: use 1..40 ASCII letters, digits, - or _; start with a letter/digit')
    return value


def keys(value, required, optional=(), label='result'):
    if not isinstance(value,dict): raise ValueError(f'{label}: expected an object')
    missing=set(required)-value.keys(); extra=value.keys()-set(required)-set(optional)
    if missing or extra: raise ValueError(f'{label}: missing {sorted(missing)}, unknown {sorted(extra)}')


def text(value, label, empty=False):
    if not isinstance(value,str) or (not empty and not value.strip()): raise ValueError(f'{label}: nonempty text required')
    return value


def text_list(value, label):
    if not isinstance(value,list) or any(not isinstance(x,str) or not x.strip() for x in value):
        raise ValueError(f'{label}: expected a list of nonempty strings')
    return value


def valid_plan(value, size):
    keys(value, ['regions'], ['notes','uncertainties','element_scope'])
    if not isinstance(value['regions'],list) or not value['regions']: raise ValueError('regions: at least one region required')
    seen=set(); rows=[]
    for row in value['regions']:
        keys(row,['id','bbox','role','summary'],['local_review'])
        rid=identifier(row['id'],'region id')
        if rid.casefold() in seen or rid.casefold()=='full': raise ValueError('Duplicate/reserved region id: '+rid)
        seen.add(rid.casefold())
        normalize_regions([{'id':rid,'bbox':row['bbox']}],size)
        if row['role'] not in ROLES: raise ValueError('region role must be one of '+', '.join(sorted(ROLES)))
        text(row['summary'],'region summary')
        if 'local_review' in row and type(row['local_review']) is not bool: raise ValueError('local_review must be boolean')
        rows.append({**row,'local_review':row.get('local_review',row['role'] in {'diagram','chart','table'})})
    result = {'regions':rows, 'notes':value.get('notes',''), 'uncertainties':text_list(value.get('uncertainties',[]),'uncertainties')}
    if 'element_scope' in value:
        from element_scope import validate_plan
        result['element_scope'] = copy.deepcopy(validate_plan(value['element_scope'], [r['id'] for r in rows]))
    return result


def input_mapping(canvas, size, mode='uniform'):
    iw,ih=size; w,h=canvas['width'],canvas['height']
    if mode=='uniform':
        if abs(iw*h/w-ih)>1.01:
            raise ValueError('Reference/target aspect ratio differs by more than rounding. Use an explicit stretch decision or import a scene with reviewed mapping; do not silently distort.')
        k=w/iw
        return {'scale_x':1/k,'scale_y':1/k,'offset_x':0,'offset_y':0}
    if mode=='explicit_stretch':
        return {'scale_x':iw/w,'scale_y':ih/h,'offset_x':0,'offset_y':0}
    raise ValueError('Unsupported input mapping')


def import_file(source:Path, project:Path, folder='assets'):
    source=source.resolve()
    if not source.is_file(): raise FileNotFoundError(source)
    if source.suffix.lower() in {'.ttf','.otf','.ttc','.woff','.woff2','.key','.pem'}:
        raise ValueError('Fonts/credentials are not project assets handled by this importer')
    # Persistent, content-addressed assets. Never overwrite a different existing file.
    name=sha256(source)+source.suffix.lower()
    target=project/folder/name; target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and sha256(target)!=sha256(source): raise ValueError('Asset content collision')
    if not target.exists(): shutil.copyfile(source,target)
    return target.relative_to(project).as_posix()


def import_scene(scene_path:Path, project:Path):
    scene=read_json(scene_path); errors=validate(scene,scene_path.parent)
    if errors: raise ValueError('Scene import errors: '+'; '.join(errors[:12]))
    scene=copy.deepcopy(scene); pages=[]
    for i,s in enumerate(scene['slides'],1):
        ref=resolve_asset(scene_path.parent,s.get('reference',''))
        size=image_size(ref); rel=f'input/slide-{i:03}{ref.suffix.lower()}'
        (project/'input').mkdir(parents=True,exist_ok=True);shutil.copyfile(ref,project/rel)
        s['reference']=rel
        # Enforce an explicit and usable comparison transform at import time.
        review_mapping(scene,s,size)
        for obj in walk_objects(s['objects']):
            if obj['kind']=='image':obj['asset']=import_file(resolve_asset(scene_path.parent,obj['asset']),project)
        for unit in s.get('element_scope', {}).get('units', []):
            if 'source' in unit:
                unit['source']['asset'] = import_file(resolve_asset(scene_path.parent,unit['source']['asset']),project)
        pages.append({'id':s['id'],'index':i,'reference':rel,'size':size,'sha256':sha256(project/rel),
                      'imported_slide':s,'plan':None,'fragments':{},'source_review':None})
    return scene['canvas'],scene.get('title','Reference rebuild'),pages


def implicit_component_cover(components, objects):
    """Catch default ordering that paints an opaque card over a component.

    This is intentionally limited to unrotated solid rectangles and the safe
    central bands of default rounded rectangles. It is not a visibility audit.
    """
    for cover in objects:
        style=cover.get('style',{})
        if (cover.get('kind')!='shape' or cover.get('geometry') not in {'rect','round_rect'}
                or cover.get('rotation',0) or cover.get('adjustments')
                or not style.get('fill') or style.get('fill_alpha',1)!=1
                or 'gradient' in style or len(cover.get('bbox',[]))!=4):
            continue
        x,y,w,h=cover['bbox']
        if w<=0 or h<=0:continue
        bands=[[x,y,x+w,y+h]]
        if cover['geometry']=='round_rect':
            # Default Office corner adjustment is 1/6 of the short side;
            # inset by 1/4 leaves a conservative, certainly filled cross.
            inset=min(w,h)/4
            bands=[[x+inset,y,x+w-inset,y+h],[x,y+inset,x+w,y+h-inset]]
        for component in components:
            box=logical_bounds(component)
            if any(box[0]>b[0]+1 and box[1]>b[1]+1 and
                   box[2]<b[2]-1 and box[3]<b[3]-1 for b in bands):
                return component['id'],cover['id']
    return None


def fragment_digest(payload):
    """Identity of the complete previous local payload, including ordering."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def merge_fragment_revision(previous, result):
    """Replace selected top-level records; preserve all other payload data."""
    keys(result, ['action', 'base_fragment_sha256', 'reason'], ['objects', 'components'])
    if result['action'] != 'revise_objects':
        raise ValueError('Expected revise_objects action')
    text(result['reason'], 'object revision reason')
    if not isinstance(previous, dict):
        raise ValueError('Object revision requires a previous regional fragment')
    if result['base_fragment_sha256'] != fragment_digest(previous):
        raise ValueError('Stale previous fragment hash')
    merged = copy.deepcopy(previous)
    replacements = 0
    for field in ('objects', 'components'):
        rows = result.get(field, [])
        if not isinstance(rows, list):
            raise ValueError(field+' replacements must be a list')
        old = previous.get(field, [])
        positions = {obj['id']: i for i, obj in enumerate(old)}
        seen = set()
        for obj in rows:
            if not isinstance(obj, dict):
                raise ValueError('Replacement must be a complete object/component')
            oid = identifier(obj.get('id'))
            if oid not in positions or oid in seen:
                raise ValueError('Replacement ID must name a unique existing top-level '+field+' record: '+oid)
            seen.add(oid)
            merged[field][positions[oid]] = copy.deepcopy(obj)
            replacements += 1
    if not replacements:
        raise ValueError('Provide at least one object or component replacement')
    if merged == previous:
        raise ValueError('Object revision contains no change')
    # Original source_notes and global asset/relationship decisions are retained.
    # The response record stores the new reason. Compilation validates the whole
    # merged region; changed routing, membership/order or decisions use full payloads.
    return merged


def compile_fragment(page, region, payload, canvas, project):
    keys(payload,['objects','source_notes'],['relationship_ids','uncertainties','components','draw_order','asset_decisions','scope_bindings'])
    if not isinstance(payload['objects'],list): raise ValueError('objects must be an array')
    if not payload['objects'] and not payload.get('components'): raise ValueError('objects: empty regions cannot be marked reconstructed')
    if not isinstance(payload.get('components',[]),list):raise ValueError('components must be an array')
    text(payload['source_notes'],'source_notes')
    text_list(payload.get('uncertainties',[]),'uncertainties')
    from components import compile_component
    raw=[compile_component(s) for s in payload.get('components',[])]+copy.deepcopy(payload['objects']); prefix=f'{page["id"]}.{region["id"]}.'
    local=[]
    def collect(rows):
        for obj in rows:
            if not isinstance(obj,dict):raise ValueError('objects must contain object records')
            identifier(obj.get('id'),'local object id'); local.append(obj['id'])
            if obj.get('kind')=='group': collect(obj.get('children',[]))
    collect(raw)
    if len(local)!=len(set(local)):raise ValueError('Duplicate local object IDs')
    from task_contracts import validate_asset_decisions
    decisions=validate_asset_decisions(payload.get('asset_decisions',[]),set(local))
    from element_scope import validate_outputs
    scope = (page.get('plan') or {}).get('element_scope')
    preserved = set()
    if scope is not None:
        preserved = validate_outputs(scope, raw, project, region_id=region['id'],
                                     bindings=payload.get('scope_bindings'), check_native=False)
    elif 'scope_bindings' in payload:
        raise ValueError('scope_bindings requires a page element_scope')
    if page.get('native_first'):
        from material_routes import generated_illustration
        by_target = {row['target_id']: row for row in decisions}
        for item in walk_objects(raw):
            if item.get('kind') != 'image':
                continue
            oid = item['id']
            exception=generated_illustration(item,project) or oid in preserved
            if (item.get('asset_role') in {'icon', 'logo'} and not exception) or (region['role'] in {'chart','table'} and oid not in preserved):
                raise ValueError(oid + ': native reconstruction required; use shapes/paths, editable text, tables or data charts')
            if not exception and item.get('raster_content') not in {'photograph','texture','continuous_tone_artwork'}:
                raise ValueError(oid + ': raster_content required; vector-like illustrations and icons must use native shapes/paths')
            if len(item.get('raster_reason','').strip()) < 12:
                raise ValueError(oid + ': raster_reason must describe source details that cannot reasonably be represented by native geometry')
            decision = by_target.get(oid)
            expected_route = {'crop':'crop','generated':'generated','external':'external','user':'user_asset'}.get(item.get('source_kind'))
            if decision is None or decision['route'] == 'native' or (expected_route and decision['route'] != expected_route):
                raise ValueError(oid + ': each raster object requires an asset_decision matching its actual source route')
    if 'draw_order' in payload:
        order=payload['draw_order'];top_ids=[o['id'] for o in raw]
        if not isinstance(order,list) or len(order)!=len(top_ids) or any(not isinstance(v,str) for v in order) or set(order)!=set(top_ids):raise ValueError('draw_order must list each top-level component/object ID exactly once, back to front')
        by_id={o['id']:o for o in raw};raw=[by_id[i] for i in order]
    elif payload.get('components'):
        covered=implicit_component_cover(raw[:len(payload['components'])],payload['objects'])
        if covered:
            raise ValueError('Default component-first order places '+covered[0]+' behind opaque '+covered[1]+
                             '; supply draw_order with every top-level ID, background before components before labels. No order was changed.')
    m=page['mapping']; sx,sy=m['scale_x'],m['scale_y']; ox,oy=m['offset_x'],m['offset_y']
    left,top,_,_=region['bbox']
    def point(x,y):return [(x+left-ox)/sx,(y+top-oy)/sy]
    def convert(rows):
        for obj in rows:
            kind=obj.get('kind')
            if kind not in EDIT:raise ValueError(f'{obj["id"]}: unknown kind {kind!r}')
            obj['id']=prefix+obj['id']
            obj.setdefault('editability',EDIT[kind])
            obj.setdefault('evidence',{'status':'inferred','note':'Regional reconstruction; '+payload['source_notes']})
            if 'bbox' in obj:
                if not isinstance(obj['bbox'],list) or len(obj['bbox'])!=4:raise ValueError('bbox is local px xywh, four numbers')
                x,y,w,h=obj['bbox'];p=point(x,y);obj['bbox']=[*p,w/sx,h/sy]
                # Only clip subpixel screenshot rounding at page boundaries, not real overflow.
                for j,limit in [(0,canvas['width']),(1,canvas['height'])]:
                    if obj['bbox'][j]+obj['bbox'][j+2]>limit and obj['bbox'][j]+obj['bbox'][j+2]-limit<=1.01/min(sx,sy):
                        obj['bbox'][j+2]=limit-obj['bbox'][j]
            if 'points' in obj:obj['points']=[point(*p) for p in obj['points']]
            if 'commands' in obj:
                commands=[]
                for cmd in obj['commands']:
                    row=[cmd[0]]
                    if len(cmd[1:])%2:raise ValueError('path command coordinates must come in x,y pairs')
                    for k in range(1,len(cmd),2):row.extend(point(cmd[k],cmd[k+1]))
                    commands.append(row)
                obj['commands']=commands
            if 'column_widths' in obj:obj['column_widths']=[v/sx for v in obj['column_widths']]
            if 'row_heights' in obj:obj['row_heights']=[v/sy for v in obj['row_heights']]
            for endpoint in ('begin','end'):
                if endpoint in obj:
                    target=obj[endpoint]['object_id']
                    if target in local:obj[endpoint]['object_id']=prefix+target
            if kind=='group':convert(obj['children'])
    convert(raw)
    if scope is not None:
        scoped = copy.deepcopy(scope)
        scoped['units'] = [u for u in scoped['units'] if u['region_id'] == region['id']]
        scoped['bindings'] = [{'unit_id': row['unit_id'], 'object_ids': [prefix + oid for oid in row['object_ids']]}
                              for row in payload['scope_bindings']]
        validate_outputs(scoped, raw, project)
    # Validate with already committed sibling fragments to support cross-region connectors.
    siblings=[]
    for rid,frag in page['fragments'].items():
        if rid!=region['id']:siblings.extend(frag['objects'])
    temp={'version':'1.0','canvas':canvas,'slides':[{'id':page['id'],'objects':siblings+raw}]}
    if scope is not None:
        from element_scope import compiled_scope
        shadow = copy.deepcopy(page)
        shadow['fragments'][region['id']] = {'raw': payload}
        combined = compiled_scope(shadow)
        present = {b['unit_id'] for b in combined['bindings']}
        combined['units'] = [u for u in combined['units'] if u['id'] in present]
        for unit in combined['units']:
            if unit['owner_id'] not in present: unit['owner_id'] = None
        temp['slides'][0]['element_scope'] = combined
    errors=validate(temp,project)
    if errors:raise ValueError('Fragment errors: '+'; '.join(errors[:16]))
    relations=text_list(payload.get('relationship_ids',[]),'relationship_ids')
    if set(relations)-set(local):raise ValueError('relationship_ids must be IDs from this fragment')
    return {'objects':raw,'source_notes':payload['source_notes'],'relationship_ids':[prefix+x for x in relations],
            'uncertainties':payload.get('uncertainties',[]),'asset_decisions':copy.deepcopy(decisions),'raw':copy.deepcopy(payload)}


def assemble(state):
    slides=[]
    for page in state['pages']:
        if page.get('imported_slide') is not None:
            slides.append(copy.deepcopy(page['imported_slide']));continue
        if not page.get('plan'):raise ValueError('Page plan incomplete: '+page['id'])
        objects=[];locals_=[];rels=[]
        for region in page['plan']['regions']:
            frag=page['fragments'].get(region['id'])
            if not frag:raise ValueError('Region incomplete: '+page['id']+'/'+region['id'])
            objects.extend(copy.deepcopy(frag['objects']));rels.extend(frag['relationship_ids'])
            if region['local_review']:locals_.extend(o['id'] for o in frag['objects'])
        slides.append({'id':page['id'],'reference':page['reference'],'reference_mapping':'Regional local pixels mapped by the recorded affine transform',
                       'review_mapping':page['mapping'],'objects':objects,
                       'review_requirements':{'local_objects':sorted(set(locals_)),'relationship_objects':sorted(set(rels))}})
        from element_scope import compiled_scope
        scope = compiled_scope(page)
        if scope is not None: slides[-1]['element_scope'] = scope
    return {'version':'1.0','title':state['title'],'canvas':state['canvas'],'slides':slides}


def auto_regions(scene, pages):
    """Deterministic ROI proposals. Covers declared objects, not omitted source content."""
    result=[]
    for idx,(slide,page) in enumerate(zip(scene['slides'],pages),1):
        size=page['size'];m=review_mapping(scene,slide,size);required=required_review(slide)
        lookup={o['id']:o for o in walk_objects(slide['objects'])};assigned=set();regions=[]
        def add(ids, basebox=None):
            boxes=[]
            if basebox:boxes.append(basebox)
            for oid in ids:
                b=logical_bounds(lookup[oid]);boxes.append([b[0]*m['scale_x']+m['offset_x'],b[1]*m['scale_y']+m['offset_y'],b[2]*m['scale_x']+m['offset_x'],b[3]*m['scale_y']+m['offset_y']])
            if not boxes:return
            box=[max(0,math.floor(min(b[0] for b in boxes))-8),max(0,math.floor(min(b[1] for b in boxes))-8),
                 min(size[0],math.ceil(max(b[2] for b in boxes))+8),min(size[1],math.ceil(max(b[3] for b in boxes))+8)]
            if box[0]>=box[2] or box[1]>=box[3]:raise ValueError('Required object has no valid visible review crop')
            regions.append({'id':f'roi-{len(regions)+1:03}','bbox':box,'object_ids':sorted(ids),'note':'Automatically proposed bounds; review against source, not proof of semantics'})
            assigned.update(ids)
        review_plan=page.get('review_plan') if page.get('imported_slide') is not None else None
        plan=review_plan or page.get('plan') or {}
        for region in plan.get('regions',[]):
            if review_plan:
                ids=set(region['object_ids']) & lookup.keys()
            elif page.get('imported_slide') is not None:
                prefix=page['id']+'.'+region['id']+'.'
                ids={oid for oid in lookup if oid.startswith(prefix)}
            else:
                ids={o['id'] for o in walk_objects(page['fragments'].get(region['id'],{}).get('objects',[]))}
            mandatory=ids & set(required['local_objects'])
            # These are review crops, not write bounds. Include current geometry
            # even when a retained object has moved beyond the old region.
            if mandatory or region['local_review']:add(ids if region['local_review'] else mandatory,region['bbox'])
        # Imported scenes may have semantic groups but no page-plan fragments.
        # Review each bounded group in context instead of hundreds of tiny leaf crops.
        # Large slide-wide groups are descended; every required ID remains covered.
        def group_regions(objects):
            for obj in objects:
                if obj['kind'] != 'group':continue
                ids={x['id'] for x in walk_objects([obj])} & set(required['local_objects']) - assigned
                bounds=logical_bounds(obj)
                area=(bounds[2]-bounds[0])*(bounds[3]-bounds[1])
                if ids and area <= .45*scene['canvas']['width']*scene['canvas']['height']:
                    add(ids)
                else:group_regions(obj['children'])
        group_regions(slide['objects'])
        for oid in required['local_objects']:
            if oid not in assigned:add({oid})
        regions=normalize_regions(regions,size);validate_local_coverage(scene,slide,size,regions)
        result.append({'index':idx,'regions':regions})
    return {'slides':result}


def freeze_scene(state, project, run_dir):
    scene=assemble(state);errors=validate(scene,project)
    for page, slide in zip(state['pages'], scene['slides']):
        if page.get('native_first'):
            from element_scope import validate_outputs
            preserved = validate_outputs(slide['element_scope'], slide['objects'], project) if 'element_scope' in slide else set()
            errors.extend(native_image_issues(slide['objects'], preserved))
    if errors:raise ValueError('Assembled scene errors: '+'; '.join(errors[:16]))
    files=set(s['reference'] for s in scene['slides'])
    for s in scene['slides']:
        files.update(u['source']['asset'] for u in s.get('element_scope', {}).get('units', []) if 'source' in u)
        files.update(o['asset'] for o in walk_objects(s['objects']) if o['kind']=='image')
        for obj in walk_objects(s['objects']):
            if obj.get('raster_content')=='generated_illustration':
                files.update(obj['generation_decision'][k] for k in ('reference','drawing') if k in obj['generation_decision'])
    for rel in sorted(files):
        src=resolve_asset(project,rel);dst=run_dir/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    refs=[{'slide':i,'path':p['reference'],'size':p['size'],'sha256':p['sha256']} for i,p in enumerate(state['pages'],1)]
    write_json(run_dir/'input/references.json',refs);write_json(run_dir/'scene.json',scene)
    write_json(run_dir/'regions.json',auto_regions(scene,state['pages']))
    tracked={rel:sha256(run_dir/rel) for rel in files}
    tracked.update({rel:sha256(run_dir/rel) for rel in ['scene.json','input/references.json','regions.json']})
    write_json(run_dir/'frozen-inputs.json',tracked)
    return scene,tracked
