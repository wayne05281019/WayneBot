# ==============================================================================
# 三大法人籌碼：盤後寫入、歷史回補、主力買賣超表（含買賣超比／10日累計）
# ==============================================================================
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

logger = logging.getLogger("WayneBot.Chips")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}


def _clean_int(val) -> int:
    s = str(val).replace(",", "").replace("+", "").replace("X", "").strip()
    if s in ("--", "-", "", "N/A", "null", "None"):
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def _shares_to_lots(n: int) -> int:
    if abs(n) >= 1000:
        return int(n // 1000)
    return int(n)


def _pick_col(headers: List[str], row: list, keywords: List[str], fallback: Optional[int] = None, forbid: str = "") -> int:
    for i, h in enumerate(headers):
        hs = str(h)
        if forbid and forbid in hs:
            continue
        if all(k in hs for k in keywords):
            if i < len(row):
                return _clean_int(row[i])
    if fallback is not None and fallback < len(row):
        return _clean_int(row[fallback])
    return 0


def parse_twse_t86(payload: dict) -> Dict[str, Dict[str, int]]:
    fields = payload.get("fields") or []
    data = payload.get("data") or []
    out: Dict[str, Dict[str, int]] = {}
    for r in data:
        if not r:
            continue
        sid = str(r[0]).strip()
        if not sid:
            continue
        foreign = _pick_col(fields, r, ["外陸資買賣超"], 4)
        trust = _pick_col(fields, r, ["投信買賣超"], 10)
        dealer = _pick_col(fields, r, ["自營商買賣超股數"], 11, forbid="外資自營")
        if dealer == 0:
            dealer = _pick_col(fields, r, ["自營商買賣超"], 11, forbid="外資自營")
        three = _pick_col(fields, r, ["三大法人買賣超"], None)
        f_lot, t_lot, d_lot = _shares_to_lots(foreign), _shares_to_lots(trust), _shares_to_lots(dealer)
        three_lot = _shares_to_lots(three) if three else (f_lot + t_lot + d_lot)
        out[sid] = {
            "foreign_net": f_lot,
            "trust_net": t_lot,
            "dealer_net": d_lot,
            "three_net": three_lot,
        }
    return out


def parse_tpex_t86(payload: dict) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    tables = payload.get("tables") or []
    if tables and isinstance(tables[0], dict):
        for tb in tables:
            for r in tb.get("data") or []:
                if not r or len(r) < 5:
                    continue
                sid = str(r[0]).strip()
                if not sid or not sid[0].isdigit():
                    continue
                if len(r) >= 24:
                    foreign, trust, dealer, three = _clean_int(r[4]), _clean_int(r[13]), _clean_int(r[22]), _clean_int(r[23])
                else:
                    foreign = _clean_int(r[4])
                    trust = _clean_int(r[13]) if len(r) > 13 else 0
                    dealer = _clean_int(r[22]) if len(r) > 22 else 0
                    three = _clean_int(r[-1])
                f_lot, t_lot, d_lot = _shares_to_lots(foreign), _shares_to_lots(trust), _shares_to_lots(dealer)
                out[sid] = {
                    "foreign_net": f_lot,
                    "trust_net": t_lot,
                    "dealer_net": d_lot,
                    "three_net": _shares_to_lots(three) if three else (f_lot + t_lot + d_lot),
                }
        return out

    fields = payload.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    data = payload.get("aaData") or payload.get("data") or []
    if data and isinstance(data[0], dict):
        for item in data:
            sid = str(item.get("SecuritiesCompanyCode") or item.get("code") or "").strip()
            if not sid:
                continue
            foreign = _clean_int(item.get("ForeignerNetBuySell") or 0)
            trust = _clean_int(item.get("InvestmentTrustNetBuySell") or 0)
            dealer = _clean_int(item.get("DealerNetBuySell") or 0)
            out[sid] = {
                "foreign_net": _shares_to_lots(foreign),
                "trust_net": _shares_to_lots(trust),
                "dealer_net": _shares_to_lots(dealer),
                "three_net": _shares_to_lots(foreign) + _shares_to_lots(trust) + _shares_to_lots(dealer),
            }
        return out
    for r in data:
        if not r or len(r) < 8:
            continue
        sid = str(r[0]).strip()
        foreign = _clean_int(r[4])
        trust = _clean_int(r[10]) if len(r) > 10 else 0
        dealer = _clean_int(r[13]) if len(r) > 13 else 0
        f_lot, t_lot, d_lot = _shares_to_lots(foreign), _shares_to_lots(trust), _shares_to_lots(dealer)
        out[sid] = {"foreign_net": f_lot, "trust_net": t_lot, "dealer_net": d_lot, "three_net": f_lot + t_lot + d_lot}
    return out


def roc_date(yyyymmdd: str) -> str:
    return f"{int(yyyymmdd[:4]) - 1911}/{yyyymmdd[4:6]}/{yyyymmdd[6:]}"


def fetch_chips_for_date(session: requests.Session, yyyymmdd: str) -> Dict[str, Dict[str, int]]:
    merged: Dict[str, Dict[str, int]] = {}
    tw_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={yyyymmdd}&selectType=ALLBUT0999&response=json"
    try:
        resp = session.get(tw_url, timeout=20)
        if resp.status_code == 200:
            merged.update(parse_twse_t86(resp.json()))
    except Exception as e:
        logger.warning("上市 T86 失敗 %s: %s", yyyymmdd, e)
    roc = roc_date(yyyymmdd)
    two_url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
        f"?l=zh-tw&d={roc}&se=EW&t=D&_={int(time.time() * 1000)}"
    )
    try:
        resp = session.get(two_url, timeout=20)
        if resp.status_code == 200:
            merged.update(parse_tpex_t86(resp.json()))
    except Exception as e:
        logger.warning("上櫃法人失敗 %s: %s", yyyymmdd, e)
    return merged


def apply_chips_to_quotes(db_path: str, yyyymmdd: str, chips: Dict[str, Dict[str, int]]) -> int:
    if not chips:
        return 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    updated = 0
    for sid, c in chips.items():
        cur.execute(
            "UPDATE daily_quotes SET foreign_net=?, trust_net=?, dealer_net=? WHERE date=? AND stock_id=?",
            (c.get("foreign_net", 0), c.get("trust_net", 0), c.get("dealer_net", 0), yyyymmdd, sid),
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated


def update_chips_for_date(db_path: str, yyyymmdd: str, session: Optional[requests.Session] = None) -> int:
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    chips = fetch_chips_for_date(sess, yyyymmdd)
    n = apply_chips_to_quotes(db_path, yyyymmdd, chips)
    logger.info("籌碼寫入 %s：API %s 檔，更新 quotes %s 列", yyyymmdd, len(chips), n)
    return n


def backfill_chips(db_path: str = None, days: int = 30, sleep_s: float = 0.45) -> Dict[str, Any]:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_quotes ORDER BY date DESC LIMIT ?", (days,))]
    conn.close()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    total = 0
    done = []
    for i, d in enumerate(dates):
        n = update_chips_for_date(path, d, sess)
        total += n
        done.append((d, n))
        if i < len(dates) - 1:
            time.sleep(sleep_s)
    return {"dates": len(dates), "updated_rows": total, "detail": done[:8]}


def major_player_rows(db_path: str, stock_id: str, limit: int = 15) -> List[Dict[str, Any]]:
    sid = str(stock_id).strip()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """SELECT date, stock_name, close, volume, foreign_net, trust_net, dealer_net
           FROM daily_quotes WHERE stock_id=? ORDER BY date ASC""",
        (sid,),
    )
    raw = cur.fetchall()
    conn.close()
    if not raw:
        return []
    window: List[int] = []
    acc = 0
    built = []
    for date, sname, close, vol, f, t, d in raw:
        three = int(f or 0) + int(t or 0) + int(d or 0)
        window.append(three)
        acc += three
        if len(window) > 10:
            acc -= window.pop(0)
        vol_i = int(vol or 0)
        ratio = round(three / vol_i * 100.0, 1) if vol_i > 0 else 0.0
        built.append({
            "date": date, "stock_name": sname, "close": close, "volume": vol_i,
            "foreign_net": int(f or 0), "trust_net": int(t or 0), "dealer_net": int(d or 0),
            "three_net": three, "ratio_pct": ratio, "acc_10d": acc,
        })
    built.reverse()
    return built[:limit]


def fetch_major_player_html(stock_id: str, db_path: str = None, limit: int = 15) -> str:
    path = db_path or get_db_path()
    rows = major_player_rows(path, str(stock_id).strip(), limit=limit)
    return format_major_player_html(rows, str(stock_id).strip()) if rows else ""


def format_major_player_html(rows: List[Dict[str, Any]], stock_id: str) -> str:
    if not rows:
        return f"⚠️ 找不到 {stock_id} 的主力買賣超（請先完成盤後法人回補）。"
    name = rows[0].get("stock_name") or stock_id
    lines = [
        f"📊 <b>【主力買賣超】{stock_id} {name}</b>",
        "<code>日期     收盤     量    超比    買賣超  10日累計</code>",
        "───────────────────",
    ]
    for r in rows:
        d = str(r["date"])
        if len(d) == 8:
            d = f"{d[4:6]}/{d[6:]}"
        three = r["three_net"]
        mark = "🔴" if three > 0 else ("🟢" if three < 0 else "⚪")
        lines.append(
            f"{mark} <code>{d}</code> {r['close']:.0f} {r['volume']:,} "
            f"{r['ratio_pct']:+.1f}% <b>{three:+d}</b> {r['acc_10d']:+d}"
        )
    lines.append("\n💡 買賣超＝外資+投信+自營（張）；超比＝三大法人／成交量。")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print(backfill_chips(path, days=20))
    print(format_major_player_html(major_player_rows(path, "2383", 10), "2383"))
