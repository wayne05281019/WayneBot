#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由尾回推五波（觀察用，非買訊；不准當話筒浪號認證）。

使用者教法（2026-11-26）：
1. 先抓出大量（一年級）股票
2. 浪由尾畫回去
3. 今天若上漲 → 連回前幾天低點＝「新的開始」
4. 由該低點往回畫，看能不能畫出五波（前一段下跌）

硬邊界：phone_sync blocked；不改 leave_zero／ma60_lower。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class Pivot:
    i: int
    price: float
    kind: str  # H / L
    date: str = ""


@dataclass
class TailBackFive:
    ok_new_start: bool
    ok_five: bool
    today_up: bool
    new_start: Optional[Pivot] = None
    prior_high: Optional[Pivot] = None
    five_points: List[Pivot] = field(default_factory=list)  # 0..5：高起→五波低終
    fail_reason_zh: str = ""
    note_zh: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _is_up_day(o: float, c: float, prev_c: float | None = None) -> bool:
    if c > o + 1e-12:
        return True
    if prev_c is not None and c > prev_c + 1e-12:
        return True
    return False


def find_new_start_low(
    bars: Sequence[Dict[str, float]],
    *,
    lookback_days: int = 8,
) -> Optional[Pivot]:
    """今日上漲時：前幾日（含今日）最低點＝新開始。"""
    if len(bars) < 3:
        return None
    last = bars[-1]
    prev_c = float(bars[-2]["close"]) if len(bars) >= 2 else None
    if not _is_up_day(float(last["open"]), float(last["close"]), prev_c):
        return None
    win = list(bars[-max(2, lookback_days) :])
    # 取窗內最低 low；若多根同低取最早那根（起漲錨）
    best_i_local = 0
    best_low = float(win[0]["low"])
    for j, b in enumerate(win):
        lo = float(b["low"])
        if lo < best_low - 1e-12:
            best_low = lo
            best_i_local = j
    abs_i = len(bars) - len(win) + best_i_local
    return Pivot(
        i=abs_i,
        price=best_low,
        kind="L",
        date=str(bars[abs_i].get("date") or ""),
    )


def _fractal_pivots(
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    left: int = 2,
) -> List[Pivot]:
    n = len(highs)
    raw: List[Pivot] = []
    if n < left * 2 + 1:
        return raw
    for i in range(left, n - left):
        if highs[i] >= max(highs[i - left : i + left + 1]) - 1e-12:
            raw.append(Pivot(i=i, price=float(highs[i]), kind="H"))
        if lows[i] <= min(lows[i - left : i + left + 1]) + 1e-12:
            raw.append(Pivot(i=i, price=float(lows[i]), kind="L"))
    raw.sort(key=lambda p: p.i)
    out: List[Pivot] = []
    for p in raw:
        if not out:
            out.append(p)
            continue
        if p.kind == out[-1].kind:
            if p.kind == "H" and p.price >= out[-1].price:
                out[-1] = p
            elif p.kind == "L" and p.price <= out[-1].price:
                out[-1] = p
        else:
            out.append(p)
    return out


def _filter_degree(
    piv: Sequence[Pivot],
    *,
    min_bars: int = 2,
    min_pct: float = 0.015,
) -> List[Pivot]:
    out: List[Pivot] = []
    for p in piv:
        if not out:
            out.append(p)
            continue
        if p.kind == out[-1].kind:
            if p.kind == "H" and p.price >= out[-1].price:
                out[-1] = p
            elif p.kind == "L" and p.price <= out[-1].price:
                out[-1] = p
            continue
        bars = p.i - out[-1].i
        amp = abs(p.price - out[-1].price) / max(out[-1].price, 1e-9)
        if bars < min_bars or amp < min_pct:
            continue
        out.append(p)
    return out


def _right_dominant_highs(
    bars: Sequence[Dict[str, float]],
    *,
    start_i: int,
    end_i: int,
) -> List[Pivot]:
    """右側無更高高的波段起點候選（由近→遠）。

    台光電教法：新開始低 2560 往回，起點是 10/7 的 6325，不是更早絕對高 6470。
    取「從此高到終低之間沒有更高高」的 H，再由近到遠試五波。
    """
    if end_i <= start_i + 4:
        return []
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    raw = _fractal_pivots(highs[start_i : end_i + 1], lows[start_i : end_i + 1], left=2)
    for p in raw:
        p.i = start_i + p.i
        p.date = str(bars[p.i].get("date") or "")
    # 也允許窗內絕對最高日當候選（即使不是 fractal）
    jmax = max(range(start_i, end_i + 1), key=lambda j: highs[j])
    abs_peak = Pivot(
        i=jmax,
        price=highs[jmax],
        kind="H",
        date=str(bars[jmax].get("date") or ""),
    )
    h_piv = [p for p in raw if p.kind == "H"]
    if not any(p.i == abs_peak.i for p in h_piv):
        h_piv.append(abs_peak)
    # 右側主導：peak..end 內 max high == peak.high
    cands: List[Pivot] = []
    for p in h_piv:
        if p.i >= end_i - 4:
            continue
        seg_max = max(highs[p.i : end_i + 1])
        if highs[p.i] + 1e-9 >= seg_max:
            cands.append(p)
    # 由近到遠（越靠近終低越先試＝本段結構，不跨到上一段）
    cands.sort(key=lambda p: p.i, reverse=True)
    # 去重 index
    seen: set[int] = set()
    out: List[Pivot] = []
    for p in cands:
        if p.i in seen:
            continue
        seen.add(p.i)
        out.append(p)
    return out


def _alt_hl(piv: Sequence[Pivot]) -> List[Pivot]:
    """強制 H/L 交替（同向取更極端）。"""
    alt: List[Pivot] = []
    for p in piv:
        if not alt:
            alt.append(p)
            continue
        if p.kind == alt[-1].kind:
            if p.kind == "H" and p.price >= alt[-1].price:
                alt[-1] = p
            elif p.kind == "L" and p.price <= alt[-1].price:
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def _force_peak_end(
    piv: Sequence[Pivot],
    bars: Sequence[Dict[str, float]],
    peak: Pivot,
    new_start: Pivot,
) -> List[Pivot]:
    peak_abs = int(peak.i)
    i5 = int(new_start.i)
    prior_high = Pivot(
        i=peak_abs,
        price=float(bars[peak_abs]["high"]),
        kind="H",
        date=str(bars[peak_abs].get("date") or ""),
    )
    end_low = Pivot(
        i=i5, price=float(new_start.price), kind="L", date=new_start.date
    )
    mid = [p for p in piv if peak_abs < p.i < i5]
    return _alt_hl([prior_high] + mid + [end_low])


def _pivots_fractal(
    bars: Sequence[Dict[str, float]],
    peak: Pivot,
    new_start: Pivot,
    *,
    left: int,
    min_bars: int,
    min_pct: float,
) -> List[Pivot]:
    peak_abs = int(peak.i)
    i5 = int(new_start.i)
    sub_h = [float(b["high"]) for b in bars[peak_abs : i5 + 1]]
    sub_l = [float(b["low"]) for b in bars[peak_abs : i5 + 1]]
    raw = _fractal_pivots(sub_h, sub_l, left=int(left))
    for p in raw:
        p.i = peak_abs + p.i
        p.date = str(bars[p.i].get("date") or "")
    piv = _filter_degree(raw, min_bars=int(min_bars), min_pct=float(min_pct))
    return _force_peak_end(piv, bars, peak, new_start)


def _pivots_day_swing(
    bars: Sequence[Dict[str, float]],
    peak: Pivot,
    new_start: Pivot,
) -> List[Pivot]:
    """急殺短段備援：逐日紅K取低、綠K取高＋低，再交替（健策／南電型）。"""
    peak_abs = int(peak.i)
    i5 = int(new_start.i)
    raw: List[Pivot] = []
    for i in range(peak_abs + 1, i5):
        b = bars[i]
        o, h, l, c = (
            float(b["open"]),
            float(b["high"]),
            float(b["low"]),
            float(b["close"]),
        )
        d = str(b.get("date") or "")
        if c < o - 1e-12:
            raw.append(Pivot(i=i, price=l, kind="L", date=d))
        else:
            raw.append(Pivot(i=i, price=h, kind="H", date=d))
            raw.append(Pivot(i=i, price=l, kind="L", date=d))
    return _force_peak_end(raw, bars, peak, new_start)


def _pivots_peak_to_low(
    bars: Sequence[Dict[str, float]],
    peak: Pivot,
    new_start: Pivot,
) -> List[Pivot]:
    """波段高→新開始低：轉折點（強制起高終低、交替）。

    先 fractal left=2；點數不夠再 left=1；仍不夠用逐日擺動（急殺短段）。
    實際過關仍以鐵律為準——這裡只負責產出候選轉折。
    """
    primary = _pivots_fractal(
        bars, peak, new_start, left=2, min_bars=2, min_pct=0.012
    )
    if len(primary) >= 6:
        return primary
    loose = _pivots_fractal(
        bars, peak, new_start, left=1, min_bars=1, min_pct=0.015
    )
    if len(loose) >= 6:
        return loose
    return _pivots_day_swing(bars, peak, new_start)


def _pivot_strategies(
    bars: Sequence[Dict[str, float]],
    peak: Pivot,
    new_start: Pivot,
) -> List[List[Pivot]]:
    """多策略轉折，供試畫逐一過鐵律（避免只靠一種抽稀漏掉健策／南電）。"""
    seen: set[Tuple[Tuple[int, str, float], ...]] = set()
    out: List[List[Pivot]] = []
    for piv in (
        _pivots_fractal(bars, peak, new_start, left=2, min_bars=2, min_pct=0.012),
        _pivots_fractal(bars, peak, new_start, left=1, min_bars=1, min_pct=0.015),
        _pivots_day_swing(bars, peak, new_start),
    ):
        key = tuple((p.i, p.kind, round(float(p.price), 4)) for p in piv)
        if key in seen:
            continue
        seen.add(key)
        out.append(piv)
    return out


def _ranges_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    lo_a, hi_a = (a0, a1) if a0 <= a1 else (a1, a0)
    lo_b, hi_b = (b0, b1) if b0 <= b1 else (b1, b0)
    return not (hi_b < lo_a - 1e-9 or lo_b > hi_a + 1e-9)


def _overlap_depth_pct(a0: float, a1: float, b0: float, b1: float) -> float:
    lo_a, hi_a = (a0, a1) if a0 <= a1 else (a1, a0)
    lo_b, hi_b = (b0, b1) if b0 <= b1 else (b1, b0)
    inter = min(hi_a, hi_b) - max(lo_a, lo_b)
    if inter <= 0:
        return 0.0
    short = min(hi_a - lo_a, hi_b - lo_b)
    if short <= 1e-12:
        return 1.0
    return float(inter / short)


# ①④ 淺疊容差：南亞科型只差數檔（深度≤8%）仍算「畫得出五波」觀察過關；
# 深度更大＝真重疊，鐵律擋。非買訊／非話筒浪認證。
IRON_14_SOFT_DEPTH = 0.08


def iron_laws_down_five(
    five: Sequence[Pivot],
    *,
    soft_overlap_depth: float = IRON_14_SOFT_DEPTH,
) -> Tuple[bool, str]:
    """下跌五波推進鐵律（對齊 WR-IRON-*／wave8 簡核）。

    點序：H0,L1,H2,L3,H4,L5
    - ③非最短（①③⑤）
    - ①與④價區不重疊（淺疊深度≤soft 仍過，標淺疊）
    - ②不穿越起點（H2 < H0）
    - ③創新低（L3 < L1）；⑤再創新低（L5 < L3）
    """
    if not (
        len(five) == 6
        and five[0].kind == "H"
        and five[-1].kind == "L"
        and all(five[k].kind == ("H" if k % 2 == 0 else "L") for k in range(6))
    ):
        return False, f"轉折抽稀後={len(five)}，無法穩定定義五波"
    h0, l1, h2, l3, h4, l5 = (float(five[i].price) for i in range(6))
    # 下跌方向硬序
    if not (h2 < h0 - 1e-9):
        return False, "鐵律：②高不得穿越起點（H2≥H0）"
    if not (l3 < l1 - 1e-9):
        return False, "鐵律：③須低於①低（L3≥L1）"
    if not (l5 < l3 - 1e-9):
        return False, "鐵律：⑤須再創新低（L5≥L3）"
    # WR-IRON-W3-NOT-SHORTEST
    legs135 = [abs(l1 - h0), abs(l3 - h2), abs(l5 - h4)]
    if legs135[1] + 1e-9 < min(legs135[0], legs135[2]):
        return False, "鐵律：③非①③⑤最短"
    # WR-IRON-14-OVERLAP：①價區 vs ④價區（淺疊容差）
    depth = _overlap_depth_pct(h0, l1, l3, h4)
    if depth > float(soft_overlap_depth) + 1e-12:
        return False, f"鐵律：①與④價區不重疊（深度{depth:.0%}）"
    if depth > 1e-12:
        return True, f"淺疊{depth:.0%}≤容差{float(soft_overlap_depth):.0%}（觀察可畫）"
    return True, ""


def _five_wave_ok(five: Sequence[Pivot]) -> Tuple[bool, str]:
    """結構＋下跌推進鐵律。"""
    return iron_laws_down_five(five)


def try_five_wave_back_from_low(
    bars: Sequence[Dict[str, float]],
    new_start: Pivot,
    *,
    search_back: int = 120,
) -> TailBackFive:
    """由新開始低點往回，試畫前一段下跌的五波（0高→1低→2高→3低→4高→5低）。

    起點不取搜尋窗絕對最高（會跨到上一段，如 6470）；改取右側無更高高、
    由近到遠第一個能過五波檢核的波段高（台光電＝6325→2560）。
    """
    today_up = True
    if new_start is None:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="無新開始低點",
        )

    n = len(bars)
    i5 = int(new_start.i)
    if i5 <= 10 or i5 >= n:
        return TailBackFive(
            ok_new_start=True,
            ok_five=False,
            today_up=today_up,
            new_start=new_start,
            fail_reason_zh="新開始位置太靠前／無效",
            note_zh="低點已定，但往回空間不足",
        )

    start_i = max(0, i5 - int(search_back))
    cands = _right_dominant_highs(bars, start_i=start_i, end_i=i5)
    if not cands:
        return TailBackFive(
            ok_new_start=True,
            ok_five=False,
            today_up=today_up,
            new_start=new_start,
            fail_reason_zh="找不到右側主導波段高",
        )

    best_fail: Optional[TailBackFive] = None
    best_any_five: Optional[TailBackFive] = None
    # 現價：優先「次級四浪高仍在上方」(room>0)；健策／南電近段峰常已過四浪高
    last_close = float(bars[-1]["close"]) if bars else 0.0

    def _try_piv(peak: Pivot, piv: List[Pivot]) -> Optional[TailBackFive]:
        nonlocal best_fail, best_any_five
        prior_high = Pivot(
            i=int(peak.i),
            price=float(bars[int(peak.i)]["high"]),
            kind="H",
            date=str(bars[int(peak.i)].get("date") or ""),
        )
        five = _thin_to_five_down(piv)
        ok, reason = _five_wave_ok(five)
        if ok and five and len(five) >= 6:
            note = (
                f"由尾回推五波可定義：高{five[0].price:.0f}→低{five[5].price:.0f}；"
                f"今日連回新開始低{new_start.price:.0f}"
            )
            hit = TailBackFive(
                ok_new_start=True,
                ok_five=True,
                today_up=today_up,
                new_start=new_start,
                prior_high=prior_high,
                five_points=list(five),
                fail_reason_zh="",
                note_zh=note,
            )
            # room>0：立刻收（由近到遠第一個仍有回測空間）
            if float(five[4].price) > last_close + 1e-9:
                return hit
            # 可畫但已過四浪高：先記下，繼續找仍有空間的起點
            if best_any_five is None:
                best_any_five = hit
            return None
        if best_fail is None:
            best_fail = TailBackFive(
                ok_new_start=True,
                ok_five=False,
                today_up=today_up,
                new_start=new_start,
                prior_high=prior_high,
                five_points=list(five) if five else list(piv),
                fail_reason_zh=reason
                or f"轉折點數={len(piv)}，抽稀後={len(five)}，無法穩定定義五波",
                note_zh="五波未過關，僅標新開始與波段高",
            )
        return None

    # 兩段：先 fractal（保台光電近段起點），全敗再用急殺逐日擺動備援
    for peak in cands:
        for piv in (
            _pivots_fractal(
                bars, peak, new_start, left=2, min_bars=2, min_pct=0.012
            ),
            _pivots_fractal(
                bars, peak, new_start, left=1, min_bars=1, min_pct=0.015
            ),
        ):
            got = _try_piv(peak, piv)
            if got is not None:
                return got
    for peak in cands:
        got = _try_piv(peak, _pivots_day_swing(bars, peak, new_start))
        if got is not None:
            return got

    if best_any_five is not None:
        return best_any_five
    return best_fail or TailBackFive(
        ok_new_start=True,
        ok_five=False,
        today_up=today_up,
        new_start=new_start,
        prior_high=cands[0],
        fail_reason_zh="候選起點皆未過五波檢核",
    )


def _thin_to_five_down(piv: Sequence[Pivot]) -> List[Pivot]:
    """把 H-L 交替序列抽成 6 點（五波下跌）。"""
    if len(piv) < 6:
        return list(piv)
    if len(piv) == 6:
        return list(piv)
    # 保留首尾；中間要 4 點（L H L H），從候選裡依段落幅度挑
    head, tail = piv[0], piv[-1]
    mid = list(piv[1:-1])
    # 需要剛好 HLHL（若 mid 過多，反覆合併最弱擺動）
    while len(mid) > 4:
        # 找相鄰三點中「中間擺動」幅度最小者合併
        best_k = 1
        best_amp = 1e99
        for k in range(1, len(mid) - 1):
            amp = abs(mid[k].price - mid[k - 1].price) + abs(mid[k + 1].price - mid[k].price)
            if amp < best_amp:
                best_amp = amp
                best_k = k
        # 刪掉 best_k，並修交替
        del mid[best_k]
        fixed: List[Pivot] = []
        for p in mid:
            if not fixed:
                fixed.append(p)
                continue
            if p.kind == fixed[-1].kind:
                if p.kind == "H" and p.price >= fixed[-1].price:
                    fixed[-1] = p
                elif p.kind == "L" and p.price <= fixed[-1].price:
                    fixed[-1] = p
            else:
                fixed.append(p)
        mid = fixed
    out = [head] + mid + [tail]
    # 再保證交替
    alt: List[Pivot] = []
    for p in out:
        if not alt:
            alt.append(p)
            continue
        if p.kind == alt[-1].kind:
            if p.kind == "H" and p.price >= alt[-1].price:
                alt[-1] = p
            elif p.kind == "L" and p.price <= alt[-1].price:
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def analyze_bars(bars: Sequence[Dict[str, float]]) -> TailBackFive:
    """完整：今日漲？→新開始→往回五波。"""
    if len(bars) < 30:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="K棒不足",
        )
    last = bars[-1]
    prev_c = float(bars[-2]["close"])
    today_up = _is_up_day(float(last["open"]), float(last["close"]), prev_c)
    if not today_up:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="今日非上漲，先不定義新開始",
            note_zh="規則：今日上漲才連回前低當新開始",
        )
    ns = find_new_start_low(bars, lookback_days=8)
    if ns is None:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=True,
            fail_reason_zh="找不到前幾日低點",
        )
    return try_five_wave_back_from_low(bars, ns)
