# 竖排繁体史料 · 校对界面 v1 设计 spec

目标：把 PaddleOCR **待核初稿**（手写约九成对）经人工高效校对，导出**简体整理本** docx（对齐用户「输出样式」：A4/五号/宋体/首行缩进2字符）。打底 PaddleOCR，识别引擎升级后置（任务 #4）。

## 形态
本地 `FastAPI` + Chrome 单页，素材不出本机。
- **识别**（paddleocr env）：`recognize.py` 批量出每页逐行 `{text, box, score}` → `_recog.json`。server 子进程调用 paddleocr python，结果缓存。
- **校对 server**（codex env：fastapi+uvicorn+opencc+docx）：读 recog、读写 `proof.json`、导出 docx、本地自动加标点。

## 数据模型 `proof.json`（三稿纪律）
```
{ batch, pages:[ {
    page_id, image, width, height,
    lines:[ {id, text_draft(只读初稿), text(修订), box:[x1,y1,x2,y2], score, para_break, deleted} ],
    order:[line_id...]   # 阅读序,初始=右起重排(x降y升),可人工拖拽
} ] }
```
`text_draft` 永不被覆盖；`text` 是人工修订；导出用 `text`。

## 导入与校对动作（v1）
0. 导入：左上角源名可点 → 原生对话框选文件夹/文件(jpg/pdf) → `ingest.py` 摊平(PDF渲染) → 即时识别 → **默认简体辑录**
1. 行内改字（编辑 `text`）
2. 拖拽调阅读序（改 `order`，修多栏块串位——CER 高主因）
3. 合并/拆分行
4. 段落分隔（`para_break`，决定导出分段）
5. 删除行（`deleted`，镜像页/噪声）
6. 简/繁切换（`/api/convert` OpenCC 在位转换，默认简）；撤销/恢复（Ctrl+Z/Y）
7. 导出：`text` 按 `order`+`para_break` 拼 → `build_docx`；弹窗选本页/全部 → 原生选目标文件夹
（已删一键标点功能。）

低置信（score<阈值，默认0.85）高亮黄；点检测框↔定位行。
**省人工度量**：拼接初稿 vs 定稿编辑距离 → 改动字数/占比。

## 接口
- `GET /api/batch?dir=` 加载/新建 proof（缺 recog 则子进程识别）
- `GET /img/{page_id}` 原图
- `POST /api/save` 落盘修订
- 自动断句标点：导入后由本地古文标点模型处理
- `POST /api/export` 导出整理本 docx
- `GET /api/stats` 改动量

## 后置（非 v1）
镜像页 skip 工作流、繁简一对多复核 UI、视觉大模型识别升级（任务 #4）。

## 复用
`run_paddle.py`(识别内核) · `build_docx.py`(导出)。
