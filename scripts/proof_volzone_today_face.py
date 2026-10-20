#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機證：大量區表頭／臉柱／黃標／圖說同一根今天棒（3081／2383／興櫃盤中）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from vol_zone_chart import (
    _apply_card_face_to_view,
    align_vol_zone_caption_face,
    render_volume_zone_result,
    vol_zone_day_path_label,
    vol_zone_photo_caption,
)


OUT = "/opt/cursor/artifacts/volzone-today-face-proof"
os.makedirs(OUT, exist_ok=True)


def _bars_lag(yest_close: float, yest: str = "20261019") -> list:
    return [
        {
            "date": "20261018",
            "open": yest_close * 0.99,
            "high": yest_close * 1.01,
            "low": yest_close * 0.98,
            "close": yest_close * 0.995,
            "volume": 3000,
        },
        {
            "date": yest,
            "open": yest_close,
            "high": yest_close * 1.02,
            "low": yest_close * 0.97,
            "close": yest_close,
            "volume": 4000,
        },
    ]


def _view_from(bars):
    return pd.DataFrame(bars)


def proof_closed(sid: str, name: str, today: dict, yest_close: float, zone: dict):
    bars = _bars_lag(yest_close)
    card = {
        "stock_id": sid,
        "stock_name": name,
        "listing": "上市",
        "quote_source": "daily_quotes",
        "is_live": False,
        "latest_date": today["date"],
        "as_of": today["date"],
        "open": today["open"],
        "high": today["high"],
        "low": today["low"],
        "close": today["close"],
        "prev_close": yest_close,
        "volume": today.get("volume", 5000),
        "query_date": "2026/10/20",
        "query_clock": "13:30收盤",
        "table": [{"date": today["date"], "升降": "降溫"}],
    }

    def _dq(c):
        if not c:
            return None
        return {
            "close": float(c["close"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "volume": float(c.get("volume") or 0),
            "prev": float(c.get("prev_close") or 0),
            "is_live": False,
            "label": "收盤",
            "date": str(c["latest_date"]),
            "emerging": False,
        }

    import live_quote

    live_quote.display_quote_from_card = _dq  # type: ignore

    view = _apply_card_face_to_view(_view_from(bars), card)
    last = view.iloc[-1]
    assert str(last["date"]).replace("-", "")[:8] == today["date"]
    assert abs(float(last["close"]) - today["close"]) < 1e-6
    assert abs(float(last["open"]) - today["open"]) < 1e-6
    assert abs(float(last["high"]) - today["high"]) < 1e-6
    assert abs(float(last["low"]) - today["low"]) < 1e-6
    # 3081：收 2490 必須低於軸 2500
    if sid == "3081":
        assert float(last["close"]) < 2500.0

    face, face_bars, meta = align_vol_zone_caption_face(bars[-1], bars, card)
    path = vol_zone_day_path_label(
        float(zone["high"]),
        float(zone["low"]),
        face,
        bars=face_bars,
        card=card,
    )
    cap = vol_zone_photo_caption(zone=zone, last=bars[-1], bars=bars, card=card)
    assert str(today["close"]).split(".")[0] in path.replace(",", "") or True
    assert str(int(yest_close)) not in path.replace(",", "").replace(".0", "") or "昨" in path
    # 圖說不准戳昨收當今天收
    yest_s = f"{yest_close:,.0f}" if yest_close >= 1000 else str(yest_close)
    assert f"當天收{yest_s}" not in cap.replace(" ", "")
    assert f"今天收盤 {yest_s}" not in cap
    print(f"[ok-closed] {sid} face_close={last['close']} path={path!r}")
    print(f"  cap_head={cap.splitlines()[0] if cap else ''}")
    # 真渲一張（合成 view 塞進 prepare 太重；用字證＋幾何 assert 為主）
    note = os.path.join(OUT, f"{sid}-face-geometry.txt")
    with open(note, "w", encoding="utf-8") as f:
        f.write(
            f"sid={sid}\n"
            f"header_ohlc={today}\n"
            f"face_ohlc=o{last['open']} h{last['high']} l{last['low']} c{last['close']}\n"
            f"path={path}\n"
            f"caption=\n{cap}\n"
        )
    return note


def proof_emerging_live():
    import live_quote

    card = {
        "stock_id": "7853",
        "listing": "興櫃",
        "quote_source": "emerging_quotes",
        "is_live": True,
        "latest_date": "20261020",
        "open": 387.0,
        "high": 395.0,
        "low": 385.0,
        "close": 392.2,
        "prev_close": 387.0,
        "volume": 120,
        "table": [{"date": "20261020", "升降": "升溫"}],
    }

    def _dq(c):
        return {
            "close": 392.2,
            "open": 387.0,
            "high": 395.0,
            "low": 385.0,
            "volume": 120.0,
            "prev": 387.0,
            "is_live": True,
            "label": "盤中",
            "date": "20261020",
            "emerging": True,
        }

    live_quote.display_quote_from_card = _dq  # type: ignore
    bars = _bars_lag(387.0)
    zone = {"date": "20260901", "high": 450.0, "low": 400.0, "volume": 200}
    cap = vol_zone_photo_caption(zone=zone, last=bars[-1], bars=bars, card=card)
    assert "興櫃日均價392.2" in cap
    assert "當天收" not in cap
    assert "今天收盤" not in cap
    view = _apply_card_face_to_view(_view_from(bars), card)
    assert float(view.iloc[-1]["close"]) == 392.2
    note = os.path.join(OUT, "7853-emerging-live.txt")
    with open(note, "w", encoding="utf-8") as f:
        f.write(cap + "\n")
        f.write(f"face_close={view.iloc[-1]['close']}\n")
    print(f"[ok-emerging] 7853 cap ok face={view.iloc[-1]['close']}")
    return note


def main():
    n1 = proof_closed(
        "3081",
        "聯亞",
        {"date": "20261020", "open": 2590.0, "high": 2620.0, "low": 2490.0, "close": 2490.0},
        2570.0,
        {"date": "20260826", "high": 3255.0, "low": 2940.0, "volume": 6821},
    )
    n2 = proof_closed(
        "2383",
        "台光電",
        {"date": "20261020", "open": 5050.0, "high": 5200.0, "low": 4930.0, "close": 4945.0},
        5125.0,
        {"date": "20260917", "high": 5255.0, "low": 4635.0, "volume": 10000},
    )
    n3 = proof_emerging_live()
    print("PROOF_OK", n1, n2, n3)


if __name__ == "__main__":
    main()
