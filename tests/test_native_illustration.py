"""Shared-centerline surfaces, rejected geometry, discovery and native output."""
import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from graphics_geometry import ribbon, flatten
from graphics_recipe import compile_recipe


def example():
    return json.loads((ROOT/'examples/graphics/native-tube.json').read_text('utf-8'))


def test_straight_band_has_exact_width_offset_area():
    from shapely import Polygon
    commands, report = ribbon([['M', 10, 20], ['L', 110, 20]], 8, 3)
    p = Polygon(flatten(commands)[0])
    assert p.bounds == pytest.approx((10, 19, 110, 27))
    assert p.area == pytest.approx(800)
    assert report['visual_review'] == 'pending'


def test_case_centerline_makes_seven_named_editable_surfaces():
    result = compile_recipe(example())
    children = result['objects'][0]['children']
    assert len(children) == 7
    assert all(o['kind'] == 'path' and o['closed'] for o in children)
    assert children[0]['id'] == 'tube_clear-body'
    assert all(any(c[0] == 'C' for c in o['commands']) for o in children)
    assert result['dependencies']['tube'] == ['centerline']
    changed = example()
    changed['paths'][0]['commands'][1][1] += 1
    after = compile_recipe(changed)['objects'][0]['children']
    assert all(a['commands'] != b['commands'] for a, b in zip(children, after))
    assert result['office'] == 'not_run'


@pytest.mark.parametrize('commands', [
    [['M', 0, 0], ['L', 0, 0]],
    [['M', 0, 0], ['L', 20, 20], ['L', 0, 20], ['L', 20, 0]],
    [['M', 0, 0], ['L', 20, 0], ['Z']],
    [['M', 0, 0], ['C', 0, 0, 0, 0, 0, 0]],
    [['M', 0, 0], ['L', 20, 0], ['L', 20, 1], ['L', 0, 1]],
])
def test_degenerate_crossing_closed_and_collapsed_bands_are_rejected(commands):
    with pytest.raises(ValueError):
        ribbon(commands, 8)


@pytest.mark.parametrize('width', [0, -1, .01, float('nan'), True])
def test_width_guards(width):
    with pytest.raises(ValueError):
        ribbon([['M', 0, 0], ['L', 100, 0]], width)


def test_seven_stop_metal_fill_and_reject_bad_layer_stops():
    r = example()
    gradient = r['curve_groups'][0]['layers'][0]['style']['gradient']
    gradient['stops'] = [{'position': i/6, 'color': c} for i, c in enumerate(
        ['646766', 'B6BAB8', 'FAFBF9', '515655', '3D4342', '777D7B', 'C4C8C5'])]
    assert len(compile_recipe(r)['objects'][0]['children'][0]['style']['gradient']['stops']) == 7
    gradient['stops'][2]['position'] = 0
    with pytest.raises(ValueError, match='stops'):
        compile_recipe(r)


def test_layer_ids_and_irrelevant_parameters_rejected():
    r = example()
    r['curve_groups'][0]['layers'][1]['id'] = r['curve_groups'][0]['layers'][0]['id']
    with pytest.raises(ValueError, match='Duplicate'):
        compile_recipe(r)
    r = example()
    r['curve_groups'][0]['count'] = 4
    with pytest.raises(ValueError, match='not applicable'):
        compile_recipe(r)


def test_native_package_retains_paths_gradients_and_no_images(tmp_path):
    from build_pptx import build
    from zipfile import ZipFile
    from lxml import etree
    result = compile_recipe(example())
    scene = tmp_path/'scene.json'
    scene.write_text(json.dumps(result['scene']), encoding='utf-8')
    target = tmp_path/'tube.pptx'
    build(scene, target)
    with ZipFile(target) as z:
        xml = etree.fromstring(z.read('ppt/slides/slide1.xml'))
        ns = {'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
              'p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
        assert len(xml.findall('.//a:custGeom', ns)) == 7
        assert len(xml.findall('.//a:gradFill', ns)) == 7
        assert not xml.findall('.//p:pic', ns)


def test_managed_inspect_exposes_example_and_execution_guard(tmp_path):
    from toolbox_manager.service import Manager
    from toolbox_manager.graphics import call
    root = tmp_path/'app'
    root.mkdir()
    (root/'SKILL.md').write_text('version: "test"', encoding='utf-8')
    m = Manager(tmp_path/'data', root=root, home=tmp_path/'home')
    info = call(m, 'inspect', {})
    assert 'surface_layers' in info['capabilities']
    assert info['illustration_example'] == example()
    with pytest.raises(ValueError):
        call(m, 'preview', {'recipe': example()})
