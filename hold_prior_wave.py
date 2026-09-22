"""高低卡：創區間新高後，回測幾乎不破前波高。

用官方 OHLC 高低重述（友達 2409：20260107 創 60／180 日新高，
20260203 回測低 13.30 vs 起漲前高 13.85）。查股／決策卡協助判斷顯示，
不是買訊、不改黃金買點、不進海選、不進飆大。

區間＝既有 60 根（季）高低；若同日也是 180 根導航新高就一併標。
前波高＝這波 60 日新高起漲前 5 根的最高。幾乎不破＝回測低不低於前波高 4%。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

WINDOW = 60
NAV_WINDOW = 180  # 與 180 日高低導航同一視窗；不另開 240
PRIOR_BARS = 5
MERGE_GAP = 15
ALMOST_FRAC = 0.04
FRESH_BARS = 90


def _ymd(val: Any) -> str:
    d = str(val or "").strip().replace("-", "").replace("/", "")
    if len(d) >= 8 and d[:8].isdigit():
        return d[:8]
    return str(val or "").strip()


def _px(val: Any) -> str:
    try:
        x = float(val)
    except (TypeError, ValueError):
        return ""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _fseq(seq: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for x in seq or []:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _is_window_high(highs: Sequence[float], i: int, window: int) -> bool:
    if i < 0 or i >= len(highs):
        return False
    w0 = max(0, i - int(window) + 1)
    seg = [float(highs[j]) for j in range(w0, i + 1)]
    if not seg:
        return False
    return float(highs[i]) + 1e-12 >= max(seg)


def _clusters(highs: Sequence[float], *, window: int = WINDOW, merge_gap: int = MERGE_GAP) -> List[Dict[str, Any]]:
    n = len(highs)
    clusters: List[Dict[str, Any]] = []
    if n < window:
        return clusters
    for i in range(n):
        if not _is_window_high(highs, i, window):
            continue
        h = float(highs[i])
        if (
            clusters
            and i - int(clusters[-1]["end"]) <= int(merge_gap)
            and h + 1e-12 >= float(clusters[-1]["peak_h"]) * 0.998
        ):
            c = clusters[-1]
            c["end"] = i
            if h + 1e-12 >= float(c["peak_h"]):
                c["peak"] = i
                c["peak_h"] = h
        else:
            clusters.append({"start": i, "peak": i, "peak_h": h, "end": i})
    return clusters


def classify_hold_prior_wave(
    highs: Sequence[Any],
    lows: Sequence[Any],
    dates: Optional[Sequence[Any]] = None,
    *,
    window: int = WINDOW,
    prior_bars: int = PRIOR_BARS,
    almost: float = ALMOST_FRAC,
    fresh: int = FRESH_BARS,
) -> Dict[str, Any]:
    """最新一根：創區間新高／回測不破／已破。空狀態不上句。"""
    empty = {
        "hold_prior_state": "",
        "hold_prior_why": "",
        "hold_prior_note": "",
        "hold_prior_window": 0,
        "hold_prior_also_180": False,
        "hold_prior_high": None,
        "hold_prior_date": "",
        "hold_prior_new_high": None,
        "hold_prior_new_date": "",
        "hold_prior_retest_low": None,
        "hold_prior_retest_date": "",
    }
    hs = _fseq(highs)
    ls = _fseq(lows)
    n = min(len(hs), len(ls))
    if n < int(window) + int(prior_bars) + 1:
        return empty
    hs, ls = hs[:n], ls[:n]
    ds = [_ymd(d) for d in (dates or [])]
    if len(ds) < n:
        ds = ds + [""] * (n - len(ds))
    else:
        ds = ds[:n]
    clusters = _clusters(hs, window=window)
    if not clusters:
        return empty
    last_i = n - 1
    c = clusters[-1]
    if last_i - int(c["peak"]) > int(fresh):
        return empty
    start = int(c["start"])
    peak = int(c["peak"])
    if start <= 0:
        return empty
    p0 = max(0, start - int(prior_bars))
    prior_seg = hs[p0:start]
    if not prior_seg:
        return empty
    pj = p0 + max(range(len(prior_seg)), key=lambda k: prior_seg[k])
    prior = float(hs[pj])
    if prior <= 0:
        return empty
    new_h = float(hs[peak])
    also_180 = n >= NAV_WINDOW and _is_window_high(hs, peak, NAV_WINDOW)
    win_lab = "60／180日" if also_180 else "60日"
    out = {
        "hold_prior_state": "",
        "hold_prior_why": "",
        "hold_prior_note": "",
        "hold_prior_window": int(window),
        "hold_prior_also_180": bool(also_180),
        "hold_prior_high": round(prior, 4),
        "hold_prior_date": ds[pj],
        "hold_prior_new_high": round(new_h, 4),
        "hold_prior_new_date": ds[peak],
        "hold_prior_retest_low": None,
        "hold_prior_retest_date": "",
    }
    if last_i <= peak:
        out["hold_prior_state"] = "new_high"
        out["hold_prior_why"] = f"創{win_lab}新高"
        out["hold_prior_note"] = (
            f"創{win_lab}新高，回測先看前波高 {_px(prior)}。不是買訊"
        )
        return out
    r0 = peak + 1
    rj = r0 + min(range(last_i - peak), key=lambda k: ls[r0 + k])
    retest = float(ls[rj])
    out["hold_prior_retest_low"] = round(retest, 4)
    out["hold_prior_retest_date"] = ds[rj]
    floor = prior * (1.0 - float(almost))
    pair = f"前波高 {_px(prior)}／回測低 {_px(retest)}"
    if retest + 1e-12 >= floor:
        out["hold_prior_state"] = "holds"
        out["hold_prior_why"] = "回測幾乎不破前波高"
        out["hold_prior_note"] = f"回測幾乎不破前波高（{pair}）。不是買訊"
    else:
        out["hold_prior_state"] = "broke"
        out["hold_prior_why"] = "回測已破前波高"
        out["hold_prior_note"] = f"回測已破前波高（{pair}）。這波先當壞了。不是買訊"
    return out


def attach_hold_prior_wave(
    card: Dict[str, Any],
    dates: Optional[Sequence[Any]] = None,
    highs: Optional[Sequence[Any]] = None,
    lows: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """寫入決策卡。沒有區間新高就空白。不改黃金買點。"""
    if not card or card.get("error"):
        return card
    if highs is None or lows is None:
        src = card.get("table")
        df = card.get("_ohlc")
        if df is not None and hasattr(df, "columns") and "high" in df.columns:
            highs = list(df["high"])
            lows = list(df["low"])
            if dates is None and "date" in df.columns:
                dates = list(df["date"])
        elif src is not None and hasattr(src, "columns"):
            return card
    flags = classify_hold_prior_wave(
        highs if highs is not None else [],
        lows if lows is not None else [],
        dates,
    )
    card.update(flags)
    return card


def hold_note_short(card: Dict[str, Any] | None) -> str:
    if not card or card.get("error"):
        return ""
    return str(card.get("hold_prior_note") or "").strip()


def hold_note_lines(card: Dict[str, Any] | None) -> List[str]:
    note = hold_note_short(card)
    return [note] if note else []
