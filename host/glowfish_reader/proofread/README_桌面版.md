# GlowFish 史料阅读器 · 本地桌面 App（阶段 2 交付）

把竖排繁体史料「识别 + 图文对照点校」工作台打成**双击安装、开箱即用**的 Windows 桌面软件：
软件与全部史料处理都在用户本机，**素材永不上云**，无需 Python / conda。

## 形态

- **单机单用户**：无登录，数据落 `%APPDATA%\GlowFish史料阅读器\`（卸载不删）。
- **识别引擎**：PP-OCRv6 ONNX（onnxruntime，CPU 可跑），模型随包内置、离线可用。
- **窗口**：pywebview + 系统 WebView2（不捆 Chromium，体积小）。
- **多用户网页版**：降级为「机构私有化 SKU」备用，代码仍在仓库（`SHUPAI_MODE=multi` 启用）。

## 运行模式开关（`appconfig`）

| 变量 | 取值 | 说明 |
|---|---|---|
| `SHUPAI_MODE` | `single` / `multi` | 默认 single；multi 为机构私有化登录模式，需显式启用 |
| `SHUPAI_DATA_DIR` | 路径 | 数据根覆盖；打包态默认 `%APPDATA%\GlowFish史料阅读器\` |
| `SHUPAI_ENGINE` | `ppocrv6` / `ppocrv6_onnx` / `paddle` / `onnx` | 默认 `ppocrv6`；`onnx` 为 `ppocrv6_onnx` 兼容别名 |
| `SHUPAI_OPEN_BROWSER` | `0` / `1` | 桌面壳固定 0 |

## 入口 `desktop_app.py`

| 命令 | 作用 |
|---|---|
| `python desktop_app.py` | 起内嵌服务 + pywebview 原生窗口（关窗即退） |
| `exe --ocr <engine> --images … --out … [--progress …]` | 识别子进程（打包态内部用，规避 frozen `sys.executable` 非解释器坑） |
| `exe --selftest` | 无界面自检：起服务→打 `/api/me`+`/api/settings`→打印 `SELFTEST OK/FAIL` |
| `exe --serve [port] [host]` | 无界面前台起服务（调试 / E2E 验证 / 内网共享） |

## 构建（开发机，已装 `.venv` + pyinstaller + pywebview）

```powershell
# 1) PyInstaller 打包成自包含 onedir（产物 dist\glowfish_reader\）
cd proofread
..\.venv\Scripts\pyinstaller.exe glowfish_reader.spec --noconfirm

# 2) Inno Setup 编译安装包（产物 Output\glowfish_reader_setup.exe）
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

- `glowfish_reader.spec`：collect_all(paddleocr/paddlex/opencc/onnxruntime) + static + `../pipeline/build_docx`；
  剔除未用的 `*_server.onnx` 大模型；`console=False` 不弹黑窗。
- `installer.iss`：按用户装到 `%LOCALAPPDATA%\Programs`（免 UAC），开始菜单 + 桌面快捷方式 + 卸载器，
  首装检查 WebView2 运行时（缺失可跑随包 bootstrapper）。中文向导需 `Languages\ChineseSimplified.isl`。

## 体积

- onedir：约 309 MB（含 ONNX 模型 ~37 MB、onnxruntime、opencc 词典、前端）。
- 安装包：约 111 MB（lzma2/max）。

## 阶段 2 验收（本机已过）

- 打包 exe `--ocr` 识别子进程：从 bundle 加载 PP-OCRv6 ONNX → 识别正常。
- frozen 服务 `--selftest`：`SELFTEST OK`（single 模式、设置 20 键）。
- 打包 exe 完整 E2E（`--serve` + HTTP）：上传 → 识别(子进程) → 导出 **合法 docx**（PK 魔数 + RFC5987 中文名）。
- 双击（无控制台）启动：窗口稳定存活、服务可达（已修 windowed 下 `sys.stdout=None` 致崩溃）。
- 安装包：静默安装 → 已装 exe 自检 → 卸载，全程正常；用户数据目录不被创建/删除。

## 待续（后续阶段）

- 阶段 3：联网激活授权（唯一云端组件，只碰授权码/机器指纹）。
- 阶段 4：单机产品化打磨（首启引导、错误提示、自动更新）。
- 阶段 6：代码签名（避 SmartScreen）、clean-VM 矩阵测、定价。
- 阶段 5：准确率二版（待用户测试集，经引擎接缝热插入）。
