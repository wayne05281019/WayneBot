#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大盤走勢預測（靜默）｜從投資人要的結果反推。

目標（使用者鎖）：預判大盤漲勢（方向）及幅度。

投資人要的最終答案：
1. 這一段往哪（up／down／range）
2. 預估幅度 amp_pct（%）、目標價與失效價
3. 依據哪些因素（可覆盤歸因；幅度錯了也要能檢討）

因素與切法＝本模組責任（不准丟回使用者決定）。
缺就標缺；只落數字 json／gz；不准存圖；不是買訊；不准進話筒。
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
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

# 投資人產出欄（責任切面）
INVESTOR_OUTPUT = (
    "bias",  # up|down|range
    "amp_pct",  # 預估幅度％（漲勢為正、跌勢為負）
    "amp_class",  # micro|small|mid|large
    "horizon",  # session(1d)|segment(3d)
    "last_close",
    "target",
    "invalidate",
    "factors",  # 當下鎖進的因素快照
    "missing",  # 缺什麼 → 覆盤時知道資訊不完整
    "why_codes",  # 點亮的可沿用旗標／結構碼
)

# 我負責納入的因素包（正反：預測要準＋錯了能歸因）
FACTOR_PACK = (
    # A0 波浪主結構（教課書八循環；飆大軌另對質）
    "wave_bias",
    "wave_phase",
    "wave_ok",
    # A 結構
    "twii_ret",
    "twii_wick",
    "twii_vol_spike",
    "twii_prev_ret",
    # B 美股領導
    "ixic_prior_ret",
    "sox_prior_ret",
    "vix_prior_ret",
    # C 權值／半導體代理
    "tsm_prior_ret",
    "nvda_prior_ret",
    # D 外圍風險
    "dxy_prior_ret",
    "usdtwd_prior_ret",
    "brent_prior_ret",
    # E 期貨夜盤（有才納；缺標缺）
    "tx_night_ret",
    # F 法人＝外資＋投信＋自營（TWSE BFI82U 市場級；不准假成本）
    "inst_trust_yi",
    "inst_foreign_yi",
    "inst_three_yi",
    "inst_trust_z",
    "inst_foreign_z",
    "inst_three_z",
    "inst_trust_neg_2d",
    "inst_three_neg_2d",
    "inst_foreign_neg_2d",
    "inst_foreign_pos_2d",
    "inst_foreign_pos_3d",
    "inst_foreign_yi_p80",
    "inst_foreign_yi_p85",
    "inst_foreign_yi_p90",
    "inst_2330_foreign_net",
    "inst_2330_foreign_ge_3k",
    # G 多週期量價（季／年線＋爆巨量；飆大圖文參考）
    "mtf_dist_ath_pct",
    "mtf_amount_pctile_60",
    "mtf_volume_climax",
    "mtf_qtd_range_pct",
    "mtf_named_support_broken",
    # H 黃金切割（回撤 0.382／0.5／0.618／0.75／0.786＋延伸）
    "fib_near_0618_support",
    "fib_near_0382_support",
    "fib_near_0618_resist",
    "fib_deep_pull",
    "fib_amp_0618_pct",
    # I 籌碼多面向（融資／廣度／成交值／TX OI／融券；法人另見 F）
    "chips_margin_delta_z",
    "chips_ud_ratio",
    "chips_tape_tril",
    "chips_tx_oi_z",
    "chips_short_z",
)

# 可沿用旗標權重：用 reusable_quant 的 edge 符號當票（正 edge→偏多票）
# 這裡內建已量化過關的碼；檔案更新時可覆寫
DEFAULT_EDGE_VOTES: Dict[str, float] = {
    "us_up_tw_down": 0.57,
    "us_risk_off_tw_green": 0.45,
    "us_down_tw_hold": 0.36,
    "tw_vol_spike": 0.41,
    "after_tw_down2_with_wick": 0.90,
    "after_tw_down2_us_up": 0.56,
    "after_tw_down2_vol_spike": 0.49,
    "tw_crash_3pct": 0.31,
    "dxy_up_tw_down": -0.64,
    "brent_up_tw_down": -0.40,
    "fx_up_tw_down": -0.77,
}

DDL = """
CREATE TABLE IF NOT EXISTS path_forecast (
    as_of TEXT NOT NULL,
    horizon TEXT NOT NULL,
    bias TEXT NOT NULL,
    last_close REAL,
    target REAL,
    invalidate REAL,
    factors_json TEXT NOT NULL DEFAULT '{}',
    missing_json TEXT NOT NULL DEFAULT '[]',
    why_json TEXT NOT NULL DEFAULT '[]',
    score REAL,
    verdict TEXT NOT NULL DEFAULT '',
    check_close REAL,
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    amp_pct REAL,
    amp_class TEXT NOT NULL DEFAULT '',
    amp_verdict TEXT NOT NULL DEFAULT '',
    actual_ret_pct REAL,
    PRIMARY KEY (as_of, horizon)
);
"""


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


def _load_sym(conn: sqlite3.Connection, symbol: str) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume, pct_change
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, o, h, l, c, vol, pct in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = _f(pct)
        if ret is None and prev and prev > 0:
            ret = (cc / prev - 1.0) * 100.0
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(l) or cc,
            "close": cc,
            "volume": _f(vol) or 0.0,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _load_tx_night(conn: sqlite3.Connection) -> Dict[str, float]:
    out: Dict[str, float] = {}
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), pct_change, close
            FROM futures_daily WHERE symbol='TX' AND session='night' ORDER BY 1
            """
        ).fetchall()
    except sqlite3.Error:
        return out
    prev = None
    for d, pct, c in rows:
        day = _ymd(d)
        if not day:
            continue
        r = _f(pct)
        if r is None and prev and _f(c) and prev > 0:
            r = (float(c) / prev - 1.0) * 100.0
        if r is not None:
            out[day] = r
        if _f(c):
            prev = float(c)
    return out


def _prior(us_days: Sequence[str], tw: str) -> Optional[str]:
    prev = None
    for d in us_days:
        if d < tw:
            prev = d
        else:
            break
    return prev


def _wick(bar: Dict[str, float]) -> float:
    span = bar["high"] - bar["low"]
    if span <= 0:
        return 0.0
    return (min(bar["open"], bar["close"]) - bar["low"]) / span


def _load_edge_votes() -> Dict[str, float]:
    path = OUT_DIR / "reusable_quant_latest.json"
    votes = dict(DEFAULT_EDGE_VOTES)
    if path.is_file():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blob = {}
        for r in blob.get("reusable") or blob.get("flags") or []:
            flag = str(r.get("flag") or r.get("code") or r.get("id") or "")
            edge = _f(r.get("edge3") or r.get("vote"))
            n = int(r.get("n") or 0)
            if flag and edge is not None and n >= 20:
                votes[flag] = float(edge)
    # 法人／投信模組：過閘旗標必併入（使用者鎖：一定要用）
    try:
        from scripts.decade_lab_inst_module import load_inst_votes

        for k, v in load_inst_votes().items():
            votes[k] = float(v)
    except Exception:
        pass
    # 多週期爆巨量／距高（飆大季年線參考，過閘才進）
    try:
        from scripts.decade_lab_mtf_volume import load_mtf_votes

        for k, v in load_mtf_votes().items():
            votes[k] = float(v)
    except Exception:
        pass
    # 黃金切割完整位（過閘才進）
    try:
        from scripts.decade_lab_fib_module import load_fib_votes

        for k, v in load_fib_votes().items():
            votes[k] = float(v)
    except Exception:
        pass
    # 籌碼多面向（融資／廣度／量能／OI／融券；過閘才進）
    try:
        from scripts.decade_lab_chips_module import load_chips_votes

        for k, v in load_chips_votes().items():
            votes[k] = float(v)
    except Exception:
        pass
    # 宏觀／ADR／跳空／基差／背離加測包（過閘才進；波浪主判外確認）
    try:
        from scripts.decade_lab_path_extras import load_extras_votes

        for k, v in load_extras_votes().items():
            votes[k] = float(v)
    except Exception:
        pass
    return votes


def snapshot_factors(
    *,
    twii: Dict[str, Dict[str, float]],
    ixic: Dict[str, Dict[str, float]],
    sox: Dict[str, Dict[str, float]],
    vix: Dict[str, Dict[str, float]],
    tsm: Dict[str, Dict[str, float]],
    nvda: Dict[str, Dict[str, float]],
    dxy: Dict[str, Dict[str, float]],
    usdtwd: Dict[str, Dict[str, float]],
    brent: Dict[str, Dict[str, float]],
    tx_night: Dict[str, float],
    tw_days: Sequence[str],
    as_of: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """只准用 as_of 當日（含）以前的資訊。"""
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    if day not in twii or not twii[day].get("ret_ok"):
        return {}, ["twii_bar"]
    i = list(tw_days).index(day)
    bar = twii[day]
    factors["twii_ret"] = bar["ret"]
    factors["twii_wick"] = _wick(bar)
    # vol spike vs prior 20
    vols = [twii[tw_days[j]]["volume"] for j in range(max(0, i - 20), i) if twii[tw_days[j]]["volume"] > 0]
    ma = (sum(vols) / len(vols)) if vols else 0.0
    factors["twii_vol_spike"] = bool(ma > 0 and bar["volume"] >= 1.5 * ma)
    if i >= 1 and twii[tw_days[i - 1]].get("ret_ok"):
        factors["twii_prev_ret"] = twii[tw_days[i - 1]]["ret"]
    else:
        missing.append("twii_prev_ret")

    us_days = sorted(ixic.keys())
    u = _prior(us_days, day)
    if not u:
        missing.extend(
            [
                "ixic_prior_ret",
                "sox_prior_ret",
                "vix_prior_ret",
                "tsm_prior_ret",
                "nvda_prior_ret",
                "dxy_prior_ret",
                "usdtwd_prior_ret",
                "brent_prior_ret",
            ]
        )
    else:
        factors["us_as_of"] = u

        def take(name: str, m: Dict[str, Dict[str, float]]) -> None:
            b = m.get(u)
            if b and b.get("ret_ok"):
                factors[name] = b["ret"]
            else:
                missing.append(name)

        take("ixic_prior_ret", ixic)
        take("sox_prior_ret", sox)
        take("vix_prior_ret", vix)
        take("tsm_prior_ret", tsm)
        take("nvda_prior_ret", nvda)
        take("dxy_prior_ret", dxy)
        take("usdtwd_prior_ret", usdtwd)
        take("brent_prior_ret", brent)

    # TX night：同日或前一日
    if day in tx_night:
        factors["tx_night_ret"] = tx_night[day]
    elif u and u in tx_night:
        factors["tx_night_ret"] = tx_night[u]
    else:
        missing.append("tx_night_ret")

    return factors, missing


def _lit_why(factors: Dict[str, Any], votes: Dict[str, float]) -> List[Dict[str, Any]]:
    tw = _f(factors.get("twii_ret")) or 0.0
    ix = _f(factors.get("ixic_prior_ret"))
    dx = _f(factors.get("dxy_prior_ret"))
    br = _f(factors.get("brent_prior_ret"))
    fx = _f(factors.get("usdtwd_prior_ret"))
    wick = _f(factors.get("twii_wick")) or 0.0
    vol_spike = bool(factors.get("twii_vol_spike"))
    lit = []

    def add(code: str, ok: bool) -> None:
        if not ok or code not in votes:
            return
        lit.append({"code": code, "edge": votes[code]})

    if ix is not None:
        add("us_up_tw_down", ix >= 1.0 and tw <= -0.8)
        add("us_down_tw_hold", ix <= -1.5 and tw >= -0.55)
        add("us_risk_off_tw_green", ix <= -1.5 and tw > 0.2)
        add("after_tw_down2_us_up", tw <= -2.0 and ix >= 0.5)
    add("tw_vol_spike", vol_spike)
    add("after_tw_down2_with_wick", tw <= -2.0 and wick >= 0.45)
    add("after_tw_down2_vol_spike", tw <= -2.0 and vol_spike)
    add("tw_crash_3pct", tw <= -3.0)
    if dx is not None:
        add("dxy_up_tw_down", dx >= 0.6 and tw <= -0.8)
    if br is not None:
        add("brent_up_tw_down", br >= 2.0 and tw <= -0.8)
    if fx is not None:
        add("fx_up_tw_down", fx >= 0.4 and tw <= -0.8)
    # 法人＝外資＋投信＋自營（市場級 BFI；z／分位／連買賣／2330外資）
    tz = _f(factors.get("inst_trust_z"))
    fz = _f(factors.get("inst_foreign_z"))
    z3 = _f(factors.get("inst_three_z"))
    if tz is not None:
        add("inst_trust_z_le_m1", tz <= -1.0)
        add("inst_trust_z_ge_p1", tz >= 1.0)
    if fz is not None:
        add("inst_foreign_z_ge_p1", fz >= 1.0)
        add("inst_foreign_z_le_m1", fz <= -1.0)
    if z3 is not None:
        add("inst_three_z_le_m1", z3 <= -1.0)
        add("inst_three_z_ge_p1", z3 >= 1.0)
    add("inst_trust_neg_2d", bool(factors.get("inst_trust_neg_2d")))
    add("inst_three_neg_2d", bool(factors.get("inst_three_neg_2d")))
    add("inst_foreign_neg_2d", bool(factors.get("inst_foreign_neg_2d")))
    add("inst_foreign_pos_2d", bool(factors.get("inst_foreign_pos_2d")))
    add("inst_foreign_pos_3d", bool(factors.get("inst_foreign_pos_3d")))
    # 外資分位只點最強一檔，避免 p80/p85/p90 同日重複灌票
    if factors.get("inst_foreign_yi_p90"):
        add("inst_foreign_yi_p90", True)
    elif factors.get("inst_foreign_yi_p85"):
        add("inst_foreign_yi_p85", True)
    elif factors.get("inst_foreign_yi_p80"):
        add("inst_foreign_yi_p80", True)
    elif factors.get("inst_foreign_yi_p10"):
        add("inst_foreign_yi_p10", True)
    elif factors.get("inst_foreign_yi_p15"):
        add("inst_foreign_yi_p15", True)
    # 2330 外資：大買與大賣反彈互斥，取單邊
    if factors.get("inst_2330_foreign_ge_5k"):
        add("inst_2330_foreign_ge_5k", True)
    elif factors.get("inst_2330_foreign_ge_3k"):
        add("inst_2330_foreign_ge_3k", True)
    elif factors.get("inst_2330_foreign_le_m8k"):
        add("inst_2330_foreign_le_m8k", True)
    # 多週期爆巨量
    add("mtf_volume_climax_d3", bool(factors.get("mtf_volume_climax")))
    add(
        "mtf_climax_near_ath_d3",
        bool(factors.get("mtf_volume_climax"))
        and (_f(factors.get("mtf_dist_ath_pct")) or -99) >= -3.0,
    )
    add(
        "mtf_climax_deep_discount_d3",
        bool(factors.get("mtf_volume_climax"))
        and (_f(factors.get("mtf_dist_ath_pct")) or 0) <= -15.0,
    )
    # 黃金切割：支撐／壓力近位＋深修（互斥取最強一檔支撐）
    if factors.get("fib_near_0618_support"):
        add("fib_near_0618_support", True)
    elif factors.get("fib_near_0500_support"):
        add("fib_near_0500_support", True)
    elif factors.get("fib_near_0382_support"):
        add("fib_near_0382_support", True)
    elif factors.get("fib_near_0750_support"):
        add("fib_near_0750_support", True)
    elif factors.get("fib_near_0786_support"):
        add("fib_near_0786_support", True)
    if factors.get("fib_near_0618_resist"):
        add("fib_near_0618_resist", True)
    elif factors.get("fib_near_0382_resist"):
        add("fib_near_0382_resist", True)
    elif factors.get("fib_near_0750_resist"):
        add("fib_near_0750_resist", True)
    add("fib_deep_pull", bool(factors.get("fib_deep_pull")))
    add("fib_upper_third", bool(factors.get("fib_upper_third")))
    add("fib_lower_third", bool(factors.get("fib_lower_third")))
    add("fib_mid_band", bool(factors.get("fib_mid_band")))
    if factors.get("fib_nearest_is_0.618"):
        add("fib_nearest_is_0.618", True)
    elif factors.get("fib_nearest_is_0.5"):
        add("fib_nearest_is_0.5", True)
    elif factors.get("fib_nearest_is_0.382"):
        add("fib_nearest_is_0.382", True)
    elif factors.get("fib_nearest_is_0.75"):
        add("fib_nearest_is_0.75", True)
    elif factors.get("fib_nearest_is_0.786"):
        add("fib_nearest_is_0.786", True)
    # 切割×籌碼／外資共現
    add("fib_lower_x_margin_kill", bool(factors.get("fib_lower_x_margin_kill")))
    add("fib_0618sup_x_foreign_pos", bool(factors.get("fib_0618sup_x_foreign_pos")))
    add("fib_deep_x_margin_z", bool(factors.get("fib_deep_x_margin_z")))
    add("fib_upper_x_limit_up", bool(factors.get("fib_upper_x_limit_up")))
    # 籌碼：融資／廣度／成交值／OI／融券
    add("chips_margin_z_le_m1", bool(factors.get("chips_margin_z_le_m1")))
    add("chips_margin_z_ge_p1", bool(factors.get("chips_margin_z_ge_p1")))
    add("chips_margin_kill_2d", bool(factors.get("chips_margin_kill_2d")))
    add("chips_margin_add_2d", bool(factors.get("chips_margin_add_2d")))
    add("chips_ud_le_0_6", bool(factors.get("chips_ud_le_0_6")))
    add("chips_ud_ge_1_5", bool(factors.get("chips_ud_ge_1_5")))
    if factors.get("chips_limit_down_ge_40"):
        add("chips_limit_down_ge_40", True)
    elif factors.get("chips_limit_down_ge_20"):
        add("chips_limit_down_ge_20", True)
    add("chips_limit_up_ge_20", bool(factors.get("chips_limit_up_ge_20")))
    if factors.get("chips_tape_p90"):
        add("chips_tape_p90", True)
    elif factors.get("chips_tape_p80"):
        add("chips_tape_p80", True)
    elif factors.get("chips_tape_p10"):
        add("chips_tape_p10", True)
    elif factors.get("chips_tape_p20"):
        add("chips_tape_p20", True)
    add("chips_tx_oi_z_ge_p1", bool(factors.get("chips_tx_oi_z_ge_p1")))
    add("chips_tx_oi_z_le_m1", bool(factors.get("chips_tx_oi_z_le_m1")))
    add("chips_tx_oi_drop", bool(factors.get("chips_tx_oi_drop")))
    add("chips_tx_oi_rise", bool(factors.get("chips_tx_oi_rise")))
    add("chips_short_z_ge_p1", bool(factors.get("chips_short_z_ge_p1")))
    add("chips_short_z_le_m1", bool(factors.get("chips_short_z_le_m1")))
    # 加測包：宏觀／跳空／連漲跌／ADR／基差／背離
    add("tw_down_streak_ge3", bool(factors.get("tw_down_streak_ge3")))
    add("tw_up_streak_ge3", bool(factors.get("tw_up_streak_ge3")))
    add("tw_gap_up_ge_0_8", bool(factors.get("tw_gap_up_ge_0_8")))
    add("tw_gap_dn_le_m0_8", bool(factors.get("tw_gap_dn_le_m0_8")))
    add("us10y_up_tw_down", bool(factors.get("us10y_up_tw_down")))
    add("yen_up_tw_down", bool(factors.get("yen_up_tw_down")))
    add("gold_up_risk_off", bool(factors.get("gold_up_risk_off")))
    add("copper_down_risk_off", bool(factors.get("copper_down_risk_off")))
    add("vix_z_ge_p1", bool(factors.get("vix_z_ge_p1")))
    add("vix_z_le_m1", bool(factors.get("vix_z_le_m1")))
    add("us_tw_diverge_2d", bool(factors.get("us_tw_diverge_2d")))
    add("adr_tw_lag", bool(factors.get("adr_tw_lag")))
    add("adr_tw_lead", bool(factors.get("adr_tw_lead")))
    add("tx_contango_ge_0_4", bool(factors.get("tx_contango_ge_0_4")))
    add("tx_backward_le_m0_4", bool(factors.get("tx_backward_le_m0_4")))
    return lit


def decide_path(factors: Dict[str, Any], missing: Sequence[str], votes: Dict[str, float]) -> Dict[str, Any]:
    """產出投資人要的預測列。因素不夠仍給 bias，但標 reviewable=false。

    主判順序（鎖死）：波浪結構 → 再疊法人／籌碼／切割／宏觀確認或否決。
    飆大軌另對質學習；不准雜訊票蓋掉波浪主判。
    """
    last = None
    # last_close must be passed via factors helper — caller fills
    lit = _lit_why(factors, votes)
    score = sum(float(x["edge"]) for x in lit)
    wave_bias = str(factors.get("wave_bias") or "")
    wave_ok = bool(factors.get("wave_ok"))
    # 結構微調：大跌＋下影偏多；美元／油漲＋台跌偏空已在票裡
    if score > 0.35:
        bias = "up"
    elif score < -0.35:
        bias = "down"
    else:
        bias = "range"
    # 波浪主結構：有明確方向時，弱雜訊票不准蓋掉；分數空窗則跟波浪
    if wave_ok and wave_bias in {"up", "down"}:
        lit = list(lit) + [{"code": f"wave_struct_{wave_bias}", "edge": 0.85 if wave_bias == "up" else -0.85}]
        score = sum(float(x["edge"]) for x in lit)
        if abs(score) < 1.10 and bias != wave_bias:
            # 雜訊與波浪打架且不夠強 → 跟波浪
            bias = wave_bias
        elif bias == "range":
            bias = wave_bias
    elif wave_ok and wave_bias == "range" and abs(score) < 0.90:
        # 波浪觀望時，弱票也不硬出方向
        bias = "range"
    # 飆大參考：高檔爆巨量後中期偏橫整——短窗分數不夠強就改觀望（不是自動空）
    near_ath = (_f(factors.get("mtf_dist_ath_pct")) or -99) >= -5.0
    if (
        bool(factors.get("mtf_volume_climax"))
        and near_ath
        and bias in {"up", "down"}
        and abs(score) < 0.90
    ):
        bias = "range"
        lit = list(lit) + [{"code": "mtf_climax_near_ath_soft_range", "edge": 0.0}]
    # 他點名支撐有效跌破 → 橫整假設失效，保留原方向票（可偏空若分數空）
    if bool(factors.get("mtf_named_support_broken")) and score > -0.2:
        score = score - 0.25
        lit = list(lit) + [{"code": "mtf_named_support_broken", "edge": -0.25}]
        if score < -0.35:
            bias = "down"
    # 必要因素：至少有 twii＋ixic，否則不可完整覆盤歸因
    need = {"twii_ret", "ixic_prior_ret"}
    have = set(factors.keys())
    reviewable = need.issubset(have) and len(missing) <= 4
    return {
        "bias": bias,
        "score": round(score, 4),
        "why": lit,
        "reviewable": reviewable,
        "missing": list(missing),
    }


def _amp_class(amp_abs: float) -> str:
    a = abs(float(amp_abs))
    if a < 0.6:
        return "micro"
    if a < 1.5:
        return "small"
    if a < 3.0:
        return "mid"
    return "large"


def estimate_amplitude(
    bias: str,
    score: float,
    factors: Dict[str, Any],
    *,
    realized_abs_ret: Optional[float] = None,
) -> Dict[str, Any]:
    """估幅度％。漲勢為正、跌勢為負；range＝0。

    自修：純票強度 MAE 大；近窗實現波動（日均 |ret| ×√3）準度較高，改為主幹，
    票強度／量能／VIX／夜盤只做微調。
    """
    if bias not in {"up", "down"}:
        return {"amp_pct": 0.0, "amp_class": "micro", "amp_basis": "range_no_amp"}
    strength = abs(float(score or 0.0))
    score_leg = 0.45 + min(2.4, strength * 0.85)
    if realized_abs_ret is not None and realized_abs_ret > 0:
        # 自修對質：純 rv20×√3×1.1 準度最高；混票強度／外加碼反而變差 → 不混
        base = float(realized_abs_ret) * (3.0 ** 0.5) * 1.10
        basis = "rv20_sqrt3"
    else:
        base = score_leg
        basis = "score_fallback"
        if bool(factors.get("twii_vol_spike")):
            base += 0.20
    amp_abs = max(0.40, min(4.0, base))
    amp = amp_abs if bias == "up" else -amp_abs
    return {
        "amp_pct": round(amp, 3),
        "amp_class": _amp_class(amp_abs),
        "amp_basis": basis,
    }


def _targets(
    bias: str,
    last_close: float,
    amp_pct: float = 0.8,
    factors: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float]:
    """目標／失效。有黃金切割位時優先用切割價（0.382／0.618／0.786），否則用幅度％。"""
    if last_close <= 0:
        return last_close, last_close
    f = factors or {}
    # 切割目標：多→反彈側／前高；空→回檔側／前低
    if bias == "up":
        cand = [
            _f(f.get("fib_bounce_0.618")),
            _f(f.get("fib_bounce_0.382")),
            _f(f.get("fib_swing_high")),
        ]
        inv_c = [
            _f(f.get("fib_pull_0.786")),
            _f(f.get("fib_swing_low")),
        ]
        tgt = next((x for x in cand if x is not None and x > last_close), None)
        inv = next((x for x in inv_c if x is not None and x < last_close), None)
        if tgt is not None and inv is not None:
            return float(tgt), float(inv)
        a = abs(float(amp_pct) or 0.8) / 100.0
        return last_close * (1.0 + a), last_close * (1.0 - a * 0.5)
    if bias == "down":
        cand = [
            _f(f.get("fib_pull_0.618")),
            _f(f.get("fib_pull_0.382")),
            _f(f.get("fib_swing_low")),
        ]
        inv_c = [
            _f(f.get("fib_bounce_0.786")),
            _f(f.get("fib_swing_high")),
        ]
        tgt = next((x for x in cand if x is not None and x < last_close), None)
        inv = next((x for x in inv_c if x is not None and x > last_close), None)
        if tgt is not None and inv is not None:
            return float(tgt), float(inv)
        a = abs(float(amp_pct) or 0.8) / 100.0
        return last_close * (1.0 - a), last_close * (1.0 + a * 0.5)
    return last_close, last_close * 0.985


def ensure_lab(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(path_forecast)")}
    for name, typ in (
        ("amp_pct", "REAL"),
        ("amp_class", "TEXT"),
        ("amp_verdict", "TEXT"),
        ("actual_ret_pct", "REAL"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE path_forecast ADD COLUMN {name} {typ}")


def upsert_forecast(conn: sqlite3.Connection, rec: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO path_forecast(
            as_of, horizon, bias, last_close, target, invalidate,
            factors_json, missing_json, why_json, score, verdict,
            check_close, checked_at, created_at,
            amp_pct, amp_class, amp_verdict, actual_ret_pct
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of, horizon) DO UPDATE SET
            bias=excluded.bias, last_close=excluded.last_close,
            target=excluded.target, invalidate=excluded.invalidate,
            factors_json=excluded.factors_json, missing_json=excluded.missing_json,
            why_json=excluded.why_json, score=excluded.score,
            verdict=excluded.verdict, check_close=excluded.check_close,
            checked_at=excluded.checked_at, created_at=excluded.created_at,
            amp_pct=excluded.amp_pct, amp_class=excluded.amp_class,
            amp_verdict=excluded.amp_verdict, actual_ret_pct=excluded.actual_ret_pct
        """,
        (
            rec["as_of"],
            rec["horizon"],
            rec["bias"],
            rec.get("last_close"),
            rec.get("target"),
            rec.get("invalidate"),
            json.dumps(rec.get("factors") or {}, ensure_ascii=False),
            json.dumps(rec.get("missing") or [], ensure_ascii=False),
            json.dumps(rec.get("why") or [], ensure_ascii=False),
            rec.get("score"),
            rec.get("verdict") or "",
            rec.get("check_close"),
            rec.get("checked_at") or "",
            rec.get("created_at") or _now(),
            rec.get("amp_pct"),
            rec.get("amp_class") or "",
            rec.get("amp_verdict") or "",
            rec.get("actual_ret_pct"),
        ),
    )


def _judge(bias: str, last: float, close: float, invalidate: float) -> str:
    """方向對錯。range＝無明確方向，不計勝率（觀望）。"""
    if close <= 0 or last <= 0:
        return "還沒走完"
    ret = (close / last - 1.0) * 100.0
    if bias == "up":
        if close > last:
            return f"對得上往上：收{close:.0f}"
        if close < invalidate:
            return f"偏了破失效：收{close:.0f}"
        return f"偏了沒往上：收{close:.0f}（{ret:+.2f}%）"
    if bias == "down":
        if close < last:
            return f"對得上往下：收{close:.0f}"
        if close > invalidate:
            return f"偏了破失效：收{close:.0f}"
        return f"偏了沒往下：收{close:.0f}（{ret:+.2f}%）"
    return f"觀望不計分：收{close:.0f}（{ret:+.2f}%）"


def _judge_amp(bias: str, amp_pct: float, actual_ret: float) -> str:
    """幅度對質：僅在方向對時計；落在預估帶＝幅度對得上。

    帶寬：預估 |amp| 的 50%～150%，且至少 ±0.35pt 容差。
    """
    if bias not in {"up", "down"}:
        return "觀望不計幅度"
    if bias == "up" and actual_ret <= 0:
        return "方向偏了不計幅度"
    if bias == "down" and actual_ret >= 0:
        return "方向偏了不計幅度"
    pred = abs(float(amp_pct) or 0.0)
    act = abs(float(actual_ret) or 0.0)
    if pred <= 0:
        return "無幅度預測"
    lo = max(0.0, pred * 0.5 - 0.15)
    hi = pred * 1.5 + 0.35
    if lo <= act <= hi:
        return f"幅度對得上：估{amp_pct:+.2f}% 實{actual_ret:+.2f}%"
    return f"幅度偏了：估{amp_pct:+.2f}% 實{actual_ret:+.2f}%"


def run_backtest(*, max_days: int = 0) -> Dict[str, Any]:
    votes = _load_edge_votes()
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        from scripts.decade_lab_inst_module import ensure as ensure_inst
        from scripts.decade_lab_inst_module import snapshot_inst_factors

        ensure_inst(conn)
        twii = _load_sym(conn, "TWII")
        ixic = _load_sym(conn, "IXIC")
        sox = _load_sym(conn, "SOX")
        vix = _load_sym(conn, "VIX")
        tsm = _load_sym(conn, "TSM")
        nvda = _load_sym(conn, "NVDA")
        dxy = _load_sym(conn, "DXY")
        usdtwd = _load_sym(conn, "USDTWD")
        brent = _load_sym(conn, "BRENT")
        tx_night = _load_tx_night(conn)
        us10y = _load_sym(conn, "US10Y")
        usdjpy = _load_sym(conn, "USDJPY")
        gold = _load_sym(conn, "GOLD")
        copper = _load_sym(conn, "COPPER")
        # 2330 日K（ADR 對照）
        tw2330: Dict[str, Dict[str, float]] = {}
        _prev2330 = None
        for _d, _c in conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), close FROM daily_quotes WHERE stock_id='2330' ORDER BY 1"
        ):
            _day = _ymd(_d)
            _cc = _f(_c)
            if not _day or not _cc:
                continue
            _ret = ((_cc / _prev2330 - 1.0) * 100.0) if _prev2330 else None
            tw2330[_day] = {"close": _cc, "ret": _ret or 0.0, "ret_ok": _ret is not None}
            _prev2330 = _cc
        tx_night_px: Dict[str, float] = {}
        try:
            for _d, _c in conn.execute(
                "SELECT REPLACE(CAST(date AS TEXT),'-',''), close FROM futures_daily "
                "WHERE symbol='TX' AND session='night'"
            ):
                _day = _ymd(_d)
                _cc = _f(_c)
                if _day and _cc:
                    tx_night_px[_day] = _cc
        except sqlite3.Error:
            pass

        tw_days = sorted(twii.keys())
        # segment horizon＝後 3 根；預測日用「當日收盤後」視角對下一窗（用當日因素預測未來，對質用後3日收）
        # 為免偷看：factors 用 as_of 當日已知（收盤後建檔）
        lab = sqlite3.connect(str(LAB_DB), timeout=60.0)
        ensure_lab(lab)
        wrote = 0
        scored = []
        days = tw_days[:-3]  # need forward
        if max_days > 0:
            days = days[-max_days:]
        inst_lit_days = 0
        fib_lit_days = 0
        chips_lit_days = 0
        wave_lit_days = 0
        # 波浪主結構快取（TWII 柱＋樞紐一次）
        try:
            from scripts.decade_lab_wave8_dual import (
                _load_twii as _wave_twii,
                _pivots as _wave_pivots,
                snapshot_wave_asof,
            )

            run_backtest._wave_bars = _wave_twii(conn)  # type: ignore[attr-defined]
            run_backtest._wave_pivots = _wave_pivots(run_backtest._wave_bars)  # type: ignore[attr-defined]
        except Exception:
            run_backtest._wave_bars = []  # type: ignore[attr-defined]
            run_backtest._wave_pivots = []  # type: ignore[attr-defined]
        for day in days:
            if day not in twii or not twii[day].get("ret_ok"):
                continue
            factors, missing = snapshot_factors(
                twii=twii,
                ixic=ixic,
                sox=sox,
                vix=vix,
                tsm=tsm,
                nvda=nvda,
                dxy=dxy,
                usdtwd=usdtwd,
                brent=brent,
                tx_night=tx_night,
                tw_days=tw_days,
                as_of=day,
            )
            if not factors:
                continue
            # 波浪＝主結構
            try:
                w = snapshot_wave_asof(
                    run_backtest._wave_bars,  # type: ignore[attr-defined]
                    run_backtest._wave_pivots,  # type: ignore[attr-defined]
                    day,
                )
                factors["wave_bias"] = w.get("bias") or "range"
                factors["wave_phase"] = w.get("phase")
                factors["wave_ok"] = bool(w.get("ok"))
                factors["wave_gate_ok"] = bool(w.get("gate_ok"))
                factors["wave_htf_ok"] = bool(w.get("htf_ok"))
            except Exception:
                missing.append("wave_snapshot")
            inst_f, inst_m = snapshot_inst_factors(conn, day)
            factors.update(inst_f)
            missing.extend(inst_m)
            try:
                from scripts.decade_lab_mtf_volume import (
                    _load_daily as _mtf_daily,
                    _load_tape_amount,
                    snapshot_mtf_factors,
                )

                # 輕量：每輪重載過重；改用函式外快取
                if "_mtf_bars" not in run_backtest.__dict__:
                    run_backtest._mtf_bars = _mtf_daily(conn)  # type: ignore[attr-defined]
                    run_backtest._mtf_tape = _load_tape_amount(conn)  # type: ignore[attr-defined]
                    # 他點 2026/7/29 低＝橫整失效參考
                    run_backtest._mtf_sup = None  # type: ignore[attr-defined]
                    for _b in run_backtest._mtf_bars:  # type: ignore[attr-defined]
                        if _b["date"] == "20260729":
                            run_backtest._mtf_sup = float(_b["low"])  # type: ignore[attr-defined]
                            break
                mtf_f, mtf_m = snapshot_mtf_factors(
                    run_backtest._mtf_bars,  # type: ignore[attr-defined]
                    run_backtest._mtf_tape,  # type: ignore[attr-defined]
                    day,
                    named_support=run_backtest._mtf_sup,  # type: ignore[attr-defined]
                )
                factors.update(mtf_f)
                missing.extend(mtf_m)
            except Exception:
                missing.append("mtf_snapshot")
            try:
                from scripts.decade_lab_fib_module import load_twii as _fib_twii
                from scripts.decade_lab_fib_module import snapshot_fib_factors

                if "_fib_bars" not in run_backtest.__dict__:
                    run_backtest._fib_bars = _fib_twii(conn)  # type: ignore[attr-defined]
                fib_f, fib_m = snapshot_fib_factors(run_backtest._fib_bars, day)  # type: ignore[attr-defined]
                factors.update(fib_f)
                missing.extend(fib_m)
            except Exception:
                missing.append("fib_snapshot")
            try:
                from scripts.decade_lab_chips_module import snapshot_chips_factors

                chips_f, chips_m = snapshot_chips_factors(conn, day)
                factors.update(chips_f)
                missing.extend(chips_m)
            except Exception:
                missing.append("chips_snapshot")
            # 切割×籌碼／外資共現（快照層合成，供 lit／投票）
            factors["fib_lower_x_margin_kill"] = bool(
                factors.get("fib_lower_third") and factors.get("chips_margin_kill_2d")
            )
            factors["fib_0618sup_x_foreign_pos"] = bool(
                factors.get("fib_near_0618_support")
                and (
                    factors.get("inst_foreign_pos_2d")
                    or (_f(factors.get("inst_foreign_z")) or 0) >= 0.5
                )
            )
            factors["fib_deep_x_margin_z"] = bool(
                factors.get("fib_deep_pull") and factors.get("chips_margin_z_le_m1")
            )
            factors["fib_upper_x_limit_up"] = bool(
                factors.get("fib_upper_third") and factors.get("chips_limit_up_ge_20")
            )
            try:
                from scripts.decade_lab_path_extras import snapshot_extras

                ex_f, ex_m = snapshot_extras(
                    twii=twii,
                    ixic=ixic,
                    sox=sox,
                    vix=vix,
                    us10y=us10y,
                    usdjpy=usdjpy,
                    gold=gold,
                    copper=copper,
                    tsm=tsm,
                    tw2330=tw2330,
                    tx_night_px=tx_night_px,
                    tw_days=tw_days,
                    as_of=day,
                )
                factors.update(ex_f)
                missing.extend(ex_m)
            except Exception:
                missing.append("extras_snapshot")
            decision = decide_path(factors, missing, votes)
            why_codes = [str(x.get("code") or "") for x in (decision.get("why") or [])]
            if any(c.startswith("inst_") for c in why_codes):
                inst_lit_days += 1
            if any(c.startswith("fib_") for c in why_codes):
                fib_lit_days += 1
            if any(c.startswith("chips_") for c in why_codes):
                chips_lit_days += 1
            if any(c.startswith("wave_") for c in why_codes):
                wave_lit_days += 1
            last = twii[day]["close"]
            # 近 20 日 |ret| 均（as-of 前，不含未來）
            i0 = tw_days.index(day)
            prior_abs = [
                abs(float(twii[tw_days[j]]["ret"]))
                for j in range(max(0, i0 - 20), i0)
                if twii[tw_days[j]].get("ret_ok")
            ]
            rv = (sum(prior_abs) / len(prior_abs)) if len(prior_abs) >= 5 else None
            amp_info = estimate_amplitude(
                decision["bias"],
                float(decision["score"] or 0.0),
                factors,
                realized_abs_ret=rv,
            )
            amp_pct = float(amp_info["amp_pct"])
            tgt, inv = _targets(decision["bias"], last, amp_pct, factors)
            # forward close
            i = tw_days.index(day)
            fut = twii[tw_days[i + 3]]["close"]
            actual_ret = ((fut / last - 1.0) * 100.0) if last > 0 else 0.0
            verd = (
                _judge(decision["bias"], last, fut, inv)
                if decision["reviewable"]
                else "因素不足不計分"
            )
            amp_verd = (
                _judge_amp(decision["bias"], amp_pct, actual_ret)
                if decision["reviewable"]
                else "因素不足不計幅度"
            )
            rec = {
                "as_of": day,
                "horizon": "segment3",
                "bias": decision["bias"],
                "amp_pct": amp_pct,
                "amp_class": amp_info.get("amp_class"),
                "regime": factors.get("regime") or "",
                "wave_phase": factors.get("wave_phase") or "",
                "last_close": last,
                "target": tgt,
                "invalidate": inv,
                "factors": factors,
                "missing": decision["missing"],
                "why": decision["why"],
                "score": decision["score"],
                "verdict": verd,
                "amp_verdict": amp_verd,
                "actual_ret_pct": round(actual_ret, 4),
                "check_close": fut,
                "checked_at": _now(),
                "created_at": _now(),
                "reviewable": decision["reviewable"],
            }
            upsert_forecast(lab, rec)
            wrote += 1
            if decision["reviewable"] and ("對得上" in verd or "偏了" in verd):
                scored.append(
                    {
                        "as_of": day,
                        "bias": decision["bias"],
                        "amp_pct": amp_pct,
                        "amp_class": amp_info.get("amp_class"),
                        "actual_ret_pct": round(actual_ret, 4),
                        "verdict": verd,
                        "amp_verdict": amp_verd,
                        "score": decision["score"],
                        "why": decision["why"],
                        "regime": factors.get("regime") or "",
                        "wave_phase": factors.get("wave_phase") or "",
                    }
                )
        lab.commit()

        # 投資人可用：只計有方向（up/down）的對質
        dir_rows = [r for r in scored if r.get("bias") in {"up", "down"}]
        hit = sum(1 for r in dir_rows if "對得上" in r["verdict"])
        miss = sum(1 for r in dir_rows if "偏了" in r["verdict"])
        amp_rows = [r for r in dir_rows if "對得上" in (r.get("verdict") or "")]
        amp_hit = sum(1 for r in amp_rows if "幅度對得上" in (r.get("amp_verdict") or ""))
        amp_miss = sum(1 for r in amp_rows if "幅度偏了" in (r.get("amp_verdict") or ""))
        abs_err = [
            abs(abs(float(r.get("amp_pct") or 0)) - abs(float(r.get("actual_ret_pct") or 0)))
            for r in amp_rows
        ]
        mae = (sum(abs_err) / len(abs_err)) if abs_err else None
        by_bias = {}
        for b in ("up", "down"):
            sub = [r for r in dir_rows if r.get("bias") == b]
            h = sum(1 for r in sub if "對得上" in r["verdict"])
            m = sum(1 for r in sub if "偏了" in r["verdict"])
            by_bias[b] = {
                "n": h + m,
                "hit": h,
                "miss": m,
                "hit_rate": (h / (h + m)) if (h + m) else None,
            }
        by_amp_class: Dict[str, Any] = {}
        for cls in ("micro", "small", "mid", "large"):
            sub = [r for r in amp_rows if r.get("amp_class") == cls]
            ah = sum(1 for r in sub if "幅度對得上" in (r.get("amp_verdict") or ""))
            am = sum(1 for r in sub if "幅度偏了" in (r.get("amp_verdict") or ""))
            by_amp_class[cls] = {
                "n": ah + am,
                "hit": ah,
                "miss": am,
                "hit_rate": (ah / (ah + am)) if (ah + am) else None,
            }
        by_regime: Dict[str, Any] = {}
        for reg in ("bull", "bear", "chop"):
            sub = [r for r in dir_rows if r.get("regime") == reg]
            h = sum(1 for r in sub if "對得上" in r["verdict"])
            m = sum(1 for r in sub if "偏了" in r["verdict"])
            by_regime[reg] = {
                "n": h + m,
                "hit": h,
                "miss": m,
                "hit_rate": (h / (h + m)) if (h + m) else None,
            }
        summary = {
            "written_at": _now(),
            "tz": "Asia/Taipei",
            "goal_zh": "預判大盤漲勢（方向）及幅度",
            "investor_output": list(INVESTOR_OUTPUT),
            "factor_pack": list(FACTOR_PACK),
            "my_responsibility_zh": (
                "最終答案＝漲勢方向＋預估幅度％＋目標／失效＋依據。"
                "法人／投信一定納入判斷；要納入哪些因素、怎麼切＝程式責任。"
            ),
            "wrote": wrote,
            "scored_n": len(scored),
            "directional_n": hit + miss,
            "hit": hit,
            "miss": miss,
            "hit_rate_directional": (hit / (hit + miss)) if (hit + miss) else None,
            "amp_n": amp_hit + amp_miss,
            "amp_hit": amp_hit,
            "amp_miss": amp_miss,
            "hit_rate_amplitude": (amp_hit / (amp_hit + amp_miss)) if (amp_hit + amp_miss) else None,
            "amp_mae_pct": round(mae, 4) if mae is not None else None,
            "by_bias": by_bias,
            "by_amp_class": by_amp_class,
            "by_regime": by_regime,
            "inst_lit_days": inst_lit_days,
            "inst_votes": sorted(k for k in votes if str(k).startswith("inst_")),
            "fib_lit_days": fib_lit_days,
            "fib_votes": sorted(k for k in votes if str(k).startswith("fib_")),
            "chips_lit_days": chips_lit_days,
            "chips_votes": sorted(k for k in votes if str(k).startswith("chips_")),
            "wave_lit_days": wave_lit_days,
            "structural_primary": "wave",
            "biaoke_learn": "見 biaoke_wave_learn_latest（五件／細微波／他說過的）",
            "gate_n20": (hit + miss) >= 20,
            "purpose_zh": (
                "預判大盤方向＋幅度；波浪主結構；飆大五件／細微波／他說過的並列學習對質；"
                "法人外資必進；錯了能歸因；不足記缺口再測；不是買訊不上話筒"
            ),
            "reverse_think_zh": (
                "波浪主判→法人／籌碼／切割／宏觀確認或否決；飆大軌另學另比。"
                "幅度偏了回查波動／夜盤／外圍／法人／切割跨度／波浪相位。"
                "range＝觀望不計分。因素不足→factor_gap_queue。"
            ),
            "not_buy_signal": True,
            "phone_sync": "blocked",
            "WAVE_NEURONS_MATCH": False,
            "storage": "decade_lab.path_forecast + json/gz；不准 PNG",
        }
        lab.close()
    finally:
        conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "path_forecast_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "path_forecast_scored_latest.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in scored[-5000:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        from scripts.decade_lab_factor_gap_queue import record_gap

        gap = record_gap(source="path_forecast", path_summary=summary)
        summary["factor_gap"] = {
            "id": gap.get("id"),
            "fruitless": gap.get("fruitless"),
            "ideas_n": len(gap.get("ideas") or []),
            "schedule_n": len(gap.get("schedule") or []),
            "reason_zh": (gap.get("reason_zh") or "")[:300],
        }
    except Exception as exc:  # noqa: BLE001
        summary["factor_gap_error"] = str(exc)[:200]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=0, help="0=全長史；否則只跑最近 N 日")
    args = ap.parse_args()
    summary = run_backtest(max_days=args.max_days)
    return 0 if summary.get("wrote", 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
