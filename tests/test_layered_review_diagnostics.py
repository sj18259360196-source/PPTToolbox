"""Advisory diagnostics and exact versioned comparison coverage."""
import copy
import json
import sys
from pathlib import Path
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from layered_review import POLICY, required_views, bundle_view_files, view_signature, effective_resolution, review_policy
from illustration_tools import analyze


def test_versioned_views_bind_overlay_bytes(tmp_path):
    assert review_policy({}) == 'legacy-side/1'
    assert review_policy({'review_policy': POLICY}) == POLICY
    side, overlay = tmp_path/'side.png', tmp_path/'overlay.png'
    side.write_bytes(b'same-side'); overlay.write_bytes(b'first-overlay')
    row = {'file': side, 'views': {'side_by_side': side, 'overlay': overlay}}
    comp = {'full_paths': {1: side}, 'full_view_paths': {1: row['views']},
            'local_paths': {(1, 'organ'): row}}
    assert required_views(comp, 1) == [side]
    assert required_views(comp, 1, policy=POLICY) == [side, overlay]
    assert bundle_view_files(row, POLICY) == [side, overlay]
    old = view_signature(comp, 1, 'organ', POLICY)
    overlay.write_bytes(b'changed-overlay')
    assert view_signature(comp, 1, 'organ', POLICY) != old
    assert required_views(comp, 1, 'organ') == [side]
    with pytest.raises(KeyError):
        required_views({'full_paths': {1: side}}, 1, policy=POLICY)
    with pytest.raises(ValueError):
        required_views(comp, 1, policy='unsupported/9')


def test_reuse_cannot_upgrade_legacy_observation(tmp_path):
    from review_reuse import eligible
    assert eligible(tmp_path, {}, {'review_policy': POLICY}) == {}


def test_overlay_change_invalidates_reuse_even_with_equal_side_and_scene(tmp_path, monkeypatch):
    import review_reuse
    import workflow_evidence
    from common import sha256
    side = tmp_path/'side.png'; side.write_bytes(b'identical-side')
    old_overlay = tmp_path/'old-overlay.png'; old_overlay.write_bytes(b'old')
    new_overlay = tmp_path/'new-overlay.png'; new_overlay.write_bytes(b'new')
    def comp(overlay):
        views = {'side_by_side': side, 'overlay': overlay}
        return {'full_paths': {1: side}, 'full_view_paths': {1: views},
                'local_paths': {(1, 'organ'): {'file': side, 'views': views, 'object_ids': ['organ']}}}
    monkeypatch.setattr(workflow_evidence, 'comparison_views', lambda project, run: comp(old_overlay if run['id']=='old' else new_overlay))
    monkeypatch.setattr(review_reuse, 'signature', lambda project, run, local=False: {(1, 'organ'): 'scene'} if local else {1: 'scene'})
    folder = tmp_path/'workflow/tasks/task-1'; folder.mkdir(parents=True)
    packet = folder/'packet.json'; packet.write_text(json.dumps({'input_files': []}), encoding='utf-8')
    record = tmp_path/'observation.json'
    record.write_text(json.dumps({'kind': 'review_local', 'target': {'index': 1, 'region_id': 'organ'},
        'result': {'status': 'passed'}, 'task_id': 'task-1', 'packet_sha256': sha256(packet)}), encoding='utf-8')
    old = {'id': 'old', 'review_policy': POLICY, 'reviews': {'local:1:organ': {'file': 'observation.json', 'sha256': sha256(record)}}}
    new = {'id': 'new', 'review_policy': POLICY}
    assert review_reuse.eligible(tmp_path, old, new) == {}
    new_overlay.write_bytes(b'old')
    assert review_reuse.eligible(tmp_path, old, new) == old['reviews']


def test_surfaces_preserve_holes_connectors_and_report_fragments():
    def path(identifier, coords, closed=True, fill='FF0000'):
        return {'id': identifier, 'kind': 'path', 'closed': closed,
                'commands': coords, 'style': {'fill': fill}}
    shell = [['M', 0, 0], ['L', 100, 0], ['L', 100, 100], ['Z'],
             ['M', 10, 10], ['L', 20, 10], ['L', 20, 20], ['Z']]
    objects = [{'id': 'body', 'kind': 'group', 'children': [path('shell', shell),
        path('tiny', [['M', 60, 60], ['L', 61, 60], ['L', 61, 61], ['Z']]),
        path('edge', [['M', 0, 0], ['L', 5, 5]], False, None),
        path('unclosed-fill', [['M', 0, 0], ['L', 1, 1]])]}]
    before = copy.deepcopy(objects)
    report = analyze(objects)['semantic_surfaces']
    assert report['open_filled_path_ids'] == ['unclosed-fill']
    assert report['tiny_relative_hull_ids'] == ['tiny', 'unclosed-fill']
    assert report['paths'][0]['closed_subpaths'] == 2
    assert report['paths'][0]['compound_interpretation']
    assert report['component_groups']['body'] == ['shell', 'tiny', 'edge', 'unclosed-fill']
    assert report['automatic_acceptance'] is False
    assert objects == before


def test_effective_resolution_uses_subject_not_transparent_file_bounds(tmp_path):
    im = Image.new('RGBA', (1000, 1000))
    im.paste((255, 0, 0, 255), (400, 300, 600, 700)); im.save(tmp_path/'asset.png')
    node = {'id': 'art', 'kind': 'image', 'asset': 'asset.png', 'bbox': [0, 0, 500, 500]}
    report = effective_resolution(node, tmp_path, {'width': 1000, 'height': 1000, 'width_pt': 720, 'height_pt': 720})
    assert report['subject_pixels_xywh'] == [400, 300, 200, 400]
    assert report['placed_subject_size'] == [100, 200]
    assert report['effective_ppi'] == pytest.approx([200, 200])
    assert report['automatic_acceptance'] is False


def test_resolution_crop_and_cover_follow_actual_picture_fit(tmp_path):
    Image.new('RGB', (200, 100)).save(tmp_path/'photo.png')
    canvas = {'width': 100, 'height': 100, 'width_pt': 72, 'height_pt': 72}
    node = {'id': 'photo', 'kind': 'image', 'asset': 'photo.png', 'bbox': [0, 0, 100, 100], 'fit': 'cover'}
    report = effective_resolution(node, tmp_path, canvas)
    assert report['visible_crop_xywh'] == [50, 0, 100, 100]
    assert report['effective_ppi'] == pytest.approx([100, 100])
    node['source_crop'] = [25, 10, 50, 20]
    report = effective_resolution(node, tmp_path, canvas)
    assert report['effective_ppi'] == pytest.approx([50, 20])
    node['source_crop'] = [100, 0, 101, 50]
    with pytest.raises(ValueError): effective_resolution(node, tmp_path, canvas)
