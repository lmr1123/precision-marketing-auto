$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$targetBat = Join-Path $repoRoot "scripts\windows\windows_start_ui.bat"
if (!(Test-Path $targetBat)) {
  throw "Cannot find: $targetBat"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "精准营销自动化工具.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetBat
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "双击启动精准营销自动化UI"
$shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
$shortcut.Save()

Write-Host "OK: Desktop shortcut created -> $shortcutPath"
