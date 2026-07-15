[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Task,
  [ValidateSet("host", "ui", "ocr", "account", "contracts")][string]$Component = "host",
  [int]$Port = 8765
)
$ErrorActionPreference = "Stop"
if ($Task -notmatch '^[a-z0-9][a-z0-9-]{1,40}$') { throw "Task must be a safe lowercase slug" }
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$parent = Split-Path $repo -Parent
$target = Join-Path $parent ("gf-{0}-{1}" -f $Component, $Task)
if (Test-Path $target) { throw "Worktree already exists: $target" }
$branch = if ($Component -eq "host") { "integration/$Task" } else { "feature/$Component-$Task" }
git -C $repo worktree add $target -b $branch main
if ($LASTEXITCODE -ne 0) { throw "git worktree add failed" }
$runtime = Join-Path $target ".runtime\$Task"
@("data", "db", "logs", "cache", "ocr", "build", "dist", "pytest") | ForEach-Object {
  New-Item -ItemType Directory -Force (Join-Path $runtime $_) | Out-Null
}
@"
GLOWFISH_TASK=$Task
GLOWFISH_PORT=$Port
SHUPAI_DATA_DIR=$runtime\data
GLOWFISH_DB_DIR=$runtime\db
GLOWFISH_LOG_DIR=$runtime\logs
GLOWFISH_OCR_CACHE=$runtime\ocr
PYTEST_ADDOPTS=--basetemp=$runtime\pytest
"@ | Set-Content -LiteralPath (Join-Path $target ".runtime.env") -Encoding UTF8
Write-Host "Created $target on $branch with isolated runtime at $runtime"
