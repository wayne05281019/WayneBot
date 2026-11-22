# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from jiuha_watch_desk import (
    build_after_close_audit_only,
    build_tomorrow_intraday_checks,
    build_watch_desk,
    render_watch_desk_markdown,
    write_watch_desk_artifacts,
)


def test_tomorrow_checks_are_intraday_only():
    pack = {
        "ok": True,
        "asof": "20261120",
        "twii": {"chg_pct": 2.0, "vol_vs_5": 0.7},
        "structure_labels": ["縮量反彈／疑空手回補"],
    }
    checks = build_tomorrow_intraday_checks(pack)
    assert checks
    assert all(c.get("intraday") is True for c in checks)
    assert any(c["id"] == "T_open15_vol" for c in checks)
    assert any(c["id"] == "T_escape_follow" for c in checks)
    # 融資速度差不准混進盤中應對清單
    assert not any("融資餘額" in (c.get("watch") or "") for c in checks)


def test_after_close_audit_separated():
    audit = build_after_close_audit_only({})
    ids = {a["id"] for a in audit}
    assert "A_margin_speed" in ids
    assert "A_futures_oi" in ids
    for a in audit:
        assert a.get("why_not_intraday")


def test_watch_desk_from_market_db(tmp_path):
    db = Path("/workspace/data/wayne_market.db")
    if not db.is_file():
        return
    desk = build_watch_desk(str(db), asof="20261120")
    assert desk.get("ok") is True
    assert desk.get("not_buy_signal") is True
    assert desk.get("tomorrow_intraday")
    md = render_watch_desk_markdown(desk)
    assert "明日盤中要注意" in md
    assert "盤後對質欄" in md
    assert "非買訊" in md
    out = write_watch_desk_artifacts(
        market_db=str(db), out_dir=str(tmp_path), asof="20261120"
    )
    assert out.get("ok") is True
    assert Path(out["md"]).is_file()
    assert Path(out["png"]).is_file()
    assert Path(out["png"]).stat().st_size > 1000
