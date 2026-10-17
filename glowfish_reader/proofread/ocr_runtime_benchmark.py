"""Structured OCR runtime benchmark for source and frozen desktop builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

import content_api
import ocr_component_runtime


def _result_summary(path: Path) -> tuple[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    normalized = {}
    for key, value in data.items():
        if key == "_meta":
            continue
        if isinstance(value, dict):
            value = dict(value)
            if value.get("image"):
                value["image"] = Path(str(value["image"])).name
            meta = value.get("ocr_meta")
            if isinstance(meta, dict):
                # Provider identity and timings prove acceleration separately;
                # they must not make repeated OCR quality runs look different.
                value["ocr_meta"] = {
                    name: item for name, item in meta.items()
                    if name not in {
                        "provider", "requested_provider", "device", "device_name",
                        "runtime_version", "stage_timings_ms", "attempt",
                    }
                }
        normalized[key] = value
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    lines = sum(
        len(page.get("lines") or ())
        for page in normalized.values()
        if isinstance(page, dict)
    )
    return hashlib.sha256(payload).hexdigest(), lines


def _rss_tree_mb() -> float:
    root = psutil.Process()
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.Error, OSError):
        pass
    total = 0
    for process in processes:
        try:
            total += process.memory_info().rss
        except (psutil.Error, OSError):
            pass
    return round(total / (1024 * 1024), 2)


def _worker_state(mode: str, runner) -> tuple[int | None, bool]:
    if mode == "legacy":
        worker = content_api._WORKER
    else:
        service = getattr(runner, "_service", None)
        worker = getattr(service, "_worker", None)
    if worker is None:
        return None, False
    try:
        return getattr(worker, "pid", None), bool(worker.alive())
    except Exception:
        return getattr(worker, "pid", None), False


def run_benchmark(
    *,
    mode: str,
    fixture: Path,
    iterations: int,
    engine: str,
    idle_ttl_seconds: float,
    idle_wait_seconds: float,
    provider_config: dict | None = None,
) -> dict:
    if mode not in {"legacy", "component"}:
        raise ValueError(f"unsupported benchmark mode: {mode}")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    fixture = Path(fixture).resolve(strict=True)
    os.environ["SHUPAI_OCR_IDLE_TTL"] = str(idle_ttl_seconds)
    provider_config = dict(provider_config or {"provider": "cpu"})
    if provider_config.get("provider") not in {"cpu", "cuda"}:
        raise ValueError("benchmark provider must be cpu or cuda")
    if provider_config["provider"] == "cuda" and not provider_config.get("gpu_runtime_dir"):
        raise ValueError("CUDA benchmark requires gpu_runtime_dir")
    runner = (
        ocr_component_runtime.ComponentOcrEngineRunner(
            provider_config_factory=lambda _ctx, _engine: dict(provider_config),
        )
        if mode == "component"
        else None
    )
    content_api.configure_ocr_engine_runner(runner)
    started_at = time.time()
    baseline_rss = _rss_tree_mb()

    try:
        with tempfile.TemporaryDirectory(prefix=f"glowfish_{mode}_benchmark_") as temp:
            root = Path(temp)
            images = root / "images"
            images.mkdir()
            shutil.copy2(fixture, images / fixture.name)
            ctx = SimpleNamespace(progress_path=root / "progress.json")

            prewarm_started = time.perf_counter()
            if not content_api.prewarm(engine):
                raise RuntimeError(f"{mode} prewarm failed for {engine}")
            prewarm_seconds = time.perf_counter() - prewarm_started
            prewarm_pid, prewarm_alive = _worker_state(mode, runner)
            peak_rss = max(baseline_rss, _rss_tree_mb())

            durations = []
            fingerprints = []
            line_counts = []
            worker_pids = []
            for index in range(iterations):
                output = root / f"result_{index}.json"
                run_started = time.perf_counter()
                content_api._run_engine(ctx, images, output, engine)
                durations.append(time.perf_counter() - run_started)
                fingerprint, line_count = _result_summary(output)
                fingerprints.append(fingerprint)
                line_counts.append(line_count)
                worker_pids.append(_worker_state(mode, runner)[0])
                peak_rss = max(peak_rss, _rss_tree_mb())

            if len(set(fingerprints)) != 1:
                raise RuntimeError(f"{mode} produced inconsistent output fingerprints")
            if min(line_counts) < 1:
                raise RuntimeError(f"{mode} produced no OCR lines")

            time.sleep(max(0.0, idle_wait_seconds))
            idle_pid, idle_alive = _worker_state(mode, runner)
            report = {
                "schema_version": 1,
                "mode": mode,
                "provider": provider_config["provider"] if mode == "component" else "legacy",
                "gpu_runtime_version": provider_config.get("gpu_runtime_version"),
                "engine": engine,
                "fixture": fixture.name,
                "iterations": iterations,
                "prewarm_seconds": round(prewarm_seconds, 4),
                "iteration_seconds": [round(value, 4) for value in durations],
                "warm_median_seconds": round(statistics.median(durations), 4),
                "baseline_rss_mb": baseline_rss,
                "peak_rss_mb": peak_rss,
                "rss_growth_mb": round(max(0.0, peak_rss - baseline_rss), 2),
                "fingerprint": fingerprints[0],
                "line_count": min(line_counts),
                "prewarm_worker_pid": prewarm_pid,
                "prewarm_worker_alive": prewarm_alive,
                "iteration_worker_pids": worker_pids,
                "worker_reused": bool(
                    prewarm_pid
                    and prewarm_alive
                    and worker_pids
                    and all(pid == prewarm_pid for pid in worker_pids)
                ),
                "idle_worker_pid": idle_pid,
                "idle_worker_alive": idle_alive,
                "idle_released": not idle_alive,
                "idle_ttl_seconds": idle_ttl_seconds,
                "idle_wait_seconds": idle_wait_seconds,
                "frozen": bool(getattr(sys, "frozen", False)),
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "started_at": started_at,
            }
            return report
    finally:
        if runner is not None:
            runner.shutdown()
        content_api.configure_ocr_engine_runner(None)
        content_api.shutdown_ocr()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("legacy", "component"), required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--engine", default="ppocrv6_onnx_high")
    parser.add_argument("--idle-ttl", type=float, default=1.0)
    parser.add_argument("--idle-wait", type=float, default=1.5)
    parser.add_argument("--provider", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--gpu-runtime-dir", type=Path)
    parser.add_argument("--gpu-runtime-version")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--device-name")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    provider_config = {"provider": args.provider}
    if args.gpu_runtime_dir:
        provider_config["gpu_runtime_dir"] = str(args.gpu_runtime_dir.resolve())
    if args.gpu_runtime_version:
        provider_config["gpu_runtime_version"] = args.gpu_runtime_version
    if args.model_root:
        provider_config["model_root"] = str(args.model_root.resolve())
    if args.device_name:
        provider_config["device_name"] = args.device_name
    report = run_benchmark(
        mode=args.mode,
        fixture=args.fixture,
        iterations=args.iterations,
        engine=args.engine,
        idle_ttl_seconds=args.idle_ttl,
        idle_wait_seconds=args.idle_wait,
        provider_config=provider_config,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
