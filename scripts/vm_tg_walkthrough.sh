#!/usr/bin/env bash
# VM Telegram Web 真機 walkthrough：錄影 + 大盤/資金按鈕測試
set -euo pipefail
export DISPLAY=:1
WIN=29360132
ART=/opt/cursor/artifacts
SHOT="$ART/screenshots"
VID="$ART/vm_tg_menu_walkthrough.mp4"
mkdir -p "$SHOT"

snap() {
  local name="$1"
  ffmpeg -y -loglevel error -f x11grab -video_size 1920x1200 -i "$DISPLAY" \
    -frames:v 1 "$SHOT/${name}.png" 2>/dev/null || true
}

echo "[vm_tg] start recording -> $VID"
ffmpeg -y -loglevel error -f x11grab -framerate 15 -video_size 1920x1200 -i "$DISPLAY" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$VID" &
REC_PID=$!
sleep 1

xdotool windowactivate --sync "$WIN"
sleep 1
# 點左側 WayneBot 對話
xdotool mousemove 220 130; xdotool click 1
sleep 2
snap "vm_tg_00_chat.png"

# 點右側訊息輸入框
xdotool mousemove 1050 1020; xdotool click 1
sleep 0.5
snap "vm_tg_01_ready.png"

send_btn() {
  local label="$1"
  local tag="$2"
  echo "[vm_tg] send: $label"
  xdotool mousemove 1050 1020; xdotool click 1
  sleep 0.2
  xdotool key --clearmodifiers ctrl+a BackSpace
  xdotool type --delay 20 "$label"
  xdotool key Return
  sleep 12
  snap "vm_tg_${tag}.png"
}

send_btn "大盤" "02_market"
send_btn "資金" "03_flow"
send_btn "持股" "04_portfolio"

sleep 2
kill "$REC_PID" 2>/dev/null || true
wait "$REC_PID" 2>/dev/null || true
snap "vm_tg_05_final.png"

echo "[vm_tg] done video=$VID"
