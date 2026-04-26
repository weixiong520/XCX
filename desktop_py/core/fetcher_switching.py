from __future__ import annotations

import re
import time

from playwright.sync_api import Locator, Page

from desktop_py.core.fetcher_support import (
    FetchError,
    ensure_account_session_available,
    is_login_timeout_page,
    normalize_profile_dir,
    recover_login_timeout_page,
    safe_page_content,
)
from desktop_py.core.models import AccountConfig


def find_switch_entry_impl(page: Page) -> Locator | None:
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


def switch_dialog_ready_impl(page: Page) -> bool:
    dialog = page.locator(".switch_account_dialog")
    if dialog.count() == 0:
        return False
    try:
        if dialog.first.is_visible():
            return True
    except Exception:
        pass
    return page.locator(".switch_account_dialog .account_item").count() > 0


def maybe_expand_account_menu_impl(page: Page) -> None:
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


def should_retry_switch_from_home_impl(current_url: str, home_url: str, has_switch_entry: bool) -> bool:
    if has_switch_entry:
        return False
    normalized_home_url = home_url.strip().rstrip("/")
    if not normalized_home_url:
        return False
    normalized_current_url = current_url.strip().rstrip("/")
    return normalized_current_url != normalized_home_url


def prepare_switch_account_page_impl(
    page: Page,
    home_url: str = "",
    logger: callable | None = None,
    *,
    switch_dialog_ready_fn,
    find_switch_entry_fn,
    should_retry_switch_from_home_fn,
    log_fn,
    wait_for_url_contains_fn,
) -> None:
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content):
        recover_login_timeout_page(
            page,
            logger=logger,
            log_fn=log_fn,
            safe_page_content_fn=safe_page_content,
            wait_or_cancel_fn=lambda current_page, wait_ms, _is_cancelled=None: current_page.wait_for_timeout(wait_ms),
        )
    has_switch_entry = switch_dialog_ready_fn(page) or find_switch_entry_fn(page) is not None
    if not should_retry_switch_from_home_fn(page.url, home_url, has_switch_entry):
        return
    log_fn(logger, f"当前页面未发现切换入口，正在返回后台首页重试：{home_url}")
    page.goto(home_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index"), timeout_ms=4000)
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content):
        recover_login_timeout_page(
            page,
            logger=logger,
            log_fn=log_fn,
            safe_page_content_fn=safe_page_content,
            wait_or_cancel_fn=lambda current_page, wait_ms, _is_cancelled=None: current_page.wait_for_timeout(wait_ms),
        )


def open_switch_account_dialog_impl(
    page: Page,
    timeout_ms: int = 12000,
    *,
    switch_dialog_ready_fn,
    find_switch_entry_fn,
    maybe_expand_account_menu_fn,
    extract_current_account_name_fn,
) -> None:
    if switch_dialog_ready_fn(page):
        return

    deadline = time.monotonic() + (timeout_ms / 1000)
    dialog = page.locator(".switch_account_dialog")
    while time.monotonic() < deadline:
        switch_entry = find_switch_entry_fn(page)
        if switch_entry is not None:
            try:
                switch_entry.click(timeout=1500)
            except Exception:
                switch_entry.evaluate("e => e.click()")
            try:
                dialog.first.wait_for(state="visible", timeout=2000)
            except Exception:
                pass
            if switch_dialog_ready_fn(page):
                return
        maybe_expand_account_menu_fn(page)
        page.wait_for_timeout(500)

    current_url = page.url
    actual_name = extract_current_account_name_fn(page) or "未知"
    raise FetchError(f"当前页面不存在切换账号入口。当前地址：{current_url}，当前账号：{actual_name}")


def extract_current_account_name_impl(page: Page, *, safe_page_content_fn) -> str:
    try:
        html = safe_page_content_fn(page, timeout_ms=5000)
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


def should_switch_account_impl(current_account_name: str, target_account_name: str) -> bool:
    current_name = current_account_name.strip()
    target_name = target_account_name.strip()
    if not current_name or not target_name:
        return True
    return current_name != target_name


def should_switch_for_account_impl(account: AccountConfig, current_account_name: str) -> bool:
    if account.is_entry_account:
        return False
    return should_switch_account_impl(current_account_name, account.name)


def switch_to_account_impl(
    page: Page,
    account_name: str,
    home_url: str = "",
    logger: callable | None = None,
    *,
    prepare_switch_account_page_fn,
    open_switch_account_dialog_fn,
    wait_for_switch_account_items_fn,
    wait_for_current_account_name_fn,
    wait_for_account_switch_stable_fn,
    log_fn,
) -> None:
    prepare_switch_account_page_fn(page, home_url, logger)
    open_switch_account_dialog_fn(page)

    account_items = wait_for_switch_account_items_fn(page, ".switch_account_dialog .account_item", logger)
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
        log_fn(logger, f"当前已是目标账号：{account_name}")
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
    actual_name = wait_for_current_account_name_fn(page, account_name, timeout_ms=5000)
    if actual_name and actual_name != account_name:
        raise FetchError(f"已点击切换账号，但当前实际账号为“{actual_name}”，不是目标账号“{account_name}”。")
    wait_for_account_switch_stable_fn(page, account_name, home_url=home_url)
    log_fn(logger, f"已切换到账号：{account_name}")


def wait_for_account_switch_stable_impl(
    page: Page,
    expected_account_name: str,
    home_url: str = "",
    *,
    extract_current_account_name_fn,
    wait_for_url_contains_fn,
    wait_or_cancel_fn,
    is_cancelled: callable | None = None,
    stable_rounds: int = 2,
    interval_ms: int = 600,
) -> str:
    wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback"), timeout_ms=5000)
    latest_name = ""
    matched_rounds = 0
    for _ in range(6):
        latest_name = extract_current_account_name_fn(page).strip()
        if latest_name == expected_account_name:
            matched_rounds += 1
            if matched_rounds >= stable_rounds:
                return latest_name
        else:
            matched_rounds = 0
        wait_or_cancel_fn(page, interval_ms, is_cancelled)

    if latest_name and latest_name != expected_account_name:
        raise FetchError(
            f"切换账号后页面稳定校验失败，当前实际账号为“{latest_name}”，不是目标账号“{expected_account_name}”。"
        )
    return latest_name


def list_switchable_accounts_impl(
    page: Page,
    home_url: str = "",
    logger: callable | None = None,
    *,
    prepare_switch_account_page_fn,
    open_switch_account_dialog_fn,
    wait_for_switch_account_items_fn,
) -> list[str]:
    prepare_switch_account_page_fn(page, home_url, logger)
    open_switch_account_dialog_fn(page)
    account_items = wait_for_switch_account_items_fn(page, ".switch_account_dialog .account_item .account_name", logger)

    names: list[str] = []
    for index in range(account_items.count()):
        name = (account_items.nth(index).text_content() or "").strip()
        if name and name not in names:
            names.append(name)

    close_icon = page.locator(".switch_account_dialog .close_icon")
    if close_icon.count():
        close_icon.first.evaluate("e => e.click()")
    return names


def wait_for_locator_items_impl(page: Page, locator, timeout_ms: int = 1800, interval_ms: int = 200) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if locator.count() > 0:
            return True
        page.wait_for_timeout(interval_ms)
    return locator.count() > 0


def wait_for_switch_account_items_impl(
    page: Page,
    selector: str,
    logger: callable | None = None,
    retry_limit: int = 3,
    is_cancelled: callable | None = None,
    *,
    wait_for_locator_items_fn,
    log_fn,
    wait_or_cancel_fn,
    open_switch_account_dialog_fn,
):
    locator = page.locator(selector)
    for attempt in range(1, retry_limit + 1):
        if wait_for_locator_items_fn(page, locator):
            return locator
        if attempt >= retry_limit:
            break
        log_fn(logger, f"未读取到切换账号列表，正在进行第 {attempt + 1} 次重试。")
        close_icon = page.locator(".switch_account_dialog .close_icon")
        if close_icon.count():
            try:
                close_icon.first.evaluate("e => e.click()")
            except Exception:
                pass
        wait_or_cancel_fn(page, 1200, is_cancelled)
        open_switch_account_dialog_fn(page)
        locator = page.locator(selector)
    raise FetchError(f"未读取到切换账号列表，已重试 {retry_limit} 次。")


def fetch_switchable_accounts_impl(
    account: AccountConfig,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
    *,
    sync_playwright_fn,
    path_exists_fn,
    validate_shared_browser_profile_dir_fn,
    create_browser_context_fn,
    wait_for_url_contains_fn,
    list_switchable_accounts_fn,
    close_page_fn,
    close_context_and_browser_fn,
) -> list[str]:
    normalized_profile_dir = normalize_profile_dir(
        profile_dir,
        validate_shared_browser_profile_dir_fn=validate_shared_browser_profile_dir_fn,
    )
    state_path = ensure_account_session_available(
        account,
        normalized_profile_dir,
        path_exists_fn=path_exists_fn,
        error_cls=FetchError,
    )

    with sync_playwright_fn() as playwright:
        browser, context = create_browser_context_fn(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        try:
            bootstrap_url = account.home_url
            page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_url_contains_fn(
                page, ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback"), timeout_ms=4000
            )
            names = list_switchable_accounts_fn(page, account.home_url, logger)
        finally:
            close_page_fn(page)
            close_context_and_browser_fn(
                context,
                browser,
                state_path=state_path if normalized_profile_dir else None,
                persist_state=bool(normalized_profile_dir),
                page=page,
            )
    return names
