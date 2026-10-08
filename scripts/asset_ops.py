"""Visible-content placement and explicit host image-generation handoff.
No network, provider impersonation, or claim of seeing the image is made here.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from common import read_json, write_json, sha256, staged_directory


def subject_placement(path, target, anchor=(.5,.5), alpha_threshold=32):
    if len(target)!=4 or len(anchor)!=2:raise ValueError('target is xywh; anchor is normalized x,y')
    vals=list(target)+list(anchor)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vals):raise ValueError('Placement values must be finite numbers')
    x,y,w,h=target;ax,ay=anchor
    if w<=0 or h<=0 or not 0<=ax<=1 or not 0<=ay<=1:raise ValueError('Positive target and anchor 0..1 required')
    if type(alpha_threshold)is not int or not 1<=alpha_threshold<=255:raise ValueError('alpha_threshold must be integer 1..255')
    with Image.open(path) as original:
        has_alpha='A' in original.getbands() or 'transparency' in original.info
        rgba=original.convert('RGBA');a=rgba.getchannel('A')
        alpha_range=a.getextrema();full=a.getbbox();subject=a.point(lambda v:255 if v>=alpha_threshold else 0).getbbox()
    if full is None or subject is None:raise ValueError('No visible subject at the selected alpha threshold')
    l,t,r,b=subject;sw,sh=r-l,b-t;scale=min(w/sw,h/sh)
    body_left=x+(w-sw*scale)*ax;body_top=y+(h-sh*scale)*ay
    box=[body_left-l*scale,body_top-t*scale,rgba.width*scale,rgba.height*scale]
    return {'status':'passed','scope':'Alpha-based geometry only; visual subject identity and edge quality require review',
            'file_sha256':sha256(path),'file_size':list(rgba.size),'has_alpha_channel':has_alpha,'has_transparent_pixels':alpha_range[0]<255,
            'alpha_range':list(alpha_range),'alpha_threshold':alpha_threshold,'all_visible_bbox_xyxy':list(full),
            'subject_bbox_xyxy':list(subject),'target_bbox_xywh':list(target),'anchor':list(anchor),'image_bbox_xywh':box,
            'placed_subject_bbox_xywh':[body_left,body_top,sw*scale,sh*scale],
            'warning':'Alpha threshold is a geometric heuristic, not semantic segmentation. Transparent file bounds may extend beyond target; do not clip glow silently.'}


def placement_report(path,target,outdir,anchor=(.5,.5),alpha_threshold=32,background='DCECF4'):
    result=subject_placement(path,target,anchor,alpha_threshold)
    if not isinstance(background,str) or len(background)!=6:raise ValueError('background must be hex RGB')
    int(background,16)
    with Image.open(path) as im:rgba=im.convert('RGBA')
    with staged_directory(outdir) as stage:
        imagebox=result['image_bbox_xywh'];x,y,w,h=target
        left=min(x,imagebox[0]);top=min(y,imagebox[1]);right=max(x+w,imagebox[0]+imagebox[2]);bottom=max(y+h,imagebox[1]+imagebox[3])
        k=min(1.0,1000/max(right-left,bottom-top));pad=12
        size=(max(1,round((right-left)*k))+2*pad,max(1,round((bottom-top)*k))+2*pad)
        thumb=rgba.resize((max(1,round(imagebox[2]*k)),max(1,round(imagebox[3]*k))),Image.Resampling.LANCZOS)
        names=[]
        for name,bg in [('light','FFFFFF'),('dark','202A34'),('target',background)]:
            canvas=Image.new('RGBA',size,'#'+bg);canvas.alpha_composite(thumb,(round((imagebox[0]-left)*k)+pad,round((imagebox[1]-top)*k)+pad))
            draw=ImageDraw.Draw(canvas);draw.rectangle([round((x-left)*k)+pad,round((y-top)*k)+pad,round((x+w-left)*k)+pad,round((y+h-top)*k)+pad],outline='#E07B29',width=1)
            filename=name+'-matte.png';canvas.convert('RGB').save(stage/filename);names.append(filename)
        result['must_view_files']=names;write_json(stage/'placement.json',result)
    return result


def prepare_generation(project:Path,outdir:Path):
    import workflow
    state=workflow.next_task(project);task=state.get('task') or {}
    if task.get('kind')!='asset_material':raise ValueError('Current project task is not asset_material. Submit its request_asset alternative first.')
    packet_path=Path(task['packet']);packet=read_json(packet_path);request=packet['context']['request']
    references=list(task['must_view_files'])
    generation_reference=None
    if request.get('generation_decision'):
        from common import resolve_asset
        from material_routes import validate_decision
        decision=validate_decision(request['generation_decision'],project)
        generation_reference=str(resolve_asset(project,decision['reference']))
        references.extend(str(resolve_asset(project,decision[field])) for field in ('reference','drawing') if field in decision)
    with staged_directory(outdir) as stage:
        result={'format':'ppt-generation-handoff/1.3','status':'awaiting_host_generation','project':str(project.resolve()),
                'task_id':packet['task_id'],'packet_sha256':sha256(packet_path),'packet_file':str(packet_path),
                'reference_files':[{'file':f,'sha256':sha256(f)} for f in dict.fromkeys(references)],
                'generation_reference':generation_reference,
                'target':packet['target'],'purpose':request['purpose'],'prompt':request['prompt'],
                'output_contract':{'separate_local_asset':True,'transparent':request['transparent'],'baked_text_numbers_relations':False,
                                   'multi_icon_sheet':request.get('multi_icon_sheet',False)},
                'generation_decision':request.get('generation_decision'),
                'host_call':{'required':'Actual available image-generation/edit tool','model':None,'tool_schema':'Discover through host; never assume a model or API payload'},
                'instructions':'View and pass the reference crop to the real authorized host image tool, then save the actual returned PNG. For a multi-icon sheet, keep separate icons with transparent gutters; use separate source_crop image objects or cropped files in the PPT. Keep text and connectors separate. Then run generation-ingest. Model identity comes from the real tool. No new external upload permission is implied.',
                'visual_review_status':'not_run'}
        write_json(stage/'generation-request.json',result)
        write_json(stage/'producer.template.json',{'tool_used':'','model_reported':None,'provenance':''})
    return result


def ingest_generation(project:Path,request_path:Path,image:Path,producer_path:Path,outdir:Path):
    import workflow
    request=read_json(request_path);state=workflow.next_task(project);task=state.get('task') or {}
    if task.get('kind')!='asset_material' or task.get('id')!=request['task_id']:raise ValueError('Stale generation task; read the current task')
    packet_path=Path(task['packet'])
    if sha256(packet_path)!=request['packet_sha256']:raise ValueError('Generation source/task changed')
    for ref in request['reference_files']:
        if sha256(ref['file'])!=ref['sha256']:raise ValueError('Reference crop changed')
    prod=read_json(producer_path)
    if not isinstance(prod,dict) or set(prod)!={'tool_used','model_reported','provenance'}:raise ValueError('Producer fields must be tool_used, model_reported, provenance')
    if not all(isinstance(prod[k],str) and prod[k].strip() for k in ['tool_used','provenance']):raise ValueError('Record the actual host tool and provenance')
    if prod['model_reported'] is not None and not isinstance(prod['model_reported'],str):raise ValueError('model_reported is string or null, never guessed')
    with Image.open(image) as im:
        if im.format!='PNG':raise ValueError('Generation handoff expects an actual PNG')
        a=im.convert('RGBA').getchannel('A');ar=a.getextrema()
        if request['output_contract']['transparent'] and (('A' not in im.getbands() and 'transparency' not in im.info) or ar[0]==255 or ar[1]==0):raise ValueError('PNG lacks useful real transparency; use chroma/trim only when applicable')
    packet=read_json(packet_path)
    with staged_directory(outdir) as stage:
        response={'task_id':packet['task_id'],'token':packet['token'],'result':{'file':str(image.resolve()),**prod}}
        write_json(stage/'response.json',response)
        report={'status':'awaiting_visual_review','material_sha256':sha256(image),'producer_claim':prod,'alpha_range':list(ar),'response':'response.json','scope':'Real local file inspected, tool identity is a host assertion, no image semantics certified. View on actual background before submitting.'}
        write_json(stage/'ingestion.json',report)
    return report
