"""高低卡：創區間新高後，回測對前波高／前次底，查股只出一句綜合判斷。

用這檔自己的收盤、獲利、前波高、前次底組句；介紹圖／協助判斷／今日態度同一句。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

WINDOW = 60
NAV_WINDOW = 180  # 與 180 日高低導航同一視窗；不另開 240
PRIOR_BARS = 5
MERGE_GAP = 15
ALMOST_FRAC = 0.04  # 友達 2/3 貼前波高的距離；過了還看前次底
WASH_FRAC = 0.08  # 略破前次底；再深才寫底底低
HEAVY_VOL = 1.5  # 破低點線那根量 ≥ 近20根均量：帶量，相對危險
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
    volumes: Optional[Sequence[Any]] = None,
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
        "hold_prior_heavy": False,
        "hold_prior_vol_ratio": None,
    }
    hs = _fseq(highs)
    ls = _fseq(lows)
    n = min(len(hs), len(ls))
    if n < int(window) + int(prior_bars) + 1:
        return empty
    hs, ls = hs[:n], ls[:n]
    vs = _fseq(volumes)[:n] if volumes is not None else []
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
        "hold_prior_heavy": False,
        "hold_prior_vol_ratio": None,
    }
    base_txt = f"、前次底 {_px(base)}" if base and base > 0 else ""
    if last_i <= peak:
        out["hold_prior_state"] = "new_high"
        out["hold_prior_why"] = f"創{win_lab}新高"
        out["hold_prior_note"] = (
            f"創{win_lab}新高，回測先看前波高 {_px(prior)}{base_txt}"
        )
        return out
    r0 = peak + 1
    rj = r0 + min(range(last_i - peak), key=lambda k: ls[r0 + k])
    retest = float(ls[rj])
    out["hold_prior_retest_low"] = round(retest, 4)
    out["hold_prior_retest_date"] = ds[rj]
    if vs and len(vs) > rj:
        w0 = max(0, rj - 20)
        prior_v = vs[w0:rj]
        avg = (sum(prior_v) / len(prior_v)) if prior_v else 0.0
        ratio = (float(vs[rj]) / avg) if avg > 0 else None
        out["hold_prior_vol_ratio"] = round(ratio, 2) if ratio is not None else None
        out["hold_prior_heavy"] = bool(ratio is not None and ratio >= HEAVY_VOL)
    high_floor = prior * (1.0 - float(almost))
    trio = f"前波高 {_px(prior)}／前次底 {_px(base)}／回測低 {_px(retest)}" if base else (
        f"前波高 {_px(prior)}／回測低 {_px(retest)}"
    )
    if retest + 1e-12 >= high_floor:
        out["hold_prior_state"] = "holds"
        out["hold_prior_why"] = "回測幾乎不破前波高"
        out["hold_prior_note"] = f"回測幾乎不破前波高（{trio}）"
        return out
    if base is None or base <= 0:
        out["hold_prior_state"] = "wash"
        out["hold_prior_why"] = "回測過了前波高"
        out["hold_prior_note"] = f"回測過了前波高（{trio}）"
        return out
    wash_floor = base * (1.0 - float(WASH_FRAC))
    if retest + 1e-12 >= base:
        out["hold_prior_state"] = "wash"
        out["hold_prior_why"] = "過了前波高，前次底還在"
        out["hold_prior_note"] = f"回測過了前波高，前次底還在（{trio}）"
        return out
    if retest + 1e-12 >= wash_floor:
        out["hold_prior_state"] = "nick"
        out["hold_prior_why"] = "回測略破前次底"
        out["hold_prior_note"] = f"回測略破前次底（{trio}）"
        return out
    out["hold_prior_state"] = "broke"
    if out.get("hold_prior_heavy"):
        out["hold_prior_why"] = "低點線被帶量跌破"
        out["hold_prior_note"] = f"低點線被帶量跌破，相對危險（{trio}）"
    else:
        out["hold_prior_why"] = "回測已破前次底"
        out["hold_prior_note"] = f"回測已破前次底（{trio}）"
    return out


def attach_hold_prior_wave(
    card: Dict[str, Any],
    dates: Optional[Sequence[Any]] = None,
    highs: Optional[Sequence[Any]] = None,
    lows: Optional[Sequence[Any]] = None,
    volumes: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """寫入決策卡。沒有區間新高就空白。不改黃金買點。均線不當支撐壓力。"""
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
            if volumes is None and "volume" in df.columns:
                volumes = list(df["volume"])
        elif src is not None and hasattr(src, "columns"):
            return card
    flags = classify_hold_prior_wave(
        highs if highs is not None else [],
        lows if lows is not None else [],
        dates,
        volumes=volumes,
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


def _md(val: Any) -> str:
    d = _ymd(val)
    if len(d) == 8:
        return f"{int(d[4:6])}/{int(d[6:8])}"
    return ""


def _gain_txt(val: Any) -> str:
    try:
        x = float(val)
    except (TypeError, ValueError):
        return ""
    return f"{x:+.1f}%"


def _who(card: Dict[str, Any]) -> str:
    sid = str(card.get("stock_id") or "").strip()
    name = str(card.get("stock_name") or "").strip()
    if name and sid and name != sid:
        return f"{name}{sid}"
    return name or sid


def _close_txt(card: Dict[str, Any]) -> str:
    try:
        c = float(card.get("close") or 0)
    except (TypeError, ValueError):
        return ""
    return _px(c) if c > 0 else ""


def _vs(low: Any, ref: Any) -> str:
    try:
        a, b = float(low), float(ref)
    except (TypeError, ValueError):
        return ""
    if b <= 0:
        return ""
    pct = (a / b - 1.0) * 100.0
    if abs(pct) < 0.08:
        return "幾乎貼齊"
    if pct >= 0:
        return f"還高出 {pct:.1f}%"
    return f"低了 {abs(pct):.1f}%"


def _lead(card: Dict[str, Any], today_p: Optional[float]) -> str:
    bits: List[str] = []
    who = _who(card)
    if who:
        bits.append(who)
    cl = _close_txt(card)
    if cl:
        bits.append(f"收 {cl}")
    g = _gain_txt(today_p if today_p is not None else card.get("gain_pct", card.get("profit_pct")))
    if g:
        bits.append(f"獲利 {g}")
    return "，".join(bits) if bits else "這檔"


def _retest_clause(card: Dict[str, Any]) -> str:
    prior = card.get("hold_prior_high")
    base = card.get("hold_prior_base")
    retest = card.get("hold_prior_retest_low")
    pd, bd, rd = _md(card.get("hold_prior_date")), _md(card.get("hold_prior_base_date")), _md(
        card.get("hold_prior_retest_date")
    )
    if retest is None:
        bits = []
        if prior is not None:
            bits.append(f"高點線 {_px(prior)}" + (f"（{pd}）" if pd else ""))
        if base is not None:
            bits.append(f"低點線 {_px(base)}" + (f"（{bd}）" if bd else ""))
        return "、".join(bits)
    bits = [f"回測低 {_px(retest)}" + (f"（{rd}）" if rd else "")]
    if prior is not None:
        vs = _vs(retest, prior)
        bits.append(
            f"對高點線 {_px(prior)}" + (f"（{pd}）" if pd else "") + (f" {vs}" if vs else "")
        )
    if base is not None:
        vs = _vs(retest, base)
        bits.append(
            f"對低點線 {_px(base)}" + (f"（{bd}）" if bd else "") + (f" {vs}" if vs else "")
        )
    return "，".join(bits)


def _k20_clause(card: Dict[str, Any]) -> str:
    try:
        n = int(card.get("k20_high_streak") or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 2:
        return f"已經連 {n} 天貼高檔"
    if n == 1:
        return "剛貼到高檔"
    return ""


def judge_buy_point(card: Dict[str, Any] | None) -> Dict[str, str]:
    """每檔一句綜合判斷：用這檔自己的收盤、獲利、前波高／前次底。"""
    if not card or card.get("error"):
        return {"buy_verdict": "", "buy_verdict_note": ""}
    hold = str(card.get("hold_prior_state") or "")
    sell = str(card.get("sell_action") or "")
    sell_why = str(card.get("sell_why") or "").strip()
    hl = ""
    alert = ""
    try:
        from decision_card_signals import last_table_facts, leave_zero_screen_ok, table_reads_as_low

        facts = last_table_facts(card)
        hl = str(facts.get("hl") or "")
        alert = str(facts.get("alert") or "")
        low_table = table_reads_as_low(card)
    except Exception:
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
    lead = _lead(card, today_p)
    rt = _retest_clause(card)
    k20 = _k20_clause(card)
    win = "60／180日" if card.get("hold_prior_also_180") else "60日"

    def _sent(*parts: str) -> str:
        out: List[str] = []
        for p in parts:
            s = str(p or "").strip().strip("。")
            if s:
                out.append(s)
        text = "。".join(out)
        return (text + "。") if text else ""

    if hold == "broke":
        if card.get("hold_prior_heavy"):
            danger = "低點線被帶量跌破，相對危險，現在不要買"
        else:
            danger = "低點線破了，現在不要買"
        return {
            "buy_verdict": "no",
            "buy_verdict_note": _sent(lead, rt, danger),
        }
    if sell in ("直接減碼", "準備減碼") and not low_table:
        why = sell_why or sell
        return {
            "buy_verdict": "no",
            "buy_verdict_note": _sent(lead, f"高低卡要{sell}（{why}）", "現在不要加碼"),
        }
    if hl in ("20高", "10高") or alert == "K20高":
        bits = [lead, f"高低格 {hl or alert}"]
        if k20:
            bits.append(k20)
        if hold == "new_high":
            bits.append(f"剛創{win}新高")
            if rt:
                bits.append("回測先盯 " + rt)
        bits.append("價在高檔，現在別追")
        return {"buy_verdict": "no", "buy_verdict_note": _sent(*bits)}
    if hold == "new_high":
        return {
            "buy_verdict": "no",
            "buy_verdict_note": _sent(lead, f"剛創{win}新高", "回測先盯 " + rt if rt else "先等回測", "現在別追"),
        }
    if hold == "nick":
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": _sent(lead, rt, "略破前次底，等站回來再看，現在先不要下手"),
        }
    if lz_ok and hold in ("", "holds", "wash"):
        extra = rt if hold else (lz_why or "獲利剛離零")
        if hold == "wash":
            extra = (rt + "。" if rt else "") + "洗過前波高但前次底還在"
        elif hold == "holds":
            extra = rt
        return {
            "buy_verdict": "buy",
            "buy_verdict_note": _sent(lead, extra, "表上剛離零，現在算黃金買點"),
        }
    rel = str(card.get("relative_buy_kind") or "")
    try:
        g = float(today_p) if today_p is not None else None
    except (TypeError, ValueError):
        g = None
    if rel == "at_floor" or (g is not None and g <= 0.05):
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": _sent(lead, "獲利還貼在零附近，先等離零再動手"),
        }
    if hold in ("holds", "wash"):
        hint = "回測還在、前次底沒破" if hold == "wash" else "回測貼著前波高"
        gtxt = _gain_txt(g) if g is not None else ""
        mid = f"獲利 {gtxt} 已不在剛離零" if gtxt else "表上還不是剛離零"
        return {
            "buy_verdict": "watch",
            "buy_verdict_note": _sent(lead, rt or hint, mid, "現在先看，不要當黃金買點"),
        }
    if g is not None and g > 5:
        return {
            "buy_verdict": "no",
            "buy_verdict_note": _sent(
                lead, f"獲利 {_gain_txt(g)} 已離開剛離零那一帶", "現在不要當黃金買點"
            ),
        }
    return {
        "buy_verdict": "watch",
        "buy_verdict_note": _sent(lead, "先看這張高低卡，還沒到能下手的位置"),
    }


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
    """查股／介紹圖／協助判斷共用同一句。"""
    if card:
        attach_buy_verdict(card)
    note = str((card or {}).get("buy_verdict_note") or "").strip()
    return [note] if note else []
