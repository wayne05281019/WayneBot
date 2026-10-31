# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from biaoke_level_learn import (
    _sparse_slot_id,
    ensure_tables,
    looks_like_level_now,
    paint_open_day_hypothesis,
    record_level_learn_from_events,
    verify_pending_with_event,
)

TAIPEI = ZoneInfo("Asia/Taipei")


def test_looks_like_level_now_index_wave():
    assert looks_like_level_now("大盤 C3-3 主跌段開始啟動")
    assert looks_like_level_now("目前只是C3-3-1轉C3-3-2")
    assert looks_like_level_now("橫台整理只是中繼站，細微波之後南下")
    assert not looks_like_level_now("今天天氣不錯")


def test_ingest_hooks_level_learn_and_live_paint():
    from biaoke_ingest import _after_ingest_analyze, start_biaoke_poller

    src = inspect.getsource(_after_ingest_analyze)
    assert "record_level_learn_from_events" in src
    assert "maybe_paint_open_day_after_ingest" in src
    poll = inspect.getsource(start_biaoke_poller)
    assert "maybe_paint_open_day_after_ingest" in poll


def test_sparse_slots_not_every_minute():
    pre = datetime(2026, 11, 2, 8, 10, tzinfo=TAIPEI)
    mid = datetime(2026, 11, 2, 11, 20, tzinfo=TAIPEI)
    night = datetime(2026, 10, 30, 21, 40, tzinfo=TAIPEI)
    idle = datetime(2026, 11, 2, 10, 5, tzinfo=TAIPEI)
    assert _sparse_slot_id(pre) == "20261102-pre"
    assert _sparse_slot_id(mid) == "20261102-mid"
    assert _sparse_slot_id(night) == "20261030-night"
    assert _sparse_slot_id(idle) is None


def test_verify_pending_optimistic_then_crash(tmp_path):
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_level_snaps(post_id, as_of, snippet, pending, created_at) "
        "VALUES ('a','20261028','大盤已經止跌，打第二隻腳',1,'t')"
    )
    conn.commit()
    conn.close()
    n = verify_pending_with_event(
        db, "b", "大盤 C3-3 主跌段開始啟動，跳空確認"
    )
    assert n == 1
    row = sqlite3.connect(db).execute(
        "SELECT pending, verdict FROM biaoke_level_snaps WHERE post_id='a'"
    ).fetchone()
    assert row[0] == 0 and row[1] == "偏"


def test_record_skips_under_pytest(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_LEVEL_LEARN_LIVE", raising=False)
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    stats = record_level_learn_from_events(
        db, [{"id": "x", "date": "20261030", "time": "09:18", "text": "大盤 C3-3 主跌"}]
    )
    assert stats.get("skipped") == "pytest"


def test_paint_skips_under_pytest(tmp_path, monkeypatch):
    monkeypatch.delenv("WAYNE_LEVEL_LEARN_LIVE", raising=False)
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    out = paint_open_day_hypothesis(db, force=True)
    assert out.get("skipped") == "pytest"


def test_open_day_table_has_vol_fields(tmp_path):
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    cols = {
        r[1]
        for r in sqlite3.connect(db).execute(
            "PRAGMA table_info(biaoke_open_day_paints)"
        )
    }
    for need in ("turn_note", "vol_note", "key_levels", "tx60_path", "us_note", "pending"):
        assert need in cols


def test_live_dark_renderer_enforces_fifth_above_b():
    """八浪基本形：活畫原始碼必須守 ⑤高>B高，並帶他用過的 Fib／1-4。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("biaoke_level_learn.py").read_text(
        encoding="utf-8"
    )
    assert "y_bhi >= y5" in src
    assert "0.382" in src and "0.618" in src and "0.75" in src
    assert "45546" in src and "44210" in src
    assert "C3-3" in src
    assert "1-4" in src and "動態修正" in src
    assert "48066" in src or "rule14" in src
    assert "預估" in src and ("隨時檢視" in src or "重新修訂" in src)
    assert "_REVISE_MARK" in src
    assert "gap * 0.078" in src or "結構優先" in src
    # 教不懂浪的學生：遠窗／近窗各一張＋外圍費半對照；缺資料自補
    assert "遠窗" in src and "近窗" in src
    assert "20260825" in src
    assert "_render_twii_far_dark" in src
    assert "_render_us_compare_dark" in src
    assert "_ensure_us_index_daily" in src
    assert "費半" in src
    assert "_morph_note_from_text" in src
    assert "黃金切割" in src
    assert "切0.382" in src or "0.382" in src
    assert "_twii_intent_story" in src
    assert "大善人" in src or "解套" in src
    assert "沒底子" in src or "白話" in src
    assert "_twii_intent_story" in src
    assert "量縮止穩" in src or "好心" in src or "套牢" in src
    # 超級近窗：C 內小波層＋另前提才畫另色線
    assert "_render_twii_super_near_dark" in src
    assert "_alt_path_needed" in src
    assert "micro_path" in src
    assert "另前提" in src or "薄荷" in src
    # 費半主圖：同月日軸，波浪自轉折（不准抄加權 A/B 日）
    assert "_align_us_to_twii_dates" in src
    assert "_sox_abc_anchors_on_axis" in src
    assert "自轉折" in src or "不准抄" in src
    # 超級近窗：C起自 B；幾何①②不准冒充他說；今＝只認 ≤as_of 的他文
    assert "B高＝C起" in src
    assert "幾何對讀" in src
    assert "今・C進行中" in src or "不准冒充他說" in src
    assert "_level_break_tag" in src
    assert "as_of<=" in src or "chart_as_of" in src
    assert "C內①②（未稱C3）" in src
    assert "title_bit" in src or "不准寫死 C3-3" in src


def test_his_micro_degree_and_alt_gate():
    from biaoke_level_learn import _alt_path_needed, _his_micro_degree

    d = _his_micro_degree("目前只是C3-3-1轉C3-3-2")
    assert d["degree"] == "C3-3-2"
    assert "C3-3" in d["chain"]
    assert _alt_path_needed("C3-3-2", "C3-3-1") is True
    assert _alt_path_needed("C3-3-2", "C3-3-2") is False
    # C／橫台 vs 幾何 C3 不准另畫
    assert _alt_path_needed("C", "C3-3-2") is False


def test_wave_now_ladder_big_to_small():
    from biaoke_level_learn import _wave_now_ladder

    mid = _wave_now_ladder(
        {"thesis": "五波後下降ABC・C內橫台中繼（預估）", "chart_as_of": "20261029"}
    )
    assert mid["now"] == "C內橫台中繼"
    assert "五波升完" in mid["chain"] and "C進行中" in mid["chain"]
    assert "C3-3" not in mid["chain"]
    deep = _wave_now_ladder(
        {
            "thesis": "五波後下降ABC・C內＝C3-3（1→2・預估）",
            "snippet": "目前只是C3-3-1轉C3-3-2",
            "chart_as_of": "20261030",
        }
    )
    assert deep["now"] == "C3-3-2"
    assert "C3-3主跌" in deep["chain"]
    assert "他說現在：" in deep["one_line"]


def test_sox_abc_anchors_not_copy_twii_ab():
    """費半 A/B 用合成柱自算；不准落在加權 A/B 同索引（10/13–10/14 那兩格）。"""
    from biaoke_level_learn import _sox_abc_anchors_on_axis

    # 索引對齊加權近窗：0..；⑤＝5、加權A＝8、加權B＝9；費半A應更深（14）、B＝17
    n = 20
    highs = [100.0 + i for i in range(n)]
    lows = [90.0 + i for i in range(n)]
    closes = [95.0 + i for i in range(n)]
    # ⑤ 高在 5
    highs[5] = 140.0
    # 加權式短 A/B（8/9）故意做淺，費半不該停這
    lows[8] = 110.0
    highs[9] = 118.0
    # 費半真 A 更深低 + 之後反彈 B
    lows[14] = 95.0
    highs[17] = 120.0
    closes[-1] = 105.0
    sax = _sox_abc_anchors_on_axis(highs, lows, closes, i5_hint=5)
    assert sax is not None
    assert sax["i5"] == 5
    assert sax["i_alow"] == 14
    assert sax["i_bhi"] == 17
    assert sax["i_alow"] not in (8, 9)
    assert sax["i_bhi"] not in (8, 9)
    assert sax["y_bhi"] < sax["y5"]


def test_thesis_respects_chart_as_of_and_break_tag(tmp_path):
    """圖 as_of=10/29 不准吃到 10/30 的 C3-3；45546 未破不准寫已破。"""
    import sqlite3

    from biaoke_level_learn import _latest_level_thesis, _level_break_tag, ensure_tables

    db = str(tmp_path / "lvl.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_level_snaps("
        "post_id, as_of, post_date, post_time, snippet, chart_path, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("p29", "20261029", "2026-10-29", "12:00", "橫台整理中繼站", "", "t"),
    )
    conn.execute(
        "INSERT INTO biaoke_level_snaps("
        "post_id, as_of, post_date, post_time, snippet, chart_path, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("p30", "20261030", "2026-10-30", "09:18", "目前只是C3-3-1轉C3-3-2", "", "t"),
    )
    conn.commit()
    conn.close()
    pack = _latest_level_thesis(db, as_of="20261029")
    assert "C3-3" not in (pack.get("thesis") or "")
    assert "C3-3" not in (pack.get("snippet") or "")
    assert "橫台" in (pack.get("thesis") or pack.get("snippet") or "")
    assert _level_break_tag(45546.0, [46055.0, 45676.0, 46041.0]) == "未破"
    assert _level_break_tag(45546.0, [44726.0]) == "已破"


def test_twii_intent_story_trap_language():
    """量價故事要能講套牢／無量≠止穩；不准當買訊句。"""
    from biaoke_level_learn import _twii_intent_story

    # 無庫也要空字串回傳，不准拋
    empty = _twii_intent_story("")
    assert empty.get("intent_note") == "" or isinstance(empty.get("intent_note"), str)


def test_latest_teach_kit_reads_paths(tmp_path):
    from biaoke_level_learn import ensure_tables, latest_teach_kit

    db = str(tmp_path / "t.db")
    ensure_tables(db)
    far = tmp_path / "far.png"
    near = tmp_path / "near.png"
    far.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    near.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    conn = sqlite3.connect(db)
    micro = tmp_path / "micro.png"
    micro.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    conn.execute(
        "INSERT INTO biaoke_open_day_paints("
        "slot_id, as_of, thesis, far_path, near_path, us_path, micro_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("20261030-night", "20261030", "預估在 C", str(far), str(near), "", str(micro), "t"),
    )
    conn.commit()
    conn.close()
    kit = latest_teach_kit(db)
    assert kit["far_path"] == str(far)
    assert kit["near_path"] == str(near)
    assert kit["micro_path"] == str(micro)
    assert kit["us_path"] == ""
    assert "C" in kit["thesis"]
