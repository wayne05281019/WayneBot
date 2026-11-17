# -*- coding: utf-8 -*-
"""低估名單盤後掃描寫庫（開市日）。

觸發＝官方 16:30 融合成功後立刻掃（掛 main_runner._run_post_fuse_silent_tracks）。
不准硬等 19:20。不寄話筒推播。不是買訊。
掃完：話筒現況碼寫庫＋靜默落檔；同件跑下一版硬濾只靜默（§13 再生）。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.undervalue")

TAIPEI = ZoneInfo("Asia/Taipei")
PIPELINE_PREFIX = "undervalue-"


def pipeline_key(ymd: str) -> str:
    return f"{PIPELINE_PREFIX}{str(ymd or '').strip()}"


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_tables(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    try:
        from wayne_db import ensure_core_schema

        ensure_core_schema(path)
    except Exception:
        pass
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_date TEXT PRIMARY KEY,
                finished_at TEXT,
                status TEXT,
                notes TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS undervalue_runs (
                as_of TEXT NOT NULL PRIMARY KEY,
                status TEXT NOT NULL,
                n_star INTEGER DEFAULT 0,
                n_watch INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                started_at TEXT,
                finished_at TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS undervalue_picks (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                name TEXT DEFAULT '',
                mark TEXT NOT NULL,
                close REAL,
                pe REAL,
                pe_est INTEGER DEFAULT 0,
                peer_pe_median REAL,
                dist_to_floor_pct REAL,
                flow_shares REAL,
                reason TEXT DEFAULT '',
                detail_json TEXT DEFAULT '',
                PRIMARY KEY (as_of, stock_id)
            );
            """
        )
        try:
            cols = {
                str(r[1])
                for r in conn.execute("PRAGMA table_info(undervalue_picks)").fetchall()
            }
            if "detail_json" not in cols:
                conn.execute(
                    "ALTER TABLE undervalue_picks ADD COLUMN detail_json TEXT DEFAULT ''"
                )
        except sqlite3.Error:
            pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_uv_picks_asof ON undervalue_picks(as_of);"
        )
        conn.commit()
    finally:
        conn.close()


def _already_success(db_path: str, ymd: str) -> bool:
    key = pipeline_key(ymd)
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT status FROM pipeline_runs WHERE run_date=?", (key,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row and str(row[0] or "") == "success")


def _mark_pipeline(db_path: str, ymd: str, status: str, notes: str) -> None:
    key = pipeline_key(ymd)
    try:
        from wayne_db import connect

        conn = connect(db_path)
    except Exception:
        conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs "
            "(run_date, status, notes, finished_at) VALUES (?, ?, ?, ?)",
            (key, status, (notes or "")[:500], _stamp()),
        )
        conn.commit()
    finally:
        conn.close()


def load_run(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    ensure_tables(db_path)
    ymd = str(as_of or "").replace("-", "")[:8]
    if len(ymd) != 8:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT as_of, status, n_star, n_watch, note, started_at, finished_at "
            "FROM undervalue_runs WHERE as_of=?",
            (ymd,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def load_picks(db_path: str, as_of: str) -> list:
    ensure_tables(db_path)
    ymd = str(as_of or "").replace("-", "")[:8]
    if len(ymd) != 8:
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT stock_id, name, mark, close, pe, pe_est, peer_pe_median, "
            "dist_to_floor_pct, flow_shares, reason, detail_json "
            "FROM undervalue_picks WHERE as_of=? "
            "ORDER BY CASE mark WHEN 'star' THEN 0 WHEN 'watch' THEN 1 "
            "WHEN 'emerging' THEN 2 ELSE 3 END, stock_id",
            (ymd,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["pe_est"] = bool(int(d.get("pe_est") or 0))
        raw = str(d.pop("detail_json", "") or "")
        if raw:
            try:
                import json

                detail = json.loads(raw)
                if isinstance(detail, dict):
                    for k, v in detail.items():
                        d.setdefault(k, v)
            except Exception:
                pass
        out.append(d)
    return out


def empty_note_for_button(db_path: str, as_of: str) -> Optional[str]:
    """回傳空名單說明；有列則 None。"""
    run = load_run(db_path, as_of)
    if not run:
        return "盤後還沒算完（融合後掃描）"
    st = str(run.get("status") or "")
    if st in ("pending", "running", "failed", ""):
        if st == "failed":
            return "掃描失敗，稍後再按；不是買訊"
        return "盤後還沒算完（融合後掃描）"
    picks = load_picks(db_path, as_of)
    if not picks:
        return "已算完 0 檔"
    return None


def latest_success_as_of(db_path: str) -> str:
    """最近一次 success 低估掃描日（YYYYMMDD）；沒有則空字。"""
    ensure_tables(db_path)
    conn = sqlite3.connect(str(db_path or ""), timeout=15.0)
    try:
        row = conn.execute(
            "SELECT as_of FROM undervalue_runs WHERE status='success' "
            "ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    ymd = str(row[0] or "").replace("-", "")[:8] if row else ""
    return ymd if len(ymd) == 8 else ""


def resolve_button_as_of(db_path: str) -> str:
    """話筒要用的 as_of：優先最新完整行情日；該日還沒掃成功→退回最近 success。

    避免 Render latest_complete 已到 11/16、庫裡只有 11/09 success 時
    整張顯示「盤後還沒算完」空卡。
    """
    as_of = ""
    try:
        from import_health import latest_complete_quote_date

        as_of = str(latest_complete_quote_date(db_path) or "").replace("-", "")[:8]
    except Exception:
        as_of = ""
    if len(as_of) == 8:
        run = load_run(db_path, as_of)
        if run and str(run.get("status") or "") == "success":
            return as_of
        picks = load_picks(db_path, as_of)
        if picks:
            return as_of
    prev = latest_success_as_of(db_path)
    return prev or as_of


def run_undervalue_sync(
    db_path: str,
    *,
    skip_if_done: bool = True,
    now: Optional[datetime] = None,
    notify: bool = False,
) -> Dict[str, Any]:
    """開市日融合後掃描；notify 一律忽略（不准自動推播）。"""
    _ = notify
    out: Dict[str, Any] = {"ok": False, "as_of": "", "n": 0, "note": ""}
    path = str(db_path or "").strip()
    if not path:
        out["note"] = "缺 db"
        return out
    dt = now or datetime.now(TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    else:
        dt = dt.astimezone(TAIPEI)
    try:
        from tw_holidays import closed_tw_session

        closed = closed_tw_session(now=dt, db_path=path)
    except Exception:
        closed = None
    if closed is not None:
        out["note"] = f"休市略過 {closed.get('ymd')}"
        logger.info("低估掃描：%s", out["note"])
        return out
    try:
        from import_health import latest_complete_quote_date

        as_of = latest_complete_quote_date(path) or ""
    except Exception:
        as_of = ""
    if len(str(as_of)) != 8:
        out["note"] = "缺完整行情日"
        return out
    as_of = str(as_of)
    out["as_of"] = as_of
    if skip_if_done and _already_success(path, as_of):
        out["ok"] = True
        out["note"] = "已 success 略過"
        return out
    ensure_tables(path)
    started = _stamp()
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO undervalue_runs "
            "(as_of, status, n_star, n_watch, note, started_at, finished_at) "
            "VALUES (?, 'running', 0, 0, '', ?, NULL)",
            (as_of, started),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        from undervalue_scan import RULE_PHONE, run_undervalue_scan

        scanned = run_undervalue_scan(path, as_of, rule_key=RULE_PHONE) or {}
    except Exception as exc:
        logger.exception("低估掃描失敗")
        _mark_pipeline(path, as_of, "failed", type(exc).__name__)
        conn = sqlite3.connect(path, timeout=30.0)
        try:
            conn.execute(
                "UPDATE undervalue_runs SET status='failed', note=?, finished_at=? "
                "WHERE as_of=?",
                (type(exc).__name__[:200], _stamp(), as_of),
            )
            conn.commit()
        finally:
            conn.close()
        out["note"] = type(exc).__name__
        return out
    rows = list(scanned.get("rows") or [])
    n_star = sum(1 for r in rows if str(r.get("mark") or "") == "star")
    n_watch = sum(1 for r in rows if str(r.get("mark") or "") == "watch")
    n_emerging = sum(1 for r in rows if str(r.get("mark") or "") == "emerging")
    note = str(scanned.get("note") or "")[:200]
    finished = _stamp()
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        import json

        conn.execute("DELETE FROM undervalue_picks WHERE as_of=?", (as_of,))
        for r in rows:
            detail = {
                k: r.get(k)
                for k in (
                    "industry",
                    "gross_margin",
                    "core_ratio_pct",
                    "core_ratio_label",
                    "yoy_pct",
                    "fair_year",
                    "target_next",
                    "ups_fair_pct",
                    "ups_tgt_pct",
                    "pe_year",
                    "pe_next",
                    "pe_fwd",
                    "eps_earned",
                    "eps_2026",
                    "eps_2027",
                    "rev_threshold_yi",
                    "rev_oct_yi",
                    "support",
                    "resistance",
                    "tech_status",
                    "tech_broken",
                    "chip_note",
                    "chip_kind",
                )
                if r.get(k) is not None
            }
            conn.execute(
                "INSERT OR REPLACE INTO undervalue_picks "
                "(as_of, stock_id, name, mark, close, pe, pe_est, peer_pe_median, "
                "dist_to_floor_pct, flow_shares, reason, detail_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    as_of,
                    str(r.get("stock_id") or ""),
                    str(r.get("name") or ""),
                    str(r.get("mark") or "watch"),
                    r.get("close"),
                    r.get("pe"),
                    1 if r.get("pe_est") else 0,
                    r.get("peer_pe_median"),
                    r.get("dist_to_floor_pct"),
                    r.get("flow_shares"),
                    str(r.get("reason") or "")[:200],
                    json.dumps(detail, ensure_ascii=False) if detail else "",
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO undervalue_runs "
            "(as_of, status, n_star, n_watch, note, started_at, finished_at) "
            "VALUES (?, 'success', ?, ?, ?, ?, ?)",
            (as_of, n_star, n_watch, note, started, finished),
        )
        conn.commit()
    finally:
        conn.close()
    # 靜默落檔＋下一版（失敗不准打斷寫庫 success）
    try:
        from undervalue_confront import remember_scan_rows, run_next_variant_silent

        remember_scan_rows(path, as_of, rows, rule_key=str(scanned.get("rule_key") or ""))
        nxt = run_next_variant_silent(path, as_of)
        out["next_n"] = int(nxt.get("n") or 0)
    except Exception:
        logger.exception("低估靜默／下一版失敗（名單已寫庫）")
    _mark_pipeline(
        path,
        as_of,
        "success",
        f"n={len(rows)} star={n_star} watch={n_watch} emerging={n_emerging} {note}",
    )
    out["ok"] = True
    out["n"] = len(rows)
    out["note"] = note or "ok"
    logger.info(
        "低估掃描完成 as_of=%s n=%s star=%s watch=%s emerging=%s",
        as_of,
        len(rows),
        n_star,
        n_watch,
        n_emerging,
    )
    return out
