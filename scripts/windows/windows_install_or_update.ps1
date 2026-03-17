$ErrorActionPreference = "Stop"

param(
  [string]$InstallDir = "$env:LOCALAPPDATA\PrecisionMarketingAuto",
  [string]$Repo = "lmr1123/precision-marketing-auto",
  [string]$AssetName = "precision-marketing-auto-windows-oneclick.zip"
)

function Write-Step([string]$msg) {
  Write-Host "[Installer] $msg"
}

function Get-LatestRelease([string]$repo) {
  $api = "https://api.github.com/repos/$repo/releases/latest"
  return Invoke-RestMethod -Uri $api -UseBasicParsing
}

function Resolve-AssetUrl($release, [string]$assetName, [string]$repo) {
  if ($release -and $release.assets) {
    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    if ($asset -and $asset.browser_download_url) { return $asset.browser_download_url }
  }
  return "https://github.com/$repo/releases/latest/download/$assetName"
}

function Ensure-DesktopShortcut([string]$installDir) {
  $targetBat = Join-Path $installDir "scripts\windows\windows_start_ui.bat"
  if (!(Test-Path $targetBat)) { return }

  $desktop = [Environment]::GetFolderPath("Desktop")
  $shortcutPath = Join-Path $desktop "精准营销自动化工具.lnk"
  $wsh = New-Object -ComObject WScript.Shell
  $shortcut = $wsh.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $targetBat
  $shortcut.WorkingDirectory = $installDir
  $shortcut.Description = "双击启动精准营销自动化UI"
  $shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,220"
  $shortcut.Save()
  Write-Step "Desktop shortcut ready: $shortcutPath"
}

Write-Step "Install directory: $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

$tmpRoot = Join-Path $env:TEMP ("pm_auto_update_" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpRoot $AssetName
$extractRoot = Join-Path $tmpRoot "extract"
New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

Write-Step "Fetching latest release info..."
$release = $null
try { $release = Get-LatestRelease -repo $Repo } catch {}

$assetUrl = Resolve-AssetUrl -release $release -assetName $AssetName -repo $Repo
Write-Step "Downloading package..."
Invoke-WebRequest -Uri $assetUrl -OutFile $zipPath -UseBasicParsing

Write-Step "Extracting package..."
Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

$pkgDir = Join-Path $extractRoot "precision-marketing-auto-windows"
if (!(Test-Path $pkgDir)) {
  $candidate = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
  if ($candidate) { $pkgDir = $candidate.FullName }
}
if (!(Test-Path $pkgDir)) {
  throw "Unzip failed: package folder not found."
}

Write-Step "Applying update files..."
robocopy $pkgDir $InstallDir /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD ".venv" "ui_uploads" "__pycache__" | Out-Null

$releaseTag = ""
if ($release -and $release.tag_name) { $releaseTag = [string]$release.tag_name }
if ([string]::IsNullOrWhiteSpace($releaseTag)) { $releaseTag = "unknown" }
Set-Content -Path (Join-Path $InstallDir "VERSION.txt") -Value $releaseTag -Encoding UTF8

Ensure-DesktopShortcut -installDir $InstallDir

Write-Step "Done. Version: $releaseTag"
Write-Host ""
Write-Host "Next step:"
Write-Host "1) Open: $InstallDir"
Write-Host "2) Double click: scripts\windows\windows_start_ui.bat"

