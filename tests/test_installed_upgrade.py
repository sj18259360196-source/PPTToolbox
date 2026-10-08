import hashlib,json,sqlite3
from pathlib import Path
import pytest
from distribution.update_installed import discover,upgrade,install_new
from toolbox_manager.service import Manager

@pytest.fixture
def installed(tmp_path):
    source=tmp_path/"bundle";dest=tmp_path/"installed";data=tmp_path/"data"
    for root,version in ((source,"1.8.2-icons"),(dest,"1.8.1-icons")):
        (root/"app").mkdir(parents=True)
        files={"app/PRODUCT.json":json.dumps({"product":"PPT Toolbox","version":version,"source_sha256":version}),
               "app/SKILL.md":'version: "1.3.1"',"app/example.txt":version,
               "runtime/python.exe":"runtime","PPTToolbox.exe":version,"portable.py":version}
        for name,value in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value,encoding="utf-8")
        (root/"FILES.json").write_text(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in files}))
    m=Manager(data,root=dest/"app")
    (tmp_path/"custom-projects").mkdir()
    m.save_settings({"revision":m.settings()["revision"],"values":{"projects_directory":str(tmp_path/"custom-projects")}})
    m.store.set("project_authorizations",{"test":{"write":True}})
    (dest/"location.json").write_text(json.dumps({"data_directory":str(data),"projects_directory":"stale-value"}))
    return source,dest,data

def state(data):
    with sqlite3.connect(data/"manager.sqlite3") as db:
        return db.execute("SELECT key,value FROM kv ORDER BY key").fetchall()

def test_update_preserves_location_settings_and_authorization(installed):
    src,dest,data=installed;before=state(data);location=(dest/"location.json").read_bytes()
    result=upgrade(src,dest,process_check=lambda _:[])
    assert result["status"]=="updated"
    assert state(data)==before
    assert (dest/"location.json").read_bytes()==location
    assert (dest/"app/example.txt").read_text()=="1.8.2-icons"
    assert (Path(result["backup"])/"files/app/example.txt").read_text()=="1.8.1-icons"
    assert upgrade(src,dest,process_check=lambda _:[])["status"]=="already_current"

def test_busy_update_keeps_files_and_data(installed):
    src,dest,data=installed;before=state(data)
    with pytest.raises(ValueError,match="占用"):
        upgrade(src,dest,process_check=lambda _:[123])
    assert state(data)==before
    assert (dest/"app/example.txt").read_text()=="1.8.1-icons"

def test_runtime_validation_failure_rolls_back(installed):
    src,dest,data=installed;before=state(data)
    def failed(_):raise RuntimeError("new runtime rejected")
    with pytest.raises(RuntimeError,match="rejected"):
        upgrade(src,dest,process_check=lambda _:[],validate=failed)
    assert state(data)==before
    assert (dest/"app/example.txt").read_text()=="1.8.1-icons"
    assert not (dest/"UPDATE_PENDING.json").exists()

def test_reinstall_restores_removed_program_and_keeps_data(installed):
    src,dest,data=installed
    upgrade(src,dest,process_check=lambda _:[])
    before=state(data);(dest/"runtime/python.exe").unlink()
    assert upgrade(src,dest,process_check=lambda _:[])["status"]=="updated"
    assert state(data)==before and (dest/"runtime/python.exe").exists()

def test_legacy_unresolved_call_preserved_without_blocking_update(installed):
    src,dest,data=installed
    m=Manager(data,root=dest/"app")
    m.store.event("tool.started","fixture",details={"call_id":"unknown"})
    before=state(data)
    with sqlite3.connect(data/'manager.sqlite3') as db:
        events=db.execute('SELECT * FROM events ORDER BY id').fetchall()
    result=upgrade(src,dest,process_check=lambda _:[])
    assert result['historical_calls_preserved']==[{'call_id':'unknown','project':None,'tool_id':None,'outcome':'unknown_preserved'}]
    assert state(data)==before
    with sqlite3.connect(data/'manager.sqlite3') as db:
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall()==events
    assert (dest/"app/example.txt").read_text()=="1.8.2-icons"

@pytest.mark.parametrize('alive', [True, None])
def test_live_or_uninspectable_call_blocks_update(installed, monkeypatch, alive):
    src,dest,data=installed
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'live','owner_pid':123})
    monkeypatch.setattr('toolbox_manager.execution.process_alive',lambda pid: alive)
    with pytest.raises(ValueError,match='调用仍在运行或无法确认'):
        upgrade(src,dest,process_check=lambda _:[])
    assert (dest/'app/example.txt').read_text()=='1.8.1-icons'

def test_dead_call_upgrade_preserves_project_and_unknown_result(installed, tmp_path, monkeypatch):
    src,dest,data=installed
    project=tmp_path/'中文项目'; (project/'workflow').mkdir(parents=True)
    (project/'workflow/state.json').write_text('{"operation":"interrupted"}',encoding='utf-8')
    (project/'original.pptx').write_bytes(b'original-content')
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'dead','owner_pid':123,'project':str(project)})
    monkeypatch.setattr('toolbox_manager.execution.process_alive',lambda pid: False)
    before={str(p):p.read_bytes() for p in project.rglob('*') if p.is_file()}
    result=upgrade(src,dest,process_check=lambda _:[])
    assert result['historical_calls_preserved'][0]['outcome']=='unknown_preserved'
    assert {str(p):p.read_bytes() for p in project.rglob('*') if p.is_file()}==before

def test_unregistered_pending_project_lock_blocks_update(installed,tmp_path,monkeypatch):
    src,dest,data=installed
    project=tmp_path/'locked';(project/'workflow').mkdir(parents=True)
    (project/'workflow/writer.lock').write_text('locked')
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'locked','project':str(project)})
    with pytest.raises(ValueError,match='写入锁'):
        upgrade(src,dest,process_check=lambda _:[])

def test_setup_preflight_accepts_legacy_history(installed,monkeypatch):
    from distribution import setup_helper
    _,dest,data=installed
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'legacy'})
    monkeypatch.setattr(setup_helper,'controllers',lambda _:[])
    setup_helper.stop_idle(dest)
    assert not (data/'UPDATE_REQUEST.json').exists()

def test_running_app_audit_still_blocks_legacy_history(installed):
    from distribution.update_installed import audit
    _,dest,data=installed
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'legacy'})
    with sqlite3.connect(data/'manager.sqlite3') as db:
        with pytest.raises(ValueError,match='未决'):
            audit(data,db)

def test_partial_events_retain_process_identity(installed,monkeypatch):
    src,dest,data=installed
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'partial','owner_pid':123})
    m.store.event('tool.authorized','fixture',details={'call_id':'partial','tool_id':'workflow.start'})
    monkeypatch.setattr('toolbox_manager.execution.process_alive',lambda pid: True)
    with pytest.raises(ValueError,match='partial'):
        upgrade(src,dest,process_check=lambda _:[])

def test_history_survives_failed_runtime_validation(installed):
    src,dest,data=installed
    m=Manager(data,root=dest/'app')
    m.store.event('tool.started','fixture',details={'call_id':'legacy'})
    before=state(data)
    with sqlite3.connect(data/'manager.sqlite3') as db:
        events=db.execute('SELECT * FROM events ORDER BY id').fetchall()
    def reject(_):raise RuntimeError('runtime rejected')
    with pytest.raises(RuntimeError,match='runtime rejected'):
        upgrade(src,dest,process_check=lambda _:[],validate=reject)
    assert state(data)==before
    with sqlite3.connect(data/'manager.sqlite3') as db:
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall()==events
    assert (dest/'app/example.txt').read_text()=='1.8.1-icons'

def test_custom_pointer_and_stale_pointer(installed,tmp_path):
    _,dest,_=installed;local=tmp_path/"local";local.mkdir()
    pointer=local/"PPTToolbox-installation.json";pointer.write_text(json.dumps({"installation":str(dest)}))
    assert discover(local)==dest
    pointer.write_text(json.dumps({"installation":str(tmp_path/"missing")}))
    with pytest.raises(ValueError,match="失效"):discover(local)

def test_fresh_install_selects_separate_paths(installed,tmp_path):
    src,_,_=installed
    dest=tmp_path/"new-install";data=tmp_path/"new-data";projects=tmp_path/"selected-projects"
    install_new(src,dest,data,projects,process_check=lambda _:[])
    m=Manager(data,root=dest/"app")
    assert m.settings()["projects_directory"]==str(projects)
    assert not m.settings()["agent_execution_enabled"]
    assert json.loads((dest/"location.json").read_text())["data_directory"]==str(data)

def test_failed_copy_rolls_back(installed,monkeypatch):
    src,dest,data=installed;before=state(data);write=Path.write_bytes
    def fail_once(self,content):
        if self==dest/"app/example.txt" and content==b"1.8.2-icons":
            raise OSError("fixture write failed")
        return write(self,content)
    monkeypatch.setattr(Path,"write_bytes",fail_once)
    with pytest.raises(OSError,match="fixture"):upgrade(src,dest,process_check=lambda _:[])
    assert (dest/"app/example.txt").read_text()=="1.8.1-icons"
    assert state(data)==before
    assert not (dest/"UPDATE_PENDING.json").exists()
