"""Public method defaults are searchable and do not replace owner overrides."""
import json
from test_tools import ROOT
from experience_library import audit,load_library

def test_default_library_is_valid():
    result=audit(root=ROOT)
    assert result['status']=='passed',result['issues']
    sources,rows,_=load_library(ROOT)
    ids={r['id'] for r in rows}
    assert {f'EXP-{i:03d}' for i in range(1,203)}<=ids
    if (ROOT/'PUBLIC_DISTRIBUTION.json').exists():
        marker=json.loads((ROOT/'PUBLIC_DISTRIBUTION.json').read_text('utf-8'))
        assert len(rows)==marker['builtin_method_count']
        assert len(sources)==1 and sources[0]['source_id']=='S38'
        assert all(r['origin']=='bundled_method_guidance' for r in rows)

def test_templates_include_current_managed_routes(tmp_path):
    from toolbox_manager.service import Manager
    manager=Manager(tmp_path/'data',root=ROOT,home=tmp_path/'home')
    recipes=json.loads((ROOT/'assets/experience/knowledge/command-recipes.json').read_text('utf-8'))['commands']
    bodies=' '.join(r['body'] for r in recipes)
    for route in ['graphics_construct','graphics_read_properties','graphics_boolean_trials','graphics_compare_contours','native.nodes']:
        assert route in bodies
    assert any('shape_operation_evidence'==r['id'] for r in recipes)
    row=next(r for r in manager.commands() if r['id']=='shape_operation_evidence')
    manager.save_command({**row,'body':'Owner customized body','enabled':False})
    current=next(r for r in manager.commands() if r['id']==row['id'])
    assert current['body']=='Owner customized body' and not current['enabled']
