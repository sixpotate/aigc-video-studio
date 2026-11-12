"""Own child processes as a Windows job; bound cancellation and failed-start cleanup."""
import ctypes
import os
import pathlib
import subprocess
import time
from ctypes import wintypes

from settings import CREATE_NO_WINDOW, WORKSPACE


class ProcessGroup:
    def __init__(self):
        self.handle = None
        if os.name == 'nt':
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
            self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.handle = self.kernel.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            class BasicLimits(ctypes.Structure):
                _fields_ = [('per_process_time', ctypes.c_longlong), ('per_job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t), ('max_working_set', ctypes.c_size_t),
                    ('active_process_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority_class', wintypes.DWORD), ('scheduling_class', wintypes.DWORD)]
            class ExtendedLimits(ctypes.Structure):
                _fields_ = [('basic', BasicLimits), ('io_counters', ctypes.c_ulonglong * 6),
                    ('process_memory_limit', ctypes.c_size_t), ('job_memory_limit', ctypes.c_size_t),
                    ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
            self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                error = ctypes.get_last_error()
                self.kernel.CloseHandle(self.handle)
                self.handle = None
                raise ctypes.WinError(error)

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            error = ctypes.get_last_error()
            try:
                process.kill()
                process.wait(timeout=5)
            finally:
                raise ctypes.WinError(error)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            try:
                self.kernel.TerminateJobObject(handle, 1)
            finally:
                self.kernel.CloseHandle(handle)


class ManagedProcess:
    """Create ownership before Popen, then always stop/reap the child on exit.

    Windows assigns the spawned process immediately; Python Popen does not expose an
    atomic job-assignment launch, so this is not a guarantee against every launch race.
    """
    def __init__(self):
        self.group = None
        self.process = None
        self._closed = False

    def start(self, command, **popen_kwargs):
        if self.group is not None or self.process is not None:
            raise RuntimeError('此进程管理器已启动过，请为新步骤创建新的管理器。')
        self.group = ProcessGroup()
        try:
            self.process = subprocess.Popen([str(value) for value in command], **popen_kwargs)
            self.group.assign(self.process)
            return self.process
        except BaseException:
            self.close()
            raise

    def poll(self):
        return self.process.poll() if self.process is not None else None

    def close(self):
        if self._closed:
            return
        try:
            self._close_owned()
            self._closed = True
        except Exception as exc:
            from production_errors import SharedRuntimeFailure
            from runtime_health import mark_incident
            mark_incident('无法确认模型子进程已完全退出，已暂停新的模型计算。', source='process_cleanup',
                          details={'pid': self.process.pid if self.process is not None else None,
                                   'error': str(exc)[:500]})
            raise SharedRuntimeFailure('子进程清理失败；请先确认后台任务已退出，再恢复模型计算。') from exc

    def _close_owned(self):
        try:
            if self.group is not None:
                self.group.close()
        finally:
            self.group = None
            if self.process is not None:
                try:
                    if self.process.poll() is None:
                        self.process.kill()
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def run_child(command, cancelled, log_path, on_tick=None, timeout=None, *, on_tick_interval=15, on_success=None, thread_limit=None):
    """Run a step, reap it, then validate its result before recording completion.

    Optional timeout is seconds; no automatic restart on shared failures.
    on_success runs after owned-process cleanup and its return value is forwarded.
    Optional positive integer thread_limit affects only the child environment.
    """
    from runtime_health import RunHealth, mark_incident
    from production_errors import SharedRuntimeFailure, fatal_error
    if cancelled():
        raise InterruptedError('已停止，已完成的配音和镜头已保留。')
    if timeout is not None and timeout <= 0:
        raise ValueError('步骤超时必须大于 0 秒。')
    if on_tick_interval <= 0:
        raise ValueError('进度更新间隔必须大于 0 秒。')
    if thread_limit is not None and (type(thread_limit) is not int or thread_limit < 1):
        raise ValueError('子进程线程数必须为正整数。')
    log_path = pathlib.Path(log_path)
    health = RunHealth(command, log_path)
    managed = ManagedProcess()
    try:
        health.start()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as log:
            log.flush()
            log_start = os.fstat(log.fileno()).st_size
            child_env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
            if thread_limit is not None:
                child_env.update({key: str(thread_limit) for key in
                                  ('OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')})
            process = managed.start(command, cwd=WORKSPACE, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_NO_WINDOW,
                                    env=child_env)
            started = last_tick = time.monotonic()
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError('已停止，已完成的配音和镜头已保留。')
                if timeout is not None and time.monotonic() - started >= timeout:
                    raise SharedRuntimeFailure('此生成步骤超过设定时限，已停止并保留完成内容；不会自动重试。')
                health.tick()
                if on_tick and time.monotonic() - last_tick >= on_tick_interval:
                    on_tick()
                    last_tick = time.monotonic()
                time.sleep(.3)
            if cancelled():
                raise InterruptedError('已停止，已完成的配音和镜头已保留。')
            if process.returncode:
                log.flush()
                # Resume logs are append-only: classify only bytes emitted by this
                # child, never a previous run's CUDA error. Bound the read as well.
                with log_path.open('rb') as current_log:
                    current_log.seek(0, os.SEEK_END)
                    end = current_log.tell()
                    current_log.seek(max(log_start, end - 9600))
                    tail = current_log.read(9600).decode('utf-8', errors='replace')[-2400:]
                lines = [line.strip() for line in tail.splitlines() if line.strip()]
                detail = next((line for line in reversed(lines) if 'Error:' in line or 'Exception:' in line),
                              lines[-1] if lines else '没有返回运行日志')
                if 'out of memory' in tail.lower() or 'OutOfMemoryError' in tail:
                    detail = '显存或内存不足；已保留完成内容，本次没有降低画质或跳过该镜头。'
                error = RuntimeError('生成步骤失败：' + detail[:500])
                abnormal = process.returncode < 0 or process.returncode >= 0x80000000
                shared = ('out of memory', 'outofmemoryerror', 'cuda error', 'device lost',
                          'device-side assert', 'illegal memory access', 'driver shutting down')
                device_fault = any(term in tail.lower() for term in ('device lost', 'device-side assert',
                    'illegal memory access', 'driver shutting down', 'gpu has fallen off the bus', 'cuda driver error'))
                if abnormal or device_fault:
                    mark_incident('模型进程异常退出或报告设备故障，已暂停新的模型计算；请检查运行日志后再恢复。',
                                  source='child_process_fault', details={'exit_code': process.returncode,
                                  'program': pathlib.Path(str(command[0])).name})
                if abnormal or device_fault or any(term in tail.lower() for term in shared) or fatal_error(error):
                    raise SharedRuntimeFailure(str(error))
                raise error
        managed.close()
        result = on_success() if on_success is not None else None
        health.finish('completed')
        return result
    except BaseException as exc:
        # Ownership also exists during startup failure; clean up before claiming completion.
        try:
            managed.close()
        finally:
            health.finish('cancelled' if isinstance(exc, InterruptedError) else 'failed', str(exc))
        raise
