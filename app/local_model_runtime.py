"""Owned local llama servers with resource budgets, not a stability certification.

Flags verified against bundled llama-server 161755f29; no weights loaded.
"""
import concurrent.futures
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from process_control import ManagedProcess
from production_errors import SharedRuntimeFailure
from runtime_health import RunHealth, assert_runtime_allowed, mark_incident
from settings import CREATE_NO_WINDOW, TRANSLATION_RUNTIME

GPU_STARTUP_TIMEOUT_SECONDS = 300
CPU_STARTUP_TIMEOUT_SECONDS = 300


def resource_arguments(context=12288, cpu=False):
    return ['--ctx-size', str(context), '--parallel', '1',
            '--threads', '2' if cpu else '4', '--threads-batch', '2' if cpu else '4',
            '--batch-size', '512', '--ubatch-size', '128',
            '--gpu-layers', '0' if cpu else 'auto', '--fit', 'on',
            '--fit-target', '2048', '--no-context-shift']


def record_device_failure(detail, returncode=None):
    abnormal = returncode is not None and (returncode < 0 or returncode >= 0x80000000)
    device_fault = any(word in detail.lower() for word in
                       ('device lost', 'device removed', 'device has been lost',
                        'driver shutting down', 'illegal memory access', 'device-side assert'))
    if abnormal or device_fault:
        mark_incident('本地模型异常退出或报告设备故障，已暂停新的模型计算。',
                      source='local_model', details={'returncode': returncode, 'error': detail[:500]})


class LocalModelSession:
    def __init__(self, log_path, check_cancelled, request_timeout=600):
        self.log_path, self.check_cancelled = log_path, check_cancelled
        self.request_timeout = request_timeout
        self.manager = self.health = self.process = self.executor = self.log = None
        self.request_deadline = None
        self.closed = False
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def check(self):
        self.check_cancelled()
        if self.health:
            self.health.tick()
        if self.process and self.process.poll() is not None:
            record_device_failure('', self.process.returncode)
            raise SharedRuntimeFailure('本地模型进程意外退出，已停止后续任务，请查看本次模型日志。')
        if self.request_deadline and time.monotonic() >= self.request_deadline:
            raise SharedRuntimeFailure('本地模型响应超时，已停止本任务；已完成的内容仍保留。')

    def call(self, path, data=None, timeout=None):
        timeout = self.request_timeout if timeout is None else timeout
        completion = path == '/v1/chat/completions'
        if completion:
            self.request_deadline = time.monotonic() + timeout
        request = urllib.request.Request(self.base + path,
            None if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Keep full-context rejection available to the caller; never trim text.
            if not completion or exc.code in (400, 413):
                raise
            detail = exc.read(1600).decode('utf-8', 'replace')[:500]
            record_device_failure(detail)
            raise SharedRuntimeFailure(f'本地模型服务异常（HTTP {exc.code}），已停止后续任务：{detail}') from exc
        except (OSError, TimeoutError) as exc:
            if not completion:
                raise
            raise SharedRuntimeFailure('本地模型连接中断或响应超时，已停止后续任务，完成内容仍保留。') from exc
        finally:
            if completion:
                self.request_deadline = None

    def start(self, model_path, extra_args, context=12288, cpu=False):
        assert_runtime_allowed()
        self.check_cancelled()
        if not model_path.is_file() or not TRANSLATION_RUNTIME.is_file():
            raise ValueError('缺少本地模型或运行程序，请检查安装目录。')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.base, self.token = f'http://127.0.0.1:{port}', secrets.token_hex(24)
        command = [str(TRANSLATION_RUNTIME), '-m', str(model_path),
                   '--host', '127.0.0.1', '--port', str(port), '--api-key', self.token,
                   *resource_arguments(context, cpu), '--no-webui', *extra_args]
        try:
            self.health = RunHealth(command, self.log_path, gpu=not cpu)
            self.health.start()
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # A resume must not overwrite evidence of an earlier failed run.
            self.log = self.log_path.open('a', encoding='utf-8')
            self.log.write('\n本地模型启动 ' + time.strftime('%Y-%m-%d %H:%M:%S') +
                           f' model={model_path.name} context={context} cpu={cpu}\n')
            self.log.flush()
            self.manager = ManagedProcess()
            self.process = self.manager.start(command, cwd=TRANSLATION_RUNTIME.parent,
                env={**os.environ, 'HF_HUB_OFFLINE': '1'}, stdout=self.log,
                stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            # A vision/text model can start immediately after a large image model.
            # On memory-constrained Windows hosts, releasing and paging those model
            # weights can make an otherwise healthy llama-server need more than the
            # former 180-second GPU limit. Keep the wait bounded, but give cleanup
            # the same five-minute ceiling already used by the CPU route.
            startup_timeout = CPU_STARTUP_TIMEOUT_SECONDS if cpu else GPU_STARTUP_TIMEOUT_SECONDS
            deadline = time.monotonic() + startup_timeout
            while True:
                self.check()
                try:
                    self.call('/health', timeout=1)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        raise SharedRuntimeFailure('本地模型启动超时，已停止本任务，请查看模型日志。')
                    time.sleep(.2)
        except BaseException as exc:
            self.close(exc)
            raise

    def complete(self, payload):
        self.check()
        future = self.executor.submit(self.call, '/v1/chat/completions', payload)
        deadline = time.monotonic() + self.request_timeout
        while not future.done():
            self.check()
            if time.monotonic() >= deadline:
                raise SharedRuntimeFailure('本地模型响应超时，已停止本任务；已完成的内容仍保留。')
            time.sleep(.15)
        return future.result()

    def close(self, error=None):
        if self.closed:
            return
        self.closed = True
        cleanup_error = None
        try:
            if self.manager:
                self.manager.close()
        except BaseException as exc:
            cleanup_error = exc
        finally:
            if self.executor:
                # Server is closed first; Stop need not wait for the HTTP timeout.
                self.executor.shutdown(wait=False, cancel_futures=True)
            if self.log:
                self.log.close()
            if self.health:
                failure = error or cleanup_error
                status = 'cancelled' if isinstance(failure, InterruptedError) else 'failed' if failure else 'completed'
                self.health.finish(status, str(failure or ''))
        if cleanup_error and error is None:
            raise cleanup_error

