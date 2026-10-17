from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENTRY = ROOT / "glowfish_reader" / "proofread" / "desktop_app.py"
DEFAULT_FIXTURE = ROOT / "components" / "ocr" / "bench" / "fixtures" / "vertical_cht_clean.png"


def evaluate_reports(
    legacy: dict,
    component: dict,
    *,
    max_warm_ratio: float,
    max_prewarm_ratio: float,
    max_rss_growth_mb: float,
    baseline_label: str = "legacy",
    candidate_label: str = "component",
) -> list[str]:
    failures = []
    for name, report in ((baseline_label, legacy), (candidate_label, component)):
        if report.get("line_count", 0) < 1:
            failures.append(f"{name} produced no OCR lines")
        if not report.get("worker_reused"):
            failures.append(f"{name} did not reuse its prewarmed worker")
        if not report.get("idle_released"):
            failures.append(f"{name} did not release its idle worker")
    if legacy.get("fingerprint") != component.get("fingerprint"):
        failures.append("legacy/component OCR output fingerprints differ")

    legacy_warm = float(legacy.get("warm_median_seconds") or 0)
    component_warm = float(component.get("warm_median_seconds") or 0)
    if legacy_warm <= 0 or component_warm > legacy_warm * max_warm_ratio:
        failures.append(
            f"{candidate_label} warm median {component_warm:.4f}s exceeds "
            f"{baseline_label} {legacy_warm:.4f}s * {max_warm_ratio:.2f}"
        )

    legacy_prewarm = float(legacy.get("prewarm_seconds") or 0)
    component_prewarm = float(component.get("prewarm_seconds") or 0)
    if legacy_prewarm <= 0 or component_prewarm > legacy_prewarm * max_prewarm_ratio:
        failures.append(
            f"{candidate_label} prewarm {component_prewarm:.4f}s exceeds "
            f"{baseline_label} {legacy_prewarm:.4f}s * {max_prewarm_ratio:.2f}"
        )

    component_growth = float(component.get("rss_growth_mb") or 0)
    legacy_growth = float(legacy.get("rss_growth_mb") or 0)
    if component_growth > legacy_growth + max_rss_growth_mb:
        failures.append(
            f"{candidate_label} RSS growth {component_growth:.2f}MB exceeds "
            f"{baseline_label} {legacy_growth:.2f}MB + {max_rss_growth_mb:.2f}MB"
        )
    return failures


def _display_output(value: bytes | str | None) -> str:
    """Keep a child-process encoding error from hiding its real exit status."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _command(args, mode: str, output: Path, *, component_provider: str | None = None) -> list[str]:
    common = [
        "--benchmark-ocr-runtime",
        "--mode",
        mode,
        "--fixture",
        str(args.fixture),
        "--output",
        str(output),
        "--iterations",
        str(args.iterations),
        "--idle-ttl",
        str(args.idle_ttl),
        "--idle-wait",
        str(args.idle_wait),
    ]
    if mode == "component":
        provider = component_provider or args.component_provider
        common += ["--provider", provider]
        if provider == "cuda":
            common += ["--gpu-runtime-dir", str(args.gpu_runtime_dir)]
            if args.gpu_runtime_version:
                common += ["--gpu-runtime-version", args.gpu_runtime_version]
        if args.model_root:
            common += ["--model-root", str(args.model_root)]
    if args.executable:
        return [str(args.executable), *common]
    return [str(args.python), str(args.entry), *common]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--entry", type=Path, default=DEFAULT_ENTRY)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--idle-ttl", type=float, default=1.0)
    parser.add_argument("--idle-wait", type=float, default=1.5)
    parser.add_argument("--max-warm-ratio", type=float, default=1.15)
    parser.add_argument("--max-prewarm-ratio", type=float, default=1.25)
    parser.add_argument("--max-rss-growth-mb", type=float, default=256.0)
    parser.add_argument("--component-provider", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--gpu-runtime-dir", type=Path)
    parser.add_argument("--gpu-runtime-version")
    parser.add_argument("--model-root", type=Path)
    args = parser.parse_args(argv)

    args.python = args.python.resolve()
    args.entry = args.entry.resolve()
    args.fixture = args.fixture.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.executable:
        args.executable = args.executable.resolve()
    if args.component_provider == "cuda" and args.gpu_runtime_dir is None:
        parser.error("--gpu-runtime-dir is required when --component-provider=cuda")
    if args.gpu_runtime_dir:
        args.gpu_runtime_dir = args.gpu_runtime_dir.resolve()
    if args.model_root:
        args.model_root = args.model_root.resolve()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["SHUPAI_PREWARM_OCR"] = "0"
    runs = [("legacy", "legacy", None), ("component", "component", args.component_provider)]
    # Source checkouts can lack the frozen desktop model payload.  In that case
    # compare component CPU and CUDA against the explicit same locked models.
    if args.component_provider == "cuda" and args.model_root:
        runs = [("cpu_component", "component", "cpu"), ("cuda_component", "component", "cuda")]
    reports = {}
    for label, mode, component_provider in runs:
        output = args.output_dir / f"{label}.json"
        result = subprocess.run(
            _command(args, mode, output, component_provider=component_provider),
            cwd=str(ROOT / "glowfish_reader" / "proofread"),
            env=env,
            capture_output=True,
        )
        if result.returncode != 0:
            print(_display_output(result.stdout))
            print(_display_output(result.stderr), file=sys.stderr)
            raise SystemExit(f"{label} benchmark failed: {result.returncode}")
        reports[label] = json.loads(output.read_text(encoding="utf-8"))

    baseline_label, candidate_label = runs[0][0], runs[1][0]

    failures = evaluate_reports(
        reports[baseline_label],
        reports[candidate_label],
        max_warm_ratio=args.max_warm_ratio,
        max_prewarm_ratio=args.max_prewarm_ratio,
        max_rss_growth_mb=args.max_rss_growth_mb,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
    )
    summary = {
        "schema_version": 1,
        "target": str(args.executable or args.entry),
        "baseline": reports[baseline_label],
        "component": reports[candidate_label],
        "baseline_label": baseline_label,
        "component_label": candidate_label,
        "component_provider": args.component_provider,
        "thresholds": {
            "max_warm_ratio": args.max_warm_ratio,
            "max_prewarm_ratio": args.max_prewarm_ratio,
            "max_rss_growth_mb": args.max_rss_growth_mb,
        },
        "failures": failures,
        "ok": not failures,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
