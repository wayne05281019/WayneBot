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


def test_checklist_blocks_stack_when_and_body():
    from jiuha_watch_desk import _checklist_blocks

    rows = [
        {
            "when": "08:30／09:30／11:00／13:00",
            "line": "台幣較昨收貶≥0.15%＝壓力、升≥0.15%＝偏暖；與指數背離優先信台幣",
        },
        {"when": "08:50開盤前", "line": "停損／最多虧多少說好了嗎 未說好＝後面燈先不當操作解讀（空手／等待）"},
    ]
    blocks = _checklist_blocks(rows, body_width=26)
    assert len(blocks) == 2
    assert blocks[0]["when"].startswith("08:30")
    assert blocks[0]["n_lines"] >= 2
    assert all("\n" not in ln for ln in blocks[0]["body_lines"])
    # 長時段不准跟內文同一行互壓：when 獨立、body 另列
    assert blocks[0]["body_lines"][0] != blocks[0]["when"]


def test_watch_desk_png_layout_no_giant_empty(tmp_path):
    from PIL import Image
    from jiuha_watch_desk import build_watch_desk, render_watch_desk_png

    db = Path("/workspace/data/wayne_market.db")
    if not db.is_file():
        return
    desk = build_watch_desk(str(db), asof="20261120")
    if not desk.get("ok"):
        return
    # 缺欄路徑：畫布應明顯矮於舊固定 19.5"（~2925px＠150dpi）
    slim = dict(desk)
    slim["concrete"] = dict(desk.get("concrete") or {})
    for k in ("otc_ok", "fx_ok", "margin_ok", "oi_ok", "bfi_ok"):
        slim["concrete"][k] = False
    p = tmp_path / "desk_slim.png"
    render_watch_desk_png(slim, str(p))
    im = Image.open(p)
    assert im.size[1] < 2600
    assert p.stat().st_size > 1000
