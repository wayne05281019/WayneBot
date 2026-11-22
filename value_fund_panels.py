# -*- coding: utf-8 -*-
"""價值投資三圖：對齊轟天雷「表格式」可讀性（黑底／黃標／青格／紅漲青跌）。

格線對齊 HT：只留外框／欄直欄／表頭下橫線；資料列之間不畫橫線；
總覽上框只綠外框、無內格與中線；下半無框。

只吃官方庫／OpenAPI 真數。
- 負債比／ROE／每股參考淨值／非流動負債÷權益 ← OpenAPI 資產負債 t187ap07
- 除息／現金股利 ← 庫內 ex_rights（TWT49U）；除權日另查 kind＝權／權息
- 股東會 ← company_events／t187ap41
- 會計年度月／長期借款／應收／存貨 ← mopsov 個股資產負債／綜合損益明細（t164sb03／04）
- 應收／存貨週轉＝官方營收或成本 ÷ 平均餘額（可年化）；業務比重若年報營運概況無機器可讀列才 —
- 月表右欄去年營收：先對去年同月列，缺則用官方 revenue_prev_year
季報明細圖用「單季」：累計列差分還原（與 expand_ytd_income_eps_to_single 同規則）。
排版：標籤欄寬依字實測，值欄不得壓標籤；footer 預留，空季塊不畫。
估值≠買訊；切入仍只認高低卡黃金買點。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

MOPS_BS_DETAIL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03"
MOPS_IS_DETAIL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb04"

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

# 話筒點開全螢幕＝橫向看（iPhone Pro Max 橫拿 ≈19.5:9＝2.17:1）
# 畫布對這個比例；像素夠大，點開打橫才清楚。格線 1px；字粗體＋列中錨點。
W = 2400
H_OVERVIEW = 1106  # 2400/2.17
H_MONTHLY = 1106
H_QUARTERLY = 1106
_HT_SCALE = W / 1440.0  # 相對舊 1440 版等比放大
HT_LABEL_W = int(round(241 * _HT_SCALE))
HT_COL_W = int(round(299 * _HT_SCALE))
HT_ROW_H = int(round(32 * _HT_SCALE))
HT_HEADER_H = int(round(28 * _HT_SCALE))
HT_PAD = max(4, int(round(4 * _HT_SCALE)))
HT_BODY_FONT = int(round(28 * _HT_SCALE))  # 字高／列高 ≈0.84
HT_NOTE_FONT = int(round(14 * _HT_SCALE))
HT_GRID_W = 1
# 滾動窗：月表左右各 N 列（最新在上）；季表單季 N 季（左新右舊，兩塊各 4）
HT_MONTHLY_ROWS = 12
HT_QUARTERLY_COLS = 8  # 需庫內至少 N 季累計列；缺前期成長％／欄位顯示 —


def _rolling_monthly(months: Sequence[Dict[str, Any]], n: int = HT_MONTHLY_ROWS):
    """最新→舊；只取前 n。右欄配對用全量 by_ym，不截斷對照年。"""
    return list(months or [])[: max(0, int(n))]


def _rolling_quarterly(quarters: Sequence[Dict[str, Any]], n: int = HT_QUARTERLY_COLS):
    """最新→舊；取前 n 季（畫面兩塊×4）。"""
    return list(quarters or [])[: max(0, int(n))]


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
# 標籤與「：值」之間最少空隙（壓窄後像素）
HT_LABEL_GAP = max(12, int(round(10 * _HT_SCALE)))
# 底註預留（兩行 note）；內容區不可壓進來
HT_FOOT_RESERVE = max(52, int(round(48 * _HT_SCALE)))


def _condensed_w(font, text: str) -> int:
    return max(1, int(_text_w(font, str(text or "")) * HT_CONDENSE))


def _kv_label_w(font, labels: Sequence[str], *, gap: int = HT_LABEL_GAP) -> int:
    """標籤欄寬＝最長標籤 condensed 寬＋gap；值從這之後起畫，不准壓字。"""
    mw = 0
    for lab in labels or ():
        s = str(lab or "")
        if s:
            mw = max(mw, _condensed_w(font, s))
    return int(mw + max(8, gap))


def _clip_text_to_width(font, text: str, max_w: int) -> str:
    """過長值截到 max_w（condensed）；末尾加…。不准互壓。"""
    s = str(text or "")
    if not s or max_w <= 0:
        return s
    if _condensed_w(font, s) <= max_w:
        return s
    ell = "…"
    ew = _condensed_w(font, ell)
    if max_w <= ew:
        return ell
    out = s
    while out and _condensed_w(font, out) + ew > max_w:
        out = out[:-1]
    return (out + ell) if out else ell


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


def _draw_plain(
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    font,
    fill,
    *,
    anchor: str = "lm",
) -> None:
    """底註／小字：不橫向壓窄，避免字距糊成一團。"""
    s = str(text or "")
    if not s:
        return
    draw.text(xy, s, font=font, fill=fill, anchor=anchor)


def _draw_left(
    draw: ImageDraw.ImageDraw,
    xy,
    text: str,
    font,
    fill,
    *,
    anchor: str = "lm",
    plain: bool = False,
) -> None:
    """預設 lm＝列中左對齊（表格字）；頂列改傳 anchor='lt'。"""
    if plain:
        _draw_plain(draw, xy, text, font, fill, anchor=anchor)
    else:
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
    """西元 YYYYMMDD；櫃買／OpenAPI 常給民國七碼（1150525）→ 轉西元。"""
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(s) == 7:
        try:
            y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:7])
            return f"{y:04d}{m:02d}{d:02d}"
        except ValueError:
            return ""
    return s[:8]


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
    """YYYYMMDD／民國七碼／YYYY-MM-DD → 民國 yy/mm/dd；缺則原字或空。"""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 7:
        try:
            return f"{int(digits[:3]):03d}/{digits[3:5]}/{digits[5:7]}"
        except ValueError:
            return str(raw or "").strip()
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
    """上市 t187ap03_L／櫃買 mopsfin_t187ap03_O／興櫃 mopsfin_t187ap03_R。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        urls = (
            ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "t187ap03_L"),
            (
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
                "t187ap03_O",
            ),
            (
                "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R",
                "t187ap03_R",
            ),
        )
        for url, src in urls:
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
                capital = _finite(
                    item.get("實收資本額")
                    or item.get("實收資本額(元)")
                    or item.get("Paidin.Capital.NTDollars")
                )
                shares = _finite(
                    item.get("已發行普通股數或TDR原股發行股數")
                    or item.get("已發行普通股數")
                    or item.get("IssueShares")
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
                        or item.get("Symbol")
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
                    "founded": str(
                        item.get("成立日期")
                        or item.get("DateOfIncorporation")
                        or ""
                    ).strip(),
                    "phone": str(
                        item.get("總機電話") or item.get("Telephone") or ""
                    ).strip(),
                    "fax": str(
                        item.get("傳真機號碼") or item.get("Fax") or ""
                    ).strip(),
                    "address": str(
                        item.get("住址") or item.get("Address") or ""
                    ).strip(),
                    "capital": capital,
                    "shares": shares,
                    "par": str(
                        item.get("普通股每股面額")
                        or item.get("ParValueOfCommonStock")
                        or ""
                    ).strip(),
                    "published": str(
                        item.get("出表日期") or item.get("Date") or ""
                    ).strip(),
                    "source": src,
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
    """股東會：只認常會／臨時會／股東會；不准把法說會當股東會。"""
    out: Dict[str, Any] = {}
    if not db_path or not os.path.isfile(db_path):
        return out
    try:
        con = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = con.execute(
                """
                SELECT event_date, kind, title, source
                FROM company_events
                WHERE stock_id=?
                ORDER BY REPLACE(CAST(event_date AS TEXT),'-','') DESC
                LIMIT 40
                """,
                (sid,),
            ).fetchall()
        finally:
            con.close()
        pick = None
        for row in rows or ():
            kind = str(row[1] or "").strip()
            title = str(row[2] or "").strip()
            blob = kind + title
            if "法說" in blob:
                continue
            if any(k in blob for k in ("常會", "臨時會", "股東會", "股東常會", "股東臨時會")):
                pick = row
                break
            if kind in ("常會", "臨時會"):
                pick = row
                break
        if not pick:
            return out
        place = ""
        title = str(pick[2] or "").strip()
        # t187ap41 標題常帶地點：常會 桃園…
        if " " in title:
            place = title.split(" ", 1)[-1].strip()
        return {
            "date": _ymd(pick[0]),
            "kind": str(pick[1] or "").strip(),
            "title": title,
            "place": place,
            "source": str(pick[3] or "").strip(),
        }
    except Exception:
        return out


def _mops_html(url: str, form: Dict[str, str]) -> str:
    from fundamentals import _decode_mops_html, _post_form

    return _decode_mops_html(_post_form(url, form)) or ""


def _mops_cell_num(raw: str) -> Optional[float]:
    s = (
        str(raw or "")
        .replace(",", "")
        .replace("%", "")
        .replace("＋", "+")
        .replace("−", "-")
        .replace("－", "-")
        .strip()
    )
    if s in ("", "-", "--", "—", "N/A", "null", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _parse_mops_kv_rows(html: str) -> List[Tuple[str, List[Optional[float]]]]:
    """t164sb0x 表格：會計項目｜數｜%｜數｜%… → (科目, 數值列)。"""
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows: List[List[str]] = []
            self._tr: Optional[List[str]] = None
            self._td: Optional[List[str]] = None

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self._tr = []
            elif tag in ("td", "th") and self._tr is not None:
                self._td = []

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self._tr is not None and self._td is not None:
                self._tr.append("".join(self._td).strip())
                self._td = None
            elif tag == "tr" and self._tr is not None:
                if any(self._tr):
                    self.rows.append(self._tr)
                self._tr = None

        def handle_data(self, data):
            if self._td is not None:
                self._td.append(data)

    p = _P()
    try:
        p.feed(html or "")
    except Exception:
        return []
    out: List[Tuple[str, List[Optional[float]]]] = []
    for cells in p.rows:
        if not cells:
            continue
        name = re.sub(r"\s+", "", cells[0] or "")
        nums: List[Optional[float]] = []
        for c in cells[1:]:
            # 跳過純％欄：若相鄰已有金額，％另格；一律試解析，失敗略過
            nums.append(_mops_cell_num(c))
        # 去掉夾在中間的佔比％（通常 <1000 且緊鄰大數）— 保留所有成功解析數，後續用位置取
        out.append((name, nums))
    return out


def _load_mops_statement_detail(
    sid: str, year: int, season: int, *, kind: str
) -> Dict[str, Any]:
    """個股 MOPS 明細：kind=bs→t164sb03；kind=is→t164sb04。"""
    empty: Dict[str, Any] = {}
    sid = str(sid or "").strip()
    if not sid or year < 1990 or season not in (1, 2, 3, 4):
        return empty
    url = MOPS_BS_DETAIL if kind == "bs" else MOPS_IS_DETAIL
    form = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "isnew": "false",
        "co_id": sid,
        "year": str(year - 1911),
        "season": str(int(season)),
    }
    try:
        html = _mops_html(url, form)
    except Exception:
        return empty
    if not html or "安全" in html[:500]:
        return empty
    fiscal_month: Optional[int] = None
    m = re.search(
        r"本公司採\s*([0-9]{0,2})\s*月制會計年度（?空白表曆年制）?",
        html.replace("(", "（").replace(")", "）"),
    )
    if not m:
        m = re.search(r"本公司採\s*([0-9]{0,2})\s*月制會計年度", html)
    if m:
        raw = (m.group(1) or "").strip()
        # 空白＝曆年制 → 12（報表自己寫的規則，不是猜）
        fiscal_month = int(raw) if raw.isdigit() else 12
    rows = _parse_mops_kv_rows(html)

    def find(*names: str) -> List[Optional[float]]:
        # 先精確／合計，再模糊；全空列（分類標題）跳過
        fuzzy: List[Optional[float]] = []
        for nm, nums in rows:
            if not any(v is not None for v in nums):
                continue
            for want in names:
                if nm == want or nm.endswith(want) or want in nm:
                    if "合計" in nm or nm == want:
                        return nums
                    if not fuzzy:
                        fuzzy = nums
        return fuzzy

    out: Dict[str, Any] = {
        "year": year,
        "season": season,
        "fiscal_month": fiscal_month,
        "source": "mopsov_t164sb03" if kind == "bs" else "mopsov_t164sb04",
    }
    if kind == "bs":
        # 欄：本期金額、%、上期／去年底、%、去年同期、%
        ar = find("應收帳款淨額", "應收帳款")
        notes = find("應收票據淨額", "應收票據")
        inv = find("存貨")
        lt = find("長期借款")
        eq = find("權益總計", "權益總額")
        out.update(
            {
                "ar_end": ar[0] if ar else None,
                "ar_prior_ye": ar[2] if len(ar) > 2 else None,
                "ar_prior_yoy": ar[4] if len(ar) > 4 else None,
                "notes_end": notes[0] if notes else None,
                "notes_prior_ye": notes[2] if len(notes) > 2 else None,
                "inv_end": inv[0] if inv else None,
                "inv_prior_ye": inv[2] if len(inv) > 2 else None,
                "inv_prior_yoy": inv[4] if len(inv) > 4 else None,
                "lt_loan": lt[0] if lt else None,
                "equity": eq[0] if eq else None,
            }
        )
    else:
        # 綜合損益：本季、%、去年同季、%、本年累計、%、去年累計、%
        rev = find("營業收入合計", "營業收入")
        cogs = find("營業成本合計", "營業成本")
        non = find("營業外收入及支出合計", "營業外收入及支出")
        out.update(
            {
                "rev_q": rev[0] if rev else None,
                "rev_ytd": rev[4] if len(rev) > 4 else None,
                "cogs_q": cogs[0] if cogs else None,
                "cogs_ytd": cogs[4] if len(cogs) > 4 else None,
                "non_q": non[0] if non else None,
                "non_ytd": non[4] if len(non) > 4 else None,
            }
        )
    return out


def _avg2(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (a + b) / 2.0


def _recv_total(ar: Optional[float], notes: Optional[float]) -> Optional[float]:
    if ar is None and notes is None:
        return None
    return float(ar or 0.0) + float(notes or 0.0)


def _turn_times(
    flow: Optional[float], avg_bal: Optional[float], *, season: int, annualize: bool
) -> Optional[float]:
    if flow is None or avg_bal is None or avg_bal == 0:
        return None
    t = flow / abs(avg_bal)
    if annualize and season in (1, 2, 3):
        t *= 4.0 / float(season)
    return round(t, 2)


def _load_mops_business_mix(sid: str) -> Dict[str, Any]:
    """主要經營業務：mopsov t05st03（公司基本資料）。有機器可讀列才填。"""
    empty: Dict[str, Any] = {}
    sid = str(sid or "").strip()
    if not sid:
        return empty
    try:
        html = _mops_html(
            "https://mopsov.twse.com.tw/mops/web/ajax_t05st03",
            {
                "encodeURIComponent": "1",
                "step": "1",
                "firstin": "1",
                "off": "1",
                "queryName": "co_id",
                "inpuType": "co_id",
                "TYPEK": "all",
                "co_id": sid,
            },
        )
    except Exception:
        return empty
    if not html or "主要經營業務" not in html:
        return empty
    m = re.search(
        r"主要經營業務</th>\s*<td[^>]*>(.*?)</td>",
        html,
        flags=re.I | re.S,
    )
    if not m:
        return empty
    raw = m.group(1) or ""
    parts = [
        re.sub(r"\s+", "", p)
        for p in re.split(r"<br\s*/?>|\n|、|／|/", raw, flags=re.I)
        if re.sub(r"<[^>]+>", "", p).strip()
    ]
    clean = [re.sub(r"<[^>]+>", "", p).strip() for p in parts if p]
    clean = [c for c in clean if c and c not in ("-", "--", "—")]
    if not clean:
        return empty
    text = "／".join(clean)
    return {"text": text, "parts": clean, "source": "mopsov_t05st03"}


_MOPS_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS mops_fund_extra_cache (
    stock_id TEXT NOT NULL,
    asof_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_ymd TEXT NOT NULL,
    PRIMARY KEY (stock_id, asof_key)
)
"""


def _taipei_ymd() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")


def _turns_to_json(d: Dict[Tuple[int, int], float]) -> Dict[str, float]:
    return {f"{y}:{s}": float(v) for (y, s), v in (d or {}).items()}


def _turns_from_json(d: Any) -> Dict[Tuple[int, int], float]:
    out: Dict[Tuple[int, int], float] = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        try:
            ys, ss = str(k).split(":", 1)
            fv = _finite(v)
            if fv is None:
                continue
            out[(int(ys), int(ss))] = float(fv)
        except (TypeError, ValueError):
            continue
    return out


def _mops_extra_cache_get(
    db_path: str, sid: str, asof_key: str, ymd: str
) -> Optional[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        import json

        con = sqlite3.connect(db_path, timeout=15.0)
        try:
            con.execute(_MOPS_EXTRA_DDL)
            row = con.execute(
                """
                SELECT payload FROM mops_fund_extra_cache
                WHERE stock_id=? AND asof_key=? AND fetched_ymd=?
                """,
                (sid, asof_key, ymd),
            ).fetchone()
        finally:
            con.close()
        if not row:
            return None
        raw = json.loads(row[0])
        if not isinstance(raw, dict):
            return None
        return {
            "fiscal_month": raw.get("fiscal_month"),
            "lt_loan_equity_pct": _finite(raw.get("lt_loan_equity_pct")),
            "ar_turn": _turns_from_json(raw.get("ar_turn")),
            "inv_turn": _turns_from_json(raw.get("inv_turn")),
            "non_op_q": _turns_from_json(raw.get("non_op_q")),
            "non_op_ytd": _turns_from_json(raw.get("non_op_ytd")),
            "business_mix": raw.get("business_mix"),
            "source": str(raw.get("source") or "") + ",cache",
        }
    except Exception:
        return None


def _mops_extra_cache_put(
    db_path: str, sid: str, asof_key: str, ymd: str, payload: Dict[str, Any]
) -> None:
    if not db_path:
        return
    try:
        import json

        blob = json.dumps(
            {
                "fiscal_month": payload.get("fiscal_month"),
                "lt_loan_equity_pct": payload.get("lt_loan_equity_pct"),
                "ar_turn": _turns_to_json(payload.get("ar_turn") or {}),
                "inv_turn": _turns_to_json(payload.get("inv_turn") or {}),
                "non_op_q": _turns_to_json(payload.get("non_op_q") or {}),
                "non_op_ytd": _turns_to_json(payload.get("non_op_ytd") or {}),
                "business_mix": payload.get("business_mix"),
                "source": payload.get("source") or "",
            },
            ensure_ascii=False,
        )
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        con = sqlite3.connect(db_path, timeout=30.0)
        try:
            con.execute(_MOPS_EXTRA_DDL)
            con.execute(
                """
                INSERT OR REPLACE INTO mops_fund_extra_cache
                (stock_id, asof_key, payload, fetched_ymd)
                VALUES (?,?,?,?)
                """,
                (sid, asof_key, blob, ymd),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        return


def _load_mops_fund_extras(
    sid: str,
    quarters: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
) -> Dict[str, Any]:
    """補轟天雷有、OpenAPI 彙總沒有的欄：會計年度月／長期借款比／應收存貨週轉。

    季報兩塊共 8 季都抓；同日台北快取，話筒不准每次重打十次 MOPS。
    """
    out: Dict[str, Any] = {
        "fiscal_month": None,
        "lt_loan_equity_pct": None,
        "ar_turn": {},  # (y,s) -> float
        "inv_turn": {},
        "non_op_q": {},  # 單季營業外（mopsov 本季欄）
        "non_op_ytd": {},  # 累計營業外（寫回 quarterly_income 用）
        "business_mix": None,
        "source": "",
    }
    if os.environ.get("WAYNE_SKIP_MOPS_DETAIL", "").strip() in ("1", "true", "yes"):
        return out
    qs_raw = list(quarters or [])[:8]
    if not qs_raw:
        return out
    keys: List[Tuple[int, int]] = []
    for q in qs_raw:
        try:
            keys.append((int(q["year"]), int(q["season"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not keys:
        return out
    asof_key = "v2:" + ",".join(f"{y}Q{s}" for y, s in keys)
    ymd = _taipei_ymd()
    cached = _mops_extra_cache_get(db_path, sid, asof_key, ymd) if db_path else None
    if cached and (cached.get("ar_turn") or cached.get("fiscal_month") is not None):
        return cached

    sources: List[str] = []
    bs_by: Dict[Tuple[int, int], Dict[str, Any]] = {}
    # 由舊到新：同年第 N 季可吃到已抓的 N-1
    for y, s in sorted(keys):
        bs = _load_mops_statement_detail(sid, y, s, kind="bs")
        time.sleep(0.2)
        inc = _load_mops_statement_detail(sid, y, s, kind="is")
        time.sleep(0.2)
        if bs:
            bs_by[(y, s)] = bs
            sources.append(str(bs.get("source") or ""))
        if inc:
            sources.append(str(inc.get("source") or ""))
            nq = _finite(inc.get("non_q"))
            ny = _finite(inc.get("non_ytd"))
            if nq is not None:
                out["non_op_q"][(y, s)] = nq
            if ny is not None:
                out["non_op_ytd"][(y, s)] = ny
            elif s == 1 and nq is not None:
                # Q1 累計＝本季
                out["non_op_ytd"][(y, s)] = nq
        if not bs:
            continue
        end_recv = _recv_total(bs.get("ar_end"), bs.get("notes_end"))
        end_inv = _finite(bs.get("inv_end"))
        if s == 1:
            start_recv = _recv_total(bs.get("ar_prior_ye"), bs.get("notes_prior_ye"))
            start_inv = _finite(bs.get("inv_prior_ye"))
        else:
            prev = bs_by.get((y, s - 1))
            if not prev:
                prev = _load_mops_statement_detail(sid, y, s - 1, kind="bs")
                time.sleep(0.2)
                if prev:
                    bs_by[(y, s - 1)] = prev
            start_recv = (
                _recv_total(prev.get("ar_end"), prev.get("notes_end"))
                if prev
                else None
            )
            start_inv = _finite(prev.get("inv_end")) if prev else None
        rev_q = _finite((inc or {}).get("rev_q"))
        cogs_q = _finite((inc or {}).get("cogs_q"))
        ar_t = _turn_times(
            rev_q, _avg2(end_recv, start_recv), season=s, annualize=True
        )
        inv_t = _turn_times(
            cogs_q, _avg2(end_inv, start_inv), season=s, annualize=True
        )
        if ar_t is not None:
            out["ar_turn"][(y, s)] = ar_t
        if inv_t is not None:
            out["inv_turn"][(y, s)] = inv_t

    # 會計年度月／長期借款：最新一季
    for y, s in keys:  # keys 已是季報新→舊順序
        bs = bs_by.get((y, s))
        if not bs:
            continue
        if out["fiscal_month"] is None and bs.get("fiscal_month") is not None:
            out["fiscal_month"] = bs.get("fiscal_month")
        if out["lt_loan_equity_pct"] is None:
            lt = _finite(bs.get("lt_loan"))
            eq = _finite(bs.get("equity"))
            if lt is not None and eq and eq != 0:
                out["lt_loan_equity_pct"] = round(lt / eq * 100.0, 2)
        if out["fiscal_month"] is not None and out["lt_loan_equity_pct"] is not None:
            break

    out["source"] = ",".join(sorted({x for x in sources if x}))
    if db_path:
        _mops_extra_cache_put(db_path, sid, asof_key, ymd, out)
    return out


def _load_official_dividend(sid: str, db_path: str) -> Dict[str, Any]:
    """最近一筆官方除息（TWT49U）＋除權日＋股利分派（t187ap45 盈配／資配）；啟發式不上。"""
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
            # 除權日：只認官方「權」或「權息」列；純息列不算除權
            right = con.execute(
                """
                SELECT ex_date, kind, source
                FROM ex_rights
                WHERE stock_id=?
                  AND kind IN ('權','權息')
                  AND IFNULL(source,'') NOT LIKE 'heuristic%'
                ORDER BY REPLACE(CAST(ex_date AS TEXT),'-','') DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
        finally:
            con.close()
        if row:
            out = {
                "ex_date": _ymd(row[0]),
                "kind": str(row[1] or "").strip(),
                "cash_div": _finite(row[2]),
                "source": str(row[3] or "").strip(),
                "updated_at": str(row[4] or "").strip(),
            }
        if right:
            out["ex_right_date"] = _ymd(right[0])
            out["ex_right_kind"] = str(right[1] or "").strip()
            out["ex_right_source"] = str(right[2] or "").strip()
    except Exception:
        out = {}
    # 盈配／資配：證交所 t187ap45（元／股）；0 也是真數要顯示
    try:
        import requests

        resp = requests.get(
            "https://openapi.twse.com.tw/v1/opendata/t187ap45_L",
            headers=_openapi_headers(),
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            for item in data:
                code = str(item.get("公司代號") or "").strip()
                if code != sid:
                    continue
                earn = _finite(item.get("股東配發-盈餘轉增資配股(元/股)"))
                cap = _finite(item.get("股東配發-資本公積轉增資配股(元/股)"))
                cash_earn = _finite(item.get("股東配發-盈餘分配之現金股利(元/股)"))
                out["stock_div_earn"] = earn  # 盈配
                out["stock_div_capital"] = cap  # 資配
                out["div_year"] = str(item.get("股利年度") or "").strip()
                out["div_allocate_source"] = "t187ap45_L"
                if out.get("cash_div") is None and cash_earn is not None:
                    out["cash_div"] = cash_earn
                break
    except Exception:
        pass
    return out


def _load_agm_openapi(sid: str) -> Dict[str, Any]:
    """股東會地點／日期：上市 t187ap41_L／櫃買 t187ap41_O（無時刻欄）。"""
    empty: Dict[str, Any] = {}
    try:
        import requests

        urls = (
            ("https://openapi.twse.com.tw/v1/opendata/t187ap41_L", "t187ap41_L"),
            ("https://www.tpex.org.tw/openapi/v1/t187ap41_O", "t187ap41_O"),
        )
        for url, src in urls:
            try:
                resp = requests.get(url, headers=_openapi_headers(), timeout=45)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                code = str(item.get("公司代號") or "").strip()
                if code != sid:
                    continue
                return {
                    "date": _ymd(item.get("開會日期")),
                    "kind": str(item.get("股東常(臨時)會") or "").strip(),
                    "place": str(item.get("開會地點") or "").strip(),
                    "title": str(item.get("開會地點") or "").strip(),
                    "source": src,
                }
    except Exception:
        return empty
    return empty


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
        "mops_extra": {},
        "monthly": [],
        "quarterly": [],
        "single": {},
        "sources": {},
        "note": "",
        "omit": "",
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
        # 月表右欄要對去年同月：至少 24 月；多抓利於回補窗
        monthly = list_monthly_revenue(path, sid, limit=36)
        quarterly = list_quarterly_income(path, sid, limit=16)
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
    agm_o = _load_agm_openapi(sid)
    if agm_o:
        # OpenAPI 有開會地點；庫列可補日期。時刻欄官方沒有 → 不上假 09:00
        # 不准用 OpenAPI 蓋掉已選到的常會（庫列優先於誤抓）
        if agm_o.get("place") and not agm.get("place"):
            agm["place"] = agm_o["place"]
        elif agm_o.get("place") and agm.get("kind") in ("常會", "臨時會", ""):
            agm["place"] = agm_o["place"]
        if agm_o.get("date") and not agm.get("date"):
            agm["date"] = agm_o["date"]
        if agm_o.get("kind") and not agm.get("kind"):
            agm["kind"] = agm_o["kind"]
        if not agm.get("source"):
            agm["source"] = agm_o.get("source") or ""
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

    mops_extra = _load_mops_fund_extras(sid, quarterly, db_path=path)
    biz = _load_mops_business_mix(sid)
    if biz.get("text"):
        mops_extra["business_mix"] = biz.get("text")
        src_biz = str(biz.get("source") or "")
        if src_biz:
            mops_extra["source"] = (
                (mops_extra.get("source") + "," + src_biz).strip(",")
                if mops_extra.get("source")
                else src_biz
            )

    # 庫內業外 NULL（上櫃 OpenAPI 常漏）→ mopsov 本季／累計補畫面，並 COALESCE 寫回
    non_q_map = mops_extra.get("non_op_q") or {}
    non_ytd_map = mops_extra.get("non_op_ytd") or {}
    if non_q_map:
        for k, v in non_q_map.items():
            if non_single.get(k) is None and _finite(v) is not None:
                non_single[k] = float(v)
    if non_ytd_map and path:
        try:
            from fundamentals import _upsert_income, ensure_fundamentals_tables

            ensure_fundamentals_tables(path)
            heal_rows: List[Dict[str, Any]] = []
            by_qs = {
                (int(q["year"]), int(q["season"])): q for q in (quarterly or [])
            }
            for (y, s), ny in non_ytd_map.items():
                q = by_qs.get((y, s))
                if not q:
                    continue
                if _finite(q.get("non_operating")) is not None:
                    continue
                if _finite(ny) is None:
                    continue
                heal_rows.append(
                    {
                        "stock_id": sid,
                        "year": y,
                        "season": s,
                        "stock_name": q.get("stock_name") or name,
                        "market": q.get("market") or market or "",
                        "revenue": q.get("revenue"),
                        "cogs": q.get("cogs"),
                        "gross_profit": q.get("gross_profit"),
                        "gross_margin_pct": q.get("gross_margin_pct"),
                        "operating_income": q.get("operating_income"),
                        "non_operating": float(ny),
                        "net_income": q.get("net_income"),
                        "eps": q.get("eps"),
                        "published_roc": q.get("published_roc") or "",
                    }
                )
                q["non_operating"] = float(ny)
            if heal_rows:
                con_h = sqlite3.connect(path, timeout=30.0)
                try:
                    _upsert_income(con_h, heal_rows)
                    con_h.commit()
                finally:
                    con_h.close()
        except Exception:
            pass

    omit_bits: List[str] = []
    if not mops_extra.get("business_mix"):
        omit_bits.append("業務比重")
    if mops_extra.get("fiscal_month") is None:
        omit_bits.append("會計年度月")
    if not (mops_extra.get("ar_turn") or {}):
        omit_bits.append("應收週轉")
    if not (mops_extra.get("inv_turn") or {}):
        omit_bits.append("存貨週轉")
    omit = (
        ("缺欄＝" + "／".join(omit_bits) + "（官方無機器可讀）；非造假")
        if omit_bits
        else ""
    )

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
        "div_allocate_source": dividend.get("div_allocate_source") or "",
        "agm_date": agm.get("date") or "",
        "agm_source": agm.get("source") or "",
        "income_published": str(income_ni.get("published") or ""),
        "mops_extra": str(mops_extra.get("source") or ""),
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
        "mops_extra": mops_extra,
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
        "omit": omit,
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
    head_fs = max(16, int(round(16 * _HT_SCALE)))
    f = _font(head_fs)
    f_brand = _font(head_fs)
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
    # HT 頂列與表格之間無橫線；不另畫
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
    mx = pack.get("mops_extra") or {}
    src = pack.get("sources") or {}
    q0 = (pack.get("quarterly") or [None])[0]
    f_lab = _font(HT_BODY_FONT)
    f_val = _font(HT_BODY_FONT)
    f_small = _font(HT_NOTE_FONT)
    row_h = HT_ROW_H

    # 上框：公司（HT＝只綠外框，雙欄靠空白對齊，不畫內格／中線）
    n_co = 8
    box1 = (0, y0 + HT_PAD, W - 1, y0 + HT_PAD + n_co * row_h)
    draw.rectangle(box1, outline=GREEN, width=HT_GRID_W)
    mid_x = W // 2

    founded = _roc_ymd(co.get("founded")) or "—"
    phone = _fmt_phone(co.get("phone")) or "—"
    fax = _fmt_phone(co.get("fax")) or ""
    biz_mix = str(mx.get("business_mix") or "").strip() or "—"
    fiscal_m = mx.get("fiscal_month")
    fiscal_s = f"{int(fiscal_m)}月" if fiscal_m is not None else "—"
    left_co = [
        ("股票名稱", pack.get("name") or "—"),
        ("創立日期", founded),
        ("董事長", co.get("chairman") or "—"),
        ("電話", phone),
        ("中文全名", co.get("name_full") or pack.get("name") or "—"),
        ("英文全名", co.get("name_en") or "—"),
        ("公司地址", co.get("address") or "—"),
        ("業務比重", biz_mix),  # mopsov t05st03 主要經營業務
    ]
    right_co = [
        ("股票代碼", pack.get("stock_id") or "—"),
        ("會計年度月份", fiscal_s),  # mopsov 空白＝曆年制→12
        ("總經理", co.get("gm") or "—"),
        ("傳真", fax or "—"),  # HT：右欄＝傳真（標清楚，避免兩「電話」）
        ("", ""),
        ("", ""),
        ("", ""),
        ("", ""),
    ]
    lab_w = _kv_label_w(
        f_lab, [a for a, _ in left_co] + [a for a, _ in right_co if a]
    )
    # 值欄右界：左半不越 mid；右半不越畫布
    left_val_max = max(40, mid_x - 16 - (8 + lab_w))
    right_val_max = max(40, W - 16 - (mid_x + 8 + lab_w))
    for i, ((lab_l, v_l), (lab_r, v_r)) in enumerate(zip(left_co, right_co)):
        yy = box1[1] + i * row_h
        ty = _row_mid_y(yy, row_h)
        if lab_l:
            _draw_left(draw, (8, ty), lab_l, f_lab, WHITE)
            _draw_left(
                draw,
                (8 + lab_w, ty),
                f"：{_clip_text_to_width(f_val, v_l, left_val_max)}",
                f_val,
                YELLOW,
            )
        if lab_r:
            _draw_left(draw, (mid_x + 8, ty), lab_r, f_lab, WHITE)
            _draw_left(
                draw,
                (mid_x + 8 + lab_w, ty),
                f"：{_clip_text_to_width(f_val, v_r, right_val_max)}",
                f_val,
                YELLOW,
            )

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
        # OpenAPI／庫皆無開會時刻 → 只顯示日，不上假 09:00
        agm_when = _roc_ymd(agm["date"]) or "—"
    agm_place = (
        agm.get("place")
        or (agm.get("title") if agm.get("title") and "號" in str(agm.get("title")) else "")
        or co.get("address")
        or "—"
    )
    ex_div = "—"
    if div.get("ex_date"):
        ex_div = _roc_ymd(div["ex_date"]) or "—"
    ex_right = "—"
    if div.get("ex_right_date"):
        ex_right = _roc_ymd(div["ex_right_date"]) or "—"
    cash_div = (
        _fmt_m(div.get("cash_div"), digits=3)
        if _finite(div.get("cash_div")) is not None
        else "—"
    )
    # 盈配／資配：t187ap45 官方元／股（0 也顯示）
    earn_div = div.get("stock_div_earn")
    cap_div = div.get("stock_div_capital")
    earn_s = (
        _fmt_m(earn_div, digits=3) if _finite(earn_div) is not None else "—"
    )
    cap_s = _fmt_m(cap_div, digits=3) if _finite(cap_div) is not None else "—"
    debt = _finite(bs.get("debt_ratio_pct"))
    roe = _finite(pack.get("roe_pct"))
    book_nav = _finite(bs.get("book_nav")) or _finite(pack.get("book_from_pb"))
    ncl_eq = _finite(bs.get("ncl_equity_pct"))
    lt_eq = _finite(mx.get("lt_loan_equity_pct"))
    # 有 mopsov 長期借款明細 → 對齊 HT「長期借款／權益」；否則退 t187ap07 非流動負債／權益
    if lt_eq is not None:
        lev_lab, lev_val = "長期借款／權益", lt_eq
    else:
        lev_lab, lev_val = "非流動負債／權益", ncl_eq

    left_bot = [
        ("股東大會地點", agm_place, YELLOW if agm_place != "—" else MUTED),
        ("股東大會時間", agm_when, GREEN if agm_when != "—" else MUTED),
        ("除權日期", ex_right, GREEN if ex_right != "—" else MUTED),
        ("除息日期", ex_div, GREEN if ex_div != "—" else MUTED),
        ("盈配(元)", earn_s, YELLOW if earn_s != "—" else MUTED),
        ("資配(元)", cap_s, YELLOW if cap_s != "—" else MUTED),
        ("現金股利(元)", cash_div, YELLOW if cash_div != "—" else MUTED),
        (
            "股本(億)",
            _fmt_m(capital_yi) if capital_yi is not None else "—",
            YELLOW,
        ),
        (
            "每股淨值(元)",
            _fmt_m(book_nav, digits=2) if book_nav is not None else "—",
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
                f"{_fmt_m(eps0)} ({season0}Q)"
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
        (
            lev_lab,
            f"{_fmt_pct(lev_val)}%" if lev_val is not None else "—",
            YELLOW if lev_val is not None else MUTED,
        ),
        (
            "股東權益報酬率",
            f"{_fmt_pct(roe)}%" if roe is not None else "—",
            YELLOW if roe is not None else MUTED,
        ),
    ]
    lab_w2 = _kv_label_w(
        f_lab, [a for a, _v, _c in left_bot] + [a for a, _v, _c in right_bot]
    )
    left_val_max2 = max(40, mid_x - 16 - (8 + lab_w2))
    right_val_max2 = max(40, W - 16 - (mid_x + 8 + lab_w2))
    for i, (lab, v, col) in enumerate(left_bot):
        ty = _row_mid_y(y2 + i * row_h, row_h)
        _draw_left(draw, (8, ty), lab, f_lab, WHITE)
        _draw_left(
            draw,
            (8 + lab_w2, ty),
            f"：{_clip_text_to_width(f_val, v, left_val_max2)}",
            f_val,
            col if v != "—" else MUTED,
        )
    for i, (lab, v, col) in enumerate(right_bot):
        ty = _row_mid_y(y2 + i * row_h, row_h)
        _draw_left(draw, (mid_x + 8, ty), lab, f_lab, WHITE)
        _draw_left(
            draw,
            (mid_x + 8 + lab_w2, ty),
            f"：{_clip_text_to_width(f_val, v, right_val_max2)}",
            f_val,
            col if v != "—" else MUTED,
        )

    note = pack.get("omit") or ""
    # 來源＋更新時戳（台北語意的民國／西元日，標清欄位）；短句＋截斷防壓內容
    stamp_bits = []
    if src.get("valuation_date"):
        stamp_bits.append(f"本益{_stamp_roc_day(src['valuation_date'])}")
    if src.get("balance_published"):
        stamp_bits.append(f"資產負債{_stamp_roc_day(src['balance_published'])}")
    if src.get("monthly_asof"):
        stamp_bits.append(f"月{src['monthly_asof']}")
    if src.get("quarterly_asof"):
        stamp_bits.append(f"季{src['quarterly_asof']}")
    if src.get("dividend_ex"):
        stamp_bits.append(f"除息{_stamp_roc_day(src['dividend_ex'])}")
    stamp_line = "｜".join(stamp_bits) if stamp_bits else "來源時戳待同步"
    # 底註用 plain 字寬裁切（不套 condensed）
    def _plain_clip(s: str) -> str:
        t = str(s or "")
        max_w = W - 24
        if _text_w(f_small, t) <= max_w:
            return t
        while t and _text_w(f_small, t + "…") > max_w:
            t = t[:-1]
        return (t + "…") if t else "…"

    foot1 = _plain_clip(note)
    foot2 = _plain_clip(f"官方TWSE/TPEx｜{stamp_line}｜估值≠買訊")
    _draw_left(
        draw, (8, h - HT_FOOT_RESERVE + 8), foot1, f_small, AMBER, anchor="lt", plain=True
    )
    _draw_left(
        draw,
        (8, h - max(16, HT_FOOT_RESERVE // 2)),
        foot2,
        f_small,
        MUTED,
        anchor="lt",
        plain=True,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def _prev_year_yyyymm(yyyymm: str) -> str:
    s = str(yyyymm or "")
    if len(s) != 6 or not s.isdigit():
        return ""
    return f"{int(s[:4]) - 1}{s[4:]}"


def render_monthly_png(pack: Dict[str, Any], out_path: str) -> str:
    """對齊轟天雷「單月營收」：左＝今年（上月比）、右＝去年同月營收＋去年比%；底季累計。"""
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
    by_ym = {
        str(m.get("yyyymm") or ""): m
        for m in months
        if str(m.get("yyyymm") or "").isdigit() and len(str(m.get("yyyymm"))) == 6
    }
    show = _rolling_monthly(months, HT_MONTHLY_ROWS)

    mid = W // 2
    table_top = y0 + HT_PAD
    # 底季累計：標題列＋5 資料列；預留 footer 防壓
    q_rows = 5
    title_h = max(row_h, int(round(36 * _HT_SCALE)))
    q_band = title_h + q_rows * row_h + HT_FOOT_RESERVE
    table_bot = h - q_band
    # 左／右兩表；中縫 4px
    left_box = (0, table_top, mid - 2, table_bot)
    right_box = (mid + 2, table_top, W - 1, table_bot)

    def _paint_table(
        box,
        *,
        pct_lab: str,
        rows: Sequence[Tuple[str, Optional[float], Optional[float]]],
    ) -> None:
        """rows: (年月標籤, 月營收百萬, 比%)。
        HT：欄間直欄線＋表頭下橫線；資料列之間不畫橫線（靠列距分開）。
        數字右對齊於各欄右緣內縮，不准壓隔壁欄標。
        """
        x0, y_t, x1, y_b = box
        # 三欄：年月較窄、月營收較寬、比％中寬
        span = max(1, x1 - x0)
        c1 = x0 + int(span * 0.22)
        c2 = x0 + int(span * 0.62)
        draw.line((x0, y_t, x0, y_b), fill=GRID, width=HT_GRID_W)
        draw.line((x1, y_t, x1, y_b), fill=GRID, width=HT_GRID_W)
        draw.line((c1, y_t, c1, y_b), fill=GRID, width=HT_GRID_W)
        draw.line((c2, y_t, c2, y_b), fill=GRID, width=HT_GRID_W)
        head_bot = y_t + row_h
        draw.line((x0, head_bot, x1, head_bot), fill=GRID, width=HT_GRID_W)
        ty = _row_mid_y(y_t, row_h)
        _draw_center(draw, (x0 + c1) // 2, ty, "年月", f_c, WHITE)
        # 表頭置中於欄，避免「月營收」貼左、數字貼右看起來互壓
        _draw_center(draw, (c1 + c2) // 2, ty, "月營收", f_c, WHITE)
        _draw_center(draw, (c2 + x1) // 2, ty, pct_lab, f_c, WHITE)
        for i, (lab, rev_m, pct) in enumerate(rows):
            yy = head_bot + i * row_h
            if yy + row_h > y_b:
                break
            ty2 = _row_mid_y(yy, row_h)
            # 年月置中於欄；數字右對齊欄內縮 10px
            _draw_center(draw, (x0 + c1) // 2, ty2, lab, f_c, YELLOW)
            _draw_right(draw, c2 - 10, ty2, _fmt_m(rev_m), f_c, YELLOW)
            _draw_right(
                draw,
                x1 - 10,
                ty2,
                _fmt_pct(pct, signed=False),
                f_c,
                _pct_color(pct),
            )

    left_rows: List[Tuple[str, Optional[float], Optional[float]]] = []
    right_rows: List[Tuple[str, Optional[float], Optional[float]]] = []
    for i, m in enumerate(show):
        yyyymm = str(m.get("yyyymm") or "")
        left_rows.append(
            (
                _month_label(yyyymm, index=i),
                _million_from_k(m.get("revenue")),
                _finite(m.get("mom_pct")),
            )
        )
        # 右欄＝去年同月營收＋今年 yoy%；缺去年列時用官方 revenue_prev_year
        prev_ym = _prev_year_yyyymm(yyyymm)
        prev = by_ym.get(prev_ym) or {}
        prev_rev = _finite(prev.get("revenue"))
        if prev_rev is None:
            prev_rev = _finite(m.get("revenue_prev_year"))
        right_rows.append(
            (
                _month_label(prev_ym, index=i) if prev_ym else "—",
                _million_from_k(prev_rev),
                _finite(m.get("yoy_pct")),
            )
        )

    _paint_table(left_box, pct_lab="上月比%", rows=left_rows)
    _paint_table(right_box, pct_lab="去年比%", rows=right_rows)

    # 底：季營收累計（標題獨立一列，不准壓期別）
    yq = table_bot + 4
    _draw_center(draw, W // 2, yq + title_h // 2, "季營收 (Q1-Q4 累計)", f_c, WHITE)
    qs = _rolling_quarterly(pack.get("quarterly") or [], 4)
    row_labs = ["期別", "營業收入", "營益率", "業外比率", "每股盈餘"]
    label_w = max(HT_LABEL_W, _kv_label_w(f_c, row_labs))
    col_w = max(120, (W - label_w) // 4)
    q_box_top = yq + title_h
    q_box_bot = q_box_top + q_rows * row_h
    xs = [0, label_w] + [label_w + col_w * (i + 1) for i in range(4)]
    for x in xs:
        if x <= W - 1:
            draw.line((x, q_box_top, x, min(q_box_bot, h - HT_FOOT_RESERVE)), fill=GRID, width=HT_GRID_W)
    draw.line(
        (0, q_box_top + row_h, W - 1, q_box_top + row_h),
        fill=GRID,
        width=HT_GRID_W,
    )

    for ri, lab in enumerate(row_labs):
        yy = q_box_top + ri * row_h
        if yy + row_h > h - HT_FOOT_RESERVE:
            break
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
    foot = "百萬四捨五入；紅＋／青−；估值≠買訊"
    if m_asof or q_asof:
        foot = f"月{m_asof or '—'}｜季{q_asof or '—'}｜{foot}"
    foot_s = foot
    max_w = W - 24
    if _text_w(f_note, foot_s) > max_w:
        while foot_s and _text_w(f_note, foot_s + "…") > max_w:
            foot_s = foot_s[:-1]
        foot_s = (foot_s + "…") if foot_s else "…"
    _draw_left(
        draw,
        (8, h - max(16, HT_FOOT_RESERVE // 2)),
        foot_s,
        f_note,
        MUTED,
        anchor="lt",
        plain=True,
    )
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
    f_c = _font(HT_BODY_FONT)
    f_note = _font(HT_NOTE_FONT)
    single = pack.get("single") or {}
    qs = _rolling_quarterly(pack.get("quarterly") or [], HT_QUARTERLY_COLS)
    # 只畫有資料的塊；空塊不畫格線（防底部空白＋footer 互壓）
    blocks = [b for b in (qs[:4], qs[4:8]) if b]
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
            return (_fmt_m(v) if v is not None else "—"), (
                YELLOW if v is not None else MUTED
            )
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
            return f"{g:.2f}%", YELLOW
        if kind == "op":
            v = _million_from_k(single.get("operating_income", {}).get(key))
            return (_fmt_m(v) if v is not None else "—"), (
                YELLOW if v is not None else MUTED
            )
        if kind == "non":
            raw = single.get("non_operating", {}).get(key)
            if raw is None and q.get("non_operating") is None:
                return "—", MUTED
            v = _million_from_k(raw if raw is not None else q.get("non_operating"))
            if v is None:
                return "—", MUTED
            return _fmt_m(v), YELLOW
        if kind in ("ar", "inv"):
            mx = pack.get("mops_extra") or {}
            turns = mx.get("ar_turn" if kind == "ar" else "inv_turn") or {}
            v = turns.get(key)
            if v is None:
                return "—", MUTED
            return f"{v:.2f}", YELLOW
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
    label_w = max(HT_LABEL_W, _kv_label_w(f_c, [a for a, _ in metrics]))
    col_w = max(120, (W - label_w) // 4)
    gap_mid = max(10, int(round(10 * _HT_SCALE)))
    gw = HT_GRID_W
    # 依剩餘高度自適列高：兩塊＋footer 塞得下才畫；否則縮列高
    avail = max(200, h - y0 - HT_PAD - HT_FOOT_RESERVE)
    n_blocks = max(1, len(blocks))
    row_h = HT_ROW_H
    need = n_blocks * n_metrics * row_h + max(0, n_blocks - 1) * gap_mid
    if need > avail:
        row_h = max(
            int(round(22 * _HT_SCALE)),
            int((avail - max(0, n_blocks - 1) * gap_mid) / (n_blocks * n_metrics)),
        )
        f_c = _font(max(18, int(row_h * 0.82)))
        label_w = max(HT_LABEL_W, _kv_label_w(f_c, [a for a, _ in metrics]))
        col_w = max(120, (W - label_w) // 4)

    for bi, block in enumerate(blocks):
        block_h = n_metrics * row_h
        top = y0 + HT_PAD + bi * (block_h + gap_mid)
        bot = top + block_h
        if bot > h - HT_FOOT_RESERVE:
            break
        xs = [0, label_w] + [label_w + col_w * (i + 1) for i in range(4)]
        for x in xs:
            if x > W - 1:
                continue
            draw.line((x, top, x, bot), fill=GRID, width=gw)
        draw.line((0, top, W - 1, top), fill=GRID, width=gw)
        head_bot = top + row_h
        draw.line((0, head_bot, W - 1, head_bot), fill=GRID, width=gw)
        for mi, (lab, kind) in enumerate(metrics):
            yy = top + mi * row_h
            ty = _row_mid_y(yy, row_h)
            _draw_left(draw, (6, ty), lab, f_c, WHITE)
            for ci in range(4):
                if ci >= len(block):
                    continue
                text, col = cell(block[ci], kind)
                cx_r = min(W - 4, label_w + col_w * (ci + 1) - 10)
                _draw_right(draw, cx_r, ty, text, f_c, col)

    src = pack.get("sources") or {}
    q_asof = src.get("quarterly_asof") or ""
    bits = ["單季＝累計差分（缺前期不上）"]
    if q_asof:
        bits.append(f"季{q_asof}")
    bits.append("估值≠買訊")
    def _plain_clip_q(s: str) -> str:
        t = str(s or "")
        max_w = W - 24
        if _text_w(f_note, t) <= max_w:
            return t
        while t and _text_w(f_note, t + "…") > max_w:
            t = t[:-1]
        return (t + "…") if t else "…"

    foot1 = _plain_clip_q(pack.get("omit") or "")
    foot2 = _plain_clip_q("｜".join(bits))
    _draw_left(
        draw, (8, h - HT_FOOT_RESERVE + 8), foot1, f_note, AMBER, anchor="lt", plain=True
    )
    _draw_left(
        draw,
        (8, h - max(16, HT_FOOT_RESERVE // 2)),
        foot2,
        f_note,
        MUTED,
        anchor="lt",
        plain=True,
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
