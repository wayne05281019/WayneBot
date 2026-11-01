# -*- coding: utf-8 -*-
"""按台股大盤：美股先對到最新官方列，再畫走勢；沒有官方走勢不上圖。"""
from __future__ import annotations

import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TP = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")


def test_weekend_morning_expected_us_session_is_friday():
    from us_overnight import expected_us_print_session

    # 2026-10-18 00:25 台北＝美東週五 12:25，現金盤仍是週五。
    assert expected_us_print_session(datetime(2026, 10, 18, 0, 25, tzinfo=TP)) == "20261016"
    # 週六下午紐約不另開星期六。
    assert expected_us_print_session(datetime(2026, 10, 17, 16, 0, tzinfo=NY)) == "20261016"


def test_press_refreshes_us_block_to_latest_official_bar(tmp_path, monkeypatch):
    from taiwan_market import _format_overnight_watch_lines
    from us_overnight import refresh_us_for_market_page, save_us_overnight

    db = str(tmp_path / "us.db")
    save_us_overnight(
        db,
        "20261016",
        {
            "ok": True,
            "regime": "ok",
            "us_session": "20261015",
            "us_phase": "overnight",
            "fetched_at": "2026-10-15T22:30:00+00:00",
            "vix": 18.0,
            "dji_pct": 1.11,
            "spx_pct": 0.8,
            "ixic_pct": 1.25,
            "sox_pct": 0.4,
        },
    )

    def _friday(_now=None):
        return {
            "ok": True,
            "fetched_at": "2026-10-17T16:25:00+00:00",
            "us_phase": "regular",
            "us_session": "20261016",
            "regime": "caution",
            "vix": 20.5,
            "dji_pct": -0.34,
            "dji_chg": -175.29,
            "dji_px": 52002.41,
            "spx_pct": -1.09,
            "ixic_pct": -2.15,
            "sox_pct": -3.83,
        }

    monkeypatch.setattr("us_overnight.fetch_us_tape", _friday)
    now = datetime(2026, 10, 18, 0, 25, tzinfo=TP)
    got = refresh_us_for_market_page(db, "20261016", now=now)
    assert got["us_session"] == "20261016"
    assert got["ixic_pct"] == -2.15
    lines = _format_overnight_watch_lines(db, "20261016", {}, now=now, us_snap=got)
    joined = "\n".join(lines)
    assert "2026/10/16" in joined
    assert "-2.15%" in joined
    assert "+1.25%" not in joined
    assert "1.11%" not in joined


def test_missing_us_overnight_table_does_not_kill_market_page(monkeypatch):
    """:memory: 沒有 us_overnight。寫庫失敗仍回這次官方列，不准整頁炸掉。"""
    from us_overnight import refresh_us_for_market_page

    def _friday(_now=None):
        return {
            "ok": True,
            "fetched_at": "2026-10-17T16:25:00+00:00",
            "us_phase": "regular",
            "us_session": "20261016",
            "regime": "caution",
            "vix": 20.5,
            "dji_pct": -0.34,
            "spx_pct": -1.09,
            "ixic_pct": -2.15,
            "sox_pct": -3.83,
        }

    monkeypatch.setattr("us_overnight.fetch_us_tape", _friday)
    now = datetime(2026, 10, 18, 0, 25, tzinfo=TP)
    got = refresh_us_for_market_page(":memory:", "20261016", now=now)
    assert got["us_session"] == "20261016"
    assert got["ixic_pct"] == -2.15
    assert got.get("_press_miss") is not True


def test_press_fetch_fail_does_not_show_older_as_current(tmp_path, monkeypatch):
    from taiwan_market import _format_overnight_watch_lines
    from us_overnight import refresh_us_for_market_page, save_us_overnight

    db = str(tmp_path / "us.db")
    save_us_overnight(
        db,
        "20261016",
        {
            "ok": True,
            "regime": "ok",
            "us_session": "20261015",
            "fetched_at": "2026-10-15T22:30:00+00:00",
            "vix": 18.0,
            "dji_pct": 1.11,
            "spx_pct": 0.8,
            "ixic_pct": 1.25,
            "sox_pct": 0.4,
        },
    )

    def _boom(_now=None):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr("us_overnight.fetch_us_tape", _boom)
    now = datetime(2026, 10, 18, 0, 25, tzinfo=TP)
    got = refresh_us_for_market_page(db, "20261016", now=now)
    assert got.get("_press_miss") is True
    joined = "\n".join(_format_overnight_watch_lines(db, "20261016", {}, now=now, us_snap=got))
    assert "尚未接到" in joined
    assert "2026/10/15" in joined
    assert "1.25%" not in joined
    assert "1.11%" not in joined


def test_tx_night_keeps_friday_session_across_saturday_prints():
    from market_session_cards import build_tx_night_card

    ticks = [
        ("20261016", "202610", "150100", 47269.0, 10),
        ("20261016", "202610", "210000", 47000.0, 20),
        ("20261017", "202610", "045957", 46140.0, 12),
        ("20261017", "202611", "045900", 46289.0, 1),
    ]
    card = build_tx_night_card(ticks, 47284.0)
    assert card is not None
    assert card["session"] == "20261016"
    assert card["last"] == 46140.0
    assert card["chg"] == pytest.approx(46140.0 - 47284.0)
    assert card["pct"] == pytest.approx((46140.0 - 47284.0) / 47284.0 * 100.0)
    assert "20261017" not in card["session"]
    assert card["series"][-1] == 46140.0


def test_saturday_only_ticks_are_not_a_session():
    from market_session_cards import build_tx_night_card

    ticks = [
        ("20261017", "202610", "150100", 46000.0, 5),
        ("20261017", "202610", "160000", 45900.0, 5),
    ]
    assert build_tx_night_card(ticks, 47284.0) is None


def test_missing_series_omits_card_and_says_so():
    from market_session_cards import omission_lines

    lines = omission_lines(
        {"session": "20261016", "cards": [], "missing": ["道瓊", "費城半導體"]},
        {"card": None, "missing": True},
        None,
    )
    assert lines == [
        "道瓊這次沒有官方走勢，不上圖",
        "費城半導體這次沒有官方走勢，不上圖",
        "台指電子盤這次沒有官方走勢，不上圖",
        "恐懼與貪婪指數這次沒有官方讀數，不上圖",
    ]


def test_render_cards_use_official_prints_and_taiwan_colors(tmp_path):
    import matplotlib.image as mpimg

    from market_session_cards import render_session_cards

    down = {
        "name": "道瓊",
        "last": 100.0,
        "prev": 110.0,
        "chg": -10.0,
        "pct": -9.09,
        "series": [112.0, 108.0, 104.0, 100.0],
        "integers": False,
    }
    up = {
        "name": "那斯達克",
        "last": 120.0,
        "prev": 100.0,
        "chg": 20.0,
        "pct": 20.0,
        "series": [98.0, 104.0, 112.0, 120.0],
        "integers": False,
    }
    path = str(tmp_path / "us.png")
    out = render_session_cards(
        path, [down, up], heading="美股現金　2026/10/16", columns=2
    )
    assert out == path
    img = mpimg.imread(path)
    assert img.shape[0] > 400 and img.shape[1] > 600
    # 左卡跌、填色在虛線下應偏綠；右卡漲、填色偏紅。
    h, w = img.shape[:2]
    left = img[int(h * 0.72) : int(h * 0.88), int(w * 0.12) : int(w * 0.38), :3]
    right = img[int(h * 0.72) : int(h * 0.88), int(w * 0.62) : int(w * 0.88), :3]
    assert float(left[:, :, 1].mean()) > float(left[:, :, 0].mean())
    assert float(right[:, :, 0].mean()) > float(right[:, :, 1].mean())
    empty = render_session_cards(str(tmp_path / "none.png"), [], heading="美股現金　2026/10/16", columns=2)
    assert empty == ""


def test_market_page_sends_cards_after_text():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_market_page)
    assert src.index("reply_html") < src.index("_send_market_session_cards")
    # 教具遠／近／超近先出；美股卡改後面（不准拖一分鐘才出第1張）
    assert src.index("_send_market_wave_charts") < src.index("_send_market_session_cards")
    assert "refresh_us_for_market_page" in src
    assert "assemble_session_cards" in src


def test_tick_zip_date_parser_reads_newest_file():
    from market_session_cards import latest_taifex_tick_zip_ymd

    html = "Daily_2026_10_19.zip later Daily_2026_10_16.zip"
    assert latest_taifex_tick_zip_ymd(html) == "20261019"
