# -*- coding: utf-8 -*-
"""價值投資三圖：對齊轟天雷「表格式」可讀性（黑底／黃標／青格／紅漲青跌）。

只吃官方庫／OpenAPI 真數。
- 負債比／ROE／每股參考淨值 ← OpenAPI 資產負債 t187ap07（由官方合計欄算出）
- 除息／現金股利 ← 庫內 ex_rights（TWT49U 官方）
- 股東會 ← company_events（t187ap41）
- 應收／存貨週轉、業務比重、長期負債權益比（需長期借款明細）→ OpenAPI 彙總無欄，顯示 —
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


# 轟天雷語彙色（對齊截圖像素抽樣，不是螢光青）
BG = (0, 0, 0)
GRID = (112, 160, 160)  # 灰青格（HT 實測主色）
YELLOW = (255, 255, 0)
WHITE = (255, 255, 255)
GREEN = (0, 200, 0)  # 公司框
RED = (255, 0, 0)  # 正％／頁碼
CYAN = (0, 220, 220)  # 負％（略亮於格線以便閱讀）
MUTED = (160, 160, 160)
AMBER = (255, 200, 60)

# 對齊 HT 顯示寬（截圖約 1140–1440）：用 1440 畫布＝2880 視網膜的一半
# 話筒縮圖接近 1:1，格線 1px 不會被 Telegram 糊掉；比例與 2880 版相同
# 字用粗體無襯線＋列中錨點（PIL 預設基線會讓字沉底）
W = 1440
H_OVERVIEW = 820
H_MONTHLY = 720
H_QUARTERLY = 720
HT_LABEL_W = 241
HT_COL_W = 299
HT_ROW_H = 32
HT_HEADER_H = 28
HT_PAD = 4
HT_BODY_FONT = 28  # 字高／列高 ≈0.84
HT_NOTE_FONT = 14
HT_GRID_W = 1


def _font(size: int, *, bold: bool = True):
    """全部粗體（使用者鎖）；襯線優先＋橫向壓窄逼近 HT 瘦高字。"""
    from PIL import ImageFont

    size = int(size)
    # 一律優先 Bold；無 Bold 檔才退 Regular
    cands = [
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    for path in cands:
        try:
            return ImageFont.truetype(path, size=size, index=0)
        except Exception:
            continue
    from industry_card import _card_font

    return _card_font(size, bold=True)


def _text_w(font, text: str) -> int:
    return int(font.getlength(str(text or "")))


# HT 字偏「瘦高」：橫向壓到 0.82（無明體字檔時用變形逼近）
HT_CONDENSE = 0.82


def _paste_condensed(
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    font,
    fill,
    *,
    anchor: str = "lm",
) -> None:
    """畫 condensed 字：先渲 RGBA 再橫向壓窄貼上（對齊 HT 瘦高字感）。"""
    s = str(text or "")
    if not s:
        return
    # 量原始 bbox
    try:
        bbox = font.getbbox(s)
    except Exception:
        bbox = (0, 0, int(font.getlength(s)), int(getattr(font, "size", 16)))
    l, t, r, b = bbox
    pad = 2
    tw = max(1, r - l + pad * 2)
    th = max(1, b - t + pad * 2)
    tmp = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((pad - l, pad - t), s, font=font, fill=fill)
    cw = max(1, int(tw * HT_CONDENSE))
    tmp = tmp.resize((cw, th), Image.Resampling.LANCZOS)
    # 依 anchor 算貼上位置（相對 xy）
    ax, ay = xy
    # 水平
    if "l" in anchor:
        px = int(ax)
    elif "r" in anchor:
        px = int(ax) - cw
    else:
        px = int(ax) - cw // 2
    # 垂直：m＝中、t＝頂
    if "m" in anchor and "t" not in anchor:
        py = int(ay) - th // 2
    elif "b" in anchor:
        py = int(ay) - th
    else:
        py = int(ay)
    # draw 所屬 image
    base = draw.im if hasattr(draw, "im") else None
    img = getattr(draw, "_image", None)
    if img is None:
        # Pillow ImageDraw 內部持有 image
        img = draw._image  # type: ignore[attr-defined]
    img.paste(tmp, (px, py), tmp)


def _draw_left(
    draw: ImageDraw.ImageDraw, xy, text: str, font, fill, *, anchor: str = "lm"
) -> None:
    """預設 lm＝列中左對齊（表格字）；頂列改傳 anchor='lt'。"""
    _paste_condensed(draw, xy, text, font, fill, anchor=anchor)


def _draw_right(
    draw: ImageDraw.ImageDraw,
    x_right: int,
    y: int,
    text: str,
    font,
    fill,
    *,
    anchor: str = "rm",
) -> None:
    """預設 rm＝列中右對齊。"""
    _paste_condensed(draw, (x_right, y), text, font, fill, anchor=anchor)


def _draw_center(
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    text: str,
    font,
    fill,
    *,
    anchor: str = "mm",
) -> None:
    _paste_condensed(draw, (cx, y), text, font, fill, anchor=anchor)


def _row_mid_y(row_top: int, row_h: int = HT_ROW_H) -> int:
    """列垂直中線：搭配 anchor lm/rm 讓字真正置中（避免 PIL 基線沉底）。"""
    return int(row_top + row_h / 2)


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


def _openapi_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }


def _load_company_profile(sid: str) -> Dict[str, Any]:
    """證交所 t187ap03／櫃買對應：有抓到才上，失敗回空。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        urls = (
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        )
        for url in urls:
            try:
                resp = requests.get(url, headers=_openapi_headers(), timeout=45)
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
                        or item.get("CompanyAbbreviation")
                        or item.get("CompanyName")
                        or sid
                    ).strip(),
                    "name_full": str(
                        item.get("公司名稱") or item.get("CompanyName") or ""
                    ).strip(),
                    "name_en": str(
                        item.get("英文簡稱")
                        or item.get("英文通訊地址")
                        or item.get("EnglishAbbreviation")
                        or ""
                    ).strip(),
                    "chairman": str(
                        item.get("董事長") or item.get("Chairman") or ""
                    ).strip(),
                    "gm": str(
                        item.get("總經理") or item.get("GeneralManager") or ""
                    ).strip(),
                    "founded": str(item.get("成立日期") or "").strip(),
                    "phone": str(item.get("總機電話") or "").strip(),
                    "fax": str(item.get("傳真機號碼") or "").strip(),
                    "address": str(
                        item.get("住址") or item.get("Address") or ""
                    ).strip(),
                    "capital": capital,
                    "shares": shares,
                    "par": str(item.get("普通股每股面額") or "").strip(),
                    "published": str(
                        item.get("出表日期") or item.get("Date") or ""
                    ).strip(),
                    "source": "t187ap03",
                }
    except Exception:
        return empty
    return empty


def _load_balance_sheet(sid: str) -> Dict[str, Any]:
    """OpenAPI 資產負債彙總 t187ap07：負債比／ROE 用官方合計欄；無應收／存貨明細。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        urls = (
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci",
        )
        for url in urls:
            try:
                resp = requests.get(url, headers=_openapi_headers(), timeout=45)
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
                assets = _finite(item.get("資產總計"))
                liab = _finite(item.get("負債總計"))
                equity = _finite(item.get("權益總計"))
                equity_p = _finite(item.get("歸屬於母公司業主之權益合計"))
                ncl = _finite(item.get("非流動負債"))
                book = _finite(item.get("每股參考淨值"))
                capital_k = _finite(item.get("股本"))  # 千元
                year = item.get("年度")
                season = item.get("季別")
                try:
                    # 民國年 → 西元
                    y_i = int(str(year).strip())
                    if y_i < 1911:
                        y_i += 1911
                except (TypeError, ValueError):
                    y_i = None
                try:
                    s_i = int(str(season).strip())
                except (TypeError, ValueError):
                    s_i = None
                debt_pct = None
                if assets and liab is not None and assets != 0:
                    debt_pct = liab / assets * 100.0
                ncl_eq_pct = None
                if equity and ncl is not None and equity != 0:
                    ncl_eq_pct = ncl / equity * 100.0
                return {
                    "year": y_i,
                    "season": s_i,
                    "assets": assets,
                    "liabilities": liab,
                    "equity": equity,
                    "equity_parent": equity_p,
                    "noncurrent_liab": ncl,
                    "book_nav": book,
                    "capital_yi": (capital_k / 1e5) if capital_k is not None else None,
                    # 股本欄千元 → 億：/1e5
                    "debt_ratio_pct": debt_pct,
                    "ncl_equity_pct": ncl_eq_pct,
                    "published": str(
                        item.get("出表日期") or item.get("Date") or ""
                    ).strip(),
                    "source": "t187ap07",
                }
    except Exception:
        return empty
    return empty


def _load_agm_event(sid: str, db_path: str) -> Dict[str, Any]:
    """股東會：company_events（t187ap41 等官方）。"""
    out: Dict[str, Any] = {}
    if not db_path or not os.path.isfile(db_path):
        return out
    try:
        con = sqlite3.connect(db_path, timeout=15.0)
        try:
            row = con.execute(
                """
                SELECT event_date, kind, title, source
                FROM company_events
                WHERE stock_id=? AND (kind LIKE '%會%' OR title LIKE '%會%')
                ORDER BY REPLACE(CAST(event_date AS TEXT),'-','') DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
        finally:
            con.close()
        if not row:
            return out
        return {
            "date": _ymd(row[0]),
            "kind": str(row[1] or "").strip(),
            "title": str(row[2] or "").strip(),
            "source": str(row[3] or "").strip(),
        }
    except Exception:
        return out


def _load_official_dividend(sid: str, db_path: str) -> Dict[str, Any]:
    """最近一筆官方除息（TWT49U）；啟發式不上。"""
    out: Dict[str, Any] = {}
    if not db_path or not os.path.isfile(db_path):
        return out
    try:
        con = sqlite3.connect(db_path, timeout=15.0)
        try:
            row = con.execute(
                """
                SELECT ex_date, kind, right_plus_div, source, updated_at
                FROM ex_rights
                WHERE stock_id=?
                  AND kind IN ('息','權息')
                  AND IFNULL(source,'') NOT LIKE 'heuristic%'
                ORDER BY REPLACE(CAST(ex_date AS TEXT),'-','') DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
        finally:
            con.close()
        if not row:
            return out
        return {
            "ex_date": _ymd(row[0]),
            "kind": str(row[1] or "").strip(),
            "cash_div": _finite(row[2]),
            "source": str(row[3] or "").strip(),
            "updated_at": str(row[4] or "").strip(),
        }
    except Exception:
        return out


def _load_income_parent_ni(sid: str) -> Dict[str, Any]:
    """OpenAPI 綜合損益：取「淨利歸屬於母公司業主」（ROE 用；≠合計淨利）。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        urls = (
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
        )
        for url in urls:
            try:
                resp = requests.get(url, headers=_openapi_headers(), timeout=45)
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
                ni_p = _finite(
                    item.get("淨利（淨損）歸屬於母公司業主")
                    or item.get("淨利(淨損)歸屬於母公司業主")
                )
                ni = _finite(item.get("本期淨利（淨損）") or item.get("本期淨利(淨損)"))
                return {
                    "ni_parent": ni_p,
                    "ni_total": ni,
                    "published": str(
                        item.get("出表日期") or item.get("Date") or ""
                    ).strip(),
                    "source": "t187ap06",
                }
    except Exception:
        return empty
    return empty


def _roe_from_pack(
    quarterly: Sequence[Dict[str, Any]],
    bs: Dict[str, Any],
    *,
    ni_parent: Optional[float] = None,
) -> Optional[float]:
    """ROE＝該季累計「淨利歸母」／「母公司權益」。對齊 HT 總覽（非年化）。"""
    eq = _finite(bs.get("equity_parent")) or _finite(bs.get("equity"))
    if eq is None or eq == 0:
        return None
    ni = _finite(ni_parent)
    if ni is None:
        y, s = bs.get("year"), bs.get("season")
        for q in quarterly or ():
            try:
                if int(q["year"]) == int(y) and int(q["season"]) == int(s):
                    ni = _finite(q.get("net_income"))
                    break
            except (KeyError, TypeError, ValueError):
                continue
    if ni is None:
        return None
    return ni / eq * 100.0


def _stamp_roc_day(raw: Any) -> str:
    """出表／估值日 → 民國 yy/mm/dd；六碼出表日期也吃。"""
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(s) == 7:  # 1151121
        try:
            return f"{int(s[:3]):03d}/{s[3:5]}/{s[5:7]}"
        except ValueError:
            return s
    if len(s) == 8:
        return _roc_ymd(s)
    return str(raw or "").strip()


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
        "balance": {},
        "dividend": {},
        "agm": {},
        "roe_pct": None,
        "monthly": [],
        "quarterly": [],
        "single": {},
        "sources": {},
        "note": "",
        "omit": "應收／存貨週轉、業務比重、長期借款明細、會計年度月：OpenAPI 彙總無欄 → —",
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
            SELECT date, pe, pb, dividend_yield, source, updated_at
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
    balance = _load_balance_sheet(sid)
    income_ni = _load_income_parent_ni(sid)
    dividend = _load_official_dividend(sid, path)
    agm = _load_agm_event(sid, path)
    roe_pct = (
        _roe_from_pack(
            quarterly, balance, ni_parent=income_ni.get("ni_parent")
        )
        if balance
        else None
    )
    # 每股淨值優先官方資產負債「每股參考淨值」
    if _finite(balance.get("book_nav")) is not None:
        book = _finite(balance.get("book_nav"))

    m_asof = ""
    if monthly:
        m_asof = str(monthly[0].get("yyyymm") or "")
    q_asof = ""
    if quarterly:
        try:
            q_asof = f"{int(quarterly[0]['year'])}Q{int(quarterly[0]['season'])}"
        except (KeyError, TypeError, ValueError):
            q_asof = ""

    sources = {
        "valuation_date": _ymd(valuation.get("date")),
        "valuation_updated": str(valuation.get("updated_at") or ""),
        "valuation_source": str(valuation.get("source") or ""),
        "company_published": str(company.get("published") or ""),
        "balance_published": str(balance.get("published") or ""),
        "balance_season": (
            f"{balance.get('year')}Q{balance.get('season')}"
            if balance.get("year") and balance.get("season")
            else ""
        ),
        "monthly_asof": m_asof,
        "quarterly_asof": q_asof,
        "dividend_ex": dividend.get("ex_date") or "",
        "dividend_source": dividend.get("source") or "",
        "agm_date": agm.get("date") or "",
        "agm_source": agm.get("source") or "",
        "income_published": str(income_ni.get("published") or ""),
    }

    ok = bool(valuation or monthly or quarterly or balance)
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
            "updated_at": str(valuation.get("updated_at") or ""),
        },
        "close": close,
        "book_from_pb": book,
        "company": company,
        "balance": balance,
        "dividend": dividend,
        "agm": agm,
        "roe_pct": roe_pct,
        "monthly": monthly,
        "quarterly": quarterly,
        "single": {
            "eps": eps_single,
            "revenue": rev_single,
            "operating_income": op_single,
            "non_operating": non_single,
            "gross_profit": gp_single,
        },
        "sources": sources,
        "note": "" if ok else "尚無官方本益／月營收／季報",
        "omit": empty["omit"],
    }


def _draw_grid_rect(
    draw: ImageDraw.ImageDraw,
    box,
    *,
    fill=None,
    outline=GRID,
    width: int = HT_GRID_W,
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
    """頂列：對齊 HT 高度；黃品牌＋白公司＋白標題＋白單位＋紅頁碼。"""
    f = _font(16)
    f_brand = _font(16)
    brand = "WayneBot"
    y = 6
    _draw_left(draw, (8, y), brand, f_brand, YELLOW, anchor="lt")
    bx = 8 + _text_w(f_brand, brand) + 6
    _draw_left(draw, (bx, y), f"{name}{sid}", f, WHITE, anchor="lt")
    _draw_center(draw, canvas_w // 2, y, title, f, WHITE, anchor="mt")
    unit_s = f"單位：{unit}"
    page_s = str(page)
    gap = 10
    total_r = _text_w(f, unit_s) + gap + _text_w(f, page_s)
    rx = canvas_w - 10 - total_r
    _draw_left(draw, (rx, y), unit_s, f, WHITE, anchor="lt")
    _draw_left(
        draw, (rx + _text_w(f, unit_s) + gap, y), page_s, f, RED, anchor="lt"
    )
    # 頂列底細線（HT 表頭分隔）
    draw.line(
        (8, HT_HEADER_H - 2, canvas_w - 8, HT_HEADER_H - 2),
        fill=GRID,
        width=HT_GRID_W,
    )
    return HT_HEADER_H


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
    """對齊轟天雷「公司基本面總覽」：綠框公司卡（雙欄）＋底比率；字級／列距同季報密度。"""
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
    bs = pack.get("balance") or {}
    div = pack.get("dividend") or {}
    agm = pack.get("agm") or {}
    src = pack.get("sources") or {}
    q0 = (pack.get("quarterly") or [None])[0]
    f_lab = _font(HT_BODY_FONT)
    f_val = _font(HT_BODY_FONT)
    f_small = _font(HT_NOTE_FONT)
    row_h = HT_ROW_H

    # 上框：公司（綠細框、雙欄）
    n_co = 8
    box1 = (0, y0 + HT_PAD, W - 1, y0 + HT_PAD + n_co * row_h)
    draw.rectangle(box1, outline=GREEN, width=HT_GRID_W)
    mid_x = W // 2
    draw.line((mid_x, box1[1], mid_x, box1[3]), fill=GREEN, width=HT_GRID_W)

    founded = _roc_ymd(co.get("founded")) or "—"
    phone = _fmt_phone(co.get("phone")) or ""
    fax = _fmt_phone(co.get("fax")) or ""
    phone_s = "／".join(x for x in (phone, fax) if x) or "—"
    left_co = [
        ("股票名稱", pack.get("name") or "—"),
        ("創立日期", founded),
        ("董事長", co.get("chairman") or "—"),
        ("電話", phone_s),
        ("中文全名", co.get("name_full") or pack.get("name") or "—"),
        ("英文全名", co.get("name_en") or "—"),
        ("公司地址", co.get("address") or "—"),
        ("業務比重", "—"),  # OpenAPI 無欄
    ]
    right_co = [
        ("股票代碼", pack.get("stock_id") or "—"),
        ("會計年度月份", "—"),  # t187ap03 無欄
        ("總經理", co.get("gm") or "—"),
        ("", ""),
        ("", ""),
        ("", ""),
        ("", ""),
        ("", ""),
    ]
    lab_w = 110
    for i, ((lab_l, v_l), (lab_r, v_r)) in enumerate(zip(left_co, right_co)):
        yy = box1[1] + i * row_h
        if i > 0:
            draw.line((0, yy, W - 1, yy), fill=GREEN, width=HT_GRID_W)
        ty = _row_mid_y(yy, row_h)
        if lab_l:
            _draw_left(draw, (8, ty), lab_l, f_lab, WHITE)
            _draw_left(draw, (8 + lab_w, ty), f"：{v_l}", f_val, YELLOW)
        if lab_r:
            _draw_left(draw, (mid_x + 8, ty), lab_r, f_lab, WHITE)
            _draw_left(draw, (mid_x + 8 + lab_w + 20, ty), f"：{v_r}", f_val, YELLOW)

    # 底：股東會／股利（左）＋獲利／估值（右）
    y2 = box1[3] + 20
    capital_yi = _finite(bs.get("capital_yi"))
    if capital_yi is None and _finite(co.get("capital")) is not None:
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

    agm_when = "—"
    if agm.get("date"):
        agm_when = _roc_ymd(agm["date"]) or "—"
    agm_place = co.get("address") or "—"
    if agm.get("title") and "號" in str(agm.get("title")):
        # title 常帶地址；有真地址列優先用公司住址
        pass
    ex_div = "—"
    if div.get("ex_date"):
        ex_div = _roc_ymd(div["ex_date"]) or "—"
    cash_div = (
        _fmt_m(div.get("cash_div"), digits=3)
        if _finite(div.get("cash_div")) is not None
        else "—"
    )
    debt = _finite(bs.get("debt_ratio_pct"))
    roe = _finite(pack.get("roe_pct"))
    book_nav = _finite(bs.get("book_nav")) or _finite(pack.get("book_from_pb"))

    left_bot = [
        ("股東大會地點", agm_place, YELLOW if agm_place != "—" else MUTED),
        ("股東大會時間", agm_when, GREEN if agm_when != "—" else MUTED),
        ("除權日期", "—", MUTED),  # 最近官方列為息；無權則不上假
        ("除息日期", ex_div, GREEN if ex_div != "—" else MUTED),
        ("盈配(元)", "—", MUTED),
        ("資配(元)", "—", MUTED),
        ("現金股利(元)", cash_div, YELLOW if cash_div != "—" else MUTED),
        (
            "股本(億)",
            _fmt_m(capital_yi) if capital_yi is not None else "—",
            YELLOW,
        ),
        (
            "每股淨值(元)",
            _fmt_m(book_nav, digits=2),
            YELLOW if book_nav is not None else MUTED,
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
        (
            "負債比率",
            f"{_fmt_pct(debt)}%" if debt is not None else "—",
            YELLOW if debt is not None else MUTED,
        ),
        # OpenAPI 彙總無「長期借款」明細；非流動／權益≠HT「長期負債權益比」→ 不上混名
        ("長期負債權益比", "—", MUTED),
        (
            "股東權益報酬率",
            f"{_fmt_pct(roe)}%" if roe is not None else "—",
            YELLOW if roe is not None else MUTED,
        ),
    ]
    lab_w2 = 140
    for i, (lab, v, col) in enumerate(left_bot):
        ty = _row_mid_y(y2 + i * row_h, row_h)
        _draw_left(draw, (8, ty), lab, f_lab, WHITE)
        _draw_left(
            draw,
            (8 + lab_w2, ty),
            f"：{v}",
            f_val,
            col if v != "—" else MUTED,
        )
    for i, (lab, v, col) in enumerate(right_bot):
        ty = _row_mid_y(y2 + i * row_h, row_h)
        _draw_left(draw, (mid_x + 8, ty), lab, f_lab, WHITE)
        _draw_left(
            draw,
            (mid_x + 8 + lab_w2 + 20, ty),
            f"：{v}",
            f_val,
            col if v != "—" else MUTED,
        )

    note = pack.get("omit") or ""
    # 來源＋更新時戳（台北語意的民國／西元日，標清欄位）
    stamp_bits = []
    if src.get("valuation_date"):
        stamp_bits.append(f"本益日{_stamp_roc_day(src['valuation_date'])}")
    if src.get("balance_published"):
        stamp_bits.append(f"資產負債出表{_stamp_roc_day(src['balance_published'])}")
    if src.get("balance_season"):
        stamp_bits.append(str(src["balance_season"]))
    if src.get("monthly_asof"):
        stamp_bits.append(f"月營收{src['monthly_asof']}")
    if src.get("quarterly_asof"):
        stamp_bits.append(f"季報{src['quarterly_asof']}")
    if src.get("dividend_ex"):
        stamp_bits.append(f"除息{_stamp_roc_day(src['dividend_ex'])}")
    stamp_line = "｜".join(stamp_bits) if stamp_bits else "來源時戳待同步"
    _draw_left(draw, (8, h - 28), note, f_small, AMBER, anchor="lt")
    _draw_left(
        draw,
        (8, h - 14),
        f"官方TWSE/TPEx｜{stamp_line}｜估值≠買訊",
        f_small,
        MUTED,
        anchor="lt",
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_monthly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「單月營收」：左 MoM、右 YoY；底季累計；字／格同季報密度。"""
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
    f_c = _font(HT_BODY_FONT)
    f_note = _font(HT_NOTE_FONT)
    row_h = HT_ROW_H
    months = list(pack.get("monthly") or [])
    show_n = 12
    show = months[:show_n]

    mid = W // 2
    table_top = y0 + HT_PAD
    # 底季累計：標題＋5 列
    q_rows = 5
    q_band = 20 + q_rows * row_h + 24
    table_bot = h - q_band
    # 左／右兩表；中縫 4px
    left_box = (0, table_top, mid - 2, table_bot)
    right_box = (mid + 2, table_top, W - 1, table_bot)

    def _paint_side(box, *, pct_lab: str, pct_key: str) -> None:
        x0, y_t, x1, y_b = box
        draw.rectangle(box, outline=GRID, width=HT_GRID_W)
        # 三欄：年月｜月營收｜比%
        c1 = x0 + int((x1 - x0) * 0.28)
        c2 = x0 + int((x1 - x0) * 0.62)
        draw.line((c1, y_t, c1, y_b), fill=GRID, width=HT_GRID_W)
        draw.line((c2, y_t, c2, y_b), fill=GRID, width=HT_GRID_W)
        # 表頭列
        head_bot = y_t + row_h
        draw.line((x0, head_bot, x1, head_bot), fill=GRID, width=HT_GRID_W)
        ty = _row_mid_y(y_t, row_h)
        _draw_left(draw, (x0 + 6, ty), "年月", f_c, WHITE)
        _draw_left(draw, (c1 + 6, ty), "月營收", f_c, WHITE)
        _draw_left(draw, (c2 + 6, ty), pct_lab, f_c, WHITE)
        for i, m in enumerate(show):
            yy = head_bot + i * row_h
            if yy + row_h > y_b:
                break
            draw.line((x0, yy, x1, yy), fill=GRID, width=HT_GRID_W)
            ty2 = _row_mid_y(yy, row_h)
            yyyymm = str(m.get("yyyymm") or "")
            lab = _month_label(yyyymm, index=i)
            rev_m = _million_from_k(m.get("revenue"))
            pct = _finite(m.get(pct_key))
            _draw_left(draw, (x0 + 6, ty2), lab, f_c, YELLOW)
            _draw_right(draw, c2 - 8, ty2, _fmt_m(rev_m), f_c, YELLOW)
            _draw_right(
                draw,
                x1 - 8,
                ty2,
                _fmt_pct(pct, signed=False),
                f_c,
                _pct_color(pct),
            )

    _paint_side(left_box, pct_lab="上月比%", pct_key="mom_pct")
    _paint_side(right_box, pct_lab="去年比%", pct_key="yoy_pct")

    # 底：季營收累計
    yq = table_bot + 4
    _draw_center(draw, W // 2, yq + 8, "季營收 (Q1-Q4 累計)", f_c, WHITE)
    yq += 20
    qs = list(pack.get("quarterly") or [])[:4]
    label_w = HT_LABEL_W
    col_w = HT_COL_W
    q_box_top = yq
    q_box_bot = yq + q_rows * row_h
    draw.rectangle((0, q_box_top, W - 1, q_box_bot), outline=GRID, width=HT_GRID_W)
    xs = [label_w] + [label_w + col_w * (i + 1) for i in range(4)]
    for x in xs:
        if x < W - 1:
            draw.line((x, q_box_top, x, q_box_bot), fill=GRID, width=HT_GRID_W)

    row_labs = ["", "營業收入", "營益率", "業外比率", "每股盈餘"]
    for ri, lab in enumerate(row_labs):
        yy = q_box_top + ri * row_h
        if ri > 0:
            draw.line((0, yy, W - 1, yy), fill=GRID, width=HT_GRID_W)
        ty = _row_mid_y(yy, row_h)
        if lab:
            _draw_left(draw, (6, ty), lab, f_c, WHITE)
        if not qs:
            continue
        for ci, q in enumerate(qs):
            cx_r = min(W - 4, label_w + col_w * (ci + 1) - 10)
            if ri == 0:
                _draw_right(
                    draw,
                    cx_r,
                    ty,
                    _roc_season(q["year"], q["season"]),
                    f_c,
                    WHITE,
                )
            elif ri == 1:
                _draw_right(
                    draw,
                    cx_r,
                    ty,
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
                _draw_right(draw, cx_r, ty, txt, f_c, YELLOW if txt != "—" else MUTED)
            elif ri == 3:
                rev = _finite(q.get("revenue"))
                non = _finite(q.get("non_operating"))
                txt = (
                    f"{(non / rev * 100.0):.2f}%"
                    if rev and non is not None and rev != 0
                    else "—"
                )
                _draw_right(draw, cx_r, ty, txt, f_c, YELLOW if txt != "—" else MUTED)
            elif ri == 4:
                e = _finite(q.get("eps"))
                txt = f"{_fmt_m(e)}元" if e is not None else "—"
                _draw_right(draw, cx_r, ty, txt, f_c, YELLOW if txt != "—" else MUTED)

    src = pack.get("sources") or {}
    m_asof = src.get("monthly_asof") or ""
    q_asof = src.get("quarterly_asof") or ""
    foot = "備註: 百萬元四捨五入。紅＝正成長、青＝負成長。估值≠買訊"
    if m_asof or q_asof:
        foot = f"月營收截至{m_asof or '—'}｜季報{q_asof or '—'}｜{foot}"
    _draw_left(draw, (8, h - 14), foot, f_note, MUTED, anchor="lt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_quarterly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「季營收(單季資料)」像素比例：2880×1490、標籤欄482、列距63、灰青細格。"""
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
    # 字級：原圖縮放實測字高／列高≈0.84 → 54/63；粗體無襯線
    f_c = _font(HT_BODY_FONT)
    f_note = _font(HT_NOTE_FONT)
    single = pack.get("single") or {}
    qs = list(pack.get("quarterly") or [])[:8]
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
            # HT 季報成長％＝淡黃（含負）；紅／青留給月營收比％
            return f"{g:.2f}%", YELLOW
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
            return _fmt_m(v), YELLOW
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
    label_w = HT_LABEL_W
    col_w = HT_COL_W
    row_h = HT_ROW_H
    # 兩大區塊：上4季＋下4季；區塊間雙細線（HT 實測）
    block_h = n_metrics * row_h
    gap_mid = 14
    gw = HT_GRID_W
    for bi, block in enumerate(blocks):
        top = y0 + HT_PAD + bi * (block_h + gap_mid)
        bot = top + block_h
        draw.rectangle((0, top, W - 1, bot), outline=GRID, width=gw)
        xs = [label_w] + [label_w + col_w * (i + 1) for i in range(4)]
        for x in xs:
            if x >= W - 1:
                continue
            draw.line((x, top, x, bot), fill=GRID, width=gw)
        for mi, (lab, kind) in enumerate(metrics):
            yy = top + mi * row_h
            if mi > 0:
                draw.line((0, yy, W - 1, yy), fill=GRID, width=gw)
            ty = _row_mid_y(yy, row_h)
            # HT：左欄標籤白字；數值黃（負成長／負業外＝青）
            _draw_left(draw, (6, ty), lab, f_c, WHITE)
            for ci in range(4):
                if ci >= len(block):
                    continue
                text, col = cell(block[ci], kind)
                cx_r = min(W - 4, label_w + col_w * (ci + 1) - 10)
                _draw_right(draw, cx_r, ty, text, f_c, col)
        if bi == 0:
            y_mid = bot + gap_mid // 2
            draw.line((0, y_mid - 2, W - 1, y_mid - 2), fill=GRID, width=gw)
            draw.line((0, y_mid + 2, W - 1, y_mid + 2), fill=GRID, width=gw)

    _draw_left(
        draw, (8, h - 28), pack.get("omit") or "", f_note, AMBER, anchor="lt"
    )
    src = pack.get("sources") or {}
    q_asof = src.get("quarterly_asof") or ""
    bs_pub = _stamp_roc_day(src.get("balance_published")) if src.get("balance_published") else ""
    bits = ["單季＝累計差分（缺前期不上）", "綜合損益官方"]
    if q_asof:
        bits.append(f"季報{q_asof}")
    if bs_pub:
        bits.append(f"資產負債出表{bs_pub}")
    bits.append("估值≠買訊")
    _draw_left(draw, (8, h - 14), "｜".join(bits), f_note, MUTED, anchor="lt")
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
