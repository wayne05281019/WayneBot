"""結構圖全面替換：所有出圖入口只准走 biaoke_chart.render_biaoke_structure_png。"""
from __future__ import annotations

import inspect


def test_all_structure_entries_use_biaoke_chart_renderer():
    """查股第三張／飆大／三合一內嵌結構，一律同一套 render_biaoke_structure_png。"""
    from biaoke_chart import build_biaoke_structure_chart, render_biaoke_structure_png
    from bot_servers import WayneTelegramBot
    from three_in_one_chart import render_lookup_structure_result

    rsrc = inspect.getsource(render_biaoke_structure_png)
    assert "hdr-band-v73" in rsrc
    assert "status_row" in rsrc
    assert "status_h_gap" in rsrc
    assert "neighbor" in inspect.getsource(
        __import__("biaoke_chart", fromlist=["_place_right_notes"])._place_right_notes
    )
    assert "不准畫「連點延長」" in rsrc or "不准畫" in rsrc

    lookup = inspect.getsource(render_lookup_structure_result)
    assert "render_biaoke_structure_png" in lookup
    assert "_STRUCTURE_LOOKUP_FIG" in lookup

    build = inspect.getsource(build_biaoke_structure_chart)
    assert "render_biaoke_structure_png" in build
    assert "_STRUCTURE_LOOKUP_FIG" in build

    send = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "render_lookup_structure_result" in send

    biaoke_send = inspect.getsource(WayneTelegramBot._send_biaoke_structure_chart)
    assert "build_biaoke_structure_chart" in biaoke_send

    advice = inspect.getsource(WayneTelegramBot._render_biaoke_advice_chart)
    assert "build_biaoke_structure_chart" in advice

    # 三合一內嵌結構也要同一核准 figsize（不准殘留預設直式／舊比例）
    import three_in_one_chart as tio

    compose = inspect.getsource(tio._apply_patches_and_render)
    assert "render_biaoke_structure_png" in compose
    assert "_STRUCTURE_LOOKUP_FIG" in compose

    # 不准另開第二套結構圖渲染器
    import biaoke_chart as bc

    assert hasattr(bc, "render_biaoke_structure_png")
    assert not hasattr(tio, "render_structure_png")
    assert "def render_biaoke_structure" not in open(
        "three_in_one_chart.py", encoding="utf-8"
    ).read()
    # 75／76：昨收去重用文案真價，不准錨點誤刪
    assert "_note_true_price" in inspect.getsource(bc._dedupe_right_notes) or hasattr(
        bc, "_note_true_price"
    )
