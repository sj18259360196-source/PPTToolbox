"""Synthetic end-to-end batch state/contract tests, no model or Office claims."""
import copy

import pytest
from PIL import Image, ImageDraw

from test_tools import ROOT
from test_workflow import ref, respond
from common import read_json, sha256
import workflow as wf
from workflow_store import load, WorkflowError


def begin_batch(tmp_path):
    project = tmp_path / 'project'
    wf.start(project, [ref(tmp_path)])
    # Historical layered-material/2 batch project, before material-quality/1.
    from common import write_json
    state = load(project)
    state.pop('material_quality_policy')
    write_json(project/'workflow/state.json', state)
    units = [{'id': name, 'region_id': 'art', 'owner_id': None,
              'semantic_role': 'page_content', 'input_form': 'raster',
              'requirement': 'Synthetic image replacement requirement',
              'evidence': 'Synthetic reference component', 'counterevidence': 'No internal editing requested',
              'required_edit': 'image_replace', 'content_type': 'complex_illustration',
              'material_route': 'reference_generate'} for name in ['mouse', 'flower']]
    respond(project, {'regions': [{'id': 'art', 'bbox': [0, 0, 640, 360], 'role': 'diagram',
                                  'summary': 'Synthetic independent replaceable icons'}],
                      'element_scope': {'version': 1, 'revision': 1,
                                        'task_requirement': 'Synthetic two independent image components',
                                        'units': units}})
    items = [{'id': name, 'purpose': 'Synthetic ' + name,
              'scope_unit_ids': [name], 'target_bbox_xywh': [10 + index*50, 10, 40, 40],
              'min_subject_pixels': [10, 10], 'generation_decision': {
                  'basis': 'content_category', 'reference': 'input/slide-001.png',
                  'reason': 'Complex illustration, whole-image replacement requested',
                  'content_type': 'complex_illustration', 'required_edit': 'image_replace'}}
             for index, name in enumerate(['mouse', 'flower'])]
    request = {'id': 'icons', 'purpose': 'Synthetic sheet', 'prompt': 'No real generation requested',
               'transparent': True, 'multi_icon_sheet': True, 'allowed_approximation': True,
               'scope_unit_ids': ['mouse', 'flower'], 'items': items}
    respond(project, {'action': 'request_asset', 'request': request})
    task = wf.next_task(project)
    assert task['task']['kind'] == 'asset_material'
    assert len(load(project)['asset_jobs']) == 1
    return project, request, task


def sheet(project, name='sheet.png', retry=False):
    path = project / name
    image = Image.new('RGBA', (100, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if retry:
        draw.ellipse((10, 10, 30, 30), fill='green')
    else:
        draw.rectangle((8, 8, 30, 30), fill='red')
        draw.rectangle((65, 12, 85, 33), fill='blue')
    image.save(path)
    return path


def response(task, image, rows):
    packet = read_json(task['task']['packet'])
    return {'task_id': packet['task_id'], 'token': packet['token'], 'result': {
        'file': str(image), 'tool_used': 'Pillow synthetic fixture', 'model_reported': None,
        'provenance': 'Deterministic synthetic fixture, no host generation',
        'sheet_sha256': sha256(image), 'items': [{**row, 'note': 'Synthetic crop-selection assertion only',
                                                'viewed_files': [str(image)]} for row in rows]}}


def first_rows():
    return [{'id': 'mouse', 'crop': [2, 2, 38, 38], 'status': 'accepted'},
            {'id': 'flower', 'crop': [55, 2, 40, 40], 'status': 'retry'}]


def test_one_sheet_partial_retry_retains_accepted_and_rejects_replay(tmp_path):
    project, request, task = begin_batch(tmp_path)
    first_response = response(task, sheet(project), first_rows())
    wf.submit(project, first_response)
    state = load(project)
    job = state['asset_jobs'][0]
    assert job['status'] == 'pending'
    assert set(job['accepted_items']) == {'mouse'}
    assert len(state['asset_catalog']) == 1
    original = project / state['asset_catalog'][0]['asset']
    original_hash = sha256(original)
    original_manifest = read_json(project / job['attempts'][0]['manifest']['file'])
    assert original_manifest['decision_scope'] == 'crop_selection_only'
    assert original_manifest['visual_review_status'] == 'not_run'
    assert original_manifest['sheet']['sha256'] == first_response['result']['sheet_sha256']
    retry_task = wf.next_task(project)
    retry_packet = read_json(retry_task['task']['packet'])
    assert retry_task['task']['kind'] == 'asset_material'
    assert retry_task['task']['id'] != task['task']['id']
    assert [i['id'] for i in retry_packet['context']['request']['items']] == ['flower']
    assert retry_packet['context']['request']['scope_unit_ids'] == ['flower']
    before = sha256(project / 'workflow/state.json')
    with pytest.raises(WorkflowError, match='Task ID/token'):
        wf.submit(project, first_response)
    assert sha256(project / 'workflow/state.json') == before
    retry_response = response(retry_task, sheet(project, 'retry.png', retry=True),
                              [{'id': 'flower', 'crop': [0, 0, 45, 45], 'status': 'accepted'}])
    wf.submit(project, retry_response)
    state = load(project)
    assert state['asset_jobs'][0]['status'] == 'completed'
    assert len(state['asset_jobs'][0]['attempts']) == 2
    assert {row['item_id'] for row in state['asset_catalog']} == {'mouse', 'flower'}
    assert sha256(original) == original_hash
    assert state['asset_catalog'][0]['visual_review_status'] == 'not_run'
    assert wf.next_task(project)['task']['kind'] == 'region_objects'


def test_invalid_hash_crop_and_missing_items_preserve_state_and_task(tmp_path):
    project, request, task = begin_batch(tmp_path)
    source = sheet(project)
    valid = response(task, source, first_rows())
    state_hash = sha256(project / 'workflow/state.json')
    for change in ['hash', 'crop', 'missing', 'accepted_id_unknown', 'token']:
        invalid = copy.deepcopy(valid)
        if change == 'hash': invalid['result']['sheet_sha256'] = '0' * 64
        if change == 'crop': invalid['result']['items'][0]['crop'] = [95, 0, 20, 30]
        if change == 'missing': invalid['result']['items'].pop()
        if change == 'accepted_id_unknown': invalid['result']['items'][0]['id'] = 'other'
        if change == 'token': invalid['token'] = 'invalid'
        if change == 'token':
            with pytest.raises(WorkflowError, match='identity changed'):
                wf.validate_response(project, invalid)
        else:
            checked = wf.validate_response(project, invalid)
            assert checked['valid'] is False
            assert checked['task_consumed'] is False
        with pytest.raises(WorkflowError): wf.submit(project, invalid)
        assert sha256(project / 'workflow/state.json') == state_hash
        assert not (project / 'assets/batches').exists()
        assert load(project)['active_task']['id'] == task['task']['id']
        assert load(project)['asset_jobs'][0].get('accepted_items', {}) == {}
    wf.submit(project, valid)
    retry_task = wf.next_task(project)
    invalid_retry = response(retry_task, source, first_rows())
    state_hash = sha256(project / 'workflow/state.json')
    with pytest.raises(WorkflowError): wf.submit(project, invalid_retry)
    assert sha256(project / 'workflow/state.json') == state_hash
    assert len(load(project)['asset_catalog']) == 1


def test_content_category_route_without_drawing_builds_regional_images(tmp_path):
    project, request, task = begin_batch(tmp_path)
    rows = first_rows()
    rows[1]['status'] = 'accepted'
    wf.submit(project, response(task, sheet(project), rows))
    task = wf.next_task(project)
    state = load(project)
    catalog = {a['item_id']: a for a in state['asset_catalog']}
    objects = []
    for index, name in enumerate(['mouse', 'flower']):
        asset = catalog[name]
        assert 'drawing' not in asset['generation_decision']
        assert 'similarity_pct' not in asset['generation_decision']
        objects.append({'id': name, 'kind': 'image', 'bbox': [20 + index*100, 20, 70, 70],
                        'asset': asset['asset'], 'fit': 'stretch', 'asset_role': 'icon',
                        'source_kind': 'generated', 'provenance': asset['provenance'],
                        'raster_content': 'generated_illustration',
                        'raster_reason': 'Synthetic replaceable generated illustration',
                        'generation_decision': asset['generation_decision']})
    respond(project, {'objects': objects, 'source_notes': 'Synthetic content-category assembly',
                      'scope_bindings': [{'unit_id': name, 'object_ids': [name]} for name in catalog],
                      'asset_decisions': [{'target_id': name, 'route': 'generated', 'generation_considered': True,
                                           'reason': 'Content-category generation with whole-image replacement',
                                           'remaining_risk': 'Synthetic only; visual review remains required'}
                                          for name in catalog]}, task)
    next_task = wf.next_task(project)
    assert next_task['task']['kind'] == 'source_review'
    fragment = load(project)['pages'][0]['fragments']['art']
    assert len(fragment['objects']) == 2
    assert all(o['editability'] == 'image_replace' for o in fragment['objects'])


def test_generated_catalog_identity_cannot_be_relabelled(tmp_path):
    project, request, task = begin_batch(tmp_path)
    rows=first_rows();rows[1]['status']='accepted'
    wf.submit(project,response(task,sheet(project),rows))
    state=load(project)
    asset=state['asset_catalog'][0]
    obj={'id':'mouse','kind':'image','asset':asset['asset'],'source_kind':'crop'}
    for source_kind,decision in [('crop',asset['generation_decision']),('generated',{'basis':'user_request'})]:
        obj.update(source_kind=source_kind,generation_decision=decision)
        with pytest.raises(ValueError,match='retain its accepted'):
            wf._track_assets(project,copy.deepcopy(state),[obj])


def test_batch_interruption_after_result_write_recovers_identical_only(tmp_path, monkeypatch):
    project, request, task = begin_batch(tmp_path)
    rows = first_rows()
    rows[1]['status'] = 'accepted'
    submitted = response(task, sheet(project), rows)
    before_state = load(project)
    before_hash = sha256(project / 'workflow/state.json')
    save = wf.save
    def interrupted_save(*args, **kwargs):
        raise RuntimeError('Simulated interruption before workflow state commit')
    monkeypatch.setattr(wf, 'save', interrupted_save)
    with pytest.raises(RuntimeError, match='Simulated interruption'):
        wf.submit(project, submitted)
    monkeypatch.setattr(wf, 'save', save)
    assert sha256(project / 'workflow/state.json') == before_hash
    dest = project / 'assets/batches' / task['task']['id']
    published = {p.relative_to(dest).as_posix(): sha256(p) for p in dest.rglob('*') if p.is_file()}
    assert 'sheet.png' in published and 'batch-manifest.json' in published
    record = project / 'workflow/results' / (task['task']['id'] + '.json')
    assert record.is_file()
    record_hash = sha256(record)
    changed = copy.deepcopy(submitted)
    changed['result']['items'][0]['note'] = 'Different crop decision'
    with pytest.raises(WorkflowError): wf.submit(project, changed)
    assert sha256(project / 'workflow/state.json') == before_hash
    assert {p.relative_to(dest).as_posix(): sha256(p) for p in dest.rglob('*') if p.is_file()} == published
    assert sha256(record) == record_hash
    wf.submit(project, submitted)
    state = load(project)
    assert state['asset_jobs'][0]['status'] == 'completed'
    assert len(state['asset_catalog']) == 2
    assert len(state['accepted']) == len(before_state['accepted']) + 1
    assert len(state['asset_jobs'][0]['attempts']) == 1
    assert sha256(record) == record_hash
    assert {p.relative_to(dest).as_posix(): sha256(p) for p in dest.rglob('*') if p.is_file()} == published
    assert wf.next_task(project)['task']['kind'] == 'region_objects'
