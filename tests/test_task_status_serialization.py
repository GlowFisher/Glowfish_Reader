import threading
import time

import document_task_manager as task_module
from document_task_manager import DocumentTask


def test_same_task_status_publication_is_serialized(tmp_path, monkeypatch):
    task = DocumentTask("user", tmp_path, "export", ("batch",), 2)
    barrier = threading.Barrier(3)
    guard = threading.Lock()
    active = 0
    max_active = 0
    errors = []

    def tracked_atomic(_path, _payload):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    monkeypatch.setattr(task_module, "_atomic_json", tracked_atomic)

    def publish(done):
        try:
            barrier.wait()
            task.progress(done=done)
        except Exception as exc:  # pragma: no cover - assertion captures the thread
            errors.append(exc)

    threads = [
        threading.Thread(target=publish, args=(1,)),
        threading.Thread(target=publish, args=(2,)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert max_active == 1
    assert task.status()["done"] == 2
