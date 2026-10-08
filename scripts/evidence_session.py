"""Request-local decoded metadata. Every reuse still hashes the actual file bytes."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import io
from pathlib import Path
import time

_current = ContextVar("ppt_evidence_validation", default=None)


class ValidationSession:
    def __init__(self):
        self.images = {}
        self.counts = {}
        self.seconds = {}

    def add(self, name, elapsed=0.0, count=1):
        self.counts[name] = self.counts.get(name, 0) + count
        self.seconds[name] = self.seconds.get(name, 0.0) + elapsed

    def report(self):
        return {
            "scope": "one invocation; file content hashes are never cached",
            "counts": dict(self.counts),
            "seconds": {k: round(v, 6) for k, v in self.seconds.items()},
            "timing_note": "Named phases are inclusive and may overlap; do not add them.",
        }


@contextmanager
def validation_scope():
    existing = _current.get()
    if existing is not None:
        yield existing
        return
    session = ValidationSession()
    token = _current.set(session)
    try:
        yield session
    finally:
        _current.reset(token)


def scoped(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with validation_scope():
            return function(*args, **kwargs)
    return wrapped


def measured(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            session = _current.get()
            if session is None:
                return function(*args, **kwargs)
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                session.add(name, time.perf_counter() - started)
        return wrapped
    return decorate


def image_metadata(path, *, png_only=False, expected=None):
    from PIL import Image

    path = Path(path)
    session = _current.get()
    started = time.perf_counter()
    raw = path.read_bytes()
    identity = hashlib.sha256(raw).hexdigest()
    if session is not None:
        session.add("image_read_hash", time.perf_counter() - started)
        session.add("image_bytes_hashed", count=len(raw))
    if expected is not None and identity != expected:
        raise ValueError(f"File hash mismatch: {path.name}")
    key = str(path.resolve())
    cached = session.images.get(key) if session is not None else None
    if cached is not None and cached[0] == identity:
        if png_only and cached[1] != "PNG":
            raise ValueError(f"Expected PNG content: {path.name}")
        session.add("image_decode_reused")
        return list(cached[2]), identity
    # Hash and decode the same byte snapshot; never trust size/mtime as file identity.
    started = time.perf_counter()
    with Image.open(io.BytesIO(raw)) as image:
        if png_only and image.format != "PNG":
            raise ValueError(f"Expected PNG content: {path.name}")
        image.load()
        value = (identity, image.format, (image.width, image.height))
    if session is not None:
        session.add("image_decode", time.perf_counter() - started)
        if len(session.images) >= 4096:
            session.images.clear()
        session.images[key] = value
    return list(value[2]), identity
