"""Optional Windows tray host for the existing authenticated managed service."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def identity(data):
    return hashlib.sha256(str(Path(data).resolve()).casefold().encode()).hexdigest()[:24]


class Instance:
    def __init__(self, data):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args in (("CreateMutexW", [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]),
                           ("CreateEventW", [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p])):
            function = getattr(self.kernel, name)
            function.argtypes = args
            function.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.SetEvent.argtypes = [ctypes.c_void_p]
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        key = identity(data)
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\PPTManaged-" + key)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.existing = ctypes.get_last_error() == 183
        self.show_event = self.kernel.CreateEventW(None, False, False, "Local\\PPTManagedShow-" + key)
        if not self.show_event:
            self.kernel.CloseHandle(self.mutex)
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        self.kernel.CloseHandle(self.show_event)
        self.kernel.CloseHandle(self.mutex)


def launch_for_agent(manager):
    """Opt-in only. Failure never prevents MCP initialization or fabricates success."""
    preferences = manager.store.get("desktop_preferences", {})
    if not preferences.get("agent_start") or sys.platform != "win32":
        return
    try:
        executable = Path(sys.executable).with_name("pythonw.exe")
        if not executable.is_file():
            raise ValueError("pythonw.exe is required for background startup")
        args = [str(executable), str(manager.root / "manager.py"), "--data-dir", str(manager.data), "desktop"]
        vendor = preferences.get("vendor")
        if vendor:
            args += ["--vendor", vendor]
        with (manager.data / "desktop-startup.log").open("ab") as log:
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
    except Exception as exc:
        manager.store.event("desktop.start_failed", str(exc), source="mcp", status="error")


def run(data, vendor=None, show=False, smoke=False, agent_start=False):
    if sys.platform != "win32":
        raise RuntimeError("The tray host requires Windows")
    if vendor:
        vendor = Path(vendor).resolve(strict=True)
        sys.path.insert(0, str(vendor))
    import webview
    # Owner-triggered exports use Blob downloads and the native save dialog.
    webview.settings['ALLOW_DOWNLOADS'] = True
    import pystray
    from PIL import Image, ImageDraw
    from .server import LocalServer
    from .storage import Store
    instance = Instance(data)
    if instance.existing:
        if show:
            instance.kernel.SetEvent(instance.show_event)
        instance.close()
        return
    server = None
    tray = None
    try:
        server = LocalServer(data)
        manager = server.manager
        if agent_start:
            manager.store.set("desktop_preferences", {"agent_start": True, "vendor": str(vendor) if vendor else None})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        title = "PPT Toolbox · " + identity(data)[:8]
        first_launch=not manager.store.get("desktop_onboarding_shown",False)
        manager.store.set("desktop_onboarding_shown",True)
        query="/?desktop_visible="+("1" if show else "0")+("&onboarding=1" if first_launch else "")
        window = webview.create_window(title, server.origin + query + "#token=" + server.token,
                                       width=1380, height=920, min_size=(900, 640),
                                       hidden=not show, background_color="#f5f7fb")
        exiting = threading.Event()
        manager.store.set("desktop_runtime", {"state": "running", "pid": os.getpid(),
                                              "origin": server.origin, "title": title,
                                              "root": str(manager.root)})
        manager.store.event("desktop.started", "Desktop host started", details={"pid": os.getpid(), "hidden": not show})

        visibility={"shown":show,"minimized":False}
        def notify_visibility():
            if not window.events.loaded.is_set():return
            visible=visibility["shown"] and not visibility["minimized"]
            try:
                window.evaluate_js("window.__pptDesktopVisible="+str(visible).lower()+";window.dispatchEvent(new Event('ppt-desktop-visibility'));")
            except Exception:pass
        def show_window(*_):
            was_minimized=visibility["minimized"]
            visibility.update(shown=True,minimized=False)
            window.show()
            if was_minimized:window.restore()
            notify_visibility()
        def loaded_visibility():
            window.events.loaded.wait(5)
            notify_visibility()
        def minimized():
            visibility["minimized"]=True;notify_visibility()
        def restored():
            visibility["minimized"]=False;notify_visibility()
        def closing():
            if exiting.is_set():
                return True
            visibility["shown"]=False
            # Closing runs on the native UI thread. JS evaluation must not block
            # that thread while WebView2 marshals its result back to the UI.
            threading.Thread(target=notify_visibility,daemon=True).start()
            window.hide()
            manager.store.event("desktop.hidden", "Window hidden to tray")
            return False

        def stop(*_):
            # Stopping this UI does not stop independently owned MCP/workflow workers.
            with server.write_lock:
                if exiting.is_set():
                    return
                if getattr(server.workbench, "running", set()):
                    show_window()
                    manager.store.event("desktop.exit_deferred", "A UI request is still running; exit deferred", status="waiting")
                    return
                server.closing = True
                exiting.set()
            window.destroy()

        def events():
            window.events.loaded.wait(30)
            while not exiting.is_set():
                from .update_signal import requested, idle
                if requested(data) and idle(data):
                    stop()
                    continue
                if instance.kernel.WaitForSingleObject(instance.show_event, 300) == 0:
                    show_window()
                    manager.store.event("desktop.shown", "Window restored from launcher")

        window.events.closing += closing
        window.events.loaded += loaded_visibility
        window.events.minimized += minimized
        window.events.restored += restored
        window.events.closed += lambda: exiting.set()
        image = Image.new("RGB", (64, 64), "#28655a")
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 23, 52, 51), outline="white", width=4)
        draw.rectangle((23, 13, 41, 23), outline="white", width=4)
        tray = pystray.Icon("ppt-managed-" + identity(data), image, "PPT 工具箱",
                           pystray.Menu(pystray.MenuItem("打开工具箱", show_window, default=True),
                                        pystray.MenuItem("退出界面", stop)))
        threading.Thread(target=tray.run, daemon=True).start()
        threading.Thread(target=events, daemon=True).start()
        if smoke:
            def verify():
                try:
                    if not window.events.loaded.wait(40):
                        raise TimeoutError("WebView page did not load")
                    deadline = time.monotonic() + 20
                    expected_page = "概况"
                    while time.monotonic() < deadline:
                        body = window.evaluate_js("document.body.innerText")
                        if expected_page in body:
                            break
                        time.sleep(.2)
                    assert expected_page in body, body
                    user = ctypes.WinDLL("user32")
                    user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                    user.FindWindowW.restype = ctypes.c_void_p
                    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
                    handle = user.FindWindowW(None, title)
                    assert handle
                    hidden = not bool(user.IsWindowVisible(handle))
                    # Exercise a second launcher against the same live singleton.
                    args = [sys.executable, str(manager.root/"manager.py"), "--data-dir", str(manager.data),
                            "desktop", "--show"]
                    if vendor:
                        args += ["--vendor", str(vendor)]
                    subprocess.run(args, check=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                    time.sleep(.4)
                    visible = bool(user.IsWindowVisible(handle))
                    closing()
                    time.sleep(.4)
                    hidden_again = not bool(user.IsWindowVisible(handle))
                    assert visible and hidden_again
                    manager.store.set("desktop_smoke", {"passed": True, "initial_hidden": hidden,
                                                       "show_visible": visible, "close_hides": hidden_again,
                                                       "body_loaded": True, "duplicate_launcher_restored": True})
                except Exception as exc:
                    manager.store.set("desktop_smoke", {"passed": False, "error": str(exc)})
                finally:
                    stop()
            threading.Thread(target=verify, daemon=True).start()
        webview.start(gui="edgechromium", storage_path=str(manager.data / "webview"), private_mode=False)
    finally:
        if tray:
            tray.stop()
        if server:
            server.shutdown()
            server.server_close()
            server.manager.store.set("desktop_runtime", {"state": "stopped", "pid": os.getpid()})
            server.manager.store.event("desktop.stopped", "Desktop host stopped; independent Agent workers unchanged")
        instance.close()
    if smoke and not Store(data).get("desktop_smoke", {}).get("passed"):
        raise RuntimeError("Desktop smoke failed; inspect desktop_smoke in the isolated manager")
