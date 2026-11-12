"""Resource checks and durable incident quarantine; never changes OS safety settings."""
import hashlib
import importlib
import json
import math
import os
import pathlib
import re
import subprocess
import tempfile
import time
import uuid

from settings import WORKSPACE, CREATE_NO_WINDOW
from production_errors import SharedRuntimeFailure

ROOT = WORKSPACE / 'work/runtime_health'
GPU_SCRIPTS = {'run_motion.py', 'motion_runtime.py', 'portrait_worker.py', 'flux_worker.py',
               'voice_worker.py', 'sync_character.py', 'native_lip_worker.py', 'director_worker.py',
               'story_worker.py', 'worker.py', 'super_resolution.py', 'sd-cli.exe', 'llama-server.exe', 'llama-server'}
LIMITATIONS = ['没有 CPU 核心温度、电压或电源监测；资源检查不能证明硬件稳定。',
               '软件保护不能修复硬件错误，也不能保证在整机失去响应前完成停止。']


def assert_engine_allowed(engine):
    from director_plan import policy
    blocked = policy().get('blocked_models', {}).get(engine)
    if blocked:
        raise SharedRuntimeFailure('此模型已暂停：' + str(blocked))


def save(path, value):
    """Same-directory atomic replacement with distinct temp names for concurrent writers."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/antivirus may briefly deny replacement. Retry only this
        # atomic operation, for less than one second; never discard the old file.
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(.01 * 2 ** attempt, .1))
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def mark_incident(reason, *, source='runtime', details=None):
    """Latch heavy work off until an explicit maintenance procedure resolves the incident.

    There is intentionally no automatic unlock and no normal generation-button bypass.
    Preserve each incident separately so a later failure cannot erase earlier evidence.
    """
    incident = dict(id=uuid.uuid4().hex, active=True, created_at=time.time(),
                    reason=str(reason)[:2000], source=str(source)[:100], details=details or {})
    save(ROOT / 'incidents' / (incident['id'] + '.json'), incident)
    save(ROOT / 'incident.json', incident)
    return incident


def _owner_identity():
    import psutil
    process = psutil.Process(os.getpid())
    return dict(owner_pid=process.pid, owner_create_time=process.create_time(), boot_time=psutil.boot_time())


def _stale_reason(state, current_boot):
    import psutil
    last = state.get('last') if isinstance(state.get('last'), dict) else {}
    previous_boot = state.get('boot_time', last.get('boot_time'))
    if previous_boot is not None and not isinstance(previous_boot, (int, float)):
        return '运行记录中的系统启动时间损坏，无法确认上次是否正常结束。'
    # Windows boot_time can shift slightly when the system clock is adjusted.
    # A small difference is not proof of a reboot; the PID AND creation time
    # checks below still reject a missing or replaced owner process.
    if previous_boot is not None and current_boot is not None and abs(previous_boot - current_boot) > 30:
        return '上次运行跨越了系统重启，未记录正常结束。'
    pid, created = state.get('owner_pid'), state.get('owner_create_time')
    if not isinstance(pid, int) or not isinstance(created, (float, int)):
        return '旧运行记录缺少进程身份，无法确认是否正常结束。'
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - created) > 0.01 or not process.is_running():
            return '上次运行进程已结束，但没有记录正常结束。'
    except psutil.NoSuchProcess:
        return '上次运行进程已结束，但没有记录正常结束。'
    except (psutil.AccessDenied, OSError):
        return '无法确认上次运行进程的身份，暂不启动新模型。'
    return ''


def _read_runtime_record(path):
    """Retry briefly when Windows readers meet an atomic record replacement."""
    for attempt in range(8):
        try:
            return json.loads(path.read_text('utf-8'))
        except FileNotFoundError:
            raise
        except (PermissionError, json.JSONDecodeError):
            if attempt == 7:raise
            time.sleep(min(.02 * (attempt+1), .12))


def runtime_status():
    """Read-only: no GPU probes, model calls, or state writes (safe for status polling)."""
    incident = None
    reason = ''
    incident_path = ROOT / 'incident.json'
    try:
        incident = _read_runtime_record(incident_path)
        if not isinstance(incident, dict) or not isinstance(incident.get('active'), bool):
            raise ValueError('invalid incident state')
        if incident['active']:
            reason = str(incident.get('reason') or '存在尚未处理的运行异常。')
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        reason = '运行保护记录无法读取；请先修复记录，不能直接启动模型。'
    stale = []
    try:
        import psutil
        current_boot = psutil.boot_time()
    except (ImportError, OSError):
        current_boot = None
    for path in ROOT.glob('*.json'):
        if not re.fullmatch(r'[0-9a-f]{24}', path.stem):
            continue
        try:
            state = _read_runtime_record(path)
            if not isinstance(state, dict):
                raise ValueError('invalid run state')
            if state.get('status') != 'running':
                continue
            stale_reason = _stale_reason(state, current_boot)
        except (OSError, ValueError, TypeError, ImportError):
            stale_reason = '历史运行记录损坏，无法确认上次是否正常结束。'
            state = {}
        if stale_reason:
            stale.append(dict(path=str(path), script=state.get('script', ''),
                              started_at=state.get('started_at'), reason=stale_reason))
    if not reason and stale:
        reason = '检测到未正常结束的模型任务，已暂停新的模型计算；已完成作品仍可查看和导出。'
    return dict(blocked=bool(reason), reason=reason, incident=incident, stale_runs=stale,
                limitations=list(LIMITATIONS))


def assert_runtime_allowed():
    status = runtime_status()
    if not status['blocked']:
        return
    if status['stale_runs'] and not (isinstance(status['incident'], dict) and status['incident'].get('active')):
        # Preserve original RUNNING records, and add a separate immutable incident.
        mark_incident(status['reason'], source='interrupted_run', details={'runs': status['stale_runs']})
    raise SharedRuntimeFailure(status['reason'])


def _nvml_snapshot():
    """Optional official nvidia-ml-py binding; never installs or changes dependencies."""
    nvml = importlib.import_module('pynvml')
    nvml.nvmlInit()
    try:
        handle = nvml.nvmlDeviceGetHandleByIndex(0)
        memory = nvml.nvmlDeviceGetMemoryInfo(handle)
        data = dict(gpu_total_mib=memory.total / 1024**2, gpu_used_mib=memory.used / 1024**2,
                    gpu_temperature=nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU),
                    gpu_utilization=nvml.nvmlDeviceGetUtilizationRates(handle).gpu, gpu_backend='nvml')
        try:
            data['gpu_power_watts'] = nvml.nvmlDeviceGetPowerUsage(handle) / 1000
        except Exception:
            # Power is useful context, but unsupported power sensors are not zero watts.
            data['gpu_power_watts'] = None
        return data
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:
            pass


def _validate_gpu(data):
    total, used, temp, util = [float(data[key]) for key in
                            ('gpu_total_mib', 'gpu_used_mib', 'gpu_temperature', 'gpu_utilization')]
    if not all(math.isfinite(value) for value in (total, used, temp, util)):
        raise ValueError('invalid GPU telemetry')
    if total <= 0 or used < 0 or used > total or not 0 <= temp <= 130 or not 0 <= util <= 100:
        raise ValueError('invalid GPU telemetry range')
    return data


def snapshot(gpu=True):
    try:
        import psutil
        ram = psutil.virtual_memory()
        data = dict(time=time.time(), available_ram_mib=round(ram.available / 1024**2),
                    boot_time=psutil.boot_time(), gpu_required=bool(gpu), telemetry_errors=[], telemetry_notes=[],
                    cpu_temperature=None, cpu_temperature_available=False)
    except Exception as exc:
        raise SharedRuntimeFailure('无法读取系统内存状态，已停止模型计算并保留完成内容。') from exc
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('physical', 'available', 'commit_limit',
                'commit_available', 'virtual', 'virtual_available', 'extended_available')]
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            data.update(commit_available_mib=round(memory.commit_available / 1024**2),
                        commit_limit_mib=round(memory.commit_limit / 1024**2))
        else:
            data['telemetry_errors'].append('系统可提交内存状态不可用')
    if gpu:
        try:
            data.update(_validate_gpu(_nvml_snapshot()))
            return data
        except ModuleNotFoundError:
            data['telemetry_notes'].append('未安装可选 NVML 绑定，使用 nvidia-smi 监测')
        except Exception:
            data['telemetry_notes'].append('NVML 监测不可用，尝试 nvidia-smi')
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=memory.total,memory.used,temperature.gpu,utilization.gpu',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                    timeout=5, creationflags=CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError('nvidia-smi returned nonzero')
            values = [float(x.strip()) for x in result.stdout.splitlines()[0].split(',')]
            if len(values) != 4:
                raise ValueError('invalid GPU telemetry')
            total, used, temp, util = values
            data.update(_validate_gpu(dict(gpu_total_mib=total, gpu_used_mib=used,
                        gpu_temperature=temp, gpu_utilization=util, gpu_backend='nvidia-smi', gpu_power_watts=None)))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            data['telemetry_errors'].append('显卡监测不可用或响应超时')
    return data


def check_limits(data, starting=False):
    if data.get('telemetry_errors'):
        raise SharedRuntimeFailure('无法可靠读取资源状态（' + '；'.join(data['telemetry_errors']) + '），已停止模型计算并保留完成内容。')
    available = data.get('available_ram_mib')
    if not isinstance(available, (int, float)) or not math.isfinite(available):
        raise SharedRuntimeFailure('系统内存状态未知，已暂停模型计算。')
    if available < (3072 if starting else 1024):
        raise SharedRuntimeFailure('可用内存不足，已停止本次计算并保留完成内容；关闭其他大程序后可继续。')
    commit = data.get('commit_available_mib')
    if commit is not None and commit < (3072 if starting else 1024):
        raise SharedRuntimeFailure('系统可提交内存余量不足，已停止计算并保留完成内容，避免继续挤占系统资源。')
    if data.get('gpu_required'):
        for field in ('gpu_total_mib', 'gpu_used_mib', 'gpu_temperature'):
            if not isinstance(data.get(field), (int, float)) or not math.isfinite(data[field]):
                raise SharedRuntimeFailure('显卡资源状态未知，已暂停模型计算。')
    temperature = data.get('gpu_temperature')
    if temperature is not None and temperature >= 85:
        raise SharedRuntimeFailure('显卡温度达到本软件的 85℃ 保护阈值，已停止计算并保留完成内容。')
    if starting and 'gpu_used_mib' in data and data.get('gpu_total_mib', 0) - data['gpu_used_mib'] < 1536:
        raise SharedRuntimeFailure('当前显存余量过小，已暂停启动模型；请先结束其他占用显卡的任务。')


class RunHealth:
    def __init__(self, command, log_path, *, gpu=True):
        names = [pathlib.Path(str(value)).name.lower() for value in command]
        self.script = next((name for name in names if name in GPU_SCRIPTS), '')
        self.enabled = bool(self.script)
        self.gpu = bool(gpu)
        identity = hashlib.sha256((str(log_path) + self.script).encode()).hexdigest()[:24]
        self.path = ROOT / (identity + '.json')
        self.events = ROOT / (identity + '.jsonl')
        self.state = {}
        self.last = 0
        if self.script == 'motion_runtime.py':
            assert_engine_allowed('wan22_5b')

    def start(self):
        if not self.enabled:
            return
        assert_runtime_allowed()
        try:
            previous = json.loads(self.path.read_text('utf-8'))
        except FileNotFoundError:
            previous = {}
        except (OSError, ValueError, TypeError) as exc:
            raise SharedRuntimeFailure('运行记录无法读取，暂不覆盖旧记录或启动模型。') from exc
        if previous.get('status') == 'running':
            raise SharedRuntimeFailure('此步骤已有正在运行的记录，请先停止原任务。')
        data = snapshot(gpu=self.gpu)
        check_limits(data, starting=True)
        self.state = dict(status='running', script=self.script, started_at=time.time(), samples=0,
                          run_id=uuid.uuid4().hex, **_owner_identity())
        self.record(data)

    def record(self, data):
        self.state.update(last=data, samples=self.state['samples'] + 1)
        save(self.path, self.state)
        with self.events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(data, run_id=self.state['run_id']), ensure_ascii=False) + '\n')
        self.last = time.monotonic()

    def tick(self):
        if self.enabled and time.monotonic() - self.last >= 10:
            assert_runtime_allowed()
            data = snapshot(gpu=self.gpu)
            self.record(data)
            check_limits(data)

    def finish(self, status, note=''):
        if self.enabled and self.state:
            self.state.update(status=status, finished_at=time.time(), note=str(note)[:500])
            save(self.path, self.state)
