"""Native Office font specimen generation and explicit foreground measurements.
No font is distributed and no candidate is claimed to be the original typeface.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from PIL import Image
from common import read_json,write_json,sha256,staged_directory
from build_pptx import build
from compare_images import _labelled_side


def font_sheet(spec,outdir):
    if not isinstance(spec,dict) or set(spec)-{'text','candidates','canvas','sample_bbox','background','color'}:raise ValueError('Invalid font-sheet spec')
    text=spec.get('text');candidates=spec.get('candidates')
    if not isinstance(text,str) or not text.strip():raise ValueError('Exact source sample text required')
    if not isinstance(candidates,list) or not 1<=len(candidates)<=24:raise ValueError('Supply 1..24 font candidates')
    width,height=spec.get('canvas',[960,360]);bbox=spec.get('sample_bbox',[40,100,880,120]);bg=spec.get('background','FFFFFF')
    for v in [width,height,*bbox]:
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Finite canvas/bbox required')
    if not all(v>0 for v in (width,height,bbox[2],bbox[3])) or bbox[0]<0 or bbox[1]<0 or bbox[0]+bbox[2]>width or bbox[1]+bbox[3]>height:raise ValueError('Sample box outside sheet')
    scene={'version':'1.0','title':'Font candidates / functional specimen','canvas':{'width':width,'height':height,'width_pt':width*.75,'height_pt':height*.75,'mapping':'uniform','background':bg},'slides':[]}
    samples=[]
    for i,c in enumerate(candidates,1):
        if not isinstance(c,dict) or set(c)-{'font','font_east_asia','font_size_pt','bold','italic','char_spacing_pt','warp'}:raise ValueError('Candidate fields: font/font_east_asia/font_size_pt/bold/italic/char_spacing_pt/warp')
        if not c.get('font') or not c.get('font_size_pt'):raise ValueError('Each candidate needs actual family name and point size')
        ev={'status':'synthetic','note':'Font specimen; source text supplied separately, not a fidelity result'}
        obj={'id':'sample','kind':'text','role':'content','editability':'text','evidence':ev,'bbox':bbox,'text':text,'style':{'margin_pt':0,'color':spec.get('color','1A5271'),'wrap':False}|c}
        label=f"Candidate {i}: {c['font']} / {c.get('font_east_asia',c['font'])} / {c['font_size_pt']} pt"
        scene['slides'].append({'id':f'font-{i:03}','objects':[{'id':'label','kind':'text','role':'header','editability':'text','evidence':ev,'bbox':[24,20,width-48,46],'text':label,'style':{'font':'Arial','font_size_pt':14,'color':'444444'}},obj]})
        samples.append({'index':i,'candidate':c,'bbox_xyxy':[bbox[0],bbox[1],bbox[0]+bbox[2],bbox[1]+bbox[3]],'file':f'slide-{i:03}.png'})
    with staged_directory(outdir) as stage:
        write_json(stage/'font-candidates.scene.json',scene);build(stage/'font-candidates.scene.json',stage/'font-candidates.pptx')
        report={'format':'ppt-font-samples/1.3','status':'awaiting_office','pptx':'font-candidates.pptx','pptx_sha256':sha256(stage/'font-candidates.pptx'),'export_size':[round(width),round(height)],'background':bg,'samples':samples,'scope':'Native specimen files generated. Installed fonts and rendered glyphs require actual Office check; no font file embedded/distributed.'}
        write_json(stage/'font-samples.json',report)
    return report


def ink_metrics(image,background='FFFFFF',tolerance=24):
    if type(tolerance)is not int or not 0<=tolerance<=254:raise ValueError('tolerance is 0..254 RGB distance')
    rgb=np.asarray(image.convert('RGB'),dtype=np.int16);bg=np.array([int(background[i:i+2],16) for i in (0,2,4)])
    mask=np.max(np.abs(rgb-bg),axis=2)>tolerance
    ys,xs=np.where(mask)
    if not len(xs):return {'status':'empty','bbox_xyxy':None,'ink_pixels':0,'occupancy':0}
    b=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
    return {'status':'measured','bbox_xyxy':b,'ink_pixels':int(mask.sum()),'occupancy':float(mask.mean()),'width':b[2]-b[0],'height':b[3]-b[1],
            'touches_crop_edge':bool(b[0]==0 or b[1]==0 or b[2]==image.width or b[3]==image.height)}


def evaluate_fonts(reference,manifest,receipt_path,outdir,background=None,tolerance=24):
    """Requires a receipt matching the native specimen. Does not trust file names alone."""
    m=read_json(manifest);receipt=read_json(receipt_path)
    if receipt.get('renderer')!='Microsoft PowerPoint' or receipt.get('status')!='passed' or receipt.get('probe_only'):raise ValueError('Need an actual successful PowerPoint render receipt, not a probe')
    if receipt.get('pptx_sha256')!=m['pptx_sha256'] or sha256(manifest.parent/m['pptx'])!=m['pptx_sha256']:raise ValueError('Font specimen/receipt identity mismatch')
    if len(receipt.get('slides',[]))!=len(m['samples']):raise ValueError('Font render page count mismatch')
    rows={r['index']:r for r in receipt['slides']}
    if len(rows)!=len(m['samples']):raise ValueError('Duplicate font render index')
    with Image.open(reference) as im:ref=im.convert('RGB')
    bg=background or m['background'];rm=ink_metrics(ref,bg,tolerance);result=[]
    if rm['status']=='empty':raise ValueError('Reference has no foreground under selected condition')
    with staged_directory(outdir) as stage:
        for sample in m['samples']:
            r=rows[sample['index']];file=(receipt_path.parent/r['file']).resolve()
            if not file.is_relative_to(receipt_path.parent.resolve()) or sha256(file)!=r['sha256']:raise ValueError('Font PNG path/hash mismatch')
            with Image.open(file) as im:
                if list(im.size)!=m['export_size']:raise ValueError('Font export must use the exact recorded dimensions')
                crop=im.convert('RGB').crop([round(v) for v in sample['bbox_xyxy']])
            cm=ink_metrics(crop,m['background'],tolerance)
            # Pad, never stretch the glyphs to fabricate matching extents.
            size=(max(ref.width,crop.width),max(ref.height,crop.height));a=Image.new('RGB',size,'#'+bg);b=Image.new('RGB',size,'#'+bg);a.paste(ref,(0,0));b.paste(crop,(0,0))
            name=f'font-{sample["index"]:03}-side-by-side.png';_labelled_side(a,b,'REFERENCE','POWERPOINT FONT').save(stage/name)
            row={'index':sample['index'],'candidate':sample['candidate'],'measurement':cm,'side_by_side':name}
            if cm['status']=='measured':row.update(width_ratio=cm['width']/rm['width'],height_ratio=cm['height']/rm['height'])
            result.append(row)
        out={'status':'awaiting_visual_review','reference_sha256':sha256(reference),'manifest_sha256':sha256(manifest),'render_receipt_sha256':sha256(receipt_path),'reference_measurement':rm,'candidates':result,'threshold':tolerance,'scope':'Foreground geometry under explicit plain-background assumption, not OCR/typeface recognition. No auto font winner; inspect strokes, baseline and crop clipping.'}
        write_json(stage/'font-evaluation.json',out)
    return out


def list_local_fonts():
    """List locally registered names only. Not proof that Office uses every requested glyph."""
    import os,shutil,subprocess
    rows=[]
    if os.name=='nt':
        import winreg
        for hive,label in [(winreg.HKEY_LOCAL_MACHINE,'machine'),(winreg.HKEY_CURRENT_USER,'user')]:
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                    i=0
                    while True:
                        try:name,filename,_=winreg.EnumValue(key,i)
                        except OSError:break
                        rows.append({'registered_name':name,'file_hint':filename,'scope':label});i+=1
            except OSError:continue
        source='Windows Fonts registry display names; not resolved family names or Office glyph evidence'
    else:
        fc=shutil.which('fc-list')
        if not fc:return {'status':'blocked','fonts':[],'reason':'No platform font enumerator discovered; provide locally verified candidate family names'}
        result=subprocess.run([fc,'--format','%{family}\t%{style}\n'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,shell=False)
        if result.returncode:raise ValueError('Fontconfig enumeration failed')
        for line in sorted(set(result.stdout.splitlines())):
            family,_,style=line.partition('\t');rows.append({'family':family,'style':style})
        source='Fontconfig registered families; not Office rendering proof'
    return {'status':'enumerated','source':source,'fonts':rows,'font_files_exported':False}
