import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_py.core.models import AccountConfig
from desktop_py.core.store import (
    SHARED_BROWSER_PROFILE_DIR_NAME,
    account_output_file,
    account_state_path,
    load_accounts,
    load_settings,
    prepare_shared_browser_profile_dir,
    runtime_root,
    save_settings,
    validate_shared_browser_profile_dir,
    write_account_output_json,
    write_account_output_text,
)


class StoreTestCase(unittest.TestCase):
    def test_account_state_path(self):
        path = account_state_path("账号 A-1")
        self.assertTrue(path.endswith("storage\\账号_A_1.json") or path.endswith("storage/账号_A_1.json"))

    def test_account_dict(self):
        account = AccountConfig(name="测试账号", state_path="storage/test.json")
        self.assertEqual(account.to_dict()["name"], "测试账号")
        self.assertTrue(account.to_dict()["is_entry_account"])

    def test_load_settings_defaults_auto_fetch_push_when_missing(self):
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text('{"feishu_webhook":"demo"}\n', encoding="utf-8")

            with (
                patch("desktop_py.core.store.SETTINGS_FILE", settings_path),
                patch("desktop_py.core.store.ensure_runtime_dirs"),
            ):
                settings = load_settings()

        self.assertFalse(settings.auto_fetch_push_enabled)

    def test_load_settings_supports_utf8_bom(self):
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text('{"feishu_webhook":"demo"}\n', encoding="utf-8-sig")

            with (
                patch("desktop_py.core.store.SETTINGS_FILE", settings_path),
                patch("desktop_py.core.store.ensure_runtime_dirs"),
            ):
                settings = load_settings()

        self.assertEqual(settings.feishu_webhook, "demo")

    def test_load_settings_keeps_persisted_login_wait_seconds(self):
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text('{"login_wait_seconds":45}\n', encoding="utf-8")

            with (
                patch("desktop_py.core.store.SETTINGS_FILE", settings_path),
                patch("desktop_py.core.store.ensure_runtime_dirs"),
            ):
                settings = load_settings()

        self.assertEqual(settings.login_wait_seconds, 45)

    def test_load_accounts_supports_utf8_bom(self):
        with TemporaryDirectory() as temp_dir:
            accounts_path = Path(temp_dir) / "accounts.json"
            accounts_path.write_text('[{"name":"测试账号","state_path":"storage/test.json"}]\n', encoding="utf-8-sig")

            with (
                patch("desktop_py.core.store.ACCOUNTS_FILE", accounts_path),
                patch("desktop_py.core.store.ensure_runtime_dirs"),
            ):
                accounts = load_accounts()

        self.assertEqual(accounts[0].name, "测试账号")

    def test_save_settings_persists_auto_fetch_push_enabled(self):
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text("{}\n", encoding="utf-8")

            with (
                patch("desktop_py.core.store.SETTINGS_FILE", settings_path),
                patch("desktop_py.core.store.ensure_runtime_dirs"),
            ):
                save_settings(load_settings())
                settings = load_settings()
                settings.auto_fetch_push_enabled = True
                save_settings(settings)

            content = settings_path.read_text(encoding="utf-8")

        self.assertIn('"auto_fetch_push_enabled": true', content)

    def test_runtime_root_uses_executable_directory_when_frozen(self):
        with (
            patch("desktop_py.core.store.os.access", return_value=True),
            patch("desktop_py.core.store.sys", frozen=True, executable=r"C:\\portable\\小程序工具\\小程序工具.exe"),
        ):
            root = runtime_root()

        self.assertEqual(root, Path(r"C:\portable\小程序工具"))

    def test_runtime_root_falls_back_to_local_appdata_when_frozen_dir_not_writable(self):
        fake_env = {"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"}
        with (
            patch("desktop_py.core.store.os.access", return_value=False),
            patch(
                "desktop_py.core.store.sys", frozen=True, executable=r"C:\\Program Files\\小程序工具\\小程序工具.exe"
            ),
            patch.dict("desktop_py.core.store.os.environ", fake_env, clear=True),
        ):
            root = runtime_root()

        self.assertEqual(root, Path(r"C:\Users\Tester\AppData\Local\小程序工具"))

    def test_validate_shared_browser_profile_dir_accepts_empty_value(self):
        self.assertEqual(validate_shared_browser_profile_dir(""), "")

    def test_validate_shared_browser_profile_dir_rejects_default_user_data_dir(self):
        with TemporaryDirectory() as temp_dir:
            profile_root = Path(temp_dir) / "User Data"
            profile_root.mkdir()
            (profile_root / "Local State").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "默认用户资料目录"):
                validate_shared_browser_profile_dir(str(profile_root))

    def test_validate_shared_browser_profile_dir_rejects_locked_dir(self):
        with TemporaryDirectory() as temp_dir:
            profile_root = Path(temp_dir) / "automation"
            profile_root.mkdir()
            (profile_root / "SingletonLock").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "正被浏览器占用"):
                validate_shared_browser_profile_dir(str(profile_root))

    def test_validate_shared_browser_profile_dir_returns_resolved_path(self):
        with TemporaryDirectory() as temp_dir:
            profile_root = Path(temp_dir) / "automation"
            profile_root.mkdir()

            validated = validate_shared_browser_profile_dir(str(profile_root))

        self.assertEqual(validated, str(profile_root.resolve()))

    def test_prepare_shared_browser_profile_dir_creates_dedicated_child_dir(self):
        with TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            prepared = prepare_shared_browser_profile_dir(str(parent))
            expected = parent / SHARED_BROWSER_PROFILE_DIR_NAME

            self.assertTrue(expected.is_dir())
            self.assertEqual(prepared, str(expected.resolve()))

    def test_prepare_shared_browser_profile_dir_does_not_nest_dedicated_dir(self):
        with TemporaryDirectory() as temp_dir:
            dedicated = Path(temp_dir) / SHARED_BROWSER_PROFILE_DIR_NAME
            dedicated.mkdir()

            prepared = prepare_shared_browser_profile_dir(str(dedicated))

        self.assertEqual(prepared, str(dedicated.resolve()))

    def test_prepare_shared_browser_profile_dir_rejects_file_parent(self):
        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "not-dir.txt"
            file_path.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "父目录必须是文件夹"):
                prepare_shared_browser_profile_dir(str(file_path))

    def test_account_output_file_uses_safe_account_dir(self):
        path = account_output_file("账号 A-1", "result.json")

        self.assertTrue(
            str(path).endswith("output\\desktop_py\\账号_A_1\\result.json")
            or str(path).endswith("output/desktop_py/账号_A_1/result.json")
        )

    def test_write_account_output_text_creates_named_file(self):
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "output"
            with patch("desktop_py.core.store.PY_OUTPUT_DIR", output_root):
                write_account_output_text("测试账号", "note.txt", "内容")

                target = output_root / "测试账号" / "note.txt"
                self.assertEqual(target.read_text(encoding="utf-8"), "内容")

    def test_write_account_output_json_creates_named_file(self):
        with TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "output"
            with patch("desktop_py.core.store.PY_OUTPUT_DIR", output_root):
                write_account_output_json("测试账号", "payload.json", {"ok": True})

                target = output_root / "测试账号" / "payload.json"
                self.assertIn('"ok": true', target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
