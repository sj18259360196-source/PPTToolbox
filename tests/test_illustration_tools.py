"""Real command counting, geometry, provenance, and managed discovery checks."""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from illustration_tools import analyze, material_recipe, audit_sources


def test_counts_nested_subpaths_and_input_unchanged():
    objects = [{'id': 'g', 'kind': 'group', 'children': [
        {'id': 'a', 'kind': 'path', 'commands': [['M', 0, 0], ['C', 1, 0, 2, 0, 3, 0],
            ['M', 2, 3], ['L', 4, 5]], 'style': {'fill_alpha': .5,
            'gradient': {'type': 'linear', 'stops': []}}},
        {'id': 'b', 'kind': 'text', 'bbox': [0, 0, 10, 10]}]}]
    before = copy.deepcopy(objects)
    result = analyze(objects, cubic_warning=1)
    assert result['counts'] == dict(objects=3, groups=1, leaves=2, paths=1,
        subpaths=2, cubic_segments=1, commands=4, gradients=1, images=0, text=1)
    assert {w['code'] for w in result['warnings']} == {'edit_complexity', 'composed_alpha', 'compound_path'}
    assert objects == before
    assert result['office'] == 'not_run'


@pytest.mark.parametrize('commands', [[['C', 1, 2]], [['M', float('nan'), 1]], [['M', True, 0]], [['Q', 1, 2]]])
def test_rejects_malformed_commands(commands):
    with pytest.raises(ValueError):
        analyze([{'id': 'a', 'kind': 'path', 'commands': commands}])


def test_rejects_duplicate_ids_and_deep_groups():
    with pytest.raises(ValueError):
        analyze([{'id': 'a', 'kind': 'shape'}]*2)
    node = {'id': 'leaf', 'kind': 'shape'}
    for i in range(35):
        node = {'id': f'g{i}', 'kind': 'group', 'children': [node]}
    with pytest.raises(ValueError):
        analyze([node])


@pytest.mark.parametrize('preset,count', [('droplet', 4), ('rotated_end', 3)])
def test_material_native_package_and_roles(tmp_path, preset, count):
    from graphics_recipe import compile_recipe
    from build_pptx import build
    from zipfile import ZipFile
    from lxml import etree
    result = material_recipe(preset, 'water', [20, 30, 40, 25], [200, 150])
    assert len(result['roles']) == len(result['objects']) == count
    compiled = compile_recipe(result['recipe'])
    scene = tmp_path/'scene.json'
    scene.write_text(json.dumps(compiled['scene']), encoding='utf-8')
    build(scene, tmp_path/'material.pptx')
    with ZipFile(tmp_path/'material.pptx') as z:
        xml = etree.fromstring(z.read('ppt/slides/slide1.xml'))
        ns = {'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
              'p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
        assert len(xml.findall('.//a:custGeom', ns)) == count
        assert not xml.findall('.//p:pic', ns)
    assert result['scope'] == 'new_parameterized_example_not_historical_generator'


def test_rotation_moves_every_material_point_about_common_center():
    a = material_recipe('droplet', 'd', [30, 40, 60, 20], [200, 200])
    b = material_recipe('droplet', 'd', [30, 40, 60, 20], [200, 200], rotation=90)
    for p, q in zip(a['recipe']['paths'], b['recipe']['paths']):
        for c, d in zip(p['commands'], q['commands']):
            for j in range(1, len(c), 2):
                assert d[j:j+2] == pytest.approx([60-(c[j+1]-50), 50+(c[j]-60)])
    with pytest.raises(ValueError):
        material_recipe('droplet', 'd', [0, 0, 10, 20], [100, 100], rotation=float('nan'))


def test_dependency_hash_missing_and_temporary(tmp_path):
    f = tmp_path/'.tmp/generator.py'
    f.parent.mkdir(); f.write_bytes(b'print(1)')
    result = audit_sources(tmp_path, [
        {'path': '.tmp/generator.py', 'role': 'generator', 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()},
        {'path': 'absent.json', 'role': 'schema'},
        {'path': '.tmp/generator.py', 'role': 'helper', 'sha256': '0'*64}])
    assert [r['status'] for r in result['files']] == ['present', 'missing', 'hash_mismatch']
    assert result['files'][0]['temporary'] is True
    assert result['status'] == 'needs_attention'


@pytest.mark.parametrize('name', ['../outside.py', '/outside.py', 'C:\\outside.py', 'a/../../b', 'data:stream'])
def test_dependency_cannot_escape_project(tmp_path, name):
    with pytest.raises(ValueError):
        audit_sources(tmp_path, [{'path': name, 'role': 'helper'}])


def test_managed_discovery_policy_and_cli_parity(tmp_path):
    from toolbox_manager.service import Manager
    from toolbox_manager.mcp import MCP
    from toolbox_manager.policy import PolicyDenied
    m = Manager(tmp_path/'data', root=ROOT, home=tmp_path/'home')
    names = [t['id'] for t in m.catalog()]
    for name in ['analyze', 'material_recipe', 'audit_sources']:
        assert names.count('graphics.'+name) == 1
        assert 'graphics_'+name in {n for n, _, _ in MCP(tmp_path/'rpc-data', root=ROOT, home=tmp_path/'rpc-home').specs()}
    request = {'objects': [{'id': 'a', 'kind': 'shape'}]}
    f = tmp_path/'request.json'; f.write_text(json.dumps(request), encoding='utf-8')
    assert m.execute('graphics.analyze', ['--json', str(f)]) == m.graphics('analyze', request)
    with pytest.raises(PolicyDenied):
        m.graphics('material_recipe', {'preset': 'droplet', 'id': 'a', 'box': [10, 10, 20, 20], 'canvas': [100, 100]})
    assert m.graphics('material_recipe', {'preset': 'droplet', 'id': 'a', 'box': [10, 10, 20, 20], 'canvas': [100, 100]}, source='owner')['objects']
    with pytest.raises((PolicyDenied, ValueError)):
        m.graphics('audit_sources', {'project': str(tmp_path/'unregistered'), 'dependencies': [{'path': 'a', 'role': 'helper'}]})
    with pytest.raises(ValidationError):
        m.graphics('analyze', {'objects': [], 'unknown': True})


def test_builtin_commands_visible_without_writes_and_user_override_wins(tmp_path):
    from toolbox_manager.service import Manager
    m = Manager(tmp_path/'data', root=ROOT, home=tmp_path/'home')
    settings = m.settings()
    grants = m.store.get('project_authorizations', {})
    rows = m.commands()
    row = next(r for r in rows if r['id'] == 'native_illustration_complexity')
    assert row['builtin'] is True and row['revision'] == 0
    assert row['id'] in {r['id'] for r in m.context()['instructions']}
    with m.store.db() as c:
        assert c.execute('SELECT count(*) FROM commands').fetchone()[0] == 0
    m.save_command({**row, 'body': 'User revised guidance', 'enabled': False})
    saved = next(r for r in m.commands() if r['id'] == row['id'])
    assert saved['body'] == 'User revised guidance' and not saved['enabled']
    assert row['id'] not in {r['id'] for r in m.context()['instructions']}
    assert m.settings() == settings
    assert m.store.get('project_authorizations', {}) == grants


@pytest.mark.parametrize('query,identifier', [
    ('复杂度 子路径', 'EXP-174'), ('中心线 反向 高光', 'EXP-175'),
    ('水珠 四层', 'EXP-176'), ('依赖 临时目录', 'EXP-178')])
def test_new_lessons_are_searchable_and_source_bound(query, identifier):
    from rebuild_assistance import search
    from experience_library import show, audit
    assert identifier in {r['id'] for r in search(query)['matches']}
    expected_source='S38' if (ROOT/'PUBLIC_DISTRIBUTION.json').exists() else 'S36'
    assert show(identifier)['sources'][0]['source_id'] == expected_source
    assert show(identifier)['runtime_retested'] is False
    assert audit()['status'] == 'passed'
