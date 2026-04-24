import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from desktop_py.core.fetcher import (
    extract_current_account_name,
    fetch_account,
    fetch_accounts_batch,
    fetch_switchable_accounts,
    renew_account_state,
    save_login_state,
    save_login_state_with_profile,
    validate_account_state,
    wait_for_current_account_name,
    wait_for_switch_account_items,
)
from desktop_py.core.fetcher_page_strategy import register_response_capture
from desktop_py.core.fetcher_pipeline import fetch_account_in_page_impl
from desktop_py.core.fetcher_pipeline import resolve_bootstrap_url_impl as resolve_bootstrap_url
from desktop_py.core.fetcher_runtime import close_all_group_runtimes
from desktop_py.core.fetcher_support import (
    CancelledError,
    _capture_response_payload,
    _close_context_and_browser,
    _fallback_from_responses,
    build_feedback_url,
    business_iframe_selector,
    classify_refund_response_type,
    extract_response_token,
    is_login_timeout_page,
    recover_login_timeout_page,
    safe_page_content,
    wait_for_iframe_ready,
    wait_for_url_contains,
    wait_or_cancel,
)
from desktop_py.core.fetcher_switching import (
    find_switch_entry_impl as find_switch_entry,
)
from desktop_py.core.fetcher_switching import (
    prepare_switch_account_page_impl as prepare_switch_account_page,
)
from desktop_py.core.fetcher_switching import (
    should_retry_switch_from_home_impl as should_retry_switch_from_home,
)
from desktop_py.core.fetcher_switching import (
    should_switch_account_impl as should_switch_account,
)
from desktop_py.core.fetcher_switching import (
    should_switch_for_account_impl as should_switch_for_account,
)
from desktop_py.core.fetcher_switching import (
    wait_for_account_switch_stable_impl as wait_for_account_switch_stable,
)
from desktop_py.core.models import AccountConfig, FetchResult
from desktop_py.core.notification_page_strategy import (
    build_notification_summary,
    filter_target_unread_notifications,
)
from desktop_py.core.parser import extract_labeled_datetime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fetcher"


class FakeElementHandle:
    def __init__(self, frame):
        self._frame = frame

    def content_frame(self):
        return self._frame


class FakeFrame:
    def __init__(self, text: str = "", html: str = "", url: str = "https://example.com/frame"):
        self.url = url
        self._text = text
        self._html = html
        self.load_state_calls: list[tuple[str | None, int | None]] = []

    def wait_for_load_state(self, state=None, timeout=None):
        self.load_state_calls.append((state, timeout))

    def locator(self, selector):
        if selector == "body":
            return FakeLocator(count=1, text=self._text, html=self._html)
        return FakeLocator()


class FakeLocator:
    def __init__(
        self,
        count: int = 0,
        counts: list[int] | None = None,
        frame=None,
        text: str = "",
        html: str = "",
        click_cb=None,
    ):
        self._count = count
        self._counts = list(counts) if counts is not None else None
        self._frame = frame
        self._text = text
        self._html = html
        self._click_cb = click_cb
        self.first = self

    def count(self) -> int:
        if self._counts is not None:
            if len(self._counts) > 1:
                return self._counts.pop(0)
            return self._counts[0]
        return self._count

    def evaluate(self, _script):
        if self._click_cb is not None:
            self._click_cb()
        return None

    def click(self, timeout=None):
        if self._click_cb is not None:
            self._click_cb()
        return None

    def element_handle(self):
        if self._frame is None:
            return None
        return FakeElementHandle(self._frame)

    def text_content(self, timeout=None):
        return self._text

    def inner_html(self, timeout=None):
        return self._html


class FakePage:
    def __init__(self, locator_map=None, text_map=None):
        self.locator_map = locator_map or {}
        self.text_map = text_map or {}
        self.wait_calls: list[int] = []
        self.load_state_calls: list[tuple[str | None, int | None]] = []
        self.url = ""
        self._current_account_names: list[str] = []
        self._content_results: list[object] = []

    def locator(self, selector, **kwargs):
        key = (selector, kwargs.get("has_text"))
        return self.locator_map.get(key, FakeLocator())

    def get_by_text(self, text, exact=False):
        key = (text, exact)
        return self.text_map.get(key, FakeLocator())

    def wait_for_timeout(self, timeout):
        self.wait_calls.append(timeout)

    def wait_for_load_state(self, state=None, timeout=None):
        self.load_state_calls.append((state, timeout))
        return None

    def set_current_account_names(self, names: list[str]):
        self._current_account_names = list(names)

    def set_content_results(self, results: list[object]):
        self._content_results = list(results)

    def content(self):
        if self._content_results:
            result = self._content_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return ""


class FakeResponse:
    def __init__(
        self, text: str, content_type: str = "application/json", url: str = "https://example.com/api", status: int = 200
    ):
        self._text = text
        self.headers = {"content-type": content_type}
        self.url = url
        self.status = status

    def text(self):
        return self._text


class FixturePage:
    def __init__(self, html: str):
        self.html = html

    def locator(self, selector, **kwargs):
        has_text = kwargs.get("has_text")
        if selector == "div.menu_box_account_info_item[title='切换账号']":
            return FakeLocator(count=1 if 'title="切换账号"' in self.html else 0)
        if selector == ".menu_box_account_info_item":
            if has_text == "切换账号" and "切换账号" in self.html:
                return FakeLocator(count=1)
            return FakeLocator()
        if selector == "[title='切换账号']":
            return FakeLocator(count=1 if 'title="切换账号"' in self.html else 0)
        if selector == "#js_iframe":
            return FakeLocator(count=1 if 'id="js_iframe"' in self.html else 0)
        if selector == "iframe[src*='gameFeedback']":
            return FakeLocator(count=1 if "gameFeedback" in self.html else 0)
        return FakeLocator()

    def get_by_text(self, text, exact=False):
        if exact and text in self.html:
            return FakeLocator(count=1)
        return FakeLocator()


class FetcherTestCase(unittest.TestCase):
    def tearDown(self):
        close_all_group_runtimes()

    def read_fixture(self, name: str) -> str:
        return (FIXTURE_ROOT / name).read_text(encoding="utf-8")

    def test_build_feedback_url(self):
        url = build_feedback_url("https://mp.weixin.qq.com/wxamp/index/index?lang=zh_CN&token=2056634783")
        self.assertIn("plugin_uin=1010", url)
        self.assertIn("selected=2", url)
        self.assertIn("token=2056634783", url)

    def test_contract_fixture_switch_account_menu_matches_title_selector(self):
        page = FixturePage(self.read_fixture("switch_account_menu.html"))

        result = find_switch_entry(page)

        self.assertIsNotNone(result)
        self.assertEqual(result.count(), 1)

    def test_contract_fixture_reports_missing_switch_account_entry(self):
        page = FixturePage(self.read_fixture("no_switch_account_menu.html"))

        result = find_switch_entry(page)

        self.assertIsNone(result)

    def test_contract_fixture_extracts_current_account_name_from_page_html(self):
        page = FakePage()
        page.set_content_results([self.read_fixture("switch_account_menu.html")])

        with patch(
            "desktop_py.core.fetcher.safe_page_content", return_value=self.read_fixture("switch_account_menu.html")
        ):
            self.assertEqual(extract_current_account_name(page), "主账号")

    def test_contract_fixture_prefers_js_iframe_selector(self):
        page = FixturePage(self.read_fixture("feedback_page_iframe.html"))

        self.assertEqual(business_iframe_selector(page), "#js_iframe")

    def test_contract_fixture_reports_missing_business_iframe(self):
        page = FixturePage(self.read_fixture("no_feedback_iframe.html"))

        self.assertEqual(business_iframe_selector(page), "")

    def test_contract_fixture_extracts_deadline_from_detail_text(self):
        deadline = extract_labeled_datetime(self.read_fixture("detail_frame.txt"), "处理截止时间")

        self.assertEqual(deadline, "2026-04-20 18:00")

    def test_contract_fixture_returns_empty_when_detail_text_has_no_deadline(self):
        deadline = extract_labeled_datetime(self.read_fixture("detail_without_deadline.txt"), "处理截止时间")

        self.assertEqual(deadline, "")

    def test_contract_fixture_extracts_deadline_from_response_payload(self):
        payload = json.loads(self.read_fixture("refund_response.json"))

        deadline = _fallback_from_responses([payload])

        self.assertEqual(deadline, "2026-04-21 10:19:34")

    def test_contract_fixture_returns_empty_when_response_has_no_deadline(self):
        payload = json.loads(self.read_fixture("refund_response_without_deadline.json"))

        deadline = _fallback_from_responses([payload])

        self.assertEqual(deadline, "")

    def test_find_switch_entry_prefers_title_selector(self):
        title_locator = FakeLocator(count=1)
        fallback_locator = FakeLocator(count=1)
        page = FakePage(
            locator_map={
                ("div.menu_box_account_info_item[title='切换账号']", None): title_locator,
                (".menu_box_account_info_item", "切换账号"): fallback_locator,
            }
        )

        result = find_switch_entry(page)

        self.assertIs(result, title_locator)

    def test_find_switch_entry_falls_back_to_text_locator(self):
        text_locator = FakeLocator(count=1)
        page = FakePage(
            locator_map={
                ("div.menu_box_account_info_item[title='切换账号']", None): FakeLocator(),
                (".menu_box_account_info_item", "切换账号"): FakeLocator(),
                ("[title='切换账号']", None): FakeLocator(),
            },
            text_map={
                ("切换账号", True): text_locator,
            },
        )

        result = find_switch_entry(page)

        self.assertIs(result, text_locator)

    def test_find_switch_entry_returns_none_when_missing(self):
        page = FakePage()

        result = find_switch_entry(page)

        self.assertIsNone(result)

    def test_should_switch_account(self):
        self.assertFalse(should_switch_account("七色花消消乐", "七色花消消乐"))
        self.assertTrue(should_switch_account("主账号", "七色花消消乐"))
        self.assertTrue(should_switch_account("", "七色花消消乐"))

    def test_should_switch_for_entry_account(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True)

        self.assertFalse(should_switch_for_account(account, ""))
        self.assertFalse(should_switch_for_account(account, "七色花消消乐"))

    def test_should_switch_for_imported_account(self):
        account = AccountConfig(name="七色花消消乐", state_path="storage/shared.json", is_entry_account=False)

        self.assertFalse(should_switch_for_account(account, "七色花消消乐"))
        self.assertTrue(should_switch_for_account(account, "不灭轮回"))
        self.assertTrue(should_switch_for_account(account, ""))

    def test_should_retry_switch_from_home(self):
        self.assertTrue(
            should_retry_switch_from_home(
                "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=1",
                "https://mp.weixin.qq.com/",
                False,
            )
        )

    def test_resolve_bootstrap_url_uses_home_url_when_feedback_url_exists(self):
        account = AccountConfig(
            name="导入账号",
            state_path="storage/shared.json",
            is_entry_account=False,
            feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=old",
            home_url="https://mp.weixin.qq.com/",
        )

        self.assertEqual(resolve_bootstrap_url(account, Path("output/demo")), "https://mp.weixin.qq.com/")

    def test_resolve_bootstrap_url_ignores_stale_result_page_url(self):
        account = AccountConfig(
            name="导入账号",
            state_path="storage/shared.json",
            is_entry_account=False,
            home_url="https://mp.weixin.qq.com/",
        )
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "result.json").write_text(
                '{"page_url": "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=old"}',
                encoding="utf-8",
            )

            self.assertEqual(resolve_bootstrap_url(account, output_dir), "https://mp.weixin.qq.com/")
        self.assertFalse(
            should_retry_switch_from_home(
                "https://mp.weixin.qq.com/",
                "https://mp.weixin.qq.com/",
                False,
            )
        )
        self.assertFalse(
            should_retry_switch_from_home(
                "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=1",
                "https://mp.weixin.qq.com/",
                True,
            )
        )

    def test_wait_for_switch_account_items_retries_until_success(self):
        account_locator = FakeLocator(counts=[0, 0, 0, 0, 0, 0, 0, 0, 0, 2])
        close_locator = FakeLocator(count=1)
        page = FakePage(
            locator_map={
                (".switch_account_dialog .account_item", None): account_locator,
                (".switch_account_dialog .close_icon", None): close_locator,
                ("div.menu_box_account_info_item[title='切换账号']", None): FakeLocator(count=1),
            }
        )
        logs: list[str] = []

        with patch("desktop_py.core.fetcher.open_switch_account_dialog"):
            result = wait_for_switch_account_items(page, ".switch_account_dialog .account_item", logs.append)

        self.assertIs(result, account_locator)
        self.assertGreaterEqual(len(page.wait_calls), 8)
        self.assertEqual(logs, [])

    def test_wait_for_switch_account_items_raises_after_three_attempts(self):
        page = FakePage(
            locator_map={
                (".switch_account_dialog .account_item", None): FakeLocator(counts=[0] * 40),
                (".switch_account_dialog .close_icon", None): FakeLocator(count=1),
                ("div.menu_box_account_info_item[title='切换账号']", None): FakeLocator(count=1),
            }
        )

        with patch("desktop_py.core.fetcher.open_switch_account_dialog"):
            with self.assertRaisesRegex(Exception, "未读取到切换账号列表，已重试 3 次。"):
                wait_for_switch_account_items(page, ".switch_account_dialog .account_item")

    def test_wait_for_switch_account_items_waits_before_first_retry_log(self):
        account_locator = FakeLocator(counts=[0, 0, 0, 0, 0, 0, 0, 0, 1])
        page = FakePage(
            locator_map={
                (".switch_account_dialog .account_item", None): account_locator,
                (".switch_account_dialog .close_icon", None): FakeLocator(count=1),
                ("div.menu_box_account_info_item[title='切换账号']", None): FakeLocator(count=1),
            }
        )
        logs: list[str] = []

        with patch("desktop_py.core.fetcher.open_switch_account_dialog"):
            result = wait_for_switch_account_items(page, ".switch_account_dialog .account_item", logs.append)

        self.assertIs(result, account_locator)
        self.assertEqual(logs, [])
        self.assertGreaterEqual(len(page.wait_calls), 8)

    def test_wait_for_url_contains_returns_when_keyword_appears(self):
        page = FakePage()
        urls = ["https://mp.weixin.qq.com/", "https://mp.weixin.qq.com/wxamp/index/index?token=1"]

        def fake_wait(_timeout):
            page.wait_calls.append(_timeout)
            if len(urls) > 1:
                page.url = urls.pop(1)

        page.url = urls[0]
        page.wait_for_timeout = fake_wait

        self.assertTrue(wait_for_url_contains(page, ("token=",)))

    def test_wait_for_current_account_name_returns_expected_name(self):
        page = FakePage()
        names = ["", "目标账号"]

        with patch(
            "desktop_py.core.fetcher.extract_current_account_name",
            side_effect=lambda _page: names.pop(0) if len(names) > 1 else names[0],
        ):
            actual_name = wait_for_current_account_name(page, "目标账号", timeout_ms=1000)

        self.assertEqual(actual_name, "目标账号")

    def test_wait_for_account_switch_stable_requires_repeated_match(self):
        page = FakePage()
        page.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"
        names = iter(["目标账号", "目标账号"])

        actual_name = wait_for_account_switch_stable(
            page,
            "目标账号",
            extract_current_account_name_fn=lambda _page: next(names),
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
            wait_or_cancel_fn=lambda _page, timeout_ms, _is_cancelled=None: page.wait_for_timeout(timeout_ms),
            stable_rounds=2,
            interval_ms=1,
        )

        self.assertEqual(actual_name, "目标账号")
        self.assertEqual(page.wait_calls, [1])

    def test_wait_for_account_switch_stable_raises_on_wrong_account(self):
        page = FakePage()
        page.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        with self.assertRaisesRegex(Exception, "不是目标账号"):
            wait_for_account_switch_stable(
                page,
                "目标账号",
                extract_current_account_name_fn=lambda _page: "其他账号",
                wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
                wait_or_cancel_fn=lambda _page, timeout_ms, _is_cancelled=None: None,
                stable_rounds=2,
                interval_ms=1,
            )

    def test_wait_or_cancel_raises_when_cancelled(self):
        page = FakePage()

        with self.assertRaisesRegex(CancelledError, "任务已取消"):
            wait_or_cancel(page, 200, lambda: True)

    def test_business_iframe_selector_prefers_js_iframe(self):
        page = FakePage(
            locator_map={
                ("#js_iframe", None): FakeLocator(count=1),
                ("iframe[src*='gameFeedback']", None): FakeLocator(count=1),
            }
        )

        self.assertEqual(business_iframe_selector(page), "#js_iframe")

    def test_business_iframe_selector_falls_back_to_game_feedback_iframe(self):
        page = FakePage(
            locator_map={
                ("#js_iframe", None): FakeLocator(count=0),
                ("iframe[src*='gameFeedback']", None): FakeLocator(count=1),
            }
        )

        self.assertEqual(business_iframe_selector(page), "iframe[src*='gameFeedback']")

    def test_business_iframe_selector_ignores_generic_non_business_iframe(self):
        page = FakePage(
            locator_map={
                ("#js_iframe", None): FakeLocator(count=0),
                ("iframe[src*='gameFeedback']", None): FakeLocator(count=0),
                ("iframe[src*='refund']", None): FakeLocator(count=0),
                ("iframe", None): FakeLocator(count=1),
            }
        )

        self.assertEqual(business_iframe_selector(page), "")

    def test_wait_for_iframe_ready_accepts_fallback_iframe_with_refund_text(self):
        frame = FakeFrame(text="退款申请 处理截止时间：2026-04-20 18:00")
        page = FakePage(
            locator_map={
                ("#js_iframe", None): FakeLocator(count=0),
                ("iframe[src*='gameFeedback']", None): FakeLocator(count=1, frame=frame),
            }
        )

        self.assertTrue(wait_for_iframe_ready(page, timeout_ms=1000))
        self.assertIn(("domcontentloaded", 1000), frame.load_state_calls)

    def test_offline_fixture_extracts_deadline_from_page_text(self):
        text = "退款申请详情 处理截止时间：2026-04-20 18:00 请尽快处理"

        deadline = extract_labeled_datetime(text, "处理截止时间")

        self.assertEqual(deadline, "2026-04-20 18:00")

    def test_safe_page_content_retries_until_success(self):
        page = FakePage()
        page.set_content_results([RuntimeError("navigating"), "<html>ok</html>"])

        content = safe_page_content(page, timeout_ms=1000)

        self.assertEqual(content, "<html>ok</html>")
        self.assertGreaterEqual(len(page.wait_calls), 1)

    def test_safe_page_content_waits_for_navigation_to_settle(self):
        page = FakePage()
        page.set_content_results(
            [
                RuntimeError(
                    "Page.content: Unable to retrieve content because the page is navigating and changing the content."
                ),
                "<html>ok</html>",
            ]
        )

        content = safe_page_content(page, timeout_ms=1500)

        self.assertEqual(content, "<html>ok</html>")
        self.assertIn(("domcontentloaded", 1000), page.load_state_calls)
        self.assertIn(("networkidle", 1000), page.load_state_calls)

    def test_is_login_timeout_page_detects_recoverable_timeout_screen(self):
        class TimeoutPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"

            def wait_for_load_state(self, state=None, timeout=None):
                return None

            def locator(self, selector, **kwargs):
                if selector == "text=登录超时，请重新登录":
                    return FakeLocator(count=1)
                if selector == "text=小程序":
                    return FakeLocator(count=1)
                if selector == "text=退出登录":
                    return FakeLocator(count=1)
                return FakeLocator()

            def content(self):
                return "<div>登录超时，请重新登录</div><div>小程序</div><div>退出登录</div>"

        self.assertTrue(is_login_timeout_page(TimeoutPage(), safe_page_content_fn=safe_page_content))

    def test_recover_login_timeout_page_clicks_mini_program_entry(self):
        class TimeoutPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"
                self.recovered = False

            def wait_for_load_state(self, state=None, timeout=None):
                return None

            def wait_for_timeout(self, timeout):
                return None

            def locator(self, selector, **kwargs):
                if selector == "text=登录超时，请重新登录":
                    return FakeLocator(count=0 if self.recovered else 1)
                if selector == "text=小程序":
                    return FakeLocator(count=1, click_cb=self._recover)
                if selector == "text=退出登录":
                    return FakeLocator(count=1)
                return FakeLocator()

            def content(self):
                if self.recovered:
                    return '<div class="menu_box_account_info">账号设置</div>'
                return "<div>登录超时，请重新登录</div><div>小程序</div><div>退出登录</div>"

            def _recover(self):
                self.recovered = True
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        page = TimeoutPage()
        recovered = recover_login_timeout_page(
            page,
            safe_page_content_fn=safe_page_content,
            wait_or_cancel_fn=lambda current_page, wait_ms, _is_cancelled=None: current_page.wait_for_timeout(wait_ms),
        )

        self.assertTrue(recovered)
        self.assertTrue(page.recovered)
        self.assertIn("token=1", page.url)

    def test_filter_target_unread_notifications_only_keeps_unread_target_titles(self):
        items = [
            {
                "notify_id": "1",
                "class_name": "notice_item js_msg_item",
                "title": "小程序微信认证年审通知",
                "time_text": "2026-04-19",
                "content_text": "年审内容",
            },
            {
                "notify_id": "2",
                "class_name": "notice_item js_msg_item readed",
                "title": "小程序微信认证年审通知",
                "time_text": "2026-04-12",
                "content_text": "已读年审",
            },
            {
                "notify_id": "3",
                "class_name": "notice_item js_msg_item",
                "title": "其它通知",
                "time_text": "2026-04-10",
                "content_text": "其它内容",
            },
        ]

        result = filter_target_unread_notifications(items, "账号A")

        self.assertEqual(
            result,
            [
                {
                    "account_name": "账号A",
                    "notify_id": "1",
                    "title": "小程序微信认证年审通知",
                    "time_text": "2026-04-19",
                    "content_text": "年审内容",
                    "is_unread": True,
                    "matched_rule": "annual_review",
                }
            ],
        )

    def test_build_notification_summary_formats_count_and_titles(self):
        summary = build_notification_summary(
            [
                {"title": "小程序微信认证年审通知"},
                {"title": "你的账号收到一条侵权投诉"},
            ]
        )
        self.assertEqual(summary, "通知中心未读消息 2 条：小程序微信认证年审通知、你的账号收到一条侵权投诉")

    def test_prepare_switch_account_page_recovers_login_timeout_screen(self):
        class TimeoutPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"
                self.recovered = False
                self.goto_calls: list[str] = []

            def wait_for_load_state(self, state=None, timeout=None):
                return None

            def wait_for_timeout(self, timeout):
                return None

            def get_by_text(self, text, exact=False):
                if text == "切换账号" and self.recovered:
                    return FakeLocator(count=1)
                return FakeLocator()

            def locator(self, selector, **kwargs):
                has_text = kwargs.get("has_text")
                if selector == "text=登录超时，请重新登录":
                    return FakeLocator(count=0 if self.recovered else 1)
                if selector == "text=小程序":
                    return FakeLocator(count=1, click_cb=self._recover)
                if selector == "text=退出登录":
                    return FakeLocator(count=1)
                if selector == "div.menu_box_account_info_item[title='切换账号']":
                    return FakeLocator(count=1 if self.recovered else 0)
                if selector == ".menu_box_account_info_item" and has_text == "切换账号":
                    return FakeLocator(count=1 if self.recovered else 0)
                if selector == "[title='切换账号']":
                    return FakeLocator(count=1 if self.recovered else 0)
                if selector == ".switch_account_dialog":
                    return FakeLocator(count=0)
                if selector == ".switch_account_dialog .account_item":
                    return FakeLocator(count=0)
                return FakeLocator()

            def content(self):
                if self.recovered:
                    return '<div class="menu_box_account_info_item" title="切换账号">切换账号</div>'
                return "<div>登录超时，请重新登录</div><div>小程序</div><div>退出登录</div>"

            def goto(self, url, wait_until=None, timeout=None):
                self.goto_calls.append(url)
                self.url = url

            def _recover(self):
                self.recovered = True
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        page = TimeoutPage()
        prepare_switch_account_page(
            page,
            "https://mp.weixin.qq.com/",
            None,
            switch_dialog_ready_fn=lambda _page: False,
            find_switch_entry_fn=find_switch_entry,
            should_retry_switch_from_home_fn=should_retry_switch_from_home,
            log_fn=lambda *_args, **_kwargs: None,
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
        )

        self.assertTrue(page.recovered)
        self.assertEqual(page.goto_calls, [])

    def test_fallback_from_responses_prefers_appeal_deadline_time(self):
        deadline = _fallback_from_responses(
            [
                {
                    "data": {
                        "user_refund_check_list": [
                            {
                                "ctrl_info": {
                                    "deadline_time": "1776147849",
                                    "appeal_deadline_time": "1776737974",
                                }
                            }
                        ]
                    }
                }
            ]
        )

        self.assertEqual(deadline, "2026-04-21 10:19:34")

    def test_capture_response_payload_keeps_json_body_for_fallback(self):
        response = FakeResponse(
            '{"data":{"user_refund_check_list":[{"ctrl_info":{"appeal_deadline_time":"1776737974"}}]}}'
        )

        payload = _capture_response_payload(response)

        self.assertEqual(
            payload["body"]["data"]["user_refund_check_list"][0]["ctrl_info"]["appeal_deadline_time"], "1776737974"
        )

    def test_capture_response_payload_adds_business_metadata(self):
        response = FakeResponse(
            '{"data":{"total_count":1,"user_refund_check_list":[{"ctrl_info":{"deadline_time":"1777046400"}}]}}',
            url="https://game.weixin.qq.com/cgi-bin/gamewxagbdatawap/getuserrefundchecklist?per_page=6&cur_page=0",
        )

        payload = _capture_response_payload(response)

        self.assertEqual(payload["response_type"], "list")
        self.assertIn("captured_at", payload)
        self.assertEqual(payload["token"], "")

    def test_classify_refund_response_type_distinguishes_list_and_detail(self):
        self.assertEqual(
            classify_refund_response_type(
                "https://game.weixin.qq.com/cgi-bin/gamewxagbdatawap/getuserrefundchecklist?per_page=6&cur_page=0",
                {},
            ),
            "list",
        )
        self.assertEqual(
            classify_refund_response_type(
                "https://game.weixin.qq.com/cgi-bin/gamewxagbdatawap/getuserrefundchecklist?cid=abc",
                {},
            ),
            "detail",
        )
        self.assertEqual(extract_response_token("https://mp.weixin.qq.com/wxamp/index/index?token=123"), "123")

    def test_offline_response_fixture_extracts_deadline_candidate(self):
        deadline = _fallback_from_responses(
            [
                {
                    "body": {
                        "data": {
                            "user_refund_check_list": [
                                {
                                    "ctrl_info": {
                                        "appeal_deadline_time": "2026-04-20 18:00",
                                    }
                                }
                            ]
                        }
                    }
                }
            ]
        )

        self.assertEqual(deadline, "2026-04-20 18:00")

    def test_fetch_accounts_batch_groups_accounts_by_state_path(self):
        accounts = [
            AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False),
            AccountConfig(name="账号B", state_path="storage/a.json", is_entry_account=False),
            AccountConfig(name="账号C", state_path="storage/b.json", is_entry_account=False),
        ]
        progress_calls: list[str] = []
        contexts = []

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch("desktop_py.core.fetcher.create_browser_context") as mock_create_context,
            patch(
                "desktop_py.core.fetcher._fetch_account_in_page",
                side_effect=lambda page, context, account, logger, profile_dir: type(
                    "Result", (), {"account_name": account.name}
                )(),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()
            for _ in range(2):
                fake_context = type(
                    "FakeContext", (), {"new_page": lambda self: object(), "close": lambda self: None}
                )()
                fake_browser = type("FakeBrowser", (), {"close": lambda self: None})()
                contexts.append((fake_browser, fake_context))
            mock_create_context.side_effect = contexts

            results = fetch_accounts_batch(accounts, progress=lambda result: progress_calls.append(result.account_name))

        self.assertEqual([result.account_name for result in results], ["账号A", "账号B", "账号C"])
        self.assertEqual(progress_calls, ["账号A", "账号B", "账号C"])
        self.assertEqual(mock_create_context.call_count, 2)

    def test_fetch_accounts_batch_creates_and_closes_single_page_per_group(self):
        accounts = [
            AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False),
            AccountConfig(name="账号B", state_path="storage/a.json", is_entry_account=False),
        ]
        created_pages = []

        class FakePageObject:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeContext:
            def new_page(self):
                page = FakePageObject()
                created_pages.append(page)
                return page

            def close(self):
                return None

        fake_context = FakeContext()
        fake_browser = type("FakeBrowser", (), {"close": lambda self: None})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch("desktop_py.core.fetcher.create_browser_context", return_value=(fake_browser, fake_context)),
            patch(
                "desktop_py.core.fetcher._fetch_account_in_page",
                side_effect=lambda page, context, account, logger, profile_dir: type(
                    "Result", (), {"account_name": account.name}
                )(),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            results = fetch_accounts_batch(accounts)
            close_all_group_runtimes()

        self.assertEqual([result.account_name for result in results], ["账号A", "账号B"])
        self.assertEqual(len(created_pages), 1)
        self.assertTrue(all(page.closed for page in created_pages))

    def test_fetch_account_reuses_existing_group_runtime(self):
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)
        created_pages = []

        class FakePageObject:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeContext:
            def new_page(self):
                page = FakePageObject()
                created_pages.append(page)
                return page

            def close(self):
                return None

        fake_context = FakeContext()
        fake_browser = type("FakeBrowser", (), {"close": lambda self: None})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context", return_value=(fake_browser, fake_context)
            ) as mock_create_context,
            patch(
                "desktop_py.core.fetcher._fetch_account_in_page",
                side_effect=lambda page, context, account, logger, profile_dir, is_cancelled=None: FetchResult(
                    account_name=account.name,
                    ok=True,
                    actual_account_name=account.name,
                ),
            ) as mock_fetch,
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            first = fetch_account(account, 0)
            second = fetch_account(account, 0)
            close_all_group_runtimes()

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(mock_create_context.call_count, 1)
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(len(created_pages), 1)
        self.assertTrue(created_pages[0].closed)

    def test_fetch_account_and_batch_share_group_runtime(self):
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)
        created_pages = []

        class FakePageObject:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class FakeContext:
            def new_page(self):
                page = FakePageObject()
                created_pages.append(page)
                return page

            def close(self):
                return None

        fake_context = FakeContext()
        fake_browser = type("FakeBrowser", (), {"close": lambda self: None})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context", return_value=(fake_browser, fake_context)
            ) as mock_create_context,
            patch(
                "desktop_py.core.fetcher._fetch_account_in_page",
                side_effect=lambda page, context, account, logger, profile_dir, is_cancelled=None: FetchResult(
                    account_name=account.name,
                    ok=True,
                    actual_account_name=account.name,
                ),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            single_result = fetch_account(account, 0)
            batch_results = fetch_accounts_batch([account])
            close_all_group_runtimes()

        self.assertTrue(single_result.ok)
        self.assertEqual([item.account_name for item in batch_results], ["账号A"])
        self.assertEqual(mock_create_context.call_count, 1)
        self.assertEqual(len(created_pages), 1)
        self.assertTrue(created_pages[0].closed)

    def test_register_response_capture_removes_listener_on_cleanup(self):
        events: dict[str, list] = {}

        class ListenerPage:
            def on(self, event_name, callback):
                events.setdefault(event_name, []).append(callback)

            def remove_listener(self, event_name, callback):
                events.setdefault(event_name, []).remove(callback)

        page = ListenerPage()

        captures, cleanup = register_response_capture(page, lambda response: {"url": response})

        self.assertEqual(len(events["response"]), 1)
        events["response"][0]("https://example.com/api")
        self.assertEqual(captures, [{"url": "https://example.com/api"}])

        cleanup()

        self.assertEqual(events["response"], [])

    def test_fetch_account_in_page_uses_cached_current_account_name_without_reloading_home(self):
        calls = {
            "extract": 0,
            "switch": 0,
            "feedback": 0,
            "cleanup": 0,
        }

        class CachedPage:
            def __init__(self):
                self.url = (
                    "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=1"
                )
                self._current_account_name_cache = "账号A"
                self.goto_calls: list[str] = []

            def goto(self, url, wait_until=None, timeout=None):
                self.goto_calls.append(url)
                self.url = url

        test_case = self

        class FakeFrameLocator:
            def locator(self, selector):
                test_case.assertEqual(selector, "body")

                class FakeBodyLocator:
                    def text_content(self, timeout=None):
                        return "退款申请(0)"

                return FakeBodyLocator()

        page = CachedPage()
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)

        def fake_register_response_capture(_page, _capture):
            return [], lambda: calls.__setitem__("cleanup", calls["cleanup"] + 1)

        def fake_extract_current_account_name(_page):
            calls["extract"] += 1
            return "账号A"

        def fake_switch_to_account(_page, _account_name, _home_url, _logger):
            calls["switch"] += 1

        def fake_open_feedback_page(_page, **_kwargs):
            calls["feedback"] += 1
            return "https://example.com/detail"

        result = fetch_account_in_page_impl(
            page,
            object(),
            account,
            None,
            "",
            None,
            account_output_dir_fn=lambda _account_name: Path("output") / "账号A",
            register_response_capture_fn=fake_register_response_capture,
            capture_response_payload_fn=lambda response: response,
            resolve_bootstrap_url_fn=lambda _account, _output_dir: _account.home_url,
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
            extract_current_account_name_fn=fake_extract_current_account_name,
            should_switch_for_account_fn=lambda _account, current_account_name: current_account_name != _account.name,
            switch_to_account_fn=fake_switch_to_account,
            log_fn=lambda _logger, _message: None,
            open_feedback_page_fn=fake_open_feedback_page,
            build_feedback_url_fn=lambda page_url: page_url,
            wait_for_iframe_ready_fn=lambda *_args, **_kwargs: True,
            resolve_frame_locator_fn=lambda *_args, **_kwargs: FakeFrameLocator(),
            business_iframe_selector_fn=lambda _page: "#js_iframe",
            safe_page_content_fn=lambda _page: "<html></html>",
            is_empty_refund_list_fn=lambda list_text: "退款申请(0)" in list_text,
            confirm_empty_refund_list_fn=lambda **kwargs: (True, kwargs["initial_text"]),
            build_empty_refund_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
            build_detail_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(page.goto_calls, [])
        self.assertEqual(calls["extract"], 0)
        self.assertEqual(calls["switch"], 0)
        self.assertEqual(calls["feedback"], 1)
        self.assertEqual(calls["cleanup"], 1)

    def test_fetch_account_in_page_rechecks_empty_list_before_marking_empty(self):
        class EmptyThenDataPage:
            def __init__(self):
                self.url = (
                    "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=1"
                )

        class SequencedBodyLocator:
            def __init__(self, values: list[str]):
                self._values = list(values)

            def text_content(self, timeout=None):
                if len(self._values) > 1:
                    return self._values.pop(0)
                return self._values[0]

            def inner_html(self, timeout=None):
                return "<div>ok</div>"

        class SequencedFrameLocator:
            def __init__(self, body_locator):
                self._body_locator = body_locator

            def locator(self, selector):
                test_case.assertEqual(selector, "body")
                return self._body_locator

            def get_by_text(self, _text, exact=False):
                return FakeLocator(count=0)

        test_case = self
        page = EmptyThenDataPage()
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)
        body_locator = SequencedBodyLocator(["退款申请(0)", "退款申请(1) 处理截止时间：2026-04-25 00:00:00"])
        frame_locator = SequencedFrameLocator(body_locator)
        empty_called = {"value": False}
        detail_called = {"value": False}

        result = fetch_account_in_page_impl(
            page,
            object(),
            account,
            None,
            "",
            None,
            account_output_dir_fn=lambda _account_name: Path("output") / "账号A",
            register_response_capture_fn=lambda _page, _capture: ([], lambda: None),
            capture_response_payload_fn=lambda response: response,
            resolve_bootstrap_url_fn=lambda _account, _output_dir: _account.home_url,
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
            extract_current_account_name_fn=lambda _page: "账号A",
            should_switch_for_account_fn=lambda _account, _current_account_name: False,
            switch_to_account_fn=lambda *_args, **_kwargs: None,
            log_fn=lambda *_args, **_kwargs: None,
            open_feedback_page_fn=lambda _page, **_kwargs: "https://example.com/detail",
            build_feedback_url_fn=lambda page_url: page_url,
            wait_for_iframe_ready_fn=lambda *_args, **_kwargs: True,
            resolve_frame_locator_fn=lambda *_args, **_kwargs: frame_locator,
            business_iframe_selector_fn=lambda _page: "#js_iframe",
            safe_page_content_fn=lambda _page: "<html></html>",
            is_empty_refund_list_fn=lambda list_text: "退款申请(0)" in list_text,
            confirm_empty_refund_list_fn=lambda **kwargs: (
                False,
                kwargs["frame_locator"].locator("body").text_content(),
            ),
            build_empty_refund_result_fn=lambda **kwargs: (
                empty_called.__setitem__("value", True)
                or FetchResult(
                    account_name=kwargs["account"].name,
                    ok=True,
                    actual_account_name=kwargs["account"].name,
                    page_url=kwargs["feedback_url"],
                )
            ),
            build_detail_result_fn=lambda **kwargs: (
                detail_called.__setitem__("value", True)
                or FetchResult(
                    account_name=kwargs["account"].name,
                    ok=True,
                    actual_account_name=kwargs["account"].name,
                    deadline_text="2026-04-25 00:00:00",
                    page_url=kwargs["feedback_url"],
                )
            ),
        )

        self.assertTrue(result.ok)
        self.assertFalse(empty_called["value"])
        self.assertTrue(detail_called["value"])

    def test_fetch_account_in_page_only_passes_feedback_window_captures(self):
        class DemoPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        page = DemoPage()
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)
        captures = [
            {"response_type": "list", "body": {"data": {"total_count": 0, "user_refund_check_list": []}}},
        ]
        seen_confirm_captures: list[list[dict]] = []

        class FrameLocator:
            def locator(self, selector):
                return FakeLocator(text="退款申请(0)")

            def get_by_text(self, text, exact=False):
                return FakeLocator(count=0)

        def fake_open_feedback_page(_page, **_kwargs):
            captures.append(
                {
                    "response_type": "list",
                    "body": {
                        "data": {
                            "total_count": 1,
                            "user_refund_check_list": [{"ctrl_info": {"deadline_time": "1777046400"}}],
                        }
                    },
                }
            )
            return "https://example.com/detail"

        result = fetch_account_in_page_impl(
            page,
            object(),
            account,
            None,
            "",
            None,
            account_output_dir_fn=lambda _account_name: Path("output") / "账号A",
            register_response_capture_fn=lambda _page, _capture: (captures, lambda: None),
            capture_response_payload_fn=lambda response: response,
            resolve_bootstrap_url_fn=lambda _account, _output_dir: _account.home_url,
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
            extract_current_account_name_fn=lambda _page: "账号A",
            should_switch_for_account_fn=lambda _account, _current_account_name: False,
            switch_to_account_fn=lambda *_args, **_kwargs: None,
            log_fn=lambda *_args, **_kwargs: None,
            open_feedback_page_fn=fake_open_feedback_page,
            build_feedback_url_fn=lambda page_url: page_url,
            wait_for_iframe_ready_fn=lambda *_args, **_kwargs: True,
            resolve_frame_locator_fn=lambda *_args, **_kwargs: FrameLocator(),
            business_iframe_selector_fn=lambda _page: "#js_iframe",
            safe_page_content_fn=lambda _page: "<html></html>",
            is_empty_refund_list_fn=lambda list_text: "退款申请(0)" in list_text,
            confirm_empty_refund_list_fn=lambda **kwargs: (
                seen_confirm_captures.append(list(kwargs["captures"])) or (False, kwargs["initial_text"])
            ),
            build_empty_refund_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
            build_detail_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                deadline_text="2026-04-25 00:00:00",
                page_url=kwargs["feedback_url"],
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(seen_confirm_captures), 1)
        self.assertEqual(len(seen_confirm_captures[0]), 1)
        self.assertEqual(seen_confirm_captures[0][0]["body"]["data"]["total_count"], 1)

    def test_fetch_account_in_page_appends_notification_summary(self):
        class DemoPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        page = DemoPage()
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)

        class FrameLocator:
            def locator(self, selector):
                return FakeLocator(text="退款申请(0)")

            def get_by_text(self, text, exact=False):
                return FakeLocator(count=0)

        result = fetch_account_in_page_impl(
            page,
            object(),
            account,
            None,
            "",
            None,
            account_output_dir_fn=lambda _account_name: Path("output") / "账号A",
            register_response_capture_fn=lambda _page, _capture: ([], lambda: None),
            capture_response_payload_fn=lambda response: response,
            resolve_bootstrap_url_fn=lambda _account, _output_dir: _account.home_url,
            wait_for_url_contains_fn=lambda *_args, **_kwargs: True,
            extract_current_account_name_fn=lambda _page: "账号A",
            should_switch_for_account_fn=lambda _account, _current_account_name: False,
            switch_to_account_fn=lambda *_args, **_kwargs: None,
            log_fn=lambda *_args, **_kwargs: None,
            open_feedback_page_fn=lambda _page, **_kwargs: "https://example.com/detail",
            build_feedback_url_fn=lambda page_url: page_url,
            wait_for_iframe_ready_fn=lambda *_args, **_kwargs: True,
            resolve_frame_locator_fn=lambda *_args, **_kwargs: FrameLocator(),
            business_iframe_selector_fn=lambda _page: "#js_iframe",
            safe_page_content_fn=lambda _page: "<html></html>",
            fetch_notifications_fn=lambda *_args, **_kwargs: {
                "ok": True,
                "notifications": [{"title": "小程序微信认证年审通知"}],
                "summary": "通知中心未读消息 1 条：小程序微信认证年审通知",
                "page_url": "https://example.com/notice",
            },
            is_empty_refund_list_fn=lambda list_text: "退款申请(0)" in list_text,
            confirm_empty_refund_list_fn=lambda **kwargs: (True, kwargs["initial_text"]),
            build_empty_refund_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
            build_detail_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
        )

        self.assertTrue(result.ok)
        self.assertIn("通知中心未读消息 1 条：小程序微信认证年审通知", result.note)

    def test_fetch_account_in_page_recovers_login_timeout_screen_before_opening_feedback(self):
        class TimeoutThenReadyPage:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"
                self.recovered = False
                self.goto_calls: list[str] = []

            def goto(self, url, wait_until=None, timeout=None):
                self.goto_calls.append(url)
                self.url = url

            def wait_for_load_state(self, state=None, timeout=None):
                return None

            def wait_for_timeout(self, timeout):
                return None

            def locator(self, selector, **kwargs):
                if selector == "text=登录超时，请重新登录":
                    return FakeLocator(count=0 if self.recovered else 1)
                if selector == "text=小程序":
                    return FakeLocator(count=1, click_cb=self._recover)
                if selector == "text=退出登录":
                    return FakeLocator(count=1)
                return FakeLocator()

            def content(self):
                if self.recovered:
                    return '<div class="menu_box_account_info">账号设置</div>'
                return "<div>登录超时，请重新登录</div><div>小程序</div><div>退出登录</div>"

            def _recover(self):
                self.recovered = True
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

        page = TimeoutThenReadyPage()
        account = AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False)

        class FakeFrameLocator:
            def locator(self, selector):
                return FakeLocator(text="退款申请(0)")

            def get_by_text(self, text, exact=False):
                return FakeLocator(count=0)

        result = fetch_account_in_page_impl(
            page,
            object(),
            account,
            None,
            "",
            None,
            account_output_dir_fn=lambda _account_name: Path("output") / "账号A",
            register_response_capture_fn=lambda _page, _capture: ([], lambda: None),
            capture_response_payload_fn=lambda response: response,
            resolve_bootstrap_url_fn=lambda _account, _output_dir: _account.home_url,
            wait_for_url_contains_fn=lambda current_page, keywords, timeout_ms=0, is_cancelled=None: any(
                keyword in current_page.url for keyword in keywords
            ),
            extract_current_account_name_fn=lambda _page: "账号A",
            should_switch_for_account_fn=lambda _account, _current_account_name: False,
            switch_to_account_fn=lambda *_args, **_kwargs: None,
            log_fn=lambda *_args, **_kwargs: None,
            open_feedback_page_fn=lambda _page, **_kwargs: "https://example.com/detail",
            build_feedback_url_fn=lambda page_url: page_url,
            wait_for_iframe_ready_fn=lambda *_args, **_kwargs: True,
            resolve_frame_locator_fn=lambda *_args, **_kwargs: FakeFrameLocator(),
            business_iframe_selector_fn=lambda _page: "#js_iframe",
            safe_page_content_fn=lambda current_page: current_page.content(),
            is_empty_refund_list_fn=lambda list_text: "退款申请(0)" in list_text,
            confirm_empty_refund_list_fn=lambda **kwargs: (True, kwargs["initial_text"]),
            build_empty_refund_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
            build_detail_result_fn=lambda **kwargs: FetchResult(
                account_name=kwargs["account"].name,
                ok=True,
                actual_account_name=kwargs["account"].name,
                page_url=kwargs["feedback_url"],
            ),
        )

        self.assertTrue(result.ok)
        self.assertTrue(page.recovered)
        self.assertIn("https://mp.weixin.qq.com/", page.goto_calls)

    def test_confirm_empty_refund_list_requires_second_confirmation(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()
        body_locator = FakeLocator(text="退款申请(0)")

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: "处理截止时间" in text,
            captures_indicate_non_empty_refunds_fn=lambda captures: False,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=1,
            interval_ms=1,
        )

        self.assertTrue(confirmed)
        self.assertEqual(latest_text, "退款申请(0)")

    def test_confirm_empty_refund_list_detects_late_pending_data(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()

        class BodyLocator:
            def __init__(self):
                self._values = ["退款申请(1) 处理截止时间：2026-04-25 00:00:00"]

            def text_content(self, timeout=None):
                return self._values[0]

        body_locator = BodyLocator()

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: "处理截止时间" in text or "退款申请(1)" in text,
            captures_indicate_non_empty_refunds_fn=lambda captures: False,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=1,
            interval_ms=1,
        )

        self.assertFalse(confirmed)
        self.assertIn("处理截止时间", latest_text)

    def test_confirm_empty_refund_list_detects_very_late_detail_before_accepting_empty(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()

        class BodyLocator:
            def __init__(self):
                self._values = [
                    "退款申请(0)",
                    "退款申请(0)",
                    "退款申请(0)",
                    "退款申请(0)",
                    "退款申请(1) 处理截止时间：2026-04-22 16:02:09",
                ]

            def text_content(self, timeout=None):
                if len(self._values) > 1:
                    return self._values.pop(0)
                return self._values[0]

        body_locator = BodyLocator()

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: "处理截止时间" in text or "退款申请(1)" in text,
            captures_indicate_non_empty_refunds_fn=lambda captures: False,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=5,
            interval_ms=1,
        )

        self.assertFalse(confirmed)
        self.assertIn("处理截止时间", latest_text)

    def test_confirm_empty_refund_list_uses_capture_signal_to_block_false_empty(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()
        body_locator = FakeLocator(text="退款申请(0)")

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[{"body": {"data": {"appeal_deadline_time": "2026-04-25 00:00:00"}}}],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: False,
            captures_indicate_non_empty_refunds_fn=lambda captures: True,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=1,
            interval_ms=1,
        )

        self.assertFalse(confirmed)
        self.assertEqual(latest_text, "退款申请(0)")

    def test_confirm_empty_refund_list_prefers_non_empty_list_capture_over_empty_dom(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()
        body_locator = FakeLocator(text="退款申请(0)")

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[
                {
                    "response_type": "list",
                    "body": {
                        "data": {
                            "total_count": 1,
                            "user_refund_check_list": [{"ctrl_info": {"deadline_time": "1777046400"}}],
                        }
                    },
                }
            ],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: False,
            captures_indicate_non_empty_refunds_fn=lambda captures: False,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=1,
            interval_ms=1,
        )

        self.assertFalse(confirmed)
        self.assertEqual(latest_text, "退款申请(0)")

    def test_confirm_empty_refund_list_prefers_empty_list_capture_when_dom_empty(self):
        from desktop_py.core.fetcher_page_strategy import confirm_empty_refund_list

        page = FakePage()
        body_locator = FakeLocator(text="退款申请(0)")

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        confirmed, latest_text = confirm_empty_refund_list(
            page=page,
            frame_locator=FrameLocator(),
            initial_text="退款申请(0)",
            captures=[
                {
                    "response_type": "list",
                    "body": {"data": {"total_count": 0, "user_refund_check_list": []}},
                }
            ],
            is_empty_refund_list_fn=lambda text: "退款申请(0)" in text,
            has_pending_refund_signal_fn=lambda text: False,
            captures_indicate_non_empty_refunds_fn=lambda captures: False,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=1,
            interval_ms=1,
        )

        self.assertTrue(confirmed)
        self.assertEqual(latest_text, "退款申请(0)")

    def test_confirm_detail_deadline_retries_until_text_ready(self):
        from desktop_py.core.fetcher_page_strategy import confirm_detail_deadline

        page = FakePage()

        class BodyLocator:
            def __init__(self):
                self._texts = ["详情加载中", "处理截止时间：2026-04-25 00:00:00"]

            def text_content(self, timeout=None):
                if len(self._texts) > 1:
                    return self._texts.pop(0)
                return self._texts[0]

            def inner_html(self, timeout=None):
                return "<div>detail</div>"

        body_locator = BodyLocator()

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        deadline_text, frame_text, _frame_html = confirm_detail_deadline(
            page=page,
            frame_locator=FrameLocator(),
            captures=[],
            feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
            extract_labeled_datetime_fn=extract_labeled_datetime,
            fallback_from_responses_fn=lambda _captures: "",
            filter_detail_captures_fn=lambda captures, _feedback_url: captures,
            wait_or_cancel_fn=lambda _page, timeout_ms, _is_cancelled=None: page.wait_for_timeout(timeout_ms),
            retries=2,
            interval_ms=1,
        )

        self.assertEqual(deadline_text, "2026-04-25 00:00:00")
        self.assertIn("处理截止时间", frame_text)
        self.assertEqual(page.wait_calls, [1])

    def test_confirm_detail_deadline_default_window_tolerates_slow_first_load(self):
        from desktop_py.core.fetcher_page_strategy import confirm_detail_deadline

        page = FakePage()

        class BodyLocator:
            def __init__(self):
                self._texts = [
                    "详情加载中",
                    "详情加载中",
                    "详情加载中",
                    "详情加载中",
                    "详情加载中",
                    "详情加载中",
                    "处理截止时间：2026-04-22 16:02:09",
                ]

            def text_content(self, timeout=None):
                if len(self._texts) > 1:
                    return self._texts.pop(0)
                return self._texts[0]

            def inner_html(self, timeout=None):
                return "<div>detail</div>"

        body_locator = BodyLocator()

        class FrameLocator:
            def locator(self, selector):
                return body_locator

        deadline_text, frame_text, _frame_html = confirm_detail_deadline(
            page=page,
            frame_locator=FrameLocator(),
            captures=[],
            feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
            extract_labeled_datetime_fn=extract_labeled_datetime,
            fallback_from_responses_fn=lambda _captures: "",
            filter_detail_captures_fn=lambda captures, _feedback_url: captures,
            wait_or_cancel_fn=lambda _page, timeout_ms, _is_cancelled=None: page.wait_for_timeout(timeout_ms),
        )

        self.assertEqual(deadline_text, "2026-04-22 16:02:09")
        self.assertIn("处理截止时间", frame_text)
        self.assertEqual(page.wait_calls, [1500, 1500, 1500, 1500, 1500, 1500])

    def test_confirm_detail_deadline_prefers_detail_capture_over_dom(self):
        from desktop_py.core.fetcher_page_strategy import confirm_detail_deadline, filter_detail_captures

        page = FakePage()

        class BodyLocator:
            def text_content(self, timeout=None):
                return "详情加载中"

            def inner_html(self, timeout=None):
                return "<div>loading</div>"

        class FrameLocator:
            def locator(self, selector):
                return BodyLocator()

        deadline_text, frame_text, _frame_html = confirm_detail_deadline(
            page=page,
            frame_locator=FrameLocator(),
            captures=[
                {
                    "response_type": "detail",
                    "url": "https://game.weixin.qq.com/cgi-bin/gamewxagbdatawap/getuserrefundchecklist?cid=abc",
                    "body": {"data": {"user_refund_check_list": [{"ctrl_info": {"deadline_time": "1777046400"}}]}},
                }
            ],
            feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
            extract_labeled_datetime_fn=extract_labeled_datetime,
            fallback_from_responses_fn=_fallback_from_responses,
            filter_detail_captures_fn=filter_detail_captures,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=0,
            interval_ms=1,
        )

        self.assertEqual(deadline_text, "2026-04-25 00:00:00")
        self.assertEqual(frame_text, "详情加载中")

    def test_confirm_detail_deadline_filters_previous_account_captures(self):
        from desktop_py.core.fetcher_page_strategy import confirm_detail_deadline, filter_detail_captures

        page = FakePage()

        class BodyLocator:
            def text_content(self, timeout=None):
                return "详情加载中"

            def inner_html(self, timeout=None):
                return "<div>detail</div>"

        class FrameLocator:
            def locator(self, selector):
                return BodyLocator()

        captures = [
            {
                "response_type": "detail",
                "token": "old",
                "url": "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=old",
                "body": {
                    "data": {"user_refund_check_list": [{"ctrl_info": {"appeal_deadline_time": "2026-04-22 16:02:09"}}]}
                },
            },
            {
                "response_type": "detail",
                "token": "current",
                "url": "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
                "body": {
                    "data": {"user_refund_check_list": [{"ctrl_info": {"appeal_deadline_time": "2026-04-27 08:37:32"}}]}
                },
            },
        ]

        deadline_text, _frame_text, _frame_html = confirm_detail_deadline(
            page=page,
            frame_locator=FrameLocator(),
            captures=captures,
            feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
            extract_labeled_datetime_fn=extract_labeled_datetime,
            fallback_from_responses_fn=_fallback_from_responses,
            filter_detail_captures_fn=filter_detail_captures,
            wait_or_cancel_fn=lambda _page, _timeout_ms, _is_cancelled=None: None,
            retries=0,
            interval_ms=1,
        )

        self.assertEqual(deadline_text, "2026-04-27 08:37:32")

    def test_build_detail_result_only_uses_captures_after_action_click(self):
        from desktop_py.core.fetcher_page_strategy import build_detail_result

        captures = [
            {
                "url": "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
                "body": {"data": {"appeal_deadline_time": "2026-04-22 16:02:09"}},
            }
        ]
        seen_captures: list[list[dict]] = []

        class ActionLocator:
            def __init__(self):
                self.last = self

            def count(self):
                return 1

            def click(self, timeout=None):
                captures.append(
                    {
                        "url": "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
                        "body": {"data": {"appeal_deadline_time": "2026-04-27 08:37:32"}},
                    }
                )

        class FrameLocator:
            def get_by_text(self, text, exact=False):
                return ActionLocator()

        def fake_confirm_detail_deadline(**kwargs):
            seen_captures.append(list(kwargs["captures"]))
            return _fallback_from_responses(kwargs["captures"]), "detail text", "<div>detail</div>"

        with TemporaryDirectory() as temp_dir:
            result = build_detail_result(
                page=object(),
                context=object(),
                account=AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False),
                output_dir=Path(temp_dir),
                frame_locator=FrameLocator(),
                captures=captures,
                feedback_url="https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current",
                profile_dir="",
                logger=None,
                safe_page_content_fn=lambda _page: "<html></html>",
                extract_current_account_name_fn=lambda _page: "账号A",
                confirm_detail_deadline_fn=fake_confirm_detail_deadline,
            )

        self.assertEqual(result.deadline_text, "2026-04-27 08:37:32")
        self.assertEqual(len(seen_captures), 1)
        self.assertEqual(len(seen_captures[0]), 1)
        self.assertEqual(
            _fallback_from_responses(seen_captures[0]),
            "2026-04-27 08:37:32",
        )

    def test_close_context_and_browser_still_closes_browser_when_context_close_fails(self):
        calls: list[str] = []

        class FakeContext:
            def close(self):
                calls.append("context")
                raise RuntimeError("context close failed")

        class FakeBrowser:
            def close(self):
                calls.append("browser")

        with self.assertRaisesRegex(RuntimeError, "context close failed"):
            _close_context_and_browser(FakeContext(), FakeBrowser())

        self.assertEqual(calls, ["context", "browser"])

    def test_save_login_state_still_closes_browser_when_context_close_fails(self):
        calls: list[str] = []

        class FakePageForLogin:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None):
                return None

            def wait_for_timeout(self, _timeout):
                return None

            def close(self):
                calls.append("page")

        class FakeContextForLogin:
            def __init__(self):
                self.page = FakePageForLogin()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                return None

            def close(self):
                calls.append("context")
                raise RuntimeError("context close failed")

        class FakeBrowserForLogin:
            def __init__(self):
                self.context = FakeContextForLogin()

            def new_context(self, viewport=None):
                return self.context

            def close(self):
                calls.append("browser")

        fake_browser = FakeBrowserForLogin()
        fake_playwright = type(
            "FakePlaywright",
            (),
            {"chromium": type("FakeChromium", (), {"launch": lambda self, headless=False: fake_browser})()},
        )()

        with patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright:
            mock_playwright.return_value.__enter__.return_value = fake_playwright
            with self.assertRaisesRegex(RuntimeError, "context close failed"):
                save_login_state(AccountConfig(name="账号A", state_path="storage/a.json"), 1)

        self.assertEqual(calls, ["page", "context", "browser"])

    def test_save_login_state_fails_without_overwriting_existing_state_when_login_not_completed(self):
        calls: list[str] = []

        class FakePageForLogin:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"

            def goto(self, _url, wait_until=None):
                return None

            def wait_for_timeout(self, _timeout):
                return None

            def close(self):
                calls.append("page")

        class FakeContextForLogin:
            def __init__(self):
                self.page = FakePageForLogin()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        class FakeBrowserForLogin:
            def __init__(self):
                self.context = FakeContextForLogin()

            def new_context(self, viewport=None):
                return self.context

            def close(self):
                calls.append("browser")

        fake_browser = FakeBrowserForLogin()
        fake_playwright = type(
            "FakePlaywright",
            (),
            {"chromium": type("FakeChromium", (), {"launch": lambda self, headless=False: fake_browser})()},
        )()

        timestamps = iter([100.0, 101.0])
        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch("desktop_py.core.fetcher.datetime") as mock_datetime,
        ):
            mock_playwright.return_value.__enter__.return_value = fake_playwright
            mock_datetime.now.return_value.timestamp.side_effect = lambda: next(timestamps)

            with self.assertRaisesRegex(Exception, "未在限定时间内检测到登录成功"):
                save_login_state(AccountConfig(name="账号A", state_path="storage/a.json"), 1)

        self.assertEqual(calls, ["page", "context", "browser"])
        self.assertFalse(any(call.startswith("storage:") for call in calls))

    def test_fetch_switchable_accounts_still_closes_browser_when_context_close_fails(self):
        calls: list[str] = []

        class FakePageForSwitch:
            def goto(self, _url, wait_until=None, timeout=None):
                return None

            def close(self):
                calls.append("page")

        class FakeContextForSwitch:
            def __init__(self):
                self.page = FakePageForSwitch()

            def new_page(self):
                return self.page

            def close(self):
                calls.append("context")
                raise RuntimeError("context close failed")

        class FakeBrowserForSwitch:
            def close(self):
                calls.append("browser")

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(FakeBrowserForSwitch(), FakeContextForSwitch()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
            patch("desktop_py.core.fetcher.list_switchable_accounts", return_value=["账号A", "账号B"]),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(RuntimeError, "context close failed"):
                fetch_switchable_accounts(
                    AccountConfig(name="主账号", state_path="storage/shared.json"), profile_dir=""
                )

        self.assertEqual(calls, ["page", "context", "browser"])

    def test_validate_account_state_does_not_persist_shared_profile_state(self):
        calls: list[str] = []

        class FakePageForValidation:
            url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                calls.append("page")

        class FakeContextForValidation:
            def __init__(self):
                self.page = FakePageForValidation()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(None, FakeContextForValidation()),
            ),
            patch("desktop_py.core.fetcher.validate_shared_browser_profile_dir", return_value="C:/profile"),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = validate_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="C:/profile",
            )

        self.assertTrue(valid)
        self.assertNotIn("storage:storage\\shared.json:True", calls)
        self.assertEqual(calls[-2:], ["page", "context"])

    def test_validate_account_state_trusts_transient_backend_url_match(self):
        calls: list[str] = []

        class FakePageForValidation:
            url = "https://mp.weixin.qq.com/"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                calls.append("page")

        class FakeContextForValidation:
            def __init__(self):
                self.page = FakePageForValidation()

            def new_page(self):
                return self.page

            def close(self):
                calls.append("context")

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(None, FakeContextForValidation()),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True) as mock_wait,
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = validate_account_state(AccountConfig(name="主账号", state_path="storage/shared.json"))

        self.assertTrue(valid)
        mock_wait.assert_called_once_with(
            mock_wait.call_args.args[0],
            ("token=", "/wxamp/index/index", "pluginRedirect/gameFeedback"),
            timeout_ms=10000,
        )
        self.assertEqual(calls[-2:], ["page", "context"])

    def test_validate_account_state_accepts_feedback_page_url(self):
        class FakePageForValidation:
            url = "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?action=plugin_redirect&token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                return None

            def close(self):
                return None

        class FakeContextForValidation:
            def __init__(self):
                self.page = FakePageForValidation()

            def new_page(self):
                return self.page

            def close(self):
                return None

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(None, FakeContextForValidation()),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=False),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = validate_account_state(AccountConfig(name="主账号", state_path="storage/shared.json"))

        self.assertTrue(valid)

    def test_renew_account_state_persists_shared_profile_state(self):
        calls: list[str] = []

        class FakePageForValidation:
            url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                calls.append("page")

        class FakeContextForValidation:
            def __init__(self):
                self.page = FakePageForValidation()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(None, FakeContextForValidation()),
            ),
            patch("desktop_py.core.fetcher.validate_shared_browser_profile_dir", return_value="C:/profile"),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="C:/profile",
            )

        self.assertTrue(valid)
        self.assertIn("storage:storage\\shared.json:True", calls)
        self.assertEqual(calls[-2:], ["storage:storage\\shared.json:True", "context"])

    def test_renew_account_state_passes_headless_flag_to_browser_context(self):
        observed: list[object] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                return None

            def close(self):
                return None

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                return None

            def close(self):
                return None

        def fake_create_browser_context(_playwright, account, headless, profile_dir):
            observed.extend([account.name, headless, profile_dir])
            return None, FakeContextForRenew()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch("desktop_py.core.fetcher.create_browser_context", side_effect=fake_create_browser_context),
            patch("desktop_py.core.fetcher.validate_shared_browser_profile_dir", return_value="C:/profile"),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="accountA", state_path="storage/shared.json"),
                profile_dir="C:/profile",
                headless=False,
            )

        self.assertTrue(valid)
        self.assertEqual(observed, ["accountA", False, "C:/profile"])

    def test_renew_account_state_persists_regular_state_file(self):
        calls: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                calls.append("page")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="",
            )

        self.assertTrue(valid)
        self.assertIn("storage:storage\\shared.json:True", calls)
        self.assertEqual(calls[-3:], ["storage:storage\\shared.json:True", "context", "browser"])

    def test_renew_account_state_accepts_logged_in_backend_page_without_token_url(self):
        calls: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append(f"goto:{_url}")

            def wait_for_load_state(self, _state, timeout=None):
                return None

            def content(self):
                return '<div class="menu_box_account_info_item">退出登录</div>'

            def close(self):
                calls.append("page")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=False),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="",
            )

        self.assertTrue(valid)
        self.assertIn("storage:storage\\shared.json:True", calls)

    def test_renew_account_state_recovers_login_timeout_page_via_mini_program_entry(self):
        calls: list[str] = []

        class FakePageForRenew:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/"
                self.recovered = False

            def goto(self, url, wait_until=None, timeout=None):
                self.url = url
                calls.append(f"goto:{url}")

            def wait_for_load_state(self, state=None, timeout=None):
                return None

            def wait_for_timeout(self, timeout):
                return None

            def locator(self, selector, **kwargs):
                if selector == "text=登录超时，请重新登录":
                    return FakeLocator(count=0 if self.recovered else 1)
                if selector == "text=小程序":
                    return FakeLocator(count=1, click_cb=self._recover)
                if selector == "text=退出登录":
                    return FakeLocator(count=1)
                return FakeLocator()

            def content(self):
                if self.recovered:
                    return '<div class="menu_box_account_info_item">账号设置</div>'
                return "<div>登录超时，请重新登录</div><div>小程序</div><div>退出登录</div>"

            def close(self):
                calls.append("page")

            def _recover(self):
                self.recovered = True
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"
                calls.append("recover")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch(
                "desktop_py.core.fetcher.wait_for_url_contains",
                side_effect=lambda page, keywords, timeout_ms=0, is_cancelled=None: any(
                    keyword in page.url for keyword in keywords
                ),
            ),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="",
            )

        self.assertTrue(valid)
        self.assertIn("recover", calls)
        self.assertIn("storage:storage\\shared.json:True", calls)

    def test_renew_account_state_falls_back_to_saved_feedback_url(self):
        calls: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/"

            def goto(self, url, wait_until=None, timeout=None):
                self.url = url
                calls.append(f"goto:{url}")

            def close(self):
                calls.append("page")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()
        feedback_url = "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current"

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=False),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json", feedback_url=feedback_url),
                profile_dir="",
            )

        self.assertTrue(valid)
        self.assertEqual(
            calls[:2],
            [
                "goto:https://mp.weixin.qq.com/",
                f"goto:{feedback_url}",
            ],
        )
        self.assertIn("storage:storage\\shared.json:True", calls)

    def test_renew_account_state_falls_back_to_feedback_url_when_home_timeout(self):
        calls: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/"

            def goto(self, url, wait_until=None, timeout=None):
                calls.append(f"goto:{url}")
                if len(calls) == 1:
                    raise PlaywrightTimeoutError("home timeout")
                self.url = url

            def close(self):
                calls.append("page")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()
        feedback_url = "https://mp.weixin.qq.com/wxamp/frame/pluginRedirect/gameFeedback?token=current"

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=False),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json", feedback_url=feedback_url),
                profile_dir="",
            )

        self.assertTrue(valid)
        self.assertEqual(
            calls[:2],
            [
                "goto:https://mp.weixin.qq.com/",
                f"goto:{feedback_url}",
            ],
        )
        self.assertIn("storage:storage\\shared.json:True", calls)

    def test_renew_account_state_does_not_overwrite_state_when_invalid(self):
        calls: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/"

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                calls.append("page")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", side_effect=PlaywrightTimeoutError("timeout")),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                profile_dir="",
            )

        self.assertFalse(valid)
        self.assertFalse(any(call.startswith("storage:") for call in calls))

    def test_renew_account_state_logs_result(self):
        logs: list[str] = []

        class FakePageForRenew:
            url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"

            def goto(self, _url, wait_until=None, timeout=None):
                return None

            def close(self):
                return None

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                return None

            def close(self):
                return None

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(None, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.validate_shared_browser_profile_dir", return_value="C:/profile"),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()
            valid = renew_account_state(
                AccountConfig(name="主账号", state_path="storage/shared.json"),
                logger=logs.append,
                profile_dir="C:/profile",
            )

        self.assertTrue(valid)
        self.assertIn("开始自动续期账号 主账号。", logs)
        self.assertIn("账号 主账号 自动续期成功。", logs)

    def test_fetch_accounts_batch_stops_gracefully_when_cancelled(self):
        accounts = [
            AccountConfig(name="账号A", state_path="storage/a.json", is_entry_account=False),
            AccountConfig(name="账号B", state_path="storage/a.json", is_entry_account=False),
        ]
        progress_calls: list[str] = []

        class FakePageObject:
            def close(self):
                return None

        class FakeContext:
            def new_page(self):
                return FakePageObject()

            def close(self):
                return None

        fake_context = FakeContext()
        fake_browser = type("FakeBrowser", (), {"close": lambda self: None})()
        results = [
            type("Result", (), {"account_name": "账号A"})(),
            CancelledError("任务已取消"),
        ]

        def fake_fetch(page, context, account, logger, profile_dir, is_cancelled=None):
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch("desktop_py.core.fetcher.create_browser_context", return_value=(fake_browser, fake_context)),
            patch("desktop_py.core.fetcher._fetch_account_in_page", side_effect=fake_fetch),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()
            with self.assertRaisesRegex(CancelledError, "任务已取消"):
                fetch_accounts_batch(
                    accounts,
                    progress=lambda result: progress_calls.append(result.account_name),
                )

        self.assertEqual(progress_calls, ["账号A"])

    def test_validate_account_state_runs_in_helper_thread_when_asyncio_loop_exists(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json")

        async def runner():
            with patch("desktop_py.core.fetcher.validate_account_state_impl", return_value=True) as mock_impl:
                valid = validate_account_state(account)
            return valid, mock_impl.call_count

        valid, call_count = asyncio.run(runner())

        self.assertTrue(valid)
        self.assertEqual(call_count, 1)

    def test_save_login_state_runs_in_helper_thread_when_asyncio_loop_exists(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json")

        async def runner():
            with patch(
                "desktop_py.core.fetcher.save_login_state_impl", return_value="storage/shared.json"
            ) as mock_impl:
                state_path = save_login_state(account, 120)
            return state_path, mock_impl.call_count

        state_path, call_count = asyncio.run(runner())

        self.assertEqual(state_path, "storage/shared.json")
        self.assertEqual(call_count, 1)

    def test_save_login_state_with_profile_runs_in_helper_thread_when_asyncio_loop_exists(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json")

        async def runner():
            with patch(
                "desktop_py.core.fetcher.save_login_state_with_profile_impl",
                return_value="storage/shared.json",
            ) as mock_impl:
                state_path = save_login_state_with_profile(account, 120, "C:/profile")
            return state_path, mock_impl.call_count, mock_impl.call_args.args

        state_path, call_count, args = asyncio.run(runner())

        self.assertEqual(state_path, "storage/shared.json")
        self.assertEqual(call_count, 1)
        self.assertEqual(args[:3], (account, 120, "C:/profile"))

    def test_renew_account_state_runs_in_helper_thread_when_asyncio_loop_exists(self):
        account = AccountConfig(name="主账号", state_path="storage/shared.json")

        async def runner():
            with patch("desktop_py.core.fetcher.renew_account_state_impl", return_value=True) as mock_impl:
                valid = renew_account_state(account)
            return valid, mock_impl.call_count

        valid, call_count = asyncio.run(runner())

        self.assertTrue(valid)
        self.assertEqual(call_count, 1)


    def test_renew_account_state_persists_after_page_already_closed(self):
        calls: list[str] = []

        class FakePageForRenew:
            def __init__(self):
                self.url = "https://mp.weixin.qq.com/wxamp/index/index?token=1"
                self.closed = False

            def goto(self, _url, wait_until=None, timeout=None):
                calls.append("goto")

            def close(self):
                self.closed = True
                calls.append("page")

            def is_closed(self):
                return self.closed

            def wait_for_timeout(self, timeout):
                calls.append(f"wait:{timeout}")

        class FakeContextForRenew:
            def __init__(self):
                self.page = FakePageForRenew()

            def new_page(self):
                return self.page

            def storage_state(self, path=None, indexed_db=False):
                calls.append(f"storage:{path}:{indexed_db}")

            def close(self):
                calls.append("context")

        fake_browser = type("FakeBrowser", (), {"close": lambda self: calls.append("browser")})()

        with (
            patch("desktop_py.core.fetcher.sync_playwright") as mock_playwright,
            patch(
                "desktop_py.core.fetcher.create_browser_context",
                return_value=(fake_browser, FakeContextForRenew()),
            ),
            patch("desktop_py.core.fetcher.wait_for_url_contains", return_value=True),
            patch("desktop_py.core.fetcher.Path.exists", return_value=True),
        ):
            mock_playwright.return_value.__enter__.return_value = object()

            valid = renew_account_state(AccountConfig(name="accountA", state_path="storage/shared.json"), profile_dir="")

        self.assertTrue(valid)
        self.assertIn("page", calls)
        self.assertIn("storage:storage\\shared.json:True", calls)
        self.assertFalse(any(call.startswith("wait:") for call in calls))


if __name__ == "__main__":
    unittest.main()
