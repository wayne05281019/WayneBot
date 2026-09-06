# -*- coding: utf-8 -*-
"""話筒「回報」：家人／偉權把狀況或截圖留下來，方便之後對照修正。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tg_issue_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    body TEXT DEFAULT '',
    photo_file_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def ensure_issue_reports_table(db_path: str) -> None:
    """建表必須用獨立 sqlite 連線：init_database 內部已拿著 DB_LOCK。"""
    parent = os.path.dirname(str(db_path) or "")
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def _jsonl_path(db_path: str) -> str:
    root = os.path.dirname(os.path.abspath(str(db_path) or "")) or "data"
    return os.path.join(root, "issue_reports.jsonl")


def save_issue_report(
    db_path: str,
    user_id: str,
    *,
    display_name: str = "",
    body: str = "",
    photo_file_id: str = "",
) -> Dict[str, Any]:
    """寫進庫＋旁邊一份 jsonl（給之後對帳）。空內容不寫。"""
    uid = str(user_id or "").strip()
    text = str(body or "").strip()
    photo = str(photo_file_id or "").strip()
    name = str(display_name or "").strip()
    if not uid:
        raise ValueError("missing user_id")
    if not text and not photo:
        raise ValueError("empty report")
    if len(text) > 4000:
        text = text[:4000] + "…"
    ensure_issue_reports_table(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            INSERT INTO tg_issue_reports (user_id, display_name, body, photo_file_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uid, name, text, photo, now),
        )
        rid = int(cur.lastrowid or 0)
        conn.commit()
    finally:
        conn.close()
    rec = {
        "id": rid,
        "user_id": uid,
        "display_name": name,
        "body": text,
        "photo_file_id": photo,
        "created_at": now,
    }
    if db_path and db_path != ":memory:":
        try:
            os.makedirs(os.path.dirname(_jsonl_path(db_path)) or ".", exist_ok=True)
            with open(_jsonl_path(db_path), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return rec


def list_recent_issue_reports(db_path: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_issue_reports_table(db_path)
    n = max(1, min(int(limit or 20), 100))
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, user_id, display_name, body, photo_file_id, created_at
            FROM tg_issue_reports
            ORDER BY id DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def format_owner_notice_html(rec: Dict[str, Any]) -> str:
    from tg_layout import html_escape

    name = rec.get("display_name") or "未留名"
    uid = rec.get("user_id") or ""
    body = rec.get("body") or "（只有截圖）"
    rid = rec.get("id") or "?"
    when = rec.get("created_at") or ""
    extra = "\n附截圖" if rec.get("photo_file_id") else ""
    return (
        f"<b>話筒回報</b> #{html_escape(rid)}\n"
        f"{html_escape(when)}\n"
        f"來自 {html_escape(name)} <code>{html_escape(uid)}</code>{extra}\n"
        f"{html_escape(body)}"
    )
