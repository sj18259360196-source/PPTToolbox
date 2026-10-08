"""Shared executable selection for managed and direct toolbox calls."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

POWERSHELL_ENV = 'PPT_TOOLBOX_POWERSHELL'


def powershell_path(explicit=None):
    configured = explicit or os.environ.get(POWERSHELL_ENV)
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError('Configured PowerShell does not exist: ' + str(path))
        return str(path.resolve())
    if os.name != 'nt':
        return None
    preferred = Path(r'C:\Program Files\PowerShell\7\pwsh.exe')
    if preferred.is_file():
        return str(preferred)
    return shutil.which('pwsh') or shutil.which('powershell')


def child_environment(explicit=None):
    env = dict(os.environ)
    shell = powershell_path(explicit)
    if shell:
        env[POWERSHELL_ENV] = shell
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def python_tool_argv(executable, package, entry, arguments, *, isolated=False):
    """Share one bootstrap; preserve configured interpreter dependencies in development."""
    root = Path(package).resolve()
    target = (root / entry).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Python entry must stay inside the active package')
    # Safe path and environment handling exclude cwd/PYTHONPATH injection while
    # retaining dependencies installed for the explicitly configured interpreter.
    # Delivered embedded Python also has its own isolated ._pth; release probes
    # additionally disable user site packages so a developer machine cannot mask gaps.
    flags = ['-I'] if isolated else ['-E', '-P']
    return [str(executable), '-B', *flags, '-X', 'utf8',
            str(Path(__file__).with_name('python_entry.py')),
            str(root), target.relative_to(root).as_posix(), '--', *arguments]


from contextlib import contextmanager


class OfficeBusy(RuntimeError):
    code = "office_busy"


@contextmanager
def office_guard(path=None):
    """One managed Office writer per shared manager data directory."""
    import json
    from pathlib import Path
    path = path or os.environ.get("PPT_MANAGED_OFFICE_LOCK")
    if not path:
        yield
        return
    lock = Path(path)
    uncertain = False
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise OfficeBusy("Managed Office writer or interrupted lock exists; inspect before explicit recovery")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump({"pid": os.getpid(), "scope": "managed Office only"}, handle)
        yield
    except Exception as exc:
        uncertain = isinstance(exc, __import__("subprocess").TimeoutExpired) or getattr(exc, "code", None) == "office_timeout"
        raise
    finally:
        if not uncertain:
            lock.unlink(missing_ok=True)
