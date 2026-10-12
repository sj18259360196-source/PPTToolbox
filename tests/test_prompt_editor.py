from pathlib import Path
import pytest
from toolbox_manager.service import Manager
from toolbox_manager.prompt_editor import PATH, MARKER
from toolbox_manager.prompt_modes import BRIEF_PATH, LIMIT, MODE_KEY
from toolbox_manager.server import READS, WRITES

@pytest.fixture
def manager(tmp_path,monkeypatch):
    root=tmp_path/'app';root.mkdir()
    (root/'SKILL.md').write_text('version: "1.3.1"\n',encoding='utf-8')
    (root/PATH).write_text('默认制作要求\n'+MARKER,encoding='utf-8')
    (root/'references').mkdir()
    (root/BRIEF_PATH).write_text((Path(__file__).parents[1]/BRIEF_PATH).read_text(encoding='utf-8'),encoding='utf-8')
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'host'))
    return Manager(tmp_path/'data',root=root,home=tmp_path/'home')

def save(m,text,state=None):
    state=state or m.call('prompt.read',{})
    return m.call('prompt.save',dict(content=text,revision=state['revision'],package_id=state['package_id']))

def test_read_and_copy_do_not_mutate_or_create_project(manager,tmp_path):
    m=manager;before=m.settings()
    a=m.call('prompt.read',{});b=m.call('prompt.read',{})
    assert a==b and a['revision']==0 and not a['history']
    assert MARKER not in a['text'] and MARKER not in a['content']
    assert m.settings()==before
    assert a['paths']['toolbox_root'] in a['text']
    with m.store.db() as db:assert db.execute('SELECT count(*) FROM docs').fetchone()[0]==0

def test_save_conflict_and_restore_history(manager):
    m=manager;original=m.call('prompt.read',{})
    one=save(m,'保持语义可编辑')
    assert one['revision']==1 and one['history'][0]['revision']==0
    with pytest.raises(ValueError,match='另一窗口'):save(m,'stale',original)
    two=save(m,'新要求')
    old=m.call('prompt.history',{'revision':0})
    assert '默认制作要求' in old['content']
    restored=m.call('prompt.restore',{'revision':two['revision'],'package_id':two['package_id'],'restore_revision':1})
    assert restored['content']=='保持语义可编辑' and restored['revision']==3
    assert len(restored['history'])==3
    with pytest.raises(ValueError,match='工具包'):m.call('prompt.save',{'revision':3,'package_id':'wrong','content':'x'})

def test_live_paths_and_context_use_saved_prompt(manager,tmp_path):
    m=manager;save(m,'用户定制要求')
    for name in ['项目旧目录','项目新目录']:
        target=str(tmp_path/name);Path(target).mkdir();settings=m.settings()
        m.save_settings({'values':{'projects_directory':target},'revision':settings['revision']})
        live=m.call('prompt.read',{})
        assert target in live['text'] and live['content']=='用户定制要求'
        assert live['creation_instruction']==f'在 {target} 下创建一个新的项目目录，名称按参考图主题和当前日期生成。'
        assert live['creation_instruction'] in live['text']
        assert not list(Path(target).iterdir())
    assert str(tmp_path/'项目旧目录') not in live['text']
    assert live['revision']==1
    assert '用户定制要求' in m.context()['startup_prompt']

def test_default_and_historical_zero_are_distinct(manager):
    m=manager;one=save(m,'定制')
    (m.root/PATH).write_text('新版默认\n'+MARKER,encoding='utf-8')
    assert m.call('prompt.read',{})['base_changed']
    old=m.call('prompt.restore',{'revision':1,'package_id':one['package_id'],'restore_revision':0})
    assert old['content']=='默认制作要求'
    default=m.call('prompt.default',{'revision':2,'package_id':one['package_id']})
    assert default['content']=='新版默认' and default['revision']==3

@pytest.mark.parametrize('text',['','   ','x'*250001],ids=['empty','whitespace','oversize'])
def test_invalid_save_keeps_prior_revision(manager,text):
    with pytest.raises(ValueError):save(manager,text)
    assert manager.call('prompt.read',{})['revision']==0

def test_routes():
    assert {'prompt.read','prompt.history'}<=READS
    assert {'prompt.save','prompt.restore','prompt.default','prompt.mode'}<=WRITES


def test_modes_share_requirements_and_persist_only_preference(manager):
    from toolbox_manager.production_storage import startup_prompt
    state=save(manager,'独立要求 ABC，不得省略')
    assert state['text']==startup_prompt(manager)['text']
    assert state['mode']=='concise'
    short=state['concise']
    assert short['chars']==len(short['text'])<=LIMIT
    assert all(path in short['text'] for path in state['paths'].values())
    assert BRIEF_PATH in short['text'] and 'rebuild_start' in short['text']
    with manager.store.db() as db:
        before=[tuple(row) for row in db.execute('SELECT * FROM docs')]
    manager.call('prompt.mode',{'mode':'professional'})
    reopened=Manager(manager.data,root=manager.root,home=manager.home)
    after=reopened.call('prompt.read',{})
    assert after['mode']=='professional'
    assert after['revision']==state['revision'] and after['content']==state['content']
    assert reopened.settings()==manager.settings()
    with reopened.store.db() as db:
        assert before==[tuple(row) for row in db.execute('SELECT * FROM docs')]
    for bad in ['full','',None,{},True]:
        with pytest.raises(ValueError):manager.call('prompt.mode',{'mode':bad})
    assert manager.store.get(MODE_KEY)=='professional'


def test_guide_reads_latest_overrides_settings_paths_and_is_readonly(manager,tmp_path):
    from toolbox_manager.production_settings import save as save_settings
    from toolbox_manager.mcp import MCP
    save(manager,'用户完整要求 <特殊字符> 123')
    client=MCP(manager.data,root=manager.root,home=manager.home)
    assert BRIEF_PATH in [doc['path'] for doc in client.call('toolbox_manual',{})]
    first=client.call('toolbox_manual',{'path':BRIEF_PATH})
    assert first['generated'] and not first['editable']
    assert 'base' not in first and 'diff' not in first and 'history' not in first
    assert first['source']['revision']==1
    assert '用户完整要求 <特殊字符> 123' in first['content']
    assert manager.call('prompt.read',{})['text'] in first['content']
    with pytest.raises(ValueError,match='只读'):
        manager.save_document(BRIEF_PATH,'stale duplicate',first['revision'])
    target=tmp_path/'实际项目目录';target.mkdir()
    manager.save_settings({'revision':manager.settings()['revision'],'values':{'projects_directory':str(target)}})
    save_settings(manager,{'revision':0,'values':{'illustration_mode':'draw_first','font_matching':'precise','text_layout':'line'}})
    second=client.call('toolbox_manual',{'path':BRIEF_PATH})
    assert first['base_sha256']!=second['base_sha256']
    assert str(target) in second['content']
    assert '复杂插画优先语义拆分' in second['content']
    assert second['revision']==1 and not list(target.iterdir())
    saved=save(manager,'修订后的专属要求')
    third=client.call('toolbox_manual',{'path':BRIEF_PATH})
    assert third['revision']==saved['revision']==2
    assert '用户完整要求 <特殊字符> 123' not in third['content']
    assert '修订后的专属要求' in third['content']
    assert third==client.call('toolbox_manual',{'path':BRIEF_PATH})


def test_long_directories_use_context_without_truncation(manager):
    from toolbox_manager.prompt_modes import concise
    paths={key:'A:/'+('中文目录😀/'*600)+key for key in ['toolbox_root','management_root','default_projects_root']}
    result=concise(manager,paths)
    assert result['chars']==len(result['text'])<=LIMIT
    assert not result['inline_paths']
    assert 'instance 与 storage' in result['text']
    assert '中文目录' not in result['text'] and BRIEF_PATH in result['text']


def test_old_packages_without_guide_have_working_full_context_fallback(manager):
    (manager.root/BRIEF_PATH).unlink()
    short=manager.call('prompt.read',{})['concise']
    assert short['guide_path'] is None and short['chars']<=LIMIT
    assert BRIEF_PATH not in short['text']
    assert '"profile":"full"' in short['text'] and 'startup_prompt' in short['text']
