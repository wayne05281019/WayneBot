# -*- coding: utf-8 -*-
"""次級四浪分級：EPS／股性桶。"""
from __future__ import annotations

from unittest.mock import patch

from focus_wave4_desk import (
    PAGE_SIZE,
    Wave4Row,
    _assign_bucket,
    _chip_label,
    apply_live_close,
    format_wave4_desk_html,
    format_wave4_hub_html,
    format_wave4_one_html,
    format_wave4_page_html,
    intervene_page,
    overlay_live_on_rows,
)


def test_chip_label_foreign_dominant():
    assert _chip_label(5000, 100, -50, chip_asof="20261103").startswith("外資")


def test_chip_label_missing_not_fake_retail():
    assert _chip_label(0, 0, 0) == "籌碼未齊"


def test_assign_intervene_needs_eps_and_chain():
    row = Wave4Row(
        stock_id="2383",
        stock_name="台光電",
        market="TW",
        close=3660,
        room_to_w4_pct=24.7,
        bottom_near_year_ago_bars=3,
        score=120,
        eps_last=15.0,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "intervene"
    assert "實質" in why or "AI" in why


def test_quality_below_w4_low_still_intervene():
    """台光電型：未過四浪低也不排除。"""
    row = Wave4Row(
        stock_id="2383",
        stock_name="台光電",
        market="TW",
        close=3660,
        wave3_low=3690,
        wave4=4565,
        room_to_w4_pct=24.7,
        above_w4_low=False,
        bottom_near_year_ago_bars=3,
        score=120,
        eps_last=15.0,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "intervene"
    assert "不准排除" in why or "8000" in why


def test_passive_is_rebound_sprint():
    """被動元件＝搶反彈短衝，不當成長線值得介入。"""
    row = Wave4Row(
        stock_id="2327",
        stock_name="國巨",
        market="TW",
        close=800,
        room_to_w4_pct=30.0,
        above_w4_low=True,
        bottom_near_year_ago_bars=1,
        score=90,
        eps_last=14.0,
        eps_profit=True,
        taught_tags=["被動元件"],
        industry_chain="電子上游-被動元件",
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "sprint"
    assert "搶反彈" in why


def test_passive_past_w4_still_sprint_not_intervene():
    """被動元件已過四浪高仍搶反彈臉，不准進值得介入。"""
    row = Wave4Row(
        stock_id="2327",
        stock_name="國巨",
        market="TW",
        close=1200,
        room_to_w4_pct=-5.0,
        above_w4_low=True,
        bottom_near_year_ago_bars=1,
        score=90,
        eps_last=14.0,
        eps_profit=True,
        taught_tags=["被動元件"],
        industry_chain="電子上游-被動元件",
        chip_label="外資偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "sprint"
    assert "intervene" != bucket
    assert "搶反彈" in why


def test_assign_sprint_when_no_eps():
    row = Wave4Row(
        stock_id="9999",
        stock_name="dummy",
        market="TW",
        close=10,
        room_to_w4_pct=30,
        bottom_near_year_ago_bars=0,
        score=80,
        eps_last=-1.0,
        eps_profit=False,
        taught_tags=[],
        chip_label="偏散戶／雜訊",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "sprint"
    assert "短衝" in why


def test_format_html_has_buckets():
    html = format_wave4_desk_html(
        {
            "ok": True,
            "asof": "20261126",
            "n_hits": 2,
            "n_intervene": 1,
            "n_sprint": 1,
            "n_watch": 0,
            "intervene": [
                {
                    "stock_id": "2383",
                    "stock_name": "台光電",
                    "room_to_w4_pct": 24.7,
                    "chip_label": "外資偏愛",
                    "eps_last": 15.0,
                    "taught_tags": ["PCB"],
                }
            ],
            "sprint": [
                {
                    "stock_id": "1111",
                    "stock_name": "dummy",
                    "room_to_w4_pct": 40.0,
                    "chip_label": "偏散戶／雜訊",
                    "eps_last": None,
                    "taught_tags": [],
                }
            ],
        }
    )
    assert "次級四浪" in html
    assert "值得介入" in html
    assert "短衝" in html
    assert "非買訊" in html
    assert "四浪高" in html
    assert "搶反彈" in html or "被動元件" in html


def test_hub_two_paths():
    html = format_wave4_hub_html()
    assert "打代號" in html
    assert "實質十檔" in html
    assert "結構圖" in html
    assert "現價" in html
    assert "非買訊" in html


def test_paint_wave4_page_charts_skips_empty(tmp_path):
    from focus_wave4_desk import paint_wave4_page_charts

    assert paint_wave4_page_charts([], out_dir=tmp_path, db_path=tmp_path) == []


def test_paint_wave4_chart_uses_mpl_paint_worker():
    """不准自開 ThreadPool 踩 matplotlib；必須走 run_mpl_paint。"""
    import inspect

    import focus_wave4_desk as m

    src = inspect.getsource(m.paint_wave4_chart)
    assert "run_mpl_paint" in src
    page_src = inspect.getsource(m.paint_wave4_page_charts)
    assert "ThreadPoolExecutor" not in page_src
    pair_src = inspect.getsource(m.paint_wave4_one_pair)
    assert "run_mpl_paint" in pair_src
    assert "render_lookup_structure_result" in pair_src
    assert "wave4" in pair_src and "struct" in pair_src
    assert "force_vol_zone" in pair_src
    assert 'meta.get("zone")' in pair_src or 'meta or {}).get("zone")' in pair_src
    assert "face_asof" in pair_src


def test_force_vol_zone_skips_next_layer_attach():
    """次級四浪強制路上區時，結構圖不准再掛舊爆大量下一層灰帶。"""
    import inspect

    from biaoke_chart import render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    assert "force_vol_zone" in src
    assert 'info["next_support"] = {}' in src
    assert "if sid and not force_vol_zone:" in src


def test_wave4_hub_mentions_two_charts():
    from focus_wave4_desk import format_wave4_hub_html

    html = format_wave4_hub_html()
    assert "一次兩張" in html
    assert "結構圖" in html
    assert "同路上大量區" in html


def test_wave4_send_media_group_single_uses_reply_photo():
    """單張不准 reply_media_group（Telegram 硬要 2–10）。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._wave4_send_media_group)
    assert "len(send_paths) == 1" in src
    assert "reply_photo" in src


def test_wave4_send_one_uses_pair_two_charts():
    """單檔呼叫＝次級四浪圖＋結構圖一次送。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._wave4_send_one)
    assert "paint_wave4_one_pair" in src
    assert "次級四浪圖＋結構圖" in src


def test_wave4_send_page_list_first_then_wave4_not_struct():
    """實質十檔：先名單再逐張次級四浪圖；文案不准再叫結構圖。"""
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._wave4_send_page)
    assert "先推名單再逐張出圖" in src
    assert "paint_wave4_chart" in src
    assert "不是結構圖" in src
    assert "頁結構圖" not in src
    assert "這頁次級四浪圖沒送出" in src
    assert "重試一次" in src
    assert "兩次都畫不出" in src
    one_src = inspect.getsource(WayneTelegramBot._wave4_send_one)
    assert "正在重試一次" in one_src
    assert "兩次都沒送出" in one_src


def test_guangsheng_horizon_sid_is_6442_not_1815():
    """資料正確性：光聖＝6442；1815是富喬，不准掛錯遠距。"""
    from focus_wave4_desk import QUALITY_HORIZON_ZH

    assert "6442" in QUALITY_HORIZON_ZH
    assert "光聖" in QUALITY_HORIZON_ZH["6442"]
    assert "1815" not in QUALITY_HORIZON_ZH


def test_intervene_page_ten_and_live_room():
    payload = {
        "asof": "20261126",
        "n_intervene": 12,
        "intervene": [
            {
                "stock_id": f"{i:04d}",
                "stock_name": f"n{i}",
                "room_to_w4_pct": 20.0,
                "wave4": 120.0,
                "wave3_low": 90.0,
                "close": 100.0,
                "eps_last": 1.0,
                "eps_profit": True,
                "taught_tags": ["PCB"],
                "above_w4_low": True,
                "bucket": "intervene",
                "why_zh": "舊收盤文案",
                "chip_label": "外資偏愛",
            }
            for i in range(12)
        ],
    }
    rows, pages, has_next = intervene_page(payload, 0)
    assert len(rows) == 10
    assert pages == 2
    assert has_next
    page_html = format_wave4_page_html(payload, rows, page=0, pages=2, live=True)
    assert "實質十檔" in page_html
    assert "現價" in page_html
    assert "次級四浪圖" in page_html
    assert "不是結構圖" in page_html
    assert "結構圖接著送" not in page_html
    live = apply_live_close(rows[0], 110.0)
    assert live["live_px"] is True
    assert abs(live["room_to_w4_pct"] - (120 - 110) / 110 * 100) < 0.05
    one = format_wave4_one_html(live, live=True)
    assert "四浪高" in one and "非買訊" in one


def test_live_past_w4_refreshes_bucket_not_stale_intervene():
    """條件錯回歸：現價已過四浪高，不准還掛收盤時的值得介入舊文案。"""
    row = {
        "stock_id": "2383",
        "stock_name": "台光電",
        "market": "TW",
        "close": 3660.0,
        "wave4": 4565.0,
        "wave3_low": 3690.0,
        "room_to_w4_pct": 24.7,
        "above_w4_low": False,
        "bottom_near_year_ago_bars": 3,
        "score": 120,
        "eps_last": 15.0,
        "eps_profit": True,
        "taught_tags": ["PCB"],
        "chip_label": "外資偏愛",
        "bucket": "intervene",
        "why_zh": "舊收盤→實質＋鏈",
    }
    live = apply_live_close(row, 5000.0)
    assert live["room_to_w4_pct"] < 0
    assert live["above_w4_low"] is True
    assert live["bucket"] != "intervene"
    assert "已過四浪" in (live.get("why_zh") or "") or live["bucket"] == "watch"
    html = format_wave4_one_html(live, live=True)
    assert "已過／觸及次級四浪高" in html or "已過四浪高" in html
    assert "值得介入" not in html.split("分級：")[-1].split("｜")[0]


def test_passive_industry_chain_never_intervene_even_past_h4():
    """被動元件（taught 或 industry）→ sprint 搶反彈，永不 intervene。"""
    by_tag = Wave4Row(
        stock_id="2327",
        stock_name="國巨",
        market="TW",
        close=500,
        wave4=442,
        wave3_low=364,
        room_to_w4_pct=-12.0,
        above_w4_low=True,
        bottom_near_year_ago_bars=2,
        score=100,
        eps_last=14.0,
        eps_profit=True,
        taught_tags=["被動元件"],
        chip_label="外資偏愛",
    )
    by_chain = Wave4Row(
        stock_id="9991",
        stock_name="被動樣",
        market="TW",
        close=100,
        wave4=130,
        wave3_low=90,
        room_to_w4_pct=25.0,
        above_w4_low=True,
        bottom_near_year_ago_bars=2,
        score=100,
        eps_last=5.0,
        eps_profit=True,
        taught_tags=["PCB"],
        industry_chain="電子上游-被動元件-MLCC",
        chip_label="外資偏愛",
    )
    for row in (by_tag, by_chain):
        bucket, why = _assign_bucket(row)
        assert bucket == "sprint"
        assert bucket != "intervene"
        assert "搶反彈" in why


def test_quality_6442_below_l3_still_intervene():
    """光聖＝6442：未過四浪低＋EPS＋鏈仍可 intervene，不准排除。"""
    row = Wave4Row(
        stock_id="6442",
        stock_name="光聖",
        market="TW",
        close=100,
        wave4=130,
        wave3_low=110,
        room_to_w4_pct=30.0,
        above_w4_low=False,
        bottom_near_year_ago_bars=1,
        score=90,
        eps_last=3.4,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="投信偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert bucket == "intervene"
    assert "不准排除" in why or "2500" in why


def test_past_h4_why_not_also_below_l3():
    """已過四浪高時 why 不准再疊未過四浪低（倒置波會自相矛盾）。"""
    row = Wave4Row(
        stock_id="6442",
        stock_name="光聖",
        market="TW",
        close=107.5,
        wave4=102.0,
        wave3_low=110.0,
        room_to_w4_pct=-5.12,
        above_w4_low=False,
        score=40,
        eps_last=3.4,
        eps_profit=True,
        taught_tags=["PCB"],
        chip_label="投信偏愛",
    )
    bucket, why = _assign_bucket(row)
    assert "已過四浪高" in why
    assert "未過四浪低" not in why
    assert bucket != "intervene"


def test_page_size_ten_only_from_intervene():
    """實質十檔只吃 intervene；PAGE_SIZE=10；n>10 第1頁有下一頁。"""
    assert PAGE_SIZE == 10
    payload = {
        "asof": "20261126",
        "n_intervene": 11,
        "intervene": [
            {"stock_id": f"I{i:03d}", "bucket": "intervene", "room_to_w4_pct": 20}
            for i in range(11)
        ],
        "sprint": [
            {"stock_id": "S001", "bucket": "sprint", "room_to_w4_pct": 30}
        ],
        "watch": [
            {"stock_id": "W001", "bucket": "watch", "room_to_w4_pct": 10}
        ],
    }
    rows, pages, has_next = intervene_page(payload, 0)
    assert len(rows) == PAGE_SIZE == 10
    assert pages == 2
    assert has_next is True
    assert all(str(r["stock_id"]).startswith("I") for r in rows)
    assert {r["stock_id"] for r in rows}.isdisjoint({"S001", "W001"})


def test_overlay_live_failure_keeps_close_face():
    """現價失敗／窗外：保留收盤臉，不崩潰、不寫假價。"""
    rows = [
        {
            "stock_id": "2383",
            "stock_name": "台光電",
            "market": "TW",
            "close": 3660.0,
            "wave4": 4565.0,
            "wave3_low": 3690.0,
            "room_to_w4_pct": 24.7,
            "above_w4_low": False,
            "eps_last": 15.0,
            "eps_profit": True,
            "taught_tags": ["PCB"],
            "chip_label": "外資偏愛",
            "bucket": "intervene",
        }
    ]
    # 非合併窗 → 收盤臉
    with patch("live_quote.is_live_merge_window", return_value=False):
        out, any_live = overlay_live_on_rows(rows, "/tmp/no.db")
    assert any_live is False
    assert out[0]["close"] == 3660.0
    assert not out[0].get("live_px")

    # 合併窗但抓價失敗 → 仍收盤臉
    with patch("live_quote.is_live_merge_window", return_value=True), patch(
        "live_quote.fetch_lookup_quote", side_effect=RuntimeError("boom")
    ):
        out2, any_live2 = overlay_live_on_rows(rows, "/tmp/no.db")
    assert any_live2 is False
    assert out2[0]["close"] == 3660.0
    assert not out2[0].get("live_px")

    # 回 0 價＝失敗，不准當現價
    with patch("live_quote.is_live_merge_window", return_value=True), patch(
        "live_quote.fetch_lookup_quote", return_value={"close": 0}
    ):
        out3, any_live3 = overlay_live_on_rows(rows, "/tmp/no.db")
    assert any_live3 is False
    assert out3[0]["close"] == 3660.0


def test_scan_hit_fields_present_when_mocked():
    """scan hits 進 desk 必須帶 wave3_low／wave4／above_w4_low／score。"""
    from focus_wave4_desk import enrich_hits

    hits = [
        {
            "stock_id": "2383",
            "stock_name": "台光電",
            "market": "TW",
            "close": 3660.0,
            "wave4": 4565.0,
            "wave3_low": 3690.0,
            "room_to_w4_pct": 24.7,
            "above_w4_low": False,
            "bottom_near_year_ago_bars": 3,
            "score": 124.63,
        }
    ]
    with patch("focus_wave4_desk._eps_last", return_value=(15.0, True)), patch(
        "focus_wave4_desk._chip_sums", return_value=(100.0, 50.0, 0.0, "20261103")
    ), patch("focus_wave4_desk._industry", return_value="PCB"), patch(
        "focus_wave4_desk._taught_ai_sids", return_value={"2383": ["PCB"]}
    ), patch("focus_wave4_desk.sqlite3.connect") as con_m:
        con_m.return_value.__enter__ = lambda s: s
        con_m.return_value.execute = lambda *a, **k: None
        # enrich_hits uses connect().execute via helpers we patched; still needs close
        mock_con = con_m.return_value
        mock_con.close = lambda: None
        rows = enrich_hits(hits, db_path="/tmp/x.db")
    assert len(rows) == 1
    r = rows[0]
    assert r.wave4 == 4565.0
    assert r.wave3_low == 3690.0
    assert r.above_w4_low is False
    assert r.score == 124.63
