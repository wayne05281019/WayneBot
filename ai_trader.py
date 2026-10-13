"""WayneBot AI 模擬操盤：總 50 萬＝可動用 30 萬（勝率買點）＋留 20 萬（大跌加碼）。

每位 Telegram 使用者各有一套模擬帳戶（ai_{uid}），與手記持股完全分開。
進場母體＝當日勝率買點；最多 3 檔（含零股）。選股前可研究（不限庫內）；理由必落檔。
不會改黃金買點公式；進化只調倉位倍數。假錢對照，不能塞進富邦量化積木。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from portfolio_engine import PortfolioEngine

AI_USER_LEGACY = "wayne_ai"
# 資金鎖死：50 萬＝30 操作＋20 抄底（2026-10-12）
TOTAL_CAPITAL = 500_000.0
ACTIVE_BUDGET = 300_000.0  # 勝率買點隔日操作
DIP_RESERVE = 200_000.0  # 大跌／抄底加碼保留
MAX_ACTIVE_NAMES = 3  # 操作桶最多 3 檔（含零股）
MAX_SLOTS = MAX_ACTIVE_NAMES  # 相容舊測試／畫面槽位語意
CORE_SLOTS = MAX_ACTIVE_NAMES  # 操作桶可滿 3 檔
DIP_SLOTS = 1  # 大盤超跌才動抄底（動用保留額）
# 重跑：清空舊部位＋舊成交／fills；台北 2026-10-13 起買新的
# v20261013_wipe：使用者看到舊買賣殘留 → 再清一次（含 trade_logs／ai_fills）
RESTART_PARAM_KEY = "ai_desk_restart_v20261013_wipe"
RESTART_BUY_FROM = "20261013"
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
    try:
        from ai_research import ensure_ai_research_tables

        ensure_ai_research_tables(db_path)
    except Exception:
        pass
    conn.commit()
    conn.close()


def slot_notional(initial_capital: float, size_mult: float = 1.0) -> float:
    """操作桶單檔上限＝可動用 30 萬／最多 3 檔 × 倍數。空槽不把剩錢併進下一檔。"""
    _ = initial_capital  # 總本金 50 萬；單檔上限看 ACTIVE_BUDGET
    try:
        mult = float(size_mult or 1.0)
    except (TypeError, ValueError):
        mult = 1.0
    if ACTIVE_BUDGET <= 0:
        return 0.0
    return ACTIVE_BUDGET / float(MAX_ACTIVE_NAMES) * max(0.4, min(1.2, mult))


def cash_reserve_floor(initial_capital: float) -> float:
    """留 20 萬給大跌加碼；勝率買點操作不得吃進這筆。"""
    try:
        cap = float(initial_capital or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap <= 0:
        return 0.0
    # 本金若非 50 萬，按比例鎖 40%（＝20／50）；標準戶直接 20 萬
    if abs(cap - TOTAL_CAPITAL) < 1.0:
        return float(DIP_RESERVE)
    return cap * (DIP_RESERVE / TOTAL_CAPITAL)


def buy_budget(
    cash: float,
    initial_capital: float,
    size_mult: float = 1.0,
    *,
    dip: bool = False,
) -> float:
    """單檔可動用額。

    操作桶：min(每槽上限, 現金−20萬保留)。
    抄底桶（dip）：可動用保留額內剩餘現金，單檔仍不超過操作槽上限。
    """
    try:
        have = float(cash or 0)
    except (TypeError, ValueError):
        have = 0.0
    reserve = cash_reserve_floor(initial_capital)
    slot = slot_notional(initial_capital, size_mult)
    if dip:
        # 只動保留額：現金高於「總本金−保留」以外的部分
        deployable = max(0.0, have - max(0.0, float(initial_capital or 0) - reserve))
        # 若已用掉部分操作額，保留額＝目前現金中仍屬抄底的部分
        if have <= reserve:
            deployable = have
        else:
            deployable = min(have, reserve)
        return min(slot, max(0.0, deployable))
    deployable = max(0.0, have - reserve)
    return min(slot, deployable)


def market_is_dip(
    db_path: str,
    as_of: str,
    results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> bool:
    """大盤偏空且當日勝率買點母體非空 → 才准動 20 萬抄底。"""
    has_names = False
    if results:
        has_names = bool(
            (results or {}).get("leave_zero")
            or (results or {}).get("ma60_lower")
            or (results or {}).get("winrate")
        )
    if not has_names:
        try:
            from winrate_buypoint import load_winrate_roster, latest_roster_as_of

            day = str(as_of or "").replace("-", "")[:8] or latest_roster_as_of(db_path)
            rows = load_winrate_roster(db_path, day) if day else []
            has_names = any(
                str(r.get("stock_id") or "").strip()
                and not str(r.get("stock_id") or "").startswith("__")
                for r in rows
            )
        except Exception:
            has_names = False
    if not has_names:
        return False
    snap: Dict[str, Any] = {}
    try:
        from taiwan_market import analyze_taiwan_market

        snap = analyze_taiwan_market(db_path, as_of, db_only=True, page_light=True) or {}
    except Exception:
        snap = {}
    if not snap.get("ok"):
        return False
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
    return regime == "bear" or fr >= 35 or (vs20_n is not None and vs20_n < -1)


def market_deploy_cap(
    db_path: str,
    as_of: str,
    results: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> int:
    """操作桶最多 3 檔。抄底是加碼／另動保留額，不另開無限槽。"""
    _ = (db_path, as_of, results)
    return int(MAX_ACTIVE_NAMES)


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
        "ma60_lower",
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


def _winrate_roster_rows(db_path: str, as_of: str = "") -> List[Dict[str, Any]]:
    """勝率買點母體：先試 as_of，空則退最新已落檔日（隔日操作吃前一日名單）。"""
    try:
        from winrate_buypoint import latest_roster_as_of, load_winrate_roster

        day = str(as_of or "").replace("-", "")[:8]
        rows: List[Dict[str, Any]] = []
        if day:
            rows = load_winrate_roster(db_path, day) or []
        if not rows:
            latest = latest_roster_as_of(db_path)
            if latest and latest != day:
                rows = load_winrate_roster(db_path, latest) or []
    except Exception:
        return []
    out = []
    for it in rows:
        sid = str(it.get("stock_id") or "").strip()
        if not sid or sid.startswith("__"):
            continue
        out.append(dict(it))
    return out


def _candidates(
    results: Dict[str, List[Dict[str, Any]]],
    db_path: str = "",
    *,
    dip_only: bool = False,
    as_of: str = "",
) -> List[Dict[str, Any]]:
    """隔夜模擬倉：硬閘＝只認盤後勝率買點 roster。

    沒出現在勝率買點 → 不准買（含 leave_zero 海選後備、紅箭、還在零、雜桶）。
    有出現 → 可認真研究（庫內＋連線公開站）再挑；操作／抄底同一母體。
    不准改黃金買點公式。
    """
    _ = results  # 海選 results 不准當買進母體；只吃 winrate_buypoint_roster
    out, seen = [], set()
    bucket = "dip_add" if dip_only else "winrate_active"
    reason = (
        "大跌加碼：當日勝率買點"
        if dip_only
        else "勝率買點隔日操作"
    )
    if not db_path:
        return []
    roster = _winrate_roster_rows(db_path, as_of)
    for it in roster:
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid or sid in seen or sid.startswith("__"):
            continue
        try:
            from universe import is_screen_equity

            if not is_screen_equity(sid, str(it.get("stock_name") or it.get("name") or "")):
                continue
        except Exception:
            pass
        if it.get("chase_warning") or it.get("us_peer_headwind") or it.get("us_risk_off"):
            continue
        close = it.get("close")
        if close is None:
            close = it.get("pick_close")
        try:
            px = float(close or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            continue
        seen.add(sid)
        row = dict(it)
        row["close"] = px
        row["ai_reason"] = reason
        row["ai_bucket"] = bucket
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


def _param_get(db_path: str, key: str) -> Optional[float]:
    ensure_ai_tables(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT v FROM ai_params WHERE k=?", (key,)).fetchone()
    conn.close()
    return float(row[0]) if row else None


def _param_set(db_path: str, key: str, value: float) -> None:
    ensure_ai_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO ai_params (k, v) VALUES (?, ?);",
        (key, float(value)),
    )
    conn.commit()
    conn.close()


def reset_ai_account(engine: PortfolioEngine, user_id: str, *, note: str = "") -> Dict[str, Any]:
    """清空該 AI 戶：持倉＋成交日誌＋ai_fills＋淨值／理由／研究；現金重設 50 萬。

    不寫 RESET 進成交（避免話筒還看到舊／假成交）。只動 ai_* 假錢倉。
    """
    uid = str(user_id or "").strip()
    if not uid:
        return {"success": False, "msg": "無 user_id"}
    # 硬閘：只准清 AI 模擬戶（ai_*／舊 wayne_ai），不准動真實持股 uid
    if not (uid.startswith("ai_") or uid == AI_USER_LEGACY):
        return {"success": False, "msg": "只清 AI 假錢倉"}
    engine.ensure_user_exists(uid)
    conn = engine._get_connection()
    try:
        from config import taipei_now

        now_str = taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        from datetime import datetime

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_pos = n_logs = n_fills = 0
    try:
        n_pos = conn.execute(
            "SELECT COUNT(*) FROM user_positions WHERE user_id=?", (uid,)
        ).fetchone()[0]
        n_logs = conn.execute(
            "SELECT COUNT(*) FROM trade_logs WHERE user_id=?", (uid,)
        ).fetchone()[0]
        conn.execute("DELETE FROM user_positions WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM trade_logs WHERE user_id=?", (uid,))
        conn.execute(
            """
            UPDATE user_funds
            SET cash=?, initial_capital=?, updated_at=?
            WHERE user_id=?
            """,
            (TOTAL_CAPITAL, TOTAL_CAPITAL, now_str, uid),
        )
        # 附帶清 AI 專用表（缺表略過）
        for sql in (
            "DELETE FROM ai_nav_log WHERE user_id=?",
            "DELETE FROM ai_lessons WHERE user_id=?",
            "DELETE FROM ai_fills WHERE user_id=?",
            "DELETE FROM ai_buy_research WHERE user_id=?",
            "DELETE FROM ai_buy_reasons WHERE user_id=?",
        ):
            try:
                cur = conn.execute(sql, (uid,))
                if "ai_fills" in sql:
                    n_fills = int(cur.rowcount or 0)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()
    # 重跑備註只進 ai_params，不上成交頁
    try:
        ensure_ai_tables(engine.db_path)
        _param_set(engine.db_path, f"ai_wipe_note:{uid}", 1.0)
    except Exception:
        pass
    _ = note  # 呼叫端可傳說明；不寫進 trade_logs
    return {
        "success": True,
        "user_id": uid,
        "cleared_positions": int(n_pos or 0),
        "cleared_trade_logs": int(n_logs or 0),
        "cleared_fills": int(n_fills or 0),
        "cash": TOTAL_CAPITAL,
        "buy_from": RESTART_BUY_FROM,
    }


def mark_ai_restart_done(db_path: str, user_id: str) -> None:
    """標記重跑已做完（測試／遷移用）；不影響其他功能。"""
    uid = str(user_id or "").strip()
    if not uid:
        return
    _param_set(db_path, f"{RESTART_PARAM_KEY}:{uid}", 1.0)


def ensure_ai_restart_applied(engine: PortfolioEngine, user_id: str) -> bool:
    """每位 AI 戶只完整清空一次（v20261013_wipe：部位＋舊買賣紀錄）。

    只動該人 ai_{uid} 假錢倉；不碰真實持股／觀察／海選／勝率買點推播。
    """
    ensure_ai_tables(engine.db_path)
    key = f"{RESTART_PARAM_KEY}:{user_id}"
    if _param_get(engine.db_path, key) is not None:
        return False
    reset_ai_account(
        engine,
        user_id,
        note="2026-10-13 全清舊買賣；總50萬＝30操作＋20抄底；今日起買新的",
    )
    _param_set(engine.db_path, key, 1.0)
    return True


def buys_allowed_on(as_of: str) -> bool:
    """重跑後買進閘：台北日 >= 20261013。"""
    day = str(as_of or "").replace("-", "")[:8]
    if not day or not day.isdigit():
        return False
    return day >= RESTART_BUY_FROM


def ensure_ai_user(engine: PortfolioEngine, telegram_uid: str) -> str:
    """確保此 Telegram 使用者有獨立 AI 模擬帳戶。不再複製舊 wayne_ai 倉。"""
    user_id = ai_user_id(telegram_uid)
    engine.ensure_user_exists(user_id)
    try:
        ensure_ai_restart_applied(engine, user_id)
    except Exception:
        pass
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
        return "樣本不足，維持原倉位比例（操作最多 3 檔／留 20 萬抄底）"
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
        "entry": "winrate_buypoint",
        "observe": "golden_buy",
        "not_entry": "red_arrow_unconfirmed",
        "stop_pct": STOP_PCT,
        "take_pct": TAKE_PCT,
        "total_capital": TOTAL_CAPITAL,
        "active_budget": ACTIVE_BUDGET,
        "dip_reserve": DIP_RESERVE,
        "core_slots": CORE_SLOTS,
        "max_active_names": MAX_ACTIVE_NAMES,
        "dip_slots": DIP_SLOTS,
        "cash_slots": 0,
        "cash_reserve": True,
        "dip_open": "winrate_buypoint",
        "restart_buy_from": RESTART_BUY_FROM,
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
        "表面仍是模擬買進／賣出。背後只調倉位倍數。不准改黃金買點公式。",
        "進場母體＝當日勝率買點。還在零只觀察。未確認紅箭頭不是買訊。假錢對照，不能塞進富邦量化積木。",
        "",
        "<b>目前編碼</b>",
        "總本金 50 萬＝可動用 30 萬（勝率買點隔日、最多 3 檔含零股）＋留 20 萬（大跌加碼，也只從當日勝率買點挑）",
        "選隔日前可研究（庫內＋公開）；查不到寫未取得。有買進理由必落檔（台北時間）。",
        f"停損 {STOP_PCT:.0f}%　停利 ＋{TAKE_PCT:.0f}%　操作最多 {MAX_ACTIVE_NAMES} 檔；買進不得吃 20 萬保留額（抄底除外）",
        f"單筆倍數 {size_mult:.2f}（0.40～1.20，依近況勝率縮放）",
        f"重跑買進閘 {RESTART_BUY_FROM} 起。三個月後算這輪賺賠。",
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
    """最近真買賣；略過 RESET／0 股殘列，避免話筒還看到清空備註。"""
    conn = engine._get_connection()
    rows = conn.execute(
        """
        SELECT date, action, stock_id, stock_name, shares, price, realized_pnl, pnl_pct, reason
        FROM trade_logs
        WHERE user_id=?
          AND UPPER(COALESCE(action,'')) IN ('BUY','SELL')
          AND COALESCE(shares,0) > 0
          AND COALESCE(stock_id,'') NOT IN ('','RESET')
        ORDER BY id DESC LIMIT ?
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
    initial = float(s.get("initial_capital") or TOTAL_CAPITAL)
    slot = slot_notional(initial, size_mult)
    used = int(s["positions_count"])
    reasons = _last_buy_reasons(engine, user_id)
    realized = _realized_pnl(engine, user_id)
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in s["positions"])

    empty = max(0, MAX_ACTIVE_NAMES - used)
    dots = ("●" * min(used, MAX_ACTIVE_NAMES)) + ("○" * empty)
    reserve = cash_reserve_floor(initial)
    head = [
        section_eq("AI 模擬帳戶"),
        "假錢對照組，不是真下單。",
        "總 50 萬＝可動用 30 萬＋留 20 萬抄底。",
        "勝率買點隔日最多 3 檔（含零股）。",
        "停損 −7%、停利 ＋8%。理由必落檔。",
        "",
        "────────────────",
        "<b>帳戶</b>",
        kv_html_compact("總資產", html_money(s["total_assets"], signed=False, compact=True)),
        kv_html_compact("現金", html_money(s["cash"], signed=False, compact=True)),
        kv_html_compact("保留現金", html_money(reserve, signed=False, compact=True)),
        kv_html_compact("市值", html_money(s["stock_market_value"], signed=False, compact=True)),
        kv_html_compact("未實現", html_money(unreal, compact=True)),
        kv_html_compact("已實現", html_money(realized, compact=True)),
        kv_html_compact("總損益", html_num_paren(_plain_num(s["total_pnl"], signed=True), s["total_pnl_pct"], compact=True)),
        "",
        "────────────────",
        "<b>槽位</b>",
        kv_compact("已用槽", f"{dots}　{used}/{MAX_ACTIVE_NAMES}"),
        kv_compact("每槽上限", f"{slot:,.0f}　倍數 {size_mult:.2f}"),
        kv_compact("本金", f"{initial:,.0f}"),
        "可動用 30 萬操作；留 20 萬大跌加碼。",
        "操作買進不得吃保留額。",
    ]
    pages: List[str] = []
    if not s["positions"]:
        head.extend(["", "────────────────", "<b>持倉</b>"])
        head.append("尚無持倉。操作最多 3 檔。")
        head.append(f"每槽約 {slot:,.0f}。留 20 萬給抄底。")
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
        flows: Dict[str, str] = {}
        try:
            from money_flow import industry_flows_for_stocks

            flows = industry_flows_for_stocks(
                engine.db_path, [p.get("stock_id") for p in s["positions"]]
            )
        except Exception:
            flows = {}
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
            flow = str(flows.get(sid) or "").strip()
            if flow:
                block.extend(_ai_phone_lines(kv_compact("資金", flow.rstrip("。"))))
            note = sell_notes.get(sid) or ""
            if note:
                block.extend(_ai_phone_lines(f"紀律：{note}"))
            month = str((readings.get(sid) or {}).get("monthly_stage_short") or "").strip()
            if month:
                block.extend(_ai_phone_lines(f"月K　{month}"))
            pos_pages.append("\n".join(x for x in block if x))
        held_txt = "\n\n".join(pos_pages)
        if empty > 0:
            held_txt += f"\n空槽 {empty}/{MAX_ACTIVE_NAMES}　每槽仍 {slot:,.0f}"
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
        # 只放 AI 成交復盤；海選復盤不准混進 AI倉（勝率分開）。
        from screen_review import format_ai_review_html

        txt = str(format_ai_review_html(engine.db_path, user_id=user_id) or "").strip()
        if txt and not ("還沒有" in txt and len(txt) < 220):
            pages.append(txt)
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


def _research_and_log_buy(
    db_path: str,
    user_id: str,
    as_of: str,
    sid: str,
    name: str,
    *,
    bucket: str,
    signal_label: str,
) -> Dict[str, Any]:
    """選前研究＋買進理由落檔。缺資料寫未取得。"""
    from ai_research import (
        build_buy_reason_from_research,
        gather_buy_research,
        persist_buy_reason,
    )

    research = gather_buy_research(db_path, user_id, as_of, sid, name, allow_public=True)
    built = build_buy_reason_from_research(
        research, signal_label=signal_label, bucket=bucket
    )
    rid = persist_buy_reason(
        db_path,
        user_id=user_id,
        as_of=as_of,
        stock_id=sid,
        stock_name=name,
        bucket=bucket,
        reason=built["reason"],
        sources_summary=built["sources_summary"],
        target_exit=built["target_exit"],
        stop_pct=STOP_PCT,
        take_pct=TAKE_PCT,
        research_id=int(research.get("research_id") or 0) or None,
    )
    return {
        "reason": built["reason"],
        "sources_summary": built["sources_summary"],
        "target_exit": built["target_exit"],
        "research_id": research.get("research_id"),
        "reason_id": rid,
    }


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
    # 勝率買點報價併入
    for it in _winrate_roster_rows(db_path, as_of):
        sid = str(it.get("stock_id") or "")
        if not sid:
            continue
        try:
            px = float(it.get("pick_close") or it.get("close") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px > 0 and sid not in result_quotes:
            result_quotes[sid] = {
                "close": px,
                "stock_name": it.get("stock_name") or "",
                "is_k20_warning": False,
                "d20": 0.0,
                "pct_change": 0,
            }
    quotes = engine.load_quotes_for(
        [p["stock_id"] for p in seed["positions"]],
        result_quotes,
    )

    sold = []
    # 舊模擬倉若抱著 ETF，先用官方收盤清掉。
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
    researched = []
    initial = float(summary.get("initial_capital") or TOTAL_CAPITAL)
    allow_buy = buys_allowed_on(as_of)

    # 選前：對母體做研究落檔（即使今日還不能買，也先研）
    cands_preview = _candidates(results, db_path, as_of=as_of)
    try:
        from ai_research import research_batch

        researched = research_batch(
            db_path, user_id, as_of, cands_preview, allow_public=True, limit=20
        )
    except Exception:
        researched = []

    while allow_buy and slots > 0:
        cands = _candidates(results, db_path, dip_only=False, as_of=as_of)
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
            budget = buy_budget(cash, initial, size_mult, dip=False)
            shares = _shares_for_budget(price, budget)
            if shares <= 0:
                continue
            logged = _research_and_log_buy(
                db_path,
                user_id,
                as_of,
                sid,
                name,
                bucket="winrate_active",
                signal_label="勝率買點隔日操作",
            )
            reason = logged.get("reason") or it.get("ai_reason") or "勝率買點"
            r = engine.buy(
                user_id, as_of, sid, name, price, shares,
                reason=reason,
                strategy_type="WINRATE",
            )
            if r.get("success"):
                bought.append(r["msg"])
                held.add(sid)
                slots -= 1
                _record_fill(
                    db_path, user_id, as_of, "BUY", r,
                    reason=reason, bucket="winrate_active",
                )
                picked = sid
                break
        if not picked:
            break

    # 大跌才動 20 萬保留額加碼（同一勝率買點母體；可加碼已持有）
    if allow_buy and market_is_dip(db_path, as_of, results):
        dip_cands = _candidates(results, db_path, dip_only=True, as_of=as_of)
        for it in dip_cands:
            sid = str(it.get("stock_id") or it.get("code") or "")
            price = float(it.get("close") or 0)
            name = it.get("stock_name") or it.get("name") or sid
            if not sid or price <= 0:
                continue
            cash = engine.get_cash(user_id)
            budget = buy_budget(cash, initial, size_mult, dip=True)
            shares = _shares_for_budget(price, budget)
            if shares <= 0:
                continue
            # 新開檔仍受操作最多 3 檔限制；已持有可加碼
            if sid not in held and len(held) >= MAX_ACTIVE_NAMES:
                continue
            logged = _research_and_log_buy(
                db_path,
                user_id,
                as_of,
                sid,
                name,
                bucket="dip_add",
                signal_label="大跌加碼：當日勝率買點",
            )
            reason = logged.get("reason") or "大跌加碼：當日勝率買點"
            r = engine.buy(
                user_id, as_of, sid, name, price, shares,
                reason=reason,
                strategy_type="DIP_ADD",
            )
            if r.get("success"):
                bought.append(r["msg"])
                held.add(sid)
                _record_fill(
                    db_path, user_id, as_of, "BUY", r,
                    reason=reason, bucket="dip_add",
                )
                break  # 一輪抄底先加一檔，避免一次打光

    _snapshot(engine, db_path, user_id, as_of, quotes, lesson)
    persist_ai_lesson(db_path, user_id, as_of, lesson)
    return {
        "sold": sold,
        "bought": bought,
        "lesson": lesson,
        "candidates": len(_candidates(results, db_path, as_of=as_of)),
        "researched": len(researched),
        "slot": slot_notional(initial, size_mult),
        "max_held": max_held,
        "active_budget": ACTIVE_BUDGET,
        "dip_reserve": DIP_RESERVE,
        "buys_allowed": allow_buy,
        "html": format_ai_desk_html(engine, telegram_uid, quotes),
        "user_id": user_id,
    }


# 相容舊測試／腳本
AI_USER = AI_USER_LEGACY
