#!/usr/bin/env python3
"""Unified local entry for the PPT Skill, task controller, commands and manuals."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))


def parser():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--version',action='version',version='ppt-reference-rebuild 1.3.1')
    sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('ops',help='Native components, assets, fonts and bounded edits (ops --help)')
    sub.add_parser('bench',help='Separate offline/live/cross-model evidence (bench --help)')
    t=sub.add_parser('tools',help='Find/show/run actual bundled tools');ts=t.add_subparsers(dest='action',required=True)
    p=ts.add_parser('list');p.add_argument('--query',default='')
    p=ts.add_parser('show');p.add_argument('id')
    p=ts.add_parser('run');p.add_argument('id');p.add_argument('args',nargs=argparse.REMAINDER)
    p=ts.add_parser('check');p.add_argument('--cli',action='store_true',help='Also check registered Python CLI help and fenced documentation examples; no Office or model calls')
    p=sub.add_parser('doctor',help='Actual local import/path probe, no installation');p.add_argument('--out',type=Path)
    p=sub.add_parser('start',help='Create NEW persistent project from references or a known scene')
    p.add_argument('--project',required=True,type=Path);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--references',nargs='+',type=Path);g.add_argument('--scene',type=Path)
    p.add_argument('--candidate',type=Path);p.add_argument('--ratio');p.add_argument('--mapping',choices=['uniform','explicit_stretch'],default='uniform')
    p.add_argument('--office',action='store_true');p.add_argument('--builder',choices=['python','external'],default='python');p.add_argument('--in-place',action='store_true')
    for command in ['next','status','advance','finish','handoff']:
        p=sub.add_parser(command);p.add_argument('--project',required=True,type=Path)
        if command=='advance':p.add_argument('--office',action='store_const',const=True,default=None)
    p=sub.add_parser('preview',help='Explicit LibreOffice pre-review; never Office acceptance');p.add_argument('--project',required=True,type=Path);p.add_argument('--receipt',type=Path);p.add_argument('--executable',type=Path);p.add_argument('--timeout',type=int,default=180)
    p=sub.add_parser('submit');p.add_argument('--project',required=True,type=Path);p.add_argument('--response',required=True,type=Path);p.add_argument('--return-next',action='store_true')
    p=sub.add_parser('review-again');p.add_argument('--project',required=True,type=Path);p.add_argument('--task',required=True);p.add_argument('--reason',required=True)
    p=sub.add_parser('retry');p.add_argument('--project',required=True,type=Path);p.add_argument('--reason',required=True)
    p=sub.add_parser('revise');p.add_argument('--project',required=True,type=Path);p.add_argument('--slide',required=True);p.add_argument('--region');p.add_argument('--reason',required=True)
    p=sub.add_parser('replace-candidate');p.add_argument('--project',required=True,type=Path);p.add_argument('--pptx',required=True,type=Path);p.add_argument('--reason',required=True)
    p=sub.add_parser('replace-scene');p.add_argument('--project',required=True,type=Path);p.add_argument('--scene',required=True,type=Path);p.add_argument('--reason',required=True)
    p=sub.add_parser('asset-add');p.add_argument('--project',required=True,type=Path);p.add_argument('--file',required=True,type=Path);p.add_argument('--provenance',required=True)
    p=sub.add_parser('unlock');p.add_argument('--project',required=True,type=Path);p.add_argument('--token',required=True);p.add_argument('--confirmed-no-active-writer',action='store_true')
    from toolbox_manager.contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
    for command in (*LOCAL_COMMANDS, *REQUEST_COMMANDS):
        p=sub.add_parser(command,help='Managed local workflow; request JSON')
        p.add_argument('--project',required=True,type=Path);p.add_argument('--request',required=True,type=Path)
    return ap


def main(argv=None):
    actual=list(sys.argv[1:] if argv is None else argv)
    if actual and actual[0] in {'ops','bench'}:
        import direct_ops, benchmark
        return (direct_ops.main if actual[0]=='ops' else benchmark.main)(actual[1:])
    args=parser().parse_args(actual)
    try:
        if args.command=='tools':
            import tool_registry as tr
            if args.action=='list':result={'command_status':'completed','tools':tr.listing(args.query)};code=0
            elif args.action=='show':result=tr.show(args.id);code=0
            elif args.action=='check':result=tr.validate_registry(check_cli=args.cli);code=0 if result['status']=='passed' else 1
            else:result,code=tr.run(args.id,args.args[1:] if args.args and args.args[0]=='--' else args.args)
        elif args.command=='doctor':
            from preflight import probe
            result=probe();result['command_status']='completed';code=0
            if args.out:
                from common import write_json
                write_json(args.out,result)
        else:
            import workflow as wf
            from toolbox_manager.contracts import LOCAL_COMMANDS, REQUEST_COMMANDS
            if args.command in {*LOCAL_COMMANDS, *REQUEST_COMMANDS}:
                raise ValueError('Use manager.py execute --tool workflow.'+args.command)
            from workflow_store import unlock
            project=args.project.resolve()
            if args.command=='start':result=wf.start(project,args.references,args.scene,args.candidate,args.ratio,args.mapping,args.office,args.builder,args.in_place)
            elif args.command=='next':result=wf.next_task(project)
            elif args.command in {'status','handoff'}:
                result=wf.status(project)
                if args.command=='handoff':result['handoff_file']=str(project/'HANDOFF.md')
            elif args.command=='advance':result=wf.advance(project,args.office)
            elif args.command=='preview':result=wf.preview(project,args.receipt,args.executable,args.timeout)
            elif args.command=='submit':result=wf.submit(project,args.response,return_next=args.return_next)
            elif args.command=='review-again':result=wf.review_again(project,args.task,args.reason)
            elif args.command=='retry':result=wf.retry(project,args.reason)
            elif args.command=='revise':result=wf.revise(project,args.slide,args.region,args.reason)
            elif args.command=='replace-candidate':result=wf.replace_candidate(project,args.pptx,args.reason)
            elif args.command=='replace-scene':result=wf.replace_scene(project,args.scene,args.reason)
            elif args.command=='asset-add':result=wf.add_asset(project,args.file,args.provenance)
            elif args.command=='unlock':result=unlock(project,args.token,args.confirmed_no_active_writer)
            else:result=wf.complete(project)
            code=1 if result.get('workflow_status')=='tool_failed' else 0
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return code
    except Exception as exc:
        print(json.dumps({'command_status':'failed','error':{'code':getattr(exc,'code','invalid_operation'),
                   'message':str(exc),'hint':getattr(exc,'hint','Use tools show or the current task template; do not silently drop unsupported requirements.')}},ensure_ascii=False,indent=2))
        return 2

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
