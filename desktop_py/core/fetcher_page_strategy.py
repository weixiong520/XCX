from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from desktop_py.core.fetcher_output import persist_storage_state, write_fetch_artifacts
from desktop_py.core.fetcher_support import FetchError, _fallback_from_responses
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.parser import extract_labeled_datetime


def register_response_capture(page, capture_response_payload_fn) -> list[Any]:
    captures: list[Any] = []

    def handle_response(response) -> None:
        capture = capture_response_payload_fn(response)
        if capture is not None:
            captures.append(capture)

    page.on("response", handle_response)
    return captures


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
    _log(logger, f"账号 {account.name} 自动生成反馈页链接：{feedback_url}")
    page.goto(feedback_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_iframe_ready_fn(page, timeout_ms=5000, is_cancelled=is_cancelled)
    return feedback_url


def resolve_frame_locator(page, *, output_dir: Path, business_iframe_selector_fn, safe_page_content_fn):
    iframe_selector = business_iframe_selector_fn(page)
    if not iframe_selector:
        html = safe_page_content_fn(page)
        (output_dir / "page.html").write_text(html, encoding="utf-8")
        raise FetchError("页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。")
    return page.frame_locator(iframe_selector)


def is_empty_refund_list(list_text: str) -> bool:
    return "退款申请(0)" in list_text or "暂无内容" in list_text


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
        output_dir, page_html=page_html, frame_html=frame_html, frame_text=list_text, captures=captures
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
    write_result(output_dir, result)
    _log(logger, f"账号 {account.name} 当前无待处理申请。")
    return result


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
) -> FetchResult:
    action_locator = frame_locator.get_by_text("处理", exact=True)
    if action_locator.count():
        action_locator.last.click(timeout=10000)
        page.wait_for_timeout(800)

    frame_text = frame_locator.locator("body").text_content(timeout=15000) or ""
    frame_html = frame_locator.locator("body").inner_html(timeout=15000)
    deadline_text = extract_labeled_datetime(frame_text, "处理截止时间")
    actual_account_name = extract_current_account_name_fn(page)
    if not deadline_text:
        deadline_text = _fallback_from_responses(captures)

    page_html = safe_page_content_fn(page)
    write_fetch_artifacts(
        output_dir, page_html=page_html, frame_html=frame_html, frame_text=frame_text, captures=captures
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
    write_result(output_dir, result)
    _log(logger, f"账号 {account.name} 抓取成功，处理截止时间：{deadline_text}")
    return result


def write_result(output_dir: Path, result: FetchResult) -> None:
    (output_dir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _log(logger: callable | None, message: str) -> None:
    if logger:
        logger(message)
