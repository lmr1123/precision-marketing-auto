import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (REPO_ROOT / "scripts" / "deploy" / "start.bat").read_text(encoding="utf-8")

    def test_reuse_and_ready_paths_open_simple_page(self):
        source = self.source

        self.assertIn("if \"!UI_REUSE!\"==\"1\"", source)
        self.assertGreaterEqual(source.count("call :OPEN_UI"), 2)
        self.assertIn(":OPEN_UI", source)
        self.assertIn("Opening browser: %UI_URL%", source)

    def test_open_ui_has_multiple_windows_fallbacks(self):
        source = self.source

        self.assertIn("http://127.0.0.1:18800/json/new?", source)
        self.assertIn("Invoke-WebRequest -UseBasicParsing -Method Put", source)
        self.assertIn('start "" "%CHROME_PATH%" "%UI_URL%"', source)
        self.assertIn("Start-Process '%UI_URL%'", source)
        self.assertIn('explorer.exe "%UI_URL%"', source)
        self.assertIn('start "" "%UI_URL%"', source)


if __name__ == "__main__":
    unittest.main()
