import threading
import time

import pytest

from glowfish_ocr.pipeline import (
    MAX_PREFETCH_PAGES,
    OrderedPagePipeline,
    PagePipelineConfig,
    PipelineCancelled,
)


def test_pipeline_keeps_page_order_and_one_inference_slot():
    active_inference = 0
    max_active_inference = 0
    lock = threading.Lock()

    def prepare(value):
        # Complete page 0 after page 1 to prove output ordering is explicit.
        time.sleep(0.02 if value == 0 else 0)
        return value * 2

    def infer(value):
        nonlocal active_inference, max_active_inference
        with lock:
            active_inference += 1
            max_active_inference = max(max_active_inference, active_inference)
        time.sleep(0.002)
        with lock:
            active_inference -= 1
        return value + 1

    pipeline = OrderedPagePipeline(prepare, infer, lambda value: value * 10)

    assert pipeline.run(range(5)) == [10, 30, 50, 70, 90]
    assert max_active_inference == 1


def test_pipeline_bounds_preparation_and_can_be_cancelled():
    prepared = []
    cancellation = {"requested": False}

    def prepare(value):
        prepared.append(value)
        if value == 1:
            cancellation["requested"] = True
        return value

    pipeline = OrderedPagePipeline(prepare, lambda value: value, lambda value: value)

    with pytest.raises(PipelineCancelled):
        pipeline.run(range(10), cancelled=lambda: cancellation["requested"])

    assert len(prepared) <= MAX_PREFETCH_PAGES


def test_pipeline_configuration_rejects_unbounded_or_empty_pools():
    with pytest.raises(ValueError):
        PagePipelineConfig(max_prefetch_pages=0)
    with pytest.raises(ValueError):
        PagePipelineConfig(input_workers=0)


def test_pipeline_reports_completed_pages_without_losing_source_order():
    completed = []
    pipeline = OrderedPagePipeline(
        lambda value: value,
        lambda value: value * 2,
        lambda value: value,
        on_complete=lambda index, value: completed.append((index, value)),
    )
    assert pipeline.run([3, 1, 2]) == [6, 2, 4]
    assert sorted(completed) == [(0, 6), (1, 2), (2, 4)]
