from document_task_manager import DocumentTask, DocumentTaskManager


def test_task_persists_progress_and_result(tmp_path):
    manager = DocumentTaskManager(max_workers=1)

    def runner(task):
        task.progress(done=1)
        output = task.directory / "result.txt"
        output.write_text("ok", encoding="utf-8")
        return output, "result.txt"

    task = manager.submit("user", tmp_path, "export", ["batch"], 1, runner)
    task.future.result(timeout=5)

    status = manager.get("user", task.task_id).status()
    assert status["state"] == "done"
    assert status["done"] == status["total"] == 1
    assert task.status_path.is_file()
    assert task.result_path.read_text(encoding="utf-8") == "ok"


def test_task_cancel_is_cooperative(tmp_path):
    manager = DocumentTaskManager(max_workers=1)

    def runner(task):
        task.cancel_event.wait(2)
        task.check_cancelled()

    task = manager.submit("user", tmp_path, "checkpoint", ["batch"], 1, runner)
    manager.cancel("user", task.task_id)
    task.future.result(timeout=5)

    assert task.status()["state"] == "cancelled"


def test_terminal_task_state_is_not_overwritten_by_late_cancellation(tmp_path):
    task = DocumentTask("user", tmp_path, "checkpoint", ("batch",), 1)

    task.progress(state="cancelled")
    task.progress(state="cancelling")

    assert task.status()["state"] == "cancelled"
