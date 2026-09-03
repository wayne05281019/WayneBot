#!/usr/bin/env bash
# 話筒真機：連買區精靈逐步走完（生產 Bot 若尚未上線會拍下現況）
set -euo pipefail
export DISPLAY=:1
WIN="${TG_WIN_ID:-29360132}"
ART=/opt/cursor/artifacts
SHOT="$ART/screenshots/streak_live"
VID="$ART/vm_streak_wizard_live.mp4"
mkdir -p "$SHOT"

snap() {
  ffmpeg -y -loglevel error -f x11grab -video_size 1920x1200 -i "$DISPLAY" \
    -frames:v 1 "$SHOT/${1}.png" 2>/dev/null || true
}

send() {
  local label="$1" tag="$2" wait_s="${3:-8}"
  echo "[streak_live] $label"
  xdotool mousemove 1050 1020; xdotool click 1
  sleep 0.2
  xdotool key --clearmodifiers ctrl+a BackSpace
  xdotool type --delay 18 "$label"
  xdotool key Return
  sleep "$wait_s"
  snap "$tag"
}

echo "[streak_live] recording -> $VID"
ffmpeg -y -loglevel error -f x11grab -framerate 12 -video_size 1920x1200 -i "$DISPLAY" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$VID" &
REC_PID=$!
sleep 1

xdotool windowactivate --sync "$WIN"
sleep 1
xdotool mousemove 220 130; xdotool click 1
sleep 2
xdotool mousemove 1050 1020; xdotool click 1
sleep 0.4
snap "00_ready"

send "連買區" "01_streak" 6
send "外資" "02_foreign" 5
send "上市" "03_tw" 10
send "19" "04_days19" 10
send "1524" "05_1524" 16
send "回主選單" "06_back" 5
send "大盤" "07_market" 10

# 交錯：連買進行中再按大盤（單帳號話筒能做到的「不互相卡死」）
send "連買區" "08_streak2" 5
send "投信" "09_trust" 5
send "大盤" "10_market_interrupt" 10
send "連買區" "11_streak3" 5

sleep 2
kill "$REC_PID" 2>/dev/null || true
wait "$REC_PID" 2>/dev/null || true
snap "99_final"
echo "[streak_live] done $VID -> $SHOT"
