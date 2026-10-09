"""Bounded illustration diagnostics and editable material recipes. No Office calls."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path, PurePosixPath, PureWindowsPath


def analyze(objects, *, cubic_warning=128, subpath_warning=32):
    """Count actual commands, not estimated edit points; never mutate input."""
    counts = dict(objects=0, groups=0, leaves=0, paths=0, subpaths=0,
                  cubic_segments=0, commands=0, gradients=0, images=0, text=0)
    rows, warnings, seen = [], [], set()
    pending = [(o, 0) for o in reversed(objects)]
    while pending:
        node, depth = pending.pop()
        if not isinstance(node, dict) or depth > 32 or counts['objects'] >= 10000:
            raise ValueError('Invalid object or illustration object/depth budget exceeded')
        counts['objects'] += 1
        oid, kind = node.get('id'), node.get('kind')
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ValueError('Missing or duplicate object ID')
        seen.add(oid)
        if kind == 'group':
            counts['groups'] += 1
            children = node.get('children', [])
            if not isinstance(children, list) or len(children) > 10000:
                raise ValueError('Invalid group children')
            pending.extend((child, depth+1) for child in reversed(children))
            continue
        counts['leaves'] += 1
        counts['images'] += kind == 'image'
        counts['text'] += kind == 'text'
        commands = node.get('commands', [])
        if not isinstance(commands, list):
            raise ValueError('Invalid commands on '+oid)
        counts['commands'] += len(commands)
        if counts['commands'] > 100000:
            raise ValueError('Illustration command budget exceeded')
        for c in commands:
            if (not isinstance(c, list) or not c or c[0] not in ('M', 'L', 'C', 'Z')
                    or len(c) != {'M': 3, 'L': 3, 'C': 7, 'Z': 1}[c[0]]
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in c[1:])):
                raise ValueError('Invalid path command on '+oid)
        cubic = sum(c[0] == 'C' for c in commands)
        subpaths = sum(c[0] == 'M' for c in commands)
        counts['paths'] += kind == 'path'
        counts['cubic_segments'] += cubic
        counts['subpaths'] += subpaths
        style = node.get('style', {})
        if not isinstance(style, dict):
            raise ValueError('Invalid style on '+oid)
        gradient = style.get('gradient')
        counts['gradients'] += bool(gradient)
        row = dict(id=oid, kind=kind, commands=len(commands), cubic_segments=cubic, subpaths=subpaths)
        rows.append(row)
        if cubic >= cubic_warning or subpaths >= subpath_warning:
            warnings.append(dict(id=oid, code='edit_complexity', cubic_segments=cubic, subpaths=subpaths))
        if gradient and style.get('fill_alpha', 1) != 1:
            warnings.append(dict(id=oid, code='composed_alpha',
                                 note='Object alpha and stop alpha multiply; inspect the actual background.'))
        if style.get('native_format', {}).get('shadow', {}).get('enabled'):
            warnings.append(dict(id=oid, code='preview_shadow_parity',
                                 note='SVG filter and Office shadow require separate visual review.'))
        if kind == 'path' and subpaths > 1:
            warnings.append(dict(id=oid, code='compound_path',
                                 note='Multiple subpaths may be texture or holes; winding is not certified here.'))
    return {'format': 'illustration-analysis/1', 'counts': counts,
            'thresholds': {'cubic_warning': cubic_warning, 'subpath_warning': subpath_warning},
            'most_complex': sorted(rows, key=lambda x: (x['cubic_segments'], x['subpaths'], x['commands']), reverse=True)[:20],
            'warnings': warnings[:200], 'warning_count': len(warnings),
            'warnings_truncated': len(warnings) > 200,
            'scope': 'structure_diagnostics_not_editability_or_visual_acceptance',
            'office': 'not_run', 'visual_review': 'pending'}


def ellipse(cx, cy, rx, ry, rotation=0):
    k = .5522847498307936
    commands = [['M', cx+rx, cy], ['C', cx+rx, cy+k*ry, cx+k*rx, cy+ry, cx, cy+ry],
                ['C', cx-k*rx, cy+ry, cx-rx, cy+k*ry, cx-rx, cy],
                ['C', cx-rx, cy-k*ry, cx-k*rx, cy-ry, cx, cy-ry],
                ['C', cx+k*rx, cy-ry, cx+rx, cy-k*ry, cx+rx, cy], ['Z']]
    a = math.radians(rotation)
    for c in commands:
        for j in range(1, len(c), 2):
            x, y = c[j]-cx, c[j+1]-cy
            c[j] = cx+x*math.cos(a)-y*math.sin(a)
            c[j+1] = cy+x*math.sin(a)+y*math.cos(a)
    return commands


def material_recipe(preset, identifier, box, canvas, *, rotation=0, points_per_unit=1):
    """New parameterized examples, not the historical bottom-row generator."""
    from graphics_recipe import validate_recipe, native_path
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in [*box, *canvas, rotation, points_per_unit]):
        raise ValueError('Material parameters must be finite numbers')
    x, y, w, h = box
    cx, cy = x+w/2, y+h/2
    paths, roles = [], {}

    def add(suffix, commands, style, closed=True):
        oid = identifier+'_'+suffix
        paths.append(dict(id=oid, commands=commands, closed=closed, style=style))
        roles[oid] = suffix

    def oval(dx=0, dy=0, sx=1, sy=1):
        # Offset centers rotate with the material, not about themselves.
        a = math.radians(rotation)
        return ellipse(cx+w*dx*math.cos(a)-h*dy*math.sin(a),
                       cy+w*dx*math.sin(a)+h*dy*math.cos(a), w*sx/2, h*sy/2, rotation)

    def fill(color, alpha=1):
        return dict(fill=color, line=None, fill_alpha=alpha)

    def grad(colors, angle):
        return dict(fill=None, line=None, gradient=dict(type='linear', angle_deg=angle % 360,
                    stops=[dict(position=i/(len(colors)-1), color=c) for i, c in enumerate(colors)]))

    if preset == 'rotated_end':
        add('rim', oval(), grad(['829CAE', 'E4EDF3', '7894A9'], rotation+35))
        add('cavity', oval(sx=.65, sy=.77), grad(['38556B', '7899B0'], rotation+70))
        add('inner_edge', oval(sx=.80, sy=.90), dict(fill=None, line='D0E0EB', line_width_pt=.48))
    elif preset == 'droplet':
        add('shadow', oval(.06, .14, 1.04, .90), fill('214B64', .24))
        add('volume', oval(), grad(['628FA6', 'BDDBE5', '79ACC1'], rotation+90))
        add('lower_light', oval(0, .27, .65, .15), fill('DAF8FF', .65))
        add('specular', oval(-.18, -.22, .30, .17), fill('FFFFFF', .9))
    else:
        raise ValueError('Unknown material preset')
    recipe = dict(format='graphics-recipe/1', id=identifier, canvas=canvas,
                  points_per_unit=points_per_unit, paths=paths, order=[p['id'] for p in paths])
    # These presets contain authored paths only. Validate the same recipe and
    # scene contracts without loading the numerical curve-fitting runtime.
    validate_recipe(recipe)
    objects = [native_path(p['id'], p['commands'], p['closed'], p['style']) for p in paths]
    from validate_scene import validate
    scene = dict(version='1.0', canvas=dict(width=canvas[0], height=canvas[1],
                 width_pt=canvas[0]*points_per_unit, height_pt=canvas[1]*points_per_unit, mapping='uniform'),
                 slides=[dict(id='material', objects=objects)])
    errors = validate(scene, Path(__file__).resolve().parents[1], check_files=False)
    if errors:
        raise ValueError('; '.join(errors[:5]))
    return dict(format='illustration-material/1', recipe=recipe, roles=roles,
                objects=objects, analysis=analyze(objects),
                scope='new_parameterized_example_not_historical_generator',
                limitations=['ellipse_based_draft_adjust_contour_to_reference',
                             'no_physical_refraction', 'review_lighting_after_transform',
                             'group_material_parts_when_submitting'],
                office='not_run', visual_review='pending')


def audit_sources(project, dependencies):
    """Hash explicit dependencies inside one authorized project, never execute them."""
    root = Path(project).resolve()
    rows = []
    for dependency in dependencies:
        name = dependency['path']
        normalized = name.replace('\\', '/')
        rel = PurePosixPath(normalized)
        if (not name or rel.is_absolute() or PureWindowsPath(name).drive
                or any(p in ('..', '') for p in rel.parts) or ':' in name):
            raise ValueError('Dependency must be a project-relative path')
        target = (root / normalized).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Dependency escapes project')
        row = dict(path=normalized, role=dependency['role'],
                   temporary=any(p.lower() in ('.tmp', 'tmp', 'temp')
                                 for p in (*rel.parts, *target.relative_to(root).parts)))
        if not target.is_file():
            row['status'] = 'missing'
        elif target.stat().st_size > 16_000_000:
            row['status'] = 'too_large_to_audit'
        else:
            row['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            row['status'] = 'hash_mismatch' if dependency.get('sha256', row['sha256']) != row['sha256'] else 'present'
        rows.append(row)
    return dict(format='illustration-source-audit/1', files=rows,
                status='needs_attention' if any(r['status'] != 'present' or r['temporary'] for r in rows) else 'listed_files_verified',
                scope='explicit_dependency_list_only_import_completeness_not_verified',
                office='not_run', visual_review='pending')
