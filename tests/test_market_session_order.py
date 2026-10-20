# -*- coding: utf-8 -*-
"""大盤附圖順序：美股 → 台指電子盤 → 恐懼與貪婪；不用 VIX 冒充恐懼貪婪。"""
import inspect
import os

from cnn_fear import fear_greed_band, gauge_face


def test_session_card_jobs_order_us_tx_fear():
    from market_session_cards import session_card_jobs

    bundle = {
        "us": {
            "session": "20261016",
            "cards": [
                {
                    "name": "道瓊",
                    "last": 52002.41,
                    "prev": 52177.7,
                    "chg": -175.29,
                    "pct": -0.34,
                    "series": [52000 + i for i in range(5)],
                }
            ],
        },
        "tx": {
            "card": {
                "name": "台指電子盤",
                "session": "20261016",
                "last": 46140,
                "prev": 47284,
                "chg": -1144,
                "pct": -2.42,
                "series": [47000 - i * 20 for i in range(20)],
                "volumes": [10] * 20,
                "integers": True,
            }
        },
        "fear": {
            "score": 17.938,
            "face": "18",
            "band": "極度恐懼",
            "session": "20261016",
            "history": [{"label": "前一日", "face": "22", "band": "極度恐懼"}],
        },
    }
    kinds = [k for k, _ in session_card_jobs(bundle)]
    assert kinds == ["us", "tx", "fear"]
    heads = [spec["heading"] for _, spec in session_card_jobs(bundle)]
    assert heads[0].startswith("美股收盤")
    assert heads[1].startswith("台指電子盤")
    assert heads[2].startswith("恐懼與貪婪指數")


def test_send_path_source_has_locked_order_not_vix_card():
    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_market_session_cards)
    assert "session_card_jobs" in src
    assert "美股現金" not in src
    assert "恐慌指數　" not in src
    assert "恐懼與貪婪" in inspect.getsource(WayneTelegramBot._session_card_face)
    assert "台指電子盤" in inspect.getsource(WayneTelegramBot._session_card_face)


def test_fear_band_labels_match_gauge_lock():
    assert fear_greed_band(17.938, "extreme fear") == "極度恐懼"
    assert fear_greed_band(30, "fear") == "恐懼"
    assert fear_greed_band(50, "neutral") == "中立"
    assert fear_greed_band(60, "greed") == "貪婪"
    assert fear_greed_band(80, "extreme greed") == "極度貪婪"
    assert gauge_face(17.938) == "18"


def test_render_fear_greed_gauge_passes_send_gate(tmp_path):
    from bot_servers import WayneTelegramBot
    from market_session_cards import render_fear_greed_gauge

    fear = {
        "score": 17.938,
        "face": "18",
        "band": "極度恐懼",
        "band_en": "Extreme Fear",
        "session": "20261016",
        "history": [
            {"label": "當日", "date": "2026/10/16", "face": "18", "band": "極度恐懼", "color": "#e53935"},
            {"label": "前一交易日", "date": "2026/10/15", "face": "22", "band": "極度恐懼", "color": "#e53935"},
            {"label": "一週前", "date": "2026/10/09", "face": "46", "band": "中立", "color": "#f9a825"},
            {"label": "一個月前", "date": "2026/09/16", "face": "30", "band": "恐懼", "color": "#ef6c00"},
            {"label": "一年前", "date": "2025/10/16", "face": "22", "band": "極度恐懼", "color": "#e53935"},
        ],
    }
    path = str(tmp_path / "fear.png")
    out = render_fear_greed_gauge(path, fear, heading="恐懼與貪婪指數　2026/10/16")
    assert out == path
    assert os.path.getsize(path) >= 12_000
    assert WayneTelegramBot._market_landscape_chart_ok(path)


def test_tx_board_card_with_volume_passes_send_gate(tmp_path):
    from bot_servers import WayneTelegramBot
    from market_session_cards import render_tx_electronic_board

    card = {
        "name": "台指電子盤",
        "last": 46140,
        "prev": 47284,
        "chg": -1144,
        "pct": -2.42,
        "series": [47200 - i * 15 for i in range(40)],
        "xs": [i * 20 for i in range(40)],
        "ma": [47200 - i * 12 for i in range(40)],
        "volumes": [100 + (i % 7) * 30 for i in range(40)],
        "volume": 8000,
        "last_qty": 12,
        "high": 47300,
        "low": 46000,
        "asof_time": "04:55:00",
        "integers": True,
    }
    path = str(tmp_path / "tx.png")
    out = render_tx_electronic_board(path, card, heading="台指電子盤　2026/10/16")
    assert out == path
    assert WayneTelegramBot._market_landscape_chart_ok(path)


def test_us_grid_large_type_passes_send_gate(tmp_path):
    from bot_servers import WayneTelegramBot
    from market_session_cards import render_session_cards

    cards = []
    for name, last, chg, pct in (
        ("道瓊", 52002.41, -175.29, -0.34),
        ("S&P500", 7659.44, -84.62, -1.09),
        ("那斯達克", 26140.03, -573.0, -2.15),
        ("費城半導體", 11137.29, -443.93, -3.83),
    ):
        cards.append(
            {
                "name": name,
                "last": last,
                "prev": last - chg,
                "chg": chg,
                "pct": pct,
                "series": [last + (i - 10) * abs(chg) / 40 for i in range(30)],
            }
        )
    path = str(tmp_path / "us.png")
    out = render_session_cards(
        path, cards, heading="美股收盤　2026/10/16", columns=2, layout="grid"
    )
    assert out == path
    assert WayneTelegramBot._market_landscape_chart_ok(path)


def test_omission_lines_use_electronic_and_fear_not_vix():
    from market_session_cards import omission_lines

    lines = omission_lines(
        {"missing": ["道瓊"]},
        {"missing": True, "card": None},
        None,
    )
    assert "台指電子盤這次沒有官方走勢，不上圖" in lines
    assert "恐懼與貪婪指數這次沒有官方讀數，不上圖" in lines
    assert not any("恐慌指數" in x for x in lines)
