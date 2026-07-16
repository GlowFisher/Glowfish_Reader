[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$BundleDirectory,
  [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = "Stop"
$bundles = [IO.Path]::GetFullPath($BundleDirectory)
$targetRoot = [IO.Path]::GetFullPath($Destination)
if (Test-Path $targetRoot) { throw "Destination must not already exist: $targetRoot" }
New-Item -ItemType Directory $targetRoot | Out-Null
$names = @("glowfish-contracts", "glowfish-reader-ui", "glowfish-ocr", "glowfish-account", "glowfish-reader-host")
foreach ($name in $names) {
  $bundle = Join-Path $bundles "$name.bundle"
  git bundle verify $bundle | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Invalid bundle: $bundle" }
  git clone $bundle (Join-Path $targetRoot $name)
  if ($LASTEXITCODE -ne 0) { throw "Clone failed: $name" }
}
$hostRepo = Join-Path $targetRoot "glowfish-reader-host"
git -C $hostRepo switch release/1.0.1
if ($LASTEXITCODE -ne 0) { throw "Host integration branch missing" }
$mapping = @{contracts="glowfish-contracts"; ui="glowfish-reader-ui"; ocr="glowfish-ocr"; account="glowfish-account"}
foreach ($component in $mapping.Keys) {
  $source = Join-Path $targetRoot $mapping[$component]
  $path = Join-Path $hostRepo "components\$component"
  git clone --no-hardlinks $source $path
  if ($LASTEXITCODE -ne 0) { throw "Host component clone failed: $component" }
  $line = git -C $hostRepo ls-tree HEAD "components/$component"
  $sha = ($line -split '\s+')[2]
  git -C $path checkout $sha
  if ($LASTEXITCODE -ne 0) { throw "Pinned checkout failed: $component@$sha" }
}
$contractPath = Join-Path $targetRoot "glowfish-contracts"
foreach ($component in @("ui", "ocr", "account")) {
  $componentRepo = Join-Path $hostRepo "components\$component"
  $nested = Join-Path $componentRepo "components\contracts"
  git clone --no-hardlinks $contractPath $nested
  if ($LASTEXITCODE -ne 0) { throw "Nested contracts clone failed: $component" }
  $line = git -C $componentRepo ls-tree HEAD components/contracts
  $sha = ($line -split '\s+')[2]
  git -C $nested checkout $sha
  if ($LASTEXITCODE -ne 0) { throw "Nested contracts checkout failed: $component@$sha" }
}
python (Join-Path $hostRepo "scripts\validate_components.py")
if ($LASTEXITCODE -ne 0) { throw "Restored component graph failed validation" }
Write-Host "Offline handoff restored and verified at $targetRoot"
