# -*- coding: utf-8 -*-
"""默默畫、覆盤、能講才開口。現在不准主動講。"""
from pathlib import Path

from silent_progress import (
    REVIEW_STEPS,
    WAVE_NEURONS_MATCH,
    capture_review_context,
    load_review_context,
    maybe_speak,
    night_review,
    pack_holes,
    simulate_next_legs,
    speak_line,
    speak_ready,
)


def test_speak_ready_stays_off():
    assert WAVE_NEURONS_MATCH is False
    assert speak_ready("twii") is False
    assert speak_ready("dongzhu") is False
    assert speak_ready("leave_zero") is False
    assert speak_ready("golden_buy") is False
    assert maybe_speak("twii") == ""
    assert maybe_speak("dongzhu") == ""
    assert maybe_speak("leave_zero") == ""


def test_speak_line_shape():
    line = speak_line(
        path="先守住他自己點過的低",
        level="45839",
        maybe="再測一次",
        prep="只看、不追",
        because="官方柱還沒碰到他的位",
        result="還沒走完",
    )
    assert "預計大盤走勢會是" in line
    assert "到45839有可能會發生" in line
    assert "建議現在要提前" in line
    assert "因為依照" in line


def test_simulate_next_legs_only_his_levels():
    legs = simulate_next_legs("逃命波C-2", 45862.0, [])
    ys = [float(x["y"]) for x in legs]
    assert 43500.0 in ys
    assert 45839.36 in ys
    blob = str(legs)
    assert "1-2-3-4-5" not in blob
    assert 17000 not in ys
    c5 = simulate_next_legs("C-5低點", 45511.0, [])
    c5y = [float(x["y"]) for x in c5]
    assert 43500.0 in c5y
    assert 45398.43 in c5y


def test_night_review_does_not_speak(tmp_path):
    db = str(tmp_path / "n.db")
    Path(db).write_text("")
    out = night_review(db)
    assert out.get("speak") is False
    assert out.get("dongzhu") == 0
    assert out.get("screen") == 0
    assert out.get("ai") == 0
    src = Path("silent_progress.py").read_text(encoding="utf-8")
    assert "send_telegram" not in src
    assert "TELEGRAM_BOT_TOKEN" not in src
    assert "snapshot_and_score_dongzhu" not in src
    assert "write_snapshot" not in src
    assert "score_dongzhu_picks" not in src
    assert "score_screen_picks" not in src
    assert "score_ai_fills" not in src
    assert "run_ai_desk" not in src
    assert "verify_due" not in src
    absorb = Path("biaoke_absorb.py").read_text(encoding="utf-8")
    assert "night_review" in absorb
    i = absorb.find("night_review")
    assert "send_telegram" not in absorb[i : i + 400]
    assert absorb.find('endswith("-0200")') < absorb.find("night_review")
    from dongzhu_tape import optimize_ready

    assert optimize_ready(19) is False


def test_capture_review_context_freezes_then_fills_missing(tmp_path):
    import sqlite3

    from silent_progress import capture_review_context, load_review_context

    db = str(tmp_path / "c.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE futures_daily (
            date TEXT, symbol TEXT, session TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER, pct_change REAL,
            source TEXT, updated_at TEXT,
            PRIMARY KEY (date, symbol, session)
        )
        """
    )
    conn.execute(
        "INSERT INTO futures_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "20260918",
            "TE",
            "night",
            100.0,
            102.0,
            99.0,
            101.0,
            10,
            1.0,
            "taifex",
            "2026-09-18T20:00:00",
        ),
    )
    conn.commit()
    conn.close()
    a = capture_review_context(db, "20260918")
    assert a.get("te_night", {}).get("close") == 101.0
    conn = sqlite3.connect(db)
    conn.execute("UPDATE futures_daily SET close=999 WHERE symbol='TE'")
    conn.commit()
    conn.close()
    b = capture_review_context(db, "20260918")
    assert b.get("te_night", {}).get("close") == 101.0
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE us_overnight (
            as_of TEXT PRIMARY KEY,
            ixic_pct REAL, sox_pct REAL, dji_pct REAL, spx_pct REAL,
            vix REAL, tsm_pct REAL, nvda_pct REAL, nq_f_pct REAL, regime TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO us_overnight VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("20260918", -1.2, -0.8, None, None, None, -0.5, None, None, "caution"),
    )
    conn.commit()
    conn.close()
    c = capture_review_context(db, "20260918")
    assert c.get("te_night", {}).get("close") == 101.0
    assert c.get("us", {}).get("ixic_pct") == -1.2
    assert c.get("us", {}).get("tsm_pct") == -0.5
    assert load_review_context(db, "20260918") == c
    src = Path("silent_progress.py").read_text(encoding="utf-8")
    assert "requests" not in src
    assert "refresh_us_overnight" not in src
    assert "yahoo" not in src.lower()
    assert src.find('"score_old"') < src.find('"record_forecast"') < src.find('"never_speak"')
    assert '"score_dongzhu"' not in src


def test_pack_holes_lists_missing_slots():
    holes = pack_holes({"te_night": {"close": 101.0}})
    assert "twii" in holes
    assert "biaoke" in holes
    assert "legs" in holes
    assert "tx_day" in holes
    assert "tx_night" in holes
    assert "te_day" in holes
    assert "us" in holes
    assert "te_night" not in holes
    full = pack_holes(
        {
            "twii": {"close": 45800},
            "biaoke": {"tag": "逃命波C-2", "direc": "down"},
            "legs": [{"y": 43500}],
            "tx_day": {"close": 45750},
            "tx_night": {"close": 45700},
            "te_day": {"close": 2090},
            "te_night": {"close": 2100},
            "us": {"ixic_pct": -1.0},
        }
    )
    assert full == []
    assert list(REVIEW_STEPS)[-1] == "never_speak"
    assert REVIEW_STEPS[0] == "complete_as_of"


def test_capture_freezes_twii_bar_for_review(tmp_path):
    import sqlite3

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE index_daily (
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, pct_change REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?)",
        ("20260918", "TWII", 45700, 45900, 45600, 45820, 1, 0),
    )
    conn.commit()
    conn.close()
    pack = capture_review_context(
        db,
        "20260918",
        extra={"biaoke": {"tag": "逃命波C-2", "direc": "down"}, "legs": [{"y": 43500}]},
    )
    assert pack["twii"]["close"] == 45820
    assert pack["biaoke"]["tag"] == "逃命波C-2"
    assert pack["legs"][0]["y"] == 43500
    holes = pack_holes(pack)
    assert "twii" not in holes
    assert "biaoke" not in holes
    assert "legs" not in holes
    assert "te_night" in holes
    assert "us" in holes


def test_silent_pack_stays_off_product_db(tmp_path):
    import sqlite3

    db = str(tmp_path / "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE index_daily (date TEXT)")
    conn.commit()
    conn.close()
    capture_review_context(
        db, "20260918", extra={"legs": [{"y": 43500}], "biaoke": {"tag": "逃命波C-2"}}
    )
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "silent_review_ctx" not in names
    pack = load_review_context(db, "20260918")
    assert pack.get("biaoke", {}).get("tag") == "逃命波C-2"


def test_silent_does_not_import_product_paths():
    src = Path("silent_progress.py").read_text(encoding="utf-8")
    for banned in (
        "screening_engine",
        "bot_servers",
        "decision_card",
        "industry_card",
        "wayne_navigator",
        "biaoke_field_scan",
        "record_twii(",
        "snapshot_and_score_dongzhu",
        "score_ai_fills",
        "run_ai_desk",
    ):
        assert banned not in src
    for path in (
        "screening_engine.py",
        "bot_servers.py",
        "decision_card_signals.py",
        "industry_card.py",
        "wayne_navigator.py",
        "dongzhu_judge.py",
        "biaoke_field_scan.py",
        "ai_trader.py",
    ):
        text = Path(path).read_text(encoding="utf-8")
        assert "silent_progress" not in text
        assert "snapshot_and_score_twii" not in text
