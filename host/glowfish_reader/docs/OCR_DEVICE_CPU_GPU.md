# OCR 识别设备：CPU 版 / GPU 版并存说明

识别引擎（`proofread/recognize_ppocrv6.py`）**同时支持 CPU 与 NVIDIA GPU**。
代码一套，跑在哪由环境里装的是哪个 paddle + `SHUPAI_OCR_DEVICE` 决定。

> ⚠️ `paddlepaddle`（CPU 版）与 `paddlepaddle-gpu`（GPU 版）**不能装在同一个 python 环境里**
> ——两者都提供 `paddle` 包，后装的会覆盖先装的。所以"两个版本"指的是：同一套代码，
> 用户按自己机器选择安装其中之一；没有显卡的用户不受任何影响。

## 设备选择：`SHUPAI_OCR_DEVICE`

| 取值 | 行为 |
|---|---|
| `auto`（默认） | 装了 GPU 版 paddle 且检测到可用显卡 → 用 `gpu:0`；否则 CPU |
| `cpu` | 强制 CPU（GPU 版 paddle 也能这样跑，便于对拍） |
| `gpu` / `gpu:N` | 强制指定显卡 |

**自动兜底**：即使选了 GPU，若引擎构造失败（缺驱动 / CUDA DLL 不全 / 显存不足），
会打一条 `WARN: GPU OCR unavailable ...; falling back to CPU` 并**自动回落 CPU**，
不会让用户的识别任务直接崩掉。实际生效的设备记在 `recog.json` 的 `ocr_meta.device`。

## 安装（paddleocr conda 环境，Python 3.10）

环境备份（换版本前先留底）：

```powershell
& "C:\Users\18267\miniconda3\envs\paddleocr\python.exe" -m pip freeze > tmp/paddleocr_env_freeze.txt
```

### GPU 版（推荐，有 NVIDIA 显卡时）

驱动 ≥ CUDA 12.6 对应版本（本机 565.90 / RTX 4060 Laptop 8GB 实测可用）。
国内官方源直连（绕代理，实测 16MB/s）：

```powershell
$env:NO_PROXY="*"
& "...\paddleocr\python.exe" -m pip uninstall -y paddlepaddle
& "...\paddleocr\python.exe" -m pip install paddlepaddle-gpu==3.1.1 `
    -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

会额外拉 ~2GB 的 `nvidia-cudnn-cu12` / `nvidia-cublas-cu12` 等 CUDA 依赖。

### CPU 版（无显卡 / 需要回滚）

```powershell
& "...\paddleocr\python.exe" -m pip uninstall -y paddlepaddle-gpu
& "...\paddleocr\python.exe" -m pip install paddlepaddle==3.1.1 `
    -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

## 为什么值得装 GPU 版

`high_accuracy` 档对每一竖列裁图重跑一遍全尺度 det+rec，一页十几趟整页级推理。
实测《黔人自组盐号承办仁岸运销节略》页1（6347×6345 草书公文）端到端：

| 档位 | 耗时/页 |
|---|---|
| CPU（改造前） | **22 分 45 秒** |
| GPU（RTX 4060 Laptop） | **约 26 秒** |

精度一致：CPU 与 GPU 的字准率差 0.15pt（1 个字，CER 差 0.0015），属正常数值差异。

## 相关开关

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `SHUPAI_OCR_DEVICE` | `auto` | 识别设备 |
| `SHUPAI_COL_DETECT_V2` | `1` | v2 列检测（去边框实心线 + 投影波谷切列） |
| `SHUPAI_COL_AGG_YGUARD` | `1` | 竖列聚合的 y 守卫（防相邻两列被链式并成一列致读序错乱） |
| `SHUPAI_DOMAIN_FIXES` | `1` | 域词确定性修复层（空跑审计准入，见 `bench/audit_domain_fixes.py`） |
