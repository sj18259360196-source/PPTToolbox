"""Synthetic PNG tests, not host generation or visual/Office acceptance."""
import copy

import pytest
from PIL import Image, ImageDraw

from test_tools import ROOT
from common import read_json, sha256, write_json
from asset_batch import validate_batch_request, validate_batch_result, ingest_batch_result
from asset_ops import generation_text_contract, prepare_generation, ingest_generation


def fixture(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    reference = project / 'reference.png'
    Image.new('RGB', (50, 50), 'white').save(reference)
    decision = {'basis': 'user_request', 'reference': 'reference.png', 'reason': 'Explicit fixture request'}
    request = {'id': 'icons', 'purpose': 'Synthetic independent icons', 'prompt': 'Synthetic test only',
               'transparent': True, 'allowed_approximation': True, 'multi_icon_sheet': True,
               'items': [{'id': name, 'purpose': name, 'generation_decision': copy.deepcopy(decision),
                          'min_subject_pixels': [10, 10]} for name in ['mouse', 'flower']]}
    image = project / 'sheet.png'
    im = Image.new('RGBA', (100, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rectangle((8, 8, 30, 30), fill='red')
    draw.rectangle((65, 12, 85, 33), fill='blue')
    im.save(image)
    job = {'id': 'page.art.icons', 'request': request}
    result = {'file': str(image), 'tool_used': 'Pillow synthetic fixture', 'model_reported': None,
              'provenance': 'Synthetic fixture, no generation', 'sheet_sha256': sha256(image),
              'items': [{'id': 'mouse', 'crop': [2, 2, 38, 38], 'status': 'accepted',
                         'note': 'Controlled red pixels', 'viewed_files': [str(image)]},
                        {'id': 'flower', 'crop': [55, 2, 40, 40], 'status': 'accepted',
                         'note': 'Controlled blue pixels', 'viewed_files': [str(image)]}]}
    return project, job, result


def test_one_sheet_retained_and_exact_pixels_cropped(tmp_path):
    project, job, result = fixture(tmp_path)
    destination = project / 'attempt-001'
    manifest = ingest_batch_result(project, job, result, destination)
    assert manifest['sheet']['sha256'] == sha256(destination / 'sheet.png')
    assert manifest['visual_review_status'] == 'not_run'
    assert manifest['decision_scope'] == 'crop_selection_only'
    with Image.open(result['file']) as source:
        for item in manifest['items']:
            x, y, w, h = item['crop']
            with Image.open(destination / item['asset']) as crop:
                assert crop.tobytes() == source.crop((x, y, x+w, y+h)).tobytes()
            assert sha256(destination / item['asset']) == item['asset_sha256']
            assert item['source_crop'] == item['crop']
    assert read_json(destination / 'batch-manifest.json') == manifest
    original_hashes = {p.relative_to(destination).as_posix(): sha256(p) for p in destination.rglob('*') if p.is_file()}
    assert ingest_batch_result(project, job, result, destination) == manifest
    assert {p.relative_to(destination).as_posix(): sha256(p) for p in destination.rglob('*') if p.is_file()} == original_hashes


@pytest.mark.parametrize('change', ['crop_file', 'crop_result', 'sheet_file', 'manifest', 'extra'])
def test_interrupted_batch_recovery_refuses_changed_artifacts(tmp_path, change):
    project, job, result = fixture(tmp_path)
    destination = project / 'published'
    manifest = ingest_batch_result(project, job, result, destination)
    if change == 'crop_file': Image.new('RGBA', (38, 38), 'yellow').save(destination / 'assets/mouse.png')
    if change == 'crop_result': result['items'][0]['crop'] = [1, 1, 38, 38]
    if change == 'sheet_file': Image.new('RGBA', (100, 50), 'yellow').save(destination / 'sheet.png')
    if change == 'manifest':
        manifest['producer_claim']['provenance'] = 'Different claim'
        write_json(destination / 'batch-manifest.json', manifest)
    if change == 'extra': (destination / 'unknown.txt').write_text('Unknown artifact', encoding='utf-8')
    before = {p.relative_to(destination).as_posix(): sha256(p) for p in destination.rglob('*') if p.is_file()}
    with pytest.raises(ValueError): ingest_batch_result(project, job, result, destination)
    assert {p.relative_to(destination).as_posix(): sha256(p) for p in destination.rglob('*') if p.is_file()} == before


def test_partial_retry_keeps_prior_accepted_pixels(tmp_path):
    project, job, result = fixture(tmp_path)
    result['items'][1]['status'] = 'retry'
    first = ingest_batch_result(project, job, result, project / 'attempt-001')
    accepted = project / 'attempt-001' / first['items'][0]['asset']
    accepted_hash = sha256(accepted)
    assert not (project / 'attempt-001/assets/flower.png').exists()
    retry_job = copy.deepcopy(job)
    retry_job['request']['items'] = retry_job['request']['items'][1:]
    Image.new('RGBA', (70, 70), (0, 0, 0, 0)).save(project / 'retry.png')
    with Image.open(project / 'retry.png') as im:
        draw = ImageDraw.Draw(im)
        draw.ellipse((20, 20, 45, 45), fill='green')
        im.save(project / 'retry.png')
    retry_result = {**result, 'file': str(project / 'retry.png'), 'sheet_sha256': sha256(project / 'retry.png'),
                    'items': [{**result['items'][1], 'status': 'accepted', 'crop': [10, 10, 50, 50],
                               'viewed_files': [str(project / 'retry.png')]}]}
    second = ingest_batch_result(project, retry_job, retry_result, project / 'attempt-002')
    assert second['items'][0]['id'] == 'flower'
    assert sha256(accepted) == accepted_hash
    assert second['sheet']['sha256'] != first['sheet']['sha256']


@pytest.mark.parametrize('mutation', ['hash', 'missing', 'duplicate', 'outside', 'fraction', 'overlap', 'unviewed', 'tiny'])
def test_reject_before_any_output(tmp_path, mutation):
    project, job, result = fixture(tmp_path)
    if mutation == 'hash': result['sheet_sha256'] = '0' * 64
    if mutation == 'missing': result['items'].pop()
    if mutation == 'duplicate': result['items'][1]['id'] = 'mouse'
    if mutation == 'outside': result['items'][0]['crop'] = [90, 0, 20, 30]
    if mutation == 'fraction': result['items'][0]['crop'][0] = 0.5
    if mutation == 'overlap': result['items'][1]['crop'] = [2, 2, 90, 40]
    if mutation == 'unviewed': result['items'][0]['viewed_files'] = []
    if mutation == 'tiny': job['request']['items'][0]['min_subject_pixels'] = [100, 100]
    with pytest.raises(ValueError):
        ingest_batch_result(project, job, result, project / 'bad')
    assert not (project / 'bad').exists()


def test_new_sheet_cannot_use_old_hash(tmp_path):
    project, job, result = fixture(tmp_path)
    Image.new('RGBA', (100, 50), 'purple').save(result['file'])
    with pytest.raises(ValueError, match='hash changed'):
        validate_batch_result(project, job, result)


def test_no_blank_or_rgb_sheet(tmp_path):
    project, job, result = fixture(tmp_path)
    for mode, color in [('RGB', 'white'), ('RGBA', (0, 0, 0, 0))]:
        Image.new(mode, (100, 50), color).save(result['file'])
        result['sheet_sha256'] = sha256(result['file'])
        with pytest.raises(ValueError): validate_batch_result(project, job, result)


def test_text_contract_scopes_embedded_words():
    decision = {'text_ownership': 'embedded', 'embedded_text': [{'text': 'A1', 'legibility': 'readable'}]}
    contract = generation_text_contract(decision)
    assert contract['baked_text_numbers_relations']
    assert contract['allowed_material_text'] == decision['embedded_text']
    assert generation_text_contract(None)['baked_text_numbers_relations'] is False


def test_host_handoff_and_ingress_keep_task_token_and_one_sheet(tmp_path, monkeypatch):
    project, job, result = fixture(tmp_path)
    packet = project / 'packet.json'
    write_json(packet, {'task_id': 'task-01', 'token': 'fixture-token',
                       'target': {'job_id': job['id']}, 'context': {'request': job['request']}})
    import workflow
    monkeypatch.setattr(workflow, 'next_task', lambda p: {'task': {'kind': 'asset_material', 'id': 'task-01',
                                                               'packet': str(packet), 'must_view_files': []}})
    handoff = prepare_generation(project, project / 'handoff')
    assert len(handoff['items']) == 2
    assert handoff['output_contract']['one_sheet_multiple_independent_items']
    assert handoff['visual_review_status'] == 'not_run'
    producer = project / 'producer.json'
    write_json(producer, {k: result[k] for k in ('tool_used', 'model_reported', 'provenance')})
    crops = project / 'crops.json'
    write_json(crops, {k: result[k] for k in ('sheet_sha256', 'items')})
    report = ingest_generation(project, project / 'handoff/generation-request.json',
                               project / 'sheet.png', producer, project / 'ingress', crops)
    response = read_json(project / 'ingress/response.json')
    assert response['token'] == 'fixture-token'
    assert response['result']['items'] == result['items']
    assert report['status'] == 'awaiting_visual_review'
    assert not (project / 'ingress/assets').exists()
