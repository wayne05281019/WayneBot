"""永久碟空間守衛：清可重建出圖快取，不准動官方柱／私人表／飆大必要材料。

目標結果：
- 開機立刻回收 `_lookup_memo`、scratch PNG／JPG、過期勝率 pair cache
- 排程週期掃：設 TTL／上限，滿前回收；日誌記清了多少 MB／檔數
- 從不刪 `wayne_market.db`、私人表、biaoke 語料／圖檔索引必要材料
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("WayneBot.disk_guard")

_TAIPEI = ZoneInfo("Asia/Taipei")

# 剩餘空間低於此值（MB）就全力清可重建檔
DEFAULT_MIN_FREE_MB = 400
# 週期掃間隔（秒）
DEFAULT_INTERVAL_SEC = 30 * 60
# scratch／memo 圖檔 TTL（秒）；過期就刪（可重建）
DEFAULT_CHART_TTL_SEC = 6 * 60 * 60
# wr_pair_cache 保留最近幾個台北曆日（含今天）
DEFAULT_PAIR_CACHE_KEEP_DAYS = 2
# charts 根目錄圖檔總量上限（MB）；超過就依 mtime 刪最舊
DEFAULT_CHARTS_CAP_MB = 800

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
# 不准動的相對路徑片段（飆大必要材料／官方庫）
_PROTECTED_NAME_FRAGMENTS = (
    "wayne_market.db",
    "archive_1709",
    "archive_club",
    "biaoke",
    "corpus",
)

_started = False
_lock = threading.Lock()


def _now_taipei() -> datetime:
    return datetime.now(_TAIPEI)


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


def _is_protected(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    base = os.path.basename(low)
    if base.startswith("wayne_market.db"):
        return True
    for frag in _PROTECTED_NAME_FRAGMENTS:
        # charts 底下偶然檔名含 biaoke 字樣的 scratch（如 2330_biaoke_...png）可清；
        # 真正保護的是非 charts 樹、或明確 archive／corpus。
        if frag in ("biaoke",) and "/charts/" in low:
            continue
        if frag in low:
            return True
    return False


def _file_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def _unlink(path: str) -> float:
    """刪檔，回傳釋放的 MB。保護路徑跳過。"""
    if not path or _is_protected(path):
        return 0.0
    try:
        if not os.path.isfile(path):
            return 0.0
        mb = _file_mb(path)
        os.unlink(path)
        return mb
    except OSError:
        return 0.0


def _iter_files(root: str) -> Iterable[str]:
    if not root or not os.path.isdir(root):
        return []
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 不准走進非出圖材料的保護目錄名
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower()
            not in ("archive_1709", "archive_club", "corpus", ".git")
        ]
        for name in filenames:
            out.append(os.path.join(dirpath, name))
    return out


def _purge_tree_files(root: str, *, older_than: Optional[float] = None) -> Tuple[int, float]:
    """刪 root 下檔案；older_than 為 epoch 秒，只刪更舊的。回傳 (n, mb)。"""
    n = 0
    mb = 0.0
    if not root or not os.path.isdir(root):
        return n, mb
    for path in _iter_files(root):
        if _is_protected(path):
            continue
        if older_than is not None:
            try:
                if os.path.getmtime(path) >= older_than:
                    continue
            except OSError:
                continue
        freed = _unlink(path)
        if freed > 0:
            n += 1
            mb += freed
    # 清空目錄（由深到淺）
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            if dirpath == root:
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass
    except OSError:
        pass
    return n, mb


def _purge_lookup_memo(charts_dir: str) -> Tuple[int, float]:
    memo = os.path.join(charts_dir, "_lookup_memo")
    return _purge_tree_files(memo)


def _purge_scratch_images(
    charts_dir: str,
    *,
    ttl_sec: float,
    now: Optional[float] = None,
    all_images: bool = False,
) -> Tuple[int, float]:
    """清 charts 根層與子目錄的可重建圖；保留 marks 小檔、保護路徑。"""
    n = 0
    mb = 0.0
    if not charts_dir or not os.path.isdir(charts_dir):
        return n, mb
    now_ts = now or time.time()
    if all_images:
        cutoff = now_ts + 1.0
    else:
        cutoff = now_ts - max(60.0, float(ttl_sec))
    skip_dirs = {"_lookup_memo", "wr_pair_cache", "marks"}
    for name in os.listdir(charts_dir):
        path = os.path.join(charts_dir, name)
        if name in skip_dirs:
            continue
        if os.path.isdir(path):
            for fp in _iter_files(path):
                if not fp.lower().endswith(_IMAGE_SUFFIXES):
                    continue
                if _is_protected(fp):
                    continue
                try:
                    if os.path.getmtime(fp) >= cutoff:
                        continue
                except OSError:
                    continue
                freed = _unlink(fp)
                if freed > 0:
                    n += 1
                    mb += freed
            continue
        if not name.lower().endswith(_IMAGE_SUFFIXES):
            continue
        if _is_protected(path):
            continue
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
        except OSError:
            continue
        freed = _unlink(path)
        if freed > 0:
            n += 1
            mb += freed
    return n, mb


def _purge_old_pair_cache(
    charts_dir: str, *, keep_days: int, today: Optional[datetime] = None
) -> Tuple[int, float]:
    """刪 wr_pair_cache 裡超過保留日的日資料夾。"""
    n = 0
    mb = 0.0
    root = os.path.join(charts_dir, "wr_pair_cache")
    if not os.path.isdir(root):
        return n, mb
    base = today or _now_taipei()
    keep = set()
    for i in range(max(1, int(keep_days))):
        keep.add((base - timedelta(days=i)).strftime("%Y-%m-%d"))
        keep.add((base - timedelta(days=i)).strftime("%Y%m%d"))
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        day_name = os.path.basename(dirpath)
        # 日資料夾名是 YYYY-MM-DD 或 YYYYMMDD
        is_day = (
            len(day_name) == 10
            and day_name[4:5] == "-"
            and day_name[7:8] == "-"
        ) or (len(day_name) == 8 and day_name.isdigit())
        if not is_day:
            continue
        if day_name in keep:
            continue
        for fn in filenames:
            freed = _unlink(os.path.join(dirpath, fn))
            if freed > 0:
                n += 1
                mb += freed
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass
    return n, mb


def _enforce_charts_cap_mb(charts_dir: str, *, cap_mb: float) -> Tuple[int, float]:
    """圖檔總量超過上限時，依 mtime 刪最舊可重建圖。"""
    n = 0
    mb = 0.0
    if not charts_dir or not os.path.isdir(charts_dir):
        return n, mb
    files: List[Tuple[float, str, float]] = []
    total = 0.0
    for path in _iter_files(charts_dir):
        if _is_protected(path):
            continue
        if not path.lower().endswith(_IMAGE_SUFFIXES):
            continue
        # marks 小 GIF 留著
        if "/marks/" in path.replace("\\", "/"):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        size_mb = st.st_size / (1024 * 1024)
        total += size_mb
        files.append((st.st_mtime, path, size_mb))
    if total <= float(cap_mb):
        return n, mb
    files.sort(key=lambda x: x[0])  # oldest first
    for _mtime, path, size_mb in files:
        if total <= float(cap_mb):
            break
        freed = _unlink(path)
        if freed > 0:
            n += 1
            mb += freed
            total -= size_mb
    return n, mb


def _try_wal_checkpoint(db_path: str) -> str:
    """盡量截 WAL；失敗不擋主流程。不准 VACUUM 硬撞碟滿。"""
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
    """僅當剩餘空間明顯大於 DB 體積時才 VACUUM（否則會更滿）。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
    try:
        db_mb = os.path.getsize(db_path) / (1024 * 1024)
    except OSError:
        return "skip"
    # 需要大約一份 DB 的暫存空間
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
    pair_keep_days: int = DEFAULT_PAIR_CACHE_KEEP_DAYS,
    cap_mb: float = DEFAULT_CHARTS_CAP_MB,
    aggressive: bool = False,
) -> Dict[str, Any]:
    """清可重建出圖快取。aggressive=True 時 memo／scratch 不看 TTL 全清。"""
    charts_dir = charts_dir or ""
    stats: Dict[str, Any] = {
        "charts_dir": charts_dir,
        "files": 0,
        "mb": 0.0,
        "parts": {},
    }
    if not charts_dir:
        return stats

    # memo＝查股暖路徑副本，可整夾重建
    n, mb = _purge_lookup_memo(charts_dir)
    stats["parts"]["lookup_memo"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _purge_scratch_images(
        charts_dir,
        ttl_sec=float(ttl_sec),
        now=time.time(),
        all_images=bool(aggressive),
    )
    stats["parts"]["scratch_images"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _purge_old_pair_cache(
        charts_dir, keep_days=1 if aggressive else pair_keep_days
    )
    stats["parts"]["wr_pair_cache"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _enforce_charts_cap_mb(
        charts_dir, cap_mb=float(cap_mb) * (0.5 if aggressive else 1.0)
    )
    stats["parts"]["cap_trim"] = {"files": n, "mb": round(mb, 2)}
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
    force: bool = False,
) -> Dict[str, Any]:
    """開機／週期：空間不足或 force 就清可重建檔；必要時 checkpoint／VACUUM。"""
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
    # force＝週期／開機必清可重建；空間過低才改全力（全 scratch）
    need = bool(force) or free < float(min_free_mb)
    aggressive = free < float(min_free_mb) * 0.5

    result: Dict[str, Any] = {
        "root": root,
        "before": before,
        "cleaned": False,
        "stats": {},
        "checkpoint": "skip",
        "vacuum": "skip",
    }
    if not need:
        result["after"] = before
        result["reason"] = "ok"
        return result

    stats = cleanup_rebuildable_charts(charts, aggressive=aggressive)
    result["cleaned"] = True
    result["stats"] = stats
    result["reason"] = (
        "low_free_aggressive"
        if aggressive
        else ("periodic" if force else "low_free")
    )

    mid = disk_usage_mb(root)
    result["checkpoint"] = _try_wal_checkpoint(dbp)
    # 仍緊才考慮 VACUUM
    free_mid = float(mid.get("free") or 0.0)
    if free_mid < float(min_free_mb):
        result["vacuum"] = _try_vacuum_if_room(dbp, free_mb=free_mid)
    after = disk_usage_mb(root)
    result["after"] = after
    result["freed_mb_approx"] = round(
        float(after.get("free") or 0.0) - float(before.get("free") or 0.0), 2
    )
    logger.info(
        "磁碟守衛：free %.1f→%.1f MB，清 %s 檔／%.2f MB（%s）checkpoint=%s vacuum=%s",
        before.get("free"),
        after.get("free"),
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
) -> None:
    """背景週期掃；開機呼叫一次即可。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    interval = max(60.0, float(interval_sec))

    def _loop():
        # 開機腳步稍讓 /live 先穩
        time.sleep(5)
        while True:
            try:
                ensure_disk_headroom(min_free_mb=min_free_mb, force=True)
            except Exception:
                logger.exception("磁碟守衛週期失敗")
            time.sleep(interval)

    threading.Thread(target=_loop, name="disk-guard", daemon=True).start()
    logger.info(
        "磁碟守衛已排程：每 %.0f 分清可重建出圖快取（下限 %.0f MB）",
        interval / 60.0,
        float(min_free_mb),
    )
