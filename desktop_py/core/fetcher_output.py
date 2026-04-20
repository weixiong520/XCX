from __future__ import annotations

import json
from pathlib import Path


def write_fetch_artifacts(output_dir: Path, *, page_html: str, frame_html: str, frame_text: str, captures: list) -> None:
    (output_dir / "page.html").write_text(page_html, encoding="utf-8")
    (output_dir / "iframe.html").write_text(frame_html, encoding="utf-8")
    (output_dir / "iframe.txt").write_text(frame_text, encoding="utf-8")
    (output_dir / "responses.json").write_text(
        json.dumps(captures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def persist_storage_state(context, state_path: str) -> None:
    target = Path(state_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(target), indexed_db=True)
