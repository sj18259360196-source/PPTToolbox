"""Versioned scene paths. Resolving a base never grants filesystem permission."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

if __package__:
    from .common import read_json, resolve_asset
else:
    from common import read_json, resolve_asset


def base_for(scene, directory, project_root=None):
    if not isinstance(scene, dict):
        raise ValueError('Scene must be an object')
    directory = Path(directory).resolve()
    if scene.get('version') != '1.1':
        return directory
    if scene.get('path_base') != 'project_root':
        raise ValueError('Scene 1.1 requires path_base=project_root')
    root = project_root or os.environ.get('PPT_USAGE_PROJECT')
    if root:
        root = Path(root).resolve()
    else:
        candidates = [p for p in (directory, *directory.parents)
                      if (p/'workflow/state.json').is_file()]
        if len(candidates) != 1:
            raise ValueError('Scene 1.1 needs one explicit managed project root; '
                             'missing or nested project roots are ambiguous')
        root = candidates[0]
    if not directory.is_relative_to(root):
        raise ValueError('Scene directory is outside the selected project root')
    return root


def prepare(scene, directory, project_root=None):
    """Return a copy and path preview; never rewrite the authored scene."""
    base = base_for(scene, directory, project_root)
    normalized = copy.deepcopy(scene)
    records = []
    modern = scene.get('version') == '1.1'

    def scan(value, pointer=''):
        if isinstance(value, dict):
            for key, item in value.items():
                field = pointer+'/'+key.replace('~', '~0').replace('/', '~1')
                requirement = bool(re.fullmatch(
                    r'/slides/\d+/element_scope/material_contract/requirement_sources/\d+/file', field))
                if (key in {'reference', 'asset', 'drawing'} or requirement) and isinstance(item, str):
                    row = {'field': field, 'value': item, 'base': str(base),
                           'purpose': 'requirement_source' if requirement else key}
                    if requirement or re.fullmatch(r'/slides/\d+/element_scope/units/\d+/source/asset', field):
                        if 'sha256' in value:
                            row['expected_sha256'] = value['sha256']
                    try:
                        candidate = Path(item)
                        if modern:
                            if PureWindowsPath(item).is_absolute() and not candidate.is_absolute():
                                raise ValueError('Foreign absolute path cannot be resolved on this host')
                            resolved = (candidate if candidate.is_absolute() else base/candidate).resolve()
                            if not resolved.is_relative_to(base):
                                raise ValueError('Path leaves the selected project root')
                            relative = resolved.relative_to(base).as_posix()
                        else:
                            relative = item
                        row.update(resolved=str((base/relative).resolve()), normalized=relative,
                                   changed=relative != item)
                        # Reuse the existing symlink-aware containment and file checks.
                        resolved = resolve_asset(base, relative)
                        row.update(resolved=str(resolved), exists=True,
                                   normalized=relative, changed=relative != item)
                        if modern:
                            value[key] = relative
                    except (OSError, ValueError) as exc:
                        row.update(exists=False, error=str(exc))
                    records.append(row)
                elif isinstance(item, (dict, list)):
                    scan(item, field)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                scan(item, pointer+'/'+str(index))

    scan(normalized)
    return normalized, base, records



def dependency_records(scene, directory, project_root=None):
    """Collect only declared dependency fields, retaining every reference."""
    normalized, base, records = prepare(scene, directory, project_root)
    for row in records:
        if not row.get('exists'):
            continue
        try:
            row['sha256'] = hashlib.sha256(Path(row['resolved']).read_bytes()).hexdigest()
            if row.get('expected_sha256', row['sha256']) != row['sha256']:
                raise ValueError('Declared dependency SHA-256 does not match file')
        except (OSError, ValueError) as exc:
            row.update(error=str(exc))
    return normalized, base, records


def require_dependencies(records):
    errors = [r['field'] + ': ' + r.get('error', 'missing file')
              for r in records if 'error' in r or not r.get('exists')]
    if errors:
        raise ValueError('Scene dependency errors: ' + '; '.join(errors))


def copy_dependencies(records, source, destination):
    """Validate the complete copy plan, preserve existing bytes, then verify copies."""
    require_dependencies(records)
    destination = Path(destination).resolve()
    planned = {}
    for row in records:
        relative = row['normalized']
        dest = (destination/relative).resolve()
        if not dest.is_relative_to(destination):
            raise ValueError('Dependency destination leaves the bundle: ' + relative)
        src = resolve_asset(source, relative)
        if hashlib.sha256(src.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Dependency changed during copy: ' + relative)
        if dest.exists() and (not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest() != row['sha256']):
            raise ValueError('Dependency destination collision: ' + relative)
        if dest in planned and planned[dest][2] != row['sha256']:
            raise ValueError('Dependency destination collision: ' + relative)
        planned[dest] = (src, relative, row['sha256'])
    for dest, (src, relative, expected) in planned.items():
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also protects a destination appearing after preflight.
            with src.open('rb') as incoming, dest.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        if hashlib.sha256(resolve_asset(destination, relative).read_bytes()).hexdigest() != expected:
            raise ValueError('Dependency changed during copy: ' + relative)
    return {relative for _, relative, _ in planned.values()}


def dependency_manifest(records):
    require_dependencies(records)
    fields = ('field', 'normalized', 'purpose', 'sha256')
    return {'format': 'scene-dependencies/1', 'files': sorted(
        [{key: row[key] for key in fields} for row in records],
        key=lambda row: (row['normalized'], row['field']))}

def load(path, project_root=None):
    path = Path(path).resolve()
    scene, base, records = dependency_records(read_json(path), path.parent, project_root)
    require_dependencies(records)
    return scene, base


