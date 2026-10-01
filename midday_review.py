"""12:45 雙時段比價：只對照今早 06:30 剛離零＋還在零，開盤 vs 現價。

仍一天只推一次（claim 鎖在 main_runner）。不是全市場海選，也不是舊尾盤可切大雜燴。
免費機一次約幾十檔、MIS 每批 40。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

import requests

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.MiddayReview")

# 12:45 只認早報這兩桶（內部鍵）；畫面寫剛離零／還在零。
MIDDAY_BUCKETS: Tuple[str, ...] = ("leave_zero", "golden_buy")
MIDDAY_BUCKET_TITLE = {
    "leave_zero": "剛離零",
    "golden_buy": "還在零",
}

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    }
)


def _num(val, default: float = 0.0) -> float:
    s = str(val or "").replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "N/A", "null", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _live_px(item: dict) -> float:
    z = _num(item.get("z"))
    if z > 0:
        return z
    bid = _num(str(item.get("b") or "").split("_")[0])
    ask = _num(str(item.get("a") or "").split("_")[0])
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    return ask or bid or 0.0


def fetch_mis_batch(
    stock_ids: List[str], db_path: str, *, timeout: float = 12.0
) -> Dict[str, Dict[str, Any]]:
    """每批最多 40 檔，跟現有盤中報價同一支 MIS。回傳含 open／close。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_ALLOW_MIS") != "1":
        return {}
    import sqlite3
    import time

    ids = [str(s).strip() for s in stock_ids if str(s).strip()]
    if not ids:
        return {}
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" * len(ids))
        market_rows = conn.execute(
            f"""
            SELECT d1.stock_id, d1.market FROM daily_quotes d1
            WHERE d1.stock_id IN ({placeholders})
              AND d1.date = (
                  SELECT MAX(d2.date) FROM daily_quotes d2 WHERE d2.stock_id = d1.stock_id
              )
            """,
            ids,
        ).fetchall()
        market = {str(r[0]): (r[1] if r[1] else "TW") or "TW" for r in market_rows}
        for sid in ids:
            market.setdefault(sid, "TW")
    finally:
        conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    req_timeout = max(1.0, float(timeout))
    for i in range(0, len(ids), 40):
        chunk = ids[i : i + 40]
        chs = []
        for sid in chunk:
            m = str(market.get(sid) or "TW").upper()
            from live_quote import mis_ex_ch

            chs.append(mis_ex_ch(sid, m))
        url = (
            "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
            f"?ex_ch={'|'.join(chs)}&json=1&delay=0&_={int(time.time() * 1000)}"
        )
        try:
            resp = _SESSION.get(url, timeout=req_timeout)
            arr = (resp.json() or {}).get("msgArray") or []
        except Exception:
            logger.exception("12:45 MIS 失敗")
            continue
        for item in arr:
            sid = str(item.get("c") or "")
            if not sid:
                continue
            y = _num(item.get("y"))
            px = _live_px(item)
            open_px = _num(item.get("o"))
            pct = round((px - y) / y * 100.0, 2) if y > 0 and px > 0 else _num(item.get("zf") or item.get("ch"))
            chg = round(px - y, 2) if y > 0 and px > 0 else None
            vol = int(_num(item.get("v"), 0))
            out[sid] = {
                "close": px,
                "price": px,
                "open": open_px if open_px > 0 else None,
                "pct": pct,
                "change": chg,
                "volume": vol,
                "yesterday_close": y if y > 0 else None,
                "update_time": item.get("t") or "",
                "name": item.get("n") or "",
            }
        time.sleep(0.15)
    return out


def _px_txt(val: float) -> str:
    x = round(float(val), 2)
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _signed_txt(val: float, nd: int = 2) -> str:
    x = round(float(val), nd)
    if abs(x) < 0.5 * (10 ** (-nd)):
        return "0"
    return f"{x:+.{nd}f}".rstrip("0").rstrip(".")


def open_ref_price(live: Dict[str, Any]) -> float:
    """今日開盤＝MIS o；沒有真開盤就不捏假數。"""
    try:
        o = float((live or {}).get("open") or 0)
    except (TypeError, ValueError):
        o = 0.0
    return o if o > 0 else 0.0


def morning_ref_price(row: Dict[str, Any]) -> float:
    """相容舊測：名單收盤（pick_close）；沒有才退保險進場。新比價請用 open_ref_price。"""
    for key in ("pick_close", "entry_price"):
        try:
            v = float(row.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return 0.0


def format_midday_stock_line(
    row: Dict[str, Any], live: Dict[str, Any], *, dual: bool = False, db_path: str = None
) -> str:
    """純文字列。例：4915 致伸　現在 62.1　開盤 60.8　比開盤 +1.3 元（+2.1%）"""
    sid = str(row.get("stock_id") or "").strip()
    name = str(row.get("stock_name") or "").strip()
    listing = ""
    try:
        from wayne_db import listing_zh

        listing = listing_zh(row)
        if not listing and sid:
            from stock_links import quote_market

            listing = listing_zh(quote_market(sid, db_path))
    except Exception:
        listing = ""
    listing_bit = f"　{listing}" if listing else ""
    prefix = f"{sid} {name}{listing_bit}".strip()
    return _midday_price_suffix(prefix, row, live)


def format_midday_stock_line_html(
    row: Dict[str, Any], live: Dict[str, Any], *, dual: bool = False, db_path: str = None
) -> str:
    """Telegram HTML：代號＋股名＝奇摩手機報價頁藍字（上市 TW／上櫃 TWO）。"""
    sid = str(row.get("stock_id") or "").strip()
    name = str(row.get("stock_name") or "").strip()
    try:
        from stock_links import html_stock_anchor

        anchor = html_stock_anchor(sid, name, db_path) if sid else html_escape(name or "")
    except Exception:
        anchor = html_escape(f"{sid} {name}".strip())
    prefix = f"{anchor}".strip()
    rest = _midday_price_suffix("", row, live)
    if not rest:
        return prefix
    return f"{prefix}{html_escape(rest)}"


def _midday_price_suffix(prefix: str, row: Dict[str, Any], live: Dict[str, Any]) -> str:
    try:
        px = float((live or {}).get("close") or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        return prefix
    open_px = open_ref_price(live)
    if open_px <= 0:
        # 沒開盤價不准用假數；只寫現在。
        bit = f"　現在 {_px_txt(px)}"
        return f"{prefix}{bit}" if prefix else bit
    diff = px - open_px
    pct = (px - open_px) / open_px * 100.0
    bit = (
        f"　現在 {_px_txt(px)}　開盤 {_px_txt(open_px)}　"
        f"比開盤 {_signed_txt(diff)} 元（{_signed_txt(pct, 1)}%）"
    )
    return f"{prefix}{bit}" if prefix else bit


def classify_row(row: Dict[str, Any], live: Dict[str, Any]) -> str:
    """舊高低卡分類（相容測試）；12:45 推播不再用這組分區。"""
    px = float(live.get("close") or 0)
    hi20 = float(row["hi20_close"] or 0) if row.get("hi20_close") is not None else 0.0
    entry = float(row["entry_price"] or 0) if row.get("entry_price") is not None else 0.0
    if px <= 0:
        return "no_quote"
    if hi20 > 0 and px >= hi20 * 0.985:
        return "chase"
    if entry > 0 and px > entry:
        return "above_entry"
    return "ok"


def format_midday_line(as_of: str, groups: Dict[str, List[str]]) -> str:
    """相容舊測：若傳 ok/chase 形狀仍可出字；正式推播走 format_midday_html。"""
    from trading_calendar import format_trading_date_zh

    as_of_label = format_trading_date_zh(as_of) or as_of
    if "leave_zero" in groups or "golden_buy" in groups:
        lines = [
            f"WayneBot 12:45 雙時段比價",
            f"對照今早 06:30 剛離零＋還在零（{as_of_label}）。開盤＝今日開盤價，現在＝約 12:45 成交價。",
            "",
            "【剛離零】" + ("" if groups.get("leave_zero") else "　今天這桶沒有"),
        ]
        lines.extend(groups.get("leave_zero") or [])
        lines += ["", "【還在零　觀察不是買】" + ("" if groups.get("golden_buy") else "　今天這桶沒有")]
        lines.extend(groups.get("golden_buy") or [])
        if groups.get("no_quote"):
            lines += ["", "【盤中沒接到現價】"]
            lines.extend(groups["no_quote"])
        lines.append("")
        lines.append("（WayneBot）")
        text = "\n".join(lines).strip()
        if len(text) > 3900:
            text = text[:3880].rstrip() + "\n…（已截短）"
        return text
    # 舊尾盤可切形狀（測試相容）
    lines = [
        f"WayneBot 尾盤 12:45　現在要做的事",
        "沒買：只看第一區。已貼 20 日高、或現價貴過今早保險進場的，現在不要追。",
        "已買：先看要不要停利，不要加碼。",
        f"對照今早 06:30 名單（{as_of_label}）。不是新海選。現在＝此刻成交價，今早＝今早名單上的價。",
        "",
        "【現在還能看（沒貼高、沒超過保險進場）】" + ("" if groups.get("ok") else "　這一區現在沒有"),
    ]
    lines.extend(groups.get("ok") or [])
    lines += ["", "【已靠近 20 日高　現在不要追】" + ("" if groups.get("chase") else "　無")]
    lines.extend(groups.get("chase") or [])
    lines += ["", "【已貴過今早保險進場　現在不要追】" + ("" if groups.get("above_entry") else "　無")]
    lines.extend(groups.get("above_entry") or [])
    if groups.get("no_quote"):
        lines += ["", "【盤中沒接到現價】"]
        lines.extend(groups["no_quote"])
    lines.append("")
    lines.append("（WayneBot）")
    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3880].rstrip() + "\n…（已截短）"
    return text


def format_midday_html(as_of: str, groups: Dict[str, List[str]]) -> str:
    from trading_calendar import format_trading_date_zh

    def block(title: str, rows: List[str], empty: str) -> str:
        body = "\n".join(rows) if rows else f"<i>{html_escape(empty)}</i>"
        return f"<b>{html_escape(title)}</b>\n{body}"

    as_of_label = format_trading_date_zh(as_of) or as_of
    # 新雙時段比價：剛離零／還在零
    if "leave_zero" in groups or "golden_buy" in groups:
        parts = [
            "<b>12:45 雙時段比價</b>",
            (
                f"對照今早 06:30 <b>剛離零</b>＋<b>還在零</b>"
                f"（{html_escape(as_of_label)}）。"
                "開盤＝今日開盤價，現在＝約 12:45 成交價。還在零＝觀察不是買。"
            ),
            block("剛離零", groups.get("leave_zero") or [], "今天這桶沒有"),
            block("還在零　觀察不是買", groups.get("golden_buy") or [], "今天這桶沒有"),
        ]
        if groups.get("no_quote"):
            parts.append(block("盤中沒接到現價", groups["no_quote"], "無"))
        return "\n\n".join(parts)
    # 舊形狀相容
    parts = [
        "<b>尾盤 12:45　現在要做的事</b>",
        "<i>沒買：只看第一區。已貼 20 日高、或現價貴過今早保險進場的，現在不要追。已買：先看要不要停利，不要加碼。</i>",
        f"對照今早 06:30 名單（{html_escape(as_of_label)}）。不是新海選。現在＝此刻成交價，今早＝今早名單上的價。",
        block("現在還能看（沒貼高、沒超過保險進場）", groups.get("ok") or [], "這一區現在沒有"),
        block("已靠近 20 日高　現在不要追", groups.get("chase") or [], "無"),
        block("已貴過今早保險進場　現在不要追", groups.get("above_entry") or [], "無"),
    ]
    if groups.get("no_quote"):
        parts.append(block("盤中沒接到現價", groups["no_quote"], "無"))
    return "\n\n".join(parts)


def load_midday_bucket_rows(db_path: str, as_of: str) -> List[Dict[str, Any]]:
    """只讀今早 morning 的 leave_zero＋golden_buy；同檔兩桶則留剛離零。"""
    from screen_sessions import ensure_screen_session_table

    ensure_screen_session_table(db_path)
    import sqlite3

    as_of = str(as_of or "").replace("-", "")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(MIDDAY_BUCKETS))
        rows = conn.execute(
            f"""
            SELECT bucket, stock_id, stock_name, pick_close, hi20_close,
                   entry_price, defense_price, chase_warning
            FROM screen_sessions
            WHERE as_of=? AND session='morning' AND bucket IN ({placeholders})
            ORDER BY CASE bucket WHEN 'leave_zero' THEN 0 ELSE 1 END, stock_id
            """,
            (as_of, *MIDDAY_BUCKETS),
        ).fetchall()
    finally:
        conn.close()
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        sid = str(r["stock_id"] or "").strip()
        if not sid or sid in seen:
            continue
        try:
            from universe import is_screen_equity

            if not is_screen_equity(sid, str(r["stock_name"] or "")):
                continue
        except Exception:
            pass
        seen.add(sid)
        out.append(dict(r))
    return out


def run_midday_review(db_path: str, as_of: str) -> Dict[str, Any]:
    rows = load_midday_bucket_rows(db_path, as_of)
    if not rows:
        msg = (
            "今早 06:30 剛離零／還在零還沒存到，沒有可對照的標的。"
            "不是新海選，也不用自己找突破來買。"
        )
        return {
            "html": (
                "<b>12:45 雙時段比價</b>\n"
                f"<i>{html_escape(msg)}</i>"
            ),
            "line_share": "",
            "n": 0,
            "leave_zero_n": 0,
            "golden_buy_n": 0,
        }
    live = fetch_mis_batch([r["stock_id"] for r in rows], db_path)
    groups: Dict[str, List[str]] = {
        "leave_zero": [],
        "golden_buy": [],
        "no_quote": [],
    }
    for r in rows:
        sid = str(r["stock_id"])
        bucket = str(r.get("bucket") or "leave_zero")
        if bucket not in ("leave_zero", "golden_buy"):
            bucket = "leave_zero"
        q = live.get(sid) or {}
        try:
            px = float(q.get("close") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            groups["no_quote"].append(
                format_midday_stock_line_html(r, q, db_path=db_path)
                or html_escape(f"{sid} {r.get('stock_name') or ''}".strip())
            )
            continue
        line = format_midday_stock_line_html(r, q, db_path=db_path)
        groups[bucket].append(line)
    return {
        "html": format_midday_html(as_of, groups),
        "line_share": "",
        "n": len(rows),
        "leave_zero_n": len(groups["leave_zero"]),
        "golden_buy_n": len(groups["golden_buy"]),
        "ok_n": len(groups["leave_zero"]) + len(groups["golden_buy"]),
    }
