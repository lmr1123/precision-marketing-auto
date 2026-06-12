@echo off
setlocal EnableExtensions

if not "%PM_AUTO_START_INNER%"=="1" if exist "%~dp0start.bat.pending" (
  if not exist "%~dp0data\logs" mkdir "%~dp0data\logs" 2>nul
  echo Applying launcher update ...
  copy /y "%~dp0start.bat.pending" "%~f0" >nul
  if errorlevel 1 (
    echo ERROR: Failed to apply launcher update.
    echo Please send this log folder to support: %~dp0data\logs
    pause
    endlocal
    exit /b 1
  )
  del "%~dp0start.bat.pending" >nul 2>nul
  echo Launcher updated. Continuing startup ...
)

if "%PM_AUTO_START_INNER%"=="1" goto :INNER

REM Outer guard: keep the window open on startup failures and persist logs.
set "PM_AUTO_START_INNER=1"
set "PM_START_DIR=%~dp0"
if not exist "%PM_START_DIR%data\logs" mkdir "%PM_START_DIR%data\logs" 2>nul
set "PM_LAUNCHER_LOG=%PM_START_DIR%data\logs\launcher.log"
(
  echo ============================================================
  echo Precision Marketing Auto launcher
  echo Time: %DATE% %TIME%
  echo Start dir: %PM_START_DIR%
  echo ============================================================
) > "%PM_LAUNCHER_LOG%"
call "%~f0" >> "%PM_LAUNCHER_LOG%" 2>&1
set "PM_EXIT=%ERRORLEVEL%"
if not "%PM_EXIT%"=="0" (
  type "%PM_LAUNCHER_LOG%"
  echo.
  echo ========================================
  echo   STARTUP FAILED
  echo   Please send this log to support:
  echo   %PM_LAUNCHER_LOG%
  echo ========================================
  echo.
  pause
)
endlocal & exit /b %PM_EXIT%

:INNER
chcp 65001 >nul 2>nul
setlocal EnableExtensions EnableDelayedExpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

REM ============================================================
REM  start.bat - Precision Marketing Auto Launcher
REM  Desktop shortcut target. Handles:
REM    1. Auto-update from server
REM    2. Runtime bootstrap (bundled / system / auto-download)
REM    3. Dependency check (offline wheelhouse preferred)
REM    4. Start uvicorn + open browser
REM ============================================================

REM --- Resolve base directory (where this .bat lives) ---
cd /d "%~dp0"
set "BASE_DIR=%CD%"
set "APP_DIR=%BASE_DIR%\app"
set "DATA_DIR=%BASE_DIR%\data"
set "RUNTIME_DIR=%BASE_DIR%\runtime"
set "RUNTIME_PY_DIR=%RUNTIME_DIR%\python"
set "WHEELHOUSE_DIR=%RUNTIME_DIR%\wheelhouse"
set "LOG_DIR=%DATA_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "UI_LOG=%LOG_DIR%\ui_server.log"
set "BASE_URL=http://127.0.0.1:8790"
set "UI_URL=%BASE_URL%/simple"

REM --- Tell server.py where data lives ---
set "PM_DATA_DIR=%DATA_DIR%"

if not exist "%APP_DIR%\ui_app\server.py" (
    echo ERROR: app files not found: "%APP_DIR%\ui_app\server.py"
    echo Please extract the zip first, then run start.bat from the extracted root folder.
    goto :FAIL
)

REM ========== STEP 1: Auto-update ==========
echo [1/6] Checking for updates ...
if exist "%APP_DIR%\scripts\deploy\auto_update.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\deploy\auto_update.ps1" -BaseDir "%BASE_DIR%"
)
echo.

REM --- Reuse only if the running service is this package/version ---
call :CHECK_EXISTING_UI
if "!UI_REUSE!"=="1" (
    echo [0/6] UI already running from current package on %UI_URL%
    call :OPEN_UI
    goto :DONE
)

REM ========== STEP 2: Locate / Bootstrap Python ==========
echo [2/6] Locating Python ...
set "PY_EXE="
set "PY_ARGS="

REM Option A: bundled runtime Python (strong one-click package)
set "EMBED_PY=%RUNTIME_PY_DIR%\python.exe"
if exist "!EMBED_PY!" (
    set "PY_EXE=!EMBED_PY!"
    echo     Using bundled runtime Python.
    goto :PY_FOUND
)

REM Option B: initialize bundled runtime Python from local zip
set "RUNTIME_PY_ZIP=%RUNTIME_DIR%\python-3.11.9-embed-amd64.zip"
if exist "!RUNTIME_PY_ZIP!" (
    echo     Preparing bundled runtime Python ...
    if exist "!RUNTIME_PY_DIR!" rmdir /s /q "!RUNTIME_PY_DIR!"
    mkdir "!RUNTIME_PY_DIR!"
    powershell -NoProfile -Command "Expand-Archive -Path '!RUNTIME_PY_ZIP!' -DestinationPath '!RUNTIME_PY_DIR!' -Force"
    if errorlevel 1 (
        echo ERROR: Failed to extract bundled runtime Python.
        goto :FAIL
    )
    for %%F in ("!RUNTIME_PY_DIR!\*._pth") do (
        powershell -NoProfile -Command "$c=Get-Content '%%F'; $c=$c -replace '#import site','import site'; if($c -notcontains 'Lib\site-packages'){$c+='Lib\site-packages'}; Set-Content '%%F' $c"
    )
    if exist "!RUNTIME_DIR!\get-pip.py" (
        "!RUNTIME_PY_DIR!\python.exe" "!RUNTIME_DIR!\get-pip.py" --no-index --find-links "!WHEELHOUSE_DIR!" --no-warn-script-location
        if errorlevel 1 (
            echo ERROR: Failed to install pip from bundled wheelhouse.
            goto :FAIL
        )
    )
    set "PY_EXE=!RUNTIME_PY_DIR!\python.exe"
    echo     Bundled runtime Python ready.
    goto :PY_FOUND
)

REM Option C: system Python
where py >nul 2>nul
if not errorlevel 1 ( set "PY_EXE=py" & set "PY_ARGS=-3" & goto :PY_FOUND )
where python >nul 2>nul
if not errorlevel 1 ( set "PY_EXE=python" & goto :PY_FOUND )

REM Option D: Auto-download embedded Python (legacy online fallback)
echo     No Python found. Downloading embedded Python 3.11 ...
echo     This only happens on first run. Please wait ...
set "PY_VERSION=3.11.9"
set "PY_URL=https://www.python.org/ftp/python/!PY_VERSION!/python-!PY_VERSION!-embed-amd64.zip"
set "PY_DIR=!RUNTIME_PY_DIR!"
set "PY_ZIP=%TEMP%\pm-auto-python-embed.zip"

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_ZIP!' -TimeoutSec 120"
if errorlevel 1 (
    echo ERROR: Failed to download embedded Python.
    echo Please install Python 3.11+ manually from https://www.python.org/downloads/windows/
    goto :FAIL
)

echo     Extracting embedded Python ...
if exist "!PY_DIR!" rmdir /s /q "!PY_DIR!"
mkdir "!PY_DIR!"
powershell -NoProfile -Command "Expand-Archive -Path '!PY_ZIP!' -DestinationPath '!PY_DIR!' -Force"
del "!PY_ZIP!" 2>nul

REM Enable pip: uncomment "import site" in ._pth file
for %%F in ("!PY_DIR!\*._pth") do (
    powershell -NoProfile -Command "$c=Get-Content '%%F'; $c=$c -replace '#import site','import site'; $c+='Lib\site-packages'; Set-Content '%%F' $c"
)

REM Install pip
echo     Installing pip ...
set "GET_PIP=%TEMP%\get-pip.py"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '!GET_PIP!' -TimeoutSec 60"
"!PY_DIR!\python.exe" "!GET_PIP!" --no-warn-script-location
del "!GET_PIP!" 2>nul
if errorlevel 1 (
    echo ERROR: Failed to install pip.
    goto :FAIL
)

set "PY_EXE=!PY_DIR!\python.exe"
echo     Embedded Python ready.
goto :PY_FOUND

:PY_FOUND
echo     Python: "!PY_EXE!" !PY_ARGS!

REM ========== STEP 3: Ensure dependencies ==========
echo [3/6] Checking dependencies ...
set /p APP_VERSION=<"%APP_DIR%\VERSION.txt"
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
set "DEPS_MARKER=%RUNTIME_DIR%\.deps_ready_%APP_VERSION%"
if not exist "%DEPS_MARKER%" (
    echo     Installing dependencies - first run may take a minute ...
    if exist "%WHEELHOUSE_DIR%\*.whl" (
        echo     Using bundled offline wheelhouse.
        "%PY_EXE%" %PY_ARGS% -m pip install -r "%APP_DIR%\requirements.txt" -r "%APP_DIR%\requirements-ui.txt" --no-index --find-links "%WHEELHOUSE_DIR%" --quiet
        if errorlevel 1 (
            echo ERROR: offline pip install failed. Retrying without --quiet ...
            "%PY_EXE%" %PY_ARGS% -m pip install -r "%APP_DIR%\requirements.txt" -r "%APP_DIR%\requirements-ui.txt" --no-index --find-links "%WHEELHOUSE_DIR%"
            if errorlevel 1 goto :PIP_FAIL
        )
    ) else (
        "%PY_EXE%" %PY_ARGS% -m pip install -r "%APP_DIR%\requirements.txt" -r "%APP_DIR%\requirements-ui.txt" --quiet
        if errorlevel 1 (
            echo ERROR: pip install failed. Retrying without --quiet ...
            "%PY_EXE%" %PY_ARGS% -m pip install -r "%APP_DIR%\requirements.txt" -r "%APP_DIR%\requirements-ui.txt"
            if errorlevel 1 goto :PIP_FAIL
        )
        "%PY_EXE%" %PY_ARGS% -m playwright install chromium
        if errorlevel 1 goto :PLAYWRIGHT_FAIL
    )
    echo ok > "%DEPS_MARKER%"
    echo     Dependencies installed.
) else (
    echo     Dependencies OK.
)

REM ========== STEP 4: Ensure Chrome CDP ==========
echo [4/6] Checking Chrome CDP ...
call :ENSURE_CDP

REM ========== STEP 5: Start server ==========
echo [5/6] Starting UI server ...
set "SERVER_CMD=%LOG_DIR%\run_ui_server.bat"
(
  echo @echo off
  echo chcp 65001 ^>nul
  echo set PYTHONUTF8=1
  echo set PYTHONIOENCODING=utf-8
  echo set PYTHONUNBUFFERED=1
  echo set "PM_DATA_DIR=%DATA_DIR%"
  echo cd /d "%APP_DIR%"
  echo "%PY_EXE%" %PY_ARGS% -m uvicorn ui_app.server:app --host 127.0.0.1 --port 8790
) > "%SERVER_CMD%"
start "Precision Marketing UI Server" /min cmd /c ""%SERVER_CMD%" > "%UI_LOG%" 2>&1"

REM Wait for health check
for /l %%i in (1,1,30) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri '%BASE_URL%/api/tasks' -TimeoutSec 2 | Out-Null" >nul 2>nul
  if not errorlevel 1 goto :UI_READY
  timeout /t 1 /nobreak >nul
)
echo ERROR: UI did not start. Check %UI_LOG%
if exist "%UI_LOG%" (
  echo ----- Last UI server log lines -----
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%UI_LOG%' -Tail 80" 2>nul
  echo ------------------------------------
)
goto :FAIL

:UI_READY
echo.
echo ========================================
echo   UI ready: %UI_URL%
echo ========================================
echo.
call :OPEN_UI
goto :DONE

REM ============================================================
REM  Subroutines
REM ============================================================

:OPEN_UI
echo     Opening browser: %UI_URL%
start "" "%UI_URL%"
exit /b 0

:IS_PORT_OPEN
set "PORT_OPEN=0"
for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING" 2^>nul') do (
  set "PORT_OPEN=1"
  goto :PORT_DONE
)
:PORT_DONE
exit /b 0

:CHECK_EXISTING_UI
set "UI_REUSE=0"
call :IS_PORT_OPEN 8790
if not "!PORT_OPEN!"=="1" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $app=(Resolve-Path '%APP_DIR%').Path; $local=(Get-Content (Join-Path $app 'VERSION.txt') -Raw).Trim(); $rt=Invoke-RestMethod -Uri '%BASE_URL%/api/runtime' -TimeoutSec 2; if($rt -and $rt.version -eq $local -and ((Resolve-Path $rt.app_dir).Path -eq $app)){ exit 10 }; if($rt -and $rt.pid){ Stop-Process -Id ([int]$rt.pid) -Force; exit 20 }; $conn=Get-NetTCPConnection -LocalPort 8790 -State Listen | Select-Object -First 1; if($conn){ Stop-Process -Id ([int]$conn.OwningProcess) -Force }; exit 20"
if "!ERRORLEVEL!"=="10" (
  set "UI_REUSE=1"
  exit /b 0
)
echo [0/6] Found stale UI on 8790; switching to current package ...
timeout /t 2 /nobreak >nul
exit /b 0

:ENSURE_CDP
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18800/json/version' -TimeoutSec 2 | Out-Null" >nul 2>nul
if not errorlevel 1 (
  echo     CDP already running.
  exit /b 0
)
echo     Starting Chrome with CDP ...
call :FIND_CHROME
if not defined CHROME_PATH (
  echo     WARNING: Chrome not found. Please start Chrome manually with:
  echo       chrome.exe --remote-debugging-port=18800 --user-data-dir="%DATA_DIR%\chrome-cdp-profile"
  exit /b 0
)
set "CDP_PROFILE=%DATA_DIR%\chrome-cdp-profile"
start "" /min "%CHROME_PATH%" --remote-debugging-port=18800 --user-data-dir="%CDP_PROFILE%" --no-first-run --no-default-browser-check about:blank
for /l %%i in (1,1,20) do (
  timeout /t 1 /nobreak >nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18800/json/version' -TimeoutSec 2 | Out-Null" >nul 2>nul
  if not errorlevel 1 (
    echo     CDP started.
    exit /b 0
  )
)
echo     WARNING: CDP verification timed out.
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
) do (
  for /f "tokens=2,*" %%A in ('reg query %%~K /ve 2^>nul ^| find /i "REG_SZ"') do (
    set "CHROME_PATH=%%B"
    if defined CHROME_PATH exit /b 0
  )
)
exit /b 0

REM ============================================================
REM  End states
REM ============================================================

:DONE
endlocal
exit /b 0

:FAIL
echo.
echo ========================================
echo   STARTUP FAILED - see errors above
echo   Logs: %LOG_DIR%
echo ========================================
echo.
if not "%PM_AUTO_START_INNER%"=="1" pause
endlocal
exit /b 1

:NO_PY
echo ERROR: Python not found.
goto :FAIL

:PIP_FAIL
echo ERROR: Dependency installation failed.
goto :FAIL

:PLAYWRIGHT_FAIL
echo ERROR: playwright install chromium failed.
goto :FAIL
