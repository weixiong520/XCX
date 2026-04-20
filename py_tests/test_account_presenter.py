import unittest
from datetime import datetime

from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.ui.account_presenter import (
    apply_batch_fetch_results,
    apply_fetch_result,
    deadline_tooltip_text,
    display_account_name,
    display_deadline_text,
    display_result_text,
    next_auto_fetch_push_interval_ms,
    parse_deadline_for_sort,
    sort_accounts_for_display,
)


class AccountPresenterTestCase(unittest.TestCase):
    def test_apply_fetch_result_updates_account_and_returns_actual_name(self):
        account = AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False)
        result = FetchResult(
            account_name="导入账号A",
            ok=True,
            actual_account_name="萌萌连消",
            deadline_text="2026-04-18 10:30:00",
            note="已完成详情页抓取。",
            page_url="https://example.com/detail",
        )

        current_main_account_name = apply_fetch_result(account, result)

        self.assertEqual(current_main_account_name, "萌萌连消")
        self.assertEqual(account.last_status, "抓取成功")
        self.assertEqual(account.last_deadline, "2026-04-18 10:30:00")
        self.assertEqual(account.feedback_url, "https://example.com/detail")
        self.assertIn("当前实际账号：萌萌连消", account.last_note)

    def test_apply_batch_fetch_results_returns_latest_actual_name(self):
        accounts = [
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False),
        ]
        results = [
            FetchResult(
                account_name="导入账号A", ok=True, actual_account_name="账号甲", page_url="https://example.com/a"
            ),
            FetchResult(
                account_name="导入账号B", ok=True, actual_account_name="账号乙", page_url="https://example.com/b"
            ),
        ]

        latest_actual_account_name = apply_batch_fetch_results(accounts, results)

        self.assertEqual(latest_actual_account_name, "账号乙")
        self.assertEqual(accounts[0].feedback_url, "https://example.com/a")
        self.assertEqual(accounts[1].feedback_url, "https://example.com/b")

    def test_display_helpers_keep_existing_copy(self):
        account = AccountConfig(
            name="导入账号A",
            state_path="storage/shared.json",
            is_entry_account=False,
            last_status="抓取失败",
            last_note="页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。",
        )

        self.assertEqual(display_deadline_text(account), "无页面")
        self.assertEqual(deadline_tooltip_text(account), account.last_note)
        self.assertEqual(display_result_text(account), "失败")

    def test_apply_fetch_result_treats_no_deadline_note_as_success(self):
        account = AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False)
        result = FetchResult(
            account_name="导入账号A",
            ok=False,
            note="未在详情页文本中提取到处理截止时间。",
        )

        apply_fetch_result(account, result)

        self.assertEqual(account.last_status, "抓取成功")
        self.assertEqual(display_deadline_text(account), "无待处理")
        self.assertEqual(display_result_text(account), "完成")

    def test_apply_fetch_result_treats_no_business_page_note_as_success(self):
        account = AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False)
        result = FetchResult(
            account_name="导入账号A",
            ok=False,
            note="页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。",
        )

        apply_fetch_result(account, result)

        self.assertEqual(account.last_status, "抓取成功")
        self.assertEqual(display_deadline_text(account), "无页面")
        self.assertEqual(display_result_text(account), "完成")

    def test_next_auto_fetch_push_interval_ms_matches_existing_schedule(self):
        self.assertEqual(
            next_auto_fetch_push_interval_ms(datetime(2026, 4, 18, 8, 30, 0)),
            30 * 60 * 1000,
        )
        self.assertEqual(
            next_auto_fetch_push_interval_ms(datetime(2026, 4, 18, 9, 30, 0)),
            int(23.5 * 60 * 60 * 1000),
        )

    def test_display_account_name_formats_entry_account_state(self):
        entry_account = AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True)
        imported_account = AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False)

        self.assertEqual(display_account_name(entry_account, "七色花消消乐"), "主账号状态：七色花消消乐")
        self.assertEqual(display_account_name(entry_account, ""), "主账号状态：未记录")
        self.assertEqual(display_account_name(imported_account, "七色花消消乐"), "导入账号")

    def test_sort_accounts_for_display_keeps_entry_first_and_deadlines_nearest_first(self):
        accounts = [
            AccountConfig(
                name="无截止账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取成功"
            ),
            AccountConfig(
                name="较远截止账号",
                state_path="storage/shared.json",
                is_entry_account=False,
                last_status="抓取成功",
                last_deadline="2026-04-25 12:00:00",
            ),
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(
                name="较近截止账号",
                state_path="storage/shared.json",
                is_entry_account=False,
                last_status="抓取成功",
                last_deadline="2026-04-19 09:00:00",
            ),
        ]

        sorted_accounts = sort_accounts_for_display(accounts)

        self.assertEqual(
            [account.name for account in sorted_accounts],
            ["主账号", "较近截止账号", "较远截止账号", "无截止账号"],
        )

    def test_parse_deadline_for_sort_supports_known_formats(self):
        self.assertEqual(parse_deadline_for_sort("2026-04-18").strftime("%Y-%m-%d"), "2026-04-18")
        self.assertEqual(parse_deadline_for_sort("2026-04-18 08:30").strftime("%Y-%m-%d %H:%M"), "2026-04-18 08:30")


if __name__ == "__main__":
    unittest.main()
