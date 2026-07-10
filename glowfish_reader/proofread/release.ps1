# GlowFish Reader -- release / publish script (dev side).
# ASCII-only on purpose (PS 5.1 mis-parses params in non-BOM Chinese scripts).
#
# What it does:
#   1. Read the single-source version from _version.py.
#   2. (optional) Build the PyInstaller onedir via the .spec.
#   3. Assert the frozen exe really carries every model/lexicon asset (fail the build if not).
#   4. Compile one Inno Setup installer.
#   5. Compute sha256 + size for the installer.
#   6. Emit update.json for the application update channel.
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
  [string]$SshKey = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path     # proofread/

# --- 1. version (single source: _version.py) ---
$verFile = Join-Path $here "_version.py"
$m = Select-String -Path $verFile -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $m) { throw "version not found in $verFile" }
$ver = $m.Matches[0].Groups[1].Value
Write-Host "[release] version = $ver"

# --- 2. optional build (PyInstaller onedir) ---
if ($Build) {
  $py = Join-Path $here "..\.venv\Scripts\python.exe"
  if (-not (Test-Path $py)) { throw "venv python not found: $py" }
  Write-Host "[release] building onedir via PyInstaller ..."
  & $py -m PyInstaller --noconfirm (Join-Path $here "glowfish_reader.spec")
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
}

# --- 3. capability gate: the frozen exe must carry every model + lexicon ---
# History: punct / mlm / lexicon each shipped missing at least once. The app still ran,
# the correction layers silently no-op'd, nobody noticed. A failed build is far cheaper.
$frozenExe = Join-Path $here "dist\glowfish_reader\glowfish_reader.exe"
if (Test-Path $frozenExe) {
  Write-Host "[release] asserting bundled capabilities ..."
  # The spec builds a windowed exe (console=False). PowerShell does NOT wait for GUI-subsystem
  # processes with the call operator, and leaves $LASTEXITCODE unset -- so `& $exe` would look
  # like a silent failure. Start-Process -Wait -PassThru is the only reliable way to get the code.
  $cap = Start-Process -FilePath $frozenExe -ArgumentList "--selftest-capabilities" -NoNewWindow -Wait -PassThru
  if ($cap.ExitCode -ne 0) { throw "capability selftest FAILED ($($cap.ExitCode)) -- assets missing from the bundle, refusing to ship" }
  Write-Host "[release]   capabilities OK"
} else {
  throw "frozen exe not found: $frozenExe (run PyInstaller first, or pass -Build)"
}

# --- 4. compile installers ---
$isccCandidates = @(
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
  "C:\Program Files\Inno Setup 6\ISCC.exe",
  (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$ISCC = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ISCC) { throw ("ISCC not found in any of: " + ($isccCandidates -join '; ') + " (install Inno Setup 6 or edit path)") }
$iss = Join-Path $here "installer.iss"
Write-Host "[release] compiling FULL installer ..."
& $ISCC "/DAppVersion=$ver" $iss
if ($LASTEXITCODE -ne 0) { throw "ISCC (full) failed ($LASTEXITCODE)" }

# --- 4. versioned artifacts + hashes ---
$outDir  = Join-Path $here "Output"
$built   = Join-Path $outDir "glowfish_reader_setup.exe"
if (-not (Test-Path $built)) { throw "installer not produced: $built" }
$verName = "glowfish_reader_setup_$ver.exe"
$verOut  = Join-Path $outDir $verName
Copy-Item $built $verOut -Force
$sha  = (Get-FileHash $verOut -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item $verOut).Length
Write-Host "[release] full  = $verOut"
Write-Host "[release]   sha256 = $sha  size = $size"

# --- 5. manifest update.json v2 (written WITHOUT BOM so requests.json() can parse it) ---
$manifest = [ordered]@{
  latest        = $ver
  min_supported = $MinSupported
  mandatory     = [bool]$Mandatory
  url           = "$DownloadBase/$verName"
  sha256        = $sha
  size          = $size
  notes         = $Notes
  released      = (Get-Date -Format "yyyy-MM-dd")
}
$json = $manifest | ConvertTo-Json -Depth 6
$manifestPath = Join-Path $outDir "update.json"
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[release] manifest = $manifestPath"
Write-Host $json

# --- 6. publish to HK nginx (installer first, manifest LAST) ---
$keyArg = @(); if ($SshKey) { $keyArg = @("-i", $SshKey) }
if ($Upload) {
  Write-Host "[release] uploading installer(s) + manifest ..."
  & scp @keyArg $verOut "${SshTarget}:$RemoteDlDir/$verName"
  if ($LASTEXITCODE -ne 0) { throw "scp full installer failed" }
  & scp @keyArg $manifestPath "${SshTarget}:$RemoteManifest"
  if ($LASTEXITCODE -ne 0) { throw "scp manifest failed" }
  Write-Host "[release] published. Live at: $DownloadBase/$verName"
} else {
  Write-Host ""
  Write-Host "To publish (installer first, manifest LAST):"
  Write-Host "  scp $verOut ${SshTarget}:$RemoteDlDir/$verName"
  Write-Host "  scp $manifestPath ${SshTarget}:$RemoteManifest"
}
