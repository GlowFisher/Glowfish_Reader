# -*- coding: utf-8 -*-
"""Validate the desktop packaging environment without building anything."""
from importlib import metadata, util

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils.hooks import copy_metadata


BUNDLE_METADATA_DISTRIBUTIONS = (
    "Jinja2", "OpenCC", "PyYAML", "aistudio-sdk", "chardet", "colorlog",
    "filelock", "huggingface-hub", "imagesize", "lxml", "modelscope",
    "numpy", "opencv-contrib-python", "packaging", "pandas", "pillow",
    "prettytable", "py-cpuinfo", "pydantic", "pypdfium2", "python-bidi",
    "python-docx", "regex", "requests", "ruamel.yaml", "safetensors",
    "tokenizers", "tqdm", "typing-extensions", "ujson",
)

_IMPORT_NAMES = {
    "imagesize": "imagesize",
    "opencv-contrib-python": "cv2",
    "pyclipper": "pyclipper",
    "pypdfium2": "pypdfium2",
    "python-bidi": "bidi",
    "shapely": "shapely",
}


def ocr_core_distributions():
    """Return PaddleX's current ``ocr-core`` distribution requirements."""
    names = []
    for dep_spec in metadata.requires("paddlex") or ():
        req = Requirement(dep_spec)
        marker = req.marker
        if marker is None or "extra" not in str(marker):
            continue
        if marker.evaluate({"extra": "ocr-core"}):
            names.append(req.name)
    return tuple(dict.fromkeys(names))


def check_preflight():
    """Return ``(summary, failures)`` without mutating the environment."""
    failures = []
    try:
        paddlex_version = metadata.version("paddlex")
        paddleocr_version = metadata.version("paddleocr")
        required = ocr_core_distributions()
    except metadata.PackageNotFoundError as exc:
        return [], [f"missing build distribution: {exc.name}"]

    if not required:
        failures.append("PaddleX declares no ocr-core dependencies")

    bundled = {canonicalize_name(name) for name in BUNDLE_METADATA_DISTRIBUTIONS}
    bundled.update({canonicalize_name("pyclipper"), canonicalize_name("shapely")})
    uncovered = [name for name in required if canonicalize_name(name) not in bundled]
    if uncovered:
        failures.append("ocr-core metadata not covered by spec: " + ", ".join(uncovered))

    summary = [
        f"paddleocr={paddleocr_version}",
        f"paddlex={paddlex_version}",
        "ocr-core=" + ",".join(required),
    ]
    for dist_name in required:
        normalized = canonicalize_name(dist_name)
        module_name = _IMPORT_NAMES.get(normalized, normalized.replace("-", "_"))
        try:
            version = metadata.version(dist_name)
        except metadata.PackageNotFoundError:
            failures.append(f"missing distribution metadata: {dist_name}")
            continue
        if util.find_spec(module_name) is None:
            failures.append(f"module not importable: {module_name} ({dist_name})")
        try:
            entries = copy_metadata(dist_name)
        except Exception as exc:
            failures.append(f"PyInstaller cannot copy {dist_name} metadata: {exc}")
            continue
        if not entries or not any(
            str(dest).lower().endswith((".dist-info", ".egg-info"))
            for _source, dest in entries
        ):
            failures.append(f"PyInstaller returned no dist-info for {dist_name}")
        summary.append(f"{dist_name}={version}")
    core_names = {canonicalize_name(name) for name in required}
    for dist_name in BUNDLE_METADATA_DISTRIBUTIONS:
        if canonicalize_name(dist_name) in core_names:
            continue
        try:
            metadata.version(dist_name)
            entries = copy_metadata(dist_name)
        except Exception as exc:
            failures.append(f"bundle metadata unavailable for {dist_name}: {exc}")
            continue
        if not entries:
            failures.append(f"PyInstaller returned no metadata for {dist_name}")
    return summary, failures


def main():
    summary, failures = check_preflight()
    for item in summary:
        print(f"[preflight] {item}")
    if failures:
        for failure in failures:
            print(f"[preflight] FAIL: {failure}")
        return 1
    print("[preflight] OK: PaddleX ocr-core metadata is collectable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
