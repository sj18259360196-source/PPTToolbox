"""Gradient probes and immutable scene proposals; no automatic adoption."""
import copy
import uuid
from pathlib import Path
from common import read_json, write_json, sha256, walk_objects

def preflight(project,args):
    from toolbox_manager.policy import plain_path
    from validate_scene import validate
    path=plain_path(project/args['scene'])
    if not path.is_relative_to(project): raise ValueError('Scene must be inside authorized project')
    from scene_preflight import inspect
    return inspect(path)


def select_versions(project,args):
    from toolbox_manager.policy import plain_path
    from graphics_recipe import digest
    from validate_scene import validate
    def load(spec):
        p=plain_path(project/spec['scene'])
        if not p.is_relative_to(project): raise ValueError('Scene outside project')
        if sha256(p)!=spec['sha256']: raise ValueError('Stale scene hash')
        return read_json(p),p
    base,path=load(args['base']);result=copy.deepcopy(base);selected=set();records=[];dependencies=[]
    for choice in args['selections']:
        other,other_path=load(choice)
        if other['canvas']!=base['canvas']: raise ValueError('Coordinate frames differ')
        slide=next(s for s in result['slides'] if s['id']==choice['slide'])
        source=next(s for s in other['slides'] if s['id']==choice['slide'])
        key=(choice['slide'],choice['id'])
        if key in selected: raise ValueError('Duplicate selection')
        selected.add(key)
        old=next(o for o in slide['objects'] if o['id']==choice['id'])
        new=next(o for o in source['objects'] if o['id']==choice['id'])
        if old['kind']!='group' or new['kind']!='group': raise ValueError('Only top-level semantic groups supported')
        if any(o['kind'] not in {'group','path'} for o in walk_objects([new])): raise ValueError('Native path groups only')
        for dep in choice['dependencies']:
            a=next(o for o in slide['objects'] if o['id']==dep)
            b=next(o for o in source['objects'] if o['id']==dep)
            if digest(a)!=digest(b): raise ValueError('Background dependency differs: '+dep)
            dependencies.append((choice['slide'],dep,digest(b)))
        slide['objects'][slide['objects'].index(old)]=copy.deepcopy(new)
        records.append({'id':choice['id'],'source':str(other_path),'source_sha256':choice['sha256'],
                        'before':digest(old),'after':digest(new),'dependencies':choice['dependencies']})
    for slide_id,dep,expected in dependencies:
        slide=next(s for s in result['slides'] if s['id']==slide_id)
        if digest(next(o for o in slide['objects'] if o['id']==dep))!=expected:
            raise ValueError('A later selection changed a background dependency: '+dep)
    errors=validate(result,path.parent)
    if errors: raise ValueError('; '.join(errors[:5]))
    # Return proposal in memory so existing relative assets retain their original base.
    return {'scene':result,'scene_base':str(path.parent),'selections':records,'base_sha256':args['base']['sha256'],
            'adopted':False,'mutated':False,'visual_review':'pending',
            'next':'Save proposal beside its scene_base, then use managed import/review; protect other objects'}

def probe(project,args):
    from graphics_recipe import compile_recipe
    from build_pptx import build
    from gradient_jobs import run_job
    from toolbox_manager.policy import plain_path
    directory=plain_path(project/'runs/gradient-probes'/uuid.uuid4().hex)
    directory.mkdir(parents=True,exist_ok=False)
    paths=[]
    for i,sample in enumerate(args['samples']):
        x=10+(i%3)*210;y=10+(i//3)*150;w,h=sample.get('size',[190,130])
        paths.append({'id':f'sample{i+1}','closed':True,'style':sample['style'],
                      'commands':[['M',x,y],['L',x+w,y],['L',x+w,y+h],['L',x,y+h],['Z']]})
    recipe={'format':'graphics-recipe/1','id':'probe','canvas':[640,10+150*((len(paths)+2)//3)],
            'paths':paths,'order':[p['id'] for p in paths]}
    scene=compile_recipe(recipe)['scene']
    scene['canvas']['background']=args.get('background','FFFFFF')
    write_json(directory/'recipe.json',recipe);write_json(directory/'scene.json',scene)
    build(directory/'scene.json',directory/'probe.pptx')
    result=run_job(project,'read_properties',{'pptx':str((directory/'probe.pptx').relative_to(project)),
        'pptx_sha256':sha256(directory/'probe.pptx'),'targets':[{'slide':1,'id':p['id']} for p in paths],
        'timeout_seconds':args.get('timeout_seconds',90),'_office_lock':args.get('_office_lock')})
    result.update(probe_directory=str(directory),profile='Office renderer observed per receipt',samples=args['samples'])
    if result['status']=='recorded':
        from PIL import Image
        image=Image.open(Path(result['directory'])/'slide-001.png').convert('RGB')
        values=[]
        for p in paths:
            x,y=p['commands'][0][1:];w=p['commands'][1][1]-x;h=p['commands'][2][2]-y
            values.append({'id':p['id'],'rgb':[list(image.getpixel((min(image.width-1,round((x+w*t)/640*image.width)),
                   min(image.height-1,round((y+h*.5)/recipe['canvas'][1]*image.height))))) for t in [.1,.5,.9]]})
        result['sampled_colors']=values
    write_json(directory/'probe.json',result)
    return result
