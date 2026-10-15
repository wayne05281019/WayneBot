# -*- coding: utf-8 -*-
"""恐懼複合用｜美股／外圍歷史：本庫優先，缺欄才外聯 Yahoo 日 K 補齊並落庫。

優先序：``us_overnight`` 本庫 → 缺美股關鍵欄才抓 Yahoo 官方 chart → ``save_us_overnight``
仍缺＝標缺（不准假數交差）。不是買訊。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

from fear_composite import _f, _ymd, us_keys_present
from us_overnight import (
    classify_us_regime,
    load_us_overnight,
    save_us_overnight,
)

logger = logging.getLogger("wayne.fear_us_history")
NY = ZoneInfo("America/New_York")

# 與 us_overnight 同源符號（官方 Yahoo 日 K）
YAHOO_US_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("ixic", "^IXIC"),
    ("spx", "^GSPC"),
    ("dji", "^DJI"),
    ("sox", "^SOX"),
    ("vix", "^VIX"),
    ("tsm", "TSM"),
    ("nvda", "NVDA"),
)
YAHOO_OUTER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("brent", "BZ=F"),
    ("dx_f", "DX-Y.NYB"),
    ("usdtwd", "TWD=X"),
)

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
)


def fetch_yahoo_daily_bars(sym: str, range_: str = "2y") -> List[Dict[str, Any]]:
    """Yahoo 官方日 K 全列（該 range 每一根）。失敗回空列表。"""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1d&range={range_}"
    )
    try:
        resp = _SESSION.get(url, timeout=30)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
    except Exception:
        logger.exception("Yahoo 日 K 失敗 %s", sym)
        return []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    vols = q.get("volume") or []
    out: List[Dict[str, Any]] = []
    prev_c: Optional[float] = None
    for i, ts in enumerate(stamps):
        c = _f(closes[i]) if i < len(closes) else None
        if c is None or c <= 0:
            continue
        d_ny = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(NY)
        ymd = d_ny.strftime("%Y%m%d")
        pct = (c / prev_c - 1.0) * 100.0 if prev_c and prev_c > 0 else None
        out.append(
            {
                "date": ymd,
                "open": _f(opens[i]) if i < len(opens) else None,
                "high": _f(highs[i]) if i < len(highs) else None,
                "low": _f(lows[i]) if i < len(lows) else None,
                "close": c,
                "volume": _f(vols[i]) if i < len(vols) else None,
                "pct": pct,
            }
        )
        prev_c = c
    return out


def build_session_snaps(range_: str = "2y") -> Dict[str, Dict[str, Any]]:
    """美股 session 日 → 合併 snap（含外圍）。每個符號全歷史，不抽日。"""
    by_day: Dict[str, Dict[str, Any]] = {}
    for key, sym in YAHOO_US_FIELDS:
        bars = fetch_yahoo_daily_bars(sym, range_=range_)
        time.sleep(0.08)
        for b in bars:
            d = b["date"]
            snap = by_day.setdefault(d, {})
            if key == "vix":
                snap["vix"] = b["close"]
                if b.get("pct") is not None:
                    snap["vix_pct"] = b["pct"]
            else:
                snap[f"{key}_pct"] = b.get("pct")
                snap[f"{key}_px"] = b["close"]
        logger.info("Yahoo %s → %s 根", sym, len(bars))
    for key, sym in YAHOO_OUTER_FIELDS:
        bars = fetch_yahoo_daily_bars(sym, range_=range_)
        time.sleep(0.08)
        for b in bars:
            d = b["date"]
            snap = by_day.setdefault(d, {})
            snap[f"{key}_px"] = b["close"]
            snap[f"{key}_pct"] = b.get("pct")
        logger.info("Yahoo %s → %s 根", sym, len(bars))
    for d, snap in by_day.items():
        snap["regime"] = classify_us_regime(snap)
        snap["ok"] = us_keys_present(snap)
        snap["us_session"] = d
        snap["fetched_at"] = datetime.now(timezone.utc).isoformat()
        snap["source"] = "yahoo_daily_backfill"
    return by_day


def map_us_session_to_tw_day(
    tw_day: str, us_by_session: Dict[str, Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    """台股開市日 D ← 嚴格早於 D 的最近美股 session（開盤前可知）。"""
    day = _ymd(tw_day)
    if not day:
        return "", {}
    best = ""
    for d in us_by_session.keys():
        if d < day and d > best:
            best = d
    if not best:
        return "", {}
    return best, dict(us_by_session.get(best) or {})


def outer_present(snap: Dict[str, Any]) -> bool:
    snap = snap or {}
    return any(
        _f(snap.get(k)) is not None
        for k in ("brent_pct", "dx_f_pct", "usdtwd_pct")
    )


def load_us_prefer_db(db_path: str, tw_day: str) -> Dict[str, Any]:
    """只讀本庫。"""
    return dict(load_us_overnight(db_path, _ymd(tw_day)) or {})


def backfill_us_overnight_for_tw_days(
    db_path: str,
    tw_days: Sequence[str],
    *,
    range_: str = "2y",
    fill_outer_only_gaps: bool = True,
) -> Dict[str, Any]:
    """對台股開市日：本庫已有美股鍵則沿用；缺才用 Yahoo 全日史對映補齊並落庫。

    回傳統計：already／filled／still_missing／outer_filled。
    """
    days = [_ymd(d) for d in tw_days if _ymd(d)]
    already = 0
    need: List[str] = []
    need_outer: List[str] = []
    for d in days:
        snap = load_us_prefer_db(db_path, d)
        if us_keys_present(snap):
            already += 1
            if fill_outer_only_gaps and not outer_present(snap):
                need_outer.append(d)
        else:
            need.append(d)

    filled = 0
    outer_filled = 0
    still_missing: List[str] = []
    us_by: Dict[str, Dict[str, Any]] = {}
    if need or need_outer:
        us_by = build_session_snaps(range_=range_)

    for d in need:
        _sess, snap = map_us_session_to_tw_day(d, us_by)
        if not us_keys_present(snap):
            still_missing.append(d)
            continue
        # 落庫：鍵＝台股開市日 as_of（與早報／靜默一致）
        save_us_overnight(db_path, d, snap)
        filled += 1

    for d in need_outer:
        if d in need:
            continue  # 上面已整包補
        existing = load_us_prefer_db(db_path, d)
        _sess, hist = map_us_session_to_tw_day(d, us_by)
        if not hist:
            continue
        merged = dict(existing)
        changed = False
        for k in (
            "brent_px",
            "brent_pct",
            "dx_f_px",
            "dx_f_pct",
            "usdtwd_px",
            "usdtwd_pct",
        ):
            if merged.get(k) is None and hist.get(k) is not None:
                merged[k] = hist[k]
                changed = True
        if changed:
            merged["regime"] = merged.get("regime") or classify_us_regime(merged)
            merged["fetched_at"] = datetime.now(timezone.utc).isoformat()
            merged["source"] = (merged.get("source") or "") + "+outer_backfill"
            save_us_overnight(db_path, d, merged)
            outer_filled += 1

    return {
        "n_tw_days": len(days),
        "already_in_db": already,
        "filled_from_yahoo": filled,
        "outer_filled": outer_filled,
        "still_missing": still_missing,
        "n_still_missing": len(still_missing),
        "yahoo_sessions": len(us_by),
        "policy": "db_first_then_official_yahoo_persist",
    }
