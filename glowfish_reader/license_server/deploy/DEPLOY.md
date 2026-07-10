# 授权服务器部署套件

> ⚠**已过期**：本文档写于「授权码(激活码)」还是唯一登录方式的年代。该机制已于 2026-07-07 退役，
> 改用手机号+短信验证码账号登录；`shupai-license.service`/`nginx-shupai-license.conf`/
> `issue.py`/`revoke.py`/`seats.py` 已随之删除。`serverapp.py` 本身仍在跑（现在服务
> `/account/*` 账号接口），但下面第 2/3/4/6 步与验收命令引用的文件、环境变量、端点均已不存在，
> 照抄会直接失败。留存仅供追溯部署套路（systemd+nginx+certbot 的骨架仍可参考），
> 重新部署前须先补一份不含授权码逻辑的 systemd unit + nginx conf。

**已定路线（2026-06-22）：香港轻量服务器（2 核 2G，Ubuntu 22.04）+ 域名，免 ICP 备案、最快上线。**
本目录给出可直接套用的模板；选型理由见计划文件
`C:\Users\18267\.claude\plans\sorted-napping-torvalds.md`。

> 前置：开通**香港**轻量服务器（阿里云/腾讯云香港地域，或 Vultr/搬瓦工等），域名解析到该机即可——
> **香港机无需 ICP 备案**，443 直接可用，certbot 正常签证。买好服务器、域名解析生效后即可执行下面步骤。
> 客户端 `keys.py:DEFAULT_SERVER` 已设 `https://license.glowfishreader.com`；如换域名同步改它（或打包注入 `SHUPAI_LICENSE_SERVER`）。

## 文件
- `shupai-license.service` — systemd 常驻单元（uvicorn 只绑 127.0.0.1:8800，不直接对外）
- `license.env.example` — 环境变量/密钥模板（复制为 `/etc/shupai/license.env`，chmod 600）
- `nginx-shupai-license.conf` — Nginx 反代 + 限流（certbot 自动补 TLS）
- `backup_db.sh` — SQLite 账本每日热备份 + 保留轮转

## 步骤

**0. 系统加固**
```bash
adduser shupai && usermod -aG sudo shupai          # 非 root 运维用户
# SSH 改密钥登录、禁 root 密码登录：编辑 /etc/ssh/sshd_config
#   PermitRootLogin no / PasswordAuthentication no  → systemctl restart ssh
apt update && apt install -y python3-venv nginx certbot python3-certbot-nginx \
    sqlite3 fail2ban unattended-upgrades ufw
ufw allow 22/tcp && ufw allow 80,443/tcp && ufw enable
```
> 云控制台**安全组**再收一遍：仅放行 443（全网）、22（限你自己出口 IP）。

**1. 放代码 + venv**
```bash
mkdir -p /opt/shupai && cd /opt/shupai
# 上传 license_server/ 到 /opt/shupai/license_server（serverapp/core/sign/issue/revoke/seats/keygen）
python3 -m venv venv
./venv/bin/pip install fastapi "uvicorn[standard]" pynacl
mkdir -p /var/lib/shupai && chown shupai:shupai /var/lib/shupai
```

**2. 密钥（在你本机生成，私钥分置）**
```bash
# 本机：python keygen.py → 生成 _keys/{license_private,server_private}.b64 + public_keys.txt
#  · server_private.b64  → 填服务器 /etc/shupai/license.env 的 SERVER_PRIV
#  · license_private.b64 → 只留本机（issue.py 签授权码用），绝不上服务器
#  · 两个公钥           → 回填客户端 proofread/licensing/keys.py 的 LICENSE_PUB / SERVER_PUB
```
服务器上：
```bash
mkdir -p /etc/shupai
cp /opt/shupai/license_server/deploy/license.env.example /etc/shupai/license.env
# 编辑填入 SERVER_PRIV / LICENSE_PUB
chown shupai:shupai /etc/shupai/license.env && chmod 600 /etc/shupai/license.env
```

**3. 起服务**
```bash
cp /opt/shupai/license_server/deploy/shupai-license.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now shupai-license
curl -s http://127.0.0.1:8800/health      # → {"ok":true}
```

**4. Nginx + TLS**
```bash
cp /opt/shupai/license_server/deploy/nginx-shupai-license.conf /etc/nginx/conf.d/
sed -i 's/license.YOURDOMAIN.com/license.你的域名/' /etc/nginx/conf.d/nginx-shupai-license.conf
nginx -t && systemctl reload nginx
certbot --nginx -d license.你的域名        # 自动签证书 + 80→443 跳转 + 自动续期
```

**5. 备份**
```bash
chmod +x /opt/shupai/license_server/deploy/backup_db.sh
( crontab -l 2>/dev/null; echo "5 3 * * * /opt/shupai/license_server/deploy/backup_db.sh" ) | crontab -
```
> 强烈建议在 `backup_db.sh` 末尾打开异地同步（OSS/COS/rclone）。

**6. 接回客户端**
- 改 `proofread/licensing/keys.py:DEFAULT_SERVER = "https://license.你的域名"`（或打包注入 `SHUPAI_LICENSE_SERVER`）。
- 重新打包消费版（确认 `proofread/sku.txt` = `single`）。

## 验收（对应计划第四节）
```bash
curl https://license.你的域名/health                                   # {"ok":true}
curl -X POST https://license.你的域名/trial -H 'Content-Type: application/json' -d '{"fingerprint":"test"}'   # 带 cred
```
真机：`issue.py --license-id GF-001 --days 365` 出码 → 激活页激活 → 第二台同码 → `seat_full`；
旧机「停用本机」→ 新机可激活；`revoke.py --license-id GF-001` → 目标机宽限末被拦。
