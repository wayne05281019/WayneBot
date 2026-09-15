# -*- coding: utf-8 -*-
"""新文進六顆神經元：捕獲就分類，開火讀最近句，不改 SYSTEM。"""
import inspect
import sqlite3

from biaoke_chain import fire_chain
from biaoke_ingest import _after_ingest_analyze
from biaoke_neurons import classify_spoken, latest_bundle, record_neuron_events


def test_classify_c2_goes_to_nest():
    hits = classify_spoken("今天強彈反而提高警惕，小心逃命波C-2，不是已確認。")
    nids = {h["neuron"] for h in hits}
    assert "nest" in nids
    assert "doubt" in nids
    assert any(h["sid"] in ("", "TWII") for h in hits if h["neuron"] == "nest")


def test_classify_wenmao_standback_goes_to_tape():
    hits = classify_spoken("穩懋昨天跌破支撐立刻站回，近期會比台達電強")
    tape = [h for h in hits if h["neuron"] == "tape"]
    assert any(h["sid"] == "3105" for h in tape)
    quoted = classify_spoken('"健策要跌停了" 沒有，大盤還好')
    assert all(h.get("sid") != "3653" for h in quoted)


def test_record_and_fire_reads_latest(tmp_path):
    db = str(tmp_path / "n.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260915", "3105", "穩懋", 447.5, 476.0, 445.5, 454.0, 35312, 2.25),
    )
    conn.commit()
    conn.close()
    n = record_neuron_events(
        db,
        [
            {
                "id": "r1",
                "date": "2026-09-15",
                "time": "09:45",
                "kind": "reply",
                "text": "穩懋昨天跌破支撐立刻站回，近期會比台達電強",
            },
            {
                "id": "p1",
                "date": "2026-09-15",
                "time": "09:02",
                "kind": "post",
                "text": "今天強彈反而提高警惕，小心逃命波C-2，不是已確認。",
            },
        ],
    )
    assert n >= 2
    bundle = latest_bundle(db, "3105")
    assert "站回" in (bundle.get("tape") or "")
    assert "逃命波" in (bundle.get("nest") or "") or "C-2" in (bundle.get("nest") or "")
    fired = fire_chain(db, "穩懋怎麼看")
    assert fired["sid"] == "3105"
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "他自己最新" in tape["text"]
    assert "站回" in tape["text"]
    assert "他自己最新" in nest["text"]
    assert "C-2" in nest["text"] or "逃命波" in nest["text"]
    think = fired["think"]
    assert "站回" in think or "逃命波" in think or "C-2" in think
    assert "這族龍頭是 他自己最新" not in think


def test_ingest_hooks_neurons_immediately():
    src = inspect.getsource(_after_ingest_analyze)
    assert "record_neuron_events" in src
    assert "record_events" in src
    ingest_src = inspect.getsource(__import__("biaoke_ingest").ingest_public_posts)
    assert "backfill_recent_neurons" in ingest_src
    assert "n=160" in ingest_src or "n = 160" in ingest_src


def test_bystander_kind_not_filed(tmp_path):
    db = str(tmp_path / "b.db")
    n = record_neuron_events(
        db,
        [
            {
                "id": "x",
                "date": "2026-09-15",
                "time": "10:00",
                "kind": "bystander",
                "text": "小心逃命波C-2",
            }
        ],
    )
    assert n == 0
    assert latest_bundle(db, "") == {}


def test_classify_night_gold_uses_five_tools_not_keywords():
    nest = classify_spoken(
        "目前這兩天大盤(夜盤)在築底是好事，接下來看星期四或星期五反彈點位(夜盤)至少要46767。"
    )
    assert {h["neuron"] for h in nest} >= {"nest"}
    assert any(h["sid"] in ("", "TWII") for h in nest if h["neuron"] == "nest")
    tape = classify_spoken("後來收盤看到健策爆大量跌破平台，確認出現轉折，多頭結構被破壞的量價結構")
    assert any(h["neuron"] == "tape" and h["sid"] == "3653" for h in tape)
    hold = classify_spoken("我只要看到出現止漲整理K棒是一定會調節的。至於今天抽出的資金轉到創意，說實話，風險也很大。")
    nids = {h["neuron"] for h in hold}
    assert "hold" in nids
    assert "doubt" in nids or "field" in nids
    field = classify_spoken("上詮屬CPO／FAU，而聯亞屬光通訊 InP")
    assert "field" in {h["neuron"] for h in field}
    naked = classify_spoken("先要習慣裸K看盤，看股票要先看量再看價")
    assert "tape" in {h["neuron"] for h in naked}


def test_classify_c3_without_stock_is_nest_not_hold():
    hits = classify_spoken(
        "但是盤勢如果C-2 轉 C-3 還是要先調節一趟股票，可能來回差4000點，但應該C-3 修正末端在43500附近"
    )
    nids = {h["neuron"] for h in hits}
    assert "nest" in nids
    assert "hold" not in nids
    assert all(h["sid"] in ("", "TWII") for h in hits if h["neuron"] == "nest")


def test_classify_snippet_starts_at_name_not_mid_word():
    hits = classify_spoken(
        "健策多頭結構已經被破壞要進行整理，奇鋐也走到技術分析模糊地帶，明天只能上不能下。"
    )
    d3017 = [h for h in hits if h["neuron"] == "doubt" and h["sid"] == "3017"]
    assert d3017 and "奇鋐" in d3017[0]["snippet"]
    assert not any((h.get("snippet") or "").startswith("鋐") for h in hits)
    d3653 = [h for h in hits if h["neuron"] == "doubt" and h["sid"] == "3653"]
    if d3653:
        assert d3653[0]["snippet"].startswith("健策")


def test_classify_jian_ce_typo_maps_to_3653():
    hits = classify_spoken("建策破線，奇鋐今天技術分析來看非常模糊")
    assert any(h["sid"] == "3653" for h in hits)
    tape = classify_spoken("今天鑑測今天出現轉折K棒確認，所以我盤中先調節奇鋐1/2")
    assert any(h["sid"] == "3653" and h["neuron"] == "tape" for h in tape)
    assert any(h["sid"] == "3017" and h["neuron"] == "hold" for h in tape)
    assert not any(h["sid"] == "3653" and h["neuron"] == "hold" for h in tape)
    assert not any(h["sid"] == "3017" and h["neuron"] == "tape" for h in tape)


def _quotes(conn, sid, name, close=100.0):
    conn.execute(
        "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260915", sid, name, close, close + 10, close - 10, close, 1000, -1.0),
    )


def test_latest_bundle_named_ignores_empty_sid_and_other_sid(tmp_path):
    db = str(tmp_path / "leak.db")
    from biaoke_neurons import ensure_neuron_hits_table

    ensure_neuron_hits_table(db)
    conn = sqlite3.connect(db)
    conn.executemany(
        """
        INSERT INTO biaoke_neuron_hits
        (post_id, neuron_id, stock_id, stock_name, post_date, post_time, snippet)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            ("e1", "field", "", "", "2026-09-15", "20:11", "很有潛力，應該在光通訊，僅次於InP"),
            ("e2", "hold", "", "", "2026-09-15", "22:58", "C-3 還是要先調節一趟股票"),
            ("n1", "nest", "TWII", "加權", "2026-09-15", "22:58", "C-2 轉 C-3 還是要先調節"),
            ("t1", "tape", "3653", "健策", "2026-09-15", "18:22", "健策爆大量跌破平台，確認出現轉折"),
            ("f1", "field", "3653", "健策", "2026-09-15", "12:14", "散熱轉弱，轉一些到創意"),
            ("h1", "hold", "2383", "台光電", "2026-09-15", "10:28", "台光電先不用管，奇鋐要留意"),
            ("t2", "tape", "3363", "上詮", "2026-09-15", "20:09", "上詮回測頸線"),
        ],
    )
    conn.commit()
    conn.close()
    b3653 = latest_bundle(db, "3653")
    assert "僅次於InP" not in (b3653.get("field") or "")
    assert "光通訊" not in (b3653.get("field") or "")
    assert "散熱" in (b3653.get("field") or "")
    assert "爆大量" in (b3653.get("tape") or "")
    assert "C-3 還是要先調節一趟股票" not in (b3653.get("hold") or "")
    assert "C-3" in (b3653.get("nest") or "")
    b2383 = latest_bundle(db, "2383")
    assert "僅次於InP" not in (b2383.get("field") or "")
    assert "C-3 還是要先調節一趟股票" not in (b2383.get("hold") or "")
    assert "先不用管" in (b2383.get("hold") or "")
    b3363 = latest_bundle(db, "3363")
    assert "頸線" in (b3363.get("tape") or "")
    assert "爆大量" not in (b3363.get("tape") or "")
    unnamed = latest_bundle(db, "")
    assert "僅次於InP" in (unnamed.get("field") or "")


def test_rerecord_drops_stale_empty_hold(tmp_path):
    db = str(tmp_path / "stale.db")
    from biaoke_neurons import ensure_neuron_hits_table

    ensure_neuron_hits_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO biaoke_neuron_hits
        (post_id, neuron_id, stock_id, stock_name, post_date, post_time, snippet)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("p-c3", "hold", "", "", "2026-09-15", "22:58", "C-3 還是要先調節一趟股票"),
    )
    conn.commit()
    conn.close()
    n = record_neuron_events(
        db,
        [
            {
                "id": "p-c3",
                "date": "2026-09-15",
                "time": "22:58",
                "kind": "reply",
                "text": "但是盤勢如果C-2 轉 C-3 還是要先調節一趟股票",
            }
        ],
    )
    assert n >= 1
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT neuron_id, stock_id FROM biaoke_neuron_hits WHERE post_id='p-c3'"
    ).fetchall()
    conn.close()
    assert ("hold", "") not in rows
    assert any(r[0] == "nest" for r in rows)


def test_fire_named_does_not_splice_empty_sid(tmp_path):
    db = str(tmp_path / "fire.db")
    from biaoke_neurons import ensure_neuron_hits_table

    ensure_neuron_hits_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (date TEXT, stock_id TEXT, stock_name TEXT, "
        "open REAL, high REAL, low REAL, close REAL, volume INTEGER, pct_change REAL, "
        "PRIMARY KEY (date, stock_id))"
    )
    _quotes(conn, "3653", "健策", 5310)
    _quotes(conn, "2383", "台光電", 4510)
    conn.executemany(
        """
        INSERT INTO biaoke_neuron_hits
        (post_id, neuron_id, stock_id, stock_name, post_date, post_time, snippet)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            ("e1", "field", "", "", "2026-09-15", "20:11", "很有潛力，應該在光通訊，僅次於InP"),
            ("e2", "hold", "", "", "2026-09-15", "22:58", "C-3 還是要先調節一趟股票"),
            ("t1", "tape", "3653", "健策", "2026-09-15", "18:22", "健策爆大量跌破平台，確認出現轉折"),
        ],
    )
    conn.commit()
    conn.close()
    jian = fire_chain(db, "健策怎麼看")
    assert jian["sid"] == "3653"
    field = next(s for s in jian["steps"] if s["id"] == "field")
    hold = next(s for s in jian["steps"] if s["id"] == "hold")
    tape = next(s for s in jian["steps"] if s["id"] == "tape")
    think = jian["think"]
    assert "僅次於InP" not in field["text"]
    assert "C-3 還是要先調節一趟股票" not in hold["text"]
    assert "爆大量" in tape["text"]
    assert "波浪" in think or "關鍵K" in think or "碎形" in think
    emc = fire_chain(db, "台光電怎麼看")
    assert emc["sid"] == "2383"
    hold_e = next(s for s in emc["steps"] if s["id"] == "hold")
    assert "勿輕易調節" in hold_e["text"]
    assert "C-3 還是要先調節一趟股票" not in hold_e["text"]
    five = jian.get("five") or jian["think"]
    assert "輪動不是覆巢" in five
    emc_five = emc.get("five") or emc["think"]
    assert "續抱" in emc_five or "沒破線" in emc_five
    assert "輪動不是覆巢" not in emc_five
