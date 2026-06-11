@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Move to repo root (scripts/windows -> repo root)
cd /d "%~dp0\..\.."
set "REPO_ROOT=%CD%"
set "LOG_DIR=%REPO_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "UI_LOG=%LOG_DIR%\ui_server.log"
set "UI_URL=http://127.0.0.1:8790"

call :IS_PORT_OPEN 8790
if "%PORT_OPEN%"=="1" (
  echo [0/6] UI already running on %UI_URL%
  start "" "%UI_URL%"
  endlocal
  exit /b 0
)

echo [1/5] Checking Python ...
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD goto :NO_PY

echo [2/5] Preparing virtual environment ...
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :VENV_FAIL
)

echo [3/5] Installing dependencies ...
if not exist ".venv\.deps_ready" (
  ".venv\Scripts\python.exe" -m pip install -U pip
  if errorlevel 1 goto :PIP_FAIL
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-ui.txt
  if errorlevel 1 goto :PIP_FAIL
  ".venv\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 goto :PLAYWRIGHT_FAIL
  echo ok > ".venv\.deps_ready"
) else (
  echo     Dependencies already prepared, skip reinstall.
)

echo [4/6] Starting local UI service ...
echo     URL: %UI_URL%
call :ENSURE_CDP

echo [5/6] Launching server process ...
start "" /b cmd /c ""%REPO_ROOT%\.venv\Scripts\python.exe" -m uvicorn ui_app.server:app --host 127.0.0.1 --port 8790 > "%UI_LOG%" 2>&1"

echo [6/6] Waiting for UI health ...
for /l %%i in (1,1,25) do (
  curl -s "%UI_URL%/api/tasks" >nul 2>nul
  if not errorlevel 1 goto :UI_READY
  timeout /t 1 /nobreak >nul
)
echo ERROR: UI did not start successfully.
echo ----- Last server log lines -----
if exist "%UI_LOG%" powershell -NoProfile -Command "Get-Content -Path '%UI_LOG%' -Tail 40"
echo ---------------------------------
pause
endlocal
exit /b 1

:UI_READY
echo UI started.
start "" "%UI_URL%"
endlocal
exit /b 0


:NO_PY
echo ERROR: Python not found.
echo Please install Python 3.11+ from https://www.python.org/downloads/windows/
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

:IS_PORT_OPEN
set "PORT_OPEN=0"
for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING" 2^>nul') do (
  set "PORT_OPEN=1"
  goto :PORT_DONE
)
:PORT_DONE
exit /b 0

:ENSURE_CDP
echo [CDP] Checking http://127.0.0.1:18800 ...
curl -s http://127.0.0.1:18800/json/version >nul 2>nul
if not errorlevel 1 (
  echo [CDP] Already running.
  exit /b 0
)

echo [CDP] Not running. Trying to start Chrome with remote debugging ...
call :FIND_CHROME
if not defined CHROME_PATH (
  echo [CDP] WARNING: Chrome not found automatically.
  echo [CDP] Please start Chrome manually with:
  echo       chrome.exe --remote-debugging-port=18800 --user-data-dir="D:\chrome-cdp-profile"
  exit /b 0
)

if not defined CDP_PROFILE_DIR set "CDP_PROFILE_DIR=D:\chrome-cdp-profile"
start "" "%CHROME_PATH%" --remote-debugging-port=18800 --user-data-dir="%CDP_PROFILE_DIR%"

for /l %%i in (1,1,20) do (
  timeout /t 1 /nobreak >nul
  curl -s http://127.0.0.1:18800/json/version >nul 2>nul
  if not errorlevel 1 (
    echo [CDP] Started successfully.
    exit /b 0
  )
)
echo [CDP] WARNING: Failed to verify 18800. You can continue, but task may fail to connect CDP.
exit /b 0

:FIND_CHROME
set "CHROME_PATH="
for %%P in (
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
) do (
  if exist %%~P (
    set "CHROME_PATH=%%~P"
    exit /b 0
  )
)

for %%K in (
  "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
  "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
  "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
) do (
  for /f "tokens=2,*" %%A in ('reg query %%~K /ve 2^>nul ^| find /i "REG_SZ"') do (
    set "CHROME_PATH=%%B"
    if defined CHROME_PATH exit /b 0
  )
)
exit /b 0
