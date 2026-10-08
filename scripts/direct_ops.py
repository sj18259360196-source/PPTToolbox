"""Task-level tools: component/boolean, font specimens, asset alignment, bounded edits.
All outputs are new paths. Tools produce artifacts; target Office/visual review remains required.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path
from common import read_json,write_json,staged_directory,resolve_asset,walk_objects
from components import CATALOG,compile_component,boolean_component


def create_component(spec,outdir,canvas=None,boolean=False,asset_base=None):
    from build_pptx import build
    from evidence_contract import logical_bounds
    obj=boolean_component(spec) if boolean else compile_component(spec)
    if canvas is None:
        bounds=logical_bounds(obj);w=max(160,bounds[2]+20);h=max(100,bounds[3]+20);canvas=[w,h]
    if not isinstance(canvas,list) or len(canvas)!=2:raise ValueError('canvas needs width,height logical units')
    w,h=canvas
    scene={'version':'1.0','title':'Native component specimen','canvas':{'width':w,'height':h,'width_pt':w*.75,'height_pt':h*.75,'mapping':'uniform','background':'FFFFFF'},'slides':[{'id':'component','objects':[obj]}]}
    with staged_directory(outdir) as stage:
        for child in walk_objects([obj]):
            if child['kind']=='image':
                if asset_base is None:raise ValueError('Image component needs --asset-base pointing to persistent local inputs')
                src=resolve_asset(asset_base,child['asset']);dst=stage/child['asset'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        write_json(stage/'fragment.json',{'objects':[obj],'source_notes':'Parameterised specimen; compare with the real reference before adoption','relationship_ids':[obj['id']] if spec.get('recipe') in {'double_arrow','feedback_curve'} else []})
        write_json(stage/'scene.json',scene);report=build(stage/'scene.json',stage/'component.pptx')
        write_json(stage/'operation.json',{'status':'awaiting_office_review','spec':spec,'primitive_count':len(list(walk_objects([obj]))),'build':report,'next_action':'Render component.pptx with actual Office, then compare the same reference region; source image is not invented by this command.'})
    return {'command_status':'completed','workflow_status':'awaiting_office_review','outdir':str(outdir),'files':['fragment.json','scene.json','component.pptx','operation.json']}


def parser():
    ap=argparse.ArgumentParser(description=__doc__);s=ap.add_subparsers(dest='action',required=True)
    s.add_parser('components')
    s.add_parser('fonts')
    p=s.add_parser('describe');p.add_argument('recipe',choices=list(CATALOG))
    for name in ['component','boolean']:
        p=s.add_parser(name);p.add_argument('--spec',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True);p.add_argument('--canvas',type=float,nargs=2);p.add_argument('--asset-base',type=Path)
    p=s.add_parser('asset-layout');p.add_argument('--image',type=Path,required=True);p.add_argument('--target',nargs=4,type=float,required=True);p.add_argument('--anchor',nargs=2,type=float,default=[.5,.5]);p.add_argument('--alpha-threshold',type=int,default=32);p.add_argument('--background',default='DCECF4');p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('font-sheet');p.add_argument('--spec',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('font-evaluate');p.add_argument('--reference',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True);p.add_argument('--background');p.add_argument('--tolerance',type=int,default=24)
    for name in ['patch-scene','patch-pptx']:
        p=s.add_parser(name);p.add_argument('--source',type=Path,required=True);p.add_argument('--spec',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('regression');p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--regions',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True);p.add_argument('--threshold',type=int,default=12);p.add_argument('--max-outside-fraction',type=float,default=.001);p.add_argument('--margin',type=int,default=2);p.add_argument('--environment-before');p.add_argument('--environment-after');p.add_argument('--slide',type=int,help='Select page in a shared deck regions file')
    p=s.add_parser('generation-prepare');p.add_argument('--project',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p=s.add_parser('generation-ingest');p.add_argument('--project',type=Path,required=True);p.add_argument('--request',type=Path,required=True);p.add_argument('--image',type=Path,required=True);p.add_argument('--producer',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    return ap


def main(argv=None):
    a=parser().parse_args(argv)
    try:
        if a.action=='fonts':
            from text_ops import list_local_fonts
            result=list_local_fonts()
        elif a.action=='components':result={'components':[{'recipe':k,**v} for k,v in CATALOG.items()]}
        elif a.action=='describe':result={'recipe':a.recipe,**CATALOG[a.recipe],'example':{'id':'target','recipe':a.recipe,'bbox':[20,20,200,100],'params':CATALOG[a.recipe]['params']}}
        elif a.action in {'component','boolean'}:result=create_component(read_json(a.spec),a.outdir,a.canvas,a.action=='boolean',a.asset_base or a.spec.parent)
        elif a.action=='asset-layout':
            from asset_ops import placement_report
            result=placement_report(a.image,a.target,a.outdir,a.anchor,a.alpha_threshold,a.background)
        elif a.action=='font-sheet':
            from text_ops import font_sheet
            result=font_sheet(read_json(a.spec),a.outdir)
        elif a.action=='font-evaluate':
            from text_ops import evaluate_fonts
            result=evaluate_fonts(a.reference,a.manifest,a.receipt,a.outdir,a.background,a.tolerance)
        elif a.action in {'patch-scene','patch-pptx'}:
            from patch_ops import patch_scene,patch_pptx
            result=(patch_scene if a.action=='patch-scene' else patch_pptx)(a.source,read_json(a.spec),a.outdir)
        elif a.action=='regression':
            from visual_regression import compare_changes
            result=compare_changes(a.before,a.after,read_json(a.regions),a.outdir,a.threshold,a.max_outside_fraction,a.margin,a.environment_before,a.environment_after,a.slide)
        elif a.action=='generation-prepare':
            from asset_ops import prepare_generation
            result=prepare_generation(a.project,a.outdir)
        elif a.action=='generation-ingest':
            from asset_ops import ingest_generation
            result=ingest_generation(a.project,a.request,a.image,a.producer,a.outdir)
        else:raise ValueError('Unknown action')
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except Exception as exc:
        print(json.dumps({'command_status':'failed','error':str(exc),'next_action':'Correct only the specified spec/entry; source files were not intentionally overwritten.'},ensure_ascii=False,indent=2));return 2

if __name__=='__main__':raise SystemExit(main())
