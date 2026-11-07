# -*- coding: utf-8 -*-
"""持續強化軌：個股波浪起漲進／相對高點出 × 蕭量價 × 飆大裸K × 大盤波浪位階同步。

教義（實驗室；phone_sync=blocked；不上查股／不改黃金買點）：
1. 買：各波段起漲點（主看 W3 起漲；W1／拉回底轉折僅實驗；W5 起漲更嚴）
2. 出：各波段相對高點（蕭首碰20高／如何賣減碼；可併 W3 頂事件、大盤轉弱）
3. 蕭量價：攻擊量／時間安全／角度／四維分／週線／非過熱
4. 飆大裸K：破線翻／爆量換手當「同向確認」；無量續跌／套牢鏈當「挡」
5. 大盤同步：TWII 蕭氏狀態機位階 —— 非 C/B/A 崩壞才准進；可要求大盤在拉回底／推動窗

「相對高點」＝賣點（使用者鎖死：相對高點就會賣股票）。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, load_twii, select_g_universe
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import (
    KEEP_EXIT,
    _align_feat,
    _bool,
    _near,
    _num,
    _room_mask,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"

CRASHY = {"WAVE_C_CRASH", "WAVE_A_DROP", "WAVE_B_TRAP", "WAVE_5_ENDING_DIAGONAL"}
IMPULSE = {"WAVE_1_UP", "WAVE_3_MAIN", "WAVE_5_FINAL"}
PULLBASE = {"BASE_BOTTOM", "WAVE_2_PULLBACK"}


def _twii_wave_pack(
    *,
    entry_preset: str = "A1_score",
    score_threshold: float = 50.0,
) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
    """大盤 TWII：狀態＋蕭特徵＋事件近窗。"""
    raw = load_twii()
    prep = prepare_ohlcv(raw)
    feat = compute_hsiao_features(prep)
    eng = ElliottHsiaoEngine(entry_preset=entry_preset, score_threshold=score_threshold)
    lab = eng.run(feat, already_featured=True)
    ymd = pd.to_datetime(lab.index).strftime("%Y%m%d")
    st = pd.Series(lab["state_name"].astype(str).values, index=ymd)
    sig = pd.Series(lab["lab_signal"].astype(str).values, index=ymd)
    score = pd.Series(pd.to_numeric(lab.get("hsiao_score_eff"), errors="coerce").values, index=ymd)

    # 事件碼 → 日遮罩（lab_events 的 t 是位置）
    ev_codes = {e["code"]: [] for e in (lab.attrs.get("lab_events") or [])}
    for e in lab.attrs.get("lab_events") or []:
        t = int(e.get("t", -1))
        if 0 <= t < len(ymd):
            ev_codes.setdefault(e["code"], []).append(ymd[t])
    ev_masks: Dict[str, pd.Series] = {}
    for code, days in ev_codes.items():
        m = pd.Series(False, index=ymd)
        for d in days:
            m.loc[d] = True
        ev_masks[code] = m

    feat_ymd = feat.copy()
    feat_ymd.index = pd.to_datetime(feat_ymd.index).strftime("%Y%m%d")

    not_crash = ~st.isin(CRASHY)
    impulse = st.isin(IMPULSE) | sig.eq("LAB_BUY_W3_START")
    pull = st.isin(PULLBASE)
    w3z = st.eq("WAVE_3_MAIN") | _near(sig.eq("LAB_BUY_W3_START"), 3)
    week = _bool(feat_ymd.get("weekly_trend_bullish"), feat_ymd.index)
    not_hot = ~_bool(feat_ymd.get("is_overextended"), feat_ymd.index)
    v_ok = _bool(feat_ymd.get("is_attack_vol"), feat_ymd.index) | _num(
        feat_ymd.get("vol_attack_ratio"), feat_ymd.index
    ).fillna(0).ge(1.5)

    mkt = {
        "mkt_not_crash": not_crash,
        "mkt_pullbase": pull,
        "mkt_impulse": impulse,
        "mkt_w3_zone": w3z,
        "mkt_risk_on": not_crash & (pull | impulse | w3z | st.eq("WAVE_4_CONSOL")),
        "mkt_week": week,
        "mkt_not_hot": not_hot,
        "mkt_V": v_ok,
        "mkt_score50": score.fillna(0) >= 50.0,
        "mkt_ok_basic": not_crash & week & not_hot,
        "mkt_ok_pull_or_impulse": not_crash & (pull | impulse | w3z),
        "mkt_ok_strong": not_crash & week & (pull | w3z | impulse) & not_hot,
    }
    # 大盤相對高／轉弱：W1/W3 頂、避雷針、假突破、進入崩壞近窗
    top = pd.Series(False, index=ymd)
    for code in ("LAB_W1_TOP", "LAB_W3_TOP", "LAB_SELL_W5_TOP", "LAB_SHOOTING_STAR", "LAB_MACD_W5_DIVERGENCE_EXIT"):
        if code in ev_masks:
            top = top | _near(ev_masks[code].reindex(ymd).fillna(False), 3)
    weaken = top | _near(st.isin(CRASHY), 3)
    mkt["mkt_rel_high_risk"] = weaken
    # 特徵位階（浪段引擎若黏住 BASE/W2，仍可用蕭大盤條件當同步）
    align = _bool(feat_ymd.get("bull_alignment"), feat_ymd.index)
    s20 = _num(feat_ymd.get("ma20_time_safety"), feat_ymd.index).fillna(-9) > 0
    a5 = _num(feat_ymd.get("angle_5"), feat_ymd.index).fillna(-9) >= 15.0
    mkt["mkt_feat_bull"] = week & align & not_hot
    mkt["mkt_feat_safe"] = week & s20 & not_hot
    mkt["mkt_feat_thrust"] = week & (v_ok | a5) & not_hot & (~weaken)
    mkt["mkt_feat_ok"] = week & not_hot & (~weaken) & (align | s20 | pull)

    pack = pd.DataFrame({"state": st, "signal": sig, "score": score})
    pack.index = ymd
    return pack, mkt


def _align_mkt(df: pd.DataFrame, mkt: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
    ymd = df["date"].astype(str).str.replace("-", "").str[:8]
    out = {}
    for k, s in mkt.items():
        out[k] = s.reindex(ymd.values).fillna(False).astype(bool)
        out[k].index = df.index
    return out


def _barek_masks(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """飆大裸K近似（向量化；與 story_codes 同精神，不當單獨買訊）。"""
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    prev_c = c.shift(1)
    med_v = v.shift(1).rolling(20, min_periods=5).median()
    max_v = v.shift(1).rolling(20, min_periods=5).max()
    min_low = low.shift(1).rolling(20, min_periods=5).min()
    max_high = h.shift(1).rolling(20, min_periods=5).max()

    down = (c < prev_c) | (c < o)
    up = (c > prev_c) | (c > o)
    dry = v < (med_v * 0.7)
    climax = v >= (max_v * 0.95)
    dry_down = down & dry
    break_low_no_climax = (low < min_low) & (~climax)
    climax_turn = climax & (up | down)
    # 套牢鏈：紅→兩綠加深
    trap = (c.shift(2) > o.shift(2)) & (c.shift(1) < o.shift(1)) & (c < o) & (c < c.shift(1))
    flip = (low < min_low) & (c > min_low)
    # 建設性裸K：破線翻或爆量換手且非套牢／無量續跌
    constructive = (flip | (climax_turn & up)) & (~trap) & (~dry_down)
    avoid = dry_down | trap | break_low_no_climax

    return {
        "bk_flip": flip.fillna(False),
        "bk_climax": climax_turn.fillna(False),
        "bk_constructive": constructive.fillna(False),
        "bk_avoid": avoid.fillna(False),
        "bk_not_avoid": (~avoid.fillna(False)),
    }


def _event_mask_from_wave(wave: pd.DataFrame, code: str, near: int = 1) -> pd.Series:
    """wave 來自 _wave_frame，僅有 lab_signal；W1/W5/TOP 需另跑 engine attrs。"""
    sig = wave["lab_signal"].fillna("") if "lab_signal" in wave.columns else pd.Series("", index=wave.index)
    return _near(sig.eq(code), near) if near > 1 else sig.eq(code)


def _stock_wave_events(raw: pd.DataFrame, df: pd.DataFrame) -> Dict[str, pd.Series]:
    prep = prepare_ohlcv(raw)
    feat = compute_hsiao_features(prep)
    eng = ElliottHsiaoEngine(entry_preset="A1_score", score_threshold=50.0)
    lab = eng.run(feat, already_featured=True)
    ymd_lab = pd.to_datetime(lab.index).strftime("%Y%m%d")
    ymd = df["date"].astype(str).str.replace("-", "").str[:8]
    # events
    masks: Dict[str, pd.Series] = {}
    for code in (
        "LAB_W1_START",
        "LAB_BUY_W3_START",
        "LAB_W5_START",
        "LAB_W1_TOP",
        "LAB_W3_TOP",
        "LAB_SELL_W5_TOP",
        "LAB_W2_HAMMER",
        "LAB_IMMORTAL_GUIDE",
    ):
        m = pd.Series(False, index=ymd_lab)
        for e in lab.attrs.get("lab_events") or []:
            if e.get("code") == code:
                t = int(e.get("t", -1))
                if 0 <= t < len(ymd_lab):
                    m.iloc[t] = True
        # also lab_signal equality
        if "lab_signal" in lab.columns:
            m = m | lab["lab_signal"].astype(str).eq(code).values
        aligned = m.reindex(ymd.values).fillna(False)
        aligned.index = df.index
        masks[code] = aligned.astype(bool)
    return masks


def _stock_entries(
    masks: Dict[str, pd.Series],
    wmasks: Dict[str, pd.Series],
    ev: Dict[str, pd.Series],
    feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    room = _room_mask(feat)
    w3 = _bool(wmasks.get("W_w3_start"), feat.index) | _bool(ev.get("LAB_BUY_W3_START"), feat.index)
    w1 = _bool(ev.get("LAB_W1_START"), feat.index)
    w5 = _bool(ev.get("LAB_W5_START"), feat.index)
    pull = _bool(wmasks.get("W_pullbase"), feat.index)
    ma60 = _bool(masks.get("ma60_lower_confirmed"), feat.index)
    w3z = _bool(wmasks.get("W_w3_zone"), feat.index)
    hammer = _bool(ev.get("LAB_W2_HAMMER"), feat.index) | _near(pull, 3)

    return {
        "E_w3_start": w3 & room,
        "E_w3_or_ma60w3": (w3 | (ma60 & w3z)) & room,
        "E_w1_start": w1 & room,  # 實驗
        "E_pull_hammer": hammer & room,
        "E_w5_start": w5 & room,  # 更嚴，後面必疊大盤＋量價
    }


def run_sync(
    *, n_universe: int = 100, twii_preset: str = "A1_score", twii_thr: float = 50.0,
) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    _, mkt_raw = _twii_wave_pack(entry_preset=twii_preset, score_threshold=twii_thr)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    # 進場核 × 大盤閘 × 蕭／裸K
    mkt_gates = (
        "mkt_none",
        "mkt_not_crash",
        "mkt_ok_basic",
        "mkt_ok_pull_or_impulse",
        "mkt_ok_strong",
        "mkt_risk_on",
        "mkt_feat_bull",
        "mkt_feat_safe",
        "mkt_feat_thrust",
        "mkt_feat_ok",
    )
    stock_filters = (
        "F_none",
        "F_hsiao_V",
        "F_hsiao_S55",
        "F_hsiao_VPT",
        "F_bk_ok",
        "F_bk_constructive",
        "F_V_bk",
        "F_S55_bk",
        "F_V_mktstrong",  # placeholder resolved per row
    )

    bucket: Dict[str, List[Dict[str, Any]]] = {
        "leave_zero__hi20_or_desync": [],
        "random__leave_zero__hi20_or_desync": [],
    }
    # 出場變體：標準 hi20；若大盤轉弱則視同更積極（仍用 hi20_or_desync 模擬，另做 early 標記統計）
    meta_n = 0
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 150:
                continue
            meta_n += 1
            df = _normalize_ohlc(raw)
            feat = _align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
            wave = _align_wave(df, _wave_frame(raw))
            wmasks = _wave_masks(wave)
            masks = _build_mark_masks(df)
            ev = _stock_wave_events(raw, df)
            entries = _stock_entries(masks, wmasks, ev, feat)
            bank = _wave_hsiao_bank(feat, wmasks, wave)
            bk = _barek_masks(df)
            mkt = _align_mkt(df, mkt_raw)
            hl, temp_label = __import__(
                "scripts.decade_lab_phone_trade_confront", fromlist=["_build_hl_temp"]
            )._build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            # 大盤轉弱日：可選提早出場（用 sell_desync 路徑不夠；改在 entry 擋或另 exit）
            # 這裡用 hi20_or_desync；另測「進場避开大盤相對高風險」
            lz = _bool(masks.get("leave_zero_blue_tri"), df.index)
            bucket["leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df, lz, hl=hl, temp_label=temp_label, sid=sid, entry_tag="lz", exit_mode=KEEP_EXIT
                )
            )
            bucket["random__leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df,
                    _random_matched(lz, pd.Series(True, index=df.index), seed=seed),
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    entry_tag="rnd_lz",
                    exit_mode=KEEP_EXIT,
                )
            )

            filt_map = {
                "F_none": pd.Series(True, index=df.index),
                "F_hsiao_V": bank["hsiao_V"],
                "F_hsiao_S55": bank["score55"],
                "F_hsiao_VPT": bank["hsiao_VPT"],
                "F_bk_ok": bk["bk_not_avoid"],
                "F_bk_constructive": bk["bk_constructive"],
                "F_V_bk": bank["hsiao_V"] & bk["bk_not_avoid"],
                "F_S55_bk": bank["score55"] & bk["bk_not_avoid"],
            }

            # 主核：W3／W3∪紅箭；實驗核較少組合以免爆炸
            core_use = ("E_w3_start", "E_w3_or_ma60w3")
            exp_use = ("E_w1_start", "E_pull_hammer", "E_w5_start")

            for ename in core_use + exp_use:
                em = entries[ename].fillna(False)
                for mg in mkt_gates:
                    mm = pd.Series(True, index=df.index) if mg == "mkt_none" else mkt[mg]
                    # 实验核强制至少 basic 大盘
                    if ename in exp_use and mg == "mkt_none":
                        continue
                    if ename == "E_w5_start" and mg not in ("mkt_ok_strong", "mkt_ok_pull_or_impulse"):
                        continue
                    f_list = list(filt_map.keys()) if ename in core_use else ("F_none", "F_hsiao_V", "F_V_bk", "F_hsiao_S55")
                    for fname in f_list:
                        fmask = filt_map[fname].reindex(df.index).fillna(False)
                        # 避开大盘相对高风险日进场
                        entry = em & mm.fillna(False) & fmask & (~mkt["mkt_rel_high_risk"].fillna(False))
                        key = f"{ename}__{mg}__{fname}__{KEEP_EXIT}"
                        bucket.setdefault(key, []).extend(
                            _simulate_exits(
                                df,
                                entry,
                                hl=hl,
                                temp_label=temp_label,
                                sid=sid,
                                entry_tag=key,
                                exit_mode=KEEP_EXIT,
                            )
                        )
                        pool = entries["E_w3_or_ma60w3"].fillna(False) | entries["E_w3_start"].fillna(False)
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=df.index)
                        rnd = _random_matched(
                            entry, pool & mm.fillna(False) & fmask, seed=seed + len(key)
                        )
                        bucket.setdefault(f"random__{key}", []).extend(
                            _simulate_exits(
                                df,
                                rnd,
                                hl=hl,
                                temp_label=temp_label,
                                sid=sid,
                                entry_tag=f"rnd__{key}",
                                exit_mode=KEEP_EXIT,
                            )
                        )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    from scripts.decade_lab_phone_trade_confront import _agg_trades

    by_key = {k: _agg_trades(v) for k, v in bucket.items()}
    lz0 = by_key.get("leave_zero__hi20_or_desync") or {}

    ranking = []
    for key, st in by_key.items():
        if key.startswith("random__") or key.startswith("leave_zero__"):
            continue
        rnd = by_key.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        win = float(st.get("win_rate") or np.nan)
        exp = float(st.get("expectancy") or np.nan)
        ok_n = days >= 20
        beats_random = bool(
            ok_n
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        beats_lz = bool(
            ok_n
            and lz0
            and exp > float(lz0.get("expectancy", np.nan))
            and win >= float(lz0.get("win_rate", np.nan)) - 0.005
        )
        # vs same entry without mkt (mkt_none + F_none)
        parts = key.split("__")
        ename = parts[0] if parts else ""
        base = by_key.get(f"{ename}__mkt_none__F_none__{KEEP_EXIT}") or {}
        base_win = float(base.get("win_rate") or np.nan) if base else float("nan")
        lifts = bool(ok_n and np.isfinite(base_win) and win > base_win + 0.005)
        bal = float(win) * min(1.0, days / 50.0) if ok_n and np.isfinite(win) else float("-inf")
        ranking.append(
            {
                "key": key,
                "entry": ename,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": win,
                "expectancy": exp,
                "avg_hold": st.get("avg_hold"),
                "exit_reason_counts": st.get("exit_reason_counts"),
                "random_win_rate": rnd.get("win_rate"),
                "random_expectancy": rnd.get("expectancy"),
                "beats_random": beats_random,
                "beats_leave_zero": beats_lz,
                "lifts_entry_baseline": lifts,
                "entry_base_win": base_win if np.isfinite(base_win) else None,
                "balanced_score": bal,
            }
        )

    winners = [r for r in ranking if r["beats_random"] and r["beats_leave_zero"]]
    lift = [r for r in winners if r["lifts_entry_baseline"]]
    by_bal = sorted(
        winners,
        key=lambda r: (float(r.get("balanced_score") or -9), float(r.get("win_rate") or -1)),
        reverse=True,
    )
    by_win = sorted(
        [r for r in ranking if int(r.get("n_unique_entry_days") or 0) >= 20],
        key=lambda r: float(r.get("win_rate") or -1),
        reverse=True,
    )
    # 分进场类型
    by_entry: Dict[str, List] = {}
    for r in by_bal:
        by_entry.setdefault(r["entry"], []).append(r)

    gate = (
        f"winners={len(winners)}/{len(ranking)}; lift={len(lift)}; "
        f"best_bal={by_bal[0]['key'] if by_bal else None} "
        f"win={by_bal[0].get('win_rate') if by_bal else None} "
        f"days={by_bal[0].get('n_unique_entry_days') if by_bal else None}; "
        f"best_win={by_win[0]['key'] if by_win else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "doctrine_zh": {
            "buy": "波浪各段起漲（主W3；W1／拉回錘子實驗；W5更嚴）",
            "sell": "相對高點＝蕭20高／如何賣；避开大盤相對高風險日進場",
            "hsiao": "量價時間角度／四維分",
            "biaoke_barek": "破線翻／爆量建設；挡無量續跌／套牢鏈",
            "market_sync": "TWII 蕭氏位階：非崩壞／拉回或推動窗／強閘＝週線+位階+非過熱",
        },
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "leave_zero_baseline": lz0,
        "ranking": ranking,
        "winners_beat_random_and_lz": winners,
        "winners_lift_entry_baseline": lift,
        "by_balanced_score": by_bal[:20],
        "by_winrate_n20": by_win[:15],
        "best_by_entry": {k: v[:5] for k, v in by_entry.items()},
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_market_wave_sync_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_market_wave_sync_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_BAL", json.dumps(by_bal[:6], ensure_ascii=False, default=str)[:2000], flush=True)
    print("TOP_WIN", json.dumps(by_win[:6], ensure_ascii=False, default=str)[:1500], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--twii-preset", default="A1_score")
    ap.add_argument("--twii-thr", type=float, default=50.0)
    args = ap.parse_args()
    run_sync(n_universe=args.n, twii_preset=args.twii_preset, twii_thr=args.twii_thr)


if __name__ == "__main__":
    main()
