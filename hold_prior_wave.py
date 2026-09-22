"""高低卡：創區間新高後，回測對前波高／前次底。

用官方 OHLC 高低重述（友達 2409：20260107 創 60／180 日新高，
20260203 回測低 13.30 vs 起漲前高 13.85、前次底 11.10）。
查股／決策卡協助判斷顯示，不是買訊、不改黃金買點、不進海選、不進飆大。

區間＝既有 60 根（季）高低；若同日也是 180 根導航新高就一併標。
前波高＝這波 60 日新高起漲前 5 根的最高。4% 只描述友達那次貼前波高，
不是判死線。洗盤可以過前波高、甚至略破前次底再翻；底底低才先當這波壞了。
前次底＝起漲前最近一個局部低。略破＝低於前次底但不超過 8%。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

WINDOW = 60
NAV_WINDOW = 180  # 與 180 日高低導航同一視窗；不另開 240
PRIOR_BARS = 5
MERGE_GAP = 15
ALMOST_FRAC = 0.04  # 友達 2/3 貼前波高的距離；過了還看前次底
WASH_FRAC = 0.08  # 略破前次底；再深才寫底底低
SWING = 5
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


def _last_swing_low(
    lows: Sequence[float],
    exclusive_end: int,
    *,
    swing: int = SWING,
) -> Optional[int]:
    """起漲前最近局部低。右側只看到起漲前，避免用到這波低。"""
    n = min(int(exclusive_end), len(lows))
    L = int(swing)
    if n <= L:
        return None
    for i in range(n - 1, L - 1, -1):
        left = [float(lows[j]) for j in range(max(0, i - L), i)]
        right = [float(lows[j]) for j in range(i + 1, min(n, i + L + 1))]
        lo = float(lows[i])
        if left and lo <= min(left) and (not right or lo <= min(right)):
            return i
    if n > 0:
        return min(range(n), key=lambda j: float(lows[j]))
    return None


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
    """最新一根：創區間新高／貼前波高／前次底還在／略破前次底／底底低。"""
    empty = {
        "hold_prior_state": "",
        "hold_prior_why": "",
        "hold_prior_note": "",
        "hold_prior_window": 0,
        "hold_prior_also_180": False,
        "hold_prior_high": None,
        "hold_prior_date": "",
        "hold_prior_base": None,
        "hold_prior_base_date": "",
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
    bj = _last_swing_low(ls, start)
    base = float(ls[bj]) if bj is not None else None
    out = {
        "hold_prior_state": "",
        "hold_prior_why": "",
        "hold_prior_note": "",
        "hold_prior_window": int(window),
        "hold_prior_also_180": bool(also_180),
        "hold_prior_high": round(prior, 4),
        "hold_prior_date": ds[pj],
        "hold_prior_base": round(base, 4) if base is not None else None,
        "hold_prior_base_date": ds[bj] if bj is not None else "",
        "hold_prior_new_high": round(new_h, 4),
        "hold_prior_new_date": ds[peak],
        "hold_prior_retest_low": None,
        "hold_prior_retest_date": "",
    }
    base_txt = f"、前次底 {_px(base)}" if base and base > 0 else ""
    if last_i <= peak:
        out["hold_prior_state"] = "new_high"
        out["hold_prior_why"] = f"創{win_lab}新高"
        out["hold_prior_note"] = (
            f"創{win_lab}新高，回測先看前波高 {_px(prior)}{base_txt}。不是買訊"
        )
        return out
    r0 = peak + 1
    rj = r0 + min(range(last_i - peak), key=lambda k: ls[r0 + k])
    retest = float(ls[rj])
    out["hold_prior_retest_low"] = round(retest, 4)
    out["hold_prior_retest_date"] = ds[rj]
    high_floor = prior * (1.0 - float(almost))
    trio = f"前波高 {_px(prior)}／前次底 {_px(base)}／回測低 {_px(retest)}" if base else (
        f"前波高 {_px(prior)}／回測低 {_px(retest)}"
    )
    if retest + 1e-12 >= high_floor:
        out["hold_prior_state"] = "holds"
        out["hold_prior_why"] = "回測幾乎不破前波高"
        out["hold_prior_note"] = f"回測幾乎不破前波高（{trio}）。不是買訊"
        return out
    if base is None or base <= 0:
        out["hold_prior_state"] = "wash"
        out["hold_prior_why"] = "回測過了前波高"
        out["hold_prior_note"] = (
            f"回測過了前波高（{trio}）。洗盤可以比4%深。不是買訊"
        )
        return out
    wash_floor = base * (1.0 - float(WASH_FRAC))
    if retest + 1e-12 >= base:
        out["hold_prior_state"] = "wash"
        out["hold_prior_why"] = "過了前波高，前次底還在"
        out["hold_prior_note"] = (
            f"回測過了前波高，前次底還在（{trio}）。洗盤可以比4%深。不是買訊"
        )
        return out
    if retest + 1e-12 >= wash_floor:
        out["hold_prior_state"] = "nick"
        out["hold_prior_why"] = "回測略破前次底"
        out["hold_prior_note"] = (
            f"回測略破前次底（{trio}）。先看有沒有翻上來。不是買訊"
        )
        return out
    out["hold_prior_state"] = "broke"
    out["hold_prior_why"] = "回測已破前次底"
    out["hold_prior_note"] = f"回測已破前次底（{trio}）。底底低先當這波壞了。不是買訊"
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
    attach_buy_verdict(card)
    return card


def _table_profit_pair(card: Dict[str, Any]) -> tuple:
    tbl = card.get("table")
    today_p = card.get("gain_pct", card.get("profit_pct"))
    today_a = ""
    yest_p = None
    yest_a = ""
    try:
        from sell_discipline import _chrono_table

        src = _chrono_table(tbl)
        if src is not None and hasattr(src, "iloc") and len(src):
            last = src.iloc[-1]
            today_p = last.get("profit_pct", today_p)
            today_a = str(last.get("預警") or "")
            if len(src) >= 2:
                prev = src.iloc[-2]
                yest_p = prev.get("profit_pct")
                yest_a = str(prev.get("預警") or "")
    except Exception:
        pass
    try:
        today_p = float(today_p) if today_p is not None else None
    except (TypeError, ValueError):
        today_p = None
    try:
        yest_p = float(yest_p) if yest_p is not None else None
    except (TypeError, ValueError):
        yest_p = None
    return yest_p, today_p, yest_a, today_a


def judge_buy_point(card: Dict[str, Any] | None) -> Dict[str, str]:
    """查股買點一句。只認高低卡表＋前次底，不改海選桶、不是紅箭頭。"""
    empty = {"buy_verdict": "watch", "buy_verdict_note": "現在先看表。不是買點。"}
    if not card or card.get("error"):
        return {"buy_verdict": "", "buy_verdict_note": ""}
    hold = str(card.get("hold_prior_state") or "")
    sell = str(card.get("sell_action") or "")
    hl = ""
    alert = ""
    try:
        from decision_card_signals import last_table_facts, leave_zero_screen_ok, table_reads_as_low

        facts = last_table_facts(card)
        hl = str(facts.get("hl") or "")
        alert = str(facts.get("alert") or "")
        low_table = table_reads_as_low(card)
    except Exception:
        facts = {}
        low_table = False
        try:
            from decision_card_signals import leave_zero_screen_ok
        except Exception:
            leave_zero_screen_ok = None  # type: ignore
    yest_p, today_p, yest_a, today_a = _table_profit_pair(card)
    lz_ok, lz_why = False, ""
    if leave_zero_screen_ok is not None and today_p is not None:
        lz_ok, lz_why = leave_zero_screen_ok(
            float(yest_p if yest_p is not None else 0.0),
            float(today_p),
            yest_alert=yest_a,
            today_alert=today_a or alert,
        )
    if hold == "broke":
        return {
            "buy_verdict": "no",
            "buy_verdict_note": "現在不是買點。回測已破前次底。",
        }
    if sell in ("直接減碼", "準備減碼") and not low_table:
        return {
            "buy_verdict": "no",
            "buy_verdict_note": "現在不是買點。高低卡要減碼，別買。",
        }
    if hl in ("20高", "10高") or alert == "K20高":
        return {
            "buy_verdict": "no",
            "buy_verdict_note": "現在不是買點。價在高檔，別追。",
        }
    if hold == "new_high":
        return {
            "buy_verdict": "no",
            "buy_verdict_note": "現在不是買點。剛創區間新高，先等回測。",
        }
    if hold == "nick":
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": "現在先看。回測略破前次底，等翻上來。不是買點。",
        }
    if lz_ok and hold in ("", "holds", "wash"):
        tail = ""
        if hold == "holds":
            tail = "回測幾乎不破前波高。"
        elif hold == "wash":
            tail = "洗盤過了前波高，前次底還在。"
        return {
            "buy_verdict": "buy",
            "buy_verdict_note": f"現在是買點。表上黃金買點（{lz_why}）。{tail}".strip(),
        }
    rel = str(card.get("relative_buy_kind") or "")
    try:
        g = float(today_p) if today_p is not None else None
    except (TypeError, ValueError):
        g = None
    if rel == "at_floor" or (g is not None and g <= 0.05):
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": "現在先看。獲利還沒離零。不是買點。",
        }
    if hold in ("holds", "wash"):
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": "現在先看。回測結構還在，表上不是黃金買點。",
        }
    if g is not None and g > 5:
        return {
            "buy_verdict": "no",
            "buy_verdict_note": "現在不是買點。獲利已離黃金買點帶。",
        }
    return empty


def attach_buy_verdict(card: Dict[str, Any]) -> Dict[str, Any]:
    if not card or card.get("error"):
        return card
    card.update(judge_buy_point(card))
    return card


def hold_note_short(card: Dict[str, Any] | None) -> str:
    if not card or card.get("error"):
        return ""
    return str(card.get("hold_prior_note") or "").strip()


def hold_note_lines(card: Dict[str, Any] | None) -> List[str]:
    """協助判斷：先買點一句，再回測細節。"""
    if card:
        attach_buy_verdict(card)
    lines: List[str] = []
    verdict = str((card or {}).get("buy_verdict_note") or "").strip()
    if verdict:
        lines.append(verdict)
    note = hold_note_short(card)
    if note and note not in lines:
        lines.append(note)
    return lines
