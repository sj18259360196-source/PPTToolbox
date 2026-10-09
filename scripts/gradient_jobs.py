"""Bounded Office workers. Copies and receipts survive timeout; never kill Office."""
from pathlib import Path
import json
import sys
import uuid
import subprocess
import os
from common import sha256, write_json, read_json

def source_path(project, args):
    from toolbox_manager.policy import plain_path
    src=plain_path(project/args['pptx'])
    if not src.is_relative_to(project) or src.suffix.lower()!='.pptx' or not src.is_file():
        raise ValueError('Source must be a PPTX inside the authorized project')
    if sha256(src)!=args['pptx_sha256']: raise ValueError('Stale source hash')
    return src

def run_job(project, kind, args):
    from toolbox_manager.policy import plain_path
    from runtime_env import python_tool_argv
    src=source_path(project,args)
    if kind=='read_properties':
        from pptx import Presentation
        from local_edit import shapes_by_name
        wanted={(v['slide']-1,v['id']) for v in args['targets']}
        if len(wanted)!=len(args['targets']): raise ValueError('Duplicate target')
        if not wanted<=shapes_by_name(Presentation(src)).keys(): raise ValueError('Target missing or ambiguous')
    else:
        from office_edit import validate_operations
        ops=validate_operations(args['operations'])
        if any(not o['op'].startswith('gradient.') for o in ops): raise ValueError('Gradient operations only')
    dest=plain_path(project/'runs/graphics-evidence'/uuid.uuid4().hex)
    dest.mkdir(parents=True,exist_ok=False)
    # Work from a snapshot. The source and project writer lock are not held during COM.
    import shutil
    shutil.copyfile(src,dest/'source.pptx')
    if sha256(dest/'source.pptx')!=args['pptx_sha256']: raise ValueError('Source changed during snapshot')
    request={'kind':kind,'args':args,'source':str(dest/'source.pptx'),'directory':str(dest)}
    write_json(dest/'request.json',request)
    write_json(dest/'stage.json',{'stage':'worker_start','source_sha256':args['pptx_sha256']})
    argv=python_tool_argv(sys.executable,Path(__file__).resolve().parents[1],
                          'scripts/gradient_jobs.py',[str(dest/'request.json')])
    with (dest/'stdout.log').open('wb') as stdout,(dest/'stderr.log').open('wb') as stderr:
        try:
            env={**os.environ}
            if args.get('_office_lock'):env['PPT_MANAGED_OFFICE_LOCK']=args['_office_lock']
            result=subprocess.run(argv,stdout=stdout,stderr=stderr,timeout=args.get('timeout_seconds',90),env=env)
            report=read_json(dest/'result.json') if (dest/'result.json').is_file() else {
                'status':'failed','error':'Worker exited without result','returncode':result.returncode}
        except subprocess.TimeoutExpired:
            report={'status':'outcome_unknown','error':'Office worker time budget exhausted',
                    'recovery':'Inspect stage, logs, private copies and Office lock owner before retry; user Office was not terminated'}
    report.update(directory=str(dest),source_unchanged=sha256(src)==args['pptx_sha256'],
                  source_sha256=args['pptx_sha256'],visual_review='pending')
    write_json(dest/'result.json',report)
    return report

def worker(request):
    r=read_json(request);dest=Path(r['directory']);src=Path(r['source']);a=r['args']
    def stage(value): write_json(dest/'stage.json',{'stage':value})
    try:
        stage('office_save_reopen')
        if r['kind']=='gradient_roundtrip':
            from office_edit import execute,validate_operations
            from runtime_env import office_guard
            ops=validate_operations(a['operations'])
            if any(not o['op'].startswith('gradient.') for o in ops): raise ValueError('Gradient operations only')
            with office_guard(): result=execute(src,dest/'edit',ops)
        else:
            from local_edit import office_roundtrip
            from native_nodes import summary
            targets={(v['slide'],v['id']) for v in a['targets']}
            if len(targets)!=len(a['targets']): raise ValueError('Duplicate target')
            office_roundtrip(src,dest/'saved-copy.pptx',dest/'office-readback.json',native=True,
                             targets=targets,detailed=False,export=True)
            receipt=read_json(dest/'office-readback.json')
            if {(r['slide'],r['name']) for r in receipt['objects']}!=targets: raise ValueError('Office target missing or ambiguous')
            stage('native_geometry')
            result={'format':'native-properties/1','status':'recorded','office_version':receipt['office_version'],'objects':receipt['objects'],
                    'native_geometry':summary(dest/'saved-copy.pptx',targets=targets),
                    'edit_test':'not_performed','pptx':str(dest/'saved-copy.pptx')}
        stage('finished');write_json(dest/'result.json',result)
    except Exception as exc:
        stage('failed');write_json(dest/'result.json',{'status':'failed','error':str(exc)})

if __name__=='__main__': worker(Path(sys.argv[1]))
