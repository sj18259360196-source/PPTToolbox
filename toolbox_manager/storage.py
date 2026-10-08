"""SQLite configuration/audit store shared by browser, CLI and MCP processes."""
from __future__ import annotations
import contextlib, hashlib, json, os, re, sqlite3, time
from pathlib import Path


def stamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def digest(data):
    if isinstance(data,str): data=data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def redact(value):
    if isinstance(value,dict):
        return {k: ('[REDACTED]' if re.search(r'(^|_)(password|secret|authorization|api_key|token|cookie)($|_)',k,re.I) else redact(v)) for k,v in value.items()}
    if isinstance(value,list):return [redact(x) for x in value]
    if isinstance(value,str):
        value=re.sub(r'(?i)\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[^\s"\']+)', '[REDACTED]', value)
        value=re.sub(r'(?i)([?&](?:token|key|api_key|secret)=)[^&\s]+',r'\1[REDACTED]',value)
    return value


class Store:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'manager.sqlite3'
        with self.db() as c:
            has_kv=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kv'").fetchone()
            if has_kv:
                existing=c.execute('SELECT value FROM kv WHERE key="schema_version"').fetchone()
                if existing and json.loads(existing[0])!=1:
                    raise ValueError('管理数据库版本不兼容；请使用匹配版本，不自动覆盖或降级')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS packages (id TEXT PRIMARY KEY, name TEXT, version TEXT, description TEXT, path TEXT,
                source TEXT, fingerprint TEXT, trusted INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, created TEXT);
            CREATE TABLE IF NOT EXISTS overrides (package_id TEXT, kind TEXT, target TEXT, value TEXT NOT NULL,
                PRIMARY KEY(package_id,kind,target));
            CREATE TABLE IF NOT EXISTS docs (package_id TEXT, path TEXT, content TEXT, revision INTEGER, updated TEXT,
                PRIMARY KEY(package_id,path));
            CREATE TABLE IF NOT EXISTS doc_history (id INTEGER PRIMARY KEY AUTOINCREMENT, package_id TEXT,
                path TEXT, content TEXT, revision INTEGER, updated TEXT);
            CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, title TEXT, description TEXT, body TEXT,
                enabled INTEGER, revision INTEGER, updated TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, source TEXT,
                action TEXT, status TEXT, message TEXT, details TEXT);
            CREATE TABLE IF NOT EXISTS activations (id INTEGER PRIMARY KEY AUTOINCREMENT, old_id TEXT, new_id TEXT, time TEXT);
            CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, path TEXT, name TEXT, created TEXT);
            ''')
            c.execute('INSERT OR IGNORE INTO kv VALUES(?,?)',('schema_version','1'))
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=20)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    def get(self,key,default=None):
        with self.db() as c:r=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default
    def set(self,key,value):
        with self.db() as c:c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,ensure_ascii=False)))
    def event(self,action,message,status='ok',source='manager',details=None):
        details={**(details or {}),'usage_test':os.environ.get('PPT_USAGE_TEST')=='1'}
        with self.db() as c:
            c.execute('INSERT INTO events(time,source,action,status,message,details) VALUES(?,?,?,?,?,?)',
                (stamp(),source,action,status,redact(str(message)),json.dumps(redact(details or {}),ensure_ascii=False)))
        # No stdout logging: MCP owns stdout. No automatic destructive log retention.
    def logs(self,query='',status='',limit=200):
        with self.db() as c:
            rows=c.execute('SELECT * FROM events WHERE (?="" OR message LIKE ? OR action LIKE ?) AND (?="" OR status=?) ORDER BY id DESC LIMIT ?',
                (query,'%'+query+'%','%'+query+'%',status,status,min(max(int(limit),1),1000))).fetchall()
        return [{**dict(r),'details':json.loads(r['details'])} for r in rows]

    def unfinished_calls(self, project):
        with self.db() as c:
            rows = c.execute(
                "SELECT action,details FROM events WHERE action IN "
                "('tool.started','tool.authorized','tool.launched','tool.finished','tool.reconciled') ORDER BY id"
            ).fetchall()
        active = {}
        for row in rows:
            d = json.loads(row["details"])
            cid = d.get("call_id")
            if not cid:
                continue
            if row["action"] in {"tool.finished", "tool.reconciled"}:
                active.pop(cid, None)
            elif d.get("project") == project:
                active[cid] = d
        return list(active.values())
