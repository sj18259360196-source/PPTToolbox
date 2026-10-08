"""Relocatable distribution entry. No ambient Python, old checkout or old data."""
from __future__ import annotations

import os
import json
from pathlib import Path
import sys


def arguments(bundle, args):
    args = list(args)
    portable = "--portable" in args
    if portable:args.remove("--portable")
    data = bundle / "data"
    location = bundle / "location.json"
    if location.is_file():
        value = json.loads(location.read_text(encoding='utf-8'))
        data = Path(value['data_directory']).expanduser()
        if not data.is_absolute():
            raise ValueError('Configured data directory must be absolute')
    if "--data-dir" in args:
        index = args.index("--data-dir")
        if index + 1 >= len(args):
            raise ValueError("--data-dir requires a value")
        data = Path(args[index + 1]).resolve()
        del args[index:index + 2]
    elif not location.is_file() and not portable:
        raise ValueError("请通过正式安装启动；独立便携模式需要明确指定 --portable")
    return ["--data-dir", str(data), *(args or ["desktop", "--show", "--agent-start"])]


def main():
    bundle = Path(__file__).resolve().parent
    app = bundle / "app"
    sys.path.insert(0, str(app))
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Only the distribution's interpreter and modules are used by child workers.
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)
    sys.dont_write_bytecode = True
    requested=sys.argv[1:]
    if not (bundle/"location.json").exists() and "--portable" not in requested and "--data-dir" not in requested:
        from distribution.update_installed import discover, upgrade
        local=Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData/Local"))
        destination=discover(local)
        if destination is None:
            raise ValueError("请先运行 PPTToolbox.exe 完成安装与目录选择")
        upgrade(bundle,destination)
        import subprocess
        # Run the installed interpreter and entry, so app/data identities agree.
        return subprocess.call([str(destination/"runtime/python.exe"),"-B",str(destination/"portable.py"),*requested],
                               stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if (bundle/"UPDATE_PENDING.json").exists():
        raise ValueError("程序更新尚未完成，请先检查更新备份")
    argv = arguments(bundle, requested)
    if len(argv) > 2 and argv[2] == "mcp":
        from toolbox_manager.storage import Store
        store = Store(argv[1])
        if store.get("desktop_preferences") is None:
            store.set("desktop_preferences", {"agent_start": True, "vendor": None})
    import manager
    sys.argv = [str(app / "manager.py"), *argv]
    return manager.main()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as exc:
        if ("desktop" in sys.argv or len(sys.argv)==1) and "--smoke" not in sys.argv:
            if os.name=="nt":
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,str(exc),"PPT 工具箱启动未完成",0x10)
        elif sys.stderr:
            print(str(exc),file=sys.stderr)
        raise SystemExit(1)
