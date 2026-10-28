# -*- coding: utf-8 -*-
"""WB-68 資金輪動＋洞燭剩餘真怪（純文字；不渲圖）。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def test_share_path_keeps_mid_peak():
    from biaoke_field_scan import _share_path_body, _share_path_lines

    body = _share_path_body([0.0, 28.3, 8.0, 4.1, 8.5])
    assert "28.3%" in body
    assert body.startswith("0.0%")
    assert body.endswith("8.5%")
    lines = _share_path_lines(
        {"shares": [0.0, 28.3, 8.0, 4.1, 8.5], "share_chg": 4.4, "share_up": 8.5}
    )
    blob = "\n".join(lines)
    assert "28.3%" in blob


def test_lag_capture_count_matches_n():
    from biaoke_field_scan import _lag_capture_count_line

    assert "1 檔" in _lag_capture_count_line(1)
    assert "兩到三" not in _lag_capture_count_line(1)
    assert "兩檔" in _lag_capture_count_line(2)
    assert "三檔" in _lag_capture_count_line(3)


def test_dongzhu_page_rec_count_and_no_share_dup(tmp_path, monkeypatch):
    from biaoke_field_scan import dongzhu_page

    data = {
        "cap": "20261027",
        "chip_cap": "20261027",
        "field": "筆記型電腦",
        "layers": ("電子下游", "電腦", "筆記型電腦"),
        "flow": {
            "shares": [0.0, 28.3, 8.0, 4.1, 8.5],
            "nets": [0, 100, 50, 20, 30],
            "share_last": 8.5,
            "share_chg": 4.4,
            "share_up": 8.5,
            "last": 30,
            "cum5": 200,
            "flowing_in": True,
        },
        "pre_sign": "pre",
        "recs": [{"sid": "2364", "name": "倫飛", "vs20": -12.1}],
        "buys": [],
        "laggards": [{"sid": "2364", "name": "倫飛", "vs20": -12.1}],
        "leader": {"sid": "3231", "name": "緯創", "vs20": -5.0, "broke": False},
        "named": ["筆記型電腦"],
        "why": "",
        "inflow_board": "",
        "flow_window": 5,
        "in_lead_n": 0,
        "share_pos_n": 3,
    }
    monkeypatch.setattr(
        "biaoke_field_scan._dongzhu_query_stamp_line",
        lambda *_a, **_k: "查詢 2026/10/28（三）15:13（已收盤）",
    )
    monkeypatch.setattr(
        "biaoke_field_scan._dongzhu_post_cash_pre_fuse_note",
        lambda *_a, **_k: "今日盤後資料未齊，先機依 2026/10/27 完整日（約 16:30 盤後匯入後換今日）",
    )
    html = dongzhu_page(str(tmp_path / "x.db"), data=data)
    assert "這型最落後次級 1 檔" in html
    assert "兩到三檔" not in html
    assert "資金進出" in html
    assert "28.3%" in html
    assert "開盤前" not in html
    assert "層級 主→次→鏈" in html
    assert "·輪動" in html
    assert "輪動進產業鏈" in html
    # 此刻最像不重印近N日佔比摘要（留給資金進出）
    assert html.count("近5日佔比") <= 1


def test_price_strong_chip_out_bridge():
    from money_flow import _price_strong_chip_out_bridge

    out = [
        {
            "industry": "光電業",
            "three_net": -100000,
            "top_sells": [
                {"stock_id": "2409", "stock_name": "友達", "three_net": -95000},
                {"stock_id": "3481", "stock_name": "群創", "three_net": -3000},
            ],
        }
    ]
    html = _price_strong_chip_out_bridge(
        "光電業",
        out,
        live_reps=[
            {"stock_id": "2409", "stock_name": "友達", "pct_change": 6.3},
            {"stock_id": "3008", "stock_name": "大立光", "pct_change": 2.0},
        ],
    )
    assert "價漲錢出" in html
    assert "不是買訊" in html
    assert "友達" in html
    assert "法人賣超" in html
    assert _price_strong_chip_out_bridge("半導體業", out) == ""


def test_accel_skips_inflow_overlap():
    """較前日加碼略過已在流入前三的族（部分重疊也去重）。"""
    from money_flow import format_sector_rotation_html
    import os
    import sqlite3
    import tempfile
    from unittest import mock

    from wayne_db import ensure_core_schema

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        conn = sqlite3.connect(path)
        now = "2026-10-27T00:00:00"
        # 流入＝半導體大買；加速也含半導體＋電腦週邊 → 加碼只應剩電腦週邊
        stocks = [
            ("2330", "台積電", "半導體業", 8000, 2000),
            ("2454", "聯發科", "半導體業", 3000, 1000),
            ("2301", "光寶科", "電腦及週邊設備業", 2500, 500),
            ("2357", "華碩", "電腦及週邊設備業", 1500, 400),
            ("2409", "友達", "光電業", -9000, -1000),
            ("3481", "群創", "光電業", -5000, -500),
        ]

        def ins(date, sid, name, fn, tn):
            conn.execute(
                """
                INSERT INTO daily_quotes(
                    date, stock_id, stock_name, market, open, high, low, close, volume,
                    turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
                ) VALUES (?, ?, ?, 'TW', 100, 101, 99, 100, 5000, 500000, 1.0, 100, ?, ?, 0)
                """,
                (date, sid, name, fn, tn),
            )

        for sid, name, ind, fn, tn in stocks:
            conn.execute(
                """
                INSERT INTO stock_universe(
                    stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at
                ) VALUES (?, ?, 'TWSE', 'STOCK', ?, 1, ?)
                """,
                (sid, name, ind, now),
            )
            # 前日：半導體／電腦較少買；今日加碼
            ins("20261026", sid, name, fn // 4, tn // 4)
            ins("20261027", sid, name, fn, tn)
        conn.commit()
        conn.close()
        from money_flow import recompute_sector_flow

        recompute_sector_flow(path, "20261027")
        with mock.patch("live_quote.is_live_merge_window", return_value=False):
            html = format_sector_rotation_html(
                path, "20261027", now=datetime(2026, 10, 28, 15, 13, tzinfo=TAIPEI)
            )
        assert "資金流入" in html
        assert "半導體" in html
        # 加碼段若出現，不准把已在流入的半導體整段再印一輪
        if "較前日加碼" in html:
            accel = html.split("較前日加碼", 1)[1]
            assert "＝＝半導體業＝＝" not in accel
        assert "開盤前" not in html
    finally:
        os.remove(path)


def test_sector_sells_skip_positive_lots():
    from money_flow import _sector_entry

    html = _sector_entry(
        {
            "industry": "玻璃陶瓷業",
            "three_net": -100,
            "avg_pct": -0.2,
            "three_delta": -50,
            "top_sells": [
                {"stock_id": "1802", "stock_name": "台玻", "three_net": -80},
                {"stock_id": "9914", "stock_name": "凱撒衛", "three_net": 1},
            ],
        }
    )
    assert "台玻" in html
    assert "凱撒衛" not in html
    assert "+1" not in html and "＋1" not in html
