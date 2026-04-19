from __future__ import annotations

import inspect
from typing import Callable

from PySide6.QtCore import QThread, Signal


class TaskThread(QThread):
    message = Signal(str)
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, job_builder: Callable[[Callable[[str], None]], object], parent=None):
        super().__init__(parent)
        self._job_builder = job_builder

    def run(self) -> None:
        try:
            parameter_count = len(inspect.signature(self._job_builder).parameters)
            if parameter_count >= 3:
                result = self._job_builder(self.message.emit, self.progress.emit, self.isInterruptionRequested)
            elif parameter_count >= 2:
                result = self._job_builder(self.message.emit, self.progress.emit)
            else:
                result = self._job_builder(self.message.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)
