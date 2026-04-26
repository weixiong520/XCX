from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from desktop_py.core.models import FetchResult


def send_feishu_text(webhook: str, content: str) -> None:
    if not webhook.strip():
        raise ValueError("飞书机器人地址不能为空。")
    response = requests.post(webhook, json={"msg_type": "text", "content": {"text": content}}, timeout=20)
    response.raise_for_status()
    payload = _read_feishu_response(response)
    code = _feishu_response_code(payload)
    if code != 0:
        message = str(payload.get("msg") or payload.get("message") or payload.get("StatusMessage") or "").strip()
        suffix = f"：{message}" if message else ""
        raise ValueError(f"飞书消息发送失败，业务码 {code}{suffix}")


def _read_feishu_response(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("飞书消息发送失败：响应不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise ValueError("飞书消息发送失败：响应内容格式不正确。")
    return payload


def _feishu_response_code(payload: dict[str, Any]) -> int:
    raw_code = payload.get("code", payload.get("StatusCode", payload.get("status_code")))
    if raw_code is None:
        raise ValueError("飞书消息发送失败：响应缺少业务状态码。")
    try:
        return int(raw_code)
    except (TypeError, ValueError) as exc:
        raise ValueError("飞书消息发送失败：响应缺少业务状态码。") from exc


def build_summary(results: list[FetchResult]) -> str:
    pending_results = sorted(
        [result for result in results if _should_include_in_summary(result)],
        key=_summary_sort_key,
    )
    lines = [
        "微信退款处理截止时间日报",
        f"待处理账号：{len(pending_results)} 个",
        "",
    ]
    if not pending_results:
        lines.append("暂无待处理账号。")
        return "\n".join(lines)
    for index, result in enumerate(pending_results, start=1):
        lines.append(_format_pending_result(index, result))
    return "\n".join(lines)


def _format_pending_result(index: int, result: FetchResult) -> str:
    parts: list[str] = []
    if result.deadline_text.strip():
        parts.append(f"未成年申请截止 {result.deadline_text}")
    notification_summary = _notification_summary(result)
    if notification_summary:
        parts.append(notification_summary)
    line = "；".join(parts)
    return f"{index}. {result.account_name}：{line}{_actual_suffix(result)}"


def _notification_summary(result: FetchResult) -> str:
    note = str(result.note or "").strip()
    if not note:
        return ""
    for segment in note.split("；"):
        value = segment.strip()
        if value.startswith("通知中心未读消息"):
            return value
    return ""


def _should_include_in_summary(result: FetchResult) -> bool:
    if not result.account_name.strip() or not result.ok:
        return False
    return bool(result.deadline_text.strip() or _notification_summary(result))


def _summary_sort_key(result: FetchResult) -> tuple[int, datetime, str]:
    deadline = _parse_deadline(result.deadline_text)
    if deadline is not None:
        return (0, deadline, result.account_name)
    return (1, datetime.max, result.account_name)


def _actual_suffix(result: FetchResult) -> str:
    if not result.actual_account_name or result.actual_account_name == result.account_name:
        return ""
    return f"（实际：{result.actual_account_name}）"


def _parse_deadline(deadline_text: str) -> datetime | None:
    value = deadline_text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
