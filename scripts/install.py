"""Windows setup for the local AIGC workspace.

The two virtual environments are isolated below app/work. Existing environments
are left untouched unless the user explicitly opts into updating them.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'
MODELS_SCRIPT = ROOT / 'scripts' / 'models.py'
PROFILES = ('basic', 'image', 'voice', 'motion', 'lip', 'all')
MANAGED_MARKER = '.aigc-managed-venv.json'
TORCH_INDEX = 'https://download.pytorch.org/whl/cu128'
FFMPEG_URL = ('https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/'
              'autobuild-2026-11-11-12-39/'
              'ffmpeg-n8.1.3-35-gf1acb0a266-win64-gpl-8.1.zip')
FFMPEG_SHA256 = '0fd32c3dd2a60a9d9d1206d217ec3e2dd74b47f5b6e67da648c73cb1db0f0bba'
TORCH_PACKAGES = ('torch==2.8.0', 'torchvision==0.23.0', 'torchaudio==2.8.0')
COMMON_PACKAGES = (
    'Pillow==12.3.0', 'numpy==2.2.6', 'opencv-python==4.11.0.86',
    'psutil==7.2.2', 'soundfile==0.14.0', 'scipy==1.18.1',
    'huggingface-hub==0.36.2', 'safetensors==0.8.0',
)
BASE_MODEL_PACKAGES = (
    'diffusers==0.30.2', 'transformers==4.57.3', 'accelerate==1.12.0',
    'einops==0.8.2', 'qwen-tts==0.1.1',
)
LIP_PACKAGES = ('ffmpeg-python==0.2.0',)
MOTION_PACKAGES = (
    'diffusers==0.35.2', 'transformers==4.57.3', 'accelerate==1.12.0',
    'einops==0.8.2', 'peft==0.17.1', 'triton-windows==3.4.0.post21',
    'easydict==1.13', 'ftfy==6.3.1', 'loguru==0.7.3', 'imageio==2.37.4',
    'imageio-ffmpeg==0.6.0',
    'pyzmq==27.1.0', 'prometheus-client==0.26.0', 'pydantic==2.13.5',
    'gguf==0.19.0',
)


def run(command):
    print('\n>', subprocess.list2cmdline([str(part) for part in command]), flush=True)
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def interpreter(environment):
    return environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def choose_profile():
    if not sys.stdin.isatty():
        raise ValueError('非交互模式请用 --profile 指定安装范围。')
    print('\n请选择安装范围。模型和运行组件可能占用大量硬盘空间。')
    print('1  基础界面（不下载模型）')
    print('2  绘图   3  配音   4  动作   5  口型   6  全部')
    choices = {'1': 'basic', '2': 'image', '3': 'voice',
               '4': 'motion', '5': 'lip', '6': 'all'}
    selected = input('请输入数字 1–6，回车取消: ').strip()
    if selected not in choices:
        raise ValueError('未选择安装范围。')
    return choices[selected]


def prepare_environment(path, allow_existing):
    executable = interpreter(path)
    marker = path / MANAGED_MARKER
    if path.exists():
        if not path.is_dir() or not executable.is_file():
            raise RuntimeError(f'环境目录不完整或被其他文件占用，已保留原内容：{path}')
        if not marker.is_file() and not allow_existing:
            raise RuntimeError(f'发现非安装器创建的环境，已保留原内容：{path}\n'
                               '如确认更新该环境中的 Python 软件包，可加 --allow-existing-env 重试。')
        return executable
    path.mkdir(parents=True, exist_ok=False)
    marker.write_text(json.dumps({'installer': 'aigc', 'python': '3.12',
                                  'state': 'creating'}, ensure_ascii=False), encoding='utf-8')
    venv.EnvBuilder(with_pip=True).create(path)
    if not executable.is_file():
        raise RuntimeError(f'Python 环境未创建完成，原文件已保留：{path}')
    marker.write_text(json.dumps({'installer': 'aigc', 'python': '3.12',
                                  'state': 'created'}, ensure_ascii=False), encoding='utf-8')
    return executable


def install_packages(python, packages, index=None):
    command = [python, '-m', 'pip', 'install', '--disable-pip-version-check']
    if index:
        command += ['--index-url', index]
    run(command + list(packages))


def verify_imports(python, names):
    code = ('import importlib,sys; '
            '[importlib.import_module(name) for name in sys.argv[1:]]; '
            'print("Python 模块导入检查通过")')
    run([python, '-X', 'utf8', '-c', code, *names])


def ensure_ffmpeg():
    target = APP / 'runtime/ffmpeg'
    if target.exists():
        if all((target / name).is_file() for name in ('ffmpeg.exe', 'ffprobe.exe')):
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                run([target / name, '-version'])
            print(f'保留已有 FFmpeg: {target}')
            return
        raise RuntimeError(f'已有 FFmpeg 目录不完整，未覆盖：{target}')
    if shutil.which('ffmpeg') and shutil.which('ffprobe'):
        run([shutil.which('ffmpeg'), '-version'])
        run([shutil.which('ffprobe'), '-version'])
        print('使用系统 PATH 中已有的 FFmpeg 和 ffprobe。')
        return
    downloads = APP / 'work/installer-downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='ffmpeg-', suffix='.zip', dir=downloads)
    archive = Path(name)
    digest = hashlib.sha256()
    print('下载 FFmpeg GPL 发行版，约需数百 MB 空间。许可证：https://ffmpeg.org/legal.html', flush=True)
    with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(FFMPEG_URL, timeout=90) as response:
        while block := response.read(1024 * 1024):
            output.write(block)
            digest.update(block)
    if digest.hexdigest() != FFMPEG_SHA256:
        raise RuntimeError(f'FFmpeg 哈希不一致，下载文件已保留：{archive}')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='ffmpeg.incomplete-', dir=target.parent))
    with zipfile.ZipFile(archive) as package:
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            matches = [entry for entry in package.infolist()
                       if entry.filename.endswith('/bin/' + name)]
            if len(matches) != 1:
                raise RuntimeError(f'FFmpeg 压缩包缺少唯一的 {name}；已保留：{archive}')
            with package.open(matches[0]) as source, (staging / name).open('xb') as output:
                shutil.copyfileobj(source, output)
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        run([staging / name, '-version'])
    if target.exists():
        raise RuntimeError(f'安装期间 FFmpeg 目标已出现，未覆盖：{target}')
    staging.rename(target)


def configure_default_image_engine():
    config = APP / 'image_engine.json'
    original = b'{"engine": "legacy"}'
    if config.is_file() and config.read_bytes().strip() == original:
        old = config.read_bytes()
        backup = APP / 'work/installer-downloads/image_engine.before-install.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            if backup.read_bytes() != old:
                raise RuntimeError(f'已有配置备份内容不同，保留现有文件：{backup}')
        else:
            with backup.open('xb') as output:
                output.write(old)
        if config.read_bytes() != old:
            raise RuntimeError('绘图配置在安装期间发生变化，已保留新内容。')
        fd, temp = tempfile.mkstemp(prefix='image_engine.', suffix='.tmp', dir=config.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write('{"engine": "flux"}\n')
        if config.read_bytes() != old:
            raise RuntimeError(f'绘图配置在安装期间发生变化，临时文件已保留：{temp}')
        os.replace(temp, config)
        print('已将未修改的默认绘图配置设为 FLUX 4B，原配置已备份。')
    else:
        print('保留已有绘图配置；请在界面确认是否选择 FLUX 4B。')


def print_status():
    print(f'项目目录: {ROOT}')
    print(f'Python: {sys.version.split()[0]} ({platform.architecture()[0]})')
    print(f'基础环境: {interpreter(APP / "work/local_test/venv")}')
    print(f'动作环境: {interpreter(APP / "work/motion_test/venv")}')
    for tool in ('nvidia-smi', 'ffmpeg', 'ffprobe'):
        found = shutil.which(tool)
        print(f'{tool}: {found or "未在 PATH 中找到"}')
    portable = APP / 'runtime/ffmpeg'
    if (portable / 'ffmpeg.exe').is_file() and (portable / 'ffprobe.exe').is_file():
        print(f'已找到本地 FFmpeg: {portable}')
    print('模型任务需要兼容的 NVIDIA 显卡、驱动、足够显存和内存。')


def main():
    parser = argparse.ArgumentParser(description='安装 AIGC 本地短剧制作工具')
    parser.add_argument('--profile', choices=PROFILES, help='选择安装范围')
    parser.add_argument('--check-only', action='store_true', help='只检查，不创建环境或下载')
    parser.add_argument('--skip-dependencies', action='store_true', help='跳过 Python 包安装')
    parser.add_argument('--skip-models', action='store_true', help='跳过模型下载')
    parser.add_argument('--allow-existing-env', action='store_true',
                        help='允许修改非本安装器创建的既有虚拟环境')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise RuntimeError('需要 64 位 Python 3.12。')
    if os.name != 'nt':
        raise RuntimeError('目前安装脚本仅支持 Windows。')
    if not (APP / 'server.py').is_file():
        raise RuntimeError('找不到 app/server.py，请从完整的项目目录运行安装器。')
    print_status()
    if args.check_only:
        return
    profile = args.profile or 'all'
    print(f'安装范围: {profile}')
    if profile != 'basic':
        if not MODELS_SCRIPT.is_file():
            raise RuntimeError('缺少 scripts/models.py，未开始安装。')
        # Do not download large dependencies before finding known missing sources
        # or conflicts in the model plan. This check does not download models.
        run([sys.executable, '-X', 'utf8', MODELS_SCRIPT, 'install',
             '--profile', profile, '--check-only', '--yes'])
        ensure_ffmpeg()
    base = prepare_environment(APP / 'work/local_test/venv', args.allow_existing_env)
    motion = prepare_environment(APP / 'work/motion_test/venv', args.allow_existing_env)
    if profile != 'basic' and not args.skip_dependencies:
        # The CUDA wheel is installed separately, matching the original local runtime.
        if profile in ('voice', 'lip', 'motion', 'all'):
            install_packages(base, TORCH_PACKAGES, TORCH_INDEX)
        install_packages(base, COMMON_PACKAGES)
        if profile in ('voice', 'lip', 'all'):
            install_packages(base, BASE_MODEL_PACKAGES)
        if profile in ('lip', 'all'):
            install_packages(base, LIP_PACKAGES)
        if profile in ('motion', 'all'):
            install_packages(motion, TORCH_PACKAGES, TORCH_INDEX)
            install_packages(motion, COMMON_PACKAGES + MOTION_PACKAGES)
    if profile != 'basic':
        checks = ['PIL', 'numpy', 'cv2', 'psutil', 'soundfile', 'scipy']
        if profile in ('voice', 'lip', 'motion', 'all'):
            checks += ['torch']
        if profile in ('voice', 'lip', 'all'):
            checks += ['diffusers', 'transformers', 'qwen_tts']
        if profile in ('lip', 'all'):
            checks += ['ffmpeg']
        verify_imports(base, checks)
        if profile in ('motion', 'all'):
            verify_imports(motion, ['torch', 'diffusers', 'transformers', 'triton',
                                    'imageio_ffmpeg', 'zmq', 'prometheus_client', 'pydantic'])
    if args.skip_models:
        if profile != 'basic':
            raise RuntimeError('已跳过模型下载，所选完整功能尚未安装。')
        print('\n已准备基础界面，不包含生成模型。')
        return
    if profile == 'basic':
        print('\n基础界面环境已准备。双击 start.bat 可启动，生成模型需要另行安装。')
        return
    if not MODELS_SCRIPT.is_file():
        raise RuntimeError('缺少 scripts/models.py，未开始模型下载。')
    run([sys.executable, '-X', 'utf8', MODELS_SCRIPT, 'install', '--profile', profile])
    run([sys.executable, '-X', 'utf8', MODELS_SCRIPT, 'verify', '--profile', profile])
    if profile in ('image', 'all'):
        configure_default_image_engine()
    print('\n所选组件的安装和文件检查已完成。完整生成链路仍需实际验证。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'安装未完成：{error}', file=sys.stderr)
        sys.exit(1)
