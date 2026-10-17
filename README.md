# Glowfish Reader（史料阅读器）

一款**完全本地化运行**的开源史料 OCR 阅读器。面向历史文献 / 古籍的数字化阅读与点校（校对）场景：在本地离线完成 OCR 识别、竖排（右起栏序）排版还原、繁简转换、自动断句与语义纠错，提供点校工作台，并可导出 Word 文档。

> **本地运行 · 永不上云**：图片、文本与批注全部落本机磁盘，OCR 与模型全部本地推理，无任何云端依赖、无需登录。

## 功能特性

- **本地 OCR**：集成 PP-OCRv6（ONNX Runtime 推理），支持古籍繁体竖排。
- **竖排右起栏序还原**：针对古籍「从右往左、竖列」版面做列检测与读序排序。
- **多层后处理**：形近字纠错、古文本地断句（punct 模型）、上下文语义纠错（mlm 模型）、域词典修复。
- **点校工作台**：整页 / 逐行点校、双行夹注、简繁一键切换、批注与导出。
- **断点续识**：大型古籍逐页 checkpoint 保存、重启续识、失败引擎接续。
- **完全离线**：无登录、无授权门，数据落 `%APPDATA%`（打包态）或本地数据目录。

## 仓库结构

本仓库为**单一 monorepo**，所有组件（host / ui / ocr / contracts）同仓管理：

| 目录 | 职责 |
|---|---|
| `host/` | Windows 桌面集成与打包（pywebview 壳 + 内嵌 FastAPI + 校对/文档/导出服务） |
| `ui/` | 阅读器前端（原生 HTML/CSS/JS，构建产物 `dist/` 被 host 消费） |
| `ocr/` | OCR 服务与公共 API（`glowfish_ocr` 包，纯本地独立） |
| `contracts/` | 跨组件共享契约（JSON Schema / OpenAPI） |
| `scripts/` | 工作区校验、模型下载等引导脚本 |
| `docs/` | 模型清单（`MODELS.md`）等文档 |

克隆完整产品工作区：

```powershell
git clone <your-repo-url>
```

> 原仓库地址已随开源发布脱敏，请替换为你的公开仓库地址。

## 外部资源

OCR 模型与安装器**有意排除在 Git 之外**：

- 模型统一存放于 `host/glowfish_reader/proofread/models/`（可用 `GLOWFISH_OCR_MODELS` 覆盖）。
- `ocr/models.lock.json` 定义所需模型路径、大小、哈希与下载/构建来源。
- 运行 `bootstrap.ps1` 会自动**检测缺失模型 → 下载 → 校验**（PP-OCRv6 可直接下载，
  mlm / punct 需本地导出）。详见 [docs/MODELS.md](docs/MODELS.md)。
- 安装器与 `update.json` 在 `releases/` 下生成。

## 环境要求

- Windows x64
- Python 3.12（服务端）+ 3.10（OCR 识别子进程 conda env）
- Node.js 22 / npm
- Inno Setup 6（构建安装器时）

## 快速开始

```powershell
# 引导：创建 .venv、安装模块、构建 UI、检测并下载模型、校验工作区
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1

# 验证
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify.ps1 -Full
```

模型获取与校验详见 [docs/MODELS.md](docs/MODELS.md)。

配置说明见 [`.env.example`](.env.example)。

## 构建安装器

```powershell
$env:GLOWFISH_OCR_MODELS = "D:\path\to\verified\models"
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1 -Notes "..."
```

## 协作贡献

- 请勿提交模型、安装器、数据库、凭据、用户文件、构建产物或本地环境。
- 使用功能分支 + 评审过的 Pull Request。
- 本仓库统一管理产品版本与 Releases；各组件在对应子目录内开发与测试。
- 详见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

本项目以 [GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0）开源发布。
