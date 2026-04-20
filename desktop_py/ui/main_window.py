from __future__ import annotations

from datetime import datetime
import os

from PySide6.QtCore import QItemSelectionModel, QTimer, Qt
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
    keep_alive_account_state,
    save_login_state,
    save_login_state_with_profile,
    validate_account_state,
)
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
from desktop_py.ui.account_presenter import (
    apply_batch_fetch_results,
    apply_fetch_result,
    deadline_tooltip_text,
    display_account_name,
    display_deadline_text,
    display_result_text,
    is_no_business_page_note,
    next_auto_fetch_push_interval_ms,
    parse_deadline_for_sort,
    sort_accounts_for_display,
)
from desktop_py.ui.account_dialog import AccountDialog
from desktop_py.ui.message_dialog import MessageDialog
from desktop_py.ui.main_window_actions_impl import (
    account_for_keep_alive as account_for_keep_alive_impl,
    actual_account_name_from_note as actual_account_name_from_note_impl,
    add_account as add_account_impl,
    apply_auto_fetch_push_schedule as apply_auto_fetch_push_schedule_impl,
    apply_keep_alive_schedule as apply_keep_alive_schedule_impl,
    auto_fetch_and_send as auto_fetch_and_send_impl,
    auto_validate_entry_account as auto_validate_entry_account_impl,
    build_fetch_job as build_fetch_job_impl,
    choose_profile_dir as choose_profile_dir_impl,
    delete_account as delete_account_impl,
    edit_account as edit_account_impl,
    entry_account as entry_account_impl,
    fetch_all as fetch_all_impl,
    fetch_selected as fetch_selected_impl,
    handle_auto_fetch_push_timeout as handle_auto_fetch_push_timeout_impl,
    handle_auto_fetch_push_toggled as handle_auto_fetch_push_toggled_impl,
    handle_keep_alive_timeout as handle_keep_alive_timeout_impl,
    handle_selection_changed as handle_selection_changed_impl,
    handle_thread_finished as handle_thread_finished_impl,
    import_accounts as import_accounts_impl,
    login_selected as login_selected_impl,
    login_start_message as login_start_message_impl,
    mark_batch_results as mark_batch_results_impl,
    mark_fetch_progress as mark_fetch_progress_impl,
    mark_fetch_result as mark_fetch_result_impl,
    mark_keep_alive_result as mark_keep_alive_result_impl,
    mark_login as mark_login_impl,
    mark_validation as mark_validation_impl,
    merge_imported_accounts as merge_imported_accounts_impl,
    milliseconds_until_next_auto_fetch_push as milliseconds_until_next_auto_fetch_push_impl,
    reset_current_main_account_name as reset_current_main_account_name_impl,
    run_auto_fetch_push as run_auto_fetch_push_impl,
    run_keep_alive as run_keep_alive_impl,
    run_thread as run_thread_impl,
    safe_validate_account_state as safe_validate_account_state_impl,
    save_current_settings as save_current_settings_impl,
    selected_account as selected_account_impl,
    selected_index as selected_index_impl,
    selected_indexes as selected_indexes_impl,
    select_imported_accounts as select_imported_accounts_impl,
    send_summary as send_summary_impl,
    send_summary_with_webhook as send_summary_with_webhook_impl,
    stop_fetching as stop_fetching_impl,
    update_action_buttons as update_action_buttons_impl,
    update_current_main_account as update_current_main_account_impl,
    validate_selected as validate_selected_impl,
)
from desktop_py.ui.task_runner import WindowTaskRunner
from desktop_py.ui.workers import TaskThread
from desktop_py.ui.main_window_view import (
    append_log as append_log_impl,
    apply_styles as apply_styles_impl,
    build_actions_card as build_actions_card_impl,
    build_actions as build_actions_impl,
    build_auto_fetch_push_switch as build_auto_fetch_push_switch_impl,
    build_metric_card as build_metric_card_impl,
    build_settings_box as build_settings_box_impl,
    build_summary_strip as build_summary_strip_impl,
    build_ui as build_ui_impl,
    event_filter as event_filter_impl,
    refresh_summary_cards as refresh_summary_cards_impl,
    refresh_table as refresh_table_impl,
    set_browse_profile_button_enabled as set_browse_profile_button_enabled_impl,
    set_status_text as set_status_text_impl,
    sync_browse_profile_button_state as sync_browse_profile_button_state_impl,
    wrap_card as wrap_card_impl,
)
from desktop_py.ui.main_window_widgets import HoverTableWidget, RowHighlightDelegate, ToggleActionButton


BLOCKED_ACCOUNT_NAMES = {
    "山每北荒修僊1",
    "山每北荒修僊2",
    "山每北荒修僊4",
    "叨空SSR",
}

KEEP_ALIVE_INTERVAL_MS = 5 * 60 * 60 * 1000
ACTUAL_ACCOUNT_PREFIX = "当前实际账号："

class MainWindow(QMainWindow):
    # 当前工作台以双栏信息密度为优先，固定窗口尺寸是有意设计；
    # 若未来要支持小屏自适应，需要连同卡片排布与滚动策略一起重构。
    CLIENT_WIDTH = 1376
    CLIENT_HEIGHT = 956

    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_dirs()
        self.accounts = load_accounts()
        self.settings = load_settings()
        self._reset_current_main_account_name()
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
        self._keep_alive_timer = QTimer(self)
        self._keep_alive_timer.setSingleShot(True)
        self._keep_alive_timer.timeout.connect(self._handle_keep_alive_timeout)
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
        QTimer.singleShot(0, self._auto_validate_entry_account)
        QTimer.singleShot(0, self._apply_auto_fetch_push_schedule)
        QTimer.singleShot(0, self._apply_keep_alive_schedule)

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

    def _display_deadline_text(self, account: AccountConfig) -> str:
        return display_deadline_text(account)

    def _deadline_tooltip_text(self, account: AccountConfig) -> str:
        return deadline_tooltip_text(account)

    def _is_no_business_page_note(self, note: str) -> bool:
        return is_no_business_page_note(note)

    def _display_result_text(self, account: AccountConfig) -> str:
        return display_result_text(account)

    def _show_info(self, title: str, text: str) -> None:
        MessageDialog.show_info(self, title, text)

    def _show_warning(self, title: str, text: str) -> None:
        MessageDialog.show_warning(self, title, text)

    def _auto_validate_entry_account(self) -> None:
        auto_validate_entry_account_impl(self, os_module=os, validate_account_state_fn=validate_account_state)

    def _safe_validate_account_state(self, account: AccountConfig) -> bool:
        return safe_validate_account_state_impl(self, account, validate_account_state_fn=validate_account_state)

    def _entry_account(self) -> AccountConfig | None:
        return entry_account_impl(self)

    def _account_for_keep_alive(self, candidates: list[AccountConfig] | None = None) -> AccountConfig | None:
        return account_for_keep_alive_impl(self, candidates)

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

    def _display_account_name(self, account: AccountConfig) -> str:
        return display_account_name(account, self.settings.current_main_account_name)

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
        add_account_impl(self, account_dialog_cls=AccountDialog, default_state_path_fn=default_state_path, save_accounts_fn=save_accounts)

    def edit_account(self) -> None:
        edit_account_impl(self, account_dialog_cls=AccountDialog, default_state_path_fn=default_state_path, save_accounts_fn=save_accounts)

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
        login_selected_impl(self, save_login_state_with_profile_fn=save_login_state_with_profile, save_login_state_fn=save_login_state)

    def _mark_login(self, account: AccountConfig) -> None:
        mark_login_impl(self, account, datetime_cls=datetime, save_accounts_fn=save_accounts)

    def _login_start_message(self, account: AccountConfig) -> str:
        return login_start_message_impl(self, account)

    def validate_selected(self) -> None:
        validate_selected_impl(self, validate_account_state_fn=validate_account_state)

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
        return milliseconds_until_next_auto_fetch_push_impl(self, now, next_interval_fn=next_auto_fetch_push_interval_ms)

    def _handle_auto_fetch_push_timeout(self) -> None:
        handle_auto_fetch_push_timeout_impl(self)

    def _apply_keep_alive_schedule(self) -> None:
        apply_keep_alive_schedule_impl(self, keep_alive_interval_ms=KEEP_ALIVE_INTERVAL_MS)

    def _handle_keep_alive_timeout(self) -> None:
        handle_keep_alive_timeout_impl(self)

    def _run_keep_alive(self) -> None:
        if self._threads:
            self.append_log("静默保活已跳过：当前存在后台任务。")
            return
        account = self._account_for_keep_alive()
        if account is None:
            self.append_log("静默保活已跳过：未配置主账号。")
            return
        self._run_thread(
            lambda log: keep_alive_account_state(account, log, self.settings.browser_profile_dir),
            on_success=lambda ok: self._mark_keep_alive_result(account, bool(ok)),
            update_status=False,
        )

    def _mark_keep_alive_result(self, account: AccountConfig, valid: bool) -> None:
        mark_keep_alive_result_impl(self, account, valid, save_accounts_fn=save_accounts)

    def _run_auto_fetch_push(self) -> None:
        run_auto_fetch_push_impl(self)

    def _build_fetch_job(self, enabled_accounts: list[AccountConfig]):
        def job(log, progress, is_cancelled=None) -> list[FetchResult]:
            return fetch_accounts_batch(
                enabled_accounts,
                headless=self.settings.headless_fetch,
                logger=log,
                progress=progress,
                profile_dir=self.settings.browser_profile_dir,
                is_cancelled=is_cancelled,
            )

        return job

    def _mark_fetch_progress(self, result: FetchResult) -> None:
        mark_fetch_progress_impl(self, result)

    def _mark_fetch_result(self, account: AccountConfig, result: FetchResult) -> None:
        mark_fetch_result_impl(self, account, result, apply_fetch_result_fn=apply_fetch_result, save_accounts_fn=save_accounts)

    def _mark_batch_results(self, results: list[FetchResult]) -> None:
        mark_batch_results_impl(self, results, apply_batch_fetch_results_fn=apply_batch_fetch_results, save_accounts_fn=save_accounts)

    def send_summary(self) -> None:
        send_summary_impl(self)

    def _send_summary_with_webhook(self, webhook: str, append_batch_log: bool = False) -> None:
        if append_batch_log:
            self.append_log("批量抓取已完成。")
        results = [
            FetchResult(
                account_name=account.name,
                ok=account.last_status == "抓取成功",
                actual_account_name=self._actual_account_name_from_note(account.last_note),
                deadline_text=account.last_deadline,
                note=account.last_note,
                page_url=account.home_url,
            )
            for account in self.accounts if account.enabled
        ]
        self._run_thread(
            lambda _log: send_feishu_text(webhook, build_summary(results)),
            on_success=lambda _: self.append_log("飞书汇总已发送。"),
        )

    def _actual_account_name_from_note(self, note: str) -> str:
        return actual_account_name_from_note_impl(note, actual_account_prefix=ACTUAL_ACCOUNT_PREFIX)

    def _run_thread(self, job_builder, on_success, emit_log: bool = True, emit_failure_log: bool = True, update_status: bool = True, on_progress=None) -> None:
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
