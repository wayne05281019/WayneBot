# 重活窗話筒提示：開始推「資料處理中，請稍後再用」給白名單兩人；
# 結束魔法刪訊。只服務最重負荷三窗（06:30 早報／16:30 融合／03:00–04:00 DC）。
# 輕量：不進 matplotlib、不掃全市場、不改買訊。Asia/Taipei。
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("WayneBotRunner")

BUSY_TEXT = "資料處理中，請稍後再用"
# 刪不掉時先改成幾乎空白再刪，避免永遠留 spam。
_EDIT_FALLBACK = "·"

KINDS = frozenset({"morning", "fuse", "dc_sf"})

_lock = threading.Lock()
# kind → {chat_id: message_id}
_active: Dict[str, Dict[str, int]] = {}


def _taipei_stamp() -> str:
    try:
        from config import taipei_stamp

        return str(taipei_stamp())
    except Exception:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _state_path(db_path: str = "") -> Path:
    """輕量 JSON：跟行情庫同碟，Crash 後下一窗仍能清掉殘訊。"""
    raw = str(db_path or "").strip()
    if not raw:
        try:
            from config import get_db_path

            raw = str(get_db_path() or "").strip()
        except Exception:
            raw = ""
    if raw:
        parent = Path(raw).resolve().parent
    else:
        parent = Path(os.getenv("WAYNE_CACHE_DIR") or "/tmp")
    parent.mkdir(parents=True, exist_ok=True)
    return parent / "busy_window_notice.json"


def _may_push() -> bool:
    """GHA／測試／無 token 不准寄。重活提示跟早報同一把推播閘。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # 單測可開 WAYNE_BUSY_NOTICE_TEST=1 測真路徑（仍 mock HTTP）
        if str(os.getenv("WAYNE_BUSY_NOTICE_TEST") or "").strip() not in (
            "1",
            "true",
            "yes",
        ):
            return False
    raw = (os.getenv("WAYNE_SCREEN_NOTIFY") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _token() -> str:
    try:
        from config import get_telegram_token

        return str(get_telegram_token() or "").strip()
    except Exception:
        return str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_ids() -> List[str]:
    try:
        from config import allowed_telegram_uids

        return [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    except Exception:
        return []


def _tg_api(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=12,
        )
        if resp is None:
            return {}
        try:
            return resp.json() if resp.content else {}
        except Exception:
            return {"ok": False, "status_code": getattr(resp, "status_code", 0)}
    except Exception as e:
        logger.warning("busy_window tg %s 失敗：%s", method, e)
        return {}


def _load_file(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_file(path: Path, payload: Dict[str, Any]) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        logger.debug("busy_window 狀態檔寫失敗", exc_info=True)


def _clear_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        logger.debug("busy_window 狀態檔刪失敗", exc_info=True)


def is_busy_window_active(*, db_path: str = "") -> bool:
    """話筒／web 輕量查：重活進行中？只讀小 JSON，不碰行情庫。"""
    with _lock:
        if _active:
            return True
    data = _load_file(_state_path(db_path))
    msgs = data.get("messages") if isinstance(data, dict) else None
    return bool(isinstance(msgs, dict) and msgs)


def active_busy_kind(*, db_path: str = "") -> str:
    with _lock:
        if _active:
            return next(iter(_active.keys()))
    data = _load_file(_state_path(db_path))
    return str((data or {}).get("kind") or "").strip()


def active_message_pairs(*, db_path: str = "") -> List[Tuple[str, int]]:
    """進行中重活提示的 (chat_id, message_id)；給 tg_message_ttl 略過誤刪。"""
    out: List[Tuple[str, int]] = []
    seen = set()

    def _add(cid: Any, mid: Any) -> None:
        try:
            key = (str(cid), int(mid))
        except (TypeError, ValueError):
            return
        if not key[0] or key[1] <= 0 or key in seen:
            return
        seen.add(key)
        out.append(key)

    with _lock:
        for msgs in (_active or {}).values():
            if not isinstance(msgs, dict):
                continue
            for cid, mid in msgs.items():
                _add(cid, mid)
    data = _load_file(_state_path(db_path))
    raw = (data or {}).get("messages") or {}
    if isinstance(raw, dict):
        for cid, mid in raw.items():
            _add(cid, mid)
    return out


def _delete_one(token: str, chat_id: str, message_id: int) -> bool:
    mid = int(message_id or 0)
    if not mid:
        return True
    gone = _tg_api(
        token,
        "deleteMessage",
        {"chat_id": chat_id, "message_id": mid},
    )
    if gone.get("ok"):
        return True
    # 刪失敗：先改成幾乎空白再刪，不准永遠留 spam。
    _tg_api(
        token,
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": mid,
            "text": _EDIT_FALLBACK,
            "disable_web_page_preview": True,
        },
    )
    gone2 = _tg_api(
        token,
        "deleteMessage",
        {"chat_id": chat_id, "message_id": mid},
    )
    if gone2.get("ok"):
        return True
    logger.warning(
        "busy_window 刪訊仍失敗 chat=%s mid=%s err=%s",
        chat_id,
        mid,
        (gone2 or gone or {}).get("description")
        or (gone2 or gone or {}).get("status_code"),
    )
    return False


def clear_busy_notices(
    *,
    db_path: str = "",
    token: str = "",
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """盡力清掉殘留提示（開機／下一窗開始前）。"""
    tok = str(token or _token()).strip()
    path = _state_path(db_path)
    stats = {"deleted": 0, "failed": 0, "kinds": []}
    with _lock:
        mem = dict(_active)
        if kinds:
            mem = {k: v for k, v in mem.items() if k in kinds}
        for kind, msgs in list(mem.items()):
            if tok:
                for cid, mid in list(msgs.items()):
                    if _delete_one(tok, str(cid), int(mid)):
                        stats["deleted"] += 1
                    else:
                        stats["failed"] += 1
            _active.pop(kind, None)
            stats["kinds"].append(kind)
    data = _load_file(path)
    file_msgs = data.get("messages") if isinstance(data, dict) else None
    file_kind = str((data or {}).get("kind") or "")
    if isinstance(file_msgs, dict) and file_msgs:
        if not kinds or file_kind in (kinds or []):
            if tok:
                for cid, mid in list(file_msgs.items()):
                    try:
                        m = int(mid)
                    except (TypeError, ValueError):
                        continue
                    if _delete_one(tok, str(cid), m):
                        stats["deleted"] += 1
                    else:
                        stats["failed"] += 1
            _clear_file(path)
            if file_kind and file_kind not in stats["kinds"]:
                stats["kinds"].append(file_kind)
    elif not _active:
        _clear_file(path)
    return stats


def start_busy_notice(
    kind: str,
    *,
    db_path: str = "",
    token: str = "",
    text: str = "",
) -> Dict[str, int]:
    """推給白名單每一人；回傳 {chat_id: message_id}。失敗的 chat 不進表。"""
    k = str(kind or "").strip()
    if k not in KINDS:
        logger.warning("busy_window 未知 kind=%s，略過", kind)
        return {}
    if not _may_push():
        return {}
    tok = str(token or _token()).strip()
    ids = _chat_ids()
    if not tok or not ids:
        return {}

    # 上一窗殘訊先清，不准堆 spam
    try:
        clear_busy_notices(db_path=db_path, token=tok)
    except Exception:
        logger.debug("busy_window 清殘略過", exc_info=True)

    body = str(text or BUSY_TEXT).strip() or BUSY_TEXT
    sent: Dict[str, int] = {}
    for cid in ids:
        res = _tg_api(
            tok,
            "sendMessage",
            {
                "chat_id": cid,
                "text": body,
                "disable_web_page_preview": True,
                "disable_notification": True,
            },
        )
        mid = int(((res.get("result") or {}).get("message_id") or 0) or 0)
        if res.get("ok") and mid:
            sent[str(cid)] = mid
            try:
                from tg_message_ttl import protect_message, record_outbound

                record_outbound(cid, mid, db_path=db_path, protect=True, kind=f"busy:{k}")
                protect_message(cid, mid, db_path=db_path, kind=f"busy:{k}")
            except Exception:
                pass
        else:
            logger.warning(
                "busy_window 推播失敗 kind=%s chat=%s err=%s",
                k,
                cid,
                (res or {}).get("description") or (res or {}).get("status_code"),
            )

    path = _state_path(db_path)
    with _lock:
        _active[k] = dict(sent)
    _save_file(
        path,
        {
            "kind": k,
            "started_at": _taipei_stamp(),
            "messages": sent,
            "text": body,
        },
    )
    logger.info(
        "busy_window 已推 kind=%s chats=%s/%s",
        k,
        len(sent),
        len(ids),
    )
    return dict(sent)


def finish_busy_notice(
    kind: str,
    *,
    db_path: str = "",
    token: str = "",
    messages: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """魔法刪：依 chat 各自 message_id 刪；刪失敗則改字再刪。"""
    k = str(kind or "").strip()
    tok = str(token or _token()).strip()
    path = _state_path(db_path)
    with _lock:
        mem = dict(_active.get(k) or {})
        if messages:
            for cid, mid in messages.items():
                try:
                    mem[str(cid)] = int(mid)
                except (TypeError, ValueError):
                    continue
        _active.pop(k, None)
    if not mem:
        data = _load_file(path)
        if str((data or {}).get("kind") or "") == k:
            raw_msgs = data.get("messages") or {}
            if isinstance(raw_msgs, dict):
                for cid, mid in raw_msgs.items():
                    try:
                        mem[str(cid)] = int(mid)
                    except (TypeError, ValueError):
                        continue

    stats = {"kind": k, "deleted": 0, "failed": 0}
    if tok and mem:
        for cid, mid in list(mem.items()):
            ok = _delete_one(tok, str(cid), int(mid))
            if ok:
                stats["deleted"] += 1
                try:
                    from tg_message_ttl import forget_outbound

                    forget_outbound(cid, mid, db_path=db_path)
                except Exception:
                    pass
            else:
                stats["failed"] += 1
                try:
                    from tg_message_ttl import unprotect_message

                    unprotect_message(cid, mid, db_path=db_path)
                except Exception:
                    pass
    # 本 kind 清完；若檔內仍是本 kind 就刪檔
    data = _load_file(path)
    if str((data or {}).get("kind") or "") == k:
        _clear_file(path)
    with _lock:
        still = bool(_active)
    if not still and str((data or {}).get("kind") or "") != k:
        # 別種進行中則保留檔；否則保險清
        if not _load_file(path).get("messages"):
            _clear_file(path)
    logger.info(
        "busy_window 收起 kind=%s deleted=%s failed=%s",
        k,
        stats["deleted"],
        stats["failed"],
    )
    return stats


@contextmanager
def busy_window(
    kind: str,
    *,
    db_path: str = "",
    token: str = "",
    enabled: bool = True,
) -> Iterator[Dict[str, int]]:
    """with busy_window('morning'): 重活本體。結束／例外都盡力刪訊。"""
    sent: Dict[str, int] = {}
    if enabled:
        try:
            sent = start_busy_notice(kind, db_path=db_path, token=token) or {}
        except Exception:
            logger.exception("busy_window 推播例外 kind=%s（不擋重活）", kind)
            sent = {}
    try:
        yield sent
    finally:
        if enabled or sent:
            try:
                finish_busy_notice(
                    kind, db_path=db_path, token=token, messages=sent or None
                )
            except Exception:
                logger.exception("busy_window 收起例外 kind=%s", kind)
