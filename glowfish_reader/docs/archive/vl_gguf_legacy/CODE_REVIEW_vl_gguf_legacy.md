# GlowFish 史料阅读器代码审查记录

> 本记录面向后续 Fable 5 接手迭代：先说明本轮审查范围、已修问题、仍需跟进风险和验证结果。详细项目背景见 `FABLE_HANDOFF.md` 与 `HANDOFF.md`。

## 审查范围

- 桌面入口与服务装配：`proofread/desktop_app.py`、`proofread/server.py`
- OCR 引擎接缝：`proofread/engines.py`、`appconfig.py`、`content_api.py`
- VL GGUF 路径：`recognize_vl_gguf.py`、`vl_layout.py`、`vl_llama.py`
- 数据模型与导出：`proof_model.py`、`export_api.py`
- 授权与更新：`license_api.py`、`licensing/*`、`update_api.py`、`updater.py`
- 交接文档：`HANDOFF.md`、新增 `FABLE_HANDOFF.md`

## 已修问题

### 1. 桌面入口覆盖默认引擎

**问题**：`appconfig.DEFAULTS["engine"]` 和 `engines.DEFAULT_ENGINE` 已声明默认 `vl_gguf`，但 `desktop_app._start_server()` 与 `_serve_headless()` 又通过 `os.environ.setdefault("SHUPAI_ENGINE", "onnx")` 把桌面/headless 入口真实默认压回 ONNX。

**影响**：文档与代码表面都说 Fable 应继续推进 VL 默认引擎，但用户实际启动桌面 App 时仍可能默认走 ONNX，导致后续排查方向错误。

**处理**：删除两处 `SHUPAI_ENGINE=onnx` 默认覆盖，让入口服从 `appconfig/engines`。新增 `test_desktop_engine_default.py` 防回归。

### 2. VL 回退信息被最终进度覆盖

**问题**：`content_api._ensure_recog()` 在 `vl_gguf` 失败并回退 ONNX 后会写入 `fallback` 进度，但 `/api/open` 末尾无条件写普通 `done`，覆盖了回退原因。

**影响**：即使自动回退成功，前端和后续维护者也看不到“为什么没有走 VL”，降低可观测性。

**处理**：新增 `_finish_progress()`，导入结束时保留原进度里的 `fallback` 字段；补 `test_finish_progress_preserves_fallback()`。

## 仍需跟进的风险

> 状态更新（2026-07-02）：#1 已完成、#5 已落地；#2/#3 本轮已修复（含测试）；#4 留档排队；#6 已部分清理。

1. **VL 真资产冒烟未完成** — ✅ 已完成
   `models/vl/`（1.1G）与 `vendor/llama/`（43M）真资产已在位，`recognize_vl_gguf.py` 已在手写集端到端跑通，实测 **F1=0.972**（> onnx 0.936，提交 `b4e02f7`）。

2. **`vl_llama.LlamaServer.close()` 只 terminate 不 wait/kill** — ✅ 本轮已修复
   `close()` 改为 terminate→wait(超时)→kill→wait，全程异常安全且幂等；`test_vl_llama.py` 补 kill 兜底与异常安全两用例。

3. **`recognize_vl_gguf.py` 单页失败时 width/height 为 0** — ✅ 本轮已修复
   失败页改写归一图真实尺寸（归一图→原图→仅当图不可读才退 0×0），输出契约不变；`test_vl_gguf.py` 补图可读/不可读两用例。

4. **`vl_layout.sort_reading(auto)` 规则仍朴素** — ○ 留档排队
   当前按 `vertical_text` 占比判断竖排；混排标题、页眉、表格、注脚可能误序。行书页阅读序损失（CER−(1−F1)≈0.06）已留档，作版面侧优化排队项，待有失败样张纳入 bench/gold 后再改，不凭感觉调。

5. **打包体积与更新拆分未验证** — ✅ 已落地
   代码/模型双通道拆分已实现：`update.json` v2 顶层全量包兼容旧客户端 + `code{}` 代码小包 + `models.vl{}` 模型通道，staging 原子换入（提交 `40248cb`/`1744dfe`/`a7710a8`）。1.0.2 双包首次实跑构建与 clean 机验收随本轮发版进行。

6. **工作区脏状态很大** — ◐ 已部分清理
   `D:\CC-first` 中 `_upgrade_log` 历史快照曾有大量删除状态；已清理 820 个文件的历史快照（提交 `70a365b`）。抽独立仓库或提交前仍须只取 `glowfish_reader` 主代码和新文档，避免把历史快照删除混入。

## 验证结果

```powershell
cd D:\CC-first\glowfish_reader\proofread
..\.venv\Scripts\python.exe -m pytest test_desktop_engine_default.py test_content_fallback.py test_vl_gguf.py -q
# 9 passed

cd D:\CC-first\glowfish_reader\proofread
..\.venv\Scripts\python.exe -m pytest test_desktop_engine_default.py test_content_fallback.py test_vl_gguf.py test_vl_layout.py test_vl_llama.py test_vlm_appconfig.py test_vlm_engines.py test_proof_model.py test_update_api.py test_updater.py -q
# 60 passed

cd D:\CC-first\glowfish_reader
.\.venv\Scripts\python.exe -m pytest license_server\tests proofread\licensing\tests -q
# 60 passed
```

## 下一轮建议

下一轮不要先大改 UI。优先顺序应是：VL 真资产冒烟、fallback 前端提示、bench 三方对照、干净机打包验收、更新拆分。完成这五件事后，再考虑交互细节和商业化页面。
