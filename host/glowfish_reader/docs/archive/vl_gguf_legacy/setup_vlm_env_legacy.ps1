# -*- coding: utf-8 -*-
# 建 PaddleOCR-VL 独立 conda 环境(与旧 paddle/chinese_cht env 物理隔离)。
# 本机 NVIDIA 8GB 显卡 -> 装 GPU 版。本脚本会触发 GB 级下载,请在网络良好时运行。
#
# ⚠️ paddlepaddle-gpu 的 wheel 必须匹配本机 CUDA。本机 restore env 用 cu118,默认按 cu118 装;
#    若不符,改 $CudaTag,或以 PaddleOCR-VL 官方安装页为准:https://www.paddleocr.ai/
#
# 用法:  & "D:\CC-first\glowfish_reader\setup_vlm_env.ps1"
#         可选参数:-EnvName paddleocr-vl  -CudaTag cu118  -PyVer 3.11

param(
    [string]$EnvName = "paddleocr-vl",
    [string]$CudaTag = "cu118",
    [string]$PyVer   = "3.11"
)

# ⚠️ 不用 $ErrorActionPreference="Stop"：本机 base conda 每次都往 stderr 吐一句无害的
#    urllib3/chardet 版本不匹配警告，Stop 会把这条 NativeCommandError 当致命错误误杀脚本。
#    改为手动查 $LASTEXITCODE：无害 stderr 噪声放行，真失败（非零退出码）才拦。
$ErrorActionPreference = "Continue"

function Assert-LastExit($what) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] 步骤失败（退出码 $LASTEXITCODE）：$what"
        exit 1
    }
}

# 0) 前置:conda 必须在 PATH
$conda = (Get-Command conda -ErrorAction SilentlyContinue)
if (-not $conda) {
    Write-Host "[X] 未找到 conda。请在 Anaconda/Miniconda Prompt 里运行,或把 conda 加入 PATH。"
    exit 1
}

# 1) 建环境(已存在则跳过创建)。conda env list 的 stderr 警告无害，只看 stdout。
$envs = (conda env list 2>$null)
if ($envs -match "[\\/]$([regex]::Escape($EnvName))\b") {
    Write-Host "[=] conda env '$EnvName' 已存在,跳过创建。"
} else {
    Write-Host "[*] 创建 conda env '$EnvName' (python=$PyVer) ..."
    conda create -y -n $EnvName "python=$PyVer"
    Assert-LastExit "conda create -n $EnvName"
}

# 2) 升级 pip
Write-Host "[*] 升级 pip ..."
conda run -n $EnvName python -m pip install --upgrade pip
Assert-LastExit "pip install --upgrade pip"

# 3) 装 paddlepaddle-gpu(匹配 CUDA)。版本不锁死,取官方 stable 源该 CUDA 档最新 3.x。
Write-Host "[*] 安装 paddlepaddle-gpu ($CudaTag) ..."
conda run -n $EnvName python -m pip install paddlepaddle-gpu `
    -i "https://www.paddlepaddle.org.cn/packages/stable/$CudaTag/"
Assert-LastExit "pip install paddlepaddle-gpu ($CudaTag)"

# 4) 装 paddleocr(含 doc-parser/VL pipeline 依赖)。首次 predict 时自动拉取 VL-1.6 权重(Baidu BOS,国内快)。
Write-Host "[*] 安装 paddleocr[doc-parser] ..."
conda run -n $EnvName python -m pip install -U "paddleocr[doc-parser]"
Assert-LastExit "pip install paddleocr[doc-parser]"

# 5) 自检:打印解释器路径 + 能否导入 PaddleOCRVL
Write-Host "[*] 自检 import ..."
conda run -n $EnvName python -c "import sys, paddleocr; from paddleocr import PaddleOCRVL; print('VLM_PY=' + sys.executable); print('paddleocr ' + paddleocr.__version__)"
Assert-LastExit "import PaddleOCRVL 自检"

Write-Host ""
Write-Host "[OK] 完成。把上面打印的 VLM_PY 路径设给环境变量 SHUPAI_VLM_PY,"
Write-Host "     或直接留给 appconfig 自动探测(它会扫名字含 'vl' 的 conda env)。"
Write-Host "     启用引擎:`$env:SHUPAI_ENGINE = 'paddleocr_vl' 后起 server。"
