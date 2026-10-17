[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Python,
  [string]$ProofreadDirectory = "",
  [string]$BuildRoot = ""
)
$ErrorActionPreference = "Stop"
$hostRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ProofreadDirectory) { $ProofreadDirectory = Join-Path $hostRoot "glowfish_reader\proofread" }
if (-not $BuildRoot) { $BuildRoot = $env:GLOWFISH_BUILD_ROOT }
if (-not $BuildRoot) { $BuildRoot = Join-Path ([IO.Path]::GetPathRoot($hostRoot)) "GlowfishBuild\local" }
$workPath = Join-Path $BuildRoot "work"
$distPath = Join-Path $BuildRoot "dist"
if (-not (Test-Path $Python)) { throw "Python executable missing: $Python" }
Push-Location $ProofreadDirectory
try {
  & $Python -m PyInstaller --clean --noconfirm --workpath $workPath --distpath $distPath glowfish_reader.spec
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }
