"""Local paths and the capabilities exposed to the interface."""
import os
import pathlib

APP_DIR = pathlib.Path(__file__).resolve().parent
# Program files, user content, and runtime resources have separate roots.
INSTALL_DIR = APP_DIR.parent
WORKSPACE = APP_DIR
PROJECTS_DIR = INSTALL_DIR / '我的作品'
MATERIAL_DIR = INSTALL_DIR / '创作素材'
SCENE_ASSET_DIR = MATERIAL_DIR / '场景与音乐'
SOUND_LIBRARY_DIR = MATERIAL_DIR / '声音素材'
LOG_DIR = INSTALL_DIR / '备份与记录/运行日志'
PORTABLE_PYTHON = WORKSPACE / 'runtime/python/python.exe'
PYTHON = PORTABLE_PYTHON if PORTABLE_PYTHON.is_file() else WORKSPACE / 'work/local_test/venv/Scripts/python.exe'
PORTABLE_FFMPEG = WORKSPACE / 'runtime/ffmpeg'
if PORTABLE_FFMPEG.is_dir():
    os.environ['PATH'] = str(PORTABLE_FFMPEG) + os.pathsep + os.environ.get('PATH', '')
os.environ.setdefault('PYTHONNOUSERSITE', '1')
LIBRARY = WORKSPACE / 'work/series/scripts.json'
STORAGE = PROJECTS_DIR / '分镜项目'
VIDEO_DIR = PROJECTS_DIR / '生成的视频'
EXPORT_DIR = PROJECTS_DIR / '导出的图片'
CHARACTER_DIR = INSTALL_DIR / '我的角色'
CHARACTER_MODEL = WORKSPACE / 'work/local_test/models/DreamShaper-8'
CHARACTER_CONFIG = WORKSPACE / 'work/local_test/models/SD15-config'
POSE_MODEL = WORKSPACE / 'work/local_test/models/ControlNet-OpenPose'
TRANSLATION_MODEL = WORKSPACE / 'work/local_test/models/opus-mt-zh-en'
TRANSLATION_LLM = WORKSPACE / 'work/local_test/models/Qwen3-4B-GGUF/Qwen3-4B-Q4_K_M.gguf'
TRANSLATION_RUNTIME = WORKSPACE / 'runtime/portrait-translator/llama-server.exe'
WRITING_LLM = WORKSPACE / 'work/local_test/models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf'
WRITING_MODEL_NAME = 'Qwen3.5-9B · 本地编剧'
CURRENT = WORKSPACE / 'work/app_ui/current.json'
CREATE_NO_WINDOW = 0x08000000
ROLES = [
    {'id': 'boss', 'name': '角色甲', 'description': '待设置的角色'},
    {'id': 'robot', 'name': '角色乙', 'description': '待设置的角色'},
    {'id': 'colleague', 'name': '角色丙', 'description': '待设置的角色'},
]
SIZES = {
    '540': {'9:16': (540, 960), '16:9': (960, 540), '1:1': (540, 540)},
    '720': {'9:16': (720, 1280), '16:9': (1280, 720), '1:1': (720, 720)},
    '1080': {'9:16': (1080, 1920), '16:9': (1920, 1080), '1:1': (1080, 1080)},
    '1440': {'9:16': (1440, 2560), '16:9': (2560, 1440), '1:1': (1440, 1440)},
}
