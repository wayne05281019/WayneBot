# -*- coding: utf-8 -*-
"""抽查 50 檔高低卡：上欄標籤、數字、扣抵、徽章不能互打。"""
from __future__ import annotations

import os
import tempfile

import pytest

MUST = [
    "00631L", "0050", "00632R", "00663L", "00878", "00919",
    "2330", "6770", "2454", "2317", "2412", "2881", "2303", "2308", "3711",
    "2382", "3008", "3037", "3231", "3661", "3035", "2379", "2395", "2002",
    "1301", "1303", "1216", "1326", "2603", "2615", "2609", "2882", "2884",
    "2886", "2891", "1101", "1102", "1476", "1590", "2207", "2345", "2408",
    "2474", "2912", "3045", "3481", "4938", "5871", "6415", "8454",
]


def _approx(a, b, tol=0.16) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _issues(card: dict, texts: list[str]) -> list[str]:
    sid = str(card.get("stock_id") or "")
    out = []
    badges = [str(b) for b in (card.get("badges") or [])]
    if "多頭格局" in badges and "月K已走空" in badges:
        out.append("徽章互打：多頭格局＋月K已走空")
    live = bool(card.get("is_live"))
    blob = "\n".join(texts)
    if live:
        if "現價" not in texts:
            out.append("盤中沒有標現價")
        if "收盤" in texts:
            out.append("盤中大字還寫收盤")
        if "13:30收盤" in blob and "現價" in texts:
            out.append("盤中時鐘寫13:30收盤")
    else:
        if "現價" in texts:
            out.append("收盤後還寫現價")
    if "今開" not in blob:
        out.append("沒有今開")
    if "昨收" not in blob:
        out.append("沒有昨收")
    if "今K" not in texts:
        out.append("沒有今K")
    if float(card.get("prev_close") or 0) and "較昨" not in blob:
        out.append("有昨收但漲跌沒寫較昨")
    kotei = str(card.get("kotei_note") or "")
    if "還有再" in kotei or "還有再" in blob:
        out.append("扣抵寫成還有再")
    try:
        gain = float(card.get("gain_pct") if card.get("gain_pct") is not None else card.get("dist_l60") or 0)
    except (TypeError, ValueError):
        gain = 0.0
    if gain >= 12 and "打底" in kotei:
        out.append(f"獲利 {gain}% 還寫等多久打底")
    close = float(card.get("close") or 0)
    for lab, px, dist in (
        ("h10", card.get("h10"), card.get("dist_h10")),
        ("h20", card.get("h20"), card.get("dist_h20")),
        ("h60", card.get("h60"), card.get("dist_h60")),
    ):
        if px and close and dist is not None:
            want = round((close - float(px)) / close * 100.0, 1)
            if not _approx(dist, want):
                out.append(f"{lab} 距高 {dist} ≠ {want}")
    for lab, px, dist in (
        ("l10", card.get("l10"), card.get("dist_l10")),
        ("l20", card.get("l20"), card.get("dist_l20")),
        ("l60", card.get("l60"), card.get("dist_l60")),
    ):
        if px and dist is not None:
            want = round((close - float(px)) / float(px) * 100.0, 1) if px else 0.0
            if not _approx(dist, want):
                out.append(f"{lab} 距低 {dist} ≠ {want}")
    h60, l60, sp = card.get("h60"), card.get("l60"), card.get("space_60")
    if h60 and l60 and sp is not None:
        want = int(round((float(h60) - float(l60)) / float(l60) * 100.0))
        if abs(int(sp) - want) > 1:
            out.append(f"季空間 {sp} ≠ {want}")
    if card.get("etf_nav") is not None:
        if live and "昨淨值" not in blob:
            out.append("ETF 盤中沒標昨淨值")
        if "折溢價" in blob:
            out.append("還在用含糊的折溢價，沒分折價／溢價")
        nav = float(card["etf_nav"])
        prem = card.get("etf_premium")
        if prem is not None and nav:
            want = (close - nav) / nav * 100.0
            if not _approx(prem, want, 0.08):
                out.append(f"折溢價 {prem} ≠ {want:.2f}")
    tbl = card.get("table")
    if tbl is not None and hasattr(tbl, "iloc") and len(tbl):
        row0 = tbl.iloc[0]
        try:
            if abs(float(row0["close"]) - close) > 0.02:
                out.append("表第一列股價跟大字不一致")
        except (TypeError, ValueError, KeyError):
            pass
    if sid:
        pass
    return out


def _sample(db: str) -> list[str]:
    import sqlite3

    have = []
    con = sqlite3.connect(db)
    try:
        for sid in MUST:
            n = con.execute(
                "SELECT COUNT(*) FROM daily_quotes WHERE stock_id=?", (sid,)
            ).fetchone()[0]
            if n >= 60:
                have.append(sid)
        if len(have) < 50:
            rows = con.execute(
                """
                SELECT stock_id, COUNT(*) n FROM daily_quotes
                GROUP BY stock_id HAVING n >= 80
                ORDER BY n DESC LIMIT 80
                """
            ).fetchall()
            for sid, _n in rows:
                if sid not in have:
                    have.append(str(sid))
                if len(have) >= 50:
                    break
    finally:
        con.close()
    return have[:50]


@pytest.mark.production_db
def test_fifty_highlow_cards_face_invariants(tmp_path, monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.axes

    from tests.conftest import require_production_db
    from wayne_navigator import NavigatorEngine, render_decision_card_png

    db = require_production_db()
    sids = _sample(db)
    assert len(sids) >= 50, f"庫裡不夠 50 檔，只有 {len(sids)}"
    eng = NavigatorEngine(db)
    orig = matplotlib.axes.Axes.text
    bag: list[str] = []

    def wrap(self, *args, **kwargs):
        s = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        bag.append(s)
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    report = []
    failed = []
    for sid in sids:
        card = eng.get_decision_card(sid, lookback=20)
        if card.get("error"):
            failed.append(f"{sid} 建卡失敗 {card.get('error')}")
            continue
        bag.clear()
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            assert render_decision_card_png(card, path)
            issues = _issues(card, list(bag))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        line = f"{sid} {card.get('stock_name')} live={card.get('is_live')} close={card.get('close')} badges={card.get('badges')}"
        if issues:
            failed.append(f"{sid}: " + "；".join(issues))
            report.append("FAIL " + line + " | " + "；".join(issues))
        else:
            report.append("OK   " + line)
    os.makedirs("/opt/cursor/artifacts", exist_ok=True)
    with open("/opt/cursor/artifacts/card_face_audit50.log", "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
        if failed:
            f.write("\nFAILED\n" + "\n".join(failed) + "\n")
    assert not failed, "\n".join(failed[:12])
