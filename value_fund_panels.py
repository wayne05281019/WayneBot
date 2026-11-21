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


# 轟天雷語彙色（對齊截圖像素：純黃／純白／純青格／正紅／負青／綠框）
BG = (0, 0, 0)
GRID = (0, 255, 255)  # 青格
YELLOW = (255, 255, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)  # 公司框／日期
RED = (255, 0, 0)  # 正％
CYAN = (0, 255, 255)  # 負％
MUTED = (170, 170, 170)
AMBER = (255, 200, 60)

# 寬終端、密排（對齊 HT ~16:9；W≈1500）
W = 1520
H_OVERVIEW = 900
H_MONTHLY = 820
H_QUARTERLY = 880


def _font(size: int, *, bold: bool = False):
    from industry_card import _card_font

    return _card_font(size, bold=bold)


def _text_w(font, text: str) -> int:
    return int(font.getlength(str(text or "")))


def _draw_left(draw: ImageDraw.ImageDraw, xy, text: str, font, fill) -> None:
    draw.text(xy, str(text or ""), font=font, fill=fill)


def _draw_right(
    draw: ImageDraw.ImageDraw, x_right: int, y: int, text: str, font, fill
) -> None:
    s = str(text or "")
    draw.text((x_right - _text_w(font, s), y), s, font=font, fill=fill)


def _draw_center(
    draw: ImageDraw.ImageDraw, cx: int, y: int, text: str, font, fill
) -> None:
    s = str(text or "")
    draw.text((cx - _text_w(font, s) / 2, y), s, font=font, fill=fill)


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


def _roc_ymd(raw: Any) -> str:
    """YYYYMMDD／YYYY-MM-DD → 民國 yy/mm/dd；缺則原字或空。"""
    s = _ymd(raw)
    if len(s) != 8:
        return str(raw or "").strip()
    try:
        return f"{int(s[:4]) - 1911:02d}/{s[4:6]}/{s[6:8]}"
    except ValueError:
        return s


def _fmt_phone(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        return f"({digits[:2]}){digits[2:6]}-{digits[6:]}"
    if len(digits) == 9 and digits.startswith("2"):
        return f"(0{digits[0]}){digits[1:5]}-{digits[5:]}"
    return s


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


def _draw_grid_rect(
    draw: ImageDraw.ImageDraw, box, *, fill=None, outline=GRID, width: int = 1
) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle((x0, y0, x1, y1), outline=outline, width=width, fill=fill)


def _header_bar(
    draw: ImageDraw.ImageDraw,
    title: str,
    sid: str,
    name: str,
    unit: str,
    page: str,
    *,
    canvas_w: int = W,
) -> int:
    """頂列：黃品牌＋白公司＋白標題＋白單位＋紅頁碼。回傳內容起始 y。"""
    f_brand = _font(26, bold=True)
    f = _font(24, bold=True)
    brand = "WayneBot"
    _draw_left(draw, (16, 10), brand, f_brand, YELLOW)
    bx = 16 + _text_w(f_brand, brand) + 10
    _draw_left(draw, (bx, 12), f"{name}{sid}", f, WHITE)
    _draw_center(draw, canvas_w // 2, 12, title, f, WHITE)
    unit_s = f"單位：{unit}"
    page_s = str(page)
    gap = 14
    total_r = _text_w(f, unit_s) + gap + _text_w(f, page_s)
    rx = canvas_w - 16 - total_r
    _draw_left(draw, (rx, 12), unit_s, f, WHITE)
    _draw_left(draw, (rx + _text_w(f, unit_s) + gap, 12), page_s, f, RED)
    return 48


def _month_label(yyyymm: str, *, index: int, force_full: bool = False) -> str:
    s = str(yyyymm or "")
    if len(s) != 6:
        return s
    if force_full or index == 0 or s[4:] == "01" or s[4:] == "12":
        # 跨年列／首列給完整民國年月；12 月也給年方便對齊 HT
        if index == 0 or s[4:] == "01":
            return _roc_ym(s)
        if s[4:] == "12":
            return _roc_ym(s)
    return str(int(s[4:]))


def render_overview_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「公司基本面總覽」：綠框公司卡（雙欄）＋底比率。"""
    h = H_OVERVIEW
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y0 = _header_bar(
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
    f_lab = _font(22)
    f_val = _font(22)
    f_small = _font(16)

    # 上框：公司（綠框、雙欄，對齊 HT）
    box1 = (16, y0 + 4, W - 16, y0 + 4 + 340)
    _draw_grid_rect(draw, box1, outline=GREEN, width=2)

    founded = _roc_ymd(co.get("founded")) or "—"
    phone = _fmt_phone(co.get("phone")) or "—"
    left_co = [
        ("股票名稱", pack.get("name") or "—"),
        ("創立日期", founded),
        ("董事長", co.get("chairman") or "—"),
        ("電話", phone),
        ("中文全名", co.get("name_full") or pack.get("name") or "—"),
        ("英文全名", co.get("name_en") or "—"),
        ("公司地址", co.get("address") or "—"),
        ("業務比重", "—"),  # OpenAPI t187ap03 無此欄
    ]
    right_co = [
        ("股票代碼", pack.get("stock_id") or "—"),
        ("會計年度月份", "—"),
        ("總經理", co.get("gm") or "—"),
        ("", ""),
        ("", ""),
        ("", ""),
        ("", ""),
        ("", ""),
    ]
    lab_w = 150
    yy = box1[1] + 14
    row_h = 38
    for i, ((lab_l, v_l), (lab_r, v_r)) in enumerate(zip(left_co, right_co)):
        if lab_l:
            _draw_left(draw, (box1[0] + 18, yy), f"{lab_l}", f_lab, YELLOW)
            _draw_left(draw, (box1[0] + 18 + lab_w, yy), f"：{v_l}", f_val, WHITE)
        if lab_r:
            x2 = box1[0] + W // 2 - 20
            _draw_left(draw, (x2, yy), f"{lab_r}", f_lab, YELLOW)
            _draw_left(draw, (x2 + lab_w + 20, yy), f"：{v_r}", f_val, WHITE)
        yy += row_h

    # 底：股東會／股利（左）＋獲利／估值（右）；無官方欄 → —
    y2 = box1[3] + 18
    capital_yi = None
    if _finite(co.get("capital")) is not None:
        capital_yi = float(co["capital"]) / 1e8
    gm = _finite(q0.get("gross_margin_pct")) if q0 else None
    opm = None
    if q0:
        rev0 = _finite(q0.get("revenue"))
        op0 = _finite(q0.get("operating_income"))
        if rev0 and op0 is not None and rev0 != 0:
            opm = op0 / rev0 * 100.0
    eps0 = _finite(q0.get("eps")) if q0 else None
    season0 = q0.get("season") if q0 else None

    left_bot = [
        ("股東大會地點", co.get("address") or "—", WHITE),
        ("股東大會時間", "—", GREEN),
        ("除權日期", "—", GREEN),
        ("除息日期", "—", GREEN),
        ("盈配(元)", "—", WHITE),
        ("資配(元)", "—", WHITE),
        ("現金股利(元)", "—", WHITE),  # 無官方每股現金股利欄，不准用殖利率推
        (
            "股本(億)",
            _fmt_m(capital_yi) if capital_yi is not None else "—",
            WHITE,
        ),
        (
            "每股淨值(元)",
            _fmt_m(pack.get("book_from_pb"), digits=2),
            WHITE,
        ),
    ]
    right_bot = [
        ("毛利率", f"{_fmt_pct(gm)}%" if gm is not None else "—", YELLOW),
        ("營益率", f"{_fmt_pct(opm)}%" if opm is not None else "—", YELLOW),
        ("本益比", _fmt_m(val.get("pe")), YELLOW),
        (
            "每股純益(元)",
            (
                f"{_fmt_m(eps0)}({season0}Q)"
                if season0 is not None and eps0 is not None
                else "—"
            ),
            YELLOW,
        ),
        ("股價淨值比", _fmt_m(val.get("pb")), YELLOW),
        ("負債比率", "—", MUTED),
        ("長期負債權益比", "—", MUTED),
        ("股東權益報酬率", "—", MUTED),
    ]
    lab_w2 = 180
    yy = y2
    for lab, v, col in left_bot:
        _draw_left(draw, (34, yy), lab, f_lab, YELLOW)
        _draw_left(draw, (34 + lab_w2, yy), f"：{v}", f_val, col if v != "—" else MUTED)
        yy += 36

    yy = y2
    x_r = W // 2 + 40
    for lab, v, col in right_bot:
        _draw_left(draw, (x_r, yy), lab, f_lab, YELLOW)
        _draw_left(
            draw,
            (x_r + lab_w2 + 30, yy),
            f"：{v}",
            f_val,
            col if v != "—" else MUTED,
        )
        yy += 36

    note = pack.get("omit") or ""
    _draw_left(draw, (34, h - 48), note, f_small, AMBER)
    _draw_left(
        draw,
        (34, h - 28),
        "來源：TWSE/TPEx 官方｜估值≠買訊｜—＝無官方免驗證欄",
        f_small,
        MUTED,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_monthly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「單月營收」：左 MoM、右 YoY；底季累計；單位百萬。"""
    h = H_MONTHLY
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y0 = _header_bar(
        draw,
        "單月營收(合併)",
        pack["stock_id"],
        pack["name"],
        "百萬",
        "02/10",
    )
    f_h = _font(20, bold=True)
    f_c = _font(20)
    f_note = _font(14)
    months = list(pack.get("monthly") or [])
    show_n = 12
    show = months[:show_n]

    mid = W // 2
    table_top = y0 + 4
    q_band = 210
    table_bot = h - q_band
    left_box = (12, table_top, mid - 6, table_bot)
    right_box = (mid + 6, table_top, W - 12, table_bot)
    _draw_grid_rect(draw, left_box, outline=GRID, width=1)
    _draw_grid_rect(draw, right_box, outline=GRID, width=1)

    # 欄寬：年月｜月營收｜比%
    def _col_xs(box):
        x0, _, x1, _ = box
        w = x1 - x0
        return {
            "ym": x0 + 12,
            "rev_r": x0 + int(w * 0.62),
            "pct_r": x1 - 14,
            "head_ym": x0 + 12,
            "head_rev": x0 + int(w * 0.38),
            "head_pct": x0 + int(w * 0.68),
        }

    lx = _col_xs(left_box)
    rx = _col_xs(right_box)
    head_y = table_top + 8
    _draw_left(draw, (lx["head_ym"], head_y), "年月", f_h, WHITE)
    _draw_left(draw, (lx["head_rev"], head_y), "月營收", f_h, WHITE)
    _draw_left(draw, (lx["head_pct"], head_y), "上月比%", f_h, WHITE)
    _draw_left(draw, (rx["head_ym"], head_y), "年月", f_h, WHITE)
    _draw_left(draw, (rx["head_rev"], head_y), "月營收", f_h, WHITE)
    _draw_left(draw, (rx["head_pct"], head_y), "去年比%", f_h, WHITE)

    # 表頭下橫線＋中線
    hy = head_y + 28
    draw.line((left_box[0], hy, left_box[2], hy), fill=GRID, width=1)
    draw.line((right_box[0], hy, right_box[2], hy), fill=GRID, width=1)
    # 直欄線
    for box, xs in ((left_box, lx), (right_box, rx)):
        v1 = box[0] + int((box[2] - box[0]) * 0.28)
        v2 = box[0] + int((box[2] - box[0]) * 0.62)
        draw.line((v1, table_top, v1, table_bot), fill=GRID, width=1)
        draw.line((v2, table_top, v2, table_bot), fill=GRID, width=1)

    row_h = max(28, (table_bot - hy - 8) // max(1, show_n))
    for i, m in enumerate(show):
        yyyymm = str(m.get("yyyymm") or "")
        lab = _month_label(yyyymm, index=i)
        rev_m = _million_from_k(m.get("revenue"))
        mom = _finite(m.get("mom_pct"))
        yy = hy + 6 + i * row_h
        _draw_left(draw, (lx["ym"], yy), lab, f_c, YELLOW)
        _draw_right(draw, lx["rev_r"], yy, _fmt_m(rev_m), f_c, YELLOW)
        _draw_right(
            draw, lx["pct_r"], yy, _fmt_pct(mom, signed=False), f_c, _pct_color(mom)
        )

        # 右：同月營收＋去年比%（對齊 HT 左右雙表同營收、右欄年增）
        yoy = _finite(m.get("yoy_pct"))
        _draw_left(draw, (rx["ym"], yy), lab, f_c, YELLOW)
        _draw_right(draw, rx["rev_r"], yy, _fmt_m(rev_m), f_c, YELLOW)
        _draw_right(
            draw, rx["pct_r"], yy, _fmt_pct(yoy, signed=False), f_c, _pct_color(yoy)
        )

    # 底：季營收累計（Q1–Q4 累計）
    yq = table_bot + 10
    _draw_center(draw, W // 2, yq, "季營收 (Q1-Q4 累計)", _font(22, bold=True), WHITE)
    yq += 30
    qs = list(pack.get("quarterly") or [])[:4]
    # 5 欄：標籤 + 4 季
    label_w = 140
    q_box = (12, yq, W - 12, h - 36)
    _draw_grid_rect(draw, q_box, outline=GRID, width=1)
    n_col = 4
    cell_w = (q_box[2] - q_box[0] - label_w) / max(1, n_col)
    # 直線
    draw.line(
        (q_box[0] + label_w, q_box[1], q_box[0] + label_w, q_box[3]),
        fill=GRID,
        width=1,
    )
    for i in range(1, n_col):
        x = q_box[0] + label_w + int(i * cell_w)
        draw.line((x, q_box[1], x, q_box[3]), fill=GRID, width=1)

    row_labs = ["", "營業收入", "營益率", "業外比率", "每股盈餘"]
    q_row_h = (q_box[3] - q_box[1]) // len(row_labs)
    for ri, lab in enumerate(row_labs):
        yy = q_box[1] + 4 + ri * q_row_h
        if ri > 0:
            draw.line(
                (q_box[0], q_box[1] + ri * q_row_h, q_box[2], q_box[1] + ri * q_row_h),
                fill=GRID,
                width=1,
            )
        if lab:
            _draw_left(draw, (q_box[0] + 10, yy), lab, f_c, YELLOW)
        if not qs:
            continue
        for ci, q in enumerate(qs):
            cx_r = q_box[0] + label_w + int((ci + 1) * cell_w) - 10
            if ri == 0:
                _draw_right(
                    draw,
                    cx_r,
                    yy,
                    _roc_season(q["year"], q["season"]),
                    f_h,
                    WHITE,
                )
            elif ri == 1:
                _draw_right(
                    draw,
                    cx_r,
                    yy,
                    _fmt_m(_million_from_k(q.get("revenue")), digits=0),
                    f_c,
                    YELLOW,
                )
            elif ri == 2:
                rev = _finite(q.get("revenue"))
                op = _finite(q.get("operating_income"))
                txt = (
                    f"{(op / rev * 100.0):.2f}%"
                    if rev and op is not None and rev != 0
                    else "—"
                )
                _draw_right(draw, cx_r, yy, txt, f_c, YELLOW if txt != "—" else MUTED)
            elif ri == 3:
                rev = _finite(q.get("revenue"))
                non = _finite(q.get("non_operating"))
                txt = (
                    f"{(non / rev * 100.0):.2f}%"
                    if rev and non is not None and rev != 0
                    else "—"
                )
                _draw_right(draw, cx_r, yy, txt, f_c, YELLOW if txt != "—" else MUTED)
            elif ri == 4:
                e = _finite(q.get("eps"))
                txt = f"{_fmt_m(e)}元" if e is not None else "—"
                _draw_right(draw, cx_r, yy, txt, f_c, YELLOW if txt != "—" else MUTED)

    _draw_left(
        draw,
        (16, h - 26),
        "備註: 本表格因採取百萬元為計算單位, 四捨五入。紅＝正成長、青＝負成長。估值≠買訊",
        f_note,
        MUTED,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_quarterly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「季營收(單季資料)」：2 列×4 季欄；左指標；單季＝累計差分。"""
    h = H_QUARTERLY
    img = Image.new("RGB", (W, h), BG)
    draw = ImageDraw.Draw(img)
    y0 = _header_bar(
        draw,
        "季營收(單季資料)(合併)",
        pack["stock_id"],
        pack["name"],
        "百萬",
        "04/10",
    )
    f_h = _font(20, bold=True)
    f_c = _font(20)
    f_note = _font(14)
    single = pack.get("single") or {}
    qs = list(pack.get("quarterly") or [])[:8]
    blocks = [qs[:4], qs[4:8]]
    # 使用者列序；應收／存貨無官方欄 → —
    metrics = [
        ("期別", "season"),
        ("營業收入淨額", "revenue"),
        ("毛利率", "gm"),
        ("營收成長率", "growth"),
        ("營業利益", "op"),
        ("營業外損益", "non"),
        ("應收週轉", "ar"),
        ("存貨週轉", "inv"),
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
                return f"{gp / rev * 100.0:.2f}%", YELLOW
            gm = _finite(q.get("gross_margin_pct"))
            if gm is None:
                return "—", MUTED
            return f"{gm:.2f}%", YELLOW
        if kind == "growth":
            rev = _finite(single.get("revenue", {}).get(key))
            prev = _finite(single.get("revenue", {}).get((key[0] - 1, key[1])))
            if rev is None or prev is None or prev == 0:
                return "—", MUTED
            g = (rev - prev) / abs(prev) * 100.0
            return f"{g:.2f}%", _pct_color(g)
        if kind == "op":
            v = _million_from_k(single.get("operating_income", {}).get(key))
            return _fmt_m(v), YELLOW
        if kind == "non":
            raw = single.get("non_operating", {}).get(key)
            if raw is None and q.get("non_operating") is None:
                return "—", MUTED
            v = _million_from_k(raw if raw is not None else q.get("non_operating"))
            if v is None:
                return "—", MUTED
            # 負數用青，對齊 HT 損益色感
            return _fmt_m(v), CYAN if v < 0 else YELLOW
        if kind in ("ar", "inv"):
            return "—", MUTED
        if kind == "opm":
            rev = _finite(single.get("revenue", {}).get(key))
            op = _finite(single.get("operating_income", {}).get(key))
            if rev and op is not None and rev != 0:
                return f"{op / rev * 100.0:.2f}%", YELLOW
            return "—", MUTED
        if kind == "eps":
            e = _finite(single.get("eps", {}).get(key))
            if e is None:
                return "—", MUTED
            return f"{e:.2f}元", YELLOW
        return "—", MUTED

    n_metrics = len(metrics)
    gap = 10
    usable = h - y0 - 50
    block_h = (usable - gap) // 2
    label_w = 200

    for bi, block in enumerate(blocks):
        top = y0 + 4 + bi * (block_h + gap)
        box = (12, top, W - 12, top + block_h)
        _draw_grid_rect(draw, box, outline=GRID, width=1)
        n_col = max(1, len(block)) if block else 4
        cell_w = (box[2] - box[0] - label_w) / 4.0
        # 直格線（固定 4 欄）
        draw.line(
            (box[0] + label_w, box[1], box[0] + label_w, box[3]),
            fill=GRID,
            width=1,
        )
        for ci in range(1, 4):
            x = box[0] + label_w + int(ci * cell_w)
            draw.line((x, box[1], x, box[3]), fill=GRID, width=1)

        row_h = (box[3] - box[1]) / n_metrics
        for mi, (lab, kind) in enumerate(metrics):
            yy = int(box[1] + mi * row_h)
            if mi > 0:
                draw.line((box[0], yy, box[2], yy), fill=GRID, width=1)
            ty = yy + max(2, int((row_h - 22) / 2))
            # 白＝表頭期別列；黃＝指標標籤（對齊 HT 黃標）
            lab_col = WHITE if mi == 0 else YELLOW
            _draw_left(draw, (box[0] + 10, ty), lab, f_h if mi == 0 else f_c, lab_col)
            for ci, q in enumerate(block):
                text, col = cell(q, kind)
                cx_r = box[0] + label_w + int((ci + 1) * cell_w) - 12
                _draw_right(draw, cx_r, ty, text, f_c, col)

    _draw_left(
        draw,
        (16, h - 40),
        pack.get("omit") or "",
        f_note,
        AMBER,
    )
    _draw_left(
        draw,
        (16, h - 22),
        "單季＝累計差分（缺前期不上）｜來源官方綜合損益｜估值≠買訊",
        f_note,
        MUTED,
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
