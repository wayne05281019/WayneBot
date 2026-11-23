# -*- coding: utf-8 -*-
"""SYNC-RETRACT：開火句形狀／改口・還在等・未完／警語／非買訊。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sync_retract import (
    PHONE_WARNING_FIXED,
    STATUS_OPEN,
    STATUS_RETRACT,
    STATUS_WAIT,
    attach_retract_to_teach_brief,
    decide_status,
    enrich_level_hit_html,
    format_fire_line,
    format_wave_retract_html,
    grade_level_vs_bars,
    run_sync_retract,
)


def _mk_db(tmp_path: Path, *, posts, bars) -> str:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, kind TEXT, text TEXT)"
    )
    conn.execute(
        "CREATE TABLE index_daily("
        "symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL)"
    )
    for p in posts:
        conn.execute(
            "INSERT INTO biaoke_posts VALUES (?,?,?,?,?)",
            (
                p["id"],
                p["date"],
                p.get("time", "10:00"),
                p.get("kind", "post"),
                p["text"],
            ),
        )
    for b in bars:
        conn.execute(
            "INSERT INTO index_daily VALUES (?,?,?,?,?,?)",
            (
                "TWII",
                b["date"],
                b.get("open", b["close"]),
                b["high"],
                b["low"],
                b["close"],
            ),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_fire_shape_wait_not_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "p1",
                "date": "2026-11-18",
                "time": "21:10",
                "text": "大盤先看 37837 支撐，不破再談反彈；夜盤觀察。",
            }
        ],
        bars=[
            {
                "date": "20261120",
                "open": 39000,
                "high": 39500,
                "low": 38800,
                "close": 39200,
            }
        ],
    )
    out = run_sync_retract(db, write_sample=False)
    assert out["buy_signal"] is False
    assert out["status"] == STATUS_WAIT
    fire = out["fire_line"]
    assert fire.startswith("開火：上一句位")
    assert "37837" in fire
    assert "還沒碰到" in fire or "還在等" in fire
    assert PHONE_WARNING_FIXED in fire
    assert "不是買訊" in format_wave_retract_html(payload=out) or "非買訊" in format_wave_retract_html(
        payload=out
    )


def test_fire_retract_when_he_said(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "p2",
                "date": "2026-11-19",
                "text": (
                    "大盤位階要重新修訂，改口：舊 23631 只參考；"
                    "現在先盯加權 25000 附近。"
                ),
            }
        ],
        bars=[
            {
                "date": "20261120",
                "open": 24800,
                "high": 25200,
                "low": 24600,
                "close": 24950,
            }
        ],
    )
    out = run_sync_retract(db)
    assert out["status"] == STATUS_RETRACT
    assert "改口" in out["fire_line"]
    assert "不准發明" in out["fire_line"] or "後文已改口" in out["fire_line"]
    assert PHONE_WARNING_FIXED in out["fire_line"]


def test_fire_retract_when_support_broke(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    # 純函式路徑：句無改口用語，但官方有效失守支撐
    sentence = {
        "post_id": "x",
        "date": "2026-11-10",
        "time": "09:30",
        "kind": "post",
        "text": "大盤守住 37837 支撐就不看更低。",
        "he_said_retract": False,
        "levels": [
            {
                "level": 37837.0,
                "face": "37837",
                "role": "support",
                "oral_role": "加權",
                "ctx": "守住 37837 支撐",
            }
        ],
    }
    bars = [
        {
            "date": "20261120",
            "open": 37000,
            "high": 37200,
            "low": 36500,
            "close": 36800,
        }
    ]
    grades = [
        grade_level_vs_bars(37837.0, "support", bars),
    ]
    assert grades[0]["broke"] is True
    status = decide_status(sentence=sentence, grades=grades, bars=bars)
    assert status == STATUS_RETRACT
    fire = format_fire_line(
        status=status, sentence=sentence, grades=grades, bars=bars
    )
    assert "改口條件觸發" in fire
    assert "37837" in fire
    assert PHONE_WARNING_FIXED in fire


def test_open_when_no_official(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: False
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "p3",
                "date": "2026-11-21",
                "text": "大盤盯 41900，夜盤先看結構。",
            }
        ],
        bars=[
            {
                "date": "20261121",
                "open": 42000,
                "high": 42100,
                "low": 41800,
                "close": 41950,
            }
        ],
    )
    out = run_sync_retract(db)
    assert out["status"] == STATUS_OPEN
    assert "未完" in out["fire_line"]


def test_leave_noise_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "leave",
                "date": "2026-11-22",
                "text": "不想再發文 壓力很大 被檢舉。",
            },
            {
                "id": "ok",
                "date": "2026-11-20",
                "text": "加權先看 40816，夜盤確認後明早大盤觀察。",
            },
        ],
        bars=[
            {
                "date": "20261121",
                "open": 41000,
                "high": 41200,
                "low": 40700,
                "close": 40900,
            }
        ],
    )
    out = run_sync_retract(db)
    assert out["sentence"]["post_id"] == "ok"
    assert "40816" in out["fire_line"]


def test_attach_teach_brief_and_level_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "p4",
                "date": "2026-11-18",
                "text": "大盤 45546 關前觀察，夜盤先看。",
            }
        ],
        bars=[
            {
                "date": "20261120",
                "open": 45000,
                "high": 45600,
                "low": 44800,
                "close": 45200,
            }
        ],
    )
    brief = "<b>波浪位階・預估・非買訊</b>\n目前落在：測試"
    merged = attach_retract_to_teach_brief(brief, db)
    assert "改口開火" in merged
    assert "開火：上一句位" in merged
    assert PHONE_WARNING_FIXED in merged
    # idempotent
    assert attach_retract_to_teach_brief(merged, db) == merged

    hit = "<b>飆大提醒·大盤碰到關卡</b>\n今天加權碰到他講過的 45546。\n不是買訊"
    enriched = enrich_level_hit_html(hit, db)
    assert "開火：" in enriched
    assert "不是買訊" in enriched


def test_write_sample_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trading_calendar.is_official_daily_bar", lambda day, **kw: True
    )
    root = tmp_path / "manual"
    root.mkdir()
    (root / "atoms_latest.json").write_text(
        json.dumps(
            {
                "atoms": [
                    {
                        "atom_id": "retract.revise_general",
                        "theme": "retract",
                        "core": True,
                        "rule": "位階是預估：動態修正就重訂",
                        "levels": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db = _mk_db(
        tmp_path,
        posts=[
            {
                "id": "p5",
                "date": "2026-11-15",
                "text": "大盤 27000 支撐，不破續抱結構觀察。",
            }
        ],
        bars=[
            {
                "date": "20261116",
                "open": 27500,
                "high": 27800,
                "low": 27200,
                "close": 27600,
            }
        ],
    )
    # monkeypatch sample paths via write into root by temporarily pointing MANUAL
    import sync_retract as sr

    monkeypatch.setattr(sr, "MANUAL", root)
    monkeypatch.setattr(sr, "SAMPLE_PATH", root / "sync_retract_latest.json")
    monkeypatch.setattr(sr, "SAMPLE_MD", root / "sync_retract_latest.md")
    out = run_sync_retract(db, root=root, write_sample=True)
    assert out["retract_atoms_n"] == 1
    assert (root / "sync_retract_latest.json").is_file()
    blob = json.loads((root / "sync_retract_latest.json").read_text(encoding="utf-8"))
    assert blob["rule_id"] == "WR-RETRACT-COND"
    assert blob["golden_buy_untouched"] is True
