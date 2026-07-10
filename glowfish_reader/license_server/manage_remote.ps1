#Requires -Version 5.1
<#
  GlowFish 账号服务器 · 本机一键运维（SSH 到香港机）

  线上现状（2026-07-09 核实）：
    服务   glowfish-account.service（uvicorn serverapp:app，127.0.0.1:8800，nginx 反代
           https://license.glowfishreader.com）
    代码   /opt/glowfish/account-server/
    数据库 /var/lib/glowfish/account.db（⚠同目录 license.db 是空的旧库，别看错）
    环境   /etc/glowfish/account.env

  用法:
    .\manage_remote.ps1 backup   # 生产库热备份
    .\manage_remote.ps1 deploy   # 增量部署 core.py + serverapp.py（备份→推送→语法检→重启→冒烟）

  ⚠deploy 故意只推 core.py/serverapp.py：线上 sms.py（阿里云短信认证服务 dypnsapi）
   与 sign.py 曾比仓库新，整目录覆盖会打断验证码短信。若要动这两个文件，先人工 diff。
#>
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('backup', 'deploy')]
    [string]$Action,
    [string]$Server = 'root@47.83.12.17',
    [string]$Key = "$env:USERPROFILE\.ssh\glowfish_license_deploy"
)
$ErrorActionPreference = 'Stop'

$DIR = '/opt/glowfish/account-server'
$LOCAL = Split-Path -Parent $MyInvocation.MyCommand.Path   # 本仓库 license_server/

function Invoke-Remote([string]$RemoteCmd) {
    if (-not (Test-Path $Key)) { throw "找不到 SSH 私钥: $Key" }
    & ssh -i $Key -o BatchMode=yes -o ConnectTimeout=15 $Server $RemoteCmd
    if ($LASTEXITCODE -ne 0) { throw "远程命令失败 (exit $LASTEXITCODE)" }
}

switch ($Action) {
    'backup' {
        Write-Host '触发生产库热备份' -ForegroundColor Cyan
        Invoke-Remote "LICENSE_DB=/var/lib/glowfish/account.db BACKUP_DIR=/var/backups/glowfish bash $DIR/deploy/backup_db.sh"
    }
    'deploy' {
        $ts = Get-Date -Format 'yyyyMMddHHmmss'
        Write-Host "1/4 备份线上 core.py/serverapp.py (bak-$ts)" -ForegroundColor Cyan
        Invoke-Remote "cd $DIR && cp core.py core.py.bak-$ts && cp serverapp.py serverapp.py.bak-$ts"

        Write-Host '2/4 推送 core.py + serverapp.py' -ForegroundColor Cyan
        & scp -q -i $Key -o BatchMode=yes "$LOCAL\core.py" "$LOCAL\serverapp.py" "${Server}:$DIR/"
        if ($LASTEXITCODE -ne 0) { throw "scp 失败 (exit $LASTEXITCODE)" }

        Write-Host '3/4 语法预检 + 重启服务' -ForegroundColor Cyan
        Invoke-Remote "cd $DIR && python3 -m py_compile core.py serverapp.py && systemctl restart glowfish-account && sleep 2 && systemctl is-active glowfish-account"

        Write-Host '4/4 冒烟: /health + /account/check + /admin' -ForegroundColor Cyan
        Invoke-Remote "curl -sf http://127.0.0.1:8800/health && curl -sf -X POST http://127.0.0.1:8800/account/check -H 'Content-Type: application/json' -d '{\""session_id\"":\""bogus\""}' && curl -sf -o /dev/null -w 'admin:%{http_code}\n' http://127.0.0.1:8800/admin"
        Write-Host "部署完成。回滚: ssh 后 cd $DIR && cp core.py.bak-$ts core.py && cp serverapp.py.bak-$ts serverapp.py && systemctl restart glowfish-account" -ForegroundColor Green
    }
}
