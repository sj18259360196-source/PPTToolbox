"""Cooperative exit for idle desktop/MCP instances. Never terminates processes."""
import json
import time
from pathlib import Path

def requested(data):
    try:
        r=json.loads((Path(data)/"UPDATE_REQUEST.json").read_text(encoding="utf-8"))
        return r.get("data")==str(Path(data).resolve()) and 0<=time.time()-r["created"]<60
    except (OSError,ValueError,KeyError,TypeError):return False

def idle(data):
    from distribution.update_installed import audit
    import sqlite3
    try:
        with sqlite3.connect(Path(data)/"manager.sqlite3") as db:audit(Path(data),db)
        return True
    except Exception:return False
