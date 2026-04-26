from __future__ import annotations

import os
import random

from desktop_py.core.session_links import (
    normalize_group_feedback_urls,
    propagate_account_feedback_url,
    sync_account_feedback_url,
)


def initialize_window_state(
    window,
    *,
    ensure_runtime_dirs_fn,
    load_accounts_fn,
    load_settings_fn,
    save_accounts_fn,
    reset_current_main_account_name_fn,
) -> None:
    ensure_runtime_dirs_fn()
    window.accounts = load_accounts_fn()
    if normalize_group_feedback_urls(window.accounts):
        save_accounts_fn(window.accounts)
    window.settings = load_settings_fn()
    reset_current_main_account_name_fn()


def schedule_startup_jobs(window, *, timer_cls) -> None:
    timer_cls.singleShot(0, window._run_auto_renew)
    timer_cls.singleShot(0, window._auto_validate_entry_account)
    timer_cls.singleShot(0, window._apply_auto_fetch_push_schedule)
    timer_cls.singleShot(0, window._apply_auto_renew_schedule)


def auto_validate_entry_account(window, *, os_module, validate_account_state_fn) -> None:
    if os_module.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    account = entry_account(window)
    if account is None:
        return
    account.last_status = "检测中"
    account.last_note = ""
    window.refresh_table()
    window._run_thread(
        lambda _log: safe_validate_account_state(window, account, validate_account_state_fn=validate_account_state_fn),
        on_success=lambda ok: window._mark_validation(account, bool(ok)),
        emit_log=False,
        emit_failure_log=False,
        update_status=False,
    )


def safe_validate_account_state(window, account, *, validate_account_state_fn) -> bool:
    try:
        return bool(validate_account_state_fn(account, None, window.settings.browser_profile_dir))
    except Exception:
        return False


def entry_account(window):
    return next((item for item in window.accounts if item.is_entry_account), None)


def account_for_auto_renew(window, candidates: list | None = None):
    current_entry_account = entry_account(window)
    if current_entry_account is not None:
        return current_entry_account
    if candidates:
        return candidates[0]
    return None


def selected_index(window) -> int:
    selected = window.table.selectionModel().selectedRows()
    return selected[0].row() if selected else -1


def selected_indexes(window) -> list[int]:
    selected = window.table.selectionModel().selectedRows()
    return sorted(item.row() for item in selected)


def selected_account(window):
    index = window.selected_index()
    return window.accounts[index] if 0 <= index < len(window.accounts) else None


def handle_selection_changed(window) -> None:
    window.table.viewport().update()
    window._update_action_buttons()


def update_action_buttons(window) -> None:
    current_indexes = window.selected_indexes()
    single_selected = len(current_indexes) == 1
    account = window.accounts[current_indexes[0]] if single_selected else None
    if window.login_button is not None:
        window.login_button.setEnabled(bool(account and account.is_entry_account))
    if window.renew_button is not None:
        window.renew_button.setEnabled(bool(account and account.is_entry_account))
    if window.edit_button is not None:
        window.edit_button.setEnabled(bool(account and account.is_entry_account))
    if window.import_button is not None:
        window.import_button.setEnabled(bool(account and account.is_entry_account))
    if window.validate_button is not None:
        window.validate_button.setEnabled(bool(account and account.is_entry_account))
    if window.fetch_selected_button is not None:
        window.fetch_selected_button.setEnabled(bool(account and not account.is_entry_account))
    if window.delete_button is not None:
        window.delete_button.setEnabled(bool(current_indexes))
    if window.stop_fetch_button is not None:
        window.stop_fetch_button.setEnabled(bool(window._threads))


def stop_fetching(window) -> None:
    if not window._threads:
        window._show_info("提示", "当前没有正在执行的抓取或推送任务。")
        return
    window._task_runner.cancel_all()
    window._update_action_buttons()
    window.append_log("已请求停止当前后台抓取任务，正在等待当前任务退出。")
    window.statusBar().showMessage("正在停止后台任务", 4000)
    window._set_status_text("正在停止后台任务")


def update_current_main_account(window, account_name: str, *, save_settings_fn) -> None:
    current_name = account_name.strip()
    if not current_name:
        return
    window.settings.current_main_account_name = current_name
    save_settings_fn(window.settings)


def reset_current_main_account_name(window, *, save_settings_fn) -> None:
    if not window.settings.current_main_account_name.strip():
        return
    window.settings.current_main_account_name = ""
    save_settings_fn(window.settings)


def select_imported_accounts(window, *, selection_flag) -> None:
    window.table.clearSelection()
    selected_any = False
    for row, account in enumerate(window.accounts):
        if account.is_entry_account:
            continue
        window.table.selectionModel().select(
            window.table.model().index(row, 0),
            selection_flag.Select | selection_flag.Rows,
        )
        selected_any = True
    if not selected_any:
        window._show_info("提示", "没有可全选的导入账号。")
    window._update_action_buttons()


def save_current_settings(
    window,
    *,
    app_settings_cls,
    validate_shared_browser_profile_dir_fn,
    save_settings_fn,
    ) -> None:
    try:
        browser_profile_dir = validate_shared_browser_profile_dir_fn(window.profile_dir_edit.text().strip())
        window.settings = app_settings_cls(
            feishu_webhook=window.webhook_edit.text().strip(),
            login_wait_seconds=window.settings.login_wait_seconds,
            headless_fetch=window.settings.headless_fetch,
            browser_profile_dir=browser_profile_dir,
            current_main_account_name=window.settings.current_main_account_name,
            auto_fetch_push_enabled=window.auto_fetch_push_switch.isChecked()
            if window.auto_fetch_push_switch is not None
            else False,
        )
        save_settings_fn(window.settings)
    except ValueError as exc:
        window._show_warning("参数错误", str(exc))
        return
    window.profile_dir_edit.setText(browser_profile_dir)
    window._apply_auto_fetch_push_schedule()
    window.append_log("全局设置已保存。")
    window.statusBar().showMessage("设置已保存", 4000)


def choose_profile_dir(window, *, file_dialog, prepare_shared_browser_profile_dir_fn) -> None:
    target = file_dialog.getExistingDirectory(window, "选择共享浏览器资料目录", window.profile_dir_edit.text().strip())
    if target:
        try:
            profile_dir = prepare_shared_browser_profile_dir_fn(target)
        except (OSError, ValueError) as exc:
            window._show_warning("目录错误", str(exc))
            return
        window.profile_dir_edit.setText(profile_dir)


def add_account(window, *, account_dialog_cls, default_state_path_fn, save_accounts_fn) -> None:
    dialog = account_dialog_cls(parent=window)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return
    account = dialog.build_account()
    if not account.name:
        window._show_warning("提示", "账号名称不能为空。")
        return
    if any(item.name == account.name for item in window.accounts):
        window._show_warning("提示", f"账号“{account.name}”已存在。")
        return
    if not account.state_path:
        account.state_path = default_state_path_fn(window.accounts)
    window.accounts.append(account)
    sync_account_feedback_url(window.accounts, account)
    propagate_account_feedback_url(window.accounts, account)
    save_accounts_fn(window.accounts)
    window.refresh_table()
    window.append_log(f"已新增账号：{account.name}，登录态文件：{account.state_path}")


def edit_account(window, *, account_dialog_cls, default_state_path_fn, save_accounts_fn) -> None:
    account = window.selected_account()
    if not account:
        window._show_info("提示", "请先选择一个账号。")
        return
    if not account.is_entry_account:
        window._show_info("提示", "导入账号不允许编辑。")
        return
    dialog = account_dialog_cls(account, parent=window)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return
    updated = dialog.build_account()
    if not updated.name:
        window._show_warning("提示", "账号名称不能为空。")
        return
    duplicate = any(
        item.name == updated.name for idx, item in enumerate(window.accounts) if idx != window.selected_index()
    )
    if duplicate:
        window._show_warning("提示", f"账号“{updated.name}”已存在。")
        return
    original_state_path = account.state_path
    if not updated.state_path:
        updated.state_path = account.state_path or default_state_path_fn(window.accounts)
    if updated.state_path == original_state_path:
        updated.feedback_url = account.feedback_url
    else:
        updated.feedback_url = ""
    updated.last_login_at = account.last_login_at
    updated.last_fetch_at = account.last_fetch_at
    updated.last_deadline = account.last_deadline
    updated.last_status = account.last_status
    updated.last_note = account.last_note
    updated.session_status = account.session_status
    updated.session_source = account.session_source
    updated.last_session_verified_at = account.last_session_verified_at
    updated.last_session_renewed_at = account.last_session_renewed_at
    updated.last_session_error = account.last_session_error
    updated.last_actual_account_name = account.last_actual_account_name
    window.accounts[window.selected_index()] = updated
    sync_account_feedback_url(window.accounts, updated)
    propagate_account_feedback_url(window.accounts, updated)
    save_accounts_fn(window.accounts)
    window.refresh_table()
    window.append_log(f"已更新账号：{updated.name}")


def import_accounts(window, *, fetch_switchable_accounts_fn) -> None:
    base_account = window.selected_account()
    if not base_account:
        window._show_info("提示", "请先选择一个已登录的账号作为读取入口。")
        return
    if not base_account.is_entry_account:
        window._show_info("提示", "只有主账号可以导入账号列表。")
        return
    window._run_thread(
        lambda log: fetch_switchable_accounts_fn(
            base_account,
            headless=window.settings.headless_fetch,
            logger=log,
            profile_dir=window.settings.browser_profile_dir,
        ),
        on_success=lambda names: window._merge_imported_accounts(base_account, names),
    )


def merge_imported_accounts(
    window,
    base_account,
    names: list[str],
    *,
    blocked_account_names: set[str],
    account_config_cls,
    save_accounts_fn,
) -> None:
    existing = {account.name for account in window.accounts}
    imported = 0
    for name in names:
        if name in blocked_account_names or name in existing:
            continue
        window.accounts.append(
            account_config_cls(
                name=name,
                state_path=base_account.state_path,
                is_entry_account=False,
                feedback_url="",
                home_url=base_account.home_url,
                enabled=True,
            )
        )
        existing.add(name)
        imported += 1

    save_accounts_fn(window.accounts)
    window.refresh_table()
    window.append_log(f"已导入 {imported} 个新账号。")


def delete_account(window, *, message_dialog_cls, save_accounts_fn) -> None:
    current_indexes = window.selected_indexes()
    if not current_indexes:
        window._show_info("提示", "请先选择一个账号。")
        return
    removed_names = [window.accounts[index].name for index in current_indexes]
    if not message_dialog_cls.ask_confirm(
        window,
        "确认删除",
        f"确认删除已选中的 {len(removed_names)} 个账号吗？",
        confirm_text="删除",
        cancel_text="取消",
    ):
        return
    for index in reversed(current_indexes):
        window.accounts.pop(index)
    save_accounts_fn(window.accounts)
    window.refresh_table()
    window.append_log(f"已删除账号：{'、'.join(removed_names)}")


def login_selected(window, *, save_login_state_with_profile_fn, save_login_state_fn) -> None:
    account = window.selected_account()
    if not account:
        window._show_info("提示", "请先选择一个账号。")
        return
    if not account.is_entry_account:
        window._show_info("提示", "导入账号不能直接保存登录态，请选择入口账号。")
        return
    window.append_log(window._login_start_message(account))
    window.statusBar().showMessage("已打开浏览器，请完成扫码登录。", 8000)
    window._run_thread(
        lambda log, _progress=None, is_cancelled=None: (
            save_login_state_with_profile_fn(
                account, window.settings.login_wait_seconds, window.settings.browser_profile_dir, log, is_cancelled
            )
            if window.settings.browser_profile_dir.strip()
            else save_login_state_fn(account, window.settings.login_wait_seconds, log, is_cancelled)
        ),
        on_success=lambda _: window._mark_login(account),
    )


def mark_login(window, account, *, datetime_cls, save_accounts_fn, close_all_group_runtimes_fn=None) -> None:
    account.last_login_at = datetime_cls.now().strftime("%Y-%m-%d %H:%M:%S")
    account.last_status = "已保存登录态"
    account.last_note = "可继续导入账号或直接抓取"
    account.session_status = SESSION_STATUS_VALID
    account.last_session_error = ""
    for item in window.accounts:
        if item is account:
            continue
        if item.state_path == account.state_path:
            item.feedback_url = ""
    propagate_account_feedback_url(window.accounts, account)
    if callable(close_all_group_runtimes_fn):
        close_all_group_runtimes_fn()
    save_accounts_fn(window.accounts)
    window.refresh_table()
    window.append_log(f"账号 {account.name} 的登录态已保存完成。")
    window.statusBar().showMessage("登录态已保存", 5000)


def login_start_message(window, account) -> str:
    if window.settings.browser_profile_dir.strip():
        return (
            f"正在为账号 {account.name} 打开共享浏览器资料目录。"
            f"请在 {window.settings.login_wait_seconds} 秒内完成扫码，登录成功后保持页面打开等待自动保存。"
        )
    return (
        f"正在为账号 {account.name} 打开独立登录窗口。"
        f"请在 {window.settings.login_wait_seconds} 秒内完成扫码，登录成功后保持页面打开等待自动保存。"
    )


def validate_selected(window, *, validate_account_state_fn) -> None:
    account = window.selected_account()
    if not account:
        window._show_info("提示", "请先选择一个账号。")
        return
    if not account.is_entry_account:
        window._show_info("提示", "导入账号不能校验登录态，请选择主账号。")
        return
    window._run_thread(
        lambda log: validate_account_state_fn(account, log, window.settings.browser_profile_dir),
        on_success=lambda ok: window._mark_validation(account, bool(ok)),
    )


def renew_selected(window, *, renew_account_state_fn) -> None:
    account = window.selected_account()
    if not account:
        window._show_info("提示", "请先选择一个账号。")
        return
    if not account.is_entry_account:
        window._show_info("提示", "导入账号不能登录续期，请选择主账号。")
        return
    window._run_thread(
        lambda log: renew_account_state_fn(
            account,
            log,
            window.settings.browser_profile_dir,
            window.settings.headless_fetch,
        ),
        on_success=lambda ok: window._mark_auto_renew_result(account, bool(ok)),
    )


def mark_validation(window, account, valid: bool, *, save_accounts_fn) -> None:
    account.last_status = "登录有效" if valid else "登录失效"
    if valid:
        account.last_note = "可直接抓取" if account.session_status != SESSION_STATUS_STALE else "登录态接近失效，建议优先续期"
    else:
        account.last_note = account.last_session_error or "请重新保存登录态"
    if valid:
        propagate_account_feedback_url(window.accounts, account)
    save_accounts_fn(window.accounts)
    window.refresh_table()


def fetch_selected(window, *, fetch_account_fn) -> None:
    account = window.selected_account()
    if not account:
        window._show_info("提示", "请先选择一个账号。")
        return
    if account.is_entry_account:
        window._show_info("提示", "主账号不参与抓取，请选择导入账号。")
        return

    window._run_thread(
        lambda log, _progress=None, is_cancelled=None: fetch_account_fn(
            account,
            0,
            window.settings.headless_fetch,
            log,
            window.settings.browser_profile_dir,
            is_cancelled,
        ),
        on_success=lambda result: window._mark_fetch_result(account, result),
    )


def _enabled_imported_accounts(window):
    return [account for account in window.accounts if account.enabled and not account.is_entry_account]


def fetch_all(window) -> None:
    enabled_accounts = _enabled_imported_accounts(window)
    if not enabled_accounts:
        window._show_info("提示", "没有可抓取的导入账号。")
        return

    window._run_thread(
        window._build_fetch_job(enabled_accounts),
        on_success=lambda _results: window.append_log("批量抓取已完成。"),
        on_progress=window._mark_fetch_progress,
    )


def auto_fetch_and_send(window) -> None:
    webhook = window.webhook_edit.text().strip()
    window.settings.feishu_webhook = webhook
    if not webhook:
        window._show_warning("提示", "请先填写飞书 Webhook。")
        return
    enabled_accounts = _enabled_imported_accounts(window)
    if not enabled_accounts:
        window._show_info("提示", "没有可抓取的导入账号。")
        return
    window._run_thread(
        window._build_fetch_job(enabled_accounts),
        on_success=lambda results: _handle_auto_summary_after_fetch(window, webhook, results),
        on_progress=window._mark_fetch_progress,
    )


def handle_auto_fetch_push_toggled(window, checked: bool, *, save_settings_fn) -> None:
    window.settings.auto_fetch_push_enabled = checked
    save_settings_fn(window.settings)
    if checked:
        window.append_log("已开启自动抓取推送，每天 09:00 自动执行。")
    else:
        window.append_log("已关闭自动抓取推送。")
    window._apply_auto_fetch_push_schedule()


def apply_auto_fetch_push_schedule(window) -> None:
    window._auto_fetch_timer.stop()
    if not window.settings.auto_fetch_push_enabled:
        return
    interval = window._milliseconds_until_next_auto_fetch_push()
    window._auto_fetch_timer.start(interval)


def milliseconds_until_next_auto_fetch_push(window, now=None, *, next_interval_fn) -> int:
    return next_interval_fn(now)


def handle_auto_fetch_push_timeout(window) -> None:
    window._apply_auto_fetch_push_schedule()
    window._run_auto_fetch_push()


def apply_auto_renew_schedule(window, *, min_auto_renew_interval_ms: int, max_auto_renew_interval_ms: int) -> None:
    window._auto_renew_timer.stop()
    interval = random.randint(min_auto_renew_interval_ms, max_auto_renew_interval_ms)
    window._auto_renew_timer.start(interval)


def handle_auto_renew_timeout(window) -> None:
    window._apply_auto_renew_schedule()
    window._run_auto_renew()


def run_auto_renew(window, *, renew_account_state_fn) -> None:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    if window._threads:
        window.append_log("自动续期已跳过：当前存在后台任务。")
        return
    account = account_for_auto_renew(window)
    if account is None:
        window.append_log("自动续期已跳过：未配置主账号。")
        return
    window._run_thread(
        lambda log: renew_account_state_fn(
            account,
            log,
            window.settings.browser_profile_dir,
            window.settings.headless_fetch,
        ),
        on_success=lambda ok: window._mark_auto_renew_result(account, bool(ok)),
        update_status=False,
    )


def mark_auto_renew_result(window, account, valid: bool, *, save_accounts_fn) -> None:
    account.last_status = "登录有效" if valid else "登录失效"
    account.last_note = "自动续期成功，可直接抓取" if valid else (account.last_session_error or "自动续期失败，请重新保存登录态")
    save_accounts_fn(window.accounts)
    window.refresh_table()


def run_auto_fetch_push(window) -> None:
    webhook = window.webhook_edit.text().strip() or window.settings.feishu_webhook.strip()
    if not webhook:
        window.append_log("自动抓取推送已跳过：未配置飞书 Webhook。")
        return
    enabled_accounts = _enabled_imported_accounts(window)
    if not enabled_accounts:
        window.append_log("自动抓取推送已跳过：没有可抓取的导入账号。")
        return
    window.settings.feishu_webhook = webhook
    window.append_log("开始执行每日自动抓取推送。")
    window._run_thread(
        window._build_fetch_job(enabled_accounts),
        on_success=lambda results: _handle_auto_summary_after_fetch(window, webhook, results),
        on_progress=window._mark_fetch_progress,
    )


AUTO_PUSH_SKIP_NOTE = "当前登录态未自动跳入后台页，且没有可复用的历史反馈页地址，无法启动自动切换账号。"


def should_skip_auto_summary_for_results(results: list) -> bool:
    if not results:
        return False
    return all(str(getattr(result, "note", "") or "").strip() == AUTO_PUSH_SKIP_NOTE for result in results)


def _handle_auto_summary_after_fetch(window, webhook: str, results: list) -> None:
    if should_skip_auto_summary_for_results(results):
        window.append_log("批量抓取已完成。")
        window.append_log("自动抓取推送已跳过：当前登录态未进入后台页，且没有可复用的历史反馈页地址。")
        return
    window._send_summary_with_webhook(webhook, append_batch_log=True)


def build_fetch_job(window, enabled_accounts: list, *, fetch_accounts_batch_fn):
    def job(log, progress, is_cancelled=None):
        return fetch_accounts_batch_fn(
            enabled_accounts,
            headless=window.settings.headless_fetch,
            logger=log,
            progress=progress,
            profile_dir=window.settings.browser_profile_dir,
            is_cancelled=is_cancelled,
        )

    return job


def mark_fetch_progress(window, result) -> None:
    account = next((item for item in window.accounts if item.name == result.account_name), None)
    if account is None:
        return
    window._mark_fetch_result(account, result)


def mark_fetch_result(window, account, result, *, apply_fetch_result_fn, save_accounts_fn) -> None:
    current_main_account_name = apply_fetch_result_fn(account, result)
    window.refresh_table()
    try:
        save_accounts_fn(window.accounts)
    except Exception as exc:
        window.append_log(f"保存抓取结果失败：{exc}")
    try:
        window._update_current_main_account(current_main_account_name)
    except Exception as exc:
        window.append_log(f"更新当前主账号失败：{exc}")
    else:
        window.refresh_table()


def mark_batch_results(window, results: list, *, apply_batch_fetch_results_fn, save_accounts_fn) -> None:
    latest_actual_account_name = apply_batch_fetch_results_fn(window.accounts, results)
    window.refresh_table()
    try:
        save_accounts_fn(window.accounts)
    except Exception as exc:
        window.append_log(f"保存批量抓取结果失败：{exc}")
    if latest_actual_account_name:
        try:
            window._update_current_main_account(latest_actual_account_name)
        except Exception as exc:
            window.append_log(f"更新当前主账号失败：{exc}")
        else:
            window.refresh_table()
    window.append_log("批量抓取已完成。")


def send_summary(window) -> None:
    webhook = window.webhook_edit.text().strip()
    window.settings.feishu_webhook = webhook
    if not webhook:
        window._show_warning("提示", "请先填写飞书 Webhook。")
        return
    window._send_summary_with_webhook(webhook)


def send_summary_with_webhook(
    window,
    webhook: str,
    append_batch_log: bool = False,
    *,
    build_summary_fn,
    send_feishu_text_fn,
    fetch_result_cls,
    actual_account_prefix: str,
    save_accounts_fn,
) -> None:
    if append_batch_log:
        window.append_log("批量抓取已完成。")
    results = [
        fetch_result_cls(
            account_name=account.name,
            ok=account.last_status == "抓取成功",
            actual_account_name=actual_account_name_from_note(
                account.last_note, actual_account_prefix=actual_account_prefix
            ),
            deadline_text=account.last_deadline,
            note=account.last_note,
            page_url=account.home_url,
        )
        for account in window.accounts
        if account.enabled
    ]
    window._run_thread(
        lambda _log: send_feishu_text_fn(webhook, build_summary_fn(results)),
        on_success=lambda _: clear_pushed_fetch_state(window, save_accounts_fn=save_accounts_fn),
    )


def clear_pushed_fetch_state(window, *, save_accounts_fn) -> None:
    for account in window.accounts:
        if account.is_entry_account or not account.enabled:
            continue
        if account.last_status != "抓取成功":
            continue
        account.last_deadline = ""
        account.last_status = ""
        account.last_note = ""
    window.refresh_table()
    try:
        save_accounts_fn(window.accounts)
    except Exception as exc:
        window.append_log(f"清理推送后状态失败：{exc}")
    window.append_log("飞书汇总已发送。")
    window.append_log("已清理推送后的抓取状态。")


def actual_account_name_from_note(note: str, *, actual_account_prefix: str) -> str:
    for part in note.split("；"):
        text = part.strip()
        if text.startswith(actual_account_prefix):
            return text.removeprefix(actual_account_prefix).strip()
    return ""


def run_thread(
    window,
    job_builder,
    on_success,
    *,
    emit_log: bool = True,
    emit_failure_log: bool = True,
    update_status: bool = True,
    on_progress=None,
) -> None:
    window._task_runner.run(
        job_builder,
        on_success,
        emit_log=emit_log,
        emit_failure_log=emit_failure_log,
        update_status=update_status,
        on_progress=on_progress,
    )


def handle_thread_finished(window, thread) -> None:
    window._task_runner.handle_finished(thread)
