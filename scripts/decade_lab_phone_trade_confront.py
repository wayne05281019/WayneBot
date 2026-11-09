# -*- coding: utf-8 -*-
"""話筒對齊對質：進場＋出場整段（雲端實驗室；不上話筒）。

先前只測「標到後 5 日漲不漲」對你幫助有限。這裡改測：
- 進場＝話筒真認的買訊（leave_zero／ma60_lower）＋對照（生紅箭／同密度隨機）
- 出場＝可轉符號的規則：首碰 20高（出場提示）／如何賣不同步直接減碼／峰值回吐 8%／最多抱 60 日
- 指標＝整段報酬、勝率、平均持有、期望值、MFE／MAE；對 leave_zero 現況比輸贏
- 過閘才談查股加符號；本腳本只落實驗室結論
- 資料＝各檔真實最長窗；來源寫 attrs；不准捏柱
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
FRICTION = 0.003  # 來回粗估（證交稅＋手續費量級）；只用於 net
MAX_HOLD = 60
GIVEBACK = 0.08
ENTRY_TAGS = (
    "leave_zero_blue_tri",
    "ma60_lower_confirmed",
    "red_arrow_raw_first",
    "random_matched_density",
)


def _wilson_ci(hits: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = hits / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def _build_hl_temp(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """高低格＋溫度標（最高溫＝當日溫度＝近窗最高）。用公開日 K，不抄密技。"""
    from decision_card_signals import compute_card_temperature, hi_lo_tag

    cl = df["close"].astype(float)
    n = len(cl)
    high20 = cl.rolling(20, min_periods=5).max()
    high10 = cl.rolling(10, min_periods=3).max()
    high5 = cl.rolling(5, min_periods=2).max()
    low20 = cl.rolling(20, min_periods=5).min()
    low10 = cl.rolling(10, min_periods=3).min()
    low5 = cl.rolling(5, min_periods=2).min()
    high60 = cl.rolling(60, min_periods=20).max()
    low60 = cl.rolling(60, min_periods=20).min()
    ma20 = cl.rolling(20, min_periods=1).mean()
    ma60 = cl.rolling(60, min_periods=1).mean()
    bias = pd.Series(0.0, index=cl.index)
    ok = ma20 > 0
    bias.loc[ok] = ((cl.loc[ok] - ma20.loc[ok]) / ma20.loc[ok] * 100.0).round(1)

    hl = []
    temp = []
    for i in range(n):
        c = float(cl.iloc[i])
        tag = hi_lo_tag(
            c,
            h20=float(high20.iloc[i] or 0),
            h10=float(high10.iloc[i] or 0),
            h5=float(high5.iloc[i] or 0),
            l20=float(low20.iloc[i] or 0),
            l10=float(low10.iloc[i] or 0),
            l5=float(low5.iloc[i] or 0),
        )
        t = compute_card_temperature(
            c,
            float(high20.iloc[i] or 0),
            float(low20.iloc[i] or 0),
            float(bias.iloc[i] if pd.notna(bias.iloc[i]) else 0),
            high60=float(high60.iloc[i] or 0),
            low60=float(low60.iloc[i] or 0),
            ma60=float(ma60.iloc[i] or 0),
        )
        hl.append(tag)
        temp.append(t)
    # 最高溫＝近 20 日溫度最高（含今日）
    temp_s = pd.Series(temp, index=cl.index, dtype=float)
    roll_max = temp_s.rolling(20, min_periods=5).max()
    temp_label = []
    for i in range(n):
        t = float(temp_s.iloc[i])
        mx = float(roll_max.iloc[i]) if pd.notna(roll_max.iloc[i]) else t
        if mx > 0 and t >= mx - 1e-9 and t >= 40.0:
            temp_label.append("最高溫")
        else:
            temp_label.append("")
    return pd.Series(hl, index=cl.index), pd.Series(temp_label, index=cl.index)


def _simulate_trades(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: pd.Series,
    sid: str,
    entry_tag: str,
) -> List[Dict[str, Any]]:
    from sell_discipline import classify_how_to_sell

    cl = df["close"].astype(float)
    op = df["open"].astype(float)
    lo = df["low"].astype(float)
    hi = df["high"].astype(float)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(len(df))]
    n = len(df)
    trades: List[Dict[str, Any]] = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        # 次日開盤進（話筒訊號當日收盤後才看得到）
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(op.iloc[entry_i])
        if not (np.isfinite(entry_px) and entry_px > 0):
            i += 1
            continue
        peak = entry_px
        trough = entry_px
        exit_i = None
        exit_reason = None
        saw_hi20 = False
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD)):
            c = float(cl.iloc[j])
            h = float(hi.iloc[j])
            l = float(lo.iloc[j])
            if np.isfinite(h):
                peak = max(peak, h)
            if np.isfinite(l):
                trough = min(trough, l)
            hl_j = str(hl.iloc[j] or "")
            # 符號候選「出場▲／減碼◆」：進場後首碰 20高（最高價）→ 次日開盤出
            if j > entry_i and hl_j == "20高" and not saw_hi20:
                saw_hi20 = True
                exit_i = j + 1
                exit_reason = "first_hi20"  # 圖上可畫：出場提示（非自動賣）
                break
            # 如何賣：20高 vs 最高溫不同步 → 直接減碼（圖上可畫減碼標）
            if j > entry_i:
                flags = classify_how_to_sell(hl.iloc[j], temp_label.iloc[j])
                act = str(flags.get("sell_action") or "")
                if act == "直接減碼":
                    exit_i = j + 1
                    exit_reason = "sell_desync_cut"
                    break
            # 峰值回吐（風控底線；話筒可不畫，實驗室要記）
            if peak > 0 and np.isfinite(c) and c <= peak * (1.0 - GIVEBACK):
                exit_i = j + 1
                exit_reason = "giveback_8pct"
                break
        if exit_i is None:
            exit_i = min(n - 1, entry_i + MAX_HOLD)
            exit_reason = "max_hold_60"
        if exit_i >= n:
            exit_i = n - 1
        exit_px = float(op.iloc[exit_i]) if exit_reason != "max_hold_60" else float(cl.iloc[exit_i])
        if exit_reason == "max_hold_60":
            exit_px = float(cl.iloc[exit_i])
        else:
            exit_px = float(op.iloc[exit_i]) if np.isfinite(op.iloc[exit_i]) else float(cl.iloc[exit_i])
        if not (np.isfinite(exit_px) and exit_px > 0):
            i = max(i + 1, exit_i)
            continue
        gross = exit_px / entry_px - 1.0
        net = gross - FRICTION
        hold = int(exit_i - entry_i)
        mfe = peak / entry_px - 1.0
        mae = trough / entry_px - 1.0
        trades.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "entry_signal_date": dates[i],
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_i],
                "exit_reason": exit_reason,
                "hold_days": hold,
                "gross_ret": gross,
                "net_ret": net,
                "win": 1 if net > 0 else 0,
                "mfe": mfe,
                "mae": mae,
            }
        )
        # 不重疊部位：出場後才接下一個訊號
        i = exit_i + 1
    return trades


def _agg_trades(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {
            "n_trades": 0,
            "n_unique_entry_days": 0,
            "n_sids": 0,
            "win_rate": float("nan"),
            "wilson_ci95": [float("nan"), float("nan")],
            "avg_net": float("nan"),
            "median_net": float("nan"),
            "expectancy": float("nan"),
            "avg_hold": float("nan"),
            "avg_mfe": float("nan"),
            "avg_mae": float("nan"),
            "exit_reason_counts": {},
        }
    def _net(t: Dict[str, Any]) -> float:
        # 相容舊鍵 ret（部分 lab 草稿用 ret／hold）
        if "net_ret" in t:
            return float(t["net_ret"])
        return float(t["ret"])

    def _hold(t: Dict[str, Any]) -> float:
        if "hold_days" in t:
            return float(t["hold_days"])
        return float(t.get("hold") or 0)

    nets = np.asarray([_net(t) for t in trades], dtype=float)
    wins = int(sum(int(t["win"]) for t in trades))
    n = len(trades)
    days = {t["entry_date"] for t in trades}
    sids = {t["sid"] for t in trades}
    reasons: Dict[str, int] = defaultdict(int)
    for t in trades:
        reasons[str(t["exit_reason"])] += 1
    wlo, whi = _wilson_ci(wins, n)
    holds = np.asarray([_hold(t) for t in trades], dtype=float)
    mfes = np.asarray([float(t["mfe"]) if "mfe" in t else float("nan") for t in trades], dtype=float)
    maes = np.asarray([float(t["mae"]) if "mae" in t else float("nan") for t in trades], dtype=float)
    return {
        "n_trades": n,
        "n_unique_entry_days": len(days),
        "n_sids": len(sids),
        "win_rate": wins / n,
        "wilson_ci95": [wlo, whi],
        "avg_net": float(np.mean(nets)),
        "median_net": float(np.median(nets)),
        "expectancy": float(np.mean(nets)),
        "avg_hold": float(np.nanmean(holds)),
        "avg_mfe": float(np.nanmean(mfes)),
        "avg_mae": float(np.nanmean(maes)),
        "exit_reason_counts": dict(reasons),
    }


def run_phone_trade_confront(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    # 點名必在
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    all_trades: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ENTRY_TAGS}
    data_meta: Dict[str, Any] = {}
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 120:
                continue
            data_meta[sid] = {
                "source": raw.attrs.get("source"),
                "years": raw.attrs.get("years"),
                "span": raw.attrs.get("span"),
                "adj_kind": raw.attrs.get("adj_kind"),
                "name": MUST_INCLUDE.get(sid)
                or (
                    str(uni.loc[uni.stock_id == sid, "stock_name"].iloc[0])
                    if (uni.stock_id == sid).any()
                    else sid
                ),
            }
            df = _normalize_ohlc(raw)
            masks = _build_mark_masks(df)
            hl, temp_label = _build_hl_temp(df)
            for tag in ENTRY_TAGS:
                m = masks.get(tag)
                if m is None:
                    continue
                trades = _simulate_trades(df, m.fillna(False), hl=hl, temp_label=temp_label, sid=sid, entry_tag=tag)
                all_trades[tag].extend(trades)
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_tag = {tag: _agg_trades(trs) for tag, trs in all_trades.items()}
    baseline = by_tag.get("leave_zero_blue_tri") or {}
    comparisons = {}
    for tag, stats in by_tag.items():
        if tag == "leave_zero_blue_tri":
            continue
        ok = (
            int(stats.get("n_unique_entry_days") or 0) >= 20
            and int(baseline.get("n_unique_entry_days") or 0) >= 20
            and np.isfinite(stats.get("expectancy", np.nan))
            and np.isfinite(baseline.get("expectancy", np.nan))
        )
        comparisons[f"{tag}_vs_leave_zero"] = {
            "ok": ok,
            "gate_n20": int(stats.get("n_unique_entry_days") or 0) >= 20,
            "expectancy_delta": (
                float(stats["expectancy"]) - float(baseline["expectancy"])
                if ok
                else float("nan")
            ),
            "win_rate_delta": (
                float(stats["win_rate"]) - float(baseline["win_rate"]) if ok else float("nan")
            ),
            "beats_leave_zero": bool(
                ok
                and float(stats["expectancy"]) > float(baseline["expectancy"])
                and float(stats["win_rate"]) >= float(baseline["win_rate"]) - 0.01
            ),
            "tag_days": stats.get("n_unique_entry_days"),
            "base_days": baseline.get("n_unique_entry_days"),
        }

    # 點名檔各進場摘要
    must_focus = {}
    for sid in MUST_INCLUDE:
        must_focus[sid] = {"name": MUST_INCLUDE[sid], "data": data_meta.get(sid), "by_entry": {}}
        for tag, trs in all_trades.items():
            sub = [t for t in trs if t["sid"] == sid]
            must_focus[sid]["by_entry"][tag] = _agg_trades(sub)

    promote_candidates = [
        tag
        for tag, cmp_ in comparisons.items()
        if cmp_.get("beats_leave_zero") and tag.startswith("ma60_lower")
    ]
    # 只有確認紅箭贏 leave_zero 才談查股；生紅箭／隨機就算贏也不上買訊
    promote = bool(comparisons.get("ma60_lower_confirmed_vs_leave_zero", {}).get("beats_leave_zero"))

    gate = (
        f"leave_zero trades={baseline.get('n_trades')} days={baseline.get('n_unique_entry_days')} "
        f"win={baseline.get('win_rate')} E={baseline.get('expectancy')}; "
        f"ma60_lower days={by_tag.get('ma60_lower_confirmed', {}).get('n_unique_entry_days')} "
        f"win={by_tag.get('ma60_lower_confirmed', {}).get('win_rate')} "
        f"E={by_tag.get('ma60_lower_confirmed', {}).get('expectancy')}; "
        f"promote={'YES_lab_only_review' if promote else 'NO'}（不上話筒）"
    )

    symbol_map = {
        "leave_zero_blue_tri": {
            "role": "entry",
            "phone_now": True,
            "glyph_zh": "藍▲紅框",
            "note": "現況黃金買點（獲利剛離零）",
        },
        "ma60_lower_confirmed": {
            "role": "entry",
            "phone_now": True,
            "glyph_zh": "確認紅箭",
            "note": "已過閘可並列進場；本跑再比整段期望值",
        },
        "red_arrow_raw_first": {
            "role": "entry_control",
            "phone_now": False,
            "glyph_zh": "生紅箭（對照）",
            "note": "未確認＝不是買訊",
        },
        "first_hi20": {
            "role": "exit_assist",
            "phone_now": False,
            "glyph_zh": "出場◇（建議）",
            "note": "進場後首碰20高＝最高價協助；不是自動賣、要過閘才畫",
        },
        "sell_desync_cut": {
            "role": "exit_assist",
            "phone_now": "text_only",
            "glyph_zh": "減碼◆（建議）",
            "note": "如何賣：20高vs最高溫不同步→直接減碼；現況多在文字，符號化待過閘",
        },
        "giveback_8pct": {
            "role": "risk_lab_only",
            "phone_now": False,
            "glyph_zh": "（實驗室風控，不畫）",
            "note": "峰值回吐8%底線；未過閘不上圖",
        },
    }
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "method_zh": "次日開進；出場＝首碰20高／如何賣不同步減碼／峰值回吐8%／最多60日；淨報酬扣0.3%摩擦",
        "friction": FRICTION,
        "max_hold": MAX_HOLD,
        "giveback": GIVEBACK,
        "symbol_map": symbol_map,
        "n_stocks_meta": len(data_meta),
        "by_entry": by_tag,
        "comparisons_vs_leave_zero": comparisons,
        "must_named": must_focus,
        "promote_to_lookup_display": False,  # 本跑只給建議；真上話筒另過 §13
        "promote_lab_signal": promote,
        "promote_candidates": promote_candidates,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "note_zh": "進出場規則可轉符號；過閘才畫上查股；本跑不上話筒",
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_trade_confront_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_trade_confront_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print(
        "SUMMARY",
        json.dumps(
            {k: out[k] for k in out if k not in ("must_named",)},
            ensure_ascii=False,
            default=str,
        )[:1500],
        flush=True,
    )
    return out


if __name__ == "__main__":
    run_phone_trade_confront()
