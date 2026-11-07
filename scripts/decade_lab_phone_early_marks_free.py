# -*- coding: utf-8 -*-
"""提早買賣自由因子對質（實驗室；不上話筒）。

使用者目標（2026-11-08）：提早知道個股買點＋提早知道賣點。
給定精神材料若限制達標 → 可自由加真史官方 OHLC／feat／lab_signal 因子。

同時量：
- 勝率／期望／獨立日（relhigh 模擬）
- 買提早：bars_before_hi20（愈大＝買標相對 20 高愈早）
- 賣提早：持有根數（在贏的前提下愈短＝賣愈早抓到相對高）

鎖：phone_sync=blocked；不准改 leave_zero；不准發明話筒 5／9；不准假資料。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_champion_v3_ideas import build_v3_extras
from scripts.decade_lab_phone_champion_v4_ideas import build_v4_extras
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import (
    _align_feat,
    _cores,
    _near,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_mark_earliness import _agg_earliness, _measure_signal_earliness
from scripts.decade_lab_phone_market_wave_sync import (
    _align_mkt,
    _barek_masks,
    _stock_wave_events,
    _twii_wave_pack,
)
from scripts.decade_lab_phone_spirit_masks import build_spirit_masks
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"
MAX_HOLD = 60


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _simulate_exit(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: str,
    sid: str,
    entry_tag: str,
    wave_top: pd.Series,
    early_sell: pd.Series,
    mode: str,
) -> List[Dict[str, Any]]:
    """mode: hi20_or_wave_top | wave_top_next | hi20_or_wave_or_early（early＝耗盡／近10高／脫離）。"""
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
    rows: List[Dict[str, Any]] = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(o.iloc[entry_i])
        exit_j: Optional[int] = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            if mode in ("hi20_or_wave_top", "hi20_or_wave_or_early") and hl_j == "20高":
                exit_j = j
                reason = "first_hi20"
                break
            if mode in ("wave_top_next", "hi20_or_wave_top", "hi20_or_wave_or_early") and bool(wave_top.iloc[j]):
                exit_j = j
                reason = "wave_rel_high"
                break
            if mode == "hi20_or_wave_or_early" and bool(early_sell.iloc[j]):
                exit_j = j
                reason = "early_rel_high"
                break
        if exit_j is None:
            exit_j = min(n - 1, entry_i + MAX_HOLD)
            reason = "max_hold_60"
        exit_px = float(c.iloc[exit_j])
        ret = exit_px / entry_px - 1.0 if entry_px > 0 else float("nan")
        rows.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "temp_label": temp_label,
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_j],
                "entry_i": int(entry_i),
                "exit_i": int(exit_j),
                "hold_bars": int(exit_j - entry_i),
                "net_ret": ret,
                "win": bool(np.isfinite(ret) and ret > 0),
                "exit_reason": reason,
            }
        )
        i = exit_j + 1
    return rows


def run(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    trade_bucket: Dict[str, List[Dict[str, Any]]] = {}
    early_bucket: Dict[str, List[Dict[str, Any]]] = {}
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
            cores = _cores(_build_mark_masks(df), wmasks, feat)
            bank = _wave_hsiao_bank(feat, wmasks, wave)
            spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
            barek = _barek_masks(df)
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            v3 = build_v3_extras(df, feat, bank, barek=barek)
            v4 = build_v4_extras(df, feat)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % 10_000
            idx = df.index

            w3 = cores["core_w3_start"].fillna(False)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            V = bank["hsiao_V"].fillna(False)
            S55 = bank["score55"].fillna(False)
            Vnear = _near(V, 3)
            bal = w3u & (Vnear | S55)
            intent = spirit["INTENT_build_soft"].fillna(False)
            turn_barek = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            t60 = v4["V4_t60_safe"].fillna(False) | v3["V3_time_align"].fillna(False)
            feat_ok = mkt.get("mkt_feat_ok", pd.Series(True, index=idx)).fillna(False)

            # —— 自由加：真史欄提早買候選（不限精神清單）——
            hammer = feat.get("is_hammer_shape")
            hammer = hammer.reindex(idx).fillna(False).astype(bool) if hammer is not None else pd.Series(False, index=idx)
            gap = feat.get("gap_breakaway_candidate")
            gap = gap.reindex(idx).fillna(False).astype(bool) if gap is not None else pd.Series(False, index=idx)
            compress = feat.get("had_ma_compression_5d")
            compress = compress.reindex(idx).fillna(False).astype(bool) if compress is not None else pd.Series(False, index=idx)
            kd_buy = feat.get("kd_pullback_buy_zone")
            kd_buy = kd_buy.reindex(idx).fillna(False).astype(bool) if kd_buy is not None else pd.Series(False, index=idx)
            immortal = bank.get("immortal", pd.Series(False, index=idx))
            immortal = immortal.reindex(idx).fillna(False).astype(bool)
            pull_n = _near(spirit["WAVE_pullbase"].fillna(False), 5)
            free_early_buy = hammer | gap | (compress & kd_buy) | immortal | pull_n

            filters = {
                "F_intent": intent,
                "F_intent_n3": _near(intent, 3),
                "F_turn_barek": turn_barek,
                "F_turn_n3": _near(turn_barek, 3),
                "F_intent_or_turn": intent | turn_barek,
                "F_t60_intent": t60 & intent,
                "F_free_early": free_early_buy,
                "F_free_or_intent": free_early_buy | intent,
                "F_w3_near_free": _near(w3, 5) & free_early_buy,
                "F_bal_intent": bal & intent,
            }
            entries = {"E_w3": w3, "E_w3u": w3u, "E_bal": bal}
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            # 提早賣代理：耗盡量／近窗 10 高觸及／假突破出場欄
            h = df["high"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            touch10 = h >= hi10.shift(1)
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            fake = feat.get("fake_breakout_exit")
            fake = fake.reindex(idx).fillna(False).astype(bool) if fake is not None else pd.Series(False, index=idx)
            early_sell = exhaust | touch10 | fake

            sell_modes = ("hi20_or_wave_top", "wave_top_next", "hi20_or_wave_or_early")

            for en, em in entries.items():
                for fn, fm in filters.items():
                    base = em & fm & risk & feat_ok
                    for mode in sell_modes:
                        key = f"{en}__{fn}__SELL_{mode}"
                        trades = _simulate_exit(
                            df,
                            base,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=key,
                            wave_top=wave_top,
                            early_sell=early_sell,
                            mode=mode,
                        )
                        trade_bucket.setdefault(key, []).extend(trades)
                        early_bucket.setdefault(key, []).extend(
                            _measure_signal_earliness(df, base, hl, sid=sid, entry_tag=key)
                        )
                        pool = w3u | w3
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=idx)
                        rnd = _random_matched(base, pool & fm, seed=seed + len(key))
                        rkey = f"random__{key}"
                        trade_bucket.setdefault(rkey, []).extend(
                            _simulate_exit(
                                df,
                                rnd,
                                hl=hl,
                                temp_label=temp,
                                sid=sid,
                                entry_tag=rkey,
                                wave_top=wave_top,
                                early_sell=early_sell,
                                mode=mode,
                            )
                        )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by = {k: _agg_trades(v) for k, v in trade_bucket.items()}
    by_early = {k: _agg_earliness(v) for k, v in early_bucket.items()}
    ranking: List[Dict[str, Any]] = []
    for key, st in by.items():
        if key.startswith("random__"):
            continue
        rnd = by.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        win = float(st.get("win_rate") or np.nan)
        exp = float(st.get("expectancy") or np.nan)
        ok = days >= 20
        beats = bool(
            ok
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        early = by_early.get(key) or {}
        hold = float(st.get("avg_hold") or st.get("mean_hold_bars") or np.nan)
        # 若 _agg_trades 無 avg_hold，自算
        if not np.isfinite(hold):
            raw_rows = trade_bucket.get(key) or []
            hb = [float(r.get("hold_bars", np.nan)) for r in raw_rows]
            hold = float(np.nanmean(hb)) if hb else float("nan")
        bars = float(early.get("mean_bars_before_hi20") or np.nan)
        # 提早綜合：勝率 × min(1,days/50) × 買提早正規化 × 賣提早（持有短加分，僅贏單）
        buy_early_score = min(1.0, bars / 25.0) if np.isfinite(bars) else 0.0
        sell_early_score = min(1.0, 15.0 / hold) if np.isfinite(hold) and hold > 0 else 0.0
        early_score = float(win) * min(1.0, days / 50.0) * (0.5 + 0.25 * buy_early_score + 0.25 * sell_early_score) if ok else float("-inf")
        ranking.append(
            {
                "key": key,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": win,
                "expectancy": exp,
                "beats_random": beats,
                "balanced_score": _bal(win, days) if ok else float("-inf"),
                "win_ge80": bool(ok and win >= 0.80),
                "days_ge30": days >= 30,
                "days_ge50": days >= 50,
                "mean_bars_before_hi20": bars,
                "mean_hold_bars": hold,
                "early_goal_score": early_score,
            }
        )

    winners = [r for r in ranking if r["beats_random"]]
    ge80 = sorted([r for r in winners if r["win_ge80"]], key=lambda r: (r["win_rate"], r["n_unique_entry_days"]), reverse=True)
    by_early_goal = sorted(winners, key=lambda r: (r.get("early_goal_score") or -9), reverse=True)
    by_buy_early = sorted(
        [r for r in winners if np.isfinite(r.get("mean_bars_before_hi20") or np.nan)],
        key=lambda r: (r["mean_bars_before_hi20"], r["win_rate"]),
        reverse=True,
    )
    gate = (
        f"early_marks_free winners={len(winners)}/{len(ranking)} ge80={len(ge80)}; "
        f"best_early={by_early_goal[0]['key'] if by_early_goal else None} "
        f"win={by_early_goal[0].get('win_rate') if by_early_goal else None} "
        f"bars={by_early_goal[0].get('mean_bars_before_hi20') if by_early_goal else None} "
        f"hold={by_early_goal[0].get('mean_hold_bars') if by_early_goal else None}; "
        f"best_win={ge80[0]['key'] if ge80 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "提早知道個股買點＋提早知道賣點；材料不夠可自由加因子",
        "never_quit_zh": "不准輕言放棄",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "by_early_goal_score": by_early_goal[:20],
        "by_buy_earliness": by_buy_early[:15],
        "extreme_win_ge80": ge80[:20],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_early_marks_free_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_early_marks_free_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_EARLY", json.dumps(by_early_goal[:5], ensure_ascii=False, default=str)[:1500], flush=True)
    return out


def main() -> None:
    run(n_universe=100)


if __name__ == "__main__":
    main()
