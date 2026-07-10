# GlowFish Reader v1.0.3 修改说明

日期：2026-07-04

## 版本定位

v1.0.3 是一次面向协作接手的功能与 OCR 稳定性版本。重点是把默认识别链路切到官方 PP-OCRv6，本地补齐低召回兜底、噪声分层、目录管理、导入进度可观测性，以及批注合并导出。

## 这两天的主要修改

### 1. OCR 与导入链路

- 默认 OCR 引擎改为 `ppocrv6`，通过 `recognize_ppocrv6.py` 调用官方 PaddleOCR 本地引擎。
- `requirements-paddle.txt` 升级到 PaddleOCR/PaddleX 3.7.0，并保留 `onnx` 快速引擎作为兜底。
- 新增 `ocr_filter.py`，对英文水印、印章、页心/边栏目录碎片、低置信短噪声做保守标注。
- 新增 `ocr_rescue.py`，当 PP-OCRv6 对竖排史料召回偏低时，执行列级增强重识别与去重。
- `proof_model.py` 支持把噪声行保存到 `noise_lines`，默认不进入正文、导出和编辑顺序，但仍可保留排查信息。
- `content_api.py` 在 PP-OCRv6 召回明显不足时自动用 ONNX 重新识别，并记录 fallback 信息。
- 导入顶部提示拆成“正在导入素材”和“正在识别文字 N/M”，识别阶段显示引擎、百分比和估时；即使只有一个文件或识别很快，也会展示识别阶段。

### 2. 文件夹与导入体验

- 左侧文件夹支持新建子文件夹、重命名、递归删除、拖拽移动和同级排序。
- 导入新文件时，如果用户正在浏览旧文件，不再强制切换当前图片和文本，只登记到左侧目录，避免左右视图不一致。
- 左侧术语从“笔记本”调整为“文件夹”，更贴合目录管理。

### 3. 图片区与重识别交互

- 左侧“噪声”按钮移除。
- 识别切分框默认不显示，新增“框”按钮控制显示状态。
- 只有在识别框显示时，才允许 `Alt + 拖动` 框选区域重新识别；按钮 hover 文案已说明用法。
- 框选重识别走 `/api/reocr_region`，结果追加到当前页并写入撤销栈。

### 4. 批注导出

- 勾选“是否带批注笔记”后，导出不再生成正文和批注两个文件。
- DOCX 导出现在在正文中插入上标编号，并在文后生成“注释”区，形成单文件的论文脚注式批注。
- Markdown/TXT 导出也会把注释追加到同一个文件。

### 5. 协作与发布准备

- 版本号升到 `proofread/_version.py = 1.0.3`。
- 新增 PP-OCRv6 过滤设计与实施计划文档：`proofread/docs/superpowers/...`。
- `.gitignore` 增加 `.paddle_venv/`，避免本地 Paddle 虚拟环境误入库。

## 验证记录

已在本地完成：

```powershell
.\.venv\Scripts\python.exe -m pytest proofread -q
```

结果：`164 passed, 11 warnings`。警告来自 Pillow 未来弃用 `Image.Image.getdata`，不影响当前功能。

也完成了前端语法检查：

```powershell
node --check proofread\static\app.js
node --check proofread\static\viewer.js
node --check proofread\static\settings.js
```

## 同事接手注意

- 不要提交 `.venv/`、`.paddle_venv/`、`proofread/_work/`、`proofread/models/`、打包产物和本地授权数据库。
- GitHub 远端应设置为 `https://github.com/001Vincent/historcial-photo-detabase.git`。
- 如果要跑 PP-OCRv6，需要安装 `requirements-paddle.txt` 对应环境；快速兜底可继续用主 `.venv` 里的 ONNX 路径。
- 本地服务健康检查可用 `/api/me`、`/health`、`desktop_app.py --selftest`。
