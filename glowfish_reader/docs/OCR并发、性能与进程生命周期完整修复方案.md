# Glowfish Reader OCR 并发、性能与进程生命周期完整修复方案

## 1. 文档目的

本文档针对 Glowfish Reader V1.0.0 安装版本中已经实机确认的 OCR 重复并发、CPU/内存长时间满载、CMD 闪窗和关闭应用后残留进程问题，给出完整的实施与验收方案。

本文是修复设计文档，不代表相关业务代码已经完成修改。

## 2. 已确认的问题与证据

排查的安装版本位于：

```text
D:\桌面\Glowfish Reader V1.0.0
```

实机发现三个 OCR 子进程同时执行相同任务：

```text
Glowfish Reader V1.0.0.exe
  --ocr ppocrv6_onnx_high
  --images ...\users\local\10\_src
  --out ...\users\local\10\_recog.json
  --progress ...\users\local\_import_progress.json
```

它们具有相同父进程、输入目录、输出文件和进度文件。两个高负载子进程分别占用约 5.88 GB 和 5.55 GB 私有内存。运行日志在约 12 分钟内记录了 22 次 OCR 进程初始化，其中约 0.18 秒内连续初始化了 4 个进程。

第一个进程写出 `_recog.json` 后，其他重复进程仍在生成 `_col_*`、`_lc_*` 文件。因此界面可以先显示识别结果，而剩余进程继续占满 CPU 和内存。

主窗口关闭后，一次性 OCR 子进程不会被 Windows 自动终止，会继续运行到自然完成。这说明问题同时涉及重复任务、输出竞争、worker 回退和进程生命周期。

## 3. 修复后的强制约束

1. 同一用户、输出批次、引擎和配置最多运行一个 OCR 任务。
2. 重复请求必须等待并复用已有任务，不得启动新进程。
3. 不同配置请求同一输出路径时必须排队。
4. OCR 不得直接写最终 `_recog.json`。
5. 结果必须完整校验后原子提交。
6. 正常情况下一个桌面应用最多保留一个 OCR 模型进程。
7. 关闭应用后不得残留任何 OCR 子进程。
8. 进度必须单调递增，100% 表示全部增强和提交均完成。
9. 满血版必须有推理次数、候选数量和执行时间预算。
10. OCR、`subst` 等子进程不得显示控制台窗口。
11. 常驻模型允许保留内存，但空闲 CPU 必须接近零。

## 4. 第一阶段：前端单飞保护

### 4.1 导入确认防重复

修改 `proofread/static/importer.js`，增加：

```javascript
let impImporting = false;
```

`confirmImport()` 必须在第一个 `await` 前：

1. 检查 `impImporting`，已执行时立即返回；
2. 设置 `impImporting = true`；
3. 禁用确认、取消和重新选择按钮；
4. 显示“正在识别”；
5. 生成本轮唯一 `request_id`；
6. 在 `finally` 中恢复状态。

不能等异步文件夹解析或关闭弹窗后才设置忙碌状态，否则卡顿期间连续点击仍可启动多条导入循环。

### 4.2 文档打开防重复

修改 `proofread/static/notebook.js`，增加：

```javascript
const nbOpenInflight = new Map();
```

- 同一文档已在加载时复用原 Promise；
- 当前文档已经打开时直接返回；
- 加载期间显示忙碌状态并禁止重复点击；
- 成功或失败后清理 Map；
- 连续点击不得重复发送 `/api/load`。

### 4.3 前端取消

使用 `AbortController` 取消调用方不再需要等待的 HTTP 请求。浏览器取消不能直接杀死其他等待者正在共享的 OCR 任务，实际任务取消由后端统一决定。

前端保护仅改善体验，后端单飞才是最终正确性边界。

## 5. 第二阶段：后端 OCR JobManager

建议新增：

```text
proofread/ocr_job_manager.py
```

### 5.1 任务键

任务键包含：

```text
用户 ID
+ 最终 recog_path 的规范化绝对路径
+ OCR engine
+ OCR config hash
```

还要对最终输出路径设置第二层互斥。即使引擎或配置不同，只要输出相同，也不能并发执行。

### 5.2 任务状态机

```text
queued
starting_worker
loading_model
full_page
column_rescue
small_text
low_conf_ensemble
postprocess
committing
done
failed
cancelled
```

任务至少保存：

- `job_id`、`request_id`；
- 用户、批次、输出路径；
- 引擎和配置哈希；
- 创建、开始、结束时间；
- 当前阶段、页数和额外推理次数；
- worker/fallback PID；
- 等待者数量；
- 取消事件；
- Future/Condition；
- 最终结果或异常。

### 5.3 同任务复用

- 没有任务：创建并启动；
- 相同任务运行中：等待同一个 Future；
- 相同输出、不同配置：排队；
- 已有有效缓存：直接返回；
- 已失败：按明确策略重试，不允许无限自动重启。

即使前端重复请求十次，实际 OCR 也只能运行一次。

### 5.4 避免阻塞事件循环

同步 OCR 应通过 `anyio.to_thread.run_sync()` 或 JobManager 的单线程执行器运行。线程用于避免阻塞 FastAPI，不用于并行 OCR；默认 OCR 并发数必须为 1。

## 6. 第三阶段：原子输出与任务级进度

### 6.1 独立任务目录

```text
batch/
  _ocr_jobs/
    <job_id>/
      recog.tmp.json
      progress.json
      img/
```

任务执行期间不得直接写 `batch/_recog.json` 和共享 `_img`。

### 6.2 原子提交

1. 在任务目录完成全部识别；
2. 解析并验证临时 JSON；
3. 检查页数与输入数量；
4. 写入引擎和配置元数据；
5. 刷盘并关闭文件；
6. 用 `os.replace()` 替换最终 `_recog.json`；
7. 提交需要保留的图片；
8. 最后将状态设置为 `done`。

失败或取消时删除临时任务目录，保留上一份有效结果，绝不暴露半成品。

### 6.3 任务级进度

每个任务使用自己的 `progress.json`。现有 `/api/import_progress` 可作为兼容入口，返回当前活动 job 的状态。进度必须单调递增，只有补救推理、后处理和原子提交全部结束后才能达到 100%。

## 7. 第四阶段：常驻 worker 修复

涉及：

```text
proofread/content_api.py
proofread/recognize_ppocrv6_onnx.py
```

### 7.1 禁止静默失败

worker 启动或提交失败必须记录：

- 引擎和配置哈希；
- PID、启动耗时；
- ready 消息；
- stderr、退出码；
- 异常堆栈；
- 是否进入 fallback。

不得继续捕获异常后直接返回 `None`。

### 7.2 stderr 管理

worker 的 stderr 改为 `PIPE`，由后台线程持续读取并写入滚动日志 `logs/ocr-worker.log`。必须持续消费 PIPE，避免缓冲区填满导致 worker 卡死。

### 7.3 有限重启与熔断

1. 启动 worker；
2. 等待 ready，最长 120 秒；
3. 失败后记录完整原因并清理进程；
4. 最多重启一次；
5. 第二次失败后进入受控 fallback；
6. 当前会话不再反复启动 worker。

### 7.4 受控 fallback

- 全局同时最多一个一次性 OCR 进程；
- 必须登记 PID 并支持取消；
- 同一任务只能 fallback 一次；
- 重复请求等待已有任务；
- worker 失败原因必须写日志；
- 不能每张图片都重新尝试 worker 再 fallback。

worker 请求和响应都携带 `job_id`，父进程必须校验响应归属。

## 8. 第五阶段：满血版推理预算

涉及：

```text
proofread/recognize_ppocrv6_onnx.py
proofread/ocr_enhance.py
```

### 8.1 初始预算

```python
InferenceBudget(
    max_extra_predicts=32,
    max_rescue_columns=8,
    max_ensemble_lines=10,
    max_small_text_lines=8,
    soft_time_limit_seconds=120,
)
```

这是第一版保守值，需根据真实高分辨率样本基准测试调整。低阈值第二遍、每个列救援、小字识别和每种低置信度预处理都计入预算。

### 8.2 优先级

1. 基础整页 OCR；
2. 明确未覆盖的主文字列；
3. 最低置信度正文行；
4. 小字补救；
5. 其他可选增强。

### 8.3 候选限制

低置信度候选按正文优先、分数最低优先和有效文本长度排序，排除印章、水印和噪声，默认最多处理 10 条。

列救援默认最多 8 列，按未覆盖比例、面积和正文概率排序。达到时间或推理预算后立即停止可选增强。

### 8.4 取消检查点

在每页开始、整页识别后、每个列救援前后、每条小字/低置信度增强前和提交结果前检查取消事件。

### 8.5 CPU 线程上限

建议初始值：

```text
intra_op_num_threads = min(物理核心数, 8)
inter_op_num_threads = 1
```

必须验证 PaddleOCR/ONNX Runtime 确实接受这些设置，不能加入无效参数。

## 9. 第六阶段：隐藏 Windows 子进程

建议新增：

```text
proofread/windows_process.py
```

所有 OCR 相关子进程统一从这里启动：

```python
creationflags = subprocess.CREATE_NO_WINDOW
startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startupinfo.wShowWindow = subprocess.SW_HIDE
```

适用于常驻 worker、一次性 fallback、`subst` 和 `subst /D`。

盘符映射在一个 worker 生命周期内只创建一次并复用。第一阶段先实现隐藏、复用和可靠释放，长期可评估使用 Windows API 替代 `subst.exe`。

## 10. 第七阶段：关闭应用与进程树清理

### 10.1 关闭顺序

1. 设置全局 `APP_STOPPING`；
2. 后端停止接受 OCR，返回 `503 application_stopping`；
3. JobManager 取消全部任务；
4. worker 停止接受新任务；
5. 等待当前任务短暂退出；
6. 终止剩余子进程；
7. 停止 FastAPI；
8. 退出桌面主进程。

### 10.2 进程登记

所有 OCR `Popen` 必须登记 PID、用途、job_id、启动时间和类型（worker/fallback/helper）。禁止业务代码创建未登记的 OCR 子进程。

### 10.3 分级终止

1. 发送取消并等待 3 秒；
2. `terminate()` 后等待 3 秒；
3. 仍未退出则 `kill()`；
4. 记录退出码和耗时。

### 10.4 Windows Job Object

全部 OCR 子进程加入设置了 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 的 Windows Job Object。即使主程序崩溃或被强制结束，Windows 也会清理所有 OCR 子进程。该机制是防止孤儿进程的最终保障，不能仅依赖 `atexit`。

## 11. 模型驻留策略

健康 worker 完成任务后允许保留内存，但 CPU 应在数秒内降至接近零。建议提供：

```text
自动：空闲 180 秒后释放
性能优先：保留至应用退出
内存优先：完成后 30–60 秒释放
```

真正释放模型通常需要销毁 ONNX Session 或退出 worker，不能仅依赖 `gc.collect()`。

## 12. 日志与诊断

每个任务至少记录：

```text
job_id
request_id
batch
engine
config_hash
deduplicated
worker_pid
fallback_pid
当前阶段和页数
额外推理次数
耗时
取消原因
worker 失败原因
进程退出码
```

关键事件包括：

```text
OCR job started
Duplicate request joined existing job
Worker ready
Worker startup failed
One-shot fallback started
Enhancement budget exhausted
OCR output committed
OCR job cancelled
Child terminated on application shutdown
```

## 13. 自动化测试矩阵

1. 同一批次并发请求 10 次，只执行一次 `run_job()`；
2. 所有重复请求得到同一结果；
3. 不同引擎请求同一输出时串行执行；
4. 第二个请求不能删除第一个任务的文件；
5. 失败任务不覆盖旧 `_recog.json`；
6. 进度只增不减；
7. worker 启动失败最多重试一次；
8. fallback 全局并发数始终为 1；
9. stderr 被持续读取并记录；
10. 关闭应用后全部子进程退出；
11. `terminate()` 无效时执行 `kill()`；
12. Windows 子进程全部使用隐藏窗口标志；
13. 满血版达到预算后停止可选增强；
14. 取消后不再开始下一列或下一页；
15. 常驻 worker 连续处理多个任务时不重复加载模型。

## 14. 冻结安装版验证

必须用 PyInstaller/Setup 安装版本测试：

- 连续点击导入确认 10 次；
- 连续点击同一文档 10 次；
- 导入过程中关闭窗口；
- 人为制造 worker 启动失败；
- 满血版识别 12 张高分辨率图片；
- 轻量版同数据对照；
- 检查任务管理器和完整命令行；
- 检查 CMD 闪窗；
- 关闭应用后等待 10 秒检查残留进程。

## 15. 最终验收标准

1. 同批次并发请求 10 次，实际 OCR 任务数为 1；
2. 正常运行最多一个 OCR worker；
3. 识别完成后 5 秒内，OCR CPU 低于单核约 5%；
4. 不再出现多个 5–6 GB OCR 进程；
5. 关闭应用后 10 秒内，Glowfish Reader 进程数为 0；
6. CMD 闪窗次数为 0；
7. 进度 100% 后不再生成 `_col_*`、`_lc_*` 或 `_small_*`；
8. `_recog.json` 始终为完整可解析 JSON；
9. worker 失败日志能够直接定位原因；
10. 任务失败或取消不能破坏上一份有效结果。

## 16. 推荐实施顺序

### 第一批：正确性热修复

1. 前端重复提交保护；
2. 后端 JobManager；
3. 批次级锁和同任务复用；
4. 临时目录与原子提交；
5. 任务级进度。

### 第二批：生命周期热修复

6. worker 错误日志；
7. 有限重试、熔断和受控 fallback；
8. 子进程 registry；
9. 关闭应用分级清理；
10. Windows Job Object；
11. 隐藏全部控制台子进程。

### 第三批：性能控制

12. 满血版推理预算；
13. 取消检查点；
14. ONNX CPU 线程上限；
15. 模型空闲 TTL；
16. 真实数据性能基准和稳定性测试。

### 第四批：发布验证

17. 完整单元与集成测试；
18. 冻结 EXE 并发和退出测试；
19. Setup 安装版本测试；
20. 资源占用与残留进程复核；
21. 全部门禁通过后重新打包。

不能只凭源码单元测试通过就发布。常驻 worker、控制台窗口、Job Object 和孤儿进程问题必须在冻结安装版本中验证。
