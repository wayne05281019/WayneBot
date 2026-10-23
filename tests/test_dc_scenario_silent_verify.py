# -*- coding: utf-8 -*-
"""D.C 情境預估靜默日對質：排程鍵／隔離／文意欄／非買訊。"""
from __future__ import annotations

import inspect
import os
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dc_scenario_silent_verify import (
    align_wave_turns,
    DC_SF_START,
    JOB_KIND,
    LOCK_NAME,
    PIPE_PREFIX,
    LOOKBACK_HOURS,
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    WINDOW_END_MIN,
    WINDOW_START_MIN,
    biaoke_night_busy,
    build_why_card,
    compare_one,
    ensure_tables,
    fetch_dc_posts_within,
    in_campaign,
    in_dc_work_window,
    in_lookback,
    load_rules,
    meaning_diff_line,
    night_tick,
    persist_mismatch_learn,
    pipeline_key,
    propose_rule_updates,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def test_schedule_staggered_from_biaoke_0100():
    assert JOB_KIND == "dc_sf_silent"
    assert SCHEDULE_HOUR == 3 and SCHEDULE_MINUTE == 0
    assert WINDOW_START_MIN == 3 * 60 and WINDOW_END_MIN == 4 * 60
    assert LOOKBACK_HOURS == 24
    assert PIPE_PREFIX.startswith("dc-sf-silent")
    assert LOCK_NAME == "dc_sf_silent.lock"
    # 01:00–02:19 忙；03:00–04:00 才是本軌
    busy = datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI)
    free = datetime(2026, 10, 15, 3, 0, tzinfo=TAIPEI)
    assert biaoke_night_busy(busy) is True
    assert biaoke_night_busy(free) is False
    assert in_dc_work_window(free) is True
    assert in_dc_work_window(datetime(2026, 10, 15, 3, 59, tzinfo=TAIPEI)) is True
    assert in_dc_work_window(datetime(2026, 10, 15, 4, 0, tzinfo=TAIPEI)) is False
    assert in_dc_work_window(datetime(2026, 10, 15, 20, 40, tzinfo=TAIPEI)) is False


def test_campaign_window_and_pipeline_key():
    assert DC_SF_START == date(2026, 10, 15)
    assert in_campaign(datetime(2026, 10, 15, 3, 30, tzinfo=TAIPEI))
    assert in_campaign(datetime(2026, 12, 1, 3, 30, tzinfo=TAIPEI))
    assert not in_campaign(datetime(2026, 10, 14, 3, 30, tzinfo=TAIPEI))
    assert pipeline_key(date(2026, 10, 15)) == "dc-sf-silent-20261015"


def test_meaning_diff_and_compare_fields():
    md = meaning_diff_line(
        our_narrative="情境預估：已標(1)(2)，虛線(3)（不保證・不是買訊）",
        his_narrative="下降壓連 (v)–(b)，通道內往目標，轉多要站上",
    )
    assert "文意" in md or "他有" in md or "我們有" in md
    diff = compare_one(
        our_wave={
            "labels": ["(1)", "(2)"],
            "confirmed": [{"label": "(1)", "price": 100}, {"label": "(2)", "price": 80}],
            "projected": [],
            "abc": [],
            "zones": [],
            "wedge": False,
            "desc_press": {},
        },
        our_caption="不是買訊",
        our_narrative="上升衝動 (1)(2) 虛線",
        his_text="下降壓 通道 目標 轉多 (v)(a)(b) 4800",
    )
    assert diff.get("not_buy_signal") is True
    assert "meaning_diff" in diff
    assert isinstance(diff.get("has_actionable_diff"), bool)


def test_night_tick_out_of_campaign_and_isolation_notes():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        # 活動窗前
        r = night_tick(
            db,
            now=datetime(2026, 10, 14, 2, 20, tzinfo=TAIPEI),
            skip_if_done=False,
        )
        assert r.get("ok") is True
        assert r.get("notes") == "out_of_campaign"
        # 飆大夜窗延後
        r2 = night_tick(
            db,
            now=datetime(2026, 10, 15, 1, 5, tzinfo=TAIPEI),
            skip_if_done=False,
        )
        assert r2.get("notes") == "defer_biaoke_night_window"
        # 窗外（晚上 deploy）不准整批重畫
        r3 = night_tick(
            db,
            now=datetime(2026, 10, 15, 20, 40, tzinfo=TAIPEI),
            skip_if_done=False,
        )
        assert r3.get("notes") == "outside_dc_window"
        assert r3.get("ok") is True


def test_main_scheduler_wires_dc_sf_silent_isolated():
    import main as main_mod

    src = inspect.getsource(main_mod.run_scheduled_job)
    assert "dc_sf_silent" in src
    assert "dc_sf_night_tick" in src or "night_tick" in src
    assert "return" in src  # 專鍵提早 return，不走飆大 ingest 鏈
    slot_src = inspect.getsource(main_mod.start_daily_scheduler)
    assert "(3, 0, \"dc_sf_silent\")" in slot_src or "(3, 0, 'dc_sf_silent')" in slot_src
    absorb = open("biaoke_absorb.py", encoding="utf-8").read()
    assert "dc_sf_silent" in absorb and "互不影響" in absorb
    assert "03:00" in absorb and "04:00" in absorb


def test_catch_up_dc_sf_only_in_0300_0400_window():
    """補跑只 03:00–04:00；晚上／白天／deploy 不准再拉整輪渲圖。"""
    import main as main_mod

    src = inspect.getsource(main_mod.catch_up_missed_jobs)
    assert "(3 * 60)" in src or "3 * 60" in src
    assert "(4 * 60)" in src or "4 * 60" in src
    assert "need_dc_sf" in src
    assert "03:00–04:00" in src or "03:00-04:00" in src or "outside" in open(
        "dc_scenario_silent_verify.py", encoding="utf-8"
    ).read()


def test_scheduler_defers_catch_up_after_boot():
    """開機先聽筒、延後補跑，避免跟第一檔查股搶 2GB。"""
    import main as main_mod

    src = inspect.getsource(main_mod.start_daily_scheduler)
    assert "180" in src
    assert "先開聽筒" in src or "boot_catchup" in src or "_boot_catchup_delay" in src
    # §14：開機清 orphan morning-claim，不准空等租約
    assert "demote_orphaned_morning_claims" in src


def test_catch_up_skips_cache_while_morning_claim_fresh():
    """morning-claim 進行中不准背景補建海選快取（DB 互鎖根因）。"""
    import inspect

    import main as main_mod

    src = inspect.getsource(main_mod.catch_up_missed_jobs)
    assert "morning_claim_is_fresh_running" in src
    assert "略過背景補建海選快取" in src


def test_reclaim_stale_running_marks_error():
    from dc_scenario_silent_verify import (
        _mark_pipeline,
        reclaim_stale_running,
        stamp_status,
    )

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        day = date(2026, 10, 20)
        _mark_pipeline(db, day, "running", "killed mid-render")
        # 假裝 finished_at 很舊
        import sqlite3

        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "UPDATE pipeline_runs SET finished_at=? WHERE run_date=?",
                ("2026-10-20 03:40:00", "dc-sf-silent-20261020"),
            )
            conn.commit()
        finally:
            conn.close()
        now = datetime(2026, 10, 20, 20, 40, tzinfo=TAIPEI)
        assert reclaim_stale_running(db, day, now=now, stale_sec=600) is True
        hit = stamp_status(db, day)
        assert hit and hit.get("status") == "error"
        assert "stale_running_reclaim" in str(hit.get("notes") or "")
        # 已是 error：不再重降
        assert reclaim_stale_running(db, day, now=now, stale_sec=600) is False


def test_align_uses_our_bars_for_walked_turns_and_drawn_forecast():
    rows = [
        {"date": "d0", "high": 5000, "low": 4000},
        {"date": "d1", "high": 4800, "low": 3900},
        {"date": "d2", "high": 5100, "low": 4100},
    ]
    wave = {
        "start": {"i": 0, "price": 4000},
        "confirmed": [{"label": "(2)", "i": 1, "price": 3900, "kind": "L"}],
        "projected": [{"label": "(5)", "i": 10, "price": 100, "kind": "H"}],
        "abc": [],
    }
    out = align_wave_turns(
        wave,
        rows,
        {"his": {"(2)": 4100, "(5)": 5200}, "drawn": {"(5)": 2650}},
    )
    assert out["confirmed"][0]["i"] == 2
    assert out["confirmed"][0]["price"] == 4100
    assert out["projected"][0]["price"] == 2650
    assert out["projected"][0]["i"] == 10
    assert rows[1]["low"] == 3900
    assert out["path_proj"][-1][1] == 2650


def test_lookback_is_trailing_24h():
    now = datetime(2026, 10, 17, 3, 30, tzinfo=TAIPEI)
    assert in_lookback({"date": "2026-10-16", "time": "03:30"}, now)
    assert in_lookback({"date": "2026-10-17", "time": "03:30"}, now)
    assert not in_lookback({"date": "2026-10-16", "time": "03:29"}, now)
    assert not in_lookback({"date": "2026-10-17", "time": "03:31"}, now)


def test_fetch_within_stops_when_older_than_window(monkeypatch):
    rows = {
        "1": {"id": "1", "date": "2026-10-17", "time": "01:00", "text": "新文", "images": []},
        "2": {"id": "2", "date": "2026-10-15", "time": "01:00", "text": "舊文", "images": []},
        "3": {"id": "3", "date": "2026-10-17", "time": "02:00", "text": "不該再讀", "images": []},
    }
    seen = []

    def fetch_html(url, session=None):
        return "2590523"

    def parse_ids(html):
        return ["1", "2", "3"]

    def parse_article(aid, html):
        seen.append(str(aid))
        return rows[str(aid)]

    monkeypatch.setattr("biaoke_ingest.fetch_html", fetch_html)
    monkeypatch.setattr("biaoke_ingest.parse_user_article_ids", parse_ids)
    monkeypatch.setattr(
        "dc_scenario_silent_verify.parse_dc_article", parse_article
    )
    got = fetch_dc_posts_within(datetime(2026, 10, 17, 3, 30, tzinfo=TAIPEI))
    assert [p["id"] for p in got] == ["1"]
    assert seen == ["1", "2"]


def _matching_diff():
    return compare_one(
        our_wave={
            "labels": ["(1)"],
            "confirmed": [{"label": "(1)", "price": 4800}],
            "projected": [{"label": "(3)", "price": 4800}],
            "abc": [],
            "zones": [{"lo": 4700, "hi": 4900, "kind": "ok", "label": "滿足 4800"}],
            "wedge": True,
            "desc_press": {"source": "vb"},
        },
        our_caption="通道 目標 轉多",
        our_narrative="通道 目標 轉多",
        his_text="通道 目標 轉多 4800",
    )


def test_reached_95_does_not_change_drawing_rules():
    diff = _matching_diff()
    assert diff["likeness"]["reached_95"] is True
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        applied = propose_rule_updates(
            db,
            "20261017",
            [{"caption": "通道 目標 轉多", "his_text": "通道 目標 轉多 4800", "diff": diff}],
        )
        assert applied.get("held") is True
        assert applied.get("changed") is False
        rules = load_rules(db)
        assert "support_band" not in rules
        assert "narrative_template" not in rules
        assert "4800" not in str(rules)


def test_gap_updates_method_not_his_price():
    diff = compare_one(
        our_wave={
            "labels": ["(1)"],
            "confirmed": [{"label": "(1)", "price": 100}],
            "projected": [],
            "abc": [],
            "zones": [],
            "wedge": False,
            "desc_press": {},
        },
        our_caption="上升",
        our_narrative="上升",
        his_text="下降 通道 目標 4800",
    )
    assert diff["likeness"]["reached_95"] is False
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        row = [{"caption": "上升", "his_text": "下降 通道 目標 4800", "diff": diff}]
        first = propose_rule_updates(db, "20261017", row)
        assert first.get("changed") is True
        assert "4800" not in str(load_rules(db))
        wick1 = load_rules(db)["support_band"]["wick_ratio"]
        second = propose_rule_updates(db, "20261018", row)
        assert second.get("changed") is True
        wick2 = load_rules(db)["support_band"]["wick_ratio"]
        assert wick2 < wick1
        assert wick2 >= 0.95


def test_night_tick_one_chart_per_post_and_skips_encoding_when_empty(monkeypatch):
    def fake_fetch(now=None, **kwargs):
        return [
            {
                "id": "a",
                "date": "2026-10-16",
                "time": "16:51",
                "text": "2330 通道 目標 4800",
                "images": [],
                "image_notes": "圖注：前高",
            },
            {
                "id": "b",
                "date": "2026-10-16",
                "time": "16:30",
                "text": "2330 下降壓",
                "images": [],
                "image_notes": "",
            },
            {
                "id": "c",
                "date": "2026-10-16",
                "time": "10:22",
                "text": "這篇沒有代號",
                "images": [],
                "image_notes": "",
            },
        ]

    calls = []
    order = []

    def fake_render(sid, db_path, png):
        calls.append(os.path.basename(png))
        order.append("draw")
        return png, "上升", {"wave": {"bubble": "上升", "labels": ["(1)"], "confirmed": [{"price": 100}]}}

    import dc_scenario_silent_verify as mod

    orig_compare = mod.compare_one

    def fake_compare(**kwargs):
        order.append("cmp")
        assert order.count("draw") == 2
        return orig_compare(**kwargs)

    def fake_stocks(posts, db_path=""):
        out = []
        for p in posts:
            if "2330" in str(p.get("text") or ""):
                out.append(
                    {
                        "stock_id": "2330",
                        "stock_name": "台積電",
                        "post_ids": [str(p.get("id"))],
                        "excerpts": [p.get("text")],
                    }
                )
        return out

    monkeypatch.setattr("dc_scenario_silent_verify.fetch_dc_posts_within", fake_fetch)
    monkeypatch.setattr("dc_scenario_silent_verify.render_our_bundle", fake_render)
    monkeypatch.setattr("dc_scenario_silent_verify.compare_one", fake_compare)
    monkeypatch.setattr("dc_scenario_silent_verify.stocks_from_posts", fake_stocks)
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        now = datetime(2026, 10, 17, 3, 30, tzinfo=TAIPEI)
        report = night_tick(db, now=now, skip_if_done=False)
        assert report.get("post_n") == 3
        assert report.get("compare_n") == 2
        assert report.get("unmapped_n") == 1
        assert calls == ["a-2330-scenario-forecast.png", "b-2330-scenario-forecast.png"]
        assert order == ["draw", "draw", "cmp", "cmp", "cmp"]
        assert report.get("drawn_n") == 2
        assert report.get("rules_changed") == 1
        blob = str(load_rules(db))
        assert "4800" not in blob
        monkeypatch.setattr(
            "dc_scenario_silent_verify.fetch_dc_posts_within", lambda now=None, **k: []
        )
        empty = night_tick(
            db,
            now=datetime(2026, 10, 18, 3, 30, tzinfo=TAIPEI),
            skip_if_done=False,
        )
        assert empty.get("notes") == "empty_posts"
        assert empty.get("rules_changed") == 0
        from dc_scenario_silent_verify import stamp_status

        # 有跑完／沒發文仍要有自己的成功戳（不被 recent 六筆限制）
        hit = stamp_status(db, "20261018")
        assert hit is not None
        assert hit["run_date"] == "dc-sf-silent-20261018"
        assert hit["status"] == "success"
        assert "empty" in str(hit.get("notes") or "")


def test_mismatch_writes_why_learn_not_blind_turns_only():
    """他≠我們：落 why 卡（動機／滿足點／時間軸／可遷移）；可遷移進 learn_transfer。"""
    import sqlite3

    diff = compare_one(
        our_wave={
            "labels": ["(1)"],
            "confirmed": [{"label": "(1)", "price": 100}],
            "projected": [],
            "abc": [],
            "zones": [],
            "wedge": False,
            "desc_press": {},
            "deadline": {"i": 120, "label": "估·年底"},
        },
        our_caption="上升",
        our_narrative="上升",
        his_text="2330 下降壓 通道 (5)：5200 目標 月底前 滿足",
    )
    assert diff["has_actionable_diff"] is True
    card = build_why_card(
        as_of="20261020",
        stock_id="2330",
        post_id="p1",
        his_text="2330 下降壓 通道 (5)：5200 目標 月底前 滿足",
        our_caption="上升",
        our_wave={"deadline": {"i": 120, "label": "估·年底"}},
        diff=diff,
    )
    assert "通道" in card["motive"] or "方法詞" in card["motive"] or "差距" in card["motive"]
    assert any(float(x.get("price") or 0) == 5200 for x in card["fulfill_targets"])
    assert card["timeline"].get("his_timing_hints")
    assert card["transferable"]
    assert "5200" not in " ".join(card["transferable"])
    assert card["ticker_only"]["his_turn_prices"].get("(5)") == 5200
    assert card["not_buy_signal"] is True

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        applied = propose_rule_updates(
            db,
            "20261020",
            [
                {
                    "stock_id": "2330",
                    "post_id": "p1",
                    "caption": "上升",
                    "his_text": "2330 下降壓 通道 (5)：5200 目標 月底前 滿足",
                    "diff": diff,
                }
            ],
        )
        assert applied.get("learn", {}).get("n", 0) >= 1
        rules = load_rules(db)
        lt = rules.get("learn_transfer") or {}
        assert lt.get("rules")
        assert "5200" not in str(lt)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT motive, fulfill_json, timeline_json, transferable_json FROM dc_sf_learn "
            "WHERE as_of=? AND stock_id=?",
            ("20261020", "2330"),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0]
        assert "5200" in row[1]
        assert "月底" in row[2] or "deadline" in row[2]
        assert "通道" in row[3] or "時間軸" in row[3]


def test_persist_mismatch_learn_skips_aligned_row():
    diff = _matching_diff()
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        out = persist_mismatch_learn(
            db,
            "20261020",
            [{"stock_id": "2330", "post_id": "x", "caption": "通道 目標 轉多", "his_text": "通道 目標 轉多 4800", "diff": diff}],
        )
        assert out.get("n") == 0


def test_stamp_status_error_not_hidden_by_other_success():
    """本軌 error 戳與別軌 success 鍵分開；讀 stamp_status 不受 recent 擠掉。"""
    import sqlite3
    from dc_scenario_silent_verify import _mark_pipeline, stamp_status

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        open(db, "a").close()
        ensure_tables(db)
        _mark_pipeline(db, "20261017", "error", "boom")
        # 別軌 success 不該蓋掉本軌鍵
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs(run_date,finished_at,status,notes) "
            "VALUES (?,?,?,?)",
            ("20261017", "2026-10-17 17:09:00", "success", "increment"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs(run_date,finished_at,status,notes) "
            "VALUES (?,?,?,?)",
            ("screen-20261016", "2026-10-17 07:14:00", "success", "morning"),
        )
        conn.commit()
        conn.close()
        hit = stamp_status(db, "20261017")
        assert hit["status"] == "error"
        assert "boom" in str(hit.get("notes") or "")
        # 本軌重跑 empty 才准把自己的 error 換成 success
        _mark_pipeline(db, "20261017", "success", "dc_sf empty_posts as_of=20261017")
        hit2 = stamp_status(db, "20261017")
        assert hit2["status"] == "success"
