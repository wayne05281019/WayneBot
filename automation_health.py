# -*- coding: utf-8 -*-
"""自動化資料管線巡檢：回傳、彙整、融合各環節，問題由系統先發現。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from import_health import (
    audit_import,
    can_publish_release,
    db_quick_check_ok,
    latest_complete_quote_date,
    list_coverage_issues,
    verify_increment_import,
)
from quote_integrity import filter_trusted_quote_tuples


def quote_filter_regression_ok() -> Dict[str, Any]:
    """過濾器煙霧：正常 K 必須通過，高低錯亂必須擋下。漲停鎖死不是假 K。"""
    good = (
        "20260902",
        "2330",
        "台積電",
        "TW",
        1180.0,
        1195.0,
        1175.0,
        1190.0,
        45000,
        53.0,
        0.8,
        1185.0,
        100,
        0,
        0,
    )
    limit_lock = (
        "20260902",
        "3664",
        "安瑞-KY",
        "TWO",
        8.34,
        8.34,
        8.34,
        8.34,
        132,
        1100.88,
        9.88,
        8.34,
        0,
        0,
        0,
    )
    bad = (
        "20260902",
        "9999",
        "錯價",
        "TW",
        100.0,
        90.0,
        110.0,
        100.0,
        1000,
        100.0,
        0.0,
        100.0,
        0,
        0,
        0,
    )
    kept, dropped = filter_trusted_quote_tuples([good, limit_lock, bad])
    kept_ids = {r[1] for r in kept}
    ok = kept_ids == {"2330", "3664"} and dropped >= 1
    return {
        "ok": ok,
        "kept": len(kept),
        "dropped": dropped,
        "reason": "" if ok else "過濾器回歸失敗：正常 K 未通過或高低錯亂未擋下",
    }


def pipeline_recent_status(db_path: str, limit: int = 12) -> Dict[str, Any]:
    """最近排程執行紀錄（pipeline_runs）。"""
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return {"ok": False, "runs": [], "reason": "資料庫不存在"}
    try:
        conn = sqlite3.connect(path)
        rows = conn.execute(
            """
            SELECT run_date, finished_at, status, notes
            FROM pipeline_runs
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return {"ok": False, "runs": [], "reason": str(exc)}
    runs = [
        {"run_date": r[0], "finished_at": r[1], "status": r[2], "notes": r[3] or ""}
        for r in rows
    ]
    return {"ok": True, "runs": runs}


def pipeline_run_status(db_path: str, run_date: str) -> Optional[Dict[str, Any]]:
    """讀取單一 pipeline_runs 紀錄（不受 recent limit 影響）。"""
    path = str(db_path or "").strip()
    key = str(run_date or "").strip()
    if not path or not key or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT run_date, finished_at, status, notes FROM pipeline_runs WHERE run_date = ?",
            (key,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {"run_date": row[0], "finished_at": row[1], "status": row[2], "notes": row[3] or ""}


def pipeline_expectations_met(db_path: str, cap: str = "") -> Dict[str, Any]:
    """交易日應完成的排程是否 success（increment / screen）。"""
    try:
        from config import taipei_now, taipei_today_str
        from trading_calendar import fuse_end_trading_date, is_trading_weekday
    except Exception:
        return {"ok": True, "skipped": True, "reasons": []}

    cap = str(cap or fuse_end_trading_date() or "").replace("-", "")[:8]
    today = taipei_today_str().replace("-", "")[:8]
    reasons: List[str] = []
    path = str(db_path or "").strip()
    if not path or not os.path.isfile(path):
        return {"ok": True, "skipped": True, "cap": cap, "today": today, "reasons": [], "recent": []}
    try:
        conn = sqlite3.connect(path)
        run_count = int(conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] or 0)
        conn.close()
    except sqlite3.Error:
        run_count = 0
    if run_count == 0:
        return {"ok": True, "skipped": True, "cap": cap, "today": today, "reasons": [], "recent": []}
    recent = pipeline_recent_status(db_path).get("runs") or []

    now = taipei_now()
    hour = now.hour if now else 0

    if cap and is_trading_weekday(cap):
        # 盤後融合：16:30 後才要求當日 success
        if hour >= 17:
            inc = pipeline_run_status(db_path, today) or pipeline_run_status(db_path, cap)
            if not inc or str(inc.get("status") or "") != "success":
                reasons.append(f"盤後融合 {today} 未成功")
        # 早上海選：06:45 後才要求 screen-{基準日} success（基準日＝06:30 當下庫內完整日）
        # Render data 角色不擁有 morning，pipeline_runs 在 GHA 那份庫，本地查會誤報。
        if hour >= 7:
            from config import scheduler_owns
            from trading_calendar import morning_screen_pipeline_key

            if scheduler_owns("morning"):
                screen_key = morning_screen_pipeline_key(db_path, now=now)
                if not screen_key.endswith("-none"):
                    screen = pipeline_run_status(db_path, screen_key)
                    if not screen or str(screen.get("status") or "") != "success":
                        reasons.append(f"早上海選 {screen_key} 未成功")

    return {"ok": not reasons, "cap": cap, "today": today, "reasons": reasons, "recent": recent[:6]}


def verify_release_snapshot(db_path: str) -> Dict[str, Any]:
    """CI push：Release zip 基本可用（過濾器、庫完整、最近基準日有日K），不要求當日已融合。"""
    path = str(db_path or "").strip()
    reasons: List[str] = []

    filt = quote_filter_regression_ok()
    if not filt.get("ok"):
        reasons.append(str(filt.get("reason") or "過濾器回歸失敗"))

    if not path or not os.path.isfile(path) or not db_quick_check_ok(path, min_bytes=1):
        reasons.append("Release 資料庫損壞或不存在")
    else:
        complete = latest_complete_quote_date(path)
        if not complete:
            reasons.append("沒有上市＋上櫃都齊的基準日")
        else:
            health = audit_import(path, complete)
            if int(health.get("total") or 0) == 0:
                reasons.append(f"基準日 {complete} 日 K 為 0")
            if int(health.get("tw") or 0) == 0 or int(health.get("two") or 0) == 0:
                reasons.append(f"基準日 {complete} 上市或上櫃為 0")
        if not db_quick_check_ok(path) and not complete:
            reasons.append("Release 資料庫過小且無基準日")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "quote_filter": filt,
        "latest_complete": latest_complete_quote_date(path) if path and os.path.isfile(path) else "",
    }


def verify_scheduled_audit(db_path: str, cap: str = None) -> Dict[str, Any]:
    """定時巡檢：當日融合門檻、基準日對齊 cap、排程紀錄。"""
    try:
        from config import fuse_end_date

        cap = str(cap or fuse_end_date() or "").replace("-", "")[:8]
    except Exception:
        cap = str(cap or "").replace("-", "")[:8]

    report = run_automation_audit(db_path, cap=cap, strict_release=False, max_gap_days=999)
    reasons: List[str] = list(report.get("reasons") or [])

    inc = (report.get("checks") or {}).get("increment") or {}
    filt = (report.get("checks") or {}).get("quote_filter") or {}
    if not filt.get("ok"):
        reasons.append("過濾器回歸失敗")
    if not inc.get("ok"):
        for r in inc.get("reasons") or []:
            if r not in reasons:
                reasons.append(str(r))
    if report.get("latest_complete") and cap and report["latest_complete"] < cap:
        msg = f"基準日 {report['latest_complete']} 落後可融合日 {cap}"
        if msg not in reasons:
            reasons.append(msg)

    return {
        "ok": not reasons,
        "cap": cap,
        "latest_complete": report.get("latest_complete") or "",
        "reasons": reasons,
        "report": report,
    }


def health_payload(db_path: str = None, cap: str = None) -> Dict[str, Any]:
    """給 /health 的輕量資料狀態（程序仍回 200，data_ok 反映資料管線）。"""
    try:
        from config import fuse_end_date, get_db_path

        path = db_path or get_db_path()
        cap = cap or fuse_end_date()
    except Exception:
        path = os.getenv("WAYNE_DB_PATH") or "data/wayne_market.db"
        cap = ""

    audit = run_automation_audit(path, cap=cap, strict_release=False, max_gap_days=999)
    pipeline = pipeline_expectations_met(path, cap=cap) if audit.get("checks", {}).get("database", {}).get("ok") else {}
    data_ok = bool(audit.get("ok")) and bool(pipeline.get("ok", True))
    return {
        "status": "healthy",
        "service": "WayneBot 24H Online",
        "ok": True,
        "data_ok": data_ok,
        "cap": audit.get("cap") or "",
        "latest_complete": audit.get("latest_complete") or "",
        "reasons": list(audit.get("reasons") or []) + list(pipeline.get("reasons") or []),
    }


def run_automation_audit(
    db_path: str,
    cap: str = None,
    *,
    strict_release: bool = False,
    max_gap_days: int = 0,
) -> Dict[str, Any]:
    """全面巡檢資料自動化管線，回傳 ok=False 時 reasons 列出具體問題。"""
    try:
        from config import fuse_end_date
    except Exception:
        fuse_end_date = lambda: ""  # type: ignore

    cap = str(cap or fuse_end_date() or "").replace("-", "")[:8]
    reasons: List[str] = []
    checks: Dict[str, Any] = {}

    path = str(db_path or "").strip()
    db_ok = bool(path and os.path.isfile(path) and db_quick_check_ok(path, min_bytes=1))
    prod_db_ok = bool(db_ok and db_quick_check_ok(path))
    checks["database"] = {"ok": db_ok, "production_size": prod_db_ok, "path": path}
    if not db_ok:
        reasons.append("資料庫損壞或不存在")
    elif strict_release and not prod_db_ok:
        reasons.append("資料庫過小，非正式 Release 規模")

    filt = quote_filter_regression_ok()
    checks["quote_filter"] = filt
    if not filt.get("ok"):
        reasons.append(str(filt.get("reason") or "行情過濾器回歸失敗"))

    if db_ok:
        try:
            from db_migrations import schema_health

            schema = schema_health(path)
        except Exception as exc:
            schema = {"ok": False, "reasons": [str(exc)]}
        checks["schema"] = schema
        if not schema.get("ok"):
            for r in schema.get("reasons") or []:
                if r not in reasons:
                    reasons.append(f"schema：{r}")

    health: Dict[str, Any] = {}
    increment: Dict[str, Any] = {}
    if db_ok and cap:
        # 巡檢工具在庫壞掉時直接拋例外的話，正好在最需要它的時候沒有輸出。
        try:
            increment = verify_increment_import(path, cap=cap)
        except Exception as exc:
            increment = {"ok": False, "reasons": [f"增量檢查無法執行：{exc}"]}
        checks["increment"] = increment
        if not increment.get("ok"):
            for r in increment.get("reasons") or []:
                if r not in reasons:
                    reasons.append(str(r))
        health = increment.get("health") or {}
        if not health:
            try:
                health = audit_import(path, cap)
            except Exception as exc:
                health = {"error": str(exc)}

    def _guard(label, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            note = f"{label}無法執行：{exc}"
            if note not in reasons:
                reasons.append(note)
            return fallback

    complete = _guard("基準日查詢", lambda: latest_complete_quote_date(path), None) if db_ok else None
    checks["latest_complete"] = complete
    checks["cap"] = cap
    if db_ok and cap and complete != cap:
        reasons.append(f"基準日 {complete or '無'} 未對齊可融合日 {cap}")

    gaps = _guard("缺口查詢", lambda: list_coverage_issues(path), []) if db_ok else []
    checks["gap_n"] = len(gaps)
    if db_ok and int(max_gap_days or 0) >= 0 and gaps:
        if max_gap_days == 0 and gaps:
            reasons.append(f"歷史日K缺口 {len(gaps)} 日")
        elif len(gaps) > max_gap_days:
            reasons.append(f"歷史日K缺口 {len(gaps)} 日（>{max_gap_days}）")

    release: Dict[str, Any] = {}
    if db_ok:
        release = _guard(
            "Release 檢查",
            lambda: can_publish_release(path, cap=cap) if cap else can_publish_release(path),
            {},
        )
        checks["release"] = {"ok": bool(release.get("ok")), "reasons": release.get("reasons") or []}
        if strict_release and not release.get("ok"):
            for r in release.get("reasons") or []:
                if r not in reasons:
                    reasons.append(str(r))
        pipeline = _guard(
            "排程期望檢查", lambda: pipeline_expectations_met(path, cap=cap), {"ok": True, "skipped": True}
        )
        checks["pipeline"] = pipeline
        if not pipeline.get("ok") and not pipeline.get("skipped"):
            for r in pipeline.get("reasons") or []:
                if r not in reasons:
                    reasons.append(str(r))

    return {
        "ok": not reasons,
        "cap": cap,
        "latest_complete": complete or "",
        "reasons": reasons,
        "checks": checks,
        "health": health,
        "release": release,
    }


def format_automation_audit_plain(report: Dict[str, Any]) -> str:
    lines = [
        f"自動化巡檢 cap={report.get('cap')} 基準日={report.get('latest_complete') or '無'}",
    ]
    health = report.get("health") or {}
    if health:
        lines.append(
            f"日K 上市{health.get('tw')} 上櫃{health.get('two')} 合計{health.get('total')} 法人非0 {health.get('chips_nonzero')}"
        )
    filt = (report.get("checks") or {}).get("quote_filter") or {}
    lines.append(f"過濾器回歸 {'OK' if filt.get('ok') else 'FAIL'}")
    gap_n = (report.get("checks") or {}).get("gap_n")
    if gap_n:
        lines.append(f"歷史缺口 {gap_n} 日")
    if report.get("reasons"):
        lines.append("問題：" + "；".join(report["reasons"]))
    else:
        lines.append("自動化管線正常。")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    strict = "--strict-release" in argv
    if "--strict-release" in argv:
        argv.remove("--strict-release")
    try:
        from config import fuse_end_date, get_db_path

        db_path = get_db_path()
        cap = fuse_end_date()
    except Exception:
        db_path = os.getenv("WAYNE_DB_PATH") or "data/wayne_market.db"
        cap = ""

    if "--json" in argv:
        argv.remove("--json")
        as_json = True
    else:
        as_json = False

    report = run_automation_audit(db_path, cap=cap, strict_release=strict)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_automation_audit_plain(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
