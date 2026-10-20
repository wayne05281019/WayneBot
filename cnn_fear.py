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

# 官網儀表檔位（使用者 2026-10-20 鎖中文帶＋英文）。
_BANDS = (
    (25.0, "extreme fear", "極度恐懼", "Extreme Fear", "#e53935"),
    (45.0, "fear", "恐懼", "Fear", "#ef6c00"),
    (55.0, "neutral", "中立", "Neutral", "#f9a825"),
    (75.0, "greed", "貪婪", "Greed", "#7cb342"),
    (100.0, "extreme greed", "極度貪婪", "Extreme Greed", "#2e7d32"),
)

_HISTORY_SPECS = (
    ("score", "當日", 0),
    ("previous_close", "前一交易日", 1),
    ("previous_1_week", "一週前", 5),
    ("previous_1_month", "一個月前", 21),
    ("previous_1_year", "一年前", 252),
)


def fear_greed_band(score: float, rating: str = "") -> str:
    """檔位跟官方 rating／分數綁，不跟 VIX 數字綁。"""
    key = str(rating or "").strip().lower()
    for _cap, name, zh, _en, _color in _BANDS:
        if key == name:
            return zh
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    for cap, _name, zh, _en, _color in _BANDS:
        if s <= cap:
            return zh
    return ""


def fear_greed_band_en(score: float, rating: str = "") -> str:
    key = str(rating or "").strip().lower()
    for _cap, name, _zh, en, _color in _BANDS:
        if key == name:
            return en
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    for cap, _name, _zh, en, _color in _BANDS:
        if s <= cap:
            return en
    return ""


def fear_greed_badge_color(score: float, rating: str = "") -> str:
    key = str(rating or "").strip().lower()
    for _cap, name, _zh, _en, color in _BANDS:
        if key == name:
            return color
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "#9e9e9e"
    for cap, _name, _zh, _en, color in _BANDS:
        if s <= cap:
            return color
    return "#9e9e9e"


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


def _slash(ymd: str) -> str:
    s = str(ymd or "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return s


def _nth_prev_us_day(ymd: str, n: int) -> str:
    """往前回推 n 個美股開市日。n=0 回自己。"""
    if n <= 0:
        return str(ymd or "")
    try:
        from us_holidays import previous_trading_day
    except Exception:
        return ""
    cur = str(ymd or "")
    for _ in range(n):
        cur = previous_trading_day(cur)
        if not cur:
            return ""
    return cur


def _history_rows(block: Dict[str, Any], session_ymd: str) -> List[Dict[str, str]]:
    """市場情緒變化趨勢列。缺官方分數就略過該列，不准補假數。"""
    rows: List[Dict[str, str]] = []
    for key, lab, steps in _HISTORY_SPECS:
        if key == "score":
            score = _as_float(block.get("score"))
            rating = str(block.get("rating") or "")
            day = session_ymd
        else:
            score = _as_float(block.get(key))
            rating = ""
            day = _nth_prev_us_day(session_ymd, steps)
        if score is None:
            continue
        band = fear_greed_band(score, rating)
        if not band:
            continue
        rows.append(
            {
                "label": lab,
                "date": _slash(day) if day else "",
                "face": gauge_face(score),
                "band": band,
                "band_en": fear_greed_band_en(score, rating),
                "color": fear_greed_badge_color(score, rating),
                "score": f"{score:.2f}",
            }
        )
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
        import requests

        resp = requests.get(
            _URL.format(ymd=slash),
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        payload = resp.json()
    except Exception:
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
            from zoneinfo import ZoneInfo

            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            # 美股交易日看紐約日，不准用 UTC 日把 10/19 收誤判成 10/20。
            live_day = dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y%m%d")
        except ValueError:
            live_day = ""
    history_ok = False
    if live_score is not None and live_day == ymd:
        score, rating = live_score, live_rating
        history_ok = True
        display_block = dict(block)
    else:
        picked = _score_from_historical(payload, ymd)
        if picked is not None:
            score, rating = picked
            if not rating:
                rating = live_rating
            # 歷史日：當日分數用歷史點；previous_* 不准拿「現在」那針的去冒充舊日。
            display_block = {"score": score, "rating": rating}
        elif live_score is not None and not live_day:
            score, rating = live_score, live_rating
            history_ok = True
            display_block = dict(block)
        else:
            return None
    band = fear_greed_band(score, rating)
    if not band:
        return None
    return {
        "score": score,
        "face": gauge_face(score),
        "rating": rating,
        "band": band,
        "band_en": fear_greed_band_en(score, rating),
        "session": ymd,
        "source": "cnn",
        "history": _history_rows(display_block, ymd) if history_ok else _history_rows(display_block, ymd),
    }
