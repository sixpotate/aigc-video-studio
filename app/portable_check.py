"""Human-readable check for the packaged Windows runtime and required assets."""
import importlib
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

from settings import APP_DIR as APP, WORKSPACE as ROOT, INSTALL_DIR
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
cache = ROOT / 'work/local_test/hf-cache'
cache.mkdir(parents=True, exist_ok=True)
os.environ['HF_HOME'] = str(cache)
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['PYTHONNOUSERSITE'] = '1'
print('本地AI短剧制作器 · 电脑环境检查')
print('软件位置：', INSTALL_DIR)
print('Python：', sys.executable)

missing = []
for relative in (
    'work/local_test/models/DreamShaper-8/dreamshaper_8.safetensors',
    'work/local_test/models/SD15-config/model_index.json',
    'work/local_test/models/opus-mt-zh-en/pytorch_model.bin',
    'work/local_test/models/Qwen3-TTS-1.7B-CustomVoice/model.safetensors',
    'work/local_test/models/Linly-MuseTalk/MuseTalk/musetalk/pytorch_model.bin',
    'outputs/motion_test/ep01_motion.mp4',
):
    if not (ROOT / relative).is_file():
        missing.append(relative)
print('必要文件：', '完整' if not missing else '缺少 ' + '、'.join(missing))

try:
    import torch
    print('NVIDIA显卡：', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '未检测到可用CUDA')
    if not torch.cuda.is_available():
        missing.append('可用的NVIDIA CUDA显卡')
except Exception as exc:
    print('绘图运行库：加载失败 -', exc)
    missing.append('绘图运行库')

for module in ('diffusers', 'transformers', 'cv2', 'soundfile'):
    try:
        importlib.import_module(module)
        print(module + '：正常')
    except Exception as exc:
        print(module + '：加载失败 -', exc)
        missing.append(module)

if importlib.util.find_spec('qwen_tts'):
    print('qwen_tts：正常')
else:
    print('qwen_tts：未找到')
    missing.append('qwen_tts')

bundled_ffmpeg = ROOT / 'runtime/ffmpeg/ffmpeg.exe'
ffmpeg = str(bundled_ffmpeg) if bundled_ffmpeg.is_file() else shutil.which('ffmpeg')
print('视频工具：', ffmpeg or '未找到')
if not ffmpeg:
    missing.append('ffmpeg')

print()
if missing:
    print('检查未通过。请确认便携包已完整解压，并更新NVIDIA显卡驱动。')
    raise SystemExit(1)
print('检查通过。可以双击“启动AIGC.vbs”。')
