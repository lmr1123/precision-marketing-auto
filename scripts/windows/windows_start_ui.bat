@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Move to repo root (scripts/windows -> repo root)
cd /d "%~dp0\..\.."

echo [1/4] Checking Python ...
where py >nul 2>nul
if %ERRORLEVEL% NEQ 0 goto :NO_PY

echo [2/4] Preparing virtual environment ...
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if %ERRORLEVEL% NEQ 0 goto :VENV_FAIL

echo [3/4] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install -U pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-ui.txt
if %ERRORLEVEL% NEQ 0 goto :PIP_FAIL
".venv\Scripts\python.exe" -m playwright install chromium
if %ERRORLEVEL% NEQ 0 goto :PLAYWRIGHT_FAIL

echo [4/4] Starting UI on http://127.0.0.1:8790 ...
start "" "http://127.0.0.1:8790"
".venv\Scripts\python.exe" -m uvicorn ui_app.server:app --host 127.0.0.1 --port 8790

endlocal
exit /b 0

:NO_PY
echo ERROR: Python Launcher (py) not found.
echo Please install Python 3.11+ first: https://www.python.org/downloads/windows/
pause
exit /b 1

:VENV_FAIL
echo ERROR: Failed to create .venv
pause
exit /b 1

:PIP_FAIL
echo ERROR: Dependency installation failed.
pause
exit /b 1

:PLAYWRIGHT_FAIL
echo ERROR: playwright install chromium failed.
pause
exit /b 1
