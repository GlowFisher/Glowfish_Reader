# OCR 满血版设计（唯一信源）

> 引擎名 `ppocrv6_onnx_high`，`engines.py` 的 `DEFAULT_ENGINE`。
> 本文是满血版的唯一设计文档。旧的 Paddle 满血档 `ppocrv6_high` 已作废删除。

## 一句话

**满血版 = ONNX 运行时的 PP-OCRv6 + det 输入尺度自适应（治整列漏检的根因）+ 三层后处理增强。**
轻量版 `ppocrv6_onnx` 是同一份模型、同一个检测尺度修复，只是不跑那三层增强。

## 为什么只剩一个满血版

历史上有两个"满血版"，路子相反：

| | 老 Paddle 满血档（已删） | 现满血档 |
|---|---|---|
| 引擎名 | `ppocrv6_high` | `ppocrv6_onnx_high` |
| 运行时 | PaddleOCR 静态图 | onnxruntime |
| 打包 | ✗ 需要额外的 PaddleOCR 解释器 | ✓ 随 App 走 |
| 思路 | 修检测器本身 | 修检测器 + 外挂后处理 |

打包版里根本装不下 Paddle 那套解释器，`ppocrv6_high` 在装机版上永远回落到轻量档——
它只在开发机上"是"满血版。删掉它，满血版就只有一个，不再有"我这里是满血、用户那里不是"的错位。

`ppocrv6`（官方本地 PaddleOCR）保留为 dev/诊断对照路径，不是满血档。

## 底座：det 输入尺度自适应（`det_scale.py`）

这是整条链上**唯一的大头**，不是"增强"，是根因修复。

PaddleOCR 的 pipeline 配置（`paddlex/configs/pipelines/OCR.yaml`）把
`limit_side_len` 写死成 `64/min`，覆盖了 `PP-OCRv6_medium_det` 自己设计的 `960/max`。
后果：4000×6000 的史料大图**从不缩放**，字符尺寸远超模型训练尺度，DB 检测头的置信度塌陷，
**整列文字被漏掉**。同一份 yaml 还把 `box_thresh` 从模型自带的 0.45 抬到 0.6，雪上加霜。

修法：先跑一趟列检测量出列距，反推"缩放后列距 ≈ 目标值"的 `text_det_limit_side_len`，
按页下发给 `predict()`；`box_thresh` 显式调回 0.45。列裁剪图必须施加**同一个** scale。

消融实测（手写集，2026-07-08）：

```
baseline 全开        F1 0.942
关列救援             F1 0.942   (Δ  0.000)   ← 列救援是尺度失配时代的补丁，病根治好后纯属重复劳动
关第二尺度 alt       F1 0.940   (Δ -0.002)
只留整页单趟         F1 0.941   (Δ -0.001，趟数 8→1，每页 3.50s→1.26s)
关 det 尺度自适应    F1 0.925   (Δ -0.017)   ← 唯一的大头
```

所以满血档的主干是 **整页单趟 + det 自适应**，列救援只保留 `uncovered_columns` 兜底。

⚠ 尺度是刀锋解：缩放后列距 46/58/65 可用，50/62/78 会整列塌。别再微调 `target_pitch`，
免疫力来自把 `box_thresh` 调回 0.45。
⚠ `limit_type=max` 会丢掉 `64/min` 的短边放大保底，必须把 scale 夹到 `64/短边`，
统一走 `det_for_size()`。

## 三层后处理增强（`ocr_enhance.py` + `ocr_confusion.py`）

搬自同事分支 `onnx-high-accuracy-v2`（提交 `1cfe7a2e`），**每层可用环境变量单独关断**以做消融。

| 层 | 开关 | 做什么 |
|---|---|---|
| 手写页低阈值二检 | `GF_HIGH_LOWTHRESH` | 稀疏/小字页用 `box_thresh=0.35` 再检一遍，合并 |
| 低置信行多预处理集成 | `GF_HIGH_ENSEMBLE` | score<0.85 的行，用 enhanced/CLAHE/denoise 三种预处理各识一遍，投票 |
| 小字超分重识 | `GF_HIGH_SMALLSR` | 短边<20px 的框 2× Lanczos 放大重识 |
| 形近字词典纠错 | `GF_OCR_CONFUSION` | 92 对形近字 + 60 词组上下文纠错（纯文本，两档共用） |

另有合并前的低分预过滤（`GF_HIGH_MINSCORE`，默认 0.55）。

### 搬迁时修掉的三个缺陷

原实现有三处会**主动把对的字改错**，不修不能上线：

**① 投票的"分数"是一致率，不是置信度。**
`_vote_chars` 返回的是三个预处理变体彼此同意的比例——它们一起认错同一个字时，
这个数照样接近 1.0。原实现拿它跟模型的 rec score 比大小来决定要不要替换
（`new_score > line.score`），等于用两个不同量纲的数比大小，**替换条件几乎恒真**。

实测铁证（s04_p1，退想斋日记）：

```
原行   天龍山聖壽寺駐特僧佛晉祠朝陽洞厚上午來拜年   rec score 0.792
三变体 enhanced 0.742 / clahe 0.742 / denoise 0.799   ← 都不比原行强，且各自认错字
投票产物 天龍山聖壽孝羅特僧在晉祠朝陽洞事上午來拜年   "分数" 0.953   ← 纯属虚构
```

修法：集成分取**变体 rec score 的均值**（同量纲），且需超出原行 `0.05` 余量才替换。
裁剪重识丢了整页上下文，平手时原行更可信。

**② 按字符位投票要求各变体等长。** 一处多识/漏识就让其后全部错位。
改为等长才投票，不等长退回最高分变体。

**③ 形近字纠错缺"原字已成词"护栏。**
原实现只判"替换后能否凑出已知词"。而 `CONFUSION_MAP` 是**双向**的，词表里
`大爺` 和 `太爺` 并存 → 正确的 `太爺` 被改成 `大爺`，反之亦然，**纯抛硬币**。
加 `_forms_compound(chars, i, 原文)` 护栏：原字本来就成词就跳过。

顺带修掉日期规则：原规则"数字后的 `曰` → `日`"会把文言列举 `一曰…五曰…` 改坏
（退想斋日记 s01 真值即「國之民五曰宗」）。日期的数字是两位以上（`二十曰`/`廿八曰`/`三月十五曰`），
故要求前文近处有「年/月」，或 `曰` 前是连续两个以上数字字。

### 另两处实现问题

- 层⑤原实现**每页重建一个 PaddleOCR 实例**（一页一次模型加载）。
  paddleocr 3.x 的 `predict()` 本来就收 `text_det_*` 参数，逐调用覆盖即可。
- 层④原判据是 `box 高 < 20px`。竖排史料里一"行"就是一整列、又高又窄，该判据几乎永不触发。
  改成判**短边**。

## 回退链

```
ppocrv6_onnx_high  →  ppocrv6_onnx        （打包版；两跳）
ppocrv6            →  ppocrv6_onnx        （dev；官方档质量太差时按 _recog_quality 改投）
```

满血 ONNX **不做**"质量差就降级轻量"的兜底——两档同一批模型，轻量只是少跑几层后处理，
不可能更好，那趟往返纯属浪费。

## 评测

`bench/run_bench.py` 默认即 `ppocrv6_onnx_high`（引擎 params 从 `engines.py` 单一信源读）。

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe bench\run_bench.py --only 手写
```

手写集 5 份文档 11 页：s01 行楷 / s02 行书 / s03 草书公文（基线桶，不卡门）/ s04 行书 /
s05 行书公文（《黔人自组盐号承办仁岸运销节略》，用户人工点校稿为真值）。

⚠ 评测真值必须是人工点校稿。用 App 自己的辑录输出当真值 = 自己考自己，分数无意义。

## 相关文件

- `proofread/engines.py` — 引擎注册与默认档（单一信源）
- `proofread/det_scale.py` — det 输入尺度自适应
- `proofread/recognize_ppocrv6_onnx.py` — 两档共用的识别主流程
- `proofread/ocr_enhance.py` — 满血档的后处理增强层
- `proofread/ocr_confusion.py` — 形近字词典纠错
- `proofread/test_onnx_high_profile.py` — 满血档流水线不变量
