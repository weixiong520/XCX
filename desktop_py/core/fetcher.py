from __future__ import annotations

from datetime import datetime
from pathlib import Path

from playwright.sync_api import Locator, Page

from desktop_py.core.browser_runtime import configure_playwright_environment

configure_playwright_environment()

from playwright.sync_api import sync_playwright

from desktop_py.core.fetcher_page_strategy import (
    build_detail_result,
    build_empty_refund_result,
    captures_indicate_non_empty_refunds,
    confirm_detail_deadline,
    confirm_empty_refund_list,
    has_pending_refund_signal,
    is_empty_refund_list,
    open_feedback_page,
    register_response_capture,
    resolve_frame_locator,
)
from desktop_py.core.fetcher_pipeline import (
    fetch_account_impl,
    fetch_account_in_page_impl,
    fetch_accounts_batch_impl,
    resolve_bootstrap_url_impl,
)
from desktop_py.core.fetcher_runtime import (
    acquire_group_runtime,
    invalidate_group_runtime,
    release_group_runtime,
    runtime_current_account_name,
    should_invalidate_runtime,
    update_runtime_current_account_name,
)
from desktop_py.core.fetcher_session import (
    renew_account_state_impl,
    save_login_state_impl,
    save_login_state_with_profile_impl,
    validate_account_state_impl,
)
from desktop_py.core.fetcher_support import (
    SWITCH_ACCOUNT_LIST_RETRY_LIMIT,
    _capture_response_payload,
    _close_context_and_browser,
    _close_page,
    _fallback_from_responses,
    _log,
    build_feedback_url,
    business_iframe_selector,
    create_browser_context,
    safe_page_content,
    wait_for_iframe_ready,
    wait_for_url_contains,
    wait_or_cancel,
)
from desktop_py.core.fetcher_support import (
    wait_for_current_account_name as wait_for_current_account_name_impl,
)
from desktop_py.core.fetcher_switching import (
    extract_current_account_name_impl,
    fetch_switchable_accounts_impl,
    find_switch_entry_impl,
    list_switchable_accounts_impl,
    maybe_expand_account_menu_impl,
    open_switch_account_dialog_impl,
    prepare_switch_account_page_impl,
    should_retry_switch_from_home_impl,
    should_switch_account_impl,
    should_switch_for_account_impl,
    switch_dialog_ready_impl,
    switch_to_account_impl,
    wait_for_account_switch_stable_impl,
    wait_for_locator_items_impl,
    wait_for_switch_account_items_impl,
)
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.parser import extract_labeled_datetime
from desktop_py.core.store import account_output_dir, validate_shared_browser_profile_dir

# 稳定公开接口只包含主流程入口；
# 其余符号继续保留在模块命名空间中，仅用于兼容现有测试和局部内部调用。
PUBLIC_FETCHER_API = (
    "save_login_state",
    "save_login_state_with_profile",
    "fetch_switchable_accounts",
    "fetch_account",
    "fetch_accounts_batch",
    "validate_account_state",
    "renew_account_state",
)

__all__ = [
    *PUBLIC_FETCHER_API,
]


def find_switch_entry(page: Page) -> Locator | None:
    return find_switch_entry_impl(page)


def _switch_dialog_ready(page: Page) -> bool:
    return switch_dialog_ready_impl(page)


def _maybe_expand_account_menu(page: Page) -> None:
    maybe_expand_account_menu_impl(page)


def wait_for_current_account_name(
    page: Page,
    expected_name: str,
    timeout_ms: int = 5000,
    is_cancelled: callable | None = None,
) -> str:
    return wait_for_current_account_name_impl(
        page,
        expected_name,
        timeout_ms=timeout_ms,
        is_cancelled=is_cancelled,
        extract_current_account_name_fn=extract_current_account_name,
    )


def should_retry_switch_from_home(current_url: str, home_url: str, has_switch_entry: bool) -> bool:
    return should_retry_switch_from_home_impl(current_url, home_url, has_switch_entry)


def prepare_switch_account_page(page: Page, home_url: str = "", logger: callable | None = None) -> None:
    prepare_switch_account_page_impl(
        page,
        home_url,
        logger,
        switch_dialog_ready_fn=_switch_dialog_ready,
        find_switch_entry_fn=find_switch_entry,
        should_retry_switch_from_home_fn=should_retry_switch_from_home,
        log_fn=_log,
        wait_for_url_contains_fn=wait_for_url_contains,
    )


def open_switch_account_dialog(page: Page, timeout_ms: int = 12000) -> None:
    open_switch_account_dialog_impl(
        page,
        timeout_ms=timeout_ms,
        switch_dialog_ready_fn=_switch_dialog_ready,
        find_switch_entry_fn=find_switch_entry,
        maybe_expand_account_menu_fn=_maybe_expand_account_menu,
        extract_current_account_name_fn=extract_current_account_name,
    )


def extract_current_account_name(page: Page) -> str:
    return extract_current_account_name_impl(page, safe_page_content_fn=safe_page_content)


def save_login_state(
    account: AccountConfig,
    wait_seconds: int,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
) -> str:
    return save_login_state_impl(
        account,
        wait_seconds,
        logger,
        is_cancelled,
        sync_playwright_fn=sync_playwright,
        datetime_cls=datetime,
        log_fn=_log,
        wait_or_cancel_fn=wait_or_cancel,
        close_page_fn=_close_page,
        close_context_and_browser_fn=_close_context_and_browser,
    )


def save_login_state_with_profile(
    account: AccountConfig,
    wait_seconds: int,
    profile_dir: str,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
) -> str:
    return save_login_state_with_profile_impl(
        account,
        wait_seconds,
        profile_dir,
        logger,
        is_cancelled,
        sync_playwright_fn=sync_playwright,
        datetime_cls=datetime,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        log_fn=_log,
        wait_or_cancel_fn=wait_or_cancel,
        close_page_fn=_close_page,
        close_context_and_browser_fn=_close_context_and_browser,
    )


def switch_to_account(page: Page, account_name: str, home_url: str = "", logger: callable | None = None) -> None:
    switch_to_account_impl(
        page,
        account_name,
        home_url,
        logger,
        prepare_switch_account_page_fn=prepare_switch_account_page,
        open_switch_account_dialog_fn=open_switch_account_dialog,
        wait_for_switch_account_items_fn=wait_for_switch_account_items,
        wait_for_current_account_name_fn=wait_for_current_account_name,
        wait_for_account_switch_stable_fn=lambda target_page, expected_account_name, home_url="": (
            wait_for_account_switch_stable_impl(
                target_page,
                expected_account_name,
                home_url,
                extract_current_account_name_fn=extract_current_account_name,
                wait_for_url_contains_fn=wait_for_url_contains,
                wait_or_cancel_fn=wait_or_cancel,
            )
        ),
        log_fn=_log,
    )


def should_switch_account(current_account_name: str, target_account_name: str) -> bool:
    return should_switch_account_impl(current_account_name, target_account_name)


def should_switch_for_account(account: AccountConfig, current_account_name: str) -> bool:
    return should_switch_for_account_impl(account, current_account_name)


def list_switchable_accounts(page: Page, home_url: str = "", logger: callable | None = None) -> list[str]:
    return list_switchable_accounts_impl(
        page,
        home_url,
        logger,
        prepare_switch_account_page_fn=prepare_switch_account_page,
        open_switch_account_dialog_fn=open_switch_account_dialog,
        wait_for_switch_account_items_fn=wait_for_switch_account_items,
    )


def _wait_for_locator_items(page: Page, locator, timeout_ms: int = 1800, interval_ms: int = 200) -> bool:
    return wait_for_locator_items_impl(page, locator, timeout_ms=timeout_ms, interval_ms=interval_ms)


def wait_for_switch_account_items(
    page: Page,
    selector: str,
    logger: callable | None = None,
    retry_limit: int = SWITCH_ACCOUNT_LIST_RETRY_LIMIT,
    is_cancelled: callable | None = None,
):
    return wait_for_switch_account_items_impl(
        page,
        selector,
        logger,
        retry_limit=retry_limit,
        is_cancelled=is_cancelled,
        wait_for_locator_items_fn=_wait_for_locator_items,
        log_fn=_log,
        wait_or_cancel_fn=wait_or_cancel,
        open_switch_account_dialog_fn=open_switch_account_dialog,
    )


def fetch_switchable_accounts(
    account: AccountConfig,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
) -> list[str]:
    names = fetch_switchable_accounts_impl(
        account,
        headless=headless,
        logger=logger,
        profile_dir=profile_dir,
        sync_playwright_fn=sync_playwright,
        path_exists_fn=Path.exists,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        create_browser_context_fn=create_browser_context,
        wait_for_url_contains_fn=wait_for_url_contains,
        list_switchable_accounts_fn=list_switchable_accounts,
        close_page_fn=_close_page,
        close_context_and_browser_fn=_close_context_and_browser,
    )
    _log(logger, f"已读取到 {len(names)} 个可切换账号。")
    return names


def resolve_bootstrap_url(account: AccountConfig, output_dir: Path) -> str:
    return resolve_bootstrap_url_impl(account, output_dir)


def _fetch_account_in_page(
    page,
    context,
    account: AccountConfig,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> FetchResult:
    return fetch_account_in_page_impl(
        page,
        context,
        account,
        logger,
        profile_dir,
        is_cancelled,
        account_output_dir_fn=account_output_dir,
        register_response_capture_fn=register_response_capture,
        capture_response_payload_fn=_capture_response_payload,
        resolve_bootstrap_url_fn=resolve_bootstrap_url,
        wait_for_url_contains_fn=wait_for_url_contains,
        extract_current_account_name_fn=extract_current_account_name,
        should_switch_for_account_fn=should_switch_for_account,
        switch_to_account_fn=switch_to_account,
        log_fn=_log,
        open_feedback_page_fn=open_feedback_page,
        build_feedback_url_fn=build_feedback_url,
        wait_for_iframe_ready_fn=wait_for_iframe_ready,
        resolve_frame_locator_fn=resolve_frame_locator,
        business_iframe_selector_fn=business_iframe_selector,
        safe_page_content_fn=safe_page_content,
        is_empty_refund_list_fn=is_empty_refund_list,
        confirm_empty_refund_list_fn=lambda **kwargs: confirm_empty_refund_list(
            **kwargs,
            has_pending_refund_signal_fn=has_pending_refund_signal,
            captures_indicate_non_empty_refunds_fn=captures_indicate_non_empty_refunds,
            wait_or_cancel_fn=wait_or_cancel,
        ),
        build_empty_refund_result_fn=build_empty_refund_result,
        build_detail_result_fn=lambda **kwargs: build_detail_result(
            **kwargs,
            confirm_detail_deadline_fn=lambda **detail_kwargs: confirm_detail_deadline(
                **detail_kwargs,
                extract_labeled_datetime_fn=extract_labeled_datetime,
                fallback_from_responses_fn=_fallback_from_responses,
                wait_or_cancel_fn=wait_or_cancel,
            ),
        ),
    )


def fetch_account(
    account: AccountConfig,
    wait_seconds: int,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> FetchResult:
    return fetch_account_impl(
        account,
        wait_seconds,
        headless=headless,
        logger=logger,
        profile_dir=profile_dir,
        is_cancelled=is_cancelled,
        sync_playwright_fn=sync_playwright,
        path_exists_fn=Path.exists,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        create_browser_context_fn=create_browser_context,
        fetch_account_in_page_fn=_fetch_account_in_page,
        acquire_group_runtime_fn=acquire_group_runtime,
        release_group_runtime_fn=release_group_runtime,
        invalidate_group_runtime_fn=invalidate_group_runtime,
        runtime_current_account_name_fn=runtime_current_account_name,
        update_runtime_current_account_name_fn=update_runtime_current_account_name,
        should_invalidate_runtime_fn=should_invalidate_runtime,
    )


def fetch_accounts_batch(
    accounts: list[AccountConfig],
    headless: bool = True,
    logger: callable | None = None,
    progress: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> list[FetchResult]:
    return fetch_accounts_batch_impl(
        accounts,
        headless=headless,
        logger=logger,
        progress=progress,
        profile_dir=profile_dir,
        is_cancelled=is_cancelled,
        sync_playwright_fn=sync_playwright,
        path_exists_fn=Path.exists,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        create_browser_context_fn=create_browser_context,
        fetch_account_in_page_fn=_fetch_account_in_page,
        acquire_group_runtime_fn=acquire_group_runtime,
        release_group_runtime_fn=release_group_runtime,
        invalidate_group_runtime_fn=invalidate_group_runtime,
        update_runtime_current_account_name_fn=update_runtime_current_account_name,
        should_invalidate_runtime_fn=should_invalidate_runtime,
    )


def validate_account_state(account: AccountConfig, logger: callable | None = None, profile_dir: str = "") -> bool:
    return validate_account_state_impl(
        account,
        logger=logger,
        profile_dir=profile_dir,
        sync_playwright_fn=sync_playwright,
        path_exists_fn=Path.exists,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        create_browser_context_fn=create_browser_context,
        wait_for_url_contains_fn=wait_for_url_contains,
        close_page_fn=_close_page,
        close_context_and_browser_fn=_close_context_and_browser,
        log_fn=_log,
    )


def renew_account_state(account: AccountConfig, logger: callable | None = None, profile_dir: str = "") -> bool:
    return renew_account_state_impl(
        account,
        logger=logger,
        profile_dir=profile_dir,
        sync_playwright_fn=sync_playwright,
        path_exists_fn=Path.exists,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir,
        create_browser_context_fn=create_browser_context,
        wait_for_url_contains_fn=wait_for_url_contains,
        close_page_fn=_close_page,
        close_context_and_browser_fn=_close_context_and_browser,
        log_fn=_log,
    )
