# -*- coding: utf-8 -*-
"""大盤位階只跟飆大自己點過的標籤走。"""
import inspect
import os

from biaoke_chain import fire_chain
from biaoke_digest import format_latest_focus
from biaoke_wave import (
    EYES,
    build_twii_degree_chart,
    degree_hits,
    degree_turns,
    ensure_wave_history,
    format_wave_now,
    format_wave_path,
    is_wave_question,
    last_two,
    locator_wave_legs,
    span_of,
    wave_abc_story,
    wave_chart_mark,
    wave_extend_rays,
    wave_path_points,
    wave_path_segments,
    locator_abc_legs,
    _hist_bits,
    _ymd,
)
from biaoke_why import is_why_query, lookup
from bot_servers import WayneTelegramBot


def test_wave_question_no_ticker():
    assert is_wave_question("現在是逃命波嗎")
    assert is_wave_question("目前大盤是屬於哪個位階 以波浪來看的話")
    assert is_wave_question("他技術線圖看到什麼")
    assert not is_wave_question("台光電怎麼看")
    assert not is_wave_question("46506 怎麼來")


def test_degree_hits_are_his_labels_only():
    hits = degree_hits("")
    tags = {h["tag"] for h in hits}
    aids = {h.get("aid") or "" for h in hits}
    dates = {h.get("date") or "" for h in hits}
    assert "A波低" in tags
    assert "位階二" in tags
    assert "第五波測底" in tags
    assert "修正末端" in tags
    assert "3-3-4調整" in tags
    assert "邪惡第五波" in tags
    assert "細微波主跌" in tags
    assert "160266701" not in aids
    assert not any(d.startswith("2023") for d in dates)
    assert any(h["date"] == "2024-03-19" and h["tag"] == "修正末端" for h in hits)
    assert not any(
        str(h.get("aid") or "").startswith("164375850") and h["tag"] == "逃命波C-2"
        for h in hits
    )
    last, prev = last_two("")
    assert last is not None
    assert last["tag"] == "逃命波C-2"
    assert "逃命波" in (last.get("quote") or "")
    assert prev is not None
    assert prev["tag"] in {"第五波測底", "頭肩底", "修正末端"}
    blob = " ".join(h.get("quote") or "" for h in hits)
    assert "蔡森" not in blob
    assert "廣達從細微波" not in blob


def test_degree_path_from_2024_not_invented_2023():
    path = format_wave_path("")
    assert "2023-12" in path
    assert "沒寫死" in path
    assert "2024-03-15" in path or "3-3-4" in path
    assert "細微波主跌" in path or "2025-03-04" in path
    assert "右肩" in path
    assert "2025-05-19" in path or "位階二" in path
    assert "A波低" in path
    assert "逃命波C-2" in path
    assert "17000" not in path
    turns = degree_turns("")
    assert turns
    assert turns[0]["date"] >= "2024-03-15"
    assert turns[-1]["tag"] == "逃命波C-2"
    tags = [t["tag"] for t in turns]
    assert tags == [t["tag"] for i, t in enumerate(turns) if i == 0 or t["tag"] != tags[i - 1]]


def test_format_wave_now_compares_and_turning():
    text = format_wave_now("")
    assert "第五波測底" in text or "逃命波" in text
    assert "開牌" in text or "漲不動" in text or "10:47" in text
    assert "位階二" in text or "修正末端" in text
    assert "A 波低" in text or "A波低" in text or "7/29" in text
    assert "精準" in text or "細微波" in text
    assert "不數" in text
    assert "不是買訊" in text
    assert "位階不講死" in text
    assert "17000" not in text
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    live = format_wave_now(db)
    assert "45839" in live
    assert "47578" in live
    assert "39385" in live or "39384" in live
    assert "45398" in live or "低於 45839" in live
    assert "22000" in live
    assert "20250311" in live or "3/11" in live or "21770" in live or "21769" in live
    assert "19660" in live or "24730" in live or "沒柱" in live or "台指期" in live


def test_why_wave_now_and_eyes():
    assert is_why_query("現在波浪位階")
    body = lookup("現在波浪位階")
    assert "位階二" in body
    assert "逃命波" in body
    assert "測底" in body or "修正末端" in body
    assert "不數" in body or "5／9" in body
    assert "2023-12" in body or "沒寫死" in body
    eyes = lookup("他技術線圖看到什麼")
    assert "KD" in eyes or "均線" in eyes
    assert "台積電" in eyes
    assert "7/29" in eyes or "A 波低" in eyes
    turn = lookup("看大盤轉折最準")
    assert "精準" in turn or "細微波" in turn
    assert "7/29" in turn
    assert EYES


def test_blank_focus_leads_with_degree():
    html = format_latest_focus("")
    assert "現在位階" in html
    assert "第五波測底" in html or "測底" in html or "逃命波" in html
    assert "位階不講死" in html
    assert "產業趨勢" in html
    assert "現在波浪位階" in html
    assert "位階他不講死" not in html
    assert len(html) < 2800


def test_nest_includes_his_degree():
    fired = fire_chain("", "目前大盤是屬於哪個位階 以波浪來看的話")
    nest = next(s for s in fired["steps"] if s["id"] == "nest")
    assert "第五波測底" in nest["text"] or "現在位階" in nest["text"] or "逃命波" in nest["text"]
    assert "不數" in nest["text"]
    think = fired["think"]
    assert "現在位階" in think or "逃命波" in think or "第五波測底" in think
    tape = next(s for s in fired["steps"] if s["id"] == "tape")
    assert tape.get("skip") is True


def test_twii_degree_chart_when_db_present(tmp_path):
    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
    dest = str(tmp_path / "twii-degree.png")
    built = build_twii_degree_chart(db, dest)
    assert built.get("ok")
    assert os.path.isfile(built.get("path") or "")
    assert os.path.getsize(built["path"]) > 12_000
    cap = built.get("caption") or ""
    assert "不是15分" in cap or "不是 15" in cap
    assert "不是買訊" in cap
    assert "轉折線" in cap
    assert "不數" in cap or "5／9" in cap
    assert "不是一路大B" in cap or "區間" in cap
    assert "延伸線" in cap
    assert "縮圖" in cap or "橙底" in cap or "橙框" in cap
    src_w = inspect.getsource(__import__("biaoke_wave").render_twii_degree_png)
    assert "日成交量" in src_w
    assert "height_ratios" in src_w
    assert "axv" in src_w
    src = inspect.getsource(WayneTelegramBot._send_biaoke_structure_chart)
    assert "is_wave_question" in src
    assert "_send_biaoke_twii_degree_chart" in src
    origin = inspect.getsource(WayneTelegramBot._send_biaoke_origin_charts)
    assert "is_wave_question" in origin
    assert "TWII" in origin


def test_ensure_wave_history_skips_in_pytest(tmp_path):
    r = ensure_wave_history(str(tmp_path / "no.db"))
    assert r.get("reason") in {"pytest", "no-db"}
    db = "data/wayne_market.db"
    if os.path.isfile(db):
        r2 = ensure_wave_history(db)
        assert r2.get("reason") == "pytest"
        assert r2.get("ok") is False


def test_hist_bits_checks_his_tx_levels(tmp_path):
    import sqlite3

    from taiwan_market import ensure_futures_daily_table, ensure_index_daily_table

    db = str(tmp_path / "wave-hist.db")
    ensure_index_daily_table(db)
    ensure_futures_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO index_daily(date,symbol,open,high,low,close,volume,pct_change,updated_at) "
        "VALUES ('20240319','TWII',19700,19800,19640,19720,1,0,'t')"
    )
    rows = [
        ("20240319", 19700, 19800, 19650, 19710),
        ("20240603", 21800, 21940, 21700, 21880),
        ("20240715", 24000, 24400, 23900, 24300),
    ]
    for d, o, h, lo, c in rows:
        conn.execute(
            """
            INSERT INTO futures_daily(
                date, symbol, session, contract_month, open, high, low, close,
                settlement, volume, open_interest, pct_change, source, updated_at
            ) VALUES (?, 'TX', 'regular', '', ?, ?, ?, ?, ?, 1, 1, 0, 'taifex', 't')
            """,
            (d, o, h, lo, c, c),
        )
    conn.commit()
    conn.close()
    bits = "。".join(_hist_bits(db))
    assert "19660" in bits
    assert "19650" in bits
    assert "對得上" in bits or "接近" in bits
    assert "21937" in bits
    assert "24730" in bits
    assert "還沒到他點的滿足" in bits


def test_wave_path_points_pins_intraday_and_a_low(tmp_path):
    import sqlite3

    from taiwan_market import ensure_index_daily_table

    db = str(tmp_path / "wave-path.db")
    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    rows = [
        ("20260729", 40000, 40100, 39385, 39500),
        ("20260730", 39600, 41000, 39500, 40800),
        ("20260731", 40800, 41200, 40400, 40900),
        ("20260910", 47000, 47600, 46800, 47200),
        ("20260911", 47200, 47400, 45840, 46200),
        ("20260912", 46200, 46800, 46000, 46500),
        ("20260913", 46500, 46700, 45500, 45600),
        ("20260914", 46010, 46050, 45398, 45862),
    ]
    extra = 0
    while len(rows) < 12:
        extra += 1
        rows.insert(0, (f"202607{10+extra:02d}", 48000, 48200, 47800, 47900))
    for d, o, h, lo, c in rows:
        conn.execute(
            "INSERT INTO index_daily(date,symbol,open,high,low,close,volume,pct_change,updated_at) "
            "VALUES (?, 'TWII', ?, ?, ?, ?, 1, 0, 't')",
            (d, o, h, lo, c),
        )
    conn.commit()
    conn.close()
    from biaoke_wave import _load_twii_bars

    bars = _load_twii_bars(db, n=90)
    pts = wave_path_points(db, bars)
    by_tag = {p["tag"]: p for p in pts}
    assert "A波低" in by_tag
    a = by_tag["A波低"]
    assert abs(float(a["y"]) - 39385) < 1
    assert _ymd(bars[int(a["i"])].get("date")) == "20260729"
    assert "逃命波C-2" in by_tag
    c2 = by_tag["逃命波C-2"]
    assert c2.get("pinned") is True
    assert _ymd(bars[int(c2["i"])].get("date")) == "20260914"
    labels = " ".join(p["tag"] for p in pts)
    assert "1-2-3-4-5" not in labels
    assert not any(str(p["tag"]).isdigit() for p in pts)


def test_two_big_b_are_different_spans():
    turns = degree_turns("")
    bs = [t for t in turns if t.get("tag") == "大B波"]
    assert len(bs) >= 2
    a = span_of(bs[0]["date"], bs[0]["tag"])
    b = span_of(bs[-1]["date"], bs[-1]["tag"])
    assert a["span"] != b["span"]
    assert "第4浪" in a["point_lab"]
    assert "A波後" in b["point_lab"]
    segs = wave_path_segments(
        [
            {"i": 1, "y": 21000, "tag": "大B波", **a},
            {"i": 8, "y": 45000, "tag": "大B波", **b},
        ]
    )
    assert len(segs) == 2
    assert segs[0]["span"] != segs[1]["span"]
    june = span_of("2026-06-27", "大B波")
    assert june["span"] == "2026-B"
    assert "A波後" in june["point_lab"]
    assert span_of("2024-06-02", "大B波")["span"] == "2024-w4"


def test_wave_chart_mark_is_short_abc():
    assert wave_chart_mark("A波低", "2026-A") == "A"
    assert wave_chart_mark("大B波", "2026-B") == "B"
    assert wave_chart_mark("逃命波C-2", "2026-C") == "C-2"
    assert wave_chart_mark("右肩", "2026-d2") == "2"
    legs = locator_wave_legs(
        [
            {"i": 1, "y": 40000, "tag": "A波低", "span": "2026-A", "span_color": "#2e7d32"},
            {"i": 8, "y": 46000, "tag": "大B波", "span": "2026-A", "span_color": "#2e7d32"},
            {"i": 12, "y": 45500, "tag": "逃命波C-2", "span": "2026-C", "span_color": "#6a1b9a"},
            {"i": 18, "y": 44000, "tag": "逃命波C-2", "span": "2026-C", "span_color": "#6a1b9a"},
        ]
    )
    labs = {str(x.get("lab") or "") for x in legs}
    assert "A" in labs
    assert "C" in labs
    assert "2026·第五波失敗改A" not in labs


def _abc_rows():
    rows = []
    # 6/23 高 → 7/29 低 → 9/8 高 → 9/15 收
    spec = [
        ("20260623", 47000, 48218.87, 46800, 47500),
        ("20260701", 45000, 45500, 44000, 44800),
        ("20260729", 41000, 41600, 39384.85, 39947),
        ("20260810", 42000, 43000, 41500, 42800),
        ("20260908", 46000, 47578.24, 45800, 47000),
        ("20260915", 45800, 46000, 45000, 45511.49),
    ]
    for d, o, h, lo, c in spec:
        rows.append({"date": d, "open": o, "high": h, "low": lo, "close": c})
    return rows


def test_wave_abc_story_a_then_b_same_july29():
    story = wave_abc_story(_abc_rows(), last_tag="逃命波C-2")
    assert story.get("a")
    assert story.get("b")
    assert story.get("c")
    assert int(story["a"]["i1"]) == int(story["b"]["i0"])
    assert _ymd(story["a"]["d0"]).endswith("0623")
    assert _ymd(story["a"]["d1"]).endswith("0729")
    assert abs(float(story["a"]["y0"]) - 48218.87) < 0.01
    assert abs(float(story["a"]["y1"]) - 39384.85) < 0.01
    assert float(story["a"]["y0"]) > float(story["a"]["y1"])
    assert _ymd(story["b"]["d1"]).endswith("0908")
    assert abs(float(story["b"]["y1"]) - 47578.24) < 0.01
    assert float(story["b"]["y1"]) > float(story["b"]["y0"])
    assert story["c"].get("unconfirmed") is True
    legs = locator_abc_legs(story)
    circ = [str(x.get("circle") or "") for x in legs]
    assert circ[:2] == ["A", "B"]
    assert "C" in circ
    assert legs[0]["circle_side"] == "mid-left"
    assert legs[1]["circle_side"] == "right"
    assert int(legs[0]["xs"][0]) < int(legs[1]["xs"][0]) or (
        int(legs[0]["xs"][0]) == int(story["a"]["i0"])
    )
    src = inspect.getsource(__import__("biaoke_wave").render_twii_degree_png)
    assert "locator_abc_legs" in src
    assert "k_on_top" in src
    assert "wave_path_segments" not in src


def test_wave_extend_rays_escape_c2_hits_worst():
    pts = [{"i": 10, "y": 45862.0, "tag": "逃命波C-2"}]
    rays = wave_extend_rays(pts, 12, "逃命波C-2")
    kinds = {r["kind"] for r in rays}
    assert "worst" in kinds
    worst = next(r for r in rays if r["kind"] == "worst")
    assert abs(float(worst["y"]) - 43500) < 1e-6
    labels = " ".join(str(r.get("label") or "") for r in rays)
    assert "最差43500" in labels
    assert "1-2-3-4-5" not in labels
    assert not any(str(r.get("label") or "").isdigit() for r in rays)
    src = inspect.getsource(build_twii_degree_chart)
    assert "wave_extend_rays" in src
    assert "record_twii" in src
