import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import desktop_py_cli
from desktop_py.core.models import AccountConfig, AppSettings, FetchResult


class CliTestCase(unittest.TestCase):
    def test_login_uses_shared_profile_flow_when_profile_dir_configured(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True)
        settings = AppSettings(login_wait_seconds=45, browser_profile_dir="C:/shared/profile")

        with (
            patch("desktop_py_cli.load_accounts", return_value=[account]),
            patch("desktop_py_cli.load_settings", return_value=settings),
            patch("desktop_py_cli.save_login_state_with_profile") as mock_login_with_profile,
            patch("desktop_py_cli.save_login_state") as mock_login,
            patch("sys.argv", ["desktop_py_cli.py", "login", "--account", "主账号"]),
        ):
            result = desktop_py_cli.main()

        self.assertEqual(result, 0)
        mock_login_with_profile.assert_called_once_with(account, 45, "C:/shared/profile", print)
        mock_login.assert_not_called()

    def test_fetch_all_skips_entry_account(self):
        accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False, enabled=False),
        ]
        captured = io.StringIO()
        calls: list[str] = []

        def fake_fetch(account, *_args, **_kwargs):
            calls.append(account.name)
            return FetchResult(account_name=account.name, ok=True)

        with (
            patch("desktop_py_cli.load_accounts", return_value=accounts),
            patch("desktop_py_cli.load_settings", return_value=AppSettings(headless_fetch=True)),
            patch("desktop_py_cli.fetch_account", side_effect=fake_fetch),
            patch("sys.argv", ["desktop_py_cli.py", "fetch-all"]),
            redirect_stdout(captured),
        ):
            result = desktop_py_cli.main()

        self.assertEqual(result, 0)
        self.assertEqual(calls, ["导入账号A"])
        self.assertEqual(json.loads(captured.getvalue())[0]["account_name"], "导入账号A")

    def test_notify_skips_entry_account(self):
        accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        calls: list[str] = []

        def fake_fetch(account, *_args, **_kwargs):
            calls.append(account.name)
            return FetchResult(account_name=account.name, ok=True, deadline_text="2026-04-20 09:00:00")

        with (
            patch("desktop_py_cli.load_accounts", return_value=accounts),
            patch("desktop_py_cli.load_settings", return_value=AppSettings(headless_fetch=True, feishu_webhook="hook")),
            patch("desktop_py_cli.fetch_account", side_effect=fake_fetch),
            patch("desktop_py_cli.send_feishu_text") as mock_send,
            patch("sys.argv", ["desktop_py_cli.py", "notify"]),
        ):
            result = desktop_py_cli.main()

        self.assertEqual(result, 0)
        self.assertEqual(calls, ["导入账号A"])
        mock_send.assert_called_once()

    def test_notify_continues_when_one_account_fetch_fails(self):
        accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        captured = io.StringIO()

        def fake_fetch(account, *_args, **_kwargs):
            if account.name == "导入账号A":
                raise RuntimeError("抓取超时")
            return FetchResult(account_name=account.name, ok=True, deadline_text="2026-04-20 09:00:00")

        with (
            patch("desktop_py_cli.load_accounts", return_value=accounts),
            patch("desktop_py_cli.load_settings", return_value=AppSettings(headless_fetch=True, feishu_webhook="hook")),
            patch("desktop_py_cli.fetch_account", side_effect=fake_fetch),
            patch("desktop_py_cli.send_feishu_text") as mock_send,
            patch("sys.argv", ["desktop_py_cli.py", "notify"]),
            redirect_stdout(captured),
        ):
            result = desktop_py_cli.main()

        self.assertEqual(result, 0)
        mock_send.assert_called_once()
        self.assertIn("飞书消息已发送", captured.getvalue())
        self.assertIn("导入账号A：抓取超时", captured.getvalue())
        sent_summary = mock_send.call_args.args[1]
        self.assertIn("导入账号B", sent_summary)
        self.assertNotIn("导入账号A", sent_summary)


if __name__ == "__main__":
    unittest.main()
