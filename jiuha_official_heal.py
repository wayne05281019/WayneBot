# -*- coding: utf-8 -*-
"""啾哈對質官方欄補洞（非買訊；不准改黃金買點／海選／洞燭／value_fund_panels）。

補齊逐日對質缺欄，提高可驗證 n。沒有官方來源就標 unavailable，不准假數。

  python3 scripts/jiuha_official_heal.py --market data/wayne_market.db
  python3 scripts/jiuha_daily_confront.py --heal
"""
from __future__ import annotations

import csv
import io
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")

_TAIFEX_FUT_CONTRACTS_DOWN = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
_TX_CONTRACT = "臺股期貨"
_TX_FOREIGN = "外資及陸資"

# 可選欄：目前無穩定官方日列可落庫 → 對質標 unavailable（不准假數）
OPTIONAL_UNAVAILABLE: Dict[str, str] = {
    "open15_vol": "開盤15分量／成交金額：無穩定官方日列可對齊對質日（需分K另源）",
    "etf_gov_buy": "ETF／官股買超：無穩定官方日彙總可對齊對質日（不准用非官方推估）",
}


def _ymd(raw: Any) -> str:
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(s) >= 8:
        return s[:8]
    if len(s) == 7:
        try:
            y = int(s[:3]) + 1911
            return f"{y:04d}{s[3:7]}"
        except ValueError:
            return ""
    return ""


def _finite(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _now_utc() -> str:
    return datetime.now(tz=TAIPEI).astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_taipei() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def parse_taifex_fut_contracts_csv(text: str) -> List[Dict[str, Any]]:
    """解析期交所「三大法人期貨契約」CSV（cp950／utf-8）。

    口數欄：多方未平倉口數／空方未平倉口數／多空未平倉口數淨額。
    沒有真數列就不收。
    """
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        return []
    # 有些回應夾 HTML；只留 CSV 段
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []
    # 找表頭
    start = 0
    for i, ln in enumerate(lines):
        if "日期" in ln and ("未平倉" in ln or "身份" in ln):
            start = i
            break
    body = "\n".join(lines[start:])
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    # 容錯欄位名
    def _col(*names: str) -> int:
        for n in names:
            if n in header:
                return header.index(n)
        for i, h in enumerate(header):
            for n in names:
                if n in h:
                    return i
        return -1

    i_date = _col("日期")
    i_contract = _col("商品名稱", "契約名稱")
    i_item = _col("身份別")
    i_long = _col("多方未平倉口數")
    i_short = _col("空方未平倉口數")
    i_net = _col("多空未平倉口數淨額")
    if min(i_date, i_contract, i_item, i_long, i_short) < 0:
        return []
    out: List[Dict[str, Any]] = []
    for row in rows[1:]:
        if not row or len(row) <= max(i_date, i_contract, i_item, i_long, i_short):
            continue
        day = _ymd(row[i_date].replace("/", "-"))
        contract = str(row[i_contract] or "").strip()
        item = str(row[i_item] or "").strip()
        if len(day) != 8 or not contract or not item:
            continue
        oi_long = _finite(row[i_long])
        oi_short = _finite(row[i_short])
        if oi_long is None or oi_short is None:
            continue
        oi_net = _finite(row[i_net]) if i_net >= 0 and i_net < len(row) else None
        if oi_net is None:
            oi_net = float(oi_long) - float(oi_short)
        out.append(
            {
                "date": day,
                "contract": contract,
                "item": item,
                "oi_long": int(oi_long),
                "oi_short": int(oi_short),
                "oi_net": int(oi_net),
                "source": "taifex_fut_contracts_csv",
            }
        )
    return out


def fetch_taifex_fut_contracts_range(
    start_ymd: str,
    end_ymd: str,
    *,
    commodity_id: str = "TXF",
    session: Any = None,
    timeout: float = 60.0,
) -> List[Dict[str, Any]]:
    """期交所官方下載：臺股期貨三大法人多空未平倉（可跨日）。失敗回空。"""
    import requests

    s = start_ymd
    e = end_ymd
    if len(s) != 8 or len(e) != 8:
        return []
    q0 = f"{s[:4]}/{s[4:6]}/{s[6:8]}"
    q1 = f"{e[:4]}/{e[4:6]}/{e[6:8]}"
    sess = session
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": "Mozilla/5.0 (compatible; WayneBot-jiuha-heal/1.0)"})
    payload = {
        "queryStartDate": q0,
        "queryEndDate": q1,
        "commodityId": commodity_id,
        "queryType": "1",
        "marketCode": "0",
    }
    try:
        resp = sess.post(_TAIFEX_FUT_CONTRACTS_DOWN, data=payload, timeout=timeout)
        resp.raise_for_status()
        # 期交所常以 cp950 回 CSV
        raw = resp.content
        for enc in ("cp950", "big5", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
        return parse_taifex_fut_contracts_csv(text)
    except Exception:
        logger.debug("TAIFEX futContractsDateDown 失敗 %s–%s", q0, q1, exc_info=True)
        return []


def upsert_futures_inst_oi(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    from taiwan_market import ensure_futures_inst_oi_table

    ensure_futures_inst_oi_table(db_path)
    if not rows:
        return 0
    now = _now_utc()
    wrote = 0
    con = sqlite3.connect(db_path, timeout=60.0)
    try:
        for row in rows:
            day = _ymd(row.get("date"))
            contract = str(row.get("contract") or "").strip()
            item = str(row.get("item") or "").strip()
            if len(day) != 8 or not contract or not item:
                continue
            if row.get("oi_long") is None or row.get("oi_short") is None:
                continue
            con.execute(
                """
                INSERT INTO futures_inst_oi(
                    date, contract, item, oi_long, oi_short, oi_net, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, contract, item) DO UPDATE SET
                    oi_long=excluded.oi_long,
                    oi_short=excluded.oi_short,
                    oi_net=excluded.oi_net,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    day,
                    contract,
                    item,
                    int(row["oi_long"]),
                    int(row["oi_short"]),
                    int(row.get("oi_net") if row.get("oi_net") is not None else int(row["oi_long"]) - int(row["oi_short"])),
                    str(row.get("source") or "taifex_fut_contracts_csv"),
                    now,
                ),
            )
            wrote += 1
        con.commit()
    finally:
        con.close()
    return wrote


def heal_futures_foreign_oi(
    db_path: str,
    *,
    from_ymd: str = "",
    to_ymd: str = "",
    chunk_days: int = 31,
    sleep_s: float = 0.25,
) -> Dict[str, Any]:
    """補外資及陸資／臺股期貨 OI。缺官方列就不寫。"""
    end = _ymd(to_ymd) or datetime.now(TAIPEI).strftime("%Y%m%d")
    start = _ymd(from_ymd)
    if not start:
        # 預設往前約 120 曆日（涵蓋對質 60 交易日＋緩衝）
        start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    # 先寫 OpenAPI 最新日（若有）
    latest_n = 0
    try:
        from taiwan_market import sync_futures_inst_oi

        latest = sync_futures_inst_oi(db_path)
        latest_n = int(latest.get("rows") or 0)
    except Exception as exc:
        latest = {"ok": False, "error": str(exc)}
    # 分段下載歷史
    import requests

    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 (compatible; WayneBot-jiuha-heal/1.0)"})
    d0 = datetime.strptime(start, "%Y%m%d")
    d1 = datetime.strptime(end, "%Y%m%d")
    wrote = 0
    chunks = 0
    foreign_days: set[str] = set()
    errors = 0
    retries = 0
    cur = d0
    while cur <= d1:
        chunk_end = min(cur + timedelta(days=max(1, chunk_days) - 1), d1)
        rows: List[Dict[str, Any]] = []
        for attempt in range(3):
            rows = fetch_taifex_fut_contracts_range(
                cur.strftime("%Y%m%d"),
                chunk_end.strftime("%Y%m%d"),
                session=sess,
            )
            if rows:
                break
            retries += 1
            time.sleep(0.6 * (attempt + 1))
        chunks += 1
        if not rows:
            # 整段失敗→改逐日（開市日才打；失敗標 skip）
            day = cur
            while day <= chunk_end:
                ymd = day.strftime("%Y%m%d")
                try:
                    from trading_calendar import is_tw_open_calendar_day

                    open_day = is_tw_open_calendar_day(ymd)
                except Exception:
                    open_day = True
                if open_day:
                    one = fetch_taifex_fut_contracts_range(ymd, ymd, session=sess)
                    if one:
                        wrote += upsert_futures_inst_oi(db_path, one)
                        for r in one:
                            if (
                                r.get("contract") == _TX_CONTRACT
                                and r.get("item") == _TX_FOREIGN
                            ):
                                foreign_days.add(str(r["date"]))
                    else:
                        errors += 1
                    time.sleep(max(0.0, sleep_s))
                day += timedelta(days=1)
        else:
            wrote += upsert_futures_inst_oi(db_path, rows)
            for r in rows:
                if r.get("contract") == _TX_CONTRACT and r.get("item") == _TX_FOREIGN:
                    foreign_days.add(str(r["date"]))
        cur = chunk_end + timedelta(days=1)
        if cur <= d1:
            time.sleep(max(0.0, sleep_s))
    # 第二遍：對質窗內仍缺外資列的開市日逐日補（防整段偶發空回）
    try:
        sessions = _session_dates(db_path, limit=90)
    except Exception:
        sessions = []
    gap_fill = 0
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        have = {
            _ymd(r[0])
            for r in con.execute(
                """
                SELECT date FROM futures_inst_oi
                WHERE contract=? AND item=?
                """,
                (_TX_CONTRACT, _TX_FOREIGN),
            )
        }
    finally:
        con.close()
    for ymd in sessions:
        if ymd < start or ymd > end or ymd in have:
            continue
        one = fetch_taifex_fut_contracts_range(ymd, ymd, session=sess)
        if not one:
            errors += 1
            continue
        gap_fill += upsert_futures_inst_oi(db_path, one)
        for r in one:
            if r.get("contract") == _TX_CONTRACT and r.get("item") == _TX_FOREIGN:
                foreign_days.add(str(r["date"]))
                have.add(str(r["date"]))
        time.sleep(max(0.0, sleep_s))
    return {
        "ok": wrote > 0 or latest_n > 0 or gap_fill > 0,
        "wrote_rows": wrote + gap_fill,
        "gap_fill_rows": gap_fill,
        "openapi_latest": latest,
        "chunks": chunks,
        "errors": errors,
        "retries": retries,
        "foreign_tx_days": len(foreign_days),
        "from": start,
        "to": end,
        "source": "taifex_fut_contracts_csv+openapi",
    }


def _upsert_index_bar(
    db_path: str,
    *,
    day: str,
    symbol: str,
    open_: Optional[float],
    high: Optional[float],
    low: Optional[float],
    close: float,
    volume: Optional[float],
    pct_change: Optional[float],
    regime: str,
) -> int:
    from taiwan_market import ensure_index_daily_table

    ensure_index_daily_table(db_path)
    day = _ymd(day)
    if len(day) != 8 or close is None or close <= 0:
        return 0
    now = _now_utc()
    # 完整 OHLC：四欄皆有且非全同；否則若僅收 → 戳記（開高低＝收），標 regime
    o = open_ if open_ is not None else close
    h = high if high is not None else close
    l = low if low is not None else close
    con = sqlite3.connect(db_path, timeout=60.0)
    try:
        # 若庫內已有完整 OHLC，不准用戳記覆寫高低
        prev = con.execute(
            "SELECT open, high, low, close FROM index_daily WHERE date=? AND symbol=?",
            (day, symbol),
        ).fetchone()
        if prev:
            po, ph, pl, pc = prev
            complete_prev = (
                po is not None
                and ph is not None
                and pl is not None
                and pc is not None
                and not (po == ph == pl == pc)
                and ph >= pl
            )
            stamp_new = o == h == l == close
            if complete_prev and stamp_new:
                # 只補量／漲跌若缺
                con.execute(
                    """
                    UPDATE index_daily SET
                        volume=COALESCE(?, volume),
                        pct_change=COALESCE(?, pct_change),
                        updated_at=?
                    WHERE date=? AND symbol=?
                    """,
                    (volume, pct_change, now, day, symbol),
                )
                con.commit()
                return 1
        con.execute(
            """
            INSERT INTO index_daily(
                date, symbol, open, high, low, close, volume, pct_change, regime, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date, symbol) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close,
                volume=COALESCE(excluded.volume, index_daily.volume),
                pct_change=COALESCE(excluded.pct_change, index_daily.pct_change),
                regime=excluded.regime,
                updated_at=excluded.updated_at
            """,
            (day, symbol, o, h, l, close, volume, pct_change, regime, now),
        )
        con.commit()
    finally:
        con.close()
    return 1


def heal_otc_index(
    db_path: str,
    *,
    from_ym: str = "",
    max_months: int = 6,
    sleep_s: float = 0.18,
) -> Dict[str, Any]:
    """補櫃買指數。

    - 歷史：TPEX tradingIndex 官方收＋量（開高低僅收盤戳記；歷史完整 OHLC＝unavailable）
    - 最新結算日：若 MIS otc_o00 有完整開高低收且非全同，寫完整柱（來源 mis_otc_o00）
    - 已有完整 OHLC 不准被戳記覆寫（走 ``_upsert_index_bar``）
    """
    from scripts.decade_lab_pulse_backfill import fetch_tpex_otc_month

    raw = str(from_ym or "").replace("/", "").replace("-", "")
    end = datetime.now(TAIPEI).date()
    if len(raw) >= 6 and raw[:6].isdigit():
        y0, m0 = int(raw[:4]), int(raw[4:6])
    else:
        start = end - timedelta(days=31 * max(1, max_months))
        y0, m0 = start.year, start.month
    months: List[Tuple[int, int]] = []
    y, m = y0, m0
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    if max_months > 0:
        months = months[-int(max_months) :]

    wrote_stamp = 0
    errors = 0
    for i, (yy, mm) in enumerate(months):
        try:
            bars = fetch_tpex_otc_month(yy, mm)
        except Exception:
            errors += 1
            bars = []
        for b in bars:
            day = _ymd(b.get("date"))
            c = _finite(b.get("close"))
            if len(day) != 8 or c is None or c <= 0:
                continue
            # 歷史官方僅收：戳記寫入；完整柱保護在 _upsert_index_bar
            wrote_stamp += _upsert_index_bar(
                db_path,
                day=day,
                symbol="OTC",
                open_=c,
                high=c,
                low=c,
                close=c,
                volume=_finite(b.get("volume")),
                pct_change=_finite(b.get("pct_change")),
                regime="tpex_trading_index",
            )
        if i < len(months) - 1:
            time.sleep(max(0.0, sleep_s))
    stamp_res = {
        "ok": wrote_stamp > 0,
        "months": len(months),
        "wrote": wrote_stamp,
        "errors": errors,
        "source": "tpex_trading_index",
    }
    # MIS 最新完整 OHLC（盤後仍常留最後交易日）
    mis_wrote = 0
    mis_meta: Dict[str, Any] = {"status": "unavailable"}
    try:
        from live_quote import fetch_mis_otc_index_quote

        q = fetch_mis_otc_index_quote(fresh=True)
    except Exception as exc:
        q = None
        mis_meta = {"status": "unavailable", "error": str(exc)}
    if q:
        day = _ymd(q.get("date"))
        o = _finite(q.get("open"))
        h = _finite(q.get("high"))
        l = _finite(q.get("low"))
        c = _finite(q.get("close") or q.get("price"))
        vol = _finite(q.get("volume"))
        if (
            len(day) == 8
            and c is not None
            and c > 0
            and o is not None
            and h is not None
            and l is not None
            and not (o == h == l == c)
            and h >= l
        ):
            mis_wrote = _upsert_index_bar(
                db_path,
                day=day,
                symbol="OTC",
                open_=o,
                high=h,
                low=l,
                close=c,
                volume=vol if vol and vol > 0 else None,
                pct_change=_finite(q.get("pct_change")),
                regime="mis_otc_o00",
            )
            mis_meta = {
                "status": "ok",
                "date": day,
                "ohlc": [o, h, l, c],
                "source": "mis_otc_o00",
            }
        else:
            mis_meta = {
                "status": "unavailable",
                "reason": "MIS 無完整高低或仍為戳記／盤中未收",
                "date": day or None,
            }
    # 統計完整 vs 戳記
    complete = stamp = 0
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        for o, h, l, c in con.execute(
            "SELECT open, high, low, close FROM index_daily WHERE symbol='OTC'"
        ):
            if None in (o, h, l, c):
                continue
            if o == h == l == c:
                stamp += 1
            elif h >= l:
                complete += 1
    finally:
        con.close()
    return {
        "ok": bool(stamp_res.get("ok")) or mis_wrote > 0,
        "stamp_backfill": stamp_res,
        "mis_ohlc": mis_meta,
        "mis_wrote": mis_wrote,
        "n_complete_ohlc": complete,
        "n_close_stamp": stamp,
        "historical_ohlc": "unavailable",
        "note_zh": "TPEX tradingIndex 僅官方收＋量；完整開高低收僅 MIS 最新結算日可寫，歷史 OHLC 標 unavailable",
    }


def heal_market_margin(
    db_path: str,
    *,
    from_ymd: str = "",
    max_days: int = 90,
    sleep_s: float = 0.22,
) -> Dict[str, Any]:
    """證交所 MI_MARGN 大盤融資金額（仟元）對齊對質日。"""
    from scripts.decade_lab_pulse_backfill import backfill_market_margin

    start = _ymd(from_ymd)
    if not start:
        start = (datetime.now(TAIPEI) - timedelta(days=max(1, max_days) + 20)).strftime(
            "%Y%m%d"
        )
    res = backfill_market_margin(
        __import__("pathlib").Path(db_path),
        from_ymd=start,
        sleep_s=sleep_s,
        max_days=max_days,
    )
    return {"ok": bool(res.get("ok")), **res, "source": "twse_mi_margn_credit"}


def fetch_yahoo_usdtwd_bars(
    *,
    range_: str = "6mo",
    session: Any = None,
) -> List[Dict[str, Any]]:
    """Yahoo TWD=X → 台北日對齊的 OHLC。來源標 yahoo_twd_x（非 CBC／央行牌告）。"""
    import requests

    sess = session
    if sess is None:
        sess = requests.Session()
        sess.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; WayneBot-jiuha-heal/1.0)",
                "Accept": "application/json",
            }
        )
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote('TWD=X', safe='')}?interval=1d&range={range_}"
    )
    try:
        resp = sess.get(url, timeout=45)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
    except Exception:
        logger.debug("Yahoo TWD=X 失敗", exc_info=True)
        return []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    vols = q.get("volume") or []
    out: List[Dict[str, Any]] = []
    prev = None
    for i, ts in enumerate(stamps):
        c = _finite(closes[i]) if i < len(closes) else None
        if c is None or c <= 0:
            continue
        # 落後日對齊：用 Asia/Taipei 日，對齊台股對質 session
        d = datetime.fromtimestamp(int(ts), tz=ZoneInfo("UTC")).astimezone(TAIPEI)
        ymd = d.strftime("%Y%m%d")
        o = _finite(opens[i]) if i < len(opens) else c
        h = _finite(highs[i]) if i < len(highs) else c
        l = _finite(lows[i]) if i < len(lows) else c
        pct = (c / prev - 1.0) * 100.0 if prev and prev > 0 else None
        out.append(
            {
                "date": ymd,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": _finite(vols[i]) if i < len(vols) else None,
                "pct_change": pct,
            }
        )
        prev = c
    return out


def heal_usdtwd(
    db_path: str,
    *,
    range_: str = "6mo",
    align_tw_sessions: bool = True,
) -> Dict[str, Any]:
    """補 USDTWD：Yahoo TWD=X，台北日；可選只留台股開市日列。"""
    bars = fetch_yahoo_usdtwd_bars(range_=range_)
    if not bars:
        return {
            "ok": False,
            "wrote": 0,
            "status": "unavailable",
            "reason": "Yahoo TWD=X 無列",
            "source": "yahoo_twd_x",
        }
    keep = bars
    if align_tw_sessions:
        try:
            from trading_calendar import is_tw_open_calendar_day

            keep = [b for b in bars if is_tw_open_calendar_day(b["date"])]
        except Exception:
            keep = bars
    wrote = 0
    for b in keep:
        wrote += _upsert_index_bar(
            db_path,
            day=b["date"],
            symbol="USDTWD",
            open_=_finite(b.get("open")),
            high=_finite(b.get("high")),
            low=_finite(b.get("low")),
            close=float(b["close"]),
            volume=_finite(b.get("volume")),
            pct_change=_finite(b.get("pct_change")),
            regime="yahoo_twd_x",
        )
    # 對齊報告：相對 TWII 末日
    twii_max = usdtwd_max = None
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = con.execute(
            "SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')) FROM index_daily WHERE symbol='TWII'"
        ).fetchone()
        twii_max = row[0] if row else None
        row2 = con.execute(
            "SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')), COUNT(*) FROM index_daily WHERE symbol='USDTWD'"
        ).fetchone()
        usdtwd_max = row2[0] if row2 else None
        n = int(row2[1] or 0) if row2 else 0
    finally:
        con.close()
    lag_days = None
    if twii_max and usdtwd_max and len(str(twii_max)) == 8 and len(str(usdtwd_max)) == 8:
        try:
            lag_days = (
                datetime.strptime(str(twii_max), "%Y%m%d")
                - datetime.strptime(str(usdtwd_max), "%Y%m%d")
            ).days
        except ValueError:
            lag_days = None
    return {
        "ok": wrote > 0,
        "wrote": wrote,
        "table_n": n,
        "twii_max": twii_max,
        "usdtwd_max": usdtwd_max,
        "lag_vs_twii_days": lag_days,
        "source": "yahoo_twd_x",
        "tz": "Asia/Taipei",
        "note_zh": "標明 yahoo；非央行牌告。對質日無列仍＝缺欄。",
    }


def heal_market_inst_bfi(
    db_path: str,
    *,
    from_ymd: str = "",
    max_days: int = 90,
    sleep_s: float = 0.2,
) -> Dict[str, Any]:
    """證交所 BFI82U 三大法人買賣金額（億）→ market_inst_bfi_daily。

    對質三同步只用外資方向（正＝買超）；缺官方列就不寫。
    """
    from scripts.decade_lab_inst_module import ensure, fetch_bfi, upsert_bfi

    start = _ymd(from_ymd)
    if not start:
        start = (datetime.now(TAIPEI) - timedelta(days=max(1, max_days) + 20)).strftime(
            "%Y%m%d"
        )
    sessions = _session_dates(db_path, limit=max(max_days, 60))
    todo = [d for d in sessions if d >= start][-max_days:]
    con = sqlite3.connect(db_path, timeout=60.0)
    wrote = 0
    errors = 0
    try:
        ensure(con)
        have = {
            _ymd(r[0])
            for r in con.execute("SELECT date FROM market_inst_bfi_daily").fetchall()
        }
        for i, ymd in enumerate(todo):
            if ymd in have:
                continue
            row = fetch_bfi(ymd)
            if not row:
                errors += 1
            else:
                upsert_bfi(con, ymd, row)
                wrote += 1
                have.add(ymd)
            if i < len(todo) - 1:
                time.sleep(max(0.0, sleep_s))
        con.commit()
        n, mn, mx = con.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM market_inst_bfi_daily"
        ).fetchone()
    finally:
        con.close()
    return {
        "ok": wrote > 0 or int(n or 0) > 0,
        "wrote": wrote,
        "errors": errors,
        "todo": len(todo),
        "table_n": int(n or 0),
        "from": mn,
        "to": mx,
        "source": "TWSE_BFI82U",
    }


def optional_fields_status() -> Dict[str, Dict[str, str]]:
    return {
        k: {"status": "unavailable", "reason": v} for k, v in OPTIONAL_UNAVAILABLE.items()
    }


def _session_dates(db_path: str, *, limit: int = 60) -> List[str]:
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
            FROM index_daily WHERE symbol='TWII'
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (max(limit * 2, limit),),
        ).fetchall()
    finally:
        con.close()
    out: List[str] = []
    for d, o, h, l, c in rows:
        day = _ymd(d)
        if len(day) != 8 or None in (o, h, l, c):
            continue
        if o == h == l == c:
            continue
        if h < l:
            continue
        out.append(day)
    out = sorted(out)[-limit:]
    return out


def coverage_report(db_path: str, *, sessions_n: int = 60) -> Dict[str, Any]:
    """近 N 個完整加權交易日：各官方欄覆蓋率（對質可驗證前置）。"""
    sessions = _session_dates(db_path, limit=sessions_n)
    if not sessions:
        return {"ok": False, "sessions": [], "n": 0}
    want = set(sessions)
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        fut = {
            _ymd(r[0])
            for r in con.execute(
                """
                SELECT date FROM futures_inst_oi
                WHERE contract=? AND item=? AND oi_short IS NOT NULL
                """,
                (_TX_CONTRACT, _TX_FOREIGN),
            )
        }
        margin = {
            _ymd(r[0])
            for r in con.execute("SELECT date FROM market_margin_daily WHERE margin_bal_k IS NOT NULL")
        }
        inst_bfi: set[str] = set()
        try:
            inst_bfi = {
                _ymd(r[0])
                for r in con.execute(
                    "SELECT date FROM market_inst_bfi_daily WHERE foreign_net_yi IS NOT NULL"
                )
            }
        except sqlite3.Error:
            inst_bfi = set()
        usdtwd = {
            _ymd(r[0])
            for r in con.execute(
                "SELECT date FROM index_daily WHERE symbol='USDTWD' AND close IS NOT NULL"
            )
        }
        otc_rows = con.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close FROM index_daily WHERE symbol='OTC'"
        ).fetchall()
    finally:
        con.close()
    otc_any: set[str] = set()
    otc_full: set[str] = set()
    for d, o, h, l, c in otc_rows:
        day = _ymd(d)
        if len(day) != 8 or c is None:
            continue
        otc_any.add(day)
        if (
            o is not None
            and h is not None
            and l is not None
            and not (o == h == l == c)
            and h >= l
        ):
            otc_full.add(day)

    def _cov(have: set[str]) -> Dict[str, Any]:
        hit = len(want & have)
        return {"covered": hit, "of": len(want), "pct": round(100.0 * hit / len(want), 1) if want else 0.0}

    return {
        "ok": True,
        "sessions_n": len(sessions),
        "session_from": sessions[0],
        "session_to": sessions[-1],
        "futures_foreign_oi": _cov(fut),
        "market_margin": _cov(margin),
        "market_inst_bfi": _cov(inst_bfi),
        "usdtwd": _cov(usdtwd),
        "otc_any": _cov(otc_any),
        "otc_full_ohlc": _cov(otc_full),
        "optional": optional_fields_status(),
        "timezone": "Asia/Taipei",
        "not_buy_signal": True,
    }


def heal_all(
    db_path: str,
    *,
    from_ymd: str = "",
    sessions_n: int = 60,
    margin_max_days: int = 90,
    otc_max_months: int = 6,
    usdtwd_range: str = "6mo",
    sleep_s: float = 0.2,
) -> Dict[str, Any]:
    """一次補齊對質缺欄；回傳前後覆蓋率。不准改買訊規則。"""
    before = coverage_report(db_path, sessions_n=sessions_n)
    # 對齊窗：從 session_from 往前一點
    start = from_ymd
    if not start and before.get("session_from"):
        start = before["session_from"]
    out: Dict[str, Any] = {
        "ok": True,
        "generated_at": _now_taipei(),
        "timezone": "Asia/Taipei",
        "not_buy_signal": True,
        "before": before,
        "steps": {},
        "optional_unavailable": optional_fields_status(),
    }
    out["steps"]["futures_foreign_oi"] = heal_futures_foreign_oi(
        db_path, from_ymd=start, sleep_s=sleep_s
    )
    out["steps"]["market_margin"] = heal_market_margin(
        db_path, from_ymd=start, max_days=margin_max_days, sleep_s=sleep_s
    )
    out["steps"]["market_inst_bfi"] = heal_market_inst_bfi(
        db_path, from_ymd=start, max_days=margin_max_days, sleep_s=sleep_s
    )
    out["steps"]["otc_index"] = heal_otc_index(
        db_path, max_months=otc_max_months, sleep_s=sleep_s
    )
    out["steps"]["usdtwd"] = heal_usdtwd(db_path, range_=usdtwd_range)
    after = coverage_report(db_path, sessions_n=sessions_n)
    out["after"] = after
    out["delta"] = {
        k: {
            "covered_before": (before.get(k) or {}).get("covered"),
            "covered_after": (after.get(k) or {}).get("covered"),
            "delta": (
                ((after.get(k) or {}).get("covered") or 0)
                - ((before.get(k) or {}).get("covered") or 0)
            ),
        }
        for k in (
            "futures_foreign_oi",
            "market_margin",
            "market_inst_bfi",
            "usdtwd",
            "otc_any",
            "otc_full_ohlc",
        )
        if isinstance(before.get(k), dict)
    }
    return out
