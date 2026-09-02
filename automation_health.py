# -*- coding: utf-8 -*-
"""自動化資料管線巡檢：回傳、彙整、融合各環節，問題由系統先發現。"""
from __future__ import annotations

import json
import os
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
    """過濾器煙霧：正常 K 必須通過，假 K 必須擋下。"""
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
    bad = (
        "20260902",
        "2454",
        "聯發科",
        "TW",
        4315.0,
        4315.0,
        4315.0,
        4315.0,
        4931,
        42.0,
        9.94,
        4315.0,
        0,
        0,
        0,
    )
    kept, dropped = filter_trusted_quote_tuples([good, bad])
    ok = len(kept) == 1 and kept[0][1] == "2330" and dropped >= 1
    return {
        "ok": ok,
        "kept": len(kept),
        "dropped": dropped,
        "reason": "" if ok else "過濾器回歸失敗：正常 K 未通過或假 K 未擋下",
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

    health: Dict[str, Any] = {}
    increment: Dict[str, Any] = {}
    if db_ok and cap:
        increment = verify_increment_import(path, cap=cap)
        checks["increment"] = increment
        if not increment.get("ok"):
            for r in increment.get("reasons") or []:
                if r not in reasons:
                    reasons.append(str(r))
        health = increment.get("health") or audit_import(path, cap)

    complete = latest_complete_quote_date(path) if db_ok else None
    checks["latest_complete"] = complete
    checks["cap"] = cap
    if db_ok and cap and complete != cap:
        reasons.append(f"基準日 {complete or '無'} 未對齊可融合日 {cap}")

    gaps = list_coverage_issues(path) if db_ok else []
    checks["gap_n"] = len(gaps)
    if db_ok and int(max_gap_days or 0) >= 0 and gaps:
        if max_gap_days == 0 and gaps:
            reasons.append(f"歷史日K缺口 {len(gaps)} 日")
        elif len(gaps) > max_gap_days:
            reasons.append(f"歷史日K缺口 {len(gaps)} 日（>{max_gap_days}）")

    release: Dict[str, Any] = {}
    if db_ok:
        release = can_publish_release(path, cap=cap) if cap else can_publish_release(path)
        checks["release"] = {"ok": bool(release.get("ok")), "reasons": release.get("reasons") or []}
        if strict_release and not release.get("ok"):
            for r in release.get("reasons") or []:
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
