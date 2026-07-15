[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Owner)
$ErrorActionPreference = "Stop"
if ($Owner -notmatch '^[A-Za-z0-9_.-]+$') { throw "Invalid GitHub owner" }
gh auth status
if ($LASTEXITCODE -ne 0) { throw "Authenticate gh on this workstation first" }
$hostRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reposRoot = Split-Path $hostRepo -Parent
$names = @("glowfish-contracts", "glowfish-reader-ui", "glowfish-ocr", "glowfish-account", "glowfish-reader-host")
foreach ($name in $names) {
  $repo = Join-Path $reposRoot $name
  gh repo create "$Owner/$name" --private --disable-issues --disable-wiki
  if ($LASTEXITCODE -ne 0) { throw "Private repository creation failed: $name" }
  $url = "https://github.com/$Owner/$name.git"
  git -C $repo remote add github $url
  if ($LASTEXITCODE -ne 0) { throw "Adding remote failed: $name" }
  git -C $repo push github --all
  if ($LASTEXITCODE -ne 0) { throw "Branch push failed: $name" }
  git -C $repo push github --tags
  if ($LASTEXITCODE -ne 0) { throw "Tag push failed: $name" }
  gh repo edit "$Owner/$name" --default-branch main
}
Write-Host "Private repositories pushed. Apply the mandatory branch protection checklist in docs/OFFLINE_HANDOFF.md."
