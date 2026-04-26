from __future__ import annotations

from datetime import datetime, timedelta

from desktop_py.core.models import SESSION_STATUS_VALID, AccountConfig, FetchResult


def is_no_deadline_note(note: str) -> bool:
    return "未在详情页文本中提取到处理截止时间" in note


def next_auto_fetch_push_interval_ms(now: datetime | None = None) -> int:
    current = now or datetime.now()
    target = current.replace(hour=9, minute=0, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return max(int((target - current).total_seconds() * 1000), 1)


def apply_fetch_result(account: AccountConfig, result: FetchResult) -> str:
    account.last_fetch_at = result.fetched_at
    account.last_deadline = result.deadline_text
    account.last_status = "抓取成功" if result.ok or is_expected_empty_result_note(result.note) else "抓取失败"
    actual_note = f"当前实际账号：{result.actual_account_name}" if result.actual_account_name else ""
    account.last_note = "；".join(item for item in [result.note, actual_note] if item)
    account.feedback_url = result.page_url
    account.last_actual_account_name = result.actual_account_name or account.last_actual_account_name
    account.last_session_verified_at = result.fetched_at
    if result.ok:
        account.session_status = SESSION_STATUS_VALID
        account.last_session_error = ""
    return result.actual_account_name or account.name


def apply_batch_fetch_results(accounts: list[AccountConfig], results: list[FetchResult]) -> str:
    latest_actual_account_name = ""
    result_map = {result.account_name: result for result in results}
    for account in accounts:
        result = result_map.get(account.name)
        if result is None:
            continue
        account.last_fetch_at = result.fetched_at
        account.last_deadline = result.deadline_text
        account.last_status = "抓取成功" if result.ok or is_expected_empty_result_note(result.note) else "抓取失败"
        actual_note = f"当前实际账号：{result.actual_account_name}" if result.actual_account_name else ""
        account.last_note = "；".join(item for item in [result.note, actual_note] if item)
        if result.page_url:
            account.feedback_url = result.page_url
        if result.actual_account_name:
            account.last_actual_account_name = result.actual_account_name
        account.last_session_verified_at = result.fetched_at
        if result.ok:
            account.session_status = SESSION_STATUS_VALID
            account.last_session_error = ""
        if result.actual_account_name:
            latest_actual_account_name = result.actual_account_name
    return latest_actual_account_name


def is_no_business_page_note(note: str) -> bool:
    return "页面未出现业务 iframe" in note


def is_expected_empty_result_note(note: str) -> bool:
    return is_no_business_page_note(note) or is_no_deadline_note(note) or "当前账号无待处理申请" in note


def display_deadline_text(account: AccountConfig) -> str:
    if account.is_entry_account and not account.last_deadline:
        return "--"
    if is_no_business_page_note(account.last_note):
        return "无页面"
    if account.last_status == "抓取成功":
        return account.last_deadline or "无待处理"
    if account.last_status == "抓取失败":
        return account.last_note or "抓取失败"
    return account.last_deadline


def deadline_tooltip_text(account: AccountConfig) -> str:
    if account.last_status == "抓取失败" and account.last_note:
        return account.last_note
    return display_deadline_text(account)


def display_result_text(account: AccountConfig) -> str:
    if account.last_status in {"抓取成功", "登录有效", "已保存登录态"}:
        return "完成"
    if not account.last_status or account.last_status == "检测中":
        return ""
    return "失败"


def parse_deadline_for_sort(deadline_text: str) -> datetime | None:
    value = deadline_text.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def sort_accounts_for_display(accounts: list[AccountConfig]) -> list[AccountConfig]:
    indexed_accounts = list(enumerate(accounts))

    def sort_key(item: tuple[int, AccountConfig]) -> tuple[int, int, datetime, int]:
        index, account = item
        if account.is_entry_account:
            return (0, 0, datetime.min, index)
        deadline = parse_deadline_for_sort(account.last_deadline)
        if deadline is not None:
            return (1, 0, deadline, index)
        return (2, 0, datetime.max, index)

    return [account for _, account in sorted(indexed_accounts, key=sort_key)]


def display_account_name(account: AccountConfig, current_main_account_name: str) -> str:
    if account.is_entry_account:
        current_name = current_main_account_name.strip()
        if current_name:
            return f"主账号状态：{current_name}"
        return "主账号状态：未记录"
    return account.name
