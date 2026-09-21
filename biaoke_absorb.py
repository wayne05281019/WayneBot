# -*- coding: utf-8 -*-
"""飆大神經元彙整：抓文節奏不變；輔助先存。

開市日台北 08:00–13:30 每 10 分、盤後 16:30／19:30／22:30，
隔日 01:00（僅前一日曆日開市）才吸收。路人樓不進神經元。不是買訊。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from trading_calendar import TAIPEI, is_tw_open_calendar_day

logger = logging.getLogger("WayneBot.BiaokeAbsorb")

SLOT_GRACE_MIN = 8
_OPEN_START_MIN = 8 * 60
_OPEN_END_MIN = 13 * 60 + 30
_OPEN_STEP_MIN = 10
_AFTER_CLOSE_HMS = ((16, 30), (19, 30), (22, 30))
_NIGHT_HM = (1, 0)


def _open_session_hms() -> tuple:
    out = []
    t = _OPEN_START_MIN
    while t <= _OPEN_END_MIN:
        out.append((t // 60, t % 60))
        t += _OPEN_STEP_MIN
    return tuple(out)


OPEN_SESSION_HMS = _open_session_hms()


def _slot_label(ymd: str, hour: int, minute: int) -> str:
    return f"{ymd}-{hour:02d}{minute:02d}"


def _in_grace(hm: int, hour: int, minute: int) -> bool:
    start = hour * 60 + minute
    return start <= hm < start + SLOT_GRACE_MIN


_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_absorb_inbox (
    post_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'post',
    layer INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    five TEXT NOT NULL DEFAULT '',
    charts TEXT NOT NULL DEFAULT '',
    queued_at TEXT NOT NULL DEFAULT '',
    absorbed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_biaoke_absorb_pending
    ON biaoke_absorb_inbox(absorbed_at, queued_at);
CREATE TABLE IF NOT EXISTS biaoke_absorb_aux (
    post_id TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    aux TEXT NOT NULL DEFAULT '{}',
    queued_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, stock_id)
);
CREATE TABLE IF NOT EXISTS biaoke_absorb_runs (
    slot_id TEXT PRIMARY KEY,
    ran_at TEXT NOT NULL DEFAULT '',
    posts INTEGER NOT NULL DEFAULT 0,
    aux INTEGER NOT NULL DEFAULT 0
);
"""


def taipei_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(TAIPEI)
    if now.tzinfo is None:
        return now.replace(tzinfo=TAIPEI)
    return now.astimezone(TAIPEI)


def taipei_stamp(now: Optional[datetime] = None) -> str:
    return taipei_now(now).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_absorb_tables(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _yesterday_open(dt: datetime) -> bool:
    yest = (dt - timedelta(days=1)).strftime("%Y%m%d")
    return is_tw_open_calendar_day(yest)


def _slot_datetimes_on(day: datetime) -> List[datetime]:
    """該台北日曆日會醒的彙整點（尚未跟 now 比）。"""
    day = taipei_now(day).replace(second=0, microsecond=0)
    ymd = day.strftime("%Y%m%d")
    out: List[datetime] = []
    if _yesterday_open(day):
        out.append(day.replace(hour=_NIGHT_HM[0], minute=_NIGHT_HM[1]))
    if is_tw_open_calendar_day(ymd):
        for hour, minute in OPEN_SESSION_HMS:
            out.append(day.replace(hour=hour, minute=minute))
        for hour, minute in _AFTER_CLOSE_HMS:
            out.append(day.replace(hour=hour, minute=minute))
    return out


def absorb_slot_id(now: Optional[datetime] = None) -> str:
    """正在彙整窗才回 slot。抓文輪詢不走這條。"""
    dt = taipei_now(now)
    ymd = dt.strftime("%Y%m%d")
    hm = dt.hour * 60 + dt.minute
    if _in_grace(hm, *_NIGHT_HM) and _yesterday_open(dt):
        return _slot_label(ymd, *_NIGHT_HM)
    if is_tw_open_calendar_day(ymd):
        slot_start = (hm // _OPEN_STEP_MIN) * _OPEN_STEP_MIN
        if (
            _OPEN_START_MIN <= slot_start <= _OPEN_END_MIN
            and hm < slot_start + SLOT_GRACE_MIN
        ):
            return _slot_label(ymd, slot_start // 60, slot_start % 60)
        for hour, minute in _AFTER_CLOSE_HMS:
            if _in_grace(hm, hour, minute):
                return _slot_label(ymd, hour, minute)
    return ""


def planned_slot_id(when: datetime) -> str:
    dt = taipei_now(when)
    ymd = dt.strftime("%Y%m%d")
    pair = (dt.hour, dt.minute)
    if pair == _NIGHT_HM and _yesterday_open(dt):
        return _slot_label(ymd, *_NIGHT_HM)
    if is_tw_open_calendar_day(ymd):
        if pair in OPEN_SESSION_HMS or pair in _AFTER_CLOSE_HMS:
            return _slot_label(ymd, dt.hour, dt.minute)
    return absorb_slot_id(dt)


def next_absorb_at(now: Optional[datetime] = None) -> datetime:
    """下一檔台北彙整：開市日 08:00–13:30／10 分、盤後三小時、隔日 01:00。"""
    dt = taipei_now(now)
    best: Optional[datetime] = None
    for day_off in range(0, 16):
        day = dt + timedelta(days=day_off)
        for cand in _slot_datetimes_on(day):
            if cand > dt and (best is None or cand < best):
                best = cand
        if best is not None:
            break
    return best or (dt + timedelta(minutes=_OPEN_STEP_MIN))


def _slot_ran(db_path: str, slot_id: str) -> bool:
    if not db_path or not slot_id:
        return False
    ensure_absorb_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT 1 FROM biaoke_absorb_runs WHERE slot_id=?", (slot_id,)
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mark_slot(db_path: str, slot_id: str, *, posts: int, aux: int, now: Optional[datetime] = None) -> None:
    ensure_absorb_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_absorb_runs(slot_id, ran_at, posts, aux)
            VALUES (?,?,?,?)
            ON CONFLICT(slot_id) DO UPDATE SET
                ran_at=excluded.ran_at,
                posts=excluded.posts,
                aux=excluded.aux
            """,
            (slot_id, taipei_stamp(now), int(posts), int(aux)),
        )
        conn.commit()
    finally:
        conn.close()


def _px(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _recent_equity_bars(conn: sqlite3.Connection, sid: str, n: int = 80) -> List[Dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, IFNULL(pct_change, '') "
            "FROM daily_quotes WHERE stock_id=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (sid, int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: List[Dict[str, Any]] = []
    for date_s, o, h, l, c, v, pct in reversed(rows):
        out.append(
            {
                "date": _ymd(date_s),
                "open": _px(o),
                "high": _px(h),
                "low": _px(l),
                "close": _px(c),
                "volume": _px(v),
                "pct_change": _px(pct),
            }
        )
    return out


def _recent_index_bars(conn: sqlite3.Connection, n: int = 80) -> List[Dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM index_daily WHERE symbol='TWII' OR symbol='^TWII' "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (int(n),),
        ).fetchall()
    except sqlite3.Error:
        return []
    out: List[Dict[str, Any]] = []
    for date_s, o, h, l, c, v in reversed(rows):
        out.append(
            {
                "date": _ymd(date_s),
                "open": _px(o),
                "high": _px(h),
                "low": _px(l),
                "close": _px(c),
                "volume": _px(v),
            }
        )
    return out


def _card_from_bars(bars: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """用已存日 K 算出高低卡既有欄，彙整時不用重抓。沒柱就空，不編。"""
    if not bars:
        return {}
    last = bars[-1]
    last_day = str(last.get("date") or "")
    highs = [b.get("high") for b in bars[-20:] if b.get("high") is not None]
    lows = [b.get("low") for b in bars[-20:] if b.get("low") is not None]
    hi20 = max(highs) if highs else None
    lo20 = min(lows) if lows else None
    cal60 = None
    if last_day:
        floor = None
        try:
            last_dt = datetime.strptime(last_day, "%Y%m%d")
            floor = (last_dt - timedelta(days=59)).strftime("%Y%m%d")
        except ValueError:
            floor = None
        closes = []
        for b in bars:
            day = str(b.get("date") or "")
            c = b.get("close")
            if c is None or not day:
                continue
            if floor and day < floor:
                continue
            closes.append(float(c))
        if closes:
            cal60 = min(closes)
    close = last.get("close")
    profit = None
    if close is not None and cal60:
        profit = round((float(close) / float(cal60) - 1.0) * 100.0, 1)
    return {
        "bar_date": last_day,
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "close": close,
        "volume": last.get("volume"),
        "hi20": hi20,
        "lo20": lo20,
        "cal60": cal60,
        "profit_pct": profit,
        "bars_n": len(bars),
    }


def _chart_urls(text: str) -> List[str]:
    try:
        from biaoke_walk import post_chart_urls

        return list(post_chart_urls(text) or [])[:6]
    except Exception:
        return []


def _stash_charts(urls: Sequence[str], post_id: str, db_path: str) -> List[str]:
    """圖檔 URL 必存；能抓到的附件寫進 data/biaoke_aux_charts，彙整時不重找。"""
    saved: List[str] = []
    root = os.path.join(os.path.dirname(os.path.abspath(db_path)), "biaoke_aux_charts")
    pid = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(post_id or ""))[:48]
    for i, url in enumerate(urls or []):
        u = str(url or "").strip()
        if not u:
            continue
        saved.append(u)
        if not u.startswith("https://image.cmoney.tw/attachment/"):
            continue
        if os.getenv("PYTEST_CURRENT_TEST"):
            continue
        try:
            import requests

            os.makedirs(root, exist_ok=True)
            dest = os.path.join(root, f"{pid}_{i}.bin")
            if os.path.isfile(dest) and os.path.getsize(dest) > 32:
                saved.append(dest)
                continue
            resp = requests.get(u, timeout=6)
            if int(getattr(resp, "status_code", 0) or 0) != 200:
                continue
            blob = resp.content or b""
            if len(blob) < 32:
                continue
            tmp = dest + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, dest)
            saved.append(dest)
        except Exception:
            continue
    return saved


def _fill_missing_quotes(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """提到的檔缺月日 K 現在就抓，不要等到彙整窗再打證交所。"""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return 0
    posts = [dict(ev) for ev in (events or []) if str(ev.get("kind") or "") != "bystander"]
    if not posts:
        return 0
    try:
        from biaoke_walk import fetch_missing_quotes

        got = fetch_missing_quotes(db_path, posts, sleep_s=0.2, limit=24)
        return int(got.get("months") or 0)
    except Exception:
        logger.exception("飆大點名缺月日K先補失敗")
        return 0


def _stock_aux(
    db_path: str,
    sid: str,
    name: str,
    *,
    post_date: str,
    spoken: str,
    charts: Sequence[str],
) -> Dict[str, Any]:
    from biaoke_tape import official_for_post

    bar, pinned = official_for_post(db_path, sid, post_date)
    listing = ""
    fine = ""
    try:
        from universe import listing_industry_face

        listing = listing_industry_face(sid, db_path) if sid != "TWII" else "加權"
    except Exception:
        listing = ""
    if sid and sid != "TWII":
        try:
            from industry_fine import (
                fetch_cmoney_fine_industry,
                load_cached_fine_industry,
                save_fine_industry,
            )

            cached = load_cached_fine_industry(db_path, [sid])
            rec = cached.get(sid) or {}
            if not rec and not os.getenv("PYTEST_CURRENT_TEST"):
                rec = fetch_cmoney_fine_industry(sid) or {}
                if rec:
                    save_fine_industry(db_path, rec)
            fine = str((rec or {}).get("chain") or "")
        except Exception:
            fine = ""
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        bars = (
            _recent_index_bars(conn)
            if sid == "TWII"
            else _recent_equity_bars(conn, sid)
        )
    finally:
        conn.close()
    card = _card_from_bars(bars)
    last20 = bars[-20:] if bars else []
    return {
        "stock_id": sid,
        "stock_name": name,
        "listing": listing,
        "fine_industry": fine,
        "pinned_intraday": bool(pinned),
        "official": {
            "date": str((bar or {}).get("date") or ""),
            "open": (bar or {}).get("open"),
            "high": (bar or {}).get("high"),
            "low": (bar or {}).get("low"),
            "close": (bar or {}).get("close"),
            "volume": (bar or {}).get("volume"),
            "pct_change": (bar or {}).get("pct_change"),
        }
        if bar
        else {},
        "card": card,
        "recent_bars": last20,
        "charts": list(charts or []),
        "spoken_clip": str(spoken or "")[:240],
        "tz": "Asia/Taipei",
    }


def queue_absorb_events(
    db_path: str,
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """抓到就入匣＋把點名檔的評斷底料／圖檔存好。不進神經元。"""
    stats = {"queued": 0, "aux": 0, "quotes": 0}
    if not db_path or not events:
        return stats
    ensure_absorb_tables(db_path)
    stamp = taipei_stamp(now)
    packed = [dict(ev) for ev in events if str(ev.get("kind") or "") != "bystander"]
    if not packed:
        return stats
    stats["quotes"] = _fill_missing_quotes(db_path, packed)
    try:
        from biaoke_tape import named_pairs
    except Exception:
        named_pairs = lambda *_a, **_k: []  # noqa: E731
    try:
        from biaoke_watch import think_spoken
    except Exception:
        think_spoken = lambda *_a, **_k: {}  # noqa: E731

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for ev in packed:
            pid = str(ev.get("id") or ev.get("post_id") or "").strip()
            raw = str(ev.get("text") or "").strip()
            if not pid or not raw:
                continue
            five = ""
            try:
                thought = think_spoken(raw)
                five = str((thought or {}).get("five") or "")
            except Exception:
                five = ""
            charts = _stash_charts(_chart_urls(raw), pid, db_path)
            payload = {
                "id": pid,
                "post_id": pid,
                "date": str(ev.get("date") or ""),
                "time": str(ev.get("time") or ""),
                "kind": str(ev.get("kind") or "post"),
                "layer": int(ev.get("layer") or 0),
                "parent": str(ev.get("parent") or ""),
                "tags": list(ev.get("tags") or []),
                "text": raw[:4000],
                "reply_to_text": str(ev.get("reply_to_text") or "")[:240],
                "voice": str(ev.get("voice") or "author"),
            }
            conn.execute(
                """
                INSERT INTO biaoke_absorb_inbox(
                    post_id, kind, layer, payload, five, charts, queued_at, absorbed_at
                ) VALUES (?,?,?,?,?,?,?, '')
                ON CONFLICT(post_id) DO UPDATE SET
                    kind=excluded.kind,
                    layer=excluded.layer,
                    payload=excluded.payload,
                    five=excluded.five,
                    charts=excluded.charts,
                    queued_at=excluded.queued_at,
                    absorbed_at=''
                """,
                (
                    pid,
                    payload["kind"],
                    payload["layer"],
                    json.dumps(payload, ensure_ascii=False),
                    five,
                    " ".join(charts),
                    stamp,
                ),
            )
            stats["queued"] += 1
            pairs = list(named_pairs(raw, ev.get("tags")) or [])
            spoken = raw
            if any(
                k in spoken
                for k in ("大盤", "加權", "台指", "C-2", "C-3", "逃命波")
            ) and not any(s == "TWII" for s, _n in pairs):
                pairs.append(("TWII", "加權"))
            for sid, name in pairs:
                aux = _stock_aux(
                    db_path,
                    sid,
                    name,
                    post_date=str(ev.get("date") or ""),
                    spoken=spoken,
                    charts=charts,
                )
                conn.execute(
                    """
                    INSERT INTO biaoke_absorb_aux(post_id, stock_id, stock_name, aux, queued_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(post_id, stock_id) DO UPDATE SET
                        stock_name=excluded.stock_name,
                        aux=excluded.aux,
                        queued_at=excluded.queued_at
                    """,
                    (
                        pid,
                        sid,
                        name,
                        json.dumps(aux, ensure_ascii=False),
                        stamp,
                    ),
                )
                stats["aux"] += 1
        conn.commit()
    finally:
        conn.close()
    return stats


def pending_events(db_path: str) -> List[Dict[str, Any]]:
    if not db_path:
        return []
    ensure_absorb_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT payload FROM biaoke_absorb_inbox
            WHERE IFNULL(absorbed_at,'')=''
            ORDER BY queued_at ASC, post_id ASC
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for (blob,) in rows:
        try:
            row = json.loads(blob or "{}")
        except Exception:
            continue
        if isinstance(row, dict) and row.get("id"):
            out.append(row)
    return out


def aux_for_post(db_path: str, post_id: str) -> List[Dict[str, Any]]:
    if not db_path or not post_id:
        return []
    ensure_absorb_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT stock_id, stock_name, aux FROM biaoke_absorb_aux WHERE post_id=?",
            (post_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for sid, name, blob in rows:
        try:
            rec = json.loads(blob or "{}")
        except Exception:
            rec = {}
        if not isinstance(rec, dict):
            rec = {}
        rec.setdefault("stock_id", sid)
        rec.setdefault("stock_name", name)
        out.append(rec)
    return out


def _mark_absorbed(db_path: str, post_ids: Sequence[str], now: Optional[datetime] = None) -> None:
    ids = [str(p) for p in post_ids if p]
    if not ids:
        return
    stamp = taipei_stamp(now)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        conn.executemany(
            "UPDATE biaoke_absorb_inbox SET absorbed_at=? WHERE post_id=?",
            [(stamp, pid) for pid in ids],
        )
        conn.commit()
    finally:
        conn.close()


def run_absorb(
    db_path: str,
    *,
    now: Optional[datetime] = None,
    slot: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """只在台北開市日 08:00–13:30／10 分、盤後三小時、隔日 01:00 把匣丟進神經元。"""
    dt = taipei_now(now)
    slot_id = str(slot or planned_slot_id(dt) or absorb_slot_id(dt))
    stats: Dict[str, Any] = {"ok": False, "slot": slot_id, "posts": 0, "neurons": 0, "tz": "Asia/Taipei"}
    if not db_path:
        stats["reason"] = "no_db"
        return stats
    if not slot_id and not force:
        stats["reason"] = "not_slot"
        return stats
    if slot_id and _slot_ran(db_path, slot_id) and not force:
        stats["ok"] = True
        stats["skipped"] = True
        return stats
    events = pending_events(db_path)
    stats["posts"] = len(events)
    if events:
        try:
            from biaoke_why import ingest_why_events

            ingest_why_events(events, db_path)
        except Exception:
            logger.exception("飆大彙整判斷鏈失敗")
        try:
            from biaoke_watch import record_watch_events

            record_watch_events(db_path, events)
        except Exception:
            logger.exception("飆大彙整觀察失敗")
        try:
            from biaoke_forecast import record_from_events

            record_from_events(db_path, events)
        except Exception:
            logger.exception("飆大彙整演算失敗")
        try:
            from biaoke_neurons import record_neuron_events

            stats["neurons"] = int(record_neuron_events(db_path, events) or 0)
        except Exception:
            logger.exception("飆大彙整神經元失敗")
        try:
            from biaoke_weave import load_weave

            load_weave.cache_clear()
        except Exception:
            pass
        _mark_absorbed(db_path, [str(ev.get("id") or "") for ev in events], now=dt)
    if str(slot_id).endswith("-0100"):
        try:
            from silent_progress import night_review

            night_review(db_path)
        except Exception:
            logger.exception("凌晨默默覆盤失敗")
    if slot_id:
        aux_n = 0
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute("SELECT COUNT(*) FROM biaoke_absorb_aux").fetchone()
            aux_n = int(row[0] if row else 0)
        except sqlite3.Error:
            aux_n = 0
        finally:
            conn.close()
        _mark_slot(db_path, slot_id, posts=stats["posts"], aux=aux_n, now=dt)
    stats["ok"] = True
    return stats


def start_biaoke_absorb_scheduler() -> Optional[Any]:
    """與抓文輪詢分開：開市日 08:00–13:30／10 分、盤後到 01:00。GHA --once 不開。"""
    import threading
    import time as _time

    from config import daily_scheduler_enabled, get_db_path, is_once_mode

    if is_once_mode() or not daily_scheduler_enabled():
        return None

    def _loop() -> None:
        _time.sleep(120)
        while True:
            nxt = next_absorb_at()
            wait = max(5.0, (nxt - taipei_now()).total_seconds())
            logger.info(
                "飆大神經元彙整：約 %.0f 秒後台灣 %s",
                wait,
                nxt.strftime("%m/%d %H:%M"),
            )
            _time.sleep(wait)
            try:
                slot = planned_slot_id(nxt)
                run_absorb(get_db_path(), now=taipei_now(), slot=slot)
            except Exception:
                logger.exception("飆大神經元彙整失敗")

    t = threading.Thread(target=_loop, name="biaoke-absorb", daemon=True)
    t.start()
    return t
