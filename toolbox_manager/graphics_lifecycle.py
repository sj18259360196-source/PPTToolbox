"""Durable, bounded preview workers. Only the owned process/job may be stopped."""
from __future__ import annotations
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

TERMINAL = {'completed', 'failed', 'timed_out', 'cancelled', 'interrupted'}
_locks = {}
_guard = threading.Lock()
_children = {}
_held = threading.local()
READ_RETRY_SECONDS = .25

def read_observation(path, binary=False):
    """Bound transient Windows sharing failures; mandatory reads still fail closed."""
    path = Path(path)
    deadline = time.monotonic()+READ_RETRY_SECONDS
    while True:
        try:
            return path.read_bytes() if binary else path.read_text(encoding='utf-8')
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.01)

def atomic(path, value):
    path = Path(path)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    # Windows readers can briefly hold a handle without delete sharing.
    # Keep publication atomic and bound the retry instead of losing progress/results.
    deadline = time.monotonic()+2
    while True:
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.01)

def identity(pid):
    if os.name != 'nt':
        try:
            return Path(f'/proc/{pid}/stat').read_text().split(') ')[1].split()[19]
        except (OSError, IndexError):
            return None
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = w.HANDLE
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() not in (87, 1168):
            raise OSError('Cannot confirm preview process identity')
        return None
    try:
        code = w.DWORD()
        if not k.GetExitCodeProcess(w.HANDLE(handle), ctypes.byref(code)):
            raise OSError('Cannot confirm preview process exit')
        if code.value != 259:
            return None
        times = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(w.HANDLE(handle), *[ctypes.byref(t) for t in times]):
            raise OSError('Cannot confirm preview process creation identity')
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        k.CloseHandle(w.HANDLE(handle))

class WindowsJob:
    """A private job kills its members if the supervising host exits."""
    def __init__(self, process, name):
        from ctypes import wintypes as w
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.handle = self.k.CreateJobObjectW(None, name)
        class BASIC(ctypes.Structure):
            _fields_ = [('times', ctypes.c_longlong*2), ('flags', w.DWORD),
                        ('min', ctypes.c_size_t), ('max', ctypes.c_size_t),
                        ('active', w.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('basic', BASIC), ('io', ctypes.c_ulonglong*6),
                        ('limits', ctypes.c_size_t*4)]
        info = EXTENDED()
        info.basic.flags = 0x2000
        if not self.handle or not self.k.SetInformationJobObject(w.HANDLE(self.handle), 9, ctypes.byref(info), ctypes.sizeof(info)) or not self.k.AssignProcessToJobObject(w.HANDLE(self.handle), w.HANDLE(int(process._handle))):
            self.close()
            raise OSError('Cannot establish private preview process job')
    def stop(self):
        from ctypes import wintypes as w
        if not self.k.TerminateJobObject(w.HANDLE(self.handle), 1):
            raise OSError('Cannot terminate owned preview job')
    def close(self):
        if self.handle:
            from ctypes import wintypes as w
            self.k.CloseHandle(w.HANDLE(self.handle))
            self.handle = None

class PreviewLifecycle:
    def __init__(self, data, worker=None, on_terminal=None):
        self.root = Path(data)/'graphics-preview-calls'
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker = Path(worker or Path(__file__).resolve().parents[1]/'scripts/graphics_preview_worker.py')
        self.on_terminal = on_terminal

    def directory(self, call_id):
        if not isinstance(call_id, str) or not call_id or len(call_id)>128 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in call_id):
            raise ValueError('Invalid preview call_id')
        return self.root/call_id

    @contextmanager
    def lock(self, call_id):
        key = str(self.directory(call_id))
        with _guard:
            local_lock = _locks.setdefault(key, threading.RLock())
        with local_lock:
            held = getattr(_held, 'keys', set())
            if key in held:
                yield
                return
            lock_path = self.root/(call_id+'.lock')
            with lock_path.open('a+b') as handle:
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                limit = time.monotonic()+30
                while True:
                    handle.seek(0)
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= limit:
                            raise TimeoutError('Preview state is locked by another manager process')
                        time.sleep(.02)
                _held.keys = held | {key}
                try:
                    yield
                finally:
                    _held.keys = held
                    handle.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def start(self, request, call_id=None, timeout=30):
        timeout = float(timeout)
        if not 0.1 <= timeout <= 120:
            raise ValueError('Preview timeout must be between 0.1 and 120 seconds')
        call_id = call_id or uuid.uuid4().hex
        directory = self.directory(call_id)
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        with self.lock(call_id):
            if (directory/'state.json').exists():
                state = json.loads(read_observation(directory/'state.json'))
                if state['input_sha256'] != digest:
                    raise ValueError('Preview call_id already belongs to a different input')
                return self.query(call_id)
            directory.mkdir(exist_ok=False)
            atomic(directory/'request.json', request)
            state = dict(format='graphics-preview-call/1', call_id=call_id, input_sha256=digest,
                         status='running', step='starting', started_at=time.time(), deadline=time.time()+timeout,
                         launch_clock=time.perf_counter(),
                         owner_pid=os.getpid(), owner_identity=identity(os.getpid()), worker=str(self.worker))
            atomic(directory/'state.json', state)
            try:
                with (directory/'worker.log').open('wb') as log:
                    process = subprocess.Popen([sys.executable, '-B', '-I', str(self.worker), str(directory)],
                                               stdout=log, stderr=log, start_new_session=os.name != 'nt',
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                state['job_name'] = 'PPTToolboxPreview-'+uuid.uuid4().hex
                job = WindowsJob(process, state['job_name']) if os.name == 'nt' else None
                state.update(pid=process.pid, process_identity=identity(process.pid))
                if not state['process_identity']:
                    raise OSError('Preview process creation identity unavailable')
                _children[str(directory)] = (process, job)
                atomic(directory/'state.json', state)
                (directory/'launch').write_text('ready', encoding='utf-8')
                threading.Thread(target=self._supervise, args=(call_id, dict(state)), daemon=True,
                                 name='graphics-preview-'+call_id).start()
            except Exception as exc:
                stopped = True
                if 'process' in locals():
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        stopped = False
                state.update(status='failed' if stopped else 'outcome_unknown', error=str(exc))
                if stopped:
                    state['ended_at'] = time.time()
                atomic(directory/'state.json', state)
            return self.query(call_id)

    def _stop(self, directory, state):
        owned = _children.get(str(directory))
        if identity(state.get('pid', -1)) != state.get('process_identity'):
            return True
        if owned:
            process, job = owned
            if job:
                job.stop()
            elif os.name != 'nt':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return False
        else:
            if os.name == 'nt':
                from ctypes import wintypes as w
                k = ctypes.WinDLL('kernel32', use_last_error=True)
                k.OpenJobObjectW.restype = w.HANDLE
                k.OpenProcess.restype = w.HANDLE
                job = k.OpenJobObjectW(0x0c, False, state.get('job_name'))
                process = k.OpenProcess(0x100400, False, state['pid'])
                if not job or not process:
                    if job: k.CloseHandle(w.HANDLE(job))
                    if process: k.CloseHandle(w.HANDLE(process))
                    return False
                try:
                    member = w.BOOL()
                    if not k.IsProcessInJob(w.HANDLE(process), w.HANDLE(job), ctypes.byref(member)) or not member.value:
                        return False
                    if not k.TerminateJobObject(w.HANDLE(job), 1):
                        return False
                    if k.WaitForSingleObject(w.HANDLE(process), 5000) != 0:
                        return False
                finally:
                    k.CloseHandle(w.HANDLE(process))
                    k.CloseHandle(w.HANDLE(job))
            else:
                if os.getpgid(state['pid']) != state['pid']:
                    return False
                os.killpg(state['pid'], signal.SIGKILL)
                until = time.monotonic()+5
                while identity(state['pid']) == state['process_identity'] and time.monotonic()<until:
                    time.sleep(.02)
        return identity(state['pid']) != state['process_identity']

    def query(self, call_id, cancel=False, include_image=True):
        query_clock = time.perf_counter()
        directory = self.directory(call_id)
        with self.lock(call_id):
            def unavailable(exc, state=None):
                response = {**(state or {}), 'call_id': call_id, 'status': 'outcome_unknown',
                            'execution_status': (state or {}).get('status', 'unconfirmed'),
                            'retrieval_status': 'unavailable', 'retrieval_error': str(exc),
                            'query': {'operation': 'graphics.preview_status', 'call_id': call_id}}
                try:
                    atomic(directory/'supervision-error.json', response)
                except OSError:
                    pass
                return response
            try:
                state = json.loads(read_observation(directory/'state.json'))
            except PermissionError as exc:
                return unavailable(exc)
            if state['status'] not in TERMINAL:
                step = directory/'progress.json'
                if step.exists():
                    try:
                        progress = json.loads(read_observation(step))
                        state['step'] = progress.get('step')
                        if progress.get('timing'):
                            state['timing'] = progress['timing']
                            entry = progress['timing'].get('worker_entry_clock')
                            if entry is not None and state.get('launch_clock') is not None:
                                state['timing']['launch_to_worker_ms'] = round(max(0, entry-state['launch_clock'])*1000, 3)
                        state.pop('progress_read_error', None)
                    except PermissionError as exc:
                        # Progress is advisory. Retain the last confirmed step and
                        # continue identity, deadline and output integrity checks.
                        state['progress_read_error'] = str(exc)
                try:
                    observed_identity = identity(state['pid']) if state.get('pid') else None
                except OSError as exc:
                    state.update(status='outcome_unknown', error=str(exc))
                    atomic(directory/'state.json', state)
                    return {**state, 'query': {'operation': 'graphics.preview_status', 'call_id': call_id}}
                if not state.get('process_identity'):
                    state.update(status='outcome_unknown', error='Worker launch identity was not persisted')
                    atomic(directory/'state.json', state)
                    return {**state, 'query': {'operation': 'graphics.preview_status', 'call_id': call_id}}
                alive = observed_identity == state['process_identity']
                requested = state.get('termination_requested')
                if cancel:
                    requested = requested or 'cancelled'
                elif time.time() >= state['deadline']:
                    requested = requested or 'timed_out'
                # Recover an on-time publication before interpreting a late query/cancel.
                # A previously persisted termination request always wins over late output.
                result_file = directory/'result.json'
                if not alive and not state.get('termination_requested') and result_file.exists():
                    try:
                        published = json.loads(read_observation(result_file))
                    except PermissionError as exc:
                        return unavailable(exc, state)
                    if published.get('published_at', float('inf')) <= state['deadline']:
                        requested = None
                if requested:
                    state['termination_requested'] = requested
                    atomic(directory/'state.json', state)
                    try:
                        stopped = not alive or self._stop(directory, state)
                    except OSError as exc:
                        stopped = False
                        state['error'] = str(exc)
                    if stopped:
                        state.update(status=requested, ended_at=time.time())
                    else:
                        state['status'] = 'outcome_unknown'
                elif not alive:
                    # Re-read after exit: publication may have completed between
                    # the earlier progress read and the process-identity check.
                    if step.exists():
                        try:
                            final_progress = json.loads(read_observation(step))
                            state['step'] = final_progress.get('step', state['step'])
                            if final_progress.get('timing'):
                                state['timing'] = {**state.get('timing', {}), **final_progress['timing']}
                        except (OSError, ValueError) as exc:
                            state['progress_read_error'] = str(exc)
                    result_file = directory/'result.json'
                    if result_file.exists():
                        try:
                            result = json.loads(read_observation(result_file))
                        except PermissionError as exc:
                            return unavailable(exc, state)
                        if result.get('status') == 'completed':
                            try:
                                data = read_observation(directory/'preview.png', binary=True)
                            except PermissionError as exc:
                                return unavailable(exc, state)
                            if hashlib.sha256(data).hexdigest() != result['output_sha256']:
                                state.update(status='failed', error='Preview output hash mismatch')
                            else:
                                state.update(status='completed', output_sha256=result['output_sha256'], dimensions=result['dimensions'])
                        else:
                            state.update(status='failed', error=result.get('error', 'Worker failed'))
                    else:
                        state.update(status='interrupted', error='Worker exited without a published result')
                    state['ended_at'] = time.time()
                    if state.get('timing') and state.get('launch_clock') is not None:
                        state['timing']['completion_observed_ms'] = round((time.perf_counter()-state['launch_clock'])*1000, 3)
                if state['status'] in TERMINAL and state.get('timing'):
                    timing = state['timing']
                    for phase in timing.get('stages', []):
                        if phase.get('status') == 'running':
                            end = max(phase['start_ms'], (time.perf_counter()-timing['worker_entry_clock'])*1000)
                            phase.update(end_ms=round(end, 3), duration_ms=round(end-phase['start_ms'], 3),
                                         status='interrupted', end_observation='manager_after_'+state['status'])
                atomic(directory/'state.json', state)
            if state['status'] in TERMINAL:
                owned = _children.pop(str(directory), None)
                if owned and owned[1]:
                    owned[1].close()
                if self.on_terminal and not state.get('terminal_event_recorded'):
                    try:
                        self.on_terminal(dict(state))
                        state['terminal_event_recorded'] = True
                    except Exception as exc:
                        state['terminal_event_error'] = str(exc)
                    atomic(directory/'state.json', state)
            response = {**state, 'query': {'operation': 'graphics.preview_status', 'call_id': call_id}}
            if state['status'] == 'completed':
                try:
                    result = json.loads(read_observation(directory/'result.json'))
                    data = read_observation(directory/'preview.png', binary=True)
                except PermissionError as exc:
                    # The immutable execution receipt remains completed. Retrieval
                    # is currently unavailable; the caller can query again safely.
                    return unavailable(exc, state)
                if hashlib.sha256(data).hexdigest() != state['output_sha256']:
                    raise ValueError('Persisted preview output hash mismatch')
                response['result'] = result['compiled']
                if include_image:
                    response['result']['preview'] = 'data:image/png;base64,'+base64.b64encode(data).decode()
            if response.get('timing'):
                response['timing'] = {**response['timing'],
                    'response_assembly_ms': round((time.perf_counter()-query_clock)*1000, 3),
                    'transport_to_client_ms': None}
            return response

    def _supervise(self, call_id, owned_state):
        """Observation I/O must not tear down the sole deadline supervisor."""
        directory = self.directory(call_id)
        while True:
            result = None
            try:
                result = self.query(call_id, include_image=False)
                if result['status'] in TERMINAL:
                    return
            except (OSError, ValueError) as exc:
                try:
                    atomic(directory/'supervision-error.json', {
                        'status': 'outcome_unknown', 'error': type(exc).__name__+': '+str(exc),
                        'call_id': call_id, 'observed_at': time.time()})
                except OSError:
                    pass
            owned = _children.get(str(directory))
            if not owned:
                return
            if owned[0].poll() is not None:
                if result is not None and result['status'] != 'outcome_unknown':
                    continue  # One final locked reconciliation after observed exit.
                _children.pop(str(directory), None)
                if owned[1]:
                    owned[1].close()
                return
            if time.time() >= owned_state['deadline']:
                try:
                    stopped = self._stop(directory, owned_state)
                    if stopped:
                        _children.pop(str(directory), None)
                        if owned[1]:
                            owned[1].close()
                except OSError:
                    pass
                # Persisted state is never overwritten from a stale cached receipt.
                # A later authorized query reconciles the confirmed process/result.
                return
            time.sleep(.05)

    def wait(self, call_id):
        while True:
            result = self.query(call_id)
            if result['status'] in TERMINAL or result['status'] == 'outcome_unknown':
                return result
            time.sleep(.05)
