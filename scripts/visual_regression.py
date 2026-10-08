"""Same-environment local-edit regression evidence; never an aesthetic verdict."""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from common import sha256,write_json,staged_directory
from compare_images import rgb,_labelled_side
from region_contract import normalize_region_input


def compare_changes(before,after,regions,outdir,threshold=12,max_outside_fraction=0.001,margin=2,environment_before=None,environment_after=None,slide_index=None):
    if type(threshold)is not int or not 0<=threshold<=255 or type(margin)is not int or not 0<=margin<=100:raise ValueError('Invalid pixel threshold/margin')
    if type(max_outside_fraction)not in (int,float) or not math.isfinite(max_outside_fraction) or not 0<=max_outside_fraction<=1:raise ValueError('max_outside_fraction must be 0..1')
    a=rgb(before);b=rgb(after)
    if a.size!=b.size:raise ValueError('Before/after dimensions differ; no resize permitted in local regression')
    records=normalize_region_input(regions,a.size,slide_index,require_nonempty=True)
    regions=[r['bbox'] for r in records]
    allow=np.zeros((a.height,a.width),dtype=bool);boxes=[]
    for r in regions:
        if not isinstance(r,list) or len(r)!=4 or any(type(v)is not int for v in r):raise ValueError('Allowed regions use integer source-pixel xyxy')
        x0,y0,x1,y1=r
        if not 0<=x0<x1<=a.width or not 0<=y0<y1<=a.height:raise ValueError('Allowed region outside image')
        box=[max(0,x0-margin),max(0,y0-margin),min(a.width,x1+margin),min(a.height,y1+margin)];boxes.append(box);allow[box[1]:box[3],box[0]:box[2]]=True
    raw=np.max(np.abs(np.asarray(a,dtype=np.int16)-np.asarray(b,dtype=np.int16)),axis=2)
    changed=raw>threshold;outside=changed & ~allow;outside_count=int(outside.sum());outside_area=int((~allow).sum())
    frac=outside_count/outside_area if outside_area else 0
    same_environment=bool(environment_before and environment_after and environment_before==environment_after)
    status='not_applicable' if not outside_area else 'needs_review' if frac>max_outside_fraction else 'no_excess_outside_change' if same_environment else 'environment_unverified'
    with staged_directory(outdir) as stage:
        _labelled_side(a,b,'BEFORE / 修改前','AFTER / 修改后').save(stage/'before-after.png')
        marked=b.copy();arr=np.asarray(marked).copy();arr[outside]=[225,40,45];marked=Image.fromarray(arr);d=ImageDraw.Draw(marked)
        for box in boxes:d.rectangle([box[0],box[1],box[2]-1,box[3]-1],outline='#00A170',width=2)
        marked.save(stage/'outside-changes.png')
        ys,xs=np.where(outside);bbox=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)] if len(xs) else None
        result={'status':status,'before_sha256':sha256(before),'after_sha256':sha256(after),'size':list(a.size),'allowed_regions_xyxy':regions,'allowed_region_records':records,'coordinate_contract':'source_pixels_xyxy','expanded_regions_xyxy':boxes,'threshold_per_channel':threshold,'margin_px':margin,'outside_changed_pixels':outside_count,'outside_area_pixels':outside_area,'outside_changed_fraction':frac,'outside_change_bbox':bbox,'inside_changed_pixels':int((changed & allow).sum()),'environment_matched':same_environment,'environment_before':environment_before,'environment_after':environment_after,'scope':'Pixel change localisation only. Environment equality is caller evidence, not independently detected. No claim that all inside edits are correct. All-page permission has no outside coverage.'}
        write_json(stage/'regression.json',result)
    return result
