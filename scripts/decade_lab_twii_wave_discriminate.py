# -*- coding: utf-8 -*-
"""強化大盤 TWII 浪段辨識：掃 entry_preset × score 門檻，找「狀態可分」的引擎設定。

問題：A1_score@50 下 TWII 幾乎全停 BASE／W2，大盤閘咬不住。
本腳本只評狀態分布／事件密度／可分性，不上話筒。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import load_twii
from scripts.decade_lab_hsiao_wave_engine import ENTRY_PRESETS, ElliottHsiaoEngine

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"

CRASHY = {"WAVE_C_CRASH", "WAVE_A_DROP", "WAVE_B_TRAP"}
IMPULSE = {"WAVE_1_UP", "WAVE_3_MAIN", "WAVE_5_FINAL"}
PULL = {"BASE_BOTTOM", "WAVE_2_PULLBACK"}


def _entropy(counts: Dict[str, int]) -> float:
    n = sum(counts.values()) or 1
    p = np.array([c / n for c in counts.values() if c > 0], dtype=float)
    if len(p) == 0:
        return 0.0
    return float(-(p * np.log(p + 1e-12)).sum())


def run() -> Dict[str, Any]:
    t0 = time.time()
    raw = load_twii()
    prep = prepare_ohlcv(raw)
    feat = compute_hsiao_features(prep)
    rows: List[Dict[str, Any]] = []
    for preset in ENTRY_PRESETS:
        for thr in (40.0, 45.0, 50.0, 55.0, 60.0):
            eng = ElliottHsiaoEngine(entry_preset=preset, score_threshold=thr)
            lab = eng.run(feat, already_featured=True)
            st = lab["state_name"].astype(str)
            sig = lab["lab_signal"].astype(str)
            vc = st.value_counts().to_dict()
            n = len(st)
            frac = {k: float(v) / n for k, v in vc.items()}
            n_w3 = int((sig == "LAB_BUY_W3_START").sum())
            n_w1 = int(sum(1 for e in (lab.attrs.get("lab_events") or []) if e.get("code") == "LAB_W1_START"))
            n_w3_top = int(sum(1 for e in (lab.attrs.get("lab_events") or []) if e.get("code") == "LAB_W3_TOP"))
            crash_pct = float(st.isin(CRASHY).mean())
            impulse_pct = float(st.isin(IMPULSE).mean())
            pull_pct = float(st.isin(PULL).mean())
            # 可分性：熵 + 非單一狀態佔比 + 有推動／修正對比
            ent = _entropy({str(k): int(v) for k, v in vc.items()})
            top1 = max(frac.values()) if frac else 1.0
            diversity = 1.0 - top1
            has_contrast = impulse_pct > 0.01 and pull_pct > 0.05
            # 評分：要可分，但不要崩壞佔滿；要有一點 W3／W1 事件
            score = (
                2.0 * ent
                + 3.0 * diversity
                + 2.0 * min(impulse_pct * 10, 1.0)
                + 1.5 * min(n_w3 / 20.0, 1.0)
                + 0.5 * min(n_w1 / 10.0, 1.0)
                - 2.0 * max(crash_pct - 0.35, 0.0)
                - 1.0 * max(top1 - 0.85, 0.0) * 5
            )
            rows.append(
                {
                    "preset": preset,
                    "score_threshold": thr,
                    "n_bars": n,
                    "state_counts": vc,
                    "state_frac": frac,
                    "entropy": ent,
                    "diversity": diversity,
                    "crash_pct": crash_pct,
                    "impulse_pct": impulse_pct,
                    "pull_pct": pull_pct,
                    "n_w3_start": n_w3,
                    "n_w1_start": n_w1,
                    "n_w3_top": n_w3_top,
                    "has_contrast": has_contrast,
                    "disc_score": score,
                }
            )
    rows.sort(key=lambda r: float(r["disc_score"]), reverse=True)
    best = rows[0] if rows else None
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_presets_tried": len(rows),
        "ranking": rows,
        "best": best,
        "note_zh": "挑大盤狀態可分的 preset×門檻；下一步用 best 重跑 market_wave_sync。",
        "gate_one_liner": (
            f"best={best['preset'] if best else None}@{best['score_threshold'] if best else None} "
            f"disc={best['disc_score'] if best else None} "
            f"impulse={best['impulse_pct'] if best else None} "
            f"w3={best['n_w3_start'] if best else None}; promote_lookup=NO"
            if best
            else "no_rows"
        ),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    (ART / "phone_twii_wave_discriminate_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_twii_wave_discriminate_latest.json").write_text(text, encoding="utf-8")
    print("GATE", out["gate_one_liner"], flush=True)
    print("TOP", json.dumps(rows[:5], ensure_ascii=False, default=str)[:1500], flush=True)
    return out


if __name__ == "__main__":
    run()
