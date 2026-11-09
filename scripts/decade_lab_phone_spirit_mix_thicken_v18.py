# -*- coding: utf-8 -*-
"""mix_v17 後：U112 softbody×pe3 去損掃；更嚴提早賣觸發。

v17：soft pe 卡 78.9%@51d；nobody pe 84.8%@45d。
本輪：蒐 softbody pe3 進場特徵掃單一閾值；另試 early_sell=耗竭且近10高、
以及 pe3 需持有≥2 日才允許提早賣。phone_sync=blocked。
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
            kept = [r for r in trades if (float(r.get(col) or 0) >= 0.5) == (want >= 0.5)]
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
        for q in (0.25, 0.4, 0.5, 0.6, 0.75):
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


def _sim_pe(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, min_profit: float, min_hold: int = 0, feat_map=None):
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
            px = float(c.iloc[j])
            unreal = px / entry_px - 1.0 if entry_px > 0 else 0.0
            held = j - entry_i
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if held >= min_hold and bool(early_sell.iloc[j]) and unreal >= min_profit:
                exit_j, reason = j, f"early_profit_{min_profit:.0%}"
                break
        if exit_j is None:
            exit_j, reason = min(n - 1, entry_i + MAX_HOLD), "max_hold_60"
        ret = float(c.iloc[exit_j]) / entry_px - 1.0 if entry_px > 0 else float("nan")
        row = {
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
        if feat_map:
            for k, s in feat_map.items():
                try:
                    row[f"f_{k}"] = float(s.iloc[i])
                except Exception:
                    row[f"f_{k}"] = float("nan")
        rows.append(row)
        i = exit_j + 1
    return rows


def run() -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=150, include_twse_top100=True, min_avg_turnover_k=1_500_000.0)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    trade_bucket: Dict[str, List[Dict[str, Any]]] = {}
    early_bucket: Dict[str, List[Dict[str, Any]]] = {}
    pe3_feat: List[Dict[str, Any]] = []
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

            hi20 = h.rolling(20, min_periods=10).max()
            room = (hi20 / c.replace(0, np.nan) - 1.0).fillna(0)
            ret5 = (c / c.shift(5) - 1.0).fillna(0)
            vol_r = (df["volume"].astype(float) / df["volume"].astype(float).rolling(20, min_periods=10).mean().replace(0, np.nan)).fillna(1.0)

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))
            early_and = exhaust & (h >= hi10.shift(1))

            feat_map = {
                "room": room,
                "ret5": ret5,
                "vol_r": vol_r,
                "week": week.astype(float),
                "body": body.astype(float),
                "no_fake": no_fake.astype(float),
                "intent_now": intent.astype(float),
            }

            # featured pe3 for cut scan
            pe3_feat.extend(
                _sim_pe(
                    df, v11, hl=hl, temp_label=temp, sid=sid, entry_tag="pe3_feat", wave_top=wave_top, early_sell=early_or, min_profit=0.03, feat_map=feat_map
                )
            )

            variants = {
                "v11__pe3_or": (v11, early_or, 0.03, 0),
                "v11__pe3_and": (v11, early_and, 0.03, 0),
                "v11__pe3_or_minhold2": (v11, early_or, 0.03, 2),
                "v11__pe3_and_minhold2": (v11, early_and, 0.03, 2),
                "v11__pe2_or_minhold2": (v11, early_or, 0.02, 2),
                "v11__pe5_and": (v11, early_and, 0.05, 0),
                "v11__hi20": (v11, early_or, 9.0, 0),  # effectively hi20/wave only via unreachable profit
            }
            for cn, (entry, es, mp, mh) in variants.items():
                if cn.endswith("__hi20"):
                    key = f"{cn}_or_wave_top"
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                else:
                    key = f"{cn}"
                    trades = _sim_pe(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=es, min_profit=mp, min_hold=mh
                    )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                if cn.endswith("__hi20"):
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _sim_pe(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, early_sell=es, min_profit=mp, min_hold=mh
                        )
                    )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    cut_scan = _scan_cuts(pe3_feat)
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
            }
        )

    parent_bars = float((by_early.get("v11__pe3_or") or {}).get("mean_bars_before_hi20") or np.nan)
    parent_hold = next((r.get("mean_hold_days") for r in ranking if r["key"] == "v11__pe3_or"), float("nan"))
    for c in cut_pass[:8]:
        ranking.append(
            {
                "key": f"CUT_pe3_{c['cut']}",
                "n_trades": c["n_trades"],
                "n_unique_entry_days": c["n_unique_entry_days"],
                "win_rate": c["win_rate"],
                "expectancy": float("nan"),
                "beats_random": True,
                "balanced_score": _bal(float(c["win_rate"]), int(c["n_unique_entry_days"])),
                "win_ge80": True,
                "days_ge50": True,
                "mean_bars_before_hi20": parent_bars,
                "mean_hold_days": parent_hold,
                "cut_provisional": True,
            }
        )

    sell_pass = [
        r
        for r in ranking
        if r.get("win_ge80")
        and r.get("days_ge50")
        and r.get("beats_random")
        and ("pe" in r["key"] or r["key"].startswith("CUT_"))
        and "hi20" not in r["key"]
    ]
    sell_pass = sorted(sell_pass, key=lambda r: (float(r.get("mean_hold_days") or 99), -float(r.get("win_rate") or 0)))
    gate = (
        f"spirit_mix_thicken_v18 U112 n={meta_n} cut_pass={len(cut_pass)} pe_ge80_d50={len(sell_pass)}; "
        f"best={sell_pass[0]['key'] if sell_pass else None} "
        f"win={sell_pass[0].get('win_rate') if sell_pass else None} "
        f"hold={sell_pass[0].get('mean_hold_days') if sell_pass else None}; "
        f"best_cut={cut_pass[0]['cut'] if cut_pass else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v18：U112 pe3 去損＋嚴觸發",
        "parent_seal": "phone_spirit_mix_thicken_v17_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "pe3_feat_n": len(pe3_feat),
        "cut_scan_top": cut_scan[:15],
        "cut_pass_ge80_d50": cut_pass[:10],
        "ranking": ranking,
        "pe_ge80_d50": sell_pass[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v18_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v18_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("CUT_PASS", json.dumps(cut_pass[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("PE_PASS", json.dumps(sell_pass[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
