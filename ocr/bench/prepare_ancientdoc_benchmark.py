"""Create a deterministic, locally stored AncientDoc OCR acceptance subset.

The resulting files are for internal regression testing only.  They are not
packaged with the desktop application.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path


DATASET_ID = "ByteDance/AncientDoc"
DATASET_LICENSE = "CC0-1.0"
IMAGE_PREFIX = "imgs"
PAGE_NAME = re.compile(r"^(?P<book>.+?)(?P<page>page_\d+\.[^.]+)$")


def _rank(row: dict[str, str]) -> str:
    return hashlib.sha256(f"{row['type']}\0{row['name']}".encode("utf-8")).hexdigest()


def select_rows(label_csv: Path, count: int) -> list[dict[str, str]]:
    with label_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("OCR", "").strip()]
    if count < 1:
        raise ValueError("count must be positive")
    if len(rows) < count:
        raise ValueError(f"only {len(rows)} annotated pages are available, need {count}")

    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row)
    selected: list[dict[str, str]] = []
    for group in sorted(by_type.values(), key=lambda value: value[0]["type"]):
        selected.append(min(group, key=_rank))
        if len(selected) == count:
            return selected
    selected_names = {(row["type"], row["name"]) for row in selected}
    remaining = [row for row in rows if (row["type"], row["name"]) not in selected_names]
    selected.extend(sorted(remaining, key=_rank)[: count - len(selected)])
    return selected


def build_records(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    records = []
    for index, row in enumerate(rows, start=1):
        match = PAGE_NAME.match(row["name"])
        if not match:
            raise ValueError(f"unsupported AncientDoc page name: {row['name']}")
        source_path = f"{IMAGE_PREFIX}/{row['type']}/{match['book']}/{match['page']}"
        records.append(
            {
                "id": f"ancientdoc-{index:03d}",
                "source_dataset": DATASET_ID,
                "source_license": DATASET_LICENSE,
                "source_path": source_path,
                "image_path": f"images/{index:03d}{Path(row['name']).suffix.lower()}",
                "category": row["type"],
                "source_book": match["book"],
                "source_name": row["name"],
                "gold_text": row["OCR"],
            }
        )
    return records


def write_manifest(records: list[dict[str, str]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "benchmark.jsonl"
    manifest.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    (output_dir / "download-paths.txt").write_text(
        "\n".join(record["source_path"] for record in records) + "\n", encoding="utf-8"
    )
    (output_dir / "README.md").write_text(
        "# AncientDoc internal OCR acceptance subset\n\n"
        f"Source: `{DATASET_ID}` ({DATASET_LICENSE}).\n\n"
        "This subset is solely for internal OCR regression tests. It must not be bundled "
        "with the desktop application or redistributed as a separate dataset.\n\n"
        "`benchmark.jsonl` preserves the source OCR gold text. `download-paths.txt` is "
        "the exact source-image list used to materialize the subset.\n",
        encoding="utf-8",
    )


def materialize_images(records: list[dict[str, str]], output_dir: Path, downloaded_root: Path) -> None:
    for record in records:
        source = downloaded_root / record["source_path"]
        if not source.is_file():
            raise FileNotFoundError(f"downloaded source image missing: {source}")
        destination = output_dir / record["image_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record["image_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--downloaded-root", type=Path)
    args = parser.parse_args(argv)
    records = build_records(select_rows(args.labels, args.count))
    if args.downloaded_root:
        materialize_images(records, args.output_dir, args.downloaded_root)
    write_manifest(records, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
