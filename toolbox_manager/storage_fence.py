"""Durable DML fence for legacy connections; not a sandbox against arbitrary DDL."""
import contextlib
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path


KEY = '__ppt_toolbox_migration_fence__'
PREFIX = '__ppt_migration_fence_'


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


@contextlib.contextmanager
def transaction(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=20)
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _triggers(connection):
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for (table,) in rows:
        if table.startswith('sqlite_'):
            continue
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            name = PREFIX + hashlib.sha256(table.encode('utf-8')).hexdigest() + '_' + operation
            connection.execute(
                f'CREATE TRIGGER {quoted(name)} BEFORE {operation} ON {quoted(table)} '
                f"WHEN EXISTS (SELECT 1 FROM kv WHERE key='{KEY}') "
                "BEGIN SELECT RAISE(ABORT, 'Management data is migration-fenced'); END")


def _record(connection, owner):
    row = connection.execute('SELECT value FROM kv WHERE key=?', (KEY,)).fetchone()
    if row is None or json.loads(row[0]).get('owner') != owner:
        raise ValueError('Migration fence identity changed; refusing to release it')
    return json.loads(row[0])


def _drop(connection):
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        if name.startswith(PREFIX):
            connection.execute('DROP TRIGGER ' + quoted(name))


def acquire(path, audit):
    """Audit and fence atomically, after any prior writer commits."""
    owner = uuid.uuid4().hex
    with transaction(path) as connection:
        if connection.execute('SELECT 1 FROM kv WHERE key=?', (KEY,)).fetchone():
            raise ValueError('Source data already has a migration fence; inspect before recovery')
        if any(name.startswith(PREFIX) for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")):
            raise ValueError('Orphaned migration triggers require explicit recovery')
        audit(connection)
        # Legacy request writers lazily create this table without first writing kv.
        created = []
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='requests'").fetchone():
            connection.execute('CREATE TABLE requests (id TEXT PRIMARY KEY, binding TEXT UNIQUE, body TEXT)')
            created.append('requests')
        connection.execute('INSERT INTO kv VALUES (?,?)',
                           (KEY, json.dumps({'owner': owner, 'status': 'migrating', 'created_tables': created})))
        _triggers(connection)
    return owner


@contextlib.contextmanager
def maintenance(path, owner, release=False):
    """Only the installer can remove the fence, within its exclusive write transaction."""
    with transaction(path) as connection:
        record = _record(connection, owner)
        _drop(connection)
        yield connection
        if release:
            connection.execute('DELETE FROM kv WHERE key=?', (KEY,))
            for table in record.get('created_tables', []):
                if table == 'requests' and not connection.execute('SELECT 1 FROM requests LIMIT 1').fetchone():
                    connection.execute('DROP TABLE requests')
        else:
            _triggers(connection)


def release(path, owner):
    with maintenance(path, owner, release=True):
        pass


def retire(path, owner, target):
    with maintenance(path, owner) as connection:
        record = _record(connection, owner)
        record.update(status='retired', canonical_data=str(target))
        connection.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(record), KEY))
