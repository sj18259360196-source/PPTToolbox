#!/usr/bin/env python3
"""PPT toolbox manager: human control plane plus read-only MCP discovery."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
if sys.version_info < (3,10):
    raise SystemExit('Python 3.10 or later is required. No dependency download has been attempted.')
from toolbox_manager import VERSION

def default_data():
    root = Path(__file__).resolve().parent
    if (root/'PRODUCT.json').is_file():
        location = root.parent/'location.json'
        if location.is_file():
            data = Path(json.loads(location.read_text(encoding='utf-8'))['data_directory']).expanduser()
            if not data.is_absolute():raise ValueError('Configured data directory must be absolute')
            return data
        return root.parent/'data'
    return Path(os.environ.get('PPT_TOOLBOX_DATA',str(Path.home()/'.ppt-toolbox-manager')))

def main():
    root = Path(__file__).resolve().parent
    bundle = root/'dist/PPTToolbox'
    pointer = Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'PPTToolbox-installation.json'
    if not (root/'PRODUCT.json').exists() and pointer.is_file():
        bundle = Path(json.loads(pointer.read_text(encoding='utf-8'))['installation'])
    if not (root/'PRODUCT.json').exists() and (bundle/'portable.py').is_file() and '--data-dir' not in sys.argv and not os.environ.get('PPT_TOOLBOX_DATA'):
        os.execv(str(bundle/'runtime/python.exe'), [str(bundle/'runtime/python.exe'), '-B', str(bundle/'portable.py'), *sys.argv[1:]])
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--version',action='version',version=VERSION);p.add_argument('--data-dir',type=Path,default=default_data())
    s=p.add_subparsers(dest='command');a=s.add_parser('serve');a.add_argument('--port',type=int,default=0);a.add_argument('--no-browser',action='store_true')
    for n in ['mcp','check','context','export-config']:s.add_parser(n)
    a=s.add_parser('desktop',help='Windows background tray host; no execution permission changes')
    a.add_argument('--vendor',type=Path);a.add_argument('--show',action='store_true')
    a.add_argument('--smoke',action='store_true');a.add_argument('--agent-start',action='store_true')
    a=s.add_parser('register-codex');a.add_argument('--apply',action='store_true')
    a=s.add_parser('agent-setup',help='Configure only this toolbox MCP server; never grants project execution')
    a.add_argument('--host',choices=['codex','cursor','antigravity','generic'],default='codex')
    a.add_argument('--path');a.add_argument('--apply',action='store_true')
    a.add_argument('--probe',action='store_true');a.add_argument('--challenge',action='store_true')
    a=s.add_parser('execute');a.add_argument('--tool',required=True);a.add_argument('args',nargs=argparse.REMAINDER)
    a=s.add_parser('describe');a.add_argument('--tool',required=True)
    a=s.add_parser('authorize-project',help='Owner-only explicit directory grant; never exposed through MCP')
    a.add_argument('--project',type=Path,required=True);a.add_argument('--input-root',type=Path,action='append',default=[])
    x=p.parse_args()
    if x.command in {None,'serve'}:
        from toolbox_manager.server import serve
        serve(x.data_dir,getattr(x,'port',0),not getattr(x,'no_browser',False));return 0
    if x.command=='mcp':
        from toolbox_manager.mcp import run
        run(x.data_dir);return 0
    if x.command=='desktop':
        from toolbox_manager.desktop import run
        run(x.data_dir,x.vendor,x.show,x.smoke,x.agent_start);return 0
    from toolbox_manager.service import Manager
    m=Manager(x.data_dir)
    if x.command=='agent-setup':
        from toolbox_manager.agent_onboarding import run
        out=run(m,vars(x))
    elif x.command=='authorize-project':out=m.authorize_project(x.project,x.input_root)
    elif x.command=='check':out={'manager':m.boot(),'environment':m.doctor()}
    elif x.command=='context':out=m.context()
    elif x.command=='describe':out=m.tool(x.tool)
    elif x.command=='export-config':out=m.export_integration()
    elif x.command=='register-codex':
        out=m.register_plan()
        if x.apply:out=m.register_apply(out['confirm_id'])
    else:
        out=m.execute(x.tool,x.args[1:] if x.args[:1]==['--'] else x.args)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return (0 if out.get('command_status')=='action_required' else out.get('returncode',0)) if isinstance(out,dict) else 0
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    try:raise SystemExit(main())
    except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)
