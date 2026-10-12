"""Persistence, conflicts and legacy preservation; no Office acceptance claims."""
import copy
import json
from pathlib import Path
import pytest
from scripts import production_settings as pure
from toolbox_manager import production_settings as settings
from toolbox_manager.service import Manager
from toolbox_manager.project_context import bind
from toolbox_manager.mcp import MCP


@pytest.fixture
def manager(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / 'SKILL.md').write_text('---\nversion: "1.27.4"\n---\n# Skill', encoding='utf-8')
    return Manager(tmp_path / 'data', root=root)


def test_canonical_validation_hash_and_definitions_are_isolated():
    assert pure.defaults() == {'illustration_mode': 'generate_first', 'font_matching': 'similar', 'text_layout': 'paragraph'}
    assert pure.snapshot(pure.defaults())['effective_sha256'] == pure.snapshot(dict(reversed(list(pure.defaults().items()))))['effective_sha256']
    for values in ({}, {**pure.defaults(), 'font_matching': 'unknown'}, {**pure.defaults(), 'quality': 'low'}):
        with pytest.raises(ValueError):
            pure.validate_values(values)
    d = pure.definitions()
    d[0]['options'][0]['label'] = 'mutated'
    assert pure.definitions()[0]['options'][0]['label'] != 'mutated'
    assert 'paragraphs' in '\n'.join(pure.instructions(pure.defaults()))


def test_new_snapshot_global_changes_do_not_migrate_existing(manager, tmp_path):
    project = tmp_path / 'new-project'
    first = bind(manager, project=project)
    assert not project.exists()
    assert first['production_settings']['source'] == 'project_snapshot'
    new_values = {**pure.defaults(), 'illustration_mode': 'draw_first'}
    global_row = settings.save(manager, {'revision': 0, 'values': new_values})
    assert global_row['revision'] == 1
    assert settings.effective(manager, project)['values'] == pure.defaults()
    assert settings.effective(manager, tmp_path / 'next-project')['values'] == new_values
    restarted = Manager(manager.data, root=manager.root)
    assert settings.effective(restarted, project)['values'] == pure.defaults()


def test_legacy_read_only_and_explicit_adoption_pending(manager, tmp_path):
    project = tmp_path / 'historic'
    (project / 'workflow').mkdir(parents=True)
    state = project / 'workflow/state.json'
    original = json.dumps({'project_id': 'old', 'revision': 17, 'status': 'delivered'})
    state.write_text(original, encoding='utf-8')
    previous_permissions = copy.deepcopy(manager.settings())
    old = settings.effective(manager, project)
    assert old['legacy'] and old['values'] is None and old['applied'] is None
    assert settings.ensure_project(manager, project)['legacy']
    assert settings.ensure_project(manager, project, new=True)['legacy']
    saved = settings.save(manager, {'project': str(project), 'revision': 0, 'values': pure.defaults()})
    assert not saved['legacy'] and saved['pending']['scope'] == 'unfinished'
    assert state.read_text(encoding='utf-8') == original
    assert manager.settings() == previous_permissions
    assert not manager.store.get('project_authorizations', {})
    with pytest.raises(ValueError, match='另一窗口'):
        settings.save(manager, {'project': str(project), 'revision': 0, 'values': pure.defaults()})


def test_pending_scope_cas_and_applied_workflow_readback(manager, tmp_path):
    project = tmp_path / 'task'
    settings.ensure_project(manager, project)
    changed = {**pure.defaults(), 'text_layout': 'line'}
    with pytest.raises(ValueError, match='Select completed'):
        settings.save(manager, {'project': str(project), 'revision': 0, 'values': changed, 'apply_scope': 'selected_completed'})
    selected = [{'slide_id': 'slide-1', 'region_id': 'region-2'}]
    (project / 'workflow').mkdir(parents=True)
    (project / 'workflow/state.json').write_text(json.dumps({'pages': [{
        'id': 'slide-1', 'index': 1, 'plan': {'regions': [{'id': 'region-2', 'summary': 'Caption'}]},
        'fragments': {'region-2': {}}}]}), encoding='utf-8')
    saved = settings.save(manager, {'project': str(project), 'revision': 0, 'values': changed,
                                  'apply_scope': 'selected_completed', 'selected_objects': selected})
    assert saved['pending']['selected_objects'] == selected
    assert settings.mark_applied(manager, project, 0)['pending']
    applied = pure.snapshot(changed, saved['revision'], 'project_snapshot')
    (project / 'workflow/state.json').write_text(json.dumps({'production_settings': applied}), encoding='utf-8')
    assert settings.mark_applied(manager, project, saved['revision'])['pending'] is None
    assert settings.effective(manager, project)['applied'] == applied


def test_mcp_query_read_only_registered_and_context_values(manager, tmp_path):
    client = MCP(manager.data, root=manager.root)
    assert 'toolbox_production_settings' in {row[0] for row in __import__('toolbox_manager.mcp', fromlist=['TOOLS']).TOOLS}
    before = manager.store.get(settings.GLOBAL_KEY)
    result = client.call('toolbox_production_settings', {})
    assert result['values'] == pure.defaults()
    assert manager.store.get(settings.GLOBAL_KEY) == before
    assert client.call('toolbox_project_bind', {'project': str(tmp_path / 'bound')})['production_settings']['values'] == result['values']


def test_ungranted_binding_does_not_read_workflow_settings(manager, tmp_path):
    project = tmp_path / 'ungranted'
    (project / 'workflow').mkdir(parents=True)
    (project / 'workflow/state.json').write_text('invalid protected workflow data', encoding='utf-8')
    client = MCP(manager.data, root=manager.root)
    bound = client.call('toolbox_project_bind', {'project': str(project)})
    assert bound['production_settings']['legacy']
    assert client.call('toolbox_production_settings', {})['applied'] is None


def test_workflow_snapshot_without_manager_override_is_cas_baseline(manager, tmp_path):
    project = tmp_path / 'workflow-owned'
    (project / 'workflow').mkdir(parents=True)
    applied = pure.snapshot({**pure.defaults(), 'font_matching': 'precise'}, 7, 'project_snapshot')
    state = project / 'workflow/state.json'
    state.write_text(json.dumps({'production_settings': applied}), encoding='utf-8')
    original = state.read_bytes()
    read = settings.effective(manager, project)
    assert read['revision'] == 7 and read['source'] == 'workflow_snapshot'
    unchanged = settings.save(manager, {'project': str(project), 'revision': 7, 'values': read['values']})
    assert unchanged['revision'] == 7 and unchanged['pending'] is None
    assert manager.store.get(settings._key(project)) is None
    updated = settings.save(manager, {'project': str(project), 'revision': 7,
        'values': {**read['values'], 'text_layout': 'line'}})
    assert updated['revision'] == 8 and updated['pending']['changed_fields'] == ['text_layout']
    assert state.read_bytes() == original
    with pytest.raises(ValueError, match='另一窗口'):
        settings.save(manager, {'project': str(project), 'revision': 7, 'values': read['values']})


def test_queued_completed_selection_survives_later_unfinished_changes(manager, tmp_path):
    project = tmp_path / 'queued'
    settings.ensure_project(manager, project)
    (project / 'workflow').mkdir(parents=True)
    regions = [{'id': 'one', 'summary': 'One'}, {'id': 'two', 'summary': 'Two'}]
    (project / 'workflow/state.json').write_text(json.dumps({'pages': [{
        'id': 'slide-1', 'plan': {'regions': regions}, 'fragments': {'one': {}, 'two': {}}}]}), encoding='utf-8')
    selected = [{'slide_id': 'slide-1', 'region_id': 'one'}]
    first = settings.save(manager, {'project': str(project), 'revision': 0, 'values': pure.defaults(),
        'apply_scope': 'selected_completed', 'selected_objects': selected})
    next_values = {**pure.defaults(), 'font_matching': 'precise'}
    later = settings.save(manager, {'project': str(project), 'revision': first['revision'],
        'values': next_values, 'apply_scope': 'unfinished', 'selected_objects': []})
    assert later['pending']['scope'] == 'selected_completed'
    assert later['pending']['selected_objects'] == selected
    same = settings.save(manager, {'project': str(project), 'revision': later['revision'], 'values': next_values})
    assert same['revision'] == later['revision'] and same['pending'] == later['pending']
    union = settings.save(manager, {'project': str(project), 'revision': same['revision'], 'values': next_values,
        'apply_scope': 'selected_completed', 'selected_objects': [{'slide_id': 'slide-1', 'region_id': 'two'}]})
    assert union['pending']['selected_objects'] == selected + [{'slide_id': 'slide-1', 'region_id': 'two'}]


def test_noop_save_does_not_reopen_applied_settings_or_churn_revision(manager, tmp_path):
    assert settings.save(manager, {'revision': 0, 'values': pure.defaults()})['revision'] == 0
    assert manager.store.get(settings.GLOBAL_KEY) is None
    project = tmp_path / 'applied'
    settings.ensure_project(manager, project)
    values = {**pure.defaults(), 'text_layout': 'line'}
    saved = settings.save(manager, {'project': str(project), 'revision': 0, 'values': values})
    (project / 'workflow').mkdir(parents=True)
    applied = pure.snapshot(values, saved['revision'], 'project_snapshot')
    (project / 'workflow/state.json').write_text(json.dumps({'production_settings': applied}), encoding='utf-8')
    same = settings.save(manager, {'project': str(project), 'revision': saved['revision'], 'values': values})
    assert same['revision'] == saved['revision'] and same['pending'] is None
    assert settings.effective(manager, project)['applied'] == applied


def test_unsnapshotted_new_path_saves_visible_default_revision(manager, tmp_path):
    values = {**pure.defaults(), 'font_matching': 'precise'}
    global_row = settings.save(manager, {'revision': 0, 'values': values})
    project = tmp_path / 'not-created'
    read = settings.effective(manager, project)
    assert read['revision'] == global_row['revision'] == 1
    saved = settings.save(manager, {'project': str(project), 'revision': read['revision'], 'values': read['values']})
    assert saved['source'] == 'project_snapshot' and saved['revision'] == 1 and saved['pending'] is None
    settings.save(manager, {'revision': 1, 'values': pure.defaults()})
    assert settings.effective(manager, project)['values'] == values
