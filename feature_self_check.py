# -*- coding: utf-8 -*-
"""話筒／子鈕自主檢查骨架。

各功能把自己的檢查掛進來；過舊／缺檔／異常只落 pipeline_runs，
失敗不准打斷查股／海選／出圖。之後可接推播或叫 Cloud Agent 查修。

Asia/Taipei。不是買訊。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.feature_self_check")

TAIPEI = ZoneInfo("Asia/Taipei")
PIPELINE_PREFIX = "feat-check-"


def _stamp() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd_today() -> str:
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def _mark(db_path: str, feature: str, status: str, notes: str) -> None:
    key = f"{PIPELINE_PREFIX}{feature}-{_ymd_today()}"
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
            (key, status, (notes or "")[:800], _stamp()),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug("feature self-check stamp skip", exc_info=True)


CheckFn = Callable[[str], Dict[str, Any]]


def _check_narrative(db_path: str) -> Dict[str, Any]:
    from phone_narrative_freshness import run_narrative_self_check

    got = run_narrative_self_check(db_path) or {}
    fresh = got.get("fresh") or {}
    status = "stale" if fresh.get("stale") else "success"
    return {
        "feature": "narrative",
        "status": status,
        "ok": not bool(fresh.get("stale")),
        "notes": str(fresh.get("note") or got.get("status") or ""),
        "detail": {
            "board_ymd": fresh.get("board_ymd"),
            "twii_ymd": fresh.get("twii_ymd"),
        },
    }


def _check_teach_kit(db_path: str) -> Dict[str, Any]:
    """波浪教具 trio 是否齊；缺檔標 warn（可呼叫補渲，這裡只檢查）。"""
    try:
        from biaoke_level_learn import latest_teach_kit, teach_kit_needs_restore

        needs = bool(teach_kit_needs_restore(db_path))
        kit = latest_teach_kit(db_path) or {}
        has = any(str(kit.get(k) or "").strip() for k in ("far_path", "near_path", "micro_path"))
        if needs:
            return {
                "feature": "teach-kit",
                "status": "warn",
                "ok": False,
                "notes": "教具缺檔可補渲",
                "detail": {"has_any": has},
            }
        return {
            "feature": "teach-kit",
            "status": "success",
            "ok": True,
            "notes": "齊" if has else "尚無列",
            "detail": {"has_any": has},
        }
    except Exception as exc:
        return {
            "feature": "teach-kit",
            "status": "error",
            "ok": False,
            "notes": type(exc).__name__,
            "detail": {},
        }


# 可擴充：低估／海選／洞燭…各自加一條，過舊才亮
DEFAULT_CHECKS: List[CheckFn] = [
    _check_narrative,
    _check_teach_kit,
]


def run_feature_self_check(
    db_path: str,
    *,
    checks: Optional[List[CheckFn]] = None,
) -> Dict[str, Any]:
    """跑一輪自主檢查。回傳各 feature 狀態；整體 ok＝無 error／stale／warn。"""
    path = str(db_path or "").strip()
    report: Dict[str, Any] = {
        "ok": True,
        "checked_at": _stamp(),
        "features": [],
        "needs_attention": [],
    }
    if not path:
        report["ok"] = False
        report["notes"] = "缺 db"
        return report
    for fn in checks or DEFAULT_CHECKS:
        try:
            row = fn(path) or {}
        except Exception as exc:
            logger.exception("feature self-check 單項失敗")
            row = {
                "feature": getattr(fn, "__name__", "unknown"),
                "status": "error",
                "ok": False,
                "notes": type(exc).__name__,
            }
        feat = str(row.get("feature") or "unknown")
        status = str(row.get("status") or "error")
        _mark(path, feat, status, str(row.get("notes") or ""))
        report["features"].append(row)
        if status in ("stale", "warn", "error") or not row.get("ok", True):
            report["ok"] = False
            report["needs_attention"].append(feat)
    # 總戳：當天有沒有需要人看／之後可叫修
    overall = "success" if report["ok"] else "attention"
    _mark(
        path,
        "all",
        overall,
        ",".join(report["needs_attention"]) or "齊",
    )
    return report


def refresh_and_check(db_path: str) -> Dict[str, Any]:
    """彙整／融合後：先刷新主述快取，再跑自主檢查。"""
    out: Dict[str, Any] = {"refresh": {}, "check": {}}
    try:
        from phone_narrative_freshness import refresh_wave_narrative_cache

        out["refresh"] = refresh_wave_narrative_cache(db_path)
    except Exception as exc:
        out["refresh"] = {"ok": False, "note": type(exc).__name__}
    try:
        out["check"] = run_feature_self_check(db_path)
    except Exception as exc:
        out["check"] = {"ok": False, "notes": type(exc).__name__}
    return out
