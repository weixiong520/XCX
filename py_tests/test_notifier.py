import unittest

from desktop_py.core.models import FetchResult
from desktop_py.core.notifier import build_summary


class NotifierTestCase(unittest.TestCase):
    def test_summary_contains_actual_account_name(self):
        text = build_summary(
            [
                FetchResult(
                    account_name="配置账号A",
                    actual_account_name="实际账号B",
                    ok=True,
                    deadline_text="2026-04-20 11:42:31",
                    note="已完成详情页抓取。",
                )
            ]
        )
        self.assertIn("配置账号A", text)
        self.assertIn("实际账号B", text)
        self.assertIn("未成年申请截止 2026-04-20 11:42:31", text)

    def test_summary_only_pushes_pending_accounts_and_sorts_deadlines(self):
        text = build_summary(
            [
                FetchResult(account_name="无待处理账号", ok=True, note="当前账号无待处理申请。"),
                FetchResult(account_name="较远账号", ok=True, deadline_text="2026-04-22 10:00:00"),
                FetchResult(account_name="失败账号", ok=False, note="页面未出现业务 iframe，可能是链接失效。"),
                FetchResult(account_name="较近账号", ok=True, deadline_text="2026-04-20 09:00:00"),
            ]
        )

        self.assertIn("待处理账号：2 个", text)
        self.assertLess(text.index("较近账号"), text.index("较远账号"))
        self.assertNotIn("无待处理账号", text)
        self.assertNotIn("失败账号", text)

    def test_summary_appends_notification_summary_to_pending_line(self):
        text = build_summary(
            [
                FetchResult(
                    account_name="账号A",
                    ok=True,
                    deadline_text="2026-04-24 22:48:57",
                    note="已完成详情页抓取。；通知中心未读消息 1 条：小程序微信认证年审通知",
                ),
                FetchResult(
                    account_name="账号B",
                    ok=True,
                    deadline_text="2026-04-28 21:39:08",
                    note="已完成详情页抓取。；通知中心未读消息 1 条：小程序微信认证年审通知",
                ),
            ]
        )

        self.assertIn(
            "1. 账号A：未成年申请截止 2026-04-24 22:48:57；通知中心未读消息 1 条：小程序微信认证年审通知",
            text,
        )
        self.assertIn(
            "2. 账号B：未成年申请截止 2026-04-28 21:39:08；通知中心未读消息 1 条：小程序微信认证年审通知",
            text,
        )

    def test_summary_includes_notification_only_accounts_after_deadline_accounts(self):
        text = build_summary(
            [
                FetchResult(
                    account_name="只有通知账号",
                    ok=True,
                    note="通知中心未读消息 1 条：小程序微信认证年审通知",
                ),
                FetchResult(
                    account_name="退款账号",
                    ok=True,
                    deadline_text="2026-04-20 09:00:00",
                    note="已完成详情页抓取。",
                ),
            ]
        )

        self.assertIn("待处理账号：2 个", text)
        self.assertIn("1. 退款账号：未成年申请截止 2026-04-20 09:00:00", text)
        self.assertIn("2. 只有通知账号：通知中心未读消息 1 条：小程序微信认证年审通知", text)
        self.assertLess(text.index("退款账号"), text.index("只有通知账号"))

    def test_summary_shows_empty_pending_message(self):
        text = build_summary(
            [
                FetchResult(account_name="无待处理账号", ok=True, note="当前账号无待处理申请。"),
                FetchResult(account_name="失败账号", ok=False, note="切换失败"),
            ]
        )

        self.assertIn("待处理账号：0 个", text)
        self.assertIn("暂无待处理账号。", text)
        self.assertNotIn("1. 无待处理账号", text)
        self.assertNotIn("失败账号", text)


if __name__ == "__main__":
    unittest.main()
