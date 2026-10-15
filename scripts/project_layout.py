"""Shared project directory contract and read-only reference resolution."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

CONTRACT = {
    'format': 'ppt-project-layout/1',
    'directories': {'input': 'original references and references.json',
        'assets': 'persistent material and generators', 'runs': 'managed candidate versions',
        'workflow': 'managed state and tasks', 'evidence': 'version-linked checks',
        'delivery': 'formal deliverables', 'logs/tool-calls': 'managed call logs',
        '.tmp/codex/<task>': 'task-owned temporary files'},
    'asset_outputs': {'crop': 'assets/crops', 'generated': 'assets/generated',
        'imported': 'assets/imported', 'native': 'assets/native'},
    'reference_index': 'input/references.json',
    'legacy_versions': 'build',
    'rules': ['Never overwrite original inputs.', 'Update workflow state through managed tools.',
        'Do not automatically move legacy files.', 'Remove task-owned temporary files only after checking dependencies.'],
    'manual': 'references/project-layout.md',
}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}

def read_record(path):
    if path.stat().st_size > 16*1024*1024: raise ValueError('Project metadata exceeds 16 MB')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def safe_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Expected a portable project-relative path')
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('Path leaves project')
    target = root / p
    for part in (target, *target.parents):
        if part == root: break
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Linked project paths are not supported')
    if not target.resolve().is_relative_to(root): raise ValueError('Path leaves project')
    return target

def references(root, state=None):
    """Use explicit metadata only; malformed manifests never trigger a folder scan."""
    root = Path(root)
    issues = []
    manifest = root / 'input/references.json'
    source = 'manifest' if manifest.exists() else 'workflow'
    try:
        if manifest.exists():
            rows = read_record(safe_path(root, 'input/references.json'))
            if not isinstance(rows, list): raise ValueError('Reference manifest must be a list')
        else:
            if state is None:
                state = read_record(safe_path(root, 'workflow/state.json'))
            rows = [{'slide': p.get('index', i), 'path': p.get('reference'), 'sha256': p.get('sha256')}
                    for i, p in enumerate(state.get('pages', []), 1)]
        if not rows: issues.append({'code': 'references_not_registered', 'path': 'input/references.json'})
        if len(rows) > 5000: raise ValueError('Reference index exceeds 5000 pages')
        indexed = []
        seen = set()
        seen_paths = set()
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict): raise ValueError('Invalid reference row')
            index = row.get('slide', i)
            if type(index) is not int or index < 1 or index in seen: raise ValueError('Invalid or duplicate reference page')
            seen.add(index)
            rel = row.get('path')
            try:
                p = safe_path(root, rel)
                if rel.casefold() in seen_paths: issues.append({'code':'reference_duplicate','path':rel})
                seen_paths.add(rel.casefold())
                if p.suffix.lower() not in IMAGE_SUFFIXES: raise ValueError('Unsupported reference format')
                exists = p.is_file()
                indexed.append({'path': rel, 'name': p.name, 'slide': index,
                    'modified_ns': p.stat().st_mtime_ns if exists else 0,
                    'missing': not exists, 'sha256': row.get('sha256')})
                if not exists: issues.append({'code': 'reference_missing', 'path': rel})
            except (OSError, ValueError) as exc:
                issues.append({'code': 'reference_path_invalid', 'path': rel, 'detail': str(exc)})
        return {'source': source, 'pages': sorted(indexed, key=lambda r: r['slide']), 'issues': issues}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {'source': source, 'pages': [], 'issues': [{'code': 'reference_index_invalid', 'path': 'input/references.json', 'detail': str(exc)}]}

def check_output(root, destination):
    root = Path(root).resolve()
    dest = Path(destination).resolve()
    if not dest.is_relative_to(root): raise ValueError('Asset output leaves project')
    rel = dest.relative_to(root).as_posix()
    safe_path(root, rel)
    if rel.split('/')[0] in {'input', 'workflow', 'delivery', 'runs', 'logs'}:
        raise ValueError('Material output must use assets/ or a task-owned temporary directory')
    for row in references(root)['pages']:
        if dest == safe_path(root, row['path']).resolve(): raise ValueError('Never overwrite a registered reference')
    return rel

def audit(root):
    """Bounded inspection only; never executes sources, creates files or moves assets."""
    root = Path(root).resolve()
    refs = references(root)
    issues = [{**r, 'severity': 'error'} for r in refs['issues']]
    registered = {r['path'] for r in refs['pages']}
    for row in refs['pages']:
        if not row['missing'] and row.get('sha256'):
            with safe_path(root, row['path']).open('rb') as stream: actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != row['sha256']: issues.append({'code': 'reference_changed', 'path': row['path'], 'severity': 'error'})
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', 'node_modules', '__pycache__'})
        for d in list(dirs):
            try: safe_path(root, (Path(directory)/d).relative_to(root).as_posix())
            except ValueError:
                dirs.remove(d)
                issues.append({'code': 'linked_path', 'path': (Path(directory)/d).relative_to(root).as_posix(), 'severity': 'error'})
        for name in files:
            count += 1
            if count > 5000:
                return {'status': 'needs_attention', 'issues': issues, 'limited': True, 'contract': CONTRACT}
            rel = (Path(directory)/name).relative_to(root).as_posix()
            if rel.startswith('input/') and Path(name).suffix.lower() in IMAGE_SUFFIXES and rel not in registered:
                issues.append({'code': 'unregistered_input_image', 'path': rel, 'severity': 'warning', 'suggested_directory': 'assets/crops'})
    if (root/'build').exists(): issues.append({'code': 'legacy_versions_directory', 'path': 'build', 'severity': 'warning'})
    # Inspect explicitly declared scene references/assets. No inference from script text.
    scenes = [root/'scene.json']
    try:
        state = read_record(safe_path(root, 'workflow/state.json'))
        run = state.get('run') or {}
        if run.get('dir'): scenes.append(safe_path(root, run['dir']+'/scene.json'))
    except (OSError, ValueError): pass
    def inspect(value, base):
        if __package__:
            from .scene_paths import dependency_records
        else:
            from scene_paths import dependency_records
        _, _, rows = dependency_records(value, base, root)
        for row in rows:
            item = row['value']
            try:
                resolved = Path(row.get('resolved', str(base/item))).resolve()
                p = safe_path(root, resolved.relative_to(root).as_posix())
                if '.tmp' in p.parts or 'Temp' in p.parts:
                    issues.append({'code': 'temporary_dependency', 'path': item, 'severity': 'error'})
                if not row.get('exists'):
                    issues.append({'code': 'dependency_missing', 'path': item, 'field': row['field'], 'severity': 'error', 'detail': row.get('error')})
                elif row.get('error'):
                    issues.append({'code': 'dependency_changed', 'path': item, 'field': row['field'], 'severity': 'error', 'detail': row['error']})
            except ValueError:
                issues.append({'code': 'external_dependency', 'path': item, 'field': row['field'], 'severity': 'error'})
    for scene in scenes:
        if not scene.is_file(): continue
        try:
            data = read_record(safe_path(root, scene.relative_to(root).as_posix()))
            inspect(data, root if data.get('path_base') == 'project_root' else scene.parent)
        except (OSError, ValueError) as exc:
            issues.append({'code': 'scene_invalid', 'path': scene.relative_to(root).as_posix(), 'severity': 'error', 'detail': str(exc)})
    return {'status': 'needs_attention' if issues else 'passed', 'issues': issues, 'limited': False,
        'contract': CONTRACT, 'scope': 'Registered references and explicit current-scene dependencies; no script execution or visual acceptance.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.project), ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__': raise SystemExit(main())
