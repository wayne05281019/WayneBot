# -*- coding: utf-8 -*-
"""飆大明確下一壓區間 → 查股／結構圖可疊帶；不准發明、不准誤綁鄰檔。"""
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


def test_structure_builders_wire_spoken_band():
    import inspect

    from biaoke_chart import build_biaoke_structure_chart
    from three_in_one_chart import render_lookup_structure_result

    build_src = inspect.getsource(build_biaoke_structure_chart)
    lookup_src = inspect.getsource(render_lookup_structure_result)
    assert "resolve_next_press_band" in build_src
    assert "resolve_next_press_band" in lookup_src
    assert "press_band" in lookup_src


def test_official_volume_press_band_from_zone():
    assert official_volume_press_band(zone_lo=2940, zone_hi=3255) == (2940.0, 3255.0)
    assert official_volume_press_band(zone_lo=0, zone_hi=3255) is None


def test_resolve_prefers_spoken_over_official(tmp_path):
    db = _seed_lianya_db(tmp_path)
    # 聯亞有說過 3255~3305，不准被官方大量高低蓋掉
    assert resolve_next_press_band(
        db, "3081", "聯亞", zone_lo=2940, zone_hi=3255
    ) == (3255.0, 3305.0)
    # 沒講過：退回官方大量高低
    assert resolve_next_press_band(
        db, "2330", "台積電", zone_lo=1000, zone_hi=1200
    ) == (1000.0, 1200.0)


def test_next_press_label_survives_dedupe_near_spike():
    """聯亞：爆大量壓 3255 與下一壓 3255~3305 要同時留。"""
    from biaoke_chart import _dedupe_right_notes, _is_level_note, _px

    assert _is_level_note("下一壓 3255~3305")
    notes = [
        {"y": 3255.0, "text": f"壓 {_px(3255)}"},
        {"y": 3305.0, "text": f"下一壓 {_px(3255)}~{_px(3305)}"},
        {"y": 3255.0, "text": "最可能＝看壓 3255"},
        {"y": 2940.0, "text": f"撐 {_px(2940)}"},
    ]
    kept = {str(n.get("text") or "") for n in _dedupe_right_notes(notes, span=2000.0)}
    assert "下一壓 3255~3305" in kept
    assert "壓 3255" in kept
