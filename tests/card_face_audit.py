# -*- coding: utf-8 -*-
"""高低卡抽測共用：標籤、數字、國字敘述。"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from wayne_navigator import _fmt_price, session_price_label

MUST = [
    "00631L", "0050", "00632R", "00663L", "00878", "00919",
    "2330", "6770", "2454", "2317", "2412", "2881", "2303", "2308", "3711",
    "2382", "3008", "3037", "3231", "3661", "3035", "2379", "2395", "2002",
    "1301", "1303", "1216", "1326", "2603", "2615", "2609", "2882", "2884",
    "2886", "2891", "1101", "1102", "1476", "1590", "2207", "2345", "2408",
    "2474", "2912", "3045", "3481", "4938", "5871", "6415", "8454",
    "5483", "6488", "8299", "3529", "4966", "5274", "5347", "3105",
    "1260", "3595", "6613", "6727", "4771",
]


def _approx(a, b, tol=0.16) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _band(close: float) -> str:
    try:
        c = float(close)
    except (TypeError, ValueError):
        return "mid"
    if c < 30:
        return "lo"
    if c < 200:
        return "mid"
    return "hi"


def sample_universe(db: str, n: int = 1000) -> list[dict]:
    """上市／上櫃／興櫃 × 低中高價，湊滿 n 檔。先放 MUST。"""
    con = sqlite3.connect(db)
    rows: list[tuple] = []
    try:
        last = con.execute("SELECT MAX(date) FROM daily_quotes").fetchone()[0]
        em_last = con.execute("SELECT MAX(date) FROM emerging_quotes").fetchone()[0]
        rows.extend(
            con.execute(
                """
                SELECT u.stock_id, u.stock_name, u.market_type, q.close
                FROM stock_universe u
                JOIN daily_quotes q ON q.stock_id=u.stock_id AND q.date=?
                WHERE u.market_type IN ('TW','TWO') AND q.close>0
                """,
                (last,),
            ).fetchall()
        )
        rows.extend(
            con.execute(
                """
                SELECT u.stock_id, u.stock_name, 'EM', e.close
                FROM stock_universe u
                JOIN emerging_quotes e ON e.stock_id=u.stock_id AND e.date=?
                WHERE u.market_type='EM' AND e.close>0
                """,
                (em_last,),
            ).fetchall()
        )
    finally:
        con.close()
    by_key: dict[tuple, list] = {}
    seen = set()
    for sid, name, mkt, close in rows:
        sid = str(sid)
        if sid in seen:
            continue
        seen.add(sid)
        key = (str(mkt or ""), _band(close))
        by_key.setdefault(key, []).append(
            {"stock_id": sid, "name": name, "market": str(mkt or ""), "close": float(close)}
        )
    # 每格先抽，再把 MUST 補進去。
    quota = {
        ("TW", "lo"): 180, ("TW", "mid"): 180, ("TW", "hi"): 140,
        ("TWO", "lo"): 120, ("TWO", "mid"): 140, ("TWO", "hi"): 90,
        ("EM", "lo"): 70, ("EM", "mid"): 60, ("EM", "hi"): 20,
    }
    picked: list[dict] = []
    used = set()

    def take(pool: list, k: int):
        out = []
        for item in pool:
            if item["stock_id"] in used:
                continue
            out.append(item)
            used.add(item["stock_id"])
            if len(out) >= k:
                break
        return out

    # MUST 先佔名額
    by_id = {str(sid): (name, mkt, close) for sid, name, mkt, close in rows}
    for sid in MUST:
        if sid in used or sid not in by_id:
            continue
        name, mkt, close = by_id[sid]
        picked.append({"stock_id": sid, "name": name, "market": mkt, "close": float(close)})
        used.add(sid)

    for key, k in quota.items():
        already = sum(1 for x in picked if (x["market"], _band(x["close"])) == key)
        need = max(0, k - already)
        picked.extend(take(by_key.get(key, []), need))

    if len(picked) < n:
        rest = []
        for pool in by_key.values():
            rest.extend(pool)
        picked.extend(take(rest, n - len(picked)))
    return picked[:n]


def card_issues(card: dict, texts: Iterable[str] | None = None) -> list[str]:
    sid = str(card.get("stock_id") or "")
    out: list[str] = []
    texts = list(texts or [])
    blob = "\n".join(texts)
    badges = [str(b) for b in (card.get("badges") or [])]
    if "多頭格局" in badges and "月K已走空" in badges:
        out.append("徽章互打：多頭格局＋月K已走空")
    if any(b in ("None", "nan", "NoneType") or "None" in b for b in badges):
        out.append("徽章出現 None")
    live = bool(card.get("is_live"))
    listing = str(card.get("listing") or "")
    if live:
        if session_price_label(card) != "現價":
            out.append("盤中 session 標籤不是現價")
        if texts:
            if "現價" not in texts:
                out.append("盤中沒有標現價")
            if "收盤" in texts:
                out.append("盤中大字還寫收盤")
            if "13:30收盤" in blob and "現價" in texts:
                out.append("盤中時鐘寫13:30收盤")
    else:
        if session_price_label(card) != "收盤":
            out.append("收盤後標籤不是收盤")
        if texts and "現價" in texts:
            out.append("收盤後還寫現價")
    if texts:
        if "今開" not in blob:
            out.append("沒有今開")
        if "昨收" not in blob and float(card.get("prev_close") or 0):
            out.append("沒有昨收")
        if "今K" not in texts:
            out.append("沒有今K")
        if float(card.get("prev_close") or 0) and "較昨" not in blob:
            out.append("有昨收但漲跌沒寫較昨日")
        if " 開 " in blob or blob.startswith("開 "):
            out.append("還在用舊標開高低")
        px = _fmt_price(card.get("close"))
        if px and px not in blob:
            out.append(f"大字沒有 {_fmt_price(card.get('close'))}")
        if "語料" in blob:
            out.append("國字出現語料")
    kotei = str(card.get("kotei_note") or "")
    stance = str(card.get("stance") or "")
    if "還有再" in kotei or "還有再" in blob:
        out.append("扣抵寫成還有再")
    if "語料" in kotei or "語料" in stance:
        out.append("敘述出現語料")
    if "扣抵距低點" in blob or "等多久打底" in blob:
        out.append("今日態度不該寫季線／月線扣抵倒數")
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
        if live and texts and "昨淨值" not in blob:
            out.append("ETF 盤中沒標昨淨值")
        if texts and "折溢價" in blob:
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
            if abs(float(row0["close"]) - close) > 0.05:
                out.append("表第一列股價跟大字不一致")
        except (TypeError, ValueError, KeyError):
            pass
    if str(card.get("quote_source") or "") == "emerging_quotes":
        if listing and listing != "興櫃":
            out.append(f"興櫃列成 {listing}")
        if "興櫃官方日均價" not in badges:
            out.append("興櫃沒有官方日均價徽章")
        if live:
            out.append("興櫃不該走上市櫃盤中現價")
    if listing and listing not in ("上市", "上櫃", "興櫃"):
        out.append(f"市場標異常 {listing}")
    del sid
    return out
