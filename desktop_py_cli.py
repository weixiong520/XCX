from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from desktop_py.core.fetcher import fetch_account, save_login_state, save_login_state_with_profile
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.notifier import build_summary, send_feishu_text
from desktop_py.core.session_links import propagate_account_feedback_url, refresh_account_feedback_url
from desktop_py.core.store import load_accounts, load_settings, save_accounts


def enabled_imported_accounts(accounts: Sequence[AccountConfig]) -> list[AccountConfig]:
    return [account for account in accounts if account.enabled and not account.is_entry_account]


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
        if settings.browser_profile_dir.strip():
            save_login_state_with_profile(account, settings.login_wait_seconds, settings.browser_profile_dir, print)
        else:
            save_login_state(account, settings.login_wait_seconds, print)
        propagate_account_feedback_url(accounts, account)
        save_accounts(accounts)
        return 0

    if args.command == "fetch-all":
        fetch_results: list[dict[str, object]] = []
        changed = False
        for account in enabled_imported_accounts(accounts):
            try:
                result = fetch_account(account, 0, settings.headless_fetch, print, settings.browser_profile_dir)
                fetch_results.append(result.to_dict())
                if refresh_account_feedback_url(account, result.page_url):
                    changed = True
                if propagate_account_feedback_url(accounts, account):
                    changed = True
            except Exception as exc:
                fetch_results.append({"account_name": account.name, "ok": False, "note": str(exc)})
        if changed:
            save_accounts(accounts)
        print(json.dumps(fetch_results, ensure_ascii=False, indent=2))
        return 0

    if args.command == "notify":
        results: list[FetchResult] = []
        failed_accounts: list[str] = []
        changed = False
        for account in enabled_imported_accounts(accounts):
            try:
                result = fetch_account(account, 0, settings.headless_fetch, print, settings.browser_profile_dir)
                results.append(result)
                if refresh_account_feedback_url(account, result.page_url):
                    changed = True
                if propagate_account_feedback_url(accounts, account):
                    changed = True
            except Exception as exc:
                failed_accounts.append(f"{account.name}：{exc}")
                results.append(FetchResult(account_name=account.name, ok=False, note=str(exc)))
        if changed:
            save_accounts(accounts)

        summary = build_summary(results)
        send_feishu_text(settings.feishu_webhook, summary)
        print("飞书消息已发送")
        if failed_accounts:
            print("以下账号抓取失败，但已完成其余账号汇总：")
            for item in failed_accounts:
                print(f"- {item}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
