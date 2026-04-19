import unittest

from desktop_py.ui.task_runner import WindowTaskRunner


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeThread:
    def __init__(self, job_builder, parent=None):
        self.job_builder = job_builder
        self.parent = parent
        self.message = FakeSignal()
        self.progress = FakeSignal()
        self.succeeded = FakeSignal()
        self.failed = FakeSignal()
        self.finished = FakeSignal()
        self.started = False

    def start(self):
        self.started = True


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

        from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
