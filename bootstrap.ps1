[CmdletBinding()]
param([string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:GLOWFISH_WORKSPACE_ROOT = $root
$env:GLOWFISH_UI_DIST = Join-Path $root "ui\dist"
$env:GLOWFISH_OCR_ROOT = Join-Path $root "ocr"
$env:GLOWFISH_CONTRACTS_ROOT = Join-Path $root "contracts"

# 默认模型目录（运行时约定：host/glowfish_reader/proofread/models/）
if (-not $env:GLOWFISH_OCR_MODELS) {
  $env:GLOWFISH_OCR_MODELS = Join-Path $root "host\glowfish_reader\proofread\models"
}

if (-not $Python) {
  $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($pythonCommand) {
    & $pythonCommand.Source -3.12 -m venv (Join-Path $root ".venv")
  } else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python 3.12 not found" }
    & $pythonCommand.Source -m venv (Join-Path $root ".venv")
  }
} else {
  if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
  & $Python -m venv (Join-Path $root ".venv")
}
if ($LASTEXITCODE -ne 0) { throw "venv creation failed ($LASTEXITCODE)" }

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed ($LASTEXITCODE)" }
& $venvPython -m pip install -r (Join-Path $root "host\glowfish_reader\proofread\requirements-desktop.txt")
if ($LASTEXITCODE -ne 0) { throw "desktop dependency install failed ($LASTEXITCODE)" }

foreach ($repo in @("contracts", "ocr", "host")) {
  & $venvPython -m pip install --no-deps -e (Join-Path $root $repo)
  if ($LASTEXITCODE -ne 0) { throw "editable install failed: $repo" }
}

$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { throw "npm.cmd not found" }
Push-Location (Join-Path $root "ui")
try {
  & $npm run build
  if ($LASTEXITCODE -ne 0) { throw "UI build failed ($LASTEXITCODE)" }
} finally {
  Pop-Location
}

& $venvPython (Join-Path $root "scripts\validate_workspace.py")
if ($LASTEXITCODE -ne 0) { throw "workspace validation failed ($LASTEXITCODE)" }

# 模型：检测缺失/损坏 → 自动下载（PP-OCRv6 可直下，mlm/punct 需本地构建，见 docs/MODELS.md）
& $venvPython (Join-Path $root "scripts\fetch_models.py")
if ($LASTEXITCODE -ne 0) { throw "model fetch/verify failed ($LASTEXITCODE)" }

$assetArgs = @((Join-Path $root "scripts\verify_release_assets.py"))
& $venvPython @assetArgs
if ($LASTEXITCODE -ne 0) { throw "release asset validation failed ($LASTEXITCODE)" }

Write-Host "Glowfish Reader workspace bootstrap complete: $root"
