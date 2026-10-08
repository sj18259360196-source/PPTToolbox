"""Record observed software releases separately from extension activation history."""
from __future__ import annotations

import json
from .storage import stamp

HISTORY_KEY = 'software_release_history'


def observe(store, distribution):
    # Source previews have no installed release receipt and must not claim an upgrade.
    if not distribution or not distribution.get('version'):
        return
    identity = {key: distribution.get(key) for key in ('version', 'source_sha256')}
    existing = store.get(HISTORY_KEY, [])
    if existing and all(existing[-1].get(key) == value for key, value in identity.items()):
        return
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM kv WHERE key=?', (HISTORY_KEY,)).fetchone()
        history = json.loads(row['value']) if row else []
        previous = history[-1] if history else None
        if previous and all(previous.get(key) == value for key, value in identity.items()):
            return
        history.append({**identity, 'observed_at': stamp(),
                        'kind': 'release_changed' if previous else 'first_observed'})
        db.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (HISTORY_KEY, json.dumps(history)))


def history(store):
    return list(reversed(store.get(HISTORY_KEY, [])))[:50]
