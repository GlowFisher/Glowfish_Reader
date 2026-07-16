import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_ocr_runtime_ab import evaluate_reports  # noqa: E402


def _report(**overrides):
    value = {
        "line_count": 12,
        "worker_reused": True,
        "idle_released": True,
        "fingerprint": "same",
        "warm_median_seconds": 10.0,
        "prewarm_seconds": 20.0,
        "rss_growth_mb": 100.0,
    }
    value.update(overrides)
    return value


def test_benchmark_accepts_equivalent_bounded_component():
    failures = evaluate_reports(
        _report(),
        _report(warm_median_seconds=10.8, prewarm_seconds=22.0, rss_growth_mb=120.0),
        max_warm_ratio=1.15,
        max_prewarm_ratio=1.25,
        max_rss_growth_mb=64.0,
    )
    assert failures == []


def test_benchmark_rejects_output_lifecycle_and_performance_regressions():
    failures = evaluate_reports(
        _report(),
        _report(
            fingerprint="different",
            worker_reused=False,
            idle_released=False,
            warm_median_seconds=13.0,
            prewarm_seconds=30.0,
            rss_growth_mb=300.0,
        ),
        max_warm_ratio=1.15,
        max_prewarm_ratio=1.25,
        max_rss_growth_mb=64.0,
    )
    assert len(failures) == 6
