from __future__ import annotations

import argparse
import json

from desktop_py.core.fetcher import fetch_account, save_login_state
from desktop_py.core.notifier import build_summary, send_feishu_text
from desktop_py.core.store import load_accounts, load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="桌面版配套命令行工具")
    parser.add_argument("command", choices=["login", "fetch-all", "notify"])
    parser.add_argument("--account", help="指定账号名称")
    args = parser.parse_args()

    accounts = load_accounts()
    settings = load_settings()

    if args.command == "login":
        account = next((item for item in accounts if item.name == args.account), None)
        if not account:
            raise SystemExit("未找到指定账号。")
        save_login_state(account, settings.login_wait_seconds, print)
        return 0

    if args.command == "fetch-all":
        results = []
        for account in accounts:
            if not account.enabled:
                continue
            try:
                results.append(fetch_account(account, 0, settings.headless_fetch, print).to_dict())
            except Exception as exc:
                results.append({"account_name": account.name, "ok": False, "note": str(exc)})
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.command == "notify":
        summary = build_summary([
            fetch_account(account, 0, settings.headless_fetch, print)
            for account in accounts if account.enabled
        ])
        send_feishu_text(settings.feishu_webhook, summary)
        print("飞书消息已发送")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
