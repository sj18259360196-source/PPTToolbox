"""Shared, offline utilities. No model calls, no downloads, no Office side effects."""
from __future__ import annotations
import hashlib, json, math, os, tempfile, time
from pathlib import Path
from typing import Any
if __package__:
    from .evidence_session import measured
    from .release_info import VERSION
else:
    from evidence_session import measured
    from release_info import VERSION
STATUSES = {"passed", "failed", "blocked", "not_run", "not_applicable"}
TASK_REVIEW_STATUSES = ("passed", "needs_changes", "blocked")

def read_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8-sig") as handle:
        return json.load(handle)

def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        for attempt in range(8):
            try:
                os.replace(temp, target)
                break
            except PermissionError as exc:
                if os.name != 'nt' or getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 7:
                    raise
                time.sleep(min(0.05 * (2 ** attempt), 0.5))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

@measured("file_hash")
def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def resolve_asset(base: str | Path, relative: str) -> Path:
    """Require persistent inputs within the scene/project folder, including symlinks."""
    root = Path(base).resolve()
    item = Path(relative)
    if item.is_absolute():
        raise ValueError(f"Use a project-relative path, not an absolute path: {relative}")
    result = (root / item).resolve()
    if not result.is_relative_to(root):
        raise ValueError(f"Path leaves the project folder: {relative}")
    if not result.is_file():
        raise FileNotFoundError(result)
    return result

def normalize_text(text: str) -> str:
    # Normalize transport line breaks only. Never remove meaningful spaces/signs.
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\v", "\n")

def bbox_to_points(box: list[float], canvas: dict) -> list[float]:
    """All scene geometry uses the one global logical canvas; fonts are already pt."""
    sx = canvas["width_pt"] / canvas["width"]
    sy = canvas["height_pt"] / canvas["height"]
    if canvas.get("mapping", "uniform") == "uniform" and not math.isclose(sx, sy, rel_tol=1e-7):
        raise ValueError("Uniform mapping requires matching logical and physical aspect ratios")
    x, y, w, h = box
    return [x * sx, y * sy, w * sx, h * sy]

def walk_objects(objects: list[dict]):
    for obj in objects:
        yield obj
        if obj["kind"] == "group":
            yield from walk_objects(obj["children"])


from contextlib import contextmanager
import shutil

@contextmanager
def staged_directory(destination: str | Path):
    """Write into a script-owned staging folder, publish only after full success."""
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'Choose a new output directory, do not overwrite evidence: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.' + target.name + '.staging-', dir=target.parent))
    try:
        yield stage
        if target.exists() or target.is_symlink():
            raise FileExistsError(f'Output appeared during execution: {target}')
        # Windows readers can briefly hold the new tree; retain atomic publication.
        for attempt in range(8):
            if target.exists() or target.is_symlink():
                raise FileExistsError(f'Output appeared during execution: {target}')
            try:
                stage.rename(target)
                break
            except PermissionError as exc:
                if os.name != 'nt' or getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 7:
                    raise
                time.sleep(min(0.05 * (2 ** attempt), 0.5))
    finally:
        if stage.exists():
            shutil.rmtree(stage)  # Only the exact staging directory created above.
