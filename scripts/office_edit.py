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
    'text.set': {'required': ['op', 'slide', 'name', 'text'], 'kind': 'text'},
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
        if set(op) != set(CONTRACTS[op['op']]['required']):
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
        if op['op']=='picture.crop':
            if op['edge'] not in {'left','top','right','bottom'}:
                raise ValueError('edge must be left/top/right/bottom')
            if type(op['points']) not in (int,float) or not math.isfinite(op['points']) or op['points']<0:
                raise ValueError('points must be a finite nonnegative absolute crop value')
        key = (op['slide'], op['name'], op['op'], op.get('row'), op.get('column'), op.get('edge'))
        if key in seen:
            raise ValueError('Duplicate sample edit target')
        seen.add(key)
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
    if op['op']=='picture.crop':return float(op['points'])
    return rgb(op['color']) if op['op'] == 'shape.fill' else op['text'].replace('\r\n', '\n').replace('\r', '\n')

def values_match(op,actual):
    return abs(actual-expected(op))<=.05 if op['op']=='picture.crop' else actual==expected(op)

def read_value(shape, op):
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
    if op['op'] == 'text.set':
        shape.TextFrame.TextRange.Text = op['text']
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
    app = application_factory()
    outdir.mkdir(parents=True, exist_ok=False)
    copy = outdir/'edited-copy.pptx'
    receipt = {'format': 'ppt-edit-readback/1', 'status': 'failed', 'renderer': 'Microsoft PowerPoint',
               'source': str(source), 'source_sha256': source_hash, 'checks': [], 'renders': [],
               'scope': 'sampled text/fill/table/picture-crop only', 'visual_status': 'not_run',
               'longer_text_layout': 'not_assessed', 'all_objects_tested': False}
    deck = None
    try:
        shutil.copyfile(source, copy)
        deck = app.Presentations.Open(str(copy), 0, 0, 0)
        # Resolve all edits and reject no-ops before modifying the copy.
        targets = []
        for op in operations:
            shape = find_shape(deck.Slides.Item(op['slide']).Shapes, op['name'])
            before = read_value(shape, op)
            if values_match(op,before):
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
            if op['op']=='text.set' and len(expected(op))>len(before):
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
        receipt.update(edited_file=copy.name, edited_sha256=sha256(copy))
        receipt['status'] = 'passed' if all(c['matches'] for c in receipt['checks']) else 'failed'
        receipt['content_readback_status']=receipt['status']
        receipt['acceptance_status']=('needs_changes' if receipt['longer_text_layout']=='overflow_detected'
                                      else 'visual_review_required')
        receipt['acceptance_note']='Attribute readback, longer-text layout and visual review are separate. A passed status alone is not layout acceptance.'
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
    for command in ('validate', 'run'):
        c = sub.add_parser(command)
        c.add_argument('--operations', type=Path, required=True)
        if command == 'run':
            c.add_argument('--pptx', type=Path, required=True)
            c.add_argument('--outdir', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == 'describe':
            result = {'operations': CONTRACTS, 'index_base': 1, 'additional_fields': False,
                      'limits': 'Sample only; chart edits and visual layout require separate checks.'}
        else:
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
