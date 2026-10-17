"""Bounded, ordered page pipeline primitives for OCR jobs.

The OCR engine itself is deliberately kept single-file compatible.  Callers that
need to process a document can use this helper to overlap CPU preparation and
post-processing while preserving a single, serial inference lane (which is the
safe default for one CUDA execution provider).
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar


Input = TypeVar("Input")
Prepared = TypeVar("Prepared")
Inference = TypeVar("Inference")
Output = TypeVar("Output")

CPU_INPUT_WORKERS = 2
CPU_OUTPUT_WORKERS = 2
MAX_PREFETCH_PAGES = 2


class PipelineCancelled(RuntimeError):
    """Raised when a caller cancels a document pipeline."""


@dataclass(frozen=True)
class PagePipelineConfig:
    """Concurrency limits for :class:`OrderedPagePipeline`.

    ``max_prefetch_pages`` is shared by the preparation and post-processing
    queues, so a large document cannot accumulate unbounded decoded pages.
    ``inference`` remains serial by design.
    """

    input_workers: int = CPU_INPUT_WORKERS
    output_workers: int = CPU_OUTPUT_WORKERS
    max_prefetch_pages: int = MAX_PREFETCH_PAGES

    def __post_init__(self) -> None:
        if self.input_workers < 1 or self.output_workers < 1:
            raise ValueError("CPU worker counts must be positive")
        if self.max_prefetch_pages < 1:
            raise ValueError("max_prefetch_pages must be positive")


class OrderedPagePipeline(Generic[Input, Prepared, Inference, Output]):
    """Run page work in bounded stages and return results in source order.

    ``prepare`` and ``finalize`` execute in small CPU pools.  ``infer`` is
    intentionally executed on the caller thread, creating one GPU inference
    slot even when preparation completes out of order.  This avoids hidden GPU
    contention and makes provider fallback behaviour deterministic.
    """

    def __init__(
        self,
        prepare: Callable[[Input], Prepared],
        infer: Callable[[Prepared], Inference],
        finalize: Callable[[Inference], Output],
        *,
        config: PagePipelineConfig | None = None,
        on_complete: Callable[[int, Output], None] | None = None,
    ) -> None:
        self._prepare = prepare
        self._infer = infer
        self._finalize = finalize
        self._config = config or PagePipelineConfig()
        self._on_complete = on_complete

    def run(
        self,
        pages: Iterable[Input],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[Output]:
        """Process ``pages`` and return their results in original order.

        Cancellation is checked before new work is accepted and between every
        stage.  The caller owns checkpoint persistence; this primitive raises
        promptly so it can retain completed checkpoints and clear job state.
        """

        is_cancelled = cancelled or (lambda: False)
        iterator = iter(enumerate(pages))
        prepared: dict[Future[Prepared], int] = {}
        finalized: dict[Future[Output], int] = {}
        results: dict[int, Output] = {}
        exhausted = False

        def check_cancelled() -> None:
            if is_cancelled():
                for future in (*prepared, *finalized):
                    future.cancel()
                raise PipelineCancelled("page pipeline cancelled")

        def submit_preparation(pool: ThreadPoolExecutor) -> None:
            nonlocal exhausted
            while not exhausted and len(prepared) < self._config.max_prefetch_pages:
                check_cancelled()
                try:
                    index, page = next(iterator)
                except StopIteration:
                    exhausted = True
                    return
                prepared[pool.submit(self._prepare, page)] = index

        def collect_one_finalized() -> None:
            check_cancelled()
            done, _ = wait(tuple(finalized), return_when=FIRST_COMPLETED)
            for future in done:
                index = finalized.pop(future)
                result = future.result()
                results[index] = result
                if self._on_complete is not None:
                    self._on_complete(index, result)

        with ThreadPoolExecutor(max_workers=self._config.input_workers) as input_pool, ThreadPoolExecutor(
            max_workers=self._config.output_workers
        ) as output_pool:
            submit_preparation(input_pool)
            while prepared:
                check_cancelled()
                done, _ = wait(tuple(prepared), return_when=FIRST_COMPLETED)
                for future in done:
                    index = prepared.pop(future)
                    prepared_page = future.result()
                    check_cancelled()
                    inference = self._infer(prepared_page)
                    check_cancelled()
                    while len(finalized) >= self._config.max_prefetch_pages:
                        collect_one_finalized()
                    finalized[output_pool.submit(self._finalize, inference)] = index
                submit_preparation(input_pool)

            while finalized:
                collect_one_finalized()

        return [results[index] for index in range(len(results))]
