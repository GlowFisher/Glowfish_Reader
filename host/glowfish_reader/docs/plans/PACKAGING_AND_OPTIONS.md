# 打包与配置选项方案（2026-07-08 草案，待拍板）

## 0. 结论先行

三件事导致「开发态测出来的精度，装机版用户一分钱都拿不到」：

1. ~~`spec` 里 `excludes=["…","paddle"]` → 装机版跑不了默认引擎 `ppocrv6_high`，回落 `ppocrv6_onnx`。~~
   已消解：满血档改为 `ppocrv6_onnx_high`（纯 onnxruntime，随包走），`ppocrv6_high` 已删。见 docs/OCR_满血版设计.md。
2. `assets/lexicon/` 与 `models/mlm/` 不在 `spec` 的 `datas` 里 → 纠错层加载到空表、静默 no-op。
3. `models/punct/model_int8.onnx` 本地不存在（v1.0.4 交接版只带 fp32）→ spec 的 `if exists` 跳过 → 断句模型又没进包（2026-07-02 修过的同一个 bug 复发）。

共同点是**静默降级**：功能没了，程序照跑，没人知道。方案的核心不只是"补打包"，而是**让缺件必须尖叫**。

---

## 1. 模型资产清单（2026-07-08 清理后）

| 资产 | 大小 | 用途 | 上线 |
|---|---|---|---|
| `models/ppocrv6_onnx/` | 133MB | ONNX 识别引擎（唯一能在 exe 内跑） | ✅ 必带 |
| `models/punct/model_int8.onnx` | 103MB | 古文断句（per-channel 量化，F1 0.805 = fp32） | ✅ 必带 |
| `models/mlm/model_int8.onnx` | 123MB | GuwenBERT 语义纠错 | ✅ 建议带 |
| `assets/lexicon/*.txt` | 0.4MB | confusion / confusion_suggest / domain_fixes / bigrams / surnames | ✅ 必带 |
| `models/punct/model.onnx` | 407MB | 量化源，dev only | ❌ |
| `models/mlm/model.onnx` | 487MB | 量化源，dev only | ❌ |
| `_work/paddlex_cache/PP-OCRv6_medium_*` | 134MB | 高精度引擎权重，走外部 conda env | ❌（见 §3） |

已删除：`models/mlm_dapt/`（DAPT 裁决否决，checkpoint 留档 `D:\CC-train\dapt\guwenbert-dapt`）。

**必带资产合计 ≈ 359MB**（+ PyInstaller runtime / onnxruntime / paddleocr-paddlex / opencc，需实测一次构建才知底座多大）。

---

## 2. 配置选项设计：三档 + 勾选项

把「引擎」和「后处理增强」分开——前者互斥单选，后者独立开关。

### 2.1 识别精度档（单选，`appconfig.engine`）

| 档位 | 底层 | 页1/页2 字准率 | 速度 | 依赖 |
|---|---|---|---|---|
| **快速** | `ppocrv6_onnx` 单趟 | 0.8856 / 0.7292 | 32–45s/页 | 包内自带 |
| **精细**（默认，*待开发*） | onnx + `high_accuracy` 多候选 + 选择性救列 | 待实测 | 待实测 | 包内自带 |
| **极致** | 外部 PaddleOCR 环境（检测到才显示；有 N 卡自动 GPU） | 0.9019 / 0.8901 | 19–27s/页（GPU）<br>**22 分/页（CPU）** | 用户自装 conda env |

- 「极致」档在未检测到 `paddle_py` 时**灰显并提示**，而不是选了以后静默回落。
- 「极致」+ CPU 时必须警告 22 分/页，否则用户会以为程序卡死。
- 「精细」档是关键投资：onnx 与 paddle 用同一组 PP-OCRv6_medium 权重（det 62MB/rec 76MB ≈ paddlex 的 60/74MB），把 `_recognize_one_high_accuracy` 的多候选流程移植过去，理论上零包体增量拿回大部分精度。**需要先做一次验证再决定是否作为默认档**。

### 2.2 增强项（勾选，各自独立开关，已有 env 一一对应）

| 选项 | env | 默认 | 代价 | 说明 |
|---|---|---|---|---|
| 简繁转换与异体字修正 | —（`t2s_fixes` 常开） | 开 | 0 | 无模型 |
| 竖列读序修正 | `SHUPAI_COL_AGG_YGUARD` | 开 | 0 | 行草页读序，日记 +19.6pt |
| 边框/波谷列检测 | `SHUPAI_COL_DETECT_V2` | 开 | 0 | 带边框页漏字 53→0 |
| 夹注读序合并 | `SHUPAI_INTERLINEAR` | 开 | 0 | 双行小字夹注 |
| **域词修复** | `SHUPAI_DOMAIN_FIXES` | 开 | 0.4MB / ~0s | 空跑审计证明零误纠 |
| **语义纠错（AI）** | `SHUPAI_OCR_CORRECT` | 开 | 123MB / **4.3s 每页** | 页1 +1.9pt、页2 +4.3pt |
| **自动断句** | `punct_backend` | 开 | 103MB | 已有设置项 |
| 人名切分建议 | `SHUPAI_NAME_SEGMENT` | 开 | 0 | 只出建议不改字 |
| 退化页预处理 | `degraded_preproc` | **关** | +30~40% 耗时 | A/B 判负（页2 −1.34pt），留给用户试 |

原则：**会改字的层默认开且可关；只给建议的层无所谓；A/B 判负的层默认关但保留**。

---

## 3. 打包方案

### 3.1 必做（无论引擎路线怎么选）

1. `spec` 的 `datas` 补三项：
   - `assets/lexicon` → `assets/lexicon`
   - `models/mlm/{model_int8.onnx,vocab.txt,meta.json}` → `models/mlm`
   - `models/punct/model_int8.onnx`（现已存在，原逻辑即可命中）
2. **构建后冒烟必须断言能力齐全**，而不是靠肉眼：见 §4。
3. `models/mlm_dapt/` 已删，确保不会被 `collect_*` 意外扫进去。

### 3.2 包体分级（可选）

模型增量下载通道在 v1.0.4 交接版里已丢失（`release.ps1` 无 `-UploadModels`、`updater.py` 无 `evaluate_models`）。重建它是一笔独立工作。在那之前建议：

- **单包**：全带（+359MB 资产）。简单、离线可用、符合「本地不上传」的产品定位。
- 若日后包体成为障碍，再重建双包（代码包 / 模型包），把 mlm(123MB) 与 punct(103MB) 挪到模型包。

---

## 4. 防止「静默失效」再犯（本方案的重点）

新增 `proofread/capabilities.py`：

```python
def capabilities() -> dict:
    """逐项报告能力是否真的可用（引擎/断句/语义纠错/词表），供启动自检与设置页显示。"""
```

三处消费它：

1. **构建后冒烟测试**（新增 `test_packaging_assets.py` 或 release.ps1 的一步）：
   冻结 exe 跑 `--selftest-capabilities`，任何一项为 False 即**构建失败**。
   这条能一次性杜绝 punct/mlm/lexicon 三类漏打包。
2. **App 启动自检**：缺件时在 UI 顶部挂持久横幅（复用已有 `gfShowFallbackBanner`），
   写明「语义纠错未启用：模型缺失」，而不是安静地少改几个字。
3. **设置页**：每个勾选项旁显示其依赖资产是否在位；不在位则灰显 + 说明。

---

## 5. 待决策 / 待验证

| 事项 | 需要什么 |
|---|---|
| 「精细」档能追回多少精度 | 一次移植验证（把 high_accuracy 多候选搬到 onnx 引擎，跑三样本） |
| MLM 123MB 是否进主包 | 若「精细」档把页2 拉到 0.85+，MLM 的 +4.3pt 仍值这 123MB |
| 是否重建模型增量下载通道 | 取决于主包体积能否接受 |
| 「极致」档要不要写进产品 | 需要用户自装 conda paddle env，是「高级用户」功能还是干脆不暴露 |

---

## 附：本轮清理与修复记录

- 删 `models/mlm_dapt/`（123MB，DAPT 否决，代码零引用）。
- 重建 `models/punct/model_int8.onnx`：⚠ **必须 `per_channel=True`**。
  per-tensor 量化 F1 0.792（fp32 0.805，−1.3pt）；per-channel 量化 F1 **0.805 = fp32，无损**。
  与 MLM 掩码头同一条铁律。（`bench/eval_punct.py --int8-ab` 复核）
- 清 `bench/out/_img/` 中间裁图。
