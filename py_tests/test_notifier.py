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
