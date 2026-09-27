# -*- coding: utf-8 -*-
"""興櫃獨立行情：櫃買官方當日行情表／日表 CSV，不寫進上市櫃 daily_quotes。

興櫃沒有上市櫃那種集合競價開收盤。官方欄位：
日均價＝close、日最高＝high、日最低＝low、前日均價＝open。
獲利／高低卡用這套官方均價序列，不要用上市櫃日K去硬套。
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import requests

logger = logging.getLogger("WayneBot.Emerging")

OPENAPI_LATEST = "https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics"
CSV_URL = "https://www.tpex.org.tw/www/en-us/emerging/dailyDl?name=EMdes010.{ymd}-E.csv"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,*/*;q=0.8",
}

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS emerging_quotes (
    date TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'EM',
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    turnover_k REAL NOT NULL,
    pct_change REAL NOT NULL,
    avg_price REAL NOT NULL,
    foreign_net INTEGER DEFAULT 0,
    trust_net INTEGER DEFAULT 0,
    dealer_net INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    PRIMARY KEY (date, stock_id)
);
"""


def roc_yyyymmdd(raw: str) -> str:
    """1150907 → 20260907。已是西元八碼就原樣。"""
    s = str(raw or "").strip().replace("/", "").replace("-", "")
    if len(s) == 8 and s.startswith("11"):
        y = int(s[:3]) + 1911
        return f"{y:04d}{s[3:]}"
    if len(s) == 7 and s.isdigit():
        y = int(s[:3]) + 1911
        return f"{y:04d}{s[3:]}"
    return s[:8]


def _f(val) -> float:
    s = str(val or "").replace(",", "").replace("%", "").replace("+", "").strip()
    if s in ("", "-", "n/a", "N/A", "--"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _i(val) -> int:
    return int(round(_f(val)))


def parse_emerging_csv(text: str) -> Tuple[str, List[dict]]:
    """解析櫃買英文日表 CSV。回傳 (YYYYMMDD, rows)。"""
    as_of = ""
    rows: List[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("DATADATE"):
            # DATADATE,Date:2026/09/07
            part = line.split("Date:", 1)[-1].strip().replace("/", "")
            as_of = part[:8]
            continue
        if not line.startswith("BODY,"):
            continue
        payload = line[5:]
        try:
            fields = next(csv.reader(io.StringIO(payload)))
        except Exception:
            continue
        if len(fields) < 13:
            continue
        sid = str(fields[0]).strip()
        name = str(fields[1]).strip()
        avg = _f(fields[4])
        prev = _f(fields[5])
        pct = _f(fields[7])
        high = _f(fields[8])
        low = _f(fields[9])
        last = _f(fields[10])
        shares = max(0, _i(fields[11]))
        turnover = _f(fields[12])
        if not sid:
            continue
        # 官方股數／1000＝張（可小數）。不准 round 成 0 把薄量當天畫成無量洞。
        vol_lots = round(shares / 1000.0, 6) if shares > 0 else 0.0
        if avg <= 0:
            # 官方有列、均價「-」＝當日無成交；前日均價當停價參考，不准編高低振幅
            if prev <= 0:
                continue
            rows.append(
                {
                    "stock_id": sid,
                    "stock_name": name,
                    "open": prev,
                    "high": prev,
                    "low": prev,
                    "close": prev,
                    "volume": 0.0,
                    "turnover_k": 0.0,
                    "pct_change": 0.0,
                    "avg_price": prev,
                    "no_trade": True,
                    "source": "tpex_esb_csv",
                }
            )
            continue
        if high <= 0:
            high = max(avg, last, prev)
        if low <= 0:
            low = min(x for x in (avg, last, prev, high) if x > 0) if high > 0 else avg
        if low > high:
            low, high = high, low
        open_px = prev if prev > 0 else avg
        rows.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "open": open_px,
                "high": high,
                "low": low,
                "close": avg,
                "volume": vol_lots,
                "turnover_k": round(turnover / 1000.0, 2),
                "pct_change": pct,
                "avg_price": avg,
                "no_trade": False,
                "source": "tpex_esb_csv",
            }
        )
    return as_of, rows


def parse_emerging_openapi(items: Iterable[dict]) -> Tuple[str, List[dict]]:
    rows: List[dict] = []
    as_of = ""
    for it in items or []:
        if not isinstance(it, dict):
            continue
        as_of = as_of or roc_yyyymmdd(it.get("Date") or "")
        sid = str(it.get("SecuritiesCompanyCode") or "").strip()
        name = str(it.get("CompanyName") or "").strip()
        avg = _f(it.get("Average"))
        prev = _f(it.get("PreviousAveragePrice"))
        high = _f(it.get("Highest"))
        low = _f(it.get("Lowest"))
        last = _f(it.get("LatestPrice"))
        shares = max(0, _i(it.get("TransactionVolume")))
        if not sid:
            continue
        vol_lots = round(shares / 1000.0, 6) if shares > 0 else 0.0
        if avg <= 0:
            if prev <= 0:
                continue
            rows.append(
                {
                    "stock_id": sid,
                    "stock_name": name,
                    "open": prev,
                    "high": prev,
                    "low": prev,
                    "close": prev,
                    "volume": 0.0,
                    "turnover_k": 0.0,
                    "pct_change": 0.0,
                    "avg_price": prev,
                    "no_trade": True,
                    "source": "tpex_esb_openapi",
                }
            )
            continue
        if high <= 0:
            high = max(avg, last, prev)
        if low <= 0:
            low = min(x for x in (avg, last, prev, high) if x > 0) if high > 0 else avg
        if low > high:
            low, high = high, low
        open_px = prev if prev > 0 else avg
        pct = 0.0
        if prev > 0:
            pct = round((avg - prev) / prev * 100.0, 2)
        turnover = avg * shares
        rows.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "open": open_px,
                "high": high,
                "low": low,
                "close": avg,
                "volume": vol_lots,
                "turnover_k": round(turnover / 1000.0, 2),
                "pct_change": pct,
                "avg_price": avg,
                "no_trade": False,
                "source": "tpex_esb_openapi",
            }
        )
    return as_of, rows


def ensure_emerging_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_em_stock_date ON emerging_quotes(stock_id, date);"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_em_date ON emerging_quotes(date);")
        # 舊庫 volume 曾是 INTEGER affinity，薄量 0.03 可能被存壞；遷成 REAL 後重抓才準
        _migrate_emerging_volume_real(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_emerging_volume_real(conn: sqlite3.Connection) -> None:
    """把 emerging_quotes.volume 確實變成 REAL affinity（SQLite 不能 ALTER TYPE）。"""
    try:
        cols = conn.execute("PRAGMA table_info(emerging_quotes)").fetchall()
    except sqlite3.OperationalError:
        return
    if not cols:
        return
    vol_decl = ""
    for _cid, name, ctype, *_rest in cols:
        if str(name) == "volume":
            vol_decl = str(ctype or "").upper()
            break
    if "REAL" in vol_decl or "FLOAT" in vol_decl or "DOUBLE" in vol_decl:
        return
    conn.execute(
        """
        CREATE TABLE emerging_quotes__real (
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            market TEXT NOT NULL DEFAULT 'EM',
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            turnover_k REAL NOT NULL,
            pct_change REAL NOT NULL,
            avg_price REAL NOT NULL,
            foreign_net INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            PRIMARY KEY (date, stock_id)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO emerging_quotes__real
        SELECT date, stock_id, stock_name, market, open, high, low, close,
               CAST(volume AS REAL), turnover_k, pct_change, avg_price,
               foreign_net, trust_net, dealer_net, source
        FROM emerging_quotes;
        """
    )
    conn.execute("DROP TABLE emerging_quotes;")
    conn.execute("ALTER TABLE emerging_quotes__real RENAME TO emerging_quotes;")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_em_stock_date ON emerging_quotes(stock_id, date);"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_em_date ON emerging_quotes(date);")


def _emerging_bar_ok(open_p: float, high: float, low: float, close: float) -> bool:
    """興櫃開＝前日均價，可落在當日高低外；只要求高低收官方一致，不准拒寫薄量日。"""
    o, h, l, c = float(open_p or 0), float(high or 0), float(low or 0), float(close or 0)
    if c <= 0 or h <= 0 or l <= 0:
        return False
    return h >= l - 1e-6 and h >= c - 1e-6 and l <= c + 1e-6


def upsert_emerging_rows(db_path: str, as_of: str, rows: List[dict]) -> int:
    if not as_of or not rows:
        return 0
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        payload = []
        for r in rows:
            try:
                o = float(r["open"] or 0)
                h = float(r["high"] or 0)
                l = float(r["low"] or 0)
                c = float(r["close"] or 0)
                v = float(r["volume"] or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if not _emerging_bar_ok(o, h, l, c):
                continue
            payload.append(
                (
                    as_of,
                    r["stock_id"],
                    r["stock_name"],
                    "EM",
                    o,
                    h,
                    l,
                    c,
                    v,
                    r["turnover_k"],
                    r["pct_change"],
                    r["avg_price"],
                    r.get("source") or "",
                )
            )
        if not payload:
            return 0
        # CSV 永遠可覆寫；OpenAPI 只能覆寫非 CSV（或缺列）。半套 OpenAPI 不准蓋掉全日 CSV。
        conn.executemany(
            """
            INSERT INTO emerging_quotes(
                date, stock_id, stock_name, market, open, high, low, close,
                volume, turnover_k, pct_change, avg_price,
                foreign_net, trust_net, dealer_net, source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?)
            ON CONFLICT(date, stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                turnover_k=excluded.turnover_k,
                pct_change=excluded.pct_change,
                avg_price=excluded.avg_price,
                source=excluded.source
            WHERE instr(lower(excluded.source), 'csv') > 0
               OR instr(lower(COALESCE(emerging_quotes.source, '')), 'csv') = 0;
            """,
            payload,
        )
        n = conn.total_changes
        conn.commit()
    finally:
        conn.close()
    return n


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_emerging_csv_day(ymd: str, session: Optional[requests.Session] = None) -> Tuple[str, List[dict]]:
    sess = session or _session()
    url = CSV_URL.format(ymd=ymd)
    resp = sess.get(url, timeout=25)
    if resp.status_code != 200 or not (resp.text or "").lstrip().startswith("TITLE"):
        return "", []
    as_of, rows = parse_emerging_csv(resp.text)
    return as_of or ymd, rows


def fetch_emerging_openapi(session: Optional[requests.Session] = None) -> Tuple[str, List[dict]]:
    sess = session or _session()
    resp = sess.get(OPENAPI_LATEST, timeout=25)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return "", []
    return parse_emerging_openapi(data)


def emerging_date_count(db_path: str) -> int:
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(DISTINCT date) FROM emerging_quotes").fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def emerging_rows_on(db_path: str, ymd: str) -> int:
    day = str(ymd or "").replace("-", "")[:8]
    if len(day) != 8 or not day.isdigit():
        return 0
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM emerging_quotes WHERE date=?", (day,)
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _listed_quote_cap(db_path: str) -> str:
    if not db_path:
        return ""
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')) FROM daily_quotes"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return ""
    day = str(row[0] or "").replace("-", "")[:8] if row else ""
    return day if len(day) == 8 and day.isdigit() else ""


def _weekdays_after(start_ymd: str, cap: str, *, limit: int = 15) -> List[str]:
    cap = str(cap or "").replace("-", "")[:8]
    start = str(start_ymd or "").replace("-", "")[:8]
    if len(cap) != 8 or not cap.isdigit():
        return []
    try:
        end = datetime.strptime(cap, "%Y%m%d")
        if len(start) == 8 and start.isdigit():
            cur = datetime.strptime(start, "%Y%m%d") + timedelta(days=1)
        else:
            cur = end - timedelta(days=14)
    except ValueError:
        return []
    out: List[str] = []
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    if len(out) > int(limit):
        out = out[-int(limit) :]
    return out


def _weekdays_ending(cap: str, *, limit: int = 40) -> List[str]:
    """含 cap 往回的平日（不管庫裡最新日有沒有更新）。假日抓空會自然略過。"""
    cap = str(cap or "").replace("-", "")[:8]
    if len(cap) != 8 or not cap.isdigit():
        return []
    try:
        cur = datetime.strptime(cap, "%Y%m%d")
    except ValueError:
        return []
    out: List[str] = []
    lim = max(1, int(limit))
    while len(out) < lim:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y%m%d"))
        cur -= timedelta(days=1)
        if cur.year < 2020:
            break
    out.reverse()
    return out


# 高低卡要 240 根收盤低；約 280 開市日 ≈ 400 曆日。滿 40 天就停補＝10～240 低塌成同一價。
DEFAULT_EMERGING_LOOKBACK_DAYS = 400
MIN_EMERGING_DEPTH_DAYS = 240
# 全日約 360；350 仍可能缺無成交停價列（2758 20260813 等）。同步補齊用這個，健康半套關卡仍 MIN_EM=300。
EM_DAY_FULL_ROWS = 355


def _em_day_min_rows(min_rows: int = 0) -> int:
    """與 import_health.MIN_EM 同一門檻：半套日（~250）仍要重抓到全日。"""
    if int(min_rows or 0) > 0:
        return int(min_rows)
    try:
        from import_health import MIN_EM

        return int(MIN_EM)
    except Exception:
        return 300


def _em_day_full_rows(min_rows: int = 0) -> int:
    """同步寫滿用：比 MIN_EM 嚴，避免 350 列就停、漏掉無成交列。"""
    if int(min_rows or 0) > 0:
        return max(int(min_rows), EM_DAY_FULL_ROWS)
    return EM_DAY_FULL_ROWS


def missing_emerging_days(
    db_path: str, cap: str, *, lookback: int = 40, min_rows: int = 0
) -> List[str]:
    """中間缺日也要補。最新日若比 cap 新（盤中 OpenAPI）仍要回補 cap 以前的洞。

    預設用 EM_DAY_FULL_ROWS（355）：庫裡 300～354 列的「看起來夠」日仍重抓，
    把無成交停價列補齊。import_health 半套關卡仍看 MIN_EM=300。
    """
    need = _em_day_full_rows(min_rows)
    days = _weekdays_ending(cap, limit=lookback)
    return [d for d in days if emerging_rows_on(db_path, d) < need]


# 高低卡要 240 根收盤低；約 280 開市日 ≈ 400 曆日。滿 40 天就停補＝10～240 低塌成同一價。
DEFAULT_EMERGING_LOOKBACK_DAYS = 400
MIN_EMERGING_DEPTH_DAYS = 240


def sync_emerging_quotes(
    db_path: str,
    *,
    lookback_days: int = DEFAULT_EMERGING_LOOKBACK_DAYS,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.2,
    cap: str = "",
) -> Dict[str, int]:
    """補齊官方興櫃日表到上市櫃已收那日。

    - 半套日（列數 < MIN_EM）一律重抓 CSV。
    - 深度不足（開市日數 < 240）或 lookback 窗內缺日：永遠往回補，不准「已有 40 天就停」。
    - 當日 OpenAPI 先寫；同日 CSV 可覆寫（量／列較齊）。
    """
    ensure_emerging_table(db_path)
    sess = session or _session()
    need = _em_day_full_rows()
    lb = max(40, int(lookback_days or DEFAULT_EMERGING_LOOKBACK_DAYS))
    # 平日窗 ≈ 曆日 × 5/7。預設 400 曆日 → ~290 開市日 ≥ 240 低窗。
    weekday_window = max(40, int(lb * 5 / 7) + 5)
    stats = {
        "latest": 0,
        "hist": 0,
        "days": 0,
        "gaps": 0,
        "min_rows": need,
        "lookback_weekdays": weekday_window,
    }
    try:
        as_of, rows = fetch_emerging_openapi(sess)
        if as_of and rows:
            stats["latest"] = upsert_emerging_rows(db_path, as_of, rows)
    except Exception:
        logger.exception("興櫃 OpenAPI 當日行情失敗")
    listed = _listed_quote_cap(db_path)
    want_cap = str(cap or "").replace("-", "")[:8] or listed
    if not want_cap:
        try:
            from zoneinfo import ZoneInfo

            want_cap = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
        except Exception:
            want_cap = datetime.now().strftime("%Y%m%d")
    gap_days = missing_emerging_days(
        db_path, want_cap, lookback=weekday_window, min_rows=need
    )
    for ymd in gap_days:
        if emerging_rows_on(db_path, ymd) >= need:
            continue
        try:
            as_of, rows = fetch_emerging_csv_day(ymd, sess)
        except Exception:
            logger.info("興櫃 CSV %s 失敗", ymd)
            continue
        if as_of and rows:
            stats["hist"] += upsert_emerging_rows(db_path, as_of, rows)
            stats["gaps"] += 1
        time.sleep(max(0.0, float(sleep_s)))
    # 最新完整日若只靠 OpenAPI 半套，強制再用 CSV 覆寫一次
    if want_cap and emerging_rows_on(db_path, want_cap) < need:
        try:
            as_of, rows = fetch_emerging_csv_day(want_cap, sess)
            if as_of and rows:
                stats["hist"] += upsert_emerging_rows(db_path, as_of, rows)
                stats["gaps"] += 1
        except Exception:
            logger.info("興櫃 CSV cap %s 失敗", want_cap)
    stats["days"] = emerging_date_count(db_path)
    return stats


def compare_stock_to_official_csv(
    db_path: str,
    stock_id: str,
    *,
    lookback: int = 120,
    session: Optional[requests.Session] = None,
    sleep_s: float = 0.05,
) -> Dict[str, object]:
    """逐日對質：庫內 emerging_quotes vs 櫃買官方日表 CSV（開高低收量）。"""
    sid = str(stock_id or "").strip()
    out: Dict[str, object] = {
        "stock_id": sid,
        "checked": 0,
        "matched": 0,
        "missing_in_db": [],
        "price_mismatch": [],
        "volume_mismatch": [],
        "false_halt": [],
        "official_empty": [],
    }
    if not sid or not db_path:
        return out
    listed = _listed_quote_cap(db_path) or latest_emerging_date(db_path)
    days = _weekdays_ending(listed, limit=max(20, int(lookback)))
    sess = session or _session()
    conn = sqlite3.connect(db_path)
    try:
        for ymd in days:
            try:
                as_of, rows = fetch_emerging_csv_day(ymd, sess)
            except Exception:
                out["official_empty"] = list(out["official_empty"]) + [ymd]  # type: ignore
                continue
            time.sleep(max(0.0, float(sleep_s)))
            if not as_of or not rows:
                # 平日無檔＝假日／尚未公布，不算缺庫
                continue
            official = next((r for r in rows if str(r.get("stock_id")) == sid), None)
            if official is None:
                continue
            out["checked"] = int(out["checked"]) + 1  # type: ignore
            db_row = conn.execute(
                """
                SELECT open, high, low, close, volume, source
                FROM emerging_quotes WHERE stock_id=? AND date=?
                """,
                (sid, ymd),
            ).fetchone()
            if not db_row:
                out["missing_in_db"] = list(out["missing_in_db"]) + [ymd]  # type: ignore
                continue
            o_o, o_h, o_l, o_c = (
                float(official["open"]),
                float(official["high"]),
                float(official["low"]),
                float(official["close"]),
            )
            o_v = float(official["volume"])
            d_o, d_h, d_l, d_c, d_v = (
                float(db_row[0] or 0),
                float(db_row[1] or 0),
                float(db_row[2] or 0),
                float(db_row[3] or 0),
                float(db_row[4] or 0),
            )
            no_trade = bool(official.get("no_trade"))
            flat_db = (
                abs(d_h - d_l) <= 1e-8
                and abs(d_o - d_c) <= 1e-8
                and d_v <= 0
            )
            if (not no_trade) and o_v > 0 and flat_db:
                out["false_halt"] = list(out["false_halt"]) + [ymd]  # type: ignore
            price_ok = (
                abs(d_o - o_o) <= 0.06
                and abs(d_h - o_h) <= 0.06
                and abs(d_l - o_l) <= 0.06
                and abs(d_c - o_c) <= 0.06
            )
            # 量：CSV 小數張；OpenAPI 可能整數張。允許 1 張內差，或相對 0.5%
            vol_tol = max(1.0, o_v * 0.005)
            vol_ok = abs(d_v - o_v) <= vol_tol
            if not price_ok:
                out["price_mismatch"] = list(out["price_mismatch"]) + [  # type: ignore
                    {
                        "date": ymd,
                        "db": (d_o, d_h, d_l, d_c),
                        "csv": (o_o, o_h, o_l, o_c),
                    }
                ]
            elif not vol_ok:
                out["volume_mismatch"] = list(out["volume_mismatch"]) + [  # type: ignore
                    {"date": ymd, "db": d_v, "csv": o_v}
                ]
            else:
                out["matched"] = int(out["matched"]) + 1  # type: ignore
    finally:
        conn.close()
    return out


def load_stock_bars(db_path: str, stock_id: str, limit: int = 520):
    """單檔興櫃官方日均價序列，欄位對齊 daily_quotes 給決策卡／導航圖用。"""
    import pandas as pd

    sid = str(stock_id or "").strip()
    if not sid:
        return pd.DataFrame()
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT date, stock_name, open, high, low, close, volume, turnover_k,
                   pct_change AS change_pct, pct_change
            FROM emerging_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?
            """,
            conn,
            params=(sid, int(limit)),
        )
    finally:
        conn.close()
    return df


def latest_emerging_date(db_path: str) -> str:
    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(date) FROM emerging_quotes").fetchone()
        return str(row[0] or "") if row else ""
    finally:
        conn.close()


def load_emerging_frames(db_path: str, as_of: Optional[str] = None) -> Dict[str, "object"]:
    """給 ScreeningEngine 用的興櫃日K框。法人欄官方沒有，填 0。"""
    import pandas as pd

    ensure_emerging_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        if not as_of:
            row = conn.execute("SELECT MAX(date) FROM emerging_quotes").fetchone()
            as_of = str(row[0] or "") if row else ""
        if not as_of:
            return {}
        ids = [
            r[0]
            for r in conn.execute(
                """
                SELECT stock_id FROM emerging_quotes
                WHERE date=? AND close>0
                """,
                (as_of,),
            )
        ]
        if not ids:
            return {}
        ph = ",".join("?" * len(ids))
        df = pd.read_sql_query(
            f"""
            SELECT date, stock_id, stock_name, market, open, high, low, close,
                   volume, turnover_k, pct_change, avg_price,
                   foreign_net, trust_net, dealer_net
            FROM emerging_quotes
            WHERE stock_id IN ({ph}) AND date<=?
            ORDER BY stock_id, date
            """,
            conn,
            params=list(ids) + [as_of],
        )
    finally:
        conn.close()
    if df is None or df.empty:
        return {}
    out = {}
    for sid, g in df.groupby("stock_id"):
        if len(g) < 5:
            continue
        out[str(sid)] = g.reset_index(drop=True)
    return out
