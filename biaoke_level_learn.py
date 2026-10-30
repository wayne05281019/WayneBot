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

# 現況位階／細微波說話（他講大盤走法時）
_LEVEL_NOW = re.compile(
    r"("
    r"波浪位階|細微波|主跌段|初跌段|末跌段|"
    r"C\s*波|C\d|C3-\d|B\s*波|B-[abc]|"
    r"橫台|中繼站|第[一二三四五1-5]波|第[1-5]小浪|"
    r"1-4\s*重疊|鐵律|破底翻|第二隻腳|第二支腳|"
    r"目前只是|目前是走|現在是走|確認.*發動|準備啟動"
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
    if re.search(r"C3-\d|細微波|波浪位階|主跌段|橫台整理", blob):
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
    """粗對質：下一句是否延續／改口／打臉。不是買訊。"""
    a = (prev_snip or "").lower()
    b = (next_snip or "").lower()
    if not a or not b:
        return "還沒走完"
    # 改口／重標
    if any(k in b for k in ("重新修訂", "動態修正", "穿刺原規劃", "改口")):
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


def _latest_level_thesis(db_path: str) -> Dict[str, str]:
    """從最近位階 snap／貼文抽出活畫題旨（可遷移結構語，不背死價當唯一）。"""
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT snippet, as_of, post_id FROM biaoke_level_snaps "
            "ORDER BY as_of DESC, created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    snip = str((row["snippet"] if row else "") or "")
    thesis = "大盤細微波位階待更新"
    wait = "等下一結構位（前波低／降軌破／1-4重疊）"
    if "C3-3-1" in snip and "C3-3-2" in snip:
        thesis = "C3-3 主跌進行中（1→2）"
        wait = "結構下一測＝前波低（他點過的相對錨）；無爆量≠止穩"
    elif "C3-3" in snip:
        thesis = "C3-3 主跌發動／進行中"
        wait = "段內細微切換＋前波低是否碰到"
    elif "橫台" in snip or "中繼" in snip:
        thesis = "橫台中繼（浪4區敘事）"
        wait = "中繼後原方向；不過壓／拖太久→主跌"
    elif "主跌" in snip:
        thesis = "主跌段敘事進行中"
        wait = "細微波完整結構＋降軌是否破壞"
    return {
        "thesis": thesis,
        "wait_struct": wait,
        "snippet": snip[:240],
        "as_of": str((row["as_of"] if row else "") or ""),
        "post_id": str((row["post_id"] if row else "") or ""),
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
    # 裸K／量價：實體、影線、量相對近窗
    body = abs(float(last["close"]) - float(last["open"]))
    rng = max(1.0, float(last["high"]) - float(last["low"]))
    upper = float(last["high"]) - max(float(last["open"]), float(last["close"]))
    lower = min(float(last["open"]), float(last["close"])) - float(last["low"])
    vols = [float(r["volume"]) for r in win]
    v_med = sorted(vols)[len(vols) // 2] if vols else 0.0
    v_last = float(last["volume"])
    up = float(last["close"]) >= float(last["open"])
    vol_tag = "平量"
    if v_med > 0 and v_last >= v_med * 1.8:
        vol_tag = "爆量"
    elif v_med > 0 and v_last <= v_med * 0.55:
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
    color = "紅漲" if up else "綠跌"
    out["vol_note"] = (
        f"TX60 裸K={color}{shape}{engulf}；量={vol_tag}"
        f"（{_px(v_last)}／近窗中位{_px(v_med)}）"
    )
    # 轉折：相對降軌／近窗高低
    down = out["levels"].get("tx60_down")
    turn = "近窗中段整理"
    if down and float(last["close"]) < float(down):
        turn = f"仍在降軌下（軌≈{_px(down)}）；過軌才像扭轉"
    if float(last["low"]) <= swing_lo * 1.001:
        turn = f"測近窗低{_px(swing_lo)}；要止穩需縮量收回"
    if float(last["high"]) >= swing_hi * 0.999 and up:
        turn = f"碰近窗高{_px(swing_hi)}；爆量長上影＝壓、量縮＝假突破風險"
    out["turn_note"] = turn
    return out


def _us_lead_read(db_path: str) -> Dict[str, Any]:
    """納指／費半先行（活化 us_overnight；他的外圍順序）。"""
    out: Dict[str, Any] = {"note": "", "levels": {}}
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
    """活化 futures_daily 日／夜最近一筆。"""
    out: Dict[str, Any] = {"levels": {}, "note": ""}
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        night = conn.execute(
            "SELECT date, open, high, low, close, volume FROM futures_daily "
            "WHERE symbol='TX' AND session='night' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        day = conn.execute(
            "SELECT date, open, high, low, close, volume FROM futures_daily "
            "WHERE symbol='TX' AND session='regular' ORDER BY date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    parts = []
    if night:
        out["levels"]["tx_night_c"] = float(night[4])
        out["levels"]["tx_night_l"] = float(night[3])
        out["levels"]["tx_night_h"] = float(night[2])
        parts.append(
            f"夜盤{night[0]} 收{_px(night[4])}（高{_px(night[2])}低{_px(night[3])}）"
        )
    if day:
        out["levels"]["tx_day_c"] = float(day[4])
        parts.append(f"日盤{day[0]} 收{_px(day[4])}")
    out["note"] = "；".join(parts)
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


def _build_live_pack(db_path: str) -> Dict[str, Any]:
    """彙整庫內多源 → 一包題旨／關鍵位／量價（活化使用）。"""
    thesis_pack = _latest_level_thesis(db_path)
    tx = _tx60_read(db_path)
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
    turn = str(tx.get("turn_note") or thesis_pack.get("wait_struct") or "")
    vol = str(tx.get("vol_note") or "")
    us_note = str(us.get("note") or "")
    wait = str(thesis_pack.get("wait_struct") or "")
    if fut.get("note"):
        wait = f"{wait}｜{fut['note']}"
    if claims.get("note"):
        wait = f"{wait}｜{claims['note']}"
    return {
        "thesis": thesis_pack.get("thesis") or "",
        "wait_struct": wait[:360],
        "turn_note": turn[:240],
        "vol_note": vol[:240],
        "us_note": us_note[:240],
        "key_levels": levels,
        "snippet": thesis_pack.get("snippet") or "",
    }


# 活畫深底：話筒縮圖對比（對齊你覺得清楚的黑底讀法）
_LIVE_BG = "#0b0f14"
_LIVE_PANEL = "#121820"
_LIVE_TEXT = "#f2f5f8"
_LIVE_MUTED = "#b0bec5"
_LIVE_GRID = "#2a3440"
_LIVE_UP = "#ff5252"
_LIVE_DOWN = "#26a69a"
_LIVE_LV = (
    ("tx60_down", "#ce93d8", "降軌"),
    ("tx60_swing_hi", "#ffd54f", "近窗高"),
    ("tx60_swing_lo", "#81d4fa", "近窗低"),
    ("tx_night_l", "#ffab91", "夜低"),
)


def _style_live_ax(ax, axv) -> None:
    ax.set_facecolor(_LIVE_PANEL)
    axv.set_facecolor(_LIVE_PANEL)
    for a in (ax, axv):
        a.tick_params(colors=_LIVE_MUTED, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)


def _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up) -> None:
    n = len(closes)
    for i in range(n):
        prev_c = closes[i - 1] if i else None
        up = candle_up(closes[i], prev_c, opens[i])
        color = _LIVE_UP if up else _LIVE_DOWN
        ax.vlines(i, lows[i], highs[i], color=color, linewidth=1.15, zorder=3)
        y0, y1 = sorted((opens[i], closes[i]))
        import matplotlib.pyplot as plt

        ax.add_patch(
            plt.Rectangle(
                (i - 0.34, y0),
                0.68,
                max(y1 - y0, 6),
                facecolor=color,
                edgecolor=color,
                linewidth=0.4,
                zorder=4,
            )
        )
        axv.bar(i, vols[i], color=color, width=0.68, zorder=3, alpha=0.92)


def _render_twii_live_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """加權日K深底活畫：只標真關鍵位＋量柱＋底部題旨。不准標錯5高。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from biaoke_wave import _load_twii_bars, wave_abc_story
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _load_twii_bars(db_path, n=90)
    if len(bars) < 12 or not save_path:
        return ""
    story = wave_abc_story(bars, last_tag="")
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs = [float(r.get("high") or 0) for r in bars]
    lows = [float(r.get("low") or 0) for r in bars]
    closes = [float(r.get("close") or 0) for r in bars]
    vols = [float(r.get("volume") or 0) for r in bars]
    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(14.8, 9.0),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.3, 1.55), hspace=0.046),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    # ABC 骨架（B 過 A 起時標籤已在 story 改過，不會寫錯5高）
    for key in ("a", "b", "c"):
        leg = story.get(key) or {}
        xs = list(leg.get("xs") or [])
        ys = list(leg.get("ys") or [])
        if len(xs) < 2:
            continue
        dashed = bool(leg.get("unconfirmed"))
        ax.plot(
            xs,
            ys,
            color=str(leg.get("color") or "#90caf9"),
            linewidth=1.6,
            linestyle=(0, (5, 2.5)) if dashed else "-",
            zorder=6,
        )
    # 關鍵位：只用真標；B過A起時 fifth 文案已是 A起
    for meta_key, color in (
        ("fifth_high", "#69f0ae"),
        ("b_high", "#ffd54f"),
        ("a_done", "#80cbc4"),
    ):
        hit = story.get(meta_key) or {}
        if not hit:
            continue
        y = float(hit.get("y") or 0)
        i = float(hit.get("i") or 0)
        if y <= 0:
            continue
        ax.axhline(y, color=color, linewidth=1.0, linestyle=(0, (4, 3)), zorder=5)
        ax.text(
            min(n - 0.8, i + 1.2),
            y,
            str(hit.get("text") or "")[:28],
            fontproperties=_fp(10, "bold"),
            color=color,
            ha="left",
            va="bottom",
            zorder=8,
        )
    levels = pack.get("key_levels") or {}
    for key, color, lab in _LIVE_LV:
        if key not in levels:
            continue
        y = float(levels[key])
        ax.axhline(y, color=color, linewidth=0.9, linestyle=(0, (3, 2)), alpha=0.85)
        ax.text(
            n - 0.4,
            y,
            f"{lab} {_px(y)}",
            fontproperties=_fp(9, "bold"),
            color=color,
            ha="right",
            va="bottom",
        )
    ax.set_xlim(-0.6, n + 0.8)
    ax.set_ylim(min(lows) - 420, max(highs) + 520)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.4)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    last = bars[-1]
    as_of = _ymd(last.get("date"))
    fig.text(
        0.03,
        0.965,
        f"加權日K活畫（深底）　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(last.get('close'))}",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    # 底部題旨：縮圖先讀這裡
    caps = [
        str(pack.get("thesis") or ""),
        str(pack.get("turn_note") or ""),
        str(pack.get("vol_note") or ""),
        str(pack.get("us_note") or ""),
    ]
    if story.get("b_over_a_start"):
        caps.insert(1, "B高已過A起→不准標5高（標錯＝教錯）")
    y = 0.078
    for line in caps:
        t = str(line or "").strip()
        if not t:
            continue
        fig.text(
            0.03,
            y,
            t[:78],
            fontproperties=_fp(10, "bold"),
            color=_LIVE_TEXT if y > 0.05 else _LIVE_MUTED,
            ha="left",
            va="bottom",
        )
        y -= 0.022
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000:
        return save_path
    return ""


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
    for key, col, lab in _LIVE_LV:
        if key not in levels:
            continue
        ax.axhline(float(levels[key]), color=col, linewidth=1.05, linestyle=(0, (4, 3)))
        ax.text(
            n - 0.5,
            float(levels[key]),
            f"{lab} {_px(levels[key])}",
            fontproperties=_fp(10, "bold"),
            color=col,
            ha="right",
            va="bottom",
        )
    ax.set_xlim(-0.6, n + 0.6)
    ax.set_ylim(min(lows) - 180, max(highs) + 280)
    axv.set_ylim(0, (max(vols) if vols else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    fig.text(
        0.03,
        0.965,
        "台指期 60 分　深底官方柱＋量（細微波底圖，不數段）",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    y = 0.07
    for line in (
        str(pack.get("vol_note") or ""),
        str(pack.get("turn_note") or ""),
        str(pack.get("thesis") or ""),
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


def paint_open_day_hypothesis(
    db_path: str, *, now: Optional[datetime] = None, force: bool = False
) -> Dict[str, Any]:
    """稀疏槽活畫：日盤／夜盤／納指費半＋量價裸K。不進話筒。"""
    out: Dict[str, Any] = {"ok": False, "path": "", "tx60_path": "", "slot_id": ""}
    if not db_path:
        return out
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_LEVEL_LEARN_LIVE") != "1":
        return {**out, "skipped": "pytest"}
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
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

    pack = _build_live_pack(db_path)
    thesis = pack.get("thesis") or ""
    wait_struct = pack.get("wait_struct") or ""
    turn_note = pack.get("turn_note") or ""
    vol_note = pack.get("vol_note") or ""
    us_note = pack.get("us_note") or ""
    key_levels = pack.get("key_levels") or {}

    # 內部試畫（既有 evolve）
    try:
        from biaoke_forecast import snapshot_and_score_twii

        snapshot_and_score_twii(db_path, ymd)
    except Exception:
        logger.exception("開市日內部試畫略過")

    snap_root = _paint_dir(db_path)
    chart_path = os.path.join(snap_root, f"{slot_id}.png")
    tx60_path = os.path.join(snap_root, f"{slot_id}-tx60.png")
    try:
        # 深底活畫：只標不錯的關鍵位；B過A起時不准寫5高
        got = _render_twii_live_dark(db_path, chart_path, pack)
        chart_path = got or ""
    except Exception:
        logger.exception("加權活畫渲圖失敗")
        chart_path = ""

    try:
        got60 = _render_tx60_png(db_path, tx60_path, pack)
        tx60_path = got60 or ""
    except Exception:
        logger.exception("TX60 活畫渲圖失敗")
        tx60_path = ""

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_open_day_paints(
                slot_id, as_of, thesis, wait_struct, turn_note, vol_note,
                key_levels, chart_path, tx60_path, us_note, pending, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)
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
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "活畫 slot=%s thesis=%s twii=%s tx60=%s",
        slot_id,
        thesis,
        bool(chart_path),
        bool(tx60_path),
    )
    return {
        "ok": bool(chart_path or tx60_path),
        "path": chart_path or "",
        "tx60_path": tx60_path or "",
        "thesis": thesis,
        "wait_struct": wait_struct,
        "turn_note": turn_note,
        "vol_note": vol_note,
        "us_note": us_note,
        "key_levels": key_levels,
        "slot_id": slot_id,
        "as_of": ymd,
    }


def maybe_paint_open_day_after_ingest(db_path: str) -> Dict[str, Any]:
    """抓文／輪詢後：稀疏槽內才活畫；順便隔日對質。"""
    try:
        verify_live_hyps_next_day(db_path)
    except Exception:
        logger.exception("活畫隔日對質鉤子失敗")
    try:
        return paint_open_day_hypothesis(db_path)
    except Exception:
        logger.exception("開市日活畫鉤子失敗")
        return {"ok": False, "error": "exception"}
