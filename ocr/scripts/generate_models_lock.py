from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = [
    "ppocrv6_onnx/det/inference.json",
    "ppocrv6_onnx/det/inference.onnx",
    "ppocrv6_onnx/det/inference.yml",
    "ppocrv6_onnx/rec/inference.json",
    "ppocrv6_onnx/rec/inference.onnx",
    "ppocrv6_onnx/rec/inference.yml",
    "punct/meta.json",
    "punct/model_int8.onnx",
    "punct/vocab.txt",
    "mlm/meta.json",
    "mlm/model_int8.onnx",
    "mlm/vocab.txt",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("models.lock.json"))
    args = parser.parse_args()
    files = []
    for relative in REQUIRED:
        path = args.model_root / relative
        if not path.is_file():
            raise SystemExit(f"required model asset missing: {relative}")
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    payload = {"schema_version": 1, "component": "glowfish-ocr", "source": "local-curated-v1", "files": files}
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
