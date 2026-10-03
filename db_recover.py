# -*- coding: utf-8 -*-
"""行情庫損毀／wal-shm 錯位時的復原。

碟滿後 quick_check 失敗會把 wayne_market.db 搬成 .corrupt-*。
若只搬 .db、留下 -wal／-shm，Release 裝回後會套到舊 WAL → 永遠讀不到。
救回順序：清 sidecar → 可開且 biaoke≥1700 的 .corrupt-* → 再 Release。
不准刪私人表／silent 落檔／官方 OHLC（整檔搬移或整檔覆蓋，不做 DELETE）。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger("WayneBot.db_recover")

# 與 biaoke_archive.ARCHIVE_BASELINE_N 對齊；避免循環 import 寫死常數。
MIN_BIAOKE_RESTORE = 1700


def sidecar_paths(db_path: str) -> Tuple[str, str]:
    return f"{db_path}-wal", f"{db_path}-shm"


def has_sidecars(db_path: str) -> bool:
    wal, shm = sidecar_paths(db_path)
    return os.path.isfile(wal) or os.path.isfile(shm)


def remove_sidecars(db_path: str) -> List[str]:
    """刪掉錯位的 -wal／-shm。回傳已刪路徑。"""
    removed: List[str] = []
    for side in sidecar_paths(db_path):
        if not os.path.isfile(side):
            continue
        try:
            os.remove(side)
            removed.append(side)
        except OSError:
            logger.exception("無法刪除 sidecar %s", side)
    return removed


def move_db_with_sidecars(src: str, dest: str) -> None:
    """把 .db 與同名 -wal／-shm 一起搬到 dest（SQLite 才認得出）。"""
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isfile(src):
        shutil.move(src, dest)
    for suffix in ("-wal", "-shm"):
        s = f"{src}{suffix}"
        d = f"{dest}{suffix}"
        if os.path.isfile(s):
            try:
                shutil.move(s, d)
            except OSError:
                logger.exception("搬移 sidecar 失敗 %s → %s，改刪", s, d)
                try:
                    os.remove(s)
                except OSError:
                    pass


def quarantine_db(db_path: str, *, tag: Optional[str] = None) -> Optional[str]:
    """把壞庫（含 sidecar）搬成 path.corrupt-TS。沒有本尊則只清 sidecar。"""
    if not os.path.isfile(db_path):
        remove_sidecars(db_path)
        return None
    stamp = tag or str(int(time.time()))
    dest = f"{db_path}.corrupt-{stamp}"
    # 避免撞名
    n = 0
    while os.path.exists(dest):
        n += 1
        dest = f"{db_path}.corrupt-{stamp}-{n}"
    move_db_with_sidecars(db_path, dest)
    # 正式路徑上不准留殘 sidecar
    remove_sidecars(db_path)
    return dest


def biaoke_post_count(db_path: str) -> int:
    """主文筆數（不含 reply）。讀不到回 0。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
            ).fetchone()
            if not hit:
                return 0
            row = conn.execute(
                "SELECT COUNT(*) FROM biaoke_posts "
                "WHERE IFNULL(kind,'post')!='reply'"
            ).fetchone()
            return int((row or [0])[0] or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def list_corrupt_candidates(db_path: str) -> List[str]:
    """同目錄下 path.corrupt-* 本尊（不含其 -wal／-shm）。"""
    parent = os.path.dirname(db_path) or "."
    base = os.path.basename(db_path)
    prefix = f"{base}.corrupt-"
    out: List[str] = []
    try:
        names = os.listdir(parent)
    except OSError:
        return []
    for name in names:
        if not name.startswith(prefix):
            continue
        if name.endswith("-wal") or name.endswith("-shm"):
            continue
        cand = os.path.join(parent, name)
        if os.path.isfile(cand):
            out.append(cand)
    return out


def best_corrupt_restore(
    db_path: str,
    *,
    min_biaoke: int = MIN_BIAOKE_RESTORE,
    quick_check=None,
) -> Optional[str]:
    """可 quick_check 且 biaoke 主文 ≥ min 的最佳 .corrupt-*。"""
    from import_health import db_quick_check_ok

    check = quick_check or (lambda p: db_quick_check_ok(p, min_bytes=1))
    ranked: List[Tuple[int, float, str]] = []
    for cand in list_corrupt_candidates(db_path):
        if not check(cand):
            continue
        n = biaoke_post_count(cand)
        if n < int(min_biaoke):
            continue
        try:
            mtime = os.path.getmtime(cand)
        except OSError:
            mtime = 0.0
        ranked.append((n, mtime, cand))
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return ranked[0][2]


def restore_corrupt_to_path(corrupt_path: str, db_path: str) -> bool:
    """把選定的 .corrupt-*（含 sidecar）移回正式路徑。"""
    if not corrupt_path or not os.path.isfile(corrupt_path):
        return False
    # 正式路徑若還有東西，先另存，避免蓋掉
    if os.path.isfile(db_path) or has_sidecars(db_path):
        quarantine_db(db_path)
    remove_sidecars(db_path)
    move_db_with_sidecars(corrupt_path, db_path)
    return os.path.isfile(db_path)


def install_release_db(
    db_path: str,
    *,
    url: Optional[str] = None,
    urlretrieve=None,
) -> bool:
    """下載 Release 到暫存、quick_check 通過才換上；換上前清 sidecar。"""
    import urllib.request

    from config import get_github_release_url
    from import_health import db_quick_check_ok

    retrieve = urlretrieve or urllib.request.urlretrieve
    release_url = url or get_github_release_url()
    tmpdir = tempfile.mkdtemp(prefix="wayne-db-")
    zpath = os.path.join(tmpdir, "db.zip")
    try:
        logger.info("下載公開 Release 行情庫（可能要幾分鐘）")
        retrieve(release_url, zpath)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmpdir)
        found = None
        for root, _, files in os.walk(tmpdir):
            for name in files:
                if name.endswith(".db"):
                    cand = os.path.join(root, name)
                    if found is None or os.path.getsize(cand) > os.path.getsize(found):
                        found = cand
        if not found:
            logger.warning("Release zip 內找不到 .db")
            return False
        if not db_quick_check_ok(found, min_bytes=1):
            logger.error("Release .db quick_check 失敗，拒裝")
            return False
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # 寫到同目錄暫存再 replace，縮短無庫窗口
        staging = f"{db_path}.staging-{int(time.time())}"
        shutil.copy2(found, staging)
        if not db_quick_check_ok(staging, min_bytes=1):
            logger.error("staging quick_check 失敗，拒裝")
            try:
                os.remove(staging)
            except OSError:
                pass
            return False
        if os.path.isfile(db_path) or has_sidecars(db_path):
            quarantine_db(db_path)
        remove_sidecars(db_path)
        os.replace(staging, db_path)
        remove_sidecars(db_path)
        logger.info("已安裝行情庫 %.0f MB", os.path.getsize(db_path) / 1e6)
        return db_quick_check_ok(db_path, min_bytes=1)
    except Exception:
        logger.exception("下載／安裝行情庫失敗")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ensure_market_db_recoverable(
    db_path: Optional[str] = None,
    *,
    min_biaoke: int = MIN_BIAOKE_RESTORE,
    allow_release: bool = True,
    urlretrieve=None,
) -> dict:
    """確保正式路徑可讀；優先救回含飆大底圖的 .corrupt-*。

    回傳狀態給測試／log：ok / source / biaoke_n / actions。
    """
    from config import get_db_path
    from import_health import db_quick_check_ok

    path = db_path or get_db_path()
    actions: List[str] = []
    result = {
        "ok": False,
        "path": path,
        "source": "",
        "biaoke_n": 0,
        "actions": actions,
    }

    def _ok() -> bool:
        return bool(path and os.path.isfile(path) and db_quick_check_ok(path, min_bytes=1))

    # 1) 已可讀且飆大底圖夠 → 完成
    if _ok():
        n = biaoke_post_count(path)
        if n >= int(min_biaoke):
            result.update(ok=True, source="current", biaoke_n=n)
            return result
        actions.append("current_ok_low_biaoke")
    else:
        # 2) 錯位 wal/shm：先清再驗
        if os.path.isfile(path) and has_sidecars(path):
            removed = remove_sidecars(path)
            if removed:
                actions.append("stripped_sidecars")
            if _ok():
                n = biaoke_post_count(path)
                if n >= int(min_biaoke):
                    result.update(ok=True, source="sidecar_strip", biaoke_n=n)
                    return result
                actions.append("sidecar_strip_ok_low_biaoke")

    # 3) 優先從 .corrupt-* 救回（含 overlay）
    best = best_corrupt_restore(path, min_biaoke=min_biaoke)
    if best:
        actions.append(f"restore_corrupt:{os.path.basename(best)}")
        if restore_corrupt_to_path(best, path) and _ok():
            n = biaoke_post_count(path)
            result.update(ok=True, source="corrupt", biaoke_n=n)
            return result
        actions.append("restore_corrupt_failed")

    # 4) 現況已可讀（只是 biaoke 低、沒有更好 corrupt）→ 留給 seed，不准再 Release 蓋掉
    if _ok():
        n = biaoke_post_count(path)
        result.update(ok=True, source="current", biaoke_n=n)
        return result

    # 5) 壞本尊搬走（含 sidecar），再 Release
    if os.path.isfile(path) or has_sidecars(path):
        dest = quarantine_db(path)
        if dest:
            actions.append(f"quarantine:{os.path.basename(dest)}")
        else:
            actions.append("quarantine_sidecars_only")

    if not allow_release:
        result.update(ok=_ok(), source="none", biaoke_n=biaoke_post_count(path))
        return result

    if install_release_db(path, urlretrieve=urlretrieve):
        actions.append("release_install")
        n = biaoke_post_count(path)
        result.update(ok=True, source="release", biaoke_n=n)
        return result

    actions.append("release_failed")
    result.update(ok=False, source="none", biaoke_n=0)
    return result
