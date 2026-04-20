from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass
from pathlib import Path

from desktop_py.core.fetcher_support import FetchError


@dataclass
class GroupRuntime:
    group_key: str
    sync_manager: object
    playwright: object
    browser: object | None
    context: object
    page: object
    profile_dir: str
    state_path: Path | None
    persist_state: bool
    valid: bool = True
    busy: bool = False
    current_account_name: str = ""
    home_ready: bool = False
    last_error: str = ""


_RUNTIME_LOCK = threading.RLock()
_RUNTIME_CONDITION = threading.Condition(_RUNTIME_LOCK)
_GROUP_RUNTIMES: dict[str, GroupRuntime] = {}


def runtime_group_key(account, profile_dir: str) -> str:
    return profile_dir.strip() or account.state_path


def _close_runtime(runtime: GroupRuntime) -> None:
    close_errors: list[Exception] = []
    runtime.valid = False
    runtime.busy = False
    try:
        if runtime.persist_state and runtime.state_path is not None:
            runtime.context.storage_state(path=str(runtime.state_path), indexed_db=True)
    except Exception as exc:
        close_errors.append(exc)
    try:
        runtime.page.close()
    except Exception as exc:
        close_errors.append(exc)
    try:
        runtime.context.close()
    except Exception as exc:
        close_errors.append(exc)
    if runtime.browser is not None:
        try:
            runtime.browser.close()
        except Exception as exc:
            close_errors.append(exc)
    try:
        runtime.sync_manager.__exit__(None, None, None)
    except Exception as exc:
        close_errors.append(exc)
    if close_errors:
        raise close_errors[0]


def _create_runtime(
    account,
    *,
    headless: bool,
    profile_dir: str,
    sync_playwright_fn,
    create_browser_context_fn,
) -> GroupRuntime:
    sync_manager = sync_playwright_fn()
    playwright = sync_manager.__enter__()
    try:
        browser, context = create_browser_context_fn(playwright, account, headless, profile_dir)
        page = context.new_page()
        state_path = Path(account.state_path) if profile_dir.strip() else None
        runtime = GroupRuntime(
            group_key=runtime_group_key(account, profile_dir),
            sync_manager=sync_manager,
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            profile_dir=profile_dir,
            state_path=state_path,
            persist_state=bool(profile_dir.strip()),
        )
        try:
            setattr(page, "_current_account_name_cache", "")
        except Exception:
            pass
        return runtime
    except Exception:
        try:
            sync_manager.__exit__(None, None, None)
        except Exception:
            pass
        raise


def acquire_group_runtime(
    account,
    *,
    headless: bool,
    profile_dir: str,
    sync_playwright_fn,
    create_browser_context_fn,
    logger: callable | None = None,
    is_cancelled: callable | None = None,
) -> GroupRuntime:
    group_key = runtime_group_key(account, profile_dir)
    while True:
        if is_cancelled is not None and is_cancelled():
            raise FetchError("任务已取消")
        with _RUNTIME_CONDITION:
            runtime = _GROUP_RUNTIMES.get(group_key)
            if runtime is None:
                runtime = _create_runtime(
                    account,
                    headless=headless,
                    profile_dir=profile_dir,
                    sync_playwright_fn=sync_playwright_fn,
                    create_browser_context_fn=create_browser_context_fn,
                )
                runtime.busy = True
                _GROUP_RUNTIMES[group_key] = runtime
                return runtime
            if not runtime.valid:
                _GROUP_RUNTIMES.pop(group_key, None)
                continue
            if not runtime.busy:
                runtime.busy = True
                return runtime
            _log(logger, f"组级运行时忙碌，等待释放：{group_key}")
            _RUNTIME_CONDITION.wait(timeout=0.2)


def release_group_runtime(runtime: GroupRuntime) -> None:
    with _RUNTIME_CONDITION:
        runtime.busy = False
        _RUNTIME_CONDITION.notify_all()


def invalidate_group_runtime(runtime: GroupRuntime, message: str = "") -> None:
    with _RUNTIME_CONDITION:
        current = _GROUP_RUNTIMES.get(runtime.group_key)
        if current is runtime:
            _GROUP_RUNTIMES.pop(runtime.group_key, None)
        runtime.last_error = message.strip()
        try:
            _close_runtime(runtime)
        finally:
            _RUNTIME_CONDITION.notify_all()


def close_all_group_runtimes() -> None:
    with _RUNTIME_CONDITION:
        runtimes = list(_GROUP_RUNTIMES.values())
        _GROUP_RUNTIMES.clear()
    for runtime in runtimes:
        try:
            _close_runtime(runtime)
        except Exception:
            continue


def runtime_current_account_name(runtime: GroupRuntime) -> str:
    try:
        cached = str(getattr(runtime.page, "_current_account_name_cache", "") or "").strip()
    except Exception:
        cached = ""
    return cached or runtime.current_account_name.strip()


def update_runtime_current_account_name(runtime: GroupRuntime, account_name: str) -> None:
    runtime.current_account_name = account_name.strip()
    try:
        setattr(runtime.page, "_current_account_name_cache", runtime.current_account_name)
    except Exception:
        pass


def should_invalidate_runtime(exc: Exception) -> bool:
    message = str(exc).lower()
    fatal_tokens = (
        "has been closed",
        "target page, context or browser has been closed",
        "browser closed",
        "context closed",
        "page closed",
        "connection closed",
    )
    return any(token in message for token in fatal_tokens)


def _log(logger: callable | None, message: str) -> None:
    if logger:
        logger(message)


atexit.register(close_all_group_runtimes)
