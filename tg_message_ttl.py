"""Telegram 話筒顯示 TTL：Bot 自己寄出的訊息超過約 24h 自動 deleteMessage。

使用者鎖死（2026-10-26）：
- 只刪 Bot 自己寄出的（偉權＋哥哥兩 chat 同一規則）
- TTL＝24h（Asia/Taipei 用 epoch）
- 寄出時落檔 message_id；缺歷史 id 的舊訊無法回溯＝可接受
- 節流：不准一次狂刪打爆 API；失敗可重試／略過，不准擋住查股
- 不准刪使用者自己打的字；不准動 Render 碟官方柱／私人本／默默落檔
  （那是 disk_guard 另一條：碟暫存 24h＋午夜）
- 進行中 LOADING／pending／busy_window 綁定的訊息：未完成前不要誤刪；
  完成後仍走既有魔法消逝
- 早報／海選推播／查股圖／飆大回文：超過 24h 都可清
- 不准跟排程／重活／其他原始功能互搶造成崩潰：busy 或重鐘點整輪略過；
  失敗只略過；不改排程編碼、不碰官方柱／私人本

本模組只管「Telegram 顯示」；與 disk_guard 碟暫存分開。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("WayneBot.tg_message_ttl")

DEFAULT_TTL_SEC = 24 * 60 * 60
DEFAULT_INTERVAL_SEC = 15 * 60
DEFAULT_MAX_PER_RUN = 24
DEFAULT_SLEEP_SEC = 0.45
DEFAULT_MAX_FAILS = 5

TABLE = "tg_bot_outbound"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    chat_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    sent_at REAL NOT NULL,
    protect INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT '',
    fail_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_tg_bot_outbound_sent
    ON {TABLE}(sent_at);
"""

_started = False
_lock = threading.Lock()
_hooked_bots: Set[int] = set()

# PTB Bot 寄出方法：reply_* 最終也走這些。
_SEND_METHODS = (
    "send_message",
    "send_photo",
    "send_document",
    "send_animation",
    "send_video",
    "send_audio",
    "send_voice",
    "send_sticker",
    "send_media_group",
    "send_venue",
    "send_location",
    "send_contact",
    "send_poll",
    "send_dice",
    "copy_message",
)


def _enabled() -> bool:
    raw = (os.getenv("WAYNE_TG_MSG_TTL") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if str(os.getenv("WAYNE_TG_MSG_TTL_TEST") or "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return False
    return True


def _db_path(db_path: str = "") -> str:
    raw = str(db_path or "").strip()
    if raw:
        return raw
    try:
        from config import get_db_path

        return str(get_db_path() or "").strip()
    except Exception:
        return ""


def _token(token: str = "") -> str:
    raw = str(token or "").strip()
    if raw:
        return raw
    try:
        from config import get_telegram_token

        return str(get_telegram_token() or "").strip()
    except Exception:
        return str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _now_epoch() -> float:
    return float(time.time())


def ensure_table(db_path: str = "") -> str:
    path = _db_path(db_path)
    if not path:
        return ""
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(path, timeout=8.0)
        try:
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()
        return path
    except Exception:
        logger.debug("tg_bot_outbound 建表略過", exc_info=True)
        return ""


def record_outbound(
    chat_id: Any,
    message_id: Any,
    *,
    db_path: str = "",
    protect: bool = False,
    kind: str = "",
    sent_at: Optional[float] = None,
) -> bool:
    """寄出成功後落檔。失敗只 debug，不准擋查股／推播。"""
    if not _enabled():
        return False
    try:
        cid = str(chat_id or "").strip()
        mid = int(message_id or 0)
    except (TypeError, ValueError):
        return False
    if not cid or mid <= 0:
        return False
    path = ensure_table(db_path)
    if not path:
        return False
    stamp = float(sent_at) if sent_at is not None else _now_epoch()
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            conn.execute(
                f"""
                INSERT INTO {TABLE}(chat_id, message_id, sent_at, protect, kind, fail_count)
                VALUES (?,?,?,?,?,0)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                  sent_at=excluded.sent_at,
                  protect=MAX({TABLE}.protect, excluded.protect),
                  kind=CASE
                    WHEN excluded.kind!='' THEN excluded.kind
                    ELSE {TABLE}.kind
                  END
                """,
                (cid, mid, stamp, 1 if protect else 0, str(kind or "")[:64]),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        logger.debug("tg outbound 落檔略過", exc_info=True)
        return False


def record_from_api_result(
    result: Any,
    *,
    chat_id: Any = None,
    db_path: str = "",
    protect: bool = False,
    kind: str = "",
) -> int:
    """從 Telegram API JSON／Message 物件抽出 message_id 並落檔。回傳寫入筆數。"""
    n = 0
    if result is None:
        return 0
    # requests JSON: {"ok": true, "result": {...}} 或 result 本體
    if isinstance(result, dict):
        body = result.get("result") if "ok" in result or "result" in result else result
        if isinstance(body, list):
            for item in body:
                n += record_from_api_result(
                    item, chat_id=chat_id, db_path=db_path, protect=protect, kind=kind
                )
            return n
        if isinstance(body, dict):
            mid = body.get("message_id")
            cid = chat_id
            if cid is None:
                chat = body.get("chat") or {}
                if isinstance(chat, dict):
                    cid = chat.get("id")
                else:
                    cid = getattr(chat, "id", None)
            if record_outbound(cid, mid, db_path=db_path, protect=protect, kind=kind):
                n += 1
            return n
    # PTB Message / list of Message
    if isinstance(result, (list, tuple)):
        for item in result:
            n += record_from_api_result(
                item, chat_id=chat_id, db_path=db_path, protect=protect, kind=kind
            )
        return n
    mid = getattr(result, "message_id", None)
    cid = chat_id
    if cid is None:
        chat = getattr(result, "chat", None)
        cid = getattr(chat, "id", None) if chat is not None else None
        if cid is None:
            cid = getattr(result, "chat_id", None)
    if record_outbound(cid, mid, db_path=db_path, protect=protect, kind=kind):
        n += 1
    return n


def protect_message(
    chat_id: Any, message_id: Any, *, db_path: str = "", kind: str = "loading"
) -> None:
    """進行中 LOADING／pending：標 protect，purge 跳過。"""
    if not _enabled():
        return
    try:
        cid = str(chat_id or "").strip()
        mid = int(message_id or 0)
    except (TypeError, ValueError):
        return
    if not cid or mid <= 0:
        return
    path = ensure_table(db_path)
    if not path:
        return
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            row = conn.execute(
                f"SELECT 1 FROM {TABLE} WHERE chat_id=? AND message_id=?",
                (cid, mid),
            ).fetchone()
            if row:
                conn.execute(
                    f"UPDATE {TABLE} SET protect=1, kind=? WHERE chat_id=? AND message_id=?",
                    (str(kind or "loading")[:64], cid, mid),
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO {TABLE}(chat_id, message_id, sent_at, protect, kind, fail_count)
                    VALUES (?,?,?,?,?,0)
                    """,
                    (cid, mid, _now_epoch(), 1, str(kind or "loading")[:64]),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("tg outbound protect 略過", exc_info=True)


def unprotect_message(chat_id: Any, message_id: Any, *, db_path: str = "") -> None:
    """魔法消逝／完成後解除；訊息本身由既有路徑刪，這裡只放行 TTL。"""
    try:
        cid = str(chat_id or "").strip()
        mid = int(message_id or 0)
    except (TypeError, ValueError):
        return
    if not cid or mid <= 0:
        return
    path = _db_path(db_path)
    if not path or not os.path.isfile(path):
        return
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            conn.execute(
                f"UPDATE {TABLE} SET protect=0 WHERE chat_id=? AND message_id=?",
                (cid, mid),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("tg outbound unprotect 略過", exc_info=True)


def forget_outbound(chat_id: Any, message_id: Any, *, db_path: str = "") -> None:
    """已成功 deleteMessage 時從表拿掉，避免重試。"""
    try:
        cid = str(chat_id or "").strip()
        mid = int(message_id or 0)
    except (TypeError, ValueError):
        return
    if not cid or mid <= 0:
        return
    path = _db_path(db_path)
    if not path or not os.path.isfile(path):
        return
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            conn.execute(
                f"DELETE FROM {TABLE} WHERE chat_id=? AND message_id=?",
                (cid, mid),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.debug("tg outbound forget 略過", exc_info=True)


def _protected_pairs(db_path: str) -> Set[Tuple[str, int]]:
    """進行中不准刪：tg_progress_orphans＋busy_window 進行中。"""
    out: Set[Tuple[str, int]] = set()
    path = _db_path(db_path)
    if path and os.path.isfile(path):
        try:
            conn = sqlite3.connect(path, timeout=5.0)
            try:
                names = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "tg_progress_orphans" in names:
                    for row in conn.execute(
                        "SELECT chat_id, message_id FROM tg_progress_orphans"
                    ).fetchall():
                        try:
                            out.add((str(row[0]), int(row[1])))
                        except (TypeError, ValueError):
                            continue
            finally:
                conn.close()
        except Exception:
            logger.debug("讀 progress orphans 略過", exc_info=True)
    try:
        from busy_window_notice import active_message_pairs

        for cid, mid in active_message_pairs(db_path=path) or []:
            try:
                out.add((str(cid), int(mid)))
            except (TypeError, ValueError):
                continue
    except Exception:
        # 相容舊版 busy_window_notice（尚未加 helper）
        try:
            import busy_window_notice as bwn

            with bwn._lock:
                for msgs in (bwn._active or {}).values():
                    if not isinstance(msgs, dict):
                        continue
                    for cid, mid in msgs.items():
                        try:
                            out.add((str(cid), int(mid)))
                        except (TypeError, ValueError):
                            continue
            path_state = bwn._state_path(path)
            data = bwn._load_file(path_state)
            raw = (data or {}).get("messages") or {}
            if isinstance(raw, dict):
                for cid, mid in raw.items():
                    try:
                        out.add((str(cid), int(mid)))
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass
    return out


def list_expired(
    *,
    db_path: str = "",
    ttl_sec: float = DEFAULT_TTL_SEC,
    now: Optional[float] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    path = ensure_table(db_path)
    if not path:
        return []
    cutoff = float(now if now is not None else _now_epoch()) - float(ttl_sec)
    try:
        conn = sqlite3.connect(path, timeout=8.0)
        try:
            rows = conn.execute(
                f"""
                SELECT chat_id, message_id, sent_at, protect, kind, fail_count
                FROM {TABLE}
                WHERE sent_at <= ? AND protect=0 AND fail_count < ?
                ORDER BY sent_at ASC
                LIMIT ?
                """,
                (cutoff, int(DEFAULT_MAX_FAILS), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        logger.debug("list_expired 略過", exc_info=True)
        return []
    protected = _protected_pairs(path)
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        cid = str(row[0] or "")
        try:
            mid = int(row[1] or 0)
        except (TypeError, ValueError):
            continue
        if not cid or mid <= 0:
            continue
        if (cid, mid) in protected:
            continue
        out.append(
            {
                "chat_id": cid,
                "message_id": mid,
                "sent_at": float(row[2] or 0),
                "protect": int(row[3] or 0),
                "kind": str(row[4] or ""),
                "fail_count": int(row[5] or 0),
            }
        )
    return out


def _tg_delete(token: str, chat_id: str, message_id: int) -> Dict[str, Any]:
    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": int(message_id)},
            timeout=12,
        )
        if resp is None:
            return {}
        try:
            return resp.json() if resp.content else {}
        except Exception:
            return {"ok": False, "status_code": getattr(resp, "status_code", 0)}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def _bump_fail(db_path: str, chat_id: str, message_id: int) -> None:
    path = _db_path(db_path)
    if not path:
        return
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            conn.execute(
                f"UPDATE {TABLE} SET fail_count=fail_count+1 WHERE chat_id=? AND message_id=?",
                (str(chat_id), int(message_id)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _gone_error(res: Dict[str, Any]) -> bool:
    """訊息已不在／Bot 無權再刪 → 當已清，從表拿掉。"""
    if res.get("ok"):
        return False
    desc = str(res.get("description") or "").lower()
    code = res.get("error_code")
    needles = (
        "message to delete not found",
        "message can't be deleted",
        "message not found",
        "chat not found",
        "bot was blocked",
        "forbidden",
    )
    if any(n in desc for n in needles):
        return True
    if code in (400, 403):
        # 400 多半是已刪；403 無權／被擋。都不要一直重試。
        return True
    return False


# 台北重鐘點（分鐘）：早報／海選尾盤／融合／DC／午夜 disk_guard。
# 整輪略過 purge，不准跟排程或其他原始功能搶 API／碟 IO。
HEAVY_WINDOWS_MINS = (
    (6 * 60 + 25, 7 * 60 + 10),  # 06:30 早報＋海選
    (12 * 60 + 40, 13 * 60 + 10),  # 12:45 尾盤海選
    (16 * 60 + 25, 17 * 60 + 10),  # 16:30 融合
    (3 * 60, 4 * 60 + 10),  # 03:00–04:00 DC
    (23 * 60 + 55, 24 * 60 - 1),  # 23:55–23:59 接午夜 disk_guard
    (0, 14),  # 00:00–00:14 午夜 disk_guard
)


def _mins_in_heavy_window(mins: int) -> bool:
    m = int(mins) % (24 * 60)
    for lo, hi in HEAVY_WINDOWS_MINS:
        if lo <= hi:
            if lo <= m <= hi:
                return True
        else:
            # 跨日窗（若日後需要）
            if m >= lo or m <= hi:
                return True
    return False


def _heavy_window_active(db_path: str = "", *, now_mins: Optional[int] = None) -> bool:
    """重活窗進行中：整輪略過 purge，不准跟早報／海選／融合／DC／disk_guard 搶。"""
    try:
        from busy_window_notice import is_busy_window_active

        if is_busy_window_active(db_path=db_path):
            return True
    except Exception:
        pass
    try:
        if now_mins is not None:
            mins = int(now_mins)
        else:
            from zoneinfo import ZoneInfo
            from datetime import datetime

            now = datetime.now(ZoneInfo("Asia/Taipei"))
            mins = now.hour * 60 + now.minute
        if _mins_in_heavy_window(mins):
            return True
    except Exception:
        pass
    return False


def purge_expired(
    *,
    db_path: str = "",
    token: str = "",
    ttl_sec: float = DEFAULT_TTL_SEC,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    now: Optional[float] = None,
    delete_fn: Optional[Callable[[str, str, int], Dict[str, Any]]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """節流刪過期 Bot 訊。永不 raise 到呼叫端；查股路徑不准等這裡。

    不准跟排程／重活／查股互搶：busy_window 或重鐘點整輪略過（force 僅單測）。
    不改任何排程編碼、不碰官方柱／私人本／默默落檔。
    """
    stats = {
        "scanned": 0,
        "deleted": 0,
        "skipped": 0,
        "failed": 0,
        "forgotten": 0,
        "disabled": 0,
        "deferred": 0,
    }
    if not _enabled():
        stats["disabled"] = 1
        return stats
    path = ensure_table(db_path)
    tok = _token(token)
    if not path:
        return stats
    if not force and _heavy_window_active(path):
        stats["deferred"] = 1
        return stats
    rows = list_expired(
        db_path=path,
        ttl_sec=ttl_sec,
        now=now,
        limit=max(1, int(max_per_run) * 3),
    )
    stats["scanned"] = len(rows)
    if not rows:
        return stats
    if not tok and delete_fn is None:
        # 無 token：本機／CI 只掃不刪，不准假成功。
        stats["skipped"] = len(rows)
        return stats

    budget = max(1, int(max_per_run))
    pause = max(0.05, float(sleep_sec))
    for row in rows:
        if budget <= 0:
            break
        cid = str(row["chat_id"])
        mid = int(row["message_id"])
        # 再查一次 protect／orphan，避免長掃中途變進行中
        if (cid, mid) in _protected_pairs(path):
            stats["skipped"] += 1
            continue
        try:
            if delete_fn is not None:
                res = delete_fn(tok, cid, mid) or {}
            else:
                res = _tg_delete(tok, cid, mid)
        except Exception as exc:
            res = {"ok": False, "description": str(exc)}
        if res.get("ok"):
            forget_outbound(cid, mid, db_path=path)
            stats["deleted"] += 1
            budget -= 1
        elif _gone_error(res):
            forget_outbound(cid, mid, db_path=path)
            stats["forgotten"] += 1
            budget -= 1
        else:
            _bump_fail(path, cid, mid)
            stats["failed"] += 1
            budget -= 1
        try:
            time.sleep(pause)
        except Exception:
            pass
    if stats["deleted"] or stats["forgotten"] or stats["failed"]:
        logger.info(
            "tg_message_ttl purge deleted=%s forgotten=%s failed=%s skipped=%s scanned=%s",
            stats["deleted"],
            stats["forgotten"],
            stats["failed"],
            stats["skipped"],
            stats["scanned"],
        )
    return stats


def install_bot_hooks(bot: Any, *, db_path: str = "") -> bool:
    """包 PTB Bot.send_*：reply_text／reply_photo 也會走到這裡。"""
    if bot is None or not _enabled():
        return False
    bot_id = id(bot)
    with _lock:
        if bot_id in _hooked_bots:
            return False
        _hooked_bots.add(bot_id)
    path = _db_path(db_path)
    ensure_table(path)

    def _wrap(name: str, orig: Callable):
        if getattr(orig, "_wayne_ttl_wrapped", False):
            return orig

        async def _async_wrapped(*args, **kwargs):
            result = await orig(*args, **kwargs)
            try:
                record_from_api_result(result, db_path=path, kind=name)
            except Exception:
                logger.debug("ttl hook record 略過", exc_info=True)
            return result

        def _sync_wrapped(*args, **kwargs):
            result = orig(*args, **kwargs)
            try:
                record_from_api_result(result, db_path=path, kind=name)
            except Exception:
                logger.debug("ttl hook record 略過", exc_info=True)
            return result

        import asyncio
        import inspect

        wrapped = _async_wrapped if inspect.iscoroutinefunction(orig) else _sync_wrapped
        try:
            wrapped._wayne_ttl_wrapped = True  # type: ignore[attr-defined]
            wrapped.__name__ = getattr(orig, "__name__", name)
            wrapped.__qualname__ = getattr(orig, "__qualname__", name)
        except Exception:
            pass
        # 避免未用 asyncio 警告
        _ = asyncio
        return wrapped

    n = 0
    for name in _SEND_METHODS:
        orig = getattr(bot, name, None)
        if orig is None or not callable(orig):
            continue
        if getattr(orig, "_wayne_ttl_wrapped", False):
            continue
        try:
            setattr(bot, name, _wrap(name, orig))
            n += 1
        except Exception:
            logger.debug("ttl hook %s 略過", name, exc_info=True)
    if n:
        logger.info("tg_message_ttl 已掛 Bot send hook ×%s", n)
    return n > 0


def start_message_ttl_guard(
    *,
    db_path: str = "",
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    ttl_sec: float = DEFAULT_TTL_SEC,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
) -> bool:
    """背景每 N 分節流清過期 Bot 訊。開機呼叫一次即可。"""
    global _started
    if not _enabled():
        return False
    with _lock:
        if _started:
            return False
        _started = True

    path = ensure_table(db_path)
    interval = max(60.0, float(interval_sec))

    def _loop():
        time.sleep(20)
        while True:
            try:
                purge_expired(
                    db_path=path,
                    ttl_sec=ttl_sec,
                    max_per_run=max_per_run,
                    sleep_sec=sleep_sec,
                )
            except Exception:
                logger.exception("tg_message_ttl 背景 purge 失敗")
            time.sleep(interval)

    threading.Thread(target=_loop, name="tg-msg-ttl", daemon=True).start()
    logger.info(
        "tg_message_ttl 已排程：TTL %.0fh、每 %.0f 分最多刪 %s 則、間隔 %.2fs；"
        "LOADING／busy 進行中不刪；不擋查股",
        float(ttl_sec) / 3600.0,
        interval / 60.0,
        int(max_per_run),
        float(sleep_sec),
    )
    return True


def reset_for_tests() -> None:
    """單測用：清啟動旗標。"""
    global _started
    with _lock:
        _started = False
        _hooked_bots.clear()
