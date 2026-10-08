"""Live MCP transport sessions, separate from configuration and authorization."""
import contextlib,json,os,sqlite3,threading,time,uuid
from .storage import redact

TTL=12

@contextlib.contextmanager
def database(data):
    db=sqlite3.connect(data/'agent-runtime.sqlite3',timeout=2)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, updated REAL, body TEXT)')
            yield db
    finally:db.close()

class Session:
    def __init__(self,data):
        self.data=data;self.id=uuid.uuid4().hex;self.row=None
        self.lock=threading.RLock();self.stopped=threading.Event();self.thread=None
    def save(self):
        # Status failures must never change execution results or permissions.
        try:
            with database(self.data) as db:
                db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?)',(self.id,time.time(),json.dumps(self.row)))
                db.execute('DELETE FROM sessions WHERE updated < ?',(time.time()-86400,))
        except (OSError,sqlite3.Error):pass
    def connect(self,client):
        if os.environ.get('PPT_TOOLBOX_CONNECTION_PROBE')=='1':return
        name=str(client.get('name','未知客户端'))[:120]
        if 'local probe' in name.lower():return
        with self.lock:
            self.row={'id':self.id,'client':name,'pid':os.getpid(),'state':'connected',
                      'connected_at':time.time(),'last_call':None,'tool':'','error':''}
            self.save()
        if self.thread is None:
            self.thread=threading.Thread(target=self.pulse,daemon=True);self.thread.start()
    def pulse(self):
        while not self.stopped.wait(3):
            with self.lock:
                if self.row:self.save()
    def begin(self,tool):
        with self.lock:
            if self.row:
                self.row.update(state='working',tool=str(tool)[:120],last_call=time.time(),error='',recovery=None);self.save()
    def finish(self,error='',recovery=None):
        with self.lock:
            if self.row:
                self.row.update(state='error' if error else 'connected',error=str(redact(error))[:500],
                                recovery=redact(recovery),last_call=time.time());self.save()
    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=3)
        with self.lock:
            if self.row:self.row.update(state='offline');self.save()

def status(m,now=None):
    now=time.time() if now is None else now
    rows=[]
    if (m.data/'agent-runtime.sqlite3').exists():
        with database(m.data) as db:
            for updated,body in db.execute('SELECT updated,body FROM sessions ORDER BY updated DESC LIMIT 100'):
                row=json.loads(body);row['updated_at']=updated
                if now-updated>TTL:row['state']='offline'
                rows.append(row)
    live=[r for r in rows if r['state']!='offline']
    state=next((s for s in ('working','error','connected') if any(r['state']==s for r in live)),'offline')
    return {'state':state,'sessions':live,'recent_disconnects':[r for r in rows if r['state']=='offline'][:5],
            'connected_count':len(live),'checked_at':now,'heartbeat_timeout_seconds':TTL,
            'scope':'仅显示通过本工具箱 MCP 的连接和调用，无法观察 Agent 在其他软件中的活动。'}
