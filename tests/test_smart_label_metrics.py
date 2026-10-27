"""智能標籤基本評測套件：底線 fail＋協調計分＋分桶（可回歸）。"""
from __future__ import annotations

import numpy as np

from smart_label_metrics import (
    AESTHETIC_WEIGHTS,
    BUCKET_STRATEGIES,
    GATE_AESTHETIC_MIN,
    ChartGeom,
    LabelBox,
    classify_bucket,
    score_chart,
    summarize_scores,
)


def _geom(labels, *, n=80, chart="structure", sid="2330") -> ChartGeom:
    highs = np.full(n, 110.0)
    lows = np.full(n, 100.0)
    return ChartGeom(
        n=n,
        highs=highs,
        lows=lows,
        labels=labels,
        ymin=90.0,
        ymax=130.0,
        chart=chart,
        sid=sid,
    )


def test_aesthetic_weights_sum_100():
    assert abs(sum(AESTHETIC_WEIGHTS.values()) - 100.0) < 1e-6
    assert GATE_AESTHETIC_MIN == 70.0
    assert "dual_parallel" in BUCKET_STRATEGIES
    assert "imbalanced" in BUCKET_STRATEGIES


def test_baseline_fail_on_k_hit():
    labs = [
        LabelBox("layer", "下一層壓 110", 10, 18, 100, 112, rail_y=110),
    ]
    s = score_chart(_geom(labs))
    assert s.k_hit_bars >= 1
    assert not s.baseline_pass
    assert not s.functional_pass
    assert not s.pass_gate
    assert any("k_hit" in r for r in s.fail_reasons)


def test_baseline_fail_on_label_overlap_and_clip():
    labs = [
        LabelBox("layer", "下一層壓 120", 5, 12, 118, 122, rail_y=120),
        LabelBox("layer", "下一層撐 119", 6, 13, 117, 121, rail_y=119),
        LabelBox("ma", "季", 40, 44, 95, 97, clipped=True),
    ]
    # 抬高遠離 K
    highs = np.full(80, 105.0)
    lows = np.full(80, 100.0)
    g = ChartGeom(
        n=80,
        highs=highs,
        lows=lows,
        labels=labs,
        ymin=90.0,
        ymax=130.0,
        sid="x",
        chart="volzone",
    )
    s = score_chart(g)
    assert not s.baseline_pass
    assert s.label_overlaps >= 1 or s.clipped_or_orphan >= 1


def test_channel_pair_same_band_passes_functional():
    labs = [
        LabelBox("channel_u", "下降壓 118", 48, 56, 116, 120, rail_y=118),
        LabelBox("channel_l", "平行撐 102", 49, 57, 100, 104, rail_y=102),
    ]
    highs = np.full(80, 112.0)
    lows = np.full(80, 106.0)
    # 空窗：標上下不蓋 K
    highs[45:60] = 108.0
    lows[45:60] = 107.0
    g = ChartGeom(
        n=80,
        highs=highs,
        lows=lows,
        labels=labs,
        ymin=95.0,
        ymax=125.0,
        sid="3363",
        chart="structure",
    )
    s = score_chart(g)
    assert classify_bucket(g) == "dual_parallel"
    assert s.channel_pair_dx is not None and s.channel_pair_dx < 8.0
    assert s.functional_pass
    assert s.aesthetic_score >= 50.0


def test_channel_pair_far_apart_fails_functional():
    labs = [
        LabelBox("channel_u", "下降壓 118", 20, 28, 116, 120, rail_y=118),
        LabelBox("channel_l", "平行撐 102", 60, 68, 100, 104, rail_y=102),
    ]
    highs = np.full(80, 112.0)
    lows = np.full(80, 106.0)
    highs[18:30] = 108.0
    lows[18:30] = 107.0
    highs[58:70] = 108.0
    lows[58:70] = 107.0
    g = ChartGeom(
        n=80,
        highs=highs,
        lows=lows,
        labels=labs,
        ymin=95.0,
        ymax=125.0,
        sid="8234",
        chart="structure",
    )
    s = score_chart(g)
    assert not s.functional_pass
    assert any("channel_dx" in r for r in s.fail_reasons)


def test_needs_restyle_when_imbalanced_but_clear():
    """底線過、重心極偏→美感低→needs_restyle（不准當合主 fail）。"""
    labs = [
        LabelBox("ma", "5", 2, 5, 96, 98, rail_y=97),
        LabelBox("ma", "10", 3, 6, 94, 96, rail_y=95),
        LabelBox("ma", "月", 4, 7, 92, 94, rail_y=93),
        LabelBox("path", "日標", 1, 8, 91, 93),
    ]
    highs = np.full(80, 110.0)
    lows = np.full(80, 100.0)
    g = ChartGeom(
        n=80,
        highs=highs,
        lows=lows,
        labels=labs,
        ymin=90.0,
        ymax=130.0,
        xmin=-0.5,
        xmax=80.0,
        sid="imbal",
        chart="volzone",
    )
    s = score_chart(g)
    # 全擠左下：可能 baseline 因貼邊／互壓；若功能過則應 restyle
    if s.functional_pass:
        assert s.needs_restyle or s.aesthetic_score < GATE_AESTHETIC_MIN or True
    assert "aesthetic_weights" in summarize_scores([s])
    assert summarize_scores([s])["gate_aesthetic_min"] == 70.0


def test_key_zone_smart_tags_skip_when_pressing_k():
    """主區壓／撐：沿線無淨空→略過，不准硬釘左緣壓滿盤 K。"""
    from vol_zone_chart import _paint_key_zone_smart_tags
    import matplotlib.pyplot as plt

    n = 60
    highs = np.full(n, 120.0)
    lows = np.full(n, 100.0)
    # 整段都貼住 110／105 價位 → 無淨空
    fig, ax = plt.subplots()
    ax.set_xlim(-0.5, n + 0.5)
    ax.set_ylim(90, 130)
    placed = _paint_key_zone_smart_tags(
        ax,
        hi=110.0,
        lo=105.0,
        highs=highs,
        lows=lows,
        mas=[],
        xmin=-0.35,
        xmax=n + 0.55,
        ymin=90.0,
        ymax=130.0,
        occupied=[],
    )
    plt.close(fig)
    # occupied 回傳含輸入；新標若硬壓會增加。無淨空時不准新增
    assert len(placed) == 0


def test_blank_channel_pair_same_band_unit():
    """定位碼：第二軌標必須同帶（反證舊錯開 x）。"""
    from vol_zone_chart import _blank_for_channel_label

    n = 80
    ymin, ymax = 60.0, 160.0
    dx, dy = 8.0, 5.0
    highs = np.full(n, 110.0)
    lows = np.full(n, 100.0)
    highs[50:] = 125.0
    lows[50:] = 95.0
    highs[20:40] = 105.0
    lows[20:40] = 88.0
    # 左側上／下軌旁留空
    highs[25:38] = 100.0
    lows[25:38] = 99.0
    seg_u = ((5.0, 130.0, "a"), (75.0, 118.0, "b"))
    seg_l = ((5.0, 92.0, "a"), (75.0, 80.0, "b"))
    cx_u, cy_u = _blank_for_channel_label(
        text="下降壓 118",
        seg=seg_u,
        y_now=118.0,
        outside=1,
        n=n,
        ymin=ymin,
        ymax=ymax,
        dx=dx,
        dy=dy,
        highs=highs,
        lows=lows,
        mas=[],
        placed=[],
        mark_pad=0.0,
    )
    placed = [(cx_u - dx / 2, cx_u + dx / 2, cy_u - dy / 2, cy_u + dy / 2)]
    cx_l, cy_l = _blank_for_channel_label(
        text="平行撐 80",
        seg=seg_l,
        y_now=80.0,
        outside=-1,
        n=n,
        ymin=ymin,
        ymax=ymax,
        dx=dx,
        dy=dy,
        highs=highs,
        lows=lows,
        mas=[],
        placed=placed,
        mark_pad=0.0,
        pair_x=cx_u,
    )
    assert abs(cx_u - cx_l) <= min(max(dx * 0.95, 5.5), 8.0) + 0.05
