# -*- coding: utf-8 -*-
"""mix_v56 keep；本輪 turn_n2 days 加厚＋intent_pri5 ge80 回收，救 earlier×ge80×50d >16.26，救 earlier×ge80×beats bars>15.94。

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
PARENT_BARS = 16.26  # v40/v41 買鎖
PARENT_HOLD = 8.901960784313726


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def run(*, n_stocks: int = 180) -> Dict[str, Any]:
    t0 = time.time()
    # select_g_universe 回 DataFrame（stock_id 欄），不准當 dict.get("symbols")
    uni = select_g_universe(
        n=max(150, int(n_stocks)),
        include_twse_top100=True,
        min_avg_turnover_k=1_500_000.0,
    )
    symbols: List[str] = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        sid_s = str(sid)
        if sid_s not in symbols:
            symbols.append(sid_s)
    # U112 目標：必測先留，再補到 n_stocks
    must = [str(s) for s in MUST_INCLUDE]
    rest = [s for s in symbols if s not in must]
    symbols = must + rest
    symbols = symbols[: max(int(n_stocks), len(must))]
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    trade_bucket: Dict[str, list] = {}
    early_bucket: Dict[str, list] = {}
    errors: List[str] = []
    meta_n = 0

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if raw is None or len(raw) < 150:
                continue
            # 與 v38 同口：df＝小寫 OHLC；feat／wave 另吃 prepare_ohlcv(raw)
            df = _normalize_ohlc(raw)
            if df is None or len(df) < 150:
                continue
            meta_n += 1
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
            idx = df.index
            seed = abs(hash(sid)) % 10_000

            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            t60 = v4["V4_t60_safe"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            week = v4["V4_week_stack"].fillna(False)
            body = v4["V4_body_thrust"].fillna(False)
            no_fake = v4["V4_no_fake_break"].fillna(False)
            bull = (df["close"].astype(float) > df["open"].astype(float)).fillna(False)
            room = v4.get("V4_room_ok", pd.Series(True, index=idx)).reindex(idx).fillna(True)

            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            ei_n6 = w3u & _near(turn, 3) & t60 & _near(intent, 6) & risk
            ei_n4 = w3u & _near(turn, 3) & t60 & _near(intent, 4) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))

            ei_n7 = w3u & _near(turn, 3) & t60 & _near(intent, 7) & risk
            ei_n8 = w3u & _near(turn, 3) & t60 & _near(intent, 8) & risk
            body_n5 = ei_n5 & (_near(week, 3) | _near(body, 5))
            parent = (ei_n6 & (_near(week, 3) | _near(body, 3))) & room
            b5r = (ei_n6 & (_near(week, 3) | _near(body, 5))) & room
            b4r = (ei_n6 & (_near(week, 3) | _near(body, 4))) & room
            b6r = (ei_n6 & (_near(week, 3) | _near(body, 6))) & room
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            # 結構精準：不破昨低、或創昨高（只砍疑敗筆）
            hold_yl = (low >= low.shift(1)).fillna(False)
            hh = (high > high.shift(1)).fillna(False)
            hold_or_hh = hold_yl | hh
            # room-soft：近3日 room 曾成立即可（放寬當日 room）
            room_soft = _near(room.fillna(False), 3)
            parent_soft = (ei_n6 & (_near(week, 3) | _near(body, 3))) & room_soft
            n7_room = (ei_n7 & (_near(week, 3) | _near(body, 3))) & room
            n7_soft = (ei_n7 & (_near(week, 3) | _near(body, 3))) & room_soft
            n7_b5 = (ei_n7 & (_near(week, 3) | _near(body, 5))) & room
            n7_b5_soft = (ei_n7 & (_near(week, 3) | _near(body, 5))) & room_soft
            n8_room = (ei_n8 & (_near(week, 3) | _near(body, 3))) & room
            # v51：拿掉 room／縮 turn 窗／intent 當主鎖，試更早進
            ei_n6_noroom = ei_n6 & (_near(week, 3) | _near(body, 3))
            ei_n5_noroom = v11  # ei_n5 & (week|body n3)
            turn_n2 = w3u & _near(turn, 2) & t60 & _near(intent, 6) & risk
            turn2_wb = turn_n2 & (_near(week, 3) | _near(body, 3))
            turn2_room = turn2_wb & room
            intent_pri = w3u & t60 & _near(intent, 4) & risk & (_near(week, 3) | _near(body, 3))
            intent_pri_room = intent_pri & room
            intent_pri_turn = intent_pri & _near(turn, 3)
            intent_pri3 = w3u & t60 & _near(intent, 3) & risk & (_near(week, 3) | _near(body, 3))
            intent_pri5 = w3u & t60 & _near(intent, 5) & risk & (_near(week, 3) | _near(body, 3))
            intent_pri3_room = intent_pri3 & room
            intent_pri5_room = intent_pri5 & room
            # v53：intent_pri5 近失（earlier但win<80）→ ge80 回收；turn_n2 earlier但days<50 → 加厚
            intent_pri5_hold = intent_pri5 & hold_yl
            intent_pri5_nofake = intent_pri5 & _near(no_fake, 3)
            intent_pri5_bull = intent_pri5 & bull
            intent_pri5_hold_nofake = intent_pri5 & hold_yl & _near(no_fake, 3)
            intent_pri5_room_hold = intent_pri5_room & hold_yl
            intent_pri2 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 3) | _near(body, 3))
            intent_pri2_room = intent_pri2 & room
            intent_pri6 = w3u & t60 & _near(intent, 6) & risk & (_near(week, 3) | _near(body, 3))
            intent_pri6_hold = intent_pri6 & hold_yl
            turn_n2_hold = turn2_wb & hold_yl
            turn_n2_nofake = turn2_wb & _near(no_fake, 3)
            turn_n2_soft = turn2_wb & room_soft
            turn_n2_body5 = turn_n2 & (_near(week, 3) | _near(body, 5))
            turn_n1 = w3u & _near(turn, 1) & t60 & _near(intent, 6) & risk
            turn_n1_wb = turn_n1 & (_near(week, 3) | _near(body, 3))
            parent_or_ip5 = parent | intent_pri5
            parent_or_ip5_hold = parent | intent_pri5_hold
            parent_or_turn2_hold = parent | turn_n2_hold
            # v54：intent_pri2 近失（ge80／earlier／days=46）→ 加厚 days
            intent_pri2_soft = intent_pri2 & room_soft
            intent_pri2_wb5 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 5) | _near(body, 5))
            intent_pri2_wb4 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 4) | _near(body, 4))
            intent_pri2_body5 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 3) | _near(body, 5))
            intent_pri2_week5 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 5) | _near(body, 3))
            intent_pri2_or_pri3 = intent_pri2 | intent_pri3
            intent_pri2_or_pri = intent_pri2 | intent_pri
            intent_pri2_turn = intent_pri2 & _near(turn, 3)
            intent_pri2_turn2 = intent_pri2 & _near(turn, 2)
            intent_pri2_nofake = intent_pri2 & _near(no_fake, 3)
            intent_pri2_wb5_room = intent_pri2_wb5 & room
            intent_pri2_wb4_room = intent_pri2_wb4 & room
            # 微放寬 intent 窗：n=2 或近鄰日 intent
            intent_pri2_near = w3u & t60 & _near(intent, 2) & risk & (_near(week, 3) | _near(body, 3))
            # 同形但 intent 近窗用 fill 已是 _near(intent,2)；再試 week|body 任一近5
            intent_loose2 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 5) | _near(body, 5) | room_soft)
            parent_or_ip2 = parent | intent_pri2
            parent_or_ip2_wb5 = parent | intent_pri2_wb5
            # v55：days=46→50 軟橋——pri2 為核，稀疏補 pri3／pri 日，盡量保 earlier
            ip2_or_pri3_soft = intent_pri2 | (intent_pri3 & room_soft)
            ip2_or_pri_soft = intent_pri2 | (intent_pri & room_soft)
            ip2_wb5_or_pri3 = intent_pri2_wb5 | intent_pri3
            ip2_week7 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 7) | _near(body, 5))
            ip2_body7 = w3u & t60 & _near(intent, 2) & risk & (_near(week, 5) | _near(body, 7))
            ip2_intent3 = w3u & t60 & _near(intent, 3) & risk & (_near(week, 5) | _near(body, 5))
            # 隔日補：pri2 當日或次日 pri3（用 near 模擬）
            ip2_bridge = intent_pri2 | (_near(intent_pri3, 2) & t60 & risk)
            ip2_bridge_room = ip2_bridge & room
            ip2_or_turn2_soft = intent_pri2 | (turn2_wb & room_soft)
            # v56：turn_n2 earlier但days<50 → 放寬 week/body；ip5 earlier但wr<80 → 輕濾
            turn_n3 = w3u & _near(turn, 3) & t60 & _near(intent, 6) & risk
            turn_n3_wb5 = turn_n3 & (_near(week, 5) | _near(body, 5))
            turn_n2_wb7 = turn_n2 & (_near(week, 7) | _near(body, 5))
            turn_n2_or_ip2 = turn2_wb | intent_pri2
            turn_n2_or_ip3 = turn2_wb | intent_pri3
            ip5_or_ip3 = intent_pri5 | intent_pri3
            ip5_soft_ge = intent_pri5 & (_near(no_fake, 5) | hold_yl | bull)
            cores_entry = {
                # 复現買鎖
                "ei_n6_and_room": parent,
                "ei_n4_and_room": (ei_n4 & (_near(week, 3) | _near(body, 3))) & room,
                "ei_n4_body_n5_room": (ei_n4 & (_near(week, 3) | _near(body, 5))) & room,
                # v51 earlier 軸
                "ei_n6_noroom": ei_n6_noroom,
                "ei_n5_noroom": ei_n5_noroom,
                "ei_n6_noroom_soft": ei_n6_noroom & room_soft,  # soft only
                "turn_n2_wb": turn2_wb,
                "turn_n2_room": turn2_room,
                "intent_pri": intent_pri,
                "intent_pri_room": intent_pri_room,
                "intent_pri_turn": intent_pri_turn,
                "intent_pri3": intent_pri3,
                "intent_pri5": intent_pri5,
                "intent_pri3_room": intent_pri3_room,
                "intent_pri5_room": intent_pri5_room,
                "intent_pri5_hold": intent_pri5_hold,
                "intent_pri5_nofake": intent_pri5_nofake,
                "intent_pri5_bull": intent_pri5_bull,
                "intent_pri5_hold_nofake": intent_pri5_hold_nofake,
                "intent_pri5_room_hold": intent_pri5_room_hold,
                "intent_pri2": intent_pri2,
                "intent_pri2_room": intent_pri2_room,
                "intent_pri2_soft": intent_pri2_soft,
                "intent_pri2_wb5": intent_pri2_wb5,
                "intent_pri2_wb4": intent_pri2_wb4,
                "intent_pri2_body5": intent_pri2_body5,
                "intent_pri2_week5": intent_pri2_week5,
                "intent_pri2_or_pri3": intent_pri2_or_pri3,
                "intent_pri2_or_pri": intent_pri2_or_pri,
                "intent_pri2_turn": intent_pri2_turn,
                "intent_pri2_turn2": intent_pri2_turn2,
                "intent_pri2_nofake": intent_pri2_nofake,
                "intent_pri2_wb5_room": intent_pri2_wb5_room,
                "intent_pri2_wb4_room": intent_pri2_wb4_room,
                "intent_loose2": intent_loose2,
                "parent_or_ip2": parent_or_ip2,
                "parent_or_ip2_wb5": parent_or_ip2_wb5,
                "ip2_or_pri3_soft": ip2_or_pri3_soft,
                "ip2_or_pri_soft": ip2_or_pri_soft,
                "ip2_wb5_or_pri3": ip2_wb5_or_pri3,
                "ip2_week7": ip2_week7,
                "ip2_body7": ip2_body7,
                "ip2_intent3": ip2_intent3,
                "ip2_bridge": ip2_bridge,
                "ip2_bridge_room": ip2_bridge_room,
                "ip2_or_turn2_soft": ip2_or_turn2_soft,
                "turn_n3_wb5": turn_n3_wb5,
                "turn_n2_wb7": turn_n2_wb7,
                "turn_n2_or_ip2": turn_n2_or_ip2,
                "turn_n2_or_ip3": turn_n2_or_ip3,
                "ip5_or_ip3": ip5_or_ip3,
                "ip5_soft_ge": ip5_soft_ge,
                "intent_pri6": intent_pri6,
                "intent_pri6_hold": intent_pri6_hold,
                "turn_n2_hold": turn_n2_hold,
                "turn_n2_nofake": turn_n2_nofake,
                "turn_n2_soft": turn_n2_soft,
                "turn_n2_body5": turn_n2_body5,
                "turn_n1_wb": turn_n1_wb,
                "parent_or_ip5": parent_or_ip5,
                "parent_or_ip5_hold": parent_or_ip5_hold,
                "parent_or_turn2_hold": parent_or_turn2_hold,
                "parent_or_noroom": parent | ei_n6_noroom,
                "parent_or_intent_pri": parent | intent_pri,
                "parent_or_turn2": parent | turn2_wb,
                # 近失本體
                "ei_n6_body_n5_room": b5r,
                "ei_n7_body_n5_room": n7_b5,
                "ei_n7_and_room": n7_room,
                # ge80 回收：結構／假突破／陽線
                "n7_b5_hold_yl": n7_b5 & hold_yl,
                "n7_b5_hh": n7_b5 & hh,
                "n7_b5_hold_or_hh": n7_b5 & hold_or_hh,
                "n7_b5_nofake": n7_b5 & _near(no_fake, 3),
                "n7_b5_hold_nofake": n7_b5 & hold_yl & _near(no_fake, 3),
                "n7_b5_bull": n7_b5 & bull,
                "n7_b5_bull_hold": n7_b5 & bull & hold_yl,
                "n6_b5_hold_yl": b5r & hold_yl,
                "n6_b5_nofake": b5r & _near(no_fake, 3),
                "n6_b5_hold_nofake": b5r & hold_yl & _near(no_fake, 3),
                "n6_b5_bull_hold": b5r & bull & hold_yl,
                # 軟 OR：父鎖 ∪ 回收近失
                "parent_or_n7_b5_hold": parent | (n7_b5 & hold_yl),
                "parent_or_n6_b5_nofake": parent | (b5r & _near(no_fake, 3)),
                "n7_room_or_n7_b5_hold": n7_room | (n7_b5 & hold_yl),
            }
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)

            for cn, entry in cores_entry.items():
                key = f"{cn}__SELL_hi20_or_wave_top"
                trades = _simulate_relhigh(
                    df,
                    entry,
                    hl=hl,
                    temp_label=temp,
                    sid=sid,
                    entry_tag=key,
                    wave_top=wave_top,
                    mode="hi20_or_wave_top",
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
                        df,
                        rnd,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=rkey,
                        wave_top=wave_top,
                        mode="hi20_or_wave_top",
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

    confirm = next((r for r in ranking if r["key"] == "ei_n6_and_room__SELL_hi20_or_wave_top"), None)
    pe_ok = [
        r
        for r in ranking
        if r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    pe_ok = sorted(pe_ok, key=lambda r: (-float(r.get("mean_bars_before_hi20") or -1), -float(r.get("win_rate") or 0)))
    earlier = [r for r in pe_ok if r.get("earlier_than_parent")]
    gate = (
        f"spirit_mix_thicken_v56 U180 n={meta_n} confirm_parent="
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
        "user_goal_zh": "v56：turn_n2 days＋ip5 ge80 earlier>16.26",
        "parent_seal": "phone_spirit_mix_thicken_v56_decision.json",
        "sell_lock_key": "pe2_mh20_vdry_gb15",
        "sell_lock_hold": PARENT_HOLD,
        "parent_bars": PARENT_BARS,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "confirm_buy": confirm,
        "ranking": ranking,
        "buy_ge80_d50": pe_ok[:12],
        "earlier_ok": earlier[:8],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v56_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v56_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("CONFIRM", json.dumps(confirm, ensure_ascii=False, default=str)[:700], flush=True)
    print("EARLIER", json.dumps(earlier[:6], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
