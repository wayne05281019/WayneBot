# -*- coding: utf-8 -*-
"""我的波浪結構純規則（擴延 161.8%／前端傾斜 1–4 重疊）。

來源消化：D.C 直流變頻教學圖 → 變成 AI 自己的判斷工具（source=mine）。
單向：可參考同學／老師；輸出不准冒充飆大原文，也不准寫回黃金買點。

- detect_extension_1618：五浪群最長浪 ≥ 161.8% × 次長 → 推進擴延候選。
- check_w1_w4_overlap／leading_diagonal_flags：①④ 價區重疊（前端傾斜特徵之一）。

不是買訊；盤中未收柱呼叫端自己擋。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

EXT_RATIO = 1.618

Number = Union[int, float]


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def wave_price_length(start: Number, end: Number) -> Optional[float]:
    """價距絕對值；缺數回 None。"""
    a, b = _f(start), _f(end)
    if a is None or b is None:
        return None
    return abs(b - a)


def detect_extension_1618(
    lengths: Mapping[str, Number],
    *,
    ratio: float = EXT_RATIO,
) -> Dict[str, Any]:
    """擴延波檢測：L_max ≥ ratio × L_second_max。

    ``lengths`` 典型鍵 ``\"1\"``／``\"3\"``／``\"5\"``（也可只傳有的浪）。
    回傳一律可 JSON 化；``pass``＝過核心閘。
    """
    cleaned: Dict[str, float] = {}
    for k, v in (lengths or {}).items():
        fv = _f(v)
        if fv is None or fv < 0:
            continue
        cleaned[str(k)] = float(fv)

    ordered = sorted(cleaned.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) < 2:
        return {
            "pass": False,
            "ratio": None,
            "threshold": float(ratio),
            "longest": ordered[0][0] if ordered else None,
            "second": None,
            "lengths": cleaned,
            "variant": "insufficient_legs",
            "basis": "need≥2 motive legs",
        }

    (long_k, long_v), (sec_k, sec_v) = ordered[0], ordered[1]
    if sec_v <= 0:
        return {
            "pass": False,
            "ratio": None,
            "threshold": float(ratio),
            "longest": long_k,
            "second": sec_k,
            "lengths": cleaned,
            "variant": "zero_second",
            "basis": "second length≤0",
        }

    got = long_v / sec_v
    passed = got + 1e-12 >= float(ratio)
    variant: Optional[str] = None
    if not passed:
        # 例外標籤（digest §1）：僅提示，不自動升格為 pass
        l1 = cleaned.get("1")
        l3 = cleaned.get("3")
        l5 = cleaned.get("5")
        if long_k == "1" and l3 is not None and l1 is not None:
            variant = "rare_motive_variant_w1_longest"
        elif (
            l3 is not None
            and l1 is not None
            and l5 is not None
            and l3 >= l1
            and l3 >= l5
            and l3 < float(ratio) * l1
            and l5 < l3
        ):
            variant = "rare_ending_motive_variant"

    return {
        "pass": bool(passed),
        "ratio": float(got),
        "threshold": float(ratio),
        "longest": long_k,
        "second": sec_k,
        "lengths": cleaned,
        "variant": variant,
        "basis": f"L_max≥{ratio:g}×L_2nd",
    }


def price_ranges_overlap(
    a_lo: Number,
    a_hi: Number,
    b_lo: Number,
    b_hi: Number,
) -> Optional[bool]:
    """兩價區是否重疊（閉區間）。缺數→None。"""
    alo, ahi = _f(a_lo), _f(a_hi)
    blo, bhi = _f(b_lo), _f(b_hi)
    if None in (alo, ahi, blo, bhi):
        return None
    lo_a, hi_a = (alo, ahi) if alo <= ahi else (ahi, alo)
    lo_b, hi_b = (blo, bhi) if blo <= bhi else (bhi, blo)
    return not (hi_a < lo_b or hi_b < lo_a)


def check_w1_w4_overlap(
    w1_start: Number,
    w1_end: Number,
    w4_start: Number,
    w4_end: Number,
) -> Dict[str, Any]:
    """① 與 ④ 價區是否重疊（前端傾斜關鍵特徵；標準 impulse 禁止）。"""
    ov = price_ranges_overlap(w1_start, w1_end, w4_start, w4_end)
    return {
        "overlap": ov,
        "w1": {"start": _f(w1_start), "end": _f(w1_end)},
        "w4": {"start": _f(w4_start), "end": _f(w4_end)},
        "basis": "w1_w4_price_range_overlap",
    }


def leading_diagonal_flags(
    *,
    w1_w4_overlap: Optional[bool],
    position_ok: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
) -> Dict[str, Any]:
    """前端傾斜旗標組裝（純規則；內部 5-3-5-3-5 由呼叫端先判再傳入）。

    implication=continuation（vs ending_diagonal=termination）。
    candidate＝重疊為真；confirmed 還要位置＋結構（缺則 False）。
    """
    overlap = None if w1_w4_overlap is None else bool(w1_w4_overlap)
    pos = None if position_ok is None else bool(position_ok)
    struct = None if structure_53535 is None else bool(structure_53535)
    candidate = overlap is True
    confirmed = candidate and pos is True and struct is True
    return {
        "candidate": candidate,
        "confirmed": confirmed,
        "w1_w4_overlap": overlap,
        "position_ok": pos,
        "structure_53535": struct,
        "implication": "continuation",
        "vs_ending": "ending_diagonal=termination",
        "basis": "leading_diagonal: overlap(+pos+5-3-5-3-5)",
    }


def lengths_from_pivots(
    pivots: Sequence[Tuple[Number, Number]],
) -> Dict[str, float]:
    """連續轉折點 (price, ...) 序列 → 浪價距。

    pivots 長度 n 產生 n-1 段；鍵 ``\"1\"``起編。只取絕對價距。
    """
    out: Dict[str, float] = {}
    pts = [_f(p[0]) if isinstance(p, (tuple, list)) else _f(p) for p in pivots]
    pts = [p for p in pts if p is not None]
    for i in range(len(pts) - 1):
        out[str(i + 1)] = abs(float(pts[i + 1]) - float(pts[i]))
    return out


# --- 序C：Fib／等長／交替（一律 source=mine／我估；≠他說） ---

DEFAULT_RETRACE_RATIOS: Tuple[float, ...] = (0.382, 0.5, 0.618, 0.75, 0.786)
DEFAULT_EXT_RATIOS: Tuple[float, ...] = (1.0, 1.272, 1.618, 2.618)


def fib_retracement_levels(
    swing_high: Number,
    swing_low: Number,
    *,
    ratios: Sequence[float] = DEFAULT_RETRACE_RATIOS,
    direction: str = "bounce_from_low",
) -> Dict[str, Any]:
    """回撤／反彈 Fib 位（價）。

    ``bounce_from_low``：低→高區間的回升壓力＝ low + r×(high−low)。
    ``pullback_from_high``：高→低區間的回檔支撐＝ high − r×(high−low)。
    與鐵律衝突時呼叫端必須鐵律優先。不是買訊。
    """
    hi, lo = _f(swing_high), _f(swing_low)
    if hi is None or lo is None:
        return {
            "ok": False,
            "direction": direction,
            "levels": {},
            "span": None,
            "basis": "缺高低",
        }
    if hi < lo:
        hi, lo = lo, hi
    span = hi - lo
    if span <= 0:
        return {
            "ok": False,
            "direction": direction,
            "levels": {},
            "span": span,
            "basis": "span≤0",
        }
    levels: Dict[str, float] = {}
    for r in ratios:
        rf = _f(r)
        if rf is None:
            continue
        key = f"{rf:g}"
        if direction == "pullback_from_high":
            levels[key] = float(hi - rf * span)
        else:
            levels[key] = float(lo + rf * span)
    return {
        "ok": True,
        "direction": direction,
        "swing_high": hi,
        "swing_low": lo,
        "span": float(span),
        "levels": levels,
        "basis": "fib_retracement; pot=DC→我估",
    }


def fib_extension_targets(
    start: Number,
    end: Number,
    *,
    ratios: Sequence[float] = DEFAULT_EXT_RATIOS,
    from_price: Optional[Number] = None,
) -> Dict[str, Any]:
    """投影／延伸目標（等長 C＝1.0；1.272／1.618／2.618）。

    以 ``start→end`` 為參考浪價距；自 ``from_price``（缺則＝end）同向延伸。
    **≠** 擴延 1618 閘（五浪群內 L_max 比）。
    """
    a, b = _f(start), _f(end)
    if a is None or b is None:
        return {"ok": False, "targets": {}, "basis": "缺起迄"}
    span = b - a
    if abs(span) < 1e-12:
        return {"ok": False, "targets": {}, "span": 0.0, "basis": "span≈0"}
    origin = _f(from_price) if from_price is not None else b
    if origin is None:
        return {"ok": False, "targets": {}, "basis": "缺投影起點"}
    targets: Dict[str, float] = {}
    for r in ratios:
        rf = _f(r)
        if rf is None:
            continue
        targets[f"{rf:g}"] = float(origin + rf * span)
    return {
        "ok": True,
        "start": a,
        "end": b,
        "from_price": origin,
        "span": float(span),
        "targets": targets,
        "basis": "fib_extension_projection; pot=DC→我估; ≠extension_1618_gate",
    }


def wave_equality_guide(
    length_ref: Number,
    length_compare: Number,
    *,
    tol: float = 0.05,
) -> Dict[str, Any]:
    """波浪等長指引：compare／ref ≈ 1 ± tol → equal 候選。我估指引，非他說。"""
    a, b = _f(length_ref), _f(length_compare)
    if a is None or b is None or a <= 0:
        return {
            "ok": False,
            "ratio": None,
            "equalish": None,
            "basis": "缺長度",
        }
    ratio = b / a
    return {
        "ok": True,
        "ratio": float(ratio),
        "equalish": abs(ratio - 1.0) <= float(tol),
        "tol": float(tol),
        "length_ref": float(a),
        "length_compare": float(b),
        "basis": "wave_equality_guide; pot=DC→我估",
    }


def alternation_2_4_hint(
    w2_retrace_pct: Number,
    w4_retrace_pct: Number,
    *,
    sharp_lt: float = 0.5,
    flat_ge: float = 0.5,
) -> Dict[str, Any]:
    """2 與 4 交替粗檢：一銳一平（回撤％相對 0.5）。我估指引。"""
    r2, r4 = _f(w2_retrace_pct), _f(w4_retrace_pct)
    if r2 is None or r4 is None:
        return {
            "ok": False,
            "alternates": None,
            "w2_kind": None,
            "w4_kind": None,
            "basis": "缺回撤％",
        }

    def _kind(r: float) -> str:
        if r < sharp_lt:
            return "sharp"
        if r >= flat_ge:
            return "flat_or_deep"
        return "mid"

    k2, k4 = _kind(r2), _kind(r4)
    alt = (k2 == "sharp" and k4 == "flat_or_deep") or (
        k2 == "flat_or_deep" and k4 == "sharp"
    )
    return {
        "ok": True,
        "alternates": bool(alt),
        "w2_kind": k2,
        "w4_kind": k4,
        "w2_retrace_pct": float(r2),
        "w4_retrace_pct": float(r4),
        "basis": "2_4_alternation_hint; pot=DC→我估",
    }
