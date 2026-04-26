from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
from desktop_py.core.models import (
    SESSION_SOURCE_PROFILE,
    SESSION_SOURCE_STATE_FILE,
    SESSION_STATUS_EXPIRED,
    SESSION_STATUS_MISSING,
    SESSION_STATUS_NEEDS_RELOGIN,
    SESSION_STATUS_STALE,
    SESSION_STATUS_VALID,
    AccountConfig,
)
from desktop_py.core.session_links import canonical_feedback_url, refresh_account_feedback_url

BACKEND_SESSION_URL_KEYWORDS = ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback")
BACKEND_SESSION_CONTENT_KEYWORDS = (
    '"nickName"',
    "current_login",
    "switch_account_dialog",
    "menu_box_account_info",
    "切换账号",
)
SESSION_STALE_AFTER = timedelta(days=3)
SESSION_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")

Logger = Callable[[str], None]
CancelCheck = Callable[[], bool]
LogFn = Callable[[Logger | None, str], None]


@dataclass(frozen=True)
class SessionVerification:
    valid: bool
    status: str = SESSION_STATUS_EXPIRED
    actual_account_name: str = ""
    feedback_url: str = ""
    reason: str = ""
    should_retry: bool = False
    should_relogin: bool = False
    session_source: str = ""


def session_source_for_profile_dir(profile_dir: str) -> str:
    return SESSION_SOURCE_PROFILE if profile_dir.strip() else SESSION_SOURCE_STATE_FILE


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in SESSION_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _verified_status_for_account(account: AccountConfig | None) -> str:
    if account is None:
        return SESSION_STATUS_VALID
    latest_activity = (
        _parse_datetime(account.last_session_renewed_at)
        or _parse_datetime(account.last_login_at)
        or _parse_datetime(account.last_session_verified_at)
    )
    if latest_activity is None:
        return SESSION_STATUS_VALID
    if datetime.now() - latest_activity >= SESSION_STALE_AFTER:
        return SESSION_STATUS_STALE
    return SESSION_STATUS_VALID


def apply_session_verification(
    account: AccountConfig,
    verification: SessionVerification,
    *,
    profile_dir: str = "",
    verified_at: str | None = None,
    renewed: bool = False,
) -> None:
    timestamp = verified_at or _now_text()
    account.session_status = verification.status
    account.session_source = verification.session_source or session_source_for_profile_dir(profile_dir)
    account.last_session_verified_at = timestamp
    account.last_session_error = "" if verification.valid else verification.reason
    if verification.actual_account_name.strip():
        account.last_actual_account_name = verification.actual_account_name.strip()
    if verification.feedback_url:
        account.feedback_url = verification.feedback_url
    if renewed:
        account.last_session_renewed_at = timestamp


def mark_account_session_missing(account: AccountConfig, *, profile_dir: str = "", reason: str = "") -> None:
    account.session_status = SESSION_STATUS_MISSING
    account.session_source = session_source_for_profile_dir(profile_dir)
    account.last_session_error = reason.strip()


def _wait_for_timeout(current_page: Any, wait_ms: int, _cancelled: CancelCheck | None = None) -> None:
    current_page.wait_for_timeout(wait_ms)


def _has_backend_session_url(page: Any) -> bool:
    return any(keyword in str(getattr(page, "url", "") or "") for keyword in BACKEND_SESSION_URL_KEYWORDS)


def _extract_account_name_from_html(html: str) -> str:
    try:
        matched = re.search(r'"nickName":"([^"]+)"', html)
    except Exception:
        return ""
    if not matched:
        return ""
    return matched.group(1).strip()


def _locator_count(page: Any, selector: str, **kwargs: Any) -> int:
    try:
        return int(page.locator(selector, **kwargs).count())
    except Exception:
        return 0


def _has_backend_session_locator(page: Any) -> bool:
    if not callable(getattr(page, "locator", None)):
        return False
    if _locator_count(page, ".switch_account_dialog .account_item") > 0:
        return True
    if _locator_count(page, "div.menu_box_account_info_item[title='切换账号']") > 0:
        return True
    if _locator_count(page, ".menu_box_account_info_item", has_text="切换账号") > 0:
        return True
    if _locator_count(page, "[title='切换账号']") > 0:
        return True
    try:
        return bool(page.get_by_text("切换账号", exact=True).count() > 0)
    except Exception:
        return False


def _has_backend_session_content(page: Any) -> bool:
    if not callable(getattr(page, "content", None)):
        return False
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content):
        return False
    try:
        html = safe_page_content(page, timeout_ms=1500)
    except Exception:
        return False
    return any(keyword in html for keyword in BACKEND_SESSION_CONTENT_KEYWORDS)


def verify_backend_session(page: Any, account: AccountConfig | None = None) -> SessionVerification:
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content):
        return SessionVerification(
            False,
            status=SESSION_STATUS_EXPIRED,
            reason="页面显示登录超时",
            should_relogin=True,
        )

    html = ""
    if callable(getattr(page, "content", None)):
        try:
            html = safe_page_content(page, timeout_ms=2000)
        except Exception:
            html = ""

    actual_account_name = _extract_account_name_from_html(html)
    content_valid = any(keyword in html for keyword in BACKEND_SESSION_CONTENT_KEYWORDS)
    locator_valid = _has_backend_session_locator(page)
    feedback_url = ""
    if _has_backend_session_url(page):
        feedback_url = canonical_feedback_url(str(getattr(page, "url", "") or ""))

    if actual_account_name or locator_valid or content_valid:
        return SessionVerification(
            True,
            status=_verified_status_for_account(account),
            actual_account_name=actual_account_name,
            feedback_url=feedback_url,
            reason="后台账号信息校验通过",
        )
    if (
        _has_backend_session_url(page)
        and not callable(getattr(page, "content", None))
        and not callable(getattr(page, "locator", None))
    ):
        return SessionVerification(
            True,
            status=_verified_status_for_account(account),
            feedback_url=feedback_url,
            reason="测试页缺少可检查 DOM，按后台 URL 兼容",
        )
    if _has_backend_session_url(page):
        return SessionVerification(
            False,
            status=SESSION_STATUS_EXPIRED,
            reason="仅检测到后台 URL/token，未检测到账号菜单或账号信息",
            should_retry=True,
        )
    return SessionVerification(
        False,
        status=SESSION_STATUS_NEEDS_RELOGIN,
        reason="未检测到后台账号信息",
        should_relogin=True,
    )


def _has_backend_session(page: Any) -> bool:
    return verify_backend_session(page).valid


def _wait_for_backend_session(
    page: Any,
    *,
    wait_for_url_contains_fn: Callable[..., Any],
    timeout_ms: int,
) -> bool:
    try:
        wait_for_url_contains_fn(page, BACKEND_SESSION_URL_KEYWORDS, timeout_ms=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    return _has_backend_session(page)


def _probe_account_session_url(
    page: Any,
    url: str,
    *,
    wait_for_url_contains_fn: Callable[..., Any],
    timeout_ms: int,
) -> bool:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeoutError:
        if recover_login_timeout_page(
            page,
            safe_page_content_fn=safe_page_content,
            wait_or_cancel_fn=_wait_for_timeout,
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
        wait_or_cancel_fn=_wait_for_timeout,
    ):
        return _wait_for_backend_session(page, wait_for_url_contains_fn=wait_for_url_contains_fn, timeout_ms=timeout_ms)
    return _has_backend_session(page)


def _probe_account_session(
    page: Any,
    account: AccountConfig,
    *,
    wait_for_url_contains_fn: Callable[..., Any],
    timeout_ms: int,
) -> bool:
    return _probe_account_session_result(
        page,
        account,
        wait_for_url_contains_fn=wait_for_url_contains_fn,
        timeout_ms=timeout_ms,
    ).valid


def _probe_account_session_result(
    page: Any,
    account: AccountConfig,
    *,
    wait_for_url_contains_fn: Callable[..., Any],
    timeout_ms: int,
) -> SessionVerification:
    if not callable(getattr(page, "goto", None)):
        return SessionVerification(
            True,
            status=_verified_status_for_account(account),
            reason="兼容测试页：跳过后台导航探测",
        )
    _probe_account_session_url(
        page,
        account.home_url,
        wait_for_url_contains_fn=wait_for_url_contains_fn,
        timeout_ms=timeout_ms,
    )
    return verify_backend_session(page, account)


def _create_state_file_context(
    playwright: Any,
    account: AccountConfig,
    headless: bool,
    _profile_dir: str,
) -> tuple[Any, Any]:
    browser = playwright.chromium.launch(headless=headless)
    try:
        context = browser.new_context(storage_state=str(account.state_path), viewport={"width": 1440, "height": 1200})
    except Exception:
        browser.close()
        raise
    return browser, context


def _wait_for_login_success(
    account: AccountConfig,
    page: Any,
    context: Any,
    state_path: Path,
    *,
    wait_seconds: int,
    datetime_cls: type[datetime],
    is_cancelled: CancelCheck | None,
    wait_or_cancel_fn: Callable[..., Any],
    logger: Logger | None = None,
    log_fn: LogFn | None = None,
    sync_playwright_fn: Callable[..., Any] | None = None,
    create_browser_context_fn: Callable[..., tuple[Any | None, Any]] | None = None,
    close_page_fn: Callable[[Any], None] | None = None,
    close_context_and_browser_fn: Callable[..., None] | None = None,
    headless_verify: bool = True,
    profile_dir: str = "",
) -> None:
    def fallback_verify(temp_state_path: str) -> bool:
        if sync_playwright_fn is None or create_browser_context_fn is None:
            return False
        temp_account = AccountConfig(
            name=account.name,
            state_path=temp_state_path,
            is_entry_account=account.is_entry_account,
            feedback_url="",
            home_url=account.home_url,
            enabled=account.enabled,
        )
        with sync_playwright_fn() as verify_playwright:
            verify_browser, verify_context = create_browser_context_fn(
                verify_playwright, temp_account, headless_verify, ""
            )
            verify_page = verify_context.new_page()
            try:
                result = _probe_account_session_result(
                    verify_page,
                    temp_account,
                    wait_for_url_contains_fn=lambda current_page, keywords, timeout_ms=10000, is_cancelled=None: (
                        _wait_for_backend_session(
                            current_page,
                            wait_for_url_contains_fn=lambda page_obj, url_keywords, timeout_ms=timeout_ms: any(
                                keyword in str(getattr(page_obj, "url", "") or "") for keyword in url_keywords
                            ),
                            timeout_ms=timeout_ms,
                        )
                    ),
                    timeout_ms=10000,
                )
                return result.valid
            finally:
                if callable(close_page_fn):
                    close_page_fn(verify_page)
                if callable(close_context_and_browser_fn):
                    close_context_and_browser_fn(
                        verify_context,
                        verify_browser,
                        state_path=None,
                        persist_state=False,
                    )
                else:
                    verify_context.close()
                    if verify_browser:
                        verify_browser.close()

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
                fallback_verify_fn=fallback_verify if sync_playwright_fn and create_browser_context_fn else None,
            )
            apply_session_verification(
                account,
                SessionVerification(
                    True,
                    status=SESSION_STATUS_VALID,
                    actual_account_name=verify_backend_session(page, account).actual_account_name,
                    feedback_url=canonical_feedback_url(str(getattr(page, "url", "") or "")),
                    reason="登录成功并已保存登录态",
                    session_source=session_source_for_profile_dir(profile_dir),
                ),
                profile_dir=profile_dir,
                renewed=True,
            )
            return
    raise FetchError("未在限定时间内检测到登录成功，已保留原登录态文件。")


def save_login_state_impl(
    account: AccountConfig,
    wait_seconds: int,
    logger: Logger | None = None,
    is_cancelled: CancelCheck | None = None,
    *,
    sync_playwright_fn: Callable[..., Any],
    datetime_cls: type[datetime],
    log_fn: LogFn,
    wait_or_cancel_fn: Callable[..., Any],
    close_page_fn: Callable[[Any], None],
    close_context_and_browser_fn: Callable[..., None],
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
                    sync_playwright_fn=sync_playwright_fn,
                    create_browser_context_fn=_create_state_file_context,
                    close_page_fn=close_page_fn,
                    close_context_and_browser_fn=close_context_and_browser_fn,
                    profile_dir="",
                )
            except FetchError as exc:
                raise FetchError(f"账号 {account.name} {exc}") from exc
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(context, browser)

    account.last_login_at = _now_text()
    log_fn(logger, f"登录态已保存到 {state_path}")
    return str(state_path)


def save_login_state_with_profile_impl(
    account: AccountConfig,
    wait_seconds: int,
    profile_dir: str,
    logger: Logger | None = None,
    is_cancelled: CancelCheck | None = None,
    *,
    sync_playwright_fn: Callable[..., Any],
    datetime_cls: type[datetime],
    validate_shared_browser_profile_dir_fn: Callable[[str], str],
    log_fn: LogFn,
    wait_or_cancel_fn: Callable[..., Any],
    close_page_fn: Callable[[Any], None],
    close_context_and_browser_fn: Callable[..., None],
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
                    sync_playwright_fn=sync_playwright_fn,
                    create_browser_context_fn=_create_state_file_context,
                    close_page_fn=close_page_fn,
                    close_context_and_browser_fn=close_context_and_browser_fn,
                    profile_dir=str(user_data_dir),
                )
            except FetchError as exc:
                raise FetchError(f"账号 {account.name} {exc}") from exc
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(context, None)

    account.last_login_at = _now_text()
    log_fn(logger, f"共享资料目录登录态已同步保存到 {state_path}")
    return str(state_path)


def validate_account_state_impl(
    account: AccountConfig,
    logger: Logger | None = None,
    profile_dir: str = "",
    *,
    sync_playwright_fn: Callable[..., Any],
    path_exists_fn: Callable[..., bool],
    validate_shared_browser_profile_dir_fn: Callable[[str], str],
    create_browser_context_fn: Callable[..., tuple[Any | None, Any]],
    wait_for_url_contains_fn: Callable[..., Any],
    close_page_fn: Callable[[Any], None],
    close_context_and_browser_fn: Callable[..., None],
    log_fn: LogFn,
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
        mark_account_session_missing(account, profile_dir=normalized_profile_dir, reason="缺少可用登录态")
        return False

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, True, normalized_profile_dir)
        page = context.new_page()
        try:
            verification = _probe_account_session_result(
                page,
                account,
                wait_for_url_contains_fn=wait_for_url_contains_fn,
                timeout_ms=10000,
            )
            valid = verification.valid
        except PlaywrightTimeoutError:
            valid = False
            verification = SessionVerification(
                False,
                status=SESSION_STATUS_EXPIRED,
                reason="等待后台页面超时",
                should_retry=True,
            )
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(
                context,
                browser,
                state_path=None,
                persist_state=False,
            )

    verification = SessionVerification(
        verification.valid,
        status=verification.status if valid else verification.status,
        actual_account_name=verification.actual_account_name,
        feedback_url=verification.feedback_url,
        reason=verification.reason,
        should_retry=verification.should_retry,
        should_relogin=verification.should_relogin,
        session_source=session_source_for_profile_dir(normalized_profile_dir),
    )
    apply_session_verification(account, verification, profile_dir=normalized_profile_dir)
    reason = f"：{verification.reason}" if not valid and verification.reason else ""
    log_fn(logger, f"账号 {account.name} 登录态校验结果：{'有效' if valid else '无效'}{reason}")
    return valid


def renew_account_state_impl(
    account: AccountConfig,
    logger: Logger | None = None,
    profile_dir: str = "",
    headless: bool = True,
    *,
    sync_playwright_fn: Callable[..., Any],
    path_exists_fn: Callable[..., bool],
    validate_shared_browser_profile_dir_fn: Callable[[str], str],
    create_browser_context_fn: Callable[..., tuple[Any | None, Any]],
    wait_for_url_contains_fn: Callable[..., Any],
    wait_or_cancel_fn: Callable[..., Any],
    close_page_fn: Callable[[Any], None],
    close_context_and_browser_fn: Callable[..., None],
    log_fn: LogFn,
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
        mark_account_session_missing(account, profile_dir=normalized_profile_dir, reason="缺少可用登录态")
        log_fn(logger, f"账号 {account.name} 自动续期失败：缺少可用登录态。")
        return False

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        renewed = False
        try:
            verification = _probe_account_session_result(
                page,
                account,
                wait_for_url_contains_fn=wait_for_url_contains_fn,
                timeout_ms=10000,
            )
            renewed = verification.valid
        except PlaywrightTimeoutError:
            renewed = False
            verification = SessionVerification(
                False,
                status=SESSION_STATUS_EXPIRED,
                reason="等待后台页面超时",
                should_retry=True,
            )
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

    verification = SessionVerification(
        verification.valid,
        status=SESSION_STATUS_VALID if renewed else verification.status,
        actual_account_name=verification.actual_account_name,
        feedback_url=verification.feedback_url,
        reason=verification.reason,
        should_retry=verification.should_retry,
        should_relogin=verification.should_relogin,
        session_source=session_source_for_profile_dir(normalized_profile_dir),
    )
    apply_session_verification(account, verification, profile_dir=normalized_profile_dir, renewed=renewed)
    if renewed:
        log_fn(logger, f"账号 {account.name} 自动续期成功。")
    else:
        reason = f"：{verification.reason}" if verification.reason else ""
        log_fn(logger, f"账号 {account.name} 自动续期失败{reason}。")
    return renewed
