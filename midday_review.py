"""12:45 尾盤複核：只打早上名單的 MIS，用高低卡刪掉不該追的。

不是全市場突破海選。免費機一次約幾十檔、每批 40。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

from screen_sessions import load_morning_rows
from tg_layout import html_escape

logger = logging.getLogger("WayneBot.MiddayReview")

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


def fetch_mis_batch(stock_ids: List[str], db_path: str) -> Dict[str, Dict[str, Any]]:
    """每批最多 40 檔，跟現有盤中報價同一支 MIS。"""
    import sqlite3
    import time

    ids = [str(s).strip() for s in stock_ids if str(s).strip()]
    if not ids:
        return {}
    conn = sqlite3.connect(db_path)
    market = {}
    for sid in ids:
        row = conn.execute(
            "SELECT market FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
        market[sid] = (row[0] if row else "TW") or "TW"
    conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 40):
        chunk = ids[i : i + 40]
        chs = []
        for sid in chunk:
            m = str(market.get(sid) or "TW").upper()
            if m in ("TWO", "OTC", "ROCO", "上櫃"):
                chs.append(f"otc_{sid}.two")
            else:
                chs.append(f"tse_{sid}.tw")
        url = (
            "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
            f"?ex_ch={'|'.join(chs)}&json=1&delay=0&_={int(time.time() * 1000)}"
        )
        try:
            resp = _SESSION.get(url, timeout=12)
            arr = (resp.json() or {}).get("msgArray") or []
        except Exception:
            logger.exception("尾盤 MIS 失敗")
            continue
        for item in arr:
            sid = str(item.get("c") or "")
            if not sid:
                continue
            out[sid] = {
                "close": _live_px(item),
                "pct": _num(item.get("zf") or item.get("ch")),
                "name": item.get("n") or "",
            }
        time.sleep(0.15)
    return out


def classify_row(row: Dict[str, Any], live: Dict[str, Any]) -> str:
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
    lines = [
        f"WayneBot 尾盤可切 12:45（對照今早 06:30 海選 {as_of}）",
        "轉貼哥哥 LINE：整則複製。【建議切入】＝今早有、現價還沒貼月高。不是新的突破海選。",
        "",
        "【建議切入】" + ("" if groups["ok"] else " 無"),
    ]
    lines.extend(groups["ok"] or [])
    lines += ["", "【今早有、現在少追】" + ("" if groups["chase"] else " 無")]
    lines.extend(groups["chase"] or [])
    lines += ["", "【現價高過保險進場、不要追】" + ("" if groups["above_entry"] else " 無")]
    lines.extend(groups["above_entry"] or [])
    if groups["no_quote"]:
        lines += ["", "【盤中沒接到】"]
        lines.extend(groups["no_quote"])
    lines.append("")
    lines.append("（WayneBot）")
    text = "\n".join(lines).strip()
    if len(text) > 3900:
        text = text[:3880].rstrip() + "\n…（已截短）"
    return text


def format_midday_html(as_of: str, groups: Dict[str, List[str]]) -> str:
    def block(title: str, rows: List[str], empty: str) -> str:
        body = "\n".join(html_escape(x) for x in rows) if rows else f"<i>{html_escape(empty)}</i>"
        return f"<b>{html_escape(title)}</b>\n{body}"

    return "\n\n".join(
        [
            f"<b>尾盤可切</b>　對照今早 06:30　昨收 {html_escape(as_of)}",
            "<i>只複核早上名單＋高低卡。下一則純文字轉 LINE。</i>",
            block("建議切入", groups["ok"], "無"),
            block("今早有、現在少追", groups["chase"], "無"),
            block("現價高過保險進場、不要追", groups["above_entry"], "無"),
        ]
    )


def run_midday_review(db_path: str, as_of: str) -> Dict[str, Any]:
    from screen_sessions import overlap_ids

    rows = load_morning_rows(db_path, as_of)
    if not rows:
        msg = (
            f"WayneBot 尾盤可切 12:45\n"
            "今早 06:30 名單還沒存到，沒有可切標的（不是新突破海選）。"
        )
        return {"html": f"<b>尾盤可切</b>\n<i>{html_escape(msg.split(chr(10),1)[-1])}</i>", "line_share": msg, "n": 0}
    both = overlap_ids(db_path, as_of)
    live = fetch_mis_batch([r["stock_id"] for r in rows], db_path)
    groups = {"ok": [], "chase": [], "above_entry": [], "no_quote": []}
    for r in rows:
        sid = str(r["stock_id"])
        name = str(r["stock_name"] or "")
        q = live.get(sid) or {}
        kind = classify_row(r, q)
        px = q.get("close") or 0
        tag = "【雙時段】" if sid in both else ""
        line = f"{tag}{sid} {name} 現{px:g}" if px else f"{tag}{sid} {name}"
        groups[kind].append(line)
    return {
        "html": format_midday_html(as_of, groups),
        "line_share": format_midday_line(as_of, groups),
        "n": len(rows),
        "ok_n": len(groups["ok"]),
    }
