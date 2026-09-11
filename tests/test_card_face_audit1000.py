# -*- coding: utf-8 -*-
"""抽測上市／上櫃／興櫃共 1000 檔高低卡：低中高價、排版標籤、數字、國字。"""
from __future__ import annotations

import os
import tempfile
from collections import Counter

import pytest

from tests.card_face_audit import card_issues, sample_universe


SHOWCASE = [
    ("2330", "tw-hi"),
    ("2002", "tw-lo"),
    ("2412", "tw-mid"),
    ("6488", "two-hi"),
    ("5483", "two-mid"),
    ("00631L", "etf"),
    ("3595", "em-hi"),
    ("1260", "em-lo"),
]


@pytest.mark.production_db
def test_nan_ohlc_etf_still_builds_card():
    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(require_production_db()).get_decision_card("00636K")
    assert not card.get("error")
    assert float(card.get("close") or 0) > 0


@pytest.mark.production_db
def test_thousand_highlow_cards_face_invariants(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes
    import matplotlib.figure

    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine, render_decision_card_png

    db = require_production_db()
    sample = sample_universe(db, 1000)
    assert len(sample) >= 1000, f"庫裡不夠 1000 檔，只有 {len(sample)}"
    mix = Counter((x["market"], "lo" if x["close"] < 30 else "mid" if x["close"] < 200 else "hi") for x in sample)
    assert mix.get(("TW", "lo"), 0) >= 80
    assert mix.get(("TW", "hi"), 0) >= 40
    assert mix.get(("TWO", "lo"), 0) >= 40
    assert mix.get(("TWO", "hi"), 0) >= 20
    assert sum(v for (m, _b), v in mix.items() if m == "EM") >= 80

    eng = NavigatorEngine(db)
    orig_text = matplotlib.axes.Axes.text
    orig_save = matplotlib.figure.Figure.savefig
    bag: list[str] = []

    def wrap_text(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        bag.append(s)
        return orig_text(self, *args, **kwargs)

    def wrap_save(self, *args, **kwargs):
        fname = str(kwargs.get("fname") or (args[0] if args else "") or "")
        if "/opt/cursor/artifacts/" in fname.replace("\\", "/"):
            return orig_save(self, *args, **kwargs)
        return None

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap_text)
    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", wrap_save)

    os.makedirs("/opt/cursor/artifacts", exist_ok=True)
    report = []
    failed = []
    built = 0
    skipped = []
    counts = Counter()
    showcase_ids = {s for s, _ in SHOWCASE}

    for item in sample:
        sid = item["stock_id"]
        try:
            card = eng.get_decision_card(sid, lookback=20)
        except Exception as e:
            failed.append(f"{sid} 建卡炸掉 {type(e).__name__}: {e}")
            report.append(f"CRASH {sid} {item.get('market')} {e}")
            continue
        if card.get("error"):
            skipped.append(f"{sid} {item.get('market')} {card.get('error')}")
            continue
        built += 1
        listing = str(card.get("listing") or item["market"])
        band = "lo" if float(card.get("close") or 0) < 30 else "mid" if float(card.get("close") or 0) < 200 else "hi"
        counts[f"{listing}-{band}"] += 1
        bag.clear()
        save_real = sid in showcase_ids
        path = (
            f"/opt/cursor/artifacts/{sid}-audit1000.png"
            if save_real
            else os.path.join(tempfile.gettempdir(), f"wayne-audit-{sid}.png")
        )
        assert render_decision_card_png(card, path)
        issues = card_issues(card, list(bag))
        line = (
            f"{sid} {card.get('stock_name')} {listing} {band} "
            f"px={card.get('close')} live={card.get('is_live')} badges={card.get('badges')}"
        )
        if issues:
            failed.append(f"{sid}: " + "；".join(issues))
            report.append("FAIL " + line + " | " + "；".join(issues))
        else:
            report.append("OK   " + line)

    head = [
        f"built={built} skipped={len(skipped)} failed={len(failed)} sampled={len(sample)}",
        "mix " + " ".join(f"{k}:{v}" for k, v in sorted(counts.items())),
    ]
    if skipped:
        head.append("SKIP " + " | ".join(skipped[:20]))
    with open("/opt/cursor/artifacts/card_face_audit1000.log", "w", encoding="utf-8") as f:
        f.write("\n".join(head + report) + "\n")
        if failed:
            f.write("\nFAILED\n" + "\n".join(failed) + "\n")
    assert built >= 900, f"成功出卡只有 {built}，skip={len(skipped)}"
    assert not failed, "\n".join(failed[:25])
