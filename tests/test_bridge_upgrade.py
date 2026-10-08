"""Real subprocess/stdio upgrade lifecycle using a fixture backend, not a Codex host."""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


def test_supervisor_keeps_pipe_and_does_not_replay_writes(tmp_path):
    root=tmp_path/'install';root.mkdir();data=tmp_path/'data';data.mkdir()
    (root/'location.json').write_text(json.dumps({'data_directory':str(data)}),encoding='utf-8')
    shutil.copyfile(Path(__file__).resolve().parents[1]/'distribution/agent_bridge.py',root/'agent_bridge.py')
    (root/'portable.py').write_text('''import json,sys,threading,time,os
from pathlib import Path
data=Path(json.loads((Path(__file__).parent/'location.json').read_text())['data_directory'])
def watch():
 while True:
  if (data/'UPDATE_REQUEST.json').exists():os._exit(0)
  time.sleep(.05)
threading.Thread(target=watch,daemon=True).start()
for line in sys.stdin:
 r=json.loads(line)
 if 'id' in r:
  if r.get('method')=='write':
   with (data/'writes.txt').open('a') as f:f.write('write\\n')
  print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':{'pid':os.getpid()}}),flush=True)
''',encoding='utf-8')
    child=subprocess.Popen([sys.executable,'-B',str(root/'agent_bridge.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,encoding='utf-8')
    lines=queue.Queue()
    def reader():
        for line in child.stdout:lines.put(json.loads(line))
    threading.Thread(target=reader,daemon=True).start()
    def send(r):child.stdin.write(json.dumps(r)+'\n');child.stdin.flush()
    def response(rid):
        until=time.monotonic()+12
        while time.monotonic()<until:
            r=lines.get(timeout=10)
            if r.get('id')==rid:return r
        raise AssertionError('Missing response')
    try:
        send({'jsonrpc':'2.0','id':1,'method':'initialize'});first=response(1)['result']['pid']
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        send({'jsonrpc':'2.0','id':2,'method':'write'});response(2)
        session=data/'UPDATE_SESSION.json';session.write_text('{}')
        signal=data/'UPDATE_REQUEST.json';signal.write_text('{}')
        marker=data/'mcp-bridges'/f'{child.pid}.json'
        until=time.monotonic()+10
        while time.monotonic()<until:
            try:
                if json.loads(marker.read_text())['parked']:break
            except (OSError,ValueError):pass
            time.sleep(.05)
        assert json.loads(marker.read_text())['parked']
        send({'jsonrpc':'2.0','id':3,'method':'write'})
        assert 'not dispatched' in response(3)['error']['message']
        signal.unlink();session.unlink()
        notification=lines.get(timeout=10)
        assert notification['method']=='notifications/tools/list_changed'
        send({'jsonrpc':'2.0','id':4,'method':'ping'});second=response(4)['result']['pid']
        assert first!=second and child.poll() is None
        assert (data/'writes.txt').read_text()=='write\n'
    finally:
        child.stdin.close();child.wait(timeout=10)
    assert child.returncode==0,child.stderr.read()
    assert not marker.exists()


def test_supervisor_drains_responses_on_host_eof(tmp_path):
    root=tmp_path/'install';root.mkdir();data=tmp_path/'data';data.mkdir()
    (root/'location.json').write_text(json.dumps({'data_directory':str(data)}))
    shutil.copyfile(Path(__file__).resolve().parents[1]/'distribution/agent_bridge.py',root/'agent_bridge.py')
    (root/'portable.py').write_text("import sys,json,time\nfor line in sys.stdin:\n r=json.loads(line);time.sleep(.1);print(json.dumps({'id':r['id'],'result':{}}),flush=True)\n")
    r=subprocess.run([sys.executable,'-B',str(root/'agent_bridge.py')],input='{"id":1,"method":"ping"}\n',
                     capture_output=True,text=True,timeout=10)
    assert r.returncode==0 and json.loads(r.stdout)['id']==1,r.stderr


def test_backend_crash_keeps_host_pipe_and_reports_unknown_without_replay(tmp_path):
    root=tmp_path/'install';root.mkdir();data=tmp_path/'data';data.mkdir()
    (root/'location.json').write_text(json.dumps({'data_directory':str(data)}))
    shutil.copyfile(Path(__file__).resolve().parents[1]/'distribution/agent_bridge.py',root/'agent_bridge.py')
    (root/'portable.py').write_text('''import json,sys,os
from pathlib import Path
data=Path(json.loads((Path(__file__).parent/'location.json').read_text())['data_directory'])
for line in sys.stdin:
 r=json.loads(line)
 if r.get('method')=='crash_write':
  with (data/'writes.txt').open('a') as f:f.write('write\\n')
  os._exit(7)
 if 'id' in r:
  print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':{'pid':os.getpid()}}),flush=True)
''',encoding='utf-8')
    child=subprocess.Popen([sys.executable,'-B',str(root/'agent_bridge.py')],stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    lines=queue.Queue()
    def reader():
        for line in child.stdout:lines.put(json.loads(line))
    threading.Thread(target=reader,daemon=True).start()
    def send(value):
        child.stdin.write(json.dumps(value)+'\n');child.stdin.flush()
    def wait_for(predicate):
        end=time.monotonic()+12
        while time.monotonic()<end:
            row=lines.get(timeout=10)
            if predicate(row):return row
        raise AssertionError('Missing bridge response')
    try:
        send({'jsonrpc':'2.0','id':1,'method':'initialize'})
        before=wait_for(lambda r:r.get('id')==1)['result']['pid']
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        send({'jsonrpc':'2.0','id':2,'method':'crash_write'})
        failed=wait_for(lambda r:r.get('id')==2)
        assert failed['error']['data']['outcome']=='outcome_unknown'
        assert failed['error']['data']['replay_allowed'] is False
        wait_for(lambda r:r.get('method')=='notifications/tools/list_changed')
        send({'jsonrpc':'2.0','id':3,'method':'ping'})
        assert wait_for(lambda r:r.get('id')==3)['result']['pid']!=before
        assert child.poll() is None
        assert (data/'writes.txt').read_text()=='write\n'
    finally:
        child.stdin.close();child.wait(timeout=10)
    assert child.returncode==0,child.stderr.read()
