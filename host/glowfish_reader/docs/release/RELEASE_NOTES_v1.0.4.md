# GlowFish Reader v1.0.4 修改说明

发布日期：2026-07-06

v1.0.4 是面向 GitHub 协作交接的小版本。核心产品路径继续沿用 v1.0.3 的 PP-OCRv6 主线，本版本重点是版本号同步和接手文档补齐。

## 变更内容

- 将运行时版本单一真源 `proofread/_version.py` 更新为 `1.0.4`。
- 新增 `项目交接文档.md`，覆盖项目定位、关键目录、本地运行、GitHub 协作、测试、发版和接手清单。
- 更新当前 handoff 文档中的版本口径，明确 `1.0.4` 是协作交接版本。

## 接手提示

- 当前默认 OCR 仍是 `ppocrv6`。
- 轻量 fallback 仍是 `ppocrv6_onnx`。
- 旧 VL/GGUF/llama/PaddleOCR-VL 路线仍为历史归档，不是当前主线。
- 发版时仍只需手动修改 `proofread/_version.py`，安装器版本由 `release.ps1` 注入。
