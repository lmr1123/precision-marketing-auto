@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0\..\.."
set "INSTALL_DIR=%CD%"

echo Updating package from latest GitHub release ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows_install_or_update.ps1" -InstallDir "%INSTALL_DIR%"
if errorlevel 1 (
  echo ERROR: update failed.
  pause
  exit /b 1
)

echo Update completed.
pause
endlocal
exit /b 0

