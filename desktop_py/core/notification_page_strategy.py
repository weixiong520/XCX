from __future__ import annotations

from collections.abc import Callable
from typing import Any

from desktop_py.core.fetcher_support import (
    FetchError,
    is_login_timeout_page,
    recover_login_timeout_page,
)
from desktop_py.core.store import write_account_output_json, write_account_output_text

NOTIFICATION_CENTER_URL_KEYWORD = "/wxamp/tools/wasysnotify"
NOTIFICATION_CONTAINER_SELECTOR = "div.page_notice"
NOTIFICATION_ITEM_SELECTOR = "dl.notice_item.js_msg_item"
NOTIFICATION_ENTRY_TEXT = "通知中心"

TARGET_NOTIFICATION_RULES = {
    "annual_review": "小程序微信认证年审通知",
    "copyright_complaint": "你的账号收到一条侵权投诉",
}


def collect_notification_items(page) -> list[dict[str, Any]]:
    locator = page.locator(NOTIFICATION_ITEM_SELECTOR)
    if locator.count() == 0:
        return []
    items = locator.evaluate_all(
        """
        elements => elements.map(el => ({
          notify_id: (el.getAttribute('notify_id') || '').trim(),
          class_name: (el.className || '').trim(),
          title: (el.querySelector('.notice_title')?.textContent || '').trim(),
          time_text: (el.querySelector('.notice_time')?.textContent || '').trim(),
          content_text: (el.querySelector('dd')?.textContent || '').trim()
        }))
        """
    )
    return [item for item in items if isinstance(item, dict)]


def filter_target_unread_notifications(items: list[dict[str, Any]], account_name: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for item in items:
        class_name = str(item.get("class_name", "") or "").strip()
        if "readed" in class_name:
            continue
        title = str(item.get("title", "") or "").strip()
        if not title:
            continue
        for rule_name, expected_title in TARGET_NOTIFICATION_RULES.items():
            if title != expected_title:
                continue
            matched.append(
                {
                    "account_name": account_name,
                    "notify_id": str(item.get("notify_id", "") or "").strip(),
                    "title": title,
                    "time_text": str(item.get("time_text", "") or "").strip(),
                    "content_text": str(item.get("content_text", "") or "").strip(),
                    "is_unread": True,
                    "matched_rule": rule_name,
                }
            )
            break
    return matched


def build_notification_summary(notifications: list[dict[str, Any]]) -> str:
    if not notifications:
        return "通知中心无目标未读消息。"
    titles = "、".join(item["title"] for item in notifications[:3] if item.get("title"))
    suffix = " 等" if len(notifications) > 3 else ""
    return f"通知中心未读消息 {len(notifications)} 条：{titles}{suffix}"


def open_notification_center(
    page,
    *,
    account,
    logger: Callable[[str], None] | None,
    log_fn,
    wait_for_url_contains_fn,
    safe_page_content_fn,
    is_cancelled: callable | None = None,
) -> None:
    page.goto(account.home_url, wait_until="domcontentloaded", timeout=60000)
    wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index"), timeout_ms=4000, is_cancelled=is_cancelled)
    if is_login_timeout_page(page, safe_page_content_fn=safe_page_content_fn):
        recover_login_timeout_page(
            page,
            logger=logger,
            log_fn=log_fn,
            safe_page_content_fn=safe_page_content_fn,
            wait_or_cancel_fn=lambda current_page, wait_ms, cancelled=None: current_page.wait_for_timeout(wait_ms),
            is_cancelled=is_cancelled,
        )
        wait_for_url_contains_fn(page, ("token=", "/wxamp/index/index"), timeout_ms=4000, is_cancelled=is_cancelled)

    entry = page.get_by_text(NOTIFICATION_ENTRY_TEXT, exact=False)
    if entry.count() == 0:
        raise FetchError("未找到通知中心入口。")
    try:
        entry.first.click(timeout=2000)
    except Exception:
        entry.first.evaluate("e => e.click()")
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    if NOTIFICATION_CENTER_URL_KEYWORD not in page.url and page.locator(NOTIFICATION_CONTAINER_SELECTOR).count() == 0:
        raise FetchError("进入通知中心失败。")


def fetch_notifications(
    page,
    *,
    account,
    logger: Callable[[str], None] | None,
    output_dir,
    log_fn,
    wait_for_url_contains_fn,
    safe_page_content_fn,
    is_cancelled: callable | None = None,
) -> dict[str, Any]:
    try:
        open_notification_center(
            page,
            account=account,
            logger=logger,
            log_fn=log_fn,
            wait_for_url_contains_fn=wait_for_url_contains_fn,
            safe_page_content_fn=safe_page_content_fn,
            is_cancelled=is_cancelled,
        )
        items = collect_notification_items(page)
        notifications = filter_target_unread_notifications(items, account.name)
        write_account_output_json(account.name, "notifications.json", notifications)
        summary = build_notification_summary(notifications)
        log_fn(logger, f"账号 {account.name} {summary}")
        return {
            "ok": True,
            "notifications": notifications,
            "summary": summary,
            "page_url": page.url,
        }
    except Exception as exc:
        try:
            write_account_output_text(account.name, "notification_page.html", safe_page_content_fn(page))
        except Exception:
            pass
        write_account_output_json(account.name, "notifications.json", [])
        message = f"通知中心抓取失败：{exc}"
        log_fn(logger, f"账号 {account.name} {message}")
        return {
            "ok": False,
            "notifications": [],
            "summary": message,
            "page_url": page.url,
        }
