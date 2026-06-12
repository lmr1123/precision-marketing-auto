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
        self.assertIn('start "" "%CHROME_PATH%" --new-window "%UI_URL%"', source)
        self.assertIn("Start-Process '%UI_URL%'", source)
        self.assertIn('explorer.exe "%UI_URL%"', source)
        self.assertIn('rundll32 url.dll,FileProtocolHandler "%UI_URL%"', source)
        self.assertIn('start "" "%UI_URL%"', source)

    def test_open_ui_does_not_exit_after_first_success(self):
        source = self.source
        open_ui = source.split(":OPEN_UI", 1)[1].split(":IS_PORT_OPEN", 1)[0]

        self.assertNotIn("if not errorlevel 1 exit /b 0", open_ui)
        self.assertIn('start "" "%UI_URL%"', open_ui)

    def test_pending_launcher_update_continues_in_same_window(self):
        source = self.source
        pending_block = source.split('if not "%PM_AUTO_START_INNER%"=="1" if exist "%~dp0start.bat.pending"', 1)[1].split('if "%PM_AUTO_START_INNER%"=="1"', 1)[0]

        self.assertIn("Applying launcher update", pending_block)
        self.assertIn('copy /y "%~dp0start.bat.pending" "%~f0"', pending_block)
        self.assertIn("Launcher updated. Continuing startup", pending_block)
        self.assertNotIn("/min cmd", pending_block)
        self.assertNotIn("exit /b 0", pending_block)


if __name__ == "__main__":
    unittest.main()
