from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QSystemTrayIcon,
)

from desktop_py.core.fetcher import (
    fetch_account,
    fetch_accounts_batch,
    fetch_switchable_accounts,
    renew_account_state,
    save_login_state,
    save_login_state_with_profile,
    validate_account_state,
)
from desktop_py.core.fetcher_runtime import close_all_group_runtimes
from desktop_py.core.models import AccountConfig, AppSettings, FetchResult
from desktop_py.core.notifier import build_summary, send_feishu_text
from desktop_py.core.store import (
    default_state_path,
    ensure_runtime_dirs,
    load_accounts,
    load_settings,
    prepare_shared_browser_profile_dir,
    save_accounts,
    save_settings,
    validate_shared_browser_profile_dir,
)
from desktop_py.ui.account_dialog import AccountDialog
from desktop_py.ui.account_presenter import (
    apply_batch_fetch_results,
    apply_fetch_result,
    is_no_business_page_note,
    next_auto_fetch_push_interval_ms,
    parse_deadline_for_sort,
    sort_accounts_for_display,
)
from desktop_py.ui.main_window_actions_impl import (
    actual_account_name_from_note as actual_account_name_from_note_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    add_account as add_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    apply_auto_fetch_push_schedule as apply_auto_fetch_push_schedule_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    apply_auto_renew_schedule as apply_auto_renew_schedule_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    auto_fetch_and_send as auto_fetch_and_send_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    auto_validate_entry_account as auto_validate_entry_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    build_fetch_job as build_fetch_job_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    choose_profile_dir as choose_profile_dir_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    delete_account as delete_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    edit_account as edit_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    fetch_all as fetch_all_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    fetch_selected as fetch_selected_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    handle_auto_fetch_push_timeout as handle_auto_fetch_push_timeout_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    handle_auto_fetch_push_toggled as handle_auto_fetch_push_toggled_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    handle_auto_renew_timeout as handle_auto_renew_timeout_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    handle_selection_changed as handle_selection_changed_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    handle_thread_finished as handle_thread_finished_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    import_accounts as import_accounts_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    initialize_window_state as initialize_window_state_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    login_selected as login_selected_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    login_start_message as login_start_message_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_auto_renew_result as mark_auto_renew_result_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_batch_results as mark_batch_results_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_fetch_progress as mark_fetch_progress_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_fetch_result as mark_fetch_result_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_login as mark_login_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    mark_validation as mark_validation_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    merge_imported_accounts as merge_imported_accounts_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    milliseconds_until_next_auto_fetch_push as milliseconds_until_next_auto_fetch_push_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    renew_selected as renew_selected_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    reset_current_main_account_name as reset_current_main_account_name_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    run_auto_fetch_push as run_auto_fetch_push_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    run_auto_renew as run_auto_renew_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    run_thread as run_thread_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    safe_validate_account_state as safe_validate_account_state_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    save_current_settings as save_current_settings_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    schedule_startup_jobs as schedule_startup_jobs_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    select_imported_accounts as select_imported_accounts_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    selected_account as selected_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    selected_index as selected_index_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    selected_indexes as selected_indexes_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    send_summary as send_summary_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    send_summary_with_webhook as send_summary_with_webhook_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    stop_fetching as stop_fetching_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    update_action_buttons as update_action_buttons_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    update_current_main_account as update_current_main_account_impl,
)
from desktop_py.ui.main_window_actions_impl import (
    validate_selected as validate_selected_impl,
)
from desktop_py.ui.main_window_view import (
    append_log as append_log_impl,
)
from desktop_py.ui.main_window_view import (
    apply_styles as apply_styles_impl,
)
from desktop_py.ui.main_window_view import (
    build_actions as build_actions_impl,
)
from desktop_py.ui.main_window_view import (
    build_actions_card as build_actions_card_impl,
)
from desktop_py.ui.main_window_view import (
    build_auto_fetch_push_switch as build_auto_fetch_push_switch_impl,
)
from desktop_py.ui.main_window_view import (
    build_metric_card as build_metric_card_impl,
)
from desktop_py.ui.main_window_view import (
    build_settings_box as build_settings_box_impl,
)
from desktop_py.ui.main_window_view import (
    build_summary_strip as build_summary_strip_impl,
)
from desktop_py.ui.main_window_view import (
    build_ui as build_ui_impl,
)
from desktop_py.ui.main_window_view import (
    event_filter as event_filter_impl,
)
from desktop_py.ui.main_window_view import (
    refresh_summary_cards as refresh_summary_cards_impl,
)
from desktop_py.ui.main_window_view import (
    refresh_table as refresh_table_impl,
)
from desktop_py.ui.main_window_view import (
    set_browse_profile_button_enabled as set_browse_profile_button_enabled_impl,
)
from desktop_py.ui.main_window_view import (
    set_status_text as set_status_text_impl,
)
from desktop_py.ui.main_window_view import (
    sync_browse_profile_button_state as sync_browse_profile_button_state_impl,
)
from desktop_py.ui.main_window_view import (
    wrap_card as wrap_card_impl,
)
from desktop_py.ui.main_window_widgets import HoverTableWidget, RowHighlightDelegate, ToggleActionButton
from desktop_py.ui.message_dialog import MessageDialog
from desktop_py.ui.task_runner import WindowTaskRunner
from desktop_py.ui.workers import TaskThread

BLOCKED_ACCOUNT_NAMES = {
    "山每北荒修僊1",
    "山每北荒修僊2",
    "山每北荒修僊4",
    "叨空SSR",
}

AUTO_RENEW_INTERVAL_MIN_MS = 2 * 60 * 60 * 1000
AUTO_RENEW_INTERVAL_MAX_MS = 4 * 60 * 60 * 1000
ACTUAL_ACCOUNT_PREFIX = "当前实际账号："


class MainWindow(QMainWindow):
    # 当前工作台以双栏信息密度为优先，固定窗口尺寸是有意设计；
    # 若未来要支持小屏自适应，需要连同卡片排布与滚动策略一起重构。
    CLIENT_WIDTH = 1376
    CLIENT_HEIGHT = 956

    def __init__(self) -> None:
        super().__init__()
        self.accounts: list[AccountConfig] = []
        self.settings = AppSettings()
        initialize_window_state_impl(
            self,
            ensure_runtime_dirs_fn=ensure_runtime_dirs,
            load_accounts_fn=load_accounts,
            load_settings_fn=load_settings,
            save_accounts_fn=save_accounts,
            reset_current_main_account_name_fn=self._reset_current_main_account_name,
        )
        self._threads: list[TaskThread] = []
        self._task_runner = WindowTaskRunner(
            parent=self,
            threads=self._threads,
            append_log=self.append_log,
            update_action_buttons=self._update_action_buttons,
            set_status_text=self._set_status_text,
            status_message=lambda message, timeout: self.statusBar().showMessage(message, timeout),
        )
        self._summary_labels: dict[str, QLabel] = {}
        self._status_label: QLabel | None = None
        self.login_button: QPushButton | None = None
        self.renew_button: QPushButton | None = None
        self.edit_button: QPushButton | None = None
        self.import_button: QPushButton | None = None
        self.validate_button: QPushButton | None = None
        self.fetch_selected_button: QPushButton | None = None
        self.send_summary_button: QPushButton | None = None
        self.stop_fetch_button: QPushButton | None = None
        self.delete_button: QPushButton | None = None
        self.browse_profile_button: QPushButton | None = None
        self.auto_fetch_push_switch: QPushButton | None = None
        self.tray_icon: QSystemTrayIcon | None = None
        self._allow_close = False
        self._auto_fetch_timer = QTimer(self)
        self._auto_fetch_timer.setSingleShot(True)
        self._auto_fetch_timer.timeout.connect(self._handle_auto_fetch_push_timeout)
        self._auto_renew_timer = QTimer(self)
        self._auto_renew_timer.setSingleShot(True)
        self._auto_renew_timer.timeout.connect(self._handle_auto_renew_timeout)
        self._toggle_action_button_cls = ToggleActionButton

        self.setWindowTitle("小程序工具")
        self.setWindowFlag(Qt.WindowType.WindowTitleHint, True)
        self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setFixedSize(self.CLIENT_WIDTH, self.CLIENT_HEIGHT)
        self._build_ui()
        self._apply_styles()
        self.refresh_table()
        self._center_on_screen()
        schedule_startup_jobs_impl(self, timer_cls=QTimer)

    def _center_on_screen(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close or self.tray_icon is None or not self.tray_icon.isVisible():
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def request_exit(self) -> None:
        self._allow_close = True
        self._task_runner.shutdown()
        close_all_group_runtimes()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _build_ui(self) -> None:
        build_ui_impl(self, HoverTableWidget, RowHighlightDelegate)

    def _build_summary_strip(self):
        return build_summary_strip_impl(self)

    def _build_metric_card(self, key: str, title: str, value: str):
        return build_metric_card_impl(self, key, title, value)

    def _build_settings_box(self):
        return build_settings_box_impl(self)

    def eventFilter(self, watched, event):
        return event_filter_impl(self, watched, event, super().eventFilter)

    def _set_browse_profile_button_enabled(self, enabled: bool) -> None:
        set_browse_profile_button_enabled_impl(self, enabled)

    def _sync_browse_profile_button_state(self) -> None:
        sync_browse_profile_button_state_impl(self)

    def _build_actions_card(self):
        return build_actions_card_impl(self)

    def _build_actions(self):
        return build_actions_impl(self)

    def _build_auto_fetch_push_switch(self):
        return build_auto_fetch_push_switch_impl(self)

    def _wrap_card(self, title: str, subtitle: str, content):
        return wrap_card_impl(title, subtitle, content)

    def _apply_styles(self) -> None:
        apply_styles_impl(self)

    def append_log(self, message: str) -> None:
        append_log_impl(self, message)

    def refresh_table(self) -> None:
        refresh_table_impl(self)

    def _sort_accounts_for_display(self) -> None:
        self.accounts = sort_accounts_for_display(self.accounts)

    def _parse_deadline_for_sort(self, deadline_text: str) -> datetime | None:
        return parse_deadline_for_sort(deadline_text)

    def _is_no_business_page_note(self, note: str) -> bool:
        return is_no_business_page_note(note)

    def _show_info(self, title: str, text: str) -> None:
        MessageDialog.show_info(self, title, text)

    def _show_warning(self, title: str, text: str) -> None:
        MessageDialog.show_warning(self, title, text)

    def _auto_validate_entry_account(self) -> None:
        auto_validate_entry_account_impl(self, os_module=os, validate_account_state_fn=validate_account_state)

    def _safe_validate_account_state(self, account: AccountConfig) -> bool:
        return safe_validate_account_state_impl(self, account, validate_account_state_fn=validate_account_state)

    def selected_index(self) -> int:
        return selected_index_impl(self)

    def selected_indexes(self) -> list[int]:
        return selected_indexes_impl(self)

    def selected_account(self) -> AccountConfig | None:
        return selected_account_impl(self)

    def _handle_selection_changed(self) -> None:
        handle_selection_changed_impl(self)

    def _update_action_buttons(self) -> None:
        update_action_buttons_impl(self)

    def stop_fetching(self) -> None:
        stop_fetching_impl(self)

    def _update_current_main_account(self, account_name: str) -> None:
        update_current_main_account_impl(self, account_name, save_settings_fn=save_settings)

    def _reset_current_main_account_name(self) -> None:
        reset_current_main_account_name_impl(self, save_settings_fn=save_settings)

    def select_imported_accounts(self) -> None:
        select_imported_accounts_impl(self, selection_flag=QItemSelectionModel.SelectionFlag)

    def save_current_settings(self) -> None:
        save_current_settings_impl(
            self,
            app_settings_cls=AppSettings,
            validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
            save_settings_fn=save_settings,
        )

    def choose_profile_dir(self) -> None:
        choose_profile_dir_impl(
            self,
            file_dialog=QFileDialog,
            prepare_shared_browser_profile_dir_fn=prepare_shared_browser_profile_dir,
        )

    def add_account(self) -> None:
        add_account_impl(
            self,
            account_dialog_cls=AccountDialog,
            default_state_path_fn=default_state_path,
            save_accounts_fn=save_accounts,
        )

    def edit_account(self) -> None:
        edit_account_impl(
            self,
            account_dialog_cls=AccountDialog,
            default_state_path_fn=default_state_path,
            save_accounts_fn=save_accounts,
        )

    def import_accounts(self) -> None:
        import_accounts_impl(self, fetch_switchable_accounts_fn=fetch_switchable_accounts)

    def _merge_imported_accounts(self, base_account: AccountConfig, names: list[str]) -> None:
        merge_imported_accounts_impl(
            self,
            base_account,
            names,
            blocked_account_names=BLOCKED_ACCOUNT_NAMES,
            account_config_cls=AccountConfig,
            save_accounts_fn=save_accounts,
        )

    def delete_account(self) -> None:
        delete_account_impl(self, message_dialog_cls=MessageDialog, save_accounts_fn=save_accounts)

    def login_selected(self) -> None:
        login_selected_impl(
            self, save_login_state_with_profile_fn=save_login_state_with_profile, save_login_state_fn=save_login_state
        )

    def _mark_login(self, account: AccountConfig) -> None:
        mark_login_impl(
            self,
            account,
            datetime_cls=datetime,
            save_accounts_fn=save_accounts,
            close_all_group_runtimes_fn=close_all_group_runtimes,
        )

    def _login_start_message(self, account: AccountConfig) -> str:
        return login_start_message_impl(self, account)

    def validate_selected(self) -> None:
        validate_selected_impl(self, validate_account_state_fn=validate_account_state)

    def renew_selected(self) -> None:
        renew_selected_impl(self, renew_account_state_fn=renew_account_state)

    def _mark_validation(self, account: AccountConfig, valid: bool) -> None:
        mark_validation_impl(self, account, valid, save_accounts_fn=save_accounts)

    def fetch_selected(self) -> None:
        fetch_selected_impl(self, fetch_account_fn=fetch_account)

    def fetch_all(self) -> None:
        fetch_all_impl(self)

    def auto_fetch_and_send(self) -> None:
        auto_fetch_and_send_impl(self)

    def _handle_auto_fetch_push_toggled(self, checked: bool) -> None:
        handle_auto_fetch_push_toggled_impl(self, checked, save_settings_fn=save_settings)

    def _apply_auto_fetch_push_schedule(self) -> None:
        apply_auto_fetch_push_schedule_impl(self)

    def _milliseconds_until_next_auto_fetch_push(self, now: datetime | None = None) -> int:
        return milliseconds_until_next_auto_fetch_push_impl(
            self, now, next_interval_fn=next_auto_fetch_push_interval_ms
        )

    def _handle_auto_fetch_push_timeout(self) -> None:
        handle_auto_fetch_push_timeout_impl(self)

    def _apply_auto_renew_schedule(self) -> None:
        apply_auto_renew_schedule_impl(
            self,
            min_auto_renew_interval_ms=AUTO_RENEW_INTERVAL_MIN_MS,
            max_auto_renew_interval_ms=AUTO_RENEW_INTERVAL_MAX_MS,
        )

    def _handle_auto_renew_timeout(self) -> None:
        handle_auto_renew_timeout_impl(self)

    def _run_auto_renew(self) -> None:
        run_auto_renew_impl(
            self,
            renew_account_state_fn=lambda account, log, profile_dir, headless: renew_account_state(
                account,
                log,
                profile_dir,
                headless,
            ),
        )

    def _mark_auto_renew_result(self, account: AccountConfig, valid: bool) -> None:
        mark_auto_renew_result_impl(self, account, valid, save_accounts_fn=save_accounts)

    def _run_auto_fetch_push(self) -> None:
        run_auto_fetch_push_impl(self)

    def _build_fetch_job(self, enabled_accounts: list[AccountConfig]):
        return build_fetch_job_impl(
            self,
            enabled_accounts,
            fetch_accounts_batch_fn=lambda *args, **kwargs: fetch_accounts_batch(*args, **kwargs),
        )

    def _mark_fetch_progress(self, result: FetchResult) -> None:
        mark_fetch_progress_impl(self, result)

    def _mark_fetch_result(self, account: AccountConfig, result: FetchResult) -> None:
        mark_fetch_result_impl(
            self, account, result, apply_fetch_result_fn=apply_fetch_result, save_accounts_fn=save_accounts
        )

    def _mark_batch_results(self, results: list[FetchResult]) -> None:
        mark_batch_results_impl(
            self, results, apply_batch_fetch_results_fn=apply_batch_fetch_results, save_accounts_fn=save_accounts
        )

    def send_summary(self) -> None:
        send_summary_impl(self)

    def _send_summary_with_webhook(self, webhook: str, append_batch_log: bool = False) -> None:
        send_summary_with_webhook_impl(
            self,
            webhook,
            append_batch_log=append_batch_log,
            build_summary_fn=lambda results: build_summary(results),
            send_feishu_text_fn=lambda target_webhook, content: send_feishu_text(target_webhook, content),
            fetch_result_cls=FetchResult,
            actual_account_prefix=ACTUAL_ACCOUNT_PREFIX,
            save_accounts_fn=save_accounts,
        )

    def _actual_account_name_from_note(self, note: str) -> str:
        return actual_account_name_from_note_impl(note, actual_account_prefix=ACTUAL_ACCOUNT_PREFIX)

    def _run_thread(
        self,
        job_builder,
        on_success,
        emit_log: bool = True,
        emit_failure_log: bool = True,
        update_status: bool = True,
        on_progress=None,
    ) -> None:
        run_thread_impl(
            self,
            job_builder,
            on_success,
            emit_log=emit_log,
            emit_failure_log=emit_failure_log,
            update_status=update_status,
            on_progress=on_progress,
        )

    def _handle_thread_finished(self, thread: TaskThread) -> None:
        handle_thread_finished_impl(self, thread)

    def _refresh_summary_cards(self) -> None:
        refresh_summary_cards_impl(self)

    def _set_status_text(self, message: str) -> None:
        set_status_text_impl(self, message)
