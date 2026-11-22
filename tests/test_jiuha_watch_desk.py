# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from jiuha_watch_desk import (
    build_after_close_audit_only,
    build_tomorrow_intraday_checks,
    build_watch_desk,
    render_watch_desk_markdown,
    run_jiuha_daily_fuse,
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
    assert any(c["id"] == "T_tx_proxy" for c in checks)
    assert any(c["id"] == "T_l0_survive" for c in checks)
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
    assert "盤中這樣看" in md
    assert "盤後對質" in md
    assert "非買訊" in md
    assert "今天" in md
    out = write_watch_desk_artifacts(
        market_db=str(db), out_dir=str(tmp_path), asof="20261120"
    )
    assert out.get("ok") is True
    assert Path(out["md"]).is_file()
    assert Path(out["png"]).is_file()
    assert Path(out["png"]).stat().st_size > 1000
    assert "非買訊" in (out.get("caption") or "")
    assert Path(tmp_path / "desk_fuse_latest.json").is_file()
    fused = run_jiuha_daily_fuse(
        market_db=str(db),
        out_dir=str(tmp_path / "fuse"),
        charts_dir=str(tmp_path / "charts"),
    )
    assert fused.get("ok") is True
    assert Path(fused["png"]).is_file()


def test_menu_slot_jiuha_row3():
    from bot_servers import MENU_BTN_JIUHA, MENU_LAYOUT_VERSION, MENU_ROW3

    assert MENU_LAYOUT_VERSION == "42"
    assert MENU_ROW3[1] == MENU_BTN_JIUHA


def test_concrete_omits_empty_otc_and_has_numbers(tmp_path):
    db = Path("/workspace/data/wayne_market.db")
    if not db.is_file():
        return
    desk = build_watch_desk(str(db), asof="20261120")
    c = desk.get("concrete") or {}
    assert c.get("twii_close") is not None
    assert c.get("twii_vol_wan") is not None
    # 補洞後同日櫃買才出；若仍缺則 otc_ok=False 且畫面不准硬塞空白櫃買卡
    if c.get("otc_ok"):
        assert c.get("otc_close") is not None
        assert c.get("otc_rel_pp") is not None
    md = render_watch_desk_markdown(desk)
    assert "盤中可對照" in md or "加權收" in md
    assert "1708" in md or "成交量" in md
    assert desk.get("next_session")
    ser = (desk.get("series") or {}).get("twii") or []
    assert ser
    from jiuha_watch_desk import _is_tw_open_day

    assert all(_is_tw_open_day(b["date"], str(db)) for b in ser)
    if not c.get("otc_ok"):
        assert "櫃買收" not in md
