"""
月營收 YoY/MoM 與季報毛利率：只吃證交所／櫃買官方 OpenAPI 最新一期快照。
歷史深度靠每次盤後寫入 SQLite 累積，不臆造公式、不抓第三方付費源。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

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
TWSE_INCOME = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
TPEX_INCOME = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci"


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
                stock_name=excluded.stock_name, market=excluded.market, industry=excluded.industry,
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
    months = sorted({r["yyyymm"] for r in monthly_rows})
    quarters = sorted({f"{r['year']}Q{r['season']}" for r in income_rows})
    m_max = conn.execute("SELECT COUNT(*), MAX(yyyymm) FROM monthly_revenue").fetchone()
    q_max = conn.execute("SELECT COUNT(*), MAX(year), MAX(season) FROM quarterly_income").fetchone()
    conn.close()
    stats = {
        "monthly_rows": m_n,
        "income_rows": i_n,
        "errors": errors,
        "months_in_feed": months[-3:],
        "quarters_in_feed": quarters[-4:],
        "db_monthly": int(m_max[0] or 0),
        "db_latest_month": m_max[1] or "",
        "db_income": int(q_max[0] or 0),
        "db_latest_quarter": f"{q_max[1]}Q{q_max[2]}" if q_max[1] else "",
        "note": "官方 OpenAPI 永遠是目前最新一期；公司公布後隔日盤後就會寫入，不必指定財報日。月營收約每月10日前後、季報約5/8/11月中與隔年3月底陸續出表。",
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
    m = get_latest_monthly(path, sid)
    q = get_latest_income(path, sid)
    rows = []
    if m:
        yyyymm = str(m.get("yyyymm") or "")
        label = f"{yyyymm[:4]}/{yyyymm[4:]}" if len(yyyymm) >= 6 else yyyymm
        rows.append(
            (
                "月營收",
                f"{label}　{format_yi(m.get('revenue') or 0)}",
            )
        )
        rows.append(
            (
                "較上月／去年",
                f"{format_yi(_mom_delta_k(m), signed=True, unit=False)}　"
                f"{format_yi(_yoy_delta_k(m), signed=True, unit=False)}",
            )
        )
        rows.append(
            (
                "較去年累計",
                format_yi(_ytd_yoy_delta_k(m), signed=True),
            )
        )
    if q:
        rev = float(q.get("revenue") or 0)
        opm = round(float(q.get("operating_income") or 0) / rev * 100.0, 1) if rev else 0.0
        rows.append(("季報", f"{q['year']}Q{q['season']}　營收 {format_yi(q.get('revenue') or 0)}"))
        rows.append(
            (
                "毛利",
                f"{format_yi(q.get('gross_profit') or 0)}　"
                f"毛利率 {float(q['gross_margin_pct']):.1f}%　營益率 {opm:.1f}%",
            )
        )
        rows.append(("EPS", f"{float(q['eps']):.2f}"))
    try:
        from official_snapshots import valuation_plain_rows

        rows.extend(valuation_plain_rows(sid, path))
    except Exception:
        pass
    if not rows:
        rows.append(("基本面", "尚無月營收／季報"))
    return rows


def glance_fundamentals_rows(stock_id: str, db_path: str = None) -> list:
    """第一眼用的短基本面：月營收／增減（億元）、季報營收毛利。"""
    from tg_layout import kv_compact

    return [kv_compact(lab, val) for lab, val in glance_fundamentals_plain(stock_id, db_path)]


def format_fundamentals_html(stock_id: str, db_path: str = None) -> str:
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    m = get_latest_monthly(path, sid)
    q = get_latest_income(path, sid)
    if not m and not q:
        return f"⚠️ 尚無 <code>{sid}</code> 月營收／季報（等盤後流水線寫入；按鈕路徑不再現場全市場同步）。"
    name = (m or q or {}).get("stock_name") or sid
    from tg_layout import title_line, kv_compact, section, join_sections

    blocks = [title_line("基本面", sid, name)]
    if m:
        yyyymm = m["yyyymm"]
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
        if prev and prev.get("gross_margin_pct") is not None:
            diff = q["gross_margin_pct"] - prev["gross_margin_pct"]
            gm_note = f"（較{prev['year']}Q{prev['season']} {diff:+.1f}pt）"
        blocks.append(
            section(
                kv_compact("季報", f"{q['year']}Q{q['season']}"),
                kv_compact("營收", format_yi(q.get("revenue") or 0)),
                kv_compact("毛利", format_yi(q.get("gross_profit") or 0)),
                kv_compact("毛利率", f"{q['gross_margin_pct']:.1f}%{gm_note}"),
                kv_compact("營益率", f"{(q['operating_income'] / q['revenue'] * 100.0) if q.get('revenue') else 0:.1f}%"),
                kv_compact("EPS", f"{q['eps']:.2f}"),
                kv_compact("稅後淨利", format_yi(q.get("net_income") or 0)),
            )
        )
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
    rows = hot_revenue_names(db_path)
    if not rows:
        return ""
    yyyymm = rows[0]["yyyymm"]
    label = f"{yyyymm[:4]}/{yyyymm[4:]}"
    lines = [f"🔥 <b>【月營收轉強】{label} YoY≥20% 且 MoM≥0</b>"]
    for r in rows:
        lines.append(
            f"• <code>{r['stock_id']}</code> {r['stock_name']} YoY {r['yoy_pct']:+.1f}% MoM {r['mom_pct']:+.1f}%"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print(sync_fundamentals(path))
    print(format_fundamentals_html("2330", path))
    print(format_hot_revenue_html(path))
