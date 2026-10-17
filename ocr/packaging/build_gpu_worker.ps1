[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$BuildRoot,
  [string]$LockFile,
  [switch]$RequireReleaseQualified
)

$ErrorActionPreference = "Stop"
$ocrRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$entry = Join-Path $ocrRoot "src\glowfish_ocr\legacy\gpu_worker.py"
$legacy = Join-Path $ocrRoot "src\glowfish_ocr\legacy"
$source = Join-Path $ocrRoot "src"
$dist = Join-Path $BuildRoot "gpu-worker"
$lockVerifier = Join-Path $PSScriptRoot "verify_gpu_runtime_build.py"
if (-not $LockFile) { $LockFile = Join-Path $PSScriptRoot "gpu-runtime-build.lock.json" }
$provenance = Join-Path $BuildRoot "gpu-build-provenance.json"

if (-not (Test-Path $Python)) { throw "Python executable missing: $Python" }
if (-not (Test-Path $LockFile)) { throw "GPU build lock missing: $LockFile" }

$verifyArgs = @($lockVerifier, "--lock", $LockFile, "--out", $provenance)
if ($RequireReleaseQualified) { $verifyArgs += "--require-release-qualified" }
& $Python @verifyArgs
if ($LASTEXITCODE -ne 0) { throw "GPU Worker build environment rejected by lock: $LASTEXITCODE" }

# Fail early with an actionable message.  ``paddlepaddle-gpu`` must already
# have been chosen from Paddle's official Windows/CUDA compatibility matrix.
& $Python -c "import PyInstaller, onnxruntime, paddle, paddleocr, paddlex; from paddlex.utils.deps import is_extra_available; from PIL import Image; providers=onnxruntime.get_available_providers(); assert 'CUDAExecutionProvider' in providers, providers; assert is_extra_available('ocr-core'), 'paddlex[ocr-core] dependencies are missing'"
if ($LASTEXITCODE -ne 0) {
  throw "GPU Worker environment is incomplete or has no CUDAExecutionProvider. Install the matching paddlepaddle-gpu wheel, then run: $Python -m pip install -r $ocrRoot\gpu-runtime-requirements.txt pyinstaller"
}

# The current Paddle/PaddleX ONNX execution stack dynamically loads additional
# NVIDIA math libraries beyond the CUDA EP's documented cuBLAS/cuDNN surface.
# A measured minimal collection failed the strict CUDA Session probe with error
# 126, so keep this complete, known-good set until a standalone ONNX-only
# Worker removes that implicit Paddle dependency.
& $Python -m PyInstaller --clean --noconfirm --onefile --name glowfish_gpu_worker `
  --paths $source --paths $legacy `
  --collect-all onnxruntime --collect-all paddleocr --collect-all paddlex --collect-all nvidia `
  --copy-metadata paddlex --copy-metadata imagesize `
  --copy-metadata opencv-contrib-python --copy-metadata pyclipper `
  --copy-metadata pypdfium2 --copy-metadata python-bidi --copy-metadata shapely `
  --distpath $dist --workpath (Join-Path $BuildRoot "work") $entry
if ($LASTEXITCODE -ne 0) { throw "GPU Worker PyInstaller build failed: $LASTEXITCODE" }

$worker = Join-Path $dist "glowfish_gpu_worker.exe"
if (-not (Test-Path $worker)) { throw "GPU Worker artifact missing after PyInstaller build" }
Write-Output "GPU Worker built: $worker"
Write-Output "GPU Worker provenance: $provenance"
