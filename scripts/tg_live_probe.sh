#!/usr/bin/env bash
# VM Telegram Web 真機話筒探測：開 WayneBot 對話並依序送主選單按鈕
set -euo pipefail
export DISPLAY=:1
BOT_URL="${TG_BOT_URL:-https://web.telegram.org/k/#@WC_ai_trade_bot}"
WIN="${TG_WIN_ID:-$(xdotool search --name 'Telegram' 2>/dev/null | tail -1)}"
if [[ -z "${WIN:-}" ]]; then
  WIN="$(xdotool search --class 'google-chrome' 2>/dev/null | tail -1)"
fi
SHOT=/opt/cursor/artifacts/screenshots/tg_probe
mkdir -p "$SHOT"

click_rel() {
  xdotool mousemove --window "$WIN" "$1" "$2"
  xdotool click 1
}

shot() {
  ffmpeg -y -loglevel error -f x11grab -video_size 1920x1200 -i "$DISPLAY" \
    -frames:v 1 "$SHOT/$1.png" 2>/dev/null || true
}

open_waynebot() {
  xdotool windowactivate --sync "$WIN"
  sleep 0.5
  echo "$BOT_URL" | xclip -selection clipboard 2>/dev/null || true
  xdotool key --clearmodifiers ctrl+l
  sleep 0.25
  xdotool key --clearmodifiers ctrl+v
  sleep 0.2
  xdotool key Return
  sleep 10
  for _ in 1 2; do xdotool key Escape; sleep 0.1; done
  # 聚焦訊息輸入框（K 版底部）
  click_rel 700 980
  sleep 0.4
}

send_btn() {
  local label="$1" tag="$2"
  click_rel 700 980
  sleep 0.15
  xdotool key --clearmodifiers ctrl+a BackSpace
  xdotool type --delay 10 "$label"
  xdotool key Return
  sleep "${WAIT_S:-16}"
  shot "$tag"
  echo "[tg_probe] $label -> $SHOT/${tag}.png"
}

echo "[tg_probe] window=$WIN url=$BOT_URL"
open_waynebot
shot "00_chat_open"

WAIT_S=16
send_btn "大盤" "01_market"
send_btn "資金" "02_flow"
send_btn "持股" "03_portfolio"
send_btn "連買區" "04_streak"
echo "[tg_probe] done"
