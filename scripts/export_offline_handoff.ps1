[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = "Stop"
$hostRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reposRoot = Split-Path $hostRepo -Parent
$destinationPath = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force $destinationPath | Out-Null
$names = @("glowfish-contracts", "glowfish-reader-ui", "glowfish-ocr", "glowfish-account", "glowfish-reader-host")
$hashes = @()
foreach ($name in $names) {
  $repo = Join-Path $reposRoot $name
  if (-not (Test-Path (Join-Path $repo ".git"))) { throw "Repository missing: $repo" }
  $dirty = git -C $repo status --porcelain
  if ($dirty) { throw "Refusing to export dirty repository: $name" }
  $bundle = Join-Path $destinationPath "$name.bundle"
  git -C $repo bundle create $bundle --all
  if ($LASTEXITCODE -ne 0) { throw "Bundle creation failed: $name" }
  git bundle verify $bundle | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Bundle verification failed: $name" }
  $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant()
  $hashes += "$digest  $name.bundle"
}
$hashes | Set-Content -LiteralPath (Join-Path $destinationPath "SHA256SUMS.txt") -Encoding ASCII
Copy-Item -LiteralPath (Join-Path $hostRepo "component-manifest.json") -Destination $destinationPath -Force
Copy-Item -LiteralPath (Join-Path $hostRepo "docs\OFFLINE_HANDOFF.md") -Destination (Join-Path $destinationPath "RESTORE.md") -Force
Copy-Item -LiteralPath (Join-Path $hostRepo "scripts\restore_offline_handoff.ps1") -Destination $destinationPath -Force
Write-Host "Verified offline handoff created at $destinationPath"
