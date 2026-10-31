"""2026-10-28 智能標籤：昨收誤導／壓撐擋尾K／爆大量擋紫箭／淡灰藍趨勢線。"""
from __future__ import annotations

import inspect


def test_close_tag_clearance_widened_for_prev_close():
    from biaoke_chart import _CLOSE_TAG_CANDLE_CLEAR, _close_tags_lower_right_y

    assert float(_CLOSE_TAG_CANDLE_CLEAR) >= 11.0
    # 6213 級中價：錨點必須明顯低於現價，不准落在 750 現價帶
    ay = _close_tags_lower_right_y(350.0, 1000.0, avoid_price=778.0)
    assert ay < 620.0
    assert abs(ay - 778.0) >= 140.0


def test_structure_skips_near_end_spike_vline():
    import biaoke_chart as bc

    src = inspect.getsource(bc.render_biaoke_structure_png)
    assert "n) - 6" in src or "n - 6" in src
    assert "當日價" in src or "尾端虛線" in src
    # 量圖末日豎虛線已刪（貼昨收會誤導）
    assert "ax2.axvline(n - 0.45" not in src


def test_structure_prev_close_gutter_hline():
    from biaoke_chart import _place_right_notes

    src = inspect.getsource(_place_right_notes)
    assert "true_prev_y" in src
    assert "短水平虛線" in src or "真昨收價" in src
    assert "gutter_x0" in src


def test_volzone_tail_crush_and_short_zone_sep():
    from vol_zone_chart import _paint_key_zone_smart_tags

    src = inspect.getsource(_paint_key_zone_smart_tags)
    assert "tail0" in src
    assert "4.2" in src
    assert "短大量區" in src or "need * 0.55" in src
    assert "不准預設釘末日右溝" in src or "偏左" in src


def test_volzone_ochre_keeps_below_signal_row():
    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "_vol_callout_cap" in src
    # 量標上緣：長「下一層量日」clip_on=False 防裁半；仍受 _vol_callout_cap 限高
    assert "clip_on=False" in src or "clip_on=not long_layer" in src
    assert "紫箭" in src or "訊號列" in src
    assert "long_layer" in src


def test_stock_quiet_trend_rail_constants():
    from vol_zone_chart import (
        _STOCK_TREND_RAIL_COLOR,
        _STOCK_TREND_RAIL_DASH,
        _STOCK_TREND_RAIL_LW,
        paint_vol_zone_parallel_channel,
        render_lookup_vol_result,
    )

    # 淡灰藍但須縮圖可辨（過淡＝看起來沒畫）
    assert str(_STOCK_TREND_RAIL_COLOR).lower().startswith("#")
    assert float(_STOCK_TREND_RAIL_LW) >= 1.2
    assert isinstance(_STOCK_TREND_RAIL_DASH, tuple)
    assert "with_parallel_channel=True" in inspect.getsource(render_lookup_vol_result)
    # 平行軌保底不准盲放近端蓋縮圖 K；須 ignore_k=False 掃淨空／軸外溝
    qsrc = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "ignore_k=False" in qsrc
    assert "_recent_cut" in qsrc or "recent_cut" in qsrc
    assert "ink:quiet-rail" in qsrc
    assert "n - 3.2" not in qsrc  # 舊盲放右緣
    # 導航臉漏傳仍開平行軌（v2e／預覽不准再無軌）
    from vol_zone_chart import render_volume_zone_result

    rsrc = inspect.getsource(render_volume_zone_result)
    assert "if with_nav_signals:" in rsrc
    assert "with_parallel_channel = True" in rsrc
    psrc = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "quiet_rails" in psrc
    assert "draw_markers=False" in psrc
    # 改口：要標名＋最新價；不准再強制 paint_labels=False
    assert "if quiet:\n        paint_labels = False" not in psrc
    assert "_STOCK_TREND_LABEL_FS" in psrc or "_fmt_price" in psrc
    # 個股 quiet：幾何空窗，不准每候選整圖 canvas.draw（1303 卡死）
    assert "_channel_text_box_data" in psrc
    assert "_PIXEL_DRAW_BUDGET" in psrc
    assert "卡死話筒讀秒" in psrc or "不准每候選整圖" in psrc


def test_vol_zone_dpi_sharpness_floor():
    """結構／大量：paint 可 220 少 Agg；輸出 save 底線 238、仍輕於導航 320。"""
    from vol_zone_chart import VOL_ZONE_DPI, VOL_ZONE_SAVE_DPI
    from wayne_navigator import NAV_CHART_DPI

    assert int(VOL_ZONE_DPI) >= 220
    assert int(VOL_ZONE_SAVE_DPI) >= 238
    assert int(VOL_ZONE_SAVE_DPI) < int(NAV_CHART_DPI)
    assert int(VOL_ZONE_SAVE_DPI) <= 280  # 防 OOM：不准無上限狂加


def test_lookup_progress_tick_has_hard_elapsed_cap():
    """查股 LOADING 逾時不准 silently dismiss；要 overtime 文案並等結果／錯誤。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot)
    assert "_WAIT_MAX_ELAPSED_S" in src
    # 查股 _progress_tick：逾時改 overtime，不准當成功收泡泡
    tick = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "overtime=" in tick
    assert "查股逾時仍在出圖" in src or "overtime=overtime" in tick
    # 海選／plain wait 仍可 dismiss 殘框；查股路徑不准靠 dismiss 冒充成功
    progress_fn = WayneTelegramBot._chart_progress_text
    txt = progress_fn(130, sent=["card", "glance", "struct"], current="vol", overtime=True)
    assert "逾時" in txt
    assert "with_parallel_channel=True" in src  # memo 鍵對齊第 4 張


def test_volzone_ink_right_margin_keeps_tick_numbers():
    """軸右緣內縮留刻度溝；外框 0.982 封閉右邊（刻度不准出畫布／卡框）。"""
    import inspect

    from ink_chart_theme import (
        VOL_AXES_X1,
        VOL_OUTER_X1,
        align_vol_panel_margins,
        apply_vol,
        vol_close_right_outer_frame,
    )

    assert float(VOL_AXES_X1) < float(VOL_OUTER_X1)
    assert float(VOL_AXES_X1) <= 0.92
    assert float(VOL_OUTER_X1) == 0.982
    src = inspect.getsource(align_vol_panel_margins)
    assert "VOL_AXES_X1" in src
    assert "target_x1 = 0.982" not in src
    assert "vol_close_right_outer_frame" in inspect.getsource(apply_vol)
    assert "ink:vol-outer-frame" in inspect.getsource(vol_close_right_outer_frame)


def test_volzone_quiet_rail_footnote_not_in_foot1():
    """淡灰藍說明不准塞進 foot1 第一行（Reviewer-A：整行左右裁切）。"""
    import inspect

    from vol_zone_chart import _paint_volume_zone

    src = inspect.getsource(_paint_volume_zone)
    assert "quiet_bit" in src
    # foot1 組句後面不准再插 quiet_bit
    assert 'f"{quiet_bit}"' not in src.split("foot1 = (")[1].split("foot2 = (")[0]
    assert "淡灰藍虛線＝平行趨勢" in src
