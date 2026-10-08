"""Paired synthetic scope fixtures, not visual recognition or real Office acceptance."""
import copy
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from test_tools import ROOT
import workflow as wf
from common import read_json, write_json, sha256
from element_scope import (validate_plan, validate_outputs, native_digest,
                           compiled_scope, validate_review, SCOPE, COMPILED_SCOPE)
from workflow_scene import valid_plan, assemble
from workflow_store import load, WorkflowError
from test_workflow import ref, respond, assertion, region_payload
from test_managed_rebuild import runtime


def unit(need='text', **patch):
    return {'id': 'body', 'region_id': 'one', 'owner_id': None,
            'semantic_role': 'page_content', 'input_form': 'raster',
            'requirement': 'TEST explicit edit request', 'evidence': 'TEST source content',
            'counterevidence': 'TEST none found after source inspection', 'required_edit': need, **patch}


def scope(*units):
    return {'version': 1, 'revision': 1, 'task_requirement': 'TEST user task', 'units': list(units or [unit()])}


def plan(contract):
    return {'regions': [{'id': 'one', 'bbox': [0, 0, 640, 360], 'role': 'content',
                          'summary': 'TEST page content and cited artifact'}], 'element_scope': contract}


def begin(tmp_path, contract=None):
    p = tmp_path/'project'
    wf.start(p, [ref(tmp_path)])
    if contract is not None: respond(p, plan(contract))
    return p


def payload():
    return {**region_payload(), 'scope_bindings': [{'unit_id': 'body', 'object_ids': ['label']}]}


def review(p):
    t = wf.next_task(p)
    result = assertion(t)
    contract = compiled_scope(load(p)['pages'][0])
    result['scope_review'] = {'revision': contract['revision'], 'units': [
        {'unit_id': u['id'], 'status': 'passed', 'note': 'TEST independent source observation'}
        for u in contract['units']]}
    result['text_checks'] = [{'object_id': 'slide-001.one.label', 'source_text': 'TEST'}]
    return t, result


def poster(p):
    asset = 'input/slide-001.png'
    return unit('preserve', id='poster', semantic_role='reference_artifact',
                source={'asset': asset, 'sha256': sha256(p/asset)})


def image_payload():
    return {'objects': [{'id': 'poster', 'kind': 'image', 'bbox': [300, 30, 300, 169],
                         'asset': 'input/slide-001.png', 'source_kind': 'user',
                         'asset_role': 'decoration', 'raster_content': 'reference_artifact',
                         'fit': 'stretch', 'raster_reason': 'TEST preserve cited source artwork unchanged'}],
            'source_notes': 'TEST source citation',
            'scope_bindings': [{'unit_id': 'poster', 'object_ids': ['poster']}],
            'asset_decisions': [{'target_id': 'poster', 'route': 'user_asset',
                                 'generation_considered': False, 'reason': 'TEST source citation',
                                 'remaining_risk': 'TEST visual review still required'}]}


def test_poster_and_explanation_build_preserves_source_and_editable_text(tmp_path):
    p = begin(tmp_path)
    respond(p, plan(scope(unit(), poster(p))))
    data = image_payload()
    body = payload()
    for field in ('objects', 'scope_bindings'): data[field] += body[field]
    respond(p, data)
    task, result = review(p)
    assert read_json(task['task']['packet'])['context']['element_scope']['units'][1]['required_edit'] == 'preserve'
    respond(p, result, task)
    task = wf.next_task(p)
    assert task['task']['kind'] == 'office_render'
    state = load(p)
    scene = read_json(p/state['run']['dir']/'scene.json')
    assert scene['slides'][0]['element_scope']['bindings'][0]['unit_id'] == 'poster'
    with ZipFile(p/state['run']['candidate']['file']) as z:
        xml = z.read('ppt/slides/slide1.xml')
        assert b'<p:pic>' in xml and b'TEST' in xml
        assert (p/'input/slide-001.png').read_bytes() in [z.read(n) for n in z.namelist() if n.startswith('ppt/media/')]


@pytest.mark.parametrize('change', ['split', 'crop', 'generated', 'mask', 'unassigned', 'bytes'])
def test_preserved_poster_cannot_be_destructively_rebuilt(tmp_path, change):
    p = begin(tmp_path)
    respond(p, plan(scope(poster(p))))
    data = image_payload()
    if change == 'split':
        data['objects'] += payload()['objects']
        data['scope_bindings'][0]['object_ids'].append('label')
    if change == 'crop': data['objects'][0]['source_crop'] = [0, 0, 100, 100]
    if change == 'generated': data['objects'][0]['source_kind'] = 'generated'
    if change == 'mask': data['objects'][0]['mask'] = 'ellipse'
    if change == 'unassigned': data['objects'] += payload()['objects']
    if change == 'bytes':
        Image.new('RGB', (640, 360), 'red').save(p/'assets/changed.png')
        data['objects'][0]['asset'] = 'assets/changed.png'
    task = wf.next_task(p)
    before = sha256(p/'workflow/state.json')
    with pytest.raises(WorkflowError, match='element_scope'): respond(p, data, task)
    assert sha256(p/'workflow/state.json') == before


@pytest.mark.parametrize('role', ['page_content', 'reference_artifact'])
def test_same_raster_requires_text_when_user_requests_text(tmp_path, role):
    p = begin(tmp_path)
    u = poster(p)
    u.update(required_edit='text', semantic_role=role)
    respond(p, plan(scope(u)))
    with pytest.raises(WorkflowError, match='capability missing'): respond(p, image_payload())
    data = payload()
    data['scope_bindings'][0]['unit_id'] = 'poster'
    respond(p, data)


@pytest.mark.parametrize('change', ['missing', 'stale', 'failed', 'transcription', 'unknown'])
def test_scope_review_cannot_hide_incomplete_obligations(tmp_path, change):
    p = begin(tmp_path, scope(unit('unresolved' if change == 'unknown' else 'text')))
    respond(p, payload())
    task, result = review(p)
    if change == 'missing': result.pop('scope_review')
    if change == 'stale': result['scope_review']['revision'] = 2
    if change == 'failed': result['scope_review']['units'][0]['status'] = 'blocked'
    if change == 'transcription': result.pop('text_checks')
    with pytest.raises(WorkflowError, match='element_scope'): respond(p, result, task)
    assert load(p)['pages'][0]['source_review'] is None
    if change in {'failed', 'unknown'}:
        result['status'] = 'blocked'
        respond(p, result, task)
        assert load(p)['pages'][0]['source_review']['status'] == 'blocked'


def test_preserved_native_content_stays_native_and_unchanged(tmp_path):
    obj = {**payload()['objects'][0], 'editability': 'text'}
    u = unit('preserve', input_form='native', semantic_role='reference_artifact',
             native_sha256=native_digest([obj]))
    p = begin(tmp_path, scope(u))
    data = payload()
    bad = copy.deepcopy(data)
    bad['objects'][0]['text'] = 'altered'
    with pytest.raises(WorkflowError, match='native source changed'): respond(p, bad)
    respond(p, data)
    assert assemble(load(p))['slides'][0]['objects'][0]['kind'] == 'text'


def test_scope_revision_is_retained_and_cannot_be_dropped(tmp_path):
    p = begin(tmp_path, scope())
    respond(p, payload())
    wf.revise(p, 'slide-001', None, 'TEST new source evidence')
    task = wf.next_task(p)
    assert read_json(task['task']['packet'])['context']['previous_element_scope']['revision'] == 1
    for candidate in (plan(scope()), {'regions': plan(scope())['regions']}):
        with pytest.raises(WorkflowError, match='increased revision'): respond(p, candidate, task)
    contract = scope(); contract['revision'] = 2
    respond(p, plan(contract), task)
    respond(p, payload())
    task, result = review(p)
    assert result['scope_review']['revision'] == 2
    respond(p, result, task)


def test_regional_revision_keeps_bindings_and_rechecks_scope(tmp_path):
    p = begin(tmp_path, scope())
    respond(p, payload())
    task, result = review(p); respond(p, result, task)
    wf.revise(p, 'slide-001', 'one', 'TEST correct transcription')
    task = wf.next_task(p)
    changed = payload()['objects'][0]; changed['text'] = 'CORRECT'
    respond(p, {'action': 'revise_objects', 'base_fragment_sha256': read_json(task['task']['packet'])['context']['previous_fragment_sha256'],
                'reason': 'TEST corrected source reading', 'objects': [changed]}, task)
    assert load(p)['pages'][0]['source_review'] is None
    assert compiled_scope(load(p)['pages'][0])['revision'] == 1


def test_scene_replacement_cannot_drop_scope(tmp_path):
    p = begin(tmp_path, scope())
    respond(p, payload())
    scene = assemble(load(p)); scene['slides'][0].pop('element_scope')
    write_json(p/'replacement.json', scene)
    with pytest.raises(ValueError, match='retain scope'): wf.replace_scene(p, p/'replacement.json', 'TEST attempt')


def test_generation_cannot_target_preserved_or_unknown_content(tmp_path):
    p = begin(tmp_path)
    respond(p, plan(scope(poster(p))))
    request = {'id': 'art', 'purpose': 'TEST', 'prompt': 'TEST', 'transparent': True,
               'allowed_approximation': True, 'scope_unit_ids': ['poster']}
    with pytest.raises(WorkflowError, match='cannot be regenerated'):
        respond(p, {'action': 'request_asset', 'request': request})
    assert not load(p)['asset_jobs']


@pytest.mark.parametrize('change', ['duplicate', 'owner', 'cycle', 'region'])
def test_plan_rejects_inconsistent_ownership(change):
    value = scope()
    if change == 'duplicate': value['units'] *= 2
    if change == 'owner': value['units'][0]['owner_id'] = 'missing'
    if change == 'cycle': value['units'][0]['owner_id'] = 'body'
    if change == 'region': value['units'][0]['region_id'] = 'missing'
    with pytest.raises(ValueError, match='element_scope'): valid_plan(plan(value), [640, 360])


def test_scene_and_tool_contracts_share_same_schema():
    from toolbox_manager.contracts import result_contracts
    root = Path(__file__).resolve().parents[1]
    contracts, _ = result_contracts(root)
    scene = read_json(root/'assets/schemas/scene.schema.json')
    assert contracts['page_plan']['properties']['element_scope'] == SCOPE
    assert scene['properties']['slides']['items']['properties']['element_scope'] == COMPILED_SCOPE


def test_group_and_nested_semantic_units_keep_independent_editability(tmp_path):
    contract = scope(unit('group', id='card', input_form='native'), unit(owner_id='card'))
    p = begin(tmp_path, contract)
    data = payload()
    data['objects'] = [{'id': 'card', 'kind': 'group', 'children': data['objects']}]
    data['scope_bindings'].insert(0, {'unit_id': 'card', 'object_ids': ['card']})
    respond(p, data)
    task, result = review(p)
    respond(p, result, task)
    assert wf.next_task(p)['task']['kind'] == 'office_render'


def test_unrelated_units_cannot_claim_same_text(tmp_path):
    p = begin(tmp_path, scope(unit(), unit(id='other')))
    data = payload()
    data['scope_bindings'].append({'unit_id': 'other', 'object_ids': ['label']})
    with pytest.raises(WorkflowError, match='overlapping ownership'): respond(p, data)


def test_partial_explicit_edit_preserves_other_units_and_layer_order(tmp_path):
    p = begin(tmp_path)
    respond(p, plan(scope(poster(p), unit())))
    data = image_payload(); data['objects'] += payload()['objects']
    data['scope_bindings'] += payload()['scope_bindings']
    data['draw_order'] = ['poster', 'label']
    respond(p, data)
    objects = assemble(load(p))['slides'][0]['objects']
    assert [o['kind'] for o in objects] == ['image', 'text']
    assert objects[0]['asset'] == 'input/slide-001.png'


def test_scoped_crop_uses_xywh_and_retains_original_asset(tmp_path):
    p = begin(tmp_path)
    u = poster(p); u['source']['crop'] = [200, 100, 300, 200]
    respond(p, plan(scope(u)))
    data = image_payload(); data['objects'][0]['source_crop'] = u['source']['crop']
    data['objects'][0]['source_kind'] = 'crop'
    data['asset_decisions'][0]['route'] = 'crop'
    respond(p, data)
    task, result = review(p); result.pop('text_checks')
    respond(p, result, task)
    assert wf.next_task(p)['task']['kind'] == 'office_render'


def test_replacement_and_import_preserve_bound_sources(tmp_path):
    p = begin(tmp_path)
    respond(p, plan(scope(poster(p))))
    respond(p, image_payload())
    task, result = review(p); result.pop('text_checks'); respond(p, result, task)
    wf.next_task(p)
    scene = assemble(load(p)); write_json(p/'replacement.json', scene)
    wf.replace_scene(p, p/'replacement.json', 'TEST unchanged scoped scene import')
    imported = load(p)['pages'][0]['imported_slide']
    source = imported['element_scope']['units'][0]['source']
    assert sha256(p/source['asset']) == source['sha256']
    assert validate_outputs(imported['element_scope'], imported['objects'], p)
    task, result = review(p); result.pop('text_checks'); respond(p, result, task)
    assert wf.next_task(p)['task']['kind'] == 'office_render'


def test_new_templates_default_to_unresolved_scope_without_fake_observations(tmp_path):
    p = begin(tmp_path)
    task = wf.next_task(p)
    template = read_json(task['task']['response_template'])['result']
    assert template['element_scope']['units'][0]['required_edit'] == 'unresolved'
    assert not template['element_scope']['task_requirement']


def test_schema_validates_real_scoped_payloads(tmp_path):
    from toolbox_manager.contracts import validate_result
    p = begin(tmp_path)
    validate_result('page_plan', plan(scope(poster(p), unit())), ROOT)
    data = image_payload(); data['objects'] += payload()['objects']; data['scope_bindings'] += payload()['scope_bindings']
    validate_result('region_objects', data, ROOT)
    respond(p, plan(scope(poster(p), unit()))); respond(p, data)
    task, result = review(p)
    validate_result('source_review', result, ROOT)
    respond(p, result, task)


def test_editable_unit_cannot_hide_screenshot_behind_one_native_label(tmp_path):
    p = begin(tmp_path, scope())
    data = image_payload(); data['objects'] += payload()['objects']
    data['scope_bindings'] = [{'unit_id': 'body', 'object_ids': ['poster', 'label']}]
    with pytest.raises(WorkflowError, match='cannot hide content'): respond(p, data)


def test_managed_dispatch_validates_scope_before_committing(runtime):
    from test_managed_rebuild import begin as managed_begin, response, invoke, declare
    manager, p, _ = managed_begin(runtime)
    assert response(manager, p, plan(scope(poster(p), unit())))['command_status'] == 'completed'
    declare(manager, p, 'production')
    data = image_payload(); data['objects'] += payload()['objects']; data['scope_bindings'] += payload()['scope_bindings']
    task = invoke(manager, 'next', p)['task']
    before = sha256(p/'workflow/state.json')
    bad = copy.deepcopy(data); bad['objects'][0]['source_kind'] = 'generated'
    result = invoke(manager, 'validate_response', p, task_id=task['task_id'], token=task['token'],
                    base_revision=task['base_revision'], result=bad)
    assert result['command_status'] == 'completed' and result['valid'] is False
    assert any('preserved source cannot' in row['message'] for row in result['errors'])
    assert sha256(p/'workflow/state.json') == before
    assert response(manager, p, data, task)['command_status'] == 'completed'
    task = invoke(manager, 'next', p)['task']
    contract = compiled_scope(load(p)['pages'][0])
    result = {'status': 'passed', 'reviewer': 'TEST', 'note': 'SYNTHETIC transport fixture',
              'viewed_files': task['must_view_files'],
              'scope_review': {'revision': 1, 'units': [
                  {'unit_id': u['id'], 'status': 'passed', 'note': 'SYNTHETIC source fixture'} for u in contract['units']]},
              'text_checks': [{'object_id': 'slide-001.one.label', 'source_text': 'TEST'}]}
    assert response(manager, p, result, task)['command_status'] == 'completed'
    assert load(p)['pages'][0]['source_review']['status'] == 'passed'
