# -*- coding: utf-8 -*-
"""Seal champion_v3 latest → decision JSON/md; phone_sync=blocked."""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")


def main() -> None:
    src = DOC / "phone_champion_v3_latest.json"
    if not src.exists():
        src = ART / "phone_champion_v3_latest.json"
    if not src.exists():
        raise SystemExit("no phone_champion_v3_latest.json")
    latest = json.loads(src.read_text(encoding="utf-8"))
    now = datetime.now(TZ).isoformat()
    winners = latest.get("winners_beat_random") or []
    lift = latest.get("winners_lift_bal") or []
    by_bal = latest.get("by_balanced_score") or []
    ge50 = latest.get("best_ge50") or []
    base = None
    for r in latest.get("ranking") or []:
        if r.get("key") == "B_bal__M0__X0__SELL_hi20_or_wave_top":
            base = r
            break
    dec = {
        "phone_sync": "blocked",
        "promote_to_lookup_display": False,
        "NOT_BUY_SIGNAL": True,
        "as_of_taipei": now,
        "gate_one_liner": latest.get("gate_one_liner"),
        "n_stocks": latest.get("n_stocks"),
        "elapsed_s": latest.get("elapsed_s"),
        "baseline_M0_X0": base,
        "winners_beat_random_n": len(winners),
        "winners_lift_bal_n": len(lift),
        "by_balanced_top": by_bal[:10],
        "best_ge50": ge50[:8],
        "lifts_bal_baseline": bool(lift),
        "read_zh": [
            str(latest.get("gate_one_liner")),
            "promote 預設 false；須 n≥20 且抬 B_bal__M0__X0 才進下一版候選",
        ],
    }
    text = json.dumps(dec, ensure_ascii=False, indent=2, default=str)
    (DOC / "phone_champion_v3_decision.json").write_text(text, encoding="utf-8")
    (ART / "phone_champion_v3_decision.json").write_text(text, encoding="utf-8")
    md = (
        f"# phone_champion_v3\n\n- gate: `{latest.get('gate_one_liner')}`\n"
        f"- lift_bal_n: {len(lift)}; winners: {len(winners)}\n"
        f"- phone_sync: blocked; promote: false\n"
    )
    (DOC / "phone_champion_v3_decision.md").write_text(md, encoding="utf-8")
    (ART / "phone_champion_v3_decision.md").write_text(md, encoding="utf-8")
    print(latest.get("gate_one_liner"), flush=True)


if __name__ == "__main__":
    main()
