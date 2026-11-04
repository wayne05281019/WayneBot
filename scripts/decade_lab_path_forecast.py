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
    # J 錯單補強閘（震盪／修正浪／融資殺方向／假彈連錯／台積量價確認）
    "regime",
    "false_up_streak",
    "abc_up_call_streak",
    "tsmc_vol_spike",
    "tsmc_vol_confirm_up",
    "tsmc_vol_confirm_down",
    "margin_kill_confirmed",
    "margin_kill_blocked",
    # K 麥可自研模組（深挖硬閘變體優先；過閘才投票）
    "michael_gap_south_bounce",
    "michael_gap_south_after_strong",
    "michael_gap_south_fx_ok",
    "michael_gap_south_fx_ma",
    "michael_gap_south_bear_wick",
    "michael_gap_south_after_night",
    "michael_gap_south",
    "michael_wick_flip_risk",
    "michael_fail_upper",
    "michael_break_lower",
    "michael_wide_chop",
    "michael_ma60_lost",
    "michael_sox_weak",
    # L 八浪段位×定義黃金切割（波底↔波頂目標；過閘才當幅度）
    "wave_fib_primary_px",
    "wave_fib_primary_pct",
    "wave_fib_primary_ratio",
    "wave_fib_mode",
    "wave_fib_expect_down",
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
    # 麥可大葛格條件（討論串長文能量化；加測抬勝率，不取代飆大）
    try:
        from scripts.decade_lab_michael_module import load_michael_votes

        for k, v in load_michael_votes().items():
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
    # 融資連殺：只在「方向閘」通過時灌偏多票；被擋時改記 blocked（不投多）
    add("chips_margin_z_le_m1", bool(factors.get("chips_margin_z_le_m1")))
    add("chips_margin_z_ge_p1", bool(factors.get("chips_margin_z_ge_p1")))
    if factors.get("margin_kill_confirmed") or (
        factors.get("chips_margin_kill_2d") and not factors.get("margin_kill_blocked")
    ):
        add("chips_margin_kill_2d", True)
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
    # 麥可自研：硬閘變體互斥取 |vote| 最強一檔（深挖保留）；裸 gap_south 僅軟閘／非修正浪
    _hard_michaels = (
        "michael_gap_south_bear_wick",
        "michael_gap_south_bounce",
        "michael_gap_south_fx_ma",  # 嚴變體優先於裸 fx_ok
        "michael_gap_south_fx_ok",
        # after_night 語料有用、量化過閘，但進 path 主判易孤票踩空 → 只收集／soft 另議
        "michael_gap_south_after_strong",
    )
    _cands = [
        (_code, abs(float(votes.get(_code) or 0.0)))
        for _code in _hard_michaels
        if factors.get(_code) and _code in votes
    ]
    _picked = False
    if _cands:
        _cands.sort(key=lambda x: -x[1])
        add(_cands[0][0], True)
        _picked = True
    if not _picked:
        _abc = str(factors.get("wave_phase") or "").startswith("corrective_abc")
        _gap_ok = bool(factors.get("michael_gap_south")) and (
            not _abc
            or bool(factors.get("inst_foreign_pos_2d"))
            or (_f(factors.get("inst_foreign_z")) or 0) >= 0.5
        )
        add("michael_gap_south", _gap_ok)
    add("michael_wick_flip_risk", bool(factors.get("michael_wick_flip_risk")))
    add("michael_fail_upper", bool(factors.get("michael_fail_upper")))
    add("michael_break_lower", bool(factors.get("michael_break_lower")))
    add("michael_wide_chop", bool(factors.get("michael_wide_chop")))
    add("michael_ma60_lost", bool(factors.get("michael_ma60_lost")))
    add("michael_sox_weak", bool(factors.get("michael_sox_weak")))
    add("michael_bull_strict", bool(factors.get("michael_bull_strict")))
    return lit


def _margin_kill_direction_ok(factors: Dict[str, Any]) -> Tuple[bool, str]:
    """融資連殺偏多票的方向閘。

    回測錯單顯示 kill_2d 常被當反彈，卻在修正浪尾／支撐破／外資空時踩空。
    通過＝至少一項同向確認，且沒有硬否決。
    """
    if not factors.get("chips_margin_kill_2d"):
        return False, "no_kill"
    phase = str(factors.get("wave_phase") or "")
    regime = str(factors.get("regime") or "")
    hard_veto = bool(factors.get("mtf_named_support_broken")) or (
        str(factors.get("wave_bias") or "") == "down" and phase.startswith("corrective_abc")
    )
    # 震盪＋修正浪：融資殺反彈極易踩空（20260727）→ 直接擋
    if regime == "chop" and phase.startswith("corrective_abc"):
        hard_veto = True
    if hard_veto:
        return False, "hard_veto"
    confirm = any(
        (
            bool(factors.get("inst_foreign_pos_2d")),
            bool(factors.get("inst_foreign_pos_3d")),
            (_f(factors.get("inst_foreign_z")) or 0.0) >= 0.5,
            bool(factors.get("chips_ud_ge_1_5")),
            bool(factors.get("fib_0618sup_x_foreign_pos")),
            bool(factors.get("fib_lower_x_margin_kill")),
            bool(factors.get("tsmc_vol_confirm_up")),
            str(factors.get("wave_bias") or "") == "up"
            and phase.startswith("impulse"),
        )
    )
    if not confirm:
        return False, "no_confirm"
    return True, "confirmed"


def _chop_abc_up_confirm(factors: Dict[str, Any], score: float) -> bool:
    """震盪＋修正浪看漲：要雙確認，否則改 range（維持 n，不擴到全市況）。"""
    if bool(factors.get("mtf_named_support_broken")):
        return False
    if abs(float(score or 0.0)) < 1.35:
        return False
    hits = 0
    if bool(factors.get("inst_foreign_pos_2d")) or (_f(factors.get("inst_foreign_z")) or 0) >= 0.8:
        hits += 1
    if bool(factors.get("margin_kill_confirmed")):
        hits += 1
    if bool(factors.get("tsmc_vol_confirm_up")):
        hits += 1
    if bool(factors.get("fib_0618sup_x_foreign_pos")) or bool(factors.get("fib_deep_x_margin_z")):
        hits += 1
    return hits >= 2


def _macro_only_down(lit: Sequence[Dict[str, Any]]) -> bool:
    """只有美元／油／匯等外圍空票、沒有波浪／法人／籌碼 → 假空。"""
    codes = [
        str(x.get("code") or "")
        for x in lit
        if x.get("code")
        and not str(x.get("code")).endswith("soft_range")
        and not str(x.get("code")).startswith("margin_kill_blocked")
    ]
    if not codes:
        return False
    macro = {
        "dxy_up_tw_down",
        "brent_up_tw_down",
        "fx_up_tw_down",
        "yen_up_tw_down",
        "us10y_up_tw_down",
        "gold_up_risk_off",
        "copper_down_risk_off",
    }
    return any(c in macro for c in codes) and all(c in macro for c in codes)


def _weak_wave_macro_down(lit: Sequence[Dict[str, Any]]) -> bool:
    """wave_struct_down＋外圍、缺法人／籌碼／VIX／支撐 → 震盪假空。"""
    codes = [
        str(x.get("code") or "")
        for x in lit
        if x.get("code")
        and not str(x.get("code")).endswith("soft_range")
        and not str(x.get("code")).startswith("margin_kill_blocked")
        and not str(x.get("code")).startswith("michael_")  # 麥可票另算衝突
    ]
    macro = {
        "dxy_up_tw_down",
        "brent_up_tw_down",
        "fx_up_tw_down",
        "yen_up_tw_down",
        "us10y_up_tw_down",
        "gold_up_risk_off",
        "copper_down_risk_off",
    }
    hard = {
        "inst_foreign_neg_2d",
        "inst_trust_neg_2d",
        "inst_three_neg_2d",
        "inst_foreign_z_le_m1",
        "chips_ud_le_0_6",
        "mtf_named_support_broken",
        "tsmc_vol_confirm_down",
        "vix_z_ge_p1",
        "tx_backward_le_m0_4",
    }
    if "wave_struct_down" not in codes:
        return False
    if any(c in hard for c in codes):
        return False
    return any(c in macro for c in codes) and all(
        c in macro or c == "wave_struct_down" for c in codes
    )


def _rebound_only_up_in_abc(factors: Dict[str, Any], lit: Sequence[Dict[str, Any]]) -> bool:
    """修正浪內只有反彈簇（下影／暴跌／融資z）無外資／台積／融資殺確認 → 假多。"""
    codes = {str(x.get("code") or "") for x in lit}
    rebound = {
        "after_tw_down2_with_wick",
        "after_tw_down2_us_up",
        "after_tw_down2_vol_spike",
        "tw_crash_3pct",
        "tw_vol_spike",
        "chips_margin_z_le_m1",
        "us_up_tw_down",
        "wave_struct_up",
    }
    real = {
        "inst_foreign_pos_2d",
        "inst_foreign_pos_3d",
        "inst_foreign_z_ge_p1",
        "chips_margin_kill_2d",
        "tsmc_vol_confirm_up",
        "fib_0618sup_x_foreign_pos",
        "fib_deep_x_margin_z",
        "fib_lower_x_margin_kill",
    }
    # 外圍空票混在看漲裡不算真確認
    active = {
        c
        for c in codes
        if c
        and not c.endswith("soft_range")
        and not c.startswith("margin_kill_blocked")
        and c not in {"dxy_up_tw_down", "brent_up_tw_down", "fx_up_tw_down"}
    }
    if any(c in real for c in active):
        return False
    if bool(factors.get("margin_kill_confirmed")) or bool(factors.get("tsmc_vol_confirm_up")):
        return False
    if bool(factors.get("inst_foreign_pos_2d")) or (_f(factors.get("inst_foreign_z")) or 0) >= 0.5:
        return False
    return bool(active) and active <= (rebound | {"mtf_named_support_broken"})


def decide_path(factors: Dict[str, Any], missing: Sequence[str], votes: Dict[str, float]) -> Dict[str, Any]:
    """產出投資人要的預測列。因素不夠仍給 bias，但標 reviewable=false。

    主判順序（鎖死）：波浪結構 → 再疊法人／籌碼／切割／宏觀確認或否決。
    飆大軌另對質學習；不准雜訊票蓋掉波浪主判。
    錯單補強：融資殺方向閘、支撐破衝突、震盪修正浪軟觀望、假彈連錯降權。
    """
    # 融資連殺方向閘先寫進 factors，再點亮 lit（避免錯方向灌多票）
    mk_ok, mk_why = _margin_kill_direction_ok(factors)
    if factors.get("chips_margin_kill_2d"):
        factors["margin_kill_confirmed"] = bool(mk_ok)
        factors["margin_kill_blocked"] = not bool(mk_ok)
        factors["margin_kill_gate"] = mk_why

    lit = _lit_why(factors, votes)
    score = sum(float(x["edge"]) for x in lit)
    wave_bias = str(factors.get("wave_bias") or "")
    wave_ok = bool(factors.get("wave_ok"))
    wave_phase = str(factors.get("wave_phase") or "")
    regime = str(factors.get("regime") or "")
    in_abc = wave_phase.startswith("corrective_abc")
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
    # 他點名支撐有效跌破 → 融資殺反彈票作廢；衝突以「中性化」為主，不准單靠衝突硬推空
    # （對質：硬推空會把反彈段打成 down 錯單）
    support_broken = bool(factors.get("mtf_named_support_broken"))
    if support_broken and (factors.get("chips_margin_kill_2d") or factors.get("margin_kill_confirmed")):
        lit = [x for x in lit if x.get("code") != "chips_margin_kill_2d"]
        lit = list(lit) + [{"code": "conflict_support_over_margin_kill", "edge": 0.0}]
        score = sum(float(x["edge"]) for x in lit)
        factors["margin_kill_blocked"] = True
        factors["margin_kill_confirmed"] = False
        if score < -0.55:
            bias = "down"
        elif score > 0.55:
            bias = "up"
        else:
            bias = "range"
    elif support_broken and score > -0.2:
        # 無融資殺衝突時維持原輕量否決（可偏空）
        score = score - 0.25
        lit = list(lit) + [{"code": "mtf_named_support_broken", "edge": -0.25}]
        if score < -0.35:
            bias = "down"
    # 融資殺被擋：記一筆（可歸因），不另加分
    if factors.get("margin_kill_blocked") and factors.get("chips_margin_kill_2d"):
        lit = list(lit) + [{"code": f"margin_kill_blocked_{factors.get('margin_kill_gate') or 'x'}", "edge": 0.0}]
    # 台積量價確認：同向微加權（飆大說法；非主判）
    if bias == "up" and factors.get("tsmc_vol_confirm_up"):
        lit = list(lit) + [{"code": "tsmc_vol_confirm_up", "edge": 0.28}]
        score = sum(float(x["edge"]) for x in lit)
    elif bias == "down" and factors.get("tsmc_vol_confirm_down"):
        lit = list(lit) + [{"code": "tsmc_vol_confirm_down", "edge": -0.28}]
        score = sum(float(x["edge"]) for x in lit)
    # 假彈連錯：修正浪內連續看漲偏了 → 降權改觀望
    false_up = int(factors.get("false_up_streak") or 0)
    if false_up >= 2 and bias == "up" and in_abc:
        bias = "range"
        lit = list(lit) + [{"code": "false_up_streak_soft_range", "edge": 0.0}]
        score = sum(float(x["edge"]) for x in lit if x.get("code") != "wave_struct_up")
    # 同段修正浪連續發 up：第 3 次起改觀望（擋 202607 連錯串）
    abc_up_calls = int(factors.get("abc_up_call_streak") or 0)
    if abc_up_calls >= 2 and bias == "up" and in_abc:
        bias = "range"
        lit = list(lit) + [{"code": "abc_up_call_streak_soft_range", "edge": 0.0}]
    # 震盪＋修正浪看漲要雙確認（不擴到 bull，避免掏空 n）
    if regime == "chop" and in_abc and bias == "up":
        if not _chop_abc_up_confirm(factors, score):
            bias = "range"
            lit = list(lit) + [{"code": "chop_abc_soft_range", "edge": 0.0}]
    # 純外圍空票 → 假空
    if bias == "down" and _macro_only_down(lit):
        bias = "range"
        lit = list(lit) + [{"code": "macro_only_down_soft_range", "edge": 0.0}]
    # 弱波浪＋外圍空 → 假空
    if bias == "down" and _weak_wave_macro_down(lit):
        bias = "range"
        lit = list(lit) + [{"code": "weak_wave_macro_down_soft_range", "edge": 0.0}]
    # 麥可 gap_south（三日偏回歸／多）與空頭主判打架 → 觀望
    if bias == "down" and bool(factors.get("michael_gap_south")) and abs(float(score or 0.0)) < 1.35:
        bias = "range"
        lit = list(lit) + [{"code": "michael_gap_south_vs_down_soft_range", "edge": 0.0}]
    # 裸 michael_gap_south_fx_ok 孤票 → 觀望（檢測有用但單獨當主判方法錯）
    if bias == "up":
        _active_m = [
            str(x.get("code") or "")
            for x in lit
            if x.get("code")
            and not str(x.get("code")).endswith("soft_range")
            and not str(x.get("code")).startswith("margin_kill_blocked")
            and not str(x.get("code")).startswith("conflict_")
        ]
        # 任一麥可旗孤票 → 觀望（檢測有用；單獨當主判方法錯）
        _michael_only = [c for c in _active_m if c.startswith("michael_")]
        if len(_active_m) == 1 and _michael_only:
            bias = "range"
            lit = list(lit) + [{"code": "michael_alone_soft_range", "edge": 0.0}]
        # 20261005（麥可×漲停）暫留計分：擋了會 n<20；下一版另切
    # 修正浪內只剩 wave_struct_up → 觀望（20260708）
    if bias == "up" and in_abc:
        active = [
            str(x.get("code") or "")
            for x in lit
            if x.get("code")
            and not str(x.get("code")).endswith("soft_range")
            and not str(x.get("code")).startswith("margin_kill_blocked")
        ]
        if active == ["wave_struct_up"] or set(active) <= {"wave_struct_up", "michael_gap_south"}:
            bias = "range"
            lit = list(lit) + [{"code": "bare_wave_up_abc_soft_range", "edge": 0.0}]
        # 修正浪＋暴跌反彈票＋融資偏空 → 觀望（20260608／20260707）
        if any(c.startswith("after_tw_down2") for c in active) and "chips_margin_z_le_m1" in active:
            bias = "range"
            lit = list(lit) + [{"code": "abc_crash_bounce_soft_range", "edge": 0.0}]
        # 修正浪極弱看漲＋wave_struct_up → 觀望（20260709；勿無 wave 就擋以免 n 掉）
        if abs(float(score or 0.0)) < 0.35 and "wave_struct_up" in active:
            bias = "range"
            lit = list(lit) + [{"code": "abc_weak_up_soft_range", "edge": 0.0}]
    # 支撐已破＋弱多 → 觀望
    if bias == "up" and support_broken and abs(float(score or 0.0)) <= 0.85:
        bias = "range"
        lit = list(lit) + [{"code": "support_broken_weak_up_soft_range", "edge": 0.0}]
    # 櫃買落後加權：弱多改觀望
    if bool(factors.get("otc_lag_tw")) and bias == "up" and abs(score) < 1.25:
        bias = "range"
        lit = list(lit) + [{"code": "otc_lag_soft_range", "edge": 0.0}]
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

    自修：純票強度 MAE 大；近窗實現波動（日均 |ret| ×√3）準度較高，改為主幹。
    分市況縮放：震盪收斂、空頭略放、多頭中性——壓 MAE 高估。
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
    regime = str(factors.get("regime") or "")
    if regime == "chop":
        base *= 0.78
        basis = f"{basis}_chop078"
    elif regime == "bear":
        base *= 1.08
        basis = f"{basis}_bear108"
    elif regime == "bull":
        base *= 0.95
        basis = f"{basis}_bull095"
    # 修正浪看漲時幅度再收一點（假彈常高估）
    phase = str(factors.get("wave_phase") or "")
    if bias == "up" and phase.startswith("corrective_abc"):
        base *= 0.85
        basis = f"{basis}_abc085"
    # 注意：wave_fib 是波段樞紐目標（底↔頂），不准塞進三日 amp（檢測窗不同會把幅度撐爆）
    # 三日幅度仍用 rv／市況；波段切割只進 target／invalidate（見 _targets）
    amp_abs = max(0.35, min(4.0, base))
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
    """目標／失效。八浪段切割主目標優先；其次 swing Fib；否則幅度％。"""
    if last_close <= 0:
        return last_close, last_close
    f = factors or {}
    # 八浪段位主目標（定義切割率；方向一致才用）
    wf_px = _f(f.get("wave_fib_primary_px"))
    wf_inv = _f(f.get("wave_fib_invalidate_px"))
    if bool(f.get("wave_fib_amp_ok")) and wf_px is not None:
        expect_down = bool(f.get("wave_fib_expect_down"))
        if bias == "down" and expect_down and wf_px < last_close:
            inv = wf_inv if (wf_inv is not None and wf_inv > last_close) else last_close * 1.008
            return float(wf_px), float(inv)
        if bias == "up" and (not expect_down) and wf_px > last_close:
            inv = wf_inv if (wf_inv is not None and wf_inv < last_close) else last_close * 0.992
            return float(wf_px), float(inv)
    # swing 切割目標：多→反彈側／前高；空→回檔側／前低
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
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        from scripts.decade_lab_inst_module import ensure as ensure_inst
        from scripts.decade_lab_inst_module import snapshot_inst_factors

        ensure_inst(conn)
        # 麥可票先量化再載入（檢測窗分軌：當日空≠三日回歸；語料長文先落檔）
        try:
            from scripts.decade_lab_michael_module import (
                extract_michael_corpus,
                quantify_michael,
            )

            extract_michael_corpus(conn)
            quantify_michael(conn)
        except Exception:
            pass
        # 八浪段×定義切割率對質（過閘才開 wave_fib_amp_ok）
        try:
            from scripts.decade_lab_wave_fib_targets import quantify_wave_fib_targets

            quantify_wave_fib_targets(conn)
        except Exception:
            pass
        votes = _load_edge_votes()
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
        # 2330 日K（ADR 對照＋量價確認）
        tw2330: Dict[str, Dict[str, float]] = {}
        _prev2330 = None
        for _d, _c, _vol in conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), close, volume FROM daily_quotes WHERE stock_id='2330' ORDER BY 1"
        ):
            _day = _ymd(_d)
            _cc = _f(_c)
            if not _day or not _cc:
                continue
            _ret = ((_cc / _prev2330 - 1.0) * 100.0) if _prev2330 else None
            tw2330[_day] = {
                "close": _cc,
                "ret": _ret or 0.0,
                "ret_ok": _ret is not None,
                "volume": _f(_vol) or 0.0,
            }
            _prev2330 = _cc
        otc = _load_sym(conn, "OTC")
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
        false_up_streak = 0  # 修正浪內連續看漲偏了（無未來：只消化 as_of+3 已到的案）
        abc_up_call_streak = 0  # 同段 ABC 連續發 up 呼叫次數（發呼叫當下就加，不等結果）
        pending_false: List[Dict[str, Any]] = []
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
            i_day = tw_days.index(day)
            # 先消化已到期的假彈案（resolve_i <= 今日），再進 decide（不准偷看）
            still_pending: List[Dict[str, Any]] = []
            for p in pending_false:
                if int(p["resolve_i"]) <= i_day:
                    fut_c = twii[tw_days[int(p["resolve_i"])]]["close"]
                    verd_p = _judge(str(p["bias"]), float(p["last"]), float(fut_c), float(p["inv"]))
                    if p.get("bias") == "up" and p.get("in_abc"):
                        if "對得上" in verd_p:
                            false_up_streak = 0
                        elif "偏了" in verd_p:
                            false_up_streak += 1
                    elif p.get("bias") != "up":
                        false_up_streak = 0
                else:
                    still_pending.append(p)
            pending_false = still_pending
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
            # 波底↔波頂／波頂↔波底：定義黃金切割目標
            try:
                from scripts.decade_lab_wave_fib_targets import (
                    load_wave_fib_primary,
                    snapshot_wave_fib_targets,
                )

                wf_f, wf_m = snapshot_wave_fib_targets(
                    run_backtest._wave_bars,  # type: ignore[attr-defined]
                    run_backtest._wave_pivots,  # type: ignore[attr-defined]
                    day,
                )
                factors.update(wf_f)
                missing.extend(wf_m)
                prim = load_wave_fib_primary()
                if prim.get("ratio"):
                    # 對質過閘：用過閘主比覆寫當日 primary（切割率固定，只換選哪一檔）
                    ratio = str(prim["ratio"])
                    kind = str(prim.get("kind") or "")
                    if kind.startswith("retrace"):
                        px = _f(wf_f.get(f"wave_fib_retrace_{ratio}"))
                        pct = _f(wf_f.get(f"wave_fib_retrace_{ratio}_pct"))
                    else:
                        px = _f(wf_f.get(f"wave_fib_ext_{ratio}"))
                        pct = _f(wf_f.get(f"wave_fib_ext_{ratio}_pct"))
                    if px is not None:
                        factors["wave_fib_primary_ratio"] = ratio
                        factors["wave_fib_primary_px"] = round(float(px), 2)
                        if pct is not None:
                            factors["wave_fib_primary_pct"] = round(float(pct), 4)
                        factors["wave_fib_amp_ok"] = True
                        factors["wave_fib_primary_hit_band"] = float(prim.get("hit_in_band") or 0)
                    else:
                        factors["wave_fib_amp_ok"] = False
                else:
                    factors["wave_fib_amp_ok"] = False
            except Exception:
                missing.append("wave_fib_snapshot")
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
                    otc=otc or None,
                )
                factors.update(ex_f)
                missing.extend(ex_m)
            except Exception:
                missing.append("extras_snapshot")
            try:
                from scripts.decade_lab_michael_module import (
                    load_tx_regular,
                    snapshot_michael_factors,
                )

                if "_tx_reg" not in run_backtest.__dict__:
                    run_backtest._tx_reg = load_tx_regular(conn)  # type: ignore[attr-defined]
                mi_f, mi_m = snapshot_michael_factors(
                    twii=twii,
                    tx_reg=run_backtest._tx_reg,  # type: ignore[attr-defined]
                    tx_night=tx_night,
                    sox=sox,
                    tw_days=tw_days,
                    as_of=day,
                    foreign_z=_f(factors.get("inst_foreign_z")),
                )
                factors.update(mi_f)
                missing.extend(mi_m)
            except Exception:
                missing.append("michael_snapshot")
            factors["false_up_streak"] = int(false_up_streak)
            factors["abc_up_call_streak"] = int(abc_up_call_streak)
            decision = decide_path(factors, missing, votes)
            # 更新同段 ABC 連看漲呼叫（本件決定後；下一日才看得到累加）
            _phase_now = str(factors.get("wave_phase") or "")
            if _phase_now.startswith("corrective_abc") and decision.get("bias") == "up":
                abc_up_call_streak += 1
            else:
                abc_up_call_streak = 0
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
            # 登記假彈案：3 根後才結案進 streak（今日 decide 看不到本件結果）
            pending_false.append(
                {
                    "bias": decision["bias"],
                    "in_abc": str(factors.get("wave_phase") or "").startswith("corrective_abc"),
                    "last": last,
                    "inv": inv,
                    "resolve_i": i_day + 3,
                }
            )
            # forward close
            i = i_day
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
                "預判大盤方向＋幅度；波浪主結構；錯單閘（震盪修正浪／融資殺方向／"
                "支撐衝突中性／假彈連錯／幅度分市況／台積量價確認）；飆大五件／細微波另學；"
                "法人外資必進；不是買訊不上話筒"
            ),
            "reverse_think_zh": (
                "波浪主判→法人／籌碼／切割／宏觀確認或否決；錯單閘先擋假多再投票。"
                "幅度偏了回查波動／市況／波浪相位。"
                "range＝觀望不計分。因素不足→factor_gap_queue。"
            ),
            "path_gates_zh": (
                "chop+abc軟觀望；margin_kill要同向確認；支撐破×融資殺中性化；"
                "false_up_streak≥2改range；amp分bull/bear/chop；tsmc量價確認票"
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
