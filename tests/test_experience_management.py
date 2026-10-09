import copy
from pathlib import Path
import pytest
from scripts.experience_library import load_library, audit, show
from scripts.experience_management import call, export_library, revision

ROOT = Path(__file__).resolve().parents[1]


def token(external):
    s, r, _ = load_library(ROOT, external)
    return revision(s, r)


def test_export_repeat_import_is_idempotent(tmp_path):
    data = export_library(ROOT, tmp_path, ['EXP-001'])
    preview = call(ROOT, tmp_path, 'import-preview', {'payload': data})
    assert preview['duplicate_count'] == 1 and preview['new_count'] == 0
    result = call(ROOT, tmp_path, 'import', {'payload': data, 'revision': preview['revision']})
    assert result['status'] == 'unchanged'
    assert audit(ROOT, external_root=tmp_path)['status'] == 'passed'


def test_collision_import_edit_merge_undo_and_roundtrip(tmp_path):
    data = export_library(ROOT, tmp_path, ['EXP-001'])
    data['entries'][0]['title'] += ' 修改版'
    preview = call(ROOT, tmp_path, 'import-preview', {'payload': data})
    assert preview['new_count'] == 1
    rid = preview['items'][0]['id']
    assert rid != 'EXP-001'
    call(ROOT, tmp_path, 'import', {'payload': data, 'revision': preview['revision']})
    assert call(ROOT, tmp_path, 'import-preview', {'payload': data})['duplicate_count'] == 1
    before = token(tmp_path)
    call(ROOT, tmp_path, 'edit', {'id': rid, 'revision': before, 'changes': {'title': '修改优化测试'}})
    assert show(rid, ROOT, tmp_path)['title'] == '修改优化测试'
    with pytest.raises(ValueError, match='已更新'):
        call(ROOT, tmp_path, 'edit', {'id': rid, 'revision': before, 'changes': {'title': '覆盖'}})
    call(ROOT, tmp_path, 'merge', {'keep': 'EXP-001', 'remove': rid, 'revision': token(tmp_path)})
    assert rid not in {r['id'] for r in load_library(ROOT, tmp_path)[1]}
    history = call(ROOT, tmp_path, 'history', {})
    call(ROOT, tmp_path, 'undo', {'history_id': history['items'][0]['id'], 'revision': history['revision']})
    assert show(rid, ROOT, tmp_path)['title'] == '修改优化测试'
    assert audit(ROOT, external_root=tmp_path)['status'] == 'passed'
    exported = export_library(ROOT, tmp_path, [rid])
    other = tmp_path/'other'
    p = call(ROOT, other, 'import-preview', {'payload': exported})
    call(ROOT, other, 'import', {'payload': exported, 'revision': p['revision']})
    assert show(p['items'][0]['id'], ROOT, other)['title'] == '修改优化测试'


@pytest.mark.parametrize('damage', ['hash', 'excerpt', 'tool', 'validation', 'duplicate_id'])
def test_invalid_import_has_no_persistent_effect(tmp_path, damage):
    data = export_library(ROOT, tmp_path, ['EXP-001'])
    if damage == 'hash': data['sources'][0]['metadata']['sha256'] = '0'*64
    if damage == 'excerpt': data['entries'][0]['evidence'][0]['excerpt'] = 'fabricated'
    if damage == 'tool': data['entries'][0]['tools'] = ['shell.execute']
    if damage == 'validation': data['entries'][0]['runtime_retested_in_this_delivery'] = True
    if damage == 'duplicate_id': data['entries'].append(copy.deepcopy(data['entries'][0]))
    with pytest.raises(ValueError):
        call(ROOT, tmp_path, 'import', {'payload': data, 'revision': token(tmp_path)})
    assert not list(tmp_path.iterdir())


def test_edit_cannot_change_provenance(tmp_path):
    with pytest.raises(ValueError, match='原文出处'):
        call(ROOT, tmp_path, 'edit', {'id': 'EXP-001', 'revision': token(tmp_path), 'changes': {'evidence': []}})
    assert show('EXP-001', ROOT, tmp_path)['evidence']


def test_new_source_collision_and_duplicate_evidence_preserved(tmp_path):
    import base64
    import hashlib
    data = export_library(ROOT, tmp_path, ['EXP-001'])
    raw = '独立归档原文\n第二行\n'.encode('utf-8')
    # Deliberately collide with an existing source ID and include an unsafe input path.
    data['sources'] = [{'metadata': {'source_id': 'S01', 'sha256': hashlib.sha256(raw).hexdigest(),
                        'byte_count': len(raw), 'line_count': 2, 'topic': '独立来源',
                        'relative_path': '../../outside'}, 'content_base64': base64.b64encode(raw).decode()}]
    data['entries'][0]['evidence'] = [{'source_id': 'S01', 'line_start': 1, 'line_end': 1,
                                      'excerpt': '独立归档原文', 'reported_state': 'recorded_constraint'}]
    plan = call(ROOT, tmp_path, 'import-preview', {'payload': data})
    assert plan['duplicate_count'] == 1 and plan['evidence_update_count'] == 1
    call(ROOT, tmp_path, 'import', {'payload': data, 'revision': plan['revision']})
    row = show('EXP-001', ROOT, tmp_path)
    assert len(row['sources']) == 3 and row['sources'][-1]['source_id'] != 'S01'
    assert Path(row['sources'][-1]['file']).is_relative_to(tmp_path/'managed-assets')
    assert audit(ROOT, external_root=tmp_path)['status'] == 'passed'
    assert call(ROOT, tmp_path, 'import-preview', {'payload': data})['evidence_update_count'] == 0


def test_http_write_auth_and_read_method_boundary(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    import json
    from toolbox_manager.server import LocalServer
    server = LocalServer(tmp_path/'http-manager', root=ROOT, token='fixture-only')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        headers = {'Content-Type': 'application/json', 'Origin': server.origin}
        payload = json.dumps({'ids': ['EXP-001']}).encode()
        request = urllib.request.Request(server.origin+'/api/experience.export', payload, headers)
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 401
        headers['Authorization'] = 'Bearer fixture-only'
        request = urllib.request.Request(server.origin+'/api/experience.export', payload, headers)
        response = json.load(urllib.request.urlopen(request))
        assert response['result']['entries'][0]['id'] == 'EXP-001'
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(server.origin+'/api/experience.edit', headers=headers))
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
