import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_py.core.browser_runtime import (
    DEFAULT_PLAYWRIGHT_DOWNLOAD_HOST,
    DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS,
    configure_playwright_environment,
    playwright_install_environment,
    playwright_install_command,
    playwright_browsers_ready,
    required_browser_directories,
)


class BrowserRuntimeTestCase(unittest.TestCase):
    def test_configure_playwright_environment_points_to_runtime_root(self):
        with patch("desktop_py.core.browser_runtime.runtime_root", return_value=Path(r"C:\portable\小程序工具")):
            target = configure_playwright_environment()

        self.assertEqual(target, Path(r"C:\portable\小程序工具\ms-playwright"))

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

            with patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=root), patch(
                "desktop_py.core.browser_runtime.required_browser_directories",
                return_value=["chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011"],
            ):
                self.assertTrue(playwright_browsers_ready())

            (root / "ffmpeg-1011").rmdir()
            with patch("desktop_py.core.browser_runtime.configure_playwright_environment", return_value=root), patch(
                "desktop_py.core.browser_runtime.required_browser_directories",
                return_value=["chromium-1208", "chromium_headless_shell-1208", "ffmpeg-1011"],
            ):
                self.assertFalse(playwright_browsers_ready())

    def test_playwright_install_command_uses_python_in_source_mode(self):
        command = playwright_install_command()
        self.assertEqual(command[1:], ["-m", "playwright", "install", "chromium"])

    def test_playwright_install_command_uses_bundled_node_when_frozen(self):
        with patch("desktop_py.core.browser_runtime.sys", frozen=True, executable=r"C:\\app\\tool.exe", _MEIPASS=r"C:\\app\\_internal"):
            command = playwright_install_command()

        self.assertEqual(command[0], r"C:\app\_internal\playwright\driver\node.exe")
        self.assertEqual(command[1], r"C:\app\_internal\playwright\driver\package\cli.js")
        self.assertEqual(command[2:], ["install", "chromium"])

    def test_playwright_install_environment_uses_default_domestic_mirror(self):
        with patch.dict("desktop_py.core.browser_runtime.os.environ", {}, clear=True):
            env = playwright_install_environment(Path(r"C:\portable\小程序工具\ms-playwright"))

        self.assertEqual(env["PLAYWRIGHT_BROWSERS_PATH"], r"C:\portable\小程序工具\ms-playwright")
        self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_HOST"], DEFAULT_PLAYWRIGHT_DOWNLOAD_HOST)
        self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"], DEFAULT_PLAYWRIGHT_DOWNLOAD_TIMEOUT_MS)

    def test_playwright_install_environment_keeps_custom_mirror(self):
        with patch.dict(
            "desktop_py.core.browser_runtime.os.environ",
            {
                "PLAYWRIGHT_DOWNLOAD_HOST": "https://example.com/playwright",
                "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "300000",
            },
            clear=True,
        ):
            env = playwright_install_environment(Path(r"C:\portable\小程序工具\ms-playwright"))

        self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_HOST"], "https://example.com/playwright")
        self.assertEqual(env["PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT"], "300000")

    def test_playwright_install_environment_keeps_chromium_specific_mirror(self):
        with patch.dict(
            "desktop_py.core.browser_runtime.os.environ",
            {"PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST": "https://example.com/chromium"},
            clear=True,
        ):
            env = playwright_install_environment(Path(r"C:\portable\小程序工具\ms-playwright"))

        self.assertNotIn("PLAYWRIGHT_DOWNLOAD_HOST", env)
        self.assertEqual(env["PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST"], "https://example.com/chromium")


if __name__ == "__main__":
    unittest.main()
