# Fable 5 接手速读：GlowFish 史料阅读器

> 目标：让 Fable 5 在接手后先建立正确项目心智，再进入代码审查、精度迭代、打包发布。本文是快速入口；深层细节仍以代码、测试、`HANDOFF.md` 和专项文档为准。

## 1. 项目一句话

GlowFish 史料阅读器是一款 Windows 本地桌面 App，用于识别竖排繁体近代史料（印刷报纸、日记手写等），在本地完成 OCR、断句、简繁转换、校对、批注和 docx 导出。核心卖点是：竖排、繁体、近代史料/手写、简体辑录、史料不上传。

## 2. 当前代码状态

- 主目录：`D:\CC-first\glowfish_reader\`
- App 主体：`proofread/`
- 授权服务：`license_server/`
- 准确率回归：`bench/`
- 当前默认引擎意图：`vl_gguf`，在 `appconfig.DEFAULTS["engine"]` 与 `engines.DEFAULT_ENGINE` 中声明。
- 快速兜底引擎：`onnx`，即 PP-OCRv5 ONNX，CPU 快、可打包、手写基线 F1 约 0.936。
- 高精开发态引擎：`paddleocr_vl`，依赖独立 conda/GPU，不随 App 打包。
- 消费版高精方向：`vl_gguf`，基于 PP-DocLayoutV3 ONNX + llama-server + PaddleOCR-VL GGUF，目标是 CPU、离线、随安装包分发。

## 3. 先读顺序

1. `FABLE_HANDOFF.md`：先读本文，建立任务地图。
2. `HANDOFF.md`：读完整交接，包括环境、架构、授权、发版、密钥清单。
3. `proofread/engines.py`、`appconfig.py`、`content_api.py`、`desktop_app.py`：确认真实运行路径。
4. `proofread/recognize_onnx.py`、`recognize_vl_gguf.py`、`vl_layout.py`、`vl_llama.py`：确认 OCR 引擎契约。
5. `bench/README.md`、`bench/run_bench.py`、`bench/out/*.md`：确认精度口径和当前基线。
6. `proofread/发版指南_开发端.md`、`license_server/运营SOP.md`：发布和运营前再读。

## 4. 架构地图

```text
desktop_app.py
  -> 内嵌 uvicorn/FastAPI server.py
  -> static/ 前端
  -> content_api.py 导入、识别、proof 构建、标点、保存
  -> export_api.py 导出 docx/txt/md/csv/zip
  -> license_api.py 授权门
  -> update_api.py 应用内更新

OCR 引擎层：
  engines.py
    vl_gguf       -> recognize_vl_gguf.py -> vl_layout.py + vl_llama.py
    onnx          -> recognize_onnx.py
    paddle        -> recognize.py
    paddleocr_vl  -> recognize_vlm.py

数据模型：
  proof_model.py
    text_ocr -> text_draft -> text
    aggregate_columns -> default_order -> assemble_paragraphs -> export_docx
```

## 5. 不要破坏的铁律

- 识别脚本输出契约不可改：
  `{ "<page_id>": {"image","width","height","lines":[{"text","box","score"}]} }`
- 所有识别脚本必须把 EXIF 朝向烘焙到 `_img/`，叠框坐标必须对应归一图。
- `proof_model.py` 是核心数据模型，改动前先读测试并补测试。
- 准确率评估必须先繁转简、剥标点、剥空白等噪声，否则会把后编辑和标点算成 OCR 错。
- 产品/打包 Python 是 `glowfish_reader\.venv`；Paddle/VL 开发态另走 conda；不要混解释器。
- 打包严禁引入 torch/paddle 到 `.venv` 或安装包。
- 授权私钥、服务器密钥、生产数据库绝不进入 git 或聊天。
- `SHUPAI_*` 环境变量前缀是历史兼容名，不要因品牌改名随手替换。

## 6. 当前最该做的迭代

> 更新（2026-07-02）：下列六项已基本落地，仅印刷金标准一项未完。逐条状态见每项末尾。

1. **确认默认引擎真实一致** — ✅ 已完成（提交 `5bfe4b6`）
   验证桌面、headless、server 三种入口默认是否都按 `vl_gguf` 意图运行；若资产缺失，应可观测地回退 `onnx`。
   已删除 `desktop_app` 中 `SHUPAI_ENGINE=onnx` 硬编码，三入口统一服从 `appconfig/engines`；防回归测试 `test_desktop_engine_default.py`。

2. **让 fallback 可见** — ✅ 已完成（提交 `66a803b`/`6fe39fb`）
   当 `vl_gguf` 缺资产、启动失败或识别失败时，应在前端进度、日志、proof 元信息中看见“从 vl_gguf 回退 onnx”的原因。
   `content_api._mark_fallback`/`_finish_progress` 保留回退字段，前端 `app.js gfShowFallbackBanner` 显示橙色持久横幅。

3. **跑通 VL 真件冒烟** — ✅ 已完成（提交 `b4e02f7`）
   下载/校验 `models/vl/` 与 `vendor/llama/` 资产；用 2-3 张真实竖排/手写样张跑 `recognize_vl_gguf.py`，检查非空、坐标、阅读序和耗时。
   资产已在位（`models/vl` 1.1G + `vendor/llama` 43M），手写集实测 F1=0.972（> onnx 0.936）。

4. **bench 接 VL 并制度化** — ◐ 部分完成（唯一未完项：印刷金标准）
   `bench/run_bench.py` 已有 `vl_gguf` 分支。下一步是补印刷金标准、记录 VL/ONNX/Paddle 三方结果，避免靠主观样张判断。
   `run_bench` 三引擎对照已接通；印刷金标准集 `bench/gold_printed/` 仍空，是本项唯一缺口。

5. **打包与安装包体积验证** — ✅ 已完成
   确认 `glowfish_reader.spec` 是否包含 `models/vl/` 与 `vendor/llama/`，并在干净机验证：无 conda、无 NVIDIA 时默认可用；资产缺失时自动回退。
   spec 已含 VL 资产，并提供 `GF_SKIP_VL_MODELS` 开关剪出代码小包。clean 机验收随本轮 1.0.2 发版一起走。

6. **更新拆分** — ✅ 已完成（提交 `40248cb`/`1744dfe`/`a7710a8`）
   如果安装包因模型膨胀到 1GB+，应把模型版本和代码版本拆开，避免每次小修都让用户重新下载大模型。
   已落地 `update.json` v2：顶层全量包兼容旧客户端 + `code{}` 代码小包 + `models.vl{}` 模型通道，staging 原子换入。

## 7. 代码审查关注点

- ~~`desktop_app.py` 是否用环境变量覆盖了 appconfig 的默认引擎。~~ ✅ 已解决（删 `SHUPAI_ENGINE=onnx` 硬编码，`5bfe4b6`）。
- ~~`content_api.py` 是否在导入完成时覆盖了 fallback 进度。~~ ✅ 已解决（`_finish_progress` 保留 fallback，`66a803b`）。
- ~~`recognize_vl_gguf.py` 单页失败时 width/height 置 0，会不会影响前端叠图和导出。~~ ✅ 已解决（失败页写归一图真实尺寸，图不可读才退 0；测试覆盖）。
- `vl_layout.sort_reading(auto)` 对混排、标题、表格、页眉是否足够稳。（留档排队，见 §10。）
- ~~`vl_llama.LlamaServer.close()` 是否需要 wait/kill 兜底，避免升级/退出时残留 llama-server。~~ ✅ 已解决（terminate→wait→kill→wait 异常安全兜底；测试覆盖）。
- ~~`bench/run_bench.py` 的 help 文案是否仍只写 onnx/paddle。~~ ✅ 已解决（docstring/help/README 补齐三引擎）。
- ~~`HANDOFF.md` 是否与当前 `vl_gguf` 状态同步。~~ ✅ 已同步（§8/§13 已按双包/VL 默认刷新）。

## 8. 常用命令

```powershell
# 单元测试（App 主体）
cd D:\CC-first\glowfish_reader\proofread
..\.venv\Scripts\python.exe -m pytest test_content_fallback.py test_vl_gguf.py test_vl_layout.py test_vl_llama.py -q

# 授权测试
cd D:\CC-first\glowfish_reader
.\.venv\Scripts\python.exe -m pytest license_server\tests proofread\licensing\tests -q

# ONNX bench
cd D:\CC-first\glowfish_reader
.\.venv\Scripts\python.exe bench\run_bench.py --engine onnx --only 手写

# VL bench（需要资产）
cd D:\CC-first\glowfish_reader
.\.venv\Scripts\python.exe bench\run_bench.py --engine vl_gguf --only 手写

# 桌面开发态
cd D:\CC-first\glowfish_reader\proofread
..\.venv\Scripts\python.exe desktop_app.py
```

## 9. 当前文档分工

- `FABLE_HANDOFF.md`：Fable 5 快速接手入口。
- `CODE_REVIEW.md`：本轮代码审查记录、已修问题、剩余风险和验证结果。
- `HANDOFF.md`：完整工程/运营/交接总文档。
- `proofread/SPEC.md`：proof 数据模型与校对界面设计。
- `proofread/README_桌面版.md`：桌面 App 运行/打包基础。
- `bench/README.md`：准确率台架。
- `proofread/发版指南_开发端.md`：安装包与更新发布。
- `license_server/运营SOP.md`：授权码、席位、续费、备份。

## 10. 本轮审查结论

原定五件事——真实默认、可观测 fallback、VL 资产冒烟、bench 对照、打包验证——已做实（VL 手写 F1 0.972，默认引擎/回退横幅/更新拆分均已落地并有提交与测试）。当前重心转为 **1.0.2 双包发版闭环**（跳过 1.0.1，首次实跑代码小包 + 模型通道构建、clean 机验收、上传发布，UI 视觉再设计 v2 一并验收并入）**+ 印刷金标准**（`bench/gold_printed/` 仍空，是 bench 对照的唯一缺口）。排队后续：行书阅读序版面优化（`sort_reading`）、P3 商业化。GlowFish Reader 已从“能跑的原型/内测工具”跨入“可交付的商业软件”收尾阶段。
