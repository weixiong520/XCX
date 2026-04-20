import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_installer.ps1"


class BuildInstallerScriptTestCase(unittest.TestCase):
    def test_build_script_uses_project_inno_compiler(self):
        content = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("tools\\inno\\ISCC.exe", content)
        self.assertIn("Resolve-InnoCompilerPath", content)

    def test_build_script_collects_playwright_driver_assets(self):
        content = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("--collect-all playwright", content)
        self.assertIn("_internal\\playwright\\driver\\package\\.local-browsers", content)

    def test_build_script_requires_clean_mode(self):
        content = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('throw "当前仅支持基于干净源目录构建安装包，请传入 -Clean。"', content)

    def test_build_script_supports_offline_runtime_mode(self):
        content = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("[switch]$IncludeOfflineChromium", content)
        self.assertIn("Resolve-OfflineRuntimeSource -ProjectRoot $projectRoot", content)
        self.assertIn(
            "Copy-Item -LiteralPath $offlineRuntimeSource -Destination $offlineRuntimeTarget -Recurse -Force", content
        )


if __name__ == "__main__":
    unittest.main()
