#!/usr/bin/env bash
# 十人格 VM 真機 walkthrough：每人設不同操作序列 + 截圖
set -euo pipefail
export DISPLAY=:1
WIN="${TG_WIN_ID:-29360132}"
ART=/opt/cursor/artifacts
SHOT="$ART/screenshots/personas"
mkdir -p "$SHOT"

snap() { ffmpeg -y -loglevel error -f x11grab -video_size 1920x1200 -i "$DISPLAY" -frames:v 1 "$SHOT/$1.png" 2>/dev/null || true; }

focus_chat() {
  xdotool windowactivate --sync "$WIN"
  sleep 0.8
  xdotool mousemove 220 130; xdotool click 1
  sleep 1.5
  xdotool mousemove 1050 1020; xdotool click 1
  sleep 0.3
}

send() {
  xdotool key --clearmodifiers ctrl+a BackSpace
  xdotool type --delay 18 "$1"
  xdotool key Return
}

run_persona() {
  local id="$1" name="$2"
  shift 2
  echo "[persona] $id $name"
  focus_chat
  snap "${id}_00_start"
  local step=1
  for action in "$@"; do
    printf -v tag "%s_%02d_%s" "$id" "$step" "$action"
    tag=$(echo "$tag" | tr ' /' '__' | head -c 40)
    echo "  -> $action"
    send "$action"
    sleep "${WAIT_S:-10}"
    snap "$tag"
    step=$((step + 1))
  done
  snap "${id}_99_end"
}

echo "[vm_personas] start"
xdotool windowactivate --sync "$WIN"
sleep 1

# 5 人格：行為完全不同
WAIT_S=12 run_persona p01_weiquan "偉權" "決策卡" "大盤" "資金" "海選"
WAIT_S=10 run_persona p02_gege "哥哥" "觀察" "大盤" "當沖"
WAIT_S=10 run_persona p03_newbie "新手" "/start" "連買區" "說明" "大盤"
WAIT_S=8  run_persona p04_luan "不懂股" "asdfgh" "股票" "持股"
WAIT_S=8  run_persona p05_spam "亂按" "大盤" "資金" "大盤" "資金"

# 5 人格延伸
WAIT_S=10 run_persona p06_hold "長線族" "持股" "觀察" "資金"
WAIT_S=10 run_persona p07_market "只看盤" "大盤" "資金"
WAIT_S=12 run_persona p08_line "愛轉LINE" "海選" "當沖" "隔日沖"
WAIT_S=10 run_persona p09_cmp "比較股" "2330" "2317" "1303"
WAIT_S=10 run_persona p10_night "夜間" "說明" "隔日沖" "大盤"

echo "[vm_personas] done -> $SHOT"
