"""Archive abandoned start intents without creating projects or changing grants."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from toolbox_manager.service import Manager
from toolbox_manager.requests import archive_request, record_start, decide, list_requests, apply_saved_policy, next_action
from toolbox_manager.projects import directory
from toolbox_manager.execution import execute


@pytest.fixture
def sample(tmp_path):
    manager = Manager(tmp_path / 'data')
    args = {'project': str(tmp_path / 'never-created'), 'references': [], 'office': False}
    return manager, args, record_start(manager, args)


def archive(manager, row, value=True):
    return archive_request(manager, {'id': row['id'], 'revision': row['revision'], 'archived': value})


@pytest.mark.parametrize('status', ['pending', 'approved', 'rejected'])
def test_archive_restore_missing_folder_preserves_permission_history(sample, status):
    manager, args, row = sample
    if status != 'pending':
        row = decide(manager, {'id': row['id'], 'revision': row['revision'], 'decision': 'approve' if status == 'approved' else 'reject'})
    grants = manager.store.get('project_authorizations', {})
    settings = manager.settings()
    before = directory(manager)['revision']
    archived = archive(manager, row)
    assert archived['archived'] and archived['status'] == row['status']
    assert directory(manager)['revision'] != before
    assert record_start(manager, args) == archived
    assert apply_saved_policy(manager, row['id'], archived['revision'])['changed'] is False
    assert next_action(archived) == 'owner_restore_archived_request'
    restored = archive(manager, archived, False)
    assert restored['archived'] is False and restored['status'] == row['status']
    assert not Path(args['project']).exists()
    assert manager.store.get('workbench_projects', {}) == {}
    assert manager.store.get('project_authorizations', {}) == grants
    assert manager.settings() == settings


def test_approved_archive_blocks_retry_even_with_automatic_approval(sample):
    manager, args, row = sample
    manager.save_settings({'revision': manager.settings()['revision'], 'values': {'auto_approve_project_requests': True, 'agent_execution_enabled': True}})
    row = record_start(manager, args)
    assert row['status'] == 'approved'
    archived = archive(manager, row)
    # Changed inputs must not recreate an abandoned intent automatically.
    assert record_start(manager, {**args, 'references': [str(Path(args['project']).parent / 'other/input.png')]}) == archived
    result = execute(manager, 'start', {**args, 'references': [str(Path(args['project']).parent / 'reference.png')]}, source='mcp')
    assert result['command_status'] == 'permission_denied'
    assert result['next_action'] == 'owner_restore_archived_request'
    assert result['authorization_request']['archived']
    assert not Path(args['project']).exists()


def test_archived_pending_request_cannot_be_approved(sample):
    manager, args, row = sample
    row = archive(manager, row)
    with pytest.raises(ValueError, match='changed'):
        decide(manager, {'id': row['id'], 'revision': row['revision'], 'decision': 'approve'})
    assert not manager.store.get('project_authorizations', {})


def test_stale_revision_and_concurrent_actions_have_one_winner(sample):
    manager, args, row = sample
    def attempt(_):
        try:
            archive(manager, row)
            return 'saved'
        except ValueError:
            return 'stale'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count('saved') == 1
    assert results.count('stale') == 3
    assert len(list_requests(manager)) == 1


def test_archive_preserves_existing_files_and_rejects_registered_project(sample):
    manager, args, row = sample
    root = Path(args['project'])
    root.mkdir()
    file = root / 'owner-notes.txt'
    file.write_text('preserve', encoding='utf-8')
    row = archive(manager, row)
    assert file.read_text('utf-8') == 'preserve'
    assert list(root.iterdir()) == [file]
    from toolbox_manager.project_hub import index
    index(manager, root)
    with pytest.raises(ValueError, match='登记为项目'):
        archive(manager, row, False)


def test_running_or_unresolved_work_blocks_archive(sample):
    manager, args, row = sample
    manager.store.event('tool.authorized', 'fixture', details={'call_id': 'active', 'project': args['project']})
    with pytest.raises(ValueError, match='未确认'):
        archive(manager, row)
    assert 'archived' not in list_requests(manager)[0]


@pytest.mark.parametrize('value', [1, 'true', None])
def test_archive_requires_boolean(sample, value):
    manager, args, row = sample
    with pytest.raises(ValueError):
        archive(manager, row, value)


def test_manual_order_persists_across_archive_restore_and_does_not_touch_files(sample):
    manager, args, row = sample
    from toolbox_manager.projects import reorder
    second = record_start(manager, {**args, 'project': args['project']+'-second'})
    initial = directory(manager)
    ordered = reorder(manager, {'revision': 0, 'id': 'request:'+row['id'],
                                'relative_id': 'request:'+second['id'], 'placement': 'before'})
    assert ordered['ids'][0] == 'request:'+row['id']
    assert directory(manager)['revision'] != initial['revision']
    row = archive(manager, row)
    row = archive(manager, row, False)
    assert directory(Manager(manager.data))['order'] == ordered
    with pytest.raises(ValueError, match='顺序已变化'):
        reorder(manager, {'revision': 0, 'id': 'request:'+row['id'], 'relative_id': 'request:'+second['id'], 'placement': 'after'})
    assert not Path(args['project']).exists()
    assert not Path(second['path']).exists()


def test_manual_order_keeps_children_in_their_folder(sample):
    manager, args, row = sample
    from toolbox_manager.project_hub import index
    from toolbox_manager.projects import reorder
    root = Path(args['project']);root.mkdir()
    child = root/'child';child.mkdir()
    parent_key = index(manager, root);child_key = index(manager, child)
    before = directory(manager)
    assert 'request:'+row['id'] not in before['order']['ids']
    with pytest.raises(ValueError, match='同级'):
        reorder(manager, {'revision': 0, 'id': child_key, 'relative_id': parent_key, 'placement': 'before'})
    assert directory(manager)['order'] == before['order']


def test_activity_timestamps_do_not_reorder_or_invalidate_manual_directory(sample):
    manager, args, row = sample
    manager.store.set('workbench_projects', {'a': {'path':args['project'], 'project_id':'a', 'label':'A', 'updated_at':'2026-10-01'},
                                            'b': {'path':args['project']+'-b', 'project_id':'b', 'label':'B', 'updated_at':'2026-10-02'}})
    before = directory(manager)
    rows = manager.store.get('workbench_projects');rows['a']['updated_at']='2026-10-09'
    manager.store.set('workbench_projects', rows)
    assert directory(manager)['revision'] == before['revision']
