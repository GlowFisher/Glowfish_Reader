import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bench" / "prepare_ancientdoc_benchmark.py"
SPEC = importlib.util.spec_from_file_location("prepare_ancientdoc_benchmark", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_subset_is_deterministic_and_includes_each_category(tmp_path):
    labels = tmp_path / "label.csv"
    labels.write_text(
        "type,name,OCR\nA,bookpage_1.png,甲\nA,bookpage_2.png,乙\nB,otherpage_1.png,丙\nB,otherpage_2.png,丁\n",
        encoding="utf-8",
    )

    records = MODULE.build_records(MODULE.select_rows(labels, 3))
    MODULE.write_manifest(records, tmp_path / "subset")

    assert len(records) == 3
    assert {record["category"] for record in records} == {"A", "B"}
    assert all(record["source_path"].startswith("imgs/") for record in records)
    manifest = [json.loads(line) for line in (tmp_path / "subset" / "benchmark.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest == records
    assert len((tmp_path / "subset" / "download-paths.txt").read_text(encoding="utf-8").splitlines()) == 3
