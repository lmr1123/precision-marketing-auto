@echo off
setlocal
chcp 65001 >nul

REM Build must run on Windows.
cd /d "%~dp0\..\.."

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python Launcher (py) not found.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
)

".venv\Scripts\python.exe" -m pip install -U pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-ui.txt pyinstaller
if errorlevel 1 (
  echo ERROR: install failed
  pause
  exit /b 1
)

REM This creates a portable startup EXE that launches local UI.
".venv\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --name PrecisionMarketingUIStarter ^
  --onefile ^
  scripts/windows/windows_ui_starter.py

if errorlevel 1 (
  echo ERROR: build failed
  pause
  exit /b 1
)

echo Build done: dist\PrecisionMarketingUIStarter.exe
pause
endlocal
