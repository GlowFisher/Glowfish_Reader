"""Compare CPU/CUDA OCR outputs and source gold text for a fixed corpus."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]


def _lines(page: dict) -> list[tuple[str, tuple[float, ...]]]:
    return [
        (str(line.get("text") or ""), tuple(round(float(value), 3) for value in line.get("box", [])))
        for line in page.get("lines", [])
    ]


def _gold_by_id(manifest: Path) -> dict[str, str]:
    return {
        Path(record["image_path"]).stem: str(record["gold_text"])
        for record in (json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line)
    }


def compare(cpu: dict, cuda: dict, gold: dict[str, str]) -> dict:
    if set(cpu) != set(cuda):
        raise ValueError("CPU and CUDA output page ids differ")
    pages = []
    total_gold_chars = total_cpu_distance = total_cuda_distance = 0
    for page_id in sorted(cpu):
        cpu_page, cuda_page = cpu[page_id], cuda[page_id]
        cpu_lines, cuda_lines = _lines(cpu_page), _lines(cuda_page)
        cpu_text = "".join(text for text, _box in cpu_lines)
        cuda_text = "".join(text for text, _box in cuda_lines)
        expected = _compact(gold.get(page_id, ""))
        if not expected:
            raise ValueError(f"missing gold text for page: {page_id}")
        cpu_distance = _distance(_compact(cpu_text), expected)
        cuda_distance = _distance(_compact(cuda_text), expected)
        total_gold_chars += len(expected)
        total_cpu_distance += cpu_distance
        total_cuda_distance += cuda_distance
        pages.append(
            {
                "id": page_id,
                "cpu_provider": cpu_page.get("ocr_meta", {}).get("provider"),
                "cuda_provider": cuda_page.get("ocr_meta", {}).get("provider"),
                "cpu_lines": len(cpu_lines),
                "cuda_lines": len(cuda_lines),
                "text_exact": [text for text, _box in cpu_lines] == [text for text, _box in cuda_lines],
                "geometry_exact": cpu_lines == cuda_lines,
                "cpu_gold_distance": cpu_distance,
                "cuda_gold_distance": cuda_distance,
            }
        )
    return {
        "pages": pages,
        "summary": {
            "pages": len(pages),
            "cpu_providers": sorted({page["cpu_provider"] for page in pages}),
            "cuda_providers": sorted({page["cuda_provider"] for page in pages}),
            "text_exact_pages": sum(page["text_exact"] for page in pages),
            "geometry_exact_pages": sum(page["geometry_exact"] for page in pages),
            "cpu_gold_cer": round(total_cpu_distance / total_gold_chars, 6),
            "cuda_gold_cer": round(total_cuda_distance / total_gold_chars, 6),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", type=Path, required=True)
    parser.add_argument("--cuda", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(
        json.loads(args.cpu.read_text(encoding="utf-8")),
        json.loads(args.cuda.read_text(encoding="utf-8")),
        _gold_by_id(args.manifest),
    )
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
