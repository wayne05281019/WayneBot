# -*- coding: utf-8 -*-
"""飆大每一則目標價／支撐／例子：當日價、後來實價、前後互參。"""
from __future__ import annotations

import sqlite3

from biaoke_claims import extract_claims, file_biaoke_claims, format_stock_claims


def test_extract_zhiyuan_support_and_target():
    hits = extract_claims("智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！")
    assert any(
        h["stock_id"] == "3035" and h["role"] == "support" and abs(h["lo"] - 370) < 0.01
        for h in hits
    )
    hits2 = extract_claims(
        "智原底部型態已經出來了，這波第一目標價397，第二目標價41*，我就不說了，怕影響盤勢！"
    )
    targs = [h for h in hits2 if h["role"] == "target" and h["stock_id"] == "3035"]
    assert any(abs(h["lo"] - 397) < 0.01 for h in targs)
    assert not any(h.get("lo") == 41 for h in targs)


def test_extract_skips_unbound_and_keeps_index():
    assert extract_claims("這檔股票主力目標價明年一月至少250，做空深思，否則非死即傷！") == []
    night = extract_claims("今晚夜盤至少要穿越46506為今晚觀盤重點。")
    assert any(
        h["stock_id"] == "TWII" and h["role"] == "target" and abs(h["lo"] - 46506) < 0.1
        for h in night
    )


def test_extract_feijie_range_and_lianya_example():
    fei = extract_claims(
        "至於 AI PC領頭羊飛捷我昨天已經說過完成修正，只要135附近之後C波修正不破，必創新高至少200以上。"
    )
    roles = {(h["role"], round(float(h["lo"]))) for h in fei if h.get("lo")}
    assert ("support", 135) in roles
    assert ("target", 200) in roles
    assert all(h["stock_id"] == "6206" for h in fei if h.get("lo"))
    ex = extract_claims(
        "聯亞爆大量到壓力線反彈目標區約2000～2200，走勢會像健策，要等底部型態完成才有真正進場點"
    )
    targs = [h for h in ex if h["role"] == "target" and h["stock_id"] == "3081"]
    assert targs and abs(targs[0]["lo"] - 2000) < 0.1 and abs(targs[0]["hi"] - 2200) < 0.1
    analog = [h for h in ex if h["role"] == "example"]
    assert analog
    assert analog[0]["stock_id"] == "3081"
    assert analog[0]["analog_id"] == "3653"
    fan = extract_claims(
        "台積電設備檢測設備股泛銓(6830)，今天型態確認，有興趣的同學可在尾盤前買進投入資金全部持股或至少2/3，目標會測210~220。"
    )
    targs = [
        h
        for h in fan
        if h["role"] == "target" and h["stock_id"] == "6830" and h.get("lo")
    ]
    assert any(abs(h["lo"] - 210) < 0.1 and abs(h["hi"] - 220) < 0.1 for h in targs)
    assert not any(h.get("lo") in (2, 3) for h in targs)
    months = extract_claims("聯亞今天跌破平台至少要整理3個月，所有矽光子族群等第四季再觀察即可")
    assert not any(h.get("lo") == 3 for h in months)


def test_extract_wave_marks_missing_15m():
    hits = extract_claims("夜盤15分走出5段、下降軌破壞，今晚至少穿越46506。")
    waves = [h for h in hits if h["role"] == "wave"]
    assert waves
    assert "無數" in waves[0]["snippet"] or "不數" in waves[0]["snippet"]
    assert "夜盤" in waves[0]["snippet"]


def test_file_claims_then_price_and_later_hit(tmp_path):
    db = str(tmp_path / "c.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            turnover_k REAL, pct_change REAL, avg_price REAL,
            foreign_net REAL, trust_net REAL, dealer_net REAL,
            source TEXT, fetched_at TEXT,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    rows = [
        ("20231204", 392, 393.5, 374.5, 380, 23573),
        ("20231212", 385, 390, 378, 382, 12000),
        ("20231213", 388, 400, 380, 398, 15000),
        ("20231214", 399, 405, 395, 402, 11000),
    ]
    for d, o, h, lo, c, v in rows:
        conn.execute(
            "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "3035", "智原", "TW", o, h, lo, c, v),
        )
    conn.commit()
    conn.close()
    posts = [
        {
            "id": "a",
            "date": "2023-12-04",
            "time": "09:00",
            "kind": "post",
            "text": "智原這幾天支撐線370不跌破",
            "_sids": ["3035"],
            "_snames": ["智原"],
        },
        {
            "id": "b",
            "date": "2023-12-12",
            "time": "09:00",
            "kind": "post",
            "text": "智原這波第一目標價397，第二目標價41*",
            "_sids": ["3035"],
            "_snames": ["智原"],
        },
    ]
    stats = file_biaoke_claims(db, [(posts, 0)])
    assert stats["claims"] >= 2
    assert stats["targets"] >= 1
    assert stats["cross"] >= 1
    conn = sqlite3.connect(db)
    sup = conn.execute(
        "SELECT then_close, then_low, hit, next_date FROM biaoke_claims "
        "WHERE stock_id='3035' AND role='support' AND lo=370"
    ).fetchone()
    tgt = conn.execute(
        "SELECT then_close, hit, hit_date, prev_date FROM biaoke_claims "
        "WHERE stock_id='3035' AND role='target' AND lo=397"
    ).fetchone()
    ghost = conn.execute(
        "SELECT 1 FROM biaoke_claims WHERE stock_id='3035' AND lo=41"
    ).fetchone()
    conn.close()
    assert sup is not None
    assert abs(float(sup[0]) - 380) < 0.01
    assert abs(float(sup[1]) - 374.5) < 0.01
    assert "有守" in (sup[2] or "")
    assert str(sup[3]).startswith("2023-12-12")
    assert tgt is not None
    assert abs(float(tgt[0]) - 382) < 0.01
    assert "碰到" in (tgt[1] or "")
    assert str(tgt[2]).startswith("20231213")
    assert str(tgt[3]).startswith("2023-12-04")
    assert ghost is None
    html = format_stock_claims(db, "3035")
    assert "397" in html
    assert "當日收" in html
    assert "前次" in html or "後次" in html
    assert "不是買訊" in html
    assert "語料" not in html


def _wave_night_db(tmp_path):
    db = str(tmp_path / "c.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _night_post():
    return [
        {
            "id": "n1",
            "date": "2026-09-11",
            "time": "17:49",
            "kind": "post",
            "text": "夜盤15分走出5段、下降軌破壞，今晚至少穿越46506。",
            "_sids": ["TWII"],
            "_snames": ["加權"],
        }
    ]


def test_file_wave_night_without_tx_does_not_count(tmp_path):
    from kline_hop import save_minute_bars

    db = _wave_night_db(tmp_path)
    bars = []
    t = 9 * 60
    while t <= 13 * 60 + 15:
        hh, mm = divmod(t, 60)
        bars.append(
            {
                "t": f"20260911{hh:02d}{mm:02d}",
                "o": 46000,
                "h": 46100,
                "l": 45900,
                "c": 46050,
                "v": 1,
            }
        )
        t += 15
    save_minute_bars("TWII", "15", bars, db)
    stats = file_biaoke_claims(db, [(_night_post(), 0)])
    assert stats["claims"] >= 1
    conn = sqlite3.connect(db)
    hit = conn.execute(
        "SELECT hit FROM biaoke_claims WHERE role='wave'"
    ).fetchone()
    conn.close()
    assert hit
    blob = hit[0] or ""
    assert "夜盤" in blob
    assert "不數" in blob or "無數" in blob
    assert "46100" not in blob
    assert "日盤" not in blob


def test_file_wave_night_reports_tx_cover_without_counting(tmp_path):
    from kline_hop import save_minute_bars

    db = _wave_night_db(tmp_path)
    bars = []
    t = 15 * 60
    while t <= 16 * 60 + 45:
        hh, mm = divmod(t, 60)
        bars.append(
            {
                "t": f"20260911{hh:02d}{mm:02d}",
                "o": 46300,
                "h": 46400,
                "l": 46200,
                "c": 46350,
                "v": 1,
            }
        )
        t += 15
    bars.append(
        {
            "t": "202609120000",
            "o": 46600,
            "h": 46663,
            "l": 46580,
            "c": 46650,
            "v": 1,
        }
    )
    bars.append(
        {
            "t": "202609120445",
            "o": 46050,
            "h": 46100,
            "l": 46041,
            "c": 46080,
            "v": 1,
        }
    )
    save_minute_bars("TX", "15", bars, db, source="taifex")
    stats = file_biaoke_claims(db, [(_night_post(), 0)])
    assert stats["claims"] >= 1
    conn = sqlite3.connect(db)
    hit = conn.execute(
        "SELECT hit FROM biaoke_claims WHERE role='wave'"
    ).fetchone()
    conn.close()
    assert hit
    blob = hit[0] or ""
    assert "期交所" in blob
    assert "46663" in blob
    assert "46041" in blob
    assert "不發明" in blob
    assert "5段" not in blob.replace(" ", "") or "不發明" in blob


def test_refresh_wave_minute_hits_keeps_other_claims(tmp_path):
    from biaoke_claims import refresh_wave_minute_hits
    from kline_hop import save_minute_bars

    db = _wave_night_db(tmp_path)
    stats = file_biaoke_claims(db, [(_night_post(), 0)])
    assert stats["claims"] >= 1
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO biaoke_claims(
            claim_key, post_id, post_date, post_time, kind, club,
            stock_id, stock_name, analog_id, analog_name, role, verb,
            snippet, hit
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "keep-target",
            "x1",
            "2026-09-11",
            "10:00",
            "post",
            0,
            "2330",
            "台積電",
            "",
            "",
            "target",
            "目標",
            "目標價1000",
            "當日高還沒到",
        ),
    )
    conn.commit()
    conn.close()
    bars = []
    t = 15 * 60
    while t <= 16 * 60 + 45:
        hh, mm = divmod(t, 60)
        bars.append(
            {
                "t": f"20260911{hh:02d}{mm:02d}",
                "o": 46300,
                "h": 46400,
                "l": 46200,
                "c": 46350,
                "v": 1,
            }
        )
        t += 15
    bars.append(
        {
            "t": "202609120000",
            "o": 46600,
            "h": 46663,
            "l": 46580,
            "c": 46650,
            "v": 1,
        }
    )
    bars.append(
        {
            "t": "202609120445",
            "o": 46050,
            "h": 46100,
            "l": 46041,
            "c": 46080,
            "v": 1,
        }
    )
    save_minute_bars("TX", "15", bars, db, source="taifex")
    n = refresh_wave_minute_hits(db)
    assert n >= 1
    conn = sqlite3.connect(db)
    wave = conn.execute(
        "SELECT hit FROM biaoke_claims WHERE role='wave'"
    ).fetchone()
    keep = conn.execute(
        "SELECT hit FROM biaoke_claims WHERE claim_key='keep-target'"
    ).fetchone()
    conn.close()
    assert "期交所" in (wave[0] or "")
    assert "46663" in (wave[0] or "")
    assert keep[0] == "當日高還沒到"
