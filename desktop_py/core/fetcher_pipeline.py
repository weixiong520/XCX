from __future__ import annotations

from pathlib import Path

from desktop_py.core.fetcher_support import (
    CancelledError,
    FetchError,
    ensure_account_session_available,
    normalize_profile_dir,
)
from desktop_py.core.models import AccountConfig, FetchResult


def resolve_bootstrap_url_impl(account: AccountConfig, output_dir: Path) -> str:
    return account.home_url


def fetch_account_in_page_impl(
    page,
    context,
    account: AccountConfig,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
    *,
    account_output_dir_fn,
    register_response_capture_fn,
    capture_response_payload_fn,
    resolve_bootstrap_url_fn,
    wait_for_url_contains_fn,
    extract_current_account_name_fn,
    should_switch_for_account_fn,
    switch_to_account_fn,
    log_fn,
    open_feedback_page_fn,
    build_feedback_url_fn,
    wait_for_iframe_ready_fn,
    resolve_frame_locator_fn,
    business_iframe_selector_fn,
    safe_page_content_fn,
    is_empty_refund_list_fn,
    build_empty_refund_result_fn,
    build_detail_result_fn,
) -> FetchResult:
    output_dir = account_output_dir_fn(account.name)
    captures = register_response_capture_fn(page, capture_response_payload_fn)

    bootstrap_url = resolve_bootstrap_url_fn(account, output_dir)
    page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index"), timeout_ms=4000, is_cancelled=is_cancelled)

    if "token=" not in page.url and bootstrap_url == account.home_url:
        raise FetchError("当前登录态未自动跳入后台页，且没有可复用的历史反馈页地址，无法启动自动切换账号。")

    current_account_name = extract_current_account_name_fn(page)
    if should_switch_for_account_fn(account, current_account_name):
        switch_to_account_fn(page, account.name, account.home_url, logger)
    elif account.is_entry_account:
        log_fn(logger, "入口账号使用当前共享会话，不执行切换账号。")
    else:
        log_fn(logger, f"账号 {account.name} 已处于当前会话，跳过切换步骤。")

    feedback_url = open_feedback_page_fn(
        page,
        account=account,
        logger=logger,
        build_feedback_url_fn=build_feedback_url_fn,
        wait_for_iframe_ready_fn=wait_for_iframe_ready_fn,
        is_cancelled=is_cancelled,
    )
    frame_locator = resolve_frame_locator_fn(
        page,
        output_dir=output_dir,
        business_iframe_selector_fn=business_iframe_selector_fn,
        safe_page_content_fn=safe_page_content_fn,
    )
    list_text = frame_locator.locator("body").text_content(timeout=15000) or ""

    if is_empty_refund_list_fn(list_text):
        return build_empty_refund_result_fn(
            page=page,
            context=context,
            account=account,
            output_dir=output_dir,
            frame_locator=frame_locator,
            list_text=list_text,
            captures=captures,
            feedback_url=feedback_url,
            profile_dir=profile_dir,
            logger=logger,
            safe_page_content_fn=safe_page_content_fn,
            extract_current_account_name_fn=extract_current_account_name_fn,
        )

    return build_detail_result_fn(
        page=page,
        context=context,
        account=account,
        output_dir=output_dir,
        frame_locator=frame_locator,
        captures=captures,
        feedback_url=feedback_url,
        profile_dir=profile_dir,
        logger=logger,
        safe_page_content_fn=safe_page_content_fn,
        extract_current_account_name_fn=extract_current_account_name_fn,
    )


def fetch_account_impl(
    account: AccountConfig,
    wait_seconds: int,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
    *,
    sync_playwright_fn,
    path_exists_fn,
    validate_shared_browser_profile_dir_fn,
    create_browser_context_fn,
    fetch_account_in_page_fn,
    close_page_fn,
    close_context_and_browser_fn,
) -> FetchResult:
    normalized_profile_dir = normalize_profile_dir(
        profile_dir,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn,
    )
    ensure_account_session_available(
        account,
        normalized_profile_dir,
        path_exists_fn=path_exists_fn,
        error_cls=FetchError,
    )

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        try:
            return fetch_account_in_page_fn(page, context, account, logger, normalized_profile_dir, is_cancelled)
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(context, browser)


def fetch_accounts_batch_impl(
    accounts: list[AccountConfig],
    headless: bool = True,
    logger: callable | None = None,
    progress: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
    *,
    sync_playwright_fn,
    path_exists_fn,
    validate_shared_browser_profile_dir_fn,
    create_browser_context_fn,
    fetch_account_in_page_fn,
    close_page_fn,
    close_context_and_browser_fn,
) -> list[FetchResult]:
    normalized_profile_dir = normalize_profile_dir(
        profile_dir,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn,
    )
    enabled_accounts = [account for account in accounts if account.enabled and not account.is_entry_account]
    if not enabled_accounts:
        return []

    grouped_accounts: dict[str, list[AccountConfig]] = {}
    for account in enabled_accounts:
        group_key = normalized_profile_dir or account.state_path
        grouped_accounts.setdefault(group_key, []).append(account)

    results: list[FetchResult] = []
    with sync_playwright_fn() as playwright:
        for group_accounts in grouped_accounts.values():
            if is_cancelled is not None and is_cancelled():
                break
            primary_account = group_accounts[0]
            ensure_account_session_available(
                primary_account,
                normalized_profile_dir,
                path_exists_fn=path_exists_fn,
                error_cls=FetchError,
            )

            browser, context = create_browser_context_fn(playwright, primary_account, headless, normalized_profile_dir)
            try:
                for account in group_accounts:
                    if is_cancelled is not None and is_cancelled():
                        break
                    page = context.new_page()
                    try:
                        result = fetch_account_in_page_fn(
                            page, context, account, logger, normalized_profile_dir, is_cancelled
                        )
                    except CancelledError:
                        break
                    except Exception as exc:
                        result = FetchResult(account_name=account.name, ok=False, note=str(exc))
                    finally:
                        close_page_fn(page)
                    if is_cancelled is not None and is_cancelled():
                        break
                    results.append(result)
                    if progress is not None:
                        progress(result)
                if is_cancelled is not None and is_cancelled():
                    break
            finally:
                close_context_and_browser_fn(context, browser)
    return results
