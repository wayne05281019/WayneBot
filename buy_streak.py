# -*- coding: utf-8 -*-
"""連買區域：外資／投信／外資+投信 連續買超（上市／上櫃）。"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

KIND_FOREIGN = "foreign"
KIND_TRUST = "trust"
KIND_BOTH = "both"
KINDS = (KIND_FOREIGN, KIND_TRUST, KIND_BOTH)

KIND_LABEL = {
    KIND_FOREIGN: "外資連買",
    KIND_TRUST: "投信連買",
    KIND_BOTH: "外資+投信皆買",
}
KIND_BTN = {
    KIND_FOREIGN: "外資",
    KIND_TRUST: "投信",
    KIND_BOTH: "外資+投信",
}

MARKET_TW = "TW"
MARKET_TWO = "TWO"
MARKET_LABEL = {MARKET_TW: "上市", MARKET_TWO: "上櫃"}
MARKET_ALIASES = {
    "上市": MARKET_TW,
    "上市股票": MARKET_TW,
    "twse": MARKET_TW,
    "tse": MARKET_TW,
    "tw": MARKET_TW,
    "上櫃": MARKET_TWO,
    "上櫃股票": MARKET_TWO,
    "otc": MARKET_TWO,
    "tpex": MARKET_TWO,
    "two": MARKET_TWO,
}

KIND_ALIASES = {
    "外資": KIND_FOREIGN,
    "外資連買": KIND_FOREIGN,
    "投信": KIND_TRUST,
    "投信連買": KIND_TRUST,
    "外資+投信": KIND_BOTH,
    "外資＋投信": KIND_BOTH,
    "投信外資皆買": KIND_BOTH,
    "外資投信皆買": KIND_BOTH,
    "皆買": KIND_BOTH,
    "一起買": KIND_BOTH,
}

LOOKBACK_SESSIONS = 80
MIN_STREAK = 2
CACHE_SEC = 300.0
PAGE_SIZE = 12

_CACHE: Dict[str, Tuple[float, "StreakSnapshot"]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class StreakRow:
    stock_id: str
    name: str
    market: str
    days: int
    foreign_lots: int
    trust_lots: int
    volume_lots: int

    @property
    def foreign_pct(self) -> Optional[float]:
        if self.volume_lots <= 0:
            return None
        return round(self.foreign_lots / self.volume_lots * 100.0, 1)

    @property
    def trust_pct(self) -> Optional[float]:
        if self.volume_lots <= 0:
            return None
        return round(self.trust_lots / self.volume_lots * 100.0, 1)

    @property
    def lead_lots(self) -> int:
        if self.foreign_lots and self.trust_lots:
            return self.foreign_lots + self.trust_lots
        return self.foreign_lots or self.trust_lots


@dataclass
class StreakSnapshot:
    as_of: str
    kind: str
    market: str
    max_days: int = 0
    by_days: Dict[int, List[StreakRow]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{KIND_LABEL.get(self.kind, self.kind)} · {MARKET_LABEL.get(self.market, self.market)}"

    def days_menu(self, *, min_days: int = MIN_STREAK) -> List[int]:
        """最長天數往下排到 min_days（中間空檔也列出，點進去會說沒有）。"""
        if self.max_days < min_days:
            return []
        return list(range(self.max_days, min_days - 1, -1))

    def stocks(self, days: int) -> List[StreakRow]:
        return list(self.by_days.get(int(days), []))


def parse_kind(text: str) -> Optional[str]:
    t = (text or "").strip()
    return KIND_ALIASES.get(t)


def parse_market(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    return MARKET_ALIASES.get(t) or MARKET_ALIASES.get((text or "").strip())


def parse_days(text: str) -> Optional[int]:
    t = (text or "").strip().replace("天", "").replace("日", "")
    if t.isdigit():
        n = int(t)
        if 1 <= n <= 120:
            return n
    return None


def parse_stock_code(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    head = t.split()[0].strip()
    if head.isdigit() and 4 <= len(head) <= 6:
        return head
    return None


def _kind_ok(foreign: int, trust: int, kind: str) -> bool:
    if kind == KIND_FOREIGN:
        return foreign > 0
    if kind == KIND_TRUST:
        return trust > 0
    if kind == KIND_BOTH:
        return foreign > 0 and trust > 0
    return False


def _pct_text(pct: Optional[float]) -> str:
    if pct is None:
        return "—"
    return f"{pct:.1f}%"


def _lots_text(n: int) -> str:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 0
    return f"{v:,}張"


def format_row_lines(row: StreakRow, kind: str) -> List[str]:
    d = int(row.days)
    if kind == KIND_FOREIGN:
        return [
            f"{d}日連買 {_lots_text(row.foreign_lots)}",
            f"佔{d}日總成交 {_pct_text(row.foreign_pct)}",
        ]
    if kind == KIND_TRUST:
        return [
            f"{d}日連買 {_lots_text(row.trust_lots)}",
            f"佔{d}日總成交 {_pct_text(row.trust_pct)}",
        ]
    return [
        f"{d}日皆買 外資 {_lots_text(row.foreign_lots)}／投信 {_lots_text(row.trust_lots)}",
        (
            f"佔{d}日總成交 外資 {_pct_text(row.foreign_pct)}"
            f" · 投信 {_pct_text(row.trust_pct)}"
        ),
    ]


def format_stock_html(row: StreakRow, kind: str, db_path: Optional[str] = None) -> str:
    try:
        from stock_links import html_stock_anchor

        title = html_stock_anchor(row.stock_id, row.name, db_path)
    except Exception:
        title = f"{row.stock_id} {row.name}".strip()
    lines = [title, *format_row_lines(row, kind)]
    return "\n".join(lines)


def format_list_html(
    snap: StreakSnapshot,
    days: int,
    db_path: Optional[str] = None,
    *,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> str:
    rows = snap.stocks(days)
    total = len(rows)
    chunk = rows[offset : offset + limit]
    as_of = snap.as_of
    try:
        from trading_calendar import format_trading_date_zh

        as_of_s = format_trading_date_zh(as_of)
    except Exception:
        as_of_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:8]}" if len(as_of) == 8 else as_of
    head = (
        f"<b>{KIND_LABEL.get(snap.kind, snap.kind)} {days} 天 · "
        f"{MARKET_LABEL.get(snap.market, snap.market)}</b>"
        f"　{total} 檔\n"
        f"截至 {as_of_s} 官方籌碼（剛好連買 {days} 天，不是以上）。\n"
        "股名＝奇摩走勢；點鍵盤股名看出完整圖；旁「籌碼」核對法人買賣超。"
    )
    if not chunk:
        return head + "\n\n<i>這個天數目前沒有股票。</i>"
    blocks = [head, ""]
    for i, row in enumerate(chunk, start=offset + 1):
        blocks.append(f"{i}. {format_stock_html(row, snap.kind, db_path)}")
        blocks.append("")
    if offset + limit < total:
        blocks.append(f"<i>還有 {total - offset - limit} 檔，按「下一批」。</i>")
    return "\n".join(blocks).strip()


def _cache_key(db_path: str, kind: str, market: str, as_of: str) -> str:
    return f"{db_path}|{kind}|{market}|{as_of}"


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def resolve_official_as_of(db_path: str, *, now=None) -> str:
    """連買最後一天＝庫內官方融合收盤日（與海選／大盤同一基準，不晚於 fuse 上限）。"""
    try:
        from trading_calendar import resolve_screen_as_of

        return str(resolve_screen_as_of(db_path, now=now) or "").replace("-", "")[:8]
    except Exception:
        pass
    try:
        from import_health import latest_complete_quote_date

        return str(latest_complete_quote_date(db_path, now=now) or "").replace("-", "")[:8]
    except Exception:
        return ""


def _latest_chip_date(conn: sqlite3.Connection, market: str, as_of: str) -> str:
    """as_of 當日該市場已有日K＋法人欄位即可（基準日本身由 resolve_official_as_of 決定）。"""
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE length(q.stock_id) = 4
          AND q.date = ?
          AND UPPER(COALESCE(u.market_type, q.market, '')) = ?
        """,
        (as_of, market),
    ).fetchone()
    if row and int(row[0] or 0) > 0:
        return as_of
    return ""


def _load_rows(
    conn: sqlite3.Connection, market: str, cutoff: str
) -> Tuple[List[str], Dict[str, Tuple[str, List[Tuple[str, int, int, int]]]]]:
    cur = conn.execute(
        """
        SELECT q.stock_id,
               COALESCE(NULLIF(u.stock_name, ''), q.stock_name, q.stock_id),
               q.date,
               COALESCE(q.foreign_net, 0),
               COALESCE(q.trust_net, 0),
               COALESCE(q.volume, 0)
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE length(q.stock_id) = 4
          AND q.date >= ?
          AND UPPER(COALESCE(u.market_type, q.market, '')) = ?
          AND UPPER(COALESCE(u.asset_type, 'STOCK')) IN ('STOCK', 'KY')
          AND COALESCE(u.is_active, 1) = 1
        ORDER BY q.stock_id, q.date
        """,
        (cutoff, market),
    )
    dates: List[str] = []
    date_seen = set()
    by_sid: Dict[str, Tuple[str, List[Tuple[str, int, int, int]]]] = {}
    for sid, name, date, foreign, trust, volume in cur:
        sid = str(sid).strip()
        date = str(date)
        if date not in date_seen:
            date_seen.add(date)
            dates.append(date)
        bucket = by_sid.get(sid)
        if bucket is None:
            by_sid[sid] = (str(name or sid), [(date, int(foreign), int(trust), int(volume))])
        else:
            bucket[1].append((date, int(foreign), int(trust), int(volume)))
    dates.sort()
    return dates, by_sid


def _compute_streak(
    dates: Sequence[str],
    bars: Sequence[Tuple[str, int, int, int]],
    kind: str,
) -> Tuple[int, int, int, int]:
    """從最新交易日往回算連續符合天數；缺K或當日不符合即中斷。"""
    if not dates or not bars:
        return 0, 0, 0, 0
    fmap = {d: f for d, f, _t, _v in bars}
    tmap = {d: t for d, _f, t, _v in bars}
    vmap = {d: v for d, _f, _t, v in bars}
    n = 0
    f_acc = t_acc = v_acc = 0
    for d in reversed(dates):
        if d not in fmap and d not in tmap:
            break
        foreign = int(fmap.get(d) or 0)
        trust = int(tmap.get(d) or 0)
        if not _kind_ok(foreign, trust, kind):
            break
        n += 1
        f_acc += foreign
        t_acc += trust
        v_acc += int(vmap.get(d) or 0)
    return n, f_acc, t_acc, v_acc


def load_snapshot(
    db_path: str,
    kind: str,
    market: str,
    *,
    as_of: Optional[str] = None,
    lookback: int = LOOKBACK_SESSIONS,
    use_cache: bool = True,
) -> StreakSnapshot:
    kind = str(kind or "").strip()
    market = str(market or "").strip().upper()
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    if market not in (MARKET_TW, MARKET_TWO):
        raise ValueError(f"unknown market {market}")

    conn = sqlite3.connect(db_path)
    try:
        chip_as_of = str(as_of or "").replace("-", "")[:8] or resolve_official_as_of(db_path)
        if not chip_as_of:
            return StreakSnapshot(as_of="", kind=kind, market=market)
        if not _latest_chip_date(conn, market, chip_as_of):
            return StreakSnapshot(as_of=chip_as_of, kind=kind, market=market)

        cache_key = _cache_key(db_path, kind, market, chip_as_of)
        if use_cache:
            with _CACHE_LOCK:
                hit = _CACHE.get(cache_key)
            if hit and (time.time() - hit[0]) < CACHE_SEC:
                return hit[1]

        dates_all = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT DISTINCT q.date
                FROM daily_quotes q
                LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE length(q.stock_id) = 4
                  AND UPPER(COALESCE(u.market_type, q.market, '')) = ?
                  AND q.date <= ?
                ORDER BY q.date DESC
                LIMIT ?
                """,
                (market, chip_as_of, int(lookback)),
            ).fetchall()
        ]
        if not dates_all:
            snap = StreakSnapshot(as_of=chip_as_of, kind=kind, market=market)
        else:
            cutoff = dates_all[-1]
            session_dates = list(reversed(dates_all))
            _dates, by_sid = _load_rows(conn, market, cutoff)
            by_days: Dict[int, List[StreakRow]] = {}
            max_days = 0
            for sid, (name, bars) in by_sid.items():
                days, f_acc, t_acc, v_acc = _compute_streak(session_dates, bars, kind)
                if days < MIN_STREAK:
                    continue
                row = StreakRow(
                    stock_id=sid,
                    name=name,
                    market=market,
                    days=days,
                    foreign_lots=f_acc,
                    trust_lots=t_acc,
                    volume_lots=v_acc,
                )
                by_days.setdefault(days, []).append(row)
                if days > max_days:
                    max_days = days
            for bucket in by_days.values():
                bucket.sort(key=lambda r: (-r.lead_lots, r.stock_id))
            snap = StreakSnapshot(
                as_of=chip_as_of,
                kind=kind,
                market=market,
                max_days=max_days,
                by_days=by_days,
            )
        if use_cache:
            with _CACHE_LOCK:
                _CACHE[cache_key] = (time.time(), snap)
        return snap
    finally:
        conn.close()


def find_row(snap: StreakSnapshot, days: int, stock_id: str) -> Optional[StreakRow]:
    sid = str(stock_id or "").strip()
    for row in snap.stocks(days):
        if row.stock_id == sid:
            return row
    return None


def page_bounds(total: int, offset: int, limit: int = PAGE_SIZE) -> Tuple[int, bool, bool]:
    off = max(0, int(offset))
    lim = max(1, int(limit))
    has_prev = off > 0
    has_next = off + lim < total
    return off, has_prev, has_next
