# -*- coding: utf-8 -*-
"""CNN Fear & Greed 官方讀數。話筒圖卡用指針儀表；不准改寫 VIX、不准填假分數。"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("WayneBot.CnnFear")

_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{ymd}"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 官網儀表檔位（使用者 2026-10-20 鎖中文帶）。
_BANDS = (
    (25.0, "extreme fear", "極度恐懼"),
    (45.0, "fear", "恐懼"),
    (55.0, "neutral", "中立"),
    (75.0, "greed", "貪婪"),
    (100.0, "extreme greed", "極度貪婪"),
)

_HISTORY_KEYS = (
    ("previous_close", "前一日"),
    ("previous_1_week", "一週前"),
    ("previous_1_month", "一個月前"),
    ("previous_1_year", "一年前"),
)


def fear_greed_band(score: float, rating: str = "") -> str:
    """檔位跟官方 rating／分數綁，不跟 VIX 數字綁。"""
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


def _as_float(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _history_rows(block: Dict[str, Any]) -> List[Dict[str, str]]:
    """官網歷史列。缺欄就略過，不准補假數。"""
    rows: List[Dict[str, str]] = []
    for key, lab in _HISTORY_KEYS:
        score = _as_float(block.get(key))
        if score is None:
            continue
        band = fear_greed_band(score)
        if not band:
            continue
        rows.append({"label": lab, "face": gauge_face(score), "band": band, "score": f"{score:.2f}"})
    return rows


def _score_from_historical(payload: Dict[str, Any], ymd: str) -> Optional[Tuple[float, str]]:
    """歷史序列對上該美股日就用那天；對不上不准硬湊最新分。"""
    hist = payload.get("fear_and_greed_historical")
    if not isinstance(hist, dict):
        return None
    data = hist.get("data")
    if not isinstance(data, list):
        return None
    for row in data:
        if not isinstance(row, dict):
            continue
        ts = row.get("x") or row.get("timestamp")
        score = _as_float(row.get("y") if row.get("y") is not None else row.get("score"))
        if ts is None or score is None:
            continue
        try:
            ms = float(ts)
            if ms > 1e12:
                ms /= 1000.0
            day = datetime.fromtimestamp(ms, tz=timezone.utc).strftime("%Y%m%d")
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if day != ymd:
            continue
        return score, str(row.get("rating") or "")
    return None


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
    if not isinstance(payload, dict):
        return None
    block = payload.get("fear_and_greed")
    if not isinstance(block, dict):
        return None
    live_score = _as_float(block.get("score"))
    live_rating = str(block.get("rating") or "")
    live_day = ""
    ts = block.get("timestamp")
    if ts:
        try:
            live_day = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime(
                "%Y%m%d"
            )
        except ValueError:
            live_day = ""
    history_ok = False
    if live_score is not None and live_day == ymd:
        score, rating = live_score, live_rating
        history_ok = True
    else:
        picked = _score_from_historical(payload, ymd)
        if picked is None:
            return None
        score, rating = picked
        if not rating:
            rating = live_rating
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
        # previous_* 是相對官網「現在」那針；只有針就是當日才附歷史列。
        "history": _history_rows(block) if history_ok else [],
    }
