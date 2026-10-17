[CmdletBinding()]
param(
  [string]$Notes = "Glowfish Reader 1.0.3：OCR 续识、PDF 完整导入与运行稳定性修复",
  [switch]$Mandatory,
  [string]$MinSupported = "1.0.0",
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:GLOWFISH_WORKSPACE_ROOT = $root
$env:GLOWFISH_UI_DIST = Join-Path $root "ui\dist"
$env:GLOWFISH_OCR_ROOT = Join-Path $root "ocr"
$env:GLOWFISH_CONTRACTS_ROOT = Join-Path $root "contracts"
$python = $Python
if (-not $python) {
  $python = Join-Path $root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
  throw "Build Python not found. Run bootstrap.ps1 or pass -Python."
}

$release = Join-Path $root "host\glowfish_reader\proofread\release.ps1"
$buildRoot = Join-Path $root ".build"
$output = Join-Path $root "releases\internal-validation\1.0.3"
$arguments = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $release,
  "-Notes", $Notes,
  "-MinSupported", $MinSupported,
  "-Build",
  "-BuildRoot", $buildRoot,
  "-OutputDir", $output,
  "-Python", $python
)
if ($Mandatory) { $arguments += "-Mandatory" }

& powershell.exe @arguments
if ($LASTEXITCODE -ne 0) { throw "release build failed ($LASTEXITCODE)" }

Write-Host "Release artifacts written to $output"
