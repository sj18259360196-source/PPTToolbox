"""Stable stdio supervisor. Upgrades restart only the idle backend, never replay writes."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def serve(root):
    location=root/'location.json'
    if not location.is_file():raise SystemExit('PPT Toolbox installation configuration is missing; run Setup.')
    data=Path(json.loads(location.read_text(encoding='utf-8'))['data_directory'])
    marker=data/'mcp-bridges'/f'{os.getpid()}.json';marker.parent.mkdir(parents=True,exist_ok=True)
    events=queue.Queue();child=None;generation=0;pending=set();handshake=None;initialized=False;parked=False
    host_closed=False;restart_at=0.0;restart_allowed=True;unexpected_exits=[];park_reason='upgrade'
    if hasattr(sys.stdin,'reconfigure'):sys.stdin.reconfigure(encoding='utf-8')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
    def error(rid,message,outcome='not_dispatched'):
        emit({'jsonrpc':'2.0','id':rid,'error':{'code':-32002,'message':message,
              'data':{'outcome':outcome,'replay_allowed':False,
                      'next_action':'inspect_status' if outcome=='outcome_unknown' else 'wait_then_rebind'}}})
    def read_host():
        try:
            for line in sys.stdin:events.put(('host',line))
        finally:events.put(('host',None))
    def upgrading():
        return any(p.exists() for p in (data/'UPDATE_SESSION.json',data/'UPDATE_REQUEST.json',root/'UPDATE_PENDING.json'))
    def mark(value):
        marker.write_text(json.dumps({'pid':os.getpid(),'installation':str(root),'parked':value,
            'reason':park_reason if value else None,'backend_generation':generation,
            'backend_pid':child.pid if child and child.poll() is None else None}),encoding='utf-8')
    def start():
        nonlocal child,generation
        generation+=1;tag=generation
        env={**os.environ,'PPT_TOOLBOX_BRIDGE_PID':str(os.getpid()),
             'PPT_TOOLBOX_BACKEND_GENERATION':str(generation)}
        child=subprocess.Popen([sys.executable,'-B',str(root/'portable.py'),'mcp'],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=sys.stderr,text=True,encoding='utf-8',bufsize=1,
            env=env,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process=child
        def read_child():
            try:
                for line in process.stdout:events.put((tag,line))
            finally:events.put((tag,None))
        threading.Thread(target=read_child,daemon=True).start()
        if handshake:
            child.stdin.write(json.dumps({**handshake,'id':'__toolbox_upgrade_initialize__'})+'\n')
            if initialized:child.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n')
            child.stdin.flush()
    threading.Thread(target=read_host,daemon=True).start()
    parked=upgrading();mark(parked)
    if not parked:start()
    try:
        while True:
            if parked and not host_closed and restart_allowed and not upgrading() and time.monotonic()>=restart_at:
                start();parked=False;mark(False)
                if initialized:emit({'jsonrpc':'2.0','method':'notifications/tools/list_changed'})
            try:source,line=events.get(timeout=.2)
            except queue.Empty:continue
            if source=='host':
                if line is None:
                    host_closed=True
                    if parked:break
                    child.stdin.close()
                    continue
                try:req=json.loads(line)
                except ValueError:error(None,'Invalid JSON');continue
                if not isinstance(req,dict):error(None,'Expected a JSON object');continue
                if req.get('method')=='initialize':handshake=req
                if req.get('method')=='notifications/initialized':initialized=True
                if parked or upgrading():
                    if 'id' in req:
                        reason='Toolbox upgrade in progress' if upgrading() else 'Backend restarting' if restart_allowed else 'Backend restart limit reached; reconnect the bridge'
                        error(req['id'],reason+'. Request not dispatched. Wait, then bind project again; do not replay previous writes.')
                    continue
                if 'id' in req:pending.add(req['id'])
                try:child.stdin.write(line.rstrip()+'\n');child.stdin.flush()
                except (BrokenPipeError,OSError):
                    if 'id' in req:pending.discard(req['id']);error(req['id'],'Backend unavailable. Inspect project status before retrying any write.','outcome_unknown')
            elif source==generation:
                if line is None:
                    for rid in pending:error(rid,'Backend exited; outcome unknown. Inspect project status before retrying any write.','outcome_unknown')
                    pending.clear();child.wait()
                    try:uninstall=json.loads((data/'UPDATE_REQUEST.json').read_text(encoding='utf-8')).get('mode')=='uninstall'
                    except (OSError,ValueError):uninstall=False
                    if uninstall or host_closed:break
                    parked=True
                    if upgrading():
                        park_reason='upgrade';restart_at=0.0;restart_allowed=True
                    else:
                        now=time.monotonic()
                        unexpected_exits=[v for v in unexpected_exits if now-v<60]+[now]
                        restart_allowed=len(unexpected_exits)<=3
                        restart_at=now+min(len(unexpected_exits)*.25,1)
                        park_reason='backend_restart' if restart_allowed else 'restart_limit'
                    mark(True);continue
                result=json.loads(line)
                if result.get('id')=='__toolbox_upgrade_initialize__':continue
                pending.discard(result.get('id'));emit(result)
    finally:
        marker.unlink(missing_ok=True)
        if child and child.poll() is None:
            if not child.stdin.closed:child.stdin.close()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:pass


if __name__=='__main__':serve(Path(__file__).resolve().parent)
