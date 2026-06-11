#!/bin/bash
# ============================================================
#  start.command - Precision Marketing Auto Launcher (macOS)
#  Double-click to launch. Handles:
#    1. Auto-update from Tencent Cloud server
#    2. Python / venv bootstrap
#    3. Dependency check
#    4. Start uvicorn + open browser
# ============================================================
set -euo pipefail

# --- Resolve base directory (where this .command lives) ---
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$BASE_DIR/app"
DATA_DIR="$BASE_DIR/data"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"
UI_LOG="$LOG_DIR/ui_server.log"
UI_URL="http://127.0.0.1:8790"
OPEN_URL="$UI_URL/simple"

export PM_DATA_DIR="$DATA_DIR"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

stop_existing_ui() {
    local pids
    pids=$(lsof -tiTCP:8790 -sTCP:LISTEN 2>/dev/null || true)
    if [ -z "$pids" ]; then
        return 0
    fi
    echo "    Stopping old UI process: $pids"
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 10); do
        sleep 1
        if ! lsof -tiTCP:8790 -sTCP:LISTEN >/dev/null 2>&1; then
            return 0
        fi
    done
    kill -9 $pids 2>/dev/null || true
}

check_existing_ui() {
    if ! curl -sf "$UI_URL/api/tasks" >/dev/null 2>&1; then
        return 1
    fi
    local local_version runtime_json
    local_version="$(cat "$APP_DIR/VERSION.txt" 2>/dev/null | tr -d '[:space:]')"
    runtime_json="$(curl -sf "$UI_URL/api/runtime" 2>/dev/null || true)"
    if [ -n "$runtime_json" ] && command -v python3 >/dev/null 2>&1; then
        if RUNTIME_JSON="$runtime_json" APP_DIR="$APP_DIR" LOCAL_VERSION="$local_version" python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

try:
    info = json.loads(os.environ["RUNTIME_JSON"])
except Exception:
    sys.exit(1)

app_dir = Path(info.get("app_dir", "")).resolve()
current_app = Path(os.environ["APP_DIR"]).resolve()
same_version = info.get("version") == os.environ.get("LOCAL_VERSION")
same_dir = app_dir == current_app
sys.exit(0 if same_version and same_dir else 1)
PY
        then
            echo "[0/5] UI already running from current package on $UI_URL"
            open "$OPEN_URL"
            exit 0
        fi
    fi

    echo "[0/5] Found stale UI on 8790; switching to current package ..."
    stop_existing_ui
    return 1
}

# ========== STEP 1: Auto-update ==========
echo "[1/5] Checking for updates ..."
bash "$APP_DIR/scripts/deploy/auto_update.sh" "$BASE_DIR" 2>&1 || true
echo

# --- Reuse only if the running service is this package/version ---
check_existing_ui || true

# ========== STEP 2: Locate Python ==========
echo "[2/5] Locating Python ..."
PY_CMD=""

# Option A: embedded Python
if [ -x "$APP_DIR/python/bin/python3" ]; then
    PY_CMD="$APP_DIR/python/bin/python3"
    echo "    Using embedded Python."
# Option B: Homebrew / system Python
elif command -v python3 &>/dev/null; then
    PY_CMD="python3"
    echo "    Using system Python."
elif command -v python &>/dev/null; then
    PY_CMD="python"
    echo "    Using system Python."
else
    echo "ERROR: Python not found. Install Python 3.11+ from https://www.python.org/"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "    Python: $PY_CMD"

# ========== STEP 3: Ensure venv + dependencies ==========
echo "[3/5] Checking dependencies ..."
VENV_DIR="$DATA_DIR/.venv"
APP_VERSION="$(cat "$APP_DIR/VERSION.txt" 2>/dev/null | tr -d '[:space:]')"
DEPS_MARKER="$VENV_DIR/.deps_ready_${APP_VERSION:-unknown}"

if [ ! -d "$VENV_DIR" ]; then
    echo "    Creating virtual environment ..."
    "$PY_CMD" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"

if [ ! -f "$DEPS_MARKER" ]; then
    echo "    Installing dependencies (first run) ..."
    "$VENV_PY" -m pip install -r "$APP_DIR/requirements.txt" -r "$APP_DIR/requirements-ui.txt" --quiet || {
        echo "ERROR: pip install failed."
        read -p "Press Enter to exit..."
        exit 1
    }
    "$VENV_PY" -m playwright install chromium || {
        echo "ERROR: playwright install chromium failed."
        read -p "Press Enter to exit..."
        exit 1
    }
    echo "ok" > "$DEPS_MARKER"
    echo "    Dependencies installed."
else
    echo "    Dependencies OK."
fi

# ========== STEP 4: Ensure Chrome CDP ==========
echo "[4/5] Checking Chrome CDP ..."
if curl -sf http://127.0.0.1:18800/json/version >/dev/null 2>&1; then
    echo "    CDP already running."
else
    echo "    Starting Chrome with CDP ..."
    CHROME_APP=""
    for candidate in "/Applications/Google Chrome.app" "/Applications/Google Chrome Beta.app"; do
        if [ -d "$candidate" ]; then
            CHROME_APP="$candidate"
            break
        fi
    done
    CDP_PROFILE="$DATA_DIR/chrome-cdp-profile"
    if [ -n "$CHROME_APP" ]; then
        echo "    Chrome app: $CHROME_APP"
        open -n "$CHROME_APP" --args \
            --remote-debugging-port=18800 \
            --user-data-dir="$CDP_PROFILE" \
            --no-first-run \
            --no-default-browser-check \
            "https://precision.dslyy.com/admin#/dashboard" &
        for i in $(seq 1 20); do
            sleep 1
            if curl -sf http://127.0.0.1:18800/json/version >/dev/null 2>&1; then
                echo "    CDP started."
                break
            fi
        done
    else
        echo "    WARNING: Chrome not found."
        echo "    Please start Chrome manually with:"
        echo "      open -a 'Google Chrome' --args --remote-debugging-port=18800 --user-data-dir=\"$CDP_PROFILE\""
    fi
fi

# ========== STEP 5: Start server ==========
echo "[5/5] Starting UI server ..."
cd "$APP_DIR"
"$VENV_PY" -m uvicorn ui_app.server:app \
    --host 127.0.0.1 --port 8790 \
    > "$UI_LOG" 2>&1 &

# Wait for health check
for i in $(seq 1 30); do
    if curl -sf "$UI_URL/api/tasks" >/dev/null 2>&1; then
        echo
        echo "========================================"
        echo "  UI ready: $UI_URL"
        echo "========================================"
        echo
        open "$OPEN_URL"
        exit 0
    fi
    sleep 1
done

echo "ERROR: UI did not start. Check $UI_LOG"
read -p "Press Enter to exit..."
exit 1
