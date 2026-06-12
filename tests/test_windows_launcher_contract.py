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

    def test_open_ui_opens_once_with_limited_fallbacks(self):
        source = self.source

        self.assertIn('start "" "%CHROME_PATH%" --new-window "%UI_URL%"', source)
        self.assertIn("Start-Process '%UI_URL%'", source)
        self.assertIn('start "" "%UI_URL%"', source)
        self.assertNotIn("http://127.0.0.1:18800/json/new?", source)
        self.assertNotIn('explorer.exe "%UI_URL%"', source)
        self.assertNotIn('rundll32 url.dll,FileProtocolHandler "%UI_URL%"', source)

    def test_open_ui_exits_after_first_selected_open_method(self):
        source = self.source
        open_ui = source.split(":OPEN_UI", 1)[1].split(":IS_PORT_OPEN", 1)[0]

        self.assertIn("exit /b 0", open_ui)
        self.assertIn("if not errorlevel 1 exit /b 0", open_ui)
        self.assertIn('start "" "%UI_URL%"', open_ui)
        self.assertLess(open_ui.count('"%UI_URL%"'), 4)

    def test_ui_server_start_has_health_check_and_log_tail(self):
        source = self.source

        self.assertIn("Starting UI server at", source)
        self.assertIn("Invoke-WebRequest -UseBasicParsing -Uri '%BASE_URL%/api/tasks'", source)
        self.assertIn("Last UI server log lines", source)
        self.assertIn("Get-Content -Path '%UI_LOG%' -Tail 80", source)

    def test_cdp_start_does_not_open_business_dashboard(self):
        source = self.source

        self.assertNotIn("precision.dslyy.com/admin#/dashboard", source)
        self.assertIn("--remote-debugging-port=18800", source)
        self.assertIn("about:blank", source)

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
