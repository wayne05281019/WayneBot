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
        resp = session.get(tw_url, timeout=40)
        if resp.status_code == 200:
            merged.update(parse_twse_t86(resp.json()))
    except Exception as e:
        logger.warning("上市 T86 失敗 %s: %s", yyyymmdd, e)
    n_tw = len(merged)
    roc = roc_date(yyyymmdd)
    yyyy, mm, dd = yyyymmdd[:4], yyyymmdd[4:6], yyyymmdd[6:]
    two_urls = [
        f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date={yyyy}/{mm}/{dd}&type=Daily&id=&response=json",
        (
            "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
            f"?l=zh-tw&d={roc}&se=EW&t=D&_={int(time.time() * 1000)}"
        ),
    ]
    for two_url in two_urls:
        try:
            resp = session.get(two_url, timeout=40)
            if resp.status_code != 200:
                continue
            parsed = parse_tpex_t86(resp.json())
            if parsed:
                merged.update(parsed)
                break
        except Exception as e:
            logger.warning("上櫃法人失敗 %s: %s", yyyymmdd, e)
    logger.info("法人 %s 上市後 %s 檔，合併後 %s 檔", yyyymmdd, n_tw, len(merged))
    return merged


def apply_chips_to_quotes(db_path: str, yyyymmdd: str, chips: Dict[str, Dict[str, int]]) -> int:
    if not chips:
        return 0
    day = str(yyyymmdd or "").replace("-", "")[:8]
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    updated = 0
    for sid, c in chips.items():
        cur.execute(
            """UPDATE daily_quotes SET foreign_net=?, trust_net=?, dealer_net=?
               WHERE replace(date,'-','')=? AND stock_id=?""",
            (c.get("foreign_net", 0), c.get("trust_net", 0), c.get("dealer_net", 0), day, sid),
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated


def update_chips_for_date(db_path: str, yyyymmdd: str, session: Optional[requests.Session] = None) -> int:
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    day = str(yyyymmdd or "").replace("-", "")[:8]
    chips = fetch_chips_for_date(sess, day)
    n = apply_chips_to_quotes(db_path, day, chips)
    logger.info("籌碼寫入 %s：API %s 檔，更新 quotes %s 列", day, len(chips), n)
    return n


def backfill_chips(db_path: str = None, days: int = 30, sleep_s: float = 0.45) -> Dict[str, Any]:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    dates = [
        str(r[0]).replace("-", "")[:8]
        for r in conn.execute(
            "SELECT DISTINCT replace(date,'-','') FROM daily_quotes ORDER BY 1 DESC LIMIT ?",
            (days,),
        )
    ]
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
    """10 日累計用這檔全部日 K 滾出來，不少算前面的棒。畫面只列最近 limit 列方便讀。"""
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


def load_major_player_rows(db_path: str, stock_id: str, limit: int = 15, allow_fetch: bool = True) -> List[Dict[str, Any]]:
    """讀籌碼列；近日全 0 且允許連網時才回補當日 T86。看這檔出圖不要連網，否則會卡住後面的圖。"""
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    rows = major_player_rows(path, sid, limit=limit)
    if allow_fetch and rows:
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
    return rows


def fetch_major_player_html(stock_id: str, db_path: str = None, limit: int = 15) -> str:
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    rows = load_major_player_rows(path, sid, limit=limit)
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


def _fmt_ymd_short(date_val) -> str:
    d = str(date_val or "").replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{int(d[4:6])}/{int(d[6:8])}"
    return d


def _chips_signed_style(v, C):
    if v > 0:
        return C["hi_fill"], C["hi_ink"]
    if v < 0:
        return C["lo_fill"], C["lo_ink"]
    return C["panel"], C["ink_mute"]


def fit_table_cols(headers, col_vals, fig_w, span, *, fs=11.5, hdr_fs=11.5,
                   weight=800, pad=2.4, min_fs=9.0):
    """表列共用字級：每欄寬＝該欄最寬字＋留白；加總超過 span 就整表等比縮，數字才對齊。

    回傳 (xs 左緣列表含右端, 內文字級, 表頭字級)。
    """
    from cary_navigator import _text_w

    def widths(body_fs, head_fs):
        out = []
        for i, h in enumerate(headers):
            w = _text_w(h, head_fs, fig_w, weight)
            for val in col_vals[i]:
                w = max(w, _text_w(val, body_fs, fig_w, weight))
            out.append(w + pad)
        return out

    body_fs, head_fs = fs, hdr_fs
    cols = widths(body_fs, head_fs)
    while sum(cols) > span and body_fs > min_fs:
        body_fs *= 0.95
        head_fs = min(head_fs, body_fs + 0.2)
        cols = widths(body_fs, head_fs)
    total = sum(cols)
    if total > span and total > 0:
        cols = [w * span / total for w in cols]
    elif total < span and total > 0:
        extra = (span - total) / len(cols)
        cols = [w + extra for w in cols]
    xs = [0.0]
    for w in cols:
        xs.append(xs[-1] + w)
    return xs, body_fs, head_fs


def render_chips_png(rows: List[Dict[str, Any]], save_path: str, stock_id: str = "") -> str:
    """籌碼表：色票與決策卡同一套，欄寬依真實字寬算，同一張表共用字級。"""
    if not rows:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from cary_navigator import _CARD, _fp, _text_w

    C = _CARD
    n = max(len(rows), 1)
    sid = str(stock_id or rows[0].get("stock_id") or "").strip()
    name = str(rows[0].get("stock_name") or sid)
    pad_x, m_top, m_bot = 2.4, 1.0, 1.2
    head_h, sub_h, hdr_h, body_h = 8.6, 3.4, 3.4, 3.25
    gap = 1.15
    H = m_top + head_h + gap + sub_h + hdr_h + n * body_h + m_bot
    fig_w = 7.2
    fig, ax = plt.subplots(figsize=(fig_w, H * 0.078), dpi=160, facecolor=C["page"])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.subplots_adjust(left=0.022, right=0.978, top=0.99, bottom=0.012)

    y = H - m_top - head_h
    ax.add_patch(patches.FancyBboxPatch(
        (pad_x, y), 100 - 2 * pad_x, head_h, boxstyle="round,pad=0,rounding_size=0.95",
        facecolor=C["navy"], edgecolor="none", zorder=2))
    ax.text(pad_x + 2.6, y + head_h - 2.9, f"{sid}　{name}",
            fontproperties=_fp(18, "bold"), color="#FFFFFF", va="center", zorder=3)
    tag = "主力買賣超（張）"
    tag_w = _text_w(tag, 11.2, fig_w, 900) + 3.2
    ax.add_patch(patches.FancyBboxPatch(
        (pad_x + 2.6, y + 1.35), tag_w, 2.85, boxstyle="round,pad=0,rounding_size=0.5",
        facecolor=C["tag"], edgecolor="none", zorder=3))
    ax.text(pad_x + 2.6 + tag_w / 2, y + 2.78, tag, fontproperties=_fp(11.2, "heavy"),
            color="#FFFFFF", ha="center", va="center", zorder=4)
    ax.text(100 - pad_x - 2.6, y + head_h / 2, "WayneBot", fontproperties=_fp(11.5, "bold"),
            color=C["navy_soft"], ha="right", va="center", zorder=3)

    y -= gap + sub_h
    ax.text(pad_x + 0.4, y + sub_h / 2, "買賣超＝三大法人合計　超比＝合計／成交量　單位：張",
            fontproperties=_fp(10), color=C["ink_soft"], va="center", zorder=3)

    headers = ["日期", "收盤", "量", "外資", "投信", "自營", "合計", "超比", "10日累"]
    numeric = {1, 2, 3, 4, 5, 6, 7, 8}
    table = []
    signed = []
    for r in rows:
        d = _fmt_ymd_short(r.get("date"))
        three = int(r.get("three_net") or 0)
        f_n, t_n, d_n = int(r.get("foreign_net") or 0), int(r.get("trust_net") or 0), int(r.get("dealer_net") or 0)
        ratio = float(r.get("ratio_pct") or 0)
        acc = int(r.get("acc_10d") or 0)
        table.append([
            d,
            f"{float(r.get('close') or 0):,.2f}",
            f"{int(r.get('volume') or 0):,}",
            f"{f_n:+,d}",
            f"{t_n:+,d}",
            f"{d_n:+,d}",
            f"{three:+,d}",
            f"{ratio:+.1f}%",
            f"{acc:+,d}",
        ])
        signed.append([None, None, None, f_n, t_n, d_n, three, ratio, acc])

    span = 100 - 2 * pad_x
    col_vals = list(zip(*table)) if table else [[] for _ in headers]
    xs_rel, body_fs, head_fs = fit_table_cols(headers, col_vals, fig_w, span)
    xs = [pad_x + x for x in xs_rel]

    tbl_top = y
    for i, h in enumerate(headers):
        ax.add_patch(patches.Rectangle(
            (xs[i], tbl_top - hdr_h), xs[i + 1] - xs[i], hdr_h,
            facecolor=C["tbl_hdr"], edgecolor=C["tbl_line"], lw=0.7, zorder=2))
        ax.text((xs[i] + xs[i + 1]) / 2, tbl_top - hdr_h / 2, h,
                fontproperties=_fp(head_fs, "bold"), ha="center", va="center",
                color=C["tbl_ink"], zorder=3)

    ry = tbl_top - hdr_h
    right_pad = 0.85
    for row_i, vals in enumerate(table):
        y1 = ry - body_h
        zebra = row_i % 2 == 0
        for i, val in enumerate(vals):
            if i >= 3:
                fc, color = _chips_signed_style(signed[row_i][i], C)
            else:
                fc = C["panel"] if zebra else C["zebra"]
                color = C["ink"]
            ax.add_patch(patches.Rectangle(
                (xs[i], y1), xs[i + 1] - xs[i], body_h,
                facecolor=fc, edgecolor="#E6EBF2", lw=0.5, zorder=2))
            cy = (ry + y1) / 2
            if i in numeric:
                ax.text(xs[i + 1] - right_pad, cy, val, fontproperties=_fp(body_fs, "heavy"),
                        ha="right", va="center", color=color, zorder=3)
            else:
                ax.text((xs[i] + xs[i + 1]) / 2, cy, val, fontproperties=_fp(body_fs, "bold"),
                        ha="center", va="center", color=color, zorder=3)
        ry = y1
    ax.add_patch(patches.Rectangle(
        (pad_x, ry), span, tbl_top - ry, facecolor="none",
        edgecolor=C["tbl_line"], lw=1.1, zorder=4))
    fig.savefig(save_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return save_path


def generate_chips_image(stock_id: str, db_path: str = None, save_path: str = None, limit: int = 15) -> str:
    path = db_path or get_db_path()
    rows = load_major_player_rows(path, str(stock_id).strip(), limit=limit, allow_fetch=False)
    if not rows:
        return ""
    try:
        from config import get_charts_dir
        charts = get_charts_dir()
    except Exception:
        charts = os.path.join("data", "charts")
    out = save_path or os.path.join(charts, f"{stock_id}_chips.png")
    return render_chips_png(rows, out, stock_id=str(stock_id).strip())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print(backfill_chips(path, days=20))
    print(format_major_player_html(major_player_rows(path, "2383", 10), "2383"))
