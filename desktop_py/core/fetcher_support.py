from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.sync_api import Page, Response

from desktop_py.core.parser import convert_timestamp
from desktop_py.core.store import validate_shared_browser_profile_dir


class FetchError(RuntimeError):
    """抓取失败。"""


class CancelledError(RuntimeError):
    """后台任务已取消。"""


SWITCH_ACCOUNT_LIST_RETRY_LIMIT = 3
BUSINESS_IFRAME_SELECTORS = (
    "#js_iframe",
    "iframe[src*='gameFeedback']",
    "iframe[src*='refund']",
)


def normalize_profile_dir(profile_dir: str, *, validate_shared_browser_profile_dir_fn) -> str:
    if not profile_dir.strip():
        return ""
    return validate_shared_browser_profile_dir_fn(profile_dir)


def account_state_path(account) -> Path:
    return Path(account.state_path)


def ensure_account_session_available(
    account,
    normalized_profile_dir: str,
    *,
    path_exists_fn,
    error_cls: type[Exception] | None = None,
) -> Path | None:
    state_path = account_state_path(account)
    if normalized_profile_dir:
        return state_path
    if path_exists_fn(state_path):
        return state_path
    if error_cls is not None:
        raise error_cls(f"账号 {account.name} 缺少登录态文件：{state_path}")
    return None


def wait_for_url_contains(
    page: Page,
    keywords: tuple[str, ...],
    timeout_ms: int = 5000,
    is_cancelled: callable | None = None,
) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        current_url = page.url
        if any(keyword in current_url for keyword in keywords):
            return True
        wait_or_cancel(page, 200, is_cancelled)
    return any(keyword in page.url for keyword in keywords)


def wait_for_current_account_name(
    page: Page,
    expected_name: str,
    timeout_ms: int = 5000,
    is_cancelled: callable | None = None,
    *,
    extract_current_account_name_fn,
) -> str:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        actual_name = extract_current_account_name_fn(page)
        if actual_name and actual_name == expected_name:
            return actual_name
        wait_or_cancel(page, 250, is_cancelled)
    return extract_current_account_name_fn(page)


def business_iframe_selector(page: Page) -> str:
    for selector in BUSINESS_IFRAME_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return selector
        except Exception:
            continue
    return ""


def wait_for_iframe_ready(page: Page, timeout_ms: int = 5000, is_cancelled: callable | None = None) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        selector = business_iframe_selector(page)
        if not selector:
            wait_or_cancel(page, 200, is_cancelled)
            continue
        iframe = page.locator(selector)
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
        wait_or_cancel(page, 200, is_cancelled)
    return False


def wait_or_cancel(page: Page, timeout_ms: int, is_cancelled: callable | None = None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise CancelledError("任务已取消")
    page.wait_for_timeout(timeout_ms)
    if is_cancelled is not None and is_cancelled():
        raise CancelledError("任务已取消")


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


def extract_response_token(response_url: str) -> str:
    return (parse_qs(urlparse(response_url).query).get("token") or [""])[0].strip()


def classify_refund_response_type(response_url: str, body: Any) -> str:
    url = response_url.strip().lower()
    if "getuserrefundchecklist" in url:
        if "cid=" in url or "openid=" in url:
            return "detail"
        return "list"
    if "checkuserrefundcheck" in url or "getpayorderlistforuserrefund" in url:
        return "detail"

    body_text = str(body)
    if "user_refund_check_list" in body_text:
        return "detail" if any(keyword in url for keyword in ("cid=", "openid=")) else "list"
    return "other"


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

    response_type = classify_refund_response_type(response.url, body)
    return {
        "url": response.url,
        "status": response.status,
        "content_type": content_type,
        "body": body,
        "token": extract_response_token(response.url),
        "response_type": response_type,
        "captured_at": time.time(),
    }


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


def create_browser_context(playwright, account, headless: bool, profile_dir: str = ""):
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


def _log(logger: callable | None, message: str) -> None:
    if logger:
        logger(message)
