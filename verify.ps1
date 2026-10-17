[CmdletBinding()]
param(
  [string]$Python = "",
  [switch]$Full,
  [switch]$ReleaseArtifacts
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content (Join-Path $root "workspace-manifest.json") -Raw | ConvertFrom-Json

# 单仓库 monorepo：校验组件目录存在即可，不再做子模块 commit 锁定。
foreach ($name in @("host", "ui", "ocr", "contracts")) {
  $repo = Join-Path $root $name
  if (-not (Test-Path -LiteralPath $repo -PathType Container)) {
    throw "Component directory missing: $repo"
  }
}

if (-not $Python) {
  $localPython = Join-Path $root ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
  else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python not found; run bootstrap.ps1" }
    $Python = $pythonCommand.Source
  }
}

$env:GLOWFISH_WORKSPACE_ROOT = $root
$env:GLOWFISH_UI_DIST = Join-Path $root "ui\dist"
$env:GLOWFISH_OCR_ROOT = Join-Path $root "ocr"
$env:GLOWFISH_CONTRACTS_ROOT = Join-Path $root "contracts"

& $Python (Join-Path $root "scripts\validate_workspace.py")
if ($LASTEXITCODE -ne 0) { throw "workspace validation failed ($LASTEXITCODE)" }
$assetArgs = @((Join-Path $root "scripts\verify_release_assets.py"))
if (-not $env:GLOWFISH_OCR_MODELS) { $assetArgs += "--skip-models" }
& $Python @assetArgs
if ($LASTEXITCODE -ne 0) { throw "release asset validation failed ($LASTEXITCODE)" }

$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if ($npm) {
  Push-Location (Join-Path $root "ui")
  try {
    & $npm run check
    if ($LASTEXITCODE -ne 0) { throw "UI check failed ($LASTEXITCODE)" }
    & $npm test
    if ($LASTEXITCODE -ne 0) { throw "UI tests failed ($LASTEXITCODE)" }
  } finally {
    Pop-Location
  }
}

if ($ReleaseArtifacts) {
  $releaseDir = Join-Path $root $manifest.release_artifacts
  $installer = Get-ChildItem -LiteralPath $releaseDir -Filter "*.exe" | Select-Object -First 1
  if (-not $installer) { throw "installer missing: $releaseDir" }
  $update = Get-Content (Join-Path $releaseDir "update.json") -Raw | ConvertFrom-Json
  $sha = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($update.latest -ne $manifest.product_version -or $update.sha256 -ne $sha -or [int64]$update.size -ne $installer.Length) {
    throw "release artifact manifest mismatch"
  }
}

if ($Full) {
  $env:PYTHONPATH = @(
    (Join-Path $root "host"),
    (Join-Path $root "host\src"),
    (Join-Path $root "host\glowfish_reader\proofread"),
    (Join-Path $root "ocr\src"),
    (Join-Path $root "contracts\src")
  ) -join ";"
  $testTemp = Join-Path $root ".pytest-verify"
  if (Test-Path -LiteralPath $testTemp) { Remove-Item -LiteralPath $testTemp -Recurse -Force }
  New-Item -ItemType Directory -Path $testTemp | Out-Null
  & $Python -m pytest -q (Join-Path $root "host\tests") --basetemp (Join-Path $testTemp "host")
  if ($LASTEXITCODE -ne 0) { throw "Host tests failed ($LASTEXITCODE)" }
  & $Python -m pytest -q (Join-Path $root "ocr\tests") --basetemp (Join-Path $testTemp "ocr")
  if ($LASTEXITCODE -ne 0) { throw "OCR tests failed ($LASTEXITCODE)" }
  Remove-Item -LiteralPath $testTemp -Recurse -Force
}

Write-Host "Glowfish Reader workspace verification OK: $root"
