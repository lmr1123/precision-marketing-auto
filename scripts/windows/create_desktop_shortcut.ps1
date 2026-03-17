$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$targetBat = Join-Path $repoRoot "scripts\windows\windows_start_ui.bat"
if (!(Test-Path $targetBat)) {
  throw "Cannot find: $targetBat"
}

function Resolve-DesktopPath {
  $candidates = @()
  $p1 = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
  $p2 = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
  if ($p1) { $candidates += $p1 }
  if ($p2) { $candidates += $p2 }
  if ($env:USERPROFILE) { $candidates += (Join-Path $env:USERPROFILE "Desktop") }
  if ($env:OneDrive) { $candidates += (Join-Path $env:OneDrive "Desktop") }
  foreach ($p in $candidates) {
    if ($p -and (Test-Path $p)) { return $p }
  }
  $fallback = Join-Path $env:USERPROFILE "Desktop"
  New-Item -ItemType Directory -Path $fallback -Force | Out-Null
  return $fallback
}

$desktop = Resolve-DesktopPath
$shortcutPath = Join-Path $desktop "Precision Marketing Automation.lnk"
$shortcutPath = [System.IO.Path]::ChangeExtension($shortcutPath, ".lnk")
$shortcutPath = [System.IO.Path]::GetFullPath($shortcutPath)

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetBat
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "双击启动精准营销自动化UI"
$shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
$shortcut.Save()

Write-Host "OK: Desktop shortcut created -> $shortcutPath"
