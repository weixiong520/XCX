from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WATCH_PATHS = [
    ROOT / "desktop_main.py",
    ROOT / "desktop_py",
]
IGNORE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
SUFFIXES = {".py"}
POLL_INTERVAL = 0.6
DEV_LOCK_PORT = 47231


def iter_watch_files() -> list[Path]:
    files: list[Path] = []
    for target in WATCH_PATHS:
        if target.is_file():
            files.append(target)
            continue
        if not target.exists():
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORE_PARTS for part in path.parts):
                continue
            if path.suffix in SUFFIXES:
                files.append(path)
    return sorted(files)


def snapshot_files() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    for path in iter_watch_files():
        try:
            snapshot[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def find_changes(previous: dict[Path, int], current: dict[Path, int]) -> list[Path]:
    changed: list[Path] = []
    all_paths = set(previous) | set(current)
    for path in sorted(all_paths):
        if previous.get(path) != current.get(path):
            changed.append(path)
    return changed


def acquire_dev_lock() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", DEV_LOCK_PORT))
    except OSError as exc:
        sock.close()
        raise RuntimeError("开发模式已在运行，请先关闭现有开发模式窗口后再启动。") from exc
    sock.listen(1)
    return sock


def list_python_processes() -> list[dict[str, object]]:
    if os.name != "nt":
        return []
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' } | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    payload = completed.stdout.strip()
    if completed.returncode != 0 or not payload:
        return []
    parsed = json.loads(payload)
    if isinstance(parsed, dict):
        return [parsed]
    return parsed if isinstance(parsed, list) else []


def find_existing_app_pids(processes: list[dict[str, object]], current_pid: int) -> list[int]:
    pids: list[int] = []
    for item in processes:
        pid = int(item.get("ProcessId") or 0)
        command_line = str(item.get("CommandLine") or "").lower()
        if pid <= 0 or pid == current_pid:
            continue
        if "desktop_main.py" in command_line:
            pids.append(pid)
    return pids


def stop_existing_app_instances(current_pid: int) -> None:
    for pid in find_existing_app_pids(list_python_processes(), current_pid):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )


def spawn_app() -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "desktop_main.py"], cwd=ROOT)


def stop_app(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    try:
        dev_lock = acquire_dev_lock()
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print("开发模式已启动，检测到 Python 文件变化后会自动重启桌面应用。")
    stop_existing_app_instances(os.getpid())
    process = spawn_app()
    previous = snapshot_files()

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            current = snapshot_files()
            changed = find_changes(previous, current)
            if not changed:
                if process.poll() is not None:
                    print("应用已退出，正在重新启动。")
                    stop_existing_app_instances(os.getpid())
                    process = spawn_app()
                continue

            previous = current
            changed_display = ", ".join(str(path.relative_to(ROOT)) for path in changed[:3])
            if len(changed) > 3:
                changed_display += " ..."
            print(f"检测到文件变化：{changed_display}")
            stop_app(process)
            stop_existing_app_instances(os.getpid())
            process = spawn_app()
    except KeyboardInterrupt:
        print("开发模式已停止。")
    finally:
        stop_app(process)
        dev_lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
