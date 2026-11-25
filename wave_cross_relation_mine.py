# -*- coding: utf-8 -*-
"""2023 起聯動×波浪位階：系統化假設網＋量化挖礦（靜默）。

目的：找出「值得再深挖」的關係候選，餵波浪加深軌。
不是買訊；phone_sync=blocked；WAVE_NEURONS_MATCH=false；
§13 未過閘不准換現況／不上話筒定案。

對齊（Asia/Taipei）：
- SOX／TSM ADR 美股已收 → 對下一開市台股日
- 2330／TWII＝台股日盤（2330 缺則 decade_lab raw_quote）
- TE／TX night＝期貨夜盤（覆蓋短則標 coverage_gap）
"""
from __future__ import annotations

import gzip
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
OUT_JSON = LAB / "wave_cross_relation_mine_latest.json"
OUT_MD = LAB / "wave_cross_relation_mine_latest.md"
OUT_DAILY = LAB / "wave_cross_daily_2023.jsonl.gz"
TAIPEI = ZoneInfo("Asia/Taipei")

TRACK = "wave_cross_relation_mine"
VARIANT = "mine_v1_sys_quant_2023"
PHONE_SYNC = "blocked"
PHONE_WARNING = "試標・推論／非他原文・非買訊・對質未過閘"
MIN_N = 20
SINCE_DEFAULT = "20230101"
UP = 0.6
DOWN = -0.6
HOLD = -0.25
LEVEL_TOL = 0.004  # 0.4% 觸碰容差
LEVEL_LOOKBACK_POSTS = 40  # 近窗口述位階材料


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


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


def _side(ret: Optional[float]) -> str:
    if ret is None:
        return "na"
    if ret >= UP:
        return "up"
    if ret <= DOWN:
        return "down"
    if ret >= HOLD:
        return "hold"
    return "soft"


def _year(day: str) -> str:
    return day[:4] if len(day) >= 4 else ""


def _load_index(
    conn: sqlite3.Connection, symbol: str
) -> Dict[str, Dict[str, float]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
            FROM index_daily WHERE symbol=? ORDER BY 1
            """,
            (symbol,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return _bars_from_rows(rows)


def _load_stock(
    conn: sqlite3.Connection, sid: str
) -> Dict[str, Dict[str, float]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
            FROM daily_quotes WHERE stock_id=? ORDER BY 1
            """,
            (sid,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return _bars_from_rows(rows)


def _load_fut(
    conn: sqlite3.Connection, symbol: str, session: str
) -> Dict[str, Dict[str, float]]:
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
            FROM futures_daily WHERE symbol=? AND session=? ORDER BY 1
            """,
            (symbol, session),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return _bars_from_rows(rows)


def _bars_from_rows(rows: Sequence[Tuple[Any, ...]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    prev: Optional[float] = None
    for d, o, h, lo, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = None if prev is None else (cc / prev - 1.0) * 100.0
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(lo) or cc,
            "c": cc,
            "ret": float(ret) if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_2330_lab(lab_db: Path) -> Dict[str, Dict[str, float]]:
    if not lab_db.is_file():
        return {}
    conn = sqlite3.connect(str(lab_db), timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
            FROM lab_daily
            WHERE symbol='2330' AND adj_kind='raw_quote'
            ORDER BY 1
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return _bars_from_rows(rows)


def _merge_bars(
    primary: Dict[str, Dict[str, float]], fill: Dict[str, Dict[str, float]]
) -> Dict[str, Dict[str, float]]:
    """官方優先；缺日用 fill。重算 ret 依合併後時間序。"""
    days = sorted(set(primary) | set(fill))
    merged: Dict[str, Dict[str, float]] = {}
    prev: Optional[float] = None
    for day in days:
        src = primary.get(day) or fill.get(day)
        if not src:
            continue
        cc = float(src["c"])
        ret = None if prev is None else (cc / prev - 1.0) * 100.0
        merged[day] = {
            "o": float(src.get("o") or cc),
            "h": float(src.get("h") or cc),
            "l": float(src.get("l") or cc),
            "c": cc,
            "ret": float(ret) if ret is not None else 0.0,
            "ret_ok": ret is not None,
            "src": "mkt" if day in primary else "lab",
        }
        prev = cc
    return merged


def _prior_us_day(us_days: List[str], tw_day: str) -> Optional[str]:
    tw = _ymd(tw_day)
    cands = [d for d in us_days if d < tw]
    return cands[-1] if cands else None


def _load_oral_levels_by_day(db_path: str) -> Dict[str, List[float]]:
    """每個有文的日 → 口述大盤點位（材料庫）。"""
    try:
        from biaoke_walk import extract_index_levels
    except Exception:
        return {}
    path = str(db_path or "").strip()
    if not path or not Path(path).is_file():
        return {}
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), text
            FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
              AND IFNULL(text,'') != ''
              AND REPLACE(CAST(date AS TEXT),'-','') >= ?
            ORDER BY 1
            """,
            (SINCE_DEFAULT,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    by_day: Dict[str, List[float]] = defaultdict(list)
    for d, text in rows:
        day = _ymd(d)
        if not day:
            continue
        for hit in extract_index_levels(str(text or "")):
            lv = _f(hit.get("level"))
            if lv and lv >= 15000:
                by_day[day].append(float(lv))
    # unique round
    out: Dict[str, List[float]] = {}
    for day, lvls in by_day.items():
        seen = set()
        uniq = []
        for x in lvls:
            k = round(x, 1)
            if k in seen:
                continue
            seen.add(k)
            uniq.append(float(x))
        out[day] = uniq
    return out


def _active_levels(
    by_day: Dict[str, List[float]], day: str, post_days: List[str]
) -> List[float]:
    """取 day 當日（含）往前近窗有口述的位階。"""
    cands = [d for d in post_days if d <= day]
    if not cands:
        return []
    window = cands[-LEVEL_LOOKBACK_POSTS:]
    seen = set()
    out: List[float] = []
    for d in window:
        for lv in by_day.get(d) or []:
            k = round(lv, 1)
            if k in seen:
                continue
            seen.add(k)
            out.append(lv)
    return out


def _level_state(bar: Dict[str, float], levels: List[float]) -> Dict[str, Any]:
    """觸／守／破：只對加權柱 vs 口述位（不准發明新價）。"""
    if not levels:
        return {"n_levels": 0, "touch": False, "hold": False, "break": False}
    hi = float(bar["h"])
    lo = float(bar["l"])
    cl = float(bar["c"])
    touch = hold = brk = False
    nearest = None
    nearest_dist = None
    for lv in levels:
        if lv <= 0:
            continue
        tol = lv * LEVEL_TOL
        dist = min(abs(hi - lv), abs(lo - lv), abs(cl - lv))
        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest = lv
        if lo - tol <= lv <= hi + tol:
            touch = True
            if cl >= lv - tol:
                hold = True
            if cl < lv - tol:
                brk = True
    return {
        "n_levels": len(levels),
        "nearest": nearest,
        "touch": touch,
        "hold": hold,
        "break": brk,
    }


def build_daily_panel(
    db_path: str = "",
    *,
    since_ymd: str = SINCE_DEFAULT,
    lab_db: Optional[Path] = None,
) -> Dict[str, Any]:
    path = str(db_path or "").strip()
    if not path:
        try:
            from config import get_db_path

            path = str(get_db_path() or "")
        except Exception:
            path = str(ROOT / "data" / "wayne_market.db")
    p = Path(path)
    if not p.is_file() and not p.is_absolute():
        p = ROOT / path
        path = str(p)
    if not path or not Path(path).is_file():
        return {"ok": False, "reason": "no_db", "rows": []}

    lab_path = Path(lab_db) if lab_db else ROOT / "data" / "decade_lab.db"
    conn = sqlite3.connect(path, timeout=60.0)
    try:
        twii = _load_index(conn, "TWII")
        sox = _load_index(conn, "SOX")
        tsm_adr = _load_index(conn, "TSM")
        tsmc_mkt = _load_stock(conn, "2330")
        te_n = _load_fut(conn, "TE", "night")
        te_r = _load_fut(conn, "TE", "regular")
        tx_n = _load_fut(conn, "TX", "night")
    finally:
        conn.close()

    tsmc = _merge_bars(tsmc_mkt, _load_2330_lab(lab_path))
    since = _ymd(since_ymd) or SINCE_DEFAULT
    tw_days = [d for d in sorted(twii.keys()) if d >= since]
    us_days = sorted(set(sox.keys()) | set(tsm_adr.keys()))
    oral_by = _load_oral_levels_by_day(path)
    oral_days = sorted(oral_by.keys())

    rows: List[Dict[str, Any]] = []
    for day in tw_days:
        tw = twii.get(day)
        if not tw or not tw.get("ret_ok"):
            continue
        u = _prior_us_day(us_days, day)
        sx = sox.get(u) if u else None
        adr = tsm_adr.get(u) if u else None
        t2330 = tsmc.get(day)
        ten = te_n.get(day)
        ter = te_r.get(day)
        txn = tx_n.get(day)

        sx_ret = float(sx["ret"]) if sx and sx.get("ret_ok") else None
        adr_ret = float(adr["ret"]) if adr and adr.get("ret_ok") else None
        t_ret = float(t2330["ret"]) if t2330 and t2330.get("ret_ok") else None
        tw_ret = float(tw["ret"])
        te_n_ret = float(ten["ret"]) if ten and ten.get("ret_ok") else None
        te_r_ret = float(ter["ret"]) if ter and ter.get("ret_ok") else None
        tx_n_ret = float(txn["ret"]) if txn and txn.get("ret_ok") else None

        levels = _active_levels(oral_by, day, oral_days)
        lv_st = _level_state(tw, levels)

        rows.append(
            {
                "tw_day": day,
                "year": _year(day),
                "us_day": u,
                "sides": {
                    "sox": _side(sx_ret),
                    "tsm_adr": _side(adr_ret),
                    "2330": _side(t_ret),
                    "twii": _side(tw_ret),
                    "te_night": _side(te_n_ret),
                    "te_day": _side(te_r_ret),
                    "tx_night": _side(tx_n_ret),
                },
                "rets": {
                    "sox": sx_ret,
                    "tsm_adr": adr_ret,
                    "2330": t_ret,
                    "twii": tw_ret,
                    "te_night": te_n_ret,
                    "te_day": te_r_ret,
                    "tx_night": tx_n_ret,
                },
                "level": lv_st,
                "src_2330": (t2330 or {}).get("src"),
            }
        )

    coverage = {
        "since": since,
        "n_tw_days": len(rows),
        "n_sox": sum(1 for r in rows if r["rets"]["sox"] is not None),
        "n_2330": sum(1 for r in rows if r["rets"]["2330"] is not None),
        "n_te_night": sum(1 for r in rows if r["rets"]["te_night"] is not None),
        "n_tx_night": sum(1 for r in rows if r["rets"]["tx_night"] is not None),
        "n_level_touch": sum(1 for r in rows if r["level"].get("touch")),
        "te_night_span": (
            min((r["tw_day"] for r in rows if r["rets"]["te_night"] is not None), default="")
            ,
            max((r["tw_day"] for r in rows if r["rets"]["te_night"] is not None), default=""),
        ),
        "coverage_gap_zh": [
            "TE night／day 本地庫約自 20260707 起，2023–2026H1 電子夜盤鏈樣本不足，該軌只標候選不硬推。",
            "TX night 約自 20240301；更早用 SOX↔2330↔TWII 主鏈。",
            "TSM ADR 近窗可能滯後；缺日不算。",
        ],
    }
    return {"ok": True, "db": path, "rows": rows, "coverage": coverage}


# ---------- 假設網：條件 → 結果；對基線算 lift ----------

Pred = Callable[[Dict[str, Any]], Optional[bool]]


def _agree(a: str, b: str) -> Optional[bool]:
    if a == "na" or b == "na":
        return None
    if a in ("up", "down") and b in ("up", "down"):
        return a == b
    return None


def _hypotheses() -> List[Dict[str, Any]]:
    """系統化假設清單：聯動一致、領先、位階交叉。"""

    def sox_ok(r):
        return r["rets"]["sox"] is not None

    def t_ok(r):
        return r["rets"]["2330"] is not None

    def te_ok(r):
        return r["rets"]["te_night"] is not None

    def tx_ok(r):
        return r["rets"]["tx_night"] is not None

    def tw_not_down(r):
        return r["sides"]["twii"] in ("up", "hold", "soft")

    def tw_up(r):
        return r["sides"]["twii"] == "up"

    def t_not_down(r):
        return r["sides"]["2330"] in ("up", "hold", "soft")

    def t_up(r):
        return r["sides"]["2330"] == "up"

    def lv_touch(r):
        return bool(r["level"].get("touch"))

    def lv_hold(r):
        return bool(r["level"].get("hold"))

    def lv_break(r):
        return bool(r["level"].get("break"))

    hyps: List[Dict[str, Any]] = [
        {
            "id": "agree_sox_2330",
            "family": "co_move",
            "zh": "費半已收方向＝次日2330方向（上下）",
            "cond": lambda r: sox_ok(r) and t_ok(r) and r["sides"]["sox"] in ("up", "down") and r["sides"]["2330"] in ("up", "down"),
            "pred": lambda r: r["sides"]["sox"] == r["sides"]["2330"],
            "base_pred": lambda r: True,  # will use unconditional rate of pred among cond-universe differently
        },
        {
            "id": "agree_sox_twii",
            "family": "co_move",
            "zh": "費半已收方向＝次日加權方向（上下）",
            "cond": lambda r: sox_ok(r) and r["sides"]["sox"] in ("up", "down") and r["sides"]["twii"] in ("up", "down"),
            "pred": lambda r: r["sides"]["sox"] == r["sides"]["twii"],
        },
        {
            "id": "agree_2330_twii",
            "family": "co_move",
            "zh": "2330方向＝加權方向（上下）",
            "cond": lambda r: t_ok(r) and r["sides"]["2330"] in ("up", "down") and r["sides"]["twii"] in ("up", "down"),
            "pred": lambda r: r["sides"]["2330"] == r["sides"]["twii"],
        },
        {
            "id": "agree_adr_2330",
            "family": "co_move",
            "zh": "台積ADR已收方向＝次日2330方向",
            "cond": lambda r: r["rets"]["tsm_adr"] is not None and t_ok(r) and r["sides"]["tsm_adr"] in ("up", "down") and r["sides"]["2330"] in ("up", "down"),
            "pred": lambda r: r["sides"]["tsm_adr"] == r["sides"]["2330"],
        },
        {
            "id": "agree_te_night_twii",
            "family": "co_move",
            "zh": "電子夜盤方向＝當日加權方向",
            "cond": lambda r: te_ok(r) and r["sides"]["te_night"] in ("up", "down") and r["sides"]["twii"] in ("up", "down"),
            "pred": lambda r: r["sides"]["te_night"] == r["sides"]["twii"],
        },
        {
            "id": "agree_tx_night_twii",
            "family": "co_move",
            "zh": "台指夜盤方向＝當日加權方向",
            "cond": lambda r: tx_ok(r) and r["sides"]["tx_night"] in ("up", "down") and r["sides"]["twii"] in ("up", "down"),
            "pred": lambda r: r["sides"]["tx_night"] == r["sides"]["twii"],
        },
        {
            "id": "sox_down_tw_not_down",
            "family": "lead_lag",
            "zh": "費半大跌後次日加權未續跌（守／軟／漲）",
            "cond": lambda r: sox_ok(r) and r["sides"]["sox"] == "down",
            "pred": tw_not_down,
        },
        {
            "id": "sox_down_2330_not_down",
            "family": "lead_lag",
            "zh": "費半大跌後次日2330未續跌",
            "cond": lambda r: sox_ok(r) and t_ok(r) and r["sides"]["sox"] == "down",
            "pred": t_not_down,
        },
        {
            "id": "sox_up_tw_up",
            "family": "lead_lag",
            "zh": "費半大漲後次日加權大漲",
            "cond": lambda r: sox_ok(r) and r["sides"]["sox"] == "up",
            "pred": tw_up,
        },
        {
            "id": "sox_up_2330_up",
            "family": "lead_lag",
            "zh": "費半大漲後次日2330大漲",
            "cond": lambda r: sox_ok(r) and t_ok(r) and r["sides"]["sox"] == "up",
            "pred": t_up,
        },
        {
            "id": "sox_up_adr_up_tw_up",
            "family": "lead_lag",
            "zh": "費半＋ADR同漲 → 次日加權大漲",
            "cond": lambda r: sox_ok(r) and r["rets"]["tsm_adr"] is not None and r["sides"]["sox"] == "up" and r["sides"]["tsm_adr"] == "up",
            "pred": tw_up,
        },
        {
            "id": "sox_down_adr_down_tw_down",
            "family": "lead_lag",
            "zh": "費半＋ADR同跌 → 次日加權大跌",
            "cond": lambda r: sox_ok(r) and r["rets"]["tsm_adr"] is not None and r["sides"]["sox"] == "down" and r["sides"]["tsm_adr"] == "down",
            "pred": lambda r: r["sides"]["twii"] == "down",
        },
        {
            "id": "desync_sox_down_2330_hold_tw_hold",
            "family": "desync",
            "zh": "費半跌但2330守住 → 加權亦守",
            "cond": lambda r: sox_ok(r) and t_ok(r) and r["sides"]["sox"] == "down" and r["sides"]["2330"] in ("up", "hold"),
            "pred": tw_not_down,
        },
        {
            "id": "te_night_down_tw_not_down",
            "family": "lead_lag",
            "zh": "電子夜盤大跌後當日加權未續跌",
            "cond": lambda r: te_ok(r) and r["sides"]["te_night"] == "down",
            "pred": tw_not_down,
        },
        {
            "id": "te_night_up_tw_up",
            "family": "lead_lag",
            "zh": "電子夜盤大漲 → 當日加權大漲",
            "cond": lambda r: te_ok(r) and r["sides"]["te_night"] == "up",
            "pred": tw_up,
        },
        {
            "id": "tx_night_up_tw_up",
            "family": "lead_lag",
            "zh": "台指夜盤大漲 → 當日加權大漲",
            "cond": lambda r: tx_ok(r) and r["sides"]["tx_night"] == "up",
            "pred": tw_up,
        },
        {
            "id": "level_touch_hold_rate",
            "family": "wave_level",
            "zh": "口述位觸碰日：收盤守住",
            "cond": lv_touch,
            "pred": lv_hold,
        },
        {
            "id": "level_touch_sox_up_hold",
            "family": "wave_x_link",
            "zh": "觸位＋前夜費半漲 → 守住",
            "cond": lambda r: lv_touch(r) and sox_ok(r) and r["sides"]["sox"] == "up",
            "pred": lv_hold,
        },
        {
            "id": "level_touch_sox_down_break",
            "family": "wave_x_link",
            "zh": "觸位＋前夜費半跌 → 收破",
            "cond": lambda r: lv_touch(r) and sox_ok(r) and r["sides"]["sox"] == "down",
            "pred": lv_break,
        },
        {
            "id": "level_touch_2330_up_hold",
            "family": "wave_x_link",
            "zh": "觸位＋2330漲 → 守住",
            "cond": lambda r: lv_touch(r) and t_ok(r) and r["sides"]["2330"] == "up",
            "pred": lv_hold,
        },
        {
            "id": "level_touch_2330_down_break",
            "family": "wave_x_link",
            "zh": "觸位＋2330跌 → 收破",
            "cond": lambda r: lv_touch(r) and t_ok(r) and r["sides"]["2330"] == "down",
            "pred": lv_break,
        },
        {
            "id": "level_touch_tx_night_up_hold",
            "family": "wave_x_link",
            "zh": "觸位＋台指夜漲 → 守住",
            "cond": lambda r: lv_touch(r) and tx_ok(r) and r["sides"]["tx_night"] == "up",
            "pred": lv_hold,
        },
        {
            "id": "level_touch_te_night_up_hold",
            "family": "wave_x_link",
            "zh": "觸位＋電子夜漲 → 守住",
            "cond": lambda r: lv_touch(r) and te_ok(r) and r["sides"]["te_night"] == "up",
            "pred": lv_hold,
        },
        {
            "id": "level_touch_sox_down_tw_not_down",
            "family": "wave_x_link",
            "zh": "觸位日且費半跌：加權當日未續跌",
            "cond": lambda r: lv_touch(r) and sox_ok(r) and r["sides"]["sox"] == "down",
            "pred": tw_not_down,
        },
    ]
    return hyps


def _eval_hyp(
    rows: List[Dict[str, Any]], hyp: Dict[str, Any]
) -> Dict[str, Any]:
    cond_f: Pred = hyp["cond"]
    pred_f: Pred = hyp["pred"]
    universe = []
    hits = []
    by_year: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "hit": 0})
    for r in rows:
        try:
            on = cond_f(r)
        except Exception:
            on = False
        if not on:
            continue
        universe.append(r)
        try:
            ok = bool(pred_f(r))
        except Exception:
            ok = False
        if ok:
            hits.append(r)
        y = r.get("year") or ""
        by_year[y]["n"] += 1
        if ok:
            by_year[y]["hit"] += 1

    n = len(universe)
    h = len(hits)
    rate = (h / n) if n else None

    # 基線：同一 pred 在「可評估母體」上的無條件率
    # 對 co_move：母體＝cond 已定義的方向日；基線用 0.5（兩向隨機）
    # 對其他：母體＝所有具備 pred 所需欄位的日子
    family = hyp.get("family")
    if family == "co_move":
        base_rate = 0.5
        base_n = n
    else:
        base_u = []
        base_h = 0
        # 放寬：所有有 TWII 的日測同一 pred（若 pred 需觸位則只在觸位母體）
        for r in rows:
            try:
                # 若 cond 本質需要 touch，基線也限 touch 日
                if family in ("wave_level", "wave_x_link"):
                    if not r["level"].get("touch"):
                        continue
                ok = bool(pred_f(r))
            except Exception:
                continue
            base_u.append(r)
            if ok:
                base_h += 1
        base_n = len(base_u)
        base_rate = (base_h / base_n) if base_n else None

    lift = None
    if rate is not None and base_rate is not None and base_rate > 0:
        lift = rate / base_rate - 1.0

    year_rows = []
    year_pos = 0
    year_ok_n = 0
    for y in sorted(by_year.keys()):
        st = by_year[y]
        yr = (st["hit"] / st["n"]) if st["n"] else None
        ylift = None
        if yr is not None and base_rate and base_rate > 0:
            ylift = yr / base_rate - 1.0
        if st["n"] >= 8:
            year_ok_n += 1
            if ylift is not None and ylift > 0:
                year_pos += 1
        year_rows.append(
            {
                "year": y,
                "n": st["n"],
                "hit": st["hit"],
                "rate": round(yr, 4) if yr is not None else None,
                "lift": round(ylift, 4) if ylift is not None else None,
            }
        )

    # dig_worth：n≥20、|lift|≥0.08、至少兩年 n≥8 且 lift 同向為正（或強負也值得挖）
    abs_lift = abs(lift) if lift is not None else 0.0
    year_consistent = year_ok_n >= 2 and year_pos >= max(2, math.ceil(year_ok_n * 0.6))
    # 負 lift 也算「值得挖」（反向關係）— 用 year_pos 對正；負向另計
    year_neg = 0
    for yr in year_rows:
        if (yr.get("n") or 0) >= 8 and (yr.get("lift") or 0) < 0:
            year_neg += 1
    if lift is not None and lift < -0.08:
        year_consistent = year_ok_n >= 2 and year_neg >= max(2, math.ceil(year_ok_n * 0.6))

    dig = bool(
        n >= MIN_N
        and lift is not None
        and abs_lift >= 0.08
        and (year_consistent or (n >= 80 and abs_lift >= 0.15))
    )
    score = 0.0
    if n and lift is not None:
        score = float(n) * abs_lift * (1.2 if year_consistent else 1.0)

    return {
        "id": hyp["id"],
        "family": family,
        "zh": hyp["zh"],
        "n": n,
        "hit": h,
        "rate": round(rate, 4) if rate is not None else None,
        "base_n": base_n,
        "base_rate": round(base_rate, 4) if base_rate is not None else None,
        "lift": round(lift, 4) if lift is not None else None,
        "by_year": year_rows,
        "year_consistent": year_consistent,
        "dig_worth": dig,
        "score": round(score, 3),
        "buy_signal": False,
        "phone_sync": PHONE_SYNC,
    }


def mine_relations(panel: Dict[str, Any]) -> Dict[str, Any]:
    rows = list(panel.get("rows") or [])
    results = [_eval_hyp(rows, h) for h in _hypotheses()]
    results.sort(key=lambda x: (-(x.get("score") or 0), -(x.get("n") or 0)))
    dig = [r for r in results if r.get("dig_worth")]
    by_fam: Dict[str, int] = defaultdict(int)
    for r in dig:
        by_fam[str(r.get("family"))] += 1
    return {
        "n_hypotheses": len(results),
        "n_dig_worth": len(dig),
        "dig_by_family": dict(by_fam),
        "dig_worth": dig[:20],
        "all_ranked": results,
        "note_zh": (
            "dig_worth＝n≥20 且 |lift|≥0.08，並跨年同向或大樣本強 lift；"
            "只當加深候選，不是買訊，未過閘不上話筒。"
        ),
    }


def _hint_for_dig(d: Dict[str, Any]) -> Dict[str, Any]:
    hid = str(d.get("id") or "")
    lift = d.get("lift")
    lift_f = float(lift) if lift is not None else 0.0
    meta = (
        f"(n={d.get('n')} rate={d.get('rate')} lift={d.get('lift')})"
    )
    if hid in (
        "level_touch_sox_up_hold",
        "level_touch_2330_up_hold",
        "level_touch_tx_night_up_hold",
        "level_touch_te_night_up_hold",
    ):
        return {
            "next_track": "pref_confirm_link_v1",
            "from_hyp": hid,
            "zh": f"位階觸碰日用聯動確認守勢：{d.get('zh')} {meta}；收樣對質，未過閘不准改 preferred 現況。",
        }
    if hid in ("level_touch_sox_down_break", "level_touch_2330_down_break") or (
        "level_touch" in hid and lift_f < -0.08 and "not_down" in hid
    ):
        return {
            "next_track": "pref_fail_link_v1",
            "from_hyp": hid,
            "zh": f"位階觸碰＋聯動偏空作失效加權：{d.get('zh')} {meta}；對質三態失效邊，未過閘不換。",
        }
    if hid.startswith("agree_"):
        return {
            "next_track": "path_weight_co_move_v1",
            "from_hyp": hid,
            "zh": f"共向聯動加權路徑可信度：{d.get('zh')} {meta}。",
        }
    if "desync" in hid:
        return {
            "next_track": "desync_hold_filter_v1",
            "from_hyp": hid,
            "zh": f"背離守勢過濾假跌破：{d.get('zh')} {meta}。",
        }
    if hid.startswith("sox_up") or hid.startswith("sox_down_adr"):
        return {
            "next_track": "us_lead_tw_path_v1",
            "from_hyp": hid,
            "zh": f"美股先行加權路徑：{d.get('zh')} {meta}。",
        }
    if hid.startswith("tx_night") or hid.startswith("te_night"):
        return {
            "next_track": "night_session_confirm_v1",
            "from_hyp": hid,
            "zh": f"夜盤確認鏈：{d.get('zh')} {meta}。",
        }
    return {
        "next_track": "cross_link_generic_v1",
        "from_hyp": hid,
        "zh": f"{d.get('zh')} {meta}",
    }


def _wave_strengthen_hints(dig: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把值得挖的關係轉成波浪加深下一軌提示（仍 blocked）。

    優先保留 wave_x_link／desync 家族，再補共向／美股先行，避免被高分共向擠掉。
    """
    priority = []
    rest = []
    for d in dig:
        fam = str(d.get("family") or "")
        if fam in ("wave_x_link", "wave_level", "desync"):
            priority.append(d)
        else:
            rest.append(d)
    ordered = priority + rest
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for d in ordered:
        h = _hint_for_dig(d)
        k = h["next_track"]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
        if len(uniq) >= 8:
            break
    return uniq


def run_suite(
    db_path: str = "",
    *,
    since_ymd: str = SINCE_DEFAULT,
    write_daily: bool = True,
) -> Dict[str, Any]:
    panel = build_daily_panel(db_path, since_ymd=since_ymd)
    if not panel.get("ok"):
        return {
            "ok": False,
            "reason": panel.get("reason"),
            "phone_sync": PHONE_SYNC,
            "buy_signal": False,
            "WAVE_NEURONS_MATCH": False,
        }
    mined = mine_relations(panel)
    dig = list(mined.get("dig_worth") or [])
    hints = _wave_strengthen_hints(dig)
    daily_path = None
    if write_daily:
        LAB.mkdir(parents=True, exist_ok=True)
        with gzip.open(OUT_DAILY, "wt", encoding="utf-8") as fh:
            for r in panel["rows"]:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        daily_path = str(OUT_DAILY.relative_to(ROOT))

    # 精簡 all_ranked 進主 JSON（完整仍在 ranked 檔可另存；這裡留 top＋dig）
    payload = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "variant": VARIANT,
        "purpose_zh": (
            "2023起逐日聯動×波浪位階系統化假設網量化挖礦；"
            "找出值得加深的關係以強化波浪對質（非買訊）"
        ),
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_warning_fixed": PHONE_WARNING,
        "WAVE_NEURONS_MATCH": False,
        "since": _ymd(since_ymd) or SINCE_DEFAULT,
        "coverage": panel.get("coverage"),
        "daily_jsonl_gz": daily_path,
        "gate": {
            "min_n": MIN_N,
            "n_tw_days": (panel.get("coverage") or {}).get("n_tw_days"),
            "n_dig_worth": mined.get("n_dig_worth"),
            "gate_n20": ((panel.get("coverage") or {}).get("n_sox") or 0) >= MIN_N,
            "replace": False,
            "note_zh": "挖礦候選≠替換閘；波浪現況仍走 pref_3state，未過 n≥20且贏現況不准換。",
        },
        "mine": {
            "n_hypotheses": mined.get("n_hypotheses"),
            "n_dig_worth": mined.get("n_dig_worth"),
            "dig_by_family": mined.get("dig_by_family"),
            "note_zh": mined.get("note_zh"),
            "dig_worth": dig,
            "top_ranked": (mined.get("all_ranked") or [])[:15],
        },
        "wave_strengthen_hints": hints,
        "forbid_zh": [
            "不准當買訊",
            "不准發明未口述價／個股浪號",
            "不准未收當收",
            "phone_sync=blocked",
            "勝率不准混海選／黃金買點",
            "dig_worth 未過閘不准直接改 preferred／話筒",
        ],
    }
    return payload


def write_outputs(payload: Dict[str, Any]) -> Tuple[Path, Path]:
    LAB.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    g = payload.get("gate") or {}
    mine = payload.get("mine") or {}
    cov = payload.get("coverage") or {}
    lines = [
        "# 聯動×位階 系統化量化挖礦（2023起）",
        "",
        f"寫入：`{payload.get('written_at')}`（Asia/Taipei）。",
        f"軌：`{TRACK}`／`{VARIANT}`｜phone_sync=blocked｜非買訊｜WAVE_NEURONS_MATCH=false",
        "",
        f"- since=`{payload.get('since')}` n_tw={cov.get('n_tw_days')} "
        f"sox={cov.get('n_sox')} 2330={cov.get('n_2330')} "
        f"te_night={cov.get('n_te_night')} level_touch={cov.get('n_level_touch')}",
        f"- hypotheses={mine.get('n_hypotheses')} dig_worth={mine.get('n_dig_worth')} "
        f"replace={g.get('replace')}",
        f"- daily=`{payload.get('daily_jsonl_gz')}`",
        "",
        "## 值得再挖（dig_worth）",
        "",
    ]
    for d in mine.get("dig_worth") or []:
        lines.append(
            f"- `{d.get('id')}` [{d.get('family')}] n={d.get('n')} "
            f"rate={d.get('rate')} base={d.get('base_rate')} "
            f"lift={d.get('lift')} score={d.get('score')}｜{d.get('zh')}"
        )
    lines += ["", "## 波浪強化提示（仍 blocked）", ""]
    for h in payload.get("wave_strengthen_hints") or []:
        lines.append(f"- `{h.get('next_track')}` ← `{h.get('from_hyp')}`：{h.get('zh')}")
    lines += [
        "",
        "## 覆蓋缺口",
        "",
    ]
    for z in cov.get("coverage_gap_zh") or []:
        lines.append(f"- {z}")
    lines += ["", "不上話筒定案。未過閘不換現況。", ""]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT_JSON, OUT_MD


def main() -> int:
    payload = run_suite()
    jp, mp = write_outputs(payload)
    g = payload.get("gate") or {}
    mine = payload.get("mine") or {}
    print(
        "GATE",
        f"cross_mine dig={mine.get('n_dig_worth')}/{mine.get('n_hypotheses')} "
        f"n_tw={g.get('n_tw_days')} gate_n20={g.get('gate_n20')} "
        f"replace=0 phone_sync=blocked buy_signal=0",
    )
    for d in (mine.get("dig_worth") or [])[:5]:
        print(
            "DIG",
            d.get("id"),
            f"n={d.get('n')}",
            f"rate={d.get('rate')}",
            f"lift={d.get('lift')}",
            f"score={d.get('score')}",
        )
    print("WROTE", jp.name, mp.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
