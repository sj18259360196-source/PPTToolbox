"""Real isolated registered subprocess calls, synthetic sheets, no host model."""
import copy
import json

import pytest

from test_tools import ROOT
from test_layered_material_workflow import begin_batch, sheet, first_rows, response
from toolbox_manager.service import Manager
from toolbox_manager.policy import PolicyDenied
from common import read_json, write_json, sha256
import workflow as wf


def setup(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    project, request, task = begin_batch(work)
    manager = Manager(tmp_path / 'manager', root=ROOT, home=tmp_path / 'home')
    manager.authorize_project(project, [work])
    manager.save_settings({'revision':manager.settings()['revision'], 'values':{'agent_execution_enabled':True}})
    return manager, project, task


def execute(manager, project, tool, **options):
    args = ['--project', str(project)]
    for key, value in options.items():
        args.extend(['--' + key, str(value)])
    return manager.execute(tool, args)


def ingress_files(project, task):
    image = sheet(project)
    result = response(task, image, first_rows())['result']
    producer = project / 'producer.json'
    crops = project / 'crops.json'
    write_json(producer, {k:result[k] for k in ('tool_used','model_reported','provenance')})
    write_json(crops, {k:result[k] for k in ('sheet_sha256','items')})
    return image, producer, crops


def test_actual_managed_registered_batch_prepare_and_ingest_are_read_only(tmp_path):
    manager, project, task = setup(tmp_path)
    state_hash = sha256(project / 'workflow/state.json')
    prepared = execute(manager, project, 'ops.generation-prepare', outdir='handoff')
    assert prepared['command_status'] == 'completed', prepared
    handoff = project / 'handoff/generation-request.json'
    request = read_json(handoff)
    assert len(request['items']) == 2
    assert request['task_id'] == task['task']['id']
    assert sha256(project / 'workflow/state.json') == state_hash
    image, producer, crops = ingress_files(project, task)
    ingested = execute(manager, project, 'ops.generation-ingest', request=handoff,
                       image=image, producer=producer, crops=crops, outdir='ingress')
    assert ingested['command_status'] == 'completed', ingested
    response_file = read_json(project / 'ingress/response.json')
    packet = read_json(task['task']['packet'])
    assert response_file['task_id'] == packet['task_id']
    assert response_file['token'] == packet['token']
    assert [i['id'] for i in response_file['result']['items']] == ['mouse','flower']
    assert sha256(project / 'workflow/state.json') == state_hash
    assert not (project / 'assets/batches').exists()
    poisoned = copy.deepcopy(request)
    poisoned['reference_files'].append({'file':str(tmp_path / 'must-not-be-read-missing.png'), 'sha256':'0'*64})
    write_json(project / 'poisoned-handoff.json', poisoned)
    rejected = execute(manager, project, 'ops.generation-ingest', request=project/'poisoned-handoff.json',
                       image=image, producer=producer, crops=crops, outdir='poisoned-output')
    assert rejected['command_status'] == 'tool_failed'
    assert 'unrelated references' in json.loads(rejected['stdout'])['error']
    assert not (project / 'poisoned-output').exists()
    assert sha256(project / 'workflow/state.json') == state_hash


def test_disabled_and_escaped_managed_handoff_are_rejected_before_writes(tmp_path):
    manager, project, task = setup(tmp_path)
    before = sha256(project / 'workflow/state.json')
    manager.save_settings({'revision':manager.settings()['revision'], 'values':{'agent_execution_enabled':False}})
    with pytest.raises(ValueError): execute(manager, project, 'ops.generation-prepare', outdir='disabled-exec')
    manager.save_settings({'revision':manager.settings()['revision'], 'values':{'agent_execution_enabled':True}})
    manager.toggle('tool','ops.generation-prepare',False)
    with pytest.raises(ValueError): execute(manager, project, 'ops.generation-prepare', outdir='disabled-tool')
    manager.toggle('tool','ops.generation-prepare',True)
    assert execute(manager,project,'ops.generation-prepare',outdir='handoff')['command_status'] == 'completed'
    image, producer, crops = ingress_files(project, task)
    escaped = tmp_path / 'escaped-crops.json'
    write_json(escaped, read_json(crops))
    with pytest.raises(PolicyDenied, match='outside'):
        execute(manager, project, 'ops.generation-ingest', request=project/'handoff/generation-request.json',
                image=image, producer=producer, crops=escaped, outdir='escaped-output')
    with pytest.raises(PolicyDenied, match='match'):
        manager.execute('ops.generation-prepare', ['--project',str(project),'--project',str(tmp_path/'different'),
                                                  '--outdir',str(project/'different-project-output')])
    with pytest.raises(ValueError, match='arguments'):
        manager.execute('ops.generation-prepare', ['--project',str(project),'--out',str(project/'abbreviated')])
    assert sha256(project / 'workflow/state.json') == before
    for folder in ('disabled-exec','disabled-tool','escaped-output','different-project-output','abbreviated'):
        assert not (project/folder).exists()


def test_managed_prepare_does_not_issue_task_when_none_is_active(tmp_path):
    manager, project, task = setup(tmp_path)
    rows = first_rows()
    rows[1]['status'] = 'accepted'
    wf.submit(project, response(task, sheet(project), rows))
    before = sha256(project / 'workflow/state.json')
    result = execute(manager, project, 'ops.generation-prepare', outdir='must-not-issue')
    assert result['command_status'] == 'tool_failed'
    assert 'rebuild_next' in json.loads(result['stdout'])['error']
    assert sha256(project / 'workflow/state.json') == before
    assert not (project / 'must-not-issue').exists()
