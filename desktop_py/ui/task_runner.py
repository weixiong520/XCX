from __future__ import annotations

from collections.abc import Callable

from desktop_py.ui.workers import TaskThread


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
        thread = TaskThread(job_builder, self._parent)
        if emit_log:
            thread.message.connect(self._append_log)
        if on_progress is not None:
            thread.progress.connect(on_progress)
        if emit_failure_log:
            thread.failed.connect(lambda message: self._append_log(f"任务失败：{message}"))
        thread.succeeded.connect(on_success)
        thread.finished.connect(lambda: self.handle_finished(thread))
        self._threads.append(thread)
        self._update_action_buttons()
        thread.start()
        if update_status:
            self._status_message("任务执行中…", 0)
            self._set_status_text("后台任务执行中…")

    def handle_finished(self, thread: TaskThread) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        self._update_action_buttons()
