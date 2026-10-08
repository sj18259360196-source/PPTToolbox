"""Discover executable scripts, PowerPoint module commands, host tools and manuals.
Registry entries are data, never arbitrary shell code. Module/host abilities are NOT CLI-implemented.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from runtime_env import powershell_path, child_environment, python_tool_argv

ROOT=Path(__file__).resolve().parents[1]


def entries():
    data=json.loads((ROOT/'toolbox/registry.json').read_text(encoding='utf-8'))
    if data.get('format')!='ppt-toolbox/1.2':raise ValueError('Unsupported tool registry format')
    rows=data['tools'];names=[r['id'] for r in rows]
    if len(names)!=len(set(names)):raise ValueError('Duplicate tool ID')
    return rows


def _local(relative):
    p=(ROOT/relative).resolve()
    if not p.is_relative_to(ROOT) or not p.is_file():raise ValueError('Registry entry path is missing or unsafe: '+relative)
    return p


def available(row):
    if row['kind']=='host':return 'host_discovery_required'
    _local(row['entry'])
    if row['kind'] in {'powershell','powershell_module'}:
        if os.name!='nt' or not powershell_path():return 'requires_windows_powershell'
        return 'available_path_office_not_probed'
    if row['kind']=='manual':return 'readable'
    return 'script_available_dependencies_not_probed'


def listing(query=''):
    rows=entries();q=query.casefold()
    return [{'id':r['id'],'title':r['title'],'kind':r['kind'],'availability':available(r)} for r in rows
            if not q or q in json.dumps(r,ensure_ascii=False).casefold()]


def show(name):
    row=next((r for r in entries() if r['id']==name),None)
    if row is None:raise ValueError('Unknown tool ID; use tools list')
    out={**row,'availability':available(row)}
    if row.get('entry'):out['resolved_entry']=str(_local(row['entry']))
    out['resolved_manuals']=[str(_local(f)) for f in row.get('manuals',[])]
    if row['kind']=='python':out['argv_prefix']=python_tool_argv(sys.executable,ROOT,row['entry'],row.get('prefix',[]))
    if row['kind']=='powershell_module':out['use']='Import the actual .psm1 in a task-owned PowerShell script; this entry is not a generic scene-to-COM renderer.'
    if row['kind']=='host':out['use']='Discover the actual host tool schema, call it through the host, then submit the real file. No hidden API/endpoint configured in this bundle.'
    return out


def run(name,args):
    r=show(name)
    if r['kind'] in {'host','manual','powershell_module'}:
        return {'command_status':'action_required','tool':r,'note':'This item is not an executable CLI adapter. Use its actual host/module/read interface.'},0
    # Flags/paths are individual argv elements. No shell expansion, eval, or arbitrary code strings.
    if r['kind']=='python':argv=r['argv_prefix']+args
    else:
        shell=powershell_path()
        if os.name!='nt' or not shell:return {'command_status':'awaiting_capability','tool_id':name,'needed':'Windows PowerShell; Office needs a real probe'},0
        argv=[shell,'-NoProfile','-File',r['resolved_entry'],*r.get('prefix',[]),*args]
    try:p=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=r.get('timeout_seconds',240),shell=False,env=child_environment())
    except subprocess.TimeoutExpired:
        return {'command_status':'tool_failed','tool_id':name,'error':'Launcher timed out. No Office process was force-terminated; inspect the task-owned presentation before retry.'},1
    waits=r.get('waiting_exit_codes',[])
    status='completed' if p.returncode==0 else 'action_required' if p.returncode in waits else 'tool_failed'
    return {'command_status':status,'tool_id':name,'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,
            'scope':'Executed this registered entry only; successful exit is not visual or Office acceptance.'},0 if status!='tool_failed' else 1


def validate_registry(check_cli=False):
    issues=[];rows=entries()
    for r in rows:
        for key in ['id','title','kind','manuals','inputs','outputs','limitations']:
            if key not in r:issues.append(r.get('id','?')+': missing '+key)
        try:
            for m in r.get('manuals',[]):_local(m)
            if r['kind']!='host':
                p=_local(r['entry'])
                if r['kind']=='powershell_module':
                    funcs=set(re.findall(r'^function\s+([\w-]+)',p.read_text(encoding='utf-8-sig'),re.M))
                    for f in r.get('functions',[]):
                        if f not in funcs:issues.append(r['id']+': missing function '+f)
        except Exception as exc:issues.append(str(exc))
    # Every production .py/.ps1 and module is either directly callable or an explicitly catalogued library.
    catalogued={r.get('entry') for r in rows}|set(json.loads((ROOT/'toolbox/registry.json').read_text(encoding='utf-8')).get('internal_modules',[]))
    for p in (ROOT/'scripts').glob('*'):
        if p.suffix in {'.py','.ps1','.psm1'} and p.relative_to(ROOT).as_posix() not in catalogued:issues.append('Uncatalogued code file: '+p.name)
    if check_cli:
        from cli_contract import check_contracts
        issues.extend(check_contracts(ROOT, rows))
    return {'command_status':'completed' if not issues else 'tool_failed','status':'passed' if not issues else 'failed','issues':issues,'registered_items':len(rows)}
