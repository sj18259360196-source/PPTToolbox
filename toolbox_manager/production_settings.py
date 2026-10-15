"""Owner-saved defaults and immutable project snapshots, separate from permissions."""
from __future__ import annotations
import json
from pathlib import Path
from scripts.production_settings import defaults, definitions, instructions, snapshot, validate_values
from .storage import stamp

GLOBAL_KEY = 'production_settings:defaults'


def _root(manager, project):
    from .project_context import ProjectContext
    if isinstance(project, str) and not Path(project).is_absolute():
        from .workbench import Workbench
        project = Workbench(manager).entry(project)[0]
    return ProjectContext(manager, project).root


def _key(root):
    return 'production_settings:project:' + str(root)


def _global(manager):
    row = manager.store.get(GLOBAL_KEY, {})
    return snapshot({**defaults(), **row.get('values', {})}, row.get('revision', 0), 'global_default')


def _applied(root):
    path = root / 'workflow/state.json'
    if path.is_file():
        state = json.loads(path.read_text(encoding='utf-8-sig'))
        return state.get('production_settings')
    return None


def _regions(root):
    path = root / 'workflow/state.json'
    if not path.is_file():
        return []
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    return [{'slide_id': page['id'], 'region_id': region['id'],
             'label': f"第 {page.get('index', index + 1)} 页 · {region.get('summary') or region['id']}",
             'completed': region['id'] in page.get('fragments', {})}
            for index, page in enumerate(state.get('pages', []))
            for region in (page.get('plan') or {}).get('regions', [])]


def effective(manager, project=None, *, read_state=True):
    global_row = _global(manager)
    pending = None
    applied = None
    legacy = False
    available_regions = []
    if project is None:
        row = global_row
    else:
        root = _root(manager, project)
        record = manager.store.get(_key(root))
        applied = _applied(root) if read_state else None
        available_regions = _regions(root) if read_state else []
        if record:
            row = snapshot(record['values'], record['revision'], 'project_snapshot')
            pending = record.get('pending')
        elif applied:
            row = snapshot(applied['values'], applied.get('revision', 0), 'workflow_snapshot')
        elif root.exists():
            legacy = True
            row = {'values': None, 'revision': 0, 'source': 'legacy', 'effective_sha256': None,
                   'instructions': instructions(None)}
        else:
            row = {**global_row, 'source': 'new_project_default'}
    return {**row, 'saved': {k: row[k] for k in ('values', 'revision', 'source', 'effective_sha256')},
            'legacy': legacy, 'applied': applied, 'pending': pending,
            'global_values': global_row['values'], 'global_revision': global_row['revision'],
            'definitions': definitions(), 'available_regions': available_regions, 'permission_effect': 'none'}


def ensure_project(manager, project, *, new=False):
    """Snapshot defaults once for a new project; existing historical roots stay legacy."""
    root = _root(manager, project)
    key = _key(root)
    if (root / 'workflow/state.json').is_file() or (root.exists() and not new):
        return effective(manager, root)
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM kv WHERE key=?', (key,)).fetchone():
            value = _global(manager)
            db.execute('INSERT INTO kv VALUES (?,?)', (key, json.dumps({
                'values': value['values'], 'revision': 0, 'source_global_revision': value['revision'],
                'created': stamp(), 'pending': None}, ensure_ascii=False)))
    return effective(manager, root)


def save(manager, body):
    if not isinstance(body, dict) or set(body) - {'project', 'revision', 'values', 'restore_defaults', 'apply_scope', 'selected_objects'}:
        raise ValueError('Invalid production settings request')
    project = body.get('project')
    root = _root(manager, project) if project else None
    key = _key(root) if root else GLOBAL_KEY
    if type(body.get('revision')) is not int or body['revision'] < 0:
        raise ValueError('Production settings revision is required')
    scope = body.get('apply_scope', 'unfinished')
    selected = body.get('selected_objects', [])
    if scope not in {'unfinished', 'selected_completed'} or not isinstance(selected, list) or len(selected) > 500 or any(
            not isinstance(x, dict) or set(x) != {'slide_id', 'region_id'} or
            any(not isinstance(x[k], str) or not x[k].strip() for k in ('slide_id', 'region_id')) for x in selected):
        raise ValueError('Invalid production apply scope')
    if scope == 'selected_completed' and not selected:
        raise ValueError('Select completed objects for formal revision')
    if scope == 'selected_completed':
        if root is None:
            raise ValueError('Completed object revision requires a project')
        available = {(x['slide_id'], x['region_id']) for x in _regions(root) if x['completed']}
        if any((x['slide_id'], x['region_id']) not in available for x in selected):
            raise ValueError('Selected completed regions changed; refresh the project')
    if 'restore_defaults' in body and type(body['restore_defaults']) is not bool:
        raise ValueError('restore_defaults must be boolean')
    values = validate_values(_global(manager)['values'] if body.get('restore_defaults') else body.get('values'))
    saved_change = False
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        applied = _applied(root) if root else None
        # A workflow snapshot is also the baseline returned by GET when the
        # manager has no override. CAS must compare the same visible version.
        global_row = _global(manager)
        record = json.loads(old[0]) if old else ({'revision': applied.get('revision', 0),
            'values': applied['values'], 'pending': None} if applied else
            {'revision': global_row['revision'], 'values': global_row['values'], 'pending': None}
            if root is None or not root.exists() else {'revision': 0})
        if body['revision'] != record['revision']:
            raise ValueError('制作设置已被另一窗口修改，请刷新后重试')
        changed = [k for k, v in values.items() if (record.get('values') or {}).get(k) != v]
        previous = record.get('pending') or {}
        # Recover a receipt that the workflow has already applied, without
        # issuing a new settings version or reopening completed work.
        if previous and applied and applied.get('revision') == record['revision'] and applied.get('effective_sha256') == snapshot(record['values'], record['revision'])['effective_sha256']:
            previous = {}
            record['pending'] = None
            if old:
                db.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(record, ensure_ascii=False), key))
        queued = {(item['slide_id'], item['region_id']): dict(item)
                  for item in previous.get('selected_objects', [])}
        requested = {(item['slide_id'], item['region_id']): dict(item) for item in selected}
        additional_selection = requested.keys() - queued.keys()
        queued.update(requested)
        if root and not old and not applied and not root.exists() and not changed:
            # Saving the currently displayed default still freezes a project
            # snapshot. Later global edits must not change that owner's choice.
            db.execute('INSERT INTO kv VALUES (?,?)', (key, json.dumps({**record,
                'values': values, 'pending': None, 'updated': stamp()}, ensure_ascii=False)))
        if changed or additional_selection:
            saved_change = True
            revision = record['revision'] + 1
            pending = None
            if root:
                pending = {'revision': revision,
                    'changed_fields': sorted(set(changed + previous.get('changed_fields', []))),
                    'scope': 'selected_completed' if queued else 'unfinished',
                    'selected_objects': list(queued.values()), 'requested_at': stamp()}
            saved = {**record, 'values': values, 'revision': revision, 'pending': pending, 'updated': stamp()}
            db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(saved, ensure_ascii=False)))
    if saved_change:
        manager.store.event('production.settings.saved', '已保存制作设置', source='owner', details={'project': str(root) if root else None, 'changed_fields': changed})
    return effective(manager, root)


def mark_applied(manager, project, revision):
    """Clear only the revision actually applied by the governed workflow."""
    root = _root(manager, project)
    key = _key(root)
    with manager.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        if row:
            record = json.loads(row[0])
            if record['revision'] == revision:
                record['pending'] = None
                db.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(record, ensure_ascii=False), key))
    return effective(manager, root)
