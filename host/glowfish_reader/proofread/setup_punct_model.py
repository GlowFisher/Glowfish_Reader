# -*- coding: utf-8 -*-
"""一次性：把古文标点模型导出为 ONNX，供 punctuate_local.py 在 .venv(onnxruntime) 离线跑。

⚠ 本脚本需 **transformers + torch + onnx**，不在产品 .venv 跑，用带 torch 的环境，例如：
    & "C:\\Users\\18267\\miniconda3\\envs\\colorize\\python.exe" setup_punct_model.py
（colorize/CC-train 等含 torch 的 conda 环境；torch.onnx.export 需 onnx 包，缺则 pip install onnx）

模型：raynardj/classical-chinese-punctuation-guwen-biaodian（BERT token 分类，
label = 该字之后应插入的现代标点；'O'=不插）。经 hf-mirror 绕代理下载。
产物落 proofread/models/punct/：model.onnx + vocab.txt + meta.json（.gitignore，不入库）。
"""
import os
import sys
import json
from pathlib import Path

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"           # 国内镜像
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)                                    # 绕 Clash 直连镜像
os.environ["NO_PROXY"] = "*"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MODEL = "raynardj/classical-chinese-punctuation-guwen-biaodian"
OUT = Path(__file__).resolve().parent / "models" / "punct"


def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    OUT.mkdir(parents=True, exist_ok=True)
    print("下载/加载:", MODEL)
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForTokenClassification.from_pretrained(MODEL).eval()

    # vocab.txt（按 id 顺序，供 .venv 极简字级分词）
    id2tok = {i: t for t, i in tok.get_vocab().items()}
    with open(OUT / "vocab.txt", "w", encoding="utf-8") as f:
        for i in range(len(id2tok)):
            f.write(id2tok[i] + "\n")

    meta = {
        "model": MODEL,
        "id2label": {int(k): v for k, v in model.config.id2label.items()},
        "max_content": 510,
        "cls_id": tok.cls_token_id, "sep_id": tok.sep_token_id,
        "unk_id": tok.unk_token_id, "pad_id": tok.pad_token_id or 0,
    }
    json.dump(meta, open(OUT / "meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask, token_type_ids):
            return self.m(input_ids=input_ids, attention_mask=attention_mask,
                          token_type_ids=token_type_ids).logits

    enc = tok("子曰學而時習之不亦說乎", return_tensors="pt")
    args = (enc["input_ids"], enc["attention_mask"], enc["token_type_ids"])
    torch.onnx.export(
        Wrap(model).eval(), args, str(OUT / "model.onnx"),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                      "token_type_ids": {0: "b", 1: "s"}, "logits": {0: "b", 1: "s"}},
        opset_version=14, do_constant_folding=True)
    sz = (OUT / "model.onnx").stat().st_size / 1e6
    print(f"完成 → {OUT}  (model.onnx {sz:.0f}MB, vocab {len(id2tok)}, labels {len(meta['id2label'])})")
    quantize()


def quantize():
    """动态量化 int8（388MB→~97MB）；punctuate_local 优先加载 model_int8.onnx。
    实测断句 F1 与 fp32 持平（bench/eval_punct.py --int8-ab，报告 bench/out/punct_report.md）。
    需 onnx 包；可在任何有 onnxruntime+onnx 的环境单独跑：python setup_punct_model.py --quantize-only"""
    from onnxruntime.quantization import quantize_dynamic, QuantType
    src, dst = OUT / "model.onnx", OUT / "model_int8.onnx"
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    print(f"量化完成 → {dst.name} ({dst.stat().st_size / 1e6:.0f}MB)")


if __name__ == "__main__":
    import sys as _sys
    if "--quantize-only" in _sys.argv:
        quantize()
    else:
        main()
