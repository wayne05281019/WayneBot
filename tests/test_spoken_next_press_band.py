# -*- coding: utf-8 -*-
"""飆大壓力區解析仍可測；查股／結構圖定案不畫「下一壓」帶。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from biaoke_claims import (
    official_volume_press_band,
    press_band_from_spoken_text,
    resolve_next_press_band,
    spoken_next_press_band,
)


_LIANYA_LINE = (
    "3.\t光通訊可分成三個部分來看，最飆悍的InP次族群聯亞剩下最後一個關卡"
    "壓力區3255~3305只要過了以後就非常有可能反彈轉回升。"
)


def test_press_band_binds_lianya_not_qunlian_or_shengmao():
    """族群聯亞≠群聯；3255~3305 右端≠昇貿代號。"""
    db = ""  # _compiled 仍有內建聯亞／群聯／昇貿
    assert press_band_from_spoken_text(_LIANYA_LINE, "3081", db_path=db) == (
        3255.0,
        3305.0,
    )
    assert press_band_from_spoken_text(_LIANYA_LINE, "8299", db_path=db) is None
    assert press_band_from_spoken_text(_LIANYA_LINE, "3305", db_path=db) is None
    assert press_band_from_spoken_text(_LIANYA_LINE, "2330", db_path=db) is None


def test_press_band_requires_named_stock():
    assert (
        press_band_from_spoken_text("大盤壓力區22000~22500", "3081", db_path="")
        is None
    )
    assert press_band_from_spoken_text(
        "3081 壓力區 3255～3305", "3081", db_path=""
    ) == (3255.0, 3305.0)


def _seed_lianya_db(tmp_path: Path) -> str:
    db = str(tmp_path / "press_band.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY(date, stock_id)
        );
        CREATE TABLE biaoke_posts(
            id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT,
            kind TEXT DEFAULT 'post', parent TEXT DEFAULT ''
        );
        """
    )
    day = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO biaoke_posts(id,date,time,text,kind) VALUES(?,?,?,?,?)",
        ("p-lianya", day, "09:43", _LIANYA_LINE, "post"),
    )
    for i in range(1, 30):
        d = f"202609{i:02d}" if i <= 30 else f"202610{i-30:02d}"
        c = 2800.0 + i * 10
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,"
            "open,high,low,close,volume) VALUES(?,?,?,?,?,?,?,?,?)",
            (d, "3081", "聯亞", "TW", c - 20, c + 40, c - 40, c, 5000 + i),
        )
    conn.commit()
    conn.close()
    return db


def test_spoken_next_press_band_from_db(tmp_path):
    db = _seed_lianya_db(tmp_path)
    assert spoken_next_press_band(db, "3081", "聯亞") == (3255.0, 3305.0)
    assert spoken_next_press_band(db, "3081", "") == (3255.0, 3305.0)
    assert spoken_next_press_band(db, "2330", "台積電") is None


def test_structure_builders_do_not_auto_paint_next_press():
    """使用者定案：查股／結構圖不准自動上「下一壓」帶。"""
    import inspect

    from biaoke_chart import build_biaoke_structure_chart, render_biaoke_structure_png
    from three_in_one_chart import render_lookup_structure_result

    from biaoke_chart import _structure_render_memo_key

    build_src = inspect.getsource(build_biaoke_structure_chart)
    lookup_src = inspect.getsource(render_lookup_structure_result)
    render_src = inspect.getsource(render_biaoke_structure_png)
    memo_src = inspect.getsource(_structure_render_memo_key)
    band_src = render_src + memo_src
    assert "resolve_next_press_band" not in build_src
    assert "resolve_next_press_band" not in lookup_src
    assert 'f"下一壓' not in render_src
    assert "下一壓 " not in render_src
    assert (
        "hdr-band-v78j-axis-card" in band_src
        or "hdr-band-v78h-quote-ink" in band_src
        or "hdr-band-v78g-close-half" in band_src
        or "hdr-band-v78f-gap-tighten" in band_src
        or "hdr-band-v78e-dash-rails" in band_src
        or "hdr-band-v78d-label-gaps" in band_src
        or "hdr-band-v78c-c-polish" in band_src
        or "hdr-band-v77-vol-min-visible" in band_src
    )
    # 桃色主大量區可用 axhspan（_WINDOW_BG）；不准自動下一壓帶
    assert "press_band=None" in render_src or "press_band" in render_src
    assert "_WINDOW_BG" in render_src or "resolve_next_press_band" not in render_src
    assert "下一壓帶" not in render_src and "spoken_next_press" not in render_src


def test_official_volume_press_band_from_zone():
    assert official_volume_press_band(zone_lo=2940, zone_hi=3255) == (2940.0, 3255.0)
    assert official_volume_press_band(zone_lo=0, zone_hi=3255) is None


def test_resolve_prefers_spoken_over_official(tmp_path):
    db = _seed_lianya_db(tmp_path)
    assert resolve_next_press_band(
        db, "3081", "聯亞", zone_lo=2940, zone_hi=3255
    ) == (3255.0, 3305.0)
    assert resolve_next_press_band(
        db, "2330", "台積電", zone_lo=1000, zone_hi=1200
    ) == (1000.0, 1200.0)


def test_next_press_not_level_note_anymore():
    """拿掉下一壓後，不再當壓／撐同級標籤。"""
    from biaoke_chart import _is_level_note

    assert _is_level_note("壓 3255")
    assert _is_level_note("撐 2940")
    assert not _is_level_note("下一壓 3255~3305")
