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
    """活畫用的加權 as_of＝已收完整柱末日（盤中未收不准當收）。"""
    try:
        from biaoke_wave import _load_twii_bars

        bars = _load_twii_bars(db_path, n=8)
    except Exception:
        bars = []
    if bars:
        return _ymd(bars[-1].get("date"))
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def _latest_level_thesis(db_path: str, as_of: str = "") -> Dict[str, str]:
    """從最近位階 snap／貼文抽出活畫題旨（可遷移結構語，不背死價當唯一）。

    課綱三科：波浪 · 黃金切割 · 型態（見 wave_fib_morph_curriculum.md）。
    as_of＝圖的收盤日：只准用 ≤ 該日的他文／snap，不准拿隔日 C3-3 回填昨天的圖。
    """
    ensure_tables(db_path)
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
    morph_blob = snip + " " + " ".join(str(r["snippet"] or "") for r in (extra or []))
    # 庫內近期大盤文也補型態（缺 snap 時）；同樣卡 as_of
    if not _morph_note_from_text(morph_blob):
        try:
            cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}" if len(cap) == 8 else cap
            since = (datetime.now(TAIPEI) - timedelta(days=14)).strftime("%Y-%m-%d")
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
        "as_of": str((row["as_of"] if row else "") or cap),
        "post_id": str((row["post_id"] if row else "") or ""),
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


def _build_live_pack(db_path: str) -> Dict[str, Any]:
    """彙整庫內多源 → 一包題旨／關鍵位／量價（活化使用）。"""
    chart_as_of = _twii_chart_as_of(db_path)
    thesis_pack = _latest_level_thesis(db_path, as_of=chart_as_of)
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
    return {
        "thesis": thesis_pack.get("thesis") or "",
        "wait_struct": wait[:400],
        "turn_note": str(turn)[:240],
        "vol_note": vol,
        "intent_note": intent,
        "us_note": us_note[:240],
        "morph_note": str(thesis_pack.get("morph_note") or "")[:180],
        "fib_note": str(thesis_pack.get("fib_note") or "")[:120],
        "key_levels": levels,
        "snippet": thesis_pack.get("snippet") or "",
        "chart_as_of": chart_as_of,
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
        if axv is not None:
            axv.bar(i, vols[i], color=color, width=0.68, zorder=3, alpha=0.92)


def _paint_vol_bars_max_yellow(
    axv,
    vols: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
    candle_up,
    *,
    fp: Any,
    title: str = "量",
) -> Optional[int]:
    """日量柱；窗內最大量那根改黃色並標「最大量」。回傳最大量索引。"""
    import matplotlib.pyplot as plt

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
        axv.annotate(
            "最大量",
            xy=(i_max, vals[i_max]),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontproperties=fp(8, "bold"),
            color="#ffeb3b",
            zorder=10,
            bbox=dict(boxstyle="round,pad=0.1", fc="#0b0f14", ec="#ffeb3b", lw=0.55, alpha=0.94),
        )
    axv.set_ylabel(title, fontproperties=fp(9, "bold"), color=_LIVE_MUTED)
    return i_max


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


def _paint_sr_zone_yellow(
    ax,
    *,
    y_now: float,
    support: Optional[float],
    resist: Optional[float],
    fp: Any,
    n: int,
) -> None:
    """淺黃底＝目前所在撐～壓區間；邊界標『下一撐／近壓』（一眼看即將遇到哪）。"""
    if support is None and resist is None:
        return
    y0 = float(support) if support is not None else float(y_now) * 0.98
    y1 = float(resist) if resist is not None else float(y_now) * 1.02
    if y1 <= y0:
        return
    ax.axhspan(y0, y1, facecolor="#ffeb3b", alpha=0.14, zorder=1)
    if support is not None:
        ax.axhline(float(support), color="#ffeb3b", lw=1.05, ls=(0, (4, 2)), alpha=0.85, zorder=4)
        ax.text(
            0.01,
            float(support),
            f"下一撐 {_px(support)}",
            transform=ax.get_yaxis_transform(),
            fontproperties=fp(9, "bold"),
            color="#ffe082",
            ha="left",
            va="bottom",
            zorder=11,
            bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec="#ffeb3b", lw=0.7, alpha=0.94),
        )
    if resist is not None:
        ax.axhline(float(resist), color="#ffeb3b", lw=1.05, ls=(0, (4, 2)), alpha=0.85, zorder=4)
        ax.text(
            0.01,
            float(resist),
            f"近壓 {_px(resist)}",
            transform=ax.get_yaxis_transform(),
            fontproperties=fp(9, "bold"),
            color="#ffe082",
            ha="left",
            va="top",
            zorder=11,
            bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec="#ffeb3b", lw=0.7, alpha=0.94),
        )


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


def _place_live_right_labels(
    ax,
    notes: Sequence[Dict[str, Any]],
    *,
    n: int,
    ymin: float,
    ymax: float,
    fp,
) -> None:
    """右側價標：結構優先、近距去重、垂直拉開，不准字壓字／字騎線。

    Fib 與 B／1-4 太近就只留結構標（線仍可畫在外面）；文字 Y 與價線 Y 分開，
    用短引線接到真價；文字一律實心底，水平線不准切開字。
    """
    items = [dict(x) for x in (notes or []) if x.get("y") is not None and x.get("text")]
    if not items:
        return
    span = max(ymax - ymin, 1.0)
    gap = max(span * 0.078, 520.0)
    # 結構標優先於 Fib 裝飾標
    def _pri(d: Dict[str, Any]) -> Tuple[int, float]:
        t = str(d.get("text") or "")
        soft = 1 if (t.startswith("Fib") or t.startswith("切")) else 0
        return (soft, -float(d["y"]))

    items.sort(key=_pri)
    kept: List[Dict[str, Any]] = []
    kept_ys: List[float] = []
    for it in items:
        y0 = float(it["y"])
        t = str(it.get("text") or "")
        soft = t.startswith("Fib") or t.startswith("切")
        # Fib／切 真價太靠近已留結構 → 丟字（水平線若外面已畫就夠）
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
        # 文字永遠離開真價線，不准騎在虛線上
        y = y_true + gap * 0.16
        for py in placed:
            if abs(y - py) < gap:
                y = py - gap
        y = min(max(y, ymin + gap * 0.35), ymax - gap * 0.3)
        # 仍撞 → 再往下推一格
        while any(abs(y - py) < gap * 0.92 for py in placed):
            y -= gap
            if y < ymin + gap * 0.25:
                break
        # 推完仍貼真價 → 再偏一點
        if abs(y - y_true) < gap * 0.12:
            y = y_true - gap * 0.18
        placed.append(y)
        color = str(it.get("color") or _LIVE_MUTED)
        x0 = float(it.get("x", n - 1))
        # 真價水平虛線（短）：從錨點拉到右欄；不重複滿幅 axhline（外面已畫）
        ax.hlines(
            y_true,
            x0,
            x_text - 0.35,
            colors=color,
            linewidth=0.75,
            linestyles=(0, (2, 2)),
            alpha=0.7,
            zorder=5,
        )
        # 文字偏離真價時：右側小豎引線，讀者對得回價位
        if abs(y - y_true) > gap * 0.12:
            ax.vlines(
                x_text - 0.38,
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
            zorder=10,
            clip_on=False,
            bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec=color, lw=0.55, alpha=0.94),
        )


def _his_micro_degree(blob: str) -> Dict[str, str]:
    """從他原文／題旨抽出『現在在哪一層小波』（只認他寫過的代號）。"""
    s = str(blob or "")
    degree = ""
    if re.search(r"C3-3-2|C3‑3‑2", s):
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
    if degree in ("C3-3-1", "C3-3-2"):
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
    """C 段內幾何小波錨（預估）：只服務超級近窗教學，不准當買訊、不准發明個股浪。

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
    # 幾何讀法：已做出②高且今收低於②→偏 C3-3-2 進行；否則仍像 ①
    if i_c2 > i_c1 and float(closes[i_now]) < float(highs[i_c2]) * 0.998:
        if i_c3 > i_c2 and float(lows[i_c3]) < float(lows[i_c1]) * 1.001:
            out["geom_degree"] = "C3-3-2"
        else:
            out["geom_degree"] = "C3-3-1"
    else:
        out["geom_degree"] = "C3-3-1"
    return out


def _alt_path_needed(his_degree: str, geom_degree: str) -> bool:
    """另色演化線：只有同家族細微層互斥才畫（如 C3-3-1 vs C3-3-2）。

    C／橫台 vs 幾何 C3-* 不准另畫——會讓人以為他換前提。同層＝不畫。
    """
    h = str(his_degree or "").strip()
    g = str(geom_degree or "").strip()
    if not h or not g:
        return False
    if h.startswith("C3-3") and g.startswith("C3-3"):
        return h != g
    return False


def _c_forecast_tip(
    *,
    i_now: int,
    y_now: float,
    y_ref: float,
    lows: Sequence[float],
) -> Dict[str, Any]:
    """C 段『預估未來』虛線端點：只指向他說過的下一錨（45546→44210），不准發明新價。

    回傳 fut_x／fut_y／label；繪圖端用虛線＋「預估↓…（會改・非買訊）」。
    """
    fut_x = float(i_now + max(3, 4))
    tag = _level_break_tag(45546.0, lows)
    if tag != "已破":
        fut_y = 45546.0
        lab = "預估↓45546"
    else:
        fut_y = 44210.0
        lab = "預估↓44210"
    # 今已低於該錨：略往下延伸示意續弱，仍不發明具體新價標
    if float(y_now) <= float(fut_y) + 1.0:
        drop = max(abs(float(y_ref) - float(y_now)) * 0.12, 180.0)
        fut_y = float(y_now) - drop
        lab = "預估↓續弱"
    return {
        "fut_x": fut_x,
        "fut_y": float(fut_y),
        "label": lab,
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
) -> Dict[str, Any]:
    """在今之後畫預估虛線＋標；回傳 tip 方便調 xlim。"""
    tip = _c_forecast_tip(i_now=i_now, y_now=y_now, y_ref=y_ref, lows=lows)
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
    # 標在端點下方，不准騎在虛線／水平錨線上
    lab_y = float(fut_y) - max(abs(float(y_now) - float(fut_y)) * 0.1, 120.0)
    ax.text(
        fut_x + 0.2,
        lab_y,
        str(tip["label"]),
        fontproperties=fp(9, "bold"),
        color="#ea80fc",
        ha="left",
        va="top",
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec="#ea80fc", lw=0.65, alpha=0.94),
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
    steps: List[str] = ["五波升完", "下降ABC", "C進行中"]
    if deg in ("C3-3-1", "C3-3-2"):
        steps.extend(["C3-3主跌", deg])
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
    as_of = _ymd(pack.get("chart_as_of") or pack.get("as_of") or "")
    as_bit = f"（as_of {as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}）" if len(as_of) == 8 else ""
    return {
        "steps": steps,
        "chain": chain,
        "now": now,
        "degree": deg,
        "one_line": f"他說現在：{chain}",
        "now_line": f"此刻＝{now}{as_bit}（預估會改・非買訊）",
        "teach_box": (
            f"他說現在層級（大→小）\n"
            f"{chain}\n"
            f"此刻＝{now}{as_bit}\n"
            f"預估會改；不是買訊"
        ),
    }


def _twii_abc_anchors(
    bars: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """⑤／A／B／C 錨；B≥⑤ 拒（不准教錯）。

    加權錨跟他確認：⑤＝10/6、A＝10/13、B＝10/14、C起＝10/14夜～10/15日。
    C 仍進行中（C3-3），不准把中段標成 C 已走完。
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


def _render_twii_far_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具①遠窗三欄：上費半波浪 → 中加權⑤起／ABC → 下加權日量（最大量黃）。

    費半指數無官方量 → 不畫費半量。淺黃＝即將撐～壓區間。
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
        logger.exception("遠窗費半補資料略過")
    bars = _load_twii_bars(db_path, n=260)
    if len(bars) < 20 or not save_path:
        return ""
    i0 = (
        _bar_index_by_ymd(bars, "20260728")
        or _bar_index_by_ymd(bars, "20260729")
        or _bar_index_by_ymd(bars, "20260725")
        or _bar_index_by_ymd(bars, "20260825")
        or 0
    )
    bars = list(bars[i0:])
    anc = _twii_abc_anchors(bars)
    if not anc:
        return ""
    sox = _load_us_daily(db_path, "SOX", "20260720")
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
    sox_a = _align_us_to_twii_dates(sox, bars)
    sox_o, sox_h, sox_l, sox_c = sox_a["open"], sox_a["high"], sox_a["low"], sox_a["close"]
    sox_anc = _sox_abc_anchors_on_axis(sox_h, sox_l, sox_c, i5_hint=i5)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    sr = _next_support_resist(
        y_now,
        supports=(45546.0, 44210.0, y_alow),
        resists=(47637.0, 48613.0, y_bhi, y5),
    )

    # 上費半 / 中加權 / 下加權量
    fig, (axu, ax, axv) = plt.subplots(
        3,
        1,
        figsize=(16.8, 12.2),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(2.55, 3.45, 1.25), hspace=0.06),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    fig.subplots_adjust(left=0.05, right=0.90, top=0.91, bottom=0.055)
    for a in (axu, ax, axv):
        a.set_facecolor(_LIVE_PANEL)
        a.tick_params(colors=_LIVE_MUTED, labelsize=9)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)

    fut_x = float(i_now + 4)
    tip: Dict[str, Any] = {"fut_x": fut_x, "xlim_right": float(n) + 4}

    # —— 上：費半價＋自轉折波浪（不畫費半量）——
    valid = [
        i
        for i, c in enumerate(sox_c)
        if c == c and c and math.isfinite(float(sox_h[i])) and math.isfinite(float(sox_l[i]))
    ]
    if len(valid) >= 5:
        span_raw = max(x for x in sox_h if x == x) - min(x for x in sox_l if x == x)
        for i in valid:
            prev_i = next((j for j in range(i - 1, -1, -1) if sox_c[j] == sox_c[j]), None)
            prev_c = sox_c[prev_i] if prev_i is not None else None
            up = candle_up_taiwan(sox_c[i], prev_c, sox_o[i])
            color = _LIVE_UP if up else _LIVE_DOWN
            axu.vlines(i, sox_l[i], sox_h[i], color=color, linewidth=1.05, zorder=3)
            y0, y1 = sorted((sox_o[i], sox_c[i]))
            axu.add_patch(
                plt.Rectangle(
                    (i - 0.32, y0),
                    0.64,
                    max(y1 - y0, span_raw * 0.0015),
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.3,
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
            before5 = [i for i in valid if i <= s5i]
            s_lo_i = min(before5, key=lambda i: float(sox_l[i])) if before5 else s5i
            s_lo_y = float(sox_l[s_lo_i])
            sox_sr = _next_support_resist(sn, supports=(sa, s_lo_y), resists=(sb, s5))
            _paint_sr_zone_yellow(
                axu,
                y_now=sn,
                support=sox_sr.get("support"),
                resist=sox_sr.get("resist"),
                fp=_fp,
                n=n,
            )
            axu.plot([s_lo_i, s5i], [s_lo_y, s5], color="#ff8a80", lw=2.1, zorder=7)
            axu.plot([s5i, sai], [s5, sa], color="#ff8a80", lw=2.0, zorder=7)
            axu.plot([sai, sbi], [sa, sb], color="#40c4ff", lw=2.0, zorder=7)
            axu.plot([sbi, i_now], [sb, sn], color="#ea80fc", lw=1.85, zorder=7)
            s_fut = sn - max((sb - sn) * 0.28, abs(sb - sn) * 0.12)
            axu.plot(
                [i_now, fut_x],
                [sn, s_fut],
                color="#ea80fc",
                lw=1.4,
                ls=(0, (4, 2)),
                alpha=0.78,
                zorder=6,
            )
            for ii, yy, col in (
                (s_lo_i, s_lo_y, "#ffab91"),
                (s5i, s5, "#ff8a80"),
                (sai, sa, "#ff8a80"),
                (sbi, sb, "#40c4ff"),
                (i_now, sn, "#ea80fc"),
            ):
                axu.scatter([ii], [yy], s=34, c=col, zorder=8, edgecolors="#fff", linewidths=0.4)
            span_s = span_raw
            s_lo_md = _md(bars[s_lo_i].get("date"))
            for x, y, lab, col, va, ha in (
                (s_lo_i + 0.8, s_lo_y + span_s * 0.03, f"費⑤起 {s_lo_md}", "#ffab91", "bottom", "left"),
                (s5i, s5 + span_s * 0.03, "費⑤升完", "#ff8a80", "bottom", "center"),
                (sai, sa - span_s * 0.03, "費A", "#ff8a80", "top", "center"),
                (sbi - 0.35, sb + span_s * 0.03, "費B", "#40c4ff", "bottom", "center"),
                (i_now + 0.45, sn + span_s * 0.04, "費C進行中", "#ea80fc", "bottom", "left"),
            ):
                axu.text(
                    x,
                    y,
                    lab,
                    fontproperties=_fp(9, "bold"),
                    color=col,
                    ha=ha,
                    va=va,
                    zorder=10,
                    bbox=dict(boxstyle="round,pad=0.1", fc="#0b0f14", ec=col, lw=0.55, alpha=0.94),
                )
            axu.set_ylim(
                min(x for x in sox_l if x == x) - span_s * 0.12,
                max(x for x in sox_h if x == x) + span_s * 0.18,
            )
    axu.set_ylabel("費半 SOX", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)

    # —— 中：加權價 ——
    _paint_live_candles(ax, None, opens, highs, lows, closes, vols, candle_up_taiwan)
    ymin = min(min(lows), 44210, y_far_lo) - 520
    ymax = max(highs) + 780
    _paint_sr_zone_yellow(
        ax,
        y_now=y_now,
        support=sr.get("support"),
        resist=sr.get("resist"),
        fp=_fp,
        n=n,
    )
    ax.axvspan(-0.4, i5 + 0.4, facecolor="#ff8a80", alpha=0.06, zorder=0)
    ax.axvspan(i5 + 0.4, n - 0.2, facecolor="#ea80fc", alpha=0.05, zorder=0)
    ax.plot([i_far_lo, i5], [y_far_lo, y5], color="#ff8a80", lw=2.35, zorder=7)
    ax.plot([i5, i_alow], [y5, y_alow], color="#ff8a80", lw=1.75, alpha=0.85, zorder=7)
    ax.plot([i_alow, i_bhi], [y_alow, y_bhi], color="#40c4ff", lw=1.75, alpha=0.85, zorder=7)
    ax.plot([i_bhi, i_now], [y_bhi, y_now], color="#ea80fc", lw=1.85, zorder=7)
    tip = _paint_c_forecast(
        ax, i_now=i_now, y_now=y_now, y_ref=y_bhi, lows=c_seg_lows, fp=_fp, n=n
    )
    fut_x = float(tip.get("fut_x") or fut_x)
    for ii, yy, col in (
        (i_far_lo, y_far_lo, "#ff8a80"),
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=40, c=col, zorder=8, edgecolors="#fff", linewidths=0.55)
    span = ymax - ymin
    far_lo_md = _md(bars[i_far_lo].get("date"))
    for x, y, lab, col, ha, va in (
        (i_far_lo + 1.0, y_far_lo + span * 0.028, f"⑤起 {far_lo_md}", "#ffab91", "left", "bottom"),
        (i5, y5 + span * 0.028, "⑤升完", "#ff8a80", "center", "bottom"),
        (i_alow, y_alow - span * 0.03, "A", "#ff8a80", "center", "top"),
        (i_bhi - 0.7, y_bhi + span * 0.028, "B", "#40c4ff", "center", "bottom"),
        (min(i_now + 1.2, n + 0.2), y_now + span * 0.055, "C進行中", "#ea80fc", "left", "bottom"),
    ):
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(10, "bold"),
            color=col,
            ha=ha,
            va=va,
            zorder=10,
            bbox=dict(boxstyle="round,pad=0.14", fc="#0b0f14", ec=col, lw=0.8, alpha=0.94),
        )
    tag_44210 = _level_break_tag(44210.0, c_seg_lows)
    right_notes = [
        {"x": i5, "y": y5, "text": f"⑤ {_px(y5)}", "color": "#ff8a80"},
        {"x": i_bhi, "y": y_bhi, "text": f"B {_px(y_bhi)}", "color": "#40c4ff"},
        {"x": i_now, "y": y_now, "text": f"今 {_px(y_now)}", "color": "#ea80fc"},
    ]
    if sr.get("support") != 44210.0:
        right_notes.append(
            {"x": n - 1, "y": 44210.0, "text": f"次撐44210{tag_44210}", "color": "#82b1ff"}
        )
    _place_live_right_labels(ax, right_notes, n=n, ymin=ymin, ymax=ymax, fp=_fp)
    ax.set_ylabel("加權", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    ax.set_ylim(ymin, ymax)

    # —— 下：加權日量（最大量黃）——
    _paint_vol_bars_max_yellow(
        axv, vols, opens, closes, candle_up_taiwan, fp=_fp, title="加權量"
    )
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.45)

    want = {
        _ymd(bars[0].get("date")),
        _ymd(bars[i_far_lo].get("date")),
        "20260825",
        "20261006",
        "20261015",
        _ymd(bars[-1].get("date")),
    }
    if sox_anc:
        for key in ("i5", "i_alow", "i_bhi"):
            want.add(_ymd(bars[int(sox_anc[key])].get("date")))
    t2, l2 = [], []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        if d in want or i % 8 == 0:
            if i not in t2:
                t2.append(i)
                tag = ""
                if i == i_far_lo:
                    tag = "⑤起"
                elif i == i5:
                    tag = "⑤"
                elif sox_anc and i == int(sox_anc["i_alow"]):
                    tag = "費A"
                elif sox_anc and i == int(sox_anc["i_bhi"]):
                    tag = "費B"
                l2.append(f"{_md(d)}{tag}")
    t2, l2 = _sparse_xticks(t2, l2, min_gap=3)
    x_right = max(n + 5.5, float(tip.get("xlim_right") or n) + 1.6, fut_x + 1.5)
    for a in (axu, ax, axv):
        a.set_xlim(-0.6, x_right)
    axv.set_xticks(t2)
    axv.set_xticklabels(l2, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    for a in (axu, ax, axv):
        for lab in a.get_yticklabels():
            lab.set_fontproperties(_fp(8, "bold"))
            lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    sup_s = _px(sr["support"]) if sr.get("support") is not None else "—"
    res_s = _px(sr["resist"]) if sr.get("resist") is not None else "—"
    fig.text(
        0.05,
        0.975,
        f"第1張（遠窗）：上費半｜中加權⑤起→ABC｜下加權量　｜　黃底撐～壓（撐{sup_s}／壓{res_s}）　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(closes[-1])}",
        fontproperties=_fp(11, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.05,
        0.952,
        "費半不畫量（指數無官方量）｜黃量柱＝加權窗內最大量｜左黃標＝下一撐／近壓｜紫虛＝預估（非買訊）",
        fontproperties=_fp(9, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="top",
    )
    fig.text(
        0.05,
        0.018,
        str(pack.get("thesis") or "五波後下降ABC・現在在C（預估）")[:96],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight", pad_inches=0.18)
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
    # 已走 C 實線；預估未來虛線另畫（已破只看 C 段後）
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    ax.plot([i_bhi, i_now], [y_bhi, y_now], color="#ea80fc", lw=2.3, zorder=7)
    tip = _paint_c_forecast(
        ax, i_now=i_now, y_now=y_now, y_ref=y_bhi, lows=c_seg_lows, fp=_fp, n=n
    )
    for ii, yy, col in (
        (i5, y5, "#ff8a80"),
        (i_alow, y_alow, "#ff8a80"),
        (i_bhi, y_bhi, "#40c4ff"),
        (i_now, y_now, "#ea80fc"),
    ):
        ax.scatter([ii], [yy], s=56, c=col, zorder=8, edgecolors="#ffffff", linewidths=0.7)
    span = max(ymax - ymin, 1.0)
    # 圓標貼轉折外緣：⑤在峰上、A在谷下、B在峰上、C在今右上空白，不准壓K／騎線
    for x, y, lab, col, ha, va in (
        (i5, y5 + span * 0.045, "⑤", "#ff8a80", "center", "bottom"),
        (i_alow - 0.55, y_alow - span * 0.045, "A↓", "#ff8a80", "center", "top"),
        (i_bhi - 0.7, y_bhi + span * 0.04, "B↑", "#40c4ff", "center", "bottom"),
        (i_now + 1.1, y_now + span * 0.06, "C進行中", "#ea80fc", "left", "bottom"),
    ):
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(14, "bold"),
            color=col,
            ha=ha,
            va=va,
            zorder=10,
            bbox=dict(boxstyle="circle,pad=0.2", fc="#0b0f14", ec=col, lw=1.2),
        )
    ax.axvline(i_c, color="#ea80fc", lw=0.95, ls=(0, (2, 2)), alpha=0.8, zorder=5)
    for xx, yy, lab, col, va, ha in (
        (i5 - 0.4, y5 + span * 0.07, f"升完⑤ {_md(bars[i5].get('date'))}", "#ff8a80", "bottom", "center"),
        (i_alow - 0.9, y_alow - span * 0.07, f"A低 {_md(bars[i_alow].get('date'))}", "#ff8a80", "top", "center"),
        (i_bhi - 0.5, y_bhi + span * 0.07, f"B高＜⑤ {_md(bars[i_bhi].get('date'))}", "#40c4ff", "bottom", "center"),
        (i_c + 0.55, ymax - span * 0.035, "C起 10/14夜～10/15日", "#ea80fc", "top", "left"),
    ):
        ax.text(
            xx,
            yy,
            lab,
            fontproperties=_fp(9, "bold"),
            color=col,
            ha=ha,
            va=va,
            zorder=10,
            bbox=dict(boxstyle="round,pad=0.14", fc="#0b0f14", ec=col, lw=0.7, alpha=0.94),
        )
    for y, _lab, col in fib_levels:
        ax.axhline(y, color=col, lw=0.85, ls=(0, (3, 2)), alpha=0.55, zorder=4)
    ax.axhline(rule14_y, color="#ffffff", lw=1.2, ls=(0, (6, 2)), alpha=0.92, zorder=5)
    ax.axhline(45546.0, color="#ffab40", lw=0.85, ls=(0, (4, 3)), alpha=0.55, zorder=4)
    ax.axhline(44210.0, color="#82b1ff", lw=0.85, ls=(0, (4, 3)), alpha=0.55, zorder=4)
    tag_45546 = _level_break_tag(45546.0, c_seg_lows)
    tag_44210 = _level_break_tag(44210.0, c_seg_lows)
    right_notes = [
        {"x": i5, "y": y5, "text": f"⑤ {_px(y5)}", "color": "#ff8a80"},
        {"x": i_bhi, "y": y_bhi, "text": f"B {_px(y_bhi)}", "color": "#40c4ff"},
        {"x": i_alow, "y": rule14_y, "text": rule14_lab, "color": "#ffffff"},
        {"x": n - 1, "y": 49160.0, "text": "切0.75", "color": "#ffca28"},
        {"x": n - 1, "y": 48613.0, "text": "切0.618", "color": "#ffd54f"},
        {"x": n - 1, "y": 47637.0, "text": "切0.382", "color": "#ffe082"},
        {"x": n - 1, "y": 45546.0, "text": f"45546{tag_45546}", "color": "#ffab40"},
        {"x": n - 1, "y": 44210.0, "text": f"44210{tag_44210}", "color": "#82b1ff"},
    ]
    _place_live_right_labels(ax, right_notes, n=n, ymin=ymin, ymax=ymax, fp=_fp)
    morph = str(pack.get("morph_note") or "").strip()
    morph_line = (morph[:24] + "…") if len(morph) > 24 else (morph or "楔形／盤頭＝觀察，不是叫你買")
    intent = str(pack.get("intent_note") or "").strip()
    # 教具框只留一句最重要的故事，避免牆字
    intent_one = intent.split("；")[0] if intent else "量價要先講故事：無量跌≠止穩；套牢後別等好心解套"
    intent_line = (intent_one[:36] + "…") if len(intent_one) > 36 else intent_one
    teach = (
        "第2張（近窗）給沒底子的人\n"
        "①波浪：⑤走完→A跌→B彈（比⑤低）→C再跌\n"
        "②黃金切割：黃線0.382／0.618／0.75＝反彈壓\n"
        f"③型態：{morph_line}\n"
        f"④量價故事：{intent_line}"
    )
    ax.text(
        0.018,
        0.08,
        teach,
        transform=ax.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=12,
        linespacing=1.35,
        bbox=dict(boxstyle="round,pad=0.32", fc="#0b0f14", ec="#546e7a", lw=0.9, alpha=0.96),
    )
    want_dates = {
        "20261006",
        "20261013",
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
    ax.set_xlim(-0.6, max(n + 7.5, float(tip.get("xlim_right") or n) + 2.0))
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
    # 標題跟當日層級走：一眼看到大→小走到哪
    title_bit = str(ladder.get("now") or "").strip() or "現在在C（預估）"
    if len(title_bit) > 22:
        title_bit = title_bit[:21] + "…"
    fig.text(
        0.03,
        0.972,
        f"第2張（近窗）：此刻＝{title_bit}　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(closes[-1])}",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.945,
        f"{str(ladder.get('one_line') or '他說現在：C進行中')[:72]}｜紫虛＝預估未來（非買訊）",
        fontproperties=_fp(10, "bold"),
        color="#ffe082",
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.048,
        f"{str(pack.get('thesis') or '')}"[:88],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    intent_foot = str(pack.get("intent_note") or pack.get("vol_note") or "")
    fig.text(
        0.03,
        0.022,
        ("量價：" + intent_foot.split("；")[0])[:90],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
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
        from biaoke_wave import _load_twii_bars
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars = _load_twii_bars(db_path, n=120)
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
    # 視覺裁切：B 高前半根起（⑤只當鐵律錨，不佔畫面）
    x_left = max(-0.4, float(i_bhi) - 0.8)

    blob = " ".join(
        str(pack.get(k) or "")
        for k in ("thesis", "wait_struct", "snippet", "morph_note")
    )
    his = _his_micro_degree(blob)
    geom = _geom_c_micro_swings(
        highs, lows, closes, i_bhi=i_bhi, i_c=i_c, i_now=i_now
    )
    need_alt = _alt_path_needed(his.get("degree") or "", geom.get("geom_degree") or "")
    ladder = _wave_now_ladder(pack)

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(15.6, 9.6),
        dpi=NAV_CHART_DPI,
        sharex=True,
        gridspec_kw=dict(height_ratios=(5.5, 1.25), hspace=0.04),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ymin = min(lows) - 420
    ymax = max(highs) + 720
    span = ymax - ymin
    ax.axvspan(i_c - 0.35, n - 0.15, facecolor="#ea80fc", alpha=0.08, zorder=1)

    # 他說路徑：只連他點過的結構——B高＝C起 → 今（進行中）
    # 幾何①②不准畫進「他說路徑」（他沒點過那兩日轉折）
    i_c1 = int(geom.get("i_c1_lo") or i_c)
    i_c2 = int(geom.get("i_c2_hi") or i_now)
    his_xs = [i_bhi, i_now]
    his_ys = [float(highs[i_bhi]), float(closes[i_now])]
    ax.plot(his_xs, his_ys, color="#ea80fc", lw=2.6, zorder=7, label="他說路徑")
    ax.scatter(his_xs, his_ys, s=46, c="#ea80fc", zorder=8, edgecolors="#fff", linewidths=0.55)
    ax.axvline(i_c, color="#ea80fc", lw=0.9, ls=(0, (2, 2)), alpha=0.75, zorder=5)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    tip = _paint_c_forecast(
        ax,
        i_now=i_now,
        y_now=float(closes[i_now]),
        y_ref=y_bhi,
        lows=c_seg_lows,
        fp=_fp,
        n=n,
    )

    # 幾何對讀（細線＋①②）：只對讀，圖例分開；不准冒充他說
    geom_xs = [i_bhi, i_c1, i_c2, i_now]
    geom_ys = [
        float(highs[i_bhi]),
        float(lows[i_c1]),
        float(highs[i_c2]),
        float(closes[i_now]),
    ]
    ax.plot(
        geom_xs,
        geom_ys,
        color="#ffab40",
        lw=1.55,
        ls=(0, (3, 2)),
        alpha=0.9,
        zorder=6,
        label="幾何對讀",
    )
    ax.scatter(
        [i_c1, i_c2],
        [float(lows[i_c1]), float(highs[i_c2])],
        s=36,
        c="#ffab40",
        zorder=7,
        edgecolors="#fff",
        linewidths=0.45,
    )

    # 標籤避開線路：B靠峰右上；C起確認再上移離豎線；幾何①下／②上；今再上移離K與紫實線
    c_lo = min(float(lows[i]) for i in range(i_bhi, n))
    c_hi = max(float(highs[i]) for i in range(i_bhi, n))
    pad = (c_hi - c_lo) * 0.04
    now_lab = f"今＝{ladder.get('now') or 'C進行中'}（預估）"
    layer_labs = [
        # B 標放在峰左側，避開 i_c 紫豎虛線
        (i_bhi - 0.85, float(highs[i_bhi]) + pad * 1.4, "B高＝C起", "#40c4ff", "bottom", "right"),
        (i_c + 0.85, c_hi + pad * 3.0, "C起確認\n10/14夜～10/15日", "#ea80fc", "bottom", "left"),
        (i_c1, float(lows[i_c1]) - pad * 2.2, "幾何①", "#ffab40", "top", "center"),
        (i_c2, float(highs[i_c2]) + pad * 1.8, "幾何②", "#ffab40", "bottom", "center"),
        (i_now + 0.55, float(closes[i_now]) + pad * 3.4, now_lab, "#ffffff", "bottom", "left"),
    ]
    for x, y, lab, col, va, ha in layer_labs:
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(10, "bold"),
            color=col,
            ha=ha,
            va=va,
            zorder=10,
            linespacing=1.15,
            bbox=dict(boxstyle="round,pad=0.14", fc="#0b0f14", ec=col, lw=0.7, alpha=0.94),
        )

    # 另前提演化（薄荷虛線）：只有跟他約的不同才畫
    if need_alt:
        # 另前提：若他說已到 2、幾何仍像 1 → 虛線往②高延伸再轉；相反則虛線先標更深①
        if (his.get("degree") or "") == "C3-3-2" and (geom.get("geom_degree") or "") == "C3-3-1":
            alt_xs = [i_c1, i_now, min(i_now + max(2, (i_now - i_c1) // 3), n - 1)]
            tip = float(closes[i_now]) + span * 0.06
            alt_ys = [float(lows[i_c1]), float(closes[i_now]), tip]
            alt_note = "另前提：若還在①整理→先墊高再進②（非他主敘）"
        else:
            # 他偏①／C3-3，幾何已像②：另線示更深殺段
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
    # 幾何框：他還沒點名 C3-3 時，不准把 geom 代號印成 C3-3-*（會像他說）
    geom_show = str(geom.get("geom_degree") or "").strip()
    if not deg_his.startswith("C3") and geom_show.startswith("C3"):
        geom_show = "C內①②（未稱C3）"
    teach = (
        f"{ladder.get('teach_box') or '他說現在層級（大→小）'}\n"
        f"幾何對讀：{geom_show or '—'}（非他說）\n"
        f"{alt_note}"
    )
    ax.text(
        0.018,
        0.08,
        teach,
        transform=ax.transAxes,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
        zorder=12,
        linespacing=1.3,
        bbox=dict(boxstyle="round,pad=0.32", fc="#0b0f14", ec="#546e7a", lw=0.9, alpha=0.96),
    )
    # 圖例放右上，避開左上K線與層級框
    ax.plot([], [], color="#ea80fc", lw=2.4, label="紫實＝他說（B→今）")
    ax.plot([], [], color="#ea80fc", lw=1.5, ls=(0, (4, 2)), label="紫虛＝預估未來")
    ax.plot([], [], color="#ffab40", lw=1.5, ls=(0, (3, 2)), label="橙虛＝幾何（非他說）")
    if need_alt:
        ax.plot([], [], color="#69f0ae", lw=2.0, ls=(0, (5, 2)), label="薄荷＝另前提")
    leg = ax.legend(
        loc="upper right",
        fontsize=8,
        frameon=True,
        fancybox=True,
        framealpha=0.92,
    )
    if leg is not None:
        leg.get_frame().set_facecolor("#0b0f14")
        leg.get_frame().set_edgecolor("#546e7a")
        for t in leg.get_texts():
            t.set_color(_LIVE_TEXT)
            t.set_fontproperties(_fp(8, "bold"))

    want_dates = {
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
    ax.set_xlim(x_left, max(n + 3.5, float(tip.get("xlim_right") or n) + 1.2))
    # 超級近窗 y：上方多留空給層級標，下方給幾何①／預估端
    y_bot = min(c_lo, float(tip.get("fut_y") or c_lo), float(tip.get("lab_y") or c_lo)) - (
        c_hi - c_lo
    ) * 0.18
    ax.set_ylim(y_bot, c_hi + (c_hi - c_lo) * 0.34)
    axv.set_ylim(0, (max(vols[i_bhi:]) if any(vols[i_bhi:]) else 1) * 1.4)
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
        f"第3張（超級近窗）：他說現在層級＋C內幾何對讀　｜　{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]} 收 {_px(closes[-1])}",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.945,
        str(ladder.get("one_line") or "他說現在：C進行中")[:100],
        fontproperties=_fp(11, "bold"),
        color="#ffe082",
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.022,
        str(ladder.get("now_line") or (pack.get("thesis") or ""))[:96],
        fontproperties=_fp(10, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
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
    for a in (ax, axu, axv):
        a.set_facecolor(_LIVE_PANEL)
        a.tick_params(colors=_LIVE_MUTED, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)

    # 上：加權＋⑤／A／B／C進行中（中段不准標成 C 已完）
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up_taiwan)
    ax.plot([i5, i_alow], [y5, y_alow], color="#ff8a80", lw=2.2, zorder=7)
    ax.plot([i_alow, i_bhi], [y_alow, y_bhi], color="#40c4ff", lw=2.2, zorder=7)
    ax.plot([i_bhi, i_now], [y_bhi, y_now], color="#ea80fc", lw=2.0, zorder=7)
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
    span_tw = max(highs) - min(lows)
    # 標在轉折點旁，不貼線中段（避免 A 浮在半空）；預估標由 _paint_c_forecast 畫
    for x, y, lab, col, va in (
        (i5, y5 + span_tw * 0.028, "⑤", "#ff8a80", "bottom"),
        (i_alow, y_alow - span_tw * 0.025, "A低", "#ff8a80", "top"),
        (i_bhi, y_bhi + span_tw * 0.028, "B高", "#40c4ff", "bottom"),
        (i_c, float(highs[i_c]) + span_tw * 0.04, "C起", "#ea80fc", "bottom"),
        (i_now, y_now + span_tw * 0.03, "C進行中", "#ea80fc", "bottom"),
    ):
        ax.text(
            x,
            y,
            lab,
            fontproperties=_fp(11, "bold"),
            color=col,
            ha="center",
            va=va,
            zorder=9,
            bbox=dict(boxstyle="round,pad=0.12", fc="#0b0f14", ec=col, lw=0.65, alpha=0.9),
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
            # 費半標在自己轉折點：A＝低點旁、B＝高點旁（不准漂在線中段）
            for x, y, lab, col, va in (
                (s5i, s5 + span_s * 0.03, "費⑤", "#ff8a80", "bottom"),
                (sai, sa - span_s * 0.03, "費A低", "#ff8a80", "top"),
                (sbi, sb + span_s * 0.03, "費B高", "#40c4ff", "bottom"),
                (i_now, sn + span_s * 0.035, "費C進行中", "#ea80fc", "bottom"),
                (fut_x, s_fut - span_s * 0.01, "預估↓", "#ea80fc", "top"),
            ):
                axu.text(
                    x,
                    y,
                    lab,
                    fontproperties=_fp(10, "bold"),
                    color=col,
                    ha="center",
                    va=va,
                    zorder=9,
                    bbox=dict(
                        boxstyle="round,pad=0.12", fc="#0b0f14", ec=col, lw=0.65, alpha=0.9
                    ),
                )
            axu.axvline(s5i, color="#ff8a80", lw=0.85, ls=(0, (2, 2)), alpha=0.75, zorder=5)
            axu.axvline(sai, color="#ff8a80", lw=0.7, ls=(0, (2, 3)), alpha=0.45, zorder=5)
            axu.axvline(sbi, color="#40c4ff", lw=0.7, ls=(0, (2, 3)), alpha=0.45, zorder=5)
            axu.set_ylim(
                min(x for x in sox_l if x == x) - span_s * 0.12,
                max(x for x in sox_h if x == x) + span_s * 0.18,
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
    """稀疏槽活畫：日盤／夜盤／納指費半＋量價裸K。空白鍵可取檔送教具（非買訊）。"""
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
    intent_note = pack.get("intent_note") or ""
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
    micro_path = os.path.join(snap_root, f"{slot_id}-micro.png")
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
        got_micro = _render_twii_super_near_dark(db_path, micro_path, pack)
        micro_path = got_micro or ""
    except Exception:
        logger.exception("超級近窗渲圖失敗")
        micro_path = ""

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

    logger.info(
        "活畫 slot=%s thesis=%s far=%s near=%s micro=%s us=%s tx60=%s",
        slot_id,
        thesis,
        bool(far_path),
        bool(near_path),
        bool(micro_path),
        bool(us_path),
        bool(tx60_path),
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
        "as_of": ymd,
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
