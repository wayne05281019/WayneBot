# -*- coding: utf-8 -*-
"""他一說大盤現況位階 → 立刻畫圖落檔 → 靜默準備下一句對質。

成長迴路（不是買訊、不進話筒）：
1. 抓文事件若像「現況浪級／細微／C 段／主跌／橫台位階」→ 渲加權位階圖
2. 寫入 biaoke_level_snaps（post_id／snippet／圖路徑／pending）
3. 下一則位階文或盤後 → 對前一筆 pending（對／偏／還沒走完）

開市／夜盤活畫（稀疏槽，不准每分鐘）：
- 讀庫：加權日K、台指日／夜、TX60、納指／費半、近窗他說錨、量價結構
- 先用他的方法寫關鍵位＋轉折＋裸K／量價題旨並畫圖
- 他說時對敘事；隔日官方柱對關鍵位 → 對／偏／還沒 → 覆盤修正
不准發明 5／9；不准改黃金買點；失敗不擋抓文。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.biaoke_level_learn")
TAIPEI = ZoneInfo("Asia/Taipei")

# 現況位階／細微波說話（他講大盤走法時；含預估重修／動態修正）
_LEVEL_NOW = re.compile(
    r"("
    r"波浪位階|細微波|主跌段|初跌段|末跌段|"
    r"C\s*波|C\d|C3-\d|B\s*波|B-[abc]|"
    r"橫台|中繼站|第[一二三四五1-5]波|第[1-5]小浪|"
    r"1-4\s*重疊|鐵律|破底翻|第二隻腳|第二支腳|"
    r"動態修正|重新修訂|重新規劃|穿刺原規劃|"
    r"目前只是|目前是走|現在是走|確認.*發動|準備啟動"
    r")",
    re.I,
)
# 他改口／重修位階的用語（預估不是鎖死；被誤導／鐵律不符就重訂）
_REVISE_MARK = re.compile(
    r"("
    r"動態修正|重新修訂|重新規劃|重新畫|穿刺原規劃|"
    r"改口|被.?誤導|很容易看錯|不要做太遠|"
    r"完成某一段之後|再進行重新修訂|隨時.*檢視|檢視.*位階"
    r")",
    re.I,
)
_INDEXISH = re.compile(r"(大盤|加權|台指|台指期|夜盤|TWII)")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_level_snaps (
    post_id TEXT NOT NULL PRIMARY KEY,
    as_of TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    chart_path TEXT NOT NULL DEFAULT '',
    pending INTEGER NOT NULL DEFAULT 1,
    verdict TEXT NOT NULL DEFAULT '',
    next_post_id TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_biaoke_level_snaps_pending
    ON biaoke_level_snaps(pending, as_of);
"""

_OPEN_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_open_day_paints (
    slot_id TEXT NOT NULL PRIMARY KEY,
    as_of TEXT NOT NULL DEFAULT '',
    thesis TEXT NOT NULL DEFAULT '',
    wait_struct TEXT NOT NULL DEFAULT '',
    turn_note TEXT NOT NULL DEFAULT '',
    vol_note TEXT NOT NULL DEFAULT '',
    key_levels TEXT NOT NULL DEFAULT '',
    chart_path TEXT NOT NULL DEFAULT '',
    tx60_path TEXT NOT NULL DEFAULT '',
    us_note TEXT NOT NULL DEFAULT '',
    pending INTEGER NOT NULL DEFAULT 1,
    verdict TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_biaoke_open_day_pending
    ON biaoke_open_day_paints(pending, as_of);
"""

# 稀疏槽：偶爾看一下就好（名→(起分, 迄分) 台北分鐘；先比對先命中）
_SPARSE_SLOTS: Tuple[Tuple[str, int, int], ...] = (
    ("dawn", 4 * 60, 5 * 60),
    ("pre", 7 * 60 + 50, 8 * 60 + 40),
    ("mid", 11 * 60, 11 * 60 + 50),
    ("close", 13 * 60 + 15, 13 * 60 + 45),
    ("after", 16 * 60 + 30, 20 * 60 + 50),  # 盤後～夜盤前
    ("night", 21 * 60, 22 * 60 + 30),  # 夜盤中段一眼
)


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _px(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x <= 0:
        return "—"
    return f"{x:,.0f}"


def ensure_tables(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.executescript(_OPEN_DDL)
        # 舊表補欄（已有表 CREATE IF NOT EXISTS 不會加欄）
        cols = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(biaoke_open_day_paints)").fetchall()
        }
        for col, decl in (
            ("turn_note", "TEXT NOT NULL DEFAULT ''"),
            ("vol_note", "TEXT NOT NULL DEFAULT ''"),
            ("key_levels", "TEXT NOT NULL DEFAULT ''"),
            ("tx60_path", "TEXT NOT NULL DEFAULT ''"),
            ("us_note", "TEXT NOT NULL DEFAULT ''"),
            ("far_path", "TEXT NOT NULL DEFAULT ''"),
            ("near_path", "TEXT NOT NULL DEFAULT ''"),
            ("us_path", "TEXT NOT NULL DEFAULT ''"),
            ("micro_path", "TEXT NOT NULL DEFAULT ''"),
            ("mine_path", "TEXT NOT NULL DEFAULT ''"),
            ("pending", "INTEGER NOT NULL DEFAULT 1"),
            ("verdict", "TEXT NOT NULL DEFAULT ''"),
            ("checked_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE biaoke_open_day_paints ADD COLUMN {col} {decl}"
                )
        conn.commit()
    finally:
        conn.close()


def looks_like_level_now(text: str) -> bool:
    blob = str(text or "")
    if not blob.strip():
        return False
    if not _LEVEL_NOW.search(blob):
        return False
    # 大盤戰場；純個股位階不進這條（個股不發明浪）
    if _INDEXISH.search(blob):
        return True
    # 他有時只寫 C3-3／細微波不帶「大盤」二字，但同串在講台指
    # 動態修正／重新修訂／穿刺原規劃＝他在檢視浪級（預估會改）
    if re.search(
        r"C3-\d|細微波|波浪位階|主跌段|橫台整理|動態修正|重新修訂|穿刺原規劃|重新規劃",
        blob,
    ):
        return True
    return False


def _snap_dir(db_path: str) -> str:
    root = os.path.dirname(os.path.abspath(db_path)) or "."
    path = os.path.join(root, "biaoke_level_snaps")
    os.makedirs(path, exist_ok=True)
    return path


def _paint_dir(db_path: str) -> str:
    root = os.path.dirname(os.path.abspath(db_path)) or "."
    path = os.path.join(root, "biaoke_open_day_paints")
    os.makedirs(path, exist_ok=True)
    return path


def _render_snap(db_path: str, post_id: str, as_of: str) -> str:
    """渲加權位階圖；失敗回空，不准擋抓文。"""
    safe = re.sub(r"[^\w.\-]+", "_", str(post_id or "x"))[:80]
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    out = os.path.join(_snap_dir(db_path), f"{day}_{safe}.png")
    try:
        from biaoke_wave import render_twii_degree_png

        path = render_twii_degree_png(db_path, out)
        if path and os.path.isfile(path) and os.path.getsize(path) > 5000:
            return path
    except Exception:
        logger.exception("位階學習圖渲失敗 post=%s", post_id)
    return ""


def _upsert_snap(
    db_path: str,
    *,
    post_id: str,
    as_of: str,
    post_date: str,
    post_time: str,
    snippet: str,
    chart_path: str,
) -> None:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_level_snaps(
                post_id, as_of, post_date, post_time, snippet, chart_path,
                pending, created_at
            ) VALUES (?,?,?,?,?,?,1,?)
            ON CONFLICT(post_id) DO UPDATE SET
                as_of=excluded.as_of,
                post_date=excluded.post_date,
                post_time=excluded.post_time,
                snippet=excluded.snippet,
                chart_path=CASE WHEN excluded.chart_path!='' THEN excluded.chart_path
                    ELSE biaoke_level_snaps.chart_path END,
                pending=1,
                verdict='',
                next_post_id='',
                checked_at=''
            """,
            (
                post_id,
                as_of,
                post_date,
                post_time,
                snippet,
                chart_path or "",
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _pending_rows(db_path: str) -> List[Dict[str, Any]]:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM biaoke_level_snaps WHERE pending=1 "
            "ORDER BY as_of ASC, post_date ASC, post_time ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _mark_verdict(
    db_path: str, post_id: str, verdict: str, next_post_id: str = ""
) -> None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "UPDATE biaoke_level_snaps SET pending=0, verdict=?, next_post_id=?, "
            "checked_at=? WHERE post_id=?",
            (verdict, next_post_id or "", _now(), post_id),
        )
        conn.commit()
    finally:
        conn.close()


def _score_against_next(prev_snip: str, next_snip: str) -> str:
    """粗對質：下一句是否延續／改口／打臉。不是買訊。

    他訂的波浪多是預估；不符鐵律／穿刺原規劃／被誤導→會重修位階。
    """
    a = (prev_snip or "").lower()
    b = (next_snip or "").lower()
    if not a or not b:
        return "還沒走完"
    # 改口／重標／被誤導後檢視（預估位階被推翻＝偏）
    if _REVISE_MARK.search(next_snip or "") or _REVISE_MARK.search(b):
        return "偏"
    if any(k in b for k in ("重新修訂", "動態修正", "穿刺原規劃", "改口", "誤導", "看錯")):
        return "偏"
    # 同向延續
    for k in ("c3-3", "主跌", "橫台", "中繼", "b波", "細微波"):
        if k in a.replace(" ", "") and k in b.replace(" ", ""):
            return "對"
    if ("必破" in a or "會破" in a) and ("已破" in b or "破了" in b or "驗證" in b):
        return "對"
    if ("止跌" in a or "第二隻腳" in a or "第二支腳" in a) and (
        "主跌" in b or "c3-3" in b.replace(" ", "")
    ):
        return "偏"  # 樂觀止跌後接主跌＝打臉／偏
    return "還沒走完"


def verify_pending_with_event(
    db_path: str, next_post_id: str, next_snippet: str
) -> int:
    """新位階文進來：對先前 pending 粗評一輪。"""
    n = 0
    for row in _pending_rows(db_path):
        pid = str(row.get("post_id") or "")
        if not pid or pid == next_post_id:
            continue
        verdict = _score_against_next(str(row.get("snippet") or ""), next_snippet)
        if verdict == "還沒走完":
            continue
        _mark_verdict(db_path, pid, verdict, next_post_id=next_post_id)
        n += 1
    return n


def record_level_learn_from_events(
    db_path: str, events: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """ingest 鉤子：現況位階 → 畫圖＋對前一筆。失敗回空統計。"""
    stats = {"seen": 0, "snaps": 0, "verified": 0, "live_verified": 0}
    if not db_path or not events:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_LEVEL_LEARN_LIVE") != "1":
        return {**stats, "skipped": "pytest"}
    ensure_tables(db_path)
    for ev in events:
        text = str(ev.get("text") or "")
        if not looks_like_level_now(text):
            continue
        stats["seen"] += 1
        post_id = str(ev.get("id") or "").strip()
        if not post_id:
            continue
        post_date = str(ev.get("date") or "").strip()
        post_time = str(ev.get("time") or "").strip()
        as_of = _ymd(post_date) or datetime.now(TAIPEI).strftime("%Y%m%d")
        snippet = re.sub(r"\s+", " ", text).strip()[:400]
        # 先用新文對舊 pending
        try:
            stats["verified"] += int(
                verify_pending_with_event(db_path, post_id, snippet) or 0
            )
        except Exception:
            logger.exception("位階學習對前筆失敗")
        try:
            stats["live_verified"] += int(
                verify_live_hyps_with_speech(db_path, snippet) or 0
            )
        except Exception:
            logger.exception("活畫敘事對質略過")
        # 再畫本則
        chart = ""
        try:
            chart = _render_snap(db_path, post_id, as_of)
        except Exception:
            logger.exception("位階學習渲圖略過")
        try:
            _upsert_snap(
                db_path,
                post_id=post_id,
                as_of=as_of,
                post_date=post_date,
                post_time=post_time,
                snippet=snippet,
                chart_path=chart,
            )
            if chart:
                stats["snaps"] += 1
        except Exception:
            logger.exception("位階學習落檔失敗")
    return stats


# ─── 開市／夜盤活畫 ───────────────────────────────────────────


def _morph_note_from_text(blob: str) -> str:
    """型態課：只抽他用過的形態學語，不准抄成買訊。"""
    t = str(blob or "")
    if not t:
        return ""
    bits: List[str] = []
    if "上升楔形" in t or ("楔形" in t and "上升" in t):
        bits.append("上升楔形（漲幅縮→下殺更快・觀察）")
    if "盤頭" in t or ("末端" in t and ("型態" in t or "形態" in t)):
        bits.append("漲幅縮短／重疊→盤頭或B反彈末端觀察")
    if "頸線" in t:
        bits.append("頸線（外圍／個股他點過才標）")
    if "頭肩" in t:
        bits.append("頭肩（費半先行常見）")
    if ("橫台" in t or "中繼" in t) and "楔形" not in "".join(bits):
        bits.append("橫台中繼")
    if "頭部型態" in t or "頭部形態" in t:
        bits.append("頭部型態＋組合K（轉弱佐證・非買訊）")
    return "；".join(bits[:3])


def _twii_chart_as_of(db_path: str) -> str:
    """活畫／教具 as_of＝加權指數最新已收官方柱（盤中未收不准當收）。

    教具必須畫到最新交易日縮圖K，不准被 daily_quotes 完整日卡在前一日。
    """
    try:
        from biaoke_wave import _load_twii_bars

        bars = _load_twii_bars(db_path, n=8, teach=True)
    except Exception:
        bars = []
    if bars:
        return _ymd(bars[-1].get("date"))
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def _merge_live_index_display_bar(
    bars: Sequence[Dict[str, Any]],
    live: Optional[Dict[str, Any]],
    *,
    today: str,
) -> List[Dict[str, Any]]:
    """把即時 OHLC 疊成當日未收柱（只渲染、不寫庫、不當官方收）。"""
    out = [dict(r) for r in (bars or [])]
    if not live or not out:
        return out
    day = _ymd(today) or str(today or "").replace("-", "")[:8]
    if len(day) != 8:
        return out
    try:
        px = float(live.get("price") or live.get("close") or 0)
        o = float(live.get("open") or px or 0)
        h = float(live.get("high") or max(o, px) or 0)
        lo = float(live.get("low") or min(o, px) or 0)
        vol = float(
            live.get("volume")
            or live.get("vol")
            or live.get("volume_proxy")
            or 0
        )
    except (TypeError, ValueError):
        return out
    if px <= 0:
        return out
    last = out[-1]
    last_d = _ymd(last.get("date"))
    if last_d == day:
        try:
            h = max(h, float(last.get("high") or 0), px)
            lo = min(
                lo if lo > 0 else px,
                float(last.get("low") or px) or px,
                px,
            )
            o = float(last.get("open") or o or px)
            # 盤中累積量以即時為準；即時缺才留庫內
            last_vol = float(last.get("volume") or 0)
            if vol > 0:
                vol = max(vol, last_vol)
            else:
                vol = last_vol
        except (TypeError, ValueError):
            pass
        out[-1] = {
            **last,
            "open": o,
            "high": h,
            "low": lo,
            "close": px,
            "volume": vol,
            "live_session": 1,
        }
        return out
    if last_d and last_d > day:
        return out
    out.append(
        {
            "date": day,
            "open": o,
            "high": h,
            "low": lo if lo > 0 else px,
            "close": px,
            "volume": vol,
            "live_session": 1,
        }
    )
    return out


def _merge_live_twii_display_bar(
    bars: Sequence[Dict[str, Any]], live: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """盤中顯示用：把 MIS 加權疊成當日未收柱（只渲染、不寫庫、不當官方收）。

    末K OHLC＋成交量都疊；量認 MIS（加權用 m），不准留 0 假柱。
    """
    if not live:
        return [dict(r) for r in (bars or [])]
    try:
        from live_quote import is_live_merge_window
    except Exception:
        return [dict(r) for r in (bars or [])]
    try:
        if not is_live_merge_window():
            return [dict(r) for r in (bars or [])]
    except Exception:
        return [dict(r) for r in (bars or [])]
    today = _ymd(live.get("date")) if isinstance(live, dict) else ""
    if len(today or "") != 8:
        today = datetime.now(TAIPEI).strftime("%Y%m%d")
    return _merge_live_index_display_bar(bars, live, today=today)


def _merge_live_sox_display_bar(
    bars: Sequence[Dict[str, Any]], live: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """美股現金盤中：Yahoo 費半當日未收柱疊顯示（不寫庫）。"""
    if not live:
        return [dict(r) for r in (bars or [])]
    day = _ymd(live.get("date")) or ""
    if len(day) != 8:
        return [dict(r) for r in (bars or [])]
    return _merge_live_index_display_bar(bars, live, today=day)


def _twii_bars_for_teach(
    db_path: str, n: int, pack: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """教具用加權柱：指數最新已收官方柱＋（盤中）MIS 顯示疊加。

    遠／近／超近三張都必須畫到最新交易日縮圖K；盤中查／飆大新文要立刻對得上。
    """
    from biaoke_wave import _load_twii_bars

    bars = list(_load_twii_bars(db_path, n=n, teach=True) or [])
    live = (pack or {}).get("live_twii") if isinstance(pack, dict) else None
    if live:
        bars = _merge_live_twii_display_bar(bars, live)
    return bars


def _ensure_teach_index_bars(db_path: str) -> None:
    """活畫前補齊加權／費半最新官方日K（失敗不擋出圖）。"""
    if not db_path:
        return
    try:
        from taiwan_market import sync_index_daily

        sync_index_daily(db_path, range_="3mo")
    except Exception:
        logger.exception("教具補加權日K略過")
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("教具補費半日K略過")


def _finish_last_twii_candle(
    ax,
    *,
    i_now: int,
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    candle_up,
    ymin: float,
    ymax: float,
) -> None:
    """近／超近／遠窗共用：右標後蓋回末日縮圖K＋空心 tip，不准被紫點吃掉。"""
    if ax is None or i_now < 0 or i_now >= len(closes):
        return
    span = max(float(ymax) - float(ymin), 1.0)
    min_body = max(
        _candle_span_min_body(highs, lows, frac=_LIVE_CANDLE_MIN_BODY_FRAC),
        span * 0.02,
    )
    prev_c = float(closes[i_now - 1]) if i_now > 0 else None
    _paint_one_live_candle(
        ax,
        int(i_now),
        open_=float(opens[i_now]),
        high=float(highs[i_now]),
        low=float(lows[i_now]),
        close=float(closes[i_now]),
        prev_c=prev_c,
        candle_up=candle_up,
        min_body=float(min_body),
        width=0.72,
        wick_lw=1.55,
        z_wick=14,
        z_body=15,
        edgecolor="#ffffff",
        edge_lw=0.9,
    )
    ax.scatter(
        [float(i_now)],
        [float(closes[i_now])],
        s=42,
        facecolors="none",
        edgecolors="#ea80fc",
        linewidths=1.15,
        zorder=16,
        clip_on=False,
    )


def _bar_clock_tag(bars: Sequence[Dict[str, Any]]) -> str:
    """末日若為盤中疊加 →『盤中』；否則『收盤』（不准把未收當收）。

    教具標題請用 `_teach_query_clock`（含查詢當下 HH:MM）；本函式留相容。
    """
    if bars and int((bars[-1] or {}).get("live_session") or 0) == 1:
        return "盤中"
    return "收盤"


def _parse_query_at(raw: Any) -> Optional[datetime]:
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI)


def _teach_session_phase_word(dt: datetime) -> str:
    """查詢戳時段字：盤前／市撮（試搓）／盤中／收盤。只認台北牆鐘＋開市日。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    try:
        from trading_calendar import is_tw_open_calendar_day

        open_day = bool(is_tw_open_calendar_day(dt.strftime("%Y%m%d")))
    except Exception:
        open_day = dt.weekday() < 5
    if not open_day:
        return "收盤"
    hm = int(dt.hour) * 60 + int(dt.minute)
    # 試搓＝市撮：08:30 ≤ t < 09:00；更早＝盤前；09:00–13:30＝盤中；其後＝收盤
    if hm < 8 * 60 + 30:
        return "盤前"
    if hm < 9 * 60:
        return "市撮"
    if hm < 13 * 60 + 30:
        return "盤中"
    return "收盤"


def _teach_query_clock(
    bars: Sequence[Dict[str, Any]],
    *,
    pack: Optional[Dict[str, Any]] = None,
    generated_at: Optional[datetime] = None,
) -> str:
    """遠／近／超近時鐘：時段字＋查詢當下 HH:MM（三張同 pack['query_at']）。

    盤前／市撮／盤中／收盤；不准把未收當收盤，也不准標題沒鐘點。
    """
    del bars  # 時段跟牆鐘；末柱 live_session 不覆寫市撮／盤前
    dt = None
    if isinstance(pack, dict):
        dt = _parse_query_at(pack.get("query_at"))
    if dt is None:
        dt = generated_at or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    hm = dt.strftime("%H:%M")
    return f"{_teach_session_phase_word(dt)} {hm}"


# 教具查詢戳：黃框白底；日期／時段黑字；價／漲跌台股紅漲綠跌
_TEACH_STAMP_EDGE = "#ffff00"
_TEACH_STAMP_FACE = "#ffffff"
_TEACH_STAMP_META = "#111111"
_TEACH_STAMP_TEXT = "#111111"  # 相容舊讀；實畫走分段色
# 八浪縮圖鎖超近窗實測大小（fig 15.6×9.6 → fraction；相容舊 inset）
# 遠／近／超近構圖統一：中排左＝對位說明、右＝八浪小圖吃滿格；不准壓 K
_TEACH_EIGHT_WAVE_INSET_REF_FIG = (15.6, 9.6)
_TEACH_EIGHT_WAVE_INSET_W_FRAC = 0.248
_TEACH_EIGHT_WAVE_INSET_H_FRAC = 0.220
# 教具頁邊鎖死（遠／近／超近同一套），畫面不因內容晃
_TEACH_FIG_LEFT = 0.05
_TEACH_FIG_RIGHT = 0.98
_TEACH_FIG_TOP = 0.88
_TEACH_HSPACE = 0.055
_TEACH_MID_WSPACE = 0.035


def _day_change_vs_prev(
    close: Optional[float], prev_close: Optional[float]
) -> Dict[str, Any]:
    """相對前一個交易日收：漲跌點數與％（不是前天）。

    顯示序：漲幅％ → 差異點數（價在呼叫端先寫）。
    """
    out: Dict[str, Any] = {
        "pts": None,
        "pct": None,
        "pct_text": "",
        "pts_text": "",
        "text": "",
        "sign": 0,
    }
    try:
        c = float(close) if close is not None else None
        p = float(prev_close) if prev_close is not None else None
    except (TypeError, ValueError):
        return out
    if c is None or p is None or p <= 0:
        return out
    pts = c - p
    pct = pts / p * 100.0
    out["pts"] = pts
    out["pct"] = pct
    out["sign"] = 1 if pts > 0 else (-1 if pts < 0 else 0)
    out["pct_text"] = f"（{pct:+.2f}%）"
    out["pts_text"] = f"{pts:+,.0f}"
    # 價｜漲幅｜點數
    out["text"] = f"{out['pct_text']} {out['pts_text']}"
    return out


def _chg_paint_color(sign: int) -> str:
    """台股慣例：漲紅跌綠；平盤黑。"""
    if int(sign or 0) > 0:
        return _LIVE_UP
    if int(sign or 0) < 0:
        return _LIVE_DOWN
    return _TEACH_STAMP_META


def _prev_bar_close(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    """前一個交易日收（bars 倒數第二根有收才算）。"""
    if not bars or len(bars) < 2:
        return None
    try:
        v = float(bars[-2].get("close") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# 加權／費半黃框同一字級與框高；費半字少→寬自然較短（回到 bold）
_TEACH_STAMP_FS = 17
_TEACH_STAMP_FS_LONG = 15
_TEACH_STAMP_BOX_PAD = 0.40
_TEACH_STAMP_BOX_LW = 2.6


def _teach_stamp_fsz(*parts: str) -> int:
    line = "".join(str(p or "") for p in parts)
    return _TEACH_STAMP_FS_LONG if len(line) > 36 else _TEACH_STAMP_FS


def _teach_stamp_line(
    bars: Sequence[Dict[str, Any]],
    *,
    pack: Optional[Dict[str, Any]] = None,
    close: Optional[float] = None,
) -> str:
    """查詢戳一行（純文字）：日期＋時段鐘＋價＋漲幅％＋點數。"""
    as_of = _ymd(bars[-1].get("date")) if bars else ""
    day = (
        f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}"
        if len(as_of) == 8
        else (as_of or "—")
    )
    clock = _teach_query_clock(bars, pack=pack)
    px_v = close
    if px_v is None and bars:
        try:
            px_v = float(bars[-1].get("close") or 0)
        except (TypeError, ValueError):
            px_v = 0.0
    try:
        px_s = _px(float(px_v or 0))
    except (TypeError, ValueError):
        px_s = "—"
    chg = _day_change_vs_prev(px_v, _prev_bar_close(bars))
    chg_s = str(chg.get("text") or "").strip()
    if chg_s:
        return f"{day}  {clock}  {px_s}  {chg_s}"
    return f"{day}  {clock}  {px_s}"


def _stamp_box_alignment(ha: str) -> Tuple[float, float]:
    ha_s = str(ha or "right")
    if ha_s == "left":
        return (0.0, 1.0)
    if ha_s == "center":
        return (0.5, 1.0)
    return (1.0, 1.0)


def _fig_xy_from_axes_data(ax: Any, fig: Any, x_data: float, y_data: float) -> Tuple[float, float]:
    """把軸上 data 座標轉成 figure fraction（給黃戳／縮圖對齊虛線位）。"""
    try:
        disp = ax.transData.transform((float(x_data), float(y_data)))
        fx, fy = fig.transFigure.inverted().transform(disp)
        return float(fx), float(fy)
    except Exception:
        return 0.5, 0.5


def _teach_eight_wave_inset_wh(fig: Any) -> Tuple[float, float]:
    """超近窗八浪縮圖同吋寬高 → 此 fig 的 fraction（遠／近／超近一模一樣大小）。"""
    rw, rh = _TEACH_EIGHT_WAVE_INSET_REF_FIG
    try:
        fw, fh = fig.get_size_inches()
    except Exception:
        fw, fh = rw, rh
    w_in = float(_TEACH_EIGHT_WAVE_INSET_W_FRAC) * float(rw)
    h_in = float(_TEACH_EIGHT_WAVE_INSET_H_FRAC) * float(rh)
    return (
        max(0.10, w_in / max(float(fw), 0.1)),
        max(0.08, h_in / max(float(fh), 0.1)),
    )


def _eight_wave_inset_rect_in_host(
    ax_host: Any,
    fig: Any,
) -> Tuple[float, float, float, float]:
    """舊：figure fraction 置中小卡（保留相容）。新畫走 `_eight_wave_card_ax_in_host`。"""
    w, h = _teach_eight_wave_inset_wh(fig)
    try:
        pos = ax_host.get_position()
    except Exception:
        return (0.35, 0.28, float(w), float(h))
    pad = 0.012
    max_w = max(0.10, float(pos.width) - 2 * pad)
    max_h = max(0.06, float(pos.height) - 2 * pad)
    scale = min(1.0, max_w / max(float(w), 1e-6), max_h / max(float(h), 1e-6))
    w2 = float(w) * float(scale)
    h2 = float(h) * float(scale)
    left = float(pos.x0) + (float(pos.width) - w2) * 0.5
    bottom = float(pos.y0) + (float(pos.height) - h2) * 0.5
    return (float(left), float(bottom), float(w2), float(h2))


def _eight_wave_card_ax_in_host(ax_host: Any, fig: Any) -> Any:
    """獨立列內置中八浪小卡（inset 掛在 host 上）。

    host 當安靜間隔帶、不准 hide：tight 存檔才留得住列，框也不會蓋回 K。
    小卡鎖超近同吋；列矮時等比縮，不准整列撐滿。
    """
    w_fig, h_fig = _teach_eight_wave_inset_wh(fig)
    try:
        pos = ax_host.get_position()
        hw = max(float(pos.width), 1e-6)
        hh = max(float(pos.height), 1e-6)
    except Exception:
        return ax_host.inset_axes([0.32, 0.08, 0.36, 0.84])
    # figure fraction → host axes fraction；維持小卡長寬比
    aspect = float(w_fig) / max(float(h_fig), 1e-6)
    host_aspect = hw / hh
    h_ax = min(0.90, float(h_fig) / hh)
    w_ax = h_ax * (aspect / host_aspect)
    if w_ax > 0.90:
        w_ax = 0.90
        h_ax = w_ax * (host_aspect / aspect)
    left = (1.0 - w_ax) * 0.5
    bottom = (1.0 - h_ax) * 0.5
    return ax_host.inset_axes([float(left), float(bottom), float(w_ax), float(h_ax)])


def _eight_wave_inset_rect_left_of_vmax(
    ax: Any,
    fig: Any,
    *,
    i_vmax: Optional[int],
    ymin: float,
    ymax: float,
    n_bars: int,
    gap_fig: float = 0.008,
) -> Tuple[float, float, float, float]:
    """舊位：K 軸內黃虛線左（已停用遠／近；保留給測試／相容）。

    新規則請用 `_eight_wave_inset_rect_in_host`：獨立列，不准壓縮圖 K。
    """
    w, h = _teach_eight_wave_inset_wh(fig)
    ys = max(float(ymax) - float(ymin), 1.0)
    y_bot = float(ymin) + ys * 0.055
    iv = int(i_vmax) if i_vmax is not None else max(0, int(n_bars) - 8)
    fx_v, fy_bot = _fig_xy_from_axes_data(ax, fig, float(iv), y_bot)
    left = float(fx_v) - float(gap_fig) - float(w)
    bottom = float(fy_bot)
    try:
        pos = ax.get_position()
        min_left = float(pos.x0) + 0.012
        max_bottom = float(pos.y0) + float(pos.height) * 0.42 - float(h)
        min_bottom = float(pos.y0) + 0.010
    except Exception:
        min_left, max_bottom, min_bottom = 0.04, 0.52, 0.08
    if left < min_left:
        left = min_left
    if bottom > max_bottom:
        bottom = max(min_bottom, max_bottom)
    if bottom < min_bottom:
        bottom = min_bottom
    if left + w > float(fx_v) - float(gap_fig):
        left = max(min_left, float(fx_v) - float(gap_fig) - float(w))
    return (float(left), float(bottom), float(w), float(h))


def _fig_rect_band_right(
    ax: Any,
    fig: Any,
    *,
    y_top: float,
    y_bot: float,
    x_left_frac: float = 0.78,
    width: float = 0.17,
    pad: float = 0.012,
) -> Tuple[float, float, float, float]:
    """右欄兩條橫虛線之間的縮圖框（figure fraction）。"""
    _xl, fy_top = _fig_xy_from_axes_data(ax, fig, 0.0, float(y_top))
    _xl2, fy_bot = _fig_xy_from_axes_data(ax, fig, 0.0, float(y_bot))
    if fy_top < fy_bot:
        fy_top, fy_bot = fy_bot, fy_top
    bottom = fy_bot + float(pad)
    height = max(0.08, (fy_top - fy_bot) - 2.0 * float(pad))
    return (float(x_left_frac), float(bottom), float(width), float(height))


def _fig_rect_from_data_box(
    ax: Any,
    fig: Any,
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    min_w: float = 0.12,
    min_h: float = 0.10,
) -> Tuple[float, float, float, float]:
    """把軸上 data 矩形轉成 figure fraction 縮圖框（給紅框空檔定位）。"""
    fx0, fy0 = _fig_xy_from_axes_data(ax, fig, float(x0), float(y0))
    fx1, fy1 = _fig_xy_from_axes_data(ax, fig, float(x1), float(y1))
    left = min(fx0, fx1)
    bottom = min(fy0, fy1)
    width = max(float(min_w), abs(fx1 - fx0))
    height = max(float(min_h), abs(fy1 - fy0))
    # 不准超出 figure
    if left + width > 0.98:
        width = max(float(min_w), 0.98 - left)
    if bottom + height > 0.92:
        height = max(float(min_h), 0.92 - bottom)
    return (float(left), float(bottom), float(width), float(height))


def _paint_stamp_hbox(
    fig,
    kids: List[Any],
    *,
    x: float,
    y: float,
    ha: str = "right",
    zorder: float = 40,
) -> None:
    """黃邊白底圓角框（加權／費半共用框高與線寬）。"""
    from matplotlib.offsetbox import AnnotationBbox, HPacker

    if fig is None or not kids:
        return
    ab = AnnotationBbox(
        HPacker(children=kids, align="center", pad=0, sep=0),
        (float(x), float(y)),
        xycoords="figure fraction",
        box_alignment=_stamp_box_alignment(ha),
        pad=0.32,
        frameon=True,
        bboxprops=dict(
            boxstyle=f"round,pad={_TEACH_STAMP_BOX_PAD}",
            facecolor=_TEACH_STAMP_FACE,
            edgecolor=_TEACH_STAMP_EDGE,
            linewidth=_TEACH_STAMP_BOX_LW,
        ),
        zorder=float(zorder),
    )
    fig.add_artist(ab)


def _paint_teach_query_stamp(
    fig,
    bars: Sequence[Dict[str, Any]],
    *,
    pack: Optional[Dict[str, Any]] = None,
    close: Optional[float] = None,
    fp=None,
    x: float = 0.995,
    y: float = 0.958,
    ha: str = "right",
) -> None:
    """三張教具共用：黃框白底；日期／時段黑；價→漲幅％→點數（紅漲綠跌）。

    預設貼右、略離上緣，不准壓標題白字；近／超近可再調 y 適中。
    """
    if fig is None or not bars:
        return
    if fp is None:
        try:
            from wayne_navigator import _fp as fp
        except Exception:
            return
    from matplotlib.offsetbox import TextArea

    as_of = _ymd(bars[-1].get("date")) if bars else ""
    day = (
        f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}"
        if len(as_of) == 8
        else (as_of or "—")
    )
    clock = _teach_query_clock(bars, pack=pack)
    px_v = close
    if px_v is None:
        try:
            px_v = float(bars[-1].get("close") or 0)
        except (TypeError, ValueError):
            px_v = 0.0
    try:
        px_s = _px(float(px_v or 0))
    except (TypeError, ValueError):
        px_s = "—"
    chg = _day_change_vs_prev(px_v, _prev_bar_close(bars))
    pct_s = str(chg.get("pct_text") or "").strip()
    pts_s = str(chg.get("pts_text") or "").strip()
    chg_col = _chg_paint_color(int(chg.get("sign") or 0))
    fsz = _teach_stamp_fsz(day, clock, px_s, pct_s, pts_s)
    kids = [
        TextArea(
            f"{day}  {clock}  ",
            textprops={
                "color": _TEACH_STAMP_META,
                "fontproperties": fp(fsz, "bold"),
            },
        ),
        TextArea(
            px_s,
            textprops={
                "color": chg_col,
                "fontproperties": fp(fsz, "bold"),
            },
        ),
    ]
    if pct_s:
        kids.append(
            TextArea(
                f"  {pct_s}",
                textprops={
                    "color": chg_col,
                    "fontproperties": fp(fsz, "bold"),
                },
            )
        )
    if pts_s:
        kids.append(
            TextArea(
                f"  {pts_s}",
                textprops={
                    "color": chg_col,
                    "fontproperties": fp(fsz, "bold"),
                },
            )
        )
    _paint_stamp_hbox(fig, kids, x=x, y=y, ha=ha, zorder=40)


def _paint_index_last_chg_tip(
    fig,
    *,
    close: float,
    prev_close: Optional[float],
    label_prefix: str = "費半",
    fp=None,
    x: float = 0.995,
    y: float = 0.848,
    ha: str = "right",
) -> None:
    """費半漲跌黃框：與加權同字級／同框高；字少故較短；圖層座標，不准壓加權黃框。"""
    if fig is None or fp is None:
        return
    from matplotlib.offsetbox import TextArea

    chg = _day_change_vs_prev(close, prev_close)
    pct_s = str(chg.get("pct_text") or "").strip()
    pts_s = str(chg.get("pts_text") or "").strip()
    col = _chg_paint_color(int(chg.get("sign") or 0))
    try:
        px_s = _px(float(close))
    except (TypeError, ValueError):
        px_s = "—"
    # 與加權同一套字級／框；前綴黑字，價→％→點數紅漲綠跌
    fsz = _TEACH_STAMP_FS
    kids = [
        TextArea(
            f"{label_prefix}  ",
            textprops={
                "color": _TEACH_STAMP_META,
                "fontproperties": fp(fsz, "bold"),
            },
        ),
        TextArea(
            px_s,
            textprops={"color": col, "fontproperties": fp(fsz, "bold")},
        ),
    ]
    if pct_s:
        kids.append(
            TextArea(
                f"  {pct_s}",
                textprops={"color": col, "fontproperties": fp(fsz, "bold")},
            )
        )
    if pts_s:
        kids.append(
            TextArea(
                f"  {pts_s}",
                textprops={"color": col, "fontproperties": fp(fsz, "bold")},
            )
        )
    _paint_stamp_hbox(fig, kids, x=x, y=y, ha=ha, zorder=41)


def _thesis_cap_for_query(
    db_path: str, *, now: Optional[datetime] = None
) -> str:
    """活畫題旨日上限：永遠可讀到查詢當日他文（週末／休市他也會發）；柱 as_of 仍另算。

    盤中未收柱仍不當官方收。同日文還要卡牆鐘（見 _latest_biaoke_index_snip）。
    2026-11-01：週日新文被卡在上一個開市日 cap＝漏題旨／三張不跟文。
    """
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    today = dt.strftime("%Y%m%d")
    chart = ""
    try:
        chart = _twii_chart_as_of(db_path)
    except Exception:
        chart = ""
    return max(x for x in (chart, today) if x)


def _latest_biaoke_index_snip(
    db_path: str,
    cap_ymd: str,
    *,
    now: Optional[datetime] = None,
    with_id: bool = False,
):
    """≤cap 日、且時間 ≤ 查詢當下的最新大盤相關他文（主文優先於短回）。

    短自回（「費半沒跌完」）也會命中細微波關鍵字；不准蓋掉同日長篇位階主文。
    with_id=True 時回 (snip, post_id)；否則只回 snip 字串。
    """
    empty = ("", "") if with_id else ""
    cap = _ymd(cap_ymd)
    if not db_path or not cap:
        return empty
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}"
    today_dash = dt.strftime("%Y-%m-%d")
    hm = dt.strftime("%H:%M")
    since = (dt - timedelta(days=21)).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT id, date, time, text FROM biaoke_posts "
                "WHERE date>=? AND date<=? "
                "ORDER BY date DESC, time DESC LIMIT 40",
                (since, cap_dash),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return empty
    best_blob = ""
    best_pid = ""
    best_score = -1
    for pid, date_s, time_s, text in rows or ():
        d = str(date_s or "").strip()
        t = str(time_s or "").strip()
        blob = str(text or "")
        if not blob:
            continue
        # 同一查詢日：不准吃到牆鐘之後的文
        if d == today_dash and t and t > hm:
            continue
        if not (_INDEXISH.search(blob) or looks_like_level_now(blob)):
            continue
        score = 0
        if looks_like_level_now(blob):
            score += 10
        if _INDEXISH.search(blob):
            score += 3
        if re.search(
            r"波浪位階|主跌段|C3-\d|(?<![0-9])3-3-\d|重新修訂|動態修正|不能去抄底|破底",
            blob,
        ):
            score += 12
        n = len(blob)
        if n >= 120:
            score += 6
        if n >= 240:
            score += 6
        # 主文 id 無 :c；短樓下回文降權
        sid = str(pid or "")
        if ":c" not in sid:
            score += 10
        elif n < 80:
            score -= 8
        if score > best_score:
            best_score = score
            best_blob = blob
            best_pid = sid
    if not best_blob:
        return empty
    # 留足長：11/1 文第3點才寫費半10445／4/28 9865，截太短會漏預測點
    snip = re.sub(r"\s+", " ", best_blob).strip()[:900]
    return (snip, best_pid) if with_id else snip


def _reserve_avoid_zone(
    ax: Any, x0: float, y0: float, x1: float, y1: float
) -> None:
    """登記圖上禁區（縮圖／黃戳／主線空檔）；智慧標不准坐進去。"""
    if ax is None:
        return
    zs = getattr(ax, "_wayne_avoid_zones", None)
    if zs is None:
        ax._wayne_avoid_zones = []
        zs = ax._wayne_avoid_zones
    zs.append(
        (
            float(min(x0, x1)),
            float(min(y0, y1)),
            float(max(x0, x1)),
            float(max(y0, y1)),
        )
    )


def _seat_onchart_labels(
    cands: Sequence[Dict[str, Any]],
    *,
    ymin: float,
    ymax: float,
    min_gap: float,
    avoid_zones: Optional[Sequence[Tuple[float, float, float, float]]] = None,
) -> List[Dict[str, Any]]:
    """智慧標座位：同圖內標垂直拉開，仍撞就丟掉（寧可少標不准互壓／蓋字／蓋縮圖）。"""
    items = [dict(c) for c in (cands or []) if c.get("text") is not None]
    if not items:
        return []
    span = max(ymax - ymin, 1.0)
    gap = max(float(min_gap), span * 0.045, 180.0)
    zones = [tuple(z) for z in (avoid_zones or []) if z is not None]

    def _in_zone(x: float, y: float, min_dx: float) -> bool:
        for zx0, zy0, zx1, zy1 in zones:
            if (zx0 - min_dx) <= x <= (zx1 + min_dx) and zy0 <= y <= zy1:
                return True
        return False

    items.sort(key=lambda d: (-int(d.get("pri") or 0), -float(d.get("y") or 0)))
    placed: List[Dict[str, Any]] = []
    used: List[Tuple[float, float]] = []  # (x, y)
    for it in items:
        x = float(it.get("x") or 0)
        y = float(it.get("y") or 0)
        min_dx = float(it.get("min_dx") or 1.2)
        nudge_up = (it.get("nudge") or "up") == "up"
        for _ in range(10):
            hit = any(
                abs(x - ux) < min_dx and abs(y - uy) < gap * 0.92 for ux, uy in used
            ) or _in_zone(x, y, min_dx)
            if not hit:
                break
            y = y + gap * (0.55 if nudge_up else -0.55)
        y = min(max(y, ymin + gap * 0.25), ymax - gap * 0.25)
        if any(
            abs(x - ux) < min_dx and abs(y - uy) < gap * 0.88 for ux, uy in used
        ) or _in_zone(x, y, min_dx):
            continue
        used.append((x, y))
        it["x"], it["y"] = x, y
        placed.append(it)
    return placed


def _latest_level_thesis(
    db_path: str, as_of: str = "", *, now: Optional[datetime] = None
) -> Dict[str, str]:
    """從最近位階 snap／貼文抽出活畫題旨（可遷移結構語，不背死價當唯一）。

    課綱三科：波浪 · 黃金切割 · 型態（見 wave_fib_morph_curriculum.md）。
    as_of＝題旨上限日：只准用 ≤ 該日的他文／snap，不准拿隔日 C3-3 回填昨天的圖。
    活畫另可把 as_of 放到查詢當日，對齊他最新發文（柱仍未收不當收）。
    """
    ensure_tables(db_path)
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    cap = _ymd(as_of) or _twii_chart_as_of(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT snippet, as_of, post_id FROM biaoke_level_snaps "
            "WHERE as_of<=? ORDER BY as_of DESC, created_at DESC LIMIT 1",
            (cap,),
        ).fetchone()
        # 近窗型態：再掃同 cap 內位階文，補形態學句
        extra = conn.execute(
            "SELECT snippet FROM biaoke_level_snaps "
            "WHERE as_of<=? ORDER BY as_of DESC, created_at DESC LIMIT 4",
            (cap,),
        ).fetchall()
    finally:
        conn.close()
    snip = str((row["snippet"] if row else "") or "")
    post_id = str((row["post_id"] if row else "") or "")
    # 對齊查詢當下最新大盤文：正文像現況位階就覆蓋 snap（仍卡 ≤cap／牆鐘）
    post_snip, post_snip_id = _latest_biaoke_index_snip(
        db_path, cap, now=dt, with_id=True
    )
    if post_snip and (not snip or looks_like_level_now(post_snip)):
        snip = post_snip
        if post_snip_id:
            post_id = post_snip_id
    morph_blob = snip + " " + " ".join(str(r["snippet"] or "") for r in (extra or []))
    if post_snip:
        morph_blob = f"{morph_blob} {post_snip}"
    # 庫內近期大盤文也補型態（缺 snap 時）；同樣卡 as_of
    if not _morph_note_from_text(morph_blob):
        try:
            cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}" if len(cap) == 8 else cap
            since = (dt - timedelta(days=14)).strftime("%Y-%m-%d")
            conn = sqlite3.connect(db_path, timeout=15.0)
            try:
                posts = conn.execute(
                    "SELECT text FROM biaoke_posts WHERE date>=? AND date<=? "
                    "AND (text LIKE '%型態%' OR text LIKE '%形態%' OR text LIKE '%楔形%' "
                    "OR text LIKE '%頸線%' OR text LIKE '%頭肩%' OR text LIKE '%橫台%') "
                    "ORDER BY date DESC, time DESC LIMIT 6",
                    (since, cap_dash),
                ).fetchall()
            finally:
                conn.close()
            morph_blob += " " + " ".join(str(p[0] or "") for p in posts)
        except Exception:
            pass
    morph = _morph_note_from_text(morph_blob)
    # 他確認大結構：大A底7/29→大B反彈（不是上升⑤）→大C進行中；近窗⑤後才是下降abc細分
    # 位階＝預估（他原文：很容易看錯／不要做太遠）；隨時檢視；誤導或鐵律不符→動態修正
    thesis = "大A底7/29→大B反彈→大C進行中（預估・隨時檢視）"
    wait = "C走完≠自動接新五波升；不符鐵律／被誤導→重修位階"
    # 他細微標號有時寫 C3-3-x、有時只寫 3-3-x（11/1 夜盤文）
    has_333 = ("C3-3-3" in snip) or bool(re.search(r"(?<![0-9])3-3-3(?![0-9])", snip))
    has_334 = ("C3-3-4" in snip) or bool(re.search(r"(?<![0-9])3-3-4(?![0-9])", snip))
    if "C3-3-1" in snip and "C3-3-2" in snip:
        thesis = "大A→大B→大C｜C內＝C3-3（1→2・預估）"
        wait = "下一測他點過錨；C走完≠新五波升；鐵律不符→重修"
    elif has_333 and has_334:
        thesis = "大A→大B→大C｜C內＝C3-3（3→4・預估）"
        wait = "第二組主跌未完；周一破底／勿抄底；C走完≠新五波升"
    elif "C3-3" in snip or has_333 or has_334:
        thesis = "大A→大B→大C｜C內＝C3-3主跌（預估）"
        wait = "隨時檢視細微；C走完≠新五波升；穿刺→重修"
    elif "橫台" in snip or "中繼" in snip:
        thesis = "大A→大B→大C｜C內橫台中繼（預估）"
        wait = "中繼後原方向；C走完≠新五波升；不符就改"
    elif "主跌" in snip:
        thesis = "大A→大B→大C｜C內主跌（預估）"
        wait = "細微波完整＋降軌；C走完≠新五波升；再重訂位階"
    if morph and "楔形" in morph:
        wait = f"{wait}｜型態：{morph}"
    elif morph:
        wait = f"{wait}｜型態觀察：{morph}"
    if _REVISE_MARK.search(snip):
        wait = "他已示警重修／動態修正・圖位＝當下預估" + (f"｜{morph}" if morph else "")
    return {
        "thesis": thesis,
        "wait_struct": wait[:360],
        "morph_note": morph[:180],
        "fib_note": "黃金切割反彈壓 0.382／0.618／0.75（他10/27台指日盤・可修訂）",
        "snippet": snip[:320],
        "snippet_full": snip[:900],
        "as_of": str((row["as_of"] if row else "") or cap),
        "post_id": post_id,
        "chart_as_of": cap,
    }


def _sparse_slot_id(dt: datetime, *, force: bool = False) -> Optional[str]:
    """稀疏槽 id；不在窗＝None。force 另開 force- 槽。"""
    ymd = dt.strftime("%Y%m%d")
    if force:
        return f"force-{ymd}-{dt.strftime('%H%M')}"
    hm = dt.hour * 60 + dt.minute
    for name, lo, hi in _SPARSE_SLOTS:
        if lo <= hm <= hi:
            return f"{ymd}-{name}"
    return None


def _load_tx60_rows(db_path: str, n: int = 80) -> List[Dict[str, Any]]:
    """庫內 TX 60 分 → 結構分析用列（活化 minute_bars）。"""
    try:
        from kline_hop import load_minute_bars

        bars = load_minute_bars("TX", "60", db_path) or []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for b in bars[-max(8, int(n)) :]:
        ts = str(b.get("t") or "")
        if len(ts) < 12:
            continue
        out.append(
            {
                "date": ts[:8],
                "ts": ts,
                "open": float(b.get("o") or 0),
                "high": float(b.get("h") or 0),
                "low": float(b.get("l") or 0),
                "close": float(b.get("c") or 0),
                "volume": float(b.get("v") or 0),
            }
        )
    return out


def _bar_vol_tags(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vols: Sequence[float],
    *,
    i: int,
    win: int = 20,
) -> Dict[str, Any]:
    """單根裸K＋相對近窗量（描述用，不當買訊）。"""
    n = len(closes)
    if i < 0 or i >= n:
        return {}
    lo = max(0, i - win + 1)
    wvols = [float(v) for v in vols[lo : i + 1]]
    v_med = sorted(wvols)[len(wvols) // 2] if wvols else 0.0
    o, h, l, c, v = (
        float(opens[i]),
        float(highs[i]),
        float(lows[i]),
        float(closes[i]),
        float(vols[i]),
    )
    body = abs(c - o)
    rng = max(1.0, h - l)
    upper = h - max(o, c)
    lower = min(o, c) - l
    up = c >= o
    vol_tag = "平量"
    if v_med > 0 and v >= v_med * 1.8:
        vol_tag = "爆量"
    elif v_med > 0 and v <= v_med * 0.55:
        vol_tag = "量縮"
    shape = "中實體"
    if body / rng < 0.25:
        shape = "十字／小實體"
    elif body / rng > 0.7:
        shape = "長實體"
    if lower / rng > 0.45 and body / rng < 0.35:
        shape = "長下影"
    if upper / rng > 0.45 and body / rng < 0.35:
        shape = "長上影"
    return {
        "up": up,
        "vol_tag": vol_tag,
        "shape": shape,
        "v_med": v_med,
        "v": v,
        "close": c,
        "open": o,
        "high": h,
        "low": l,
    }


def _twii_intent_story(db_path: str) -> Dict[str, str]:
    """加權日K量價故事→主力意圖（教沒底子的學生用白話；不是買訊）。

    老師＝飆大。不懂就查他原文再教：
    - 無量下跌≠止穩（10/30）
    - 沒爆量＝籌碼沒換完、沒止跌（10/22）
    - 主力不是大善人給散戶解套（10/23）
    - 紅漲後連跌＝套牢加深→別幻想好心拉回
    """
    out: Dict[str, str] = {"vol_note": "", "intent_note": "", "turn_note": ""}
    try:
        from biaoke_wave import _load_twii_bars
        from decision_card_signals import candle_up_taiwan
    except Exception:
        return out
    bars = _load_twii_bars(db_path, n=40)
    if len(bars) < 6:
        return out
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs = [float(r.get("high") or 0) for r in bars]
    lows = [float(r.get("low") or 0) for r in bars]
    closes = [float(r.get("close") or 0) for r in bars]
    vols = [float(r.get("volume") or 0) for r in bars]
    i = len(bars) - 1
    last = _bar_vol_tags(opens, highs, lows, closes, vols, i=i)
    if not last:
        return out
    # 連跌天數（收盤相對昨收）
    down_streak = 0
    for j in range(i, 0, -1):
        prev_c = closes[j - 1]
        if not candle_up_taiwan(closes[j], prev_c, opens[j]):
            down_streak += 1
        else:
            break
    # 套牢鏈：近窗曾有紅漲日，其後連續綠跌≥2
    trap = False
    trap_from = ""
    if down_streak >= 2 and i - down_streak >= 0:
        k = i - down_streak
        if candle_up_taiwan(closes[k], closes[k - 1] if k else None, opens[k]):
            trap = True
            trap_from = _md(bars[k].get("date"))
    color = "紅（漲）" if last["up"] else "綠（跌）"
    # 白話：先講學生看得到的K與量
    out["vol_note"] = (
        f"今天這根K是{color}、樣子像「{last['shape']}」；"
        f"成交量算「{last['vol_tag']}」"
        f"（今日{_px(last['v'])}，近窗平常大約{_px(last['v_med'])}）"
    )[:200]
    # 白話故事：聯想主力意圖（有他原文依據）
    stories: List[str] = []
    if (not last["up"]) and last["vol_tag"] == "量縮":
        stories.append(
            "量很小還在跌＝無量下跌；他教過：這不是「量縮止穩」，後面常繼續跌"
        )
    if (not last["up"]) and last["vol_tag"] != "爆量" and down_streak >= 1:
        stories.append(
            "跌的時候量沒爆出來＝籌碼還沒換完，還不能說已經止跌（他10/22量價課）"
        )
    if trap:
        stories.append(
            f"故事：{trap_from}有人還在買（紅K），接著連跌{down_streak}天＝愈套愈深；"
            "主力把人套住後，沒義務好心拉上來給大家解套"
            "（他10/23：主力不是大善人）"
        )
    if last["up"] and last["vol_tag"] == "爆量" and last["shape"] == "長上影":
        stories.append(
            "爆量卻留很長上影＝上面有人倒貨壓力大；先等第二天K確認，不要急著下判"
        )
    if last["shape"] in {"長下影", "十字／小實體"} and last["vol_tag"] != "爆量":
        stories.append(
            "只有影線或小實體、量又沒爆＝還沒真的換籌碼；單看一天不能喊止穩"
        )
    if not stories:
        stories.append(
            "今天量價故事還不清楚；照他習慣：看組合K＋量，最好等第二根再下結論"
        )
    out["intent_note"] = "；".join(stories)[:280]
    if down_streak >= 2:
        out["turn_note"] = (
            f"最近連續{down_streak}天收跌；先用「套牢／續跌」故事看，"
            "不要先假設會拉回來解套"
        )
    elif last["up"]:
        out["turn_note"] = "近窗收漲；還要第二天＋量價一起確認，才像真的轉折"
    return out


def _tx60_read(db_path: str) -> Dict[str, Any]:
    """台指 60 分結構＋量價裸K題旨（不數段）。"""
    rows = _load_tx60_rows(db_path, 80)
    out: Dict[str, Any] = {"n": len(rows), "levels": {}, "vol_note": "", "turn_note": ""}
    if len(rows) < 8:
        return out
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else last
    out["last"] = last
    # 近窗高低＝關鍵位候選（官方柱，不是發明價）
    win = rows[-20:] if len(rows) >= 20 else rows
    swing_hi = max(float(r["high"]) for r in win)
    swing_lo = min(float(r["low"]) for r in win)
    out["levels"] = {
        "tx60_last": float(last["close"]),
        "tx60_swing_hi": swing_hi,
        "tx60_swing_lo": swing_lo,
    }
    try:
        from biaoke_chart import analyze_structure

        struct = analyze_structure(rows) or {}
        if struct.get("down_now"):
            out["levels"]["tx60_down"] = float(struct["down_now"])
        notes = list(struct.get("notes") or [])
        if notes:
            out["struct_note"] = str(notes[-1])[:180]
    except Exception:
        struct = {}
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r["volume"]) for r in rows]
    tag = _bar_vol_tags(opens, highs, lows, closes, vols, i=len(rows) - 1)
    # 簡易吞沒／孕線（只描述，不當買訊）
    engulf = ""
    if float(last["high"]) >= float(prev["high"]) and float(last["low"]) <= float(
        prev["low"]
    ):
        engulf = "；外包前棒"
    elif float(last["high"]) <= float(prev["high"]) and float(last["low"]) >= float(
        prev["low"]
    ):
        engulf = "；孕線收斂"
    color = "紅漲" if tag.get("up") else "綠跌"
    out["vol_note"] = (
        f"TX60 裸K={color}{tag.get('shape', '')}{engulf}；量={tag.get('vol_tag', '')}"
        f"（{_px(tag.get('v'))}／近窗中位{_px(tag.get('v_med'))}）"
    )
    # 轉折：相對降軌／近窗高低
    down = out["levels"].get("tx60_down")
    turn = "近窗中段整理"
    if down and float(last["close"]) < float(down):
        turn = f"仍在降軌下（軌≈{_px(down)}）；過軌才像扭轉"
    if float(last["low"]) <= swing_lo * 1.001:
        turn = f"測近窗低{_px(swing_lo)}；止穩要縮量收回＋第二根確認（非預設解套）"
    if float(last["high"]) >= swing_hi * 0.999 and tag.get("up"):
        turn = f"碰近窗高{_px(swing_hi)}；爆量長上影＝壓、量縮＝假突破風險"
    out["turn_note"] = turn
    return out


def _ensure_us_index_daily(db_path: str) -> Dict[str, int]:
    """缺費半／納指日K就自己去 Yahoo 補進 index_daily（教具用；失敗不擋活畫）。

    符號：SOX／IXIC。TWII 官方柱不走這條。
    """
    stats = {"SOX": 0, "IXIC": 0}
    if not db_path:
        return stats
    try:
        import requests
        from taiwan_market import ensure_index_daily_table
    except Exception:
        return stats
    ensure_index_daily_table(db_path)
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    pairs = (("SOX", "^SOX"), ("IXIC", "^IXIC"))
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for sym, yid in pairs:
            # 近窗夠、且已有 4/28 前後柱 → 跳過；否則拉 1y（教具要標他點過的回測日K）
            n_have = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=?",
                (sym, "20260901"),
            ).fetchone()[0]
            n_apr = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=? AND date<=?",
                (sym, "20260420", "20260510"),
            ).fetchone()[0]
            n_jul = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=? AND date<=?",
                (sym, "20260725", "20260802"),
            ).fetchone()[0]
            if (
                int(n_have or 0) >= 25
                and int(n_apr or 0) >= 3
                and int(n_jul or 0) >= 3
            ):
                stats[sym] = int(n_have)
                continue
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
                f"?interval=1d&range=1y"
            )
            try:
                resp = requests.get(url, timeout=12, headers=ua)
                if resp.status_code != 200:
                    continue
                block = ((resp.json() or {}).get("chart") or {}).get("result") or [None]
                block = block[0] or {}
                stamps = block.get("timestamp") or []
                q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
            except Exception:
                logger.exception("補%s日K失敗", sym)
                continue
            written = 0
            for ts, op, hi, lo, cl, vol in zip(
                stamps,
                q.get("open") or [],
                q.get("high") or [],
                q.get("low") or [],
                q.get("close") or [],
                q.get("volume") or [],
            ):
                if cl is None or op is None:
                    continue
                try:
                    dt = datetime.fromtimestamp(int(ts), tz=TAIPEI)
                except (TypeError, ValueError, OSError):
                    continue
                d = dt.strftime("%Y%m%d")
                o = float(op)
                c = float(cl)
                h = float(hi if hi is not None else max(o, c))
                l = float(lo if lo is not None else min(o, c))
                v = float(vol or 0)
                pct = None
                conn.execute(
                    """
                    INSERT INTO index_daily(
                        date, symbol, open, high, low, close, volume, pct_change, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, symbol) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume,
                        updated_at=excluded.updated_at
                    """,
                    (d, sym, o, h, l, c, v, pct, _now()),
                )
                written += 1
            conn.commit()
            stats[sym] = written
            # 補 pct_change（對前收）
            rows = conn.execute(
                "SELECT date, close FROM index_daily WHERE symbol=? ORDER BY date",
                (sym,),
            ).fetchall()
            prev = None
            for d, c in rows:
                if prev and prev > 0 and c:
                    pct = (float(c) / float(prev) - 1.0) * 100.0
                    conn.execute(
                        "UPDATE index_daily SET pct_change=? WHERE date=? AND symbol=?",
                        (pct, d, sym),
                    )
                prev = float(c) if c else prev
            conn.commit()
    finally:
        conn.close()
    # Yahoo 失敗時：費半還可從 minute_bars 日切（庫內已有 SOX 分K）
    if stats.get("SOX", 0) < 10:
        try:
            stats["SOX"] = int(_sox_daily_from_minutes(db_path) or 0)
        except Exception:
            logger.exception("SOX 分K日切略過")
    # ^SOX 指數幾乎無官方量 → 另抓 SOXX ETF 量當費半量代理（標清楚）
    try:
        stats["SOXX"] = int(_ensure_soxx_volume_proxy(db_path) or 0)
    except Exception:
        logger.exception("SOXX 量代理略過")
        stats["SOXX"] = 0
    return stats


def _ensure_soxx_volume_proxy(db_path: str) -> int:
    """補 SOXX 日K量：費半指數本身無成交量，教具量柱用 SOXX 代理。"""
    if not db_path:
        return 0
    try:
        import requests
        from taiwan_market import ensure_index_daily_table
    except Exception:
        return 0
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        n_have = conn.execute(
            "SELECT COUNT(*) FROM index_daily WHERE symbol='SOXX' AND date>=? AND volume>0",
            ("20260701",),
        ).fetchone()[0]
        if int(n_have or 0) >= 40:
            return int(n_have)
    finally:
        conn.close()
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    url = "https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1d&range=6mo"
    try:
        resp = requests.get(url, timeout=12, headers=ua)
        if resp.status_code != 200:
            return 0
        block = ((resp.json() or {}).get("chart") or {}).get("result") or [None]
        block = block[0] or {}
        stamps = block.get("timestamp") or []
        q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    except Exception:
        logger.exception("補 SOXX 失敗")
        return 0
    written = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for ts, op, hi, lo, cl, vol in zip(
            stamps,
            q.get("open") or [],
            q.get("high") or [],
            q.get("low") or [],
            q.get("close") or [],
            q.get("volume") or [],
        ):
            if cl is None or op is None:
                continue
            try:
                dt = datetime.fromtimestamp(int(ts), tz=TAIPEI)
            except (TypeError, ValueError, OSError):
                continue
            d = dt.strftime("%Y%m%d")
            o = float(op)
            c = float(cl)
            h = float(hi if hi is not None else max(o, c))
            l = float(lo if lo is not None else min(o, c))
            v = float(vol or 0)
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, pct_change, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    updated_at=excluded.updated_at
                """,
                (d, "SOXX", o, h, l, c, v, None, _now()),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def _sox_daily_from_minutes(db_path: str) -> int:
    """minute_bars SOX → index_daily 日切備援。"""
    conn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        days = [
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT substr(ts,1,8) FROM minute_bars "
                "WHERE stock_id='SOX' AND ts>='202608010000' ORDER BY 1"
            )
        ]
        for d in days:
            row = conn.execute(
                "SELECT "
                "(SELECT o FROM minute_bars WHERE stock_id='SOX' AND substr(ts,1,8)=? "
                "ORDER BY ts ASC LIMIT 1), "
                "MAX(h), MIN(l), "
                "(SELECT c FROM minute_bars WHERE stock_id='SOX' AND substr(ts,1,8)=? "
                "ORDER BY ts DESC LIMIT 1), "
                "SUM(v) "
                "FROM minute_bars WHERE stock_id='SOX' AND substr(ts,1,8)=?",
                (d, d, d),
            ).fetchone()
            if not row or row[0] is None or row[3] is None:
                continue
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    updated_at=excluded.updated_at
                """,
                (d, "SOX", float(row[0]), float(row[1]), float(row[2]), float(row[3]),
                 float(row[4] or 0), _now()),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _load_us_daily(
    db_path: str, symbol: str, since: str = "20260915"
) -> List[Dict[str, Any]]:
    """讀 index_daily 美股符號；缺就空。"""
    sym = str(symbol or "").upper()
    since_s = _ymd(since) or "20260915"
    if not db_path or not sym:
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, pct_change "
            "FROM index_daily WHERE symbol=? AND date>=? ORDER BY date",
            (sym, since_s),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append(
            {
                "date": str(r[0]),
                "open": float(r[1] or 0),
                "high": float(r[2] or 0),
                "low": float(r[3] or 0),
                "close": float(r[4] or 0),
                "volume": float(r[5] or 0),
                "pct": float(r[6]) if r[6] is not None else None,
            }
        )
    return out


def _us_lead_read(db_path: str) -> Dict[str, Any]:
    """納指／費半先行（活化 us_overnight；他的外圍順序）。缺柱先自己補。"""
    out: Dict[str, Any] = {"note": "", "levels": {}}
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("補美股日K略過")
    try:
        from us_overnight import load_us_overnight
    except Exception:
        return out
    # 找最近有資料的 as_of
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        row = conn.execute(
            "SELECT as_of FROM us_overnight ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return out
    as_of = str(row[0])
    try:
        us = load_us_overnight(db_path, as_of) or {}
    except Exception:
        return out
    ixic_pct = us.get("ixic_pct")
    sox_pct = us.get("sox_pct")
    regime = str(us.get("regime") or "")
    ixic_px = us.get("ixic_px")
    sox_px = us.get("sox_px")
    if ixic_px:
        out["levels"]["ixic"] = float(ixic_px)
    if sox_px:
        out["levels"]["sox"] = float(sox_px)
    # 庫內日K最後收也可當錨
    for sym, key in (("SOX", "sox"), ("IXIC", "ixic")):
        if key in out["levels"]:
            continue
        series = _load_us_daily(db_path, sym, "20261001")
        if series:
            out["levels"][key] = float(series[-1]["close"])

    def _pct(v: Any) -> str:
        try:
            return f"{float(v):+.2f}%"
        except (TypeError, ValueError):
            return "—"

    lead = "外圍中性"
    try:
        sp = float(sox_pct) if sox_pct is not None else None
        ip = float(ixic_pct) if ixic_pct is not None else None
    except (TypeError, ValueError):
        sp = ip = None
    if sp is not None and sp <= -2.0:
        lead = "費半大弱→台指夜／日偏壓（他常用費半先行）"
    elif sp is not None and sp >= 2.0:
        lead = "費半偏強→短線反彈空間打開（仍看降軌）"
    elif ip is not None and ip <= -1.5:
        lead = "納指弱→風險偏收斂"
    elif ip is not None and ip >= 1.5:
        lead = "納指強→跟漲情緒，仍要過結構壓"
    out["note"] = (
        f"美股{as_of} 納指{_pct(ixic_pct)} 費半{_pct(sox_pct)}"
        f"（{regime or '—'}）；{lead}"
    )
    return out


def _futures_day_night(db_path: str) -> Dict[str, Any]:
    """大台 TX／電子 TE：日盤＋夜盤（電子盤）最近柱。

    我估隔夜順位：TX夜 vs 前日日盤最直接；TE夜交叉電子氣氛。不准假數。
    """
    out: Dict[str, Any] = {"levels": {}, "note": "", "tx_night_pct": None, "te_night_pct": None}
    if not db_path or not os.path.isfile(db_path):
        return out
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        def _last(sym: str, session: str):
            return conn.execute(
                "SELECT date, open, high, low, close, volume, pct_change FROM futures_daily "
                "WHERE symbol=? AND session=? ORDER BY date DESC LIMIT 1",
                (sym, session),
            ).fetchone()

        tx_n, tx_d = _last("TX", "night"), _last("TX", "regular")
        te_n, te_d = _last("TE", "night"), _last("TE", "regular")
    except sqlite3.OperationalError:
        # 煙霧／空庫沒 futures_daily：不准炸 pack；有正式庫再寫夜盤注
        return out
    finally:
        conn.close()
    parts: List[str] = []
    if tx_n:
        out["levels"]["tx_night_c"] = float(tx_n[4])
        out["levels"]["tx_night_l"] = float(tx_n[3])
        out["levels"]["tx_night_h"] = float(tx_n[2])
        try:
            out["tx_night_pct"] = float(tx_n[6]) if tx_n[6] is not None else None
        except (TypeError, ValueError):
            out["tx_night_pct"] = None
        # 相對最近日盤收：夜盤消化美股後的跳空氣氛
        if tx_d and float(tx_d[4]) > 0:
            gap = (float(tx_n[4]) - float(tx_d[4])) / float(tx_d[4]) * 100.0
            out["tx_night_vs_day_pct"] = gap
            parts.append(
                f"大台夜{tx_n[0]}收{_px(tx_n[4])}（vs日{_px(tx_d[4])} {gap:+.2f}%）"
            )
        else:
            parts.append(
                f"大台夜{tx_n[0]}收{_px(tx_n[4])}（高{_px(tx_n[2])}低{_px(tx_n[3])}）"
            )
    if tx_d:
        out["levels"]["tx_day_c"] = float(tx_d[4])
        if not tx_n:
            parts.append(f"大台日{tx_d[0]}收{_px(tx_d[4])}")
    if te_n:
        out["levels"]["te_night_c"] = float(te_n[4])
        try:
            out["te_night_pct"] = float(te_n[6]) if te_n[6] is not None else None
        except (TypeError, ValueError):
            out["te_night_pct"] = None
        pct_s = ""
        if out["te_night_pct"] is not None:
            pct_s = f" {out['te_night_pct']:+.2f}%"
        parts.append(f"電子夜{te_n[0]}收{float(te_n[4]):.1f}{pct_s}")
    if te_d:
        out["levels"]["te_day_c"] = float(te_d[4])
    out["note"] = "；".join(parts)[:240]
    return out


def _claim_anchors(db_path: str) -> Dict[str, Any]:
    """近窗他說過的大盤／台指錨（活化 claims；不准發明新價）。"""
    out: Dict[str, Any] = {"levels": {}, "note": ""}
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT lo, hi, snippet, stock_id FROM biaoke_claims
            WHERE (stock_id IN ('','TWII','TX') OR stock_id IS NULL)
            ORDER BY post_date DESC, post_time DESC LIMIT 60
            """
        ).fetchall()
    except Exception:
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass
    vals: List[float] = []
    for lo, hi, snip, _sid in rows:
        blob = str(snip or "")
        if not re.search(r"大盤|台指|加權|夜盤|細微|C3|主跌", blob):
            # 無指數語且無高價 → 跳過個股錨
            pass
        for raw in (lo, hi):
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v >= 20000:
                vals.append(v)
    if not vals:
        return out
    vals = sorted(set(int(round(v)) for v in vals))[-6:]
    out["levels"] = {f"claim_{i}": float(v) for i, v in enumerate(vals)}
    out["note"] = "他近窗點過：" + "／".join(_px(v) for v in vals)
    return out


def _level_break_tag(level: float, lows: Sequence[float]) -> str:
    """官方柱是否已破該價；未破不准寫已破。"""
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return "未到"
    if not lows:
        return "未到"
    try:
        mn = min(float(x) for x in lows if x is not None)
    except ValueError:
        return "未到"
    if mn < lv - 0.5:
        return "已破"
    return "未破" if mn <= lv * 1.02 else "未到"


def _biaoke_pred_label(
    price: float,
    tag: str = "",
    *,
    prob: Optional[float] = None,
) -> str:
    """他點過的位：標成『飆預測』＋狀態；機率只有真量化傳入才帶％（不准假％）。"""
    base = f"飆預測{_px(price)}"
    t = str(tag or "").strip()
    if t:
        base = f"{base}{t}"
    if prob is None:
        return base
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return base
    if 0.0 < p <= 100.0:
        return f"{base}（{int(round(p))}%機率）"
    return base


def _official_bar_low(db_path: str, symbol: str, ymd: str) -> Optional[float]:
    """官方日K低；缺柱回 None（不准假數）。"""
    d = _ymd(ymd)
    sym = str(symbol or "").upper()
    if not db_path or not d or not sym:
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT low FROM index_daily WHERE symbol=? AND date=?",
                (sym, d),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _thesis_pred_levels(snip: str, db_path: str = "") -> Dict[str, Any]:
    """從他最新題旨抽出寫死預測點＋回測日（只認原文數字，不准發明）。

    回傳 tw／sox 列：level／ref_ymd／ref_md／role／tag／label／note。
    """
    s = str(snip or "")
    out: Dict[str, Any] = {"tw": [], "sox": [], "note": ""}
    if not s:
        return out

    def _add(bucket: str, *, level: float, ref_ymd: str, role: str, tag: str, label: str) -> None:
        row = {
            "level": float(level),
            "ref_ymd": _ymd(ref_ymd),
            "ref_md": _md(ref_ymd) if _ymd(ref_ymd) else "",
            "role": role,
            "tag": tag,
            "label": label,
        }
        out[bucket].append(row)

    # 台指／大盤
    if re.search(r"44042", s):
        _add(
            "tw",
            level=44042.0,
            ref_ymd="",
            role="周一破台指",
            tag="未到",
            label=f"飆預測{_px(44042)}周一破台指",
        )
    if re.search(r"39384", s) and re.search(r"7\s*/\s*29|7月29", s):
        off = _official_bar_low(db_path, "TWII", "20260729")
        tag = "第三組才必破"
        lab = f"7/29低{_px(39384)}（第三組末跌）"
        if off is not None and abs(off - 39384.0) <= 2.0:
            lab = f"7/29低{_px(off)}（第三組末跌）"
        _add(
            "tw",
            level=float(off) if off is not None and abs(off - 39384.0) <= 2.0 else 39384.0,
            ref_ymd="20260729",
            role="第三組末跌",
            tag=tag,
            label=lab,
        )

    # 費半：7/29 A波低 10445；周五 10439 已破；次回測 4/28 9865
    if re.search(r"10445", s) and re.search(r"7\s*/\s*29|A\s*波", s):
        off = _official_bar_low(db_path, "SOX", "20260729")
        fri = _official_bar_low(db_path, "SOX", "20261030")
        tag = "已破" if (fri is not None and fri < 10445.0 - 0.5) or re.search(
            r"10439.*已破|已經破A", s
        ) else "未破"
        lv = float(off) if off is not None and abs(off - 10445.0) <= 2.0 else 10445.0
        # 右標／腳註要短且完整：周五低改寫進 tag 旁短註，不准長句被裁半截
        lab = f"7/29 A低{_px(lv)}{tag}"
        if fri is not None and tag == "已破":
            lab = f"7/29 A低{_px(lv)}已破·周五{_px(fri)}"
        _add(
            "sox",
            level=lv,
            ref_ymd="20260729",
            role="A波低",
            tag=tag,
            label=lab,
        )
    if re.search(r"9865", s) and re.search(r"4\s*/\s*28", s):
        off = _official_bar_low(db_path, "SOX", "20260428")
        lv = float(off) if off is not None and abs(off - 9865.0) <= 2.0 else 9865.0
        _add(
            "sox",
            level=lv,
            ref_ymd="20260428",
            role="次回測",
            tag="未到",
            label=f"次回測4/28低{_px(lv)}",
        )

    # 他最新文抽出的大盤／台指點位 → 進預測列（虛線／右標跟著換；不准發明）
    seen_tw = {round(float(r["level"]), 1) for r in out["tw"]}
    try:
        from biaoke_walk import extract_index_levels

        for hit in extract_index_levels(s) or []:
            try:
                lv = float(hit.get("level"))
            except (TypeError, ValueError):
                continue
            if not (35000.0 <= lv <= 60000.0):
                continue
            key = round(lv, 1)
            if key in seen_tw:
                continue
            seen_tw.add(key)
            role = str(hit.get("role") or "點位")
            _add(
                "tw",
                level=lv,
                ref_ymd="",
                role=role,
                tag="未到",
                label=f"飆預測{_px(lv)}",
            )
    except Exception:
        logger.debug("題旨抽大盤點位略過", exc_info=True)
    # 費半點位：文內「費半…數字」或既有 10445／9865 外的他寫價
    seen_sox = {round(float(r["level"]), 1) for r in out["sox"]}
    for m in re.finditer(
        r"費半[^0-9]{0,16}(\d{4,5}(?:\.\d+)?)", s
    ):
        try:
            lv = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if not (7000.0 <= lv <= 16000.0):
            continue
        key = round(lv, 1)
        if key in seen_sox:
            continue
        seen_sox.add(key)
        _add(
            "sox",
            level=lv,
            ref_ymd="",
            role="費半點位",
            tag="未到",
            label=f"費半{_px(lv)}",
        )

    bits = []
    for row in out["tw"]:
        bits.append(str(row.get("label") or ""))
    for row in out["sox"]:
        bits.append(str(row.get("label") or ""))
    out["note"] = "｜".join(b for b in bits if b)[:280]
    return out


def _tw_support_ladder(pack: Optional[Dict[str, Any]] = None) -> Tuple[float, ...]:
    """加權撐位：他最新寫死點優先＋舊錨備援（高→低）。"""
    vals: List[float] = []
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            v = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if v >= 20000:
            vals.append(v)
    for k, raw in ((pack or {}).get("key_levels") or {}).items():
        if not str(k).startswith(("pred_tw_", "claim_")):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v >= 20000:
            vals.append(v)
    # 舊錨只在他沒點新價時當備援；有他點就跟著他的梯子走
    if not vals:
        vals = [45546.0, 44210.0]
    else:
        for fixed in (45546.0, 44210.0):
            if any(abs(fixed - v) < 1.0 for v in vals):
                vals.append(fixed)
    return tuple(sorted(set(vals), reverse=True))


def _tw_tip_anchors(pack: Optional[Dict[str, Any]] = None) -> Tuple[float, ...]:
    """預估虛線下一錨順序（高→低）：跟他最新題旨點位走；沒點才退回 45546→44210。

    只吃 pred_levels.tw 與 key_levels 的 pred_tw_*（他寫死預測錨）。
    不准把舊 claim_* 歷史宣稱混進虛線梯，否則端點／右標會卡在舊價。
    """
    his: List[float] = []
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            v = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if 30000.0 <= v <= 60000.0:
            his.append(v)
    for k, raw in ((pack or {}).get("key_levels") or {}).items():
        if not str(k).startswith("pred_tw_"):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if 30000.0 <= v <= 60000.0:
            his.append(v)
    if not his:
        return (45546.0, 44210.0)
    # 他點過的價高→低；1 點內視為同錨（避免 39384／39384.9 雙標）
    ordered = sorted(his, reverse=True)
    uniq: List[float] = []
    for v in ordered:
        if any(abs(v - u) < 1.0 for u in uniq):
            continue
        uniq.append(round(v, 1))
    return tuple(uniq)


def _paint_window_dual_zones(
    ax,
    *,
    highs: Sequence[float],
    lows: Sequence[float],
    vols: Sequence[float],
    bars: Sequence[Dict[str, Any]],
    y_now: float,
    fp: Any,
    supports: Sequence[float] = (45546.0, 44210.0),
    resists: Sequence[float] = (47637.0, 48613.0),
    skip_label_ys: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """遠／近／超近共用：黃＝最大量日高低、青＝飆預測位階帶（不交疊）；底色在K下層。"""
    n = len(highs)
    i_vmax: Optional[int] = None
    if n and any(float(v or 0) > 0 for v in vols):
        i_vmax = max(range(n), key=lambda i: float(vols[i] or 0))
    sr = _next_support_resist(float(y_now), supports=supports, resists=resists)
    y_excl_lo = float(lows[i_vmax]) if i_vmax is not None else None
    y_excl_hi = float(highs[i_vmax]) if i_vmax is not None else None
    if i_vmax is not None:
        _paint_max_vol_hl_zone(
            ax,
            high=float(highs[i_vmax]),
            low=float(lows[i_vmax]),
            date_lab=_ymd(bars[i_vmax].get("date")),
            fp=fp,
        )
    # 青位階虛線只畫到末日K右緣；右欄飆預測字在更右，不准字盒壓線
    sr_skip = _paint_next_sr_zone(
        ax,
        support=sr.get("support"),
        resist=sr.get("resist"),
        fp=fp,
        exclude_lo=y_excl_lo,
        exclude_hi=y_excl_hi,
        skip_label_ys=skip_label_ys,
        x_end=float(n) + 0.12 if n else None,
    )
    return {
        "sr": sr,
        "sr_skip": sr_skip,
        "i_vmax": i_vmax,
        "y_excl_lo": y_excl_lo,
        "y_excl_hi": y_excl_hi,
    }


def _build_live_pack(
    db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """彙整庫內多源 → 一包題旨／關鍵位／量價（活化使用）。

    now＝查詢當下（台北）；題旨對齊 ≤ 查詢日的最新飆大文；
    chart_as_of 仍＝已收完整柱末日（盤中未收不當收）。
    """
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    chart_as_of = _twii_chart_as_of(db_path)
    thesis_cap = _thesis_cap_for_query(db_path, now=dt)
    thesis_pack = _latest_level_thesis(db_path, as_of=thesis_cap, now=dt)
    tx = _tx60_read(db_path)
    tw = _twii_intent_story(db_path)
    us = _us_lead_read(db_path)
    fut = _futures_day_night(db_path)
    claims = _claim_anchors(db_path)
    levels: Dict[str, float] = {}
    for src in (tx, us, fut, claims):
        for k, v in (src.get("levels") or {}).items():
            try:
                levels[k] = float(v)
            except (TypeError, ValueError):
                continue
    # 日K主力意圖故事優先；TX60 裸K當盤中輔句
    turn = (
        str(tw.get("turn_note") or "")
        or str(tx.get("turn_note") or "")
        or thesis_pack.get("wait_struct")
        or ""
    )
    vol_parts = [p for p in (tw.get("vol_note"), tx.get("vol_note")) if p]
    vol = "｜".join(vol_parts)[:240]
    intent = str(tw.get("intent_note") or "")[:240]
    us_note = str(us.get("note") or "")
    wait = str(thesis_pack.get("wait_struct") or "")
    if intent:
        wait = f"{wait}｜量價故事：{intent}"
    if fut.get("note"):
        wait = f"{wait}｜{fut['note']}"
    if claims.get("note"):
        wait = f"{wait}｜{claims['note']}"
    pred = _thesis_pred_levels(
        str(
            thesis_pack.get("snippet_full")
            or thesis_pack.get("snippet")
            or ""
        ),
        db_path,
    )
    if pred.get("note"):
        wait = f"{wait}｜預測點：{pred['note']}"
    for row in (pred.get("tw") or []):
        try:
            levels[f"pred_tw_{int(float(row['level']))}"] = float(row["level"])
        except (TypeError, ValueError, KeyError):
            continue
    for row in (pred.get("sox") or []):
        try:
            levels[f"pred_sox_{int(float(row['level']))}"] = float(row["level"])
        except (TypeError, ValueError, KeyError):
            continue
    return {
        "thesis": thesis_pack.get("thesis") or "",
        "wait_struct": wait[:480],
        "turn_note": str(turn)[:240],
        "vol_note": vol,
        "intent_note": intent,
        "us_note": us_note[:240],
        "morph_note": str(thesis_pack.get("morph_note") or "")[:180],
        "fib_note": str(thesis_pack.get("fib_note") or "")[:120],
        "key_levels": levels,
        # pred_levels＝他原文抽出（獨立源）；不准把 self_pred 寫進來
        "pred_levels": pred,
        "pred_note": str(pred.get("note") or "")[:280],
        "_fut_snap": fut,
        "snippet": thesis_pack.get("snippet") or "",
        "chart_as_of": chart_as_of,
        "thesis_as_of": thesis_cap,
        "query_at": dt.isoformat(),
    }


# 活畫深底：暖墨指揮台（元素全留；縮圖遠看也要跟舊版一眼不同）
_LIVE_BG = "#0b0908"
_LIVE_PANEL = "#14110f"
_LIVE_PANEL_EDGE = "#2a221c"
_LIVE_HUD = "#100e0c"
_LIVE_ACCENT = "#ffb300"
_LIVE_TEXT = "#f6f1e8"
_LIVE_MUTED = "#a89a88"
_LIVE_GRID = "#241c16"
_LIVE_UP = "#ff4d4d"
_LIVE_DOWN = "#26c6a8"
_LIVE_CHIP_FC = "#1a1512"
# 遠窗縮圖：絕對 min body=6 對費半／加權價軸幾乎看不見；改跟價窗比例走
_LIVE_CANDLE_MIN_BODY_FRAC = 0.01
_FAR_SOX_MIN_BODY_FRAC = 0.018
# 遠窗固定根數（約 2026-03-31→最新）：含推進⑤＝4/1→6/23；每多一日刪最左
_FAR_TEACH_MAX_BARS = 152


def _far_teach_roll_bars(
    bars: Sequence[Dict[str, Any]], *, max_bars: int = _FAR_TEACH_MAX_BARS
) -> List[Dict[str, Any]]:
    """遠窗滾動裁切：超過 max_bars 只留最右（最新）一段。"""
    rows = list(bars or [])
    cap = max(20, int(max_bars or _FAR_TEACH_MAX_BARS))
    if len(rows) > cap:
        return rows[-cap:]
    return rows


def _teach_chip_bbox(edge: str, *, pad: float = 0.22, lw: float = 1.35, alpha: float = 0.96) -> Dict[str, Any]:
    """浪名／註解晶片：厚邊＋暖墨底（話筒縮圖遠看也讀得到框）。"""
    return {
        "boxstyle": f"round,pad={float(pad)}",
        "fc": _LIVE_CHIP_FC,
        "ec": str(edge or _LIVE_ACCENT),
        "lw": float(lw),
        "alpha": float(alpha),
    }


def _wave_line(
    ax,
    xs,
    ys,
    color: str,
    *,
    lw: float = 2.0,
    ls: str = "-",
    alpha: float = 1.0,
    zorder: float = 7,
    glow: bool = True,
) -> None:
    """結構浪線：雙層光暈＋實線（bold 版；不准改錨點）。"""
    if ax is None:
        return
    xlist = list(xs)
    ylist = list(ys)
    if len(xlist) < 2 or len(ylist) < 2:
        return
    kw = dict(solid_capstyle="round", solid_joinstyle="round")
    if glow and ls == "-":
        ax.plot(
            xlist,
            ylist,
            color=color,
            lw=float(lw) * 7.2,
            alpha=min(0.16, float(alpha) * 0.22),
            ls=ls,
            zorder=float(zorder) - 0.6,
            **kw,
        )
        ax.plot(
            xlist,
            ylist,
            color=color,
            lw=float(lw) * 3.6,
            alpha=min(0.34, float(alpha) * 0.42),
            ls=ls,
            zorder=float(zorder) - 0.3,
            **kw,
        )
    ax.plot(
        xlist,
        ylist,
        color=color,
        lw=float(lw) * 1.08,
        alpha=float(alpha),
        ls=ls,
        zorder=float(zorder),
        **kw,
    )


def _style_teach_axes(axes) -> None:
    """三張教具共用面板：暖墨底、低調格、左側略強調。"""
    for a in axes:
        if a is None:
            continue
        a.set_facecolor(_LIVE_PANEL)
        a.tick_params(colors=_LIVE_MUTED, labelsize=9, length=3.5, width=0.7)
        for side, sp in a.spines.items():
            sp.set_color(_LIVE_ACCENT if side == "left" else _LIVE_PANEL_EDGE)
            sp.set_linewidth(1.35 if side == "left" else 0.85)
        a.grid(True, linestyle=(0, (1.0, 2.4)), linewidth=0.4, color=_LIVE_GRID, alpha=0.85)
        a.set_axisbelow(True)


def _paint_right_rail_panel(ax, *, x0: float, x1: float) -> None:
    """右欄價梯底板：K 區與右標分層，標籤仍全畫，不准吃掉數字。"""
    if ax is None:
        return
    try:
        lo = float(x0)
        hi = float(x1)
    except (TypeError, ValueError):
        return
    if hi <= lo + 0.2:
        return
    ax.axvspan(
        lo,
        hi,
        facecolor="#0e0a08",
        edgecolor="none",
        alpha=0.88,
        zorder=0.28,
    )
    # 雙線分隔：外琥珀＋內淡線，縮圖遠看也分得出價梯卡
    ax.axvline(lo, color=_LIVE_ACCENT, lw=1.55, alpha=0.72, zorder=0.45)
    ax.axvline(lo + 0.12, color=_LIVE_ACCENT, lw=0.55, alpha=0.28, zorder=0.46)


def _paint_teach_hud(
    fig,
    *,
    title: str,
    meta: str = "",
    fp,
    chips: Optional[Sequence[Tuple[str, str]]] = None,
    top: float = 0.888,
    height: float = 0.112,
) -> None:
    """頁眉指揮條：標題＋圖例晶片列＋日曆淡行。元素全留，只換成可掃的層級。"""
    if fig is None:
        return
    try:
        from matplotlib.patches import Rectangle
    except Exception:
        return
    y0 = float(top)
    h = float(height)
    fig.patches.append(
        Rectangle(
            (0.0, y0),
            1.0,
            h,
            transform=fig.transFigure,
            facecolor=_LIVE_HUD,
            edgecolor="none",
            zorder=-2,
            clip_on=False,
        )
    )
    fig.patches.append(
        Rectangle(
            (0.0, y0),
            0.012,
            h,
            transform=fig.transFigure,
            facecolor=_LIVE_ACCENT,
            edgecolor="none",
            zorder=-1,
            clip_on=False,
        )
    )
    fig.patches.append(
        Rectangle(
            (0.0, y0),
            1.0,
            0.0032,
            transform=fig.transFigure,
            facecolor=_LIVE_ACCENT,
            alpha=0.4,
            edgecolor="none",
            zorder=-1,
            clip_on=False,
        )
    )
    fig.text(
        0.028,
        y0 + h * 0.72,
        str(title or ""),
        fontproperties=fp(14, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="center",
        zorder=20,
    )
    # 圖例改晶片橫列（仍是同一批資訊，不准刪；寬度用字數估，避免中途 canvas.draw）
    chip_rows = [(str(a), str(b)) for a, b in (chips or []) if str(a or "").strip()]
    x_chip = 0.028
    y_chip = y0 + h * 0.38
    for lab, col in chip_rows[:5]:
        # 價帶晶片放寬到 28：數字不准中途切成「9,」；短標仍緊湊
        lim = 28 if any(ch.isdigit() for ch in lab) else 20
        short = lab if len(lab) <= lim else (lab[: lim - 1] + "…")
        fig.text(
            x_chip,
            y_chip,
            short,
            fontproperties=fp(8, "bold"),
            color=col or _LIVE_ACCENT,
            ha="left",
            va="center",
            zorder=21,
            bbox=_teach_chip_bbox(col or _LIVE_ACCENT, pad=0.36, lw=1.25, alpha=0.97),
        )
        # 全形約 0.0115／字；加框墊與縫（價帶較長仍不准撞黃戳區）
        x_chip += 0.020 + min(0.28, 0.0115 * max(4, len(short)))
        if x_chip > 0.70:
            break
    if meta:
        fig.text(
            0.028,
            y0 + h * 0.12,
            str(meta)[:168],
            fontproperties=fp(7, "bold"),
            color=_LIVE_MUTED,
            ha="left",
            va="center",
            zorder=20,
        )


def _paint_teach_foot_bar(fig, *, y: float = 0.0, height: float = 0.052) -> None:
    """頁腳暖墨條＋琥珀豎條（腳註字仍由呼叫端畫）。"""
    if fig is None:
        return
    try:
        from matplotlib.patches import Rectangle
    except Exception:
        return
    fig.patches.append(
        Rectangle(
            (0.0, float(y)),
            1.0,
            float(height),
            transform=fig.transFigure,
            facecolor=_LIVE_HUD,
            edgecolor="none",
            zorder=-2,
            clip_on=False,
        )
    )
    fig.patches.append(
        Rectangle(
            (0.0, float(y)),
            0.012,
            float(height),
            transform=fig.transFigure,
            facecolor=_LIVE_ACCENT,
            edgecolor="none",
            zorder=-1,
            clip_on=False,
        )
    )


_LIVE_LV = (
    ("tx60_down", "#ce93d8", "降軌"),
    ("tx60_swing_hi", "#ffd54f", "近窗高"),
    ("tx60_swing_lo", "#81d4fa", "近窗低"),
    ("tx_night_l", "#ffab91", "夜低"),
)


def _candle_span_min_body(
    highs: Sequence[float], lows: Sequence[float], *, frac: float = _LIVE_CANDLE_MIN_BODY_FRAC
) -> float:
    """可見最小實體高度＝價窗比例（遠窗縮圖不准再用絕對 6）。"""
    import math

    hs = [float(x) for x in highs if x == x and math.isfinite(float(x))]
    ls = [float(x) for x in lows if x == x and math.isfinite(float(x))]
    if not hs or not ls:
        return 6.0
    span = max(hs) - min(ls)
    if span <= 0:
        return 6.0
    return max(6.0, float(span) * float(frac))


def _paint_one_live_candle(
    ax,
    i: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    prev_c: Optional[float],
    candle_up,
    min_body: float,
    width: float = 0.68,
    wick_lw: float = 1.35,
    z_wick: int = 5,
    z_body: int = 6,
    edgecolor: Optional[str] = None,
    edge_lw: float = 0.45,
) -> None:
    """單根日K；給遠窗末根蓋回紫點／右標用（z 高於 tip scatter）。"""
    import matplotlib.pyplot as plt

    up = candle_up(close, prev_c, open_)
    color = _LIVE_UP if up else _LIVE_DOWN
    ec = edgecolor or color
    wick = ax.vlines(
        i, low, high, color=color, linewidth=wick_lw, zorder=z_wick, clip_on=False
    )
    try:
        wick.set_clip_on(False)
    except Exception:
        pass
    y0, y1 = sorted((float(open_), float(close)))
    patch = plt.Rectangle(
        (i - width * 0.5, y0),
        width,
        max(y1 - y0, float(min_body)),
        facecolor=color,
        edgecolor=ec,
        linewidth=edge_lw,
        zorder=z_body,
        clip_on=False,
    )
    ax.add_patch(patch)


def _extend_us_ohlc_past_twii(
    aligned: Dict[str, List[float]],
    us_rows: Sequence[Dict[str, Any]],
    last_twii_ymd: str,
) -> Tuple[Dict[str, List[float]], List[str]]:
    """加權軸之後若美股還有已收官方日 → 只追加美股 OHLC（不准造假加權柱）。"""
    import math

    last_d = _ymd(last_twii_ymd)
    opens = list(aligned.get("open") or [])
    highs = list(aligned.get("high") or [])
    lows = list(aligned.get("low") or [])
    closes = list(aligned.get("close") or [])
    volumes = list(aligned.get("volume") or [])
    extra_dates: List[str] = []
    if not last_d:
        return (
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
            extra_dates,
        )
    seen = set(extra_dates)
    rows = sorted(
        (
            r
            for r in (us_rows or [])
            if _ymd(r.get("date"))
            and _ymd(r.get("date")) > last_d
            and float(r.get("close") or 0) > 0
        ),
        key=lambda r: _ymd(r.get("date")),
    )
    for r in rows:
        d = _ymd(r.get("date"))
        if not d or d in seen:
            continue
        o = float(r.get("open") or r.get("close") or 0)
        h = float(r.get("high") or r.get("close") or 0)
        lo = float(r.get("low") or r.get("close") or 0)
        c = float(r.get("close") or 0)
        if not (c > 0 and math.isfinite(o) and math.isfinite(h) and math.isfinite(lo)):
            continue
        opens.append(o)
        highs.append(h)
        lows.append(lo)
        closes.append(c)
        volumes.append(float(r.get("volume") or 0))
        extra_dates.append(d)
        seen.add(d)
    return (
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        extra_dates,
    )


def _style_live_ax(ax, axv) -> None:
    _style_teach_axes((ax, axv))
    for a in (ax, axv):
        if a is not None:
            a.tick_params(labelsize=10)


def _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up) -> None:
    n = len(closes)
    min_body = _candle_span_min_body(highs, lows, frac=_LIVE_CANDLE_MIN_BODY_FRAC)
    import matplotlib.pyplot as plt

    last_c = None
    for i in range(n):
        prev_c = closes[i - 1] if i else None
        up = candle_up(closes[i], prev_c, opens[i])
        color = _LIVE_UP if up else _LIVE_DOWN
        rim = "#ffcdd2" if up else "#b2dfdb"
        # wick/body z 高於底帶、低於空心 tip；末根另蓋回
        ax.vlines(i, lows[i], highs[i], color=color, linewidth=1.55, zorder=5, alpha=0.95)
        y0, y1 = sorted((opens[i], closes[i]))
        ax.add_patch(
            plt.Rectangle(
                (i - 0.36, y0),
                0.72,
                max(y1 - y0, float(min_body)),
                facecolor=color,
                edgecolor=rim,
                linewidth=0.65,
                zorder=6,
                alpha=0.98,
            )
        )
        if axv is not None:
            axv.bar(i, vols[i], color=color, width=0.72, zorder=3, alpha=0.9)
        last_c = color
    # 末日柔光：縮圖一眼看到「現在這根」
    if n >= 1 and last_c:
        ax.scatter(
            [n - 1],
            [closes[-1]],
            s=220,
            c=last_c,
            alpha=0.12,
            zorder=4.5,
            linewidths=0,
        )


def _paint_special_candle(
    ax,
    i: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    color: str = "#ffd54f",
    date_lab: str = "",
    fp: Any = None,
) -> None:
    """把指定日K改特殊色（蓋在普通紅綠上）；給最大量日那一根用。

    價圖不准再貼「最大量」黃字標——量欄已有「最大量＋月日」；對日靠金K＋豎虛線＋黃底左標。
    date_lab／fp 保留相容，不畫字。
    """
    import matplotlib.pyplot as plt

    _ = (date_lab, fp)
    ax.vlines(i, low, high, color=color, linewidth=1.55, zorder=6)
    y0, y1 = sorted((float(open_), float(close)))
    ax.add_patch(
        plt.Rectangle(
            (i - 0.36, y0),
            0.72,
            max(y1 - y0, 8),
            facecolor=color,
            edgecolor="#fff59d",
            linewidth=0.9,
            zorder=7,
        )
    )


def _paint_vol_bars_max_yellow(
    axv,
    vols: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
    candle_up,
    *,
    fp: Any,
    title: str = "量",
    date_lab: str = "",
) -> Optional[int]:
    """日量柱；窗內最大量那根改黃色並標「最大量＋月日」。回傳最大量索引（＝當日K同一格）。"""
    n = len(vols)
    if n == 0 or axv is None:
        return None
    vals = [float(v or 0) for v in vols]
    i_max = max(range(n), key=lambda i: vals[i]) if any(v > 0 for v in vals) else None
    for i in range(n):
        prev_c = closes[i - 1] if i else None
        up = candle_up(closes[i], prev_c, opens[i] if i < len(opens) else closes[i])
        color = "#ffeb3b" if i_max is not None and i == i_max else (_LIVE_UP if up else _LIVE_DOWN)
        axv.bar(i, vals[i], color=color, width=0.68, zorder=3, alpha=0.95 if color == "#ffeb3b" else 0.88)
    if i_max is not None and vals[i_max] > 0:
        tip = f"最大量 {_md(date_lab)}" if _ymd(date_lab) else "最大量"
        axv.annotate(
            tip,
            xy=(i_max, vals[i_max]),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontproperties=fp(8, "bold"),
            color="#ffeb3b",
            zorder=10,
            bbox=_teach_chip_bbox("#ffeb3b", pad=0.12, lw=0.7, alpha=0.94),
        )
    axv.set_ylabel(title, fontproperties=fp(9, "bold"), color=_LIVE_MUTED)
    return i_max


def _paint_max_vol_day_guide(axes: Sequence[Any], i_max: Optional[int]) -> None:
    """三欄同一 x 畫黃虛線，最大量日與上方金K／黃底／量柱對齊一眼可見。"""
    if i_max is None:
        return
    for a in axes:
        if a is None:
            continue
        a.axvline(float(i_max), color="#ffeb3b", lw=1.15, ls=(0, (4, 2)), alpha=0.88, zorder=5)


def _next_support_resist(
    y_now: float,
    *,
    supports: Sequence[float],
    resists: Sequence[float],
) -> Dict[str, Optional[float]]:
    """此刻下方最近撐、上方最近壓（只認傳入的他說過／結構位）。"""
    yn = float(y_now)
    below = sorted((float(x) for x in supports if x is not None and float(x) < yn - 1.0), reverse=True)
    above = sorted(float(x) for x in resists if x is not None and float(x) > yn + 1.0)
    return {
        "support": below[0] if below else None,
        "resist": above[0] if above else None,
    }


def _paint_max_vol_hl_zone(
    ax,
    *,
    high: float,
    low: float,
    date_lab: str,
    fp: Any,
) -> None:
    """淺黃底＝最大量日那根K的最高～最低；底色 zorder 低於K棒。

    左標一定帶交易日月日，跟金K／量柱黃／豎虛線同一日，不准只寫高低不寫日。
    """
    y0, y1 = float(low), float(high)
    if y1 <= y0:
        return
    md = _md(date_lab) if _ymd(date_lab) else ""
    day_tag = f"{md} " if md else ""
    # 只留淺黃底，不准上下虛線框（框會跟K攪糊）；對齊交易日靠豎虛線＋金K＋左標月日
    # alpha 略降：K 燭體仍清楚，黃帶只當層級提示
    ax.axhspan(y0, y1, facecolor="#ffd54f", alpha=0.10, zorder=0.5)
    ax.text(
        0.01,
        y1,
        f"{day_tag}最大量日高 {_px(y1)}",
        transform=ax.get_yaxis_transform(),
        fontproperties=fp(9, "bold"),
        color="#ffe082",
        ha="left",
        va="bottom",
        zorder=11,
        bbox=_teach_chip_bbox("#ffeb3b", pad=0.14, lw=0.75, alpha=0.94),
    )
    ax.text(
        0.01,
        y0,
        f"{day_tag}最大量日低 {_px(y0)}",
        transform=ax.get_yaxis_transform(),
        fontproperties=fp(9, "bold"),
        color="#ffe082",
        ha="left",
        va="top",
        zorder=11,
        bbox=_teach_chip_bbox("#ffeb3b", pad=0.14, lw=0.75, alpha=0.94),
    )


def _hl_spans_excluding(
    y0: float,
    y1: float,
    *,
    ex_lo: Optional[float] = None,
    ex_hi: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """回傳 [y0,y1] 扣掉 [ex_lo,ex_hi] 後不相交的段；兩底色不准互疊。"""
    a, b = (float(y0), float(y1)) if float(y0) <= float(y1) else (float(y1), float(y0))
    if ex_lo is None or ex_hi is None:
        return [(a, b)] if b > a else []
    e0, e1 = (float(ex_lo), float(ex_hi)) if float(ex_lo) <= float(ex_hi) else (float(ex_hi), float(ex_lo))
    if e1 <= a or e0 >= b:
        return [(a, b)]
    out: List[Tuple[float, float]] = []
    if a < e0:
        out.append((a, min(e0, b)))
    if e1 < b:
        out.append((max(e1, a), b))
    return [(lo, hi) for lo, hi in out if hi > lo + 0.5]


def _y_inside_hl(y: float, lo: Optional[float], hi: Optional[float]) -> bool:
    """真價是否落在黃帶開區間內（標在這裡會看起來像青底仍蓋過去）。"""
    if lo is None or hi is None:
        return False
    a, b = (float(lo), float(hi)) if float(lo) <= float(hi) else (float(hi), float(lo))
    return a < float(y) < b


def _paint_next_sr_zone(
    ax,
    *,
    support: Optional[float],
    resist: Optional[float],
    fp: Any,
    exclude_lo: Optional[float] = None,
    exclude_hi: Optional[float] = None,
    skip_label_ys: Optional[Sequence[float]] = None,
    x_end: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """飆預測位階青帶；與最大量黃帶重疊處不塗（兩底色不准互疊）。

    回傳落在黃帶內、左欄故意不標的價（呼叫端可改放右欄），避免青標浮在黃底上像交疊。
    skip_label_ys＝已由預估端／右欄標過的價，左欄不准再貼同價「飆預測」（多餘）。
    x_end＝水平虛線右端（資料座標）；有給就不准 axhline 貫穿右欄標籤。
    """
    skipped: Dict[str, Optional[float]] = {"support": None, "resist": None}
    if support is None and resist is None:
        return skipped
    skip_set = {round(float(y), 1) for y in (skip_label_ys or []) if y is not None}

    def _skip_lab(y: float) -> bool:
        return round(float(y), 1) in skip_set

    def _level_dash(y: float, color: str = "#4dd0e1") -> None:
        if x_end is not None:
            ax.plot(
                [-0.5, float(x_end)],
                [float(y), float(y)],
                color=color,
                lw=0.85,
                ls=(0, (3, 2)),
                alpha=0.55,
                zorder=4,
                solid_capstyle="butt",
            )
        else:
            ax.axhline(
                float(y),
                color=color,
                lw=0.85,
                ls=(0, (3, 2)),
                alpha=0.55,
                zorder=4,
            )

    # 左標：真價若不在黃帶內才標；在黃帶內 → 交給右欄（不准看起來像青底蓋過黃）
    # 左標有畫的 → 同價水平虛線（位階不是某日K，但是他點過的真價）
    if support is not None:
        if _y_inside_hl(float(support), exclude_lo, exclude_hi):
            skipped["support"] = float(support)
        else:
            _level_dash(float(support))
            if not _skip_lab(float(support)):
                ax.text(
                    0.01,
                    float(support),
                    _biaoke_pred_label(float(support)),
                    transform=ax.get_yaxis_transform(),
                    fontproperties=fp(9, "bold"),
                    color="#b2ebf2",
                    ha="left",
                    va="top",
                    zorder=11,
                    bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec="#4dd0e1", lw=0.7, alpha=0.94),
                )
    if resist is not None:
        if _y_inside_hl(float(resist), exclude_lo, exclude_hi):
            skipped["resist"] = float(resist)
        else:
            _level_dash(float(resist))
            if not _skip_lab(float(resist)):
                ax.text(
                    0.01,
                    float(resist),
                    _biaoke_pred_label(float(resist)),
                    transform=ax.get_yaxis_transform(),
                    fontproperties=fp(9, "bold"),
                    color="#b2ebf2",
                    ha="left",
                    va="bottom",
                    zorder=11,
                    bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec="#4dd0e1", lw=0.7, alpha=0.94),
                )
    if support is None or resist is None:
        return skipped
    y0, y1 = float(support), float(resist)
    if y1 <= y0:
        return skipped
    for lo, hi in _hl_spans_excluding(y0, y1, ex_lo=exclude_lo, ex_hi=exclude_hi):
        ax.axhspan(lo, hi, facecolor="#4dd0e1", alpha=0.14, zorder=0.4)
    return skipped


def _paint_sr_zone_yellow(
    ax,
    *,
    y_now: float,
    support: Optional[float],
    resist: Optional[float],
    fp: Any,
    n: int,
) -> None:
    """相容舊名：改轉呼叫青色下一撐壓（不准再跟最大量黃帶同色）。"""
    _paint_next_sr_zone(ax, support=support, resist=resist, fp=fp, exclude_lo=None, exclude_hi=None)


def _bar_index_by_ymd(bars: Sequence[Dict[str, Any]], ymd: str) -> Optional[int]:
    want = _ymd(ymd)
    if not want:
        return None
    for i, r in enumerate(bars):
        if _ymd(r.get("date")) == want:
            return i
    return None


def _md(ymd: Any) -> str:
    t = _ymd(ymd)
    return f"{int(t[4:6])}/{int(t[6:8])}" if len(t) == 8 else str(ymd or "")


def _sparse_xticks(
    idxs: Sequence[int],
    labels: Sequence[str],
    *,
    min_gap: int = 2,
) -> Tuple[List[int], List[str]]:
    """日期刻度稀釋：相鄰索引少於 min_gap 只留前一個，不准 10/15 壓 10/16。"""
    pairs = sorted(((int(i), str(lab)) for i, lab in zip(idxs, labels)), key=lambda t: t[0])
    out_i: List[int] = []
    out_l: List[str] = []
    last = -10**9
    for i, lab in pairs:
        if out_i and i - last < int(min_gap):
            continue
        out_i.append(i)
        out_l.append(lab)
        last = i
    return out_i, out_l


def _pin_pivot_name(
    ax,
    x: float,
    y: float,
    lab: str,
    color: str,
    fp,
    *,
    side: str = "auto",
    tip: str = "mid",
    n: Optional[int] = None,
    pad_x: float = 0.35,
    fontsize: int = 10,
    zorder: int = 10,
    clear_dy: Optional[float] = None,
    pri: int = 5,
) -> None:
    """浪名智慧標：尖點對準，整盒不准蓋住縮圖K；走座位，不准互壓／蓋禁區。

    tip=high → 整盒在高點上方；tip=low → 整盒在低點下方（含 bbox pad 也離尖）；
    tip=mid → 左右錯開到柱外（C／今）。
    """
    tip_k = str(tip or "mid").lower()
    try:
        y_lo, y_hi = ax.get_ylim()
        span = max(float(y_hi) - float(y_lo), 1.0)
    except Exception:
        y_lo, y_hi = float(y) - 1.0, float(y) + 1.0
        span = max(abs(float(y)) * 0.08, 1.0)
    # bbox pad 會往尖點回吃一截 → 必須再撐開，整盒才離得開K
    lift = float(clear_dy) if clear_dy is not None else max(span * 0.04, abs(float(y)) * 0.002)
    yy = float(y)
    if tip_k in {"high", "low"}:
        # 上下離尖；若指定 left／right 再水平讓開（A／B 緊貼黃K時必讓）
        va = "bottom" if tip_k == "high" else "top"
        yy = float(y) + lift if tip_k == "high" else float(y) - lift
        if side == "left":
            xx, ha = float(x) - max(float(pad_x), 0.7), "right"
        elif side == "right":
            xx, ha = float(x) + max(float(pad_x), 0.7), "left"
        else:
            xx, ha = float(x), "center"
    else:
        xx = float(x) + float(pad_x)
        ha = "left"
        va = "center"
        use_left = side == "left" or (
            side == "auto" and n is not None and float(x) >= max(float(n) * 0.62, 1.0)
        )
        if use_left:
            xx = float(x) - float(pad_x)
            ha = "right"
        elif side == "right":
            xx = float(x) + float(pad_x)
            ha = "left"
    seats = getattr(ax, "_wayne_pin_seats", None)
    if seats is None:
        ax._wayne_pin_seats = []
        seats = ax._wayne_pin_seats
    avoid = list(getattr(ax, "_wayne_avoid_zones", None) or [])
    prior = [
        {
            "x": float(sx),
            "y": float(sy),
            "text": f"__seat{i}",
            "pri": 100,
            "min_dx": 1.35,
        }
        for i, (sx, sy) in enumerate(seats)
    ]
    lab_s = str(lab)
    seated = _seat_onchart_labels(
        prior
        + [
            {
                "x": float(xx),
                "y": float(yy),
                "text": lab_s,
                "pri": int(pri),
                "nudge": "up" if tip_k == "high" else "down",
                "min_dx": 1.35,
            }
        ],
        ymin=float(y_lo),
        ymax=float(y_hi),
        min_gap=span * 0.05,
        avoid_zones=avoid,
    )
    mine = [r for r in seated if str(r.get("text")) == lab_s]
    if not mine:
        return
    xx = float(mine[0]["x"])
    yy = float(mine[0]["y"])
    seats.append((xx, yy))
    ax.text(
        xx,
        yy,
        lab_s,
        fontproperties=fp(int(fontsize), "bold"),
        color=color,
        ha=ha,
        va=va,
        zorder=int(zorder),
        clip_on=False,
        bbox=_teach_chip_bbox(color, pad=0.16, lw=0.8, alpha=0.93),
    )


def _c_path_label_xy(
    i0: float,
    y0: float,
    i1: float,
    y1: float,
    *,
    i_avoid: Optional[float] = None,
) -> Tuple[float, float]:
    """C進行中釘在 B→今 折線上；若有最大量日，選離它最遠的參數 t。"""

    def _xy(t: float) -> Tuple[float, float]:
        return (
            float(i0) + (float(i1) - float(i0)) * t,
            float(y0) + (float(y1) - float(y0)) * t,
        )

    if i_avoid is None:
        return _xy(0.42)
    cands = (0.18, 0.28, 0.38, 0.48, 0.58, 0.68, 0.78, 0.88)
    t_best = max(cands, key=lambda t: abs(_xy(t)[0] - float(i_avoid)))
    return _xy(t_best)


def _place_live_right_labels(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    n: int,
    ymin: float,
    ymax: float,
    fp,
    level_dash: bool = True,
    min_gap: Optional[float] = None,
    x_text_min: Optional[float] = None,
    x_col: Optional[float] = None,
) -> None:
    """右側價標：全部對齊同一右欄；同色水平虛線從指定點位連到標籤。

    - 字 Y＝真價（不准漂離）；真價互撞→丟低優先。
    - 字 X＝同一欄（預設對齊長標如「7/29低…」那欄），不准左一截右一截。
    - 虛線：note['x']（轉折／末日）→ 標籤左緣，顏色＝標籤色。
    note 可設 dash=False；level_dash=False 時整批不畫虛線。
    """
    items = [dict(x) for x in (notes or []) if x.get("y") is not None and x.get("text")]
    if not items:
        return
    span = max(ymax - ymin, 1.0)
    # 間距只跟價窗比例走。不准絕對 floor 把真價標漂離（費半 10445↔9865）。
    gap = float(min_gap) if min_gap is not None else span * 0.09
    gap = max(gap, span * 0.055)
    # 浪／細浪硬標可互近，仍留呼吸；c5(45677)↔今(45212) 差值約 465 必須雙留
    gap_wave = max(span * 0.033, 360.0)

    def _tier(t: str) -> int:
        """0=浪／細浪／今（必留）→1=飆預測等→2=Fib／切／錨（可丟）。"""
        s = str(t or "")
        if s.startswith("Fib") or s.startswith("切") or s.startswith("錨"):
            return 2
        if (
            "c4細" in s
            or "c5細" in s
            or s.startswith("⑤")
            or s.startswith("A低")
            or s.startswith("B高")
            or s.startswith("C今")
            or s.startswith("今 ")
            or s.startswith("今　")
            or s.startswith("費")
        ):
            return 0
        return 1

    def _pri(d: Dict[str, Any]) -> Tuple[int, float]:
        return (_tier(str(d.get("text") or "")), -float(d["y"]))

    def _collide(y0: float, tier: int, kept_ys: List[float], kept_tiers: List[int]) -> bool:
        for ky, kt in zip(kept_ys, kept_tiers):
            # 兩個浪標：用較緊間距，才留得下 c4／c5／今
            thresh = gap_wave if (tier == 0 and kt == 0) else gap * 0.85
            if abs(y0 - ky) < thresh:
                return True
        return False

    items.sort(key=_pri)
    kept: List[Dict[str, Any]] = []
    kept_ys: List[float] = []
    kept_tiers: List[int] = []
    for it in items:
        y0 = float(it["y"])
        t = str(it.get("text") or "")
        tier = _tier(t)
        if _collide(y0, tier, kept_ys, kept_tiers):
            continue
        kept.append(it)
        kept_ys.append(y0)
        kept_tiers.append(tier)
    kept.sort(key=lambda d: float(d["y"]), reverse=True)
    placed: List[float] = []
    placed_tiers: List[int] = []
    # 同一右欄：預設 n+2.55（夠長標「7/29低…」）；可被 x_col／x_text_min 拉開
    x_label = float(x_col) if x_col is not None else float(n) + 2.55
    if x_text_min is not None:
        try:
            x_label = max(x_label, float(x_text_min) + 0.85)
        except (TypeError, ValueError):
            pass
    for it in kept:
        y_true = float(it["y"])
        if y_true < ymin or y_true > ymax:
            continue
        tier = _tier(str(it.get("text") or ""))
        if _collide(y_true, tier, placed, placed_tiers):
            continue
        placed.append(y_true)
        placed_tiers.append(tier)
        color = str(it.get("color") or _LIVE_MUTED)
        try:
            x_from = float(it.get("x"))
        except (TypeError, ValueError):
            x_from = float(n) - 1.0
        # 點位在標籤右側時仍從左側合理點拉（末日K）
        if x_from >= x_label - 0.25:
            x_from = max(0.0, float(n) - 1.0)
        x_from = max(0.0, float(x_from))
        # 虛線停在標籤左緣外，不准切進框內數字
        x_dash_end = max(x_from + 0.2, x_label - 0.55)
        if level_dash and it.get("dash", True) and x_dash_end > x_from + 0.15:
            ax.plot(
                [x_from, x_dash_end],
                [y_true, y_true],
                color=color,
                lw=1.2,
                ls=(0, (3.0, 1.7)),
                alpha=0.9,
                zorder=5,
                solid_capstyle="butt",
            )
        ax.text(
            x_label,
            y_true,
            str(it["text"])[:28],
            fontproperties=fp(10, "bold"),
            color=color,
            ha="left",
            va="center",
            zorder=10,
            clip_on=False,
            bbox=_teach_chip_bbox(color, pad=0.24, lw=1.4, alpha=0.97),
        )


def _his_micro_degree(blob: str) -> Dict[str, str]:
    """從他原文／題旨抽出『現在在哪一層小波』（只認他寫過的代號）。"""
    s = str(blob or "")
    degree = ""
    # 細微可寫 C3-3-x 或裸 3-3-x；轉段語（3→4／完成轉）優先較新的那一層
    if re.search(r"C3-3-4|(?<![0-9])3-3-4(?![0-9])|3→4|3\-3\-3完成轉3\-3\-4", s):
        degree = "C3-3-4"
    elif re.search(r"C3-3-3|(?<![0-9])3-3-3(?![0-9])", s) and not re.search(
        r"3→4|轉3-3-4|轉C3-3-4", s
    ):
        degree = "C3-3-3"
    elif re.search(r"C3-3-2|C3‑3‑2", s):
        degree = "C3-3-2"
    elif re.search(r"C3-3-1|C3‑3‑1", s):
        degree = "C3-3-1"
    elif re.search(r"C3-3", s):
        degree = "C3-3"
    elif re.search(r"C3-", s):
        degree = "C3"
    elif re.search(r"(現在在C|下降ABC.*C|主跌段)", s):
        degree = "C"
    chain = "五波→ABC→C"
    if degree.startswith("C3"):
        chain = "五波→ABC→C→C3-3" if "C3-3" in degree else "五波→ABC→C→C3"
    if degree in ("C3-3-1", "C3-3-2", "C3-3-3", "C3-3-4"):
        chain = f"五波→ABC→C→C3-3→{degree}"
    return {"degree": degree, "chain": chain, "raw": s[:160]}


def _geom_c_micro_swings(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    i_bhi: int,
    i_c: int,
    i_now: int,
) -> Dict[str, Any]:
    """C 段內柱上小波錨（預估）：只服務超級近窗教學，不准當買訊、不准發明個股浪。

    回傳 pivots（索引）與 geom_degree（跟他說的比對用）。
    """
    out: Dict[str, Any] = {
        "pivots": [],
        "geom_degree": "C",
        "i_c1_lo": None,
        "i_c2_hi": None,
        "i_c3_lo": None,
    }
    if not (0 <= i_bhi < i_c <= i_now < len(closes)):
        return out
    # C 啟動後：找第一個較深低（C3-3-1 底候選）→ 反彈高（C3-3-2 高）→ 其後再低
    seg_lo = list(range(i_c, i_now + 1))
    if len(seg_lo) < 3:
        out["geom_degree"] = "C"
        out["pivots"] = [(i_bhi, float(highs[i_bhi]), "B"), (i_now, float(closes[i_now]), "今")]
        return out
    # 前半窗最低＝①底；後半相對高＝②高；②後最低＝③進行
    mid = i_c + max(2, (i_now - i_c) // 2)
    i_c1 = min(range(i_c, min(mid + 1, i_now + 1)), key=lambda i: float(lows[i]))
    i_c2 = max(range(i_c1, i_now + 1), key=lambda i: float(highs[i])) if i_c1 < i_now else i_c1
    i_c3 = (
        min(range(i_c2, i_now + 1), key=lambda i: float(lows[i]))
        if i_c2 < i_now
        else i_now
    )
    out["i_c1_lo"] = int(i_c1)
    out["i_c2_hi"] = int(i_c2)
    out["i_c3_lo"] = int(i_c3)
    out["pivots"] = [
        (int(i_bhi), float(highs[i_bhi]), "B高"),
        (int(i_c), float(closes[i_c]), "C起"),
        (int(i_c1), float(lows[i_c1]), "①低"),
        (int(i_c2), float(highs[i_c2]), "②高"),
        (int(i_now), float(closes[i_now]), "今"),
    ]
    # 柱上小波讀法：已做出②高且今收低於②→偏 C3-3-2 進行；否則仍像 ①
    if i_c2 > i_c1 and float(closes[i_now]) < float(highs[i_c2]) * 0.998:
        if i_c3 > i_c2 and float(lows[i_c3]) < float(lows[i_c1]) * 1.001:
            out["geom_degree"] = "C3-3-2"
        else:
            out["geom_degree"] = "C3-3-1"
    else:
        out["geom_degree"] = "C3-3-1"
    return out


def _c_subwave_anchors_vs_biaoke60(
    highs: Sequence[float],
    lows: Sequence[float],
    bars: Sequence[Dict[str, Any]],
    *,
    i_c: int,
    i_now: int,
) -> Dict[str, Any]:
    """C 內細浪錨：只釘他 60 分圖對得上、且官方日K 對得上的點。

    大結構仍是日K ⑤→A→B→C；此處 c4／c5 是 C 裡細分，不取代 ABC。
    他標約 47408.95（4高）／45676.57（5低）；日K 取 C 段內最近高／低。
    """
    out: Dict[str, Any] = {
        "i_c4_hi": None,
        "y_c4": None,
        "i_c5_lo": None,
        "y_c5": None,
        "ok": False,
    }
    if not (0 <= i_c <= i_now < len(highs) == len(lows)):
        return out
    if i_now - i_c < 2:
        return out
    # 他圖 5 低 → 日K 優先 10/27；否則 C 段內距 45676.57 最近的低
    target_c5 = 45676.57
    target_c4 = 47408.95
    i_pref5 = _bar_index_by_ymd(list(bars), "20261027")
    if i_pref5 is not None and i_c <= i_pref5 <= i_now:
        i_c5 = int(i_pref5)
    else:
        i_c5 = min(
            range(i_c, i_now + 1),
            key=lambda i: abs(float(lows[i]) - target_c5),
        )
    # 4 高須在 5 低之前（下跌 1–5 的第 4 腳）
    hi_hi = max(i_c, i_c5 - 1)
    if hi_hi < i_c:
        return out
    i_c4 = min(
        range(i_c, hi_hi + 1),
        key=lambda i: abs(float(highs[i]) - target_c4),
    )
    y4, y5 = float(highs[i_c4]), float(lows[i_c5])
    # 離他標太遠＝還沒走出／對不上，不硬標（±2.5%）
    if abs(y5 - target_c5) / target_c5 > 0.025:
        return out
    if abs(y4 - target_c4) / target_c4 > 0.025:
        return out
    out["i_c4_hi"] = int(i_c4)
    out["y_c4"] = y4
    out["i_c5_lo"] = int(i_c5)
    out["y_c5"] = y5
    out["ok"] = True
    return out


def _alt_path_needed(his_degree: str, geom_degree: str) -> bool:
    """另色演化線：只有同家族細微層互斥才畫（如 C3-3-1 vs C3-3-2）。

    C／橫台 vs 柱讀 C3-* 不准另畫——會讓人以為他換前提。同層＝不畫。
    """
    h = str(his_degree or "").strip()
    g = str(geom_degree or "").strip()
    if not h or not g:
        return False
    if h.startswith("C3-3") and g.startswith("C3-3"):
        return h != g
    return False


def _self_pred_label(price: float, basis: str) -> str:
    """我的判斷預估標：必須帶依據；≠他說／飆預測。

    單向：可讀他的當參考；不准把我估回寫成他的依據或標成飆預測。
    """
    b = str(basis or "").strip()[:28]
    if b:
        return f"我估{_px(price)}｜{b}"
    return f"我估{_px(price)}｜依據未寫＝不准"


def _near_his_level(lv: float, his: Sequence[float], *, tol: float = 80.0) -> bool:
    try:
        x = float(lv)
    except (TypeError, ValueError):
        return False
    for h in his:
        try:
            if abs(x - float(h)) <= tol:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _build_self_pred_levels(
    pack: Optional[Dict[str, Any]],
    *,
    y_now: float,
    y5: float,
    y_alow: float,
    y_bhi: float,
    highs: Sequence[float],
    lows: Sequence[float],
    vols: Sequence[float],
    bars: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> Dict[str, Any]:
    """我的判斷預估（≠他說・非買訊）。

    依據優先序（我評估後鎖）：
    1) 官方加權轉折距（⑤／A／B 等長或 1.618 延伸）
    2) 近窗官方高低／最大量日高低
    3) 庫內費半／納指已收（他比照美股→我也比照；SOX 對台半導體有實證領先文獻）
    每筆必帶 basis；與他寫死位太近就不另標「我估」（避免冒充他的）。
    """
    pack = pack or {}
    his_lv: List[float] = []
    his_notes: List[Dict[str, Any]] = []
    for row in ((pack.get("pred_levels") or {}).get("tw") or []):
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        his_lv.append(lv)
        his_notes.append(
            {
                "level": lv,
                "label": f"他說{str(row.get('label') or _px(lv))[:22]}",
                "color": "#90a4ae",
                "source": "his",
            }
        )
    for fixed in (45546.0, 44210.0):
        if not _near_his_level(fixed, his_lv, tol=1.0):
            his_lv.append(fixed)
            his_notes.append(
                {
                    "level": fixed,
                    "label": f"他說錨{_px(fixed)}",
                    "color": "#78909c",
                    "source": "his",
                }
            )

    mine: List[Dict[str, Any]] = []
    yn = float(y_now)
    # 1) 官方轉折：B 高 − (⑤−A) 等長 C；再 1.618 延伸
    leg = float(y5) - float(y_alow)
    if leg > 200:
        c_eq = float(y_bhi) - leg
        c_ext = float(y_bhi) - 1.618 * leg
        if c_eq > 20000 and not _near_his_level(c_eq, his_lv):
            mine.append(
                {
                    "level": c_eq,
                    "label": _self_pred_label(c_eq, "官方⑤→A等長C"),
                    "basis": "加權官方轉折：B高−(⑤高−A低)",
                    "color": "#ffcc80",
                    "source": "mine",
                    "kind": "equal_c",
                }
            )
        if c_ext > 20000 and not _near_his_level(c_ext, his_lv):
            mine.append(
                {
                    "level": c_ext,
                    "label": _self_pred_label(c_ext, "官方1.618延伸"),
                    "basis": "加權官方轉折：B高−1.618×(⑤高−A低)",
                    "color": "#ffb74d",
                    "source": "mine",
                    "kind": "ext1618",
                }
            )
    # 2) 近窗官方低／最大量日低（價離舊區才當候選撐）
    n = len(lows)
    if n >= 8:
        win = list(range(max(0, n - 20), n))
        swing_lo = min(float(lows[i]) for i in win)
        if swing_lo < yn - 80 and not _near_his_level(swing_lo, his_lv):
            mine.append(
                {
                    "level": swing_lo,
                    "label": _self_pred_label(swing_lo, "近窗官方低"),
                    "basis": "近20根加權官方最低",
                    "color": "#ffe082",
                    "source": "mine",
                    "kind": "swing_lo",
                }
            )
        if any(float(vols[i] or 0) > 0 for i in win):
            i_vmax = max(win, key=lambda i: float(vols[i] or 0))
            vmax_lo = float(lows[i_vmax])
            md = _md(bars[i_vmax].get("date")) if i_vmax < len(bars) else ""
            if vmax_lo < yn - 40 and not _near_his_level(vmax_lo, his_lv):
                mine.append(
                    {
                        "level": vmax_lo,
                        "label": _self_pred_label(vmax_lo, f"{md}最大量低" if md else "最大量低"),
                        "basis": f"官方最大量日低{_px(vmax_lo)}" + (f"（{md}）" if md else ""),
                        "color": "#ffd54f",
                        "source": "mine",
                        "kind": "vmax_lo",
                    }
                )
    # 3) 隔夜氣氛（只當偏壓句，不准發明加權假目標價）
    # 順位：大台夜 vs 日 → 電子夜 → 費半／納指／TSM（庫內 us_overnight／us_note）
    bias_bits: List[str] = []
    tx_vs = None
    te_pct = None
    try:
        fut = pack.get("_fut_snap") or {}
        if not fut and db_path:
            fut = _futures_day_night(db_path)
        tx_vs = fut.get("tx_night_vs_day_pct")
        te_pct = fut.get("te_night_pct")
    except Exception:
        fut = {}
    if tx_vs is not None:
        try:
            g = float(tx_vs)
            if g <= -1.0:
                bias_bits.append(f"大台夜vs日{g:+.2f}%→開盤偏壓")
            elif g >= 1.0:
                bias_bits.append(f"大台夜vs日{g:+.2f}%→開盤偏多")
            else:
                bias_bits.append(f"大台夜vs日{g:+.2f}%")
        except (TypeError, ValueError):
            pass
    if te_pct is not None:
        try:
            t = float(te_pct)
            if t <= -1.5:
                bias_bits.append(f"電子夜{t:+.2f}%→電子偏弱")
            elif t >= 1.5:
                bias_bits.append(f"電子夜{t:+.2f}%→電子偏強")
        except (TypeError, ValueError):
            pass
    us_note = str(pack.get("us_note") or "")
    sox_pct = ixic_pct = tsm_pct = vix = None
    m = re.search(r"費半([+\-]?\d+(?:\.\d+)?)%", us_note)
    if m:
        try:
            sox_pct = float(m.group(1))
        except ValueError:
            sox_pct = None
    m2 = re.search(r"納指([+\-]?\d+(?:\.\d+)?)%", us_note)
    if m2:
        try:
            ixic_pct = float(m2.group(1))
        except ValueError:
            ixic_pct = None
    # 完整 us_overnight 列（四大／龍頭／VIX／油匯）— 有才用
    if db_path:
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            try:
                row = conn.execute(
                    "SELECT sox_pct, ixic_pct, spx_pct, dji_pct, vix, tsm_pct, nvda_pct, "
                    "nq_f_pct, payload FROM us_overnight ORDER BY as_of DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
            if row:
                sox_pct = sox_pct if sox_pct is not None else (
                    float(row[0]) if row[0] is not None else None
                )
                ixic_pct = ixic_pct if ixic_pct is not None else (
                    float(row[1]) if row[1] is not None else None
                )
                vix = float(row[4]) if row[4] is not None else None
                tsm_pct = float(row[5]) if row[5] is not None else None
                try:
                    payload = json.loads(row[8] or "{}")
                except Exception:
                    payload = {}
                brent = payload.get("brent_pct")
                usdtwd = payload.get("usdtwd_pct")
                if vix is not None and vix >= 30:
                    bias_bits.append(f"VIX{vix:.1f}→系統險")
                elif vix is not None and vix >= 25:
                    bias_bits.append(f"VIX{vix:.1f}→偏險")
                if tsm_pct is not None and abs(tsm_pct) >= 2.0:
                    bias_bits.append(f"TSM{tsm_pct:+.2f}%")
                if sox_pct is not None and sox_pct <= -2.0:
                    bias_bits.append(f"費半{sox_pct:+.2f}%→偏壓")
                elif sox_pct is not None and sox_pct >= 2.0:
                    bias_bits.append(f"費半{sox_pct:+.2f}%→偏多")
                elif ixic_pct is not None and ixic_pct <= -1.5:
                    bias_bits.append(f"納指{ixic_pct:+.2f}%→風險收斂")
                if brent is not None and abs(float(brent)) >= 2.0:
                    bias_bits.append(f"Brent{float(brent):+.2f}%")
                if usdtwd is not None and abs(float(usdtwd)) >= 0.3:
                    bias_bits.append(f"美金台幣{float(usdtwd):+.2f}%")
        except Exception:
            logger.debug("我估讀 us_overnight 略過", exc_info=True)
    us_bias = "；".join(bias_bits[:5])
    # 去重：同價只留一筆我估
    kept: List[Dict[str, Any]] = []
    seen: List[float] = []
    for row in sorted(mine, key=lambda d: float(d["level"]), reverse=True):
        lv = float(row["level"])
        if any(abs(lv - s) < 40 for s in seen):
            continue
        seen.append(lv)
        kept.append(row)
        if len(kept) >= 4:
            break
    refs = [
        "隔夜A：大台夜／電子夜／TSM／SOX／NQ（開盤氣氛；盤中≠延續）",
        "價位：加權官方轉折等長／1.618／近窗低／最大量低",
        "文獻：TX夜比美四大更直接；美股資訊多在跳空用完",
    ]
    if us_bias:
        refs.insert(0, us_bias)
    return {
        "mine": kept,
        "his_aux": his_notes[:6],
        "us_bias": us_bias,
        "refs": refs,
        "note": "｜".join(
            [f"{r['label']}" for r in kept[:3]]
            + ([us_bias] if us_bias else [])
        )[:280],
    }


def _c_forecast_tip(
    *,
    i_now: int,
    y_now: float,
    y_ref: float,
    lows: Sequence[float],
    anchors: Sequence[float] = (45546.0, 44210.0),
) -> Dict[str, Any]:
    """C 段預估虛線端點：只指向他說過的下一錨，不准發明新價。

    錨梯＝_tw_tip_anchors（他最新點位高→低；沒點才退回 45546→44210）。
    端點標＝『飆預測』（與右欄／青帶同一套）；不准再寫多餘的「預估↓同價」。
    今已低於錨才用『預估↓續弱』（沒有具體他說價可標）。
    """
    fut_x = float(i_now + max(3, 4))
    chain = [float(x) for x in (anchors or (45546.0, 44210.0)) if x]
    if not chain:
        chain = [45546.0, 44210.0]
    anchor_y: Optional[float] = None
    fut_y = float(chain[-1])
    lab = _biaoke_pred_label(fut_y, _level_break_tag(fut_y, lows))
    for a in chain:
        tag = _level_break_tag(a, lows)
        if tag != "已破":
            fut_y = float(a)
            anchor_y = float(a)
            lab = _biaoke_pred_label(a, tag)
            break
    else:
        # 全破：仍標最後一錨狀態
        fut_y = float(chain[-1])
        anchor_y = float(chain[-1])
        lab = _biaoke_pred_label(fut_y, _level_break_tag(fut_y, lows))
    # 今已低於該錨：略往下延伸示意續弱，仍不發明具體新價標
    if float(y_now) <= float(fut_y) + 1.0:
        drop = max(abs(float(y_ref) - float(y_now)) * 0.12, 180.0)
        fut_y = float(y_now) - drop
        lab = "預估↓續弱"
        anchor_y = None
    return {
        "fut_x": fut_x,
        "fut_y": float(fut_y),
        "label": lab,
        "anchor_y": anchor_y,
        "note": "虛線＝預估未來（會改・非買訊）",
    }


def _paint_c_forecast(
    ax: Any,
    *,
    i_now: int,
    y_now: float,
    y_ref: float,
    lows: Sequence[float],
    fp: Any,
    n: int,
    show_label: bool = True,
    keep_left_of_right: bool = False,
    anchors: Sequence[float] = (45546.0, 44210.0),
) -> Dict[str, Any]:
    """在今之後畫預估虛線＋標；回傳 tip 方便調 xlim。

    keep_left_of_right＝True 時標停在右欄左側，不准跟右價標互壓。
    """
    tip = _c_forecast_tip(
        i_now=i_now, y_now=y_now, y_ref=y_ref, lows=lows, anchors=anchors
    )
    fut_x, fut_y = float(tip["fut_x"]), float(tip["fut_y"])
    ax.plot(
        [i_now, fut_x],
        [y_now, fut_y],
        color="#ea80fc",
        lw=1.55,
        ls=(0, (4, 2)),
        alpha=0.8,
        zorder=6,
    )
    ax.scatter([fut_x], [fut_y], s=28, c="#ea80fc", zorder=7, edgecolors="#fff", linewidths=0.4)
    lab_y = float(fut_y)
    if show_label:
        # 預估端標釘在端點同價；遠窗停右欄左側，不准壓右價標、不准漂到端點下方
        if keep_left_of_right:
            _pin_pivot_name(
                ax,
                min(float(fut_x), float(n) - 2.4),
                lab_y,
                str(tip["label"]),
                "#ea80fc",
                fp,
                side="left",
                n=n,
                pad_x=0.45,
                fontsize=9,
            )
        else:
            _pin_pivot_name(
                ax,
                float(fut_x),
                lab_y,
                str(tip["label"]),
                "#ea80fc",
                fp,
                side="right",
                n=n,
                pad_x=0.45,
                fontsize=9,
            )
    tip["xlim_right"] = max(float(n) + 1.2, fut_x + 2.2)
    tip["lab_y"] = lab_y
    return tip


def _wave_now_ladder(pack: Optional[Dict[str, Any]] = None, *, blob: str = "") -> Dict[str, Any]:
    """他說『現在走到哪一層』：大→小一條龍（預估會改；非買訊）。

    回傳 steps／chain／now／one_line，給話筒文字、圖題、caption 共用。
    """
    pack = pack or {}
    text = " ".join(
        str(x or "")
        for x in (
            blob,
            pack.get("thesis"),
            pack.get("snippet"),
            pack.get("wait_struct"),
        )
    )
    his = _his_micro_degree(text)
    deg = str(his.get("degree") or "").strip()
    thesis = str(pack.get("thesis") or text)
    # 大結構跟他鎖的：A底→B反彈→C；不准寫成「五波升完再ABC」讓人把7/29→四萬九當上升⑤
    steps: List[str] = ["大A底7/29", "大B反彈", "大C進行中"]
    if deg in ("C3-3-1", "C3-3-2", "C3-3-3", "C3-3-4"):
        steps.extend(["C3-3主跌", deg])
    elif "3→4" in thesis:
        steps.extend(["C3-3主跌", "C3-3-4"])
    elif deg.startswith("C3-3") or ("C3-3" in thesis and "橫台" not in thesis):
        steps.append("C3-3主跌")
    elif "橫台" in thesis or "中繼" in thesis:
        steps.append("C內橫台中繼")
    elif "主跌" in thesis:
        steps.append("C內主跌")
    elif deg == "C3":
        steps.append("C3")
    now = steps[-1]
    chain = " → ".join(steps)
    # 層級文字對齊他文日（thesis_as_of）；柱日是圖軸，不准蓋題旨日。
    # 話筒只用「題旨日 M/D」，不准寫英文 as_of。
    as_of = _ymd(
        pack.get("thesis_as_of") or pack.get("chart_as_of") or pack.get("as_of") or ""
    )
    if len(as_of) == 8:
        day_zh = f"{int(as_of[4:6])}/{int(as_of[6:8])}"
        day_bit = f"題旨日 {day_zh}"
    else:
        day_zh = ""
        day_bit = ""
    return {
        "steps": steps,
        "chain": chain,
        "now": now,
        "degree": deg,
        "day_zh": day_zh,
        "day_bit": day_bit,
        "one_line": f"現在走到：{chain}",
        "now_line": (
            f"落在「{now}」"
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        ),
        "teach_box": (
            f"現在走到（大→小）\n"
            f"{chain}\n"
            f"落在「{now}」"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        ),
    }


def _twii_abc_anchors(
    bars: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """C 段內早段震盪錨（10/6→10/13→10/14→10/15）——只供 C 內細讀。

    不准標成大A／大B。大結構一律 `_twii_macro_wave_anchors`：
    ⑤＝4/1→6/23｜A＝6/23→7/29｜B＝7/29→10/6｜C＝10/6→今。
    """
    i5 = _bar_index_by_ymd(bars, "20261006")
    i_alow = _bar_index_by_ymd(bars, "20261013")
    i_bhi = _bar_index_by_ymd(bars, "20261014")
    i_c = _bar_index_by_ymd(bars, "20261015")
    if i5 is None or i_alow is None or i_bhi is None or i_c is None:
        return None
    if not (i5 < i_alow < i_bhi <= i_c):
        return None
    highs = [float(r.get("high") or 0) for r in bars]
    lows = [float(r.get("low") or 0) for r in bars]
    closes = [float(r.get("close") or 0) for r in bars]
    y5, y_alow, y_bhi = highs[i5], lows[i_alow], highs[i_bhi]
    if y_bhi >= y5:
        return None
    return {
        "i5": i5,
        "i_alow": i_alow,
        "i_bhi": i_bhi,
        "i_c": i_c,
        "i_now": len(bars) - 1,
        "y5": y5,
        "y_alow": y_alow,
        "y_bhi": y_bhi,
        "y_now": closes[-1],
        "highs": highs,
        "lows": lows,
        "closes": closes,
    }


def _twii_macro_wave_anchors(
    bars: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """大結構（三張教具＋八浪縮圖同一套，不准另編）：

    ⑤起4/1→⑤末6/23｜A起＝⑤末→A末7/29｜B起＝A末→B末10/6｜C起＝B末峰（確認10/15）→今。
    今已在大C；C內上下＝細浪／震盪，不准再叫成大A／大B。
    """
    # 注意：索引 0 是合法（窗左緣＝⑤起日）；不准用 `or` 把 0 當缺值
    i5s = _bar_index_by_ymd(bars, "20260401")
    if i5s is None:
        i5s = _bar_index_by_ymd(bars, "20260331")
    i5e = _bar_index_by_ymd(bars, "20260623")
    i_alow = _bar_index_by_ymd(bars, "20260729")
    if i_alow is None:
        i_alow = _bar_index_by_ymd(bars, "20260728")
    i_bend = _bar_index_by_ymd(bars, "20261006")
    i_c = _bar_index_by_ymd(bars, "20261015")
    if i_c is None:
        i_c = _bar_index_by_ymd(bars, "20261014")
    if None in (i5s, i5e, i_alow, i_bend, i_c):
        return None
    if not (i5s < i5e <= i_alow < i_bend <= i_c):
        return None
    highs = [float(r.get("high") or 0) for r in bars]
    lows = [float(r.get("low") or 0) for r in bars]
    closes = [float(r.get("close") or 0) for r in bars]
    return {
        "i5_start": int(i5s),
        "i5_end": int(i5e),
        # A起＝⑤末；B起＝A末（大A底）
        "i_a_start": int(i5e),
        "i_alow": int(i_alow),
        "i_b_start": int(i_alow),
        "i_b_end": int(i_bend),
        "i_c": int(i_c),
        "i_now": len(bars) - 1,
        "y5_start": float(lows[i5s]),
        "y5_end": float(highs[i5e]),
        "y_a_start": float(highs[i5e]),
        "y_alow": float(lows[i_alow]),
        "y_b_start": float(lows[i_alow]),
        "y_b_end": float(highs[i_bend]),
        "y_now": float(closes[-1]),
        "highs": highs,
        "lows": lows,
        "closes": closes,
    }


def _macro_wave_calendar_line() -> str:
    """三張＋縮圖共用浪階日曆字（Asia/Taipei 交易日）。"""
    return "⑤＝4/1→6/23｜A＝6/23→7/29｜B＝7/29→10/6｜C＝10/6→今（確認10/15）"


def _eight_wave_now_key(pack: Optional[Dict[str, Any]] = None) -> str:
    """從層級鏈取八浪縮圖此刻鍵（大結構落在修正波 C）。

    C3-3-x 細碼必須完整保留給閃折①～⑤，不准裁成裸 C。
    """
    now = str((_wave_now_ladder(pack) or {}).get("now") or "").strip()
    if not now:
        return "C"
    u = now.upper().replace(" ", "")
    m = re.search(r"C3-3-[1-5]", now, flags=re.I)
    if m:
        return m.group(0)
    if "C3-3" in u or u.startswith("C"):
        return "C"
    if "⑤" in now or u.startswith("5"):
        return "⑤"
    if u.startswith("A") or "大A" in now:
        return "A"
    if u.startswith("B") or "大B" in now:
        return "B"
    return "C"


def _c_flash_step(now_key: str) -> int:
    """大C 內微觀閃折此刻落在①～⑤哪一尖（對齊 C3-3-x）。"""
    nk = str(now_key or "").upper().replace(" ", "")
    if "C3-3-4" in nk or nk.endswith("-4") or "3-3-4" in nk:
        return 4
    if "C3-3-3" in nk or nk.endswith("-3") or "3-3-3" in nk:
        return 3
    if "C3-3-2" in nk or nk.endswith("-2") or "3-3-2" in nk:
        return 2
    if "C3-3-1" in nk or nk.endswith("-1") or "3-3-1" in nk:
        return 1
    if "C3-3" in nk or nk.startswith("C3"):
        return 3
    return 4


def _c_teach_flash_pivots(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    i_bhi: int,
    i_c: int,
    i_now: int,
    c_sub: Optional[Dict[str, Any]] = None,
) -> List[Tuple[int, float, str]]:
    """超近主圖日K小波＝縮圖閃折同一套官方柱錨：B→①→②→③→④→⑤。

    點位只取已收柱高低，不准發明價。①＝C起日低；②＝其後反彈高；
    ③＝②後、④日前最低（不准跟④同日——日K若先高後低會把③→④時間畫反）；
    ④＝他60分對得上的 c4 高；⑤＝今收（進行中）。左右圖同序同價。
    """
    out: List[Tuple[int, float, str]] = []
    n = min(len(highs), len(lows), len(closes))
    if not (0 <= i_bhi < i_c <= i_now < n):
        return out
    y_b = float(highs[i_bhi])
    out.append((int(i_bhi), y_b, "B"))
    # ①：C 起確認日低（第一段急殺）
    i1 = int(i_c)
    y1 = float(lows[i1])
    out.append((i1, y1, "①"))
    # ④候選：c4 細高（他60分對得上）——先定④，③才不會跟它搶同一根
    i4: Optional[int] = None
    y4: Optional[float] = None
    if isinstance(c_sub, dict) and c_sub.get("ok"):
        try:
            i4c = int(c_sub["i_c4_hi"])
            y4c = float(c_sub["y_c4"])
            if i1 < i4c <= i_now:
                i4, y4 = i4c, y4c
        except (TypeError, ValueError, KeyError):
            i4, y4 = None, None
    # ②：①後、④前反彈最高
    i2_hi = (i4 - 1) if i4 is not None and i4 > i1 + 1 else i_now
    if i2_hi <= i1:
        i2_hi = min(i1 + 1, i_now)
    i2 = (
        max(range(i1 + 1, i2_hi + 1), key=lambda i: float(highs[i]))
        if i1 < i2_hi
        else min(i1 + 1, i_now)
    )
    y2 = float(highs[i2])
    out.append((int(i2), y2, "②"))
    # ③：②後～④日前（不含④日）最低。10/22 先高後低收在低＝④後已進⑤，不准當③
    if i4 is not None and i4 > i2:
        i3 = min(range(i2, i4), key=lambda i: float(lows[i]))
    elif i2 < i_now:
        i3 = min(range(i2, i_now + 1), key=lambda i: float(lows[i]))
    else:
        i3 = i2
    y3 = float(lows[i3])
    out.append((int(i3), y3, "③"))
    # ④：c4；若無則③後、今前反彈高（仍不准與③同日倒畫）
    if i4 is None or y4 is None:
        if i3 < i_now:
            i4 = max(range(i3 + 1, i_now + 1), key=lambda i: float(highs[i]))
            y4 = float(highs[i4])
        else:
            i4, y4 = i3, float(highs[i3])
    out.append((int(i4), float(y4), "④"))
    # ⑤：今收（進行中；④後已走的殺段歸⑤，未走完）
    out.append((int(i_now), float(closes[i_now]), "⑤"))
    return out


def _flash_spec_from_pivots(
    pivots: Sequence[Tuple[int, float, str]],
) -> List[Tuple[float, float, str]]:
    """把官方柱錨換成縮圖 (t, drop, lab)；t／drop 都對真窗比例，不准另編振幅。"""
    if len(pivots) < 2:
        return []
    i0, y0, _ = pivots[0]
    iN, yN, _ = pivots[-1]
    span_i = max(1, int(iN) - int(i0))
    # 跌幅基準：B 高 → ⑤（若⑤高於B則用窗內最低）
    y_lo = min(float(y) for _i, y, _lab in pivots)
    drop_span = max(1.0, float(y0) - float(y_lo))
    spec: List[Tuple[float, float, str]] = []
    raw: List[Tuple[float, float, str, int]] = []
    for i, y, lab in pivots:
        t = (int(i) - int(i0)) / float(span_i)
        drop = (float(y0) - float(y)) / drop_span
        if drop < 0.0:
            drop = 0.0
        if drop > 1.0:
            drop = 1.0
        if t < 0.0:
            t = 0.0
        if t > 1.0:
            t = 1.0
        raw.append((t, drop, str(lab), int(i)))
    # 同日高低（③低④高）在縮圖略錯開 t，否則垂直疊標讀不出閃折
    for j in range(1, len(raw)):
        t0, d0, lab0, i_a = raw[j - 1]
        t1, d1, lab1, i_b = raw[j]
        if i_a == i_b and abs(t1 - t0) < 1e-9:
            raw[j - 1] = (max(0.0, t0 - 0.035), d0, lab0, i_a)
            raw[j] = (min(1.0, t1 + 0.035), d1, lab1, i_b)
    spec = [(t, d, lab) for t, d, lab, _i in raw]
    # 端點鎖死，避免浮點把 B／⑤ 漂離黃框角
    spec[0] = (0.0, 0.0, spec[0][2])
    spec[-1] = (1.0, min(1.0, max(0.0, (float(y0) - float(yN)) / drop_span)), spec[-1][2])
    return spec


def _style_teach_mid_panel(ax: Any) -> None:
    """中排說明／八浪格：暖墨面板＋琥珀左緣，跟 HUD 同一語言。"""
    if ax is None:
        return
    ax.set_facecolor(_LIVE_PANEL)
    ax.patch.set_alpha(1.0)
    ax.patch.set_visible(True)
    for side, sp in ax.spines.items():
        sp.set_visible(True)
        sp.set_color(_LIVE_ACCENT if side == "left" else _LIVE_PANEL_EDGE)
        sp.set_linewidth(1.35 if side == "left" else 0.95)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)


def _paint_teach_eight_wave_legend(
    ax: Any,
    *,
    fp: Any,
    now_key: str,
    pack: Optional[Dict[str, Any]] = None,
    detail: bool = False,
    c_flash: bool = False,
) -> None:
    """中排左：對位讀法（色碼＋此刻）；右格才是八浪小圖。"""
    if ax is None:
        return
    _style_teach_mid_panel(ax)
    ladder = _wave_now_ladder(pack or {})
    now = str(now_key or ladder.get("now") or "C").strip() or "C"
    one = str(ladder.get("one_line") or "").strip()
    if len(one) > 40:
        one = one[:39] + "…"
    lines = [
        ("八浪對位・怎麼讀", _LIVE_ACCENT, 11),
        (one or "大結構對齊教科書八浪", _LIVE_TEXT, 9),
        (f"此刻＝{now}", "#ffd54f", 10),
    ]
    if detail and not c_flash:
        lines.append(("右圖黃框＝落在哪一段", "#ffe082", 8))
    if c_flash:
        lines.append(("右圖黃框＝C內①～⑤閃折", "#ffe082", 8))
    lines.append(("小圖＝結構對位・不是價位", _LIVE_MUTED, 8))
    y = 0.94
    for text, col, fs in lines:
        ax.text(
            0.05,
            y,
            text,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontproperties=fp(int(fs), "bold"),
            color=col,
            zorder=3,
        )
        y -= 0.13 if fs >= 10 else 0.11
    # 色碼樣本列：填滿左格下半，一眼對上右圖線色
    swatches = [
        ("#40c4ff", "━━ 1→5 推進"),
        ("#ff8a80", "━━ A 修正"),
        ("#ffd54f", "┅┅ B 反彈"),
        ("#ea80fc", "━━ C 進行"),
    ]
    y = min(y, 0.42)
    for col, lab in swatches:
        ax.text(
            0.05,
            y,
            lab,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontproperties=fp(9, "bold"),
            color=col,
            zorder=4,
        )
        y -= 0.10


def _paint_eight_wave_inset(
    fig: Any,
    *,
    fp: Any,
    now_key: str = "C",
    detail: bool = False,
    c_flash: bool = False,
    flash_pivots: Optional[Sequence[Tuple[int, float, str]]] = None,
    rect: Sequence[float] = (0.72, 0.62, 0.26, 0.28),
    ax: Any = None,
    title: str = "八浪對位",
) -> None:
    """三張教具共用：教科書八浪縮圖；detail 框此刻；c_flash＝超近在C內畫下殺閃折①～⑤。

    遠／近／超近一律傳中排右格 `ax`：小圖吃滿右格，不准整列漂浮小卡、
    不准 set_visible(False) 讓 tight 裁列後蓋回 K。
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    if ax is None:
        ax = fig.add_axes(list(rect))
    # 不透明暖墨底＋琥珀邊（右格本身就是小圖卡）
    ax.set_facecolor("#14110e")
    ax.patch.set_alpha(1.0)
    ax.patch.set_visible(True)
    ax.set_navigate(False)
    for side, sp in ax.spines.items():
        sp.set_visible(True)
        sp.set_color(_LIVE_ACCENT if side in ("left", "top") else "#4a3f34")
        sp.set_linewidth(1.85 if side in ("left", "top") else 1.25)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    # 簡化八浪折線；色碼跟主圖一致：藍⑤／粉A／金虛B／紫C
    # 鐵律：起→1…5→A→B→C 的 x 嚴格遞增；A 必須在黃框（B→C）左側外
    if c_flash:
        # 左：推進；中：A低→B反彈（都在黃框外）；右黃框：只裝 B→C 緩坡閃折
        pts = [
            (0.00, 0.20),
            (0.07, 0.38),  # 1
            (0.12, 0.28),  # 2
            (0.22, 0.72),  # 3
            (0.28, 0.52),  # 4
            (0.36, 0.88),  # 5
            (0.44, 0.40),  # A（黃框外・左下）
            (0.54, 0.66),  # B（黃框左緣＝C起）
            (0.97, 0.38),  # C 緩下末
        ]
    else:
        pts = [
            (0.0, 0.22),
            (0.10, 0.42),  # 1
            (0.18, 0.32),  # 2
            (0.36, 0.78),  # 3
            (0.46, 0.58),  # 4
            (0.58, 0.92),  # 5
            (0.72, 0.48),  # A
            (0.82, 0.68),  # B
            (0.98, 0.18),  # C
        ]
    col_imp, col_a, col_b, col_c = "#40c4ff", "#ff8a80", "#ffd54f", "#ea80fc"
    # 推進1→5（藍）
    ax.plot(
        [pts[i][0] for i in range(0, 6)],
        [pts[i][1] for i in range(0, 6)],
        color=col_imp,
        lw=1.85,
        zorder=3,
    )
    # 修正A（粉）
    ax.plot(
        [pts[5][0], pts[6][0]],
        [pts[5][1], pts[6][1]],
        color=col_a,
        lw=1.85,
        zorder=3,
    )
    # 修正B（金虛＝主圖大B）
    ax.plot(
        [pts[6][0], pts[7][0]],
        [pts[6][1], pts[7][1]],
        color=col_b,
        lw=1.95,
        ls=(0, (5, 1.6)),
        zorder=3,
    )
    # 修正C：無閃折時畫紫實線；有閃折時只留極淡底軸，主路徑改細閃（避免雙線錯位）
    if c_flash:
        ax.plot(
            [pts[7][0], pts[8][0]],
            [pts[7][1], pts[8][1]],
            color=col_c,
            lw=2.6,
            alpha=0.22,
            zorder=2.5,
            solid_capstyle="round",
        )
    else:
        ax.plot(
            [pts[7][0], pts[8][0]],
            [pts[7][1], pts[8][1]],
            color=col_c,
            lw=1.85,
            zorder=3,
        )
    labs = ["", "1", "2", "3", "4", "5", "A", "B", "C"]
    pt_cols = [
        "#90a4ae",
        col_imp,
        col_imp,
        col_imp,
        col_imp,
        col_imp,
        col_a,
        col_b,
        col_c,
    ]
    key_map = {
        "5": 5,
        "⑤": 5,
        "A": 6,
        "B": 7,
        "C": 8,
        "C3": 8,
        "C3-3": 8,
        "C3-3-4": 8,
        "C3-3-3": 8,
    }
    nk = str(now_key or "C")
    hi = 8
    for k, v in key_map.items():
        if nk == k or nk.upper().startswith(str(k).upper()):
            hi = v
            break
    # 高亮此刻：只墊底層光暈（z 低於色線），不准金光蓋掉粉A／金虛B／紫C
    if 1 <= hi < len(pts) and not c_flash:
        seg_x = [pts[hi - 1][0], pts[hi][0]]
        seg_y = [pts[hi - 1][1], pts[hi][1]]
        ax.plot(
            seg_x,
            seg_y,
            color="#ffe082",
            lw=6.0,
            alpha=0.28,
            zorder=2,
            solid_capstyle="round",
        )
    for i, (x, y) in enumerate(pts):
        if i == 0:
            ax.text(
                x - 0.01,
                y - 0.08,
                "起",
                fontproperties=fp(7, "bold"),
                color="#90a4ae",
                ha="center",
                va="top",
                zorder=5,
            )
            continue
        # 超近閃折：C 端點讓給微觀⑤；B 標在黃框左緣外上方，不准跟①搶位
        if c_flash and i == 8:
            continue
        col = pt_cols[i]
        ax.scatter(
            [x],
            [y],
            s=22 if not detail else 30,
            c=col,
            zorder=5,
            edgecolors="#fff",
            linewidths=0.4,
        )
        lab_dx, lab_dy = 0.0, (0.07 if i in (1, 3, 5, 7) else -0.09)
        if c_flash and i == 6:  # A：標在點左下，遠離黃框
            lab_dx, lab_dy = -0.02, -0.08
        if c_flash and i == 7:  # B：標在點左上，黃框外
            lab_dx, lab_dy = -0.02, 0.08
        ax.text(
            x + lab_dx,
            y + lab_dy,
            labs[i],
            fontproperties=fp(8 if not detail else 9, "bold"),
            color=col,
            ha="center",
            va="center",
            zorder=6,
        )
    # 超近：黃框只包 B→C；閃折＝主圖同一套官方柱錨（flash_pivots），不准另編點
    # 真窗：B高→①C起日低→②反彈高→③更深低→④c4反彈→⑤今收
    flash_pts: List[Tuple[float, float]] = []
    flash_step = 0
    if c_flash and hi >= 8:
        bx, by = pts[7]
        cx, cy = pts[8]
        dx, dy = cx - bx, cy - by
        # 優先用主圖傳入的官方柱錨；缺才退回近似比例（仍須六點）
        flash_spec = _flash_spec_from_pivots(list(flash_pivots or ()))
        if len(flash_spec) < 6:
            flash_spec = [
                (0.00, 0.00, "B"),
                (0.10, 0.59, "①"),
                (0.20, 0.40, "②"),
                (0.40, 0.75, "③"),
                (0.60, 0.45, "④"),
                (1.00, 1.00, "⑤"),
            ]
        for t, drop, _lab in flash_spec:
            flash_pts.append((bx + dx * t, by + dy * drop))
        flash_pts[0] = (bx, by)
        flash_pts[-1] = (cx, cy)
        fx = [p[0] for p in flash_pts]
        fy = [p[1] for p in flash_pts]
        ax.plot(fx, fy, color="#0b0f14", lw=2.35, zorder=6.1, solid_capstyle="round")
        ax.plot(fx, fy, color="#ffffff", lw=1.45, zorder=6.2, solid_capstyle="round")
        ax.plot(fx, fy, color="#ff5252", lw=1.05, zorder=6.3, solid_capstyle="round")
        flash_step = _c_flash_step(nk)
        for j, ((x, y), (_t, _d, lab)) in enumerate(zip(flash_pts, flash_spec)):
            if lab == "B":
                continue
            step_i = j
            is_now = step_i == flash_step
            ax.scatter(
                [x],
                [y],
                s=42 if is_now else 26,
                c="#ffd54f" if is_now else "#ffffff",
                zorder=7,
                edgecolors="#111111",
                linewidths=0.55,
            )
            ax.text(
                x + 0.014,
                y + (0.05 if lab in ("②", "④") else -0.055),
                lab,
                fontproperties=fp(8 if is_now else 7, "bold"),
                color="#ffd54f" if is_now else "#ffffff",
                ha="left",
                va="center",
                zorder=8,
            )
        if 1 <= flash_step < len(flash_pts):
            sx, sy = flash_pts[flash_step]
            ax.scatter(
                [sx],
                [sy],
                s=84,
                facecolors="none",
                edgecolors="#ffd54f",
                linewidths=1.7,
                zorder=9,
            )
    # 此刻框：detail＝近／超近要框選＋註；遠窗只圈點
    if 0 <= hi < len(pts):
        x0, y0 = pts[hi]
        x_l = pts[max(0, hi - 1)][0] - 0.05
        x_r = min(1.04, x0 + 0.10)
        y_b = min(y0, pts[max(0, hi - 1)][1]) - 0.12
        y_t = max(y0, pts[max(0, hi - 1)][1]) + 0.14
        if c_flash and flash_pts:
            # 黃框只包閃折（自 B 起），不准把 A 包進去造成「B→A→①」錯位感
            xs_f = [p[0] for p in flash_pts]
            ys_f = [p[1] for p in flash_pts]
            x_l = max(pts[7][0] - 0.02, min(xs_f) - 0.03)
            x_r = max(xs_f) + 0.06
            y_b = min(ys_f) - 0.08
            y_t = max(ys_f) + 0.10
        if detail:
            ax.add_patch(
                plt.Rectangle(
                    (x_l, y_b),
                    x_r - x_l,
                    y_t - y_b,
                    fill=False,
                    ec="#ffd54f",
                    lw=2.05,
                    zorder=7,
                )
            )
            tip = f"此刻＝{nk}"
            if c_flash and flash_step:
                tip = f"此刻＝{nk}・閃①～⑤之{flash_step}"
            ax.text(
                (x_l + x_r) / 2,
                min(1.05, y_t + 0.02),
                tip,
                fontproperties=fp(8, "bold"),
                color="#ffd54f",
                ha="center",
                va="bottom",
                zorder=8,
            )
            # 細註：大結構對位（⑤＝4/1→6/23；今在修正 C）
            note = _macro_wave_calendar_line()
            if c_flash:
                # 大結構同上；黃框內＝C內震盪①～⑤（＝主圖橙線）
                note = "大＝⑤A B C｜框內＝C震盪①～⑤"
            ax.text(
                0.50,
                0.98,
                note,
                fontproperties=fp(7, "bold"),
                color="#ffe082",
                ha="center",
                va="top",
                transform=ax.transAxes,
                zorder=8,
            )
        else:
            ax.scatter(
                [x0],
                [y0],
                s=64,
                facecolors="none",
                edgecolors="#ffd54f",
                linewidths=1.7,
                zorder=7,
            )
            ax.text(
                x0,
                y0 - 0.14,
                f"今={nk}",
                fontproperties=fp(7, "bold"),
                color="#ffd54f",
                ha="center",
                va="top",
                zorder=8,
            )
    # 折線吃滿框：少留黑空，字／點仍不貼邊
    ax.set_xlim(-0.02, 1.03)
    ax.set_ylim(0.01, 1.06)
    ax.set_title(
        title,
        fontproperties=fp(11, "bold"),
        color=_LIVE_ACCENT,
        pad=4,
        loc="left",
    )
    foot = "藍＝1→5｜粉＝A｜金虛＝B｜紫＝C"
    if c_flash:
        foot = "⑤AB框外對齊｜B末→C內①…⑤｜金圈＝此刻"
    ax.text(
        0.02,
        0.02,
        foot,
        fontproperties=fp(8, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
        transform=ax.transAxes,
    )


def _sox_abc_anchors_on_axis(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    i5_hint: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """費半自己的⑤／A／B（索引＝加權月日對齊後的同一格）。

    時間軸與加權同一條月／日；轉折日不准抄加權 A／B。
    B 高必須低於⑤；A 後要有夠清楚反彈才成 B；C＝自 B 迄今（進行中）。
    """
    import math

    n = len(closes)
    if n < 8 or not (len(highs) == len(lows) == n):
        return None
    valid = [
        i
        for i in range(n)
        if math.isfinite(float(highs[i]))
        and math.isfinite(float(lows[i]))
        and math.isfinite(float(closes[i]))
        and float(highs[i]) > 0
        and float(lows[i]) > 0
    ]
    if len(valid) < 6:
        return None
    hint = int(i5_hint) if i5_hint is not None else None
    early_cut = max((hint + 5) if hint is not None else 0, int(n * 0.45))
    early = [i for i in valid if i <= early_cut]
    if not early:
        early = valid[: max(3, len(valid) // 2)]
    if hint is not None and hint in valid:
        max_early = max(float(highs[i]) for i in early)
        if float(highs[hint]) >= max_early * 0.995:
            i5 = hint
        else:
            i5 = max(early, key=lambda i: float(highs[i]))
    else:
        i5 = max(early, key=lambda i: float(highs[i]))
    y5 = float(highs[i5])
    best: Optional[Tuple[float, int, int, float, float]] = None
    for i_a in valid:
        if i_a <= i5 or i_a >= n - 2:
            continue
        ya = float(lows[i_a])
        after = [i for i in valid if i > i_a]
        if not after:
            continue
        cands = [i for i in after if float(highs[i]) < y5 * 0.999]
        if not cands:
            continue
        i_b = max(cands, key=lambda i: float(highs[i]))
        yb = float(highs[i_b])
        if yb <= ya * 1.02:
            continue
        seg = [i for i in valid if i5 < i <= i_b]
        if not seg:
            continue
        true_a = min(seg, key=lambda i: float(lows[i]))
        if true_a != i_a:
            continue
        depth = (y5 - ya) / y5
        if depth < 0.08:
            continue
        bounce = (yb - ya) / y5
        c_started = 1.0 if (i_b < n - 1 and float(closes[-1]) < yb * 0.995) else 0.5
        score = depth * 2.0 + bounce + c_started
        if best is None or score > best[0]:
            best = (score, i_a, i_b, ya, yb)
    if best is None:
        return None
    _, i_a, i_b, ya, yb = best
    return {
        "i5": int(i5),
        "i_alow": int(i_a),
        "i_bhi": int(i_b),
        "i_now": n - 1,
        "y5": y5,
        "y_alow": float(ya),
        "y_bhi": float(yb),
        "y_now": float(closes[-1]),
    }


def _paint_sox_thesis_preds(
    ax: Any,
    *,
    bars: Sequence[Dict[str, Any]],
    sox_o: Sequence[float],
    sox_h: Sequence[float],
    sox_l: Sequence[float],
    sox_c: Sequence[float],
    pack: Dict[str, Any],
    fp: Any,
    i_now: int,
    n: int,
    ymin: float,
    ymax: float,
    now_y: Optional[float] = None,
    now_lab: str = "",
    place: bool = True,
    x_col: Optional[float] = None,
    x_text_min: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """費半上欄：已破 A → 下一撐（青帶＋金K回測日）；右標＋虛線與加權同一欄。

    place=False 時只畫帶／金K，回傳右標列給呼叫端與加權同 x_col 再放。
    """
    import math

    preds = ((pack or {}).get("pred_levels") or {}).get("sox") or []
    if not preds:
        return []
    broken = next((r for r in preds if str(r.get("role") or "") == "A波低"), None)
    nxt = next((r for r in preds if str(r.get("role") or "") == "次回測"), None)
    y_hi = float(broken["level"]) if broken else None
    y_lo = float(nxt["level"]) if nxt else None
    # 青帶＝已破A低 → 次回測低（下一撐壓區）；跟加權青帶同一套讀法
    if y_hi is not None and y_lo is not None and y_hi > y_lo:
        ax.axhspan(y_lo, y_hi, facecolor="#4dd0e1", alpha=0.14, zorder=0.4)
        ax.text(
            0.012,
            0.96,
            f"青＝已破A{_px(y_hi)}→下一撐{_px(y_lo)}（4/28回測）",
            transform=ax.transAxes,
            fontproperties=fp(8, "bold"),
            color="#4dd0e1",
            ha="left",
            va="top",
            zorder=12,
            bbox=dict(
                boxstyle="round,pad=0.14", fc="#0b0f14", ec="#4dd0e1", lw=0.6, alpha=0.92
            ),
        )
    right: List[Dict[str, Any]] = []
    for row in preds:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        ref = _ymd(row.get("ref_ymd"))
        lab = str(row.get("label") or f"費{_px(lv)}")
        col = "#ffab40" if "已破" in str(row.get("tag") or lab) else "#4dd0e1"
        ii = _bar_index_by_ymd(bars, ref) if ref else None
        if ii is not None and 0 <= ii < len(sox_l):
            # 回測日金K＋豎導線（對齊大量圖：看得到那一根）
            oo = float(sox_o[ii]) if ii < len(sox_o) else lv
            hh = float(sox_h[ii]) if ii < len(sox_h) else lv
            ll = float(sox_l[ii]) if math.isfinite(float(sox_l[ii])) else lv
            cc = float(sox_c[ii]) if ii < len(sox_c) else lv
            _paint_special_candle(
                ax,
                int(ii),
                open_=oo,
                high=hh,
                low=ll,
                close=cc,
                color="#ffd54f",
                date_lab=ref,
                fp=fp,
            )
            ax.axvline(ii, color="#ffd54f", lw=0.85, ls=(0, (2, 2)), alpha=0.7, zorder=3)
        # 虛線起點＝回測／轉折日；沒索引才用末日
        x_note = int(ii) if ii is not None else max(int(n) - 1, 0)
        right.append(
            {
                "x": x_note,
                "y": lv,
                "text": lab[:26],
                "color": col,
            }
        )
    if now_y is not None:
        right.append(
            {
                "x": int(i_now) if i_now is not None else max(int(n) - 1, 0),
                "y": float(now_y),
                "text": (now_lab or f"費C今{_px(float(now_y))}")[:26],
                "color": "#ea80fc",
            }
        )
    if place and right:
        _place_live_right_labels(
            ax,
            right,
            n=n,
            ymin=ymin,
            ymax=ymax,
            fp=fp,
            level_dash=True,
            # 比例間距即可；不准絕對 floor 把真價標互擠掉或漂離
            min_gap=(ymax - ymin) * 0.08,
            x_col=x_col,
            x_text_min=x_text_min,
        )
    return right


def _tw_pred_right_notes(
    pack: Dict[str, Any],
    *,
    n: int,
    lows: Sequence[float],
    tip_skip: Optional[set] = None,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """加權右欄：他最新寫死點（44042／39384…）；有 ref 日則虛線從那根拉。"""
    skip = tip_skip or set()
    out: List[Dict[str, Any]] = []
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if round(lv, 1) in skip:
            continue
        tag = str(row.get("tag") or "")
        if tag in {"未到", "未破", "已破"}:
            text = _biaoke_pred_label(lv, _level_break_tag(lv, lows) if tag == "未到" else tag)
        else:
            text = str(row.get("label") or _biaoke_pred_label(lv))
        # 周一破台指：狀態跟官方柱
        if abs(lv - 44042.0) < 0.6:
            text = _biaoke_pred_label(lv, _level_break_tag(lv, lows) + "周一")
        # 近／超近窗沒有 ref 日柱時從窗左拉滿，不准縮成末日短樁
        x_note = 0
        ref = _ymd(row.get("ref_ymd"))
        if bars and ref:
            ii = _bar_index_by_ymd(bars, ref)
            if ii is not None:
                x_note = int(ii)
        out.append(
            {
                "x": x_note,
                "y": lv,
                "text": text[:28],
                "color": "#82b1ff" if lv < 45000 else "#4dd0e1",
            }
        )
        skip.add(round(lv, 1))
    return out


def _render_twii_far_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具①遠窗三欄：上費半浪 → 中加權推進⑤／大ABC → 下加權日量。

    推進⑤＝4/1→6/23；大A底7/29；大B末10/6；大C起10/15。費半同軸數。
    """
    try:
        import math

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("遠窗費半補資料略過")
    bars = _twii_bars_for_teach(db_path, 400, pack)
    if len(bars) < 20 or not save_path:
        return ""
    # 遠窗故事起點＝3 月底（推進⑤起 4/1 要進窗）
    i0 = (
        _bar_index_by_ymd(bars, "20260331")
        or _bar_index_by_ymd(bars, "20260328")
        or _bar_index_by_ymd(bars, "20260401")
        or 0
    )
    bars = _far_teach_roll_bars(list(bars[i0:]), max_bars=_FAR_TEACH_MAX_BARS)
    mac = _twii_macro_wave_anchors(bars)
    anc = _twii_abc_anchors(bars)  # 近窗細分（右標／預估仍可參考）
    if not mac:
        return ""
    sox = _load_us_daily(db_path, "SOX", "20260320")
    if (pack or {}).get("live_sox"):
        sox = _merge_live_sox_display_bar(sox, (pack or {}).get("live_sox"))
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = mac["highs"], mac["lows"], mac["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i5s, i5e = int(mac["i5_start"]), int(mac["i5_end"])
    i_alow = int(mac["i_alow"])
    i_b_end = int(mac["i_b_end"])
    i_c = int(mac["i_c"])
    i_now = int(mac["i_now"])
    y5s, y5e = float(mac["y5_start"]), float(mac["y5_end"])
    y_alow, y_b_end, y_now = (
        float(mac["y_alow"]),
        float(mac["y_b_end"]),
        float(mac["y_now"]),
    )
    # 相容舊變名（預估／雙底色仍用近窗 B 高當 y_ref 時用大B末）
    i5, y5 = i_b_end, y_b_end
    i_bhi, y_bhi = i_b_end, y_b_end
    sox_a = _align_us_to_twii_dates(sox, bars)
    # 加權完整柱末日之後若費半還有官方日 → 只延長費半軸（不准造假加權 OHLC）
    sox_a, sox_extra_dates = _extend_us_ohlc_past_twii(
        sox_a, sox, _ymd(bars[-1].get("date"))
    )
    sox_o, sox_h, sox_l, sox_c = sox_a["open"], sox_a["high"], sox_a["low"], sox_a["close"]
    n_tw = int(n)
    n_axis = len(sox_c)
    sox_anc = _sox_abc_anchors_on_axis(sox_h, sox_l, sox_c, i5_hint=i5)
    sox_i_now = int(sox_anc["i_now"]) if sox_anc else (n_axis - 1)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    # 最大量日＝黃帶定義來源（跟個股一樣：那天K最高～最低）；量只認加權 n_tw，不准造 SOX-only 日量
    i_vmax = (
        max(range(n_tw), key=lambda i: float(vols[i] or 0))
        if n_tw and any(float(v or 0) > 0 for v in vols[:n_tw])
        else None
    )

    # 上費半｜中加權｜中排左說明＋右八浪｜量——八浪不准壓任何縮圖K
    fig = plt.figure(figsize=(16.8, 13.2), dpi=NAV_CHART_DPI)
    _gs_far = fig.add_gridspec(
        4,
        1,
        height_ratios=(2.40, 3.45, 1.65, 1.12),
        hspace=_TEACH_HSPACE,
    )
    axu = fig.add_subplot(_gs_far[0, 0])
    ax = fig.add_subplot(_gs_far[1, 0], sharex=axu)
    _gs_far_mid = _gs_far[2].subgridspec(
        1, 2, width_ratios=(1.05, 1.20), wspace=_TEACH_MID_WSPACE
    )
    ax_leg = fig.add_subplot(_gs_far_mid[0, 0])
    # 八浪格不准 sharex：縮圖用 0～1 座標，跟 K 日軸脫鉤
    ax_wave_host = fig.add_subplot(_gs_far_mid[0, 1])
    axv = fig.add_subplot(_gs_far[3, 0], sharex=axu)
    fig.patch.set_facecolor(_LIVE_BG)
    # bottom 加高：腳註多行完整數字＋不壓 x 軸日期
    # top 略降：標題列＋雙黃框上移進頁眉，不准擋費半縮圖K
    fig.subplots_adjust(
        left=_TEACH_FIG_LEFT,
        right=_TEACH_FIG_RIGHT,
        top=_TEACH_FIG_TOP,
        bottom=0.125,
    )
    _style_teach_axes((axu, ax, axv))
    _style_teach_mid_panel(ax_leg)
    _style_teach_mid_panel(ax_wave_host)

    fut_x = float(i_now + 4)
    tip: Dict[str, Any] = {"fut_x": fut_x, "xlim_right": float(n) + 4}

    # —— 上：費半價＋自轉折波浪（不畫費半量）——
    valid = [
        i
        for i, c in enumerate(sox_c)
        if c == c and c and math.isfinite(float(sox_h[i])) and math.isfinite(float(sox_l[i]))
    ]
    sox_min_body = _candle_span_min_body(sox_h, sox_l, frac=_FAR_SOX_MIN_BODY_FRAC)
    _sox_last_repaint: Optional[Dict[str, Any]] = None
    _sox_chg_tip: Optional[Dict[str, Any]] = None
    _sox_right_deferred: List[Dict[str, Any]] = []
    _sox_ylabel_span: Optional[Tuple[float, float]] = None
    if len(valid) >= 5:
        span_raw = max(x for x in sox_h if x == x) - min(x for x in sox_l if x == x)
        for i in valid:
            prev_i = next((j for j in range(i - 1, -1, -1) if sox_c[j] == sox_c[j]), None)
            prev_c = sox_c[prev_i] if prev_i is not None else None
            up = candle_up_taiwan(sox_c[i], prev_c, sox_o[i])
            color = _LIVE_UP if up else _LIVE_DOWN
            # 遠窗費半：加粗影線＋價窗比例最小實體（舊 0.15%→看不見）
            axu.vlines(i, sox_l[i], sox_h[i], color=color, linewidth=1.55, zorder=5, alpha=0.95)
            y0, y1 = sorted((sox_o[i], sox_c[i]))
            _bh = max(y1 - y0, float(sox_min_body))
            rim = "#ffcdd2" if up else "#b2dfdb"
            axu.add_patch(
                plt.Rectangle(
                    (i - 0.36, y0),
                    0.72,
                    _bh,
                    facecolor=color,
                    edgecolor=rim,
                    linewidth=0.65,
                    zorder=6,
                    alpha=0.98,
                )
            )
        # 費半跟加權同一日曆錨：⑤起4/1→⑤終6/23→A底7/29→B末10/6→C
        s5s, s5e, sa, sb = i5s, i5e, i_alow, i_b_end
        if all(i in valid or (0 <= i < n_axis and sox_c[i] == sox_c[i]) for i in (s5s, s5e, sa, sb)):
            sy5s = float(sox_l[s5s]) if sox_l[s5s] == sox_l[s5s] else float(sox_c[s5s])
            sy5e = float(sox_h[s5e]) if sox_h[s5e] == sox_h[s5e] else float(sox_c[s5e])
            sya = float(sox_l[sa]) if sox_l[sa] == sox_l[sa] else float(sox_c[sa])
            syb = float(sox_h[sb]) if sox_h[sb] == sox_h[sb] else float(sox_c[sb])
            sn = float(sox_c[sox_i_now])
            _wave_line(axu, [s5s, s5e], [sy5s, sy5e], "#40c4ff", lw=2.25, zorder=7)
            _wave_line(axu, [s5e, sa], [sy5e, sya], "#ff8a80", lw=2.05, zorder=7)
            axu.plot(
                [sa, sb],
                [sya, syb],
                color="#ffd54f",
                lw=2.2,
                ls=(0, (7, 2.2)),
                zorder=7,
                solid_capstyle="round",
            )
            # 費C：自費B末連到今（中經 C 起日若有柱），不准大B末後斷線
            sox_c_xs = [sb]
            sox_c_ys = [syb]
            if (
                0 <= i_c < n_axis
                and i_c != sb
                and sox_c[i_c] == sox_c[i_c]
                and math.isfinite(float(sox_c[i_c]))
            ):
                sox_c_xs.append(i_c)
                sox_c_ys.append(float(sox_c[i_c]))
            sox_c_xs.append(sox_i_now)
            sox_c_ys.append(sn)
            _wave_line(axu, sox_c_xs, sox_c_ys, "#ea80fc", lw=1.95, zorder=7)
            span_s = span_raw
            sox_pred_ys = [
                float(r.get("level"))
                for r in ((pack or {}).get("pred_levels") or {}).get("sox") or []
                if r.get("level") is not None
            ]
            y_lo_s = min([x for x in sox_l if x == x] + sox_pred_ys)
            y_hi_s = max([x for x in sox_h if x == x] + sox_pred_ys)
            axu.set_ylim(y_lo_s - span_s * 0.22, y_hi_s + span_s * 0.22)
            _pin_pivot_name(
                axu, s5s, sy5s, "費⑤起", "#40c4ff", _fp, side="right", tip="low", n=n_axis, pad_x=0.35, fontsize=8
            )
            _pin_pivot_name(
                axu, s5e, sy5e, "費⑤終", "#40c4ff", _fp, side="auto", tip="high", n=n_axis, pad_x=0.2, fontsize=9
            )
            _pin_pivot_name(
                axu, sa, sya, "費A低", "#ff8a80", _fp, side="auto", tip="low", n=n_axis, pad_x=0.2, fontsize=9
            )
            _pin_pivot_name(
                axu, sb, syb, "費B末", "#ffd54f", _fp, side="auto", tip="high", n=n_axis, pad_x=0.2, fontsize=9
            )
            for ii, yy, col in (
                (s5s, sy5s, "#40c4ff"),
                (s5e, sy5e, "#40c4ff"),
                (sa, sya, "#ff8a80"),
                (sb, syb, "#ffd54f"),
                (sox_i_now, sn, "#ea80fc"),
            ):
                axu.scatter(
                    [ii],
                    [yy],
                    s=44,
                    facecolors="none",
                    edgecolors=col,
                    linewidths=1.35,
                    zorder=8,
                )
            # 右標延到加權 tip 後，與加權同一 x_col（對齊「7/29低…」那欄）
            _sox_right_deferred = _paint_sox_thesis_preds(
                axu,
                bars=bars,
                sox_o=sox_o,
                sox_h=sox_h,
                sox_l=sox_l,
                sox_c=sox_c,
                pack=pack,
                fp=_fp,
                i_now=sox_i_now,
                n=n_axis,
                ymin=y_lo_s - span_s * 0.22,
                ymax=y_hi_s + span_s * 0.22,
                now_y=float(sn),
                now_lab=f"費C今{_px(float(sn))}",
                place=False,
            )
            _sox_ylabel_span = (
                y_lo_s - span_s * 0.22,
                y_hi_s + span_s * 0.22,
            )
            # 末根費半K在 tip＋右標之後再蓋一次（見 xlim 後最終蓋回）
            _sox_last_repaint = {
                "i": sox_i_now,
                "o": float(sox_o[sox_i_now]),
                "h": float(sox_h[sox_i_now]),
                "l": float(sox_l[sox_i_now]),
                "c": float(sox_c[sox_i_now]),
                "prev": next(
                    (j for j in range(sox_i_now - 1, -1, -1) if sox_c[j] == sox_c[j]),
                    None,
                ),
                "min_body": max(float(sox_min_body), float(span_raw) * 0.035),
            }
    axu.set_ylabel("費半 SOX", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axu.text(
        0.012,
        0.04,
        "費半＝自轉折浪＋他點過回測日低（無官方量→不畫撐壓黃區）",
        transform=axu.transAxes,
        fontproperties=_fp(8, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.16", fc="#0b0f14", ec="#546e7a", lw=0.65, alpha=0.92),
    )

    # —— 中：加權價（先畫底帶在K下一層，再畫K）——
    tw_supports = _tw_support_ladder(pack)
    tip_anchors = _tw_tip_anchors(pack)
    # 上下多留：高點浪名在尖上、低點浪名在尖下，不准被裁、也不准回頭蓋K
    ymin = min([min(lows), y5s, y_alow] + list(tw_supports)) - 720
    ymax = max([max(highs), y5e, y_b_end]) + 1100
    sr = _next_support_resist(
        y_now,
        supports=tw_supports,
        resists=(47637.0, 48613.0, y_b_end, y5e),
    )
    # 預估端先算：同價只留端點「飆預測」，左青帶／右欄不准再貼一次
    tip_pre = _c_forecast_tip(
        i_now=i_now, y_now=y_now, y_ref=y_bhi, lows=c_seg_lows, anchors=tip_anchors
    )
    skip_lab_ys = (
        [float(tip_pre["anchor_y"])] if tip_pre.get("anchor_y") is not None else []
    )
    # 他點過的錨會上右欄 → 左欄不准再貼同價
    skip_lab_ys = list(skip_lab_ys) + [float(v) for v in tip_anchors]
    # 先黃＝最大量日高低；青＝飆預測位階帶，重疊處不塗青（兩底色不准互疊）
    y_excl_lo = float(lows[i_vmax]) if i_vmax is not None else None
    y_excl_hi = float(highs[i_vmax]) if i_vmax is not None else None
    if i_vmax is not None:
        _paint_max_vol_hl_zone(
            ax,
            high=float(highs[i_vmax]),
            low=float(lows[i_vmax]),
            date_lab=_ymd(bars[i_vmax].get("date")),
            fp=_fp,
        )
    sr_skip = _paint_next_sr_zone(
        ax,
        support=sr.get("support"),
        resist=sr.get("resist"),
        fp=_fp,
        exclude_lo=y_excl_lo,
        exclude_hi=y_excl_hi,
        skip_label_ys=skip_lab_ys,
        x_end=float(n) + 0.12,
    )
    _paint_live_candles(ax, None, opens, highs, lows, closes, vols, candle_up_taiwan)
    # 黃帶對應那一根K＝最大量日：金K＋豎線；「最大量」字只留量欄
    if i_vmax is not None:
        _paint_special_candle(
            ax,
            int(i_vmax),
            open_=float(opens[i_vmax]),
            high=float(highs[i_vmax]),
            low=float(lows[i_vmax]),
            close=float(closes[i_vmax]),
            color="#ffd54f",
            date_lab=_ymd(bars[i_vmax].get("date")),
            fp=_fp,
        )
    # 底色：藍＝推進⑤；金＝大B；紫＝大C（更淡，讓K／浪線主視覺）
    ax.axvspan(i5s - 0.4, i5e + 0.4, facecolor="#40c4ff", alpha=0.04, zorder=0.2)
    ax.axvspan(i_alow - 0.2, i_b_end + 0.4, facecolor="#ffd54f", alpha=0.035, zorder=0.2)
    ax.axvspan(i_c - 0.2, n - 0.2, facecolor="#ea80fc", alpha=0.035, zorder=0.2)
    # 推進⑤：4/1→6/23（藍實線）
    _wave_line(ax, [i5s, i5e], [y5s, y5e], "#40c4ff", lw=2.65, zorder=7)
    # 大A：6/23→7/29（粉）
    _wave_line(ax, [i5e, i_alow], [y5e, y_alow], "#ff8a80", lw=2.4, zorder=7)
    # 大B：7/29→10/6（金虛線）
    ax.plot(
        [i_alow, i_b_end],
        [y_alow, y_b_end],
        color="#ffd54f",
        lw=2.85,
        ls=(0, (8, 2.4)),
        zorder=7,
        solid_capstyle="round",
    )
    # 大C：自大B末連到今（經 C 起 10/15），紫線不准在 10/6 後斷開
    _wave_line(
        ax,
        [i_b_end, i_c, i_now],
        [y_b_end, float(closes[i_c]), y_now],
        "#ea80fc",
        lw=2.2,
        zorder=7,
    )
    # 近窗細分淡線（不搶大結構）
    if anc:
        ax.plot(
            [anc["i5"], anc["i_alow"]],
            [anc["y5"], anc["y_alow"]],
            color="#ff8a80",
            lw=1.05,
            alpha=0.35,
            zorder=6,
        )
        ax.plot(
            [anc["i_alow"], anc["i_bhi"]],
            [anc["y_alow"], anc["y_bhi"]],
            color="#40c4ff",
            lw=1.05,
            alpha=0.35,
            zorder=6,
        )
    # C 內細浪先算：c5≈45546 時預估端不准再浮「飆預測45,546」（改右欄）
    c_sub = _c_subwave_anchors_vs_biaoke60(
        highs, lows, bars, i_c=i_c, i_now=i_now
    )
    # 遠窗：預估端點只畫點＋虛線，字改右欄（不准「飆預測」浮在K／黃線上）
    tip = _paint_c_forecast(
        ax,
        i_now=i_now,
        y_now=y_now,
        y_ref=y_bhi,
        lows=c_seg_lows,
        fp=_fp,
        n=n,
        keep_left_of_right=True,
        show_label=False,
        anchors=tip_anchors,
    )
    fut_x = float(tip.get("fut_x") or fut_x)
    for ii, yy, col in (
        (i5s, y5s, "#40c4ff"),
        (i5e, y5e, "#40c4ff"),
        (i_alow, y_alow, "#ff8a80"),
        (i_b_end, y_b_end, "#ffd54f"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter(
            [ii],
            [yy],
            s=48,
            facecolors="none",
            edgecolors=col,
            linewidths=1.4,
            zorder=8,
        )
    # 末根加權K參數先記；等右標畫完再蓋回（避免虛線／字壓掉縮圖K）
    _tw_span = max(highs) - min(lows) if highs and lows else 0.0
    _tw_min_body = max(
        _candle_span_min_body(highs, lows, frac=_LIVE_CANDLE_MIN_BODY_FRAC),
        float(_tw_span) * 0.02,
    )
    _tw_last_repaint = {
        "i": i_now,
        "o": float(opens[i_now]),
        "h": float(highs[i_now]),
        "l": float(lows[i_now]),
        "c": float(closes[i_now]),
        "prev_c": float(closes[i_now - 1]) if i_now > 0 else None,
        "min_body": float(_tw_min_body),
    }
    # 先定 ylim 再釘浪名：lift／字級才對最終軸距，整盒不准蓋K
    ax.set_ylim(ymin, ymax)
    # 遠窗八浪縮圖＝超近同尺、黃虛線左側（見文末）
    _pin_pivot_name(
        ax,
        i5s,
        y5s,
        f"⑤起 {_md(bars[i5s].get('date'))}",
        "#40c4ff",
        _fp,
        side="right",
        tip="low",
        n=n,
        pad_x=0.35,
        fontsize=9,
    )
    _pin_pivot_name(
        ax,
        i5e,
        y5e,
        f"⑤終 {_md(bars[i5e].get('date'))}",
        "#40c4ff",
        _fp,
        side="auto",
        tip="high",
        n=n,
        pad_x=0.22,
        fontsize=10,
    )
    _pin_pivot_name(
        ax,
        i_alow,
        y_alow,
        f"大A底 {_md(bars[i_alow].get('date'))}",
        "#ff8a80",
        _fp,
        side="auto",
        tip="low",
        n=n,
        pad_x=0.22,
        fontsize=10,
    )
    _pin_pivot_name(
        ax,
        i_b_end,
        y_b_end,
        f"大B末＝假突破 {_md(bars[i_b_end].get('date'))}",
        "#ffd54f",
        _fp,
        side="auto",
        tip="high",
        n=n,
        pad_x=0.22,
        fontsize=10,
    )
    # 遠窗：C進行中只留轉折點（紫點），字併右欄「C今」——不准再蓋最後幾根縮圖K
    tip_skip: set = set()
    right_notes = [
        {"x": i5s, "y": y5s, "text": f"⑤起 {_px(y5s)}", "color": "#40c4ff"},
        {"x": i5e, "y": y5e, "text": f"⑤終 {_px(y5e)}", "color": "#40c4ff"},
        {"x": i_alow, "y": y_alow, "text": f"大A底 {_px(y_alow)}", "color": "#ff8a80"},
        {
            "x": i_b_end,
            "y": y_b_end,
            "text": f"大B末＝假突破 {_px(y_b_end)}",
            "color": "#ffd54f",
        },
        {"x": i_now, "y": y_now, "text": f"大C今 {_px(y_now)}", "color": "#ea80fc"},
    ]
    # 近窗細分（若窗內有）淡標，不搶大結構
    if anc:
        # anc＝C內早段震盪，不准標成大A／大B（大結構已用 mac）
        right_notes.append(
            {
                "x": int(anc["i_alow"]),
                "y": float(anc["y_alow"]),
                "text": f"C內早低 {_px(anc['y_alow'])}",
                "color": "#90a4ae",
            }
        )
        right_notes.append(
            {
                "x": int(anc["i_bhi"]),
                "y": float(anc["y_bhi"]),
                "text": f"C內早高 {_px(anc['y_bhi'])}",
                "color": "#90a4ae",
            }
        )
    tip_anchor = tip.get("anchor_y")
    if tip_anchor is not None:
        right_notes.append(
            {
                "x": n_axis - 1,
                "y": float(tip_anchor),
                "text": _biaoke_pred_label(float(tip_anchor)),
                "color": "#ea80fc",
            }
        )
        tip_skip.add(round(float(tip_anchor), 1))
    if sr_skip.get("support") is not None and round(float(sr_skip["support"]), 1) not in tip_skip:
        right_notes.append(
            {
                "x": n_axis - 1,
                "y": float(sr_skip["support"]),
                "text": _biaoke_pred_label(float(sr_skip["support"])),
                "color": "#4dd0e1",
            }
        )
    # 他最新錨（虛線梯）上右欄；跟著題旨換，不准寫死單一 44210
    for anch in tip_anchors:
        if round(float(anch), 1) in tip_skip:
            continue
        right_notes.append(
            {
                "x": n_axis - 1,
                "y": float(anch),
                "text": _biaoke_pred_label(
                    float(anch), _level_break_tag(float(anch), c_seg_lows)
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack, n=n_axis, lows=c_seg_lows, tip_skip=tip_skip, bars=bars
        )
    )
    # 右標在末日右側；八浪縮圖已改黃虛線左，不再跟右欄搶位
    x_right_col = float(n_axis) + 1.95
    try:
        x_right_col = max(x_right_col, float(tip.get("fut_x") or n_axis) + 0.35)
    except (TypeError, ValueError):
        pass
    x_sox_col = x_right_col + 0.40
    if _sox_right_deferred and _sox_ylabel_span is not None:
        # 費半價窗窄：間距略鬆才留得下 A低10445＋次回測9865＋費C今
        _place_live_right_labels(
            axu,
            _sox_right_deferred,
            n=n_axis,
            ymin=float(_sox_ylabel_span[0]),
            ymax=float(_sox_ylabel_span[1]),
            fp=_fp,
            level_dash=True,
            min_gap=(float(_sox_ylabel_span[1]) - float(_sox_ylabel_span[0])) * 0.045,
            x_col=x_sox_col,
        )
    _place_live_right_labels(
        ax,
        right_notes,
        n=n_axis,
        ymin=ymin,
        ymax=ymax,
        fp=_fp,
        level_dash=True,
        # 比例間距；不准絕對 floor 900 把真價標漂掉／擠掉
        min_gap=(ymax - ymin) * 0.055,
        x_col=x_right_col,
    )
    # 右標之後蓋回末根加權K（縮圖必見；白邊＋高 z，不准被 tip／虛線吃掉）
    if _tw_last_repaint:
        _paint_one_live_candle(
            ax,
            int(_tw_last_repaint["i"]),
            open_=float(_tw_last_repaint["o"]),
            high=float(_tw_last_repaint["h"]),
            low=float(_tw_last_repaint["l"]),
            close=float(_tw_last_repaint["c"]),
            prev_c=_tw_last_repaint.get("prev_c"),
            candle_up=candle_up_taiwan,
            min_body=float(_tw_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=14,
            z_body=15,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
    ax.set_ylabel("加權", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)

    # —— 下：加權日量（最大量黃＝與上方同索引當日K對齊）——
    _paint_vol_bars_max_yellow(
        axv,
        vols,
        opens,
        closes,
        candle_up_taiwan,
        fp=_fp,
        title="加權量",
        date_lab=_ymd(bars[i_vmax].get("date")) if i_vmax is not None else "",
    )
    if i_vmax is not None:
        _paint_max_vol_day_guide((axu, ax, axv), i_vmax)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.45)

    want = {
        _ymd(bars[0].get("date")),
        _ymd(bars[i5s].get("date")),
        _ymd(bars[i5e].get("date")),
        _ymd(bars[i_alow].get("date")),
        "20260401",
        "20260428",
        "20260623",
        "20260729",
        "20261006",
        "20261015",
        _ymd(bars[-1].get("date")),
    }
    want.update(sox_extra_dates)
    for row in ((pack or {}).get("pred_levels") or {}).get("sox") or []:
        want.add(_ymd(row.get("ref_ymd")))
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want or i % 10 == 0:
            if i not in t2:
                t2.append(i)
                tag = ""
                if i == i5s or d == "20260401":
                    tag = "⑤起"
                elif i == i5e or d == "20260623":
                    tag = "⑤終"
                elif d == "20260428":
                    tag = "費次回測"
                elif d == "20260729" or i == i_alow:
                    tag = "大A底"
                elif i == i_b_end or d == "20261006":
                    tag = "大B末假突破"
                l2.append(f"{_md(d)}{tag}")
    # 費半官方日晚於加權軸：x 軸補日期（加權那格不畫假K）
    for j, d in enumerate(sox_extra_dates):
        i = n_tw + j
        if d in want and i not in t2:
            t2.append(i)
            l2.append(f"{_md(d)}費半")
    t2, l2 = _sparse_xticks(t2, l2, min_gap=4)
    # 右標／xlim 跟最長軸（費半可多日）；加權右標仍貼加權末日；費半黃框右欄要留空
    x_right = max(
        n_axis + 8.6,
        n_tw + 8.6,
        float(tip.get("xlim_right") or n_tw) + 2.0,
        fut_x + 2.0,
        float(x_sox_col) + 5.2,
    )
    # 遠窗自 3 月底起：左側多留一格，⑤起首根不准被裁
    need_apr = True
    x_left = -1.35 if need_apr else -0.6
    for a in (axu, ax, axv):
        a.set_xlim(x_left, x_right)
    # 右欄價梯底板：K 區與右標分層（標籤全留；三層同線對齊）
    _rail0 = float(n_axis) + 0.42
    for _a in (axu, ax, axv):
        _paint_right_rail_panel(_a, x0=_rail0, x1=float(x_right))
    # xlim 定完再蓋末根費半K（避免右標／裁切吃掉周五官方柱）
    if _sox_last_repaint:
        _prev = _sox_last_repaint.get("prev")
        _prev_c = float(sox_c[_prev]) if _prev is not None else None
        _paint_one_live_candle(
            axu,
            int(_sox_last_repaint["i"]),
            open_=float(_sox_last_repaint["o"]),
            high=float(_sox_last_repaint["h"]),
            low=float(_sox_last_repaint["l"]),
            close=float(_sox_last_repaint["c"]),
            prev_c=_prev_c,
            candle_up=candle_up_taiwan,
            min_body=float(_sox_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=14,
            z_body=15,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
        # 空心 tip 最後蓋在末根收上（環看得見、不塗死K）
        axu.scatter(
            [float(_sox_last_repaint["i"])],
            [float(_sox_last_repaint["c"])],
            s=52,
            facecolors="none",
            edgecolors="#ea80fc",
            linewidths=1.5,
            zorder=16,
            clip_on=False,
        )
        # 末根K再蓋一次（空心 tip 已在上）；費半漲跌黃框改圖層座標、與加權黃框錯開
        _paint_one_live_candle(
            axu,
            int(_sox_last_repaint["i"]),
            open_=float(_sox_last_repaint["o"]),
            high=float(_sox_last_repaint["h"]),
            low=float(_sox_last_repaint["l"]),
            close=float(_sox_last_repaint["c"]),
            prev_c=_prev_c,
            candle_up=candle_up_taiwan,
            min_body=float(_sox_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=18,
            z_body=19,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
        axu.scatter(
            [float(_sox_last_repaint["i"])],
            [float(_sox_last_repaint["c"])],
            s=52,
            facecolors="none",
            edgecolors="#ea80fc",
            linewidths=1.5,
            zorder=20,
            clip_on=False,
        )
        # 暫存給標題列下方畫費半黃框（與加權黃框同字級、垂直錯開）
        _sox_chg_tip = {
            "close": float(_sox_last_repaint["c"]),
            "prev": _prev_c,
        }
    if _tw_last_repaint:
        ax.scatter(
            [float(_tw_last_repaint["i"])],
            [float(_tw_last_repaint["c"])],
            s=52,
            facecolors="none",
            edgecolors="#ea80fc",
            linewidths=1.5,
            zorder=16,
            clip_on=False,
        )
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for a in (axu, ax, axv):
        for lab in a.get_yticklabels():
            lab.set_fontproperties(_fp(8, "bold"))
            lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    vz_y = (
        f"黃＝最大量{_md(bars[i_vmax].get('date'))} {_px(highs[i_vmax])}～{_px(lows[i_vmax])}"
        if i_vmax is not None
        else "黃＝最大量日高低"
    )
    vz_c = (
        f"青＝飆預測{_px(sr['support']) if sr.get('support') is not None else '—'}～"
        f"{_px(sr['resist']) if sr.get('resist') is not None else '—'}"
    )
    sox_bit = ""
    sox_preds = ((pack or {}).get("pred_levels") or {}).get("sox") or []
    if sox_preds:
        sox_bit = "｜費半青＝已破A→下一撐（4/28回測K同軸）"
    # 不准 [:72]：會把「次回測4/28低9,865」裁成「9,」
    pred_foot = str(pack.get("pred_note") or "")[:240]
    # 頁眉：窗名＋圖例晶片＋日曆淡行（回到 bold：價帶仍在晶片，元素全留）
    _paint_teach_hud(
        fig,
        title="第1張・遠窗　上費半浪｜中加權大ABC｜下加權量",
        chips=[
            (vz_y, "#ffd54f"),
            (vz_c, "#4dd0e1"),
            ("藍⑤｜粉A｜金虛B｜紫C", "#ce93d8"),
            ("費半同軸", "#81d4fa"),
            ("C走完≠新五波升", "#ffab91"),
        ],
        meta=f"{_macro_wave_calendar_line()}{sox_bit}",
        fp=_fp,
    )
    _paint_teach_foot_bar(fig, y=0.0, height=0.058)
    # 加權／費半黃框：加權貼最上；費半在桃色副標下一行，不准擋桃色字／費半K
    _tw_stamp_y = 0.982
    _sox_stamp_y = 0.918
    _paint_teach_query_stamp(
        fig, bars, pack=pack, close=closes[-1], fp=_fp, x=0.995, y=_tw_stamp_y
    )
    if _sox_chg_tip:
        _paint_index_last_chg_tip(
            fig,
            close=float(_sox_chg_tip["close"]),
            prev_close=_sox_chg_tip.get("prev"),
            label_prefix="費半",
            fp=_fp,
            x=0.995,
            y=_sox_stamp_y,
            ha="right",
        )
    # 腳註多行：thesis＋預測點按｜分行；壓在 x 軸日期下方，不准互疊、不准裁半截
    foot_main = str(
        pack.get("thesis") or "推進⑤＝4/1→6/23｜大A底7/29→大B→大C進行中（預估）"
    )[:56]
    fig.text(
        0.05,
        0.048,
        foot_main,
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    if pred_foot:
        chunks: List[str] = []
        cur = ""
        for part in str(pred_foot).split("｜"):
            part = part.strip()
            if not part:
                continue
            cand = f"{cur}｜{part}" if cur else part
            if len(cand) > 62 and cur:
                chunks.append(cur)
                cur = part
            else:
                cur = cand
        if cur:
            chunks.append(cur)
        for i, line in enumerate(chunks[:4]):
            fig.text(
                0.05,
                0.032 - i * 0.014,
                line,
                fontproperties=_fp(8, "bold"),
                color=_LIVE_MUTED,
                ha="left",
                va="bottom",
            )
    # 中排：左對位說明｜右八浪小圖吃滿格（不准 hide）
    _nk_far = _eight_wave_now_key(pack)
    _paint_teach_eight_wave_legend(
        ax_leg, fp=_fp, now_key=_nk_far, pack=pack, detail=False
    )
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_nk_far,
        detail=False,
        ax=ax_wave_host,
        title="八浪對位",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_self_pred_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """專圖：主＝我的判斷預估；淡＝他說位輔助。≠買訊。

    依據＝官方加權轉折／量＋庫內費半／納指；與他說分欄標清。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _twii_bars_for_teach(db_path, 120, pack)
    if len(bars) < 16 or not save_path:
        return ""
    i0 = (
        _bar_index_by_ymd(bars, "20260929")
        or _bar_index_by_ymd(bars, "20260925")
        or _bar_index_by_ymd(bars, "20260915")
        or 0
    )
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    if not anc:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = anc["highs"], anc["lows"], anc["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i5, i_alow, i_bhi = anc["i5"], anc["i_alow"], anc["i_bhi"]
    i_now = anc["i_now"]
    y5, y_alow, y_bhi, y_now = anc["y5"], anc["y_alow"], anc["y_bhi"], anc["y_now"]
    self_pack = _build_self_pred_levels(
        pack,
        y_now=float(y_now),
        y5=float(y5),
        y_alow=float(y_alow),
        y_bhi=float(y_bhi),
        highs=highs,
        lows=lows,
        vols=vols,
        bars=bars,
        db_path=db_path,
    )
    # 掛回 pack 給敘述用
    if isinstance(pack, dict):
        pack["self_pred"] = self_pack

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(14.8, 9.2),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.4, 1.35), hspace=0.05),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ax.plot([i5, i_alow], [y5, y_alow], color="#ff8a80", lw=1.6, alpha=0.75, zorder=6)
    ax.plot([i_alow, i_bhi], [y_alow, y_bhi], color="#40c4ff", lw=1.6, alpha=0.75, zorder=6)
    ax.plot([i_bhi, i_now], [y_bhi, y_now], color="#ea80fc", lw=1.7, zorder=6)
    for ii, yy, col in (
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=36, c=col, zorder=8, edgecolors="#fff", linewidths=0.45)
    _pin_pivot_name(
        ax, i5, y5, "大B末／近⑤", "#ff8a80", _fp, side="auto", tip="high", n=n, pad_x=0.3, fontsize=9
    )
    _pin_pivot_name(ax, i_alow, y_alow, "A", "#ff8a80", _fp, side="auto", tip="low", n=n, pad_x=0.3, fontsize=9)
    _pin_pivot_name(ax, i_bhi, y_bhi, "B", "#40c4ff", _fp, side="auto", tip="high", n=n, pad_x=0.3, fontsize=9)

    mine_ys = [float(r["level"]) for r in (self_pack.get("mine") or [])]
    his_ys = [float(r["level"]) for r in (self_pack.get("his_aux") or [])]
    y_lo = min([min(lows)] + mine_ys + his_ys)
    y_hi = max([max(highs)] + mine_ys + his_ys)
    span = max(y_hi - y_lo, 1.0)
    ymin, ymax = y_lo - span * 0.12, y_hi + span * 0.14
    ax.set_ylim(ymin, ymax)
    ax.set_xlim(-0.5, n + 4.2)

    right: List[Dict[str, Any]] = []
    # 主：我估（亮）
    for row in self_pack.get("mine") or []:
        right.append(
            {
                "x": n - 1,
                "y": float(row["level"]),
                "text": str(row.get("label") or "")[:26],
                "color": str(row.get("color") or "#ffcc80"),
            }
        )
    # 輔：他說（淡灰，互撞時 _place 會丟低優先——他說標以「他」開頭不算 soft，所以用較淡色且放後面）
    for row in self_pack.get("his_aux") or []:
        right.append(
            {
                "x": n - 1,
                "y": float(row["level"]),
                "text": str(row.get("label") or "")[:26],
                "color": str(row.get("color") or "#78909c"),
            }
        )
    # 今
    right.append(
        {
            "x": n - 1,
            "y": float(y_now),
            "text": f"今{_px(float(y_now))}",
            "color": "#ea80fc",
        }
    )
    _place_live_right_labels(
        ax,
        right,
        n=n,
        ymin=ymin,
        ymax=ymax,
        fp=_fp,
        level_dash=True,
        min_gap=(ymax - ymin) * 0.07,
    )
    ax.set_ylabel("加權・我估主圖", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(9, "bold"), color=_LIVE_MUTED)
    ticks, labs = [], []
    for i, r in enumerate(bars):
        if i == 0 or i == n - 1 or i % 5 == 0 or i in (i5, i_alow, i_bhi):
            ticks.append(i)
            labs.append(_md(r.get("date")))
    axv.set_xticks(ticks)
    axv.set_xticklabels(labs, fontproperties=_fp(8, "bold"), color=_LIVE_TEXT)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)

    fig.text(
        0.03,
        0.975,
        "我的判斷預估（主・橘）｜他說位階（輔・灰）｜≠買訊｜不准當他的下一步",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    ref_line = "；".join(str(x) for x in (self_pack.get("refs") or [])[:2])[:110]
    fig.text(
        0.03,
        0.948,
        ref_line or "依據＝官方柱幾何＋庫內美股已收",
        fontproperties=_fp(9, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="top",
    )
    us_bias = str(self_pack.get("us_bias") or "")
    ax.text(
        0.012,
        0.04,
        (us_bias or "美股依據見上欄；無％＝庫內尚無已收")[:48],
        transform=ax.transAxes,
        fontproperties=_fp(8, "bold"),
        color="#ffcc80" if us_bias else _LIVE_MUTED,
        ha="left",
        va="bottom",
        zorder=12,
        bbox=dict(boxstyle="round,pad=0.18", fc="#0b0f14", ec="#ffcc80", lw=0.7, alpha=0.92),
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_live_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具②近窗特寫：⑤→A↓→B↑→C↓＋Fib／1-4（不懂浪也能跟折數）。

    遠窗另張；外圍費半／納指另張。位階＝預估・會動態修正。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _twii_bars_for_teach(db_path, 220, pack)
    if len(bars) < 16 or not save_path:
        return ""
    # 近窗＝大結構特寫：從⑤起入窗，⑤／A／B 起末與遠窗／縮圖同一日曆
    i0 = (
        _bar_index_by_ymd(bars, "20260401")
        or _bar_index_by_ymd(bars, "20260331")
        or _bar_index_by_ymd(bars, "20260325")
        or 0
    )
    bars = list(bars[i0:])
    mac = _twii_macro_wave_anchors(bars)
    if not mac:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = mac["highs"], mac["lows"], mac["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i5s, i5e, i_alow, i_b_end, i_c = (
        int(mac["i5_start"]),
        int(mac["i5_end"]),
        int(mac["i_alow"]),
        int(mac["i_b_end"]),
        int(mac["i_c"]),
    )
    i_now = int(mac["i_now"])
    y5s, y5e, y_alow, y_b_end, y_now = (
        float(mac["y5_start"]),
        float(mac["y5_end"]),
        float(mac["y_alow"]),
        float(mac["y_b_end"]),
        float(mac["y_now"]),
    )
    # 相容舊變名（後段 Fib／預估仍引用）
    i5, y5 = i_b_end, y_b_end
    i_bhi, y_bhi = i_b_end, y_b_end
    fib_levels = (
        (47637.0, "0.382", "#ffe082"),
        (48613.0, "0.618", "#ffd54f"),
        (49160.0, "0.75", "#ffca28"),
    )
    rule14_y = float(y_alow)
    rule14_lab = f"大A底＝1-4 {_px(rule14_y)}"

    # 三列：加權K｜中排左說明＋右八浪｜量——八浪不准壓縮圖K
    fig = plt.figure(figsize=(15.6, 11.0), dpi=NAV_CHART_DPI)
    _gs_near = fig.add_gridspec(
        3,
        1,
        height_ratios=(5.25, 1.70, 1.15),
        hspace=_TEACH_HSPACE,
    )
    ax = fig.add_subplot(_gs_near[0, 0])
    _gs_near_mid = _gs_near[1].subgridspec(
        1, 2, width_ratios=(1.05, 1.20), wspace=_TEACH_MID_WSPACE
    )
    ax_leg = fig.add_subplot(_gs_near_mid[0, 0])
    # 八浪格不准 sharex：縮圖用 0～1 座標，跟 K 日軸脫鉤
    ax_wave_host = fig.add_subplot(_gs_near_mid[0, 1])
    axv = fig.add_subplot(_gs_near[2, 0], sharex=ax)
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _style_teach_mid_panel(ax_leg)
    _style_teach_mid_panel(ax_wave_host)
    tw_supports = _tw_support_ladder(pack)
    tip_anchors = _tw_tip_anchors(pack)
    ymin = min([min(lows)] + list(tw_supports)) - 480
    ymax = max(highs) + 860
    # 預估端先算：同價只留端點飆預測
    tip_pre = _c_forecast_tip(
        i_now=i_now,
        y_now=y_now,
        y_ref=y_b_end,
        lows=list(lows[i_c : i_now + 1]) or list(lows[i_b_end:]),
        anchors=tip_anchors,
    )
    skip_lab_ys = (
        [float(tip_pre["anchor_y"])] if tip_pre.get("anchor_y") is not None else []
    )
    # 他點錨走右欄 → 左欄不准再貼同價壓虛線
    skip_lab_ys = list(skip_lab_ys) + [float(v) for v in tip_anchors]
    # 與遠窗同一套雙底色（黃＝最大量日高低、青＝飆預測位階帶）
    zone = _paint_window_dual_zones(
        ax,
        highs=highs,
        lows=lows,
        vols=vols,
        bars=bars,
        y_now=y_now,
        fp=_fp,
        supports=tw_supports,
        resists=(47637.0, 48613.0, y_b_end, y5e),
        skip_label_ys=skip_lab_ys,
    )
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    i_vmax = zone.get("i_vmax")
    if i_vmax is not None:
        _paint_special_candle(
            ax,
            int(i_vmax),
            open_=float(opens[i_vmax]),
            high=float(highs[i_vmax]),
            low=float(lows[i_vmax]),
            close=float(closes[i_vmax]),
            color="#ffd54f",
            date_lab=_ymd(bars[i_vmax].get("date")),
            fp=_fp,
        )
        _paint_max_vol_day_guide((ax, axv), int(i_vmax))
    # 大結構色帶／折線＝遠窗／縮圖同一套（⑤→A→B→C）；C內震盪不准再叫近A／近B
    ax.axvspan(i5s - 0.35, i5e + 0.35, facecolor="#40c4ff", alpha=0.035, zorder=0.2)
    ax.axvspan(i5e - 0.2, i_alow + 0.2, facecolor="#ff8a80", alpha=0.035, zorder=0.2)
    ax.axvspan(i_alow - 0.2, i_b_end + 0.35, facecolor="#ffd54f", alpha=0.035, zorder=0.2)
    ax.axvspan(i_b_end + 0.35, n - 0.15, facecolor="#ea80fc", alpha=0.045, zorder=0.2)
    _wave_line(ax, [i5s, i5e], [y5s, y5e], "#40c4ff", lw=2.55, zorder=7)  # 推進⑤
    _wave_line(ax, [i5e, i_alow], [y5e, y_alow], "#ff8a80", lw=2.55, zorder=7)  # 大A
    ax.plot(
        [i_alow, i_b_end],
        [y_alow, y_b_end],
        color="#ffd54f",
        lw=2.7,
        ls=(0, (8, 2.4)),
        zorder=7,
        solid_capstyle="round",
    )  # 大B
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_b_end:])
    _wave_line(
        ax,
        [i_b_end, i_c, i_now],
        [y_b_end, float(closes[i_c]), y_now],
        "#ea80fc",
        lw=2.5,
        zorder=7,
    )  # 大C
    c_sub = _c_subwave_anchors_vs_biaoke60(
        highs, lows, bars, i_c=i_c, i_now=i_now
    )
    tip = _paint_c_forecast(
        ax,
        i_now=i_now,
        y_now=y_now,
        y_ref=y_b_end,
        lows=c_seg_lows,
        fp=_fp,
        n=n,
        keep_left_of_right=True,
        show_label=not bool(c_sub.get("ok")),
        anchors=tip_anchors,
    )
    if c_sub.get("ok"):
        i4, y4 = int(c_sub["i_c4_hi"]), float(c_sub["y_c4"])
        i5c, y5c = int(c_sub["i_c5_lo"]), float(c_sub["y_c5"])
        ax.plot(
            [i4, i5c],
            [y4, y5c],
            color="#ce93d8",
            lw=1.35,
            ls=(0, (2.2, 1.6)),
            alpha=0.92,
            zorder=6.5,
        )
        ax.scatter(
            [i4, i5c],
            [y4, y5c],
            s=36,
            c="#ce93d8",
            zorder=8,
            edgecolors="#fff",
            linewidths=0.5,
        )
    for ii, yy, col in (
        (i5s, y5s, "#40c4ff"),
        (i5e, y5e, "#40c4ff"),
        (i_alow, y_alow, "#ff8a80"),
        (i_b_end, y_b_end, "#ffd54f"),
    ):
        ax.scatter([ii], [yy], s=56, c=col, zorder=8, edgecolors="#ffffff", linewidths=0.7)
    ax.scatter(
        [i_now],
        [y_now],
        s=56,
        facecolors="none",
        edgecolors="#ea80fc",
        linewidths=1.2,
        zorder=8,
    )
    span = max(ymax - ymin, 1.0)
    ax.axvline(i_c, color="#ea80fc", lw=0.95, ls=(0, (2, 2)), alpha=0.8, zorder=5)
    # 禁區先登記：黃戳帶＋右下縮圖帶，智慧標不准蓋主線／縮圖／戳
    _reserve_avoid_zone(ax, float(n) - 24.0, 40500.0, float(n) + 5.0, 43300.0)
    _reserve_avoid_zone(ax, float(n) * 0.55, 31800.0, float(n) - 0.5, 39200.0)
    _pin_pivot_name(
        ax,
        i5s,
        y5s,
        f"⑤起 {_md(bars[i5s].get('date'))}",
        "#40c4ff",
        _fp,
        side="auto",
        tip="low",
        n=n,
        pad_x=0.35,
        fontsize=9,
    )
    _pin_pivot_name(
        ax,
        i5e,
        y5e,
        f"⑤末＝A起 {_md(bars[i5e].get('date'))}",
        "#40c4ff",
        _fp,
        side="auto",
        tip="high",
        n=n,
        pad_x=0.35,
        fontsize=9,
    )
    _pin_pivot_name(
        ax,
        i_alow,
        y_alow,
        f"大A末＝B起 {_md(bars[i_alow].get('date'))}",
        "#ff8a80",
        _fp,
        side="auto",
        tip="low",
        n=n,
        pad_x=0.35,
        fontsize=9,
    )
    _pin_pivot_name(
        ax,
        i_b_end,
        y_b_end,
        f"大B末＝假突破 {_md(bars[i_b_end].get('date'))}",
        "#ffd54f",
        _fp,
        side="auto",
        tip="high",
        n=n,
        pad_x=0.35,
        fontsize=9,
    )
    _pin_pivot_name(
        ax,
        i_now,
        y_now,
        "C進行中",
        "#ea80fc",
        _fp,
        side="right",
        tip="mid",
        n=n,
        pad_x=1.05,
        fontsize=9,
    )
    # c4／c5 只走右欄，不准再浮主圖壓紫C線／K
    # Fib／錨／撐壓虛線改走右標函式（自 note['x'] 連到同欄標左緣），不准再左一截短虛線
    sr = zone.get("sr") or {}
    sr_skip = zone.get("sr_skip") or {}
    tip_anchor = tip.get("anchor_y")
    tip_skip: set = set()
    right_notes = [
        {"x": i5s, "y": y5s, "text": f"⑤起 {_px(y5s)}", "color": "#40c4ff"},
        {"x": i5e, "y": y5e, "text": f"⑤末 {_px(y5e)}", "color": "#40c4ff"},
        {"x": i_alow, "y": y_alow, "text": rule14_lab, "color": "#ff8a80"},
        {
            "x": i_b_end,
            "y": y_b_end,
            "text": f"大B末＝假突破 {_px(y_b_end)}",
            "color": "#ffd54f",
        },
        {"x": i_now, "y": y_now, "text": f"大C今 {_px(y_now)}", "color": "#ea80fc"},
    ]
    for y_fib, lab_fib, col_fib in fib_levels:
        right_notes.append(
            {
                "x": 0,
                "y": float(y_fib),
                "text": f"切{lab_fib}" if lab_fib == "0.75" else _biaoke_pred_label(float(y_fib)),
                "color": col_fib,
            }
        )
    if c_sub.get("ok"):
        right_notes.append(
            {
                "x": int(c_sub["i_c4_hi"]),
                "y": float(c_sub["y_c4"]),
                "text": f"c4細 {_px(c_sub['y_c4'])}",
                "color": "#ce93d8",
            }
        )
        right_notes.append(
            {
                "x": int(c_sub["i_c5_lo"]),
                "y": float(c_sub["y_c5"]),
                "text": f"c5細 {_px(c_sub['y_c5'])}",
                "color": "#ce93d8",
            }
        )
    # 圖上若沒浮預估標（有 c4／c5 時 show_label=False）→ 端點錨改上右欄
    if tip_anchor is not None and bool(c_sub.get("ok")):
        right_notes.append(
            {
                "x": 0,
                "y": float(tip_anchor),
                "text": _biaoke_pred_label(
                    float(tip_anchor),
                    _level_break_tag(float(tip_anchor), c_seg_lows),
                ),
                "color": "#ea80fc",
            }
        )
        tip_skip.add(round(float(tip_anchor), 1))
    elif tip_anchor is not None:
        tip_skip.add(round(float(tip_anchor), 1))
    # 他最新錨（虛線梯）上右欄；跟著題旨換，不准寫死 45546／44210
    for anch in tip_anchors:
        if round(float(anch), 1) in tip_skip:
            continue
        right_notes.append(
            {
                "x": 0,
                "y": float(anch),
                "text": _biaoke_pred_label(
                    float(anch), _level_break_tag(float(anch), c_seg_lows)
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack, n=n, lows=c_seg_lows, tip_skip=tip_skip, bars=bars
        )
    )
    # 落在黃帶內的青標改右欄（與遠窗同一套；已有同價／預估端則不重複）
    have_ys = {round(float(n0["y"]), 1) for n0 in right_notes} | tip_skip
    for key, col in (("resist", "#4dd0e1"), ("support", "#4dd0e1")):
        yv = sr_skip.get(key)
        if yv is None:
            continue
        if round(float(yv), 1) in have_ys:
            continue
        right_notes.append(
            {
                "x": 0,
                "y": float(yv),
                "text": _biaoke_pred_label(float(yv)),
                "color": col,
            }
        )
        have_ys.add(round(float(yv), 1))
    # 與遠窗同一套：同欄右標＋自點位拉滿虛線；比例間距（不准絕對 floor）
    x_near_col = float(n) + 2.55
    try:
        x_near_col = max(x_near_col, float(tip.get("fut_x") or n) + 0.85)
    except (TypeError, ValueError):
        pass
    _place_live_right_labels(
        ax,
        right_notes,
        n=n,
        ymin=ymin,
        ymax=ymax,
        fp=_fp,
        level_dash=True,
        min_gap=(ymax - ymin) * 0.055,
        x_col=x_near_col,
    )
    _finish_last_twii_candle(
        ax,
        i_now=i_now,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_up_taiwan,
        ymin=ymin,
        ymax=ymax,
    )
    morph = str(pack.get("morph_note") or "").strip()
    morph_line = (morph[:24] + "…") if len(morph) > 24 else (morph or "楔形／盤頭＝觀察，不是叫你買")
    intent = str(pack.get("intent_note") or "").strip()
    # 說明框移出價圖（fig 底），不准擋 K／右標
    intent_one = intent.split("；")[0] if intent else "量價要先講故事：無量跌≠止穩；套牢後別等好心解套"
    intent_line = (intent_one[:36] + "…") if len(intent_one) > 36 else intent_one
    c_sub_teach = ""
    if c_sub.get("ok"):
        c_sub_teach = (
            f"｜C內細c4 {_px(c_sub['y_c4'])}→c5 {_px(c_sub['y_c5'])}（對他60分・同遠窗）"
        )
    teach = (
        f"近窗＝大結構特寫｜{_macro_wave_calendar_line()}｜"
        f"今在大C內震盪（不是新的大A／大B）｜C走完≠新五波升"
        f"{c_sub_teach}｜黃線Fib＝反彈壓｜型態：{morph_line}｜{intent_line}"
    )
    want_dates = {
        "20260401",
        "20260623",
        "20260729",
        "20261006",
        "20261015",
        "20261022",
        _ymd(bars[-1].get("date")),
    }
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want_dates or i % 4 == 0:
            if i not in t2:
                t2.append(i)
                l2.append(_md(d))
    t2, l2 = _sparse_xticks(t2, l2, min_gap=2)
    # 右標水平往左貼K；近窗留寬夠長標（含「大B末=假突破」）進軸內，不准裁字
    _near_x_right = max(
        float(x_near_col) + 6.8,
        n + 10.2,
        float(tip.get("xlim_right") or n) + 2.4,
    )
    ax.set_xlim(-0.6, _near_x_right)
    _paint_right_rail_panel(ax, x0=float(n) + 0.55, x1=float(_near_x_right))
    _paint_right_rail_panel(axv, x0=float(n) + 0.55, x1=float(_near_x_right))
    ax.set_ylim(ymin, ymax)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.4)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    ladder = _wave_now_ladder(pack)
    # 標題跟當日層級走：一眼看到大→小走到哪；雙底色與遠窗對齊
    title_bit = str(ladder.get("now") or "").strip() or "現在在C（預估）"
    if len(title_bit) > 22:
        title_bit = title_bit[:21] + "…"
    vz_y = (
        f"黃＝最大量{_md(bars[int(i_vmax)].get('date'))} {_px(highs[int(i_vmax)])}～{_px(lows[int(i_vmax)])}"
        if i_vmax is not None
        else "黃＝最大量日高低"
    )
    vz_c = (
        f"青＝飆預測{_px(sr['support']) if sr.get('support') is not None else '—'}～"
        f"{_px(sr['resist']) if sr.get('resist') is not None else '—'}"
    )
    _paint_teach_hud(
        fig,
        title=f"第2張・近窗　此刻＝{title_bit}",
        chips=[
            (vz_y, "#ffd54f"),
            (vz_c, "#4dd0e1"),
            ("細＝C內c4／c5", "#ce93d8"),
            ("C走完≠新五波升", "#ffab91"),
        ],
        meta=(
            f"{str(ladder.get('one_line') or '現在走到：C進行中')[:44]}｜"
            f"{_macro_wave_calendar_line()}"
        ),
        fp=_fp,
    )
    _paint_teach_foot_bar(fig, y=0.0, height=0.045)
    # 近窗：黃戳貼頁眉下右，不准再坐在 K 腰線擋浪／蠟燭
    fig.subplots_adjust(
        left=_TEACH_FIG_LEFT,
        right=_TEACH_FIG_RIGHT,
        top=_TEACH_FIG_TOP,
        bottom=0.08,
    )
    _paint_teach_query_stamp(
        fig,
        bars,
        pack=pack,
        close=closes[-1],
        fp=_fp,
        x=0.995,
        y=0.855,
        ha="right",
    )
    # 單行腳：不准雙行疊字蓋數字；主句用正文色，量價輔句才淡
    intent_foot = str(pack.get("intent_note") or pack.get("vol_note") or "")
    intent_one = intent_foot.split("；")[0] if intent_foot else ""
    foot_one = teach[:110]
    if intent_one:
        foot_one = f"{foot_one}｜量價：{intent_one}"[:160]
    fig.text(
        0.03,
        0.018,
        foot_one,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    # 中排：左對位說明｜右八浪小圖吃滿格（不准 hide）
    _nk_near = _eight_wave_now_key(pack)
    _paint_teach_eight_wave_legend(
        ax_leg, fp=_fp, now_key=_nk_near, pack=pack, detail=True
    )
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_nk_near,
        detail=True,
        ax=ax_wave_host,
        title="八浪對位",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_super_near_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具④超級近窗：C 段內『哪一層小波』對齊他說的；另色線僅前提不同才畫。

    不是買訊。個股不准發明浪；大盤細微只標他點過／題旨能對上的層。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _twii_bars_for_teach(db_path, 120, pack)
    if len(bars) < 16 or not save_path:
        return ""
    # 資料窗仍留⑤錨（鐵律要⑤）；畫面 xlim 再裁到 B／C 超級近窗
    i0 = (
        _bar_index_by_ymd(bars, "20261006")
        or _bar_index_by_ymd(bars, "20260929")
        or _bar_index_by_ymd(bars, "20260925")
        or 0
    )
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    if not anc:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = anc["highs"], anc["lows"], anc["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i_bhi, i_c, i_now = anc["i_bhi"], anc["i_c"], anc["i_now"]
    y_bhi, y_now = anc["y_bhi"], anc["y_now"]
    # 超近閃折／浪階對縮圖：B 峰＝大B末＝近⑤日（10/6 真高），不准用近B(10/14)假高峰
    i_b_peak = int(anc["i5"])
    y_b_peak = float(anc["y5"])
    # 視覺裁切：自大B末前半根起，讓縮圖 B 峰同根看得見
    x_left = max(-0.4, float(i_b_peak) - 0.8)

    blob = " ".join(
        str(pack.get(k) or "")
        for k in ("thesis", "wait_struct", "snippet", "morph_note")
    )
    his = _his_micro_degree(blob)
    geom = _geom_c_micro_swings(
        highs, lows, closes, i_bhi=i_b_peak, i_c=i_c, i_now=i_now
    )
    need_alt = _alt_path_needed(his.get("degree") or "", geom.get("geom_degree") or "")
    ladder = _wave_now_ladder(pack)

    # 超近窗鎖定上下分層：上＝縮圖K、中＝說明＋八浪小圖、下＝量（與遠／近同構）
    fig = plt.figure(figsize=(15.6, 11.3), dpi=NAV_CHART_DPI)
    _gs = fig.add_gridspec(
        3,
        2,
        height_ratios=(5.35, 2.45, 1.15),
        width_ratios=(1.05, 1.20),
        hspace=_TEACH_HSPACE + 0.015,
        wspace=_TEACH_MID_WSPACE,
    )
    ax = fig.add_subplot(_gs[0, :])
    ax_leg = fig.add_subplot(_gs[1, 0])
    ax_wave_host = fig.add_subplot(_gs[1, 1])
    axv = fig.add_subplot(_gs[2, :], sharex=ax)
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _style_teach_mid_panel(ax_leg)
    _style_teach_mid_panel(ax_wave_host)
    tw_supports = _tw_support_ladder(pack)
    tip_anchors = _tw_tip_anchors(pack)
    ymin = min([min(lows)] + list(tw_supports)) - 420
    ymax = max(highs) + 720
    span = ymax - ymin
    # 與遠／近窗同一套雙底色；他點錨／c5 走右欄 → 左欄不准再浮同價
    _c_sub_pre = _c_subwave_anchors_vs_biaoke60(
        highs, lows, bars, i_c=i_c, i_now=i_now
    )
    _skip_left = [float(v) for v in tip_anchors]
    if _c_sub_pre.get("ok"):
        _skip_left.append(float(_c_sub_pre["y_c5"]))
    zone = _paint_window_dual_zones(
        ax,
        highs=highs,
        lows=lows,
        vols=vols,
        bars=bars,
        y_now=float(y_now),
        fp=_fp,
        supports=tw_supports,
        resists=(47637.0, 48613.0, y_bhi),
        skip_label_ys=_skip_left,
    )
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    i_vmax = zone.get("i_vmax")
    if i_vmax is not None:
        _paint_special_candle(
            ax,
            int(i_vmax),
            open_=float(opens[i_vmax]),
            high=float(highs[i_vmax]),
            low=float(lows[i_vmax]),
            close=float(closes[i_vmax]),
            color="#ffd54f",
            date_lab=_ymd(bars[i_vmax].get("date")),
            fp=_fp,
        )
        _paint_max_vol_day_guide((ax, axv), int(i_vmax))
    ax.axvspan(i_c - 0.35, n - 0.15, facecolor="#ea80fc", alpha=0.05, zorder=1)

    # 超近主視覺＝縮圖同套細浪；他說 B→今 只留淡底，不准搶橙線浪階
    i_c1 = int(geom.get("i_c1_lo") or i_c)
    i_c2 = int(geom.get("i_c2_hi") or i_now)
    his_xs = [i_b_peak, i_now]
    his_ys = [y_b_peak, float(closes[i_now])]
    _wave_line(
        ax, his_xs, his_ys, "#ea80fc", lw=1.35, alpha=0.35, zorder=5, glow=False
    )
    ax.axvline(i_c, color="#ea80fc", lw=0.9, ls=(0, (2, 2)), alpha=0.45, zorder=4)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_b_peak:])
    c_sub = _c_sub_pre
    tip = _paint_c_forecast(
        ax,
        i_now=i_now,
        y_now=float(closes[i_now]),
        y_ref=y_b_peak,
        lows=c_seg_lows,
        fp=_fp,
        n=n,
        keep_left_of_right=True,
        show_label=False,  # 超近：45546／c5 只走右欄，圖上不准浮
        anchors=tip_anchors,
    )
    # 細浪重畫：B＝大B末真高 →①…⑤；與右縮圖 flash_pivots 同一套，不准另編
    flash_pivots = _c_teach_flash_pivots(
        highs, lows, closes, i_bhi=i_b_peak, i_c=i_c, i_now=i_now, c_sub=c_sub
    )
    if len(flash_pivots) >= 6:
        geom_xs = [int(p[0]) for p in flash_pivots]
        geom_ys = [float(p[1]) for p in flash_pivots]
    else:
        geom_xs = [i_b_peak, i_c1, i_c2, i_now]
        geom_ys = [
            y_b_peak,
            float(lows[i_c1]),
            float(highs[i_c2]),
            float(closes[i_now]),
        ]
    # 雙描邊＋實折，讓 B→①～⑤ 一眼對得上縮圖閃折（不准淡虛線看不見）
    ax.plot(
        geom_xs,
        geom_ys,
        color="#ffab40",
        lw=4.6,
        alpha=0.22,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=6.15,
    )
    ax.plot(
        geom_xs,
        geom_ys,
        color=_LIVE_BG,
        lw=3.35,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=6.2,
    )
    ax.plot(
        geom_xs,
        geom_ys,
        color="#ffb74d",
        lw=2.2,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=6.4,
        label="日K小波①～⑤（＝縮圖）",
    )
    flash_step = _c_flash_step(str(ladder.get("now") or ""))
    for j, (gx, gy) in enumerate(zip(geom_xs, geom_ys)):
        is_now = j == flash_step  # 0=B；1…5＝①…⑤
        ax.scatter(
            [gx],
            [gy],
            s=92 if is_now else 54,
            c="#ffd54f" if is_now else "#ffab40",
            zorder=8.5,
            edgecolors="#111111",
            linewidths=0.75,
        )
        if is_now:
            ax.scatter(
                [gx],
                [gy],
                s=148,
                facecolors="none",
                edgecolors="#ffd54f",
                linewidths=1.95,
                zorder=8.6,
            )
    # c5 只釘點（對他60分），不再另畫紫折線搶①～⑤浪階
    if c_sub.get("ok"):
        i5c, y5c = int(c_sub["i_c5_lo"]), float(c_sub["y_c5"])
        ax.scatter(
            [i5c],
            [y5c],
            s=36,
            c="#ce93d8",
            zorder=7.5,
            edgecolors="#fff",
            linewidths=0.5,
            label="c5細（對他60分）",
        )

    # 轉折浪名釘同價Y；B峰＝大B末真高；①～⑤與縮圖同錨
    c_lo = min(float(lows[i]) for i in range(i_b_peak, n))
    c_hi = max(float(highs[i]) for i in range(i_b_peak, n))
    pad = (c_hi - c_lo) * 0.04
    now_lab = f"今＝{ladder.get('now') or 'C進行中'}（預估）"
    # 大B末日期用右欄／B釘；近B(10/14)不釘名（非峰、非縮圖B）
    # B＋①～⑤ 全釘（與右縮圖一一對）；金圈＝浪級此刻
    _flash_side = {"B": "left", "①": "left", "②": "right", "③": "left", "④": "right", "⑤": "left"}
    _flash_tip = {"B": "high", "①": "low", "②": "high", "③": "low", "④": "high", "⑤": "mid"}
    for _fi, _fy, _flab in flash_pivots:
        if _flab == "B":
            _name = f"B {_px(_fy)}"
        elif _flab == "④" and c_sub.get("ok"):
            _name = f"④＝c4 {_px(_fy)}"
        elif _flab == "⑤":
            _name = f"⑤今 {_px(_fy)}"
        else:
            _name = f"{_flab} {_px(_fy)}"
        _pin_pivot_name(
            ax,
            int(_fi),
            float(_fy),
            _name,
            "#ffd54f" if _flab == "④" and flash_step == 4 else "#ffab40",
            _fp,
            side=_flash_side.get(_flab, "auto"),
            tip=_flash_tip.get(_flab, "mid"),
            n=n,
            pad_x=0.4,
            fontsize=11 if _flab == "B" else 10,
        )
    # 說明句：C 起確認（Y 用真價）；今層級字另釘，避免跟⑤價標疊
    _pin_pivot_name(
        ax,
        i_c,
        float(closes[i_c]) if i_c < len(closes) else float(highs[i_c]),
        "C起確認 10/15（峰在大B末）",
        "#ea80fc",
        _fp,
        side="right",
        tip="mid",
        n=n,
        pad_x=0.62,
        fontsize=10,
    )
    _pin_pivot_name(
        ax,
        i_now,
        float(closes[i_now]),
        now_lab,
        "#ffffff",
        _fp,
        side="right",
        tip="mid",
        n=n,
        pad_x=0.62,
        fontsize=10,
    )

    # 另前提演化（薄荷虛線）：只有跟他約的不同才畫
    if need_alt:
        # 另前提：若他說已到 2、柱讀仍像 1 → 虛線往②高延伸再轉；相反則虛線先標更深①
        if (his.get("degree") or "") == "C3-3-2" and (geom.get("geom_degree") or "") == "C3-3-1":
            alt_xs = [i_c1, i_now, min(i_now + max(2, (i_now - i_c1) // 3), n - 1)]
            tip_y = float(closes[i_now]) + span * 0.06
            alt_ys = [float(lows[i_c1]), float(closes[i_now]), tip_y]
            alt_note = "另前提：若還在①整理→先墊高再進②（非他主敘）"
        else:
            # 他偏①／C3-3，柱讀已像②：另線示更深殺段
            deeper = float(lows[i_c1]) - span * 0.08
            alt_xs = [i_c2, i_now, min(i_now + 2, n - 1)]
            alt_ys = [float(highs[i_c2]), float(closes[i_now]), deeper]
            alt_note = "另前提：若②已完→續走更深③（非他主敘）"
        ax.plot(
            alt_xs,
            alt_ys,
            color="#69f0ae",
            lw=2.0,
            ls=(0, (5, 2)),
            zorder=7,
            label="另前提演化",
        )
        ax.scatter(alt_xs[-1:], alt_ys[-1:], s=40, c="#69f0ae", zorder=8, edgecolors="#fff", linewidths=0.5)
        ax.text(
            alt_xs[-1],
            alt_ys[-1],
            "另色演化",
            fontproperties=_fp(9, "bold"),
            color="#69f0ae",
            ha="left",
            va="bottom",
            zorder=9,
        )
    else:
        alt_note = "另色線未畫：同家族細微層一致（或他還沒點名C3）"

    deg_his = str(his.get("degree") or "").strip()
    # 柱讀框：他還沒點名 C3-3 時，不准把 geom 代號印成 C3-3-*（會像他說）
    # 他已點 C3-3-x：左框主標以他說為準；柱讀只當副標，不准蓋過口述尾碼
    geom_show = str(geom.get("geom_degree") or "").strip()
    if not deg_his.startswith("C3") and geom_show.startswith("C3"):
        geom_show = "C內小波①②（未稱C3）"
    # 中排左＝說明框（層級／色線）；不准再疊進上方縮圖K
    hierarchy = str(ladder.get("teach_box") or "他說現在層級（大→小）")
    now_vis = str(ladder.get("now") or deg_his or "").strip()
    if now_vis and now_vis not in hierarchy:
        hierarchy = f"{hierarchy}\n此刻＝{now_vis}"
    if deg_his.startswith("C3-3-") and geom_show and geom_show != deg_his:
        geom_line = f"日K小波柱讀：{geom_show}（口述此刻＝{deg_his}）"
    else:
        geom_line = f"日K小波：{geom_show or '—'}（柱上自讀，非口述）"
    swatch_rows = [
        ("#ffab40", "━━", "細浪＝縮圖 B→①…⑤"),
        ("#ea80fc", "━━", "他說 B→今（淡）"),
        ("#ea80fc", "┅┅", "預估"),
    ]
    if c_sub.get("ok"):
        swatch_rows.append(("#ce93d8", "━━", "c5細點"))
    if need_alt:
        swatch_rows.append(("#69f0ae", "┅┅", "另前提"))
    ax_leg.text(
        0.04,
        0.96,
        "\n".join([hierarchy, geom_line, str(alt_note)]),
        transform=ax_leg.transAxes,
        ha="left",
        va="top",
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        linespacing=1.28,
        zorder=3,
    )
    # 色線樣本（不准寫紫／橙國字；色自己秀）
    _sw_y0 = 0.42
    for i, (col, mark, role) in enumerate(swatch_rows):
        ax_leg.text(
            0.04,
            _sw_y0 - i * 0.11,
            f"{mark}  {role}",
            transform=ax_leg.transAxes,
            ha="left",
            va="top",
            fontproperties=_fp(9, "bold"),
            color=col,
            zorder=4,
        )

    want_dates = {
        _ymd(bars[i_b_peak].get("date")),
        _ymd(bars[i_bhi].get("date")),
        _ymd(bars[i_c].get("date")),
        _ymd(bars[i_c1].get("date")),
        _ymd(bars[i_c2].get("date")),
        _ymd(bars[-1].get("date")),
    }
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want_dates or i % 3 == 0:
            if i not in t2:
                t2.append(i)
                l2.append(_md(d))
    t2, l2 = _sparse_xticks(t2, l2, min_gap=2)
    # 右欄飆預測字往右移後，xlim 要夠寬，不准裁掉標籤
    _micro_x_right = max(n + 8.6, float(tip.get("xlim_right") or n) + 2.0)
    ax.set_xlim(x_left, _micro_x_right)
    _paint_right_rail_panel(ax, x0=float(n) + 0.35, x1=float(_micro_x_right))
    _paint_right_rail_panel(axv, x0=float(n) + 0.35, x1=float(_micro_x_right))
    # 超級近窗 y：上方多留空給層級標，下方給小波①／預估端；雙底色價也要進窗
    sr = zone.get("sr") or {}
    sr_skip = zone.get("sr_skip") or {}
    zone_ys = [
        float(v)
        for v in (
            sr.get("support"),
            sr.get("resist"),
            zone.get("y_excl_lo"),
            zone.get("y_excl_hi"),
            *list(tw_supports),
        )
        if v is not None
    ]
    y_bot = min(
        [c_lo, float(tip.get("fut_y") or c_lo), float(tip.get("lab_y") or c_lo)] + zone_ys
    ) - (c_hi - c_lo) * 0.18
    y_top = max([c_hi] + zone_ys) + (c_hi - c_lo) * 0.34
    ax.set_ylim(y_bot, y_top)
    tip_anchor = tip.get("anchor_y")
    tip_skip: set = set()
    right_notes = [
        {
            "x": i_b_peak,
            "y": y_b_peak,
            "text": f"大B末＝假突破 {_px(y_b_peak)}",
            "color": "#40c4ff",
        },
        {"x": i_now, "y": float(closes[i_now]), "text": f"今 {_px(closes[i_now])}", "color": "#ea80fc"},
    ]
    # 超近圖上不准浮預估標 → 端點錨改上右欄（跟遠窗同一套）
    if tip_anchor is not None:
        right_notes.append(
            {
                "x": 0,
                "y": float(tip_anchor),
                "text": _biaoke_pred_label(
                    float(tip_anchor),
                    _level_break_tag(float(tip_anchor), c_seg_lows),
                ),
                "color": "#ea80fc",
            }
        )
        tip_skip.add(round(float(tip_anchor), 1))
    # 他最新錨（虛線梯）上右欄；跟著題旨換，不准寫死 45546／44210
    for anch in tip_anchors:
        if round(float(anch), 1) in tip_skip:
            continue
        right_notes.append(
            {
                "x": 0,
                "y": float(anch),
                "text": _biaoke_pred_label(
                    float(anch), _level_break_tag(float(anch), c_seg_lows)
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    if c_sub.get("ok"):
        right_notes.append(
            {
                "x": int(c_sub["i_c4_hi"]),
                "y": float(c_sub["y_c4"]),
                "text": f"c4細 {_px(c_sub['y_c4'])}",
                "color": "#ce93d8",
            }
        )
        right_notes.append(
            {
                "x": int(c_sub["i_c5_lo"]),
                "y": float(c_sub["y_c5"]),
                "text": f"c5細 {_px(c_sub['y_c5'])}",
                "color": "#ce93d8",
            }
        )
    right_notes.extend(
        _tw_pred_right_notes(
            pack, n=n, lows=c_seg_lows, tip_skip=tip_skip, bars=bars
        )
    )
    have_ys = {round(float(n0["y"]), 1) for n0 in right_notes} | tip_skip
    for key, col in (("resist", "#4dd0e1"), ("support", "#4dd0e1")):
        yv = sr_skip.get(key)
        if yv is None:
            continue
        if round(float(yv), 1) in have_ys:
            continue
        right_notes.append(
            {
                "x": 0,
                "y": float(yv),
                "text": _biaoke_pred_label(float(yv)),
                "color": col,
            }
        )
        have_ys.add(round(float(yv), 1))
    # 右標略往左：超近中排已給八浪／說明，右欄仍不准被裁掉
    x_micro_col = float(n) + 1.55
    try:
        x_micro_col = max(x_micro_col, float(tip.get("fut_x") or n) + 0.35)
    except (TypeError, ValueError):
        pass
    _place_live_right_labels(
        ax,
        right_notes,
        n=n,
        ymin=y_bot,
        ymax=y_top,
        fp=_fp,
        level_dash=True,
        # 與遠窗同比例間距；不准 520 絕對 floor 把右標擠掉
        min_gap=(y_top - y_bot) * 0.055,
        x_col=x_micro_col,
    )
    _finish_last_twii_candle(
        ax,
        i_now=i_now,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_up_taiwan,
        ymin=y_bot,
        ymax=y_top,
    )
    axv.set_ylim(0, (max(vols[i_b_peak:]) if any(vols[i_b_peak:]) else 1) * 1.4)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    vz_y = (
        f"黃＝最大量{_md(bars[int(i_vmax)].get('date'))} {_px(highs[int(i_vmax)])}～{_px(lows[int(i_vmax)])}"
        if i_vmax is not None
        else "黃＝最大量日高低"
    )
    vz_c = (
        f"青＝飆預測{_px(sr['support']) if sr.get('support') is not None else '—'}～"
        f"{_px(sr['resist']) if sr.get('resist') is not None else '—'}"
    )
    # 不准 [:40] 把「C3-3-4」裁成「C3-3」；尾碼必須完整
    _ol = str(ladder.get("one_line") or "現在走到：C進行中")
    _now = str(ladder.get("now") or "").strip()
    if len(_ol) > 52 and _now and _ol.endswith(_now):
        _ol = f"現在走到：…→{_now}"
    elif len(_ol) > 52:
        _ol = _ol[:51] + "…"
    _paint_teach_hud(
        fig,
        title="第3張・超近窗　C內細浪①～⑤（對齊縮圖・不取代大ABC）",
        chips=[
            (vz_y, "#ffd54f"),
            (vz_c, "#4dd0e1"),
            ("細浪①～⑤＝縮圖", "#ce93d8"),
            ("C走完≠新五波升", "#ffab91"),
        ],
        meta=f"{_ol}｜{_macro_wave_calendar_line()}",
        fp=_fp,
    )
    _paint_teach_foot_bar(fig, y=0.0, height=0.042)
    # 上K／中說明＋八浪／下量：頁邊鎖同一套
    fig.subplots_adjust(
        left=_TEACH_FIG_LEFT,
        right=_TEACH_FIG_RIGHT,
        top=_TEACH_FIG_TOP,
        bottom=0.06,
    )
    _paint_teach_query_stamp(
        fig, bars, pack=pack, close=closes[-1], fp=_fp, x=0.995, y=0.855
    )
    foot_m = str(ladder.get("now_line") or (pack.get("thesis") or ""))[:64]
    fig.text(
        0.03,
        0.012,
        f"{foot_m}｜{_macro_wave_calendar_line()}｜上＝縮圖K｜中＝說明＋八浪｜下＝量｜C走完≠新五波升",
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    # 中排右＝八浪縮圖（與說明同列、在K下方）；直接畫進 host，不准 hide 後被 tight 裁掉
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_eight_wave_now_key(pack),
        detail=True,
        c_flash=True,
        flash_pivots=flash_pivots,
        ax=ax_wave_host,
        title="八浪・C閃",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    # 回填 pack 方便摘要（呼叫端可忽略）
    pack["micro_degree_his"] = his.get("degree") or ""
    pack["micro_degree_geom"] = geom.get("geom_degree") or ""
    pack["micro_alt"] = "1" if need_alt else "0"
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _align_us_to_twii_dates(
    us_rows: Sequence[Dict[str, Any]], bars: Sequence[Dict[str, Any]]
) -> Dict[str, List[float]]:
    """美股日K對齊加權交易日索引；缺日 OHLC 用前值填；量只計有真柱的日（缺日量＝0）。"""
    by = {_ymd(r.get("date")): r for r in us_rows}
    opens: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    volumes: List[float] = []
    last: Optional[Dict[str, Any]] = None
    for r in bars:
        d = _ymd(r.get("date"))
        hit = by.get(d)
        if hit and float(hit.get("close") or 0) > 0:
            last = hit
            volumes.append(float(hit.get("volume") or 0))
        else:
            # 美股休／缺日：價可延前收對齊軸，量不准假灌
            volumes.append(0.0)
        if last:
            opens.append(float(last.get("open") or last.get("close") or 0))
            highs.append(float(last.get("high") or last.get("close") or 0))
            lows.append(float(last.get("low") or last.get("close") or 0))
            closes.append(float(last.get("close") or 0))
        else:
            opens.append(float("nan"))
            highs.append(float("nan"))
            lows.append(float("nan"))
            closes.append(float("nan"))
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}


def _render_us_compare_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具④外圍對照：加權近窗 vs 費半（同月日軸；波浪各自轉折）。

    缺日K會先 _ensure_us_index_daily 自己補。
    上下同一條加權月／日軸；費半⑤／A／B／C 用費半自己高低，不准抄加權 A／B 日。
    """
    try:
        import math

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from biaoke_wave import _load_twii_bars
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("外圍教具補資料略過")
    # 與遠／近／超近同一套：盤中 MIS 加權疊柱
    bars = _twii_bars_for_teach(db_path, 120, pack)
    if len(bars) < 12 or not save_path:
        return ""
    i0 = (
        _bar_index_by_ymd(bars, "20260929")
        or _bar_index_by_ymd(bars, "20260925")
        or 0
    )
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    sox = _load_us_daily(db_path, "SOX", "20260920")
    if (pack or {}).get("live_sox"):
        sox = _merge_live_sox_display_bar(sox, (pack or {}).get("live_sox"))
    ixic = _load_us_daily(db_path, "IXIC", "20260920")
    if not anc or (len(sox) < 5 and len(ixic) < 5):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = anc["highs"], anc["lows"], anc["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i5, i_alow, i_bhi, i_c = anc["i5"], anc["i_alow"], anc["i_bhi"], anc["i_c"]
    i_now = anc["i_now"]
    y5, y_alow, y_bhi, y_now = anc["y5"], anc["y_alow"], anc["y_bhi"], anc["y_now"]

    sox_a = _align_us_to_twii_dates(sox, bars)
    ix_a = _align_us_to_twii_dates(ixic, bars)
    sox_o, sox_h, sox_l, sox_c = sox_a["open"], sox_a["high"], sox_a["low"], sox_a["close"]
    ix_c = ix_a["close"]
    sox_anc = _sox_abc_anchors_on_axis(sox_h, sox_l, sox_c, i5_hint=i5)

    fig, (ax, axu, axv) = plt.subplots(
        3,
        1,
        figsize=(15.6, 10.8),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(3.0, 3.0, 1.05), hspace=0.05),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_teach_axes((ax, axu, axv))
    for a in (ax, axu, axv):
        a.tick_params(labelsize=10)

    # 上：加權＋⑤／A／B／C進行中（中段不准標成 C 已完）
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    _wave_line(ax, [i5, i_alow], [y5, y_alow], "#ff8a80", lw=2.25, zorder=7)
    _wave_line(ax, [i_alow, i_bhi], [y_alow, y_bhi], "#40c4ff", lw=2.25, zorder=7)
    _wave_line(ax, [i_bhi, i_now], [y_bhi, y_now], "#ea80fc", lw=2.05, zorder=7)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    tip_tw = _paint_c_forecast(
        ax, i_now=i_now, y_now=y_now, y_ref=y_bhi, lows=c_seg_lows, fp=_fp, n=n
    )
    fut_x = float(tip_tw["fut_x"])
    fut_y = float(tip_tw["fut_y"])
    for ii, yy, col in (
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=42, c=col, zorder=8, edgecolors="#fff", linewidths=0.5)
    # 浪名貼尖點；預估標由 _paint_c_forecast 畫
    _pin_pivot_name(
        ax, i5, y5, "大B末／近⑤", "#ff8a80", _fp, side="auto", tip="high", n=n, pad_x=0.35, fontsize=11
    )
    _pin_pivot_name(
        ax, i_alow, y_alow, "近A低", "#ff8a80", _fp, side="auto", tip="low", n=n, pad_x=0.35, fontsize=11
    )
    _pin_pivot_name(
        ax, i_bhi, y_bhi, "近B高", "#40c4ff", _fp, side="auto", tip="high", n=n, pad_x=0.35, fontsize=11
    )
    _pin_pivot_name(
        ax,
        i_c,
        float(closes[i_c]) if i_c < len(closes) else y_now,
        "C起",
        "#ea80fc",
        _fp,
        side="left",
        tip="mid",
        n=n,
        pad_x=0.4,
        fontsize=11,
    )
    _pin_pivot_name(
        ax, i_now, y_now, "C進行中", "#ea80fc", _fp, side="left", tip="mid", n=n, pad_x=0.45, fontsize=11
    )
    ax.set_ylabel("加權近窗", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)

    # 中：費半 K（對齊加權交易日）＋費半自己的⑤／A／B／C
    valid = [i for i, c in enumerate(sox_c) if c == c and c]
    if len(valid) >= 5:
        for i in valid:
            prev_i = next((j for j in range(i - 1, -1, -1) if sox_c[j] == sox_c[j]), None)
            prev_c = sox_c[prev_i] if prev_i is not None else None
            up = candle_up_taiwan(sox_c[i], prev_c, sox_o[i])
            color = _LIVE_UP if up else _LIVE_DOWN
            axu.vlines(i, sox_l[i], sox_h[i], color=color, linewidth=1.1, zorder=3)
            y0, y1 = sorted((sox_o[i], sox_c[i]))
            axu.add_patch(
                plt.Rectangle(
                    (i - 0.34, y0),
                    0.68,
                    max(
                        y1 - y0,
                        (max(x for x in sox_h if x == x) - min(x for x in sox_l if x == x))
                        * 0.0015,
                    ),
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.35,
                    zorder=4,
                )
            )
        if sox_anc:
            s5i, sai, sbi = sox_anc["i5"], sox_anc["i_alow"], sox_anc["i_bhi"]
            s5, sa, sb, sn = (
                sox_anc["y5"],
                sox_anc["y_alow"],
                sox_anc["y_bhi"],
                sox_anc["y_now"],
            )
            axu.plot([s5i, sai], [s5, sa], color="#ff8a80", lw=2.3, zorder=7)
            axu.plot([sai, sbi], [sa, sb], color="#40c4ff", lw=2.3, zorder=7)
            axu.plot([sbi, i_now], [sb, sn], color="#ea80fc", lw=2.1, zorder=7)
            s_fut = sn - (sb - sn) * 0.35
            axu.plot(
                [i_now, fut_x],
                [sn, s_fut],
                color="#ea80fc",
                lw=1.5,
                ls=(0, (4, 2)),
                alpha=0.75,
                zorder=6,
            )
            for ii, yy, col in (
                (s5i, s5, "#ff8a80"),
                (sai, sa, "#ff8a80"),
                (sbi, sb, "#40c4ff"),
                (i_now, sn, "#ea80fc"),
            ):
                axu.scatter([ii], [yy], s=42, c=col, zorder=8, edgecolors="#fff", linewidths=0.5)
            span_s = max(x for x in sox_h if x == x) - min(x for x in sox_l if x == x)
            sox_pred_ys = [
                float(r.get("level"))
                for r in ((pack or {}).get("pred_levels") or {}).get("sox") or []
                if r.get("level") is not None
            ]
            y_lo_s = min([x for x in sox_l if x == x] + sox_pred_ys + [float(s_fut)])
            y_hi_s = max([x for x in sox_h if x == x] + sox_pred_ys)
            # 先定 ylim（含他寫死 10445／9865）再釘浪名；右欄真價延伸才對得上
            axu.set_ylim(y_lo_s - span_s * 0.18, y_hi_s + span_s * 0.16)
            # 費半浪名貼尖點；費C／預測點字走右欄（不准再釘「預估↓」假端點）
            _pin_pivot_name(
                axu, s5i, s5, "費⑤", "#ff8a80", _fp, side="auto", tip="high", n=n, pad_x=0.35, fontsize=10
            )
            _pin_pivot_name(
                axu, sai, sa, "費A低", "#ff8a80", _fp, side="auto", tip="low", n=n, pad_x=0.35, fontsize=10
            )
            _pin_pivot_name(
                axu, sbi, sb, "費B高", "#40c4ff", _fp, side="auto", tip="high", n=n, pad_x=0.35, fontsize=10
            )
            axu.axvline(s5i, color="#ff8a80", lw=0.85, ls=(0, (2, 2)), alpha=0.75, zorder=5)
            axu.axvline(sai, color="#ff8a80", lw=0.7, ls=(0, (2, 3)), alpha=0.45, zorder=5)
            axu.axvline(sbi, color="#40c4ff", lw=0.7, ls=(0, (2, 3)), alpha=0.45, zorder=5)
            _paint_sox_thesis_preds(
                axu,
                bars=bars,
                sox_o=sox_o,
                sox_h=sox_h,
                sox_l=sox_l,
                sox_c=sox_c,
                pack=pack,
                fp=_fp,
                i_now=i_now,
                n=n,
                ymin=y_lo_s - span_s * 0.18,
                ymax=y_hi_s + span_s * 0.16,
                now_y=float(sn),
                now_lab=f"費C今{_px(float(sn))}",
            )
    # 納指收盤線陪看（細、不搶 ABC）
    ix_ok = [v for v in ix_c if v == v and v]
    if len(ix_ok) >= 5:
        axu.plot(range(n), ix_c, color="#4fc3f5", lw=1.15, alpha=0.55, zorder=5, label="納指收（陪看）")
    axu.set_ylabel("費半 SOX（同月日・自轉折）", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    leg = axu.legend(
        loc="upper left", fontsize=8, framealpha=0.9, facecolor="#0b0f14", edgecolor="#546e7a"
    )
    if leg is not None:
        for t in leg.get_texts():
            t.set_color(_LIVE_TEXT)
            t.set_fontproperties(_fp(8, "bold"))

    # 外圍一句放左下空白，不准壓右側K
    last_note = str(pack.get("us_note") or "")
    axu.text(
        0.012,
        0.04,
        (last_note[:42] or "費半轉折＝自己高低；軸＝加權月日"),
        transform=axu.transAxes,
        fontproperties=_fp(8, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.22", fc="#0b0f14", ec="#546e7a", lw=0.8, alpha=0.92),
    )
    ladder = _wave_now_ladder(pack)
    teach = (
        f"{ladder.get('one_line') or '他說現在：C進行中'}\n"
        "上下同一月日軸；費半波浪自轉折\n"
        "C＝進行中；虛線＝預估；非買訊"
    )
    ax.text(
        0.012,
        0.04,
        teach,
        transform=ax.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=12,
        linespacing=1.25,
        bbox=dict(boxstyle="round,pad=0.3", fc="#0b0f14", ec="#546e7a", lw=0.85, alpha=0.92),
    )
    # 時間軸：只標關鍵日＋稀疏月日，不准加A+費A疊字
    want = {
        _ymd(bars[i5].get("date")),
        _ymd(bars[i_alow].get("date")),
        _ymd(bars[i_bhi].get("date")),
        _ymd(bars[i_c].get("date")),
        _ymd(bars[-1].get("date")),
    }
    if sox_anc:
        for key in ("i_alow", "i_bhi"):
            want.add(_ymd(bars[int(sox_anc[key])].get("date")))
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want or i % 4 == 0:
            if i not in t2:
                t2.append(i)
                # 單一短註；加權／費半轉折分開看圖上標，軸上不堆
                tag = ""
                if i == i5:
                    tag = "⑤"
                elif i == i_c:
                    tag = "C起"
                elif sox_anc and i == int(sox_anc["i_alow"]):
                    tag = "費A"
                elif sox_anc and i == int(sox_anc["i_bhi"]):
                    tag = "費B"
                l2.append(f"{_md(d)}{tag}")
    ax.set_xlim(-0.5, max(n + 1.2, fut_x + 0.8))
    ax.set_ylim(min(lows) - 520, max(highs) + 900)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel("加權量", fontproperties=_fp(9, "bold"), color=_LIVE_MUTED)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for a in (ax, axu, axv):
        for lab in a.get_yticklabels():
            lab.set_fontproperties(_fp(9, "bold"))
            lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    fig.text(
        0.03,
        0.975,
        f"外圍對照：同月日軸・波浪各自轉折（費半不抄加權A/B）　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.948,
        "下面刻度＝加權交易日的月／日；費半缺日用前收對齊。虛線＝預估續走（非買訊）",
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="top",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_tx60_png(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """TX60 深底裸K＋量柱＋關鍵位（縮圖要讀得懂量價）。"""
    rows = _load_tx60_rows(db_path, 64)
    if len(rows) < 8 or not save_path:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(rows)
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r["volume"]) for r in rows]
    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(14.5, 8.8),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.2, 1.5), hspace=0.05),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    levels = pack.get("key_levels") or {}
    lv_notes = []
    for key, col, lab in _LIVE_LV:
        if key not in levels:
            continue
        lv_notes.append(
            {
                "x": n - 1,
                "y": float(levels[key]),
                "text": f"{lab} {_px(levels[key])}",
                "color": col,
            }
        )
    # 右標水平往左貼K；60 分圖留寬夠長標進軸內
    ax.set_xlim(-0.6, n + 8.0)
    ax.set_ylim(min(lows) - 180, max(highs) + 280)
    _place_live_right_labels(
        ax,
        lv_notes,
        n=n,
        ymin=min(lows) - 180,
        ymax=max(highs) + 280,
        fp=_fp,
        level_dash=True,
        # 比例間距；不准絕對 floor 把真價標互擠掉
        min_gap=(max(highs) - min(lows)) * 0.12,
    )
    axv.set_ylim(0, (max(vols) if vols else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    # 日期軸：60分 ts=YYYYMMDDHHMM
    ticks, labs = [], []
    for i, r in enumerate(rows):
        ts = str(r.get("ts") or "")
        if len(ts) < 12:
            continue
        if i == 0 or i == n - 1 or i % 8 == 0:
            ticks.append(i)
            labs.append(f"{ts[4:6]}/{ts[6:8]} {ts[8:10]}:00")
    axv.set_xticks(ticks)
    axv.set_xticklabels(labs, fontproperties=_fp(8, "bold"), color=_LIVE_TEXT, rotation=0)
    fig.text(
        0.03,
        0.965,
        "台指期 60 分　深底＋量（C段細微波底圖，不數他沒畫的段）",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    y = 0.07
    for line in (
        str(pack.get("thesis") or ""),
        str(pack.get("vol_note") or ""),
        str(pack.get("turn_note") or ""),
    ):
        if not line.strip():
            continue
        fig.text(
            0.03,
            y,
            line[:78],
            fontproperties=_fp(10, "bold"),
            color=_LIVE_TEXT,
            ha="left",
            va="bottom",
        )
        y -= 0.024
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000:
        return save_path
    return ""


def _score_levels_vs_bar(
    levels: Dict[str, float], high: float, low: float, close: float
) -> str:
    """隔日柱對關鍵位：碰到／守住／跌破。"""
    if not levels or high <= 0 or low <= 0:
        return "還沒走完"
    down = levels.get("tx60_down") or levels.get("tx_night_l")
    swing_lo = levels.get("tx60_swing_lo") or levels.get("tx_night_l")
    swing_hi = levels.get("tx60_swing_hi") or levels.get("tx_night_h")
    hits = 0
    misses = 0
    if swing_lo and low <= float(swing_lo) * 1.002:
        hits += 1
        if close < float(swing_lo) * 0.995:
            misses += 1
    if down and high >= float(down) and close > float(down):
        hits += 1  # 過降軌
    if swing_hi and high >= float(swing_hi) * 0.998 and close < float(swing_hi) * 0.995:
        hits += 1  # 碰高壓回
    if hits and not misses:
        return "對"
    if misses and hits:
        return "偏"
    if misses:
        return "偏"
    return "還沒走完"


def verify_live_hyps_next_day(db_path: str, today: str = "") -> int:
    """隔日官方柱對前一交易日活畫關鍵位。"""
    ensure_tables(db_path)
    day = _ymd(today) or datetime.now(TAIPEI).strftime("%Y%m%d")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    n = 0
    try:
        rows = conn.execute(
            "SELECT slot_id, as_of, key_levels FROM biaoke_open_day_paints "
            "WHERE pending=1 AND as_of!='' AND as_of<? ORDER BY as_of ASC",
            (day,),
        ).fetchall()
        for row in rows:
            try:
                levels = json.loads(row["key_levels"] or "{}")
            except Exception:
                levels = {}
            # 用下一根 TX 日盤或夜盤收對
            bar = conn.execute(
                "SELECT high, low, close FROM futures_daily "
                "WHERE symbol='TX' AND session='regular' AND date>? "
                "ORDER BY date ASC LIMIT 1",
                (row["as_of"],),
            ).fetchone()
            if not bar:
                bar = conn.execute(
                    "SELECT high, low, close FROM futures_daily "
                    "WHERE symbol='TX' AND session='night' AND date>? "
                    "ORDER BY date ASC LIMIT 1",
                    (row["as_of"],),
                ).fetchone()
            if not bar:
                continue
            verdict = _score_levels_vs_bar(
                levels, float(bar[0]), float(bar[1]), float(bar[2])
            )
            if verdict == "還沒走完":
                continue
            conn.execute(
                "UPDATE biaoke_open_day_paints SET pending=0, verdict=?, checked_at=? "
                "WHERE slot_id=?",
                (verdict, _now(), row["slot_id"]),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def verify_live_hyps_with_speech(db_path: str, snippet: str) -> int:
    """他說現況位階時：活畫敘事粗對。"""
    ensure_tables(db_path)
    if not looks_like_level_now(snippet):
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    n = 0
    try:
        rows = conn.execute(
            "SELECT slot_id, thesis, wait_struct FROM biaoke_open_day_paints "
            "WHERE pending=1 ORDER BY created_at ASC"
        ).fetchall()
        for row in rows:
            blob = f"{row['thesis']} {row['wait_struct']}"
            verdict = _score_against_next(blob, snippet)
            if verdict == "還沒走完":
                continue
            conn.execute(
                "UPDATE biaoke_open_day_paints SET pending=0, verdict=?, checked_at=? "
                "WHERE slot_id=?",
                (verdict, _now(), row["slot_id"]),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def prepare_wave_live_pack(
    db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """波浪／教具共用準備：ensure 加權／費半日K＋組 pack＋盤中 MIS／SOX 疊柱。

    話筒遠／近／超近同按一次只准跑一回；paint 可帶 pack 進來不再重抓。
    盤中未收不當官方收；不寫庫。
    """
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    if db_path:
        try:
            _ensure_teach_index_bars(db_path)
        except Exception:
            logger.debug("prepare_wave ensure 略過", exc_info=True)
    pack = dict(_build_live_pack(db_path, now=dt) or {})
    try:
        from live_quote import fetch_mis_index_quote, is_live_merge_window

        if is_live_merge_window(dt):
            live_tw = fetch_mis_index_quote(fresh=True)
            if live_tw:
                pack["live_twii"] = live_tw
    except Exception:
        logger.debug("prepare_wave 盤中加權略過", exc_info=True)
    try:
        from us_overnight import fetch_live_sox_display_bar

        live_sox = fetch_live_sox_display_bar(dt)
        if live_sox:
            pack["live_sox"] = live_sox
    except Exception:
        logger.debug("prepare_wave 盤中費半略過", exc_info=True)
    pack["query_at"] = dt.isoformat()
    pack["_prep_now"] = dt
    return pack


def paint_open_day_hypothesis(
    db_path: str,
    *,
    now: Optional[datetime] = None,
    force: bool = False,
    panels: str = "full",
    pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """稀疏槽活畫：日盤／夜盤／納指費半＋量價裸K。空白鍵可取檔送教具（非買訊）。

    panels:
      - full＝遠／近／超近＋外圍＋TX60（排程／ingest）
      - trio＝話筒熱路徑只畫遠／近／超近（減壓；外圍用已存）
      - far／near／micro＝單窗（話筒 send∥paint：遠先畫先送）
    pack：呼叫端已 prepare_wave_live_pack 時傳入，不准再 ensure／重抓。
    """
    out: Dict[str, Any] = {"ok": False, "path": "", "tx60_path": "", "slot_id": ""}
    if not db_path:
        return out
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_LEVEL_LEARN_LIVE") != "1":
        return {**out, "skipped": "pytest"}
    mode = str(panels or "full").strip().lower()
    if mode not in {"full", "trio", "far", "near", "micro"}:
        mode = "full"
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    if isinstance(pack, dict) and pack.get("_prep_now") is not None:
        try:
            dt = pack["_prep_now"]
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=TAIPEI)
            else:
                dt = dt.astimezone(TAIPEI)
        except Exception:
            pass
    ymd = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_tw_open_calendar_day
    except Exception:
        return {**out, "error": "calendar"}

    slot_id = _sparse_slot_id(dt, force=force)
    if not slot_id:
        return {**out, "skipped": "off_hours"}

    # 休市：只准 night／dawn／force（承接周五夜）；日盤槽跳過
    open_day = is_tw_open_calendar_day(ymd)
    slot_kind = slot_id.rsplit("-", 1)[-1] if not force else "force"
    if not force and not open_day and slot_kind not in {"night", "dawn"}:
        # 週六 dawn 可對周五；否則跳過
        yest = (dt - timedelta(days=1)).strftime("%Y%m%d")
        if not (slot_kind == "dawn" and is_tw_open_calendar_day(yest)):
            return {**out, "skipped": "closed"}

    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM biaoke_open_day_paints WHERE slot_id=?", (slot_id,)
        ).fetchone()
        if hit and not force:
            return {**out, "skipped": "slot_done", "slot_id": slot_id}
    finally:
        conn.close()

    # 隔日對質先跑（活化前筆）
    try:
        verify_live_hyps_next_day(db_path, ymd)
    except Exception:
        logger.exception("活畫隔日對質略過")

    if isinstance(pack, dict) and pack:
        pack = dict(pack)
        pack.pop("_prep_now", None)
        if not pack.get("query_at"):
            pack["query_at"] = dt.isoformat()
    else:
        # 三張必畫最新交易日縮圖K：先同步加權／費半官方日，再組 pack／盤中疊柱
        pack = prepare_wave_live_pack(db_path, now=dt)
        pack.pop("_prep_now", None)
    thesis = pack.get("thesis") or ""
    wait_struct = pack.get("wait_struct") or ""
    turn_note = pack.get("turn_note") or ""
    vol_note = pack.get("vol_note") or ""
    intent_note = pack.get("intent_note") or ""
    us_note = pack.get("us_note") or ""
    key_levels = pack.get("key_levels") or {}

    # 排程 full 才跑內部試畫；美股日K已在 _ensure_teach_index_bars
    if mode == "full":
        try:
            from biaoke_forecast import snapshot_and_score_twii

            snapshot_and_score_twii(db_path, ymd)
        except Exception:
            logger.exception("開市日內部試畫略過")

    snap_root = _paint_dir(db_path)
    near_path = os.path.join(snap_root, f"{slot_id}-near.png")
    far_path = os.path.join(snap_root, f"{slot_id}-far.png")
    us_path = os.path.join(snap_root, f"{slot_id}-us.png")
    micro_path = os.path.join(snap_root, f"{slot_id}-micro.png")
    chart_path = os.path.join(snap_root, f"{slot_id}.png")  # 兼容＝近窗特寫
    tx60_path = os.path.join(snap_root, f"{slot_id}-tx60.png")
    # 話筒 send∥paint：遠先畫；trio／full 也改遠→近→超近，與送出順序一致
    do_far = mode in {"full", "trio", "far"}
    do_near = mode in {"full", "trio", "near"}
    do_micro = mode in {"full", "trio", "micro"}

    if do_far:
        try:
            got_far = _render_twii_far_dark(db_path, far_path, pack)
            far_path = got_far or ""
        except Exception:
            logger.exception("遠窗教具渲圖失敗")
            far_path = ""
    else:
        far_path = ""

    if do_near:
        try:
            got_near = _render_twii_live_dark(db_path, near_path, pack)
            near_path = got_near or ""
            # 主檔＝近窗（舊讀 chart_path 的路徑仍可用）
            if near_path:
                try:
                    import shutil

                    shutil.copy2(near_path, chart_path)
                except Exception:
                    chart_path = near_path
            else:
                chart_path = ""
        except Exception:
            logger.exception("近窗特寫渲圖失敗")
            near_path = chart_path = ""
    else:
        near_path = ""
        chart_path = ""

    if do_micro:
        try:
            got_micro = _render_twii_super_near_dark(db_path, micro_path, pack)
            micro_path = got_micro or ""
        except Exception:
            logger.exception("超級近窗渲圖失敗")
            micro_path = ""
    else:
        micro_path = ""

    if mode == "full":
        try:
            got_us = _render_us_compare_dark(db_path, us_path, pack)
            us_path = got_us or ""
        except Exception:
            logger.exception("外圍對照渲圖失敗")
            us_path = ""
        try:
            got60 = _render_tx60_png(db_path, tx60_path, pack)
            tx60_path = got60 or ""
        except Exception:
            logger.exception("TX60 活畫渲圖失敗")
            tx60_path = ""
    else:
        # 話筒 trio／far：外圍／TX60 留空，ON CONFLICT 保留庫內舊檔
        us_path = ""
        tx60_path = ""

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_open_day_paints(
                slot_id, as_of, thesis, wait_struct, turn_note, vol_note,
                key_levels, chart_path, tx60_path, us_note,
                far_path, near_path, us_path, micro_path, pending, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(slot_id) DO UPDATE SET
                thesis=excluded.thesis,
                wait_struct=excluded.wait_struct,
                turn_note=excluded.turn_note,
                vol_note=excluded.vol_note,
                key_levels=excluded.key_levels,
                chart_path=CASE WHEN excluded.chart_path!='' THEN excluded.chart_path
                    ELSE biaoke_open_day_paints.chart_path END,
                tx60_path=CASE WHEN excluded.tx60_path!='' THEN excluded.tx60_path
                    ELSE biaoke_open_day_paints.tx60_path END,
                us_note=excluded.us_note,
                far_path=CASE WHEN excluded.far_path!='' THEN excluded.far_path
                    ELSE biaoke_open_day_paints.far_path END,
                near_path=CASE WHEN excluded.near_path!='' THEN excluded.near_path
                    ELSE biaoke_open_day_paints.near_path END,
                us_path=CASE WHEN excluded.us_path!='' THEN excluded.us_path
                    ELSE biaoke_open_day_paints.us_path END,
                micro_path=CASE WHEN excluded.micro_path!='' THEN excluded.micro_path
                    ELSE biaoke_open_day_paints.micro_path END,
                pending=1,
                verdict='',
                checked_at='',
                created_at=excluded.created_at
            """,
            (
                slot_id,
                ymd,
                thesis,
                wait_struct,
                turn_note,
                vol_note,
                json.dumps(key_levels, ensure_ascii=False),
                chart_path or "",
                tx60_path or "",
                us_note,
                far_path or "",
                near_path or "",
                us_path or "",
                micro_path or "",
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # 回傳 as_of＝加權最新已收柱日（或盤中疊加顯示日）；不准用日曆 ymd 把週末查詢寫成假收盤日
    chart_as_of = _ymd(pack.get("chart_as_of")) or _twii_chart_as_of(db_path) or ymd
    try:
        live_bars = _twii_bars_for_teach(db_path, 8, pack)
        if live_bars:
            chart_as_of = _ymd(live_bars[-1].get("date")) or chart_as_of
    except Exception:
        pass
    logger.info(
        "活畫 slot=%s thesis=%s far=%s near=%s micro=%s us=%s tx60=%s as_of=%s",
        slot_id,
        thesis,
        bool(far_path),
        bool(near_path),
        bool(micro_path),
        bool(us_path),
        bool(tx60_path),
        chart_as_of,
    )
    return {
        "ok": bool(near_path or far_path or us_path or micro_path or tx60_path),
        "path": chart_path or near_path or "",
        "far_path": far_path or "",
        "near_path": near_path or "",
        "micro_path": micro_path or "",
        "us_path": us_path or "",
        "tx60_path": tx60_path or "",
        "thesis": thesis,
        "wait_struct": wait_struct,
        "turn_note": turn_note,
        "vol_note": vol_note,
        "intent_note": intent_note,
        "morph_note": pack.get("morph_note") or "",
        "fib_note": pack.get("fib_note") or "",
        "us_note": us_note,
        "key_levels": key_levels,
        "micro_degree_his": pack.get("micro_degree_his") or "",
        "micro_degree_geom": pack.get("micro_degree_geom") or "",
        "slot_id": slot_id,
        "as_of": chart_as_of,
        "query_at": str(pack.get("query_at") or dt.isoformat()),
        "thesis_as_of": str(pack.get("thesis_as_of") or ""),
        "panels": mode,
    }


def latest_teach_kit(db_path: str) -> Dict[str, str]:
    """話筒空白鍵教具：取最近一槽已存遠／近／超級近／外圍路徑（有檔才回）。

    失敗回空 dict；不准擋主摘要。不在這裡重渲（重渲走 paint_open_day_hypothesis）。
    """
    out: Dict[str, str] = {
        "far_path": "",
        "near_path": "",
        "micro_path": "",
        "us_path": "",
        "thesis": "",
        "slot_id": "",
        "as_of": "",
    }
    if not db_path:
        return out
    try:
        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT slot_id, as_of, thesis, far_path, near_path, us_path, "
                "COALESCE(micro_path,'') "
                "FROM biaoke_open_day_paints "
                "ORDER BY created_at DESC, slot_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception("讀教具路徑失敗")
        return out
    if not row:
        return out
    far, near, us, micro = (
        str(row[3] or ""),
        str(row[4] or ""),
        str(row[5] or ""),
        str(row[6] or ""),
    )
    out["slot_id"] = str(row[0] or "")
    out["as_of"] = str(row[1] or "")
    out["thesis"] = str(row[2] or "")[:180]
    if far and os.path.isfile(far):
        out["far_path"] = far
    if near and os.path.isfile(near):
        out["near_path"] = near
    if micro and os.path.isfile(micro):
        out["micro_path"] = micro
    if us and os.path.isfile(us):
        out["us_path"] = us
    return out


def teach_kit_needs_restore(db_path: str) -> bool:
    """庫有教具列，但遠／近／超近有檔路徑在磁碟缺 → True。

    無列／路徑欄全空＝False（不准憑空硬補）。latest_teach_kit 已跳過缺檔。
    """
    if not db_path:
        return False
    try:
        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT far_path, near_path, COALESCE(micro_path,'') "
                "FROM biaoke_open_day_paints "
                "ORDER BY created_at DESC, slot_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    if not row:
        return False
    wrote = [str(p or "").strip() for p in row]
    if not any(wrote):
        return False
    kit = latest_teach_kit(db_path)
    return not all(str(kit.get(k) or "").strip() for k in ("far_path", "near_path", "micro_path"))


def maybe_restore_teach_kit(db_path: str) -> Dict[str, Any]:
    """開機／閒置：庫有列、trio 檔缺才 force 補渲；檔齊不重畫。不擋 /health。"""
    out: Dict[str, Any] = {"ok": False, "restored": False}
    if not teach_kit_needs_restore(db_path):
        return {**out, "ok": True, "skipped": "present_or_empty"}
    try:
        painted = paint_open_day_hypothesis(db_path, force=True, panels="trio")
    except Exception:
        logger.exception("教具缺檔補渲失敗")
        return {**out, "error": "exception"}
    ok = bool(painted.get("ok"))
    return {
        **out,
        **painted,
        "ok": ok,
        "restored": ok,
    }


def maybe_paint_open_day_after_ingest(
    db_path: str, *, force: bool = False
) -> Dict[str, Any]:
    """抓文／輪詢後：稀疏槽活畫；force＝他說新點位／話筒按鍵時強制重渲。

    稀疏窗外／休市略過時：若庫有列但 trio 檔缺，順便補渲（部署後週末不必逼話筒現畫）。
    """
    try:
        verify_live_hyps_next_day(db_path)
    except Exception:
        logger.exception("活畫隔日對質鉤子失敗")
    try:
        painted = paint_open_day_hypothesis(db_path, force=force)
        if painted.get("ok") or force:
            return painted
        if painted.get("skipped") in {"off_hours", "closed", "slot_done"}:
            restored = maybe_restore_teach_kit(db_path)
            if restored.get("restored"):
                return restored
        return painted
    except Exception:
        logger.exception("開市日活畫鉤子失敗")
        return {"ok": False, "error": "exception"}


def _level_events_with_prices(
    events: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """只收：大盤現況位階文＋文內有他點的真價（不准發明）。"""
    out: List[Dict[str, Any]] = []
    try:
        from biaoke_walk import extract_index_levels
    except Exception:
        return out
    for ev in events or []:
        if ev.get("club") or ev.get("kind") == "bystander":
            continue
        text = str(ev.get("text") or "")
        if not looks_like_level_now(text):
            continue
        levels = extract_index_levels(text) or []
        if not levels:
            continue
        out.append(
            {
                "id": str(ev.get("id") or ev.get("post_id") or "").strip(),
                "date": str(ev.get("date") or "").strip(),
                "time": str(ev.get("time") or "").strip(),
                "text": text,
                "levels": levels,
                "kind": str(ev.get("kind") or "post"),
            }
        )
    return out


def maybe_push_level_teach_update(
    db_path: str, events: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """他新文／自回提到大盤最新點位 → 強制重畫遠近超近 → 雙人推播文＋圖。

    只推他確實寫出的價；不准補假點。同一則 post_id 不重推。不是買訊。
    """
    stats: Dict[str, Any] = {
        "seen": 0,
        "pushed": 0,
        "photos": 0,
        "skipped": 0,
        "painted": False,
    }
    if not db_path or not events:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_LEVEL_LEARN_LIVE") != "1":
        return {**stats, "skipped": "pytest"}
    rows = _level_events_with_prices(events)
    stats["seen"] = len(rows)
    if not rows:
        return stats
    # 同一輪取最新一則（主文／自回都算）
    row = rows[-1]
    post_id = str(row.get("id") or "").strip()
    if not post_id:
        return {**stats, "skipped": "no_id"}
    dedupe = f"level_teach:{post_id}"
    try:
        from biaoke_alert import _claim_chat_dedupe, _send_family, _send_family_photos
        from config import allowed_telegram_uids
    except Exception:
        logger.exception("位階教具推播模組略過")
        return {**stats, "error": "import"}
    # 先對白名單第一人占位；若已推過同則就整輪略過
    uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    if not uids:
        return {**stats, "skipped": "no_uid"}
    # 同日同組價＝重複，不重推（主文＋自回各寫一次仍只發一輪）
    as_of_d = str(row.get("date") or "").replace("-", "")[:8]
    lv_fp = "|".join(
        sorted(
            {
                f"{round(float(h.get('level')), 1)}"
                for h in (row.get("levels") or [])
                if h.get("level") is not None
            }
        )
    )
    if as_of_d and lv_fp:
        fp_key = f"level_teach:fp:{as_of_d}:{lv_fp}"
        if not _claim_chat_dedupe(uids[0], fp_key, db_path=db_path):
            stats["skipped"] = "same_levels"
            return stats
    # 用 alert 表級鍵（不綁單一 chat）— 佔第一人失敗＝已送過
    if not _claim_chat_dedupe(uids[0], dedupe, db_path=db_path):
        stats["skipped"] = 1
        return stats
    # 強制重畫：說法＋點位進教具
    painted = maybe_paint_open_day_after_ingest(db_path, force=True)
    stats["painted"] = bool(painted.get("ok"))
    if stats["painted"]:
        kit = {
            "far_path": str(painted.get("far_path") or ""),
            "near_path": str(painted.get("near_path") or ""),
            "micro_path": str(painted.get("micro_path") or ""),
            "us_path": str(painted.get("us_path") or ""),
            "thesis": str(painted.get("thesis") or "")[:180],
            "as_of": str(painted.get("as_of") or ""),
        }
    else:
        kit = latest_teach_kit(db_path)
    lv_bits = []
    for hit in row.get("levels") or []:
        try:
            lv = float(hit.get("level"))
        except (TypeError, ValueError):
            continue
        role = str(hit.get("role") or "點位")
        lv_bits.append(f"{role}{lv:g}")
    snip = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()[:280]
    when = f"{row.get('date') or ''} {row.get('time') or ''}".strip()
    from tg_layout import html_escape

    html = (
        "<b>飆大更新・大盤點位</b>\n"
        f"{html_escape(when)}（{html_escape(str(row.get('kind') or 'post'))}）\n"
        f"點位：{html_escape('／'.join(lv_bits) if lv_bits else '—')}\n"
        f"{html_escape(snip)}\n"
        "<i>已重畫遠／近／超近教具。不是買訊。</i>"
    )
    # 第一人已 claim；其餘人用同 key 再 claim
    sent = 0
    try:
        # 補第二人 claim 後送（第一人已 claim，_send_family 會再 claim 每人）
        # 為避免第一人被 _send_family 再擋：用獨立文案鍵
        text_key = f"{dedupe}:text"
        sent = _send_family(html, dedupe_key=text_key, db_path=db_path)
        stats["pushed"] = int(sent or 0)
    except Exception:
        logger.exception("位階教具文字推播失敗")
    paths = []
    caps = []
    for key, head in (
        ("far_path", "遠窗・波浪／切割（非買訊）"),
        ("near_path", "近窗・細微波／量價（非買訊）"),
        ("micro_path", "超近窗・日K小波（非買訊）"),
    ):
        p = str(kit.get(key) or "").strip()
        if p and os.path.isfile(p):
            paths.append(p)
            caps.append(head)
    if paths:
        try:
            n_photo = _send_family_photos(
                paths,
                captions=caps,
                dedupe_key=f"{dedupe}:photos",
                db_path=db_path,
            )
            stats["photos"] = int(n_photo or 0)
        except Exception:
            logger.exception("位階教具圖推播失敗")
    logger.info(
        "位階教具更新推播 post=%s levels=%s sent=%s photos=%s painted=%s",
        post_id,
        lv_bits,
        stats["pushed"],
        stats["photos"],
        stats["painted"],
    )
    return stats
