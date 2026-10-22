# -*- coding: utf-8 -*-
"""台指電子盤：zip 逾時／失敗 → 庫內日夜盤／分 K 備援。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

TP = ZoneInfo("Asia/Taipei")


def _seed_futures(db: str) -> None:
    from taiwan_market import ensure_futures_daily_table

    ensure_futures_daily_table(db)
    conn = sqlite3.connect(db)
    rows = [
        # prior regular (for day chg)
        ("20261019", "TX", "regular", 46627.0, 46902.0, 46390.0, 46779.0, 46779.0, 100000),
        ("20261019", "TE", "regular", 2871.9, 2917.85, 2871.9, 2910.15, 2910.15, 400),
        # evening regular + night end label
        ("20261020", "TX", "regular", 46434.0, 46920.0, 46162.0, 46384.0, 46341.0, 95321),
        ("20261020", "TE", "regular", 2879.2, 2933.6, 2878.3, 2890.6, 2890.6, 353),
        ("20261021", "TX", "night", 46490.0, 47098.0, 46136.0, 46975.0, 46975.0, 30400),
        ("20261021", "TE", "night", 2891.0, 2957.6, 2872.0, 2934.9, 2934.9, 152),
    ]
    for day, sym, sess, o, h, lo, c, settle, vol in rows:
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?, ?, ?, '202610', ?, ?, ?, ?, ?, ?, 0, 0, 'taifex', 't')
            """,
            (day, sym, sess, o, h, lo, c, settle, vol),
        )
    conn.commit()
    conn.close()


def _seed_night_minutes(db: str) -> None:
    from kline_hop import save_minute_bars

    bars = []
    # 20261020 15:00 → 20261021 04:45（對應夜盤標籤 20261021）
    for hm, px, v in (
        ("1500", 46490.0, 800),
        ("1600", 46550.0, 600),
        ("1800", 46600.0, 500),
        ("2100", 46800.0, 700),
        ("2300", 46750.0, 400),
    ):
        bars.append({"t": f"20261020{hm}", "o": px, "h": px + 20, "l": px - 20, "c": px, "v": v})
    for hm, px, v in (
        ("0000", 46720.0, 300),
        ("0200", 46850.0, 350),
        ("0445", 46975.0, 280),
    ):
        bars.append({"t": f"20261021{hm}", "o": px, "h": px + 15, "l": px - 15, "c": px, "v": v})
    save_minute_bars("TX", "15", bars, db, source="taifex")


class _Boom:
    status_code = 500
    content = b""
    text = ""

    def raise_for_status(self):
        raise TimeoutError("ReadTimeout")


def test_zip_fail_falls_back_to_minute_bars(tmp_path, monkeypatch):
    from market_session_cards import fetch_tx_after_hours_card

    db = str(tmp_path / "m.db")
    _seed_futures(db)
    _seed_night_minutes(db)
    monkeypatch.setattr("config.get_db_path", lambda: db)
    monkeypatch.setattr(
        "market_session_cards._SESSION.get",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("ReadTimeout")),
    )
    monkeypatch.setattr(
        "market_session_cards._regular_settlement", lambda session, month: 46341.0
    )

    now = datetime(2026, 10, 21, 6, 30, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("missing") is False
    assert out.get("source") == "db:minute_bars"
    assert card.get("session") == "20261020"
    assert card.get("last") == 46975.0
    assert len(card.get("series") or []) >= 2
    assert card.get("board_mode") is None


def test_zip_fail_falls_back_to_futures_ohlc_when_no_minutes(tmp_path, monkeypatch):
    from market_session_cards import fetch_tx_after_hours_card, session_card_jobs

    db = str(tmp_path / "o.db")
    _seed_futures(db)
    monkeypatch.setattr("config.get_db_path", lambda: db)
    monkeypatch.setattr(
        "market_session_cards._SESSION.get",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("ReadTimeout")),
    )

    now = datetime(2026, 10, 21, 6, 30, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("missing") is False
    assert out.get("source") == "db:futures_daily"
    assert card.get("board_mode") == "sessions_ohlc"
    assert card.get("session") == "20261021"
    labels = [r["label"] for r in card.get("rows") or []]
    assert "台指期夜盤" in labels
    assert "電子期夜盤" in labels
    assert "台指期日盤" in labels
    jobs = session_card_jobs({"tx": out, "us": {}, "fear": None})
    assert len(jobs) == 1 and jobs[0][0] == "tx"
    assert "2026/10/21" in jobs[0][1]["heading"]
    assert "庫內" in str((out.get("card") or {}).get("source_label") or "")


def test_zip_success_still_preferred_over_db(tmp_path, monkeypatch):
    from market_session_cards import fetch_tx_after_hours_card

    db = str(tmp_path / "z.db")
    _seed_futures(db)
    _seed_night_minutes(db)
    monkeypatch.setattr("config.get_db_path", lambda: db)

    ticks = [
        ("20261020", "202610", "150100", 46490.0, 10),
        ("20261020", "202610", "210000", 46800.0, 20),
        ("20261021", "202610", "045953", 46975.0, 12),
    ]

    class _Resp:
        def __init__(self, status=200, content=b"x" * 2000, text=""):
            self.status_code = status
            self.content = content
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http")

    def _get(url, timeout=0):
        if "futPrevious30DaysSalesData" in url:
            return _Resp(text="Daily_2026_10_21.zip")
        if "Daily_2026_10_21.zip" in url:
            return _Resp(content=b"ZIP" + b"0" * 2000)
        return _Resp(status=404, content=b"")

    monkeypatch.setattr("market_session_cards._SESSION.get", _get)
    monkeypatch.setattr("market_session_cards._read_tick_zip", lambda blob: "ZIP")
    monkeypatch.setattr("market_session_cards.parse_tx_night_ticks", lambda text: list(ticks))
    monkeypatch.setattr(
        "market_session_cards._regular_settlement", lambda session, month: 46341.0
    )
    monkeypatch.setattr(
        "market_session_cards._tx_card_from_db",
        lambda now=None: (_ for _ in ()).throw(AssertionError("db fallback must not run")),
    )

    now = datetime(2026, 10, 21, 8, 0, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    assert out.get("missing") is False
    assert out.get("source") == "taifex_zip"
    assert (out.get("card") or {}).get("last") == 46975.0


def test_ohlc_board_render_passes_send_gate(tmp_path, monkeypatch):
    from bot_servers import WayneTelegramBot
    from market_session_cards import (
        build_tx_te_sessions_card_from_db,
        render_tx_electronic_board,
    )

    db = str(tmp_path / "r.db")
    _seed_futures(db)
    monkeypatch.setattr("config.get_db_path", lambda: db)
    now = datetime(2026, 10, 21, 6, 30, tzinfo=TP)
    card = build_tx_te_sessions_card_from_db(db, now)
    assert card and card.get("board_mode") == "sessions_ohlc"
    path = str(tmp_path / "tx_ohlc.png")
    out = render_tx_electronic_board(
        path, card, heading="台指電子盤　2026/10/21　庫內台指／電子日盤＋夜盤"
    )
    assert out == path
    assert os.path.getsize(path) >= 8_000
    assert WayneTelegramBot._market_landscape_chart_ok(path)


def test_omission_lines_accept_ohlc_board():
    from market_session_cards import omission_lines

    lines = omission_lines(
        {"missing": []},
        {
            "missing": False,
            "card": {
                "board_mode": "sessions_ohlc",
                "rows": [{"label": "台指期夜盤", "close": 1}],
            },
        },
        {"score": 50},
    )
    assert not any("台指電子盤" in x for x in lines)


def test_stale_minute_bars_do_not_beat_newer_futures_night(tmp_path, monkeypatch):
    """庫內夜盤列較新時，不准用更舊分 K 冒充現況。"""
    from kline_hop import save_minute_bars
    from market_session_cards import fetch_tx_after_hours_card

    db = str(tmp_path / "stale.db")
    _seed_futures(db)
    # 只留更舊一晚的分 K（週五夜），最新夜盤列仍是 20261021
    bars = []
    for hm, px in (("1500", 46926.0), ("2100", 47200.0), ("0445", 47366.0)):
        day = "20261016" if hm >= "1500" else "20261017"
        if hm < "1500":
            day = "20261017"
        bars.append(
            {
                "t": f"{day}{hm}",
                "o": px,
                "h": px + 10,
                "l": px - 10,
                "c": px,
                "v": 100,
            }
        )
    # fix Friday night: 16 evening → 17 morning
    bars = [
        {"t": "202610161500", "o": 46926.0, "h": 47000.0, "l": 46900.0, "c": 46950.0, "v": 100},
        {"t": "202610162100", "o": 47000.0, "h": 47200.0, "l": 46980.0, "c": 47100.0, "v": 120},
        {"t": "202610170445", "o": 47200.0, "h": 47366.0, "l": 47150.0, "c": 47366.0, "v": 90},
    ]
    save_minute_bars("TX", "15", bars, db, source="taifex")
    monkeypatch.setattr("config.get_db_path", lambda: db)
    monkeypatch.setattr(
        "market_session_cards._SESSION.get",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("ReadTimeout")),
    )
    now = datetime(2026, 10, 21, 6, 30, tzinfo=TP)
    out = fetch_tx_after_hours_card(now)
    card = out.get("card") or {}
    assert out.get("source") == "db:futures_daily"
    assert card.get("board_mode") == "sessions_ohlc"
    assert card.get("session") == "20261021"
    assert card.get("last") == 46975.0
