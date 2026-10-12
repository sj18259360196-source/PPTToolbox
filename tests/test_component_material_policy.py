"""Deterministic contracts only; no host generation or visual acceptance."""
import copy

import jsonschema
import pytest

from scripts.material_routes import DECISION_SCHEMA, validate_decision
from toolbox_manager.project_status import generation_nodes, generation_routes


def category(**patch):
    return {'basis': 'content_category', 'reference': 'input/art.png',
            'reason': 'Complex source illustration needs whole-component replacement',
            'content_type': 'complex_illustration', 'required_edit': 'image_replace', **patch}


@pytest.mark.parametrize('content_type', ['complex_illustration', 'decorative_title'])
def test_category_route_has_no_required_drawing_or_score(content_type):
    value = category(content_type=content_type)
    if content_type == 'decorative_title':
        value.update(text_ownership='asset_title', embedded_text=[{'text': 'Exact title', 'legibility': 'readable'}])
    jsonschema.validate(value, DECISION_SCHEMA)
    assert validate_decision(value) == value
    assert 'drawing' not in value and 'similarity_pct' not in value


def test_generated_decorative_title_requires_exact_original_text():
    for patch in ({}, {'text_ownership': 'embedded'},
                  {'text_ownership': 'asset_title', 'embedded_text': []},
                  {'text_ownership': 'asset_title', 'embedded_text': [{'text': '', 'legibility': 'unreadable'}]}):
        with pytest.raises(ValueError):
            validate_decision(category(content_type='decorative_title', **patch))


@pytest.mark.parametrize('patch', [
    {'content_type': 'identity_asset'}, {'content_type': 'page_text'},
    {'content_type': 'simple_icon'}, {'fidelity': 'exact'}, {'required_edit': 'geometry'},
    {'required_edit': 'preserve'}, {'required_edit': 'text'},
    {'required_edit': 'data'}, {'required_edit': 'unresolved'},
    {'text_ownership': 'page'}, {'unexpected': True},
])
def test_category_cannot_bypass_preservation_or_editability(patch):
    with pytest.raises(ValueError):
        validate_decision(category(**patch))


def test_category_requires_both_classification_and_edit_contract():
    for field in ('content_type', 'required_edit'):
        value = category()
        del value[field]
        with pytest.raises(ValueError):
            validate_decision(value)


def test_exact_embedded_text_is_preserved_without_editable_page_ownership():
    value = category(text_ownership='embedded', embedded_text=[
        {'text': 'FOLLICLE 2', 'legibility': 'readable', 'owner_unit_id': 'follicle'},
        {'text': '', 'legibility': 'unreadable'},
    ])
    original = copy.deepcopy(value)
    assert validate_decision(value) == original
    assert value == original
    for patch in ({'text_ownership': 'page'}, {'text_ownership': 'asset_title',
                  'embedded_text': [{'text': '', 'legibility': 'readable'}]},
                  {'embedded_text': [{'text': 'guessed', 'legibility': 'unreadable'}]}):
        with pytest.raises(ValueError):
            validate_decision({**value, **patch})


def test_user_request_does_not_override_recorded_native_or_source_requirements():
    value = {'basis': 'user_request', 'reference': 'input/art.png', 'reason': 'Explicit generation request'}
    assert validate_decision(value) == value
    for patch in ({'required_edit': 'text'}, {'content_type': 'identity_asset'},
                  {'text_ownership': 'page'}):
        with pytest.raises(ValueError):
            validate_decision({**value, **patch})


def test_content_route_graph_never_invents_drawing_score_or_host_execution():
    route = {'id': 'complex-art', 'decision': category(), 'purpose': 'reference art',
             'status': 'pending', 'multi_icon_sheet': False, 'placed': 0, 'cropped': 0}
    nodes = generation_nodes([route])
    assert [n['kind'] for n in nodes] == ['fidelity', 'generation', 'compose']
    assert nodes[0]['status_label'] == '组件路线'
    assert '%' not in nodes[0]['detail']
    assert nodes[1]['status'] == 'planned'


def test_policy_changes_routing_without_mutating_permission_overrides():
    from toolbox_manager.material_policy import effective

    class Store:
        def get(self, key, default):
            return default

    class Manager:
        store = Store()

        def settings(self):
            return {'revision': 7, 'material_search_allowed': False,
                    'host_generation_allowed': False, 'reference_upload_allowed': False}

    result = effective(Manager())
    policy = result['illustration_route']
    assert policy['default_basis'] == 'content_category_and_object_requirements'
    assert policy['drawing_required'] is False
    assert policy['category_defaults']['photograph'] == 'inspect_photo_requirement'
    assert policy['category_defaults']['complex_illustration'] == 'reference_generate'
    assert policy['legacy_fallback']['threshold_pct'] == 75
    assert result['values'] == {key: False for key in result['values']}


def test_batch_routes_retain_per_item_decisions_and_show_one_sheet_generation():
    items = [{'id': name, 'purpose': name, 'generation_decision': category()}
             for name in ('mouse', 'follicle')]
    workflow = {'asset_jobs': [{'id': 'sheet', 'slide_id': 'slide1', 'status': 'pending',
                               'request': {'purpose': 'two components', 'transparent': True,
                                           'multi_icon_sheet': True, 'items': items}}]}
    routes = generation_routes(workflow)
    assert len(routes) == 1 and routes[0]['decision'] is None
    assert [r['id'] for r in routes[0]['item_decisions']] == ['mouse', 'follicle']
    nodes = generation_nodes(routes)
    assert [n['kind'] for n in nodes] == ['fidelity', 'generation', 'crop', 'compose']
    assert nodes[1]['status'] == 'planned'
    job = workflow['asset_jobs'][0]
    job['accepted_items'] = {'mouse': {'asset': 'assets/mouse.png'}}
    job['attempts'] = [{'accepted_ids': ['mouse'], 'retry_ids': ['follicle']}]
    routes = generation_routes(workflow)
    nodes = generation_nodes(routes)
    assert nodes[1]['status_label'] == '部分素材已登记'
    assert nodes[2]['status'] == 'planned'
    assert routes[0]['accepted_item_ids'] == ['mouse']


def test_package_validation_uses_relative_common_import(tmp_path):
    from PIL import Image
    source = tmp_path / 'input' / 'art.png'
    source.parent.mkdir()
    Image.new('RGBA', (1, 1), 'red').save(source)
    assert validate_decision(category(), tmp_path)['reference'] == 'input/art.png'


def scoped_material(**patch):
    return {'id': 'art', 'region_id': 'region', 'owner_id': None,
            'required_edit': 'image_replace', 'content_type': 'complex_illustration',
            'material_route': 'reference_generate', 'text_ownership': 'embedded',
            'embedded_text': [{'text': 'ORIGINAL', 'legibility': 'readable'}], **patch}


def bind_generated(units, decision, source_kind='generated'):
    from scripts.element_scope import validate_outputs
    image = {'id': 'image', 'kind': 'image', 'source_kind': source_kind,
             'generation_decision': decision}
    return validate_outputs({'units': units}, [image], bindings=[
        {'unit_id': unit['id'], 'object_ids': ['image']} for unit in units])


def scoped_decision(**patch):
    return category(text_ownership='embedded', embedded_text=scoped_material()['embedded_text'], **patch)


@pytest.mark.parametrize('route', ['native', 'preserve_source'])
def test_generation_rejects_selected_component_route_without_scope_revision(route):
    from scripts.component_strategy import validate_generation_scope
    unit = scoped_material(material_route=route)
    with pytest.raises(ValueError, match='selected component route'):
        validate_generation_scope({'scope_unit_ids': ['art'], 'generation_decision': scoped_decision()},
                                  {'units': [unit]}, 'region')
    with pytest.raises(ValueError, match='selected component route'):
        bind_generated([unit], scoped_decision())


def test_embedded_child_generation_cannot_override_its_owners_native_route():
    from scripts.component_strategy import validate_generation_scope
    parent = scoped_material(region_id='parent_region', material_route='native')
    child = {'id': 'caption', 'region_id': 'child_region', 'owner_id': 'art',
             'required_edit': 'image_replace', 'text_ownership': 'embedded'}
    with pytest.raises(ValueError, match='selected component route'):
        validate_generation_scope({'scope_unit_ids': ['caption'], 'generation_decision': scoped_decision()},
                                  {'units': [parent, child]}, 'child_region')


@pytest.mark.parametrize('source_kind', ['user', 'crop', 'external'])
def test_reference_generation_route_cannot_hide_generated_text_by_relabelling_image(source_kind):
    with pytest.raises(ValueError, match='requires generated image source'):
        bind_generated([scoped_material()], scoped_decision(), source_kind=source_kind)


def test_native_component_route_cannot_be_satisfied_by_user_image():
    with pytest.raises(ValueError, match='selected component route'):
        bind_generated([scoped_material(material_route='native')], scoped_decision(), source_kind='user')


@pytest.mark.parametrize('field', ['content_type', 'required_edit', 'text_ownership', 'embedded_text'])
def test_generated_output_cannot_drop_scope_declarations(field):
    decision = scoped_decision()
    del decision[field]
    with pytest.raises(ValueError, match='generated output'):
        bind_generated([scoped_material()], decision)


def test_generated_output_cannot_replace_original_text_with_weaker_legacy_decision():
    weak = {'basis': 'user_request', 'reference': 'input/art.png', 'reason': 'Direct generation'}
    with pytest.raises(ValueError, match='generated output'):
        bind_generated([scoped_material()], weak)
    changed = scoped_decision()
    changed['embedded_text'] = [{'text': 'CHANGED', 'legibility': 'readable'}]
    with pytest.raises(ValueError, match='embedded text'):
        bind_generated([scoped_material()], changed)


def test_legacy_scopes_without_component_declarations_keep_old_decisions():
    unit = {'id': 'old', 'region_id': 'region', 'owner_id': None, 'required_edit': 'image_replace'}
    assert bind_generated([unit], {'basis': 'user_request', 'reference': 'input/art.png',
                                  'reason': 'Historical direct generation'}) == set()


def test_parent_and_embedded_child_share_image_without_duplicate_text_checks():
    parent = scoped_material(content_type='decorative_title', text_ownership='asset_title')
    child = {'id': 'caption', 'region_id': 'region', 'owner_id': 'art',
             'required_edit': 'image_replace', 'text_ownership': 'embedded',
             'embedded_text': [{'text': 'ORIGINAL', 'legibility': 'readable', 'owner_unit_id': 'art'}]}
    decision = category(content_type='decorative_title', text_ownership='asset_title',
                        embedded_text=[{'text': 'ORIGINAL', 'legibility': 'readable', 'owner_unit_id': 'caption'}])
    assert bind_generated([child, parent], decision) == set()
    decision['embedded_text'][0]['owner_unit_id'] = 'unrelated'
    with pytest.raises(ValueError, match='unrelated component owner'):
        bind_generated([parent, child], decision)


def test_repeated_original_labels_within_one_material_are_not_collapsed():
    unit = scoped_material()
    unit['embedded_text'] *= 2
    with pytest.raises(ValueError, match='embedded text'):
        bind_generated([unit], scoped_decision())
    decision = scoped_decision()
    decision['embedded_text'] *= 2
    assert bind_generated([unit], decision) == set()


def test_regional_embedded_child_keeps_its_material_owners_declaration():
    from scripts.element_scope import validate_outputs
    parent = scoped_material(region_id='parent_region', content_type='decorative_title', text_ownership='asset_title')
    child = {'id': 'caption', 'region_id': 'child_region', 'owner_id': 'art',
             'required_edit': 'image_replace', 'text_ownership': 'embedded'}
    image = {'id': 'image', 'kind': 'image', 'source_kind': 'generated',
             'generation_decision': category(content_type='decorative_title', text_ownership='asset_title',
                                             embedded_text=parent['embedded_text'])}
    args = {'region_id': 'child_region', 'bindings': [{'unit_id': 'caption', 'object_ids': ['image']}]}
    assert validate_outputs({'units': [parent, child]}, [image], **args) == set()
    del image['generation_decision']['embedded_text']
    with pytest.raises(ValueError, match='embedded text'):
        validate_outputs({'units': [parent, child]}, [image], **args)
    image['generation_decision']['embedded_text'] = parent['embedded_text']
    image['source_kind'] = 'user'
    with pytest.raises(ValueError, match='requires generated image source'):
        validate_outputs({'units': [parent, child]}, [image], **args)


def test_material_text_advertised_schema_matches_runtime_rows(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    from scripts.task_contracts import constraints
    from scripts.material_text_review import CHECK_SCHEMA
    advertised = constraints('source_review', {})['material_text_checks_schema']
    row = [{'object_id': 'title', 'asset_sha256': 'a'*64, 'observed_text': ['TITLE']}]
    assert advertised == CHECK_SCHEMA
    assert jsonschema.Draft202012Validator(advertised).is_valid(row)


def test_native_container_accepts_independent_generated_material_with_own_text():
    from scripts.component_strategy import validate_generation_scope
    from scripts.element_scope import validate_plan, validate_outputs
    common = {'region_id': 'region', 'semantic_role': 'decoration', 'input_form': 'raster',
              'requirement': 'TEST component edit requirement', 'evidence': 'TEST source inspection',
              'counterevidence': 'TEST independently declared child material'}
    container = {**common, 'id': 'container', 'owner_id': None, 'required_edit': 'group',
                 'content_type': 'geometric_graphic', 'material_route': 'native'}
    material = {**common, **scoped_material(owner_id='container')}
    contract = {'version': 1, 'revision': 1, 'task_requirement': 'TEST layered composition',
                'units': [container, material]}
    assert validate_plan(contract, region_ids=['region']) == contract
    decision = scoped_decision()
    assert validate_generation_scope({'scope_unit_ids': ['art'], 'generation_decision': decision},
                                     contract, 'region') is None
    image = {'id': 'image', 'kind': 'image', 'source_kind': 'generated',
             'generation_decision': decision}
    objects = [{'id': 'group', 'kind': 'group', 'children': [image]}]
    bindings = [{'unit_id': 'container', 'object_ids': ['group']},
                {'unit_id': 'art', 'object_ids': ['image']}]
    assert validate_outputs(contract, objects, bindings=bindings) == set()
    image['generation_decision'] = {**decision, 'embedded_text': []}
    with pytest.raises(ValueError, match='embedded text'):
        validate_outputs(contract, objects, bindings=bindings)


def test_independent_materials_cannot_share_standalone_image_as_embedded_children():
    parent = scoped_material(required_edit='image_replace')
    child = scoped_material(id='child', owner_id='art')
    with pytest.raises(ValueError, match='containing group'):
        bind_generated([parent, child], scoped_decision())
