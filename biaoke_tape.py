# -*- coding: utf-8 -*-
"""捕獲飆大主文／自回後立刻對官方日 K 建檔。

點到的檔才寫。IET＝IET-KY 4971。引號裡路人話不收。
盤中未收盤柱不當官方收，對最後一根完整官方柱。不是買訊。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_tape (
    post_id TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    bar_date TEXT NOT NULL DEFAULT '',
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    pct_change REAL,
    note TEXT NOT NULL DEFAULT '',
    charts TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, stock_id)
);
CREATE INDEX IF NOT EXISTS idx_biaoke_tape_sid ON biaoke_tape(stock_id, post_date);
"""
_IDX = re.compile(r"(大盤|加權|台指|C-2|C-3|逃命波)")
_SPACE = re.compile(r"\s+")
_TICKER = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def ensure_biaoke_tape_table(db_path: str) -> None:
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


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "").strip()


def _snip(text: str, needle: str, n: int = 80) -> str:
    blob = _SPACE.sub(" ", text or "").strip()
    if not blob:
        return ""
    i = blob.find(needle) if needle else -1
    if i < 0:
        return blob[:n]
    a = max(0, i - 10)
    return blob[a : a + n]


def named_pairs(text: str, tags: Optional[Sequence[Any]] = None) -> List[Tuple[str, str]]:
    """只收他點過、表裡有代號的檔。IET＝IET-KY 4971。"""
    from biaoke_why import _NAME_SID, named_stocks

    spoken = _spoken(text)
    out: List[Tuple[str, str]] = []
    seen = set()
    for name in named_stocks(spoken, tags):
        sid = str(_NAME_SID.get(name) or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        shown = "IET-KY" if sid == "4971" else name
        if sid != "4971":
            for alias, other in _NAME_SID.items():
                if str(other) == sid:
                    shown = alias
                    break
        out.append((sid, shown))
    inv: Dict[str, str] = {}
    for name, sid in _NAME_SID.items():
        sid_s = str(sid)
        if sid_s not in inv or len(name) > len(inv[sid_s]):
            inv[sid_s] = name
    for m in _TICKER.finditer(spoken):
        sid = m.group(1)
        if sid in inv and sid not in seen:
            seen.add(sid)
            shown = "IET-KY" if sid == "4971" else inv[sid]
            out.append((sid, shown))
    return out


def last_official_bar(db_path: str, sid: str) -> Optional[Dict[str, Any]]:
    """庫裡最後一根完整官方柱。沒這列就空，不編。"""
    from biaoke_link import bar_on

    if not db_path or not os.path.isfile(db_path) or not sid:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        if sid == "TWII":
            try:
                row = conn.execute(
                    "SELECT date FROM index_daily "
                    "WHERE symbol='TWII' OR symbol='^TWII' "
                    "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1"
                ).fetchone()
            except sqlite3.Error:
                row = None
        else:
            try:
                row = conn.execute(
                    "SELECT date FROM daily_quotes WHERE stock_id=? "
                    "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1",
                    (sid,),
                ).fetchone()
            except sqlite3.Error:
                row = None
    finally:
        conn.close()
    if not row:
        return None
    return bar_on(db_path, sid, str(row[0]))


def official_for_post(db_path: str, sid: str, post_date: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """發文當天有完整官方柱就用當天；沒有就對最後一根，並標未收盤。"""
    from biaoke_link import bar_on

    day = _ymd(post_date)
    bar = bar_on(db_path, sid, day) if day else None
    if bar:
        return bar, False
    last = last_official_bar(db_path, sid)
    if last:
        return last, True
    return None, bool(day)


def recent_quote_bars(db_path: str, sid: str, n: int = 30) -> List[Dict[str, Any]]:
    """舊→新官方日 K。缺日不編。櫃買量欄失真的檔仍回高低收。"""
    if not db_path or not os.path.isfile(db_path) or not sid or sid == "TWII":
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (sid, max(8, int(n))),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in reversed(rows):
        try:
            out.append(
                {
                    "date": str(r[0] or ""),
                    "open": float(r[1] or 0),
                    "high": float(r[2] or 0),
                    "low": float(r[3] or 0),
                    "close": float(r[4] or 0),
                    "volume": float(r[5] or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def _fake_kind(bars: Sequence[Dict[str, Any]]) -> str:
    if len(bars) < 8:
        return ""
    try:
        from biaoke_vol_fake import classify_volume_fake

        rows = [
            (
                str(b.get("date") or ""),
                float(b.get("high") or 0),
                float(b.get("low") or 0),
                float(b.get("close") or 0),
                float(b.get("volume") or 0),
            )
            for b in bars
        ]
        return str(classify_volume_fake(rows).get("kind") or "")
    except Exception:
        return ""


def _prior_high(bars: Sequence[Dict[str, Any]]) -> Tuple[str, float]:
    best_d, best_h = "", 0.0
    for b in bars[:-1]:
        try:
            h = float(b.get("high") or 0)
        except (TypeError, ValueError):
            continue
        if h > best_h:
            best_h = h
            best_d = str(b.get("date") or "")
    return best_d, best_h


def structure_vs_spoken(
    spoken: str, sid: str, bars: Sequence[Dict[str, Any]], *, skip_vol: bool = False
) -> str:
    """用官方高低量重述他為何能這樣說。不准發明 5／9。不是買訊。"""
    blob = spoken or ""
    if len(bars) < 8:
        return ""
    last = bars[-1]
    last_d = str(last.get("date") or "")
    last_h = float(last.get("high") or 0)
    last_l = float(last.get("low") or 0)
    last_c = float(last.get("close") or 0)
    last_v = last.get("volume")
    gate_d, gate_h = _prior_high(bars)
    kind = "" if skip_vol else _fake_kind(bars)
    bits: List[str] = []
    if sid == "3017" and re.search(r"(關前整理|主升段|下星期)", blob):
        bits.append(
            f"關前近高 {gate_d} 高{_px(gate_h)}；這根高{_px(last_h)}收{_px(last_c)}量"
            f"{int(last_v) if last_v is not None else '—'}，還沒有效過那根高"
        )
        if kind == "dump":
            bits.append("這根是爆量長上影＝轉弱K候選，關前完成這句對不上")
        elif kind == "pause":
            bits.append("這根爆量收在下半＝還要整理，主升還沒")
        else:
            bits.append("量沒爆、不是轉弱K，回測近高量縮＝他說的關前整理")
        bits.append("下星期二主升＝待驗證有效過近高，不是保證")
    elif sid == "3653" and re.search(r"(真突破|滾量上攻|整理完成)", blob):
        bits.append(
            f"前平台高 {gate_d} 高{_px(gate_h)}；這根高{_px(last_h)}收{_px(last_c)}"
            + (
                "收在當日高且收過前高＝他後來說的真突破"
                if last_c >= gate_h * 0.997 and last_c >= last_h * 0.997
                else "還沒用收盤確認過前高"
            )
        )
        bits.append("盤中改口滾量上攻／不好操作，待驗證不是保證")
    elif sid == "6274" and re.search(r"(前高|初步整理|聯發科|噴)", blob):
        bits.append(
            f"近窗高 {gate_d} 高{_px(gate_h)}；這根高{_px(last_h)}收{_px(last_c)}還在前高下"
            "＝到前高後整理，不像聯發科已過高後噴。櫃買量欄不採"
        )
    elif sid == "2455" and re.search(r"(沒有這麼快|沒這麼快|量縮買點)", blob):
        prior_v = [float(b.get("volume") or 0) for b in bars[-4:-1]]
        peak_v = max(prior_v) if prior_v else 0
        bits.append(
            f"近幾根量高{_px(peak_v)}、這根量{_px(last_v)}收{_px(last_c)}高{_px(last_h)}"
            "＝回測有沒有量縮還要看尾盤，他說還沒這麼快整理完成"
        )
    elif sid == "2368" and re.search(r"(整理完成|1245)", blob):
        bits.append(
            f"他點過的前高 1245；這根高{_px(last_h)}收{_px(last_c)}"
            + ("還沒過 1245" if last_h < 1245 else "高已碰到 1245 附近再對轉弱K")
        )
    elif sid == "2383" and re.search(r"(不破|支撐|布局|整理)", blob):
        low_d, low_v = "", 1e18
        for b in bars:
            try:
                lv = float(b.get("low") or 0)
            except (TypeError, ValueError):
                continue
            if 0 < lv < low_v:
                low_v = lv
                low_d = str(b.get("date") or "")
        bits.append(
            f"近窗低 {low_d} 低{_px(low_v)}；這根低{_px(last_l)}收{_px(last_c)}"
            + ("沒破那根低" if last_l >= low_v * 0.998 else "這根低已低於近窗低")
        )
    if bits:
        bits.append("不是買訊")
    return "；".join(bits)


def _note(
    name: str,
    spoken: str,
    bar: Optional[Dict[str, Any]],
    pinned: bool,
    *,
    extra: str = "",
) -> str:
    bits: List[str] = []
    if pinned:
        bits.append(
            f"盤中未收盤，對最後官方收 {bar.get('date')}" if bar else "盤中未收盤，官方還沒這列"
        )
    if not bar:
        if not pinned:
            bits.append("官方還沒這列，不准編")
        return "；".join(bits)
    vol = bar.get("volume")
    vol_s = str(int(vol)) if vol is not None else "—"
    bits.append(
        f"官方{name} {bar.get('date')} "
        f"開{_px(bar.get('open')) or '—'} 高{_px(bar.get('high')) or '—'} "
        f"低{_px(bar.get('low')) or '—'} 收{_px(bar.get('close')) or '—'} 量{vol_s}"
    )
    blob = spoken or ""
    if "站回" in blob or "跌破" in blob:
        bits.append("原文跌破／站回，對這根官方高低收")
    if "跌停" in blob and pinned:
        bits.append("原文跌停是盤中說法，未收盤不當官方收")
    if extra:
        bits.append(extra)
    return "；".join(bits)


def record_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """新抓到的主文／樓下立刻對官方圖建檔。"""
    if not db_path or not events:
        return 0
    ensure_biaoke_tape_table(db_path)
    try:
        from biaoke_walk import post_chart_urls
    except Exception:
        post_chart_urls = lambda _t: []  # noqa: E731

    rows: List[Tuple[Any, ...]] = []
    for ev in events:
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        spoken = _spoken(raw)
        charts = " ".join((post_chart_urls(raw) or [])[:4])
        pairs = named_pairs(raw, ev.get("tags"))
        if _IDX.search(spoken) and not any(s == "TWII" for s, _n in pairs):
            pairs.append(("TWII", "加權"))
        day = str(ev.get("date") or "")
        hm = str(ev.get("time") or "")
        for sid, name in pairs:
            bar, pinned = official_for_post(db_path, sid, day)
            hist = recent_quote_bars(db_path, sid, 30) if sid != "TWII" else []
            extra = structure_vs_spoken(
                spoken, sid, hist, skip_vol=(sid == "6274")
            )
            note = _note(name, spoken, bar, pinned, extra=extra)
            if extra and bar:
                try:
                    from biaoke_forecast import record_spoken_path

                    record_spoken_path(
                        db_path,
                        sid,
                        spoken=spoken,
                        bar=bar,
                        bars=hist,
                    )
                except Exception:
                    pass
            rows.append(
                (
                    pid,
                    sid,
                    name,
                    day,
                    hm,
                    _snip(spoken, name),
                    str((bar or {}).get("date") or ""),
                    (bar or {}).get("open"),
                    (bar or {}).get("high"),
                    (bar or {}).get("low"),
                    (bar or {}).get("close"),
                    (bar or {}).get("volume"),
                    (bar or {}).get("pct_change"),
                    note,
                    charts,
                    "daily_quotes" if bar and sid != "TWII" else ("index_daily" if bar else ""),
                )
            )
    if not rows:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO biaoke_tape
            (post_id, stock_id, stock_name, post_date, post_time, snippet,
             bar_date, open, high, low, close, volume, pct_change, note, charts, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


_CLOSE_MIN = 13 * 60 + 30
_CORE_SIDS = (
    "2383",
    "2368",
    "4971",
    "3653",
    "3017",
    "1815",
    "2408",
    "3105",
    "3081",
    "2330",
    "2308",
    "3443",
)


def refresh_published_official(
    db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """收盤後證交所已公布＝寫今天官方柱並重對 tape。盤中／未公布不寫。不等 16:30 全表。"""
    stats: Dict[str, Any] = {"ok": False}
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return {**stats, "skipped": "no_db"}
    try:
        from config import taipei_now
        from trading_calendar import is_tw_open_calendar_day
    except Exception:
        return {**stats, "skipped": "cal"}
    dt = now or taipei_now()
    if dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    ymd = dt.strftime("%Y%m%d")
    iso = dt.strftime("%Y-%m-%d")
    if not is_tw_open_calendar_day(ymd):
        return {**stats, "skipped": "holiday"}
    if dt.hour * 60 + dt.minute < _CLOSE_MIN:
        return {**stats, "skipped": "session"}
    last = last_official_bar(path, "TWII")
    last_d = _ymd((last or {}).get("date"))
    if last_d >= ymd:
        return {**stats, "ok": True, "skipped": "have_today", "date": ymd}
    try:
        from taiwan_market import _fetch_twse_index_close

        off = _fetch_twse_index_close(ymd)
    except Exception:
        return {**stats, "skipped": "mi_index_err"}
    if not off or float(off.get("close") or 0) <= 0:
        return {**stats, "skipped": "not_published"}
    try:
        from taiwan_market import sync_index_daily

        stats["index"] = sync_index_daily(path, range_="5d")
    except Exception:
        stats["index_err"] = True
    want = set(_CORE_SIDS)
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        rows = conn.execute(
            "SELECT tags, text FROM biaoke_posts WHERE date>=? AND date<=?",
            (iso, iso),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for tags, text in rows:
        try:
            tag_l = json.loads(tags) if tags else []
        except Exception:
            tag_l = []
        for sid, _n in named_pairs(str(text or ""), tag_l):
            if sid != "TWII":
                want.add(sid)
    try:
        from data_fetcher import DataFetcher

        n = DataFetcher(db_path=path)._upsert_named_quotes(ymd, want)
        stats["quotes"] = int(n or 0)
    except Exception:
        stats["quotes_err"] = True
    events = []
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        for pid, day, hm, kind, tags, text in conn.execute(
            "SELECT id, date, time, kind, tags, text FROM biaoke_posts WHERE date=?",
            (iso,),
        ):
            try:
                tag_l = json.loads(tags) if tags else []
            except Exception:
                tag_l = []
            events.append(
                {
                    "id": pid,
                    "date": day,
                    "time": hm,
                    "kind": kind,
                    "tags": tag_l,
                    "text": text,
                }
            )
    except sqlite3.Error:
        events = []
    finally:
        conn.close()
    if events:
        stats["tape"] = record_events(path, events)
    stats.update({"ok": True, "date": ymd, "close": off.get("close")})
    return stats


def glance_for(db_path: str, sid: str, *, n: int = 2) -> str:
    """第④顆讀最近建檔：他剛點這檔時官方高低量。"""
    if not db_path or not os.path.isfile(db_path) or not sid:
        return ""
    ensure_biaoke_tape_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT post_date, post_time, stock_name, note
            FROM biaoke_tape WHERE stock_id=?
            ORDER BY post_date DESC, post_time DESC LIMIT ?
            """,
            (sid, max(1, int(n))),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    bits: List[str] = []
    for day, hm, name, note in rows:
        stamp = " ".join(x for x in (str(day or ""), str(hm or "")) if x)
        bits.append(f"{stamp} {name} {note}".strip())
    if not bits:
        return ""
    return "即時建檔：" + "；".join(bits)
