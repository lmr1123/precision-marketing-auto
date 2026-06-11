<#
  auto_update.ps1 - Precision Marketing Auto Update
  Called by start.bat on every launch.
  Compares local VERSION.txt with server latest.json,
  downloads and replaces app/ if a newer version is available.

  Expected layout:
    PrecisionMarketingAuto/
    +-- app/            (code, replaced on update)
    +-- data/           (user data, NEVER touched)
    +-- start.bat
    +-- app/VERSION.txt
#>
param(
    [string]$BaseDir = (Split-Path -Parent $PSScriptRoot | Split-Path -Parent | Split-Path -Parent),
    [string]$UpdateUrl = "http://49.232.195.165"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$AppDir     = Join-Path $BaseDir "app"
$RuntimeDir = Join-Path $BaseDir "runtime"
$VersionFile = Join-Path $AppDir "VERSION.txt"
$TmpDir     = Join-Path $env:TEMP "pm-auto-update"

# --- helpers -----------------------------------------------------------
function Get-LocalVersion {
    if (Test-Path $VersionFile) {
        return (Get-Content $VersionFile -Raw).Trim()
    }
    return "0.0.0"
}

function Write-Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg"
}

# --- main --------------------------------------------------------------
$localVer = Get-LocalVersion
Write-Log "Local version: $localVer"

try {
    $jsonUrl = "$UpdateUrl/latest.json"
    Write-Log "Checking $jsonUrl ..."
    $resp = Invoke-RestMethod -Uri $jsonUrl -TimeoutSec 15 -Method Get
} catch {
    Write-Log "Cannot reach update server, skipping update."
    return
}

$remoteVer  = $resp.version
$downloadUrl = if ($resp.url_win) { $resp.url_win } else { $resp.url }
$changelog   = $resp.changelog

if (-not $remoteVer -or -not $downloadUrl) {
    Write-Log "Invalid latest.json, skipping update."
    return
}

# Simple semver compare (handles x.y.z)
function Compare-SemVer($a, $b) {
    $pa = $a -split '\.' | ForEach-Object { [int]$_ }
    $pb = $b -split '\.' | ForEach-Object { [int]$_ }
    for ($i = 0; $i -lt 3; $i++) {
        if ($pa[$i] -lt $pb[$i]) { return -1 }
        if ($pa[$i] -gt $pb[$i]) { return 1 }
    }
    return 0
}

$cmp = Compare-SemVer $localVer $remoteVer
if ($cmp -ge 0) {
    Write-Log "Already up-to-date ($localVer >= $remoteVer)."
    return
}

Write-Log "New version available: $localVer -> $remoteVer"
if ($changelog) { Write-Log "Changelog: $changelog" }

# Download
if (Test-Path $TmpDir) { Remove-Item $TmpDir -Recurse -Force }
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null

$zipPath = Join-Path $TmpDir "update.zip"
Write-Log "Downloading $downloadUrl ..."
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -TimeoutSec 300
} catch {
    Write-Log "Download failed: $_"
    return
}

# Extract
$extractDir = Join-Path $TmpDir "extracted"
Write-Log "Extracting ..."
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

# Find the app/ folder inside the extracted archive
$newApp = Join-Path $extractDir "app"
$nested = Get-ChildItem $extractDir -Directory | Select-Object -First 1
if (-not (Test-Path $newApp) -and $nested) {
    $candidate = Join-Path $nested.FullName "app"
    if (Test-Path $candidate) { $newApp = $candidate }
}
if (-not (Test-Path $newApp)) {
    Write-Log "ERROR: No app/ folder found in update package."
    return
}

# Replace app/ (data/ is never touched)
$backupDir = "$AppDir.bak"
if (Test-Path $backupDir) { Remove-Item $backupDir -Recurse -Force }

Write-Log "Backing up current app/ ..."
Rename-Item $AppDir $backupDir

Write-Log "Installing new version ..."
Copy-Item $newApp $AppDir -Recurse -Force

$newRoot = Split-Path -Parent $newApp
$newRuntime = Join-Path $newRoot "runtime"
if ((Test-Path $newRuntime) -and -not (Test-Path $RuntimeDir)) {
    Write-Log "Installing bundled runtime ..."
    Copy-Item $newRuntime $RuntimeDir -Recurse -Force
}

$newStartBat = Join-Path $newRoot "start.bat"
if (Test-Path $newStartBat) {
    Write-Log "Staging start.bat update for next launch ..."
    Copy-Item $newStartBat (Join-Path $BaseDir "start.bat.pending") -Force
}

# Cleanup
Remove-Item $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Log "Updated to v$remoteVer successfully."
