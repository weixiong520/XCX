import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_py.core.browser_runtime import (
    DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS,
    configure_playwright_environment,
    install_playwright_browsers,
    playwright_browsers_ready,
    playwright_install_command,
    playwright_install_environment,
    required_browser_directories,
)


class BrowserRuntimeTestCase(unittest.TestCase):
    def test_configure_playwright_environment_points_to_runtime_root(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("desktop_py.core.browser_runtime.runtime_root", return_value=root):
                target = configure_playwright_environment()

            self.assertEqual(target, root / "ms-playwright")

    def test_required_browser_directories_reads_browsers_json(self):
        names = required_browser_directories()

        self.assertIn("chromium-1208", names)
        self.assertIn("chromium_headless_shell-1208", names)
        self.assertIn("ffmpeg-1011", names)

    def test_playwright_browsers_ready_checks_required_directories(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011"):
                (root / name).mkdir()

            with (
                patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=root),
                patch(
                    "desktop_py.core.browser_runtime.required_browser_directories",
                    return_value=["chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011"],
                ),
            ):
                self.assertTrue(playwright_browsers_ready())

            (root / "ffmpeg-1011").rmdir()
            with (
                patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=root),
                patch(
                    "desktop_py.core.browser_runtime.required_browser_directories",
                    return_value=["chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011"],
                ),
            ):
                self.assertFalse(playwright_browsers_ready())

    def test_playwright_browsers_ready_returns_false_when_metadata_missing(self):
        with TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "package"
            package_root.mkdir()

            with (
                patch("desktop_py.core.browser_runtime.browser_archive_root", return_value=package_root),
                patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=Path(temp_dir)),
            ):
                self.assertFalse(playwright_browsers_ready())

    def test_playwright_browsers_ready_returns_false_when_metadata_is_invalid_json(self):
        with TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "package"
            package_root.mkdir()
            (package_root / "browsers.json").write_text("{invalid", encoding="utf-8")

            with (
                patch("desktop_py.core.browser_runtime.browser_archive_root", return_value=package_root),
                patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=Path(temp_dir)),
            ):
                self.assertFalse(playwright_browsers_ready())

    def test_playwright_browsers_ready_returns_false_when_metadata_shape_changes(self):
        with TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "package"
            package_root.mkdir()
            (package_root / "browsers.json").write_text('{"unexpected":[]}', encoding="utf-8")

            with (
                patch("desktop_py.core.browser_runtime.browser_archive_root", return_value=package_root),
                patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=Path(temp_dir)),
            ):
                self.assertFalse(playwright_browsers_ready())

    def test_playwright_install_command_uses_python_in_source_mode(self):
        command = playwright_install_command()
        self.assertEqual(command[1:], ["-m", "playwright", "install", "chromium"])

    def test_playwright_install_command_uses_bundled_node_when_frozen(self):
        with patch(
            "desktop_py.core.browser_runtime.sys",
            frozen=True,
            executable=r"C:\\app\\tool.exe",
            _MEIPASS=r"C:\\app\\_internal",
        ):
            command = playwright_install_command()

        self.assertEqual(command[0], r"C:\app\_internal\playwright\driver\node.exe")
        self.assertEqual(command[1], r"C:\app\_internal\playwright\driver\package\cli.js")
        self.assertEqual(command[2:], ["install", "chromium"])

    def test_playwright_install_environment_uses_official_source_by_default(self):
        with TemporaryDirectory() as temp_dir, patch.dict("desktop_py.core.browser_runtime.os.environ", {}, clear=True):
            target = Path(temp_dir) / "ms-playwright"
            env = playwright_install_environment(target)

            self.assertEqual(env["PLAYWRIGHT_BROWSERS_PATH"], str(target))
            self.assertNotIn("PLAYWRIGHT_DOWNLOAD_HOST", env)
            self.assertNotIn("PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST", env)
            self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"], DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS)

    def test_playwright_install_environment_keeps_custom_mirror(self):
        with (
            TemporaryDirectory() as temp_dir,
            patch.dict(
                "desktop_py.core.browser_runtime.os.environ",
                {
                    "PLAYWRIGHT_DOWNLOAD_HOST": "https://example.com/playwright",
                    "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "300000",
                },
                clear=True,
            ),
        ):
            env = playwright_install_environment(Path(temp_dir) / "ms-playwright")

            self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_HOST"], "https://example.com/playwright")
            self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"], "300000")

    def test_playwright_install_environment_keeps_chromium_specific_mirror(self):
        with (
            TemporaryDirectory() as temp_dir,
            patch.dict(
                "desktop_py.core.browser_runtime.os.environ",
                {"PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST": "https://example.com/chromium"},
                clear=True,
            ),
        ):
            env = playwright_install_environment(Path(temp_dir) / "ms-playwright")

            self.assertNotIn("PLAYWRIGHT_DOWNLOAD_HOST", env)
            self.assertEqual(env["PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST"], "https://example.com/chromium")

    def test_install_playwright_browsers_uses_single_official_install_attempt(self):
        call_envs: list[dict[str, str]] = []

        def fake_run(env, logger=None):
            call_envs.append(dict(env))
            return True, "ok"

        logs: list[str] = []
        with (
            TemporaryDirectory() as temp_dir,
            patch(
                "desktop_py.core.browser_runtime.configure_playwright_environment",
                return_value=Path(temp_dir) / "ms-playwright",
            ),
            patch("desktop_py.core.browser_runtime._run_playwright_install", side_effect=fake_run),
        ):
            ok, output = install_playwright_browsers(logs.append)

        self.assertTrue(ok)
        self.assertEqual(output, "ok")
        self.assertEqual(len(call_envs), 1)
        self.assertNotIn("PLAYWRIGHT_DOWNLOAD_HOST", call_envs[0])
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
