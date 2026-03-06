#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -r requirements.txt -r requirements-ui.txt

PORT="${1:-8791}"
echo "UI starting at: http://127.0.0.1:${PORT}"
exec ./.venv/bin/python -m uvicorn ui_app.server:app --host 127.0.0.1 --port "${PORT}" --reload
