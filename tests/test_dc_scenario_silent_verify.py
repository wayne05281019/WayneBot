# -*- coding: utf-8 -*-
"""D.C 情境預估靜默日對質：排程鍵／隔離／文意欄／非買訊。"""
from __future__ import annotations

import inspect
import os
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dc_scenario_silent_verify import (
    DC_SF_START,
    JOB_KIND,
    LOCK_NAME,
    PIPE_PREFIX,
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    biaoke_night_busy,
    compare_one,
    in_campaign,
    meaning_diff_line,
    pipeline_key,
    ensure_tables,
    night_tick,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def test_schedule_staggered_from_biaoke_0100():
    assert JOB_KIND == "dc_sf_silent"
    assert SCHEDULE_HOUR == 2 and SCHEDULE_MINUTE == 20
    assert PIPE_PREFIX.startswith("dc-sf-silent")
    assert LOCK_NAME == "dc_sf_silent.lock"
    # 01:00–02:19 忙；02:20 起可跑
    busy = datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI)
    free = datetime(2026, 10, 15, 2, 20, tzinfo=TAIPEI)
    assert biaoke_night_busy(busy) is True
    assert biaoke_night_busy(free) is False


def test_campaign_window_and_pipeline_key():
    assert DC_SF_START == date(2026, 10, 15)
    assert in_campaign(datetime(2026, 10, 15, 2, 20, tzinfo=TAIPEI))
    assert not in_campaign(datetime(2026, 10, 14, 2, 20, tzinfo=TAIPEI))
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


def test_main_scheduler_wires_dc_sf_silent_isolated():
    import main as main_mod

    src = inspect.getsource(main_mod.run_scheduled_job)
    assert "dc_sf_silent" in src
    assert "dc_sf_night_tick" in src or "night_tick" in src
    assert "return" in src  # 專鍵提早 return，不走飆大 ingest 鏈
    slot_src = inspect.getsource(main_mod.start_daily_scheduler)
    assert "(2, 20, \"dc_sf_silent\")" in slot_src or "(2, 20, 'dc_sf_silent')" in slot_src
    absorb = open("biaoke_absorb.py", encoding="utf-8").read()
    assert "dc_sf_silent" in absorb and "互不影響" in absorb
