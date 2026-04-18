from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from desktop_py.core.browser_runtime import configure_playwright_environment
configure_playwright_environment()

from playwright.sync_api import BrowserContext, Locator, Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright

from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.parser import convert_timestamp, extract_labeled_datetime
from desktop_py.core.store import account_output_dir, validate_shared_browser_profile_dir


class FetchError(RuntimeError):
    """抓取失败。"""


SWITCH_ACCOUNT_LIST_RETRY_LIMIT = 3


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


def wait_for_url_contains(page: Page, keywords: tuple[str, ...], timeout_ms: int = 5000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        current_url = page.url
        if any(keyword in current_url for keyword in keywords):
            return True
        page.wait_for_timeout(200)
    return any(keyword in page.url for keyword in keywords)


def wait_for_current_account_name(page: Page, expected_name: str, timeout_ms: int = 5000) -> str:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        actual_name = extract_current_account_name(page)
        if actual_name:
            if actual_name == expected_name:
                return actual_name
        page.wait_for_timeout(250)
    return extract_current_account_name(page)


def wait_for_iframe_ready(page: Page, timeout_ms: int = 5000) -> bool:
    iframe = page.locator("#js_iframe")
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if iframe.count() > 0:
            try:
                handle = iframe.element_handle()
                if handle is not None:
                    frame = handle.content_frame()
                    if frame is not None and frame.url and frame.url != "about:blank":
                        try:
                            frame.wait_for_load_state("domcontentloaded", timeout=1000)
                        except Exception:
                            pass
                        try:
                            frame.wait_for_load_state("networkidle", timeout=1000)
                        except Exception:
                            pass
                        body = frame.locator("body")
                        body_text = (body.text_content(timeout=500) or "").strip()
                        body_html = (body.inner_html(timeout=500) or "").strip()
                        if any(token in body_text for token in ("退款申请", "处理截止时间", "处理", "暂无内容")):
                            return True
                        if any(token in body_html for token in ("退款申请", "处理截止时间", "处理", "暂无内容")):
                            return True
                        if body_text and not body_text.startswith("document.getElementById("):
                            return True
            except Exception:
                pass
        page.wait_for_timeout(200)
    return False


def _is_navigation_content_error(error: Exception) -> bool:
    message = str(error).lower()
    return "page.content" in message and ("navigating" in message or "changing the content" in message)


def safe_page_content(page: Page, timeout_ms: int = 3000) -> str:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_error = None
    try:
        page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 1500))
    except Exception:
        pass
    while time.monotonic() < deadline:
        try:
            return page.content()
        except Exception as exc:
            last_error = exc
            if _is_navigation_content_error(exc):
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=1000)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=1000)
                except Exception:
                    pass
                page.wait_for_timeout(300)
                continue
            page.wait_for_timeout(200)
    if last_error is not None:
        raise last_error
    return page.content()


def _fallback_from_responses(responses: list[Any]) -> str:
    candidates: list[tuple[int, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = f"{path}.{key}" if path else key
                visit(item, next_path)
            return

        if isinstance(value, list):
            for index, item in enumerate(value):
                next_path = f"{path}[{index}]"
                visit(item, next_path)
            return

        if value is None:
            return

        text = str(value).strip()
        if not text:
            return

        normalized = convert_timestamp(text)
        matched = re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:[日\sT]*\d{1,2}:\d{2}(?::\d{2})?)?", normalized)
        if not matched:
            return

        path_lower = path.lower()
        score = 0
        if "appeal_deadline_time" in path_lower:
            score = 100
        elif "deadline_time" in path_lower:
            score = 95
        elif "deadline" in path_lower:
            score = 90

        if score > 0:
            candidates.append((score, matched.group(0)))

    visit(responses, "$")
    if not candidates:
        return ""
    return max(candidates, key=lambda item: item[0])[1]


def _capture_response_payload(response: Response) -> Any | None:
    content_type = (response.headers.get("content-type") or "").lower()
    if not any(keyword in content_type for keyword in ("json", "javascript", "text")):
        return None

    try:
        text = response.text()
    except Exception:
        return None

    if not text.strip():
        return None

    try:
        body: Any = json.loads(text)
    except Exception:
        body = text[:3000]

    return {
        "url": response.url,
        "status": response.status,
        "content_type": content_type,
        "body": body,
    }


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
    matched = None
    try:
        import re

        matched = re.search(r'"nickName":"([^"]+)"', html)
        if matched:
            return matched.group(1).strip()
    except Exception:
        pass

    try:
        current_names = page.locator(".switch_account_dialog .account_item .current_login").locator("xpath=ancestor::div[contains(@class, 'account_item')]").locator(".account_name")
        if current_names.count():
            return (current_names.first.text_content() or "").strip()
    except Exception:
        pass

    return ""


def build_feedback_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    query = parse_qs(parsed.query)
    token = (query.get("token") or [""])[0]
    if not token:
        raise FetchError("当前后台地址中未找到有效 token，无法自动构造反馈页链接。")
    return "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?" + urlencode(
        {
            "action": "plugin_redirect",
            "plugin_uin": "1010",
            "selected": "2",
            "token": token,
            "lang": "zh_CN",
        }
    )


def save_login_state(account: AccountConfig, wait_seconds: int, logger: callable | None = None) -> str:
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
                page.wait_for_timeout(2000)
                if "token=" in page.url or "/wxamp/index/index" in page.url:
                    context.storage_state(path=str(state_path), indexed_db=True)
                    saved = True
                    break

            if not saved:
                context.storage_state(path=str(state_path), indexed_db=True)
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
                page.wait_for_timeout(2000)
                if "token=" in page.url or "/wxamp/index/index" in page.url:
                    context.storage_state(path=str(state_path), indexed_db=True)
                    saved = True
                    break

            if not saved:
                context.storage_state(path=str(state_path), indexed_db=True)
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


def wait_for_switch_account_items(page: Page, selector: str, logger: callable | None = None, retry_limit: int = SWITCH_ACCOUNT_LIST_RETRY_LIMIT):
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
        page.wait_for_timeout(1200)
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
    # 反馈页 token 容易过期；统一从后台首页进入，切换账号后再生成最新反馈页链接。
    return account.home_url


def create_browser_context(playwright, account: AccountConfig, headless: bool, profile_dir: str = ""):
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    if normalized_profile_dir:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=normalized_profile_dir,
            headless=headless,
            viewport={"width": 1440, "height": 1200},
        )
        return None, context

    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(storage_state=str(account.state_path), viewport={"width": 1440, "height": 1200})
    return browser, context


def _close_page(page) -> None:
    close = getattr(page, "close", None)
    if callable(close):
        close()


def _close_context_and_browser(context, browser, state_path: Path | None = None, persist_state: bool = False) -> None:
    context_error: Exception | None = None
    if persist_state and state_path is not None:
        try:
            context.storage_state(path=str(state_path), indexed_db=True)
        except Exception as exc:
            context_error = exc

    try:
        context.close()
    except Exception as exc:
        if context_error is None:
            context_error = exc

    browser_error: Exception | None = None
    if browser:
        try:
            browser.close()
        except Exception as exc:
            browser_error = exc

    if context_error is not None:
        raise context_error
    if browser_error is not None:
        raise browser_error


def _fetch_account_in_page(page: Page, context, account: AccountConfig, logger: callable | None = None, profile_dir: str = "") -> FetchResult:
    output_dir = account_output_dir(account.name)
    captures: list[Any] = []

    def handle_response(response: Response) -> None:
        capture = _capture_response_payload(response)
        if capture is not None:
            captures.append(capture)

    page.on("response", handle_response)

    bootstrap_url = resolve_bootstrap_url(account, output_dir)
    page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains(page, ("token=", "/wxamp/index/index"), timeout_ms=4000)

    if "token=" not in page.url and bootstrap_url == account.home_url:
        raise FetchError("当前登录态未自动跳入后台页，且没有可复用的历史反馈页地址，无法启动自动切换账号。")

    current_account_name = extract_current_account_name(page)
    if should_switch_for_account(account, current_account_name):
        switch_to_account(page, account.name, account.home_url, logger)
    elif account.is_entry_account:
        _log(logger, "入口账号使用当前共享会话，不执行切换账号。")
    else:
        _log(logger, f"账号 {account.name} 已处于当前会话，跳过切换步骤。")

    feedback_url = build_feedback_url(page.url)
    _log(logger, f"账号 {account.name} 自动生成反馈页链接：{feedback_url}")
    page.goto(feedback_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_iframe_ready(page, timeout_ms=5000)

    if page.locator("#js_iframe").count() == 0:
        html = safe_page_content(page)
        (output_dir / "page.html").write_text(html, encoding="utf-8")
        raise FetchError("页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。")

    frame_locator = page.frame_locator("#js_iframe")

    list_text = frame_locator.locator("body").text_content(timeout=15000) or ""
    if "退款申请(0)" in list_text or "暂无内容" in list_text:
        page_html = safe_page_content(page)
        frame_html = frame_locator.locator("body").inner_html(timeout=15000)
        (output_dir / "page.html").write_text(page_html, encoding="utf-8")
        (output_dir / "iframe.html").write_text(frame_html, encoding="utf-8")
        (output_dir / "iframe.txt").write_text(list_text, encoding="utf-8")
        (output_dir / "responses.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        actual_account_name = extract_current_account_name(page)
        if profile_dir.strip():
            state_path = Path(account.state_path)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(state_path), indexed_db=True)
        result = FetchResult(
            account_name=account.name,
            ok=True,
            actual_account_name=actual_account_name,
            deadline_text="",
            deadline_source="",
            matched_path="",
            page_url=feedback_url,
            note="当前账号无待处理申请。"
        )
        (output_dir / "result.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _log(logger, f"账号 {account.name} 当前无待处理申请。")
        return result

    action_locator = frame_locator.get_by_text("处理", exact=True)
    if action_locator.count():
        action_locator.last.click(timeout=10000)
        page.wait_for_timeout(800)

    frame_text = frame_locator.locator("body").text_content(timeout=15000) or ""
    frame_html = frame_locator.locator("body").inner_html(timeout=15000)
    deadline_text = extract_labeled_datetime(frame_text, "处理截止时间")
    actual_account_name = extract_current_account_name(page)
    if not deadline_text:
        deadline_text = _fallback_from_responses(captures)

    page_html = safe_page_content(page)
    (output_dir / "page.html").write_text(page_html, encoding="utf-8")
    (output_dir / "iframe.html").write_text(frame_html, encoding="utf-8")
    (output_dir / "iframe.txt").write_text(frame_text, encoding="utf-8")
    (output_dir / "responses.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not deadline_text:
        raise FetchError("未在详情页文本中提取到处理截止时间。")

    if profile_dir.strip():
        state_path = Path(account.state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(account.state_path), indexed_db=True)
    result = FetchResult(
        account_name=account.name,
        ok=True,
        actual_account_name=actual_account_name,
        deadline_text=deadline_text,
        deadline_source="iframe-label",
        matched_path="$iframeText.处理截止时间",
        page_url=feedback_url,
        note="已完成详情页抓取。"
    )
    (output_dir / "result.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _log(logger, f"账号 {account.name} 抓取成功，处理截止时间：{deadline_text}")
    return result


def fetch_account(
    account: AccountConfig,
    wait_seconds: int,
    headless: bool = True,
    logger: callable | None = None,
    profile_dir: str = "",
) -> FetchResult:
    normalized_profile_dir = validate_shared_browser_profile_dir(profile_dir) if profile_dir.strip() else ""
    state_path = Path(account.state_path)
    if not state_path.exists() and not normalized_profile_dir:
        raise FetchError(f"账号 {account.name} 缺少登录态文件：{state_path}")

    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright, account, headless, normalized_profile_dir)
        page = context.new_page()
        try:
            return _fetch_account_in_page(page, context, account, logger, normalized_profile_dir)
        finally:
            _close_page(page)
            _close_context_and_browser(context, browser)


def fetch_accounts_batch(
    accounts: list[AccountConfig],
    headless: bool = True,
    logger: callable | None = None,
    progress: callable | None = None,
    profile_dir: str = "",
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
            primary_account = group_accounts[0]
            state_path = Path(primary_account.state_path)
            if not state_path.exists() and not normalized_profile_dir:
                raise FetchError(f"账号 {primary_account.name} 缺少登录态文件：{state_path}")

            browser, context = create_browser_context(playwright, primary_account, headless, normalized_profile_dir)
            try:
                for account in group_accounts:
                    page = context.new_page()
                    try:
                        result = _fetch_account_in_page(page, context, account, logger, normalized_profile_dir)
                    except Exception as exc:
                        result = FetchResult(account_name=account.name, ok=False, note=str(exc))
                    finally:
                        _close_page(page)
                    results.append(result)
                    if progress is not None:
                        progress(result)
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


def _log(logger: callable | None, message: str) -> None:
    if logger:
        logger(message)
