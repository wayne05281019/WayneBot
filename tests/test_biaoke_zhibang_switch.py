# -*- coding: utf-8 -*-
"""近窗點名智邦 → 光通訊交換器進 digest／按鍵顯示；大盤欄不准吃「回測」。"""
from __future__ import annotations

import pytest

from biaoke_advisor import _inp_asic_tiers, _live_field_flags, format_action_advice_html
from biaoke_digest import _BOARD, _FIELD, _numbered_bits, format_focus_oral
from biaoke_field_scan import _OPT_SWITCH, _OPT_SWITCH_HEADER


def test_board_regex_does_not_steal_zhibang_retest():
    bit = (
        "另外光通訊交換器龍頭智邦已經確認中期整理完成，最簡單方式突破季線之後回測再介入，"
        "這檔光通訊龍頭股非常穩健安全，應該至少到過年前可測前高假突破有25%左右漲幅空間"
    )
    assert not _BOARD.search(bit)
    assert _FIELD.search(bit)


def test_board_regex_keeps_taigu_wang():
    bit = "上星期四台股出現最大的事件就是兩檔超過萬元價股王、股后跌停"
    assert _BOARD.search(bit)


def test_live_flags_switch_on_zhibang():
    flags = _live_field_flags("光通訊交換器龍頭智邦…年前有25%漲幅空間")
    assert flags.get("switch") is True
    assert flags.get("opt") is True


def test_focus_oral_puts_zhibang_not_in_board_column():
    text = (
        "1.\t上星期四台股出現最大的事件就是兩檔超過萬元價股王、股后跌停。\n"
        "2.\t目前盤面最強主流為CCL，台光電及台燿已經從反彈轉回升。\n"
        "3.\t光通訊可分成三個部分來看，最飆悍的InP次族群聯亞剩下最後一個關卡壓力區3255~3305。\n"
        "4.\tCPO/FAU次族群 最重要一檔股票就是大立光。\n"
        "5.\t另外光通訊交換器龍頭智邦已經確認中期整理完成，最簡單方式突破季線之後回測再介入，"
        "這檔光通訊龍頭股非常穩健安全，應該至少到過年前可測前高假突破有25%左右漲幅空間，"
        "操作這檔比去接高階測試或川湖等股票穩健安全得多。\n"
    )
    bits = _numbered_bits(text)
    assert len(bits) >= 5
    assert _BOARD.search(bits[0])
    assert not _BOARD.search(bits[4])
    oral = format_focus_oral(
        [{"date": "2026-10-11", "time": "09:43", "text": text}],
        [],
        db_path="",
    )
    assert "智邦" in oral
    assert "股王" in oral or "台股" in oral
    # 大盤區塊應含股王；智邦應在他還說／族群，不准獨占大盤
    board_idx = oral.find("<b>大盤</b>")
    field_idx = oral.find("<b>族群</b>")
    assert board_idx >= 0
    board_chunk = oral[board_idx:field_idx] if field_idx > board_idx else oral[board_idx:]
    assert "股王" in board_chunk or "台股" in board_chunk
    assert "智邦" not in board_chunk or "股王" in board_chunk


def test_switch_roster_has_zhibang():
    assert _OPT_SWITCH.get("2345") == "智邦"
    assert "交換器" in _OPT_SWITCH_HEADER


@pytest.mark.production_db
def test_production_advice_shows_zhibang(production_db):
    tiers = _inp_asic_tiers(production_db, "")
    assert tiers.get("live", {}).get("switch") is True
    rows = list(tiers.get("switch") or [])
    assert any(str(r.get("sid")) == "2345" for r in rows)
    html = format_action_advice_html(production_db)
    assert "智邦" in (html or "")
    assert "2345" in (html or "")
    assert "光通訊交換器" in (html or "")
    assert "年前約25%" in (html or "")
