# -*- coding: utf-8 -*-
"""話筒主述新鮮度：飆大／波浪位階文案是否脫離現況。

目標：使用者一看就知道「他文日／加權資料日」；過舊就標警告，不准默默當今日現況。
不是買訊。失敗吞掉，不准打斷出圖／抓文。
Asia/Taipei。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.narrative_fresh")

TAIPEI = ZoneInfo("Asia/Taipei")
# 開市日滯後幾日算「主述偏舊」（週末休市不算硬過期；1＝隔一個開市日就標）
STALE_OPEN_LAG = 1
PIPELINE_PREFIX = "narrative-fresh-"


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _ymd_dash(ymd: str) -> str:
    d = _ymd(ymd)
    if not d:
        return ""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def latest_biaoke_board_meta(db_path: str) -> Dict[str, str]:
    """他最新大盤／位階相關文（主文或自回）。"""
    out = {"ymd": "", "when": "", "post_id": "", "snip": ""}
    path = str(db_path or "").strip()
    if not path:
        return out
    try:
        conn = sqlite3.connect(path, timeout=12.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return out
    try:
        # 優先：level snaps（位階題旨）；缺表不准整段放棄改讀 posts
        try:
            row = conn.execute(
                """
                SELECT as_of, post_date, post_id, snippet
                FROM biaoke_level_snaps
                ORDER BY as_of DESC, created_at DESC LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row:
            out["ymd"] = _ymd(row["as_of"]) or _ymd(str(row["post_date"] or "").replace("-", ""))
            pd = str(row["post_date"] or "")
            out["when"] = pd[:16] if pd else _ymd_dash(out["ymd"])
            out["post_id"] = str(row["post_id"] or "")
            out["snip"] = str(row["snippet"] or "")[:80]
        # 再用「大盤／位階」相關最新文／自回（個股文不准把板面日拉新）
        # 含防線／35000／35700 等當令點位句，自回改口也要刷新「他文」日
        try:
            post = conn.execute(
                """
                SELECT id, date, time, text FROM biaoke_posts
                WHERE IFNULL(kind,'') != 'bystander'
                  AND (
                    text LIKE '%大盤%' OR text LIKE '%加權%' OR text LIKE '%台指%'
                    OR text LIKE '%波浪%' OR text LIKE '%費半%' OR text LIKE '%位階%'
                    OR text LIKE '%下降壓%' OR text LIKE '%C3%' OR text LIKE '%假跌破%'
                    OR text LIKE '%防線%' OR text LIKE '%系統性風險%'
                    OR text LIKE '%35000%' OR text LIKE '%35500%' OR text LIKE '%35700%'
                    OR text LIKE '%33000%' OR text LIKE '%31700%' OR text LIKE '%31500%'
                    OR text LIKE '%9波%' OR text LIKE '%1 4重疊%' OR text LIKE '%14重疊%'
                  )
                ORDER BY date DESC, time DESC LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error:
            post = None
        if post:
            py = _ymd(str(post["date"] or "").replace("-", ""))
            if py and (not out["ymd"] or py >= out["ymd"]):
                out["ymd"] = py
                tm = str(post["time"] or "")[:5]
                out["when"] = f"{_ymd_dash(py)} {tm}".strip()
                out["post_id"] = str(post["id"] or "")
                out["snip"] = str(post["text"] or "")[:80]
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def official_twii_ymd(db_path: str) -> str:
    try:
        from biaoke_level_learn import _twii_chart_as_of

        return _ymd(_twii_chart_as_of(db_path))
    except Exception:
        pass
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(db_path))
    except Exception:
        return ""


def _open_days_between(db_path: str, a: str, b: str) -> int:
    """a→b 之間開市日數（不含 a、含 b 近似）。缺曆＝日曆差。"""
    ya, yb = _ymd(a), _ymd(b)
    if not ya or not yb or yb <= ya:
        return 0
    try:
        from trading_calendar import is_tw_open_calendar_day

        d0 = datetime.strptime(ya, "%Y%m%d").date()
        d1 = datetime.strptime(yb, "%Y%m%d").date()
        n = 0
        cur = d0 + timedelta(days=1)
        while cur <= d1:
            if is_tw_open_calendar_day(cur):
                n += 1
            cur += timedelta(days=1)
        return n
    except Exception:
        try:
            d0 = datetime.strptime(ya, "%Y%m%d")
            d1 = datetime.strptime(yb, "%Y%m%d")
            return max(0, (d1 - d0).days)
        except Exception:
            return 0


def assess_narrative_freshness(
    db_path: str,
    *,
    now: Optional[datetime] = None,
    thesis_as_of: str = "",
) -> Dict[str, Any]:
    """回傳新鮮度評估。stale=True 時話筒必須標警告。"""
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    board = latest_biaoke_board_meta(db_path)
    twii = official_twii_ymd(db_path)
    thesis = _ymd(thesis_as_of)
    board_ymd = _ymd(board.get("ymd"))
    lag_board_twii = _open_days_between(db_path, board_ymd, twii) if board_ymd and twii else 0
    lag_thesis_twii = _open_days_between(db_path, thesis, twii) if thesis and twii else 0
    # 牆鐘相對他文：休市日用日曆，但開市滯後才硬 stale
    today = dt.strftime("%Y%m%d")
    lag_board_today = _open_days_between(db_path, board_ymd, today) if board_ymd else 99
    stale = False
    reasons = []
    if board_ymd and twii and lag_board_twii >= STALE_OPEN_LAG:
        stale = True
        reasons.append(f"他文落後加權{lag_board_twii}開市日")
    if thesis and twii and lag_thesis_twii >= STALE_OPEN_LAG:
        stale = True
        reasons.append(f"題旨落後加權{lag_thesis_twii}開市日")
    if board_ymd and lag_board_today >= STALE_OPEN_LAG:
        stale = True
        reasons.append(f"他文距今{lag_board_today}開市日")
    note = "；".join(reasons) if reasons else "齊"
    return {
        "stale": stale,
        "board_ymd": board_ymd,
        "board_when": str(board.get("when") or ""),
        "twii_ymd": twii,
        "thesis_as_of": thesis,
        "lag_board_twii": lag_board_twii,
        "lag_thesis_twii": lag_thesis_twii,
        "note": note,
        "checked_at": _stamp(),
    }


def freshness_banner_html(fresh: Dict[str, Any]) -> str:
    """話筒 HTML 前綴：資料日一行；過舊加警告。不准英文 as_of。"""
    board = _ymd_dash(str(fresh.get("board_ymd") or ""))
    twii = _ymd_dash(str(fresh.get("twii_ymd") or ""))
    when = str(fresh.get("board_when") or board).strip()
    bits = []
    if when:
        bits.append(f"他文 {when}")
    if twii:
        bits.append(f"加權已收 {twii}")
    line = "　".join(bits) if bits else "資料日未齊"
    from html import escape

    out = f"<i>{escape(line)}（台北）</i>"
    if fresh.get("stale"):
        warn = (
            "主述可能已脫離現況—"
            + str(fresh.get("note") or "偏舊")
            + "。請先對圖上現價／最新柱，勿當今日現況。"
        )
        out += f"\n<b>⚠ {escape(warn)}</b>"
    return out


def freshness_banner_plain(fresh: Dict[str, Any]) -> str:
    board = _ymd_dash(str(fresh.get("board_ymd") or ""))
    twii = _ymd_dash(str(fresh.get("twii_ymd") or ""))
    when = str(fresh.get("board_when") or board).strip()
    bits = []
    if when:
        bits.append(f"他文 {when}")
    if twii:
        bits.append(f"加權已收 {twii}")
    line = "　".join(bits) if bits else "資料日未齊"
    out = f"{line}（台北）"
    if fresh.get("stale"):
        out += (
            "\n⚠ 主述可能已脫離現況—"
            + str(fresh.get("note") or "偏舊")
            + "。請先對圖上現價／最新柱，勿當今日現況。"
        )
    return out


def mark_pipeline(db_path: str, status: str, notes: str) -> None:
    ymd = datetime.now(TAIPEI).strftime("%Y%m%d")
    key = f"{PIPELINE_PREFIX}{ymd}"
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_date TEXT PRIMARY KEY,
                finished_at TEXT,
                status TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs "
            "(run_date, status, notes, finished_at) VALUES (?,?,?,?)",
            (key, status, (notes or "")[:500], _stamp()),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug("narrative pipeline stamp skip", exc_info=True)


def refresh_wave_narrative_cache(db_path: str) -> Dict[str, Any]:
    """彙整後重算題旨 pack＋自檢新鮮度；必要時觸發活畫鉤子。

    失敗不擋 absorb／融合。不是買訊。重渲走既有稀疏槽，不准每檔都硬畫。
    """
    out: Dict[str, Any] = {"ok": False, "note": ""}
    path = str(db_path or "").strip()
    if not path:
        out["note"] = "缺 db"
        return out
    try:
        try:
            from biaoke_weave import load_weave

            load_weave.cache_clear()
        except Exception:
            pass
        pack: Dict[str, Any] = {}
        try:
            from biaoke_level_learn import _build_live_pack

            pack = _build_live_pack(path) or {}
        except Exception:
            pack = {}
        painted: Dict[str, Any] = {}
        try:
            from biaoke_level_learn import maybe_paint_open_day_after_ingest

            # force＝他文／題旨可能已變；稀疏窗外仍可能 restore 缺檔
            painted = maybe_paint_open_day_after_ingest(path, force=True) or {}
        except Exception:
            logger.debug("narrative refresh paint skip", exc_info=True)
        fresh = assess_narrative_freshness(
            path,
            thesis_as_of=str(
                pack.get("thesis_as_of")
                or pack.get("chart_as_of")
                or painted.get("as_of")
                or ""
            ),
        )
        st = "stale" if fresh.get("stale") else "success"
        mark_pipeline(
            path,
            st,
            f"board={fresh.get('board_ymd')} twii={fresh.get('twii_ymd')} "
            f"thesis={str(pack.get('thesis') or '')[:40]}",
        )
        out["ok"] = True
        out["fresh"] = fresh
        out["painted_ok"] = bool(painted.get("ok"))
        out["note"] = fresh.get("note") or "ok"
    except Exception as exc:
        logger.exception("刷新波浪／飆大主述快取失敗")
        out["note"] = type(exc).__name__
        mark_pipeline(path, "error", out["note"])
    return out


def run_narrative_self_check(db_path: str) -> Dict[str, Any]:
    """融合後自檢：只記新鮮度；過舊打 stale 戳（之後可接推播／叫修）。"""
    fresh = assess_narrative_freshness(db_path)
    st = "stale" if fresh.get("stale") else "success"
    mark_pipeline(
        db_path,
        st,
        f"selfcheck board={fresh.get('board_ymd')} twii={fresh.get('twii_ymd')} "
        f"{fresh.get('note')}",
    )
    return {"ok": True, "fresh": fresh, "status": st}
