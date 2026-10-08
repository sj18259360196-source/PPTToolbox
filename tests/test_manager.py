"""Management-layer tests. No Office/Codex installation claims; tests use temporary homes."""
from __future__ import annotations
import io,json,os,sys,threading,zipfile,urllib.request,urllib.error,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox_manager.service import Manager, WORKFLOWS
from toolbox_manager import VERSION
from toolbox_manager.packages import inspect_zip
from toolbox_manager.storage import digest,redact
from toolbox_manager.server import LocalServer
from toolbox_manager.mcp import MCP, TOOLS
from toolbox_manager.icons.contracts import SPECS as ICON_SPECS
from toolbox_manager.graphics import SPECS as GRAPHICS_SPECS

@pytest.fixture
def manager(tmp_path):return Manager(tmp_path/'data',root=ROOT,home=tmp_path/'home')

def package_bytes(version='1.5.0',name='ppt-reference-rebuild',files=None,manifest=True):
    data={'SKILL.md':f'---\nname: {name}\ndescription: Test skill\nmetadata:\n  version: "{version}"\n---\n# Test\n'.encode(),'readme.txt':'中文文件名验证'.encode()}
    data.update(files or {})
    if manifest:data['MANIFEST.json']=json.dumps({'files':[{'path':n,'size':len(b),'sha256':digest(b)} for n,b in data.items()]},ensure_ascii=False).encode()
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for n,v in data.items():z.writestr('sample/'+n,v)
    return b.getvalue()

def expected_tool_count():
    from toolbox_manager.contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
    return len(json.loads((ROOT/'toolbox/registry.json').read_text(encoding='utf-8'))['tools']) + len(WORKFLOWS) + len(LOCAL_COMMANDS) + len(REQUEST_COMMANDS) + len(ICON_SPECS) + len(GRAPHICS_SPECS)


def test_boot_real_catalog(manager):
    r=manager.boot();assert r['counts']['tools']==expected_tool_count() and r['active']['version']==VERSION;assert r['version']==VERSION

def test_reopen_keeps_state(manager):
    manager.toggle('tool','assets.audit',False)
    other=Manager(manager.data,root=ROOT,home=manager.home)
    assert not next(x for x in other.catalog() if x['id']=='assets.audit')['enabled']


def test_catalog_observes_other_window_permission_changes(manager):
    other=Manager(manager.data,root=ROOT,home=manager.home)
    assert next(x for x in manager.catalog() if x['id']=='assets.audit')['enabled']
    other.toggle('tool','assets.audit',False)
    assert not next(x for x in manager.catalog() if x['id']=='assets.audit')['enabled']
    other.toggle('tool','assets.audit',True)
    assert next(x for x in manager.catalog() if x['id']=='assets.audit')['enabled']

def test_toggle_preserves_package_files(manager):
    p=ROOT/'toolbox/registry.json';before=p.read_bytes();manager.toggle('tool','assets.audit',False);assert p.read_bytes()==before

@pytest.mark.parametrize('enabled',['false',0,None,[]])
def test_toggle_rejects_wrong_boolean(manager,enabled):
    with pytest.raises(ValueError):manager.toggle('tool','assets.audit',enabled)

def test_invalid_tool_toggle(manager):
    with pytest.raises(ValueError):manager.toggle('tool','not-real',False)

def test_settings_revision_conflict(manager):
    s=manager.save_settings({'revision':0,'values':{'theme':'dark'}});assert s['revision']==1
    with pytest.raises(ValueError):manager.save_settings({'revision':0,'values':{'theme':'light'}})
    assert manager.settings()['theme']=='dark'

@pytest.mark.parametrize('values',[{'api_key':'secret'},{'theme':'bogus'},{'agent_execution_enabled':'true'},{'log_page_size':1},{'log_page_size':1001},{'update_channel':'auto'},{'python_path':'x\nmalicious'}])
def test_settings_reject_invalid(manager,values):
    with pytest.raises(ValueError):manager.save_settings({'revision':0,'values':values})

def test_overlay_save_read_restore(manager):
    doc=manager.document('SKILL.md');original=(ROOT/'SKILL.md').read_bytes();changed=doc['content']+'\n用户指令测试。\n'
    r=manager.save_document('SKILL.md',changed,0);assert r['revision']==1 and r['customized'];assert '用户指令测试' in manager.context()['skill']
    assert (ROOT/'SKILL.md').read_bytes()==original
    r=manager.save_document('SKILL.md','',1,restore_revision=0);assert r['content']==doc['base'];assert r['revision']==2

def test_overlay_conflict(manager):
    d=manager.document('SKILL.md');manager.save_document('SKILL.md',d['content']+'a',0)
    with pytest.raises(ValueError):manager.save_document('SKILL.md',d['content']+'b',0)

@pytest.mark.parametrize('path',['../README.md','/etc/passwd','scripts/build_pptx.py','toolbox/registry.json'])
def test_doc_allowlist(manager,path):
    with pytest.raises(ValueError):manager.document(path)

def test_readonly_doc_cannot_save(manager):
    with pytest.raises(ValueError):manager.save_document('README.md','x',0)

def test_custom_command_not_execute(manager,tmp_path):
    out=tmp_path/'not-created';r=manager.save_command({'title':'Command','body':f'touch {out}'})
    assert not out.exists();assert manager.context()['instructions'][0]['id']==r['id']
    manager.save_command({'id':r['id'],'title':'Command','body':'x','revision':1,'enabled':False});assert not manager.context()['instructions']

def test_command_conflict(manager):
    r=manager.save_command({'title':'one','body':'text'})
    with pytest.raises(ValueError):manager.save_command({'id':r['id'],'title':'two','body':'text','revision':0})

def test_import_nonexecuting_default_untrusted(manager,tmp_path):
    marker=tmp_path/'never'
    plan=manager.prepare_import(package_bytes(files={'install.py':f'open({str(marker)!r},"w").write("x")'.encode()}))
    r=manager.commit_import(plan['confirm_id']);assert not r['enabled'] and not r['trusted'] and not marker.exists()
    with pytest.raises(ValueError):manager.activate(r['id'])

def imported(manager):
    r=manager.commit_import(manager.prepare_import(package_bytes())['confirm_id']);manager.trust(r['id'],True);manager.toggle('package','',True,r['id']);return r

def test_version_activate_and_rollback(manager):
    r=imported(manager);manager.activate(r['id']);assert manager.package()['version']=='1.5.0'
    manager.activate('builtin');assert manager.package()['version']==VERSION;assert len(manager.versions()['history'])==2

def test_import_tampering_rejected(manager):
    r=imported(manager);(Path(r['path'])/'readme.txt').write_text('changed')
    with pytest.raises(ValueError):manager.activate(r['id'])

def test_duplicate_import_rejected(manager):
    manager.commit_import(manager.prepare_import(package_bytes())['confirm_id'])
    with pytest.raises(ValueError):manager.commit_import(manager.prepare_import(package_bytes())['confirm_id'])

def test_update_token_once(manager):
    p=manager.prepare_import(package_bytes());manager.commit_import(p['confirm_id'])
    with pytest.raises(ValueError):manager.commit_import(p['confirm_id'])

def test_overlay_version_isolation(manager):
    d=manager.document('SKILL.md');manager.save_document('SKILL.md',d['content']+'\ncustom',0)
    r=imported(manager);manager.activate(r['id']);assert 'custom' not in manager.context()['skill']
    manager.activate('builtin');assert 'custom' in manager.context()['skill']

@pytest.mark.parametrize('name',['../escape','sample/../../escape','/absolute','sample\\oops','sample/CON.txt','sample/name.','sample/foo:bar','sample/./bad'])
def test_unsafe_zip_paths(name):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr(name,b'x')
    with pytest.raises(ValueError):inspect_zip(b.getvalue())

def test_case_collision_zip():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('sample/A.txt','x');z.writestr('sample/a.txt','x')
    with pytest.raises(ValueError):inspect_zip(b.getvalue())

def test_zip_symlink():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        info=zipfile.ZipInfo('sample/link');info.external_attr=0o120777<<16;z.writestr(info,'/etc/passwd')
    with pytest.raises(ValueError):inspect_zip(b.getvalue())

def test_zip_hash_reject():
    b=io.BytesIO(package_bytes());out=io.BytesIO()
    with zipfile.ZipFile(b) as z,zipfile.ZipFile(out,'w') as target:
        for i in z.infolist():target.writestr(i,z.read(i) if not i.filename.endswith('readme.txt') else b'changed')
    with pytest.raises(ValueError):inspect_zip(out.getvalue())

def test_no_manifest_is_reported():
    assert inspect_zip(package_bytes(manifest=False))['integrity']=='unmanifested'

def test_implicit_trust_rejected(manager):
    with pytest.raises(ValueError):manager.trust('builtin',False)

def test_settings_no_automatic_execution(manager):
    manager.save_settings({'revision':0,'values':{'python_path':'/no/such/python'}})
    assert manager.diagnostic('registry')['status']=='failed'

def test_execute_disabled(manager):
    with pytest.raises(ValueError):manager.execute('assets.audit',[])

def test_execute_registered_help_only(manager):
    manager.save_settings({'revision':0,'values':{'agent_execution_enabled':True}})
    r=manager.execute('assets.audit',['--help']);assert r['returncode']==0 and 'usage' in r['stdout']
    assert any(l['source']=='cli' for l in manager.store.logs())

def test_execute_respects_tool_disable(manager):
    manager.save_settings({'revision':0,'values':{'agent_execution_enabled':True}});manager.toggle('tool','assets.audit',False)
    with pytest.raises(ValueError):manager.execute('assets.audit',['--help'])

def test_network_benchmark_gate(manager):
    manager.save_settings({'revision':0,'values':{'agent_execution_enabled':True}})
    with pytest.raises(ValueError):manager.execute('bench.run',['--help'])

def test_diagnostic_actual_registry(manager):
    r=manager.diagnostic('registry');assert r['status']=='passed'
    assert json.loads(r['stdout'])['registered_items']==len(json.loads((ROOT/'toolbox/registry.json').read_text(encoding='utf-8'))['tools'])

@pytest.mark.parametrize('name',['run-shell','delete','install','benchmark'])
def test_diagnostic_allowlist(manager,name):
    with pytest.raises(ValueError):manager.diagnostic(name)

def test_logs_redact():
    r=redact({'api_key':'secret','nested':{'authorization':'Bearer A'},'text':'sk-abcdefghijklmnop url?token=hello'})
    assert r['api_key']=='[REDACTED]' and 'abcdefghijklmnop' not in r['text'] and 'hello' not in r['text']

def test_export_only_allowlisted(manager):
    out=manager.export_data();p=manager.export_file(out['file_id']);assert p.is_file() and p.suffix=='.json'
    with pytest.raises(ValueError):manager.export_file('../../etc/passwd')

def test_integration_generate_not_modify_home(manager):
    r=manager.export_integration();assert manager.export_file(r['file_id']).is_file();assert not (manager.home/'.codex/config.toml').exists();assert not (manager.home/'.agents/plugins/marketplace.json').exists()

def test_integration_describes_governed_writes_without_granting_them(manager):
    from toolbox_manager.integrations import config_for,wrapper_skill
    cfg=config_for(manager);text=wrapper_skill(manager)
    assert cfg["manifest"]["interface"]["capabilities"]==["Read","Write"]
    assert "rebuild_start/next/submit/status/revise/finish" in text
    assert "rebuild_probe/patch/compare/adopt" in text
    assert "MCP没有生图或Office执行能力" not in text
    assert "MCP 仅暴露发现" not in "".join(cfg["notes"])
    assert not manager.settings()["agent_execution_enabled"]
    assert manager.store.get("project_grants",{})=={}

def test_generated_plugin_targets_exact_runtime_and_data(manager,tmp_path):
    from toolbox_manager.integrations import write_plugin
    dest=tmp_path/"plugin";write_plugin(manager,dest)
    manifest=json.loads((dest/".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    cfg=json.loads((dest/".mcp.json").read_text(encoding="utf-8"))
    assert manifest["mcpServers"]=="./.mcp.json"
    assert set(cfg)=={"mcpServers"}
    assert cfg["mcpServers"]["ppt_toolbox_manager"]["args"]==[str(ROOT/"manager.py"),"--data-dir",str(manager.data),"mcp"]
    assert manifest["author"]["name"] and manifest["interface"]["developerName"]
    assert manifest["interface"]["longDescription"] and manifest["interface"]["defaultPrompt"]
    assert not (manager.home/".codex/config.toml").exists()

def test_registration_preserve_other_entries_and_backup(manager):
    path=manager.home/'.agents/plugins/marketplace.json';path.parent.mkdir(parents=True);old={'name':'mine','plugins':[{'name':'other','source':'./plugins/other'}],'custom':'retain'};path.write_text(json.dumps(old))
    p=manager.register_plan();assert p['preserved_other_entries']==1 and 'other' in path.read_text()
    r=manager.register_apply(p['confirm_id']);now=json.loads(path.read_text());assert now['custom']=='retain' and now['plugins'][0]==old['plugins'][0]
    assert Path(r['backup']).read_text()==json.dumps(old);assert r['state']=='source_registered_host_not_verified'
    assert not (manager.home/'.codex/config.toml').exists()

def test_registration_conflict(manager):
    p=manager.register_plan();path=Path(p['target']);path.parent.mkdir(parents=True);path.write_text('{}')
    with pytest.raises(ValueError):manager.register_apply(p['confirm_id'])

def test_mcp_handshake_and_read_policy(manager):
    m=MCP(manager.data,root=ROOT,home=manager.home)
    assert 'error' in m.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})
    r=m.handle({'jsonrpc':'2.0','id':2,'method':'initialize','params':{'protocolVersion':'2025-11-25'}});assert r['result']['protocolVersion']=='2025-11-25'
    from toolbox_manager.contracts import COMMANDS
    tools=m.handle({'jsonrpc':'2.0','id':3,'method':'tools/list'})['result']['tools']
    assert len(tools)==(len(TOOLS)+1)+len(COMMANDS)+len(ICON_SPECS)+len(GRAPHICS_SPECS)
    assert next(t for t in tools if t['name']=='toolbox_learning')['annotations']['readOnlyHint']
    manager.toggle('tool','assets.audit',False)
    r=m.handle({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'toolbox_describe','arguments':{'id':'assets.audit'}}});assert r['result']['isError']

def test_mcp_disabled_package(manager):
    m=MCP(manager.data,root=ROOT,home=manager.home);manager.toggle('package','',False)
    with pytest.raises(ValueError):m.call('toolbox_context',{})

def test_mcp_stdio_subprocess(manager):
    payload='\n'.join(json.dumps(x) for x in [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/list'}])+'\n'
    r=subprocess.run([sys.executable,str(ROOT/'manager.py'),'--data-dir',str(manager.data),'mcp'],input=payload,capture_output=True,text=True,encoding='utf-8',timeout=20)
    from toolbox_manager.contracts import COMMANDS
    assert r.returncode==0;lines=[json.loads(x) for x in r.stdout.splitlines()];assert len(lines)==2 and len(lines[1]['result']['tools'])==(len(TOOLS)+1)+len(COMMANDS)+len(ICON_SPECS)+len(GRAPHICS_SPECS)

@pytest.fixture
def server(manager):
    s=LocalServer(manager.data,token='test-session',root=ROOT,home=manager.home);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    yield s
    s.shutdown();s.server_close();t.join()

def request(server,path,body=None,auth=True,headers=None):
    h={'Authorization':'Bearer test-session'} if auth else {};h.update(headers or {})
    if body is not None:h['Content-Type']='application/json'
    req=urllib.request.Request(server.origin+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
    return urllib.request.urlopen(req,timeout=10)

def test_http_api_auth(server):
    with pytest.raises(urllib.error.HTTPError) as e:request(server,'/api/boot',auth=False)
    assert e.value.code==401
    assert json.load(request(server,'/api/boot'))['result']['counts']['tools']==expected_tool_count()

def test_http_cross_origin_blocked(server):
    with pytest.raises(urllib.error.HTTPError) as e:request(server,'/api/boot',headers={'Origin':'https://evil.invalid'})
    assert e.value.code==403

def test_http_invalid_host_blocked(server):
    with pytest.raises(urllib.error.HTTPError) as e:request(server,'/api/boot',headers={'Host':'evil.invalid'})
    assert e.value.code==403

def test_http_no_shell_endpoint(server):
    with pytest.raises(urllib.error.HTTPError):request(server,'/api/execute',body={'command':'echo x'})

def test_http_static_native_ui(server):
    data=request(server,'/',auth=False).read().decode();assert 'PPT Toolbox' in data and 'canvas' not in data
    assert 'frame-ancestors' in request(server,'/',auth=False).headers['Content-Security-Policy']

def test_http_save_settings_real(server):
    json.load(request(server,'/api/settings.save',{'revision':0,'values':{'theme':'dark'}}));assert json.load(request(server,'/api/settings'))['result']['theme']=='dark'

def test_manager_start_without_site_packages(manager):
    r=subprocess.run([sys.executable,'-S',str(ROOT/'manager.py'),'--data-dir',str(manager.data),'context'],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert r.returncode==0 and json.loads(r.stdout)['active']['name']=='ppt-reference-rebuild'


def test_workflow_registered_and_executable(manager):
    manager.save_settings({'revision':0,'values':{'agent_execution_enabled':True}})
    r=manager.execute('workflow.next',['--help']);assert r['returncode']==0 and '--project' in r['stdout']

def test_blocked_execution_logged(manager):
    with pytest.raises(ValueError):manager.execute('assets.audit',[])
    assert manager.store.logs()[0]['action']=='tool.rejected'


def test_future_database_schema_not_silently_downgraded(manager):
    manager.store.set('schema_version',99)
    with pytest.raises(ValueError):Manager(manager.data,root=ROOT,home=manager.home)
    manager.store.set('schema_version',1)

def test_data_must_stay_outside_program():
    with pytest.raises(ValueError):Manager(ROOT/'data-should-not-be-created',root=ROOT)
    assert not (ROOT/'data-should-not-be-created').exists()


def test_source_view_is_readonly(manager):
    r=manager.source('assets.audit');assert 'def ' in r['content'];assert r['entry']=='scripts/assets_tool.py'

def test_source_unknown_entry_rejected(manager):
    with pytest.raises(ValueError):manager.source('../../etc/passwd')

def test_inactive_package_document_readable_without_trusting(manager):
    r=manager.commit_import(manager.prepare_import(package_bytes())['confirm_id'])
    assert manager.document('SKILL.md',r['id'])['content'].endswith('# Test\n')
    assert not manager.package(r['id'])['trusted']
