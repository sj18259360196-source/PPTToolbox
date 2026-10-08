"""Owner-only signed GitHub releases. No project scanning, model calls or shell API."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

from scripts.release_info import VERSION
from distribution.install_local import no_reparse

MAX_INSTALLER = 2 * 1024 ** 3
MAX_JSON = 256 * 1024
BUSY = {'checking', 'downloading', 'verifying', 'installing'}
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('更新版本号无效')
    return tuple(map(int, value.split('.')))


def config(root):
    value = json.loads((Path(root) / 'distribution/release_config.json').read_text('utf-8'))
    if not REPOSITORY.fullmatch(value.get('repository', '')):
        raise ValueError('发行仓库配置无效')
    return value


def safe_url(url, repository=None, asset=False):
    if not isinstance(url, str):
        raise ValueError('下载地址无效')
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ValueError('更新只接受官方发行仓库的 HTTPS 地址')
    if repository:
        prefix = f'/{repository}/releases/download/' if asset else f'/repos/{repository}/releases/'
        if parsed.hostname != ('github.com' if asset else 'api.github.com') or not parsed.path.startswith(prefix) or parsed.query:
            raise ValueError('下载地址与发行仓库不符')
    elif parsed.hostname not in {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
        raise ValueError('更新下载重定向到未允许的地址')
    return url


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Transport:
    def open(self, url):
        safe_url(url)
        req = Request(url, headers={'User-Agent': f'PPTToolbox/{VERSION}', 'Accept': 'application/octet-stream'})
        return build_opener(ReleaseRedirect()).open(req, timeout=25)

    def read(self, url, maximum=MAX_JSON):
        with self.open(url) as response:
            raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('更新信息超过大小限制')
        return raw


def verified_manifest(raw, signature, cfg):
    """Verify exact bytes before interpreting executable names, paths or hashes."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        envelope = json.loads(signature)
        key = cfg['trusted_keys'][envelope['key_id']]
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(envelope['signature'], validate=True), raw)
    except Exception as exc:
        raise ValueError('更新签名校验失败，已停止下载或安装') from exc
    value = json.loads(raw)
    number = value.get('version')
    version(number)
    expected_name = f'PPTToolbox-{number}-Setup.exe'
    asset = value.get('asset', {})
    if (value.get('format') != 'ppttoolbox-update/1' or value.get('product') != 'PPT Toolbox'
            or value.get('repository') != cfg['repository'] or value.get('tag') != 'v' + number
            or value.get('platform') != 'windows-x64' or value.get('updater_version') != 1
            or asset.get('name') != expected_name or type(asset.get('size')) is not int
            or not 0 < asset['size'] <= MAX_INSTALLER
            or not re.fullmatch('[0-9a-f]{64}', str(asset.get('sha256', '')))):
        raise ValueError('发行清单不适用于此软件或当前更新器')
    expected_url = f'https://github.com/{cfg["repository"]}/releases/download/v{number}/{expected_name}'
    if asset.get('url') != expected_url:
        raise ValueError('安装包地址与签名发行版本不一致')
    if value.get('database_schema') != {'minimum': 1, 'maximum': 1}:
        raise ValueError('此更新不兼容当前管理数据库，请查看发行说明')
    if not isinstance(value.get('notes', ''), str) or len(value.get('notes', '')) > 20000:
        raise ValueError('发行说明无效')
    return value


def blockers(manager):
    from distribution.update_installed import audit
    try:
        with sqlite3.connect(manager.data / 'manager.sqlite3') as db:
            audit(manager.data, db)
        # A queued assistant job can begin writing without another UI request.
        tasks = manager.store.get('pptagent_tasks', [])
        tasks = tasks.values() if isinstance(tasks, dict) else tasks
        if any(t.get('status') in {'queued', 'running'} for t in tasks):
            return ['驻留 PPTAgent 仍有待执行或正在执行的任务']
        return []
    except Exception as exc:
        return [str(exc)]


def installer_process_identity(pid):
    """Return creation time, None for a stopped process, or unknown on access failure."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name != 'nt':
        from .execution import process_alive
        return 'unknown' if process_alive(pid) is not False else None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return 'unknown' if ctypes.get_last_error() == 5 else None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return 'unknown'
        if code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return 'unknown'
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


class Updater:
    def __init__(self, manager, transport=None, launch=None):
        self.manager = manager
        self.cfg = config(manager.root)
        self.transport = transport or Transport()
        self.launch = launch or self._launch
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.stopped = threading.Event()
        self.job = None
        self.monitor = None
        self.cache = manager.data / 'software-updates'
        self.state = manager.store.get('software_update_state', {'phase': 'idle'})
        if self.state.get('phase') in {'checking', 'downloading', 'verifying'}:
            self.state.update(phase='error', error='上次更新检查或下载已中断，可以重试')

    def _set(self, **values):
        with self.lock:
            self.state.update(values)
            self.manager.store.set('software_update_state', self.state)

    def _installed(self):
        root = self.manager.root.parent
        try:
            location = json.loads((root / 'location.json').read_text('utf-8'))
            return no_reparse(location['data_directory']) == self.manager.data and (root / 'PPTToolbox.exe').is_file()
        except (OSError, ValueError, KeyError):
            return False

    def status(self):
        with self.lock:
            if self.state.get('phase') == 'installing':
                result_path = no_reparse(self.cache / 'install-result.json')
                if result_path.is_file():
                    result = json.loads(result_path.read_text('utf-8-sig'))
                    if result.get('version') == self.state.get('release', {}).get('version'):
                        self._set(phase='installed' if result.get('exit_code') == 0 else 'error',
                                  error='' if result.get('exit_code') == 0 else '安装未完成，原版本保留。请查看安装日志后重试',
                                  install_result=result)
                if self.state.get('phase') == 'installing':
                    helper = self.state.get('install_helper')
                    elapsed = time.time() - self.state.get('install_started', 0)
                    if isinstance(helper, dict):
                        identity = installer_process_identity(helper.get('pid'))
                        interrupted = identity is None or (identity != 'unknown'
                            and helper.get('created') not in (None, 'unknown', identity))
                    else:
                        # Covers a crash between recording intent and launching the helper.
                        interrupted = elapsed > 120
                    if interrupted:
                        self._set(phase='error', error='安装过程已中断。请查看安装日志，必要时重新运行完整安装包。')
            value = copy.deepcopy(self.state)
        return {**value, 'installed_version': VERSION, 'repository': self.cfg['repository'],
                'configured': bool(self.cfg.get('trusted_keys')), 'can_install': self._installed(),
                'automatic': self.manager.store.get('software_update_preferences', {}).get('automatic', True)}

    def configure(self, body):
        if set(body) != {'automatic'} or type(body['automatic']) is not bool:
            raise ValueError('需要 automatic 布尔值')
        self.manager.store.set('software_update_preferences', body)
        return self.status()

    def _start(self, fn, phase):
        with self.lock:
            if self.job and self.job.is_alive() or self.state.get('phase') in {'installing', 'deferred'}:
                raise ValueError('已有更新任务，请等待或取消后重试')
            self.cancelled.clear()
            self._set(phase=phase, error='', blockers=[])
            def run():
                try:
                    fn()
                except Exception as exc:
                    self._set(phase='cancelled' if self.cancelled.is_set() else 'error',
                              error='' if self.cancelled.is_set() else str(exc)[:500])
            self.job = threading.Thread(target=run, daemon=True, name='software-update')
            self.job.start()
        return self.status()

    def check(self):
        return self._start(self._check, 'checking')

    def _check(self):
        self._set(last_check=time.time())  # Failures are also throttled to once a day.
        if not self.cfg.get('trusted_keys'):
            raise ValueError('尚未配置发行签名公钥')
        repo = self.cfg['repository']
        url = safe_url(f'https://api.github.com/repos/{repo}/releases/latest', repo)
        release = json.loads(self.transport.read(url))
        if release.get('draft') or release.get('prerelease'):
            raise ValueError('当前更新源没有可用的正式发行版')
        assets = {row['name']: row for row in release.get('assets', [])}
        try:
            raw = self.transport.read(safe_url(assets[self.cfg['manifest']]['browser_download_url'], repo, True))
            sig = self.transport.read(safe_url(assets[self.cfg['signature']]['browser_download_url'], repo, True))
        except KeyError as exc:
            raise ValueError('发行版缺少已签名的更新清单，请稍后重试') from exc
        manifest = verified_manifest(raw, sig, self.cfg)
        asset = manifest['asset']
        entry = assets.get(asset['name'], {})
        if (release.get('tag_name') != manifest['tag'] or entry.get('browser_download_url') != asset['url']
                or entry.get('size') != asset['size']):
            raise ValueError('GitHub 发行文件与签名清单不一致')
        if entry.get('digest') and entry['digest'] != 'sha256:' + asset['sha256']:
            raise ValueError('GitHub 文件摘要与签名清单不一致')
        highest = self.manager.store.get('software_update_highest', VERSION)
        if version(manifest['version']) < version(highest):
            raise ValueError('更新源返回了已发现版本之前的发行版，已拒绝降级')
        self.manager.store.set('software_update_highest', manifest['version'])
        self._set(release=manifest, signed_manifest=base64.b64encode(raw).decode(),
                  signature=base64.b64encode(sig).decode(), received=0,
                  phase='available' if version(manifest['version']) > version(VERSION) else 'current')

    def _release(self):
        raw = base64.b64decode(self.state['signed_manifest'], validate=True)
        sig = base64.b64decode(self.state['signature'], validate=True)
        manifest = verified_manifest(raw, sig, self.cfg)
        if version(manifest['version']) <= version(VERSION):
            raise ValueError('只允许安装比当前软件更新的版本')
        return manifest

    def download(self):
        self._release()
        return self._start(self._download, 'downloading')

    def _download(self):
        manifest = self._release()
        asset = manifest['asset']
        cache = no_reparse(self.cache)
        cache.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(cache).free < asset['size'] * 2 + 512 * 1024 ** 2:
            raise ValueError('可用磁盘空间不足，请腾出空间后重试')
        target = no_reparse(cache / asset['name'])
        part = no_reparse(cache / (asset['name'] + '.part'))
        digest = hashlib.sha256()
        received = 0
        deadline = time.monotonic() + 3600
        try:
            with self.transport.open(asset['url']) as response, part.open('wb') as output:
                last = 0.0
                while True:
                    if self.cancelled.is_set() or self.stopped.is_set():
                        raise ValueError('下载已取消')
                    if time.monotonic() > deadline:
                        raise ValueError('下载超时，请重试')
                    chunk = response.read(512 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > asset['size']:
                        raise ValueError('安装包超过签名清单的大小')
                    output.write(chunk)
                    digest.update(chunk)
                    if time.monotonic() - last > .4:
                        self._set(received=received)
                        last = time.monotonic()
            self._set(phase='verifying', received=received)
            if received != asset['size'] or digest.hexdigest() != asset['sha256']:
                raise ValueError('安装包不完整或校验失败，已丢弃下载文件')
            if self.cancelled.is_set():
                raise ValueError('下载已取消')
            os.replace(part, target)
            self._set(phase='ready', received=received)
        finally:
            part.unlink(missing_ok=True)

    def cancel(self):
        with self.lock:
            phase = self.state.get('phase')
            if phase == 'installing':
                raise ValueError('安装程序已启动，请在安装程序中处理')
            self.cancelled.set()
            if phase == 'deferred':
                self._set(phase='ready', blockers=[])
            elif phase not in {'downloading', 'verifying'}:
                raise ValueError('当前没有可取消的下载或安装排队')
        return self.status()

    def install(self):
        with self.lock:
            if self.state.get('phase') not in {'ready', 'deferred'}:
                raise ValueError('请先下载并校验安装包')
            if not self._installed():
                raise ValueError('源码或便携预览不能直接更新正式安装，请手动运行安装包')
            manifest = self._release()
            pending = blockers(self.manager)
            if pending:
                self._set(phase='deferred', blockers=pending)
            else:
                target = no_reparse(self.cache / manifest['asset']['name'])
                if not target.is_file() or target.stat().st_size != manifest['asset']['size']:
                    raise ValueError('已下载的安装包发生变化，请重新下载')
                with target.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != manifest['asset']['sha256']:
                    raise ValueError('已下载的安装包发生变化，请重新下载')
                self._set(phase='installing', blockers=[], error='', install_helper=None,
                          install_started=time.time())
                try:
                    helper = self.launch(target, manifest)
                    self._set(install_helper=helper)
                except Exception as exc:
                    self._set(phase='ready', error='无法启动安装程序 ' + str(exc)[:300])
                    raise
        return self.status()

    def _launch(self, target, manifest):
        if os.name != 'nt':
            raise ValueError('此安装包仅支持 Windows')
        from scripts.runtime_env import powershell_path
        helper = no_reparse(self.cache / 'install-update.ps1')
        helper.write_bytes((self.manager.root / 'distribution/install_update.ps1').read_bytes())
        result = no_reparse(self.cache / 'install-result.json')
        result.unlink(missing_ok=True)
        log = no_reparse(self.cache / 'install.log')
        args = [powershell_path(), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(helper), '-Installer', str(target), '-ExpectedSha256', manifest['asset']['sha256'],
                '-Destination', str(self.manager.root.parent), '-Version', manifest['version'],
                '-ResultPath', str(result), '-LogPath', str(log)]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)
        return {'pid': process.pid, 'created': installer_process_identity(process.pid)}

    def start(self):
        def monitor():
            while not self.stopped.wait(20):
                try:
                    state = self.status()
                    if state['phase'] == 'deferred':
                        self.install()
                    elif (self._installed() and state['automatic'] and state['configured']
                          and state['phase'] not in BUSY | {'ready', 'available'}
                          and time.time() - state.get('last_check', 0) >= 86400):
                        self.check()
                except Exception:
                    pass  # State holds network/validation failures; never stop project work.
        self.monitor = threading.Thread(target=monitor, daemon=True, name='software-update-monitor')
        self.monitor.start()

    def close(self):
        self.stopped.set()
        self.cancelled.set()
