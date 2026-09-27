"""
月營收 YoY/MoM 與季報毛利率：只吃證交所／櫃買官方 OpenAPI 最新一期快照。
歷史深度靠每次盤後寫入 SQLite 累積，不臆造公式、不抓第三方付費源。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

logger = logging.getLogger("WayneBot.Fundamentals")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

TWSE_MONTHLY = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_MONTHLY = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
TPEX_EMERGING_MONTHLY = "https://www.tpex.org.tw/openapi/v1/t187ap05_R"
TWSE_INCOME = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
TPEX_INCOME = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci"
# 公開資訊觀測站「已公告」月營收彙總（無驗證碼）。OpenAPI 月營收是全市場同一期，
# 10 號前仍停在上上月時，先公告的公司（例如緯穎 8 月）只出現在這份表。
# 興櫃月營收：櫃買 OpenAPI t187ap05_R（免驗證碼）。NAS rot／emg 彙總 404；個股頁要驗證碼不抓。
# 興櫃季報綜合損益尚無免驗證碼 OpenAPI；有月營收歷史就彙成季營收看兩年。
MOPS_NAS_MONTHLY = "https://mopsov.twse.com.tw/nas/t21/{ex}/t21sc03_{roc}_{month}_{kind}.html"


def _num(val) -> float:
    s = str(val if val is not None else "").replace(",", "").replace("%", "").replace("＋", "+").strip()
    if s in ("", "-", "--", "－", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def roc_period_to_yyyymm(raw: str) -> str:
    """11507 → 202607；民國年資料年月。"""
    s = str(raw or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 5:
        return f"{int(digits[:3]) + 1911}{digits[3:]}"
    if len(digits) == 6 and int(digits[:3]) < 200:
        return f"{int(digits[:3]) + 1911}{digits[3:]}"
    return digits[-6:] if len(digits) >= 6 else digits


def roc_year_to_ad(raw: str) -> int:
    n = int(_num(raw))
    return n + 1911 if n < 1911 else n


def ensure_fundamentals_tables(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_revenue (
            stock_id TEXT NOT NULL,
            yyyymm TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            revenue REAL DEFAULT 0,
            revenue_prev_month REAL DEFAULT 0,
            revenue_prev_year REAL DEFAULT 0,
            mom_pct REAL DEFAULT 0,
            yoy_pct REAL DEFAULT 0,
            ytd_revenue REAL DEFAULT 0,
            ytd_prev_year REAL DEFAULT 0,
            ytd_yoy_pct REAL DEFAULT 0,
            published_roc TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (stock_id, yyyymm)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS quarterly_income (
            stock_id TEXT NOT NULL,
            year INTEGER NOT NULL,
            season INTEGER NOT NULL,
            stock_name TEXT DEFAULT '',
            market TEXT DEFAULT '',
            revenue REAL DEFAULT 0,
            cogs REAL DEFAULT 0,
            gross_profit REAL DEFAULT 0,
            gross_margin_pct REAL DEFAULT 0,
            operating_income REAL DEFAULT 0,
            net_income REAL DEFAULT 0,
            eps REAL DEFAULT 0,
            published_roc TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (stock_id, year, season)
        );
        """
    )
    conn.commit()
    conn.close()


def _get(url: str) -> list:
    last = None
    for i in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=40)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def _get_bytes(url: str) -> bytes:
    last = None
    for i in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=40)
            if getattr(resp, "status_code", 0) == 404:
                return b""
            resp.raise_for_status()
            return resp.content or b""
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def _decode_mops_html(raw: bytes) -> str:
    for enc in ("cp950", "big5", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", "replace")


def previous_calendar_yyyymm(today_ymd: str = "") -> str:
    raw = str(today_ymd or "").replace("-", "")[:8]
    if len(raw) == 8 and raw.isdigit():
        y, m = int(raw[:4]), int(raw[4:6])
    else:
        from datetime import datetime

        now = datetime.now()
        y, m = now.year, now.month
    m -= 1
    if m <= 0:
        m = 12
        y -= 1
    return f"{y:04d}{m:02d}"


def mops_monthly_urls(yyyymm: str) -> List[Tuple[str, str]]:
    """上市／上櫃 × 本國／外國。kind 0=本國、1=外國（KY）。"""
    s = str(yyyymm or "").replace("-", "")[:6]
    if len(s) != 6 or not s.isdigit():
        return []
    roc = int(s[:4]) - 1911
    month = int(s[4:6])
    if roc < 1 or month < 1 or month > 12:
        return []
    out: List[Tuple[str, str]] = []
    for ex, market in (("sii", "TW"), ("otc", "TWO")):
        for kind in (0, 1):
            out.append(
                (
                    MOPS_NAS_MONTHLY.format(ex=ex, roc=roc, month=month, kind=kind),
                    market,
                )
            )
    return out


class _T21sc03Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: List[Tuple[str, List[str]]] = []
        self.industry = ""
        self._tr: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._tr = []
        elif tag in ("td", "th") and self._tr is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._tr is not None and self._cell is not None:
            text = "".join(self._cell).strip()
            self._tr.append(text)
            if tag == "th" and text.startswith("產業別："):
                self.industry = text.split("：", 1)[-1].strip()
            self._cell = None
        elif tag == "tr" and self._tr is not None:
            cells = self._tr
            self._tr = None
            if (
                cells
                and cells[0].isdigit()
                and len(cells[0]) in (4, 5, 6)
                and len(cells) >= 10
            ):
                self.rows.append((self.industry, cells))

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_t21sc03_html(html: str, yyyymm: str, market: str) -> List[Dict[str, Any]]:
    """公開資訊觀測站已公告月營收彙總表。金額單位千元，與 OpenAPI 相同。"""
    yyyymm = str(yyyymm or "").replace("-", "")[:6]
    if len(yyyymm) != 6:
        return []
    parser = _T21sc03Parser()
    parser.feed(html or "")
    out: List[Dict[str, Any]] = []
    for industry, cells in parser.rows:
        sid = cells[0]
        if sid in ("合計",):
            continue
        out.append(
            {
                "stock_id": sid,
                "yyyymm": yyyymm,
                "stock_name": cells[1],
                "market": market,
                "industry": industry,
                "revenue": _num(cells[2]),
                "revenue_prev_month": _num(cells[3]),
                "revenue_prev_year": _num(cells[4]),
                "mom_pct": _num(cells[5]),
                "yoy_pct": _num(cells[6]),
                "ytd_revenue": _num(cells[7]),
                "ytd_prev_year": _num(cells[8]),
                "ytd_yoy_pct": _num(cells[9]),
                "published_roc": "",
            }
        )
    return out


def fetch_mops_monthly_filings(yyyymm: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for url, market in mops_monthly_urls(yyyymm):
        try:
            html = _decode_mops_html(_get_bytes(url))
            if not html.strip():
                continue
            parsed = parse_t21sc03_html(html, yyyymm, market)
            rows.extend(parsed)
            logger.info("MOPS 月營收 %s %s 解析 %s 筆", yyyymm, market, len(parsed))
        except Exception as e:
            msg = f"mops {yyyymm} {market}: {e}"
            errors.append(msg)
            logger.warning(msg)
    return rows, errors


def parse_monthly_row(item: dict, market: str) -> Optional[Dict[str, Any]]:
    sid = str(item.get("公司代號") or item.get("SecuritiesCompanyCode") or "").strip()
    if not sid:
        return None
    yyyymm = roc_period_to_yyyymm(item.get("資料年月") or "")
    if len(yyyymm) != 6:
        return None
    return {
        "stock_id": sid,
        "yyyymm": yyyymm,
        "stock_name": str(item.get("公司名稱") or item.get("CompanyName") or sid).strip(),
        "market": market,
        "industry": str(item.get("產業別") or "").strip(),
        "revenue": _num(item.get("營業收入-當月營收")),
        "revenue_prev_month": _num(item.get("營業收入-上月營收")),
        "revenue_prev_year": _num(item.get("營業收入-去年當月營收")),
        "mom_pct": _num(item.get("營業收入-上月比較增減(%)")),
        "yoy_pct": _num(item.get("營業收入-去年同月增減(%)")),
        "ytd_revenue": _num(item.get("累計營業收入-當月累計營收")),
        "ytd_prev_year": _num(item.get("累計營業收入-去年累計營收")),
        "ytd_yoy_pct": _num(item.get("累計營業收入-前期比較增減(%)")),
        "published_roc": str(item.get("出表日期") or "").strip(),
    }


def parse_income_row(item: dict, market: str) -> Optional[Dict[str, Any]]:
    sid = str(item.get("公司代號") or item.get("SecuritiesCompanyCode") or "").strip()
    if not sid:
        return None
    year = roc_year_to_ad(item.get("年度") or item.get("Year") or 0)
    season = int(_num(item.get("季別") or item.get("Season") or 0))
    if year < 1990 or season not in (1, 2, 3, 4):
        return None
    revenue = _num(item.get("營業收入"))
    gp = _num(item.get("營業毛利（毛損）淨額") or item.get("營業毛利（毛損）"))
    margin = round(gp / revenue * 100.0, 2) if revenue else 0.0
    return {
        "stock_id": sid,
        "year": year,
        "season": season,
        "stock_name": str(item.get("公司名稱") or item.get("CompanyName") or sid).strip(),
        "market": market,
        "revenue": revenue,
        "cogs": _num(item.get("營業成本")),
        "gross_profit": gp,
        "gross_margin_pct": margin,
        "operating_income": _num(item.get("營業利益（損失）")),
        "net_income": _num(item.get("本期淨利（淨損）") or item.get("淨利（淨損）歸屬於母公司業主")),
        "eps": _num(item.get("基本每股盈餘（元）")),
        "published_roc": str(item.get("出表日期") or item.get("Date") or "").strip(),
    }


def _upsert_monthly(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.cursor()
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO monthly_revenue (
                stock_id, yyyymm, stock_name, market, industry, revenue, revenue_prev_month,
                revenue_prev_year, mom_pct, yoy_pct, ytd_revenue, ytd_prev_year, ytd_yoy_pct,
                published_roc, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(stock_id, yyyymm) DO UPDATE SET
                stock_name=excluded.stock_name, market=excluded.market,
                industry=CASE WHEN excluded.industry!='' THEN excluded.industry ELSE monthly_revenue.industry END,
                revenue=excluded.revenue, revenue_prev_month=excluded.revenue_prev_month,
                revenue_prev_year=excluded.revenue_prev_year, mom_pct=excluded.mom_pct,
                yoy_pct=excluded.yoy_pct, ytd_revenue=excluded.ytd_revenue,
                ytd_prev_year=excluded.ytd_prev_year, ytd_yoy_pct=excluded.ytd_yoy_pct,
                published_roc=excluded.published_roc, updated_at=excluded.updated_at;
            """,
            (
                r["stock_id"], r["yyyymm"], r["stock_name"], r["market"], r["industry"],
                r["revenue"], r["revenue_prev_month"], r["revenue_prev_year"], r["mom_pct"],
                r["yoy_pct"], r["ytd_revenue"], r["ytd_prev_year"], r["ytd_yoy_pct"],
                r["published_roc"], now,
            ),
        )
        n += 1
    return n


def _upsert_income(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.cursor()
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO quarterly_income (
                stock_id, year, season, stock_name, market, revenue, cogs, gross_profit,
                gross_margin_pct, operating_income, net_income, eps, published_roc, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(stock_id, year, season) DO UPDATE SET
                stock_name=excluded.stock_name, market=excluded.market, revenue=excluded.revenue,
                cogs=excluded.cogs, gross_profit=excluded.gross_profit,
                gross_margin_pct=excluded.gross_margin_pct, operating_income=excluded.operating_income,
                net_income=excluded.net_income, eps=excluded.eps,
                published_roc=excluded.published_roc, updated_at=excluded.updated_at;
            """,
            (
                r["stock_id"], r["year"], r["season"], r["stock_name"], r["market"],
                r["revenue"], r["cogs"], r["gross_profit"], r["gross_margin_pct"],
                r["operating_income"], r["net_income"], r["eps"], r["published_roc"], now,
            ),
        )
        n += 1
    return n


def sync_fundamentals(db_path: str = None) -> Dict[str, Any]:
    path = db_path or get_db_path()
    ensure_fundamentals_tables(path)
    monthly_rows: List[Dict[str, Any]] = []
    income_rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for url, market, kind in (
        (TWSE_MONTHLY, "TW", "monthly"),
        (TPEX_MONTHLY, "TWO", "monthly"),
        (TPEX_EMERGING_MONTHLY, "EM", "monthly"),
        (TWSE_INCOME, "TW", "income"),
        (TPEX_INCOME, "TWO", "income"),
    ):
        try:
            payload = _get(url)
            if kind == "monthly":
                monthly_rows.extend([p for p in (parse_monthly_row(x, market) for x in payload) if p])
            else:
                income_rows.extend([p for p in (parse_income_row(x, market) for x in payload) if p])
            logger.info("%s %s 解析 %s 筆", market, kind, len(payload))
        except Exception as e:
            msg = f"{market}/{kind}: {e}"
            errors.append(msg)
            logger.warning(msg)

    conn = sqlite3.connect(path)
    m_n = _upsert_monthly(conn, monthly_rows)
    i_n = _upsert_income(conn, income_rows)
    conn.commit()
    filing_month = previous_calendar_yyyymm()
    mops_n = 0
    try:
        mops_rows, mops_err = fetch_mops_monthly_filings(filing_month)
        errors.extend(mops_err)
        if mops_rows:
            mops_n = _upsert_monthly(conn, mops_rows)
            conn.commit()
            monthly_rows.extend(mops_rows)
            logger.info("已公告月營收 %s 寫入 %s 筆（OpenAPI 尚未換期也要每天對）", filing_month, mops_n)
    except Exception as e:
        msg = f"mops {filing_month}: {e}"
        errors.append(msg)
        logger.warning(msg)
    months = sorted({r["yyyymm"] for r in monthly_rows})
    quarters = sorted({f"{r['year']}Q{r['season']}" for r in income_rows})
    m_max = conn.execute("SELECT COUNT(*), MAX(yyyymm) FROM monthly_revenue").fetchone()
    q_max = conn.execute("SELECT COUNT(*), MAX(year), MAX(season) FROM quarterly_income").fetchone()
    conn.close()
    stats = {
        "monthly_rows": m_n,
        "mops_filing_month": filing_month,
        "mops_rows": mops_n,
        "income_rows": i_n,
        "errors": errors,
        "months_in_feed": months[-3:],
        "quarters_in_feed": quarters[-4:],
        "db_monthly": int(m_max[0] or 0),
        "db_latest_month": m_max[1] or "",
        "db_income": int(q_max[0] or 0),
        "db_latest_quarter": f"{q_max[1]}Q{q_max[2]}" if q_max[1] else "",
        "note": "OpenAPI 月營收是全市場同一期快照（含櫃買興櫃 t187ap05_R）；已先公告的上市櫃另從公開資訊觀測站 NAS 彙總表補入。季報 OpenAPI 僅上市櫃最新一期；興櫃無免驗證碼季報源，有月歷史就彙成季。",
    }
    logger.info("基本面同步完成 %s", stats)
    return stats


def get_latest_monthly(db_path: str, stock_id: str) -> Optional[Dict[str, Any]]:
    ensure_fundamentals_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM monthly_revenue WHERE stock_id=? ORDER BY yyyymm DESC LIMIT 1",
        (str(stock_id).strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_income(db_path: str, stock_id: str) -> Optional[Dict[str, Any]]:
    ensure_fundamentals_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM quarterly_income WHERE stock_id=? ORDER BY year DESC, season DESC LIMIT 1",
        (str(stock_id).strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_monthly_revenue(db_path: str, stock_id: str, *, limit: int = 36) -> List[Dict[str, Any]]:
    """近 N 個月營收列（新→舊）。興櫃靠每天同步 t187ap05_R 累積。"""
    ensure_fundamentals_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM monthly_revenue
        WHERE stock_id=?
        ORDER BY yyyymm DESC
        LIMIT ?
        """,
        (str(stock_id).strip(), int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _yyyymm_to_quarter(yyyymm: str) -> Optional[Tuple[int, int]]:
    s = str(yyyymm or "").replace("-", "")[:6]
    if len(s) != 6 or not s.isdigit():
        return None
    y, m = int(s[:4]), int(s[4:6])
    if m < 1 or m > 12:
        return None
    return y, (m - 1) // 3 + 1


def quarterly_revenue_from_monthly(months: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """月營收合成季營收。三個月齊才算完整季；缺月不硬湊假數。"""
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for row in months or []:
        key = _yyyymm_to_quarter(str(row.get("yyyymm") or ""))
        if not key:
            continue
        buckets.setdefault(key, []).append(row)
    out: List[Dict[str, Any]] = []
    for (year, season), rows in sorted(buckets.items(), reverse=True):
        if len(rows) < 3:
            continue  # 未滿季不准當完整季營收
        rev = sum(float(r.get("revenue") or 0) for r in rows)
        out.append(
            {
                "year": year,
                "season": season,
                "revenue": rev,
                "months": sorted(str(r.get("yyyymm") or "") for r in rows),
                "complete": True,
            }
        )
    return out


def revenue_trend_label(pct: Optional[float], *, kind: str = "yoy") -> str:
    """營收增減白話標。kind=mom／yoy／qoq／yoy_q。不准發明假％。"""
    if pct is None:
        return "—"
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "—"
    if p != p:  # NaN
        return "—"
    prefix = {
        "mom": "較上月",
        "yoy": "較去年同月",
        "qoq": "較上季",
        "yoy_q": "較去年同季",
    }.get(kind, "較去年同月")
    if p >= 20:
        return f"{prefix}大增・越來越好"
    if p >= 5:
        return f"{prefix}改善"
    if p > -5:
        return f"{prefix}持平"
    if p > -20:
        return f"{prefix}走弱"
    return f"{prefix}大減"


def _fmt_signed_pct(pct) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "—"
    if p != p:
        return "—"
    return f"{p:+.1f}%"


def monthly_revenue_window_rows(months: List[Dict[str, Any]], *, limit: int = 12) -> List[Tuple[str, str]]:
    """近窗月營收表列（新→舊）：年月｜億｜月增%｜年增%｜累年增%｜狀態。一行一列。"""
    out: List[Tuple[str, str]] = []
    for i, m in enumerate((months or [])[: max(1, int(limit))]):
        yyyymm = str(m.get("yyyymm") or "")
        if len(yyyymm) >= 6:
            lab_m = f"{yyyymm[4:6]}月'{yyyymm[2:4]}"
        else:
            lab_m = yyyymm or "—"
        mom = m.get("mom_pct")
        yoy = m.get("yoy_pct")
        ytd = m.get("ytd_yoy_pct")
        try:
            mom_f = float(mom) if mom is not None else None
        except (TypeError, ValueError):
            mom_f = None
        try:
            yoy_f = float(yoy) if yoy is not None else None
        except (TypeError, ValueError):
            yoy_f = None
        status = "；".join(
            t
            for t in (
                revenue_trend_label(mom_f, kind="mom"),
                revenue_trend_label(yoy_f, kind="yoy"),
            )
            if t and t != "—"
        )
        val = (
            f"{lab_m}　{format_yi(m.get('revenue') or 0)}　"
            f"月增{_fmt_signed_pct(mom)}　年增{_fmt_signed_pct(yoy)}　"
            f"累年增{_fmt_signed_pct(ytd)}"
        )
        if status and i == 0:
            # 狀態只掛最新月，避免每列過長互壓
            val = f"{val}　{status}"
        lab = "月營收近窗" if i == 0 else f"月營收{i + 1}"
        out.append((lab, val))
    return out


def prior_income(db_path: str, latest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT * FROM quarterly_income
        WHERE stock_id=? AND (year < ? OR (year=? AND season < ?))
        ORDER BY year DESC, season DESC LIMIT 1
        """,
        (latest["stock_id"], latest["year"], latest["year"], latest["season"]),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _yi_from_thousand(amount_k: float) -> float:
    """官方金額單位是千元 → 億元。1 億元 = 100_000 千元。"""
    return float(amount_k or 0) / 100_000.0


def format_yi(amount_k: float, *, signed: bool = False, unit: bool = True) -> str:
    """千元金額改顯示為億元（例：1,146,434 千元 → 11.46億元）。"""
    v = _yi_from_thousand(amount_k)
    suffix = "億元" if unit else "億"
    if signed:
        return f"{v:+.2f}{suffix}"
    return f"{v:.2f}{suffix}"


def _mom_delta_k(m: Dict[str, Any]) -> float:
    rev = float(m.get("revenue") or 0)
    prev = float(m.get("revenue_prev_month") or 0)
    if prev > 0:
        return rev - prev
    pct = float(m.get("mom_pct") or 0)
    if abs(pct + 100.0) < 1e-9:
        return 0.0
    if pct:
        return rev - rev / (1.0 + pct / 100.0)
    return 0.0


def _yoy_delta_k(m: Dict[str, Any]) -> float:
    rev = float(m.get("revenue") or 0)
    prev = float(m.get("revenue_prev_year") or 0)
    if prev > 0:
        return rev - prev
    pct = float(m.get("yoy_pct") or 0)
    if abs(pct + 100.0) < 1e-9:
        return 0.0
    if pct:
        return rev - rev / (1.0 + pct / 100.0)
    return 0.0


def _ytd_yoy_delta_k(m: Dict[str, Any]) -> float:
    ytd = float(m.get("ytd_revenue") or 0)
    prev = float(m.get("ytd_prev_year") or 0)
    if prev > 0:
        return ytd - prev
    pct = float(m.get("ytd_yoy_pct") or 0)
    if abs(pct + 100.0) < 1e-9:
        return 0.0
    if pct:
        return ytd - ytd / (1.0 + pct / 100.0)
    return 0.0


def glance_fundamentals_plain(stock_id: str, db_path: str = None) -> list:
    """[(標籤, 值), ...] 給第一眼圖／文字共用。金額一律億元，不再顯示 MoM/YoY％。"""
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    try:
        from universe import card_asset_type, etf_card_kind_label, is_etf_asset

        asset = card_asset_type(sid, path)
        if is_etf_asset(asset, sid):
            rows = []
            kind = etf_card_kind_label(asset, sid)
            if kind:
                rows.append(("類型", kind))
            try:
                from official_snapshots import etf_div_plain_rows

                rows.extend(etf_div_plain_rows(sid, path))
            except Exception:
                pass
            if not rows:
                rows.append(("ETF", "沒有公司月營收／毛利率"))
            return rows
    except Exception:
        pass
    emerging = False
    try:
        from universe import stock_is_emerging

        emerging = bool(stock_is_emerging(sid, path))
    except Exception:
        emerging = False
    m = get_latest_monthly(path, sid)
    q = get_latest_income(path, sid)
    months = list_monthly_revenue(path, sid, limit=36)
    q_from_m = quarterly_revenue_from_monthly(months)
    rows = []
    # 月營收近窗（對齊參考表：億／月增／年增／累年增＋狀態）；有幾月列幾月
    if months:
        # 介紹卡高度有限：近窗最多 6 列，單位對齊一行；多月靠每日同步累積
        win_n = 6 if emerging else 4
        rows.extend(monthly_revenue_window_rows(months, limit=win_n))
    elif m:
        # 理論上 list 會含 latest；保底
        rows.extend(monthly_revenue_window_rows([m], limit=1))
    # 近兩年季營收：有完整三個月才列；標同季年增／較上季
    if q_from_m:
        by_key = {(int(x["year"]), int(x["season"])): x for x in q_from_m}
        show = q_from_m[:8]  # 最多 8 季＝兩年
        for i, qq in enumerate(show):
            y, s = int(qq["year"]), int(qq["season"])
            rev = float(qq.get("revenue") or 0)
            try:
                from industry_brief import format_season_zh

                q_lab = format_season_zh(y, s)
            except Exception:
                q_lab = f"{y}Q{s}"
            yoy_q = by_key.get((y - 1, s))
            if s == 1:
                prev_key = (y - 1, 4)
            else:
                prev_key = (y, s - 1)
            qoq_q = by_key.get(prev_key)
            yoy_pct = None
            qoq_pct = None
            if yoy_q and float(yoy_q.get("revenue") or 0) > 0:
                yoy_pct = (rev - float(yoy_q["revenue"])) / float(yoy_q["revenue"]) * 100.0
            if qoq_q and float(qoq_q.get("revenue") or 0) > 0:
                qoq_pct = (rev - float(qoq_q["revenue"])) / float(qoq_q["revenue"]) * 100.0
            tag = "；".join(
                t
                for t in (
                    revenue_trend_label(yoy_pct, kind="yoy_q"),
                    revenue_trend_label(qoq_pct, kind="qoq"),
                )
                if t and t != "—"
            ) or "—"
            lab = "季營收" if i == 0 else f"季營收{i + 1}"
            rows.append((lab, f"{q_lab}　{format_yi(rev)}　{tag}"))
    elif emerging and (months or m):
        rows.append(("季營收", "月數未滿三個月齊，暫不彙季（不造假）"))
        rows.append(("季毛利／EPS", "興櫃無免驗證季報源，不上卡"))
    if q:
        rev = float(q.get("revenue") or 0)
        opm = round(float(q.get("operating_income") or 0) / rev * 100.0, 1) if rev else 0.0
        try:
            from industry_brief import format_season_zh

            q_lab = format_season_zh(q["year"], q["season"])
        except Exception:
            q_lab = f"{q['year']}Q{q['season']}"
        # 已有月彙季時，官方季報列毛利／EPS，避免營收重複
        if not q_from_m:
            rows.append(("季報", f"{q_lab}　營收 {format_yi(q.get('revenue') or 0)}"))
        else:
            rows.append(("季報", f"{q_lab}（綜合損益）"))
        rows.append(("毛利", format_yi(q.get("gross_profit") or 0)))
        rows.append(("毛利率", f"{float(q['gross_margin_pct']):.1f}%"))
        if rev:
            rows.append(("營益率", f"{opm:.1f}%"))
        rows.append(("EPS", f"{float(q['eps']):.2f}"))
    try:
        from official_snapshots import valuation_plain_rows

        rows.extend(valuation_plain_rows(sid, path))
    except Exception:
        pass
    try:
        from industry_brief import stock_peer_plain_rows

        rows.extend(stock_peer_plain_rows(sid, path))
    except Exception:
        pass
    if not rows:
        if emerging:
            rows.append(("基本面", "興櫃月營收尚未同步到庫（櫃買 OpenAPI）"))
        else:
            rows.append(("基本面", "尚無月營收／季報"))
    return rows


def glance_fundamentals_rows(stock_id: str, db_path: str = None, *, skip_labels=()) -> list:
    """第一眼用的短基本面：月營收／增減（億元）、季報營收毛利。"""
    from tg_layout import kv_compact

    skip = {str(x) for x in (skip_labels or ())}
    return [
        kv_compact(lab, val)
        for lab, val in glance_fundamentals_plain(stock_id, db_path)
        if lab not in skip
    ]


def format_fundamentals_html(stock_id: str, db_path: str = None) -> str:
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    try:
        from universe import card_asset_type, etf_card_kind_label, is_etf_asset

        asset = card_asset_type(sid, path)
        if is_etf_asset(asset, sid):
            from tg_layout import title_line, kv_compact, section, join_sections

            kind = etf_card_kind_label(asset, sid)
            name = sid
            try:
                conn = sqlite3.connect(path)
                row = conn.execute(
                    "SELECT stock_name FROM stock_universe WHERE stock_id=?",
                    (sid,),
                ).fetchone()
                conn.close()
                if row and row[0]:
                    name = str(row[0])
            except Exception:
                name = sid
            kind_txt = f"{kind} ETF" if kind else "ETF"
            blocks = [title_line("ETF", sid, name)]
            blocks.append(
                section(
                    f"這檔是{kind_txt}，沒有公司月營收／季報毛利率。",
                    "公司本益不上卡。折溢價看收盤旁；配息只上已公告金額。",
                )
            )
            kv = []
            if kind:
                kv.append(kv_compact("類型", kind))
            try:
                from official_snapshots import etf_div_plain_rows, etf_nav_plain_rows

                kv.extend(kv_compact(a, b) for a, b in etf_nav_plain_rows(sid, path))
                kv.extend(kv_compact(a, b) for a, b in etf_div_plain_rows(sid, path))
            except Exception:
                pass
            if kv:
                blocks.append(section(*kv))
            return join_sections(*blocks)
    except Exception:
        pass
    m = get_latest_monthly(path, sid)
    q = get_latest_income(path, sid)
    if not m and not q:
        return f"⚠️ 尚無 <code>{sid}</code> 月營收／季報（等盤後流水線寫入；按鈕路徑不再現場全市場同步）。"
    name = (m or q or {}).get("stock_name") or sid
    face = ""
    try:
        from universe import listing_industry_face

        face = listing_industry_face(sid, path)
    except Exception:
        face = ""
    if not face:
        try:
            from stock_links import quote_market
            from wayne_db import listing_zh

            face = listing_zh(quote_market(sid, path))
        except Exception:
            face = ""
    title_name = f"{name}　{face}" if face else name
    from tg_layout import title_line, kv_compact, section, join_sections

    blocks = [title_line("基本面", sid, title_name)]
    if m:
        yyyymm = m["yyyymm"]
        try:
            from industry_brief import format_month_zh

            label = format_month_zh(yyyymm)
        except Exception:
            label = f"{yyyymm[:4]}/{yyyymm[4:]}"
        blocks.append(
            section(
                kv_compact("期間", label),
                kv_compact("月營收", format_yi(m.get("revenue") or 0)),
                kv_compact("較上月", format_yi(_mom_delta_k(m), signed=True)),
                kv_compact("較去年同月", format_yi(_yoy_delta_k(m), signed=True)),
                kv_compact("較去年累計", format_yi(_ytd_yoy_delta_k(m), signed=True)),
            )
        )
    if q:
        prev = prior_income(path, q)
        gm_note = ""
        try:
            from industry_brief import format_season_zh

            q_lab = format_season_zh(q["year"], q["season"])
            prev_lab = format_season_zh(prev["year"], prev["season"]) if prev else ""
        except Exception:
            q_lab = f"{q['year']}Q{q['season']}"
            prev_lab = f"{prev['year']}Q{prev['season']}" if prev else ""
        if prev and prev.get("gross_margin_pct") is not None:
            diff = q["gross_margin_pct"] - prev["gross_margin_pct"]
            gm_note = f"（較{prev_lab} {diff:+.1f}pt）"
        blocks.append(
            section(
                kv_compact("季報", q_lab),
                kv_compact("營收", format_yi(q.get("revenue") or 0)),
                kv_compact("毛利", format_yi(q.get("gross_profit") or 0)),
                kv_compact("毛利率", f"{q['gross_margin_pct']:.1f}%{gm_note}"),
                kv_compact("營益率", f"{(q['operating_income'] / q['revenue'] * 100.0) if q.get('revenue') else 0:.1f}%"),
                kv_compact("EPS", f"{q['eps']:.2f}"),
                kv_compact("稅後淨利", format_yi(q.get("net_income") or 0)),
            )
        )
    try:
        from industry_brief import stock_peer_plain_rows

        peer_rows = stock_peer_plain_rows(sid, path)
    except Exception:
        peer_rows = []
    if peer_rows:
        blocks.append(section(*[kv_compact(a, b) for a, b in peer_rows]))
    try:
        from stock_links import yahoo_income_url

        yurl = yahoo_income_url(sid, path)
        blocks.append(f'<a href="{yurl}">奇摩損益表（人工核對用）</a>')
    except Exception:
        pass
    return join_sections(*blocks)


def hot_revenue_names(db_path: str, min_yoy: float = 20.0, min_mom: float = 0.0, limit: int = 12) -> List[Dict[str, Any]]:
    ensure_fundamentals_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    latest = conn.execute("SELECT MAX(yyyymm) FROM monthly_revenue").fetchone()[0]
    if not latest:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT stock_id, stock_name, yyyymm, yoy_pct, mom_pct, ytd_yoy_pct, revenue
        FROM monthly_revenue
        WHERE yyyymm=? AND yoy_pct >= ? AND yoy_pct <= 200 AND mom_pct >= ?
          AND revenue >= 5000
        ORDER BY yoy_pct DESC LIMIT ?
        """,
        (latest, min_yoy, min_mom, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def format_hot_revenue_html(db_path: str) -> str:
    from stock_links import html_stock_anchor
    from tg_layout import join_dashed

    rows = hot_revenue_names(db_path)
    if not rows:
        return ""
    yyyymm = rows[0]["yyyymm"]
    try:
        from industry_brief import format_month_zh

        label = format_month_zh(yyyymm)
    except Exception:
        label = f"{yyyymm[:4]}/{yyyymm[4:]}"
    head = "\n".join(
        [
            "＝＝月營收轉強＝＝",
            str(label),
            "年增≥20%　且月增≥0",
        ]
    )
    body: list = []
    for r in rows:
        body.append("• " + html_stock_anchor(r["stock_id"], r["stock_name"], db_path))
        body.append(f"年增 {r['yoy_pct']:+.1f}%　月增 {r['mom_pct']:+.1f}%")
    return join_dashed(head, "\n".join(body))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print(sync_fundamentals(path))
    print(format_fundamentals_html("2330", path))
    print(format_hot_revenue_html(path))
