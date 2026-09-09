"""WayneBot AI 模擬操盤：50 萬本金切 3 等份，平常只用 1 份，永遠留現金。

每位 Telegram 使用者各有一套模擬帳戶（ai_{uid}），與手記持股完全分開。
不會改寫自己的程式碼；進化是調整倉位比例與哪類海選最近準（寫入 ai_lessons／ai_params）。
這是模擬倉，不是真實下單，也不能塞進富邦量化積木。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from portfolio_engine import PortfolioEngine

AI_USER_LEGACY = "wayne_ai"
MAX_SLOTS = 3
CORE_SLOTS = 1  # 平常可動的操作份
DIP_SLOTS = 1  # 大盤超跌才動的抄低份
# 第 3 份永遠留現金，不買滿。
STOP_PCT = -7.0
TAKE_PCT = 8.0
STOP_MULT = 0.93
TAKE_MULT = 1.08


def ai_user_id(telegram_uid: str) -> str:
    """portfolio_engine 內的 AI 模擬帳戶 id（與 Telegram uid 及手記持股分開）。"""
    uid = str(telegram_uid or "").strip()
    if not uid:
        return AI_USER_LEGACY
    if uid.startswith("ai_"):
        return uid
    return f"ai_{uid}"


def ensure_ai_tables(db_path: str) -> None:
    """啟動時確保 AI 相關表與欄位存在。"""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL);")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_nav_log (
            date TEXT NOT NULL,
            nav REAL, cash REAL, market_value REAL, pnl_pct REAL, note TEXT
        );"""
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_nav_log)")}
    if "user_id" not in cols:
        conn.execute(f"ALTER TABLE ai_nav_log ADD COLUMN user_id TEXT DEFAULT '{AI_USER_LEGACY}'")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_lessons (
            user_id TEXT NOT NULL,
            as_of TEXT NOT NULL,
            lesson TEXT NOT NULL,
            encoding TEXT DEFAULT '',
            created_at TEXT,
            PRIMARY KEY (user_id, as_of)
        );"""
    )
    try:
        from screen_review import ensure_ai_fills_table

        ensure_ai_fills_table(db_path)
    except Exception:
        pass
    conn.commit()
    conn.close()


def slot_notional(initial_capital: float, size_mult: float = 1.0) -> float:
    """本金固定切成 3 等份；單檔不超過一份，空槽不把剩錢加進下一檔。"""
    try:
        cap = float(initial_capital or 0)
    except (TypeError, ValueError):
        cap = 0.0
    try:
        mult = float(size_mult or 1.0)
    except (TypeError, ValueError):
        mult = 1.0
    if cap <= 0:
        return 0.0
    return cap / float(MAX_SLOTS) * max(0.4, min(1.2, mult))


def market_deploy_cap(
    db_path: str,
    as_of: str,
    results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> int:
    """今晚最多抱幾檔。平常 1 份；大盤偏空且有抄低名單才動第 2 份。永遠留 1 份現金。"""
    cap = CORE_SLOTS
    snap: Dict[str, Any] = {}
    try:
        from taiwan_market import analyze_taiwan_market

        snap = analyze_taiwan_market(db_path, as_of, db_only=True, page_light=True) or {}
    except Exception:
        snap = {}
    if not snap.get("ok"):
        return cap
    regime = str(snap.get("regime") or "")
    try:
        fr = int(snap.get("falling_risk") or 0)
    except (TypeError, ValueError):
        fr = 0
    vs20 = snap.get("vs_ma20_pct")
    try:
        vs20_n = float(vs20) if vs20 is not None else None
    except (TypeError, ValueError):
        vs20_n = None
    dip_names = bool((results or {}).get("golden_buy") or (results or {}).get("leave_zero"))
    weak = regime == "bear" or fr >= 35 or (vs20_n is not None and vs20_n < -1)
    if weak and dip_names:
        cap = CORE_SLOTS + DIP_SLOTS
    return min(int(cap), MAX_SLOTS - 1)


def _shares_for_budget(price: float, budget: float) -> int:
    if price <= 0 or budget <= 0:
        return 0
    lot_cost = price * 1000.0
    if budget >= lot_cost:
        return int(budget // lot_cost) * 1000
    return max(0, int(budget // price))


def _quotes_from_results(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    quotes: Dict[str, Dict[str, Any]] = {}
    for key in (
        "revenue_cross",
        "leave_zero",
        "golden_buy",
        "select_01",
        "select_02",
        "select_03",
        "day_trade",
        "overnight",
    ):
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid:
                continue
            quotes[sid] = {
                "close": float(it.get("close") or 0),
                "stock_name": it.get("stock_name") or it.get("name") or "",
                "is_k20_warning": bool(it.get("chase_warning")),
                "d20": 0.0,
                "pct_change": it.get("pct_change") or 0,
            }
    return quotes


def _candidates(
    results: Dict[str, List[Dict[str, Any]]], db_path: str = "", *, dip_only: bool = False
) -> List[Dict[str, Any]]:
    """隔夜模擬倉：佈局／隔日沖，不拿當沖名單去隔夜。貼月高、美股電子逆風不買。

    dip_only：第二份只准抄低（重點觀察／黃金買點），不准拿周帶量去填。
    """
    out, seen = [], set()
    keys = (
        ("leave_zero", "黃金買點：獲利離零"),
        ("golden_buy", "重點觀察：60低超跌"),
        ("revenue_cross", "優先看：營收轉強×突破"),
        ("overnight", "隔日沖佈局"),
        ("select_01", "周帶量突破"),
    )
    if dip_only:
        keys = (
            ("golden_buy", "重點觀察：60低超跌"),
            ("leave_zero", "黃金買點：獲利離零"),
        )
    for key, reason in keys:
        if db_path:
            try:
                from screen_review import bucket_weight

                if bucket_weight(db_path, key) <= 0:
                    continue
            except Exception:
                pass
        for it in results.get(key) or []:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if not sid or sid in seen:
                continue
            try:
                from universe import is_screen_equity

                if not is_screen_equity(sid, str(it.get("stock_name") or it.get("name") or "")):
                    continue
            except Exception:
                pass
            if it.get("chase_warning") or it.get("us_peer_headwind") or it.get("us_risk_off"):
                continue
            if float(it.get("close") or 0) <= 0:
                continue
            seen.add(sid)
            row = dict(it)
            row["ai_reason"] = reason
            row["ai_bucket"] = key
            out.append(row)
    return out


def _held_is_equity(stock_id: str, stock_name: str = "") -> bool:
    """持倉是否現股／KY。匯入失敗時不當 ETF 清掉。"""
    try:
        from universe import is_screen_equity

        return is_screen_equity(stock_id, stock_name)
    except Exception:
        return True


def _official_close(quotes: Dict[str, Dict[str, Any]], stock_id: str) -> float:
    """只認 quotes 裡的官方收盤；沒有就不賣，禁止用成本價充當成交價。"""
    q = quotes.get(stock_id) or {}
    try:
        px = float(q.get("close") or 0)
    except (TypeError, ValueError):
        return 0.0
    return px if px > 0 else 0.0


def _size_mult_key(user_id: str) -> str:
    return f"size_mult:{user_id}"


def _load_size_mult(db_path: str, user_id: str = AI_USER_LEGACY) -> float:
    ensure_ai_tables(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT v FROM ai_params WHERE k=?",
        (_size_mult_key(user_id),),
    ).fetchone()
    if row is None and user_id != AI_USER_LEGACY:
        row = conn.execute("SELECT v FROM ai_params WHERE k='size_mult'").fetchone()
    conn.close()
    return float(row[0]) if row else 1.0


def _save_size_mult(db_path: str, mult: float, user_id: str) -> None:
    ensure_ai_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO ai_params (k, v) VALUES (?, ?);",
        (_size_mult_key(user_id), max(0.4, min(1.2, mult))),
    )
    conn.commit()
    conn.close()


def ensure_ai_user(engine: PortfolioEngine, telegram_uid: str) -> str:
    """確保此 Telegram 使用者有獨立 AI 模擬帳戶。不再複製舊 wayne_ai 倉。"""
    user_id = ai_user_id(telegram_uid)
    engine.ensure_user_exists(user_id)
    return user_id


def _adapt_from_trades(engine: PortfolioEngine, db_path: str, user_id: str) -> str:
    """用實際賣出損益＋買進隔日復盤調倉位倍數。"""
    notes = []
    conn = engine._get_connection()
    rows = conn.execute(
        """SELECT pnl_pct FROM trade_logs
           WHERE user_id=? AND action='SELL' AND pnl_pct IS NOT NULL
           ORDER BY id DESC LIMIT 10;""",
        (user_id,),
    ).fetchall()
    conn.close()
    wr_sell = None
    if len(rows) >= 5:
        wins = sum(1 for r in rows if float(r["pnl_pct"]) > 0)
        wr_sell = wins / len(rows)
        notes.append(f"賣出近 {len(rows)} 筆勝率 {wr_sell:.0%}")

    wr_buy = None
    try:
        from screen_review import ensure_ai_fills_table

        ensure_ai_fills_table(db_path)
        conn = sqlite3.connect(db_path)
        fills = conn.execute(
            """
            SELECT next_pct FROM ai_fills
            WHERE user_id=? AND action='BUY' AND next_pct IS NOT NULL
            ORDER BY id DESC LIMIT 10
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        if len(fills) >= 5:
            hits = sum(1 for r in fills if float(r[0]) > 0)
            wr_buy = hits / len(fills)
            notes.append(f"買進隔日近 {len(fills)} 筆勝率 {wr_buy:.0%}")
    except sqlite3.OperationalError:
        wr_buy = None

    cur = _load_size_mult(db_path, user_id)
    wr = wr_buy if wr_buy is not None else wr_sell
    if wr is None:
        return "樣本不足，維持原倉位比例（平常只用 1 等份）"
    if wr < 0.35:
        _save_size_mult(db_path, cur * 0.85, user_id)
        notes.append("縮小單筆倉位")
    elif wr > 0.6:
        _save_size_mult(db_path, cur * 1.05, user_id)
        notes.append("略增單筆倉位")
    else:
        notes.append("倉位倍數維持")
    return "，".join(notes)


def current_ai_encoding(db_path: str, user_id: str = AI_USER_LEGACY) -> Dict[str, Any]:
    """模擬倉下一輪會用的參數。進場規則仍是高低卡，這裡只調倉位與哪類少買。"""
    from screen_review import BUCKETS, bucket_weight

    uid = str(user_id or AI_USER_LEGACY)
    weights = {key: float(bucket_weight(db_path, key)) for key, _label in BUCKETS}
    return {
        "entry": "leave_zero",
        "observe": "golden_buy",
        "not_entry": "red_arrow",
        "stop_pct": STOP_PCT,
        "take_pct": TAKE_PCT,
        "core_slots": CORE_SLOTS,
        "dip_slots": DIP_SLOTS,
        "cash_slots": 1,
        "size_mult": _load_size_mult(db_path, uid),
        "bucket_w": weights,
    }


def persist_ai_lesson(
    db_path: str,
    user_id: str,
    as_of: str,
    lesson: str,
    encoding: Optional[Dict[str, Any]] = None,
) -> None:
    """每一輪模擬操盤把進化結果存起來，給週報／以後對量化積木用。"""
    import json
    from datetime import datetime

    as_of = str(as_of or "").replace("-", "")[:8]
    uid = str(user_id or AI_USER_LEGACY)
    if not as_of or not uid:
        return
    ensure_ai_tables(db_path)
    enc = encoding if encoding is not None else current_ai_encoding(db_path, uid)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO ai_lessons(user_id, as_of, lesson, encoding, created_at)
           VALUES (?,?,?,?,?)""",
        (
            uid,
            as_of,
            str(lesson or "").strip(),
            json.dumps(enc, ensure_ascii=False, sort_keys=True),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()


def _evolve_week_key(user_id: str, as_of: str) -> str:
    as_of = str(as_of or "").replace("-", "")[:8]
    try:
        from datetime import datetime

        iso = datetime.strptime(as_of, "%Y%m%d").isocalendar()
        week = f"{iso[0]}W{int(iso[1]):02d}"
    except Exception:
        week = as_of or "none"
    return f"evolve_week:{user_id}:{week}"


def should_send_weekly_evolve(db_path: str, user_id: str, as_of: str) -> bool:
    """週五收盤後那一輪才寄週報；同一週不重寄。"""
    as_of = str(as_of or "").replace("-", "")[:8]
    try:
        from datetime import datetime

        if datetime.strptime(as_of, "%Y%m%d").weekday() != 4:
            return False
    except Exception:
        return False
    ensure_ai_tables(db_path)
    key = _evolve_week_key(user_id, as_of)
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT v FROM ai_params WHERE k=?", (key,)).fetchone()
    conn.close()
    return row is None


def mark_weekly_evolve_sent(db_path: str, user_id: str, as_of: str) -> None:
    ensure_ai_tables(db_path)
    key = _evolve_week_key(user_id, as_of)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)", (key, 1.0))
    conn.commit()
    conn.close()


def format_evolve_report_html(db_path: str, user_id: str = AI_USER_LEGACY) -> str:
    """給人看的進化週報／編碼卡。不是買訊，也不能貼進下單 App 當腳本。"""
    from tg_layout import html_escape

    from screen_review import BUCKETS

    uid = str(user_id or AI_USER_LEGACY)
    ensure_ai_tables(db_path)
    enc = current_ai_encoding(db_path, uid)
    labels = dict(BUCKETS)
    size_mult = float(enc.get("size_mult") or 1.0)
    lines = [
        "<b>AI倉進化回報</b>",
        "表面仍是模擬買進／賣出。背後只調倉位倍數與哪類海選少買。",
        "進場只認高低卡表的黃金買點。紅箭頭不是買訊。不會改程式，也不能塞進富邦量化積木。",
        "",
        "<b>目前編碼</b>",
        "進場＝高低卡黃金買點（獲利剛離 0）",
        "第二份＝大盤偏空才買重點觀察／黃金買點",
        f"停損 {STOP_PCT:.0f}%　停利 ＋{TAKE_PCT:.0f}%　平常 {CORE_SLOTS} 份、永遠留 1 份現金",
        f"單筆倍數 {size_mult:.2f}（0.40～1.20，依近況勝率縮放）",
    ]
    wbits = []
    for key, label in BUCKETS:
        w = float((enc.get("bucket_w") or {}).get(key) or 0)
        if w <= 0:
            wbits.append(f"{label} 暫停")
        elif abs(w - 1.0) >= 0.05:
            wbits.append(f"{label} ×{w:.2f}")
    if wbits:
        lines.append("弱的類別：" + "　".join(wbits[:6]))
    else:
        lines.append("各桶權重維持，沒有類別被關掉。")
    lines.extend(
        [
            "",
            "<b>以後要接到富邦量化積木</b>",
            "用手把上面條件打進積木（OHLC／均線／近 60 曆日低）。不要把 WayneBot 貼進下單軟體。",
            "這份編碼只給你對照；真倉進場仍只認高低卡表。",
        ]
    )
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT as_of, lesson FROM ai_lessons
        WHERE user_id=? ORDER BY as_of DESC LIMIT 8
        """,
        (uid,),
    ).fetchall()
    conn.close()
    if rows:
        lines.extend(["", "<b>近況日誌</b>"])
        for as_of, lesson in rows:
            day = _fmt_ymd(str(as_of or ""))
            text = html_escape(str(lesson or "").strip() or "—")
            lines.append(f"• {html_escape(day)}　{text}")
    else:
        lines.extend(["", "還沒有存過進化日誌。今晚 20:00 模擬操盤後會開始寫。"])
    return "\n".join(lines)


def _snapshot(
    engine: PortfolioEngine, db_path: str, user_id: str, as_of: str, quotes: dict, note: str
) -> None:
    s = engine.get_portfolio_summary(user_id, quotes)
    ensure_ai_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO ai_nav_log (user_id, date, nav, cash, market_value, pnl_pct, note)
           VALUES (?, ?, ?, ?, ?, ?, ?);""",
        (user_id, as_of, s["total_assets"], s["cash"], s["stock_market_value"], s["total_pnl_pct"], note),
    )
    conn.commit()
    conn.close()


def _last_buy_reasons(engine: PortfolioEngine, user_id: str) -> Dict[str, str]:
    conn = engine._get_connection()
    rows = conn.execute(
        """
        SELECT stock_id, reason FROM trade_logs
        WHERE user_id=? AND action='BUY' AND id IN (
            SELECT MAX(id) FROM trade_logs WHERE user_id=? AND action='BUY' GROUP BY stock_id
        )
        """,
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return {str(r["stock_id"]): str(r["reason"] or "") for r in rows}


def _realized_pnl(engine: PortfolioEngine, user_id: str) -> float:
    conn = engine._get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(realized_pnl),0) FROM trade_logs WHERE user_id=? AND action='SELL'",
        (user_id,),
    ).fetchone()
    conn.close()
    return float(row[0] or 0) if row else 0.0


def _recent_fills(engine: PortfolioEngine, user_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    conn = engine._get_connection()
    rows = conn.execute(
        """
        SELECT date, action, stock_id, stock_name, shares, price, realized_pnl, pnl_pct, reason
        FROM trade_logs WHERE user_id=? ORDER BY id DESC LIMIT ?
        """,
        (user_id, int(limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fmt_ymd(raw: str) -> str:
    s = str(raw or "").replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return str(raw or "")


def _fmt_lots_html(shares: int) -> str:
    from tg_layout import html_qty_tight

    sh = int(shares or 0)
    if sh >= 1000 and sh % 1000 == 0:
        return html_qty_tight(sh / 1000.0, "張", signed=False)
    return html_qty_tight(sh, "股", signed=False)


def ai_desk_positions(
    engine: PortfolioEngine, telegram_uid: str, quotes: Optional[dict] = None
) -> List[Dict[str, Any]]:
    """AI 倉持倉列，給主選單點股名查圖用。"""
    user_id = ensure_ai_user(engine, telegram_uid)
    quotes = dict(quotes or {})
    held0 = engine.get_portfolio_summary(user_id, {})
    quotes = engine.load_quotes_for([p["stock_id"] for p in held0["positions"]], quotes)
    s = engine.get_portfolio_summary(user_id, quotes)
    return list(s.get("positions") or [])


def _ai_phone_lines(text: str) -> List[str]:
    """AI 倉白話折行：手機不要一長條。"""
    from tg_layout import wrap_cjk_lines

    raw = str(text or "").strip()
    if not raw:
        return []
    return wrap_cjk_lines(raw, 18, unit="chars") or [raw]


def format_ai_desk_pages(
    engine: PortfolioEngine, telegram_uid: str, quotes: Optional[dict] = None
) -> List[str]:
    """帳戶／持倉／成交／復盤分開則，避免 Telegram 一則塞滿。"""
    from tg_layout import (
        html_escape,
        html_last_move,
        html_money,
        html_num_paren,
        html_pct,
        html_price,
        kv_html_compact,
        kv_compact,
        price_change,
        section_eq,
        _plain_num,
    )

    user_id = ensure_ai_user(engine, telegram_uid)
    quotes = dict(quotes or {})
    held0 = engine.get_portfolio_summary(user_id, {})
    quotes = engine.load_quotes_for([p["stock_id"] for p in held0["positions"]], quotes)
    s = engine.get_portfolio_summary(user_id, quotes)
    size_mult = _load_size_mult(engine.db_path, user_id)
    initial = float(s.get("initial_capital") or 500000)
    slot = slot_notional(initial, size_mult)
    used = int(s["positions_count"])
    reasons = _last_buy_reasons(engine, user_id)
    realized = _realized_pnl(engine, user_id)
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in s["positions"])

    empty = max(0, MAX_SLOTS - used)
    dots = ("●" * used) + ("○" * empty)
    head = [
        section_eq("AI 模擬帳戶"),
        "假錢對照組，不是真下單。",
        "本金 50 萬分 3 份，平常最多用 1 份。",
        "超跌才動第 2 份，第 3 份留現金。",
        "停損 −7%、停利 ＋8%。只買黃金買點。",
        "",
        "────────────────",
        "<b>帳戶</b>",
        kv_html_compact("總資產", html_money(s["total_assets"], signed=False, compact=True)),
        kv_html_compact("現金", html_money(s["cash"], signed=False, compact=True)),
        kv_html_compact("市值", html_money(s["stock_market_value"], signed=False, compact=True)),
        kv_html_compact("未實現", html_money(unreal, compact=True)),
        kv_html_compact("已實現", html_money(realized, compact=True)),
        kv_html_compact("總損益", html_num_paren(_plain_num(s["total_pnl"], signed=True), s["total_pnl_pct"], compact=True)),
        "",
        "────────────────",
        "<b>槽位</b>",
        kv_compact("已用槽", f"{dots}　{used}/{MAX_SLOTS}"),
        kv_compact("每槽上限", f"{slot:,.0f}　倍數 {size_mult:.2f}"),
        kv_compact("本金", f"{initial:,.0f}"),
        "空心＝留現金，不是三份都要買滿。",
    ]
    pages: List[str] = []
    if not s["positions"]:
        head.extend(["", "────────────────", "<b>持倉</b>"])
        head.append("尚無持倉。平常最多 1 檔。")
        head.append(f"每槽 {slot:,.0f}。另兩份留著抄低或加碼。")
        pages.append("\n".join(head))
    else:
        pages.append("\n".join(head))
        sell_notes: Dict[str, str] = {}
        readings: Dict[str, Dict[str, str]] = {}
        try:
            from sell_discipline import sell_notes_for_stocks

            sell_notes = sell_notes_for_stocks(
                [p.get("stock_id") for p in s["positions"]],
                engine.db_path,
                full=True,
                readings=readings,
            )
        except Exception:
            sell_notes = {}
            readings = {}
        pos_pages: List[str] = []
        for i, p in enumerate(s["positions"]):
            sid = p["stock_id"]
            name = p.get("stock_name") or ""
            cost = float(p["cost_price"] or 0)
            last = float(p["current_price"] or cost)
            pct = p.get("pct_change")
            chg = price_change(last, pct) if pct is not None else last - cost
            move_pct = float(pct) if pct is not None else float(p.get("pnl_pct") or 0)
            stop_px = float(p.get("stop_price") or (cost * STOP_MULT))
            take_px = float(p.get("take_price") or (cost * TAKE_MULT))
            try:
                from stock_links import html_stock_anchor

                title = html_stock_anchor(sid, name, engine.db_path)
            except Exception:
                title = f"<code>{html_escape(sid)}</code> {html_escape(name)}"
            sh = int(p["shares"] or 0)
            qty = _fmt_lots_html(sh)
            cost_s = html_price(cost, compact=True)
            if chg is not None:
                last_s = html_last_move(last, chg, move_pct, compact=True)
            else:
                last_s = html_price(last, compact=True)
            block = [
                "<b>持倉</b>" if i == 0 else "",
                f"<b>第 {i + 1} 槽</b>　{title}",
                f"{qty}　成本 {cost_s}　現 {last_s}",
                kv_html_compact(
                    "未實現",
                    html_num_paren(_plain_num(p["unrealized_pnl"], signed=True), p["pnl_pct"], compact=True),
                ),
                kv_html_compact("停損", html_num_paren(f"{stop_px:,.2f}", STOP_PCT, compact=True)),
                kv_html_compact("停利", html_num_paren(f"{take_px:,.2f}", TAKE_PCT, compact=True)),
            ]
            reason = reasons.get(sid) or "海選紀律"
            bought = _fmt_ymd(p.get("buy_date") or "")
            block.extend(_ai_phone_lines(f"進場　{reason} {bought}".strip()))
            note = sell_notes.get(sid) or ""
            if note:
                block.extend(_ai_phone_lines(f"紀律：{note}"))
            month = str((readings.get(sid) or {}).get("monthly_stage_short") or "").strip()
            if month:
                block.extend(_ai_phone_lines(f"月K　{month}"))
            pos_pages.append("\n".join(x for x in block if x))
        held_txt = "\n\n".join(pos_pages)
        if empty > 0:
            held_txt += f"\n空槽 {empty}/{MAX_SLOTS}　每槽仍 {slot:,.0f}"
        pages.append(held_txt)

    fill_lines: List[str] = []
    fills = _recent_fills(engine, user_id, 8)
    if fills:
        fill_lines.extend(["<b>成交紀錄</b>"])
        for i, t in enumerate(fills):
            if i:
                fill_lines.append("────────")
            act = "買" if str(t.get("action") or "").upper() == "BUY" else "賣"
            lot = _fmt_lots_html(int(t.get("shares") or 0))
            extra = ""
            if str(t.get("action") or "").upper() == "SELL":
                extra = " " + html_num_paren(
                    _plain_num(t.get("realized_pnl"), signed=True), t.get("pnl_pct"), compact=True
                )
            sid = html_escape(t.get("stock_id"))
            nm = html_escape(t.get("stock_name") or "")
            fill_lines.append(f"{_fmt_ymd(t.get('date'))}　{act}　<code>{sid}</code> {nm}".strip())
            fill_lines.append(f"{lot} @{html_price(t.get('price'), compact=True)}{extra}")
            if t.get("reason"):
                fill_lines.append(html_escape(str(t["reason"])))

    ensure_ai_tables(engine.db_path)
    conn = sqlite3.connect(engine.db_path)
    try:
        rows = conn.execute(
            "SELECT date, nav, pnl_pct FROM ai_nav_log WHERE user_id=? ORDER BY date DESC LIMIT 5;",
            (user_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    if rows:
        if fill_lines:
            fill_lines.extend(["", "────────────────"])
        fill_lines.append("<b>淨值</b>")
        for date, nav, pnl in rows:
            fill_lines.append(
                f"• {_fmt_ymd(date)} {html_money(nav, signed=False)} {html_pct(pnl).strip()}"
            )
    if fill_lines:
        pages.append("\n".join(fill_lines))

    try:
        from screen_review import format_ai_review_html, format_review_html

        review_bits: List[str] = []
        for blob in (
            format_ai_review_html(engine.db_path, user_id=user_id),
            format_review_html(engine.db_path),
        ):
            txt = str(blob or "").strip()
            if not txt:
                continue
            if "還沒有" in txt and len(txt) < 220:
                continue
            review_bits.append(txt)
        if review_bits:
            pages.append("\n\n────────────────\n\n".join(review_bits))
    except Exception:
        pass
    return [p for p in pages if str(p or "").strip()]


def format_ai_desk_html(
    engine: PortfolioEngine, telegram_uid: str, quotes: Optional[dict] = None
) -> str:
    """券商帳戶式全文；Telegram 請走 format_ai_desk_pages 分則。"""
    return "\n\n────────────────\n\n".join(format_ai_desk_pages(engine, telegram_uid, quotes))


def _record_fill(
    db_path: str, user_id: str, as_of: str, action: str, result: Dict[str, Any], reason: str = "", bucket: str = ""
) -> None:
    try:
        from screen_review import persist_ai_fill

        persist_ai_fill(
            db_path,
            user_id=user_id,
            as_of=as_of,
            stock_id=result.get("stock_id") or "",
            stock_name=result.get("stock_name") or "",
            action=action,
            price=float(result.get("price") or 0),
            shares=int(result.get("shares") or result.get("sold_shares") or 0),
            amount=float(result.get("total_cost") or result.get("net_proceeds") or 0),
            reason=reason or "",
            bucket=bucket or "",
            realized_pnl=float(result.get("realized_pnl") or 0),
            pnl_pct=float(result.get("pnl_pct") or 0),
        )
    except Exception:
        pass


def run_ai_desk(
    db_path: str,
    telegram_uid: str,
    results: Dict[str, List[Dict[str, Any]]],
    as_of: str,
) -> Dict[str, Any]:
    engine = PortfolioEngine(db_path)
    user_id = ensure_ai_user(engine, telegram_uid)
    try:
        from screen_review import score_ai_fills

        score_ai_fills(db_path)
    except Exception:
        pass
    lesson = _adapt_from_trades(engine, db_path, user_id)
    size_mult = _load_size_mult(db_path, user_id)

    seed = engine.get_portfolio_summary(user_id, {})
    result_quotes = _quotes_from_results(results)
    quotes = engine.load_quotes_for(
        [p["stock_id"] for p in seed["positions"]],
        result_quotes,
    )

    sold = []
    # 舊模擬倉若抱著 ETF，先用官方收盤清掉，避免佔滿 3 槽買不進現股。
    for p in list(seed["positions"]):
        sid = str(p.get("stock_id") or "")
        name = str(p.get("stock_name") or "")
        if not sid or _held_is_equity(sid, name):
            continue
        price = _official_close(quotes, sid)
        if price <= 0:
            continue
        r = engine.sell(
            user_id,
            as_of,
            sid,
            price,
            shares=int(p.get("shares") or 0),
            reason="非現股／KY，清出模擬槽",
        )
        if r.get("success"):
            sold.append(r["msg"])
            _record_fill(db_path, user_id, as_of, "SELL", r, reason="非現股／KY，清出模擬槽")

    for sig in engine.evaluate_exit_signals(user_id, quotes):
        r = engine.sell(
            user_id, as_of, sig["stock_id"], float(sig["current_price"]),
            shares=int(sig["shares"]), reason=sig["reason"],
        )
        if r.get("success"):
            sold.append(r["msg"])
            _record_fill(db_path, user_id, as_of, "SELL", r, reason=sig.get("reason") or "")

    summary = engine.get_portfolio_summary(user_id, quotes)
    for p in list(summary["positions"]):
        if p["pnl_pct"] <= STOP_PCT:
            r = engine.sell(user_id, as_of, p["stock_id"], p["current_price"], reason="紀律停損 -7%")
            if r.get("success"):
                sold.append(r["msg"])
                _record_fill(db_path, user_id, as_of, "SELL", r, reason="紀律停損 -7%")
        elif p["pnl_pct"] >= TAKE_PCT:
            r = engine.sell(user_id, as_of, p["stock_id"], p["current_price"], reason="紀律停利 +8%")
            if r.get("success"):
                sold.append(r["msg"])
                _record_fill(db_path, user_id, as_of, "SELL", r, reason="紀律停利 +8%")

    summary = engine.get_portfolio_summary(user_id, quotes)
    held = {p["stock_id"] for p in summary["positions"]}
    max_held = market_deploy_cap(db_path, as_of, results)
    slots = max(0, max_held - len(held))
    bought = []
    initial = float(summary.get("initial_capital") or 500000)
    while slots > 0:
        dip_only = len(held) >= CORE_SLOTS
        cands = _candidates(results, db_path, dip_only=dip_only)
        picked = None
        for it in cands:
            sid = str(it.get("stock_id") or it.get("code") or "")
            if sid in held:
                continue
            price = float(it.get("close") or 0)
            name = it.get("stock_name") or it.get("name") or sid
            if price <= 0:
                continue
            cash = engine.get_cash(user_id)
            budget = min(slot_notional(initial, size_mult), cash)
            shares = _shares_for_budget(price, budget)
            if shares <= 0:
                continue
            reason = it.get("ai_reason") or "海選紀律"
            r = engine.buy(
                user_id, as_of, sid, name, price, shares,
                reason=reason,
                strategy_type="MOMENTUM",
            )
            if r.get("success"):
                bought.append(r["msg"])
                held.add(sid)
                slots -= 1
                _record_fill(
                    db_path, user_id, as_of, "BUY", r,
                    reason=reason, bucket=str(it.get("ai_bucket") or ""),
                )
                picked = sid
                break
        if not picked:
            break

    _snapshot(engine, db_path, user_id, as_of, quotes, lesson)
    persist_ai_lesson(db_path, user_id, as_of, lesson)
    return {
        "sold": sold,
        "bought": bought,
        "lesson": lesson,
        "candidates": len(_candidates(results, db_path)),
        "slot": slot_notional(initial, size_mult),
        "max_held": max_held,
        "html": format_ai_desk_html(engine, telegram_uid, quotes),
        "user_id": user_id,
    }


# 相容舊測試／腳本
AI_USER = AI_USER_LEGACY
