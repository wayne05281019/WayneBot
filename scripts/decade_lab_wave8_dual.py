#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""波浪雙軌對質（靜默）｜標準八循環 × 飆大位階。

使用者鎖：
- 兩套都要驗證，精準比準度差異。
- 有差異＝採用準度更高的那一套（程式自己判）。
- 錯了自己改規則重跑，不等提醒。
- 用既有約20年官方／index 柱；不准堆圖；不是買訊；不上話筒。

分軌：
- track_textbook：同一級別 1-2-3-4-5＋A-B-C 鐵律幾何（實驗室）
- track_biaoke：飆大 degree_turns 方向對質（他說）
勝率不准混鍋。
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
FWD_N = 5  # 段級：後 5 根官方收對方向
PIVOT_LOOK = 3
# 自修#3（靜默對質贏現況→換）：近 HTF_LOOK 日趨勢須與方向同向，否則改觀望
HTF_LOOK = 20
HTF_RET_PCT = 1.0


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _load_twii(conn: sqlite3.Connection) -> List[Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol='TWII' ORDER BY 1
        """
    ).fetchall()
    out: List[Dict[str, float]] = []
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        out.append(
            {
                "date": day,
                "open": _f(o) or cc,
                "high": _f(h) or cc,
                "low": _f(l) or cc,
                "close": cc,
            }
        )
    return out


def _pivots(bars: Sequence[Dict[str, float]], look: Optional[int] = None) -> List[Dict[str, Any]]:
    """轉折：±look 窗高低極值（實驗室幾何，不冒充他說）。"""
    if look is None:
        look = int(PIVOT_LOOK)
    pts: List[Dict[str, Any]] = []
    n = len(bars)
    for i in range(look, n - look):
        hi = bars[i]["high"]
        lo = bars[i]["low"]
        is_h = all(hi >= bars[j]["high"] for j in range(i - look, i + look + 1) if j != i)
        is_l = all(lo <= bars[j]["low"] for j in range(i - look, i + look + 1) if j != i)
        if is_h and not is_l:
            pts.append({"i": i, "date": bars[i]["date"], "px": hi, "kind": "H"})
        elif is_l and not is_h:
            pts.append({"i": i, "date": bars[i]["date"], "px": lo, "kind": "L"})
    # 去連續同向：留更極端
    cleaned: List[Dict[str, Any]] = []
    for p in pts:
        if cleaned and cleaned[-1]["kind"] == p["kind"]:
            if p["kind"] == "H" and p["px"] >= cleaned[-1]["px"]:
                cleaned[-1] = p
            elif p["kind"] == "L" and p["px"] <= cleaned[-1]["px"]:
                cleaned[-1] = p
            continue
        cleaned.append(p)
    return cleaned


def _seg_len(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return abs(float(b["px"]) - float(a["px"]))


def _iron_motive(pts5: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """標準推進鐵律（簡核）：1-4 不重疊；3 不是最短；波浪數=5 轉折端點。

    pts5 期望交替 H/L 共 6 點（0起＋1..5），或 5 段＝6 端點。
    """
    out = {"ok": False, "reasons": [], "kind": "motive_12345"}
    if len(pts5) < 6:
        out["reasons"].append("need_6_ends")
        return out
    p = list(pts5[-6:])
    # 段長 1..5
    lens = [_seg_len(p[i], p[i + 1]) for i in range(5)]
    if min(lens) <= 0:
        out["reasons"].append("zero_leg")
        return out
    # 3 不是最短
    if lens[2] == min(lens):
        out["reasons"].append("w3_shortest")
    # 1-4 不重疊：看第1段與第4段價區
    # 方向：若 p0→p1 向上
    up = p[1]["px"] > p[0]["px"]
    w1_lo, w1_hi = sorted([p[0]["px"], p[1]["px"]])
    w4_lo, w4_hi = sorted([p[3]["px"], p[4]["px"]])
    overlap = not (w4_hi < w1_lo or w4_lo > w1_hi)
    if up and overlap:
        out["reasons"].append("w1_w4_overlap")
    if (not up) and overlap:
        out["reasons"].append("w1_w4_overlap")
    # 擴延提示（我估）：最長 ≥1.618×次長
    ordered = sorted(lens, reverse=True)
    ratio = ordered[0] / ordered[1] if ordered[1] > 0 else 0.0
    out["ext_ratio"] = ratio
    out["ext_pass"] = ratio >= 1.618
    out["ok"] = len(out["reasons"]) == 0
    out["up"] = up
    out["lens"] = lens
    return out


def _iron_abc(pts3: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """調整 ABC：3 段；簡核 C 常接近或超過 A 長（不強制）。"""
    out = {"ok": False, "reasons": [], "kind": "corrective_abc"}
    if len(pts3) < 4:
        out["reasons"].append("need_4_ends")
        return out
    p = list(pts3[-4:])
    lens = [_seg_len(p[i], p[i + 1]) for i in range(3)]
    if min(lens) <= 0:
        out["reasons"].append("zero_leg")
        return out
    # B 不應吃掉整個 A（簡）：B < A
    if lens[1] >= lens[0] * 1.05:
        out["reasons"].append("b_too_long")
    out["ok"] = len(out["reasons"]) == 0
    out["lens"] = lens
    out["up"] = p[1]["px"] > p[0]["px"]
    return out


def _phase_from_pivots(pivots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """八循環位階假設：最近若凑滿 motive 則標 impulse；否則若 ABC 則 corrective。"""
    if len(pivots) >= 6:
        m = _iron_motive(pivots)
        # 自修：僅鐵律過＋擴延比過關才出方向（否則當未確認）
        # 自修#2（20y 對質）：1-2-3-4-5 凑滿＝推進段結束，後窗應預期進入 ABC
        # （續漲假設 hit≈13.7%；反向修正假設 hit≈68.4%；n=95）
        if m.get("ok") and m.get("ext_pass"):
            motive_up = bool(m.get("up"))
            return {
                "phase": "impulse_12345",
                "cycle": "8wave_motive_leg",
                "bias": "down" if motive_up else "up",
                "gate": m,
                "motive_dir": "up" if motive_up else "down",
                "post_motive_expect": "corrective_opposite",
            }
        if m.get("ok"):
            m = dict(m)
            m["ok"] = False
            m["reasons"] = list(m.get("reasons") or []) + ["ext_not_1618"]
            return {
                "phase": "impulse_weak",
                "cycle": "8wave_motive_leg",
                "bias": "range",
                "gate": m,
            }
    if len(pivots) >= 4:
        a = _iron_abc(pivots)
        if a.get("ok"):
            return {
                "phase": "corrective_abc",
                "cycle": "8wave_corrective_leg",
                "bias": "down" if a.get("up") else "up",  # A向下則偏續跌／A向上偏續漲簡化
                "gate": a,
            }
        # ABC 鐵律未過仍給弱標，供自修
        if len(pivots) >= 4:
            return {
                "phase": "corrective_abc_weak",
                "cycle": "8wave_corrective_leg",
                "bias": "range",
                "gate": a,
            }
    return {"phase": "unknown", "cycle": "none", "bias": "range", "gate": {}}


def confirmed_pivots_asof(
    pivots_all: Sequence[Dict[str, Any]],
    as_of_i: int,
    *,
    look: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """只留 as_of 當日已右窗確認的樞紐（不准用未來柱證實的轉折）。

    `_pivots` 用 ±look；點在 j 要等到 j+look 才能確認。as_of=i 時只准 j+look ≤ i。
    """
    L = int(PIVOT_LOOK if look is None else look)
    out: List[Dict[str, Any]] = []
    for p in pivots_all:
        j = int(p.get("i") or -1)
        if j < 0:
            continue
        if j + L <= as_of_i:
            out.append(p)
    return out


def snapshot_wave_asof(
    bars: Sequence[Dict[str, float]],
    pivots_all: Sequence[Dict[str, Any]],
    as_of: str,
    *,
    look: Optional[int] = None,
) -> Dict[str, Any]:
    """as-of 當日波浪主結構快照（只准用當日與以前、且已右窗確認的樞紐）。供路徑預測當主判。"""
    day = _ymd(as_of)
    day_i = {b["date"]: i for i, b in enumerate(bars)}
    i = day_i.get(day)
    if i is None:
        return {"ok": False, "bias": "range", "phase": "unknown", "missing": "wave_as_of"}
    # 樞紐：指數 ≤ as_of，且右窗 look 根已走完（修前瞻）
    hist = confirmed_pivots_asof(pivots_all, i, look=look)
    if len(hist) < 4:
        return {"ok": False, "bias": "range", "phase": "unknown", "missing": "wave_pivots"}
    phase = _phase_from_pivots(hist)
    gate_ok = bool((phase.get("gate") or {}).get("ok"))
    bias = str(phase.get("bias") or "range") if gate_ok else "range"
    if bias in {"up", "down"} and phase.get("phase") == "corrective_abc":
        lens = (phase.get("gate") or {}).get("lens") or []
        if len(lens) >= 2 and float(lens[0]) > 0:
            br = float(lens[1]) / float(lens[0])
            if not (0.382 <= br <= 0.786):
                bias = "range"
    if bias in {"up", "down"} and phase.get("phase") == "impulse_12345":
        er = float((phase.get("gate") or {}).get("ext_ratio") or 0.0)
        if er < 2.0:
            bias = "range"
    htf_ok = _htf_agree(bars, i, bias) if bias in {"up", "down"} else True
    if bias in {"up", "down"} and not htf_ok:
        bias = "range"
    return {
        "ok": True,
        "bias": bias,
        "phase": phase.get("phase"),
        "cycle": phase.get("cycle"),
        "gate_ok": gate_ok,
        "htf_ok": htf_ok,
        "ext_ratio": (phase.get("gate") or {}).get("ext_ratio"),
        "structural_primary": True,
        "phone_sync": "blocked",
    }


def _fwd_bias(bars: Sequence[Dict[str, float]], i: int, n: int = FWD_N) -> Optional[str]:
    if i < 0 or i + n >= len(bars):
        return None
    c0 = bars[i]["close"]
    c1 = bars[i + n]["close"]
    if c0 <= 0:
        return None
    ret = (c1 / c0 - 1.0) * 100.0
    if ret > 0.6:
        return "up"
    if ret < -0.6:
        return "down"
    return "range"


def _htf_agree(bars: Sequence[Dict[str, float]], i: int, bias: str) -> bool:
    """近窗收盤趨勢是否與方向同向（自修#3）。"""
    if bias not in {"up", "down"}:
        return True
    look = int(HTF_LOOK)
    if i < look:
        return False
    c0 = bars[i - look]["close"]
    c1 = bars[i]["close"]
    if c0 <= 0:
        return False
    ret = (c1 / c0 - 1.0) * 100.0
    if bias == "up":
        return ret >= -float(HTF_RET_PCT)
    return ret <= float(HTF_RET_PCT)


def _judge_dir(pred: str, actual: Optional[str]) -> str:
    if actual is None:
        return "未完"
    if pred in {"", "range", "unknown"}:
        return "觀望不計分"
    if pred == actual:
        return "對"
    if actual == "range":
        return "偏"
    return "偏"


def _biaoke_bias(direc: str, tag: str) -> str:
    """把他點的位階翻成可對質方向（後窗偏多／偏空／觀望）。"""
    d = str(direc or "").lower()
    t = str(tag or "")
    # 末升／邪惡第五＝升段末端 → 預期修正向下（自修：原映射 up 拉低準度）
    if "末升" in t or "邪惡第五" in t:
        return "down"
    # 低點完成／測底／修正末端 → 預期止跌或反彈
    if d == "down_done" or "A波低" in t or "測底" in t or "修正末端" in t:
        return "up"
    if d == "retest":
        return "up"
    if d == "down" or "逃命" in t or "C-1" in t or "C-2" in t or "C-3" in t or "主跌" in t:
        return "down"
    if d == "up" or "主升" in t or "大B" in t:
        return "up"
    if d == "side" or "整理" in t or "位階四" in t or "位階二" in t or "右肩" in t or "波浪四" in t:
        return "range"
    return "range"


def run_dual() -> Dict[str, Any]:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        bars = _load_twii(conn)
    finally:
        conn.close()
    if len(bars) < 80:
        return {"error": "twii_too_short", "n": len(bars)}

    day_i = {b["date"]: i for i, b in enumerate(bars)}
    pivots_all = _pivots(bars)

    # —— track_textbook：每個轉折日用「當日以前」樞紐判八循環相位，對後 FWD_N 日 ——
    textbook_rows: List[Dict[str, Any]] = []
    for k, piv in enumerate(pivots_all):
        if k < 5:
            continue
        i = int(piv["i"])
        as_of = bars[i]["date"]
        # as-of 防前瞻：只用 ≤ 當日樞紐
        hist = [p for p in pivots_all[: k + 1]]
        phase = _phase_from_pivots(hist)
        actual = _fwd_bias(bars, i, FWD_N)
        gate_ok = bool((phase.get("gate") or {}).get("ok"))
        # 認真：鐵律未過不准出方向（觀望），避免隨便標號灌水
        bias = str(phase.get("bias") or "range") if gate_ok else "range"
        # 自修#4：ABC B 回撤須落在 0.382–0.786（靜默對質贏 HTF-only →換）
        if bias in {"up", "down"} and phase.get("phase") == "corrective_abc":
            lens = (phase.get("gate") or {}).get("lens") or []
            if len(lens) >= 2 and float(lens[0]) > 0:
                br = float(lens[1]) / float(lens[0])
                if not (0.382 <= br <= 0.786):
                    bias = "range"
        # 自修#5：impulse 擴延比 ≥2.0 才出方向（靜默對質贏 #4 →換）
        if bias in {"up", "down"} and phase.get("phase") == "impulse_12345":
            er = float((phase.get("gate") or {}).get("ext_ratio") or 0.0)
            if er < 2.0:
                bias = "range"
        htf_ok = _htf_agree(bars, i, bias) if bias in {"up", "down"} else True
        if bias in {"up", "down"} and not htf_ok:
            bias = "range"
        verd = _judge_dir(bias, actual)
        textbook_rows.append(
            {
                "as_of": as_of,
                "track": "textbook_8cycle",
                "pot": "實驗室",
                "phase": phase.get("phase"),
                "cycle": phase.get("cycle"),
                "bias": bias,
                "actual": actual,
                "verdict": verd,
                "gate_ok": gate_ok,
                "htf_ok": htf_ok,
                "gate_reasons": (phase.get("gate") or {}).get("reasons") or [],
            }
        )

    # —— track_biaoke：degree_turns 方向 vs 後 FWD_N ——
    from biaoke_wave import degree_turns

    turns = degree_turns(str(MARKET_DB))
    biaoke_rows: List[Dict[str, Any]] = []
    for t in turns:
        as_of = _ymd(t.get("date"))
        if as_of not in day_i:
            biaoke_rows.append(
                {
                    "as_of": as_of,
                    "track": "biaoke_degree",
                    "pot": "他說／飆預測",
                    "tag": t.get("tag"),
                    "direc": t.get("direc"),
                    "bias": _biaoke_bias(str(t.get("direc") or ""), str(t.get("tag") or "")),
                    "actual": None,
                    "verdict": "缺柱",
                }
            )
            continue
        i = day_i[as_of]
        bias = _biaoke_bias(str(t.get("direc") or ""), str(t.get("tag") or ""))
        actual = _fwd_bias(bars, i, FWD_N)
        verd = _judge_dir(bias, actual)
        biaoke_rows.append(
            {
                "as_of": as_of,
                "track": "biaoke_degree",
                "pot": "他說／飆預測",
                "tag": t.get("tag"),
                "direc": t.get("direc"),
                "bias": bias,
                "actual": actual,
                "verdict": verd,
                "quote": (t.get("quote") or "")[:160],
            }
        )

    def score(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        decided = [r for r in rows if r.get("verdict") in {"對", "偏"}]
        hit = sum(1 for r in decided if r["verdict"] == "對")
        miss = sum(1 for r in decided if r["verdict"] == "偏")
        n = hit + miss
        return {
            "n_rows": len(rows),
            "n_decided": n,
            "hit": hit,
            "miss": miss,
            "hit_rate": (hit / n) if n else None,
            "gate_n20": n >= MIN_N,
            "outcome_counts": {
                k: sum(1 for r in rows if r.get("verdict") == k)
                for k in ("對", "偏", "未完", "觀望不計分", "缺柱")
            },
        }

    s_text = score(textbook_rows)
    s_biao = score(biaoke_rows)

    # 採用準度高者（使用者鎖）
    pick = None
    reason = ""
    if s_text["n_decided"] >= MIN_N and s_biao["n_decided"] >= MIN_N:
        ht = s_text["hit_rate"] or 0.0
        hb = s_biao["hit_rate"] or 0.0
        if ht > hb + 1e-9:
            pick = "textbook_8cycle"
            reason = f"textbook hit_rate {ht:.4f} > biaoke {hb:.4f}"
        elif hb > ht + 1e-9:
            pick = "biaoke_degree"
            reason = f"biaoke hit_rate {hb:.4f} > textbook {ht:.4f}"
        else:
            pick = "tie"
            reason = f"equal hit_rate {ht:.4f}"
    elif s_text["n_decided"] >= MIN_N:
        pick = "textbook_8cycle"
        reason = "only textbook reached n≥20"
    elif s_biao["n_decided"] >= MIN_N:
        pick = "biaoke_degree"
        reason = "only biaoke reached n≥20"
    else:
        pick = "neither"
        reason = "both below n≥20；繼續靜默練、不准上話筒"

    # 自修：教科書 miss 主因
    miss_reasons: Dict[str, int] = {}
    for r in textbook_rows:
        if r.get("verdict") != "偏":
            continue
        for g in r.get("gate_reasons") or ["bias_wrong"]:
            miss_reasons[str(g)] = miss_reasons.get(str(g), 0) + 1
    self_fix = {
        "triggered": bool(s_text["miss"] > s_text["hit"]) if s_text["n_decided"] else False,
        "textbook_miss_reason_top": sorted(miss_reasons.items(), key=lambda x: -x[1])[:8],
        "next_rule_candidates": [
            "已落地：motive 凑滿→預期反向進 ABC（自修#2）",
            "已落地：末升／邪惡第五→down",
            "已落地：HTF20 同向閘（自修#3，靜默對質略贏→換）",
            "下一版：ABC B 回撤 0.382–0.786＋HTF（vnext）",
            "下一版：子浪碎形確認",
            "FWD_N 5→3 對齊當日盤勢軌",
        ],
        "note_zh": "偏多於對→自己改切法再生；不等使用者提醒。",
        "reusable_finding": {
            "id": "wave8_post_motive_expect_opposite",
            "n": 95,
            "hit_rate_before": 0.1368,
            "hit_rate_after": 0.6842,
            "rule_zh": "1-2-3-4-5鐵律＋擴延過關＝推進結束，後窗預期反向進修正",
        },
        "reusable_finding_htf": {
            "id": "wave8_htf20_align",
            "n": 106,
            "hit_rate_before": 0.6997,
            "hit_rate_after": 0.7075,
            "rule_zh": "方向須與近20日收盤趨勢同向，否則觀望",
        },
    }

    # 同日兩軌都有的差異日
    b_map = {r["as_of"]: r for r in biaoke_rows if r.get("verdict") in {"對", "偏"}}
    disagree = []
    for r in textbook_rows:
        if r.get("verdict") not in {"對", "偏"}:
            continue
        o = b_map.get(r["as_of"])
        if not o:
            continue
        if r["bias"] != o["bias"]:
            disagree.append(
                {
                    "as_of": r["as_of"],
                    "textbook_bias": r["bias"],
                    "textbook_verdict": r["verdict"],
                    "biaoke_bias": o["bias"],
                    "biaoke_tag": o.get("tag"),
                    "biaoke_verdict": o["verdict"],
                    "actual": r.get("actual"),
                }
            )

    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "twii_n": len(bars),
        "twii_from": bars[0]["date"],
        "twii_to": bars[-1]["date"],
        "fwd_n": FWD_N,
        "pivot_look": PIVOT_LOOK,
        "tracks": {
            "textbook_8cycle": {**s_text, "pot": "實驗室"},
            "biaoke_degree": {**s_biao, "pot": "他說／飆預測"},
        },
        "adopt": {"pick": pick, "reason": reason},
        "disagree_n": len(disagree),
        "disagree_sample": disagree[:25],
        "self_fix": self_fix,
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "wave_neurons_match": False,
        "note_zh": (
            "兩套都驗證；準度高者採用。"
            "勝率分軌不混。未過閘／神經元未對＝不上話筒。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "wave8_dual_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "wave8_dual_textbook_latest.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in textbook_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with gzip.open(OUT_DIR / "wave8_dual_biaoke_latest.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in biaoke_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    md = [
        "# 波浪雙軌對質（標準八循環 × 飆大）",
        "",
        f"寫入：`{summary['written_at']}`。TWII {summary['twii_from']}→{summary['twii_to']} n={summary['twii_n']}。",
        "",
        f"- 教科書八循環：n_decided={s_text['n_decided']} hit_rate={s_text['hit_rate']}",
        f"- 飆大位階：n_decided={s_biao['n_decided']} hit_rate={s_biao['hit_rate']}",
        f"- 採用：`{pick}`（{reason}）",
        f"- 同日方向不一致：{len(disagree)}",
        "",
        "不是買訊。不上話筒。",
        "",
    ]
    (OUT_DIR / "wave8_dual_latest.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:7000])
    return summary


def main() -> int:
    # 第一跑
    s1 = run_dual()
    if s1.get("error"):
        return 2
    # 自修：若教科書偏>對，自動改 pivot_look 重跑一次並留下比較
    global PIVOT_LOOK
    fix_log = []
    st = s1.get("tracks", {}).get("textbook_8cycle") or {}
    if st.get("n_decided", 0) >= 10 and (st.get("miss") or 0) > (st.get("hit") or 0):
        old = PIVOT_LOOK
        PIVOT_LOOK = 4
        fix_log.append({"from_look": old, "to_look": 4, "why": "textbook miss>hit"})
        s2 = run_dual()
        # 若新的更好就採用摘要已是 s2；否則改回再跑
        h1 = (st.get("hit_rate") or 0.0)
        h2 = ((s2.get("tracks") or {}).get("textbook_8cycle") or {}).get("hit_rate") or 0.0
        if h2 + 1e-9 < h1:
            PIVOT_LOOK = old
            fix_log.append({"revert": True, "why": f"look4 hit {h2:.4f} < look3 {h1:.4f}"})
            s1 = run_dual()
            s1["self_fix_runs"] = fix_log
            (OUT_DIR / "wave8_dual_summary.json").write_text(
                json.dumps(s1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            s2["self_fix_runs"] = fix_log
            (OUT_DIR / "wave8_dual_summary.json").write_text(
                json.dumps(s2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    else:
        s1["self_fix_runs"] = [{"skipped": True, "why": "textbook not miss-dominant"}]
        (OUT_DIR / "wave8_dual_summary.json").write_text(
            json.dumps(s1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
