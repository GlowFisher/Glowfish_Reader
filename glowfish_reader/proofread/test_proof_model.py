# -*- coding: utf-8 -*-
"""proof_model 核心单测：竖列聚合/阅读序/拼装/分段/删除/导出/度量。

注意：build_proof 会先经 aggregate_columns 把「同一竖列被 OCR 切碎的多块」合并成单行
（竖行兜底聚合，自 v3 起的既定行为）。故下面阅读序/拼装类用例刻意用三个 x 方向互不重叠
的独立竖列，避免聚合干扰；聚合本身由 test_aggregate_columns_* 单独覆盖。
"""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import proof_model as M
from docx import Document
import tempfile, os

# 构造 3 列竖排，x 互不重叠（不触发竖列聚合）：右列 x≈100(最前) / 中列 x≈65 / 左列 x≈30(最后)
RECOG = {
    "p1": {"image": "p1.png", "width": 200, "height": 300, "lines": [
        {"text": "左列", "box": [20, 10, 40, 80], "score": 0.99},   # 左,最后
        {"text": "中列", "box": [55, 10, 75, 80], "score": 0.60},   # 中,低置信
        {"text": "右列", "box": [90, 10, 110, 80], "score": 0.98},  # 右,最前
    ]}
}

def test_default_order_rtl():
    proof = M.build_proof(RECOG, "t")
    order = proof["pages"][0]["order"]
    ids = {l["id"]: l["text"] for l in proof["pages"][0]["lines"]}
    seq = [ids[i] for i in order]
    assert seq == ["右列", "中列", "左列"], seq           # 右起栏序
    print("OK default_order_rtl:", seq)

def test_assemble_and_export():
    proof = M.build_proof(RECOG, "t")
    pg = proof["pages"][0]
    # 修订：右列设为段落结尾；中列改字；删除左列
    for l in pg["lines"]:
        if l["text"] == "右列":
            l["para_break"] = True
        elif l["text"] == "中列":
            l["text"] = "中列改"
        elif l["text"] == "左列":
            l["deleted"] = True
    paras = M.assemble_paragraphs(proof)
    assert paras == ["右列", "中列改"], paras              # 分段(右列后断) + 删除(左列) + 改字
    print("OK assemble (分段+删除+改字):", paras)
    # 导出 docx（t2s 对纯简文本无碍）
    out = os.path.join(tempfile.gettempdir(), "_test_proof.docx")
    M.export_docx(proof, out, t2s=True)
    doc = Document(out)
    got = [p.text for p in doc.paragraphs if p.text.strip()]
    assert got == ["右列", "中列改"], got
    print("OK export_docx:", got)
    os.remove(out)

def test_edit_stats():
    proof = M.build_proof(RECOG, "t")
    pg = proof["pages"][0]
    for l in pg["lines"]:
        if l["text"] == "中列":
            l["text"] = "中列改"
    st = M.edit_stats(proof)
    assert st["edit_distance"] >= 1, st
    assert 0 <= st["changed_ratio"] <= 1, st
    print("OK edit_stats:", st)

def test_aggregate_columns_merges_same_column():
    # 同一竖列被 OCR 切成上下两块 → 合并为单块(留底碎块)；另一列保持独立
    raw = [
        {"text": "上", "box": [90, 10, 110, 80], "score": 0.9},
        {"text": "下", "box": [88, 90, 112, 160], "score": 0.7},  # 与「上」同列(x 高度重叠)
        {"text": "旁", "box": [20, 10, 40, 80], "score": 0.95},   # 另一列
    ]
    merged = M.aggregate_columns(raw)
    assert len(merged) == 2, merged
    assert {m["text"] for m in merged} == {"上下", "旁"}, merged
    col = next(m for m in merged if m["text"] == "上下")
    assert col["member_texts"] == ["上", "下"]               # 列内自上而下拼字 + 留底
    assert col["score"] == 0.7                                # 列内取最低分(保守)
    print("OK aggregate_columns:", [m["text"] for m in merged])

if __name__ == "__main__":
    test_default_order_rtl()
    test_assemble_and_export()
    test_edit_stats()
    test_aggregate_columns_merges_same_column()
    print("\nALL PASS")



def test_build_proof_ignores_internal_recog_meta():
    recog = {
        "_meta": {"engine": "ppocrv6_high", "engine_config_hash": "abc"},
        "p001": {"image": "p001.jpg", "width": 100, "height": 100, "lines": [
            {"text": "\u6b63\u6587", "box": [1, 2, 3, 4], "score": 0.9}
        ]},
    }

    proof = M.build_proof(recog, "batch", engine="ppocrv6_high")

    assert [page["page_id"] for page in proof["pages"]] == ["p001"]
