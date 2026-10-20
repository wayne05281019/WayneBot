# -*- coding: utf-8 -*-
"""2026-10-18 台股大盤：美股現金對齊開頭、恐懼貪婪、元不換行、外資句、盤後圖尺寸。"""
import os
import sqlite3

from tg_layout import _disp_w, _html_plain


FRIDAY_US = {
    "ok": True,
    "regime": "caution",
    "us_session": "20261016",
    "us_phase": "overnight",
    "vix": 19.99,
    "vix_pct": 8.0,
    "dji_pct": -0.34,
    "dji_chg": -175.28,
    "spx_pct": -1.09,
    "spx_chg": -84.62,
    "ixic_pct": -2.15,
    "ixic_chg": -573.0,
    "sox_pct": -3.83,
    "sox_chg": -443.92,
    "cnn_fear": {"score": 17.938, "face": "18", "band": "極度恐懼", "rating": "extreme fear"},
}


def test_washout_replaces_bull_zero_risk_without_new_score():
    from taiwan_market import _page_regime_lines

    snap = {
        "regime": "bull",
        "regime_label": "多頭帶動",
        "regime_plus": "trend_up",
        "regime_plus_label": "多頭延伸",
        "falling_risk": 0,
    }
    plain = _html_plain("\n".join(_page_regime_lines(snap, FRIDAY_US)))
    assert "美股收盤大跌" in plain
    assert "下一個台股交易日不是平穩多頭日" in plain
    assert "不是還在往上" not in plain
    assert "不是風險 0" not in plain
    assert "美股現金" not in plain
    assert plain.count("那斯達克 -2.15%") == 1
    assert plain.count("費半 -3.83%") == 1
    assert plain.count("道瓊 -0.34%") == 1
    assert "往下跌的風險偏低，0 分" not in plain
    assert "分，100 分最危險" not in plain
    from tg_layout import _disp_w

    for ln in plain.splitlines():
        if ln.strip():
            assert _disp_w(ln) <= 36, ln


def test_us_drop_drops_fear_eased_lines():
    from taiwan_market import _drop_fear_lines_that_fight_us_drop

    kept = _drop_fear_lines_that_fight_us_drop(
        [
            "<b>環境觀察｜觀察 / 預警</b>",
            "開盤前，市場不怕。",
            "今天沒有外資賣得更兇的股票。",
            "害怕已經緩下來。",
            "害怕這件事今天沒特別變化。",
            "開盤前，市場在怕。",
        ]
    )
    blob = "\n".join(kept)
    assert "市場不怕" not in blob
    assert "害怕已經緩下來" not in blob
    assert "沒特別變化" not in blob
    assert "外資賣得更兇" in blob
    assert "市場在怕" in blob


def test_session_card_heading_says_us_close_not_cash():
    import inspect

    from bot_servers import WayneTelegramBot
    from market_session_cards import session_card_jobs

    src = inspect.getsource(WayneTelegramBot._send_market_session_cards)
    assert "session_card_jobs" in src
    assert "美股現金" not in src
    jobs = session_card_jobs(
        {
            "us": {"session": "20261016", "cards": [{"name": "道瓊", "series": [1, 2]}]},
            "tx": {"card": {"name": "台指電子盤", "session": "20261016", "series": [1, 2]}},
            "fear": {"score": 18, "session": "20261016"},
        }
    )
    heads = " ".join(spec["heading"] for _, spec in jobs)
    assert "美股收盤" in heads
    assert "台指電子盤" in heads
    assert "恐懼與貪婪指數" in heads
    assert "恐慌指數" not in heads


def test_mild_caution_keeps_taiwan_structure_lines():
    from taiwan_market import _page_regime_lines

    snap = {
        "regime": "bull",
        "regime_label": "多頭帶動",
        "regime_plus": "trend_up",
        "falling_risk": 0,
    }
    us = {
        "ok": True,
        "regime": "caution",
        "vix": 18.2,
        "dji_pct": -0.2,
        "spx_pct": -0.4,
        "ixic_pct": -0.9,
        "sox_pct": -1.6,
    }
    plain = _html_plain("\n".join(_page_regime_lines(snap, us)))
    assert "多頭帶動" in plain
    assert "還在往上" in plain
    assert "往下跌的風險偏低，0 分" in plain


def test_phone_usd_quote_stays_on_one_line():
    from taiwan_market import _us_quote_rows
    from us_overnight import _ADR_CASH_ITEMS

    snap = {
        "tsm_pct": -2.28,
        "tsm_chg": -9.64,
        "tsm_px": 412.61,
        "tsm_post_pct": -2.10,
        "tsm_post_chg": -8.70,
        "tsm_post_px": 403.91,
        "nvda_pct": -2.50,
        "nvda_chg": -4.80,
        "nvda_px": 187.20,
        "nvda_post_pct": -1.10,
        "nvda_post_chg": -2.05,
        "nvda_post_px": 185.15,
    }
    rows = _us_quote_rows(snap, _ADR_CASH_ITEMS)
    assert len(rows) == 4
    for row in rows:
        plain = _html_plain(row)
        assert "元)" in plain or "元）" in plain
        assert "美元" not in plain
        assert _disp_w(plain) <= 36, plain
        assert "\n" not in plain


def test_vix_block_keeps_19_99_and_adds_extreme_fear():
    from taiwan_market import _cnn_fear_lines, _format_overnight_watch_lines

    lines = _cnn_fear_lines(FRIDAY_US)
    plain = _html_plain("\n".join(lines))
    assert "18" in plain and "極度恐懼" in plain
    # 直接組美股塊：VIX 原文不改成別的數
    html = "\n".join(
        _format_overnight_watch_lines("", "20261016", {}, us_snap=FRIDAY_US)
    )
    text = _html_plain(html)
    assert "19.99" in text
    assert "跳升" in text
    assert "恐懼貪婪" in text and "極度恐懼" in text


def test_foreign_hedge_sentence_needs_both_series(tmp_path):
    from taiwan_market import ensure_futures_inst_oi_table, tx_foreign_short_hedge_line

    db = str(tmp_path / "oi.db")
    ensure_futures_inst_oi_table(db)
    conn = sqlite3.connect(db)
    # 官方 10/16 外資空單比 10/15 少，不能寫持續加碼。
    rows = [
        ("20261014", "外資及陸資", 11352, 98166),
        ("20261015", "外資及陸資", 9171, 106753),
        ("20261016", "外資及陸資", 9812, 103487),
        ("20261014", "自營商", 6449, 4135),
        ("20261015", "自營商", 10619, 3725),
        ("20261016", "自營商", 9000, 3000),
    ]
    for date, item, long_oi, short_oi in rows:
        conn.execute(
            """
            INSERT INTO futures_inst_oi(
                date, contract, item, oi_long, oi_short, oi_net, source, updated_at
            ) VALUES (?, '臺股期貨', ?, ?, ?, ?, 'taifex', 't')
            """,
            (date, item, long_oi, short_oi, long_oi - short_oi),
        )
    conn.commit()
    conn.close()
    assert tx_foreign_short_hedge_line(db, "20261016") == ""

    conn = sqlite3.connect(db)
    for date, short_oi in (("20261014", 1000), ("20261015", 1200), ("20261016", 1500)):
        conn.execute(
            """
            INSERT INTO futures_inst_oi(
                date, contract, item, oi_long, oi_short, oi_net, source, updated_at
            ) VALUES (?, '臺股期貨', '自營商(避險)', 10, ?, ?, 'taifex', 't')
            """,
            (date, short_oi, 10 - short_oi),
        )
    # 外資改成連續加空，避險也加空，才出那句。
    conn.execute(
        "UPDATE futures_inst_oi SET oi_short=110000 WHERE date='20261016' AND item='外資及陸資'"
    )
    conn.commit()
    conn.close()
    assert tx_foreign_short_hedge_line(db, "20261016") == "外資持續加碼放空及避險"
    # 頁面基準日沒有當日列，不准用前一日加空當成現在。
    assert tx_foreign_short_hedge_line(db, "20261017") == ""


def test_cnn_extreme_fear_band_and_gauge_rounds_official_score():
    from cnn_fear import fear_greed_band, gauge_face

    assert fear_greed_band(17.938, "extreme fear") == "極度恐懼"
    assert gauge_face(17.938) == "18"
    assert fear_greed_band(19.99, "") == "極度恐懼"
    assert fear_greed_band(19.99, "fear") == "恐懼"


def test_tx_after_hours_card_passes_send_gate(tmp_path):
    from bot_servers import WayneTelegramBot
    from market_session_cards import render_session_cards

    from market_session_cards import render_tx_electronic_board

    card = {
        "name": "台指電子盤",
        "last": 47366,
        "prev": 47242,
        "chg": 124,
        "pct": 0.26,
        "series": [46900 + i * 3 for i in range(40)],
        "xs": [i * 20 for i in range(40)],
        "ma": [46900 + i * 2 for i in range(40)],
        "volumes": [50 + i for i in range(40)],
        "volume": 3000,
        "last_qty": 8,
        "high": 47420,
        "low": 46880,
        "asof_time": "04:50:00",
        "integers": True,
    }
    path = str(tmp_path / "tx.png")
    out = render_tx_electronic_board(path, card, heading="台指電子盤　2026/10/16")
    assert out == path
    assert WayneTelegramBot._market_landscape_chart_ok(path)
    assert os.path.getsize(path) >= 12_000
