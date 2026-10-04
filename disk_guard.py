"""永久碟空間守衛：只刪白名單內可重建出圖快取／暫存。

使用者鎖死（2026-10-04 改口）：
- 白天：正常用；不准追高 free（舊 2.5GB／2GB 目標取消）
- 緊急：free ≈ 200～300MB 才強制清白名單可重建檔
- 每天台北 00:00：例行只清白名單（_lookup_memo／wr_pair_cache／根層 scratch）
- 絕對不准刪：靜默對質／默默落檔、持股、觀察、AI倉、pending、tg 私人狀態、
  官方柱、飆大必要材料、archive_1709、wayne_market.db、.corrupt-*；
  偉權與哥哥兩人資料都留
- 碟緊時不准 VACUUM（暫吃空間會更痛）
- 必要資料（DB＋必要 archive）持續成長：追 durable 用量趨勢，預估撐到緊急線還剩多久；
  跑道低（＜約 30 天或 free＜約 900MB）才推偉權＋哥哥兩支話筒，去重不日刷；
  訊息只講大概能撐多久／現在剩多少／建議考慮加購 Render 碟；不准自作主張買

做法：路徑白名單鎖死；從不對 SQLite 下 DELETE／DROP；checkpoint 可回收 WAL；
VACUUM 只在 free 夠寬裕時。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("WayneBot.disk_guard")

# 緊急下限：約 200～300MB 才白天強清（2026-10-04 使用者改口；取消 2GB／2.5GB 追趕）
DEFAULT_MIN_FREE_MB = 250
# 保留欄位相容／health 顯示；白天不准用它去 until_free 追趕
DEFAULT_TARGET_FREE_MB = 250
# 白天只做緊急巡檢；午夜另排
DEFAULT_INTERVAL_SEC = 30 * 60
# 可重建出圖快取／暫存：午夜例行全清白名單；白天緊急也全清白名單
DEFAULT_CHART_TTL_SEC = 24 * 60 * 60
DEFAULT_CHARTS_CAP_MB = 400
# VACUUM 至少要有這麼多 free 才考慮（遠高於緊急線）
_VACUUM_MIN_FREE_MB = 1500.0
# 跑道預警：free 低於約 800MB～1GB、或預估＜30 天撐到緊急線 → 推兩支話筒
DEFAULT_WARN_FREE_MB = 900.0
DEFAULT_RUNWAY_WARN_DAYS = 30.0
# durable 快照至少隔這麼久才再記一筆；估計至少要這段跨度才敢談趨勢
_RUNWAY_SNAPSHOT_MIN_GAP_SEC = 6 * 60 * 60
_RUNWAY_HISTORY_MAX = 60
_RUNWAY_MIN_SPAN_DAYS = 2.0
_RUNWAY_MIN_GROWTH_MB_PER_DAY = 0.5
_RUNWAY_STATE_NAME = "disk_runway_state.json"

# 只准清這些 charts 子目錄（相對 charts_dir）
ALLOW_CHART_SUBDIRS: Tuple[str, ...] = (
    "_lookup_memo",
    "wr_pair_cache",
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
# unique_chart_path：{code}_{kind}_{uid}_{pid}_{ms}_{seq}.png
_SCRATCH_BASENAME_RE = re.compile(
    r"^.+_.+_.+_\d+_\d+_\d+\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)

_started = False
_lock = threading.Lock()
_last_midnight_ymd = ""
_runway_lock = threading.Lock()


def _taipei_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        return datetime.now()


def disk_usage_mb(path: str) -> Dict[str, float]:
    """回傳 path 所在磁碟的 total/used/free（MB）。"""
    try:
        usage = shutil.disk_usage(path or ".")
    except OSError as exc:
        return {"total": 0.0, "used": 0.0, "free": 0.0, "error": str(exc)}
    return {
        "total": round(usage.total / (1024 * 1024), 1),
        "used": round(usage.used / (1024 * 1024), 1),
        "free": round(usage.free / (1024 * 1024), 1),
    }


def _runway_state_path(data_dir: str) -> str:
    root = data_dir or "."
    return os.path.join(root, _RUNWAY_STATE_NAME)


def _load_runway_state(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"snapshots": [], "last_alert": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError, TypeError):
        return {"snapshots": [], "last_alert": None}
    if not isinstance(raw, dict):
        return {"snapshots": [], "last_alert": None}
    snaps = raw.get("snapshots")
    if not isinstance(snaps, list):
        snaps = []
    return {"snapshots": snaps, "last_alert": raw.get("last_alert")}


def _save_runway_state(path: str, state: Dict[str, Any]) -> None:
    if not path:
        return
    parent = os.path.dirname(path) or "."
    try:
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        logger.exception("寫入碟跑道狀態失敗")


def measure_durable_mb(
    data_dir: str,
    charts_dir: str = "",
    db_path: str = "",
) -> Dict[str, float]:
    """量 durable（不可重建）用量：DB＋必要 archive／私人／官方柱等；排除白名單快取。"""
    root = data_dir or "."
    charts = charts_dir or os.path.join(root, "charts")
    dbp = db_path or os.path.join(root, "wayne_market.db")
    durable = 0.0
    rebuildable = 0.0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # 不進 .git 之類
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for name in filenames:
                fp = os.path.join(dirpath, name)
                try:
                    sz = os.path.getsize(fp) / (1024 * 1024)
                except OSError:
                    continue
                if charts and is_allowlisted_deletable(fp, charts):
                    rebuildable += sz
                else:
                    durable += sz
    except OSError:
        pass
    # DB 可能在 root 外；補上
    for extra in (dbp, dbp + "-wal", dbp + "-shm"):
        if not extra or not os.path.isfile(extra):
            continue
        ap = _norm(extra)
        if ap.startswith(_norm(root).rstrip("/") + "/") or ap == _norm(root):
            continue
        durable += _file_mb(extra)
    return {
        "durable_mb": round(durable, 2),
        "rebuildable_mb": round(rebuildable, 2),
    }


def _runway_free_bucket(free_mb: float, warn_free_mb: float, min_free_mb: float) -> str:
    free = float(free_mb)
    if free < float(min_free_mb):
        return "emergency"
    if free < float(warn_free_mb) * 0.6:
        return "lt_warn60"
    if free < float(warn_free_mb):
        return "lt_warn"
    return "ok"


def _runway_days_bucket(days: Optional[float]) -> str:
    if days is None:
        return "unknown"
    d = float(days)
    if d < 7:
        return "lt7"
    if d < 14:
        return "lt14"
    if d < 30:
        return "lt30"
    return "ok"


def estimate_disk_runway(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    warn_free_mb: float = DEFAULT_WARN_FREE_MB,
    warn_days: float = DEFAULT_RUNWAY_WARN_DAYS,
    record: bool = True,
    now_ts: Optional[float] = None,
    disk_usage_fn=None,
) -> Dict[str, Any]:
    """追 durable 成長、估撐到緊急線還剩多久；趨勢弱／未知就明講，不准假精準。"""
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    charts = charts_dir or get_charts_dir()
    root = data_dir or os.path.dirname(dbp) or os.path.dirname(charts) or "."
    usage_fn = disk_usage_fn or disk_usage_mb
    usage = usage_fn(root)
    free = float(usage.get("free") or 0.0)
    total = float(usage.get("total") or 0.0)
    min_free = float(min_free_mb)
    warn_free = float(warn_free_mb)
    warn_d = float(warn_days)
    ts = float(now_ts if now_ts is not None else time.time())
    sizes = measure_durable_mb(root, charts_dir=charts, db_path=dbp)
    durable = float(sizes.get("durable_mb") or 0.0)

    state_path = _runway_state_path(root)
    with _runway_lock:
        state = _load_runway_state(state_path)
        snaps: List[Dict[str, Any]] = [
            s for s in (state.get("snapshots") or []) if isinstance(s, dict)
        ]
        if record:
            last_ts = float(snaps[-1].get("ts") or 0.0) if snaps else 0.0
            if not snaps or (ts - last_ts) >= float(_RUNWAY_SNAPSHOT_MIN_GAP_SEC):
                snaps.append(
                    {
                        "ts": ts,
                        "durable_mb": durable,
                        "free_mb": round(free, 1),
                        "total_mb": round(total, 1),
                    }
                )
                if len(snaps) > int(_RUNWAY_HISTORY_MAX):
                    snaps = snaps[-int(_RUNWAY_HISTORY_MAX) :]
                state["snapshots"] = snaps
                _save_runway_state(state_path, state)

    growth_mb_per_day: Optional[float] = None
    trend = "unknown"
    runway_days: Optional[float] = None
    headroom = max(0.0, free - min_free)
    if len(snaps) >= 2:
        first = snaps[0]
        last = snaps[-1]
        span_sec = float(last.get("ts") or 0.0) - float(first.get("ts") or 0.0)
        span_days = span_sec / 86400.0 if span_sec > 0 else 0.0
        d_grow = float(last.get("durable_mb") or 0.0) - float(
            first.get("durable_mb") or 0.0
        )
        if span_days >= float(_RUNWAY_MIN_SPAN_DAYS):
            growth_mb_per_day = d_grow / span_days
            if growth_mb_per_day >= float(_RUNWAY_MIN_GROWTH_MB_PER_DAY):
                trend = "growing"
                runway_days = headroom / growth_mb_per_day
            elif growth_mb_per_day <= -float(_RUNWAY_MIN_GROWTH_MB_PER_DAY):
                trend = "shrinking"
                runway_days = None
            else:
                trend = "flat"
                runway_days = None
        else:
            trend = "short_history"

    need_warn = False
    reasons: List[str] = []
    if free < warn_free:
        need_warn = True
        reasons.append("low_free")
    if runway_days is not None and runway_days < warn_d:
        need_warn = True
        reasons.append("short_runway")
    if free < min_free:
        need_warn = True
        reasons.append("emergency")

    level = "ok"
    if need_warn:
        if free < min_free or (runway_days is not None and runway_days < 7):
            level = "critical"
        else:
            level = "warn"

    return {
        "root": root,
        "free_mb": round(free, 1),
        "total_mb": round(total, 1),
        "durable_mb": round(durable, 2),
        "rebuildable_mb": float(sizes.get("rebuildable_mb") or 0.0),
        "min_free_mb": min_free,
        "warn_free_mb": warn_free,
        "warn_days": warn_d,
        "headroom_mb": round(headroom, 1),
        "growth_mb_per_day": (
            round(growth_mb_per_day, 3) if growth_mb_per_day is not None else None
        ),
        "trend": trend,
        "runway_days": round(runway_days, 1) if runway_days is not None else None,
        "need_warn": need_warn,
        "level": level,
        "reasons": reasons,
        "snapshot_n": len(snaps),
        "free_bucket": _runway_free_bucket(free, warn_free, min_free),
        "days_bucket": _runway_days_bucket(runway_days),
        "state_path": state_path,
        "last_alert": (state.get("last_alert") if isinstance(state, dict) else None),
    }


def format_runway_alert_zh(est: Dict[str, Any]) -> str:
    """短中文：大概能撐多久、現在剩多少、建議考慮加購；不准自作主張買。"""
    free = float(est.get("free_mb") or 0.0)
    min_free = float(est.get("min_free_mb") or DEFAULT_MIN_FREE_MB)
    days = est.get("runway_days")
    trend = str(est.get("trend") or "unknown")
    if days is not None:
        d = float(days)
        if d < 1:
            span = "大概還能撐不到 1 天"
        elif d < 14:
            span = f"大概還能撐約 {d:.0f} 天"
        else:
            weeks = d / 7.0
            span = f"大概還能撐約 {d:.0f} 天（約 {weeks:.0f} 週）"
    elif trend in ("flat", "shrinking"):
        span = "必要資料成長趨勢偏弱／幾乎沒長，撐多久暫時估不準"
    elif trend == "short_history":
        span = "紀錄天數還不夠，撐多久暫時估不準"
    else:
        span = "成長趨勢不明，撐多久暫時估不準"
    return (
        f"⚠️ 永久碟預警：{span}。\n"
        f"現在剩餘約 {free:.0f}MB（緊急線約 {min_free:.0f}MB）。\n"
        f"必要資料會一直長，建議考慮加購 Render 碟；我不會自己買。"
    )


def _runway_alert_signature(est: Dict[str, Any]) -> str:
    return f"{est.get('level')}|{est.get('free_bucket')}|{est.get('days_bucket')}"


def _send_family_plain(text: str) -> int:
    """推偉權＋哥哥兩支話筒；pytest／無 token 略過。"""
    if not text:
        return 0
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    if os.environ.get("WAYNE_DISK_RUNWAY_NOTIFY", "1").strip() in ("0", "false", "no"):
        return 0
    try:
        from config import allowed_telegram_uids, get_telegram_token
    except Exception:
        return 0
    token = get_telegram_token()
    uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    if not token or not uids:
        logger.warning("碟跑道預警沒有 token 或白名單，略過")
        return 0
    import requests

    n = 0
    for cid in uids:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if int(getattr(resp, "status_code", 0) or 0) == 200:
                n += 1
            else:
                logger.error(
                    "碟跑道預警 Telegram %s", getattr(resp, "status_code", "?")
                )
        except Exception:
            logger.exception("碟跑道預警失敗 uid 略")
    return n


def maybe_push_runway_alert(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    warn_free_mb: float = DEFAULT_WARN_FREE_MB,
    warn_days: float = DEFAULT_RUNWAY_WARN_DAYS,
    force: bool = False,
    send_fn=None,
    now_ts: Optional[float] = None,
    disk_usage_fn=None,
) -> Dict[str, Any]:
    """跑道低才推兩人；簽名相同／未惡化就不日刷。"""
    est = estimate_disk_runway(
        data_dir=data_dir,
        charts_dir=charts_dir,
        db_path=db_path,
        min_free_mb=min_free_mb,
        warn_free_mb=warn_free_mb,
        warn_days=warn_days,
        record=True,
        now_ts=now_ts,
        disk_usage_fn=disk_usage_fn,
    )
    out: Dict[str, Any] = {
        "estimate": est,
        "pushed": False,
        "sent": 0,
        "skipped": "",
        "text": "",
    }
    if not est.get("need_warn") and not force:
        out["skipped"] = "ok"
        return out
    sig = _runway_alert_signature(est)
    last = est.get("last_alert") if isinstance(est.get("last_alert"), dict) else None
    last_sig = str((last or {}).get("sig") or "")
    last_ts = float((last or {}).get("ts") or 0.0)
    ts = float(now_ts if now_ts is not None else time.time())
    # 同簽名且 20 小時內已推過 → 去重
    if not force and last_sig == sig and (ts - last_ts) < 20 * 3600:
        out["skipped"] = "dedupe"
        return out
    text = format_runway_alert_zh(est)
    out["text"] = text
    sender = send_fn or _send_family_plain
    sent = int(sender(text) or 0)
    out["sent"] = sent
    out["pushed"] = sent > 0 or send_fn is not None
    # 有自訂 send_fn（測）也記 last_alert，避免測試外漏推
    if out["pushed"] or force:
        state_path = str(est.get("state_path") or "")
        with _runway_lock:
            state = _load_runway_state(state_path)
            state["last_alert"] = {
                "ts": ts,
                "sig": sig,
                "level": est.get("level"),
                "free_mb": est.get("free_mb"),
                "runway_days": est.get("runway_days"),
                "ymd": _taipei_now().strftime("%Y%m%d"),
            }
            # 保留 snapshots
            if "snapshots" not in state:
                state["snapshots"] = []
            _save_runway_state(state_path, state)
        if sent:
            logger.info(
                "碟跑道預警已推 %d 人：free=%.0fMB runway=%s",
                sent,
                float(est.get("free_mb") or 0.0),
                est.get("runway_days"),
            )
    return out


def disk_health_fields(
    *,
    data_dir: str = "",
    db_path: str = "",
    charts_dir: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> Dict[str, Any]:
    """給 /health：disk free／緊急下限／警訊／跑道。便宜、不碰 SQLite 列。

    不把 serving 變紅（Render 會重開，重開修不了碟滿）；欄位一查就知道。
    """
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    charts = charts_dir or get_charts_dir()
    root = data_dir or os.path.dirname(dbp) or "."
    usage = disk_usage_mb(root)
    free = float(usage.get("free") or 0.0)
    min_free = float(min_free_mb)
    target = float(target_free_mb)
    if free <= 0 and usage.get("error"):
        alert = "unknown"
        alert_zh = "磁碟用量讀不到"
    elif free < min_free * 0.5:
        alert = "critical"
        alert_zh = f"碟即將滿：free {free:.0f}MB＜緊急線一半（{min_free * 0.5:.0f}MB）"
    elif free < min_free:
        alert = "below_floor"
        alert_zh = f"碟空位緊急：free {free:.0f}MB＜緊急線 {min_free:.0f}MB（將只清白名單快取）"
    elif free < float(DEFAULT_WARN_FREE_MB):
        alert = "runway_warn"
        alert_zh = f"碟空位偏低：free {free:.0f}MB＜預警線 {DEFAULT_WARN_FREE_MB:.0f}MB"
    else:
        alert = "ok"
        alert_zh = ""
    fields: Dict[str, Any] = {
        "disk_free_mb": free,
        "disk_used_mb": float(usage.get("used") or 0.0),
        "disk_total_mb": float(usage.get("total") or 0.0),
        "disk_min_free_mb": min_free,
        "disk_target_free_mb": target,
        "disk_warn_free_mb": float(DEFAULT_WARN_FREE_MB),
        "disk_ok": free >= min_free,
        "disk_alert": alert,
        "disk_alert_zh": alert_zh,
        "disk_runway_days": None,
        "disk_durable_mb": None,
        "disk_runway_trend": None,
    }
    try:
        est = estimate_disk_runway(
            data_dir=root,
            charts_dir=charts,
            db_path=dbp,
            min_free_mb=min_free,
            record=False,
        )
        fields["disk_runway_days"] = est.get("runway_days")
        fields["disk_durable_mb"] = est.get("durable_mb")
        fields["disk_runway_trend"] = est.get("trend")
        if alert == "ok" and est.get("need_warn"):
            fields["disk_alert"] = "runway_warn"
            fields["disk_alert_zh"] = format_runway_alert_zh(est).replace("\n", " ")
    except Exception as exc:
        fields["disk_runway_trend"] = f"err:{exc}"
    return fields


def _norm(path: str) -> str:
    return os.path.abspath(path or "").replace("\\", "/")


def is_allowlisted_deletable(path: str, charts_dir: str) -> bool:
    """路徑是否落在白名單可刪區（只認 charts 下 memo／pair_cache／根層 scratch）。"""
    if not path or not charts_dir:
        return False
    ap = _norm(path)
    root = _norm(charts_dir)
    if not ap.startswith(root.rstrip("/") + "/") and ap != root:
        return False
    # 絕對不准動 DB／WAL／SHM／.corrupt-*（可能是唯一可 salvage 備份）
    base = os.path.basename(ap).lower()
    if base.startswith("wayne_market.db"):
        return False
    if ".corrupt-" in base:
        return False
    # 飆大 archive／corpus 即使誤掛在 charts 下也不動
    low = ap.lower()
    for frag in ("archive_1709", "archive_club", "/corpus/", "corpus_index"):
        if frag in low:
            return False
    rel = ap[len(root) :].lstrip("/")
    if not rel:
        return False
    parts = rel.split("/")
    # 白名單子目錄整樹
    if parts[0] in ALLOW_CHART_SUBDIRS:
        return os.path.isfile(path)
    # 只准 charts 根層 scratch 圖，不准進 marks／其他子目錄
    if len(parts) == 1 and _SCRATCH_BASENAME_RE.match(parts[0]):
        return os.path.isfile(path)
    return False


def _file_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def _unlink_allowlisted(path: str, charts_dir: str) -> float:
    """只刪白名單檔；否則 0。"""
    if not is_allowlisted_deletable(path, charts_dir):
        return 0.0
    try:
        mb = _file_mb(path)
        os.unlink(path)
        return mb
    except OSError:
        return 0.0


def _iter_allowlisted_files(charts_dir: str) -> Iterable[str]:
    """只列白名單可刪檔。"""
    if not charts_dir or not os.path.isdir(charts_dir):
        return []
    out: List[str] = []
    # 1) 白名單子目錄
    for sub in ALLOW_CHART_SUBDIRS:
        root = os.path.join(charts_dir, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                if is_allowlisted_deletable(fp, charts_dir):
                    out.append(fp)
    # 2) charts 根層 scratch
    try:
        for name in os.listdir(charts_dir):
            fp = os.path.join(charts_dir, name)
            if os.path.isfile(fp) and is_allowlisted_deletable(fp, charts_dir):
                out.append(fp)
    except OSError:
        pass
    return out


def _rm_empty_allowlist_dirs(charts_dir: str) -> None:
    for sub in ALLOW_CHART_SUBDIRS:
        root = os.path.join(charts_dir, sub)
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, _dn, _fn in os.walk(root, topdown=False):
                if dirpath == root:
                    continue
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                except OSError:
                    pass
        except OSError:
            pass


def _purge_allowlisted(
    charts_dir: str,
    *,
    older_than: Optional[float] = None,
    all_files: bool = False,
) -> Tuple[int, float]:
    n = 0
    mb = 0.0
    for path in _iter_allowlisted_files(charts_dir):
        if not all_files and older_than is not None:
            try:
                if os.path.getmtime(path) >= float(older_than):
                    continue
            except OSError:
                continue
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _purge_allowlisted_until_free(
    charts_dir: str,
    probe: str,
    *,
    want_free_mb: float,
    disk_usage_fn=None,
) -> Tuple[int, float]:
    """緊急時：依 mtime 從舊到新清白名單，直到 free ≥ want 或白名單空。"""
    usage_fn = disk_usage_fn or disk_usage_mb
    n = 0
    mb = 0.0
    paths = sorted(
        _iter_allowlisted_files(charts_dir),
        key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0.0,
    )
    for path in paths:
        free = float(usage_fn(probe).get("free") or 0.0)
        if free >= float(want_free_mb):
            break
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _enforce_allowlist_cap_mb(charts_dir: str, *, cap_mb: float) -> Tuple[int, float]:
    paths = list(_iter_allowlisted_files(charts_dir))
    total = sum(_file_mb(p) for p in paths)
    if total <= float(cap_mb):
        return 0, 0.0
    paths.sort(key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0.0)
    n = 0
    mb = 0.0
    for path in paths:
        if total <= float(cap_mb):
            break
        size = _file_mb(path)
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
            total -= size
    return n, mb


def _try_wal_checkpoint(db_path: str) -> str:
    """截 WAL 回收空間；不准 DELETE 任何表。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        return "ok"
    except sqlite3.Error as exc:
        return f"fail:{exc}"


def _try_vacuum_if_room(db_path: str, *, free_mb: float) -> str:
    """有足夠剩餘才 VACUUM（不刪列，只重整檔）。碟緊一律 skip。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
    if float(free_mb) < float(_VACUUM_MIN_FREE_MB):
        return "skip_below_target"
    try:
        db_mb = os.path.getsize(db_path) / (1024 * 1024)
    except OSError:
        return "skip"
    if free_mb < db_mb * 1.15 + 50:
        return "skip_no_room"
    try:
        conn = sqlite3.connect(db_path, timeout=120)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        return "ok"
    except sqlite3.Error as exc:
        return f"fail:{exc}"


def cleanup_rebuildable_charts(
    charts_dir: str,
    *,
    ttl_sec: float = DEFAULT_CHART_TTL_SEC,
    cap_mb: float = DEFAULT_CHARTS_CAP_MB,
    aggressive: bool = False,
    root: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
    disk_usage_fn=None,
    chase_target: bool = False,
) -> Dict[str, Any]:
    """只清白名單可重建出圖快取。

    aggressive／午夜：白名單全清。
    否則：只清＞TTL；可選 cap。白天不准 chase_target 追高 free。
    """
    charts_dir = charts_dir or ""
    ttl = float(ttl_sec if ttl_sec is not None else DEFAULT_CHART_TTL_SEC)
    usage_fn = disk_usage_fn or disk_usage_mb
    probe = root or charts_dir or "."
    stats: Dict[str, Any] = {
        "charts_dir": charts_dir,
        "ttl_sec": ttl,
        "min_free_mb": float(min_free_mb),
        "target_free_mb": float(target_free_mb),
        "cap_mb": float(cap_mb),
        "allow_subdirs": list(ALLOW_CHART_SUBDIRS),
        "files": 0,
        "mb": 0.0,
        "parts": {},
    }
    if not charts_dir:
        return stats

    if aggressive:
        n, mb = _purge_allowlisted(charts_dir, all_files=True)
        stats["parts"]["allowlist_all"] = {"files": n, "mb": round(mb, 2)}
    else:
        cutoff = time.time() - max(60.0, ttl)
        n, mb = _purge_allowlisted(charts_dir, older_than=cutoff, all_files=False)
        stats["parts"]["allowlist_ttl"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _enforce_allowlist_cap_mb(
        charts_dir, cap_mb=float(cap_mb) * (0.5 if aggressive else 1.0)
    )
    stats["parts"]["cap_trim"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    # 白天取消 until_free 追趕；僅緊急／明確 chase 才用
    if chase_target:
        free_now = float(usage_fn(probe).get("free") or 0.0)
        want = float(min_free_mb)
        if free_now < want:
            n, mb = _purge_allowlisted_until_free(
                charts_dir,
                probe,
                want_free_mb=want,
                disk_usage_fn=usage_fn,
            )
            stats["parts"]["until_free"] = {
                "files": n,
                "mb": round(mb, 2),
                "want_free_mb": want,
                "free_before": free_now,
            }
            stats["files"] += n
            stats["mb"] += mb

    stats["mb"] = round(float(stats["mb"]), 2)
    return stats


def ensure_disk_headroom(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
    force: bool = False,
    mode: str = "",
) -> Dict[str, Any]:
    """開機／白天緊急／午夜例行：只清白名單；從不刪私人列。

    - daytime／boot：free ＜緊急線（~250MB）才強清白名單；不准追 2.5GB
    - midnight：例行全清白名單
    - force 且非午夜：等同緊急巡檢（仍只在 below 緊急線才清，除非 mode=midnight）
    - 碟緊不准 VACUUM
    """
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    charts = charts_dir or get_charts_dir()
    dbp = db_path or get_db_path()
    root = data_dir or os.path.dirname(dbp) or os.path.dirname(charts) or "."
    os.makedirs(charts, exist_ok=True)

    before = disk_usage_mb(root)
    free = float(before.get("free") or 0.0)
    min_free = float(min_free_mb)
    target = float(target_free_mb)
    mode_s = str(mode or "").strip().lower()
    is_midnight = mode_s == "midnight"
    below_emergency = free < min_free

    result: Dict[str, Any] = {
        "root": root,
        "before": before,
        "cleaned": False,
        "stats": {},
        "checkpoint": "skip",
        "vacuum": "skip",
        "min_free_mb": min_free,
        "target_free_mb": target,
        "mode": mode_s or ("midnight" if is_midnight else "daytime"),
    }

    if is_midnight:
        need = True
        aggressive = True
        reason = "midnight"
    elif below_emergency:
        need = True
        aggressive = True
        reason = "emergency"
    else:
        # 白天／開機：空間夠 → 不追趕、不清、不 VACUUM；仍記 durable 跑道並視需要預警
        result["after"] = before
        result["reason"] = "ok_daytime"
        result["freed_mb_approx"] = 0.0
        try:
            result["runway"] = maybe_push_runway_alert(
                data_dir=root,
                charts_dir=charts,
                db_path=dbp,
                min_free_mb=min_free,
            )
        except Exception:
            logger.exception("碟跑道預警失敗")
            result["runway"] = {"skipped": "error"}
        if force and not below_emergency:
            # force 也不准白天追高 free；只記一筆
            logger.info(
                "磁碟守衛：白天略過（free %.1f MB ≥ 緊急線 %.0f MB；不追高 free）",
                free,
                min_free,
            )
        return result

    if not need:
        result["after"] = before
        result["reason"] = "ok"
        return result

    stats = cleanup_rebuildable_charts(
        charts,
        aggressive=aggressive,
        root=root,
        min_free_mb=min_free,
        target_free_mb=target,
        disk_usage_fn=disk_usage_mb,
        chase_target=below_emergency and not is_midnight,
    )
    result["cleaned"] = True
    result["stats"] = stats
    result["reason"] = reason

    mid = disk_usage_mb(root)
    result["checkpoint"] = _try_wal_checkpoint(dbp)
    free_mid = float(mid.get("free") or 0.0)
    # 碟緊／剛緊急清完：不准 VACUUM
    if free_mid >= float(_VACUUM_MIN_FREE_MB):
        result["vacuum"] = _try_vacuum_if_room(dbp, free_mb=free_mid)
    else:
        result["vacuum"] = "skip_below_target"
    after = disk_usage_mb(root)
    result["after"] = after
    result["freed_mb_approx"] = round(
        float(after.get("free") or 0.0) - float(before.get("free") or 0.0), 2
    )
    try:
        result["runway"] = maybe_push_runway_alert(
            data_dir=root,
            charts_dir=charts,
            db_path=dbp,
            min_free_mb=min_free,
        )
    except Exception:
        logger.exception("碟跑道預警失敗")
        result["runway"] = {"skipped": "error"}
    logger.info(
        "磁碟守衛：free %.1f→%.1f MB（緊急線 %.0f），白名單清 %s 檔／%.2f MB（%s）checkpoint=%s vacuum=%s",
        before.get("free"),
        after.get("free"),
        min_free,
        stats.get("files"),
        stats.get("mb"),
        result["reason"],
        result["checkpoint"],
        result["vacuum"],
    )
    return result


def run_midnight_cache_purge(**kwargs) -> Dict[str, Any]:
    """台北午夜例行：只清白名單快取／scratch。"""
    return ensure_disk_headroom(mode="midnight", force=True, **kwargs)


def _seconds_until_taipei_midnight() -> float:
    now = _taipei_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    # 若剛好在 00:00～00:01，下一輪仍等明天，避免雙跑；呼叫端用 ymd 去重
    if now.hour == 0 and now.minute < 2:
        return max(30.0, (nxt - now).total_seconds())
    today_mid = now.replace(hour=0, minute=0, second=5, microsecond=0)
    if now < today_mid:
        return max(5.0, (today_mid - now).total_seconds())
    return max(30.0, (nxt - now).total_seconds())


def start_disk_guard(
    *,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> None:
    """背景：白天只巡緊急線＋跑道；台北 00:00 例行清白名單。開機呼叫一次即可。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    interval = max(60.0, float(interval_sec))

    def _emergency_loop():
        time.sleep(5)
        while True:
            try:
                ensure_disk_headroom(
                    min_free_mb=min_free_mb,
                    target_free_mb=target_free_mb,
                    force=False,
                    mode="daytime",
                )
            except Exception:
                logger.exception("磁碟守衛白天巡檢失敗")
            time.sleep(interval)

    def _midnight_loop():
        global _last_midnight_ymd
        time.sleep(8)
        while True:
            try:
                wait = _seconds_until_taipei_midnight()
                time.sleep(min(wait, 3600.0))
                now = _taipei_now()
                if now.hour != 0:
                    continue
                ymd = now.strftime("%Y%m%d")
                if ymd == _last_midnight_ymd:
                    time.sleep(60)
                    continue
                run_midnight_cache_purge(
                    min_free_mb=min_free_mb,
                    target_free_mb=target_free_mb,
                )
                _last_midnight_ymd = ymd
            except Exception:
                logger.exception("磁碟守衛午夜清快取失敗")
                time.sleep(60)

    threading.Thread(target=_emergency_loop, name="disk-guard-day", daemon=True).start()
    threading.Thread(target=_midnight_loop, name="disk-guard-midnight", daemon=True).start()
    logger.info(
        "磁碟守衛已排程：白天每 %.0f 分只看緊急線 %.0f MB＋跑道預警（free＜%.0fMB／＜%.0f天）；"
        "台北 00:00 例行清白名單（cap %dMB）；不追高 free；不自作主張加購",
        interval / 60.0,
        float(min_free_mb),
        float(DEFAULT_WARN_FREE_MB),
        float(DEFAULT_RUNWAY_WARN_DAYS),
        int(DEFAULT_CHARTS_CAP_MB),
    )
