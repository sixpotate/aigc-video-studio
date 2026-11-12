# AIGC 本地短剧制作软件

面向 Windows 的本地短剧制作项目，包含剧本、角色、分镜、绘图、配音、动作生成、口型同步与视频导出流程。界面在本机浏览器打开；模型和作品保存在使用者自己的电脑上。资料研究等部分可选功能及安装下载会访问网络。

本仓库提供程序和安装脚本，**不包含模型权重、运行环境、创作作品、用户角色、素材和项目备份**。模型和第三方组件从清单中的上游公开来源下载，受各自许可约束。

## 电脑准备

- Windows 10/11 64 位、兼容 CUDA 的 NVIDIA 显卡及可用驱动；能打开界面不代表能够运行全部生成模型。
- 可访问 GitHub、PyPI、Hugging Face 和 PyTorch 下载站的网络。完整模型体积较大，建议预留至少 100 GB 磁盘空间，安装过程中还需要临时空间；实际占用随安装选项变化。
- 安装过程及模型运行需要较多可用内存和显存。不同配置下能否生成尚需实测，内存或显存不足时不要通过关闭保护强行运行。
- 将 ZIP 解压到自己有写入权限、空间充足的本地 NTFS 磁盘目录，例如 `D:\AIGC-Video-Studio`。下载器使用硬链接完成大文件的安全落盘；不要在压缩包内直接运行，也不要与已有作品目录混用。

## 下载安装

1. 在 GitHub 页面选择 **Code → Download ZIP**，下载并解压整个项目。当前完整方案预计下载约 45.9 GB，Python 依赖与解压空间另计。
2. 双击解压后的 `install.bat`。安装程序优先使用已有的 64 位 Python 3.12；没有时会下载经校验的官方 Python 到项目目录，不修改全局 Python。
3. 按窗口提示确认下载。首次安装要下载 Python 包、外部工具和模型，可能耗时较长。窗口提示失败时，安装尚未完成，请保留提示信息；重新运行会检查已有文件，不会直接覆盖不匹配的文件。
4. 安装成功后双击 `start.bat`，浏览器打开本机界面。如果没有自动打开，访问 `http://127.0.0.1:8765/`。
5. 新建角色和项目，在界面中配置角色、分镜和配音，再逐项测试绘图、动作、口型及导出。已有作品不会随程序下载。

**验证范围：** 当前已验证公开源码可在隔离目录启动界面，并对安装组件、文件校验和部分安装过程做了测试；尚未在全新电脑上完成包含真实模型推理和视频导出的端到端验收。安装或文件校验成功不等于任意电脑都能成功生成。

## 模型与下载选项

默认安装入口面向完整流程。进阶用户可以在项目目录的 PowerShell 中指定安装范围：

```powershell
.\install.bat --profile basic   # 仅准备基础界面，不含模型
.\install.bat --profile image   # 绘图、翻译和编剧
.\install.bat --profile voice   # 本地配音
.\install.bat --profile motion  # 动作生成
.\install.bat --profile lip     # 口型同步
.\install.bat --profile all     # 完整安装
```

各范围是按需安装，不代表单独一个范围就具备制作完整视频所需的全部功能。若安装程序提示某个范围暂不可用，应以提示为准，不要把未下载的模型当成已安装。

- 绘图：FLUX.2 klein 4B、配套图像解码器和 Qwen3 4B 文字编码器，由 `stable-diffusion.cpp` 运行。安装后可在界面的绘图设置中检查是否选择了 4B；程序也支持自行准备其他兼容模型。
- 本地编剧：Qwen3.5 9B 的量化文字模型，通过 `llama.cpp` 运行；视觉审核所需的额外投影模型尚未包含，文字模型不能替代它。
- 本地配音：Qwen3 TTS 及其所需文件。
- 动作：Wan2.1 图生视频模型和 LightX2V。动作模型及依赖体积较大；[LightX2V 兼容说明](patches/LightX2V-兼容说明.md)记录了固定版本和本项目补丁。
- 口型：MuseTalk、Whisper 和相关模型。各组件的实际配置要求以安装程序报告为准。
- 视频编码与导出依赖 FFmpeg。安装程序会优先使用已有可用版本，否则按提示下载单独的 GPL 版 FFmpeg 发行版。

安装脚本使用固定的来源、文件大小和 SHA-256 核验；本项目不重新发布模型权重。下载中断后可重新运行安装程序；如果目标文件或已有运行器与清单冲突，脚本会停止并保留原文件供检查。模型及下载工具需要联网，涉及的许可可能与本项目代码许可不同，请在使用前核对实际版本。

## 使用和作品保存

- 本机作品位于项目目录内的“我的作品”“我的角色”“创作素材”和“备份与记录”。备份作品时请连同这些目录一起备份。
- 模型和运行环境位于 `app/work/` 与 `app/runtime/`；生成过程也可能使用 `app/outputs/`。
- `.gitignore` 默认排除上述作品、运行环境、模型和常见媒体文件。自行分享或提交时仍要检查暂存文件和 Git 历史，切勿强制上传私人作品、令牌、日志或大型模型。
- 浏览器界面是本机服务，默认地址为 `127.0.0.1`；请不要在未做好访问控制时把服务暴露到公网。

## 常见问题

**启动后部分功能显示缺少模型？** 先确认安装选项及窗口中的失败原因，再检查网络、磁盘空间、模型许可和相应模型文件；基础界面安装本身不包含生成模型。需要时可重新运行对应安装选项。

**已经有同名文件，安装器提示冲突？** 安装器保留了原文件。请先自行备份、核对来源和内容，再决定如何处理；不要直接删除原作品或依赖。

**显卡、内存不足或模型运行失败？** 首先检查驱动、可用显存和内存。不同模型的资源需求差异很大，模型文件存在并不代表显卡兼容或可完成推理。

**生成质量能直接用吗？** 角色一致性、口型、动作、字幕、声音、叙事连续性都需要人工审片和修正。第三方模型的输出效果、可用性和授权以其发布方说明为准。

## 第三方来源与许可证

本项目自有代码采用 [MIT 许可证](LICENSE)。第三方源码、程序、模型和素材使用各自许可证，安装或使用前请核对：

- [FLUX.2 klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)、[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)
- [Qwen3](https://huggingface.co/Qwen/Qwen3-4B-GGUF)、[Qwen3.5](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF)、[Qwen3 TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [LightX2V](https://github.com/ModelTC/LightX2V)（[Apache 2.0 许可](third_party_licenses/LightX2V-Apache-2.0.txt)）、[Wan2.1](https://huggingface.co/lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill-Lightx2v)、[MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [FFmpeg](https://ffmpeg.org/legal.html)、[llama.cpp](https://github.com/ggml-org/llama.cpp)、[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)。Real-ESRGAN 派生部分保留其 [BSD 3-Clause 许可](third_party_licenses/Real-ESRGAN-BSD-3-Clause.txt)。

旧动作模板原本依赖特定素材与固定坐标，相关素材没有随本仓库发布，使用者需要自行准备和适配。
