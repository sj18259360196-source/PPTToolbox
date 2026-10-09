"""Project-scoped illustration candidates; no access outside authorized project."""
import hashlib, io, json, uuid
from pathlib import Path

def route(observations):
    from illustration_methods import choose
    return choose(observations)

def read_input(project,name,expected,max_bytes=16*1024*1024):
    from project_journal import safe
    if Path(name).is_absolute():raise ValueError('Use a project-relative input path')
    p=safe(project,name)
    if not p.is_file() or p.stat().st_size>max_bytes:raise ValueError('Missing or oversized project input')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Stale input SHA-256')
    return raw

def persist(project,op,result):
    from project_journal import safe
    folder=safe(project,'runs/illustration-tools/'+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    raw=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    p=folder/(op+'.json');p.write_bytes(raw)
    return dict(result_file=p.relative_to(project).as_posix(),result_sha256=hashlib.sha256(raw).hexdigest(),
                status='candidate_only' if op=='fit_paths' else 'measured_not_reviewed',
                office='not_run',visual_review='not_assessed')

def compare(project,a):
    import numpy as np
    from PIL import Image
    from scipy.ndimage import binary_erosion,distance_transform_edt
    names=['reference','candidate','reference_mask','candidate_mask'];images={}
    for name in names:
        raw=read_input(project,a[name],a['sha256'][name])
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>4_000_000:raise ValueError('Region exceeds four million pixels')
            im.load();images[name]=im.copy()
    if len({im.size for im in images.values()})!=1:raise ValueError('Inputs must share the same fixed pixel frame')
    def mask(name):
        raw=np.asarray(images[name].convert('L'))
        if not np.isin(raw,[0,255]).all():raise ValueError('Masks must be explicit binary 0/255')
        return raw==255
    r=mask('reference_mask');c=mask('candidate_mask')
    if not r.any() or not c.any():raise ValueError('Empty foreground masks cannot be compared')
    re=r & ~binary_erosion(r,border_value=0);ce=c & ~binary_erosion(c,border_value=0)
    d=np.r_[distance_transform_edt(~ce)[re],distance_transform_edt(~re)[ce]]/a['pixels_per_reference_pixel']
    common=r & c;erosion=a.get('erosion_pixels',1)
    if erosion:common=binary_erosion(common,iterations=erosion,border_value=0)
    left=np.asarray(images['reference'].convert('RGB'),dtype=float)
    right=np.asarray(images['candidate'].convert('RGB'),dtype=float)
    return dict(mask_iou_pct=float(100*(r & c).sum()/(r | c).sum()),
        boundary_mean_source_px=float(d.mean()),boundary_p95_source_px=float(np.percentile(d,95)),
        boundary_max_source_px=float(d.max()),shared_interior_pixels=int(common.sum()),
        rgb_mae_on_shared_interior=float(np.abs(left[common]-right[common]).mean()) if common.any() else None,
        inputs={k:a[k] for k in names},sha256=a['sha256'],
        pixels_per_reference_pixel=a['pixels_per_reference_pixel'],erosion_pixels=erosion,
        alignment='none',limits=['Binary masks supplied by caller; no semantic validation',
           'Color statistic covers intersection only; inspect unmatched area separately',
           'No threshold score means visual or Office acceptance'])

def run_inline(project,op,a):
    if op=='route_illustration':return route(a['observations'])
    if op=='compare_regions':
        result=compare(project,a);return {**persist(project,op,result),'metrics':result}
    if op in {'selection_masks','freeze_evaluation','evaluate_stages','share_rings'}:
        from illustration_methods import execute
        return execute(project,op,a)
    assessment=route(a['observations'])
    if assessment['decision']!='applicable':raise ValueError('Illustration route is '+assessment['decision'])
    raw=read_input(project,a['input_file'],a['input_sha256'])
    v=json.loads(raw.decode('utf-8-sig'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Non-finite JSON')))
    fragment=v.get('scene_fragment',v)
    from pen_path_fit import fit_fragment
    result,records=fit_fragment(fragment,a.get('rms',.32),a.get('max_error',.9),a.get('anchors',{}))
    output=dict(scene_fragment=result,fit_report=dict(input_file=a['input_file'],input_sha256=a['input_sha256'],
        route=assessment,rms=a.get('rms',.32),max_error=a.get('max_error',.9),
        distance_scope='sampled symmetric contour distance, input-coordinate units; not a continuous proof',
        records=records,visual_review='pending',office='not_run'))
    return {**persist(project,op,output),'path_records':len(records),'route':assessment,
            'next_action':'Inspect candidate and original, compare fixed-frame metrics, then use managed rebuild to render and edit-test in Office.'}


def run(project,op,a):
    if op=='route_illustration':return route(a['observations'])
    # Validate identity and scope before creating any job output.
    if op=='fit_paths':
        if route(a['observations'])['decision']!='applicable':raise ValueError('Illustration route is not applicable')
        read_input(project,a['input_file'],a['input_sha256'])
    elif op=='share_rings':
        read_input(project,a['input_file'],a['input_sha256'])
    elif op in {'selection_masks','freeze_evaluation'}:
        if op=='selection_masks' and a['method']=='coverage' and any(k not in a for k in ('foreground_rules','background_rules','coverage_weights')):raise ValueError('Coverage requires explicit core rules and weights')
        if bool(a.get('support_mask'))!=bool(a.get('support_sha256')):raise ValueError('Support mask requires its SHA-256')
        read_input(project,a['reference'],a['reference_sha256'])
        if a.get('support_mask'):read_input(project,a['support_mask'],a['support_sha256'])
    elif op=='evaluate_stages':
        read_input(project,a['contract_file'],a['contract_sha256'])
        for stage in a['stages']:read_input(project,stage['mask'],stage['sha256'])
    else:
        for key in ('reference','candidate','reference_mask','candidate_mask'):
            read_input(project,a[key],a['sha256'][key])
    import subprocess,sys
    from project_journal import safe
    folder=safe(project,'runs/illustration-jobs/'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=False)
    request=folder/'request.json'
    request.write_text(json.dumps({'operation':op,'args':a},ensure_ascii=False,allow_nan=False),encoding='utf-8')
    with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
        try:
            process=subprocess.run([sys.executable,'-B','-I',str(Path(__file__).with_name('illustration_worker.py')),
                '--project',str(project),'--request',request.relative_to(project).as_posix()],
                stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            return {'command_status':'outcome_unknown','job_dir':folder.relative_to(project).as_posix(),
                    'next_action':'Inspect job result and published artifact before retry; do not replay accepted output.'}
    result_path=folder/'result.json'
    if process.returncode or not result_path.is_file():
        error=(folder/'stderr.log').read_text('utf-8',errors='replace')[-1200:]
        raise ValueError('Numerical worker failed; evidence '+folder.relative_to(project).as_posix()+'; '+error)
    result=json.loads(result_path.read_text('utf-8'))
    read_input(project,result['result_file'],result['result_sha256'])
    return {**result,'job_dir':folder.relative_to(project).as_posix()}
