"""Versioned scene paths. Resolving a base never grants filesystem permission."""
from __future__ import annotations

import copy
import os
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
                if key in {'reference', 'asset', 'drawing'} and isinstance(item, str):
                    row = {'field': field, 'value': item, 'base': str(base)}
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


def load(path, project_root=None):
    path = Path(path).resolve()
    scene, base, records = prepare(read_json(path), path.parent, project_root)
    errors = [r['field']+': '+r['error'] for r in records if 'error' in r]
    if errors:
        raise ValueError('Scene path errors: '+'; '.join(errors))
    return scene, base
