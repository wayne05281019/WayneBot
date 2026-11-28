#!/usr/bin/env python3
"""Audit every Huang day against daily focus card. Exit 1 if gaps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

DAYS = Path("/workspace/docs/expert_notes/黃培碩/huang_days")


def audit_one(path: Path) -> list[str]:
    d = json.loads(path.read_text(encoding="utf-8"))
    bad: list[str] = []
    meta = d.get("meta") or {}
    if meta.get("film_status") not in ("present", "absent_open", "closed"):
        bad.append("film_status")
    if meta.get("film_status") == "closed":
        return bad
    if not meta.get("written_before_peek", False):
        bad.append("written_before_peek")
    fc = d.get("forecast_for_next") or {}
    if not fc.get("high_prob") or not (fc.get("low_prob") or fc.get("single_branch_ok")):
        bad.append("dual_branch")
    ar = (d.get("quant") or {}).get("amp_ratios") or {}
    amp_zh = ((fc.get("high_prob") or {}).get("amp_zh") or "")
    if not ar.get("next_chop_band_tx") and "～" not in amp_zh and "~" not in amp_zh:
        bad.append("amp_band")
    fu = (d.get("quant") or {}).get("fib_used")
    if not isinstance(fu, dict) or not (fu.get("index") or {}).get("R"):
        bad.append("fib_equal_amp")
    vp = (d.get("quant") or {}).get("vol_price") or {}
    if vp.get("vol") is None or vp.get("vol_ma20") is None:
        bad.append("vol_numeric")
    if "量" not in (d.get("five_vol_sox_note_zh") or ""):
        bad.append("five_vol_needs_量")
    if not d.get("market_power"):
        bad.append("market_power")
    if not d.get("stock_quant"):
        bad.append("stock_quant")
    wp = d.get("wave_progress") or {}
    if not wp.get("pullback_band") or not wp.get("rebound_band"):
        bad.append("wave_bands")
    if not d.get("confront_official"):
        bad.append("confront")
    if not d.get("miss_anatomy_zh"):
        bad.append("miss_anatomy")
    if not d.get("breadth_official"):
        bad.append("breadth")
    if (d.get("sync_tx") or {}).get("status") != "ok":
        bad.append("sync_tx")
    for k in ("exit_learn_zh", "holdings_env_gate", "night_morning_line", "biaoke_cross"):
        if not d.get(k):
            bad.append(k)
    named = (d.get("regime_D") or {}).get("named_symbols") or []
    bars = ((d.get("named_stocks_ohlcv") or {}).get("bars") or {})
    if named and not bars:
        bad.append("named_bars")
    aud = d.get("no_forget_audit") or {}
    if not aud.get("full_suite_evidence_ok"):
        bad.append("full_suite_evidence_ok")
    return bad


def main() -> int:
    files = sorted(DAYS.glob("2026*.json"))
    gaps = []
    for p in files:
        bad = audit_one(p)
        if bad:
            gaps.append((p.stem, bad))
    print(
        json.dumps(
            {"n": len(files), "gaps": len(gaps), "detail": gaps[:30], "ok": len(gaps) == 0},
            ensure_ascii=False,
        )
    )
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
