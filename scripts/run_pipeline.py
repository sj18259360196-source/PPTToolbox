"""Build -> inspect -> optional Office render -> comparison -> honest review template.
Input must already contain the Agent's analysis. No automatic acceptance or background work.
"""
from __future__ import annotations
import argparse, os, shutil, subprocess, sys
from pathlib import Path
from runtime_env import powershell_path
from PIL import Image
from common import read_json,resolve_asset,sha256,write_json
from build_pptx import build
from inspect_pptx import inspect
from compare_deck import compare_deck
from preflight import probe
from verify_delivery import REQUIRED
from evidence_contract import required_review

def run(scene:Path,out:Path,office=False,regions:Path|None=None):
    if out.exists():raise FileExistsError('Output folder already exists; choose a new run folder')
    out.mkdir(parents=True);sd=read_json(scene)
    write_json(out/'preflight.json',probe())
    pptx=out/'candidate.pptx';build(scene,pptx);audit=inspect(pptx,scene);write_json(out/'audit.json',audit)
    if any(c['status']=='failed' for c in audit['checks'].values()):raise ValueError('Automatic audit failed; inspect audit.json')
    review={'scene_sha256':sha256(scene),'comparison_sha256':'','pptx_sha256':sha256(pptx),'reviewer':'','checks':{n:{'status':'not_run','note':'','slides':[],'evidence':[]} for n in REQUIRED},'limitations':[],'user_acceptance':'not_run'}
    review['checks']['visual_local']['regions']=[]
    review['checks']['relationships']['objects']=[]
    write_json(out/'review.json',review)
    write_json(out/'required-review.json', {'scene_sha256':sha256(scene), 'slides':[
        {'index':i,'slide_id':s['id'],**required_review(s)} for i,s in enumerate(sd['slides'],1)],
        'scope':'Mandatory declared objects only; Agent must also check source omissions'})
    if not office:
        write_json(out/'pipeline.json',{'status':'blocked','reason':'Candidate built; Office render and source/visual/edit checks not run','pptx_sha256':sha256(pptx)})
        return 3
    shell=powershell_path()
    if os.name!='nt' or not shell:
        write_json(out/'pipeline.json',{'status':'blocked','reason':'No Windows/PowerShell target runtime; no substitute renderer was claimed','pptx_sha256':sha256(pptx)})
        return 3
    sizes=[]
    for i,s in enumerate(sd['slides'],1):
        if s.get('reference'):
            with Image.open(resolve_asset(scene.parent,s['reference'])) as im:w,h=im.size
        else:w=1920;h=round(w*sd['canvas']['height_pt']/sd['canvas']['width_pt'])
        sizes.append({'index':i,'width':w,'height':h})
    write_json(out/'render-sizes.json',sizes)
    cmd=[shell,'-NoProfile','-File',str(Path(__file__).with_name('render_powerpoint.ps1')),'-Pptx',str(pptx.resolve()),'-OutputDir',str((out/'office').resolve()),'-SizesJson',str((out/'render-sizes.json').resolve())]
    try:result=subprocess.run(cmd,timeout=180,capture_output=True,text=True,encoding='utf-8',errors='replace')
    except subprocess.TimeoutExpired:
        write_json(out/'pipeline.json',{'status':'blocked','reason':'Render command timed out; inspect PowerPoint before retry, do not kill user Office processes'});return 3
    (out/'office-command.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Office render failed; see office-command.log and office/office-render.json')
    compare_deck(scene,out/'office/office-render.json',out/'comparisons',regions,pptx_path=pptx)
    # Bind the empty review to its actual evidence, without changing any review status.
    review['comparison_sha256']=sha256(out/'comparisons/deck-comparison.json')
    write_json(out/'review.json',review)
    write_json(out/'pipeline.json',{'status':'blocked','reason':'Build, structural audit, Office export and mandatory side-by-side comparisons produced; Agent must actually inspect them and complete review.json','pptx_sha256':sha256(pptx),'comparison_receipt':'comparisons/deck-comparison.json'})
    return 3

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('scene',type=Path);ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--office',action='store_true');ap.add_argument('--regions',type=Path,help='Local regions JSON; required when the scene has mandatory local objects')
    a=ap.parse_args()
    try:return run(a.scene.resolve(),a.output_dir,a.office,a.regions.resolve() if a.regions else None)
    except Exception as exc:print(f'Pipeline failed: {exc}',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
