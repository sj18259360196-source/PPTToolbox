"""Current material guidance reaches searches, command defaults and public text."""
import json
import hashlib
import sys
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from scripts.rebuild_assistance import search
from scripts.experience_library import show, audit
from distribution.builtin_experience import entries


def test_default_native_search_retrieves_scoped_current_actions():
    for query in ('少色 插画 选区', '软管 中心线 七层', '透明餐盒 泵瓶 材质'):
        hits=search(query,external_root='')['matches']
        assert hits
        for hit in hits:
            if hit['id'] in {'EXP-163','EXP-164','EXP-207','EXP-208','EXP-209'}:
                assert any('当前组件已选择原生路线' in x for x in hit['constraints'])
    row=show('EXP-208',root=ROOT,external_root='')
    assert '图片生成优先时参考生成' in row['actions'][0]
    assert '可编辑绘制优先时保留真实原生部件' in row['actions'][0]
    assert '孔洞与连通变化阻止采用' in row['evidence'][0]['excerpt']


def test_material_text_ownership_does_not_require_ocr_textbox_conversion():
    row=show('EXP-062',root=ROOT,external_root='')
    assert '照片自带文字保留源像素' in ''.join(row['actions'])
    assert '不得擦去素材自带文字' in ''.join(row['constraints'])
    assert '可辨且承担正文功能的标签单独原生化' not in row['actions']


def test_real_command_defaults_and_explicit_user_disable_survive(tmp_path):
    from toolbox_manager.service import Manager
    manager=Manager(tmp_path/'data',root=ROOT,home=tmp_path/'home')
    row=next(x for x in manager.commands() if x['id']=='illustration-method-choice')
    assert row['builtin'] and '复杂素材可以直接请求生成' in row['body']
    manager.save_command({**row,'body':'用户自定指令','enabled':False})
    saved=next(x for x in manager.commands() if x['id']==row['id'])
    assert saved['body']=='用户自定指令' and not saved['enabled']
    native=next(x for x in manager.commands() if x['id']=='native_illustration_plan')
    assert '素材自带文字随素材保留' in native['body']


def test_public_default_text_includes_applicability_and_archive_integrity():
    defaults=ROOT/'assets/experience/defaults'
    text=(defaults/'sources/S38_原生绘图基础方法.md.txt').read_text('utf-8')
    assert '当前路线先于案例步骤' in text
    assert '照片按保真要求处理' in text
    assert '全局默认只供新项目取用' in text
    rows=[json.loads(line) for line in (defaults/'knowledge/experience-ledger.jsonl').read_text('utf-8').splitlines()]
    row=next(x for x in rows if x['id']=='EXP-208')
    assert '当前组件已选择原生路线' in row['evidence'][0]['excerpt']
    assert {r['id'] for r in rows}=={r['id'] for r in entries(ROOT)}
    assert audit(ROOT,external_root='')['status']=='passed'


def test_current_methods_and_commands_follow_selected_preferences(tmp_path):
    from toolbox_manager.service import Manager
    from toolbox_manager.illustration_guide import guide
    manager = Manager(tmp_path/'data', root=ROOT, home=tmp_path/'home')
    rows = {r['id']:r for r in entries(ROOT)}
    assert 'precise' in rows['EXP-034']['trigger']
    assert 'line' in rows['EXP-039']['trigger']
    assert 'generate_first' in rows['EXP-112']['trigger']
    assert not any('当前组件已选择原生路线' in s for s in rows['EXP-112']['constraints'])
    guidance = guide(manager, {})
    assert any('可编辑绘制优先' in r['when'] and '原生' in r['choose'] for r in guidance['classification'])
    commands = {r['id']:r for r in manager.commands()}
    route = commands['illustration-method-choice']['body']
    assert 'production_settings' in route and 'font_matching' in route and 'text_layout' in route
    assert '图片生成优先且符合对象要求时' in route
    paths = commands['scene_contract_preflight']['body']
    assert '1.1' in paths and 'path_base=project_root' in paths
    assert '1.0 继续按场景文件目录解释' in paths
    for row in rows.values():
        assert '复杂插画和复杂标题默认准备参考生图' not in ''.join(row['actions']+row['constraints'])


def test_old_external_import_keeps_actions_and_gets_current_read_only_context(tmp_path):
    from scripts.experience_library import load_library
    external=tmp_path/'external'; package=external/'imports/old'
    package.mkdir(parents=True)
    original=next(r for r in entries(ROOT) if r['id']=='EXP-208')
    old={**original,'actions':['旧版要求先做两条原生路线'],'constraints':['旧版限制']}
    (package/'sources.json').write_text('[]',encoding='utf-8')
    (package/'entries.json').write_text(json.dumps([old],ensure_ascii=False),encoding='utf-8')
    manual=package/old['manual'];manual.parent.mkdir(parents=True);manual.write_text('archived manual',encoding='utf-8')
    files={name:hashlib.sha256((package/name).read_bytes()).hexdigest() for name in ['sources.json','entries.json',old['manual']]}
    (package/'bundle.json').write_text(json.dumps({'format':'ppt-experience-import/1','new_ids':[],'files':files}),encoding='utf-8')
    raw=load_library(ROOT,external)[1]
    assert next(r for r in raw if r['id']=='EXP-208')['actions']==old['actions']
    result=show('EXP-208',root=ROOT,external_root=external)
    assert result['actions']==old['actions'] and result['evidence']==old['evidence']
    assert result['production_guidance']['policy']=='layered-material/2'
    assert '无需先绘制或填写相似度' in result['production_guidance']['guidance']
    found=search('少色 插画 选区',budget=12000,external_root=external)
    hit=next(r for r in found['matches'] if r['id']=='EXP-208')
    assert hit['actions']==old['actions']
    assert hit['constraints'][0].startswith('当前执行适用提示')
    assert found['production_guidance']==result['production_guidance']
    assert all('production_guidance' not in r for r in found['matches'])
    from toolbox_manager.source_experience import call
    listing=call(SimpleNamespace(root=ROOT,data=tmp_path), 'list', {'query':'选区'})
    assert listing['production_guidance']['policy']=='layered-material/2'
    assert all('production_guidance' not in r for r in listing['items'])
    state={'sources':[],'rows':[],'overrides':{'EXP-208':{'actions':['用户调整方法']}},'hidden':{'EXP-207':True}}
    # The guidance layer does not alter management overlays or resurrect hidden IDs.
    rows=load_library(ROOT,external,_management_state=state)[1]
    assert next(r for r in rows if r['id']=='EXP-208')['actions']==['用户调整方法']
    assert 'EXP-207' not in {r['id'] for r in rows}
