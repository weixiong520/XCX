from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, cast

from desktop_py.core.models import AccountConfig, AppSettings, FetchResult

APP_NAME = "小程序工具"
SHARED_BROWSER_PROFILE_DIR_NAME = "browser_profile"
BROWSER_PROFILE_LOCK_FILES = (
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "LOCK",
    "lockfile",
)


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        if os.access(executable_dir, os.W_OK):
            return executable_dir
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return Path(local_appdata).expanduser() / APP_NAME
        return executable_dir
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = runtime_root()
DATA_DIR = PROJECT_ROOT / "data"
STORAGE_DIR = PROJECT_ROOT / "storage"
PY_OUTPUT_DIR = PROJECT_ROOT / "output" / "desktop_py"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_text_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_path).replace(path)
    except Exception:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def validate_shared_browser_profile_dir(profile_dir: str) -> str:
    value = profile_dir.strip()
    if not value:
        return ""

    path = Path(value).expanduser()
    if not path.exists():
        raise ValueError("共享浏览器资料目录不存在，请选择已存在的目录。")
    if not path.is_dir():
        raise ValueError("共享浏览器资料目录必须是文件夹。")

    resolved = path.resolve()
    if _looks_like_default_browser_profile_dir(resolved):
        raise ValueError("共享浏览器资料目录不能直接指向 Chrome 或 Edge 的默认用户资料目录，请改用专用自动化目录。")
    if _has_browser_lock_markers(resolved):
        raise ValueError("共享浏览器资料目录当前疑似正被浏览器占用，请先关闭相关浏览器后再使用。")
    return str(resolved)


def prepare_shared_browser_profile_dir(parent_dir: str) -> str:
    value = parent_dir.strip()
    if not value:
        return ""

    parent = Path(value).expanduser()
    if parent.exists() and not parent.is_dir():
        raise ValueError("共享浏览器资料父目录必须是文件夹。")

    target = parent if parent.name == SHARED_BROWSER_PROFILE_DIR_NAME else parent / SHARED_BROWSER_PROFILE_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return validate_shared_browser_profile_dir(str(target))


def _looks_like_default_browser_profile_dir(path: Path) -> bool:
    name = path.name.lower()
    parent_name = path.parent.name.lower()
    if name == "user data" and (path / "Local State").exists():
        return True
    if parent_name == "user data" and (path / "Preferences").exists():
        return True
    return False


def _has_browser_lock_markers(path: Path) -> bool:
    if any((path / lock_name).exists() for lock_name in BROWSER_PROFILE_LOCK_FILES):
        return True
    parent = path.parent
    if parent.name.lower() == "user data":
        return any((parent / lock_name).exists() for lock_name in BROWSER_PROFILE_LOCK_FILES)
    return False


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    PY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS_FILE.exists():
        _write_text_atomic(ACCOUNTS_FILE, "[]\n")
    if not SETTINGS_FILE.exists():
        _write_text_atomic(SETTINGS_FILE, json.dumps(AppSettings().to_dict(), ensure_ascii=False, indent=2) + "\n")


def load_accounts() -> list[AccountConfig]:
    ensure_runtime_dirs()
    data = cast(list[dict[str, Any]], read_json_file(ACCOUNTS_FILE))
    return [AccountConfig(**item) for item in data]


def save_accounts(accounts: list[AccountConfig]) -> None:
    ensure_runtime_dirs()
    _write_text_atomic(
        ACCOUNTS_FILE, json.dumps([account.to_dict() for account in accounts], ensure_ascii=False, indent=2) + "\n"
    )


def load_settings() -> AppSettings:
    ensure_runtime_dirs()
    raw = cast(dict[str, Any], read_json_file(SETTINGS_FILE))
    allowed = {item.name for item in fields(AppSettings)}
    filtered = {key: value for key, value in raw.items() if key in allowed}
    return AppSettings(**filtered)


def save_settings(settings: AppSettings) -> None:
    ensure_runtime_dirs()
    _write_text_atomic(SETTINGS_FILE, json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n")


def account_state_path(name: str) -> str:
    safe_name = "".join(char if char.isalnum() else "_" for char in name).strip("_") or "account"
    return str(STORAGE_DIR / f"{safe_name}.json")


def default_state_path(accounts: list[AccountConfig]) -> str:
    for account in accounts:
        if account.state_path:
            return account.state_path
    return str(STORAGE_DIR / "shared_accounts.json")


def account_output_dir(account_name: str) -> Path:
    safe_name = "".join(char if char.isalnum() else "_" for char in account_name).strip("_") or "account"
    target = PY_OUTPUT_DIR / safe_name
    target.mkdir(parents=True, exist_ok=True)
    return target


def account_output_file(account_name: str, filename: str) -> Path:
    return account_output_dir(account_name) / filename


def write_account_output_text(account_name: str, filename: str, content: str) -> None:
    _write_text_atomic(account_output_file(account_name, filename), content)


def write_account_output_json(account_name: str, filename: str, payload: object) -> None:
    _write_text_atomic(
        account_output_file(account_name, filename), json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )


def write_fetch_result(account_name: str, result: FetchResult, extra: dict | None = None) -> None:
    payload = result.to_dict()
    if extra:
        payload["extra"] = extra
    write_account_output_json(account_name, "result.json", payload)
