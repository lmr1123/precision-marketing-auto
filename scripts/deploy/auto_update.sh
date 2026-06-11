#!/bin/bash
# auto_update.sh - Precision Marketing Auto Update (macOS)
# Called by start.command on every launch.
set -uo pipefail

BASE_DIR="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
UPDATE_URL="http://49.232.195.165"

APP_DIR="$BASE_DIR/app"
VERSION_FILE="$APP_DIR/VERSION.txt"
TMP_DIR="/tmp/pm-auto-update-$$"

log() { echo "[$(date +%H:%M:%S)] $*"; }

get_local_version() {
    if [ -f "$VERSION_FILE" ]; then
        cat "$VERSION_FILE" | tr -d '[:space:]'
    else
        echo "0.0.0"
    fi
}

LOCAL_VER=$(get_local_version)
log "Local version: $LOCAL_VER"

# Fetch latest.json
JSON=$(curl -sf --max-time 15 "$UPDATE_URL/latest.json" 2>/dev/null) || {
    log "Cannot reach update server, skipping update."
    exit 0
}

REMOTE_VER=$(echo "$JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null)
DOWNLOAD_URL=$(echo "$JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('url_mac') or d.get('url') or '')" 2>/dev/null)
CHANGELOG=$(echo "$JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('changelog',''))" 2>/dev/null)

if [ -z "$REMOTE_VER" ] || [ -z "$DOWNLOAD_URL" ]; then
    log "Invalid latest.json, skipping update."
    exit 0
fi

# Semver compare: returns 0 if $1 < $2
ver_lt() {
    local IFS=.
    local a=($1) b=($2)
    for i in 0 1 2; do
        if (( ${a[$i]:-0} < ${b[$i]:-0} )); then return 0; fi
        if (( ${a[$i]:-0} > ${b[$i]:-0} )); then return 1; fi
    done
    return 1
}

if ! ver_lt "$LOCAL_VER" "$REMOTE_VER"; then
    log "Already up-to-date ($LOCAL_VER >= $REMOTE_VER)."
    exit 0
fi

log "New version available: $LOCAL_VER -> $REMOTE_VER"
[ -n "$CHANGELOG" ] && log "Changelog: $CHANGELOG"

# Download
mkdir -p "$TMP_DIR"
ZIP_PATH="$TMP_DIR/update.zip"
log "Downloading $DOWNLOAD_URL ..."
if ! curl -L --max-time 300 -o "$ZIP_PATH" "$DOWNLOAD_URL"; then
    log "Download failed."
    rm -rf "$TMP_DIR"
    exit 1
fi

# Extract
EXTRACT_DIR="$TMP_DIR/extracted"
log "Extracting ..."
unzip -qo "$ZIP_PATH" -d "$EXTRACT_DIR"

# Find app/ folder
NEW_APP="$EXTRACT_DIR/app"
if [ ! -d "$NEW_APP" ]; then
    # Check nested: extracted/PrecisionMarketingAuto/app
    for d in "$EXTRACT_DIR"/*/; do
        if [ -d "$d/app" ]; then
            NEW_APP="$d/app"
            break
        fi
    done
fi
if [ ! -d "$NEW_APP" ]; then
    log "ERROR: No app/ folder found in update package."
    rm -rf "$TMP_DIR"
    exit 1
fi

# Replace app/ (data/ is NEVER touched)
BACKUP_DIR="$APP_DIR.bak"
[ -d "$BACKUP_DIR" ] && rm -rf "$BACKUP_DIR"

log "Backing up current app/ ..."
mv "$APP_DIR" "$BACKUP_DIR"

log "Installing new version ..."
cp -R "$NEW_APP" "$APP_DIR"

NEW_ROOT="$(dirname "$NEW_APP")"
if [ -f "$NEW_ROOT/start.command" ]; then
    log "Updating start.command ..."
    cp "$NEW_ROOT/start.command" "$BASE_DIR/start.command"
    chmod +x "$BASE_DIR/start.command" 2>/dev/null || true
fi

# Cleanup
rm -rf "$TMP_DIR"
rm -rf "$BACKUP_DIR"

log "Updated to v$REMOTE_VER successfully."
