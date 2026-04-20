from __future__ import annotations

from pathlib import Path

from desktop_py.core.fetcher_support import (
    CancelledError,
    FetchError,
    ensure_account_session_available,
    normalize_profile_dir,
)
from desktop_py.core.models import AccountConfig, FetchResult


def _page_current_account_name(page) -> str:
    try:
        return str(getattr(page, "_current_account_name_cache", "") or "").strip()
    except Exception:
        return ""


def _set_page_current_account_name(page, account_name: str) -> None:
    try:
        setattr(page, "_current_account_name_cache", account_name.strip())
    except Exception:
        pass


def _page_has_backend_session(page) -> bool:
    try:
        current_url = str(getattr(page, "url", "") or "")
    except Exception:
        return False
    return any(keyword in current_url for keyword in ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback"))


def _set_page_home_ready(page, ready: bool) -> None:
    try:
        setattr(page, "_home_ready_cache", bool(ready))
    except Exception:
        pass


def _page_home_ready(page) -> bool:
    try:
        return bool(getattr(page, "_home_ready_cache", False))
    except Exception:
        return False


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
    confirm_empty_refund_list_fn,
    build_empty_refund_result_fn,
    build_detail_result_fn,
) -> FetchResult:
    output_dir = account_output_dir_fn(account.name)
    captures, cleanup_response_capture = register_response_capture_fn(page, capture_response_payload_fn)

    try:
        bootstrap_url = resolve_bootstrap_url_fn(account, output_dir)
        if not _page_has_backend_session(page):
            page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index"), timeout_ms=4000, is_cancelled=is_cancelled)
            _set_page_home_ready(page, bootstrap_url == account.home_url)

        if "token=" not in page.url and bootstrap_url == account.home_url:
            raise FetchError("当前登录态未自动跳入后台页，且没有可复用的历史反馈页地址，无法启动自动切换账号。")

        current_account_name = _page_current_account_name(page)
        if not current_account_name:
            current_account_name = extract_current_account_name_fn(page)
            if current_account_name:
                _set_page_current_account_name(page, current_account_name)

        if should_switch_for_account_fn(account, current_account_name):
            switch_to_account_fn(page, account.name, account.home_url, logger)
            _set_page_current_account_name(page, account.name)
        elif account.is_entry_account:
            log_fn(logger, "入口账号使用当前共享会话，不执行切换账号。")
        else:
            log_fn(logger, f"账号 {account.name} 已处于当前会话，跳过切换步骤。")

        feedback_capture_start = len(captures)
        feedback_url = open_feedback_page_fn(
            page,
            account=account,
            logger=logger,
            build_feedback_url_fn=build_feedback_url_fn,
            wait_for_iframe_ready_fn=wait_for_iframe_ready_fn,
            is_cancelled=is_cancelled,
        )
        current_captures = captures[feedback_capture_start:]
        frame_locator = resolve_frame_locator_fn(
            page,
            output_dir=output_dir,
            business_iframe_selector_fn=business_iframe_selector_fn,
            safe_page_content_fn=safe_page_content_fn,
        )
        list_text = frame_locator.locator("body").text_content(timeout=15000) or ""

        empty_confirmed, confirmed_list_text = confirm_empty_refund_list_fn(
            page=page,
            frame_locator=frame_locator,
            initial_text=list_text,
            captures=current_captures,
            is_empty_refund_list_fn=is_empty_refund_list_fn,
            is_cancelled=is_cancelled,
        )

        if empty_confirmed:
            result = build_empty_refund_result_fn(
                page=page,
                context=context,
                account=account,
                output_dir=output_dir,
                frame_locator=frame_locator,
                list_text=confirmed_list_text,
                captures=current_captures,
                feedback_url=feedback_url,
                profile_dir=profile_dir,
                logger=logger,
                safe_page_content_fn=safe_page_content_fn,
                extract_current_account_name_fn=extract_current_account_name_fn,
                is_cancelled=is_cancelled,
            )
        else:
            result = build_detail_result_fn(
                page=page,
                context=context,
                account=account,
                output_dir=output_dir,
                frame_locator=frame_locator,
                captures=current_captures,
                feedback_url=feedback_url,
                profile_dir=profile_dir,
                logger=logger,
                safe_page_content_fn=safe_page_content_fn,
                extract_current_account_name_fn=extract_current_account_name_fn,
            )
        if result.actual_account_name.strip():
            _set_page_current_account_name(page, result.actual_account_name)
        _set_page_home_ready(page, False)
        return result
    finally:
        cleanup_response_capture()


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
    acquire_group_runtime_fn,
    release_group_runtime_fn,
    invalidate_group_runtime_fn,
    runtime_current_account_name_fn,
    update_runtime_current_account_name_fn,
    should_invalidate_runtime_fn,
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

    runtime = acquire_group_runtime_fn(
        account,
        headless=headless,
        profile_dir=normalized_profile_dir,
        sync_playwright_fn=sync_playwright_fn,
        create_browser_context_fn=create_browser_context_fn,
        logger=logger,
        is_cancelled=is_cancelled,
    )
    try:
        if runtime_current_account_name_fn(runtime):
            update_runtime_current_account_name_fn(runtime, runtime_current_account_name_fn(runtime))
        result = fetch_account_in_page_fn(
            runtime.page,
            runtime.context,
            account,
            logger,
            normalized_profile_dir,
            is_cancelled,
        )
        if result.actual_account_name.strip():
            update_runtime_current_account_name_fn(runtime, result.actual_account_name)
        return result
    except Exception as exc:
        if should_invalidate_runtime_fn(exc):
            invalidate_group_runtime_fn(runtime, str(exc))
        else:
            release_group_runtime_fn(runtime)
        raise
    else:
        release_group_runtime_fn(runtime)
    finally:
        if runtime.busy:
            release_group_runtime_fn(runtime)


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
    acquire_group_runtime_fn,
    release_group_runtime_fn,
    invalidate_group_runtime_fn,
    update_runtime_current_account_name_fn,
    should_invalidate_runtime_fn,
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
    for group_accounts in grouped_accounts.values():
        if is_cancelled is not None and is_cancelled():
            raise CancelledError("任务已取消")
        primary_account = group_accounts[0]
        ensure_account_session_available(
            primary_account,
            normalized_profile_dir,
            path_exists_fn=path_exists_fn,
            error_cls=FetchError,
        )
        runtime = acquire_group_runtime_fn(
            primary_account,
            headless=headless,
            profile_dir=normalized_profile_dir,
            sync_playwright_fn=sync_playwright_fn,
            create_browser_context_fn=create_browser_context_fn,
            logger=logger,
            is_cancelled=is_cancelled,
        )
        try:
            for account in group_accounts:
                if is_cancelled is not None and is_cancelled():
                    raise CancelledError("任务已取消")
                try:
                    result = fetch_account_in_page_fn(
                        runtime.page,
                        runtime.context,
                        account,
                        logger,
                        normalized_profile_dir,
                        is_cancelled,
                    )
                    if result.actual_account_name.strip():
                        update_runtime_current_account_name_fn(runtime, result.actual_account_name)
                except CancelledError:
                    raise
                except Exception as exc:
                    if should_invalidate_runtime_fn(exc):
                        invalidate_group_runtime_fn(runtime, str(exc))
                        runtime = acquire_group_runtime_fn(
                            primary_account,
                            headless=headless,
                            profile_dir=normalized_profile_dir,
                            sync_playwright_fn=sync_playwright_fn,
                            create_browser_context_fn=create_browser_context_fn,
                            logger=logger,
                            is_cancelled=is_cancelled,
                        )
                    result = FetchResult(account_name=account.name, ok=False, note=str(exc))
                if is_cancelled is not None and is_cancelled():
                    raise CancelledError("任务已取消")
                results.append(result)
                if progress is not None:
                    progress(result)
            if is_cancelled is not None and is_cancelled():
                raise CancelledError("任务已取消")
        finally:
            if runtime.busy:
                release_group_runtime_fn(runtime)
    return results
