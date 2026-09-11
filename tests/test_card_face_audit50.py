# -*- coding: utf-8 -*-
"""抽查 50 檔高低卡：上欄標籤、數字、扣抵、徽章不能互打。"""
from __future__ import annotations

import os
import tempfile

import pytest

from tests.card_face_audit import MUST, card_issues


def _sample(db: str) -> list[str]:
    import sqlite3

    have = []
    con = sqlite3.connect(db)
    try:
        for sid in MUST:
            n = con.execute(
                "SELECT COUNT(*) FROM daily_quotes WHERE stock_id=?", (sid,)
            ).fetchone()[0]
            if n >= 20:
                have.append(sid)
                continue
            n2 = con.execute(
                "SELECT COUNT(*) FROM emerging_quotes WHERE stock_id=?", (sid,)
            ).fetchone()[0]
            if n2 >= 20:
                have.append(sid)
        if len(have) < 50:
            rows = con.execute(
                """
                SELECT stock_id, COUNT(*) n FROM daily_quotes
                GROUP BY stock_id HAVING n >= 80
                ORDER BY n DESC LIMIT 80
                """
            ).fetchall()
            for sid, _n in rows:
                if sid not in have:
                    have.append(str(sid))
                if len(have) >= 50:
                    break
    finally:
        con.close()
    return have[:50]


@pytest.mark.production_db
def test_fifty_highlow_cards_face_invariants(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine, render_decision_card_png

    db = require_production_db()
    sids = _sample(db)
    assert len(sids) >= 50, f"庫裡不夠 50 檔，只有 {len(sids)}"
    eng = NavigatorEngine(db)
    orig = matplotlib.axes.Axes.text
    bag: list[str] = []

    def wrap(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        bag.append(s)
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    report = []
    failed = []
    for sid in sids:
        card = eng.get_decision_card(sid, lookback=20)
        if card.get("error"):
            failed.append(f"{sid} 建卡失敗 {card.get('error')}")
            continue
        bag.clear()
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            assert render_decision_card_png(card, path)
            issues = card_issues(card, list(bag))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        line = f"{sid} {card.get('stock_name')} live={card.get('is_live')} close={card.get('close')} badges={card.get('badges')}"
        if issues:
            failed.append(f"{sid}: " + "；".join(issues))
            report.append("FAIL " + line + " | " + "；".join(issues))
        else:
            report.append("OK   " + line)
    os.makedirs("/opt/cursor/artifacts", exist_ok=True)
    with open("/opt/cursor/artifacts/card_face_audit50.log", "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
        if failed:
            f.write("\nFAILED\n" + "\n".join(failed) + "\n")
    assert not failed, "\n".join(failed[:12])
