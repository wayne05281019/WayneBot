# -*- coding: utf-8 -*-
"""mix_v38 後：賣 gb15 hold 平台≈8.90；本輪改買側 bars>15.86 且 ge80×50d。

phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
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
PARENT_BARS = 15.854166666666666
PARENT_HOLD = 8.901960784313726


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def run(*, n_stocks: int = 112) -> Dict[str, Any]:
    t0 = time.time()
    u = select_g_universe(n=n_stocks, must_include=MUST_INCLUDE)
    meta_n = int(u.get("n") or len(u.get("symbols") or []))
    symbols: List[str] = list(u.get("symbols") or [])
    seed = 39039
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    trade_bucket: Dict[str, list] = {}
    early_bucket: Dict[str, list] = {}
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if raw is None or len(raw) < 80:
                continue
            df = prepare_ohlcv(_normalize_ohlc(raw))
            if df is None or len(df) < 80:
                continue
            feat = compute_hsiao_features(df)
            hl, temp = _build_hl_temp(df)
            idx = df.index
            marks = _build_mark_masks(df, feat)
            spirit = build_spirit_masks(df, feat)
            v3 = build_v3_extras(df, feat)
            v4 = build_v4_extras(df, feat)
            cores = _cores(df, feat, marks)
            wpack = _wave_frame(df)
            wmasks = _wave_masks(wpack)
            w3u = wmasks.get("w3_up", pd.Series(False, index=idx)).reindex(idx).fillna(False)
            turn = spirit.get("turn_up", pd.Series(False, index=idx)).reindex(idx).fillna(False)
            intent = spirit.get("intent_buy", pd.Series(False, index=idx)).reindex(idx).fillna(False)
            risk = (~spirit.get("risk_off", pd.Series(False, index=idx)).reindex(idx).fillna(False)).fillna(True)
            t60 = cores.get("t60", pd.Series(True, index=idx)).reindex(idx).fillna(True)
            week = v3.get("V3_weekly_turn", pd.Series(False, index=idx)).reindex(idx).fillna(False)
            body = v4["V4_body_thrust"].fillna(False)
            no_fake = v4["V4_no_fake_break"].fillna(False)
            bull = (df["close"].astype(float) > df["open"].astype(float)).fillna(False)
            room = v4.get("V4_room_ok", pd.Series(True, index=idx)).reindex(idx).fillna(True)

            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            ei_n6 = w3u & _near(turn, 3) & t60 & _near(intent, 6) & risk
            ei_n4 = w3u & _near(turn, 3) & t60 & _near(intent, 4) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))

            cores_entry = {
                "v11_week_n3_softbody": v11,
                "v11_week_n2_softbody": ei_n5 & (_near(week, 2) | _near(body, 3)),
                "v11_week_n3_body_n5": ei_n5 & (_near(week, 3) | _near(body, 5)),
                "v11_week_n2_body_n5": ei_n5 & (_near(week, 2) | _near(body, 5)),
                "v11_week_n1_softbody": ei_n5 & (_near(week, 1) | _near(body, 3)),
                "v11_week_n3_body_n7": ei_n5 & (_near(week, 3) | _near(body, 7)),
                "ei_n6_week_n3_softbody": ei_n6 & (_near(week, 3) | _near(body, 3)),
                "ei_n4_week_n3_softbody": ei_n4 & (_near(week, 3) | _near(body, 3)),
                "v11_plus_nofake_or": ei_n5 & (_near(week, 3) | _near(body, 3) | _near(no_fake, 3)),
                "v11_plus_bull_or": ei_n5 & (_near(week, 3) | _near(body, 3) | _near(bull, 2)),
                "v11_room": v11 & room,
                "ei_n5_week_n3_or_bull": ei_n5 & (_near(week, 3) | _near(bull, 2)),
                "ei_n5_body_n3_or_bull": ei_n5 & (_near(body, 3) | _near(bull, 2)),
            }
            wave_top = (
                spirit.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | spirit.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | spirit.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            # stock wave events fallback
            try:
                ev = _stock_wave_events(df)
                wave_top = (
                    wave_top
                    | ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                    | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                    | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
                ).fillna(False)
            except Exception:
                pass

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
                rkey = f"random__{key}"
                trade_bucket.setdefault(rkey, []).extend(
                    _simulate_relhigh(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
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
                "earlier_than_parent": bool(np.isfinite(bars) and bars > PARENT_BARS + 0.05),
            }
        )

    confirm = next((r for r in ranking if r["key"] == "v11_week_n3_softbody__SELL_hi20_or_wave_top"), None)
    pe_ok = [
        r
        for r in ranking
        if r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    pe_ok = sorted(pe_ok, key=lambda r: (-float(r.get("mean_bars_before_hi20") or -1), -float(r.get("win_rate") or 0)))
    earlier = [r for r in pe_ok if r.get("earlier_than_parent")]
    gate = (
        f"spirit_mix_thicken_v39 U112 n={meta_n} confirm_v11="
        f"{bool(confirm and confirm.get('win_ge80') and confirm.get('days_ge50') and confirm.get('beats_random'))} "
        f"confirm_bars={confirm.get('mean_bars_before_hi20') if confirm else None}; "
        f"buy_ge80_d50={len(pe_ok)} earlier={len(earlier)}; "
        f"best_early={earlier[0]['key'] if earlier else None} "
        f"bars={earlier[0].get('mean_bars_before_hi20') if earlier else None}; "
        f"sell_lock=pe2_mh20_vdry_gb15 hold={PARENT_HOLD}; promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v39：买侧 bars>15.86；卖锁 gb15 维持",
        "parent_seal": "phone_spirit_mix_thicken_v38_decision.json",
        "sell_lock_key": "pe2_mh20_vdry_gb15",
        "sell_lock_hold": PARENT_HOLD,
        "parent_bars": PARENT_BARS,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "confirm_v11_buy": confirm,
        "ranking": ranking,
        "buy_ge80_d50": pe_ok[:12],
        "earlier_ok": earlier[:8],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v39_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v39_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("CONFIRM", json.dumps(confirm, ensure_ascii=False, default=str)[:700], flush=True)
    print("EARLIER", json.dumps(earlier[:6], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
