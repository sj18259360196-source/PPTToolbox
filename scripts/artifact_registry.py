"""Provenance for managed artifacts and bounded, read-only delivery preflight."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

if __package__:
    from .common import sha256, write_json
    from .project_layout import safe_path, read_record
else:
    from common import sha256, write_json
    from project_layout import safe_path, read_record

FORMAT = 'ppt-artifacts/1'
REQUIRED = ('candidate', 'audit', 'render', 'comparison', 'review', 'gate')


def capture(state, event, root=None):
    """Commit metadata with workflow state, using already accepted hashes only."""
    registry = state.setdefault('artifact_registry', {'format': FORMAT, 'files': {}})
    if root is not None:
        folder = safe_path(root, 'evidence/provenance')
        paths = sorted(folder.glob('*.json')) if folder.is_dir() else []
        if len(paths) > 5000:
            raise ValueError('Provenance registry exceeds 5000 records')
        for path in paths:
            relative = path.relative_to(root).as_posix()
            path = safe_path(root, relative)
            if relative not in state.setdefault('tracked_inputs', {}):
                state['tracked_inputs'][relative] = sha256(path)
    files = registry['files']
    catalog = {r['asset']: r for r in state.get('asset_catalog', [])}
    def add(path, value, role, dependencies=(), origin=None):
        row = {'file': path, 'sha256': value, 'role': role,
               'dependencies': list(dependencies), 'origin': origin or {'operation': event}}
        old = files.get(path)
        if old and old['sha256'] == value:
            row['origin'] = origin or old['origin']
            row['registered_revision'] = old['registered_revision']
        else:
            row['registered_revision'] = state.get('revision', 0)
        files[path] = row
        return {'file': path, 'sha256': value}
    for path, value in state.get('tracked_inputs', {}).items():
        item = catalog.get(path, {})
        origin = {k: item[k] for k in ('source_kind', 'provenance', 'tool_used', 'job_id', 'source_origin', 'source_sheet') if k in item}
        dependencies = []
        for path_key, hash_key in [('source_sheet', 'source_sheet_sha256')]:
            if item.get(path_key) and item.get(hash_key):
                dependencies.append({'file': item[path_key], 'sha256': item[hash_key]})
        add(path, value, 'input' if path.startswith('input/') else 'asset_or_evidence', dependencies, origin)
    for record in state.get('accepted', []):
        add(record['file'], record['sha256'], 'accepted_response')
    run = state.get('run') or {}
    frozen = []
    for path, value in run.get('frozen', {}).items():
        full = run['dir']+'/'+path
        frozen.append(add(full, value, 'frozen_input', origin={'operation': 'freeze', 'source_file': path}))
    dependencies = frozen
    for role in REQUIRED:
        record = run.get(role)
        if record:
            ref = add(record['file'], record['sha256'], role, dependencies)
            dependencies = [*dependencies, ref]
    return registry


def record_transform(root, source, output, details):
    """Write a content-addressed provenance receipt after a successful transform."""
    root, source, output = Path(root).resolve(), Path(source).resolve(), Path(output).resolve()
    target_rel = output.relative_to(root).as_posix()
    safe_path(root, target_rel)
    origin = {'path': str(source), 'sha256': sha256(source)}
    dependencies = []
    if source.is_relative_to(root):
        rel = source.relative_to(root).as_posix()
        safe_path(root, rel)
        dependencies.append({'file': rel, 'sha256': origin['sha256']})
    row = {'format': FORMAT, 'output': {'file': target_rel, 'sha256': sha256(output)},
           'origin': origin, 'dependencies': dependencies, 'operation': details['operation'],
           'parameters': {k:v for k,v in details.items() if k in {'crop_box', 'source_box', 'key', 'tolerance', 'feather', 'padding', 'threshold', 'background'}}}
    name = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()+'.json'
    path = safe_path(root, 'evidence/provenance/'+name)
    if not path.exists():
        write_json(path, row)
    return {'file': path.relative_to(root).as_posix(), 'sha256': sha256(path)}


def preflight(root, state=None, limit=5000):
    """No deletion. Candidate cleanup files are suggestions for owner review."""
    root = Path(root).resolve()
    issues, checked, cleanup, protected = [], set(), [], set()
    if state is None:
        try:
            state = read_record(safe_path(root, 'workflow/state.json'))
        except (OSError, ValueError) as exc:
            return {'status': 'unavailable', 'issues': [{'code': 'state_unavailable', 'detail': str(exc)}], 'state_changed': False}
    view = copy.deepcopy(state)
    registry = capture(view, 'legacy_state_observation')
    current = set(state.get('tracked_inputs', {})) | {r['file'] for r in state.get('accepted', [])}
    run = state.get('run') or {}
    current.update(run['dir']+'/'+rel for rel in run.get('frozen', {}))
    current.update(run[k]['file'] for k in REQUIRED if run.get(k))
    missing_evidence = [role for role in REQUIRED if not run.get(role)]
    def check(ref, dependent=None):
        rel = ref['file']; protected.add(rel)
        key = (rel, ref['sha256'])
        if key in checked:
            return
        if len(checked) >= limit:
            return
        checked.add(key)
        try:
            path = safe_path(root, rel)
            if not path.is_file():
                issues.append({'code': 'file_missing', 'file': rel, 'required_by': dependent})
            elif sha256(path) != ref['sha256']:
                issues.append({'code': 'file_changed', 'file': rel, 'required_by': dependent})
            if '.tmp' in Path(rel).parts:
                issues.append({'code': 'temporary_dependency', 'file': rel, 'required_by': dependent})
        except (OSError, ValueError) as exc:
            issues.append({'code': 'path_invalid', 'file': rel, 'detail': str(exc)})
    for rel in sorted(current):
        record = registry['files'][rel]
        check(record)
        for ref in record['dependencies']:
            check(ref, rel)
    # Only explicit, bounded provenance records are parsed. Never infer script dependencies.
    receipts = safe_path(root, 'evidence/provenance')
    provenance_count, links = 0, {}
    if receipts.is_dir():
        for path in sorted(receipts.glob('*.json'))[:limit]:
            provenance_count += 1
            try:
                row = read_record(safe_path(root, path.relative_to(root).as_posix()))
                if row.get('format') != FORMAT:
                    raise ValueError('Unknown provenance format')
                key = (row['output']['file'], row['output']['sha256'])
                links.setdefault(key, []).extend(row['dependencies'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                issues.append({'code': 'provenance_invalid', 'file': path.relative_to(root).as_posix(), 'detail': str(exc)})
    pending, visited = list(checked), set()
    while pending and len(visited) < limit:
        key = pending.pop()
        if key in visited: continue
        visited.add(key)
        for ref in links.get(key, []):
            check(ref, key[0])
            pending.append((ref['file'], ref['sha256']))
    # Walk without following junctions/symlinks. Suggestions never authorize deletion.
    import os
    scratch = safe_path(root, '.tmp/codex')
    scanned, cleanup_count = 0, 0
    if scratch.is_dir():
        for directory, dirs, names in os.walk(scratch, followlinks=False):
            for name in list(dirs):
                try: safe_path(root, (Path(directory)/name).relative_to(root).as_posix())
                except ValueError: dirs.remove(name)
            for name in names:
                scanned += 1
                if scanned > limit: break
                path = Path(directory)/name; rel = path.relative_to(root).as_posix()
                try:
                    safe_path(root, rel)
                    if rel not in protected:
                        cleanup_count += 1
                        if len(cleanup) < 20:
                            cleanup.append({'file': rel, 'bytes': path.stat().st_size, 'action': 'review_owner_and_live_use_before_removal'})
                except (OSError, ValueError): pass
            if scanned > limit: break
    limited = len(checked) >= limit or scanned > limit or provenance_count >= limit or bool(pending)
    return {'format': 'ppt-delivery-preflight/1', 'status': 'blocked' if issues or limited else 'pending_evidence' if missing_evidence else 'ready_for_existing_gate',
            'issues': issues, 'missing_evidence': missing_evidence, 'checked_files': len(checked),
            'registered_files': len(registry['files']), 'registry_available': 'artifact_registry' in state,
            'cleanup_candidates': cleanup, 'cleanup_candidate_count': cleanup_count,
            'cleanup_candidates_truncated': cleanup_count > len(cleanup), 'limited': limited, 'state_changed': False,
            'scope': 'Current managed dependencies and declared provenance only; cleanup requires owner review; formal visual and Office gates remain required.'}
