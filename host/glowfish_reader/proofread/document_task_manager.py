"""Background document tasks with durable progress and cooperative cancellation."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


TERMINAL_STATES = {"done", "failed", "cancelled"}


class DocumentTaskCancelled(RuntimeError):
    pass


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@dataclass
class DocumentTask:
    user_id: str
    root: Path
    kind: str
    batches: tuple[str, ...]
    total: int
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "queued"
    done: int = 0
    error: str | None = None
    result_name: str | None = None
    result_path: Path | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    _status_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    @property
    def directory(self) -> Path:
        return self.root / ".document_tasks" / self.task_id

    @property
    def status_path(self) -> Path:
        return self.directory / "status.json"

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise DocumentTaskCancelled("document task cancelled")

    def progress(self, *, done: int | None = None, total: int | None = None,
                 state: str | None = None, **extra) -> dict:
        # Windows can reject concurrent os.replace calls targeting the same
        # status file. Serialize both state mutation and durable publication per task.
        with self._status_lock:
            if done is not None:
                self.done = max(self.done, int(done))
            if total is not None:
                self.total = max(0, int(total))
            if state is not None and not (
                self.state in TERMINAL_STATES and state not in TERMINAL_STATES
            ):
                self.state = state
            payload = self.status()
            payload.update(extra)
            _atomic_json(self.status_path, payload)
            return payload

    def status(self) -> dict:
        with self._status_lock:
            return {
                "job_id": self.task_id,
                "kind": self.kind,
                "batches": list(self.batches),
                "state": self.state,
                "done": self.done,
                "total": self.total,
                "error": self.error,
                "result_name": self.result_name,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


TaskRunner = Callable[[DocumentTask], tuple[Path, str] | None]


class DocumentTaskManager:
    """Per-user task registry; independent from the single-flight OCR scheduler."""

    def __init__(self, *, max_workers: int = 2, retention_seconds: int = 24 * 3600):
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="glowfish-document")
        self._tasks: dict[tuple[str, str], DocumentTask] = {}
        self._retention_seconds = retention_seconds

    def submit(self, user_id: str, root: Path, kind: str, batches, total: int, runner: TaskRunner) -> DocumentTask:
        root = Path(root).resolve()
        self._cleanup(root)
        task = DocumentTask(str(user_id), root, str(kind), tuple(map(str, batches)), int(total))
        with self._lock:
            self._tasks[(task.user_id, task.task_id)] = task
            task.future = self._executor.submit(self._execute, task, runner)
        return task

    def _execute(self, task: DocumentTask, runner: TaskRunner) -> None:
        task.started_at = time.time()
        task.progress(state="running", done=0)
        try:
            task.check_cancelled()
            result = runner(task)
            task.check_cancelled()
            if result:
                task.result_path, task.result_name = result
            task.progress(state="done", done=task.total)
        except DocumentTaskCancelled as exc:
            task.error = str(exc)
            task.progress(state="cancelled")
        except Exception as exc:
            task.error = f"{type(exc).__name__}: {exc}"
            task.progress(state="failed")
        finally:
            task.finished_at = time.time()
            task.progress()

    def get(self, user_id: str, task_id: str) -> DocumentTask | None:
        with self._lock:
            return self._tasks.get((str(user_id), str(task_id)))

    def cancel(self, user_id: str, task_id: str) -> DocumentTask | None:
        task = self.get(user_id, task_id)
        if task and task.state not in TERMINAL_STATES:
            task.cancel_event.set()
            task.progress(state="cancelling")
        return task

    def _cleanup(self, root: Path) -> None:
        tasks = root / ".document_tasks"
        if not tasks.is_dir():
            return
        cutoff = time.time() - self._retention_seconds
        for child in tasks.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass


TASK_MANAGER = DocumentTaskManager()
