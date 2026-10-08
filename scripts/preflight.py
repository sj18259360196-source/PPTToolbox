"""Record actual local paths, installed packages and input image sizes without installing anything."""
from __future__ import annotations
import argparse, importlib, importlib.metadata, os, platform, shutil, sys
from pathlib import Path
from common import write_json
from runtime_env import powershell_path

def probe(inputs:list[Path]|None=None):
    packages={}
    for module,distribution in [('PIL','Pillow'),('numpy','numpy'),('pptx','python-pptx'),('lxml','lxml'),('jsonschema','jsonschema')]:
        try:importlib.import_module(module);packages[module]={'status':'passed','version':importlib.metadata.version(distribution)}
        except Exception as exc:packages[module]={'status':'blocked','reason':str(exc)}
    images=[]
    for file in inputs or []:
        try:
            from PIL import Image
            with Image.open(file) as im:images.append({'path':str(file.resolve()),'size':list(im.size),'mode':im.mode})
        except Exception as exc:images.append({'path':str(file),'error':str(exc)})
    return {'status':'passed' if all(p['status']=='passed' for p in packages.values()) else 'blocked',
      'os':platform.platform(),'python':{'executable':sys.executable,'version':platform.python_version()},'packages':packages,
      'programs':{**{p:shutil.which(p) for p in ['pwsh','powershell','node']},
                  'selected_powershell':powershell_path(),
                  'libreoffice':shutil.which('libreoffice') or shutil.which('soffice')},'images':images,
      'office_com':{'status':'not_run' if os.name=='nt' else 'blocked','reason':'Use render_powerpoint.ps1 -ProbeOnly for actual COM availability; installed paths alone do not prove capability'},
      'agent_vision':{'status':'not_run','reason':'Agent declares its actual ability; no extra model endpoint is assumed'},
      'image_generation':{'status':'not_run','reason':'Use only an actually available host tool, when needed'},
      'scope':'Local imports, executable discovery and image metadata only; no network or install'}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('inputs',type=Path,nargs='*');ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();r=probe(a.inputs);write_json(a.out,r);print(f"Preflight {r['status']}; saved {a.out}");return 0 if r['status']=='passed' else 3
if __name__=='__main__':raise SystemExit(main())
