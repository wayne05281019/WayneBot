# -*- coding: utf-8 -*-
"""SYNC-NARRATIVE：位階／大盤／三窗敘述口徑統一。"""
from __future__ import annotations

import inspect
from pathlib import Path

from observe_manual import (
    CHAIN_ONE_LINER_ZH,
    OBSERVE_CAPTION_SHORT,
    OBSERVE_PHONE_DISCLAIMER,
    PERIOD_SPOT_SPLIT_ZH,
    SOX_LINK_ONE_ZH,
    WAVE_BRIEF_TITLE,
    caption_disclaimer_bit,
    chain_one_liner,
    format_market_observe_footer,
    format_teach_brief_frame_lines,
    format_wave_observe_slot,
    merge_wave_phone_html,
    sox_link_one_liner,
)


def test_hard_lock_disclaimer_and_title():
    assert OBSERVE_PHONE_DISCLAIMER == "試標・推論／非他原文・非買訊・對質未過閘"
    assert "試標" in WAVE_BRIEF_TITLE
    assert "預估" not in WAVE_BRIEF_TITLE
    assert caption_disclaimer_bit() == OBSERVE_CAPTION_SHORT
    assert "預估會改" not in OBSERVE_CAPTION_SHORT


def test_chain_one_liner_from_playbook_or_placeholder():
    one = chain_one_liner()
    assert "e-mini" in one or "夜盤" in one
    assert "不准倒灌" in one or one == CHAIN_ONE_LINER_ZH
    sox = sox_link_one_liner()
    assert "費半" in sox
    assert sox
    # 不准誤吃第一層「＋費半外圍」role
    assert "定大方向假設" not in sox
    assert "假強" in sox or "內盤" in sox or "試標" in sox


def test_chain_placeholder_without_json(tmp_path: Path):
    """缺 chain JSON 仍可用 playbook／lock placeholder。"""
    one = chain_one_liner(root=tmp_path)
    assert "夜盤" in one or "e-mini" in one
    slot = format_wave_observe_slot(root=tmp_path)
    assert OBSERVE_PHONE_DISCLAIMER in slot
    assert "觀盤鏈定式" in slot
    assert "不准倒灌" in slot or "TX" in slot or "夜盤" in slot


def test_frame_lines_dual_and_pots():
    lines = format_teach_brief_frame_lines(dual_wave=True)
    blob = "\n".join(lines)
    assert WAVE_BRIEF_TITLE in blob or "試標" in blob
    assert OBSERVE_PHONE_DISCLAIMER in blob
    assert "觀盤鏈" in blob
    assert "雙浪" in blob
    assert "分鍋" in blob or "他說" in blob
    assert PERIOD_SPOT_SPLIT_ZH in blob or "期＝" in blob


def test_teach_brief_uses_synced_frame(monkeypatch):
    from biaoke_digest import format_teach_brief

    pack = {
        "thesis": "B-b 反彈；備線九波；五波跌完",
        "morph_note": "",
        "intent_note": "",
        "fib_note": "",
        "wait_struct": "假跌破37837；35579→31705",
        "pred_note": "",
        "pred_levels": {},
        "chart_as_of": "20261120",
    }
    monkeypatch.setattr(
        "biaoke_level_learn._build_live_pack", lambda _db: pack
    )
    monkeypatch.setattr(
        "biaoke_level_learn._wave_now_ladder",
        lambda _p: {"now": "B-b／九波雙軌", "day_zh": "11/20"},
    )
    out = format_teach_brief("x.db", pack)
    assert "試標" in out
    assert OBSERVE_PHONE_DISCLAIMER in out
    assert "觀盤鏈" in out
    assert "費半" in out
    assert "雙浪" in out or "並標" in out
    assert "現・加權" in out or "期・" in out
    assert "預估・非買訊" not in out


def test_market_footer_synced():
    foot = format_market_observe_footer()
    assert "觀盤鏈" in foot
    assert OBSERVE_PHONE_DISCLAIMER in foot
    assert "波浪位階" in foot
    assert "費半" in foot or SOX_LINK_ONE_ZH[:4] in foot


def test_market_page_wires_footer():
    from taiwan_market import format_taiwan_market_page_html

    src = inspect.getsource(format_taiwan_market_page_html)
    assert "format_market_observe_footer" in src


def test_wave_cmd_text_before_charts_and_disclaimer():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "merge_wave_phone_html" in src
    assert OBSERVE_PHONE_DISCLAIMER in src
    assert src.index("merge_wave_phone_html") < src.index("_send_market_wave_charts")


def test_trio_captions_drop_old_yugu_phrase():
    from bot_servers import WayneTelegramBot

    album = inspect.getsource(WayneTelegramBot._send_market_teach_trio_album)
    paint = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "預估會改・非買訊" not in album
    assert "預估會改・非買訊" not in paint
    assert "caption_disclaimer_bit" in album or OBSERVE_CAPTION_SHORT in album


def test_merge_sample_text():
    brief = (
        f"<b>{WAVE_BRIEF_TITLE}</b>\n"
        f"{OBSERVE_PHONE_DISCLAIMER}\n"
        "現・加權：樣張測試"
    )
    html = merge_wave_phone_html(brief)
    assert WAVE_BRIEF_TITLE in html
    assert "觀測手冊摘要／今日觀測" in html
    assert OBSERVE_PHONE_DISCLAIMER in html
    # 樣張落檔給人工對讀
    out = Path("/opt/cursor/artifacts/sync_narrative_sample.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    assert out.is_file()


def test_market_wave_caption_has_disclaimer():
    from market_biaoke_wave import market_wave_caption_lines, _chart_caption_lines

    full = market_wave_caption_lines("20261120")
    assert any("試標" in x for x in full)
    short = _chart_caption_lines("20261120")
    assert any("試標" in x for x in short)
