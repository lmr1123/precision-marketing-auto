@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "DEFAULT_DIR=%LOCALAPPDATA%\PrecisionMarketingAuto"
set "DEFAULT_PKG=%~dp0..\..\release\precision-marketing-auto-windows-oneclick.zip"

echo Precision Marketing Automation - Offline Installer/Updater
echo.
echo Default install path:
echo   %DEFAULT_DIR%
echo.
set /p USER_DIR=Press Enter to use default, or input custom path: 
if "%USER_DIR%"=="" set "USER_DIR=%DEFAULT_DIR%"
if "%USER_DIR:~-1%"=="\" set "USER_DIR=%USER_DIR%."

echo.
echo Default package:
echo   %DEFAULT_PKG%
echo.
set /p USER_PKG=Press Enter to use default package, or input zip path: 
if "%USER_PKG%"=="" set "USER_PKG=%DEFAULT_PKG%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_install_or_update.ps1" -InstallDir "%USER_DIR%" -PackageFile "%USER_PKG%"
if errorlevel 1 (
  echo ERROR: offline install/update failed.
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

