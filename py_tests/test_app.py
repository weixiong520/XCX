import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from desktop_py.app import ensure_browser_runtime


class FakeTaskThread(QObject):
    task_message = Signal(object, str)
    task_succeeded = Signal(object, object)
    task_failed = Signal(object, str)
    task_finished = Signal(object)

    def __init__(self, should_fail: bool = False):
        super().__init__()
        self._should_fail = should_fail
        self._job_builder = None
        self._task = object()

    def enqueue(
        self,
        *,
        job_builder,
        on_success,
        emit_log: bool,
        emit_failure_log: bool,
        update_status: bool,
        on_progress,
    ):
        self._job_builder = job_builder
        self._on_success = on_success
        return self._task

    def start(self):
        if self._should_fail:
            self.task_failed.emit(self._task, "network error")
            self.task_finished.emit(self._task)
            return
        result = self._job_builder(lambda message: self.task_message.emit(self._task, message))
        self.task_succeeded.emit(self._task, result)
        self.task_finished.emit(self._task)

    def deleteLater(self):
        return None


class AppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ensure_browser_runtime_skips_install_when_ready(self):
        with (
            patch("desktop_py.app.playwright_browsers_ready", return_value=True),
            patch("desktop_py.app.install_playwright_browsers") as mock_install,
        ):
            self.assertTrue(ensure_browser_runtime(self.app))

        mock_install.assert_not_called()

    def test_ensure_browser_runtime_shows_warning_when_install_fails(self):
        with (
            patch("desktop_py.app.playwright_browsers_ready", return_value=False),
            patch("desktop_py.app.TaskThread", side_effect=lambda: FakeTaskThread(should_fail=True)),
            patch("desktop_py.app.MessageDialog.show_warning") as mock_warning,
        ):
            self.assertFalse(ensure_browser_runtime(self.app))

        mock_warning.assert_called_once()

    def test_ensure_browser_runtime_runs_install_in_background_thread(self):
        with (
            patch("desktop_py.app.playwright_browsers_ready", return_value=False),
            patch("desktop_py.app.TaskThread", side_effect=lambda: FakeTaskThread()),
            patch("desktop_py.app.install_playwright_browsers", return_value=(True, "ok")) as mock_install,
        ):
            self.assertTrue(ensure_browser_runtime(self.app))

        mock_install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
