"""Small durable usage ledger shared by installed UI and managed workers."""
import contextlib
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def key(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def connect(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root/'usage.sqlite3', timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usage_events (
          event_key TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, entity TEXT NOT NULL,
          action TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, project TEXT NOT NULL,
          task TEXT NOT NULL, version TEXT NOT NULL, duration REAL, is_test INTEGER NOT NULL,
          historical INTEGER NOT NULL, evidence TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS usage_lookup ON usage_events(kind,entity,at);
        CREATE INDEX IF NOT EXISTS usage_period ON usage_events(at,is_test);''')
        db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', ('enabled_since', now()))
        db.commit()
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def insert(db, event_key, kind, entity, action, *, at=None, status='ok', source='agent',
           project='', task='', version='', duration=None, is_test=None, historical=False, evidence=None):
    if is_test is None: is_test = os.environ.get('PPT_USAGE_TEST') == '1'
    values = (event_key, at or now(), kind, entity, action, status, source, project or '', task or '',
              version or '', duration, int(is_test), int(historical), json.dumps(evidence or {}, ensure_ascii=False))
    return db.execute('INSERT OR IGNORE INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values).rowcount


def record(root, event_key, kind, entity, action, **values):
    with connect(root) as db:
        return insert(db, event_key, kind, entity, action, **values)


def worker_record(event_key, kind, entity, action, **values):
    """Metrics cannot turn completed production work into a retryable failure."""
    root = os.environ.get('PPT_USAGE_ROOT')
    if not root: return
    try:
        values.setdefault('project', os.environ.get('PPT_USAGE_PROJECT', ''))
        values.setdefault('task', os.environ.get('PPT_USAGE_TASK', ''))
        record(root, event_key, kind, entity, action, **values)
    except (OSError, sqlite3.Error) as exc:
        import warnings
        warnings.warn('Usage recording unavailable: '+type(exc).__name__, RuntimeWarning)
