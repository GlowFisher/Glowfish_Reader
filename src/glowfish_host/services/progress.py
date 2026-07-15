from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any


class OcrProgressStore:
    def __init__(self):
        self._lock = RLock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def put(self, task_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._tasks[task_id] = deepcopy(state)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._tasks.get(task_id)
            return deepcopy(state) if state is not None else None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id not in self._tasks:
                return False
            self._tasks[task_id]["cancelled"] = True
            return True
