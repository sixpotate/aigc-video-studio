# LightX2V 动作引擎兼容资料

此目录只包含补丁和公开模型的校验清单，不包含模型权重、用户图片、视频或项目。

动作引擎使用 [ModelTC/LightX2V](https://github.com/ModelTC/LightX2V)，源码按 Apache-2.0 许可发布。已比对的基线为提交 `a4b8ce30ac73ae561ec9d1a8bc6629e4aed9d2d8`。此仓库的 `lightx2v-a4b8ce3-compat.patch` 包含两处修改：初始化无偏置线性层的 `bias`，以及避免加载 T5 预训练参数前对大词嵌入表作不必要的随机初始化。补丁保留上游文件的版权与许可声明；分发引擎时也必须保留上游的 LICENSE 和版权通知。

该提交的源码 ZIP 可从 `https://codeload.github.com/ModelTC/LightX2V/zip/a4b8ce30ac73ae561ec9d1a8bc6629e4aed9d2d8` 下载。一次实际读取所得 ZIP 字节数为 12659794，SHA-256 为 `e9995e64b21ca65c582bc3fb0d712e54f635e0fa50456f393583d621bd056277`。解压时需检查路径安全，且不要覆盖已有的引擎目录或用户文件。

在新下载的固定版本源码目录中，可以先用 `git -c core.autocrlf=false apply --check <补丁路径>` 检查，再用 `git -c core.autocrlf=false apply <补丁路径>` 应用。应先确认补丁文件路径以及源码目录；如果检查失败，应停下调查，不能强行覆盖。这里显式关闭自动换行转换是为了便于在 Windows 与原文件逐字节比较。

已实际测试：在空临时目录下载这两个上游原文件后，补丁检查和应用成功，应用后的内容与已安装版本逐字节一致，逆向检查也通过。该测试没有启动模型；它不证明全新机器上的安装、推理或显存要求已通过验收。

图生视频模型使用 [LightX2V Wan 2.1 I2V 蒸馏模型](https://huggingface.co/lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill-Lightx2v)，本清单固定版本 `fef288b326f4fed6d2983b9800c35363da31fcfe`，许可标记为 Apache-2.0。`wan21-distill-fp8-manifest.json` 记录了该版本 `distill_fp8/` 下 55 个文件的名称、字节数及 SHA-256；大文件散列来自官方 LFS 元数据，小文件散列通过实际读取计算。该目录约 25.1 GB，官方已提供 `block_0.safetensors` 到 `block_39.safetensors`，无需从其他权重自行拆分。

将目录内容保存在 `app/work/motion_test/models/distill_fp8/`，使 `block_0.safetensors`、`non_block.safetensors`、`clip-fp8.pth`、`models_t5_umt5-xxl-enc-fp8.pth` 和 `Wan2.1_VAE.pth` 直接位于该目录，同时保留 `google/umt5-xxl/`、`xlm-roberta-large/` 子目录。下载工具应校验完整性，且不得覆盖用户已有模型。

本机已有全部 40 块，文件大小与清单一致；其中 6 个小文件经 SHA-256 比较一致，大块未逐个读取校验，因此不能据此断言所有本地权重内容完全一致。现有可选的 `umt5-xxl-fp8-lazy.safetensors` 不属于本清单；不存在时程序会回退官方 T5 权重，实际内存消耗及推理兼容性仍需在目标机器上验证。不同模型的许可证和使用条款可能不同，请在下载时查看对应来源。
