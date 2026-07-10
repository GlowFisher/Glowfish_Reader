# -*- coding: utf-8 -*-
"""Phase 0 冒烟测试：验证 paddleocr 环境能否识别【竖排繁体】。

流程：渲染一张已知 ground truth 的竖排繁体 fixture -> PaddleOCR(lang=chinese_cht)
-> 打印识别结果 + 字级覆盖率，初判引擎对竖排繁体是否堪用。

注意：这是【合成清晰文本】的链路验证，不是正式基准。真实基准须用用户的金标准扫描件
（真实报纸/日记有噪声、倾斜、版心复杂，准确率会显著低于本测试）。
"""
import os
import sys
import json
from pathlib import Path

# 防 Windows 控制台 GBK 崩繁体/生僻字（用户既知坑）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)

# ---------- 1. 渲染竖排繁体 fixture（已知 ground truth）----------
from PIL import Image, ImageDraw, ImageFont

# 优先选繁体取向字体
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\kaiu.ttf",      # 標楷體 (traditional)
    r"C:\Windows\Fonts\mingliu.ttc",   # 細明體 (traditional)
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体（含繁体字形）
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
]
font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
if not font_path:
    print("NO_CJK_FONT_FOUND")
    sys.exit(2)
print("font:", font_path)

# 竖排：每列自上而下；列序自右而左（繁体报纸/古籍惯例）。右列在前。
COLUMNS = ["民國二十七年武漢會戰", "四萬萬人民共赴國難"]
FONT_SIZE = 56
PAD = 40
LINE_GAP = 8
COL_W = FONT_SIZE + 34

font = ImageFont.truetype(font_path, FONT_SIZE)
n_rows = max(len(c) for c in COLUMNS)
img_w = PAD * 2 + COL_W * len(COLUMNS)
img_h = PAD * 2 + n_rows * (FONT_SIZE + LINE_GAP)
img = Image.new("RGB", (img_w, img_h), "white")
draw = ImageDraw.Draw(img)

for ci, col in enumerate(COLUMNS):  # ci=0 是最右列
    x = img_w - PAD - COL_W * (ci + 1) + (COL_W - FONT_SIZE) // 2
    for ri, ch in enumerate(col):
        y = PAD + ri * (FONT_SIZE + LINE_GAP)
        draw.text((x, y), ch, fill="black", font=font)

fixture_path = FIX / "vertical_cht_clean.png"
img.save(fixture_path)
GROUND_TRUTH = "".join(COLUMNS)  # 右起阅读顺序
(FIX / "vertical_cht_clean.gt.json").write_text(
    json.dumps({"columns": COLUMNS, "reading_order_rtl": GROUND_TRUTH}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("fixture:", fixture_path, img.size)
print("ground_truth(RTL):", GROUND_TRUTH)

# ---------- 2. PaddleOCR 识别 ----------
from paddleocr import PaddleOCR

print("instantiating PaddleOCR(lang='chinese_cht') ...")
try:
    ocr = PaddleOCR(lang="chinese_cht", use_textline_orientation=True)
except Exception as e:
    print("ctor(use_textline_orientation) failed -> retry plain:", repr(e))
    ocr = PaddleOCR(lang="chinese_cht")

print("running prediction (首次会下载模型) ...")
texts = []
try:
    res = ocr.predict(str(fixture_path))
    print("num_results:", len(res))
    for i, r in enumerate(res):
        dd = None
        try:
            dd = r.json
        except Exception:
            pass
        if isinstance(dd, dict):
            inner = dd.get("res", dd)
            rec = inner.get("rec_texts")
            scores = inner.get("rec_scores")
            print(f"[{i}] rec_texts:", rec)
            print(f"[{i}] rec_scores:", scores)
            if rec:
                texts.extend(rec)
        else:
            print(f"[{i}] raw(first1000):", str(r)[:1000])
except AttributeError as e:
    print("predict() unavailable, trying legacy .ocr():", repr(e))
    res = ocr.ocr(str(fixture_path))
    print("legacy result(first2000):", str(res)[:2000])
except Exception as e:
    print("PREDICT_ERROR:", repr(e))

# ---------- 3. 粗判 ----------
joined = "".join(texts)
print("recognized_joined:", joined)
gt_chars = set(GROUND_TRUTH)
hit = sum(1 for ch in gt_chars if ch in joined)
print(f"char_coverage: {hit}/{len(gt_chars)} unique GT chars present in output")
print("DONE")
