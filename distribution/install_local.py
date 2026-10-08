"""Verified offline per-user installation and management-data migration.

Never relocate user PPT project folders or widen grants. Running controllers must
be closed first; no application/Office process is killed by this installer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import re
import tomllib
from datetime import datetime, timezone

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolbox_manager import storage_fence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_locations():
    local = Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))
    return {'installation':str(local/'Programs/PPTToolbox'),
            'data':str(local/'PPTToolbox'),
            'projects':str(Path.home()/'Documents/PPTToolbox/Projects')}


def no_reparse(path):
    raw=Path(path).expanduser().absolute()
    for p in [raw,*raw.parents]:
        if p.exists() or p.is_symlink():
            info=p.lstat()
            if p.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('Linked paths are not accepted: '+str(p))
    return raw.resolve()


def controllers(paths):
    if os.name!='nt':return []
    script="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\\.exe$' } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    shell=Path('C:/Program Files/PowerShell/7/pwsh.exe')
    p=subprocess.run([str(shell) if shell.is_file() else 'powershell.exe','-NoProfile','-Command',script],
                     capture_output=True,encoding='utf-8',check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    rows=json.loads(p.stdout or '[]');rows=[rows] if isinstance(rows,dict) else rows
    needles=[str(x).casefold() for x in paths]
    def parked_bridge(row):
        command=(row.get('CommandLine') or '').casefold()
        if 'agent_bridge.py' not in command:return False
        for path in paths:
            marker=Path(path)/'mcp-bridges'/f"{row['ProcessId']}.json"
            try:
                value=json.loads(marker.read_text(encoding='utf-8'))
                if value.get('parked') is True and value.get('pid')==row['ProcessId'] and str(value['installation']).casefold() in command:
                    return True
            except (OSError,ValueError,KeyError):pass
        return False
    return [r['ProcessId'] for r in rows if r['ProcessId']!=os.getpid()
            and any(n in (r.get('CommandLine') or '').casefold() for n in needles) and not parked_bridge(r)]


def codex_patch(path, destination):
    """Prepare only the named server edit; unrelated configuration stays identical."""
    path=Path(path)
    before=path.read_text(encoding='utf-8') if path.exists() else ''
    original=tomllib.loads(before)
    entry=original.get('mcp_servers',{}).get('ppt_toolbox_manager')
    if entry:
        command=Path(entry.get('command',''))
        product=command.parent.parent/'app/PRODUCT.json'
        if not product.is_file() or json.loads(product.read_text('utf-8')).get('product')!='PPT Toolbox':
            raise ValueError('Existing PPT MCP registration is not this product; inspect before replacing')
    cleaned=re.sub(r'(?ms)^\[mcp_servers\.ppt_toolbox_manager\][^\n]*\n.*?(?=^\[|\Z)', '', before)
    # Nested environment/custom subtables require explicit review, not a guessed rewrite.
    if 'ppt_toolbox_manager' in tomllib.loads(cleaned).get('mcp_servers',{}):
        raise ValueError('Nonstandard PPT registration requires manual review')
    server={'command':str(destination/'runtime/python.exe'),'args':['-B',str(destination/'portable.py'),'mcp'],'enabled':True}
    text=cleaned.rstrip()+'\n\n[mcp_servers.ppt_toolbox_manager]\n'
    text+='command = '+json.dumps(server['command'])+'\nargs = '+json.dumps(server['args'])+'\nenabled = true\n'
    after=tomllib.loads(text);after['mcp_servers'].pop('ppt_toolbox_manager')
    previous=dict(original);previous['mcp_servers']=dict(previous.get('mcp_servers',{}));previous['mcp_servers'].pop('ppt_toolbox_manager',None)
    assert after==previous,'Unrelated configuration change refused'
    return before,text


def install(bundle,destination,source_data,data,projects,process_check=controllers,codex_config=None,
            active_pointer=None):
    if any(not Path(p).expanduser().is_absolute() for p in (bundle,destination,source_data,data,projects)):
        raise ValueError('Choose absolute directory paths')
    bundle,destination,source_data,data,projects=map(no_reparse,(bundle,destination,source_data,data,projects))
    if (source_data/'MIGRATION_PENDING.json').exists():
        raise ValueError('Source migration is incomplete; use the original authoritative data')
    source_db=no_reparse(source_data/'manager.sqlite3')
    if not source_db.is_file():
        raise ValueError('Source requires an initialized manager.sqlite3; a database-free source cannot be write-fenced. '
                         'First launch PPTToolbox.exe without --setup, using --data-dir with this source directory, '
                         'to initialize it once. Then fully exit the toolbox background process, stop its Agent service, '
                         'and retry --setup with the same source directory.')
    if active_pointer is not None:
        if not Path(active_pointer).expanduser().is_absolute():
            raise ValueError('Active pointer must use an absolute path')
        active_pointer=no_reparse(active_pointer)
        if any(active_pointer.is_relative_to(root) for root in (bundle,destination,source_data,data,projects)):
            raise ValueError('Active pointer must be separate from program, management data and project directories')
    if destination!=bundle and ((destination.exists() and (not destination.is_dir() or any(destination.iterdir()))) or destination.is_relative_to(bundle) or bundle.is_relative_to(destination)):
        raise ValueError('Choose a new installation directory; existing files are never overwritten')
    if data==source_data and destination!=bundle:
        raise ValueError('Choose a new data directory when moving an installation')
    if data!=source_data and data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise ValueError('Choose a new data directory; existing data is never overwritten')
    if data!=source_data and (data.is_relative_to(source_data) or source_data.is_relative_to(data)):
        raise ValueError('Source and destination data directories must not contain each other')
    if destination!=bundle and (destination.is_relative_to(source_data) or source_data.is_relative_to(destination)):
        raise ValueError('Installation must not contain the original management data')
    for p in (data,projects):
        if any(p==root or p.is_relative_to(root/'app') or p.is_relative_to(root/'runtime') or root.is_relative_to(p)
               for root in (bundle,destination)):
            raise ValueError('Data and projects must be separate from program files')
    if projects==data or projects.is_relative_to(data) or data.is_relative_to(projects):
        raise ValueError('Project storage and management data must be separate')
    active=process_check([bundle,source_data,destination,data])
    if active:raise ValueError('Close toolbox windows and reconnect/stop its Agent service before migration. Active process IDs: '+str(active))
    config_change=codex_patch(codex_config,destination) if codex_config is not None else None
    manifest=json.loads((bundle/'FILES.json').read_text('utf-8'))
    if not {'PPTToolbox.exe','portable.py','runtime/python.exe','app/PRODUCT.json'} <= set(manifest):
        raise ValueError('Incomplete distribution manifest')
    for name,h in manifest.items():
        p=no_reparse(bundle/name)
        if not p.is_relative_to(bundle) or not p.is_file() or sha(p)!=h:raise ValueError('Package hash mismatch: '+name)
    if (source_data/'RETIRED.json').exists():raise ValueError('Source data is retired; select the current data directory')
    def audit(c):
        if (source_data/'MIGRATION_PENDING.json').exists() or (source_data/'RETIRED.json').exists():
            raise ValueError('Source data is pending migration or retired')
        if c is not None:
            active={}
            for action,body in c.execute("select action,details from events order by id"):
                d=json.loads(body);cid=d.get('call_id')
                if not cid:continue
                if action in ('tool.finished','tool.reconciled'):active.pop(cid,None)
                elif action in ('tool.started','tool.authorized','tool.launched'):active[cid]=d
            if active:raise ValueError('Unresolved calls block migration; inspect their outcomes first')
            registered=c.execute("select value from kv where key='workbench_projects'").fetchone()
            for row in (json.loads(registered[0]) if registered else {}).values():
                if (Path(row['path'])/'workflow/writer.lock').exists():
                    raise ValueError('A registered project writer lock blocks migration')
        if (source_data/'office-writer.lock').exists():raise ValueError('Office writer lock blocks migration')
    owner = storage_fence.acquire(source_db, audit)
    try:
        return _install(bundle,destination,source_data,data,projects,process_check,codex_config,
                        config_change,manifest,owner,active_pointer)
    except BaseException:
        if owner is not None:
            storage_fence.release(source_db, owner)
        raise


def _install(bundle,destination,source_data,data,projects,process_check,codex_config,
             config_change,manifest,owner,active_pointer=None):
    source_db=source_data/'manager.sqlite3'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if destination!=bundle:
        destination.mkdir(parents=True,exist_ok=True)
        for name in [*manifest,'FILES.json']:
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(bundle/name,target)
    data.mkdir(parents=True,exist_ok=True)
    pending=data/'MIGRATION_PENDING.json'
    pending.write_text(json.dumps({'source_data':str(source_data),'started':stamp}),encoding='utf-8')
    if data!=source_data and source_data.exists():
        for p in source_data.rglob('*'):
            no_reparse(p)
            if not p.is_file() or p.name in ('manager.sqlite3','manager.sqlite3-wal','manager.sqlite3-shm','MIGRATION_PENDING.json'):continue
            target=data/p.relative_to(source_data);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
            assert sha(p)==sha(target),'Data copy hash mismatch'
        if source_db.exists():
            with sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True) as src:
                with sqlite3.connect(data/'manager.sqlite3') as dst:src.backup(dst)
            storage_fence.release(data/'manager.sqlite3', owner)
    backup=None
    if (data/'manager.sqlite3').exists():
        backup=data/('migration-backup-'+stamp+'.sqlite3')
        with sqlite3.connect(data/'manager.sqlite3') as src:
            with sqlite3.connect(backup) as dst:src.backup(dst)
    projects.mkdir(parents=True,exist_ok=True)
    # Existing project paths and grants are retained. This preference applies to new projects only.
    if (data/'manager.sqlite3').exists():
        context = (storage_fence.maintenance(source_db, owner) if data==source_data and owner
                   else storage_fence.transaction(data/'manager.sqlite3'))
        with context as c:
            raw=c.execute("select value from kv where key='settings'").fetchone()
            if raw:
                settings=json.loads(raw[0]);settings['projects_directory']=str(projects);settings['revision']+=1
                c.execute("update kv set value=? where key='settings'",(json.dumps(settings),))
            c.execute("delete from kv where key='desktop_runtime'")
    location={'data_directory':str(data),'projects_directory':str(projects),'installed_at':stamp}
    if process_check([bundle,source_data,destination,data]):
        raise ValueError('A controller reopened during migration; original data remains authoritative')
    report={'status':'installed','installation':str(destination),'data_directory':str(data),
            'projects_directory':str(projects),'existing_project_paths_unchanged':True,
            'database_backup':str(backup) if backup else None,'source_data_preserved':True,
            'mcp_registration':'updated_named_server_only' if config_change else 'requires_current_host_path_update'}
    published=[]
    def publish(path, text):
        old=path.read_bytes() if path.exists() else None
        published.append((path,old))
        path.write_text(text,encoding='utf-8')
    try:
        publish(destination/'location.json',json.dumps(location,indent=2))
        if config_change is not None:
            config=Path(codex_config)
            if (config.read_text('utf-8') if config.exists() else '')!=config_change[0]:
                raise ValueError('Host configuration changed during migration; do not overwrite')
            config.parent.mkdir(parents=True,exist_ok=True)
            publish(config,config_change[1])
        if active_pointer is not None:
            active_pointer.parent.mkdir(parents=True,exist_ok=True)
            publish(active_pointer,json.dumps(report,indent=2))
        if data!=source_data and source_data.exists():
            if owner is not None:
                storage_fence.retire(source_db,owner,data)
            publish(source_data/'RETIRED.json',json.dumps({'canonical_data':str(data),'retired_at':stamp}))
        (data/('installation-'+stamp+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        pending.unlink()
        if data==source_data and owner is not None:
            storage_fence.release(source_db,owner)
    except BaseException:
        for path,old in reversed(published):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old)
        raise
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('bundle','destination','source-data','data','projects'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--codex-config',type=Path)
    parser.add_argument('--active-pointer',type=Path)
    parser.add_argument('--first-install',action='store_true')
    args=parser.parse_args()
    try:
        if args.first_install:
            from distribution.update_installed import install_new
            if args.source_data.exists() and any(args.source_data.iterdir()):
                raise ValueError('原管理数据目录非空，请使用迁移并保留其数据')
            result=install_new(args.bundle,args.destination,args.data,args.projects,
                               codex_config=args.codex_config,active_pointer=args.active_pointer)
        else:
            result=install(args.bundle,args.destination,args.source_data,args.data,args.projects,
                           codex_config=args.codex_config,active_pointer=args.active_pointer)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)
