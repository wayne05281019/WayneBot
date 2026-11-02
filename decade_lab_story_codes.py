# -*- coding: utf-8 -*-
"""十年旁路｜序D 裸K／量價故事碼（實驗室粗檢）。

只吃已收 OHLCV；缺數標缺。不是買訊；不准冒充他說、不准寫回黃金買點。
半山腰／新聞擁擠需個股位階或外部語料 → 呼叫端標缺，本模組不腦補。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

Number = Any


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _bar(b: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    o, h, l, c = _f(b.get("open") if "open" in b else b.get("o")), _f(
        b.get("high") if "high" in b else b.get("h")
    ), _f(b.get("low") if "low" in b else b.get("l")), _f(
        b.get("close") if "close" in b else b.get("c")
    )
    v = _f(b.get("volume") if "volume" in b else b.get("v"))
    if None in (o, h, l, c):
        return None
    return {"o": o, "h": h, "l": l, "c": c, "v": v if v is not None else 0.0}


def _median(xs: Sequence[float]) -> Optional[float]:
    vals = sorted(float(x) for x in xs)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def classify_barek_stories(
    bars: Sequence[Mapping[str, Any]],
    *,
    vol_quiet_ratio: float = 0.7,
    climax_ratio: float = 0.95,
    gap_pct: float = 0.01,
    limit_pct: float = 0.095,
) -> Dict[str, Any]:
    """對近窗最後一根（as-of 日）標故事碼旗標。

    ``bars`` 升序；最後一根＝事件日已收柱。回傳可 JSON 化。
    """
    parsed: List[Dict[str, float]] = []
    dates: List[str] = []
    for b in bars:
        pb = _bar(b)
        if pb is None:
            continue
        parsed.append(pb)
        dates.append(str(b.get("date") or ""))
    out: Dict[str, Any] = {
        "ok": len(parsed) >= 2,
        "as_of_date": dates[-1] if dates else None,
        "n": len(parsed),
        "codes": {},
        "missing": [],
        "pot": "實驗室",
        "not_buy_signal": True,
        "basis": "decade_lab_story_codes.classify_barek_stories",
    }
    if len(parsed) < 2:
        out["missing"].append("近窗柱不足2")
        return out

    cur, prev = parsed[-1], parsed[-2]
    prior = parsed[:-1]
    vols = [p["v"] for p in prior if p["v"] > 0]
    med_v = _median(vols) if vols else None
    max_v = max(vols) if vols else None
    prior_lows = [p["l"] for p in prior]
    prior_highs = [p["h"] for p in prior]
    min_prior_low = min(prior_lows) if prior_lows else None
    max_prior_high = max(prior_highs) if prior_highs else None

    down = cur["c"] < prev["c"] or cur["c"] < cur["o"]
    up = cur["c"] > prev["c"] or cur["c"] > cur["o"]
    dry = med_v is not None and cur["v"] < med_v * vol_quiet_ratio
    climax = max_v is not None and max_v > 0 and cur["v"] >= max_v * climax_ratio

    codes: Dict[str, Any] = {}
    codes["dry_continue_down"] = {
        "hit": bool(down and dry),
        "label": "無量續跌",
        "note": "綠跌／收跌＋量<近窗中位×quiet；≠止穩",
    }
    break_low = min_prior_low is not None and cur["l"] < min_prior_low
    codes["break_low_no_climax"] = {
        "hit": bool(break_low and not climax),
        "label": "沒爆量破低",
        "note": "破近窗低但非爆量 → 籌碼未換完風險",
    }
    codes["climax_turnover"] = {
        "hit": bool(climax and (up or down)),
        "label": "爆量換手",
        "note": "量近／超近窗最大；只標現象不當買",
    }

    # 套牢鏈：紅→更深紅（或漲後連兩綠）
    trap = False
    if len(parsed) >= 3:
        a, b, c = parsed[-3], parsed[-2], parsed[-1]
        a_up = a["c"] > a["o"]
        b_dn = b["c"] < b["o"]
        c_dn = c["c"] < c["o"]
        trap = bool(a_up and b_dn and c_dn and c["c"] < b["c"])
    codes["trap_chain"] = {
        "hit": trap,
        "label": "套牢鏈",
        "note": "漲後連兩根收跌且加深",
    }

    # 破線翻：當日低破前低，收盤站回前低之上
    flip = False
    if min_prior_low is not None:
        flip = bool(cur["l"] < min_prior_low and cur["c"] > min_prior_low)
    codes["break_line_flip"] = {
        "hit": flip,
        "label": "破線翻",
        "note": "刺破近窗低後收站回；洗盤觀察非出貨定論",
    }

    # 兩根確認：連兩日收破近窗低／高
    two = False
    side = None
    if len(parsed) >= 3 and min_prior_low is not None and max_prior_high is not None:
        # 用更早窗當參考（不含最近兩根）
        base = parsed[:-2]
        if base:
            bl = min(p["l"] for p in base)
            bh = max(p["h"] for p in base)
            if parsed[-1]["c"] < bl and parsed[-2]["c"] < bl:
                two, side = True, "down"
            elif parsed[-1]["c"] > bh and parsed[-2]["c"] > bh:
                two, side = True, "up"
    codes["two_bar_confirm"] = {
        "hit": two,
        "side": side,
        "label": "兩根確認",
        "note": "連兩收破／過參考高低；單根只待確認",
    }

    # 露餡／第一根大量：前段安靜後首根放量
    first_big = False
    if len(vols) >= 5 and med_v and med_v > 0:
        quiet = all(v <= med_v * vol_quiet_ratio for v in vols[-5:])
        first_big = bool(quiet and cur["v"] >= med_v * 1.8)
    codes["first_big_volume"] = {
        "hit": first_big,
        "label": "露餡／第一根大量",
        "note": "近5日偏安靜後放量",
    }

    # 窒息量：近窗有爆量日後，當日量縮到極低
    choke = False
    if max_v and max_v > 0 and med_v and med_v > 0:
        had_attack = max_v >= med_v * 1.8
        choke = bool(had_attack and cur["v"] <= med_v * 0.4)
    codes["choke_volume"] = {
        "hit": choke,
        "label": "窒息量",
        "note": "攻擊量後縮到極致；無公式閾值僅粗檢",
    }

    # 跳空
    gap = None
    if prev["c"] != 0:
        gap = (cur["o"] - prev["c"]) / abs(prev["c"])
    codes["gap_open"] = {
        "hit": bool(gap is not None and abs(gap) >= gap_pct),
        "gap_pct": gap,
        "label": "跳空",
        "note": "開相對昨收；竭盡與否需後續確認",
    }

    # 漲跌停粗檢（約±9.5%）
    pct = None
    if prev["c"] != 0:
        pct = (cur["c"] - prev["c"]) / abs(prev["c"])
    codes["limit_move_approx"] = {
        "hit": bool(pct is not None and abs(pct) >= limit_pct),
        "pct_change": pct,
        "label": "漲跌停近似",
        "note": "無官方漲跌停旗；|Δ|≥9.5% 僅標近似",
    }

    # 量價背離：僅連續攻擊（≥3 同向）
    div = {"hit": False, "kind": None}
    if len(parsed) >= 4:
        last3 = parsed[-3:]
        up_streak = all(last3[i]["c"] > last3[i - 1]["c"] for i in range(1, 3)) and last3[0][
            "c"
        ] > parsed[-4]["c"]
        dn_streak = all(last3[i]["c"] < last3[i - 1]["c"] for i in range(1, 3)) and last3[0][
            "c"
        ] < parsed[-4]["c"]
        if up_streak and last3[-1]["h"] >= max(p["h"] for p in last3) and last3[-1]["v"] < last3[0]["v"]:
            div = {"hit": True, "kind": "up_attack_vol_fade"}
        if dn_streak and last3[-1]["l"] <= min(p["l"] for p in last3) and last3[-1]["v"] < last3[0]["v"]:
            div = {"hit": True, "kind": "down_attack_vol_fade"}
    codes["attack_vol_divergence"] = {
        **div,
        "label": "量價背離（僅連續攻擊）",
        "note": "非攻擊段不標",
    }

    # 量先價行单條：近窗最大量日高低
    if prior:
        i_max = max(range(len(prior)), key=lambda i: prior[i]["v"])
        mv = prior[i_max]
        codes["vol_leads_price_single"] = {
            "hit": True,
            "label": "量先價行单條對照",
            "max_vol_date": dates[i_max] if i_max < len(dates) - 1 else dates[i_max],
            "high": mv["h"],
            "low": mv["l"],
            "note": "視窗一換爆量日就換；證不穩、不當買訊",
        }
    else:
        codes["vol_leads_price_single"] = {"hit": False, "label": "量先價行单條對照"}

    out["codes"] = codes
    out["missing"].extend(
        [
            "半山腰：需個股位階上下文（指數日略）",
            "新聞擁擠：無當日新聞密度欄",
            "組合K＋型態：本批只做量價旗標，型態名不腦補",
            "五件同點：需浪／形叠位，留後批",
        ]
    )
    out["hit_labels"] = [
        c["label"] for c in codes.values() if isinstance(c, dict) and c.get("hit")
    ]
    return out
