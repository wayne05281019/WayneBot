#!/usr/bin/env bash
# VM Telegram Web 全選單 walkthrough（十顆按鈕 + 錄影）
set -euo pipefail
export DISPLAY=:1
WIN="${TG_WIN_ID:-29360132}"
ART=/opt/cursor/artifacts
SHOT="$ART/screenshots"
VID="$ART/vm_tg_full_menu_walkthrough.mp4"
mkdir -p "$SHOT"

BUTTONS=(決策卡 當沖 持股 觀察 海選 隔日沖 資金 說明 選單 大盤)
WAIT="${TG_BTN_WAIT:-14}"

snap() {
  ffmpeg -y -loglevel error -f x11grab -video_size 1920x1200 -i "$DISPLAY" \
    -frames:v 1 "$SHOT/vm_full_${1}.png" 2>/dev/null || true
}

click() { xdotool mousemove "$1" "$2"; xdotool click 1; }

echo "[vm_full] recording -> $VID"
ffmpeg -y -loglevel error -f x11grab -framerate 12 -video_size 1920x1200 -i "$DISPLAY" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$VID" &
REC_PID=$!
sleep 1

xdotool windowactivate --sync "$WIN"
sleep 1
click 220 130
sleep 2
click 1050 1020
sleep 0.5
snap "00_ready"

i=1
for label in "${BUTTONS[@]}"; do
  tag=$(printf "%02d" "$i")
  echo "[vm_full] ($tag) $label"
  click 1050 1020
  sleep 0.2
  xdotool key --clearmodifiers ctrl+a BackSpace
  xdotool type --delay 18 "$label"
  xdotool key Return
  sleep "$WAIT"
  snap "${tag}_${label}"
  i=$((i + 1))
done

sleep 2
kill "$REC_PID" 2>/dev/null || true
wait "$REC_PID" 2>/dev/null || true
snap "99_final"
echo "[vm_full] done $VID"
