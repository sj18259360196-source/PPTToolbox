"""Explicit management identity and retired-data guard; never auto-migrate writes."""
import json
import uuid
from pathlib import Path


def check_retired(data):
    if (Path(data)/'MIGRATION_PENDING.json').exists():
        raise ValueError('Data migration is incomplete. Keep the original data and inspect the migration report.')
    marker = Path(data).expanduser().resolve() / 'RETIRED.json'
    if marker.is_file():
        target = json.loads(marker.read_text(encoding='utf-8'))['canonical_data']
        raise ValueError('This management directory is retired. Reconnect using the packaged entry: ' + target)


def describe(manager):
    with manager.store.db() as c:
        c.execute('INSERT OR IGNORE INTO kv(key,value) VALUES (?,?)',
                  ('instance_id', json.dumps(uuid.uuid4().hex)))
        identity = json.loads(c.execute("SELECT value FROM kv WHERE key='instance_id'").fetchone()[0])
    daily = manager.root.parent / 'data'
    location = manager.root.parent/'location.json'
    if location.is_file():
        daily = Path(json.loads(location.read_text(encoding='utf-8'))['data_directory']).resolve()
    return {'id': identity, 'data_dir': str(manager.data), 'app_dir': str(manager.root),
            'mode': 'daily' if (manager.root/'PRODUCT.json').is_file() and manager.data == daily else 'isolated',
            'distribution': manager.distribution()}
