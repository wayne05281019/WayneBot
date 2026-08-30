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
    sid = str(stock_id).strip()
    rows = major_player_rows(path, sid, limit=limit)
    if rows:
        recent = rows[:5]
        if all(int(r.get("three_net") or 0) == 0 for r in recent):
            try:
                conn = sqlite3.connect(path)
                latest = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()[0]
                conn.close()
                if latest:
                    update_chips_for_date(path, str(latest))
            except Exception as e:
                logger.warning("即時回補籌碼失敗: %s", e)
            rows = major_player_rows(path, sid, limit=limit)
    return format_major_player_html(rows, sid) if rows else ""


def format_major_player_html(rows: List[Dict[str, Any]], stock_id: str) -> str:
    if not rows:
        return f"⚠️ 找不到 {stock_id} 的主力買賣超（請先完成盤後法人回補）。"
    name = rows[0].get("stock_name") or stock_id
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(stock_id, name)
    except Exception:
        title = f"{stock_id} {name}"
    lines = [
        f"📊 <b>【主力買賣超】{title}</b>",
        "完整虛線格子見下一則圖（外資／投信／自營分欄，避免對不齊）。",
        "買賣超＝三大法人合計（張）；超比＝合計／成交量。",
    ]
    return "\n".join(lines)


def generate_chips_image(stock_id: str, db_path: str = None, save_path: str = None, limit: int = 15) -> str:
    path = db_path or get_db_path()
    rows = major_player_rows(path, str(stock_id).strip(), limit=limit)
    if not rows:
        return ""
    try:
        from config import get_charts_dir
        charts = get_charts_dir()
    except Exception:
        charts = os.path.join("data", "charts")
    out = save_path or os.path.join(charts, f"{stock_id}_chips.png")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    try:
        from cary_navigator import FONT_PATH, _fp
    except Exception:
        FONT_PATH = None
        def _fp(size, weight="bold"):
            return None

    def ink(size, w="bold"):
        fp = _fp(size, w)
        return {"fontproperties": fp} if fp is not None else {"fontsize": size, "fontweight": "bold"}

    name = rows[0].get("stock_name") or stock_id
    n = len(rows)
    fig_h = 3.1 + n * 0.46
    fig, ax = plt.subplots(figsize=(6.55, fig_h), dpi=175, facecolor="#eef1f6")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.subplots_adjust(left=0.025, right=0.975, top=0.97, bottom=0.02)
    ax.add_patch(patches.FancyBboxPatch((1.2, 92.6), 97.6, 6.6, boxstyle="round,pad=0.12,rounding_size=0.5",
                                        facecolor="#1a237e", edgecolor="none"))
    ax.text(3.2, 96.8, f"{stock_id}  {name}", **ink(16), color="#ffffff", va="center")
    ax.text(3.2, 94.0, "主力買賣超　單位：張　超比＝三大法人／成交量", **ink(10), color="#ffe082", va="center")

    headers = ["日期", "收盤", "量", "外資", "投信", "自營", "合計", "超比", "10日累"]
    xs = [1.6, 13.2, 23.0, 33.2, 43.8, 54.4, 65.0, 76.0, 86.2, 98.2]
    top = 91.4
    hdr_h = 3.4
    body_h = (top - hdr_h - 1.2) / max(n, 1)

    def box(x, y, w, h, fc="#fff"):
        ax.add_patch(patches.Rectangle((x, y), w, h, facecolor=fc, edgecolor="#cfd8dc", linewidth=0.5))

    for i, h in enumerate(headers):
        box(xs[i], top - hdr_h, xs[i + 1] - xs[i], hdr_h, "#e3f2fd")
        ax.text((xs[i] + xs[i + 1]) / 2, top - hdr_h / 2, h, **ink(10), color="#0d47a1", ha="center", va="center")
    y = top - hdr_h
    for r in rows:
        y1 = y - body_h
        three = int(r["three_net"])
        d = str(r["date"])
        if len(d) == 8:
            d = f"{int(d[4:6])}/{int(d[6:])}"
        nums = [
            int(r["foreign_net"]),
            int(r["trust_net"]),
            int(r["dealer_net"]),
            three,
        ]
        vals = [
            d,
            f"{float(r['close']):,.2f}",
            f"{int(r['volume']):,}",
            f"{nums[0]:+d}",
            f"{nums[1]:+d}",
            f"{nums[2]:+d}",
            f"{three:+d}",
            f"{r['ratio_pct']:+.1f}%",
            f"{int(r['acc_10d']):+d}",
        ]
        for i, val in enumerate(vals):
            fc = "#ffffff"
            color = "#000000"
            if i >= 3:
                v = int(r["acc_10d"]) if i == 8 else (three if i in (6, 7) else nums[i - 3])
                if i == 7:
                    v = float(r["ratio_pct"])
                if v > 0:
                    fc, color = "#ffebee", "#b71c1c"
                elif v < 0:
                    fc, color = "#e8f5e9", "#1b5e20"
            box(xs[i], y1, xs[i + 1] - xs[i], body_h, fc)
            ax.text((xs[i] + xs[i + 1]) / 2, (y + y1) / 2, val, **ink(11), color=color, ha="center", va="center")
        y = y1
    plt.savefig(out, dpi=175, facecolor=fig.get_facecolor())
    plt.close()
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print(backfill_chips(path, days=20))
    print(format_major_player_html(major_player_rows(path, "2383", 10), "2383"))
