"""查股時一次抓一檔券商分點，建檔後算「平均買超成本」。

全市場日抓禁止。沒有真分點列就不上主力成本，禁止用 T86×均價推。
證交所／櫃買分點頁常有驗證碼：抓不到就空白；可把官方 CSV 放進 data/broker_csv/。
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Iterable
from urllib.request import Request, urlopen

try:
    from config import get_db_path, taipei_today_str
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

    def taipei_today_str() -> str:
        return datetime.now().strftime("%Y%m%d")

log = logging.getLogger("wayne.broker")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

_DDL = """
CREATE TABLE IF NOT EXISTS broker_branch_trades (
    stock_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    broker TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    buy_shares INTEGER NOT NULL DEFAULT 0,
    sell_shares INTEGER NOT NULL DEFAULT 0,
    buy_amount REAL NOT NULL DEFAULT 0,
    sell_amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (stock_id, trade_date, broker, price, source)
)
"""
_IDX = "CREATE INDEX IF NOT EXISTS idx_broker_stock_date ON broker_branch_trades(stock_id, trade_date)"


def _num(val: Any) -> float:
    s = str(val if val is not None else "").replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "--", "－", "N/A", "null", "None", "nan"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _shares(val: Any) -> int:
    return int(round(_num(val)))


def ensure_schema(db_path: str | None = None) -> str:
    path = db_path or get_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(_DDL)
    conn.execute(_IDX)
    conn.commit()
    conn.close()
    return path


def decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _header_map(cells: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, cell in enumerate(cells):
        s = str(cell or "").replace("\ufeff", "").strip()
        if s:
            out[s] = i
    return out


def _looks_header(cells: list[str]) -> bool:
    joined = "".join(cells)
    return ("券商" in joined or "證券商" in joined) and (
        "買" in joined or "股數" in joined or "價格" in joined
    )


def _row_from_named(cells: list[str], idx: dict[str, int]) -> dict[str, Any] | None:
    def g(*names: str) -> str:
        for name in names:
            if name in idx and idx[name] < len(cells):
                return cells[idx[name]]
        return ""

    broker = str(g("券商", "證券商", "券商名稱", "分點") or "").strip()
    if not broker or broker in ("券商", "證券商", "合計", "總計"):
        return None
    price = _num(g("價格", "成交價", "買進均價", "均價"))
    buy_sh = _shares(g("買進股數", "買進", "買張"))
    sell_sh = _shares(g("賣出股數", "賣出", "賣張"))
    buy_amt = _num(g("買進金額", "買進成交金額"))
    sell_amt = _num(g("賣出金額", "賣出成交金額"))
    if buy_sh <= 0 and sell_sh <= 0 and buy_amt <= 0 and sell_amt <= 0:
        return None
    if buy_amt <= 0 and price > 0 and buy_sh > 0:
        buy_amt = price * buy_sh
    if sell_amt <= 0 and price > 0 and sell_sh > 0:
        sell_amt = price * sell_sh
    if price <= 0 and buy_sh > 0 and buy_amt > 0:
        price = buy_amt / buy_sh
    return {
        "broker": broker[:80],
        "price": price,
        "buy_shares": buy_sh,
        "sell_shares": sell_sh,
        "buy_amount": buy_amt,
        "sell_amount": sell_amt,
    }


def _positional_block(cells: list[str]) -> dict[str, Any] | None:
    """序號,券商,價格,買進股數,賣出股數"""
    if len(cells) < 5:
        return None
    start = 0
    if cells[0].strip().isdigit() or cells[0].strip() in ("", "-"):
        start = 1
    chunk = cells[start : start + 5]
    if len(chunk) < 4:
        return None
    broker = str(chunk[0] or "").strip()
    if not broker or broker.isdigit() or "券商" in broker:
        return None
    price = _num(chunk[1])
    buy_sh = _shares(chunk[2])
    sell_sh = _shares(chunk[3] if len(chunk) > 3 else 0)
    if buy_sh <= 0 and sell_sh <= 0:
        return None
    buy_amt = price * buy_sh if price > 0 else 0.0
    sell_amt = price * sell_sh if price > 0 else 0.0
    return {
        "broker": broker[:80],
        "price": price,
        "buy_shares": buy_sh,
        "sell_shares": sell_sh,
        "buy_amount": buy_amt,
        "sell_amount": sell_amt,
    }


def parse_broker_csv(text: str) -> list[dict[str, Any]]:
    """解析證交所／櫃買分點 CSV（單欄或左右雙表）。"""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []
    reader = csv.reader(io.StringIO(raw))
    header_idx: dict[str, int] | None = None
    dual = False
    rows: list[dict[str, Any]] = []
    for cells in reader:
        cells = [str(c or "").strip() for c in cells]
        if not any(cells):
            continue
        joined = "".join(cells)
        if "驗證碼" in joined or "captcha" in joined.lower() or "<html" in joined.lower():
            return []
        if _looks_header(cells):
            broker_hits = [i for i, c in enumerate(cells) if c in ("券商", "證券商", "券商名稱")]
            dual = len(broker_hits) >= 2
            header_idx = None if dual else _header_map(cells)
            continue
        if dual or (header_idx is None and len(cells) >= 10):
            a = _positional_block(cells[:5])
            b = _positional_block(cells[5:10] if len(cells) >= 10 else [])
            if a:
                rows.append(a)
            if b:
                rows.append(b)
            continue
        if header_idx:
            item = _row_from_named(cells, header_idx)
            if item:
                rows.append(item)
            continue
        item = _positional_block(cells)
        if item:
            rows.append(item)
    return rows


def upsert_branch_rows(
    stock_id: str,
    trade_date: str,
    rows: Iterable[dict[str, Any]],
    *,
    db_path: str | None = None,
    source: str = "csv",
) -> int:
    sid = str(stock_id or "").strip()
    day = str(trade_date or "").replace("-", "")[:8]
    items = list(rows)
    if not sid or len(day) != 8 or not items:
        return 0
    path = ensure_schema(db_path)
    conn = sqlite3.connect(path)
    n = 0
    try:
        conn.execute(
            "DELETE FROM broker_branch_trades WHERE stock_id=? AND trade_date=? AND source=?",
            (sid, day, source),
        )
        for row in items:
            broker = str(row.get("broker") or "").strip()
            if not broker:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO broker_branch_trades
                   (stock_id, trade_date, broker, price, buy_shares, sell_shares,
                    buy_amount, sell_amount, source)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    sid,
                    day,
                    broker,
                    float(row.get("price") or 0),
                    int(row.get("buy_shares") or 0),
                    int(row.get("sell_shares") or 0),
                    float(row.get("buy_amount") or 0),
                    float(row.get("sell_amount") or 0),
                    source,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def aggregate_by_broker(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        name = str(row.get("broker") or "").strip()
        if not name:
            continue
        g = grouped.setdefault(
            name,
            {"broker": name, "buy_shares": 0.0, "sell_shares": 0.0, "buy_amount": 0.0, "sell_amount": 0.0},
        )
        g["buy_shares"] += float(row.get("buy_shares") or 0)
        g["sell_shares"] += float(row.get("sell_shares") or 0)
        buy_amt = float(row.get("buy_amount") or 0)
        sell_amt = float(row.get("sell_amount") or 0)
        price = float(row.get("price") or 0)
        if buy_amt <= 0 and price > 0:
            buy_amt = price * float(row.get("buy_shares") or 0)
        if sell_amt <= 0 and price > 0:
            sell_amt = price * float(row.get("sell_shares") or 0)
        g["buy_amount"] += buy_amt
        g["sell_amount"] += sell_amt
    return list(grouped.values())


def main_cost_from_net_buy(rows: Iterable[dict[str, Any]]) -> float | None:
    """分點表底「平均買超成本」＝買超券商之買進金額／買進股數。"""
    buy_amt = 0.0
    buy_sh = 0.0
    for row in aggregate_by_broker(rows):
        net = float(row["buy_shares"]) - float(row["sell_shares"])
        if net <= 0:
            continue
        buy_amt += float(row["buy_amount"] or 0)
        buy_sh += float(row["buy_shares"] or 0)
    if buy_sh <= 0 or buy_amt <= 0:
        return None
    return round(buy_amt / buy_sh, 2)


def load_branch_rows(
    stock_id: str, trade_date: str | None = None, db_path: str | None = None
) -> list[dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    try:
        if trade_date:
            day = str(trade_date).replace("-", "")[:8]
            cur = conn.execute(
                """SELECT broker, price, buy_shares, sell_shares, buy_amount, sell_amount, trade_date
                   FROM broker_branch_trades WHERE stock_id=? AND trade_date=?""",
                (sid, day),
            )
        else:
            cur = conn.execute(
                """SELECT broker, price, buy_shares, sell_shares, buy_amount, sell_amount, trade_date
                   FROM broker_branch_trades WHERE stock_id=?
                   AND trade_date=(SELECT MAX(trade_date) FROM broker_branch_trades WHERE stock_id=?)""",
                (sid, sid),
            )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "broker": r[0],
                    "price": r[1],
                    "buy_shares": r[2],
                    "sell_shares": r[3],
                    "buy_amount": r[4],
                    "sell_amount": r[5],
                    "trade_date": r[6],
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def main_cost_for_stock(
    stock_id: str, db_path: str | None = None, trade_date: str | None = None
) -> float | None:
    return main_cost_from_net_buy(load_branch_rows(stock_id, trade_date, db_path))


def _csv_drop_path(stock_id: str, trade_date: str, db_path: str | None) -> str:
    root = os.getenv("WAYNE_BROKER_CSV_DIR") or ""
    if not root:
        base = os.path.dirname(db_path or get_db_path()) or "data"
        root = os.path.join(base, "broker_csv")
    return os.path.join(root, f"{stock_id}_{trade_date}.csv")


def load_local_csv(stock_id: str, trade_date: str, db_path: str | None = None) -> list[dict[str, Any]]:
    path = _csv_drop_path(stock_id, trade_date, db_path)
    if not os.path.isfile(path):
        alt = os.path.join(os.path.dirname(path), f"{stock_id}.csv")
        path = alt if os.path.isfile(alt) else path
    if not os.path.isfile(path):
        return []
    with open(path, "rb") as fh:
        text = decode_csv_bytes(fh.read())
    return parse_broker_csv(text)


def _http_bytes(url: str, timeout: float) -> bytes | None:
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            if int(code or 200) >= 400:
                return None
            return resp.read()
    except Exception as exc:
        log.debug("broker fetch skip %s: %s", url, exc)
        return None


def _roc_slash(ymd: str) -> str:
    y, m, d = int(ymd[:4]) - 1911, ymd[4:6], ymd[6:8]
    return f"{y}/{m}/{d}"


def try_fetch_remote_csv(stock_id: str, trade_date: str, timeout: float = 8.0) -> list[dict[str, Any]]:
    """盡力抓一檔。驗證碼／405 就回空，不准造假。"""
    sid = str(stock_id).strip()
    day = str(trade_date).replace("-", "")[:8]
    if not sid or len(day) != 8:
        return []
    roc = _roc_slash(day)
    urls = [
        f"https://bsr.twse.com.tw/bshtm/bsContent.aspx?stockId={sid}",
        (
            "https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/download_ALLCSV.php"
            f"?l=zh-tw&d={roc}&s={sid}"
        ),
    ]
    for url in urls:
        raw = _http_bytes(url, timeout)
        if not raw or len(raw) < 40:
            continue
        text = decode_csv_bytes(raw)
        if "<html" in text.lower() or "驗證" in text[:800]:
            continue
        rows = parse_broker_csv(text)
        if rows:
            return rows
    return []


def ensure_broker_for_stock(
    stock_id: str,
    db_path: str | None = None,
    trade_date: str | None = None,
    *,
    fetch: bool = True,
) -> float | None:
    """查股時呼叫。已有列就直接算成本；沒有才試本地 CSV／遠端一檔。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return None
    try:
        from universe import is_screen_equity

        if not is_screen_equity(sid):
            return None
    except Exception:
        if sid.startswith("00") or sid.startswith("01"):
            return None
    day = str(trade_date or "").replace("-", "")[:8] or taipei_today_str()
    existing = load_branch_rows(sid, day, db_path)
    if not existing:
        existing = load_branch_rows(sid, None, db_path)
        if existing:
            return main_cost_from_net_buy(existing)
    else:
        return main_cost_from_net_buy(existing)
    if not fetch:
        return None
    rows = load_local_csv(sid, day, db_path)
    source = "local_csv"
    if not rows:
        rows = try_fetch_remote_csv(sid, day)
        source = "http"
    if not rows:
        return None
    upsert_branch_rows(sid, day, rows, db_path=db_path, source=source)
    return main_cost_from_net_buy(rows)


def attach_main_cost(card: dict[str, Any], db_path: str | None = None, *, fetch: bool = False) -> dict[str, Any]:
    """只在查股路徑呼叫 fetch=True。海選禁止。"""
    if not isinstance(card, dict) or card.get("error"):
        return card
    sid = str(card.get("stock_id") or "").strip()
    if not sid:
        return card
    day = str(card.get("latest_date") or card.get("db_as_of") or "").replace("-", "")[:8]
    try:
        cost = ensure_broker_for_stock(sid, db_path, day or None, fetch=fetch)
    except Exception:
        log.debug("attach_main_cost fail %s", sid, exc_info=True)
        cost = None
    if cost is not None:
        card["main_cost"] = cost
    return card
