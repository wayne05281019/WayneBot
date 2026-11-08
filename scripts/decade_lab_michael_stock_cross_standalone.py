# -*- coding: utf-8 -*-
"""麥可教學 × 現有判斷粗代理 — 個股買點交叉深度測（可獨立跑；phone_sync=blocked）。

不依賴 spirit／hsiao 整包：只用 daily_quotes 官方開高低收＋量。
教學來源＝近十篇樓下長文（向南／強摘／15K連2／發哥止跌／確認才買）。
主判＝持有末不虧 vs 寬對照；不是買訊；不准改 leave_zero／黃金。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")
HOLD_MAX = 20
MIN_N = 20
HI_GATE = 0.05
# 流動母體：近一年日均成交額（千元）下限
MIN_TURNOVER_K = 800_000.0
UNIVERSE_N = 80
MUST = ("2330", "2317", "2454", "2303", "2382", "3711", "2881", "2882")


def _load_ohlcv(sid: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        df = pd.read_sql(
            """
            SELECT date, open, high, low, close, volume, turnover_k
            FROM daily_quotes WHERE stock_id=? ORDER BY date
            """,
            con,
            params=(sid,),
        )
    finally:
        con.close()
    if df.empty:
        return df
    df["date"] = df["date"].astype(str).str.replace("-", "").str[:8]
    for c in ("open", "high", "low", "close", "volume", "turnover_k"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.reset_index(drop=True)


def _universe() -> List[str]:
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        liq = pd.read_sql(
            """
            SELECT stock_id,
                   AVG(turnover_k) AS avg_turnover_k,
                   COUNT(*) AS n_bars
            FROM daily_quotes
            WHERE date >= strftime('%Y%m%d', 'now', '-400 days')
            GROUP BY stock_id
            HAVING n_bars >= 120 AND avg_turnover_k >= ?
            ORDER BY avg_turnover_k DESC
            LIMIT ?
            """,
            con,
            params=(MIN_TURNOVER_K, UNIVERSE_N),
        )
    finally:
        con.close()
    out = liq["stock_id"].astype(str).tolist() if len(liq) else []
    for sid in MUST:
        if sid not in out:
            out.append(sid)
    return out


def _near(s: pd.Series, n: int) -> pd.Series:
    x = s.fillna(False).astype(bool)
    out = x.copy()
    for k in range(1, n + 1):
        out = out | x.shift(k).fillna(False)
    return out.fillna(False)


def _michael_masks(df: pd.DataFrame) -> Dict[str, pd.Series]:
    o, h, low, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    prev_c = c.shift(1)
    gap = (o / prev_c - 1.0) * 100.0
    ret = (c / prev_c - 1.0) * 100.0
    prior_ret = ret.shift(1)
    open_high_fade = (gap >= 0.6) & (c < o) & (ret <= -0.3)
    gap_after_strong = (prior_ret >= 1.2) & (gap <= -0.5)
    gap_south = open_high_fade | gap_after_strong
    strong_pick_trap = (prior_ret >= 2.0) & (ret <= 0.2) & (c <= o)
    ma10 = c.rolling(10, min_periods=5).mean()
    above = c >= ma10
    conf2 = above & above.shift(1).fillna(False) & (c > o) & (c.shift(1) > o.shift(1))
    vol_ma = v.rolling(20, min_periods=5).mean()
    climax = v.shift(1) >= (vol_ma.shift(1) * 1.8)
    pull_ok = climax & (v < vol_ma) & (low >= low.shift(1) * 0.995) & (c >= o)
    buy_confirm = conf2 & (~strong_pick_trap) & (~gap_south)
    buy_stable = buy_confirm & (
        pull_ok | pull_ok.shift(1).fillna(False) | pull_ok.shift(2).fillna(False)
    )
    # 裸K粗避：超長上影追高
    span = (h - low).replace(0, np.nan)
    upper = (h - np.maximum(o, c)) / span
    bk_avoid = (upper >= 0.55) & (c < o) & (ret >= 0.5)
    bk_ok = ~bk_avoid.fillna(False)
    return {
        "gap_south": gap_south.fillna(False),
        "trap": strong_pick_trap.fillna(False),
        "conf2": conf2.fillna(False),
        "buy_confirm": buy_confirm.fillna(False),
        "buy_stable": buy_stable.fillna(False),
        "bk_ok": bk_ok.fillna(True),
    }


def _intent_soft(df: pd.DataFrame) -> pd.Series:
    """意圖軟代理：近低／回測區放量收紅，或中段吸籌縮量翻紅（非正式 INTENT）。"""
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)
    low = df["low"].astype(float)
    lo20 = low.rolling(20, min_periods=8).min()
    hi20 = df["high"].astype(float).rolling(20, min_periods=8).max()
    vol_ma = v.rolling(20, min_periods=5).mean()
    near_lo = c <= (lo20 * 1.08)
    mid_pull = (c <= hi20 * 0.92) & (c >= lo20 * 1.02)
    attack = (v >= vol_ma * 1.25) & (c > o)
    absorb = (v <= vol_ma * 0.9) & (c > o) & (c.shift(1) < o.shift(1))
    return ((near_lo & attack) | (mid_pull & (attack | absorb))).fillna(False)


def _teach_phases(df: pd.DataFrame) -> pd.Series:
    """洗／吸／底確認／備攻粗 OR（日K量價）。"""
    o, h, low, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    vol_ma = v.rolling(20, min_periods=5).mean()
    lo20 = low.rolling(20, min_periods=8).min()
    # 洗：破近低後 1–3 日內站回
    broke = low < lo20.shift(1)
    reclaim = c > lo20.shift(1)
    wash = reclaim & (
        broke.shift(1).fillna(False) | broke.shift(2).fillna(False) | broke.shift(3).fillna(False)
    )
    # 吸：下跌後量縮收紅
    prev_down = c.shift(1) < o.shift(1)
    absorb = prev_down & (v < vol_ma * 0.85) & (c > o)
    # 底確認：破底翻＝今低不破昨低且收紅放量
    bottom = (low > low.shift(1)) & (c > o) & (v >= vol_ma) & (c.shift(1) < o.shift(1))
    # 備攻：縮量橫盤後放量
    prep = (v.shift(1) < vol_ma.shift(1) * 0.8) & (v >= vol_ma * 1.3) & (c > o)
    return (wash | absorb | bottom | prep).fillna(False)


def _lz_proxy(df: pd.DataFrame) -> pd.Series:
    c = df["close"].astype(float)
    lo60 = df["low"].astype(float).rolling(60, min_periods=20).min()
    near = c <= (lo60 * 1.08)
    return (near & (c > df["open"].astype(float)) & near.shift(1).fillna(False)).fillna(False)


def _fwd(df: pd.DataFrame, entry: pd.Series) -> Dict[str, Any]:
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    c = df["close"].astype(float)
    hits: List[Tuple[float, float]] = []
    mask = entry.fillna(False).astype(bool).to_numpy()
    for i, on in enumerate(mask):
        if not on or i + 2 >= len(df):
            continue
        px = float(o.iloc[i + 1])
        if not np.isfinite(px) or px <= 0:
            continue
        j2 = min(len(df) - 1, i + HOLD_MAX)
        mx = float(h.iloc[i + 1 : j2 + 1].max())
        end = float(c.iloc[j2])
        hits.append(((mx / px) - 1.0, (end / px) - 1.0))
    if not hits:
        return {k: float("nan") for k in ("n", "win_hi5", "exp_hi", "win_end", "exp_end")} | {"n": 0}
    rets = np.array([x[0] for x in hits])
    ends = np.array([x[1] for x in hits])
    return {
        "n": int(len(hits)),
        "win_hi5": float((rets >= HI_GATE).mean()),
        "exp_hi": float(rets.mean()),
        "win_end": float((ends >= 0.0).mean()),
        "exp_end": float(ends.mean()),
    }


def _agg(rows: Sequence[Dict[str, Any]], base: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ns = [r for r in rows if int(r.get("n") or 0) > 0]
    n = int(sum(int(r["n"]) for r in ns))
    if n <= 0:
        return {"n": 0, "n_ge20": False}
    out: Dict[str, Any] = {"n": n, "n_ge20": n >= MIN_N}
    for k in ("win_hi5", "exp_hi", "win_end", "exp_end"):
        out[k] = round(sum(float(r[k]) * int(r["n"]) for r in ns) / n, 5)
    if base and base.get("n"):
        for k in ("win_hi5", "win_end", "exp_end", "exp_hi"):
            out[f"d_{k}"] = round(float(out[k]) - float(base.get(k) or 0), 5)
        out["stable_score"] = round(
            2.0 * float(out.get("d_win_end") or 0)
            + 1.0 * float(out.get("d_win_hi5") or 0)
            + 0.5 * float(out.get("d_exp_end") or 0),
            5,
        )
        out["beats_base"] = bool(
            n >= MIN_N
            and float(out.get("d_win_end") or 0) > 0
            and float(out.get("d_exp_end") or 0) >= 0
            and float(out.get("win_end") or 0) >= 0.55
        )
    return out


def main() -> None:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    symbols = _universe()
    tsmc = _load_ohlcv("2330")
    tgate: Dict[str, bool] = {}
    if len(tsmc) >= 40:
        tc = tsmc["close"].astype(float)
        tma = tc.rolling(10, min_periods=5).mean()
        tlo = tsmc["low"].astype(float).rolling(20, min_periods=8).min()
        g = ((tc >= tma) & (tc.shift(1) >= tma.shift(1)) & (tsmc["low"] > tlo.shift(1))).fillna(False)
        tgate = dict(zip(tsmc["date"].astype(str), g.astype(bool)))

    bucket: Dict[str, List[Dict[str, Any]]] = {}
    errors: List[str] = []
    meta_n = 0
    for sid in symbols:
        try:
            df = _load_ohlcv(sid)
            if len(df) < 120:
                continue
            meta_n += 1
            mm = _michael_masks(df)
            intent = _intent_soft(df)
            teach = _teach_phases(df)
            lz = _lz_proxy(df)
            ip3 = _near(intent, 3) & mm["bk_ok"]
            g = df["date"].astype(str).map(lambda d: tgate.get(d, False)).fillna(False).astype(bool)
            avoid = (~mm["trap"]) & (~mm["gap_south"])
            conf_tsmc = mm["buy_confirm"] & g
            stable1 = conf_tsmc & avoid & ip3
            stable2 = stable1 & teach
            stable3 = conf_tsmc & avoid & ip3 & _near(teach, 2)
            cores = {
                "ip3": ip3,
                "m_confirm": mm["buy_confirm"],
                "m_confirm_tsmc": conf_tsmc,
                "stable1_m_ip3": stable1,
                "stable2_m_ip3_teach": stable2,
                "stable3_m_ip3_near": stable3,
                "lz_m_tsmc": lz & mm["buy_confirm"] & g & avoid,
                "trap_only": mm["trap"],
                "south_only": mm["gap_south"],
                "bk_wide": mm["bk_ok"],
            }
            for name, entry in cores.items():
                st = _fwd(df, entry)
                st["sid"] = sid
                bucket.setdefault(name, []).append(st)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    # 對照用寬底：裸K可進場日（避免意圖過稀把陷阱日抬成「贏」）
    base_wide = _agg(bucket.get("bk_wide", []))
    base_ip3 = _agg(bucket.get("ip3", []), base=base_wide)
    ranking = []
    for name, rows in bucket.items():
        a = _agg(rows, base=base_wide)
        a["key"] = name
        # 相對意圖軸的差值另記
        if base_ip3.get("n"):
            for k in ("win_hi5", "win_end", "exp_end"):
                a[f"vs_ip3_{k}"] = round(float(a.get(k) or 0) - float(base_ip3.get(k) or 0), 5)
        ranking.append(a)
    ranking.sort(
        key=lambda r: (
            -(r.get("stable_score") if r.get("stable_score") is not None else -9),
            -(r.get("n") or 0),
        )
    )
    # 穩利閘：贏寬底 + 同時贏意圖軸持有末 + 非陷阱／向南單軸
    deny = {"trap_only", "south_only", "bk_wide"}
    beats = [
        r
        for r in ranking
        if r.get("beats_base")
        and r.get("key") not in deny
        and float(r.get("vs_ip3_win_end") or 0) > 0
    ]
    out = {
        "version": "michael_stock_cross_standalone",
        "phone_sync": "blocked",
        "buy_signal": False,
        "as_of": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - t0, 1),
        "universe_n": meta_n,
        "hold_max": HOLD_MAX,
        "hi_gate": HI_GATE,
        "teach_rules_zh": [
            "確認才買：連2收短均上（15K連2代理）",
            "強摘／拉積日不追多",
            "向南日不當多單進場",
            "止跌看發哥（2330閘）再開買窗",
            "與意圖軟／教學相位交叉求穩",
        ],
        "base_wide": base_wide,
        "base_ip3": base_ip3,
        "ranking": ranking,
        "beats_base": beats,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "gate_one_liner": (
            f"michael_stock_cross_standalone n_univ={meta_n} beats={len(beats)} "
            f"best={(beats[0]['key'] if beats else None)} "
            f"d_end_vs_wide={(beats[0].get('d_win_end') if beats else None)} "
            f"vs_ip3_end={(beats[0].get('vs_ip3_win_end') if beats else None)} "
            f"phone_sync=blocked"
        ),
        "decision_zh": (
            "何時買較穩（實驗室；未過閘＝非買訊）："
            "發哥閘開＋避開強摘／向南＋連2確認後，再與意圖近窗／教學相位交叉；"
            "以持有末不虧為主判。空名單／未贏對照＝不換現況。"
        ),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    (ART / "michael_stock_cross_standalone_latest.json").write_text(text, encoding="utf-8")
    (DOC / "michael_stock_cross_standalone_latest.json").write_text(text, encoding="utf-8")
    invent = {
        "track": "michael_stock_teach",
        "phone_sync": "blocked",
        "as_of": out["as_of"],
        "gate": out["gate_one_liner"],
        "beats": [
            {
                "key": r["key"],
                "n": r["n"],
                "d_win_end": r.get("d_win_end"),
                "win_end": r.get("win_end"),
                "d_win_hi5": r.get("d_win_hi5"),
            }
            for r in beats[:8]
        ],
        "decision_zh": out["decision_zh"],
        "lab_v2_align": "與 lab mix v2 同結論方向：confirm×tsmc×ip3×teach",
    }
    (ART / "michael_teach_invent_latest.json").write_text(
        json.dumps(invent, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DOC / "michael_teach_invent_latest.json").write_text(
        json.dumps(invent, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("GATE", out["gate_one_liner"], flush=True)
    for r in ranking[:12]:
        print(
            f"  {r['key']:26s} n={r.get('n',0):6d} end={r.get('win_end')} dE={r.get('d_win_end')} "
            f"hi5={r.get('win_hi5')} score={r.get('stable_score')} beat={r.get('beats_base')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
