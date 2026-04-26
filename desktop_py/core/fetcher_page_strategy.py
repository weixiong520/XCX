from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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


def filter_detail_captures(captures: list[Any], feedback_url: str) -> list[Any]:
    current_token = (parse_qs(urlparse(feedback_url).query).get("token") or [""])[0].strip()
    if not captures:
        return []

    filtered: list[Any] = []
    for capture in captures:
        if not isinstance(capture, dict):
            continue
        capture_url = str(capture.get("url", "") or "").strip()
        if not capture_url:
            continue
        response_type = str(capture.get("response_type", "") or "").strip()
        capture_token = str(capture.get("token", "") or "").strip()
        if current_token and capture_token and capture_token != current_token:
            continue
        if response_type in {"detail", "list"}:
            filtered.append(capture)
            continue
        if any(keyword in capture_url for keyword in ("gameFeedback", "refund")):
            if current_token and capture_token and capture_token != current_token:
                continue
            filtered.append(capture)
    return filtered


def _latest_refund_capture(captures: list[Any], response_type: str) -> dict[str, Any] | None:
    for capture in reversed(captures):
        if not isinstance(capture, dict):
            continue
        if str(capture.get("response_type", "") or "").strip() != response_type:
            continue
        return capture
    return None


def _refund_items_from_capture(capture: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not capture:
        return []
    body = capture.get("body")
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("user_refund_check_list")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def list_capture_result(captures: list[Any]) -> str:
    capture = _latest_refund_capture(captures, "list")
    if capture is None:
        return "unknown"
    items = _refund_items_from_capture(capture)
    if items:
        return "non_empty"
    body = capture.get("body")
    if not isinstance(body, dict):
        return "unknown"
    data = body.get("data")
    if not isinstance(data, dict):
        return "unknown"
    total_count = data.get("total_count")
    if total_count == 0:
        return "empty"
    return "unknown"


def extract_deadline_from_refund_capture(capture: dict[str, Any] | None) -> str:
    items = _refund_items_from_capture(capture)
    for item in items:
        ctrl_info = item.get("ctrl_info")
        if not isinstance(ctrl_info, dict):
            continue
        deadline_text = _fallback_from_responses([ctrl_info])
        if deadline_text:
            return deadline_text
    if capture is None:
        return ""
    return _fallback_from_responses([capture])


def extract_deadline_from_captures(captures: list[Any]) -> str:
    detail_capture = _latest_refund_capture(captures, "detail")
    deadline_text = extract_deadline_from_refund_capture(detail_capture)
    if deadline_text:
        return deadline_text
    list_capture = _latest_refund_capture(captures, "list")
    return extract_deadline_from_refund_capture(list_capture)


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
    if list_capture_result(captures) == "non_empty":
        return True
    if extract_deadline_from_captures(captures).strip():
        return True

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
    retries: int = 6,
    interval_ms: int = 1500,
) -> tuple[bool, str]:
    latest_text = initial_text
    if list_capture_result(captures) == "non_empty":
        return False, latest_text
    if has_pending_refund_signal_fn(latest_text) or captures_indicate_non_empty_refunds_fn(captures):
        return False, latest_text

    if not is_empty_refund_list_fn(latest_text):
        return False, latest_text

    for _ in range(retries):
        wait_or_cancel_fn(page, interval_ms, is_cancelled)
        latest_text = frame_locator.locator("body").text_content(timeout=15000) or ""
        if list_capture_result(captures) == "non_empty":
            return False, latest_text
        if has_pending_refund_signal_fn(latest_text) or captures_indicate_non_empty_refunds_fn(captures):
            return False, latest_text
        if not is_empty_refund_list_fn(latest_text):
            return False, latest_text

    if list_capture_result(captures) == "empty":
        return True, latest_text
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
    actual_account_name = extract_current_account_name_fn(page)
    if profile_dir.strip():
        persist_storage_state(context, account.state_path, page=page, logger=logger, log_fn=_log)
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
    feedback_url: str,
    extract_labeled_datetime_fn,
    fallback_from_responses_fn,
    filter_detail_captures_fn,
    wait_or_cancel_fn,
    is_cancelled: callable | None = None,
    retries: int = 8,
    interval_ms: int = 1500,
) -> tuple[str, str, str]:
    latest_text = ""
    latest_html = ""
    deadline_text = ""

    for attempt in range(retries + 1):
        detail_captures = filter_detail_captures_fn(captures, feedback_url)
        deadline_text = extract_deadline_from_captures(detail_captures)
        if deadline_text:
            latest_text = frame_locator.locator("body").text_content(timeout=15000) or ""
            latest_html = frame_locator.locator("body").inner_html(timeout=15000)
            return deadline_text, latest_text, latest_html

        latest_text = frame_locator.locator("body").text_content(timeout=15000) or ""
        latest_html = frame_locator.locator("body").inner_html(timeout=15000)
        deadline_text = extract_labeled_datetime_fn(latest_text, "处理截止时间")
        if not deadline_text:
            deadline_text = fallback_from_responses_fn(detail_captures)
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
    detail_capture_start = 0
    if action_locator.count():
        detail_capture_start = len(captures)
        action_locator.last.click(timeout=10000)
    deadline_text, frame_text, frame_html = confirm_detail_deadline_fn(
        page=page,
        frame_locator=frame_locator,
        captures=captures[detail_capture_start:],
        feedback_url=feedback_url,
        is_cancelled=is_cancelled,
    )
    actual_account_name = extract_current_account_name_fn(page)

    if not deadline_text:
        page_html = safe_page_content_fn(page)
        write_fetch_artifacts(
            account.name,
            page_html=page_html,
            frame_html=frame_html,
            frame_text=frame_text,
            captures=captures,
        )
        raise FetchError("未在详情页文本中提取到处理截止时间。")

    if profile_dir.strip():
        persist_storage_state(context, account.state_path, page=page, logger=logger, log_fn=_log)
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
