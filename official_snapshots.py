# -*- coding: utf-8 -*-
"""官方快照：本益／淨值／殖利率、融資融券餘額、暫停當沖、加權全日量、產業代碼。

只存官方欄位。空字串＝沒有真數，不上卡。禁止推估成本價。
盤後一次平行抓，縮短等待；查股只讀庫。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

log = logging.getLogger("wayne.official")

TWSE_BWIBBU = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TWSE_MARGN = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
TWSE_TWTB4U = "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"
TWSE_FMTQIK = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TWSE_COMPANY = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TPEX_MARGN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
TPEX_COMPANY = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

# 證交所／櫃買「產業別」代碼 → 官方產業名（含電子業細分 24–31）。
# 來源：公開資訊觀測站／上市櫃公司基本資料產業別。
INDUSTRY_CODE_NAME = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造業",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險業",
    "18": "貿易百貨業",
    "20": "其他業",
    "21": "化學工業",
    "22": "生技醫療業",
    "23": "油電燃氣業",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
}

_UA = {"User-Agent": "WayneBot/1.0 (+https://github.com/wayne05281019/WayneBot)"}


def roc_to_ymd(raw: str) -> str:
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(s) == 7:
        y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:7])
        return f"{y:04d}{m:02d}{d:02d}"
    if len(s) == 8:
        return s
    return ""


def _num(val: Any) -> Optional[float]:
    s = str(val or "").replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--", "n/a", "N/A", "null", "None", "nan"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _int(val: Any) -> Optional[int]:
    n = _num(val)
    if n is None:
        return None
    return int(round(n))


def industry_name(code: Any) -> str:
    raw = str(code or "").strip()
    if not raw:
        return ""
    if raw in INDUSTRY_CODE_NAME:
        return INDUSTRY_CODE_NAME[raw]
    if raw.isdigit():
        return INDUSTRY_CODE_NAME.get(raw.zfill(2), "")
    # 已經是中文名就原樣用
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw):
        return raw
    return ""


def fetch_json(url: str, timeout: int = 45) -> List[dict]:
    req = Request(url, headers=_UA)
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "tables", "result"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
    return []


def ensure_schema(db_path: str | None = None) -> str:
    path = db_path or get_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_valuation (
                stock_id TEXT NOT NULL,
                date TEXT NOT NULL,
                pe REAL,
                pb REAL,
                dividend_yield REAL,
                source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_id, date)
            );
            CREATE TABLE IF NOT EXISTS daily_margin (
                stock_id TEXT NOT NULL,
                date TEXT NOT NULL,
                margin_bal INTEGER,
                margin_limit INTEGER,
                margin_util REAL,
                short_bal INTEGER,
                short_limit INTEGER,
                short_util REAL,
                source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_id, date)
            );
            CREATE TABLE IF NOT EXISTS daytrade_status (
                stock_id TEXT NOT NULL,
                date TEXT NOT NULL,
                suspended INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_id, date)
            );
            CREATE INDEX IF NOT EXISTS idx_valuation_date ON daily_valuation(date);
            CREATE INDEX IF NOT EXISTS idx_margin_date ON daily_margin(date);
            CREATE INDEX IF NOT EXISTS idx_daytrade_date ON daytrade_status(date, suspended);
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def parse_bwibbu(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        sid = str(row.get("Code") or row.get("證券代號") or "").strip()
        if not sid:
            continue
        date = roc_to_ymd(row.get("Date") or row.get("出表日期") or "")
        pe, pb, yld = _num(row.get("PEratio")), _num(row.get("PBratio")), _num(row.get("DividendYield"))
        if pe is None and pb is None and yld is None:
            continue
        out.append({"stock_id": sid, "date": date, "pe": pe, "pb": pb, "dividend_yield": yld, "source": "twse_bwibbu"})
    return out


def parse_tpex_pe(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        sid = str(row.get("SecuritiesCompanyCode") or row.get("Code") or "").strip()
        if not sid:
            continue
        date = roc_to_ymd(row.get("Date") or "")
        pe = _num(row.get("PriceEarningRatio"))
        pb = _num(row.get("PriceBookRatio"))
        yld = _num(row.get("YieldRatio"))
        if pe is None and pb is None and yld is None:
            continue
        out.append({"stock_id": sid, "date": date, "pe": pe, "pb": pb, "dividend_yield": yld, "source": "tpex_pe"})
    return out


def parse_twse_margin(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        sid = str(row.get("股票代號") or row.get("Code") or "").strip()
        if not sid:
            continue
        date = roc_to_ymd(row.get("Date") or row.get("資料日期") or "")
        m_bal = _int(row.get("融資今日餘額"))
        m_lim = _int(row.get("融資限額"))
        s_bal = _int(row.get("融券今日餘額"))
        s_lim = _int(row.get("融券限額"))
        if m_bal is None and s_bal is None:
            continue
        m_util = round(m_bal / m_lim * 100.0, 2) if m_bal is not None and m_lim else None
        s_util = round(s_bal / s_lim * 100.0, 2) if s_bal is not None and s_lim else None
        out.append({
            "stock_id": sid,
            "date": date,
            "margin_bal": m_bal,
            "margin_limit": m_lim,
            "margin_util": m_util,
            "short_bal": s_bal,
            "short_limit": s_lim,
            "short_util": s_util,
            "source": "twse_margn",
        })
    return out


def parse_tpex_margin(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        sid = str(row.get("SecuritiesCompanyCode") or "").strip()
        if not sid:
            continue
        date = roc_to_ymd(row.get("Date") or "")
        m_bal = _int(row.get("MarginPurchaseBalance"))
        m_lim = _int(row.get("MarginPurchaseQuota"))
        s_bal = _int(row.get("ShortSaleBalance"))
        s_lim = _int(row.get("ShortSaleQuota"))
        m_util = _num(row.get("MarginPurchaseUtilizationRate"))
        s_util = _num(row.get("ShortSaleUtilizationRate"))
        if m_bal is None and s_bal is None:
            continue
        if m_util is None and m_bal is not None and m_lim:
            m_util = round(m_bal / m_lim * 100.0, 2)
        if s_util is None and s_bal is not None and s_lim:
            s_util = round(s_bal / s_lim * 100.0, 2)
        out.append({
            "stock_id": sid,
            "date": date,
            "margin_bal": m_bal,
            "margin_limit": m_lim,
            "margin_util": m_util,
            "short_bal": s_bal,
            "short_limit": s_lim,
            "short_util": s_util,
            "source": "tpex_margin",
        })
    return out


def parse_twtb4u(rows: Sequence[dict]) -> List[dict]:
    out = []
    for row in rows:
        sid = str(row.get("Code") or row.get("證券代號") or "").strip()
        if not sid:
            continue
        date = roc_to_ymd(row.get("Date") or "")
        flag = str(row.get("Suspension") or row.get("註記") or "").strip().upper()
        out.append({
            "stock_id": sid,
            "date": date,
            "suspended": 1 if flag in ("Y", "YES", "*") else 0,
            "source": "twse_twtb4u",
        })
    return out


def parse_fmtqik(rows: Sequence[dict]) -> List[dict]:
    """FMTQIK TradeVolume＝成交股數 → 張（÷1000），與 daily_quotes.volume 同一單位。"""
    out = []
    for row in rows:
        date = roc_to_ymd(row.get("Date") or "")
        shares = _num(row.get("TradeVolume"))
        value = _num(row.get("TradeValue"))
        close = _num(row.get("TAIEX"))
        change = _num(row.get("Change"))
        if not date or shares is None:
            continue
        lots = int(round(shares / 1000.0))
        pct = None
        if close and change is not None:
            prev = close - change
            if prev:
                pct = round(change / prev * 100.0, 2)
        out.append({
            "date": date,
            "volume": lots,
            "trade_value": value,
            "close": close,
            "pct_change": pct,
            "source": "twse_fmtqik",
        })
    return out


def parse_company_industry(rows: Sequence[dict], *, source: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for row in rows:
        if source == "twse":
            sid = str(row.get("公司代號") or "").strip()
            name = industry_name(row.get("產業別"))
        else:
            sid = str(row.get("SecuritiesCompanyCode") or "").strip()
            name = industry_name(row.get("SecuritiesIndustryCode") or row.get("產業別"))
        if sid and name:
            out.append((sid, name))
    return out


def _upsert_valuation(conn: sqlite3.Connection, rows: Iterable[dict], now: str) -> int:
    n = 0
    for r in rows:
        date = str(r.get("date") or "")
        sid = str(r.get("stock_id") or "")
        if not sid or len(date) != 8:
            continue
        conn.execute(
            """
            INSERT INTO daily_valuation(stock_id, date, pe, pb, dividend_yield, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, date) DO UPDATE SET
                pe=excluded.pe, pb=excluded.pb, dividend_yield=excluded.dividend_yield,
                source=excluded.source, updated_at=excluded.updated_at
            """,
            (sid, date, r.get("pe"), r.get("pb"), r.get("dividend_yield"), r.get("source") or "", now),
        )
        n += 1
    return n


def _upsert_margin(conn: sqlite3.Connection, rows: Iterable[dict], now: str) -> int:
    n = 0
    for r in rows:
        date = str(r.get("date") or "")
        sid = str(r.get("stock_id") or "")
        if not sid or len(date) != 8:
            continue
        conn.execute(
            """
            INSERT INTO daily_margin(
                stock_id, date, margin_bal, margin_limit, margin_util,
                short_bal, short_limit, short_util, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, date) DO UPDATE SET
                margin_bal=excluded.margin_bal, margin_limit=excluded.margin_limit,
                margin_util=excluded.margin_util, short_bal=excluded.short_bal,
                short_limit=excluded.short_limit, short_util=excluded.short_util,
                source=excluded.source, updated_at=excluded.updated_at
            """,
            (
                sid, date, r.get("margin_bal"), r.get("margin_limit"), r.get("margin_util"),
                r.get("short_bal"), r.get("short_limit"), r.get("short_util"),
                r.get("source") or "", now,
            ),
        )
        n += 1
    return n


def _upsert_daytrade(conn: sqlite3.Connection, rows: Iterable[dict], now: str) -> int:
    n = 0
    for r in rows:
        date = str(r.get("date") or "")
        sid = str(r.get("stock_id") or "")
        if not sid or len(date) != 8:
            continue
        conn.execute(
            """
            INSERT INTO daytrade_status(stock_id, date, suspended, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(stock_id, date) DO UPDATE SET
                suspended=excluded.suspended, source=excluded.source, updated_at=excluded.updated_at
            """,
            (sid, date, int(r.get("suspended") or 0), r.get("source") or "", now),
        )
        n += 1
    return n


def overlay_fmtqik(db_path: str, rows: Sequence[dict]) -> int:
    """把 FMTQIK 全日量寫進 index_daily.volume（張）。有收盤價的日子一併補上。"""
    from taiwan_market import _INDEX_SYMBOL, ensure_index_daily_table

    ensure_index_daily_table(db_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        for r in rows:
            date = str(r.get("date") or "")
            vol = int(r.get("volume") or 0)
            if len(date) != 8 or vol <= 0:
                continue
            close = float(r.get("close") or 0)
            pct = r.get("pct_change")
            conn.execute(
                """
                INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, 'unknown', ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    volume=excluded.volume,
                    close=CASE WHEN excluded.close > 0 THEN excluded.close ELSE index_daily.close END,
                    pct_change=COALESCE(excluded.pct_change, index_daily.pct_change),
                    updated_at=excluded.updated_at
                """,
                (date, _INDEX_SYMBOL, close, float(vol), pct, now),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def overlay_industry(db_path: str, pairs: Sequence[Tuple[str, str]]) -> int:
    if not pairs:
        return 0
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_universe'"
        ).fetchone()
        if not has:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        for sid, name in pairs:
            cur = conn.execute(
                """
                UPDATE stock_universe
                SET industry=?, updated_at=?
                WHERE stock_id=? AND TRIM(COALESCE(industry,'')) != ?
                """,
                (name, now, sid, name),
            )
            if cur.rowcount:
                n += 1
            conn.execute(
                """
                UPDATE stock_universe
                SET industry=?
                WHERE stock_id=? AND TRIM(COALESCE(industry,'')) = ''
                """,
                (name, sid),
            )
        conn.commit()
    finally:
        conn.close()
    return n


def sync_official_snapshots(db_path: str | None = None) -> Dict[str, Any]:
    """盤後：平行抓官方 JSON，寫估值／融資餘額／暫停當沖／加權量／產業名。"""
    path = ensure_schema(db_path)
    jobs = {
        "bwibbu": TWSE_BWIBBU,
        "tpex_pe": TPEX_PE,
        "margn": TWSE_MARGN,
        "tpex_margin": TPEX_MARGN,
        "twtb4u": TWSE_TWTB4U,
        "fmtqik": TWSE_FMTQIK,
        "twse_co": TWSE_COMPANY,
        "tpex_co": TPEX_COMPANY,
    }
    fetched: Dict[str, List[dict]] = {}
    errors: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(fetch_json, url): name for name, url in jobs.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                fetched[name] = fut.result()
            except Exception as exc:
                errors[name] = str(exc)
                fetched[name] = []
                log.warning("官方快照 %s 失敗：%s", name, exc)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    val_n = mar_n = dt_n = 0
    conn = sqlite3.connect(path)
    try:
        val_n += _upsert_valuation(conn, parse_bwibbu(fetched.get("bwibbu") or []), now)
        val_n += _upsert_valuation(conn, parse_tpex_pe(fetched.get("tpex_pe") or []), now)
        mar_n += _upsert_margin(conn, parse_twse_margin(fetched.get("margn") or []), now)
        mar_n += _upsert_margin(conn, parse_tpex_margin(fetched.get("tpex_margin") or []), now)
        dt_n += _upsert_daytrade(conn, parse_twtb4u(fetched.get("twtb4u") or []), now)
        conn.commit()
    finally:
        conn.close()

    fmt_rows = parse_fmtqik(fetched.get("fmtqik") or [])
    fmt_n = overlay_fmtqik(path, fmt_rows) if fmt_rows else 0
    industry_pairs = parse_company_industry(fetched.get("twse_co") or [], source="twse")
    industry_pairs += parse_company_industry(fetched.get("tpex_co") or [], source="tpex")
    ind_n = overlay_industry(path, industry_pairs)

    return {
        "ok": not errors or val_n + mar_n + dt_n + fmt_n > 0,
        "valuation": val_n,
        "margin": mar_n,
        "daytrade": dt_n,
        "fmtqik": fmt_n,
        "industry": ind_n,
        "errors": errors,
    }


def latest_valuation(stock_id: str, db_path: str | None = None) -> Optional[Dict[str, Any]]:
    path = db_path or get_db_path()
    ensure_schema(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """
            SELECT date, pe, pb, dividend_yield, source
            FROM daily_valuation WHERE stock_id=? ORDER BY date DESC LIMIT 1
            """,
            (str(stock_id).strip(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"date": row[0], "pe": row[1], "pb": row[2], "dividend_yield": row[3], "source": row[4]}


def latest_margin(stock_id: str, db_path: str | None = None) -> Optional[Dict[str, Any]]:
    path = db_path or get_db_path()
    ensure_schema(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """
            SELECT date, margin_bal, margin_limit, margin_util,
                   short_bal, short_limit, short_util, source
            FROM daily_margin WHERE stock_id=? ORDER BY date DESC LIMIT 1
            """,
            (str(stock_id).strip(),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "date": row[0],
        "margin_bal": row[1],
        "margin_limit": row[2],
        "margin_util": row[3],
        "short_bal": row[4],
        "short_limit": row[5],
        "short_util": row[6],
        "source": row[7],
    }


def paused_daytrade_ids(db_path: str | None = None, as_of: str | None = None) -> set:
    """最新一日本官方標 Suspension=Y 的代號。表空就回空集合，不誤殺當沖桶。"""
    path = db_path or get_db_path()
    if not path or not os.path.isfile(path):
        return set()
    ensure_schema(path)
    conn = sqlite3.connect(path)
    try:
        if as_of:
            day = str(as_of).replace("-", "")[:8]
        else:
            row = conn.execute("SELECT MAX(date) FROM daytrade_status").fetchone()
            day = str(row[0] or "") if row else ""
        if len(day) != 8:
            return set()
        rows = conn.execute(
            "SELECT stock_id FROM daytrade_status WHERE date=? AND suspended=1",
            (day,),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {str(r[0]) for r in rows}


def valuation_plain_rows(stock_id: str, db_path: str | None = None) -> List[Tuple[str, str]]:
    """介紹圖／查股：有官方數才上列。"""
    rows: List[Tuple[str, str]] = []
    val = latest_valuation(stock_id, db_path)
    if val:
        bits = []
        if val.get("pe") is not None:
            bits.append(f"本益 {val['pe']:.2f}")
        if val.get("pb") is not None:
            bits.append(f"淨值 {val['pb']:.2f}")
        if val.get("dividend_yield") is not None:
            bits.append(f"殖利率 {val['dividend_yield']:.2f}%")
        if bits:
            rows.append(("估值", "　".join(bits)))
    mar = latest_margin(stock_id, db_path)
    if mar:
        mbits = []
        if mar.get("margin_bal") is not None:
            util = f"　使用率 {mar['margin_util']:.1f}%" if mar.get("margin_util") is not None else ""
            mbits.append(f"融資 {int(mar['margin_bal']):,}張{util}")
        if mar.get("short_bal") is not None:
            util = f"　使用率 {mar['short_util']:.1f}%" if mar.get("short_util") is not None else ""
            mbits.append(f"融券 {int(mar['short_bal']):,}張{util}")
        if mbits:
            rows.append(("資券餘額", "　".join(mbits)))
    return rows


def drop_paused_daytrade(results: Dict[str, Any], db_path: str | None = None) -> Dict[str, Any]:
    banned = paused_daytrade_ids(db_path)
    if not banned:
        return results
    out = dict(results)
    items = out.get("day_trade")
    if isinstance(items, list):
        out["day_trade"] = [
            it for it in items
            if not (isinstance(it, dict) and str(it.get("stock_id") or it.get("code") or "") in banned)
        ]
    return out
