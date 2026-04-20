from __future__ import annotations

from pathlib import Path

from desktop_py.core.store import write_account_output_json, write_account_output_text


def write_fetch_artifacts(
    account_name: str, *, page_html: str, frame_html: str, frame_text: str, captures: list
) -> None:
    write_account_output_text(account_name, "page.html", page_html)
    write_account_output_text(account_name, "iframe.html", frame_html)
    write_account_output_text(account_name, "iframe.txt", frame_text)
    write_account_output_json(account_name, "responses.json", captures)


def persist_storage_state(context, state_path: str) -> None:
    target = Path(state_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(target), indexed_db=True)
