#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────────────
# GlowFish 产品官网 · 一键发布到香港机（在本机 Git Bash 运行，非服务器）
#
# 做四件事：
#   1) 把 website/ 静态站上传到 /var/www/glowfish/site/
#   2) 安装/更新主域 nginx 配置 glowfish-site.conf（仅 80，certbot 后补 443）
#   3) nginx -t 校验后 reload
#   4) 打印 certbot 命令（DNS 主域+www 解析到本机后再手动跑一次即出证书）
#
# 用法（在 D:\CC-first\glowfish_reader 下）：
#   bash license_server/deploy/deploy_site.sh
# 可选环境变量覆盖默认：
#   HOST=47.83.12.17  SSH_KEY=~/.ssh/glowfish_license_deploy  SITE_DIR=website
# ───────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST="${HOST:-47.83.12.17}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/glowfish_license_deploy}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"          # glowfish_reader/
SITE_DIR="${SITE_DIR:-$REPO_ROOT/website}"
CONF_SRC="$SCRIPT_DIR/nginx-glowfish-site.conf"
REMOTE_SITE="/var/www/glowfish/site"
REMOTE_CONF="/etc/nginx/conf.d/glowfish-site.conf"
SSH="ssh -i $SSH_KEY -o ConnectTimeout=15 root@$HOST"
say(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

[ -f "$SITE_DIR/index.html" ] || { echo "🛑 找不到站点入口 $SITE_DIR/index.html"; exit 1; }
[ -f "$CONF_SRC" ] || { echo "🛑 找不到 nginx 配置 $CONF_SRC"; exit 1; }

say "1/4 上传站点 -> $REMOTE_SITE"
$SSH "mkdir -p $REMOTE_SITE"
# 逐项覆盖上传（scp -r 幂等覆盖；不删远端多余文件，避免误删）。
scp -i "$SSH_KEY" -r "$SITE_DIR/index.html" "$SITE_DIR/assets" "root@$HOST:$REMOTE_SITE/"

say "2/4 安装 nginx 主域配置 -> $REMOTE_CONF"
# 若已被 certbot 改写为含 443 的版本，则跳过覆盖（避免打回 80-only 丢证书引用）。
if $SSH "grep -q 'managed by Certbot' $REMOTE_CONF 2>/dev/null"; then
  echo "   远端配置已含 certbot 段，保留不覆盖（如需重置请先手动删除 $REMOTE_CONF）。"
else
  scp -i "$SSH_KEY" "$CONF_SRC" "root@$HOST:$REMOTE_CONF"
fi

say "3/4 校验并 reload nginx"
$SSH "nginx -t && systemctl reload nginx && echo reloaded"

say "4/4 DNS 就绪后签发证书（本步需手动，DNS 未生效会失败）"
cat <<EOF
  # 先确认解析已生效：
  #   dig +short glowfishreader.com A        应回 $HOST
  #   dig +short www.glowfishreader.com A    应回 $HOST
  # 再在服务器上跑：
  $SSH "certbot --nginx -d glowfishreader.com -d www.glowfishreader.com --non-interactive --agree-tos -m <你的邮箱> --redirect"
EOF
echo
echo "✅ 站点已发布（HTTP）。验证：curl -H 'Host: glowfishreader.com' http://$HOST/ | head"
