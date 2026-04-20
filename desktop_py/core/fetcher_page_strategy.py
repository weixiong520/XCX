from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from desktop_py.core.fetcher_output import persist_storage_state, write_fetch_artifacts
from desktop_py.core.fetcher_support import FetchError, _fallback_from_responses
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.store import write_account_output_text, write_fetch_result


def register_response_capture(page, capture_response_payload_fn) -> tuple[list[Any], Callable[[], None]]:
    captures: list[Any] = []

    def handle_response(response) -> None:
        capture = capture_response_payload_fn(response)
        if capture is not None:
            captures.append(capture)

    page.on("response", handle_response)

    def cleanup() -> None:
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass

    return captures, cleanup


def open_feedback_page(
    page,
    *,
    account: AccountConfig,
    logger: callable | None,
    build_feedback_url_fn,
    wait_for_iframe_ready_fn,
    is_cancelled: callable | None = None,
) -> str:
    feedback_url = build_feedback_url_fn(page.url)
    page.goto(feedback_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_iframe_ready_fn(page, timeout_ms=5000, is_cancelled=is_cancelled)
    return feedback_url


def resolve_frame_locator(page, *, output_dir: Path, business_iframe_selector_fn, safe_page_content_fn):
    iframe_selector = business_iframe_selector_fn(page)
    if not iframe_selector:
        html = safe_page_content_fn(page)
        write_account_output_text(output_dir.name, "page.html", html)
        raise FetchError("页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。")
    return page.frame_locator(iframe_selector)


def is_empty_refund_list(list_text: str) -> bool:
    return "退款申请(0)" in list_text


def has_pending_refund_signal(list_text: str) -> bool:
    text = list_text.strip()
    if not text:
        return False
    return "处理截止时间" in text or "退款申请(" in text and "退款申请(0)" not in text or "处理" in text


def captures_indicate_non_empty_refunds(captures: list[Any]) -> bool:
    deadline_candidate = _fallback_from_responses(captures)
    if deadline_candidate.strip():
        return True

    for capture in captures:
        if not isinstance(capture, dict):
            continue
        body = capture.get("body")
        body_text = str(body)
        if any(token in body_text for token in ("处理截止时间", "refund", "deadline", "申请单", "退款申请")):
            if "退款申请(0)" not in body_text and '"count": 0' not in body_text and "'count': 0" not in body_text:
                return True
    return False


def confirm_empty_refund_list(
    *,
    page,
    frame_locator,
    initial_text: str,
    captures: list[Any],
    is_empty_refund_list_fn,
    has_pending_refund_signal_fn,
    captures_indicate_non_empty_refunds_fn,
    is_cancelled: callable | None = None,
    wait_or_cancel_fn,
    retries: int = 2,
    interval_ms: int = 1500,
) -> tuple[bool, str]:
    latest_text = initial_text
    if has_pending_refund_signal_fn(latest_text) or captures_indicate_non_empty_refunds_fn(captures):
        return False, latest_text

    if not is_empty_refund_list_fn(latest_text):
        return False, latest_text

    for _ in range(retries):
        wait_or_cancel_fn(page, interval_ms, is_cancelled)
        latest_text = frame_locator.locator("body").text_content(timeout=15000) or ""
        if has_pending_refund_signal_fn(latest_text) or captures_indicate_non_empty_refunds_fn(captures):
            return False, latest_text
        if not is_empty_refund_list_fn(latest_text):
            return False, latest_text

    return True, latest_text


def build_empty_refund_result(
    *,
    page,
    context,
    account: AccountConfig,
    output_dir: Path,
    frame_locator,
    list_text: str,
    captures: list[Any],
    feedback_url: str,
    profile_dir: str,
    logger: callable | None,
    safe_page_content_fn,
    extract_current_account_name_fn,
) -> FetchResult:
    page_html = safe_page_content_fn(page)
    frame_html = frame_locator.locator("body").inner_html(timeout=15000)
    write_fetch_artifacts(
        account.name, page_html=page_html, frame_html=frame_html, frame_text=list_text, captures=captures
    )
    actual_account_name = extract_current_account_name_fn(page)
    if profile_dir.strip():
        persist_storage_state(context, account.state_path)
    result = FetchResult(
        account_name=account.name,
        ok=True,
        actual_account_name=actual_account_name,
        deadline_text="",
        deadline_source="",
        matched_path="",
        page_url=feedback_url,
        note="当前账号无待处理申请。",
    )
    write_fetch_result(account.name, result)
    _log(logger, f"账号 {account.name} 当前无待处理申请。")
    return result


def confirm_detail_deadline(
    *,
    page,
    frame_locator,
    captures: list[Any],
    extract_labeled_datetime_fn,
    fallback_from_responses_fn,
    wait_or_cancel_fn,
    is_cancelled: callable | None = None,
    retries: int = 3,
    interval_ms: int = 1200,
) -> tuple[str, str, str]:
    latest_text = ""
    latest_html = ""
    deadline_text = ""

    for attempt in range(retries + 1):
        latest_text = frame_locator.locator("body").text_content(timeout=15000) or ""
        latest_html = frame_locator.locator("body").inner_html(timeout=15000)
        deadline_text = extract_labeled_datetime_fn(latest_text, "处理截止时间")
        if not deadline_text:
            deadline_text = fallback_from_responses_fn(captures)
        if deadline_text:
            return deadline_text, latest_text, latest_html
        if attempt < retries:
            wait_or_cancel_fn(page, interval_ms, is_cancelled)

    return deadline_text, latest_text, latest_html


def build_detail_result(
    *,
    page,
    context,
    account: AccountConfig,
    output_dir: Path,
    frame_locator,
    captures: list[Any],
    feedback_url: str,
    profile_dir: str,
    logger: callable | None,
    safe_page_content_fn,
    extract_current_account_name_fn,
    confirm_detail_deadline_fn,
    is_cancelled: callable | None = None,
) -> FetchResult:
    action_locator = frame_locator.get_by_text("处理", exact=True)
    if action_locator.count():
        action_locator.last.click(timeout=10000)
    deadline_text, frame_text, frame_html = confirm_detail_deadline_fn(
        page=page,
        frame_locator=frame_locator,
        captures=captures,
        is_cancelled=is_cancelled,
    )
    actual_account_name = extract_current_account_name_fn(page)

    page_html = safe_page_content_fn(page)
    write_fetch_artifacts(
        account.name, page_html=page_html, frame_html=frame_html, frame_text=frame_text, captures=captures
    )

    if not deadline_text:
        raise FetchError("未在详情页文本中提取到处理截止时间。")

    if profile_dir.strip():
        persist_storage_state(context, account.state_path)
    result = FetchResult(
        account_name=account.name,
        ok=True,
        actual_account_name=actual_account_name,
        deadline_text=deadline_text,
        deadline_source="iframe-label",
        matched_path="$iframeText.处理截止时间",
        page_url=feedback_url,
        note="已完成详情页抓取。",
    )
    write_fetch_result(account.name, result)
    _log(logger, f"账号 {account.name} 抓取成功，处理截止时间：{deadline_text}")
    return result


def _log(logger: callable | None, message: str) -> None:
    if logger:
        logger(message)
