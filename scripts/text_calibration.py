"""Representative Office text measurements through the existing text-fit tools.

Reuse is advisory and exact-sample only. Style siblings share advice, never a
claim that different text fits. Mixed formatting and low confidence remeasure.
"""
from __future__ import annotations

import copy
import math
import os
import platform
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

if __package__:
    from .common import read_json, write_json, sha256, staged_directory
    from .review_impact import digest
else:
    from common import read_json, write_json, sha256, staged_directory
    from review_impact import digest

FORMAT = 'native-text-calibration/1'


def _export_size(canvas):
    """Raster pixels are integral; scene coordinates and physical points are not."""
    logical = [canvas[k] for k in ('width', 'height')]
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 4096 for v in logical):
        raise ValueError('Calibration needs logical dimensions within 1..4096 for pixel export')
    return [math.floor(v + .5) for v in logical]


def _bound_export_size(plan, source):
    if plan['canvas'] != source['canvas']:
        raise ValueError('Calibration canvas differs from the frozen source')
    derived = _export_size(source['canvas'])
    declared = plan.get('export_size_px')
    if 'export_size_px' not in plan:
        if any(v != int(v) for v in (source['canvas']['width'], source['canvas']['height'])):
            raise ValueError('Fractional calibration canvas requires export_size_px; regenerate the plan')
    elif (not isinstance(declared, list) or len(declared) != 2
          or any(type(v) is not int for v in declared) or declared != derived):
        raise ValueError(f'Calibration export_size_px differs from the source-derived pixel dimensions: expected {derived}, got {declared}')
    return derived


def _physical_canvas_validation(canvas, pptx, receipt):
    """Bind the package exactly; accommodate only observed Office readback rounding.

    PowerPoint 16.0 reads page sizes on an eighth-point grid. Keep this separate
    from source/package geometry, which must remain exact at build's EMU precision.
    Integer arithmetic also avoids introducing a floating-point midpoint policy.
    """
    from pptx.util import Pt
    expected = [canvas[k] for k in ('width_pt', 'height_pt')]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in expected):
        raise ValueError('Invalid calibration physical canvas in the frozen source')
    with ZipFile(pptx) as package:
        node = ElementTree.fromstring(package.read('ppt/presentation.xml')).find(
            '{http://schemas.openxmlformats.org/presentationml/2006/main}sldSz')
    if node is None:
        raise ValueError('Calibration PPTX lacks a physical canvas')
    package_emu = [int(node.attrib[k]) for k in ('cx', 'cy')]
    expected_emu = [int(Pt(v)) for v in expected]
    if package_emu != expected_emu:
        raise ValueError(f'Calibration package physical canvas differs from the frozen source: expected EMU {expected_emu}, got {package_emu}')
    physical = receipt.get('canvas_pt')
    if (not isinstance(physical, list) or len(physical) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in physical)):
        raise ValueError(f'Calibration physical canvas readback is invalid: expected pt {expected}, got {physical}')
    package_pt = [v / 12700 for v in package_emu]
    # A half-grid point is never an integral EMU (12700/16 ends in .75).
    quantized = [((v * 8 + 6350) // 12700) / 8 for v in package_emu]
    modes = []
    for axis, wanted, actual, grid in zip(('width', 'height'), expected, physical, quantized):
        if math.isclose(actual, wanted, rel_tol=0, abs_tol=.001):
            modes.append('source_with_numeric_tolerance')
        elif math.isclose(actual, grid, rel_tol=0, abs_tol=.001):
            modes.append('nearest_eighth_point')
        else:
            raise ValueError(f'Calibration physical canvas differs from the source: axis={axis}, source_pt={wanted}, '
                             f'office_pt={actual}, nearest_eighth_pt={grid}, numeric_tolerance_pt=0.001')
    return {'expected_pt': expected, 'package_emu': package_emu, 'package_pt': package_pt,
            'office_pt': physical, 'delta_pt': [a-b for a,b in zip(physical, expected)],
            'nearest_eighth_pt': quantized, 'axis_match': modes,
            'numeric_tolerance_pt': .001, 'quantization_step_pt': .125,
            'package_binding': 'exact_source_emu', 'rule': 'exact_package_nearest_eighth_readback/1'}


def environment(fonts):
    """Cheap inventory plus content hashes for requested fonts and Office binary.

    Missing identities disable cache reuse. Registry display names are only an
    inventory; they do not prove which font supplies every rendered glyph.
    """
    record = {'platform': os.name, 'collector': sha256(Path(__file__).with_name('text_calibration_measure.ps1')),
              'planner': sha256(Path(__file__)), 'fonts': [], 'requested': sorted(fonts),
              'office': None, 'available': False}
    from importlib.metadata import version
    record['text_pipeline'] = {name:sha256(Path(__file__).with_name(name)) for name in
                              ('build_pptx.py','native_text_range.py','native_extensions.py',
                               'common.py','scene_paths.py','render_powerpoint.ps1')}
    record['runtime'] = {'python':platform.python_version(), 'python_pptx':version('python-pptx')}
    if os.name != 'nt':
        return {**record, 'sha256': digest(record)}
    import winreg
    if __package__:
        from .text_ops import list_local_fonts
    else:
        from text_ops import list_local_fonts
    inventory = list_local_fonts()['fonts']
    fingerprints, matched = [], set()
    for row in inventory:
        name, hint = row.get('registered_name', ''), row.get('file_hint', '')
        path = Path(hint)
        if not path.is_absolute():
            path = Path(os.environ.get('WINDIR', r'C:\Windows'))/'Fonts'/path
        try:
            stat = path.stat()
            fingerprints.append([name, str(path), stat.st_size, stat.st_mtime_ns])
            matches = [f for f in fonts if f.casefold() in name.casefold()]
            if matches:
                record['fonts'].append({'registered_name': name, 'sha256': sha256(path)})
                matched.update(matches)
        except OSError:
            fingerprints.append([name, hint, None])
    record['font_inventory_sha256'] = digest(sorted(fingerprints, key=lambda r: r[0]))
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE') as key:
                path = Path(winreg.QueryValueEx(key, '')[0].strip('"'))
            record['office'] = {'binary_sha256': sha256(path)}
            break
        except OSError:
            continue
    record['fonts'].sort(key=lambda r: r['registered_name'])
    record['available'] = bool(record['office']) and matched == set(fonts)
    return {**record, 'sha256': digest(record)}


def _text(obj):
    if 'text' in obj:
        return obj['text']
    if 'runs' in obj:
        return ''.join(r['text'] for r in obj['runs'])
    return '\n'.join(''.join(r['text'] for r in p.get('runs', [])) if 'runs' in p else p.get('text', '')
                     for p in obj.get('paragraphs', []))


def _fonts(objects):
    result = set()
    for obj in objects:
        styles = [obj.get('style', {})] + obj.get('runs', [])
        styles += [r for p in obj.get('paragraphs', []) for r in p.get('runs', [])]
        for st in styles:
            result.update(st[k] for k in ('font', 'font_east_asia') if st.get(k))
        if not obj.get('style', {}).get('font'):
            result.add('Arial')
    return sorted(result)


def _targets(scene):
    result, deferred = [], []
    def walk(objects, sid, grouped=False):
        for obj in objects:
            if obj['kind'] == 'group':
                walk(obj['children'], sid, True)
                continue
            if obj['kind'] != 'text':
                continue
            if grouped:
                deferred.append({'slide': sid, 'id': obj['id'], 'reason': 'group_transform_requires_current_page_inspection'})
                continue
            style = obj.get('style', {})
            value = _text(obj)
            if not value.strip() or not style.get('font_size_pt'):
                deferred.append({'slide': sid, 'id': obj['id'], 'reason': 'empty_or_inherited_size'})
                continue
            mixed = bool(obj.get('runs') or obj.get('paragraphs'))
            uncertain = bool(obj.get('rotation', 0) or any(k in style for k in ('native_format', 'warp', 'text_outline')))
            roles = ['title' if obj.get('role') in ('title', 'header') else 'body']
            if re.search('[\u3400-\u9fff]', value) and re.search('[A-Za-z0-9]', value):
                roles.append('mixed_language')
            if re.search(r'\d', value) and not re.search('[\u3400-\u9fffA-Za-z]', value):
                roles.append('numbers')
            if len(value) >= 24 or '\n' in value:
                roles.append('long_text')
            category = 'title' if roles[0] == 'title' else 'mixed_language' if 'mixed_language' in roles else 'numbers' if 'numbers' in roles else 'body'
            # Position is retained: Office rasterization may depend on pixel phase.
            specimen = {k: copy.deepcopy(v) for k,v in obj.items()
                        if k in {'id', 'kind', 'role', 'editability', 'evidence', 'bbox',
                                 'text', 'runs', 'paragraphs', 'style', 'rotation'}}
            sample = {k:v for k,v in specimen.items() if k not in {'id','role','evidence','editability'}}
            style_key = digest([scene['canvas'], style, obj['bbox'][2:], obj.get('rotation', 0), category])
            result.append({'slide': sid, 'id': obj['id'], 'category': category, 'object': specimen,
                           'roles': roles, 'style_key': style_key, 'sample_key': digest([scene['canvas'], sample]),
                           'force_measure': mixed or uncertain,
                           'trigger': 'mixed_format' if mixed else 'low_confidence' if uncertain else 'first_style'})
    for slide in scene['slides']:
        walk(slide['objects'], slide['id'])
    # Pick critical content before style deduplication. A short label and a long
    # sentence with identical styling are not interchangeable fit measurements.
    ordered = []
    for category in ('title', 'body', 'numbers', 'long_text', 'mixed_language'):
        candidates = [t for t in result if category in t['roles']]
        if candidates:
            chosen = max(candidates, key=lambda t: (t['object']['style']['font_size_pt'] if category=='title' else len(_text(t['object']))))
            chosen.setdefault('representative_for', []).append(category)
            if chosen not in ordered:
                ordered.append(chosen)
    ordered += [t for t in result if t not in ordered]
    return ordered, deferred


def _measurement(target, row):
    data = row.get('calibration') or {}
    reasons = []
    if data.get('format') != 'office-text-calibration/1':
        reasons.append('calibration_not_collected_use_TextCalibration')
    normalize = lambda s: s.replace('\r\n', '\n').replace('\r', '\n').replace('\v', '\n')
    expected = normalize(_text(target['object']))
    if normalize(data.get('text', '')) not in (expected, expected+'\n'):
        reasons.append('text_readback_mismatch')
    finite = lambda n: type(n) in (int, float) and math.isfinite(n)
    valid_box = lambda b: isinstance(b,list) and len(b)==4 and all(finite(n) for n in b) and b[2]>0 and b[3]>0
    if not valid_box(row.get('box_pt')) or not valid_box(row.get('bound_pt')):
        reasons.append('text_bounds_unavailable')
    if data.get('errors') or data.get('truncated') or not data.get('lines') or not data.get('runs'):
        reasons.append('incomplete_office_measurement')
    if target['force_measure'] or row.get('rotation', 0):
        reasons.append(target['trigger'])
    if data.get('auto_size') != 0:
        reasons.append('autofit_effective_size_unresolved')
    runs = []
    for run in data.get('runs', []):
        size, offset = run.get('office_font_size_pt'), run.get('baseline_offset_fraction')
        effective = size if finite(size) and size > 0 and finite(offset) and offset == 0 and data.get('auto_size') == 0 and not target['force_measure'] else None
        if effective is None:
            reasons.append('effective_size_requires_visual_check')
        runs.append({**run, 'effective_font_size_pt': effective})
    lines = [copy.deepcopy(line) for line in data.get('lines', []) if valid_box(line.get('bound_pt'))]
    if len(lines) != len(data.get('lines', [])):
        reasons.append('line_bounds_unavailable')
    for i, line in enumerate(lines):
        line['line_advance_pt'] = (lines[i+1]['bound_pt'][1]-line['bound_pt'][1]) if i+1 < len(lines) else None
    requested_fonts = _fonts([target['object']])
    office_fonts = sorted({run[key] for run in runs for key in ('font', 'font_ascii', 'font_east_asia') if run.get(key)})
    # Names are API readback, not glyph-level fallback proof. Localized family
    # aliases can differ; report the difference without declaring substitution.
    font_names = {'requested': requested_fonts, 'office_readback': office_fonts,
                  'status': 'unavailable' if not office_fonts else 'names_differ' if any(
                      font.casefold() not in {name.casefold() for name in office_fonts} for font in requested_fonts) else 'requested_names_present',
                  'substitution': 'not_certified'}
    if font_names['status'] != 'requested_names_present':
        reasons.append('font_names_require_visual_check')
    explicit_lines = len(expected.split('\n'))
    suggestions = [{'action': 'compare_reference', 'note': 'Compare this measured sample with the same reference text before applying size changes.'}]
    bounds, box = row.get('bound_pt'), row.get('box_pt')
    if valid_box(bounds) and valid_box(box) and not row.get('rotation', 0):
        if (bounds[0] < box[0]-.75 or bounds[1] < box[1]-.75
                or bounds[0]+bounds[2] > box[0]+box[2]+.75 or bounds[1]+bounds[3] > box[1]+box[3]+.75):
            reasons.append('text_outside_frame')
            suggestions.append({'action': 'enlarge_frame_or_review_layout',
                                'note': 'Inspect available space, margins and wrapping; never shrink every font to conceal overflow.'})
    return {'slide': target['slide'], 'id': target['id'], 'category': target['category'],
            'sample_key': target['sample_key'], 'style_key': target['style_key'],
            'confidence': 'low' if reasons else 'high', 'reasons': sorted(set(reasons)),
            'box_pt': box, 'bound_pt': bounds, 'lines': lines, 'runs': runs,
            'representative_for': target.get('representative_for', []), 'font_names': font_names,
            'line_count': len(lines), 'explicit_line_count': explicit_lines,
            'additional_wrapping': len(lines) > explicit_lines if lines else None,
            'baseline_y_pt': None, 'baseline_y_status': 'unavailable_from_collector',
            'baseline_shift_basis': data.get('baseline_shift_basis'),
            'glyph_font_identity': 'not_certified', 'suggestions': suggestions,
            'visual_review': 'pending', 'automatic_changes': False}


def _verified_measurements(plan_dir, office_dir, *, check_path=lambda p: p):
    if __package__:
        from .evidence_contract import validate_render
    else:
        from evidence_contract import validate_render
    plan_path = Path(check_path(Path(plan_dir)/'plan.json'))
    plan = read_json(plan_path)
    if plan.get('version') != FORMAT:
        raise ValueError('Not a text calibration plan')
    source = Path(check_path(Path(plan_dir)/'source.scene.json'))
    pptx = Path(check_path(Path(plan_dir)/'specimens.pptx'))
    receipt_path = Path(check_path(Path(office_dir)/'office-render.json'))
    if sha256(source) != plan['source_copy_sha256'] or sha256(pptx) != plan['specimens_sha256']:
        raise ValueError('Calibration specimens or frozen source changed')
    export_size = _bound_export_size(plan, read_json(source))
    # Authorize indirect images before validate_render reads them.
    raw = read_json(receipt_path)
    for row in raw.get('slides', []):
        check_path(receipt_path.parent/row['file'])
    receipt, rows = validate_render(receipt_path, pptx, plan['page_exports_planned'])
    canvas_validation = _physical_canvas_validation(plan['canvas'], pptx, receipt)
    if any([r['width'],r['height']] != export_size for r in rows.values()):
        raise ValueError(f'Calibration export must retain the source-derived pixel dimensions: expected {export_size}')
    measurements = {}
    for row in receipt.get('text_bounds', []):
        key = (row.get('slide'), row.get('id'))
        if key in measurements:
            raise ValueError('Duplicate calibration text identity')
        measurements[key] = row
    result = [_measurement(t, measurements.get((t['index'],t['sample_id']), {})) for t in plan['targets']]
    return plan, receipt, result, canvas_validation


def cache(report_path, check_path=lambda p: p):
    """Recompute from hash-bound Office evidence, never trust cached confidence."""
    report_path = Path(check_path(Path(report_path)))
    report = read_json(report_path)
    if report.get('format') != FORMAT or report.get('kind') != 'measurements':
        raise ValueError('Reuse requires a text calibration measurement report')
    binding = report['binding']
    plan_dir, office_dir = Path(binding['plan_dir']), Path(binding['office_dir'])
    for path, key in ((plan_dir/'plan.json','plan_sha256'), (office_dir/'office-render.json','receipt_sha256')):
        if sha256(Path(check_path(path))) != binding[key]:
            raise ValueError('Cached calibration evidence changed')
    plan, receipt, rows, _ = _verified_measurements(plan_dir, office_dir, check_path=check_path)
    return plan, receipt, rows


def plan(scene_path, outdir, *, reuse=None, max_samples=8):
    if __package__:
        from .build_pptx import build
        from .scene_paths import load as load_scene
        from .validate_scene import validate
    else:
        from build_pptx import build
        from scene_paths import load as load_scene
        from validate_scene import validate
    if type(max_samples) is not int or not 1 <= max_samples <= 8:
        raise ValueError('Calibration supports 1..8 representative samples per request')
    source, base = load_scene(scene_path)
    errors = validate(source, base, project_root=base)
    if errors:
        raise ValueError('Invalid calibration scene: '+'; '.join(errors[:10]))
    canvas = source['canvas']
    export_size = _export_size(canvas)
    targets, deferred = _targets(source)
    env = environment(_fonts([t['object'] for t in targets]))
    cached = {}
    low_confidence = set()
    reuse_reason = 'not_requested'
    if reuse:
        old, _, rows = cache(reuse)
        if env['available'] and old['environment']['sha256'] == env['sha256']:
            cached = {r['sample_key']:r for r in rows if r['confidence'] == 'high'}
            low_confidence = {r['sample_key'] for r in rows if r['confidence'] != 'high'}
            reuse_reason = 'exact_sample_and_environment'
        else:
            reuse_reason = 'environment_changed_or_unresolved'
    selected, reused, siblings, pending = [], [], [], []
    styles = {t['style_key']:{k:t[k] for k in ('slide','id','category','sample_key','style_key')}
              for t in targets if not t['force_measure'] and t['sample_key'] in cached}
    for target in targets:
        key = target['sample_key']
        if key in low_confidence:
            target.update(force_measure=True, trigger='previous_low_confidence')
        identity = {k:target[k] for k in ('slide','id','category','sample_key','style_key')}
        if not target['force_measure'] and key in cached:
            reused.append({**identity, 'measurement': cached[key], 'evidence_report': str(Path(reuse).resolve())})
            styles.setdefault(target['style_key'], identity)
        elif not target['force_measure'] and not target.get('representative_for') and target['style_key'] in styles:
            siblings.append({**identity, 'representative': styles[target['style_key']],
                             'scope': 'style_advice_only', 'text_fit': 'unmeasured'})
        elif len(selected) < max_samples:
            selected.append(target)
            if not target['force_measure']:
                styles[target['style_key']] = identity
        else:
            pending.append({**identity, 'reason': 'sample_budget', 'trigger': target['trigger']})
    slides = []
    for i, target in enumerate(selected, 1):
        # Preserve physical coordinates and all original formatting.
        # No unmeasured text is guaranteed to stay in its frame. Keep separate
        # pages for different specimens; one Office invocation exports them all.
        slides.append({'id': f'calibration-{i}', 'objects': []})
        index = len(slides)
        obj = copy.deepcopy(target['object']); obj['id'] = f'calibration-text-{i}'
        slides[index-1]['objects'].append(obj)
        target.update(index=index, sample_id=obj['id'])
    specimen = {'version': '1.0', 'canvas': copy.deepcopy(canvas), 'slides': slides}
    with staged_directory(outdir) as stage:
        write_json(stage/'source.scene.json', source)
        if slides:
            write_json(stage/'specimens.scene.json', specimen)
            build(stage/'specimens.scene.json', stage/'specimens.pptx')
        record = {'version': FORMAT, 'source_path': str(Path(scene_path).resolve()),
                  'source_sha256': sha256(scene_path), 'source_copy_sha256': sha256(stage/'source.scene.json'),
                  'specimens_sha256': sha256(stage/'specimens.pptx') if slides else None,
                  'canvas': canvas, 'export_size_px': export_size, 'environment': env, 'references': {},
                  'targets': selected, 'reused': reused, 'style_siblings': siblings,
                  'pending': pending, 'deferred': deferred, 'reuse_reason': reuse_reason,
                  'page_exports_planned': len(slides), 'status': 'awaiting_office' if slides else 'reuse_only' if reused else 'no_supported_samples',
                  'automatic_changes': False, 'visual_review': 'pending'}
        write_json(stage/'plan.json', record)
    return {'format': FORMAT, 'status': record['status'], 'plan': str(Path(outdir)/'plan.json'),
            'samples': len(selected), 'reused': len(reused), 'style_siblings': len(siblings),
            'pending': len(pending), 'deferred': len(deferred), 'page_exports_planned': len(slides),
            'reuse_reason': reuse_reason, 'export_size_px': export_size,
            'office_arguments': ['-TextCalibration', '-Width', str(export_size[0]), '-Height', str(export_size[1])] if slides else [],
            'visual_review': 'pending', 'automatic_changes': False}


def evaluate(plan_dir, office_dir, output):
    if Path(output).exists():
        raise FileExistsError(output)
    plan, receipt, rows, canvas_validation = _verified_measurements(plan_dir, office_dir)
    if sha256(Path(plan['source_path'])) != plan['source_sha256']:
        raise ValueError('Source scene changed; regenerate a calibration plan')
    current = environment(plan['environment']['requested'])
    if current['sha256'] != plan['environment']['sha256']:
        raise ValueError('Font or Office environment changed during calibration')
    if not current['available']:
        for row in rows:
            row['confidence'] = 'low'
            row['reasons'].append('environment_identity_unresolved')
    report = {'format': FORMAT, 'kind': 'measurements', 'status': 'advisory',
              'binding': {'plan_dir': str(Path(plan_dir).resolve()), 'office_dir': str(Path(office_dir).resolve()),
                          'plan_sha256': sha256(Path(plan_dir)/'plan.json'),
                          'receipt_sha256': sha256(Path(office_dir)/'office-render.json'),
                          'source_sha256': plan['source_sha256'], 'environment_sha256': current['sha256']},
              'office_version': receipt.get('office_version'), 'targets': rows,
              'export_size_px': _export_size(plan['canvas']),
              'canvas_validation': canvas_validation,
              'reused': plan['reused'], 'style_siblings': plan['style_siblings'],
              'pending': plan['pending'], 'deferred': plan['deferred'],
              'visual_review': 'pending', 'automatic_changes': False,
              'baseline_note': 'Absolute baseline Y is unavailable. Run baseline shifts are relative Office values, not inferred page coordinates.',
              'reuse_note': 'Only exact plain samples with unchanged environment may reuse measurements. Different text shares style advice only.'}
    write_json(output, report)
    return {'format': FORMAT, 'status': 'advisory', 'report': str(output),
            'export_size_px': _export_size(plan['canvas']), 'canvas_validation': canvas_validation,
            'measured': len(rows), 'low_confidence': sum(r['confidence']=='low' for r in rows),
            'pending': len(plan['pending']), 'deferred': len(plan['deferred']),
            'visual_review': 'pending', 'automatic_changes': False}
