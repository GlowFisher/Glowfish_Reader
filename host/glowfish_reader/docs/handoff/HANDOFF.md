# GlowFish Reader 交接文档（v1.0.0 对外首发）

更新日期：2026-07-09。本文件是当前唯一的交接入口，取代旧 `HANDOFF.md`（v1.0.4 版）、
`FABLE_HANDOFF.md`、`项目交接文档.md`（后两者已删除，历史可从 git 找回）。
启动步骤见同目录 `STARTUP.md`；发版历史见 `docs/release/`。

**铁律：先读当前代码，再信任何文档（包括本文件）。** 引擎行为以
`proofread/engines.py`、`proofread/appconfig.py` 为第一事实源。

## 一、产品定位与当前事实

竖排繁体近代史料本地识读桌面 App（Windows）：本地 OCR → 简体辑录 → 校对 → 导出 docx。
**素材永不上传**；只有账号/更新走远程。

- **版本**：`proofread/_version.py` = `1.0.0`（**对外首发号**。内部迭代史 1.0.2→1.0.5
  见 `docs/release/`，对外从 1.0.0 起算；线上 update.json 与官网直链同步此号）。
- **默认 OCR 引擎**：`ppocrv6_onnx_high`（满血档，纯 onnxruntime 随包分发）。
  轻量档 `ppocrv6_onnx`（别名 `onnx`），回退链 high→onnx。
  `ppocrv6`/`paddle`（PaddlePaddle 路径）仅作 dev 诊断对照，UI 不暴露、打包环境不可用。
- **登录**：手机号 + 短信验证码（+密码），云账号在香港机。
  **激活码/授权码机制已于 2026-07-07 废弃**——`proofread/licensing/` 不是激活码残留，
  它已改用途承载账号凭据的 Ed25519 签名校验（`verify_cred`/`envelope`/`store`/`fingerprint`），
  被 `license_api.py`、`auth_api.py`、`updater.py` 大量调用，**不可删除**。
- **分支状态**：`ocr`（ONNX 满血档 + det 尺度自适应）、`user`（账号登录 + 管理后台）、
  `ui`（界面修复 + 公告）三线已于 2026-07-09 全部合入 `main` 并发版。
- **官网**：`website/` 在仓库内（`index.html` + assets），下载直链
  `https://license.glowfishreader.com/dl/glowfish_reader_setup_<ver>.exe`。

## 二、OCR 核心（满血档）——为什么长这样

设计权威文档：`docs/OCR_满血版设计.md`（与代码逐条对齐）。要点：

- **竖排整列漏检已修**：根因是 PaddleX pipeline yaml 把检测缩放写死
  `limit_side_len=64/min`，大图从不缩放、字符远超训练尺度、DB 置信度塌陷丢整列。
  修法在 `proofread/det_scale.py`：按列距自适应算检测尺度（目标列距约 58px），
  `box_thresh` 用模型自带 0.45。**尺度是刀锋解，别微调 target_pitch**；
  列裁剪图必须施加同一 scale。
- 三层可关的后处理：`ocr_enhance.py`（第二尺度候选/小字增强）、
  `ocr_confusion.py`（形近字纠错，「原字已成词就跳过」护栏）、
  `ocr_correct.py`（GuwenBERT MLM 语义纠错，int8 必须 per-channel 量化）。
- 其余新模块：`interlinear.py`（夹注读序）、`name_segment.py`（人名切分建议）、
  `capabilities.py`（打包资产自检）、`subprocess_env.py`（子进程环境隔离）、
  `domain_fixes.py`/`t2s_fixes.py`（域词/繁简修复）。

### 环境开关（会改字的层默认开、皆可关）

`SHUPAI_OCR_DEVICE`（cpu/gpu，dev paddle 路径）、`SHUPAI_COL_DETECT_V2`、
`SHUPAI_COL_AGG_YGUARD`、`SHUPAI_INTERLINEAR`、`SHUPAI_DOMAIN_FIXES`、
`SHUPAI_OCR_CORRECT`、`SHUPAI_NAME_SEGMENT`、`GF_HIGH_*`（满血档细项）、
`GF_OCR_CONFUSION`；账号侧 `GF_SMS_LOCAL`（本机短信兜底）、`GF_SMS_DEV`（回显验证码）。

## 三、账号体系（手机号 + 短信）

- 客户端：`proofread/auth_api.py`（`/api/sms/send`、`/api/register`、`/api/login`、
  `/api/reset`、`/api/me`、`/api/logout`；兜底页 `static/login.html` 走
  `/api/register/phone`、`/api/login/password`）。主登录 UI 是弹窗
  `static/login-modal.js`（朱丝栏配色已定案，改 CSS 必须同步 `index.html` 的 `?v=` 缓存串）。
- 错误文案单一事实源：`proofread/account_errors.py`。
  **`licensing/client._post` 必须要求响应带 `ok` 字段，否则一律降级 `unavailable`，
  未知绝不猜成具体业务失败**（2026-07-08 事故教训）。
- 服务端：`license_server/`（`core.py` 账号/短信/试用 + `serverapp.py` 端点 +
  `sms.py` 阿里云通道 + `keygen.py` 生成签名密钥 + 管理后台）。
  部署在香港机 `47.83.12.17`（`/opt/shupai/license_server`），SSH 密钥
  `~/.ssh/glowfish_license_deploy`，`manage_remote.ps1` 远程运维。
- ⚠ 线上真库是 `/var/lib/glowfish/account.db`；`/var/lib/shupai/license.db`
  是退役空库。备份必须指向真库（`deploy/backup_db.sh` 默认已正确）。
- ⚠ `deploy/*.sh` 必须 LF 行尾（`.gitattributes` 已强制；CRLF 会让脚本首行即死）。

## 四、不可破坏的契约（Do Not Break）

1. **OCR JSON 契约**：`{page_id: {image, width, height, lines: [{text, box, score}]}}`；
   `noise_lines` 分层与 RTL（右→左）列序语义不可变。
2. **EXIF 方向与 box 对齐**：图像坐标系一旦错位，前端框选全废。
3. **三层文本分离**：`text_ocr`（原始）/`text_draft`（机器修）/`text`（人工定稿）
   各自语义不可混用。
4. **本地不上云**：任何功能不得把用户素材传出本机。
5. 密钥、模型缓存、用户数据不进 git（清单见 §七）。
6. 打包必须过能力自检闸门（`--selftest-capabilities` 任一 False 即失败）——
   防「exe 静默缺资产降级」（2026-07-02 复发过）。

## 五、本地运行与验证

```powershell
cd D:\CC-first\glowfish-reader\glowfish-reader-main\glowfish_reader
.\.venv\Scripts\python.exe proofread\desktop_app.py --serve 8799 127.0.0.1
# 健康检查
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8799/health
.\.venv\Scripts\python.exe proofread\desktop_app.py --selftest
# 全量测试
.\.venv\Scripts\python.exe -m pytest proofread license_server\tests -q
```

分域 focused 测试（动哪块跑哪块）：

```powershell
# OCR 核心
.\.venv\Scripts\python.exe -m pytest proofread\test_det_scale.py proofread\test_ppocrv6_engine.py proofread\test_ocr_quality.py proofread\test_ocr_enhance.py -q
# 导出
.\.venv\Scripts\python.exe -m pytest proofread\test_export_inline_annotations.py proofread\test_export_selected_pages.py -q
# 账号/登录
.\.venv\Scripts\python.exe -m pytest proofread\test_account_api.py proofread\test_phone_auth.py proofread\licensing\tests license_server\tests -q
# 前端语法
node --check proofread\static\app.js; node --check proofread\static\viewer.js
```

Bench（评测台）：

```powershell
.\.venv\Scripts\python.exe bench\run_bench.py --only 手写
# gold 标注与测试图（bench\_hw_images、bench\gold_handwritten、bench\fixtures）不可再生，勿删
# bench\out\_img、_viz 是可再生调试产物，可随时清
# ⚠ bench\gold_printed 目前只有占位说明，印刷体评测集尚未建立
```

## 六、发版流程

1. 只改 `proofread/_version.py`（单一真源；纯数字三段，更新检查按数字比较）。
2. 重建 dist：`..\.venv\Scripts\python.exe -m PyInstaller glowfish_reader.spec --noconfirm`
   （在 `proofread/` 下；⚠ venv 移动过之后 `Scripts\*.exe` 启动器内嵌旧路径会静默失败，
   一律用 `python.exe -m` 方式调用）。
3. `.\release.ps1 -Notes "..."`：先跑能力自检闸门 → ISCC 打安装包 →
   算 sha256 → 生成 `Output/update.json`。
4. 上传：**先传安装包、最后传 update.json**（顺序颠倒会让在网客户端拉到 404/半截包）：
   `release.ps1 -Upload -SshKey $env:USERPROFILE\.ssh\glowfish_license_deploy`。
5. App 更新通道：客户端 `updater.py` 读
   `https://license.glowfishreader.com/update.json`，数字比较 `latest` 与本机版本。

## 七、不提交清单

`.venv/`、`.paddle_venv/`、`.uv-cache/`；`proofread/_work/`、`proofread/models/`
（junction 指向实体，随包分发但不进 git）；`proofread/build|dist|Output/`；
`server-*.log`、`tmp/`；`license_server/_keys/`、`*.db`；`bench/out/_img/*_col_*.jpg` 等再生产物。

## 八、工作区拓扑（2026-07-09 重组后）

```
D:\CC-first\glowfish-reader\
    glowfish-reader-main    [main]   ← 实体：.venv + proofread/models(1.2G)
    glowfish-reader-ocr     [ocr]    ← .venv/models 为 junction 指向 main
    glowfish-reader-ui      [ui]
    glowfish-reader-user    [user]
```

GitHub 远端 `001Vincent/glowfish_reader`，主线分支 `main`（`master` 留作历史）。
多会话并发时动手前先 `git status` + `git worktree list`。

## 九、历史存档（只作背景，勿当现行指引）

- `docs/archive/vl_gguf_legacy/`：已废弃的 VL/GGUF 引擎路线（勿复活）。
- `docs/release/RELEASE_NOTES_v1.0.3/4.md`：内部迭代史。
- `docs/plans/OCR_ACCURACY_ITERATION_PLAN.md`：精度四迭代计划（多数已落地）。
- 激活码机制的一切（issue/seats/激活页）：已随 2026-07-07 退役删净。
