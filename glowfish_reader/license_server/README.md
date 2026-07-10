# license_server —— 账号服务器（登录鉴权 + 后台管理）

Glowfish_Reader 史料阅读器的**用户登录鉴权 + 后台管理**服务端。
支持用户名密码登录、手机号 + 6 位短信验证码登录、7 天免费试用、后台管理。
授权码(激活码)机制已于 2026-07-07 退役，目录名沿用 `license_server` 仅为兼容既有部署路径
（`/opt/shupai/license_server`），实际业务是账号系统，不再签发/校验授权码。

## 目录结构

```
license_server/
├── serverapp.py   路由薄层 + 后台 /admin（/account/sms/send、/account/login/phone 等）
├── core.py        SQLite 业务（accounts+phone 列、sms_codes 表、验证码存取与防刷）
├── sms.py         短信网关抽象（console 开发 / aliyun 生产，纯 stdlib RPC 签名）
├── sign.py 等      Ed25519 签名信封 / 密钥生成
├── deploy/        香港机部署脚本、systemd、nginx、env 样例
├── docs/
│   ├── 阿里云短信开通与部署操作手册.md    从零开通短信到上线香港机的完整步骤
│   ├── 客户端接入契约.md                 reader 端接手机号登录的 API 契约
│   └── 域名子域名与服务器接入实施指南.md
└── tests/         自测（test_phone_login.py 覆盖手机号登录 + 防刷）
```

## 主要能力

- 用户名密码 / 手机号 + 短信验证码登录；新账号自动开 7 天免费试用。
- 短信网关抽象：`console`（验证码打日志，本地联调）/ `aliyun`（阿里云 Dysmsapi）。
- 防刷：同号冷却 60s / 单日 5 条 / 验证码 5 分钟过期 / 连错 5 次锁定 / 单次有效 / 哈希存储。
- 后台管理：用户列表、手机号搜索、续期/封禁/重置密码、公告管理。

## 快速自测（无需短信、无需上线）

```bash
cd glowfish_reader/license_server      # 需含 fastapi + pynacl 的 python 环境
python -m pytest tests -q
```

## 安全说明

- **私钥（`_keys/`）与本地账号库（`*.db`）绝不入库**，已从仓库剔除，
  运行时由 `keygen.py` 生成 / systemd 挂载；`.gitignore` 已固化该保护。
- 短信 AccessKey、服务器私钥等机密只写在香港机 `/etc/shupai/license.env`（chmod 600），
  不进仓库。仓库内 `deploy/license.env.example` 只是占位样例。
