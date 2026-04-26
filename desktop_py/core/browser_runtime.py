from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import playwright

from desktop_py.core.store import runtime_root

APP_NAME = "小程序工具"
DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS = "120000"


def browsers_root() -> Path:
    return runtime_root() / "ms-playwright"


def configure_playwright_environment() -> Path:
    target = browsers_root()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(target)
    return target


def browser_archive_root() -> Path:
    if getattr(sys, "frozen", False):
        internal_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent / "_internal"))
        return internal_root / "playwright" / "driver" / "package"
    return Path(playwright.__file__).resolve().parent / "driver" / "package"


def required_browser_directories() -> list[str]:
    browsers_json = browser_archive_root() / "browsers.json"
    payload = json.loads(browsers_json.read_text(encoding="utf-8"))
    required_names = {"chromium", "chromium-headless-shell", "ffmpeg"}
    return [
        f"{item['name'].replace('-', '_')}-{item['revision']}"
        for item in payload["browsers"]
        if item["name"] in required_names
    ]


def playwright_browsers_ready() -> bool:
    root = configure_playwright_environment()
    try:
        required_directories = required_browser_directories()
    except OSError, json.JSONDecodeError, KeyError, TypeError:
        return False
    return all(_browser_directory_ready(root / name) for name in required_directories)


def _browser_directory_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    candidates = _browser_executable_candidates(path)
    return bool(candidates) and any(candidate.exists() for candidate in candidates)


def _browser_executable_candidates(path: Path) -> list[Path]:
    name = path.name
    if name.startswith("chromium_headless_shell-"):
        return [
            path / "chrome-win" / "headless_shell.exe",
            path / "chrome-linux" / "headless_shell",
            path / "chrome-mac" / "headless_shell",
        ]
    if name.startswith("chromium-"):
        return [
            path / "chrome-win" / "chrome.exe",
            path / "chrome-linux" / "chrome",
            path / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
        ]
    if name.startswith("ffmpeg-"):
        return [
            path / "ffmpeg-win64.exe",
            path / "ffmpeg-linux",
            path / "ffmpeg-mac",
        ]
    return []


def playwright_install_command() -> list[str]:
    if getattr(sys, "frozen", False):
        package_root = browser_archive_root()
        return [
            str(package_root.parent / "node.exe"),
            str(package_root / "cli.js"),
            "install",
            "chromium",
        ]
    return [sys.executable, "-m", "playwright", "install", "chromium"]


def playwright_install_environment(target: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(target)
    env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS)
    return env


def _run_playwright_install(env: dict[str, str], logger: Callable[[str], None] | None = None) -> tuple[bool, str]:
    process = subprocess.Popen(
        playwright_install_command(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        content = line.strip()
        if not content:
            continue
        lines.append(content)
        if logger is not None:
            logger(content)

    return process.wait() == 0, "\n".join(lines[-40:])


def install_playwright_browsers(logger: Callable[[str], None] | None = None) -> tuple[bool, str]:
    target = configure_playwright_environment()
    target.mkdir(parents=True, exist_ok=True)
    env = playwright_install_environment(target)
    return _run_playwright_install(env, logger)
