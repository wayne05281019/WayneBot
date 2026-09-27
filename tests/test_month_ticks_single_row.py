# -*- coding: utf-8 -*-
"""月份標：能排下單排；只有會互壓的那顆下移。"""
from wayne_navigator import _set_staggered_month_ticks


def test_month_ticks_prefer_single_row_when_spaced(monkeypatch):
    """相鄰月距離夠＝全部同一排 y_near。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12.8, 2.0))
    ax.set_xlim(-0.8, 75)
    texts = []

    def capture_text(*args, **kwargs):
        texts.append((args, kwargs))
        return None

    monkeypatch.setattr(ax, "text", capture_text)
    months = ["6月'26", "7月'26", "8月'26", "9月'26"]
    mpos = [0, 22, 44, 66]
    _set_staggered_month_ticks(ax, months, mpos, compact=False)
    ys = [kw.get("y", args[1] if len(args) > 1 else None) for args, kw in texts]
    assert len(ys) == 4
    assert len(set(round(float(y), 5) for y in ys)) == 1
    plt.close(fig)


def test_month_ticks_only_crowded_label_drops():
    """只有互壓的那顆下移，其餘單排；不准整排無腦雙排。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12.8, 2.0))
    ax.set_xlim(-0.8, 180)
    texts = []

    def capture_text(*args, **kwargs):
        texts.append((args, kwargs))
        return None

    import wayne_navigator as wn

    orig = ax.text
    ax.text = capture_text  # type: ignore
    # 模擬 2330：12月與1月極近，其餘月距正常
    months = ["12月'25", "1月'26", "2月'26", "3月'26", "4月'26"]
    mpos = [0, 3, 24, 36, 58]
    _set_staggered_month_ticks(ax, months, mpos, compact=False)
    ys = [round(float(kw.get("y", args[1])), 5) for args, kw in texts]
    assert len(ys) == 5
    # 近排應佔多數；最多一顆因互壓下移
    near = ys[0]
    far_n = sum(1 for y in ys if y != near)
    assert far_n <= 1
    assert ys.count(near) >= 4
    plt.close(fig)


def test_month_ticks_stagger_when_cramped(monkeypatch):
    """全部擠在一起時才會有上下兩排。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.0, 2.0))
    ax.set_xlim(-0.5, 10)
    texts = []

    def capture_text(*args, **kwargs):
        texts.append((args, kwargs))
        return None

    monkeypatch.setattr(ax, "text", capture_text)
    months = ["6月'26", "7月'26", "8月'26", "9月'26"]
    mpos = [0, 0.6, 1.2, 1.8]
    _set_staggered_month_ticks(ax, months, mpos, compact=False)
    ys = [round(float(kw.get("y", args[1])), 5) for args, kw in texts]
    assert len(set(ys)) >= 2
    plt.close(fig)
