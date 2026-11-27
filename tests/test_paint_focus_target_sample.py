# -*- coding: utf-8 -*-
"""最近重點標的樣張：營收單位／季EPS拆累計／前方壓力優先。"""
from __future__ import annotations

from scripts.paint_focus_target_sample import (
    _dodge_right_ys,
    _eps_singles_cum,
    _rev_yi,
    drop_measure_points,
    drop_measure_triangle_verts,
    pick_forward_pressure_zone,
    rebound_fib_from_wave_bottom,
    wave24_descend_line,
)


def test_drop_measure_triangle_lin_style():
    """林款倒三角幾何仍保留（給之後投影用）。"""
    verts = drop_measure_triangle_verts(10.0, 284.0, 40.0, 146.0)
    assert verts == [(10.0, 284.0), (40.0, 284.0), (40.0, 146.0)]
    assert drop_measure_points(284.0, 146.0) == 138.0


def test_rebound_fib_from_wave_bottom():
    """最底往上：低＋(高−低)×0.382/0.5/0.618。"""
    lv = rebound_fib_from_wave_bottom(284.0, 146.0)
    assert [r for r, _ in lv] == [0.382, 0.5, 0.618]
    assert abs(lv[0][1] - (146 + 138 * 0.382)) < 1e-6
    assert abs(lv[1][1] - (146 + 138 * 0.5)) < 1e-6
    assert abs(lv[2][1] - (146 + 138 * 0.618)) < 1e-6
    assert rebound_fib_from_wave_bottom(100.0, 100.0) == []


def test_wave24_descend_line_extends_to_last_day():
    """②–④ 連線左右多伸；斜率＝(y4−y2)/(j4−j2)。"""
    line = wave24_descend_line(
        10.0, 300.0, 40.0, 240.0, 80.0, extend_left=4.0, extend_right=5.0
    )
    assert line is not None
    x0, y0, x1, y1 = line
    assert x0 == 6.0
    assert x1 == 85.0
    slope = (240.0 - 300.0) / 30.0
    assert abs(y0 - (300.0 + slope * (6.0 - 10.0))) < 1e-9
    assert abs(y1 - (300.0 + slope * (85.0 - 10.0))) < 1e-9
    clipped = wave24_descend_line(
        10.0, 300.0, 40.0, 240.0, 80.0, x_clip_left=20.0, extend_left=4.0
    )
    assert clipped is not None
    assert clipped[0] == 20.0
    assert wave24_descend_line(40.0, 240.0, 10.0, 300.0, 80.0) is None


def test_paint_wave4_layout_guards():
    """右標最右短截、浪序只留圓圈、最底＋反彈切割、線停 gutter 前。"""
    import inspect

    from scripts import paint_focus_target_sample as m

    src = inspect.getsource(m.paint)
    tag_src = inspect.getsource(m._paint_right_price_tags)
    assert "LABEL_RIGHT_EXTRA" in src
    assert "LINE_END_PAD" in src
    assert "ZONE_NEAR_PAD" in src
    assert "FIB_NEAR_PAD" in src
    assert "REBOUND_NEAR_PAD" in src
    assert "TAG_COL_GAP" in tag_src or "TAG_COL_GAP" in inspect.getsource(m)
    assert "短截" in tag_src or "stub" in tag_src
    assert 'boxstyle="circle,pad=0.12"' in src
    assert "rebound_fib_from_wave_bottom" in src
    assert "最底" in src
    assert 'marker="D"' not in src
    # 圖內不准再貼「146 →」這類終點價
    assert 'f"{price:.0f} →"' not in src
    assert "起→③＝" not in src
    # 水平線；壓帶上下緣掛左側；浪圈貼近頂底
    assert "hlines" in src
    assert "壓上緣" in src
    assert "_x_zone_lab" in src
    assert "FIB_NEAR_PAD" in src
    assert "(0, 7)" in src
    # right_tags 不准塞壓上緣／壓下緣／收（收價改右上大字卡；壓帶標在左側）
    right_block = src[src.find("right_tags"):]
    right_block = right_block[: right_block.find("_paint_right_price_tags")]
    assert "壓上緣" not in right_block
    assert "壓下緣" not in right_block
    assert 'f"收 {close:.0f}"' not in right_block
    assert "末根K旁不再寫收價" in src
    assert "_x_left" in src
    # 右上預設 B；K／量比例鎖 3.4:1.25；中帶瘦雙格；黃柱標張數
    assert "較昨日" in src
    assert "HEADER_STYLES" in inspect.getsource(m)
    assert 'HEADER_STYLE_DEFAULT = "B"' in inspect.getsource(m)
    assert "1.0 - _band" in src
    assert '"今K"' in src
    assert "wave24_descend_line" in src
    assert "WAVE24_LINE_COLOR" in src
    assert "set_dashes" in src
    assert "height_ratios=[3.4, 0.95, 1.25]" in src
    assert "K 線／量圖塊比例鎖死" in src
    assert "_x_fund" in src and "_x_leg" in src
    assert 'set_ylabel("價（元）"' in src
    assert "毛利率" in src
    assert "長借／權益" in src
    assert "_mid_fs" in src
    assert "fontsize=_mid_fs" in src
    assert "refresh_latest_official_bars" in src
    assert "最近上漲日" in src
    assert "四浪高／" in src
    assert "還有{room:.1f}%" in src
    assert "距四浪高還有" not in src  # 已併進四浪高標，不准另掛漂浮盒
    assert "四浪低／" in src
    assert "未過＝偏沒力" in src
    assert "②–④已破" in src
    assert "今日未觸發新起漲" in src
    assert "反彈{ratio:g}／" in src
    assert "基本面盒改中帶左格" in src
    assert '"#bbf7d0"' not in src  # 不准大面積淺綠底蓋住K
    assert "1.16" not in src  # 今日量不准掛中帶壓基本面
    assert '"#ffeb3b"' in src
    assert "張" in src[src.find("壓力來源日量柱") :]


def test_rev_yi_thousand_to_yi():
    # 庫內千元 → 億（與介紹卡／100000 同）
    assert _rev_yi(24472758.0) == "244.73"
    assert _rev_yi(100000) == "1.00"


def test_right_tags_dodge_close_vs_zone_edge():
    # 近價用左中右錯開，不准整排同一直線
    ys, cols = _dodge_right_ys(
        [4565.0, 3920.0, 3690.0, 3660.0], y_lo=2500.0, y_hi=6500.0
    )
    assert len(ys) == 4
    assert len(cols) == 4
    assert set(cols) <= {0, 1, 2}
    assert cols[2] != cols[3]  # 3690／3660 不同欄
    assert len(set(cols[:3])) >= 2  # 高→低至少兩欄


def test_right_tags_near_price_tri_col_2449_style():
    # 反彈切割近價 → 左中右輪流，不准整排遠掛
    ys, cols = _dodge_right_ys(
        [232.0, 215.0, 199.0, 194.0, 146.0],
        y_lo=140.0,
        y_hi=280.0,
    )
    assert len(ys) == 5
    assert set(cols) <= {0, 1, 2}
    assert len(set(cols)) >= 3  # 五顆應用到三欄
    src = open("scripts/paint_focus_target_sample.py", encoding="utf-8").read()
    assert "TAG_NEAR_PAD" in src
    assert "TAG_COL_GAP" in src


def test_eps_singles_from_cumulative():
    singles, cum = _eps_singles_cum(
        [(2026, 1, 14.9), (2026, 2, 42.46), (2026, 3, 82.92)], 2026
    )
    assert abs(singles[1] - 14.9) < 1e-9
    assert abs(singles[2] - 27.56) < 1e-6
    assert abs(singles[3] - 40.46) < 1e-6
    assert abs(cum - 82.92) < 1e-9


def test_forward_zone_prefers_above_close():
    # 現價 100；區內大量 overlapping；真正上方次大量 low=110
    bars = []
    for i in range(40):
        ymd = f"202602{i + 1:02d}" if i < 28 else f"202603{i - 27:02d}"
        bars.append(
            {
                "date": ymd,
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    # 重疊區：量大但含現價
    bars[10] = {
        "date": "20260211",
        "open": 98.0,
        "high": 108.0,
        "low": 92.0,
        "close": 100.0,
        "volume": 9000.0,
    }
    # 前方區：下緣 > 收
    bars[20] = {
        "date": "20260221",
        "open": 112.0,
        "high": 120.0,
        "low": 110.0,
        "close": 115.0,
        "volume": 8000.0,
    }
    bars[-1]["close"] = 100.0
    bars[-1]["high"] = 102.0
    bars[-1]["low"] = 98.0
    z = pick_forward_pressure_zone(bars, close=100.0)
    assert z is not None
    assert z.get("zone_role") == "forward"
    assert float(z["low"]) > 100.0
    assert str(z.get("date")) == "20260221"
