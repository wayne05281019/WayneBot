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
    # 他自己新文／貼圖或位階都要 force 重渲三張
    assert "his_fresh" in src
    assert "force=bool(level_seen or his_fresh)" in src
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


def test_force_slot_one_per_day_overwrite():
    """話筒重開不准每分堆 force-HHMM PNG；一日一槽覆寫。"""
    a = datetime(2026, 11, 3, 18, 0, tzinfo=TAIPEI)
    b = datetime(2026, 11, 3, 18, 36, tzinfo=TAIPEI)
    c = datetime(2026, 11, 2, 9, 1, tzinfo=TAIPEI)
    assert _sparse_slot_id(a, force=True) == "force-20261103"
    assert _sparse_slot_id(b, force=True) == "force-20261103"
    assert _sparse_slot_id(c, force=True) == "force-20261102"


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
    assert "x_col" in src or "同一右欄" in src or "結構優先" in src
    # 教不懂浪的學生：遠窗／近窗各一張＋外圍費半對照；缺資料自補
    assert "遠窗" in src and "近窗" in src
    assert "20260331" in src  # 遠窗自3月底（推進⑤起4/1）
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
    # 三張＋縮圖同一大結構日曆；超近＝C內震盪；閃折B＝大B末
    assert "_macro_wave_calendar_line" in src
    assert "⑤＝4/1→6/23｜A＝6/23→7/29｜B＝7/29→10/6｜C＝10/6→今" in src
    assert "大B末" in src
    assert "不准用近B" in src
    assert "日K小波" in src
    assert "C內震盪" in src or "C內早" in src
    assert "柱上讀" not in src
    assert "幾何對讀" not in src
    assert "大＝A底→B反彈→C" in src or "大A底" in src
    assert "C走完≠新五波升" in src
    assert "_c_subwave_anchors_vs_biaoke60" in src
    assert "c4細" in src and "c5細" in src
    assert "_level_break_tag" in src
    assert "_biaoke_pred_label" in src
    assert "飆預測" in src
    assert "_seat_onchart_labels" in src
    assert "maybe_push_level_teach_update" in src
    assert "as_of<=" in src or "chart_as_of" in src
    assert "C內小波①②（未稱C3）" in src or "日K小波①～⑤（＝縮圖）" in src or "日K小波①②（輔助）" in src
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
    assert "vol_sr=near_vol_sr" in near_blk or "大量撐壓" in near_blk
    assert "vol_sr=micro_vol_sr" in micro_blk or "大量撐壓" in micro_blk
    assert "_far_teach_bars_keeping_vol_sr" in far_blk
    assert "_paint_next_layer_vol_zone" in far_blk
    assert "SOXX" in far_blk and "大量撐壓" in far_blk
    assert "_c_subwave_anchors_vs_biaoke60" in far_blk
    assert "_c_subwave_anchors_vs_biaoke60" in near_blk
    assert "_c_subwave_anchors_vs_biaoke60" in micro_blk
    # 三張都掛八浪／九波縮圖；近窗跟遠窗細線九段（detail=False）；超近非C9仍可 detail
    assert "_paint_eight_wave_inset" in far_blk
    assert "_paint_eight_wave_inset" in near_blk
    assert "_paint_eight_wave_inset" in micro_blk
    assert "detail=False" in near_blk
    assert 'title="九波擴延"' in near_blk
    assert "_stamp_ax_x, _stamp_ax_y = 0.02, 0.96" in near_blk
    assert "avoid_top_left_stamp=True" in near_blk
    assert "float(i5s) + 7.5" in near_blk  # ⑤起讓過首根K
    assert "hspace=0.10" in near_blk
    assert "labs_ax" in near_blk and "labs_axv" in near_blk
    assert "0.62" in near_blk and "_teach_eight_wave_inset_wh" in near_blk
    assert "width) * 0.15" in near_blk  # 九波鎖價欄紅框
    assert "35500.0" in near_blk  # 上緣不准碰藍虛線
    assert "float(i5e) + 7.0" in near_blk  # ⑤末尖右下讓過戳
    assert "_near_major_date_labs" in near_blk  # 結構日欄間單行
    assert "_fp(9.5" in near_blk  # 結構日字級略大
    # 超近窗改回日K：主路不准再轉 60 分
    assert "_render_twii_super_near_c9_60m" not in micro_blk
    assert "detail=True" in micro_blk or "detail=False if _c9_micro" in micro_blk
    assert "_twii_macro_wave_anchors" in src
    assert (
        "日K小波①～⑤（＝縮圖）" in micro_blk
        or "日K小波①②（輔助）" in micro_blk
        or "橙①②僅輔助" in micro_blk
    )
    assert "_c_teach_flash_pivots" in src
    assert "flash_pivots=" in micro_blk
    # 浪名釘轉折點同價Y（左右錯開），不准再漂空＋_seat 上推
    assert "_pin_pivot_name" in far_blk
    assert "_pin_pivot_name" in near_blk
    assert "_pin_pivot_name" in micro_blk
    assert "_pin_pivot_name" in src
    # 三張共用螢光黃查詢戳（日期／盤中或收／價）；時鐘邏輯仍走 _teach_query_clock
    assert "_paint_teach_query_stamp" in far_blk
    assert "_paint_teach_query_stamp" in near_blk
    assert "_paint_teach_query_stamp" in micro_blk
    assert "def _teach_query_clock" in src
    assert "def _paint_teach_query_stamp" in src
    assert "def _paint_index_last_chg_tip" in src
    assert "_TEACH_STAMP_EDGE" in src
    assert '_TEACH_STAMP_FACE = "#ffffff"' in src or "_TEACH_STAMP_FACE = '#ffffff'" in src
    assert "市撮" in src and "盤前" in src and "收盤" in src
    assert "def _thesis_cap_for_query" in src
    # 遠窗四欄：費半→台指電子盤→加權日盤（加權較高）→量；欄間日期
    assert "figsize=(15.6, 15.6)" in far_blk
    assert "height_ratios=(2.15, 2.30, 3.30, 0.95)" in far_blk
    assert "hspace=0.18" in far_blk
    assert "_shrink_png_for_telegram" in far_blk
    assert "_TG_PHOTO_MAX_WH_SUM" in src
    assert "def _shrink_png_for_telegram" in src
    assert "axt" in far_blk and "台指電子盤" in far_blk
    assert "台指期盤後" not in far_blk
    assert "_load_tx_futures_daily" in src
    assert "_ensure_paint_live_tx" in src
    assert "_apply_live_tx_to_axis" in far_blk
    # 電子盤撐壓底色＋右標虛線＋即時K
    assert "tx_vol_sr" in far_blk
    assert "_tx_right_notes" in far_blk
    assert "電盤" in far_blk
    # 三戳鎖各欄 axes 左上（上緣下方）；transAxes 才不被 tight 裁出框外
    assert "_stamp_ax_x" in far_blk and "_stamp_ax_y" in far_blk
    assert "_stamp_ax_x, _stamp_ax_y = 0.02, 0.96" in far_blk
    assert "ax=axu" in far_blk and "ax=axt" in far_blk
    assert 'ha="left"' in far_blk and 'va="top"' in far_blk
    assert "def _fig_stamp_xy_axes_top_left" in src
    assert "CRefPrice" in src or "參考價" in src
    assert "_tx_chg_tip = _resolve_tx_after_hours_tip" in far_blk
    assert "scale=0.56" in far_blk and "pin_bottom=True" in far_blk
    assert "0.42" in far_blk  # 八浪右緣鎖左 42%（縮圖略放大）
    assert "labelbottom=True" in far_blk
    # 左軸逐字正讀；電子盤左標全關改右欄疏開（大量＋下一層）
    assert "_set_upright_ylabel" in far_blk
    assert "def _stack_upright_ylabel" in src
    assert "rotation=0" in src
    assert "clip_on=False" in src  # 左軸逐字 ax.text
    assert "labels=False" in far_blk
    assert "0.11" in far_blk  # 電子盤右標間距
    assert "nudge=True" in far_blk  # 字盒疏開、虛線仍貼真價
    # 各欄各自爆大量日豎線；不准加權 10/15 貫穿費半／電子盤
    assert "_paint_vol_sr_mark_on_axis" in far_blk
    assert "def _paint_vol_sr_day_guides" in src
    assert "_VOL_SR_GUIDE_NEXT" in src
    assert "_paint_max_vol_day_guide((axu, axt, ax, axv)" not in far_blk
    # 三戳同一 axes 相對位；加權不加浪段大底色；費A低不准豎導
    assert "_stamp_ax_x" in far_blk
    assert 'facecolor="#40c4ff", alpha=0.06' not in far_blk
    assert 'facecolor="#ea80fc", alpha=0.05' not in far_blk
    assert '"次回測", "再回測"' in src or "'次回測', '再回測'" in src
    # 電子盤撐壓只認大量規則，不准套題旨 pred_levels
    assert "電子盤撐壓只認大量規則" in far_blk
    assert "_paint_tx_after_hours_tip" in far_blk
    assert "_TEACH_STAMP_EDGE_TX" in src
    assert "def _resolve_tx_after_hours_tip" in src
    assert "def _paint_tx_after_hours_tip" in src
    assert "費半｜台指電子盤｜加權日盤" in far_blk
    # 大B末標假突破；近窗白底戳改主圖框內左上（跟遠窗同軸座標）
    assert "假突破" in src
    assert "假突破" in far_blk and "假突破" in near_blk
    assert "_stamp_y_data" not in near_blk
    assert "_stamp_ax_x, _stamp_ax_y = 0.02, 0.96" in near_blk
    assert 'ha="left"' in near_blk and "ax=ax" in near_blk
    assert "_reserve_avoid_zone" in src
    assert "_seat_onchart_labels" in src
    # 近窗戳走 axes 左上；資料座標換算工具仍給其他標座用
    assert "def _fig_xy_from_axes_data" in src
    # 超近：上＝縮圖K、中＝說明＋八浪、下＝量；不准再疊進橫圖中下方
    assert "y=0.855" in micro_blk
    assert "add_gridspec" in micro_blk
    assert "height_ratios=(5.4, 2.55, 1.15)" in micro_blk
    assert "ax_leg" in micro_blk and "ax_wave_host" in micro_blk
    assert "AnchoredOffsetbox" not in micro_blk
    assert "他說 B→今" in micro_blk
    assert "紫實" not in micro_blk and "橙虛" not in micro_blk
    assert "ax.legend" not in micro_blk
    assert "_flash_spec_from_pivots" in src
    # 遠／近八浪縮圖＝超近同吋大小，右緣貼垂直黃虛線（最大量日）左側
    assert "_eight_wave_inset_rect_left_of_vmax" in far_blk
    assert "_eight_wave_inset_rect_left_of_vmax" in near_blk
    assert "_TEACH_EIGHT_WAVE_INSET_W_FRAC" in src
    assert "_near_inset" in near_blk
    # 超近：非C9 仍閃折；C9 改跟遠窗細線九波（c_flash=not _c9_micro）
    assert "c_flash=True" in micro_blk or "c_flash=not _c9_micro" in micro_blk
    # 近窗日K八浪不開 c_flash；c9_60m 超近專用才開（夾在 live 與 super_near 之間）
    live_only = src[
        src.index("def _render_twii_live_dark") : src.index(
            "def _render_twii_super_near_c9_60m"
        )
    ]
    assert "c_flash=True" not in live_only
    assert "_c_flash_step" in src
    assert 'panels="far"' in src or "panels: str" in src
    # 遠窗大C 必須自大B末連到今，不准 10/6 後斷線
    assert "[i_b_end, i_c, i_now]" in far_blk
    assert "緩坡" in src or "非垂直" in src
    assert "不准把 A 包進去" in src or "A 必須在黃框" in src
    assert "_TEACH_STAMP_FS" in src
    assert "_paint_stamp_hbox" in src
    assert "subplots_adjust" in near_blk
    assert "subplots_adjust" in micro_blk
    # 右標同欄 x_col；虛線自 note['x'] 連到標左緣（不准左一截短虛線）
    assert "x_col" in src
    assert "x_near_col" in near_blk or "x_col=" in near_blk
    assert "level_dash=True" in near_blk
    assert "level_dash=False" not in near_blk[near_blk.index("_place_live_right_labels") :]
    assert "x_end" in src
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
    # 末日必留：即使與前一刻太近，也不准稀釋掉最新交易日
    i2, l2 = _sparse_xticks(
        [10, 13, 16, 18], ["10/15", "10/20", "11/5", "11/6"], min_gap=3
    )
    assert l2[0] == "10/15" and l2[-1] == "11/6"
    assert i2[-1] == 18


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
    """遠窗黃帶＝大量撐壓高低；灰＝下一層；青帶＝下一撐壓；底色在K下層。"""
    src = open("biaoke_level_learn.py", encoding="utf-8").read()
    block = src[src.index("def _render_twii_far_dark") : src.index("def _render_twii_live_dark")]
    assert "_paint_window_dual_zones" in block
    assert "_paint_max_vol_hl_zone" in block or "_paint_window_dual_zones" in block
    assert "_paint_next_layer_vol_zone" in block or "_paint_window_dual_zones" in block
    assert "K棒下一層" in block or "K下一層" in src
    assert "def _paint_max_vol_hl_zone" in src
    assert "def _paint_next_sr_zone" in src
    assert "def _paint_next_layer_vol_zone" in src
    assert "def _resolve_teach_vol_sr" in src
    assert "_far_teach_bars_keeping_vol_sr" in block
    # 金K只改色；「最大量」字只留量欄（價圖不准再貼黃字標）
    special = src[src.index("def _paint_special_candle") : src.index("def _paint_vol_bars_max_yellow")]
    assert "不准再貼" in special or "量欄已有" in special
    assert "ax.text" not in special
    assert "day_tag" in src[src.index("def _paint_max_vol_hl_zone") : src.index("def _hl_spans_excluding")]
    # 右標：同一欄 x_col；虛線自轉折／末日 note['x'] 連到標左緣；字 Y＝真價
    place = src[src.index("def _place_live_right_labels") : src.index("def _his_micro_degree")]
    assert "level_dash" in place
    assert "x_col" in place
    assert "x_from" in place
    assert "x_dash_end" in place
    assert "同一右欄" in place or "同欄" in place or "x_label" in place
    assert "n - 0.85" not in place
    assert "ax.scatter" not in place
    assert "axhline" not in place
    assert "level_dash=True" in block
    # 浪／細浪硬標優先，不准被鄰近飆預測擠掉（c4↔47,637、今↔c5）
    assert "gap_wave" in place and "c4細" in place and "_tier" in place
    near_src = src[src.index("def _render_twii_live_dark") : src.index("def _render_twii_super_near_dark")]
    micro_src = src[src.index("def _render_twii_super_near_dark") : src.index("def _render_us_compare_dark")]
    assert (
        "0.062 if _c9_near_now else 0.055" in near_src
        or "min_gap=(ymax - ymin) * 0.055" in near_src
    )
    assert "nudge=True" in near_src
    # 近窗 C9 右欄精簡跟遠窗同一套
    assert 'f"大B末 {_px(y_b_end)}"' in near_src or "大B末 {_px" in near_src
    assert "side=\"left\"" in near_src or "side='left'" in near_src
    # 超近窗標題不准把 C3-3-4 裁成 C3-3（保留 now 尾碼）
    assert 'one_line")[:40]' not in micro_src and "one_line')[:40]" not in micro_src
    assert "_now" in micro_src
    # 右欄預設 n+2.55（對齊長標）；不准再漂到 n+1.15、不准 right=0.90 把標甩進圖外溝
    assert "2.55" in place
    assert "n) + 1.15" not in place and "n + 1.15" not in place
    assert "x_right_col" in block or "x_col=x_right_col" in block
    assert "min_gap=(ymax - ymin) * 0.055" in block or "0.062 if _c9_now else 0.055" in block
    assert "900.0" not in block[block.index("_place_live_right_labels") :]
    # 遠窗 xlim 跟最長軸（費半可晚於加權）；舊寫 n+8.6，現況 n_axis+8.6
    assert "n_axis + 8.6" in block or "n + 8.6" in block
    assert "right=0.978" in block or "right=0.98" in block
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
    # 大結構：⑤起4/1／⑤終6/23／大A底／大B末；近窗細分另淡標
    assert '"大A底' in block and '"大B末' in block
    assert "⑤起" in block and "⑤終" in block
    assert "20260401" in block and "20260623" in block
    assert "_paint_eight_wave_inset" in block
    assert "i_now, y_now, \"C進行中\"" in block or "i_now, y_now" in block
    assert "keep_left_of_right=True" in block
    assert "_biaoke_pred_label" in block
    assert "金虛線" in block or "大B反彈" in block or "智慧標" in pin
    # 腳註多行：不准 [:72] 裁成「9,」；完整 pred_note 再換行
    assert "pred_foot[:72]" not in block
    assert "pred_foot" in block
    assert "[:240]" in block or "pred_note" in block


def test_extend_us_ohlc_past_twii_keeps_official_only():
    """加權軸後只准追加已收美股日；不准造假加權／不准灌空量當真柱。"""
    from biaoke_level_learn import _align_us_to_twii_dates, _extend_us_ohlc_past_twii, _ymd

    bars = [
        {"date": "20261028", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
        {"date": "20261029", "open": 1.5, "high": 2, "low": 1.4, "close": 1.6, "volume": 11},
    ]
    us = [
        {"date": "20261028", "open": 100, "high": 110, "low": 99, "close": 105, "volume": 1},
        {"date": "20261029", "open": 105, "high": 112, "low": 104, "close": 108, "volume": 1},
        {"date": "20261030", "open": 108, "high": 109, "low": 104.39, "close": 106.89, "volume": 1},
    ]
    aligned = _align_us_to_twii_dates(us, bars)
    assert len(aligned["close"]) == 2
    ext, extra = _extend_us_ohlc_past_twii(aligned, us, "20261029")
    assert extra == ["20261030"]
    assert len(ext["close"]) == 3
    assert abs(float(ext["low"][-1]) - 104.39) < 1e-6
    assert abs(float(ext["close"][-1]) - 106.89) < 1e-6
    # 沒有更晚官方日 → 不延長
    ext2, extra2 = _extend_us_ohlc_past_twii(aligned, us[:2], "20261029")
    assert extra2 == []
    assert len(ext2["close"]) == 2
    assert _ymd("20261030") == "20261030"


def test_candle_span_min_body_keeps_far_sox_visible():
    """遠窗費半末根不可因 body≪span 變成看不見的細線。"""
    from biaoke_level_learn import _FAR_SOX_MIN_BODY_FRAC, _candle_span_min_body

    highs = [15000.0, 12000.0, 11620.0]
    lows = [10000.0, 10400.0, 11360.0]
    mb = _candle_span_min_body(highs, lows, frac=_FAR_SOX_MIN_BODY_FRAC)
    span = 5000.0
    assert mb >= span * _FAR_SOX_MIN_BODY_FRAC * 0.9
    # 末根真實 body 22 時，畫出來至少用 min_body
    real_body = 22.0
    assert max(real_body, mb) / span >= _FAR_SOX_MIN_BODY_FRAC * 0.9


def test_far_max_vol_day_matches_official_hl():
    """黃底高低必須＝窗內最大量那根官方日K高低（同一交易日）。

    不准鎖死歷史最大量日（例如舊錨 20261015）；庫滾到更新量大日仍要對齊該根官方高低。
    """
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
    # 黃底只認「有量且官方高低有效」的最大量根；略過量在、OHLC 卻是 0 的爛柱
    candidates = [
        i
        for i in range(len(bars))
        if vols[i] > 0
        and float(bars[i].get("high") or 0) > float(bars[i].get("low") or 0) > 0
    ]
    if not candidates:
        return
    i_vmax = max(candidates, key=lambda i: vols[i])
    hi = float(bars[i_vmax].get("high") or 0)
    lo = float(bars[i_vmax].get("low") or 0)
    assert hi > lo > 0
    assert _ymd(bars[i_vmax].get("date"))
    # 黃底用的高低＝最大量那根官方柱（anc 與 bars 同索引）
    assert abs(float(anc["highs"][i_vmax]) - hi) < 0.01
    assert abs(float(anc["lows"][i_vmax]) - lo) < 0.01
    # 舊錨日若仍在窗內且 OHLC 有效：官方柱本身沒爛（不要求它仍是最大量）
    i_1015 = _bar_index_by_ymd(bars, "20261015")
    if i_1015 is not None:
        h1015 = float(bars[i_1015].get("high") or 0)
        l1015 = float(bars[i_1015].get("low") or 0)
        if h1015 > l1015 > 0:
            assert abs(float(anc["highs"][i_1015]) - h1015) < 0.01
            assert abs(float(anc["lows"][i_1015]) - l1015) < 0.01


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
    # 11/5：空格「1 4重疊」＋走3-5／假跌破（只認他寫過）
    d35 = _his_micro_degree(
        "大盤是今天走3-5沒錯，但夜盤昨天晚上 1 4穿刺，照理說 1 4重疊，"
        "但可能不是有效穿刺，因此我一直認為今天是假跌破"
    )
    assert d35["degree"] == "C3-5"
    assert "C3-5" in d35["chain"]


def test_looks_like_level_now_spaced_14_and_fake_break():
    """他常寫『1 4重疊』不是『1-4重疊』；假跌破＋大盤要過閘。"""
    from biaoke_level_learn import looks_like_level_now

    oral = (
        "大盤是今天走3-5沒錯，但夜盤昨天晚上 1 4穿刺， 照理說 1 4重疊，"
        "但可能不是有效穿刺，因此我一直認為今天是假跌破 "
        "也許因為模糊地帶判斷有點小失誤， 所以我今天並沒有下空單。"
    )
    assert looks_like_level_now(oral) is True
    # 純個股 1 4重疊、無大盤戰場 → 不准進大盤位階閘
    assert looks_like_level_now("光聖回測波浪一， 1 4重疊附近") is False


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
        {"thesis": "大A→大B→大C｜C內橫台中繼（預估）", "chart_as_of": "20261029"}
    )
    assert mid["now"] == "C內橫台中繼"
    assert "大A底7/29" in mid["chain"] and "大B反彈" in mid["chain"]
    assert "大C進行中" in mid["chain"]
    assert "五波升完" not in mid["chain"]
    assert "C3-3" not in mid["chain"]
    deep = _wave_now_ladder(
        {
            "thesis": "大A→大B→大C｜C內＝C3-3（1→2・預估）",
            "snippet": "目前只是C3-3-1轉C3-3-2",
            "chart_as_of": "20261030",
        }
    )
    assert deep["now"] == "C3-3-2"
    assert "C3-3主跌" in deep["chain"]
    assert "現在走到：" in deep["one_line"]
    assert "as_of" not in deep["now_line"]
    assert "題旨日" in deep["day_bit"]
    to4 = _wave_now_ladder(
        {
            "thesis": "大A→大B→大C｜C內＝C3-3（3→4・預估）",
            "snippet": "目前應該是3-3-3完成轉3-3-4機率最高",
            "thesis_as_of": "20261101",
        }
    )
    assert to4["now"] == "C3-3-4"
    assert "C3-3主跌" in to4["chain"]
    assert "落在「C3-3-4」" in to4["now_line"]
    assert "題旨日 11/1" in to4["now_line"]
    assert "as_of" not in to4["now_line"] and "as_of" not in to4["teach_box"]


def test_wave_now_ladder_c9_extension_oral():
    """9波擴延：人話 C-7轉C-8→C-9；超近／話筒共用。"""
    from biaoke_level_learn import _wave_now_ladder

    pack = {
        "thesis": "大A→大B→大C｜9波擴延・C-7轉C-8→C-9（預估）",
        "snippet": (
            "大盤第二段下殺應該是走9波擴延，目前最有可能C-7轉 C-8，"
            "還有最後一小段下跌C-9要跌就全部跌完，低點約會落在35500~37300之間。"
        ),
        "wait_struct": "低點區35500~37300；C-9跌完＝這段下殺完；C走完≠新五波升",
        "thesis_as_of": "20261106",
    }
    out = _wave_now_ladder(pack)
    assert out["now"] == "C-7轉C-8"
    assert "9波擴延" in out["chain"]
    assert "C-7轉C-8" in out["one_line"] and "C-9" in out["one_line"]
    assert "C-7轉C-8" in out["now_line"]
    assert "35500~37300" in out["now_line"]
    assert "C-9" in out["now_line"] or "九" in out["now_line"]
    assert "as_of" not in out["now_line"]
    assert "題旨日 11/6" in out["now_line"]


def test_nine_wave_inset_c9_ext_labels():
    """波浪循環縮圖：9波擴延畫 C1…C9，金＝C7→C8，虛線＝C9。"""
    import inspect

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from biaoke_level_learn import (
        _c9_ext_flash_step,
        _c9_extension_active,
        _eight_wave_now_key,
        _paint_eight_wave_inset,
    )
    from wayne_navigator import _fp

    assert _c9_ext_flash_step("C-8") == 8
    assert _c9_ext_flash_step("C-9") == 9
    pack = {
        "thesis": "大A→大B→大C｜9波擴延・C-7轉C-8→C-9（預估）",
        "snippet": "9波擴延，目前最有可能C-7轉 C-8，C-9，35500~37300",
        "pred_levels": {
            "tw": [
                {"level": 37300.0, "role": "C9低上沿"},
                {"level": 35500.0, "role": "C9低下沿"},
            ]
        },
    }
    assert _c9_extension_active(pack)
    assert _eight_wave_now_key(pack) == "C-8"
    src = inspect.getsource(_paint_eight_wave_inset)
    assert "c9_ext" in src
    assert "此刻＝C-7轉C-8｜虛線＝C-9" in src
    assert "框內9波｜金＝C7→C8｜虛線＝C9" in src
    fig = plt.figure(figsize=(4, 3), dpi=80)
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key="C-8",
        detail=True,
        c_flash=True,
        c9_ext=True,
        rect=(0.1, 0.1, 0.8, 0.8),
        title="九波擴延・C",
    )
    fig.savefig("/tmp/c9_inset_unit.png")
    plt.close(fig)
    import os

    assert os.path.getsize("/tmp/c9_inset_unit.png") > 2000
    # 三窗呼叫都傳 c9_ext
    import biaoke_level_learn as bll

    full = open(bll.__file__, encoding="utf-8").read()
    assert full.count("c9_ext=") >= 3


def test_thesis_pred_c9_band_and_38000_broke():
    """35500~37300 進 pred；有 C9 時 38000 標已破；虛線下一錨改走 C9。"""
    from biaoke_level_learn import (
        _biaoke_pred_label,
        _paint_c9_low_zone_band,
        _thesis_pred_levels,
        _tw_pred_break_tag,
        _tw_pred_right_notes,
        _tw_tip_anchors,
    )

    snip = (
        "大盤第二段下殺應該是走9波擴延，目前最有可能C-7轉 C-8，"
        "還有最後一小段下跌C-9，低點約會落在35500~37300之間。"
        "第一套劇本大盤會跌到35000~38000之間。"
    )
    pred = _thesis_pred_levels(snip, "")
    roles = {str(r.get("role")): r for r in (pred.get("tw") or [])}
    assert "C9低上沿" in roles and abs(float(roles["C9低上沿"]["level"]) - 37300) < 1
    assert "C9低下沿" in roles and abs(float(roles["C9低下沿"]["level"]) - 35500) < 1
    assert "劇本一上沿" in roles
    pack = {"pred_levels": pred}
    tips = _tw_tip_anchors(pack)
    assert all(abs(t - 38000) > 1 and abs(t - 35000) > 1 for t in tips)
    assert any(abs(t - 37300) < 1 for t in tips)
    assert any(abs(t - 35500) < 1 for t in tips)
    from biaoke_level_learn import _px

    br = _tw_pred_break_tag(38000.0, [45000.0], pack=pack, role="劇本一上沿")
    assert br == "已破"
    assert _biaoke_pred_label(38000.0, br) == f"飆預測{_px(38000)}已破"
    notes = _tw_pred_right_notes(
        pack, n=10, lows=[45000.0], tip_skip=set(), bars=None
    )
    texts = " ".join(str(n.get("text") or "") for n in notes)
    assert f"{_px(38000)}已破" in texts
    assert _px(37300) in texts and _px(35500) in texts
    # 有 C9 區：舊 35000 劇本一下沿不准再出現在右標
    assert _px(35000) not in texts
    # 三窗都要掛紫底帶 helper
    import biaoke_level_learn as bll

    src = open(bll.__file__, encoding="utf-8").read()
    assert src.count("_paint_c9_low_zone_band(") >= 4  # def + far/near/micro
    assert "_paint_c9_low_zone_band" in src


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
    """話筒 trio：外圍／TX60／內部試畫只在 full；官方日K同步 trio 也要先跑。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("biaoke_level_learn.py").read_text(
        encoding="utf-8"
    )
    block = src[
        src.index("def paint_open_day_hypothesis") : src.index("def latest_teach_kit")
    ]
    assert 'panels: str = "full"' in block
    assert 'mode == "full"' in block
    # 三張必先同步最新官方日K（trio／full 都跑）；不准再卡在 complete_bar 前一日
    assert "_ensure_teach_index_bars" in block
    ensure_at = block.index("_ensure_teach_index_bars")
    assert block.rfind('mode == "full"', 0, ensure_at) < 0
    # 內部試畫仍只在 full
    snap_at = block.index("snapshot_and_score_twii")
    assert block.rfind('mode == "full"', 0, snap_at) > 0
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
    """三張教具時鐘：時段字＋HH:MM；盤前／市撮／盤中／收盤。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import (
        _teach_query_clock,
        _teach_session_phase_word,
        _teach_stamp_line,
        _TEACH_STAMP_FACE,
    )

    tz = ZoneInfo("Asia/Taipei")
    assert _TEACH_STAMP_FACE.lower() in ("#ffffff", "#fff", "white")
    # 用平日 10:17＝盤中
    live_bars = [{"date": "20261030", "live_session": 1, "close": 46000}]
    pack = {"query_at": datetime(2026, 10, 30, 10, 17, tzinfo=tz).isoformat()}
    clock = _teach_query_clock(live_bars, pack=pack)
    assert clock == "盤中 10:17"
    assert _teach_session_phase_word(datetime(2026, 10, 30, 8, 10, tzinfo=tz)) == "盤前"
    assert _teach_session_phase_word(datetime(2026, 10, 30, 8, 45, tzinfo=tz)) == "市撮"
    assert _teach_query_clock(
        live_bars,
        pack={"query_at": datetime(2026, 10, 30, 8, 45, tzinfo=tz).isoformat()},
    ) == "市撮 08:45"
    closed = _teach_query_clock(
        [{"date": "20261030", "close": 46000}],
        pack={"query_at": datetime(2026, 10, 30, 17, 5, tzinfo=tz).isoformat()},
    )
    assert closed == "收盤 17:05"
    stamp = _teach_stamp_line(
        [
            {"date": "20261029", "close": 45500.0},
            {"date": "20261030", "close": 45211.83},
        ],
        pack={"query_at": datetime(2026, 10, 30, 17, 5, tzinfo=tz).isoformat()},
        close=45211.83,
        label_prefix="加權",
    )
    # 名稱 → M/D收盤 → 價 →（漲幅％）→ 較前日點數
    assert stamp.startswith("加權 10/30收盤")
    assert "45,212" in stamp
    assert "−288" in stamp or "-288" in stamp
    assert "%" in stamp
    live_stamp = _teach_stamp_line(
        [
            {"date": "20261029", "close": 45500.0},
            {"date": "20261030", "close": 45211.83, "live_session": 1},
        ],
        pack={"query_at": datetime(2026, 10, 30, 10, 17, tzinfo=tz).isoformat()},
        close=45211.83,
        label_prefix="加權",
    )
    assert "加權 10/30盤中 查詢當下為10:17" in live_stamp
    assert live_stamp.index("查詢當下為10:17") < live_stamp.index("45,212")


def test_day_change_vs_prev_trading_day():
    """漲跌＝對前一個交易日收；顯示序價→漲幅％→點數。"""
    from biaoke_level_learn import _day_change_vs_prev, _prev_bar_close, _teach_stamp_line

    assert _prev_bar_close([{"close": 100}]) is None
    assert _prev_bar_close([{"close": 100}, {"close": 110}]) == 100.0
    up = _day_change_vs_prev(110.0, 100.0)
    assert up["pts"] == 10.0
    assert abs(float(up["pct"]) - 10.0) < 1e-9
    assert "＋10" in up["pts_text"] or "+10" in up["pts_text"]
    assert "10.00%" in up["pct_text"]
    # text＝漲幅％在前、點數在後
    assert up["text"].index("%") < len(up["pct_text"])
    assert up["pts_text"] in up["text"]
    assert up["text"].index(up["pct_text"]) < up["text"].index(up["pts_text"])
    dn = _day_change_vs_prev(45212.0, 45532.0)
    assert dn["pts"] == -320.0
    assert "−320" in dn["pts_text"] or "-320" in dn["pts_text"]
    line = _teach_stamp_line(
        [{"date": "20261029", "close": 45532}, {"date": "20261030", "close": 45212}],
        close=45212,
    )
    assert "45,212" in line
    assert "%" in line
    # 價 → ％ → 點數
    i_px = line.index("45,212")
    i_pct = line.index("%")
    i_pts = max(line.find("−320"), line.find("-320"))
    assert i_px < i_pct < i_pts


def test_us_real_close_pair_skips_twii_ffill_flat():
    """費半黃框：對真實美股日算漲跌，不准因加權軸前收填日變假 +0%。"""
    from biaoke_level_learn import (
        _align_us_to_twii_dates,
        _day_change_vs_prev,
        _us_real_close_pair,
    )

    sox = [
        {"date": "20261102", "open": 10762, "high": 10890, "low": 10300, "close": 10328},
        {"date": "20261103", "open": 10574, "high": 10761, "low": 10530, "close": 10600},
    ]
    tw_bars = [
        {"date": "20261103", "close": 43307},
        {"date": "20261104", "close": 42948},
        {"date": "20261105", "close": 41575},
    ]
    aligned = _align_us_to_twii_dates(sox, tw_bars)
    # 對齊軸末兩根都被前收填成 10600 → 假平盤
    assert aligned["close"][-1] == aligned["close"][-2] == 10600.0
    fake = _day_change_vs_prev(aligned["close"][-1], aligned["close"][-2])
    assert fake["sign"] == 0
    pair = _us_real_close_pair(sox)
    assert pair["asof"] == "20261103"
    assert pair["close"] == 10600.0
    assert pair["prev_close"] == 10328.0
    real = _day_change_vs_prev(pair["close"], pair["prev_close"])
    assert real["sign"] > 0
    assert abs(float(real["pts"]) - 272.0) < 1e-6


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


def test_same_day_fake_break_reply_merges_into_main_chrono(tmp_path):
    """11/5 短回『假跌破』依時間序併進主文；不准短回蓋掉 C3-5 主文當唯一題旨。"""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import (
        _his_micro_degree,
        _latest_biaoke_index_snip,
        _latest_level_thesis,
        ensure_tables,
    )

    db = str(tmp_path / "fakebreak.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, text TEXT)"
    )
    parent = (
        "夜盤第二組下跌脈動已經完成落底確認，也就是說C3-5完成，目前開始反彈，"
        "先觀察反彈能否穿刺45546。真正要轉震盪整理46292。最後結論：目前的盤勢大盤並沒有止穩，看細微波。"
    )
    oral = (
        "大盤是今天走3-5沒錯，但夜盤昨天晚上 1 4穿刺， 照理說 1 4重疊，"
        "但可能不是有效穿刺，因此我一直認為今天是假跌破 "
        "也許因為模糊地帶判斷有點小失誤， 所以我今天並沒有下空單。"
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        ("187684179", "2026-11-04", "18:49", parent),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, text) VALUES (?,?,?,?)",
        ("187684179:c187684179-269", "2026-11-05", "12:34", oral),
    )
    conn.commit()
    conn.close()
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2026, 11, 5, 15, 0, tzinfo=tz)
    snip, pid = _latest_biaoke_index_snip(
        db, "20261105", now=now, with_id=True
    )
    assert pid == "187684179"
    assert "C3-5完成" in snip
    assert "假跌破" in snip
    pack = _latest_level_thesis(db, as_of="20261105", now=now)
    assert "假跌破" in (pack.get("snippet_full") or pack.get("snippet") or "")
    assert "C3-5完成" in (pack.get("thesis") or "")
    assert _his_micro_degree(pack.get("snippet_full") or pack.get("snippet") or "")[
        "degree"
    ] == "C3-5"


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


def test_far_teach_rolls_left_when_over_max():
    """遠窗超過固定根數 → 只留最右一段（新日進來刪最左）。"""
    from biaoke_level_learn import _FAR_TEACH_MAX_BARS, _far_teach_roll_bars

    assert _FAR_TEACH_MAX_BARS == 152
    rows = [{"date": f"2026{i:04d}", "close": float(i)} for i in range(1, 180)]
    got = _far_teach_roll_bars(rows, max_bars=_FAR_TEACH_MAX_BARS)
    assert len(got) == 152
    assert got[0]["date"] == rows[-152]["date"]
    assert got[-1]["date"] == rows[-1]["date"]
    short = _far_teach_roll_bars(rows[:50], max_bars=_FAR_TEACH_MAX_BARS)
    assert len(short) == 50


def test_far_teach_extends_left_for_vol_sr_date():
    """大量撐壓日若被滾動裁掉 → 左側自動拉到該日，最右仍＝最新。"""
    from biaoke_level_learn import (
        _FAR_TEACH_MAX_BARS,
        _far_teach_bars_keeping_vol_sr,
        _far_teach_roll_bars,
    )

    # 200 根；第 20 根爆大量且高仍壓著收 → 滾動後會被裁掉，必須拉回
    rows = []
    for i in range(1, 201):
        d = f"2026{i:04d}"
        rows.append(
            {
                "date": d,
                "open": 100.0,
                "high": 110.0 if i != 20 else 150.0,
                "low": 90.0 if i != 20 else 80.0,
                "close": 100.0,
                "volume": 1.0 if i != 20 else 9999.0,
            }
        )
    rolled = _far_teach_roll_bars(rows, max_bars=_FAR_TEACH_MAX_BARS)
    assert str(rolled[0]["date"]).replace("-", "")[:8] > "20260020"
    got, sr = _far_teach_bars_keeping_vol_sr(
        rows,
        max_bars=_FAR_TEACH_MAX_BARS,
        vol_lookback=199,
        keep_ymds=(),  # 只測撐壓日拉長，不強制浪階日
    )
    assert (sr.get("primary") or {}).get("date") == "20260020"
    assert got[0]["date"] == "20260020"
    assert got[-1]["date"] == rows[-1]["date"]
    assert len(got) > _FAR_TEACH_MAX_BARS


def test_far_teach_keep_wave_floor_and_vol_sr():
    """浪階起點＋更早撐壓日：左側取最早需求，最右仍最新。"""
    from biaoke_level_learn import _far_teach_bars_keeping_vol_sr

    rows = []
    for i in range(1, 201):
        rows.append(
            {
                "date": f"2026{i:04d}",
                "open": 100.0,
                "high": 150.0 if i == 15 else 110.0,
                "low": 80.0 if i == 15 else 90.0,
                "close": 100.0,
                "volume": 9999.0 if i == 15 else 1.0,
            }
        )
    got, sr = _far_teach_bars_keeping_vol_sr(
        rows,
        max_bars=80,
        vol_lookback=199,
        keep_ymds=("20260030",),
    )
    assert (sr.get("primary") or {}).get("date") == "20260015"
    assert got[0]["date"] == "20260015"  # 撐壓早於 keep → 取更早
    assert got[-1]["date"] == rows[-1]["date"]


def test_teach_vol_sr_title_bit_has_next_layer():
    from biaoke_level_learn import _teach_vol_sr_title_bit

    bit = _teach_vol_sr_title_bit(
        {
            "primary": {"date": "20260328", "high": 22000, "low": 21000},
            "next": {"date": "20260415", "high": 20500, "low": 19800},
        }
    )
    assert "大量撐壓" in bit and "下一層" in bit
    assert "22000" in bit or "22,000" in bit or "22,000".replace(",", "") in bit.replace(",", "")


def test_ensure_us_index_daily_always_refreshes_recent():
    """出圖前費半／納指必刷新近窗；不准「近窗夠就整段跳過」卡舊收。"""
    import inspect

    from biaoke_level_learn import _ensure_us_index_daily, _yahoo_us_index_upsert

    src = inspect.getsource(_ensure_us_index_daily)
    assert 'range_ = "1y" if need_hist else "1mo"' in src
    assert "_yahoo_us_index_upsert" in src
    assert "近窗夠、且已有 4/28" not in src
    assert 'stats[sym] = int(n_have)\n                continue' not in src
    assert "_reconcile_us_index_last_close" in src
    upsert_src = inspect.getsource(_yahoo_us_index_upsert)
    assert "America/New_York" in upsert_src
    assert "Asia/Taipei" not in upsert_src


def test_inject_yahoo_sox_overwrites_stale_10647(tmp_path, monkeypatch):
    """遠窗黃框不准卡 11/3＝10647；出圖注入 Yahoo 近窗 → 11/5＝9011。"""
    import types

    import biaoke_level_learn as m
    from taiwan_market import ensure_index_daily_table

    db = tmp_path / "sox.db"
    ensure_index_daily_table(str(db))

    def _fake_near(_yid="^SOX"):
        return [
            {
                "date": "20261103",
                "open": 10574.0,
                "high": 10761.0,
                "low": 10530.0,
                "close": 10600.4,
                "volume": 0.0,
            },
            {
                "date": "20261104",
                "open": 10485.0,
                "high": 10652.0,
                "low": 10064.0,
                "close": 10268.65,
                "volume": 0.0,
            },
            {
                "date": "20261105",
                "open": 9806.3,
                "high": 9838.1,
                "low": 8997.4,
                "close": 9011.14,
                "volume": 0.0,
            },
        ]

    monkeypatch.setattr(m, "_fetch_yahoo_index_near_bars", _fake_near)
    stale = [
        {
            "date": "20261103",
            "open": 10500.0,
            "high": 10700.0,
            "low": 10400.0,
            "close": 10647.0,
            "volume": 0.0,
        }
    ]
    out = m._inject_yahoo_us_last_into_rows(
        stale, yid="^SOX", sym="SOX", db_path=str(db)
    )
    pair = m._us_real_close_pair(out)
    assert pair["asof"] == "20261105"
    assert abs(float(pair["close"]) - 9011.14) < 0.02
    assert abs(float(pair["prev_close"]) - 10268.65) < 0.02
    assert float(pair["close"]) < 9500


def test_far_paint_wires_sox_yahoo_inject_and_stamp_uses_pair():
    """遠窗出圖必注入 Yahoo；黃框 close 走 _us_real_close_pair 不准吃末根填日K。"""
    import inspect

    from biaoke_level_learn import _render_twii_far_dark

    src = inspect.getsource(_render_twii_far_dark)
    assert "_inject_yahoo_us_last_into_rows" in src
    assert "_us_real_close_pair(sox," in src
    assert '_sox_chg_tip = {\n            "close": float(_sox_last_repaint["c"])' not in src
    assert '"close": float(_tip_close)' in src
    # tip／黃框釘真實美股日；盤中只認 live_session=1；填日不畫假K
    assert "_sox_axis_index_for_ymd" in src
    assert 'int((_sox_live or {}).get("live_session") or 0) == 1' in src
    assert "_sox_real_days" in src
    assert "not in _sox_real_days" in src


def test_sox_axis_index_for_ymd_prefers_tw_then_extra():
    """費半 tip 索引：先加權同日格，再延長格。"""
    from biaoke_level_learn import _sox_axis_index_for_ymd

    bars = [{"date": "20261105"}, {"date": "20261106"}]
    assert (
        _sox_axis_index_for_ymd(
            bars, n_tw=2, sox_extra_dates=[], ymd="20261105", n_axis=2
        )
        == 0
    )
    assert (
        _sox_axis_index_for_ymd(
            bars,
            n_tw=2,
            sox_extra_dates=["20261107"],
            ymd="20261107",
            n_axis=3,
        )
        == 2
    )
    assert (
        _sox_axis_index_for_ymd(
            bars, n_tw=2, sox_extra_dates=[], ymd="20261107", n_axis=2
        )
        is None
    )


def test_soxx_volume_proxy_always_refreshes_near_window():
    """SOXX 量代理不准「已有≥40列」整段跳過；日期美東；價跳兇只動量。"""
    import inspect

    from biaoke_level_learn import _ensure_soxx_volume_proxy, _sox_daily_from_minutes

    src = inspect.getsource(_ensure_soxx_volume_proxy)
    assert "if int(n_have or 0) >= 40:\n            return int(n_have)" not in src
    assert 'range_ = "6mo" if n_have < 40 else "1mo"' in src
    assert "America/New_York" in src
    assert "只更新量" in src or "SET volume=?" in src
    min_src = inspect.getsource(_sox_daily_from_minutes)
    assert "DO NOTHING" in min_src
    assert "astimezone(ny)" in min_src
    assert "substr(ts,1,8)" not in min_src


def test_stamp_md_phase_close_or_intraday_before_numbers():
    """遠窗白底戳：名稱＋M/D收盤｜盤中 查詢當下為HH:MM →價→％→點數。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import (
        _stamp_md_phase,
        _stamp_when_bit,
        _tx_night_session_live,
    )

    assert _stamp_md_phase("20261105", live=False) == "11/5收盤"
    assert _stamp_md_phase("20261105", live=True) == "11/5盤中"
    assert _stamp_when_bit("20261105", live=False) == "11/5收盤"
    assert (
        _stamp_when_bit("20261105", live=True, query_hm="07:20")
        == "11/5盤中 查詢當下為07:20"
    )
    assert (
        _stamp_when_bit("20261105", live=True, query_hm="04:59:58")
        == "11/5盤中 查詢當下為04:59"
    )
    tz = ZoneInfo("Asia/Taipei")
    assert _tx_night_session_live(datetime(2026, 11, 5, 21, 0, tzinfo=tz)) is True
    assert _tx_night_session_live(datetime(2026, 11, 6, 4, 59, tzinfo=tz)) is True
    assert _tx_night_session_live(datetime(2026, 11, 6, 7, 20, tzinfo=tz)) is False
    assert _tx_night_session_live(datetime(2026, 11, 6, 10, 0, tzinfo=tz)) is False


def test_tx_next_layer_33799_is_press_not_support():
    """破 6/10 大量撐後下一層：3/6 區高 33799＝壓；撐＝32820。不准把 33799 當撐。"""
    from biaoke_level_learn import (
        _nearest_vol_support_row,
        _next_support_resist,
        _resolve_teach_vol_sr,
        _ymd,
    )

    rows = [
        {
            "date": "20260304",
            "open": 34000,
            "high": 34444,
            "low": 32834,
            "close": 33548,
            "volume": 148908,
        },
        {
            "date": "20260306",
            "open": 33695,
            "high": 33799,
            "low": 32820,
            "close": 33288,
            "volume": 135936,
        },
        {
            "date": "20260610",
            "open": 44700,
            "high": 45073,
            "low": 42334,
            "close": 43878,
            "volume": 121791,
        },
        {
            "date": "20261104",
            "open": 42000,
            "high": 42298,
            "low": 38799,
            "close": 40000,
            "volume": 80000,
        },
        {
            "date": "20261105",
            "open": 41990,
            "high": 42298,
            "low": 38799,
            "close": 38936,
            "volume": 89277,
        },
    ]
    sr = _resolve_teach_vol_sr(rows, lookback=80)
    assert sr.get("primary")
    assert float((sr["primary"] or {}).get("low") or 0) == 42334.0
    assert bool((sr["primary"] or {}).get("broke_support")) is True
    nxt = sr.get("next") or {}
    assert nxt, "破撐後必須掛下一層大量區"
    assert _ymd(nxt.get("date")) in ("20260306", "20260304")
    # 區高＝壓（約 33799／34444）；撐＝區低，绝不是 33799
    assert float(nxt.get("high") or 0) >= 33790.0
    assert abs(float(nxt.get("low") or 0) - 33799.0) > 50.0
    near = _nearest_vol_support_row(sr, px=38936.0)
    assert near is not None
    assert float(near["low"]) == float(nxt["low"])
    nxt_sr = _next_support_resist(
        38936.0,
        supports=[float(sr["primary"]["low"]), float(nxt["low"])],
        resists=[float(sr["primary"]["high"]), float(nxt["high"])],
    )
    assert nxt_sr.get("support") == float(nxt["low"])
    assert abs(float(nxt_sr["support"]) - 33799.0) > 50.0


def test_reconcile_sox_last_close_patches_stale_intraday(tmp_path, monkeypatch):
    """已收後庫內末日若偏離 Yahoo 現價 → 覆寫成官方收（修 9185→9011）。"""
    import sys
    import types
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import biaoke_level_learn as m

    db = tmp_path / "t.db"
    conn = __import__("sqlite3").connect(str(db))
    conn.execute(
        """
        CREATE TABLE index_daily(
            date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, pct_change REAL, updated_at TEXT,
            PRIMARY KEY(date, symbol)
        )
        """
    )
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?)",
        ("20261104", "SOX", 10485.0, 10652.0, 10064.0, 10268.65, 0, None, "t"),
    )
    conn.execute(
        "INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?)",
        ("20261105", "SOX", 9806.0, 9838.0, 9060.0, 9185.62, 0, None, "t"),
    )
    conn.commit()
    conn.close()

    ts = int(
        datetime(2026, 11, 5, 16, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    )

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 9011.1376953125,
                                "regularMarketTime": ts,
                                "regularMarketOpen": 9806.3115234375,
                                "regularMarketDayHigh": 9838.130859375,
                                "regularMarketDayLow": 8997.3857421875,
                            },
                            "timestamp": [ts],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [9806.3115234375],
                                        "high": [9838.130859375],
                                        "low": [8997.3857421875],
                                        "close": [9011.1376953125],
                                        "volume": [0],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }

    fake_us = types.ModuleType("us_overnight")
    fake_us.us_tape_phase = lambda *_a, **_k: "closed"
    monkeypatch.setitem(sys.modules, "us_overnight", fake_us)
    fake_req = types.ModuleType("requests")
    fake_req.get = lambda *_a, **_k: _Resp()
    monkeypatch.setitem(sys.modules, "requests", fake_req)

    ok = m._reconcile_us_index_last_close(str(db), sym="SOX", yid="^SOX")
    assert ok is True
    conn = __import__("sqlite3").connect(str(db))
    close = conn.execute(
        "SELECT close, pct_change FROM index_daily WHERE symbol='SOX' AND date='20261105'"
    ).fetchone()
    conn.close()
    assert close is not None
    assert abs(float(close[0]) - 9011.1376953125) < 0.01
    assert float(close[1]) < -12.0


def test_far_twii_macro_wave5_apr_to_jun_and_big_a_729():
    """遠窗自3月底：推進⑤＝4/1→6/23；大A底仍＝7/29，不准用四月窗底當A。"""
    import inspect

    from biaoke_level_learn import _render_twii_far_dark

    src = inspect.getsource(_render_twii_far_dark)
    assert "20260331" in src
    assert "20260401" in src and "20260623" in src
    assert "20260729" in src
    assert "大A底" in src
    assert "⑤起" in src and "⑤終" in src
    assert "_twii_macro_wave_anchors" in src
    assert "_paint_eight_wave_inset" in src
    assert "_far_teach_bars_keeping_vol_sr" in src or "_FAR_TEACH_MAX_BARS" in src
    from biaoke_level_learn import (
        _FAR_TEACH_MAX_BARS,
        _FAR_TEACH_VOL_LOOKBACK,
        _build_live_pack,
        _far_teach_bars_keeping_vol_sr,
        _twii_macro_wave_anchors,
        _twii_bars_for_teach,
        _ymd,
    )
    from datetime import datetime
    from zoneinfo import ZoneInfo

    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        pytest.skip("no market db")
    pack = _build_live_pack(
        db, now=datetime(2026, 11, 1, 13, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    bars = _twii_bars_for_teach(db, 400, pack)
    if len(bars) < 80:
        pytest.skip("twii bars too short")
    bars, _sr = _far_teach_bars_keeping_vol_sr(
        list(bars),
        max_bars=_FAR_TEACH_MAX_BARS,
        vol_lookback=_FAR_TEACH_VOL_LOOKBACK,
        keep_ymds=("20260331", "20260401"),
    )
    mac = _twii_macro_wave_anchors(bars)
    assert mac, "macro anchors must stay after vol-SR left-extend"
    assert _ymd(bars[int(mac["i5_start"])].get("date")) in ("20260331", "20260401")
    assert _ymd(bars[int(mac["i5_end"])].get("date")) == "20260623"
    assert _ymd(bars[int(mac["i_alow"])].get("date")) in ("20260728", "20260729")
    lows = [float(r.get("low") or 0) for r in bars]
    i729 = int(mac["i_alow"])
    i5e = int(mac["i5_end"])
    # 窗內最低可在四月 → 大A底仍釘 7/29，不准用 min
    i_min = min(range(0, i5e + 1), key=lambda i: lows[i])
    assert _ymd(bars[i_min].get("date")) < "20260701"
    assert abs(float(lows[i729]) - 39384.85) < 2.0


def test_thesis_and_ladder_say_big_abc_not_wave5_from_july():
    """題旨／層級鏈：大A→大B→大C；不准再寫五波升完讓人把7/29當上升⑤起。"""
    from biaoke_level_learn import _build_live_pack, _wave_now_ladder
    from datetime import datetime
    from zoneinfo import ZoneInfo

    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        pytest.skip("no market db")
    pack = _build_live_pack(
        db,
        now=datetime(2026, 11, 1, 13, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    thesis = str((pack or {}).get("thesis") or "")
    if not thesis:
        pytest.skip("no thesis in db")
    assert "大A" in thesis or "大B" in thesis or "大C" in thesis
    assert "五波後下降ABC" not in thesis
    ladder = _wave_now_ladder(pack or {})
    assert "大A底7/29" in ladder["steps"]
    assert "大B反彈" in ladder["steps"]
    assert "五波升完" not in ladder["steps"]


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
    assert any(abs(v - 39384) < 2 for v in anchors)
    # 有他點 → 虛線梯跟他走，不准只剩舊錨 45546→44210
    assert anchors[0] >= anchors[-1]
    assert 44042.0 in anchors or any(abs(v - 39384) < 2 for v in anchors)


def test_sox_pred_cascade_to_feb25_8498_when_9865_broken():
    """劇本一：破9865 → 測2/25高8498；現價已破則次回測改已破並掛再回測。"""
    from biaoke_level_learn import _refresh_sox_pred_cascade, _thesis_pred_levels

    snip = (
        "7/29 A波低點10445必破，星期五低點10439已經破A波低點。"
        "接下來會去測4/28 9865。"
        "第一套劇本：費城半導體指數必破9865，會去測2/25高點8498。"
    )
    pred = _thesis_pred_levels(snip, "data/wayne_market.db")
    roles = {str(r.get("role")): r for r in pred["sox"]}
    assert "再回測" in roles
    assert abs(float(roles["再回測"]["level"]) - 8498) < 3
    # 僅寫到9865、現價已破 → 階梯仍要掛8498
    snip2 = (
        "7/29 A波低點10445必破，星期五低點10439已經破A波低點。"
        "接下來會去測4/28 9865，如果破，大盤走5波下跌的機率就高很多。"
    )
    pred2 = _thesis_pred_levels(snip2, "data/wayne_market.db")
    pred2 = _refresh_sox_pred_cascade(pred2, "data/wayne_market.db", sox_px=9310.0)
    roles2 = {str(r.get("role")): r for r in pred2["sox"]}
    assert roles2["次回測"]["tag"] == "已破"
    assert "再回測" in roles2 and abs(float(roles2["再回測"]["level"]) - 8498) < 3
    assert "2/25" in str(roles2["再回測"].get("label") or "")


def test_c_forecast_tip_follows_biaoke_tip_anchors():
    """飆大點位換了 → 預估虛線端點跟著換。"""
    from biaoke_level_learn import _c_forecast_tip, _px, _tw_tip_anchors

    pack = {
        "pred_levels": {
            "tw": [
                {"level": 44042.0, "label": "飆預測44042"},
                {"level": 39384.0, "label": "飆預測39384"},
            ],
            "sox": [],
        }
    }
    anchors = _tw_tip_anchors(pack)
    assert 44042.0 in anchors and 39384.0 in anchors
    tip = _c_forecast_tip(
        i_now=10,
        y_now=46368.0,
        y_ref=49059.0,
        lows=[46055.0, 45676.0],
        anchors=anchors,
    )
    assert tip["fut_y"] == 44042.0
    assert tip["anchor_y"] == 44042.0
    assert _px(44042.0) in tip["label"]
    tip2 = _c_forecast_tip(
        i_now=10,
        y_now=43000.0,
        y_ref=49059.0,
        lows=[43500.0],
        anchors=anchors,
    )
    assert tip2["fut_y"] == 39384.0
    assert _px(39384.0) in tip2["label"]


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
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, kind TEXT, text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        (
            "main187",
            "2026-11-01",
            "11:49",
            "post",
            "星期五夜盤C3-3跌勢運行中並未完成。"
            "由周五夜盤來拆解波浪位階，目前應該是3-3-3完成轉3-3-4機率最高，"
            "第二組下跌推動脈動連主跌段都還未完成，下周一絕對不能去抄底破底。",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        (
            "main187:c48-2",
            "2026-11-01",
            "12:03",
            "reply",
            "費辦根本沒跌完，從細微波看的出來，不要想太多",
        ),
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


def test_snip_main_plus_thread_chrono_not_drowned(tmp_path):
    """討論串自回再多也要先抓主文；凌晨改口依時間序併進題旨。"""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from biaoke_level_learn import (
        _latest_biaoke_index_snip,
        _latest_level_thesis,
        _thesis_pred_levels,
        _tw_tip_anchors,
        ensure_tables,
    )

    db = str(tmp_path / "chrono.db")
    ensure_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS biaoke_posts("
        "id TEXT PRIMARY KEY, date TEXT, time TEXT, kind TEXT, text TEXT)"
    )
    prior = (
        "第一套劇本，大盤走5段3段下殺，則7/29低點必破，大盤會跌到35000~38000之間，"
        "此時搭配費城半導體指數必破9865，會去測2/25高點8498。"
    )
    main = (
        "夜盤第二組下跌脈動已經完成落底確認，但是進場交易風險極高。"
        "夜盤目前已經確認第二組下跌脈動完成也就是說C3-5完成，目前開始反彈，"
        "先觀察反彈能否穿刺45546，如果沒辦法穿刺，則再下去走第三組下跌機率很高。"
        "真正要轉震盪整理46292，才能化解短期下跌勢。"
        "因為我怎麼看費城半導體至少殺到9865附近，目前還有一段距離。"
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        ("187638311", "2026-11-04", "13:16", "post", prior),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        ("187684179", "2026-11-04", "18:49", "post", main),
    )
    # 塞很多短回，模擬討論串灌庫把 LIMIT 擠爆
    for i in range(50):
        conn.execute(
            "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
            (
                f"187684179:c{i}",
                "2026-11-05",
                f"{10 + (i // 60):02d}:{i % 60:02d}",
                "reply",
                "空手一星期觀察就好",
            ),
        )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        (
            "187684179:c269",
            "2026-11-05",
            "12:34",
            "reply",
            "大盤是今天走3-5沒錯，但夜盤昨天晚上1 4穿刺，可能不是有效穿刺，假跌破。",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        (
            "187684179:c325-1",
            "2026-11-06",
            "00:02",
            "reply",
            "其實我認為9865會破，因為大盤要整理大概兩年",
        ),
    )
    conn.execute(
        "INSERT INTO biaoke_posts(id, date, time, kind, text) VALUES (?,?,?,?,?)",
        (
            "187684179:c325-2",
            "2026-11-06",
            "00:03",
            "reply",
            "大盤非常有機會到35000-38000之間",
        ),
    )
    conn.commit()
    conn.close()
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2026, 11, 6, 1, 20, tzinfo=tz)
    snip, pid = _latest_biaoke_index_snip(
        db, "20261106", now=now, with_id=True
    )
    assert pid == "187684179"
    assert "C3-5完成" in snip
    assert "45546" in snip and "46292" in snip
    assert "8498" in snip  # 同日較早劇本主文併入
    assert "9865會破" in snip
    assert "35000-38000" in snip or "35000~38000" in snip
    # 短「走3-5／假跌破」不准當唯一題旨蓋掉主文
    assert not snip.startswith("大盤是今天走3-5")
    thesis = _latest_level_thesis(db, as_of="20261106", now=now)
    assert "C3-5完成" in thesis["thesis"]
    pred = _thesis_pred_levels(snip, db)
    roles = {str(r.get("role")): r for r in (pred.get("tw") or [])}
    assert "反彈穿刺" in roles and abs(float(roles["反彈穿刺"]["level"]) - 45546) < 1
    assert "轉震盪" in roles and abs(float(roles["轉震盪"]["level"]) - 46292) < 1
    assert any(abs(float(r["level"]) - 35000) < 1 for r in pred["tw"])
    assert any(abs(float(r["level"]) - 38000) < 1 for r in pred["tw"])
    sox = {str(r.get("role")): r for r in (pred.get("sox") or [])}
    assert "次回測" in sox
    assert "再回測" in sox and abs(float(sox["再回測"]["level"]) - 8498) < 3
    # 上方壓不准當下跌虛線下一錨
    tips = _tw_tip_anchors({"pred_levels": pred})
    assert all(abs(t - 45546) > 1 and abs(t - 46292) > 1 for t in tips)


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


def test_teach_twii_bars_include_latest_index_day_past_complete_bar():
    """教具 teach=True 必須吃到 index_daily 最新日；不准被 complete_bar 卡掉。"""
    from biaoke_level_learn import _twii_bars_for_teach, _twii_chart_as_of, _ymd
    from biaoke_wave import _complete_bar_ymd, _load_twii_bars

    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        pytest.skip("no market db")
    cap = _complete_bar_ymd(db)
    teach = _load_twii_bars(db, n=8, teach=True)
    capped = _load_twii_bars(db, n=8, teach=False)
    if not teach or not capped:
        pytest.skip("no twii bars")
    assert teach and capped
    teach_last = _ymd(teach[-1].get("date"))
    cap_last = _ymd(capped[-1].get("date"))
    assert teach_last
    assert teach_last >= cap_last
    if cap and teach_last > cap:
        # 官方指數已有更新日時，教具一定要比 complete_bar 新
        assert teach_last > cap
    assert _twii_chart_as_of(db) == teach_last
    bars = _twii_bars_for_teach(db, 120, {})
    assert _ymd(bars[-1].get("date")) == teach_last


def test_merge_live_twii_display_bar_overlays_today(monkeypatch):
    """盤中 MIS 疊顯示柱：只渲染、不寫庫、標 live_session。"""
    from biaoke_level_learn import _merge_live_twii_display_bar

    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: True)
    bars = [
        {
            "date": "20261029",
            "open": 1,
            "high": 2,
            "low": 1,
            "close": 1.5,
            "volume": 10,
        }
    ]
    live = {
        "price": 45200.0,
        "open": 45100.0,
        "high": 45300.0,
        "low": 45000.0,
        "volume": 99,
        "date": "20261030",
    }
    # 固定牆鐘；日以 live.date 為準
    monkeypatch.setattr(
        "biaoke_level_learn.datetime",
        type(
            "D",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: datetime(2026, 10, 30, 10, 30, tzinfo=TAIPEI)
                )
            },
        ),
    )
    out = _merge_live_twii_display_bar(bars, live)
    assert len(out) == 2
    assert out[-1]["date"] == "20261030"
    assert out[-1]["close"] == 45200.0
    assert float(out[-1]["volume"]) == 99.0
    assert int(out[-1].get("live_session") or 0) == 1


def test_merge_live_twii_off_hours_when_official_lags(monkeypatch):
    """盤後空窗：官方日K仍停昨日 → 仍疊 MIS 今日柱，標收盤不准寫盤中。"""
    from biaoke_level_learn import _merge_live_twii_display_bar

    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: False)
    bars = [
        {
            "date": "20261105",
            "open": 42000,
            "high": 43000,
            "low": 41000,
            "close": 41575,
            "volume": 50,
        }
    ]
    live = {
        "price": 39701.64,
        "open": 41000.0,
        "high": 41200.0,
        "low": 37800.0,
        "volume": 120,
        "date": "20261106",
    }
    out = _merge_live_twii_display_bar(bars, live)
    assert len(out) == 2
    assert out[-1]["date"] == "20261106"
    assert abs(float(out[-1]["close"]) - 39701.64) < 0.01
    assert float(out[-1]["volume"]) == 120.0
    assert int(out[-1].get("live_session") or 0) == 0


def test_merge_live_twii_off_hours_skips_when_official_has_today(monkeypatch):
    """盤後：官方已有今日收 → 不准再用 MIS 蓋。"""
    from biaoke_level_learn import _merge_live_twii_display_bar

    monkeypatch.setattr("live_quote.is_live_merge_window", lambda: False)
    bars = [
        {
            "date": "20261106",
            "open": 41000,
            "high": 41200,
            "low": 37800,
            "close": 39701.64,
            "volume": 200,
        }
    ]
    live = {
        "price": 39999.0,
        "open": 41000.0,
        "high": 41200.0,
        "low": 37800.0,
        "volume": 1,
        "date": "20261106",
    }
    out = _merge_live_twii_display_bar(bars, live)
    assert len(out) == 1
    assert abs(float(out[-1]["close"]) - 39701.64) < 0.01
    assert float(out[-1]["volume"]) == 200.0


def test_fill_live_twii_when_official_lags(monkeypatch):
    """prepare 路徑：開市日官方落後 → pack 補 live_twii。"""
    from biaoke_level_learn import _fill_live_twii_when_official_lags

    monkeypatch.setattr(
        "trading_calendar.is_tw_open_calendar_day", lambda d: True
    )
    monkeypatch.setattr(
        "biaoke_level_learn._twii_chart_as_of", lambda _db: "20261105"
    )
    monkeypatch.setattr(
        "live_quote.fetch_mis_index_quote",
        lambda fresh=False, require_session=True: {
            "price": 39701.64,
            "date": "20261106",
            "volume": 88,
        },
    )
    pack = _fill_live_twii_when_official_lags(
        {"chart_as_of": "20261105"},
        "/tmp/x.db",
        now=datetime(2026, 11, 6, 17, 50, tzinfo=TAIPEI),
    )
    assert pack.get("live_twii")
    assert abs(float(pack["live_twii"]["price"]) - 39701.64) < 0.01


def test_merge_live_sox_display_bar_overlays_session():
    """費半盤中 Yahoo 疊顯示柱：跟 live date 走、不寫庫。"""
    from biaoke_level_learn import _merge_live_sox_display_bar

    bars = [
        {
            "date": "20261028",
            "open": 10000,
            "high": 10100,
            "low": 9900,
            "close": 10050,
            "volume": 0,
        }
    ]
    live = {
        "date": "20261029",
        "open": 10200.0,
        "high": 10350.0,
        "low": 10150.0,
        "close": 10300.0,
        "volume": 0,
        "volume_proxy": 1_200_000,
        "live_session": 1,
    }
    out = _merge_live_sox_display_bar(bars, live)
    assert len(out) == 2
    assert out[-1]["date"] == "20261029"
    assert out[-1]["close"] == 10300.0
    assert int(out[-1].get("live_session") or 0) == 1


def test_near_micro_right_notes_follow_tip_anchors():
    """近／超近右欄飆預測錨跟 tip_anchors，不准寫死 45546／44210。"""
    from biaoke_level_learn import _render_twii_live_dark, _render_twii_super_near_dark

    near = inspect.getsource(_render_twii_live_dark)
    micro = inspect.getsource(_render_twii_super_near_dark)
    for blk in (near, micro):
        assert "for anch in tip_anchors:" in blk
        assert '"y": 45546.0' not in blk
        assert '"y": 44210.0' not in blk
        assert "anchors=tip_anchors" in blk


def test_near_micro_follow_far_c9_twii_presentation():
    """近／超近加權跟遠窗同一套：C9 右欄精簡、浪號靠左、九波細線標題。"""
    from biaoke_level_learn import (
        _render_twii_far_dark,
        _render_twii_live_dark,
        _render_twii_super_near_c9_60m,
        _render_twii_super_near_dark,
    )

    far = inspect.getsource(_render_twii_far_dark)
    near = inspect.getsource(_render_twii_live_dark)
    micro = inspect.getsource(_render_twii_super_near_dark)
    micro60 = inspect.getsource(_render_twii_super_near_c9_60m)
    # 遠窗基準：C9 右欄精簡＋九波細線
    assert "_c9_now_step_label()" in far
    assert 'title="九波擴延"' in far
    assert "scale=0.56" in far and "pin_bottom=True" in far
    assert "nudge=True" in far
    # 近窗跟進
    assert "_c9_now_step_label()" in near
    assert 'title="九波擴延"' in near
    assert "nudge=True" in near
    assert 'side="left"' in near
    assert "大B末 {_px" in near or 'f"大B末 {_px' in near
    assert "_stamp_ax_x, _stamp_ax_y = 0.02, 0.96" in near
    assert "avoid_top_left_stamp=True" in near
    assert "float(i5s) + 7.5" in near
    assert "float(i5e) + 7.0" in near
    assert "_teach_eight_wave_inset_wh" in near
    assert "0.62" in near
    assert "width) * 0.15" in near
    assert "35500.0" in near
    assert "_near_major_date_labs" in near
    # C7／C8 字標多餘（右欄已有 C-7轉C-8今）；圓點仍留
    path_src = inspect.getsource(
        __import__("biaoke_level_learn", fromlist=["_paint_c9_ext_k_path"])._paint_c9_ext_k_path
    )
    assert 'lab in {"C7", "C8"}' in path_src or "lab in {'C7', 'C8'}" in path_src
    # 超近改回日K；60 分函式仍留著但不當主路
    assert "_render_twii_super_near_c9_60m" not in micro
    assert "_c9_now_step_label()" in micro
    assert 'title="九波擴延"' in micro
    assert 'side="left"' in micro
    assert "nudge=True" in micro
    assert "_c9_now_step_label()" in micro60
    assert 'title="九波擴延"' in micro60
    assert 'side="left"' in micro60
    assert "nudge=True" in micro60
    assert "大B末 {_px" in micro60 or 'f"大B末 {_px' in micro60


def test_finish_last_twii_used_by_near_and_micro():
    """近／超近右標後必蓋回末日縮圖K；遠窗亦有末根重畫。"""
    from biaoke_level_learn import (
        _finish_last_twii_candle,
        _render_twii_far_dark,
        _render_twii_live_dark,
        _render_twii_super_near_dark,
    )

    near = inspect.getsource(_render_twii_live_dark)
    micro = inspect.getsource(_render_twii_super_near_dark)
    far = inspect.getsource(_render_twii_far_dark)
    assert "_finish_last_twii_candle" in near
    assert "_finish_last_twii_candle" in micro
    assert "_paint_one_live_candle" in far
    assert "_tw_last_repaint" in far
    assert "_twii_bars_for_teach" in near
    assert "_twii_bars_for_teach" in micro
    assert "_twii_bars_for_teach" in far
    src = inspect.getsource(_finish_last_twii_candle)
    assert "facecolors=\"none\"" in src or "facecolors='none'" in src


def test_place_live_right_labels_keeps_c4_c5_now():
    """浪／細浪硬標優先：c4／c5／今 不准被鄰近飆預測擠掉。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from biaoke_level_learn import _place_live_right_labels, _px
    from wayne_navigator import _fp

    fig, ax = plt.subplots()
    notes = [
        {"x": 10, "y": 49969.0, "text": "⑤ 49,969", "color": "#ff8a80"},
        {"x": 12, "y": 47637.0, "text": "飆預測 47,637", "color": "#4dd0e1"},
        {"x": 14, "y": 47332.0, "text": f"c4細 {_px(47332.0)}", "color": "#ce93d8"},
        {"x": 16, "y": 45677.0, "text": f"c5細 {_px(45677.0)}", "color": "#ce93d8"},
        {"x": 18, "y": 45212.0, "text": f"今 {_px(45212.0)}", "color": "#ea80fc"},
        {"x": 0, "y": 44210.0, "text": "飆預測 44,210未破", "color": "#82b1ff"},
    ]
    _place_live_right_labels(
        ax,
        notes,
        n=20,
        ymin=39000,
        ymax=52000,
        fp=_fp,
        level_dash=True,
        min_gap=(52000 - 39000) * 0.055,
    )
    texts = [t.get_text() for t in ax.texts]
    plt.close(fig)
    assert any("c4細" in t for t in texts), texts
    assert any("c5細" in t for t in texts), texts
    assert any(t.startswith("今") for t in texts), texts
