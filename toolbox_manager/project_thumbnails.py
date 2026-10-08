"""Small durable reference covers, independent of project availability."""
import hashlib
import io
import json
import os
import stat
import threading
import time
from pathlib import Path
from PIL import Image, ImageOps

_lock = threading.Lock()  # Only one source image is decoded at a time.
_background = threading.Semaphore(1)
_checked = {}
SIZE = (320, 200)


def _identity(manager, key):
    row = manager.store.get('workbench_projects', {}).get(key)
    if not row:
        raise ValueError('项目未登记')
    root = Path(row['path'])
    identity = json.dumps([key, str(root).casefold(), row.get('project_id')])
    name = hashlib.sha256(identity.encode()).hexdigest()
    return root, Path(manager.data) / 'project-thumbnails' / (name + '.jpg')


def _source(root):
    from .workbench import Workbench
    base = Workbench.path(root, 'input')
    candidates = []
    count = 0
    for folder, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (getattr((Path(folder)/d).lstat(), 'st_file_attributes', 0)
                         & stat.FILE_ATTRIBUTE_REPARSE_POINT) and not (Path(folder)/d).is_symlink())
        count += 1 + len(files) + len(dirs)
        for name in sorted(files)[:512]:
            if Path(name).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                continue
            try:
                path = Workbench.path(root, (Path(folder)/name).relative_to(root))
                info = path.stat()
                candidates.append((info.st_mtime_ns, path, info.st_size))
            except (OSError, ValueError):
                continue
        if count >= 512:
            break
    if not candidates:
        return None
    newest = max(candidates, key=lambda item: item[0])[1].parent
    return min((item for item in candidates if item[1].parent == newest), key=lambda item: item[1].name)


def refresh(manager, key, force=False):
    root, target = _identity(manager, key)
    with _lock:
        now = time.monotonic()
        if not force and now - _checked.get(str(target), -60) < 60:
            return
        _checked[str(target)] = now
        try:
            source = _source(root)
            if source is None:
                return  # Keep the last good cover when references disappear.
            modified, path, size = source
            signature = [str(path.relative_to(root)), modified, size]
            metadata = target.with_suffix('.json')
            try:
                saved = json.loads(metadata.read_text('utf-8'))
            except (OSError, ValueError):
                saved = None
            if target.is_file() and saved == signature:
                return
            with Image.open(path) as original:
                if original.width * original.height > 40_000_000:
                    return
                original.draft('RGB', SIZE)
                original.thumbnail(SIZE, Image.Resampling.LANCZOS)
                im = ImageOps.exif_transpose(original).convert('RGBA')
                im.thumbnail(SIZE, Image.Resampling.LANCZOS)
                background = Image.new('RGB', im.size, 'white')
                background.paste(im, mask=im.getchannel('A'))
                out = io.BytesIO()
                background.save(out, format='JPEG', quality=76, optimize=True)
            if [path.stat().st_mtime_ns, path.stat().st_size] != [modified, size]:
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_suffix('.pending')
            pending.write_bytes(out.getvalue())
            os.replace(pending, target)
            metadata.write_text(json.dumps(signature), encoding='utf-8')
        except (OSError, ValueError, Image.DecompressionBombError):
            return


def image(manager, key):
    _, target = _identity(manager, key)
    if not target.is_file():
        refresh(manager, key)
    else:
        # Cached reads never wait for the original project disk or image decode.
        if time.monotonic() - _checked.get(str(target), -60) >= 60 and _background.acquire(blocking=False):
            def update():
                try:
                    refresh(manager, key)
                finally:
                    _background.release()
            threading.Thread(target=update, name='project-cover-refresh', daemon=True).start()
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None
