"""Offline asset inspection, strict cropping and transparent-PNG preparation; no OCR or generative calls."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import numpy as np
from PIL import Image
from common import sha256


def _hex_rgb(value:str):
    value=value.strip().lstrip('#')
    if len(value)!=6 or any(c not in '0123456789abcdefABCDEF' for c in value):
        raise ValueError('Color must be six hex digits, e.g. FF00FF')
    return tuple(int(value[i:i+2],16) for i in (0,2,4))


def audit(path:Path):
    with Image.open(path) as im:
        has_alpha=im.mode in ('RGBA','LA') or 'transparency' in im.info
        alpha=im.convert('RGBA').getchannel('A') if has_alpha else None
        extrema=list(alpha.getextrema()) if alpha else [255,255]
        return {
            'path':path.name,'sha256':sha256(path),'format':im.format,'mode':im.mode,'size':list(im.size),
            'has_alpha_storage':has_alpha,'alpha_range':extrema,'has_transparent_pixels':extrema[0]<255,
            'visible_subject_exists':extrema[1]>0,
            'warning':'Alpha does not prove a clean edge; checkerboards or halos may still be baked into visible pixels.'
        }


def _guard(source:Path,dest:Path,overwrite:bool):
    if source.resolve()==dest.resolve():raise ValueError('Never overwrite source reference')
    if dest.exists() and not overwrite:raise FileExistsError(dest)
    dest.parent.mkdir(parents=True,exist_ok=True)


def crop(source:Path,dest:Path,box:list[int],overwrite=False):
    _guard(source,dest,overwrite)
    with Image.open(source) as im:
        l,t,r,b=box
        if not(0<=l<r<=im.width and 0<=t<b<=im.height):raise ValueError(f'Crop outside actual image {im.size}: {box}')
        im.crop(box).save(dest)
    return audit(dest)


def chroma_key(source:Path,dest:Path,key:str,tolerance:float=28,feather:float=16,overwrite=False):
    """Convert a solid-color generated background to alpha using RGB distance.

    Pixels <= tolerance from key become transparent. Pixels >= tolerance+feather remain opaque.
    Existing alpha is multiplied in rather than discarded.
    """
    if tolerance<0 or feather<0:raise ValueError('Tolerance/feather must be non-negative')
    _guard(source,dest,overwrite)
    key_rgb=np.array(_hex_rgb(key),dtype=np.float32)
    with Image.open(source) as im:
        arr=np.asarray(im.convert('RGBA'),dtype=np.float32)
    rgb=arr[...,:3]
    dist=np.linalg.norm(rgb-key_rgb,axis=2)
    if feather==0:
        matte=(dist>tolerance).astype(np.float32)
    else:
        matte=np.clip((dist-tolerance)/feather,0,1)
    # Decontaminate semi-transparent edge RGB so the solid key color does not create a magenta/green fringe.
    m=matte[...,None]
    denom=np.maximum(m,1e-4)
    fg=(rgb-(1.0-m)*key_rgb)/denom
    fg=np.where(m>1e-4,fg,0)
    alpha=(arr[...,3]/255.0)*matte
    out=np.empty_like(arr,dtype=np.uint8)
    out[...,:3]=np.clip(fg,0,255).astype(np.uint8)
    out[...,3]=np.clip(alpha*255,0,255).astype(np.uint8)
    Image.fromarray(out,'RGBA').save(dest)
    result=audit(dest);result['operation']='chroma';result['key']=key.upper().lstrip('#');result['tolerance']=tolerance;result['feather']=feather
    return result


def trim_alpha(source:Path,dest:Path,padding:int=0,threshold:int=1,overwrite=False):
    if padding<0:raise ValueError('Padding must be non-negative')
    if not 0<=threshold<=255:raise ValueError('Alpha threshold must be 0..255')
    _guard(source,dest,overwrite)
    with Image.open(source) as im:
        rgba=im.convert('RGBA');alpha=np.asarray(rgba.getchannel('A'))
        ys,xs=np.where(alpha>=threshold)
        if len(xs)==0:raise ValueError('No visible subject found above alpha threshold')
        l=max(0,int(xs.min())-padding);t=max(0,int(ys.min())-padding)
        r=min(rgba.width,int(xs.max())+1+padding);b=min(rgba.height,int(ys.max())+1+padding)
        rgba.crop((l,t,r,b)).save(dest)
    result=audit(dest);result['operation']='trim-alpha';result['source_box']=[l,t,r,b];result['padding']=padding;result['threshold']=threshold
    return result


def matte(source:Path,dest:Path,background:str='FFFFFF',overwrite=False):
    _guard(source,dest,overwrite)
    bg=_hex_rgb(background)
    with Image.open(source) as im:
        rgba=im.convert('RGBA')
        canvas=Image.new('RGBA',rgba.size,(*bg,255));canvas.alpha_composite(rgba);canvas.convert('RGB').save(dest)
    result=audit(dest);result['operation']='matte-preview';result['background']=background.upper().lstrip('#')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='action',required=True)
    x=sub.add_parser('audit');x.add_argument('source',type=Path)
    x=sub.add_parser('crop');x.add_argument('source',type=Path);x.add_argument('output',type=Path);x.add_argument('--box',nargs=4,type=int,required=True);x.add_argument('--overwrite',action='store_true')
    x=sub.add_parser('chroma');x.add_argument('source',type=Path);x.add_argument('output',type=Path);x.add_argument('--key',required=True);x.add_argument('--tolerance',type=float,default=28);x.add_argument('--feather',type=float,default=16);x.add_argument('--overwrite',action='store_true')
    x=sub.add_parser('trim-alpha');x.add_argument('source',type=Path);x.add_argument('output',type=Path);x.add_argument('--padding',type=int,default=0);x.add_argument('--threshold',type=int,default=1);x.add_argument('--overwrite',action='store_true')
    x=sub.add_parser('matte');x.add_argument('source',type=Path);x.add_argument('output',type=Path);x.add_argument('--background',default='FFFFFF');x.add_argument('--overwrite',action='store_true')
    a=ap.parse_args()
    try:
        if a.action=='audit':r=audit(a.source)
        elif a.action=='crop':r=crop(a.source,a.output,a.box,a.overwrite)
        elif a.action=='chroma':r=chroma_key(a.source,a.output,a.key,a.tolerance,a.feather,a.overwrite)
        elif a.action=='trim-alpha':r=trim_alpha(a.source,a.output,a.padding,a.threshold,a.overwrite)
        else:r=matte(a.source,a.output,a.background,a.overwrite)
        print(json.dumps(r,ensure_ascii=False,indent=2))
    except Exception as exc:print(str(exc),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
