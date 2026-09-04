"""海選隔日復盤：用庫裡已經有的日 K，對昨天寄出的名單算隔日報酬。

AI 模擬成交另存 ai_fills，盤後用下一根日 K 對帳。
不另抓行情、不改程式檔。進化只寫 ai_params（哪一類最近比較準、單筆多大）。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

BUCKETS = (
    ("leave_zero", "起漲"),
    ("golden_buy", "黃金買點"),
    ("revenue_cross", "優先看"),
    ("select_01", "周突破"),
    ("select_02", "站上季線"),
    ("select_03", "止跌"),
    ("day_trade", "當沖"),
    ("overnight", "隔日沖"),
)
BUCKET_CAP = 8
WEAK_AVG = -1.0
WEAK_N = 5
FILL_WEAK_N = 3


def ensure_screen_review_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_picks (
            as_of TEXT NOT NULL,
            bucket TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            pick_close REAL NOT NULL,
            next_date TEXT,
            next_close REAL,
            next_pct REAL,
            PRIMARY KEY (as_of, bucket, stock_id)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_screen_picks_next ON screen_picks(next_date);")
    conn.commit()
    conn.close()


def save_screen_picks(db_path: str, as_of: str, results: Dict[str, Any]) -> int:
    """只存當天實際寄出／展示的前幾檔，列數很小。

    同一基準日重跑會整日覆蓋，避免舊 ETF／已淘汰檔留在復盤表。
    """
    as_of = str(as_of or "").replace("-", "")
    if not as_of or not results:
        return 0
    ensure_screen_review_table(db_path)
    try:
        from universe import is_screen_equity
    except Exception:
        def is_screen_equity(stock_id, stock_name="", asset_type=None):
            return True

    n = 0
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM screen_picks WHERE as_of=?", (as_of,))
    for key, _label in BUCKETS:
        items = results.get(key) or []
        if not isinstance(items, list):
            continue
        kept = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if not sid:
                continue
            if not is_screen_equity(sid, str(it.get("stock_name") or it.get("name") or "")):
                continue
            try:
                close = float(it.get("close") or 0)
            except (TypeError, ValueError):
                close = 0.0
            if close <= 0:
                continue
            kept.append((sid, str(it.get("stock_name") or it.get("name") or ""), close))
        for sid, name, close in kept[:BUCKET_CAP]:
            conn.execute(
                """
                INSERT OR REPLACE INTO screen_picks(
                    as_of, bucket, stock_id, stock_name, pick_close, next_date, next_close, next_pct
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (as_of, key, sid, name, close, None, None, None),
            )
            n += 1
    conn.commit()
    conn.close()
    return n


def _next_quote_date(conn: sqlite3.Connection, as_of: str) -> str:
    row = conn.execute(
        "SELECT MIN(replace(date,'-','')) FROM daily_quotes WHERE replace(date,'-','') > ?",
        (as_of,),
    ).fetchone()
    return str(row[0] or "").replace("-", "") if row else ""


def score_screen_picks(db_path: str, next_date: str = None) -> int:
    """用已經寫進庫的下一根日 K 填隔日％。next_date 有給就只對那一天。"""
    ensure_screen_review_table(db_path)
    conn = sqlite3.connect(db_path)
    pending = conn.execute(
        "SELECT DISTINCT as_of FROM screen_picks WHERE next_pct IS NULL"
    ).fetchall()
    filled = 0
    cap = str(next_date or "").replace("-", "")
    for (as_of,) in pending:
        nxt = _next_quote_date(conn, as_of)
        if not nxt:
            continue
        if cap and nxt != cap:
            continue
        rows = conn.execute(
            "SELECT as_of, bucket, stock_id, pick_close FROM screen_picks WHERE as_of=? AND next_pct IS NULL",
            (as_of,),
        ).fetchall()
        for pick_asof, bucket, sid, pick_close in rows:
            q = conn.execute(
                "SELECT close FROM daily_quotes WHERE stock_id=? AND replace(date,'-','')=? LIMIT 1",
                (sid, nxt),
            ).fetchone()
            if not q or not pick_close:
                continue
            try:
                nxt_c = float(q[0] or 0)
                pct = (nxt_c - float(pick_close)) / float(pick_close) * 100.0 if pick_close else 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            conn.execute(
                """
                UPDATE screen_picks
                SET next_date=?, next_close=?, next_pct=?
                WHERE as_of=? AND bucket=? AND stock_id=?
                """,
                (nxt, nxt_c, pct, pick_asof, bucket, sid),
            )
            filled += 1
    conn.commit()
    conn.close()
    if filled:
        adapt_bucket_weights(db_path)
    return filled


def _pick_is_equity(stock_id: str, stock_name: str = "") -> bool:
    try:
        from universe import is_screen_equity

        return is_screen_equity(stock_id, stock_name)
    except Exception:
        return True


def _bucket_stats(db_path: str, limit_days: int = 10) -> List[Tuple[str, int, float, float]]:
    ensure_screen_review_table(db_path)
    conn = sqlite3.connect(db_path)
    days = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT as_of FROM screen_picks WHERE next_pct IS NOT NULL ORDER BY as_of DESC LIMIT ?",
            (limit_days,),
        ).fetchall()
    ]
    out = []
    for key, _label in BUCKETS:
        if not days:
            out.append((key, 0, 0.0, 0.0))
            continue
        qmarks = ",".join("?" * len(days))
        rows = conn.execute(
            f"""
            SELECT stock_id, stock_name, next_pct FROM screen_picks
            WHERE bucket=? AND next_pct IS NOT NULL AND as_of IN ({qmarks})
            """,
            (key, *days),
        ).fetchall()
        rows = [r for r in rows if _pick_is_equity(str(r[0] or ""), str(r[1] or ""))]
        n = len(rows)
        if not n:
            out.append((key, 0, 0.0, 0.0))
            continue
        avg = sum(float(r[2]) for r in rows) / n
        hits = sum(1 for r in rows if float(r[2]) > 0)
        out.append((key, n, avg, hits / n))
    conn.close()
    return out


def adapt_bucket_weights(
    db_path: str, regime: Optional[str] = None, regime_plus: Optional[str] = None
) -> Dict[str, float]:
    """近幾日某類隔日平均 < -1% 且樣本夠 → 權重降到 0；再乘上 Regime+（優先）或大盤 regime 倍率。

    有足夠 AI 實際成交時，以成交隔日為準；否則退回海選名單統計。
    """
    if regime is None:
        try:
            from taiwan_market import latest_regime

            regime = latest_regime(db_path)
        except Exception:
            regime = None
    try:
        from taiwan_market import REGIME_BUCKET_MULT, regime_plus_bucket_mult
    except Exception:
        REGIME_BUCKET_MULT = {}
        regime_plus_bucket_mult = None  # type: ignore
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL);")
    screen = {key: (n, avg, hit) for key, n, avg, hit in _bucket_stats(db_path)}
    try:
        fills = {key: (n, avg, hit) for key, n, avg, hit in _ai_fill_stats(db_path)}
    except sqlite3.OperationalError:
        fills = {}
    weights = {}
    plus_mults = regime_plus_bucket_mult(regime_plus) if regime_plus and regime_plus_bucket_mult else None
    for key, _label in BUCKETS:
        sn, savg, _shit = screen.get(key, (0, 0.0, 0.0))
        fn, favg, _fhit = fills.get(key, (0, 0.0, 0.0))
        if fn >= FILL_WEAK_N:
            n, avg, need = fn, favg, FILL_WEAK_N
        else:
            n, avg, need = sn, savg, WEAK_N
        if n >= need and avg <= WEAK_AVG:
            base_w = 0.0
        elif n >= need and avg >= 1.0:
            base_w = 1.1
        else:
            base_w = 1.0
        conn.execute(
            "INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)",
            (f"bucket_w_base_{key}", base_w),
        )
        if plus_mults is not None:
            mult = float(plus_mults.get(key, 1.0))
        else:
            mult = float((REGIME_BUCKET_MULT.get(regime or "neutral") or {}).get(key, 1.0))
        eff = max(0.0, min(1.2, base_w * mult))
        conn.execute(
            "INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)",
            (f"bucket_w_{key}", eff),
        )
        weights[key] = eff
    if regime_plus:
        plus_code = {
            "trend_up": 1.0,
            "trend_up_late": 2.0,
            "range": 3.0,
            "trend_down": 4.0,
            "down_exhaust": 5.0,
            "repair": 6.0,
        }.get(str(regime_plus), 0.0)
        conn.execute(
            "INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)",
            ("mkt_regime_plus_code", plus_code),
        )
    if regime:
        code = {"bull": 1.0, "neutral": 0.0, "bear": -1.0}.get(regime, 0.0)
        conn.execute(
            "INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)",
            ("mkt_regime_code", code),
        )
    conn.commit()
    conn.close()
    return weights


def bucket_weight(db_path: str, key: str) -> float:
    """有效桶權重（已含大盤 regime × 復盤 base）。"""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT v FROM ai_params WHERE k=?", (f"bucket_w_{key}",)).fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    if row is None:
        return 1.0
    return float(row[0])


def format_review_html(db_path: str) -> str:
    from tg_layout import html_escape

    stats = _bucket_stats(db_path)
    conn = sqlite3.connect(db_path)
    latest = conn.execute(
        "SELECT MAX(as_of) FROM screen_picks WHERE next_pct IS NOT NULL"
    ).fetchone()
    as_of = str(latest[0] or "") if latest else ""
    sample = []
    if as_of:
        sample = conn.execute(
            """
            SELECT bucket, stock_id, stock_name, next_pct
            FROM screen_picks
            WHERE as_of=? AND next_pct IS NOT NULL
            ORDER BY next_pct DESC
            LIMIT 24
            """,
            (as_of,),
        ).fetchall()
        sample = [
            r for r in sample if _pick_is_equity(str(r[1] or ""), str(r[2] or ""))
        ][:6]
    conn.close()
    if not as_of:
        return (
            "<b>海選復盤</b>\n"
            "還沒有「寄出名單的隔一日收盤」。盤後日 K 齊了會自動對帳，不另抓資料。"
        )
    labels = dict(BUCKETS)
    as_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:]}" if len(as_of) == 8 else as_of
    lines = [
        f"<b>海選復盤</b>　名單日 {html_escape(as_s)} 的隔日收盤",
        "用庫內日 K，不是盤中、也不改程式。弱的類別只讓 AI 模擬倉少買。",
    ]
    bits = []
    for key, n, avg, hit in stats:
        if n <= 0:
            continue
        bits.append(f"{labels.get(key, key)} {avg:+.1f}%（勝 {hit:.0%}／{n}）")
    if bits:
        lines.append("　".join(bits[:4]))
        if len(bits) > 4:
            lines.append("　".join(bits[4:]))
    if sample:
        lines.append("<b>那日較強幾檔</b>")
        try:
            from stock_links import html_stock_anchor
        except Exception:
            html_stock_anchor = None
        for i, (bucket, sid, name, pct) in enumerate(sample, start=1):
            title = (
                html_stock_anchor(sid, name, db_path)
                if html_stock_anchor
                else f"{html_escape(sid)} {html_escape(name)}"
            )
            lines.append(
                f"{i}. {title}　{float(pct):+.1f}%　{html_escape(labels.get(bucket, bucket))}"
            )
    return "\n".join(lines)


def ensure_ai_fills_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT DEFAULT '',
            action TEXT NOT NULL,
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            reason TEXT DEFAULT '',
            bucket TEXT DEFAULT '',
            realized_pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            next_date TEXT,
            next_close REAL,
            next_pct REAL,
            created_at TEXT
        );
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_fills)")}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE ai_fills ADD COLUMN user_id TEXT DEFAULT 'wayne_ai'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_fills_next ON ai_fills(action, next_pct);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_fills_user ON ai_fills(user_id, action, next_pct);")
    conn.commit()
    conn.close()


def bucket_from_reason(reason: str) -> str:
    r = str(reason or "")
    mapping = (
        ("起漲", "leave_zero"),
        ("黃金", "golden_buy"),
        ("營收", "revenue_cross"),
        ("隔日", "overnight"),
        ("周", "select_01"),
        ("當沖", "day_trade"),
        ("站上季線", "select_02"),
        ("止跌", "select_03"),
    )
    for needle, key in mapping:
        if needle in r:
            return key
    return ""


def persist_ai_fill(
    db_path: str,
    *,
    as_of: str,
    stock_id: str,
    action: str,
    price: float,
    shares: int,
    stock_name: str = "",
    amount: float = 0.0,
    reason: str = "",
    bucket: str = "",
    realized_pnl: float = 0.0,
    pnl_pct: float = 0.0,
    user_id: str = "wayne_ai",
) -> None:
    """每一筆 AI 模擬成交都留下，隔日用庫內日 K 對帳，用來調勝率。"""
    as_of = str(as_of or "").replace("-", "")
    sid = str(stock_id or "").strip()
    if not as_of or not sid or float(price or 0) <= 0 or int(shares or 0) <= 0:
        return
    ensure_ai_fills_table(db_path)
    bucket = str(bucket or bucket_from_reason(reason) or "").strip()
    if action == "SELL" and not bucket:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            """
            SELECT bucket FROM ai_fills
            WHERE user_id=? AND stock_id=? AND action='BUY' AND bucket!=''
            ORDER BY id DESC LIMIT 1
            """,
            (str(user_id or "wayne_ai"), sid),
        ).fetchone()
        conn.close()
        if row:
            bucket = str(row[0] or "")
    from datetime import datetime

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO ai_fills(
            user_id, as_of, stock_id, stock_name, action, price, shares, amount,
            reason, bucket, realized_pnl, pnl_pct, next_date, next_close, next_pct, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(user_id or "wayne_ai"),
            as_of,
            sid,
            str(stock_name or ""),
            str(action or "").upper(),
            float(price),
            int(shares),
            float(amount or 0),
            str(reason or ""),
            bucket,
            float(realized_pnl or 0),
            float(pnl_pct or 0),
            None,
            None,
            None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()


def score_ai_fills(db_path: str, next_date: str = None) -> int:
    """買進成交用下一根日 K 填隔日％。賣出已有已實現，不另算。"""
    ensure_ai_fills_table(db_path)
    conn = sqlite3.connect(db_path)
    pending = conn.execute(
        "SELECT DISTINCT as_of FROM ai_fills WHERE action='BUY' AND next_pct IS NULL"
    ).fetchall()
    filled = 0
    cap = str(next_date or "").replace("-", "")
    for (as_of,) in pending:
        nxt = _next_quote_date(conn, as_of)
        if not nxt:
            continue
        if cap and nxt != cap:
            continue
        rows = conn.execute(
            "SELECT id, stock_id, price FROM ai_fills WHERE as_of=? AND action='BUY' AND next_pct IS NULL",
            (as_of,),
        ).fetchall()
        for fill_id, sid, fill_px in rows:
            q = conn.execute(
                "SELECT close FROM daily_quotes WHERE stock_id=? AND replace(date,'-','')=? LIMIT 1",
                (sid, nxt),
            ).fetchone()
            if not q or not fill_px:
                continue
            try:
                nxt_c = float(q[0] or 0)
                pct = (nxt_c - float(fill_px)) / float(fill_px) * 100.0 if fill_px else 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            conn.execute(
                "UPDATE ai_fills SET next_date=?, next_close=?, next_pct=? WHERE id=?",
                (nxt, nxt_c, pct, fill_id),
            )
            filled += 1
    conn.commit()
    conn.close()
    if filled:
        adapt_bucket_weights(db_path)
    return filled


def _ai_fill_stats(db_path: str, limit_days: int = 20, user_id: Optional[str] = None) -> List[Tuple[str, int, float, float]]:
    ensure_ai_fills_table(db_path)
    conn = sqlite3.connect(db_path)
    if user_id:
        days = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT as_of FROM ai_fills
                WHERE user_id=? AND action='BUY' AND next_pct IS NOT NULL
                ORDER BY as_of DESC LIMIT ?
                """,
                (str(user_id), limit_days),
            ).fetchall()
        ]
    else:
        days = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT as_of FROM ai_fills
                WHERE action='BUY' AND next_pct IS NOT NULL
                ORDER BY as_of DESC LIMIT ?
                """,
                (limit_days,),
            ).fetchall()
        ]
    out = []
    for key, _label in BUCKETS:
        if not days:
            out.append((key, 0, 0.0, 0.0))
            continue
        qmarks = ",".join("?" * len(days))
        if user_id:
            rows = conn.execute(
                f"""
                SELECT next_pct FROM ai_fills
                WHERE user_id=? AND bucket=? AND action='BUY' AND next_pct IS NOT NULL AND as_of IN ({qmarks})
                """,
                (str(user_id), key, *days),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT next_pct FROM ai_fills
                WHERE bucket=? AND action='BUY' AND next_pct IS NOT NULL AND as_of IN ({qmarks})
                """,
                (key, *days),
            ).fetchall()
        n = len(rows)
        if not n:
            out.append((key, 0, 0.0, 0.0))
            continue
        avg = sum(float(r[0]) for r in rows) / n
        hits = sum(1 for r in rows if float(r[0]) > 0)
        out.append((key, n, avg, hits / n))
    conn.close()
    return out


def format_ai_review_html(db_path: str, user_id: str = "wayne_ai") -> str:
    from tg_layout import html_escape, html_pct

    uid = str(user_id or "wayne_ai")
    ensure_ai_fills_table(db_path)
    conn = sqlite3.connect(db_path)
    agg = conn.execute(
        """
        SELECT COUNT(*), AVG(next_pct),
               SUM(CASE WHEN next_pct > 0 THEN 1 ELSE 0 END)
        FROM ai_fills WHERE user_id=? AND action='BUY' AND next_pct IS NOT NULL
        """,
        (uid,),
    ).fetchone()
    sample = conn.execute(
        """
        SELECT stock_id, stock_name, next_pct, bucket, as_of
        FROM ai_fills
        WHERE user_id=? AND action='BUY' AND next_pct IS NOT NULL
        ORDER BY id DESC LIMIT 6
        """,
        (uid,),
    ).fetchall()
    conn.close()
    n = int(agg[0] or 0) if agg else 0
    if n <= 0:
        return (
            "<b>AI 成交復盤</b>\n"
            "還沒有「模擬買進的隔一日收盤」。盤後日 K 齊了會自動對帳，用來調哪類少買、單筆多大。"
        )
    avg = float(agg[1] or 0)
    hits = int(agg[2] or 0)
    wr = hits / n if n else 0.0
    labels = dict(BUCKETS)
    lines = [
        "<b>AI 成交復盤</b>",
        f"模擬買進隔日　勝 {wr:.0%}／{n}　均 {html_pct(avg).strip()}",
        "用實際成交，不是只看海選名單。弱的類別下一輪少買；不會改程式檔。",
    ]
    bits = []
    for key, fn, favg, fhit in _ai_fill_stats(db_path, user_id=uid):
        if fn <= 0:
            continue
        bits.append(f"{labels.get(key, key)} {favg:+.1f}%（勝 {fhit:.0%}／{fn}）")
    if bits:
        lines.append("　".join(bits[:4]))
    if sample:
        lines.append("<b>最近買進隔日</b>")
        try:
            from stock_links import html_stock_anchor
        except Exception:
            html_stock_anchor = None
        for i, (sid, name, pct, bucket, as_of) in enumerate(sample, start=1):
            as_s = f"{as_of[4:6]}/{as_of[6:]}" if as_of and len(as_of) == 8 else str(as_of or "")
            title = (
                html_stock_anchor(sid, name, db_path)
                if html_stock_anchor
                else f"{html_escape(sid)} {html_escape(name)}"
            )
            lines.append(
                f"{i}. {title}　{float(pct):+.1f}%　{html_escape(labels.get(bucket, bucket) or '')}　{html_escape(as_s)}"
            )
    return "\n".join(lines)
