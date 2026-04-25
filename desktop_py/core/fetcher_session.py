from __future__ import annotations

from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from desktop_py.core.fetcher_support import (
    FetchError,
    ensure_account_session_available,
    is_login_timeout_page,
    normalize_profile_dir,
    persist_storage_state,
    recover_login_timeout_page,
    safe_page_content,
)
from desktop_py.core.models import AccountConfig
from desktop_py.core.session_links import refresh_account_feedback_url

BACKEND_SESSION_URL_KEYWORDS = ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback")
BACKEND_SESSION_CONTENT_KEYWORDS = (
    '"nickName"',
    "current_login",
    "switch_account_dialog",
    "menu_box_account_info",
    "切换账号",
)


def _has_backend_session_url(page) -> bool:
    return any(keyword in str(getattr(page, "url", "") or "") for keyword in BACKEND_SESSION_URL_KEYWORDS)


def _has_backend_session_content(page) -> bool:
    if not callable(getattr(page, "content", None)):
        return False
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content):
        return False
    try:
        html = safe_page_content(page, timeout_ms=1500)
    except Exception:
        return False
    return any(keyword in html for keyword in BACKEND_SESSION_CONTENT_KEYWORDS)


def _has_backend_session(page) -> bool:
    return _has_backend_session_url(page) or _has_backend_session_content(page)


def _wait_for_backend_session(page, *, wait_for_url_contains_fn, timeout_ms: int) -> bool:
    try:
        if wait_for_url_contains_fn(page, BACKEND_SESSION_URL_KEYWORDS, timeout_ms=timeout_ms):
            return True
    except PlaywrightTimeoutError:
        pass
    return _has_backend_session(page)


def _probe_account_session_url(page, url: str, *, wait_for_url_contains_fn, timeout_ms: int) -> bool:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeoutError:
        if recover_login_timeout_page(
            page,
            safe_page_content_fn=safe_page_content,
            wait_or_cancel_fn=lambda current_page, wait_ms, _is_cancelled=None: current_page.wait_for_timeout(wait_ms),
        ):
            return _wait_for_backend_session(
                page, wait_for_url_contains_fn=wait_for_url_contains_fn, timeout_ms=timeout_ms
            )
        return _has_backend_session(page)
    if _wait_for_backend_session(page, wait_for_url_contains_fn=wait_for_url_contains_fn, timeout_ms=timeout_ms):
        return True
    if recover_login_timeout_page(
        page,
        safe_page_content_fn=safe_page_content,
        wait_or_cancel_fn=lambda current_page, wait_ms, _is_cancelled=None: current_page.wait_for_timeout(wait_ms),
    ):
        return _wait_for_backend_session(page, wait_for_url_contains_fn=wait_for_url_contains_fn, timeout_ms=timeout_ms)
    return _has_backend_session(page)


def _probe_account_session(page, account: AccountConfig, *, wait_for_url_contains_fn, timeout_ms: int) -> bool:
    if _probe_account_session_url(
        page,
        account.home_url,
        wait_for_url_contains_fn=wait_for_url_contains_fn,
        timeout_ms=timeout_ms,
    ):
        return True

    feedback_url = account.feedback_url.strip()
    if not feedback_url:
        return False
    return _probe_account_session_url(
        page,
        feedback_url,
        wait_for_url_contains_fn=wait_for_url_contains_fn,
        timeout_ms=timeout_ms,
    )


def _wait_for_login_success(
    account: AccountConfig,
    page,
    context,
    state_path: Path,
    *,
    wait_seconds: int,
    datetime_cls,
    is_cancelled,
    wait_or_cancel_fn,
    logger=None,
    log_fn=None,
) -> None:
    deadline = datetime_cls.now().timestamp() + wait_seconds
    while datetime_cls.now().timestamp() < deadline:
        wait_or_cancel_fn(page, 2000, is_cancelled)
        if _has_backend_session(page):
            refresh_account_feedback_url(account, str(getattr(page, "url", "") or ""))
            persist_storage_state(
                context,
                str(state_path),
                page=page,
                logger=logger,
                log_fn=log_fn,
                wait_or_cancel_fn=wait_or_cancel_fn,
                is_cancelled=is_cancelled,
            )
            return
    raise FetchError("未在限定时间内检测到登录成功，已保留原登录态文件。")


def save_login_state_impl(
    account: AccountConfig,
    wait_seconds: int,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
    *,
    sync_playwright_fn,
    datetime_cls,
    log_fn,
    wait_or_cancel_fn,
    close_page_fn,
    close_context_and_browser_fn,
) -> str:
    state_path = Path(account.state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright_fn() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        try:
            page.goto(account.home_url, wait_until="domcontentloaded")
            log_fn(logger, f"已打开微信后台登录页，请在 {wait_seconds} 秒内完成账号 {account.name} 的扫码登录。")
            log_fn(logger, "如果页面已经是登录后的后台首页，无需重复扫码，保持页面打开等待程序自动保存即可。")

            try:
                _wait_for_login_success(
                    account,
                    page,
                    context,
                    state_path,
                    wait_seconds=wait_seconds,
                    datetime_cls=datetime_cls,
                    is_cancelled=is_cancelled,
                    wait_or_cancel_fn=wait_or_cancel_fn,
                    logger=logger,
                    log_fn=log_fn,
                )
            except FetchError as exc:
                raise FetchError(f"账号 {account.name} {exc}") from exc
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(context, browser)

    log_fn(logger, f"登录态已保存到 {state_path}")
    return str(state_path)


def save_login_state_with_profile_impl(
    account: AccountConfig,
    wait_seconds: int,
    profile_dir: str,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
    *,
    sync_playwright_fn,
    datetime_cls,
    validate_shared_browser_profile_dir_fn,
    log_fn,
    wait_or_cancel_fn,
    close_page_fn,
    close_context_and_browser_fn,
) -> str:
    user_data_dir = Path(
        normalize_profile_dir(
            profile_dir, validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn
        )
    )
    user_data_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(account.state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright_fn() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        try:
            page.goto(account.home_url, wait_until="domcontentloaded")
            log_fn(logger, f"已打开共享浏览器资料目录，请在 {wait_seconds} 秒内完成账号 {account.name} 的扫码登录。")
            log_fn(logger, "如果共享资料目录里已经保留有效登录态，无需重复扫码，保持页面打开等待程序自动保存即可。")

            try:
                _wait_for_login_success(
                    account,
                    page,
                    context,
                    state_path,
                    wait_seconds=wait_seconds,
                    datetime_cls=datetime_cls,
                    is_cancelled=is_cancelled,
                    wait_or_cancel_fn=wait_or_cancel_fn,
                    logger=logger,
                    log_fn=log_fn,
                )
            except FetchError as exc:
                raise FetchError(f"账号 {account.name} {exc}") from exc
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(context, None)

    log_fn(logger, f"共享资料目录登录态已同步保存到 {state_path}")
    return str(state_path)


def validate_account_state_impl(
    account: AccountConfig,
    logger: callable | None = None,
    profile_dir: str = "",
    *,
    sync_playwright_fn,
    path_exists_fn,
    validate_shared_browser_profile_dir_fn,
    create_browser_context_fn,
    wait_for_url_contains_fn,
    close_page_fn,
    close_context_and_browser_fn,
    log_fn,
) -> bool:
    normalized_profile_dir = normalize_profile_dir(
        profile_dir,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn,
    )
    state_path = ensure_account_session_available(
        account,
        normalized_profile_dir,
        path_exists_fn=path_exists_fn,
        error_cls=None,
    )
    if state_path is None:
        return False

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, True, normalized_profile_dir)
        page = context.new_page()
        try:
            valid = _probe_account_session(
                page,
                account,
                wait_for_url_contains_fn=wait_for_url_contains_fn,
                timeout_ms=10000,
            )
            if valid:
                refresh_account_feedback_url(account, str(getattr(page, "url", "") or ""))
        except PlaywrightTimeoutError:
            valid = False
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(
                context,
                browser,
                state_path=None,
                persist_state=False,
            )

    log_fn(logger, f"账号 {account.name} 登录态校验结果：{'有效' if valid else '无效'}")
    return valid


def renew_account_state_impl(
    account: AccountConfig,
    logger: callable | None = None,
    profile_dir: str = "",
    headless: bool = True,
    *,
    sync_playwright_fn,
    path_exists_fn,
    validate_shared_browser_profile_dir_fn,
    create_browser_context_fn,
    wait_for_url_contains_fn,
    wait_or_cancel_fn,
    close_page_fn,
    close_context_and_browser_fn,
    log_fn,
) -> bool:
    log_fn(logger, f"开始自动续期账号 {account.name}。")
    normalized_profile_dir = normalize_profile_dir(
        profile_dir,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn,
    )
    state_path = ensure_account_session_available(
        account,
        normalized_profile_dir,
        path_exists_fn=path_exists_fn,
        error_cls=None,
    )
    if state_path is None:
        log_fn(logger, f"账号 {account.name} 自动续期失败：缺少可用登录态。")
        return False

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        renewed = False
        try:
            renewed = _probe_account_session(
                page,
                account,
                wait_for_url_contains_fn=wait_for_url_contains_fn,
                timeout_ms=10000,
            )
            if renewed:
                refresh_account_feedback_url(account, str(getattr(page, "url", "") or ""))
        except PlaywrightTimeoutError:
            renewed = False
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(
                context,
                browser,
                state_path=state_path if renewed else None,
                persist_state=renewed,
                page=page,
                logger=logger,
                log_fn=log_fn,
                wait_or_cancel_fn=wait_or_cancel_fn,
            )

    log_fn(logger, f"账号 {account.name} 自动续期{'成功' if renewed else '失败'}。")
    return renewed
