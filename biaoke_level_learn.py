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


def _latest_level_thesis(db_path: str) -> Dict[str, str]:
    """從最近位階 snap／貼文抽出活畫題旨（可遷移結構語，不背死價當唯一）。

    課綱三科：波浪 · 黃金切割 · 型態（見 wave_fib_morph_curriculum.md）。
    """
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT snippet, as_of, post_id FROM biaoke_level_snaps "
            "ORDER BY as_of DESC, created_at DESC LIMIT 1"
        ).fetchone()
        # 近窗型態：再掃兩則位階文，補形態學句
        extra = conn.execute(
            "SELECT snippet FROM biaoke_level_snaps "
            "ORDER BY as_of DESC, created_at DESC LIMIT 4"
        ).fetchall()
    finally:
        conn.close()
    snip = str((row["snippet"] if row else "") or "")
    morph_blob = snip + " " + " ".join(str(r["snippet"] or "") for r in (extra or []))
    # 庫內近期大盤文也補型態（缺 snap 時）
    if not _morph_note_from_text(morph_blob):
        try:
            conn = sqlite3.connect(db_path, timeout=15.0)
            try:
                posts = conn.execute(
                    "SELECT text FROM biaoke_posts WHERE date>=? "
                    "AND (text LIKE '%型態%' OR text LIKE '%形態%' OR text LIKE '%楔形%' "
                    "OR text LIKE '%頸線%' OR text LIKE '%頭肩%' OR text LIKE '%橫台%') "
                    "ORDER BY date DESC, time DESC LIMIT 6",
                    ((datetime.now(TAIPEI) - timedelta(days=14)).strftime("%Y-%m-%d"),),
                ).fetchall()
            finally:
                conn.close()
            morph_blob += " " + " ".join(str(p[0] or "") for p in posts)
        except Exception:
            pass
    morph = _morph_note_from_text(morph_blob)
    # 他確認的大結構：五波後接下降ABC；10/14夜～10/15日 C 啟動；現況在 C 內
    # 位階＝預估（他原文：很容易看錯／不要做太遠）；隨時檢視；誤導或鐵律不符→動態修正
    thesis = "五波後下降ABC・現在在C（預估・隨時檢視）"
    wait = "不符鐵律／穿刺原規劃／被誤導→重修位階"
    if "C3-3-1" in snip and "C3-3-2" in snip:
        thesis = "五波後下降ABC・C內＝C3-3（1→2・預估）"
        wait = "下一測他點過錨；鐵律不符→動態修正重訂"
    elif "C3-3" in snip:
        thesis = "五波後下降ABC・C內＝C3-3主跌（預估）"
        wait = "隨時檢視細微；穿刺原規劃→重修"
    elif "橫台" in snip or "中繼" in snip:
        thesis = "五波後下降ABC・C內橫台中繼（預估）"
        wait = "中繼後原方向；不過壓／拖太久→續C；不符就改"
    elif "主跌" in snip:
        thesis = "五波後下降ABC・C內主跌（預估）"
        wait = "細微波完整＋降軌；走完一段再重訂位階"
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
            # 近 40 根已夠近窗對照就先跳過抓
            n_have = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=?",
                (sym, "20260901"),
            ).fetchone()[0]
            if int(n_have or 0) >= 25:
                stats[sym] = int(n_have)
                continue
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
                f"?interval=1d&range=3mo"
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
    return stats


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
        "morph_note": str(thesis_pack.get("morph_note") or "")[:180],
        "fib_note": str(thesis_pack.get("fib_note") or "")[:120],
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


def _place_live_right_labels(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    n: int,
    ymin: float,
    ymax: float,
    fp,
) -> None:
    """右側價標：結構優先、近距去重、垂直拉開，不准字壓字。

    Fib 與 B／1-4 太近就只留結構標（線仍可畫在外面）；文字 Y 與價線 Y 分開，
    用短引線接到真價，避免 Fib0.75／B／0.618 黏成一團。
    """
    items = [dict(x) for x in (notes or []) if x.get("y") is not None and x.get("text")]
    if not items:
        return
    span = max(ymax - ymin, 1.0)
    gap = max(span * 0.078, 520.0)
    # 結構標優先於 Fib 裝飾標
    def _pri(d: Dict[str, Any]) -> Tuple[int, float]:
        t = str(d.get("text") or "")
        soft = 1 if t.startswith("Fib") else 0
        return (soft, -float(d["y"]))

    items.sort(key=_pri)
    kept: List[Dict[str, Any]] = []
    kept_ys: List[float] = []
    for it in items:
        y0 = float(it["y"])
        soft = str(it.get("text") or "").startswith("Fib")
        # Fib 真價太靠近已留結構 → 丟字（水平線若外面已畫就夠）
        if soft and any(abs(y0 - ky) < gap * 0.85 for ky in kept_ys):
            continue
        kept.append(it)
        kept_ys.append(y0)
    # 由高到低排文字座，強制最小間距
    kept.sort(key=lambda d: float(d["y"]), reverse=True)
    placed: List[float] = []
    x_text = n + 0.55
    for it in kept:
        y_true = float(it["y"])
        y = y_true
        for py in placed:
            if abs(y - py) < gap:
                y = py - gap
        y = min(max(y, ymin + gap * 0.35), ymax - gap * 0.3)
        # 仍撞 → 再往下推一格
        while any(abs(y - py) < gap * 0.92 for py in placed):
            y -= gap
            if y < ymin + gap * 0.25:
                break
        placed.append(y)
        color = str(it.get("color") or _LIVE_MUTED)
        x0 = float(it.get("x", n - 1))
        # 真價水平虛線（短）：從錨點拉到右欄；不重複滿幅 axhline（外面已畫）
        ax.hlines(
            y_true,
            x0,
            x_text - 0.2,
            colors=color,
            linewidth=0.75,
            linestyles=(0, (2, 2)),
            alpha=0.7,
            zorder=5,
        )
        # 文字偏離真價時：右側小豎引線，讀者對得回價位
        if abs(y - y_true) > gap * 0.15:
            ax.vlines(
                x_text - 0.22,
                min(y, y_true),
                max(y, y_true),
                colors=color,
                linewidth=0.7,
                alpha=0.65,
                zorder=5,
            )
        ax.text(
            x_text,
            y,
            str(it["text"])[:16],
            fontproperties=fp(10, "bold"),
            color=color,
            ha="left",
            va="center",
            zorder=9,
            clip_on=False,
        )


def _twii_abc_anchors(
    bars: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """⑤／A／B／C 錨；B≥⑤ 拒（不准教錯）。"""
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


def _render_twii_far_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具①遠窗：8/25 低→升完⑤→ABC 只點到為止（不塞 Fib，留給近窗特寫）。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from biaoke_wave import _load_twii_bars
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _load_twii_bars(db_path, n=200)
    if len(bars) < 20 or not save_path:
        return ""
    i0 = (
        _bar_index_by_ymd(bars, "20260825")
        or _bar_index_by_ymd(bars, "20260901")
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
    i5, i_alow, i_bhi, i_c = anc["i5"], anc["i_alow"], anc["i_bhi"], anc["i_c"]
    i_now, y5, y_alow, y_bhi, y_now = (
        anc["i_now"],
        anc["y5"],
        anc["y_alow"],
        anc["y_bhi"],
        anc["y_now"],
    )
    i_far_lo = min(range(0, i5 + 1), key=lambda i: lows[i]) if i5 > 0 else 0
    y_far_lo = lows[i_far_lo]

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(15.8, 9.4),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.4, 1.3), hspace=0.04),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ymin = min(min(lows), 44210) - 580
    ymax = max(highs) + 980
    ax.axvspan(-0.4, i5 + 0.4, facecolor="#ff8a80", alpha=0.08, zorder=1)
    ax.axvspan(i5 + 0.4, n - 0.2, facecolor="#ea80fc", alpha=0.07, zorder=1)
    ax.plot([i_far_lo, i5], [y_far_lo, y5], color="#ff8a80", lw=2.4, zorder=7)
    ax.plot([i5, i_alow], [y5, y_alow], color="#ff8a80", lw=1.8, alpha=0.85, zorder=7)
    ax.plot([i_alow, i_bhi], [y_alow, y_bhi], color="#40c4ff", lw=1.8, alpha=0.85, zorder=7)
    ax.plot(
        [i_bhi, i_now],
        [y_bhi, y_now],
        color="#ea80fc",
        lw=1.7,
        ls=(0, (5, 2)),
        zorder=7,
    )
    for ii, yy, col in (
        (i_far_lo, y_far_lo, "#ff8a80"),
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=44, c=col, zorder=8, edgecolors="#fff", linewidths=0.6)
    span = ymax - ymin
    for x, y, lab, col in (
        (i_far_lo, y_far_lo - span * 0.03, "遠窗底", "#ffab91"),
        (i5, y5 + span * 0.025, "⑤升完", "#ff8a80"),
        ((i5 + i_alow) / 2, (y5 + y_alow) / 2, "A", "#ff8a80"),
        ((i_alow + i_bhi) / 2, (y_alow + y_bhi) / 2, "B", "#40c4ff"),
        ((i_bhi + i_now) / 2, (y_bhi + y_now) / 2 - span * 0.02, "C↓預估", "#ea80fc"),
    ):
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(12, "bold"),
            color=col,
            ha="center",
            va="center",
            zorder=9,
            bbox=dict(boxstyle="round,pad=0.18", fc="#0b0f14", ec=col, lw=0.9, alpha=0.9),
        )
    ax.axhline(44210.0, color="#82b1ff", lw=0.9, ls=(0, (4, 3)), alpha=0.6, zorder=4)
    ax.axhline(45546.0, color="#ffab40", lw=0.85, ls=(0, (4, 3)), alpha=0.55, zorder=4)
    right_notes = [
        {"x": i5, "y": y5, "text": f"⑤ {_px(y5)}", "color": "#ff8a80"},
        {"x": i_bhi, "y": y_bhi, "text": f"B {_px(y_bhi)}", "color": "#40c4ff"},
        {"x": n - 1, "y": 45546.0, "text": "45546已破", "color": "#ffab40"},
        {"x": n - 1, "y": 44210.0, "text": "44210未到", "color": "#82b1ff"},
        {"x": i_now, "y": y_now, "text": f"今 {_px(y_now)}", "color": "#ea80fc"},
    ]
    _place_live_right_labels(ax, right_notes, n=n, ymin=ymin, ymax=ymax, fp=_fp)
    teach = (
        "遠窗課＝波浪骨架\n"
        "①遠窗底→⑤＝上升走完\n"
        "②之後才下降ABC\n"
        "③黃金切割＋型態→近窗特寫\n"
        "預估・不符鐵律會改・非買訊"
    )
    ax.text(
        0.012,
        0.02,
        teach,
        transform=ax.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=12,
        linespacing=1.35,
        bbox=dict(boxstyle="round,pad=0.32", fc="#0b0f14", ec="#546e7a", lw=0.9, alpha=0.92),
    )
    want = {
        _ymd(bars[0].get("date")),
        _ymd(bars[i_far_lo].get("date")),
        "20261006",
        "20261015",
        _ymd(bars[-1].get("date")),
    }
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want or i % 7 == 0:
            if i not in t2:
                t2.append(i)
                l2.append(_md(d))
    ax.set_xlim(-0.8, n + 7.2)
    ax.set_ylim(ymin, ymax)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    fig.text(
        0.03,
        0.97,
        f"教具①遠窗：升完⑤才看得懂為何在C　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(closes[-1])}",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.942,
        "只看近窗會問「C從哪來」→遠窗先答：8/25低→10/6⑤＝上升走完｜預估・隨時檢視",
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.045,
        str(pack.get("thesis") or "五波後下降ABC・現在在C（預估）")[:88],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
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
        from biaoke_wave import _load_twii_bars
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _load_twii_bars(db_path, n=120)
    if len(bars) < 16 or not save_path:
        return ""
    # 近窗特寫：⑤前留一點呼吸，ABC 才夠大
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
    i5, i_alow, i_bhi, i_c = anc["i5"], anc["i_alow"], anc["i_bhi"], anc["i_c"]
    i_now, y5, y_alow, y_bhi, y_now = (
        anc["i_now"],
        anc["y5"],
        anc["y_alow"],
        anc["y_bhi"],
        anc["y_now"],
    )
    fib_levels = (
        (47637.0, "0.382", "#ffe082"),
        (48613.0, "0.618", "#ffd54f"),
        (49160.0, "0.75", "#ffca28"),
    )
    rule14_y = float(y_alow)
    rule14_lab = f"1-4鍵 {_px(rule14_y)}"

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(15.6, 9.8),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.5, 1.35), hspace=0.04),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ymin = min(min(lows), 44210) - 480
    ymax = max(highs) + 860
    ax.axvspan(i5 + 0.35, n - 0.15, facecolor="#ea80fc", alpha=0.07, zorder=1)
    ax.plot([i5, i_alow], [y5, y_alow], color="#ff8a80", lw=2.5, zorder=7)
    ax.plot([i_alow, i_bhi], [y_alow, y_bhi], color="#40c4ff", lw=2.5, zorder=7)
    ax.plot(
        [i_bhi, i_now],
        [y_bhi, y_now],
        color="#ea80fc",
        lw=2.3,
        ls=(0, (5, 2.2)),
        zorder=7,
    )
    for ii, yy, col in (
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=56, c=col, zorder=8, edgecolors="#ffffff", linewidths=0.7)
    span = max(ymax - ymin, 1.0)
    for x, y, lab, col in (
        (i5, y5 + span * 0.02, "⑤", "#ff8a80"),
        ((i5 + i_alow) / 2.0, (y5 + y_alow) / 2.0, "A↓", "#ff8a80"),
        ((i_alow + i_bhi) / 2.0, (y_alow + y_bhi) / 2.0 + span * 0.012, "B↑", "#40c4ff"),
        ((i_bhi + i_now) / 2.0, (y_bhi + y_now) / 2.0 - span * 0.02, "C↓", "#ea80fc"),
    ):
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(15, "bold"),
            color=col,
            ha="center",
            va="center",
            zorder=9,
            bbox=dict(boxstyle="circle,pad=0.22", fc="#0b0f14", ec=col, lw=1.25),
        )
    ax.axvline(i_c, color="#ea80fc", lw=0.95, ls=(0, (2, 2)), alpha=0.8, zorder=5)
    for xx, yy, lab, col, va, ha in (
        (i5 - 0.6, y5 + span * 0.04, f"升完⑤ {_md(bars[i5].get('date'))}", "#ff8a80", "bottom", "center"),
        (i_alow + 1.2, y_alow - span * 0.035, f"A低 {_md(bars[i_alow].get('date'))}", "#ff8a80", "top", "center"),
        (i_bhi + 1.4, y_bhi + span * 0.045, f"B高＜⑤ {_md(bars[i_bhi].get('date'))}", "#40c4ff", "bottom", "center"),
        (i_c - 0.2, ymax - span * 0.04, "C啟動 10/15", "#ea80fc", "top", "right"),
    ):
        ax.text(
            xx,
            yy,
            lab,
            fontproperties=_fp(9, "bold"),
            color=col,
            ha=ha,
            va=va,
            zorder=9,
            bbox=dict(boxstyle="round,pad=0.14", fc="#0b0f14", ec=col, lw=0.7, alpha=0.9),
        )
    for y, _lab, col in fib_levels:
        ax.axhline(y, color=col, lw=0.85, ls=(0, (3, 2)), alpha=0.55, zorder=4)
    ax.axhline(rule14_y, color="#ffffff", lw=1.2, ls=(0, (6, 2)), alpha=0.92, zorder=5)
    ax.axhline(45546.0, color="#ffab40", lw=0.85, ls=(0, (4, 3)), alpha=0.55, zorder=4)
    ax.axhline(44210.0, color="#82b1ff", lw=0.85, ls=(0, (4, 3)), alpha=0.55, zorder=4)
    right_notes = [
        {"x": i5, "y": y5, "text": f"⑤ {_px(y5)}", "color": "#ff8a80"},
        {"x": i_bhi, "y": y_bhi, "text": f"B {_px(y_bhi)}", "color": "#40c4ff"},
        {"x": i_alow, "y": rule14_y, "text": rule14_lab, "color": "#ffffff"},
        {"x": n - 1, "y": 49160.0, "text": "切0.75", "color": "#ffca28"},
        {"x": n - 1, "y": 48613.0, "text": "切0.618", "color": "#ffd54f"},
        {"x": n - 1, "y": 47637.0, "text": "切0.382", "color": "#ffe082"},
        {"x": n - 1, "y": 45546.0, "text": "45546已破", "color": "#ffab40"},
        {"x": n - 1, "y": 44210.0, "text": "44210未到", "color": "#82b1ff"},
    ]
    _place_live_right_labels(ax, right_notes, n=n, ymin=ymin, ymax=ymax, fp=_fp)
    morph = str(pack.get("morph_note") or "").strip()
    morph_line = (morph[:28] + "…") if len(morph) > 28 else (morph or "型態：橫台／楔形／盤頭只觀察")
    teach = (
        "近窗三科（預估・會改）\n"
        "波浪：⑤→A↓→B↑＜⑤→C↓現在\n"
        "黃金切割：黃線0.382／0.618／0.75\n"
        f"型態：{morph_line}\n"
        "白＝1-4鐵律｜非買訊｜遠窗／費半另張"
    )
    ax.text(
        0.012,
        0.02,
        teach,
        transform=ax.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=12,
        linespacing=1.35,
        bbox=dict(boxstyle="round,pad=0.35", fc="#0b0f14", ec="#546e7a", lw=0.9, alpha=0.92),
    )
    want_dates = {
        "20261006",
        "20261013",
        "20261014",
        "20261015",
        "20261022",
        _ymd(bars[-1].get("date")),
    }
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want_dates or i % 3 == 0:
            if i not in t2:
                t2.append(i)
                l2.append(_md(d))
    ax.set_xlim(-0.6, n + 7.5)
    ax.set_ylim(ymin, ymax)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.4)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    fig.text(
        0.03,
        0.972,
        f"教具②近窗特寫：下降ABC・現在在C（C3-3）　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(closes[-1])}",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.945,
        "三科：波浪ABC＋黃金切割0.382/0.618/0.75＋型態觀察　｜　預估・隨時檢視・鐵律不符→動態修正",
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="top",
    )
    wait = str(pack.get("wait_struct") or "不符鐵律／穿刺原規劃→動態修正重修")
    fig.text(
        0.03,
        0.048,
        f"{str(pack.get('thesis') or '')}　｜　{wait}"[:90],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    fig.text(
        0.03,
        0.022,
        ("45546已破・44210未到｜" + str(pack.get("us_note") or "")[:50])[:90],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_us_compare_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具③近窗外圍對照：加權近窗 vs 費半／納指（他常用費半先行）。

    缺日K會先 _ensure_us_index_daily 自己補。
    """
    try:
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
    bars = _load_twii_bars(db_path, n=120)
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
    ixic = _load_us_daily(db_path, "IXIC", "20260920")
    if not anc or (len(sox) < 5 and len(ixic) < 5):
        return ""
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(bars)
    opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
    highs, lows, closes = anc["highs"], anc["lows"], anc["closes"]
    vols = [float(r.get("volume") or 0) for r in bars]
    i5, i_now = anc["i5"], anc["i_now"]
    y5, y_now = anc["y5"], anc["y_now"]

    # 對齊日期：美股列成與 TWII 同索引的 close／pct（缺＝nan）
    by_sox = {_ymd(r["date"]): r for r in sox}
    by_ix = {_ymd(r["date"]): r for r in ixic}
    sox_c, ix_c, sox_pct, ix_pct = [], [], [], []
    for r in bars:
        d = _ymd(r.get("date"))
        s, x = by_sox.get(d), by_ix.get(d)
        sox_c.append(float(s["close"]) if s else float("nan"))
        ix_c.append(float(x["close"]) if x else float("nan"))
        sox_pct.append(float(s["pct"]) if s and s.get("pct") is not None else float("nan"))
        ix_pct.append(float(x["pct"]) if x and x.get("pct") is not None else float("nan"))

    fig, (ax, axu, axv) = plt.subplots(
        3,
        1,
        figsize=(15.6, 10.4),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(3.2, 2.4, 1.1), hspace=0.06),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    for a in (ax, axu, axv):
        a.set_facecolor(_LIVE_PANEL)
        a.tick_params(colors=_LIVE_MUTED, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ax.plot([i5, i_now], [y5, y_now], color="#ea80fc", lw=1.6, ls=(0, (4, 2)), zorder=7)
    ax.scatter([i5, i_now], [y5, y_now], s=40, c="#ea80fc", zorder=8, edgecolors="#fff", linewidths=0.5)
    ax.text(
        i5,
        y5 + (max(highs) - min(lows)) * 0.03,
        "⑤",
        fontproperties=_fp(12, "bold"),
        color="#ff8a80",
        ha="center",
        zorder=9,
    )
    ax.set_ylabel("加權近窗", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)

    # 外圍：⑤當日＝100 正規化，學生看誰先弱
    def _norm(series: List[float], i_base: int) -> List[float]:
        base = series[i_base] if 0 <= i_base < len(series) else float("nan")
        if base != base or not base:
            # 找第一個有效
            for v in series:
                if v == v and v:
                    base = v
                    break
        if not base or base != base:
            return series
        return [((v / base) * 100.0) if v == v and v else float("nan") for v in series]

    sn = _norm(sox_c, i5)
    xn = _norm(ix_c, i5)
    axu.plot(range(n), sn, color="#ffd54f", lw=2.0, label="費半 SOX（⑤＝100）", zorder=6)
    axu.plot(range(n), xn, color="#4fc3f5", lw=1.7, label="納指 IXIC（⑤＝100）", zorder=6)
    axu.axhline(100.0, color="#90a4ae", lw=0.8, ls=(0, (3, 2)), alpha=0.7, zorder=4)
    axu.axvline(i5, color="#ff8a80", lw=0.9, ls=(0, (2, 2)), alpha=0.8, zorder=5)
    # 日漲跌柱（費半）疊在次軸感覺太擠→改右邊註最近幾日
    axu.set_ylabel("外圍指數", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    leg = axu.legend(loc="upper left", fontsize=9, framealpha=0.85, facecolor="#0b0f14", edgecolor="#546e7a")
    for t in leg.get_texts():
        t.set_color(_LIVE_TEXT)
        t.set_fontproperties(_fp(9, "bold"))

    # 最近費半／納指日漲跌字（學生一眼）
    last_note = str(pack.get("us_note") or "")
    axu.text(
        0.99,
        0.04,
        last_note[:52] or "外圍日K已補；費半先行看黃線",
        transform=axu.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="right",
        va="bottom",
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.25", fc="#0b0f14", ec="#546e7a", lw=0.8, alpha=0.9),
    )
    teach = (
        "外圍課：他看費半先行\n"
        "黃線先破100＝費半比⑤弱\n"
        "→近窗C續跌偏壓加大\n"
        "藍＝納指佐證　不是買訊"
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
        linespacing=1.3,
        bbox=dict(boxstyle="round,pad=0.3", fc="#0b0f14", ec="#546e7a", lw=0.85, alpha=0.92),
    )
    want = {"20261006", "20261015", "20261022", _ymd(bars[-1].get("date"))}
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want or i % 3 == 0:
            if i not in t2:
                t2.append(i)
                l2.append(_md(d))
    ax.set_xlim(-0.5, n + 1.2)
    ax.set_ylim(min(lows) - 400, max(highs) + 700)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(9, "bold"), color=_LIVE_MUTED)
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
        f"教具③近窗×費半／納指　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}　缺資料已自補 Yahoo／分K",
        fontproperties=_fp(13, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.948,
        "老師備課：外圍不看＝近窗C缺半堂課｜費半大弱→台指偏壓（他原文順序）",
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
    ax.set_xlim(-0.6, n + 5.8)
    ax.set_ylim(min(lows) - 180, max(highs) + 280)
    _place_live_right_labels(
        ax,
        lv_notes,
        n=n,
        ymin=min(lows) - 180,
        ymax=max(highs) + 280,
        fp=_fp,
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

    # 缺費半／納指日K先自己補（老師備課）
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("活畫補美股日K略過")

    snap_root = _paint_dir(db_path)
    near_path = os.path.join(snap_root, f"{slot_id}-near.png")
    far_path = os.path.join(snap_root, f"{slot_id}-far.png")
    us_path = os.path.join(snap_root, f"{slot_id}-us.png")
    chart_path = os.path.join(snap_root, f"{slot_id}.png")  # 兼容＝近窗特寫
    tx60_path = os.path.join(snap_root, f"{slot_id}-tx60.png")
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

    try:
        got_far = _render_twii_far_dark(db_path, far_path, pack)
        far_path = got_far or ""
    except Exception:
        logger.exception("遠窗教具渲圖失敗")
        far_path = ""

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

    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_open_day_paints(
                slot_id, as_of, thesis, wait_struct, turn_note, vol_note,
                key_levels, chart_path, tx60_path, us_note,
                far_path, near_path, us_path, pending, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
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
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "活畫 slot=%s thesis=%s far=%s near=%s us=%s tx60=%s",
        slot_id,
        thesis,
        bool(far_path),
        bool(near_path),
        bool(us_path),
        bool(tx60_path),
    )
    return {
        "ok": bool(near_path or far_path or us_path or tx60_path),
        "path": chart_path or near_path or "",
        "far_path": far_path or "",
        "near_path": near_path or "",
        "us_path": us_path or "",
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
