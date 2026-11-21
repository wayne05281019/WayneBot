# -*- coding: utf-8 -*-
"""價值投資三圖：只吃官方庫欄，不准造假。

對齊話筒需求（轟天雷三張圖資語彙）：
1) 總覽：本益／淨值／殖利率／累計EPS／毛利營益／營業外（有才上）
2) 月營收＋近季累計
3) 季報明細（累計＋可還原之單季 EPS）

ROE／負債比／週轉率：證交所／櫃買免驗證碼 OpenAPI 無對應欄 → 不上假數。
估值≠買訊；切入仍只認高低卡黃金買點。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

try:
    from config import get_charts_dir, get_db_path
except Exception:

    def get_db_path():
        return "data/wayne_market.db"

    def get_charts_dir():
        return os.path.join("data", "charts")


W = 1290
H = 1800
BG = (11, 17, 32)
CARD = (17, 24, 39)
GRID = (42, 50, 60)
TEXT = (236, 242, 248)
HEAD = (132, 208, 255)
MUTED = (154, 163, 173)
GREEN = (61, 220, 151)
RED = (240, 113, 120)
AMBER = (251, 191, 36)


def _font(size: int, *, bold: bool = False):
    from industry_card import _card_font

    return _card_font(size, bold=bold)


def _ymd(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())[:8]


def _finite(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def _fmt_pct(v: Optional[float], *, signed: bool = False, digits: int = 2) -> str:
    if v is None:
        return "—"
    if signed:
        return f"{v:+.{digits}f}%"
    return f"{v:.{digits}f}%"


def _fmt_num(v: Optional[float], *, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def _fmt_yi(k_or_raw: Optional[float]) -> str:
    """金額：庫內季報／月營收多為千元；顯示億元。"""
    from fundamentals import format_yi

    if k_or_raw is None:
        return "—"
    return format_yi(k_or_raw)


def _op_margin(row: Dict[str, Any]) -> Optional[float]:
    rev = _finite(row.get("revenue"))
    op = _finite(row.get("operating_income"))
    if rev is None or rev == 0 or op is None:
        return None
    return round(op / rev * 100.0, 2)


def _non_op_ratio(row: Dict[str, Any]) -> Optional[float]:
    rev = _finite(row.get("revenue"))
    non = _finite(row.get("non_operating"))
    if rev is None or rev == 0 or non is None:
        return None
    return round(non / rev * 100.0, 2)


def load_value_fund_pack(stock_id: str, db_path: str = None) -> Dict[str, Any]:
    """組三圖用真實包：缺官方欄就空，不准補假。"""
    path = db_path or get_db_path()
    sid = str(stock_id or "").strip()
    empty: Dict[str, Any] = {
        "ok": False,
        "stock_id": sid,
        "name": sid,
        "market": "",
        "valuation": {},
        "close": None,
        "book_from_pb": None,
        "monthly": [],
        "quarterly": [],
        "eps_single": {},
        "note": "",
    }
    if not sid or not path or not os.path.isfile(path):
        empty["note"] = "缺庫"
        return empty
    try:
        from fundamentals import (
            ensure_fundamentals_tables,
            expand_ytd_income_eps_to_single,
            list_monthly_revenue,
            list_quarterly_income,
        )

        ensure_fundamentals_tables(path)
    except Exception as exc:
        empty["note"] = type(exc).__name__
        return empty

    name = sid
    market = ""
    valuation: Dict[str, Any] = {}
    close = None
    book = None
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        uni = conn.execute(
            "SELECT stock_name, market_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
        if uni:
            name = str(uni["stock_name"] or sid).strip() or sid
            market = str(uni["market_type"] or "").strip()
        val = conn.execute(
            """
            SELECT date, pe, pb, dividend_yield, source
            FROM daily_valuation
            WHERE stock_id=?
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        valuation = dict(val) if val else {}
        d = _ymd(valuation.get("date"))
        if d:
            q = conn.execute(
                """
                SELECT close FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=?
                  AND close IS NOT NULL AND close > 0
                ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
                LIMIT 1
                """,
                (sid, d),
            ).fetchone()
            if q is not None:
                close = _finite(q[0] if not isinstance(q, sqlite3.Row) else q["close"])
        pb = _finite(valuation.get("pb"))
        if close is not None and pb is not None and pb > 0:
            book = round(close / pb, 2)
    finally:
        conn.close()

    try:
        monthly = list_monthly_revenue(path, sid, limit=12)
        quarterly = list_quarterly_income(path, sid, limit=8)
    except Exception:
        monthly, quarterly = [], []

    eps_single = expand_ytd_income_eps_to_single(quarterly)
    ok = bool(valuation or monthly or quarterly)
    return {
        "ok": ok,
        "stock_id": sid,
        "name": name,
        "market": market,
        "valuation": {
            "date": _ymd(valuation.get("date")),
            "pe": _finite(valuation.get("pe")),
            "pb": _finite(valuation.get("pb")),
            "dividend_yield": _finite(valuation.get("dividend_yield")),
            "source": str(valuation.get("source") or ""),
        },
        "close": close,
        "book_from_pb": book,
        "monthly": monthly,
        "quarterly": quarterly,
        "eps_single": {f"{y}Q{s}": v for (y, s), v in eps_single.items()},
        "note": "" if ok else "尚無官方本益／月營收／季報",
        "omit": "ROE／負債比／週轉：官方 OpenAPI 無欄，不上假數",
    }


def _draw_header(draw: ImageDraw.ImageDraw, title: str, sid: str, name: str) -> int:
    f_title = _font(44, bold=True)
    f_sub = _font(28)
    draw.text((48, 40), title, font=f_title, fill=HEAD)
    draw.text((48, 100), f"{sid}　{name}", font=f_sub, fill=TEXT)
    return 160


def _hline(draw: ImageDraw.ImageDraw, y: int, x0: int = 48, x1: int = W - 48) -> None:
    draw.line((x0, y, x1, y), fill=GRID, width=2)


def render_overview_png(pack: Dict[str, Any], out_path: str) -> str:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _draw_header(draw, "價值・總覽", pack["stock_id"], pack["name"])
    _hline(draw, y)
    y += 28
    f_lab = _font(28)
    f_val = _font(32, bold=True)
    f_note = _font(24)
    val = pack.get("valuation") or {}
    rows: List[Tuple[str, str]] = [
        ("本益資料日", val.get("date") or "—"),
        ("本益比", _fmt_num(val.get("pe"))),
        ("股價淨值比", _fmt_num(val.get("pb"))),
        ("殖利率％", _fmt_num(val.get("dividend_yield"))),
        ("收盤（同資料日）", _fmt_num(pack.get("close"))),
        ("淨值／股（收÷淨值比）", _fmt_num(pack.get("book_from_pb"))),
    ]
    q0 = (pack.get("quarterly") or [None])[0]
    if q0:
        rows.append(("季報", f"{q0.get('year')}Q{q0.get('season')}累計"))
        rows.append(("累計 EPS", _fmt_num(_finite(q0.get("eps")))))
        rows.append(("毛利率", _fmt_pct(_finite(q0.get("gross_margin_pct")))))
        rows.append(("營益率", _fmt_pct(_op_margin(q0))))
        rows.append(("營業外／營收", _fmt_pct(_non_op_ratio(q0))))
        rows.append(("稅後淨利", _fmt_yi(_finite(q0.get("net_income")))))
    for lab, v in rows:
        draw.text((56, y), lab, font=f_lab, fill=MUTED)
        tw = f_val.getbbox(v)[2]
        draw.text((W - 56 - tw, y), v, font=f_val, fill=TEXT)
        y += 64
        if y > H - 160:
            break
    y += 20
    _hline(draw, y)
    y += 24
    draw.text((56, y), str(pack.get("omit") or ""), font=f_note, fill=AMBER)
    y += 40
    draw.text(
        (56, y),
        "來源：TWSE/TPEx 官方本益＋綜合損益｜估值≠買訊",
        font=f_note,
        fill=MUTED,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_monthly_png(pack: Dict[str, Any], out_path: str) -> str:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _draw_header(draw, "價值・月營收", pack["stock_id"], pack["name"])
    _hline(draw, y)
    y += 20
    f_h = _font(26, bold=True)
    f_c = _font(26)
    headers = ("年月", "營收", "月增％", "年增％")
    xs = [56, 280, 620, 920]
    for i, h in enumerate(headers):
        draw.text((xs[i], y), h, font=f_h, fill=HEAD)
    y += 48
    _hline(draw, y)
    y += 16
    for m in pack.get("monthly") or []:
        yyyymm = str(m.get("yyyymm") or "")
        lab = f"{yyyymm[:4]}/{yyyymm[4:]}" if len(yyyymm) == 6 else yyyymm
        mom = _finite(m.get("mom_pct"))
        yoy = _finite(m.get("yoy_pct"))
        cells = (
            lab,
            _fmt_yi(_finite(m.get("revenue"))),
            _fmt_pct(mom, signed=True, digits=2),
            _fmt_pct(yoy, signed=True, digits=2),
        )
        fills = (
            TEXT,
            TEXT,
            GREEN if (mom or 0) >= 0 else RED,
            GREEN if (yoy or 0) >= 0 else RED,
        )
        for i, (c, fl) in enumerate(zip(cells, fills)):
            draw.text((xs[i], y), c, font=f_c, fill=fl)
        y += 52
        if y > H - 420:
            break
    y += 12
    _hline(draw, y)
    y += 20
    draw.text((56, y), "近季累計（官方列＝年初至該季）", font=f_h, fill=HEAD)
    y += 48
    q_xs = [56, 220, 480, 780, 1020]
    for i, h in enumerate(("季", "營收", "營益率", "業外比", "EPS累計")):
        draw.text((q_xs[i], y), h, font=f_h, fill=HEAD)
    y += 44
    for q in (pack.get("quarterly") or [])[:4]:
        cells = (
            f"{q.get('year')}Q{q.get('season')}",
            _fmt_yi(_finite(q.get("revenue"))),
            _fmt_pct(_op_margin(q)),
            _fmt_pct(_non_op_ratio(q)),
            _fmt_num(_finite(q.get("eps"))),
        )
        for i, c in enumerate(cells):
            draw.text((q_xs[i], y), c, font=f_c, fill=TEXT)
        y += 48
        if y > H - 80:
            break
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_quarterly_png(pack: Dict[str, Any], out_path: str) -> str:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _draw_header(draw, "價值・季報明細", pack["stock_id"], pack["name"])
    _hline(draw, y)
    y += 20
    f_h = _font(24, bold=True)
    f_c = _font(24)
    # 單季 EPS 由累計差分還原（fundamentals.expand_ytd_income_eps_to_single）
    headers = ("季", "營收", "毛利率", "營益", "業外", "EPS累計", "EPS單季")
    xs = [40, 170, 400, 560, 760, 960, 1140]
    for i, h in enumerate(headers):
        draw.text((xs[i], y), h, font=f_h, fill=HEAD)
    y += 44
    _hline(draw, y)
    y += 12
    single = pack.get("eps_single") or {}
    for q in pack.get("quarterly") or []:
        key = f"{q.get('year')}Q{q.get('season')}"
        eps_s = single.get(key)
        cells = (
            key,
            _fmt_yi(_finite(q.get("revenue"))),
            _fmt_pct(_finite(q.get("gross_margin_pct")), digits=2),
            _fmt_yi(_finite(q.get("operating_income"))),
            _fmt_yi(_finite(q.get("non_operating")))
            if q.get("non_operating") is not None
            else "—",
            _fmt_num(_finite(q.get("eps"))),
            _fmt_num(_finite(eps_s)),
        )
        for i, c in enumerate(cells):
            draw.text((xs[i], y), str(c), font=f_c, fill=TEXT)
        y += 48
        if y > H - 120:
            break
    y += 16
    _hline(draw, y)
    y += 24
    f_note = _font(24)
    draw.text(
        (48, y),
        "單季 EPS＝累計差分（缺前期累計則不上）；營業外缺列＝—",
        font=f_note,
        fill=MUTED,
    )
    y += 40
    draw.text((48, y), "來源：官方綜合損益｜估值≠買訊", font=f_note, fill=MUTED)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_value_fund_panels(
    stock_id: str,
    db_path: str = None,
    out_dir: str = None,
    *,
    uid: str = "0",
) -> Dict[str, Any]:
    """渲三張 PNG。回傳 paths／pack；無資料則 ok=False。"""
    pack = load_value_fund_pack(stock_id, db_path)
    if not pack.get("ok"):
        return {"ok": False, "pack": pack, "paths": []}
    root = out_dir or get_charts_dir()
    sid = pack["stock_id"]
    base = os.path.join(root, f"value_{sid}_{uid}")
    os.makedirs(root, exist_ok=True)
    paths = [
        render_overview_png(pack, f"{base}_overview.png"),
        render_monthly_png(pack, f"{base}_monthly.png"),
        render_quarterly_png(pack, f"{base}_quarterly.png"),
    ]
    return {"ok": True, "pack": pack, "paths": paths}


__all__ = [
    "load_value_fund_pack",
    "render_value_fund_panels",
    "render_overview_png",
    "render_monthly_png",
    "render_quarterly_png",
]
