# -*- coding: utf-8 -*-
"""話筒步驟狀態落盤：Render 重開後偉權／哥哥各自接續。

只存 pending 目的字串＋飆大短對話；暫態訊息 id／出圖鎖不落盤。
按人（actor_key＝chat_id:uid）分開；回主選單清自己那一列。
進 PRIVATE_USER_TABLES，不准進公開 zip。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
TABLE = "tg_actor_pending"
# 超過就當過期，避免半年前的連買精靈突然接上
TTL_HOURS = 72
_HIST_CAP = 12


def uid_from_actor(actor: str) -> str:
    s = str(actor or "").strip()
    if ":" in s:
        return s.rsplit(":", 1)[-1].strip()
    return s


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_tg_pending_table(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                actor_key TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                hist_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_uid ON {TABLE}(user_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _parse_ts(raw: str) -> Optional[datetime]:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI)


def _fresh(updated_at: str) -> bool:
    dt = _parse_ts(updated_at)
    if dt is None:
        return False
    return datetime.now(TAIPEI) - dt <= timedelta(hours=TTL_HOURS)


def _clip_hist(hist: Any) -> List[Any]:
    rows = list(hist or []) if isinstance(hist, (list, tuple)) else []
    return rows[-_HIST_CAP:]


def save_actor_pending(
    db_path: str,
    actor: str,
    purpose: str,
    *,
    hist: Optional[List[Any]] = None,
    keep_hist: bool = True,
) -> None:
    """寫入／更新一步。hist=None 且 keep_hist＝保留庫內舊對話。"""
    actor = str(actor or "").strip()
    if not db_path or not actor:
        return
    ensure_tg_pending_table(db_path)
    purpose = str(purpose or "").strip()
    uid = uid_from_actor(actor)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        if hist is not None:
            hist_json = json.dumps(_clip_hist(hist), ensure_ascii=False)
        elif keep_hist:
            row = conn.execute(
                f"SELECT hist_json FROM {TABLE} WHERE actor_key=?",
                (actor,),
            ).fetchone()
            hist_json = str(row[0] if row else "[]") or "[]"
        else:
            hist_json = "[]"
        if not purpose and hist_json in ("", "[]"):
            conn.execute(f"DELETE FROM {TABLE} WHERE actor_key=?", (actor,))
        else:
            conn.execute(
                f"""
                INSERT INTO {TABLE}(actor_key, user_id, purpose, hist_json, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(actor_key) DO UPDATE SET
                    user_id=excluded.user_id,
                    purpose=excluded.purpose,
                    hist_json=excluded.hist_json,
                    updated_at=excluded.updated_at
                """,
                (actor, uid, purpose, hist_json, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def save_actor_hist(db_path: str, actor: str, hist: List[Any]) -> None:
    """只更新飆大短對話，保留既有 purpose。"""
    actor = str(actor or "").strip()
    if not db_path or not actor:
        return
    ensure_tg_pending_table(db_path)
    purpose = ""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            f"SELECT purpose FROM {TABLE} WHERE actor_key=?",
            (actor,),
        ).fetchone()
        if row:
            purpose = str(row[0] or "")
        hist_json = json.dumps(_clip_hist(hist), ensure_ascii=False)
        if not purpose and hist_json == "[]":
            conn.execute(f"DELETE FROM {TABLE} WHERE actor_key=?", (actor,))
        else:
            conn.execute(
                f"""
                INSERT INTO {TABLE}(actor_key, user_id, purpose, hist_json, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(actor_key) DO UPDATE SET
                    user_id=excluded.user_id,
                    hist_json=excluded.hist_json,
                    updated_at=excluded.updated_at
                """,
                (actor, uid_from_actor(actor), purpose, hist_json, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def clear_actor_pending(db_path: str, actor: str) -> None:
    actor = str(actor or "").strip()
    if not db_path or not actor:
        return
    ensure_tg_pending_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(f"DELETE FROM {TABLE} WHERE actor_key=?", (actor,))
        conn.commit()
    finally:
        conn.close()


def load_actor_pending(db_path: str, actor: str) -> Tuple[str, List[Any]]:
    """回 (purpose, hist)。過期或不存在 → ('', [])。"""
    actor = str(actor or "").strip()
    if not db_path or not actor:
        return "", []
    ensure_tg_pending_table(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            f"SELECT purpose, hist_json, updated_at FROM {TABLE} WHERE actor_key=?",
            (actor,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return "", []
    purpose, hist_json, updated_at = (
        str(row[0] or ""),
        str(row[1] or "[]"),
        str(row[2] or ""),
    )
    if not _fresh(updated_at):
        clear_actor_pending(db_path, actor)
        return "", []
    try:
        hist = json.loads(hist_json) if hist_json else []
    except json.JSONDecodeError:
        hist = []
    if not isinstance(hist, list):
        hist = []
    return purpose, _clip_hist(hist)


class PendingMap(dict):
    """記憶體 pending；寫入／刪除同步落盤；讀 miss 時從庫補。"""

    def __init__(self, db_path: str, hist_map: Optional[Dict[str, list]] = None):
        super().__init__()
        self._db = str(db_path or "")
        self._hist = hist_map
        self._busy = False

    def _hydrate(self, key: str) -> None:
        if not self._db or key in self or self._busy:
            return
        self._busy = True
        try:
            purpose, hist = load_actor_pending(self._db, key)
            if purpose:
                super().__setitem__(key, purpose)
            if self._hist is not None and hist and key not in self._hist:
                # 直接寫底層，避免再觸發 hist 落盤迴圈
                dict.__setitem__(self._hist, key, list(hist))
        finally:
            self._busy = False

    def __getitem__(self, key):
        self._hydrate(str(key))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._hydrate(str(key))
        return super().get(key, default)

    def __setitem__(self, key, value):
        k = str(key)
        v = str(value or "")
        super().__setitem__(k, v)
        if self._busy or not self._db:
            return
        try:
            hist = None
            if self._hist is not None and k in self._hist:
                hist = list(self._hist.get(k) or [])
            save_actor_pending(self._db, k, v, hist=hist, keep_hist=hist is None)
        except Exception:
            pass

    def __delitem__(self, key):
        k = str(key)
        super().__delitem__(k)
        if self._busy or not self._db:
            return
        try:
            clear_actor_pending(self._db, k)
            if self._hist is not None:
                self._hist.pop(k, None)
        except Exception:
            pass

    def pop(self, key, *args):
        k = str(key)
        self._hydrate(k)
        if k not in self:
            if args:
                return args[0]
            raise KeyError(k)
        val = super().pop(k)
        if not self._busy and self._db:
            try:
                clear_actor_pending(self._db, k)
                if self._hist is not None:
                    dict.pop(self._hist, k, None)
            except Exception:
                pass
        return val

    def clear(self):
        keys = list(self.keys())
        super().clear()
        if self._busy or not self._db:
            return
        for k in keys:
            try:
                clear_actor_pending(self._db, k)
            except Exception:
                pass


class BiaokeHistMap(dict):
    """飆大短對話；與 pending 同一列。"""

    def __init__(self, db_path: str, pending_map: Optional[PendingMap] = None):
        super().__init__()
        self._db = str(db_path or "")
        self._pending = pending_map
        self._busy = False

    def _hydrate(self, key: str) -> None:
        if not self._db or key in self or self._busy:
            return
        self._busy = True
        try:
            purpose, hist = load_actor_pending(self._db, key)
            if hist:
                super().__setitem__(key, list(hist))
            if self._pending is not None and purpose and key not in self._pending:
                dict.__setitem__(self._pending, key, purpose)
        finally:
            self._busy = False

    def __getitem__(self, key):
        self._hydrate(str(key))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._hydrate(str(key))
        return super().get(key, default)

    def setdefault(self, key, default=None):
        self._hydrate(str(key))
        if key in self:
            return self[key]
        self[key] = default if default is not None else []
        return self[key]

    def __setitem__(self, key, value):
        k = str(key)
        rows = _clip_hist(value)
        super().__setitem__(k, rows)
        if self._busy or not self._db:
            return
        try:
            save_actor_hist(self._db, k, rows)
        except Exception:
            pass

    def pop(self, key, *args):
        k = str(key)
        self._hydrate(k)
        if k not in self:
            if args:
                return args[0]
            raise KeyError(k)
        val = super().pop(k)
        if not self._busy and self._db:
            try:
                # 清對話但若還在飆大窗，保留 purpose
                purpose = ""
                if self._pending is not None:
                    purpose = str(dict.get(self._pending, k, "") or "")
                if purpose:
                    save_actor_pending(self._db, k, purpose, hist=[], keep_hist=False)
                else:
                    clear_actor_pending(self._db, k)
            except Exception:
                pass
        return val
