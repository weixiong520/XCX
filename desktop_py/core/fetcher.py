from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from desktop_py.core.browser_runtime import configure_playwright_environment

configure_playwright_environment()

from playwright.sync_api import BrowserContext, Locator, Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright

from desktop_py.core.fetcher_page_strategy import (
    build_detail_result,
    build_empty_refund_result,
    is_empty_refund_list,
    open_feedback_page,
    register_response_capture,
    resolve_frame_locator,
)
from desktop_py.core.fetcher_support import (
    BUSINESS_IFRAME_SELECTORS,
    SWITCH_ACCOUNT_LIST_RETRY_LIMIT,
    CancelledError,
    FetchError,
    _capture_response_payload,
    _close_context_and_browser,
    _close_page,
    _fallback_from_responses,
    _log,
    build_feedback_url,
    business_iframe_selector,
    create_browser_context,
    safe_page_content,
    wait_for_current_account_name as wait_for_current_account_name_impl,
    wait_for_iframe_ready,
    wait_for_url_contains,
    wait_or_cancel,
)
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.store import account_output_dir, validate_shared_browser_profile_dir


def find_switch_entry(page: Page) -> Locator | None:
    candidates = [
        page.locator("div.menu_box_account_info_item[title='切换账号']"),
        page.locator(".menu_box_account_info_item", has_text="切换账号"),
        page.locator("[title='切换账号']"),
        page.get_by_text("切换账号", exact=True),
    ]
    for locator in candidates:
        try:
            if locator.count():
                return locator.first
        except Exception:
            continue
    return None


def _switch_dialog_ready(page: Page) -> bool:
    dialog = page.locator(".switch_account_dialog")
    if dialog.count() == 0:
        return False
    try:
        if dialog.first.is_visible():
            return True
    except Exception:
        pass
    return page.locator(".switch_account_dialog .account_item").count() > 0


def _maybe_expand_account_menu(page: Page) -> None:
    for selector in (".menu_box_other_item_enter", ".little_menu_button"):
        trigger = page.locator(selector)
        if trigger.count() == 0:
            continue
        try:
            trigger.first.click(timeout=1000)
            page.wait_for_timeout(400)
            return
        except Exception:
            try:
                trigger.first.evaluate("e => e.click()")
                page.wait_for_timeout(400)
                return
            except Exception:
                continue


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
    if has_switch_entry:
        return False
    normalized_home_url = home_url.strip().rstrip("/")
    if not normalized_home_url:
        return False
    normalized_current_url = current_url.strip().rstrip("/")
    return normalized_current_url != normalized_home_url


def prepare_switch_account_page(page: Page, home_url: str = "", logger: callable | None = None) -> None:
    has_switch_entry = _switch_dialog_ready(page) or find_switch_entry(page) is not None
    if not should_retry_switch_from_home(page.url, home_url, has_switch_entry):
        return
    _log(logger, f"当前页面未发现切换入口，正在返回后台首页重试：{home_url}")
    page.goto(home_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains(page, ("token=", "/wxamp/index/index"), timeout_ms=4000)


def open_switch_account_dialog(page: Page, timeout_ms: int = 12000) -> None:
    if _switch_dialog_ready(page):
        return

    deadline = time.monotonic() + (timeout_ms / 1000)
    dialog = page.locator(".switch_account_dialog")
    while time.monotonic() < deadline:
        switch_entry = find_switch_entry(page)
        if switch_entry is not None:
            try:
                switch_entry.click(timeout=1500)
            except Exception:
                switch_entry.evaluate("e => e.click()")
            try:
                dialog.first.wait_for(state="visible", timeout=2000)
            except Exception:
                pass
            if _switch_dialog_ready(page):
                return
        _maybe_expand_account_menu(page)
        page.wait_for_timeout(500)

    current_url = page.url
    actual_name = extract_current_account_name(page) or "未知"
    raise FetchError(f"当前页面不存在切换账号入口。当前地址：{current_url}，当前账号：{actual_name}")


def extract_current_account_name(page: Page) -> str:
    try:
        html = safe_page_content(page, timeout_ms=5000)
    except Exception:
        html = ""

    try:
        matched = re.search(r'"nickName":"([^"]+)"', html)
        if matched:
            return matched.group(1).strip()
    except Exception:
        pass

    try:
        current_names = (
            page.locator(".switch_account_dialog .account_item .current_login")
            .locator("xpath=ancestor::div[contains(@class, 'account_item')]")
            .locator(".account_name")
        )
        if current_names.count():
            return (current_names.first.text_content() or "").strip()
    except Exception:
        pass

    return ""


def save_login_state(
    account: AccountConfig,
    wait_seconds: int,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
) -> str:
    state_path = Path(account.state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        try:
            page.goto(account.home_url, wait_until="domcontentloaded")
            _log(logger, f"已打开微信后台登录页，请在 {wait_seconds} 秒内完成账号 {account.name} 的扫码登录。")
            _log(logger, "如果页面已经是登录后的后台首页，无需重复扫码，保持页面打开等待程序自动保存即可。")

            deadline = datetime.now().timestamp() + wait_seconds
            saved = False
            while datetime.now().timestamp() < deadline:
                wait_or_cancel(page, 2000, is_cancelled)
                if "token=" in page.url or "/wxamp/index/index" in page.url:
                    context.storage_state(path=str(state_path), indexed_db=True)
                    saved = True
                    break
            if not saved:
                raise FetchError(f"账号 {account.name} 未在限定时间内检测到登录成功，已保留原登录态文件。")
        finally:
            _close_page(page)
            _close_context_and_browser(context, browser)

    _log(logger, f"登录态已保存到 {state_path}")
    return str(state_path)


def save_login_state_with_profile(
    account: AccountConfig,
    wait_seconds: int,
    profile_dir: str,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
) -> str:
    user_data_dir = Path(validate_shared_browser_profile_dir(profile_dir))
    user_data_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(account.state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        try:
            page.goto(account.home_url, wait_until="domcontentloaded")
            _log(logger, f"已打开共享浏览器资料目录，请在 {wait_seconds} 秒内完成账号 {account.name} 的扫码登录。")
            _log(logger, "如果共享资料目录里已经保留有效登录态，无需重复扫码，保持页面打开等待程序自动保存即可。")

            deadline = datetime.now().timestamp() + wait_seconds
            saved = False
            while datetime.now().timestamp() < deadline:
                wait_or_cancel(page, 2000, is_cancelled)
                if "token=" in page.url or "/wxamp/index/index" in page.url:
                    context.storage_state(path=str(state_path), indexed_db=True)
                    saved = True
                    break
            if not saved:
                raise FetchError(f"账号 {account.name} 未在限定时间内检测到登录成功，已保留原登录态文件。")
        finally:
            _close_page(page)
            _close_context_and_browser(context, None)

    _log(logger, f"共享资料目录登录态已同步保存到 {state_path}")
    return str(state_path)


def switch_to_account(page: Page, account_name: str, home_url: str = "", logger: callable | None = None) -> None:
    prepare_switch_account_page(page, home_url, logger)
    open_switch_account_dialog(page)

    account_items = wait_for_switch_account_items(page, ".switch_account_dialog .account_item", logger)
    account_meta = account_items.evaluate_all(
        """
        elements => elements.map(el => ({
            name: (el.querySelector('.account_name')?.textContent || '').trim(),
            current: !!el.querySelector('.current_login')
        }))
        """
    )

    current_name = next((item["name"] for item in account_meta if item["current"]), "")
    if current_name == account_name:
        _log(logger, f"当前已是目标账号：{account_name}")
        close_icon = page.locator(".switch_account_dialog .close_icon")
        if close_icon.count():
            close_icon.first.evaluate("e => e.click()")
        return

    target = page.locator(".switch_account_dialog .account_item").filter(
        has=page.locator(".account_name", has_text=account_name)
    )
    if target.count() == 0:
        names = "、".join(item["name"] for item in account_meta if item["name"])
        raise FetchError(f"切换账号列表中未找到“{account_name}”。当前可见账号：{names}")

    target.first.evaluate("e => e.click()")
    actual_name = wait_for_current_account_name(page, account_name, timeout_ms=5000)
    if actual_name and actual_name != account_name:
        raise FetchError(f"已点击切换账号，但当前实际账号为“{actual_name}”，不是目标账号“{account_name}”。")
    _log(logger, f"已切换到账号：{account_name}")


def should_switch_account(current_account_name: str, target_account_name: str) -> bool:
    current_name = current_account_name.strip()
    target_name = target_account_name.strip()
    if not current_name or not target_name:
        return True
    return current_name != target_name


def should_switch_for_account(account: AccountConfig, current_account_name: str) -> bool:
    if account.is_entry_account:
        return False
    return should_switch_account(current_account_name, account.name)


def list_switchable_accounts(page: Page, home_url: str = "", logger: callable | None = None) -> list[str]:
    prepare_switch_account_page(page, home_url, logger)
    open_switch_account_dialog(page)
    account_items = wait_for_switch_account_items(page, ".switch_account_dialog .account_item .account_name", logger)

    names: list[str] = []
    for index in range(account_items.count()):
        name = (account_items.nth(index).text_content() or "").strip()
        if name and name not in names:
            names.append(name)

    close_icon = page.locator(".switch_account_dialog .close_icon")
    if close_icon.count():
        close_icon.first.evaluate("e => e.click()")
    return names


def _wait_for_locator_items(page: Page, locator, timeout_ms: int = 1800, interval_ms: int = 200) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if locator.count() > 0:
            return True
        page.wait_for_timeout(interval_ms)
    return locator.count() > 0


def wait_for_switch_account_items(
    page: Page,
    selector: str,
    logger: callable | None = None,
    retry_limit: int = SWITCH_ACCOUNT_LIST_RETRY_LIMIT,
    is_cancelled: callable | None = None,
):
    locator = page.locator(selector)
    for attempt in range(1, retry_limit + 1):
        if _wait_for_locator_items(page, locator):
            return locator
        if attempt >= retry_limit:
            break
        _log(logger, f"未读取到切换账号列表，正在进行第 {attempt + 1} 次重试。")
        close_icon = page.locator(".switch_account_dialog .close_icon")
        if close_icon.count():
            try:
                close_icon.first.evaluate("e => e.click()")
            except Exception:
                pass
        wait_or_cancel(page, 1200, is_cancelled)
        open_switch_account_dialog(page)
        locator = page.locator(selector)
    raise FetchError(f"未读取到切换账号列表，已重试 {retry_limit} 次。")


def fetch_switchable_accounts(
    account: AccountConfig,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
) -> list[str]:
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    state_path = Path(account.state_path)
    if not state_path.exists() and not normalized_profile_dir:
        raise FetchError(f"账号 {account.name} 缺少登录态文件：{state_path}")

    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        try:
            bootstrap_url = account.feedback_url.strip() or account.home_url
            page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_url_contains(page, ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback"), timeout_ms=4000)
            names = list_switchable_accounts(page, account.home_url, logger)
            _log(logger, f"已读取到 {len(names)} 个可切换账号。")
        finally:
            _close_page(page)
            _close_context_and_browser(
                context,
                browser,
                state_path=state_path if normalized_profile_dir else None,
                persist_state=bool(normalized_profile_dir),
            )
    return names


def resolve_bootstrap_url(account: AccountConfig, output_dir: Path) -> str:
    return account.home_url


def _fetch_account_in_page(
    page: Page,
    context,
    account: AccountConfig,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> FetchResult:
    output_dir = account_output_dir(account.name)
    captures = register_response_capture(page, _capture_response_payload)

    bootstrap_url = resolve_bootstrap_url(account, output_dir)
    page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains(page, ("token=", "/wxamp/index/index"), timeout_ms=4000, is_cancelled=is_cancelled)

    if "token=" not in page.url and bootstrap_url == account.home_url:
        raise FetchError("当前登录态未自动跳入后台页，且没有可复用的历史反馈页地址，无法启动自动切换账号。")

    current_account_name = extract_current_account_name(page)
    if should_switch_for_account(account, current_account_name):
        switch_to_account(page, account.name, account.home_url, logger)
    elif account.is_entry_account:
        _log(logger, "入口账号使用当前共享会话，不执行切换账号。")
    else:
        _log(logger, f"账号 {account.name} 已处于当前会话，跳过切换步骤。")

    feedback_url = open_feedback_page(
        page,
        account=account,
        logger=logger,
        build_feedback_url_fn=build_feedback_url,
        wait_for_iframe_ready_fn=wait_for_iframe_ready,
        is_cancelled=is_cancelled,
    )
    frame_locator = resolve_frame_locator(
        page,
        output_dir=output_dir,
        business_iframe_selector_fn=business_iframe_selector,
        safe_page_content_fn=safe_page_content,
    )
    list_text = frame_locator.locator("body").text_content(timeout=15000) or ""

    if is_empty_refund_list(list_text):
        return build_empty_refund_result(
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
            safe_page_content_fn=safe_page_content,
            extract_current_account_name_fn=extract_current_account_name,
        )

    return build_detail_result(
        page=page,
        context=context,
        account=account,
        output_dir=output_dir,
        frame_locator=frame_locator,
        captures=captures,
        feedback_url=feedback_url,
        profile_dir=profile_dir,
        logger=logger,
        safe_page_content_fn=safe_page_content,
        extract_current_account_name_fn=extract_current_account_name,
    )


def fetch_account(
    account: AccountConfig,
    wait_seconds: int,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> FetchResult:
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    state_path = Path(account.state_path)
    if not state_path.exists() and not normalized_profile_dir:
        raise FetchError(f"账号 {account.name} 缺少登录态文件：{state_path}")

    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        try:
            return _fetch_account_in_page(page, context, account, logger, normalized_profile_dir, is_cancelled)
        finally:
            _close_page(page)
            _close_context_and_browser(context, browser)


def fetch_accounts_batch(
    accounts: list[AccountConfig],
    headless: bool = True,
    logger: callable | None = None,
    progress: callable | None = None,
    profile_dir: str = "",
    is_cancelled: callable | None = None,
) -> list[FetchResult]:
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    enabled_accounts = [account for account in accounts if account.enabled and not account.is_entry_account]
    if not enabled_accounts:
        return []

    grouped_accounts: dict[str, list[AccountConfig]] = {}
    for account in enabled_accounts:
        group_key = normalized_profile_dir or account.state_path
        grouped_accounts.setdefault(group_key, []).append(account)

    results: list[FetchResult] = []
    with sync_playwright() as playwright:
        for group_accounts in grouped_accounts.values():
            if is_cancelled is not None and is_cancelled():
                break
            primary_account = group_accounts[0]
            state_path = Path(primary_account.state_path)
            if not state_path.exists() and not normalized_profile_dir:
                raise FetchError(f"账号 {primary_account.name} 缺少登录态文件：{state_path}")

            browser, context = create_browser_context(playwright, primary_account, headless, normalized_profile_dir)
            try:
                for account in group_accounts:
                    if is_cancelled is not None and is_cancelled():
                        break
                    page = context.new_page()
                    try:
                        result = _fetch_account_in_page(page, context, account, logger, normalized_profile_dir, is_cancelled)
                    except CancelledError:
                        break
                    except Exception as exc:
                        result = FetchResult(account_name=account.name, ok=False, note=str(exc))
                    finally:
                        _close_page(page)
                    if is_cancelled is not None and is_cancelled():
                        break
                    results.append(result)
                    if progress is not None:
                        progress(result)
                if is_cancelled is not None and is_cancelled():
                    break
            finally:
                _close_context_and_browser(context, browser)
    return results


def validate_account_state(account: AccountConfig, logger: callable | None = None, profile_dir: str = "") -> bool:
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    state_path = Path(account.state_path)
    if not state_path.exists() and not normalized_profile_dir:
        return False

    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright, account, True, normalized_profile_dir)
        page = context.new_page()
        try:
            page.goto(account.home_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_url_contains(page, ("token=", "/wxamp/index/index"), timeout_ms=4000)
            valid = "token=" in page.url or "/wxamp/index/index" in page.url
        except PlaywrightTimeoutError:
            valid = False
        finally:
            _close_page(page)
            _close_context_and_browser(
                context,
                browser,
                state_path=state_path if normalized_profile_dir else None,
                persist_state=bool(normalized_profile_dir),
            )

    _log(logger, f"账号 {account.name} 登录态校验结果：{'有效' if valid else '无效'}")
    return valid


def keep_alive_account_state(account: AccountConfig, logger: callable | None = None, profile_dir: str = "") -> bool:
    _log(logger, f"开始静默保活账号 {account.name}。")
    valid = validate_account_state(account, logger, profile_dir)
    _log(logger, f"账号 {account.name} 静默保活{'成功' if valid else '失败'}。")
    return valid
