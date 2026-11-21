# -*- coding: utf-8 -*-
"""價值投資三圖：對齊轟天雷「表格式」可讀性（黑底／黃標／青格／紅漲青跌）。

只吃官方庫／OpenAPI 真數。ROE／負債比／應收週轉／存貨週轉無免驗證源 → 顯示 —。
季報明細圖用「單季」：累計列差分還原（與 expand_ytd_income_eps_to_single 同規則）。
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


# 轟天雷語彙色
BG = (0, 0, 0)
GRID = (0, 220, 220)  # 青格
YELLOW = (255, 220, 40)
WHITE = (245, 245, 245)
GREEN = (40, 220, 90)
RED = (255, 70, 70)
CYAN = (80, 220, 255)
MUTED = (160, 160, 160)
AMBER = (255, 180, 60)

W = 1600
H = 2000


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
    if v != v:
        return None
    return v


def _roc_ym(yyyymm: str) -> str:
    s = str(yyyymm or "")
    if len(s) != 6:
        return s
    return f"{int(s[:4]) - 1911}/{s[4:]}"


def _roc_season(year: int, season: int) -> str:
    return f"{int(year) - 1911}年 Q{int(season)}"


def _million_from_k(amount_k: Optional[float]) -> Optional[float]:
    """庫內千元 → 百萬（對齊轟天雷單位）。"""
    v = _finite(amount_k)
    if v is None:
        return None
    return v / 1000.0


def _fmt_m(v: Optional[float], *, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def _fmt_pct(v: Optional[float], *, signed: bool = False, digits: int = 2) -> str:
    if v is None:
        return "—"
    if signed:
        return f"{v:+.{digits}f}"
    return f"{v:.{digits}f}"


def _pct_color(v: Optional[float]):
    if v is None:
        return WHITE
    return RED if v >= 0 else CYAN


def _expand_cum_field(
    quarterly: Sequence[Dict[str, Any]], field: str
) -> Dict[Tuple[int, int], float]:
    """年初至該季累計 → 單季（相鄰季差分；Q1＝本身）。缺前期不上。"""
    by_year: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for r in quarterly or ():
        try:
            y, s = int(r["year"]), int(r["season"])
        except (KeyError, TypeError, ValueError):
            continue
        if y < 1990 or s not in (1, 2, 3, 4):
            continue
        by_year.setdefault(y, {})[s] = dict(r)
    out: Dict[Tuple[int, int], float] = {}
    for y, by_s in by_year.items():
        prev_cum: Optional[float] = None
        prev_season = 0
        for s in (1, 2, 3, 4):
            row = by_s.get(s)
            if row is None:
                continue
            cum = _finite(row.get(field))
            if cum is None:
                continue
            if s == 1:
                out[(y, s)] = cum
                prev_cum = cum
                prev_season = s
                continue
            if prev_cum is None:
                prev_cum = cum
                prev_season = s
                continue
            if s == prev_season + 1:
                out[(y, s)] = cum - prev_cum
            prev_cum = cum
            prev_season = s
    return out


def _load_company_profile(sid: str) -> Dict[str, Any]:
    """證交所 t187ap03／櫃買對應：有抓到才上，失敗回空。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate",
        }
        urls = (
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        )
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=45)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                code = str(
                    item.get("公司代號")
                    or item.get("SecuritiesCompanyCode")
                    or ""
                ).strip()
                if code != sid:
                    continue
                capital = _finite(item.get("實收資本額") or item.get("實收資本額(元)"))
                shares = _finite(
                    item.get("已發行普通股數或TDR原股發行股數")
                    or item.get("已發行普通股數")
                )
                return {
                    "name": str(
                        item.get("公司簡稱")
                        or item.get("公司名稱")
                        or item.get("CompanyName")
                        or sid
                    ).strip(),
                    "name_full": str(item.get("公司名稱") or "").strip(),
                    "name_en": str(
                        item.get("英文簡稱") or item.get("英文通訊地址") or ""
                    ).strip(),
                    "chairman": str(item.get("董事長") or "").strip(),
                    "gm": str(item.get("總經理") or "").strip(),
                    "founded": str(item.get("成立日期") or "").strip(),
                    "phone": str(item.get("總機電話") or "").strip(),
                    "address": str(item.get("住址") or "").strip(),
                    "capital": capital,
                    "shares": shares,
                    "par": str(item.get("普通股每股面額") or "").strip(),
                }
    except Exception:
        return empty
    return empty


def load_value_fund_pack(stock_id: str, db_path: str = None) -> Dict[str, Any]:
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
        "company": {},
        "monthly": [],
        "quarterly": [],
        "single": {},
        "note": "",
        "omit": "ROE／負債比／應收週轉／存貨週轉：官方 OpenAPI 無欄 → —",
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
        monthly = list_monthly_revenue(path, sid, limit=24)
        quarterly = list_quarterly_income(path, sid, limit=12)
    except Exception:
        monthly, quarterly = [], []

    eps_single = expand_ytd_income_eps_to_single(quarterly)
    rev_single = _expand_cum_field(quarterly, "revenue")
    op_single = _expand_cum_field(quarterly, "operating_income")
    non_single = _expand_cum_field(quarterly, "non_operating")
    gp_single = _expand_cum_field(quarterly, "gross_profit")

    company = _load_company_profile(sid)
    if company.get("name"):
        name = company["name"] or name

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
        "company": company,
        "monthly": monthly,
        "quarterly": quarterly,
        "single": {
            "eps": eps_single,
            "revenue": rev_single,
            "operating_income": op_single,
            "non_operating": non_single,
            "gross_profit": gp_single,
        },
        "note": "" if ok else "尚無官方本益／月營收／季報",
        "omit": empty["omit"],
    }


def _draw_grid_rect(draw: ImageDraw.ImageDraw, box, *, width: int = 2) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle((x0, y0, x1, y1), outline=GRID, width=width)


def _header_bar(
    draw: ImageDraw.ImageDraw,
    title: str,
    sid: str,
    name: str,
    unit: str,
    page: str,
) -> int:
    f = _font(30, bold=True)
    draw.text((24, 18), f"WayneBot{name}{sid}", font=f, fill=YELLOW)
    tw = f.getbbox(title)[2]
    draw.text(((W - tw) / 2, 18), title, font=f, fill=WHITE)
    right = f"單位: {unit}  {page}"
    rw = f.getbbox(right)[2]
    draw.text((W - 24 - rw, 18), right, font=f, fill=WHITE)
    # page red bit
    return 70


def render_overview_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「公司基本面總覽」：上公司卡、下估值／獲利。"""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _header_bar(
        draw,
        "公司基本面總覽(合併)",
        pack["stock_id"],
        pack["name"],
        "元／％",
        "01/10",
    )
    co = pack.get("company") or {}
    val = pack.get("valuation") or {}
    q0 = (pack.get("quarterly") or [None])[0]
    f_lab = _font(28)
    f_val = _font(28, bold=True)

    # 上框：公司
    box1 = (24, y, W - 24, y + 520)
    _draw_grid_rect(draw, box1)
    left = [
        ("股票名稱", pack.get("name") or "—"),
        ("股票代碼", pack.get("stock_id") or "—"),
        ("中文全名", co.get("name_full") or pack.get("name") or "—"),
        ("英文簡稱", co.get("name_en") or "—"),
        ("創立日期", co.get("founded") or "—"),
        ("董事長", co.get("chairman") or "—"),
        ("總經理", co.get("gm") or "—"),
        ("電話", co.get("phone") or "—"),
        ("公司地址", co.get("address") or "—"),
    ]
    yy = y + 24
    for lab, v in left:
        draw.text((48, yy), lab, font=f_lab, fill=YELLOW)
        draw.text((320, yy), str(v)[:42], font=f_val, fill=WHITE)
        yy += 52

    # 下框：資本／估值
    y2 = box1[3] + 24
    box2 = (24, y2, W - 24, H - 120)
    _draw_grid_rect(draw, box2)
    capital_yi = None
    if _finite(co.get("capital")) is not None:
        capital_yi = float(co["capital"]) / 1e8
    left2 = [
        ("股本(億)", _fmt_m(capital_yi) if capital_yi is not None else "—"),
        ("每股淨值(元)", _fmt_m(pack.get("book_from_pb"), digits=2)),
        ("收盤(元)", _fmt_m(pack.get("close"), digits=2)),
        ("本益資料日", val.get("date") or "—"),
    ]
    gm = _finite(q0.get("gross_margin_pct")) if q0 else None
    opm = None
    if q0:
        rev0 = _finite(q0.get("revenue"))
        op0 = _finite(q0.get("operating_income"))
        if rev0 and op0 is not None and rev0 != 0:
            opm = op0 / rev0 * 100.0
    eps0 = _finite(q0.get("eps")) if q0 else None
    right2 = [
        ("毛利率", f"{_fmt_pct(gm)}%" if gm is not None else "—"),
        ("營益率", f"{_fmt_pct(opm)}%" if opm is not None else "—"),
        ("本益比", _fmt_m(val.get("pe"))),
        (
            "每股純益(元)",
            f"{_fmt_m(eps0)}（{q0.get('season')}Q）" if q0 and eps0 is not None else "—",
        ),
        ("股價淨值比", _fmt_m(val.get("pb"))),
        ("殖利率％", _fmt_m(val.get("dividend_yield"))),
        ("負債比率", "—"),
        ("長期負債權益比", "—"),
        ("股東權益報酬率", "—"),
    ]
    yy = y2 + 28
    for lab, v in left2:
        draw.text((48, yy), lab, font=f_lab, fill=YELLOW)
        draw.text((320, yy), str(v), font=f_val, fill=GREEN if "淨值" in lab or "股本" in lab else WHITE)
        yy += 52
    yy = y2 + 28
    for lab, v in right2:
        draw.text((820, yy), lab, font=f_lab, fill=YELLOW)
        col = WHITE
        if v == "—":
            col = MUTED
        elif "本益" in lab or "純益" in lab or "毛利" in lab or "營益" in lab:
            col = YELLOW
        draw.text((1120, yy), str(v), font=f_val, fill=col)
        yy += 52

    note = pack.get("omit") or ""
    draw.text((48, H - 80), note, font=_font(24), fill=AMBER)
    draw.text(
        (48, H - 44),
        "來源：TWSE/TPEx 官方｜估值≠買訊｜—＝無官方免驗證欄",
        font=_font(22),
        fill=MUTED,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_monthly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「單月營收」：左近窗月增、右去年同月年增；底季累計表。"""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _header_bar(
        draw,
        "單月營收(合併)",
        pack["stock_id"],
        pack["name"],
        "百萬",
        "02/10",
    )
    f_h = _font(26, bold=True)
    f_c = _font(26)
    months = list(pack.get("monthly") or [])
    # 左：近 12 月 年月／月營收／上月比%
    left_box = (24, y, W // 2 - 12, y + 980)
    right_box = (W // 2 + 12, y, W - 24, y + 980)
    _draw_grid_rect(draw, left_box)
    _draw_grid_rect(draw, right_box)
    draw.text((40, y + 12), "年月", font=f_h, fill=WHITE)
    draw.text((200, y + 12), "月營收", font=f_h, fill=WHITE)
    draw.text((420, y + 12), "上月比%", font=f_h, fill=WHITE)
    draw.text((W // 2 + 28, y + 12), "年月", font=f_h, fill=WHITE)
    draw.text((W // 2 + 200, y + 12), "月營收", font=f_h, fill=WHITE)
    draw.text((W // 2 + 420, y + 12), "去年比%", font=f_h, fill=WHITE)

    show = months[:12]
    yy = y + 56
    for i, m in enumerate(show):
        yyyymm = str(m.get("yyyymm") or "")
        lab = _roc_ym(yyyymm) if i == 0 or yyyymm.endswith("01") else yyyymm[4:].lstrip("0") or yyyymm[4:]
        # 簡化：每年首列完整年月
        if i == 0 or (len(yyyymm) == 6 and yyyymm[4:] == "01"):
            lab = _roc_ym(yyyymm)
        elif len(yyyymm) == 6:
            lab = str(int(yyyymm[4:]))
        rev_m = _million_from_k(m.get("revenue"))
        mom = _finite(m.get("mom_pct"))
        draw.text((40, yy), lab, font=f_c, fill=WHITE)
        draw.text((200, yy), _fmt_m(rev_m), font=f_c, fill=YELLOW)
        draw.text((420, yy), _fmt_pct(mom, signed=False), font=f_c, fill=_pct_color(mom))
        yy += 72

    # 右欄：去年同月營收＋今年對去年的年增（用本列 yoy 對齊轟天雷右欄語意）
    yy = y + 56
    for m in show:
        yyyymm = str(m.get("yyyymm") or "")
        # prior year same month from revenue_prev_year if present
        prev = _million_from_k(m.get("revenue_prev_year"))
        yoy = _finite(m.get("yoy_pct"))
        lab = yyyymm[4:].lstrip("0") if len(yyyymm) == 6 else yyyymm
        if len(yyyymm) == 6 and yyyymm[4:] == "01":
            lab = _roc_ym(f"{int(yyyymm[:4])-1}{yyyymm[4:]}")
        draw.text((W // 2 + 28, yy), lab, font=f_c, fill=WHITE)
        draw.text((W // 2 + 200, yy), _fmt_m(prev), font=f_c, fill=YELLOW)
        draw.text(
            (W // 2 + 420, yy),
            _fmt_pct(yoy, signed=False),
            font=f_c,
            fill=_pct_color(yoy),
        )
        yy += 72

    # 底：季營收累計
    yq = left_box[3] + 24
    draw.text((40, yq), "季營收 (Q1-Q4 累計)", font=_font(30, bold=True), fill=WHITE)
    yq += 48
    qs = list(pack.get("quarterly") or [])[:4]
    if qs:
        # header seasons
        xs = [40, 280, 560, 840, 1120]
        draw.text((xs[0], yq), "", font=f_h, fill=WHITE)
        for i, q in enumerate(qs):
            draw.text(
                (xs[i + 1], yq),
                _roc_season(q["year"], q["season"]),
                font=f_h,
                fill=WHITE,
            )
        yq += 44
        rows_def = [
            (
                "營業收入",
                [
                    _fmt_m(_million_from_k(q.get("revenue")), digits=0)
                    for q in qs
                ],
            ),
            (
                "營益率",
                [
                    (
                        f"{(_finite(q.get('operating_income')) / _finite(q.get('revenue')) * 100.0):.2f}%"
                        if _finite(q.get("revenue"))
                        else "—"
                    )
                    for q in qs
                ],
            ),
            (
                "業外比率",
                [
                    (
                        f"{(_finite(q.get('non_operating')) / _finite(q.get('revenue')) * 100.0):.2f}%"
                        if _finite(q.get("non_operating")) is not None
                        and _finite(q.get("revenue"))
                        else "—"
                    )
                    for q in qs
                ],
            ),
            (
                "每股盈餘",
                [f"{_fmt_m(_finite(q.get('eps')))}元" for q in qs],
            ),
        ]
        for lab, cells in rows_def:
            draw.text((xs[0], yq), lab, font=f_c, fill=WHITE)
            for i, c in enumerate(cells):
                draw.text((xs[i + 1], yq), c, font=f_c, fill=YELLOW)
            yq += 48

    draw.text(
        (40, H - 70),
        "備註:單位百萬；四捨五入。紅＝正成長、青＝負成長。估值≠買訊",
        font=_font(22),
        fill=MUTED,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_quarterly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「季營收(單季資料)」：上4季＋下4季，列＝指標。"""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    y = _header_bar(
        draw,
        "季營收 (單季資料) (合併)",
        pack["stock_id"],
        pack["name"],
        "百萬",
        "04/10",
    )
    f_h = _font(24, bold=True)
    f_c = _font(24)
    single = pack.get("single") or {}
    qs = list(pack.get("quarterly") or [])[:8]
    # build chronologically newest first already
    blocks = [qs[:4], qs[4:8]]
    metrics = [
        ("期別", "season"),
        ("營業收入淨額", "revenue"),
        ("毛利率", "gm"),
        ("營收成長率", "growth"),
        ("營業利益", "op"),
        ("營業外損益", "non"),
        ("應收帳款週轉率", "ar"),
        ("存貨週轉率", "inv"),
        ("營益率", "opm"),
        ("每股純益", "eps"),
    ]

    def cell(q: Dict[str, Any], kind: str) -> Tuple[str, tuple]:
        key = (int(q["year"]), int(q["season"]))
        if kind == "season":
            return _roc_season(q["year"], q["season"]), WHITE
        if kind == "revenue":
            v = _million_from_k(single.get("revenue", {}).get(key))
            return _fmt_m(v), YELLOW
        if kind == "gm":
            rev = _finite(single.get("revenue", {}).get(key))
            gp = _finite(single.get("gross_profit", {}).get(key))
            if rev and gp is not None and rev != 0:
                return f"{gp / rev * 100.0:.2f}", YELLOW
            # fallback cum margin if single gp missing
            gm = _finite(q.get("gross_margin_pct"))
            return (_fmt_pct(gm) if gm is not None else "—"), YELLOW if gm is not None else MUTED
        if kind == "growth":
            # YoY vs same season prior year single revenue
            rev = _finite(single.get("revenue", {}).get(key))
            prev = _finite(
                single.get("revenue", {}).get((key[0] - 1, key[1]))
            )
            if rev is None or prev is None or prev == 0:
                return "—", MUTED
            g = (rev - prev) / abs(prev) * 100.0
            return _fmt_pct(g, signed=False), _pct_color(g)
        if kind == "op":
            v = _million_from_k(single.get("operating_income", {}).get(key))
            return _fmt_m(v), YELLOW
        if kind == "non":
            raw = single.get("non_operating", {}).get(key)
            if raw is None and q.get("non_operating") is None:
                return "—", MUTED
            v = _million_from_k(raw if raw is not None else q.get("non_operating"))
            return _fmt_m(v), YELLOW
        if kind in ("ar", "inv"):
            return "—", MUTED
        if kind == "opm":
            rev = _finite(single.get("revenue", {}).get(key))
            op = _finite(single.get("operating_income", {}).get(key))
            if rev and op is not None and rev != 0:
                return f"{op / rev * 100.0:.2f}", YELLOW
            return "—", MUTED
        if kind == "eps":
            e = _finite(single.get("eps", {}).get(key))
            if e is None:
                return "—", MUTED
            return f"{e:.2f}元", YELLOW
        return "—", MUTED

    for bi, block in enumerate(blocks):
        if not block:
            continue
        top = y + bi * 880
        box = (24, top, W - 24, top + 840)
        _draw_grid_rect(draw, box)
        # columns: label + up to 4 seasons
        xs = [40, 360, 640, 920, 1200]
        # metric rows
        yy = top + 20
        row_h = 76
        for mi, (lab, kind) in enumerate(metrics):
            draw.line((40, yy - 6, W - 40, yy - 6), fill=GRID, width=1)
            draw.text((xs[0], yy), lab, font=f_h if mi == 0 else f_c, fill=WHITE)
            for ci, q in enumerate(block):
                text, col = cell(q, kind)
                draw.text((xs[ci + 1], yy), text, font=f_c, fill=col)
            yy += row_h

    draw.text((40, H - 70), pack.get("omit") or "", font=_font(22), fill=AMBER)
    draw.text(
        (40, H - 40),
        "單季＝累計差分（缺前期不上）｜來源官方綜合損益｜估值≠買訊",
        font=_font(22),
        fill=MUTED,
    )
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
