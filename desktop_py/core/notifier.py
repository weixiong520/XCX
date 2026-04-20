from __future__ import annotations

from datetime import datetime

import requests

from desktop_py.core.models import FetchResult


def send_feishu_text(webhook: str, content: str) -> None:
    if not webhook.strip():
        raise ValueError("飞书机器人地址不能为空。")
    response = requests.post(webhook, json={"msg_type": "text", "content": {"text": content}}, timeout=20)
    response.raise_for_status()


def build_summary(results: list[FetchResult]) -> str:
    pending_results = sorted(
        [result for result in results if result.account_name.strip() and result.ok and result.deadline_text.strip()],
        key=lambda item: _parse_deadline(item.deadline_text) or datetime.max,
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
    return f"{index}. {result.account_name}：截止 {result.deadline_text}{_actual_suffix(result)}"


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
