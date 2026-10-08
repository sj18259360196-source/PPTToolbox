"""Compare reproducibility evidence without issuing a visual acceptance verdict.

PPT package content, decoded pixels, file hashes and source-image fidelity are
different questions. This tool measures the first three; it never infers the last.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zipfile import ZipFile
import numpy as np
from PIL import Image
from common import sha256, write_json


def package_diff(left, right):
    with ZipFile(left) as a, ZipFile(right) as b:
        an=[n for n in a.namelist() if not n.endswith('/')]
        bn=[n for n in b.namelist() if not n.endswith('/')]
        if len(an)!=len(set(an)) or len(bn)!=len(set(bn)):
            raise ValueError('Duplicate ZIP member names are ambiguous')
        aset,bset=set(an),set(bn)
        changed=sorted(n for n in aset & bset if a.read(n)!=b.read(n))
        added,removed=sorted(bset-aset),sorted(aset-bset)
        ppt_changes=[n for n in changed+added+removed if n.startswith('ppt/')]
    return {'package_bytes_equal':sha256(left)==sha256(right),
            'ppt_parts_exact_equal':not ppt_changes,
            'changed_parts':changed,'added_parts':added,'removed_parts':removed}


def pixel_diff(left, right):
    with Image.open(left) as im:
        a=np.array(im.convert('RGBA'),dtype=np.int16)
    with Image.open(right) as im:
        b=np.array(im.convert('RGBA'),dtype=np.int16)
    result={'left_size':[a.shape[1],a.shape[0]],'right_size':[b.shape[1],b.shape[0]]}
    if a.shape!=b.shape:
        return {**result,'same_size':False,'pixels_exact_equal':False,
                'note':'No resizing or pixel comparison performed.'}
    d=np.abs(a-b);mask=d.max(axis=2)>0
    y,x=np.where(mask)
    bbox=[int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)] if len(x) else None
    return {**result,'same_size':True,'pixels_exact_equal':not bool(mask.any()),
            'different_pixels':int(mask.sum()),'different_fraction':float(mask.mean()),
            'mean_absolute_rgb_difference':float(d[:,:,:3].mean()),
            'mean_absolute_alpha_difference':float(d[:,:,3].mean()),
            'max_channel_difference':int(d.max()),
            'difference_bbox_xyxy_exclusive':bbox}


def compare(left, right, left_render=None, right_render=None):
    if bool(left_render)!=bool(right_render):
        raise ValueError('Both render paths are required together')
    files={'left_pptx':Path(left),'right_pptx':Path(right)}
    if left_render:files.update(left_render=Path(left_render),right_render=Path(right_render))
    for p in files.values():
        if not p.is_file():raise ValueError('Missing input: '+str(p))
    result={'format':'ppt-rebuild-diff/1','status':'measured','visual_verdict':'not_assessed',
            'source_fidelity':'not_assessed',
            'inputs':{k:{'file':str(p.resolve()),'sha256':sha256(p)} for k,p in files.items()},
            'package':package_diff(left,right)}
    if left_render:result['render']=pixel_diff(left_render,right_render)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['left','right','out']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--left-render',type=Path);p.add_argument('--right-render',type=Path)
    a=p.parse_args()
    try:
        if a.out.exists():raise ValueError('Output must be new; never overwrite evidence')
        result=compare(a.left,a.right,a.left_render,a.right_render)
        write_json(a.out,result);print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 2


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    raise SystemExit(main())
