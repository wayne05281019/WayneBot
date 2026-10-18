# -*- coding: utf-8 -*-
"""CNN Fear & Greed 官方讀數。話筒只顯示接到的分數與檔位，不准改寫 VIX。"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("WayneBot.CnnFear")

_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{ymd}"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 官網儀表檔位。極度恐慌只對 extreme fear（約 0–25）。
_BANDS = (
    (25.0, "extreme fear", "極度恐慌"),
    (45.0, "fear", "恐慌"),
    (55.0, "neutral", "中性"),
    (75.0, "greed", "貪婪"),
    (100.0, "extreme greed", "極度貪婪"),
)


def fear_greed_band(score: float, rating: str = "") -> str:
    """極度恐慌跟極端恐懼檔綁在一起，不跟 VIX 數字綁。"""
    key = str(rating or "").strip().lower()
    for _cap, name, zh in _BANDS:
        if key == name:
            return zh
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    for cap, _name, zh in _BANDS:
        if s <= cap:
            return zh
    return ""


def gauge_face(score: float) -> str:
    """官網針是整數。17.94 顯示 18，不另編一個指數。"""
    return str(int(round(float(score))))


def fetch_cnn_fear_greed(session_ymd: str) -> Optional[Dict[str, Any]]:
    """該美股交易日的官方 Fear & Greed。抓不到回 None，不准填假分數。"""
    ymd = str(session_ymd or "").replace("-", "")[:8]
    if len(ymd) != 8 or not ymd.isdigit():
        return None
    slash = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    req = urllib.request.Request(
        _URL.format(ymd=slash),
        headers={
            "User-Agent": _UA,
            "Accept": "application/json",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        logger.warning("CNN Fear & Greed 沒接到 %s", slash, exc_info=True)
        return None
    block = payload.get("fear_and_greed") if isinstance(payload, dict) else None
    if not isinstance(block, dict) or block.get("score") is None:
        return None
    try:
        score = float(block["score"])
    except (TypeError, ValueError):
        return None
    rating = str(block.get("rating") or "")
    band = fear_greed_band(score, rating)
    if not band:
        return None
    return {
        "score": score,
        "face": gauge_face(score),
        "rating": rating,
        "band": band,
        "session": ymd,
        "source": "cnn",
    }
