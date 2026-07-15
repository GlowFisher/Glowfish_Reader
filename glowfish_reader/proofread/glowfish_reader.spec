# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— Glowfish Reader 史料阅读器（本地桌面 App，onedir）。

构建（在 proofread/ 目录下，用 venv 的 pyinstaller）：
  ..\\.venv\\Scripts\\pyinstaller.exe glowfish_reader.spec --noconfirm
产物：dist/glowfish_reader/glowfish_reader.exe（自包含，含 ONNX 模型与前端）。

要点：
· 入口 desktop_app.py 兼作识别子进程（exe --ocr ...），故主程序与 OCR 共用一个 exe。
· paddleocr/paddlex/opencc/onnxruntime 用 collect_all 带齐数据与动态库；剔除未用的 *_server.onnx 大模型。
· console=False（不弹黑窗）；OCR 子进程 stdout 在 desktop_app 内已兜底。
"""
import os
import json
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files, copy_metadata
from packaging_preflight import BUNDLE_METADATA_DISTRIBUTIONS
from _version import __version__

HERE = os.path.abspath(os.getcwd())          # 在 proofread/ 下运行 pyinstaller
ROOT = os.path.dirname(HERE)
PIPELINE = os.path.join(ROOT, "pipeline")   # ../pipeline（build_docx 在此）
HOST_ROOT = os.path.dirname(ROOT)
UI_DIST = os.path.join(HOST_ROOT, "components", "ui", "dist")
OCR_COMPONENT = os.path.join(HOST_ROOT, "components", "ocr")
MODELS_DIR = os.environ.get("GLOWFISH_OCR_MODELS") or os.path.join(HERE, "models")
PRODUCT_DISPLAY_NAME = f"Glowfish Reader V{__version__}"

datas = []
binaries = []
hiddenimports = []

# 本地业务模块（部分在函数内条件 import / 经 sys.path 插入后导入，静态分析会漏，显式声明）
hiddenimports += [
    "server", "appconfig", "runtime_logging", "auth", "auth_api", "content_api", "export_api",
    "library_api", "userctx", "safefs", "settings_store", "engines", "ingest",
    "proof_model", "t2s_fixes", "punctuate_local", "recognize", "recognize_ppocrv6",
    "recognize_ppocrv6_onnx", "build_docx",
    "det_scale", "ocr_confusion", "ocr_enhance", "capabilities",
    "license_api", "licensing", "licensing.envelope", "licensing.keys",
    "licensing.verify", "licensing.fingerprint",
    "licensing.store", "licensing.client", "license_common", "license_common.signing", "_cffi_backend",
]


def _require(path, what):
    """构建期硬闸：缺件立刻炸，不许静默出一个残废包。

    历史上 punct / mlm / lexicon 三类资产都因为 `if isfile(...)` 的静默跳过而漏打，
    程序照跑、功能没了、没人发现。构建失败远比装机版静默降级便宜。
    """
    if not os.path.exists(path):
        raise SystemExit(f"[spec] 缺少必带资产（{what}）：{path}")
    return path

# 前端静态资源（StaticFiles 从 <bundle>/static 取）
with open(_require(os.path.join(UI_DIST, "manifest.json"), "UI dist manifest"), encoding="utf-8") as _fh:
    _ui_manifest = json.load(_fh)
datas += [(os.path.join(UI_DIST, "manifest.json"), "ui_dist")]
for _asset in _ui_manifest["files"]:
    _rel = _asset["path"]
    datas += [(_require(os.path.join(UI_DIST, _rel), "UI manifest asset"), os.path.join("ui_dist", os.path.dirname(_rel)))]

# 构建期 SKU 标记（appconfig.get_mode 打包态据此锁定 single/multi，环境变量不可覆盖）
datas += [(os.path.join(HERE, "sku.txt"), ".")]
datas += [(os.path.join(HOST_ROOT, "component-manifest.json"), ".")]

# PP-OCRv6 ONNX 轻量识别模型
with open(_require(os.path.join(OCR_COMPONENT, "models.lock.json"), "OCR models lock"), encoding="utf-8") as _fh:
    _models_lock = json.load(_fh)
for _model in _models_lock["files"]:
    _rel = _model["path"]
    datas += [(_require(os.path.join(MODELS_DIR, _rel), "locked OCR model"), os.path.join("models", os.path.dirname(_rel)))]

# 冻结包真实 OCR 冒烟图：复用仓库基准 fixture，包内固定落到 assets/selftest/。
_ocr_smoke = _require(os.path.join(OCR_COMPONENT, "bench", "fixtures", "vertical_cht_clean.png"), "OCR 自检图片")
datas += [(_ocr_smoke, os.path.join("assets", "selftest"))]

# 本地古文标点模型：只带 int8 量化版（~99MB，F1 与 fp32 持平），fp32 388MB 不打。

# 词表：域词修复 / 形近字 / 人名切分依赖，0.4MB，缺了纠错层会加载成空表静默 no-op。
datas += [(_require(os.path.join(OCR_COMPONENT, "src", "glowfish_ocr", "legacy", "assets", "lexicon"), "OCR lexicon"), os.path.join("assets", "lexicon"))]

# 第三方需带数据/动态库/子模块的包（nacl 带 _sodium C 扩展，授权离线验签用）
# shapely / pyclipper 是 PaddleX OCR pipeline 运行时依赖，collect_all 不会自动拉。
for pkg in ("paddleocr", "paddlex", "opencc", "onnxruntime", "nacl",
            "shapely", "pyclipper"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("uvicorn")   # 协议/loop 动态加载
datas += collect_data_files("docx")              # python-docx 默认模板

# 精简：剔除未用的大模型
def _keep(item):
    return not str(item[0]).lower().endswith("_server.onnx")

datas = [d for d in datas if _keep(d)]
binaries = [b for b in binaries if _keep(b)]

# PaddleX 用 importlib.metadata 判断依赖是否安装；只有模块/DLL 而没有
# .dist-info 仍会报 DependencyError。copy_metadata() 必须加入 datas，
# 不能作为 Analysis 的未知关键字参数传入（PyInstaller 会静默忽略）。
for _dist_name in BUNDLE_METADATA_DISTRIBUTIONS:
    datas += copy_metadata(_dist_name)

a = Analysis(
    ["desktop_app.py"],
    pathex=[HERE, ROOT, PIPELINE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "paddle"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=PRODUCT_DISPLAY_NAME,
    console=False,                  # 桌面 App：不弹控制台黑窗
    icon=os.path.join(HERE, "assets", "glowfish.ico"),   # 商标：与 glowfish 图库同一标识（多尺寸 ico）→ 任务栏/快捷方式/explorer
    version=os.path.join(HERE, "version_info.txt"),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="glowfish_reader",
)
