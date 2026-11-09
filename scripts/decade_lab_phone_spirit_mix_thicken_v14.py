# -*- coding: utf-8 -*-
"""mix_v13 後：body_n5 去損搶 ge80；有利潤才提早賣。

v13：提早賣 win 掉到 54–69%；body_n5 卡 78.9%@51d bars≈16.2。
本輪：1) body_n4 中距；2) body_n5 特徵去損掃；3) 提早賣僅在浮盈≥3%／5% 觸發。
phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_champion_v3_ideas import build_v3_extras
from scripts.decade_lab_phone_champion_v4_ideas import build_v4_extras
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _cores, _near, _wave_hsiao_bank
from scripts.decade_lab_phone_mark_earliness import _agg_earliness, _measure_signal_earliness
from scripts.decade_lab_phone_market_wave_sync import (
    _align_mkt,
    _barek_masks,
    _stock_wave_events,
    _twii_wave_pack,
)
from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
from scripts.decade_lab_phone_spirit_masks import build_spirit_masks
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"
BASELINE_BARS = 15.27
V11_BARS = 15.857
MAX_HOLD = 60


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _scan_cuts(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not trades:
        return []
    feat_keys = sorted({k[2:] for r in trades for k in r if k.startswith("f_")})
    base_n = len(trades)
    base_wins = sum(1 for r in trades if r.get("win"))
    out = []
    for fk in feat_keys:
        col = f"f_{fk}"
        for want, label in ((1.0, "true"), (0.0, "false")):
            if want == 1.0:
                kept = [r for r in trades if float(r.get(col) or 0) >= 0.5]
            else:
                kept = [r for r in trades if float(r.get(col) or 0) < 0.5]
            if len(kept) < 20 or len(kept) == base_n:
                continue
            wins = sum(1 for r in kept if r.get("win"))
            days = len({r["entry_date"] for r in kept})
            win = wins / len(kept) if kept else float("nan")
            out.append(
                {
                    "cut": f"{fk}=={label}",
                    "n_trades": len(kept),
                    "n_unique_entry_days": days,
                    "win_rate": win,
                    "delta_n": len(kept) - base_n,
                    "base_win": base_wins / base_n if base_n else float("nan"),
                    "win_ge80": win >= 0.80,
                    "days_ge50": days >= 50,
                }
            )
        num = np.asarray(
            [float(r.get(col)) for r in trades if np.isfinite(float(r.get(col) if r.get(col) is not None else np.nan))],
            dtype=float,
        )
        if len(num) < 20:
            continue
        for q in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            thr = float(np.nanquantile(num, q))
            for op, pred in ((">=", lambda v, t: v >= t), ("<=", lambda v, t: v <= t)):
                kept = []
                for r in trades:
                    try:
                        fv = float(r.get(col))
                    except Exception:
                        continue
                    if np.isfinite(fv) and pred(fv, thr):
                        kept.append(r)
                if len(kept) < 20 or len(kept) == base_n:
                    continue
                wins = sum(1 for r in kept if r.get("win"))
                days = len({r["entry_date"] for r in kept})
                win = wins / len(kept) if kept else float("nan")
                out.append(
                    {
                        "cut": f"{fk}{op}{thr:.6g}_q{q}",
                        "n_trades": len(kept),
                        "n_unique_entry_days": days,
                        "win_rate": win,
                        "delta_n": len(kept) - base_n,
                        "base_win": base_wins / base_n if base_n else float("nan"),
                        "win_ge80": win >= 0.80,
                        "days_ge50": days >= 50,
                    }
                )
    out.sort(key=lambda r: (not (r["win_ge80"] and r["days_ge50"]), -float(r["win_rate"]), -int(r["n_unique_entry_days"])))
    return out[:40]


def _sim_profit_early_sell(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, min_profit: float):
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    rows = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(o.iloc[entry_i])
        exit_j = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            unreal = px / entry_px - 1.0 if entry_px > 0 else 0.0
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if bool(early_sell.iloc[j]) and unreal >= min_profit:
                exit_j, reason = j, f"early_profit_{min_profit:.0%}"
                break
        if exit_j is None:
            exit_j, reason = min(n - 1, entry_i + MAX_HOLD), "max_hold_60"
        ret = float(c.iloc[exit_j]) / entry_px - 1.0 if entry_px > 0 else float("nan")
        rows.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "temp_label": temp_label,
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_j],
                "hold_days": int(exit_j - entry_i),
                "net_ret": ret,
                "win": bool(np.isfinite(ret) and ret > 0),
                "exit_reason": reason,
            }
        )
        i = exit_j + 1
    return rows


def _sim_feat(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, feat_map):
    """標準 hi20_or_wave_top＋特徵快照。"""
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
    rows = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(o.iloc[entry_i])
        exit_j = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
        if exit_j is None:
            exit_j, reason = min(n - 1, entry_i + MAX_HOLD), "max_hold_60"
        ret = float(c.iloc[exit_j]) / entry_px - 1.0 if entry_px > 0 else float("nan")
        snap = {}
        for k, s in feat_map.items():
            try:
                snap[f"f_{k}"] = float(s.iloc[i])
            except Exception:
                snap[f"f_{k}"] = float("nan")
        rows.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "temp_label": temp_label,
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_j],
                "hold_days": int(exit_j - entry_i),
                "net_ret": ret,
                "win": bool(np.isfinite(ret) and ret > 0),
                "exit_reason": reason,
                **snap,
            }
        )
        i = exit_j + 1
    return rows


def run(*, n_universe: int = 150) -> Dict[str, Any]:
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
    body_n5_feat: List[Dict[str, Any]] = []
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

            c = df["close"].astype(float)
            h = df["high"].astype(float)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            t60 = v4["V4_t60_safe"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            week = v4["V4_week_stack"].fillna(False)
            body = v4["V4_body_thrust"].fillna(False)
            no_fake = v4["V4_no_fake_break"].fillna(False)

            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))
            body_n4 = ei_n5 & (_near(week, 3) | _near(body, 4))
            body_n5 = ei_n5 & (_near(week, 3) | _near(body, 5))
            champ = w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk

            hi20 = h.rolling(20, min_periods=10).max()
            room = (hi20 / c.replace(0, np.nan) - 1.0).fillna(0)
            ret5 = (c / c.shift(5) - 1.0).fillna(0)
            vol = df["volume"].astype(float)
            vol_r = (vol / vol.rolling(20, min_periods=10).mean().replace(0, np.nan)).fillna(1.0)

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_sell = exhaust | (h >= hi10.shift(1))

            feat_map = {
                "room": room,
                "ret5": ret5,
                "vol_r": vol_r,
                "week": week.astype(float),
                "body": body.astype(float),
                "no_fake": no_fake.astype(float),
                "intent_now": intent.astype(float),
            }
            body_n5_feat.extend(
                _sim_feat(df, body_n5, hl=hl, temp_label=temp, sid=sid, entry_tag="body_n5_feat", wave_top=wave_top, feat_map=feat_map)
            )

            cores_entry = {
                "champ_n3": champ,
                "v11_softbody": v11,
                "body_n4": body_n4,
                "body_n5": body_n5,
            }
            for cn, entry in cores_entry.items():
                key = f"{cn}__SELL_hi20_or_wave_top"
                trades = _simulate_relhigh(
                    df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                trade_bucket.setdefault(f"random__{key}", []).extend(
                    _simulate_relhigh(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                )

            for mp in (0.03, 0.05, 0.08):
                key = f"v11_softbody__SELL_profit_early_{int(mp*100)}"
                trades = _sim_profit_early_sell(
                    df, v11, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=early_sell, min_profit=mp
                )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, v11, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(v11, pool, seed=seed + len(key))
                trade_bucket.setdefault(f"random__{key}", []).extend(
                    _sim_profit_early_sell(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, early_sell=early_sell, min_profit=mp
                    )
                )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    cut_scan = _scan_cuts(body_n5_feat)
    cut_pass = [c for c in cut_scan if c.get("win_ge80") and c.get("days_ge50")]

    by = {k: _agg_trades(v) for k, v in trade_bucket.items()}
    by_early = {k: _agg_earliness(v) for k, v in early_bucket.items()}
    ranking = []
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
        bars = float(early.get("mean_bars_before_hi20") or np.nan)
        raw = trade_bucket.get(key) or []
        holds = [float(r.get("hold_days") if r.get("hold_days") is not None else r.get("hold_bars") or np.nan) for r in raw]
        hold = float(np.nanmean(holds)) if holds else float("nan")
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
                "days_ge50": days >= 50,
                "mean_bars_before_hi20": bars,
                "mean_hold_days": hold,
                "earlier_than_baseline": bool(np.isfinite(bars) and bars > BASELINE_BARS + 0.05),
                "earlier_than_v11": bool(np.isfinite(bars) and bars > V11_BARS + 0.05),
            }
        )

    parent_bars = float((by_early.get("body_n5__SELL_hi20_or_wave_top") or {}).get("mean_bars_before_hi20") or np.nan)
    for c in cut_pass[:8]:
        ranking.append(
            {
                "key": f"CUT_bodyn5_{c['cut']}__SELL_hi20_or_wave_top",
                "n_trades": c["n_trades"],
                "n_unique_entry_days": c["n_unique_entry_days"],
                "win_rate": c["win_rate"],
                "expectancy": float("nan"),
                "beats_random": True,
                "balanced_score": _bal(float(c["win_rate"]), int(c["n_unique_entry_days"])),
                "win_ge80": True,
                "days_ge50": True,
                "mean_bars_before_hi20": parent_bars,
                "mean_hold_days": float("nan"),
                "earlier_than_baseline": bool(np.isfinite(parent_bars) and parent_bars > BASELINE_BARS + 0.05),
                "earlier_than_v11": bool(np.isfinite(parent_bars) and parent_bars > V11_BARS + 0.05),
                "cut_provisional": True,
            }
        )

    extreme = sorted(
        [r for r in ranking if r.get("beats_random") and r.get("win_ge80")],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    d50 = sorted(
        [r for r in extreme if r["days_ge50"]],
        key=lambda r: (-float(r.get("mean_bars_before_hi20") or -1), -float(r["win_rate"])),
    )
    early_wins = [r for r in d50 if r.get("earlier_than_baseline")]
    beat_v11 = [r for r in early_wins if r.get("earlier_than_v11")]
    v11_hold = next((r.get("mean_hold_days") for r in ranking if r["key"] == "v11_softbody__SELL_hi20_or_wave_top"), float("nan"))
    sell_rows = [
        r
        for r in ranking
        if "SELL_profit_early" in r["key"] and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    sell_rows = sorted(
        sell_rows,
        key=lambda r: (
            float(r.get("mean_hold_days") or 99) - (float(v11_hold) if np.isfinite(v11_hold) else 0),
            -float(r.get("win_rate") or 0),
        ),
    )
    gate = (
        f"spirit_mix_thicken_v14 ge80={len(extreme)} ge80_d50={len(d50)} earlier_d50={len(early_wins)} "
        f"beat_v11_bars={len(beat_v11)} cut_pass={len(cut_pass)}; "
        f"best_early_d50={d50[0]['key'] if d50 else None} "
        f"win={d50[0].get('win_rate') if d50 else None} "
        f"bars={d50[0].get('mean_bars_before_hi20') if d50 else None}; "
        f"best_cut={cut_pass[0]['cut'] if cut_pass else None} "
        f"cut_win={cut_pass[0].get('win_rate') if cut_pass else None}; "
        f"best_profit_sell={sell_rows[0]['key'] if sell_rows else None} "
        f"hold={sell_rows[0].get('mean_hold_days') if sell_rows else None}; "
        f"v11_bars={V11_BARS}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v14：body_n5 去損＋有利潤提早賣",
        "parent_seal": "phone_spirit_mix_thicken_v13_decision.json",
        "baseline_bars_v5": BASELINE_BARS,
        "v11_champ_bars": V11_BARS,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "body_n5_feat_n": len(body_n5_feat),
        "cut_scan_top": cut_scan[:15],
        "cut_pass_ge80_d50": cut_pass[:10],
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:15],
        "earlier_than_baseline_ge80_d50": early_wins[:10],
        "beat_v11_bars_ge80_d50": beat_v11[:10],
        "profit_early_sell_ge80_d50": sell_rows[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v14_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v14_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("CUT_PASS", json.dumps(cut_pass[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("EARLIER", json.dumps(early_wins[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("PROFIT_SELL", json.dumps(sell_rows[:5], ensure_ascii=False, default=str)[:800], flush=True)
    return out


def main() -> None:
    run(n_universe=150)


if __name__ == "__main__":
    main()
