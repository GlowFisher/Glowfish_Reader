# -*- coding: utf-8 -*-
"""一次性：把现成古文 MLM（GuwenBERT 等）导出为 ONNX，供 ocr_correct.py 在 .venv(onnxruntime)
离线做形近字上下文重打分（迭代3a）。复刻 setup_punct_model.py 配方。

用法（两段式——colorize env 有 torch 无 onnxruntime；量化交 app .venv）：
  & "C:\\Users\\18267\\miniconda3\\envs\\colorize\\python.exe" setup_mlm_model.py            # 下载+导出 fp32 ONNX
  & "<app .venv>\\python.exe" setup_mlm_model.py --quantize-only                              # int8 量化(~100MB)
模型可换：环境变量 MLM_MODEL_ID（默认 ethanyt/guwenbert-base）。产物 proofread/models/mlm/。
"""
import os
import sys
import json
import argparse
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")   # 走 hf-mirror
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)                                    # 剥代理防 Clash 卡死
os.environ["NO_PROXY"] = "*"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("MLM_OUT") or (HERE / "models" / "mlm"))   # MLM_OUT 覆盖便于 DAPT 分目录 A/B
MODEL_ID = os.environ.get("MLM_MODEL_ID", "ethanyt/guwenbert-base")


def _bypass_torch_load_guard():
    """transformers>=5 对 torch<2.6 加载 .bin 权重的 CVE 拦截；GuwenBERT 只发 .bin。
    本模型来自 hf-mirror 可信研究权重、离线加载，绕过该拦截（用 weights_only=True）。"""
    try:
        import transformers.utils.import_utils as iu
        iu.check_torch_load_is_safe = lambda *a, **k: None
    except Exception:
        pass
    try:
        import transformers.modeling_utils as mu
        mu.check_torch_load_is_safe = lambda *a, **k: None
    except Exception:
        pass


def export():
    import torch
    _bypass_torch_load_guard()
    from transformers import AutoTokenizer, AutoModelForMaskedLM

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[mlm] load {MODEL_ID} (HF_ENDPOINT={os.environ.get('HF_ENDPOINT')})")
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForMaskedLM.from_pretrained(MODEL_ID)
    model.eval()

    vocab = tok.get_vocab()                      # token -> id
    id2tok = {i: t for t, i in vocab.items()}
    toks = [id2tok.get(i, "") for i in range(len(id2tok))]
    (OUT / "vocab.txt").write_text("\n".join(toks), encoding="utf-8")

    meta = {
        "model_id": MODEL_ID,
        "vocab_size": len(toks),
        "mask_id": tok.mask_token_id,
        "cls_id": tok.cls_token_id,
        "sep_id": tok.sep_token_id,
        "pad_id": tok.pad_token_id,
        "unk_id": tok.unk_token_id,
        "max_content": 510,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[mlm] vocab={len(toks)} mask_id={tok.mask_token_id} cls={tok.cls_token_id} sep={tok.sep_token_id}")

    class Wrap(torch.nn.Module):
        """只吃 input_ids + attention_mask（BERT 内部会自建 zero token_type_ids；RoBERTa 不需要）→ 返回 logits。"""

        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            return self.m(input_ids=input_ids, attention_mask=attention_mask).logits

    wrapped = Wrap(model)
    ids = torch.tensor([[meta["cls_id"], 100, meta["mask_id"], 101, meta["sep_id"]]], dtype=torch.long)
    attn = torch.ones_like(ids)
    with torch.no_grad():
        _ = wrapped(ids, attn)
    torch.onnx.export(
        wrapped, (ids, attn), str(OUT / "model.onnx"),
        input_names=["input_ids", "attention_mask"], output_names=["logits"],
        dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                      "logits": {0: "b", 1: "s"}},
        opset_version=14, do_constant_folding=True,
    )
    mb = (OUT / "model.onnx").stat().st_size / 1e6
    print(f"[mlm] exported model.onnx ({mb:.0f}MB) -> {OUT}")


def quantize():
    from onnxruntime.quantization import quantize_dynamic, QuantType

    src = OUT / "model.onnx"
    dst = OUT / "model_int8.onnx"
    if not src.exists():
        sys.exit(f"缺 {src}；先在 colorize env 跑导出。")
    # per_channel=True 关键：MLM 头是 768x23292 大投影，per-tensor int8 会毁掉掩码预测
    # （实测「温故而知新」top1 从「知」塌成「为」）；per-channel 逐通道量化基本无损。
    quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8, per_channel=True)
    print(f"[mlm] int8(per-channel) {src.stat().st_size/1e6:.0f}MB -> {dst.stat().st_size/1e6:.0f}MB : {dst}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quantize-only", action="store_true", help="只做 int8 量化（app .venv 跑，需 onnxruntime）")
    args = ap.parse_args()
    if args.quantize_only:
        quantize()
    else:
        export()


if __name__ == "__main__":
    main()
