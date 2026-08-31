"""海選隔日復盤：用庫裡已經有的日 K，對昨天寄出的名單算隔日報酬。

不另抓行情、不改程式檔。進化只寫 ai_params（哪一類最近比較準），
跟 AI 模擬倉調 size_mult 是同一套做法。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

BUCKETS = (
    ("revenue_cross", "優先看"),
    ("leave_zero", "起漲"),
    ("select_01", "周突破"),
    ("select_02", "半年高"),
    ("select_03", "兩年高"),
    ("select_04", "雙綠"),
    ("day_trade", "當沖"),
    ("overnight", "隔日沖"),
)
BUCKET_CAP = 8
WEAK_AVG = -1.0
WEAK_N = 5


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
    """只存當天實際寄出／展示的前幾檔，列數很小。"""
    as_of = str(as_of or "").replace("-", "")
    if not as_of or not results:
        return 0
    ensure_screen_review_table(db_path)
    n = 0
    conn = sqlite3.connect(db_path)
    for key, _label in BUCKETS:
        items = results.get(key) or []
        if not isinstance(items, list):
            continue
        for it in items[:BUCKET_CAP]:
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if not sid:
                continue
            try:
                close = float(it.get("close") or 0)
            except (TypeError, ValueError):
                close = 0.0
            if close <= 0:
                continue
            name = str(it.get("stock_name") or it.get("name") or "")
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
            f"SELECT next_pct FROM screen_picks WHERE bucket=? AND next_pct IS NOT NULL AND as_of IN ({qmarks})",
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


def adapt_bucket_weights(db_path: str) -> Dict[str, float]:
    """近幾日某類隔日平均 < -1% 且樣本夠 → 權重降到 0，AI 模擬倉先不買那類。"""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS ai_params (k TEXT PRIMARY KEY, v REAL NOT NULL);")
    weights = {}
    for key, n, avg, _hit in _bucket_stats(db_path):
        if n >= WEAK_N and avg <= WEAK_AVG:
            w = 0.0
        elif n >= WEAK_N and avg >= 1.0:
            w = 1.1
        else:
            w = 1.0
        conn.execute(
            "INSERT OR REPLACE INTO ai_params(k, v) VALUES (?, ?)",
            (f"bucket_w_{key}", w),
        )
        weights[key] = w
    conn.commit()
    conn.close()
    return weights


def bucket_weight(db_path: str, key: str) -> float:
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
            LIMIT 6
            """,
            (as_of,),
        ).fetchall()
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
        for bucket, sid, name, pct in sample:
            lines.append(
                f"• <code>{html_escape(sid)}</code> {html_escape(name)}　{float(pct):+.1f}%　{html_escape(labels.get(bucket, bucket))}"
            )
    return "\n".join(lines)
