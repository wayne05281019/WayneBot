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

from wave_pot_boundary import stamp_mine

EXT_RATIO = 1.618

# §13 靜默對質鍵（只記我估鍋；不准混飆大／海選勝率）
RULE_PHONE_EXT = "mine_ext1618_v1"
RULE_NEXT_EXT = "mine_ext1618_v2"  # 再生：+③非最短＋禁標準 impulse 1–4 重疊
RULE_PHONE_LD = "mine_lead_diag_v1"
RULE_NEXT_LD = "mine_lead_diag_v2"  # 再生：+重疊深度≥8%＋位置或結構至少一項

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
    require_w3_not_shortest: bool = False,
    forbid_w1_w4_overlap: Optional[bool] = None,
) -> Dict[str, Any]:
    """擴延波檢測：L_max ≥ ratio × L_second_max。

    ``lengths`` 典型鍵 ``"1"``／``"3"``／``"5"``（也可只傳有的浪）。
    回傳一律可 JSON 化；``pass``＝過核心閘。我估鍋；≠飆大反彈壓價表。

    v2 強化（``require_w3_not_shortest``／``forbid_w1_w4_overlap``）：
    - ①③⑤ 齊時③不可最短，否則 fail（variant=w3_shortest）。
    - 若呼叫端已知標準 impulse 下 1–4 重疊為真，則不准當擴延推進 pass。
    """
    cleaned: Dict[str, float] = {}
    for k, v in (lengths or {}).items():
        fv = _f(v)
        if fv is None or fv < 0:
            continue
        cleaned[str(k)] = float(fv)

    ordered = sorted(cleaned.items(), key=lambda kv: kv[1], reverse=True)

    def _out(**kw: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "threshold": float(ratio),
            "lengths": cleaned,
            "w3_not_shortest": motive_w3_not_shortest(cleaned),
            "phone_label": "我估｜擴延1618",
            "≠biaoke_fib_rebound_table": True,
            "basis": "L_max≥1.618×L_2nd",
        }
        base.update(kw)
        # allow pass_ alias
        if "pass_" in base:
            base["pass"] = bool(base.pop("pass_"))
        return stamp_mine(base)

    if len(ordered) < 2:
        return _out(
            **{
                "pass": False,
                "ratio": None,
                "longest": ordered[0][0] if ordered else None,
                "second": None,
                "variant": "insufficient_legs",
                "basis": "need≥2 motive legs",
            }
        )

    (long_k, long_v), (sec_k, sec_v) = ordered[0], ordered[1]
    if sec_v <= 0:
        return _out(
            **{
                "pass": False,
                "ratio": None,
                "longest": long_k,
                "second": sec_k,
                "variant": "zero_second",
                "basis": "second length≤0",
            }
        )

    got = long_v / sec_v
    passed = got + 1e-12 >= float(ratio)
    variant: Optional[str] = None
    w3_ok = motive_w3_not_shortest(cleaned)
    if not passed:
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

    if require_w3_not_shortest and w3_ok is False:
        passed = False
        variant = "w3_shortest"

    if forbid_w1_w4_overlap is True:
        passed = False
        variant = "w1_w4_overlap_not_impulse_ext"

    return _out(
        **{
            "pass": bool(passed),
            "ratio": float(got),
            "longest": long_k,
            "second": sec_k,
            "variant": variant,
        }
    )


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
    depth = overlap_depth_pct(w1_start, w1_end, w4_start, w4_end)
    return stamp_mine(
        {
            "overlap": ov,
            "overlap_depth_pct": depth,
            "w1": {"start": _f(w1_start), "end": _f(w1_end)},
            "w4": {"start": _f(w4_start), "end": _f(w4_end)},
            "basis": "w1_w4_price_range_overlap; ≠biaoke_14_forbid→auto_leading_diagonal",
            "phone_label": "我估｜前端傾斜",
        }
    )


def leading_diagonal_flags(
    *,
    w1_w4_overlap: Optional[bool],
    position_ok: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
    overlap_depth_pct: Optional[float] = None,
    min_overlap_depth: float = 0.0,
    require_pos_or_struct: bool = False,
) -> Dict[str, Any]:
    """前端傾斜旗標組裝（純規則；內部 5-3-5-3-5 由呼叫端先判再傳入）。"""
    overlap = None if w1_w4_overlap is None else bool(w1_w4_overlap)
    pos = None if position_ok is None else bool(position_ok)
    struct = None if structure_53535 is None else bool(structure_53535)
    depth = _f(overlap_depth_pct)
    depth_ok = True if float(min_overlap_depth) <= 0 else (
        depth is not None and depth + 1e-12 >= float(min_overlap_depth)
    )
    candidate = overlap is True and depth_ok
    if require_pos_or_struct and candidate:
        if pos is None and struct is None:
            candidate = False
        elif not (pos is True or struct is True):
            candidate = False
    confirmed = (
        overlap is True
        and depth_ok
        and pos is True
        and struct is True
    )
    return stamp_mine(
        {
            "candidate": candidate,
            "confirmed": confirmed,
            "w1_w4_overlap": overlap,
            "overlap_depth_pct": depth,
            "min_overlap_depth": float(min_overlap_depth),
            "position_ok": pos,
            "structure_53535": struct,
            "implication": "continuation",
            "vs_ending": "ending_diagonal=termination",
            "basis": "leading_diagonal: overlap(+pos+5-3-5-3-5)",
            "phone_label": "我估｜前端傾斜",
            "auto_promote_forbidden": True,
        }
    )


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
        return stamp_mine(
            {
                "ok": False,
                "direction": direction,
                "levels": {},
                "span": None,
                "basis": "缺高低",
                "≠biaoke_fib_rebound_table": True,
            }
        )
    if hi < lo:
        hi, lo = lo, hi
    span = hi - lo
    if span <= 0:
        return stamp_mine(
            {
                "ok": False,
                "direction": direction,
                "levels": {},
                "span": span,
                "basis": "span≤0",
                "≠biaoke_fib_rebound_table": True,
            }
        )
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
    return stamp_mine(
        {
            "ok": True,
            "direction": direction,
            "swing_high": hi,
            "swing_low": lo,
            "span": float(span),
            "levels": levels,
            "basis": "fib_retracement; pot=DC→我估",
            "≠biaoke_fib_rebound_table": True,
            "note_zh": "同比率數字≠他公開反彈壓價表；本函式＝我估工具",
        }
    )


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
        return stamp_mine(
            {"ok": False, "targets": {}, "basis": "缺起迄", "≠extension_1618_gate": True}
        )
    span = b - a
    if abs(span) < 1e-12:
        return stamp_mine(
            {
                "ok": False,
                "targets": {},
                "span": 0.0,
                "basis": "span≈0",
                "≠extension_1618_gate": True,
            }
        )
    origin = _f(from_price) if from_price is not None else b
    if origin is None:
        return stamp_mine(
            {
                "ok": False,
                "targets": {},
                "basis": "缺投影起點",
                "≠extension_1618_gate": True,
            }
        )
    targets: Dict[str, float] = {}
    for r in ratios:
        rf = _f(r)
        if rf is None:
            continue
        targets[f"{rf:g}"] = float(origin + rf * span)
    return stamp_mine(
        {
            "ok": True,
            "start": a,
            "end": b,
            "from_price": origin,
            "span": float(span),
            "targets": targets,
            "basis": "fib_extension_projection; pot=DC→我估; ≠extension_1618_gate",
            "≠extension_1618_gate": True,
        }
    )


def wave_equality_guide(
    length_ref: Number,
    length_compare: Number,
    *,
    tol: float = 0.05,
) -> Dict[str, Any]:
    """波浪等長指引：compare／ref ≈ 1 ± tol → equal 候選。我估指引，非他說。"""
    a, b = _f(length_ref), _f(length_compare)
    if a is None or b is None or a <= 0:
        return stamp_mine(
            {
                "ok": False,
                "ratio": None,
                "equalish": None,
                "basis": "缺長度",
            }
        )
    ratio = b / a
    return stamp_mine(
        {
            "ok": True,
            "ratio": float(ratio),
            "equalish": abs(ratio - 1.0) <= float(tol),
            "tol": float(tol),
            "length_ref": float(a),
            "length_compare": float(b),
            "basis": "wave_equality_guide; pot=DC→我估",
        }
    )


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
        return stamp_mine(
            {
                "ok": False,
                "alternates": None,
                "w2_kind": None,
                "w4_kind": None,
                "basis": "缺回撤％",
            }
        )

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
    return stamp_mine(
        {
            "ok": True,
            "alternates": bool(alt),
            "w2_kind": k2,
            "w4_kind": k4,
            "w2_retrace_pct": float(r2),
            "w4_retrace_pct": float(r4),
            "basis": "2_4_alternation_hint; pot=DC→我估",
        }
    )

def motive_w3_not_shortest(lengths: Mapping[str, Number]) -> Optional[bool]:
    """動機鐵律旁證：①③⑤ 齊時，③ 不可最短。缺腿→None。"""
    l1, l3, l5 = _f(lengths.get("1")), _f(lengths.get("3")), _f(lengths.get("5"))
    if None in (l1, l3, l5):
        return None
    return float(l3) + 1e-12 >= min(float(l1), float(l5))


def overlap_depth_pct(
    a_lo: Number,
    a_hi: Number,
    b_lo: Number,
    b_hi: Number,
) -> Optional[float]:
    """兩價區重疊深度＝交集長度／較短區間長度；無重疊→0；缺數→None。"""
    alo, ahi = _f(a_lo), _f(a_hi)
    blo, bhi = _f(b_lo), _f(b_hi)
    if None in (alo, ahi, blo, bhi):
        return None
    lo_a, hi_a = (alo, ahi) if alo <= ahi else (ahi, alo)
    lo_b, hi_b = (blo, bhi) if blo <= bhi else (bhi, blo)
    inter = min(hi_a, hi_b) - max(lo_a, lo_b)
    if inter <= 0:
        return 0.0
    short = min(hi_a - lo_a, hi_b - lo_b)
    if short <= 1e-12:
        return None
    return float(inter / short)


def ending_diagonal_flags(
    *,
    w1_w4_overlap: Optional[bool] = None,
    position_at_w5_or_C: Optional[bool] = None,
    wedge_converging: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
    curriculum_ready: bool = False,
) -> Dict[str, Any]:
    """末端傾斜旗標（終結意涵）。

    DC 末端完整教材尚未進 ``sources/`` 前：``curriculum_ready=False`` →
    永不 ``confirmed``，只留 candidate／缺件（不准假標 ending_diagonal）。
    對照前端：``implication=termination``。
    """
    overlap = None if w1_w4_overlap is None else bool(w1_w4_overlap)
    pos = None if position_at_w5_or_C is None else bool(position_at_w5_or_C)
    wedge = None if wedge_converging is None else bool(wedge_converging)
    struct = None if structure_53535 is None else bool(structure_53535)
    candidate = overlap is True and (pos is True or pos is None)
    # 教材未齊：confirmed 永遠 False
    confirmed = bool(
        curriculum_ready
        and candidate
        and pos is True
        and wedge is True
        and struct is True
    )
    return stamp_mine({
        "candidate": bool(candidate) if curriculum_ready else False,
        "confirmed": confirmed,
        "w1_w4_overlap": overlap,
        "position_at_w5_or_C": pos,
        "wedge_converging": wedge,
        "structure_53535": struct,
        "curriculum_ready": bool(curriculum_ready),
        "implication": "termination",
        "vs_leading": "leading_diagonal=continuation",
        "status": "ok" if curriculum_ready else "curriculum_pending",
        "basis": "ending_diagonal: need DC ending page; pot=DC→我估",
        "source": "mine",
        "pot": "DC→我估",
    })


def analyze_motive_from_pivot_prices(
    pivot_prices: Sequence[Number],
    *,
    position_ok: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
    ending_position_ok: Optional[bool] = None,
    wedge_converging: Optional[bool] = None,
) -> Dict[str, Any]:
    """由連續轉折價做擴延閘＋前後端傾斜粗檢（一律 source=mine／DC→我估）。

    需要 ≥6 個價（起點＋五浪終點）才有完整 1/3/5 與 ①④ 重疊；
    不足時 ``pass=False``／``variant=insufficient_pivots``，不腦補浪號。
    **不准**冒充飆大「他說」。
    """
    pts: List[float] = []
    for p in pivot_prices or []:
        fv = _f(p)
        if fv is not None:
            pts.append(float(fv))
    if len(pts) < 6:
        return stamp_mine({
            "source": "mine",
            "pot": "DC→我估",
            "ok": False,
            "extension": {
                "pass": False,
                "variant": "insufficient_pivots",
                "basis": "need≥6 pivot prices (start+5 ends)",
                "lengths": {},
            },
            "leading_diagonal": leading_diagonal_flags(
                w1_w4_overlap=None,
                position_ok=position_ok,
                structure_53535=structure_53535,
            ),
            "ending_diagonal": ending_diagonal_flags(
                w1_w4_overlap=None,
                position_at_w5_or_C=ending_position_ok,
                wedge_converging=wedge_converging,
            ),
            "pivot_n": len(pts),
            "basis": "analyze_motive_from_pivot_prices",
        })

    # 取前 6 點：start, w1, w2, w3, w4, w5
    six = pts[:6]
    lengths_all = lengths_from_pivots([(x,) for x in six])
    motive = {k: lengths_all[k] for k in ("1", "3", "5") if k in lengths_all}
    ext = detect_extension_1618(motive)
    ov = check_w1_w4_overlap(six[0], six[1], six[3], six[4])
    ld = leading_diagonal_flags(
        w1_w4_overlap=ov.get("overlap"),
        position_ok=position_ok,
        structure_53535=structure_53535,
    )
    ld["w1_w4_check"] = ov
    ed = ending_diagonal_flags(
        w1_w4_overlap=ov.get("overlap"),
        position_at_w5_or_C=ending_position_ok,
        wedge_converging=wedge_converging,
        structure_53535=structure_53535,
        curriculum_ready=False,
    )
    return stamp_mine({
        "source": "mine",
        "pot": "DC→我估",
        "ok": True,
        "pivot_prices": [float(x) for x in six],
        "lengths": lengths_all,
        "extension": ext,
        "leading_diagonal": ld,
        "ending_diagonal": ed,
        "basis": "analyze_motive_from_pivot_prices; ≠他說",
    })


def mine_wave_from_impulse_nodes(
    start_price: Number,
    confirmed: Sequence[Mapping[str, Any]],
    *,
    projected: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """從 ``infer_dc_wave_scenario`` 的 start＋confirmed（可選 projected）組 mine_wave。

    標籤 ``(1)``…``(5)`` 價依序；缺段不腦補。結果欄位對齊 activate checklist。
    """
    by_lab: Dict[str, float] = {}
    for node in list(confirmed or []) + list(projected or []):
        lab = str((node or {}).get("label") or "").strip()
        px = _f((node or {}).get("price"))
        if lab in ("(1)", "(2)", "(3)", "(4)", "(5)") and px is not None:
            by_lab[lab] = float(px)
    start = _f(start_price)
    ordered: List[float] = []
    if start is not None:
        ordered.append(float(start))
    for lab in ("(1)", "(2)", "(3)", "(4)", "(5)"):
        if lab in by_lab:
            ordered.append(by_lab[lab])
        else:
            break
    # 位置提示：有完整五浪 → 前端位置不預設 True（缺內部結構）；末端同理
    has_five = all(k in by_lab for k in ("(1)", "(2)", "(3)", "(4)", "(5)"))
    pack = analyze_motive_from_pivot_prices(
        ordered,
        position_ok=None,  # 不腦補 wave1_or_A
        structure_53535=None,
        ending_position_ok=True if has_five else None,
        wedge_converging=None,
    )
    pack["labels_present"] = sorted(by_lab.keys())
    pack["has_full_five"] = has_five
    return pack


def motive_lengths_from_nodes(
    start_price: Number,
    nodes: Sequence[Mapping[str, Any]],
) -> Dict[str, float]:
    """從浪節點（label=(1)(2)(3)(4)(5)）組動機浪 1/3/5 與修正 2/4 價距。

    ①＝|start→(1)|；②＝|(1)→(2)|；③＝|(2)→(3)|；④＝|(3)→(4)|；⑤＝|(4)→(5)|。
    缺節點則略該段。一律 pot=MINE。
    """
    by: Dict[str, float] = {}
    sp = _f(start_price)
    for n in nodes or []:
        lab = str(n.get("label") or "").strip()
        px = _f(n.get("price"))
        if px is None:
            continue
        if lab in ("(1)", "1", "①"):
            by["p1"] = px
        elif lab in ("(2)", "2", "②"):
            by["p2"] = px
        elif lab in ("(3)", "3", "③"):
            by["p3"] = px
        elif lab in ("(4)", "4", "④"):
            by["p4"] = px
        elif lab in ("(5)", "5", "⑤"):
            by["p5"] = px
    out: Dict[str, float] = {}
    if sp is not None and "p1" in by:
        out["1"] = abs(by["p1"] - sp)
    if "p1" in by and "p2" in by:
        out["2"] = abs(by["p2"] - by["p1"])
    if "p2" in by and "p3" in by:
        out["3"] = abs(by["p3"] - by["p2"])
    if "p3" in by and "p4" in by:
        out["4"] = abs(by["p4"] - by["p3"])
    if "p4" in by and "p5" in by:
        out["5"] = abs(by["p5"] - by["p4"])
    return out


def evaluate_mine_wave_gates(
    *,
    lengths: Optional[Mapping[str, Number]] = None,
    pivots: Optional[Sequence[Tuple[Number, ...]]] = None,
    w1_start: Optional[Number] = None,
    w1_end: Optional[Number] = None,
    w4_start: Optional[Number] = None,
    w4_end: Optional[Number] = None,
    position_ok: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
) -> Dict[str, Any]:
    """我估鍋統一閘：現況 v1 ＋ §13 下一版候選 v2（同件再生）。

    勝率／對質只准記 ``pot=MINE``；不准混飆大／海選／洞燭。
    不是買訊；不過閘不准發明 5／9 上話筒。
    """
    lens: Dict[str, float]
    if lengths:
        lens = {}
        for k, v in lengths.items():
            fv = _f(v)
            if fv is not None and fv >= 0:
                lens[str(k)] = float(fv)
    elif pivots:
        lens = lengths_from_pivots(pivots)
    else:
        lens = {}

    motive = {k: lens[k] for k in ("1", "3", "5") if k in lens}
    ov_pack: Optional[Dict[str, Any]] = None
    if None not in (w1_start, w1_end, w4_start, w4_end):
        ov_pack = check_w1_w4_overlap(w1_start, w1_end, w4_start, w4_end)
    elif pivots and len(pivots) >= 5:
        pts = [_f(p[0]) if isinstance(p, (tuple, list)) else _f(p) for p in pivots[:5]]
        pts = [p for p in pts if p is not None]
        if len(pts) >= 5:
            ov_pack = check_w1_w4_overlap(pts[0], pts[1], pts[3], pts[4])

    overlap = None if ov_pack is None else ov_pack.get("overlap")
    depth = None if ov_pack is None else ov_pack.get("overlap_depth_pct")

    ext_v1 = detect_extension_1618(motive if len(motive) >= 2 else lens)
    ext_v2 = detect_extension_1618(
        motive if len(motive) >= 2 else lens,
        require_w3_not_shortest=True,
        forbid_w1_w4_overlap=True if overlap is True else None,
    )

    ld_v1 = leading_diagonal_flags(
        w1_w4_overlap=overlap,
        position_ok=position_ok,
        structure_53535=structure_53535,
        overlap_depth_pct=depth,
        min_overlap_depth=0.0,
        require_pos_or_struct=False,
    )
    ld_v2 = leading_diagonal_flags(
        w1_w4_overlap=overlap,
        position_ok=position_ok,
        structure_53535=structure_53535,
        overlap_depth_pct=depth,
        min_overlap_depth=0.08,
        require_pos_or_struct=True,
    )
    if ov_pack is not None:
        ld_v1["w1_w4_check"] = ov_pack
        ld_v2["w1_w4_check"] = ov_pack

    return stamp_mine({
        "source": "mine",
        "pot": "MINE",
        "label_prefix": "我估",
        "≠biaoke": True,
        "≠golden_buy": True,
        "lengths": lens,
        "motive_lengths": motive,
        "extension": {
            "rule": RULE_PHONE_EXT,
            **ext_v1,
        },
        "extension_next": {
            "rule": RULE_NEXT_EXT,
            **ext_v2,
        },
        "leading_diagonal": {
            "rule": RULE_PHONE_LD,
            **ld_v1,
        },
        "leading_diagonal_next": {
            "rule": RULE_NEXT_LD,
            **ld_v2,
        },
        "track_keys": {
            "phone_ext": RULE_PHONE_EXT,
            "next_ext": RULE_NEXT_EXT,
            "phone_ld": RULE_PHONE_LD,
            "next_ld": RULE_NEXT_LD,
        },
        "basis": "DC→我估結構閘；三鍋分標；§13 再生下一版",
    })


def judge_mine_practice(
    gate_pass: Optional[bool],
    *,
    post_move_pct: Optional[float] = None,
    expect_continuation: bool = True,
    continue_thresh: float = 0.01,
    reverse_thresh: float = 0.02,
    incomplete: bool = False,
) -> Dict[str, Any]:
    """靜默對質裁決：對／偏／未完（只記我估鍋）。

    - 未完：腿不足／後續柱不足／incomplete。
    - 對：閘過且後續同向延續≥continue_thresh（或閘不過且後續反向確認非推進）。
    - 偏：閘過但後續反向≥reverse_thresh；或閘不過但後續強延續（漏抓）。
    """
    if incomplete or gate_pass is None or post_move_pct is None:
        return stamp_mine({
            "verdict": "未完",
            "scoreable": False,
            "gate_pass": gate_pass,
            "post_move_pct": post_move_pct,
            "pot": "MINE",
        })
    move = float(post_move_pct)
    gp = bool(gate_pass)
    cont = move >= float(continue_thresh) if expect_continuation else move <= -float(continue_thresh)
    rev = move <= -float(reverse_thresh) if expect_continuation else move >= float(reverse_thresh)
    if gp and cont:
        verd = "對"
    elif gp and rev:
        verd = "偏"
    elif (not gp) and rev:
        # 閘擋下且真的反向＝擋對
        verd = "對"
    elif (not gp) and cont:
        verd = "偏"  # 漏抓推進
    else:
        verd = "未完"
    return stamp_mine({
        "verdict": verd,
        "scoreable": verd in ("對", "偏"),
        "gate_pass": gp,
        "post_move_pct": move,
        "continuation": cont,
        "reversal": rev,
        "pot": "MINE",
    })


def summarize_mine_practice(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """彙總我估對質列：n／勝率只算 scoreable；勝率不准混他鍋。"""
    scored = [r for r in rows if (r.get("judge") or {}).get("scoreable")]
    hit = sum(1 for r in scored if (r.get("judge") or {}).get("verdict") == "對")
    miss = sum(1 for r in scored if (r.get("judge") or {}).get("verdict") == "偏")
    pending = sum(
        1 for r in rows if (r.get("judge") or {}).get("verdict") == "未完"
    )
    n = hit + miss
    wr = (hit / n) if n else None
    return stamp_mine({
        "pot": "MINE",
        "n_scoreable": n,
        "n_hit": hit,
        "n_miss": miss,
        "n_pending": pending,
        "n_rows": len(list(rows)),
        "winrate": wr,
        "gate_ready_n20": bool(n >= 20),
        "≠mixed_pots": True,
        "basis": "勝率只記我估鍋；n≥20且贏現況才換（§13）",
    })

