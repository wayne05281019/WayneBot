"""永久碟空間守衛：只刪白名單內可重建出圖快取／暫存。

使用者鎖死（2026-10-03；2026-10-04 加嚴達標）：
- 安全線：5GB 永久碟隨時保留約 2～3GB 空位（目標 free ≥ 2.5GB；下限 2GB）
- 可刪：`charts/_lookup_memo`、`charts/wr_pair_cache`、
  `charts/` 根層臨時 PNG／JPG（unique_chart_path scratch）
  1) ＞24h 先刪（TTL 維持 24h）
  2) 若 free 仍＜目標 2.5GB，再清更近的白名單可重建檔直到 ≥2.5GB（或白名單空）
- 絕對不准刪：靜默對質／默默落檔、持股、觀察、AI倉、pending、tg 私人狀態、
  官方柱、飆大必要材料、archive_1709、wayne_market.db、.corrupt-*；
  偉權與哥哥兩人資料都留

做法：路徑白名單鎖死；從不對 SQLite 下 DELETE／DROP；VACUUM／checkpoint 只回收空間不刪列。
不准動 .corrupt-*（可能是唯一可 salvage 備份）。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("WayneBot.disk_guard")

# 5GB 永久碟：下限 2GB；目標 2.5GB（使用者 2026-10-03 鎖死）
DEFAULT_MIN_FREE_MB = 2000
DEFAULT_TARGET_FREE_MB = 2500
# 週期掃間隔（秒）：below_target 時更勤清近窗白名單（2026-10-04 30→15 分）
DEFAULT_INTERVAL_SEC = 15 * 60
# 可重建出圖快取／暫存：超過 24 小時就刪（使用者鎖死；勿低於 24h）
DEFAULT_CHART_TTL_SEC = 24 * 60 * 60
# 白名單圖檔總量上限（MB）；超過就依 mtime 刪最舊白名單檔（2026-10-04 800→400）
DEFAULT_CHARTS_CAP_MB = 400

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


def disk_health_fields(
    *,
    data_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> Dict[str, Any]:
    """給 /health：disk free／下限／目標／警訊。便宜、不碰 SQLite 列。

    不把 serving 變紅（Render 會重開，重開修不了碟滿）；欄位一查就知道。
    """
    try:
        from config import get_db_path
    except Exception:
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
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
        alert_zh = f"碟即將滿：free {free:.0f}MB＜下限一半（{min_free * 0.5:.0f}MB）"
    elif free < min_free:
        alert = "below_floor"
        alert_zh = f"碟空位不足：free {free:.0f}MB＜下限 {min_free:.0f}MB"
    elif free < target:
        alert = "below_target"
        alert_zh = f"碟空位偏低：free {free:.0f}MB＜目標 {target:.0f}MB"
    else:
        alert = "ok"
        alert_zh = ""
    return {
        "disk_free_mb": free,
        "disk_used_mb": float(usage.get("used") or 0.0),
        "disk_total_mb": float(usage.get("total") or 0.0),
        "disk_min_free_mb": min_free,
        "disk_target_free_mb": target,
        "disk_ok": free >= min_free,
        "disk_alert": alert,
        "disk_alert_zh": alert_zh,
    }


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
                if os.path.getmtime(path) >= older_than:
                    continue
            except OSError:
                continue
        elif not all_files and older_than is None:
            continue
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _purge_allowlisted_until_free(
    charts_dir: str,
    root: str,
    *,
    want_free_mb: float,
    disk_usage_fn=None,
) -> Tuple[int, float]:
    """free 仍不足時，依 mtime 從舊到新清白名單，直到 free ≥ want 或白名單空。"""
    usage_fn = disk_usage_fn or disk_usage_mb
    n = 0
    mb = 0.0
    files: List[Tuple[float, str]] = []
    for path in _iter_allowlisted_files(charts_dir):
        try:
            files.append((os.path.getmtime(path), path))
        except OSError:
            continue
    files.sort(key=lambda x: x[0])
    for _mtime, path in files:
        free = float(usage_fn(root).get("free") or 0.0)
        if free >= float(want_free_mb):
            break
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _enforce_allowlist_cap_mb(charts_dir: str, *, cap_mb: float) -> Tuple[int, float]:
    """只對白名單檔做容量上限。"""
    n = 0
    mb = 0.0
    files: List[Tuple[float, str, float]] = []
    total = 0.0
    for path in _iter_allowlisted_files(charts_dir):
        try:
            st = os.stat(path)
        except OSError:
            continue
        size_mb = st.st_size / (1024 * 1024)
        total += size_mb
        files.append((st.st_mtime, path, size_mb))
    if total <= float(cap_mb):
        return n, mb
    files.sort(key=lambda x: x[0])
    for _mtime, path, size_mb in files:
        if total <= float(cap_mb):
            break
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
            total -= size_mb
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
    """有足夠剩餘才 VACUUM（不刪列，只重整檔）。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
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
) -> Dict[str, Any]:
    """只清白名單可重建出圖快取。

    1) 預設＞24h；aggressive 時白名單全清
    2) 若 free 仍＜目標（2.5GB），再清更近的白名單直到 ≥target 或白名單空
       （含 below_target：2GB≤free＜2.5GB；舊版只在＜2GB 才清近窗＝達不成目標）
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

    # 規則 2：TTL／cap 後 free 仍＜目標 → 繼續清白名單近窗，拉回 ≥2.5GB
    free_now = float(usage_fn(probe).get("free") or 0.0)
    if free_now < float(target_free_mb):
        n, mb = _purge_allowlisted_until_free(
            charts_dir,
            probe,
            want_free_mb=float(target_free_mb),
            disk_usage_fn=usage_fn,
        )
        stats["parts"]["until_free"] = {
            "files": n,
            "mb": round(mb, 2),
            "want_free_mb": float(target_free_mb),
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
) -> Dict[str, Any]:
    """開機／週期：只清白名單；必要時 checkpoint／VACUUM（不刪私人列）。

    - free ＜ target（2.5GB）或 force → 先清＞24h 白名單＋cap
    - free 仍＜ target → 再清更近白名單直到 ≥ target 或白名單空
    - free ＜下限一半 → aggressive 一次清空白名單（仍只動白名單）
    - 從不刪 .corrupt-*／DB／私人／官方柱／飆大 archive
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
    below_target = free < target
    below_floor = free < min_free
    need = bool(force) or below_target
    # below_floor（＜2GB）或更危：一次清空白名單 scratch；否則 TTL＋until_free
    aggressive = below_floor

    result: Dict[str, Any] = {
        "root": root,
        "before": before,
        "cleaned": False,
        "stats": {},
        "checkpoint": "skip",
        "vacuum": "skip",
        "min_free_mb": min_free,
        "target_free_mb": target,
    }
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
    )
    result["cleaned"] = True
    result["stats"] = stats
    if aggressive:
        result["reason"] = "below_floor" if below_floor else "low_free_aggressive"
    elif force:
        result["reason"] = "periodic"
    else:
        result["reason"] = "below_target"

    mid = disk_usage_mb(root)
    result["checkpoint"] = _try_wal_checkpoint(dbp)
    free_mid = float(mid.get("free") or 0.0)
    # VACUUM 會暫吃約一倍 DB 空間；碟已緊時不准跑（曾見 free 2248→1868）。
    # 只在已達目標後才重整，且仍要有足夠剩餘。
    if free_mid >= target:
        result["vacuum"] = _try_vacuum_if_room(dbp, free_mb=free_mid)
    else:
        result["vacuum"] = "skip_below_target"
    after = disk_usage_mb(root)
    result["after"] = after
    result["freed_mb_approx"] = round(
        float(after.get("free") or 0.0) - float(before.get("free") or 0.0), 2
    )
    logger.info(
        "磁碟守衛：free %.1f→%.1f MB（目標 %.0f／下限 %.0f），白名單清 %s 檔／%.2f MB（%s）checkpoint=%s vacuum=%s",
        before.get("free"),
        after.get("free"),
        target,
        min_free,
        stats.get("files"),
        stats.get("mb"),
        result["reason"],
        result["checkpoint"],
        result["vacuum"],
    )
    return result


def start_disk_guard(
    *,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> None:
    """背景週期掃白名單；開機呼叫一次即可。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    interval = max(60.0, float(interval_sec))

    def _loop():
        time.sleep(5)
        while True:
            try:
                ensure_disk_headroom(
                    min_free_mb=min_free_mb,
                    target_free_mb=target_free_mb,
                    force=True,
                )
            except Exception:
                logger.exception("磁碟守衛週期失敗")
            time.sleep(interval)

    threading.Thread(target=_loop, name="disk-guard", daemon=True).start()
    logger.info(
        "磁碟守衛已排程：每 %.0f 分清白名單出圖快取（TTL 24h，cap %dMB，目標 %.0f MB，下限 %.0f MB）",
        interval / 60.0,
        int(DEFAULT_CHARTS_CAP_MB),
        float(target_free_mb),
        float(min_free_mb),
    )
