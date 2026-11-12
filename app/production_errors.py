"""Separate a recoverable shot error from cancellation or a broken shared runtime."""
import errno

STAGES={'reference':'准备画面','preflight':'检查说话人','audio':'制作配音',
        'translation':'理解动作','motion':'生成动作','quality':'检查画面质量','enhance':'修复画面细节','lips':'制作口型','export':'导出镜头','assembly':'合成成片'}


class IncompleteProduction(RuntimeError):
    pass


class SharedRuntimeFailure(RuntimeError):
    pass


def fatal_error(exc):
    if isinstance(exc,(InterruptedError,MemoryError,ImportError,PermissionError,SharedRuntimeFailure)):
        return True
    if isinstance(exc,OSError) and (exc.errno in (errno.ENOSPC,errno.ENOMEM,errno.EACCES) or getattr(exc,'winerror',None) in (5,8,112,1455)):
        return True
    text=str(exc).lower()
    return any(term in text for term in ('cuda out of memory','cuda error','outofmemoryerror',
        'device-side assert','illegal memory access','device lost','device removed',
        'device has been lost','driver shutting down','failed to initialize nvml','nvidia-smi',
        'cuda initialization error','cublas_status','cudnn_status','no space left','disk full',
        'no module named','找不到指定的程序','磁盘空间不足','显存不足','缺少本地','模型或运行环境不完整',
        '模型文件不完整','模型未能启动','模型启动超时'))


def failure(stage, exc):
    return {'stage':stage,'label':STAGES.get(stage,stage),'message':str(exc)[:800],
            'fatal':fatal_error(exc)}
