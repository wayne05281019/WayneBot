#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旁路：從 biaoke_posts 回補「現況位階」口語樣本並對質。

硬邊界：
- 不渲每則 PNG（碟會滿；圖要看時再從柱渲）
- 不推話筒、不改黃金買點／海選／洞燭
- 已有 verdict 的列不准洗掉重算
- 時區 Asia/Taipei；空代號／空文不算
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biaoke_level_learn import (  # noqa: E402
    _mark_verdict,
    _score_against_next,
    _ymd,
    ensure_tables,
    looks_like_level_now,
)

OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")
DEFAULT_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))


def _now() -> str:
    return datetime.now(TP).isoformat()


def _load_levelish(db_path: Path) -> List[Dict[str, str]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id, date, time, text FROM biaoke_posts ORDER BY date, time, id"
        ).fetchall()
    finally:
        con.close()
    out: List[Dict[str, str]] = []
    for pid, d, t, text in rows:
        blob = str(text or "")
        if not looks_like_level_now(blob):
            continue
        pid_s = str(pid or "").strip()
        if not pid_s:
            continue
        snip = re.sub(r"\s+", " ", blob).strip()[:400]
        if not snip:
            continue
        out.append(
            {
                "post_id": pid_s,
                "as_of": _ymd(d) or "",
                "post_date": str(d or ""),
                "post_time": str(t or ""),
                "snippet": snip,
            }
        )
    return out


def _existing_map(db_path: Path) -> Dict[str, Dict[str, Any]]:
    ensure_tables(str(db_path))
    con = sqlite3.connect(str(db_path), timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT post_id, pending, verdict FROM biaoke_level_snaps").fetchall()
        return {str(r["post_id"]): dict(r) for r in rows}
    finally:
        con.close()


def insert_missing_snaps(db_path: Path, items: List[Dict[str, str]]) -> Dict[str, int]:
    """只插入尚未有列的位階文；chart_path 留空。不准洗掉已判決。"""
    ensure_tables(str(db_path))
    have = _existing_map(db_path)
    inserted = skipped = 0
    con = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        for it in items:
            pid = it["post_id"]
            if pid in have:
                skipped += 1
                continue
            con.execute(
                """
                INSERT INTO biaoke_level_snaps(
                    post_id, as_of, post_date, post_time, snippet, chart_path,
                    pending, created_at
                ) VALUES (?,?,?,?,?,'',1,?)
                """,
                (
                    pid,
                    it.get("as_of") or "",
                    it.get("post_date") or "",
                    it.get("post_time") or "",
                    it.get("snippet") or "",
                    _now(),
                ),
            )
            inserted += 1
            have[pid] = {"post_id": pid, "pending": 1, "verdict": ""}
        con.commit()
    finally:
        con.close()
    return {"inserted": inserted, "skipped_existing": skipped, "levelish": len(items)}


def verify_all_chronological(db_path: Path) -> Dict[str, int]:
    """依時間序：後文對前文 pending 粗評；已有對／偏不重寫。"""
    ensure_tables(str(db_path))
    con = sqlite3.connect(str(db_path), timeout=60.0)
    con.row_factory = sqlite3.Row
    try:
        rows = [
            dict(r)
            for r in con.execute(
                "SELECT post_id, as_of, post_date, post_time, snippet, pending, verdict "
                "FROM biaoke_level_snaps "
                "ORDER BY as_of ASC, post_date ASC, post_time ASC, post_id ASC"
            ).fetchall()
        ]
    finally:
        con.close()

    marked = 0
    still_pending = 0
    for i, cur in enumerate(rows):
        snip = str(cur.get("snippet") or "")
        pid = str(cur.get("post_id") or "")
        if not pid or not snip:
            continue
        # 用本則去對更早的 pending
        for prev in rows[:i]:
            if int(prev.get("pending") or 0) != 1:
                continue
            if str(prev.get("verdict") or "") in ("對", "偏"):
                continue
            ppid = str(prev.get("post_id") or "")
            if not ppid or ppid == pid:
                continue
            verdict = _score_against_next(str(prev.get("snippet") or ""), snip)
            if verdict == "還沒走完":
                continue
            _mark_verdict(str(db_path), ppid, verdict, next_post_id=pid)
            prev["pending"] = 0
            prev["verdict"] = verdict
            marked += 1

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        still_pending = int(
            con.execute("SELECT COUNT(*) FROM biaoke_level_snaps WHERE pending=1").fetchone()[0]
        )
        verdicts = dict(
            con.execute(
                "SELECT IFNULL(verdict,''), COUNT(*) FROM biaoke_level_snaps GROUP BY IFNULL(verdict,'')"
            ).fetchall()
        )
        n_days = int(
            con.execute(
                "SELECT COUNT(DISTINCT as_of) FROM biaoke_level_snaps WHERE as_of!=''"
            ).fetchone()[0]
        )
        decided_days = int(
            con.execute(
                "SELECT COUNT(DISTINCT as_of) FROM biaoke_level_snaps "
                "WHERE verdict IN ('對','偏') AND as_of!=''"
            ).fetchone()[0]
        )
    finally:
        con.close()
    return {
        "marked": marked,
        "still_pending": still_pending,
        "verdicts": verdicts,
        "n_days": n_days,
        "n_decided_days": decided_days,
    }


def diverge_tick(db_path: Path) -> Dict[str, Any]:
    """順便覆盤分軌 pending（不上話筒）。"""
    from biaoke_diverge import night_tick, optimize_status_one_liner

    tick = night_tick(str(db_path))
    return {
        "scored": tick.get("scored"),
        "promoted": tick.get("promoted"),
        "gate_n_ok": (tick.get("gate") or {}).get("n_ok"),
        "promote_ready": (tick.get("gate") or {}).get("promote_ready"),
        "one_liner": optimize_status_one_liner(str(db_path)),
    }


def write_lab_summary(payload: Dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TP).strftime("%Y%m%d")
    path = OUT_DIR / f"biaoke_level_sample_{stamp}.json"
    latest = OUT_DIR / "biaoke_level_sample_latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    md = [
        "# 飆大位階口語樣本回補（旁路）",
        "",
        f"寫入：`{payload.get('written_at')}`（Asia/Taipei）。",
        f"levelish 文 n={payload.get('insert',{}).get('levelish')}；新插入={payload.get('insert',{}).get('inserted')}；已有跳過={payload.get('insert',{}).get('skipped_existing')}。",
        f"對質新標={payload.get('verify',{}).get('marked')}；仍 pending={payload.get('verify',{}).get('still_pending')}。",
        f"位階軌獨立日 n_days={payload.get('verify',{}).get('n_days')}；已判決日 n={payload.get('verify',{}).get('n_decided_days')}。",
        "",
        "不渲 PNG、不推話筒、不改買訊。分軌（diverge）狀態見 one_liner。",
        "",
        f"- diverge：{payload.get('diverge',{}).get('one_liner')}",
        f"- promote_ready={payload.get('diverge',{}).get('promote_ready')}",
        "",
        "不是買訊。",
        "",
    ]
    (OUT_DIR / "biaoke_level_sample_latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return latest


def main() -> int:
    db = DEFAULT_DB
    if not db.is_file():
        print(json.dumps({"ok": False, "error": f"missing db {db}"}, ensure_ascii=False))
        return 1
    os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
    items = _load_levelish(db)
    ins = insert_missing_snaps(db, items)
    ver = verify_all_chronological(db)
    div = diverge_tick(db)
    payload = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "not_buy_signal": True,
        "no_phone_push": True,
        "no_png": True,
        "insert": ins,
        "verify": ver,
        "diverge": div,
        "gate_note": {
            "level_snaps": "位階口語軌：獨立判決日往 n≥20 收；未過閘不改話筒編碼",
            "diverge": div.get("one_liner"),
        },
    }
    path = write_lab_summary(payload)
    print(json.dumps({"ok": True, "summary": str(path.relative_to(ROOT)), **ins, **{f"v_{k}": ver[k] for k in ("marked", "still_pending", "n_days", "n_decided_days")}, "promote_ready": div.get("promote_ready")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
