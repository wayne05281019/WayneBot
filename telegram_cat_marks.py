"""WayneBot 分類用小型動態表情（跟字一樣大，不是大圖）。"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, Tuple

from PIL import Image, ImageDraw

MARK_SPECS: Dict[str, Tuple[str, Tuple[int, int, int], str]] = {
    "revenue_cross": ("📈", (232, 140, 50), "bars"),
    "select_01": ("🔥", (230, 80, 50), "flame"),
    "select_02": ("🏆", (220, 180, 50), "cup"),
    "select_03": ("💎", (140, 100, 210), "diamond"),
    "select_04": ("🌱", (60, 170, 90), "sprout"),
    "day_trade": ("⚡", (240, 190, 40), "bolt"),
    "overnight": ("🌙", (80, 130, 210), "moon"),
}

SET_NAME = "waynebot_marks_by_WC_ai_trade_bot"
IDS_PATH = os.path.join(os.path.dirname(__file__), "telegram_cat_mark_ids.json")


def load_mark_ids() -> Dict[str, str]:
    if not os.path.isfile(IDS_PATH):
        return {}
    try:
        with open(IDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: str(v) for k, v in data.items() if v}
    except Exception:
        return {}


def tg_mark(key: str, fallback: str) -> str:
    eid = load_mark_ids().get(key)
    if not eid:
        return fallback
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


def _rot(cx, cy, x, y, a):
    xr, yr = x - cx, y - cy
    ca, sa = math.cos(a), math.sin(a)
    return cx + xr * ca - yr * sa, cy + xr * sa + yr * ca


def _pillar(d, cx, cy, a, box, col):
    x0, y0, x1, y1 = box
    pts = [
        _rot(cx, cy, x0, y0, a),
        _rot(cx, cy, x1, y0, a),
        _rot(cx, cy, x1, y1, a),
        _rot(cx, cy, x0, y1, a),
    ]
    d.polygon(pts, fill=col)


def render_webm(kind: str, rgb: Tuple[int, int, int], path: str, frames: int = 24) -> str:
    tmp = path + "_frames"
    os.makedirs(tmp, exist_ok=True)
    size, cx, cy = 100, 50, 50
    col = rgb + (255,)
    for i in range(frames):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        t = i / max(frames - 1, 1)
        a = t * 2 * math.pi
        phase = 0 if t < 0.34 else (1 if t < 0.67 else 2)
        if phase == 0:
            _pillar(d, cx, cy, a, (28, 28, 42, 72), col)
            _pillar(d, cx, cy, a, (50, 28, 58, 72), col)
            _pillar(d, cx, cy, a, (46, 28, 70, 36), col)
            _pillar(d, cx, cy, a, (46, 64, 70, 72), col)
        elif phase == 1:
            _pillar(d, cx, cy, a, (46, 30, 54, 78), col)
            _pillar(d, cx, cy, a, (30, 28, 70, 42), col)
        elif kind == "flame":
            _pillar(d, cx, cy, a, (44, 26, 56, 76), col)
            _pillar(d, cx, cy, a, (32, 48, 44, 76), col)
            _pillar(d, cx, cy, a, (56, 40, 68, 76), col)
        elif kind == "cup":
            _pillar(d, cx, cy, a, (34, 32, 66, 58), col)
            _pillar(d, cx, cy, a, (46, 58, 54, 78), col)
            _pillar(d, cx, cy, a, (38, 74, 62, 80), col)
        elif kind == "diamond":
            pts = [
                _rot(cx, cy, 50, 22, a),
                _rot(cx, cy, 74, 50, a),
                _rot(cx, cy, 50, 78, a),
                _rot(cx, cy, 26, 50, a),
            ]
            d.polygon(pts, fill=col)
        elif kind == "sprout":
            _pillar(d, cx, cy, a, (46, 40, 54, 78), col)
            _pillar(d, cx, cy, a, (28, 36, 46, 50), col)
            _pillar(d, cx, cy, a, (54, 30, 72, 46), col)
        elif kind == "bolt":
            pts = [
                _rot(cx, cy, 58, 22, a),
                _rot(cx, cy, 38, 50, a),
                _rot(cx, cy, 52, 50, a),
                _rot(cx, cy, 42, 78, a),
                _rot(cx, cy, 66, 46, a),
                _rot(cx, cy, 50, 46, a),
            ]
            d.polygon(pts, fill=col)
        elif kind == "moon":
            _pillar(d, cx, cy, a, (36, 28, 64, 72), col)
            _pillar(d, cx, cy, a, (48, 32, 72, 60), (18, 22, 28, 255))
        else:
            _pillar(d, cx, cy, a, (28, 50, 38, 74), col)
            _pillar(d, cx, cy, a, (45, 32, 55, 74), col)
            _pillar(d, cx, cy, a, (62, 44, 72, 74), col)
        im.save(os.path.join(tmp, f"f{i:03d}.png"))
    os.system(
        "ffmpeg -y -framerate 8 -i "
        f"{tmp}/f%03d.png -c:v libvpx-vp9 -pix_fmt yuva420p -an "
        "-vf scale=100:100 -b:v 60k -deadline good -auto-alt-ref 0 "
        f"{path} >/dev/null 2>&1"
    )
    return path
