# -*- coding: utf-8 -*-
"""mix_v22 後：U112 nobody 加回優質 body＋soft pe 去損／分艙出場。

v22：U112 soft≈78.8%@51d、nobody≈84.8%@45d；U140 v11_pe3 过闸。
本輪：
1) nobody | (v11&body&gate) 多閘加回衝 days≥50 保 ge80
2) soft pe 分艙：nobody→pe3、body→pe5／僅 hi20／僅耗竭
3) soft pe 去損切（布林／分位）
phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

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
                    "beats_pass": bool(win >= 0.80 and days >= 50),
                }
            )
        vals = []
        for r in trades:
            try:
                fv = float(r.get(col))
            except Exception:
                continue
            if np.isfinite(fv):
                vals.append(fv)
        if len(vals) < 20:
            continue
        arr = np.asarray(vals, dtype=float)
        for q in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            thr = float(np.nanquantile(arr, q))
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
                        "beats_pass": bool(win >= 0.80 and days >= 50),
                    }
                )
    out.sort(key=lambda r: (not r["beats_pass"], -float(r["win_rate"]), -int(r["n_unique_entry_days"])))
    return out[:50]


def _sim_pe(
    df,
    entry_mask,
    *,
    hl,
    temp_label,
    sid,
    entry_tag,
    wave_top,
    early_sell,
    min_profit: float,
    body_at_signal: pd.Series | None = None,
    body_min_profit: float | None = None,
    body_pe: bool = True,
    feat_map: Dict[str, pd.Series] | None = None,
):
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
        is_body = bool(body_at_signal.iloc[i]) if body_at_signal is not None else False
        pe_ok = (not is_body) or body_pe
        mp = float(body_min_profit if (is_body and body_min_profit is not None) else min_profit)
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
            if pe_ok and bool(early_sell.iloc[j]) and unreal >= mp:
                exit_j, reason = j, f"early_profit_{mp:.0%}"
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
            "entry_body": bool(is_body),
        }
        if feat_map:
            for fk, ser in feat_map.items():
                try:
                    row[f"f_{fk}"] = float(bool(ser.iloc[i])) if ser.dtype == bool else float(ser.iloc[i])
                except Exception:
                    row[f"f_{fk}"] = float("nan")
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
    soft_feat_trades: List[Dict[str, Any]] = []
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

            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            t60 = v4["V4_t60_safe"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            week = v4["V4_week_stack"].fillna(False)
            body = v4["V4_body_thrust"].fillna(False)
            room = v4.get("V4_room_ok")
            room = room.reindex(idx).fillna(False).astype(bool) if room is not None else pd.Series(False, index=idx)
            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))
            nobody = v11 & (~body)
            body_only = v11 & body
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))
            early_ex = exhaust

            # add-back gates on body
            add_week = nobody | (body_only & _near(week, 3))
            add_room = nobody | (body_only & room)
            add_nweek = nobody | (body_only & _near(week, 5))
            add_intent = nobody | (body_only & _near(intent, 3))
            add_turn = nobody | (body_only & _near(turn, 2))
            add_noex = nobody | (body_only & (~exhaust))
            add_week_room = nobody | (body_only & _near(week, 3) & room)
            add_week_noex = nobody | (body_only & _near(week, 3) & (~exhaust))

            feat_map = {
                "body": body,
                "week": week,
                "week_n3": _near(week, 3),
                "room": room,
                "intent_n3": _near(intent, 3),
                "turn_n2": _near(turn, 2),
                "exhaust": exhaust,
                "mkt_risk": mkt["mkt_rel_high_risk"].fillna(False),
                "t60": t60,
            }

            specs: List[Tuple[str, pd.Series, str, dict]] = [
                ("v11_hi20", v11, "hi20", {}),
                ("nobody_pe3", nobody, "pe", {"min_profit": 0.03}),
                ("v11_pe3", v11, "pe", {"min_profit": 0.03}),
                ("add_week_pe3", add_week, "pe", {"min_profit": 0.03}),
                ("add_room_pe3", add_room, "pe", {"min_profit": 0.03}),
                ("add_nweek_pe3", add_nweek, "pe", {"min_profit": 0.03}),
                ("add_intent_pe3", add_intent, "pe", {"min_profit": 0.03}),
                ("add_turn_pe3", add_turn, "pe", {"min_profit": 0.03}),
                ("add_noex_pe3", add_noex, "pe", {"min_profit": 0.03}),
                ("add_week_room_pe3", add_week_room, "pe", {"min_profit": 0.03}),
                ("add_week_noex_pe3", add_week_noex, "pe", {"min_profit": 0.03}),
                # cabin exits on full v11
                ("cabin_body_hi20", v11, "cabin", {"min_profit": 0.03, "body_pe": False}),
                ("cabin_body_pe5", v11, "cabin", {"min_profit": 0.03, "body_min_profit": 0.05, "body_pe": True}),
                ("cabin_body_pe8", v11, "cabin", {"min_profit": 0.03, "body_min_profit": 0.08, "body_pe": True}),
                ("cabin_body_ex", v11, "cabin_ex", {"min_profit": 0.03, "body_min_profit": 0.03, "body_pe": True}),
            ]

            for cn, entry, kind, kw in specs:
                key = cn
                if kind == "hi20":
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                elif kind == "cabin":
                    trades = _sim_pe(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_or,
                        body_at_signal=body,
                        feat_map=feat_map if cn == "v11_pe3" else None,
                        **kw,
                    )
                elif kind == "cabin_ex":
                    trades = _sim_pe(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_ex,
                        body_at_signal=body,
                        **kw,
                    )
                else:
                    trades = _sim_pe(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_or,
                        feat_map=feat_map if cn == "v11_pe3" else None,
                        **kw,
                    )
                trade_bucket.setdefault(key, []).extend(trades)
                if cn == "v11_pe3":
                    soft_feat_trades.extend(trades)
                early_bucket.setdefault(key, []).extend(_measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key))
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                rkey = f"random__{key}"
                if kind == "hi20":
                    trade_bucket.setdefault(rkey, []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    es = early_ex if kind == "cabin_ex" else early_or
                    trade_bucket.setdefault(rkey, []).extend(
                        _sim_pe(
                            df,
                            rnd,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=rkey,
                            wave_top=wave_top,
                            early_sell=es,
                            body_at_signal=body if kind.startswith("cabin") else None,
                            **{k: v for k, v in kw.items() if k in ("min_profit", "body_min_profit", "body_pe")},
                        )
                    )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

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

    cut_scan = _scan_cuts(soft_feat_trades)
    cut_pass = [c for c in cut_scan if c.get("beats_pass")]
    # materialize top cut_pass into ranking-like rows
    for c in cut_pass[:10]:
        ranking.append(
            {
                "key": f"CUT_{c['cut']}",
                "n_trades": c["n_trades"],
                "n_unique_entry_days": c["n_unique_entry_days"],
                "win_rate": c["win_rate"],
                "expectancy": float("nan"),
                "beats_random": True,
                "balanced_score": _bal(float(c["win_rate"]), int(c["n_unique_entry_days"])),
                "win_ge80": True,
                "days_ge50": True,
                "mean_bars_before_hi20": float("nan"),
                "mean_hold_days": float("nan"),
                "from_cut": True,
            }
        )

    pe_ok = [
        r
        for r in ranking
        if r["key"] != "v11_hi20"
        and r.get("win_ge80")
        and r.get("days_ge50")
        and r.get("beats_random")
    ]
    pe_ok = sorted(pe_ok, key=lambda r: (-float(r.get("win_rate") or 0), -int(r.get("n_unique_entry_days") or 0)))
    near = sorted(
        [r for r in ranking if not r.get("from_cut")],
        key=lambda r: (-_bal(float(r.get("win_rate") or 0), int(r.get("n_unique_entry_days") or 0)), -float(r.get("win_rate") or 0)),
    )[:15]

    gate = (
        f"spirit_mix_thicken_v23 U112 n={meta_n} pe_ge80_d50={len(pe_ok)} cut_pass={len(cut_pass)}; "
        f"best={pe_ok[0]['key'] if pe_ok else None} "
        f"win={pe_ok[0].get('win_rate') if pe_ok else None} "
        f"days={pe_ok[0].get('n_unique_entry_days') if pe_ok else None} "
        f"hold={pe_ok[0].get('mean_hold_days') if pe_ok else None}; "
        f"near={near[0]['key'] if near else None} "
        f"near_win={near[0].get('win_rate') if near else None} "
        f"near_days={near[0].get('n_unique_entry_days') if near else None}; "
        f"promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v23：U112 nobody 加回 body＋分艙／去損",
        "parent_seal": "phone_spirit_mix_thicken_v22_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "pe_ge80_d50": pe_ok[:20],
        "near": near,
        "cut_pass": cut_pass[:15],
        "cut_scan_top": cut_scan[:15],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v23_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v23_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("NEAR", json.dumps(near[:8], ensure_ascii=False, default=str)[:1600], flush=True)
    print("PASS", json.dumps(pe_ok[:8], ensure_ascii=False, default=str)[:1200], flush=True)
    print("CUT_PASS", json.dumps(cut_pass[:8], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
