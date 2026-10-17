# GlowFish Reader 一体化弹窗登录子系统 — 设计与交付规则

- 日期：2026-07-07
- 分支：`shupai-licensing`
- 范围：`glowfish_reader/glowfish_reader/proofread/`（桌面阅读器前端 + 本机 FastAPI 鉴权）
- 目标：把现有「用户名+密码、独立 login.html 页」的登录，替换为**单一模态弹窗**内的三视图（登录 / 注册 / 找回密码）手机号账号体系，先做前端，再连本机服务器后端。

---

## 1. 背景与现状

现有鉴权链路（不改动其业务内核）：

- `proofread/auth.py`：纯标准库 SQLite 用户内核。`users(id,username,display,pw_hash,pw_salt,created_at)` + `sessions` 表；pbkdf2-sha256；会话以 httponly cookie `sid` 下发，TTL 30 天。
- `proofread/auth_api.py`：`POST /api/register`、`POST /api/login`、`POST /api/logout`、`GET /api/me`。当前登录凭 `username+password`。
- `proofread/static/login.html`：独立登录页（用户名/密码 + 注册 Tab）。**本方案废弃此独立页流程**，改为弹窗。
- `proofread/static/auth-guard.js`：包裹 `window.fetch`，任意 401 或 `/api/me` 失败即 `location.href="/login.html"`。
- `single` 模式（`appconfig.is_single()`）跳过登录闸；本方案保持该豁免不变。

工作树内**不存在**任何手机号/SMS 后端（记忆中 07-06 服务端 SMS 属 license_server 且未落此仓，阿里云短信尚未开通）。因此后端需在本机 proofread 侧新建，SMS 采用 **dev/console 发送器**（验证码打印到服务端日志、开发期可由接口回显），阿里云开通后替换发送器实现即可。

---

## 2. 集成架构（改动边界）

**新增自包含前端文件（弹窗模块本体）：**

| 文件 | 职责 |
|---|---|
| `proofread/static/login-modal.css` | 弹窗样式，复用现有 CSS 变量与深浅双主题 |
| `proofread/static/login-modal.js` | 弹窗全部逻辑：视图层 + 校验层 + 接口层；暴露 `window.GlowfishLoginModal.open()/.close()` |

**接线改动（surgical，仅 2 处）：**

1. `proofread/static/index.html`：`<head>` 引入 `login-modal.css`；`</body>` 前引入 `login-modal.js`（在 `auth-guard.js` 之前）；新增挂载点 `<div id="gf-login-modal-root"></div>`。
2. `proofread/static/auth-guard.js`：将两处 `location.href = LOGIN`（第 13、80 行附近）改为 `GlowfishLoginModal.open()`；登出后同样弹窗而非跳页。`single` 豁免逻辑保留。

**主应用（index 业务脚本、OCR、本地存储、史料阅读核心）零改动。** `login.html` 独立页文件保留在仓库中作直链兜底，但不再是主路径。

---

## 3. 前端弹窗设计

### 3.1 单容器三视图

模态浮层 = 半透明遮罩（`backdrop-filter: blur`）+ 居中卡片。卡片内一个 `.gf-view-stack`，三视图分别为 `.gf-view[data-view=login|register|forgot]`，同一时刻仅一个可见，切换用淡入 + 高度过渡。

- **登录（默认）**：手机号、密码、登录按钮；底部两入口【前往注册】【忘记密码】。
- **注册**：手机号、短信验证码（+「获取验证码」按钮）、设置密码、确认密码；底部【返回登录】。成功→切回登录。
- **找回密码**：绑定手机号、短信验证码（+「获取验证码」）、新密码、确认新密码；底部【返回登录】。成功→切回登录。

**三处切换逻辑入口**（代码中以 `switchView(name)` 统一实现，注释显式标注）：
- ①登录 → 注册 / 找回（登录视图底部两链接）
- ②注册 → 登录（注册视图【返回登录】及注册成功回调）
- ③找回 → 登录（找回视图【返回登录】及重置成功回调）

**状态隔离**：`switchView` 每次切换先 `resetView()` 清空目标视图所有 `<input>` 值、清错误提示、复位验证码倒计时。保证「切换页面清空上一页面内容」。

### 3.2 三层解耦

```
login-modal.js
├── View 层    buildModal() / switchView() / renderMessage()   — 只管 DOM 与切换
├── Validate 层 Validators.{phone,password,match,required}       — 纯函数，返回 {ok,msg}
└── Api 层     Api.{login,sendSms,register,resetPassword}        — 唯一 fetch 出口，集中调用点位
```

Api 层每个函数顶部注释标注 endpoint、method、入参、返回契约，作为「后端对接点位」。

### 3.3 视觉规范（沿用现有，不引入新风格）

复用 `login.html`/`activate.html` 的设计令牌：`--ink:#2a2f37`、`--accent:#365a67`、`--accent-d:#284851`、`--line:#d3dae2`、`--field:#eef1f5`、圆角卡片 14px / 控件 6px、微软雅黑、主按钮铁青实心字距、`.msg.err/.ok` 提示色、`fadeIn` 动画、`body.gf-dark` 暖深褐深色主题（读 `localStorage gf-theme`）。弹窗遮罩为新增元素但配色取自同一变量表。`/frontend-design` 与 `/impeccable` 用于打磨层级、间距、动效细节，不改配色体系。

### 3.4 硬约束落实

- 仅模态浮层，不开独立系统窗口；未登录时 Esc / 点遮罩**不关闭**（必须完成登录）。
- 所有输入框前端基础校验：空值拦截、`^1[3-9]\d{9}$` 11 位手机号正则、密码一致性。
- 提交中禁用按钮防重复提交；网络/后端错误在 `.msg` 区展示后端 `detail`。

---

## 4. 表单校验规则清单（校验层，供对接后端）

| 字段/规则 | 规则 | 触发时机 |
|---|---|---|
| 手机号 | `^1[3-9]\d{9}$`（11 位） | 提交前 + 获取验证码前 |
| 非空 | 各视图所有字段 trim 后非空 | 提交前 |
| 密码长度 | ≥6 位 | 注册/找回提交前 |
| 密码字符集 | 允许数字、大小写字母（`^[A-Za-z0-9]{6,}$`；不强制混合） | 注册/找回提交前 |
| 两次密码一致 | 严格相等 | 注册/找回提交前 |
| 获取验证码前置 | 手机号格式通过才可点；点击后 60s 倒计时禁用重复获取 | 点击「获取验证码」 |

> 后端须对同规则做二次校验（前端校验仅为体验，不可信）。

---

## 5. 后端设计（Phase 2，本机 proofread 侧）

### 5.1 数据模型扩展（`auth.py`）

- `users` 表加列 `phone TEXT UNIQUE`（启动时 `ALTER TABLE ... ADD COLUMN` 幂等迁移；旧库无 phone 的行保持可登录）。
- 新增表：
  ```sql
  CREATE TABLE IF NOT EXISTS sms_codes(
    phone TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    scene TEXT NOT NULL,          -- register | reset
    expires_at INTEGER NOT NULL,
    sent_at INTEGER NOT NULL      -- 用于 60s 重发节流
  );
  ```
- 验证码：6 位数字，pbkdf2 存 hash（不存明文），有效期 5 分钟，60s 内不可重发。验证成功后删除该行。

### 5.2 内核函数（`auth.py`）

- `issue_sms_code(phone, scene) -> code`：节流校验 + 生成 + 落 hash + 调用发送器。
- `verify_sms_code(phone, scene, code) -> bool`：校验有效期/hash/scene；成功即删。
- `create_user_by_phone(phone, password) -> user`：手机号唯一，pbkdf2，username 缺省用 phone。
- `verify_user_by_phone(phone, password) -> user|None`：登录。
- `reset_password_by_phone(phone, password)`：改密。
- 手机号格式与密码规则（`^[A-Za-z0-9]{6,}$`）后端二次校验。

### 5.3 SMS 发送器（新文件 `proofread/sms.py`）

可插拔：`send(phone, code, scene)`。默认 `console` 后端——写入服务端日志（`[SMS] {phone} code={code}`）。预留 `aliyun` 后端占位（读环境变量 AK/签名/模板），开通后切换。**dev 模式下 `issue_sms_code` 可在响应中回显 `code`（受 `GF_SMS_DEV=1` 控制）**，便于自动化验收；生产关闭。

### 5.4 API 端点（`auth_api.py`，前端 Api 层真接目标）

| 端点 | 入参 | 返回 |
|---|---|---|
| `POST /api/sms/send` | `{phone, scene:"register"\|"reset"}` | `{ok:true[, dev_code]}`；节流 429 |
| `POST /api/register` | `{phone, code, password}` | `{ok:true, user}` + set-cookie（注册即登录） |
| `POST /api/login` | `{phone, password}` | `{ok:true, user}` + set-cookie |
| `POST /api/password/reset` | `{phone, code, password}` | `{ok:true}` |

- `/api/login` 改为**手机号鉴权**（原 username 登录保留为内部兼容，不在弹窗暴露）。
- `/api/register` 改为手机号+验证码流程。
- 错误统一 `HTTPException(4xx, detail)`，前端展示 `detail`。
- `/api/me`、`/api/logout`、cookie 会话机制不变。

---

## 6. 交付规则（Acceptance Criteria）

一个改动被视为「达标交付」，须**全部**满足：

**A. 结构与边界**
1. 仅新增 `login-modal.css`、`login-modal.js`、`sms.py`；仅改 `index.html`、`auth-guard.js`、`auth.py`、`auth_api.py`。未触碰 OCR / 本地存储 / 史料阅读核心脚本。
2. 前端三层（视图/校验/接口）在 `login-modal.js` 内文件级分区清晰，接口层为唯一 fetch 出口。
3. `login-modal.js` 不超 400 行、嵌套不超 4 层（超则拆）；含中文注释。

**B. 弹窗与视图**
4. 未登录进入主界面即弹出模态，遮罩盖住阅读器，卡片居中；Esc/点遮罩不关闭。
5. 默认显示「手机密码登录」视图。
6. 三视图可平滑互相切换，三处切换入口均生效。
7. 切换任一视图后，上一视图输入框内容被清空、错误提示复位、验证码倒计时复位。
8. 不新开任何独立系统窗口。

**C. 校验**
9. 空值提交被拦截并给出中文提示。
10. 非 11 位 / 非 `1[3-9]` 开头手机号被拦截。
11. 手机号格式非法时「获取验证码」不可点。
12. 两次密码不一致被拦截。
13. 密码 <6 位被拦截；含数字与大小写字母的 ≥6 位密码通过。
14. 「获取验证码」点击后进入 60s 倒计时且期间不可重复点击。

**D. 后端联通（真接）**
15. 注册：获取验证码→填码→设密→提交，成功后**自动切回登录视图**并提示「注册成功，请登录」（对齐任务§二.4；注册不自动进入主界面）。
16. 登录：已注册手机号+正确密码登录成功；错误密码返回中文错误、不进入。
17. 找回：获取验证码→填码→设新密→提交，成功后回到登录视图，用新密码可登录。
18. 验证码错误/过期、手机号已注册、手机号未注册等分支均返回可读中文提示。
19. 后端对手机号格式、密码规则、验证码做二次校验（绕过前端直接打接口仍被拦）。

**E. 视觉**
20. 配色/圆角/间距/字体与现有 `login.html`/`activate.html` 一致；深色主题（`gf-theme=dark`）正常。
21. 无控制台报错；`/frontend-design`·`/impeccable` 层级与动效达标。

**F. 回归**
22. `single` 模式仍跳过登录闸。
23. `/api/me`、登出、license 激活流程不受影响。

---

## 7. 验收测试方案（独立 subagent 执行）

先跑后端单元自测（新增 `test_phone_auth.py`：注册/登录/找回/验证码节流/二次校验，全绿）。再由**独立 subagent** 扮演用户，用 Chrome DevTools 驱动真实弹窗，按 §6 交付规则逐条模拟点击验证（含异常分支），产出缺陷清单（每条：现象/复现步骤/期望/严重度/涉及文件）。主进程据清单**返修**，返修后复验直至交付规则全绿。

---

## 8. 实施阶段

1. **Phase 1 前端**：`login-modal.css` + `login-modal.js`（Api 层先指向真实端点路径，dev 阶段后端未就绪时可 mock）；接线 `index.html` + `auth-guard.js`。
2. **Phase 2 后端**：`auth.py` 扩展 + `sms.py` + `auth_api.py` 端点；前端 Api 层真接；后端自测。
3. **Phase 3 验收**：独立 subagent 模拟用户测试，产缺陷清单。
4. **Phase 4 返修**：按清单修复并复验至交付规则全绿。
