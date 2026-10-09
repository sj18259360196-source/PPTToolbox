"""Real managed worker/stdio fixtures; no Office or visual acceptance claims."""
import hashlib
import json

import pytest

from test_managed_rebuild import runtime, begin, invoke, plan, rpc, rpc_process, ROOT, declare
from toolbox_manager.contracts import validate
from toolbox_manager.payload_transport import (
    MCP_INLINE_BYTES, RESULT_FILE_BYTES, PayloadTooLarge, read_json_file,
    oversized_rpc, encode_worker,
)


def write_result(project, payload):
    path = project / 'large-result.json'
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    path.write_bytes(raw)
    return {'result_file': str(path), 'result_sha256': hashlib.sha256(raw).hexdigest()}


def identity(task):
    return {k: task[k] for k in ('task_id', 'token', 'base_revision')}


@pytest.mark.parametrize('source', ['file_mcp', 'cli', 'inline_service'])
def test_large_result_reaches_real_worker_once(runtime, source, monkeypatch):
    monkeypatch.setenv('PPT_TOOLBOX_CONNECTION_PROBE', '1')
    m, p, _ = begin(runtime)
    next_result = invoke(m, 'next', p)
    task = next_result['task']
    assert next_result['submission_transport']['preferred_for_geometry'] == 'result_file'
    payload = plan()
    payload['regions'][0]['summary'] = '测试' * 300000
    assert len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > 1700000
    before = (p / 'workflow/state.json').read_bytes()
    args = identity(task)
    if source == 'file_mcp':
        refs = write_result(p, payload)
        # Preflight uses the identical file route and must not consume the task.
        preflight = invoke(m, 'validate_response', p, **args, **refs)
        assert preflight['command_status'] == 'completed', preflight
        assert (p / 'workflow/state.json').read_bytes() == before
        rows = rpc_process(m, [rpc('initialize'), rpc('tools/call', 19,
            name='rebuild_submit', arguments={'project': str(p), **args, **refs})])
        result = rows[-1]['result']['structuredContent']
    elif source == 'cli':
        response = p / 'cli-response.json'
        response.write_text(json.dumps({'task_id': task['task_id'], 'token': task['token'],
            'result': payload}, ensure_ascii=False), encoding='utf-8')
        result = m.execute('workflow.submit', ['--project', str(p), '--response', str(response)])
    else:
        result = invoke(m, 'submit', p, **args, result=payload)
    assert result['command_status'] == 'completed', result
    state = json.loads((p / 'workflow/state.json').read_text(encoding='utf-8'))
    assert len(state['accepted']) == 1
    repeat = invoke(m, 'submit', p, **args, **write_result(p, payload))
    assert repeat['command_status'] != 'completed'
    assert len(json.loads((p / 'workflow/state.json').read_text(encoding='utf-8'))['accepted']) == 1


def test_stdio_oversize_is_correlated_logged_and_not_dispatched(runtime, monkeypatch):
    monkeypatch.setenv('PPT_TOOLBOX_CONNECTION_PROBE', '1')
    m, p, _ = begin(runtime)
    task = invoke(m, 'next', p)['task']
    before = (p / 'workflow/state.json').read_bytes()
    payload = plan(); payload['regions'][0]['summary'] = '图' * 600000
    rows = rpc_process(m, [rpc('initialize'), rpc('tools/call', 77,
        name='rebuild_submit', arguments={'project': str(p), **identity(task), 'result': payload}),
        rpc('ping', 78)])
    rejection = next(r for r in rows if r.get('id') == 77)
    assert rejection['error']['data']['dispatched'] is False
    assert rejection['error']['data']['code'] == 'payload_too_large'
    assert 'result_file' in rejection['error']['data']['next_action']
    assert any(r.get('id') == 78 and 'result' in r for r in rows)
    assert (p / 'workflow/state.json').read_bytes() == before
    with m.store.db() as db:
        audit = db.execute("SELECT details FROM events WHERE action='activity.finished' ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(audit['details'])['error_code'] == 'payload_too_large'
    from toolbox_manager.project_hub import observe
    key = next(k for k, row in m.store.get('workbench_projects', {}).items() if row['path'] == str(p))
    state = observe(m, key)
    assert any(i['error_code'] == 'payload_too_large' and i['state'] == 'open'
               for i in state['activity']['issues'])
    result = invoke(m, 'submit', p, **identity(task), **write_result(p, payload))
    assert result['command_status'] == 'completed', result
    state = observe(m, key)
    assert any(i['error_code'] == 'payload_too_large' and i['state'] == 'resolved'
               for i in state['activity']['issues'])


@pytest.mark.parametrize('fault', ['hash', 'outside', 'missing', 'invalid_result', 'stale_token', 'stale_revision', 'disabled'])
def test_file_route_preserves_guards(runtime, tmp_path, fault):
    m, p, _ = begin(runtime)
    task = invoke(m, 'next', p)['task']
    args = identity(task)
    refs = write_result(p, plan())
    if fault == 'hash': refs['result_sha256'] = '0' * 64
    if fault == 'outside':
        path = tmp_path / 'outside.json'; path.write_text('{}', encoding='utf-8')
        refs['result_file'] = str(path)
    if fault == 'missing': refs['result_file'] = str(p / 'missing.json')
    if fault == 'invalid_result': refs = write_result(p, {'wrong_field': True})
    if fault == 'stale_token': args['token'] = 'stale'
    if fault == 'stale_revision': args['base_revision'] = 99999
    if fault == 'disabled': m.toggle('tool', 'workflow.submit', False)
    before = (p / 'workflow/state.json').read_bytes()
    result = invoke(m, 'submit', p, **args, **refs)
    assert result['command_status'] != 'completed', result
    assert (p / 'workflow/state.json').read_bytes() == before


def test_bounds_and_mutual_exclusion(tmp_path, monkeypatch):
    line = json.dumps(rpc('tools/call', 5, arguments={'value': '图' * 400000}), ensure_ascii=False)
    assert len(line) < MCP_INLINE_BYTES
    assert oversized_rpc(line)['id'] == 5  # Count bytes, not characters.
    assert 'rebuild_submit' not in oversized_rpc(line)['error']['data']['next_action']
    path = tmp_path / 'large.json'; path.write_bytes(b' ' * (RESULT_FILE_BYTES + 1))
    with pytest.raises(PayloadTooLarge): read_json_file(path)
    from toolbox_manager import payload_transport
    monkeypatch.setattr(payload_transport, 'WORKER_BYTES', 100)
    with pytest.raises(PayloadTooLarge): encode_worker({'v': '图' * 100})
    base = {'project': 'p', 'task_id': 't', 'token': 's'}
    for extra in ({'result_file': 'f'}, {'result': plan(), 'result_file': 'f', 'result_sha256': '0' * 64},
                  {'result': plan(), 'result_sha256': '0' * 64}):
        with pytest.raises(ValueError): validate('submit', {**base, **extra}, ROOT)


def test_large_native_path_preserves_all_coordinates(runtime):
    m, p, _ = begin(runtime)
    task = invoke(m, 'next', p)['task']
    assert invoke(m, 'submit', p, **identity(task), result=plan())['command_status'] == 'completed'
    declare(m, p, 'production')
    task = invoke(m, 'next', p)['task']
    assert task['kind'] == 'region_objects'
    commands = [['M', 10, 10]] + [
        ['C', 100.12345678901234, 110.12345678901234, 120.12345678901234,
         130.12345678901234, 140.12345678901234, 150.12345678901234]
        for _ in range(16000)] + [['Z']]
    payload = {'objects': [{'id': 'map-outline', 'kind': 'path',
                           'commands': commands, 'style': {'fill': '4488AA'}}],
               'source_notes': 'Synthetic large native path transport; not map accuracy or visual acceptance'}
    refs = write_result(p, payload)
    assert (p / 'large-result.json').stat().st_size > 1700000
    result = invoke(m, 'submit', p, **identity(task), **refs)
    assert result['command_status'] == 'completed', result
    state = json.loads((p / 'workflow/state.json').read_text(encoding='utf-8'))
    record = json.loads((p / state['accepted'][-1]['file']).read_text(encoding='utf-8'))
    assert record['result']['objects'][0]['commands'] == commands
