from __future__ import annotations

import inspect
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from desktop_py.core.fetcher_support import CancelledError

MessageEmitter = Callable[[str], None]
ProgressEmitter = Callable[[Any], None]
CancelCheck = Callable[[], bool]
JobBuilder = Callable[..., Any]
SuccessHandler = Callable[[Any], None]
ProgressHandler = Callable[[Any], None]


@dataclass
class QueuedTask:
    task_id: int
    job_builder: JobBuilder
    on_success: SuccessHandler
    emit_log: bool
    emit_failure_log: bool
    update_status: bool
    on_progress: ProgressHandler | None


class TaskThread(QThread):
    task_message = Signal(object, str)
    task_progress = Signal(object, object)
    task_succeeded = Signal(object, object)
    task_cancelled = Signal(object, str)
    task_failed = Signal(object, str)
    task_finished = Signal(object)
    idle = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[QueuedTask | None] = queue.Queue()
        self._cancel_event = threading.Event()
        self._shutdown = threading.Event()
        self._task_ids = count(1)
        self._active_task: QueuedTask | None = None

    def enqueue(
        self,
        *,
        job_builder: JobBuilder,
        on_success: SuccessHandler,
        emit_log: bool,
        emit_failure_log: bool,
        update_status: bool,
        on_progress: ProgressHandler | None,
    ) -> QueuedTask:
        task = QueuedTask(
            task_id=next(self._task_ids),
            job_builder=job_builder,
            on_success=on_success,
            emit_log=emit_log,
            emit_failure_log=emit_failure_log,
            update_status=update_status,
            on_progress=on_progress,
        )
        self._queue.put(task)
        return task

    def cancel_all(self) -> None:
        self._cancel_event.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def shutdown(self) -> None:
        self.cancel_all()
        self._shutdown.set()
        self._queue.put(None)

    def has_pending_work(self) -> bool:
        return self._active_task is not None or not self._queue.empty()

    def run(self) -> None:
        while not self._shutdown.is_set():
            task = self._queue.get()
            if task is None:
                break
            self._active_task = task
            self._cancel_event.clear()
            try:
                parameter_count = len(inspect.signature(task.job_builder).parameters)
                if parameter_count >= 3:
                    result = task.job_builder(
                        lambda message: self.task_message.emit(task, message),
                        lambda payload: self.task_progress.emit(task, payload),
                        self._cancel_event.is_set,
                    )
                elif parameter_count >= 2:
                    result = task.job_builder(
                        lambda message: self.task_message.emit(task, message),
                        lambda payload: self.task_progress.emit(task, payload),
                    )
                else:
                    result = task.job_builder(lambda message: self.task_message.emit(task, message))
            except CancelledError as exc:
                self.task_cancelled.emit(task, str(exc))
            except Exception as exc:
                self.task_failed.emit(task, str(exc))
            else:
                self.task_succeeded.emit(task, result)
            finally:
                self.task_finished.emit(task)
                self._active_task = None
                if self._queue.empty():
                    self.idle.emit()
