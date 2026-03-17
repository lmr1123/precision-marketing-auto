@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "DEFAULT_DIR=%LOCALAPPDATA%\PrecisionMarketingAuto"
echo Precision Marketing Automation - Installer/Updater
echo.
echo Default install path:
echo   %DEFAULT_DIR%
echo.
set /p USER_DIR=Press Enter to use default, or input custom path: 
if "%USER_DIR%"=="" set "USER_DIR=%DEFAULT_DIR%"
REM Handle drive-root input like D:\ which can break quoted args in cmd->powershell
if "%USER_DIR:~-1%"=="\" set "USER_DIR=%USER_DIR%."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_install_or_update.ps1" -InstallDir "%USER_DIR%"
if errorlevel 1 (
  echo ERROR: install/update failed.
  pause
  exit /b 1
)

echo.
echo Installed to:
echo   %USER_DIR%
echo.
echo You can now start from desktop shortcut:
echo   Precision Marketing Automation
pause
endlocal
exit /b 0
