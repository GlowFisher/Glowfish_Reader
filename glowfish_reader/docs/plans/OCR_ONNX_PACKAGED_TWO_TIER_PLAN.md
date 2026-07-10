# 打包版 ONNX 双档 OCR 方案

## Summary

打包版 OCR 只提供两个用户可见档位：**满血版** 和 **轻量版**。满血版对应 `ppocrv6_onnx_high`，使用 ONNX 模型并启用 high_accuracy、多候选识别、列救援、缺失列补扫、宽列补扫和质量合并；轻量版对应 `ppocrv6_onnx`，保留现有快速 ONNX 路线。

这版方案包含原 `OCR_ONNX_HIGH_TIER_PLAN.md` 的核心内容，并把 ONNX 高精档升级为 ONNX 路线的能力上限。

## Key Changes

- 新增 `ppocrv6_onnx_high`：
  - 使用 `recognize_ppocrv6_onnx.py`
  - 参数包含 `profile="high_accuracy"`、`column_rescue=True`、`text_det_box_thresh=0.45`
  - 新增常量 `ONNX_HIGH_ENGINE`
- 打包版默认 OCR 改为 ONNX 高精：
  - 满血版：`ppocrv6_onnx_high`
  - 轻量版：`ppocrv6_onnx`
  - UI 设置里只展示这两个选项
  - Paddle v6 可保留为开发/诊断入口，但不再是打包用户默认链路
- ONNX 高精实现为能力上限：
  - 全页增强识别
  - body crop 识别
  - 竖列检测
  - 低召回页扫描全部列
  - 非低召回页使用 `uncovered_columns` 找漏列并补扫
  - 对目标列执行普通列补扫和宽列补扫
  - 用 `merge_high_accuracy_lines` 合并候选并抑制垃圾列
- 默认 fallback 链改为：
  - `ppocrv6_onnx_high -> ppocrv6_onnx`
  - 高精失败或质量明显更差时才落轻量版
  - 高精落轻量是精度降级，应保留横幅提示
- 吸收原方案的配套改动：
  - ONNX worker 支持 `ppocrv6_onnx_high`
  - frozen `--ocr ppocrv6_onnx_high` 显式分发到 ONNX 脚本
  - `run_job` / `serve_worker` / `OcrWorker.submit` 全链路透传 config
  - `_build_engine` pop 掉 `profile`、`column_rescue`、`degraded_preproc`
  - 缓存 hash 区分高精和轻量，轻量缓存不能冒充满血版
  - bench 增加 `ppocrv6_onnx_high`
  - 文档改成 ONNX 双档说明

## Public Interfaces

- 用户可见 engine：
  - `ppocrv6_onnx_high`：满血版
  - `ppocrv6_onnx`：轻量版
- 设置页文案：
  - 满血版：本机打包可用的最高精度 OCR 档
  - 轻量版：速度优先的 ONNX OCR 档
- `_recog.json`：
  - `_meta.engine` 写实际档位
  - ONNX 高精页面 `ocr_meta.profile == "high_accuracy"`
  - ONNX 高精页面 `ocr_meta.backend == "ppocrv6_onnx"`

## Test Plan

- 引擎注册：
  - `ppocrv6_onnx_high` 存在
  - 默认满血档解析为 `ppocrv6_onnx_high`
  - 轻量档解析为 `ppocrv6_onnx`
- ONNX 高精流程：
  - high profile 会跑全页增强、body crop、列补扫、宽列补扫
  - 低召回页补扫全部列
  - 非低召回页补扫 `uncovered_columns`
  - 候选失败只记录到 `failed_candidates`，主识别失败才整页失败
- UI / 打包：
  - 设置页只有满血版和轻量版
  - 满血版请求实际运行 `ppocrv6_onnx_high`
  - frozen `--ocr ppocrv6_onnx_high` 走 ONNX 脚本
- fallback / 缓存：
  - 满血失败后落轻量
  - 满血缓存和轻量缓存 hash 严格区分
  - 轻量缓存不能命中满血请求
- bench：
  - `bench/run_bench.py --engine ppocrv6_onnx_high --only 手写`
  - gated F1 必须不低于现有轻量 ONNX 基线 `.9681`
  - 若低于轻量基线，不把满血版默认指向该实现

## Assumptions

- 打包版不再依赖 Paddle 环境。
- Paddle 相关代码可以保留，但不参与打包用户的设置选项和默认 fallback。
- ONNX 高精档必须包含轻量档已有的列救援能力；`uncovered_columns` 不是轻量专属能力。
- 轻量版保留为速度优先和最终兜底。
