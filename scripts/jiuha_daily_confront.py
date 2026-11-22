#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""啾哈逐日事件對質（非買訊；不准改黃金買點）。

語料：data/jiuha_corpus/jiuha.sqlite
行情：data/wayne_market.db
輸出：/opt/cursor/artifacts/jiuha/deep/confront/

  python3 scripts/jiuha_daily_confront.py
  python3 scripts/jiuha_daily_confront.py --sessions 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiuha_observe import (  # noqa: E402
    AUTHOR_NAME,
    Bar,
    TAIPEI,
    _finite,
    _pct,
    _ymd,
    extract_mentioned_levels,
    load_index_bars,
    load_margin_series,
)

DEFAULT_CORPUS = "/workspace/data/jiuha_corpus/jiuha.sqlite"
DEFAULT_MARKET = "/workspace/data/wayne_market.db"
DEFAULT_OUT = "/opt/cursor/artifacts/jiuha/deep/confront"

_LOT_RE = re.compile(
    r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{4,6})(?:\s*口|\s*萬口)"
)
_COND_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "margin_speed",
        re.compile(r"融資.*(速度|跌得不|不夠快|去槓桿)|速度差|清算"),
    ),
    (
        "shrink_up",
        re.compile(r"縮量.*(漲|反彈)|漲.*縮量|空手回補|逃命窗"),
    ),
    (
        "triple_sync",
        re.compile(r"三同步|減空.*現貨|現貨.*台幣|台幣.*(外資|升值)|外資.*(減空|回補)"),
    ),
    (
        "false_break",
        re.compile(r"假突破|頸線.*突破|突破.*獵|獵殺|有效突破"),
    ),
]


def _is_complete_bar(b: Optional[Bar]) -> bool:
    if b is None:
        return False
    if None in (b.open, b.high, b.low, b.close):
        return False
    # 開高低收全同＝未收完整柱／戳記，不當官方收（對齊盤中未收不當收）
    if b.open == b.high == b.low == b.close:
        return False
    if b.high is not None and b.low is not None and b.high < b.low:
        return False
    return True


def _session_list(twii: Sequence[Bar]) -> List[str]:
    return [b.date for b in sorted(twii, key=lambda x: x.date) if b.date]


def _next_session(sessions: Sequence[str], day: str) -> Optional[str]:
    for d in sessions:
        if d > day:
            return d
    return None


def _prev_session(sessions: Sequence[str], day: str) -> Optional[str]:
    prev = None
    for d in sessions:
        if d >= day:
            break
        prev = d
    return prev


def load_author_posts(corpus_db: str) -> List[Dict[str, Any]]:
    if not corpus_db or not os.path.isfile(corpus_db):
        return []
    con = sqlite3.connect(corpus_db, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT id, article_id, kind, text, title, published_at_taipei, source_url
            FROM records
            WHERE is_author_judgment=1 AND kind IN ('main','reply')
            ORDER BY published_at_taipei ASC
            """
        ).fetchall()
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        pub = str(r[5] or "")
        day = _ymd(pub[:10].replace("-", "")) if pub else ""
        if not day and pub:
            day = _ymd(pub)
        out.append(
            {
                "id": str(r[0]),
                "article_id": str(r[1]),
                "kind": str(r[2]),
                "text": str(r[3] or ""),
                "title": str(r[4] or ""),
                "published_at_taipei": pub,
                "asof": day,
                "source_url": str(r[6] or ""),
            }
        )
    return out


def extract_lots(text: str) -> List[float]:
    out: List[float] = []
    for m in _LOT_RE.finditer(text or ""):
        raw = m.group(0)
        num = m.group(1).replace(",", "")
        v = _finite(num)
        if v is None:
            continue
        if "萬口" in raw:
            v = v * 10000.0
        # 合理外資淨空口數窗
        if 1000 <= v <= 500000:
            out.append(v)
    seen = set()
    uniq: List[float] = []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq[:10]


def detect_conditions(text: str) -> List[str]:
    hits: List[str] = []
    for name, pat in _COND_PATTERNS:
        if pat.search(text or ""):
            hits.append(name)
    return hits


def load_inst_by_date(market_db: str) -> Dict[str, Dict[str, Any]]:
    """法人現貨：優先 market_inst_lots_daily（張）；否則 BFI82U 億元（只認方向／有數列）。"""
    if not market_db or not os.path.isfile(market_db):
        return {}
    con = sqlite3.connect(market_db, timeout=30.0)
    out: Dict[str, Dict[str, Any]] = {}
    try:
        has_lots = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_inst_lots_daily'"
        ).fetchone()
        if has_lots:
            rows = con.execute(
                """
                SELECT REPLACE(CAST(date AS TEXT),'-',''),
                       foreign_net, trust_net, dealer_net, three_net, source
                FROM market_inst_lots_daily
                """
            ).fetchall()
            for r in rows:
                d = _ymd(r[0])
                if not d:
                    continue
                out[d] = {
                    "foreign_net": _finite(r[1]),
                    "trust_net": _finite(r[2]),
                    "dealer_net": _finite(r[3]),
                    "three_net": _finite(r[4]),
                    "source": str(r[5] or ""),
                    "unit": "lots",
                }
        has_bfi = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_inst_bfi_daily'"
        ).fetchone()
        if has_bfi:
            rows = con.execute(
                """
                SELECT REPLACE(CAST(date AS TEXT),'-',''),
                       foreign_net_yi, trust_net_yi, dealer_net_yi, three_net_yi, source
                FROM market_inst_bfi_daily
                """
            ).fetchall()
            for r in rows:
                d = _ymd(r[0])
                if not d or d in out:
                    continue  # 已有張數列不覆寫
                # 三同步只認方向；單位標 yi，不准跟張數混算絕對值
                out[d] = {
                    "foreign_net": _finite(r[1]),
                    "trust_net": _finite(r[2]),
                    "dealer_net": _finite(r[3]),
                    "three_net": _finite(r[4]),
                    "source": str(r[5] or "TWSE_BFI82U"),
                    "unit": "yi",
                }
    except sqlite3.Error:
        return out
    finally:
        con.close()
    return out


def load_foreign_fut_oi(market_db: str) -> Dict[str, Dict[str, Any]]:
    """外資及陸資 臺股期貨 OI；稀疏日＝缺欄。"""
    if not market_db or not os.path.isfile(market_db):
        return {}
    con = sqlite3.connect(market_db, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''),
                   oi_long, oi_short, oi_net
            FROM futures_inst_oi
            WHERE contract='臺股期貨' AND item='外資及陸資'
            """
        ).fetchall()
    finally:
        con.close()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = _ymd(r[0])
        if not d:
            continue
        out[d] = {
            "oi_long": _finite(r[1]),
            "oi_short": _finite(r[2]),
            "oi_net": _finite(r[3]),
        }
    return out


def _bar_map(bars: Sequence[Bar]) -> Dict[str, Bar]:
    return {b.date: b for b in bars if b.date}


def _vol_vs_n(
    twii_by: Dict[str, Bar], sessions: Sequence[str], day: str, n: int
) -> Optional[float]:
    b0 = twii_by.get(day)
    if not b0 or b0.volume is None:
        return None
    idx = list(sessions).index(day) if day in sessions else -1
    if idx < 0:
        return None
    prev = sessions[max(0, idx - n) : idx]
    vols = [
        twii_by[d].volume
        for d in prev
        if d in twii_by and twii_by[d].volume is not None
    ]
    if not vols:
        return None
    avg = sum(vols) / len(vols)
    if avg == 0:
        return None
    return b0.volume / avg


def _chg_pct(twii_by: Dict[str, Bar], day: str, prev: Optional[str]) -> Optional[float]:
    b0 = twii_by.get(day)
    b1 = twii_by.get(prev) if prev else None
    if not b0 or not b1:
        return None
    return _pct(b0.close, b1.close)


def _margin_speed_for_day(
    day: str,
    twii_by: Dict[str, Bar],
    margin_by: Dict[str, Dict[str, Any]],
    sessions: Sequence[str],
) -> Dict[str, Any]:
    m0 = margin_by.get(day)
    if not m0:
        return {"ok": False, "missing": "市場融資當日列"}
    # 前一筆有融資日
    m_prev = None
    for d in reversed(list(sessions)):
        if d < day and d in margin_by:
            m_prev = margin_by[d]
            m_prev_date = d
            break
    else:
        return {"ok": False, "missing": "市場融資前一列"}
    b0 = twii_by.get(day)
    ba = twii_by.get(m_prev_date)
    if not _is_complete_bar(b0) or not _is_complete_bar(ba):
        return {"ok": False, "missing": "加權完整柱（融資窗）"}
    margin_chg = _pct(m0.get("margin_bal_k"), m_prev.get("margin_bal_k"))
    idx_span = _pct(b0.close, ba.close)
    if margin_chg is None or idx_span is None:
        return {"ok": False, "missing": "融資或指數變動無法算"}
    speed_gap = margin_chg - idx_span
    return {
        "ok": True,
        "margin_chg_pct": round(margin_chg, 3),
        "idx_span_pct": round(idx_span, 3),
        "speed_gap_pp": round(speed_gap, 3),
        "margin_asof": day,
        "margin_prev": m_prev_date,
    }


def _fx_chg(
    fx_by: Dict[str, Bar], day: str, sessions: Sequence[str]
) -> Dict[str, Any]:
    f0 = fx_by.get(day)
    stale = False
    if f0 is None:
        # 允許落後，但標 stale；對質三同步時 stale＝缺欄（不准當命中）
        older = [d for d in sessions if d <= day and d in fx_by]
        if not older:
            return {"ok": False, "missing": "美金台幣"}
        # 若非當日，視為缺當日欄
        use = older[-1]
        if use != day:
            return {
                "ok": False,
                "missing": f"美金台幣僅至{use}",
                "stale_asof": use,
                "close": fx_by[use].close,
            }
        f0 = fx_by[use]
    prev = _prev_session([d for d in sessions if d in fx_by], f0.date)
    f1 = fx_by.get(prev) if prev else None
    chg = _pct(f0.close, f1.close) if f1 else None
    return {
        "ok": True,
        "close": f0.close,
        "chg_pct": None if chg is None else round(chg, 4),
        "asof": f0.date,
        "stale": stale,
    }


def _fut_short_delta(
    fut_by: Dict[str, Dict[str, Any]], day: str, sessions: Sequence[str]
) -> Dict[str, Any]:
    f0 = fut_by.get(day)
    if not f0:
        return {"ok": False, "missing": "外資期貨淨空口數（當日）"}
    prev = None
    for d in reversed(list(sessions)):
        if d < day and d in fut_by:
            prev = d
            break
    if prev is None:
        return {"ok": False, "missing": "外資期貨淨空前一列"}
    s0 = f0.get("oi_short")
    s1 = fut_by[prev].get("oi_short")
    n0 = f0.get("oi_net")
    n1 = fut_by[prev].get("oi_net")
    if s0 is None or s1 is None:
        return {"ok": False, "missing": "外資期貨空單口數缺值"}
    # 減空：空單口數下降，或淨空（淨部位更不負／空單減少）
    short_delta = s0 - s1
    net_delta = None if (n0 is None or n1 is None) else (n0 - n1)
    return {
        "ok": True,
        "oi_short": s0,
        "oi_short_prev": s1,
        "short_delta": short_delta,
        "oi_net": n0,
        "net_delta": net_delta,
        "reduced_short": short_delta < 0,
        "prev": prev,
        "asof": day,
    }


def confront_level(
    level: float,
    day: str,
    twii_by: Dict[str, Bar],
    sessions: Sequence[str],
) -> Dict[str, Any]:
    """點位：當日高低碰到＝命中；次日補碰到也算命中；完整柱未碰到＝未命中。"""
    b0 = twii_by.get(day)
    if not _is_complete_bar(b0):
        # 當日無完整柱 → 試次日
        nxt = _next_session(sessions, day)
        b1 = twii_by.get(nxt) if nxt else None
        if not _is_complete_bar(b1):
            return {
                "kind": "level",
                "value": level,
                "verdict": "unverifiable",
                "missing": "加權完整柱（當日／次日）",
                "bar_date": "",
            }
        inside = b1.low <= level <= b1.high
        return {
            "kind": "level",
            "value": level,
            "verdict": "hit" if inside else "miss",
            "window": "next_session",
            "bar_date": b1.date,
            "ohlc": {"h": b1.high, "l": b1.low, "c": b1.close},
        }
    inside0 = b0.low <= level <= b0.high
    if inside0:
        return {
            "kind": "level",
            "value": level,
            "verdict": "hit",
            "window": "same_session",
            "bar_date": b0.date,
            "ohlc": {"h": b0.high, "l": b0.low, "c": b0.close},
        }
    nxt = _next_session(sessions, day)
    b1 = twii_by.get(nxt) if nxt else None
    if _is_complete_bar(b1):
        inside1 = b1.low <= level <= b1.high
        return {
            "kind": "level",
            "value": level,
            "verdict": "hit" if inside1 else "miss",
            "window": "next_session",
            "bar_date": b1.date,
            "same_day_miss": True,
            "ohlc": {"h": b1.high, "l": b1.low, "c": b1.close},
        }
    return {
        "kind": "level",
        "value": level,
        "verdict": "miss",
        "window": "same_session",
        "bar_date": b0.date,
        "ohlc": {"h": b0.high, "l": b0.low, "c": b0.close},
        "note": "次日無完整柱，僅以當日判定未碰到",
    }


def confront_lots(
    lots: float,
    day: str,
    fut_by: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    f0 = fut_by.get(day)
    if not f0 or f0.get("oi_short") is None:
        return {
            "kind": "lots",
            "value": lots,
            "verdict": "unverifiable",
            "missing": "外資期貨空單口數（當日）",
        }
    short = f0["oi_short"]
    # 容差：±5% 或 ±3000 口
    tol = max(3000.0, abs(lots) * 0.05)
    hit = abs(short - lots) <= tol
    return {
        "kind": "lots",
        "value": lots,
        "verdict": "hit" if hit else "miss",
        "official_oi_short": short,
        "tol": tol,
        "asof": day,
    }


def _forward_giveback(
    twii_by: Dict[str, Bar],
    sessions: Sequence[str],
    day: str,
    *,
    horizon: int = 5,
) -> Dict[str, Any]:
    b0 = twii_by.get(day)
    if not _is_complete_bar(b0) or b0.close is None:
        return {"ok": False, "missing": "加權完整柱"}
    idx = list(sessions).index(day)
    fut = sessions[idx + 1 : idx + 1 + horizon]
    if not fut:
        return {"ok": False, "missing": "前瞻交易日不足"}
    closes = []
    lows = []
    for d in fut:
        b = twii_by.get(d)
        if not _is_complete_bar(b):
            continue
        closes.append(b.close)
        lows.append(b.low)
    if not closes:
        return {"ok": False, "missing": "前瞻完整柱"}
    min_close = min(closes)
    min_low = min(lows) if lows else None
    giveback = min_close < b0.close
    return {
        "ok": True,
        "signal_close": b0.close,
        "min_close": min_close,
        "min_low": min_low,
        "giveback": giveback,
        "horizon_sessions": len(closes),
    }


def _forward_continued_weak(
    twii_by: Dict[str, Bar],
    sessions: Sequence[str],
    day: str,
    *,
    horizon: int = 3,
) -> Dict[str, Any]:
    b0 = twii_by.get(day)
    if not _is_complete_bar(b0):
        return {"ok": False, "missing": "加權完整柱"}
    idx = list(sessions).index(day)
    fut = sessions[idx + 1 : idx + 1 + horizon]
    if not fut:
        return {"ok": False, "missing": "前瞻交易日不足"}
    lows = []
    for d in fut:
        b = twii_by.get(d)
        if _is_complete_bar(b):
            lows.append(b.low)
    if not lows:
        return {"ok": False, "missing": "前瞻完整柱"}
    continued = min(lows) < b0.low
    return {
        "ok": True,
        "signal_low": b0.low,
        "fwd_min_low": min(lows),
        "continued_weak": continued,
        "horizon_sessions": len(lows),
    }


def _confront_mentioned_rule(
    rule: str,
    day: str,
    *,
    sessions: Sequence[str],
    twii_by: Dict[str, Bar],
    margin_by: Dict[str, Dict[str, Any]],
    inst_by: Dict[str, Dict[str, Any]],
    fut_by: Dict[str, Dict[str, Any]],
    fx_by: Dict[str, Bar],
) -> Dict[str, Any]:
    """他當日講到的錨 → 對當日／次日官方結構（觀察，非買訊）。"""
    base: Dict[str, Any] = {
        "kind": "condition_confront",
        "rule": rule,
        "session_date": day,
    }
    b0 = twii_by.get(day)
    if not _is_complete_bar(b0):
        base.update({"verdict": "unverifiable", "missing": "加權完整柱"})
        return base
    prev = _prev_session(sessions, day)
    chg = _chg_pct(twii_by, day, prev)
    vol5 = _vol_vs_n(twii_by, sessions, day, 5)

    if rule == "margin_speed":
        ms = _margin_speed_for_day(day, twii_by, margin_by, sessions)
        if not ms.get("ok"):
            base.update({"verdict": "unverifiable", "missing": ms.get("missing")})
            return base
        # 他講速度差當日：能算出速度差＝可驗證；方向對質用「不夠快→次窗續弱」
        gap = ms["speed_gap_pp"]
        if chg is not None and chg < 0 and gap > 0:
            fwd = _forward_continued_weak(twii_by, sessions, day, horizon=3)
            if not fwd.get("ok"):
                base.update(
                    {
                        "verdict": "unverifiable",
                        "missing": fwd.get("missing"),
                        "speed_gap_pp": gap,
                    }
                )
            else:
                hit = bool(fwd.get("continued_weak"))
                base.update(
                    {
                        "verdict": "hit" if hit else "miss",
                        "speed_gap_pp": gap,
                        "claim": "不夠快→續壓",
                        "forward": fwd,
                    }
                )
        elif chg is not None and chg < 0 and gap < -3:
            # 有進度：近窗出現收高
            try:
                idx0 = list(sessions).index(day)
            except ValueError:
                idx0 = -1
            fwd_closes = [
                twii_by[d].close
                for d in list(sessions)[idx0 + 1 : idx0 + 6]
                if idx0 >= 0
                and _is_complete_bar(twii_by.get(d))
                and twii_by[d].close is not None
            ]
            if not fwd_closes:
                base.update(
                    {
                        "verdict": "unverifiable",
                        "missing": "前瞻完整柱",
                        "speed_gap_pp": gap,
                    }
                )
            else:
                hit = any(c > b0.close for c in fwd_closes)
                base.update(
                    {
                        "verdict": "hit" if hit else "miss",
                        "speed_gap_pp": gap,
                        "claim": "有進度→近窗紓壓",
                    }
                )
        else:
            # 有算出速度差但當日非明確跌勢窗 → 記可觀測、不計勝率方向
            base.update(
                {
                    "verdict": "unverifiable",
                    "missing": "當日非明確跌勢窗（速度差已算但不套續壓／紓壓閘）",
                    "speed_gap_pp": gap,
                    "chg_pct": None if chg is None else round(chg, 3),
                }
            )
        return base

    if rule == "shrink_up":
        if chg is None or vol5 is None:
            base.update({"verdict": "unverifiable", "missing": "漲幅或量比缺"})
            return base
        if not (chg > 1.0 and vol5 < 0.9):
            base.update(
                {
                    "verdict": "unverifiable",
                    "missing": "當日未達縮量大漲觸發（仍記錄提及）",
                    "chg_pct": round(chg, 3),
                    "vol_vs_5": round(vol5, 3),
                }
            )
            return base
        fwd = _forward_giveback(twii_by, sessions, day, horizon=5)
        if not fwd.get("ok"):
            base.update({"verdict": "unverifiable", "missing": fwd.get("missing")})
            return base
        hit = bool(fwd.get("giveback"))
        base.update(
            {
                "verdict": "hit" if hit else "miss",
                "claim": "縮量大漲→近5日回吐",
                "chg_pct": round(chg, 3),
                "vol_vs_5": round(vol5, 3),
                "forward": {
                    "giveback": fwd["giveback"],
                    "min_close": fwd["min_close"],
                },
            }
        )
        return base

    if rule == "triple_sync":
        miss_fields: List[str] = []
        inst = inst_by.get(day)
        if not inst or inst.get("foreign_net") is None:
            miss_fields.append("外資現貨買賣超")
        fx = _fx_chg(fx_by, day, sessions)
        if not fx.get("ok"):
            miss_fields.append(str(fx.get("missing") or "美金台幣"))
        fut = _fut_short_delta(fut_by, day, sessions)
        if not fut.get("ok"):
            miss_fields.append(str(fut.get("missing") or "外資期貨減空"))
        if miss_fields:
            base.update(
                {"verdict": "unverifiable", "missing": "；".join(miss_fields)}
            )
            return base
        spot_buy = (inst or {}).get("foreign_net", 0) > 0
        twd_up = (fx.get("chg_pct") or 0) < 0
        reduce_short = bool(fut.get("reduced_short"))
        full_sync = spot_buy and twd_up and reduce_short
        base.update(
            {
                "verdict": "hit" if full_sync else "miss",
                "claim": "當日三同步是否齊（觀察燈，非預測勝率）",
                "full_sync": full_sync,
                "legs": {
                    "spot_buy": spot_buy,
                    "twd_stronger": twd_up,
                    "reduce_short": reduce_short,
                },
            }
        )
        return base

    if rule == "false_break":
        # 事件當日：若收黑且放量，對次日續弱；無頸線官方位則無法驗證突破幅度
        if chg is None or vol5 is None:
            base.update({"verdict": "unverifiable", "missing": "漲跌或量比缺"})
            return base
        if not (chg < 0 and vol5 >= 1.1):
            base.update(
                {
                    "verdict": "unverifiable",
                    "missing": "當日未呈放量收黑（假突破獵殺窗未觸發）",
                    "chg_pct": round(chg, 3),
                    "vol_vs_5": round(vol5, 3),
                }
            )
            return base
        nxt = _next_session(sessions, day)
        b1 = twii_by.get(nxt) if nxt else None
        if not _is_complete_bar(b1):
            base.update({"verdict": "unverifiable", "missing": "次日加權完整柱"})
            return base
        hit = b1.close < b0.close
        base.update(
            {
                "verdict": "hit" if hit else "miss",
                "claim": "放量收黑日→次日續弱（事件窗；個股頸線％另需標的柱）",
                "chg_pct": round(chg, 3),
                "vol_vs_5": round(vol5, 3),
                "next_close": b1.close,
            }
        )
        return base

    base.update({"verdict": "unverifiable", "missing": f"未知規則 {rule}"})
    return base


def build_daily_events(
    posts: Sequence[Dict[str, Any]],
    *,
    twii_by: Dict[str, Bar],
    sessions: Sequence[str],
    fut_by: Dict[str, Dict[str, Any]],
    margin_by: Dict[str, Dict[str, Any]],
    inst_by: Dict[str, Dict[str, Any]],
    fx_by: Dict[str, Bar],
    otc_by: Dict[str, Bar],
) -> List[Dict[str, Any]]:
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in posts:
        day = p.get("asof") or ""
        if not day:
            continue
        by_day[day].append(p)

    rows: List[Dict[str, Any]] = []
    for day in sorted(by_day.keys()):
        day_posts = by_day[day]
        # 對齊交易日：假日文 → 下一交易日（若無則前一）
        sess = day if day in twii_by else None
        align = "exact"
        if sess is None:
            nxt = _next_session(sessions, day)
            if nxt:
                sess = nxt
                align = f"next_session:{nxt}"
            else:
                prev = _prev_session(sessions, day)
                if prev:
                    sess = prev
                    align = f"prev_session:{prev}"
                else:
                    sess = day
                    align = "no_session"

        b = twii_by.get(sess)
        missing: List[str] = []
        if not _is_complete_bar(b):
            missing.append("加權完整柱")
        if sess not in margin_by:
            missing.append("市場融資當日列")
        if sess not in inst_by:
            missing.append("法人現貨買賣超")
        if sess not in fut_by:
            missing.append("外資期貨淨空口數")
        fx = _fx_chg(fx_by, sess, sessions)
        if not fx.get("ok"):
            missing.append(fx.get("missing") or "美金台幣")
        if sess not in otc_by:
            missing.append("櫃買當日列")
        elif not _is_complete_bar(otc_by.get(sess)):
            # 現況庫多為收盤戳記（開高低收全同）→ 無法做高低對質
            missing.append("櫃買高低缺（僅收盤戳記）")

        claims: List[Dict[str, Any]] = []
        texts = []
        for p in day_posts:
            texts.append(p.get("text") or "")
            for lv in extract_mentioned_levels(p.get("text") or ""):
                claims.append(confront_level(lv, sess, twii_by, sessions))
            for lot in extract_lots(p.get("text") or ""):
                claims.append(confront_lots(lot, sess, fut_by))
            for cond in detect_conditions(p.get("text") or ""):
                claims.append(
                    {
                        "kind": "condition_mention",
                        "rule": cond,
                        "article_id": p.get("article_id"),
                        "post_id": p.get("id"),
                        "verdict": "mentioned",  # 事件列；當日結構對質見下段
                    }
                )

        # 當日條件提及 → 用官方柱做當日／次日結構對質（缺欄≠命中）
        mentioned_rules = sorted(
            {
                c.get("rule")
                for c in claims
                if c.get("kind") == "condition_mention" and c.get("rule")
            }
        )
        for rule in mentioned_rules:
            claims.append(
                _confront_mentioned_rule(
                    rule,
                    sess,
                    sessions=sessions,
                    twii_by=twii_by,
                    margin_by=margin_by,
                    inst_by=inst_by,
                    fut_by=fut_by,
                    fx_by=fx_by,
                )
            )

        # 去重點位／口數（同值只留一）
        dedup: List[Dict[str, Any]] = []
        seen_key = set()
        for c in claims:
            if c.get("kind") in ("level", "lots"):
                key = (c["kind"], c.get("value"))
                if key in seen_key:
                    continue
                seen_key.add(key)
            dedup.append(c)

        prev = _prev_session(sessions, sess) if sess in sessions else None
        chg = _chg_pct(twii_by, sess, prev) if sess else None
        official: Dict[str, Any] = {
            "session": sess,
            "align": align,
            "twii": (
                {
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                    "chg_pct": None if chg is None else round(chg, 3),
                    "complete": _is_complete_bar(b),
                }
                if b
                else {}
            ),
            "margin": margin_by.get(sess) or {},
            "inst": inst_by.get(sess) or {},
            "fut_foreign": fut_by.get(sess) or {},
            "usdtwd": fx if fx.get("ok") else {"missing": fx.get("missing")},
            "otc": (
                {
                    "c": otc_by[sess].close,
                    "complete": _is_complete_bar(otc_by.get(sess)),
                }
                if sess in otc_by
                else {}
            ),
        }

        rows.append(
            {
                "type": "daily_event",
                "calendar_date": day,
                "session_date": sess,
                "align": align,
                "author": AUTHOR_NAME,
                "not_buy_signal": True,
                "n_mains": sum(1 for p in day_posts if p.get("kind") == "main"),
                "n_replies": sum(1 for p in day_posts if p.get("kind") == "reply"),
                "posts": [
                    {
                        "id": p["id"],
                        "article_id": p["article_id"],
                        "kind": p["kind"],
                        "title": p.get("title") or "",
                        "published_at_taipei": p.get("published_at_taipei"),
                        "text_excerpt": (p.get("text") or "")[:240],
                    }
                    for p in day_posts
                ],
                "claims": dedup,
                "official": official,
                "missing_official": sorted(set(missing)),
                "timezone": "Asia/Taipei",
            }
        )
    return rows


def build_anchor_samples(
    *,
    sessions: Sequence[str],
    twii_by: Dict[str, Bar],
    margin_by: Dict[str, Dict[str, Any]],
    inst_by: Dict[str, Dict[str, Any]],
    fut_by: Dict[str, Dict[str, Any]],
    fx_by: Dict[str, Bar],
    lookback: int = 60,
    false_break_lookback: int = 250,
) -> List[Dict[str, Any]]:
    """近 N 交易日可重複對質樣本（規則觀察統計，非買訊）。

    false_break 在指數上觸發稀疏，另用較長窗收樣（仍只計可驗證；缺欄不當命中）。
    """
    complete = [d for d in sessions if _is_complete_bar(twii_by.get(d))]
    use = complete[-lookback:] if len(complete) > lookback else list(complete)
    use_fb = (
        complete[-false_break_lookback:]
        if len(complete) > false_break_lookback
        else list(complete)
    )
    samples: List[Dict[str, Any]] = []

    for i, day in enumerate(use):
        prev = use[i - 1] if i > 0 else _prev_session(sessions, day)
        chg = _chg_pct(twii_by, day, prev)
        vol5 = _vol_vs_n(twii_by, sessions, day, 5)
        b0 = twii_by[day]

        # --- 融資速度差 ---
        ms = _margin_speed_for_day(day, twii_by, margin_by, sessions)
        if chg is not None and chg < -1.0:
            if not ms.get("ok"):
                samples.append(
                    {
                        "type": "anchor_sample",
                        "rule": "margin_speed",
                        "session_date": day,
                        "trigger": "index_down_gt1",
                        "verdict": "unverifiable",
                        "missing": ms.get("missing"),
                        "chg_pct": round(chg, 3),
                    }
                )
            else:
                gap = ms["speed_gap_pp"]
                # 不夠快：速度差 > 0（融資跌幅未超過指數跌幅）
                if gap > 0:
                    fwd = _forward_continued_weak(twii_by, sessions, day, horizon=3)
                    if not fwd.get("ok"):
                        verdict = "unverifiable"
                        missing = fwd.get("missing")
                        hit = None
                    else:
                        hit = bool(fwd.get("continued_weak"))
                        verdict = "hit" if hit else "miss"
                        missing = None
                    samples.append(
                        {
                            "type": "anchor_sample",
                            "rule": "margin_speed",
                            "session_date": day,
                            "trigger": "insufficient_delever",
                            "claim": "指數跌但融資未更快降→續壓（觀察）",
                            "speed_gap_pp": gap,
                            "chg_pct": round(chg, 3),
                            "forward": fwd if fwd.get("ok") else None,
                            "verdict": verdict,
                            "missing": missing,
                        }
                    )
                elif gap < -3:
                    # 有進度：5 日內曾收高於訊號日收（紓壓）
                    try:
                        idx0 = list(sessions).index(day)
                    except ValueError:
                        idx0 = -1
                    fwd_days = (
                        list(sessions)[idx0 + 1 : idx0 + 6] if idx0 >= 0 else []
                    )
                    fwd_closes = [
                        twii_by[d].close
                        for d in fwd_days
                        if _is_complete_bar(twii_by.get(d))
                        and twii_by[d].close is not None
                    ]
                    if not fwd_closes:
                        verdict = "unverifiable"
                        missing = "前瞻完整柱"
                        relief = None
                    else:
                        relief = any(c > b0.close for c in fwd_closes)
                        verdict = "hit" if relief else "miss"
                        missing = None
                    samples.append(
                        {
                            "type": "anchor_sample",
                            "rule": "margin_speed",
                            "session_date": day,
                            "trigger": "delever_progress",
                            "claim": "融資跌更快＝去槓桿有進度→近窗紓壓（觀察）",
                            "speed_gap_pp": gap,
                            "chg_pct": round(chg, 3),
                            "relief": relief,
                            "verdict": verdict,
                            "missing": missing,
                        }
                    )

        # --- 縮量大漲 ---
        if chg is not None and vol5 is not None and chg > 1.5 and vol5 < 0.85:
            fwd = _forward_giveback(twii_by, sessions, day, horizon=5)
            if not fwd.get("ok"):
                samples.append(
                    {
                        "type": "anchor_sample",
                        "rule": "shrink_up",
                        "session_date": day,
                        "trigger": "up_gt15_vol_lt085",
                        "verdict": "unverifiable",
                        "missing": fwd.get("missing"),
                        "chg_pct": round(chg, 3),
                        "vol_vs_5": round(vol5, 3),
                    }
                )
            else:
                hit = bool(fwd.get("giveback"))
                samples.append(
                    {
                        "type": "anchor_sample",
                        "rule": "shrink_up",
                        "session_date": day,
                        "trigger": "up_gt15_vol_lt085",
                        "claim": "縮量大漲偏逃命窗→近5日回吐訊號收（觀察）",
                        "chg_pct": round(chg, 3),
                        "vol_vs_5": round(vol5, 3),
                        "forward": {
                            "giveback": fwd["giveback"],
                            "min_close": fwd["min_close"],
                            "signal_close": fwd["signal_close"],
                        },
                        "verdict": "hit" if hit else "miss",
                    }
                )

        # --- 三同步（大漲日缺同步→逃命窗）---
        if chg is not None and chg > 1.5:
            miss_fields: List[str] = []
            inst = inst_by.get(day)
            if not inst or inst.get("foreign_net") is None:
                miss_fields.append("外資現貨買賣超")
            fx = _fx_chg(fx_by, day, sessions)
            if not fx.get("ok"):
                miss_fields.append(str(fx.get("missing") or "美金台幣"))
            fut = _fut_short_delta(fut_by, day, sessions)
            if not fut.get("ok"):
                miss_fields.append(str(fut.get("missing") or "外資期貨減空"))
            if miss_fields:
                samples.append(
                    {
                        "type": "anchor_sample",
                        "rule": "triple_sync",
                        "session_date": day,
                        "trigger": "up_gt15_check_sync",
                        "verdict": "unverifiable",
                        "missing": "；".join(miss_fields),
                        "chg_pct": round(chg, 3),
                    }
                )
            else:
                spot_buy = (inst or {}).get("foreign_net", 0) > 0
                twd_up = (fx.get("chg_pct") or 0) < 0  # USDTWD 跌＝台幣升
                reduce_short = bool(fut.get("reduced_short"))
                full_sync = spot_buy and twd_up and reduce_short
                fwd = _forward_giveback(twii_by, sessions, day, horizon=5)
                if not fwd.get("ok"):
                    samples.append(
                        {
                            "type": "anchor_sample",
                            "rule": "triple_sync",
                            "session_date": day,
                            "trigger": "up_gt15_check_sync",
                            "verdict": "unverifiable",
                            "missing": fwd.get("missing"),
                            "full_sync": full_sync,
                            "legs": {
                                "spot_buy": spot_buy,
                                "twd_stronger": twd_up,
                                "reduce_short": reduce_short,
                            },
                        }
                    )
                else:
                    if full_sync:
                        # 全同步→較不像逃命；命中＝5日內未跌破訊號收
                        hit = not bool(fwd.get("giveback"))
                        claim = "三同步齊→大漲較不像逃命窗（近5日守收）"
                    else:
                        # 缺同步→逃命窗；命中＝回吐
                        hit = bool(fwd.get("giveback"))
                        claim = "大漲但三同步未齊→逃命窗（近5日回吐）"
                    samples.append(
                        {
                            "type": "anchor_sample",
                            "rule": "triple_sync",
                            "session_date": day,
                            "trigger": "up_gt15_check_sync",
                            "claim": claim,
                            "full_sync": full_sync,
                            "legs": {
                                "spot_buy": spot_buy,
                                "twd_stronger": twd_up,
                                "reduce_short": reduce_short,
                                "foreign_net": (inst or {}).get("foreign_net"),
                                "fx_chg_pct": fx.get("chg_pct"),
                                "fut_short_delta": fut.get("short_delta"),
                            },
                            "forward": {
                                "giveback": fwd["giveback"],
                                "min_close": fwd["min_close"],
                            },
                            "verdict": "hit" if hit else "miss",
                            "chg_pct": round(chg, 3),
                        }
                    )

    # --- 假突破（較長窗；指數代理）---
    for i, day in enumerate(use_fb):
        if i < 10:
            continue
        prev = use_fb[i - 1] if i > 0 else _prev_session(sessions, day)
        chg = _chg_pct(twii_by, day, prev)
        vol5 = _vol_vs_n(twii_by, sessions, day, 5)
        b0 = twii_by[day]
        if chg is None or vol5 is None:
            continue
        prior = use_fb[max(0, i - 10) : i]
        prior_highs = [
            twii_by[d].high
            for d in prior
            if _is_complete_bar(twii_by.get(d)) and twii_by[d].high is not None
        ]
        if not prior_highs or b0.high is None or b0.close is None:
            continue
        neck = max(prior_highs)
        if not (neck > 0 and b0.high > neck):
            continue
        over_pct = (b0.high / neck - 1.0) * 100.0
        if not (over_pct < 3.0 and vol5 >= 1.1 and chg < 0 and b0.close < neck):
            continue
        nxt = _next_session(sessions, day)
        b1 = twii_by.get(nxt) if nxt else None
        if not _is_complete_bar(b1):
            samples.append(
                {
                    "type": "anchor_sample",
                    "rule": "false_break",
                    "session_date": day,
                    "trigger": "small_break_vol_red",
                    "proxy": "TWII_10d_high",
                    "lookback_sessions": len(use_fb),
                    "verdict": "unverifiable",
                    "missing": "次日加權完整柱",
                    "neck": neck,
                    "over_pct": round(over_pct, 3),
                    "vol_vs_5": round(vol5, 3),
                    "chg_pct": round(chg, 3),
                }
            )
        else:
            hit = b1.close < b0.close
            samples.append(
                {
                    "type": "anchor_sample",
                    "rule": "false_break",
                    "session_date": day,
                    "trigger": "small_break_vol_red",
                    "proxy": "TWII_10d_high",
                    "lookback_sessions": len(use_fb),
                    "claim": "未達3%小突破＋放量收黑→次日續弱（觀察／指數代理）",
                    "neck": neck,
                    "over_pct": round(over_pct, 3),
                    "vol_vs_5": round(vol5, 3),
                    "chg_pct": round(chg, 3),
                    "next_close": b1.close,
                    "verdict": "hit" if hit else "miss",
                }
            )

    return samples


_ANCHOR_RULES = ("margin_speed", "shrink_up", "triple_sync", "false_break")


def _rule_stats(samples: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        by[str(s.get("rule") or "?")].append(s)
    out: Dict[str, Dict[str, Any]] = {}
    for rule in list(_ANCHOR_RULES) + [r for r in by if r not in _ANCHOR_RULES]:
        rows = by.get(rule) or []
        hit = sum(1 for r in rows if r.get("verdict") == "hit")
        miss = sum(1 for r in rows if r.get("verdict") == "miss")
        unv = sum(1 for r in rows if r.get("verdict") == "unverifiable")
        verifiable = hit + miss
        rate = (hit / verifiable) if verifiable else None
        miss_counter: Counter[str] = Counter()
        for r in rows:
            if r.get("verdict") == "unverifiable" and r.get("missing"):
                miss_counter[str(r["missing"])] += 1
        note = "hit_rate 只含 hit/(hit+miss)；unverifiable 不進勝率"
        if rule == "false_break":
            note += "；TWII 近10日前高代理（個股頸線需標的柱）"
            if not rows:
                note += "；近窗無觸發"
        out[rule] = {
            "n_samples": len(rows),
            "n_hit": hit,
            "n_miss": miss,
            "n_unverifiable": unv,
            "n_verifiable": verifiable,
            "hit_rate_obs": None if rate is None else round(rate, 4),
            "top_missing": miss_counter.most_common(5),
            "note": note,
        }
    return out


def render_summary_md(
    *,
    events: Sequence[Dict[str, Any]],
    samples: Sequence[Dict[str, Any]],
    rule_stats: Dict[str, Dict[str, Any]],
    gap_counter: Counter,
    lookback: int,
    generated_at: str,
) -> str:
    def _tally(kinds: Sequence[str]) -> Tuple[int, int, int, Optional[float]]:
        h = m = u = 0
        for e in events:
            for c in e.get("claims") or []:
                if c.get("kind") not in kinds:
                    continue
                v = c.get("verdict")
                if v == "hit":
                    h += 1
                elif v == "miss":
                    m += 1
                elif v == "unverifiable":
                    u += 1
        ver = h + m
        rate = (h / ver) if ver else None
        return h, m, u, rate

    ev_hit, ev_miss, ev_unv, ev_rate = _tally(("level", "lots"))
    ev_ver = ev_hit + ev_miss
    cd_hit, cd_miss, cd_unv, cd_rate = _tally(("condition_confront",))
    cd_ver = cd_hit + cd_miss

    lines = [
        f"# 啾哈逐日事件對質（非買訊）",
        "",
        f"- 產生時間（Asia/Taipei）：`{generated_at}`",
        f"- 作者：{AUTHOR_NAME}｜主文／自回事件日數：{len(events)}",
        f"- 錨點系統窗：近 **{lookback}** 個有完整加權柱的交易日（`false_break` 另用較長窗收樣）",
        f"- **不准**把缺欄當命中；盤中未收／開高低收全同不當官方收",
        f"- 本檔只觀察統計，**不是買訊**，不准改黃金買點",
        "",
        "## 1. 可驗證樣本總覽",
        "",
        f"| 層 | 可驗證 n | 命中 | 未命中 | 缺欄／無法驗證 | 暫時勝率（觀察） |",
        f"|----|----------|------|--------|----------------|------------------|",
        f"| 事件點位／口數 | {ev_ver} | {ev_hit} | {ev_miss} | {ev_unv} | "
        f"{'—' if ev_rate is None else f'{ev_rate*100:.1f}%'} |",
        f"| 事件條件對質 | {cd_ver} | {cd_hit} | {cd_miss} | {cd_unv} | "
        f"{'—' if cd_rate is None else f'{cd_rate*100:.1f}%'} |",
    ]
    total_v = total_h = total_m = total_u = 0
    for rule, st in sorted(rule_stats.items()):
        total_v += st["n_verifiable"]
        total_h += st["n_hit"]
        total_m += st["n_miss"]
        total_u += st["n_unverifiable"]
        rate = st["hit_rate_obs"]
        lines.append(
            f"| 錨 `{rule}` | {st['n_verifiable']} | {st['n_hit']} | {st['n_miss']} | "
            f"{st['n_unverifiable']} | {'—' if rate is None else f'{rate*100:.1f}%'} |"
        )
    lines += [
        f"| **錨合計** | **{total_v}** | **{total_h}** | **{total_m}** | **{total_u}** | "
        f"**{'—' if total_v == 0 else f'{total_h/total_v*100:.1f}%'}** |",
        "",
        "## 2. 各規則暫時勝率（僅觀察）",
        "",
    ]
    for rule, st in sorted(rule_stats.items()):
        lines.append(f"### `{rule}`")
        lines.append(
            f"- 樣本 {st['n_samples']}（可驗證 {st['n_verifiable']}／缺欄 {st['n_unverifiable']}）"
        )
        if st["hit_rate_obs"] is None:
            lines.append("- 暫時勝率：—（可驗證 n=0）")
        else:
            lines.append(
                f"- 暫時勝率：{st['hit_rate_obs']*100:.1f}% "
                f"（{st['n_hit']}/{st['n_verifiable']}）"
            )
        if st["top_missing"]:
            lines.append("- 缺欄：")
            for m, n in st["top_missing"]:
                lines.append(f"  - {m} ×{n}")
        lines.append("")

    lines += [
        "## 3. 最大缺口官方欄（全域計次）",
        "",
    ]
    if not gap_counter:
        lines.append("- （無）")
    else:
        for name, n in gap_counter.most_common(15):
            lines.append(f"- {name} ×{n}")

    lines += [
        "",
        "## 4. 逐日事件年表（精簡）",
        "",
        "| 日曆日 | 交易日 | 主／回 | 點位命中 | 點位未中 | 無法驗證 | 條件提及 | 缺欄 |",
        "|--------|--------|--------|----------|----------|----------|----------|------|",
    ]
    for e in events:
        claims = e.get("claims") or []
        lh = sum(1 for c in claims if c.get("kind") == "level" and c.get("verdict") == "hit")
        lm = sum(1 for c in claims if c.get("kind") == "level" and c.get("verdict") == "miss")
        lu = sum(
            1
            for c in claims
            if c.get("kind") in ("level", "lots") and c.get("verdict") == "unverifiable"
        )
        conds = sorted(
            {
                c.get("rule")
                for c in claims
                if c.get("kind") == "condition_mention" and c.get("rule")
            }
        )
        miss = "；".join((e.get("missing_official") or [])[:3]) or "—"
        lines.append(
            f"| {e.get('calendar_date')} | {e.get('session_date')} | "
            f"{e.get('n_mains')}/{e.get('n_replies')} | {lh} | {lm} | {lu} | "
            f"{'、'.join(conds) if conds else '—'} | {miss} |"
        )

    lines += [
        "",
        "## 5. 規則操作化（對質定義）",
        "",
        "| 規則 | 觸發 | 命中定義 | 缺欄處理 |",
        "|------|------|----------|----------|",
        "| margin_speed | 跌>1% 且可算速度差 | 不夠快→3日續破低；有進度→5日內收高於訊號 | 缺融資／不完整柱→unverifiable |",
        "| shrink_up | 漲>1.5% 且量/5日均<0.85 | 5日內收盤回吐低於訊號收 | 前瞻柱不足→unverifiable |",
        "| triple_sync | 漲>1.5% | 未齊→5日回吐；齊→5日守收 | 缺外資現貨／台幣當日／期貨減空→unverifiable |",
        "| false_break | 小破近10日前高(<3%)＋量/5≥1.1＋收黑跌回（TWII 代理） | 次日收更低 | 缺次日完整柱→unverifiable；個股頸線需標的柱 |",
        "",
        "註：`index_daily` OTC 目前多為開高低收全同戳記→「櫃買高低缺」計入最大缺口，不准當命中。",
        "",
        "估值／結構觀察 ≠ 買訊。切入仍只認已量化過關的高低卡規則。",
        "",
    ]
    return "\n".join(lines)


def collect_gaps(
    events: Sequence[Dict[str, Any]], samples: Sequence[Dict[str, Any]]
) -> Counter:
    c: Counter = Counter()
    for e in events:
        for m in e.get("missing_official") or []:
            c[str(m)] += 1
        for cl in e.get("claims") or []:
            if cl.get("verdict") == "unverifiable" and cl.get("missing"):
                c[str(cl["missing"])] += 1
    for s in samples:
        if s.get("verdict") == "unverifiable" and s.get("missing"):
            # 可能是複合「；」缺欄
            raw = str(s["missing"])
            for part in raw.split("；"):
                part = part.strip()
                if part:
                    c[part] += 1
    return c


def run(
    *,
    corpus_db: str,
    market_db: str,
    out_dir: str,
    sessions_n: int = 60,
    false_break_sessions: int = 250,
) -> Dict[str, Any]:
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)

    posts = load_author_posts(corpus_db)
    twii = load_index_bars(market_db, "TWII", limit=900)
    otc = load_index_bars(market_db, "OTC", limit=900)
    fx = load_index_bars(market_db, "USDTWD", limit=900)
    margin_rows = load_margin_series(market_db, limit=900)
    margin_by = {m["date"]: m for m in margin_rows if m.get("date")}
    inst_by = load_inst_by_date(market_db)
    fut_by = load_foreign_fut_oi(market_db)

    twii_by = _bar_map(twii)
    otc_by = _bar_map(otc)
    fx_by = _bar_map(fx)
    sessions = _session_list(twii)

    events = build_daily_events(
        posts,
        twii_by=twii_by,
        sessions=sessions,
        fut_by=fut_by,
        margin_by=margin_by,
        inst_by=inst_by,
        fx_by=fx_by,
        otc_by=otc_by,
    )
    samples = build_anchor_samples(
        sessions=sessions,
        twii_by=twii_by,
        margin_by=margin_by,
        inst_by=inst_by,
        fut_by=fut_by,
        fx_by=fx_by,
        lookback=sessions_n,
        false_break_lookback=false_break_sessions,
    )
    rule_stats = _rule_stats(samples)
    gaps = collect_gaps(events, samples)
    generated_at = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S%z")

    jsonl_path = outp / "daily_confront.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        meta = {
            "type": "meta",
            "author": AUTHOR_NAME,
            "not_buy_signal": True,
            "timezone": "Asia/Taipei",
            "generated_at": generated_at,
            "corpus_db": corpus_db,
            "market_db": market_db,
            "n_author_posts": len(posts),
            "n_event_days": len(events),
            "n_anchor_samples": len(samples),
            "anchor_lookback_sessions": sessions_n,
            "false_break_lookback_sessions": false_break_sessions,
            "rule_stats": rule_stats,
            "top_missing_official": gaps.most_common(20),
        }
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    md = render_summary_md(
        events=events,
        samples=samples,
        rule_stats=rule_stats,
        gap_counter=gaps,
        lookback=sessions_n,
        generated_at=generated_at,
    )
    md_path = outp / "confront_summary.md"
    md_path.write_text(md, encoding="utf-8")

    # 可驗證合計
    ev_v = sum(
        1
        for e in events
        for c in (e.get("claims") or [])
        if c.get("kind") in ("level", "lots") and c.get("verdict") in ("hit", "miss")
    )
    cd_v = sum(
        1
        for e in events
        for c in (e.get("claims") or [])
        if c.get("kind") == "condition_confront"
        and c.get("verdict") in ("hit", "miss")
    )
    an_v = sum(1 for s in samples if s.get("verdict") in ("hit", "miss"))

    return {
        "ok": True,
        "jsonl": str(jsonl_path),
        "md": str(md_path),
        "n_event_days": len(events),
        "n_anchor_samples": len(samples),
        "n_verifiable_event_claims": ev_v,
        "n_verifiable_condition_confront": cd_v,
        "n_verifiable_anchor": an_v,
        "rule_stats": rule_stats,
        "top_missing": gaps.most_common(10),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--market", default=DEFAULT_MARKET)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--sessions", type=int, default=60, help="錨點對質交易日窗")
    ap.add_argument(
        "--false-break-sessions",
        type=int,
        default=250,
        help="假突破指數代理較長窗（觸發稀疏）",
    )
    ap.add_argument(
        "--heal",
        action="store_true",
        help="對質前先跑官方欄補洞（期貨OI／融資／櫃買／USDTWD；非買訊）",
    )
    args = ap.parse_args()
    heal_info = None
    if args.heal:
        from jiuha_official_heal import heal_all

        heal_info = heal_all(
            args.market,
            sessions_n=args.sessions,
        )
        print(
            json.dumps(
                {
                    "heal_ok": heal_info.get("ok"),
                    "heal_delta": heal_info.get("delta"),
                    "heal_optional_unavailable": heal_info.get("optional_unavailable"),
                    "not_buy_signal": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    res = run(
        corpus_db=args.corpus,
        market_db=args.market,
        out_dir=args.out,
        sessions_n=args.sessions,
        false_break_sessions=args.false_break_sessions,
    )
    if heal_info is not None:
        res["heal_delta"] = heal_info.get("delta")
        res["heal_coverage_after"] = heal_info.get("after")
    print(json.dumps({k: res[k] for k in res if k != "rule_stats"}, ensure_ascii=False, indent=2))
    print(json.dumps(res.get("rule_stats"), ensure_ascii=False, indent=2))
    print(res.get("md"))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
