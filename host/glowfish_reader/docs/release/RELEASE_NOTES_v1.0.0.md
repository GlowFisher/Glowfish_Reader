# Release Notes — v1.0.0（对外首发，2026-07-09）

**版本口径说明**：本版是产品的对外首发号。此前 1.0.2→1.0.5 为内部迭代号
（见同目录 RELEASE_NOTES_v1.0.3/4.md），对外发布从 1.0.0 起算；
`update.json` 与官网下载直链同步此号。功能上本版等价于内部 1.0.5 + 工作树清理。

## 面向用户

- 竖排繁体史料本地识读：OCR、简体辑录、校对、批注、导出 docx 全流程本机完成，素材不上传。
- OCR 满血档（默认）：ONNX 高精引擎 + 列距自适应检测，修复竖排整列漏检；
  另有轻量档可在设置中切换（速度约 1.8×）。
- 语义纠错（GuwenBERT）、古文自动断句、形近字/域词/人名切分词表修复。
- 手机号 + 短信验证码注册登录，新号 14 天免费试用；App 内置自动更新。

## 相对内部 1.0.5 的变更（工作树纯净化）

- 删除激活码时代残留：`licensing/验收清单.md`、`license_server/sign.py`
  的 `verify_license_token()` 死函数。
- 删除不可达代码：`licensing/client.sms_verify`（线上无此端点）及
  `auth_api._verify_code` 的远程分支；`_verify_code` 现仅服务 `GF_SMS_LOCAL=1` 本机模式。
- 删除死路由：`GET /api/stats`、`POST /api/account/check`（前端均不调用；
  账号静默核对走 `/api/me`）。
- 前端：清掉 `ENGINE_LABEL` 里已废弃的 `vl_gguf`/`paddleocr_vl` 键。
- 修正备份配置隐患：`deploy/license.env.example` 与部署说明中 `LICENSE_DB`
  从退役空库 `/var/lib/shupai/license.db` 改指真库 `/var/lib/glowfish/account.db`。
- 文档：重写 `docs/handoff/HANDOFF.md`（对齐手机号登录/满血档/合并后现状）；
  删除过期的 `FABLE_HANDOFF.md`、`项目交接文档.md`、`audit/CODE_REVIEW.md`、
  `audit/findings.md`、`plans/progress.md`、`plans/task_plan.md`。

## 发布物

- 安装包：`glowfish_reader_setup_1.0.0.exe`（约 398 MB，含 ONNX 模型）。
- 通道：官网直链 + `update.json`（sha256 以 update.json 为准）。
