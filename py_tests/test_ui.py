import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from desktop_py.core.models import AccountConfig, AppSettings, FetchResult
from desktop_py.ui.account_dialog import AccountDialog
from desktop_py.ui.main_window import KEEP_ALIVE_INTERVAL_MS, MainWindow


class UiSmokeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_builds_summary_cards(self):
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual(window.table.columnCount(), 5)
        self.assertIn("total", window._summary_labels)
        expected_total = sum(1 for account in window.accounts if not account.is_entry_account)
        self.assertEqual(window._summary_labels["total"].text(), str(expected_total))
        self.assertGreaterEqual(window.table.minimumHeight(), 360)
        self.assertEqual(window.statusBar().currentMessage(), "就绪")
        self.assertIn("退款反馈抓取工作台", window.findChild(type(window._status_label), "heroTitle").text() if window.findChild(type(window._status_label), "heroTitle") else "退款反馈抓取工作台")

    def test_auto_fetch_push_switch_uses_saved_setting(self):
        with patch("desktop_py.ui.main_window.load_settings", return_value=AppSettings(auto_fetch_push_enabled=True)), patch(
            "desktop_py.ui.main_window.save_settings"
        ):
            window = MainWindow()
            self.addCleanup(window.close)

        self.assertIsNotNone(window.auto_fetch_push_switch)
        self.assertTrue(window.auto_fetch_push_switch.isChecked())

    def test_auto_validate_entry_account_skips_in_offscreen(self):
        window = MainWindow()
        self.addCleanup(window.close)

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._auto_validate_entry_account()

        mock_run_thread.assert_not_called()

    def test_auto_validate_entry_account_marks_pending_before_thread(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "windows"}):
            window = MainWindow()
            self.addCleanup(window.close)
            window.accounts = [
                AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, last_status="登录有效"),
            ]

            with patch.object(window, "_run_thread") as mock_run_thread:
                window._auto_validate_entry_account()

            self.assertEqual(window.accounts[0].last_status, "检测中")
            mock_run_thread.assert_called_once()

    def test_window_hides_minimize_and_maximize_buttons(self):
        window = MainWindow()
        self.addCleanup(window.close)

        flags = window.windowFlags()

        self.assertFalse(bool(flags & Qt.WindowType.WindowMinimizeButtonHint))
        self.assertFalse(bool(flags & Qt.WindowType.WindowMaximizeButtonHint))

    def test_close_button_hides_window_when_tray_visible(self):
        window = MainWindow()
        self.addCleanup(window.close)
        tray = QSystemTrayIcon()
        tray.setVisible(True)
        window.tray_icon = tray
        window.show()
        self.app.processEvents()

        event = QCloseEvent()
        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertFalse(window.isVisible())

    def test_request_exit_hides_tray_and_quits_app(self):
        window = MainWindow()
        self.addCleanup(window.close)

        class FakeTray:
            def __init__(self):
                self.hidden = False

            def hide(self):
                self.hidden = True

        class FakeApp:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        fake_tray = FakeTray()
        fake_app = FakeApp()
        window.tray_icon = fake_tray

        with patch("desktop_py.ui.main_window.QApplication.instance", return_value=fake_app), patch.object(window, "close") as mock_close:
            window.request_exit()

        self.assertTrue(window._allow_close)
        self.assertTrue(fake_tray.hidden)
        mock_close.assert_called_once()
        self.assertTrue(fake_app.quit_called)

    def test_summary_cards_exclude_entry_account(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True, last_status="登录有效"),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True, last_status="抓取成功", last_fetch_at="2026-04-17 20:18:46"),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False, enabled=False, last_status="抓取失败"),
        ]

        window.refresh_table()

        self.assertEqual(window._summary_labels["total"].text(), "2")
        self.assertEqual(window._summary_labels["enabled"].text(), "1")
        self.assertEqual(window._summary_labels["healthy"].text(), "1")
        self.assertEqual(window._summary_labels["recent"].text(), "2026-04-17 20:18:46")

    def test_validation_success_shows_completed_result(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, last_status="登录有效"),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 3).text(), "完成")

    def test_pending_validation_shows_empty_result(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, last_status="检测中"),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 3).text(), "")

    def test_fetch_success_without_deadline_shows_no_pending_and_completed(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取成功", last_deadline="", last_note="当前账号无待处理申请。"),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 1).text(), "无待处理")
        self.assertEqual(window.table.item(0, 3).text(), "完成")
        self.assertEqual(window.table.item(0, 1).toolTip(), "无待处理")

    def test_fetch_failure_shows_reason_in_deadline_column(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取失败", last_note="切换账号列表中未找到目标账号"),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 1).text(), "切换账号列表中未找到目标账号")
        self.assertEqual(window.table.item(0, 3).text(), "失败")
        self.assertEqual(window.table.item(0, 1).toolTip(), "切换账号列表中未找到目标账号")

    def test_no_business_page_failure_shows_short_description(self):
        window = MainWindow()
        self.addCleanup(window.close)
        reason = "页面未出现业务 iframe，可能是链接失效、无权限或登录态失效。"
        window.accounts = [
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取失败", last_note=reason),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 1).text(), "无业面")
        self.assertEqual(window.table.item(0, 3).text(), "失败")
        self.assertEqual(window.table.item(0, 1).toolTip(), reason)

    def test_mark_validation_uses_short_status_text(self):
        window = MainWindow()
        self.addCleanup(window.close)
        account = AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True)
        window.accounts = [account]

        with patch("desktop_py.ui.main_window.save_accounts"):
            window._mark_validation(account, True)
            self.assertEqual(account.last_status, "登录有效")

            window._mark_validation(account, False)
            self.assertEqual(account.last_status, "登录失效")

    def test_refresh_table_selects_entry_account_by_default(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
        ]
        window.table.clearSelection()

        window.refresh_table()

        self.assertEqual(window.selected_index(), 0)
        self.assertTrue(window.selected_account().is_entry_account)

    def test_account_dialog_builds_account(self):
        dialog = AccountDialog(AccountConfig(name="演示账号", state_path="storage/demo.json"))
        account = dialog.build_account()

        self.assertEqual(account.name, "演示账号")
        self.assertEqual(account.state_path, "storage/demo.json")
        self.assertTrue(account.is_entry_account)

    def test_browse_button_enabled_only_when_profile_input_focused(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()

        self.assertFalse(window.browse_profile_button.isEnabled())

        window.profile_dir_edit.setFocus()
        self.app.processEvents()
        self.assertTrue(window.browse_profile_button.isEnabled())

        window.browse_profile_button.setFocus()
        self.app.processEvents()
        self.assertTrue(window.browse_profile_button.isEnabled())

        window.webhook_edit.setFocus()
        self.app.processEvents()
        self.assertFalse(window.browse_profile_button.isEnabled())

    def test_imported_account_cannot_save_login_state(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="入口账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(1)

        with patch.object(window, "_show_info") as mock_information, patch.object(window, "_run_thread") as mock_run_thread:
            window.login_selected()

        mock_information.assert_called_once()
        self.assertIn("导入账号不能直接保存登录态", mock_information.call_args.args[1])
        mock_run_thread.assert_not_called()

    def test_login_selected_logs_clear_start_message_for_independent_window(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="入口账号", state_path="storage/shared.json", is_entry_account=True),
        ]
        window.settings.browser_profile_dir = ""
        window.refresh_table()

        with patch.object(window, "_run_thread") as mock_run_thread:
            window.login_selected()

        self.assertIn("正在为账号 入口账号 打开独立登录窗口", window.log_edit.toPlainText())
        mock_run_thread.assert_called_once()

    def test_login_selected_logs_clear_start_message_for_shared_profile(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="入口账号", state_path="storage/shared.json", is_entry_account=True),
        ]
        window.settings.browser_profile_dir = "C:/browser_profile"
        window.refresh_table()

        with patch.object(window, "_run_thread") as mock_run_thread:
            window.login_selected()

        self.assertIn("正在为账号 入口账号 打开共享浏览器资料目录", window.log_edit.toPlainText())
        mock_run_thread.assert_called_once()

    def test_mark_login_updates_note_and_log(self):
        window = MainWindow()
        self.addCleanup(window.close)
        account = AccountConfig(name="入口账号", state_path="storage/shared.json", is_entry_account=True)
        window.accounts = [account]

        with patch("desktop_py.ui.main_window.save_accounts"):
            window._mark_login(account)

        self.assertEqual(account.last_status, "已保存登录态")
        self.assertEqual(account.last_note, "可继续导入账号或直接抓取")
        self.assertIn("登录态已保存完成", window.log_edit.toPlainText())

    def test_login_button_enabled_only_for_entry_account(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="入口账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()

        self.assertTrue(window.login_button.isEnabled())
        self.assertTrue(window.edit_button.isEnabled())
        self.assertTrue(window.import_button.isEnabled())
        self.assertTrue(window.validate_button.isEnabled())
        self.assertFalse(window.fetch_selected_button.isEnabled())
        self.assertFalse(window.stop_fetch_button.isEnabled())
        self.assertTrue(window.delete_button.isEnabled())

        window.table.selectRow(1)
        self.assertFalse(window.login_button.isEnabled())
        self.assertFalse(window.edit_button.isEnabled())
        self.assertFalse(window.import_button.isEnabled())
        self.assertFalse(window.validate_button.isEnabled())
        self.assertTrue(window.fetch_selected_button.isEnabled())
        self.assertFalse(window.stop_fetch_button.isEnabled())
        self.assertTrue(window.delete_button.isEnabled())

    def test_multi_selection_disables_single_account_actions(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()

        window.table.selectRow(1)
        window.table.selectionModel().select(
            window.table.model().index(2, 0),
            window.table.selectionModel().SelectionFlag.Select | window.table.selectionModel().SelectionFlag.Rows,
        )

        self.assertFalse(window.login_button.isEnabled())
        self.assertFalse(window.edit_button.isEnabled())
        self.assertFalse(window.import_button.isEnabled())
        self.assertFalse(window.validate_button.isEnabled())
        self.assertFalse(window.fetch_selected_button.isEnabled())
        self.assertFalse(window.stop_fetch_button.isEnabled())
        self.assertTrue(window.delete_button.isEnabled())

    def test_imported_account_cannot_edit(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(1)

        with patch.object(window, "_show_info") as mock_information:
            window.edit_account()

        mock_information.assert_called_once()
        self.assertIn("导入账号不允许编辑", mock_information.call_args.args[1])

    def test_imported_account_cannot_validate_login_state(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(1)

        with patch.object(window, "_show_info") as mock_information, patch.object(window, "_run_thread") as mock_run_thread:
            window.validate_selected()

        mock_information.assert_called_once()
        self.assertIn("导入账号不能校验登录态", mock_information.call_args.args[1])
        mock_run_thread.assert_not_called()

    def test_imported_account_cannot_import_accounts(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(1)

        with patch.object(window, "_show_info") as mock_information, patch.object(window, "_run_thread") as mock_run_thread:
            window.import_accounts()

        mock_information.assert_called_once()
        self.assertIn("只有主账号可以导入账号列表", mock_information.call_args.args[1])
        mock_run_thread.assert_not_called()

    def test_send_summary_uses_current_webhook_without_saving_settings(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True, last_status="抓取成功", last_deadline="2026-04-20 11:42:31"),
        ]
        window.webhook_edit.setText("https://open.feishu.cn/open-apis/bot/v2/hook/demo")

        with patch("desktop_py.ui.main_window.save_settings") as mock_save_settings, patch.object(window, "_run_thread") as mock_run_thread:
            window.send_summary()

        mock_save_settings.assert_not_called()
        self.assertEqual(window.settings.feishu_webhook, "https://open.feishu.cn/open-apis/bot/v2/hook/demo")
        mock_run_thread.assert_called_once()

    def test_send_summary_preserves_actual_account_name_in_summary(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(
                name="导入账号A",
                state_path="storage/shared.json",
                is_entry_account=False,
                enabled=True,
                last_status="抓取成功",
                last_deadline="2026-04-20 11:42:31",
                last_note="已完成详情页抓取。；当前实际账号：实际账号A",
            ),
        ]
        captured_results = []

        def fake_build_summary(results):
            captured_results.extend(results)
            return "summary"

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._send_summary_with_webhook("https://example.com/hook")

        job = mock_run_thread.call_args.args[0]
        with patch("desktop_py.ui.main_window.build_summary", side_effect=fake_build_summary), patch(
            "desktop_py.ui.main_window.send_feishu_text"
        ):
            job(lambda _message: None)
        self.assertEqual(captured_results[0].actual_account_name, "实际账号A")

    def test_auto_fetch_and_send_uses_fetch_job_and_progress_callback(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        window.webhook_edit.setText("https://open.feishu.cn/open-apis/bot/v2/hook/demo")

        with patch.object(window, "_run_thread") as mock_run_thread:
            window.auto_fetch_and_send()

        mock_run_thread.assert_called_once()
        self.assertEqual(mock_run_thread.call_args.kwargs["on_progress"], window._mark_fetch_progress)

    def test_build_fetch_job_uses_batch_fetcher(self):
        window = MainWindow()
        self.addCleanup(window.close)
        accounts = [
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        job = window._build_fetch_job(accounts)

        with patch("desktop_py.ui.main_window.fetch_accounts_batch", return_value=[]) as mock_batch:
            result = job(lambda _message: None, lambda _payload: None)

        self.assertEqual(result, [])
        mock_batch.assert_called_once()

    def test_actions_include_single_run_fetch_and_push_button(self):
        window = MainWindow()
        self.addCleanup(window.close)

        buttons = [button.text() for button in window.findChildren(type(window.login_button)) if button.text()]

        self.assertIn("抓取并推送", buttons)
        self.assertIn("停止抓取", buttons)
        self.assertNotIn("抓取全部", buttons)

    def test_send_summary_button_moves_to_fetch_all_slot(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()

        self.assertIsNotNone(window.send_summary_button)
        self.assertIsNotNone(window.fetch_selected_button)
        self.assertIsNotNone(window.auto_fetch_push_switch)
        self.assertGreater(window.send_summary_button.x(), window.fetch_selected_button.x())
        self.assertLess(window.send_summary_button.x(), window.auto_fetch_push_switch.x())

    def test_auto_fetch_and_send_button_moves_to_previous_send_summary_slot(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()

        auto_fetch_button = next(button for button in window.findChildren(type(window.login_button)) if button.text() == "抓取并推送")
        self.assertIsNotNone(window.send_summary_button)
        self.assertIsNotNone(window.auto_fetch_push_switch)
        self.assertGreater(auto_fetch_button.x(), window.send_summary_button.x())
        self.assertLess(auto_fetch_button.x(), window.auto_fetch_push_switch.x())

    def test_toggle_auto_fetch_push_saves_setting_and_reschedules(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.auto_fetch_push_switch.setChecked(False)

        with patch("desktop_py.ui.main_window.save_settings") as mock_save_settings, patch.object(window, "_apply_auto_fetch_push_schedule") as mock_schedule:
            window.auto_fetch_push_switch.setChecked(True)

        self.assertTrue(window.settings.auto_fetch_push_enabled)
        mock_save_settings.assert_called_once()
        mock_schedule.assert_called_once()

    def test_save_current_settings_rejects_invalid_shared_profile_dir(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.profile_dir_edit.setText("C:/Users/Tester/AppData/Local/Google/Chrome/User Data")

        with patch("desktop_py.ui.main_window.validate_shared_browser_profile_dir", side_effect=ValueError("共享浏览器资料目录不能直接指向 Chrome 或 Edge 的默认用户资料目录，请改用专用自动化目录。")), patch(
            "desktop_py.ui.main_window.save_settings"
        ) as mock_save_settings, patch.object(window, "_show_warning") as mock_warning:
            window.save_current_settings()

        mock_save_settings.assert_not_called()
        mock_warning.assert_called_once()
        self.assertIn("默认用户资料目录", mock_warning.call_args.args[1])

    def test_save_current_settings_preserves_headless_fetch_value(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.settings.headless_fetch = False

        with patch("desktop_py.ui.main_window.validate_shared_browser_profile_dir", return_value=""), patch(
            "desktop_py.ui.main_window.save_settings"
        ):
            window.save_current_settings()

        self.assertFalse(window.settings.headless_fetch)

    def test_milliseconds_until_next_auto_fetch_push_before_nine(self):
        window = MainWindow()
        self.addCleanup(window.close)

        milliseconds = window._milliseconds_until_next_auto_fetch_push(datetime(2026, 4, 18, 8, 30, 0))

        self.assertEqual(milliseconds, 30 * 60 * 1000)

    def test_milliseconds_until_next_auto_fetch_push_after_nine(self):
        window = MainWindow()
        self.addCleanup(window.close)

        milliseconds = window._milliseconds_until_next_auto_fetch_push(datetime(2026, 4, 18, 9, 30, 0))

        self.assertEqual(milliseconds, int(23.5 * 60 * 60 * 1000))

    def test_handle_auto_fetch_push_timeout_reschedules_and_runs_job(self):
        window = MainWindow()
        self.addCleanup(window.close)

        with patch.object(window, "_apply_auto_fetch_push_schedule") as mock_schedule, patch.object(window, "_run_auto_fetch_push") as mock_run:
            window._handle_auto_fetch_push_timeout()

        mock_schedule.assert_called_once()
        mock_run.assert_called_once()

    def test_keep_alive_interval_is_five_hours(self):
        self.assertEqual(KEEP_ALIVE_INTERVAL_MS, 5 * 60 * 60 * 1000)

    def test_handle_keep_alive_timeout_reschedules_and_runs_job(self):
        window = MainWindow()
        self.addCleanup(window.close)

        with patch.object(window, "_apply_keep_alive_schedule") as mock_schedule, patch.object(window, "_run_keep_alive") as mock_run:
            window._handle_keep_alive_timeout()

        mock_schedule.assert_called_once()
        mock_run.assert_called_once()

    def test_run_keep_alive_uses_entry_account(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
        ]

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._run_keep_alive()

        mock_run_thread.assert_called_once()
        job = mock_run_thread.call_args.args[0]
        with patch("desktop_py.ui.main_window.keep_alive_account_state", return_value=True) as mock_keep_alive:
            self.assertTrue(job(lambda _message: None))
        self.assertEqual(mock_keep_alive.call_args.args[0].name, "主账号")

    def test_run_keep_alive_skips_when_background_task_exists(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window._threads.append(object())
        window._update_action_buttons()

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._run_keep_alive()

        mock_run_thread.assert_not_called()
        self.assertIn("当前存在后台任务", window.log_edit.toPlainText())

    def test_stop_fetch_button_enabled_when_background_task_exists(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window._threads.append(object())

        window._update_action_buttons()

        self.assertTrue(window.stop_fetch_button.isEnabled())

    def test_stop_fetching_terminates_running_threads(self):
        window = MainWindow()
        self.addCleanup(window.close)
        calls: list[str] = []

        class FakeThread:
            def requestInterruption(self):
                calls.append("interrupt")

            def wait(self, timeout):
                calls.append(f"wait:{timeout}")
                return True

        window._threads = [FakeThread()]
        window._update_action_buttons()

        window.stop_fetching()

        self.assertEqual(calls, ["interrupt", "wait:2000"])
        self.assertEqual(window._threads, [])
        self.assertFalse(window.stop_fetch_button.isEnabled())
        self.assertIn("已请求停止当前后台抓取任务", window.log_edit.toPlainText())

    def test_run_auto_fetch_push_requires_webhook(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        window.webhook_edit.setText("")
        window.settings.feishu_webhook = ""

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._run_auto_fetch_push()

        mock_run_thread.assert_not_called()
        self.assertIn("未配置飞书 Webhook", window.log_edit.toPlainText())

    def test_run_auto_fetch_push_uses_saved_webhook_and_progress_callback(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
        ]
        window.settings.feishu_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/demo"
        window.webhook_edit.setText("")

        with patch.object(window, "_run_thread") as mock_run_thread:
            window._run_auto_fetch_push()

        mock_run_thread.assert_called_once()
        self.assertEqual(mock_run_thread.call_args.kwargs["on_progress"], window._mark_fetch_progress)

    def test_select_imported_accounts_selects_all_imported_rows(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()

        window.select_imported_accounts()

        self.assertEqual(window.selected_indexes(), [1, 2])

    def test_ctrl_a_does_not_select_all_rows(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

        window.table.keyPressEvent(event)

        self.assertEqual(window.selected_indexes(), [0])

    def test_delete_account_supports_batch_delete(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.select_imported_accounts()

        with patch("desktop_py.ui.main_window.MessageDialog.ask_confirm", return_value=True) as mock_confirm, patch("desktop_py.ui.main_window.save_accounts") as mock_save:
            window.delete_account()

        self.assertEqual([account.name for account in window.accounts], ["主账号"])
        mock_confirm.assert_called_once()
        mock_save.assert_called_once()

    def test_delete_account_cancel_keeps_accounts(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(1)

        with patch("desktop_py.ui.main_window.MessageDialog.ask_confirm", return_value=False) as mock_confirm, patch("desktop_py.ui.main_window.save_accounts") as mock_save:
            window.delete_account()

        self.assertEqual([account.name for account in window.accounts], ["主账号", "导入账号A"])
        mock_confirm.assert_called_once()
        mock_save.assert_not_called()

    def test_entry_account_cannot_fetch_selected(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        window.refresh_table()
        window.table.selectRow(0)

        with patch.object(window, "_show_info") as mock_information, patch.object(window, "_run_thread") as mock_run_thread:
            window.fetch_selected()

        mock_information.assert_called_once()
        self.assertIn("主账号不参与抓取", mock_information.call_args.args[1])
        mock_run_thread.assert_not_called()

    def test_fetch_all_skips_entry_account(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False, enabled=True),
            AccountConfig(name="导入账号B", state_path="storage/shared.json", is_entry_account=False, enabled=False),
        ]

        with patch.object(window, "_run_thread") as mock_run_thread:
            window.fetch_all()

        mock_run_thread.assert_called_once()
        self.assertEqual(mock_run_thread.call_args.kwargs["on_progress"], window._mark_fetch_progress)

    def test_fetch_all_requires_imported_accounts(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True, enabled=True),
        ]

        with patch.object(window, "_show_info") as mock_information, patch.object(window, "_run_thread") as mock_run_thread:
            window.fetch_all()

        mock_information.assert_called_once()
        self.assertIn("没有可抓取的导入账号", mock_information.call_args.args[1])
        mock_run_thread.assert_not_called()

    def test_entry_account_row_shows_current_main_account(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        with patch("desktop_py.ui.main_window.save_settings"):
            window._update_current_main_account("七色花消消乐")
        window.refresh_table()

        self.assertEqual(window.table.item(0, 0).text(), "主账号状态：七色花消消乐")
        self.assertEqual(window.table.item(1, 0).text(), "导入账号")

    def test_deadline_accounts_are_pinned_and_sorted_by_nearest_time(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="无截止账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取成功"),
            AccountConfig(name="较远截止账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取成功", last_deadline="2026-04-25 12:00:00"),
            AccountConfig(name="较近截止账号", state_path="storage/shared.json", is_entry_account=False, last_status="抓取成功", last_deadline="2026-04-19 09:00:00"),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 0).text(), "主账号状态：未记录")
        self.assertEqual(window.table.item(1, 0).text(), "较近截止账号")
        self.assertEqual(window.table.item(2, 0).text(), "较远截止账号")
        self.assertEqual(window.table.item(3, 0).text(), "无截止账号")

    def test_mark_fetch_progress_updates_account_row_immediately(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
        ]

        with patch("desktop_py.ui.main_window.save_accounts"), patch("desktop_py.ui.main_window.save_settings"):
            window._mark_fetch_progress(
                FetchResult(
                    account_name="导入账号A",
                    ok=True,
                    actual_account_name="萌萌连消",
                    deadline_text="2026-04-18 10:30:00",
                    note="已完成详情页抓取。",
                    page_url="https://example.com/detail",
                )
            )

        self.assertEqual(window.table.item(1, 1).text(), "2026-04-18 10:30:00")
        self.assertEqual(window.table.item(1, 2).text(), "抓取成功")
        self.assertEqual(window.table.item(1, 3).text(), "完成")

    def test_mark_fetch_progress_updates_main_account_name_immediately(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号A", state_path="storage/shared.json", is_entry_account=False),
        ]

        with patch("desktop_py.ui.main_window.save_accounts"), patch("desktop_py.ui.main_window.save_settings"):
            window._mark_fetch_progress(
                FetchResult(
                    account_name="导入账号A",
                    ok=True,
                    actual_account_name="萌萌连消",
                    deadline_text="",
                    note="当前账号无待处理申请。",
                    page_url="https://example.com/detail",
                )
            )

        self.assertEqual(window.table.item(0, 0).text(), "主账号状态：萌萌连消")

    def test_entry_account_name_aligns_left_and_imported_account_stays_centered(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
            AccountConfig(name="导入账号", state_path="storage/shared.json", is_entry_account=False),
        ]
        with patch("desktop_py.ui.main_window.save_settings"):
            window._update_current_main_account("七色花消消乐")

        window.refresh_table()

        self.assertEqual(
            window.table.item(0, 0).textAlignment(),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        )
        self.assertEqual(
            window.table.item(1, 0).textAlignment(),
            int(Qt.AlignmentFlag.AlignCenter),
        )

    def test_entry_account_deadline_shows_placeholder(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.accounts = [
            AccountConfig(name="主账号", state_path="storage/shared.json", is_entry_account=True),
        ]

        window.refresh_table()

        self.assertEqual(window.table.item(0, 1).text(), "--")

    def test_init_clears_persisted_current_main_account_name(self):
        with patch("desktop_py.ui.main_window.load_settings", return_value=AppSettings(current_main_account_name="强强")), patch(
            "desktop_py.ui.main_window.save_settings"
        ) as mock_save_settings:
            window = MainWindow()
            self.addCleanup(window.close)

        self.assertEqual(window.settings.current_main_account_name, "")
        mock_save_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
