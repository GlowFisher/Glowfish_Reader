"""Classify CPU/CUDA OCR parity differences without changing OCR output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _box(line: dict) -> tuple[float, ...]:
    return tuple(round(float(value), 3) for value in line.get("box", []))


def diagnose(cpu: dict, cuda: dict) -> dict:
    if set(cpu) != set(cuda):
        raise ValueError("CPU and CUDA page ids differ")
    pages = []
    for page_id in sorted(cpu):
        cpu_lines = cpu[page_id].get("lines", [])
        cuda_lines = cuda[page_id].get("lines", [])
        compared = min(len(cpu_lines), len(cuda_lines))
        box_matches = sum(_box(cpu_lines[index]) == _box(cuda_lines[index]) for index in range(compared))
        text_matches = sum(
            str(cpu_lines[index].get("text") or "") == str(cuda_lines[index].get("text") or "")
            for index in range(compared)
        )
        if len(cpu_lines) != len(cuda_lines):
            kind = "line_count_changed"
        elif box_matches == compared and text_matches != compared:
            kind = "recognition_only"
        elif text_matches == compared and box_matches != compared:
            kind = "geometry_only"
        elif text_matches != compared or box_matches != compared:
            kind = "mixed_detection_recognition"
        else:
            kind = "exact"
        pages.append(
            {
                "id": page_id,
                "kind": kind,
                "cpu_lines": len(cpu_lines),
                "cuda_lines": len(cuda_lines),
                "box_matches_at_index": box_matches,
                "text_matches_at_index": text_matches,
                "cpu_sources": sorted({line.get("source") for line in cpu_lines}),
                "cuda_sources": sorted({line.get("source") for line in cuda_lines}),
            }
        )
    return {
        "pages": pages,
        "summary": {
            kind: sum(page["kind"] == kind for page in pages)
            for kind in sorted({page["kind"] for page in pages})
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", type=Path, required=True)
    parser.add_argument("--cuda", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = diagnose(
        json.loads(args.cpu.read_text(encoding="utf-8")),
        json.loads(args.cuda.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
