# Glowfish Reader -- release / publish script (dev side).
# ASCII-only on purpose (PS 5.1 mis-parses params in non-BOM Chinese scripts).
#
# What it does:
#   1. Read the single-source version from _version.py.
#   2. Run packaging dependency preflight.
#   3. (optional) Build the PyInstaller onedir via the .spec.
#   4. Run frozen asset, service, dependency, and real OCR gates.
#   5. Compile one Inno Setup installer.
#   6. Compute sha256 + size and emit update.json.
#   7. Print (or, with -Upload, run) the scp commands to publish.
#
# Usage examples:
#   .\release.ps1 -Notes "1.0.3: PP-OCRv6 pipeline and notebook fixes"
#   .\release.ps1 -Notes "..." -Upload -SshKey $env:USERPROFILE\.ssh\glowfish_license_deploy
#   (avoid -Build under PS5.1: run PyInstaller manually first, see HANDOFF section 8)
[CmdletBinding()]
param(
  [string]$Notes = "",
  [string]$MinSupported = "1.0.0",
  [switch]$Mandatory,
  [switch]$Build,
  [switch]$Upload,
  [string]$SshTarget   = "root@47.83.12.17",
  [string]$RemoteDlDir = "/var/www/glowfish/dl",
  [string]$RemoteManifest = "/var/www/glowfish/update.json",
  [string]$DownloadBase = "https://license.glowfishreader.com/dl",
  [string]$SshKey = "",
  [string]$BuildRoot = "",
  [string]$OutputDir = "",
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path     # proofread/

# --- 1. version (single source: _version.py) ---
$verFile = Join-Path $here "_version.py"
$m = Select-String -Path $verFile -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $m) { throw "version not found in $verFile" }
$ver = $m.Matches[0].Groups[1].Value
$productName = "Glowfish Reader V$ver"
$appExeName = "$productName.exe"
$setupBase = "$productName Setup"
$setupFileName = "$setupBase.exe"
Write-Host "[release] version = $ver"
Write-Host "[release] product = $productName"

# --- 2. packaging dependency preflight (does not build) ---
$py = $Python
if (-not $py) { $py = $env:GLOWFISH_BUILD_PYTHON }
if (-not $py) { $py = Join-Path $here "..\.venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { throw "build python not found: $py (pass -Python or set GLOWFISH_BUILD_PYTHON)" }
$hostRoot = (Resolve-Path (Join-Path $here "..\..")).Path
$workspaceRoot = $env:GLOWFISH_WORKSPACE_ROOT
if (-not $workspaceRoot) { $workspaceRoot = Split-Path $hostRoot -Parent }
if (-not $BuildRoot) { $BuildRoot = $env:GLOWFISH_BUILD_ROOT }
if (-not $BuildRoot) { $BuildRoot = Join-Path ([IO.Path]::GetPathRoot($hostRoot)) "GlowfishBuild\release" }
$workPath = Join-Path $BuildRoot "work"
$distPath = Join-Path $BuildRoot "dist"
if (-not $OutputDir) { $OutputDir = Join-Path $BuildRoot "artifacts" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
if ((Join-Path $distPath "glowfish_reader\_internal\onnxruntime\tools\ort_format_model\ort_flatbuffers_py\fbs\RuntimeOptimizationRecordContainerEntry.py").Length -ge 248) { throw "BuildRoot is too long for Windows packaging: $BuildRoot" }
$uiRoot = Join-Path $workspaceRoot "ui"
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { throw "npm.cmd not found; cannot build pinned UI component" }
Write-Host "[release] validating pinned component graph ..."
& $py (Join-Path $workspaceRoot "scripts\validate_workspace.py")
if ($LASTEXITCODE -ne 0) { throw "workspace validation FAILED ($LASTEXITCODE)" }
Push-Location $uiRoot
try {
  & $npm run build
  if ($LASTEXITCODE -ne 0) { throw "UI deterministic build FAILED ($LASTEXITCODE)" }
} finally { Pop-Location }
& $py (Join-Path $workspaceRoot "scripts\verify_release_assets.py")
if ($LASTEXITCODE -ne 0) { throw "component asset verification FAILED ($LASTEXITCODE)" }
Write-Host "[release] running packaging preflight ..."
& $py (Join-Path $here "packaging_preflight.py")
if ($LASTEXITCODE -ne 0) { throw "packaging preflight FAILED ($LASTEXITCODE)" }
Write-Host "[release] enforcing drive-free OCR runtime ..."
$driveAliasRuntimeFiles = @(
  (Join-Path $here "paddlex_cache.py"),
  (Join-Path $here "recognize_ppocrv6.py"),
  (Join-Path $here "recognize_ppocrv6_onnx.py"),
  (Join-Path $workspaceRoot "ocr\src\glowfish_ocr\legacy\paddlex_cache.py"),
  (Join-Path $workspaceRoot "ocr\src\glowfish_ocr\legacy\recognize_ppocrv6.py"),
  (Join-Path $workspaceRoot "ocr\src\glowfish_ocr\legacy\recognize_ppocrv6_onnx.py")
)
foreach ($runtimeFile in $driveAliasRuntimeFiles) {
  if (-not (Test-Path $runtimeFile)) { throw "drive-free gate input missing: $runtimeFile" }
  $forbidden = Select-String -LiteralPath $runtimeFile -SimpleMatch -Pattern '["subst"', "['subst'"
  if ($forbidden) { throw "forbidden subst invocation in runtime: $runtimeFile" }
}
Write-Host "[release]   drive-free OCR runtime OK"
# --- 3. optional build (PyInstaller onedir) ---
if ($Build) {
  Write-Host "[release] building onedir via PyInstaller ..."
  Push-Location $here
  try {
    & $py -m PyInstaller --clean --noconfirm --workpath $workPath --distpath $distPath "glowfish_reader.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
  } finally {
    Pop-Location
  }
}

# --- 4. frozen executable gates ---
# History: punct / mlm / lexicon each shipped missing at least once. The app still ran,
# the correction layers silently no-op'd, nobody noticed. A failed build is far cheaper.
$distDir = Join-Path $distPath "glowfish_reader"
$frozenExe = Join-Path $distDir $appExeName
if (Test-Path $frozenExe) {
  # Windowed executables require Start-Process -Wait -PassThru to expose the exit code.
  $gateSandboxRoot = Join-Path $here (".release-gates-" + [guid]::NewGuid().ToString("N"))
  $unicodeGateLeaf = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5Lit5paHIOeUqOaIt+aVsOaNriDplb/ot6/lvoTpqozmlLY="))
  $gateDataRoot = Join-Path $gateSandboxRoot $unicodeGateLeaf
  New-Item -ItemType Directory -Path $gateDataRoot | Out-Null
  $driveAliasesBefore = @(& subst 2>$null | Sort-Object)
  function Invoke-FrozenGate([string]$Name, [string]$Argument) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $frozenExe
    $psi.Arguments = $Argument
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $distDir
    $p = [System.Diagnostics.Process]::Start($psi)
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw "$Name FAILED ($($p.ExitCode)); refusing to ship" }
    Write-Host "[release]   $Name OK"
  }
  # Release verification must never touch a developer's real profile data.
  $previousGateDataRoot = $env:SHUPAI_DATA_DIR
  $env:SHUPAI_DATA_DIR = $gateDataRoot
  try {
    Invoke-FrozenGate "capabilities" "--selftest-capabilities"
    Invoke-FrozenGate "service selftest" "--selftest"
    Invoke-FrozenGate "OCR dependency metadata" "--selftest-ocr-deps"
    Invoke-FrozenGate "offline OCR selftest" "--selftest-ocr"
    Invoke-FrozenGate "resident OCR Unicode path selftest" "--selftest-ocr-resident"
    Invoke-FrozenGate "image export + runtime logging fixes" "--selftest-release-fixes"
  } finally {
    if ($null -eq $previousGateDataRoot) {
      Remove-Item Env:SHUPAI_DATA_DIR -ErrorAction SilentlyContinue
    } else {
      $env:SHUPAI_DATA_DIR = $previousGateDataRoot
    }
    $driveAliasesAfter = @(& subst 2>$null | Sort-Object)
    $newDriveAliases = @($driveAliasesAfter | Where-Object { $_ -notin $driveAliasesBefore })
    foreach ($aliasLine in $newDriveAliases) {
      $driveMatch = [regex]::Match($aliasLine, '^([A-Z]:)')
      if ($driveMatch.Success) { & subst $driveMatch.Groups[1].Value /D 2>$null }
    }
    Remove-Item -LiteralPath $gateSandboxRoot -Recurse -Force -ErrorAction SilentlyContinue
    if ($newDriveAliases.Count -gt 0) {
      throw ("frozen runtime created a temporary drive alias: " + ($newDriveAliases -join '; '))
    }
  }
} else {
  throw "frozen exe not found: $frozenExe (run PyInstaller first, or pass -Build)"
}

Write-Host "[release] auditing frozen payload ..."
& $py (Join-Path $here "packaging_payload_audit.py") $distDir $productName
if ($LASTEXITCODE -ne 0) { throw "frozen payload audit FAILED ($LASTEXITCODE)" }

# --- 5. compile installer ---
$isccCandidates = @(
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
  "C:\Program Files\Inno Setup 6\ISCC.exe",
  (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$ISCC = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ISCC) { throw ("ISCC not found in any of: " + ($isccCandidates -join '; ') + " (install Inno Setup 6 or edit path)") }
$iss = Join-Path $here "installer.iss"
Write-Host "[release] compiling FULL installer ..."
& $ISCC "/DAppVersion=$ver" "/DOutputBase=$setupBase" "/DSourceDir=$distDir" "/DOutputDir=$OutputDir" $iss
if ($LASTEXITCODE -ne 0) { throw "ISCC (full) failed ($LASTEXITCODE)" }

# --- 4. versioned artifacts + hashes ---
$built = Join-Path $OutputDir $setupFileName
if (-not (Test-Path $built)) { throw "installer not produced: $built" }
$verOut = $built
$meta = (Get-Item $verOut).VersionInfo
if ($meta.ProductName.Trim() -ne $productName) { throw "installer ProductName mismatch: $($meta.ProductName)" }
if ($meta.ProductVersion.Trim() -ne $ver) { throw "installer ProductVersion mismatch: $($meta.ProductVersion)" }
$sha  = (Get-FileHash $verOut -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item $verOut).Length
Write-Host "[release] setup = $verOut"
Write-Host "[release]   sha256 = $sha  size = $size"

# --- 5. manifest update.json v2 (written WITHOUT BOM so requests.json() can parse it) ---
$manifest = [ordered]@{
  latest        = $ver
  min_supported = $MinSupported
  mandatory     = [bool]$Mandatory
  url           = "$DownloadBase/$([uri]::EscapeDataString($setupFileName))"
  sha256        = $sha
  size          = $size
  notes         = $Notes
  released      = (Get-Date -Format "yyyy-MM-dd")
}
$json = $manifest | ConvertTo-Json -Depth 6
$manifestPath = Join-Path $OutputDir "update.json"
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[release] manifest = $manifestPath"
Write-Host $json

# --- 6. publish to HK nginx (installer first, manifest LAST) ---
$keyArg = @(); if ($SshKey) { $keyArg = @("-i", $SshKey) }
if ($Upload) {
  Write-Host "[release] uploading installer(s) + manifest ..."
  & scp @keyArg $verOut "${SshTarget}:$RemoteDlDir/$setupFileName"
  if ($LASTEXITCODE -ne 0) { throw "scp full installer failed" }
  & scp @keyArg $manifestPath "${SshTarget}:$RemoteManifest"
  if ($LASTEXITCODE -ne 0) { throw "scp manifest failed" }
  Write-Host "[release] published. Live at: $DownloadBase/$([uri]::EscapeDataString($setupFileName))"
} else {
  Write-Host ""
  Write-Host "To publish (installer first, manifest LAST):"
  Write-Host "  scp `"$verOut`" `"${SshTarget}:$RemoteDlDir/$setupFileName`""
  Write-Host "  scp $manifestPath ${SshTarget}:$RemoteManifest"
}
