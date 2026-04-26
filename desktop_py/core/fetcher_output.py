from __future__ import annotations

import re

from desktop_py.core.fetcher_support import persist_storage_state as persist_storage_state_impl
from desktop_py.core.store import write_account_output_json, write_account_output_text


def _redact_output_value(value):
    if isinstance(value, dict):
        return {key: _redact_output_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_output_value(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(token=)([^&\s]+)", r"\1***", value, flags=re.IGNORECASE)
    return value


def write_fetch_artifacts(
    account_name: str,
    *,
    page_html: str = "",
    frame_html: str = "",
    frame_text: str = "",
    captures: list | None = None,
) -> None:
    if page_html:
        write_account_output_text(account_name, "page.html", page_html)
    if frame_html:
        write_account_output_text(account_name, "iframe.html", frame_html)
    if frame_text:
        write_account_output_text(account_name, "iframe.txt", frame_text)
    if captures:
        write_account_output_json(account_name, "responses.json", _redact_output_value(captures))


def persist_storage_state(
    context,
    state_path: str,
    *,
    page=None,
    logger: callable | None = None,
    log_fn=None,
    wait_or_cancel_fn=None,
    is_cancelled=None,
) -> None:
    kwargs = {
        "page": page,
        "logger": logger,
        "log_fn": log_fn,
        "is_cancelled": is_cancelled,
    }
    if wait_or_cancel_fn is not None:
        kwargs["wait_or_cancel_fn"] = wait_or_cancel_fn
    persist_storage_state_impl(context, state_path, **kwargs)
