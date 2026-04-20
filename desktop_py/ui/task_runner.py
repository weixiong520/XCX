from __future__ import annotations

from collections.abc import Callable

from desktop_py.ui.workers import QueuedTask, TaskThread


class WindowTaskRunner:
    def __init__(
        self,
        *,
        parent,
        threads: list[TaskThread],
        append_log: Callable[[str], None],
        update_action_buttons: Callable[[], None],
        set_status_text: Callable[[str], None],
        status_message: Callable[[str, int], None],
    ) -> None:
        self._parent = parent
        self._threads = threads
        self._append_log = append_log
        self._update_action_buttons = update_action_buttons
        self._set_status_text = set_status_text
        self._status_message = status_message
        self._worker: TaskThread | None = None
        self._pending_tasks: list[QueuedTask] = []

    def _ensure_worker(self) -> TaskThread:
        if self._worker is not None:
            return self._worker
        worker = TaskThread(self._parent)
        worker.task_message.connect(self._handle_task_message)
        worker.task_progress.connect(self._handle_task_progress)
        worker.task_succeeded.connect(self._handle_task_succeeded)
        worker.task_cancelled.connect(self._handle_task_cancelled)
        worker.task_failed.connect(self._handle_task_failed)
        worker.task_finished.connect(self._handle_task_finished)
        worker.idle.connect(self._handle_worker_idle)
        worker.start()
        self._worker = worker
        return worker

    def run(
        self,
        job_builder,
        on_success,
        *,
        emit_log: bool = True,
        emit_failure_log: bool = True,
        update_status: bool = True,
        on_progress=None,
    ) -> None:
        worker = self._ensure_worker()
        task = worker.enqueue(
            job_builder=job_builder,
            on_success=on_success,
            emit_log=emit_log,
            emit_failure_log=emit_failure_log,
            update_status=update_status,
            on_progress=on_progress,
        )
        self._pending_tasks.append(task)
        if worker not in self._threads:
            self._threads.append(worker)
        self._update_action_buttons()
        if update_status:
            self._status_message("任务执行中…", 0)
            self._set_status_text("后台任务执行中…")

    def cancel_all(self) -> None:
        if self._worker is None:
            return
        self._pending_tasks.clear()
        self._worker.cancel_all()
        if self._worker in self._threads:
            self._threads.remove(self._worker)
        self._update_action_buttons()

    def shutdown(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self.cancel_all()
        worker.shutdown()
        worker.wait(2000)
        self._worker = None

    def _handle_task_succeeded(self, task: QueuedTask, result) -> None:
        task.on_success(result)

    def _handle_task_message(self, task: QueuedTask, message: str) -> None:
        if task.emit_log:
            self._append_log(message)

    def _handle_task_progress(self, task: QueuedTask, payload) -> None:
        if task.on_progress is not None:
            task.on_progress(payload)

    def _handle_task_failed(self, task: QueuedTask, message: str) -> None:
        if task.emit_failure_log:
            self._append_log(f"任务失败：{message}")

    def _handle_task_cancelled(self, _task: QueuedTask, _message: str) -> None:
        self._append_log("后台任务已取消。")
        self._status_message("后台任务已取消", 4000)
        self._set_status_text("后台任务已取消")

    def _handle_task_finished(self, task: QueuedTask) -> None:
        if task in self._pending_tasks:
            self._pending_tasks.remove(task)
        self._update_action_buttons()

    def _handle_worker_idle(self) -> None:
        worker = self._worker
        if worker is not None and worker in self._threads:
            self._threads.remove(worker)
        self._update_action_buttons()

    def handle_finished(self, thread: TaskThread) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        self._update_action_buttons()
