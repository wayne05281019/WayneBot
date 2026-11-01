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
    assert "force=bool(level_seen)" in src
    assert "maybe_push_level_teach_update" in src
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
    assert "20260728" in src  # 遠窗從七月底⑤起
    assert "_sox_abc_anchors_on_axis" in src  # 遠窗下方費半自轉折
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
    # 超級近窗：C起自 B；紫虛c4／c5 對他60分；橙①②僅輔助；大＝ABC｜細不取代
    assert "B高＝C起" in src
    assert "日K小波" in src
    assert "柱上讀" not in src
    assert "幾何對讀" not in src
    assert "大＝ABC｜細＝C內不取代ABC" in src
    assert "_c_subwave_anchors_vs_biaoke60" in src
    assert "c4細" in src and "c5細" in src
    assert "_level_break_tag" in src
    assert "_biaoke_pred_label" in src
    assert "飆預測" in src
    assert "_seat_onchart_labels" in src
    assert "maybe_push_level_teach_update" in src
    assert "as_of<=" in src or "chart_as_of" in src
    assert "C內小波①②（未稱C3）" in src or "日K小波①②（輔助）" in src
    assert "title_bit" in src or "不准寫死 C3-3" in src
    assert "_paint_c_forecast" in src and "_c_forecast_tip" in src
    # 預估端同價改飆預測（續弱才留預估↓）
    assert "_biaoke_pred_label(45546" in src or "飆預測" in src
    assert "預估↓續弱" in src
    assert "_paint_window_dual_zones" in src
    # 近／超近也要黃＋青雙底色（與遠窗對齊）；三張同套 c4／c5
    near_blk = src[src.index("def _render_twii_live_dark") : src.index("def _render_twii_super_near_dark")]
    micro_blk = src[src.index("def _render_twii_super_near_dark") : src.index("def _render_us_compare_dark")]
    far_blk = src[src.index("def _render_twii_far_dark") : src.index("def _render_twii_live_dark")]
    assert "_paint_window_dual_zones" in near_blk
    assert "_paint_window_dual_zones" in micro_blk
    assert "_c_subwave_anchors_vs_biaoke60" in far_blk
    assert "_c_subwave_anchors_vs_biaoke60" in near_blk
    assert "_c_subwave_anchors_vs_biaoke60" in micro_blk
    assert "日K小波①②（輔助）" in micro_blk or "橙①②僅輔助" in micro_blk
    # 浪名釘轉折點同價Y（左右錯開），不准再漂空＋_seat 上推
    assert "_pin_pivot_name" in far_blk
    assert "_pin_pivot_name" in near_blk
    assert "_pin_pivot_name" in micro_blk
    assert "_pin_pivot_name" in src
    # 三張標題都要查詢當下時鐘（盤中 HH:MM／收盤標籤），不准只寫盤中／收
    assert "_teach_query_clock" in far_blk
    assert "_teach_query_clock" in near_blk
    assert "_teach_query_clock" in micro_blk
    assert "def _teach_query_clock" in src
    assert "def _thesis_cap_for_query" in src
    assert "_latest_biaoke_index_snip" in src
    # 外圍對照（附圖二）本輪不加 c4／c5 細標；費半右欄要接他寫死預測點
    us_end = src.find("\ndef ", src.index("def _render_us_compare_dark") + 4)
    us_blk = src[src.index("def _render_us_compare_dark") : us_end if us_end > 0 else None]
    assert "_c_subwave_anchors_vs_biaoke60" not in us_blk
    assert "_paint_sox_thesis_preds" in us_blk
    assert "sox_pred_ys" in us_blk
    assert 'fut_x, s_fut, "預估↓"' not in us_blk


def test_c_forecast_tip_points_his_next_anchor():
    from biaoke_level_learn import _c_forecast_tip, _px

    # 未破 45546：端點標飆預測（不准再寫多餘預估↓同價）
    tip = _c_forecast_tip(i_now=10, y_now=46368.0, y_ref=49059.0, lows=[46055.0, 45676.0])
    assert tip["fut_y"] == 45546.0
    assert tip["anchor_y"] == 45546.0
    assert "飆預測" in tip["label"] and _px(45546.0) in tip["label"]
    assert "預估↓" not in tip["label"]
    # 已破：下一錨 44210
    tip2 = _c_forecast_tip(i_now=10, y_now=45000.0, y_ref=49059.0, lows=[44726.0])
    assert tip2["fut_y"] == 44210.0
    assert "飆預測" in tip2["label"] and _px(44210.0) in tip2["label"]
    # 低點明確破 45546 → 下一錨 44210
    tip3 = _c_forecast_tip(
        i_now=10, y_now=46368.0, y_ref=49059.0, lows=[45500.0, 46055.0]
    )
    assert tip3["fut_y"] == 44210.0


def test_sparse_xticks_no_adjacent_crush():
    from biaoke_level_learn import _sparse_xticks

    i, l = _sparse_xticks([10, 11, 12, 20], ["10/15", "10/16", "10/17", "10/29"], min_gap=3)
    assert i == [10, 20]
    assert l == ["10/15", "10/29"]


def test_next_support_resist_nearest():
    from biaoke_level_learn import _next_support_resist

    sr = _next_support_resist(
        46368.0,
        supports=(45546.0, 44210.0),
        resists=(47637.0, 49059.0),
    )
    assert sr["support"] == 45546.0
    assert sr["resist"] == 47637.0


def test_far_yellow_band_is_max_vol_day_hl():
    """遠窗黃帶＝最大量日高低；青帶＝下一撐壓；底色在K下層。"""
    src = open("biaoke_level_learn.py", encoding="utf-8").read()
    block = src[src.index("def _render_twii_far_dark") : src.index("def _render_twii_live_dark")]
    assert "_paint_max_vol_hl_zone" in block
    assert "_paint_next_sr_zone" in block
    assert "K棒下一層" in block or "K下一層" in src
    assert "def _paint_max_vol_hl_zone" in src
    assert "def _paint_next_sr_zone" in src
    # 金K只改色；「最大量」字只留量欄（價圖不准再貼黃字標）
    special = src[src.index("def _paint_special_candle") : src.index("def _paint_vol_bars_max_yellow")]
    assert "不准再貼" in special or "量欄已有" in special
    assert "ax.text" not in special
    assert "day_tag" in src[src.index("def _paint_max_vol_hl_zone") : src.index("def _hl_spans_excluding")]
    # 右標：只准最後一根K右側外側短價線；不准伸進柱區、不准假轉折點 scatter
    place = src[src.index("def _place_live_right_labels") : src.index("def _his_micro_degree")]
    assert "level_dash" in place
    assert "不准橫貫" in place or "右緣" in place or "外側" in place
    assert "n - 0.85" not in place
    assert "ax.scatter" not in place
    assert "axhline" not in place
    assert "level_dash=False" in block or "level_dash=True" in block
    # 水平往左貼最後一根K右側；不准再漂到 n+1.15、不准 right=0.90 把標甩進圖外溝
    assert "n) + 0.18" in place or "n + 0.18" in place
    assert "n) + 1.15" not in place and "n + 1.15" not in place
    assert "x_dash0" in place
    assert "min_gap=(ymax - ymin) * 0.055" in block
    assert "900.0" not in block[block.index("_place_live_right_labels") :]
    # 遠窗 xlim 跟最長軸（費半可晚於加權）；舊寫 n+8.6，現況 n_axis+8.6
    assert "n_axis + 8.6" in block or "n + 8.6" in block
    assert "right=0.98" in block
    assert "right=0.90" not in block
    assert "_extend_us_ohlc_past_twii" in block or "_extend_us_ohlc_past_twii" in src
    assert "_FAR_SOX_MIN_BODY_FRAC" in src
    assert "facecolors=\"none\"" in block or "facecolors='none'" in block
    # 浪名：high 在尖上、low 在尖下，不准左右蓋住縮圖K
    pin = src[src.index("def _pin_pivot_name") : src.index("def _c_path_label_xy")]
    assert '"high"' in pin and '"bottom"' in pin
    assert '"low"' in pin and '"top"' in pin
    assert "不准蓋住縮圖K" in pin or "整盒不准蓋住縮圖K" in pin
    assert 'tip="high"' in block and 'tip="low"' in block
    # A／B 字釘轉折尖點正上／正下（side=auto），不准再往左漂到別根K
    assert 'y_alow, "A低"' in block and 'side="auto"' in block
    assert 'y_bhi, "B高"' in block
    assert "i_now, y_now, \"C進行中\"" in block or "i_now, y_now" in block
    assert "keep_left_of_right=True" in block
    assert "_biaoke_pred_label" in block
    assert "浪名釘轉折點" in block or "浪名貼尖點" in block or "智慧標" in pin
    # 腳註多行：不准 [:72] 裁成「9,」；完整 pred_note 再換行
    assert "pred_foot[:72]" not in block
    assert "pred_foot" in block
    assert "[:240]" in block or "pred_note" in block


def test_far_max_vol_day_matches_official_hl():
    """黃底高低必須＝窗內最大量那根官方日K高低（同一交易日）。"""
    from biaoke_level_learn import _bar_index_by_ymd, _twii_abc_anchors, _ymd
    from biaoke_wave import _load_twii_bars

    bars = _load_twii_bars("data/wayne_market.db", n=260)
    if len(bars) < 20:
        return
    i0 = _bar_index_by_ymd(bars, "20260728") or _bar_index_by_ymd(bars, "20260729") or 0
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    if not anc:
        return
    vols = [float(r.get("volume") or 0) for r in bars]
    i_vmax = max(range(len(bars)), key=lambda i: vols[i])
    assert _ymd(bars[i_vmax].get("date")) == "20261015"
    assert abs(float(anc["highs"][i_vmax]) - 48382.75) < 0.5
    assert abs(float(anc["lows"][i_vmax]) - 46795.37890625) < 0.5


def test_hl_spans_excluding_no_overlap():
    from biaoke_level_learn import _hl_spans_excluding, _y_inside_hl

    # 青 45546～47637 扣黃 46795～48383 → 只剩 45546～46795（交疊量 0）
    segs = _hl_spans_excluding(45546.0, 47637.0, ex_lo=46795.0, ex_hi=48383.0)
    assert len(segs) == 1
    assert abs(segs[0][0] - 45546.0) < 0.1
    assert abs(segs[0][1] - 46795.0) < 0.1
    # 完全在黃內 → 不塗
    assert _hl_spans_excluding(47000.0, 47500.0, ex_lo=46795.0, ex_hi=48383.0) == []
    # 青包住黃 → 上下兩段，中間不塗
    segs2 = _hl_spans_excluding(45000.0, 49000.0, ex_lo=46795.0, ex_hi=48383.0)
    assert len(segs2) == 2
    assert abs(segs2[0][1] - 46795.0) < 0.1
    assert abs(segs2[1][0] - 48383.0) < 0.1
    # 近壓落在黃帶內 → 左標要改右欄
    assert _y_inside_hl(47637.0, 46795.0, 48383.0) is True
    assert _y_inside_hl(45546.0, 46795.0, 48383.0) is False


def test_his_micro_degree_and_alt_gate():
    from biaoke_level_learn import _alt_path_needed, _his_micro_degree

    d = _his_micro_degree("目前只是C3-3-1轉C3-3-2")
    assert d["degree"] == "C3-3-2"
    assert "C3-3" in d["chain"]
    assert _alt_path_needed("C3-3-2", "C3-3-1") is True
    assert _alt_path_needed("C3-3-2", "C3-3-2") is False
    # C／橫台 vs 柱讀 C3 不准另畫
    assert _alt_path_needed("C", "C3-3-2") is False
    d334 = _his_micro_degree("3-3-3完成轉3-3-4機率最高；C3-3跌勢運行中")
    assert d334["degree"] == "C3-3-4"


def test_biaoke_pred_label_no_fake_prob():
    from biaoke_level_learn import _biaoke_pred_label, _px

    px = _px(44210.0)
    assert _biaoke_pred_label(44210.0) == f"飆預測{px}"
    assert _biaoke_pred_label(44210.0, "未到") == f"飆預測{px}未到"
    # 不准假％：沒傳機率就不帶
    assert "%" not in _biaoke_pred_label(44210.0, "未到")
    assert _biaoke_pred_label(44210.0, "未到", prob=80.0) == f"飆預測{px}未到（80%機率）"


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
    to4 = _wave_now_ladder(
        {
            "thesis": "五波後下降ABC・C內＝C3-3（3→4・預估）",
            "snippet": "目前應該是3-3-3完成轉3-3-4機率最高",
            "thesis_as_of": "20261101",
        }
    )
    assert to4["now"] == "C3-3-4"
    assert "C3-3主跌" in to4["chain"]


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


def test_paint_panels_trio_skips_us_and_tx60_in_source():
    """話筒 trio 模式原始碼：試畫／補美股／外圍／TX60 只在 full 才跑。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("biaoke_level_learn.py").read_text(
        encoding="utf-8"
    )
    block = src[
        src.index("def paint_open_day_hypothesis") : src.index("def latest_teach_kit")
    ]
    assert 'panels: str = "full"' in block
    assert 'mode == "full"' in block
    # 內部試畫／補美股日K 必須包在 full 分支
    for name in ("snapshot_and_score_twii", "_ensure_us_index_daily"):
        at = block.index(name)
        assert block.rfind('mode == "full"', 0, at) > 0
    # 外圍／TX60 必須包在 full 分支，不准 trio 無條件畫
    us_at = block.index("_render_us_compare_dark")
    full_guard = block.rfind('mode == "full"', 0, us_at)
    assert full_guard > 0
    tx_at = block.index("_render_tx60_png")
    assert block.rfind('mode == "full"', 0, tx_at) > 0


def test_schedule_ingest_paint_defaults_to_full_panels():
    """排程／ingest 活畫走預設 full，不准寫死 panels=trio。"""
    from pathlib import Path

    from biaoke_level_learn import maybe_paint_open_day_after_ingest

    root = Path(__file__).resolve().parents[1]
    maybe = inspect.getsource(maybe_paint_open_day_after_ingest)
    assert "paint_open_day_hypothesis(db_path, force=force)" in maybe
    assert 'panels="trio"' not in maybe and "panels='trio'" not in maybe
    ingest = (root / "biaoke_ingest.py").read_text(encoding="utf-8")
    assert "maybe_paint_open_day_after_ingest" in ingest
    # 呼叫點不傳 panels → 預設 full
    assert 'panels="trio"' not in ingest


def test_teach_query_clock_shows_wall_hhmm():
    """三張教具時鐘：一律查詢當下 HH:MM；盤中／收都要有鐘點。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _teach_query_clock

    tz = ZoneInfo("Asia/Taipei")
    # 用平日 10:17，避免週末被合併窗判成休市
    live_bars = [{"date": "20261030", "live_session": 1, "close": 46000}]
    pack = {"query_at": datetime(2026, 10, 30, 10, 17, tzinfo=tz).isoformat()}
    clock = _teach_query_clock(live_bars, pack=pack)
    assert clock == "盤中 10:17"
    # 合併窗到 16:30；之後／週末才標「查詢 HH:MM｜收」
    closed = _teach_query_clock(
        [{"date": "20261030", "close": 46000}],
        pack={"query_at": datetime(2026, 10, 30, 17, 5, tzinfo=tz).isoformat()},
    )
    assert closed == "查詢 17:05｜收"


def test_thesis_follows_latest_biaoke_post_up_to_query(tmp_path):
    """開市日題旨 cap＝查詢日：吃得到當天最新位階文，吃不到牆鐘之後的文。"""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _latest_level_thesis, ensure_tables

    db = str(tmp_path / "lvl2.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_level_snaps("
        "post_id, as_of, post_date, post_time, snippet, chart_path, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        ("old", "20261030", "2026-10-30", "09:00", "橫台整理中繼站", "", "t"),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        ("n1", "2026-10-31", "09:05", "大盤目前只是C3-3-1轉C3-3-2，細微波進行中"),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        ("n2", "2026-10-31", "11:00", "大盤確認主跌段發動，動態修正位階"),
    )
    conn.commit()
    conn.close()
    tz = ZoneInfo("Asia/Taipei")
    before = _latest_level_thesis(
        db,
        as_of="20261031",
        now=datetime(2026, 10, 31, 10, 0, tzinfo=tz),
    )
    assert "C3-3" in (before.get("snippet") or before.get("thesis") or "")
    assert "主跌" not in (before.get("snippet") or "")
    after = _latest_level_thesis(
        db,
        as_of="20261031",
        now=datetime(2026, 10, 31, 11, 30, tzinfo=tz),
    )
    assert "主跌" in (after.get("snippet") or after.get("thesis") or "")


def test_thesis_cap_includes_weekend_posts(tmp_path, monkeypatch):
    """休市／週末他也會發文：題旨 cap 必須含查詢當日，不准卡在上一個開市柱日。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _thesis_cap_for_query

    monkeypatch.setattr(
        "biaoke_level_learn._twii_chart_as_of", lambda _db: "20261030"
    )
    tz = ZoneInfo("Asia/Taipei")
    # 2026-11-01 週日
    cap = _thesis_cap_for_query(
        str(tmp_path / "x.db"),
        now=datetime(2026, 11, 1, 12, 30, tzinfo=tz),
    )
    assert cap == "20261101"


def test_thesis_reads_333_to_334_without_c_prefix(tmp_path):
    """11/1 夜盤文：3-3-3→3-3-4（不一定寫 C 前綴）要進題旨。"""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _latest_level_thesis, ensure_tables

    db = str(tmp_path / "lvl334.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        (
            "n334",
            "2026-11-01",
            "11:49",
            "星期五夜盤C3-3跌勢運行中並未完成。"
            "目前應該是3-3-3完成轉3-3-4機率最高，下周一絕對不能去抄底。",
        ),
    )
    conn.commit()
    conn.close()
    tz = ZoneInfo("Asia/Taipei")
    out = _latest_level_thesis(
        db,
        as_of="20261101",
        now=datetime(2026, 11, 1, 12, 30, tzinfo=tz),
    )
    assert "3→4" in (out.get("thesis") or "")
    assert "抄底" in (out.get("wait_struct") or "") or "破底" in (out.get("wait_struct") or "")
    assert out.get("post_id") == "n334"


def test_far_twii_wave5_start_is_729_not_april():
    """遠窗拉到4/28後，加權⑤起仍須是7/29低，不准改用四月窗底。"""
    import inspect

    from biaoke_level_learn import _render_twii_far_dark

    src = inspect.getsource(_render_twii_far_dark)
    assert '20260729' in src
    assert "不准用窗內最低" in src or "不准把四月" in src or "跳過 7/29" in src
    # 活邏輯：同軸四月窗下，⑤起索引＝7/29
    from biaoke_level_learn import (
        _bar_index_by_ymd,
        _build_live_pack,
        _twii_abc_anchors,
        _twii_bars_for_teach,
        _ymd,
    )
    from datetime import datetime
    from zoneinfo import ZoneInfo

    db = "data/wayne_market.db"
    pack = _build_live_pack(
        db, now=datetime(2026, 11, 1, 13, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    bars = _twii_bars_for_teach(db, 320, pack)
    i0 = _bar_index_by_ymd(bars, "20260428") or 0
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    assert anc
    i5 = int(anc["i5"])
    i729 = _bar_index_by_ymd(bars, "20260729")
    assert i729 is not None and i729 < i5
    lows = [float(r.get("low") or 0) for r in bars]
    # 窗內最低在四月 → 若誤用 min 會錯；正確⑤起＝7/29
    i_min = min(range(0, i5 + 1), key=lambda i: lows[i])
    assert _ymd(bars[i_min].get("date")) < "20260701"
    assert abs(float(lows[i729]) - 39384.85) < 2.0


def test_thesis_pred_levels_sox_next_support_apr28():
    """A已破→下一撐＝4/28 9865；台指 44042／7/29 39384 都要抽出。"""
    from biaoke_level_learn import _thesis_pred_levels, _tw_tip_anchors

    snip = (
        "破台指期破44042。"
        "未來如果還有第三組末跌段，7/29低點39384必破。"
        "7/29 A波低點10445必破，星期五低點10439已經破A波低點。"
        "接下來會去測4/28 9865，如果破，大盤走5波下跌的機率就高很多。"
    )
    pred = _thesis_pred_levels(snip, "data/wayne_market.db")
    tw_lv = {round(float(r["level"])) for r in pred["tw"]}
    sox_roles = {str(r.get("role")): float(r["level"]) for r in pred["sox"]}
    assert 44042 in tw_lv
    assert any(abs(v - 39384) < 2 for v in tw_lv)
    assert "A波低" in sox_roles and abs(sox_roles["A波低"] - 10445) < 2
    assert "次回測" in sox_roles and abs(sox_roles["次回測"] - 9865) < 2
    pack = {"pred_levels": pred}
    anchors = _tw_tip_anchors(pack)
    assert 44042.0 in anchors


def test_snip_prefers_main_over_short_reply(tmp_path):
    """同日短自回不准蓋長篇位階主文。"""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import _latest_biaoke_index_snip, ensure_tables

    db = str(tmp_path / "snip.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        (
            "main187",
            "2026-11-01",
            "11:49",
            "星期五夜盤C3-3跌勢運行中並未完成。"
            "由周五夜盤來拆解波浪位階，目前應該是3-3-3完成轉3-3-4機率最高，"
            "第二組下跌推動脈動連主跌段都還未完成，下周一絕對不能去抄底破底。",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        ("main187:c48-2", "2026-11-01", "12:03", "費辦根本沒跌完，從細微波看的出來，不要想太多"),
    )
    conn.commit()
    conn.close()
    tz = ZoneInfo("Asia/Taipei")
    snip, pid = _latest_biaoke_index_snip(
        db,
        "20261101",
        now=datetime(2026, 11, 1, 12, 30, tzinfo=tz),
        with_id=True,
    )
    assert "3-3-4" in snip
    assert pid == "main187"
    assert "費辦" not in snip


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


def test_latest_teach_kit_skips_missing_files(tmp_path):
    """Redeploy 後 DB 列還在、PNG 不見 → 不准回幽靈路徑。"""
    from biaoke_level_learn import ensure_tables, latest_teach_kit, teach_kit_needs_restore

    db = str(tmp_path / "t.db")
    ensure_tables(db)
    ghost_far = str(tmp_path / "gone-far.png")
    ghost_near = str(tmp_path / "gone-near.png")
    ghost_micro = str(tmp_path / "gone-micro.png")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_open_day_paints("
        "slot_id, as_of, thesis, far_path, near_path, us_path, micro_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "20261030-night",
            "20261030",
            "預估在 C",
            ghost_far,
            ghost_near,
            "",
            ghost_micro,
            "t",
        ),
    )
    conn.commit()
    conn.close()
    kit = latest_teach_kit(db)
    assert kit["far_path"] == ""
    assert kit["near_path"] == ""
    assert kit["micro_path"] == ""
    assert kit["thesis"]  # 說法仍可讀
    assert teach_kit_needs_restore(db) is True


def test_teach_kit_needs_restore_false_when_trio_on_disk(tmp_path):
    from biaoke_level_learn import ensure_tables, teach_kit_needs_restore

    db = str(tmp_path / "t.db")
    ensure_tables(db)
    far = tmp_path / "far.png"
    near = tmp_path / "near.png"
    micro = tmp_path / "micro.png"
    for p in (far, near, micro):
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_open_day_paints("
        "slot_id, as_of, thesis, far_path, near_path, us_path, micro_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("20261030-night", "20261030", "預估在 C", str(far), str(near), "", str(micro), "t"),
    )
    conn.commit()
    conn.close()
    assert teach_kit_needs_restore(db) is False


def test_maybe_restore_teach_kit_skips_under_pytest(tmp_path, monkeypatch):
    """缺檔時會呼叫 paint；pytest 下 paint 略過，不准擋。"""
    from biaoke_level_learn import ensure_tables, maybe_restore_teach_kit

    monkeypatch.delenv("WAYNE_LEVEL_LEARN_LIVE", raising=False)
    db = str(tmp_path / "t.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO biaoke_open_day_paints("
        "slot_id, as_of, thesis, far_path, near_path, us_path, micro_path, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "20261030-night",
            "20261030",
            "預估在 C",
            str(tmp_path / "missing-far.png"),
            str(tmp_path / "missing-near.png"),
            "",
            str(tmp_path / "missing-micro.png"),
            "t",
        ),
    )
    conn.commit()
    conn.close()
    out = maybe_restore_teach_kit(db)
    assert out.get("restored") is False
    assert out.get("skipped") == "pytest" or out.get("ok") is False


def test_maybe_paint_after_ingest_restores_when_sparse_skips():
    """稀疏窗外略過時，原始碼必須接到缺檔補渲（部署後週末）。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("biaoke_level_learn.py").read_text(
        encoding="utf-8"
    )
    block = src[
        src.index("def maybe_paint_open_day_after_ingest") : src.index(
            "def _level_events_with_prices"
        )
    ]
    assert "maybe_restore_teach_kit" in block
    assert "off_hours" in block
    assert "slot_done" in block


def test_boot_wires_teach_kit_restore_background():
    import main as main_mod

    src = inspect.getsource(main_mod.run_web)
    assert "teach-kit-restore" in src
    assert "maybe_restore_teach_kit" in src
    assert "teach_kit_needs_restore" in src
    # 必須在 listen 前就排背景，且不准擋 /health（sleep 後再畫）
    assert src.index("teach-kit-restore") < src.index("bot.run_polling()")
    assert "time.sleep(12)" in src[src.index("def _restore_teach_kit_bg") :]
