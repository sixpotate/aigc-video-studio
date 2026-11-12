# AIGC 本地短剧制作软件

一个面向 Windows 的本地短剧制作项目，提供剧本、角色、分镜、配音、动作生成、口型同步和视频导出等工作流程。界面由本机 Python 服务提供，浏览器访问 `http://127.0.0.1:8765/`。

本仓库整理自实际使用的 AIGC 程序。代码、界面和导演动作调用脚本单独提供，模型权重、运行环境、第三方项目以及用户作品需要在本地另行准备。当前版本适合具备 Python 和本地 AI 环境配置经验的使用者研究与继续开发，尚未完成从干净电脑安装到成片的全流程验证。

## 功能概览

- 剧本与角色：创建角色设定，拆分剧本，编辑镜头、人物和场景。
- 导演模式：管理分镜、参考画面、对白、动作任务及输出。
- 本地生成：通过外部绘图程序、本地模型和 GPU 生成参考画面、配音及动态画面。
- 后期处理：结合 FFmpeg、口型同步、字幕、音效和可选的画面增强处理。
- 作业保护：包含资源检查、缓存校验和任务状态管理代码。不同电脑的显存、内存和驱动情况不同，需要自行验证。

生成模型主要在本机运行。项目的可选资料研究功能会访问网络服务，下载或配置依赖时也可能需要联网。

## 目录

```text
app/                  本地服务、制作流程和网页界面
app/static/           JavaScript 和 CSS
app/work/motion_test/ 导演模式使用的动作调用脚本
third_party_licenses/ 随代码提供的第三方许可
```

程序运行时还会在仓库根目录附近创建“我的作品”“我的角色”“创作素材”和“备份与记录”，在 `app/work/`、`app/outputs/` 等目录保存本地数据。`.gitignore` 对这些目录提供默认排除规则，分享前仍应检查将要提交的文件和 Git 历史。

## 环境与启动

原始开发环境使用 Windows 和 Python 3.12.10。不同功能还需要 Pillow、NumPy、PyTorch、OpenCV、soundfile、SciPy、diffusers、transformers、psutil、Qwen TTS、FFmpeg 等依赖。视频和人物生成还需要兼容的 NVIDIA GPU、驱动及相应的本地模型。项目尚没有经过完整验证的锁定依赖清单，请按所需功能单独安装和测试。

服务入口是 `app/server.py`。在 Windows 已安装 Python 3.12 的情况下，可以先在仓库内创建本地环境并启动界面：

```powershell
py -3.12 -m venv app\work\local_test\venv
.\app\work\local_test\venv\Scripts\python.exe app\server.py --no-browser
```

然后在浏览器打开 `http://127.0.0.1:8765/`。启动命令中的 `--no-browser` 仅关闭自动打开浏览器，可通过 `AI_DRAMA_PORT` 设置端口。隔离副本使用 Python 3.12 标准库验证了服务启动、首页与空项目配置接口，生成流程仍需要单独安装依赖与模型。

程序中的部分子进程使用 `app/runtime/python/python.exe` 或 `app/work/local_test/venv/Scripts/python.exe` 等约定路径，动作生成使用 `app/work/motion_test/venv/`。这些路径需按照源码和你选择的依赖版本配置。当前尚未验证一组可复现的完整依赖版本，请按具体功能检查和安装。

## 模型与外部组件

- 绘图流程调用单独准备的绘图程序与模型权重，配置可在 `app/image_engine.py` 中查看。
- Wan 动作流程使用 `app/work/motion_test/run_motion.py`、LightX2V、模型权重和独立 Python 环境。本机曾使用包含本地修改的 LightX2V，直接安装上游版本的兼容性尚未验证。
- 配音流程使用 Qwen TTS 和相应权重。口型同步依赖 MuseTalk 及所需权重。
- 可选画面增强使用 Real-ESRGAN 模型。`app/super_resolution.py` 的部分结构改编自 Real-ESRGAN，保留其 BSD 3-Clause 版权和许可文本。
- 模型、组件和数据集分别遵循各自许可证。具体权重的使用范围可能不同，例如 FLUX.2-klein-9B 官方权重采用非商业许可。安装和使用前请检查你实际下载版本的许可证。

外部组件参考：[LightX2V](https://github.com/ModelTC/LightX2V)、[MuseTalk](https://github.com/TMElyralab/MuseTalk)、[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)、[FLUX.2-klein-9B 模型卡](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)。

## 已知限制

这是从个人使用环境整理出的源码版本，尚无一键安装包。旧动作模板原本依赖特定素材和固定人物坐标，相关素材没有随仓库发布，该流程需要自行替换素材和适配。图片、视频、语音和口型输出的质量需要结合具体模型人工检查。模型权重、GPU 资源或运行组件缺失时，对应功能无法工作。

发布前已分离本地项目和素材目录。提交者仍需检查演示数据、日志、模型路径、令牌和新增文件，防止把个人创作内容带入公开仓库。

## 许可证

项目自有代码采用 [MIT 许可证](LICENSE)。第三方来源代码及独立安装的模型、工具使用各自的许可。Real-ESRGAN 派生部分的许可证位于 `third_party_licenses/`。
