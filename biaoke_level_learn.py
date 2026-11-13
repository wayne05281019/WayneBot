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
    # 他常寫「1 4重疊／1-4重疊」；假跌破／有效穿刺／走3-5＝大盤現況位階口語
    r"1\s*[-–]?\s*4\s*重疊|假跌破|有效穿刺|(?:今天)?走\s*3-5|(?<![0-9])3-5(?![0-9])|"
    r"鐵律|破底翻|第二隻腳|第二支腳|"
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
    # 14:30 黃培碩對讀飆大→教導畫線（開市日；與 main 排程 huang_teach 對齊）
    ("huang", 14 * 60 + 25, 14 * 60 + 55),
    ("after", 16 * 60 + 30, 20 * 60 + 50),  # 盤後～夜盤前
    ("night", 21 * 60, 22 * 60 + 30),  # 夜盤中段一眼
)


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _teach_bar_hhmm(raw: Any) -> str:
    """從 60 分 ts／datetime 取 HH:MM；日K無時段 → 空字（標籤只留月日）。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    # 202611050900／20261105090000
    if len(digits) >= 12:
        hh, mm = digits[8:10], digits[10:12]
        try:
            if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
                return f"{hh}:{mm}"
        except ValueError:
            pass
    # 2026-11-05 09:00:00／09:00
    for sep in (" ", "T"):
        if sep in s:
            tail = s.split(sep, 1)[1].strip()
            if len(tail) >= 5 and tail[2] == ":":
                hh, mm = tail[0:2], tail[3:5]
                if hh.isdigit() and mm.isdigit():
                    try:
                        if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
                            return f"{hh}:{mm}"
                    except ValueError:
                        pass
            break
    if len(s) == 5 and s[2] == ":" and s[0:2].isdigit() and s[3:5].isdigit():
        return s
    return ""


def _teach_vol_day_tag(date_lab: Any, ts_lab: Any = "") -> str:
    """大量撐壓左標前綴：日K＝「11/5 」；60分＝「11/5 09:00 」（寫清幾點K棒）。"""
    t = _ymd(date_lab)
    md = f"{int(t[4:6])}/{int(t[6:8])}" if len(t) == 8 else ""
    hhmm = _teach_bar_hhmm(ts_lab) or _teach_bar_hhmm(date_lab)
    if md and hhmm:
        return f"{md} {hhmm} "
    if md:
        return f"{md} "
    if hhmm:
        return f"{hhmm} "
    return ""


def _teach_vol_match_bar_index(
    rows: Sequence[Dict[str, Any]],
    *,
    ymd: str,
    high: float,
    low: float,
    ts: str = "",
) -> Optional[int]:
    """對到真爆大量棒：60分先認 ts，再同日高低吻合；日K同日即可。不准只抓當日第一根。"""
    rows = list(rows or [])
    ts_s = str(ts or "").strip()
    if ts_s:
        for i, r in enumerate(rows):
            rt = str((r or {}).get("ts") or "").strip()
            if not rt:
                continue
            if rt == ts_s or rt[:12] == ts_s[:12]:
                return int(i)
    day = _ymd(ymd)
    if not day:
        return None
    hi = float(high or 0)
    lo = float(low or 0)
    first: Optional[int] = None
    for i, r in enumerate(rows):
        rd = _ymd((r or {}).get("date")) or _ymd((r or {}).get("ts"))
        if rd != day:
            continue
        if first is None:
            first = int(i)
        try:
            rh = float((r or {}).get("high") or 0)
            rl = float((r or {}).get("low") or 0)
        except (TypeError, ValueError):
            continue
        if hi > 0 and lo > 0 and abs(rh - hi) < 0.05 and abs(rl - lo) < 0.05:
            return int(i)
    return first


def _px(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x <= 0:
        return "—"
    return f"{x:,.0f}"


def _spear_ring(
    ax: Any,
    x: float,
    y: float,
    *,
    color: str,
    zorder: float = 8.5,
    hot: bool = False,
    clip_on: bool = True,
) -> None:
    """矛點空心圈：只畫一圈、線細。hot＝C7／C8／今 略大仍細。"""
    ax.scatter(
        [float(x)],
        [float(y)],
        s=30 if hot else 22,
        facecolors="none",
        edgecolors=str(color),
        linewidths=0.38 if hot else 0.32,
        zorder=float(zorder),
        clip_on=bool(clip_on),
    )


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
    """顯示用：把 MIS 加權疊成當日柱（只渲染、不寫庫、不當官方收）。

    末K OHLC＋成交量都疊；量認 MIS（加權用 m），不准留 0 假柱。
    盤中窗一律疊；盤後空窗僅當官方日K還沒有今日柱才疊（修話筒卡昨日收）。
    """
    if not live:
        return [dict(r) for r in (bars or [])]
    today = _ymd(live.get("date")) if isinstance(live, dict) else ""
    if len(today or "") != 8:
        today = datetime.now(TAIPEI).strftime("%Y%m%d")
    out = [dict(r) for r in (bars or [])]
    last_d = _ymd(out[-1].get("date")) if out else ""
    in_window = False
    try:
        from live_quote import is_live_merge_window

        in_window = bool(is_live_merge_window())
    except Exception:
        in_window = False
    if not in_window:
        # 官方已有今日且量>0 → 不准再用 MIS 蓋；量=0 仍准疊（Yahoo 未齊）
        if last_d and last_d >= today:
            try:
                last_vol = float((out[-1] or {}).get("volume") or 0)
            except (TypeError, ValueError):
                last_vol = 0.0
            if last_vol > 0:
                return out
    merged = _merge_live_index_display_bar(bars, live, today=today)
    # 非盤中現金窗：疊完一律標收盤（live_session=0），不准還寫盤中
    # （含 13:30–16:30 合併窗外／週末；合併窗內由牆鐘決定是否仍盤中）
    if merged and not _twii_cash_session_live():
        last = dict(merged[-1])
        if int(last.get("live_session") or 0) == 1:
            last["live_session"] = 0
            merged[-1] = last
    return merged


def _merge_live_sox_display_bar(
    bars: Sequence[Dict[str, Any]], live: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """美股現金盤中：Yahoo 費半當日未收柱疊顯示（不寫庫）。

    live_session≠1（含週末休市官方收）不准蓋掉日K，否則黃框「收盤」會吃到盤後殘價。
    """
    if not live:
        return [dict(r) for r in (bars or [])]
    if int((live or {}).get("live_session") or 0) != 1:
        return [dict(r) for r in (bars or [])]
    day = _ymd(live.get("date")) or ""
    if len(day) != 8:
        return [dict(r) for r in (bars or [])]
    return _merge_live_index_display_bar(bars, live, today=day)


def _ensure_paint_live_sox(
    pack: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """出圖當下再抓費半（force）。

    黃框／末根K 只在美股**現金盤中**（regular）疊即時＝標「盤中」。
    盤後／盤前／週末：清掉 live_sox，黃框走官方收＝標「收盤」；
    不准把盤後殘價併進列卻寫收盤（話筒會看成錯價）。
    撐壓階梯仍可用抓到的價刷新（不寫進 live_sox）。
    """
    dt = now or datetime.now(TAIPEI)
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    live: Optional[Dict[str, Any]] = None
    try:
        from us_overnight import fetch_live_sox_display_bar

        live = fetch_live_sox_display_bar(dt, force=True)
    except Exception:
        logger.debug("出圖費半即時略過", exc_info=True)
        live = None
    # 只認現金盤中；盤前／盤後 live_session=1 也不准蓋官方收
    is_live = bool(live) and int((live or {}).get("live_session") or 0) == 1
    if is_live and not _sox_cash_session_live(dt):
        is_live = False
    try:
        from us_overnight import _us_cash_calendar_closed

        if is_live and _us_cash_calendar_closed(dt):
            is_live = False
    except Exception:
        pass
    if is_live and isinstance(pack, dict):
        pack["live_sox"] = live
        try:
            pred = (
                pack.get("pred_levels")
                if isinstance(pack.get("pred_levels"), dict)
                else {}
            )
            pack["pred_levels"] = _refresh_sox_pred_cascade(
                pred, "", sox_px=float(live.get("close") or 0)
            )
        except Exception:
            logger.debug("出圖費半撐壓階梯略過", exc_info=True)
        return live
    if isinstance(pack, dict):
        # 休市／非現金盤中：一律清殘旗，不准盤後殘價蓋收盤
        pack.pop("live_sox", None)
        if live:
            try:
                pred = (
                    pack.get("pred_levels")
                    if isinstance(pack.get("pred_levels"), dict)
                    else {}
                )
                pack["pred_levels"] = _refresh_sox_pred_cascade(
                    pred, "", sox_px=float(live.get("close") or 0)
                )
            except Exception:
                pass
    return None


def compute_teach_tip_snapshot(
    db_path: str,
    pack: Optional[Dict[str, Any]] = None,
    *,
    reuse_frozen: bool = True,
) -> Dict[str, Any]:
    """三窗現況一口：加權／費半／台指電子盤 asof＋收／是否盤中。

    話筒存檔回退要比對這份；三張對不起來＝不准混用舊圖。
    pack 已有 prep 凍結的 teach_tip（含三價）→ 直接重用，遠／近／超近同口。
    prep 當下算凍結時傳 reuse_frozen=False。
    """
    pack = pack if isinstance(pack, dict) else {}
    frozen = pack.get("teach_tip") if isinstance(pack.get("teach_tip"), dict) else None
    if (
        reuse_frozen
        and frozen
        and frozen.get("tw_close")
        and frozen.get("tx_close")
    ):
        # 已凍結：三窗 paint 重入不准重抓漂價
        return {
            "tw_asof": _ymd(frozen.get("tw_asof")) or "",
            "tw_close": frozen.get("tw_close"),
            "tw_live": int(frozen.get("tw_live") or 0),
            "sox_asof": _ymd(frozen.get("sox_asof")) or "",
            "sox_close": frozen.get("sox_close"),
            "sox_live": int(frozen.get("sox_live") or 0),
            "tx_asof": _ymd(frozen.get("tx_asof")) or "",
            "tx_close": frozen.get("tx_close"),
            "tx_live": int(frozen.get("tx_live") or 0),
        }
    out: Dict[str, Any] = {
        "tw_asof": "",
        "tw_close": None,
        "tw_live": 0,
        "sox_asof": "",
        "sox_close": None,
        "sox_live": 0,
        "tx_asof": "",
        "tx_close": None,
        "tx_live": 0,
    }
    wall = _query_now_from_pack(pack)
    try:
        bars = _twii_bars_for_teach(db_path, 8, pack)
        if bars:
            out["tw_asof"] = _ymd(bars[-1].get("date"))
            try:
                out["tw_close"] = float(bars[-1].get("close") or 0) or None
            except (TypeError, ValueError):
                out["tw_close"] = None
            live = int((bars[-1] or {}).get("live_session") or 0) == 1
            if live and not _twii_cash_session_live(wall):
                live = False
            out["tw_live"] = 1 if live else 0
    except Exception:
        logger.debug("teach tip tw 略過", exc_info=True)
    try:
        sox_live = None
        raw = pack.get("live_sox") if isinstance(pack.get("live_sox"), dict) else None
        if (
            isinstance(raw, dict)
            and float(raw.get("close") or 0) > 0
            and int(raw.get("live_session") or 0) == 1
            and _sox_cash_session_live(wall)
        ):
            sox_live = raw
        sox_rows = _load_us_daily(db_path, "SOX", "20260101") if db_path else []
        pair = _us_real_close_pair(sox_rows, sox_live)
        out["sox_asof"] = _ymd(pair.get("asof")) or ""
        out["sox_close"] = pair.get("close")
        out["sox_live"] = 1 if sox_live else 0
    except Exception:
        logger.debug("teach tip sox 略過", exc_info=True)
    try:
        tip = _resolve_tx_after_hours_tip(db_path, pack)
        if tip and float(tip.get("close") or 0) > 0:
            out["tx_asof"] = _ymd(tip.get("asof")) or ""
            out["tx_close"] = float(tip["close"])
            night = bool(_tx_night_session_live(wall))
            out["tx_live"] = 1 if night and str(tip.get("clock") or "").strip() else 0
    except Exception:
        logger.debug("teach tip tx 略過", exc_info=True)
    return out


def teach_tip_snapshots_match(
    want: Optional[Dict[str, Any]],
    got: Optional[Dict[str, Any]],
    *,
    px_tol: float = 1.5,
) -> bool:
    """存檔 tip 與當下 tip 同口才准回退舊圖；缺欄／價差＝否。"""
    if not isinstance(want, dict) or not isinstance(got, dict) or not want or not got:
        return False
    for prefix in ("tw", "sox", "tx"):
        wa = _ymd(want.get(f"{prefix}_asof"))
        ga = _ymd(got.get(f"{prefix}_asof"))
        if wa and ga and wa != ga:
            return False
        if int(want.get(f"{prefix}_live") or 0) != int(got.get(f"{prefix}_live") or 0):
            return False
        try:
            wc = float(want.get(f"{prefix}_close") or 0)
            gc = float(got.get(f"{prefix}_close") or 0)
        except (TypeError, ValueError):
            return False
        if wc <= 0 or gc <= 0:
            return False
        if abs(wc - gc) > float(px_tol):
            return False
    return True


def _sox_axis_index_for_ymd(
    bars: Sequence[Dict[str, Any]],
    *,
    n_tw: int,
    sox_extra_dates: Sequence[str],
    ymd: str,
    n_axis: int,
) -> Optional[int]:
    """費半真實美股日 → 對齊軸索引（加權日格或加權後延長格）。"""
    day = _ymd(ymd)
    if len(day) != 8 or n_axis <= 0:
        return None
    for i, r in enumerate(bars or []):
        if i >= int(n_tw):
            break
        if _ymd((r or {}).get("date")) == day:
            return int(i)
    for j, d in enumerate(sox_extra_dates or []):
        if _ymd(d) == day:
            i = int(n_tw) + int(j)
            if 0 <= i < int(n_axis):
                return i
    return None


def _apply_live_sox_to_axis(
    *,
    sox_o: List[float],
    sox_h: List[float],
    sox_l: List[float],
    sox_c: List[float],
    tw_bars: Sequence[Dict[str, Any]],
    live: Optional[Dict[str, Any]],
    n_tw: int,
) -> Optional[int]:
    """即時 OHLC 寫進對齊軸對應格；回傳更新索引（黃框／縮圖K共用）。"""
    if not live or not sox_c:
        return None
    day = _ymd(live.get("date"))
    try:
        px = float(live.get("close") or 0)
        o = float(live.get("open") or px)
        h = float(live.get("high") or max(o, px))
        lo = float(live.get("low") or min(o, px))
    except (TypeError, ValueError):
        return None
    if not day or px <= 0:
        return None
    i_hit: Optional[int] = None
    for i, r in enumerate(tw_bars or []):
        if i >= int(n_tw):
            break
        if _ymd(r.get("date")) == day:
            i_hit = i
            break
    if i_hit is None:
        # 加權軸後延伸的美股日
        if len(sox_c) > int(n_tw):
            i_hit = len(sox_c) - 1
        elif tw_bars and _ymd((tw_bars[-1] or {}).get("date")) == day:
            i_hit = max(0, int(n_tw) - 1)
        else:
            return None
    if not (0 <= int(i_hit) < len(sox_c)):
        return None
    i = int(i_hit)

    def _finite(v: float, fallback: float) -> float:
        try:
            x = float(v)
            return x if x == x else fallback
        except (TypeError, ValueError):
            return fallback

    old_h = _finite(sox_h[i] if i < len(sox_h) else px, px)
    old_l = _finite(sox_l[i] if i < len(sox_l) else px, px)
    sox_o[i] = o
    sox_c[i] = px
    sox_h[i] = max(h, px, o, old_h)
    sox_l[i] = min(x for x in (lo, px, o, old_l) if x and x == x)
    return i


def _fill_missing_twii_open_days_from_db(
    db_path: str, bars: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """圖軸首尾之間：開市日若庫內有官方柱卻缺席 → 插回。不准捏沒庫的假柱。

    漏一根會讓黃框漲跌％／點數用錯前收（例缺 11/06 → 假 +0.21%）。
    """
    out = [dict(r) for r in (bars or [])]
    if not db_path or len(out) < 2:
        return out
    first = _ymd(out[0].get("date"))
    last = _ymd(out[-1].get("date"))
    if len(first) != 8 or len(last) != 8 or first >= last:
        return out
    have = {_ymd(r.get("date")) for r in out if _ymd(r.get("date"))}
    try:
        from trading_calendar import is_tw_open_calendar_day

        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII') AND date>? AND date<? "
                "AND close>0 ORDER BY date",
                (first, last),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return out
    extra: List[Dict[str, Any]] = []
    for date_s, o, h, l, c, v in rows or ():
        d = _ymd(date_s)
        if not d or d in have:
            continue
        try:
            if not is_tw_open_calendar_day(d):
                continue
        except Exception:
            pass
        try:
            cv = float(c or 0)
        except (TypeError, ValueError):
            continue
        if cv <= 0:
            continue
        extra.append(
            {
                "date": d,
                "open": float(o or cv),
                "high": float(h or cv),
                "low": float(l or cv),
                "close": cv,
                "volume": float(v or 0),
            }
        )
        have.add(d)
    if not extra:
        return out
    merged = out + extra
    merged.sort(key=lambda r: _ymd(r.get("date")) or "")
    return merged


def _sanitize_bar_ohlc(row: Dict[str, Any]) -> Dict[str, Any]:
    """缺 high／low／open 時用 close 補；不准留下 0 高低下使末K隱形（量柱還在）。"""
    out = dict(row or {})
    try:
        c = float(out.get("close") or 0)
    except (TypeError, ValueError):
        c = 0.0
    if c <= 0:
        return out
    try:
        o = float(out.get("open") or 0)
    except (TypeError, ValueError):
        o = 0.0
    if o <= 0:
        o = c
    try:
        h = float(out.get("high") or 0)
    except (TypeError, ValueError):
        h = 0.0
    try:
        lo = float(out.get("low") or 0)
    except (TypeError, ValueError):
        lo = 0.0
    if h <= 0:
        h = max(o, c)
    if lo <= 0:
        lo = min(o, c)
    h = max(h, o, c)
    lo = min(lo, o, c)
    out["open"], out["high"], out["low"], out["close"] = o, h, lo, c
    return out


def _mark_intraday_incomplete_twii_bar(
    bars: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    pack: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """盤中現金窗：Yahoo 已寫今日柱但量=0／未標 live → 當盤中未收顯示。

    MIS 抓不到時，不准因 index_daily 有今日就誤標「收盤」。
    量>0 視為已有可認成交量（通常已收）→ 不改。非開市日／非盤中窗不改。
    """
    out = [dict(r) for r in (bars or [])]
    if not out:
        return out
    dt = _query_now_from_pack(pack, now=now)
    if not _twii_cash_session_live(dt):
        return out
    today = dt.strftime("%Y%m%d")
    last = out[-1]
    if _ymd(last.get("date")) != today:
        return out
    if int(last.get("live_session") or 0) == 1:
        return out
    try:
        vol = float(last.get("volume") or 0)
    except (TypeError, ValueError):
        vol = 0.0
    # Yahoo 盤中常先寫 OHLC、量仍 0；此時一定是未收
    if vol > 0:
        return out
    out[-1] = {**last, "live_session": 1}
    return out


def _twii_bars_for_teach(
    db_path: str, n: int, pack: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """教具用加權柱：指數最新已收官方柱＋（盤中）MIS 顯示疊加。

    遠／近／超近三張都必須畫到最新交易日縮圖K；盤中查／飆大新文要立刻對得上。
    開市日庫內有柱就不准從圖軸漏掉。
    """
    from biaoke_wave import _load_twii_bars

    bars = list(_load_twii_bars(db_path, n=n, teach=True) or [])
    if bars:
        _ensure_twii_prev_close_day(db_path, _ymd(bars[-1].get("date")))
        # 同步後重讀，把缺的前收開市日補進軸
        bars = list(_load_twii_bars(db_path, n=n, teach=True) or [])
    bars = _fill_missing_twii_open_days_from_db(db_path, bars)
    live = (pack or {}).get("live_twii") if isinstance(pack, dict) else None
    if live:
        bars = _merge_live_twii_display_bar(bars, live)
    bars = _mark_intraday_incomplete_twii_bar(bars, pack=pack)
    return [_sanitize_bar_ohlc(r) for r in bars]


# 教具準備：飆大文節流（行情每次可抓；貼文網頁不要連打爆）
_TEACH_BIAOKE_FRESH_AT: Dict[str, float] = {}
_TEACH_BIAOKE_FRESH_SEC = 180.0  # 盤中／活畫 3 分內同庫只補一次


def _ensure_teach_biaoke_posts_fresh(
    db_path: str, *, now: Optional[datetime] = None, force: bool = False
) -> Dict[str, Any]:
    """三窗／波浪準備：行情會即時補，飆大公開文也要跟上（失敗不擋出圖）。

    根因：本機／agent 庫常停在舊 snapshot，但 Yahoo／MIS 每次都抓到當下 →
    白底／漲幅是新的、口頭標籤卻停在多天前。Render 常駐 ingest 沒這洞。
    這裡跟 ``_ensure_teach_index_bars`` 同層；節流避免三張連打公開頁。
    """
    out: Dict[str, Any] = {"ok": False, "skipped": False, "reason": ""}
    path = str(db_path or "").strip()
    if not path:
        out["reason"] = "no_db"
        return out
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    import time as _time

    key = os.path.abspath(path)
    age = _time.time() - float(_TEACH_BIAOKE_FRESH_AT.get(key) or 0.0)
    if (not force) and age < float(_TEACH_BIAOKE_FRESH_SEC):
        out["ok"] = True
        out["skipped"] = True
        out["reason"] = "throttled"
        out["age_s"] = round(age, 1)
        return out
    try:
        from biaoke_ingest import ingest_public_posts

        # 輕量：只補最近幾則主文＋討論串；seed 1709 在 ingest 內已是缺才補
        stats = ingest_public_posts(
            db_path=path, max_ids=16, refresh_latest=4
        ) or {}
        _TEACH_BIAOKE_FRESH_AT[key] = _time.time()
        out["ok"] = bool(stats.get("ok", True))
        out["stats"] = {
            k: stats.get(k)
            for k in ("added", "updated", "replies", "n", "fetched", "ok", "reason")
            if k in stats
        }
        out["as_of"] = dt.strftime("%Y%m%d")
        return out
    except Exception:
        logger.exception("教具補飆大公開文略過")
        out["reason"] = "ingest_failed"
        return out


def _ensure_teach_index_bars(db_path: str) -> None:
    """活畫前補齊加權／費半最新官方日K（失敗不擋出圖）。"""
    if not db_path:
        return
    try:
        from taiwan_market import sync_index_daily

        sync_index_daily(db_path, range_="3mo")
    except Exception:
        logger.exception("教具補加權日K略過")
    # Yahoo 常留量=0：節流打 FMTQIK 補官方全日量（沒真數不寫）
    try:
        from taiwan_market import _maybe_fill_zero_index_volumes

        _maybe_fill_zero_index_volumes(db_path)
    except Exception:
        logger.debug("教具補加權量略過", exc_info=True)
    # 加權軸要比到「最近一個台股開市日」：週末／假日也要補齊上一個開市收
    # （舊邏輯只在開市日且 asof<today 才短窗 sync → 週日仍停週四時，
    #  費半周五會變成延長格，四欄共用軸被標成「11/6費半」、下三欄右緣像缺K）
    try:
        from trading_calendar import (
            is_tw_open_calendar_day,
            last_open_calendar_day_on_or_before,
        )
        from taiwan_market import sync_index_daily

        today = datetime.now(TAIPEI).strftime("%Y%m%d")
        target = (
            today
            if is_tw_open_calendar_day(today)
            else last_open_calendar_day_on_or_before(today)
        )
        asof = _twii_chart_as_of(db_path)
        if target and asof < target:
            sync_index_daily(db_path, range_="1mo")
    except Exception:
        logger.debug("教具補最近開市加權再同步略過", exc_info=True)
    try:
        _ensure_us_index_daily(db_path)
    except Exception:
        logger.exception("教具補費半日K略過")


def _twii_db_today_volume(db_path: str, today: str) -> float:
    """庫內加權今日成交量；缺列／讀失敗＝0（當未齊）。"""
    day = _ymd(today)
    if not db_path or len(day) != 8:
        return 0.0
    try:
        from biaoke_wave import _load_twii_bars

        bars = list(_load_twii_bars(db_path, n=6, teach=True) or [])
    except Exception:
        return 0.0
    for r in reversed(bars):
        if _ymd((r or {}).get("date")) == day:
            try:
                return float((r or {}).get("volume") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _fill_live_twii_when_official_lags(
    pack: Dict[str, Any], db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """開市日官方日K還沒到今天：用 MIS 最後一筆疊顯示柱（盤中＋盤後入庫空窗）。

    話筒波浪鍵連盤中／剛收盤都要看得到今日加權＋量；不准卡在昨日收盤黃框。
    Yahoo 常先寫今日 OHLC、量仍 0：視為未齊，16:30 前仍要疊 MIS，
    不准因 asof==今天就標「收盤」卻留下量 0／錯價（遠／近白底日期％會漂）。
    """
    out = dict(pack or {})
    if out.get("live_twii"):
        return out
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    today = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_tw_open_calendar_day

        if not is_tw_open_calendar_day(today):
            return out
    except Exception:
        return out
    asof = _ymd(out.get("chart_as_of")) or _twii_chart_as_of(db_path)
    need = False
    if not asof or asof < today:
        need = True
    else:
        # 今日列已在、量仍 0：合併窗內仍當官方落後
        try:
            from live_quote import is_live_merge_window

            in_merge = bool(is_live_merge_window(dt))
        except Exception:
            in_merge = False
        if in_merge and _twii_db_today_volume(db_path, today) <= 0:
            need = True
    if not need:
        return out
    try:
        from live_quote import fetch_mis_index_quote

        live = fetch_mis_index_quote(fresh=True, require_session=False)
        if live:
            out["live_twii"] = live
    except Exception:
        logger.debug("教具 MIS 加權疊柱略過", exc_info=True)
    return out


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
    prev_c = _prev_valid_close(closes, int(i_now), opens=opens)
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
    # 今收 tip：略偏右，不准坐在實心邊上看成浪點；Y 仍鎖收盤；單一細圈
    _spear_ring(
        ax,
        float(i_now) + 0.38,
        float(closes[i_now]),
        color="#ea80fc",
        zorder=16,
        hot=True,
        clip_on=False,
    )


def _bar_clock_tag(bars: Sequence[Dict[str, Any]]) -> str:
    """末日若為盤中疊加 →『盤中』；否則『收盤』（不准把未收當收）。

    教具標題請用 `_teach_query_clock`（含查詢當下 HH:MM）；本函式留相容。
    """
    if bars and int((bars[-1] or {}).get("live_session") or 0) == 1:
        return "盤中"
    return "收盤"


def _stamp_md_phase(asof_ymd: Any, *, live: bool = False) -> str:
    """相容舊名：幾月幾號收盤｜幾月幾號盤中。"""
    return _stamp_when_bit(asof_ymd, live=live, query_hm="")


def _stamp_query_hm(
    pack: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> str:
    """查詢當下 HH:MM（台北）；給盤中白底戳，不准用 MIS 末筆成交鐘冒充查詢時。"""
    dt = None
    if isinstance(pack, dict):
        dt = _parse_query_at(pack.get("query_at"))
    if dt is None:
        dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    return dt.strftime("%H:%M")


def _stamp_when_bit(
    asof_ymd: Any,
    *,
    live: bool = False,
    query_hm: str = "",
) -> str:
    """白底戳時間位：幾月幾號收盤｜幾月幾號盤中 查詢當下為HH:MM。

    收盤＝官方已收；盤中＝即時未收。查詢鐘點只在盤中出現。
    """
    md = _md(_ymd(asof_ymd))
    hm = str(query_hm or "").strip()
    # 容忍 MIS 傳來的 HH:MM:SS → 只留 HH:MM
    if len(hm) >= 5 and hm[2] == ":":
        hm = hm[:5]
    elif ":" not in hm:
        hm = ""
    if live:
        base = f"{md}盤中" if md else "盤中"
        if hm:
            return f"{base} 查詢當下為{hm}"
        return base
    return f"{md}收盤" if md else "收盤"


def _tx_night_session_live(now: Optional[datetime] = None) -> bool:
    """台指電子盤（夜盤）是否進行中：台北 15:00–翌日 05:00，且起日為台股開市日。

    週末／國定假起日不准標盤中（例：週六 16:22 不准因鐘點落在 15:00 後就寫盤中）。
    週五夜→週六清晨：起日＝週五開市日 → 05:00 前仍算進行中。
    """
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    hm = int(dt.hour) * 60 + int(dt.minute)
    if hm >= 15 * 60:
        start_ymd = dt.strftime("%Y%m%d")
    elif hm < 5 * 60:
        start_ymd = (dt - timedelta(days=1)).strftime("%Y%m%d")
    else:
        return False
    try:
        from trading_calendar import is_tw_open_calendar_day

        return bool(is_tw_open_calendar_day(start_ymd))
    except Exception:
        try:
            return datetime.strptime(start_ymd, "%Y%m%d").weekday() < 5
        except ValueError:
            return False


def _sox_cash_session_live(now: Optional[datetime] = None) -> bool:
    """費半＝美股 SOX 現金盤中（NYSE regular）才准標盤中；盤前／盤後／休市＝否。"""
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    try:
        from us_overnight import us_tape_phase

        return us_tape_phase(dt) == "regular"
    except Exception:
        return False


def _twii_cash_session_live(now: Optional[datetime] = None) -> bool:
    """加權現貨盤中：台股開市日 09:00–未滿 13:30。"""
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    try:
        from trading_calendar import is_tw_open_calendar_day

        if not is_tw_open_calendar_day(dt.strftime("%Y%m%d")):
            return False
    except Exception:
        if dt.weekday() >= 5:
            return False
    hm = int(dt.hour) * 60 + int(dt.minute)
    return 9 * 60 <= hm < 13 * 60 + 30


def _query_now_from_pack(
    pack: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> datetime:
    """查詢牆鐘：pack['query_at'] 優先，否則 now／此刻（台北）。"""
    dt = None
    if isinstance(pack, dict):
        dt = _parse_query_at(pack.get("query_at"))
    if dt is None:
        dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI)


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


# 教具查詢戳：白底；開盤／盤中＝螢光綠框（#ffff00 霓虹邊）；收盤／盤前／休市＝黑邊
# 話筒口頭「螢光綠框」＝這條霓虹邊，不准改紅／紫實心底
_TEACH_STAMP_EDGE = "#ffff00"
_TEACH_STAMP_EDGE_LIVE = "#ffff00"
_TEACH_STAMP_EDGE_CLOSED = "#111111"
# 遠窗台指電子盤：盤中同規白底＋螢光綠框；收盤黑邊
_TEACH_STAMP_EDGE_TX = "#ffff00"
_TEACH_STAMP_EDGE_TX_LIVE = "#ffff00"
# 三欄縮圖K底「末日」刻度：盤中螢光黃綠；收盤／盤前＝一般白字
_TEACH_LAST_DATE_NEON = "#ccff00"
# 右欄智慧席：新飆大點位可進；超過軟上限丟低優先，不准一次擠爆
_TEACH_RIGHT_SOFT_CAP = 11  # 雙軌四價＋39000＋今／大B 必留；寧可疏也不折接
# Telegram Bot sendPhoto：寬+高須 ≤10000，否則 PHOTO_INVALID_DIMENSIONS
_TG_PHOTO_MAX_WH_SUM = 9900


def _shrink_png_for_telegram(path: str, *, max_sum: int = _TG_PHOTO_MAX_WH_SUM) -> str:
    """話筒送圖前：若寬+高超限就等比縮小寫回同一檔。不准裁內容。"""
    if not path or not os.path.isfile(path):
        return path
    try:
        from PIL import Image
    except Exception:
        return path
    try:
        im = Image.open(path)
        w, h = im.size
        lim = int(max_sum or _TG_PHOTO_MAX_WH_SUM)
        if w + h <= lim or w <= 0 or h <= 0:
            im.close()
            return path
        scale = float(lim) / float(w + h)
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        out = im.resize((nw, nh), Image.Resampling.LANCZOS)
        im.close()
        out.save(path, format="PNG", optimize=True)
        out.close()
    except Exception:
        logger.debug("Telegram 圖縮略過 path=%s", path, exc_info=True)
    return path
_TEACH_STAMP_FACE = "#ffffff"
_TEACH_STAMP_META = "#111111"
_TEACH_STAMP_TEXT = "#111111"  # 相容舊讀；實畫走分段色
# 八浪縮圖鎖超近窗實測大小（fig 15.6×9.6 → fraction）；遠／近換算同吋後放黃虛線左
# 略放大一點，黃框／浪線／字改細，手機才看得清
_TEACH_EIGHT_WAVE_INSET_REF_FIG = (15.6, 9.6)
_TEACH_EIGHT_WAVE_INSET_W_FRAC = 0.248
_TEACH_EIGHT_WAVE_INSET_H_FRAC = 0.218


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


def _index_daily_close(db_path: str, symbol: str, ymd: str) -> Optional[float]:
    """讀 index_daily 某日收；缺就空。"""
    day = _ymd(ymd)
    sym = str(symbol or "").strip()
    if not db_path or not day or not sym:
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT close FROM index_daily WHERE symbol=? AND date=? AND close>0",
                (sym, day),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    try:
        v = float(row[0])
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _prev_open_ymd(ymd: str) -> str:
    """嚴格前一個台股開市日（不含當日）。"""
    day = _ymd(ymd)
    if len(day) != 8:
        return ""
    try:
        from trading_calendar import last_open_calendar_day_on_or_before

        probe = (
            datetime.strptime(day, "%Y%m%d") - timedelta(days=1)
        ).strftime("%Y%m%d")
        return last_open_calendar_day_on_or_before(probe) or ""
    except Exception:
        return ""


def _prev_bar_close(
    bars: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    symbol: str = "TWII",
) -> Optional[float]:
    """前一個交易日收。

    只認「末日的嚴格前一個開市日」收。圖軸／庫若漏那一天，不准改抓更早的
    bars[-2]（例缺 11/06＋11/09 → 誤用 11/05 → 假 +2.74%／+1,137）。
    有 db 先讀 index_daily；再只在 bars 裡找 date==期望日前收。
    """
    if not bars:
        return None
    last_d = _ymd((bars[-1] or {}).get("date"))
    expect = _prev_open_ymd(last_d) if last_d else ""
    if not expect:
        return None
    if db_path:
        got = _index_daily_close(db_path, symbol, expect)
        if got is not None:
            return got
    for j in range(len(bars) - 2, -1, -1):
        d = _ymd((bars[j] or {}).get("date"))
        if d != expect:
            continue
        try:
            v = float((bars[j] or {}).get("close") or 0)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None
    return None


def _ensure_twii_prev_close_day(db_path: str, last_ymd: str) -> None:
    """末日的前一個開市日若庫內沒收 → 短窗再同步官方加權（失敗不擋）。"""
    expect = _prev_open_ymd(last_ymd)
    if not db_path or not expect:
        return
    if _index_daily_close(db_path, "TWII", expect) is not None:
        return
    if _index_daily_close(db_path, "^TWII", expect) is not None:
        return
    try:
        from taiwan_market import sync_index_daily

        sync_index_daily(db_path, range_="1mo")
    except Exception:
        logger.debug("加權前收缺日短窗同步略過", exc_info=True)


# 加權／費半黃框同一字級與框高；費半字少→寬自然較短
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
    label_prefix: str = "",
    db_path: str = "",
) -> str:
    """查詢戳一行：名稱 幾月幾號收盤|盤中 查詢當下為HH:MM →價→（漲幅％）→較前日點數。"""
    as_of = _ymd(bars[-1].get("date")) if bars else ""
    live = bool(bars) and int((bars[-1] or {}).get("live_session") or 0) == 1
    # 加權現貨：週末／休市／非 09:00–13:30 不准硬寫盤中
    if live and not _twii_cash_session_live(_query_now_from_pack(pack)):
        live = False
    when = _stamp_when_bit(
        as_of,
        live=live,
        query_hm=_stamp_query_hm(pack) if live else "",
    )
    prefix = str(label_prefix or "").strip()
    meta = f"{prefix} {when}".strip() if prefix else when
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
    db = str(db_path or (pack or {}).get("db_path") or "").strip()
    chg = _day_change_vs_prev(px_v, _prev_bar_close(bars, db_path=db))
    chg_s = str(chg.get("text") or "").strip()
    if chg_s:
        return f"{meta}  {px_s}  {chg_s}"
    return f"{meta}  {px_s}"


def _stamp_box_alignment(ha: str, va: str = "top") -> Tuple[float, float]:
    ha_s = str(ha or "right")
    va_s = str(va or "top")
    hx = 0.0 if ha_s == "left" else (0.5 if ha_s == "center" else 1.0)
    vy = 0.0 if va_s == "bottom" else (0.5 if va_s == "center" else 1.0)
    return (hx, vy)


def _stack_upright_ylabel(text: str) -> str:
    """左軸標題正讀由上而下：漢字逐字、英文詞整段，不准橫躺歪頭看。"""
    parts: List[str] = []
    buf: List[str] = []
    for ch in str(text or ""):
        if ch.isspace():
            if buf:
                parts.append("".join(buf))
                buf = []
            continue
        if "\u4e00" <= ch <= "\u9fff" or ch in "／·・":
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append(ch)
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return "\n".join(parts) if parts else str(text or "")


def _set_upright_ylabel(ax: Any, text: str, *, fp: Any, color: str, fontsize: float = 10) -> None:
    """遠窗三欄左軸：逐字正讀由上而下（不用 set_ylabel 橫躺）。"""
    if ax is None:
        return
    # 清掉預設橫躺 ylabel
    try:
        ax.set_ylabel("")
    except Exception:
        pass
    parts = [p for p in _stack_upright_ylabel(text).split("\n") if p]
    if not parts:
        return
    n = len(parts)
    # 垂直置中；字距隨欄高自適應
    span = 0.62 if n <= 4 else min(0.78, 0.12 * n)
    y0 = 0.5 + span / 2.0
    step = span / max(n - 1, 1)
    for i, part in enumerate(parts):
        ax.text(
            -0.055,
            y0 - i * step,
            part,
            transform=ax.transAxes,
            fontproperties=fp(fontsize, "bold"),
            color=color,
            rotation=0,
            ha="center",
            va="center",
            clip_on=False,
            zorder=30,
        )


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


def _eight_wave_inset_rect_left_of_vmax(
    ax: Any,
    fig: Any,
    *,
    i_vmax: Optional[int],
    ymin: float,
    ymax: float,
    n_bars: int,
    gap_fig: float = 0.008,
    scale: float = 1.0,
    pin_bottom: bool = False,
) -> Tuple[float, float, float, float]:
    """與超近窗同寬同高（可 scale 縮小）；右緣貼垂直黃虛線左側。

    pin_bottom＝遠窗：貼加權欄左下縮小，不准擋任何縮圖K。
    """
    w, h = _teach_eight_wave_inset_wh(fig)
    sc = max(0.35, min(1.0, float(scale or 1.0)))
    w, h = float(w) * sc, float(h) * sc
    ys = max(float(ymax) - float(ymin), 1.0)
    y_bot = float(ymin) + ys * (0.04 if pin_bottom else 0.10)
    iv = int(i_vmax) if i_vmax is not None else max(0, int(n_bars) - 8)
    fx_v, fy_bot = _fig_xy_from_axes_data(ax, fig, float(iv), y_bot)
    left = float(fx_v) - float(gap_fig) - float(w)
    bottom = float(fy_bot)
    try:
        pos = ax.get_position()
        min_left = float(pos.x0) + 0.010
        max_frac = 0.26 if pin_bottom else 0.48
        max_bottom = float(pos.y0) + float(pos.height) * max_frac - float(h)
        min_bottom = float(pos.y0) + (0.005 if pin_bottom else 0.012)
    except Exception:
        min_left, max_bottom, min_bottom = 0.04, 0.55, 0.08
    if left < min_left:
        left = min_left
    if bottom > max_bottom:
        bottom = max(min_bottom, max_bottom)
    if bottom < min_bottom:
        bottom = min_bottom
    # 不准右緣跨過黃虛線
    if left + w > float(fx_v) - float(gap_fig):
        left = max(min_left, float(fx_v) - float(gap_fig) - float(w))
    return (float(left), float(bottom), float(w), float(h))


def _vol_sr_avoid_spans(vol_sr: Optional[Dict[str, Any]]) -> List[Tuple[float, float]]:
    """大量黃帶／下一層灰帶的價窗，給白底戳避讓。"""
    out: List[Tuple[float, float]] = []
    if not isinstance(vol_sr, dict):
        return out
    for key in ("primary", "next"):
        row = vol_sr.get(key) or {}
        try:
            lo = float(row.get("low"))
            hi = float(row.get("high"))
        except (TypeError, ValueError):
            continue
        if hi > lo > 0:
            out.append((lo, hi))
    return out


def _fig_stamp_xy_axes_top_left(
    ax: Any,
    fig: Any,
    *,
    left_frac: float = 0.02,
    below_top_frac: float = 0.16,
) -> Tuple[float, float]:
    """該圖框內左上：上緣線下方（遠窗三白底戳；ha=left／va=top）。

    錨點＝戳上緣；below_top_frac＝距軸上緣的欄高比例，整塊落在主圖框內，
    不准貼到／超出上框、不准壓上欄日期刻度。
    """
    try:
        pos = ax.get_position()
    except Exception:
        return (0.10, 0.78)
    x = float(pos.x0) + float(pos.width) * max(0.01, min(0.20, float(left_frac)))
    inset = max(0.08, min(0.28, float(below_top_frac)))
    y = float(pos.y1) - float(pos.height) * inset
    # 再保險：不准頂到上緣、也不准掉到欄中以下
    y = min(float(pos.y1) - 0.014, max(float(pos.y0) + float(pos.height) * 0.55, float(y)))
    return (float(x), float(y))


def _fig_stamp_xy_axes_bottom_right(
    ax: Any,
    fig: Any,
    *,
    right_clear_frac: float = 0.24,
    inset_y_frac: float = 0.045,
    stamp_h_data_frac: float = 0.10,
    avoid_spans: Optional[Sequence[Tuple[float, float]]] = None,
    avoid_ys: Optional[Sequence[float]] = None,
) -> Tuple[float, float]:
    """該圖框內偏右下；右緣讓出右標欄，不准壓右下價標／撐壓底色。"""
    try:
        pos = ax.get_position()
        ymin, ymax = ax.get_ylim()
    except Exception:
        return (0.78, 0.12)
    # 右對齊錨點停在欄寬 (1-right_clear) 處，白底戳往左長，右標仍看得見
    clear = max(0.14, min(0.36, float(right_clear_frac)))
    x = float(pos.x0) + float(pos.width) * (1.0 - clear)
    span = max(float(ymax) - float(ymin), 1.0)
    stamp_h = span * float(stamp_h_data_frac)
    bands = [
        (min(float(a), float(b)), max(float(a), float(b)))
        for a, b in (avoid_spans or [])
        if a is not None and b is not None
    ]
    # 右標單點也當薄帶避讓
    pad_y = span * 0.028
    for raw in avoid_ys or []:
        try:
            yy = float(raw)
        except (TypeError, ValueError):
            continue
        bands.append((yy - pad_y, yy + pad_y))

    def _hit(y0: float, y1: float) -> bool:
        for a, b in bands:
            if y0 < b and y1 > a:
                return True
        return False

    # 自底往上找不擋底色／右標的錨點（va=bottom → 戳在錨點之上）
    y_data = float(ymin) + span * float(inset_y_frac)
    for _ in range(28):
        if not _hit(y_data, y_data + stamp_h):
            break
        y_data += stamp_h * 0.40
        if y_data + stamp_h >= float(ymax) - span * 0.04:
            y_data = float(ymin) + span * float(inset_y_frac)
            break
    try:
        _fx, y = _fig_xy_from_axes_data(ax, fig, 0.0, float(y_data))
    except Exception:
        y = float(pos.y0) + 0.028
    y = max(float(pos.y0) + 0.012, min(float(y), float(pos.y1) - 0.04))
    return (float(x), float(y))


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


def _teach_stamp_edge(*, live: bool, kind: str = "tw") -> str:
    """戳框邊色：盤中／開盤＝螢光；收盤／盤前／休市＝黑。"""
    k = str(kind or "tw").lower()
    if bool(live):
        if k in {"tx", "te", "electronics", "夜盤"}:
            return str(_TEACH_STAMP_EDGE_TX_LIVE or _TEACH_STAMP_EDGE_TX)
        return str(_TEACH_STAMP_EDGE_LIVE or _TEACH_STAMP_EDGE)
    return str(_TEACH_STAMP_EDGE_CLOSED)


def _paint_axis_last_date_neon(
    ax,
    *,
    last_i: int,
    live: bool,
    fp=None,
) -> None:
    """縮圖K底末日刻度：必顯；盤中螢光黃綠、收盤／盤前白字。"""
    if ax is None:
        return
    try:
        ticks = list(ax.get_xticks())
        labels = list(ax.get_xticklabels())
    except Exception:
        return
    want = float(last_i)
    for lab, xv in zip(labels, ticks):
        try:
            if abs(float(xv) - want) > 0.51:
                continue
        except (TypeError, ValueError):
            continue
        col = _TEACH_LAST_DATE_NEON if bool(live) else _LIVE_TEXT
        try:
            lab.set_color(col)
            if fp is not None:
                lab.set_fontproperties(
                    fp(8.0 if live else 7.5, "bold" if live else "normal")
                )
            else:
                lab.set_fontweight("bold" if live else "normal")
        except Exception:
            pass


def _paint_stamp_hbox(
    fig,
    kids: List[Any],
    *,
    x: float,
    y: float,
    ha: str = "right",
    va: str = "top",
    zorder: float = 40,
    edgecolor: Optional[str] = None,
    ax: Any = None,
    live: Optional[bool] = None,
    kind: str = "tw",
) -> None:
    """白底圓角框（盤中螢光黃邊；收盤黑邊；共用框高與線寬）。

    點字盤硬規：面永遠白底；盤中／開盤＝螢光黃框（加權／費半），不准紅框紅底。
    ax 有給＝用該軸 axes fraction（鎖在主圖框內上緣下方）；否則 figure fraction。
    """
    from matplotlib.offsetbox import AnnotationBbox, HPacker

    if fig is None or not kids:
        return
    if ax is not None:
        xycoords = ax.transAxes
        host = ax
    else:
        xycoords = "figure fraction"
        host = fig
    if edgecolor is None and live is not None:
        edge = _teach_stamp_edge(live=bool(live), kind=kind)
    else:
        edge = str(edgecolor or _TEACH_STAMP_EDGE_CLOSED)
    # 加權／費半盤中若誤傳紅邊 → 強制螢光黃（紅框只留給台指電子盤 kind=tx）
    k = str(kind or "tw").lower()
    if bool(live) and k not in {"tx", "te", "electronics", "夜盤"}:
        if str(edge).lower() in {"#ff1744", "#ff5252", "#e53935", "#f44336", "red"}:
            edge = str(_TEACH_STAMP_EDGE_LIVE or _TEACH_STAMP_EDGE)
    ab = AnnotationBbox(
        HPacker(children=kids, align="center", pad=0, sep=0),
        (float(x), float(y)),
        xycoords=xycoords,
        box_alignment=_stamp_box_alignment(ha, va),
        pad=0.32,
        frameon=True,
        bboxprops=dict(
            boxstyle=f"round,pad={_TEACH_STAMP_BOX_PAD}",
            facecolor=_TEACH_STAMP_FACE,  # 永遠白底；盤中也不准紅／紫實心
            edgecolor=edge,
            linewidth=_TEACH_STAMP_BOX_LW,
        ),
        zorder=float(zorder),
    )
    # 欄頂白底戳：不准被 axes clip 裁半；整盒仍須落在格子內（呼叫端抬高 ylim／y）
    try:
        ab.set_clip_on(False)
    except Exception:
        pass
    host.add_artist(ab)


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
    va: str = "top",
    label_prefix: str = "加權",
    ax: Any = None,
    db_path: str = "",
) -> None:
    """黃框白底：名稱 幾月幾號收盤|盤中 查詢當下為HH:MM →價→（漲幅％）→較前日點數。

    預設貼右、略離上緣，不准壓標題白字；遠窗可改右下 va=bottom。
    盤中未收疊柱才標盤中＋查詢當下；官方已收標收盤。不准把未收當收。
    漲跌％／點數只認前一個開市日收；圖軸漏柱時用 db 官方收補，不准再出現假 +0.21%。
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
    live = int((bars[-1] or {}).get("live_session") or 0) == 1
    if live and not _twii_cash_session_live(_query_now_from_pack(pack)):
        live = False
    # prep 凍結 tip：三窗加權戳同口（不准遠／近／超近各吃一版 MIS）
    tip0 = (pack or {}).get("teach_tip") if isinstance(pack, dict) else None
    if (
        isinstance(tip0, dict)
        and str(label_prefix or "").strip() in {"", "加權"}
        and float(tip0.get("tw_close") or 0) > 0
    ):
        as_of = _ymd(tip0.get("tw_asof")) or as_of
        live = bool(int(tip0.get("tw_live") or 0))
        if close is None:
            close = float(tip0["tw_close"])
    when = _stamp_when_bit(
        as_of,
        live=live,
        query_hm=_stamp_query_hm(pack) if live else "",
    )
    prefix = str(label_prefix or "").strip()
    meta = f"{prefix} {when}".strip() if prefix else when
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
    db = str(db_path or (pack or {}).get("db_path") or "").strip()
    chg = _day_change_vs_prev(px_v, _prev_bar_close(bars, db_path=db))
    pct_s = str(chg.get("pct_text") or "").strip()
    pts_s = str(chg.get("pts_text") or "").strip()
    chg_col = _chg_paint_color(int(chg.get("sign") or 0))
    fsz = _teach_stamp_fsz(meta, px_s, pct_s, pts_s)
    kids = [
        TextArea(
            f"{meta}  ",
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
    _paint_stamp_hbox(
        fig,
        kids,
        x=x,
        y=y,
        ha=ha,
        va=va,
        zorder=40,
        live=live,
        kind="tw",
        ax=ax,
    )


def _us_real_close_pair(
    us_rows: Sequence[Dict[str, Any]],
    live: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """費半黃框用：只認真實美股日K（＋可選盤中 live），不准吃加權軸前收填日。

    加權軸缺美股日時 `_align_us_to_twii_dates` 會前收填滿 → 末兩根同價 →
    黃框假平盤 +0%。這裡改回原始 SOX 列算漲跌。
    """
    rows = [
        dict(r)
        for r in (us_rows or [])
        if float((r or {}).get("close") or 0) > 0 and _ymd((r or {}).get("date"))
    ]
    rows.sort(key=lambda r: _ymd(r.get("date")))
    if live and float((live or {}).get("close") or 0) > 0:
        day = _ymd(live.get("date"))
        if len(day) == 8:
            payload = {
                "date": day,
                "open": live.get("open") or live.get("close"),
                "high": live.get("high") or live.get("close"),
                "low": live.get("low") or live.get("close"),
                "close": live.get("close"),
            }
            if rows and _ymd(rows[-1].get("date")) == day:
                rows[-1] = payload
            elif not rows or day > _ymd(rows[-1].get("date")):
                rows.append(payload)
    if not rows:
        return {"close": None, "prev_close": None, "asof": "", "n": 0}
    close = float(rows[-1].get("close") or 0)
    asof = _ymd(rows[-1].get("date"))
    prev_close: Optional[float] = None
    if len(rows) >= 2:
        try:
            prev_close = float(rows[-2].get("close") or 0) or None
        except (TypeError, ValueError):
            prev_close = None
    return {
        "close": close if close > 0 else None,
        "prev_close": prev_close,
        "asof": asof,
        "n": len(rows),
    }


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
    va: str = "top",
    asof_ymd: str = "",
    chart_asof: str = "",
    session_live: bool = False,
    pack: Optional[Dict[str, Any]] = None,
    ax: Any = None,
) -> None:
    """費半黃框：名稱 幾月幾號收盤|盤中 查詢當下為HH:MM →價→（漲幅％）→較前日點數。

    asof_ymd＝費半真實美股日；盤中＝Yahoo 未收疊柱；收盤＝官方已收。
    """
    if fig is None or fp is None:
        return
    from matplotlib.offsetbox import TextArea

    # prep 凍結 tip：三窗費半戳同口
    tip0 = (pack or {}).get("teach_tip") if isinstance(pack, dict) else None
    if (
        isinstance(tip0, dict)
        and str(label_prefix or "費半").strip() in {"", "費半"}
        and float(tip0.get("sox_close") or 0) > 0
    ):
        close = float(tip0["sox_close"])
        asof_ymd = _ymd(tip0.get("sox_asof")) or asof_ymd
        session_live = bool(int(tip0.get("sox_live") or 0))
    chg = _day_change_vs_prev(close, prev_close)
    pct_s = str(chg.get("pct_text") or "").strip()
    pts_s = str(chg.get("pts_text") or "").strip()
    col = _chg_paint_color(int(chg.get("sign") or 0))
    asof = _ymd(asof_ymd)
    chart_d = _ymd(chart_asof)
    stale = bool(asof and chart_d and asof < chart_d)
    # 缺新美股收又算出平盤＝前收填日假象；拿掉假％，日期相位已在前綴
    if stale and int(chg.get("sign") or 0) == 0:
        pct_s = ""
        pts_s = ""
        col = _TEACH_STAMP_META
    try:
        px_s = _px(float(close))
    except (TypeError, ValueError):
        px_s = "—"
    live = bool(session_live)
    # 費半只認美股現金盤中；盤前／盤後／週末即使 live_session 殘旗也不准寫盤中
    if live and not _sox_cash_session_live(_query_now_from_pack(pack)):
        live = False
    when = _stamp_when_bit(
        asof,
        live=live,
        query_hm=_stamp_query_hm(pack) if live else "",
    )
    meta = f"{str(label_prefix or '費半').strip()} {when}".strip()
    fsz = _teach_stamp_fsz(meta, px_s, pct_s, pts_s)
    kids = [
        TextArea(
            f"{meta}  ",
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
    _paint_stamp_hbox(
        fig,
        kids,
        x=x,
        y=y,
        ha=ha,
        va=va,
        zorder=41,
        live=live,
        kind="sox",
        ax=ax,
    )


def _tx_night_evening_ymd(night_ymd: str) -> str:
    """futures_daily 夜盤 date（結束晨／下一開市標）→ 夜盤起日（15:00 那開市日）。"""
    ymd = _ymd(night_ymd)
    if len(ymd) != 8:
        return ""
    try:
        from market_session_cards import _evening_ymd_for_night_label

        eve = _ymd(_evening_ymd_for_night_label(ymd))
        if len(eve) == 8:
            return eve
    except Exception:
        pass
    try:
        from trading_calendar import last_open_calendar_day_on_or_before

        probe = (
            datetime.strptime(ymd, "%Y%m%d") - timedelta(days=1)
        ).strftime("%Y%m%d")
        return last_open_calendar_day_on_or_before(probe)
    except Exception:
        return ""


def _tx_night_rows_on_evening_axis(
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """教具加權日軸：夜盤列改掛起日。週五夜標週一時才能對上週五末K，不准停在崩盤夜。"""
    best: Dict[str, Dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        label = _ymd(raw.get("date"))
        if len(label) != 8:
            continue
        try:
            c = float(raw.get("close") or 0)
        except (TypeError, ValueError):
            c = 0.0
        if c <= 0:
            continue
        eve = _tx_night_evening_ymd(label) or label
        prev = best.get(eve)
        # 同一起日只留官方標籤較新的那列（週五夜週一標贏過同窗舊列）
        if prev is not None and str(prev.get("night_label") or "") >= label:
            continue
        best[eve] = {
            **raw,
            "date": eve,
            "night_label": label,
        }
    return [best[k] for k in sorted(best)]


def _ensure_latest_tx_night_row(db_path: str) -> None:
    """牆鐘 cap 當日夜盤列必須在庫；缺列會讓戳／末K吃到更舊夜盤。

    不准用 load_futures_night(date<=cap) 有舊列就當已齊——05:00 後 cap 已是今晨
    結束標（例 11/12），庫內若只有 11/11，舊寫法會誤判已齊、遠窗電子盤少最新一根。
    """
    if not db_path:
        return
    try:
        from taiwan_market import sync_futures_daily
        from trading_calendar import futures_night_date_cap
    except Exception:
        return
    try:
        cap = futures_night_date_cap()
    except Exception:
        return
    if len(cap) != 8:
        return
    # 只認 cap 當日那一列（官方結束標），不准 date<=cap 舊夜冒充
    have_cap = False
    try:
        rows = _load_tx_futures_daily(db_path, session="night", since=cap)
        for r in rows or []:
            if _ymd((r or {}).get("date")) == cap and float((r or {}).get("close") or 0) > 0:
                have_cap = True
                break
    except Exception:
        have_cap = False
    if have_cap:
        return
    try:
        sync_futures_daily(db_path, dates=[cap])
    except Exception:
        logger.debug("補最新台指夜盤列略過 cap=%s", cap, exc_info=True)


def _ensure_teach_tx_day_row(db_path: str, *, now: Optional[datetime] = None) -> None:
    """教具準備：開市日補齊大台日盤 regular（失敗不擋）。

    缺今日日盤時，遠窗電子盤戳只能退昨夜、加權已是今日收 → 三欄日期看起來「錯」。
    """
    if not db_path:
        return
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    today = dt.strftime("%Y%m%d")
    try:
        from trading_calendar import is_tw_open_calendar_day

        if not is_tw_open_calendar_day(today):
            return
    except Exception:
        return
    # 日盤未收完前不强抓；13:30 後才補今日 regular
    if _twii_cash_session_live(dt):
        return
    have = False
    try:
        rows = _load_tx_futures_daily(db_path, session="regular", since=today)
        for r in rows or []:
            if _ymd((r or {}).get("date")) == today and float((r or {}).get("close") or 0) > 0:
                have = True
                break
    except Exception:
        have = False
    if have:
        return
    try:
        from taiwan_market import sync_futures_daily

        sync_futures_daily(db_path, dates=[today])
    except Exception:
        logger.debug("教具補台指日盤略過 day=%s", today, exc_info=True)


def _resolve_tx_after_hours_tip(
    db_path: str, pack: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """台指電子盤戳用價：夜盤 MIS 即時優先。

    漲跌對照＝官方 CRefPrice（參考價／日盤結算），不准用前一夜盤收當前收
   （否則會把 −4.5% 算成 −8.7%）。
    夜盤未進行（週末／白天）：不准吃 MIS 殘價；改走庫內官方夜盤收。
    週末 cap 必含下一開市日標（週五夜）；asof 用夜盤起日對加權軸末K。
    """
    close: Optional[float] = None
    prev: Optional[float] = None
    asof = ""
    clock = ""
    night_live = _tx_night_session_live(_query_now_from_pack(pack))
    # prep 凍結 tip：日盤三窗電子盤戳同口（夜盤進行中仍走即時）
    tip0 = (pack or {}).get("teach_tip") if isinstance(pack, dict) else None
    tip_locked = False
    if (
        not night_live
        and isinstance(tip0, dict)
        and float(tip0.get("tx_close") or 0) > 0
    ):
        close = float(tip0["tx_close"])
        asof = _ymd(tip0.get("tx_asof")) or ""
        tip_locked = True
    # 0) pack 已抓的 live_tx（同口 OHLC＋ref）——只在夜盤進行中
    live0 = (pack or {}).get("live_tx") if isinstance(pack, dict) else None
    if (
        night_live
        and isinstance(live0, dict)
        and float(live0.get("close") or 0) > 0
    ):
        close = float(live0["close"])
        clock = str(live0.get("update_time") or "").strip()
        asof = _ymd(live0.get("date")) or ""
        for key in ("ref", "prev_close"):
            try:
                r = float(live0.get(key) or 0)
            except (TypeError, ValueError):
                r = 0.0
            if r > 0:
                prev = r
                break
        if prev is None:
            try:
                pct = live0.get("pct_change")
                if pct is not None and abs(float(pct) + 100.0) > 1e-9:
                    prev = close / (1.0 + float(pct) / 100.0)
                    if prev <= 0:
                        prev = None
            except (TypeError, ValueError):
                prev = None
    # 1) 夜盤即時 MIS——週末／白天不准抓殘價冒充收盤
    if night_live and close is None:
        try:
            from market_ticker import fetch_tx_live

            q = fetch_tx_live(night=True, timeout=2.5)
        except Exception:
            q = None
        if isinstance(q, dict) and float(q.get("close") or 0) > 0:
            close = float(q["close"])
            clock = str(q.get("update_time") or "").strip()
            try:
                r = float(q.get("ref") or q.get("prev_close") or 0)
            except (TypeError, ValueError):
                r = 0.0
            if r > 0:
                prev = r
            else:
                pct = q.get("pct_change")
                try:
                    if pct is not None and abs(float(pct) + 100.0) > 1e-9:
                        prev = close / (1.0 + float(pct) / 100.0)
                        if prev <= 0:
                            prev = None
                except (TypeError, ValueError):
                    prev = None
            asof = datetime.now(TAIPEI).strftime("%Y%m%d")
            if int(datetime.now(TAIPEI).hour) < 5:
                asof = (datetime.now(TAIPEI) - timedelta(days=1)).strftime("%Y%m%d")
    # 2) 庫內：現價＝最新已齊夜盤收；前收＝該夜起日日盤結算（對齊 CRefPrice）
    # tip 已鎖 close／asof 時仍走這段補 prev，不准另漂價
    if (close is None or tip_locked) and db_path:
        if close is None:
            try:
                _ensure_latest_tx_night_row(db_path)
            except Exception:
                pass
        try:
            from taiwan_market import load_futures_daily, load_futures_night
            from trading_calendar import futures_night_date_cap

            wall = _query_now_from_pack(pack)
            night = load_futures_night(
                db_path, futures_night_date_cap(wall), now=wall
            )
        except Exception:
            night = None
        if close is None and isinstance(night, dict) and float(night.get("close") or 0) > 0:
            close = float(night["close"])
            label = _ymd(night.get("date"))
            eve = _tx_night_evening_ymd(label) or label
            asof = eve
        if prev is None:
            eve = _ymd(asof)
            if len(eve) == 8:
                try:
                    reg = load_futures_daily(db_path, eve, symbol="TX") or {}
                    settle = float(reg.get("settlement") or 0)
                    if settle <= 0:
                        settle = float(reg.get("close") or 0)
                    if settle > 0:
                        prev = settle
                except Exception:
                    prev = None
    fut = (pack or {}).get("_fut_snap") if isinstance(pack, dict) else None
    if not isinstance(fut, dict) or not (fut.get("levels") or {}):
        try:
            fut = _futures_day_night(db_path)
        except Exception:
            fut = {}
    levels = (fut or {}).get("levels") or {}
    if close is None and not tip_locked:
        try:
            nc = float(levels.get("tx_night_c") or 0)
        except (TypeError, ValueError):
            nc = 0.0
        if nc > 0:
            close = nc
            note = str((fut or {}).get("note") or "")
            m = re.search(r"大台夜(\d{8})", note)
            if m:
                label = m.group(1)
                asof = _tx_night_evening_ymd(label) or label
    if prev is None:
        # 備援：勿直接用日盤收；優先結算。levels 只剩收才退。
        eve = _ymd(asof)
        if db_path and len(eve) == 8:
            try:
                from taiwan_market import load_futures_daily

                reg = load_futures_daily(db_path, eve, symbol="TX") or {}
                settle = float(reg.get("settlement") or 0)
                if settle <= 0:
                    settle = float(reg.get("close") or 0)
                if settle > 0:
                    prev = settle
            except Exception:
                pass
        if prev is None:
            try:
                dc = float(levels.get("tx_day_c") or 0)
            except (TypeError, ValueError):
                dc = 0.0
            if dc > 0:
                prev = dc
    if close is None or close <= 0:
        return None
    return {
        "close": float(close),
        "prev": float(prev) if prev and prev > 0 else None,
        "asof": _ymd(asof) or "",
        "clock": clock,
        "label": "台指電子盤",
    }


def _paint_tx_after_hours_tip(
    fig,
    *,
    close: float,
    prev_close: Optional[float] = None,
    label_prefix: str = "台指電子盤",
    fp=None,
    x: float = 0.995,
    y: float = 0.950,
    ha: str = "right",
    va: str = "bottom",
    clock: str = "",
    asof_ymd: str = "",
    session_live: Optional[bool] = None,
    pack: Optional[Dict[str, Any]] = None,
    ax: Any = None,
) -> None:
    """遠窗白底點字盤：台指電子盤 幾月幾號收盤|盤中 查詢當下為HH:MM →價→（漲幅％）→較前日點數。

    盤中＝白底螢光黃框（與加權／費半同規）；收盤＝白底黑框。
    夜盤進行中才標盤中；MIS 末筆 CTime 不准當「查詢當下」。貼電子盤欄右下。
    """
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
    asof = _ymd(asof_ymd)
    wall = _query_now_from_pack(pack)
    if session_live is None:
        live = bool(_tx_night_session_live(wall)) and bool(str(clock or "").strip())
    else:
        live = bool(session_live)
    # 週末／休市／非夜盤窗：呼叫端殘旗也不准硬寫盤中
    if live and not _tx_night_session_live(wall):
        live = False
    if live:
        when = _stamp_when_bit(
            asof,
            live=True,
            query_hm=_stamp_query_hm(pack),
        )
    else:
        # 夜盤已收：寫「夜收」＋起日，不准跟加權「日盤收」同一天卻看不出差源
        # （例：加權 11/13收盤、電子盤 11/12夜收 — 不是戳日期壞掉）
        md = _md(asof)
        when = f"{md}夜收" if md else "夜收"
    meta = f"{str(label_prefix or '台指電子盤').strip()} {when}".strip()
    del clock  # MIS 末筆鐘不准寫進查詢當下
    fsz = _teach_stamp_fsz(meta, px_s, pct_s, pts_s)
    kids = [
        TextArea(
            f"{meta}  ",
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
    _paint_stamp_hbox(
        fig,
        kids,
        x=x,
        y=y,
        ha=ha,
        va=va,
        zorder=42,
        live=live,
        kind="tx",
        ax=ax,
    )


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


def _biaoke_level_snip_score(blob: str, *, is_main: bool) -> int:
    """位階題旨打分：長主文＞短回；短「費半沒跌完」不准蓋長篇。"""
    score = 0
    if looks_like_level_now(blob):
        score += 10
    if _INDEXISH.search(blob):
        score += 3
    if re.search(
        r"波浪位階|主跌段|C3-\d|(?<![0-9])3-3-\d|重新修訂|動態修正|不能去抄底|破底|"
        r"假跌破|有效穿刺|1\s*[-–]?\s*4\s*重疊|(?:今天)?走\s*3-5|"
        r"第二組下跌|落底確認|劇本|5\s*波\s*跌完|走\s*B\s*[-–]?\s*b|"
        r"9\s*波\s*擴延|37837|底部判斷|41760|大盤止跌|大盤已經落底|"
        r"確認.{0,12}(?:上)?週五.{0,8}低點|"
        r"下降壓力線|不可能假跌破|回測下降壓|清洗籌碼",
        blob,
    ):
        score += 12
    # 後文下降壓改口／止跌確認／C3-5＋1 4重疊：壓較早雙軌／第二隻腳長文同分搶位
    if _text_has_c3_pressure_break(blob):
        score += 12
    if _text_has_stop_low_confirm(blob):
        score += 8
    n = len(blob)
    if n >= 120:
        score += 6
    if n >= 240:
        score += 6
    if is_main:
        score += 10
    elif n < 80:
        score -= 8
    return score


def _reply_level_delta(blob: str) -> bool:
    """樓下自回是否帶大盤／費半點位或改口（依時間序併進題旨；個股回測不收）。"""
    s = str(blob or "")
    if not s.strip():
        return False
    # 明確大盤／費半數字或改口
    if re.search(
        r"45546|46292|44210|44042|39384|42000|41000|40000|35000|38000|"
        r"35500|37300|37000|37500|9865|10445|8498|47500",
        s,
    ):
        return True
    # 改口／假跌破／9波擴延 C-7→C-9／第二隻腳：要有大盤戰場
    if re.search(
        r"假跌破|劇本一|有效穿刺|1\s*[-–]?\s*4\s*重疊|9\s*波\s*擴延|"
        r"C\s*[-–]\s*[789]|第二隻腳|第二支腳|"
        r"1\s*[-–]?\s*2\s*轉\s*1\s*[-–]?\s*3\s*[-–]?\s*1",
        s,
    ) and _INDEXISH.search(s):
        return True
    if re.search(r"(?:9865|10445|8498).{0,6}會破|會破.{0,6}(?:9865|10445|8498)", s):
        return True
    return bool(
        _INDEXISH.search(s)
        and re.search(r"(?<![0-9])(?:3[5-9]|4[0-9])\d{3}(?:\.\d+)?(?![0-9])", s)
    )


def _latest_biaoke_index_snip(
    db_path: str,
    cap_ymd: str,
    *,
    now: Optional[datetime] = None,
    with_id: bool = False,
):
    """≤cap 日、且時間 ≤ 查詢當下的最新大盤題旨（主文＋同串他回，依時間序）。

    不准只掃最新 40 列：討論串自回一多會把主文擠出窗，誤抓短回當題旨。
    做法：先在主文池（kind=post／無 :c）挑最新長篇位階主文；再依時間序併入
    同串他回的點位／改口句（例如 9865會破、35000-38000）；同日前一篇劇本主文
    若寫了 8498／35000~38000 而最新主文沒寫，也併入（後文改口壓前文）。
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

    def _ok_clock(d: str, t: str) -> bool:
        if d == today_dash and t and t > hm:
            return False
        return True

    def _fetch_mains(conn: sqlite3.Connection):
        # 正式庫有 kind；測試／舊庫可能沒有 → 退回只認無 :c 的主文 id
        try:
            return conn.execute(
                "SELECT id, date, time, text FROM biaoke_posts "
                "WHERE date>=? AND date<=? "
                "AND (kind='post' OR (IFNULL(kind,'') IN ('','post') AND id NOT LIKE '%:%')) "
                "ORDER BY date DESC, time DESC LIMIT 30",
                (since, cap_dash),
            ).fetchall()
        except sqlite3.OperationalError:
            return conn.execute(
                "SELECT id, date, time, text FROM biaoke_posts "
                "WHERE date>=? AND date<=? AND id NOT LIKE '%:%' "
                "ORDER BY date DESC, time DESC LIMIT 30",
                (since, cap_dash),
            ).fetchall()

    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            mains = _fetch_mains(conn)
        finally:
            conn.close()
    except Exception:
        return empty

    best_blob = ""
    best_pid = ""
    best_key = (-1, "", "")
    best_date = ""
    best_time = ""
    for pid, date_s, time_s, text in mains or ():
        d = str(date_s or "").strip()
        t = str(time_s or "").strip()
        blob = str(text or "")
        sid = str(pid or "")
        # 無 kind 欄時仍擋樓下 id（含 :c）
        if ":c" in sid or (":" in sid and sid.split(":", 1)[0].isdigit()):
            # id 形如 187:xxx 的回文／附篇；純主文數字 id 放行
            if ":c" in sid:
                continue
        if not blob or not _ok_clock(d, t):
            continue
        if not (_INDEXISH.search(blob) or looks_like_level_now(blob)):
            continue
        score = _biaoke_level_snip_score(blob, is_main=True)
        key = (score, d, t)
        if key > best_key:
            best_key = key
            best_blob = blob
            best_pid = sid
            best_date = d
            best_time = t
    if not best_blob or not best_pid:
        return empty

    aid = best_pid.split(":", 1)[0]
    extras: List[str] = []
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            # 同日前一篇位階主文（劇本一 8498／35000~38000 常寫在較早那篇）
            try:
                prior = conn.execute(
                    "SELECT id, date, time, text FROM biaoke_posts "
                    "WHERE date=? AND id!=? "
                    "AND (kind='post' OR (IFNULL(kind,'') IN ('','post') AND id NOT LIKE '%:%')) "
                    "ORDER BY time DESC LIMIT 4",
                    (best_date, best_pid),
                ).fetchall()
            except sqlite3.OperationalError:
                prior = conn.execute(
                    "SELECT id, date, time, text FROM biaoke_posts "
                    "WHERE date=? AND id!=? AND id NOT LIKE '%:%' "
                    "ORDER BY time DESC LIMIT 4",
                    (best_date, best_pid),
                ).fetchall()
            prior_bits: List[str] = []
            for pid, date_s, time_s, text in prior or ():
                d = str(date_s or "").strip()
                t = str(time_s or "").strip()
                blob = str(text or "")
                if not blob or not _ok_clock(d, t):
                    continue
                if t >= best_time:
                    continue
                flat = re.sub(r"\s+", " ", blob).strip()
                # 只抽劇本／8498／35000~38000／C9低點區句，不准整篇塞進來擠掉凌晨改口
                for m in re.finditer(
                    r"[^。｜]{0,40}(?:劇本一|第一套劇本)[^。｜]{0,120}"
                    r"|[^。｜]{0,40}8498[^。｜]{0,40}"
                    r"|[^。｜]{0,40}35000\s*[-~～到至]\s*38000[^。｜]{0,40}"
                    r"|[^。｜]{0,40}35500\s*[-~～到至]\s*37300[^。｜]{0,40}"
                    r"|[^。｜]{0,40}37000\s*[-~～到至\-]\s*37500[^。｜]{0,40}"
                    r"|[^。｜]{0,40}看不到\s*37000\s*以下[^。｜]{0,40}"
                    r"|[^。｜]{0,60}9\s*波\s*擴延[^。｜]{0,80}"
                    r"|[^。｜]{0,40}C\s*[-–]\s*7[^。｜]{0,48}C\s*[-–]\s*8[^。｜]{0,40}"
                    r"|[^。｜]{0,48}1\s*[-–]?\s*2\s*轉\s*1\s*[-–]?\s*3\s*[-–]?\s*1[^。｜]{0,40}"
                    r"|[^。｜]{0,40}2\s*/\s*25\s*高點?\s*8498[^。｜]{0,40}"
                    r"|[^。｜\n]{0,48}41760[^。｜\n]{0,72}"
                    r"|[^。｜\n]{0,56}C3-5.{0,48}1\s*[-–]?\s*4\s*重疊[^。｜\n]{0,96}"
                    r"|[^。｜\n]{0,48}確認.{0,16}(?:上)?週五.{0,20}最低[^。｜\n]{0,48}"
                    r"|[^。｜\n]{0,40}再測.{0,16}星期五低點[^。｜\n]{0,72}",
                    flat,
                ):
                    bit = m.group(0).strip(" ，,")
                    if bit and bit not in prior_bits:
                        prior_bits.append(bit)
                if prior_bits:
                    extras.extend(prior_bits[:3])
                    break
            # 同串他回：依時間序併點位／改口（牆鐘之後的不准吃）
            try:
                reps = conn.execute(
                    "SELECT id, date, time, text FROM biaoke_posts "
                    "WHERE id LIKE ? AND IFNULL(kind,'reply')='reply' "
                    "ORDER BY date ASC, time ASC, id ASC",
                    (f"{aid}:%",),
                ).fetchall()
            except sqlite3.OperationalError:
                reps = conn.execute(
                    "SELECT id, date, time, text FROM biaoke_posts "
                    "WHERE id LIKE ? "
                    "ORDER BY date ASC, time ASC, id ASC",
                    (f"{aid}:%",),
                ).fetchall()
        finally:
            conn.close()
    except Exception:
        reps = []
    reply_bits: List[str] = []
    seen_reply: set = set()
    for pid, date_s, time_s, text in reps or ():
        d = str(date_s or "").strip()
        t = str(time_s or "").strip()
        blob = str(text or "")
        if not blob or not _ok_clock(d, t):
            continue
        # 主文當日：只收主文時間之後；跨日回文全收（仍卡牆鐘）
        if d == best_date and t and best_time and t < best_time:
            continue
        if not _reply_level_delta(blob):
            continue
        flat = re.sub(r"\s+", " ", blob).strip()
        # 去重：同句重貼／句首多一個點，不准堆兩次
        key = re.sub(r"^[\.\s]+", "", flat)
        key = re.sub(r"\s+", "", key)[:96]
        if key in seen_reply:
            continue
        seen_reply.add(key)
        reply_bits.append(flat)
    # 主文 → 同日劇本句 → 同串他回（時間序；後句改口壓前）。回文優先保留。
    main_flat = re.sub(r"\s+", " ", best_blob).strip()
    parts = [main_flat] + extras + reply_bits
    joined = "｜".join(p for p in parts if p)
    if len(joined) > 1600:
        # 裁主文中段，保住頭尾關鍵＋全部回文改口
        keep_tail = "｜".join(extras + reply_bits)
        budget = max(400, 1600 - len(keep_tail) - 1)
        joined = main_flat[:budget].rstrip() + ("｜" + keep_tail if keep_tail else "")
        joined = joined[:1600]
    snip = joined
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


# 白底戳 axes 佔位（左上）：尖點／左欄價標／青帶註不准坐進去
# 字級17＋長句戳很寬很高 → 禁區要比視覺框再放大一截
_TEACH_STAMP_AX_X_MAX = 0.56
_TEACH_STAMP_AX_Y_MIN = 0.62


def _reserve_teach_stamp_zone(ax: Any) -> None:
    """白底戳左上佔位 → data 禁區；尖點／智慧標先避開再畫。"""
    if ax is None:
        return
    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
    except Exception:
        return
    xspan = max(float(x1) - float(x0), 1.0)
    yspan = max(float(y1) - float(y0), 1.0)
    _reserve_avoid_zone(
        ax,
        float(x0) - 0.75,
        float(y0) + yspan * float(_TEACH_STAMP_AX_Y_MIN),
        float(x0) + xspan * float(_TEACH_STAMP_AX_X_MAX),
        float(y1) + yspan * 0.08,
    )


def _clear_teach_stamp_pin_xy(
    ax: Any,
    x: float,
    y: float,
    *,
    ha: str = "center",
) -> Tuple[float, float, str]:
    """尖點標若落左上白底戳佔位，水平右移出戳；仍偏高再略降到戳下緣。"""
    if ax is None:
        return float(x), float(y), str(ha)
    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
    except Exception:
        return float(x), float(y), str(ha)
    xspan = max(float(x1) - float(x0), 1e-9)
    yspan = max(float(y1) - float(y0), 1e-9)
    ax_xf = (float(x) - float(x0)) / xspan
    ax_yf = (float(y) - float(y0)) / yspan
    xx, yy, h = float(x), float(y), str(ha or "center")
    if ax_xf < float(_TEACH_STAMP_AX_X_MAX) and ax_yf > float(_TEACH_STAMP_AX_Y_MIN):
        xx = float(x0) + xspan * (float(_TEACH_STAMP_AX_X_MAX) + 0.04)
        h = "left"
        if ax_yf > 0.88:
            yy = float(y0) + yspan * float(_TEACH_STAMP_AX_Y_MIN)
    return float(xx), float(yy), h


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

    def _escape_zone_x(x: float, y: float, min_dx: float) -> Optional[float]:
        """左上戳等橫向禁區：先水平逃出右緣，再交給垂直微挪。"""
        for zx0, zy0, zx1, zy1 in zones:
            if (zx0 - min_dx) <= x <= (zx1 + min_dx) and zy0 <= y <= zy1:
                return float(zx1) + float(min_dx) + 0.2
        return None

    items.sort(key=lambda d: (-int(d.get("pri") or 0), -float(d.get("y") or 0)))
    placed: List[Dict[str, Any]] = []
    used: List[Tuple[float, float]] = []  # (x, y)
    for it in items:
        x = float(it.get("x") or 0)
        y = float(it.get("y") or 0)
        min_dx = float(it.get("min_dx") or 1.2)
        nudge_up = (it.get("nudge") or "up") == "up"
        for _ in range(12):
            hit = any(
                abs(x - ux) < min_dx and abs(y - uy) < gap * 0.92 for ux, uy in used
            ) or _in_zone(x, y, min_dx)
            if not hit:
                break
            esc = _escape_zone_x(x, y, min_dx)
            if esc is not None:
                x = float(esc)
                continue
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
    # 9波擴延／35500~37300：庫內真文／snap 可壓舊 C3-x；口頭只補「尚無題旨」空窗
    # 更早 as_of／已有橫台・C3-3・C3-5 真文時，不准 oral-c9-band 蓋掉
    # 後文止跌／週五低確認不准被較早 C9／雙軌備線整段蓋掉
    try:
        stop_now = _text_has_stop_low_confirm(snip) or _text_has_stop_low_confirm(
            post_snip or ""
        )
        if cap >= _C9_ORAL_AS_OF:
            _ensure_c9_oral_thesis_snap(db_path, as_of=cap)
        c9_snip = _find_c9_extension_snip(db_path, cap, include_oral=False)
        if (
            not c9_snip
            and not str(snip or "").strip()
            and cap >= _C9_ORAL_AS_OF
        ):
            c9_snip = _C9_ORAL_SNIP
        if c9_snip and _text_has_c9_extension(c9_snip) and not stop_now:
            if not _text_has_c9_extension(snip):
                if not str(snip or "").strip():
                    # 空題旨才用口頭／真 C9 填上
                    snip = c9_snip
                    post_id = post_id or "oral-c9-band"
                else:
                    # 已有真文：只准「非口頭」C9 改口壓舊（仍卡止跌後文）
                    snip = c9_snip
            elif cap >= _C9_ORAL_AS_OF:
                snip = f"{c9_snip} {snip}"
    except Exception:
        logger.debug("C9 題旨覆寫略過", exc_info=True)
    # 後文改口：37000~37500／第二隻腳；但若已有更新的「五波跌完走B-b／九波雙軌」
    # 或更後「止跌／週五低確認」真文，不准用較早第二隻腳整段蓋掉。
    try:
        stop_now = _text_has_stop_low_confirm(snip) or _text_has_stop_low_confirm(
            post_snip or ""
        )
        has_bb_now = _text_has_bb_dual_path(snip) or _text_has_bb_dual_path(
            post_snip or ""
        )
        if cap >= _FOOT2_ORAL_AS_OF:
            _ensure_foot2_oral_thesis_snap(db_path, as_of=cap)
        foot2_real = _find_foot2_snip(db_path, cap, include_oral=False)
        if stop_now:
            # 止跌確認後文已定主線：不准再併舊第二隻腳／37000 帶蓋最新盯價
            pass
        elif has_bb_now:
            # 雙軌後文已定主線：只補缺的 37000~37500 參考帶，不准整段置換題旨
            if foot2_real and _text_has_foot2_revision(foot2_real):
                if not re.search(r"37000\s*[-~～到至\-]\s*37500|37000.{0,8}37500", snip):
                    snip = f"{snip}｜低點區37000~37500（前改口仍參考）".strip()
        elif foot2_real and _text_has_foot2_revision(foot2_real):
            if not _text_has_foot2_revision(snip):
                snip = foot2_real
                post_id = post_id or _FOOT2_ORAL_POST_ID
            elif cap >= _FOOT2_ORAL_AS_OF:
                snip = f"{foot2_real} {snip}"
        elif cap >= _FOOT2_ORAL_AS_OF and not _text_has_foot2_revision(snip):
            # 後文改口壓前文：即使庫內最新是 C3-5 真文，仍併入 37000~37500／第二隻腳
            snip = f"{_FOOT2_ORAL_SNIP} {snip}".strip()
            post_id = post_id or _FOOT2_ORAL_POST_ID
    except Exception:
        logger.debug("第二隻腳題旨覆寫略過", exc_info=True)
    # 後文改口：夜盤過 C3 下降壓 → 週五低不再假跌破（壓「一定再測／假跌破」）
    try:
        if cap >= _PRESSURE_BREAK_ORAL_AS_OF:
            _ensure_pressure_break_oral_thesis_snap(db_path, as_of=cap)
        pb_real = _find_pressure_break_snip(db_path, cap, include_oral=False)
        pb_any = pb_real or _find_pressure_break_snip(db_path, cap, include_oral=True)
        if (
            not pb_any
            and cap >= _PRESSURE_BREAK_ORAL_AS_OF
            and not _text_has_c3_pressure_break(snip)
            and not _text_has_c3_pressure_break(post_snip or "")
        ):
            pb_any = _PRESSURE_BREAK_ORAL_SNIP
        if pb_any and _text_has_c3_pressure_break(pb_any):
            if not _text_has_c3_pressure_break(snip):
                # 併在前：後文改口壓前文止跌「再測／假跌破」句
                snip = f"{pb_any} {snip}".strip()
                post_id = post_id or _PRESSURE_BREAK_ORAL_POST_ID
            elif pb_real and cap >= _PRESSURE_BREAK_ORAL_AS_OF:
                snip = f"{pb_real} {snip}".strip()
    except Exception:
        logger.debug("下降壓改口題旨覆寫略過", exc_info=True)
    # 後文：至少回測 41500／絕對不破週五低（11/10 口頭；壓無報價下降壓盯法）
    try:
        if cap >= _RETEST_41500_ORAL_AS_OF:
            _ensure_retest_41500_oral_thesis_snap(db_path, as_of=cap)
        if cap >= _RETEST_41500_ORAL_AS_OF and not _text_has_retest_41500(snip):
            snip = f"{_RETEST_41500_ORAL_SNIP} {snip}".strip()
            post_id = post_id or _RETEST_41500_ORAL_POST_ID
        elif _text_has_retest_41500(snip) and "41500" not in snip:
            snip = f"{_RETEST_41500_ORAL_SNIP} {snip}".strip()
    except Exception:
        logger.debug("41500 回測口頭題旨覆寫略過", exc_info=True)
    # 後文：低點帶 41900～42700（11/12；壓單點 41500 當令終點）
    try:
        if cap >= _LOW_BAND_419_427_ORAL_AS_OF:
            _ensure_low_band_419_427_oral_thesis_snap(db_path, as_of=cap)
        if cap >= _LOW_BAND_419_427_ORAL_AS_OF and not _text_has_low_band_419_427(
            snip
        ):
            snip = f"{_LOW_BAND_419_427_ORAL_SNIP} {snip}".strip()
            post_id = post_id or _LOW_BAND_419_427_ORAL_POST_ID
    except Exception:
        logger.debug("41900～42700 低點帶口頭題旨覆寫略過", exc_info=True)
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
    has_35 = bool(
        re.search(r"C3-5|(?:今天)?走\s*3-5|(?<![0-9])3-5(?![0-9])", snip)
    )
    c35_done = bool(
        re.search(r"C3-5\s*完成|第二組下跌脈動.*(?:完成|落底)", snip)
    )
    # 後文改口：37000~37500／第二隻腳（壓 C9 低點區 35500~37300）
    has_foot2 = _text_has_foot2_revision(snip)
    has_foot2_band = bool(
        re.search(r"37000\s*[-~～到至\-]\s*37500|37000.{0,8}37500", snip)
    )
    # 11/9 夜下降壓改口＞止跌再測假跌破＞11/8 雙軌＞第二隻腳＞C9（後文壓前文）
    has_pressure_break = _text_has_c3_pressure_break(snip)
    has_stop_confirm = _text_has_stop_low_confirm(snip)
    has_bb_dual = _text_has_bb_dual_path(snip)
    # 9波擴延 C-7轉C-8→C-9＋低點區 35500~37300（後文改口壓舊 C3-5）
    has_c9_band = bool(
        re.search(r"35500\s*[-~～到至]\s*37300|35500.{0,8}37300", snip)
    )
    has_9ext = bool(re.search(r"9\s*波\s*擴延", snip))
    has_c78 = bool(
        re.search(
            r"C\s*[-–]\s*7.{0,24}(?:轉|->|→|走完).{0,16}C\s*[-–]\s*8|"
            r"C\s*[-–]\s*7.{0,12}C\s*[-–]\s*8|"
            r"七走完|準備往\s*八|往八走|C-7轉C-8",
            snip,
        )
    )
    has_c9 = bool(re.search(r"C\s*[-–]\s*9", snip))
    has_41760 = bool(re.search(r"41760", snip))
    has_41500 = _text_has_retest_41500(snip) or bool(re.search(r"41500", snip))
    has_low_band = _text_has_low_band_419_427(snip)
    # 夜盤第二組落底（C3-5完成）優先於舊 C3-3 題旨；後文改口壓前文
    if has_pressure_break:
        # 他最新改口：夜盤過 C3 下降壓；上週五低不再假跌破；拉回回測下降壓（非買訊）
        # 斜線回測 ≠ 水平台指壓41760；11/12 低點帶壓 11/10 單點41500
        thesis = "大A→大B→大C｜夜盤過C3下降壓・週五低不再假跌破（預估）"
        wait_bits = [
            "拉回回測下降壓力線（口述斜線・圖上紫帶C3・粉虛下降壓示意／無報價）",
            "清洗籌碼",
            "資金可5~6成",
        ]
        if has_low_band:
            _rb = _retest_avg_min_from_text(snip) or {
                "min": _LOW_BAND_419_427_LO,
                "avg": _LOW_BAND_419_427_MID,
                "hi": _LOW_BAND_419_427_HI,
            }
            wait_bits = [
                f"回測平均{_px(_rb['avg'])}",
                f"回測最低{_px(_rb['min'])}",
                "路徑先到43000下",
                "絕對不破週五低37837",
                "拉回回測下降壓力線（口述斜線・無報價）",
                "清洗籌碼",
            ]
        elif has_41500:
            wait_bits = [
                f"回測平均{_px(41500)}",
                f"回測最低{_px(41500)}",
                "絕對不破週五低37837",
                "拉回回測下降壓力線（口述斜線・無報價）",
                "清洗籌碼",
            ]
        if has_41760:
            # 未到 11/10「至少回測41500」口頭前，不准在等待句寫 41500（會誤觸絕對不破文案）
            if has_low_band:
                wait_bits.insert(0, "水平台指壓41760（≠回測帶／≠口述下降壓）")
            elif has_41500:
                wait_bits.insert(0, "水平台指壓41760（≠41500回測／≠口述下降壓）")
            else:
                wait_bits.insert(0, "水平台指壓41760（≠口述下降壓）")
        wait_bits.append("非買訊")
        wait = "；".join(wait_bits)
    elif has_stop_confirm:
        # 他先前：C3-5＋1 4重疊／確認週五低＝最低；再測・假跌破（說明用・非買訊）
        # 若已有下降壓改口，上面分支會蓋掉這段「再測／假跌破」
        thesis = "大A→大B→大C｜C3-5＋1 4重疊・確認上週五低＝最低（預估）"
        wait_bits = [
            "一定再測週五低",
            "破＝假跌破觀察",
        ]
        if has_41760:
            wait_bits.insert(0, "台指壓41760")
        wait_bits.append("非買訊")
        wait = "；".join(wait_bits)
    elif has_bb_dual:
        # 主線五波跌完→B-b；備線九波擴延。未定案前雙軌並陳（說明用・非買訊）
        thesis = "大A→大B→大C｜主線五波跌完走B-b・備線九波擴延（預估）"
        wait = (
            "主：假跌破37837觀察；備：35579→31705；"
            "未定案前口述對照與三窗同口；非買訊"
        )
    elif has_foot2 or has_foot2_band:
        # 口述改口：夜盤跌完居多；低點 37000~37500；等第二隻腳（非買訊）
        thesis = "大A→大B→大C｜夜盤跌完居多・等第二隻腳（預估）"
        wait = (
            "低點區37000~37500；看不到37000以下；"
            "反彈後拉回1-2轉1-3-1＝第二隻腳；非買訊"
        )
    elif has_9ext or (has_c78 and (has_c9 or has_c9_band)) or (
        has_c9_band and (has_c78 or has_c9)
    ):
        # 口述改口：目前最有可能 C-7轉C-8，最後 C-9；低點區 35500~37300
        thesis = "大A→大B→大C｜9波擴延・C-7轉C-8→C-9（預估）"
        wait = (
            "低點區35500~37300；C-9跌完＝這段下殺完；C走完≠新五波升"
            if has_c9_band
            else "C-7轉C-8→C-9；C-9跌完＝這段下殺完；C走完≠新五波升"
        )
    elif c35_done or (
        has_35 and re.search(r"落底確認|目前開始反彈|反彈能否穿刺", snip)
    ):
        thesis = "大A→大B→大C｜C內＝C3-5完成（第二組落底・預估）"
        wait = "反彈觀察穿刺45546；破不了→第三組；轉震盪看46292；C走完≠新五波升"
    elif "C3-3-1" in snip and "C3-3-2" in snip:
        thesis = "大A→大B→大C｜C內＝C3-3（1→2・預估）"
        wait = "下一測他點過錨；C走完≠新五波升；鐵律不符→重修"
    elif has_333 and has_334:
        thesis = "大A→大B→大C｜C內＝C3-3（3→4・預估）"
        wait = "第二組主跌未完；周一破底／勿抄底；C走完≠新五波升"
    elif "C3-3" in snip or has_333 or has_334:
        thesis = "大A→大B→大C｜C內＝C3-3主跌（預估）"
        wait = "隨時檢視細微；C走完≠新五波升；穿刺→重修"
    elif has_35:
        thesis = "大A→大B→大C｜C內＝C3-5（預估）"
        wait = "他認走3-5；1 4／假跌破隨時檢視；C走完≠新五波升"
    elif "橫台" in snip or "中繼" in snip:
        thesis = "大A→大B→大C｜C內橫台中繼（預估）"
        wait = "中繼後原方向；C走完≠新五波升；不符就改"
    elif "主跌" in snip:
        thesis = "大A→大B→大C｜C內主跌（預估）"
        wait = "細微波完整＋降軌；C走完≠新五波升；再重訂位階"
    if morph and "楔形" in morph and not (has_stop_confirm or has_pressure_break):
        wait = f"{wait}｜型態：{morph}"
    elif morph and not (has_stop_confirm or has_pressure_break):
        wait = f"{wait}｜型態觀察：{morph}"
    if _REVISE_MARK.search(snip):
        if has_pressure_break or has_stop_confirm or has_bb_dual:
            # 下降壓改口／止跌確認／雙軌題旨已帶主線，不准改口警語整段蓋掉
            wait = f"{wait}｜隨時檢視" + (
                f"｜{morph}"
                if morph and not (has_stop_confirm or has_pressure_break)
                else ""
            )
        else:
            wait = "他已示警重修／動態修正・圖位＝當下預估" + (
                f"｜{morph}" if morph else ""
            )
    return {
        "thesis": thesis,
        "wait_struct": wait[:360],
        "morph_note": morph[:180],
        "fib_note": "黃金切割反彈壓 0.382／0.618／0.75（他10/27台指日盤・可修訂）",
        "snippet": snip[:320],
        "snippet_full": snip[:1600],
        "as_of": str((row["as_of"] if row else "") or cap),
        "post_id": post_id,
        "chart_as_of": cap,
    }


def _sparse_slot_id(dt: datetime, *, force: bool = False) -> Optional[str]:
    """稀疏槽 id；不在窗＝None。force 一天一槽覆寫（不准每分堆 PNG 吃永久碟）。"""
    ymd = dt.strftime("%Y%m%d")
    if force:
        # 話筒重開／補渲共用 force-{ymd}，遠近超近覆寫同檔；舊 force-{ymd}-{HHMM} 由 disk_guard 清
        return f"force-{ymd}"
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


def _twii60_vol_proxy_map(db_path: str) -> Dict[str, float]:
    """加權指數 Yahoo 分量永遠 0；同路個股／ETF 有量。

    用 0050 日盤 60 分對齊 ts 當量能代理（張；Yahoo 已轉張）。
    不准發明數字：抓不到就不寫。
    """
    out: Dict[str, float] = {}
    if not db_path:
        return out
    try:
        from kline_hop import fetch_yahoo_minutes, load_minute_bars

        try:
            fetch_yahoo_minutes("0050", "60", db_path)
        except Exception:
            pass
        raw = load_minute_bars("0050", "60", db_path) or []
    except Exception:
        return out
    for b in raw:
        ts = str(b.get("t") or "")
        if len(ts) < 12:
            continue
        try:
            v = float(b.get("v") or 0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        out[ts] = v
    return out


def _attach_twii60_volume_proxy(
    rows: Sequence[Dict[str, Any]], db_path: str
) -> List[Dict[str, Any]]:
    """TWII 60 分列量＝0 時，用 0050 同 ts 真量貼上並標 vol_src。"""
    if not rows:
        return []
    need = any(float(r.get("volume") or 0) <= 0 for r in rows)
    if not need:
        return [dict(r) for r in rows]
    proxy = _twii60_vol_proxy_map(db_path)
    if not proxy:
        return [dict(r) for r in rows]
    out: List[Dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        try:
            v = float(row.get("volume") or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            out.append(row)
            continue
        ts = str(row.get("ts") or "")
        pv = float(proxy.get(ts) or 0)
        if pv > 0:
            row["volume"] = pv
            row["vol_src"] = "0050"
        out.append(row)
    return out


def _load_twii60_day_rows(
    db_path: str,
    *,
    since_ymd: str = "20261006",
    until_ymd: str = "",
) -> List[Dict[str, Any]]:
    """加權日盤 60 分：自 since（含）到 until 日盤收（預設庫內最新）。

    只收 09:00–13:30 日盤柱；夜盤／盤後不進超近 9 波窗。價＝官方 minute_bars。
    量：^TWII 無成交量 → 同 ts 貼 0050 真量（vol_src=0050）；抓不到不假填。
    """
    try:
        from kline_hop import load_minute_bars

        raw = load_minute_bars("TWII", "60", db_path) or []
    except Exception:
        return []
    since = _ymd(since_ymd) or "20261006"
    until = _ymd(until_ymd)
    out: List[Dict[str, Any]] = []
    for b in raw:
        ts = str(b.get("t") or "")
        if len(ts) < 12:
            continue
        ymd = ts[:8]
        if ymd < since:
            continue
        if until and ymd > until:
            continue
        try:
            hm = int(ts[8:12])
        except ValueError:
            continue
        # 台股日盤 60 分整點（含 13:30 收）；拒 1 分髒柱混進 interval=60
        if hm not in (900, 1000, 1100, 1200, 1300, 1330):
            continue
        try:
            out.append(
                {
                    "date": ymd,
                    "ts": ts,
                    "open": float(b.get("o") or 0),
                    "high": float(b.get("h") or 0),
                    "low": float(b.get("l") or 0),
                    "close": float(b.get("c") or 0),
                    "volume": float(b.get("v") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return _attach_twii60_volume_proxy(out, db_path)


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


def _yahoo_us_index_upsert(
    conn: sqlite3.Connection,
    *,
    sym: str,
    yid: str,
    range_: str,
    ua: Dict[str, str],
) -> int:
    """Yahoo 美股指數日K UPSERT；日期用美東，不准用台北日切錯欄。"""
    try:
        import requests
    except Exception:
        return 0
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
        f"?interval=1d&range={range_}"
    )
    try:
        resp = requests.get(url, timeout=12, headers=ua)
        if resp.status_code != 200:
            return 0
        block = ((resp.json() or {}).get("chart") or {}).get("result") or [None]
        block = block[0] or {}
        stamps = block.get("timestamp") or []
        q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    except Exception:
        logger.exception("補%s日K失敗", sym)
        return 0
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
            dt = datetime.fromtimestamp(int(ts), tz=ny)
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
            (d, sym, o, h, l, c, v, None, _now()),
        )
        written += 1
    if written:
        conn.commit()
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
    return written


def _ensure_us_index_daily(db_path: str) -> Dict[str, int]:
    """費半／納指日K：出圖前必刷新近窗，撐壓才對得上最新價（失敗不擋活畫）。

    符號：SOX／IXIC。TWII 官方柱不走這條。
    舊邏輯「近窗夠就整段跳過」會卡在過期收（例如費半停 11/3＝10600），已廢。
    """
    stats = {"SOX": 0, "IXIC": 0}
    if not db_path:
        return stats
    try:
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
            n_apr = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=? AND date<=?",
                (sym, "20260420", "20260510"),
            ).fetchone()[0]
            n_jul = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=? AND date<=?",
                (sym, "20260725", "20260802"),
            ).fetchone()[0]
            # 缺歷史錨 → 拉 1y；否則每次出圖仍拉 1mo 覆寫近窗（含當日未收）
            need_hist = int(n_apr or 0) < 3 or int(n_jul or 0) < 3
            range_ = "1y" if need_hist else "1mo"
            written = _yahoo_us_index_upsert(
                conn, sym=sym, yid=yid, range_=range_, ua=ua
            )
            if written <= 0 and need_hist:
                # 1y 失敗再試近窗，至少讓末日別空白
                written = _yahoo_us_index_upsert(
                    conn, sym=sym, yid=yid, range_="1mo", ua=ua
                )
            n_have = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol=? AND date>=?",
                (sym, "20260901"),
            ).fetchone()[0]
            stats[sym] = int(written or n_have or 0)
    finally:
        conn.close()
    # Yahoo 失敗時：費半還可從 minute_bars 日切（庫內已有 SOX 分K）
    if stats.get("SOX", 0) < 10:
        try:
            stats["SOX"] = int(_sox_daily_from_minutes(db_path) or 0)
        except Exception:
            logger.exception("SOX 分K日切略過")
    # 已收後對質末日收＝Yahoo regularMarketPrice（修盤中殘值卡黃框）
    for sym, yid in pairs:
        try:
            if _reconcile_us_index_last_close(db_path, sym=sym, yid=yid):
                stats[f"{sym}_reconciled"] = 1
        except Exception:
            logger.exception("對質%s末日略過", sym)
    # ^SOX 指數幾乎無官方量 → 另抓 SOXX ETF 量當費半量代理（標清楚）
    try:
        stats["SOXX"] = int(_ensure_soxx_volume_proxy(db_path) or 0)
    except Exception:
        logger.exception("SOXX 量代理略過")
        stats["SOXX"] = 0
    return stats


def _ensure_soxx_volume_proxy(db_path: str) -> int:
    """補 SOXX 日量：費半指數無官方量，教具大量撐壓用 SOXX 代理。

    每次出圖刷新近窗（不准「已有≥40列」整段跳過卡在過期日，例如停 10/30）。
    日期用美東，與 ^SOX 同曆。Yahoo 價若相對庫內跳太兇（拆分／錯欄）
    只更新量、保留舊 OHLC；新日仍寫量（價不可用時 close=0）。
    """
    if not db_path:
        return 0
    try:
        import requests
        from taiwan_market import ensure_index_daily_table
    except Exception:
        return 0
    ensure_index_daily_table(db_path)
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    # 近窗必刷；缺更長歷史才拉 6mo
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        n_have = int(
            conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol='SOXX' AND date>=? AND volume>0",
                ("20260701",),
            ).fetchone()[0]
            or 0
        )
    finally:
        conn.close()
    range_ = "6mo" if n_have < 40 else "1mo"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/SOXX?interval=1d&range={range_}"
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
    ny = ZoneInfo("America/New_York")
    written = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        prev_close: Optional[float] = None
        row_prev = conn.execute(
            "SELECT close FROM index_daily WHERE symbol='SOXX' AND close>0 "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if row_prev and row_prev[0]:
            prev_close = float(row_prev[0])
        for ts, op, hi, lo, cl, vol in zip(
            stamps,
            q.get("open") or [],
            q.get("high") or [],
            q.get("low") or [],
            q.get("close") or [],
            q.get("volume") or [],
        ):
            v = float(vol or 0)
            if v <= 0:
                continue
            try:
                dt = datetime.fromtimestamp(int(ts), tz=ny)
            except (TypeError, ValueError, OSError):
                continue
            d = dt.strftime("%Y%m%d")
            # 近窗刷新：已落後末日之後的日必寫；歷史列價跳兇只動量
            c = float(cl) if cl is not None else 0.0
            o = float(op) if op is not None else c
            if o <= 0 and c <= 0:
                # 無價仍可留量（對齊費半同日）
                o = c = 0.0
            h = float(hi if hi is not None else max(o, c))
            l = float(lo if lo is not None else (min(o, c) if o and c else 0.0))
            existing = conn.execute(
                "SELECT close, volume FROM index_daily WHERE date=? AND symbol='SOXX'",
                (d,),
            ).fetchone()
            price_ok = True
            ref = None
            if existing and float(existing[0] or 0) > 0 and c > 0:
                ref = float(existing[0])
            elif prev_close and prev_close > 0 and c > 0:
                ref = float(prev_close)
            if ref and c > 0 and abs(c / ref - 1.0) > 0.35:
                price_ok = False
            if existing:
                if price_ok and c > 0 and o > 0:
                    conn.execute(
                        """
                        UPDATE index_daily SET open=?, high=?, low=?, close=?,
                            volume=?, updated_at=?
                        WHERE date=? AND symbol='SOXX'
                        """,
                        (o, h, l, c, v, _now(), d),
                    )
                else:
                    # 價不可信：只動量，撐壓日才對得上爆量
                    conn.execute(
                        """
                        UPDATE index_daily SET volume=?, updated_at=?
                        WHERE date=? AND symbol='SOXX'
                        """,
                        (v, _now(), d),
                    )
            else:
                if not price_ok:
                    o = h = l = c = 0.0
                conn.execute(
                    """
                    INSERT INTO index_daily(
                        date, symbol, open, high, low, close, volume,
                        pct_change, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (d, "SOXX", o, h, l, c, v, None, _now()),
                )
            written += 1
            if c > 0 and price_ok:
                prev_close = c
        conn.commit()
    finally:
        conn.close()
    # 回傳近窗有量列數（出圖 stats／對質用）
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        n_out = int(
            conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE symbol='SOXX' AND date>=? AND volume>0",
                ("20260901",),
            ).fetchone()[0]
            or 0
        )
        return n_out if n_out else written
    finally:
        conn.close()


def _sox_daily_from_minutes(db_path: str) -> int:
    """minute_bars SOX → index_daily 日切備援。

    美東交易日切（不准用台北日曆 substr 把盤中切成假收）。
    已有 Yahoo／庫內柱不准覆寫（避免 9185 這類未收盤分K蓋掉官方 9011）。
    """
    ny = ZoneInfo("America/New_York")
    conn = sqlite3.connect(db_path, timeout=30.0)
    n = 0
    try:
        rows = conn.execute(
            "SELECT ts, o, h, l, c, v FROM minute_bars "
            "WHERE stock_id='SOX' AND ts>='202608010000' ORDER BY ts"
        ).fetchall()
        by_day: Dict[str, List[Tuple[Any, ...]]] = {}
        for ts, o, h, l, c, v in rows:
            ts_s = str(ts or "")
            if len(ts_s) < 12:
                continue
            try:
                # minute_bars SOX ts＝台北牆鐘 YYYYMMDDHHMM
                dt_tp = datetime.strptime(ts_s[:12], "%Y%m%d%H%M").replace(
                    tzinfo=TAIPEI
                )
                d = dt_tp.astimezone(ny).strftime("%Y%m%d")
            except (TypeError, ValueError, OSError):
                continue
            by_day.setdefault(d, []).append((o, h, l, c, v))
        for d, bars in sorted(by_day.items()):
            exist = conn.execute(
                "SELECT close FROM index_daily WHERE date=? AND symbol='SOX'",
                (d,),
            ).fetchone()
            if exist and float(exist[0] or 0) > 0:
                continue  # 已有官方／先前柱，分K不准蓋
            o0 = h0 = l0 = c0 = None
            v_sum = 0.0
            for o, h, l, c, v in bars:
                try:
                    oo, hh, ll, cc = float(o), float(h), float(l), float(c)
                except (TypeError, ValueError):
                    continue
                if oo <= 0 or cc <= 0:
                    continue
                if o0 is None:
                    o0 = oo
                h0 = hh if h0 is None else max(h0, hh)
                l0 = ll if l0 is None else min(l0, ll)
                c0 = cc
                v_sum += float(v or 0)
            if o0 is None or c0 is None or h0 is None or l0 is None:
                continue
            conn.execute(
                """
                INSERT INTO index_daily(
                    date, symbol, open, high, low, close, volume, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(date, symbol) DO NOTHING
                """,
                (d, "SOX", float(o0), float(h0), float(l0), float(c0),
                 float(v_sum), _now()),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _fetch_yahoo_index_near_bars(yid: str = "^SOX") -> List[Dict[str, Any]]:
    """Yahoo 近窗日K列（美東日）。非現金盤中：末日收用 regularMarketPrice 覆寫。"""
    yid_s = str(yid or "").strip() or "^SOX"
    try:
        import requests
        from us_overnight import us_tape_phase
    except Exception:
        return []
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yid_s}"
        f"?interval=1d&range=10d"
    )
    try:
        resp = requests.get(url, timeout=12, headers=ua)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return []
        block = ((resp.json() or {}).get("chart") or {}).get("result") or [None]
        block = block[0] or {}
        meta = block.get("meta") or {}
        stamps = block.get("timestamp") or []
        q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    except Exception:
        logger.exception("Yahoo %s 近窗抓取失敗", yid_s)
        return []
    ny = ZoneInfo("America/New_York")
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    closes = q.get("close") or []
    vols = q.get("volume") or []
    rows: List[Dict[str, Any]] = []
    for i in range(len(stamps)):
        try:
            cl = closes[i] if i < len(closes) else None
            op = opens[i] if i < len(opens) else None
            if cl is None or op is None:
                continue
            d = datetime.fromtimestamp(int(stamps[i]), tz=ny).strftime("%Y%m%d")
            o = float(op)
            c = float(cl)
            h = float(highs[i]) if i < len(highs) and highs[i] is not None else max(o, c)
            lo = float(lows[i]) if i < len(lows) and lows[i] is not None else min(o, c)
            v = float(vols[i] or 0) if i < len(vols) else 0.0
        except (TypeError, ValueError, OSError, IndexError):
            continue
        rows.append(
            {
                "date": d,
                "open": o,
                "high": max(h, o, c),
                "low": min(x for x in (lo, o, c) if x and x > 0),
                "close": c,
                "volume": v,
            }
        )
    if not rows:
        return []
    phase = ""
    try:
        phase = str(us_tape_phase(datetime.now(TAIPEI)) or "")
    except Exception:
        phase = ""
    # 只在同日盤後（post）用 meta 修盤中殘值；週末 overnight 不准蓋官方收
    if phase == "post":
        try:
            px = float(meta.get("regularMarketPrice") or 0)
        except (TypeError, ValueError):
            px = 0.0
        ts = int(meta.get("regularMarketTime") or 0)
        if px > 0 and ts > 0:
            d_meta = datetime.fromtimestamp(ts, tz=ny).strftime("%Y%m%d")
            try:
                o = float(meta.get("regularMarketOpen") or rows[-1].get("open") or px)
                h = float(meta.get("regularMarketDayHigh") or rows[-1].get("high") or px)
                lo = float(meta.get("regularMarketDayLow") or rows[-1].get("low") or px)
            except (TypeError, ValueError):
                o = h = lo = px
            payload = {
                "date": d_meta,
                "open": o,
                "high": max(h, o, px),
                "low": min(x for x in (lo, o, px) if x and x > 0),
                "close": float(px),
                "volume": float(rows[-1].get("volume") or 0),
            }
            if _ymd(rows[-1].get("date")) == d_meta:
                rows[-1] = payload
            elif d_meta > _ymd(rows[-1].get("date")):
                rows.append(payload)
            else:
                for i in range(len(rows) - 1, -1, -1):
                    if _ymd(rows[i].get("date")) == d_meta:
                        rows[i] = payload
                        break
    return rows


def _fetch_yahoo_index_last_bar(yid: str = "^SOX") -> Optional[Dict[str, Any]]:
    """Yahoo 近窗最後一根有效日K（美東日）。"""
    rows = _fetch_yahoo_index_near_bars(yid)
    return dict(rows[-1]) if rows else None


def _inject_yahoo_us_last_into_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    yid: str = "^SOX",
    sym: str = "SOX",
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """出圖當下把 Yahoo 近窗日K併進列；庫失敗仍改記憶體——黃框不准卡舊收。"""
    by_d: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        d = _ymd((r or {}).get("date"))
        try:
            px = float((r or {}).get("close") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if len(d) == 8 and px > 0:
            by_d[d] = dict(r)
    fresh = _fetch_yahoo_index_near_bars(yid)
    if not fresh:
        out = [by_d[k] for k in sorted(by_d)]
        return out
    for bar in fresh:
        d = _ymd(bar.get("date"))
        try:
            px = float(bar.get("close") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if len(d) != 8 or px <= 0:
            continue
        by_d[d] = {
            "date": d,
            "open": float(bar.get("open") or px),
            "high": float(bar.get("high") or px),
            "low": float(bar.get("low") or px),
            "close": px,
            "volume": float(bar.get("volume") or 0),
        }
    out = [by_d[k] for k in sorted(by_d)]
    if db_path and fresh:
        try:
            from taiwan_market import ensure_index_daily_table

            ensure_index_daily_table(db_path)
            sym_u = str(sym or "SOX").upper()
            conn = sqlite3.connect(db_path, timeout=20.0)
            try:
                for bar in fresh:
                    d = _ymd(bar.get("date"))
                    px = float(bar.get("close") or 0)
                    if len(d) != 8 or px <= 0:
                        continue
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
                        (
                            d,
                            sym_u,
                            float(bar.get("open") or px),
                            float(bar.get("high") or px),
                            float(bar.get("low") or px),
                            px,
                            float(bar.get("volume") or 0),
                            None,
                            _now(),
                        ),
                    )
                rows2 = conn.execute(
                    "SELECT date, close FROM index_daily WHERE symbol=? ORDER BY date",
                    (sym_u,),
                ).fetchall()
                prev = None
                for d, c in rows2:
                    if prev and prev > 0 and c:
                        pct = (float(c) / float(prev) - 1.0) * 100.0
                        conn.execute(
                            "UPDATE index_daily SET pct_change=? WHERE date=? AND symbol=?",
                            (pct, d, sym_u),
                        )
                    prev = float(c) if c else prev
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("費半 Yahoo 近窗寫庫略過（記憶體列已更新）")
    return out


def _reconcile_us_index_last_close(db_path: str, *, sym: str, yid: str) -> bool:
    """美股已收後：庫內末日收若偏離 Yahoo regularMarketPrice，用 meta 全日欄覆寫。

    盤中未收不准當官方收；只在非 cash regular 相位修。避免遠窗黃框卡在 9185 這類盤中殘值。
    """
    if not db_path or not sym or not yid:
        return False
    try:
        import requests
        from us_overnight import us_tape_phase
    except Exception:
        return False
    now = datetime.now(TAIPEI)
    try:
        # 只在同日盤後修盤中殘值；週末 overnight 不准用 meta 蓋官方收
        if us_tape_phase(now) != "post":
            return False
    except Exception:
        return False
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
        f"?interval=1d&range=5d"
    )
    try:
        resp = requests.get(url, timeout=12, headers=ua)
        if resp.status_code != 200:
            return False
        block = ((resp.json() or {}).get("chart") or {}).get("result") or [None]
        block = block[0] or {}
        meta = block.get("meta") or {}
        q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    except Exception:
        logger.exception("對質%s末日收失敗", sym)
        return False
    try:
        px = float(meta.get("regularMarketPrice") or 0)
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        closes = q.get("close") or []
        try:
            px = float(closes[-1] or 0) if closes else 0.0
        except (TypeError, ValueError, IndexError):
            px = 0.0
    if px <= 0:
        return False
    ny = ZoneInfo("America/New_York")
    ts = int(meta.get("regularMarketTime") or 0)
    if not ts and (block.get("timestamp") or []):
        try:
            ts = int(block["timestamp"][-1])
        except (TypeError, ValueError, IndexError):
            ts = 0
    if not ts:
        return False
    d = datetime.fromtimestamp(ts, tz=ny).strftime("%Y%m%d")
    opens = q.get("open") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    try:
        o = float(opens[-1]) if opens else float(meta.get("regularMarketOpen") or px)
        h = float(
            meta.get("regularMarketDayHigh")
            or (highs[-1] if highs else px)
            or px
        )
        lo = float(
            meta.get("regularMarketDayLow")
            or (lows[-1] if lows else px)
            or px
        )
    except (TypeError, ValueError, IndexError):
        o = h = lo = px
    h = max(h, o, px)
    lo = min(x for x in (lo, o, px) if x and x > 0)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT close FROM index_daily WHERE date=? AND symbol=?",
            (d, sym),
        ).fetchone()
        old = float(row[0]) if row and row[0] is not None else 0.0
        if old > 0 and abs(old / px - 1.0) <= 0.008:
            return False
        conn.execute(
            """
            INSERT INTO index_daily(
                date, symbol, open, high, low, close, volume, pct_change, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date, symbol) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, updated_at=excluded.updated_at
            """,
            (d, sym, o, h, lo, px, 0.0, None, _now()),
        )
        # 重算該日 pct vs 前一交易日
        prev = conn.execute(
            "SELECT close FROM index_daily WHERE symbol=? AND date<? AND close>0 "
            "ORDER BY date DESC LIMIT 1",
            (sym, d),
        ).fetchone()
        if prev and float(prev[0] or 0) > 0:
            pct = (px / float(prev[0]) - 1.0) * 100.0
            conn.execute(
                "UPDATE index_daily SET pct_change=? WHERE date=? AND symbol=?",
                (pct, d, sym),
            )
        conn.commit()
        return True
    finally:
        conn.close()


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


def _load_tx_futures_daily(
    db_path: str,
    *,
    session: str = "night",
    since: str = "20260301",
) -> List[Dict[str, Any]]:
    """讀 futures_daily 大台 TX（night＝盤後／電子盤；regular＝日盤）。缺就空。"""
    sess = str(session or "night").strip().lower() or "night"
    if sess not in {"night", "regular"}:
        sess = "night"
    since_s = _ymd(since) or "20260301"
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, pct_change "
            "FROM futures_daily WHERE symbol='TX' AND session=? AND date>=? "
            "ORDER BY date",
            (sess, since_s),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            c = float(r[4] or 0)
        except (TypeError, ValueError):
            c = 0.0
        if c <= 0:
            continue
        out.append(
            {
                "date": str(r[0]),
                "open": float(r[1] or c),
                "high": float(r[2] or c),
                "low": float(r[3] or c),
                "close": c,
                "volume": float(r[5] or 0),
                "pct": float(r[6]) if r[6] is not None else None,
                "session": sess,
            }
        )
    return out


def _ensure_tx_night_for_teach(
    db_path: str, tw_bars: Sequence[Dict[str, Any]]
) -> int:
    """遠窗電子盤：加權軸上缺的 TX 夜盤日向期交所補齊（例 20260803–06 缺柱→假重複K）。

    只補缺日，失敗不擋出圖；回傳嘗試補的日數。
    另強制補 futures_night_date_cap（週末＝下一開市日標的週五夜）。
    """
    if not db_path or not tw_bars:
        return 0
    since = _ymd(tw_bars[0].get("date")) if tw_bars else ""
    have = {
        _ymd(r.get("date"))
        for r in _tx_night_rows_on_evening_axis(
            _load_tx_futures_daily(
                db_path, session="night", since=since or "20260301"
            )
        )
        if _ymd(r.get("date"))
    }
    missing = [
        _ymd(r.get("date"))
        for r in tw_bars
        if _ymd(r.get("date")) and _ymd(r.get("date")) not in have
    ]
    try:
        from trading_calendar import futures_night_date_cap

        cap = futures_night_date_cap()
        if len(cap) == 8 and cap not in missing:
            # cap 是官方晨／開市標；缺起日映射時仍要抓這列
            missing.append(cap)
    except Exception:
        pass
    missing = list(dict.fromkeys(missing))
    if not missing:
        return 0
    try:
        from taiwan_market import sync_futures_daily

        sync_futures_daily(db_path, dates=missing)
    except Exception:
        logger.exception("教具補台指夜盤缺日略過 n=%s", len(missing))
        return 0
    return len(missing)


def _ensure_paint_live_tx(
    pack: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """出圖當下抓台指電子盤即時 OHLC；遠窗台指電子盤欄＋紅框同口價。

    只在夜盤進行中才疊；週末／白天清掉殘 live，紅框走官方夜盤收。
    """
    dt = now or datetime.now(TAIPEI)
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    if not _tx_night_session_live(dt):
        if isinstance(pack, dict):
            pack.pop("live_tx", None)
        return None
    live: Optional[Dict[str, Any]] = None
    try:
        from biaoke_verify import fetch_tx_ohlc

        live = fetch_tx_ohlc(night=True, timeout=3.0)
    except Exception:
        live = None
    if not (isinstance(live, dict) and float(live.get("close") or 0) > 0):
        try:
            from market_ticker import fetch_tx_live

            q = fetch_tx_live(night=True, timeout=2.5)
        except Exception:
            q = None
        if isinstance(q, dict) and float(q.get("close") or 0) > 0:
            # 只有收：不准捏開＝高＝低＝收當「齊 OHLC」，否則會整根置換成一字線
            px = float(q["close"])
            live = {
                "date": "",
                "session": "night",
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": px,
                "pct_change": q.get("pct_change"),
                "update_time": q.get("update_time"),
                "source": "taifex_mis",
                "is_realtime": True,
            }
            try:
                r = float(q.get("ref") or q.get("prev_close") or 0)
            except (TypeError, ValueError):
                r = 0.0
            if r > 0:
                live["ref"] = r
                live["prev_close"] = r
    if not (isinstance(live, dict) and float(live.get("close") or 0) > 0):
        if isinstance(pack, dict) and isinstance(pack.get("live_tx"), dict):
            return pack.get("live_tx")
        return None
    # 夜盤起日：05:00 前算昨曆日（與電子盤卡同一套）
    eve = _ymd(live.get("date")) or ""
    if len(eve) != 8:
        try:
            from market_session_cards import _evening_start_ymd

            eve = _evening_start_ymd(dt)
        except Exception:
            eve = (
                (dt - timedelta(days=1)).strftime("%Y%m%d")
                if int(dt.hour) < 5
                else dt.strftime("%Y%m%d")
            )
        live = {**live, "date": eve}
    if isinstance(pack, dict):
        pack["live_tx"] = live
    return live


def _apply_live_tx_to_axis(
    *,
    tx_o: List[float],
    tx_h: List[float],
    tx_l: List[float],
    tx_c: List[float],
    tw_bars: Sequence[Dict[str, Any]],
    live: Optional[Dict[str, Any]],
) -> Optional[int]:
    """夜盤即時寫進加權日軸對齊格；回傳更新索引。

    MIS／即時列帶齊 OHLC 時整根置換：不准留庫內舊開／舊低（前收填或未齊夜盤）
    造成假影線、缺真K。只拿到收的殘 tip 才併入既有柱。
    """
    if not live or not tx_c or not tw_bars:
        return None
    try:
        px = float(live.get("close") or 0)
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None
    eve = _ymd(live.get("date")) or ""
    idx: Optional[int] = None
    if eve:
        for i, r in enumerate(tw_bars):
            if _ymd(r.get("date")) == eve:
                idx = i
                break
    if idx is None:
        idx = len(tw_bars) - 1
    if idx < 0 or idx >= len(tx_c):
        return None
    try:
        o = float(live.get("open") or 0)
        h = float(live.get("high") or 0)
        lo = float(live.get("low") or 0)
    except (TypeError, ValueError):
        o = h = lo = 0.0
    src = str(live.get("source") or "")
    is_rt = bool(live.get("is_realtime")) or src.startswith("taifex")
    full_live = is_rt and o > 0 and h > 0 and lo > 0
    if full_live:
        # 即時夜盤整根：開高低收都以 MIS 為準（仍自洽高低包開收）
        tx_o[idx] = float(o)
        tx_c[idx] = float(px)
        tx_h[idx] = float(max(h, px, o))
        tx_l[idx] = float(min(x for x in (lo, px, o) if x and x > 0))
        return int(idx)
    # 殘 tip 只有收：併入既有柱，不准把官方開改掉
    if o <= 0:
        o = px
    if h <= 0:
        h = px
    if lo <= 0:
        lo = px
    prev_c = float(tx_c[idx]) if tx_c[idx] == tx_c[idx] and tx_c[idx] else 0.0
    if prev_c > 0:
        try:
            o0 = float(tx_o[idx]) if tx_o[idx] == tx_o[idx] else o
        except (TypeError, ValueError):
            o0 = o
        o = o0 if o0 > 0 else o
        try:
            h0 = float(tx_h[idx]) if tx_h[idx] == tx_h[idx] else h
            l0 = float(tx_l[idx]) if tx_l[idx] == tx_l[idx] else lo
        except (TypeError, ValueError):
            h0, l0 = h, lo
        h = max(h0, h, px, o)
        lo = min(x for x in (l0, lo, px, o) if x and x > 0)
    tx_o[idx] = o
    tx_h[idx] = h
    tx_l[idx] = lo
    tx_c[idx] = px
    return int(idx)


def _soxx_volume_by_date(db_path: str, since: str = "20260301") -> Dict[str, float]:
    """SOXX 日量字典（費半指數無官方量 → 教具大量撐壓用代理）。"""
    out: Dict[str, float] = {}
    try:
        _ensure_soxx_volume_proxy(db_path)
    except Exception:
        logger.exception("SOXX 量代理補抓略過")
    for r in _load_us_daily(db_path, "SOXX", since=since):
        d = _ymd(r.get("date"))
        v = float(r.get("volume") or 0)
        if d and v > 0:
            out[d] = v
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


def _tw_has_foot2_low_zone(pack: Optional[Dict[str, Any]] = None) -> bool:
    """題旨是否已收改口低點區 37000~37500（後文壓 C9 35500~37300）。"""
    roles = {
        str(r.get("role") or "")
        for r in ((pack or {}).get("pred_levels") or {}).get("tw") or []
    }
    if "改口低上沿" in roles or "改口低下沿" in roles:
        return True
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if abs(lv - 37500.0) < 1.0 or abs(lv - 37000.0) < 1.0:
            role = str(row.get("role") or "")
            if role.startswith("改口") or role.startswith("夜盤低"):
                return True
    blob = " ".join(
        str(x or "")
        for x in (
            (pack or {}).get("thesis"),
            (pack or {}).get("snippet"),
            (pack or {}).get("wait_struct"),
        )
    )
    return _text_has_foot2_revision(blob)


def _tw_has_c9_low_zone(pack: Optional[Dict[str, Any]] = None) -> bool:
    """題旨是否已收 C-9 低點區 35500~37300（他改口後舊 38000 上沿改標已破）。

    改口低點區 37000~37500 也視為已收修訂低點（同樣讓舊 38000 標已破）。
    """
    if _tw_has_foot2_low_zone(pack):
        return True
    roles = {
        str(r.get("role") or "")
        for r in ((pack or {}).get("pred_levels") or {}).get("tw") or []
    }
    if "C9低上沿" in roles or "C9低下沿" in roles:
        return True
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if abs(lv - 37300.0) < 1.0 or abs(lv - 35500.0) < 1.0:
            return True
    return False


def _level_break_up_tag(level: float, highs: Sequence[float]) -> str:
    """上方壓力破位：官方高向上觸及／穿過＝已破；不准拿下跌低點誤標。"""
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return "未到"
    if not highs:
        return "未到"
    try:
        mx = max(float(x) for x in highs if x is not None)
    except ValueError:
        return "未到"
    if mx > lv + 0.5:
        return "已破"
    return "未破" if mx >= lv * 0.98 else "未到"


def _tw_pred_break_tag(
    level: float,
    lows: Sequence[float],
    *,
    pack: Optional[Dict[str, Any]] = None,
    role: str = "",
    highs: Optional[Sequence[float]] = None,
) -> str:
    """加權預測錨破位標。

    撐／低／買點：官方低觸及＝已破。
    壓力／上方觀察壓：官方高向上穿＝已破（不准拿下跌低點誤標已破）。
    有 C9 區時舊 38000 劇本一上沿改口標已破。
    """
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return "未到"
    role_s = str(role or "")
    if (
        (role_s == "劇本一上沿" or abs(lv - 38000.0) < 1.0)
        and _tw_has_c9_low_zone(pack)
    ):
        return "已破"
    # 回測平均／最低／舊「至少回測」：只看最近一根有沒有測到；不准拿急跌全程最低誤標已破
    if role_s in {"回測平均", "回測最低", "至少回測", "低點帶"} or abs(
        lv - 41500.0
    ) < 0.6:
        if lows:
            try:
                last_lo = float(lows[-1])
            except (TypeError, ValueError, IndexError):
                last_lo = None
            if last_lo is not None and last_lo <= lv + 80.0:
                return "已測"
        return "未到"
    is_press = bool(
        role_s in {"台指壓力", "反彈穿刺", "轉震盪"}
        or ("壓" in role_s and "撐" not in role_s and "低" not in role_s)
    )
    if is_press:
        hi_vals: List[float] = []
        if highs:
            try:
                hi_vals = [float(x) for x in highs if x is not None]
            except (TypeError, ValueError):
                hi_vals = []
        return _level_break_up_tag(lv, hi_vals)
    return _level_break_tag(level, lows)


def _c9_extension_active(pack: Optional[Dict[str, Any]] = None) -> bool:
    """題旨是否為 9波擴延 C-7走完→C-8→C-9（只認他文／pred，不准自創）。

    後文止跌確認／B-b 雙軌／第二隻腳當令時不准再畫 C1…C9／C-7轉C-8。
    不准把「改口低點區／foot2」經 _tw_has_c9_low_zone 誤開九波標。
    """
    thesis = str((pack or {}).get("thesis") or "")
    snip = str(
        (pack or {}).get("snippet_full")
        or (pack or {}).get("snippet")
        or ""
    )
    wait = str((pack or {}).get("wait_struct") or "")
    blob = f"{thesis} {snip} {wait}"
    if (
        _text_has_c3_pressure_break(blob)
        or "不再假跌破" in thesis
        or "過C3下降壓" in thesis
        or _text_has_stop_low_confirm(blob)
        or "確認上週五低" in thesis
        or "止跌確認" in thesis
    ):
        return False
    if (
        _text_has_bb_dual_path(blob)
        or "B-b" in thesis
        or "五波跌完" in thesis
        or "備線九波" in thesis
    ):
        return False
    if (
        _tw_has_foot2_low_zone(pack)
        or "第二隻腳" in thesis
        or "等第二隻腳" in thesis
        or _text_has_foot2_revision(blob)
    ):
        return False
    if (
        "9波擴延" in blob
        or "C-7走完" in blob
        or "C-7轉C-8" in blob
        or "準備往八" in blob
    ):
        return True
    if re.search(r"C\s*[-–]\s*7.{0,24}C\s*[-–]\s*8", blob) and re.search(
        r"C\s*[-–]\s*9", blob
    ):
        return True
    roles = {
        str(r.get("role") or "")
        for r in ((pack or {}).get("pred_levels") or {}).get("tw") or []
    }
    if "C9低上沿" in roles or "C9低下沿" in roles:
        return True
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if abs(lv - 37300.0) < 1.0 or abs(lv - 35500.0) < 1.0:
            return True
    return False


def _c9_now_step_label() -> str:
    """此刻層級短標（話筒／釘點／縮圖共用）。"""
    return "C-7轉C-8"


def _c9_oral_now_line() -> str:
    """9波擴延人話：目前最有可能 C-7轉C-8；最後一小段 C-9；低點區 35500~37300。"""
    return (
        "目前最有可能C-7轉C-8；還有最後一小段下跌C-9，"
        "要跌就全部跌完；低點約會落在35500~37300"
    )


def _foot2_oral_now_line() -> str:
    """改口人話：夜盤跌完居多；看不到37000以下；低點37000~37500；等第二隻腳。"""
    return (
        "夜盤來看跌完居多；目前應該看不到37000以下；"
        "低點最多37000~37500；等反彈後拉回1-2轉1-3-1第二隻腳"
    )


def _pack_pressure_break_on(pack: Optional[Dict[str, Any]] = None) -> bool:
    """題旨／等待句是否為下降壓改口當令（線≠41760）。"""
    thesis = str((pack or {}).get("thesis") or "")
    wait = str((pack or {}).get("wait_struct") or "")
    blob = " ".join(
        str(x or "")
        for x in (
            thesis,
            (pack or {}).get("snippet_full"),
            (pack or {}).get("snippet"),
            wait,
        )
    )
    return bool(
        _text_has_c3_pressure_break(blob)
        or "過C3下降壓" in thesis
        or "不再假跌破" in thesis
        or "回測下降壓力線" in wait
        or "已過C3下降壓" in blob
    )


def _paint_c3_vs_41760_legend(ax, *, fp, pack: Optional[Dict[str, Any]] = None) -> None:
    """舊色帶說明框已刪（使用者 2026-11-11：直排 C 標已夠，不准再掛對照簽）。"""
    _ = (ax, fp, pack)
    return


def _vertical_upright_label(text: str) -> str:
    """直排標：一字一行，字仍正立（不准 rotate／歪頭才讀得懂）。"""
    chars = [c for c in str(text or "") if not c.isspace()]
    return "\n".join(chars) if chars else ""


def _huang_c_daily_span_gate(pack: Optional[Dict[str, Any]] = None) -> bool:
    """日盤 C1–C4 底色／直標：下降壓／止跌確認當令才開。"""
    blob = " ".join(
        str(x or "")
        for x in (
            (pack or {}).get("thesis"),
            (pack or {}).get("snippet_full"),
            (pack or {}).get("snippet"),
            (pack or {}).get("wait_struct"),
        )
    )
    return bool(
        _pack_pressure_break_on(pack)
        or _text_has_stop_low_confirm(blob)
        or "C3-5" in blob
        or "第二組" in blob
        or "C1" in blob
        or "次級" in blob
    )


def _resolve_huang_c_daily_spans(
    bars: Sequence[Dict[str, Any]],
    *,
    lows: Optional[Sequence[float]] = None,
    highs: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """日盤 C1–C4 轉折錨：底色起迄＝紫折四段起迄（官方柱高低）。

    C1 10/6高→10/18低｜C2→10/28高｜C3→週五低37837｜C4→今。
    """
    empty: Dict[str, Any] = {"ok": False}
    if not bars:
        return empty

    def _idx_first(ymd: str, *alts: str) -> Optional[int]:
        for a in (ymd,) + alts:
            got = _bar_index_by_ymd(bars, a)
            if got is not None:
                return int(got)
        return None

    def _idx_last(ymd: str, *alts: str) -> Optional[int]:
        for a in (ymd,) + alts:
            got = _bar_index_last_by_ymd(bars, a)
            if got is not None:
                return int(got)
        return None

    hi_vals = (
        [float(x) for x in highs]
        if highs is not None
        else [float(r.get("high") or 0) for r in bars]
    )
    lo_vals = (
        [float(x) for x in lows]
        if lows is not None
        else [float(r.get("low") or 0) for r in bars]
    )
    cl_vals = [float(r.get("close") or 0) for r in bars]
    n = len(bars)
    i1 = _idx_first("20261006", "20261007")
    i1e = _idx_last("20261018", "20261019", "20261020")
    i2e = _idx_last("20261028", "20261027", "20261029")
    i3e = _idx_last("20261106", "20261107")
    if i3e is None:
        for ii, _lv in enumerate(lo_vals):
            try:
                if abs(float(_lv) - 37837.0) < 1.0:
                    i3e = ii
                    break
            except (TypeError, ValueError):
                continue
    if None in (i1, i1e, i2e, i3e):
        return empty
    i1, i1e, i2e, i3e = int(i1), int(i1e), int(i2e), int(i3e)
    i2 = i1e + 1
    i3 = i2e + 1
    i4 = i3e + 1
    i_now = n - 1
    if not (0 <= i1 < i1e < i2e < i3e <= i_now):
        return empty
    if i2 > i2e or i3 > i3e:
        return empty
    try:
        y1 = float(hi_vals[i1])
        y1e = float(lo_vals[i1e])
        y2e = float(hi_vals[i2e])
        y3e = float(lo_vals[i3e])
        y_now = float(cl_vals[i_now])
    except (TypeError, ValueError, IndexError):
        return empty
    return {
        "ok": True,
        "i1": i1,
        "i1e": i1e,
        "i2": i2,
        "i2e": i2e,
        "i3": i3,
        "i3e": i3e,
        "i4": i4,
        "i_now": i_now,
        "y1": y1,
        "y1e": y1e,
        "y2e": y2e,
        "y3e": y3e,
        "y_now": y_now,
        # 紫折五點＝四段，起迄對底色
        "xs": [float(i1), float(i1e), float(i2e), float(i3e), float(i_now)],
        "ys": [y1, y1e, y2e, y3e, y_now],
    }


def _paint_wave_draw_howto(
    fig,
    *,
    fp,
    text: str,
    y: float = 0.918,
    color: str = "#90caf9",
) -> None:
    """近／超近浪線畫法一口（figure 頂、不進主圖壓 K）。"""
    if fig is None or fp is None:
        return
    msg = str(text or "").strip()
    if not msg:
        return
    try:
        fig.text(
            0.03,
            float(y),
            msg,
            fontproperties=fp(8.0, "bold"),
            color=color,
            ha="left",
            va="top",
        )
    except Exception:
        return


def _paint_macro_wave_seg_tags(
    ax,
    *,
    i5s: int,
    i5e: int,
    i_alow: int,
    i_b_end: int,
    i_now: int,
    y5s: float,
    y5e: float,
    y_alow: float,
    y_b_end: float,
    y_now: float,
    fp,
    span_y: float,
) -> None:
    """近窗：⑤／A／B 段中點短標，一眼對上色線（尖點對尖點連）。

    不准再貼段中孤「C」：右欄已有大C今、浪名已有 C進行中（多餘會壓K）。
    """
    if ax is None or fp is None:
        return
    _ = (i_now, y_now)  # C 段終點仍傳入對齊呼叫端，但不畫孤 C
    tags = (
        ((i5s + i5e) * 0.5, (y5s + y5e) * 0.5, "⑤", "#40c4ff", "#01579b"),
        ((i5e + i_alow) * 0.5, (y5e + y_alow) * 0.5, "A", "#ff8a80", "#b71c1c"),
        ((i_alow + i_b_end) * 0.5, (y_alow + y_b_end) * 0.5, "B", "#ffd54f", "#f57f17"),
    )
    dy = max(float(span_y) * 0.012, 80.0)
    for x, y, lab, fg, face in tags:
        try:
            ax.text(
                float(x),
                float(y) + dy,
                lab,
                ha="center",
                va="bottom",
                fontproperties=fp(8.2, "bold"),
                color=fg,
                zorder=9,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": face,
                    "edgecolor": fg,
                    "linewidth": 0.8,
                    "alpha": 0.88,
                },
                clip_on=False,
            )
        except Exception:
            continue


def _paint_huang_c_degree_path(
    ax,
    spans: Optional[Dict[str, Any]],
    *,
    fade: bool = False,
) -> bool:
    """大C 紫折跟 C1–C4 底色：四段（五點），起迄對齊段界轉折。"""
    if ax is None or not isinstance(spans, dict) or not spans.get("ok"):
        return False
    xs = list(spans.get("xs") or [])
    ys = list(spans.get("ys") or [])
    if len(xs) < 5 or len(ys) < 5:
        return False
    ax.plot(
        xs,
        ys,
        color="#ea80fc",
        lw=1.15 if fade else 2.2,
        alpha=0.28 if fade else 1.0,
        zorder=5.5 if fade else 7.05,
        solid_capstyle="round",
        solid_joinstyle="round",
    )
    return True


def _paint_c3_group12_span_labels(
    ax,
    bars: Sequence[Dict[str, Any]],
    *,
    fp,
    pack: Optional[Dict[str, Any]] = None,
    lows: Optional[Sequence[float]] = None,
    highs: Optional[Sequence[float]] = None,
) -> None:
    """三窗加權：60分大段映到日K（C1～C4）。

    標＝直排正立（一字一行，不准旋轉歪頭）；底色四段；紫折另函對齊。
    不准再畫 C3 白虛下降壓示意線。
    """
    if ax is None or fp is None or not bars:
        return
    if not _huang_c_daily_span_gate(pack):
        return
    spans = _resolve_huang_c_daily_spans(bars, lows=lows, highs=highs)
    if not spans.get("ok"):
        return
    i1 = int(spans["i1"])
    i1e = int(spans["i1e"])
    i2 = int(spans["i2"])
    i2e = int(spans["i2e"])
    i3 = int(spans["i3"])
    i3e = int(spans["i3e"])
    i4 = int(spans["i4"])
    i_now = int(spans["i_now"])
    try:
        y0, y1 = ax.get_ylim()
        span_y = max(float(y1) - float(y0), 1.0)
        y_band = float(y0) + span_y * 0.08
    except Exception:
        return

    def _span_band(
        i_a: int,
        i_b: int,
        *,
        face: str,
        edge: str,
        label: str,
        fg: str,
    ) -> None:
        if int(i_b) < int(i_a):
            return
        _ = edge
        x_a, x_b = float(i_a) - 0.45, float(i_b) + 0.45
        # 底色極淡：只提示段界，不准洗掉縮圖K（使用者：不要連基本K圖都沒有）
        ax.axvspan(
            x_a,
            x_b,
            facecolor=face,
            alpha=0.035,
            zorder=0.9,
            linewidth=0,
        )
        # 直排正立：橫向太長改一字一行；英／國字都不旋轉；標貼底緣，不准蓋K實體
        ax.text(
            (float(i_a) + float(i_b)) * 0.5,
            y_band,
            _vertical_upright_label(label),
            ha="center",
            va="bottom",
            fontproperties=fp(9.2, "bold"),
            color=fg,
            zorder=3.5,
            linespacing=1.05,
            rotation=0,
            bbox={
                "boxstyle": "round,pad=0.18",
                "facecolor": face,
                "edgecolor": "#ffffff",
                "linewidth": 0.8,
                "alpha": 0.45,
            },
            clip_on=False,
        )

    try:
        _span_band(i1, i1e, face="#00e5ff", edge="#00bcd4", label="C1 下跌", fg="#00363a")
        _span_band(
            i2, i2e, face="#ffb74d", edge="#ef6c00", label="C2 中繼", fg="#3e2723"
        )
        _span_band(i3, i3e, face="#ea80fc", edge="#6a1b9a", label="C3 下跌", fg="#ffffff")
        # C3／週五低標併右欄「週五低／37,837」；不准再黃箭重複掛一顆
        # 白虛下降壓示意線／端點已刪（使用者 2026-11-11：兩張圖白虛＋紫虛＋兩點都取消）
        if i_now >= i4:
            # 2026-11-11 黃培碩：三波段結束後定義第四大波（教導用；話筒價仍跟飆大）
            _span_band(
                i4,
                i_now,
                face="#69f0ae",
                edge="#00c853",
                label="C4＝第四大波",
                fg="#003300",
            )
    except Exception:
        logger.debug("黃培碩 C1／C2／C3／C4 跨度標略過", exc_info=True)


def _nearest_bar_idx_by_price(
    rows: Sequence[Dict[str, Any]],
    target: float,
    *,
    field: str = "low",
    lo: int = 0,
    hi: Optional[int] = None,
    tol: float = 80.0,
) -> Optional[int]:
    """官方柱找最靠近 target 的高低；超過 tol 當沒找到（不准硬湊）。"""
    if not rows or target <= 0:
        return None
    end = len(rows) if hi is None else min(int(hi), len(rows))
    start = max(0, int(lo))
    best_i: Optional[int] = None
    best_d = float("inf")
    key = "high" if str(field).lower().startswith("h") else "low"
    for i in range(start, end):
        try:
            v = float((rows[i] or {}).get(key) or 0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        d = abs(v - float(target))
        if d < best_d:
            best_d = d
            best_i = i
    if best_i is None or best_d > float(tol):
        return None
    return int(best_i)


def _huang_c60_alt_swings(
    rows: Sequence[Dict[str, Any]],
    i_a: int,
    i_b: int,
    *,
    start: str = "h",
    min_swing: float = 700.0,
    force_end: str = "",
) -> List[Tuple[int, float, str]]:
    """官方柱交替高低折點（只連真高低；min_swing 以下不另起一段）。"""
    if not rows or int(i_b) <= int(i_a):
        return []
    hs = [float((r or {}).get("high") or 0) for r in rows]
    ls = [float((r or {}).get("low") or 0) for r in rows]
    ia, ib = int(i_a), int(i_b)
    pts: List[Tuple[int, str, float]] = []
    if str(start).lower().startswith("h"):
        pts.append((ia, "h", hs[ia]))
        want = "l"
    else:
        pts.append((ia, "l", ls[ia]))
        want = "h"
    i = ia + 1
    ms = float(min_swing)
    while i <= ib:
        if want == "l":
            best, bestv = i, ls[i]
            j = i
            locked = False
            while j <= ib:
                if ls[j] <= bestv:
                    bestv, best = ls[j], j
                if hs[j] >= bestv + ms and j > best:
                    pts.append((best, "l", bestv))
                    want = "h"
                    i = best + 1
                    locked = True
                    break
                j += 1
            if not locked:
                if best != pts[-1][0]:
                    pts.append((best, "l", bestv))
                break
        else:
            best, bestv = i, hs[i]
            j = i
            locked = False
            while j <= ib:
                if hs[j] >= bestv:
                    bestv, best = hs[j], j
                if ls[j] <= bestv - ms and j > best:
                    pts.append((best, "h", bestv))
                    want = "l"
                    i = best + 1
                    locked = True
                    break
                j += 1
            if not locked:
                if best != pts[-1][0]:
                    pts.append((best, "h", bestv))
                break
    end_k = str(force_end or "").lower()
    if end_k.startswith("l"):
        if pts[-1][0] != ib:
            if pts[-1][1] == "l":
                if ls[ib] <= pts[-1][2]:
                    pts[-1] = (ib, "l", ls[ib])
            else:
                pts.append((ib, "l", ls[ib]))
        elif ls[ib] < pts[-1][2]:
            pts[-1] = (ib, "l", ls[ib])
    elif end_k.startswith("h"):
        if pts[-1][0] != ib:
            if pts[-1][1] == "h":
                if hs[ib] >= pts[-1][2]:
                    pts[-1] = (ib, "h", hs[ib])
            else:
                pts.append((ib, "h", hs[ib]))
    # 折線保留全部交替點；①②③④只釘「相對大」的四個內轉折（避免小震盪搶標）
    moves: List[Tuple[float, int]] = []
    for idx in range(1, max(1, len(pts) - 1)):
        moves.append((abs(float(pts[idx][2]) - float(pts[idx - 1][2])), idx))
    moves.sort(key=lambda t: t[0], reverse=True)
    label_idx = {
        j: lab
        for lab, (_mag, j) in zip(["①", "②", "③", "④"], sorted(moves[:4], key=lambda t: t[1]))
    }
    out: List[Tuple[int, float, str]] = []
    for idx, (ii, kind, yy) in enumerate(pts):
        out.append((int(ii), float(yy), str(label_idx.get(idx) or "")))
    return out


def _huang_c60_c3_segments(
    rows: Sequence[Dict[str, Any]],
    i2: int,
    i3: int,
    *,
    y2: float,
    y3: float,
) -> List[Tuple[int, float, str]]:
    """C3 內段①～⑤（對黃培碩手繪）：④＝43135、⑤＝37837。

    ①須走完第一大段下跌才轉②（不准在 44726 小反彈提早結束①）。
    ①～⑤全在 C3＝(3) 下跌內；不准把這組浪號畫到 C4。
    """
    if not rows or int(i3) <= int(i2):
        return []
    out: List[Tuple[int, float, str]] = [(int(i2), float(y2), "")]
    # ④／⑤先釘死（手繪紅圈④＝43135、⑤＝37837＝大段(3)底）
    i4 = _nearest_bar_idx_by_price(
        rows, 43135.0, field="high", lo=int(i2) + 1, hi=int(i3), tol=40.0
    )
    if i4 is None or int(i4) <= int(i2) or int(i4) >= int(i3):
        out.append((int(i3), float(y3), "⑤"))
        return out
    y4 = float(rows[int(i4)].get("high") or 0)
    # ③＝④之前最低（約 41856）
    i_w3: Optional[int] = None
    y_w3 = float("inf")
    for i in range(int(i2) + 1, int(i4)):
        try:
            lo = float(rows[i].get("low") or 0)
        except (TypeError, ValueError):
            continue
        if 0 < lo < y_w3:
            y_w3, i_w3 = lo, i
    if i_w3 is None or y_w3 >= float(y2) - 500:
        out.extend(
            [
                (int(i4), float(y4), "④"),
                (int(i3), float(y3), "⑤"),
            ]
        )
        return out
    # ①②：①須至少跌過起點→③跌幅的一半，略過 44726 這類淺低
    min_drop = max(1800.0, 0.48 * (float(y2) - float(y_w3)))
    fine = _huang_c60_alt_swings(
        rows, int(i2), int(i_w3), start="h", min_swing=650.0, force_end="l"
    )
    i_one: Optional[int] = None
    y_one = 0.0
    for ii, yy, _lab in fine[1:]:
        if int(ii) >= int(i_w3):
            break
        lo_v = float(rows[int(ii)].get("low") or 0)
        cand = float(lo_v if lo_v > 0 else yy)
        if cand <= float(y2) - min_drop:
            i_one, y_one = int(ii), cand
            break
    i_two: Optional[int] = None
    y_two = 0.0
    if i_one is not None:
        out.append((int(i_one), float(y_one), "①"))
        for ii, yy, _lab in fine:
            if int(ii) <= int(i_one):
                continue
            if int(ii) >= int(i_w3):
                break
            hi_v = float(rows[int(ii)].get("high") or 0)
            cand = float(hi_v if hi_v > 0 else yy)
            if cand >= float(y_one) + 400:
                i_two, y_two = int(ii), cand
                break
        if i_two is None:
            # 退：①→③之間最高當②
            best_i, best_h = None, 0.0
            for i in range(int(i_one) + 1, int(i_w3)):
                try:
                    h = float(rows[i].get("high") or 0)
                except (TypeError, ValueError):
                    continue
                if h > best_h:
                    best_h, best_i = h, i
            if best_i is not None and best_h >= float(y_one) + 400:
                i_two, y_two = int(best_i), float(best_h)
        if i_two is not None:
            out.append((int(i_two), float(y_two), "②"))
    out.append((int(i_w3), float(y_w3), "③"))
    out.append((int(i4), float(y4), "④"))
    out.append((int(i3), float(y3), "⑤"))
    return out


def _huang_c60_c4_segments(
    rows: Sequence[Dict[str, Any]],
    i3: int,
    y3: float,
) -> List[Tuple[int, float, str]]:
    """C4＝第四大波折點：只連官方柱高低，不准標①～⑤。

    新縮圖K持續進來＝白折跟到窗末最新根（收）；次級4壓是水平線不是折線終點。
    浪號①～⑤只屬於 C3；不准因新柱發明 C4 浪號。
    """
    out: List[Tuple[int, float, str]] = [(int(i3), float(y3), "")]
    if not rows or int(i3) >= len(rows) - 1:
        return out
    i_end = len(rows) - 1
    swings = _huang_c60_alt_swings(
        rows, int(i3), int(i_end), start="l", min_swing=450.0, force_end=""
    )
    for ii, yy, _lab in swings[1:]:
        if int(ii) >= int(i_end):
            continue
        # 全部不標浪號（手繪 C4 無①～⑤）
        out.append((int(ii), float(yy), ""))
    # 窗末釘最新縮圖K收（教具鎖死畫到最新）；不准停在第一次碰到 43135
    try:
        c = float(rows[int(i_end)].get("close") or 0)
        h = float(rows[int(i_end)].get("high") or 0)
        lo = float(rows[int(i_end)].get("low") or 0)
    except (TypeError, ValueError):
        c = h = lo = 0.0
    y_end = c if c > 0 else (h if h > 0 else lo)
    if y_end <= 0:
        return out
    if out[-1][0] == int(i_end):
        out[-1] = (int(i_end), float(y_end), "")
    else:
        out.append((int(i_end), float(y_end), ""))
    return out


def _resolve_huang_c60_anchors(
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """黃培碩 60 分大段錨：只認官方柱對上他圖上的轉折價。

    (1) 49968→46170　(2)中繼框 46170~47060　(3)內①～⑤→37837
    C4＝第四大波白細折（不標①～⑤；2026-11-11 定義）；次級4壓≈43135。
    """
    out: Dict[str, Any] = {"ok": False}
    if not rows or len(rows) < 16:
        return out
    i1 = _nearest_bar_idx_by_price(rows, 49968.0, field="high", tol=30.0)
    i1e = _nearest_bar_idx_by_price(rows, 46170.0, field="low", tol=30.0)
    i2 = _nearest_bar_idx_by_price(
        rows, 47060.0, field="high", lo=int(i1e or 0), tol=30.0
    )
    i3 = _nearest_bar_idx_by_price(
        rows, 37837.0, field="low", lo=int(i2 or 0), tol=30.0
    )
    if None in (i1, i1e, i2, i3):
        return out
    if not (int(i1) < int(i1e) < int(i2) < int(i3)):
        return out
    y1 = float(rows[int(i1)].get("high") or 0)
    y1e = float(rows[int(i1e)].get("low") or 0)
    y2 = float(rows[int(i2)].get("high") or 0)
    y3 = float(rows[int(i3)].get("low") or 0)
    # C3 內①～⑤：④＝43135、⑤＝37837；①不准在 44726 提早轉②
    c3_seg = _huang_c60_c3_segments(rows, int(i2), int(i3), y2=y2, y3=y3)
    # C4 反彈折：不標浪號；壓力線用次級4（C3④價）
    c4 = _huang_c60_c4_segments(rows, int(i3), float(y3))
    y_press = 43135.0
    four = next((p for p in c3_seg if p[2] == "④"), None)
    if four is not None:
        y_press = float(four[1])
    else:
        i_p = _nearest_bar_idx_by_price(
            rows, 43135.0, field="high", lo=int(i2), hi=int(i3) + 1, tol=40.0
        )
        if i_p is not None:
            y_press = float(rows[int(i_p)].get("high") or 43135.0)
    out.update(
        {
            "ok": True,
            "i1": int(i1),
            "y1": y1,
            "i1e": int(i1e),
            "y1e": y1e,
            "i2": int(i2),
            "y2": y2,
            "i3": int(i3),
            "y3": y3,
            "c2_box": (float(y1e), float(y2)),
            "c3_seg": c3_seg,
            "c4": c4,
            "c4_press": float(y_press),
            # 舊鍵相容
            "red": c4,
        }
    )
    return out


def _paint_huang_c60_structure(
    ax,
    rows: Sequence[Dict[str, Any]],
    *,
    fp,
    pack: Optional[Dict[str, Any]] = None,
) -> bool:
    """超近窗 60 分：C1–C4 四色底＋大段藍粗折＋C3①～⑤／C4 細白浪折。

    底色已分 C1–C4。大段藍粗折＝(1)→C1低→(2)→C3底37837→C4段高
    （對使用者黃線示意；色同 C1–C2 藍）。細白＝段內浪折細節。
    段界不准再畫豎虛線。不是買訊；不准把黃培碩段號當進出場。
    """
    if ax is None or fp is None or not rows:
        return False
    _ = pack
    anc = _resolve_huang_c60_anchors(rows)
    if not anc.get("ok"):
        return False
    i1, i1e, i2, i3 = (
        int(anc["i1"]),
        int(anc["i1e"]),
        int(anc["i2"]),
        int(anc["i3"]),
    )
    y1, y1e, y2, y3 = (
        float(anc["y1"]),
        float(anc["y1e"]),
        float(anc["y2"]),
        float(anc["y3"]),
    )
    n = len(rows)
    try:
        y0, y1_ax = ax.get_ylim()
        span_y = max(float(y1_ax) - float(y0), 1.0)
        # 段名貼近底緣，不准壓折線／K
        y_band = float(y0) + span_y * 0.055
    except Exception:
        return False

    def _span(ia: int, ib: int, face: str, edge: str, label: str, fg: str) -> None:
        if int(ib) < int(ia):
            return
        # 只要色底＋段名；豎虛線刪（四色已分界）
        _ = edge
        ax.axvspan(
            float(ia) - 0.45,
            float(ib) + 0.45,
            facecolor=face,
            alpha=0.07,
            zorder=0.8,
            linewidth=0,
        )
        ax.text(
            (float(ia) + float(ib)) * 0.5,
            y_band,
            label,
            ha="center",
            va="bottom",
            fontproperties=fp(8.6, "bold"),
            color=fg,
            zorder=20,
            bbox={
                "boxstyle": "round,pad=0.22",
                "facecolor": face,
                "edgecolor": "#ffffff",
                "linewidth": 1.0,
                "alpha": 0.72,
            },
            clip_on=False,
        )

    def _poly(
        xs: Sequence[float],
        ys: Sequence[float],
        *,
        edge: str,
        face: str,
        lw: float,
        edge_extra: float = 1.15,
        z0: float = 7.2,
    ) -> None:
        """粗邊＋亮芯：高低連成一線；芯＝細白／藍色浪折。"""
        ax.plot(
            list(xs),
            list(ys),
            color=edge,
            lw=float(lw) + float(edge_extra),
            zorder=float(z0),
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        ax.plot(
            list(xs),
            list(ys),
            color=face,
            lw=lw,
            zorder=float(z0) + 0.1,
            solid_capstyle="round",
            solid_joinstyle="round",
        )

    # 底色＝轉折對轉折
    _span(i1, i1e, "#00e5ff", "#00bcd4", "C1＝(1)下跌", "#00363a")
    _span(i1e + 1, i2, "#ffb74d", "#ef6c00", "C2＝(2)中繼", "#3e2723")
    _span(i2, i3, "#ea80fc", "#6a1b9a", "C3＝(3)下跌", "#ffffff")
    if n - 1 >= i3 + 1:
        # 2026-11-11 黃培碩口播＋附圖：37837 起＝第四大波（教導用；不准標①～⑤）
        _span(i3 + 1, n - 1, "#69f0ae", "#00c853", "C4＝第四大波", "#003300")

    # C2 中繼：上下震盪區間虛線（46170~47060）；標在框外左側，不准壓虛線／折線
    box = anc.get("c2_box") or (y1e, y2)
    y_box_lo, y_box_hi = float(box[0]), float(box[1])
    x_box0, x_box1 = float(i1e) - 0.2, float(i2) + 0.2
    for yy, tag in ((y_box_hi, "中繼上"), (y_box_lo, "中繼下")):
        ax.plot(
            [x_box0, x_box1],
            [yy, yy],
            color="#ff6f00",
            lw=1.55,
            ls=(0, (5, 2)),
            alpha=0.95,
            zorder=6.4,
        )
        ax.text(
            float(x_box0) - 0.55,
            float(yy),
            f"{tag}\n{_px(yy)}",
            ha="right",
            va="center",
            fontproperties=fp(7.2, "bold"),
            color="#ffe0b2",
            zorder=41,
            linespacing=1.05,
            bbox={
                "boxstyle": "round,pad=0.14",
                "facecolor": "#e65100",
                "edgecolor": "#ffcc80",
                "linewidth": 0.8,
                "alpha": 0.88,
            },
            clip_on=False,
        )

    def _wave_lab(
        ii: float,
        yy: float,
        lab: str,
        *,
        high: bool,
        face: str,
        edge: str,
        fg: str,
        fs: float = 8.2,
        dx: float = 0.85,
    ) -> None:
        """浪號／錨標：往側邊＋上下讓開折線與K，不准坐在線上。"""
        if not lab:
            return
        ax.text(
            float(ii) + float(dx),
            float(yy) + (span_y * 0.018 if high else -span_y * 0.018),
            lab,
            ha="left",
            va="bottom" if high else "top",
            fontproperties=fp(fs, "bold"),
            color=fg,
            zorder=44,
            bbox={
                "boxstyle": "round,pad=0.14",
                "facecolor": face,
                "edgecolor": edge,
                "linewidth": 0.85,
                "alpha": 0.9,
            },
            clip_on=False,
        )

    # C4 段高＝C3底之後官方最高（粗藍折終點；碎浪另走細白）
    i_c4_hi = int(i3)
    y_c4_hi = float(y3)
    for ii in range(int(i3), int(n)):
        try:
            hh = float((rows[ii] or {}).get("high") or 0)
        except (TypeError, ValueError, IndexError):
            continue
        if hh > y_c4_hi:
            y_c4_hi = hh
            i_c4_hi = int(ii)

    # 粗藍折＝大段高低連成一線（C1→C2→C3底→C4高；對使用者黃線示意，色同 C1C2）
    blue_xy = [(i1, y1), (i1e, y1e), (i2, y2), (i3, y3)]
    if int(i_c4_hi) > int(i3) and float(y_c4_hi) > float(y3) + 1.0:
        blue_xy.append((int(i_c4_hi), float(y_c4_hi)))
    _poly(
        [p[0] for p in blue_xy],
        [p[1] for p in blue_xy],
        edge="#0d47a1",
        face="#42a5f5",
        lw=2.35,
        edge_extra=1.35,
        z0=7.15,
    )
    for (ii, yy), lab, high in (
        ((i1, y1), "(1)", True),
        ((i1e, y1e), "46170", False),
        ((i2, y2), "(2)", True),
        ((i3, y3), "37837", False),
    ):
        ax.scatter(
            [ii],
            [yy],
            s=34,
            c="#42a5f5",
            zorder=8.2,
            edgecolors="#0d47a1",
            linewidths=0.9,
        )
        _wave_lab(
            ii,
            yy,
            lab,
            high=high,
            face="#1565c0",
            edge="#90caf9",
            fg="#e3f2fd",
            fs=8.6,
            dx=0.9,
        )
    if int(i_c4_hi) > int(i3):
        ax.scatter(
            [float(i_c4_hi)],
            [float(y_c4_hi)],
            s=34,
            c="#42a5f5",
            zorder=8.2,
            edgecolors="#0d47a1",
            linewidths=0.9,
        )

    # C3 碎浪：細白①～⑤（④＝43135、⑤＝37837）；大段高低已由粗藍折承接
    c3_seg = list(anc.get("c3_seg") or [])
    if len(c3_seg) >= 3:
        xs3 = [float(p[0]) for p in c3_seg]
        ys3 = [float(p[1]) for p in c3_seg]
        ax.plot(
            xs3,
            ys3,
            color="#0b0f14",
            lw=1.55,
            zorder=7.55,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        ax.plot(
            xs3,
            ys3,
            color="#f5f5f5",
            lw=0.95,
            zorder=7.6,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        for ii, yy, lab in c3_seg:
            if not lab:
                continue
            _spear_ring(ax, float(ii), float(yy), color="#ffffff", zorder=8.35, hot=False)
            high = lab in {"②", "④"}
            text = lab
            if lab == "④":
                text = f"④ {_px(float(yy))}"
            elif lab == "⑤":
                text = f"⑤ {_px(float(yy))}"
            _wave_lab(
                ii,
                yy,
                text,
                high=high,
                face="#eceff1",
                edge="#90a4ae",
                fg="#111111",
                fs=7.8,
                dx=0.7,
            )

    # C4 碎浪：細白反彈折（不標①～⑤）；大段高低已由粗藍折 C3底→C4高承接
    c4 = list(anc.get("c4") or anc.get("red") or [])
    if len(c4) >= 2:
        xs = [float(p[0]) for p in c4]
        ys = [float(p[1]) for p in c4]
        ax.plot(
            xs,
            ys,
            color="#0b0f14",
            lw=1.55,
            zorder=7.65,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        ax.plot(
            xs,
            ys,
            color="#f5f5f5",
            lw=0.95,
            zorder=7.7,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
        for ii, yy, lab in c4:
            _spear_ring(ax, float(ii), float(yy), color="#ffffff", zorder=8.6, hot=False)
            if lab and lab not in {"①", "②", "③", "④", "⑤", "底"} and "⑤" not in str(lab):
                _wave_lab(
                    ii,
                    yy,
                    str(lab),
                    high=True,
                    face="#ffffff",
                    edge="#9e9e9e",
                    fg="#111111",
                    fs=7.8,
                    dx=0.75,
                )
    # 次級4壓＝C3④價（≈43135）；水平虛線＋右側標，不准壓折線
    y_press = anc.get("c4_press")
    if y_press is None:
        four = next((p for p in c3_seg if p[2] == "④"), None)
        if four is not None:
            y_press = float(four[1])
    if y_press is not None:
        ax.axhline(
            float(y_press),
            color="#ff1744",
            lw=1.45,
            ls=(0, (6, 2)),
            alpha=0.9,
            zorder=6.2,
        )
        # 標在 C4 起段線上方；價已由 C3④ 標出，這裡只寫「次級4壓」不准再疊數字
        try:
            x_lab = float(i3) + max(2.0, (float(n) - float(i3)) * 0.12)
        except Exception:
            x_lab = max(0.0, float(n) * 0.55)
        ax.text(
            x_lab,
            float(y_press) + span_y * 0.022,
            "次級4壓",
            ha="left",
            va="bottom",
            fontproperties=fp(7.4, "bold"),
            color="#ff1744",
            zorder=41,
            bbox={
                "boxstyle": "round,pad=0.10",
                "facecolor": "#1a0808",
                "edgecolor": "#ff1744",
                "linewidth": 0.8,
                "alpha": 0.9,
            },
            clip_on=False,
        )
    return True


def _teach_cyan_band_title_bit(
    sr: Optional[Dict[str, Any]],
    *,
    pack: Optional[Dict[str, Any]] = None,
) -> str:
    """標題青帶一句；41760 台指壓標已刪，標題也不掛。"""
    _ = pack
    sr = sr or {}
    _sup_c = sr.get("support")
    _res_c = sr.get("resist")
    # 41760 右標已刪：青帶標題不准再寫這價／台指壓
    try:
        if _sup_c is not None and abs(float(_sup_c) - 41760.0) < 1.5:
            _sup_c = None
    except (TypeError, ValueError):
        pass
    return (
        f"青＝飆預測{_px(_sup_c) if _sup_c is not None else '—'}～"
        f"{_px(_res_c) if _res_c is not None else '—'}"
    )


def _active_oral_now_line(pack: Optional[Dict[str, Any]] = None) -> str:
    """話筒／三窗腳註：後文當令優先（下降壓改口＞止跌確認＞第二隻腳＞C9）。"""
    blob = " ".join(
        str(x or "")
        for x in (
            (pack or {}).get("thesis"),
            (pack or {}).get("snippet_full"),
            (pack or {}).get("snippet"),
            (pack or {}).get("wait_struct"),
        )
    )
    thesis = str((pack or {}).get("thesis") or "")
    if _pack_pressure_break_on(pack) or _text_has_c3_pressure_break(blob):
        # 寫死分開：斜線口述下降壓 ≠ 水平41760；回測平均／最低跟最新口頭
        # 不准只因對照句「≠41500」就切絕對不破（11/9 下降壓當令仍用不再假跌破）
        _rb_line = _retest_avg_min_from_text(blob)
        if _rb_line is not None:
            if abs(float(_rb_line["avg"]) - float(_rb_line["min"])) < 0.6:
                line = (
                    f"回測平均＝最低{_px(_rb_line['min'])}；"
                    "絕對不破週五低37837；"
                    "他說已過C3下降壓（口述斜線・無報價）"
                )
            else:
                line = (
                    f"回測平均{_px(_rb_line['avg'])}；"
                    f"回測最低{_px(_rb_line['min'])}；"
                    "絕對不破週五低37837；"
                    "他說已過C3下降壓（口述斜線・無報價）"
                )
            if "41760" in blob or "台指壓" in blob:
                line = "水平台指壓41760（≠回測帶）；" + line
            return line
        if _text_has_retest_41500(blob) or "至少回測41500" in blob:
            line = (
                f"回測平均＝最低{_px(41500)}；絕對不破週五低37837；"
                "他說已過C3下降壓（口述斜線・無報價）"
            )
            if "41760" in blob or "台指壓" in blob:
                line = "水平台指壓41760（≠41500）；" + line
            return line
        line = (
            "他說已過C3下降壓（口述斜線・圖上紫帶C3・粉虛下降壓示意／無報價）；"
            "週五低不再假跌破；拉回再測那條下降壓"
        )
        if "41760" in blob or "台指壓" in blob:
            line = "水平台指壓41760（≠那條口述下降壓）；" + line
        return line
    if _text_has_stop_low_confirm(blob) or "確認上週五低" in thesis:
        line = "C3-5＋1 4重疊・確認上週五低＝最低；一定再測週五低，破＝假跌破觀察"
        if "41760" in blob:
            line = "台指壓41760；" + line
        return line
    if _tw_has_foot2_low_zone(pack) or _text_has_foot2_revision(blob):
        return _foot2_oral_now_line()
    return _c9_oral_now_line()


# 飆大口頭題旨（已確認）：第二段下殺＝9波擴延・C-7轉C-8→C-9・低點區35500~37300
# 併留舊劇本一 35000~38000：有 C9 後 38000 改口「已破」、35000 右標拿掉
# 口頭 as_of＝確認日；更早題旨 cap 不准回填這段蓋掉當日真文／snap
_C9_ORAL_AS_OF = "20261106"
_C9_ORAL_SNIP = (
    "大盤第二段下殺應該是走9波擴延，目前最有可能C-7轉 C-8，"
    "還有最後一小段下跌C-9要跌就全部跌完，低點約會落在35500~37300之間。"
    "第一套劇本大盤會跌到35000~38000之間。"
)

# 飆大口頭改口（已確認）：夜盤跌完居多・看不到37000以下・低點37000~37500・第二隻腳
# 後文壓前文：蓋掉 C9 低點區 35500~37300（更早 as_of 仍留 C9）
# 他講「最安全是買…」＝他口語路徑；話筒標非買訊，不准進海選／黃金買點
_FOOT2_ORAL_AS_OF = "20261107"
_FOOT2_ORAL_POST_ID = "oral-foot2-37000"
_FOOT2_ORAL_SNIP = (
    "目前應該看不到37000以下，我夜盤來看應該跌完了居多。"
    "低點應該最多37000-37500可能性非常高。"
    "最安全是買反彈之後拉回1-2轉1-3-1，也就是第二隻腳。"
)

# 飆大口頭改口（已確認・11/9 夜）：夜盤過第二組 C3 下降壓力線 → 上週五低不再假跌破
# 後文壓前文：蓋掉「一定再測週五低／破＝假跌破」；下一步改盯拉回回測下降壓
# 口頭 as_of＝確認日；更早題旨 cap 不准回填這段蓋掉當日真文／snap
_PRESSURE_BREAK_ORAL_AS_OF = "20261109"
_PRESSURE_BREAK_ORAL_POST_ID = "oral-c3-pressure-break"
_PRESSURE_BREAK_ORAL_SNIP = (
    "夜盤已經過第二組整組 C3的下降壓力線，上周五低點也不可能假跌破了，"
    "但今天下半場到明後天一定會有拉回回測下降壓力線，順便清洗籌碼的時候，"
    "這個時候直接投入股市資金可達5~6成，剩下4~5成等新主流浮現再全力拉高資金比例達8~9成。"
    "高價股風向球創意密切關注。"
    # 釘週五低官方點，讓三窗／右欄標「不再假跌破」對得上 37837
    "星期五最低點位37837。"
)

# 飆大口頭（已確認・11/10）：拉回至少回測 41500；絕對不破上週五低
# 後文壓前文：盯價從「無報價下降壓」補上他釘的水平回測至少 41500（≠41760 台指壓）
_RETEST_41500_ORAL_AS_OF = "20261110"
_RETEST_41500_ORAL_POST_ID = "oral-retest-41500"
_RETEST_41500_ORAL_SNIP = (
    "應該至少回測到41500，絕對不會破上星期五低點。"
    "星期五最低點位37837。"
    # 併留下降壓改口脈絡，題旨掃描仍認同一當令
    "夜盤已經過第二組整組 C3的下降壓力線，上周五低點也不可能假跌破了，"
    "但今天下半場到明後天一定會有拉回回測下降壓力線。"
)

# 飆大口頭（已確認・11/12）：低點帶 41900～42700（約95%）；路徑先到 43000 下
# 後文壓前文：當令回測終點帶＝這兩數字，不是單點 41500（41500＝11/10「至少」更深口）
# 話筒標只認「回測平均／回測最低」兩口；區間異動＝從最新原文重算，不准鎖死舊價
_LOW_BAND_419_427_ORAL_AS_OF = "20261112"
_LOW_BAND_419_427_ORAL_POST_ID = "oral-low-band-419-427"
_LOW_BAND_419_427_LO = 41900.0
_LOW_BAND_419_427_HI = 42700.0
_LOW_BAND_419_427_MID = 42300.0
_LOW_BAND_419_427_ORAL_SNIP = (
    "絕對會到43000之下。"
    "不用害怕 低點絕對不會破，低點應該在41900~42700左右…這個區間95%。"
)

# 回測帶：4xxxx～4xxxx（低點／回測／區間／95% 語境）；後文最新一組壓前文
_RETEST_BAND_PAIR_RE = re.compile(
    r"(?:低點|回測|區間|95\s*%).{0,40}?"
    r"(?P<a>4[0-9]{4})\s*[-~～到至\-]\s*(?P<b>4[0-9]{4})"
    r"|"
    r"(?P<a2>4[0-9]{4})\s*[-~～到至\-]\s*(?P<b2>4[0-9]{4})"
    r".{0,40}?(?:低點|回測|區間|95\s*%)",
)
_RETEST_SINGLE_MIN_RE = re.compile(
    r"(?:至少)?回測(?:到)?\s*(?P<v>4[0-9]{4})|(?P<v2>4[0-9]{4}).{0,12}(?:至少)?回測"
)


def _text_has_retest_41500(blob: str) -> bool:
    """他釘：至少回測 41500；絕對不破上週五低。"""
    s = str(blob or "")
    if not s.strip():
        return False
    return bool(
        re.search(r"41500", s)
        and re.search(
            r"(?:至少)?回測(?:到)?\s*41500|41500.{0,12}(?:回測|至少)|"
            r"絕對不(?:會)?破.{0,16}(?:上)?(?:星期)?五.{0,8}低",
            s,
        )
    )


def _parse_retest_band_lo_hi(blob: str) -> Optional[Tuple[float, float]]:
    """從原文抓最新回測／低點區間（lo, hi）。只認他寫的兩個 4xxxx，不准發明。"""
    s = str(blob or "")
    if not s.strip():
        return None
    last: Optional[Tuple[float, float]] = None
    for m in _RETEST_BAND_PAIR_RE.finditer(s):
        raw_a = m.group("a") or m.group("a2")
        raw_b = m.group("b") or m.group("b2")
        try:
            a = float(raw_a)
            b = float(raw_b)
        except (TypeError, ValueError):
            continue
        if a < 30000 or b < 30000 or a > 60000 or b > 60000:
            continue
        lo, hi = (a, b) if a <= b else (b, a)
        # 區間太寬／太窄都不像回測帶（防誤抓無關兩價）
        if hi - lo < 80.0 or hi - lo > 6000.0:
            continue
        last = (lo, hi)
    return last


def _parse_retest_single_min(blob: str) -> Optional[float]:
    """單點「至少回測 N」→ 回測最低；無區間時才用。"""
    s = str(blob or "")
    if not s.strip():
        return None
    last: Optional[float] = None
    for m in _RETEST_SINGLE_MIN_RE.finditer(s):
        raw = m.group("v") or m.group("v2")
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if 30000 <= v <= 60000:
            last = v
    return last


def _retest_avg_min_from_text(blob: str) -> Optional[Dict[str, float]]:
    """回測平均／回測最低：區間優先；只有單點「至少回測」則平均＝最低＝該點。"""
    band = _parse_retest_band_lo_hi(blob)
    if band is not None:
        lo, hi = band
        return {
            "lo": float(lo),
            "hi": float(hi),
            "min": float(lo),
            "avg": float(round((lo + hi) / 2.0, 1)),
        }
    single = _parse_retest_single_min(blob)
    if single is not None:
        v = float(single)
        return {"lo": v, "hi": v, "min": v, "avg": v}
    return None


def _retest_avg_min_from_pack(
    pack: Optional[Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    """題旨包／pred 取當令回測平均＋最低（後文最新）。"""
    blob = " ".join(
        str(x or "")
        for x in (
            (pack or {}).get("snippet"),
            (pack or {}).get("thesis"),
            (pack or {}).get("wait_struct"),
            (pack or {}).get("wait"),
        )
    )
    got = _retest_avg_min_from_text(blob)
    if got is not None:
        return got
    avg_lv = None
    min_lv = None
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            role = str(row.get("role") or "")
            lv = float(row.get("level") or 0)
        except (TypeError, ValueError):
            continue
        if role == "回測平均":
            avg_lv = lv
        elif role == "回測最低":
            min_lv = lv
    if avg_lv is not None and min_lv is not None:
        lo, hi = (min_lv, avg_lv) if min_lv <= avg_lv else (avg_lv, min_lv)
        # 平均在中間時：用 2*avg-min 還原 hi
        if abs(avg_lv - min_lv) > 1.0:
            hi = float(round(2.0 * avg_lv - min_lv, 1))
            lo = float(min_lv)
        return {
            "lo": float(lo),
            "hi": float(hi),
            "min": float(min_lv),
            "avg": float(avg_lv),
        }
    if min_lv is not None:
        return {
            "lo": float(min_lv),
            "hi": float(min_lv),
            "min": float(min_lv),
            "avg": float(min_lv),
        }
    return None


def _text_has_low_band_419_427(blob: str) -> bool:
    """相容舊呼叫：文內是否有回測／低點雙價區間。"""
    return _parse_retest_band_lo_hi(blob) is not None


def _pack_has_low_band_419_427(pack: Optional[Dict[str, Any]]) -> bool:
    """題旨／等待／pred 是否已有回測區間（或平均／最低兩標）。"""
    return _retest_avg_min_from_pack(pack) is not None


def _text_has_c3_pressure_break(blob: str) -> bool:
    """後文改口：夜盤過 C3（第二組）下降壓力線 → 週五低不再假跌破／改回測下降壓。

    不准把止跌確認當令的「再測一次假跌破」誤當這段改口；
    也不准把舊文「穿刺下降壓力線（約49200）」誤觸。
    """
    s = str(blob or "")
    if not s.strip():
        return False
    has_break = bool(
        re.search(
            r"夜盤已經過.{0,40}下降壓力線|"
            r"過.{0,12}(?:第二組)?(?:整組)?\s*C\s*[-–]?\s*3.{0,16}下降壓力線|"
            r"(?:突破|破壞).{0,16}(?:第二組)?.{0,8}C\s*[-–]?\s*3.{0,16}下降壓力線|"
            r"夜盤已經過第二組.{0,24}下降壓力線",
            s,
        )
    )
    has_no_fake = bool(
        re.search(
            r"(?:上)?週[五底].{0,16}低點.{0,20}不可能(?:再)?假跌破|"
            r"也不可能假跌破了|"
            r"不可能(?:再)?假跌破了?",
            s,
        )
    )
    has_retest = bool(
        re.search(r"回測下降壓力線|拉回回測下降|回測.{0,8}下降壓", s)
    )
    return bool(has_break and (has_no_fake or has_retest))


def _text_has_foot2_revision(blob: str) -> bool:
    """是否為 37000~37500／看不到37000以下／第二隻腳（1-2轉1-3-1）改口。"""
    s = str(blob or "")
    if not s.strip():
        return False
    has_band = bool(
        re.search(r"37000\s*[-~～到至\-]\s*37500|37000.{0,8}37500", s)
    )
    has_floor = bool(re.search(r"看不到\s*37000\s*以下", s))
    has_leg = bool(
        re.search(
            r"第二隻腳|第二支腳|"
            r"1\s*[-–]?\s*2\s*轉\s*1\s*[-–]?\s*3\s*[-–]?\s*1",
            s,
        )
    )
    return bool(has_band or (has_floor and has_leg) or (has_floor and has_band))


def _text_has_stop_low_confirm(blob: str) -> bool:
    """後文止跌／週五低確認（11/9）：壓前文 B-b 雙軌／第二隻腳／C9 低點區。

    例：C3-5＋1 4重疊・確認上週五低＝最低；大盤止跌／已經落底・再測假跌破。
    不准把 11/5「1 4重疊＋假跌破」誤當止跌確認（那時還在走 3-5／假跌破觀察）。
    """
    s = str(blob or "")
    if not s.strip():
        return False
    has_fri_low = bool(
        re.search(
            r"確認.{0,16}(?:上)?週五.{0,12}低點.{0,12}就是最低|"
            r"(?:上)?週五低點就是最低點|"
            r"確認上週五低",
            s,
        )
    )
    has_stop = bool(re.search(r"大盤止跌|不相信我大盤止跌|大盤已經落底", s))
    # C3-5＋1 4 必須再疊「確認…最低／週五低」才算；裸 1 4重疊＋假跌破不算
    has_14_confirm = bool(
        re.search(
            r"C3-5.{0,48}1\s*[-–]?\s*4\s*重疊.{0,48}"
            r"(?:確認.{0,24}(?:最低|週五)|週五.{0,12}低點.{0,12}就是最低)",
            s,
        )
    ) or bool(
        re.search(
            r"1\s*[-–]?\s*4\s*重疊.{0,24}確認.{0,24}"
            r"(?:上)?週五.{0,16}(?:低點)?(?:就是)?最低",
            s,
        )
    )
    return bool(has_fri_low or has_stop or has_14_confirm)


def _text_has_bb_dual_path(blob: str) -> bool:
    """後文雙軌：五波跌完走 B-b（主）＋不排除九波擴延（備）。

    以他說話時間序為準（date+time）；後文壓前文第二隻腳當主線題旨。
    例：11/8「5波跌完走B-b／假跌破37837／9波擴延→35579→31705」。
    若已有下降壓改口／止跌／週五低確認後文，不算雙軌當令（後文壓前文）。
    """
    s = str(blob or "")
    if not s.strip():
        return False
    if _text_has_c3_pressure_break(s) or _text_has_stop_low_confirm(s):
        return False
    has_bb = bool(
        re.search(
            r"5\s*波\s*跌完.{0,12}B\s*[-–]?\s*b|"
            r"走\s*B\s*[-–]?\s*b|"
            r"波浪理論\s*5\s*波\s*跌完",
            s,
            re.I,
        )
    )
    has_fri = bool(re.search(r"37837", s)) and bool(
        re.search(r"假跌破|破壞.{0,8}3\s*[-–]?\s*5|3\s*[-–]?\s*5.{0,8}下跌脈動", s)
    )
    has_9alt = bool(re.search(r"9\s*波\s*擴延", s)) and bool(
        re.search(r"35579|31705|第二組下跌", s)
    )
    return bool(has_bb or (has_fri and has_9alt) or (has_bb and has_9alt))


def _text_has_c9_extension(blob: str) -> bool:
    """是否為 9波擴延／C-7→C-8／C-9／35500~37300 改口題旨。

    不准把 B-b 雙軌裡「不排除走9波擴延」誤當 C9 結構題旨去蓋後文下降壓／止跌確認。
    """
    s = str(blob or "")
    if not s.strip():
        return False
    if _text_has_c3_pressure_break(s) or _text_has_stop_low_confirm(s):
        return False
    has_band = bool(re.search(r"35500\s*[-~～到至]\s*37300|35500.{0,8}37300", s))
    has_9 = bool(re.search(r"9\s*波\s*擴延", s))
    has_c78 = bool(
        re.search(
            r"C\s*[-–]\s*7.{0,24}(?:轉|->|→|走完).{0,16}C\s*[-–]\s*8|"
            r"C\s*[-–]\s*7.{0,12}C\s*[-–]\s*8|"
            r"七走完|準備往\s*八|往八走|C-7轉C-8",
            s,
        )
    )
    has_c9 = bool(re.search(r"C\s*[-–]\s*9", s))
    # 雙軌備線口中的裸「9波擴延」≠ C-7→C-9 結構改口
    if _text_has_bb_dual_path(s) and not (has_c78 or has_c9 or has_band):
        return False
    return bool(
        (has_9 and (has_c78 or has_c9 or has_band))
        or (has_c78 and (has_c9 or has_band))
        or (has_band and (has_c78 or has_c9 or has_9))
    )

def _find_c9_extension_snip(
    db_path: str, cap_ymd: str, *, include_oral: bool = True
) -> str:
    """庫內近窗掃 9波擴延／35500~37300（後文改口可壓舊 C3-5）。

    include_oral=False：略過 oral-c9-band（題旨組裝時口頭只准補空窗，不准蓋真文）。
    """
    cap = _ymd(cap_ymd)
    if not db_path or not cap:
        return ""
    ensure_tables(db_path)
    # 1) level snaps
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT post_id, snippet FROM biaoke_level_snaps "
                "WHERE as_of<=? ORDER BY as_of DESC, created_at DESC LIMIT 12",
                (cap,),
            ).fetchall()
        finally:
            conn.close()
        for post_id, snip in rows or ():
            if (not include_oral) and str(post_id or "") == "oral-c9-band":
                continue
            if _text_has_c9_extension(str(snip or "")):
                return str(snip or "").strip()
    except Exception:
        logger.debug("掃 C9 snap 略過", exc_info=True)
    # 2) 公開主文／自回
    try:
        cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}"
        since = (
            datetime.strptime(cap, "%Y%m%d") - timedelta(days=21)
        ).strftime("%Y-%m-%d")
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT text FROM biaoke_posts WHERE date>=? AND date<=? "
                "AND (text LIKE '%35500%' OR text LIKE '%9波擴延%' "
                "OR text LIKE '%C-7%' OR text LIKE '%C-9%') "
                "ORDER BY date DESC, time DESC LIMIT 20",
                (since, cap_dash),
            ).fetchall()
        finally:
            conn.close()
        for (text,) in rows or ():
            if _text_has_c9_extension(str(text or "")):
                return str(text or "").strip()
    except Exception:
        logger.debug("掃 C9 貼文略過", exc_info=True)
    return ""


def _ensure_c9_oral_thesis_snap(db_path: str, *, as_of: str = "") -> None:
    """題旨庫若還沒有 C9／35500~37300：寫入已確認口頭題旨（只補缺，不准蓋他更新文）。

    只在 as_of≥確認日才補；口頭 snap 固定 as_of＝確認日，不准用更早 cap 回填蓋歷史題旨。
    """
    if not db_path:
        return
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    if not day or day < _C9_ORAL_AS_OF:
        return
    if _find_c9_extension_snip(db_path, day):
        return
    oral_day = _C9_ORAL_AS_OF
    try:
        _upsert_snap(
            db_path,
            post_id="oral-c9-band",
            as_of=oral_day,
            post_date=f"{oral_day[:4]}-{oral_day[4:6]}-{oral_day[6:8]}",
            post_time="13:30",
            snippet=_C9_ORAL_SNIP,
            chart_path="",
        )
    except Exception:
        logger.debug("補 C9 口頭題旨 snap 略過", exc_info=True)


def _find_foot2_snip(
    db_path: str, cap_ymd: str, *, include_oral: bool = True
) -> str:
    """庫內近窗掃 37000~37500／第二隻腳改口（後文可壓 C9 低點區）。

    include_oral=False：略過 oral-foot2-37000（真文優先時用）。
    """
    cap = _ymd(cap_ymd)
    if not db_path or not cap:
        return ""
    ensure_tables(db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT post_id, snippet FROM biaoke_level_snaps "
                "WHERE as_of<=? ORDER BY as_of DESC, created_at DESC LIMIT 12",
                (cap,),
            ).fetchall()
        finally:
            conn.close()
        for post_id, snip in rows or ():
            if (not include_oral) and str(post_id or "") == _FOOT2_ORAL_POST_ID:
                continue
            if _text_has_foot2_revision(str(snip or "")):
                return str(snip or "").strip()
    except Exception:
        logger.debug("掃第二隻腳 snap 略過", exc_info=True)
    try:
        cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}"
        since = (
            datetime.strptime(cap, "%Y%m%d") - timedelta(days=21)
        ).strftime("%Y-%m-%d")
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT text FROM biaoke_posts WHERE date>=? AND date<=? "
                "AND (text LIKE '%37000%' OR text LIKE '%37500%' "
                "OR text LIKE '%第二隻腳%' OR text LIKE '%第二支腳%' "
                "OR text LIKE '%1-2轉1-3-1%') "
                "ORDER BY date DESC, time DESC LIMIT 20",
                (since, cap_dash),
            ).fetchall()
        finally:
            conn.close()
        for (text,) in rows or ():
            if _text_has_foot2_revision(str(text or "")):
                return str(text or "").strip()
    except Exception:
        logger.debug("掃第二隻腳貼文略過", exc_info=True)
    return ""


def _ensure_foot2_oral_thesis_snap(db_path: str, *, as_of: str = "") -> None:
    """題旨庫若還沒有 37000~37500／第二隻腳：寫入已確認口頭改口（只補缺）。

    只在 as_of≥確認日才補；口頭 snap 固定 as_of＝確認日。
    """
    if not db_path:
        return
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    if not day or day < _FOOT2_ORAL_AS_OF:
        return
    if _find_foot2_snip(db_path, day):
        return
    oral_day = _FOOT2_ORAL_AS_OF
    try:
        _upsert_snap(
            db_path,
            post_id=_FOOT2_ORAL_POST_ID,
            as_of=oral_day,
            post_date=f"{oral_day[:4]}-{oral_day[4:6]}-{oral_day[6:8]}",
            post_time="13:30",
            snippet=_FOOT2_ORAL_SNIP,
            chart_path="",
        )
    except Exception:
        logger.debug("補第二隻腳口頭題旨 snap 略過", exc_info=True)


def _find_pressure_break_snip(
    db_path: str, cap_ymd: str, *, include_oral: bool = True
) -> str:
    """庫內近窗掃 C3 下降壓改口（後文可壓「再測週五低／假跌破」）。

    include_oral=False：略過 oral-c3-pressure-break（真文優先時用）。
    """
    cap = _ymd(cap_ymd)
    if not db_path or not cap:
        return ""
    ensure_tables(db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT post_id, snippet FROM biaoke_level_snaps "
                "WHERE as_of<=? ORDER BY as_of DESC, created_at DESC LIMIT 12",
                (cap,),
            ).fetchall()
        finally:
            conn.close()
        for post_id, snip in rows or ():
            if (not include_oral) and str(post_id or "") == _PRESSURE_BREAK_ORAL_POST_ID:
                continue
            if _text_has_c3_pressure_break(str(snip or "")):
                return str(snip or "").strip()
    except Exception:
        logger.debug("掃下降壓改口 snap 略過", exc_info=True)
    try:
        cap_dash = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}"
        since = (
            datetime.strptime(cap, "%Y%m%d") - timedelta(days=21)
        ).strftime("%Y-%m-%d")
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            rows = conn.execute(
                "SELECT text FROM biaoke_posts WHERE date>=? AND date<=? "
                "AND (text LIKE '%下降壓力%' OR text LIKE '%不可能假跌破%' "
                "OR text LIKE '%回測下降%') "
                "ORDER BY date DESC, time DESC LIMIT 20",
                (since, cap_dash),
            ).fetchall()
        finally:
            conn.close()
        for (text,) in rows or ():
            if _text_has_c3_pressure_break(str(text or "")):
                return str(text or "").strip()
    except Exception:
        logger.debug("掃下降壓改口貼文略過", exc_info=True)
    return ""


def _ensure_pressure_break_oral_thesis_snap(db_path: str, *, as_of: str = "") -> None:
    """題旨庫若還沒有 C3 下降壓改口：寫入已確認口頭；口頭缺 37837 則覆寫補齊。

    只在 as_of≥確認日才補；口頭 snap 固定 as_of＝確認日。
    真文已含改口時不強制覆寫口頭（真文優先）。
    """
    if not db_path:
        return
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    if not day or day < _PRESSURE_BREAK_ORAL_AS_OF:
        return
    real = _find_pressure_break_snip(db_path, day, include_oral=False)
    if real and _text_has_c3_pressure_break(real):
        return
    oral_day = _PRESSURE_BREAK_ORAL_AS_OF
    try:
        _upsert_snap(
            db_path,
            post_id=_PRESSURE_BREAK_ORAL_POST_ID,
            as_of=oral_day,
            post_date=f"{oral_day[:4]}-{oral_day[4:6]}-{oral_day[6:8]}",
            post_time="19:00",
            snippet=_PRESSURE_BREAK_ORAL_SNIP,
            chart_path="",
        )
    except Exception:
        logger.debug("補下降壓改口口頭題旨 snap 略過", exc_info=True)


def _ensure_retest_41500_oral_thesis_snap(db_path: str, *, as_of: str = "") -> None:
    """題旨庫補 11/10 口頭：至少回測 41500；絕對不破上週五低。"""
    if not db_path:
        return
    day = _ymd(as_of) or datetime.now(TAIPEI).strftime("%Y%m%d")
    if not day or day < _RETEST_41500_ORAL_AS_OF:
        return
    oral_day = _RETEST_41500_ORAL_AS_OF
    try:
        _upsert_snap(
            db_path,
            post_id=_RETEST_41500_ORAL_POST_ID,
            as_of=oral_day,
            post_date=f"{oral_day[:4]}-{oral_day[4:6]}-{oral_day[6:8]}",
            post_time="11:48",
            snippet=_RETEST_41500_ORAL_SNIP,
            chart_path="",
        )
    except Exception:
        logger.debug("補41500回測口頭題旨 snap 略過", exc_info=True)


def _ensure_low_band_419_427_oral_thesis_snap(db_path: str, *, as_of: str = "") -> None:
    """題旨庫補 11/12 口頭：低點帶 41900～42700；路徑先到 43000 下。"""
    if not db_path:
        return
    day = str(as_of or "").replace("-", "")[:8]
    if not day or day < _LOW_BAND_419_427_ORAL_AS_OF:
        return
    oral_day = _LOW_BAND_419_427_ORAL_AS_OF
    try:
        _upsert_snap(
            db_path,
            post_id=_LOW_BAND_419_427_ORAL_POST_ID,
            as_of=oral_day,
            post_date=f"{oral_day[:4]}-{oral_day[4:6]}-{oral_day[6:8]}",
            post_time="13:05",
            snippet=_LOW_BAND_419_427_ORAL_SNIP,
            chart_path="",
        )
    except Exception:
        logger.debug("補41900～42700低點帶口頭題旨 snap 略過", exc_info=True)


# 主圖／右下九波縮圖共用色（C1…C9）：奇數浪偏暖紅、偶數浪偏冷青／綠，C7 最醒目，虛線 C9 淡紫
_C9_WAVE_COLORS: Dict[str, str] = {
    "B": "#ffd54f",
    "C1": "#ff7043",
    "C2": "#ffca28",
    "C3": "#ff8a65",
    "C4": "#66bb6a",
    "C5": "#ec407a",
    "C6": "#29b6f6",
    "C7": "#ff1744",
    "C8": "#ffc107",
    "C9": "#ce93d8",
}


def _c9_wave_color(lab: str) -> str:
    return str(_C9_WAVE_COLORS.get(str(lab or "").strip(), "#ff8a80"))


def _c9_ext_bar_pivots(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    i_bhi: int,
    i_now: int,
    tf: str = "1d",
) -> List[Tuple[int, float, str]]:
    """C 段 9 波擴延：用官方柱 zigzag 找 B→C1…C7／C8（價只取官方高低）。

    奇數浪＝低點、偶數浪＝反彈高。口述＝七走完、準備往八 → 60分優先讓末日落在 C7。
    tf＝60：加權日盤 60 分（超近窗）；1d＝日K。不准發明中間價。
    """
    import math

    n = min(len(highs), len(lows), len(closes))
    if not (0 <= int(i_bhi) < int(i_now) < n):
        return []
    ib, i_end = int(i_bhi), int(i_now)
    try:
        yb = float(highs[ib])
    except (TypeError, ValueError):
        return []
    ranges: List[float] = []
    for i in range(ib, i_end + 1):
        try:
            hi_r = float(highs[i])
            lo_r = float(lows[i])
        except (TypeError, ValueError):
            continue
        # 缺日／對齊空格（台指夜盤稀疏軸）不准進 ATR
        if not (math.isfinite(hi_r) and math.isfinite(lo_r)):
            continue
        ranges.append(abs(hi_r - lo_r))
    atr = (
        sorted(ranges)[len(ranges) // 2]
        if ranges
        else max(180.0, abs(yb) * 0.008)
    )

    def _run(thr: float) -> List[Tuple[int, float, str]]:
        out: List[Tuple[int, float, str]] = [(ib, yb, "B")]
        looking_low = True  # C1 先找低
        ext_i, ext_y = ib, yb
        wave = 0
        for i in range(ib + 1, i_end + 1):
            try:
                hi = float(highs[i])
                lo = float(lows[i])
            except (TypeError, ValueError):
                continue
            # 夜盤對齊加權日軸會有 NaN 空格：跳過，不准當轉折
            if not (math.isfinite(hi) and math.isfinite(lo)):
                continue
            if looking_low:
                if lo <= ext_y:
                    ext_i, ext_y = i, lo
                elif hi >= ext_y + thr:
                    wave += 1
                    out.append((int(ext_i), float(ext_y), f"C{wave}"))
                    looking_low = False
                    ext_i, ext_y = i, hi
                    if wave >= 8:
                        break
            else:
                if hi >= ext_y:
                    ext_i, ext_y = i, hi
                elif lo <= ext_y - thr:
                    wave += 1
                    out.append((int(ext_i), float(ext_y), f"C{wave}"))
                    looking_low = True
                    ext_i, ext_y = i, lo
                    if wave >= 8:
                        break
        # 收尾：未確認極端入列（今多半 C7 低；八還沒走出就不硬湊 C8）
        if wave < 8 and ext_i > out[-1][0]:
            wave += 1
            out.append((int(ext_i), float(ext_y), f"C{wave}"))
        if out and out[-1][0] < i_end and wave < 8:
            try:
                y_last = (
                    float(lows[i_end])
                    if looking_low or wave % 2 == 0
                    else float(closes[i_end])
                )
            except (TypeError, ValueError):
                y_last = float(closes[i_end])
            pi, py, plab = out[-1]
            if abs(i_end - pi) <= 1 and abs(y_last - py) < thr * 0.35:
                out[-1] = (i_end, y_last, plab)
            else:
                wave += 1
                out.append((i_end, y_last, f"C{wave}"))
        trimmed: List[Tuple[int, float, str]] = []
        for row in out:
            lab = str(row[2])
            if lab == "B":
                trimmed.append(row)
                continue
            try:
                num = int(lab.lstrip("C"))
            except ValueError:
                continue
            if num <= 8:
                trimmed.append(row)
        return trimmed

    if str(tf) == "60":
        # 七走完＝窗內官方最低當 C7；其前剛好 C1…C6。不准把之後反彈收當 C7。
        i_lo = min(range(ib, i_end + 1), key=lambda i: float(lows[i]))
        y_lo = float(lows[i_lo])
        cands: List[Tuple[float, float, List[Tuple[int, float, str]]]] = []
        for mult in (3.2, 3.6, 4.0, 4.2, 4.4, 4.8, 5.2):
            thr = max(float(atr) * mult, abs(yb) * 0.018, 900.0)
            # 只切到絕對低之前，目標 C1…C6
            out_pre: List[Tuple[int, float, str]] = [(ib, yb, "B")]
            looking_low = True
            ext_i, ext_y = ib, yb
            wave = 0
            stop = max(ib + 1, i_lo - 1)
            for i in range(ib + 1, stop + 1):
                try:
                    hi = float(highs[i])
                    lo = float(lows[i])
                except (TypeError, ValueError):
                    continue
                if not (math.isfinite(hi) and math.isfinite(lo)):
                    continue
                if looking_low:
                    if lo <= ext_y:
                        ext_i, ext_y = i, lo
                    elif hi >= ext_y + thr:
                        wave += 1
                        out_pre.append((int(ext_i), float(ext_y), f"C{wave}"))
                        looking_low = False
                        ext_i, ext_y = i, hi
                        if wave >= 6:
                            break
                else:
                    if hi >= ext_y:
                        ext_i, ext_y = i, hi
                    elif lo <= ext_y - thr:
                        wave += 1
                        out_pre.append((int(ext_i), float(ext_y), f"C{wave}"))
                        looking_low = True
                        ext_i, ext_y = i, lo
                        if wave >= 6:
                            break
            if wave == 5 and ext_i < i_lo and not looking_low:
                # 差 C6：取 C5 後、絕對低前最高為 C6
                i5 = out_pre[-1][0]
                if i5 < i_lo:
                    i6 = max(range(i5, i_lo), key=lambda j: float(highs[j]))
                    out_pre.append((int(i6), float(highs[i6]), "C6"))
                    wave = 6
            if wave < 6:
                # 門檻不合适：退回全窗 _run 再截斷
                full = _run(thr)
                out_pre = [(i, y, lab) for i, y, lab in full if lab == "B" or i < i_lo]
                wave = sum(1 for _i, _y, lab in out_pre if str(lab).startswith("C"))
            if wave >= 6:
                # 只留到 C6，再釘 C7＝絕對低
                trimmed = []
                for i, y, lab in out_pre:
                    if lab == "B":
                        trimmed.append((i, y, lab))
                        continue
                    try:
                        num = int(str(lab).lstrip("C"))
                    except ValueError:
                        continue
                    if num <= 6:
                        trimmed.append((i, y, lab))
                trimmed.append((int(i_lo), float(y_lo), "C7"))
                # 品質：C7 必須低於 C5；C6 愈靠近 C7 愈好（避免 5～7 擠怪／過早收束）
                labs = {lab: (i, y) for i, y, lab in trimmed}
                score = 50.0
                if "C5" in labs and labs["C7"][1] < labs["C5"][1] - 1.0:
                    score += 40.0
                else:
                    score -= 40.0
                if "C6" in labs and "C7" in labs:
                    span = max(1, labs["C7"][0] - ib)
                    score += 35.0 * (labs["C6"][0] - ib) / span
                    # C6→C7 至少隔一日盤（≥2根），但不要隔整段窗
                    gap67 = labs["C7"][0] - labs["C6"][0]
                    if 2 <= gap67 <= 40:
                        score += 18.0
                    elif gap67 == 1:
                        score -= 8.0
                idxs = [i for i, _y, lab in trimmed if lab != "B"]
                if len(idxs) >= 2:
                    gaps = [idxs[k + 1] - idxs[k] for k in range(len(idxs) - 1)]
                    score += min(gaps) * 0.35 + (sum(1 for g in gaps if g >= 2) * 2.0)
                cands.append((score, -thr, trimmed))
        if cands:
            cands.sort(reverse=True)
            return cands[0][2]
        # 保底：全窗切完，强制末錨＝絕對低當 C7
        base = [row for row in _run(max(float(atr) * 4.0, abs(yb) * 0.018, 950.0)) if row[2] == "B" or row[0] < i_lo]
        while len([r for r in base if str(r[2]).startswith("C")]) > 6:
            base.pop()
        base.append((int(i_lo), float(y_lo), "C7"))
        return base
    thr_d = max(float(atr) * 1.15, abs(yb) * 0.0075, 220.0)
    return _run(thr_d)


def _c9_path_line_spec(lab: str, style: str) -> Tuple[str, float, float]:
    """回傳 (線色, 線寬, 外描邊寬)。style＝white_thin｜color_thin｜color_bold。"""
    st = str(style or "white_thin").strip().lower()
    hot = lab in {"C7", "C8"}
    odd = lab in {"C1", "C3", "C5"}
    if st == "white_thin":
        # 細白主線：明顯細過縮圖K影線；C7／C8 略亮
        col = "#ffffff" if hot else "#e8eaf0"
        lw = 1.20 if hot else 0.95
        return col, lw, 0.70
    if st == "color_bold":
        col = _c9_wave_color(lab)
        if hot:
            lw = 3.85
        elif odd:
            lw = 3.05
        else:
            lw = 2.65
        return col, lw, 1.65
    # 預設 color_thin：留分色，線寬壓到比 K 影線細
    col = _c9_wave_color(lab)
    if hot:
        lw = 1.35
    elif odd:
        lw = 1.10
    else:
        lw = 0.95
    return col, lw, 0.75


def _paint_c9_ext_k_path(
    ax: Any,
    pivots: Sequence[Tuple[int, float, str]],
    *,
    n: int,
    fp: Any,
    tip: Optional[Dict[str, Any]] = None,
    fontsize: float = 9,
    style: str = "white_thin",
) -> bool:
    """主圖 K：B→C1…C8 折線＋浪號釘點；C9 只走預估虛線端。

    style：white_thin（預設・細白）｜color_thin（分色細線）｜color_bold（舊粗分色）。
    """
    rows = [(int(i), float(y), str(lab)) for i, y, lab in (pivots or [])]
    if len(rows) < 3:
        return False
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    st = str(style or "white_thin").strip().lower()
    # 找到 C7／C8 索引
    i_c7 = next((j for j, r in enumerate(rows) if r[2] == "C7"), None)
    i_c8 = next((j for j, r in enumerate(rows) if r[2] == "C8"), None)
    # 實線到 C7（或 C8 若已走出反彈高）
    solid_end = i_c8 if i_c8 is not None else (i_c7 if i_c7 is not None else len(rows) - 1)
    solid_end = max(1, int(solid_end))
    for j in range(solid_end):
        x0, y0, _lab0 = rows[j]
        x1, y1, lab1 = rows[j + 1]
        col, lw, edge = _c9_path_line_spec(lab1, st)
        ax.plot(
            [x0, x1],
            [y0, y1],
            color="#0b0f14",
            lw=lw + edge,
            solid_capstyle="round",
            zorder=6.3,
        )
        ax.plot(
            [x0, x1],
            [y0, y1],
            color=col,
            lw=lw,
            solid_capstyle="round",
            zorder=6.4,
        )
    # 浪號：釘 C1／C3／C5／C6／C7（C7＝七走完低點必顯）；C2／C4 省略避互壓；
    # C8 只留細圈（右欄已有「C-7轉C-8今」），不准跟 C7 字標疊成雙標。
    pin_labs = {"C1", "C3", "C5", "C6", "C7"}
    for j, (ii, yy, lab) in enumerate(rows):
        if lab == "B":
            continue
        is_hot = lab in {"C7", "C8"}
        if st == "white_thin":
            col = "#ff8a80" if is_hot else "#f5f5f5"
        else:
            col = _c9_wave_color(lab)
        # 矛點只一圈細線；C7／C8 不准實心＋外圈疊成雙圈
        if is_hot:
            _spear_ring(ax, ii, yy, color=col, zorder=8.8, hot=True)
        else:
            ax.scatter(
                [ii],
                [yy],
                s=22,
                c=col,
                zorder=8.7,
                edgecolors="#0b0f14",
                linewidths=0.35,
            )
        # C8 只留細圈；C1…C7 字標釘在對應高低尖（貼浪點，不准飄遠）
        if lab == "C8" or lab not in pin_labs:
            continue
        odd = lab in {"C1", "C3", "C5", "C7"}
        tip_side = "low" if odd else "high"
        try:
            _ylo, _yhi = ax.get_ylim()
            _cspan = max(float(_yhi) - float(_ylo), 1.0)
        except Exception:
            _cspan = max(abs(float(yy)) * 0.08, 1.0)
        _pin_pivot_name(
            ax,
            int(ii),
            float(yy),
            lab,
            col,
            fp,
            side="left" if odd else "right",
            tip=tip_side,
            n=n,
            # 貼尖點：水平微讓、垂直只留 bbox 呼吸（絕對點數上限，遠窗大價窗不准再漂幾百點）
            pad_x=0.38 if lab == "C7" else 0.48,
            fontsize=max(7.5, float(fontsize) - (0.0 if lab == "C7" else 0.5)),
            pri=10 if lab == "C7" else 8,
            clear_dy=min(
                max(_cspan * (0.012 if lab == "C7" else 0.018), 55.0),
                160.0 if lab == "C7" else 220.0,
            ),
        )
    # C9 只標在預估虛線端，不准拿已走柱冒充
    if tip is not None:
        try:
            fx = float(tip.get("fut_x"))
            fy = float(tip.get("fut_y"))
        except (TypeError, ValueError):
            return True
        last_i, last_y = xs[-1], ys[-1]
        c9_col = "#ce93d8" if st != "white_thin" else "#e1bee7"
        c9_lw = 1.35 if st != "color_bold" else 2.15
        ax.plot(
            [last_i, fx],
            [last_y, fy],
            color="#0b0f14",
            lw=c9_lw + 0.9,
            ls=(0, (4.0, 2.0)),
            zorder=6.45,
        )
        ax.plot(
            [last_i, fx],
            [last_y, fy],
            color=c9_col,
            lw=c9_lw,
            ls=(0, (4.0, 2.0)),
            zorder=6.5,
        )
        _spear_ring(ax, fx, fy, color=c9_col, zorder=8.9, hot=True)
        # C9 預估標釘在虛線端點下方偏左，不准跟右欄飆預測互壓
        _pin_pivot_name(
            ax,
            fx,
            fy,
            "C9（預估）",
            c9_col,
            fp,
            side="left",
            tip="low",
            n=n,
            pad_x=0.85,
            fontsize=max(8.0, float(fontsize) - 0.5),
            pri=12,
            clear_dy=None,
            zorder=12,
        )
    return True


def _paint_c9_extension_on_bars(
    ax: Any,
    *,
    pack: Optional[Dict[str, Any]],
    i_now: int,
    y_now: float,
    n: int,
    fp: Any,
    tip: Optional[Dict[str, Any]] = None,
    pin_now: bool = True,
    side: str = "left",
    fontsize: float = 9,
    pivots: Optional[Sequence[Tuple[int, float, str]]] = None,
    style: str = "",
) -> bool:
    """三窗 K：有官方轉折就釘 C1…C8＋虛線 C9；否則只留此刻／C9 人話標。"""
    if not _c9_extension_active(pack):
        return False
    # 預設細白（話筒較清楚）；pack／環境可覆寫 color_thin｜color_bold 做對照
    st = (
        str(style or "").strip()
        or str((pack or {}).get("_c9_path_style") or "").strip()
        or str(os.environ.get("WAYNE_C9_PATH_STYLE") or "").strip()
        or "white_thin"
    )
    if pivots and _paint_c9_ext_k_path(
        ax, pivots, n=n, fp=fp, tip=tip, fontsize=fontsize, style=st
    ):
        # C1…C8 已釘在 K 上＋右欄有「C-7轉C-8今」→ 不准再塞長口頭句互壓
        return True
    if pin_now:
        _pin_pivot_name(
            ax,
            int(i_now),
            float(y_now),
            "七完・還有八上→九下（今・預估）",
            "#ea80fc",
            fp,
            side=side,
            tip="mid",
            n=n,
            pad_x=0.5,
            fontsize=fontsize,
        )
    if tip is not None:
        try:
            fx = float(tip.get("fut_x"))
            fy = float(tip.get("fut_y"))
        except (TypeError, ValueError):
            return True
        _pin_pivot_name(
            ax,
            fx,
            fy,
            "→C-9（預估・跌完＝這段完）",
            "#ce93d8",
            fp,
            side="left",
            tip="low",
            n=n,
            pad_x=0.85,
            fontsize=max(8.0, float(fontsize) - 0.5),
            pri=12,
            zorder=12,
        )
    return True


def _tw_active_low_zone(
    pack: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[float, float, str]]:
    """現行低點區：(lo, hi, kind)；kind＝week_bot｜foot2｜c9。

    雙軌當令：下週底部 37100~39000 優先於改口 37000~37500／C9 35500~37300。
    """
    preds = ((pack or {}).get("pred_levels") or {}).get("tw") or []
    w_hi = w_lo = f_hi = f_lo = c_hi = c_lo = None
    for row in preds:
        role = str(row.get("role") or "")
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if role == "下週底上沿" or (
            "下週底" in role and abs(lv - 39000.0) < 1.0
        ):
            w_hi = lv
        elif role == "下週底下沿" or (
            "下週底" in role and abs(lv - 37100.0) < 1.0
        ):
            w_lo = lv
        elif role == "改口低上沿" or (
            role.startswith("改口") and abs(lv - 37500.0) < 1.0
        ):
            f_hi = lv
        elif role == "改口低下沿" or (
            role.startswith("改口") and abs(lv - 37000.0) < 1.0
        ):
            f_lo = lv
        elif role == "C9低上沿" or abs(lv - 37300.0) < 1.0:
            c_hi = lv
        elif role == "C9低下沿" or abs(lv - 35500.0) < 1.0:
            c_lo = lv
    # 無 role 時：改口兩端純數字備援（僅當題旨已是改口）
    if (f_hi is None or f_lo is None) and _tw_has_foot2_low_zone(pack):
        for row in preds:
            try:
                lv = float(row.get("level"))
            except (TypeError, ValueError):
                continue
            if abs(lv - 37500.0) < 1.0:
                f_hi = lv
            elif abs(lv - 37000.0) < 1.0:
                f_lo = lv
    # 雙軌／原文有 37100~39000：無 role 也認兩端
    if w_hi is None or w_lo is None:
        blob = " ".join(
            str(x or "")
            for x in (
                (pack or {}).get("thesis"),
                (pack or {}).get("snippet"),
                (pack or {}).get("snippet_full"),
                (pack or {}).get("wait_struct"),
            )
        )
        if re.search(
            r"37100\s*[-~～到至\-]\s*39000|37100.{0,12}39000|最低點在\s*37100",
            blob,
        ):
            for row in preds:
                try:
                    lv = float(row.get("level"))
                except (TypeError, ValueError):
                    continue
                if abs(lv - 39000.0) < 1.0:
                    w_hi = lv
                elif abs(lv - 37100.0) < 1.0:
                    w_lo = lv
            if w_hi is None:
                w_hi = 39000.0
            if w_lo is None:
                w_lo = 37100.0
    if w_hi is not None and w_lo is not None and float(w_hi) > float(w_lo):
        return (float(w_lo), float(w_hi), "week_bot")
    if f_hi is not None and f_lo is not None and float(f_hi) > float(f_lo):
        return (float(f_lo), float(f_hi), "foot2")
    if c_hi is not None and c_lo is not None and float(c_hi) > float(c_lo):
        return (float(c_lo), float(c_hi), "c9")
    return None


# 下週底黃標／AI結束觀察標：同一左緣齊頭（同 pad＋ha=left）
# 遠／近：必須在九波縮圖右緣外（縮圖是另開 axes，zorder 壓不住 → 左半會被裁成「5,579」）
# 超近：縮圖在中排右格，K 欄可更左；再左避末根K
_TEACH_ZONE_LABEL_X = 0.48  # 遠窗：縮圖在左下，標在右外側
_TEACH_ZONE_LABEL_X_NEAR = 0.34  # 近窗：右挪離開大A末／7/29 尖點，仍在縮圖左側
_TEACH_ZONE_LABEL_X_MICRO = 0.22  # 超近：清過左欄壓(0.01)／撐(0.13)，不准黃框蓋「下一層撐」
_TEACH_ZONE_LABEL_PAD = 0.18  # 兩標 pad 必須相同才齊頭；大 pad 會蓋 A低／7/29
_TEACH_ZONE_LABEL_W_AX = 0.26  # 長標約佔 axes 寬（估），用來判斷能否完全放在縮圖左側


def _reserve_zone_label_avoid(
    ax: Any,
    *,
    x_ax: float,
    y: float,
    lo: float,
    hi: float,
) -> None:
    """區帶大標佔位 → data 禁區；尖點浪名／A低／7/29 不准坐進框內。"""
    if ax is None:
        return
    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
    except Exception:
        return
    xspan = max(float(x1) - float(x0), 1.0)
    yspan = max(float(y1) - float(y0), 1.0)
    # yaxis_transform 的 x_ax（0–1）換成 data x；框高估帶寬＋字級呼吸
    xd0 = float(x0) + xspan * max(0.0, float(x_ax) - 0.02)
    xd1 = float(x0) + xspan * min(1.0, float(x_ax) + float(_TEACH_ZONE_LABEL_W_AX) + 0.04)
    yd0 = max(float(y0), float(y) - max((float(hi) - float(lo)) * 0.55, yspan * 0.045))
    yd1 = min(float(y1), float(y) + max((float(hi) - float(lo)) * 0.55, yspan * 0.045))
    _reserve_avoid_zone(ax, xd0, yd0, xd1, yd1)


def _zone_label_x_clear_of_inset(
    ax: Any,
    fig: Any,
    inset_rect: Optional[Tuple[float, float, float, float]],
    *,
    fallback: float,
    gap_ax: float = 0.028,
) -> float:
    """區帶兩標共用 x（yaxis_transform 0–1）：兩標齊頭，全文不被九波縮圖裁字。

    若 fallback 整段標可完全落在縮圖左側 → 用 fallback（近窗靠左）。
    否則貼縮圖右緣外側（遠窗縮圖在左下）。
    """
    try:
        fb = float(fallback)
    except (TypeError, ValueError):
        fb = float(_TEACH_ZONE_LABEL_X)
    if not inset_rect:
        return max(0.04, min(0.62, fb))
    try:
        pos = ax.get_position()
        pw = max(float(pos.width), 1e-9)
        ins_l, _ins_b, ins_w, _ins_h = (float(x) for x in inset_rect)
        inset_left_ax = (ins_l - float(pos.x0)) / pw
        inset_right_ax = (ins_l + ins_w - float(pos.x0)) / pw
        # 近窗：標在左、縮圖在右 → fallback 整段不撞縮圖就用 fallback
        if float(fb) + float(_TEACH_ZONE_LABEL_W_AX) + 0.02 <= float(inset_left_ax):
            return max(0.04, min(0.55, float(fb)))
        # 否則只能讓到縮圖右側
        x_clear = float(inset_right_ax) + float(gap_ax)
        x_ax = max(float(x_clear), float(fb))
        return max(0.08, min(0.58, float(x_ax)))
    except Exception:
        return max(0.04, min(0.62, fb))


def _paint_c9_low_zone_band(
    ax: Any,
    pack: Optional[Dict[str, Any]],
    *,
    fp: Any,
    label_x: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """三窗共用：現行低點區底帶＋標。

    雙軌當令＝下週底部 37100~39000（顯眼黃框大標）；否則改口 37000~37500；再否則 C-9 35500~37300。
    他原文兩端；底帶本身非買訊（買點另釘 37837）。
    label_x：與 AI結束觀察標齊頭；超近須更左，不准壓最後一根K。
    """
    zone = _tw_active_low_zone(pack)
    if not zone:
        return None
    lo, hi, kind = zone
    if kind == "week_bot":
        # 下週預計底部：黃框仍醒目，但縮小 pad／字級，不准蓋 A低／7/29
        face, ink, tag = "#fff59d", "#fbc02d", "下週底部觀察"
        fsz, pad, lw, alpha_span = 12.0, float(_TEACH_ZONE_LABEL_PAD), 2.0, 0.22
        txt_c, fc = "#1a1400", "#ffeb3b"
    elif kind == "foot2":
        face, ink, tag = "#80deea", "#80deea", "改口低點區"
        fsz, pad, lw, alpha_span = 7.5, 0.10, 0.45, 0.16
        txt_c, fc = ink, "#0b0f14"
    else:
        face, ink, tag = "#ce93d8", "#ce93d8", "C-9低點區"
        fsz, pad, lw, alpha_span = 7.5, 0.10, 0.45, 0.16
        txt_c, fc = ink, "#0b0f14"
    # 下週底黃帶必須壓過灰「下一層」底色（0.45），不然看起來像灰帶、黃標像浮在帶外
    span_z = 0.58 if kind == "week_bot" else 0.35
    span_a = 0.32 if kind == "week_bot" else float(alpha_span)
    ax.axhspan(lo, hi, facecolor=face, alpha=span_a, zorder=span_z)
    # 區帶大標＝帶內正中（黃／紫同一做法）；大A末 tip=high 在尖點上方
    y_lab = (float(lo) + float(hi)) * 0.5
    x_lab = float(_TEACH_ZONE_LABEL_X if label_x is None else label_x)
    ax.text(
        x_lab,
        y_lab,
        f"飆預測{_px(lo)}~{_px(hi)}（{tag}）",
        transform=ax.get_yaxis_transform(),
        fontproperties=fp(fsz, "bold" if kind == "week_bot" else "normal"),
        color=txt_c if kind == "week_bot" else ink,
        ha="left",
        va="center",
        zorder=12,  # 高於左欄壓撐(11)，帶內字不准被下一層左標蓋
        bbox=dict(
            boxstyle=f"round,pad={pad}", fc=fc, ec=ink, lw=lw, alpha=0.95
        ),
        clip_on=False,
    )
    _reserve_zone_label_avoid(ax, x_ax=x_lab, y=y_lab, lo=lo, hi=hi)
    return (lo, hi)


def _tw_ai_end_zone(
    pack: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[float, float]]:
    """九波備線：35579→31705＝AI行情結束觀察帶（只認原文兩端）。"""
    preds = ((pack or {}).get("pred_levels") or {}).get("tw") or []
    hi = lo = None
    for row in preds:
        role = str(row.get("role") or "")
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if role == "九波備線破位" or abs(lv - 35579.0) < 1.0:
            hi = lv
        elif role == "九波備線深殺" or abs(lv - 31705.0) < 1.0:
            lo = lv
    if hi is None or lo is None:
        blob = " ".join(
            str(x or "")
            for x in (
                (pack or {}).get("thesis"),
                (pack or {}).get("snippet"),
                (pack or {}).get("snippet_full"),
                (pack or {}).get("wait_struct"),
            )
        )
        if re.search(r"35579", blob) and re.search(r"31705", blob):
            hi = 35579.0 if hi is None else hi
            lo = 31705.0 if lo is None else lo
    if hi is not None and lo is not None and float(hi) > float(lo):
        return (float(lo), float(hi))
    return None


def _paint_ai_end_zone_band(
    ax: Any,
    pack: Optional[Dict[str, Any]],
    *,
    fp: Any,
    label_x: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """備線最差：35579~31705 畫 AI 結束觀察帶（非買訊；右欄掛上緣35579＋深殺端31705）。

    帶內標放大；x 與下週底部觀察黃標齊頭（同 _TEACH_ZONE_LABEL_X／超近 MICRO）。
    """
    zone = _tw_ai_end_zone(pack)
    if not zone:
        return None
    lo, hi = zone
    face, ink = "#ce93d8", "#e1bee7"
    ax.axhspan(lo, hi, facecolor=face, alpha=0.16, zorder=0.56)
    # 紫標＝帶內正中（與黃下週底同一排版）
    y_lab = (float(lo) + float(hi)) * 0.5
    x_lab = float(_TEACH_ZONE_LABEL_X if label_x is None else label_x)
    # pad／ha／x 必須與下週底黃標相同，左緣才真齊頭
    ax.text(
        x_lab,
        y_lab,
        f"飆預測{_px(lo)}~{_px(hi)}（AI行情結束觀察）",
        transform=ax.get_yaxis_transform(),
        fontproperties=fp(11.5, "bold"),
        color=ink,
        ha="left",
        va="center",
        zorder=12.0,  # 與下週底同層，高於左欄壓撐，尖點 tip=high 已讓開
        bbox=dict(
            boxstyle=f"round,pad={float(_TEACH_ZONE_LABEL_PAD)}",
            fc="#140c18",
            ec=ink,
            lw=1.6,
            alpha=0.96,
        ),
        clip_on=False,
    )
    _reserve_zone_label_avoid(ax, x_ax=x_lab, y=y_lab, lo=lo, hi=hi)
    return (lo, hi)


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


def _tw_level_role(pack: Optional[Dict[str, Any]], level: float) -> str:
    """pred_levels.tw 對該價的 role；沒有就空。"""
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return ""
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            if abs(float(row.get("level")) - lv) < 0.6:
                return str(row.get("role") or "")
        except (TypeError, ValueError):
            continue
    # 原文壓力位硬釘（題旨有 41760／41500）
    if abs(lv - 41760.0) < 0.6:
        return "台指壓力"
    if abs(lv - 41500.0) < 0.6:
        # 無區間時 41500 當回測最低；有平均列則由 pred role 覆蓋
        return "回測最低"
    return ""


def _format_tw_pred_note(
    level: float,
    *,
    pack: Optional[Dict[str, Any]] = None,
    lows: Optional[Sequence[float]] = None,
    highs: Optional[Sequence[float]] = None,
) -> str:
    """加權右標／tip 錨文：壓力位保留「台指壓力」，撐／低才用飆預測＋破位。"""
    role = _tw_level_role(pack, level)
    br = _tw_pred_break_tag(
        float(level),
        list(lows or []),
        pack=pack,
        role=role,
        highs=list(highs or []) if highs is not None else None,
    )
    if role == "回測平均":
        return f"回測平均／{_px(level)}・{br}"
    if role == "回測最低":
        return f"回測最低／{_px(level)}・{br}"
    _rb_fmt = _retest_avg_min_from_pack(pack)
    _band_fmt = bool(
        _rb_fmt is not None
        and abs(float(_rb_fmt["avg"]) - float(_rb_fmt["min"])) >= 0.6
    )
    if role == "至少回測" or abs(float(level) - 41500.0) < 0.6:
        # 有當令回測帶時 41500 過期，不准再格式成回測最低
        if _band_fmt:
            return ""
        return f"回測最低／{_px(level)}・{br}"
    if role == "台指壓力" or abs(float(level) - 41760.0) < 0.6:
        lab = f"台指壓力／{_px(level)}・{br}"
        # 下降壓改口當令：水平41760 不准被讀成 C3 下降壓線
        if _pack_pressure_break_on(pack):
            lab = f"{lab}｜≠口述下降壓"
        if _band_fmt:
            lab = f"{lab}｜≠回測帶"
        else:
            _pack_blob = " ".join(
                str(x or "")
                for x in (
                    (pack or {}).get("thesis"),
                    (pack or {}).get("snippet"),
                    (pack or {}).get("snippet_full"),
                    (pack or {}).get("wait_struct"),
                )
            )
            if _text_has_retest_41500(_pack_blob) or "至少回測41500" in _pack_blob:
                lab = f"{lab}｜≠41500回測"
        return lab
    return _biaoke_pred_label(float(level), br)


def _biaoke_pred_label(
    price: float,
    tag: str = "",
    *,
    prob: Optional[float] = None,
) -> str:
    """他點過的位：標成『飆預測』＋狀態；機率只有真量化傳入才帶％（不准假％）。

    價與後綴（日期／狀態）中間固定「・」分隔，不准黏成 37,1644/23。
    """
    base = f"飆預測{_px(price)}"
    t = str(tag or "").strip()
    # 已帶分隔就不重複
    if t:
        if t[0] in "・（(／/":
            base = f"{base}{t}"
        else:
            base = f"{base}・{t}"
    if prob is None:
        return base
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return base
    if 0.0 < p <= 100.0:
        return f"{base}（{int(round(p))}%機率）"
    return base


def _official_bar_field(
    db_path: str, symbol: str, ymd: str, field: str
) -> Optional[float]:
    """官方日K 單欄（open/high/low/close）；缺柱回 None（不准假數）。"""
    d = _ymd(ymd)
    sym = str(symbol or "").upper()
    col = str(field or "").lower()
    if not db_path or not d or not sym or col not in ("open", "high", "low", "close"):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                f"SELECT {col} FROM index_daily WHERE symbol=? AND date=?",
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


def _official_bar_low(db_path: str, symbol: str, ymd: str) -> Optional[float]:
    """官方日K低；缺柱回 None（不准假數）。"""
    return _official_bar_field(db_path, symbol, ymd, "low")


def _official_bar_high(db_path: str, symbol: str, ymd: str) -> Optional[float]:
    """官方日K高；缺柱回 None（不准假數）。"""
    return _official_bar_field(db_path, symbol, ymd, "high")


def _sox_latest_px(db_path: str, *, live: Optional[Dict[str, Any]] = None) -> float:
    """費半最新價：盤中即時優先；否則 Yahoo 末日／庫內最新收（出圖對撐壓用）。"""
    try:
        px = float((live or {}).get("close") or (live or {}).get("price") or 0)
        if px > 0:
            return px
    except (TypeError, ValueError):
        pass
    try:
        bar = _fetch_yahoo_index_last_bar("^SOX")
        if bar and float(bar.get("close") or 0) > 0:
            return float(bar["close"])
    except Exception:
        pass
    if not db_path:
        return 0.0
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT close FROM index_daily WHERE symbol='SOX' "
                "AND close IS NOT NULL AND close>0 ORDER BY date DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return 0.0
    try:
        return float(row[0]) if row and row[0] is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _refresh_sox_pred_cascade(
    pred: Dict[str, Any],
    db_path: str = "",
    *,
    sox_px: float = 0.0,
) -> Dict[str, Any]:
    """費半撐壓階梯：4/28 9865 撐不住 → 回測 2/25 8498（使用者鎖死）。

    題旨原文只寫到 9865；破了之後下一層＝官方 2/25 高 8498，不准停在已破的 9865。
    """
    out = dict(pred or {})
    rows = [dict(r) for r in (out.get("sox") or [])]
    if not rows:
        return out
    px = float(sox_px or 0)
    if px <= 0:
        px = _sox_latest_px(db_path)
    nxt = next((r for r in rows if str(r.get("role") or "") == "次回測"), None)
    reb = next((r for r in rows if str(r.get("role") or "") == "再回測"), None)
    if nxt:
        try:
            lv_nxt = float(nxt.get("level") or 0)
        except (TypeError, ValueError):
            lv_nxt = 0.0
        if px > 0 and lv_nxt > 0 and px < lv_nxt - 0.5:
            nxt["tag"] = "已破"
            nxt["label"] = f"4/28低{_px(lv_nxt)}已破"
            if reb is None:
                off_hi = _official_bar_high(db_path, "SOX", "20260225")
                # 他劇本一：破9865→測2/25高8498（官方高對質）
                lv = (
                    float(off_hi)
                    if off_hi is not None and abs(float(off_hi) - 8498.0) <= 3.0
                    else 8498.0
                )
                rows.append(
                    {
                        "level": lv,
                        "ref_ymd": "20260225",
                        "ref_md": _md("20260225"),
                        "role": "再回測",
                        "tag": "未到",
                        "label": f"再回測2/25高{_px(lv)}",
                    }
                )
            else:
                # 文內已有再回測列：9865 破了就維持未到標，不准還寫次回測未到
                if str(reb.get("tag") or "") != "已破":
                    reb["tag"] = "未到"
    bits = []
    for row in (out.get("tw") or []):
        bits.append(str(row.get("label") or ""))
    for row in rows:
        bits.append(str(row.get("label") or ""))
    out["sox"] = rows
    out["note"] = "｜".join(b for b in bits if b)[:280]
    return out


def _thesis_pred_levels(snip: str, db_path: str = "") -> Dict[str, Any]:
    """從他最新題旨抽出寫死預測點＋回測日（只認原文數字，不准發明）。

    回傳 tw／sox 列：level／ref_ymd／ref_md／role／tag／label／note。
    4/28 9865 若已破 → `_refresh_sox_pred_cascade` 掛 2/25 8498。
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

    # 台指／大盤（依他最新主文＋同串回文時間序；後句改口壓前）
    if re.search(r"46292", s):
        _add(
            "tw",
            level=46292.0,
            ref_ymd="",
            role="轉震盪",
            tag="未到",
            label=f"飆預測{_px(46292)}轉震盪",
        )
    if re.search(r"45546", s):
        role = "反彈穿刺" if re.search(r"穿刺|反彈", s) else "點位"
        _add(
            "tw",
            level=45546.0,
            ref_ymd="20260916",
            role=role,
            tag="未到",
            label=f"飆預測{_px(45546)}反彈穿刺"
            if role == "反彈穿刺"
            else f"飆預測{_px(45546)}",
        )
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
    # 11/9 台指壓力 41760（他原文；止跌確認後文優先寫）
    if re.search(r"41760", s):
        _lab41760 = f"台指壓力／{_px(41760)}"
        if _text_has_c3_pressure_break(s) or (
            "不再假跌破" in s and re.search(r"下降壓", s)
        ):
            _lab41760 = f"{_lab41760}｜≠口述下降壓"
        _rb417 = _retest_avg_min_from_text(s)
        if (
            _rb417 is not None
            and abs(float(_rb417["avg"]) - float(_rb417["min"])) >= 0.6
        ):
            # 後文回測帶當令：備注對齊「≠回測帶」，不准再寫過期 ≠41500
            _lab41760 = f"{_lab41760}｜≠回測帶"
        elif _text_has_retest_41500(s) or "至少回測41500" in s:
            _lab41760 = f"{_lab41760}｜≠41500回測"
        _add(
            "tw",
            level=41760.0,
            ref_ymd="",
            role="台指壓力",
            tag="未到",
            label=_lab41760,
        )
    # 回測平均＋回測最低：從最新原文區間／單點重算（後文壓前文；不准鎖死舊價）
    _rb = _retest_avg_min_from_text(s)
    if _rb is None and (re.search(r"41500", s) or _text_has_retest_41500(s)):
        _rb = {
            "lo": 41500.0,
            "hi": 41500.0,
            "min": 41500.0,
            "avg": 41500.0,
        }
    if _rb is not None:
        _avg = float(_rb["avg"])
        _min = float(_rb["min"])
        if abs(_avg - _min) < 0.6:
            _add(
                "tw",
                level=_min,
                ref_ymd="",
                role="回測最低",
                tag="未到",
                label=f"回測平均＝最低／{_px(_min)}",
            )
        else:
            _add(
                "tw",
                level=_avg,
                ref_ymd="",
                role="回測平均",
                tag="未到",
                label=f"回測平均／{_px(_avg)}",
            )
            _add(
                "tw",
                level=_min,
                ref_ymd="",
                role="回測最低",
                tag="未到",
                label=f"回測最低／{_px(_min)}",
            )
    # 11/8 雙軌點位（只認原文）：37837／37164／35579／31705
    # 右欄：最佳買點 37837＋深殺上緣 35579＋深殺端 31705；39000／37164 改走黃底帶
    # 下降壓改口：37837＝已確認最低／不再假跌破；止跌確認後文未改口前＝再測／假跌破觀察
    # 不准還寫成舊雙軌「最佳買點」主標
    # 下降壓／止跌當令但句內沒寫 37837：仍釘週五低官方點（他已點過，不准丟標）
    _pb_or_stop = _text_has_c3_pressure_break(s) or _text_has_stop_low_confirm(s)
    if _pb_or_stop and not re.search(r"37837", s):
        s = f"{s} 星期五最低點位37837"
    if re.search(r"37837", s):
        if _text_has_retest_41500(s) or re.search(r"絕對不(?:會)?破", s):
            tag = "絕對不破"
            # 與圖上 C3 底同一點：右下只留這一顆，不准再黃箭重複
            # 右欄：C3底＋價＋狀態即可；「週五低」三字多餘（使用者 2026-11-13）
            lab = f"C3底／{_px(37837)}（絕對不破）"
        elif _text_has_c3_pressure_break(s) or (
            "不再假跌破" in s and re.search(r"下降壓", s)
        ):
            tag = "不再假跌破"
            lab = f"C3底／{_px(37837)}（不再假跌破）"
        elif _text_has_stop_low_confirm(s):
            tag = "再測／假跌破"
            lab = f"再測週五低／{_px(37837)}"
        else:
            tag = "最佳買點" if re.search(r"假跌破|買點", s) else "週五低"
            lab = f"最佳買點／{_px(37837)}"
        _add(
            "tw",
            level=37837.0,
            ref_ymd="20261106",
            role="五波末／週五低",
            tag=tag,
            label=lab,
        )
    if re.search(r"37164", s):
        _add(
            "tw",
            level=37164.0,
            ref_ymd="20260423",
            role="4/23低",
            tag="近對照",
            label=f"飆預測{_px(37164)}・4/23低",
        )
    if re.search(r"35579", s):
        _add(
            "tw",
            level=35579.0,
            ref_ymd="20260226",
            role="九波備線破位",
            tag="未到",
            # 深殺帶上緣：跌破 2/26 第一波高 → 走到 31705
            label=f"AI結束上緣／{_px(35579)}",
        )
    if re.search(r"31705", s):
        _add(
            "tw",
            level=31705.0,
            ref_ymd="20260331",
            role="九波備線深殺",
            tag="未到",
            label=f"AI結束深殺／{_px(31705)}",
        )
    # 下週底部觀察區：37100~39000（他原文兩端；雙軌當令底帶；不准發明中間價）
    has_week_bot_zone = bool(
        re.search(
            r"37100\s*[-~～到至\-]\s*39000|37100.{0,12}39000|最低點在\s*37100",
            s,
        )
    )
    if has_week_bot_zone:
        _add(
            "tw",
            level=39000.0,
            ref_ymd="",
            role="下週底上沿",
            tag="未到",
            label=f"飆預測{_px(39000)}・下週底上沿",
        )
        _add(
            "tw",
            level=37100.0,
            ref_ymd="",
            role="下週底下沿",
            tag="未到",
            label=f"飆預測{_px(37100)}・下週底下沿",
        )
    # 改口低點區：37000~37500（後文壓 C9；他原文兩端；不准發明中間價）
    has_foot2_zone = bool(
        re.search(r"37000\s*[-~～到至\-]\s*37500|37000.{0,8}37500", s)
    ) or _text_has_foot2_revision(s)
    # C-9 低點區：35500~37300（他原文兩端；不准發明中間價）
    has_c9_zone = bool(
        re.search(r"35500\s*[-~～到至]\s*37300|35500.{0,8}37300", s)
    )
    if has_foot2_zone:
        _add(
            "tw",
            level=37500.0,
            ref_ymd="",
            role="改口低上沿",
            tag="未到",
            label=f"飆預測{_px(37500)}改口低上沿",
        )
        _add(
            "tw",
            level=37000.0,
            ref_ymd="",
            role="改口低下沿",
            tag="未到",
            label=f"飆預測{_px(37000)}改口低下沿",
        )
        # 改口後舊 38000 劇本一上沿仍標已破；35000／C9 35500 不准再標
        _add(
            "tw",
            level=38000.0,
            ref_ymd="",
            role="劇本一上沿",
            tag="已破",
            label=f"飆預測{_px(38000)}已破",
        )
    elif has_c9_zone:
        _add(
            "tw",
            level=37300.0,
            ref_ymd="",
            role="C9低上沿",
            tag="未到",
            label=f"飆預測{_px(37300)}C9低上沿",
        )
        _add(
            "tw",
            level=35500.0,
            ref_ymd="",
            role="C9低下沿",
            tag="未到",
            label=f"飆預測{_px(35500)}C9低下沿",
        )
        # 有 C9 區：舊劇本一上沿 38000 改口「已破」仍要上右標；35000 不准再標
        _add(
            "tw",
            level=38000.0,
            ref_ymd="",
            role="劇本一上沿",
            tag="已破",
            label=f"飆預測{_px(38000)}已破",
        )
    # 劇本一／凌晨改口：大盤 35000~38000（無 C9／改口區才兩端都標）
    elif re.search(r"35000\s*[-~～到至]\s*38000|35000.{0,8}38000", s):
        _add(
            "tw",
            level=38000.0,
            ref_ymd="",
            role="劇本一上沿",
            tag="未到",
            label=f"飆預測{_px(38000)}劇本一上沿",
        )
        _add(
            "tw",
            level=35000.0,
            ref_ymd="",
            role="劇本一下沿",
            tag="未到",
            label=f"飆預測{_px(35000)}劇本一下沿",
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
    # 9865：文內「4/28」或「殺到／會破／必破 9865」都收；凌晨改口「會破」優先
    if re.search(r"9865", s) and re.search(
        r"4\s*/\s*28|殺到|會破|必破|至少.*9865|測.*9865", s
    ):
        off = _official_bar_low(db_path, "SOX", "20260428")
        lv = float(off) if off is not None and abs(off - 9865.0) <= 2.0 else 9865.0
        tag = "未到"
        lab = f"次回測4/28低{_px(lv)}"
        if re.search(r"9865\s*會破|會破.{0,6}9865|必破\s*9865|9865\s*必破", s):
            tag = "會破"
            lab = f"4/28低{_px(lv)}會破"
        _add(
            "sox",
            level=lv,
            ref_ymd="20260428",
            role="次回測",
            tag=tag,
            label=lab,
        )
    # 劇本一：破9865 → 測2/25高8498（他原文；官方高對質）
    if re.search(r"8498", s) and re.search(r"2\s*/\s*25", s):
        off_hi = _official_bar_high(db_path, "SOX", "20260225")
        lv = (
            float(off_hi)
            if off_hi is not None and abs(float(off_hi) - 8498.0) <= 3.0
            else 8498.0
        )
        _add(
            "sox",
            level=lv,
            ref_ymd="20260225",
            role="再回測",
            tag="未到",
            label=f"再回測2/25高{_px(lv)}",
        )

    # 他最新文抽出的大盤／台指點位 → 進預測列（虛線／右標跟著換；不准發明）
    seen_tw = {round(float(r["level"]), 1) for r in out["tw"]}
    _rb_skip = _retest_avg_min_from_text(s)
    try:
        from biaoke_walk import extract_index_levels

        for hit in extract_index_levels(s) or []:
            try:
                lv = float(hit.get("level"))
            except (TypeError, ValueError):
                continue
            if not (35000.0 <= lv <= 60000.0):
                continue
            # 有 C9／改口低點區：舊劇本一 35000／38000 不准再當裸抽點（38000 已上「已破」）
            if (has_c9_zone or has_foot2_zone) and (
                abs(lv - 35000.0) < 1.0 or abs(lv - 38000.0) < 1.0
            ):
                continue
            # 「N之下／以下」＝下行路徑必經，不是撐壓預測；不准標成「飆預測・已破」
            ctx = str(hit.get("ctx") or "")
            lv_i = int(round(lv))
            if re.search(
                rf"{lv_i}\s*(?:之)?下|{lv_i}\s*以下|(?:到|至|會到)\s*{lv_i}\s*(?:之)?下",
                ctx,
            ) or re.search(
                rf"(?:絕對)?(?:會)?到\s*{lv_i}\s*(?:之)?下",
                s,
            ):
                continue
            # 已落在當令回測帶內：由回測平均／最低兩口涵蓋，不准再裸抽
            if _rb_skip is not None and (
                float(_rb_skip["lo"]) - 1.0 <= lv <= float(_rb_skip["hi"]) + 1.0
            ):
                continue
            # 後文已有雙價回測帶：舊「至少回測」單點（如41500）過期，不准再裸抽
            if (
                _rb_skip is not None
                and abs(float(_rb_skip["avg"]) - float(_rb_skip["min"])) >= 0.6
                and (
                    abs(lv - 41500.0) < 0.6
                    or (
                        re.search(
                            rf"(?:至少)?回測(?:到)?\s*{lv_i}",
                            s,
                        )
                        and not (
                            float(_rb_skip["lo"]) - 1.0
                            <= lv
                            <= float(_rb_skip["hi"]) + 1.0
                        )
                    )
                )
            ):
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

    # 過期標／備注最後再濾一次（後文壓前文）
    out = _purge_stale_tw_pred_levels(out, snip=s)
    # 庫內最新費半價：9865 已破就掛 2/25 8498（盤中 live 在 prepare 再刷一次）
    return _refresh_sox_pred_cascade(out, db_path)


def _purge_stale_tw_pred_levels(
    pred: Dict[str, Any], *, snip: str = ""
) -> Dict[str, Any]:
    """過濾過期加權標／備注：有當令回測帶就丟舊單點41500、路徑裸點、過期≠41500備注。"""
    out = dict(pred or {})
    rows_in = list(out.get("tw") or [])
    if not rows_in:
        return out
    blob = str(snip or "")
    rb = _retest_avg_min_from_text(blob)
    band_on = bool(
        rb is not None and abs(float(rb["avg"]) - float(rb["min"])) >= 0.6
    )
    keep: List[Dict[str, Any]] = []
    for row in rows_in:
        r = dict(row)
        try:
            lv = float(r.get("level") or 0)
        except (TypeError, ValueError):
            keep.append(r)
            continue
        role = str(r.get("role") or "")
        lab = str(r.get("label") or "")
        if band_on:
            # 舊至少回測單點／同價裸抽＝過期
            if abs(lv - 41500.0) < 0.6:
                continue
            if role in {"點位", "至少回測"} and abs(lv - float(rb["avg"])) > 0.6 and abs(
                lv - float(rb["min"])
            ) > 0.6:
                # 路徑句殘留或舊單點
                if abs(lv - 43000.0) < 0.6 or "至少回測" in lab or "飆預測" in lab:
                    continue
            if role == "台指壓力" and "≠41500" in lab:
                r["label"] = lab.replace("≠41500回測", "≠回測帶").replace(
                    "≠41500", "≠回測帶"
                )
        else:
            # 無區間時仍清路徑裸點「43000之下」誤標
            if role == "點位" and abs(lv - 43000.0) < 0.6 and re.search(
                r"43000\s*(?:之)?下", blob
            ):
                continue
        keep.append(r)
    out["tw"] = keep
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
    """預估虛線下一錨順序（高→低）：跟他最新題旨下跌目標走；沒點才退回 45546→44210。

    只吃 pred_levels.tw 與 key_levels 的 pred_tw_*（他寫死預測錨）。
    反彈穿刺／轉震盪＝上方觀察壓，進右標、不准當下跌虛線下一錨。
    有 C9／改口低點區時，舊劇本一 35000／38000 不准再當虛線下一錨（改口已破）。
    不准把舊 claim_* 歷史宣稱混進虛線梯，否則端點／右標會卡在舊價。
    """
    # 台指壓力＝上方觀察壓，改走 _tw_pred_right_notes；不准進下跌虛線 tip 裸標成「飆預測・已破」
    _OVERHEAD = {"反彈穿刺", "轉震盪", "台指壓力"}
    _OLD_SCRIPT1 = {"劇本一上沿", "劇本一下沿"}
    # 雙軌關鍵位改走 _tw_pred_right_notes（角色標＋分色）；不准先被裸「未破／未到」佔位
    _DUAL_PATH = {
        "五波末／週五低",
        "4/23低",
        "九波備線破位",
        "九波備線深殺",
    }
    # 底帶兩沿改走 _paint_c9_low_zone_band；不准再進 tip 裸梯擠右欄
    _ZONE_EDGE = {
        "改口低上沿",
        "改口低下沿",
        "C9低上沿",
        "C9低下沿",
        "下週底上沿",
        "下週底下沿",
    }
    drop_script1 = _tw_has_c9_low_zone(pack)

    def _is_old_script1_px(v: float) -> bool:
        return abs(float(v) - 38000.0) < 1.0 or abs(float(v) - 35000.0) < 1.0

    his: List[float] = []
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            v = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        role = str(row.get("role") or "")
        if role in _OVERHEAD or role in _DUAL_PATH or role in _ZONE_EDGE:
            continue
        if drop_script1 and (role in _OLD_SCRIPT1 or _is_old_script1_px(v)):
            continue
        # 已破錨不准再當下跌虛線下一錨（否則 C9 端點會停在舊 38000）
        if str(row.get("tag") or "") == "已破":
            continue
        # 下週底／改口兩端純數字也不准進 tip 裸梯（底帶已畫）
        if any(abs(float(v) - x) < 1.0 for x in (39000.0, 37100.0, 37500.0, 37000.0)):
            continue
        if any(abs(float(v) - x) < 1.0 for x in (45546.0, 44210.0)):
            continue
        if 30000.0 <= v <= 60000.0:
            his.append(v)
    # 雙軌價（不論從 pred 列或 key_levels）一律不進 tip 裸標
    _dual_px = {
        round(float(r.get("level")), 1)
        for r in ((pack or {}).get("pred_levels") or {}).get("tw") or []
        if str(r.get("role") or "") in _DUAL_PATH
        and r.get("level") is not None
    }
    # 上方觀察壓／台指壓力：同樣不進 tip 裸梯（改走右欄角色標）
    _overhead_px = {
        round(float(r.get("level")), 1)
        for r in ((pack or {}).get("pred_levels") or {}).get("tw") or []
        if str(r.get("role") or "") in _OVERHEAD
        and r.get("level") is not None
    }
    _overhead_px.add(round(41760.0, 1))
    # 原文常見雙軌四價：沒 role 也擋
    for _px0 in (37837.0, 37164.0, 35579.0, 31705.0):
        _dual_px.add(round(_px0, 1))
    for k, raw in ((pack or {}).get("key_levels") or {}).items():
        if not str(k).startswith("pred_tw_"):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if drop_script1 and _is_old_script1_px(v):
            continue
        if round(v, 1) in _dual_px or round(v, 1) in _overhead_px:
            continue
        if any(abs(float(v) - x) < 1.0 for x in (39000.0, 37100.0, 37500.0, 37000.0)):
            continue
        # key_levels 無 role：上方壓位若已在 pred 列就略；裸數字仍收
        if abs(v - 46292.0) < 0.6 or abs(v - 45546.0) < 0.6:
            # 僅當 pred 列標成上方壓時才排除；舊錨 45546 當下跌目標時仍可進梯
            tw_rows = ((pack or {}).get("pred_levels") or {}).get("tw") or []
            if any(
                abs(float(r.get("level") or 0) - v) < 0.6
                and str(r.get("role") or "") in _OVERHEAD
                for r in tw_rows
            ):
                continue
        # 雙軌當令：舊 45546／44210 不准進 tip 裸梯佔紅框席
        if any(abs(float(v) - x) < 1.0 for x in (45546.0, 44210.0)):
            blob_tip = " ".join(
                str(x or "")
                for x in (
                    (pack or {}).get("thesis"),
                    (pack or {}).get("snippet"),
                    (pack or {}).get("snippet_full"),
                )
            )
            if _text_has_bb_dual_path(blob_tip) or "37837" in blob_tip:
                continue
        if 30000.0 <= v <= 60000.0:
            his.append(v)
    if not his:
        blob_empty = " ".join(
            str(x or "")
            for x in (
                (pack or {}).get("thesis"),
                (pack or {}).get("snippet"),
                (pack or {}).get("snippet_full"),
                (pack or {}).get("wait_struct"),
            )
        )
        # 雙軌／止跌確認當令：空梯就空，不准退回舊 45546→44210 佔右欄
        if (
            _text_has_bb_dual_path(blob_empty)
            or "37837" in blob_empty
            or _text_has_stop_low_confirm(blob_empty)
            or "止跌確認" in blob_empty
            or "41760" in blob_empty
        ):
            return tuple()
        return (45546.0, 44210.0)
    # 他點過的價高→低；1 點內視為同錨（避免 39384／39384.9 雙標）
    ordered = sorted(his, reverse=True)
    uniq: List[float] = []
    for v in ordered:
        if any(abs(v - u) < 1.0 for u in uniq):
            continue
        uniq.append(round(v, 1))
    return tuple(uniq)


def _teach_vol_rows_merge_deep(
    face_rows: Sequence[Dict[str, Any]],
    deep_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """教具下一層用深窗歷史；可視軸可短。臉末日覆寫收價。不准造假柱。"""
    face = list(face_rows or [])
    deep = list(deep_rows or [])
    if not deep and not face:
        return []
    if not deep:
        return face
    try:
        from biaoke_next_support import merge_face_onto_history, next_layer_history_bars

        hist = next_layer_history_bars(deep) if len(deep) > 1 else list(deep)
        return merge_face_onto_history(hist, face or deep)
    except Exception:
        logger.exception("教具深窗合併略過")
        return face or deep


def _teach_rows_have_intraday_ts(rows: Sequence[Dict[str, Any]]) -> bool:
    """軸上是否為 60 分列（有 HH:MM ts）→ 豎導／標籤對最大量那根。"""
    for r in rows or []:
        if _teach_bar_hhmm((r or {}).get("ts")):
            return True
    return False


def _micro_today_session_bar_indices(
    rows: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    pack: Optional[Dict[str, Any]] = None,
) -> List[int]:
    """超近窗：今開盤→查詢當下已出現的 60 分柱索引（台北）。

    例：13:00 查詢通常 09/10/11/12 四根；若庫已有 13:00 盤中柱則一併算入。
    非開市日／窗內無今日柱 → 空。
    """
    dt = None
    if isinstance(pack, dict):
        dt = _parse_query_at(pack.get("query_at"))
    if dt is None:
        dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    today = dt.strftime("%Y%m%d")
    qhm = int(dt.hour) * 100 + int(dt.minute)
    out: List[int] = []
    for i, r in enumerate(rows or []):
        ts = str((r or {}).get("ts") or "")
        ymd = _ymd((r or {}).get("date") or ts)
        if ymd != today:
            continue
        try:
            hm = int(ts[8:12]) if len(ts) >= 12 else -1
        except ValueError:
            continue
        if hm < 0:
            continue
        # 柱開始時刻 ≤ 查詢當下才算「到現在」
        if hm <= qhm:
            out.append(int(i))
    return out


def _paint_micro_today_session_bg(
    ax,
    axv,
    rows: Sequence[Dict[str, Any]],
    *,
    pack: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    alpha: float = 0.22,
) -> List[int]:
    """超近窗：今開盤→查詢當下每根 60 分 K 白底半透明（預設 22%，50% 太洗）。

    一眼看出今天第一根；價／量同段。不是買訊。
    """
    idxs = _micro_today_session_bar_indices(rows, now=now, pack=pack)
    if not idxs:
        return []
    x0 = float(idxs[0]) - 0.48
    x1 = float(idxs[-1]) + 0.48
    for a in (ax, axv):
        if a is None:
            continue
        try:
            a.axvspan(
                x0,
                x1,
                facecolor="#ffffff",
                alpha=float(alpha),
                zorder=0.28,
                linewidth=0,
                clip_on=True,
            )
        except Exception:
            logger.debug("超近今日白底略過", exc_info=True)
    return list(idxs)


def _teach_day_max_vol_ts(
    rows: Sequence[Dict[str, Any]], ymd: str
) -> str:
    """同日最大量那根 ts（下一層豎導／標籤寫幾點；0 量略過）。"""
    ranked = _teach_day_vol_rank_indices(rows, ymd, top_n=1)
    if not ranked:
        return ""
    i = int(ranked[0])
    if i < 0 or i >= len(rows or []):
        return ""
    return str((rows[i] or {}).get("ts") or "").strip()


def _teach_day_vol_rank_indices(
    rows: Sequence[Dict[str, Any]],
    ymd: str,
    *,
    top_n: int = 2,
) -> List[int]:
    """同交易日量柱由大到小取前 top_n 索引（0 量略過）；給本層／下一層最大量＋次大量。"""
    day = _ymd(ymd)
    if not day or top_n <= 0:
        return []
    scored: List[Tuple[float, int]] = []
    for i, r in enumerate(rows or []):
        rd = _ymd((r or {}).get("date")) or _ymd((r or {}).get("ts"))
        if rd != day:
            continue
        try:
            v = float((r or {}).get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        scored.append((v, int(i)))
    if not scored:
        return []
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [i for _v, i in scored[: int(top_n)]]


def _resolve_teach_vol_sr(
    bars: Sequence[Dict[str, Any]],
    *,
    lookback: int = 40,
    preview_below: bool = True,
) -> Dict[str, Any]:
    """教具大量撐壓＋下一層（對齊結構圖／大量區規則；不是買訊）。

    primary＝volume_first 仍有效爆大量日高低。
    下一層：破撐／過壓後 cascade；教具預設未破也預覽往下的次大量區
    （「若往下會進哪層」），preview=True。60 分軸白帶高低認該大量單根
    （與黃帶同；例 11/6 10:00 壓 40,436／撐 38,929），不准用全日包絡拉長。
    """
    rows = list(bars or [])
    out: Dict[str, Any] = {
        "primary": None,
        "next": None,
        "i_primary": None,
        "i_next": None,
        "i_next_2nd": None,  # 下一層同日次大量柱（量欄標色）
        "earliest_ymd": "",
    }
    if len(rows) < 4:
        return out
    lb = max(int(lookback or 40), 1)
    try:
        from biaoke_brain import volume_first_price
        from biaoke_next_support import find_secondary_vol_zone
    except Exception:
        logger.exception("教具大量撐壓匯入略過")
        return out
    try:
        vf = volume_first_price(rows, lookback=lb) or {}
    except Exception:
        logger.exception("教具 volume_first 略過")
        vf = {}
    spike_d = _ymd(vf.get("spike_date"))
    spike_ts = str(vf.get("spike_ts") or "").strip()
    hi = float(vf.get("spike_high") or 0)
    lo = float(vf.get("spike_low") or 0)
    if spike_d and hi > 0 and lo > 0 and hi >= lo:
        i_pri = _teach_vol_match_bar_index(
            rows, ymd=spike_d, high=hi, low=lo, ts=spike_ts
        )
        if not spike_ts and i_pri is not None:
            spike_ts = str((rows[int(i_pri)] or {}).get("ts") or "").strip()
        out["primary"] = {
            "date": spike_d,
            "ts": spike_ts,
            "high": hi,
            "low": lo,
            "volume": float(vf.get("spike_vol") or 0),
            "broke_support": not bool(vf.get("above_support")),
            "broke_press": bool(vf.get("broke_resistance")),
        }
        out["i_primary"] = i_pri
        out["earliest_ymd"] = spike_d
    primary = out.get("primary") or {}
    if not primary:
        return out
    close = float((rows[-1] or {}).get("close") or 0)
    nxt = None
    nxt_preview = False
    try:
        if primary.get("broke_support"):
            nxt = find_secondary_vol_zone(
                rows,
                direction="below",
                ref_lo=float(primary["low"]),
                exclude_date=str(primary.get("date") or ""),
                lookback=max(lb, 80),
                close=close,
                allow_earlier=True,
            )
        elif primary.get("broke_press"):
            nxt = find_secondary_vol_zone(
                rows,
                direction="above",
                ref_hi=float(primary["high"]),
                exclude_date=str(primary.get("date") or ""),
                lookback=max(lb, 80),
                close=close,
                allow_earlier=True,
            )
        elif preview_below:
            # 未破主撐：仍預覽往下次大量區（教具「若往下」；非買訊）
            nxt = find_secondary_vol_zone(
                rows,
                direction="below",
                ref_lo=float(primary["low"]),
                exclude_date=str(primary.get("date") or ""),
                lookback=max(lb, 80),
                close=close,
                allow_earlier=True,
            )
            nxt_preview = bool(nxt)
    except Exception:
        logger.exception("教具下一層大量區略過")
        nxt = None
        nxt_preview = False
    if nxt:
        nd = _ymd(nxt.get("date"))
        nhi = float(nxt.get("high") or nxt.get("pressure") or 0)
        nlo = float(nxt.get("low") or nxt.get("support") or 0)
        nts = str(nxt.get("ts") or "").strip()
        # 60分：豎導／時刻標對最大量那根；高低認該根單柱（與黃帶同）
        if nd and _teach_rows_have_intraday_ts(rows) and not nts:
            nts = _teach_day_max_vol_ts(rows, nd)
        i_nx = _teach_vol_match_bar_index(
            rows, ymd=nd, high=nhi, low=nlo, ts=nts
        )
        if i_nx is None and nd:
            if not nts:
                nts = _teach_day_max_vol_ts(rows, nd)
            i_nx = _teach_vol_match_bar_index(
                rows, ymd=nd, high=0.0, low=0.0, ts=nts
            )
        if not nts and i_nx is not None:
            nts = str((rows[int(i_nx)] or {}).get("ts") or "").strip()
        # 下一層同日：最大量＋次大量（量柱標色用）
        rank = _teach_day_vol_rank_indices(rows, nd, top_n=2)
        i_nx2 = int(rank[1]) if len(rank) >= 2 else None
        ts_2nd = ""
        if i_nx2 is not None:
            ts_2nd = str((rows[int(i_nx2)] or {}).get("ts") or "").strip()
        # 豎導優先對最大量根
        if rank and (i_nx is None or int(rank[0]) != int(i_nx)):
            if nts and str((rows[int(rank[0])] or {}).get("ts") or "").startswith(
                str(nts)[:12]
            ):
                i_nx = int(rank[0])
            elif not nts:
                i_nx = int(rank[0])
                nts = str((rows[int(i_nx)] or {}).get("ts") or "").strip()
        # 60分：高低強制跟豎導那根走，白帶不准比對應K更高／更低
        if (
            i_nx is not None
            and 0 <= int(i_nx) < len(rows)
            and _teach_rows_have_intraday_ts(rows)
        ):
            try:
                bh = float((rows[int(i_nx)] or {}).get("high") or 0)
                bl = float((rows[int(i_nx)] or {}).get("low") or 0)
            except (TypeError, ValueError):
                bh, bl = 0.0, 0.0
            if bh > 0 and bl > 0 and bh >= bl:
                nhi, nlo = bh, bl
        out["next"] = {
            "date": nd,
            "ts": nts,
            "ts_2nd": ts_2nd,
            "high": nhi,
            "low": nlo,
            "direction": str(nxt.get("direction") or "below"),
            "label_hold": f"下一層撐 {_px(nlo)}" if nlo > 0 else str(nxt.get("label_hold") or ""),
            "label_press": f"下一層壓 {_px(nhi)}" if nhi > 0 else str(nxt.get("label_press") or ""),
            "preview": bool(nxt_preview),
        }
        if nd and (not out["earliest_ymd"] or nd < out["earliest_ymd"]):
            out["earliest_ymd"] = nd
        out["i_next"] = i_nx
        out["i_next_2nd"] = i_nx2
    return out


def _y_inside_pred_zone_bands(
    y: float, pack: Optional[Dict[str, Any]], *, pad: float = 120.0
) -> bool:
    """價位落在下週底／AI結束觀察帶（含呼吸）→ 左欄壓撐不准再佔同一帶（紅圈互壓）。"""
    try:
        yy = float(y)
    except (TypeError, ValueError):
        return False
    wb = _tw_active_low_zone(pack)
    if wb and str(wb[2]) == "week_bot":
        lo, hi = float(wb[0]), float(wb[1])
        if (lo - float(pad)) <= yy <= (hi + float(pad)):
            return True
    ai = _tw_ai_end_zone(pack)
    if ai:
        lo, hi = float(ai[0]), float(ai[1])
        if (lo - float(pad)) <= yy <= (hi + float(pad)):
            return True
    return False


def _paint_next_layer_vol_zone(
    ax,
    *,
    high: float,
    low: float,
    date_lab: str,
    fp: Any,
    direction: str = "below",
    labels: bool = True,
    avoid_top_left_stamp: bool = False,
    pack: Optional[Dict[str, Any]] = None,
    ts_lab: str = "",
) -> None:
    """下一層大量區＝半透明白橫帶＋白虛線上下緣（暗底也要看得出邊界）。"""
    y0, y1 = float(low), float(high)
    if y1 <= y0:
        return
    day_tag = _teach_vol_day_tag(date_lab, ts_lab)
    # 半透明白底＋上下白虛線：暗底不再糊成一塊灰
    ax.axhspan(y0, y1, facecolor="#ffffff", alpha=0.20, zorder=0.45)
    for yy in (y0, y1):
        ax.axhline(
            float(yy),
            color="#f5f5f5",
            lw=1.15,
            ls=(0, (3.2, 2.0)),
            alpha=0.92,
            zorder=1.1,
        )
    if not labels:
        return
    # 壓／撐落在飆預測黃／紫帶內 → 不准畫左標（紅圈互壓）
    if not _y_inside_pred_zone_bands(y1, pack):
        _paint_left_sr_label(
            ax,
            y1,
            f"白帶 {day_tag}下一層壓 {_px(y1)}",
            fp=fp,
            color="#ffffff",
            edge="#bdbdbd",
            va="bottom",
            fontsize=10.5,
            avoid_top_left_stamp=avoid_top_left_stamp,
            x_base=0.01,
        )
    if not _y_inside_pred_zone_bands(y0, pack):
        _paint_left_sr_label(
            ax,
            y0,
            f"白帶 {day_tag}下一層撐 {_px(y0)}",
            fp=fp,
            color="#ffffff",
            edge="#bdbdbd",
            va="top",
            fontsize=10.5,
            avoid_top_left_stamp=avoid_top_left_stamp,
            x_base=0.13,
        )
    _ = direction


def _display_teach_vol_sr_for_paint(sr_pack: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """畫圖用：主大量區已破撐／過壓且有非預覽下一層 → 黃帶升格下一層，已破主帶改淡標。

    不改 ``_resolve_teach_vol_sr`` 語意（對質／測仍認 volume_first 主區＋cascade）。
    只修三窗「分布區」：不准已破黃帶繼續當現況主色塊漂在現價外。
    """
    out = dict(sr_pack or {})
    primary = dict(out.get("primary") or {})
    nxt = dict(out.get("next") or {})
    if not primary or not nxt:
        return out
    if bool(nxt.get("preview")):
        return out
    broke = bool(primary.get("broke_support")) or bool(primary.get("broke_press"))
    if not broke:
        return out
    if not (nxt.get("high") and nxt.get("low")):
        return out
    broken = dict(primary)
    broken["broken_for_paint"] = True
    active = {
        "date": nxt.get("date"),
        "ts": nxt.get("ts") or "",
        "high": float(nxt["high"]),
        "low": float(nxt["low"]),
        "volume": float(nxt.get("volume") or 0),
        "broke_support": False,
        "broke_press": False,
        "promoted_from_next": True,
    }
    out["primary"] = active
    out["broken_primary"] = broken
    out["next"] = {}
    if out.get("i_next") is not None:
        out["i_primary"] = out.get("i_next")
    out["i_next"] = None
    out["i_next_2nd"] = None
    out["paint_promoted"] = True
    return out


def _paint_broken_vol_zone(
    ax,
    *,
    high: float,
    low: float,
    date_lab: str,
    fp: Any,
    labels: bool = True,
    avoid_top_left_stamp: bool = False,
    ts_lab: str = "",
    broke_support: bool = True,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
) -> None:
    """已破主大量區：淡灰虛邊，不准再當醒目黃帶（分布區亂源）。"""
    y0, y1 = float(low), float(high)
    if y1 <= y0:
        return
    day_tag = _teach_vol_day_tag(date_lab, ts_lab)
    ax.axhspan(y0, y1, facecolor="#90a4ae", alpha=0.10, zorder=0.42)
    for yy in (y0, y1):
        ax.axhline(
            float(yy),
            color="#78909c",
            lw=0.9,
            ls=(0, (2.5, 2.2)),
            alpha=0.55,
            zorder=1.05,
        )
    if not labels:
        return
    tag = "已破撐" if broke_support else "已破壓"
    # 淡帶：標貼「這價沒被 K 碰到」的空檔（使用者圈位），不准壓棒
    _paint_left_sr_label(
        ax,
        y1,
        f"淡帶 {day_tag}{tag}壓 {_px(y1)}",
        fp=fp,
        color="#b0bec5",
        edge="#607d8b",
        va="bottom",
        fontsize=9.0,
        avoid_top_left_stamp=avoid_top_left_stamp,
        x_base=0.01,
        x_mode="mid_clear",
        highs=highs,
        lows=lows,
    )
    _paint_left_sr_label(
        ax,
        y0,
        f"淡帶 {day_tag}{tag}撐 {_px(y0)}",
        fp=fp,
        color="#b0bec5",
        edge="#607d8b",
        va="top",
        fontsize=9.0,
        avoid_top_left_stamp=avoid_top_left_stamp,
        x_base=0.13,
        x_mode="mid_clear",
        highs=highs,
        lows=lows,
    )


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
    vol_lookback: int = 40,
    vol_sr: Optional[Dict[str, Any]] = None,
    avoid_top_left_stamp: bool = False,
    pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """遠／近／超近共用：黃＝大量撐壓、灰＝下一層大量區、青＝飆預測位階帶；底色在K下層。"""
    n = len(highs)
    sr_raw = vol_sr if isinstance(vol_sr, dict) else _resolve_teach_vol_sr(
        bars, lookback=int(vol_lookback or 40)
    )
    sr_pack = _display_teach_vol_sr_for_paint(sr_raw)
    primary = (sr_pack or {}).get("primary") or {}
    nxt = (sr_pack or {}).get("next") or {}
    broken = (sr_pack or {}).get("broken_primary") or {}
    i_vmax = (sr_pack or {}).get("i_primary")
    if i_vmax is None and n and any(float(v or 0) > 0 for v in vols):
        # 備援：窗內絕對最大量（無 volume_first 時仍要有黃帶）
        i_vmax = max(range(n), key=lambda i: float(vols[i] or 0))
        primary = {
            "date": _ymd(bars[i_vmax].get("date")),
            "ts": str(bars[i_vmax].get("ts") or ""),
            "high": float(highs[i_vmax]),
            "low": float(lows[i_vmax]),
        }
    sr = _next_support_resist(float(y_now), supports=supports, resists=resists)
    y_excl_lo = float(primary["low"]) if primary.get("low") is not None else None
    y_excl_hi = float(primary["high"]) if primary.get("high") is not None else None
    if broken.get("high") and broken.get("low"):
        _paint_broken_vol_zone(
            ax,
            high=float(broken["high"]),
            low=float(broken["low"]),
            date_lab=str(broken.get("date") or ""),
            ts_lab=str(broken.get("ts") or ""),
            fp=fp,
            avoid_top_left_stamp=avoid_top_left_stamp,
            broke_support=bool(broken.get("broke_support")),
            highs=highs,
            lows=lows,
        )
        try:
            y_excl_lo = (
                min(float(y_excl_lo), float(broken["low"]))
                if y_excl_lo is not None
                else float(broken["low"])
            )
            y_excl_hi = (
                max(float(y_excl_hi), float(broken["high"]))
                if y_excl_hi is not None
                else float(broken["high"])
            )
        except (TypeError, ValueError):
            pass
    if primary.get("high") and primary.get("low"):
        _paint_max_vol_hl_zone(
            ax,
            high=float(primary["high"]),
            low=float(primary["low"]),
            date_lab=str(primary.get("date") or ""),
            ts_lab=str(primary.get("ts") or ""),
            fp=fp,
            avoid_top_left_stamp=avoid_top_left_stamp,
        )
    if nxt.get("high") and nxt.get("low"):
        _paint_next_layer_vol_zone(
            ax,
            high=float(nxt["high"]),
            low=float(nxt["low"]),
            date_lab=str(nxt.get("date") or ""),
            ts_lab=str(nxt.get("ts") or ""),
            fp=fp,
            direction=str(nxt.get("direction") or "below"),
            avoid_top_left_stamp=avoid_top_left_stamp,
            pack=pack,
        )
        # 下一層帶也列入青帶避讓
        try:
            y_excl_lo = min(float(y_excl_lo), float(nxt["low"])) if y_excl_lo is not None else float(nxt["low"])
            y_excl_hi = max(float(y_excl_hi), float(nxt["high"])) if y_excl_hi is not None else float(nxt["high"])
        except (TypeError, ValueError):
            pass
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
        avoid_top_left_stamp=avoid_top_left_stamp,
    )
    return {
        "sr": sr,
        "sr_skip": sr_skip,
        "i_vmax": i_vmax,
        "y_excl_lo": y_excl_lo,
        "y_excl_hi": y_excl_hi,
        "vol_sr": sr_pack,
        "vol_sr_raw": sr_raw,
    }


def _ensure_teach_pack_preds(
    db_path: str, pack: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """三窗重渲：pack 缺雙軌／下週底 pred 時併入 live 題旨抽出。

    不准用空 pack 只畫結構釘、丢掉 37837／37164／35579／31705／37100~39000。
    """
    out = dict(pack or {})
    tw = (
        list(((out.get("pred_levels") or {}).get("tw") or []))
        if isinstance(out.get("pred_levels"), dict)
        else []
    )

    def _has_px(rows: List[Any], px: float) -> bool:
        for r in rows:
            try:
                if abs(float(r.get("level")) - float(px)) < 1.0:
                    return True
            except (TypeError, ValueError, AttributeError):
                continue
        return False

    need = not (
        _has_px(tw, 37837.0)
        and _has_px(tw, 35579.0)
        and _has_px(tw, 31705.0)
    )
    if not need and str(out.get("snippet_full") or out.get("snippet") or "").strip():
        return out
    try:
        live = _build_live_pack(db_path)
    except Exception:
        logger.exception("教具 pack 補 pred 略過")
        return out
    if not isinstance(live, dict):
        return out
    live_pred = live.get("pred_levels") if isinstance(live.get("pred_levels"), dict) else {}
    if need or not tw:
        out["pred_levels"] = live_pred or {"tw": [], "sox": []}
    for k in (
        "pred_note",
        "snippet",
        "snippet_full",
        "thesis",
        "wait_struct",
        "morph_note",
        "fib_note",
        "intent_note",
        "turn_note",
        "vol_note",
        "us_note",
        "chart_as_of",
        "thesis_as_of",
        "query_at",
    ):
        if live.get(k) in (None, "", [], {}):
            continue
        if not out.get(k):
            out[k] = live[k]
    merged_lv = dict(out.get("key_levels") or {})
    merged_lv.update(live.get("key_levels") or {})
    out["key_levels"] = merged_lv
    return out


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
    # 夜盤進行中：wait 注用 MIS 即時 OHLC，不准還寫庫內未收完舊夜盤收
    live_tx = _ensure_paint_live_tx(thesis_pack, now=dt)
    if (
        isinstance(live_tx, dict)
        and float(live_tx.get("close") or 0) > 0
        and _tx_night_session_live(dt)
    ):
        try:
            _lc = float(live_tx["close"])
            _lh = float(live_tx.get("high") or 0)
            _ll = float(live_tx.get("low") or 0)
            _ld = _ymd(live_tx.get("date")) or dt.strftime("%Y%m%d")
            levels["tx_night_c"] = _lc
            if _lh > 0:
                levels["tx_night_h"] = _lh
            if _ll > 0:
                levels["tx_night_l"] = _ll
            _live_note = f"大台夜{_ld}盤中{_px(_lc)}"
            if _lh > 0 and _ll > 0:
                _live_note += f"（高{_px(_lh)}低{_px(_ll)}）"
            wait = f"{wait}｜{_live_note}"
        except (TypeError, ValueError):
            if fut.get("note"):
                wait = f"{wait}｜{fut['note']}"
    elif fut.get("note"):
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
        "snippet_full": thesis_pack.get("snippet_full") or thesis_pack.get("snippet") or "",
        "chart_as_of": chart_as_of,
        "thesis_as_of": thesis_cap,
        "query_at": dt.isoformat(),
        "db_path": db_path,
    }


# 活畫深底：話筒縮圖對比（對齊你覺得清楚的黑底讀法）
_LIVE_BG = "#0b0f14"
_LIVE_PANEL = "#121820"
_LIVE_TEXT = "#f2f5f8"
_LIVE_MUTED = "#b0bec5"
_LIVE_GRID = "#2a3440"
_LIVE_UP = "#ff5252"
_LIVE_DOWN = "#26a69a"
# 遠窗縮圖：絕對 min body=6 對費半／加權價軸幾乎看不見；改跟價窗比例走
_LIVE_CANDLE_MIN_BODY_FRAC = 0.01
_FAR_SOX_MIN_BODY_FRAC = 0.018
# 教具 X／標籤契約（鎖死；不准無限變瘦、不准右欄越擠越亂）
# 1) 定長滾動：新交易日進一根 → 刪最左一根；K 寬穩定。
# 2) 右欄現況標（今／飆預測／雙軌關鍵／大量撐壓價）：x＝末根+_TEACH_RIGHT_GUTTER，
#    相對圖右緣位置幾乎不變；只跟 n（定長）走，不跟歷史總日數走。
# 3) 尖點浪名（C1…C9、⑤起、A/B）：釘該日 K 的 x；滾動後跟著那根移；
#    該日被滾出窗外 → 不釘幽靈標（價位改由右欄／帶狀承接）。
# 4) 座位：右欄=_place_live_right_labels（軟上限＋分 tier）；尖點=_pin_pivot_name。
# 5) 新飆大文／自回抽出的大盤・費半點位 → pred_levels → 右欄席位自動接；
#    擠不過就丟低優先（Fib／下一層），雙軌／今／已破必留。
# 6) 末根日期刻度必顯；盤中螢光黃綠、收盤／盤前白字。戳框同：盤中螢光邊、收盤黑邊。
# 遠窗預設根數；撐壓日可略超 soft，再長硬滾（不准為浪階日無限拉長變瘦）
_FAR_TEACH_MAX_BARS = 152
_FAR_TEACH_EXTEND_SOFT = 168  # 僅大量撐壓／下一層可略超；硬上限
_FAR_TEACH_VOL_LOOKBACK = 200
_NEAR_TEACH_MAX_BARS = 130  # 近窗：⑤起地板；滿長後滾（A／B／C 仍優先留窗）
_MICRO_TEACH_MAX_BARS = 55  # 超近：B／C 特寫定長
# 黃培碩 60 分 C 波：定長滾（K 寬穩定）；soft 僅為 C3 底還在窗內可略超
_HUANG_C60_MAX_BARS = 150
_HUANG_C60_SOFT_MAX = 168
_TEACH_RIGHT_GUTTER = 2.55  # 右欄現況相對末K的固定槽（bar 單位）
_TEACH_RIGHT_XLIM_PAD = 10.2  # xlim 右側固定留白（bar 單位）


def _teach_right_col_x(
    n: int,
    *,
    tip_fut_x: Optional[float] = None,
    extra: float = 0.0,
    x_col: Optional[float] = None,
) -> float:
    """右欄現況標 X：永遠＝末根＋固定 gutter（可被 tip／呼叫端略拉）。"""
    if x_col is not None:
        try:
            base = float(x_col)
        except (TypeError, ValueError):
            base = float(n) + float(_TEACH_RIGHT_GUTTER)
    else:
        base = float(n) + float(_TEACH_RIGHT_GUTTER) + float(extra or 0.0)
    if tip_fut_x is not None:
        try:
            base = max(base, float(tip_fut_x) + 0.85)
        except (TypeError, ValueError):
            pass
    return float(base)


def _teach_xlim_right(
    n: int,
    *,
    tip_xlim: float = 0.0,
    right_col: float = 0.0,
    fut_x: float = 0.0,
    extra: float = 0.0,
) -> float:
    """右緣 xlim：相對末K固定 pad，右欄字寬不隨歷史拉長而變瘦。"""
    return max(
        float(n) + float(_TEACH_RIGHT_XLIM_PAD) + float(extra or 0.0),
        float(tip_xlim or 0.0),
        float(right_col or 0.0) + 7.2,
        float(fut_x or 0.0) + 2.0,
    )


def _teach_roll_from_floor(
    bars: Sequence[Dict[str, Any]],
    *,
    floor_i: int = 0,
    max_bars: int,
) -> List[Dict[str, Any]]:
    """結構地板＋定長滾動：未滿 max 從地板起；滿了就進一根刪最左。"""
    rows = list(bars or [])
    if not rows:
        return rows
    cap = max(20, int(max_bars or 20))
    i0 = max(0, min(int(floor_i or 0), len(rows) - 1))
    window = rows[i0:]
    if len(window) > cap:
        return window[-cap:]
    return window


def _window_huang_c60_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    max_bars: int = _HUANG_C60_MAX_BARS,
    soft_max: int = _HUANG_C60_SOFT_MAX,
) -> List[Dict[str, Any]]:
    """黃培碩 60 分超近窗：定長滾動，x 軸不無限拉長。

    - 未滿 max：從 C1 起畫到最新（教具鎖死最新縮圖K）
    - 滿了：進一根刪最左，K 寬穩定
    - C3 底還會被硬滾切掉時，允許略超 soft 把 C3 留在窗內
    - soft 仍裝不下＝硬滾；滾出的浪標不釘幽靈（對不到錨就退日界色帶）
    """
    full = list(rows or [])
    n = len(full)
    cap = max(40, int(max_bars or _HUANG_C60_MAX_BARS))
    soft = max(cap, int(soft_max or _HUANG_C60_SOFT_MAX))
    if n <= cap:
        return full
    anc = _resolve_huang_c60_anchors(full)
    if not anc.get("ok"):
        return full[-cap:]
    i1 = int(anc["i1"])
    i3 = int(anc["i3"])
    body = full[i1:]
    if len(body) <= cap:
        return body
    rolled = body[-cap:]
    # rolled 在 full 的起點
    start = i1 + len(body) - cap
    if start <= i3:
        return rolled
    # C3 底已在硬窗左側 → soft 略拉左
    soft_start = max(i1, n - soft)
    if soft_start <= i3:
        return full[soft_start:]
    return rolled


def _far_teach_roll_bars(
    bars: Sequence[Dict[str, Any]], *, max_bars: int = _FAR_TEACH_MAX_BARS
) -> List[Dict[str, Any]]:
    """遠窗滾動裁切：超過 max_bars 只留最右（最新）一段。"""
    rows = list(bars or [])
    cap = max(20, int(max_bars or _FAR_TEACH_MAX_BARS))
    if len(rows) > cap:
        return rows[-cap:]
    return rows


def _remap_teach_vol_sr_index(
    sr: Dict[str, Any], bars: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """切片後重算大量撐壓／下一層日索引；日期不在窗內 → i_*=None（底色仍可畫價）。

    60分優先對 ts／同日高低；日K仍對 ymd（同日多根取最後一根相容舊行為）。
    """
    out = dict(sr or {})
    out["i_primary"] = None
    out["i_next"] = None
    out["i_next_2nd"] = None
    rows = list(bars or [])
    by_ymd = {_ymd(r.get("date")): i for i, r in enumerate(rows) if _ymd(r.get("date"))}
    pri = ((out.get("primary") or {}) or {})
    nxt = ((out.get("next") or {}) or {})
    pd = _ymd(pri.get("date"))
    i_pri = _teach_vol_match_bar_index(
        rows,
        ymd=pd,
        high=float(pri.get("high") or 0),
        low=float(pri.get("low") or 0),
        ts=str(pri.get("ts") or ""),
    )
    if i_pri is None and pd and pd in by_ymd:
        i_pri = int(by_ymd[pd])
    out["i_primary"] = i_pri
    nd = _ymd(nxt.get("date"))
    i_nx = _teach_vol_match_bar_index(
        rows,
        ymd=nd,
        high=float(nxt.get("high") or 0),
        low=float(nxt.get("low") or 0),
        ts=str(nxt.get("ts") or ""),
    )
    if i_nx is None and nd and nd in by_ymd:
        i_nx = int(by_ymd[nd])
    out["i_next"] = i_nx
    if nd:
        rank = _teach_day_vol_rank_indices(rows, nd, top_n=2)
        if rank:
            out["i_next"] = int(rank[0])
        if len(rank) >= 2:
            out["i_next_2nd"] = int(rank[1])
    return out


def _vol_sr_index_on_axis(
    sr: Optional[Dict[str, Any]],
    *,
    axis_ymds: Sequence[str],
) -> Tuple[Optional[int], Optional[int]]:
    """把大量撐壓／下一層日期對到本欄 x 索引（費半／電子盤／加權各算各的）。"""
    pack = sr if isinstance(sr, dict) else {}
    by = {_ymd(d): i for i, d in enumerate(axis_ymds or []) if _ymd(d)}
    i_pri = by.get(_ymd(((pack.get("primary") or {}) or {}).get("date")))
    i_nxt = by.get(_ymd(((pack.get("next") or {}) or {}).get("date")))
    return (
        int(i_pri) if i_pri is not None else None,
        int(i_nxt) if i_nxt is not None else None,
    )


# 遠窗各欄豎導：黃＝當前大量撐壓日K；藍＝下一層大量日K（對齊量欄藍柱／灰帶；不准跨欄共用加權日）
_VOL_SR_GUIDE_PRIMARY = "#f9a825"
_VOL_SR_GUIDE_NEXT = "#42a5f5"
_VOL_SR_CANDLE_PRIMARY = "#ffd54f"
_VOL_SR_CANDLE_NEXT = "#42a5f5"


def _teach_vol_sr_title_bit(
    vol_sr: Optional[Dict[str, Any]],
    *,
    bars: Sequence[Dict[str, Any]] = (),
    highs: Sequence[float] = (),
    lows: Sequence[float] = (),
    i_vmax: Optional[int] = None,
) -> str:
    """三窗標題共用：黃＝大量撐壓｜灰＝下一層。"""
    pri = ((vol_sr or {}).get("primary") or {}) if isinstance(vol_sr, dict) else {}
    nxt = ((vol_sr or {}).get("next") or {}) if isinstance(vol_sr, dict) else {}
    if pri.get("date") and pri.get("high") is not None and pri.get("low") is not None:
        tag = _teach_vol_day_tag(pri.get("date"), pri.get("ts")).strip()
        bit = (
            f"黃＝大量撐壓{tag} "
            f"{_px(pri.get('high'))}～{_px(pri.get('low'))}"
        )
    elif i_vmax is not None and bars and highs and lows:
        b = bars[int(i_vmax)]
        tag = _teach_vol_day_tag(b.get("date"), b.get("ts")).strip()
        bit = (
            f"黃＝大量撐壓{tag} "
            f"{_px(highs[int(i_vmax)])}～{_px(lows[int(i_vmax)])}"
        )
    else:
        bit = "黃＝大量撐壓"
    if nxt.get("date") and nxt.get("high") is not None and nxt.get("low") is not None:
        ntag = _teach_vol_day_tag(nxt.get("date"), nxt.get("ts")).strip()
        bit += (
            f"｜亮桃／灰＝下一層{ntag} "
            f"{_px(nxt.get('high'))}～{_px(nxt.get('low'))}"
        )
    return bit


def _far_teach_bars_keeping_vol_sr(
    bars: Sequence[Dict[str, Any]],
    *,
    max_bars: int = _FAR_TEACH_MAX_BARS,
    vol_lookback: int = _FAR_TEACH_VOL_LOOKBACK,
    keep_ymds: Sequence[str] = ("20260331", "20260401"),
    extend_soft: int = _FAR_TEACH_EXTEND_SOFT,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """遠窗切片：定長滾動為主；大量撐壓／浪階日被裁可略拉左，但硬卡 soft 上限。

    例：撐壓在窗左外 → 左側拉到該日，最右仍＝最新；若因此超過 soft → 仍硬滾，
    撐壓改由帶狀／右欄承接（不准為留舊浪階日把 K 棒無限變瘦）。
    keep_ymds＝希望進窗的浪階日（能留才留，不准破 soft）。
    """
    story = list(bars or [])
    lb = max(40, int(vol_lookback or _FAR_TEACH_VOL_LOOKBACK))
    if len(story) > 1:
        lb = min(lb, len(story) - 1)
    sr = _resolve_teach_vol_sr(story, lookback=lb)
    rolled = _far_teach_roll_bars(story, max_bars=max_bars)
    if not rolled:
        return rolled, sr
    need_dates: List[str] = []
    early = _ymd((sr or {}).get("earliest_ymd"))
    if early:
        need_dates.append(early)
    for raw in keep_ymds or ():
        kd = _ymd(raw)
        if not kd:
            continue
        if _bar_index_by_ymd(story, kd) is not None:
            need_dates.append(kd)
            continue
        # 缺精確日 → 取第一個 ≥ 該日的交易日
        for r in story:
            d = _ymd(r.get("date"))
            if d and d >= kd:
                need_dates.append(d)
                break
    if not need_dates:
        return rolled, _remap_teach_vol_sr_index(sr, rolled)
    need = min(need_dates)
    left = _ymd(rolled[0].get("date"))
    if left and need >= left:
        return rolled, _remap_teach_vol_sr_index(sr, rolled)
    # 左側拉到最早需求日；硬卡 soft，超過就改硬滾（尖點滾出＝不釘幽靈）
    i_need = _bar_index_by_ymd(story, need)
    if i_need is None:
        for i, r in enumerate(story):
            d = _ymd(r.get("date"))
            if d and d >= need:
                i_need = i
                break
    if i_need is None:
        return rolled, _remap_teach_vol_sr_index(sr, rolled)
    soft = max(int(max_bars or _FAR_TEACH_MAX_BARS), int(extend_soft or _FAR_TEACH_EXTEND_SOFT))
    extended = story[int(i_need) :]
    if len(extended) > soft:
        extended = extended[-soft:]
    return extended, _remap_teach_vol_sr_index(sr, extended)
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


def _candle_body_y0_height(open_: float, close: float, min_body: float) -> Tuple[float, float]:
    """實體 y0／高：收盤鎖在正確邊（漲＝上緣、跌＝下緣）；min_body 往另一邊長。

    舊寫法從 min(開,收) 往上長，小實體／平盤時「今」tip 會黏在紅柱下緣。
    """
    try:
        o = float(open_)
        c = float(close)
    except (TypeError, ValueError):
        return 0.0, max(float(min_body or 0), 1.0)
    mb = max(float(min_body or 0), 0.0)
    if c >= o:
        top = c
        bot = float(o)
        if top - bot < mb:
            bot = top - mb
        return bot, max(top - bot, mb if mb > 0 else 0.0)
    bot = c
    top = float(o)
    if top - bot < mb:
        top = bot + mb
    return bot, max(top - bot, mb if mb > 0 else 0.0)


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

    # 末根蓋回＝陽陰線（收相對開）；無開盤才退回昨收
    pc = prev_c
    try:
        if pc is not None:
            pc_f = float(pc)
            if not (pc_f == pc_f and pc_f > 0):
                pc = None
    except (TypeError, ValueError):
        pc = None
    up = candle_up(close, pc, open_)
    color = _LIVE_UP if up else _LIVE_DOWN
    ec = edgecolor or color
    wick = ax.vlines(
        i, low, high, color=color, linewidth=wick_lw, zorder=z_wick, clip_on=False
    )
    try:
        wick.set_clip_on(False)
    except Exception:
        pass
    y0, h_body = _candle_body_y0_height(float(open_), float(close), float(min_body))
    patch = plt.Rectangle(
        (i - width * 0.5, y0),
        width,
        h_body,
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
    ax.set_facecolor(_LIVE_PANEL)
    axv.set_facecolor(_LIVE_PANEL)
    for a in (ax, axv):
        a.tick_params(colors=_LIVE_MUTED, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)


def _prev_valid_close(
    closes: Sequence[float], i: int, *, opens: Optional[Sequence[float]] = None
) -> Optional[float]:
    """前一根有效收（>0、有限）；給三窗 K／量同色，不准缺昨收就退回開收變色。

    遠窗費半／電子盤對齊軸可有空格；加權日K一般連續，仍統一走這條。
    opens 參數保留相容（呼叫端可傳），不拿開盤冒充昨收。
    """
    import math

    _ = opens  # 相容保留；昨收只認 close
    for j in range(int(i) - 1, -1, -1):
        try:
            c = float(closes[j])
        except (TypeError, ValueError, IndexError):
            continue
        if c == c and math.isfinite(c) and c > 0:
            return c
    return None


def _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_up) -> None:
    """三窗共用日K＋量：陽紅陰綠＝收相對開（candle_body_up_taiwan）；K／量同根同色。

    不准一根用昨收、量柱改比開收；也不准缺昨收就整窗翻色。
    high／low≤0 時用 open／close 補，不准量柱在、價K隱形。
    """
    n = len(closes)
    min_body = _candle_span_min_body(highs, lows, frac=_LIVE_CANDLE_MIN_BODY_FRAC)
    import matplotlib.pyplot as plt

    for i in range(n):
        try:
            c_i = float(closes[i])
        except (TypeError, ValueError):
            continue
        if not (c_i == c_i and c_i > 0):
            continue
        try:
            o_i = float(opens[i]) if i < len(opens) else c_i
        except (TypeError, ValueError):
            o_i = c_i
        if not (o_i == o_i and o_i > 0):
            o_i = c_i
        try:
            h_i = float(highs[i]) if i < len(highs) else max(o_i, c_i)
        except (TypeError, ValueError):
            h_i = max(o_i, c_i)
        try:
            l_i = float(lows[i]) if i < len(lows) else min(o_i, c_i)
        except (TypeError, ValueError):
            l_i = min(o_i, c_i)
        if not (h_i == h_i and h_i > 0):
            h_i = max(o_i, c_i)
        if not (l_i == l_i and l_i > 0):
            l_i = min(o_i, c_i)
        h_i = max(h_i, o_i, c_i)
        l_i = min(l_i, o_i, c_i)
        prev_c = _prev_valid_close(closes, i, opens=opens)
        up = candle_up(c_i, prev_c, o_i)
        color = _LIVE_UP if up else _LIVE_DOWN
        # wick/body z 高於底帶、低於空心 tip；末根另蓋回
        # z 高過 C1–C4 底色／黃白帶；標完跨度後還會再蓋一層，基本K不准被蓋沒
        ax.vlines(i, l_i, h_i, color=color, linewidth=1.55, zorder=8)
        y0, h_body = _candle_body_y0_height(o_i, c_i, float(min_body))
        ax.add_patch(
            plt.Rectangle(
                (i - 0.34, y0),
                0.68,
                h_body,
                facecolor=color,
                edgecolor=color,
                linewidth=0.55,
                zorder=9,
            )
        )
        if axv is not None and i < len(vols):
            try:
                vv = float(vols[i] or 0)
            except (TypeError, ValueError):
                vv = 0.0
            if vv == vv and vv > 0:
                axv.bar(i, vv, color=color, width=0.68, zorder=3, alpha=0.92)


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


def _paint_teach_vol_layer_bars(
    axv,
    vols: Sequence[float],
    *,
    i_primary: Optional[int] = None,
    i_next: Optional[int] = None,
    i_next_2nd: Optional[int] = None,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
    fp: Any = None,
) -> None:
    """量欄兩根色柱＋柱頂正上方短標（完整在軸內，不准裁半句）。

    黃＝現在撐壓那根；藍＝下一層那根。次大量不上色不上標（多餘）。
    文案只要「黃 11/5 09:00」「白 11/6 10:00」——不寫張數（張數會把標裁掉）。
    """
    if axv is None or not vols:
        return
    vals = [float(v or 0) for v in vols]
    n = len(vals)
    rows = list(bars or [])
    peak = max(vals) if any(v > 0 for v in vals) else 1.0
    _ = i_next_2nd  # 明確不用：第三根會擠、會裁

    def _ok(i: Optional[int]) -> bool:
        return i is not None and 0 <= int(i) < n and vals[int(i)] > 0

    def _tag(i: int) -> str:
        if i < len(rows):
            r = rows[i] or {}
            return _teach_vol_day_tag(r.get("date"), r.get("ts")).strip()
        return ""

    marks: List[Tuple[int, str, str, str]] = []
    if _ok(i_primary):
        ii = int(i_primary)
        marks.append((ii, "#f9a825", "#fff59d", f"黃 {_tag(ii)}"))
    if _ok(i_next) and (i_primary is None or int(i_next) != int(i_primary)):
        ii = int(i_next)
        marks.append((ii, "#42a5f5", "#e3f2fd", f"白 {_tag(ii)}"))
    if not marks:
        return

    # 柱頂標要完整：ylim 留足空帶；標用 text 貼柱頂，clip 在軸內
    y_top = float(peak) * 1.55
    axv.set_ylim(0, float(y_top))
    for ii, face, ink, lab in marks:
        h = float(vals[ii])
        axv.bar(
            ii,
            h,
            color=face,
            edgecolor="#ffffff",
            linewidth=1.15,
            width=0.92,
            zorder=6,
            alpha=0.99,
        )
        if fp is None or not lab:
            continue
        # 柱頂正中上方；兩標同日或鄰近 → 左／右錯開＋一上一下，不准互壓
        y_lab = h + float(peak) * 0.06
        if y_lab > float(y_top) * 0.92:
            y_lab = float(y_top) * 0.88
        x_lab = float(ii)
        ha_lab = "center"
        if len(marks) == 2 and abs(int(marks[0][0]) - int(marks[1][0])) <= 4:
            left_i = min(int(marks[0][0]), int(marks[1][0]))
            if ii == left_i:
                x_lab = float(ii) - 0.55
                ha_lab = "right"
                y_lab = min(float(y_top) * 0.90, h + float(peak) * 0.10)
            else:
                x_lab = float(ii) + 0.55
                ha_lab = "left"
                y_lab = min(float(y_top) * 0.96, h + float(peak) * 0.22)
        axv.text(
            float(x_lab),
            float(y_lab),
            lab,
            fontproperties=fp(10.5, "bold"),
            color=ink,
            ha=ha_lab,
            va="bottom",
            zorder=12,
            clip_on=True,
            bbox=dict(
                boxstyle="round,pad=0.22",
                facecolor="#0b0f14",
                edgecolor=face,
                linewidth=1.2,
                alpha=0.98,
            ),
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
    annotate: bool = True,
) -> Optional[int]:
    """日量柱；窗內最大量那根改黃色；可選標「最大量＋月日」。

    annotate=False：只上色柱（遠窗另有黃／白短標時不准再疊「最大量」字造成互壓）。
    回傳最大量索引（＝當日K同一格）。
    """
    n = len(vols)
    if n == 0 or axv is None:
        return None
    vals = [float(v or 0) for v in vols]
    i_max = max(range(n), key=lambda i: vals[i]) if any(v > 0 for v in vals) else None
    for i in range(n):
        prev_c = _prev_valid_close(closes, i, opens=opens)
        o_i = opens[i] if i < len(opens) else closes[i]
        up = candle_up(closes[i], prev_c, o_i)
        color = "#ffeb3b" if i_max is not None and i == i_max else (_LIVE_UP if up else _LIVE_DOWN)
        axv.bar(i, vals[i], color=color, width=0.68, zorder=3, alpha=0.95 if color == "#ffeb3b" else 0.88)
    if annotate and i_max is not None and vals[i_max] > 0 and fp is not None:
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
            bbox=dict(boxstyle="round,pad=0.1", fc="#0b0f14", ec="#ffeb3b", lw=0.55, alpha=0.94),
        )
    axv.set_ylabel(title, fontproperties=fp(9, "bold"), color=_LIVE_MUTED)
    return i_max


def _paint_max_vol_day_guide(axes: Sequence[Any], i_max: Optional[int]) -> None:
    """相容舊呼叫：同一儀器多欄（價＋量）畫黃虛線。遠窗跨商品請改 `_paint_vol_sr_day_guides`。"""
    if i_max is None:
        return
    for a in axes:
        _paint_vol_sr_day_guides(a, i_primary=int(i_max), i_next=None)


def _paint_vol_sr_day_guides(
    ax: Any,
    *,
    i_primary: Optional[int] = None,
    i_next: Optional[int] = None,
) -> None:
    """單欄各自畫豎導：黃＝當前大量撐壓日；亮桃＝下一層大量日。

    費半／電子盤／加權爆大量日不一定同一天 → 不准把加權 10/15 豎線拉到上兩欄。
    """
    if ax is None:
        return
    if i_primary is not None:
        ax.axvline(
            float(i_primary),
            color=_VOL_SR_GUIDE_PRIMARY,
            lw=1.85,
            ls=(0, (3.5, 1.6)),
            alpha=0.98,
            zorder=5,
        )
    if i_next is not None and (i_primary is None or int(i_next) != int(i_primary)):
        ax.axvline(
            float(i_next),
            color=_VOL_SR_GUIDE_NEXT,
            lw=1.85,
            ls=(0, (3.0, 1.6)),
            alpha=0.96,
            zorder=5,
        )


def _paint_vol_sr_mark_on_axis(
    ax: Any,
    *,
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    i_primary: Optional[int] = None,
    i_next: Optional[int] = None,
    date_primary: str = "",
    date_next: str = "",
    fp: Any = None,
    candle_up: Any = None,
) -> None:
    """單欄：當前大量日金K＋黃豎線；下一層＝桃豎線＋桃描邊（K 本體仍紅漲綠跌）。

    不准把下一層日整根洗成亮桃色：遠窗曾把 11/6 下一層洗桃，近／超近同日仍綠，
    話筒三窗同一加權日看起來像翻色。最大量日仍金K（三窗一致）。
    """
    if ax is None:
        return
    import matplotlib.pyplot as plt

    n = min(len(opens), len(highs), len(lows), len(closes))

    def _ok(i: Optional[int]) -> bool:
        return i is not None and 0 <= int(i) < n and float(highs[int(i)]) == float(highs[int(i)])

    if _ok(i_next):
        ii = int(i_next)
        # 桃描邊鎖在已畫好的漲跌色 K 上；本體色跟近／超近同一套昨收規則
        try:
            from decision_card_signals import candle_body_up_taiwan as _cup
        except Exception:
            _cup = candle_up
        cup = candle_up or _cup
        prev_c = _prev_valid_close(closes, ii, opens=opens)
        up = bool(cup(float(closes[ii]), prev_c, float(opens[ii]))) if cup else True
        body = _LIVE_UP if up else _LIVE_DOWN
        ax.vlines(
            ii,
            float(lows[ii]),
            float(highs[ii]),
            color=body,
            linewidth=1.55,
            zorder=6,
        )
        y0, y1 = sorted((float(opens[ii]), float(closes[ii])))
        ax.add_patch(
            plt.Rectangle(
                (ii - 0.36, y0),
                0.72,
                max(y1 - y0, 8),
                facecolor=body,
                edgecolor=_VOL_SR_CANDLE_NEXT,
                linewidth=1.35,
                zorder=7,
            )
        )
        _ = (date_next, fp)
    if _ok(i_primary):
        ii = int(i_primary)
        _paint_special_candle(
            ax,
            ii,
            open_=float(opens[ii]),
            high=float(highs[ii]),
            low=float(lows[ii]),
            close=float(closes[ii]),
            color=_VOL_SR_CANDLE_PRIMARY,
            date_lab=date_primary,
            fp=fp,
        )
    _paint_vol_sr_day_guides(ax, i_primary=i_primary, i_next=i_next)


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


def _nearest_bar_touching_px(
    bars: Sequence[Dict[str, Any]],
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    px: float,
    before_i: int,
) -> Optional[Dict[str, Any]]:
    """往左找最近一根高低包住現價的日（水平虛線對到哪一天曾走過這個價）。"""
    try:
        y = float(px)
    except (TypeError, ValueError):
        return None
    if y <= 0:
        return None
    tip = max(0, int(before_i))
    n = min(len(bars), len(highs), len(lows))
    for i in range(tip - 1, -1, -1):
        if i >= n:
            continue
        try:
            hi = float(highs[i])
            lo = float(lows[i])
        except (TypeError, ValueError):
            continue
        if not (hi == hi and lo == lo and hi > 0 and lo > 0):
            continue
        if lo <= y <= hi:
            return {
                "i": int(i),
                "date": _ymd((bars[i] or {}).get("date")),
                "high": hi,
                "low": lo,
            }
    return None


def _nearest_vol_support_row(
    vol_sr: Optional[Dict[str, Any]],
    *,
    px: float,
) -> Optional[Dict[str, Any]]:
    """大量／下一層撐裡，低於現價且最近的一檔（含 date／low）。"""
    try:
        y = float(px)
    except (TypeError, ValueError):
        return None
    if y <= 0 or not isinstance(vol_sr, dict):
        return None
    cands: List[Dict[str, Any]] = []
    for key in ("primary", "next"):
        row = vol_sr.get(key) or {}
        try:
            lo = float(row.get("low") or 0)
        except (TypeError, ValueError):
            lo = 0.0
        if lo <= 0 or lo >= y - 1.0:
            continue
        cands.append(
            {
                "date": _ymd(row.get("date")),
                "low": lo,
                "high": float(row.get("high") or 0) or None,
                "kind": key,
            }
        )
    if not cands:
        return None
    cands.sort(key=lambda r: float(y) - float(r["low"]))
    return cands[0]


def _paint_tx_now_price_rail(
    ax,
    *,
    px: float,
    tip_i: int,
    fp: Any,
    live: bool = False,
    asof_ymd: str = "",
    hit: Optional[Dict[str, Any]] = None,
    near_sup: Optional[Dict[str, Any]] = None,
    x_label: Optional[float] = None,
) -> None:
    """電子盤現價／收盤水平虛線：對日期＋近撐月日價。

    紫虛線＝當下或收盤價 → 穿過末根 tip → 標籤；標籤 Y 鎖真價。
    碰到舊K的日子豎虛＋「曾到」；近撐另畫淡青虛線。
    """
    if ax is None or fp is None:
        return
    try:
        y = float(px)
        tip = int(tip_i)
    except (TypeError, ValueError):
        return
    if y <= 0 or tip < 0:
        return
    # 水平虛線：左緣 → 穿過末根 tip → 標籤左緣；標籤 Y＝真價（va=center）
    try:
        x_lab = float(x_label) if x_label is not None else float(tip) + 0.70
    except (TypeError, ValueError):
        x_lab = float(tip) + 0.70
    x_dash_end = max(float(tip) + 0.35, float(x_lab) - 0.48)
    ax.plot(
        [-0.45, x_dash_end],
        [y, y],
        color="#ea80fc",
        lw=1.25,
        ls=(0, (5, 2.4)),
        alpha=0.92,
        zorder=9,
        solid_capstyle="butt",
        clip_on=False,
    )
    phase = "盤中" if live else "收盤"
    md = _md(asof_ymd) if _ymd(asof_ymd) else ""
    head = f"{md}{phase}" if md else phase
    bits = [f"{head} {_px(y)}"]
    if hit and _ymd(hit.get("date")):
        hi = int(hit.get("i") or -1)
        if hi >= 0:
            ax.axvline(
                float(hi),
                color="#ea80fc",
                lw=0.85,
                ls=(0, (2, 2.2)),
                alpha=0.55,
                zorder=3,
            )
        bits.append(f"←{_md(hit.get('date'))}曾到")
    if near_sup and float(near_sup.get("low") or 0) > 0:
        sm = _md(near_sup.get("date")) if _ymd(near_sup.get("date")) else ""
        if sm:
            bits.append(f"近撐{sm} {_px(float(near_sup['low']))}")
        else:
            bits.append(f"近撐 {_px(float(near_sup['low']))}")
        # 近撐也畫一條淡青虛線，方便跟現價紫線對照
        try:
            sy = float(near_sup["low"])
            ax.plot(
                [-0.45, x_dash_end],
                [sy, sy],
                color="#4dd0e1",
                lw=1.05,
                ls=(0, (4, 2.5)),
                alpha=0.75,
                zorder=8,
                solid_capstyle="butt",
                clip_on=False,
            )
        except (TypeError, ValueError):
            pass
    # 矛點釘末根 tip；標籤與虛線同一水平（真價）
    # 點字盤：盤中＝白底＋螢光黃框；收盤＝白底＋黑框（與三窗查詢戳同規）
    _spear_ring(ax, float(tip), y, color="#ea80fc", zorder=9.5, hot=True)
    stamp_live = bool(live)
    ax.text(
        x_lab,
        y,
        "｜".join(bits),
        fontproperties=fp(8, "bold"),
        color=_TEACH_STAMP_META,
        ha="left",
        va="center",
        zorder=12,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.14",
            fc=_TEACH_STAMP_FACE,
            ec=_teach_stamp_edge(live=stamp_live, kind="tw"),
            lw=max(1.15, float(_TEACH_STAMP_BOX_LW) * 0.55),
            alpha=0.98,
        ),
    )


def _axes_x_clear_of_bars(
    ax,
    y: float,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    *,
    prefer: float = 0.42,
    x_nudge: float = 0.0,
) -> float:
    """該價水平線上沒被 K 高低蓋住的空檔 → axes 分數 X。

    雙區底色常在 ``set_xlim`` 前就畫：不准用當下 xlim（常是 ±0.05）換算，
    只用柱索引／根數估 axes 分數，才會落在使用者圈的空檔。
    """
    pref = float(prefer)
    hi_l = list(highs or [])
    lo_l = list(lows or [])
    n = min(len(hi_l), len(lo_l))
    _ = ax
    if n < 2:
        return float(max(0.08, min(0.72, pref + float(x_nudge))))
    clear: List[int] = []
    yy = float(y)
    for i in range(n):
        try:
            hi, lo = float(hi_l[i]), float(lo_l[i])
        except (TypeError, ValueError):
            continue
        if not (lo <= yy <= hi):
            clear.append(i)
    if not clear:
        return float(max(0.08, min(0.72, pref + float(x_nudge))))
    best_s, best_e = clear[0], clear[0]
    run_s, prev = clear[0], clear[0]
    for i in clear[1:]:
        if i == prev + 1:
            prev = i
            continue
        if prev - run_s > best_e - best_s:
            best_s, best_e = run_s, prev
        run_s = prev = i
    if prev - run_s > best_e - best_s:
        best_s, best_e = run_s, prev
    mid_i = 0.5 * (best_s + best_e)
    # 柱畫在 0..n-1；axes 分數≈索引比例（底色早於 set_xlim 也穩）
    axes_x = float(mid_i) / float(max(n - 1, 1))
    axes_x = float(axes_x) + float(x_nudge)
    return float(max(0.08, min(0.72, axes_x)))


def _left_sr_label_xy(
    ax,
    y: float,
    *,
    avoid_top_left_stamp: bool = False,
    stamp_top_frac: float = _TEACH_STAMP_AX_Y_MIN,
    clear_x: float = 0.60,
    x_base: float = 0.01,
    x_mode: str = "left",
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
) -> Tuple[float, bool]:
    """左欄價標 X（axes）；白底戳佔左上時改右移並回傳 need_dash。

    x_mode=mid_clear：標貼該價水平線上空檔（避密K），一定畫水平虛線連回左緣真價。
    """
    mode = str(x_mode or "left").strip().lower()
    if mode == "mid_clear":
        # 壓／撐微錯開；優先落在「K 沒碰到這價」的最長空檔
        # 不准再被左上白底戳邏輯右推到 0.72（會整排壓回密K）
        _ = (avoid_top_left_stamp, stamp_top_frac, clear_x)
        x = _axes_x_clear_of_bars(
            ax,
            y,
            highs,
            lows,
            prefer=0.42,
            x_nudge=0.02 if float(x_base) >= 0.10 else 0.0,
        )
        return float(x), True
    x = float(x_base)
    if not avoid_top_left_stamp or ax is None:
        return float(x), False
    try:
        y0, y1 = ax.get_ylim()
        span = max(float(y1) - float(y0), 1.0)
        axes_y = (float(y) - float(y0)) / span
    except Exception:
        return float(x), False
    if axes_y >= float(stamp_top_frac):
        return float(max(clear_x, _TEACH_STAMP_AX_X_MAX + 0.04)), True
    return float(x), False


def _paint_left_sr_label(
    ax,
    y: float,
    text: str,
    *,
    fp: Any,
    color: str,
    edge: str,
    va: str = "center",
    fontsize: float = 9,
    avoid_top_left_stamp: bool = False,
    x_base: float = 0.01,
    x_mode: str = "left",
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
) -> None:
    """左欄大量／下一層標；標籤 Y＝真價（va 鎖 center）；右移時短虛線水平連回價位。

    va 參數保留相容，一律當 center（不准標在價上／價下讓人自己對）。
    x_base：壓／撐錯欄（0.01 vs 0.13），Y 接近時不准上下互壓成一坨。
    x_mode=mid_clear：淡帶等高區改貼空檔，不准壓住 K 棒。
    """
    if ax is None or fp is None or not text:
        return
    _ = va  # 相容；鎖死水平對價
    x, need_dash = _left_sr_label_xy(
        ax,
        y,
        avoid_top_left_stamp=avoid_top_left_stamp,
        x_base=float(x_base),
        x_mode=str(x_mode or "left"),
        highs=highs,
        lows=lows,
    )
    tr = ax.get_yaxis_transform()
    # 右移避戳／中空檔：標前短虛線水平連回真價（與標籤同一 Y）
    if need_dash:
        ax.plot(
            [0.02, max(0.04, float(x) - 0.02)],
            [float(y), float(y)],
            transform=tr,
            color=str(edge),
            lw=0.75,
            ls=(0, (2.4, 1.6)),
            alpha=0.82,
            zorder=10,
            solid_capstyle="butt",
            clip_on=False,
        )
    ax.text(
        float(x),
        float(y),
        str(text),
        transform=tr,
        fontproperties=fp(float(fontsize), "bold"),
        color=str(color),
        ha="left",
        va="center",
        zorder=11,
        bbox=dict(
            boxstyle="round,pad=0.12",
            fc="#0b0f14",
            ec=str(edge),
            lw=0.7,
            alpha=0.94,
        ),
        clip_on=False,
    )


def _paint_max_vol_hl_zone(
    ax,
    *,
    high: float,
    low: float,
    date_lab: str,
    fp: Any,
    labels: bool = True,
    avoid_top_left_stamp: bool = False,
    ts_lab: str = "",
) -> None:
    """淺黃底＝大量撐壓（爆大量日最高～最低）；底色 zorder 低於K棒。

    左標一定帶交易日月日；60分再寫幾點K棒（例 11/5 09:00），跟金K／量柱黃／豎虛線同一根。
    labels=False：只留底色（遠窗電子盤改走右欄疏開，左欄不准再卡一坨）。
    avoid_top_left_stamp：遠窗三白底戳佔左上時，頂部價標右移＋虛線，不准被戳蓋住。
    """
    y0, y1 = float(low), float(high)
    if y1 <= y0:
        return
    day_tag = _teach_vol_day_tag(date_lab, ts_lab)
    # 黃帶加醒目：跟量欄黃柱／豎導同一套，一眼對「現在撐壓」
    ax.axhspan(y0, y1, facecolor="#ffeb3b", alpha=0.28, zorder=0.5)
    if not labels:
        return
    _paint_left_sr_label(
        ax,
        y1,
        f"黃帶 {day_tag}大量壓 {_px(y1)}",
        fp=fp,
        color="#fff59d",
        edge="#f9a825",
        va="bottom",
        fontsize=10.5,
        avoid_top_left_stamp=avoid_top_left_stamp,
        x_base=0.01,
    )
    _paint_left_sr_label(
        ax,
        y0,
        f"黃帶 {day_tag}大量撐 {_px(y0)}",
        fp=fp,
        color="#fff59d",
        edge="#f9a825",
        va="top",
        fontsize=10.5,
        avoid_top_left_stamp=avoid_top_left_stamp,
        x_base=0.13,  # 與壓錯欄，Y 接近時不准互壓
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
    avoid_top_left_stamp: bool = False,
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
    # 遠窗白底戳佔左上時同大量壓撐：右移＋虛線
    if support is not None:
        if _y_inside_hl(float(support), exclude_lo, exclude_hi):
            skipped["support"] = float(support)
        else:
            _level_dash(float(support))
            if not _skip_lab(float(support)):
                _paint_left_sr_label(
                    ax,
                    float(support),
                    _biaoke_pred_label(float(support)),
                    fp=fp,
                    color="#b2ebf2",
                    edge="#4dd0e1",
                    va="top",
                    fontsize=9,
                    avoid_top_left_stamp=avoid_top_left_stamp,
                )
    if resist is not None:
        if _y_inside_hl(float(resist), exclude_lo, exclude_hi):
            skipped["resist"] = float(resist)
        else:
            _level_dash(float(resist))
            if not _skip_lab(float(resist)):
                _paint_left_sr_label(
                    ax,
                    float(resist),
                    _biaoke_pred_label(float(resist)),
                    fp=fp,
                    color="#b2ebf2",
                    edge="#4dd0e1",
                    va="bottom",
                    fontsize=9,
                    avoid_top_left_stamp=avoid_top_left_stamp,
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
    """日／60分柱：回該日第一根索引（60分一天多根時取首根）。"""
    want = _ymd(ymd)
    if not want:
        return None
    for i, r in enumerate(bars):
        if _ymd(r.get("date")) == want:
            return i
    return None


def _bar_index_last_by_ymd(bars: Sequence[Dict[str, Any]], ymd: str) -> Optional[int]:
    """日／60分柱：回該日最後一根索引（60分跨度尾用這個）。"""
    want = _ymd(ymd)
    if not want:
        return None
    last: Optional[int] = None
    for i, r in enumerate(bars):
        if _ymd(r.get("date")) == want:
            last = i
    return last


# 大C起＝大B末日；近／超近60分窗從此起，前面大B不進軸（免x軸擠爆）
_C_WAVE_60_SINCE_YMD = "20261006"


def _md(ymd: Any) -> str:
    t = _ymd(ymd)
    return f"{int(t[4:6])}/{int(t[6:8])}" if len(t) == 8 else str(ymd or "")


def _sparse_xticks(
    idxs: Sequence[int],
    labels: Sequence[str],
    *,
    min_gap: int = 2,
    must_keep: Optional[Sequence[int]] = None,
) -> Tuple[List[int], List[str]]:
    """日期刻度稀釋：相鄰索引少於 min_gap 只留前一個，不准 10/15 壓 10/16。

    首尾必留：最新交易日刻度不准被稀釋掉（否則會以為沒畫 11/6）。
    must_keep：加權末日等錨點必留；與延長格太近時兩邊都留（不准用費半延長日盖掉加權末日）。
    """
    pairs = sorted(((int(i), str(lab)) for i, lab in zip(idxs, labels)), key=lambda t: t[0])
    if not pairs:
        return [], []
    lab_by_i = {i: lab for i, lab in pairs}
    must = {int(x) for x in (must_keep or []) if int(x) in lab_by_i}
    out_i: List[int] = []
    out_l: List[str] = []
    last = -10**9
    first_i, first_lab = pairs[0]
    last_i, last_lab = pairs[-1]
    must.add(first_i)
    must.add(last_i)
    for i, lab in pairs:
        if i == last_i:
            continue  # 末日最後強制補
        close = bool(out_i and i - last < int(min_gap))
        if close and i not in must:
            continue
        if close and i in must and out_i and out_i[-1] not in must:
            # 必留錨蓋掉可丟的前一刻度
            out_i[-1] = i
            out_l[-1] = lab
            last = i
            continue
        out_i.append(i)
        out_l.append(lab)
        last = i
    if not out_i or out_i[0] != first_i:
        out_i.insert(0, first_i)
        out_l.insert(0, first_lab)
    if out_i[-1] != last_i:
        if out_i and last_i - out_i[-1] < int(min_gap) and out_i[-1] not in must:
            out_i[-1] = last_i
            out_l[-1] = last_lab
        else:
            out_i.append(last_i)
            out_l.append(last_lab)
    # must_keep 漏網（被末日替換擠掉）→ 插回正確位置
    for mi in sorted(must):
        if mi in out_i:
            continue
        lab = lab_by_i.get(mi)
        if lab is None:
            continue
        insert_at = next((k for k, x in enumerate(out_i) if x > mi), len(out_i))
        out_i.insert(insert_at, mi)
        out_l.insert(insert_at, lab)
    return out_i, out_l


def _far_shared_axis_xticks(
    bars: Sequence[Dict[str, Any]],
    *,
    sox_extra_dates: Sequence[str],
    want: set,
    i5s: int,
    i5e: int,
    i_alow: int,
    i_b_end: int,
    min_gap: int = 4,
) -> Tuple[List[int], List[str]]:
    """遠窗四欄共用日軸刻度。

    只寫月日＋結構錨（⑤起／大A底…）。費半官方日若晚於加權軸，延長格
    **仍只寫月日**，不准標「費半」——四欄 sharex，電盤／加權／量底緣寫費半會誤導。
    費半身分看上欄左軸／黃框。加權末日刻度必留（must_keep）。
    """
    n_tw = len(bars or [])
    t2: List[int] = []
    l2: List[str] = []
    for i, r in enumerate(bars or []):
        d = _ymd(r.get("date"))
        if d in want or i % 10 == 0:
            if i not in t2:
                t2.append(i)
                tag = ""
                if i == i5s or d == "20260401":
                    tag = "⑤起"
                elif i == i5e or d == "20260623":
                    tag = "⑤終"
                elif d == "20260225":
                    tag = "費再回測"
                elif d == "20260428":
                    tag = "費次回測"
                elif d == "20260729" or i == i_alow:
                    tag = "大A底"
                elif i == i_b_end or d == "20261006":
                    tag = "大B末假突破"
                l2.append(f"{_md(d)}{tag}")
    # 費半官方日晚於加權軸：補月日（不加「費半」後綴）
    for j, d in enumerate(sox_extra_dates or []):
        i = n_tw + int(j)
        dd = _ymd(d)
        if dd in want and i not in t2:
            t2.append(i)
            l2.append(f"{_md(dd)}")
    must_keep: List[int] = []
    if n_tw > 0:
        must_keep.append(n_tw - 1)
    return _sparse_xticks(t2, l2, min_gap=min_gap, must_keep=must_keep)


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
    """浪名智慧標（尖點類）：跟著該日 K 的 x 走；滾出窗外就不釘。

    與右欄現況標分開：右欄走 `_place_live_right_labels`／`_teach_right_col_x`，
    圖右位置幾乎固定；本函式只服務釘在柱上的浪名／轉折名。

    tip=high → 整盒在高點上方；tip=low → 整盒在低點下方（含 bbox pad 也離尖）；
    tip=mid → 左右錯開到柱外（C／今）。
    """
    # 滾動窗外／尚未進窗：不准留幽靈標
    try:
        xx0 = float(x)
    except (TypeError, ValueError):
        return
    if n is not None:
        try:
            nn = float(n)
            if xx0 < -0.75 or xx0 > nn + 0.6:
                return
        except (TypeError, ValueError):
            pass
    tip_k = str(tip or "mid").lower()
    try:
        y_lo, y_hi = ax.get_ylim()
        span = max(float(y_hi) - float(y_lo), 1.0)
    except Exception:
        y_lo, y_hi = float(y) - 1.0, float(y) + 1.0
        span = max(abs(float(y)) * 0.08, 1.0)
    # bbox pad 會往尖點回吃一截 → 必須再撐開，整盒才離得開K／浪線
    lift = float(clear_dy) if clear_dy is not None else max(span * 0.055, abs(float(y)) * 0.0028)
    yy = float(y)
    if tip_k in {"high", "low"}:
        # 上下離尖；若指定 left／right 再水平讓開（A／B 緊貼黃K時必讓）
        va = "bottom" if tip_k == "high" else "top"
        yy = float(y) + lift if tip_k == "high" else float(y) - lift
        if side == "left":
            xx, ha = float(x) - max(float(pad_x), 0.85), "right"
        elif side == "right":
            xx, ha = float(x) + max(float(pad_x), 0.85), "left"
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
    # 左上白底戳禁區：尖點標先水平讓出，再進座位（不准費⑤終／⑤終被戳蓋）
    if not getattr(ax, "_wayne_stamp_zone_reserved", False):
        _reserve_teach_stamp_zone(ax)
        ax._wayne_stamp_zone_reserved = True
    xx, yy, ha = _clear_teach_stamp_pin_xy(ax, xx, yy, ha=ha)
    avoid = list(getattr(ax, "_wayne_avoid_zones", None) or [])
    lab_s = str(lab)
    # C1…C7 短浪號：鎖在對應高低尖，不准被智慧座位整排垂直拉開變「字柱」
    _sticky_c = bool(re.fullmatch(r"C[1-9]", lab_s))
    if _sticky_c:
        # 只避同點重疊：微水平錯開，Y 仍貼 tip（已含 clear_dy）
        for sx, sy in seats:
            if abs(float(xx) - float(sx)) < 0.85 and abs(float(yy) - float(sy)) < max(
                span * 0.012, 60.0
            ):
                xx = float(xx) + (0.55 if ha == "left" else -0.55)
                break
    else:
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
        # 落在戳區時改向下微挪（向上會更深進戳）
        try:
            _ax_yf = (float(yy) - float(y_lo)) / max(span, 1e-9)
            _nudge = (
                "down"
                if _ax_yf > float(_TEACH_STAMP_AX_Y_MIN)
                else ("up" if tip_k == "high" else "down")
            )
        except Exception:
            _nudge = "up" if tip_k == "high" else "down"
        seated = _seat_onchart_labels(
            prior
            + [
                {
                    "x": float(xx),
                    "y": float(yy),
                    "text": lab_s,
                    "pri": int(pri),
                    "nudge": _nudge,
                    "min_dx": 1.85 if len(lab_s) <= 3 else 1.55,
                }
            ],
            ymin=float(y_lo),
            ymax=float(y_hi),
            min_gap=span * 0.068,
            avoid_zones=avoid,
        )
        mine = [r for r in seated if str(r.get("text")) == lab_s]
        if not mine:
            return
        xx = float(mine[0]["x"])
        yy = float(mine[0]["y"])
        xx, yy, ha = _clear_teach_stamp_pin_xy(ax, xx, yy, ha=ha)
    seats.append((xx, yy))
    # 浪號／關鍵標：邊框跟浪色走，底略染同色，遠看也能分 C1…C9
    fc = "#0b0f14"
    ec_lw = 0.55
    try:
        from matplotlib.colors import to_rgb

        r, g, b = to_rgb(color)
        fc = (r * 0.22, g * 0.22, b * 0.22)
        if str(lab_s).startswith("C") or "預估" in lab_s or "大B" in lab_s:
            ec_lw = 0.85
    except Exception:
        pass
    ax.text(
        xx,
        yy,
        lab_s,
        fontproperties=fp(max(7, int(fontsize)), "normal"),
        color=color,
        ha=ha,
        va=va,
        zorder=int(zorder),
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.10",
            fc=fc,
            ec=color,
            lw=ec_lw,
            alpha=0.92,
        ),
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
    nudge: bool = False,
    fontsize: float = 9,
) -> None:
    """右側價標：全部對齊同一右欄；同色水平虛線對真價拉過末根 tip。

    - 字 Y＝真價（鎖死；標籤與虛線同一水平，不准上下漂讓人猜股價在標上還是標下）。
    - 真價互撞→丟低優先（寧可少標，不准把字盒挪離真價）。
    - nudge 參數保留相容；不再上下微挪字盒（2026-11-08 鎖死水平對價）。
    - 字 X＝同一欄（預設對齊長標如「7/29低…」那欄），不准左一截右一截。
    - 虛線：轉折錨／左側 → 穿過末根 tip → 標籤左緣；水平接到標前短虛線。
      不准只剩右欄短 stub（末根 x≈標籤時往左拉開可見長度）。
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
    # 字盒視覺高度約略；nudge 用這個當最小字距（框高約 5% 窗，再加呼吸）
    # 標多時加寬字距，不准框疊框把數字／日期蓋住
    n_items_est = len(items)
    box_gap = max(gap * 0.95, span * (0.078 if n_items_est >= 5 else 0.062))
    if n_items_est >= 7:
        box_gap = max(box_gap, span * 0.088)

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
            or "電盤大量" in s
            or "電盤即時" in s
            or "C-7" in s
            or "C-8" in s
            or "C-9" in s
            or "大C今" in s
            or "大B末" in s
            or "已破" in s
            # 雙軌關鍵位：數字＋虛線必留
            or "37,837" in s
            or "37837" in s
            or "31,705" in s
            or "31705" in s
            or "35,579" in s
            or "35579" in s
            or "最佳買點" in s
            or "AI結束" in s
            or "五波末" in s
            # 水平台指壓41760／回測平均／回測最低：當令必留
            or "台指壓力" in s
            or "41,760" in s
            or "41760" in s
            or "回測平均" in s
            or "回測最低" in s
            or "至少回測" in s
            or "41,500" in s
            or "41500" in s
            or "絕對不破" in s
        ):
            return 0
        # 電盤下一層可丟；一般飆預測次之（已破／C9 已升 0）
        if "電盤下一層" in s:
            return 2
        if "飆預測" in s and "電盤" not in s:
            return 1
        return 1

    def _pri(d: Dict[str, Any]) -> Tuple[int, int, float]:
        t = str(d.get("text") or "")
        # 同 tier 內：雙軌關鍵價優於一般「已破／今」浪標，避免 38000已破擠掉 37837
        dual_rank = 0 if _is_dual_key(t) else 1
        return (_tier(t), dual_rank, -float(d["y"]))

    def _is_dual_key(t: str) -> bool:
        s = str(t or "")
        return any(
            x in s
            for x in (
                "37,837",
                "37837",
                "31,705",
                "31705",
                "35,579",
                "35579",
                "最佳買點",
                "AI結束",
                "五波末",
                "台指壓力",
                "41,760",
                "41760",
                "回測平均",
                "回測最低",
                "至少回測",
                "41,500",
                "41500",
                "絕對不破",
            )
        )

    def _collide(
        y0: float,
        tier: int,
        kept_ys: List[float],
        kept_tiers: List[int],
        *,
        text: str = "",
        kept_texts: Optional[List[str]] = None,
    ) -> bool:
        kt_texts = kept_texts or []
        for i, (ky, kt) in enumerate(zip(kept_ys, kept_tiers)):
            # 兩個浪標：用較緊間距，才留得下 c4／c5／今
            thresh = gap_wave if (tier == 0 and kt == 0) else gap * 0.85
            # 雙軌／下週底關鍵價（含 39000↔今）可更近，仍各自水平虛線，不准折接
            other_t = kt_texts[i] if i < len(kt_texts) else ""
            if _is_dual_key(text) or _is_dual_key(other_t):
                thresh = max(span * 0.012, 180.0)
            # 右欄價標字盒約 400–500 點高：回測／飆預測互近必蓋字（42300↔41900）
            def _price_box(t0: str) -> bool:
                s0 = str(t0 or "")
                return any(
                    x in s0
                    for x in (
                        "回測",
                        "飆預測",
                        "台指壓力",
                        "C3底",
                        "絕對不破",
                        "不再假跌破",
                    )
                )

            if _price_box(text) and _price_box(other_t):
                thresh = max(thresh, span * 0.05, 650.0)
            if abs(y0 - ky) < thresh:
                return True
        return False

    items.sort(key=_pri)
    # 同價只留優先（大B末 vs B；今 vs C-7轉C-8今）
    deduped: List[Dict[str, Any]] = []
    seen_px: set = set()
    for it in items:
        try:
            key_px = round(float(it["y"]), 0)
        except (TypeError, ValueError):
            key_px = None
        if key_px is not None and key_px in seen_px:
            continue
        if key_px is not None:
            seen_px.add(key_px)
        deduped.append(it)
    items = deduped
    kept: List[Dict[str, Any]] = []
    kept_ys: List[float] = []
    kept_tiers: List[int] = []
    kept_texts: List[str] = []
    for it in items:
        y0 = float(it["y"])
        t = str(it.get("text") or "")
        tier = _tier(t)
        it = dict(it)
        if _collide(y0, tier, kept_ys, kept_tiers, text=t, kept_texts=kept_texts):
            # 真價互撞：改次欄（X 左移），Y 仍鎖真價；視覺框仍太近才丟
            if any(abs(y0 - ky) < max(box_gap * 0.55, span * 0.028) for ky in kept_ys):
                continue
            it["_col2"] = True
        kept.append(it)
        kept_ys.append(y0)
        kept_tiers.append(tier)
        kept_texts.append(t)
    # 新飆大點位可進席；超過軟上限丟低優先，雙軌／今／已破（tier0）必留
    soft = max(4, int(_TEACH_RIGHT_SOFT_CAP or 9))
    if len(kept) > soft:
        order = sorted(
            range(len(kept)),
            key=lambda i: (
                int(kept_tiers[i]),
                0 if _is_dual_key(kept_texts[i]) else 1,
                -float(kept[i]["y"]),
            ),
        )[:soft]
        kept = [kept[i] for i in order]
    kept.sort(key=lambda d: float(d["y"]), reverse=True)
    placed: List[float] = []
    placed_tiers: List[int] = []
    placed_texts: List[str] = []
    draw_items: List[Tuple[Dict[str, Any], float]] = []
    # 同一右欄現況槽：末根＋固定 gutter（滾窗後圖右位置幾乎不變）
    x_label = _teach_right_col_x(int(n), x_col=x_col)
    if x_text_min is not None:
        try:
            x_label = max(x_label, float(x_text_min) + 0.85)
        except (TypeError, ValueError):
            pass
    for it in kept:
        y_true = float(it["y"])
        if y_true < ymin or y_true > ymax:
            continue
        t = str(it.get("text") or "")
        tier = _tier(t)
        # 真價互撞：已標 _col2 則收進次欄；否則丟低優先。不准漂 Y。
        if _collide(
            y_true, tier, placed, placed_tiers, text=t, kept_texts=placed_texts
        ):
            if it.get("_col2"):
                pass
            else:
                continue
        placed.append(y_true)
        placed_tiers.append(tier)
        placed_texts.append(t)
        draw_items.append((it, y_true))
    # 標籤 Y 鎖死真價（draw_ys 僅相容迴圈；不再上下微挪）
    draw_ys: List[float] = [y for _, y in draw_items]
    _ = (nudge, box_gap)  # 相容保留參數；不再用於漂 Y
    x_tip = max(0.0, float(n) - 1.0)
    # 虛線至少跨末根左側一段，才對得起現價垂直距離
    dash_span_need = max(14.0, float(max(n, 1)) * 0.20)
    for (it, y_true), _y_ignored in zip(draw_items, draw_ys):
        # 鎖死：標籤 Y＝真價；虛線同水平；不准上下漂
        y_draw = float(y_true)
        color = str(it.get("color") or _LIVE_MUTED)
        x_this = float(x_label) - (2.35 if it.get("_col2") else 0.0)
        try:
            x_from = float(it.get("x"))
        except (TypeError, ValueError):
            x_from = 0.0
        x_from = max(0.0, float(x_from))
        # 錨太靠近 tip／標籤 → 往左拉開；有較早轉折日則保留（從點位拉到 tip）
        if x_from >= x_tip - dash_span_need * 0.45:
            x_from = max(0.0, x_tip - dash_span_need)
        # 虛線穿過末根 tip，水平接到標籤左緣（標前短虛線與長虛線同一水平）
        x_dash_end = max(x_from + 0.35, float(x_this) - 0.48)
        if level_dash and it.get("dash", True) and x_dash_end > x_from + 0.15:
            # 標多時改更細虛線，仍對得上右欄數字；少標維持可讀粗細
            n_dash = sum(
                1
                for d, _y in draw_items
                if d.get("dash", True) and level_dash
            )
            if n_dash >= 7:
                lw_d, ls_d, al_d = 0.55, (0, (1.6, 2.4)), 0.62
            elif n_dash >= 5:
                lw_d, ls_d, al_d = 0.72, (0, (2.2, 2.2)), 0.70
            else:
                lw_d, ls_d, al_d = 1.05, (0, (3.2, 2.0)), 0.82
            ax.plot(
                [x_from, x_dash_end],
                [y_true, y_true],
                color=color,
                lw=lw_d,
                ls=ls_d,
                alpha=al_d,
                zorder=5,
                solid_capstyle="butt",
                clip_on=False,  # 與右欄標同可見；不准 xlim 裁掉標前虛線
            )
        # 價・日期／狀態完整可見；長標略放寬裁切，不准黏字難讀
        lab_txt = str(it["text"] or "")
        if "・" in lab_txt:
            lab_txt = lab_txt[:34]
        else:
            lab_txt = lab_txt[:28]
        ax.text(
            x_this,
            float(y_draw),
            lab_txt,
            fontproperties=fp(float(fontsize), "normal"),
            color=color,
            ha="left",
            va="center",  # 鎖死：框中心＝真價＝虛線
            zorder=10,
            clip_on=False,
            bbox=dict(boxstyle="round,pad=0.10", fc="#0b0f14", ec=color, lw=0.5, alpha=0.96),
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
    elif re.search(r"C3-5|(?:今天)?走\s*3-5|(?<![0-9])3-5(?![0-9])", s):
        # 他寫 C3-5／今天走3-5（11/5 假跌破回文）；不准發明沒寫過的段號
        degree = "C3-5"
    elif re.search(r"C3-", s):
        degree = "C3"
    elif re.search(r"(現在在C|下降ABC.*C|主跌段)", s):
        degree = "C"
    # 下降壓改口／止跌／週五低確認（後文壓雙軌／第二隻腳／C9）
    if _text_has_c3_pressure_break(s) or _text_has_stop_low_confirm(s):
        degree = "止跌確認"
    # 改口第二隻腳（後文壓 9波／C9 低點區）
    elif _text_has_foot2_revision(s):
        degree = "第二隻腳"
    # 9波擴延 C-7／C-8／C-9（必帶連字號，不准誤吃 C3-7）
    elif re.search(
        r"9\s*波\s*擴延|C\s*[-–]\s*7.{0,24}C\s*[-–]\s*8|C\s*[-–]\s*9|"
        r"35500\s*[-~～到至]\s*37300|七走完|準備往\s*八|往八走",
        s,
    ):
        if re.search(
            r"七走完|準備往\s*八|往八走|C-7轉C-8|"
            r"C\s*[-–]\s*7.{0,20}(?:轉|->|→|走完).{0,12}C\s*[-–]\s*8",
            s,
        ):
            degree = "C-8"
        elif re.search(r"C\s*[-–]\s*9", s) and not re.search(
            r"C\s*[-–]\s*7|C\s*[-–]\s*8", s
        ):
            degree = "C-9"
        elif re.search(r"C\s*[-–]\s*7", s):
            degree = "C-7"
        elif re.search(r"C\s*[-–]\s*8", s):
            degree = "C-8"
        elif re.search(r"C\s*[-–]\s*9", s):
            degree = "C-9"
    chain = "五波→ABC→C"
    if degree.startswith("C3"):
        chain = "五波→ABC→C→C3-3" if "C3-3" in degree else "五波→ABC→C→C3"
    if degree == "C3-5":
        chain = "五波→ABC→C→C3-5"
    if degree in ("C3-3-1", "C3-3-2", "C3-3-3", "C3-3-4"):
        chain = f"五波→ABC→C→C3-3→{degree}"
    if degree in ("C-7", "C-8", "C-9"):
        chain = "五波→ABC→C→9波擴延→C-7→C-8→C-9"
    if degree == "第二隻腳":
        chain = "五波→ABC→C→等第二隻腳"
    if degree == "止跌確認":
        chain = "五波→ABC→C→C3-5＋1 4重疊→止跌確認"
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
    # 下跌預估虛線只指向「仍低於現價」的下一錨；上方壓（45546穿刺／46292／站穩47500）不當下一錨
    below = [a for a in chain if float(a) < float(y_now) - 1.0]
    use_chain = below if below else chain
    anchor_y: Optional[float] = None
    fut_y = float(use_chain[-1])
    lab = _biaoke_pred_label(fut_y, _level_break_tag(fut_y, lows))
    for a in use_chain:
        tag = _level_break_tag(a, lows)
        if tag != "已破":
            fut_y = float(a)
            anchor_y = float(a)
            lab = _biaoke_pred_label(a, tag)
            break
    else:
        # 全破：仍標最後一錨狀態
        fut_y = float(use_chain[-1])
        anchor_y = float(use_chain[-1])
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
    draw: bool = True,
) -> Dict[str, Any]:
    """在今之後畫預估虛線＋標；回傳 tip 方便調 xlim。

    keep_left_of_right＝True 時標停在右欄左側，不准跟右價標互壓。
    draw＝False：只算 tip（9波主路徑會自己畫分色虛線，不准再疊一條粉虛線）。
    """
    tip = _c_forecast_tip(
        i_now=i_now, y_now=y_now, y_ref=y_ref, lows=lows, anchors=anchors
    )
    fut_x, fut_y = float(tip["fut_x"]), float(tip["fut_y"])
    lab_y = float(fut_y)
    if draw:
        ax.plot(
            [i_now, fut_x],
            [y_now, fut_y],
            color="#0b0f14",
            lw=2.85,
            ls=(0, (4.0, 2.0)),
            alpha=0.95,
            zorder=5.9,
        )
        ax.plot(
            [i_now, fut_x],
            [y_now, fut_y],
            color="#ea80fc",
            lw=1.95,
            ls=(0, (4.0, 2.0)),
            alpha=0.92,
            zorder=6,
        )
        _spear_ring(ax, fut_x, fut_y, color="#ea80fc", zorder=7, hot=True)
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
    # 後文下降壓改口壓止跌再測假跌破／雙軌／第二隻腳／C9；雙軌壓第二隻腳／C9
    has_pressure_ladder = (
        _text_has_c3_pressure_break(text)
        or "不再假跌破" in thesis
        or "過C3下降壓" in thesis
        or "回測下降壓力線" in text
    )
    has_stop_ladder = (not has_pressure_ladder) and (
        deg == "止跌確認"
        or _text_has_stop_low_confirm(text)
        or "確認上週五低" in thesis
        or "1 4重疊" in thesis
        or "止跌確認" in thesis
    )
    has_bb_ladder = (not has_pressure_ladder) and (not has_stop_ladder) and (
        _text_has_bb_dual_path(text)
        or "B-b" in thesis
        or "五波跌完" in thesis
        or "備線九波" in thesis
    )
    if has_pressure_ladder:
        steps.append("止跌確認・已過C3下降壓")
    elif has_stop_ladder:
        steps.append("止跌確認・再測週五低")
    elif has_bb_ladder:
        steps.append("主B-b／備九波")
    elif (
        deg == "第二隻腳"
        or "第二隻腳" in thesis
        or "等第二隻腳" in thesis
        or _text_has_foot2_revision(text)
    ):
        steps.append("等第二隻腳")
    elif (
        deg in ("C-7", "C-8", "C-9")
        or "9波擴延" in thesis
        or "C-7轉C-8" in thesis
        or "C-7走完" in thesis
        or "準備往八" in thesis
    ):
        steps.append("9波擴延")
        if deg == "C-9":
            steps.extend([_c9_now_step_label(), "C-9"])
        elif deg == "C-7":
            steps.append("C-7")
        else:
            steps.append(_c9_now_step_label())
    elif deg in ("C3-3-1", "C3-3-2", "C3-3-3", "C3-3-4"):
        steps.extend(["C3-3主跌", deg])
    elif "3→4" in thesis:
        steps.extend(["C3-3主跌", "C3-3-4"])
    elif deg.startswith("C3-3") or ("C3-3" in thesis and "橫台" not in thesis):
        steps.append("C3-3主跌")
    elif deg == "C3-5" or "C3-5" in thesis or re.search(
        r"(?:今天)?走\s*3-5|(?<![0-9])3-5(?![0-9])", thesis
    ):
        steps.append("C3-5")
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
    # 下降壓改口／止跌確認／雙軌／改口第二隻腳／9波擴延：話筒／超近說明用人話，不准只丟代號
    if "止跌確認・已過C3下降壓" in steps or has_pressure_ladder:
        _rb_now = _retest_avg_min_from_text(text)
        if _rb_now is not None:
            if abs(float(_rb_now["avg"]) - float(_rb_now["min"])) < 0.6:
                oral_now = (
                    f"回測平均＝最低{_px(_rb_now['min'])}；"
                    "絕對不破週五低37837；"
                    "他說已過C3下降壓（口述斜線・無報價）"
                )
            else:
                oral_now = (
                    f"回測平均{_px(_rb_now['avg'])}；"
                    f"回測最低{_px(_rb_now['min'])}；"
                    "絕對不破週五低37837；"
                    "他說已過C3下降壓（口述斜線・無報價）"
                )
            if "41760" in text:
                oral_now = "水平台指壓41760（≠回測帶）；" + oral_now
        elif _text_has_retest_41500(text) or "至少回測41500" in text:
            oral_now = (
                f"回測平均＝最低{_px(41500)}；絕對不破週五低37837；"
                "他說已過C3下降壓（口述斜線・無報價）"
            )
            if "41760" in text:
                oral_now = "水平台指壓41760（≠41500）；" + oral_now
        else:
            oral_now = (
                "他說已過C3下降壓（口述斜線・圖上紫帶C3・粉虛下降壓示意／無報價）；"
                "週五低不再假跌破；拉回再測那條下降壓"
            )
            if "41760" in text:
                oral_now = "水平台指壓41760（≠那條口述下降壓）；" + oral_now
        one_line = "現在：止跌確認・已過C3下降壓（預估）"
        now_line = (
            oral_now
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            "現在走到（大→小）\n"
            f"{chain}\n"
            f"{oral_now}"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    elif "止跌確認・再測週五低" in steps or has_stop_ladder:
        oral_now = (
            "C3-5＋1 4重疊・確認上週五低＝最低；"
            "一定再測週五低，破＝假跌破觀察"
        )
        if "41760" in text:
            oral_now = "台指壓41760；" + oral_now
        one_line = "現在：止跌確認・再測週五低（預估）"
        now_line = (
            oral_now
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            "現在走到（大→小）\n"
            f"{chain}\n"
            f"{oral_now}"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    elif "主B-b／備九波" in steps or has_bb_ladder:
        oral_now = "主線五波跌完走B-b（假跌破37837觀察）；備線九波→35579→31705"
        one_line = "現在：主B-b／備九波雙軌（預估）"
        now_line = (
            oral_now
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            "現在走到（大→小）\n"
            f"{chain}\n"
            f"{oral_now}"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    elif "等第二隻腳" in steps or deg == "第二隻腳":
        oral_now = _foot2_oral_now_line()
        one_line = "現在：夜盤跌完居多・等第二隻腳（預估）"
        now_line = (
            oral_now
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            "現在走到（大→小）\n"
            f"{chain}\n"
            f"{oral_now}"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    elif "9波擴延" in steps or deg in ("C-7", "C-8", "C-9"):
        oral_now = _c9_oral_now_line()
        one_line = f"現在：9波擴延・{_c9_now_step_label()}→C-9（預估）"
        now_line = (
            oral_now
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            "現在走到（大→小）\n"
            f"{chain}\n"
            f"{oral_now}"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    else:
        one_line = f"現在走到：{chain}"
        now_line = (
            f"落在「{now}」"
            + (f"・{day_bit}" if day_bit else "")
            + "・預估會改・非買訊"
        )
        teach_box = (
            f"現在走到（大→小）\n"
            f"{chain}\n"
            f"落在「{now}」"
            + (f"・{day_bit}" if day_bit else "")
            + "\n預估會改・非買訊"
        )
    return {
        "steps": steps,
        "chain": chain,
        "now": now,
        "degree": deg,
        "day_zh": day_zh,
        "day_bit": day_bit,
        "one_line": one_line,
        "now_line": now_line,
        "teach_box": teach_box,
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
        "ymd_5_start": _ymd(bars[int(i5s)].get("date")),
        "ymd_5_end": _ymd(bars[int(i5e)].get("date")),
        "ymd_alow": _ymd(bars[int(i_alow)].get("date")),
        "ymd_b_end": _ymd(bars[int(i_bend)].get("date")),
        "ymd_c": _ymd(bars[int(i_c)].get("date")),
    }


def _clamp_macro_wave_to_window(
    mac: Dict[str, Any],
    bars_window: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """定長滾動後：尖點 x 對到窗內；滾出左緣的釘在 x=0（價仍用完整柱真值）。

    右欄現況標不走這裡。尖點滾出＝跟左緣走／或由右欄價位承接，不准幽靈 x。
    """
    if not mac or not bars_window:
        return None
    by = {_ymd(r.get("date")): i for i, r in enumerate(bars_window) if _ymd(r.get("date"))}
    left = _ymd(bars_window[0].get("date"))
    n = len(bars_window)

    def _xi(ymd: str, fallback: int) -> int:
        d = _ymd(ymd)
        if d and d in by:
            return int(by[d])
        if d and left and d < left:
            return 0
        return int(fallback)

    i5s = _xi(str(mac.get("ymd_5_start") or ""), 0)
    i5e = _xi(str(mac.get("ymd_5_end") or ""), min(1, n - 1))
    i_alow = _xi(str(mac.get("ymd_alow") or ""), min(2, n - 1))
    i_bend = _xi(str(mac.get("ymd_b_end") or ""), min(3, n - 1))
    i_c = _xi(str(mac.get("ymd_c") or ""), min(4, n - 1))
    # 滾掉前段時允許左緣重疊；仍須 A→B→C 順序在窗內站得住
    if not (i_alow < i_bend <= i_c < n):
        return None
    if i5e > i_alow:
        i5e = int(i_alow)
    if i5s > i5e:
        i5s = int(i5e)
    highs = [float(r.get("high") or 0) for r in bars_window]
    lows = [float(r.get("low") or 0) for r in bars_window]
    closes = [float(r.get("close") or 0) for r in bars_window]
    out = dict(mac)
    out.update(
        {
            "i5_start": int(i5s),
            "i5_end": int(i5e),
            "i_a_start": int(i5e),
            "i_alow": int(i_alow),
            "i_b_start": int(i_alow),
            "i_b_end": int(i_bend),
            "i_c": int(i_c),
            "i_now": int(n - 1),
            "y_now": float(closes[-1]),
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "clipped_left": bool(left and str(mac.get("ymd_5_start") or "") < left),
        }
    )
    return out


def _macro_wave_calendar_line() -> str:
    """三張＋縮圖共用浪階日曆字（Asia/Taipei 交易日）。"""
    return "⑤＝4/1→6/23｜A＝6/23→7/29｜B＝7/29→10/6｜C＝10/6→今（確認10/15）"


def _eight_wave_now_key(pack: Optional[Dict[str, Any]] = None) -> str:
    """從層級鏈取八浪縮圖此刻鍵（大結構落在修正波 C）。

    C3-3-x 細碼必須完整保留給閃折①～⑤，不准裁成裸 C。
    9波擴延題旨回 C-8（七走完、準備往八；虛線接 C-9）。
    """
    if _c9_extension_active(pack):
        now = str((_wave_now_ladder(pack) or {}).get("now") or "").strip()
        if now == "C-9" or now.endswith("C-9"):
            return "C-9"
        if now == "C-7":
            return "C-7"
        return "C-8"
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


def _c9_ext_flash_step(now_key: str) -> int:
    """9波擴延縮圖：此刻落在 C-1…C-9 哪一尖（1-based；七走完→準備往八＝C-8）。"""
    nk = str(now_key or "").upper().replace(" ", "")
    raw = str(now_key or "")
    if "C-9" in nk or nk.endswith("9"):
        return 9
    if "C-7" in nk and "8" not in nk and "走完" not in raw:
        return 7
    if (
        "C-8" in nk
        or "C-7轉C-8" in raw
        or "C-7走完" in raw
        or "準備往八" in raw
    ):
        return 8
    return 8


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


def _eight_wave_inset_rect_on_vol(
    axv: Any,
    fig: Any,
    *,
    scale: float = 0.92,
    left_frac: float = 0.06,
) -> Tuple[float, float, float, float]:
    """超近窗：八浪縮圖貼量欄左側空帶（使用者紅框區），不准壓右半爆量柱。"""
    w, h = _teach_eight_wave_inset_wh(fig)
    sc = max(0.45, min(1.05, float(scale or 1.0)))
    w, h = float(w) * sc, float(h) * sc
    try:
        pos = axv.get_position()
        left = float(pos.x0) + float(pos.width) * max(0.02, min(0.20, float(left_frac)))
        # 垂直置中於量欄；略上移避開 x 刻度
        bottom = float(pos.y0) + float(pos.height) * 0.18
        max_h = float(pos.height) * 0.78
        if h > max_h:
            w *= max_h / h
            h = max_h
        max_w = float(pos.width) * 0.42
        if w > max_w:
            h *= max_w / w
            w = max_w
        if bottom + h > float(pos.y1) - 0.01:
            bottom = max(float(pos.y0) + 0.01, float(pos.y1) - 0.01 - h)
        return (float(left), float(bottom), float(w), float(h))
    except Exception:
        return (0.06, 0.08, float(w), float(h))


def _paint_micro_retest_then_rise_schematic(
    ax: Any,
    *,
    i_now: int,
    y_now: float,
    retest_y: float,
    fp: Any,
    n: int,
    x_label_col: Optional[float] = None,
) -> Dict[str, Any]:
    """超近窗預估虛線：今→他釘回測位；再示意「C走完→新五波升」。

    回測價只認當令「回測平均」（無則最低／舊單點）；主升不准發明目標價。
    右欄另標回測平均／回測最低；虛線端不准再貼價標。
    x_label_col＝右側空帶欄位，示意標對齊右欄，不准擋K／浪折。非買訊；會改。
    """
    out: Dict[str, Any] = {"fut_x": float(i_now + 4), "retest_y": float(retest_y)}
    if ax is None or fp is None:
        return out
    try:
        y_rt = float(retest_y)
        y0 = float(y_now)
        i0 = int(i_now)
    except (TypeError, ValueError):
        return out
    if y_rt <= 0 or y0 <= 0:
        return out
    # 今已低於回測位：不再畫「往下回測」假路徑（只留主升示意會誤導）
    if float(y0) <= float(y_rt) + 1.0:
        return out
    # 兩段 x：回測折點 → 主升示意端（只延長幾根，不准拉爆右欄）
    x1 = float(i0 + 3)
    x2 = float(i0 + 7)
    y_mid = float(y_rt)
    # 主升示意端：略高於回測位即可，不准拉高到跟「今」右標互壓、不准寫死目標價
    y_up = float(y_rt) + max(abs(float(y0) - float(y_rt)) * 0.28, 520.0)
    # 底描＋紫虛＝回測（對準平均）
    ax.plot(
        [i0, x1],
        [y0, y_mid],
        color="#0b0f14",
        lw=2.7,
        ls=(0, (4.0, 2.0)),
        zorder=5.85,
    )
    ax.plot(
        [i0, x1],
        [y0, y_mid],
        color="#ea80fc",
        lw=1.85,
        ls=(0, (4.0, 2.0)),
        zorder=5.95,
    )
    _spear_ring(ax, x1, y_mid, color="#ea80fc", zorder=7, hot=True)
    # 回測價標只留右欄「回測平均／回測最低」；不准虛線端再貼價
    # 青虛＝C走完後新五波升示意（無目標價）
    ax.plot(
        [x1, x2],
        [y_mid, y_up],
        color="#0b0f14",
        lw=2.5,
        ls=(0, (3.0, 2.2)),
        zorder=5.85,
    )
    ax.plot(
        [x1, x2],
        [y_mid, y_up],
        color="#40c4ff",
        lw=1.7,
        ls=(0, (3.0, 2.2)),
        zorder=5.95,
    )
    _spear_ring(ax, x2, y_up, color="#40c4ff", zorder=7, hot=False)
    # 上升虛線中段取點：附圖式紅箭＋圈5 → 細虛指引到右側標（不准擠折點／右欄）
    try:
        from matplotlib.patches import Circle, FancyArrowPatch
    except Exception:
        Circle = None  # type: ignore
        FancyArrowPatch = None  # type: ignore
    t_arr = 0.62
    x_arr = float(x1) + (float(x2) - float(x1)) * t_arr
    y_arr = float(y_mid) + (float(y_up) - float(y_mid)) * t_arr
    # 箭尖略往右上，離開K線／折點擁擠區
    x_tip = float(x_arr) + max(2.2, (float(n) - float(x_arr)) * 0.22 + 1.2)
    y_tip = float(y_arr) + max(abs(float(y_up) - float(y_mid)) * 0.85, 680.0)
    try:
        ax.annotate(
            "",
            xy=(float(x_tip), float(y_tip)),
            xytext=(float(x_arr), float(y_arr)),
            arrowprops={
                "arrowstyle": "-|>",
                "color": "#ff1744",
                "lw": 2.35,
                "mutation_scale": 18.0,
                "shrinkA": 0,
                "shrinkB": 0,
                "alpha": 0.88,
            },
            zorder=7.5,
            clip_on=False,
        )
    except Exception:
        logger.debug("新五波升示意紅箭略過", exc_info=True)
    # 圈5貼紅箭中段外側（對附圖）
    x_c5 = float(x_arr) + (float(x_tip) - float(x_arr)) * 0.55
    y_c5 = float(y_arr) + (float(y_tip) - float(y_arr)) * 0.40
    if Circle is not None:
        try:
            # 圓半徑用點數（transform 會依軸），改 annotate 圓點＋字較穩
            ax.plot(
                [x_c5],
                [y_c5],
                marker="o",
                markersize=13,
                markerfacecolor="#101418",
                markeredgecolor="#ffffff",
                markeredgewidth=1.2,
                zorder=8.2,
                clip_on=False,
            )
            ax.text(
                x_c5,
                y_c5,
                "5",
                ha="center",
                va="center",
                fontproperties=fp(8.0, "bold"),
                color="#ffffff",
                zorder=8.3,
                clip_on=False,
            )
        except Exception:
            logger.debug("新五波升圈5略過", exc_info=True)
    # 標籤進右側空帶（與右欄同欄）；箭尖→字用青虛線接，不准擋K／浪折
    try:
        x_lab = float(x_label_col) if x_label_col is not None else float(n) + 8.8
    except (TypeError, ValueError):
        x_lab = float(n) + 8.8
    x_lab = max(float(x_lab), float(x_tip) + 1.0, float(n) + 8.0)
    y_lab = float(y_tip) + max(abs(float(y_up) - float(y_mid)) * 0.03, 70.0)
    if FancyArrowPatch is not None:
        try:
            ax.add_patch(
                FancyArrowPatch(
                    (float(x_tip), float(y_tip)),
                    (float(x_lab) - 0.12, float(y_lab)),
                    arrowstyle="-",
                    linestyle=(0, (2.2, 1.6)),
                    color="#40c4ff",
                    linewidth=0.95,
                    mutation_scale=1,
                    zorder=7.6,
                    clip_on=False,
                )
            )
        except Exception:
            logger.debug("新五波升指引線略過", exc_info=True)
    ax.text(
        x_lab,
        y_lab,
        "C走完→新五波升\n（示意・非買訊）",
        fontproperties=fp(7.4, "bold"),
        color="#40c4ff",
        ha="left",
        va="bottom",
        zorder=8.4,
        linespacing=1.05,
        bbox={
            "boxstyle": "round,pad=0.10",
            "facecolor": "#061018",
            "edgecolor": "#40c4ff",
            "linewidth": 0.7,
            "alpha": 0.9,
        },
        clip_on=False,
    )
    out["fut_x"] = max(float(x2), float(x_lab) + 3.4)
    out["fut_y"] = max(float(y_up), float(y_lab))
    out["xlim_right"] = max(float(n) + 1.2, float(x_lab) + 4.6, float(x_tip) + 2.2)
    return out


def _paint_eight_wave_inset(
    fig: Any,
    *,
    fp: Any,
    now_key: str = "C",
    detail: bool = False,
    c_flash: bool = False,
    flash_pivots: Optional[Sequence[Tuple[int, float, str]]] = None,
    rect: Sequence[float] = (0.72, 0.62, 0.26, 0.28),
    title: str = "八浪對位",
    c9_ext: bool = False,
    now_tip: str = "",
) -> None:
    """三張教具共用：教科書八浪縮圖；detail 框此刻；c_flash＝超近在C內畫下殺閃折①～⑤。

    c9_ext＝True：C 內改畫 9 波擴延（C1…C9）；此刻七走完→C-8，C8→C9 虛線（教具示意，非買訊）。
    now_tip＝覆寫黃框「此刻＝…」字（超近可寫大C＋內C4）。
    """
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    ax = fig.add_axes(list(rect))
    ax.set_facecolor("#0e151c")
    for sp in ax.spines.values():
        sp.set_color("#546e7a")
        sp.set_linewidth(0.7)
    ax.set_xticks([])
    ax.set_yticks([])
    nk = str(now_key or "C")
    use_c9 = bool(c9_ext) or nk.startswith("C-")
    if use_c9 and not title:
        title = "九波擴延"
    elif use_c9 and ("八浪" in str(title) or title == "八浪對位"):
        title = "九波擴延・C"
    # 線／字／標記一律細體；黃框線也改細（手機縮圖才不糊成一團）
    _lw = 1.05
    _lw_dash = 1.15
    _fs_lab = 6.5 if not detail else 7.5
    _fs_tip = 6.5
    _fs_note = 5.5
    _fs_foot = 5.5
    _fs_title = 7.5
    # 簡化八浪折線；色碼跟主圖一致：藍⑤／粉A／金虛B／紫C
    # 鐵律：起→1…5→A→B→C 的 x 嚴格遞增；A 必須在黃框（B→C）左側外
    if c_flash or use_c9:
        # 左：推進；中：A低→B反彈（都在黃框外）；右黃框：只裝 B→C 緩坡閃折／9波
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
        lw=_lw,
        zorder=3,
    )
    # 修正A（粉）
    ax.plot(
        [pts[5][0], pts[6][0]],
        [pts[5][1], pts[6][1]],
        color=col_a,
        lw=_lw,
        zorder=3,
    )
    # 修正B（金虛＝主圖大B）
    ax.plot(
        [pts[6][0], pts[7][0]],
        [pts[6][1], pts[7][1]],
        color=col_b,
        lw=_lw_dash,
        ls=(0, (5, 1.6)),
        zorder=3,
    )
    # 修正C：無閃折時畫紫實線；有閃折時只留極淡底軸，主路徑改細閃（避免雙線錯位）
    if c_flash:
        ax.plot(
            [pts[7][0], pts[8][0]],
            [pts[7][1], pts[8][1]],
            color=col_c,
            lw=1.6,
            alpha=0.20,
            zorder=2.5,
            solid_capstyle="round",
        )
    else:
        ax.plot(
            [pts[7][0], pts[8][0]],
            [pts[7][1], pts[8][1]],
            color=col_c,
            lw=_lw,
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
        "C-7": 8,
        "C-8": 8,
        "C-9": 8,
    }
    hi = 8
    for k, v in key_map.items():
        if nk == k or nk.upper().startswith(str(k).upper()):
            hi = v
            break
    # 高亮此刻：只墊底層光暈（z 低於色線），不准金光蓋掉粉A／金虛B／紫C
    if 1 <= hi < len(pts) and not c_flash and not use_c9:
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
                fontproperties=fp(5.5, "normal"),
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
            s=12 if not detail else 18,
            c=col,
            zorder=5,
            edgecolors="#fff",
            linewidths=0.25,
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
            fontproperties=fp(_fs_lab, "normal"),
            color=col,
            ha="center",
            va="center",
            zorder=6,
        )
    # 超近：黃框只包 B→C；閃折＝主圖同一套官方柱錨（flash_pivots），不准另編點
    # 真窗：B高→①C起日低→②反彈高→③更深低→④c4反彈→⑤今收
    # 9波擴延：框內改畫 C1…C9（教具示意）；C7→C8 金圈、C8→C9 虛線
    flash_pts: List[Tuple[float, float]] = []
    flash_step = 0
    flash_spec: List[Tuple[float, float, str]] = []
    do_flash = (c_flash or use_c9) and hi >= 8
    if do_flash:
        bx, by = pts[7]
        cx, cy = pts[8]
        dx, dy = cx - bx, cy - by
        if use_c9:
            # 優先＝主圖官方柱 C1…C8；缺才退回教具示意比例（仍標 C1…C9）
            raw_piv = [
                (int(i), float(y), str(lab))
                for i, y, lab in (flash_pivots or [])
                if str(lab) == "B" or str(lab).startswith("C")
            ]
            flash_spec = _flash_spec_from_pivots(raw_piv) if len(raw_piv) >= 4 else []
            has_c_labs = bool(
                flash_spec
                and any(str(lab).startswith("C") for _t, _d, lab in flash_spec)
            )
            if (not has_c_labs) or len(flash_spec) < 5:
                flash_spec = [
                    (0.00, 0.00, "B"),
                    (0.08, 0.22, "C1"),
                    (0.17, 0.12, "C2"),
                    (0.27, 0.38, "C3"),
                    (0.37, 0.26, "C4"),
                    (0.47, 0.52, "C5"),
                    (0.57, 0.40, "C6"),
                    (0.68, 0.72, "C7"),
                    (0.80, 0.58, "C8"),
                    (1.00, 1.00, "C9"),
                ]
            else:
                # 官方柱只到 C7／C8：t 壓到 0.82，末端補示意 C9（虛線用）
                scaled = [
                    (min(0.82, float(t) * 0.82), float(d), str(lab))
                    for t, d, lab in flash_spec
                    if str(lab) != "C9"
                ]
                if scaled:
                    scaled[0] = (0.0, 0.0, scaled[0][2])
                flash_spec = scaled + [(1.00, 1.00, "C9")]
            flash_step = _c9_ext_flash_step(nk)
        else:
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
            flash_step = _c_flash_step(nk)
        for t, drop, _lab in flash_spec:
            flash_pts.append((bx + dx * t, by + dy * drop))
        flash_pts[0] = (bx, by)
        # 非 9 波：末點鎖 C 框角；9 波末點＝C9 示意（不准被外框 C 蓋掉）
        if not use_c9:
            flash_pts[-1] = (cx, cy)
        elif flash_spec and str(flash_spec[-1][2]) == "C9":
            flash_pts[-1] = (cx, cy)
        lab_idx = {
            str(lab): j for j, (_t, _d, lab) in enumerate(flash_spec) if j < len(flash_pts)
        }
        if use_c9 and lab_idx:
            # 實線到 C7／C8：每段分色對齊主圖；C7／C8→C9 紫虛線
            solid_labs = [
                lab
                for lab in ("B", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8")
                if lab in lab_idx
            ]
            solid_i = [lab_idx[lab] for lab in solid_labs]
            for a, b in zip(solid_i, solid_i[1:]):
                lab_b = next(
                    (lb for lb, idx in lab_idx.items() if idx == b),
                    "C1",
                )
                col = _c9_wave_color(lab_b)
                if lab_b in {"C7", "C8"}:
                    lw_in = 1.55
                elif lab_b in {"C1", "C3", "C5"}:
                    lw_in = 1.25
                else:
                    lw_in = 1.10
                ax.plot(
                    [flash_pts[a][0], flash_pts[b][0]],
                    [flash_pts[a][1], flash_pts[b][1]],
                    color="#0b0f14",
                    lw=lw_in + 0.55,
                    zorder=6.1,
                    solid_capstyle="round",
                )
                ax.plot(
                    [flash_pts[a][0], flash_pts[b][0]],
                    [flash_pts[a][1], flash_pts[b][1]],
                    color=col,
                    lw=lw_in,
                    zorder=6.3,
                    solid_capstyle="round",
                )
            i7 = lab_idx.get("C7")
            i8 = lab_idx.get("C8")
            i9 = lab_idx.get("C9")
            if i7 is not None:
                dash_from = i8 if i8 is not None else i7
            else:
                dash_from = solid_i[-1] if solid_i else None
            if dash_from is not None and i9 is not None:
                ax.plot(
                    [flash_pts[dash_from][0], flash_pts[i9][0]],
                    [flash_pts[dash_from][1], flash_pts[i9][1]],
                    color="#0b0f14",
                    lw=1.55,
                    ls=(0, (3.2, 1.6)),
                    zorder=6.35,
                )
                ax.plot(
                    [flash_pts[dash_from][0], flash_pts[i9][0]],
                    [flash_pts[dash_from][1], flash_pts[i9][1]],
                    color=_c9_wave_color("C9"),
                    lw=1.20,
                    ls=(0, (3.2, 1.6)),
                    zorder=6.4,
                )
        else:
            fx = [p[0] for p in flash_pts]
            fy = [p[1] for p in flash_pts]
            ax.plot(fx, fy, color="#0b0f14", lw=1.55, zorder=6.1, solid_capstyle="round")
            ax.plot(fx, fy, color="#ffffff", lw=1.05, zorder=6.2, solid_capstyle="round")
            ax.plot(fx, fy, color="#ff5252", lw=0.85, zorder=6.3, solid_capstyle="round")
        for j, ((x, y), (_t, _d, lab)) in enumerate(zip(flash_pts, flash_spec)):
            if lab == "B":
                continue
            # flash_step：①～⑤ 用 j；C1…C9 用浪號
            if use_c9:
                try:
                    step_i = int(str(lab).lstrip("C"))
                except ValueError:
                    step_i = j
                is_now = step_i in (7, 8) if flash_step == 8 else step_i == flash_step
                seg_col = _c9_wave_color(lab)
            else:
                step_i = j
                is_now = step_i == flash_step
                seg_col = "#ffd54f" if is_now else "#ffffff"
            ax.scatter(
                [x],
                [y],
                s=22 if is_now else 12,
                c=seg_col,
                zorder=7,
                edgecolors="#111111",
                linewidths=0.35,
            )
            show_lab = lab if not use_c9 else str(lab).replace("C", "")
            ax.text(
                x + 0.010,
                y + (0.045 if (lab in ("②", "④", "C2", "C4", "C6", "C8")) else -0.048),
                show_lab,
                fontproperties=fp(6.5 if is_now else 5.5, "normal"),
                color=seg_col,
                ha="left",
                va="center",
                zorder=8,
            )
        if use_c9:
            # 金圈優先 C8；沒有 C8 就圈 C7（他說 C-7 轉 C-8）
            hot = lab_idx.get("C8")
            if hot is None:
                hot = lab_idx.get("C7")
            if hot is not None and hot < len(flash_pts):
                _spear_ring(
                    ax,
                    flash_pts[hot][0],
                    flash_pts[hot][1],
                    color="#ffd54f",
                    zorder=9,
                    hot=True,
                )
            i9 = lab_idx.get("C9")
            if i9 is not None and i9 < len(flash_pts):
                _spear_ring(
                    ax,
                    flash_pts[i9][0],
                    flash_pts[i9][1],
                    color="#ce93d8",
                    zorder=9,
                    hot=False,
                )
        elif 1 <= flash_step < len(flash_pts):
            sx, sy = flash_pts[flash_step]
            _spear_ring(ax, sx, sy, color="#ffd54f", zorder=9, hot=True)
    # 此刻框：detail＝近／超近要框選＋註；遠窗只圈點
    if 0 <= hi < len(pts):
        x0, y0 = pts[hi]
        x_l = pts[max(0, hi - 1)][0] - 0.05
        x_r = min(1.04, x0 + 0.10)
        y_b = min(y0, pts[max(0, hi - 1)][1]) - 0.12
        y_t = max(y0, pts[max(0, hi - 1)][1]) + 0.14
        if do_flash and flash_pts:
            # 黃框只包閃折（自 B 起），不准把 A 包進去造成「B→A→①」錯位感
            xs_f = [p[0] for p in flash_pts]
            ys_f = [p[1] for p in flash_pts]
            x_l = max(pts[7][0] - 0.02, min(xs_f) - 0.03)
            x_r = max(xs_f) + 0.06
            y_b = min(ys_f) - 0.08
            y_t = max(ys_f) + 0.10
        if detail or use_c9:
            ax.add_patch(
                plt.Rectangle(
                    (x_l, y_b),
                    x_r - x_l,
                    y_t - y_b,
                    fill=False,
                    ec="#ffd54f",
                    lw=0.85,
                    zorder=7,
                )
            )
            tip = f"此刻＝{nk}"
            if use_c9:
                tip = "此刻＝C-7轉C-8｜虛線＝C-9"
            elif c_flash and flash_step:
                tip = f"此刻＝{nk}・閃①～⑤之{flash_step}"
            tip_override = str(now_tip or "").strip()
            if tip_override:
                tip = tip_override
            ax.text(
                (x_l + x_r) / 2,
                min(1.05, y_t + 0.02),
                tip,
                fontproperties=fp(_fs_tip, "normal"),
                color="#ffd54f",
                ha="center",
                va="bottom",
                zorder=8,
            )
            # 細註：大結構對位（⑤＝4/1→6/23；今在修正 C）
            note = _macro_wave_calendar_line()
            if use_c9:
                note = "大＝⑤A B C｜框內＝9波擴延 C1…C9"
            elif c_flash:
                # 大結構同上；黃框內＝C內震盪①～⑤（＝主圖橙線）
                note = "大＝⑤A B C｜框內＝C震盪①～⑤"
            ax.text(
                0.50,
                0.98,
                note,
                fontproperties=fp(_fs_note, "normal"),
                color="#ffe082",
                ha="center",
                va="top",
                transform=ax.transAxes,
                zorder=8,
            )
        else:
            _spear_ring(ax, x0, y0, color="#ffd54f", zorder=7, hot=True)
            ax.text(
                x0,
                y0 - 0.14,
                f"今={nk}" if not use_c9 else "今=C-7→C-8",
                fontproperties=fp(_fs_tip, "normal"),
                color="#ffd54f",
                ha="center",
                va="top",
                zorder=8,
            )
    ax.set_xlim(-0.04, 1.06)
    ax.set_ylim(0.0, 1.10)
    ax.set_title(
        title,
        fontproperties=fp(_fs_title, "normal"),
        color="#eceff1",
        pad=2,
        loc="left",
    )
    foot = "藍＝1→5｜粉＝A｜金虛＝B｜紫＝C"
    if use_c9:
        foot = "框內9波｜金＝C7→C8｜虛線＝C9"
    elif c_flash:
        foot = "⑤AB框外對齊｜B末→C內①…⑤｜金圈＝此刻"
    ax.text(
        0.02,
        0.02,
        foot,
        fontproperties=fp(_fs_foot, "normal"),
        color="#90a4ae",
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
    # 題旨沒抽出費半點仍要留「費C今」右標（對齊電盤／加權右欄有重點標）
    if not preds:
        right_empty: List[Dict[str, Any]] = []
        if now_y is not None:
            right_empty.append(
                {
                    "x": int(i_now) if i_now is not None else max(int(n) - 1, 0),
                    "y": float(now_y),
                    "text": (now_lab or f"費C今{_px(float(now_y))}")[:26],
                    "color": "#ea80fc",
                }
            )
            if place:
                _place_live_right_labels(
                    ax,
                    right_empty,
                    n=n,
                    ymin=ymin,
                    ymax=ymax,
                    fp=fp,
                    level_dash=True,
                    min_gap=(ymax - ymin) * 0.08,
                    x_col=x_col,
                    x_text_min=x_text_min,
                )
        return right_empty
    broken_a = next((r for r in preds if str(r.get("role") or "") == "A波低"), None)
    nxt = next((r for r in preds if str(r.get("role") or "") == "次回測"), None)
    reb = next((r for r in preds if str(r.get("role") or "") == "再回測"), None)
    # 青帶＝上一已破撐 → 現在下一撐；9865 已破則對 2/25 8498
    y_hi = y_lo = None
    band_lab = ""
    try:
        if reb and nxt and str(nxt.get("tag") or "") == "已破":
            y_hi = float(nxt["level"])
            y_lo = float(reb["level"])
            band_lab = (
                f"青＝已破4/28{_px(y_hi)}→下一撐{_px(y_lo)}（2/25回測）"
            )
        elif broken_a and nxt:
            y_hi = float(broken_a["level"])
            y_lo = float(nxt["level"])
            band_lab = (
                f"青＝已破A{_px(y_hi)}→下一撐{_px(y_lo)}（4/28回測）"
            )
    except (TypeError, ValueError, KeyError):
        y_hi = y_lo = None
    if y_hi is not None and y_lo is not None and y_hi > y_lo:
        ax.axhspan(y_lo, y_hi, facecolor="#4dd0e1", alpha=0.14, zorder=0.4)
        # 青帶說明只留標題「費半青＝…」；不准再在左上貼字跟白底戳互壓
        _ = band_lab
    right: List[Dict[str, Any]] = []
    for row in preds:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        ref = _ymd(row.get("ref_ymd"))
        lab = str(row.get("label") or f"費{_px(lv)}")
        col = "#ffab40" if "已破" in str(row.get("tag") or lab) else "#4dd0e1"
        role = str(row.get("role") or "")
        ii = _bar_index_by_ymd(bars, ref) if ref else None
        # 只在「次回測／再回測」日畫金K＋豎線；A波低本身已有浪名，不准再豎一條誤導成大量日
        if (
            role in {"次回測", "再回測"}
            and ii is not None
            and 0 <= ii < len(sox_l)
        ):
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
    highs: Optional[Sequence[float]] = None,
) -> List[Dict[str, Any]]:
    """加權右欄：他最新寫死點（44042／39384…）；有 ref 日則虛線從那根拉。"""
    skip = tip_skip or set()
    out: List[Dict[str, Any]] = []
    hi_vals: List[float] = []
    if highs:
        try:
            hi_vals = [float(x) for x in highs if x is not None]
        except (TypeError, ValueError):
            hi_vals = []
    if not hi_vals and bars:
        for b in bars:
            try:
                hi_vals.append(float(b.get("high")))
            except (TypeError, ValueError, AttributeError):
                continue
    drop_script1 = _tw_has_c9_low_zone(pack)
    blob_tw = " ".join(
        str(x or "")
        for x in (
            (pack or {}).get("thesis"),
            (pack or {}).get("snippet"),
            (pack or {}).get("snippet_full"),
            (pack or {}).get("wait_struct"),
        )
    )
    bb_dual_active = _text_has_bb_dual_path(blob_tw) or (
        "B-b" in blob_tw or "五波跌完" in blob_tw or "備線九波" in blob_tw
    )
    _rb_right = _retest_avg_min_from_pack(pack) or _retest_avg_min_from_text(blob_tw)
    _band_right = bool(
        _rb_right is not None
        and abs(float(_rb_right["avg"]) - float(_rb_right["min"])) >= 0.6
    )
    for row in ((pack or {}).get("pred_levels") or {}).get("tw") or []:
        try:
            lv = float(row.get("level"))
        except (TypeError, ValueError):
            continue
        if round(lv, 1) in skip:
            continue
        tag = str(row.get("tag") or "")
        role = str(row.get("role") or "")
        # 當令回測帶已上：過期 41500／路徑 43000 裸標不准進右欄
        if _band_right and (
            abs(lv - 41500.0) < 0.6
            or (role in {"點位", "至少回測"} and abs(lv - 43000.0) < 0.6)
        ):
            continue
        # 41760 台指壓標刪：已破、右欄不再掛（使用者 2026-11-10）
        if role == "台指壓力" or abs(lv - 41760.0) < 0.6:
            continue
        # 雙軌當令：右欄留 最佳買點37837＋AI結束上緣35579＋深殺31705；
        # 39,000／37,164 改走黃底帶，不准再佔右欄
        if bb_dual_active and role in {
            "改口低上沿",
            "改口低下沿",
            "劇本一上沿",
            "下週底下沿",
            "下週底上沿",
            "4/23低",
        }:
            continue
        if bb_dual_active and any(
            abs(lv - x) < 1.0 for x in (39000.0, 37164.0, 37100.0, 38000.0)
        ):
            continue
        if bb_dual_active and role in {"點位", ""} and any(
            abs(lv - x) < 80.0
            for x in (37837.0, 37164.0, 35579.0, 31705.0, 37500.0, 37000.0, 37100.0)
        ):
            continue
        # 有 C9 低點區：舊劇本一下沿 35000 不准再畫（上沿 38000 改口「已破」仍留）
        if drop_script1 and (
            role == "劇本一下沿" or abs(lv - 35000.0) < 1.0
        ):
            continue
        if tag in {"未到", "未破", "已破"}:
            br = (
                _tw_pred_break_tag(
                    lv, lows, pack=pack, role=role, highs=hi_vals
                )
                if tag == "未到"
                else tag
            )
            if role == "回測平均":
                text = f"回測平均／{_px(lv)}・{br}"
            elif role == "回測最低":
                text = f"回測最低／{_px(lv)}・{br}"
            elif role == "至少回測" or abs(lv - 41500.0) < 0.6:
                text = f"回測最低／{_px(lv)}・{br}"
            elif role == "台指壓力":
                # 壓力位保留原文角色，不准改寫成「飆預測・已破」（低點誤破）
                text = f"台指壓力／{_px(lv)}・{br}"
                if _pack_pressure_break_on(pack):
                    text = f"{text}｜≠口述下降壓"
                if _text_has_retest_41500(
                    " ".join(
                        str(x or "")
                        for x in (
                            (pack or {}).get("thesis"),
                            (pack or {}).get("snippet"),
                            (pack or {}).get("wait_struct"),
                        )
                    )
                ):
                    text = f"{text}｜≠41500回測"
            else:
                text = _biaoke_pred_label(lv, br)
        else:
            text = str(row.get("label") or _biaoke_pred_label(lv))
        # 周一破台指／反彈穿刺／轉震盪：狀態跟官方柱
        if abs(lv - 44042.0) < 0.6:
            text = _biaoke_pred_label(lv, _level_break_tag(lv, lows) + "周一")
        elif role in {"反彈穿刺", "轉震盪"}:
            # 上方觀察壓：看「現在」有無站回／向上穿刺，不准拿下跌低點標成「已破」
            now_px = None
            if bars:
                try:
                    now_px = float(bars[-1].get("close"))
                except (TypeError, ValueError, AttributeError, IndexError):
                    now_px = None
            if now_px is None and lows:
                try:
                    now_px = float(lows[-1])
                except (TypeError, ValueError, IndexError):
                    now_px = None
            st = "已穿" if (now_px is not None and now_px >= lv - 0.5) else "未穿"
            suffix = "穿刺" if role == "反彈穿刺" else "轉震盪"
            text = _biaoke_pred_label(lv, st + suffix)
        elif role in {
            "劇本一上沿",
            "劇本一下沿",
            "C9低上沿",
            "C9低下沿",
            "改口低上沿",
            "改口低下沿",
        }:
            # 劇本一 38000：有修訂低點區＝已破；C9／改口兩沿跟官方柱
            text = _biaoke_pred_label(
                lv, _tw_pred_break_tag(lv, lows, pack=pack, role=role)
            )
        elif role in {
            "五波末／週五低",
            "九波備線破位",
            "九波備線深殺",
        }:
            # 右欄必見：最佳買點37837／上緣35579／深殺31705；虛線對齊真價
            text = str(row.get("label") or _biaoke_pred_label(lv, role))
        # 近／超近窗沒有 ref 日柱時從窗左拉滿，不准縮成末日短樁
        x_note = 0
        ref = _ymd(row.get("ref_ymd"))
        if bars and ref:
            ii = _bar_index_by_ymd(bars, ref)
            if ii is not None:
                x_note = int(ii)
        # 雙軌分色：最佳買點金；AI結束上緣／深殺冷紫
        if role == "五波末／週五低" or abs(lv - 37837.0) < 1.0:
            col = "#ffd54f"
        elif role in {"九波備線破位", "九波備線深殺"} or any(
            abs(lv - x) < 1.0 for x in (35579.0, 31705.0)
        ):
            col = "#b39ddb"
        elif role in {"改口低上沿", "改口低下沿"}:
            col = "#80deea"
        elif role in {"C9低上沿", "C9低下沿"}:
            col = "#ce93d8"
        else:
            col = "#82b1ff" if lv < 45000 else "#4dd0e1"
        # 價・日期完整；買點／上緣／深殺／台指壓長標略放寬（≠下降壓線 不准裁掉）
        lim = (
            42
            if (
                "／" in text
                or "・" in text
                or "≠口述下降壓" in text
                or "≠下降壓線" in text
                or role.startswith("九波")
                or "五波" in role
                or role == "台指壓力"
            )
            else 28
        )
        # 水平台指壓：白／淺黃，跟紫大C斜線路徑分色
        if role == "台指壓力" or abs(lv - 41760.0) < 0.6:
            col = "#ffe082"
        elif role in {"回測平均", "回測最低", "至少回測"} or abs(
            lv - 41500.0
        ) < 0.6:
            col = "#80cbc4" if role != "回測平均" else "#26a69a"
        out.append(
            {
                "x": x_note,
                "y": lv,
                "text": text[:lim],
                "color": col,
            }
        )
        skip.add(round(lv, 1))
    # 回測平均＋最低併一標：價近時兩框必互壓（42300↔41900）
    avg_i = next(
        (i for i, n0 in enumerate(out) if "回測平均" in str(n0.get("text") or "")),
        None,
    )
    min_i = next(
        (i for i, n0 in enumerate(out) if "回測最低" in str(n0.get("text") or "")),
        None,
    )
    if avg_i is not None and min_i is not None and avg_i != min_i:
        a_n, m_n = out[avg_i], out[min_i]
        try:
            ya, ym = float(a_n["y"]), float(m_n["y"])
        except (TypeError, ValueError, KeyError):
            ya = ym = 0.0
        if ya > 0 and ym > 0 and abs(ya - ym) < 1200.0:
            br = "未到"
            blob_ab = f"{a_n.get('text') or ''}{m_n.get('text') or ''}"
            if "已破" in blob_ab:
                br = "已破"
            merged = {
                "x": min(int(a_n.get("x") or 0), int(m_n.get("x") or 0)),
                "y": ya,
                "text": f"回測{_px(ya)}／{_px(ym)}・{br}",
                "color": a_n.get("color") or "#26a69a",
            }
            for i in sorted((avg_i, min_i), reverse=True):
                out.pop(i)
            out.append(merged)
    return out


def _render_twii_far_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具①遠窗四欄：上費半 → 台指電子盤 → 加權日K推進⑤／大ABC → 下加權日量。

    費半與台指電子盤同時段並看（即時查閱）；底圖加高讓三條價軸都清楚。
    推進⑤＝4/1→6/23；大A底7/29；大B末10/6；大C起10/15。費半同軸數。
    """
    pack = _ensure_teach_pack_preds(db_path, pack)
    try:
        import math

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_body_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    try:
        # 加權＋費半一起補：週末也要比到最近開市收，不准加權落後讓費半延長格誤標
        _ensure_teach_index_bars(db_path)
    except Exception:
        logger.exception("遠窗加權／費半補資料略過")
        try:
            _ensure_us_index_daily(db_path)
        except Exception:
            logger.exception("遠窗費半補資料略過")
    bars_full = _twii_bars_for_teach(db_path, 400, pack)
    if len(bars_full) < 20 or not save_path:
        return ""
    # 錨在完整柱算；顯示窗定長滾動。尖點跟 K 移；滾出左緣 clamp。
    mac_full = _twii_macro_wave_anchors(bars_full)
    if not mac_full:
        return ""
    keep_ymds: List[str] = ["20260331", "20260401"]
    # 教導：第一組／第二組跨度日要留在遠窗，才畫得出組別標
    if _pack_pressure_break_on(pack) or "C3-5" in str(
        (pack or {}).get("thesis") or ""
    ):
        keep_ymds.extend(["20261008", "20261019", "20261106"])
    for row in ((pack or {}).get("pred_levels") or {}).get("sox") or []:
        rd = _ymd(row.get("ref_ymd"))
        if rd:
            keep_ymds.append(rd)
    bars, far_vol_sr = _far_teach_bars_keeping_vol_sr(
        list(bars_full),
        max_bars=_FAR_TEACH_MAX_BARS,
        vol_lookback=_FAR_TEACH_VOL_LOOKBACK,
        keep_ymds=tuple(dict.fromkeys(keep_ymds)),
    )
    mac = _clamp_macro_wave_to_window(mac_full, bars)
    anc = _twii_abc_anchors(bars)  # 近窗細分（右標／預估仍可參考）
    if not mac:
        return ""
    sox_since = min(keep_ymds + ["20260220"]) if keep_ymds else "20260220"
    # 出圖當下重抓費半即時：黃框指數＋末根縮圖K同口更新
    live_sox = _ensure_paint_live_sox(pack)
    sox = _load_us_daily(db_path, "SOX", sox_since)
    # 盤後／漏抓：強制把 Yahoo 末日併進列（修 11/3＝10647 卡死、漏 11/5＝9011）
    try:
        sox = _inject_yahoo_us_last_into_rows(
            sox, yid="^SOX", sym="SOX", db_path=db_path
        )
    except Exception:
        logger.exception("遠窗費半 Yahoo 末日注入略過")
    if live_sox or (pack or {}).get("live_sox"):
        sox = _merge_live_sox_display_bar(
            sox, live_sox or (pack or {}).get("live_sox")
        )
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
    sox_o = list(sox_a["open"])
    sox_h = list(sox_a["high"])
    sox_l = list(sox_a["low"])
    sox_c = list(sox_a["close"])
    n_tw = int(n)
    n_axis = len(sox_c)
    i_live = _apply_live_sox_to_axis(
        sox_o=sox_o,
        sox_h=sox_h,
        sox_l=sox_l,
        sox_c=sox_c,
        tw_bars=bars,
        live=live_sox or (pack or {}).get("live_sox"),
        n_tw=n_tw,
    )
    # 台指電子盤（夜盤日K）對齊加權日軸；缺日先補官方夜盤再對齊（防前收填成重複K）
    # 夜盤列改掛起日：週五夜週一標才能對上週五末K，不准週末還停在崩盤夜
    tx_since = _ymd(bars[0].get("date")) if bars else "20260301"
    try:
        _ensure_latest_tx_night_row(db_path)
        _ensure_tx_night_for_teach(db_path, bars)
    except Exception:
        logger.exception("遠窗電子盤缺日補齊略過")
    tx_rows = _tx_night_rows_on_evening_axis(
        _load_tx_futures_daily(db_path, session="night", since=tx_since or "20260301")
    )
    _tx_real_days = {
        _ymd(r.get("date"))
        for r in (tx_rows or [])
        if float((r or {}).get("close") or 0) > 0 and _ymd((r or {}).get("date"))
    }
    live_tx = _ensure_paint_live_tx(pack)
    if isinstance(live_tx, dict) and float(live_tx.get("close") or 0) > 0:
        _ld = _ymd(live_tx.get("date"))
        if _ld:
            _tx_real_days.add(_ld)
    # 電子盤缺日不准前收灌假K（例：11/09 被灌成 11/06 夜的 39129 下影）
    tx_a = _align_us_to_twii_dates(tx_rows, bars, fill_missing=False)
    tx_o = list(tx_a["open"])
    tx_h = list(tx_a["high"])
    tx_l = list(tx_a["low"])
    tx_c = list(tx_a["close"])
    tx_v = list(tx_a.get("volume") or [])
    # 費半可延長軸；台指電子盤只畫加權日軸長度（夜盤跟台股曆）
    while len(tx_c) < n_tw:
        tx_o.append(float("nan"))
        tx_h.append(float("nan"))
        tx_l.append(float("nan"))
        tx_c.append(float("nan"))
        tx_v.append(0.0)
    while len(tx_v) < n_tw:
        tx_v.append(0.0)
    tx_o, tx_h, tx_l, tx_c = tx_o[:n_tw], tx_h[:n_tw], tx_l[:n_tw], tx_c[:n_tw]
    tx_v = [float(x or 0) for x in tx_v[:n_tw]]
    i_tx_live = _apply_live_tx_to_axis(
        tx_o=tx_o,
        tx_h=tx_h,
        tx_l=tx_l,
        tx_c=tx_c,
        tw_bars=bars,
        live=live_tx or (pack or {}).get("live_tx"),
    )
    sox_anc = _sox_abc_anchors_on_axis(sox_h, sox_l, sox_c, i5_hint=i5)
    sox_i_now = int(sox_anc["i_now"]) if sox_anc else (n_axis - 1)
    if i_live is not None:
        sox_i_now = int(i_live)
    else:
        # 不准把加權軸「前收填日」末格當費半今日K；tip／黃框釘真實美股末日
        _real_sox_asof = ""
        for _r in reversed(list(sox or [])):
            if float((_r or {}).get("close") or 0) > 0 and _ymd((_r or {}).get("date")):
                _real_sox_asof = _ymd(_r.get("date"))
                break
        _snap = _sox_axis_index_for_ymd(
            bars,
            n_tw=n_tw,
            sox_extra_dates=sox_extra_dates,
            ymd=_real_sox_asof,
            n_axis=n_axis,
        )
        if _snap is not None:
            sox_i_now = int(_snap)
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_bhi:])
    # 大量撐壓＝volume_first；無則退窗內最大量。量只認加權 n_tw。
    i_vmax = far_vol_sr.get("i_primary") if isinstance(far_vol_sr, dict) else None
    if i_vmax is None and n_tw and any(float(v or 0) > 0 for v in vols[:n_tw]):
        i_vmax = max(range(n_tw), key=lambda i: float(vols[i] or 0))

    # 上費半 / 台指電子盤 / 加權日K / 下加權量；加權欄略高；欄間留空給日期
    # Telegram sendPhoto 硬限寬+高≤10000；存檔後仍會 _shrink_png_for_telegram
    fig, (axu, axt, ax, axv) = plt.subplots(
        4,
        1,
        figsize=(15.6, 15.6),
        dpi=NAV_CHART_DPI,
        sharex=True,
        # 欄間加高：三白底戳上移仍落在各格內，不准擋縮圖K／九波
        gridspec_kw=dict(height_ratios=(2.15, 2.30, 3.30, 0.95), hspace=0.18),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    # top：標題列；戳改各欄右上，頁眉不再塞三戳
    # right 收到 0.98：右標水平往左貼K
    # left 加寬：逐字正讀左軸標題要空間（不准橫躺）
    fig.subplots_adjust(left=0.088, right=0.978, top=0.935, bottom=0.095)
    for a in (axu, axt, ax, axv):
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
    # 真實美股日才畫縮圖K；加權軸前收填日不准畫假K（否則 tip／黃框日對不上）
    _sox_real_days = {
        _ymd(r.get("date"))
        for r in (sox or [])
        if float((r or {}).get("close") or 0) > 0 and _ymd((r or {}).get("date"))
    }
    if isinstance(live_sox, dict) and float(live_sox.get("close") or 0) > 0:
        _ld = _ymd(live_sox.get("date"))
        if _ld:
            _sox_real_days.add(_ld)

    def _sox_axis_ymd_at(i: int) -> str:
        if 0 <= i < int(n_tw):
            return _ymd(bars[i].get("date"))
        j = int(i) - int(n_tw)
        if sox_extra_dates and 0 <= j < len(sox_extra_dates):
            return _ymd(sox_extra_dates[j])
        return ""

    sox_min_body = _candle_span_min_body(sox_h, sox_l, frac=_FAR_SOX_MIN_BODY_FRAC)
    _sox_last_repaint: Optional[Dict[str, Any]] = None
    _sox_chg_tip: Optional[Dict[str, Any]] = None
    _sox_right_deferred: List[Dict[str, Any]] = []
    _sox_struct_right: List[Dict[str, Any]] = []
    _sox_ylabel_span: Optional[Tuple[float, float]] = None
    if len(valid) >= 5:
        span_raw = max(x for x in sox_h if x == x) - min(x for x in sox_l if x == x)
        for i in valid:
            if _sox_axis_ymd_at(i) not in _sox_real_days:
                continue
            prev_i = next(
                (
                    j
                    for j in range(i - 1, -1, -1)
                    if sox_c[j] == sox_c[j] and _sox_axis_ymd_at(j) in _sox_real_days
                ),
                None,
            )
            prev_c = sox_c[prev_i] if prev_i is not None else None
            up = candle_body_up_taiwan(sox_c[i], prev_c, sox_o[i])
            color = _LIVE_UP if up else _LIVE_DOWN
            # 遠窗費半：加粗影線＋價窗比例最小實體（舊 0.15%→看不見）
            axu.vlines(i, sox_l[i], sox_h[i], color=color, linewidth=1.55, zorder=5)
            y0, y1 = sorted((sox_o[i], sox_c[i]))
            _bh = max(y1 - y0, float(sox_min_body))
            axu.add_patch(
                plt.Rectangle(
                    (i - 0.36, y0),
                    0.72,
                    _bh,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.45,
                    zorder=6,
                )
            )
        # 費半跟加權同一日曆錨：⑤起4/1→⑤終6/23→A底7/29→B末10/6→C
        # 窗左緣若台開美休＝NaN：就近有限柱取端點，不准整段浪線消失（加權四欄幾何不改）
        s5s, s5e, sa, sb = i5s, i5e, i_alow, i_b_end
        _sox_p5s = _axis_pivot_price(sox_h, sox_l, sox_c, s5s, tip="low", n=n_axis)
        _sox_p5e = _axis_pivot_price(sox_h, sox_l, sox_c, s5e, tip="high", n=n_axis)
        _sox_pa = _axis_pivot_price(sox_h, sox_l, sox_c, sa, tip="low", n=n_axis)
        _sox_pb = _axis_pivot_price(sox_h, sox_l, sox_c, sb, tip="high", n=n_axis)
        _sox_pn = _axis_pivot_price(
            sox_h, sox_l, sox_c, sox_i_now, tip="close", n=n_axis
        )
        if all(p is not None for p in (_sox_p5s, _sox_p5e, _sox_pa, _sox_pb, _sox_pn)):
            s5s, sy5s = _sox_p5s  # type: ignore[misc]
            s5e, sy5e = _sox_p5e  # type: ignore[misc]
            sa, sya = _sox_pa  # type: ignore[misc]
            sb, syb = _sox_pb  # type: ignore[misc]
            sox_i_now, sn = _sox_pn  # type: ignore[misc]
            axu.plot([s5s, s5e], [sy5s, sy5e], color="#40c4ff", lw=2.2, zorder=7)
            axu.plot([s5e, sa], [sy5e, sya], color="#ff8a80", lw=2.0, zorder=7)
            axu.plot(
                [sa, sb],
                [sya, syb],
                color="#ffd54f",
                lw=2.2,
                ls=(0, (7, 2.2)),
                zorder=7,
            )
            # 費C：自費B末連到今（中經 C 起日若有柱），不准大B末後斷線
            sox_c_xs = [sb]
            sox_c_ys = [syb]
            _sox_pc = _axis_pivot_price(sox_h, sox_l, sox_c, i_c, tip="close", n=n_axis)
            if _sox_pc is not None and int(_sox_pc[0]) != int(sb):
                sox_c_xs.append(int(_sox_pc[0]))
                sox_c_ys.append(float(_sox_pc[1]))
            sox_c_xs.append(sox_i_now)
            sox_c_ys.append(sn)
            axu.plot(sox_c_xs, sox_c_ys, color="#ea80fc", lw=1.85, zorder=7)
            span_s = span_raw
            sox_pred_ys = [
                float(r.get("level"))
                for r in ((pack or {}).get("pred_levels") or {}).get("sox") or []
                if r.get("level") is not None
            ]
            y_lo_s = min([x for x in sox_l if x == x] + sox_pred_ys)
            y_hi_s = max([x for x in sox_h if x == x] + sox_pred_ys)
            # 頂上多留給白底戳；戳上移後仍不准蓋最上緣 K
            axu.set_ylim(y_lo_s - span_s * 0.22, y_hi_s + span_s * 0.32)
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
                _spear_ring(
                    axu, ii, yy, color=col, zorder=8, hot=(col == "#ea80fc")
                )
            # 結構重點右標（對齊加權「大B末 價」；尖點浪名仍釘在柱上）
            _sox_struct_right = [
                {
                    "x": int(s5e),
                    "y": float(sy5e),
                    "text": f"費⑤終 {_px(sy5e)}",
                    "color": "#40c4ff",
                },
                {
                    "x": int(sa),
                    "y": float(sya),
                    "text": f"費A低 {_px(sya)}",
                    "color": "#ff8a80",
                },
                {
                    "x": int(sb),
                    "y": float(syb),
                    "text": f"費B末 {_px(syb)}",
                    "color": "#ffd54f",
                },
                {
                    "x": int(sox_i_now),
                    "y": float(sn),
                    "text": f"費C今 {_px(float(sn))}",
                    "color": "#ea80fc",
                },
            ]
            # 右標延到加權 tip 後，與加權同一 x_col（對齊「7/29低…」那欄）
            _sox_y0 = y_lo_s - span_s * 0.22
            _sox_y1 = y_hi_s + span_s * 0.32
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
                ymin=_sox_y0,
                ymax=_sox_y1,
                now_y=float(sn),
                now_lab=f"費C今{_px(float(sn))}",
                place=False,
            )
            _sox_ylabel_span = (_sox_y0, _sox_y1)
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
        # 白底戳不准跟浪線綁死：浪端點失敗仍要有末根 tip／黃框（對的東西不准整段刪）
        if _sox_last_repaint is None and valid:
            _tip_pn = _axis_pivot_price(
                sox_h, sox_l, sox_c, sox_i_now, tip="close", n=n_axis
            )
            if _tip_pn is not None:
                _ti, _tc = int(_tip_pn[0]), float(_tip_pn[1])
                if _tc == _tc and math.isfinite(_tc) and _tc > 0:
                    _sox_last_repaint = {
                        "i": _ti,
                        "o": float(sox_o[_ti])
                        if _ti < len(sox_o) and sox_o[_ti] == sox_o[_ti]
                        else _tc,
                        "h": float(sox_h[_ti])
                        if _ti < len(sox_h) and sox_h[_ti] == sox_h[_ti]
                        else _tc,
                        "l": float(sox_l[_ti])
                        if _ti < len(sox_l) and sox_l[_ti] == sox_l[_ti]
                        else _tc,
                        "c": _tc,
                        "prev": next(
                            (
                                j
                                for j in range(_ti - 1, -1, -1)
                                if j < len(sox_c) and sox_c[j] == sox_c[j]
                            ),
                            None,
                        ),
                        "min_body": max(
                            float(sox_min_body), float(span_raw) * 0.035
                        ),
                    }
                    # 無浪線時仍抬 ylim 給白底戳天空
                    try:
                        _ys = [float(x) for x in sox_h if x == x] + [
                            float(x) for x in sox_l if x == x
                        ]
                        if _ys:
                            _ylo, _yhi = min(_ys), max(_ys)
                            _sp = max(_yhi - _ylo, 1.0)
                            axu.set_ylim(_ylo - _sp * 0.22, _yhi + _sp * 0.32)
                    except Exception:
                        pass
    _set_upright_ylabel(axu, "費半 SOX", fp=_fp, color=_LIVE_MUTED, fontsize=10)
    # 費半大量撐壓：指數無量 → SOXX ETF 量代理對齊同日（標清楚）
    # 軸窗≤152；下一層另載深窗歷史再併臉（急殺連破才找得到次大量）
    _sox_deep_since = "20250101"
    sox_vol_map = _soxx_volume_by_date(db_path, since=_sox_deep_since)
    sox_rows_for_vol: List[Dict[str, Any]] = []
    for i in range(n_axis):
        d = (
            _ymd(bars[i].get("date"))
            if i < n_tw
            else (
                _ymd(sox_extra_dates[i - n_tw])
                if sox_extra_dates and (i - n_tw) < len(sox_extra_dates)
                else ""
            )
        )
        if not d:
            continue
        if not (
            i < len(sox_c)
            and sox_c[i] == sox_c[i]
            and math.isfinite(float(sox_h[i]))
            and math.isfinite(float(sox_l[i]))
        ):
            continue
        sox_rows_for_vol.append(
            {
                "date": d,
                "open": float(sox_o[i]) if sox_o[i] == sox_o[i] else float(sox_c[i]),
                "high": float(sox_h[i]),
                "low": float(sox_l[i]),
                "close": float(sox_c[i]),
                "volume": float(sox_vol_map.get(d) or 0),
            }
        )
    sox_deep_rows: List[Dict[str, Any]] = []
    try:
        for r in _load_us_daily(db_path, "SOX", _sox_deep_since):
            d = _ymd(r.get("date"))
            if not d:
                continue
            sox_deep_rows.append(
                {
                    "date": d,
                    "open": float(r.get("open") or r.get("close") or 0),
                    "high": float(r.get("high") or 0),
                    "low": float(r.get("low") or 0),
                    "close": float(r.get("close") or 0),
                    "volume": float(sox_vol_map.get(d) or r.get("volume") or 0),
                }
            )
    except Exception:
        logger.exception("遠窗費半深窗量價略過")
        sox_deep_rows = list(sox_rows_for_vol)
    sox_for_sr = _teach_vol_rows_merge_deep(sox_rows_for_vol, sox_deep_rows)
    sox_vol_sr = _resolve_teach_vol_sr(
        sox_for_sr,
        lookback=min(_FAR_TEACH_VOL_LOOKBACK, max(40, len(sox_for_sr) - 1)),
    )
    if (sox_vol_sr.get("primary") or {}).get("high"):
        pri = sox_vol_sr["primary"]
        _paint_max_vol_hl_zone(
            axu,
            high=float(pri["high"]),
            low=float(pri["low"]),
            date_lab=str(pri.get("date") or ""),
            ts_lab=str(pri.get("ts") or ""),
            fp=_fp,
            avoid_top_left_stamp=True,
        )
        if (sox_vol_sr.get("next") or {}).get("high"):
            nxt = sox_vol_sr["next"]
            _paint_next_layer_vol_zone(
                axu,
                high=float(nxt["high"]),
                low=float(nxt["low"]),
                date_lab=str(nxt.get("date") or ""),
                ts_lab=str(nxt.get("ts") or ""),
                fp=_fp,
                direction=str(nxt.get("direction") or "below"),
                avoid_top_left_stamp=True,
            )
    # 費半自己的爆大量日（常≠加權 10/15）：金K／亮桃K＋本欄豎線
    _sox_axis_ymds = [_ymd(bars[i].get("date")) for i in range(n_tw)]
    if sox_extra_dates:
        _sox_axis_ymds.extend(_ymd(d) for d in sox_extra_dates)
    while len(_sox_axis_ymds) < n_axis:
        _sox_axis_ymds.append("")
    _sox_axis_ymds = _sox_axis_ymds[:n_axis]
    _sox_i_pri, _sox_i_nxt = _vol_sr_index_on_axis(sox_vol_sr, axis_ymds=_sox_axis_ymds)
    _paint_vol_sr_mark_on_axis(
        axu,
        opens=sox_o,
        highs=sox_h,
        lows=sox_l,
        closes=sox_c,
        i_primary=_sox_i_pri,
        i_next=_sox_i_nxt,
        date_primary=str((sox_vol_sr.get("primary") or {}).get("date") or ""),
        date_next=str((sox_vol_sr.get("next") or {}).get("date") or ""),
        fp=_fp,
    )
    # 費半右欄補齊：題旨點＋結構⑤/A/B/C今＋大量撐壓（對齊電盤／加權右欄有重點）
    _sox_vol_right: List[Dict[str, Any]] = []
    if (sox_vol_sr.get("primary") or {}).get("high"):
        _sp = sox_vol_sr["primary"]
        _sp_tag = _teach_vol_day_tag(_sp.get("date"), _sp.get("ts"))
        _sox_vol_right.append(
            {
                "x": max(int(n_axis) - 1, 0),
                "y": float(_sp["high"]),
                "text": f"{_sp_tag}費大量壓 {_px(_sp['high'])}",
                "color": "#ffe082",
            }
        )
        _sox_vol_right.append(
            {
                "x": max(int(n_axis) - 1, 0),
                "y": float(_sp["low"]),
                "text": (
                    f"{_sp_tag}費大量撐 {_px(_sp['low'])}已破"
                    if bool(_sp.get("broke_support"))
                    else f"{_sp_tag}費大量撐 {_px(_sp['low'])}"
                ),
                "color": "#ffe082",
            }
        )
    _sox_right_merged: List[Dict[str, Any]] = []
    _sox_seen_y: List[float] = []

    def _sox_keep_note(note: Dict[str, Any]) -> None:
        try:
            yy = float(note.get("y"))
        except (TypeError, ValueError):
            return
        if any(abs(yy - z) < 12.0 for z in _sox_seen_y):
            return
        _sox_seen_y.append(yy)
        _sox_right_merged.append(note)

    # 優先序：題旨預測 → 結構浪點／今 → 大量撐壓（同價不重複）
    for _n0 in list(_sox_right_deferred or []) + list(_sox_struct_right or []) + list(
        _sox_vol_right
    ):
        _sox_keep_note(_n0)
    _sox_right_deferred = _sox_right_merged
    axu.text(
        0.012,
        0.04,
        "費半＝自轉折浪＋大量撐壓（量＝SOXX 代理）＋下一層｜黃豎＝費半爆大量日",
        transform=axu.transAxes,
        fontproperties=_fp(8, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
        zorder=10,
        bbox=dict(boxstyle="round,pad=0.16", fc="#0b0f14", ec="#546e7a", lw=0.65, alpha=0.92),
    )

    # —— 次上：台指電子盤（夜盤日K＋大量撐壓／下一層／即時末K）——
    # 鎖死：電子盤撐壓只認大量規則（volume_first＋破後次大量）；
    # 題旨沒有他講死的電子盤下一撐，不准套加權／費半 pred_levels。
    _tx_last_repaint: Optional[Dict[str, Any]] = None
    _tx_right_notes: List[Dict[str, Any]] = []
    _tx_ylabel_span: Optional[Tuple[float, float]] = None
    # 只認官方夜盤真日（＋即時日）；加權軸前收填日不准畫假重複K
    tx_valid = [
        i
        for i, c in enumerate(tx_c)
        if c == c
        and c
        and math.isfinite(float(tx_h[i]))
        and math.isfinite(float(tx_l[i]))
        and (
            i >= n_tw
            or _ymd(bars[i].get("date") if i < len(bars) else "") in _tx_real_days
        )
    ]
    # 夜盤九波末日預設＝最後一根真夜盤；下方 tip／即時塊會覆寫
    tip_i = int(tx_valid[-1]) if tx_valid else -1
    tx_min_body = _candle_span_min_body(tx_h, tx_l, frac=_FAR_SOX_MIN_BODY_FRAC)
    tx_rows_for_vol: List[Dict[str, Any]] = []
    for i in range(n_tw):
        d = _ymd(bars[i].get("date")) if i < len(bars) else ""
        if not d or d not in _tx_real_days:
            continue
        if not (
            i < len(tx_c)
            and tx_c[i] == tx_c[i]
            and math.isfinite(float(tx_h[i]))
            and math.isfinite(float(tx_l[i]))
        ):
            continue
        tx_rows_for_vol.append(
            {
                "date": d,
                "open": float(tx_o[i]) if tx_o[i] == tx_o[i] else float(tx_c[i]),
                "high": float(tx_h[i]),
                "low": float(tx_l[i]),
                "close": float(tx_c[i]),
                "volume": float(tx_v[i] if i < len(tx_v) else 0),
            }
        )
    # 末根用即時／收盤同口價重算破撐（不准庫內舊收讓下一層消失或錯掛）
    _tx_live_sr = live_tx if isinstance(live_tx, dict) else None
    if not _tx_live_sr and isinstance(pack, dict):
        _tx_live_sr = pack.get("live_tx") if isinstance(pack.get("live_tx"), dict) else None
    if tx_rows_for_vol and isinstance(_tx_live_sr, dict):
        try:
            _lpx = float(_tx_live_sr.get("close") or 0)
        except (TypeError, ValueError):
            _lpx = 0.0
        if _lpx > 0:
            last = dict(tx_rows_for_vol[-1])
            try:
                _lo = float(_tx_live_sr.get("low") or last.get("low") or _lpx)
                _hi = float(_tx_live_sr.get("high") or last.get("high") or _lpx)
                _oo = float(_tx_live_sr.get("open") or last.get("open") or _lpx)
            except (TypeError, ValueError):
                _lo = _hi = _oo = _lpx
            last["close"] = _lpx
            last["low"] = min(x for x in (_lo, float(last.get("low") or _lpx), _lpx) if x > 0)
            last["high"] = max(_hi, float(last.get("high") or 0), _lpx)
            if _oo > 0:
                last["open"] = _oo
            tx_rows_for_vol[-1] = last
    # 軸窗短；電子盤下一層另載深窗夜盤日K再併臉（同樣掛起日）
    _tx_deep_since = "20250101"
    try:
        tx_deep_rows = _tx_night_rows_on_evening_axis(
            _load_tx_futures_daily(
                db_path, session="night", since=_tx_deep_since
            )
        )
    except Exception:
        logger.exception("遠窗電子盤深窗量價略過")
        tx_deep_rows = list(tx_rows_for_vol)
    tx_for_sr = _teach_vol_rows_merge_deep(tx_rows_for_vol, tx_deep_rows)
    tx_vol_sr = _resolve_teach_vol_sr(
        tx_for_sr,
        lookback=min(_FAR_TEACH_VOL_LOOKBACK, max(40, len(tx_for_sr) - 1)),
    )
    # 撐壓底色先畫在K下層；雙軌當令：primary 右標＋水平虛線拿掉，只留淺黃底
    if (tx_vol_sr.get("primary") or {}).get("high"):
        pri = tx_vol_sr["primary"]
        _paint_max_vol_hl_zone(
            axt,
            high=float(pri["high"]),
            low=float(pri["low"]),
            date_lab=str(pri.get("date") or ""),
            ts_lab=str(pri.get("ts") or ""),
            fp=_fp,
            labels=False,
        )
        if (tx_vol_sr.get("next") or {}).get("high"):
            nxt = tx_vol_sr["next"]
            _paint_next_layer_vol_zone(
                axt,
                high=float(nxt["high"]),
                low=float(nxt["low"]),
                date_lab=str(nxt.get("date") or ""),
                ts_lab=str(nxt.get("ts") or ""),
                fp=_fp,
                direction=str(nxt.get("direction") or "below"),
                # 左標改走右欄，避免與青帶／即時擠在底段卡住
                labels=False,
            )
            _tx_nxt_md = _md(nxt.get("date"))
            _tx_nxt_tag = f"{_tx_nxt_md} " if _tx_nxt_md else ""
            # 先標撐再標壓：33799＝區高＝壓，不准被誤認成接下來的撐
            _tx_right_notes.append(
                {
                    "x": n_tw - 1,
                    "y": float(nxt["low"]),
                    "text": f"{_tx_nxt_tag}電盤下一層撐 {_px(nxt['low'])}",
                    "color": "#ff8aa0",
                }
            )
            _tx_right_notes.append(
                {
                    "x": n_tw - 1,
                    "y": float(nxt["high"]),
                    "text": f"{_tx_nxt_tag}電盤下一層壓 {_px(nxt['high'])}",
                    "color": "#ff8aa0",
                }
            )
    # 現價＝即時／收盤同口（與黃紅戳一致）；不准再用庫內舊收去挑近撐
    tx_now = None
    if isinstance(_tx_live_sr, dict):
        try:
            tx_now = float(_tx_live_sr.get("close") or 0) or None
        except (TypeError, ValueError):
            tx_now = None
    if not tx_now and tx_valid:
        tx_now = float(tx_c[tx_valid[-1]])
    if tx_now and tx_now > 0:
        tx_sup = []
        tx_res = []
        for key in ("primary", "next"):
            row = tx_vol_sr.get(key) or {}
            if row.get("low"):
                tx_sup.append(float(row["low"]))
            if row.get("high"):
                tx_res.append(float(row["high"]))
        tx_sr = _next_support_resist(float(tx_now), supports=tx_sup, resists=tx_res)
        _tx_pri = tx_vol_sr.get("primary") or {}
        try:
            _tx_ex_lo = (
                float(_tx_pri["low"]) if _tx_pri.get("low") is not None else None
            )
            _tx_ex_hi = (
                float(_tx_pri["high"]) if _tx_pri.get("high") is not None else None
            )
        except (TypeError, ValueError):
            _tx_ex_lo = _tx_ex_hi = None
        _tx_skip_lab: List[float] = []
        for row in (tx_vol_sr.get("primary"), tx_vol_sr.get("next")):
            if not row:
                continue
            for k in ("high", "low"):
                try:
                    if row.get(k) is not None:
                        _tx_skip_lab.append(float(row[k]))
                except (TypeError, ValueError):
                    pass
        for v in (tx_sr.get("support"), tx_sr.get("resist")):
            if v is not None:
                try:
                    _tx_skip_lab.append(float(v))
                except (TypeError, ValueError):
                    pass
        _paint_next_sr_zone(
            axt,
            support=tx_sr.get("support"),
            resist=tx_sr.get("resist"),
            fp=_fp,
            exclude_lo=_tx_ex_lo,
            exclude_hi=_tx_ex_hi,
            # 青帶左標也關掉：底段擠爆；數字只留右欄疏開
            skip_label_ys=_tx_skip_lab,
            x_end=float(n_tw) + 0.12,
        )
        # 9波／改口低點區已上圖：電子盤結構近撐太遠＝雜訊（如 32834），不准再進右欄
        _tx_skip_far_sr = _c9_extension_active(pack)
        if tx_sr.get("support") is not None and not _tx_skip_far_sr:
            _tx_right_notes.append(
                {
                    "x": n_tw - 1,
                    "y": float(tx_sr["support"]),
                    "text": _biaoke_pred_label(float(tx_sr["support"])),
                    "color": "#4dd0e1",
                }
            )
        if tx_sr.get("resist") is not None and not _tx_skip_far_sr:
            _tx_right_notes.append(
                {
                    "x": n_tw - 1,
                    "y": float(tx_sr["resist"]),
                    "text": _biaoke_pred_label(float(tx_sr["resist"])),
                    "color": "#4dd0e1",
                }
            )
    # 最佳買點／37837 只掛加權日盤右欄，不准上電子盤
    _tx_valid_set = set(tx_valid)
    if len(tx_valid) >= 2:
        for i in tx_valid:
            # 前一根只認真實夜盤日，不准吃前收填日（否則缺口後漲跌色會錯）
            prev_i = next(
                (j for j in range(i - 1, -1, -1) if j in _tx_valid_set),
                None,
            )
            prev_c = tx_c[prev_i] if prev_i is not None else None
            up = candle_body_up_taiwan(tx_c[i], prev_c, tx_o[i])
            color = _LIVE_UP if up else _LIVE_DOWN
            axt.vlines(i, tx_l[i], tx_h[i], color=color, linewidth=1.55, zorder=5)
            y0, y1 = sorted((tx_o[i], tx_c[i]))
            _bh = max(y1 - y0, float(tx_min_body))
            axt.add_patch(
                plt.Rectangle(
                    (i - 0.36, y0),
                    0.72,
                    _bh,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.45,
                    zorder=6,
                )
            )
        # 末根：即時夜盤或庫內夜盤；白邊＋tip 圈（索引日＝紅框日期）
        tip_i = int(i_tx_live) if i_tx_live is not None else int(tx_valid[-1])
        _tx_live_now = live_tx or (
            (pack or {}).get("live_tx") if isinstance(pack, dict) else None
        )
        if (
            isinstance(_tx_live_now, dict)
            and float(_tx_live_now.get("close") or 0) > 0
            and _tx_night_session_live(_query_now_from_pack(pack))
        ):
            _eve = _ymd(_tx_live_now.get("date"))
            if _eve and tip_i < len(bars) and _ymd(bars[tip_i].get("date")) != _eve:
                for _i, _r in enumerate(bars):
                    if _ymd((_r or {}).get("date")) == _eve and _i < len(tx_c):
                        tip_i = int(_i)
                        break
        if 0 <= tip_i < len(tx_c) and tx_c[tip_i] == tx_c[tip_i]:
            prev_i = next(
                (j for j in range(tip_i - 1, -1, -1) if j in _tx_valid_set),
                None,
            )
            _tx_wall = _query_now_from_pack(pack)
            _tx_last_repaint = {
                "i": tip_i,
                "o": float(tx_o[tip_i]),
                "h": float(tx_h[tip_i]),
                "l": float(tx_l[tip_i]),
                "c": float(tx_c[tip_i]),
                "prev": float(tx_c[prev_i]) if prev_i is not None else None,
                "min_body": float(tx_min_body),
                "asof": _ymd(bars[tip_i].get("date")) if tip_i < len(bars) else "",
            }
            if (
                isinstance(_tx_live_now, dict)
                and float(_tx_live_now.get("close") or 0) > 0
                and _tx_night_session_live(_tx_wall)
            ):
                try:
                    _tx_last_repaint["c"] = float(_tx_live_now["close"])
                    _tx_last_repaint["o"] = float(
                        _tx_live_now.get("open") or _tx_last_repaint["o"]
                    )
                    _tx_last_repaint["h"] = max(
                        float(_tx_last_repaint["h"]),
                        float(_tx_live_now.get("high") or 0),
                        float(_tx_last_repaint["c"]),
                    )
                    _lo_live = float(_tx_live_now.get("low") or 0)
                    if _lo_live > 0:
                        _tx_last_repaint["l"] = min(
                            float(_tx_last_repaint["l"]), _lo_live, float(_tx_last_repaint["c"])
                        )
                    _tx_last_repaint["asof"] = (
                        _ymd(_tx_live_now.get("date"))
                        or _tx_last_repaint.get("asof")
                        or ""
                    )
                except (TypeError, ValueError):
                    pass
            # 現價虛線／右標延後到 tip 索引校完再畫（避免虛線停在舊格、末根K在右側）
            _tx_last_repaint["rail_pending"] = True
            _tx_last_repaint["rail_live"] = bool(
                isinstance(_tx_live_sr, dict)
                and float((_tx_live_sr or {}).get("close") or 0) > 0
                and _tx_night_session_live(_tx_wall)
            )
        lo_v = min(float(tx_l[i]) for i in tx_valid)
        hi_v = max(float(tx_h[i]) for i in tx_valid)
        # 撐壓帶也納入 ylim，標籤不被裁
        for row in (tx_vol_sr.get("primary"), tx_vol_sr.get("next")):
            if not row:
                continue
            try:
                lo_v = min(lo_v, float(row.get("low") or lo_v))
                hi_v = max(hi_v, float(row.get("high") or hi_v))
            except (TypeError, ValueError):
                pass
        pad = max(120.0, (hi_v - lo_v) * 0.08)
        pad_top = max(pad * 1.55, (hi_v - lo_v) * 0.14)
        axt.set_ylim(lo_v - pad, hi_v + pad_top)
        _tx_ylabel_span = (lo_v - pad, hi_v + pad_top)
    # 電子盤自己的爆大量日（常≠加權 10/15）：金K／亮桃K＋本欄豎線
    _tx_axis_ymds = [_ymd(bars[i].get("date")) for i in range(n_tw)]
    _tx_i_pri, _tx_i_nxt = _vol_sr_index_on_axis(tx_vol_sr, axis_ymds=_tx_axis_ymds)
    _paint_vol_sr_mark_on_axis(
        axt,
        opens=tx_o,
        highs=tx_h,
        lows=tx_l,
        closes=tx_c,
        i_primary=_tx_i_pri,
        i_next=_tx_i_nxt,
        date_primary=str((tx_vol_sr.get("primary") or {}).get("date") or ""),
        date_next=str((tx_vol_sr.get("next") or {}).get("date") or ""),
        fp=_fp,
    )
    _set_upright_ylabel(axt, "台指電子盤", fp=_fp, color=_LIVE_MUTED, fontsize=10)
    # 大結構⑤／A／B：跟費半／加權同一日曆錨畫在夜盤柱上（C 段細浪仍走下方白 C1…C8）
    if len(tx_valid) >= 8 and tip_i >= 0:
        _tx_valid_set2 = set(int(i) for i in tx_valid)

        def _tx_snap_anchor(i_prefer: int, *, prefer_high: bool) -> Optional[int]:
            """日曆錨對到最近真夜盤日；缺柱就近找，不准畫假夜盤。"""
            i0 = int(i_prefer)
            if i0 in _tx_valid_set2:
                return i0
            # 前後各找 6 根真夜盤
            cands = [
                i
                for i in tx_valid
                if abs(int(i) - i0) <= 6
            ]
            if not cands:
                cands = [i for i in tx_valid if int(i) <= i0][-1:] or [
                    i for i in tx_valid if int(i) >= i0
                ][:1]
            if not cands:
                return None
            if prefer_high:
                return int(max(cands, key=lambda i: float(tx_h[i])))
            return int(min(cands, key=lambda i: float(tx_l[i])))

        try:
            _t5s = _tx_snap_anchor(int(i5s), prefer_high=False)
            _t5e = _tx_snap_anchor(int(i5e), prefer_high=True)
            _ta = _tx_snap_anchor(int(i_alow), prefer_high=False)
            _tb = _tx_snap_anchor(int(i_b_end), prefer_high=True)
        except (TypeError, ValueError, NameError):
            _t5s = _t5e = _ta = _tb = None
        if (
            _t5s is not None
            and _t5e is not None
            and _ta is not None
            and _tb is not None
            and _t5s < _t5e <= _ta <= _tb
        ):
            _ty5s = float(tx_l[_t5s]) if tx_l[_t5s] == tx_l[_t5s] else float(tx_c[_t5s])
            _ty5e = float(tx_h[_t5e]) if tx_h[_t5e] == tx_h[_t5e] else float(tx_c[_t5e])
            _tya = float(tx_l[_ta]) if tx_l[_ta] == tx_l[_ta] else float(tx_c[_ta])
            _tyb = float(tx_h[_tb]) if tx_h[_tb] == tx_h[_tb] else float(tx_c[_tb])
            axt.plot(
                [_t5s, _t5e], [_ty5s, _ty5e], color="#40c4ff", lw=2.0, zorder=6.8
            )
            axt.plot(
                [_t5e, _ta], [_ty5e, _tya], color="#ff8a80", lw=1.85, zorder=6.8
            )
            axt.plot(
                [_ta, _tb],
                [_tya, _tyb],
                color="#ffd54f",
                lw=2.0,
                ls=(0, (7, 2.2)),
                zorder=6.8,
            )
            # C 粗線只連 B→今；細浪白 C1…C8 疊在上面對讀
            try:
                _ty_now = float(tx_c[tip_i])
            except (TypeError, ValueError, IndexError):
                _ty_now = float(tx_l[tip_i]) if tip_i < len(tx_l) else _tyb
            axt.plot(
                [_tb, int(tip_i)],
                [_tyb, _ty_now],
                color="#ea80fc",
                lw=1.55,
                alpha=0.85,
                zorder=6.7,
            )
            for _ii, _yy, _lab, _col, _tipk in (
                (_t5s, _ty5s, "電⑤起", "#40c4ff", "low"),
                (_t5e, _ty5e, "電⑤終", "#40c4ff", "high"),
                (_ta, _tya, "電A低", "#ff8a80", "low"),
                (_tb, _tyb, "電B末", "#ffd54f", "high"),
            ):
                _pin_pivot_name(
                    axt,
                    int(_ii),
                    float(_yy),
                    _lab,
                    _col,
                    _fp,
                    side="auto",
                    tip=_tipk,
                    n=n_tw,
                    pad_x=0.22,
                    fontsize=8,
                    pri=6,
                )
                _spear_ring(axt, int(_ii), float(_yy), color=_col, zorder=8)
            if _tx_ylabel_span is not None:
                _lo0, _hi0 = float(_tx_ylabel_span[0]), float(_tx_ylabel_span[1])
                _ys_m = [_ty5s, _ty5e, _tya, _tyb, _ty_now]
                axt.set_ylim(
                    min(_lo0, min(_ys_m) - 120.0),
                    max(_hi0, max(_ys_m) + 160.0),
                )
                _tx_ylabel_span = (
                    min(_lo0, min(_ys_m) - 120.0),
                    max(_hi0, max(_ys_m) + 160.0),
                )
    # 夜盤先行：台指電子盤也數 C1…C8（官方夜盤柱），才對得上他講的「夜盤破壞最後一組 3-5」
    # 與加權日盤九波分開釘在 axt；缺日 NaN 已在 _c9_ext_bar_pivots 跳過
    if _c9_extension_active(pack) and len(tx_valid) >= 8 and tip_i >= 0:
        _win_b = [i for i in tx_valid if abs(int(i) - int(i_b_end)) <= 8]
        if _win_b:
            i_tx_b = max(_win_b, key=lambda i: float(tx_h[i]))
        else:
            _before_b = [i for i in tx_valid if int(i) <= int(i_b_end)]
            i_tx_b = int(_before_b[-1]) if _before_b else int(tx_valid[0])
        if int(i_tx_b) < int(tip_i):
            _c9_pivots_tx = _c9_ext_bar_pivots(
                tx_h, tx_l, tx_c, i_bhi=int(i_tx_b), i_now=int(tip_i)
            )
            if len(_c9_pivots_tx) >= 3:
                try:
                    _y_tx_now = float(tx_c[tip_i])
                except (TypeError, ValueError, IndexError):
                    _y_tx_now = float(tx_l[tip_i]) if tip_i < len(tx_l) else 0.0
                _paint_c9_extension_on_bars(
                    axt,
                    pack=pack,
                    i_now=int(tip_i),
                    y_now=float(_y_tx_now),
                    n=n_tw,
                    fp=_fp,
                    tip=None,
                    pin_now=False,
                    side="left",
                    fontsize=8.0,
                    pivots=_c9_pivots_tx,
                )
                _ys_tx = [
                    float(y)
                    for _i, y, _lab in _c9_pivots_tx
                    if y is not None and math.isfinite(float(y))
                ]
                if _ys_tx and _tx_ylabel_span is not None:
                    _lo0, _hi0 = float(_tx_ylabel_span[0]), float(_tx_ylabel_span[1])
                    _lo1 = min(_lo0, min(_ys_tx) - 120.0)
                    _hi1 = max(_hi0, max(_ys_tx) + 160.0)
                    axt.set_ylim(_lo1, _hi1)
                    _tx_ylabel_span = (_lo1, _hi1)
    # 不再貼左下長說明：會跟右標／戳／K互卡；說明改靠戳＋右欄

    # —— 中：加權日盤價（先畫底帶在K下一層，再畫K）——
    tw_supports = _tw_support_ladder(pack)
    tip_anchors = _tw_tip_anchors(pack)
    # 上下多留：高點浪名在尖上、低點浪名在尖下；頂上再加一截給白底戳
    ymin = min([min(lows), y5s, y_alow] + list(tw_supports)) - 720
    ymax = max([max(highs), y5e, y_b_end]) + 1550
    # 預估端先算：同價只留端點「飆預測」，左青帶／右欄不准再貼一次
    tip_pre = _c_forecast_tip(
        i_now=i_now, y_now=y_now, y_ref=y_bhi, lows=c_seg_lows, anchors=tip_anchors
    )
    skip_lab_ys = (
        [float(tip_pre["anchor_y"])] if tip_pre.get("anchor_y") is not None else []
    )
    # 他點過的錨會上右欄 → 左欄不准再貼同價
    skip_lab_ys = list(skip_lab_ys) + [float(v) for v in tip_anchors]
    # 黃＝大量撐壓、灰＝下一層、青＝飆預測位階帶（兩底色不准互疊）
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
        vol_lookback=_FAR_TEACH_VOL_LOOKBACK,
        vol_sr=far_vol_sr,
        avoid_top_left_stamp=True,
        pack=pack,
    )
    # 區帶兩標改到九波縮圖定位後再畫（須清過縮圖右緣，否則 AI 標左半被裁）
    sr = zone.get("sr") or {}
    sr_skip = zone.get("sr_skip") or {}
    if zone.get("i_vmax") is not None:
        i_vmax = int(zone["i_vmax"])
    _paint_live_candles(ax, None, opens, highs, lows, closes, vols, candle_body_up_taiwan)
    # 加權自己的大量撐壓日金K＋下一層亮桃K（豎線稍後只畫在加權價／量欄）
    # 畫圖升格後跟 zone.vol_sr（黃＝現況層）；對質仍看 far_vol_sr raw
    _far_paint_sr = zone.get("vol_sr") if isinstance(zone.get("vol_sr"), dict) else far_vol_sr
    _tw_i_pri = int(i_vmax) if i_vmax is not None else None
    _tw_i_nxt = (_far_paint_sr or {}).get("i_next") if isinstance(_far_paint_sr, dict) else None
    if _tw_i_nxt is None and isinstance(_far_paint_sr, dict):
        _tw_i_pri2, _tw_i_nxt = _vol_sr_index_on_axis(
            _far_paint_sr, axis_ymds=[_ymd(r.get("date")) for r in bars]
        )
        if _tw_i_pri is None:
            _tw_i_pri = _tw_i_pri2
    _paint_vol_sr_mark_on_axis(
        ax,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        i_primary=_tw_i_pri,
        i_next=int(_tw_i_nxt) if _tw_i_nxt is not None else None,
        date_primary=_ymd(bars[_tw_i_pri].get("date")) if _tw_i_pri is not None else "",
        date_next=_ymd(((_far_paint_sr or {}).get("next") or {}).get("date")),
        fp=_fp,
    )
    # 遠窗不加權浪段大底色（⑤／B／C axvspan）：兩大塊半透底圖擋K，只留折線
    # 推進⑤：4/1→6/23（藍實線）
    ax.plot([i5s, i5e], [y5s, y5e], color="#40c4ff", lw=2.6, zorder=7)
    # 大A：6/23→7/29（粉）
    ax.plot([i5e, i_alow], [y5e, y_alow], color="#ff8a80", lw=2.35, zorder=7)
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
    # 先算九波轉折：大C 紫線要不要淡、預估虛線要不要讓位，都看這組
    _c9_now = _c9_extension_active(pack)
    _c9_pivots_far = (
        _c9_ext_bar_pivots(
            highs, lows, closes, i_bhi=int(i_b_end), i_now=int(i_now)
        )
        if _c9_now
        else []
    )
    # 大C 紫折：跟 C1–C4 底色四段對齊（五點）；缺錨才退回舊兩段
    _c9_major_fade = _c9_now and len(_c9_pivots_far) >= 3
    _c_spans_far = _resolve_huang_c_daily_spans(bars, lows=lows, highs=highs)
    if not _paint_huang_c_degree_path(ax, _c_spans_far, fade=_c9_major_fade):
        ax.plot(
            [i_b_end, i_c, i_now],
            [y_b_end, float(closes[i_c]), y_now],
            color="#ea80fc",
            lw=1.15 if _c9_major_fade else 2.1,
            alpha=0.28 if _c9_major_fade else 1.0,
            zorder=5.5 if _c9_major_fade else 7,
            solid_capstyle="round",
            solid_joinstyle="round",
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
    # 遠窗：預估紫／暗虛線＋端點已刪（使用者 2026-11-11）；tip 仍算 xlim／右欄
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
        draw=False,
    )
    fut_x = float(tip.get("fut_x") or fut_x)
    # 矛點細圈；9波時末日已有 C7／C8 細圈；今紫圈也不再疊（對齊近窗）
    _macro_spear = [
        (i5s, y5s, "#40c4ff"),
        (i5e, y5e, "#40c4ff"),
        (i_alow, y_alow, "#ff8a80"),
        (i_b_end, y_b_end, "#ffd54f"),
    ]
    for ii, yy, col in _macro_spear:
        _spear_ring(ax, ii, yy, color=col, zorder=8, hot=False)
    # 末根加權K參數先記；xlim／右標之後再蓋回（與費半同：不准被裁／壓掉）
    _tw_span = max(highs) - min(lows) if highs and lows else 0.0
    _tw_min_body = max(
        _candle_span_min_body(highs, lows, frac=_LIVE_CANDLE_MIN_BODY_FRAC),
        float(_tw_span) * 0.02,
    )
    _tw_san = _sanitize_bar_ohlc(
        {
            "open": opens[i_now] if i_now < len(opens) else closes[i_now],
            "high": highs[i_now] if i_now < len(highs) else closes[i_now],
            "low": lows[i_now] if i_now < len(lows) else closes[i_now],
            "close": closes[i_now],
        }
    )
    _tw_last_repaint = {
        "i": i_now,
        "o": float(_tw_san["open"]),
        "h": float(_tw_san["high"]),
        "l": float(_tw_san["low"]),
        "c": float(_tw_san["close"]),
        "prev_c": _prev_valid_close(closes, int(i_now), opens=opens),
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
    # 遠窗：9波擴延時 K 上釘 C1…C8（官方柱）＋虛線 C9
    _paint_c9_extension_on_bars(
        ax,
        pack=pack,
        i_now=i_now,
        y_now=y_now,
        n=n_axis,
        fp=_fp,
        tip=tip,
        pin_now=True,
        side="left",
        fontsize=9,
        pivots=_c9_pivots_far,
    )
    tip_skip: set = set()
    # 9波擴延時右欄只留關鍵：大B末／此刻／預測錨；⑤起終／大A 已有圖上釘點＋日期，再上右欄＝互壓
    if _c9_now:
        right_notes = [
            {
                "x": i_b_end,
                "y": y_b_end,
                "text": f"大B末 {_px(y_b_end)}",
                "color": "#ffd54f",
            },
            {
                "x": i_now,
                "y": y_now,
                "text": f"{_c9_now_step_label()}今 {_px(y_now)}",
                "color": "#ea80fc",
            },
        ]
    else:
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
            {
                "x": i_now,
                "y": y_now,
                "text": f"大C今 {_px(y_now)}",
                "color": "#ea80fc",
            },
        ]
        # 近窗細分（若窗內有）淡標，不搶大結構；C9 時不加
        if anc:
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
    _c_seg_highs = list(highs[i_c : i_now + 1]) if highs else []
    if tip_anchor is not None:
        right_notes.append(
            {
                "x": n_axis - 1,
                "y": float(tip_anchor),
                "text": _format_tw_pred_note(
                    float(tip_anchor),
                    pack=pack,
                    lows=c_seg_lows,
                    highs=_c_seg_highs or highs,
                ),
                "color": "#ea80fc",
            }
        )
        tip_skip.add(round(float(tip_anchor), 1))
    # 9波／改口低點區：右欄只留他說的錨；結構近撐太遠＝互壓雜訊
    if (
        not _c9_now
        and sr_skip.get("support") is not None
        and round(float(sr_skip["support"]), 1) not in tip_skip
    ):
        _sup_y = float(sr_skip["support"])
        _sup_role = _tw_level_role(pack, _sup_y)
        # 台指壓41760：不准先貼「飆預測」佔席，改由 _tw_pred_right_notes 寫水平壓｜≠下降壓線
        if _sup_role == "台指壓力" or abs(_sup_y - 41760.0) < 0.6:
            pass
        else:
            right_notes.append(
                {
                    "x": n_axis - 1,
                    "y": _sup_y,
                    "text": _biaoke_pred_label(_sup_y),
                    "color": "#4dd0e1",
                }
            )
            tip_skip.add(round(_sup_y, 1))
    # 他最新錨（虛線梯）上右欄；跟著題旨換，不准寫死單一 44210
    for anch in tip_anchors:
        if round(float(anch), 1) in tip_skip:
            continue
        right_notes.append(
            {
                "x": n_axis - 1,
                "y": float(anch),
                "text": _format_tw_pred_note(
                    float(anch),
                    pack=pack,
                    lows=c_seg_lows,
                    highs=_c_seg_highs or highs,
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack,
            n=n_axis,
            lows=c_seg_lows,
            tip_skip=tip_skip,
            bars=bars,
            highs=_c_seg_highs or highs,
        )
    )
    # 右標在末日右側；拉開欄位，不准蓋住 K 上 C7／C8 圓點
    x_right_col = float(n_axis) + 2.55
    try:
        x_right_col = max(x_right_col, float(tip.get("fut_x") or n_axis) + 0.85)
    except (TypeError, ValueError):
        pass
    # 右欄買點／上緣／深殺＋今標：再右移半欄，字盒不壓浪點
    if any(
        abs(float(n0.get("y") or 0) - lv) < 1.0
        for n0 in right_notes
        for lv in (37837.0, 35579.0, 31705.0)
    ):
        x_right_col = max(x_right_col, float(n_axis) + 3.05)
    x_sox_col = x_right_col + 0.40
    if _sox_right_deferred and _sox_ylabel_span is not None:
        # 費半價窗窄：間距略鬆；標籤 Y 鎖真價（互撞丟低優先），虛線水平接標
        _place_live_right_labels(
            axu,
            _sox_right_deferred,
            n=n_axis,
            ymin=float(_sox_ylabel_span[0]),
            ymax=float(_sox_ylabel_span[1]),
            fp=_fp,
            level_dash=True,
            min_gap=(float(_sox_ylabel_span[1]) - float(_sox_ylabel_span[0])) * 0.062,
            x_col=x_sox_col,
            nudge=True,
            fontsize=8.5,
        )
    if _tx_right_notes and _tx_ylabel_span is not None:
        # 電子盤右標：真價虛線水平接標；標籤 Y 鎖真價（互撞丟低優先）
        _place_live_right_labels(
            axt,
            _tx_right_notes,
            n=n_tw,
            ymin=float(_tx_ylabel_span[0]),
            ymax=float(_tx_ylabel_span[1]),
            fp=_fp,
            level_dash=True,
            min_gap=(float(_tx_ylabel_span[1]) - float(_tx_ylabel_span[0])) * 0.13,
            x_col=x_right_col + 0.15,
            nudge=True,
            fontsize=8.5,
        )
    _place_live_right_labels(
        ax,
        right_notes,
        n=n_axis,
        ymin=ymin,
        ymax=ymax,
        fp=_fp,
        level_dash=True,
        # 加權資訊多：再鬆間距；標籤 Y 鎖真價、虛線水平接標（互撞丟低優先）
        min_gap=(ymax - ymin) * (0.092 if _c9_now else 0.078),
        x_col=x_right_col,
        nudge=True,
        fontsize=8.5 if _c9_now else 9.0,
    )
    _set_upright_ylabel(ax, "加權日盤", fp=_fp, color=_LIVE_MUTED, fontsize=10)

    # —— 下：加權日量（最大量黃＝與上方同索引當日K對齊）——
    _paint_vol_bars_max_yellow(
        axv,
        vols,
        opens,
        closes,
        candle_body_up_taiwan,
        fp=_fp,
        title="加權量",
        date_lab=_ymd(bars[i_vmax].get("date")) if i_vmax is not None else "",
        annotate=False,  # 短標改由黃／白層級標；不准再疊「最大量」互壓
    )
    _set_upright_ylabel(axv, "加權量", fp=_fp, color=_LIVE_MUTED, fontsize=9)
    # 加權 10/15 黃豎線只畫加權價＋量；不准延伸到費半／電子盤（各自爆大量日不同）
    _paint_vol_sr_day_guides(axv, i_primary=_tw_i_pri, i_next=_tw_i_nxt)
    # 跟超近窗同規：量欄黃／白兩柱短標（月日）
    _paint_teach_vol_layer_bars(
        axv,
        vols,
        i_primary=_tw_i_pri,
        i_next=_tw_i_nxt,
        i_next_2nd=(far_vol_sr or {}).get("i_next_2nd")
        if isinstance(far_vol_sr, dict)
        else None,
        bars=bars,
        fp=_fp,
    )
    if axv.get_ylim()[1] <= (max(vols) if any(vols) else 1) * 1.01:
        axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.45)

    want = {
        _ymd(bars[0].get("date")),
        _ymd(bars[i5s].get("date")),
        _ymd(bars[i5e].get("date")),
        _ymd(bars[i_alow].get("date")),
        "20260225",
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
    # 四欄共用軸：延長格只寫月日，不准寫「費半」（電盤／加權／量會一起被誤標）
    t2, l2 = _far_shared_axis_xticks(
        bars,
        sox_extra_dates=sox_extra_dates,
        want=want,
        i5s=i5s,
        i5e=i5e,
        i_alow=i_alow,
        i_b_end=i_b_end,
        min_gap=6,
    )
    # 右標／xlim：定長滾動下右欄 pad 鎖死；費半可多日時取較長軸
    x_right = max(
        _teach_xlim_right(
            max(int(n_axis), int(n_tw)),
            tip_xlim=float(tip.get("xlim_right") or n_tw) + 2.0,
            right_col=max(float(x_sox_col), float(x_right_col)),
            fut_x=float(fut_x),
        ),
        float(x_sox_col) + 6.4,
    )
    # 遠窗自 3 月底起：左側多留一格，⑤起首根不准被裁
    need_apr = True
    x_left = -1.35 if need_apr else -0.6
    for a in (axu, axt, ax, axv):
        a.set_xlim(x_left, x_right)
    # xlim 定完再蓋末根加權K（與費半同序；縮圖必見，不准量在價無）
    if _tw_last_repaint:
        _paint_one_live_candle(
            ax,
            int(_tw_last_repaint["i"]),
            open_=float(_tw_last_repaint["o"]),
            high=float(_tw_last_repaint["h"]),
            low=float(_tw_last_repaint["l"]),
            close=float(_tw_last_repaint["c"]),
            prev_c=_tw_last_repaint.get("prev_c"),
            candle_up=candle_body_up_taiwan,
            min_body=float(_tw_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=14,
            z_body=15,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
    # xlim 定完再蓋末根費半K（避免右標／裁切吃掉周五官方柱）
    # 電子盤／費半黃框與末根同口：先算 tip，休市末K不准停在軸上殘值
    _tx_chg_tip = _resolve_tx_after_hours_tip(db_path, pack)
    _tx_night_live = bool(_tx_night_session_live(_query_now_from_pack(pack)))
    if _tx_last_repaint and _tx_chg_tip and not _tx_night_live:
        try:
            _tip_tx_c = float(_tx_chg_tip.get("close") or 0)
        except (TypeError, ValueError):
            _tip_tx_c = 0.0
        _tip_tx_asof = _ymd(_tx_chg_tip.get("asof"))
        if _tip_tx_c > 0:
            _tx_last_repaint["c"] = _tip_tx_c
            if _tip_tx_asof:
                _tx_last_repaint["asof"] = _tip_tx_asof
                # 末根索引／OHLC 釘官方夜盤日，不准停在加權填日格
                for _i, _r in enumerate(bars):
                    if _ymd((_r or {}).get("date")) != _tip_tx_asof:
                        continue
                    if _i >= len(tx_c):
                        break
                    _tx_last_repaint["i"] = int(_i)
                    try:
                        # 官方列優先（軸可能被前收填污染）
                        _off = next(
                            (
                                r
                                for r in reversed(list(tx_rows or []))
                                if _ymd((r or {}).get("date")) == _tip_tx_asof
                                and float((r or {}).get("close") or 0) > 0
                            ),
                            None,
                        )
                    except Exception:
                        _off = None
                    if isinstance(_off, dict):
                        try:
                            _tx_last_repaint["o"] = float(
                                _off.get("open") or _tip_tx_c
                            )
                            _tx_last_repaint["h"] = float(
                                _off.get("high") or _tip_tx_c
                            )
                            _tx_last_repaint["l"] = float(
                                _off.get("low") or _tip_tx_c
                            )
                            _tx_last_repaint["c"] = float(
                                _off.get("close") or _tip_tx_c
                            )
                        except (TypeError, ValueError):
                            pass
                    _prev_i = next(
                        (
                            j
                            for j in range(int(_i) - 1, -1, -1)
                            if j in _tx_valid_set
                        ),
                        None,
                    )
                    if _prev_i is not None and _tx_chg_tip.get("prev"):
                        try:
                            _tx_last_repaint["prev"] = float(_tx_chg_tip["prev"])
                        except (TypeError, ValueError):
                            _tx_last_repaint["prev"] = float(tx_c[_prev_i])
                    break
    if _sox_last_repaint:
        # 黃框＋末根K同口：只認真實美股列（Yahoo 已注入）；不准軸上前收填日殘值
        # 現金盤中才 live；盤後／盤前殘旗不准蓋官方收
        _sox_live = (pack or {}).get("live_sox") if isinstance(pack, dict) else None
        if not isinstance(_sox_live, dict):
            _sox_live = live_sox if isinstance(live_sox, dict) else None
        _sox_is_live = (
            isinstance(_sox_live, dict)
            and float((_sox_live or {}).get("close") or 0) > 0
            and int((_sox_live or {}).get("live_session") or 0) == 1
            and _sox_cash_session_live(_query_now_from_pack(pack))
        )
        _pair = _us_real_close_pair(sox, _sox_live if _sox_is_live else None)
        _tip_close = _pair.get("close")
        _tip_asof = _ymd(_pair.get("asof")) or ""
        if _sox_is_live:
            _tip_asof = _ymd(_sox_live.get("date")) or _tip_asof
        # tip 索引必須＝黃框日期格（真實美股日／盤中日），不准停在加權填日末格
        _tip_i = _sox_axis_index_for_ymd(
            bars,
            n_tw=n_tw,
            sox_extra_dates=sox_extra_dates,
            ymd=_tip_asof,
            n_axis=n_axis,
        )
        if _tip_i is None and i_live is not None:
            _tip_i = int(i_live)
        if _tip_i is not None:
            _sox_last_repaint["i"] = int(_tip_i)
            _sox_last_repaint["prev"] = next(
                (
                    j
                    for j in range(int(_tip_i) - 1, -1, -1)
                    if j < len(sox_c) and sox_c[j] == sox_c[j]
                ),
                None,
            )
        if _tip_close is not None and float(_tip_close or 0) > 0:
            _real = None
            _asof_p = _tip_asof
            for _r in reversed(list(sox or [])):
                if _ymd((_r or {}).get("date")) == _asof_p:
                    _real = _r
                    break
            if _sox_is_live:
                try:
                    _sox_last_repaint["o"] = float(
                        _sox_live.get("open") or _tip_close
                    )
                    _sox_last_repaint["h"] = float(
                        _sox_live.get("high") or _tip_close
                    )
                    _sox_last_repaint["l"] = float(
                        _sox_live.get("low") or _tip_close
                    )
                except (TypeError, ValueError):
                    pass
            elif _real:
                try:
                    _sox_last_repaint["o"] = float(_real.get("open") or _tip_close)
                    _sox_last_repaint["h"] = float(_real.get("high") or _tip_close)
                    _sox_last_repaint["l"] = float(_real.get("low") or _tip_close)
                except (TypeError, ValueError):
                    pass
            _sox_last_repaint["c"] = float(_tip_close)
        else:
            _tip_close = float(_sox_last_repaint["c"])
        _prev = _sox_last_repaint.get("prev")
        _prev_c = (
            float(_pair["prev_close"])
            if _pair.get("prev_close")
            else (float(sox_c[_prev]) if _prev is not None else None)
        )
        _paint_one_live_candle(
            axu,
            int(_sox_last_repaint["i"]),
            open_=float(_sox_last_repaint["o"]),
            high=float(_sox_last_repaint["h"]),
            low=float(_sox_last_repaint["l"]),
            close=float(_sox_last_repaint["c"]),
            prev_c=_prev_c,
            candle_up=candle_body_up_taiwan,
            min_body=float(_sox_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=14,
            z_body=15,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
        # 末根K再蓋一次；費半漲跌黃框改圖層座標、與加權黃框錯開
        _paint_one_live_candle(
            axu,
            int(_sox_last_repaint["i"]),
            open_=float(_sox_last_repaint["o"]),
            high=float(_sox_last_repaint["h"]),
            low=float(_sox_last_repaint["l"]),
            close=float(_sox_last_repaint["c"]),
            prev_c=_prev_c,
            candle_up=candle_body_up_taiwan,
            min_body=float(_sox_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=18,
            z_body=19,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
        # 空心 tip：略偏右＝今收；只畫一圈細線（不准疊兩次變粗）
        _spear_ring(
            axu,
            float(_sox_last_repaint["i"]) + 0.38,
            float(_sox_last_repaint["c"]),
            color="#ea80fc",
            zorder=20,
            hot=True,
            clip_on=False,
        )
        _sox_chg_tip = {
            "close": float(_tip_close),
            "prev": _pair.get("prev_close"),
            "asof": _tip_asof,
            "live": bool(_sox_is_live),
        }
    if _tx_last_repaint:
        _prev_tx = _tx_last_repaint.get("prev")
        # 末根索引：若校完後仍不在真夜盤集合，改釘 tx_valid 最後一根
        try:
            _tip_final = int(_tx_last_repaint["i"])
        except (TypeError, ValueError):
            _tip_final = -1
        if tx_valid and (_tip_final < 0 or _tip_final not in _tx_valid_set):
            _tip_final = int(tx_valid[-1])
            _tx_last_repaint["i"] = int(_tip_final)
            try:
                _tx_last_repaint["o"] = float(tx_o[_tip_final])
                _tx_last_repaint["h"] = float(tx_h[_tip_final])
                _tx_last_repaint["l"] = float(tx_l[_tip_final])
                _tx_last_repaint["c"] = float(tx_c[_tip_final])
                if _tip_final < len(bars):
                    _tx_last_repaint["asof"] = _ymd(bars[_tip_final].get("date"))
            except (TypeError, ValueError, IndexError):
                pass
        # 右側還有更新的真夜盤K → 虛線／矛點跟過去（不准停在左側舊格）
        elif tx_valid and _tip_final in _tx_valid_set and int(tx_valid[-1]) > _tip_final:
            _tip_final = int(tx_valid[-1])
            _tx_last_repaint["i"] = int(_tip_final)
            try:
                _tx_last_repaint["o"] = float(tx_o[_tip_final])
                _tx_last_repaint["h"] = float(tx_h[_tip_final])
                _tx_last_repaint["l"] = float(tx_l[_tip_final])
                _tx_last_repaint["c"] = float(tx_c[_tip_final])
                if _tip_final < len(bars):
                    _tx_last_repaint["asof"] = _ymd(bars[_tip_final].get("date"))
            except (TypeError, ValueError, IndexError):
                pass
        _paint_one_live_candle(
            axt,
            int(_tx_last_repaint["i"]),
            open_=float(_tx_last_repaint["o"]),
            high=float(_tx_last_repaint["h"]),
            low=float(_tx_last_repaint["l"]),
            close=float(_tx_last_repaint["c"]),
            prev_c=_prev_tx,
            candle_up=candle_body_up_taiwan,
            min_body=float(_tx_last_repaint["min_body"]),
            width=0.86,
            wick_lw=2.05,
            z_wick=18,
            z_body=19,
            edgecolor="#ffffff",
            edge_lw=0.9,
        )
        _spear_ring(
            axt,
            float(_tx_last_repaint["i"]) + 0.38,
            float(_tx_last_repaint["c"]),
            color="#ea80fc",
            zorder=20,
            hot=True,
            clip_on=False,
        )
        # tip 校完才畫現價虛線：穿過末根 → 右欄標；Y＝今收
        if _tx_last_repaint.get("rail_pending"):
            try:
                _rail_px = float(_tx_last_repaint["c"])
            except (TypeError, ValueError):
                _rail_px = 0.0
            _rail_i = int(_tx_last_repaint["i"])
            if _rail_px > 0 and _rail_i >= 0:
                _rail_hit = _nearest_bar_touching_px(
                    bars, tx_h, tx_l, px=_rail_px, before_i=int(_rail_i)
                )
                _rail_near = None
                if not _c9_extension_active(pack):
                    _rail_near = _nearest_vol_support_row(tx_vol_sr, px=_rail_px)
                _paint_tx_now_price_rail(
                    axt,
                    px=_rail_px,
                    tip_i=int(_rail_i),
                    fp=_fp,
                    live=bool(_tx_last_repaint.get("rail_live")),
                    asof_ymd=str(_tx_last_repaint.get("asof") or ""),
                    hit=_rail_hit,
                    near_sup=_rail_near,
                    x_label=float(x_right_col) + 0.15,
                )
                _tx_last_repaint["rail_pending"] = False
    if _tw_last_repaint:
        # 9波末日已有 C7／C8 細圈時，不再疊今收圈（雙圈太粗）
        if not (_c9_now and len(_c9_pivots_far) >= 3):
            _spear_ring(
                ax,
                float(_tw_last_repaint["i"]) + 0.38,
                float(_tw_last_repaint["c"]),
                color="#ea80fc",
                zorder=16,
                hot=True,
                clip_on=False,
            )
    # 欄間小間距放日期：費半／電子盤／加權三欄底緣都標（量欄仍有完整軸）
    # 末日刻度必顯；各欄依自己盤中螢光／收盤白字
    for a in (axu, axt, ax, axv):
        a.set_xticks(t2)
        a.set_xticklabels(l2, fontproperties=_fp(7.5, "normal"), color=_LIVE_TEXT)
        a.tick_params(axis="x", labelbottom=True, length=3, pad=3.5)
    _wall_neon = _query_now_from_pack(pack)
    _last_i_tw = max(0, int(n_tw) - 1)
    _paint_axis_last_date_neon(
        axu, last_i=_last_i_tw, live=_sox_cash_session_live(_wall_neon), fp=_fp
    )
    _tx_neon_i = _last_i_tw
    if _tx_last_repaint:
        try:
            _tx_neon_i = int(_tx_last_repaint["i"])
        except (TypeError, ValueError):
            _tx_neon_i = _last_i_tw
    _paint_axis_last_date_neon(
        axt, last_i=int(_tx_neon_i), live=_tx_night_session_live(_wall_neon), fp=_fp
    )
    _tw_live_neon = _twii_cash_session_live(_wall_neon)
    _paint_axis_last_date_neon(ax, last_i=_last_i_tw, live=_tw_live_neon, fp=_fp)
    _paint_axis_last_date_neon(axv, last_i=_last_i_tw, live=_tw_live_neon, fp=_fp)
    # 費半官方日若延長過加權末日：延長末日另用費半盤中色
    if t2 and int(t2[-1]) > _last_i_tw:
        _paint_axis_last_date_neon(
            axu, last_i=int(t2[-1]), live=_sox_cash_session_live(_wall_neon), fp=_fp
        )
    for a in (axu, axt, ax, axv):
        for lab in a.get_yticklabels():
            lab.set_fontproperties(_fp(8, "bold"))
            lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    vz_y = _teach_vol_sr_title_bit(
        far_vol_sr, bars=bars, highs=highs, lows=lows, i_vmax=i_vmax
    )
    vz_c = _teach_cyan_band_title_bit(sr, pack=pack)
    sox_bit = ""
    sox_preds = ((pack or {}).get("pred_levels") or {}).get("sox") or []
    sox_bit = ""
    if sox_preds:
        if any(str(r.get("role") or "") == "再回測" for r in sox_preds):
            sox_bit = "｜費半青＝已破4/28→下一撐（2/25＝8498回測K同軸）"
        else:
            sox_bit = "｜費半青＝已破A→下一撐（4/28回測K同軸）"
    # 不准 [:72]：會把「次回測4/28低9,865」裁成「9,」；也不准裁掉 2/25 8498
    pred_foot = str(pack.get("pred_note") or "")[:280]
    # 白字標題縮短讓出右上；費半青註改第二行，不准跟黃框互壓
    left_d = _ymd(bars[0].get("date")) if bars else ""
    fig.text(
        0.05,
        0.982,
        f"第1張（遠窗・{_md(left_d) or '自3月底'}→最新）：費半｜台指電子盤｜加權日盤⑤／ABC｜加權量　｜　{vz_y}　｜　{vz_c}",
        fontproperties=_fp(11, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    _pb_bit = (
        "｜他說C3下降壓＝口述斜線（圖上紫帶C3・細白下降壓示意／無報價）｜紫線＝大C路徑"
        if _pack_pressure_break_on(pack)
        else ""
    )
    fig.text(
        0.05,
        0.961,
        f"{_macro_wave_calendar_line()}｜藍⑤｜粉A｜金虛B｜紫C｜"
        f"費半＋台指電子盤同時段｜C走完≠新五波升{sox_bit}{_pb_bit}",
        fontproperties=_fp(9, "bold"),
        color="#ce93d8",
        ha="left",
        va="top",
    )
    # 三戳：鎖在各欄 axes 左上近上緣（框內）；欄頂已加高天空，戳上移不准出格、不准擋九波／縮圖K
    _stamp_ax_x, _stamp_ax_y = 0.02, 0.96
    if _sox_chg_tip:
        _paint_index_last_chg_tip(
            fig,
            close=float(_sox_chg_tip["close"]),
            prev_close=_sox_chg_tip.get("prev"),
            label_prefix="費半",
            fp=_fp,
            x=_stamp_ax_x,
            y=_stamp_ax_y,
            ha="left",
            va="top",
            asof_ymd=str(_sox_chg_tip.get("asof") or ""),
            chart_asof=str(as_of or ""),
            session_live=bool(_sox_chg_tip.get("live")),
            pack=pack,
            ax=axu,
        )
    # 漲跌一律對官方參考價（CRefPrice）；戳價＝tip 一口（與末根K已同步）
    if _tx_chg_tip:
        _tx_clock = str(
            _tx_chg_tip.get("clock")
            or ((live_tx or (pack or {}).get("live_tx") or {}).get("update_time"))
            or ""
        )
        _tx_asof_stamp = str(
            _tx_chg_tip.get("asof")
            or (_tx_last_repaint or {}).get("asof")
            or _ymd(((live_tx or (pack or {}).get("live_tx") or {}).get("date")))
            or (
                bars[_tx_last_repaint["i"]].get("date")
                if _tx_last_repaint and bars
                else ""
            )
            or ""
        )
        try:
            _tx_stamp_px = float(_tx_chg_tip.get("close") or 0)
        except (TypeError, ValueError):
            _tx_stamp_px = 0.0
        if _tx_stamp_px <= 0 and _tx_last_repaint:
            try:
                _tx_stamp_px = float(_tx_last_repaint.get("c") or 0)
            except (TypeError, ValueError):
                _tx_stamp_px = 0.0
        if _tx_stamp_px > 0:
            _paint_tx_after_hours_tip(
                fig,
                close=float(_tx_stamp_px),
                prev_close=_tx_chg_tip.get("prev"),
                label_prefix=str(_tx_chg_tip.get("label") or "台指電子盤"),
                fp=_fp,
                x=_stamp_ax_x,
                y=_stamp_ax_y,
                ha="left",
                va="top",
                clock=_tx_clock,
                asof_ymd=_tx_asof_stamp,
                # 夜盤進行中才盤中；MIS 末筆鐘／殘 live 不准白天冒充盤中
                session_live=_tx_night_live
                and bool(live_tx or (pack or {}).get("live_tx") or _tx_clock),
                pack=pack,
                ax=axt,
            )
    _paint_teach_query_stamp(
        fig,
        bars,
        pack=pack,
        close=closes[-1],
        fp=_fp,
        x=_stamp_ax_x,
        y=_stamp_ax_y,
        ha="left",
        va="top",
        label_prefix="加權",
        ax=ax,
        db_path=db_path,
    )
    # 下降壓改口當令：加權欄左下寫死斜線≠41760，三窗同口
    _paint_c3_vs_41760_legend(ax, fp=_fp, pack=pack)
    # 第一組／第二組＝C3：他文＋官方柱對得上的跨度，畫給人對圖（非發明報價）
    _paint_c3_group12_span_labels(
        ax, bars, fp=_fp, pack=pack, lows=lows, highs=highs
    )
    # 跨度標之後再蓋回縮圖K：基本K永遠可見，不准只剩色帶／折線
    _paint_live_candles(
        ax, None, opens, highs, lows, closes, vols, candle_body_up_taiwan
    )
    _finish_last_twii_candle(
        ax,
        i_now=int(i_now),
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_body_up_taiwan,
        ymin=float(ax.get_ylim()[0]),
        ymax=float(ax.get_ylim()[1]),
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
    # 八浪縮圖：縮小貼加權左下，再往左推，不准擋右下白底戳／縮圖K
    _far_ins = _eight_wave_inset_rect_left_of_vmax(
        ax,
        fig,
        i_vmax=i_vmax,
        ymin=float(ymin),
        ymax=float(ymax),
        n_bars=n_tw,
        scale=0.56,
        pin_bottom=True,
    )
    try:
        _ins_l, _ins_b, _ins_w, _ins_h = _far_ins
        _axpos = ax.get_position()
        # 右緣鎖在欄寬 42% 內（縮圖略放大仍不准擋右標）
        _max_right = float(_axpos.x0) + float(_axpos.width) * 0.42
        if _ins_l + _ins_w > _max_right:
            _ins_l = max(float(_axpos.x0) + 0.006, _max_right - _ins_w)
        _far_ins = (float(_ins_l), float(_ins_b), float(_ins_w), float(_ins_h))
    except Exception:
        pass
    _c9_far = _c9_extension_active(pack)
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_eight_wave_now_key(pack),
        detail=False,
        rect=_far_ins,
        title="九波擴延" if _c9_far else "八浪",
        c9_ext=_c9_far,
        flash_pivots=_c9_pivots_far if _c9_far else None,
    )
    # 黃標／AI標：同一 x，貼縮圖右外側；再右挪離開大A底尖點（區帶後畫會蓋）
    _zx = _zone_label_x_clear_of_inset(
        ax, fig, _far_ins, fallback=float(_TEACH_ZONE_LABEL_X)
    )
    try:
        _x0, _x1 = ax.get_xlim()
        _xspan = max(float(_x1) - float(_x0), 1e-9)
        _piv_ax = (float(i_alow) - float(_x0)) / _xspan
        if float(_zx) < float(_piv_ax) + 0.14:
            _zx = min(0.58, float(_piv_ax) + 0.18)
    except Exception:
        pass
    _paint_c9_low_zone_band(ax, pack, fp=_fp, label_x=_zx)
    _paint_ai_end_zone_band(ax, pack, fp=_fp, label_x=_zx)
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)
    if not (os.path.isfile(save_path) and os.path.getsize(save_path) > 4000):
        return ""
    # 四欄加高後易觸 Telegram 寬+高上限 → 等比縮到可 sendPhoto
    _shrink_png_for_telegram(save_path)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_self_pred_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """專圖：主＝我的判斷預估；淡＝他說位輔助。≠買訊。

    依據＝官方加權轉折／量＋庫內費半／納指；與他說分欄標清。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_body_up_taiwan
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
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
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
    ax.set_xlim(
        -0.5,
        _teach_xlim_right(
            int(n),
            right_col=float(n) + float(_TEACH_RIGHT_GUTTER),
            extra=-6.0,  # 我估主圖右欄較短
        ),
    )

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



def _render_twii_c_wave_60_dark(
    db_path: str, save_path: str, pack: Dict[str, Any], *, kind: str = "micro"
) -> str:
    """超近窗：加權日盤 60 分 K，只顯示大 C（黃培碩 C1–C4＋飆大口頭）。

    自 10/6（大C起／大B末）起軸；前面大B不進窗，免 x 軸擠爆。
    近窗仍走原本日K特寫；kind 預設 micro（標題超近窗）。不是買訊。
    """
    pack = _ensure_teach_pack_preds(db_path, pack)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_body_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    if not save_path:
        return ""
    try:
        from kline_hop import fetch_yahoo_minutes

        fetch_yahoo_minutes("TWII", "60", db_path)
        # 加權指數無成交量；同路抓 0050 60 分真量當代理（見 _attach_twii60_volume_proxy）
        fetch_yahoo_minutes("0050", "60", db_path)
    except Exception:
        pass
    rows_full = _load_twii60_day_rows(db_path, since_ymd=_C_WAVE_60_SINCE_YMD)
    if len(rows_full) < 16:
        return ""
    # 定長滾動：新60分K進來不把 x 軸無限拉長；永遠留最新根
    rows = _window_huang_c60_rows(rows_full)
    if len(rows) < 16:
        rows = rows_full
    # 日K只給白底戳／對照，不准把大B日柱拉進60分軸
    daily_all = _twii_bars_for_teach(db_path, 80, pack) or []
    daily = [b for b in daily_all if _ymd(b.get("date")) >= _C_WAVE_60_SINCE_YMD]
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(rows)
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r["volume"]) for r in rows]
    vol_proxy = any(str(r.get("vol_src") or "") == "0050" for r in rows)
    i_now = n - 1
    y_now = float(closes[i_now])
    tip_anchors = _tw_tip_anchors(pack)
    tw_supports = _tw_support_ladder(pack)
    tip = _c_forecast_tip(
        i_now=i_now,
        y_now=y_now,
        y_ref=y_now,
        lows=lows,
        anchors=tip_anchors,
    )
    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(15.6, 10.6 if kind == "near" else 11.2),
        dpi=NAV_CHART_DPI,
        sharex=True,
        # 量欄加高：黃／灰帶對應的爆大量標要一眼讀得清
        gridspec_kw=dict(height_ratios=(5.0, 2.35), hspace=0.12),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    # 先算大量撐壓／下一層：Y 軸要裝得下灰帶（若往下次層撐）
    c60_vol_sr = _resolve_teach_vol_sr(rows, lookback=40, preview_below=True)
    _nxt = (c60_vol_sr.get("next") or {}) if isinstance(c60_vol_sr, dict) else {}
    _y_floor = [min(lows)] + list(tw_supports)
    if _nxt.get("low"):
        try:
            _y_floor.append(float(_nxt["low"]))
        except (TypeError, ValueError):
            pass
    if _nxt.get("high"):
        try:
            _y_floor.append(float(_nxt["high"]))
        except (TypeError, ValueError):
            pass
    ymin = min(_y_floor) - 520
    ymax = max(highs) + 900
    ax.set_ylim(float(ymin), float(ymax))
    zone = _paint_window_dual_zones(
        ax,
        highs=highs,
        lows=lows,
        vols=vols,
        bars=rows,
        y_now=float(y_now),
        fp=_fp,
        supports=tw_supports,
        resists=tuple(float(v) for v in tip_anchors[:4]) if tip_anchors else (43135.0,),
        skip_label_ys=[float(v) for v in tip_anchors],
        vol_lookback=40,
        vol_sr=c60_vol_sr,
        avoid_top_left_stamp=True,
        pack=pack,
    )
    _xticks, _xlabs, _bounds = _c9_60m_day_boundary_ticks(rows)
    for bi in _bounds[1:]:
        ax.axvline(bi - 0.5, color="#37474f", lw=0.7, ls=":", alpha=0.85, zorder=1.2)
        axv.axvline(bi - 0.5, color="#37474f", lw=0.7, ls=":", alpha=0.85, zorder=1.2)
    # 超近：今開盤→查詢當下每根 60 分白底半透明，一眼看出今天從哪根起
    if kind == "micro":
        _paint_micro_today_session_bg(ax, axv, rows, pack=pack)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
    # 黃＝主大量日；亮桃＝下一層大量日（與遠／近豎導同色）
    _i_pri = zone.get("i_vmax")
    _i_nxt = (c60_vol_sr or {}).get("i_next")
    _i_nxt2 = (c60_vol_sr or {}).get("i_next_2nd")
    _paint_vol_sr_mark_on_axis(
        ax,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        i_primary=_i_pri,
        i_next=_i_nxt,
        fp=_fp,
        date_primary=str(((c60_vol_sr or {}).get("primary") or {}).get("date") or ""),
        date_next=str(((c60_vol_sr or {}).get("next") or {}).get("date") or ""),
    )
    _paint_vol_sr_day_guides(axv, i_primary=_i_pri, i_next=_i_nxt)
    # 量柱抓本層最大量＋下一層最大量／次大量
    _paint_teach_vol_layer_bars(
        axv,
        vols,
        i_primary=_i_pri,
        i_next=_i_nxt,
        i_next_2nd=_i_nxt2,
        bars=rows,
        fp=_fp,
    )
    # 黃培碩 60 分：底色跟轉折價對齊＋藍(1)(2)(3)／紅反彈折線（對他手繪）
    painted = _paint_huang_c60_structure(ax, rows, fp=_fp, pack=pack)
    if not painted:
        # 錨對不上才退回日界色帶（仍不准假折線）
        _paint_c3_vs_41760_legend(ax, fp=_fp, pack=pack)
        _paint_c3_group12_span_labels(
            ax, rows, fp=_fp, pack=pack, lows=lows, highs=highs
        )
    else:
        # 說明放標題列下方（figure），不准進主圖壓 K／折線／虛線
        _paint_wave_draw_howto(
            fig,
            fp=_fp,
            y=0.922,
            text=(
                "浪線怎麼畫：底色分C1–C4｜粗藍折＝大段高低連（C1→C2→C3底→C4高）｜"
                "細白＝該段碎浪（C3①～⑤；C4不標浪號）｜黃帶＝現在撐壓｜非買訊"
            ),
        )
    right_notes: List[Dict[str, Any]] = [
        {
            "x": int(i_now),
            "y": float(y_now),
            "text": f"今 {_px(y_now)}",
            "color": "#ea80fc",
        },
    ]
    tip_skip = {round(float(y_now), 1), 43135.0, round(43135.0, 1)}
    # 當令已有回測區間：舊單點 41500 不准再進右欄（後文壓前文）
    _rb_skip = _retest_avg_min_from_pack(pack)
    if _rb_skip is not None and abs(
        float(_rb_skip["avg"]) - float(_rb_skip["min"])
    ) >= 0.6:
        tip_skip.add(41500.0)
        tip_skip.add(round(41500.0, 1))
    # 43135＝次級4壓：結構線上已有標，右欄不准再貼同價
    for anch in tip_anchors:
        if (
            round(float(anch), 1) in tip_skip
            or abs(float(anch) - 43135.0) < 0.6
            or (
                _rb_skip is not None
                and abs(float(_rb_skip["avg"]) - float(_rb_skip["min"])) >= 0.6
                and abs(float(anch) - 41500.0) < 0.6
            )
        ):
            tip_skip.add(round(float(anch), 1))
            continue
        right_notes.append(
            {
                "x": n - 1,
                "y": float(anch),
                "text": _format_tw_pred_note(
                    float(anch), pack=pack, lows=lows, highs=highs
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack, n=n, lows=lows, tip_skip=tip_skip, bars=rows, highs=highs
        )
    )
    ax.set_ylim(float(ymin), float(ymax))
    # 右欄左緣對齊使用者紅框左緣（末K右側空帶），水平虛線接真價；不准壓K／浪折
    x_col = float(n) + 8.8
    _place_live_right_labels(
        ax,
        right_notes,
        n=n,
        ymin=float(ymin),
        ymax=float(ymax),
        fp=_fp,
        level_dash=True,
        min_gap=(float(ymax) - float(ymin)) * 0.062,
        x_col=x_col,
        nudge=True,
        fontsize=8.5,
    )
    # 末根蓋回＋今 tip：Y 鎖收盤（紅柱上緣／綠柱下緣）；不准被浪折蓋掉
    _finish_last_twii_candle(
        ax,
        i_now=int(i_now),
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_body_up_taiwan,
        ymin=float(ymin),
        ymax=float(ymax),
    )
    # 預估虛線：對準當令「回測平均」（區間中點／單點）；無則退回最低；再示意新五波升
    _rb_live = _retest_avg_min_from_pack(pack)
    if _rb_live is not None:
        _retest_y = float(_rb_live["avg"])
    else:
        _retest_y = 41500.0
        try:
            for _a in tip_anchors:
                if abs(float(_a) - 41500.0) < 0.6:
                    _retest_y = float(_a)
                    break
        except (TypeError, ValueError):
            _retest_y = 41500.0
    _path = _paint_micro_retest_then_rise_schematic(
        ax,
        i_now=int(i_now),
        y_now=float(y_now),
        retest_y=float(_retest_y),
        fp=_fp,
        n=int(n),
        x_label_col=float(x_col),
    )
    # 虛線端若低於現 ylim，抬一截；上折示意也要進框
    try:
        _ymin0, _ymax0 = ax.get_ylim()
        _need_lo = min(float(_retest_y), float(y_now)) - 420.0
        _need_hi = max(float(_path.get("fut_y") or y_now), float(y_now)) + 520.0
        ax.set_ylim(min(float(_ymin0), _need_lo), max(float(_ymax0), _need_hi))
        ymin, ymax = ax.get_ylim()
    except Exception:
        pass
    x_right = _teach_xlim_right(
        int(n),
        tip_xlim=max(float(tip.get("fut_x") or n), float(_path.get("fut_x") or n))
        + 1.6,
        right_col=float(x_col),
        # 右側空帶要裝得下右欄標（x_col≈n+8.8）；不准再負 extra 把標擠回K線上
        extra=4.6,
    )
    # 左緣貼 C 起，不准再留大B空位
    ax.set_xlim(-0.35, x_right)
    axv.set_xlim(-0.35, x_right)
    # ylim 已由 _paint_teach_vol_layer_bars 留上緣空帶；無標時才備援
    if axv.get_ylim()[1] <= (max(vols) if any(vols) else 1) * 1.01:
        axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel(
        "量(0050)" if vol_proxy else "量",
        fontproperties=_fp(10, "bold"),
        color=_LIVE_MUTED,
    )
    if len(_xticks) > 14:
        keep = list(range(0, len(_xticks) - 1, 2)) + [len(_xticks) - 1]
        _xticks = [_xticks[i] for i in keep]
        _xlabs = [_xlabs[i] for i in keep]
    axv.set_xticks(_xticks)
    axv.set_xticklabels(_xlabs, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    plt.setp(ax.get_xticklabels(), visible=False)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    which = "近窗" if kind == "near" else "超近窗"
    fig.text(
        0.03,
        0.972,
        f"{which}・60分C波（定長滾・最新K｜不含大B）｜C1–C4映60分｜非買訊",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    vol_note = "｜量＝0050同ts代理（加權指數無成交量）" if vol_proxy else ""
    fig.text(
        0.03,
        0.945,
        "軸＝加權日盤60分｜藍(1)(2)(3)+C3內①～⑤｜C2上下虛框｜C4白細折｜次級4壓≈43135"
        + vol_note,
        fontproperties=_fp(9, "bold"),
        color="#ce93d8",
        ha="left",
        va="top",
    )
    fig.subplots_adjust(left=0.05, right=0.98, top=0.90, bottom=0.07)
    stamp_bars: Sequence[Dict[str, Any]] = rows
    stamp_close = closes[-1]
    if daily:
        d_last = _ymd(daily[-1].get("date"))
        r_last = _ymd(rows[-1].get("date"))
        if d_last and (not r_last or d_last >= r_last):
            stamp_bars = daily
            try:
                stamp_close = float(daily[-1].get("close") or closes[-1])
            except (TypeError, ValueError):
                stamp_close = closes[-1]
    _paint_teach_query_stamp(
        fig,
        stamp_bars,
        pack=pack,
        close=stamp_close,
        fp=_fp,
        x=0.02,
        y=0.96,
        ha="left",
        va="top",
        ax=ax,
        db_path=db_path,
    )
    # 八浪縮圖：量欄左側空帶（紅框區）＋黃框標此刻＝大C（內＝C4進行中）
    _micro_ins = _eight_wave_inset_rect_on_vol(axv, fig, scale=0.95, left_frac=0.05)
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_eight_wave_now_key(pack) or "C",
        detail=True,
        rect=_micro_ins,
        title="八浪・對位",
        now_tip="此刻＝大C｜內＝C4進行中",
    )
    try:
        fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight", pad_inches=0.22)
    except Exception:
        try:
            plt.close(fig)
        except Exception:
            pass
        return ""
    plt.close(fig)
    pack["near_tf" if kind == "near" else "micro_tf"] = "twii60_c"
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_live_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """教具②近窗特寫：⑤→A↓→B↑→C↓＋Fib／1-4（不懂浪也能跟折數）。

    遠窗另張；外圍費半／納指另張。位階＝預估・會動態修正。
    """
    pack = _ensure_teach_pack_preds(db_path, pack)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_body_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    bars_full = _twii_bars_for_teach(db_path, 220, pack)
    if len(bars_full) < 16 or not save_path:
        return ""
    # 大量撐壓／下一層＝結構圖同一套（先在完整柱算，再切片畫黃／灰帶）
    near_vol_sr = _resolve_teach_vol_sr(bars_full, lookback=40)
    mac_full = _twii_macro_wave_anchors(bars_full)
    if not mac_full:
        return ""
    # 近窗＝大結構特寫：⑤起為地板；滿 _NEAR_TEACH_MAX_BARS 後定長滾動（進一根刪最左）
    i_floor = (
        _bar_index_by_ymd(bars_full, "20260401")
        or _bar_index_by_ymd(bars_full, "20260331")
        or _bar_index_by_ymd(bars_full, "20260325")
        or 0
    )
    bars = _teach_roll_from_floor(
        bars_full, floor_i=int(i_floor), max_bars=_NEAR_TEACH_MAX_BARS
    )
    near_vol_sr = _remap_teach_vol_sr_index(near_vol_sr, bars)
    mac = _clamp_macro_wave_to_window(mac_full, bars)
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

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(15.6, 9.8),
        dpi=NAV_CHART_DPI,
        sharex=True,
        # 欄間薄一截：結構日單行；量底只留疏刻
        gridspec_kw=dict(height_ratios=(5.5, 1.35), hspace=0.10),
    )
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    tw_supports = _tw_support_ladder(pack)
    tip_anchors = _tw_tip_anchors(pack)
    # 上下多留：⑤起／大A 低點浪名要離 x 軸；頂上再加一截給白底戳（主圖框內左上）
    ymin = min([min(lows), y5s, y_alow] + list(tw_supports)) - 780
    ymax = max(highs) + 1180
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
    # 與遠窗同一套雙底色（黃＝大量撐壓、灰＝下一層、青＝飆預測位階帶）
    # 白底戳改主圖左上 → 頂部價標右移避讓
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
        vol_lookback=40,
        vol_sr=near_vol_sr,
        avoid_top_left_stamp=True,
        pack=pack,
    )
    # 區帶兩標改到九波縮圖定位後再畫（與遠窗同一套：齊頭＋不被縮圖裁字）
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
    i_vmax = zone.get("i_vmax")
    _near_paint_sr = zone.get("vol_sr") if isinstance(zone.get("vol_sr"), dict) else near_vol_sr
    _near_i_nxt = None
    if isinstance(_near_paint_sr, dict):
        _near_i_nxt = _near_paint_sr.get("i_next")
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
    # 跟超近／遠窗同規：黃＝本層、藍＝下一層豎導＋量柱短標
    _paint_vol_sr_day_guides(axv, i_primary=i_vmax, i_next=_near_i_nxt)
    _paint_vol_sr_mark_on_axis(
        ax,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        i_primary=i_vmax,
        i_next=_near_i_nxt,
        fp=_fp,
        date_primary=_ymd(((_near_paint_sr or {}).get("primary") or {}).get("date")),
        date_next=_ymd(((_near_paint_sr or {}).get("next") or {}).get("date")),
    )
    _paint_teach_vol_layer_bars(
        axv,
        vols,
        i_primary=i_vmax,
        i_next=_near_i_nxt,
        i_next_2nd=(_near_paint_sr or {}).get("i_next_2nd")
        if isinstance(_near_paint_sr, dict)
        else None,
        bars=bars,
        fp=_fp,
    )
    # 近窗亦不加權浪段大底色（⑤／A／B／C axvspan）：與遠窗同一套，只留折線，
    # 免跟 C1–C4／黃白大量帶疊成「分布區域亂」。
    ax.plot([i5s, i5e], [y5s, y5e], color="#40c4ff", lw=2.5, zorder=7)  # 推進⑤
    ax.plot([i5e, i_alow], [y5e, y_alow], color="#ff8a80", lw=2.5, zorder=7)  # 大A
    ax.plot(
        [i_alow, i_b_end],
        [y_alow, y_b_end],
        color="#ffd54f",
        lw=2.7,
        ls=(0, (8, 2.4)),
        zorder=7,
    )  # 大B
    c_seg_lows = list(lows[i_c : i_now + 1]) or list(lows[i_b_end:])
    _c9_near_now = _c9_extension_active(pack)
    _c9_pivots_near = (
        _c9_ext_bar_pivots(
            highs, lows, closes, i_bhi=int(i_b_end), i_now=int(i_now)
        )
        if _c9_near_now
        else []
    )
    _c9_near_fade = _c9_near_now and len(_c9_pivots_near) >= 3
    # 大C 紫折：跟 C1–C4 底色四段對齊；缺錨才退回舊兩段
    _c_spans_near = _resolve_huang_c_daily_spans(bars, lows=lows, highs=highs)
    if not _paint_huang_c_degree_path(ax, _c_spans_near, fade=_c9_near_fade):
        ax.plot(
            [i_b_end, i_c, i_now],
            [y_b_end, float(closes[i_c]), y_now],
            color="#ea80fc",
            lw=1.2 if _c9_near_fade else 2.45,
            alpha=0.28 if _c9_near_fade else 1.0,
            zorder=5.5 if _c9_near_fade else 7,
            solid_capstyle="round",
            solid_joinstyle="round",
        )  # 大C（有分色折線時改淡底）
    # 段中短標：⑤／A／B／C 對色線（怎麼畫＝尖點連尖點）
    _paint_macro_wave_seg_tags(
        ax,
        i5s=int(i5s),
        i5e=int(i5e),
        i_alow=int(i_alow),
        i_b_end=int(i_b_end),
        i_now=int(i_now),
        y5s=float(y5s),
        y5e=float(y5e),
        y_alow=float(y_alow),
        y_b_end=float(y_b_end),
        y_now=float(y_now),
        fp=_fp,
        span_y=float(max(ymax - ymin, 1.0)),
    )
    c_sub = _c_subwave_anchors_vs_biaoke60(
        highs, lows, bars, i_c=i_c, i_now=i_now
    )
    # 預估紫／暗虛線＋端點矛圈已刪（使用者 2026-11-11 圈選）；tip 仍算給 xlim／右欄
    tip = _paint_c_forecast(
        ax,
        i_now=i_now,
        y_now=y_now,
        y_ref=y_b_end,
        lows=c_seg_lows,
        fp=_fp,
        n=n,
        keep_left_of_right=True,
        show_label=False,
        anchors=tip_anchors,
        draw=False,
    )
    # 紫虛細 c4→c5 線＋兩端點已刪；今矛圈也不再疊（與預估端點成兩紫點）
    for ii, yy, col in (
        (i5s, y5s, "#40c4ff"),
        (i5e, y5e, "#40c4ff"),
        (i_alow, y_alow, "#ff8a80"),
        (i_b_end, y_b_end, "#ffd54f"),
    ):
        _spear_ring(ax, ii, yy, color=col, zorder=8, hot=True)
    span = max(ymax - ymin, 1.0)
    ax.axvline(i_c, color="#ea80fc", lw=0.95, ls=(0, (2, 2)), alpha=0.8, zorder=5)
    # 先定 ylim／xlim 再釘浪名：右欄固定 pad；尖點跟 K 走
    ax.set_xlim(
        -0.6,
        _teach_xlim_right(
            int(n),
            tip_xlim=float(tip.get("xlim_right") or n) + 2.0,
            right_col=float(n) + float(_TEACH_RIGHT_GUTTER),
        ),
    )
    ax.set_ylim(ymin, ymax)
    # 禁區先登記：左上白底戳（加寬）＋右上價空＋左下九波帶
    _reserve_avoid_zone(
        ax, -1.0, float(ymax) - span * 0.28, float(n) * 0.42, float(ymax) + 80.0
    )
    _reserve_avoid_zone(ax, float(n) - 24.0, 40500.0, float(n) + 5.0, 43300.0)
    _reserve_avoid_zone(ax, float(n) * 0.55, 31800.0, float(n) - 0.5, 39200.0)
    # 下週底／AI結束大標稍後才畫，先佔禁區：尖點浪名不准坐進未來黃／紫框
    try:
        _wb_early = _tw_active_low_zone(pack)
        if _wb_early and _wb_early[2] == "week_bot":
            _elo, _ehi = float(_wb_early[0]), float(_wb_early[1])
            _ey = (_elo + _ehi) * 0.5
            _reserve_avoid_zone(
                ax,
                float(n) * 0.12,
                _ey - max((_ehi - _elo) * 0.42, span * 0.045),
                float(n) * 0.52,
                _ey + max((_ehi - _elo) * 0.42, span * 0.045),
            )
        _ai_early = _tw_ai_end_zone(pack)
        if _ai_early:
            _alo, _ahi = float(_ai_early[0]), float(_ai_early[1])
            _ay = _alo + (_ahi - _alo) * 0.28
            _reserve_avoid_zone(
                ax,
                float(n) * 0.12,
                _ay - max((_ahi - _alo) * 0.30, span * 0.035),
                float(n) * 0.52,
                _ay + max((_ahi - _alo) * 0.30, span * 0.035),
            )
    except Exception:
        pass
    # ⑤起：尖點右上空檔（附圖二）— 九波已遷量欄，這裡只讓過首根K
    _w5_lab = f"⑤起 {_md(bars[i5s].get('date'))}"
    _w5_x = float(i5s) + 7.5
    _w5_y = float(y5s) + span * 0.105
    ax.text(
        _w5_x,
        _w5_y,
        _w5_lab,
        fontproperties=_fp(9, "normal"),
        color="#40c4ff",
        ha="left",
        va="bottom",
        zorder=10,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.08",
            fc="#0b0f14",
            ec="#40c4ff",
            lw=0.45,
            alpha=0.88,
        ),
    )
    seats = getattr(ax, "_wayne_pin_seats", None)
    if seats is None:
        ax._wayne_pin_seats = []
        seats = ax._wayne_pin_seats
    seats.append((_w5_x, _w5_y))
    # ⑤末：尖點右下方空檔（附圖一）— 讓過左上白底戳＋峰後縮圖K
    _w5e_lab = f"⑤末＝A起 {_md(bars[i5e].get('date'))}"
    _w5e_x = float(i5e) + 7.0
    _w5e_y = float(y5e) - span * 0.028
    ax.text(
        _w5e_x,
        _w5e_y,
        _w5e_lab,
        fontproperties=_fp(9, "normal"),
        color="#40c4ff",
        ha="left",
        va="top",
        zorder=10,
        clip_on=False,
        bbox=dict(
            boxstyle="round,pad=0.08",
            fc="#0b0f14",
            ec="#40c4ff",
            lw=0.45,
            alpha=0.88,
        ),
    )
    seats.append((_w5e_x, _w5e_y))
    _pin_pivot_name(
        ax,
        i_alow,
        y_alow,
        f"大A末＝B起 {_md(bars[i_alow].get('date'))}",
        "#ff8a80",
        _fp,
        side="left",  # 左側離開區帶黃標
        tip="high",  # 整盒在尖點上方；tip=low 會鑽進下週底黃框
        n=n,
        pad_x=1.05,
        fontsize=9,
        pri=12,
        clear_dy=max(span * 0.062, 380.0),
        zorder=13,  # 高於區帶大標(12)，轉折字不准被黃框蓋
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
    if not _paint_c9_extension_on_bars(
        ax,
        pack=pack,
        i_now=i_now,
        y_now=y_now,
        n=n,
        fp=_fp,
        tip=tip,
        pin_now=True,
        side="left",  # 與遠窗同一套：浪號靠左，右欄留給價標
        fontsize=9,
        pivots=_c9_pivots_near,
    ):
        # 浪名靠左：右欄已有「大C今＋價」，靠右會壓住「中」國字
        _pin_pivot_name(
            ax,
            i_now,
            y_now,
            "C進行中",
            "#ea80fc",
            _fp,
            side="left",
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
    # 9波擴延：右欄跟遠窗同一套精簡（大B末／此刻）；⑤起終／大A 已有圖上釘點
    if _c9_near_now:
        right_notes = [
            {
                "x": i_b_end,
                "y": y_b_end,
                "text": f"大B末 {_px(y_b_end)}",
                "color": "#ffd54f",
            },
            {
                "x": i_now,
                "y": y_now,
                "text": f"{_c9_now_step_label()}今 {_px(y_now)}",
                "color": "#ea80fc",
            },
        ]
    else:
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
            {
                "x": i_now,
                "y": y_now,
                "text": f"大C今 {_px(y_now)}",
                "color": "#ea80fc",
            },
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
    _near_highs = list(highs[i_c : i_now + 1]) if highs else []
    if tip_anchor is not None and bool(c_sub.get("ok")):
        right_notes.append(
            {
                "x": 0,
                "y": float(tip_anchor),
                "text": _format_tw_pred_note(
                    float(tip_anchor),
                    pack=pack,
                    lows=c_seg_lows,
                    highs=_near_highs or highs,
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
                "text": _format_tw_pred_note(
                    float(anch),
                    pack=pack,
                    lows=c_seg_lows,
                    highs=_near_highs or highs,
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack,
            n=n,
            lows=c_seg_lows,
            tip_skip=tip_skip,
            bars=bars,
            highs=_near_highs or highs,
        )
    )
    # 落在黃帶內的青標改右欄；雙軌／C9／下週底當令＝跟遠窗日盤：不准再加青撐壓擠掉買點
    have_ys = {round(float(n0["y"]), 1) for n0 in right_notes} | tip_skip
    _wb_zone = _tw_active_low_zone(pack)
    _wb_edges = (
        {round(float(_wb_zone[0]), 1), round(float(_wb_zone[1]), 1)}
        if _wb_zone and _wb_zone[2] == "week_bot"
        else set()
    )
    _skip_cyan_sr = bool(_c9_near_now) or bool(_wb_edges)
    if not _skip_cyan_sr:
        for key, col in (("resist", "#4dd0e1"), ("support", "#4dd0e1")):
            yv = sr_skip.get(key)
            if yv is None:
                continue
            if round(float(yv), 1) in have_ys:
                continue
            if round(float(yv), 1) in _wb_edges:
                continue
            # 台指壓41760：已有角色標就不准再貼青「飆預測」
            if (
                _tw_level_role(pack, float(yv)) == "台指壓力"
                or abs(float(yv) - 41760.0) < 0.6
            ):
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
    # 右欄現況：固定 gutter；尖點浪名另走 _pin_pivot_name 跟 K 移
    try:
        _tip_fx = float(tip.get("fut_x") or n)
    except (TypeError, ValueError):
        _tip_fx = float(n)
    x_near_col = _teach_right_col_x(int(n), tip_fut_x=_tip_fx)
    # C9／雙軌：間距跟遠窗日盤同一套，標＋虛線才對得起來
    _place_live_right_labels(
        ax,
        right_notes,
        n=n,
        ymin=ymin,
        ymax=ymax,
        fp=_fp,
        level_dash=True,
        min_gap=(ymax - ymin) * (0.092 if _c9_near_now else 0.068),
        x_col=x_near_col,
        nudge=True,
        fontsize=8.5 if _c9_near_now else 9.0,
    )
    _finish_last_twii_candle(
        ax,
        i_now=i_now,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_body_up_taiwan,
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
    # 附圖五：sharex 會讓兩欄 tick 字互蓋 → 結構日改畫進價／量欄間空檔；
    # 量底只留更疏刻，不准整排壓迫
    major_ymds = {
        "20260401",
        "20260623",
        "20260729",
        "20261006",
        "20261015",
        _ymd(bars[-1].get("date")),
    }
    major_idx = {int(i5s), int(i5e), int(i_alow), int(i_b_end), int(i_now)}
    if i_vmax is not None:
        major_idx.add(int(i_vmax))
    t_all: List[int] = []
    labs_ax: List[str] = []
    labs_axv: List[str] = []
    for i, r in enumerate(bars):
        d = _ymd(r.get("date"))
        is_major = i in major_idx or d in major_ymds
        is_sparse = (i % 20 == 0) and not is_major
        if not (is_major or is_sparse):
            continue
        if i in t_all:
            continue
        t_all.append(i)
        md = _md(d)
        if is_major:
            labs_ax.append(md)
            labs_axv.append("")
        else:
            labs_ax.append("")
            labs_axv.append(md)
    t_ax, l_ax = _sparse_xticks(
        [t for t, lab in zip(t_all, labs_ax) if lab],
        [lab for lab in labs_ax if lab],
        min_gap=6,
    )
    t_av, l_av = _sparse_xticks(
        [t for t, lab in zip(t_all, labs_axv) if lab],
        [lab for lab in labs_axv if lab],
        min_gap=22,
    )
    t_merged = sorted(set(t_ax) | set(t_av))
    lab_av_map = dict(zip(t_av, l_av))
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.4)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)
    ax.set_xticks(t_merged)
    ax.set_xticklabels([])
    ax.tick_params(axis="x", labelbottom=False, length=2, pad=1)
    axv.set_xticks(t_merged)
    axv.set_xticklabels(
        [lab_av_map.get(t, "") for t in t_merged],
        fontproperties=_fp(8, "bold"),
        color=_LIVE_MUTED,
    )
    axv.tick_params(axis="x", labelbottom=True, length=3, pad=2)
    if t_merged:
        _paint_axis_last_date_neon(
            axv,
            last_i=int(t_merged[-1]),
            live=_twii_cash_session_live(_query_now_from_pack(pack)),
            fp=_fp,
        )
    # 結構日：subplots_adjust 後用 fig 座標釘在價／量欄間空檔（附圖五上紅框）
    _near_major_date_labs = list(zip(t_ax, l_ax))
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)
    as_of = _ymd(bars[-1].get("date"))
    ladder = _wave_now_ladder(pack)
    # 標題跟當日層級走：一眼看到大→小走到哪；雙底色與遠窗對齊
    title_bit = str(ladder.get("now") or "").strip() or "現在在C（預估）"
    if title_bit in ("C-7轉C-8", "C-7走完→C-8", "C-8", "C-7", "C-9") or "9波擴延" in str(
        ladder.get("chain") or ""
    ):
        title_bit = f"{_c9_now_step_label()}→C-9"
    elif len(title_bit) > 22:
        title_bit = title_bit[:21] + "…"
    vz_y = _teach_vol_sr_title_bit(
        zone.get("vol_sr") or near_vol_sr,
        bars=bars,
        highs=highs,
        lows=lows,
        i_vmax=i_vmax,
    )
    vz_c = _teach_cyan_band_title_bit(sr, pack=pack)
    c_sub_bit = ""
    if c_sub.get("ok"):
        c_sub_bit = f"｜細c4 {_px(c_sub['y_c4'])}／c5 {_px(c_sub['y_c5'])}"
    fig.text(
        0.03,
        0.972,
        f"第2張（近窗）：此刻＝{title_bit}　｜　{vz_y}　｜　{vz_c}{c_sub_bit}",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.945,
        f"{str(ladder.get('one_line') or '他說現在：C進行中')[:40]}｜"
        f"{_macro_wave_calendar_line()}｜細＝C內c4／c5｜C走完≠新五波升",
        fontproperties=_fp(9, "bold"),
        color="#ce93d8",
        ha="left",
        va="top",
    )
    _paint_wave_draw_howto(
        fig,
        fp=_fp,
        y=0.918,
        text="浪線怎麼畫：尖點對尖點連直線｜藍⑤→粉A→金虛B→紫C（只連官方柱高低）｜非買訊",
    )
    # 近窗白底戳：跟遠窗同一套鎖主圖 axes 框內左上（不准出框、不准擋九波／縮圖K）
    fig.subplots_adjust(left=0.05, right=0.98, top=0.90, bottom=0.07)
    _stamp_ax_x, _stamp_ax_y = 0.02, 0.96
    _paint_teach_query_stamp(
        fig,
        bars,
        pack=pack,
        close=closes[-1],
        fp=_fp,
        x=_stamp_ax_x,
        y=_stamp_ax_y,
        ha="left",
        va="top",
        ax=ax,
        db_path=db_path,
    )
    _paint_c3_vs_41760_legend(ax, fp=_fp, pack=pack)
    _paint_c3_group12_span_labels(
        ax, bars, fp=_fp, pack=pack, lows=lows, highs=highs
    )
    # 跨度標之後再蓋回縮圖K＋量：基本K永遠可見
    _paint_live_candles(
        ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan
    )
    _finish_last_twii_candle(
        ax,
        i_now=int(i_now),
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        candle_up=candle_body_up_taiwan,
        ymin=float(ax.get_ylim()[0]),
        ymax=float(ax.get_ylim()[1]),
    )
    # 單行腳：不准雙行疊字蓋數字
    intent_foot = str(pack.get("intent_note") or pack.get("vol_note") or "")
    intent_one = intent_foot.split("；")[0] if intent_foot else ""
    foot_one = teach[:110]
    if intent_one:
        foot_one = f"{foot_one}｜量價：{intent_one}"[:160]
    fig.text(
        0.03,
        0.012,
        foot_one,
        fontproperties=_fp(9, "bold"),
        color=_LIVE_MUTED,
        ha="left",
        va="bottom",
    )
    _axpos = ax.get_position()
    _axvpos = axv.get_position()
    # 結構日：欄間單行、字級略大；不准上下排拉高空檔
    try:
        _gap_y = (float(_axpos.y0) + float(_axvpos.y1)) * 0.5
        for _ti, _lab in _near_major_date_labs:
            _fx, _fy = _fig_xy_from_axes_data(ax, fig, float(_ti), float(ymin))
            fig.text(
                float(_fx),
                float(_gap_y),
                _lab,
                fontproperties=_fp(9.5, "bold"),
                color=_LIVE_TEXT,
                ha="center",
                va="center",
                clip_on=False,
                zorder=20,
            )
    except Exception:
        pass
    # 近窗九波：靠右下讓位給左半區帶兩標（齊頭）；底緣仍貼價欄下框
    try:
        _iw0, _ih0 = _teach_eight_wave_inset_wh(fig)
        _sc = 0.58
        _iw = min(float(_iw0) * _sc, float(_axpos.width) * 0.30)
        _ih = min(float(_ih0) * _sc, float(_axpos.height) * 0.24)
        # 右緣留右欄；左緣須 > 區帶標右緣（fallback 0.10 + 約 0.30 寬）
        _left = float(_axpos.x0) + float(_axpos.width) * 0.55
        _max_right = float(_axpos.x0) + float(_axpos.width) * 0.92
        if _left + _iw > _max_right:
            _left = max(float(_axpos.x0) + float(_axpos.width) * 0.48, _max_right - _iw)
        # 下面那條框線＝價欄底緣；底邊貼齊不准再往下
        _bot = float(_axpos.y0)
        _, _fy_cap = _fig_xy_from_axes_data(ax, fig, float(i5s) + 28.0, 35500.0)
        _max_top = float(_fy_cap) - 0.012
        if _bot + _ih > _max_top:
            _fit = max(0.40, (_max_top - _bot) / max(_ih, 1e-6))
            _iw *= _fit
            _ih *= _fit
        _near_inset = (_left, _bot, float(_iw), float(_ih))
    except Exception:
        _near_inset = _eight_wave_inset_rect_left_of_vmax(
            ax,
            fig,
            i_vmax=int(i_vmax) if i_vmax is not None else None,
            ymin=float(ymin),
            ymax=float(ymax),
            n_bars=n,
            scale=0.62,
            pin_bottom=True,
        )
    _c9_near = _c9_extension_active(pack)
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_eight_wave_now_key(pack),
        detail=False,  # 與遠窗同：細線九段，手機縮圖才不糊
        rect=_near_inset,
        title="九波擴延" if _c9_near else "八浪",
        c9_ext=_c9_near,
        flash_pivots=_c9_pivots_near if _c9_near else None,
    )
    # 近窗：兩標齊頭；清過九波縮圖，且右挪離開大A末／7/29（區帶後畫會蓋尖點）
    _zx_n = _zone_label_x_clear_of_inset(
        ax, fig, _near_inset, fallback=float(_TEACH_ZONE_LABEL_X_NEAR)
    )
    try:
        _x0, _x1 = ax.get_xlim()
        _xspan = max(float(_x1) - float(_x0), 1e-9)
        _piv_ax = (float(i_alow) - float(_x0)) / _xspan
        # 尖點改在上方後，黃標仍須水平離開 A末 盒（長標往右長）
        if float(_zx_n) < float(_piv_ax) + 0.22:
            _zx_n = float(_piv_ax) + 0.26
        # 長標右緣不准撞縮圖／右欄；塞不下就退回縮圖左側可放的最大 x
        if _near_inset:
            _pos = ax.get_position()
            _pw = max(float(_pos.width), 1e-9)
            _ins_l = float(_near_inset[0])
            _inset_left_ax = (_ins_l - float(_pos.x0)) / _pw
            _max_zx = float(_inset_left_ax) - float(_TEACH_ZONE_LABEL_W_AX) - 0.03
            if _max_zx >= 0.08:
                _zx_n = min(float(_zx_n), float(_max_zx))
        _zx_n = max(0.08, min(0.50, float(_zx_n)))
    except Exception:
        pass
    _paint_c9_low_zone_band(ax, pack, fp=_fp, label_x=_zx_n)
    _paint_ai_end_zone_band(ax, pack, fp=_fp, label_x=_zx_n)
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_super_near_c9_60m(
    db_path: str, save_path: str, pack: Dict[str, Any]
) -> str:
    """超近窗・9波擴延專用：加權日盤 60 分 K（10/6→最新日盤收）釘 C1…C8。

    上＝60分分色浪；左下＝說明＋日K；右下＝九波圓標；黃框＝最新官方日／60收。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_body_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp
    except Exception:
        return ""
    if not save_path:
        return ""
    # 補齊最新 60 分，避免黃框停在昨日
    try:
        from kline_hop import fetch_yahoo_minutes

        fetch_yahoo_minutes("TWII", "60", db_path)
        fetch_yahoo_minutes("0050", "60", db_path)
    except Exception:
        pass
    rows = _load_twii60_day_rows(db_path, since_ymd="20261006")
    if len(rows) < 24:
        return ""
    daily_all = _twii_bars_for_teach(db_path, 80, pack) or []
    daily = [b for b in daily_all if _ymd(b.get("date")) >= "20261006"]
    if len(daily) < 8:
        daily = daily_all[-40:]
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    n = len(rows)
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r["volume"]) for r in rows]
    i_b = max(range(min(12, n)), key=lambda i: float(highs[i]))
    for i, r in enumerate(rows):
        if str(r.get("date") or "") == "20261006" and float(highs[i]) >= float(highs[i_b]):
            i_b = i
    i_now = n - 1
    y_b = float(highs[i_b])
    y_now = float(closes[i_now])
    pivots = _c9_ext_bar_pivots(
        highs, lows, closes, i_bhi=i_b, i_now=i_now, tf="60"
    )
    tip_anchors = _tw_tip_anchors(pack)
    _zone_lo_hi = _tw_active_low_zone(pack)
    _tip_fallback = (
        (float(_zone_lo_hi[1]), float(_zone_lo_hi[0]))
        if _zone_lo_hi
        else (37300.0, 35500.0)
    )
    tip = _c_forecast_tip(
        i_now=i_now,
        y_now=y_now,
        y_ref=y_b,
        lows=lows[i_b : i_now + 1] or lows,
        anchors=tip_anchors or _tip_fallback,
    )

    # 上＝60分K｜中＝量｜日期長條｜下＝左日K滿格＋右九波
    fig = plt.figure(figsize=(15.8, 12.2), dpi=NAV_CHART_DPI)
    _gs = fig.add_gridspec(
        4,
        2,
        height_ratios=(4.85, 0.95, 0.38, 3.15),
        width_ratios=(1.22, 1.0),
        hspace=0.08,
        wspace=0.06,
    )
    ax = fig.add_subplot(_gs[0, :])
    axv = fig.add_subplot(_gs[1, :], sharex=ax)
    ax_date = fig.add_subplot(_gs[2, :], sharex=ax)
    ax_daily = fig.add_subplot(_gs[3, 0])
    ax_wave_host = fig.add_subplot(_gs[3, 1])
    fig.patch.set_facecolor(_LIVE_BG)
    _style_live_ax(ax, axv)
    ax_date.set_facecolor("#0b0f14")
    for _sp in ax_date.spines.values():
        _sp.set_color("#546e7a")
        _sp.set_linewidth(0.9)
    ax_date.set_yticks([])
    ax_date.tick_params(left=False, labelleft=False)
    ax_wave_host.set_facecolor("#0b0f14")
    for _sp in ax_wave_host.spines.values():
        _sp.set_color("#546e7a")
        _sp.set_linewidth(0.95)
    ax_wave_host.set_xticks([])
    ax_wave_host.set_yticks([])
    ax_wave_host.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

    tw_supports = _tw_support_ladder(pack)
    _floor_y = float(_zone_lo_hi[0]) if _zone_lo_hi else 35500.0
    ymin = min([min(lows)] + list(tw_supports) + [_floor_y]) - 420
    ymax = max(highs) + 720
    _paint_window_dual_zones(
        ax,
        highs=highs,
        lows=lows,
        vols=vols,
        bars=rows,
        y_now=float(y_now),
        fp=_fp,
        supports=tw_supports,
        resists=(47637.0, 48613.0, y_b),
        skip_label_ys=[float(v) for v in tip_anchors],
        vol_lookback=40,
        pack=pack,
    )
    _paint_c9_low_zone_band(ax, pack, fp=_fp, label_x=_TEACH_ZONE_LABEL_X_MICRO)
    # 超近60分：黃標／AI標同欄偏左，齊頭且不准壓末K
    _paint_ai_end_zone_band(ax, pack, fp=_fp, label_x=_TEACH_ZONE_LABEL_X_MICRO)
    # 交易日界線：垂直淡線，對日期
    _xticks, _xlabs, _bounds = _c9_60m_day_boundary_ticks(rows)
    for bi in _bounds[1:]:
        ax.axvline(bi - 0.5, color="#37474f", lw=0.7, ls=":", alpha=0.85, zorder=1.2)
        axv.axvline(bi - 0.5, color="#37474f", lw=0.7, ls=":", alpha=0.85, zorder=1.2)
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
    ax.plot(
        [i_now, float(tip["fut_x"])],
        [y_now, float(tip["fut_y"])],
        color=_c9_wave_color("C9"),
        lw=1.55,
        ls=(0, (4, 2)),
        alpha=0.85,
        zorder=6,
    )
    _paint_c9_extension_on_bars(
        ax,
        pack=pack,
        i_now=i_now,
        y_now=y_now,
        n=n,
        fp=_fp,
        tip=tip,
        pin_now=True,
        side="left",  # 與遠／近窗同一套：浪號靠左，右欄留給價標
        fontsize=9,
        pivots=pivots,
    )
    _pin_pivot_name(
        ax,
        int(i_b),
        float(y_b),
        f"B {_px(y_b)}",
        _c9_wave_color("B"),
        _fp,
        side="left",
        tip="high",
        n=n,
        pad_x=0.35,
        fontsize=10,
    )

    # 右欄跟遠窗同一套精簡：B末／此刻＋預測錨；C1…C8 已釘在 K 上不准再堆
    right_notes: List[Dict[str, Any]] = [
        {
            "x": int(i_b),
            "y": float(y_b),
            "text": f"大B末 {_px(y_b)}",
            "color": "#ffd54f",
        },
        {
            "x": int(i_now),
            "y": float(y_now),
            "text": f"{_c9_now_step_label()}今 {_px(y_now)}",
            "color": "#ea80fc",
        },
    ]
    tip_skip: set = {round(float(y_b), 1), round(float(y_now), 1)}
    tip_anchor = tip.get("anchor_y")
    if tip_anchor is not None and round(float(tip_anchor), 1) not in tip_skip:
        right_notes.append(
            {
                "x": n - 1,
                "y": float(tip_anchor),
                "text": _format_tw_pred_note(
                    float(tip_anchor),
                    pack=pack,
                    lows=lows,
                    highs=highs,
                ),
                "color": "#ea80fc",
            }
        )
        tip_skip.add(round(float(tip_anchor), 1))
    for anch in tip_anchors:
        if round(float(anch), 1) in tip_skip:
            continue
        right_notes.append(
            {
                "x": n - 1,
                "y": float(anch),
                "text": _format_tw_pred_note(
                    float(anch),
                    pack=pack,
                    lows=lows,
                    highs=highs,
                ),
                "color": "#82b1ff",
            }
        )
        tip_skip.add(round(float(anch), 1))
    right_notes.extend(
        _tw_pred_right_notes(
            pack, n=n, lows=lows, tip_skip=tip_skip, bars=rows, highs=highs
        )
    )
    y_bot, y_top = float(ymin), float(ymax)
    ax.set_ylim(y_bot, y_top)
    x_col = float(n) + 1.95
    try:
        x_col = max(x_col, float(tip.get("fut_x") or n) + 0.35)
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
        min_gap=(y_top - y_bot) * 0.062,
        x_col=x_col,
        nudge=True,
        fontsize=8.5,
    )
    x_right = _teach_xlim_right(
        int(n),
        tip_xlim=float(tip.get("fut_x") or n) + 2.2,
        right_col=float(x_col) if x_col is not None else float(n) + float(_TEACH_RIGHT_GUTTER),
        extra=-3.7,  # 中排日K右欄略緊於遠／近
    )
    ax.set_xlim(-0.6, x_right)
    axv.set_xlim(-0.6, x_right)
    ax_date.set_xlim(-0.6, x_right)
    axv.set_ylim(0, (max(vols) if any(vols) else 1) * 1.35)
    axv.set_ylabel("量", fontproperties=_fp(10, "bold"), color=_LIVE_MUTED)

    # 日期長條放中間（量下方、日K上方）；只留日期，不塞說明
    # 過密時隔日顯示，末根必留
    if len(_xticks) > 12:
        keep = list(range(0, len(_xticks) - 1, 2)) + [len(_xticks) - 1]
        _xticks = [_xticks[i] for i in keep]
        _xlabs = [_xlabs[i] for i in keep]
    ax_date.set_xticks(_xticks)
    ax_date.set_xticklabels(_xlabs, fontproperties=_fp(9, "bold"), color=_LIVE_TEXT)
    ax_date.set_ylabel(
        "日", fontproperties=_fp(8, "bold"), color=_LIVE_MUTED, rotation=0, labelpad=8
    )
    ax_date.set_xlabel("")
    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(axv.get_xticklabels(), visible=False)
    for lab in list(ax.get_yticklabels()) + list(axv.get_yticklabels()):
        lab.set_fontproperties(_fp(9, "bold"))
        lab.set_color(_LIVE_MUTED)

    last_ts = str(rows[-1].get("ts") or "")
    last_day = (
        f"{int(last_ts[4:6])}/{int(last_ts[6:8])} {last_ts[8:10]}:{last_ts[10:12]}"
        if len(last_ts) >= 12
        else ""
    )
    # C7 錨時刻（絕對低）方便對上面
    c7_bit = ""
    for ii, yy, lab in pivots:
        if lab == "C7" and 0 <= ii < n:
            ts7 = str(rows[ii].get("ts") or "")
            if len(ts7) >= 12:
                c7_bit = (
                    f"｜C7={int(ts7[4:6])}/{int(ts7[6:8])} "
                    f"{ts7[8:10]}:{ts7[10:12]}低 {_px(yy)}"
                )
            break
    fig.text(
        0.03,
        0.972,
        f"第3張（超近窗・60分）：10/6→日盤收｜{_c9_now_step_label()}→C-9（9波擴延・預估）",
        fontproperties=_fp(12, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.945,
        f"上＝60分分色｜中＝量＋日期長條｜左下＝日K浪線｜右下＝九波｜{last_day}{c7_bit}｜非買訊",
        fontproperties=_fp(9, "bold"),
        color="#ce93d8",
        ha="left",
        va="top",
    )
    fig.subplots_adjust(left=0.05, right=0.98, top=0.90, bottom=0.045)

    stamp_bars: Sequence[Dict[str, Any]] = rows
    stamp_close = closes[-1]
    if daily:
        d_last = _ymd(daily[-1].get("date"))
        r_last = _ymd(rows[-1].get("date"))
        if d_last and (not r_last or d_last >= r_last):
            stamp_bars = daily
            try:
                stamp_close = float(daily[-1].get("close") or closes[-1])
            except (TypeError, ValueError):
                stamp_close = closes[-1]
    _paint_teach_query_stamp(
        fig,
        stamp_bars,
        pack=pack,
        close=stamp_close,
        fp=_fp,
        x=0.995,
        y=0.855,
        db_path=db_path,
    )
    _paint_c3_vs_41760_legend(ax, fp=_fp, pack=pack)
    # 超近60分：用日K欄對組別；60分軸日期可對就畫，對不到就略
    _paint_c3_group12_span_labels(
        ax,
        rows if rows else daily,
        fp=_fp,
        pack=pack,
        lows=lows,
        highs=highs,
    )

    labs_line = " ".join(
        f"{lab}@{_ymd(rows[i].get('date'))[4:6]}/{_ymd(rows[i].get('date'))[6:8]}"
        for i, _y, lab in pivots
        if lab.startswith("C")
    )
    _paint_c9_daily_thumb(
        ax_daily,
        daily,
        pivots_60=pivots,
        rows_60=rows,
        fp=_fp,
        candle_up=candle_body_up_taiwan,
        note="",
    )
    _oral_m = _active_oral_now_line(pack)
    foot_m = _oral_m.replace(" ", "")
    fig.text(
        0.03,
        0.028,
        f"{_oral_m}｜浪序：{labs_line}"[:140],
        fontproperties=_fp(8, "bold"),
        color="#80deea" if _tw_has_foot2_low_zone(pack) else "#ce93d8",
        ha="left",
        va="bottom",
    )
    fig.text(
        0.03,
        0.008,
        f"{foot_m}｜上＝60分K｜中＝量＋日期長條｜左下日K七段分色浪線｜右下九波｜C走完≠新五波升",
        fontproperties=_fp(9, "bold"),
        color=_LIVE_TEXT,
        ha="left",
        va="bottom",
    )
    fig.canvas.draw()
    _pos = ax_wave_host.get_position()
    ax_wave_host.set_visible(False)
    _paint_eight_wave_inset(
        fig,
        fp=_fp,
        now_key=_eight_wave_now_key(pack),
        detail=False,  # 與遠／近窗同：細線九段
        c_flash=False,
        flash_pivots=pivots,
        rect=(float(_pos.x0), float(_pos.y0), float(_pos.width), float(_pos.height)),
        title="九波擴延",
        c9_ext=True,
    )
    fig.savefig(save_path, facecolor=_LIVE_BG, bbox_inches="tight")
    plt.close(fig)
    pack["micro_tf"] = "twii60"
    pack["micro_c9_pivots"] = [
        {"i": int(i), "y": float(y), "lab": str(lab), "ts": str(rows[i].get("ts") or "")}
        for i, y, lab in pivots
    ]
    return save_path if os.path.isfile(save_path) and os.path.getsize(save_path) > 4000 else ""


def _render_twii_super_near_dark(db_path: str, save_path: str, pack: Dict[str, Any]) -> str:
    """超近窗：加權日盤60分・只顯示大C（C1–C4）；前面大B不進軸。"""
    return _render_twii_c_wave_60_dark(db_path, save_path, pack, kind="micro")


def _nearest_finite_axis_idx(
    values: Sequence[float],
    i: int,
    *,
    n: Optional[int] = None,
) -> Optional[int]:
    """軸索引 i 若為 NaN／越界，往右再往左找最近有限值；都沒有回 None。

    用途：費半／電子浪線端點。台股開市美休市對齊時，窗左緣可能是 NaN，
    不准因此整段⑤→A→B→C 浪線消失（板塊與加權K棒位置不准動）。
    """
    import math

    m = int(n) if n is not None else len(values)
    if m <= 0:
        return None
    try:
        i0 = int(i)
    except (TypeError, ValueError):
        return None

    def _ok(j: int) -> bool:
        if not (0 <= j < m and j < len(values)):
            return False
        try:
            v = float(values[j])
        except (TypeError, ValueError):
            return False
        return v == v and math.isfinite(v)

    if _ok(i0):
        return i0
    for d in range(1, m):
        r, l = i0 + d, i0 - d
        if _ok(r):
            return r
        if _ok(l):
            return l
    return None



def _c9_60m_day_boundary_ticks(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[List[int], List[str], List[int]]:
    """60分軸：每個交易日只標一次日期；另回日界線索引（開盤柱）。"""
    ticks: List[int] = []
    labs: List[str] = []
    bounds: List[int] = []
    prev = ""
    n = len(rows)
    for i, r in enumerate(rows):
        ts = str(r.get("ts") or "")
        if len(ts) < 12:
            continue
        day = ts[:8]
        if day != prev:
            bounds.append(i)
            ticks.append(i)
            labs.append(f"{int(ts[4:6])}/{int(ts[6:8])}")
            prev = day
    if n and (not ticks or ticks[-1] != n - 1):
        ts = str(rows[-1].get("ts") or "")
        if len(ts) >= 12:
            ticks.append(n - 1)
            labs.append(f"{int(ts[4:6])}/{int(ts[6:8])} {ts[8:10]}:{ts[10:12]}")
    return ticks, labs, bounds



def _paint_c9_daily_thumb(
    ax: Any,
    daily: Sequence[Dict[str, Any]],
    *,
    pivots_60: Sequence[Tuple[int, float, str]],
    rows_60: Sequence[Dict[str, Any]],
    fp: Any,
    candle_up: Any,
    note: str = "",
) -> None:
    """左下日K：10/6→日收；B→C1…C7 分色浪線對齊上方60分。"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    ax.set_facecolor("#0b0f14")
    for sp in ax.spines.values():
        sp.set_color("#546e7a")
        sp.set_linewidth(0.9)
    if len(daily) < 8:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(
            0.5,
            0.5,
            "日K不足",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=_LIVE_MUTED,
            fontproperties=fp(9, "bold"),
        )
        return
    opens = [float(b["open"]) for b in daily]
    highs = [float(b["high"]) for b in daily]
    lows = [float(b["low"]) for b in daily]
    closes = [float(b["close"]) for b in daily]
    n = len(daily)
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        # 與主圖同規：candle_body_up_taiwan(close, prev_close, open_)；不准 (o,c) 參數顛倒翻色
        prev_c = _prev_valid_close(closes, i, opens=opens)
        up = bool(candle_up(c, prev_c, o))
        col = _LIVE_UP if up else _LIVE_DOWN
        ax.plot([i, i], [l, h], color=col, lw=0.95, solid_capstyle="round", zorder=2)
        body_lo, body_hi = (o, c) if c >= o else (c, o)
        ax.add_patch(
            Rectangle(
                (i - 0.32, body_lo),
                0.64,
                max(0.5, body_hi - body_lo),
                facecolor=col,
                edgecolor=col,
                lw=0.4,
                zorder=3,
            )
        )
    # 60分轉折 → 日K同價錨＋分色浪線（B→C1…C7 共七段；同日兩點微偏X才畫得出下上）
    day_to_i = {_ymd(b.get("date")): i for i, b in enumerate(daily)}
    path: List[Tuple[float, float, str]] = []
    for ii, yy, lab in pivots_60:
        if ii < 0 or ii >= len(rows_60):
            continue
        d = _ymd(rows_60[ii].get("date"))
        di = day_to_i.get(d)
        if di is None:
            continue
        x = float(di)
        if path and abs(path[-1][0] - x) < 0.05:
            # 同日連續轉折：左低／右高微開，避免七段黏成五段
            path[-1] = (path[-1][0] - 0.18, path[-1][1], path[-1][2])
            x = float(di) + 0.18
        path.append((x, float(yy), str(lab)))
    for a, b in zip(path, path[1:]):
        col = _c9_wave_color(b[2])
        ax.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color="#0b0f14",
            lw=2.8,
            solid_capstyle="round",
            zorder=4.2,
        )
        ax.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color=col,
            lw=2.05,
            solid_capstyle="round",
            zorder=4.4,
        )
    for di, yy, lab in path:
        if lab == "B":
            ax.scatter([di], [yy], s=22, c=_c9_wave_color("B"), zorder=5.4, edgecolors="#111", linewidths=0.4)
            continue
        col = _c9_wave_color(lab)
        odd = lab in {"C1", "C3", "C5", "C7"}
        ax.scatter(
            [di],
            [yy],
            s=40 if lab in {"C7", "C8"} else 30,
            c=col,
            zorder=5.5,
            edgecolors="#111",
            linewidths=0.45,
        )
        ax.text(
            di,
            yy,
            lab.replace("C", ""),
            fontproperties=fp(8, "bold"),
            color=col,
            ha="center",
            va="top" if odd else "bottom",
            zorder=6,
        )
    ticks, labs = [], []
    for i, b in enumerate(daily):
        d = _ymd(b.get("date"))
        if len(d) != 8:
            continue
        if i == 0 or i == n - 1 or i % max(1, n // 7) == 0:
            ticks.append(i)
            labs.append(f"{int(d[4:6])}/{int(d[6:8])}")
    ax.set_xticks(ticks)
    ax.set_xticklabels(labs, fontproperties=fp(8, "bold"), color=_LIVE_TEXT)
    ax.tick_params(axis="y", labelsize=8, colors=_LIVE_MUTED)
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(8, "bold"))
        lab.set_color(_LIVE_MUTED)
    ax.set_xlim(-0.6, n - 0.4)
    ys_all = list(lows) + list(highs) + [p[1] for p in path]
    pad = (max(ys_all) - min(ys_all)) * 0.10
    ax.set_ylim(min(ys_all) - pad, max(ys_all) + pad)
    title = "日K＋分色浪線（對齊上方60分）"
    if note:
        title = f"{title}｜{note}"
    ax.set_title(title, fontproperties=fp(9, "bold"), color="#ce93d8", loc="left", pad=3)
    # 說明改由外層 fig 文字，不准蓋住浪線／日期長條



def _axis_pivot_price(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    i: int,
    *,
    tip: str = "close",
    n: Optional[int] = None,
) -> Optional[Tuple[int, float]]:
    """浪線尖點：(實際軸索引, 價)。優先 tip＝low／high／close；NaN 則就近有限柱。"""
    import math

    m = int(n) if n is not None else max(len(closes), len(highs), len(lows))
    tip_l = str(tip or "close").lower()
    primary = lows if tip_l == "low" else highs if tip_l == "high" else closes
    j = _nearest_finite_axis_idx(primary, i, n=m)
    if j is None:
        j = _nearest_finite_axis_idx(closes, i, n=m)
    if j is None:
        return None
    try:
        if tip_l == "low":
            y = float(lows[j]) if lows[j] == lows[j] else float(closes[j])
        elif tip_l == "high":
            y = float(highs[j]) if highs[j] == highs[j] else float(closes[j])
        else:
            y = float(closes[j])
    except (TypeError, ValueError, IndexError):
        return None
    if not (y == y and math.isfinite(y)):
        return None
    return (int(j), float(y))


def _align_us_to_twii_dates(
    us_rows: Sequence[Dict[str, Any]],
    bars: Sequence[Dict[str, Any]],
    *,
    fill_missing: bool = True,
) -> Dict[str, List[float]]:
    """對齊加權交易日索引。

    fill_missing=True（美股預設）：缺日 OHLC 用前值填，量只計有真柱的日。
    fill_missing=False（台指電子盤）：缺日 OHLC＝nan，不准前收灌成假重複K。
    """
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
            opens.append(float(hit.get("open") or hit.get("close") or 0))
            highs.append(float(hit.get("high") or hit.get("close") or 0))
            lows.append(float(hit.get("low") or hit.get("close") or 0))
            closes.append(float(hit.get("close") or 0))
            continue
        volumes.append(0.0)
        if fill_missing and last:
            # 美股休／缺日：價可延前收對齊軸，量不准假灌
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
        from decision_card_signals import candle_body_up_taiwan
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
    try:
        sox = _inject_yahoo_us_last_into_rows(
            sox, yid="^SOX", sym="SOX", db_path=db_path
        )
    except Exception:
        logger.exception("外圍教具費半 Yahoo 末日注入略過")
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
    for a in (ax, axu, axv):
        a.set_facecolor(_LIVE_PANEL)
        a.tick_params(colors=_LIVE_MUTED, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(_LIVE_GRID)
        a.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color=_LIVE_GRID)

    # 上：加權＋⑤／A／B／C進行中（中段不准標成 C 已完）
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
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
            up = candle_body_up_taiwan(sox_c[i], prev_c, sox_o[i])
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
        from decision_card_signals import candle_body_up_taiwan
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
    _paint_live_candles(ax, axv, opens, highs, lows, closes, vols, candle_body_up_taiwan)
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


# 三窗成品鎖死步驟（改圖前先對這表；漏一步＝殘破）
# 順序＝prepare → paint；倒推＝從出圖往回查哪步漂了
TEACH_TRIO_PIPELINE: Tuple[Tuple[str, str], ...] = (
    ("01_index_bars", "補加權／費半官方日K"),
    ("02_posts_fresh", "補飆大公開文（節流）；口頭題旨／右標跟貼文庫"),
    ("03_build_pack", "_build_live_pack：題旨≤查詢日＋pred／量價位"),
    ("04_live_twii", "MIS 疊加權；今日量=0 視為未齊仍疊"),
    ("05_live_sox", "費半即時（現金盤中才標盤中）"),
    ("06_tx_night_day", "補夜盤 cap 列＋收後補日盤 regular"),
    ("07_teach_tip", "凍白底戳三價／漲幅％（遠近超近同口）"),
    ("08_sox_pred", "費半撐壓階梯對最新價"),
    ("09_paint_far", "遠窗：費半｜電子盤｜加權｜量＋白底戳；跨度標後再蓋回縮圖K"),
    ("10_paint_near", "近窗：日K浪線＋黃帶＋右欄口頭；跨度標後再蓋回縮圖K"),
    ("11_paint_micro", "超近60m：今日底色／粗藍折／細白碎浪／右欄"),
    ("12_persist", "落 biaoke_open_day_paints＋teach_tip"),
)


def prepare_wave_live_pack(
    db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """波浪／教具共用準備：ensure 加權／費半日K＋飆大公開文＋組 pack＋盤中 MIS／SOX。

    話筒遠／近／超近同按一次只准跑一回；paint 可帶 pack 進來不再重抓。
    行情與口頭必須同輪刷新：不准出現「白底／漲幅是當下、貼文庫還停多天前」。
    盤中未收不當官方收。步驟表見 ``TEACH_TRIO_PIPELINE``。
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
        # 與日K同層：三窗題旨／右欄口頭標跟得上當下貼文（節流；失敗不擋）
        try:
            pack_fresh = _ensure_teach_biaoke_posts_fresh(db_path, now=dt)
        except Exception:
            logger.debug("prepare_wave 飆大文略過", exc_info=True)
            pack_fresh = {"ok": False, "reason": "ensure_exc"}
    else:
        pack_fresh = {"ok": False, "reason": "no_db"}
    pack = dict(_build_live_pack(db_path, now=dt) or {})
    if isinstance(pack_fresh, dict) and pack_fresh:
        pack["_biaoke_posts_fresh"] = pack_fresh
    try:
        from live_quote import fetch_mis_index_quote, is_live_merge_window

        if is_live_merge_window(dt):
            live_tw = fetch_mis_index_quote(fresh=True)
            if live_tw:
                pack["live_twii"] = live_tw
    except Exception:
        logger.debug("prepare_wave 盤中加權略過", exc_info=True)
    # 官方日K若仍停昨日：盤後空窗也要疊 MIS，不准三張黃框卡昨日收
    try:
        pack = _fill_live_twii_when_official_lags(pack, db_path, now=dt)
        # 疊完重讀 as_of（顯示日）
        try:
            live_bars = _twii_bars_for_teach(db_path, 4, pack)
            if live_bars:
                pack["chart_as_of"] = _ymd(live_bars[-1].get("date")) or pack.get(
                    "chart_as_of"
                )
        except Exception:
            pass
    except Exception:
        logger.debug("prepare_wave 官方落後疊加略過", exc_info=True)
    live_sox = None
    try:
        # force：晚上／盤前／盤後按波浪也重抓費半，不准卡昨日收
        live_sox = _ensure_paint_live_sox(pack, now=dt)
    except Exception:
        logger.debug("prepare_wave 費半即時略過", exc_info=True)
        live_sox = None
    # 電子夜盤：先強迫補牆鐘 cap 當日官方列（修遠窗少最新夜）；盤中再疊 live_tx
    try:
        _ensure_latest_tx_night_row(db_path)
    except Exception:
        logger.debug("prepare_wave 補最新夜盤列略過", exc_info=True)
    # 日盤收後補今日 TX regular，避免三欄日期各停一天
    try:
        _ensure_teach_tx_day_row(db_path, now=dt)
    except Exception:
        logger.debug("prepare_wave 補台指日盤略過", exc_info=True)
    try:
        if _tx_night_session_live(dt):
            _ensure_paint_live_tx(pack, now=dt)
    except Exception:
        logger.debug("prepare_wave 電子夜盤即時略過", exc_info=True)
    # 三窗同口：prep 當下凍一份 tip，遠／近／超近不准各自再漂成不同日盤價
    try:
        pack["teach_tip"] = compute_teach_tip_snapshot(
            db_path, pack, reuse_frozen=False
        )
    except Exception:
        logger.debug("prepare_wave teach_tip 略過", exc_info=True)
    # 即時價若已破 4/28 9865 → 掛 2/25 8498 再回測（撐壓對最新價）
    try:
        pred = pack.get("pred_levels") if isinstance(pack.get("pred_levels"), dict) else {}
        px = _sox_latest_px(db_path, live=pack.get("live_sox") or live_sox)
        refreshed = _refresh_sox_pred_cascade(pred, db_path, sox_px=px)
        pack["pred_levels"] = refreshed
        if refreshed.get("note"):
            pack["pred_note"] = str(refreshed.get("note") or "")[:280]
            for row in refreshed.get("sox") or []:
                try:
                    pack.setdefault("key_levels", {})[
                        f"pred_sox_{int(float(row['level']))}"
                    ] = float(row["level"])
                except (TypeError, ValueError, KeyError):
                    continue
    except Exception:
        logger.debug("prepare_wave 費半撐壓階梯略過", exc_info=True)
    pack["query_at"] = dt.isoformat()
    pack["_prep_now"] = dt
    return pack


def render_oral_dual_path_schematic(
    save_path: str,
    *,
    pack: Optional[Dict[str, Any]] = None,
    snip: str = "",
) -> str:
    """口述雙軌對照圖（已停用・2026-11-11 使用者定版拿掉）。

    一律不產檔、不寄話筒。雙軌題旨仍可留在文字／三窗，不准再出這張示意圖。
    """
    _ = (save_path, pack, snip)
    return ""
    # --- 以下保留備查，永不執行 ---
    blob = str(snip or "")
    if not blob and isinstance(pack, dict):
        blob = str(
            pack.get("snippet_full")
            or pack.get("snippet")
            or pack.get("thesis")
            or ""
        )
    if not _text_has_bb_dual_path(blob) and "B-b" not in blob and "9波擴延" not in blob:
        # 無雙軌題旨就不產（避免空圖蓋舊）
        if not re.search(r"37837|5\s*波\s*跌完", blob):
            return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except Exception:
        logger.exception("口述對照圖缺 matplotlib")
        return ""

    # 與三窗／高低卡同源：wayne_navigator 打包 NotoSansTC（Render 無系統 CJK 也要有字）
    # 不准只用系統 NotoSansCJK.ttc——缺檔或 TTC 選錯面＝豆腐「字」方塊，話筒讀不到
    try:
        from wayne_navigator import _fp as _nav_fp

        def _fp(size: float = 11.0, weight: str = "normal"):
            return _nav_fp(float(size), weight)

    except Exception:
        fp_path = ""
        for cand in (
            os.path.join(os.path.dirname(__file__) or ".", "fonts", "NotoSansTC-w860.ttf"),
            os.path.join(os.path.dirname(__file__) or ".", "fonts", "NotoSansTC-w560.ttf"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ):
            if os.path.isfile(cand):
                fp_path = cand
                break

        def _fp(size: float = 11.0, weight: str = "normal"):
            if fp_path:
                return font_manager.FontProperties(
                    fname=fp_path, size=size, weight=weight
                )
            return font_manager.FontProperties(size=size, weight=weight)

    fig, axes = plt.subplots(2, 1, figsize=(11.2, 9.0), dpi=150)
    fig.patch.set_facecolor("#0f1419")
    for ax in axes:
        ax.set_facecolor("#0f1419")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)

    ax = axes[0]
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10)
    ax.text(
        0.15,
        9.25,
        "主線：五波跌完 → 走 B-b（不是大C走完、也不是新上升1）",
        color="#80cbc4",
        ha="left",
        va="top",
        fontproperties=_fp(13, "bold"),
    )
    w5 = [(0.6, 7.2), (1.5, 5.0), (2.3, 6.1), (3.3, 3.4), (4.1, 4.6), (5.2, 2.2)]
    ax.plot(*zip(*w5), color="#e8eaf0", lw=2.1)
    for i, (x, y) in enumerate(w5[1:], 1):
        ax.scatter([x], [y], s=32, c="#e8eaf0", zorder=5)
        ax.text(x, y - 0.4, str(i), color="#90caf9", ha="center", fontproperties=_fp(9, "bold"))
    ax.text(5.2, 0.7, "約 37,837（五波末）", color="#ce93d8", ha="center", fontproperties=_fp(9))
    b_pts = [(5.2, 2.2), (6.4, 4.0), (7.6, 2.6), (9.2, 5.2)]
    ax.plot(*zip(*b_pts), color="#ffd54f", lw=2.3)
    for lab, (x, y), col in zip(
        ("B-a", "B-b", "B-c"), b_pts[1:], ("#ffd54f", "#ff8a80", "#ffd54f")
    ):
        ax.scatter([x], [y], s=40, c=col, zorder=6, edgecolors="#0f1419", linewidths=0.5)
        ax.text(
            x,
            y + (0.35 if lab != "B-b" else -0.55),
            lab,
            color=col,
            ha="center",
            fontproperties=_fp(10, "bold"),
        )
    ax.text(
        7.6,
        1.2,
        "可能戳破 37,837＝假跌破觀察",
        color="#ff8a80",
        ha="center",
        fontproperties=_fp(9),
    )
    ax.text(
        10.5,
        6.6,
        "五波跌完\n之後進 B",
        color="#80cbc4",
        ha="center",
        fontproperties=_fp(10, "bold"),
        bbox=dict(boxstyle="round,pad=0.3", fc="#1b2838", ec="#80cbc4", lw=0.8),
    )

    ax = axes[1]
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10)
    ax.text(
        0.15,
        9.25,
        "備線：若還沒跌完 → 九波擴延（不是轉 B；看 35,579→31,705）",
        color="#ef9a9a",
        ha="left",
        va="top",
        fontproperties=_fp(13, "bold"),
    )
    ext = [
        (0.6, 7.4),
        (1.3, 5.4),
        (2.0, 6.3),
        (2.8, 4.0),
        (3.5, 5.0),
        (4.3, 2.8),
        (5.0, 3.7),
        (5.8, 2.1),
        (6.5, 2.9),
        (7.6, 0.9),
    ]
    ax.plot(*zip(*ext[:6]), color="#e8eaf0", lw=1.9)
    ax.plot(*zip(*ext[5:]), color="#ef9a9a", lw=2.3)
    for i, (x, y) in enumerate(ext[1:], 1):
        col = "#90caf9" if i <= 5 else "#ef9a9a"
        ax.scatter([x], [y], s=28, c=col, zorder=5)
        ax.text(x, y - 0.38, str(i), color=col, ha="center", fontproperties=_fp(8.5, "bold"))
    ax.axvline(4.3, color="#546e7a", lw=0.9, ls=(0, (3, 2)), ymin=0.08, ymax=0.7)
    ax.text(
        4.3,
        7.6,
        "若只看到這裡\n會以為五波完",
        color="#b0bec5",
        ha="center",
        fontproperties=_fp(8.5),
    )
    ax.axhline(1.7, color="#ce93d8", lw=1.0, ls=(0, (4, 2)), xmin=0.55, xmax=0.92)
    ax.text(10.4, 1.7, "35,579\n(2/26 第一波高)", color="#ce93d8", ha="left", va="center", fontproperties=_fp(8.5))
    ax.axhline(0.7, color="#ff8a80", lw=1.0, ls=(0, (4, 2)), xmin=0.55, xmax=0.92)
    ax.text(10.4, 0.7, "31,705\n(3/31 低)", color="#ff8a80", ha="left", va="center", fontproperties=_fp(8.5))
    ax.text(
        9.0,
        5.6,
        "九波擴延\n＝續跌不是轉 B",
        color="#ef9a9a",
        ha="center",
        fontproperties=_fp(10, "bold"),
        bbox=dict(boxstyle="round,pad=0.3", fc="#2a1518", ec="#ef9a9a", lw=0.8),
    )

    fig.suptitle(
        "口述結構對照（說明用・非買訊）｜與三窗同口・後文壓前文",
        color="#eceff1",
        y=0.98,
        fontproperties=_fp(14, "bold"),
    )
    fig.text(
        0.5,
        0.012,
        "官方對照：週五低≈37,837；4/23低≈37,164。浪形＝口述示意，不是已驗證段號。",
        color="#78909c",
        ha="center",
        fontproperties=_fp(8),
    )
    try:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        plt.tight_layout(rect=(0.02, 0.03, 0.98, 0.95))
        fig.savefig(save_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    except Exception:
        logger.exception("口述對照圖存檔失敗")
        plt.close(fig)
        return ""
    plt.close(fig)
    if os.path.isfile(save_path) and os.path.getsize(save_path) > 2000:
        return save_path
    return ""


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

    # 口述雙軌對照圖已停用（2026-11-11 定版拿掉）：不准再渲／再寄
    oral_path = ""

    # as_of＝加權末柱顯示日（官方收或盤中／空窗疊加），不准寫日曆 ymd 讓舊圖假裝今天
    chart_as_of = _ymd(pack.get("chart_as_of")) or _twii_chart_as_of(db_path) or ymd
    try:
        live_bars = _twii_bars_for_teach(db_path, 8, pack)
        if live_bars:
            chart_as_of = _ymd(live_bars[-1].get("date")) or chart_as_of
    except Exception:
        pass
    # 三窗現況 tip 落 key_levels：話筒回退舊圖要比對同口
    if not isinstance(key_levels, dict):
        key_levels = {}
    else:
        key_levels = dict(key_levels)
    try:
        key_levels["_teach_tip"] = compute_teach_tip_snapshot(db_path, pack)
    except Exception:
        logger.debug("teach tip 落檔略過", exc_info=True)
    if oral_path:
        key_levels["_oral_path"] = oral_path

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
                as_of=excluded.as_of,
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
                    WHEN excluded.as_of!=biaoke_open_day_paints.as_of THEN ''
                    ELSE biaoke_open_day_paints.far_path END,
                near_path=CASE WHEN excluded.near_path!='' THEN excluded.near_path
                    WHEN excluded.as_of!=biaoke_open_day_paints.as_of THEN ''
                    ELSE biaoke_open_day_paints.near_path END,
                us_path=CASE WHEN excluded.us_path!='' THEN excluded.us_path
                    ELSE biaoke_open_day_paints.us_path END,
                micro_path=CASE WHEN excluded.micro_path!='' THEN excluded.micro_path
                    WHEN excluded.as_of!=biaoke_open_day_paints.as_of THEN ''
                    ELSE biaoke_open_day_paints.micro_path END,
                pending=1,
                verdict='',
                checked_at='',
                created_at=excluded.created_at
            """,
            (
                slot_id,
                chart_as_of,
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
        "活畫 slot=%s thesis=%s far=%s near=%s micro=%s oral=%s us=%s tx60=%s as_of=%s",
        slot_id,
        thesis,
        bool(far_path),
        bool(near_path),
        bool(micro_path),
        bool(oral_path),
        bool(us_path),
        bool(tx60_path),
        chart_as_of,
    )
    return {
        "ok": bool(near_path or far_path or us_path or micro_path or tx60_path or oral_path),
        "path": chart_path or near_path or "",
        "far_path": far_path or "",
        "near_path": near_path or "",
        "micro_path": micro_path or "",
        "oral_path": oral_path or "",
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


def latest_teach_kit(db_path: str) -> Dict[str, Any]:
    """話筒空白鍵教具：取最近一槽已存遠／近／超級近／外圍路徑（有檔才回）。

    失敗回空 dict；不准擋主摘要。不在這裡重渲（重渲走 paint_open_day_hypothesis）。
    附 teach_tip（key_levels._teach_tip）供回退比對三窗現況一口。
    """
    out: Dict[str, Any] = {
        "far_path": "",
        "near_path": "",
        "micro_path": "",
        "oral_path": "",
        "us_path": "",
        "thesis": "",
        "slot_id": "",
        "as_of": "",
        "teach_tip": {},
    }
    if not db_path:
        return out
    try:
        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT slot_id, as_of, thesis, far_path, near_path, us_path, "
                "COALESCE(micro_path,''), COALESCE(key_levels,'') "
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
    try:
        levels = json.loads(row[7] or "{}") if row[7] else {}
        tip = levels.get("_teach_tip") if isinstance(levels, dict) else None
        if isinstance(tip, dict):
            out["teach_tip"] = tip
        # 口述雙軌對照圖已停用：不准再從舊檔／別名回填 oral_path
        out["oral_path"] = ""
    except Exception:
        out["teach_tip"] = {}
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
