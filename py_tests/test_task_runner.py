import unittest
from unittest.mock import patch

from desktop_py.ui.task_runner import WindowTaskRunner


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeThread:
    def __init__(self, parent=None):
        self.parent = parent
        self.task_message = FakeSignal()
        self.task_progress = FakeSignal()
        self.task_succeeded = FakeSignal()
        self.task_cancelled = FakeSignal()
        self.task_failed = FakeSignal()
        self.task_finished = FakeSignal()
        self.idle = FakeSignal()
        self.started = False
        self.tasks = []
        self.cancelled = False
        self.shutdown_called = False

    def start(self):
        self.started = True

    def enqueue(self, **kwargs):
        task = type("FakeTask", (), kwargs)()
        self.tasks.append(task)
        return task

    def cancel_all(self):
        self.cancelled = True

    def shutdown(self):
        self.shutdown_called = True

    def wait(self, _timeout):
        return True


class TaskRunnerTestCase(unittest.TestCase):
    def test_run_registers_thread_and_updates_status(self):
        logs: list[str] = []
        statuses: list[str] = []
        status_messages: list[tuple[str, int]] = []
        update_calls: list[str] = []
        threads = []

        runner = WindowTaskRunner(
            parent=object(),
            threads=threads,
            append_log=logs.append,
            update_action_buttons=lambda: update_calls.append("update"),
            set_status_text=statuses.append,
            status_message=lambda message, timeout: status_messages.append((message, timeout)),
        )

        with patch("desktop_py.ui.task_runner.TaskThread", FakeThread):
            runner.run(lambda log: None, lambda _result: None, on_progress=lambda _result: None)

        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].started)
        self.assertEqual(update_calls, ["update"])
        self.assertEqual(statuses, ["后台任务执行中…"])
        self.assertEqual(status_messages, [("任务执行中…", 0)])

    def test_handle_finished_removes_thread(self):
        updates: list[str] = []
        thread = object()
        threads = [thread]
        runner = WindowTaskRunner(
            parent=object(),
            threads=threads,
            append_log=lambda _message: None,
            update_action_buttons=lambda: updates.append("update"),
            set_status_text=lambda _message: None,
            status_message=lambda _message, _timeout: None,
        )

        runner.handle_finished(thread)

        self.assertEqual(threads, [])
        self.assertEqual(updates, ["update"])

    def test_cancel_all_keeps_running_worker_until_idle(self):
        updates: list[str] = []
        threads = []
        runner = WindowTaskRunner(
            parent=object(),
            threads=threads,
            append_log=lambda _message: None,
            update_action_buttons=lambda: updates.append("update"),
            set_status_text=lambda _message: None,
            status_message=lambda _message, _timeout: None,
        )

        with patch("desktop_py.ui.task_runner.TaskThread", FakeThread):
            runner.run(lambda log: None, lambda _result: None)

        self.assertEqual(len(threads), 1)

        runner.cancel_all()

        self.assertEqual(threads, [runner._worker])
        self.assertTrue(runner._worker.cancelled)
        self.assertGreaterEqual(len(updates), 2)

        runner._worker.idle.callbacks[0]()

        self.assertEqual(threads, [])
        self.assertGreaterEqual(len(updates), 3)

    def test_cancelled_task_logs_cancelled_without_failure(self):
        logs: list[str] = []
        statuses: list[str] = []
        status_messages: list[tuple[str, int]] = []
        threads = []
        runner = WindowTaskRunner(
            parent=object(),
            threads=threads,
            append_log=logs.append,
            update_action_buttons=lambda: None,
            set_status_text=statuses.append,
            status_message=lambda message, timeout: status_messages.append((message, timeout)),
        )

        with patch("desktop_py.ui.task_runner.TaskThread", FakeThread):
            runner.run(lambda log: None, lambda _result: None)

        worker = runner._worker
        task = runner._pending_tasks[0]
        worker.task_cancelled.callbacks[0](task, "任务已取消")

        self.assertIn("后台任务已取消。", logs)
        self.assertEqual(statuses[-1], "后台任务已取消")
        self.assertEqual(status_messages[-1], ("后台任务已取消", 4000))


if __name__ == "__main__":
    unittest.main()
