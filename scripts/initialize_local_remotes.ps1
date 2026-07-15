[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = "Stop"
$hostRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reposRoot = Split-Path $hostRepo -Parent
$destinationPath = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force $destinationPath | Out-Null
$names = @("glowfish-contracts", "glowfish-reader-ui", "glowfish-ocr", "glowfish-account", "glowfish-reader-host")
foreach ($name in $names) {
  $source = Join-Path $reposRoot $name
  $target = Join-Path $destinationPath $name
  if (Test-Path $target) { throw "Target already exists: $target" }
  git clone --bare --no-hardlinks $source $target
  if ($LASTEXITCODE -ne 0) { throw "Bare clone failed: $name" }
  git -C $target config receive.denyNonFastForwards true
  git -C $target config receive.denyDeletes true
}
Write-Host "Private bare remotes created at $destinationPath; apply OS/SMB ACLs before sharing."
