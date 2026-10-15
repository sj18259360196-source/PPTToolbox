"""Explicit sample edits on a new PPTX copy, with PowerPoint close/reopen readback.

The contract and validation work without Office. Execution requires Windows and
pywin32, never edits the source and never quits the user's PowerPoint application.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import sha256, write_json

CONTRACTS = {
    'gradient.stop': {'required':['op','slide','name','index','property','expected','value'], 'kind':'gradient'},
    'gradient.angle': {'required':['op','slide','name','expected','value'], 'kind':'gradient'},
    'text.set': {'required': ['op', 'slide', 'name', 'text'], 'optional':['font_size_pt'], 'kind': 'text'},
    'picture.transform': {'required':['op','slide','name','units','expected','value','aspect_ratio'], 'kind':'picture',
        'units':'slide_points; one unrotated/unflipped group supported; nonuniform group scales require zero picture rotation'},
    'picture.replace': {'required':['op','slide','name','image','image_sha256','expected_sha256','crop_policy','fit_policy'],
        'kind':'picture', 'method':'package relationship replacement followed by Office save/reopen',
        'limits':'PNG/JPEG source-directory-relative images only; fit_policy stretch is explicit'},
    'shape.fill': {'required': ['op', 'slide', 'name', 'color'], 'kind': 'shape'},
    'table.cell': {'required': ['op', 'slide', 'name', 'row', 'column', 'text'], 'kind': 'table'},
    'picture.crop': {'required': ['op', 'slide', 'name', 'edge', 'points'], 'kind': 'picture',
                     'units': 'absolute PowerPoint CropLeft/Top/Right/Bottom points; tolerance 0.05 pt'},
}


def validate_operations(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ValueError('operations must contain 1..100 explicit edits')
    seen = set()
    for op in operations:
        if not isinstance(op, dict) or op.get('op') not in CONTRACTS:
            raise ValueError('Supported operations: '+', '.join(CONTRACTS))
        required=set(CONTRACTS[op['op']]['required'])
        if not required.issubset(op) or set(op)-required-set(CONTRACTS[op['op']].get('optional',[])):
            raise ValueError('Missing or irrelevant fields for '+op['op'])
        if type(op['slide']) is not int or op['slide'] < 1:
            raise ValueError('slide must be a positive 1-based integer')
        if not isinstance(op['name'], str) or not op['name'].strip():
            raise ValueError('name must be an exact nonempty object name')
        if 'text' in op and (not isinstance(op['text'], str) or not op['text'].strip()):
            raise ValueError('Sample text must be nonempty')
        if 'color' in op and (not isinstance(op['color'], str) or not re.fullmatch(r'[0-9a-fA-F]{6}', op['color'])):
            raise ValueError('color must be six hex digits without #')
        for k in ('row', 'column'):
            if k in op and (type(op[k]) is not int or op[k] < 1):
                raise ValueError(k+' must be a positive 1-based integer')
        if 'font_size_pt' in op and (type(op['font_size_pt']) not in (int,float) or not math.isfinite(op['font_size_pt']) or not 0<op['font_size_pt']<=400):
            raise ValueError('font_size_pt must be finite and in (0,400]')
        if op['op']=='picture.transform':
            if op['units']!='slide_points' or op['aspect_ratio'] not in {'preserve','free'}:raise ValueError('Explicit slide_points and aspect_ratio preserve/free required')
            for field in ['expected','value']:
                v=op[field]
                if not isinstance(v,dict) or set(v)!={'left','top','width','height','rotation'}:raise ValueError('Picture geometry requires left/top/width/height/rotation')
                if any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>100000 for n in v.values()):raise ValueError('Picture geometry must be finite bounded points')
                if v['width']<=0 or v['height']<=0 or not 0<=v['rotation']<360:raise ValueError('Positive picture dimensions and rotation [0,360) required')
            if op['aspect_ratio']=='preserve' and abs(op['expected']['width']/op['expected']['height']-op['value']['width']/op['value']['height'])>1e-6:raise ValueError('Picture transform violates preserved aspect ratio')
        if op['op']=='picture.replace':
            if not isinstance(op['image'],str) or not op['image'] or Path(op['image']).is_absolute() or Path(op['image']).drive or '..' in Path(op['image']).parts:raise ValueError('Replacement image must be source-directory relative')
            for field in ['image_sha256','expected_sha256']:
                if not isinstance(op[field],str) or not re.fullmatch('[0-9a-f]{64}',op[field]):raise ValueError('Replacement needs lowercase SHA-256')
            if op['crop_policy'] not in {'preserve','reset'} or op['fit_policy']!='stretch':raise ValueError('crop_policy preserve/reset and explicit fit_policy stretch required')
        if op['op']=='picture.crop':
            if op['edge'] not in {'left','top','right','bottom'}:
                raise ValueError('edge must be left/top/right/bottom')
            if type(op['points']) not in (int,float) or not math.isfinite(op['points']) or op['points']<0:
                raise ValueError('points must be a finite nonnegative absolute crop value')
        if op['op'].startswith('gradient.'):
            if op['op']=='gradient.stop':
                if type(op['index']) is not int or not 1 <= op['index'] <= 16:
                    raise ValueError('Gradient stop index must be 1..16')
                if op['property'] not in {'color','alpha','position'}:
                    raise ValueError('Unknown gradient stop property')
            for field in ('expected','value'):
                v=op[field]
                if op.get('property')=='color':
                    if not isinstance(v,str) or not re.fullmatch(r'[0-9a-fA-F]{6}',v):
                        raise ValueError('Gradient color must be six hex digits')
                elif type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=(360 if op['op']=='gradient.angle' else 1):
                    raise ValueError('Gradient value outside finite range')
        key = (op.get('index'),op.get('property'),op['slide'], op['name'], op['op'], op.get('row'), op.get('column'), op.get('edge'))
        if key in seen:
            raise ValueError('Duplicate sample edit target')
        seen.add(key)
    kinds={op['op'] for op in operations}
    if 'picture.crop' in kinds and kinds & {'picture.transform','picture.replace'}:
        raise ValueError('Run picture.crop and picture transform/replace in separate calls with separate output copies')
    return operations


def find_shape(shapes, name):
    matches = []
    def visit(items):
        for i in range(1, items.Count+1):
            shape = items.Item(i)
            if str(shape.Name) == name:
                matches.append(shape)
            if int(shape.Type) == 6:
                visit(shape.GroupItems)
    visit(shapes)
    if len(matches) != 1:
        raise ValueError(f'Object name must resolve uniquely: {name} ({len(matches)} matches)')
    return matches[0]


def rgb(value):
    return int(value[0:2], 16) | int(value[2:4], 16) << 8 | int(value[4:6], 16) << 16


def expected(op):
    if op['op'].startswith('gradient.'):
        return rgb(op['value']) if op.get('property')=='color' else float(op['value'])
    if op['op']=='picture.crop':return float(op['points'])
    return rgb(op['color']) if op['op'] == 'shape.fill' else op['text'].replace('\r\n', '\n').replace('\r', '\n')

def values_match(op,actual):
    if op['op'].startswith('gradient.') and op.get('property')!='color':
        return abs(actual-expected(op))<=0.0001
    return abs(actual-expected(op))<=.05 if op['op']=='picture.crop' else actual==expected(op)

def read_value(shape, op):
    if op['op'].startswith('gradient.'):
        if int(shape.Fill.Type)!=3: raise ValueError('Native gradient fill required')
        if op['op']=='gradient.angle': return float(shape.Fill.GradientAngle)
        if op['index']>shape.Fill.GradientStops.Count: raise ValueError('Gradient stop missing')
        stop=shape.Fill.GradientStops.Item(op['index'])
        if op['property']=='color': return int(stop.Color.RGB)
        if op['property']=='alpha': return 1-float(stop.Transparency)
        return float(stop.Position)
    if op['op']=='picture.crop':
        if int(shape.Type)!=13:
            raise ValueError('picture.crop requires an embedded picture: '+op['name'])
        return float(getattr(shape.PictureFormat,'Crop'+op['edge'].title()))
    if op['op'] == 'shape.fill':
        return int(shape.Fill.ForeColor.RGB)
    if op['op'] == 'table.cell':
        value = shape.Table.Cell(op['row'], op['column']).Shape.TextFrame.TextRange.Text
    else:
        if not shape.HasTextFrame:
            raise ValueError('Object has no text frame: '+op['name'])
        value = shape.TextFrame.TextRange.Text
    return str(value).replace('\r\n', '\n').replace('\r', '\n')


def apply_edit(shape, op):
    if op['op'].startswith('gradient.'):
        if op['op']=='gradient.angle': shape.Fill.GradientAngle=float(op['value'])
        else:
            stops=shape.Fill.GradientStops; stop=stops.Item(op['index'])
            if op['property']=='color': stop.Color.RGB=rgb(op['value'])
            elif op['property']=='alpha': stop.Transparency=1-float(op['value'])
            else:
                lo=float(stops.Item(op['index']-1).Position) if op['index']>1 else -1
                hi=float(stops.Item(op['index']+1).Position) if op['index']<stops.Count else 2
                if not lo<float(op['value'])<hi: raise ValueError('Stop position would reorder stops')
                stop.Position=float(op['value'])
    elif op['op'] == 'text.set':
        shape.TextFrame.TextRange.Text = op['text']
        if 'font_size_pt' in op:shape.TextFrame.TextRange.Font.Size=float(op['font_size_pt'])
    elif op['op'] == 'shape.fill':
        shape.Fill.Solid()
        shape.Fill.ForeColor.RGB = rgb(op['color'])
    elif op['op']=='picture.crop':
        setattr(shape.PictureFormat,'Crop'+op['edge'].title(),float(op['points']))
    else:
        shape.Table.Cell(op['row'], op['column']).Shape.TextFrame.TextRange.Text = op['text']


def text_layout(shape):
    """Geometric warning only; rotation and unavailable COM bounds stay unverified."""
    try:
        if abs(float(shape.Rotation)) > .01:
            return {'status':'not_assessed','reason':'Rotated text needs visual inspection'}
        bounds = shape.TextFrame2.TextRange
        frame = [float(shape.Left),float(shape.Top),float(shape.Width),float(shape.Height)]
        text = [float(bounds.BoundLeft),float(bounds.BoundTop),
                float(bounds.BoundWidth),float(bounds.BoundHeight)]
        if not all(math.isfinite(n) for n in frame+text):
            raise ValueError('Nonfinite Office bounds')
        x,y,w,h = frame
        a,b,c,d = text
        fits = a >= x-.5 and b >= y-.5 and a+c <= x+w+.5 and b+d <= y+h+.5
        return {'status':'within_frame' if fits else 'overflow_detected',
                'frame_pt':frame,'text_bounds_pt':text,'tolerance_pt':.5,
                'visual_review':'required'}
    except Exception:
        return {'status':'not_assessed','reason':'Office bounds unavailable; inspect the render'}


def execute(source, outdir, operations, application_factory=None):
    validate_operations(operations)
    source, outdir = Path(source).resolve(), Path(outdir).resolve()
    if source.suffix.lower() != '.pptx' or not source.is_file():
        raise ValueError('source must be an existing .pptx')
    if outdir.exists():
        raise ValueError('Output directory must be new; existing files are preserved')
    if application_factory is None:
        if os.name != 'nt':
            raise RuntimeError('Windows PowerPoint is required')
        from win32com.client import Dispatch
        application_factory = lambda: Dispatch('PowerPoint.Application')
    source_hash = sha256(source)
    package_ops=[op for op in operations if op['op'] in {'picture.transform','picture.replace'}]
    package_checks=[]
    app = None
    outdir.mkdir(parents=True, exist_ok=False)
    copy = outdir/'edited-copy.pptx'
    receipt = {'format': 'ppt-edit-readback/1', 'status': 'failed', 'renderer': 'Microsoft PowerPoint',
               'source': str(source), 'source_sha256': source_hash, 'checks': [], 'renders': [],
               'scope': 'explicit sampled operations only; see checks for gradient properties', 'visual_status': 'not_run',
               'longer_text_layout': 'not_assessed', 'all_objects_tested': False}
    receipt['process_policy'] = 'Close only this call-owned new copy; never Quit shared PowerPoint or close source/user decks'
    deck = None
    try:
        if package_ops:
            from material_edit_review import edit_picture_package
            package_checks=edit_picture_package(source,copy,package_ops)
        else:
            shutil.copyfile(source, copy)
        app=application_factory()
        deck = app.Presentations.Open(str(copy), 0, 0, 0)
        # Resolve all edits and reject no-ops before modifying the copy.
        targets = []
        for op in operations:
            if op in package_ops:continue
            shape = find_shape(deck.Slides.Item(op['slide']).Shapes, op['name'])
            before = read_value(shape, op)
            if op['op'].startswith('gradient.'):
                prior=rgb(op['expected']) if op.get('property')=='color' else float(op['expected'])
                if abs(before-prior)>0.0001: raise ValueError('Stale gradient expectation: '+op['name'])
            size_change='font_size_pt' in op and abs(float(shape.TextFrame.TextRange.Font.Size)-op['font_size_pt'])>.05
            if values_match(op,before) and not size_change:
                raise ValueError('Sample must change the existing value: '+op['name'])
            targets.append((shape, op, before))
        for shape, op, before in targets:
            apply_edit(shape, op)
        deck.Save()
        deck.Close()
        deck = None
        deck = app.Presentations.Open(str(copy), -1, 0, 0)
        for _, op, before in targets:
            shape = find_shape(deck.Slides.Item(op['slide']).Shapes, op['name'])
            actual = read_value(shape, op)
            receipt['checks'].append({'operation': op, 'kind': CONTRACTS[op['op']]['kind'],
                                      'before': before, 'expected': expected(op), 'actual': actual,
                                      'matches': values_match(op,actual)})
            if 'font_size_pt' in op:
                size=float(shape.TextFrame.TextRange.Font.Size)
                receipt['checks'][-1].update(actual_font_size_pt=size,font_size_matches=abs(size-op['font_size_pt'])<=.05)
                receipt['checks'][-1]['matches'] &= receipt['checks'][-1]['font_size_matches']
            if op['op']=='text.set' and (len(expected(op))>len(before) or 'font_size_pt' in op):
                receipt['checks'][-1]['longer_text_layout']=text_layout(shape)
        layouts=[c['longer_text_layout']['status'] for c in receipt['checks'] if 'longer_text_layout' in c]
        if layouts:
            receipt['longer_text_layout']=('overflow_detected' if 'overflow_detected' in layouts
                                          else 'within_frame' if all(s=='within_frame' for s in layouts)
                                          else 'not_assessed')
        for index in sorted({op['slide'] for op in operations}):
            file = outdir/f'slide-{index:03}.png'
            width = 1600
            height = round(width*float(deck.PageSetup.SlideHeight)/float(deck.PageSetup.SlideWidth))
            deck.Slides.Item(index).Export(str(file), 'PNG', width, height)
            if not file.is_file() or not file.stat().st_size:
                raise RuntimeError('Office did not produce the requested render')
            receipt['renders'].append({'file': file.name, 'sha256': sha256(file)})
        deck.Close()
        deck = None
        if sha256(source) != source_hash:
            raise RuntimeError('Source changed; do not reuse this evidence')
        if package_ops:
            from material_edit_review import verify_picture_package_edits
            verified=verify_picture_package_edits(source,copy,package_checks,operations,office_saved=True)
            receipt['checks'].extend(verified['checks'])
            receipt['picture_preservation']=verified['preservation']
        receipt.update(edited_file=copy.name, edited_sha256=sha256(copy))
        receipt['status'] = 'passed' if all(c['matches'] for c in receipt['checks']) else 'failed'
        receipt['content_readback_status']=receipt['status']
        receipt['acceptance_status']=('needs_changes' if receipt['longer_text_layout']=='overflow_detected'
                                      else 'visual_review_required')
        receipt['acceptance_note']='Attribute readback, longer-text layout and visual review are separate. A passed status alone is not layout acceptance.'
        receipt['edit_limits']=[{'object_id':c['operation']['name'],'slide':c['operation']['slide'],
            'operation':c['operation']['op'],'tested_value':c['expected'],
            'content_readback_status':'passed' if c['matches'] else 'failed',
            'layout_status':c.get('longer_text_layout',{}).get('status','not_assessed'),
            'required_adjustment':('Enlarge the text frame or explicitly revise typography, then render and check again.'
                if c.get('longer_text_layout',{}).get('status')=='overflow_detected' else None)}
            for c in receipt['checks']]
    except Exception as exc:
        receipt['error'] = str(exc)
    finally:
        if deck is not None:
            try:
                # Only our copy is open here. Discard unsaved partial edits on
                # failure rather than leaving an interactive save prompt.
                deck.Saved = -1
                deck.Close()
            except Exception as exc:
                receipt['cleanup_error'] = str(exc)
        # Do not Quit the application: it may contain the user's other documents.
        write_json(outdir/'edit-readback.json', receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('describe')
    plan = sub.add_parser('plan')
    plan.add_argument('--pptx', type=Path, required=True)
    plan.add_argument('--outdir', type=Path, required=True)
    plan.add_argument('--operations', type=Path)
    plan.add_argument('--previous', type=Path)
    plan.add_argument('--reuse-unchanged-slides', action='store_true')
    for command in ('validate', 'run'):
        c = sub.add_parser(command)
        group = c.add_mutually_exclusive_group(required=True)
        group.add_argument('--operations', type=Path)
        if command == 'run':
            group.add_argument('--plan', type=Path)
            c.add_argument('--pptx', type=Path)
            c.add_argument('--outdir', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == 'describe':
            result = {'operations': CONTRACTS, 'index_base': 1, 'additional_fields': False,
                      'runner': {'plan': 'plan --pptx PPTX --outdir NEW_DIR [--operations JSON] [--previous edit-run.json] [--reuse-unchanged-slides]',
                                 'run': 'run --plan edit-plan.json --outdir NEW_DIR',
                                 'defaults': 'One text, shape fill, table cell and picture transform when available. Explicit operations override samples.',
                                 'reuse': 'Exact candidate by default; opt-in unchanged-slide equivalence checks every shared package part. Old receipts retain original candidate binding; visual and formal delivery review remain required.'},
                      'limits': 'Sample only; chart edits and visual layout require separate checks.'}
        elif a.command == 'plan':
            from edit_runner import prepare
            result = prepare(a.pptx, a.outdir, json.loads(a.operations.read_text(encoding='utf-8-sig')) if a.operations else None, a.previous,
                             reuse_unchanged_slides=a.reuse_unchanged_slides)
        elif a.command == 'run' and a.plan:
            if a.pptx:
                raise ValueError('--plan already binds the candidate; omit --pptx')
            from edit_runner import run
            result = run(a.plan, a.outdir)
        else:
            if a.command == 'run' and not a.pptx:
                raise ValueError('Legacy run --operations requires --pptx')
            ops = validate_operations(json.loads(a.operations.read_text(encoding='utf-8-sig')))
            result = {'status': 'validated', 'operations': ops} if a.command == 'validate' else execute(a.pptx, a.outdir, ops)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') == 'failed' else 0
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
