# -*- coding: utf-8 -*-
"""查股高低卡要畫已結算昨淨值；庫空時補抓 e添富／櫃買。"""
from __future__ import annotations

import os

import pytest

from tests.card_face_audit import card_issues


SHOW = ["00631L", "0050", "00878", "00632R", "006201", "00858"]


@pytest.mark.production_db
def test_highlow_cards_show_settled_nav(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from tests.conftest import require_production_db
    from official_snapshots import refresh_one_etf_nav
    from wayne_navigator import NavigatorEngine, etf_nav_line_bits, render_decision_card_png

    db = require_production_db()
    os.makedirs("/opt/cursor/artifacts", exist_ok=True)
    eng = NavigatorEngine(db)
    orig = matplotlib.axes.Axes.text
    bag: list[str] = []

    def wrap(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        bag.append(s)
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    failed = []
    for sid in SHOW:
        n = refresh_one_etf_nav(sid, db)
        card = eng.get_decision_card(sid, lookback=20)
        if card.get("error"):
            failed.append(f"{sid} 建卡失敗 {card.get('error')}")
            continue
        if not card.get("etf_nav"):
            failed.append(f"{sid} 沒有昨淨值 n={n}")
            continue
        bits = etf_nav_line_bits(card)
        if not bits or not any("淨值" in x for x in bits):
            failed.append(f"{sid} 左欄沒有淨值 bits={bits}")
        if card.get("is_live") and bits and "昨淨值" not in bits[0]:
            failed.append(f"{sid} 盤中沒標昨淨值 {bits}")
        bag.clear()
        path = f"/opt/cursor/artifacts/{sid}-nav-face.png"
        assert render_decision_card_png(card, path)
        issues = card_issues(card, list(bag))
        if issues:
            failed.append(f"{sid}: " + "；".join(issues))
        blob = "\n".join(bag)
        if "昨淨值" not in blob and "淨值" not in blob:
            failed.append(f"{sid} 圖上沒有淨值字")
    assert not failed, "\n".join(failed)


def test_etfortune_follows_307(monkeypatch):
    """證交所 POST 若回 307，要帶原 body 跟到 Location，不能直接放棄。"""
    import io
    from urllib.error import HTTPError

    import official_snapshots as osnap

    calls = []

    class FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=20):
        calls.append((req.full_url, req.data, req.get_method()))
        if len(calls) == 1:
            raise HTTPError(
                req.full_url,
                307,
                "Temporary Redirect",
                hdrs={"Location": "https://www.twse.com.tw/rwd/zh/ETFortune/ajaxEtfInfoChart"},
                fp=io.BytesIO(b""),
            )
        return FakeResp(b'{"netPrice":[{"date":"2026/09/10","count":100.5}]}')

    monkeypatch.setattr(osnap, "urlopen", fake_urlopen)
    monkeypatch.setattr(osnap, "_today_ymd", lambda: "20260911")
    payload = osnap.fetch_etfortune_nav_payload("0050")
    assert payload.get("netPrice")
    assert len(calls) == 2
    assert calls[0][2] == "POST" and calls[1][2] == "POST"
    assert calls[0][1] == calls[1][1]
    assert "rwd" in calls[1][0]


def test_collect_falls_back_to_mis():
    """e添富／櫃買都空時，改吃 MIS 前一營業日淨值。"""
    import official_snapshots as osnap

    rows = osnap._collect_one_etf_nav(
        "00631L",
        fetch_twse=lambda sid: {},
        fetch_tpex=lambda sid: {},
        fetch_mis=lambda: {
            "a1": [
                {
                    "msgArray": [
                        {"a": "00631L", "h": "36.00", "i": "20260911"},
                        {"a": "0050", "h": "107.49", "i": "20260911"},
                    ]
                }
            ]
        },
    )
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "00631L"
    assert rows[0]["nav"] == 36.0
    assert rows[0]["source"] == "twse_mis_prev_nav"
