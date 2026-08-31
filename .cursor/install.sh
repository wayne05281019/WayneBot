#!/usr/bin/env bash
# Idempotent Cloud Agent install for WayneBot.
# Prepares system packages, a Python venv with pinned deps, and (best-effort)
# pre-fetches the public market SQLite DB so the bot boots with real data.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "[install] Installing system packages (venv, CJK fonts for charts, tzdata, sqlite headers)"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
  python3-venv \
  python3-pip \
  tzdata \
  fonts-noto-cjk \
  libsqlite3-dev \
  curl \
  unzip

echo "[install] Creating virtual environment (.venv) and installing Python dependencies"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "[install] Ensuring data directory exists"
DB_PATH="${WAYNE_DB_PATH:-data/wayne_market.db}"
mkdir -p "$(dirname "$DB_PATH")"

# Pre-fetch the public market database so the bot has data at boot. This is the
# same artifact main.py would otherwise download on first run; doing it here
# keeps runtime startup fast. Failure here is non-fatal: the app can still boot
# its /health endpoint and re-attempt the download at runtime.
db_size=0
if [ -f "$DB_PATH" ]; then
  db_size="$(stat -c%s "$DB_PATH" 2>/dev/null || echo 0)"
fi
if [ "$db_size" -lt 1000000 ]; then
  RELEASE_URL="${GITHUB_RELEASE_URL:-https://github.com/wayne05281019/WayneBot/releases/download/v1.0-data/waynebot_production_complete.zip}"
  echo "[install] Fetching market database from $RELEASE_URL"
  tmpdir="$(mktemp -d)"
  if curl -fL --retry 3 --retry-delay 4 -o "$tmpdir/db.zip" "$RELEASE_URL"; then
    if unzip -o -q "$tmpdir/db.zip" -d "$tmpdir/extract"; then
      found="$(find "$tmpdir/extract" -name '*.db' -size +1M | head -n 1 || true)"
      if [ -n "$found" ]; then
        cp "$found" "$DB_PATH"
        echo "[install] Installed market DB -> $DB_PATH ($(stat -c%s "$DB_PATH") bytes)"
      else
        echo "[install] WARN: no .db found inside release zip; app will fetch at runtime"
      fi
    else
      echo "[install] WARN: failed to unzip release; app will fetch at runtime"
    fi
  else
    echo "[install] WARN: market DB download failed; app will fetch at runtime"
  fi
  rm -rf "$tmpdir"
else
  echo "[install] Market DB already present ($db_size bytes); skipping download"
fi

echo "[install] Done"
